North16 Protocol 0.14.0 removes file SHA work from the recommended modular workflow.

- Initialization inventories paths, sizes and modification times without reading every raw file for SHA. Extraction checks source metadata, frame identities, sizes and PTS, and no longer hashes exported images.
- Automatic parameter estimation, GUI previews, editable JSON generation and Dataset label loading do not compute or validate file SHA. New labels record image_bytes; legacy SHA records remain readable without rewriting user data.
- Delivery manifests now record path and size_bytes. Export/import check sizes and file state; existing destination conflicts use streaming byte comparison, so different manual labels remain protected. Old SHA-only manifests remain readable.
- File-state checks are metadata checks, not content-integrity guarantees. Parameter and in-memory preview fingerprints remain. Historical build/pilot, PNG-draft editing and independent registration tools retain their existing contracts.
- Conversion keys no longer depend on package version. Compatible legacy stream keys are accepted so a software-only upgrade can reuse existing extracted images; changing the interval still rejects reuse.
- Tests exercise real video through delivery and Dataset loading with all file-SHA helpers disabled, legacy records/manifests, v0.13 stream reuse and same-size manual-label conflicts.

Install `python -m pip install "north16-0.14.0-py3-none-any.whl[gui]"`. Restart open GUI windows to load the update. The change reduces repeated disk reads; it does not reduce PNG image size. See docs/WORKFLOW.md and docs/ANNOTATION.md.
