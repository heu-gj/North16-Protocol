"""Actual FFmpeg integration on synthetic media, including safe resume."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml
import numpy as np
from PIL import Image

from north16.common.files import local_path, read_info, read_table, sha256, write_info
from north16.pipeline.build import build, validate_contract
from north16.datasets import North16SegDataset, SegResize
from north16.validation.pilot import validate

FFMPEG = shutil.which("ffmpeg") or "D:/Software/ffmpeg/bin/ffmpeg.exe"
FFPROBE = shutil.which("ffprobe") or "D:/Software/ffmpeg/bin/ffprobe.exe"
REFERENCE = Path(__file__).resolve().parents[1]


class BuildIntegration(unittest.TestCase):
    def test_build_resume_conflict_and_unsplit_reader(self):
        with tempfile.TemporaryDirectory(prefix="north16_integration_") as name:
            root = Path(name)
            project = root / "protocol"
            shutil.copytree(REFERENCE / "configs", project / "configs")
            shutil.copytree(REFERENCE / "templates", project / "templates")
            raw = root / "raw"
            seg = raw / "2026_09_02_04_42_32_data"
            for sensor in ("visible", "infrared"):
                folder = seg / "camera" / ("front_" + sensor)
                folder.mkdir(parents=True)
                subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=64x48:rate=2",
                                "-frames:v", "4", "-c:v", "mpeg4", str(folder / "lens_01.mp4")], check=True)
            (seg / "time.txt").write_text("2026_09_02_04_42_32\n2026_09_02_04_42_32\n2026_09_02_04_42_35\n", encoding="utf-8")
            radar = seg / "ice_radar"
            radar.mkdir()
            Image.fromarray(np.zeros((16, 16), dtype=np.uint8)).save(radar / "scan_a.tif")
            shutil.copyfile(radar / "scan_a.tif", radar / "scan_b.tif")
            (radar / "scan_a.kml").write_bytes(b'<?xml version="1.0" encoding="UTF-8"?><kml>\xff</kml>')
            (radar / "ice_radar_index.txt").write_text(
                'TIME,STATUS,ICE_RADAR_FILE\nraw_a,SAVED_FILE,scan_a\nraw_b,SAVED_FILE,scan_b\n', encoding="utf-8")
            nav = seg / "navigation_radar"
            nav.mkdir()
            (nav / "navigation_radar.txt").write_text('TIME:raw_time\nGGA:unknown_units\n', encoding="utf-8")
            out = root / "datasets"
            cfg = yaml.safe_load((project / "configs/pilot.yaml").read_text(encoding="utf-8"))
            cfg["inputs"][0].update(path=str(raw), segments=[seg.name])
            cfg["dataset"]["output_root"] = str(out)
            path = project / "configs/pilot.yaml"
            path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
            result = build(path, FFMPEG, FFPROBE)
            self.assertEqual(result["images"], 8)
            self.assertEqual(result["auxiliary"][0]["content_assets"], 1)
            self.assertEqual(result["auxiliary"][0]["invalid_kml"], 1)
            self.assertEqual(result["auxiliary"][0]["unmatched_receptions"], 0)
            self.assertEqual(validate(out)["stream_count"], 2)
            rows = read_table(out / "samples.txt")
            self.assertEqual({r["mask"] for r in rows}, {""})
            meta_path = local_path(out, rows[0]["meta"])
            meta = read_info(meta_path)
            self.assertEqual(meta["capture_time_utc"], "unknown")
            self.assertEqual(meta["source_log_row_index"], "unknown")
            self.assertEqual(float(meta["pts_time_s"]), 0.0)
            times = [float(read_info(local_path(out, r["meta"]))["pts_time_s"]) for r in rows[:4]]
            self.assertEqual(times, [0.0, 0.5, 1.0, 1.5])
            meta.update(weather="clear", weather_status="reviewed", weather_evidence_id="test_review")
            write_info(meta_path, meta)
            before = sha256(local_path(out, rows[0]["image"]))
            result = build(path, FFMPEG, FFPROBE)
            self.assertEqual(result["reused_streams"], 2)
            self.assertEqual(read_info(meta_path)["weather"], "clear")
            self.assertEqual(before, sha256(local_path(out, rows[0]["image"])))
            ds = North16SegDataset(out, split=None, sequences="20260902_044232", require_mask=False,
                                  sensor=["visible", "infrared"], joint_transform=SegResize((24, 32)))
            self.assertEqual(len(ds), 8)
            self.assertEqual(tuple(ds[0]["image"].shape), (3, 24, 32))
            self.assertNotIn("mask", ds[0])
            # A real raw-video build must open directly in the annotation workspace.
            from north16.annotations.dataset_workspace import DatasetWorkspace
            workspace = DatasetWorkspace(out)
            self.assertEqual(len(workspace.keys()), 1)
            key = workspace.keys()[0]
            observations, context = workspace.prepare(key, workspace.images(key)[:1])
            self.assertEqual(len(observations), 1)
            self.assertEqual(context['sequence'], '20260902_044232')
            with self.assertRaisesRegex(ValueError, "explicit sequences"):
                North16SegDataset(out, split=None, require_mask=False)
            image = local_path(out, rows[0]["image"])
            image.write_bytes(image.read_bytes() + b"tampered")
            with self.assertRaisesRegex(RuntimeError, "streams failed"):
                build(path, FFMPEG, FFPROBE)
            self.assertFalse((out / "splits").exists())
            self.assertFalse((out / ".north16_build.lock").exists())

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            for relative in ("../escape", "C:/escape", "/escape", "a\\b"):
                with self.assertRaises(ValueError):
                    local_path(Path(name), relative)

    def test_protocol_drift_rejected_before_processing(self):
        protocol = yaml.safe_load((REFERENCE / "configs/protocol.yaml").read_text(encoding="utf-8"))
        config = yaml.safe_load((REFERENCE / "configs/pilot.yaml").read_text(encoding="utf-8"))
        protocol["annotation"]["labels"]["ice"] = 9
        with self.assertRaisesRegex(ValueError, "class map"):
            validate_contract(config, protocol, REFERENCE / "templates/txt")


if __name__ == "__main__":
    unittest.main()
