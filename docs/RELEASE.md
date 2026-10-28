North16 Protocol 0.10.1 packages the current dataset and annotation workflow for installation from source, GitHub, or a wheel.

- Install the GUI: `python -m pip install "north16-0.10.1-py3-none-any.whl[gui]"`.
- Source installation: `python -m pip install ".[gui]"`.
- Launch: `north16 segmentation gui --root <dataset-root>`.
- Includes structured initialization, camera extraction, two-point horizon editing, 16-camera preview/validation, selected-camera JSON export, checked package import, and Dataset readers.
- Bundles protocol configs, TXT templates, and documentation. FFmpeg/FFprobe and X-AnyLabeling are separate tools. Dataset readers require the `[training]` extra.
- Generated labels remain draft/unreviewed. Infrared segmentation and certified synchronization are not provided by the visible GrabCut workflow.

Download the wheel for installation, or the `.tar.gz` source distribution for rebuilding. `SHA256SUMS.txt` contains checksums for both files. Full instructions are in the repository README and `docs/WORKFLOW.md`.

Camera extraction now supports `--interval 5` (seconds). It preserves source frame indices and PTS, selects real frames without interpolation, and records the sampling policy. Omit the option for full extraction. Existing streams are protected from sampling-policy conflicts.

Read-only `camera extract --dry-run` reports selected streams, frame estimates, conservative RGB24 storage budget, and free space. Capacity errors now include the budget, free space, and stream count. The independent annotation workspace is documented as a proposal; its new storage layout is not implemented in this release.
