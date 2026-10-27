"""Fit IR-to-visible transforms in native image coordinates with sanity checks."""
import cv2
import numpy as np


def project(matrix, points):
    return cv2.perspectiveTransform(np.asarray(points, np.float64).reshape(-1, 1, 2), np.asarray(matrix, np.float64)).reshape(-1, 2)


def coverage(points, size):
    if len(points) < 3:
        return 0.0
    return float(cv2.contourArea(cv2.convexHull(np.float32(points)))) / (size[0] * size[1])


def validate_matrix(matrix, source_size, target_size):
    matrix = np.asarray(matrix, np.float64)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all() or abs(np.linalg.det(matrix)) < 1e-12:
        raise ValueError("变换退化或非有限值")
    w, h = source_size
    corners = np.float64([[0, 0], [w-1, 0], [w-1, h-1], [0, h-1]])
    denominator = np.c_[corners, np.ones(4)] @ matrix[2]
    if np.any(np.abs(denominator) < 1e-8) or not (np.all(denominator > 0) or np.all(denominator < 0)):
        raise ValueError("变换在图像内出现投影奇点")
    warped = project(matrix, corners).astype(np.float32)
    if not np.isfinite(warped).all() or not cv2.isContourConvex(warped):
        raise ValueError("变换后图像边界异常")
    area = float(cv2.contourArea(warped, oriented=True))
    ratio = area / (target_size[0] * target_size[1])
    if not .03 < ratio < 15:
        raise ValueError("变换产生翻转、坍缩或异常尺度")
    rect = np.float32([[0, 0], [target_size[0]-1, 0], [target_size[0]-1, target_size[1]-1], [0, target_size[1]-1]])
    intersection, _ = cv2.intersectConvexConvex(warped, rect)
    if intersection / min(area, target_size[0]*target_size[1]) < .05:
        raise ValueError("变换后共同视场过小")
    return matrix / matrix[2, 2]


def fit(points, model, source_size, target_size, threshold=8.0, automatic=False):
    selected = [(i, p) for i, p in enumerate(points) if p.get("role", "fit") == "fit"]
    minimum = 4 if model == "homography" else 3
    if len(selected) < minimum:
        raise ValueError(f"{model}至少需要{minimum}对非共线拟合点；检查点不参与求解")
    indices, records = zip(*selected)
    source = np.float64([p["infrared"] for p in records])
    target = np.float64([p["visible"] for p in records])
    if coverage(source, source_size) < .0001 or coverage(target, target_size) < .0001:
        raise ValueError("对应点近乎共线或过度集中，请增加分布在不同位置的点")
    cv2.setRNGSeed(42)
    if model == "homography":
        matrix, inliers = cv2.findHomography(source, target, cv2.RANSAC, threshold, maxIters=10000, confidence=.999)
    else:
        affine, inliers = cv2.estimateAffine2D(source, target, method=cv2.RANSAC, ransacReprojThreshold=threshold,
                                              maxIters=10000, confidence=.999)
        matrix = np.vstack([affine, [0, 0, 1]]) if affine is not None else None
    if matrix is None or inliers is None:
        raise ValueError("无法求得稳定变换，请检查对应点")
    inliers = inliers.ravel().astype(bool)
    count = int(inliers.sum())
    needed = (12 if model == "homography" else 8) if automatic else minimum
    if count < needed:
        raise ValueError(f"可靠内点只有{count}，当前要求至少{needed}；请补人工点或换帧")
    matrix = validate_matrix(matrix, source_size, target_size)
    cov = min(coverage(source[inliers], source_size), coverage(target[inliers], target_size))
    if automatic and (cov < .003 or count / len(source) < .15):
        raise ValueError("自动匹配内点分布或比例不足，拒绝生成配准候选")
    errors = np.linalg.norm(project(matrix, source)-target, axis=1)
    checks = [p for p in points if p.get("role") == "check"]
    check_errors = np.linalg.norm(project(matrix, [p["infrared"] for p in checks]) - np.float64([p["visible"] for p in checks]), axis=1) if checks else np.array([])
    return dict(matrix=matrix.tolist(), model=model, direction="infrared_to_visible", status="candidate_unreviewed",
                source_size_wh=list(source_size), target_size_wh=list(target_size),
                fit_indices=list(indices), inliers=inliers.tolist(), inlier_count=count, fit_count=len(source),
                median_inlier_error_px=float(np.median(errors[inliers])), coverage=cov,
                check_errors_px=check_errors.tolist(), check_count=len(checks),
                warning="匹配残差不是独立准确率；存在距离相关视差，需独立检查点及跨场景验证")


def warp(infrared, matrix, target_size):
    image = cv2.warpPerspective(infrared, np.asarray(matrix), tuple(target_size), flags=cv2.INTER_LINEAR)
    valid = cv2.warpPerspective(np.full(infrared.shape[:2], 255, np.uint8), np.asarray(matrix), tuple(target_size), flags=cv2.INTER_NEAREST)
    return image, valid
