"""Preserve radar and navigation evidence without inventing scan acquisition times."""
from __future__ import annotations

import csv
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image

from north16.common.files import copy_exact, read_info, write_info, write_table


def preserve(assets, output: Path, run: Path, config: dict, templates: Path) -> list[dict]:
    findings = []
    for segment in config["inputs"][0]["segments"]:
        group = [a for a in assets if a.segment == segment]
        sequence = group[0].sequence
        seq = output / "sequences" / sequence
        info_path = seq / "info.txt"
        if info_path.exists():
            old = read_info(info_path)
            if old.get("source_relative_path") != segment or old.get("session_id") != config["inputs"][0]["session_id"]:
                raise ValueError(f"Sequence source identity collision: {seq}")
        else:
            info = read_info(templates / "sequence_info.txt")
            info.update(record_status="recorded", sequence=sequence, segment_id=segment,
                        source_relative_path=segment, source_namespace=config["inputs"][0]["source_namespace"],
                        session_id=config["inputs"][0]["session_id"], raw_root_id=config["inputs"][0]["raw_root_id"])
            write_info(info_path, info)
        for asset in group:
            if asset.sensor == "source":
                # Preserve time.txt as an unassigned raw log, never zip to decoded frames.
                copy_exact(asset.path, seq / "source" / asset.path.name)
        navs = [a for a in group if a.sensor == "nav"]
        for asset in navs:
            destination = seq / "nav" / ("source.txt" if asset.path.name == "navigation_radar.txt" else "source" / Path(asset.path.name))
            copy_exact(asset.path, destination)
            if asset.path.name == "navigation_radar.txt":
                records = []
                for number, line in enumerate(asset.path.read_text(encoding="utf-8-sig").splitlines(), 1):
                    prefix, sep, value = line.partition(":")
                    records.append(dict(row=number, field=prefix if sep else "unknown", raw_value=value if sep else line,
                                        parse_status="raw_fields_only_semantics_unverified", capture_time_utc="unknown"))
                write_table(seq / "nav" / "records.txt", ("row", "field", "raw_value", "parse_status", "capture_time_utc"), records)
                write_info(seq / "nav" / "info.txt", dict(schema_version="north16_nav_v1", source_id=asset.source_id,
                           source_sha256=asset.digest, source_relative_path=asset.relative,
                           parse_status="raw_fields_only_semantics_unverified", actual_nav_radar_imagery="not_provided"))
        radars = [a for a in group if a.sensor == "ice_radar"]
        if not radars:
            continue
        lookup = {a.path.stem: a for a in radars if a.path.suffix.lower() in {".tif", ".tiff"}}
        mapping = {}
        kml_records = []
        for asset in radars:
            if asset.path.suffix.lower() in {".tif", ".tiff"}:
                # Exact file-content asset identity; independence is deliberately unverified.
                scan = "scan_" + asset.digest[:24]
                folder = seq / "ice_radar" / "scans" / scan
                copy_exact(asset.path, folder / "image.tif")
                with Image.open(asset.path) as im:
                    metadata = dict(width=im.width, height=im.height, mode=im.mode,
                                    tiff_tag_ids=",".join(map(str, im.tag_v2.keys())))
                if not (folder / "info.txt").exists():
                    write_info(folder / "info.txt", dict(schema_version="north16_radar_asset_v1", scan_id=scan,
                               sha256=asset.digest, identity_basis="exact_file_content_including_geotiff_tags",
                               scan_independence="unverified", capture_time_utc="unknown",
                               physical_units="unknown", geospatial_handling="original_geotiff_preserved_uninterpreted",
                               **metadata))
                mapping[asset.path.stem] = (scan, asset.digest, asset.source_id)
            else:
                copy_exact(asset.path, seq / "ice_radar" / "source" / asset.path.name)
                if asset.path.suffix.lower() == ".kml":
                    try:
                        ET.parse(asset.path)
                        status, reason = "valid_xml", "unknown"
                    except (ET.ParseError, UnicodeError, ValueError) as exc:
                        status, reason = "invalid_xml_preserved", str(exc).replace("\n", " ").replace("\r", " ")
                    kml_records.append(dict(source_id=asset.source_id, filename=asset.path.name, status=status, reason=reason))
        index = next((a for a in radars if a.path.name == "ice_radar_index.txt"), None)
        receptions = []
        if index:
            with index.path.open(encoding="utf-8-sig", newline="") as handle:
                for number, row in enumerate(csv.DictReader(handle), 2):
                    name = Path(row.get("ICE_RADAR_FILE", "unknown")).stem
                    match = mapping.get(name)
                    receptions.append(dict(index_row=number, raw_timestamp=row.get("TIME", "unknown"),
                        status=row.get("STATUS", "unknown"), source_name=name,
                        scan_id=match[0] if match else "unknown", source_id=match[2] if match else "unknown",
                        source_sha256=match[1] if match else "unknown", capture_time_utc="unknown",
                        scan_independence="unverified", metadata_path=f"sequences/{sequence}/ice_radar/source/{name}.kml"
                        if (seq / "ice_radar/source" / (name + ".kml")).exists() else "unknown"))
        write_table(seq / "ice_radar" / "records.txt", ("index_row", "raw_timestamp", "status", "source_name", "scan_id",
                    "source_id", "source_sha256", "capture_time_utc", "scan_independence", "metadata_path"), receptions)
        write_table(seq / "ice_radar" / "metadata_checks.txt", ("source_id", "filename", "status", "reason"), kml_records)
        invalid = sum(r["status"] == "invalid_xml_preserved" for r in kml_records)
        write_info(seq / "ice_radar" / "info.txt", dict(schema_version="north16_radar_v1", record_status="recorded",
                   source_tiff_count=len(lookup), exact_content_asset_count=len({v[1] for v in mapping.values()}),
                   reception_count=len(receptions), invalid_kml_count=invalid,
                   independent_scan_count="unknown", scan_independence="unverified", time_mapping_status="unresolved"))
        findings.append(dict(sequence=sequence, radar_files=len(lookup), content_assets=len({v[1] for v in mapping.values()}),
                             invalid_kml=invalid, unmatched_receptions=sum(r["scan_id"] == "unknown" for r in receptions)))
    return findings
