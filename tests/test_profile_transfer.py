"""Reuse parameters across cameras without reusing source evidence or labels."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from north16.annotations.profiles import DEFAULT_PROFILE, profile_hash
from north16.common.files import sha256
from north16.gui.window import Window
from test_dataset_workspace import fixture, add_infrared


class ProfileTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        cls.app=QApplication.instance() or QApplication([])

    def test_snapshot_paste_independence_and_persistent_json_without_source_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/'data';fixture(data)
            w=Window(data);self.addCleanup(w.close)
            root=str(w.dataset_workspace.root);source_key=w.stream_key
            self.assertEqual(w.horizon_mode.currentData(),'line')
            self.assertEqual(len(w.current_profile()['horizon_normalized_xy']),2)
            p=deepcopy(DEFAULT_PROFILE)
            p.update(working_wh=[256,144],horizon_normalized_xy=[[0,.35],[1,.4]],
                     water_definite_brightness_max=60,water_probable_brightness_max=110,
                     ice_definite_brightness_min=180,grabcut_iterations=7)
            w.apply_profile(p)
            w.camera_estimations[(root,source_key)]=dict(profile_sha256=profile_hash(p),source_image=str(w.current_path))
            w.camera_validations[(root,source_key,profile_hash(p))]=[dict(image=str(w.current_path))]
            w.copy_profile_button.click()
            w.parameters.inputs['water_probable_brightness_max'].setValue(115)
            w.camera_combo.setCurrentText('back_04')
            self.assertNotEqual(w.current_profile(),p)
            w.parallel_estimate.setChecked(True)
            w.paste_profile_button.click()
            self.assertEqual(w.current_profile(),p)
            self.assertEqual(w.stream_profiles[(root,w.stream_key)],p)
            self.assertIsNone(w.last_estimation)
            self.assertIsNone(w.estimation_for_profile(p))
            self.assertEqual(w.validations_for_profile(p),[])
            self.assertFalse(w.parallel_estimate.isChecked())
            self.assertIsNone(w.mask)
            w.save_parameters()
            saved=Path(w.output_field.text())/'parameters'/Path(*w.stream_key)/(profile_hash(p)+'.json')
            self.assertEqual(json.loads(saved.read_text(encoding='utf-8')),p)
            receipt=json.loads(saved.with_suffix('.validation.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt['sampled_images'],[])
            self.assertIsNone(receipt['automatic_estimation'])
            w.parameters.inputs['water_probable_brightness_max'].setValue(120)
            self.assertEqual(w.copied_profile,p)
            w.camera_combo.setCurrentText(source_key[2])
            self.assertEqual(w.current_profile()['water_probable_brightness_max'],115)
            w.paste_parameters()
            self.assertEqual(w.current_profile(),p)
            # Saving a profile keeps it loadable independently of the session buffer.
            w2=Window(data);self.addCleanup(w2.close)
            self.assertIsNone(w2.copied_profile)
            with patch('north16.gui.window.QFileDialog.getOpenFileName',return_value=(str(saved),'JSON')):
                w2.load_parameters()
            self.assertEqual(w2.current_profile(),p)
            w2.parameters.inputs['water_probable_brightness_max'].setValue(113)
            saved_profile=w2.current_profile()
            w2.save_parameters()
            self.assertEqual(w2.copied_profile,saved_profile)
            w2.camera_combo.setCurrentText('back_04')
            w2.paste_profile_button.click()
            self.assertEqual(w2.current_profile(),saved_profile)

    def test_apply_all_includes_unchecked_only_current_visible_sequence_and_stales_previews(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/'data';fixture(data);add_infrared(data)
            w=Window(data);self.addCleanup(w.close)
            root=str(w.dataset_workspace.root);sequence=w.stream_key[0]
            p=deepcopy(DEFAULT_PROFILE);p['working_wh']=[256,144]
            w.apply_profile(p)
            for key in w.dataset_workspace.keys(None):
                w.stream_profiles[(root,key)]=deepcopy(p)
            jobs=[];w.start=lambda fn,cb,label:jobs.append((fn,cb))
            w.run_camera_previews()
            jobs[-1][1](jobs[-1][0](threading.Event(),lambda *_:None))
            w.overview.set_selection({'back_03'})
            before={key:deepcopy(value) for key,value in w.stream_profiles.items()}
            files={p:sha256(p) for p in data.rglob('*') if p.is_file()}
            w.parameters.inputs['water_probable_brightness_max'].setValue(112)
            desired=w.current_profile()
            w.parallel_estimate.setChecked(True)
            w.apply_all_profiles_button.click()
            self.assertFalse(w.parallel_estimate.isChecked())
            self.assertEqual(w.overview.selected_cameras(),['back_03'])
            for key in w.dataset_workspace.keys(None):
                expected=desired if key[0]==sequence and key[1]=='visible' else before[(root,key)]
                self.assertEqual(w.stream_profiles[(root,key)],expected)
            self.assertTrue(all(card.stale for card in w.overview.cards.values()))
            self.assertIsNone(w.mask)
            self.assertEqual(files,{p:sha256(p) for p in data.rglob('*') if p.is_file()})
            w.camera_combo.setCurrentText('back_04')
            self.assertEqual(w.current_profile(),desired)
            w.parameters.inputs['water_probable_brightness_max'].setValue(114)
            w.camera_combo.setCurrentText('back_03')
            self.assertEqual(w.current_profile(),desired)
            self.assertIn('全部',w.apply_all_profiles_button.text())

    def test_invalid_copy_keeps_previous_snapshot_and_controls_follow_busy_sensor_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/'data';fixture(data);add_infrared(data)
            w=Window(data);self.addCleanup(w.close)
            self.assertFalse(w.paste_profile_button.isEnabled())
            w.copy_parameters();snapshot=deepcopy(w.copied_profile)
            self.assertTrue(w.paste_profile_button.isEnabled())
            w.parameters.inputs['water_probable_brightness_max'].setValue(200)
            errors=[];w.error=errors.append
            w.copy_parameters()
            self.assertTrue(errors)
            self.assertEqual(w.copied_profile,snapshot)
            w.paste_parameters()
            self.assertEqual(w.current_profile(),snapshot)
            w.busy(True)
            self.assertFalse(w.copy_profile_button.isEnabled())
            self.assertFalse(w.paste_profile_button.isEnabled())
            self.assertFalse(w.apply_all_profiles_button.isEnabled())
            w.busy(False)
            w.sensor_combo.setCurrentIndex(w.sensor_combo.findData('infrared'))
            self.assertFalse(w.copy_profile_button.isEnabled())
            self.assertFalse(w.paste_profile_button.isEnabled())
            self.assertFalse(w.apply_all_profiles_button.isEnabled())
            self.assertEqual(w.copied_profile,snapshot)
            w.sensor_combo.setCurrentIndex(w.sensor_combo.findData('visible'))
            self.assertTrue(w.paste_profile_button.isEnabled())
            self.assertTrue(w.apply_all_profiles_button.isEnabled())
            empty=Window();self.addCleanup(empty.close)
            self.assertFalse(empty.apply_all_profiles_button.isEnabled())
