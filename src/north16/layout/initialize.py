"""Inventory existing raw assets and reserve camera directories, without FFmpeg."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import tempfile

import yaml

from north16 import __version__
from north16.adapters.capture import discover
from north16.common.files import read_info, write_info, write_table
from north16.preprocess.index import SAMPLE_COLUMNS
from north16.resources import resource_root
from .paths import stream_path

SOURCE_COLUMNS = ("source_id", "raw_root_id", "source_namespace", "session_id", "source_relative_path",
                  "source_absolute_path", "sha256", "size_bytes", "sequence", "sensor", "camera", "state", "modified_ns")


class DatasetInitializer:
    def initialize(self, raw, output, *, segments=None, namespace="north16", session=None):
        raw = Path(raw).resolve(strict=True)
        output = Path(output).resolve()
        if output.exists():
            raise FileExistsError("初始化要求新目录；已有数据集不会被覆盖")
        if output == raw or output.is_relative_to(raw) or raw.is_relative_to(output):
            raise ValueError("原始目录和数据集必须分开")
        session = session or raw.name
        if not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) for value in (namespace, session)):
            raise ValueError("namespace/session仅接受安全的英文、数字、下划线或横线")
        if segments is None:
            segments = sorted(p.name for p in raw.iterdir() if p.is_dir() and
                              re.fullmatch(r"\d{4}(?:_\d{2}){5}_data", p.name))
        if not segments or len(set(segments)) != len(segments):
            raise ValueError("未发现受支持片段，或指定片段重复；其他布局需增加adapter")
        resources = resource_root()
        adapter = yaml.safe_load(resources.joinpath("configs/adapters/north16_capture_v1.yaml").read_text(encoding="utf-8"))
        # Register metadata only: do not read all raw bytes to compute checksums.
        assets = discover(raw, list(segments), adapter, namespace, session, checksum=False)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="north16_init_", dir=output.parent) as temp:
            stage = Path(temp) / "dataset"
            stage.mkdir()
            for name in ("protocol.txt", "classes.txt"):
                write_info(stage/name, read_info(resources.joinpath("templates/txt", name)))
            info = read_info(resources.joinpath("templates/txt/dataset_info.txt"))
            info.update(record_status="recorded", dataset_id=namespace, dataset_status="working",
                        dataset_version="working", camera_index="frames", camera_status="initialized",
                        source_registry="sources.txt", sample_count=0, converter_version=__version__,
                        reader_version=__version__, annotation_status="unlabeled", file_checksum="none")
            write_info(stage/"info.txt", info)
            sources = []
            for a in assets:
                sources.append(dict(source_id=a.source_id, raw_root_id=raw.name, source_namespace=namespace,
                                    session_id=session, source_relative_path=a.relative, source_absolute_path=str(a.path),
                                    sha256=a.digest, size_bytes=a.size, sequence=a.sequence, sensor=a.sensor,
                                    camera=a.camera, state="registered", modified_ns=a.modified_ns))
                sequence_info = stage/"sequences"/a.sequence/"info.txt"
                if not sequence_info.exists():
                    values = read_info(resources.joinpath("templates/txt/sequence_info.txt"))
                    values.update(record_status="recorded", sequence=a.sequence, segment_id=a.segment,
                                  source_relative_path=a.segment, source_namespace=namespace,
                                  session_id=session, raw_root_id=raw.name)
                    write_info(sequence_info, values)
                if a.sensor in ("visible", "infrared"):
                    folder = stage/stream_path(a.sequence,a.sensor,a.camera)
                    (folder/"images").mkdir(parents=True)
                    (folder/"meta").mkdir()
                    write_info(folder/"info.txt", dict(schema_version="north16_camera_v1", source_id=a.source_id,
                               source_sha256=a.digest, source_bytes=a.size, source_video_path=a.relative, sequence=a.sequence,
                               sensor=a.sensor, camera=a.camera, decode_status="pending", decoded_frame_count=0))
            write_table(stage/"sources.txt", SOURCE_COLUMNS, sources)
            write_table(stage/"samples.txt", SAMPLE_COLUMNS, [])
            write_info(stage/"sync/info.txt", dict(association_status="unverified"))
            (stage/"logs").mkdir()
            write_info(stage/"logs/initialization.txt", dict(raw_root=str(raw), session_id=session,
                       assets=len(assets), videos=sum(a.sensor in ("visible", "infrared") for a in assets),
                       decoding_performed="false", implementation_version=__version__))
            stage.rename(output)
        return dict(root=str(output), sources=len(assets), videos=sum(a.sensor in ("visible", "infrared") for a in assets),
                    sequences=sorted({a.sequence for a in assets}), images=0, masks=0)


def main(argv=None):
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--segments", nargs="+")
    parser.add_argument("--namespace", default="north16")
    parser.add_argument("--session")
    args = parser.parse_args(argv)
    print(json.dumps(DatasetInitializer().initialize(args.raw, args.output, segments=args.segments,
               namespace=args.namespace, session=args.session), ensure_ascii=False, indent=2))
