"""Folder-based draft jobs. Source images are only read, never edited in place."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time

import cv2
import numpy as np
from PIL import Image

from north16.annotations.grabcut import PALETTE, atomic_image, digest, segment, segmentation_method
from north16.annotations.profiles import validate_profile, profile_hash
from north16.annotations.xanylabeling import vectorize, render, save_json


EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def list_images(folder):
    folder = Path(folder).resolve(strict=True)
    if not folder.is_dir():
        raise ValueError("请选择图片文件夹")
    images = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS),
                    key=lambda p: p.name.lower())
    if not images:
        raise ValueError("此文件夹没有图片。请选择images目录或直接包含图片的文件夹")
    return images


def read_image(path):
    with Image.open(path) as image:
        if image.mode not in ("RGB", "RGBA", "L", "P"):
            raise ValueError("当前界面支持8位图像/红外显示PNG；原始16位红外与雷达数值尚不支持，不能直接转成8位标注")
        return image.convert("RGB")


def preview(path, profile, *, internal_threads=4):
    profile = validate_profile(profile)
    source = read_image(path)
    try:
        mask = segment(source, profile, internal_threads=internal_threads)
    except cv2.error as exc:
        raise ValueError("GrabCut计算失败，可能缺少有效冰/水种子。请检查地平线和亮度阈值。\n" + str(exc)) from exc
    return mask


def colored(mask):
    lut = np.zeros((256, 3), dtype=np.uint8)
    for value, color in PALETTE.items():
        lut[value] = color
    return Image.fromarray(lut[mask])


def check_output(images, output):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError("输出目录已经存在，请为本次任务选择一个新目录")
    if not images:
        raise ValueError("没有待处理图片")
    for image in images:
        parent = Path(image).resolve(strict=True).parent
        if output == parent or output.is_relative_to(parent) or parent.is_relative_to(output):
            raise ValueError("输出应与原图目录分开，不能放在原图目录内或作为其父目录")
    return output


def run_job(images, profile, output, *, cancel=None, progress=None, estimation=None, observations=None, context=None):
    """Stop between images; receipts commit only after all per-image artifacts."""
    profile = validate_profile(profile)
    images = [Path(p).resolve(strict=True) for p in images]
    output = check_output(images, output)
    configuration = profile_hash(profile)
    if estimation is not None and estimation.get("profile_sha256") != configuration:
        raise ValueError("自动估计记录与当前参数版本不一致")
    if observations is not None:
        if set(observations) != {str(p) for p in images} or context is None:
            raise ValueError("数据集身份映射与待处理图像不一致")
        if len({p.stem.casefold() for p in images}) != len(images):
            raise ValueError("当前流存在重名帧，不能保留原始帧名")
    output.mkdir(parents=True)
    for folder in ("masks", "color", "overlay", "meta"):
        (output / folder).mkdir()
    save_json(output / "parameters.json", profile)
    if context is not None:
        save_json(output / "dataset.json", context)
    if estimation is not None:
        save_json(output / "estimation.json", estimation)
    started = time.monotonic()
    records, errors = [], []
    cancelled = False
    save_json(output / "run.json", dict(status="running", method=segmentation_method(profile), sea_mode=profile["sea_mode"],
              profile_sha256=configuration, expected=len(images), label_status="draft", review_status="unreviewed",
              sources=[str(p) for p in images], started_utc=datetime.now(timezone.utc).isoformat()))
    try:
        for index, path in enumerate(images):
            if cancel and cancel.is_set():
                cancelled = True
                break
            observation = observations[str(path)] if observations is not None else None
            stem = path.stem if observation is not None else f"{index:06d}_{path.stem}"
            try:
                before = digest(path)
                if observation is not None and before != observation["image_sha256"]:
                    raise ValueError("原图与数据集构建回执不一致")
                mask = preview(path, profile)
                if mask.dtype != np.uint8 or mask.ndim != 2 or not set(np.unique(mask)).issubset(PALETTE):
                    raise ValueError("分割结果尺寸或类别编码异常")
                if cancel and cancel.is_set():
                    cancelled = True
                    break
                source = read_image(path)
                if digest(path) != before or source.size != (mask.shape[1], mask.shape[0]):
                    raise ValueError("处理期间原图发生变化")
                paths = {"mask": output / "masks" / f"{stem}.png",
                         "color": output / "color" / f"{stem}.png",
                         "overlay": output / "overlay" / f"{stem}.jpg"}
                color = colored(mask)
                atomic_image(Image.fromarray(mask), paths["mask"], format="PNG")
                atomic_image(color, paths["color"], format="PNG")
                atomic_image(Image.blend(source, color, .42), paths["overlay"], format="JPEG", quality=92)
                with Image.open(paths["mask"]) as saved:
                    if saved.mode != "L" or not np.array_equal(np.array(saved), mask):
                        raise ValueError("PNG像素回读不一致")
                artifacts = {key: dict(path=p.relative_to(output).as_posix(), sha256=digest(p)) for key, p in paths.items()}
                record = dict(id=stem, source_image=str(path), source_image_sha256=before,
                              method=segmentation_method(profile), sea_mode=profile["sea_mode"],
                              profile_sha256=configuration, label_status="draft", review_status="unreviewed",
                              native_size_wh=list(source.size), artifacts=artifacts,
                              pixel_counts={str(k): int(np.count_nonzero(mask == k)) for k in PALETTE})
                if observation is not None:
                    record.update(id=observation["id"], frame_name=path.stem,
                                  sequence=observation["sequence"], sensor=observation["sensor"], camera=observation["camera"],
                                  source_image_relative=observation["image"], source_meta=observation["meta"],
                                  sample=dict(observation))
                save_json(output / "meta" / f"{stem}.json", record)
                records.append(record)
            except Exception as exc:
                errors.append(dict(source_image=str(path), error=f"{type(exc).__name__}: {exc}"))
            if progress:
                progress(index+1, len(images), path.name)
    finally:
        report = dict(status="cancelled" if cancelled else "completed_with_errors" if errors else "succeeded",
                      expected=len(images), succeeded=len(records), failed=len(errors), errors=errors,
                      seconds=round(time.monotonic()-started, 2), profile_sha256=configuration,
                      label_status="draft", review_status="unreviewed")
        # Always preserve a readable partial run when a stop is requested.
        save_json(output / "validation.json", report)
        save_json(output / "manifest.json", records)
        if observations is not None:
            from north16.common.files import write_table
            from north16.preprocess.index import SAMPLE_COLUMNS
            dataset_root = Path(context["dataset_root"])
            rows = []
            for record in records:
                row = {key: record["sample"][key] for key in SAMPLE_COLUMNS}
                row.update(mask=(output / record["artifacts"]["mask"]["path"]).relative_to(dataset_root).as_posix(), label_status="draft")
                rows.append(row)
            write_table(output / "samples.txt", SAMPLE_COLUMNS, rows)
        run = json.loads((output / "run.json").read_text(encoding="utf-8"))
        run.update(status=report["status"], succeeded=len(records), failed=len(errors),
                   ended_utc=datetime.now(timezone.utc).isoformat())
        save_json(output / "run.json", run)
    return report


def export_editor(draft, output, *, cancel=None, progress=None):
    """Export this folder-workspace's drafts using existing polygon conversion."""
    draft = Path(draft).resolve(strict=True)
    records = json.loads((draft / "manifest.json").read_text(encoding="utf-8"))
    output = check_output([Path(r["source_image"]) for r in records], output)
    if output == draft or output.is_relative_to(draft) or draft.is_relative_to(output):
        raise ValueError("编辑工程与草稿目录应分开")
    output.mkdir(parents=True)
    (output / "images").mkdir()
    saved = []
    save_json(output / "classes.json", {"sky": 0, "water": 1, "ice": 2, "other": 3, "ignore": 255})
    for index, record in enumerate(records):
        if cancel and cancel.is_set():
            break
        source = Path(record["source_image"])
        mask_path = draft / record["artifacts"]["mask"]["path"]
        if digest(source) != record["source_image_sha256"] or digest(mask_path) != record["artifacts"]["mask"]["sha256"]:
            raise ValueError(f"源图或掩码哈希发生变化：{source}")
        mask = np.array(Image.open(mask_path))
        shapes = vectorize(mask)
        image = output / "images" / (record.get("frame_name", record["id"]) + source.suffix.lower())
        data = dict(version="4.0.0", flags={}, shapes=shapes, imagePath=image.name, imageData=None,
                    imageWidth=mask.shape[1], imageHeight=mask.shape[0], checked=False,
                    description="North16 draft; uncovered pixels=ignore (255)")
        if not np.array_equal(render(data), mask):
            raise ValueError("多边形还原未通过，未导出错误标签")
        shutil.copyfile(source, image)
        if digest(image) != record["source_image_sha256"]:
            raise ValueError("图像复制校验失败")
        annotation = image.with_suffix(".json")
        save_json(annotation, data)
        saved.append(dict(id=record["id"], camera=record.get("camera", "folder"), image=image.relative_to(output).as_posix(),
                          sensor=record.get("sensor", "visible"), sequence=record.get("sequence", ""),
                          annotation=annotation.relative_to(output).as_posix(),
                          source_image_sha256=record["source_image_sha256"], initial_json_sha256=digest(annotation)))
        if progress:
            progress(index+1, len(records), source.name)
    if saved:
        with (output / "manifest.txt").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, list(saved[0]), delimiter="\t")
            writer.writeheader();writer.writerows(saved)
    report = dict(status="succeeded" if len(saved) == len(records) else "cancelled", expected=len(records),
                  succeeded=len(saved), pixel_mismatches=0, review_status="unreviewed")
    save_json(output / "validation.json", report)
    if (draft / "dataset.json").is_file():
        shutil.copyfile(draft / "dataset.json", output / "dataset.json")
    save_json(output / "source.json", dict(draft=str(draft), batch=draft.name, manifest_sha256=digest(draft / "manifest.json")))
    (output / "README.txt").write_text("在X-AnyLabeling中打开images文件夹，编辑同名JSON。未覆盖像素=ignore(255)。\n"
        "数据集工程回读：north16 import-labels --project <此工程> --changed-only --preview\n"
        "自动保存到annotations/corrected/<片段>/<模态>/<镜头>/<新批次>，仍需审核。\n"
        "普通文件夹工程需额外指定 --output <新目录>。\n", encoding="utf-8")
    if (output / "dataset.json").is_file():
        from north16.annotations.management import refresh
        refresh(json.loads((output / "dataset.json").read_text(encoding="utf-8"))["dataset_root"])
    return report
