"""Unlabeled camera observations; never decode videos during loading."""
from north16.camera.index import camera_rows
from .segmentation import North16SegDataset


class CameraDataset(North16SegDataset):
    def __init__(self, root, *, sequences=None, sensor=("visible", "infrared"), **kwargs):
        if sequences is None:
            sequences=sorted({row["sequence"] for row in camera_rows(root)})
        super().__init__(root,split=None,sequences=sequences,sensor=sensor,require_mask=False,**kwargs)
