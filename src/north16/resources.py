"""Initialize a batch workspace from the versioned protocol bundled in the wheel."""
from __future__ import annotations

import argparse
from importlib.resources import files
from pathlib import Path
import shutil
import tempfile

import yaml

from north16 import __version__


def resource_root():
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "configs/protocol.yaml").is_file():
        return checkout
    return files("north16").joinpath("_resources")


def copy_resource(source, target):
    if source.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            copy_resource(child, target / child.name)
    else:
        target.write_bytes(source.read_bytes())


def initialize(destination, raw, output, segments):
    destination = Path(destination).resolve()
    raw, output = Path(raw).resolve(), Path(output).resolve()
    if destination.exists():
        raise FileExistsError(f"Existing project is protected: {destination}")
    if not segments or len(set(segments)) != len(segments):
        raise ValueError("Provide unique explicit segment folder names")
    for segment in segments:
        if segment in (".", "..") or "/" in segment or "\\" in segment or ":" in segment:
            raise ValueError(f"Invalid segment folder name: {segment}")
    if raw == output or raw.is_relative_to(output) or output.is_relative_to(raw):
        raise ValueError("Raw and dataset output must be disjoint")
    for data in (raw, output):
        if destination == data or destination.is_relative_to(data) or data.is_relative_to(destination):
            raise ValueError("Batch project must be separate from raw and dataset output")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Commit only a complete, new configuration workspace; never touch images.
    with tempfile.TemporaryDirectory(prefix="north16_init_", dir=destination.parent) as temporary:
        staging = Path(temporary) / "project"
        staging.mkdir()
        resources = resource_root()
        for folder in ("configs", "templates", "docs"):
            copy_resource(resources.joinpath(folder), staging / folder)
        recipe = staging / "configs/pilot.yaml"
        config = yaml.safe_load(recipe.read_text(encoding="utf-8"))
        config["dataset"]["output_root"] = output.as_posix()
        source = config["inputs"][0]
        source.update(path=raw.as_posix(), segments=list(segments),
                      raw_root_id=raw.name, session_id=raw.name,
                      recording_date_label="unknown", verified_timezone=None)
        config["status"] = "explicit_camera_batch"
        (staging / "configs/import.yaml").write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        recipe.unlink()
        (staging / "README.md").write_text(
            f"# North16 batch configuration\n\nCreated with north16 {__version__}.\n\n"
            "Edit configs/import.yaml; raw images remain read-only.\n\n"
            "Inspect first: north16 build --config configs/import.yaml --inspect-only\n"
            "Build: north16 build --config configs/import.yaml\n",
            encoding="utf-8")
        staging.rename(destination)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--segments", nargs="+", required=True)
    args = parser.parse_args(argv)
    print(initialize(args.destination, args.raw, args.output, args.segments))
