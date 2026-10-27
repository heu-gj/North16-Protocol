"""Validated GrabCut parameter profiles shared by the GUI and command line."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path


DEFAULT_PROFILE = {
    "sea_mode": "mixed",
    "working_wh": [1280, 720],
    "horizon_normalized_xy": [[0, .475], [.25, .472], [.5, .472], [.75, .465], [1, .455]],
    "horizon_ignore_half_height": .01,
    "water_definite_brightness_max": 78,
    "water_probable_brightness_max": 125,
    "ice_definite_brightness_min": 168,
    "grabcut_iterations": 5,
    "rng_seed": 42,
    "boundary_ignore_kernel": [3, 3],
}


def validate_profile(profile):
    result = deepcopy(profile)
    # Profiles made before 0.4.1 used only mixed ice/water segmentation.
    result.setdefault("sea_mode", "mixed")
    for key in DEFAULT_PROFILE:
        if key not in result:
            raise ValueError(f"缺少参数：{key}")
    result = {key: result[key] for key in DEFAULT_PROFILE}
    if result["sea_mode"] not in {"mixed", "ice_only", "water_only"}:
        raise ValueError("海面模式必须为mixed、ice_only或water_only")
    width = result["working_wh"][0]
    if type(width) is not int or not 256 <= width <= 4096:
        raise ValueError("工作宽度应为256–4096像素")
    result["working_wh"] = [width, round(width * 9 / 16)]
    keys = ["water_definite_brightness_max", "water_probable_brightness_max", "ice_definite_brightness_min"]
    a, b, c = [result[k] for k in keys]
    if any(type(v) is not int for v in (a, b, c)) or not 0 <= a <= b < c <= 255:
        raise ValueError("亮度阈值需满足：0 ≤ 确定水域 ≤ 候选水域 < 确定冰面 ≤ 255")
    band = result["horizon_ignore_half_height"]
    if not isinstance(band, (float, int)) or not math.isfinite(band) or not 0 <= band <= .2:
        raise ValueError("地平线忽略半宽应为图高的0–20%")
    points = result["horizon_normalized_xy"]
    if not isinstance(points, list) or not 2 <= len(points) <= 32:
        raise ValueError("地平线需包含2–32个控制点")
    last = -1
    for point in points:
        if len(point) != 2 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in point):
            raise ValueError("地平线坐标必须是有限数值")
        x, y = point
        if not last < x <= 1 or not band < y < 1 - band:
            raise ValueError("地平线横坐标需递增，且忽略带应位于图像内部")
        last = x
    if points[0][0] != 0 or points[-1][0] != 1:
        raise ValueError("地平线必须覆盖图像左右边缘")
    kernel = result["boundary_ignore_kernel"]
    if len(kernel) != 2 or any(type(v) is not int or v not in range(1, 16, 2) for v in kernel):
        raise ValueError("边界核应为1–15之间的奇数；1表示不扩展边界")
    iterations, seed = result["grabcut_iterations"], result["rng_seed"]
    if type(iterations) is not int or not 1 <= iterations <= 20:
        raise ValueError("迭代次数应为1–20")
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError("随机种子应为0–2147483647")
    return result


def profile_hash(profile):
    normalized = validate_profile(profile)
    # Explicit mixed is semantically identical to older omitted defaults.
    if normalized["sea_mode"] == "mixed":
        normalized.pop("sea_mode")
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_profile(path):
    return validate_profile(json.loads(Path(path).read_text(encoding="utf-8-sig")))
