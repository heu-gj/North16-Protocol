"""PyTorch loader for the North16-Seg TXT protocol.

See DATASET.md for the on-disk contract. This loads standardized camera data;
it does not decode raw videos, infer conditions, or certify synchronization.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

import numpy as np
from PIL import Image
import torch
from torch.utils.data import Dataset


LABELS = {"sky": 0, "water": 1, "ice": 2, "other": 3, "ignore": 255}
WEATHER = frozenset({"clear", "cloudy_overcast", "fog_precipitation", "unknown"})
ILLUMINATION = frozenset({"day", "night", "unknown"})
REQUIRED_COLUMNS = (
    "id", "sequence", "sensor", "camera", "image", "mask", "meta",
    "weather", "illumination", "label_status", "group",
)


def read_info(path: str | Path) -> dict[str, str]:
    """Read UTF-8 key=value TXT, rejecting duplicate keys and empty values."""
    result: dict[str, str] = {}
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected key=value")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key or not value or key in result:
            raise ValueError(f"{path}:{line_number}: empty or duplicate field {key!r}")
        result[key] = value
    return result


def _local_file(root: Path, relative: str) -> Path:
    key = PurePosixPath(relative)
    if not relative or "\\" in relative or key.is_absolute() or ".." in key.parts or ":" in relative:
        raise ValueError(f"Expected a relative path within the dataset: {relative!r}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Path escapes dataset root: {relative!r}")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _selection(value: str | Iterable[str] | None, allowed: frozenset[str], name: str) -> frozenset[str] | None:
    if value is None:
        return None
    selected = frozenset([value] if isinstance(value, str) else value)
    if not selected or not selected.issubset(allowed):
        raise ValueError(f"Invalid {name}: {sorted(selected)!r}; allowed: {sorted(allowed)!r}")
    return selected


@dataclass(frozen=True)
class Sample:
    id: str
    sequence: str
    sensor: str
    camera: str
    image: str
    mask: str
    meta: str
    weather: str
    illumination: str
    label_status: str
    group: str


class SegResize:
    """Joint PIL resize; size=(height, width). Masks use nearest neighbor."""

    def __init__(self, size: tuple[int, int]):
        if len(size) != 2 or any(not isinstance(n, int) or isinstance(n, bool) or n <= 0 for n in size):
            raise ValueError("size must be two positive integers (height, width)")
        self.size = size

    def __call__(self, image: Image.Image, mask: Image.Image | None):
        output_size = (self.size[1], self.size[0])
        image = image.resize(output_size, Image.Resampling.BILINEAR)
        if mask is not None:
            mask = mask.resize(output_size, Image.Resampling.NEAREST)
        return image, mask


class North16SegDataset(Dataset):
    """Read a fixed split, then filter by modality and optional conditions.

    By default images become float32 [3,H,W] in [0,1] and masks int64 [H,W].
    infrared_channels=1 explicitly converts IR display images to luminance. No
    normalization, augmentation, weather inference or label remapping is hidden.

    joint_transform must take and return (PIL image, PIL mask or None), applying
    the same geometry to both. require_mask=False never opens ground-truth masks
    and omits the `mask` key, suitable for hidden-label test inference.
    """

    classes = ("sky", "water", "ice", "other")
    ignore_index = 255

    def __init__(
        self,
        root: str | Path,
        split: str | None = "train",
        *,
        sensor: str | Iterable[str] = "visible",
        sequences: str | Iterable[str] | None = None,
        weather: str | Iterable[str] | None = None,
        illumination: str | Iterable[str] | None = None,
        joint_transform: Callable | None = None,
        require_mask: bool = True,
        labeled_only: bool = False,
        infrared_channels: int = 3,
        allowed_label_statuses: Iterable[str] = ("reviewed", "adjudicated", "frozen"),
    ):
        self.root = Path(root).resolve(strict=True)
        if split not in {None, "train", "val", "test"}:
            raise ValueError("split must be train, val, test or None")
        if split is None and sequences is None:
            raise ValueError("Unsplit inspection requires explicit sequences")
        if split is not None and sequences is not None:
            raise ValueError("sequences inspection and benchmark split are mutually exclusive")
        if infrared_channels not in {1, 3}:
            raise ValueError("infrared_channels must be 1 or 3")
        self.split, self.require_mask = split, require_mask
        if labeled_only and not require_mask:
            raise ValueError("labeled_only requires require_mask=True")
        self.infrared_channels, self.joint_transform = infrared_channels, joint_transform
        sensors = _selection(sensor, frozenset({"visible", "infrared"}), "sensor")
        weather_filter = _selection(weather, WEATHER, "weather")
        light_filter = _selection(illumination, ILLUMINATION, "illumination")
        statuses = frozenset([allowed_label_statuses] if isinstance(allowed_label_statuses, str) else allowed_label_statuses)
        if not statuses.issubset({"draft", "reviewed", "adjudicated", "frozen"}):
            raise ValueError("allowed_label_statuses may contain draft/reviewed/adjudicated/frozen")
        if require_mask and not statuses:
            raise ValueError("allowed_label_statuses cannot be empty when masks are required")

        self.protocol = read_info(_local_file(self.root, "protocol.txt"))
        expected = {"schema_version": "north16_seg_v1", "task": "semantic_segmentation",
                    "num_classes": "4", "ignore_index": "255"}
        for key, value in expected.items():
            if self.protocol.get(key) != value:
                raise ValueError(f"Unsupported protocol {key}: {self.protocol.get(key)!r}; expected {value!r}")
        if not self.protocol.get("protocol_id"):
            raise ValueError("protocol.txt must declare protocol_id")
        class_info = read_info(_local_file(self.root, "classes.txt"))
        if any(class_info.get(name) != str(value) for name, value in LABELS.items()):
            raise ValueError(f"classes.txt must declare {LABELS}")

        rows: dict[str, Sample] = {}
        from north16.camera.index import camera_rows
        records = camera_rows(self.root)
        if records:
            columns = list(records[0])
            if len(set(columns)) != len(columns) or not set(REQUIRED_COLUMNS).issubset(columns):
                raise ValueError(f"samples.txt requires unique TSV columns {REQUIRED_COLUMNS}")
            for line_number, row in enumerate(records, 2):
                if None in row or any(row.get(key) is None for key in REQUIRED_COLUMNS):
                    raise ValueError(f"samples.txt:{line_number}: malformed TSV row")
                sample = Sample(**{key: row[key].strip() for key in REQUIRED_COLUMNS})
                if not all((sample.id, sample.sequence, sample.sensor, sample.camera, sample.image, sample.meta, sample.group)):
                    raise ValueError(f"samples.txt:{line_number}: missing identity, image, metadata or group")
                if sample.id in rows:
                    raise ValueError(f"Duplicate sample ID: {sample.id}")
                if sample.sensor not in {"visible", "infrared"}:
                    raise ValueError(f"North16-Seg camera manifest has unsupported sensor: {sample.sensor}")
                if sample.weather not in WEATHER or sample.illumination not in ILLUMINATION:
                    raise ValueError(f"Unresolved/invalid conditions for {sample.id}; expand inherit before indexing")
                if sample.label_status not in {"unlabeled", "draft", "reviewed", "adjudicated", "frozen"}:
                    raise ValueError(f"Invalid label status for {sample.id}: {sample.label_status}")
                rows[sample.id] = sample

        # Validate all declared splits, including cross-modal groups, before filtering.
        declared: dict[str, list[str]] = {}
        sample_owner: dict[str, str] = {}
        group_owner: dict[str, str] = {}
        image_owner: dict[Path, str] = {}
        for split_name in ("train", "val", "test"):
            split_path = self.root / "splits" / f"{split_name}.txt"
            if not split_path.exists() and split_name != split:
                continue
            ids = [s.strip() for s in _local_file(self.root, f"splits/{split_name}.txt").read_text(encoding="utf-8-sig").splitlines()
                   if s.strip() and not s.lstrip().startswith("#")]
            for sample_id in ids:
                if sample_id not in rows:
                    raise ValueError(f"Unknown sample ID in {split_name}: {sample_id}")
                if sample_id in sample_owner:
                    raise ValueError(f"Repeated sample ID across/in splits: {sample_id}")
                sample_owner[sample_id] = split_name
                image_path = _local_file(self.root, rows[sample_id].image)
                if image_path in image_owner and image_owner[image_path] != split_name:
                    raise ValueError(f"Image crosses splits under different IDs: {rows[sample_id].image}")
                image_owner[image_path] = split_name
                group = rows[sample_id].group
                if group == "unknown":
                    raise ValueError(f"Split sample {sample_id} needs a verified group, not unknown")
                if group in group_owner and group_owner[group] != split_name:
                    raise ValueError(f"Group crosses splits: {group}")
                group_owner[group] = split_name
            declared[split_name] = ids

        if split is None:
            requested = frozenset([sequences] if isinstance(sequences, str) else sequences)
            available = {sample.sequence for sample in rows.values()}
            if not requested or not requested.issubset(available):
                raise ValueError("Unknown or empty sequences selection")
            chosen_ids = [sample.id for sample in rows.values() if sample.sequence in requested]
        else:
            chosen_ids = declared[split]
        selected = []
        for sample_id in chosen_ids:
            sample = rows[sample_id]
            if sample.sensor not in sensors:
                continue
            if weather_filter is not None and sample.weather not in weather_filter:
                continue
            if light_filter is not None and sample.illumination not in light_filter:
                continue
            _local_file(self.root, sample.image)
            _local_file(self.root, sample.meta)
            if require_mask:
                # Copied JSON labels are authoritative without rewriting samples.txt.
                image_path = _local_file(self.root, sample.image)
                from north16.layout.paths import label_path
                json_path = self.root / label_path(sample.image)
                if labeled_only and not sample.mask and not json_path.is_file():
                    continue
                if json_path.is_file():
                    from north16.segmentation.labels import validate_label
                    data, _ = validate_label(json_path, image_path, root=self.root, expected_id=sample.id, rasterize=False)
                    if data["north16"].get("protocol_id") != self.protocol["protocol_id"]:
                        raise ValueError("JSON标注protocol_id不匹配")
                    sample = replace(sample, mask=json_path.relative_to(self.root).as_posix(),
                                     label_status=data["north16"]["label_status"])
                if sample.label_status not in statuses:
                    raise ValueError(f"{sample.id}: label status {sample.label_status!r} is not accepted")
                _local_file(self.root, sample.mask)
            selected.append(sample)
        if not selected:
            raise ValueError(f"No samples for split={split}, sensor={sensor}, weather={weather}, illumination={illumination}")
        self.samples = tuple(selected)

    def __len__(self) -> int:
        return len(self.samples)

    @staticmethod
    def _check_mask(mask: Image.Image, sample_id: str) -> np.ndarray:
        if mask.mode not in {"L", "P"}:
            raise ValueError(f"{sample_id}: mask must be an 8-bit label PNG (L or P), got {mask.mode}")
        values = np.array(mask, dtype=np.uint8)
        invalid = set(np.unique(values).tolist()) - set(LABELS.values())
        if invalid:
            raise ValueError(f"{sample_id}: invalid mask IDs {sorted(invalid)}")
        return values

    def __getitem__(self, index: int) -> dict:
        sample = self.samples[index]
        with Image.open(_local_file(self.root, sample.image)) as source:
            if source.mode not in {"RGB", "L"}:
                raise ValueError(f"{sample.id}: expected standardized 8-bit RGB/L camera image, got {source.mode}")
            mode = "L" if sample.sensor == "infrared" and self.infrared_channels == 1 else "RGB"
            image = source.convert(mode)
        original_size = (image.height, image.width)
        mask = None
        if self.require_mask:
            mask_path = _local_file(self.root, sample.mask)
            if mask_path.suffix.lower() == ".json":
                from north16.segmentation.labels import validate_label
                data, values = validate_label(mask_path, _local_file(self.root, sample.image), root=self.root, expected_id=sample.id)
                if data["north16"]["label_status"] != sample.label_status:
                    raise ValueError("Dataset读取期间标签状态变化，请重新加载")
                mask = Image.fromarray(values)
            else:
                with Image.open(mask_path) as source:
                    if source.format != "PNG":
                        raise ValueError(f"{sample.id}: mask must be stored as PNG")
                    mask = source.copy()
            self._check_mask(mask, sample.id)
            if mask.size != image.size:
                raise ValueError(f"{sample.id}: image and mask sizes differ")
        if self.joint_transform is not None:
            image, mask = self.joint_transform(image, mask)
            if not isinstance(image, Image.Image) or image.mode not in {"RGB", "L"}:
                raise TypeError("joint_transform must return a PIL RGB/L image")
            if self.require_mask and (not isinstance(mask, Image.Image) or mask.size != image.size):
                raise ValueError("joint_transform must return matching PIL image/mask geometry")
        pixels = np.array(image, dtype=np.float32)
        if pixels.ndim == 2:
            pixels = pixels[:, :, None]
        image_tensor = torch.from_numpy(np.ascontiguousarray(pixels.transpose(2, 0, 1))).div_(255.0)
        meta = read_info(_local_file(self.root, sample.meta))
        if meta.get("id") != sample.id:
            raise ValueError(f"{sample.id}: metadata ID does not match samples.txt")
        result = {
            "image": image_tensor, "id": sample.id, "sequence": sample.sequence,
            "sensor": sample.sensor, "camera": sample.camera, "group": sample.group,
            "weather": sample.weather, "illumination": sample.illumination,
            "capture_time_utc": meta.get("capture_time_utc", "unknown"),
            "meta_path": sample.meta, "protocol_id": self.protocol["protocol_id"],
            "original_size": torch.tensor(original_size, dtype=torch.int64),
        }
        if self.require_mask:
            result["mask"] = torch.from_numpy(self._check_mask(mask, sample.id).astype(np.int64))
        return result
