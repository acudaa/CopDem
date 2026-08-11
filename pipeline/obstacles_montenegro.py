#!/usr/bin/env python3
"""Ingest Montenegro's aeronautical obstacle data set from the VFR AIP
Serbia/Montenegro ENR 5.4 "Air Navigation Obstacles" PDF.

Input: data/obstacles/montenegro/VFR_LY_ENR_5_4_en_*.pdf (downloaded manually
via the user's own EAD Basic / SMATSA access — see docs/montenegro.md for
why this couldn't be automated: ENR 5.4 sits behind account-gated access on
both SMATSA's own eAIP and Eurocontrol's EAD, and account creation is not
something this pipeline's tooling does on a user's behalf).
Output: data/obstacles/montenegro/obstacles_simple_points.csv — same column
schema as Austria's obstacles_simple_points.csv (see obstacles_austria.py),
so extract_dem.py / analyze scripts / QGIS builder work on either country's
CSV unmodified.

SCOPE CAVEAT (read this before comparing obstacle counts across countries):
ENR 5.4 is explicitly NOT a full obstacle inventory the way Austria's Excel
export is. Its own text states it covers only "permanent obstacles in Area 1
[within Beograd FIR] with height of 328 FT (100 M) AGL and higher" — i.e.
only very tall structures. Austria's ~1,932 points span a much wider height
range from a dedicated national obstacle database; Montenegro's ~51 points
here are a small, height-filtered subset of a combined Serbia/Montenegro
AIP table. This is a real difference in what's being measured, not a gap in
this pipeline's ingestion — do not read the smaller n as an apples-to-apples
comparison with Austria's coverage.

The document lists Serbia's obstacles ("a) Srbija") first, then Montenegro's
("b) Crna Gora") — only the Montenegro section is parsed here. Each row is
anchored by its "LY_OBST_NNNN" designation; the two countries' obstacles
share one numbering sequence (Montenegro's IDs are non-contiguous - e.g.
0019-0046 then 0077-0099 in the AIRAC AMDT 3/26 edition - because Serbia's
obstacles occupy the gaps), which is expected, not a sign of missing rows.
"""
import csv
import re
from pathlib import Path

import fitz  # pymupdf

from vertical_datum import SOURCE_VERTICAL_CRS, to_egm2008

SOURCE_DIR = Path(__file__).parent.parent / "data" / "obstacles" / "montenegro"
OUTPUT_PATH = SOURCE_DIR / "obstacles_simple_points.csv"

COUNTRY_VERTICAL_EPSG = SOURCE_VERTICAL_CRS["ME"]
FT_TO_M = 0.3048

# Montenegro section starts after this exact marker (confirmed present once,
# verbatim, in the AIRAC AMDT 3/26 edition — re-check if a future edition's
# wording changes and this stops matching).
MONTENEGRO_MARKER = "b) Crna Gora"

DESIGNATION_RE = re.compile(r"LY_OBST_(\d{4})")
LAT_RE = re.compile(r"(\d{6}(?:\.\d)?)N")
LON_RE = re.compile(r"(\d{7}(?:\.\d)?)E")
ELEV_HGT_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
LIT_RE = re.compile(r"\b(Yes|No)\b")
LGT_TYPE_COLOUR_RE = re.compile(r"FLG\s*/\s*[A-Z]|Data not AVBL")

# Known English obstacle-type keywords seen in the Montenegro section as of
# AIRAC AMDT 3/26. Extend this list (don't silently swallow unknown types)
# if a future edition adds a type not seen here.
KNOWN_TYPES = ["Wind turbine", "Antenna"]


def _find_source_pdf():
    matches = sorted(SOURCE_DIR.glob("VFR_LY_ENR_5_4_en_*.pdf"))
    if not matches:
        raise FileNotFoundError(f"No ENR 5.4 PDF found in {SOURCE_DIR}")
    return matches[-1]  # most recent by filename date sort


def _dms_to_dd(digits: str, deg_len: int) -> float:
    """digits: e.g. "421708.0" (deg_len=2, lat) or "0191242.5" (deg_len=3,
    lon) — DEG + MM + SS(.s), no separators, per the AIP's coordinate
    format."""
    deg = int(digits[:deg_len])
    minute = int(digits[deg_len:deg_len + 2])
    second = float(digits[deg_len + 2:])
    return deg + minute / 60 + second / 3600


def _extract_type(chunk: str):
    for t in KNOWN_TYPES:
        if t in chunk:
            return t
    return None


def _extract_location(chunk: str, type_word_sr: str):
    """Location text is everything before the Serbian obstacle-type word
    ("Vetrogenerator" / "Antena") that precedes the English type keyword —
    kept bilingual/as-is (not deduplicated across languages), matching how
    obstacles_austria.py keeps its source location text verbatim rather
    than trying to pick a single-language version."""
    idx = chunk.find(type_word_sr)
    text = chunk[:idx] if idx != -1 else chunk
    return re.sub(r"\s+", " ", text).strip(" -")


_TYPE_WORD_SR = {"Wind turbine": "Vetrogenerator", "Antenna": "Antena"}


def _parse_chunk(designation, chunk):
    lat_m = LAT_RE.search(chunk)
    lon_m = LON_RE.search(chunk)
    if not lat_m or not lon_m:
        return None, f"{designation}: could not find coordinates"
    lat = _dms_to_dd(lat_m.group(1), 2)
    lon = _dms_to_dd(lon_m.group(1), 3)

    # Search for ELEV/HGT only after the coordinates, to avoid any earlier
    # slash-separated text being mistaken for it.
    after_coords = chunk[lon_m.end():]
    eh_m = ELEV_HGT_RE.search(after_coords)
    if not eh_m:
        return None, f"{designation}: could not find ELEV/HGT GND pair"
    elev_top_amsl_ft, height_agl_ft = float(eh_m.group(1)), float(eh_m.group(2))

    obstacle_type = _extract_type(chunk)
    if obstacle_type is None:
        return None, f"{designation}: unrecognized obstacle type — add it to KNOWN_TYPES after checking the source"
    location = _extract_location(chunk, _TYPE_WORD_SR[obstacle_type])

    lit_m = LIT_RE.search(chunk[lon_m.end():])  # search past coordinates only —
    # "Yes"/"No" could in principle appear earlier in a place name, though it
    # hasn't in this data set.
    lit = None if not lit_m else lit_m.group(1) == "Yes"
    lgt_m = LGT_TYPE_COLOUR_RE.search(chunk)
    obst_lgt_type_colour = lgt_m.group(0) if (lgt_m and lgt_m.group(0) != "Data not AVBL") else None

    elev_top_amsl_m = elev_top_amsl_ft * FT_TO_M
    height_agl_m = height_agl_ft * FT_TO_M
    # Base = top - AGL height, same convention (and same past mistake to
    # avoid — see obstacles_austria.py) as Austria: the published ELEV is
    # the obstacle's TOP, not its base.
    elev_base_amsl_m = elev_top_amsl_m - height_agl_m

    elev_base_egm2008_m = to_egm2008(lon, lat, elev_base_amsl_m, COUNTRY_VERTICAL_EPSG)
    elev_top_egm2008_m = to_egm2008(lon, lat, elev_top_amsl_m, COUNTRY_VERTICAL_EPSG)
    geoid_correction_m = elev_base_egm2008_m - elev_base_amsl_m

    return {
        "id": f"LY_OBST_{designation}",
        "location": location,
        "obstacle_type": obstacle_type,
        "lon": lon,
        "lat": lat,
        "elev_top_amsl_ft": elev_top_amsl_ft,
        "height_agl_ft": height_agl_ft,
        "elev_top_amsl_m": elev_top_amsl_m,
        "elev_base_amsl_m": elev_base_amsl_m,
        "elev_vertical_crs_epsg": COUNTRY_VERTICAL_EPSG,
        "elev_base_egm2008_m": elev_base_egm2008_m,
        "elev_top_egm2008_m": elev_top_egm2008_m,
        "geoid_correction_m": geoid_correction_m,
        "height_agl_m": height_agl_m,
        "lit": lit,
        "obst_lgt_type_colour": obst_lgt_type_colour,
    }, None


def load_obstacles(pdf_path=None):
    pdf_path = pdf_path or _find_source_pdf()
    doc = fitz.open(pdf_path)
    full_text = "\n".join(page.get_text() for page in doc)
    doc.close()

    marker_idx = full_text.find(MONTENEGRO_MARKER)
    if marker_idx == -1:
        raise ValueError(
            f"Marker {MONTENEGRO_MARKER!r} not found in {pdf_path} — the "
            "document structure may have changed; re-check before parsing blindly."
        )
    mne_text = full_text[marker_idx:]

    # Split into per-obstacle chunks anchored on the designation. re.split
    # with a capturing group returns [junk_before_first, id1, chunk1, id2,
    # chunk2, ...].
    parts = DESIGNATION_RE.split(mne_text)
    obstacles, errors = [], []
    for designation, chunk in zip(parts[1::2], parts[2::2]):
        row, err = _parse_chunk(designation, chunk)
        if err:
            errors.append(err)
        else:
            obstacles.append(row)

    print(f"Montenegro obstacle ingestion (ENR 5.4, Area-1 >=100m AGL only):")
    print(f"  parsed OK: {len(obstacles)}")
    print(f"  errors: {len(errors)}")
    for e in errors:
        print(f"    - {e}")
    by_type = {}
    for o in obstacles:
        by_type[o["obstacle_type"]] = by_type.get(o["obstacle_type"], 0) + 1
    print(f"  by type: {by_type}")

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
    obstacles = load_obstacles()
    write_csv(obstacles)
