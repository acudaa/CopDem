#!/usr/bin/env python3
"""Sample the cached Copernicus DEM tiles at each obstacle location:
single-cell (bilinear) and a 5x5-cell window, per docs/dem_extraction.md.

Samples directly from whichever native DEM chunk file contains each point —
never through the mosaic VRT (dem_mosaic.vrt), which exists purely for
QGIS visualization and involves small cross-band resampling that has no
business anywhere near the actual numeric comparison.
"""
import csv
import glob
import re
from pathlib import Path

import _rasterio_compat  # noqa: F401  (must precede `import rasterio`)
import numpy as np
import rasterio
from rasterio.windows import Window

DEM_DIR = Path(__file__).parent.parent / "data" / "dem_tiles"
OBSTACLES_CSV = Path(__file__).parent.parent / "data" / "obstacles" / "austria" / "obstacles_simple_points.csv"
OUTPUT_CSV = Path(__file__).parent.parent / "data" / "obstacles" / "austria" / "obstacles_dem_diff.csv"

_CHUNK_NAME_RE = re.compile(r"dem_([\d.]+)_([\d.]+)_([\d.]+)_([\d.]+)\.tif$")


def _load_chunk_index(dem_dir=DEM_DIR):
    """Map each cached chunk file to its (min_lon, min_lat, max_lon, max_lat)."""
    index = []
    for path in sorted(dem_dir.glob("dem_*.tif")):
        m = _CHUNK_NAME_RE.search(path.name)
        if not m:
            continue
        min_lon, min_lat, max_lon, max_lat = map(float, m.groups())
        index.append((path, min_lon, min_lat, max_lon, max_lat))
    return index


def _find_chunk(index, lon, lat):
    for path, min_lon, min_lat, max_lon, max_lat in index:
        if min_lon <= lon <= max_lon and min_lat <= lat <= max_lat:
            return path
    return None


def _sample_point(src, lon, lat):
    """Return (single_cell_value, window_5x5_values) at (lon, lat), or
    (None, None) if the 5x5 window would run off the edge of this chunk
    (see docs/dem_extraction.md — cross-tile windows are a known v1 gap)."""
    row, col = src.index(lon, lat)

    if not (0 <= row < src.height and 0 <= col < src.width):
        return None, None

    # Single-cell: bilinear interpolation at the exact sub-pixel position.
    fractional_row, fractional_col = src.index(lon, lat, op=float)
    single = _bilinear(src, fractional_row, fractional_col)

    # 5x5 window centered on the containing cell.
    half = 2
    if row - half < 0 or row + half >= src.height or col - half < 0 or col + half >= src.width:
        return single, None  # window falls off this chunk's edge

    window = Window(col - half, row - half, 5, 5)
    values = src.read(1, window=window)
    nodata = src.nodata
    if nodata is not None:
        values = np.where(values == nodata, np.nan, values)
    return single, values


def _bilinear(src, frow, fcol):
    r0, c0 = int(np.floor(frow)), int(np.floor(fcol))
    r0 = min(max(r0, 0), src.height - 2)
    c0 = min(max(c0, 0), src.width - 2)
    dr, dc = frow - r0, fcol - c0
    window = Window(c0, r0, 2, 2)
    block = src.read(1, window=window)
    top = block[0, 0] * (1 - dc) + block[0, 1] * dc
    bottom = block[1, 0] * (1 - dc) + block[1, 1] * dc
    return float(top * (1 - dr) + bottom * dr)


def load_obstacles(csv_path=OBSTACLES_CSV):
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run(obstacles_csv=OBSTACLES_CSV, dem_dir=DEM_DIR, output_csv=OUTPUT_CSV):
    index = _load_chunk_index(dem_dir)
    obstacles = load_obstacles(obstacles_csv)
    print(f"{len(obstacles)} obstacles, {len(index)} cached DEM chunks")

    open_chunks = {}
    counts = {"no_chunk": 0, "off_edge": 0, "no_window": 0, "ok": 0}
    results = []

    for obs in obstacles:
        lon, lat = float(obs["lon"]), float(obs["lat"])
        chunk_path = _find_chunk(index, lon, lat)
        if chunk_path is None:
            counts["no_chunk"] += 1
            continue

        if chunk_path not in open_chunks:
            open_chunks[chunk_path] = rasterio.open(chunk_path)
        src = open_chunks[chunk_path]

        single, window_vals = _sample_point(src, lon, lat)
        if single is None:
            counts["off_edge"] += 1
            continue

        row = dict(obs)
        row["dem_single_egm2008_m"] = single
        # Compare against BASE elevation, not top — see docs/obstacle_ingestion.md
        elev = float(obs["elev_base_egm2008_m"])
        row["error_single_m"] = single - elev

        if window_vals is not None and not np.all(np.isnan(window_vals)):
            row["dem_5x5_min_egm2008_m"] = float(np.nanmin(window_vals))
            row["dem_5x5_median_egm2008_m"] = float(np.nanmedian(window_vals))
            row["dem_5x5_mean_egm2008_m"] = float(np.nanmean(window_vals))
            row["dem_5x5_std_egm2008_m"] = float(np.nanstd(window_vals))
            row["error_5x5_min_m"] = row["dem_5x5_min_egm2008_m"] - elev
            row["error_5x5_median_m"] = row["dem_5x5_median_egm2008_m"] - elev
            row["error_5x5_mean_m"] = row["dem_5x5_mean_egm2008_m"] - elev
            row["capture_signal_m"] = single - row["dem_5x5_median_egm2008_m"]
            counts["ok"] += 1
        else:
            for key in ("dem_5x5_min_egm2008_m", "dem_5x5_median_egm2008_m",
                        "dem_5x5_mean_egm2008_m", "dem_5x5_std_egm2008_m",
                        "error_5x5_min_m", "error_5x5_median_m", "error_5x5_mean_m",
                        "capture_signal_m"):
                row[key] = ""
            counts["no_window"] += 1

        results.append(row)

    for src in open_chunks.values():
        src.close()

    print("Extraction summary:", counts)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(results[0].keys())
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"wrote {len(results)} rows to {output_csv}")


if __name__ == "__main__":
    run()
