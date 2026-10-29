"""Raw -> empty layout -> camera package -> JSON labels -> direct Dataset."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np

from north16.layout import DatasetInitializer
from north16.camera import CameraBuilder
from north16.common.files import read_info,sha256
from north16.packages import import_package
from north16.segmentation import SegmentationBuilder
from north16.segmentation.labels import validate_label,render
from north16.annotations.profiles import DEFAULT_PROFILE
from north16.datasets import CameraDataset,SegmentationDataset
from test_build import FFMPEG,FFPROBE


def raw_fixture(root):
    raw=root/'raw'
    segment=raw/'2026_09_02_04_42_32_data'
    for sensor in ('visible','infrared'):
        folder=segment/'camera'/('front_'+sensor);folder.mkdir(parents=True)
        subprocess.run([FFMPEG,'-v','error','-f','lavfi','-i','testsrc2=size=64x48:rate=2',
                        '-frames:v','3','-c:v','mpeg4',str(folder/'lens_01.mp4')],check=True)
    return raw


class ModuleTests(unittest.TestCase):
    def test_initialization_extraction_package_copy_json_reader_and_conflicts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);raw=raw_fixture(root)
            initializer=DatasetInitializer()
            with patch('subprocess.run',side_effect=AssertionError('No media process during initialize')),patch('subprocess.check_output',side_effect=AssertionError('No probing')):
                result=initializer.initialize(raw,root/'source')
                initializer.initialize(raw,root/'target')
            self.assertEqual(result['images'],0)
            self.assertEqual(len(list((root/'source').glob('sequences/*/*/*/images'))),2)
            self.assertFalse(list((root/'source').rglob('masks')))
            self.assertFalse(list((root/'source').rglob('*.png')))
            with self.assertRaises(FileExistsError):initializer.initialize(raw,root/'source')
            builder=CameraBuilder(root/'source')
            report=builder.extract(ffmpeg=FFMPEG,ffprobe=FFPROBE)
            self.assertEqual(report['images'],6)
            self.assertFalse(list((root/'source').rglob('masks')))
            self.assertEqual(builder.extract(ffmpeg=FFMPEG,ffprobe=FFPROBE)['reused_streams'],2)
            builder.export(root/'camera_package')
            # Target remains initialized (its empty samples snapshot is untouched).
            original_snapshot=sha256(root/'target/samples.txt')
            import_package(root/'target',root/'camera_package')
            self.assertEqual(sha256(root/'target/samples.txt'),original_snapshot)
            ds=SegmentationDataset(root/'target',split=None,sequences='20260902_044232',require_mask=False,sensor=['visible','infrared'])
            self.assertEqual(len(ds),6)
            self.assertEqual(tuple(ds[0]['image'].shape),(3,48,64))
            camera_data=CameraDataset(root/'target')
            self.assertEqual(len(camera_data),6)
            self.assertNotIn('mask',camera_data[0])
            segmenter=SegmentationBuilder(root/'target');key=segmenter.workspace.keys()[0]
            profile=deepcopy(DEFAULT_PROFILE);profile['sea_mode']='ice_only';profile['working_wh']=[256,192]
            images=segmenter.workspace.images(key)
            report=segmenter.generate(key,images,profile,root/'labels')
            self.assertEqual((report['format'],report['succeeded']),('json',3))
            payload=root/'labels/dataset'
            self.assertTrue(all(p.suffix=='.json' and p.parent.name=='masks' for p in payload.rglob('*') if p.is_file()))
            # User can merge-copy whole dataset tree without running an indexer.
            shutil.copytree(payload,root/'target',dirs_exist_ok=True)
            self.assertEqual(sha256(root/'target/samples.txt'),original_snapshot)
            with self.assertRaisesRegex(ValueError,'label status'):
                SegmentationDataset(root/'target',split=None,sequences=key[0])
            ds=SegmentationDataset(root/'target',split=None,sequences=key[0],allowed_label_statuses=['draft'])
            self.assertEqual(len(ds),3)
            self.assertEqual(tuple(ds[0]['mask'].shape),(48,64))
            self.assertTrue(set(np.unique(ds[0]['mask'].numpy())).issubset({0,2,255}))
            with self.assertRaises(FileExistsError):segmenter.generate(key,images,profile,root/'labels')
            # A new reference dataset can consume camera and segmentation packages.
            initializer.initialize(raw,root/'third')
            import_package(root/'third',root/'camera_package');import_package(root/'third',root/'labels')
            self.assertEqual(import_package(root/'third',root/'labels')['copied'],0)
            label=next((root/'third').glob('sequences/*/visible/*/masks/*.json'))
            edited=json.loads(label.read_text(encoding='utf-8'));edited['shapes'].append(dict(label='other',shape_type='rectangle',points=[[1,1],[5,5]]))
            label.write_text(json.dumps(edited),encoding='utf-8')
            with self.assertRaises(FileExistsError):import_package(root/'third',root/'labels')
            ds=SegmentationDataset(root/'third',split=None,sequences=key[0],allowed_label_statuses=['draft'])
            self.assertEqual(int(ds[0]['mask'][2,2]),3)
            edited['north16']['image_sha256']='bad';label.write_text(json.dumps(edited),encoding='utf-8')
            # Historical SHA declarations are ignored; byte count is still checked.
            SegmentationDataset(root/'third',split=None,sequences=key[0],allowed_label_statuses=['draft'])
            edited['north16']['image_bytes']=0;label.write_text(json.dumps(edited),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'校验'):
                SegmentationDataset(root/'third',split=None,sequences=key[0],allowed_label_statuses=['draft'])

    def test_cancel_partial_labels_and_labeled_only_are_explicit(self):
        from test_dataset_workspace import fixture
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);fixture(root/'data')
            builder=SegmentationBuilder(root/'data');key=builder.workspace.keys()[0]
            profile=deepcopy(DEFAULT_PROFILE);profile['sea_mode']='ice_only';profile['working_wh']=[256,144]
            cancel=threading.Event()
            report=builder.generate(key,builder.workspace.images(key),profile,root/'labels',cancel=cancel,progress=lambda *_:cancel.set())
            self.assertEqual((report['status'],report['succeeded']),('cancelled',1))
            import_package(root/'data',root/'labels')
            ds=SegmentationDataset(root/'data',split=None,sequences=key[0],allowed_label_statuses=['draft'],labeled_only=True)
            self.assertEqual(len(ds),1)
            with self.assertRaises(ValueError):SegmentationDataset(root/'data',split=None,sequences=key[0],allowed_label_statuses=['draft'])
            # Export installed JSON files without invoking the segmentation algorithm.
            with patch('north16.annotations.workspace.preview',side_effect=AssertionError('No segmentation during export')):
                builder.export(root/'reexport')
            self.assertEqual(len(list((root/'reexport/dataset').rglob('*.json'))),1)

    def test_annotation_geometry_and_review_records(self):
        with self.assertRaises(ValueError):render(dict(imageWidth=10,imageHeight=10,shapes=[dict(label='ice',points=[[0,0],[20,0],[1,1]])]))
        self.assertTrue((render(dict(imageWidth=10,imageHeight=10,shapes=[]))==255).all())

    def test_plain_folder_defaults_to_json_and_protects_originals(self):
        from north16.segmentation.builder import generate_folder
        from PIL import Image
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);images=root/'input';images.mkdir()
            Image.new('RGB',(256,144),(190,190,190)).save(images/'a.png')
            original=sha256(images/'a.png')
            profile=deepcopy(DEFAULT_PROFILE);profile['sea_mode']='ice_only'
            report=generate_folder([images/'a.png'],profile,root/'output')
            self.assertEqual(report['format'],'json')
            self.assertTrue((root/'output/masks/000000_a.json').is_file())
            self.assertFalse(list((root/'output/masks').glob('*.png')))
            self.assertEqual(sha256(images/'a.png'),original)
