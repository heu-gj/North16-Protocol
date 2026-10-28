North16 Protocol 0.13.0 adds extraction progress to camera and annotation commands.

- `north16 annotation extract` and `north16 camera extract` now show progress by default: source preflight, stream number, source frames decoded, selected output frames, image verification/metadata, and publication.
- Progress monitors the existing showinfo log without changing FFmpeg filters, image pixels or frame PTS.
- Interactive terminals update one line; redirected logs use throttled stage records. Progress goes to stderr and the final JSON report remains on stdout.
- Decode percentages are estimates and stay below 100%; overall completion is reported only after successful validation and index publication. Reused streams and failures have explicit states.
- `--no-progress` disables progress. `--dry-run` remains read-only and does not show extraction progress. Python APIs can receive progress event callbacks.
- Tests cover real full/sparse videos, output equivalence, both CLI entry points, failure states and decoder timeout cleanup.

Install `python -m pip install "north16-0.13.0-py3-none-any.whl[gui]"`. Existing independent annotation workspaces, profile reuse, combined image/label delivery and Dataset APIs remain available. See docs/CLI.md and docs/WORKFLOW.md.
