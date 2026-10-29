"""Deterministic image-based starting parameters, never an accuracy estimate."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import cv2
import numpy as np

from north16.common.files import file_state
from north16.annotations.profiles import DEFAULT_PROFILE, profile_hash, validate_profile
from north16.annotations.workspace import read_image


METHOD = "conservative_color_texture_agreement_otsu_seeds_v2"


def estimate_horizon(rgb, previous):
    """Score broad color transitions over eight strips and a small roll range.

    Broad support helps reject localized ships; it cannot certify a horizon.
    Flat/uninformative frames retain the prior line instead of inventing one.
    """
    h, w = rgb.shape[:2]
    luminance = rgb.astype(np.float32).mean(axis=2)
    contrast = float(np.percentile(luminance, 95)-np.percentile(luminance, 5))
    if contrast < 18:
        return deepcopy(previous), dict(status="retained", reason="整体对比度不足，保留原地平线",
                                        brightness_p95_p5=round(contrast, 3))
    small = cv2.resize(rgb, (480, max(64, round(h*480/w))), interpolation=cv2.INTER_AREA)
    height, width = small.shape[:2]
    smooth = cv2.GaussianBlur(small.astype(np.float32), (0, 0), 2)
    delta = max(2, round(height*.012))
    edge = np.zeros((height, width), np.float32)
    edge[delta:-delta] = np.linalg.norm(smooth[2*delta:]-smooth[:-2*delta], axis=2)/np.sqrt(3)
    # Keep lens edges out of the initial line score.
    xs = np.linspace(round(width*.1), round(width*.9)-1, 160).astype(int)
    candidates = []
    texture_candidates = []
    gray = cv2.GaussianBlur(small.astype(np.float32).mean(axis=2), (0, 0), .7)
    texture = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
    accumulated = np.vstack([np.zeros((1, width), np.float32), np.cumsum(texture, axis=0)])
    radius, gap = max(6, round(height*.06)), max(2, round(height*.012))
    offsets = xs/(width-1)-.5
    for slope in np.linspace(-.12, .12, 17):
        for center in np.arange(round(height*.12), round(height*.76), 2):
            ys = np.rint(center+slope*height*offsets).astype(int)
            ys = np.clip(ys, delta, height-delta-1)
            values = edge[ys, xs]
            strips = np.array([np.mean(v) for v in np.array_split(values, 8)])
            # A short strong edge must not dominate the whole image.
            score = float(.65*np.median(strips)+.35*np.mean(np.sort(strips)[:6]))
            candidates.append((score, float(center/height), float(slope), strips))
            upper = (accumulated[ys-gap, xs]-accumulated[ys-radius, xs])/(radius-gap)
            lower = (accumulated[ys+radius, xs]-accumulated[ys+gap, xs])/(radius-gap)
            ratios = np.array([np.mean(b+1)/np.mean(a+1)
                for a, b in zip(np.array_split(upper, 8), np.array_split(lower, 8))])
            ratio = float(np.median(ratios))
            if ratio >= 2 and np.median(lower) >= 5 and np.median(upper) < 10:
                texture_candidates.append((ratio, float(center/height), float(slope), ratios))
    candidates.sort(key=lambda v: v[0], reverse=True)
    score, center, slope, strips = candidates[0]
    color_center, color_slope = center, slope
    cue = "broad_color_edge"
    texture_ratio = None
    if texture_candidates:
        # Smooth sky followed by textured sea often precedes the strongest ice
        # edge. Choose the uppermost near-maximum onset, not that lower edge.
        maximum = max(c[0] for c in texture_candidates)
        comparable = [c for c in texture_candidates if c[0] >= .97*maximum]
        ratio, center, slope, ratios = min(comparable, key=lambda c: (c[1], abs(c[2])))
        texture_ratio = ratio
        cue = "smooth_to_textured_transition"
        # Keep brightness evidence measured at the chosen line, not the old best.
        selected = min(candidates, key=lambda c: abs(c[1]-center)+abs(c[2]-slope))
        score, _, _, strips = selected
    alternatives = [c[0] for c in candidates if abs(c[1]-center) > .055]
    second = max(alternatives, default=0.)
    margin = float(score/max(second, .01))
    coverage = float(np.mean(strips >= max(3., score*.45)))
    evidence = dict(score=round(score, 3), distinct_peak_ratio=round(margin, 3),
                    strip_support=round(coverage, 3), search_y_fraction=[.12, .76],
                    search_roll_slope=[-.12, .12], cue=cue,
                    texture_transition_ratio=round(texture_ratio, 3) if texture_ratio else None)
    if texture_ratio is not None:
        evidence["cue_center_distance"] = round(abs(center-color_center), 4)
        evidence["cue_slope_distance"] = round(abs(slope-color_slope), 4)
        if abs(center-color_center) > .035 or abs(slope-color_slope) > .045:
            evidence.update(status="retained", reason="颜色边缘与纹理过渡位置不一致，可能存在冰缘干扰；保留当前线，请人工定位")
            return deepcopy(previous), evidence
    if texture_ratio is not None:
        coverage = float(np.mean(ratios >= 1.8))
        evidence["strip_support"] = round(coverage, 3)
    if (score < 3 and texture_ratio is None) or coverage < .5:
        evidence.update(status="retained", reason="未找到覆盖足够宽度的稳定水平边缘，保留原地平线")
        return deepcopy(previous), evidence
    points = [[x, round(float(np.clip(center+slope*(x-.5), .05, .95)), 5)]
              for x in ([0., 1.] if len(previous) == 2 else [0., .25, .5, .75, 1.])]
    # Texture alone is not horizon evidence: distant ice edges have the same
    # smooth-to-textured pattern. Even a large ratio must pass color-edge and
    # ambiguity checks before it can replace the user's line.
    supported = coverage >= .75 and margin >= 1.2 and score >= 8 and abs(slope) < .119
    if not supported:
        evidence.update(status="retained", reason="地平线候选不清晰或存在多个竞争边缘；保留当前线，请人工定位")
        return deepcopy(previous), evidence
    evidence.update(status="suggested", evidence_level="candidate_only",
                    reason=("平滑区域到纹理区域的过渡候选" if texture_ratio else "宽范围颜色过渡候选")+
                           "；船体、岸线或冰缘仍可能产生错误边缘")
    return points, evidence


def estimate_thresholds(rgb, profile):
    """Use Otsu only when there are two sufficiently supported brightness groups."""
    h, w = rgb.shape[:2]
    brightness = rgb.astype(np.float32).mean(axis=2)
    horizon = np.interp(np.arange(w)/max(1, w-1), *np.array(profile["horizon_normalized_xy"]).T)
    sea = np.arange(h)[:, None] > (horizon[None, :]+profile["horizon_ignore_half_height"])*h
    sea[:, :round(w*.08)] = False
    sea[:, round(w*.92):] = False
    values = np.rint(brightness[sea]).clip(0, 255).astype(np.uint8)
    if values.size < 128 or np.ptp(values) < 12:
        return {}, dict(status="retained", reason="海域亮度变化不足，保留原阈值", sample_pixels=int(values.size))
    # Use all pixel counts; capped image dimensions bound the memory/CPU cost.
    threshold, _ = cv2.threshold(values.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    dark, light = values[values <= threshold], values[values > threshold]
    fraction = len(dark)/len(values)
    if not len(dark) or not len(light):
        return {}, dict(status="retained", reason="无法形成两组亮度种子，保留原阈值")
    gap = float(light.mean()-dark.mean())
    total_var = float(values.astype(float).var())
    separation = fraction*(1-fraction)*gap**2/max(total_var, 1e-6)
    evidence = dict(otsu_threshold=int(threshold), darker_fraction=round(fraction, 4),
                    brighter_fraction=round(1-fraction, 4), mean_gap=round(gap, 3),
                    histogram_separation=round(separation, 4), sample_pixels=int(values.size))
    if min(fraction, 1-fraction) < .02 or gap < 25 or separation < .55:
        evidence.update(status="retained", reason="亮暗两组区分不足或占比过小，保留原阈值")
        return {}, evidence
    probable = int(np.clip(round(threshold), 1, 253))
    definite = int(np.clip(np.floor(np.percentile(dark, 35))+1, 1, probable))
    ice = int(np.clip(round(np.percentile(light, 65)), probable+1, 255))
    evidence.update(status="suggested", reason="较暗组作为水域候选、较亮组作为冰面种子；此对应关系需要人工检查")
    return dict(water_definite_brightness_max=definite, water_probable_brightness_max=probable,
                ice_definite_brightness_min=ice), evidence


def estimate_parameters(path, base=None, *, keep_horizon=False):
    """Return suggested parameters and traceable diagnostics without writing files."""
    path = Path(path).resolve(strict=True)
    base = validate_profile(base or DEFAULT_PROFILE)
    before = file_state(path)
    image = read_image(path)
    if min(image.size) < 64 or not .25 <= image.width/image.height <= 4:
        raise ValueError("自动估计适用于至少64×64、宽高比在1:4到4:1之间的相机图像")
    width = min(960, image.width)
    rgb = np.array(image.resize((width, max(32, round(width*image.height/image.width)))))
    profile = deepcopy(base)
    warnings = []
    if keep_horizon:
        horizon = dict(status="preserved", reason="按选项保留当前地平线（位置是否正确仍需人工确认）")
    else:
        points, horizon = estimate_horizon(rgb, base["horizon_normalized_xy"])
        # Keep a non-empty sea region for the selected ignore-band size.
        band = profile["horizon_ignore_half_height"]
        if any(not band < y < 1-band for _, y in points):
            horizon = dict(status="retained", reason="候选线与当前忽略带冲突，保留原地平线")
        else:
            profile["horizon_normalized_xy"] = points
    if horizon["status"] == "retained" or horizon.get("evidence_level") == "weak":
        warnings.append(horizon["reason"])
    if profile["sea_mode"] == "mixed":
        thresholds, brightness = estimate_thresholds(rgb, profile)
    else:
        thresholds = {}
        brightness = dict(status="skipped", reason="用户选择单类海面模式，亮度阈值不参与分割；不会自动切回冰水混合")
    profile.update(thresholds)
    if brightness["status"] == "retained":
        warnings.append(brightness["reason"])
        warnings.append("未可靠分出两组亮度；请检查是否为全冰或全水，必要时人工选择海面模式，不应强行二分")
    profile = validate_profile(profile)
    if file_state(path) != before:
        raise ValueError("估计期间原图发生变化，请重新加载")
    report = dict(method=METHOD, source_image=str(path), source_image_state=before, file_checksum="none",
                  native_size_wh=list(image.size), profile_sha256=profile_hash(profile),
                  base_profile_sha256=profile_hash(base), sea_mode=profile["sea_mode"], horizon=horizon, brightness=brightness,
                  warnings=warnings, review_status="unreviewed",
                  caveat="亮度分组不等于真实冰水标签，不识别薄冰或船体；证据强弱不是分割准确率或概率")
    return profile, report
