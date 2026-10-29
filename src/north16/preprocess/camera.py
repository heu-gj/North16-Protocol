"""One decode pass emits PNGs and their actual filter-frame PTS via showinfo."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from fractions import Fraction

from PIL import Image

from north16.common.files import read_info, read_table, sha256, check_size, write_info, write_table, write_text


FRAME_COLUMNS = ("id", "image", "meta", "image_sha256", "image_bytes", "pts", "pts_time", "time_base")
SHOW = re.compile(r"\bn:\s*(\d+)\s+pts:\s*(\S+)\s+pts_time:\s*(\S+)")
TIME_BASE = re.compile(r"config in time_base:\s*(\d+/\d+)")


def probe(path: Path, ffprobe: str) -> dict:
    command = [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
               "stream=index,codec_name,width,height,pix_fmt,r_frame_rate,avg_frame_rate,time_base,start_time,duration,nb_frames,color_range,color_space,color_transfer,color_primaries",
               "-of", "json", str(path)]
    p = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if p.returncode:
        raise RuntimeError(f"ffprobe failed for {path}: {p.stderr}")
    data = json.loads(p.stdout)
    if len(data.get("streams", [])) != 1:
        raise ValueError(f"Expected exactly one selected video stream: {path}")
    return dict(data["streams"][0], probe_stderr=p.stderr)


def verify_stream(folder: Path, *, key: str, source_id: str, deep: bool = True, checksum: bool = False) -> list[dict]:
    info = read_info(folder / "info.txt")
    if info.get("extraction_key") != key or info.get("source_id") != source_id or info.get("decode_status") != "complete":
        raise ValueError(f"Incomplete/conflicting output; not overwritten: {folder}")
    rows = read_table(folder / "frames.txt")
    if len(rows) != int(info["decoded_frame_count"]) or not rows:
        raise ValueError(f"Frame count mismatch: {folder}")
    images = set((folder / "images").glob("*.png"))
    if images != {folder / "images" / Path(row["image"]).name for row in rows} or len(images) != len(rows):
        raise ValueError(f"Image set mismatch: {folder}")
    previous = -1
    sampled = info.get("frame_selection") == "minimum_pts_interval"
    if sampled:
        from north16.camera.sampling import normalize_interval
        interval = normalize_interval(info["sampling_interval_s"])
        if int(info["saved_frame_count"]) != len(rows):
            raise ValueError(f"Saved frame count mismatch: {folder}")
    prefix = f"sequences/{info['sequence']}/{info['sensor']}/{info['camera']}"
    previous_time = None
    for i, row in enumerate(rows):
        name = Path(row["image"]).name
        match = re.fullmatch(r"f(\d{6,})\.png", name)
        if not match:
            raise ValueError(f"Invalid frame filename: {name}")
        source_index = int(match[1])
        if source_index <= previous or (not sampled and source_index != i):
            raise ValueError(f"Invalid source frame order: {folder}")
        previous = source_index
        image = folder / "images" / name
        meta = read_info(folder / "meta" / Path(name).with_suffix(".txt").name)
        if meta["id"] != row["id"] or meta["source_id"] != source_id or meta["decoded_frame_index"] != str(source_index):
            raise ValueError(f"Frame identity mismatch: {image}")
        if (row["image"] != f"{prefix}/images/{name}" or
                row["meta"] != f"{prefix}/meta/{Path(name).stem}.txt" or
                any(row[k] != meta[m] for k, m in (("pts", "pts"), ("pts_time", "pts_time_s"), ("time_base", "time_base")))):
            raise ValueError(f"Frame receipt mismatch: {image}")
        if sampled:
            if (i == 0 and source_index != 0 or source_index >= int(info["source_decoded_frame_count"]) or
                    meta.get("saved_frame_index") != str(i) or normalize_interval(meta.get("sampling_interval_s")) != interval):
                raise ValueError(f"Sampling identity mismatch: {image}")
            timestamp = int(row["pts"])*Fraction(row["time_base"])
            if previous_time is not None and float(timestamp-previous_time)+1e-9 < interval:
                raise ValueError(f"Sampling interval mismatch: {image}")
            previous_time = timestamp
        check_size(image, row.get("image_bytes"))
        if checksum and deep and sha256(image) != row["image_sha256"]:
            raise ValueError(f"Image changed: {image}")
    return rows


def extract(asset, stream: dict, output: Path, run: Path, config: dict, key: str,
            ffmpeg: str, template: dict, *, interval=None, progress=None) -> dict:
    from north16.camera.sampling import normalize_interval, parse_sampled_log, video_filter
    interval = normalize_interval(interval)
    check_size(asset.path, asset.size)
    if asset.modified_ns is not None and asset.path.stat().st_mtime_ns != asset.modified_ns:
        raise ValueError(f"Source changed before conversion: {asset.path}")
    folder = output / "sequences" / asset.sequence / asset.sensor / asset.camera
    reserved = False
    if folder.exists():
        existing = read_info(folder / "info.txt")
        if existing.get("source_id") != asset.source_id:
            raise ValueError(f"Original source identity changed: {asset.relative}")
        if asset.digest != "disabled" and existing.get("source_sha256") != asset.digest:
            raise ValueError(f"Original source hash changed: {asset.relative}")
        reserved = existing.get("decode_status") == "pending" and existing.get("source_id") == asset.source_id
        if reserved:
            if ({p.name for p in folder.iterdir()} != {"info.txt", "images", "meta"} or
                    any((folder/name).is_symlink() or not (folder/name).is_dir() or any((folder/name).iterdir()) for name in ("images", "meta"))):
                raise ValueError("Initialized stream contains unexpected files; not overwritten")
        else:
            rows = verify_stream(folder, key=key, source_id=asset.source_id, checksum=asset.digest != "disabled")
            return {"asset": asset, "count": len(rows), "reused": True, "folder": folder,
                    "diagnostic": existing.get("diagnostic", "unknown")}
    folder.parent.mkdir(parents=True, exist_ok=True)
    staging = folder.with_name("." + folder.name + ".partial_" + uuid.uuid4().hex)
    (staging / "images").mkdir(parents=True)
    (staging / "meta").mkdir()
    log = run / "decoder" / (asset.source_id + ".log")
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-loglevel", "info", "-n",
               "-threads", "2", *(["-copyts"] if interval is not None else []),
               "-i", str(asset.path), "-map", "0:v:0", "-an", "-sn", "-dn",
               "-filter_threads", "1", "-vf", video_filter(interval), "-fps_mode", "passthrough",
               "-c:v", "png", "-threads:v", "2", "-compression_level", "3", "-start_number", "0",
               str(staging / "images" / "f%06d.png")]
    write_text(run / "decoder" / (asset.source_id + ".command.json"), json.dumps(command, indent=2))
    from north16.preprocess.decoder import run_decoder
    code=run_decoder(command,log,progress=progress,sampled=interval is not None)
    if code:
        raise RuntimeError(f"Decode failed ({code}), retained staging {staging}; see {log}")
    text = log.read_text(encoding="utf-8", errors="replace")
    if interval is None:
        matches = SHOW.findall(text)
        base_match = TIME_BASE.search(text)
        if not base_match or not matches or [int(m[0]) for m in matches] != list(range(len(matches))):
            raise ValueError(f"Cannot establish exact decoded output/PTS correspondence: {log}")
        time_base = base_match[1]
        decoded_count = len(matches)
    else:
        matches, time_base, decoded_count = parse_sampled_log(text, interval)
    images = sorted((staging / "images").glob("*.png"))
    if len(images) != len(matches):
        raise ValueError(f"PNG/showinfo count mismatch: {staging}")
    if interval is not None:
        # Rename backwards so sparse source indices cannot collide with not-yet
        # renamed sequential PNGs. Source index is always >= output ordinal.
        for path, (index, _, _) in reversed(list(zip(images, matches))):
            dest = path.with_name(f"f{int(index):06d}.png")
            if dest != path:
                path.rename(dest)
        images = [staging/"images"/f"f{int(index):06d}.png" for index, _, _ in matches]
    rows = []
    if progress:progress(dict(phase='verify',done=0,total=len(images)))
    for saved_index, (path, (source_index, pts, pts_time)) in enumerate(zip(images, matches)):
        i = int(source_index)
        with Image.open(path) as im:
            if im.format != "PNG" or im.mode != "RGB" or im.size != (stream["width"], stream["height"]):
                raise ValueError(f"Unexpected extracted frame geometry: {path}")
            im.verify()
        frame_id = f"n16_{asset.sequence}_{asset.sensor}_{asset.camera}_f{i:06d}"
        prefix = f"sequences/{asset.sequence}/{asset.sensor}/{asset.camera}"
        meta = dict(template)
        meta.update(record_status="recorded", id=frame_id, session_id=config["inputs"][0]["session_id"],
                    segment_id=asset.segment, sequence=asset.sequence, sensor=asset.sensor, camera=asset.camera,
                    source_id=asset.source_id, image=f"{prefix}/images/{path.name}", decoded_frame_index=i,
                    pts=pts if pts != "NOPTS" else "unknown", time_base=time_base,
                    pts_time_s=pts_time if pts_time != "NOPTS" else "unknown",
                    raw_root_id=config["inputs"][0]["raw_root_id"], source_video_path=asset.relative,
                    source_log_path=f"sequences/{asset.sequence}/source/time.txt",
                    source_log_row_index="unknown", raw_timestamp_candidate="unknown",
                    time_mapping_status="unresolved", capture_time_utc="unknown", attribute_version="unknown")
        if interval is not None:
            meta.update(saved_frame_index=saved_index, sampling_interval_s=interval)
        for attr in ("weather", "illumination"):
            meta[attr] = "unknown"
            for suffix in ("source", "evidence_id", "confidence"):
                meta[f"{attr}_{suffix}"] = "unknown"
            meta[f"{attr}_status"] = "unreviewed"
            meta[f"{attr}_reason"] = "not_assessed"
        # The legacy build command still has its explicit checksummed contract.
        digest = sha256(path) if asset.digest != "disabled" else "disabled"
        meta["image_sha256"] = digest
        # Sidecars live inside an unpublished stream staging directory. Avoid
        # a disk-wide FlushFileBuffers for every frame; final receipts are durable.
        write_info(staging / "meta" / path.with_suffix(".txt").name, meta, durable=False)
        rows.append(dict(zip(FRAME_COLUMNS, [frame_id, meta["image"], f"{prefix}/meta/{path.stem}.txt",
                                             digest, path.stat().st_size, meta["pts"], meta["pts_time_s"], time_base])))
        if progress:progress(dict(phase='verify',done=saved_index+1,total=len(images)))
    warnings = [line.strip() for line in text.splitlines() if any(w in line.lower() for w in
                ("error", "invalid", "corrupt", "damaged", "non monoton", "missing picture"))]
    diagnostic = "decoder_messages_present" if warnings else "none"
    write_table(staging / "frames.txt", FRAME_COLUMNS, rows)
    write_info(staging / "info.txt", dict(schema_version="north16_camera_v1", record_status="recorded",
               source_id=asset.source_id, source_sha256=asset.digest, source_bytes=asset.size, source_video_path=asset.relative,
               file_checksum="none" if asset.digest == "disabled" else "sha256",
               raw_root_id=config["inputs"][0]["raw_root_id"], session_id=config["inputs"][0]["session_id"],
               sequence=asset.sequence, sensor=asset.sensor, camera=asset.camera,
               position=asset.camera.rsplit("_", 1)[0], lens_id=asset.path.stem,
               width=stream["width"], height=stream["height"], codec=stream["codec_name"],
               pixel_format=stream["pix_fmt"], output_pixel_format="rgb24", time_base=time_base,
               declared_frame_count=stream.get("nb_frames", "unknown"), decoded_frame_count=len(rows),
               decode_status="complete", extraction_key=key, conversion_version="0.1.0",
               color_conversion="ffmpeg_swscale_default_to_rgb24_no_resize", diagnostic=diagnostic,
               decoder_log=log.relative_to(output).as_posix(), time_mapping_status="unresolved"))
    if interval is not None:
        info = read_info(staging / "info.txt")
        info.update(frame_selection="minimum_pts_interval", sampling_interval_s=interval,
                    source_decoded_frame_count=decoded_count, saved_frame_count=len(rows))
        write_info(staging / "info.txt", info)
    if progress:progress(dict(phase='publish'))
    check_size(asset.path, asset.size)
    if asset.modified_ns is not None and asset.path.stat().st_mtime_ns != asset.modified_ns:
        raise ValueError(f"Source changed during conversion: {asset.path}")
    if asset.digest != "disabled" and sha256(asset.path) != asset.digest:
        raise ValueError(f"Source changed during conversion: {asset.path}")
    if reserved:
        # Retain initialized metadata in the run; rollback on failed publication.
        reserved_backup = run / "initialized" / asset.sequence / asset.sensor / asset.camera
        reserved_backup.parent.mkdir(parents=True, exist_ok=True)
        from north16.common.move import move_directory
        # These paths are dataset assets rather than annotation workspace paths.
        move_directory(folder, reserved_backup, output)
        try:
            move_directory(staging, folder, output)
        except Exception:
            move_directory(reserved_backup, folder, output)
            raise
    else:
        os.rename(staging, folder)
    return {"asset": asset, "count": len(rows), "reused": False, "folder": folder, "diagnostic": diagnostic}
