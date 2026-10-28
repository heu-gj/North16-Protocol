North16 Protocol 0.11.0 introduces an independent annotation workspace.

- Initialize the final datasets directory without decoding, then create an annotation workspace from its source registry.
- Extract videos in the workspace with optional --interval seconds and read-only --dry-run capacity diagnostics.
- Open `north16 annotation gui --root <workspace>`. Save JSON directly in each camera's masks/ next to images/.
- Tune and validate each visible camera independently; save only selected cameras.
- Export images, JSON labels and per-frame metadata together using `north16 annotation export`. Unlabeled images in selected complete streams are retained and counted.
- Import the combined package into the final datasets directory with checked source identity, hashes, frame receipts and label validation. Conflicting manual edits are preserved.
- Export uses staging and only publishes a complete package; cancellation and failures leave the source workspace intact.
- Existing camera extraction and external segmentation-package workflows remain compatible. Dataset readers consume merged stream indices directly.

Install `python -m pip install "north16-0.11.0-py3-none-any.whl[gui]"`, or install source with `python -m pip install ".[gui]"`. FFmpeg/FFprobe are separate requirements. Dataset readers need the training extra. Generated labels remain draft/unreviewed; visible GrabCut does not certify synchronization or provide infrared segmentation.

See docs/WORKFLOW.md and docs/ANNOTATION.md for the workflow and storage contract. SHA256SUMS.txt records wheel and source distribution checksums.
