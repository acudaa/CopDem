#!/usr/bin/env python3
"""Build a difference raster: Copernicus DEM GLO-30 minus Austria's LiDAR-
derived DHM (dhm_at_lamb_10m_2018.tif), both on EGM2008, on a **10 m grid**
— LiDAR's own native grid (EPSG:31287), unmodified. See
docs/lidar_comparison.md for the full design rationale, known limitations,
and the vertical-datum assumption.

Redone from an earlier version that output on CopDEM's coarser ~30 m grid
(downsampling LiDAR via averaging). This version does the opposite:
CopDEM is upsampled onto LiDAR's 10 m grid via bilinear interpolation,
via a WarpedVRT over the CopDEM mosaic (data/dem_mosaic.vrt) so the whole
country is one continuous reproject rather than 40 separate per-chunk
warps — there's now a single unambiguous target grid (LiDAR's own),
unlike the previous version's need to warp LiDAR onto 40 different native
CopDEM grids. LiDAR itself is read directly, at full native resolution,
never resampled — it's the detail this version is built to preserve.

Processed in blocks (not one giant in-memory array — the full grid is
58,061 x 31,793 = ~1.85 billion pixels) via windowed reads/writes.

Steps per block:
  1. Read the LiDAR block directly (native 10 m, untouched).
  2. Read the SAME block window from a WarpedVRT of the CopDEM mosaic,
     reprojected onto LiDAR's exact CRS/transform (bilinear - this is an
     upsample, ~30m -> 10m, so bilinear/cubic is appropriate; average
     would be wrong here, that's for downsampling).
  3. GHA (EPSG:5778) -> EGM2008 correction on a coarse grid within the
     block, bilinearly interpolated to the block's full resolution (same
     smooth-over-kilometres justification as before - unchanged by grid
     resolution). Coordinates are in EPSG:31287 here, so the coarse grid
     is reprojected to WGS84 lon/lat before calling vertical_datum
     (which expects lon/lat) - this is new; the previous CopDEM-grid
     version's blocks were already in EPSG:4326. GHA, not EVRF2000
     Austria: corrected after the user questioned the original instructed
     assumption - BEV's own documentation for this product line states
     GHA ("Adria Triest", EPSG:5778) as its vertical reference, a
     genuinely different system from EVRF2000 Austria (the obstacle
     data's datum) - see vertical_datum.py and docs/lidar_comparison.md.
  4. diff = CopDEM - (LiDAR + correction), same sign convention as
     error_single_m and the previous raster version.

NO sanity clip in this version (an earlier version clipped |diff| > 100m
to nodata). Removed after a real finding: near Grossglockner (Austria's
highest peak, 3798m), a pixel with a genuine, verified -124.3m CopDEM
error (InSAR-derived DEMs like CopDEM are known to have large errors on
steep peaks/ridgelines from radar layover/foreshortening - confirmed by
reading the actual CopDEM and LiDAR values at that pixel, not assumed)
was being silently erased as a "hole" by the clip. The clip was
originally added for a different, unrelated reason (a genuine artifact
where the GHA correction grid produces implausible values OUTSIDE
Austria's real border) - but since LiDAR itself only has data WITHIN
Austria, and the correction grid is only unreliable OUTSIDE Austria,
those two conditions shouldn't co-occur at any pixel that actually has
LiDAR data - so removing the clip should be safe in practice, not just
convenient. See docs/lidar_comparison.md for the full story. If wild
values ever do reappear, the fix is a proper Austria-border mask, not a
blunt value threshold.

Output: ONE GeoTIFF (data/dem_diff_lidar_10m.tif), tiled + compressed +
with overviews for fast QGIS rendering — no VRT-mosaic trick needed this
time, since (unlike the 40 misaligned CopDEM chunks before) there's now
exactly one output grid.
"""
from pathlib import Path

import _rasterio_compat  # noqa: F401
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window, transform as window_transform

from vertical_datum import EGM2008, SOURCE_VERTICAL_CRS, ellipsoidal_to_geoid, geoid_to_ellipsoidal

ROOT_DIR = Path(__file__).parent.parent
COPDEM_VRT_PATH = ROOT_DIR / "data" / "dem_mosaic.vrt"
LIDAR_PATH = ROOT_DIR / "data" / "dem_tiles" / "austria_localDEM" / "dhm_at_lamb_10m_2018.tif"
OUTPUT_PATH = ROOT_DIR / "data" / "dem_diff_lidar_10m.tif"

COUNTRY_VERTICAL_EPSG = SOURCE_VERTICAL_CRS["AT_LIDAR_DHM"]  # GHA (EPSG:5778) - see vertical_datum.py
COARSE_GRID_STEP_PX = 150  # ~1.5km spacing at 10m resolution - same physical spacing as before
BLOCK_SIZE = 2048  # pixels per side, per processing block

_to_wgs84 = Transformer.from_crs("EPSG:31287", "EPSG:4326", always_xy=True)


def _correction_grid_31287(block_transform, height, width):
    """Same coarse-grid + bilinear-interpolation approach as the previous
    version, adapted for a source transform in EPSG:31287 (not 4326) -
    coordinates are converted to WGS84 lon/lat before the vertical_datum
    calls, which expect lon/lat."""
    from scipy.interpolate import RegularGridInterpolator

    rows_coarse = np.arange(0, height, COARSE_GRID_STEP_PX)
    if rows_coarse[-1] != height - 1:
        rows_coarse = np.append(rows_coarse, height - 1)
    cols_coarse = np.arange(0, width, COARSE_GRID_STEP_PX)
    if cols_coarse[-1] != width - 1:
        cols_coarse = np.append(cols_coarse, width - 1)

    rr, cc = np.meshgrid(rows_coarse, cols_coarse, indexing="ij")
    xs, ys = rasterio.transform.xy(block_transform, rr.ravel(), cc.ravel())
    lons, lats = _to_wgs84.transform(np.array(xs), np.array(ys))
    zeros = np.zeros_like(lons)

    h_ellip = geoid_to_ellipsoidal(lons, lats, zeros, COUNTRY_VERTICAL_EPSG)
    correction = ellipsoidal_to_geoid(lons, lats, h_ellip, EGM2008)
    correction_grid = correction.reshape(rr.shape)

    interpolator = RegularGridInterpolator(
        (rows_coarse, cols_coarse), correction_grid, bounds_error=False, fill_value=None
    )
    full_rows, full_cols = np.meshgrid(np.arange(height), np.arange(width), indexing="ij")
    points = np.stack([full_rows.ravel(), full_cols.ravel()], axis=1)
    return interpolator(points).reshape(height, width)


def run(lidar_path=LIDAR_PATH, copdem_vrt_path=COPDEM_VRT_PATH, output_path=OUTPUT_PATH,
        limit_written_blocks=None, row_range=None):
    """limit_written_blocks/row_range: for testing on a subset before a full
    run - not used in normal operation (both None)."""
    with rasterio.open(lidar_path) as lidar_src, rasterio.open(copdem_vrt_path) as copdem_src:
        with WarpedVRT(copdem_src, crs=lidar_src.crs, transform=lidar_src.transform,
                        width=lidar_src.width, height=lidar_src.height,
                        resampling=Resampling.bilinear, src_nodata=np.nan, nodata=np.nan) as copdem_warped:

            profile = lidar_src.profile.copy()
            profile.update(dtype="float32", nodata=np.nan, compress="deflate",
                            tiled=True, blockxsize=256, blockysize=256, bigtiff="YES")

            height, width = lidar_src.height, lidar_src.width
            row_start, row_end = row_range if row_range else (0, height)
            n_blocks_total = ((height + BLOCK_SIZE - 1) // BLOCK_SIZE) * ((width + BLOCK_SIZE - 1) // BLOCK_SIZE)
            block_i = 0
            written_blocks = 0

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(output_path, "w", **profile) as dst:
                for row_off in range(row_start, row_end, BLOCK_SIZE):
                    h = min(BLOCK_SIZE, height - row_off)
                    for col_off in range(0, width, BLOCK_SIZE):
                        if limit_written_blocks is not None and written_blocks >= limit_written_blocks:
                            break
                        w = min(BLOCK_SIZE, width - col_off)
                        block_i += 1
                        window = Window(col_off, row_off, w, h)

                        lidar_block = lidar_src.read(1, window=window, masked=True)
                        if lidar_block.mask.all():
                            continue  # no LiDAR coverage in this block - leave as nodata

                        copdem_block = copdem_warped.read(1, window=window)
                        if np.all(np.isnan(copdem_block)):
                            continue

                        block_tf = window_transform(window, lidar_src.transform)
                        correction = _correction_grid_31287(block_tf, h, w)

                        lidar_valid = ~lidar_block.mask
                        lidar_filled = np.ma.filled(lidar_block.astype("float64"), np.nan)
                        lidar_egm2008 = lidar_filled + correction

                        diff = copdem_block.astype("float64") - lidar_egm2008
                        diff = np.where(lidar_valid, diff, np.nan).astype("float32")

                        if np.all(np.isnan(diff)):
                            continue

                        dst.write(diff, 1, window=window)
                        written_blocks += 1

                        if block_i % 20 == 0 or block_i == n_blocks_total:
                            print(f"  block {block_i}/{n_blocks_total} "
                                  f"({written_blocks} with data so far)", flush=True)

                print("building overviews...", flush=True)
                dst.build_overviews([4, 8, 16, 32, 64], Resampling.average)
                dst.update_tags(ns="rio_overview", resampling="average")

    print(f"wrote {output_path} ({written_blocks}/{n_blocks_total} blocks had data)")
    return output_path


if __name__ == "__main__":
    run()
