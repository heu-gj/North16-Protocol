"""Decode only registered camera streams; never process radar or annotations."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

import yaml

from north16 import __version__
from north16.adapters.capture import Asset
from north16.common.files import local_path, read_info, read_table, check_size, write_info
from north16.preprocess.camera import extract, probe, verify_stream
from north16.camera.sampling import estimated_count, normalize_interval, video_filter
from north16.preprocess.index import build_index
from north16.resources import resource_root
from north16.layout.paths import stream_path


class CameraBuilder:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        info = read_info(self.root/"info.txt")
        if info.get("dataset_status") != "working":
            raise ValueError("camera模块需要working数据集")
        self.info = info
        self.sources = read_table(local_path(self.root,info.get("source_registry","sources.txt")))

    def extract(self, *, sequences=None, sensor=None, cameras=None, ffmpeg="ffmpeg", ffprobe="ffprobe", interval=None, dry_run=False, progress=None):
        interval = normalize_interval(interval)
        if self.info.get("camera_index") != "frames":
            raise ValueError("旧数据集保留原build复现入口；新抽帧请先initialize，旧数据集仍可camera export")
        if sensor not in (None, "visible", "infrared"):
            raise ValueError("sensor必须是visible或infrared")
        sources = [r for r in self.sources if r["sensor"] in ("visible", "infrared") and
                   (not sequences or r["sequence"] in sequences) and (not sensor or r["sensor"] == sensor) and
                   (not cameras or r["camera"] in cameras)]
        if not sources:
            raise ValueError("没有匹配的已登记相机流")
        resources = resource_root()
        protocol = yaml.safe_load(resources.joinpath("configs/protocol.yaml").read_text(encoding="utf-8"))
        version = subprocess.check_output([ffmpeg, "-version"], text=True, encoding="utf-8", errors="replace").splitlines()[0]
        conversion = dict(version=__version__, ffmpeg=version, pixel_format="rgb24", filter="format=rgb24,showinfo",
                          fps_mode="passthrough", compression_level=3, frame_selection="all_decodable_source_frames")
        if interval is not None:
            conversion.update(filter=video_filter(interval), frame_selection="minimum_pts_interval", interval_seconds=interval, copyts=True)
        # Software-only upgrades must not force existing streams to be decoded again.
        settings = {k:v for k,v in conversion.items() if k != "version"}
        key = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
        compatible_keys = {key} | {
            hashlib.sha256(json.dumps(dict(conversion,version=v),sort_keys=True).encode()).hexdigest()
            for v in ("0.6.0","0.7.0","0.8.0","0.9.0","0.9.1","0.9.2","0.9.3",
                      "0.10.0","0.10.1","0.11.0","0.12.0","0.13.0",__version__)}
        # Validate all sources/stream placeholders and capacity before decoding.
        pending = []
        budget = 0
        stream_details = []
        for index,row in enumerate(sources,1):
            if progress:progress(dict(phase='preflight',stream_index=index,streams=len(sources),
                                     sequence=row['sequence'],sensor=row['sensor'],camera=row['camera']))
            path = Path(row["source_absolute_path"]).resolve(strict=True)
            check_size(path, row["size_bytes"])
            modified = path.stat().st_mtime_ns
            recorded = row.get("modified_ns")
            if recorded not in (None, "unknown", "") and modified != int(recorded):
                raise ValueError(f"原视频修改时间已变化：{path}")
            asset = Asset(path, row["source_relative_path"], row["source_id"], "disabled", int(row["size_bytes"]),
                          row["sequence"], row["source_relative_path"].split("/")[0], row["sensor"], row["camera"], modified)
            folder = self.root/stream_path(asset.sequence,asset.sensor,asset.camera)
            current = read_info(folder/"info.txt")
            if current["source_id"] != asset.source_id:
                raise ValueError("相机目录来源冲突")
            stream_key=key
            if current.get("decode_status") != "pending":
                if current.get("extraction_key") in compatible_keys:
                    stream_key=current["extraction_key"]
                verify_stream(folder, key=stream_key, source_id=asset.source_id)
            stream = probe(path, ffprobe)
            count = (estimated_count(stream, interval) if current.get("decode_status") == "pending"
                     else int(current["decoded_frame_count"]))
            stream_budget = 0
            if current.get("decode_status") == "pending":
                stream_budget = int(stream["width"])*int(stream["height"])*3*count*1.2
                budget += stream_budget
            stream_details.append(dict(sequence=asset.sequence, sensor=asset.sensor, camera=asset.camera,
                                       width=int(stream["width"]), height=int(stream["height"]),
                                       estimated_images=count, state=current.get("decode_status"),
                                       budget_bytes=int(stream_budget)))
            pending.append((row, asset, stream, stream_key))
        import shutil
        free = shutil.disk_usage(self.root).free
        if dry_run:
            return dict(status="preflight", decoding_performed=False, root=str(self.root),
                        streams=len(pending), sequences=sorted({a.sequence for _, a, _, _ in pending}),
                        sensors=sorted({a.sensor for _, a, _, _ in pending}),
                        interval_seconds=interval, frame_selection=conversion["frame_selection"],
                        budget_method="rgb24_uncompressed_plus_20_percent",
                        budget_bytes=int(budget), free_bytes=free,
                        budget_gib=round(budget/2**30, 3), free_gib=round(free/2**30, 3),
                        disk_sufficient_conservative=free >= budget, stream_details=stream_details)
        if free < budget:
            pending_streams = sum(r["state"] == "pending" for r in stream_details)
            raise ValueError(
                f"抽帧磁盘容量不足（保守预估）：需 {budget/2**30:.2f} GiB，"
                f"输出磁盘剩余 {free/2**30:.2f} GiB；选择 {len(pending)} 路视频，"
                f"其中 {pending_streams} 路待抽帧。预估按 RGB24 未压缩字节数 × 1.2，"
                "实际 PNG 可能更小。加 --dry-run 查看明细；可用 --sequences / --sensor / "
                "--cameras 缩小范围，或在新初始化目录使用 --interval 5 稀疏抽帧。")
        lock = self.root/".north16_build.lock"
        with lock.open("x", encoding="utf-8") as handle:
            handle.write("camera extract\n")
        run = self.root/"logs"/("camera_"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_")+uuid.uuid4().hex[:6])
        results = []
        try:
            run.mkdir(parents=True)
            for index,(row, asset, stream, stream_key) in enumerate(pending,1):
                context=dict(stream_index=index,streams=len(pending),sequence=asset.sequence,sensor=asset.sensor,camera=asset.camera)
                def update(event):
                    if progress:progress(dict(context,**event))
                update(dict(phase='stream_start'))
                config = dict(inputs=[dict(session_id=row["session_id"], raw_root_id=row["raw_root_id"])])
                decode_progress=None
                if progress:
                    try:estimated=estimated_count(stream,None)
                    except ValueError:estimated=None
                    def decode_progress(event):
                        if event['phase']=='decode':event=dict(event,total=estimated)
                        update(event)
                result=extract(asset, stream, self.root, run, config, stream_key, ffmpeg,
                               read_info(resources.joinpath("templates/txt/frame.txt")), interval=interval,progress=decode_progress)
                results.append(result)
                update(dict(phase='stream_done',images=result['count'],reused=result['reused']))
            rows = build_index(self.root, protocol)
            info = read_info(self.root/"info.txt")
            info.update(sample_count=len(rows), camera_status="partially_or_fully_extracted", file_checksum="none",latest_camera_run=run.relative_to(self.root).as_posix())
            write_info(self.root/"info.txt", info)
            report = dict(status="succeeded", streams=len(results), images=sum(r["count"] for r in results),
                          reused_streams=sum(r["reused"] for r in results), budget_bytes=int(budget),
                          frame_selection=conversion["frame_selection"], interval_seconds=interval)
            write_info(run/"conversion.txt", conversion)
            write_info(run/"info.txt", report)
            if progress:progress(dict(phase='done',streams=len(results),images=report['images']))
            return report
        except Exception as exc:
            if progress:progress(dict(phase='failed'))
            write_info(run/"info.txt", dict(status="failed", error=str(exc).replace("\n", " ")))
            raise
        finally:
            lock.unlink(missing_ok=True)

    def export(self, output, *, sequences=None, sensor=None, cameras=None):
        from north16.packages import export_files
        files = []
        for row in self.sources:
            if (row["sensor"] not in ("visible", "infrared") or (sequences and row["sequence"] not in sequences) or
                    (sensor and row["sensor"] != sensor) or (cameras and row["camera"] not in cameras)):
                continue
            folder = self.root/stream_path(row["sequence"],row["sensor"],row["camera"])
            if not (folder/"frames.txt").is_file():
                continue
            files.extend(folder/name for name in ("info.txt", "frames.txt"))
            files.extend(p for name in ("images", "meta") for p in (folder/name).iterdir() if p.is_file())
        return export_files(self.root, output, files, kind="camera")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("extract", "export"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--output")
    parser.add_argument("--sequences", nargs="+")
    parser.add_argument("--sensor", choices=("visible", "infrared"))
    parser.add_argument("--cameras", nargs="+")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--interval", type=float, help="Minimum seconds between saved frames; omit to save all frames (e.g. 5)")
    parser.add_argument("--dry-run", action="store_true", help="Read-only preflight: show selected streams, conservative disk budget and free space without extracting")
    parser.add_argument("--no-progress",action="store_true",help="Disable stderr extraction progress")
    args = parser.parse_args(argv)
    builder = CameraBuilder(args.root)
    selection = dict(sequences=args.sequences, sensor=args.sensor, cameras=args.cameras)
    if args.action == "extract":
        from north16.camera.progress import ExtractionProgress
        report = builder.extract(**selection, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe, interval=args.interval, dry_run=args.dry_run,
                                 progress=None if args.no_progress or args.dry_run else ExtractionProgress())
    else:
        if args.interval is not None:parser.error("--interval only applies to extract")
        if args.dry_run:parser.error("--dry-run only applies to extract")
        if not args.output:parser.error("export requires --output")
        report = builder.export(args.output, **selection)
    print(json.dumps(report, ensure_ascii=False, indent=2))
