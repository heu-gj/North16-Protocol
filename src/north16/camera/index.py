"""Read observation receipts in modular datasets; legacy snapshots stay compatible."""
from pathlib import Path
import yaml

from north16.common.files import read_info, read_table
from north16.resources import resource_root


def camera_rows(root):
    root = Path(root)
    if not (root/"info.txt").is_file() or read_info(root/"info.txt").get("camera_index") != "frames":
        return read_table(root/"samples.txt")
    from north16.preprocess.index import collect_index
    protocol = yaml.safe_load(resource_root().joinpath("configs/protocol.yaml").read_text(encoding="utf-8"))
    return collect_index(root, protocol)
