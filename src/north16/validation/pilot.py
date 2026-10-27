"""Read-only post-build validation and a contact sheet; no new labels or splits."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from PIL import Image, ImageDraw
from torch.utils.data import DataLoader, Subset

from north16.common.files import local_path, read_info, read_table, sha256, write_text
from north16.datasets import North16SegDataset, SegResize


def validate(root: Path, report: Path | None = None):
    root = root.resolve(strict=True)
    info = read_info(root / "info.txt")
    run = local_path(root, info["source_registry"]).parent
    rows = read_table(root / "samples.txt")
    checksums = {r["path"]: r["sha256"] for r in read_table(run / "checksums.txt")}
    attribute_checksums = {}
    attribute_registry = info.get("attribute_registry", "unknown")
    if attribute_registry != "unknown":
        registry_path = local_path(root, attribute_registry)
        attribute_run_info = read_info(registry_path.parent / "info.txt")
        if attribute_run_info.get("status") != "succeeded" or attribute_run_info.get("source_registry") != info["source_registry"]:
            raise ValueError("Attribute snapshot is incomplete or belongs to another source snapshot")
        attribute_checksums = {r["path"]: r["sha256"] for r in read_table(registry_path)}
        for relative, digest in attribute_checksums.items():
            if sha256(local_path(root, relative)) != digest:
                raise ValueError(f"Attribute snapshot checksum failure: {relative}")
    ids, streams, counts = set(), {}, Counter()
    for row in rows:
        if row["id"] in ids:
            raise ValueError(f"Repeated ID: {row['id']}")
        ids.add(row["id"])
        image, meta_path = local_path(root, row["image"]), local_path(root, row["meta"])
        if not image.is_file() or not meta_path.is_file():
            raise FileNotFoundError(row["id"])
        meta = read_info(meta_path)
        for field in ("id", "sequence", "sensor", "camera"):
            if meta[field] != row[field]:
                raise ValueError(f"Manifest/sidecar mismatch: {row['id']}, {field}")
        if any(meta[k] != row[k] for k in ("weather", "illumination")):
            raise ValueError(f"Attribute/index mismatch: {row['id']}")
        if sha256(meta_path) != attribute_checksums.get(row["meta"], checksums[row["meta"]]):
            raise ValueError(f"Metadata changed since committed snapshot: {meta_path}")
        if meta["image_sha256"] != checksums[row["image"]]:
            raise ValueError(f"Image checksum declaration mismatch: {row['id']}")
        if row["mask"] or meta["label_status"] != "unlabeled":
            raise ValueError("This pilot-only check expects unlabeled observations")
        if meta["capture_time_utc"] != "unknown" or meta["time_mapping_status"] != "unresolved":
            raise ValueError("Unexpected certified time in unresolved pilot")
        counts[(row["sequence"], row["sensor"])] += 1
        streams.setdefault((row["sequence"], row["sensor"], row["camera"]), []).append(row)
    checked_image_count = 0
    previews = []
    for (seq, sensor, camera), members in sorted(streams.items()):
        stream_info = read_info(local_path(root, members[0]["meta"]).parent.parent / "info.txt")
        if len(members) != int(stream_info["decoded_frame_count"]):
            raise ValueError(f"Stream count mismatch: {seq}/{sensor}/{camera}")
        # Every PNG was CRC/hash checked during construction. Independently decode
        # first, middle and last in each stream, checking the saved image hash.
        for index in sorted({0, len(members) // 2, len(members) - 1}):
            row = members[index]
            image_path = local_path(root, row["image"])
            if sha256(image_path) != checksums[row["image"]]:
                raise ValueError(f"Image checksum failure: {row['id']}")
            with Image.open(image_path) as im:
                im.load()
                if im.size != (int(stream_info["width"]), int(stream_info["height"])):
                    raise ValueError(f"Image geometry failure: {row['id']}")
                if index == len(members) // 2 and camera in {"front_01", "back_01"}:
                    thumb = im.convert("RGB")
                    thumb.thumbnail((384, 236))
                    previews.append((f"{seq} {sensor} {camera}", thumb))
            checked_image_count += 1
    sequences = sorted({r["sequence"] for r in rows})
    ds = North16SegDataset(root, split=None, sequences=sequences, sensor=["visible", "infrared"],
                          require_mask=False, joint_transform=SegResize((256, 384)))
    selected = []
    positions = {s.id: i for i, s in enumerate(ds.samples)}
    for members in streams.values():
        selected.append(positions[members[len(members) // 2]["id"]])
    tensor_batches = 0
    for batch in DataLoader(Subset(ds, selected), batch_size=4, num_workers=0):
        if batch["image"].shape[1:] != (3, 256, 384) or "mask" in batch:
            raise ValueError("Dataset batch contract failure")
        tensor_batches += 1
    if (root / "splits").exists():
        raise ValueError("Pilot should not fabricate benchmark splits")
    sheet = Image.new("RGB", (4 * 400, ((len(previews) + 3) // 4) * 280), "#20242a")
    draw = ImageDraw.Draw(sheet)
    for i, (label, thumb) in enumerate(previews):
        x, y = (i % 4) * 400, (i // 4) * 280
        sheet.paste(thumb, (x + (400 - thumb.width) // 2, y + 30))
        draw.text((x + 8, y + 8), label, fill="white")
    validation_run = registry_path.parent if attribute_registry != "unknown" else run
    preview_path = validation_run / "preview.jpg"
    sheet.save(preview_path, quality=90)
    result = dict(status="pass", manifest_samples=len(rows), unique_ids=len(ids), stream_count=len(streams),
                  sequences=sequences, counts=[dict(sequence=k[0], sensor=k[1], images=v) for k, v in sorted(counts.items())],
                  all_frame_metadata_hashes_verified=len(rows),
                  independent_full_png_decodes=checked_image_count, dataloader_samples=len(selected),
                  dataloader_batches=tensor_batches, preview=preview_path.as_posix(),
                  image_crc_and_hash_scope="all during build; first/middle/last independently decoded here",
                  attribute_registry=attribute_registry,
                  label_status="unlabeled", time_alignment="unresolved", split_status="not_generated")
    destination = report or validation_run / "pilot_validation.json" if attribute_registry != "unknown" else report or run / "validation.json"
    write_text(destination, json.dumps(result, indent=2))
    print(json.dumps(result, indent=2), flush=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    validate(args.root)


if __name__ == "__main__":
    main()
