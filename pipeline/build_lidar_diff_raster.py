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

--------------------------------------------------------------------------
REVIEWED (2026-08-11): geoid-correction math double-checked by hand, see
the derivation in _correction_grid_31287()'s docstring below. Verdict:
correct. Confirmed independently three ways: (1) algebraic derivation
from how PROJ grid-shift vertical transforms actually work, (2) matches
every previously-verified test point (Vienna/Tyrol/Graz, GHA vs EVRF2000
self-test in vertical_datum.py), (3) matches the Grossglockner pixel's
hand-computed value to within 0.1 m. Two minor, non-live edge cases noted
inline where they occur - neither affects this raster's actual dimensions.
--------------------------------------------------------------------------
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
COPDEM_VRT_PATH = ROOT_DIR / "data" / "dem_mosaic.vrt"          # 40-chunk CopDEM mosaic, EPSG:4326, native EGM2008 heights
LIDAR_PATH = ROOT_DIR / "data" / "dem_tiles" / "austria_localDEM" / "dhm_at_lamb_10m_2018.tif"  # EPSG:31287, GHA heights
OUTPUT_PATH = ROOT_DIR / "data" / "dem_diff_lidar_10m.tif"

# Which vertical CRS LiDAR's raw values are actually in - GHA (EPSG:5778),
# NOT EVRF2000 Austria. Looked up once here so the rest of the file just
# says "the LiDAR datum" without repeating the EPSG number everywhere.
COUNTRY_VERTICAL_EPSG = SOURCE_VERTICAL_CRS["AT_LIDAR_DHM"]  # GHA (EPSG:5778) - see vertical_datum.py

# Geoid/quasigeoid undulation is smooth over kilometres (confirmed: at most
# ~2.5m of change across the whole of Tyrol - see vertical_datum.py), so
# sampling every COARSE_GRID_STEP_PX pixels and bilinearly interpolating
# between samples is accurate enough - and vastly cheaper than calling the
# PROJ transform machinery once per pixel (millions of calls per block).
COARSE_GRID_STEP_PX = 150  # ~1.5km spacing at 10m resolution - same physical spacing as before

# How big a chunk of the raster to hold in memory at once. The full grid
# (58,061 x 31,793 = ~1.85 billion pixels) can't be processed as one array;
# 2048x2048 (~4.2M pixels, ~34MB as float64) is a comfortable working size.
BLOCK_SIZE = 2048  # pixels per side, per processing block

# Horizontal-only reprojection: EPSG:31287 (LiDAR's CRS, MGI datum) ->
# EPSG:4326 (WGS84 lon/lat), needed ONLY so we know which (lon, lat) to feed
# into the vertical_datum geoid-lookup functions below, which expect WGS84
# coordinates. This is a separate concern from the vertical conversion - the
# MGI->WGS84 horizontal datum shift here is on the order of a few metres,
# utterly negligible against a geoid-undulation surface that only changes by
# decimetres over kilometres, so any imprecision here has no measurable
# effect on the correction values computed downstream.
_to_wgs84 = Transformer.from_crs("EPSG:31287", "EPSG:4326", always_xy=True)


def _correction_grid_31287(block_transform, height, width):
    """Compute the GHA -> EGM2008 vertical correction (metres to ADD to a
    raw GHA height to get its EGM2008 equivalent) across an entire block,
    without calling the PROJ transform once per pixel.

    THE KEY TRICK, worked through explicitly (this is the part worth
    double-checking, so here's the derivation rather than just the claim):

    A geoid-referenced height converts to WGS84 ellipsoidal height as
        h_ellipsoidal = h_geoid + N(lon, lat)
    where N is the geoid/quasigeoid undulation - a grid-interpolated value
    that depends ONLY on horizontal position, never on the height being
    converted. (This is how PROJ's vertical grid-shift transforms work
    generally, not something specific to this dataset.) Chaining GHA ->
    ellipsoidal -> EGM2008 through vertical_datum's two functions:

        h_ellipsoidal      = h_GHA + N_GHA(lon, lat)
        h_EGM2008           = h_ellipsoidal - N_EGM2008(lon, lat)
                             = h_GHA + [N_GHA(lon, lat) - N_EGM2008(lon, lat)]

    The bracketed term is a pure function of (lon, lat) - it does NOT
    depend on h_GHA at all. So feeding height=0 through exactly the same
    two-step conversion returns that bracketed term directly:

        to_egm2008-style(lon, lat, 0, GHA) = 0 + [N_GHA(lon,lat) - N_EGM2008(lon,lat)]
                                            = the correction, alone

    That's what this function returns per grid point. Adding it to a REAL
    LiDAR value elsewhere (`lidar_filled + correction` in run()) is then
    algebraically identical to calling the full conversion on that real
    value - just computed once per coarse grid point instead of once per
    pixel. Verified against vertical_datum.py's own GHA-vs-EVRF2000
    self-test and against a hand-checked pixel near Grossglockner (matched
    to within 0.1 m) - see the module docstring above.

    Coordinates here are in EPSG:31287 (the block's own CRS), so each
    coarse grid point is reprojected to WGS84 lon/lat first - vertical_datum's
    functions expect lon/lat, not easting/northing.
    """
    from scipy.interpolate import RegularGridInterpolator

    # Build a coarse (row, col) sample grid spanning the WHOLE block,
    # always including the last row/col exactly (not just every Nth pixel
    # from the top-left) so the interpolator never has to extrapolate past
    # the block's true edges.
    rows_coarse = np.arange(0, height, COARSE_GRID_STEP_PX)
    if rows_coarse[-1] != height - 1:
        rows_coarse = np.append(rows_coarse, height - 1)
    cols_coarse = np.arange(0, width, COARSE_GRID_STEP_PX)
    if cols_coarse[-1] != width - 1:
        cols_coarse = np.append(cols_coarse, width - 1)
    # EDGE CASE (not live in this raster's actual dimensions, noted for
    # future robustness): if a block were ever only 1 pixel tall or wide
    # (possible in principle for a truncated final row/col block, though
    # this raster's real last-block sizes are 1073 and 717 px - nowhere
    # near 1), rows_coarse/cols_coarse would end up length 1, and whether
    # RegularGridInterpolator accepts a single-point axis depends on the
    # scipy version. Not an issue here; would need a guard if BLOCK_SIZE or
    # the source raster's dimensions ever changed to make it possible.

    # Coarse grid's (row, col) -> (x, y) in EPSG:31287 -> (lon, lat) in WGS84.
    rr, cc = np.meshgrid(rows_coarse, cols_coarse, indexing="ij")
    xs, ys = rasterio.transform.xy(block_transform, rr.ravel(), cc.ravel())
    lons, lats = _to_wgs84.transform(np.array(xs), np.array(ys))
    zeros = np.zeros_like(lons)  # the "feed height=0" trick from the docstring above

    # geoid_to_ellipsoidal/ellipsoidal_to_geoid both accept array inputs
    # (numpy-vectorized under the hood via pyproj) - this is one batched
    # PROJ call per step for the whole coarse grid, not one call per point.
    h_ellip = geoid_to_ellipsoidal(lons, lats, zeros, COUNTRY_VERTICAL_EPSG)
    correction = ellipsoidal_to_geoid(lons, lats, h_ellip, EGM2008)
    correction_grid = correction.reshape(rr.shape)  # back to (n_rows_coarse, n_cols_coarse)

    # Bilinear interpolation from the coarse (row, col) grid to every
    # (row, col) in the full block. bounds_error=False/fill_value=None
    # permit extrapolation, but in practice never need to: rows_coarse/
    # cols_coarse always include 0 and height-1/width-1 (enforced above),
    # so every query point in full_rows/full_cols falls strictly inside
    # the sampled range - this is defensive, not load-bearing.
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
        # WarpedVRT: a "virtual" reprojected view of the CopDEM mosaic that
        # LOOKS like it's already on LiDAR's exact grid (same CRS, same
        # transform, same width/height) - reading a window from it triggers
        # GDAL to reproject+resample just that window on the fly. This is
        # what lets the SAME Window object below correctly read matching,
        # pixel-aligned data from both LiDAR (native) and CopDEM (warped) -
        # no separate per-source coordinate math needed per block.
        # resampling=bilinear because this is an UPSAMPLE (CopDEM's native
        # ~30m cells -> LiDAR's 10m grid, i.e. going to MORE pixels than
        # CopDEM naturally has) - bilinear/cubic interpolate sensibly for
        # that direction. Resampling.average (used elsewhere in this
        # project for the opposite, downsampling direction) would be wrong
        # here - it aggregates multiple source cells per destination cell,
        # which doesn't apply when there's less than one source cell per
        # destination cell to begin with.
        with WarpedVRT(copdem_src, crs=lidar_src.crs, transform=lidar_src.transform,
                        width=lidar_src.width, height=lidar_src.height,
                        resampling=Resampling.bilinear, src_nodata=np.nan, nodata=np.nan) as copdem_warped:

            # Output profile: copy LiDAR's own (CRS, transform, width,
            # height) so the output shares its exact grid, then override
            # just the parts that differ (float32 diff values instead of
            # LiDAR's own dtype, NaN nodata, tiled+compressed for size and
            # for QGIS's sake, bigtiff since the uncompressed size exceeds
            # the classic TIFF 4GB addressing limit).
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
                    h = min(BLOCK_SIZE, height - row_off)  # last row of blocks is shorter than BLOCK_SIZE
                    for col_off in range(0, width, BLOCK_SIZE):
                        if limit_written_blocks is not None and written_blocks >= limit_written_blocks:
                            break
                        w = min(BLOCK_SIZE, width - col_off)  # last column of blocks is narrower than BLOCK_SIZE
                        block_i += 1
                        window = Window(col_off, row_off, w, h)

                        # Cheap check FIRST, before the expensive CopDEM
                        # reproject: if this block has no LiDAR data at all
                        # (outside Austria, or a data gap), there's nothing
                        # to compute a difference against - skip immediately
                        # rather than paying for a warp that would be
                        # discarded anyway. This is why "outside coverage"
                        # blocks are fast even though the raster is huge.
                        lidar_block = lidar_src.read(1, window=window, masked=True)
                        if lidar_block.mask.all():
                            continue  # no LiDAR coverage in this block - leave as nodata

                        # Now do the expensive part: reproject+resample the
                        # matching CopDEM window via the WarpedVRT.
                        copdem_block = copdem_warped.read(1, window=window)
                        if np.all(np.isnan(copdem_block)):
                            continue  # CopDEM has no data here either (e.g. outside its fetched extent)

                        # This block's own (row,col)->(x,y) affine transform
                        # in EPSG:31287 - needed so the correction grid
                        # samples the right real-world locations, not (0,0)-
                        # relative block-local coordinates.
                        block_tf = window_transform(window, lidar_src.transform)
                        correction = _correction_grid_31287(block_tf, h, w)

                        # lidar_block is a numpy MASKED array (masked=True
                        # above); `.mask` is True where nodata. Convert to a
                        # plain float64 array with NaN standing in for
                        # nodata, so ordinary arithmetic (not masked-array
                        # arithmetic) can be used below.
                        lidar_valid = ~lidar_block.mask
                        lidar_filled = np.ma.filled(lidar_block.astype("float64"), np.nan)

                        # THE ACTUAL DATUM CONVERSION: add the per-pixel
                        # correction (GHA -> EGM2008 offset) to the raw GHA
                        # LiDAR values - see the derivation in
                        # _correction_grid_31287()'s docstring for why this
                        # plain addition is mathematically exact, not an
                        # approximation.
                        lidar_egm2008 = lidar_filled + correction

                        # The actual difference: CopDEM minus LiDAR, both
                        # now on EGM2008. Positive = CopDEM reads above
                        # LiDAR - same sign convention as error_single_m
                        # elsewhere in this project. NaN propagates
                        # automatically wherever copdem_block is NaN (IEEE
                        # float arithmetic), so only the LiDAR-side mask
                        # needs to be applied explicitly below.
                        diff = copdem_block.astype("float64") - lidar_egm2008
                        diff = np.where(lidar_valid, diff, np.nan).astype("float32")

                        if np.all(np.isnan(diff)):
                            continue  # everything masked out after all - nothing to write

                        dst.write(diff, 1, window=window)
                        written_blocks += 1

                        if block_i % 20 == 0 or block_i == n_blocks_total:
                            print(f"  block {block_i}/{n_blocks_total} "
                                  f"({written_blocks} with data so far)", flush=True)

                # Pyramids for fast QGIS rendering at low zoom - built once,
                # after all blocks are written, not per-block.
                print("building overviews...", flush=True)
                dst.build_overviews([4, 8, 16, 32, 64], Resampling.average)
                dst.update_tags(ns="rio_overview", resampling="average")

    print(f"wrote {output_path} ({written_blocks}/{n_blocks_total} blocks had data)")
    return output_path


if __name__ == "__main__":
    run()
