"""Inventory and reversible archival of legacy annotation workspaces."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import uuid

from north16.common.files import read_info, write_table

KINDS = ("drafts", "projects", "corrected", "profiles", "archive")
LEGACY = ("demo_camera04", "grabcut_camera04", "grabcut_20260902_044232",
          "xanylabeling_20260902_044232")
GUIDE = """North16 标注工作区

drafts/<片段>/<模态>/<镜头>/<批次>/       自动预标注，待审核
projects/<片段>/<模态>/<镜头>/<批次>/     X-AnyLabeling原图与JSON工程
corrected/<片段>/<模态>/<镜头>/<批次>/    人工修正回读PNG，仍待审核
profiles/<片段>/<模态>/<镜头>/<参数哈希>/ 参数及验证依据
archive/<旧目录名>/                     历史试验，保留原布局和内容

同一草稿与首次编辑导出共用批次编号；修正回读使用独立批次并记录来源工程。
正式审核标签位于sequences/<片段>/<模态>/<镜头>/masks，工作区不自动发布标签。
index.txt为自动生成的TAB清单；请勿手改。使用north16 annotations --root <datasets> --refresh刷新。
archive/migrations保存移动映射；旧文件内的历史绝对路径仅保留为来源记录。
未知目录不会被自动移动。不要在顶层新增算法名或试验名目录。
"""


def annotation_root(root):
    root = Path(root).resolve(strict=True)
    if (read_info(root / "info.txt").get("dataset_status") != "working" or
            read_info(root / "protocol.txt").get("schema_version") != "north16_seg_v1"):
        raise ValueError("请选择north16 working数据集根目录")
    base = root / "annotations"
    if base.is_symlink() or (base.exists() and not base.resolve().is_relative_to(root)):
        raise ValueError("annotations不能是外部链接")
    return root, base


def inventory(root):
    _, base = annotation_root(root)
    records = []
    for kind in KINDS[:-1]:
        for path in sorted((base / kind).glob("*/*/*/*")):
            if not path.is_dir() or path.is_symlink():
                continue
            sequence, sensor, camera, batch = path.relative_to(base / kind).parts
            if sensor not in ("visible", "infrared"):
                continue
            status, count = "unreviewed", ""
            for name in ("run.json", "validation.json", "import_log.json"):
                if (path / name).is_file():
                    data = json.loads((path / name).read_text(encoding="utf-8"))
                    status = data.get("status", status)
                    count = data.get("succeeded", data.get("count", count))
                    break
            records.append(dict(kind=kind, sequence=sequence, sensor=sensor, camera=camera,
                                batch=batch, path=path.relative_to(base.parent).as_posix(),
                                status=status, count=count))
    for path in sorted((base / "archive").glob("*")):
        if path.is_dir() and path.name != "migrations":
            records.append(dict(kind="archive", sequence="", sensor="", camera="",
                                batch=path.name, path=path.relative_to(base.parent).as_posix(),
                                status="historical_unreviewed", count=""))
    return records


def refresh(root):
    _, base = annotation_root(root)
    for kind in KINDS:
        target = base / kind
        if target.is_symlink() or (target.exists() and not target.resolve().is_relative_to(base)):
            raise ValueError(f"工作区目录不能是外部链接：{target}")
        target.mkdir(parents=True, exist_ok=True)
    records = inventory(root)
    temporary = base / ("index_" + uuid.uuid4().hex + ".partial")
    write_table(temporary, ("kind", "sequence", "sensor", "camera", "batch", "path", "status", "count"), records)
    temporary.replace(base / "index.txt")
    (base / "README.txt").write_text(GUIDE, encoding="utf-8")
    return records


def plan(root):
    root, base = annotation_root(root)
    moves = []
    for name in LEGACY:
        source, destination = base / name, base / "archive" / name
        if not source.exists():
            continue
        if source.is_symlink() or not source.is_dir() or destination.exists():
            raise ValueError(f"历史目录类型或目标冲突：{source}")
        moves.append(dict(source=source.relative_to(root).as_posix(),
                          destination=destination.relative_to(root).as_posix()))
    unknown = [p.name for p in base.iterdir() if p.is_dir() and p.name not in (*KINDS, *LEGACY)] if base.exists() else []
    return dict(moves=moves, unknown_directories=sorted(unknown))


def tree_identity(path):
    """Same-volume rename must preserve every file identity, size and mtime."""
    result = {}
    for child in path.rglob("*"):
        if child.is_symlink() or getattr(child, "is_junction", lambda: False)():
            raise ValueError(f"历史目录含链接，停止迁移：{child}")
        stat = child.stat()
        result[child.relative_to(path).as_posix()] = (child.is_dir(), stat.st_ino, stat.st_size if child.is_file() else 0,
                                                    stat.st_mtime_ns if child.is_file() else 0)
    return result


def move_directory(source, destination, base):
    """Use native Windows Move-Item if Python directory rename is denied."""
    base = base.resolve(strict=True)
    if not source.resolve(strict=True).is_relative_to(base) or not destination.resolve().is_relative_to(base):
        raise ValueError("迁移路径越出annotations")
    if destination.exists():
        raise FileExistsError(destination)
    try:
        source.rename(destination)
    except PermissionError:
        if os.name != "nt":
            raise
        # Pass paths as environment data, never interpolate them into shell code.
        script = """$ErrorActionPreference='Stop'
$source=[System.IO.Path]::GetFullPath($env:NORTH16_MOVE_SOURCE)
$destination=[System.IO.Path]::GetFullPath($env:NORTH16_MOVE_TARGET)
$root=[System.IO.Path]::GetFullPath($env:NORTH16_MOVE_ROOT).TrimEnd('\\')+'\\'
if (!$source.StartsWith($root,[System.StringComparison]::OrdinalIgnoreCase) -or !$destination.StartsWith($root,[System.StringComparison]::OrdinalIgnoreCase)) { throw 'Outside annotation workspace' }
if (Test-Path -LiteralPath $destination) { throw 'Destination exists' }
Move-Item -LiteralPath $source -Destination $destination -ErrorAction Stop
"""
        environment = dict(os.environ, NORTH16_MOVE_SOURCE=str(source), NORTH16_MOVE_TARGET=str(destination), NORTH16_MOVE_ROOT=str(base))
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-EncodedCommand",
                        base64.b64encode(script.encode("utf-16le")).decode("ascii")], env=environment, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    if source.exists() or not destination.is_dir():
        raise ValueError("原生目录移动未完成")


def organize(root):
    root, base = annotation_root(root)
    proposed = plan(root)
    # Preflight all trees before any move; preserve editable JSON byte for byte.
    trees = {item["source"]: tree_identity(root / item["source"]) for item in proposed["moves"]}
    refresh(root)
    journal = base / "archive" / "migrations" / (datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6] + ".json")
    journal.parent.mkdir(parents=True, exist_ok=True)
    report = dict(created_utc=datetime.now(timezone.utc).isoformat(), status="running", **proposed)
    for item in report["moves"]:
        item["status"] = "pending"
    def save():
        temporary = journal.with_suffix(".partial")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(journal)
    save()
    try:
        for item in report["moves"]:
            source, destination = root / item["source"], root / item["destination"]
            # Native same-volume rename, no recursive deletion or overwrite.
            move_directory(source, destination, base)
            item["status"] = "moved";save()
            if tree_identity(destination) != trees[item["source"]]:
                raise ValueError(f"移动后文件身份校验失败：{destination}")
            item.update(status="verified", files=sum(not v[0] for v in trees[item["source"]].values()))
            save()
        refresh(root)
        report["status"] = "succeeded"
    except Exception:
        for item in reversed(report["moves"]):
            src, dst = root / item["source"], root / item["destination"]
            if item["status"] in ("moved", "verified") and dst.exists() and not src.exists():
                move_directory(dst, src, base);item["status"] = "rolled_back"
        report["status"] = "failed_rolled_back";save()
        refresh(root)
        raise
    save()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--organize", action="store_true", help="Plan legacy archival; use --apply to execute")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="Refresh index.txt and the directory guide")
    args = parser.parse_args(argv)
    if args.apply and not args.organize:
        parser.error("--apply requires --organize")
    if args.refresh and args.organize:
        parser.error("Choose --refresh or --organize")
    result = organize(args.root) if args.apply else plan(args.root) if args.organize else refresh(args.root) if args.refresh else inventory(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
