"""The camera/segmentation path contract; no filesystem side effects."""
from pathlib import PurePosixPath
import re


def stream_path(sequence, sensor, camera):
    if sensor not in ("visible", "infrared") or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*",v) for v in (sequence,camera)):
        raise ValueError("无效的片段、模态或镜头身份")
    return PurePosixPath("sequences",sequence,sensor,camera)


def label_path(image):
    image=PurePosixPath(image)
    if len(image.parts)!=6 or image.parts[4]!="images" or image.suffix!=".png":
        raise ValueError("图像必须使用sequences/<片段>/<模态>/<镜头>/images/*.png")
    if PurePosixPath(*image.parts[:4])!=stream_path(*image.parts[1:4]):
        raise ValueError("无效图像路径")
    return image.parent.parent/"masks"/(image.stem+".json")
