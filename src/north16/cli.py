"""One entry point; business logic remains in the existing domain modules."""
from __future__ import annotations

import argparse
from importlib import import_module, metadata, util
import json
import shutil
import sys

from north16 import __version__


COMMANDS = {
    "initialize": ("north16.layout.initialize", "Initialize structured dataset without decoding videos"),
    "camera": ("north16.camera.builder", "Extract registered camera frames or export camera packages"),
    "segmentation": ("north16.segmentation.builder", "Open annotation GUI or generate/export masks JSON packages"),
    "import-package": ("north16.packages.storage", "Merge checked camera/segmentation packages without conflicting overwrite"),
    "register": ("north16.registration.app", "Open visible/infrared registration workbench"),
    "annotations": ("north16.annotations.management", "Inspect annotation inventory or archive legacy experiments"),
    "gui": ("north16.gui.app", "Open the local GrabCut parameter workspace"),
    "init": ("north16.resources", "Create batch configs/templates/docs"),
    "build": ("north16.pipeline.build", "Inspect or extract a configured camera batch"),
    "validate": ("north16.validation.pilot", "Validate a built camera dataset"),
    "attributes": ("north16.annotations.attributes", "Apply an explicit weather/illumination decision plan"),
    "grabcut": ("north16.annotations.grabcut", "Generate fixed-profile visible drafts"),
    "export-labels": ("north16.annotations.xanylabeling", "Export editable X-AnyLabeling image/JSON pairs"),
    "import-labels": ("north16.annotations.xanylabeling", "Convert edited JSON to draft PNG masks"),
}


def doctor(argv):
    parser = argparse.ArgumentParser(description="Report optional dependencies without modifying the environment")
    parser.parse_args(argv)
    report = {"north16": __version__, "python": sys.version.split()[0], "executable": sys.executable}
    for module, distribution in (("yaml", "PyYAML"), ("PIL", "Pillow"),
                                 ("numpy", "numpy"), ("cv2", "opencv-python"), ("torch", "torch")):
        if util.find_spec(module) is None:
            report[module] = "not installed"
        else:
            try:
                report[module] = metadata.version(distribution)
            except metadata.PackageNotFoundError:
                report[module] = "available (alternate distribution)"
    report.update(ffmpeg=shutil.which("ffmpeg"), ffprobe=shutil.which("ffprobe"))
    print(json.dumps(report, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="north16", description=__doc__,
        epilog="\n".join(f"{name}: {entry[1]}" for name, entry in COMMANDS.items()),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"north16 {__version__}")
    parser.add_argument("command", nargs="?", choices=[*COMMANDS, "doctor"])
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return
    if args.command == "doctor":
        return doctor(args.arguments)
    forwarded = args.arguments
    if args.command in ("export-labels", "import-labels"):
        forwarded = ["export" if args.command == "export-labels" else "import", *forwarded]
    try:
        return import_module(COMMANDS[args.command][0]).main(forwarded)
    except ModuleNotFoundError as exc:
        extras = {"cv2": "annotation", "torch": "training", "PySide6": "gui"}
        if exc.name in extras:
            parser.exit(2, f"Missing {exc.name}; install with: python -m pip install 'north16[{extras[exc.name]}]'\n")
        raise
