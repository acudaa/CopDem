#!/usr/bin/env python3
"""Sample Austria's national LiDAR-derived DHM (dhm_at_lamb_10m_2018.tif,
EPSG:31287, 10m) at each obstacle location, using the SAME single-cell +
5x5-window methodology as extract_dem.py used for Copernicus DEM — see
docs/lidar_comparison.md for the full design rationale, and
docs/dem_extraction.md for the methodology this mirrors.

Reads obstacles_dem_diff.csv (already has the CopDEM comparison columns
from extract_dem.py) and adds LiDAR columns to the SAME file in place,
rather than producing a separate output — this keeps one obstacle table
carrying both comparisons, so a row-by-row CopDEM-vs-LiDAR read is a
single-file lookup.

Vertical reference assumption (explicitly instructed, not independently
verified the way Austria's obstacle-data datum was): the LiDAR DEM is
assumed to be on the same EVRF2000 Austria height system (EPSG:9274) as
the obstacle data. Converted to EGM2008 via the same vertical_datum
conversion chain for a fair comparison against elev_base_egm2008_m.
"""
import csv
from pathlib import Path

import _rasterio_compat  # noqa: F401
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.windows import Window

from vertical_datum import SOURCE_VERTICAL_CRS, to_egm2008

ROOT_DIR = Path(__file__).parent.parent
LIDAR_PATH = ROOT_DIR / "data" / "dem_tiles" / "austria_localDEM" / "dhm_at_lamb_10m_2018.tif"
DIFF_CSV = ROOT_DIR / "data" / "obstacles" / "austria" / "obstacles_dem_diff.csv"

COUNTRY_VERTICAL_EPSG = SOURCE_VERTICAL_CRS["AT"]

_to_lidar_crs = Transformer.from_crs("EPSG:4326", "EPSG:31287", always_xy=True)


def _bilinear(src, frow, fcol):
    r0, c0 = int(np.floor(frow)), int(np.floor(fcol))
    r0 = min(max(r0, 0), src.height - 2)
    c0 = min(max(c0, 0), src.width - 2)
    dr, dc = frow - r0, fcol - c0
    window = Window(c0, r0, 2, 2)
    block = src.read(1, window=window, masked=True)
    if block.mask.any():
        return None
    top = block[0, 0] * (1 - dc) + block[0, 1] * dc
    bottom = block[1, 0] * (1 - dc) + block[1, 1] * dc
    return float(top * (1 - dr) + bottom * dr)


def _sample_point(src, x, y):
    row, col = src.index(x, y)
    if not (0 <= row < src.height and 0 <= col < src.width):
        return None, None

    frow, fcol = src.index(x, y, op=float)
    single = _bilinear(src, frow, fcol)
    if single is None:
        return None, None

    half = 2
    if row - half < 0 or row + half >= src.height or col - half < 0 or col + half >= src.width:
        return single, None

    window = Window(col - half, row - half, 5, 5)
    values = src.read(1, window=window, masked=True)
    if values.mask.all():
        return single, None
    values = np.ma.filled(values.astype("float64"), np.nan)
    values[values == src.nodata] = np.nan
    return single, values


def run(diff_csv=DIFF_CSV, lidar_path=LIDAR_PATH):
    with open(diff_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"{len(rows)} obstacles, sampling against {lidar_path.name}")

    counts = {"out_of_coverage": 0, "no_window": 0, "ok": 0}

    with rasterio.open(lidar_path) as src:
        for row in rows:
            lon, lat = float(row["lon"]), float(row["lat"])
            x, y = _to_lidar_crs.transform(lon, lat)
            single_raw, window_vals = _sample_point(src, x, y)

            if single_raw is None:
                counts["out_of_coverage"] += 1
                for key in (
                    "lidar_single_egm2008_m", "error_single_lidar_m",
                    "lidar_5x5_min_egm2008_m", "lidar_5x5_median_egm2008_m",
                    "lidar_5x5_mean_egm2008_m", "lidar_5x5_std_egm2008_m",
                    "error_5x5_min_lidar_m", "error_5x5_median_lidar_m",
                    "error_5x5_mean_lidar_m", "capture_signal_lidar_m",
                ):
                    row[key] = ""
                continue

            # Position-dependent conversion, assumed source datum per
            # docs/lidar_comparison.md - NOT independently confirmed the
            # way the obstacle data's own EVRS statement was.
            single_egm2008 = to_egm2008(lon, lat, single_raw, COUNTRY_VERTICAL_EPSG)
            row["lidar_single_egm2008_m"] = single_egm2008
            elev_base = float(row["elev_base_egm2008_m"])
            row["error_single_lidar_m"] = single_egm2008 - elev_base

            if window_vals is not None and not np.all(np.isnan(window_vals)):
                # Convert each raw window value individually - the geoid
                # correction is the same at this scale (5 cells = 50m) to
                # well under a millimetre, but converting per-value keeps
                # this consistent with how single-cell is handled and
                # avoids baking in an assumption about correction
                # constancy at a finer scale than actually checked.
                converted = to_egm2008(lon, lat, 0.0, COUNTRY_VERTICAL_EPSG)  # correction at this point
                window_egm2008 = window_vals + converted
                row["lidar_5x5_min_egm2008_m"] = float(np.nanmin(window_egm2008))
                row["lidar_5x5_median_egm2008_m"] = float(np.nanmedian(window_egm2008))
                row["lidar_5x5_mean_egm2008_m"] = float(np.nanmean(window_egm2008))
                row["lidar_5x5_std_egm2008_m"] = float(np.nanstd(window_egm2008))
                row["error_5x5_min_lidar_m"] = row["lidar_5x5_min_egm2008_m"] - elev_base
                row["error_5x5_median_lidar_m"] = row["lidar_5x5_median_egm2008_m"] - elev_base
                row["error_5x5_mean_lidar_m"] = row["lidar_5x5_mean_egm2008_m"] - elev_base
                row["capture_signal_lidar_m"] = single_egm2008 - row["lidar_5x5_median_egm2008_m"]
                counts["ok"] += 1
            else:
                for key in (
                    "lidar_5x5_min_egm2008_m", "lidar_5x5_median_egm2008_m",
                    "lidar_5x5_mean_egm2008_m", "lidar_5x5_std_egm2008_m",
                    "error_5x5_min_lidar_m", "error_5x5_median_lidar_m",
                    "error_5x5_mean_lidar_m", "capture_signal_lidar_m",
                ):
                    row[key] = ""
                counts["no_window"] += 1

    print("LiDAR extraction summary:", counts)

    fieldnames = list(rows[0].keys())
    with open(diff_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"updated {diff_csv} with LiDAR comparison columns")


if __name__ == "__main__":
    run()
