#!/usr/bin/env python3
"""Build two rasters over Montenegro, on the same grid as the CopDEM mosaic
(dem_mosaic_montenegro.vrt, EPSG:4326, native ~30m CopDEM resolution):

  1. data/egm96_egm2008_undulation_montenegro.tif — the EGM2008-minus-EGM96
     geoid separation N(lon, lat), in metres, at every CopDEM pixel. This IS
     the "how much does it matter which geoid you use" layer — it directly
     shows the magnitude of the correction that was needed for Montenegro's
     obstacle comparison (see vertical_datum.py / docs/montenegro.md: the
     obstacle data set's practical vertical reference is EGM96, per SMATSA's
     own AIP GEN 2.1, while CopDEM's native reference is EGM2008).
  2. data/dem_mosaic_montenegro_egm96.tif — CopDEM's own elevation values,
     recalculated from native EGM2008 to EGM96, i.e. CopDEM_EGM96 =
     CopDEM_EGM2008 - N(lon, lat). This is what CopDEM would read if it were
     natively published on the same geoid as the obstacle data.

MATHEMATICAL BASIS (same principle already established and used in
vertical_datum.py / build_lidar_diff_raster.py — restated here since this
script is the first to apply it as a standalone, visualizable raster in its
own right rather than as an internal per-point optimization):

Geoid undulation N(lon, lat) is a function of POSITION ONLY, not of height —
a compound-CRS geoid<->ellipsoidal transform is (to within the sub-mm
precision that matters here) a pure ADDITIVE shift:
    h_ellipsoidal = h_geoid + N(lon, lat)
So converting a height from geoid A to geoid B is:
    h_B = h_A + N_A(lon,lat) - N_B(lon,lat) = h_A + correction(lon,lat)
where correction(lon,lat) does NOT depend on h_A itself. That means
correction(lon,lat) can be computed ONCE per position with an arbitrary
input height (0.0 here) and then reused for every pixel at that position
regardless of that pixel's actual elevation — exactly what
vertical_datum.to_egm2008(lon, lat, 0.0, EGM96) computes below.

PERFORMANCE: calling pyproj per full-resolution pixel (5727x7050 =
~40M pixels) would be far too slow. Geoid undulation is an extremely
smooth, low-frequency spatial signal (wavelength of many km) — nothing like
terrain elevation — so it is computed on a COARSE grid (every
COARSE_STRIDE_PX native pixels, ~3km spacing) and then bilinearly
upsampled to the full CopDEM grid with scipy.ndimage.zoom(order=1). This is
the same coarse-grid-plus-interpolation optimization already used in
build_lidar_diff_raster.py for the GHA->EGM2008 correction, applied here to
EGM96->EGM2008 instead.
"""
import sys
from pathlib import Path

import numpy as np
from scipy.ndimage import zoom

import _rasterio_compat  # noqa: F401
import rasterio

sys.path.insert(0, str(Path(__file__).parent))
from vertical_datum import to_egm2008, EGM96

ROOT_DIR = Path(__file__).parent.parent
COPDEM_VRT = ROOT_DIR / "data" / "dem_mosaic_montenegro.vrt"
UNDULATION_TIF = ROOT_DIR / "data" / "egm96_egm2008_undulation_montenegro.tif"
COPDEM_EGM96_TIF = ROOT_DIR / "data" / "dem_mosaic_montenegro_egm96.tif"

COARSE_STRIDE_PX = 100  # ~100 native CopDEM pixels ~= 3km at this latitude


def _build_coarse_grid(transform, width, height, stride):
    """Return (coarse_correction, coarse_rows, coarse_cols) — the undulation
    correction evaluated at a coarse subgrid of pixel centres, plus the
    (row, col) subgrid indices it was evaluated at (so the zoom factor can be
    computed exactly, including the ragged last row/column)."""
    coarse_rows = list(range(0, height, stride))
    if coarse_rows[-1] != height - 1:
        coarse_rows.append(height - 1)
    coarse_cols = list(range(0, width, stride))
    if coarse_cols[-1] != width - 1:
        coarse_cols.append(width - 1)

    n_pts = len(coarse_rows) * len(coarse_cols)
    print(f"Evaluating EGM96->EGM2008 correction on a {len(coarse_rows)}x{len(coarse_cols)} "
          f"coarse grid ({n_pts:,} points)...")

    grid = np.empty((len(coarse_rows), len(coarse_cols)), dtype=np.float64)
    for i, row in enumerate(coarse_rows):
        lat = transform.f + (row + 0.5) * transform.e
        for j, col in enumerate(coarse_cols):
            lon = transform.c + (col + 0.5) * transform.a
            # correction(lon,lat) = EGM2008 - EGM96 at this position, height-
            # independent (see module docstring) - evaluated at h=0.0
            # WLOG.
            grid[i, j] = to_egm2008(lon, lat, 0.0, EGM96)
        if i % 20 == 0 or i == len(coarse_rows) - 1:
            print(f"  row {i + 1}/{len(coarse_rows)}")
    return grid, coarse_rows, coarse_cols


def _upsample_to_full_grid(coarse_grid, coarse_rows, coarse_cols, width, height):
    """Bilinear-upsample the coarse correction grid to the full (height,
    width) CopDEM grid. Uses zoom factors derived from the ACTUAL coarse
    sample positions (which include a ragged last row/col to cover the
    full extent exactly), not just stride, so the upsampled grid lines up
    with the true full-resolution pixel grid rather than being off by the
    fractional remainder at the edges."""
    zoom_row = (height) / len(coarse_rows)
    zoom_col = (width) / len(coarse_cols)
    upsampled = zoom(coarse_grid, (zoom_row, zoom_col), order=1, mode="nearest")
    # zoom's output size can be off by a pixel or two from rounding - crop or
    # edge-pad to match exactly.
    out = np.empty((height, width), dtype=np.float32)
    h_copy = min(height, upsampled.shape[0])
    w_copy = min(width, upsampled.shape[1])
    out[:h_copy, :w_copy] = upsampled[:h_copy, :w_copy]
    if h_copy < height:
        out[h_copy:, :] = out[h_copy - 1, :]
    if w_copy < width:
        out[:, w_copy:] = out[:, w_copy - 1:w_copy]
    return out


def build():
    with rasterio.open(COPDEM_VRT) as src:
        width, height = src.width, src.height
        transform, crs = src.transform, src.crs
        profile = src.profile.copy()

        coarse_grid, coarse_rows, coarse_cols = _build_coarse_grid(transform, width, height, COARSE_STRIDE_PX)
        print(f"Coarse correction range: {coarse_grid.min():.4f} to {coarse_grid.max():.4f} m "
              f"(mean {coarse_grid.mean():.4f} m) - smooth low-frequency signal, as expected.")

        correction = _upsample_to_full_grid(coarse_grid, coarse_rows, coarse_cols, width, height)

        profile.update(driver="GTiff", dtype="float32", nodata=np.nan,
                        compress="deflate", predictor=3, tiled=True,
                        blockxsize=256, blockysize=256)

        UNDULATION_TIF.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(UNDULATION_TIF, "w", **profile) as dst:
            dst.write(correction, 1)
        print(f"wrote {UNDULATION_TIF}")

        # CopDEM recalculated to EGM96: EGM2008 = EGM96 + correction, so
        # EGM96 = EGM2008 - correction. Process in blocks to avoid holding
        # the whole ~40M-pixel array (plus CopDEM's own data) in memory
        # twice at once.
        with rasterio.open(COPDEM_EGM96_TIF, "w", **profile) as dst:
            for _, window in src.block_windows(1):
                block = src.read(1, window=window)
                row_off, col_off = window.row_off, window.col_off
                corr_block = correction[row_off:row_off + window.height, col_off:col_off + window.width]
                out_block = np.where(np.isnan(block), np.nan, block - corr_block).astype(np.float32)
                dst.write(out_block, 1, window=window)
        print(f"wrote {COPDEM_EGM96_TIF}")

    return UNDULATION_TIF, COPDEM_EGM96_TIF


if __name__ == "__main__":
    build()
