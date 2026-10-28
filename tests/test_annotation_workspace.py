"""Real video -> isolated annotation -> selected delivery -> Dataset roundtrip."""
from copy import deepcopy
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from north16.annotation import AnnotationWorkspace, AnnotationBuilder
from north16.annotations.profiles import DEFAULT_PROFILE
from north16.cli import main
from north16.common.files import read_info, read_table, sha256
from north16.datasets import CameraDataset, SegmentationDataset
from north16.layout import DatasetInitializer
from north16.packages import import_package
from test_build import FFMPEG, FFPROBE
from test_modules import raw_fixture


def setup(root):
    raw=raw_fixture(root)
    first=next(raw.glob('*/camera/front_visible/lens_01.mp4'))
    shutil.copyfile(first,first.with_name('lens_02.mp4'))
    final=root/'datasets';annotation=root/'annotation'
    DatasetInitializer().initialize(raw,final)
    AnnotationWorkspace.initialize(annotation,dataset=final)
    workspace=AnnotationWorkspace(annotation)
    workspace.extract(interval=1,ffmpeg=FFMPEG,ffprobe=FFPROBE)
    profile=deepcopy(DEFAULT_PROFILE)
    profile.update(sea_mode='ice_only',working_wh=[256,192])
    return final,workspace,profile


class AnnotationTests(unittest.TestCase):
    def test_initialization_is_empty_and_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=raw_fixture(root)
            with patch('subprocess.run',side_effect=AssertionError('No media processing')):
                DatasetInitializer().initialize(raw,root/'datasets')
                report=AnnotationWorkspace.initialize(root/'annotation',dataset=root/'datasets')
                AnnotationWorkspace.initialize(root/'direct',raw=raw)
            self.assertEqual(report['images'],0)
            for name in ('datasets','annotation','direct'):
                self.assertFalse(list((root/name).rglob('*.png')))
                self.assertFalse(list((root/name).rglob('masks')))
            self.assertEqual(read_table(root/'annotation/sources.txt'),read_table(root/'datasets/sources.txt'))
            self.assertEqual(read_info(root/'annotation/info.txt')['workspace_role'],'annotation')
            with self.assertRaises(FileExistsError):AnnotationWorkspace.initialize(root/'annotation',raw=raw)
            with self.assertRaises(ValueError):AnnotationWorkspace.initialize(root/'datasets/nested',dataset=root/'datasets')
            with self.assertRaises(ValueError):AnnotationWorkspace(root/'datasets')

    def test_sparse_extraction_in_place_labels_and_combined_selected_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);final,workspace,profile=setup(root)
            self.assertFalse(list(final.rglob('*.png')))
            self.assertFalse(list(final.rglob('masks')))
            initial=sha256(final/'samples.txt')
            builder=AnnotationBuilder(workspace.root);key=builder.workspace.keys()[0]
            camera=key[2];images=builder.workspace.images(key)
            self.assertEqual([p.stem for p in images],['f000000','f000002'])
            report=builder.generate_cameras(key[0],workspace.root,cameras=[camera],profiles={camera:profile},
                                             estimate=False,workers=2,limit=1)
            self.assertEqual(report['succeeded'],1)
            label=images[0].parent.parent/'masks/f000000.json'
            self.assertTrue(label.is_file())
            self.assertFalse((workspace.root/'dataset').exists())
            self.assertFalse((workspace.root/'package.txt').exists())
            before=sha256(label)
            with self.assertRaises(FileExistsError):
                builder.generate_cameras(key[0],workspace.root,cameras=[camera],profiles={camera:profile},estimate=False)
            self.assertEqual(sha256(label),before)
            delivery=root/'delivery'
            result=workspace.export(delivery,sequences=[key[0]],sensor='visible',cameras=[camera])
            self.assertEqual((result['streams'],result['images'],result['labels'],result['unlabeled_images']),(1,2,1,1))
            self.assertEqual({r['path'].split('/')[3] for r in read_table(delivery/'files.txt')},{camera})
            self.assertEqual(read_info(delivery/'package.txt')['kind'],'annotation')
            self.assertFalse(list(final.rglob('*.png')))
            import_package(final,delivery)
            self.assertEqual(import_package(final,delivery)['copied'],0)
            self.assertEqual(sha256(final/'samples.txt'),initial)
            self.assertEqual(len(CameraDataset(final)),2)
            ds=SegmentationDataset(final,split=None,sequences=[key[0]],allowed_label_statuses=['draft'],labeled_only=True)
            self.assertEqual(len(ds),1)
            self.assertEqual(tuple(ds[0]['mask'].shape),(48,64))
            with self.assertRaisesRegex(ValueError,'label status'):
                SegmentationDataset(final,split=None,sequences=[key[0]],labeled_only=True)
            # A manually edited target label rejects the whole package before
            # copying any other missing image, rather than overwriting edits.
            target=final/label.relative_to(workspace.root)
            data=json.loads(target.read_text(encoding='utf-8'))
            data['shapes'].append(dict(label='other',shape_type='rectangle',points=[[1,1],[5,5]]))
            target.write_text(json.dumps(data),encoding='utf-8')
            missing=final/images[1].relative_to(workspace.root);missing.unlink()
            with self.assertRaises(FileExistsError):import_package(final,delivery)
            self.assertFalse(missing.exists())

    def test_export_cancel_tampering_and_lock_do_not_publish_partial_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);_,workspace,_=setup(root)
            before={p:sha256(p) for p in workspace.root.rglob('*') if p.is_file()}
            cancel=threading.Event()
            result=workspace.export(root/'cancelled',cancel=cancel,progress=lambda *_:cancel.set())
            self.assertEqual(result['status'],'cancelled')
            self.assertFalse((root/'cancelled').exists())
            self.assertFalse(list(root.glob('.north16_export_*')))
            self.assertEqual(before,{p:sha256(p) for p in workspace.root.rglob('*') if p.is_file()})
            builder=AnnotationBuilder(workspace.root)
            with builder._package(workspace.root):
                with self.assertRaises(FileExistsError):workspace.export(root/'locked')
            self.assertFalse((root/'locked').exists())
            # Edit a file already copied; final source snapshot check must catch it.
            changed=[]
            def mutate(done,total,name):
                if not changed:
                    path=workspace.root/name
                    with path.open('ab') as handle:handle.write(b'\n# changed\n')
                    changed.append(path)
            with self.assertRaisesRegex(ValueError,'发生变化'):
                workspace.export(root/'tampered',progress=mutate)
            self.assertFalse((root/'tampered').exists())
            self.assertFalse((workspace.root/'.north16_build.lock').exists())

    def test_import_checks_manifest_and_source_identity_before_copying(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);final,workspace,_=setup(root)
            package=root/'delivery';workspace.export(package)
            source=next((package/'dataset').rglob('*.png'))
            source.write_bytes(source.read_bytes()+b'changed')
            with self.assertRaisesRegex(ValueError,'校验'):import_package(final,package)
            self.assertFalse(list(final.rglob('*.png')))
            # An independently registered video is not an interchangeable target.
            other=root/'other_raw';shutil.copytree(root/'raw',other)
            video=next(other.rglob('*.mp4'));video.write_bytes(video.read_bytes()+b'new_source')
            DatasetInitializer().initialize(other,root/'other_final')
            clean=root/'clean';workspace.export(clean)
            with self.assertRaisesRegex(ValueError,'来源'):import_package(root/'other_final',clean)
            self.assertFalse(list((root/'other_final').rglob('*.png')))

    def test_cli_dry_run_and_in_place_generate_then_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);final,workspace,profile=setup(root)
            before={p:sha256(p) for p in workspace.root.rglob('*') if p.is_file()}
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                main(['annotation','extract','--root',str(workspace.root),'--interval','1','--dry-run',
                      '--ffmpeg',FFMPEG,'--ffprobe',FFPROBE])
            preflight=json.loads(stdout.getvalue())
            self.assertIn('free_gib',preflight)
            self.assertFalse(preflight['decoding_performed'])
            self.assertEqual(before,{p:sha256(p) for p in workspace.root.rglob('*') if p.is_file()})
            builder=AnnotationBuilder(workspace.root);key=builder.workspace.keys()[0]
            profile_path=root/'profile.json';profile_path.write_text(json.dumps(profile),encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()):
                main(['segmentation','generate','--root',str(workspace.root),'--sequence',key[0],
                      '--camera',key[2],'--profile',str(profile_path),'--limit','1'])
                main(['annotation','export','--root',str(workspace.root),'--cameras',key[2],
                      '--sensor','visible','--output',str(root/'delivery')])
                main(['import-package','--root',str(final),'--package',str(root/'delivery')])
            self.assertEqual(len(list(final.rglob('masks/*.json'))),1)


class AnnotationGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_gui_saves_locally_and_exports_only_checked_with_images(self):
        from north16.gui.window import Window
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);final,workspace,profile=setup(root)
            w=Window(workspace.root);seq=w.stream_key[0];camera=w.stream_key[2]
            self.assertTrue(w.annotation_mode())
            self.assertEqual(Path(w.output_field.text()),workspace.root)
            self.assertFalse(w.output_button.isEnabled())
            self.assertIn('图片',w.export_button.text())
            w.apply_profile(profile)
            w.overview.set_selection({camera})
            jobs=[];w.start=lambda fn,cb,label:jobs.append((fn,cb))
            w.run_camera_batch()
            self.assertEqual(len(jobs),1)
            result=jobs[-1][0](threading.Event(),lambda *_:None);jobs[-1][1](result)
            self.assertEqual(result['succeeded'],2)
            self.assertEqual(len(list(workspace.root.rglob('masks/*.json'))),2)
            self.assertFalse(list(final.rglob('*.png')))
            with patch('north16.gui.window.QFileDialog.getExistingDirectory',return_value=str(root)):
                w.run_export()
            result=jobs[-1][0](threading.Event(),lambda *_:None);jobs[-1][1](result)
            self.assertEqual((result['images'],result['labels']),(2,2))
            self.assertEqual(Path(w.output_field.text()),workspace.root)
            self.assertEqual({r['path'].split('/')[3] for r in read_table(w.last_output/'files.txt')},{camera})
            w.busy(True);w.busy(False)
            self.assertFalse(w.output_button.isEnabled())
            w.sensor_combo.setCurrentIndex(w.sensor_combo.findData('infrared'))
            self.assertTrue(w.export_button.isEnabled())
            self.assertFalse(w.parallel_button.isEnabled())
            with patch('north16.gui.window.QFileDialog.getExistingDirectory',return_value=str(root)):
                w.run_export()
            result=jobs[-1][0](threading.Event(),lambda *_:None);jobs[-1][1](result)
            self.assertEqual((result['images'],result['labels'],result['unlabeled_images']),(2,0,2))
            self.assertTrue(all('/infrared/' in r['path'] for r in read_table(w.last_output/'files.txt')))
            w.close()
