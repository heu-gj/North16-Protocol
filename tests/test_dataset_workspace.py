"""Dataset identities, fixed routing, source protection and GUI integration."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from north16.annotations.dataset_workspace import DatasetWorkspace, run_dataset_job
from north16.annotations.profiles import DEFAULT_PROFILE
from north16.common.files import read_table, sha256, write_info, write_table
from north16.preprocess.index import SAMPLE_COLUMNS


def fixture(root):
    root.mkdir()
    write_info(root/'info.txt',dict(protocol_id='north16-seg-v0.1-draft',dataset_status='working'))
    write_info(root/'protocol.txt',dict(schema_version='north16_seg_v1',protocol_id='north16-seg-v0.1-draft',task='semantic_segmentation',num_classes=4,ignore_index=255))
    write_info(root/'classes.txt',dict(sky=0,water=1,ice=2,other=3,ignore=255))
    rows=[]
    for seq in ['20260902_044232','20260902_044732']:
        for camera in ['back_03','back_04']:
            frames=[]
            for i in range(2):
                name=f'f{i:06d}'
                stream=f'sequences/{seq}/visible/{camera}'
                row=dict(id=f'n16_{seq}_visible_{camera}_{name}',sequence=seq,sensor='visible',camera=camera,
                         image=f'{stream}/images/{name}.png',meta=f'{stream}/meta/{name}.txt',mask='',
                         weather='unknown',illumination='day',group='unknown',label_status='unlabeled')
                pixels=np.full((144,256,3),205,np.uint8)
                pixels[:60]=[120,150,180];pixels[90:130,20:200]=[25,45,65]
                pixels=np.clip(pixels.astype(int)+np.random.default_rng(i).integers(-6,7,pixels.shape),0,255).astype(np.uint8)
                image=root/row['image'];image.parent.mkdir(parents=True,exist_ok=True);Image.fromarray(pixels).save(image)
                write_info(root/row['meta'],dict(id=row['id'],image=row['image']))
                frames.append(dict(id=row['id'],image=row['image'],meta=row['meta'],image_sha256=sha256(image),image_bytes=image.stat().st_size))
                rows.append(row)
            write_table(root/stream/'frames.txt',frames[0].keys(),frames)
    write_table(root/'samples.txt',SAMPLE_COLUMNS,rows)
    return rows


def add_infrared(root, *, infrared_only=False):
    rows=read_table(root/'samples.txt')
    infrared=[]
    frames={}
    for row in rows:
        item=dict(row)
        for key in ('id','image','meta'):
            item[key]=item[key].replace('visible','infrared')
        item['sensor']='infrared'
        image=root/item['image'];image.parent.mkdir(parents=True,exist_ok=True)
        # Real extracted IR is 8-bit display data, not a temperature product.
        Image.new('L',(256,144),137).save(image)
        write_info(root/item['meta'],dict(id=item['id'],image=item['image']))
        stream=image.parent.parent
        frames.setdefault(stream,[]).append(dict(id=item['id'],image=item['image'],meta=item['meta'],image_sha256=sha256(image),image_bytes=image.stat().st_size))
        infrared.append(item)
    for stream,records in frames.items():write_table(stream/'frames.txt',records[0].keys(),records)
    write_table(root/'samples.txt',SAMPLE_COLUMNS,infrared if infrared_only else rows+infrared)


@unittest.skipUnless(importlib.util.find_spec('cv2'),'OpenCV extra required')
class DatasetWorkspaceTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('PySide6'),'GUI extra required')
    def test_infrared_browsing_keeps_sensor_identity_and_blocks_visible_segmentation(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from north16.gui.window import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'datasets';fixture(root);add_infrared(root)
            hashes={p:sha256(p) for p in root.rglob('*') if p.is_file()}
            window=Window(root);window.show();app.processEvents()
            window.camera_combo.setCurrentText('back_04')
            window.parameters.inputs['water_probable_brightness_max'].setValue(101)
            window.sensor_combo.setCurrentIndex(window.sensor_combo.findData('infrared'))
            self.assertEqual(window.stream_key,('20260902_044232','infrared','back_04'))
            self.assertEqual(len(window.dataset_workspace.keys(None)),8)
            self.assertEqual(window.source.getpixel((30,30)),(137,137,137))
            for button in (window.preview_button,window.estimate_button,window.sample_button,window.batch_button,window.export_button):
                self.assertFalse(button.isEnabled())
            window.inspect_pixel(window.original_view,30,30)
            self.assertIn('RGB=(137, 137, 137)',window.pixel_label.text())
            self.assertIn('非温度',window.pixel_label.text())
            window.move(1);self.assertEqual(window.current_path.name,'f000001.png')
            self.assertFalse(window.original_view.show_horizon)
            window.run_preview();window.run_estimation();window.run_batch();window.run_samples()
            self.assertIsNone(window.active_worker)
            self.assertFalse((root/'annotations').exists())
            window.sensor_combo.setCurrentIndex(0)
            self.assertTrue(window.preview_button.isEnabled())
            self.assertEqual(window.parameters.inputs['water_probable_brightness_max'].value(),101)
            window.open_folder(root/'sequences/20260902_044732/infrared/back_03/images')
            self.assertEqual(window.stream_key,('20260902_044732','infrared','back_03'))
            self.assertIn('infrared',str(window.current_path))
            window.close()
            self.assertEqual({p:sha256(p) for p in root.rglob('*') if p.is_file()},hashes)

    @unittest.skipUnless(importlib.util.find_spec('PySide6'),'GUI extra required')
    def test_infrared_only_dataset_and_plain_image_folder_can_be_browsed(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from north16.gui.window import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'datasets';fixture(root);add_infrared(root,infrared_only=True)
            window=Window(root)
            self.assertEqual(window.current_sensor(),'infrared')
            self.assertIsNotNone(window.current_path)
            plain=Path(temp)/'plain_ir';plain.mkdir();Image.new('RGB',(160,120),(25,25,25)).save(plain/'ir.png')
            window.open_folder(plain)
            self.assertIsNone(window.dataset_workspace)
            self.assertEqual(window.current_sensor(),'infrared')
            self.assertEqual(window.source.size,(160,120))
            self.assertFalse(window.preview_button.isEnabled())
            window.close()

    def test_same_frame_names_keep_global_ids_and_editor_round_trip(self):
        from argparse import Namespace
        from north16.annotations.workspace import export_editor
        from north16.annotations.xanylabeling import import_project
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'datasets';rows=fixture(root);ws=DatasetWorkspace(root)
            original={p:sha256(p) for p in root.rglob('*') if p.is_file()}
            profile=deepcopy(DEFAULT_PROFILE);profile['working_wh']=[256,144]
            ids=[]
            for key in ws.keys()[:2]:
                out=ws.output_path('drafts',key,ws.new_run_id())
                result=run_dataset_job(ws,key,ws.images(key)[:1],profile,out)
                self.assertEqual(result['succeeded'],1)
                self.assertTrue((out/'masks/f000000.png').is_file())
                row=read_table(out/'samples.txt')[0];ids.append(row['id'])
                self.assertEqual((row['label_status'],row['camera']),('draft',key[2]))
                self.assertEqual((root/row['mask']).resolve(), (out/'masks/f000000.png').resolve())
            self.assertNotEqual(*ids)
            project=ws.output_path('projects',key,ws.new_run_id())
            export_editor(out,project)
            manifest=read_table(project/'manifest.txt')[0]
            self.assertEqual(manifest['id'],ids[-1])
            self.assertEqual(manifest['camera'],key[2])
            self.assertTrue((project/'images/f000000.json').is_file())
            data=json.loads((project/'images/f000000.json').read_text(encoding='utf-8'))
            data['shapes'].append(dict(label='other',shape_type='polygon',points=[[2,2],[8,2],[8,8],[2,8]]))
            (project/'images/f000000.json').write_text(json.dumps(data),encoding='utf-8')
            corrected=Path(temp)/'corrected'
            import_project(Namespace(project=str(project),output=str(corrected),changed_only=True,preview=True))
            result=json.loads((corrected/'import_log.json').read_text(encoding='utf-8'))['results'][0]
            self.assertEqual(result['id'],ids[-1])
            mask=np.array(Image.open(corrected/result['mask']))
            self.assertTrue(np.all(mask[2:9,2:9]==3))
            for p,expected in original.items():self.assertEqual(sha256(p),expected)

    def test_tampered_source_index_and_arbitrary_destinations_fail_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'datasets';fixture(root);ws=DatasetWorkspace(root)
            key=ws.keys()[0];images=ws.images(key)
            out=ws.output_path('drafts',key,'test')
            with self.assertRaises(ValueError):run_dataset_job(ws,key,images,DEFAULT_PROFILE,root/'arbitrary')
            self.assertFalse((root/'arbitrary').exists())
            with self.assertRaises(ValueError):run_dataset_job(ws,key,ws.images(ws.keys()[1]),DEFAULT_PROFILE,out)
            self.assertFalse(out.exists())
            content=images[0].read_bytes();images[0].write_bytes(content+b'tampered')
            with self.assertRaises(ValueError):run_dataset_job(ws,key,images,DEFAULT_PROFILE,out)
            self.assertFalse(out.exists());images[0].write_bytes(content)
            with (root/'samples.txt').open('a',encoding='utf-8') as handle:handle.write('\n')
            with self.assertRaisesRegex(ValueError,'索引或协议'):run_dataset_job(ws,key,images,DEFAULT_PROFILE,out)
            self.assertFalse(out.exists())

    def test_cancel_preserves_partial_draft_index_and_frozen_dataset_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'datasets';fixture(root);ws=DatasetWorkspace(root)
            key=ws.keys()[0];out=ws.output_path('drafts',key,'partial')
            cancel=threading.Event();profile=deepcopy(DEFAULT_PROFILE);profile['working_wh']=[256,144]
            result=run_dataset_job(ws,key,ws.images(key),profile,out,cancel=cancel,progress=lambda *_:cancel.set())
            self.assertEqual((result['status'],len(read_table(out/'samples.txt'))),('cancelled',1))
            self.assertTrue(all(not (root/f'sequences/{k[0]}/{k[1]}/{k[2]}/masks').exists() for k in ws.keys()))
            write_info(root/'info.txt',dict(protocol_id='north16-seg-v0.1-draft',dataset_status='frozen'))
            with self.assertRaisesRegex(ValueError,'working'):DatasetWorkspace(root)

    @unittest.skipUnless(importlib.util.find_spec('PySide6'),'GUI extra required')
    def test_gui_root_navigation_profiles_and_automatic_outputs(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QMessageBox
        from PySide6.QtTest import QTest
        from north16.gui.window import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'datasets';fixture(root)
            window=Window(root);window.show();app.processEvents()
            self.assertEqual(window.sequence_combo.count(),2)
            self.assertEqual(window.camera_combo.count(),2)
            self.assertTrue(window.output_field.isReadOnly())
            self.assertTrue(window.output_button.isEnabled())
            window.parameters.inputs['working_width'].setValue(256)
            window.parameters.inputs['grabcut_iterations'].setValue(2)
            window.camera_combo.setCurrentText('back_04')
            self.assertEqual(window.parameters.inputs['grabcut_iterations'].value(),5)
            window.camera_combo.setCurrentText('back_03')
            self.assertEqual(window.parameters.inputs['grabcut_iterations'].value(),2)
            window.save_parameters()
            self.assertEqual(len(list((Path(window.output_field.text())/'parameters').rglob('*.validation.json'))),1)
            out=Path(window.output_field.text())
            with patch('north16.gui.window.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
                window.save_current()
            deadline=time.monotonic()+30
            while window.active_worker and time.monotonic()<deadline:app.processEvents();QTest.qWait(10)
            self.assertIsNone(window.active_worker)
            label=out/'dataset/sequences/20260902_044232/visible/back_03/masks/f000000.json'
            self.assertTrue(label.is_file())
            self.assertEqual(Path(window.output_field.text()),out)
            with patch('north16.gui.window.QFileDialog.getExistingDirectory',side_effect=AssertionError('must use preset project path')),patch('north16.gui.window.QMessageBox.information'):
                window.run_export()
                deadline=time.monotonic()+30
                while window.active_worker and time.monotonic()<deadline:app.processEvents();QTest.qWait(10)
            self.assertIsNone(window.active_worker)
            self.assertFalse((root/'annotations').exists())
            before=sha256(label)
            with patch('north16.gui.window.QMessageBox.information'):
                window.run_export()
            self.assertIsNone(window.active_worker)
            self.assertEqual(sha256(label),before)
            window.sequence_combo.setCurrentText('20260902_044732')
            self.assertEqual(Path(window.output_field.text()),out)
            window.save_current()
            deadline=time.monotonic()+30
            while window.active_worker and time.monotonic()<deadline:app.processEvents();QTest.qWait(10)
            self.assertTrue((out/'dataset/sequences/20260902_044732/visible/back_03/masks/f000000.json').is_file())
            window.close()
