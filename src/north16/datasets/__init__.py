"""Camera segmentation readers; mixed sensors are unpaired samples."""
from north16.datasets.segmentation import North16SegDataset, SegResize
from north16.datasets.camera import CameraDataset
SegmentationDataset = North16SegDataset

__all__ = ["CameraDataset", "North16SegDataset", "SegmentationDataset", "SegResize"]
