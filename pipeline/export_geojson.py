#!/usr/bin/env python3
"""Export the obstacle CSVs to GeoJSON, for QGIS. GeoJSON over the raw CSVs
because it's self-describing (geometry + CRS need no manual QGIS
delimited-text configuration) and trivial to generate correctly from the
standard library alone (json + csv), no extra geospatial dependency needed
for what's a straightforward point-per-row conversion.
"""
import csv
import json
from pathlib import Path

OBSTACLES_CSV = Path(__file__).parent.parent / "data" / "obstacles" / "austria" / "obstacles_simple_points.csv"
DIFF_CSV = Path(__file__).parent.parent / "data" / "obstacles" / "austria" / "obstacles_dem_diff.csv"

OBSTACLES_GEOJSON = Path(__file__).parent.parent / "data" / "obstacles" / "austria" / "obstacles_simple_points.geojson"
DIFF_GEOJSON = Path(__file__).parent.parent / "data" / "obstacles" / "austria" / "obstacles_dem_diff.geojson"

BOOL_FIELDS = {"day_marking", "lighted"}
FLOAT_SUFFIXES = ("_m", "_epsg")  # numeric-looking fields; empty string -> null


def _coerce(key, value):
    if value == "":
        return None
    if key in BOOL_FIELDS:
        return value == "True"
    if key.endswith(FLOAT_SUFFIXES):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def csv_to_geojson(csv_path, geojson_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    features = []
    for row in rows:
        lon, lat = float(row["lon"]), float(row["lat"])
        props = {k: _coerce(k, v) for k, v in row.items() if k not in ("lon", "lat")}
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })

    fc = {
        "type": "FeatureCollection",
        "name": geojson_path.stem,
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features,
    }

    geojson_path.parent.mkdir(parents=True, exist_ok=True)
    with open(geojson_path, "w", encoding="utf-8") as f:
        json.dump(fc, f)
    print(f"wrote {len(features)} features to {geojson_path}")


if __name__ == "__main__":
    csv_to_geojson(OBSTACLES_CSV, OBSTACLES_GEOJSON)
    csv_to_geojson(DIFF_CSV, DIFF_GEOJSON)
