"""Discover the documented North16 capture layout without clock assumptions."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

from north16.common.files import sha256


@dataclass(frozen=True)
class Asset:
    path: Path
    relative: str
    source_id: str
    digest: str
    size: int
    sequence: str
    segment: str
    sensor: str
    camera: str
    modified_ns: int | None = None


def discover(raw: Path, segments: list[str], adapter: dict, namespace: str, session: str, *, checksum=True) -> list[Asset]:
    assets = []
    for segment in segments:
        if not re.fullmatch(r"\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}_data", segment):
            raise ValueError(f"Unsupported segment: {segment}")
        folder = (raw / segment).resolve(strict=True)
        if not folder.is_relative_to(raw):
            raise ValueError("Source directory escapes input root")
        parts = segment.split("_")
        sequence = "".join(parts[:3]) + "_" + "".join(parts[3:6])
        videos = list(folder.glob(adapter["camera"]["video_glob"]))
        if not videos:
            raise ValueError(f"No camera videos in {folder}")
        for path in sorted(p for p in folder.rglob("*") if p.is_file()):
            if not path.resolve().is_relative_to(raw):
                raise ValueError(f"Source symlink escape: {path}")
            sensor, camera = "source", "unknown"
            if path in videos:
                mapping = adapter["camera"]["sensor_name_mappings"].get(path.parent.name)
                match = re.fullmatch(r"lens_(\d+)", path.stem)
                if not mapping or not match:
                    raise ValueError(f"Unrecognized camera layout: {path}")
                sensor = mapping["modality"]
                camera = f"{mapping['position']}_{int(match[1]):02d}"
            elif path.parent.name == "ice_radar":
                sensor = "ice_radar"
            elif path.parent.name == "navigation_radar":
                sensor = "nav"
            relative = path.relative_to(raw).as_posix()
            identity = f"{namespace}\0{session}\0{relative}".encode()
            source_id = "src_" + hashlib.sha256(identity).hexdigest()[:24]
            stat = path.stat()
            assets.append(Asset(path, relative, source_id, sha256(path) if checksum else "disabled", stat.st_size,
                                sequence, segment, sensor, camera, stat.st_mtime_ns))
    keys = [(a.sequence, a.sensor, a.camera) for a in assets if a.sensor in {"visible", "infrared"}]
    if len(set(keys)) != len(keys):
        raise ValueError("Camera stream name collision")
    return assets
