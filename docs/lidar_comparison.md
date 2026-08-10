# Austria LiDAR DEM comparison — design decisions and omissions

Scope: [`pipeline/extract_lidar.py`](../pipeline/extract_lidar.py) (obstacle
points vs. LiDAR) and [`pipeline/build_lidar_diff_raster.py`](../pipeline/build_lidar_diff_raster.py)
(CopDEM vs. LiDAR raster, whole-coverage). Both compare Copernicus DEM
GLO-30 against Austria's national LiDAR-derived DHM.

## The source

`data/dem_tiles/austria_localDEM/dhm_at_lamb_10m_2018.tif` — already
present locally (not sourced by this pipeline; the user supplied it
directly). Inspected, not assumed:

- CRS: **EPSG:31287** (MGI / Austria Lambert)
- Resolution: **10 m**, full Austria coverage (58,061 × 31,793 px)
- float32, properly tiled (256×256 blocks), deflate-compressed — windowed
  reads are efficient despite the ~2 GB file size
- nodata: standard float32 sentinel (`-3.4028...e38`)
- Sampled values are plausible Alpine-foothill elevations (~1240 m mean at
  a central-Austria test window)

## Vertical reference: corrected after being questioned — read this section

**This datum decision has a real history worth knowing before trusting any
LiDAR number in this project**, because it was wrong for a while.

**Round 1 (instructed assumption):** the LiDAR DEM was assumed to use the
same EVRF2000 Austria height system (EPSG:9274) as the obstacle data,
per explicit instruction — not independently confirmed the way every
other datum decision in this project was.

**Round 2 (the user questioned it):** asked whether the file's horizontal
CRS, EPSG:31287 (MGI / Austria Lambert), had any bearing on the vertical
assumption. Worth being precise about the answer: **EPSG:31287 is a
horizontal-only CRS** — it doesn't specify a vertical datum by itself, so
on its own it neither confirms nor contradicts EVRF2000 Austria. But the
question was the right prompt to actually go check, rather than continue
assuming.

**Round 3 (checked, and the assumption was wrong):** BEV's (Austria's
official surveying authority) own product page for the "Digitales
Geländehöhenmodell — Höhenraster" — the same national 10 m Lambert-
projected LiDAR-DHM product line as this file — states its vertical
reference explicitly:

- **Vertical: "Adria Triest" — GHA height, EPSG:5778** (a legacy, practical
  Austrian height system based on the Trieste tide gauge)
- Horizontal: MGI / Austria Lambert (EPSG:31287) — matches this file exactly

GHA is **not** EVRF2000 Austria. There is an official EPSG grid-based
transformation between them (EPSG:9275, "GHA height to EVRF2000 Austria
height"), which by itself proves they're not interchangeable — if they
were the same thing, no transform would be registered. Confirmed
numerically (`vertical_datum.py`'s self-test): at three test points,
GHA→EGM2008 differs from EVRF2000-Austria→EGM2008 by **−0.47 m, +0.12 m,
and −0.24 m** — real, sub-meter shifts, not negligible against this
project's few-metre error scale.

**What's still not independently confirmed**: this is a match to BEV's
*general product line description*, not to metadata embedded in this
specific file. The match is strong circumstantial evidence (same
resolution, same projection, same national product family) but isn't the
same tier of certainty as reading a datum statement directly out of the
file's own metadata. If a stronger source ever turns up (e.g. metadata
embedded in the GeoTIFF itself, or a delivery note specific to this file),
revisit this.

**All LiDAR-derived numbers in this project were recomputed** after this
correction — the obstacle-vs-LiDAR comparison (`extract_lidar.py`), the
CopDEM-vs-LiDAR raster (`build_lidar_diff_raster.py`), and both reports
that depend on them.

Conversion uses the same `vertical_datum.py` machinery as everywhere else:
source datum → WGS84 ellipsoidal → EGM2008, position-dependent, via
`pyproj` compound-CRS transforms. See `SOURCE_VERTICAL_CRS["AT_LIDAR_DHM"]`
(GHA, EPSG:5778) vs. `SOURCE_VERTICAL_CRS["AT"]` (EVRF2000 Austria,
EPSG:9274, still correct for the obstacle data — these are deliberately
separate registry entries for two different Austrian sources with two
different datums, not the same key).

## Obstacle-to-LiDAR comparison (`extract_lidar.py`)

Mirrors `extract_dem.py`'s single-cell (bilinear) + 5×5-window
(min/median/mean/std) methodology exactly, applied to the LiDAR raster
instead of Copernicus DEM. "5×5 cells" means 5×5 in each raster's own
native grid — 150 m × 150 m for CopDEM's ~30 m cells, but only
**50 m × 50 m** for LiDAR's 10 m cells. This is "the same way" in
methodology (same algorithm, same statistics), not the same physical
window size.

New columns added to `obstacles_dem_diff.csv` in place (not a separate
file — see [output_fields.md](output_fields.md) for the full field list):
`lidar_single_egm2008_m`, `error_single_lidar_m`,
`lidar_5x5_{min,median,mean,std}_egm2008_m`,
`error_5x5_{min,median,mean}_lidar_m`, `capture_signal_lidar_m` — same
naming pattern and sign convention as the CopDEM columns
(`error = raster value − obstacle base elevation`, both on EGM2008),
just with `_lidar` where needed to disambiguate.

**Result** (1932/1932 obstacles matched, no coverage gaps — LiDAR covers
all of Austria, unlike CopDEM's chunk-edge gaps), **with the corrected GHA
datum**:

| Metric | mean | median | stdev |
|---|---|---|---|
| `error_single_lidar_m` (LiDAR vs. obstacle base) | −0.20 m | −0.03 m | 6.39 m |
| `error_5x5_median_lidar_m` (LiDAR vs. obstacle base, window) | −1.08 m | −0.74 m | 6.47 m |
| `error_single_m` (CopDEM vs. obstacle base, for comparison) | +5.25 m | +4.22 m | 8.77 m |

LiDAR's mean bias against obstacle base elevation is still close to zero
(as expected of a survey-grade product — this project's earlier finding
that CopDEM's ~5 m bias is attributable to CopDEM itself, not an upstream
obstacle-pipeline error, still holds), but shifted slightly negative from
the pre-correction values (+0.07 m / −0.8 m) by roughly the same
sub-metre amount found in the datum self-test above — consistent, not
alarming.

## CopDEM-vs-LiDAR difference raster (`build_lidar_diff_raster.py`)

**Redone on a 10 m grid** (an earlier version output on CopDEM's coarser
~30 m grid, downsampling LiDAR via averaging — the opposite direction).
This version keeps LiDAR's own native 10 m detail untouched and upsamples
CopDEM onto it instead:

1. **LiDAR read directly, at full native resolution — never resampled.**
   It's the higher-detail source; the whole point of the 10 m output is to
   preserve what it actually shows.
2. **CopDEM reprojected onto LiDAR's exact grid via a `WarpedVRT`** over
   `data/dem_mosaic.vrt` (the existing 40-chunk mosaic), `Resampling.
   bilinear` — this is an *upsample* (~30 m → 10 m), so bilinear (not
   `average`, which is for downsampling) is the right interpolation.
   Using a `WarpedVRT` over the whole-country mosaic means one continuous
   reproject instead of 40 separate per-chunk warps — there's now a single
   unambiguous target grid (LiDAR's own), unlike the previous version's
   need to warp LiDAR onto 40 different native CopDEM grids individually.
3. **GHA → EGM2008 correction on a coarse grid** (every 150 px, ~1.5 km at
   10 m resolution — same physical spacing as the previous version's
   coarse grid, just more pixels between samples at the finer resolution),
   bilinearly interpolated to full block resolution. Block coordinates are
   in EPSG:31287, so the coarse grid is reprojected to WGS84 lon/lat before
   calling `vertical_datum` (which expects lon/lat).
4. `diff = CopDEM − (LiDAR + correction)` — same subtraction convention as
   `error_single_m` (positive = CopDEM reads above LiDAR).
5. **Sanity clip**: `|diff| > 100 m` → nodata. Same defensive guard as the
   previous version, for the same real reason: the national vertical-datum
   grid produces implausible values outside Austria's actual border, even
   within a block that's otherwise inside CopDEM's/LiDAR's rectangular
   extent. LiDAR's own nodata mask already excludes non-Austria territory
   in practice, so this is a second layer, not the primary safeguard.

**Processing**: the full grid is 58,061 × 31,793 ≈ 1.85 billion pixels —
too large for one in-memory array, so it's processed in 2048×2048-pixel
blocks via windowed reads/writes, with blocks skipped early (before the
expensive CopDEM reproject) if their LiDAR window is entirely nodata.

**Output**: one file, `data/dem_diff_lidar_10m.tif` — tiled, deflate-
compressed, with overviews built (`[4, 8, 16, 32, 64]`, average
resampling) for fast QGIS rendering at low zoom. No VRT-mosaic trick
needed this time (unlike the 30 m version's 32-chunk mosaic) — there's
exactly one output grid now, not 40 misaligned CopDEM chunks to stitch.

## Explicit list of what this does NOT do

- Doesn't independently confirm the LiDAR DEM's vertical datum against
  metadata embedded in the file itself — see "Vertical reference" above.
  Matched to BEV's general product line, not this exact file's own
  metadata.
- Doesn't handle any horizontal datum discrepancy between EPSG:31287
  (MGI) and WGS84 beyond what `rasterio.warp.reproject`'s standard
  CRS-to-CRS transform provides — no separate MGI→WGS84 grid-based
  horizontal correction was investigated.
- The 100 m sanity clip is a blunt instrument (a fixed threshold, not a
  border-aware mask) — it happens to work because the artifact values
  it's guarding against are far larger than any real signal, but a more
  precise fix would clip to Austria's actual border polygon instead.
- No stratification of the raster diff by terrain slope, land cover, or
  region — it's the raw per-cell comparison (whole-country distribution
  stats are in the separate raster analysis report, also unstratified).
- LiDAR data year is 2018; Copernicus DEM's underlying acquisitions are
  from the TanDEM-X mission timeframe (~2011-2015) — no correction for
  the several-year gap between epochs (relevant mainly in
  actively-changing terrain: quarries, construction, glacier retreat).
