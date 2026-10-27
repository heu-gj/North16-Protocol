"""Geometric constraints, source protection, annotation identity and GUI wiring."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from north16.common.files import sha256
from north16.registration.dataset import discover
from north16.registration.geometry import fit,project,warp,validate_matrix
from north16.registration.matching import auto_register
from north16.registration.ship_annotations import read_boxes
from north16.registration.storage import save_project,read_project,load_rgb


def fixture(root):
    rng=np.random.default_rng(7)
    pixels=np.zeros((240,320,3),np.uint8)
    for _ in range(120):
        x,y=rng.integers([0,0],[320,240]);color=tuple(map(int,rng.integers(30,255,3)))
        cv2.circle(pixels,(int(x),int(y)),int(rng.integers(2,10)),color,-1)
    matrix=np.float64([[1,0,12],[0,1,8],[0,0,1]])
    for sensor in ('visible','infrared'):
        folder=root/'camera'/('back_'+sensor)/'lens_05';folder.mkdir(parents=True)
        for i in range(2):Image.fromarray(cv2.warpPerspective(pixels,matrix,(320,240)) if sensor=='visible' else pixels).save(folder/f't{i}.png')
    points=[dict(infrared=[x,y],visible=[x+12,y+8],role='fit',source='manual')
            for x,y in [(30,30),(270,30),(270,190),(30,190),(150,100),(240,150)]]
    return pixels,matrix,points


class RegistrationTests(unittest.TestCase):
    def test_native_transform_checks_excluded_from_fit_and_invalid_geometry(self):
        with tempfile.TemporaryDirectory() as temp:
            _,matrix,points=fixture(Path(temp))
            points+=[dict(infrared=[160,80],visible=[175,92],role='check',source='manual')]
            result=fit(points,'homography',(320,240),(320,240),threshold=2)
            self.assertEqual(result['fit_count'],6);self.assertEqual(result['check_count'],1)
            self.assertAlmostEqual(result['check_errors_px'][0],5,places=4)
            self.assertTrue(np.allclose(result['matrix'],matrix,atol=1e-5))
            with self.assertRaises(ValueError):validate_matrix([[0,0,0],[0,0,0],[0,0,1]],(320,240),(320,240))
            collinear=[dict(infrared=[i*20,10],visible=[i*20,10]) for i in range(5)]
            with self.assertRaises(ValueError):fit(collinear,'homography',(320,240),(320,240))

    def test_auto_registration_rejects_black_and_recovers_texture(self):
        with tempfile.TemporaryDirectory() as temp:
            image,matrix,_=fixture(Path(temp));visible=cv2.warpPerspective(image,matrix,(320,240))
            with self.assertRaises(ValueError):auto_register(visible,np.zeros_like(image))
            points,result=auto_register(visible,image)
            probes=np.float64([[40,40],[200,120],[250,180]])
            self.assertLess(np.max(np.linalg.norm(project(result['matrix'],probes)-project(matrix,probes),axis=1)),1)
            regions=[dict(visible=[10,10,310,230],infrared=[0,0,300,220])]
            _,regional=auto_register(visible,image,box_pairs=regions)
            self.assertEqual(regional['ship_roi_pairs'],1)

    def test_project_roundtrip_preserves_sources_and_valid_mask(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'capture';_,_,points=fixture(root)
            pairs=discover(root);self.assertEqual(len(pairs),1)
            key=next(iter(pairs));stamp,v,i=pairs[key][0]
            observations={stamp:dict(points=points,boxes={'visible':[],'infrared':[]},links=[],visible_path=str(v),infrared_path=str(i))}
            before={p:sha256(p) for p in root.rglob('*.png')}
            result=fit(points,'affine',(320,240),(320,240))
            path=save_project(Path(temp)/'results',root,key,stamp,v,i,observations,result)
            restored=read_project(path/'project.json');self.assertFalse(restored['metric_calibration'])
            valid=np.array(Image.open(path/'valid.png'));self.assertEqual(valid.shape,(240,320))
            self.assertTrue(np.all(valid[:8]==0));self.assertTrue(np.all(valid[:,:12]==0))
            for source,digest in before.items():self.assertEqual(sha256(source),digest)
            with self.assertRaises(ValueError):save_project(root,root,key,stamp,v,i,observations,result)
            v.write_bytes(v.read_bytes()+b'changed')
            with self.assertRaises(ValueError):read_project(path/'project.json')

    def test_ship_annotation_identity_and_class_filter(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);_,_,_=fixture(root)
            image=root/'camera/back_visible/lens_05/t0.png';path=root/'boxes.json'
            data=dict(imagePath='t0.png',imageWidth=320,imageHeight=240,shapes=[dict(label='ship',shape_type='rectangle',points=[[10,20],[80,90]]),dict(label='buoy',shape_type='rectangle',points=[[100,20],[110,30]])])
            path.write_text(json.dumps(data),encoding='utf-8');boxes=read_boxes(path,image,(320,240))
            self.assertEqual(len(boxes),1);self.assertEqual(boxes[0]['xyxy'],[10,20,80,90])
            data['imagePath']='other.png';path.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaises(ValueError):read_boxes(path,image,(320,240))

    def test_gui_point_boxes_worker_and_stale_results(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QPointF,Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication,QMessageBox
        from north16.registration.window import RegistrationWindow
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'capture';_,matrix,points=fixture(root)
            w=RegistrationWindow(root,Path(temp)/'output');w.show();app.processEvents();w.fit_views();app.processEvents()
            w.tool.setCurrentIndex(w.tool.findData('point'))
            for sensor,xy in [('visible',(62,58)),('infrared',(50,50))]:
                canvas=getattr(w,sensor+'_view');position=canvas.mapFromScene(QPointF(*xy))
                QTest.mouseClick(canvas.viewport(),Qt.MouseButton.LeftButton,pos=position)
            self.assertEqual(len(w.state()['points']),1)
            self.assertEqual(w.state()['points'][0]['source'],'manual')
            w.state()['points']=deepcopy(points);w.render_annotations();w.solve()
            self.assertIsNotNone(w.result);self.assertFalse(w.stale)
            w.add_box('visible',[10,20,100,120]);w.add_box('infrared',[0,10,90,110]);w.link_boxes()
            self.assertEqual(w.state()['links'],[[0,0]])
            w.move(1);self.assertEqual(w.current_stamp,'t1');self.assertIsNotNone(w.result)
            w.add_point('visible',60,60);w.add_point('infrared',48,52)
            self.assertTrue(w.stale)
            # Automatic worker must restore the entire UI and leave manual points visible.
            w.state()['points']=[];w.run_auto()
            deadline=time.monotonic()+15
            while w.active_worker and time.monotonic()<deadline:app.processEvents();QTest.qWait(10)
            self.assertIsNone(w.active_worker);self.assertTrue(w.centralWidget().isEnabled())
            self.assertTrue(w.main_split.isEnabled());self.assertTrue(w.frames.isEnabled())
            with patch('north16.registration.window.QMessageBox.information'):
                w.save()
                deadline=time.monotonic()+15
                while w.active_worker and time.monotonic()<deadline:app.processEvents();QTest.qWait(10)
            self.assertEqual(len(list((Path(temp)/'output').rglob('project.json'))),1)
            saved=next((Path(temp)/'output').rglob('project.json'))
            w.restore_session(saved)
            self.assertEqual(w.current_stamp,'t1');self.assertIsNotNone(w.result)
            self.assertEqual(w.model.currentData(),w.result['model'])
            w.close()


if __name__=='__main__':unittest.main()
