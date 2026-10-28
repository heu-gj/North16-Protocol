"""GUI state and real folder-workflow checks; no real dataset is modified."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

import numpy as np
from PIL import Image

from north16.annotations.profiles import DEFAULT_PROFILE, profile_hash, validate_profile


@unittest.skipUnless(importlib.util.find_spec("cv2"), "OpenCV optional extra required")
class FolderWorkflowTests(unittest.TestCase):
    def image(self, path):
        rng = np.random.default_rng(42)
        a = np.full((144, 256, 3), 205, np.uint8)
        a[:60] = [120, 150, 180]
        a[90:130, 20:200] = [25, 45, 65]
        noise = rng.integers(-10, 11, a.shape)
        Image.fromarray(np.clip(a.astype(int)+noise, 0, 255).astype(np.uint8)).save(path)

    def test_profiles_and_roundtrip_use_same_segmentation(self):
        from north16.annotations.grabcut import segment
        from north16.annotations.workspace import preview
        with tempfile.TemporaryDirectory() as name:
            path = Path(name)/"图像.png"
            self.image(path)
            p = deepcopy(DEFAULT_PROFILE)
            p["working_wh"] = [256, 144]
            expected = segment(Image.open(path).convert("RGB"), p)
            self.assertTrue(np.array_equal(preview(path, p), expected))
        for key, value in [("water_definite_brightness_max", 250),
                           ("boundary_ignore_kernel", [2, 2]), ("grabcut_iterations", 0)]:
            p = deepcopy(DEFAULT_PROFILE);p[key] = value
            with self.assertRaises(ValueError):validate_profile(p)
        p = deepcopy(DEFAULT_PROFILE);p["horizon_normalized_xy"][0][1] = float("nan")
        with self.assertRaises(ValueError):validate_profile(p)

    def test_batch_export_edit_import_cancel_and_no_overwrite(self):
        from argparse import Namespace
        from north16.annotations.workspace import run_job, export_editor, list_images
        from north16.annotations.xanylabeling import import_project, save_json
        with tempfile.TemporaryDirectory() as name:
            root = Path(name);folder=root/"中文图像";folder.mkdir()
            self.image(folder/"同名.png");self.image(folder/"同名.jpg")
            images = list_images(folder)
            hashes = {p: p.read_bytes() for p in images}
            p = deepcopy(DEFAULT_PROFILE);p["working_wh"] = [256, 144]
            report = run_job(images, p, root/"draft")
            self.assertEqual((report["status"],report["succeeded"]),("succeeded",2))
            with self.assertRaises(FileExistsError):run_job(images,p,root/"draft")
            with self.assertRaises(ValueError):run_job(images,p,folder/"nested")
            self.assertFalse((folder/"nested").exists())
            report = export_editor(root/"draft",root/"editor")
            self.assertEqual(report["succeeded"],2)
            annotation = sorted((root/"editor/images").glob("*.json"))[0]
            data = json.loads(annotation.read_text(encoding="utf-8"))
            data["shapes"].append(dict(label="other",shape_type="polygon",points=[[2,2],[8,2],[8,8],[2,8]]))
            save_json(annotation,data)
            import_project(Namespace(project=str(root/"editor"),output=str(root/"edited"),changed_only=True,preview=True))
            receipt=json.loads((root/"edited/import_log.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["count"],1)
            mask=np.array(Image.open(root/"edited"/receipt["results"][0]["mask"]))
            self.assertTrue(np.all(mask[2:9,2:9]==3))
            cancel=threading.Event()
            report=run_job(images,p,root/"stopped",cancel=cancel,progress=lambda *_:cancel.set())
            self.assertEqual((report["status"],report["succeeded"]),("cancelled",1))
            self.assertEqual(json.loads((root/"stopped/run.json").read_text(encoding="utf-8"))["status"],"cancelled")
            self.assertEqual(len(json.loads((root/"stopped/manifest.json").read_text(encoding="utf-8"))),1)
            for path,content in hashes.items():self.assertEqual(path.read_bytes(),content)


@unittest.skipUnless(importlib.util.find_spec("PySide6") and importlib.util.find_spec("cv2"), "GUI extra required")
class DesktopTests(unittest.TestCase):
    def test_pixel_readout_tracks_zoom_pan_original_values_and_mask_status(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from north16.gui.window import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            pixels=np.empty((240,320,3),np.uint8)
            pixels[:,:,0]=np.arange(320,dtype=np.uint16)[None,:]%256
            pixels[:,:,1]=np.arange(240,dtype=np.uint8)[:,None]
            pixels[:,:,2]=61
            Image.fromarray(pixels).save(root/'a.png')
            Image.new('RGB',(320,240),(7,8,9)).save(root/'b.png')
            window=Window(root);window.resize(1400,900);window.show();app.processEvents()
            def move(view, position):
                # Send a real viewport mouse move, even when offscreen QTest's
                # global cursor position happens to match the preceding test.
                event=QMouseEvent(QEvent.Type.MouseMove,QPointF(position),QPointF(view.viewport().mapToGlobal(position)),
                                  Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
                QApplication.sendEvent(view.viewport(),event);app.processEvents()
            view=window.original_view
            position=view.mapFromScene(QPointF(160.5,120.5))
            move(view,position)
            self.assertIn('尚未生成',window.pixel_label.text())
            # Probe must show original RGB even when result view displays colors.
            window.mask=np.full((240,320),2,np.uint8)
            window.mask[100:140,140:180]=255
            window.result_key=(str(window.current_path),profile_hash(window.current_profile()))
            window.mode.setCurrentIndex(1);window.refresh_display()
            for scale in (1.8,1.4):
                view.scale(scale,scale);view.centerOn(170,125);view.transform_changed.emit();app.processEvents()
                for probe in (window.original_view,window.result_view):
                    pos=probe.mapFromScene(QPointF(160.5,120.5))
                    self.assertTrue(probe.viewport().rect().contains(pos))
                    point=probe.mapToScene(pos);x,y=int(point.x()),int(point.y())
                    move(probe,pos)
                    text=window.pixel_label.text()
                    self.assertIn(f'x={x}  y={y}',text)
                    r,g,b=map(int,pixels[y,x])
                    self.assertIn(f'RGB=({r}, {g}, {b})',text)
                    self.assertIn(f'亮度均值={(r+g+b)/3:.1f}',text)
                    self.assertIn('255（忽略 ignore）',text)
            window.parameters.inputs['grabcut_iterations'].setValue(6)
            self.assertIn('上次结果',window.pixel_label.text())
            view.fit();app.processEvents();move(view,QPoint(1,1))
            self.assertIn('将鼠标移到',window.pixel_label.text())
            move(view,view.mapFromScene(QPointF(160.5,120.5)))
            QApplication.sendEvent(view.viewport(),QEvent(QEvent.Type.Leave))
            self.assertIn('将鼠标移到',window.pixel_label.text())
            window.move(1)
            self.assertIn('将鼠标移到',window.pixel_label.text())
            move(view,view.mapFromScene(QPointF(160.5,120.5)))
            self.assertIn('RGB=(7, 8, 9)',window.pixel_label.text())
            self.assertIn('尚未生成',window.pixel_label.text())
            window.close()

    def test_preview_horizon_stale_state_navigation_and_cancel(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from north16.gui.window import Window
        app=QApplication.instance() or QApplication([])
        if Path("C:/Windows/Fonts/msyh.ttc").exists():QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            for n in ["a.png","b.png"]:FolderWorkflowTests().image(root/n)
            window=Window(root)
            window.resize(1400,900);window.show();app.processEvents()
            window.parameters.inputs["working_width"].setValue(256)
            old=window.original_view.points[1][1]
            handle=window.original_view.handles[1]
            handle.setPos(handle.pos().x(),handle.pos().y()+5)
            self.assertGreater(window.current_profile()["horizon_normalized_xy"][1][1],old)
            QTest.mouseClick(window.preview_button,Qt.MouseButton.LeftButton)
            deadline=time.monotonic()+30
            while window.active_worker and time.monotonic()<deadline:
                app.processEvents();QTest.qWait(10)
            self.assertIsNone(window.active_worker)
            self.assertIsNotNone(window.mask)
            self.assertEqual(window.result_key[1],profile_hash(window.current_profile()))
            window.parameters.inputs["grabcut_iterations"].setValue(6)
            self.assertIn("上次结果",window.result_label.text())
            window.move(1);self.assertIsNone(window.mask)
            self.assertEqual(window.current_path.name,"b.png")
            window.start(lambda cancel,progress: (cancel.wait(2),"done")[1],lambda _:None,"test")
            window.stop()
            deadline=time.monotonic()+5
            while window.active_worker and time.monotonic()<deadline:
                app.processEvents();QTest.qWait(10)
            self.assertIsNone(window.active_worker)
            window.close()


if __name__ == "__main__":unittest.main()
