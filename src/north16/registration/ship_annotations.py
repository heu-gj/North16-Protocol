"""Explicit ship regions from X-AnyLabeling or COCO; regions are not keypoints."""
import json
from pathlib import Path
import numpy as np


def is_ship(label):
    return any(word in str(label).lower() for word in ("boat", "ship", "cargo", "vessel", "tug", "船"))


def read_boxes(annotation_path, image_path, image_size):
    path=Path(annotation_path).resolve(strict=True)
    data=json.loads(path.read_text(encoding="utf-8"));image_path=Path(image_path)
    boxes=[]
    if "shapes" in data:
        if Path(data["imagePath"]).name != image_path.name or (data["imageWidth"],data["imageHeight"]) != tuple(image_size):
            raise ValueError("标注图像名称或尺寸与当前图片不一致")
        for shape in data["shapes"]:
            if is_ship(shape["label"]) and shape.get("shape_type") in ("rectangle","polygon","rotation","quadrilateral"):
                points=np.asarray(shape["points"],np.float64)
                if points.ndim != 2 or points.shape[1]!=2 or len(points)<2:raise ValueError("船只形状坐标异常")
                boxes.append(dict(xyxy=[*points.min(axis=0),*points.max(axis=0)],label=shape["label"]))
    elif "images" in data and "annotations" in data:
        candidates=[i for i in data["images"] if Path(i["file_name"]).name==image_path.name]
        if len(candidates)!=1:raise ValueError("COCO中图像名不存在或重复，请导出当前镜头的独立标注文件")
        image=candidates[0]
        if (image["width"],image["height"])!=tuple(image_size):raise ValueError("COCO图像尺寸不一致")
        categories={c["id"]:c["name"] for c in data["categories"]}
        for item in data["annotations"]:
            label=categories.get(item["category_id"],"")
            if item["image_id"]==image["id"] and is_ship(label):
                x,y,w,h=map(float,item["bbox"])
                boxes.append(dict(xyxy=[x,y,x+w,y+h],label=label))
    else:raise ValueError("需要X-AnyLabeling或COCO JSON")
    for box in boxes:
        xy=np.asarray(box["xyxy"],np.float64)
        if not np.isfinite(xy).all() or not (0<=xy[0]<xy[2]<=image_size[0] and 0<=xy[1]<xy[3]<=image_size[1]):
            raise ValueError("船框越界或退化，请先修正标注")
        box.update(xyxy=xy.tolist(),source="annotation_import",annotation_path=str(path),confidence=1.,review_status="imported_not_verified")
    return boxes
