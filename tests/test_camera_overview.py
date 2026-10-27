"""Overview results, independent editing and selected-only JSON export."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from north16.annotations.profiles import DEFAULT_PROFILE,profile_hash
from north16.common.files import sha256,read_table
from north16.gui.overview_jobs import preview_cameras
from north16.gui.window import Window
from north16.segmentation import SegmentationBuilder
from test_dataset_workspace import fixture,add_infrared


def camera_profiles():
    profile=deepcopy(DEFAULT_PROFILE);profile["working_wh"]=[256,144]
    return {camera:deepcopy(profile) for camera in ("back_03","back_04")}


class OverviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        cls.app=QApplication.instance() or QApplication([])

    def test_real_worker_preview_button_completion_and_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/"data";fixture(data);w=Window(data);w.show();self.app.processEvents()
            root=str(data.resolve());seq=w.stream_key[0]
            for c,p in camera_profiles().items():w.stream_profiles[(root,(seq,"visible",c))]=p
            w.apply_profile(camera_profiles()["back_03"])
            w.show_overview()
            QTest.mouseClick(w.overview.preview_button,Qt.MouseButton.LeftButton)
            deadline=time.monotonic()+15
            while w.active_worker and time.monotonic()<deadline:
                self.app.processEvents();time.sleep(.01)
            self.assertIsNone(w.active_worker)
            self.assertEqual(len(w.camera_previews),2)
            self.assertEqual(w.progress.value(),100)
            self.assertTrue(w.overview.cards["back_03"].checkbox.isEnabled())
            w.close()

    def test_parallel_previews_read_only_cancel_and_failure_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/"data";fixture(data);builder=SegmentationBuilder(data)
            before={p:sha256(p) for p in data.rglob("*") if p.is_file()}
            p=camera_profiles()
            p["back_04"]["horizon_normalized_xy"]=[[0,.3],[1,.3]]
            report=preview_cameras(builder,"20260902_044232",profiles=p,frame_index=99,workers=2)
            self.assertEqual((report["succeeded"],report["failed"]),(2,0))
            for result in report["cameras"]:
                self.assertEqual(result["image_name"],"f000001.png")
                self.assertEqual(result["profile_sha256"],profile_hash(p[result["camera"]]))
                self.assertEqual(result["mask"].shape,(144,256))
                self.assertEqual(result["overlay"].size,(256,144))
            cancel=threading.Event();cancel.set()
            stopped=preview_cameras(builder,"20260902_044232",cancel=cancel)
            self.assertEqual((stopped["status"],stopped["succeeded"]),("cancelled",0))
            from north16.gui.overview_jobs import preview as original
            def broken(path,profile,**kwargs):
                if "back_03" in str(path):raise ValueError("camera fault")
                return original(path,profile,**kwargs)
            with patch("north16.gui.overview_jobs.preview",side_effect=broken):
                partial=preview_cameras(builder,"20260902_044232",profiles=p,workers=2)
            self.assertEqual((partial["succeeded"],partial["failed"]),(1,1))
            self.assertEqual(partial["errors"][0]["camera"],"back_03")
            self.assertEqual(before,{p:sha256(p) for p in data.rglob("*") if p.is_file()})

    def test_grid_debugging_cache_staleness_selection_scope_and_ir(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/"data";fixture(data);add_infrared(data)
            w=Window(data);w.show();self.app.processEvents()
            self.assertEqual(set(w.overview.cards),{"back_03","back_04"})
            root=str(data.resolve());seq=w.stream_key[0]
            for c,p in camera_profiles().items():w.stream_profiles[(root,(seq,"visible",c))]=p
            w.apply_profile(camera_profiles()["back_03"])
            w.overview.set_selection({"back_03"})
            jobs=[];w.start=lambda fn,cb,label:jobs.append((fn,cb))
            w.run_camera_previews()
            report=jobs[-1][0](threading.Event(),lambda *_:None);jobs[-1][1](report)
            self.assertEqual(len(w.camera_previews),2)
            self.assertIsNotNone(w.overview.cards["back_04"].result)
            self.assertEqual(w.overview.selected_cameras(),["back_03"])
            QTest.mouseClick(w.overview.cards["back_04"].thumbnail,Qt.MouseButton.LeftButton)
            self.assertEqual(w.stream_key[2],"back_04");self.assertIsNotNone(w.mask)
            self.assertEqual(w.center_tabs.currentIndex(),0)
            old03=w.camera_previews["back_03"]["profile_sha256"]
            w.parameters.inputs["water_probable_brightness_max"].setValue(120)
            self.assertTrue(w.overview.cards["back_04"].stale)
            self.assertFalse(w.overview.cards["back_03"].stale)
            w.run_preview();mask=jobs[-1][0](threading.Event(),lambda *_:None);jobs[-1][1](mask)
            self.assertFalse(w.overview.cards["back_04"].stale)
            self.assertEqual(w.camera_previews["back_03"]["profile_sha256"],old03)
            w.overview.frame_index.setValue(1)
            self.assertTrue(all(card.stale for card in w.overview.cards.values()))
            w.debug_camera("back_03");self.assertEqual(w.current_path.name,"f000001.png")
            w.sequence_combo.setCurrentText("20260902_044732")
            self.assertEqual(len(w.overview.selected_cameras()),2)
            w.overview.set_selection({"back_04"})
            w.sequence_combo.setCurrentText(seq)
            self.assertEqual(w.overview.selected_cameras(),["back_03"])
            w.sensor_combo.setCurrentIndex(w.sensor_combo.findData("infrared"))
            self.assertFalse(w.center_tabs.isTabEnabled(1));self.assertFalse(w.parallel_button.isEnabled())
            w.sensor_combo.setCurrentIndex(0)
            self.assertEqual(w.overview.selected_cameras(),["back_03"])
            w.busy(True)
            self.assertFalse(w.overview.cards["back_03"].checkbox.isEnabled())
            w.busy(False);w.close()

    def test_export_only_checked_and_new_package_excludes_old_cameras(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/"data";fixture(data)
            w=Window(data);root=str(data.resolve());seq=w.stream_key[0]
            for c,p in camera_profiles().items():w.stream_profiles[(root,(seq,"visible",c))]=p
            w.apply_profile(camera_profiles()["back_03"])
            # Seed a prior package with labels from the subsequently unchecked camera.
            b=SegmentationBuilder(data);prior=Path(w.output_field.text())
            b.generate_cameras(seq,prior,cameras=["back_04"],profiles={"back_04":camera_profiles()["back_04"]},estimate=False)
            before={p:sha256(p) for p in prior.rglob("*") if p.is_file()}
            w.overview.set_selection({"back_03"})
            jobs=[];w.start=lambda fn,cb,label:jobs.append((fn,cb))
            w.run_camera_batch()
            report=jobs[-1][0](threading.Event(),lambda *_:None);jobs[-1][1](report)
            current=Path(w.output_field.text())
            self.assertNotEqual(prior,current)
            labels=list((current/"dataset").rglob("*.json"))
            self.assertEqual(len(labels),2)
            self.assertTrue(all(p.parent.parent.name=="back_03" for p in labels))
            self.assertEqual({r["path"].split("/")[3] for r in read_table(current/"files.txt")},{"back_03"})
            self.assertEqual(before,{p:sha256(p) for p in prior.rglob("*") if p.is_file()})
            jobs.clear();errors=[];w.error=errors.append
            w.overview.set_selection(set());w.run_camera_batch()
            self.assertFalse(jobs);self.assertIn("勾选",errors[0])
            self.assertFalse(w.overview.export_button.isEnabled());w.close()
