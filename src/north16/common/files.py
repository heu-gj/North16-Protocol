"""Strict text contracts and atomic writes; never modify original inputs."""
from __future__ import annotations

import csv
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import shutil
import uuid


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def file_state(path: Path) -> str:
    """Cheap, transient change detection; this is NOT a content checksum."""
    stat = Path(path).stat()
    if not Path(path).is_file():
        raise ValueError(f"Not a regular file: {path}")
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}"


def check_size(path: Path, expected=None) -> int:
    """Check availability and an optional byte count, including legacy receipts."""
    file_state(path)
    size = Path(path).stat().st_size
    if expected not in (None, "", "unknown", "disabled") and size != int(expected):
        raise ValueError(f"File size mismatch / 文件大小校验失败: {path}")
    return size


def same_content(left: Path, right: Path) -> bool:
    """Compare only a destination conflict, without SHA or cached comparison."""
    if check_size(left) != check_size(right):
        return False
    with Path(left).open("rb") as a, Path(right).open("rb") as b:
        while True:
            block = a.read(1024 * 1024)
            if block != b.read(1024 * 1024):
                return False
            if not block:
                return True


def atomic_bytes(path: Path, data: bytes, *, durable: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp_" + uuid.uuid4().hex)
    try:
        with tmp.open("xb") as handle:
            handle.write(data)
            handle.flush()
            if durable:
                os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_text(path: Path, text: str, *, durable: bool = True) -> None:
    atomic_bytes(path, text.encode("utf-8"), durable=durable)


def read_info(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.strip() or not value.strip() or key.strip() in values:
            raise ValueError(f"Invalid/duplicate key in {path}: {line!r}")
        values[key.strip()] = value.strip()
    return values


def write_info(path: Path, values: dict, *, durable: bool = True) -> None:
    lines = []
    for key, value in values.items():
        value = "unknown" if value is None or value == "" else str(value)
        if any(c in value for c in "\r\n") or any(c in key for c in "=\r\n"):
            raise ValueError("Unsafe TXT value")
        lines.append(f"{key}={value}")
    write_text(path, "\n".join(lines) + "\n", durable=durable)


def read_table(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f"Invalid TSV header: {path}")
        rows = list(reader)
        if any(None in r or any(v is None for v in r.values()) for r in rows):
            raise ValueError(f"Malformed TSV: {path}")
        return rows


def write_table(path: Path, columns, rows) -> None:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        values = {k: row.get(k, "unknown") for k in columns}
        if any(any(c in str(v) for c in "\r\n\t") for v in values.values()):
            raise ValueError("Unsafe TSV value")
        writer.writerow(values)
    write_text(path, handle.getvalue())


def local_path(root: Path, relative: str) -> Path:
    key = PurePosixPath(relative)
    if not relative or key.is_absolute() or ".." in key.parts or "\\" in relative or ":" in relative:
        raise ValueError(f"Unsafe relative path: {relative}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes root: {relative}")
    return path


def copy_exact(source: Path, destination: Path) -> str:
    digest = sha256(source)
    if destination.exists():
        if sha256(destination) != digest:
            raise ValueError(f"Refusing to overwrite different file: {destination}")
        return digest
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(destination.name + ".tmp_" + uuid.uuid4().hex)
    try:
        shutil.copyfile(source, tmp)
        if sha256(tmp) != digest:
            raise ValueError(f"Copy verification failed: {source}")
        os.replace(tmp, destination)
    finally:
        tmp.unlink(missing_ok=True)
    return digest
