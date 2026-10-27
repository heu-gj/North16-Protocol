"""Read camera folders without modifying images or trusting timestamp provenance."""
from pathlib import Path
import re

EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp"}


def discover(root):
    root = Path(root).resolve(strict=True)
    streams = {}
    camera = root / "camera"
    if camera.is_dir():
        for group in camera.iterdir():
            match = re.fullmatch(r"(front|back)_(visible|infrared)", group.name)
            if not match:
                continue
            direction, sensor = match.groups()
            for lens in group.iterdir():
                if lens.is_dir() and re.fullmatch(r"lens_\d+", lens.name):
                    streams[("capture", sensor, direction + "_" + lens.name.split("_")[-1])] = lens
    sequences = root / "sequences"
    if sequences.is_dir():
        for path in sequences.glob("*/*/*/images"):
            sequence, sensor, camera_name, _ = path.relative_to(sequences).parts
            if sensor in ("visible", "infrared"):
                streams[(sequence, sensor, camera_name)] = path
    pairs = {}
    for (sequence, sensor, camera_name), path in streams.items():
        if sensor != "visible" or (sequence, "infrared", camera_name) not in streams:
            continue
        visible = image_map(path)
        infrared = image_map(streams[(sequence, "infrared", camera_name)])
        shared = sorted(visible.keys() & infrared.keys())
        if shared:
            pairs[(sequence, camera_name)] = [(name, visible[name], infrared[name]) for name in shared]
    if not pairs:
        raise ValueError("未找到可见光/红外共同文件名。支持camera/front_visible/lens_01及north16 sequences布局")
    return pairs


def image_map(folder):
    result = {}
    for path in Path(folder).iterdir():
        if path.is_file() and path.suffix.lower() in EXTENSIONS:
            if path.stem in result:
                raise ValueError(f"同名图像身份冲突：{path.stem}")
            result[path.stem] = path.resolve()
    return result
