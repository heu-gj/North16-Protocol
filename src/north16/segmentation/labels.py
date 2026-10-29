"""CPU-only JSON label validation/rasterization; no Qt, OpenCV or torch."""
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from north16.common.files import check_size, read_info

CLASSES = dict(sky=0, water=1, ice=2, other=3, ignore=255)


def render(data):
    width, height = data["imageWidth"], data["imageHeight"]
    if not all(isinstance(v,int) and not isinstance(v,bool) and 0<v<=100000 for v in (width,height)):
        raise ValueError("Invalid annotation dimensions")
    canvas=Image.new("L",(width,height),255);draw=ImageDraw.Draw(canvas)
    for shape in data["shapes"]:
        label=shape["label"]
        if label not in CLASSES:raise ValueError(f"Unknown label {label!r}")
        points=np.asarray(shape["points"],dtype=float)
        if points.ndim!=2 or points.shape[1]!=2 or not len(points) or not np.isfinite(points).all():
            raise ValueError("Invalid polygon coordinates")
        if (points<-.5).any() or (points[:,0]>width).any() or (points[:,1]>height).any():
            raise ValueError("Coordinates outside image")
        kind=shape.get("shape_type","polygon")
        if kind in ("polygon","rotation","quadrilateral") and len(points)>=3:
            draw.polygon([tuple(p) for p in points.tolist()],fill=CLASSES[label])
        elif kind=="rectangle" and len(points) in (2,4):
            x0,y0=points.min(axis=0);x1,y1=points.max(axis=0)
            draw.rectangle((x0,y0,x1,y1),fill=CLASSES[label])
        else:raise ValueError(f"Unsupported segmentation shape: {kind}")
    return np.asarray(canvas)


def validate_label(path, image, *, root, expected_id=None, rasterize=True, protocol_id=None):
    path,image,root=Path(path),Path(image).resolve(strict=True),Path(root).resolve(strict=True)
    data=json.loads(path.read_text(encoding="utf-8-sig"))
    metadata=data.get("north16",{})
    relative=image.relative_to(root).as_posix()
    meta_path=image.parent.parent/"meta"/(image.stem+".txt")
    if expected_id is None and meta_path.is_file():expected_id=read_info(meta_path).get("id")
    if metadata.get("image")!=relative:
        raise ValueError("标注原图路径不匹配")
    check_size(image,metadata.get("image_bytes"))
    if expected_id is not None and metadata.get("id")!=expected_id:
        raise ValueError("标注样本ID不匹配")
    if metadata.get("protocol_id")!=(protocol_id or read_info(root/"protocol.txt")["protocol_id"]):
        raise ValueError("标注协议不匹配")
    with Image.open(image) as source:
        if source.size!=(data.get("imageWidth"),data.get("imageHeight")):
            raise ValueError("标注与原图尺寸不匹配")
    if metadata.get("label_status") not in ("draft","reviewed","adjudicated","frozen"):
        raise ValueError("标注状态无效")
    if data.get("imagePath")!="../images/"+image.name:
        raise ValueError("标注imagePath必须指向同镜头images中的原图")
    # Software checked flags never promote a draft to reviewed.
    if metadata["label_status"]!="draft" and (not metadata.get("reviewer") or not metadata.get("reviewed_at")):
        raise ValueError("审核标签缺少reviewer/reviewed_at")
    return (data,render(data) if rasterize else None)
