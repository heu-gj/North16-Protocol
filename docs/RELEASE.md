North16 Protocol 0.12.0 adds reusable camera parameter profiles and a two-point straight horizon by default.

- New windows, untouched cameras, reset defaults and default CLI profiles use two horizon endpoints; existing saved polylines retain their control points when loaded.
- Save parameter JSON and validation records as before; saving also copies a session snapshot for immediate reuse.
- Copy the current complete parameter profile, switch cameras, and paste it. Subsequent edits remain independent.
- Apply the current profile to every visible camera in the current sequence, including unchecked cameras. Other sequences and infrared profiles retain their settings.
- Copied profiles include horizon, sea mode, thresholds and algorithm settings. Source camera estimation/validation evidence is not copied.
- Paste/apply-all mark previews and sample validation stale when parameters differ, and turn off automatic re-estimation before generation. Labels are not modified by parameter reuse.
- Session snapshots last for the current window; save/load JSON to reuse across launches.

Independent annotation workspaces, combined image/JSON delivery, interval extraction and Dataset readers remain available. See docs/GUI.md and docs/WORKFLOW.md.

Install `python -m pip install "north16-0.12.0-py3-none-any.whl[gui]"`. Generated labels remain draft/unreviewed and require manual review. FFmpeg/FFprobe are separate requirements.
