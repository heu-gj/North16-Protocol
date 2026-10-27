"""Build the explicit camera pilot; auxiliary observations are preserved, never certified."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

import yaml

from north16 import __version__
from north16.adapters.capture import discover
from north16.common.files import local_path, read_info, read_table, sha256, write_info, write_table, write_text
from north16.preprocess.auxiliary import preserve
from north16.preprocess.camera import extract, probe
from north16.preprocess.index import build_index


def utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8-sig"))


def validate_contract(config: dict, protocol: dict, templates: Path) -> None:
    """Reject unimplemented rule changes instead of silently ignoring YAML."""
    labels = {"sky": 0, "water": 1, "ice": 2, "other": 3, "ignore": 255}
    declared = read_info(templates / "classes.txt")
    if protocol["annotation"]["labels"] != labels or any(declared.get(k) != str(v) for k, v in labels.items()):
        raise ValueError("Protocol/template class map is incompatible with north16_seg_v1")
    expected_conditions = {"weather": {"clear", "cloudy_overcast", "fog_precipitation", "unknown"},
                           "illumination": {"day", "night", "unknown"}}
    for attr, allowed in expected_conditions.items():
        if set(protocol["scene_attributes"][attr]["values"]) != allowed:
            raise ValueError(f"Unsupported {attr} contract; update the reader/schema first")
    extraction = protocol["extraction"]
    if (extraction["frame_selection"] != "all_decodable_source_frames" or extraction["output_camera_format"] != "png"
            or not extraction["preserve_source_dimensions"] or extraction["enhancement"] != "none"
            or extraction["overwrite"] or config["build"].get("overwrite_assets", False)):
        raise ValueError("Unsupported extraction rule; this builder preserves all native frames without overwrite")
    if config["pilot"]["frame_selection"] != extraction["frame_selection"]:
        raise ValueError("Pilot and protocol disagree about frame selection")
    if not set(config["pilot"]["enabled_tasks"]).issubset({"SEG-VIS", "SEG-IR"}):
        raise ValueError("Only camera segmentation asset preparation is implemented")


def template_table(templates, name, output):
    columns = (templates / name).read_text(encoding="utf-8-sig").splitlines()[0].split("\t")
    if not output.exists():
        write_table(output, columns, [])


def build(config_path: Path, ffmpeg: str, ffprobe: str, workers: int = 2, *, inspect_only=False):
    config_path = config_path.resolve(strict=True)
    config = load_yaml(config_path)
    base = config_path.parent
    project = base.parent
    if config.get("schema_version") != "north16_import_v1" or len(config["inputs"]) != 1:
        raise ValueError("This implementation requires one explicit-segment input")
    source = config["inputs"][0]
    if source.get("scope") != "explicit_segments" or not source.get("segments"):
        raise ValueError("Explicit segments required; no implicit full-dataset traversal")
    protocol_path = (base / config["protocol"]["config"]).resolve(strict=True)
    protocol = load_yaml(protocol_path)
    adapter = load_yaml((base / source["adapter"]).resolve(strict=True))
    if adapter["adapter_id"] != "north16_capture_v1":
        raise ValueError("Unsupported adapter")
    if protocol["protocol_id"] != config["protocol"]["id"]:
        raise ValueError("Protocol identity mismatch")
    if config["pilot"]["generate_splits"] or config["pilot"]["freeze_release"]:
        raise ValueError("Pilot builder cannot generate benchmark splits/releases")
    raw = Path(source["path"]).resolve(strict=True)
    output = Path(config["dataset"]["output_root"]).resolve()
    if output == raw or output.is_relative_to(raw) or raw.is_relative_to(output):
        raise ValueError("Source/output roots must be disjoint")
    templates = project / "templates" / "txt"
    validate_contract(config, protocol, templates)
    version = subprocess.check_output([ffmpeg, "-version"], text=True, encoding="utf-8", errors="replace").splitlines()[0]
    conversion = dict(version=__version__, ffmpeg=version, pixel_format="rgb24", filter="format=rgb24,showinfo",
                      fps_mode="passthrough", compression_level=3, frame_selection="all_decodable_source_frames")
    key = hashlib.sha256(json.dumps(conversion, sort_keys=True).encode()).hexdigest()
    print("Inventory: hashing selected original files (read-only)...", flush=True)
    assets = discover(raw, source["segments"], adapter, source["source_namespace"], source["session_id"])
    videos = [a for a in assets if a.sensor in {"visible", "infrared"}]
    probes = {}
    with ThreadPoolExecutor(max_workers=min(workers, 4)) as pool:
        futures = {pool.submit(probe, a.path, ffprobe): a for a in videos}
        for future in as_completed(futures):
            a = futures[future]
            probes[a.source_id] = future.result()
    for segment in source["segments"]:
        sensors = {a.sensor for a in videos if a.segment == segment}
        if not set(config["pilot"]["required_sensors"]).issubset(sensors):
            raise ValueError(f"Required sensor missing: {segment}")
    # Before decoding use uncompressed RGB bytes plus 20% overhead as conservative budget.
    raw_bytes = 0
    for a in videos:
        p = probes[a.source_id]
        count = int(p.get("nb_frames", 0))
        if not count:
            raise ValueError(f"Capacity estimate needs an observed/declarable frame bound: {a.path}")
        folder = output / "sequences" / a.sequence / a.sensor / a.camera
        if not folder.exists():
            raw_bytes += p["width"] * p["height"] * 3 * count
    budget = int(raw_bytes * 1.2) + sum(a.size for a in assets if a.sensor not in {"visible", "infrared"})
    free = shutil.disk_usage(output if output.exists() else output.parent).free
    print(f"Preflight: {len(assets)} sources; {len(videos)} videos; budget {budget / 2**30:.1f} GiB; free {free / 2**30:.1f} GiB", flush=True)
    if free < budget:
        raise ValueError("Insufficient conservative disk budget; extraction not started")
    if inspect_only:
        return {"videos": len(videos), "sources": len(assets), "budget_bytes": budget}
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".north16_build.lock"
    with lock.open("x", encoding="utf-8") as h:
        h.write(f"started={utc()}\nconfig={config_path}\n")
    run_id = "pilot_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
    run = output / "logs" / run_id
    run.mkdir(parents=True)
    steps, errors, checks = [], [], []
    started = utc()
    root_info = {}
    registry_rows = []
    def step(name, state, reason="unknown"):
        steps.append(dict(step=name, scope_id="first_three_camera_segments", state=state,
                          started_at_utc=utc(), ended_at_utc=utc() if state != "running" else "unknown", reason=reason))
        columns = (templates / "steps.txt").read_text(encoding="utf-8-sig").splitlines()[0].split("\t")
        write_table(run / "steps.txt", columns, steps)
    def check(name, result, message, severity="info", scope="pilot"):
        checks.append(dict(check_id=name, scope_id=scope, result=result, severity=severity, message=message, evidence_path="unknown"))
    try:
        if (output / "info.txt").exists():
            root_info = read_info(output / "info.txt")
            if root_info.get("dataset_status") == "frozen" or root_info.get("protocol_id") != protocol["protocol_id"]:
                raise ValueError("Frozen or incompatible existing dataset")
            previous = root_info.get("source_registry", "unknown")
            if previous != "unknown":
                registry_rows = read_table(local_path(output, previous))
        old_by_id = {r["source_id"]: r for r in registry_rows}
        for a in assets:
            old = old_by_id.get(a.source_id)
            if old and (old["sha256"] != a.digest or old["source_relative_path"] != a.relative):
                raise ValueError(f"Source content changed: {a.relative}")
        step("inspect", "succeeded")
        config["execution"] = dict(started_at_utc=started, run_id=run_id, conversion=conversion,
                                   extraction_key=key, budget_bytes=budget, free_bytes_at_start=free,
                                   config_sha256=sha256(config_path), protocol_sha256=sha256(protocol_path),
                                   adapter=adapter, protocol=protocol, workers=workers,
                                   executed_stages=["inspect", "extract", "index", "validate"],
                                   ffmpeg_path=ffmpeg, ffprobe_path=ffprobe)
        write_text(run / "resolved.yaml", yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
        write_text(run / "probes.json", json.dumps(probes, indent=2))
        write_info(run / "info.txt", dict(schema_version="north16_run_v1", record_status="recorded", run_id=run_id,
                   run_status="running", started_at_utc=started, ended_at_utc="unknown", protocol_id=protocol["protocol_id"],
                   protocol_revision=protocol["design_version"], converter_version=__version__, reader_version=__version__,
                   config_path="resolved.yaml", config_sha256=sha256(config_path), source_scope=",".join(source["segments"])))
        # Check identity at sequence scope before any stream commits.
        for a in videos:
            seqinfo = output / "sequences" / a.sequence / "info.txt"
            if seqinfo.exists():
                old = read_info(seqinfo)
                if old["session_id"] != source["session_id"] or old["source_relative_path"] != a.segment:
                    raise ValueError(f"Sequence collision, explicit namespace resolution required: {a.sequence}")
        step("extract", "running")
        auxiliary = preserve(assets, output, run, config, templates)
        results, failures = [], []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(extract, a, probes[a.source_id], output, run, config, key, ffmpeg,
                                   read_info(templates / "frame.txt")): a for a in videos}
            for future in as_completed(futures):
                a = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                    print(f"[{len(results) + len(failures)}/{len(videos)}] {a.sequence}/{a.sensor}/{a.camera}: {result['count']} PNG {'reused' if result['reused'] else 'verified'}", flush=True)
                except Exception as exc:
                    failures.append(a)
                    errors.append(dict(step="extract", source_id=a.source_id, sample_id="unknown", code="EXTRACTION_FAILED",
                                       message=str(exc).replace("\n", " ").replace("\t", " "), severity="error"))
                    print(f"FAILED: {a.relative}: {exc}", flush=True)
        if failures:
            raise RuntimeError(f"{len(failures)} camera streams failed; successful streams retained for resume")
        step("extract", "succeeded")
        for a in assets:
            old_by_id[a.source_id] = dict(source_id=a.source_id, raw_root_id=source["raw_root_id"],
                source_namespace=source["source_namespace"], session_id=source["session_id"], source_relative_path=a.relative,
                sha256=a.digest, size_bytes=a.size, sequence=a.sequence, sensor=a.sensor, camera=a.camera,
                state="extracted", reason="camera_decode" if a.sensor in {"visible", "infrared"} else "raw_evidence_preserved")
        columns = (templates / "sources.txt").read_text(encoding="utf-8-sig").splitlines()[0].split("\t")
        write_table(run / "sources.txt", columns, sorted(old_by_id.values(), key=lambda r: r["source_id"]))
        for name in ("classes.txt", "protocol.txt"):
            target = output / name
            declared = read_info(templates / name)
            if target.exists():
                if read_info(target) != declared:
                    raise ValueError(f"Existing declaration conflict: {target}")
            else:
                write_info(target, declared)
        rows = build_index(output, protocol)
        step("index", "succeeded")
        for name in ("pairs.txt", "sar_links.txt"):
            template_table(templates, name, output / "sync" / name)
        if not (output / "sync" / "info.txt").exists():
            si = read_info(templates / "sync_info.txt")
            si.update(record_status="recorded", association_status="blocked_unverified_time_and_calibration")
            write_info(output / "sync" / "info.txt", si)
        for result in results:
            a, n = result["asset"], result["count"]
            declared = probes[a.source_id].get("nb_frames", "unknown")
            check("camera_frames", "pass", f"{n} PNG CRC/geometry/PTS/identity verified", scope=a.source_id)
            if declared != str(n):
                check("container_vs_decoded_count", "pass", f"Container declares {declared}, actual decoder emitted {n}; discrepancy retained", "warning", a.source_id)
            if result["diagnostic"] != "none":
                check("decoder_diagnostics", "pass", "Decoder diagnostic log retained; no synthetic replacement", "warning", a.source_id)
        for item in auxiliary:
            check("radar_raw_preservation", "pass", json.dumps(item, sort_keys=True), "warning" if item["invalid_kml"] else "info", item["sequence"])
        check("manifest_count", "pass", f"{len(rows)} unique observations; no masks fabricated")
        check("certified_time_alignment", "not_checked", "Capture clock and frame/log mapping unresolved", "warning")
        check("annotation_quality", "not_checked", "No human annotations produced")
        check("split_independence", "not_applicable", "Pilot has no train/val/test split")
        step("associate", "blocked", "No verified clock/calibration evidence")
        step("sample", "pending", "Human candidate review not executed in extraction run")
        step("annotate", "pending", "Human labels not generated")
        step("split", "skipped", "Pilot prohibits split generation")
        step("release", "skipped", "Working pilot only")
        step("validate", "succeeded", "Standardized camera asset scope only")
        checksum_rows = []
        for result in results:
            for frame in read_table(result["folder"] / "frames.txt"):
                checksum_rows.append(dict(path=frame["image"], sha256=frame["image_sha256"]))
                checksum_rows.append(dict(path=frame["meta"], sha256=sha256(local_path(output, frame["meta"]))))
        write_table(run / "checksums.txt", ("path", "sha256"), checksum_rows)
        root_info = root_info or read_info(templates / "dataset_info.txt")
        root_info.update(record_status="recorded", dataset_id=config["dataset"]["id"], dataset_version="pilot-v0.1-working",
                         dataset_status="working", source_registry=f"logs/{run_id}/sources.txt", latest_run=f"logs/{run_id}",
                         protocol_id=protocol["protocol_id"], converter_version=__version__, reader_version=__version__,
                         sample_count=str(len(rows)), time_alignment_status="unresolved", annotation_status="unlabeled")
        write_info(output / "info.txt", root_info)
        report = dict(run_id=run_id, build_status="succeeded", workflow_status="awaiting_time_evidence_and_human_annotation",
                      videos=len(videos), images=sum(r["count"] for r in results), manifest_samples=len(rows),
                      sensor_counts=dict(Counter(r["sensor"] for r in rows)),
                      reused_streams=sum(r["reused"] for r in results), sequences=sorted({a.sequence for a in videos}),
                      output_image_bytes=sum(int(f["image_bytes"]) for r in results for f in read_table(r["folder"] / "frames.txt")),
                      auxiliary=auxiliary, ended_at_utc=utc())
        write_text(run / "summary.json", json.dumps(report, indent=2))
        info = read_info(run / "info.txt")
        info.update(run_status="succeeded", workflow_status=report["workflow_status"], ended_at_utc=utc(),
                    discovered_source_count=len(assets), successful_observation_count=report["images"],
                    failed_asset_count=0, blocked_stage_count=1)
        write_info(run / "info.txt", info)
        print(json.dumps(report, indent=2), flush=True)
        return report
    except Exception as exc:
        step("build", "failed", str(exc).replace("\n", " "))
        write_info(run / "info.txt", dict(schema_version="north16_run_v1", run_id=run_id, run_status="failed",
                   started_at_utc=started, ended_at_utc=utc(), error=str(exc).replace("\n", " ")))
        raise
    finally:
        for name, values in (("errors.txt", errors), ("checks.txt", checks)):
            columns = (templates / name).read_text(encoding="utf-8-sig").splitlines()[0].split("\t")
            write_table(run / name, columns, values)
        lock.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--workers", type=int, default=2, choices=range(1, 5))
    parser.add_argument("--inspect-only", action="store_true")
    args = parser.parse_args(argv)
    build(args.config, args.ffmpeg, args.ffprobe, args.workers, inspect_only=args.inspect_only)
