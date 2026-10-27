"""Default 1% band, all-camera three-frame validation and source preservation."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from north16.annotations.profiles import DEFAULT_PROFILE,load_profile,profile_hash
from north16.common.files import read_table,sha256,write_info,write_table
from north16.gui.overview_jobs import validate_camera_samples
from north16.gui.sample_validation import SampleValidationDialog
from north16.gui.window import Window
from north16.preprocess.index import SAMPLE_COLUMNS
from north16.segmentation import SegmentationBuilder
from test_dataset_workspace import fixture


def fixture_three(root):
    fixture(root)
    rows=read_table(root/"samples.txt")
    for row in list(rows):
        if Path(row["image"]).stem!="f000001":continue
        extra=dict(row)
        for k in ("id","image","meta"):extra[k]=extra[k].replace("f000001","f000002")
        shutil.copyfile(root/row["image"],root/extra["image"])
        write_info(root/extra["meta"],dict(id=extra["id"],image=extra["image"]))
        path=(root/extra["image"]).parent.parent/"frames.txt"
        frames=read_table(path)
        frames.append(dict(id=extra["id"],image=extra["image"],meta=extra["meta"],image_sha256=sha256(root/extra["image"])))
        write_table(path,frames[0].keys(),frames)
        rows.append(extra)
    write_table(root/"samples.txt",SAMPLE_COLUMNS,rows)


def profiles():
    p=deepcopy(DEFAULT_PROFILE);p["working_wh"]=[256,144]
    return {c:deepcopy(p) for c in ("back_03","back_04")}


class CameraSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        cls.app=QApplication.instance() or QApplication([])

    def test_default_band_and_explicit_legacy_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root/"data");w=Window(root/"data")
            self.assertEqual(w.parameters.inputs["band"].value(),1.0)
            self.assertEqual(w.current_profile()["horizon_ignore_half_height"],.01)
            old=deepcopy(DEFAULT_PROFILE);old["horizon_ignore_half_height"]=.02
            path=root/"legacy.json";path.write_text(json.dumps(old),encoding="utf-8")
            saved_hash=sha256(path)
            loaded=load_profile(path);w.apply_profile(loaded)
            self.assertEqual(w.parameters.inputs["band"].value(),2.0)
            self.assertNotEqual(profile_hash(old),profile_hash(DEFAULT_PROFILE))
            w.apply_profile(DEFAULT_PROFILE)
            self.assertEqual(w.parameters.inputs["band"].value(),1.0)
            self.assertEqual(sha256(path),saved_hash)
            w.close()

    def test_sampling_all_positions_independent_profiles_read_only_and_short_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/"data";fixture_three(data);b=SegmentationBuilder(data)
            before={p:sha256(p) for p in data.rglob("*") if p.is_file()}
            p=profiles();p["back_03"]["sea_mode"]="ice_only";p["back_04"]["sea_mode"]="water_only"
            r=validate_camera_samples(b,"20260902_044232",profiles=p,workers=2)
            self.assertEqual((r["expected"],r["succeeded"],r["failed"]),(6,6,0))
            for camera in r["cameras"]:
                self.assertEqual([s["frame_index"] for s in camera["samples"]],[0,1,2])
                self.assertEqual([s["position"] for s in camera["samples"]],["start","middle","end"])
                self.assertEqual(camera["profile_sha256"],profile_hash(p[camera["camera"]]))
                for s in camera["samples"]:
                    self.assertNotIn("mask",s["result"])
                    self.assertEqual(len(s["result"]["mask_sha256"]),64)
            self.assertNotEqual(r["cameras"][0]["samples"][0]["result"]["mask_sha256"],r["cameras"][1]["samples"][0]["result"]["mask_sha256"])
            self.assertEqual(before,{p:sha256(p) for p in data.rglob("*") if p.is_file()})
            short=Path(tmp)/"short";fixture(short)
            r=validate_camera_samples(SegmentationBuilder(short),"20260902_044232",profiles=profiles(),workers=2)
            self.assertEqual(r["expected"],4)
            self.assertEqual([s["frame_index"] for s in r["cameras"][0]["samples"]],[0,1,1])

    def test_cancel_partial_failure_layout_switching_and_stale_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/"data";fixture_three(data);b=SegmentationBuilder(data)
            cancel=threading.Event();cancel.set()
            r=validate_camera_samples(b,"20260902_044232",profiles=profiles(),cancel=cancel)
            self.assertEqual((r["status"],r["unprocessed"]),("cancelled",6))
            from north16.gui.overview_jobs import preview as original
            def broken(path,profile,**kwargs):
                if "back_03" in str(path) and path.stem=="f000001":raise ValueError("sample error")
                return original(path,profile,**kwargs)
            with patch("north16.gui.overview_jobs.preview",side_effect=broken):
                r=validate_camera_samples(b,"20260902_044232",profiles=profiles(),workers=2)
            self.assertEqual((r["succeeded"],r["failed"]),(5,1))
            d=SampleValidationDialog(r);d.show();self.app.processEvents()
            self.assertEqual(len(d.visible_samples),2)
            d.positions.setCurrentIndex(1)
            self.assertTrue(all(position=="middle" for _,position,_ in d.visible_samples))
            d.layout_mode.setCurrentIndex(1)
            self.assertEqual(len(d.visible_samples),6)
            d.display_mode.setCurrentIndex(1)
            self.assertEqual(len(d.visible_samples),6)
            d.mark_profile(str(data.resolve()),r["sequence"],"back_03","edited")
            self.assertEqual(d.stale_cameras,{"back_03"})
            d.mark_profile(str(data.resolve()),r["sequence"],"back_03",r["cameras"][0]["profile_sha256"])
            self.assertFalse(d.stale_cameras);d.close()
            all_cameras=[f"{side}_{i:02d}" for side in ("front","back") for i in range(1,9)]
            grid_report=dict(r,cameras=[dict(r["cameras"][i%2],camera=c) for i,c in enumerate(all_cameras)])
            grid=SampleValidationDialog(grid_report);grid.show();self.app.processEvents()
            self.assertEqual(len(grid.visible_samples),16)
            self.assertEqual(grid.scroll.verticalScrollBar().maximum(),0)
            grid.close()

    def test_gui_real_worker_validates_unchecked_cameras_and_tracks_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/"data";fixture_three(data);w=Window(data);w.show();self.app.processEvents()
            root=str(data.resolve());seq=w.stream_key[0]
            for camera,p in profiles().items():w.stream_profiles[(root,(seq,"visible",camera))]=p
            w.apply_profile(profiles()["back_03"])
            w.overview.set_selection(set())
            self.assertTrue(w.overview.samples_button.isEnabled())
            QTest.mouseClick(w.sample_button,Qt.MouseButton.LeftButton)
            deadline=time.monotonic()+15
            while w.active_worker and time.monotonic()<deadline:
                self.app.processEvents();time.sleep(.01)
            self.assertIsNone(w.active_worker)
            self.assertIsNotNone(w.sample_dialog)
            self.assertEqual(len(w.sample_dialog.report["cameras"]),2)
            self.assertEqual(w.sample_dialog.report["succeeded"],6)
            self.assertEqual(len(w.validations_for_profile(w.current_profile())),3)
            self.assertFalse(w.overview.selected_cameras())
            w.parameters.inputs["water_probable_brightness_max"].setValue(124)
            self.assertEqual(w.sample_dialog.stale_cameras,{"back_03"})
            self.assertFalse(w.validations_for_profile(w.current_profile()))
            changed=profiles()["back_04"];changed["rng_seed"]+=1
            w.apply_camera_results([dict(camera="back_04",profile=changed)])
            self.assertEqual(w.sample_dialog.stale_cameras,{"back_03","back_04"})
            self.assertEqual(w.progress.value(),100)
            w.sample_dialog.close();w.close()
