"""Portable package entry points, resource initialization, and edit protection."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from north16 import cli
from north16.resources import initialize


class PackageTests(unittest.TestCase):
    def test_new_batch_keeps_unknowns_and_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            project = initialize(root / "batch", root / "raw", root / "datasets", ["segment_a"])
            cfg = yaml.safe_load((project / "configs/import.yaml").read_text(encoding="utf-8"))
            self.assertEqual(cfg["inputs"][0]["segments"], ["segment_a"])
            self.assertIsNone(cfg["inputs"][0]["verified_timezone"])
            self.assertEqual(cfg["inputs"][0]["recording_date_label"], "unknown")
            self.assertEqual(cfg["dataset"]["output_root"], (root / "datasets").as_posix())
            self.assertTrue((project / "templates/txt/classes.txt").is_file())
            self.assertTrue((project / "docs/PROTOCOL.md").is_file())
            self.assertFalse((root / "datasets").exists())
            before = (project / "configs/import.yaml").read_bytes()
            with self.assertRaises(FileExistsError):
                initialize(project, root / "raw", root / "datasets", ["other"])
            self.assertEqual((project / "configs/import.yaml").read_bytes(), before)

    def test_invalid_scopes_have_no_output(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for segments in ([], ["../escape"], ["a", "a"], ["a/b"]):
                with self.assertRaises(ValueError):
                    initialize(root / "batch", root / "raw", root / "datasets", segments)
                self.assertFalse((root / "batch").exists())
            with self.assertRaises(ValueError):
                initialize(root / "batch", root / "raw", root / "raw/output", ["a"])

    def test_cli_forwards_flags_without_reimplementing_business_logic(self):
        with patch("north16.cli.import_module") as module:
            cli.main(["export-labels", "--root", "data", "--output", "edits"])
            module.assert_called_once_with("north16.annotations.xanylabeling")
            module.return_value.main.assert_called_once_with(["export", "--root", "data", "--output", "edits"])
        with patch("north16.cli.import_module") as module:
            cli.main(["build", "--help"])
            module.return_value.main.assert_called_once_with(["--help"])

    def test_root_help_does_not_load_torch_or_opencv(self):
        with patch("north16.cli.import_module") as module, contextlib.redirect_stdout(io.StringIO()):
            cli.main([])
            module.assert_not_called()


if __name__ == "__main__":
    unittest.main()
