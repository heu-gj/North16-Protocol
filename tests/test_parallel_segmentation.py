"""Concurrency, per-camera provenance and portable-package regression checks."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from north16.annotations.profiles import DEFAULT_PROFILE
from north16.common.files import read_table, sha256, write_table
from north16.packages import import_package
from north16.segmentation import SegmentationBuilder
from north16.segmentation.labels import render
from test_dataset_workspace import fixture, add_infrared


def profiles(builder, mode="mixed"):
    p=deepcopy(DEFAULT_PROFILE);p["working_wh"]=[256,144];p["sea_mode"]=mode
    return {key[2]:deepcopy(p) for key in builder.workspace.keys()}


class ParallelTests(unittest.TestCase):
    def test_python_cli_estimation_and_parallel_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);data=root/"data";fixture(data)
            cli=Path(__file__).resolve().parents[1]/"cli.py"
            env=dict(os.environ,PYTHONIOENCODING="utf-8")
            common=[sys.executable,str(cli),"segmentation"]
            args=["--root",str(data),"--sequence","20260902_044232","--workers","2"]
            run=subprocess.run(common+["estimate",*args],check=True,capture_output=True,encoding="utf-8",env=env)
            self.assertEqual(json.loads(run.stdout)["succeeded"],2)
            folder=root/"profiles";folder.mkdir()
            for camera,p in profiles(SegmentationBuilder(data),"ice_only").items():
                (folder/(camera+".json")).write_text(json.dumps(p),encoding="utf-8")
            run=subprocess.run(common+["batch",*args,"--output",str(root/"labels"),"--profiles",str(folder),
                                       "--no-estimate","--limit","1"],check=True,capture_output=True,encoding="utf-8",env=env)
            self.assertEqual(json.loads(run.stdout)["succeeded"],2)
            self.assertEqual(len(read_table(root/"labels/files.txt")),2)

    def test_independent_estimation_parallel_equals_serial_and_imports(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);data=root/"data";fixture(data)
            # A second camera sees different brightness and a different line.
            stream=data/"sequences/20260902_044232/visible/back_04"
            rows=read_table(stream/"frames.txt")
            for row in rows:
                image=data/row["image"]
                pixels=np.array(Image.open(image)).astype(int)
                Image.fromarray(np.clip(pixels+40,0,255).astype(np.uint8)).save(image)
                row["image_sha256"]=sha256(image)
            write_table(stream/"frames.txt",rows[0].keys(),rows)
            before={p:sha256(p) for p in data.rglob("*") if p.is_file()}
            builder=SegmentationBuilder(data);p=profiles(builder)
            p["back_04"]["horizon_normalized_xy"]=[[0,.35],[1,.35]]
            seq="20260902_044232"
            original_threads=cv2.getNumThreads()
            report=builder.estimate_cameras(seq,profiles=p,workers=2)
            a,b=report["cameras"]
            self.assertNotEqual(a["profile"]["water_definite_brightness_max"],b["profile"]["water_definite_brightness_max"])
            self.assertEqual(b["profile"]["horizon_normalized_xy"],[[0,.35],[1,.35]])
            self.assertEqual(a["estimation"]["horizon"]["status"],"preserved")
            self.assertEqual(len(a["estimation"]["samples"]),2)
            serial=builder.generate_cameras(seq,root/"serial",profiles=p,workers=1)
            concurrent=builder.generate_cameras(seq,root/"parallel",profiles=p,workers=2)
            self.assertEqual((concurrent["status"],concurrent["succeeded"]),("succeeded",4))
            self.assertEqual(cv2.getNumThreads(),original_threads)
            prepared_profiles={c["camera"]:c["profile"] for c in report["cameras"]}
            evidence={c["camera"]:c["estimation"] for c in report["cameras"]}
            reused=builder.generate_cameras(seq,root/"reuse",profiles=prepared_profiles,estimations=evidence,workers=2,estimate=False)
            self.assertEqual(reused["cameras"][0]["estimation"],evidence["back_03"])
            prepared_profiles["back_03"]["rng_seed"]+=1
            changed=builder.generate_cameras(seq,root/"edited",profiles=prepared_profiles,estimations=evidence,workers=2,estimate=False)
            self.assertIsNone(changed["cameras"][0]["estimation"])
            self.assertEqual(len(read_table(root/"parallel/files.txt")),4)
            self.assertFalse((root/"parallel/.segmentation.lock").exists())
            self.assertEqual([r["profile"] for r in serial["cameras"]],[r["profile"] for r in concurrent["cameras"]])
            for label in concurrent["labels"]:
                x=json.loads((root/"serial"/label).read_text(encoding="utf-8"))
                y=json.loads((root/"parallel"/label).read_text(encoding="utf-8"))
                self.assertTrue(np.array_equal(render(x),render(y)))
                self.assertEqual(x["north16"]["id"],y["north16"]["id"])
                self.assertEqual(y["north16"]["label_status"],"draft")
            import_package(data,root/"parallel")
            for path,digest in before.items():self.assertEqual(sha256(path),digest)

    def test_actual_worker_overlap_camera_failure_and_cancellation(self):
        from north16.annotations.workspace import preview as real_preview
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);data=root/"data";fixture(data)
            builder=SegmentationBuilder(data);seq="20260902_044232";p=profiles(builder,"ice_only")
            barrier=threading.Barrier(2);threads=set();lock=threading.Lock()
            def overlapping(path,profile,**kwargs):
                with lock:threads.add(threading.get_ident())
                barrier.wait(timeout=10)
                return real_preview(path,profile,**kwargs)
            with patch("north16.annotations.workspace.preview",side_effect=overlapping):
                r=builder.generate_cameras(seq,root/"overlap",profiles=p,workers=2,estimate=False)
            self.assertEqual(r["succeeded"],4);self.assertEqual(len(threads),2)
            cancel=threading.Event()
            r=builder.generate_cameras(seq,root/"cancelled",profiles=p,workers=2,estimate=False,
                                       cancel=cancel,progress=lambda *_:cancel.set())
            self.assertEqual(r["status"],"cancelled")
            self.assertGreaterEqual(r["succeeded"],1)
            self.assertEqual(r["succeeded"],len(read_table(root/"cancelled/files.txt")))
            self.assertEqual(r["expected"],r["succeeded"]+r["failed"]+r["unprocessed"])
            bad=builder.workspace.images((seq,"visible","back_03"))[0]
            Image.new("RGB",(256,144),"white").save(bad)
            r=builder.generate_cameras(seq,root/"failure",profiles=p,workers=2)
            self.assertEqual((r["status"],r["succeeded"],r["failed"]),("completed_with_errors",2,2))
            self.assertEqual(len(read_table(root/"failure/files.txt")),2)

    def test_conflicts_locks_default_horizon_and_inconsistent_estimates(self):
        from north16.segmentation.batch import estimate_camera
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);data=root/"data";fixture(data)
            builder=SegmentationBuilder(data);seq="20260902_044232";p=profiles(builder,"ice_only")
            builder.generate_cameras(seq,root/"labels",profiles=p,workers=1,estimate=False)
            before={f:sha256(f) for f in (root/"labels").rglob("*") if f.is_file()}
            with self.assertRaises(FileExistsError):builder.generate_cameras(seq,root/"labels",profiles=p)
            self.assertEqual(before,{f:sha256(f) for f in (root/"labels").rglob("*") if f.is_file()})
            with builder._package(root/"locked"):
                with self.assertRaises(FileExistsError):builder.generate_cameras(seq,root/"locked",profiles=p)
            report=builder.estimate_cameras(seq,workers=2)
            self.assertTrue(all("默认值" in " ".join(c["estimation"]["warnings"]) for c in report["cameras"]))
            item=dict(key=(seq,"visible","back_03"),profile=DEFAULT_PROFILE,profile_source="camera_profile",
                      images=builder.workspace.images((seq,"visible","back_03")))
            def inconsistent(path,base,**kwargs):
                out=deepcopy(base);offset=0 if Path(path).stem=="f000000" else 70
                out.update(water_definite_brightness_max=10+offset,water_probable_brightness_max=80+offset,ice_definite_brightness_min=170+offset)
                return out,dict(horizon=dict(status="preserved"),brightness=dict(status="suggested"))
            with patch("north16.segmentation.batch.estimate_parameters",side_effect=inconsistent):
                result=estimate_camera(item)
            self.assertEqual(result["estimation"]["brightness"]["status"],"retained")
            self.assertEqual(result["profile"],DEFAULT_PROFILE)
            # Rejected per-frame horizon candidates must not leak into the
            # brightness stage: rerun it with the final retained camera line.
            calls=[]
            def candidates(path,base,*,keep_horizon):
                calls.append((keep_horizon,deepcopy(base["horizon_normalized_xy"])))
                out=deepcopy(base)
                if not keep_horizon:
                    y=.2 if Path(path).stem=="f000000" else .7
                    out["horizon_normalized_xy"]=[[0,y],[1,y]]
                return out,dict(source_image=str(path),horizon=dict(status="preserved" if keep_horizon else "suggested"),brightness=dict(status="suggested"))
            with patch("north16.segmentation.batch.estimate_parameters",side_effect=candidates):
                result=estimate_camera(item,keep_horizon=False)
            self.assertEqual(result["estimation"]["horizon"]["status"],"retained")
            self.assertTrue(all(line==DEFAULT_PROFILE["horizon_normalized_xy"] for keep,line in calls if keep))
            for n in (0,17):
                with self.assertRaises(ValueError):builder.estimate_cameras(seq,workers=n)

    def test_sixteen_camera_selection_and_bounded_concurrency(self):
        # Extend the protocol fixture to all sixteen streams; actual workers
        # produce JSON, manifests and per-camera parameter files.
        from north16.common.files import write_info
        from north16.preprocess.index import SAMPLE_COLUMNS
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);data=root/"data";fixture(data)
            old=read_table(data/"samples.txt");template=old[0];seq=template["sequence"]
            rows=[r for r in old if r["sequence"]!=seq]
            for camera in [f"{side}_{i:02d}" for side in ("front","back") for i in range(1,9)]:
                row=dict(template,camera=camera)
                for k in ("id","image","meta"):row[k]=row[k].replace(template["camera"],camera)
                image=data/row["image"];image.parent.mkdir(parents=True,exist_ok=True)
                Image.new("RGB",(256,144),(200,200,200)).save(image)
                write_info(data/row["meta"],dict(id=row["id"],image=row["image"]))
                write_table(image.parent.parent/"frames.txt",("id","image","meta","image_sha256"),
                            [dict(id=row["id"],image=row["image"],meta=row["meta"],image_sha256=sha256(image))])
                rows.append(row)
            write_table(data/"samples.txt",SAMPLE_COLUMNS,rows)
            builder=SegmentationBuilder(data)
            r=builder.generate_cameras(seq,root/"labels",profiles=profiles(builder,"ice_only"),workers=4,estimate=True)
            self.assertEqual((len(r["cameras"]),r["succeeded"]),(16,16))
            self.assertEqual(len(list((root/"labels/dataset").glob("sequences/*/visible/*/masks/*.json"))),16)
            self.assertEqual({r["sequence"]},{seq})

    def test_gui_controls_apply_profiles_and_disable_for_infrared(self):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        from PySide6.QtWidgets import QApplication,QMessageBox
        from north16.gui.window import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp:
            data=Path(temp)/"data";fixture(data);add_infrared(data)
            w=Window(data);app.processEvents()
            self.assertTrue(w.parallel_button.isEnabled())
            w.parameters.inputs["water_probable_brightness_max"].setValue(100)
            jobs=[]
            w.start=lambda fn,callback,label:jobs.append((fn,callback))
            w.run_camera_estimation()
            report=jobs[0][0](threading.Event(),lambda *_:None)
            with patch.object(QMessageBox,"exec",return_value=QMessageBox.StandardButton.Ok):jobs[0][1](report)
            self.assertFalse(w.parallel_estimate.isChecked())
            self.assertEqual(len(w.camera_estimations),2)
            self.assertEqual(w.estimation_for_profile(w.current_profile())["camera"],"back_03")
            w.camera_combo.setCurrentText("back_04")
            self.assertEqual(w.current_profile(),report["cameras"][1]["profile"])
            self.assertEqual(w.estimation_for_profile(w.current_profile())["camera"],"back_04")
            w.busy(True);self.assertFalse(w.parallel_button.isEnabled());self.assertFalse(w.parallel_workers.isEnabled())
            w.busy(False);self.assertTrue(w.parallel_button.isEnabled())
            w.sensor_combo.setCurrentIndex(w.sensor_combo.findData("infrared"))
            self.assertFalse(w.parallel_button.isEnabled());self.assertFalse(w.estimate_cameras_button.isEnabled())
            w.open_folder(data/"sequences/20260902_044232/visible/back_03/images")
            self.assertTrue(w.parallel_button.isEnabled())
            w.close()
