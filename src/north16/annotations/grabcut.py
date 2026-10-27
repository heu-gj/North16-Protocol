"""Reproducible fixed-profile GrabCut drafts, resumable and separate from gold."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from north16.common.files import read_info, read_table, write_info, write_table, write_text


PALETTE = {0: (90, 170, 240), 1: (20, 75, 170), 2: (245, 215, 80),
           3: (210, 80, 175), 255: (110, 110, 110)}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def segmentation_method(profile):
    mode = profile.get('sea_mode', 'mixed')
    if mode not in {'mixed', 'ice_only', 'water_only'}:
        raise ValueError('Unknown sea mode')
    return 'brightness_seeded_GrabCut' if mode == 'mixed' else 'user_assigned_' + mode


def segment(image, profile, *, internal_threads=4):
    from north16.annotations.runtime import opencv_threads
    with opencv_threads(internal_threads):
        return _segment(image, profile)


def _segment(image, profile):
    """Mixed preserves the original graph cut; explicit single classes skip it."""
    mode = profile.get('sea_mode', 'mixed')
    segmentation_method(profile)  # Reject unknown modes instead of silently mixing.
    if mode != 'mixed':
        # This is a user declaration about the visible sea surface, not a model
        # detecting absence of a class. Preserve native geometry and the band.
        width, height = image.size
        horizon = np.interp(np.arange(width)/max(1, width-1), *np.array(profile['horizon_normalized_xy']).T)*height
        rows = np.arange(height)[:, None]
        band = profile['horizon_ignore_half_height']*height
        mask = np.full((height, width), 255, np.uint8)
        mask[np.broadcast_to(rows < horizon[None, :]-band, mask.shape)] = 0
        mask[np.broadcast_to(rows > horizon[None, :]+band, mask.shape)] = 2 if mode == 'ice_only' else 1
        return mask
    w = profile['working_wh'][0]
    h = round(image.height * w / image.width)
    rgb = np.array(image.resize((w, h), Image.Resampling.LANCZOS))
    brightness = rgb.astype(np.float32).mean(2)
    horizon = np.interp(np.arange(w) / (w - 1), *np.array(profile['horizon_normalized_xy']).T) * h
    rows = np.arange(h)[:, None]
    sea = rows > horizon[None, :] + profile['horizon_ignore_half_height'] * h
    sky = rows < horizon[None, :] - profile['horizon_ignore_half_height'] * h
    seeds = np.full((h, w), cv2.GC_PR_BGD, dtype=np.uint8)
    seeds[sea & (brightness < profile['water_probable_brightness_max'])] = cv2.GC_PR_FGD
    seeds[sea & (brightness < profile['water_definite_brightness_max'])] = cv2.GC_FGD
    seeds[sea & (brightness > profile['ice_definite_brightness_min'])] = cv2.GC_BGD
    seeds[~sea] = cv2.GC_BGD
    y0 = int(np.min(horizon + profile['horizon_ignore_half_height'] * h))
    roi = np.ascontiguousarray(rgb[y0:, :, ::-1])
    labels = seeds[y0:].copy()
    cv2.setRNGSeed(profile['rng_seed'])
    bg, fg = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(roi, labels, None, bg, fg, profile['grabcut_iterations'], cv2.GC_INIT_WITH_MASK)
    water = np.zeros((h, w), bool)
    water[y0:] = np.isin(labels, [cv2.GC_FGD, cv2.GC_PR_FGD])
    water &= sea
    mask = np.full((h, w), 255, np.uint8)
    mask[sky] = 0
    mask[sea] = 2
    mask[water] = 1
    edge = cv2.morphologyEx(water.astype(np.uint8), cv2.MORPH_GRADIENT,
                           np.ones(tuple(profile['boundary_ignore_kernel']), np.uint8)) > 0
    mask[edge & sea] = 255
    return np.asarray(Image.fromarray(mask).resize(image.size, Image.Resampling.NEAREST))


def atomic_image(image, path, **kwargs):
    tmp = path.with_name(path.stem + '.partial' + path.suffix)
    try:
        image.save(tmp, **kwargs)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def process_one(task):
    started = time.monotonic()
    root, output = Path(task['root']), Path(task['output'])
    row, profile = task['row'], task['profile']
    stream = output / 'visible' / row['camera']
    stem = Path(row['image']).stem
    receipt = stream / 'meta' / f'{stem}.json'
    paths = {'mask': stream / 'masks' / f'{stem}.png',
             'color': stream / 'color' / f'{stem}.png',
             'overlay': stream / 'overlay' / f'{stem}.jpg'}
    try:
        if receipt.exists():
            old = json.loads(receipt.read_text(encoding='utf-8'))
            if old['source_id'] != row['id'] or old['profile_sha256'] != task['profile_sha256']:
                raise ValueError('Existing result identity/profile conflict.')
            for k, p in paths.items():
                if digest(p) != old['artifacts'][k]['sha256']:
                    raise ValueError(f'Existing artifact hash mismatch: {p}')
            if digest(root / row['image']) != old['source_image_sha256']:
                raise ValueError('Existing source image hash mismatch.')
            return dict(status='reused', id=row['id'], camera=row['camera'], meta=str(receipt), seconds=0)
        source = root / row['image']
        meta = read_info(root / row['meta'])
        if meta['id'] != row['id'] or digest(source) != meta['image_sha256']:
            raise ValueError('Source observation identity/hash mismatch.')
        image = Image.open(source).convert('RGB')
        mask = segment(image, profile)
        if mask.dtype != np.uint8 or mask.shape != (image.height, image.width):
            raise ValueError('Invalid mask geometry/type.')
        if not set(np.unique(mask)).issubset(PALETTE):
            raise ValueError('Invalid mask class IDs.')
        lut = np.zeros((256, 3), dtype=np.uint8)
        for label, color in PALETTE.items():
            lut[label] = color
        color = Image.fromarray(lut[mask])
        overlay = Image.blend(image, color, .42)
        atomic_image(Image.fromarray(mask), paths['mask'], format='PNG', compress_level=3)
        atomic_image(color, paths['color'], format='PNG', compress_level=3)
        atomic_image(overlay, paths['overlay'], format='JPEG', quality=92, subsampling=0)
        # Fully reopen every saved label, so partial/corrupt outputs cannot commit.
        saved = np.asarray(Image.open(paths['mask']))
        if not np.array_equal(saved, mask):
            raise ValueError('Mask round-trip mismatch.')
        counts = {str(k): int((mask == k).sum()) for k in PALETTE}
        result = dict(schema_version='north16_grabcut_draft_v1', source_id=row['id'],
                      source_image=row['image'], source_meta=row['meta'], source_image_sha256=meta['image_sha256'],
                      sequence=row['sequence'], camera=row['camera'], sensor='visible',
                      label_status='draft', review_status='unreviewed',
                      method='fixed_profile_brightness_seeded_GrabCut' if profile.get('sea_mode','mixed') == 'mixed' else segmentation_method(profile),
                      sea_mode=profile.get('sea_mode','mixed'),
                      profile_sha256=task['profile_sha256'], profile='parameters.json',
                      parameters=profile, per_image_tuning=False, other_class_supported=False,
                      native_size_wh=list(image.size), pixel_counts=counts,
                      artifacts={k: {'path': p.relative_to(output).as_posix(), 'sha256': digest(p)} for k, p in paths.items()},
                      source_image_quality_flags=meta.get('image_quality_flags', 'unknown'),
                      view_type=meta.get('view_type', 'unknown'), opencv=cv2.__version__,
                      seconds=round(time.monotonic() - started, 3))
        write_text(receipt, json.dumps(result, ensure_ascii=False, indent=2), durable=False)
        return dict(status='generated', id=row['id'], camera=row['camera'], meta=str(receipt), seconds=result['seconds'])
    except Exception as exc:
        return dict(status='failed', id=row['id'], camera=row['camera'],
                    error_type=type(exc).__name__, error=str(exc), seconds=round(time.monotonic() - started, 3))


def previews(root, output, rows):
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 18)
    title_font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 23)
    overview = Image.new('RGB', (1600, 8 * 250 + 85), '#f5f7fa')
    d = ImageDraw.Draw(overview)
    d.text((10, 5), '第一片段 · 16 路可见光 · 固定 GrabCut 参数 / draft', font=title_font, fill='black')
    for j, cam in enumerate(sorted({r['camera'] for r in rows})):
        members = [r for r in rows if r['camera'] == cam]
        selected = [members[i] for i in sorted({0, len(members)//2, len(members)-1})]
        sheet = Image.new('RGB', (1440, 3 * 302 + 40), '#f5f7fa')
        draw = ImageDraw.Draw(sheet)
        draw.text((5, 5), f'{cam} / 开头、中间、末尾 / 原图、叠加、彩色标签', font=title_font, fill='black')
        for i, row in enumerate(selected):
            stem = Path(row['image']).stem
            stream = output / 'visible' / cam
            draw.text((5, 42+i*302), stem, font=font, fill='black')
            for col, path in enumerate([root/row['image'], stream/'overlay'/f'{stem}.jpg', stream/'color'/f'{stem}.png']):
                if path.exists():
                    with Image.open(path) as im:
                        thumb = im.convert('RGB').resize((480, 270), Image.Resampling.NEAREST if col == 2 else Image.Resampling.LANCZOS)
                        sheet.paste(thumb, (col*480, 68+i*302))
            if i == 1:
                x, y = (j % 2)*800, 65+(j//2)*250
                d.text((x+5, y), f'{cam} / {stem} / 原图 → 叠加', font=font, fill='black')
                for col, p in enumerate([root/row['image'], stream/'overlay'/f'{stem}.jpg']):
                    if p.exists():
                        with Image.open(p) as im:
                            overview.paste(im.convert('RGB').resize((400,225)), (x+col*400, y+25))
        atomic_image(sheet, output/'previews'/f'{cam}.jpg', format='JPEG', quality=92)
    atomic_image(overview, output/'preview.jpg', format='JPEG', quality=92)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--sequence', required=True)
    p.add_argument('--profile', type=Path, required=True)
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--workers', type=int, default=6)
    p.add_argument('--resume', action='store_true')
    args = p.parse_args(argv)
    root = args.root.resolve(strict=True)
    output = args.output.resolve()
    if not output.is_relative_to(root/'annotations') or output == root/'annotations':
        raise ValueError('Draft output must be a dedicated directory below dataset annotations/.')
    profile = json.loads(args.profile.read_text(encoding='utf-8'))
    profile_sha = hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    rows = [r for r in read_table(root/'samples.txt') if r['sequence'] == args.sequence and r['sensor'] == 'visible']
    if not rows or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Empty or duplicate input observations.')
    for r in rows:
        if not (root/r['image']).resolve().is_relative_to(root):
            raise ValueError('Unsafe source path.')
    expected = Counter(r['camera'] for r in rows)
    if output.exists():
        if not args.resume:
            raise ValueError('Existing output requires --resume; no overwrite.')
        previous = json.loads((output/'run.json').read_text(encoding='utf-8'))
        if previous['profile_sha256'] != profile_sha or previous['sequence'] != args.sequence or previous['source_samples_sha256'] != digest(root/'samples.txt'):
            raise ValueError('Resume profile/sequence/input manifest conflict.')
    reference = json.loads((args.reference/'info.json').read_text(encoding='utf-8'))
    ref_image = Image.open(reference['source_image']).convert('RGB')
    if not np.array_equal(segment(ref_image, profile), np.asarray(Image.open(args.reference/'mask.png'))):
        raise ValueError('Fixed profile did not reproduce the previous mask exactly.')
    needed = sum((root/r['image']).stat().st_size for r in rows) * .8 + 2*1024**3
    if shutil.disk_usage(root).free < needed:
        raise ValueError('Insufficient estimated disk headroom.')
    output.mkdir(parents=True, exist_ok=True)
    (output/'previews').mkdir(exist_ok=True)
    for camera in expected:
        for directory in ['masks', 'color', 'overlay', 'meta']:
            (output/'visible'/camera/directory).mkdir(parents=True, exist_ok=True)
    for file, data in [('parameters.json', profile), ('run.json', dict(sequence=args.sequence, sensor='visible',
            frames=len(rows), streams=len(expected), profile_sha256=profile_sha, workers=args.workers,
            source_samples_sha256=digest(root/'samples.txt'), source_meta_registry=read_info(root/'info.txt').get('attribute_registry'),
            started_at_utc=datetime.now(timezone.utc).isoformat(), original_mask_exact_reproduction=True,
            expected=dict(expected), output_disk_estimate_bytes=int(needed)))]:
        write_text(output/file, json.dumps(data, ensure_ascii=False, indent=2))
    if Path(__file__).resolve() != (output/'grabcut.py').resolve():
        shutil.copy2(__file__, output/'grabcut.py')
    write_text(output/'README.md', '''# 第一片段固定参数 GrabCut 草稿

范围：20260902_044232 的全部 visible，16 路镜头。全部使用原第4路示例参数，无逐图/逐镜头调参。parameters.json 是唯一参数快照。

visible/<camera>/masks/*.png 为原图尺寸 uint8 标签，color/*.png 为彩色图，overlay/*.jpg 为原尺寸叠加图，meta/*.json 保存原图引用、哈希、运行参数与输出哈希。原图只引用，不重复复制。samples.txt 是此草稿独立清单，不代替根数据集正式索引。

天空0浅蓝、水1深蓝、冰2黄、其他3（当前算法不支持）、忽略255灰。固定地平线来自后向第4路，不自动适配镜头方向/船体/姿态；其他类不支持，船体与设备会被误分。薄冰、碎冰、反光、暗角和尾流可能混淆。所有结果为 draft/unreviewed，不直接成为训练或评测真值。

preview.jpg 汇总16镜头的中间帧；previews/<camera>.jpg 为开头/中间/末尾的原图、叠加、彩色图。summary.txt 为每路像素面积与运行状态，不代表准确率；errors.txt 保存失败，无伪造替代mask。progress.json 是进度；validation.json 是全量完成后的格式与完整性检查。支持 --resume 按源图/输出哈希校验复用已完成结果。
''')
    started = time.monotonic()
    done, status, events = Counter(), Counter(), []
    completed = []
    tasks = [dict(root=str(root), output=str(output), row=row, profile=profile, profile_sha256=profile_sha) for row in rows]
    last_report = 0
    with (output/'events.jsonl').open('a', encoding='utf-8', buffering=1) as log:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            pending = {executor.submit(process_one, t): t['row'] for t in tasks}
            for future in as_completed(pending):
                result = future.result()
                events.append(result)
                status[result['status']] += 1
                done[result['camera']] += 1
                log.write(json.dumps(result, ensure_ascii=False)+'\n')
                if result['status'] != 'failed':
                    completed.append(pending[future])
                n = len(events)
                if n % 50 == 0 or time.monotonic()-last_report > 25 or n == len(rows):
                    elapsed = time.monotonic()-started
                    progress = dict(status='running', completed=n, expected=len(rows), succeeded=len(completed),
                                    failed=status['failed'], reused=status['reused'], elapsed_seconds=round(elapsed,1),
                                    estimated_remaining_seconds=round(elapsed/n*(len(rows)-n)), by_camera=dict(done))
                    write_text(output/'progress.json', json.dumps(progress, indent=2), durable=False)
                    print(json.dumps(progress), flush=True)
                    last_report = time.monotonic()
    errors = [dict(id=e['id'], camera=e['camera'], error_type=e['error_type'], error=e['error'].replace('\n',' ')) for e in events if e['status']=='failed']
    write_table(output/'errors.txt', ['id','camera','error_type','error'], errors)
    catalog, camera_stats = [], {}
    for row in rows:
        stem = Path(row['image']).stem
        receipt = output/'visible'/row['camera']/'meta'/f'{stem}.json'
        if not receipt.exists():
            continue
        meta = json.loads(receipt.read_text(encoding='utf-8'))
        if meta['source_id'] != row['id'] or meta['profile_sha256'] != profile_sha:
            raise ValueError('Final receipt identity/profile mismatch.')
        for k, artifact in meta['artifacts'].items():
            if digest(output/artifact['path']) != artifact['sha256']:
                raise ValueError(f'Final artifact hash mismatch: {row["id"]}/{k}')
        counts = meta['pixel_counts']
        stats = camera_stats.setdefault(row['camera'], Counter())
        stats.update({f'class_{k}': n for k,n in counts.items()})
        stats['success'] += 1
        catalog.append(dict(id=row['id'], source_image=row['image'], mask=meta['artifacts']['mask']['path'],
                            color=meta['artifacts']['color']['path'], overlay=meta['artifacts']['overlay']['path'],
                            meta=receipt.relative_to(output).as_posix(), label_status='draft', review_status='unreviewed'))
    write_table(output/'samples.txt', ['id','source_image','mask','color','overlay','meta','label_status','review_status'], catalog)
    summaries = [dict(camera=cam, expected=expected[cam], succeeded=camera_stats.get(cam,{}).get('success',0),
                       failed=expected[cam]-camera_stats.get(cam,{}).get('success',0),
                       **{f'class_{k}':camera_stats.get(cam,{}).get(f'class_{k}',0) for k in PALETTE}) for cam in sorted(expected)]
    write_table(output/'summary.txt', list(summaries[0]), summaries)
    previews(root, output, rows)
    report = dict(status='pass' if len(catalog)==len(rows) and not errors else 'completed_with_failures',
                  expected=len(rows), generated=len(catalog), failed=len(errors), streams=len(expected),
                  profile_sha256=profile_sha, original_mask_exact_reproduction=True,
                  source_hash_verification='all generated/reused frames', native_size_uint8_mask_roundtrip='all generated frames',
                  artifact_hash_verification='all successful masks/colors/overlays',
                  runtime_seconds=round(time.monotonic()-started,1), errors='errors.txt',
                  review_status='unreviewed', root_dataset_annotations='unchanged')
    write_text(output/'validation.json', json.dumps(report, indent=2))
    write_text(output/'progress.json', json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)
    if errors:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
