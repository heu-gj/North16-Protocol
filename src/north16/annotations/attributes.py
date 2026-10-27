"""Apply evidence-backed, stream-scoped attribute decisions to a working dataset.

This applies explicit decisions; it is not an automatic weather classifier.
Writes are reversible through a complete ZIP of pre-edit metadata.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from north16.common.files import local_path, read_info, read_table, sha256, write_info, write_table, write_text
from north16.preprocess.index import build_index


WEATHER = {'clear', 'cloudy_overcast', 'fog_precipitation', 'unknown'}
LIGHT = {'day', 'night', 'unknown'}


def apply(root: Path, plan_path: Path, evidence: Path, run_id: str, protocol_path: Path):
    import yaml
    root = root.resolve(strict=True)
    if read_info(root / 'info.txt')['dataset_status'] != 'working':
        raise ValueError('Only a working dataset may be changed.')
    if not run_id.replace('_', '').isalnum():
        raise ValueError('Unsafe run id.')
    run = root / 'logs' / run_id
    if run.exists():
        raise ValueError('Run exists; overwriting is disabled.')
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    records = json.loads((evidence / 'evidence_images.json').read_text(encoding='utf-8'))
    rows = read_table(root / 'samples.txt')
    streams = {}
    for row in rows:
        streams.setdefault((row['sequence'], row['sensor'], row['camera']), []).append(row)
    decisions = {(r['sequence'], r['sensor'], r['camera']): r for r in plan['streams']}
    if len(decisions) != len(plan['streams']) or set(decisions) != set(streams):
        raise ValueError('Decisions must cover each current stream exactly once.')
    evidence_by_stream = {}
    for record in records:
        key = (record['sequence'], record['sensor'], record['camera'])
        evidence_by_stream.setdefault(key, []).append(record)
        if not local_path(root, record['image']).is_file() or not (evidence / record['sheet']).is_file():
            raise FileNotFoundError(record)
    for key, decision in decisions.items():
        if decision['weather'] not in WEATHER or decision['illumination'] not in LIGHT:
            raise ValueError('Invalid canonical attribute enum.')
        if len(evidence_by_stream.get(key, [])) != 3:
            raise ValueError(f'Three sampled images required: {key}')
        if decision['sensor'] == 'infrared' and plan.get('association_basis') != 'user_confirmed_simultaneous_visible_infrared_recording':
            raise ValueError('Explicit user co-recording evidence required for transferring coarse conditions.')
    now = datetime.now(timezone.utc).isoformat()
    version = plan['attribute_version']
    changes = {}
    evidence_rows = []
    stream_rows = []
    scene_counts = Counter()
    for key, members in sorted(streams.items()):
        seq, sensor, camera = key
        decision = decisions[key]
        evidence_id = f'{run_id}_{seq}_{sensor}_{camera}'
        sampled_images = {r['image'] for r in evidence_by_stream[key]}
        for record in evidence_by_stream[key]:
            evidence_rows.append(dict(evidence_id=evidence_id, image=record['image'],
                                      sha256=sha256(local_path(root, record['image'])),
                                      contact_sheet=f'logs/{run_id}/evidence/{record["sheet"]}'))
        shared = dict(attribute_version=version, attribute_run=f'logs/{run_id}',
                      attribute_actor_id='codex_visual_assessment',
                      attribute_assessed_at_utc=now, attribute_assessment_scope='sampled_stream_inference',
                      attribute_review_status='unreviewed',
                      scene_type=decision['scene_type'], scene_type_candidate='sea_ice_with_leads',
                      scene_source='visible_context_user_confirmed_corecording' if sensor == 'infrared' else 'ai_visual_stream_samples', scene_evidence_id=f'{run_id}_{seq}_visible_context' if sensor == 'infrared' else evidence_id,
                      scene_confidence=decision['scene_confidence'], scene_status='unreviewed',
                      scene_description=decision['scene_description'],
                      scene_id_reason='independent_physical_scene_boundaries_not_verified',
                      candidate_continuity_group='n16_20260902_pilot_continuous_candidate',
                      view_type=decision['view_type'],
                      image_quality_flags=decision['image_quality_flags'],
                      image_quality_scope='stream_candidate_not_per_frame_verified',
                      weather_candidate='cloudy_overcast', illumination_candidate='day',
                      condition_candidate_source='visible_samples_in_same_sequence',
                      condition_candidate_evidence_id=f'{run_id}_{seq}_visible_context',
                      condition_candidate_status='unreviewed',
                      condition_context_note='user_confirmed_corecording_not_clock_calibration',
                      solar_elevation_status='not_computed_time_position_unverified')
        for attr in ['weather', 'illumination']:
            shared.update({attr: decision[attr], f'{attr}_source': decision[f'{attr}_source'],
                           f'{attr}_evidence_id': f'{run_id}_{seq}_visible_context' if sensor == 'infrared' else evidence_id,
                           f'{attr}_confidence': decision[f'{attr}_confidence'],
                           f'{attr}_status': 'unreviewed', f'{attr}_reason': decision[f'{attr}_reason']})
        stream_info_path = Path(members[0]['meta']).parent.parent / 'info.txt'
        original = read_info(local_path(root, stream_info_path.as_posix()))
        if original.get('attribute_version', 'unknown') != 'unknown':
            raise ValueError(f'Existing attributes require an explicit revision plan: {stream_info_path}')
        changes[stream_info_path.as_posix()] = {**original, **shared,
                                               'attribute_sampled_images': ';'.join(sorted(sampled_images)),
                                               'attribute_stream_frames': str(len(members))}
        for member in members:
            original = read_info(local_path(root, member['meta']))
            if original.get('attribute_version', 'unknown') != 'unknown':
                raise ValueError(f'Existing assessment: {member["id"]}')
            if original['id'] != member['id']:
                raise ValueError('Observation identity mismatch.')
            changes[member['meta']] = {**original, **shared,
                                      'attribute_evidence_sample': str(member['image'] in sampled_images).lower(),
                                      'attribute_assignment': 'sampled_stream_inference',
                                      'scene_id': original['scene_id'], 'group': original['group']}
        stream_rows.append(dict(sequence=seq, sensor=sensor, camera=camera, images=len(members),
                                weather=decision['weather'], illumination=decision['illumination'],
                                weather_candidate='cloudy_overcast', illumination_candidate='day',
                                scene_type=decision['scene_type'], view_type=decision['view_type'],
                                image_quality_flags=decision['image_quality_flags'],
                                attribute_status='unreviewed', evidence_id=evidence_id))
        scene_counts[(sensor, decision['scene_type'])] += len(members)
    for seq in sorted({k[0] for k in streams}):
        path = f'sequences/{seq}/info.txt'
        original = read_info(local_path(root, path))
        changes[path] = {**original, 'default_scope': 'none',
                         'weather': 'cloudy_overcast', 'weather_source': 'ai_visual_visible_multiview_samples',
                         'weather_evidence_id': f'{run_id}_{seq}_visible_context', 'weather_confidence': 'medium',
                         'weather_status': 'unreviewed', 'weather_reason': 'overcast_appearance_fog_not_established',
                         'illumination': 'day', 'illumination_source': 'ai_visual_visible_multiview_samples',
                         'illumination_evidence_id': f'{run_id}_{seq}_visible_context',
                         'illumination_confidence': 'medium', 'illumination_status': 'unreviewed',
                         'illumination_reason': 'natural_diffuse_daylight_visual_not_solar_verified',
                         'condition_scope': 'all_camera_streams_user_confirmed_corecording',
                         'infrared_condition_policy': 'use_visible_conditions_user_confirmed_corecording',
                         'attribute_version': version, 'attribute_run': f'logs/{run_id}',
                         'attribute_actor_id': 'codex_visual_assessment', 'attribute_assessed_at_utc': now,
                         'scene_type': 'sea_ice_with_leads', 'scene_status': 'unreviewed',
                         'scene_description': '海冰与冰间水道；部分镜头包含本船甲板和设备。',
                         'scene_id': 'unknown',
                         'scene_id_reason': 'independent_physical_scene_boundaries_not_verified'}
    dataset_info = read_info(root / 'info.txt')
    changes['info.txt'] = {**dataset_info, 'attribute_version': version,
                           'attribute_status': 'ai_assessed_unreviewed',
                           'latest_attribute_run': f'logs/{run_id}',
                           'attribute_registry': f'logs/{run_id}/checksums.txt'}
    run.mkdir(parents=True)
    shutil.copy2(__file__, run / 'attributes.py')
    shutil.copy2(plan_path, run / 'decisions.json')
    shutil.copytree(evidence, run / 'evidence', ignore=shutil.ignore_patterns('*.py', 'decisions.json', '__pycache__'))
    backup_paths = [*changes, 'samples.txt']
    original_hashes = {}
    with zipfile.ZipFile(run / 'before.zip', 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=3) as z:
        for relative in backup_paths:
            data = local_path(root, relative).read_bytes()
            original_hashes[relative] = hashlib.sha256(data).hexdigest()
            z.writestr(relative, data)
    with zipfile.ZipFile(run / 'before.zip') as z:
        if z.testzip() is not None or len(z.namelist()) != len(backup_paths):
            raise ValueError('Backup verification failed before edits.')
    write_table(run / 'before_checksums.txt', ['path', 'sha256'],
                [dict(path=k, sha256=v) for k, v in original_hashes.items()])
    write_info(run / 'info.txt', dict(status='applying', attribute_version=version, started_at_utc=now,
                                     backup='before.zip', source_registry=dataset_info['source_registry'],
                                     assessment='AI contact-sheet visual assessment; independent human review pending'))
    for relative, info in changes.items():
        write_info(local_path(root, relative), info, durable=False)
    protocol = yaml.safe_load(protocol_path.read_text(encoding='utf-8'))
    new_rows = build_index(root, protocol)
    old_by_id = {r['id']: r for r in rows}
    condition_counts = Counter()
    for row in new_rows:
        old = old_by_id[row['id']]
        for key in old:
            if key not in {'weather', 'illumination'} and old[key] != row[key]:
                raise ValueError(f'Unrelated manifest field changed: {row["id"]}/{key}')
        meta = read_info(local_path(root, row['meta']))
        for key in ('weather', 'illumination'):
            if meta[key] != row[key] or meta[f'{key}_status'] != 'unreviewed':
                raise ValueError('Attribute/index status mismatch.')
        condition_counts[(row['sequence'], row['sensor'], row['weather'], row['illumination'])] += 1
    write_table(run / 'evidence_images.txt', ['evidence_id', 'image', 'sha256', 'contact_sheet'], evidence_rows)
    # Coarse conditions use user-confirmed co-recording, never IR brightness.
    write_info(run / 'co_recording_evidence.txt', dict(source='user_instruction', statement=plan['association_statement'], scope='coarse_weather_illumination_scene_context', clock_calibration='unresolved', frame_pairing='not_certified', spatial_registration='not_certified'))
    write_table(run / 'context_evidence.txt', ['evidence_id', 'member_evidence_id'],
                [dict(evidence_id=f'{run_id}_{seq}_visible_context', member_evidence_id=f'{run_id}_{seq}_{sensor}_{camera}')
                 for seq, sensor, camera in sorted(streams) if sensor == 'visible'])
    write_table(run / 'streams.txt', list(stream_rows[0]), stream_rows)
    summary_rows = [dict(sequence=k[0], sensor=k[1], images=n, weather=k[2], illumination=k[3],
                         weather_candidate='cloudy_overcast', illumination_candidate='day',
                         scene_type='sea_ice_with_leads', status='ai_assessed_unreviewed')
                    for k, n in sorted(condition_counts.items())]
    write_table(root / 'attributes_summary.txt', list(summary_rows[0]), summary_rows)
    write_table(run / 'summary.txt', list(summary_rows[0]), summary_rows)
    write_table(run / 'checksums.txt', ['path', 'sha256'],
                [dict(path=p, sha256=sha256(local_path(root, p))) for p in backup_paths])
    result = dict(status='pass', frames=len(new_rows), streams=len(streams), sequences=3,
                  sampled_images=len(evidence_rows), visual_review_scope='288 sampled images on 12 contact sheets, not every frame',
                  modified_metadata_files=len(changes), canonical_counts=summary_rows,
                  scene_type_counts=[dict(sensor=k[0], scene_type=k[1], count=n) for k, n in sorted(scene_counts.items())],
                  pixel_labels='unchanged_unlabeled', capture_times='unchanged_unresolved',
                  scene_ids='unchanged_unknown', split_groups='unchanged_unknown',
                  association_basis=plan['association_basis'], independent_human_review=False, backup='before.zip')
    write_text(run / 'validation.json', json.dumps(result, ensure_ascii=False, indent=2))
    log_info = read_info(run / 'info.txt')
    write_info(run / 'info.txt', {**log_info, 'status': 'succeeded', 'ended_at_utc': datetime.now(timezone.utc).isoformat()})
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    args = parser.parse_args(argv)
    apply(args.root, args.plan, args.evidence, args.run_id, args.protocol)


if __name__ == '__main__':
    main()
