"""Protocol-indexed annotation workspace; no Qt or training dependency."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath
import re
import uuid

import yaml

from north16.common.files import local_path, read_info, read_table, check_size, file_state
from north16.preprocess.index import SAMPLE_COLUMNS
from north16.resources import resource_root


LABELS = dict(sky="0", water="1", ice="2", other="3", ignore="255")


class DatasetWorkspace:
    """Read an existing working dataset, routing drafts by stable observation IDs."""

    def __init__(self, root, *, protocol_config=None):
        self.root = Path(root).resolve(strict=True)
        self.info = read_info(self.root / "info.txt")
        self.protocol = read_info(self.root / "protocol.txt")
        labels = read_info(self.root / "classes.txt")
        if self.info.get("dataset_status") != "working":
            raise ValueError("标注工作台只写入working数据集；冻结版本请先复制为独立工作集")
        if self.protocol.get("schema_version") != "north16_seg_v1":
            raise ValueError("不支持此数据集schema；请选择north16生成的数据集根目录")
        if (self.protocol.get("protocol_id") != self.info.get("protocol_id") or
                self.protocol.get("num_classes") != "4" or self.protocol.get("ignore_index") != "255" or
                any(labels.get(k) != v for k, v in LABELS.items())):
            raise ValueError("protocol/classes/info的类别或协议不一致")
        config = Path(protocol_config) if protocol_config else resource_root().joinpath("configs/protocol.yaml")
        policy = yaml.safe_load(config.read_text(encoding="utf-8"))
        if policy.get("protocol_id") != self.protocol["protocol_id"]:
            raise ValueError("工作台配置与数据集protocol_id不一致")
        self.policy = policy["annotation_workspace"]
        if (self.policy.get("generated_label_status") != "draft" or
                self.policy.get("generated_review_status") != "unreviewed" or
                self.policy.get("filename") != "original_frame_stem"):
            raise ValueError("不支持此标注输出状态或命名规则")
        self.streams = defaultdict(list)
        seen, seen_paths = set(), set()
        self.snapshots = {name: file_state(self.root / name) for name in ("samples.txt", "protocol.txt", "classes.txt", "info.txt")}
        from north16.camera.index import camera_rows
        for row in camera_rows(self.root):
            if not set(SAMPLE_COLUMNS).issubset(row) or not all(row[k] for k in ("id", "sequence", "sensor", "camera", "image", "meta")):
                raise ValueError("samples.txt缺少协议字段或样本身份")
            for key in ("id", "sequence", "camera"):
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", row[key]):
                    raise ValueError(f"不安全的样本字段：{key}")
            if row["sensor"] not in {"visible", "infrared"}:
                raise ValueError("samples.txt包含不支持的模态")
            relative = PurePosixPath(row["image"])
            base = f"sequences/{row['sequence']}/{row['sensor']}/{row['camera']}"
            if row["image"] != f"{base}/images/{relative.stem}.png" or not re.fullmatch(r"f\d+", relative.stem):
                raise ValueError("样本图像路径不符合north16结构")
            if row["meta"] != f"{base}/meta/{relative.stem}.txt":
                raise ValueError("样本元信息路径与图像不匹配")
            if row["id"] in seen or row["image"].casefold() in seen_paths:
                raise ValueError("samples.txt存在重复样本ID或图像路径")
            if row["weather"] not in {"clear", "cloudy_overcast", "fog_precipitation", "unknown"} or row["illumination"] not in {"day", "night", "unknown"}:
                raise ValueError("样本天气/光照字段非法")
            if row["label_status"] not in {"unlabeled", "draft", "reviewed", "adjudicated", "frozen"}:
                raise ValueError("样本标签状态非法")
            seen.add(row["id"]); seen_paths.add(row["image"].casefold())
            self.streams[(row["sequence"], row["sensor"], row["camera"])].append(row)
        if not self.streams:
            raise ValueError("数据集尚无相机图片，请先执行camera extract；初始化不解码视频")
        self.assert_unchanged()

    def assert_unchanged(self):
        if any(file_state(self.root / name) != value for name, value in self.snapshots.items()):
            raise ValueError("数据集索引或协议已变化，请重新打开数据集后再生成")

    def keys(self, sensor="visible"):
        return sorted(key for key in self.streams if sensor is None or key[1] == sensor)

    def images(self, key):
        images = [local_path(self.root, row["image"]) for row in self.streams[key]]
        if any(not p.is_file() for p in images):
            raise FileNotFoundError("索引中的图像不存在；请先检查数据集构建结果")
        return images

    def new_run_id(self):
        return datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]

    def output_path(self, kind, key, run_id):
        if key not in self.streams or not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
            raise ValueError("无效的流或任务ID")
        seq, sensor, camera = key
        relative = self.policy[kind].format(sequence=seq, sensor=sensor, camera=camera, run=run_id)
        path = local_path(self.root, relative)
        if not path.is_relative_to(local_path(self.root, "annotations")):
            raise ValueError("标注输出必须位于annotations目录内")
        return path

    def prepare(self, key, images):
        """Check receipts/metadata and snapshot before creating any output."""
        self.assert_unchanged()
        if key[1] != "visible":
            raise ValueError("当前亮度GrabCut只支持visible，不能直接套用到infrared")
        available = {local_path(self.root, r["image"]): r for r in self.streams[key]}
        images = [Path(p).resolve(strict=True) for p in images]
        if not images or len(images) != len(set(images)) or any(p not in available for p in images):
            raise ValueError("待标注图像必须唯一且属于当前索引流")
        seq, sensor, camera = key
        receipt_path = local_path(self.root, f"sequences/{seq}/{sensor}/{camera}/frames.txt")
        receipts = read_table(receipt_path)
        frames = {r["id"]: r for r in receipts}
        if len(frames) != len(receipts):
            raise ValueError("frames.txt存在重复身份")
        observations = {}
        for image in images:
            row = available[image]
            frame = frames.get(row["id"], {})
            meta = read_info(local_path(self.root, row["meta"]))
            if (frame.get("image") != row["image"] or frame.get("meta") != row["meta"] or
                    meta.get("id") != row["id"] or meta.get("image") != row["image"]):
                raise ValueError(f"帧回执/元信息身份不一致：{image.name}")
            size=check_size(image,frame.get("image_bytes"))
            observations[str(image)] = dict(row, image_sha256="disabled", image_bytes=size, image_state=file_state(image))
        context = dict(dataset_root=str(self.root), protocol_id=self.protocol["protocol_id"],
                       sequence=seq, sensor=sensor, camera=camera, input_snapshots=self.snapshots,
                       frames_state=file_state(receipt_path), file_checksum="none", output_policy=dict(self.policy))
        return observations, context


def run_dataset_job(workspace, key, images, profile, output, *, cancel=None, progress=None, estimation=None):
    from north16.annotations.workspace import run_job
    observations, context = workspace.prepare(key, images)
    # Dataset mode always follows the protocol-prescribed destination.
    output = Path(output).resolve()
    if output != workspace.output_path("drafts", key, output.name):
        raise ValueError("数据集模式输出不符合protocol的drafts目录规则")
    report = run_job(images, profile, output, cancel=cancel, progress=progress,
                     estimation=estimation, observations=observations, context=context)
    from north16.annotations.management import refresh
    refresh(workspace.root)
    return report
