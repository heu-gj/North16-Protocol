"""Two-point edits must survive camera changes and reach exported labels."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication

from north16.annotations.profiles import DEFAULT_PROFILE, profile_hash
from north16.annotations.workspace import preview
from north16.annotations.xanylabeling import render
from north16.gui.window import Window
from north16.segmentation import SegmentationBuilder
from test_dataset_workspace import fixture, add_infrared
from test_estimation import example


class HorizonModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        cls.app = QApplication.instance() or QApplication([])

    def test_edit_camera_roundtrip_and_export_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'data'
            fixture(root)
            add_infrared(root)
            w = Window(root)
            self.addCleanup(w.close)
            w.show(); self.app.processEvents()
            self.assertEqual(w.horizon_mode.currentData(), 'line')
            self.assertEqual(len(w.original_view.handles), 2)
            # Explicitly loaded legacy polylines remain supported.
            legacy=deepcopy(DEFAULT_PROFILE)
            legacy['horizon_normalized_xy']=[[0,.475],[.25,.472],[.5,.472],[.75,.465],[1,.455]]
            w.apply_profile(legacy)
            self.assertEqual(w.horizon_mode.currentData(), 'polyline')
            old = deepcopy(w.original_view.points)
            w.horizon_mode.setCurrentIndex(w.horizon_mode.findData('line'))
            self.assertEqual(w.original_view.points, [old[0], old[-1]])
            self.assertEqual(len(w.original_view.handles), 2)
            for handle, y in zip(w.original_view.handles, [.35, .55]):
                handle.setPos(handle.pos().x(), y*(w.original_view.height_px-1))
            w.parameters.inputs['working_width'].setValue(256)
            p = w.current_profile()
            self.assertAlmostEqual(p['horizon_normalized_xy'][0][1], .35)
            self.assertAlmostEqual(p['horizon_normalized_xy'][1][1], .55)
            expected = preview(w.current_path, p)
            key = w.stream_key
            result = SegmentationBuilder(root).generate_cameras(
                key[0], Path(tmp)/'labels', cameras=[key[2]],
                profiles={key[2]: p}, estimate=False, limit=1, workers=1)
            self.assertEqual((result['succeeded'], result['failed']), (1, 0))
            label = next((Path(tmp)/'labels/dataset').rglob('*.json'))
            data = json.loads(label.read_text(encoding='utf-8'))
            self.assertEqual(data['north16']['parameters']['horizon_normalized_xy'], p['horizon_normalized_xy'])
            np.testing.assert_array_equal(render(data), expected)
            w.camera_combo.setCurrentText('back_04')
            self.assertEqual(w.horizon_mode.currentData(), 'line')
            self.assertEqual(w.original_view.points, DEFAULT_PROFILE['horizon_normalized_xy'])
            w.camera_combo.setCurrentText(key[2])
            self.assertEqual(w.horizon_mode.currentData(), 'line')
            self.assertEqual(w.current_profile(), p)
            w.horizon_mode.setCurrentIndex(w.horizon_mode.findData('polyline'))
            self.assertEqual(len(w.original_view.handles), 5)
            for x, y in w.original_view.points:
                self.assertAlmostEqual(y, .35+.2*x)
            w.apply_profile(p)
            self.assertEqual(w.horizon_mode.currentData(), 'line')
            w.busy(True)
            self.assertFalse(w.horizon_mode.isEnabled())
            w.busy(False)
            self.assertTrue(w.horizon_mode.isEnabled())
            w.sensor_combo.setCurrentIndex(w.sensor_combo.findData('infrared'))
            self.assertFalse(w.horizon_mode.isEnabled())
            self.assertEqual(w.original_view.handles, [])
            w.sensor_combo.setCurrentIndex(w.sensor_combo.findData('visible'))
            w.camera_combo.setCurrentText(key[2])
            self.assertEqual(w.horizon_mode.currentData(), 'line')
            self.assertEqual(w.current_profile(), p)

    def test_automatic_horizon_candidate_keeps_two_point_mode(self):
        from north16.annotations.estimation import estimate_parameters
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp)/'frame.png'; example(image)
            base = deepcopy(DEFAULT_PROFILE)
            base['horizon_normalized_xy'] = [[0., .47], [1., .45]]
            p, report = estimate_parameters(image, base, keep_horizon=False)
            self.assertEqual(report['horizon']['status'], 'suggested')
            self.assertEqual(len(p['horizon_normalized_xy']), 2)
            self.assertEqual(report['profile_sha256'], profile_hash(p))


if __name__ == '__main__':
    unittest.main()
