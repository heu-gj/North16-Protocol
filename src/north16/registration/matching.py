"""Classical cross-modal matching, with rejection rather than forced alignment."""
import cv2
import numpy as np
from .geometry import fit


def resize_gray(image, width=1280):
    height, original_width = image.shape[:2]
    size = (min(width, original_width), max(1, round(height*min(1, width/original_width))))
    gray = cv2.cvtColor(cv2.resize(image, size), cv2.COLOR_RGB2GRAY)
    return cv2.createCLAHE(2, (8, 8)).apply(gray), np.array([original_width/size[0], height/size[1]])


def gradient(gray):
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    magnitude = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))
    return cv2.normalize(magnitude, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def roi_mask(gray, scale, boxes):
    if not boxes:
        return None
    mask = np.zeros(gray.shape, np.uint8)
    for box in boxes:
        x1, y1, x2, y2 = np.asarray(box, np.float64)/np.tile(scale, 2)
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(gray.shape[1], int(x2)+1), min(gray.shape[0], int(y2)+1)
        mask[y1:y2, x1:x2] = 255
    return mask


def auto_register(visible, infrared, model="homography", box_pairs=None):
    if visible.max() == visible.min() or infrared.max() == infrared.min():
        raise ValueError("输入包含纯色/黑图，无法匹配")
    visible_gray, visible_scale = resize_gray(visible)
    infrared_gray, infrared_scale = resize_gray(infrared)
    sift = cv2.SIFT_create(nfeatures=6000, contrastThreshold=.015)
    candidates, failures = [], []
    groups = box_pairs or [None]
    for mode in ("normal", "inverted_infrared", "gradient"):
        a, b = infrared_gray, visible_gray
        if mode == "inverted_infrared":
            a = 255-a
        elif mode == "gradient":
            a, b = gradient(a), gradient(b)
        points = []
        for region_index, pair in enumerate(groups):
            amask = roi_mask(a, infrared_scale, [pair["infrared"]]) if pair else None
            bmask = roi_mask(b, visible_scale, [pair["visible"]]) if pair else None
            k1, d1 = sift.detectAndCompute(a, amask)
            k2, d2 = sift.detectAndCompute(b, bmask)
            if d1 is None or d2 is None or len(d2) < 2:
                continue
            for matches in cv2.BFMatcher().knnMatch(d1, d2, k=2):
                if len(matches) != 2:
                    continue
                first, second = matches
                if first.distance < .78*second.distance:
                    points.append(dict(infrared=(np.array(k1[first.queryIdx].pt)*infrared_scale).tolist(),
                                       visible=(np.array(k2[first.trainIdx].pt)*visible_scale).tolist(),
                                       role="fit", source=mode, region=region_index if pair else None))
        # One target keypoint must not count repeatedly toward geometric support.
        unique = {}
        for point in points:
            unique.setdefault(tuple(round(x, 2) for x in point["visible"]), point)
        points = list(unique.values())
        try:
            result = fit(points, model, infrared.shape[1::-1], visible.shape[1::-1],
                         threshold=4*max(visible_scale), automatic=True)
            for i, good in zip(result["fit_indices"], result["inliers"]):
                if not good:
                    points[i]["role"] = "reject"
            result.update(method="SIFT_CLAHE_RANSAC", variant=mode, ship_roi_pairs=len(box_pairs or []))
            candidates.append((result["inlier_count"]*result["coverage"]**.25, points, result))
        except ValueError as exc:
            failures.append(f"{mode}: {exc}")
    if not candidates:
        raise ValueError("自动配准未通过几何检查。请选对应点、关联船框或换帧。\n"+"\n".join(failures))
    _, points, result = max(candidates, key=lambda x: x[0])
    result["attempt_failures"] = failures
    return points, result
