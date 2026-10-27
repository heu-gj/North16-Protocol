"""Heuristic behavior, conservative fallback, GUI application and provenance."""
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

from north16.annotations.profiles import DEFAULT_PROFILE, profile_hash, validate_profile

if importlib.util.find_spec("cv2"):
    from north16.annotations.estimation import estimate_parameters


def example(path):
    rng = np.random.default_rng(6)
    a = np.empty((200, 320, 3), np.uint8)
    a[:] = [145, 165, 195]
    a[85:] = 205
    a[85:, 20:110] = [30, 45, 60]
    noise = rng.integers(-5, 6, a.shape)
    Image.fromarray(np.clip(a.astype(int)+noise, 0, 255).astype(np.uint8)).save(path)


@unittest.skipUnless(importlib.util.find_spec("cv2"), "OpenCV optional extra required")
class EstimationTests(unittest.TestCase):
    def test_mixed_sea_suggests_ordered_seeds_and_horizon(self):
        with tempfile.TemporaryDirectory() as name:
            p = Path(name)/"混合海面.png";example(p)
            before = p.read_bytes()
            profile, report = estimate_parameters(p)
            validate_profile(profile)
            self.assertEqual(report["horizon"]["status"], "suggested")
            self.assertAlmostEqual(profile["horizon_normalized_xy"][2][1], .425, delta=.09)
            self.assertEqual(report["brightness"]["status"], "suggested")
            self.assertLess(profile["water_definite_brightness_max"], profile["ice_definite_brightness_min"])
            self.assertEqual(p.read_bytes(), before)
            self.assertEqual(report["review_status"], "unreviewed")
            self.assertEqual(report["profile_sha256"], profile_hash(profile))
            second, evidence = estimate_parameters(p)
            self.assertEqual(profile, second)
            self.assertEqual(report, evidence)

    def test_flat_image_keeps_prior_instead_of_inventing_seeds(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/"flat.png";Image.new("RGB",(300,200),(120,120,120)).save(p)
            profile,report=estimate_parameters(p)
            self.assertEqual(profile,validate_profile(DEFAULT_PROFILE))
            self.assertEqual(report["horizon"]["status"],"retained")
            self.assertEqual(report["brightness"]["status"],"retained")
            self.assertEqual(len(report["warnings"]),3)

    def test_manual_horizon_and_other_user_parameters_are_preserved(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/"image.png";example(p)
            base=deepcopy(DEFAULT_PROFILE)
            base["working_wh"]=[640,360]
            base["grabcut_iterations"]=3
            base["boundary_ignore_kernel"]=[5,5]
            base["horizon_normalized_xy"]=[[0,.42],[1,.42]]
            profile,report=estimate_parameters(p,base,keep_horizon=True)
            for key in ["working_wh","grabcut_iterations","boundary_ignore_kernel","horizon_normalized_xy"]:
                self.assertEqual(profile[key],base[key])
            self.assertEqual(report["horizon"]["status"],"preserved")
            self.assertEqual(report["brightness"]["status"],"suggested")

    @unittest.skipUnless(importlib.util.find_spec("PySide6"), "GUI optional extra required")
    def test_gui_estimates_previews_and_saves_traceable_profile(self):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        from north16.gui.window import Window
        app=QApplication.instance() or QApplication([])
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);images=root/"images";images.mkdir();example(images/"first.png")
            window=Window(images);window.show();app.processEvents()
            self.assertTrue(window.keep_horizon.isChecked())
            points = [[0,.42],[1,.42]]
            profile = window.current_profile()
            profile['horizon_normalized_xy'] = points
            window.apply_profile(profile)
            window.parameters.inputs["working_width"].setValue(256)
            QTest.mouseClick(window.estimate_button,Qt.MouseButton.LeftButton)
            deadline=time.monotonic()+30
            while window.active_worker and time.monotonic()<deadline:
                app.processEvents();QTest.qWait(10)
            self.assertIsNone(window.active_worker)
            self.assertIsNotNone(window.mask)
            self.assertEqual(window.last_estimation["horizon"]["status"],"preserved")
            self.assertEqual(window.current_profile()['horizon_normalized_xy'],points)
            self.assertEqual(window.result_key[1],profile_hash(window.current_profile()))
            config=root/"profile.json"
            with patch("north16.gui.window.QFileDialog.getSaveFileName",return_value=(str(config),"JSON")):
                window.save_parameters()
            receipt=json.loads(config.with_name("profile.validation.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["automatic_estimation"]["source_image"],str((images/"first.png").resolve()))
            self.assertEqual(receipt["automatic_estimation"]["profile_sha256"],receipt["profile_sha256"])
            self.assertEqual(receipt["review_status"],"unreviewed")
            window.close()

    def test_job_saves_evidence_and_rejects_mismatched_profile_before_writing(self):
        from north16.annotations.workspace import run_job
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            images = root / "images"; images.mkdir()
            p = images / "frame.png"; example(p)
            profile, evidence = estimate_parameters(p)
            output = root / "draft"
            result = run_job([p], profile, output, estimation=evidence)
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(json.loads((output / "estimation.json").read_text(encoding="utf-8")), evidence)
            invalid = dict(evidence, profile_sha256="mismatched")
            rejected = root / "rejected"
            with self.assertRaises(ValueError):
                run_job([p], profile, rejected, estimation=invalid)
            self.assertFalse(rejected.exists())

    def test_competing_horizon_and_ice_edge_do_not_replace_current_line(self):
        with tempfile.TemporaryDirectory() as name:
            p = Path(name)/'competing.png'
            image = np.full((240, 400, 3), 180, np.uint8)
            image[96:156] = 40
            Image.fromarray(image).save(p)
            profile, report = estimate_parameters(p)
            self.assertEqual(report['horizon']['status'],'retained')
            self.assertEqual(profile['horizon_normalized_xy'],DEFAULT_PROFILE['horizon_normalized_xy'])
            self.assertTrue(report['warnings'])


if __name__=="__main__":unittest.main()
