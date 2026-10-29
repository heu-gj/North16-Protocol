"""No file SHA in the modular workflow; legacy data and edit protection survive."""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from north16.annotation import AnnotationWorkspace, AnnotationBuilder
from north16.annotations.estimation import estimate_parameters
from north16.annotations.profiles import DEFAULT_PROFILE
from north16.common.files import read_info, read_table, sha256, write_info, write_table
from north16.datasets import SegmentationDataset
from north16.gui.overview_jobs import preview_cameras
from north16.layout import DatasetInitializer
from north16.packages import import_package
from test_build import FFMPEG, FFPROBE
from test_modules import raw_fixture


def forbid_file_sha():
    stack=ExitStack()
    for target in ('north16.common.files.sha256','north16.adapters.capture.sha256',
                   'north16.preprocess.camera.sha256','north16.annotations.grabcut.digest',
                   'north16.annotations.xanylabeling.sha'):
        stack.enter_context(patch(target,side_effect=AssertionError('File SHA must not run: '+target)))
    return stack


class FileCheckTests(unittest.TestCase):
    def test_full_workflow_estimation_previews_and_reader_without_file_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=raw_fixture(root)
            with forbid_file_sha():
                DatasetInitializer().initialize(raw,root/'final')
                self.assertTrue(all(r['sha256']=='disabled' for r in read_table(root/'final/sources.txt')))
                AnnotationWorkspace.initialize(root/'work',dataset=root/'final')
                workspace=AnnotationWorkspace(root/'work')
                workspace.extract(interval=1,dry_run=True,ffmpeg=FFMPEG,ffprobe=FFPROBE)
                workspace.extract(interval=1,ffmpeg=FFMPEG,ffprobe=FFPROBE)
                builder=AnnotationBuilder(root/'work');key=builder.workspace.keys()[0]
                profile=deepcopy(DEFAULT_PROFILE);profile['sea_mode']='ice_only'
                preview=preview_cameras(builder,key[0],profiles={key[2]:profile},workers=1)
                self.assertEqual(preview['succeeded'],1)
                self.assertIn('source_image_state',preview['cameras'][0])
                report=builder.generate(key,builder.workspace.images(key),profile,root/'work')
                self.assertEqual(report['failed'],0)
                image=root/'estimate.png';Image.new('RGB',(256,144),(190,190,190)).save(image)
                _,evidence=estimate_parameters(image,profile,keep_horizon=True)
                self.assertIn('source_image_state',evidence)
                workspace.export(root/'delivery')
                rows=read_table(root/'delivery/files.txt')
                self.assertEqual(set(rows[0]),{'path','size_bytes'})
                import_package(root/'final',root/'delivery')
                self.assertEqual(import_package(root/'final',root/'delivery')['copied'],0)
                data=SegmentationDataset(root/'final',split=None,sequences=key[0],allowed_label_statuses=['draft'])
                self.assertEqual(len(data),2)
                self.assertEqual(tuple(data[0]['mask'].shape),(48,64))

    def test_old_sha_sources_receipts_labels_and_manifest_are_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=raw_fixture(root)
            DatasetInitializer().initialize(raw,root/'final')
            # Model a v0.13 registry and stream placeholders (no raw byte count in info).
            rows=read_table(root/'final/sources.txt')
            for row in rows:
                row['sha256']=sha256(Path(row['source_absolute_path']));row.pop('modified_ns')
                info_path=root/'final'/f"sequences/{row['sequence']}/{row['sensor']}/{row['camera']}/info.txt"
                info=read_info(info_path);info['source_sha256']=row['sha256'];info.pop('source_bytes')
                write_info(info_path,info)
            write_table(root/'final/sources.txt',rows[0].keys(),rows)
            with forbid_file_sha():
                AnnotationWorkspace.initialize(root/'work',dataset=root/'final')
                workspace=AnnotationWorkspace(root/'work')
                workspace.extract(interval=1,ffmpeg=FFMPEG,ffprobe=FFPROBE)
            # Leave intentionally obsolete SHA declarations to prove they are not checked.
            for receipt in (root/'work').glob('sequences/*/*/*/frames.txt'):
                frames=read_table(receipt)
                for frame in frames:frame['image_sha256']='historical-sha-not-checked'
                write_table(receipt,frames[0].keys(),frames)
            builder=AnnotationBuilder(root/'work');key=builder.workspace.keys()[0]
            profile=deepcopy(DEFAULT_PROFILE);profile['sea_mode']='ice_only'
            with forbid_file_sha():
                builder.generate(key,builder.workspace.images(key),profile,root/'work')
                for label in (root/'work').glob('sequences/*/*/*/masks/*.json'):
                    data=json.loads(label.read_text(encoding='utf-8'))
                    data['north16'].pop('image_bytes');data['north16']['image_sha256']='historical-sha'
                    label.write_text(json.dumps(data),encoding='utf-8')
                workspace.export(root/'delivery')
            manifest=read_table(root/'delivery/files.txt')
            write_table(root/'delivery/files.txt',('path','sha256'),[dict(path=r['path'],sha256='historical-sha') for r in manifest])
            with forbid_file_sha():
                import_package(root/'final',root/'delivery')
                data=SegmentationDataset(root/'final',split=None,sequences=key[0],allowed_label_statuses=['draft'])
                self.assertEqual(len(data),2)

    def test_resume_v013_key_and_same_size_label_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=raw_fixture(root)
            AnnotationWorkspace.initialize(root/'work',raw=raw)
            workspace=AnnotationWorkspace(root/'work')
            workspace.extract(interval=1,ffmpeg=FFMPEG,ffprobe=FFPROBE)
            run=read_info(root/'work/info.txt')['latest_camera_run']
            conversion=read_info(root/'work'/run/'conversion.txt')
            # Build the actual historical key, whose JSON value types were native.
            settings=dict(version='0.13.0',ffmpeg=conversion['ffmpeg'],pixel_format='rgb24',
                          filter=conversion['filter'],fps_mode='passthrough',compression_level=3,
                          frame_selection='minimum_pts_interval',interval_seconds=1.0,copyts=True)
            old_key=hashlib.sha256(json.dumps(settings,sort_keys=True).encode()).hexdigest()
            for info_path in (root/'work').glob('sequences/*/*/*/info.txt'):
                info=read_info(info_path);info['extraction_key']=old_key;write_info(info_path,info)
            with forbid_file_sha():
                self.assertEqual(workspace.extract(interval=1,ffmpeg=FFMPEG,ffprobe=FFPROBE)['reused_streams'],2)
                with self.assertRaises(ValueError):workspace.extract(interval=2,ffmpeg=FFMPEG,ffprobe=FFPROBE)
                builder=AnnotationBuilder(root/'work');key=builder.workspace.keys()[0]
                profile=deepcopy(DEFAULT_PROFILE);profile['sea_mode']='ice_only'
                builder.generate(key,builder.workspace.images(key),profile,root/'work')
                workspace.export(root/'delivery')
                DatasetInitializer().initialize(raw,root/'final')
                import_package(root/'final',root/'delivery')
                label=next((root/'final').rglob('masks/*.json'))
                original=label.read_bytes();edited=original.replace(b'"checked":false',b'"checked":true ',1)
                self.assertNotEqual(original,edited);self.assertEqual(len(original),len(edited))
                label.write_bytes(edited)
                with self.assertRaises(FileExistsError):import_package(root/'final',root/'delivery')
                self.assertEqual(label.read_bytes(),edited)


if __name__=='__main__':unittest.main()
