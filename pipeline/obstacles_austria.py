#!/usr/bin/env python3
"""Ingest Austria's ICAO obstacle data set — v1 scope: simple point obstacles
only. See docs/obstacle_ingestion.md for the full rationale behind every
filter and omission here; keep that file in sync with this one.

Input: the "Alle - All" sheet of the Austro Control obstacle Excel export
(data/obstacles/austria/extracted/LO_OBS_DS_AREA1_*.xlsx).
Output: a clean CSV of single-point obstacles, one row per obstacle, with
elevation converted to EGM2008 (Copernicus DEM's native reference) —
data/obstacles/austria/obstacles_simple_points.csv (gitignored: not ours to
redistribute, see the source's copyright disclaimer).
"""
import csv
import glob
import re
from pathlib import Path

import openpyxl

from vertical_datum import SOURCE_VERTICAL_CRS, to_egm2008

SOURCE_DIR = Path(__file__).parent.parent / "data" / "obstacles" / "austria" / "extracted"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "obstacles" / "austria" / "obstacles_simple_points.csv"

SHEET_NAME = "Alle - All"
HEADER_ROWS = 3  # footnote row + DE header row + EN header row
COUNTRY_VERTICAL_EPSG = SOURCE_VERTICAL_CRS["AT"]

# Column indices in the "Alle - All" sheet (0-based), fixed by the source format.
COL_REGION = 0
COL_DISTRICT = 1
COL_LOCATION = 2
COL_TYPE = 3
COL_GEOMETRY = 4
COL_COORD_DMS = 5
COL_COORD_DD = 6
COL_VERTICAL_REF = 7
COL_AMSL = 8
COL_AGL = 9
COL_DAY_MARKING = 10
COL_LIGHTED = 11
COL_DATA_QUALITY = 12
COL_H_EXTENT_LXW = 13
COL_H_EXTENT_RADIUS = 14
COL_H_ACCURACY = 15
COL_V_ACCURACY_ELEV = 16
COL_V_ACCURACY_AGL = 17
COL_ID = 18

POINT_GEOMETRY = "Point / Punkt"

_NUM_PAIR_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)\s*$")
_ACCURACY_NUM_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*M?\s*$")


def _parse_m_ft_pair(value):
    """Parse a "METERS / FEET" cell, returning the metres value. Only the
    metres figure is kept — feet is redundant and metres matches the DEM."""
    match = _NUM_PAIR_RE.match(str(value))
    if not match:
        return None
    return float(match.group(1))


def _parse_accuracy(value):
    """Parse an accuracy cell ("0.15 M", "---") to metres, or None if not
    stated. '---' (not stated) is kept as None, never coerced to 0 — a
    missing accuracy is not the same claim as a perfect one."""
    text = str(value).strip()
    if text in ("---", "", "None"):
        return None
    match = _ACCURACY_NUM_RE.match(text)
    return float(match.group(1)) if match else None


def _parse_yes_no(value):
    text = str(value).strip().lower()
    if text.startswith("ja") or text.startswith("yes"):
        return True
    if text.startswith("nein") or text.startswith("no"):
        return False
    return None


def _find_source_workbook():
    matches = sorted(SOURCE_DIR.glob("LO_OBS_DS_AREA1_*.xlsx"))
    if not matches:
        raise FileNotFoundError(f"No obstacle Excel file found in {SOURCE_DIR}")
    return matches[-1]  # most recent effective date, by filename sort


def load_simple_point_obstacles(xlsx_path=None):
    """Return a list of dicts: one clean, single-point obstacle per entry.
    Applies every filter documented in docs/obstacle_ingestion.md and prints
    a summary of what was kept vs. excluded and why."""
    xlsx_path = xlsx_path or _find_source_workbook()
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb[SHEET_NAME]
    rows = list(ws.iter_rows(min_row=HEADER_ROWS + 1, values_only=True))

    counts = {
        "total_rows": len(rows),
        "not_point_geometry": 0,
        "multiline_coordinate": 0,
        "missing_id": 0,
        "unparseable_amsl": 0,
        "unparseable_coord": 0,
        "missing_agl_for_base": 0,
        "kept": 0,
    }

    obstacles = []
    for row in rows:
        if row[COL_GEOMETRY] != POINT_GEOMETRY:
            counts["not_point_geometry"] += 1
            continue

        coord_dms = row[COL_COORD_DMS]
        if coord_dms and "\n" in str(coord_dms):
            # A handful of "Point" rows carry more than one coordinate line —
            # inconsistent with a true single point. Deferred, not parsed.
            counts["multiline_coordinate"] += 1
            continue

        obstacle_id = row[COL_ID]
        if not obstacle_id:
            counts["missing_id"] += 1
            continue

        coord_dd = str(row[COL_COORD_DD]).split()
        if len(coord_dd) != 2:
            counts["unparseable_coord"] += 1
            continue
        lat, lon = float(coord_dd[0]), float(coord_dd[1])

        # "Maximale Hoehe AMSL" is the obstacle's TOP elevation (ICAO "ELEV"
        # convention), NOT its base — confirmed empirically (see
        # docs/obstacle_ingestion.md): treating it as base elevation gave a
        # ~-43 m mean "DEM error" that correlated at r=-0.95 with AGL height,
        # i.e. it was just the obstacle's own height showing up as bogus
        # error. Base elevation = top elevation - AGL height. The unmarked
        # (non-"*") convention applies to 100% of our clean Point rows.
        elev_top_amsl_m = _parse_m_ft_pair(row[COL_AMSL])
        if elev_top_amsl_m is None:
            counts["unparseable_amsl"] += 1
            continue
        height_agl_m = _parse_m_ft_pair(row[COL_AGL])
        elev_base_amsl_m = elev_top_amsl_m - height_agl_m if height_agl_m is not None else None
        if elev_base_amsl_m is None:
            counts["missing_agl_for_base"] += 1
            continue

        vertical_ref = row[COL_VERTICAL_REF]
        assert vertical_ref == "EVRS", (
            f"Unexpected vertical reference '{vertical_ref}' for {obstacle_id} — "
            "the EVRF2000 Austria conversion assumes EVRS uniformly; re-check "
            "docs/obstacle_ingestion.md before trusting this record."
        )
        elev_base_egm2008_m = to_egm2008(lon, lat, elev_base_amsl_m, COUNTRY_VERTICAL_EPSG)
        elev_top_egm2008_m = to_egm2008(lon, lat, elev_top_amsl_m, COUNTRY_VERTICAL_EPSG)
        # The net adjustment applied by the EVRF2000 Austria -> EGM2008
        # conversion at this point (position-dependent, not a constant -
        # see vertical_datum.py). Positive means EGM2008 sits above the
        # source datum here; this is what "elev_base_amsl_m" was shifted by
        # to get "elev_base_egm2008_m", recorded explicitly so the size of
        # the datum correction itself is visible per-point, not just baked
        # silently into the converted value.
        geoid_correction_m = elev_base_egm2008_m - elev_base_amsl_m

        obstacles.append({
            "id": obstacle_id,
            "region": row[COL_REGION],
            "district": row[COL_DISTRICT],
            "location": row[COL_LOCATION],
            "obstacle_type": row[COL_TYPE],
            "lon": lon,
            "lat": lat,
            "elev_top_amsl_m": elev_top_amsl_m,
            "elev_base_amsl_m": elev_base_amsl_m,
            "elev_vertical_crs_epsg": COUNTRY_VERTICAL_EPSG,
            "elev_base_egm2008_m": elev_base_egm2008_m,
            "elev_top_egm2008_m": elev_top_egm2008_m,
            "geoid_correction_m": geoid_correction_m,
            "height_agl_m": height_agl_m,
            "day_marking": _parse_yes_no(row[COL_DAY_MARKING]),
            "lighted": _parse_yes_no(row[COL_LIGHTED]),
            "horizontal_accuracy_m": _parse_accuracy(row[COL_H_ACCURACY]),
            "vertical_accuracy_elev_m": _parse_accuracy(row[COL_V_ACCURACY_ELEV]),
            "vertical_accuracy_agl_m": _parse_accuracy(row[COL_V_ACCURACY_AGL]),
        })
        counts["kept"] += 1

    print("Austria obstacle ingestion (simple points, v1):")
    for key, value in counts.items():
        print(f"  {key}: {value}")

    return obstacles


def write_csv(obstacles, output_path=OUTPUT_PATH):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(obstacles[0].keys())
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(obstacles)
    print(f"wrote {len(obstacles)} rows to {output_path}")


if __name__ == "__main__":
    obstacles = load_simple_point_obstacles()
    write_csv(obstacles)
