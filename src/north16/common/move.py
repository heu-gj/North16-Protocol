"""Verified same-volume directory moves on Windows and POSIX."""
import base64
import os
from pathlib import Path
import subprocess

def move_directory(source, destination, base):
    """Use native Windows Move-Item if Python directory rename is denied."""
    base = base.resolve(strict=True)
    if not source.resolve(strict=True).is_relative_to(base) or not destination.resolve().is_relative_to(base):
        raise ValueError("迁移路径越出允许的工作目录")
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
if (!$source.StartsWith($root,[System.StringComparison]::OrdinalIgnoreCase) -or !$destination.StartsWith($root,[System.StringComparison]::OrdinalIgnoreCase)) { throw 'Outside allowed workspace' }
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
