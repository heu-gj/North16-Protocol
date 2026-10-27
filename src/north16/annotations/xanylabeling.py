"""Lossless editable polygon projects and explicit-mask import for North16."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw


CLASSES = {"sky": 0, "water": 1, "ice": 2, "other": 3, "ignore": 255}
PALETTE = {0: (90, 170, 240), 1: (20, 75, 170), 2: (245, 215, 80),
           3: (210, 80, 175), 255: (110, 110, 110)}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def simple_polygons(binary):
    """Split holed components into ordinary polygons; retain every pixel.

    X-AnyLabeling polygons have no portable interior-ring field. Partitioning
    rather than filling/removing holes makes each piece independently editable.
    """
    queue = [(np.ascontiguousarray(binary, dtype=np.uint8), 0, 0)]
    while queue:
        a, ox, oy = queue.pop()
        n, labels, stats, _ = cv2.connectedComponentsWithStats(a, connectivity=8)
        for component in range(1, n):
            x, y, w, h, area = map(int, stats[component])
            roi = np.ascontiguousarray(labels[y:y+h, x:x+w] == component, dtype=np.uint8)
            contours, hierarchy = cv2.findContours(roi, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
            outer = [i for i, hi in enumerate(hierarchy[0]) if hi[3] < 0]
            if len(outer) != 1:
                raise ValueError("Connected-component contour topology mismatch")
            ci = outer[0]
            hole = int(hierarchy[0][ci][2])
            if hole >= 0:
                hx, hy, hw, hh = cv2.boundingRect(contours[hole])
                if w >= h:
                    cut = max(1, min(w - 1, hx + hw // 2))
                    queue.extend([(roi[:, :cut], ox+x, oy+y),
                                  (roi[:, cut:], ox+x+cut, oy+y)])
                else:
                    cut = max(1, min(h - 1, hy + hh // 2))
                    queue.extend([(roi[:cut, :], ox+x, oy+y),
                                  (roi[cut:, :], ox+x, oy+y+cut)])
                continue
            points = contours[ci][:, 0, :] + [ox+x, oy+y]
            if len(points) < 3:
                # A degenerate polygon is supported by PIL and preserves a
                # one-pixel run, without expanding it into adjacent classes.
                points = np.array([[ox+x, oy+y], [ox+x+w-1, oy+y],
                                   [ox+x+w-1, oy+y+h-1], [ox+x, oy+y+h-1]])
            yield points.tolist()


def vectorize(mask):
    shapes = []
    # Uncovered pixels deliberately mean ignore, never water/background.
    for label, value in CLASSES.items():
        if value == 255:
            continue
        for points in simple_polygons(mask == value):
            shapes.append(dict(label=label, points=points, group_id=None,
                               description="GrabCut draft; requires manual review",
                               shape_type="polygon", flags={}, difficult=False,
                               attributes={}, kie_linking=[], score=None))
    # Raster contour tracing can differ at diagonal one-pixel junctions.
    # Preserve those pixels with local, vertically merged run patches.
    rebuilt = render(dict(imageWidth=mask.shape[1], imageHeight=mask.shape[0], shapes=shapes))
    mismatch = rebuilt != mask
    if mismatch.any():
        names = {v: k for k, v in CLASSES.items()}
        active, patches = {}, []
        for y in range(mask.shape[0]):
            xs = np.flatnonzero(mismatch[y])
            runs = []
            for x in xs:
                value = int(mask[y, x])
                if runs and runs[-1][1]+1 == x and runs[-1][2] == value:
                    runs[-1] = (runs[-1][0], int(x), value)
                else:
                    runs.append((int(x), int(x), value))
            current = set(runs)
            for key in list(active):
                if key not in current:
                    patches.append((*key, *active.pop(key)))
            for key in runs:
                if key in active:
                    active[key][1] = y
                else:
                    active[key] = [y, y]
        patches.extend((*key, *ys) for key, ys in active.items())
        for x0, x1, value, y0, y1 in patches:
            shapes.append(dict(label=names[value], points=[[x0, y0], [x1, y0],
                          [x1, y1], [x0, y1]], group_id=None, shape_type="polygon",
                          flags={}, description="Lossless pixel junction patch", difficult=False))
    return shapes


from north16.segmentation.labels import render


def export_one(task):
    cv2.setNumThreads(1)
    row, root, draft, output = task
    root, draft, output = map(Path, (root, draft, output))
    source = root / row["source_image"]
    receipt = json.loads((draft / row["meta"]).read_text(encoding="utf-8"))
    if sha(source) != receipt["source_image_sha256"]:
        raise ValueError(f"Source image changed: {source}")
    mask_path = draft / row["mask"]
    if sha(mask_path) != receipt["artifacts"]["mask"]["sha256"]:
        raise ValueError(f"Source mask changed: {mask_path}")
    mask = np.array(Image.open(mask_path))
    if mask.dtype != np.uint8 or mask.ndim != 2 or not set(np.unique(mask)).issubset(CLASSES.values()):
        raise ValueError(f"Invalid source mask: {mask_path}")
    with Image.open(source) as image:
        if image.size != (mask.shape[1], mask.shape[0]):
            raise ValueError("Source image/mask size mismatch")
    camera = receipt["camera"]
    target = output / "visible" / camera / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    annotation = target.with_suffix(".json")
    if target.exists() or annotation.exists():
        raise FileExistsError(f"Will not overwrite an editing file: {target}")
    shapes = vectorize(mask)
    data = dict(version="4.0.0", flags={}, shapes=shapes, imagePath=target.name,
                imageData=None, imageHeight=mask.shape[0], imageWidth=mask.shape[1],
                checked=False, description="North16 draft; unpainted pixels=ignore (255)",
                north16=dict(source_id=row["id"], source_image=row["source_image"],
                             source_mask=str(mask_path), source_mask_sha256=sha(mask_path),
                             label_status="draft", review_status="unreviewed"))
    if not np.array_equal(render(data), mask):
        raise ValueError(f"Lossless polygon round-trip failed: {mask_path}")
    # Real copies isolate GUI rotation/deletion from the original dataset.
    shutil.copyfile(source, target)
    if sha(target) != receipt["source_image_sha256"]:
        raise ValueError(f"Image copy checksum mismatch: {target}")
    save_json(annotation, data)
    reread = json.loads(annotation.read_text(encoding="utf-8"))
    if not np.array_equal(render(reread), mask):
        raise ValueError("Saved JSON pixel round-trip failed")
    return dict(id=row["id"], camera=camera, image=target.relative_to(output).as_posix(),
                annotation=annotation.relative_to(output).as_posix(),
                source_image_sha256=receipt["source_image_sha256"],
                initial_json_sha256=sha(annotation), source_mask_sha256=sha(mask_path),
                polygons=len(shapes), vertices=sum(len(s["points"]) for s in shapes),
                pixel_mismatches=0, label_status="draft", review_status="unreviewed")


def export_project(args):
    root, draft, output = map(Path, (args.root, args.draft, args.output))
    if (draft / "manifest.json").is_file():
        if args.camera or args.limit:
            raise ValueError("新版草稿请在生成时选择镜头和图片；导出时保留完整批次")
        from north16.annotations.workspace import export_editor
        return export_editor(draft, output)
    if output.exists():
        raise FileExistsError("Choose a NEW output directory; existing edits must never be overwritten")
    with (draft / "samples.txt").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    if args.camera:
        rows = [r for r in rows if f"/{args.camera}/" in r["source_image"]]
    if args.limit:
        rows = rows[:args.limit]
    if not rows:
        raise ValueError("No selected observations")
    output.mkdir(parents=True)
    save_json(output / "classes.json", CLASSES)
    (output / "classes.txt").write_text("\n".join(CLASSES)+"\n", encoding="utf-8")
    started = time.monotonic()
    records, errors = [], []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(export_one, (r, str(root), str(draft), str(output))): r for r in rows}
        for future in as_completed(futures):
            row = futures[future]
            try:
                records.append(future.result())
            except Exception as exc:
                errors.append(dict(id=row["id"], error=f"{type(exc).__name__}: {exc}"))
            count = len(records)+len(errors)
            if count % 100 == 0 or count == len(rows):
                state = dict(expected=len(rows), succeeded=len(records), failed=len(errors),
                             seconds=round(time.monotonic()-started, 1))
                save_json(output / "progress.json", state)
                print(json.dumps(state), flush=True)
    records.sort(key=lambda r: r["id"])
    with (output / "manifest.txt").open("w", encoding="utf-8", newline="") as f:
        if records:
            writer = csv.DictWriter(f, list(records[0]), delimiter="\t")
            writer.writeheader();writer.writerows(records)
    save_json(output / "validation.json", dict(status="pass" if not errors else "failed",
              expected=len(rows), succeeded=len(records), failed=len(errors), errors=errors,
              pixel_mismatches=sum(r["pixel_mismatches"] for r in records),
              max_polygons=max((r["polygons"] for r in records), default=0),
              total_polygons=sum(r["polygons"] for r in records),
              source_draft=str(draft), gui_open_tested=False,
              validation="Exact PIL raster round-trip and image SHA256 for every exported JSON"))
    if errors:
        raise RuntimeError(f"{len(errors)} observations failed; see validation.json")


def import_project(args):
    project = Path(args.project).resolve(strict=True)
    context = None
    workspace = None
    if (project / "dataset.json").is_file():
        context = json.loads((project / "dataset.json").read_text(encoding="utf-8"))
        from north16.annotations.dataset_workspace import DatasetWorkspace
        workspace = DatasetWorkspace(context["dataset_root"])
        key = (context["sequence"], context["sensor"], context["camera"])
        if key not in workspace.streams or context["protocol_id"] != workspace.protocol["protocol_id"]:
            raise ValueError("编辑工程与工作数据集身份不一致")
    requested = getattr(args, "output", None)
    if requested:
        output = Path(requested).resolve()
    elif workspace:
        output = workspace.output_path("corrected", key, workspace.new_run_id())
    else:
        raise ValueError("旧工程/普通文件夹工程缺少数据集上下文，请显式指定 --output <新目录>")
    if output.exists():
        raise FileExistsError("Choose a NEW mask output directory")
    if output == project or output.is_relative_to(project) or project.is_relative_to(output):
        raise ValueError("修正回读目录必须与编辑工程分开")
    with (project / "manifest.txt").open(encoding="utf-8-sig", newline="") as f:
        records = list(csv.DictReader(f, delimiter="\t"))
    if workspace:
        from north16.preprocess.index import SAMPLE_COLUMNS
        observations = {row["id"]: row for row in workspace.streams[key]}
        if len({r["id"] for r in records}) != len(records) or any(r["id"] not in observations for r in records):
            raise ValueError("编辑工程含未知或重复样本ID")
    sample_rows = []
    output.mkdir(parents=True)
    results = []
    lut = np.zeros((256, 3), np.uint8)
    for k, color in PALETTE.items():
        lut[k] = color
    for row in records:
        annotation = project / row["annotation"]
        data = json.loads(annotation.read_text(encoding="utf-8"))
        image = (annotation.parent / data["imagePath"]).resolve()
        if image != (project / row["image"]).resolve():
            raise ValueError(f"Changed image identity: {annotation}")
        if sha(image) != row["source_image_sha256"]:
            raise ValueError(f"Changed image content: {image}")
        with Image.open(image) as im:
            if im.size != (data["imageWidth"], data["imageHeight"]):
                raise ValueError(f"Changed image geometry: {annotation}")
        changed = sha(annotation) != row["initial_json_sha256"]
        if args.changed_only and not changed:
            continue
        mask = render(data)
        if workspace:
            observation = observations[row["id"]]
            if (Path(observation["image"]).stem != annotation.stem or row["camera"] != key[2] or
                    row.get("sensor", key[1]) != key[1]):
                raise ValueError("编辑图像与数据集帧身份不匹配")
            dest = output / "masks" / annotation.with_suffix(".png").name
        else:
            dest = output / row.get("sensor", "visible") / row["camera"] / "masks" / annotation.with_suffix(".png").name
        dest.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(mask).save(dest)
        if not np.array_equal(np.array(Image.open(dest)), mask):
            raise ValueError("Saved mask round-trip failure")
        if args.preview:
            color = Image.fromarray(lut[mask])
            dest_color = dest.parent.parent / "color" / dest.name
            dest_overlay = dest.parent.parent / "overlay" / dest.with_suffix(".jpg").name
            dest_color.parent.mkdir(exist_ok=True);dest_overlay.parent.mkdir(exist_ok=True)
            color.save(dest_color)
            with Image.open(image) as im:
                Image.blend(im.convert("RGB"), color, .42).save(dest_overlay, quality=92)
        results.append(dict(id=row["id"], mask=dest.relative_to(output).as_posix(),
                            mask_sha256=sha(dest), annotation_sha256=sha(annotation),
                            json_changed=changed, software_checked=data.get("checked", False) is True,
                            review_status="pending_review", label_status="draft"))
        if workspace:
            sample = {field: observation[field] for field in SAMPLE_COLUMNS}
            # An explicitly external output has no valid dataset-relative path.
            if output.is_relative_to(workspace.root):
                sample.update(mask=dest.relative_to(workspace.root).as_posix(), label_status="draft")
                sample_rows.append(sample)
        if len(results)%100 == 0:
            print(f"Imported {len(results)}", flush=True)
    save_json(output / "import_log.json", dict(status="succeeded", count=len(results),
              project=str(project), source_manifest_sha256=sha(project / "manifest.txt"),
              review_status="pending_review", results=results))
    if workspace:
        save_json(output / "dataset.json", context)
        from north16.common.files import write_table
        if output.is_relative_to(workspace.root):
            write_table(output / "samples.txt", SAMPLE_COLUMNS, sample_rows)
        from north16.annotations.management import refresh
        refresh(workspace.root)
    print(f"Imported {len(results)} draft masks into {output}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("export")
    p.add_argument("--root", required=True);p.add_argument("--draft", required=True)
    p.add_argument("--output", required=True);p.add_argument("--workers", type=int, default=4)
    p.add_argument("--camera");p.add_argument("--limit", type=int)
    p.set_defaults(func=export_project)
    p = sub.add_parser("import")
    p.add_argument("--project", required=True);p.add_argument("--output", help="New output; defaults to protocol corrected path for indexed projects")
    p.add_argument("--changed-only", action="store_true");p.add_argument("--preview", action="store_true")
    p.set_defaults(func=import_project)
    args = parser.parse_args(argv);args.func(args)


if __name__ == "__main__":
    main()
