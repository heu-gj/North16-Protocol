"""Versioned registration projects and native-resolution derived images."""
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

import numpy as np
from PIL import Image

from north16.common.files import sha256
from .geometry import warp, validate_matrix


def load_rgb(path):
    with Image.open(path) as image:
        if image.mode not in ("RGB", "RGBA", "L", "P"):
            raise ValueError("仅支持8位显示图像；不转换原始16位辐射数据")
        return np.array(image.convert("RGB"))


def save_project(output_root, dataset_root, pair_key, stamp, visible_path, infrared_path,
                 observations, result=None, export_images=True):
    output_root = Path(output_root).resolve()
    dataset_root = Path(dataset_root).resolve(strict=True)
    # Never write to camera/sequence assets, protocol, or any ancestor of inputs.
    sources = [Path(visible_path).resolve(strict=True), Path(infrared_path).resolve(strict=True)]
    if any(output_root == p.parent or output_root.is_relative_to(p.parent) or p.is_relative_to(output_root) for p in sources):
        raise ValueError("输出必须与源图片目录分开，且不能作为原图的父目录")
    sequence, camera = pair_key
    batch = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    destination = output_root / sequence / camera / batch
    if not destination.resolve().is_relative_to(output_root):
        raise ValueError("不安全的片段或相机名称")
    if result is not None:
        visible, infrared = map(load_rgb, sources)
        if list(visible.shape[1::-1]) != result["target_size_wh"] or list(infrared.shape[1::-1]) != result["source_size_wh"]:
            raise ValueError("当前图像尺寸与求解变换不一致")
        validate_matrix(result["matrix"], result["source_size_wh"], result["target_size_wh"])
    # Snapshot the images involved in annotations, not only the current frame.
    files = set(sources)
    for value in observations.values():
        for key in ("visible_path", "infrared_path"):
            if value.get(key):
                files.add(Path(value[key]).resolve(strict=True))
    snapshots = {str(p): sha256(p) for p in sorted(files)}
    destination.mkdir(parents=True, exist_ok=False)
    report = dict(schema="north16_registration_project_v1", status="candidate_unreviewed", task="image_registration",
                  created_utc=datetime.now(timezone.utc).isoformat(), dataset_root=str(dataset_root),
                  sequence=sequence, camera=camera, stamp=stamp,
                  visible_path=str(sources[0]), infrared_path=str(sources[1]), source_sha256=snapshots,
                  observations=observations, result=result,
                  timestamp_status="filename_candidate_not_hardware_verified",
                  metric_calibration=False, raw_images_modified=False)
    try:
        (destination / "project.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if result is not None and export_images:
            registered, valid = warp(infrared, result["matrix"], result["target_size_wh"])
            Image.fromarray(registered).save(destination / "infrared_registered.png")
            Image.fromarray(valid).save(destination / "valid.png")
            overlay = visible.copy()
            inside = valid != 0
            overlay[inside] = ((visible[inside].astype(np.float32)+registered[inside])/2).astype(np.uint8)
            Image.fromarray(overlay).save(destination / "overlay.jpg", quality=92)
        if any(sha256(Path(p)) != value for p, value in snapshots.items()):
            raise ValueError("保存期间源图片发生变化")
        artifacts = {p.name: sha256(p) for p in destination.iterdir() if p.is_file()}
        (destination / "checksums.json").write_text(json.dumps(artifacts, indent=2), encoding="utf-8")
    except Exception:
        (destination / "FAILED.txt").write_text("保存未完成，请勿使用此批次。源图片未改写。", encoding="utf-8")
        raise
    return destination


def read_project(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != "north16_registration_project_v1":
        raise ValueError("不支持的配准工程")
    for source, digest in data["source_sha256"].items():
        if sha256(Path(source)) != digest:
            raise ValueError(f"源图不存在或内容变化：{source}")
    return data
