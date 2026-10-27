"""Absent-class handling must preserve geometry, provenance and old profiles."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from north16.annotations.profiles import DEFAULT_PROFILE, validate_profile, profile_hash, load_profile


@unittest.skipUnless(importlib.util.find_spec('cv2'), 'OpenCV extra required')
class SeaModeTests(unittest.TestCase):
    def example(self, p):
        a=np.full((144,256,3),185,np.uint8)
        a[:65]=[125,150,170]
        a[110:,:25]=35;a[110:,-25:]=35
        Image.fromarray(a).save(p)

    def test_single_class_skips_grabcut_and_preserves_native_band(self):
        from north16.annotations.workspace import preview
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/'vignetted_ice.png';self.example(p)
            for mode,expected,absent in [('ice_only',2,1),('water_only',1,2)]:
                profile=deepcopy(DEFAULT_PROFILE);profile['sea_mode']=mode
                profile['horizon_normalized_xy']=[[0,.4],[1,.5]]
                with patch('north16.annotations.grabcut.cv2.grabCut',side_effect=AssertionError('single-class mode must bypass GrabCut')):
                    mask=preview(p,profile)
                self.assertEqual(mask.shape,(144,256));self.assertEqual(mask.dtype,np.uint8)
                self.assertNotIn(absent,np.unique(mask))
                self.assertTrue(np.all(mask[-1]==expected))
                horizon=np.interp(np.arange(256)/255,[0,1],[.4,.5])*144
                yy=np.arange(144)[:,None]
                self.assertTrue(np.all(mask[yy>horizon[None,:]+.02*144]==expected))
                self.assertTrue(np.all(mask[yy<horizon[None,:]-.02*144]==0))
                self.assertTrue(np.any(mask==255))

    def test_mode_survives_estimation_save_batch_and_editor_roundtrip(self):
        from north16.annotations.estimation import estimate_parameters
        from north16.annotations.workspace import run_job,export_editor
        from north16.annotations.xanylabeling import render
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);images=root/'images';images.mkdir();p=images/'ice.png';self.example(p)
            before=p.read_bytes();profile=deepcopy(DEFAULT_PROFILE);profile['sea_mode']='ice_only'
            profile,report=estimate_parameters(p,profile,keep_horizon=True)
            self.assertEqual(report['brightness']['status'],'skipped')
            self.assertEqual(profile['sea_mode'],'ice_only')
            out=root/'draft';result=run_job([p],profile,out,estimation=report)
            self.assertEqual(result['succeeded'],1)
            self.assertEqual(load_profile(out/'parameters.json')['sea_mode'],'ice_only')
            receipt=json.loads((out/'run.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt['method'],'user_assigned_ice_only')
            project=root/'editor';export_editor(out,project)
            data=json.loads(next((project/'images').glob('*.json')).read_text(encoding='utf-8'))
            self.assertNotIn(1,np.unique(render(data)))
            self.assertEqual(before,p.read_bytes())

    def test_old_profiles_keep_mixed_hash_and_segmentation(self):
        import hashlib
        from north16.annotations.grabcut import segment
        old=deepcopy(DEFAULT_PROFILE);old.pop('sea_mode')
        expected=hashlib.sha256(json.dumps(old,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(profile_hash(old),expected)
        self.assertEqual(profile_hash(DEFAULT_PROFILE),expected)
        self.assertEqual(validate_profile(old)['sea_mode'],'mixed')
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/'mixed.png';self.example(p);image=Image.open(p).convert('RGB')
            self.assertTrue(np.array_equal(segment(image,old),segment(image,DEFAULT_PROFILE)))
        wrong=dict(DEFAULT_PROFILE,sea_mode='auto_guess')
        with self.assertRaises(ValueError):validate_profile(wrong)

    @unittest.skipUnless(importlib.util.find_spec('PySide6'),'GUI extra required')
    def test_gui_mode_disables_thresholds_and_previews_without_water(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from PySide6.QtTest import QTest
        from north16.gui.window import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);self.example(root/'ice.png');window=Window(root)
            window.parameters.sea_mode.setCurrentIndex(window.parameters.sea_mode.findData('ice_only'))
            self.assertFalse(window.parameters.inputs['water_probable_brightness_max'].isEnabled())
            window.run_estimation();deadline=time.monotonic()+30
            while window.active_worker and time.monotonic()<deadline:app.processEvents();QTest.qWait(10)
            self.assertIsNone(window.active_worker)
            self.assertIsNotNone(window.mask)
            self.assertNotIn(1,np.unique(window.mask))
            self.assertEqual(window.current_profile()['sea_mode'],'ice_only')
            window.parameters.sea_mode.setCurrentIndex(0)
            self.assertTrue(window.parameters.inputs['water_probable_brightness_max'].isEnabled())
            window.close()
