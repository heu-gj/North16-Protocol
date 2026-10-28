"""Actual PTS selection must preserve identities, pixels, reuse and label paths."""
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from north16.annotations.dataset_workspace import DatasetWorkspace
from north16.annotations.profiles import DEFAULT_PROFILE
from north16.camera import CameraBuilder
from north16.camera.sampling import estimated_count, normalize_interval, parse_sampled_log
from north16.common.files import read_info, read_table, sha256, write_info
from north16.datasets import CameraDataset, SegmentationDataset
from north16.layout import DatasetInitializer
from north16.packages import import_package
from north16.preprocess.camera import verify_stream
from north16.segmentation import SegmentationBuilder
from test_build import FFMPEG, FFPROBE


def raw_video(root, *, vfr=False):
    raw = root/'raw'
    folder = raw/'2026_09_02_04_42_32_data/camera/front_visible'
    folder.mkdir(parents=True)
    command = [FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=64x48:rate=4', '-frames:v', '8']
    if vfr:
        command += ['-vf', r'setpts=if(lt(N\,3)\,N\,2*N-2)/(4*TB)', '-fps_mode', 'vfr']
    subprocess.run([*command, '-c:v', 'mpeg4', str(folder/'lens_01.mp4')], check=True)
    return raw


class SamplingTests(unittest.TestCase):
    def test_pts_selection_pixels_resume_package_and_annotation_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=raw_video(root)
            init=DatasetInitializer()
            for name in ('full','sparse','target'):
                init.initialize(raw,root/name)
            full=CameraBuilder(root/'full');sparse=CameraBuilder(root/'sparse')
            full.extract(ffmpeg=FFMPEG,ffprobe=FFPROBE)
            result=sparse.extract(interval=.75,ffmpeg=FFMPEG,ffprobe=FFPROBE)
            self.assertEqual(result['images'],3)
            self.assertEqual(result['frame_selection'],'minimum_pts_interval')
            prefix='sequences/20260902_044232/visible/front_01'
            folder=root/'sparse'/prefix
            rows=read_table(folder/'frames.txt')
            self.assertEqual([Path(r['image']).stem for r in rows],['f000000','f000003','f000006'])
            self.assertEqual([float(r['pts_time']) for r in rows],[0.,.75,1.5])
            info=read_info(folder/'info.txt')
            self.assertEqual((info['source_decoded_frame_count'],info['saved_frame_count']),('8','3'))
            for i,row in enumerate(rows):
                meta=read_info(root/'sparse'/row['meta'])
                self.assertEqual((meta['decoded_frame_index'],meta['saved_frame_index']),(str(i*3),str(i)))
                np.testing.assert_array_equal(np.array(Image.open(root/'sparse'/row['image'])),
                                              np.array(Image.open(root/'full'/row['image'])))
                source=read_info(root/'full'/row['meta'])
                self.assertEqual((meta['pts'],meta['time_base']),(source['pts'],source['time_base']))
            self.assertEqual(sparse.extract(interval=.75,ffmpeg=FFMPEG,ffprobe=FFPROBE)['reused_streams'],1)
            before={p:sha256(p) for p in (root/'sparse').rglob('*') if p.is_file()}
            for interval in (None,1.):
                with self.assertRaisesRegex(ValueError,'conflicting'):
                    sparse.extract(interval=interval,ffmpeg=FFMPEG,ffprobe=FFPROBE)
                self.assertEqual(before,{p:sha256(p) for p in (root/'sparse').rglob('*') if p.is_file()})
            sparse.export(root/'cameras')
            import_package(root/'target',root/'cameras')
            self.assertEqual(len(CameraDataset(root/'target')),3)
            workspace=DatasetWorkspace(root/'target');key=workspace.keys()[0]
            profile=deepcopy(DEFAULT_PROFILE);profile['sea_mode']='ice_only'
            report=SegmentationBuilder(root/'target').generate(key,workspace.images(key),profile,root/'labels')
            self.assertEqual(report['succeeded'],3)
            self.assertEqual(sorted(p.stem for p in (root/'labels/dataset'/prefix/'masks').glob('*.json')),
                             ['f000000','f000003','f000006'])
            import_package(root/'target',root/'labels')
            self.assertEqual(len(SegmentationDataset(root/'target',split=None,sequences=key[0],allowed_label_statuses=['draft'])),3)
            meta_path=folder/'meta/f000003.txt';meta=read_info(meta_path);meta['decoded_frame_index']='1'
            write_info(meta_path,meta)
            with self.assertRaisesRegex(ValueError,'identity'):
                verify_stream(folder,key=info['extraction_key'],source_id=info['source_id'])

    def test_variable_frame_timing_uses_pts_not_assumed_fps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=raw_video(root,vfr=True)
            for name in ('full','sparse'):
                DatasetInitializer().initialize(raw,root/name)
            CameraBuilder(root/'full').extract(ffmpeg=FFMPEG,ffprobe=FFPROBE)
            CameraBuilder(root/'sparse').extract(interval=1,ffmpeg=FFMPEG,ffprobe=FFPROBE)
            full=read_table(next((root/'full').glob('sequences/*/*/*/frames.txt')))
            sparse=read_table(next((root/'sparse').glob('sequences/*/*/*/frames.txt')))
            expected=[];previous=None
            for row in full:
                t=int(row['pts'])*Fraction(row['time_base'])
                if previous is None or t-previous >= 1:
                    expected.append(row['id']);previous=t
            self.assertEqual([r['id'] for r in sparse],expected)
            self.assertLess(len(sparse),len(full))
            # A longer interval still keeps the first available source frame.
            DatasetInitializer().initialize(raw,root/'long')
            report=CameraBuilder(root/'long').extract(interval=100,ffmpeg=FFMPEG,ffprobe=FFPROBE)
            self.assertEqual(report['images'],1)

    def test_invalid_interval_rejected_before_media_work_and_cli_forwards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=raw_video(root);DatasetInitializer().initialize(raw,root/'data')
            builder=CameraBuilder(root/'data')
            for bad in (-1,0,float('nan'),float('inf'),True,'bad'):
                with patch('subprocess.check_output',side_effect=AssertionError('No media work')):
                    with self.assertRaises(ValueError):builder.extract(interval=bad)
            self.assertFalse((root/'data/.north16_build.lock').exists())
            self.assertFalse(list((root/'data').rglob('*.png')))
            from north16.camera.builder import main
            with patch('north16.camera.builder.CameraBuilder') as cls:
                cls.return_value.extract.return_value={}
                main(['extract','--root',str(root/'data'),'--interval','5','--sensor','visible'])
                self.assertEqual(cls.return_value.extract.call_args.kwargs['interval'],5.)
            with patch('north16.camera.builder.CameraBuilder'),self.assertRaises(SystemExit):
                main(['export','--root',str(root/'data'),'--output','x','--interval','5'])
        self.assertEqual(normalize_interval('5'),5.)
        self.assertEqual(estimated_count(dict(nb_frames='300',duration='300'),5),61)
        self.assertEqual(estimated_count(dict(nb_frames='300'),5),300)

    def test_nonzero_pts_are_preserved_and_small_interval_keeps_all_real_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=raw_video(root)
            video=next(raw.rglob('*.mp4')); shifted=video.with_name('shifted.mp4')
            subprocess.run([FFMPEG,'-v','error','-i',str(video),'-vf','setpts=PTS+2/TB',
                            '-fps_mode','passthrough','-c:v','mpeg4',str(shifted)],check=True)
            shifted.replace(video)
            source=json.loads(subprocess.check_output([FFPROBE,'-v','error','-select_streams','v:0',
                              '-show_entries','frame=pts,best_effort_timestamp_time','-of','json',str(video)],text=True))['frames']
            DatasetInitializer().initialize(raw,root/'data')
            report=CameraBuilder(root/'data').extract(interval=.01,ffmpeg=FFMPEG,ffprobe=FFPROBE)
            rows=read_table(next((root/'data').glob('sequences/*/*/*/frames.txt')))
            self.assertEqual(report['images'],len(source))
            self.assertGreaterEqual(float(rows[0]['pts_time']),2.)
            self.assertEqual([int(r['pts']) for r in rows],[r['pts'] for r in source])

    def test_ambiguous_missing_or_backwards_pts_logs_are_rejected(self):
        base='[showinfo@source @ x] config in time_base: 1/10\n[showinfo@selected @ y] config in time_base: 1/10\n'
        def frame(role,n,pts):return f'[showinfo@{role} @ x] n: {n} pts: {pts} pts_time:{pts}\n'
        for content in ('',base+frame('selected',0,0),
                        base+frame('source',0,'NOPTS')+frame('selected',0,'NOPTS'),
                        base+frame('source',0,0)+frame('selected',0,0)+frame('source',1,-1)):
            with self.assertRaises(ValueError):parse_sampled_log(content,1.)


if __name__=='__main__':unittest.main()
