#!/usr/bin/env python3
"""Build a difference raster: Copernicus DEM GLO-30 minus Austria's LiDAR-
derived DHM (dhm_at_lamb_10m_2018.tif), both on EGM2008, at CopDEM's
native per-chunk grid. See docs/lidar_comparison.md for the full design
rationale, known limitations, and the vertical-datum assumption.

Per chunk (matching the same "sample from native source, never a
resampled mosaic" principle as extract_dem.py):
  1. Reproject the LiDAR raster (EPSG:31287, 10m) onto THIS chunk's exact
     grid (EPSG:4326, ~30m) via averaging (downsampling 10m -> ~30m).
  2. Compute the EVRF2000 Austria -> EGM2008 correction on a coarse grid
     across the chunk (geoid separation varies smoothly over kilometres,
     so a sparse grid + bilinear interpolation is a standard, justified
     simplification - not full-resolution point-by-point conversion,
     which would be needlessly slow for no accuracy gain).
  3. diff = CopDEM - (LiDAR_resampled + correction), same subtraction
     convention as error_single_m (positive = CopDEM reads above LiDAR).
  4. Sanity-clip |diff| > 100 m to nodata - defensive guard against the
     correction grid producing large, non-physical values outside
     Austria's real border (within a chunk's rectangular bbox but outside
     the EVRF2000 Austria grid's valid coverage) - see docs/lidar_comparison.md.
     In practice LiDAR's own nodata mask already excludes non-Austria
     territory, so this is a belt-and-braces check, not the primary guard.
"""
from pathlib import Path

import _rasterio_compat  # noqa: F401
import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject
from scipy.interpolate import RegularGridInterpolator

from build_dem_vrt import build_vrt
from vertical_datum import EGM2008, SOURCE_VERTICAL_CRS, ellipsoidal_to_geoid, geoid_to_ellipsoidal

ROOT_DIR = Path(__file__).parent.parent
DEM_DIR = ROOT_DIR / "data" / "dem_tiles"
LIDAR_PATH = ROOT_DIR / "data" / "dem_tiles" / "austria_localDEM" / "dhm_at_lamb_10m_2018.tif"
OUTPUT_DIR = ROOT_DIR / "data" / "dem_diff_lidar"
OUTPUT_VRT = ROOT_DIR / "data" / "dem_diff_lidar_mosaic.vrt"

COUNTRY_VERTICAL_EPSG = SOURCE_VERTICAL_CRS["AT"]
COARSE_GRID_STEP_PX = 50  # ~1.5km spacing at 30m resolution - geoid separation is smooth over km
SANITY_CLIP_M = 100  # |diff| beyond this is treated as an artifact, not real signal


def _chunk_files(dem_dir=DEM_DIR):
    return sorted(dem_dir.glob("dem_*.tif"))


def _correction_grid(transform, height, width):
    """EVRF2000 Austria -> EGM2008 correction (metres) at every (row, col),
    computed on a coarse grid and bilinearly interpolated to full
    resolution. geoid_to_ellipsoidal(...,0) + ellipsoidal_to_geoid(...)
    gives the pure positional offset (height cancels out - see
    extract_lidar.py's docstring for the same reasoning)."""
    rows_coarse = np.arange(0, height, COARSE_GRID_STEP_PX)
    if rows_coarse[-1] != height - 1:
        rows_coarse = np.append(rows_coarse, height - 1)
    cols_coarse = np.arange(0, width, COARSE_GRID_STEP_PX)
    if cols_coarse[-1] != width - 1:
        cols_coarse = np.append(cols_coarse, width - 1)

    rr, cc = np.meshgrid(rows_coarse, cols_coarse, indexing="ij")
    xs, ys = rasterio.transform.xy(transform, rr.ravel(), cc.ravel())
    lons, lats = np.array(xs), np.array(ys)
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


def process_chunk(chunk_path, lidar_src, output_dir=OUTPUT_DIR):
    with rasterio.open(chunk_path) as copdem_src:
        copdem = copdem_src.read(1, masked=True)
        transform = copdem_src.transform
        crs = copdem_src.crs
        height, width = copdem_src.shape

        lidar_resampled = np.full((height, width), np.nan, dtype="float32")
        reproject(
            source=rasterio.band(lidar_src, 1),
            destination=lidar_resampled,
            src_transform=lidar_src.transform,
            src_crs=lidar_src.crs,
            src_nodata=lidar_src.nodata,
            dst_transform=transform,
            dst_crs=crs,
            dst_nodata=np.nan,
            resampling=Resampling.average,
        )

        valid_lidar = ~np.isnan(lidar_resampled)
        if not valid_lidar.any():
            return None  # this chunk has no LiDAR coverage at all (outside Austria)

        correction = _correction_grid(transform, height, width)
        lidar_egm2008 = lidar_resampled + correction

        copdem_filled = np.ma.filled(copdem.astype("float64"), np.nan)
        diff = copdem_filled - lidar_egm2008
        diff = np.where(np.abs(diff) > SANITY_CLIP_M, np.nan, diff).astype("float32")
        diff = np.where(valid_lidar, diff, np.nan).astype("float32")

        if np.all(np.isnan(diff)):
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / chunk_path.name.replace("dem_", "diff_")
        profile = copdem_src.profile.copy()
        profile.update(dtype="float32", nodata=np.nan, compress="deflate")
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(diff, 1)
        return out_path


def run(dem_dir=DEM_DIR, lidar_path=LIDAR_PATH, output_dir=OUTPUT_DIR):
    chunks = _chunk_files(dem_dir)
    print(f"{len(chunks)} CopDEM chunks to process against {lidar_path.name}")
    written = []
    skipped = []
    with rasterio.open(lidar_path) as lidar_src:
        for i, chunk_path in enumerate(chunks, 1):
            out_path = process_chunk(chunk_path, lidar_src, output_dir)
            if out_path:
                written.append(out_path)
                print(f"  [{i}/{len(chunks)}] {chunk_path.name} -> {out_path.name}")
            else:
                skipped.append(chunk_path)
                print(f"  [{i}/{len(chunks)}] {chunk_path.name} -> skipped (no LiDAR coverage)")
    print(f"wrote {len(written)} diff chunks, skipped {len(skipped)} (outside LiDAR coverage)")

    if written:
        build_vrt(dem_dir=output_dir, output_vrt=OUTPUT_VRT, glob_pattern="diff_*.tif",
                  source_subdir=output_dir.name)
    return written


if __name__ == "__main__":
    run()
