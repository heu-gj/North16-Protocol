"""Meaningful loader checks on synthetic assets; no raw dataset is modified."""
import csv
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image
import torch
from torch.utils.data import DataLoader

from north16.datasets.segmentation import LABELS, REQUIRED_COLUMNS, North16SegDataset, SegResize


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="north16_dataset_test_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "protocol.txt").write_text(
            "schema_version=north16_seg_v1\nprotocol_id=north16-seg-v0.1-draft\n"
            "task=semantic_segmentation\nnum_classes=4\nignore_index=255\n", encoding="utf-8")
        (self.root / "classes.txt").write_text("\n".join(f"{k}={v}" for k, v in LABELS.items()) + "\n", encoding="utf-8")
        (self.root / "splits").mkdir()
        self.rows = []
        self.add_sample("visible_train", "visible", "s1", "g1", "clear", "day")
        self.add_sample("infrared_train", "infrared", "s1", "g1", "fog_precipitation", "night")
        self.add_sample("visible_test", "visible", "s2", "g2", "unknown", "unknown", labeled=False)
        (self.root / "splits/train.txt").write_text("visible_train\ninfrared_train\n", encoding="utf-8")
        (self.root / "splits/val.txt").write_text("", encoding="utf-8")
        (self.root / "splits/test.txt").write_text("visible_test\n", encoding="utf-8")
        self.write_manifest()

    def add_sample(self, sample_id, sensor, sequence, group, weather, light, labeled=True):
        folder = self.root / "sequences" / sequence / sensor / "front_01"
        for name in ("images", "masks", "meta"):
            (folder / name).mkdir(parents=True, exist_ok=True)
        image = np.arange(72, dtype=np.uint8).reshape(4, 6, 3)
        Image.fromarray(image).save(folder / "images/f000000.png")
        if labeled:
            labels = np.array([[0, 1, 2, 3, 255, 2]] * 4, dtype=np.uint8)
            Image.fromarray(labels).save(folder / "masks/f000000.png")
        (folder / "meta/f000000.txt").write_text(f"id={sample_id}\ncapture_time_utc=unknown\n", encoding="utf-8")
        self.rows.append({
            "id": sample_id, "sequence": sequence, "sensor": sensor, "camera": "front_01",
            "image": (folder / "images/f000000.png").relative_to(self.root).as_posix(),
            "mask": (folder / "masks/f000000.png").relative_to(self.root).as_posix() if labeled else "",
            "meta": (folder / "meta/f000000.txt").relative_to(self.root).as_posix(),
            "weather": weather, "illumination": light,
            "label_status": "reviewed" if labeled else "unlabeled", "group": group,
        })

    def write_manifest(self):
        with (self.root / "samples.txt").open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(self.rows)

    def test_labels_shapes_and_ignore_survive_resize(self):
        ds = North16SegDataset(self.root, joint_transform=SegResize((8, 12)))
        item = ds[0]
        self.assertEqual(item["image"].shape, (3, 8, 12))
        self.assertEqual(item["mask"].shape, (8, 12))
        self.assertEqual(item["image"].dtype, torch.float32)
        self.assertEqual(item["mask"].dtype, torch.int64)
        self.assertEqual(set(torch.unique(item["mask"]).tolist()), {0, 1, 2, 3, 255})
        self.assertEqual(item["original_size"].tolist(), [4, 6])
        batch = next(iter(DataLoader(ds, batch_size=1)))
        self.assertEqual(batch["image"].shape, (1, 3, 8, 12))

    def test_filter_and_explicit_infrared_channels(self):
        ds = North16SegDataset(self.root, sensor="infrared", weather="fog_precipitation", illumination="night", infrared_channels=1)
        self.assertEqual(len(ds), 1)
        self.assertEqual(ds[0]["id"], "infrared_train")
        self.assertEqual(ds[0]["image"].shape, (1, 4, 6))

    def test_no_labels_in_inference_and_missing_labels_fail_training(self):
        item = North16SegDataset(self.root, split="test", require_mask=False)[0]
        self.assertNotIn("mask", item)
        with self.assertRaisesRegex(ValueError, "label status"):
            North16SegDataset(self.root, split="test")

    def test_same_frame_names_stay_bound_to_correct_sequence(self):
        train = North16SegDataset(self.root)[0]
        test = North16SegDataset(self.root, split="test", require_mask=False)[0]
        self.assertNotEqual(train["sequence"], test["sequence"])
        self.assertNotEqual(train["meta_path"], test["meta_path"])

    def test_group_leakage_across_modalities_is_rejected(self):
        self.rows[2]["group"] = "g1"
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "Group crosses splits"):
            North16SegDataset(self.root)

    def test_same_image_under_different_ids_cannot_cross_splits(self):
        self.rows[2]["image"] = self.rows[0]["image"]
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "Image crosses splits"):
            North16SegDataset(self.root)

    def test_invalid_mask_is_rejected(self):
        Image.fromarray(np.full((4, 6), 7, dtype=np.uint8)).save(self.root / self.rows[0]["mask"])
        with self.assertRaisesRegex(ValueError, "invalid mask IDs"):
            North16SegDataset(self.root)[0]

    def test_original_mask_size_mismatch_is_rejected(self):
        Image.fromarray(np.zeros((2, 3), dtype=np.uint8)).save(self.root / self.rows[0]["mask"])
        with self.assertRaisesRegex(ValueError, "sizes differ"):
            North16SegDataset(self.root)[0]

    def test_unknown_split_id_is_rejected_before_filtering(self):
        (self.root / "splits/test.txt").write_text("not_in_manifest\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unknown sample ID"):
            North16SegDataset(self.root, sensor="infrared")

    def test_duplicate_ids_are_rejected(self):
        self.rows.append(self.rows[0].copy())
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "Duplicate sample ID"):
            North16SegDataset(self.root)

    def test_escape_paths_are_rejected(self):
        self.rows[0]["image"] = "../outside.png"
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "relative path"):
            North16SegDataset(self.root)

    def test_unresolved_attributes_and_metadata_mismatch_are_rejected(self):
        self.rows[0]["weather"] = "inherit"
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "Unresolved/invalid conditions"):
            North16SegDataset(self.root)
        self.rows[0]["weather"] = "clear"
        self.write_manifest()
        (self.root / self.rows[0]["meta"]).write_text("id=wrong\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "metadata ID"):
            North16SegDataset(self.root)[0]

    def test_incompatible_protocol_is_rejected(self):
        protocol = self.root / "protocol.txt"
        protocol.write_text(protocol.read_text(encoding="utf-8").replace("num_classes=4", "num_classes=2"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unsupported protocol"):
            North16SegDataset(self.root)


if __name__ == "__main__":
    unittest.main()
