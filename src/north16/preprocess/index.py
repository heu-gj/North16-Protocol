"""Resolve reviewed scene attributes from sidecars into a stable manifest."""
from pathlib import Path

from north16.common.files import local_path, read_info, read_table, write_table

SAMPLE_COLUMNS = ("id", "sequence", "sensor", "camera", "image", "mask", "meta", "weather", "illumination", "label_status", "group")


def collect_index(output: Path, protocol: dict) -> list[dict]:
    rows, ids = [], set()
    for receipt in sorted(output.glob("sequences/*/*/*/frames.txt")):
        if receipt.parent.name.startswith("."):
            continue
        stream = read_info(receipt.parent / "info.txt")
        defaults = read_info(receipt.parent.parent.parent / "info.txt")
        for frame in read_table(receipt):
            meta = read_info(local_path(output, frame["meta"]))
            if meta["id"] != frame["id"] or frame["id"] in ids:
                raise ValueError(f"Duplicate/inconsistent observation: {frame['id']}")
            ids.add(frame["id"])
            conditions = {}
            for attr in ("weather", "illumination"):
                value = meta[attr]
                if value == "inherit":
                    valid_default = (defaults.get("default_scope") == "all_observations_in_sequence"
                                     and defaults.get(f"{attr}_status") in {"reviewed", "adjudicated"}
                                     and defaults.get(f"{attr}_evidence_id", "unknown") != "unknown")
                    value = defaults[attr] if valid_default else "unknown"
                allowed = protocol["scene_attributes"][attr]["values"]
                if value not in allowed:
                    raise ValueError(f"Invalid {attr}: {value}")
                conditions[attr] = value
            mask = meta.get("mask", "unknown")
            mask = "" if mask == "unknown" else mask
            if mask and not local_path(output, mask).is_file():
                raise FileNotFoundError(mask)
            row = dict(id=frame["id"], sequence=stream["sequence"], sensor=stream["sensor"], camera=stream["camera"],
                       image=frame["image"], mask=mask, meta=frame["meta"], label_status=meta["label_status"],
                       group=meta["group"], **conditions)
            if not local_path(output, row["image"]).is_file():
                raise FileNotFoundError(row["image"])
            rows.append(row)
    return rows


def build_index(output: Path, protocol: dict) -> list[dict]:
    rows = collect_index(output, protocol)
    if not rows:
        raise ValueError("No standardized camera observations to index")
    write_table(output / "samples.txt", SAMPLE_COLUMNS, rows)
    return rows
