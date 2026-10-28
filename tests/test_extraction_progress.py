"""Live decoding events must preserve pixels/PTS and finish after publication."""
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from north16.camera import CameraBuilder
from north16.camera.builder import main
from north16.camera.progress import ExtractionProgress
from north16.common.files import read_table,sha256
from north16.layout import DatasetInitializer
from north16.preprocess.decoder import run_decoder
from test_build import FFMPEG,FFPROBE
from test_camera_sampling import raw_video


class ExtractionProgressTests(unittest.TestCase):
    def test_decoder_reports_live_before_process_finishes_and_keeps_partial_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);marker=root/'finished'
            script=("import sys,time,pathlib; "
                    "sys.stderr.write('[showinfo@source @ x] n: 0 pts: 0'); sys.stderr.flush(); time.sleep(.3); "
                    "sys.stderr.write(' pts_time:0\\n'); sys.stderr.flush(); time.sleep(.5); "
                    "pathlib.Path(sys.argv[1]).write_text('done')")
            events=[]
            def update(event):
                self.assertFalse(marker.exists(),'Progress must arrive while decoding is still running')
                events.append(event)
            self.assertEqual(run_decoder([sys.executable,'-c',script,str(marker)],root/'decode.log',
                                         sampled=True,progress=update),0)
            self.assertEqual(events,[dict(phase='decode',done=1,selected=0)])
            self.assertTrue(marker.exists())

    def test_real_sparse_progress_counts_source_frames_and_publishes_before_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=raw_video(root)
            for name in ('plain','progress'):DatasetInitializer().initialize(raw,root/name)
            CameraBuilder(root/'plain').extract(interval=.75,ffmpeg=FFMPEG,ffprobe=FFPROBE)
            events=[]
            def update(event):
                events.append(event)
                if event['phase']=='done':
                    self.assertTrue(list((root/'progress').glob('sequences/*/*/*/frames.txt')))
            result=CameraBuilder(root/'progress').extract(interval=.75,ffmpeg=FFMPEG,ffprobe=FFPROBE,progress=update)
            self.assertEqual(result['images'],3)
            decode=[e for e in events if e['phase']=='decode']
            self.assertTrue(decode)
            self.assertEqual((decode[-1]['done'],decode[-1]['selected']),(8,3))
            self.assertEqual(decode[-1]['total'],8)
            self.assertEqual(events[0]['phase'],'preflight')
            self.assertEqual(events[-1]['phase'],'done')
            self.assertEqual([e['done'] for e in events if e['phase']=='verify'],[0,1,2,3])
            for name in ('frames.txt','images/f000003.png','meta/f000003.txt'):
                prefix=Path('sequences/20260902_044232/visible/front_01')
                self.assertEqual(sha256(root/'plain'/prefix/name),sha256(root/'progress'/prefix/name))
            events.clear()
            CameraBuilder(root/'progress').extract(interval=.75,ffmpeg=FFMPEG,ffprobe=FFPROBE,progress=events.append)
            self.assertFalse(any(e['phase']=='decode' for e in events))
            self.assertTrue(next(e for e in events if e['phase']=='stream_done')['reused'])

    def test_cli_progress_is_stderr_and_optional_dry_run_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=raw_video(root)
            for name in ('data','quiet'):DatasetInitializer().initialize(raw,root/name)
            options=['--ffmpeg',FFMPEG,'--ffprobe',FFPROBE]
            with contextlib.redirect_stdout(io.StringIO()) as output,contextlib.redirect_stderr(io.StringIO()) as errors:
                main(['extract','--root',str(root/'data'),*options])
            import json
            self.assertEqual(json.loads(output.getvalue())['images'],8)
            self.assertIn('100%',errors.getvalue())
            self.assertIn('已解码 8 帧',errors.getvalue())
            self.assertIn('front_01',errors.getvalue())
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()) as errors:
                main(['extract','--root',str(root/'quiet'),'--dry-run',*options])
            self.assertEqual(errors.getvalue(),'')
            # annotation extract shares the exact CLI progress implementation.
            from north16.annotation import AnnotationWorkspace
            from north16.annotation.cli import main as annotation_main
            AnnotationWorkspace.initialize(root/'annotation',dataset=root/'quiet')
            with contextlib.redirect_stdout(io.StringIO()) as output,contextlib.redirect_stderr(io.StringIO()) as errors:
                annotation_main(['extract','--root',str(root/'annotation'),'--interval','.75',*options])
            self.assertEqual(json.loads(output.getvalue())['images'],3)
            self.assertIn('100%',errors.getvalue())
            self.assertFalse(list((root/'quiet').rglob('*.png')))
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()) as errors:
                main(['extract','--root',str(root/'quiet'),'--no-progress',*options])
            self.assertEqual(errors.getvalue(),'')

    def test_failure_and_timeout_do_not_report_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=raw_video(root);DatasetInitializer().initialize(raw,root/'data')
            events=[]
            with patch('north16.preprocess.decoder.run_decoder',return_value=1):
                with self.assertRaises(RuntimeError):
                    CameraBuilder(root/'data').extract(ffmpeg=FFMPEG,ffprobe=FFPROBE,progress=events.append)
            self.assertEqual(events[-1]['phase'],'failed')
            self.assertFalse(any(e['phase']=='done' for e in events))
            self.assertFalse((root/'data/.north16_build.lock').exists())
            self.assertFalse(list((root/'data').glob('sequences/*/*/*/frames.txt')))
            command=[sys.executable,'-c','import time; time.sleep(5)']
            with self.assertRaises(subprocess.TimeoutExpired):
                run_decoder(command,root/'timeout.log',progress=events.append,timeout=.1)

    def test_renderer_unknown_totals_and_terminal_overwrite(self):
        output=io.StringIO();progress=ExtractionProgress(output)
        scope=dict(stream_index=1,streams=2,sequence='seq',sensor='visible',camera='front_01')
        progress(dict(scope,phase='decode',done=4,selected=2))
        self.assertIn('已解码 4 帧',output.getvalue())
        self.assertNotIn('%',output.getvalue())
        terminal=io.StringIO();terminal.isatty=lambda:True
        progress=ExtractionProgress(terminal)
        progress(dict(scope,phase='decode',done=100,total=100,selected=5))
        self.assertIn('99%',terminal.getvalue())
        self.assertNotIn('100%',terminal.getvalue())
        progress(dict(scope,phase='stream_done',images=5))
        progress(dict(phase='done',streams=2,images=10))
        self.assertIn('\r',terminal.getvalue())
        self.assertTrue(terminal.getvalue().endswith('\n'))
        self.assertIn('100%',terminal.getvalue())
