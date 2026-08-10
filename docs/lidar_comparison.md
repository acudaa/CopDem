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

## Vertical reference: an instructed assumption, not an independent finding

**This is different from every other datum decision in this project.**
Everywhere else (Austria's obstacle data, Copernicus DEM), the vertical
reference was read from the source's own documentation and/or confirmed
numerically against independent literature before being trusted (see
[obstacle_ingestion.md](obstacle_ingestion.md) and
[vertical_datum.py](../pipeline/vertical_datum.py)). For the LiDAR DEM,
the vertical reference was **explicitly instructed**: assume it uses the
same EVRF2000 Austria height system (EPSG:9274) as the obstacle data. This
is a reasonable assumption — Austria's national DHM products are commonly
tied to the national height system — but it has **not** been independently
verified against the file's own metadata or documentation the way the
obstacle data's "EVRS" statement was. If this assumption turns out to be
wrong, every number in this comparison shifts by whatever the true
datum's separation from EVRF2000 Austria is at each location — flagging
this prominently so it's the first thing revisited if results ever look
systematically off.

Conversion uses the same `vertical_datum.py` machinery as everywhere else:
EVRF2000 Austria → WGS84 ellipsoidal → EGM2008, position-dependent, via
`pyproj` compound-CRS transforms.

## Part 4: obstacle-to-LiDAR comparison (`extract_lidar.py`)

Mirrors `extract_dem.py`'s single-cell (bilinear) + 5×5-window
(min/median/mean/std) methodology exactly, applied to the LiDAR raster
instead of Copernicus DEM. "5×5 cells" means 5×5 in each raster's own
native grid — 150 m × 150 m for CopDEM's ~30 m cells, but only
**50 m × 50 m** for LiDAR's 10 m cells. This is "the same way" in
methodology (same algorithm, same statistics), not the same physical
window size — flagging this explicitly since the two aren't
directly comparable on window footprint, only on the comparison logic
applied.

New columns added to `obstacles_dem_diff.csv` in place (not a separate
file — see [output_fields.md](output_fields.md) for the full field list):
`lidar_single_egm2008_m`, `error_single_lidar_m`,
`lidar_5x5_{min,median,mean,std}_egm2008_m`,
`error_5x5_{min,median,mean}_lidar_m`, `capture_signal_lidar_m` — same
naming pattern and sign convention as the CopDEM columns
(`error = raster value − obstacle base elevation`, both on EGM2008),
just with `_lidar` where needed to disambiguate.

**Result** (1932/1932 obstacles matched, no coverage gaps — LiDAR covers
all of Austria, unlike CopDEM's chunk-edge gaps):

| Metric | mean | median | stdev |
|---|---|---|---|
| `error_single_lidar_m` (LiDAR vs. obstacle base) | +0.07 m | +0.24 m | 6.40 m |
| `error_single_m` (CopDEM vs. obstacle base, for comparison) | +5.25 m | +4.22 m | 8.77 m |
| CopDEM − LiDAR (both vs. obstacle base, single-cell) | +5.18 m | +3.97 m | 6.39 m |

This is a strong internal-consistency signal, not just a plausible
number: LiDAR's near-zero mean bias against obstacle base elevation is
exactly what's expected of a survey-grade product, and it indicates the
obstacle base-elevation logic and datum conversion are sound — the
~5 m CopDEM bias seen throughout this project is attributable to CopDEM
itself, not to an error upstream in the obstacle pipeline. The third row
also cross-checks arithmetically against the first two (5.25 − 0.07 ≈
5.18) — confirms no computation mistake.

## Part 3: CopDEM-vs-LiDAR difference raster (`build_lidar_diff_raster.py`)

Per-chunk, matching the existing "sample from native source, never a
resampled mosaic" principle:

1. **Reproject LiDAR onto CopDEM's exact chunk grid** (not the reverse —
   CopDEM's per-chunk grid is the one this whole pipeline's numeric
   comparisons already anchor to). `Resampling.average`, since this
   downsamples LiDAR's finer 10 m cells into CopDEM's coarser ~30 m
   cells — each output cell averages the ~9 LiDAR cells it covers, the
   standard choice for downsampling (as opposed to nearest/bilinear,
   which would just pick or interpolate one/few source values rather
   than aggregate them).
2. **Geoid correction on a coarse grid, bilinearly interpolated to full
   resolution** — not full-resolution point-by-point conversion. Geoid/
   quasigeoid separation varies smoothly over kilometres (confirmed: at
   most ~2.5 m across the whole of Tyrol — see `vertical_datum.py`), so
   sampling every 50 px (~1.5 km at this resolution) and interpolating is
   a standard, justified simplification, not a precision compromise — and
   avoids millions of individual PROJ transform calls per chunk.
3. `diff = CopDEM − (LiDAR_resampled + correction)` — same subtraction
   convention as `error_single_m` (positive = CopDEM reads above LiDAR).
4. **Sanity clip**: `|diff| > 100 m` → nodata. This exists because of a
   real finding during testing, not a hypothetical: the EVRF2000 Austria
   correction grid produced a wildly implausible value (~−52 m) when
   evaluated at a random point that turned out to be **outside Austria's
   actual border** (but still inside a chunk's rectangular bounding box —
   several chunks span into Germany, Switzerland, Italy, Slovenia, or
   Czechia). The national vertical-datum grid isn't valid outside its
   country. In practice, LiDAR's own nodata mask already excludes
   non-Austria territory from the output (no LiDAR data there means no
   diff computed there regardless), so this clip is a **defensive
   second layer**, not the primary safeguard — confirmed by checking
   actual output: only ~0.008% of valid pixels sat anywhere near the
   clip boundary on a test chunk, so it isn't silently discarding real
   data.

**Output**: one `diff_*.tif` per CopDEM chunk with any LiDAR coverage,
under `data/dem_diff_lidar/`, plus `data/dem_diff_lidar_mosaic.vrt` — a
visualization-only mosaic for QGIS, built the same way as
`dem_mosaic.vrt` (see [qgis_project.md](qgis_project.md) for why that
mosaic-vs-native-source split matters and is never crossed for numeric
work).

Chunks entirely outside LiDAR coverage (no overlap with Austria) are
skipped, not written as empty files.

## Explicit list of what this does NOT do

- Does not verify the LiDAR DEM's vertical datum independently — see
  above, this is instructed, not confirmed.
- Does not handle any horizontal datum discrepancy between EPSG:31287
  (MGI) and WGS84 beyond what `rasterio.warp.reproject`'s standard
  CRS-to-CRS transform provides — no separate MGI→WGS84 grid-based
  horizontal correction was investigated.
- The 100 m sanity clip is a blunt instrument (a fixed threshold, not a
  border-aware mask) — it happens to work because the artifact values
  it's guarding against are far larger than any real signal, but a more
  precise fix would clip to Austria's actual border polygon instead.
- No stratification of the raster diff by terrain slope, land cover, or
  region — it's the raw per-cell comparison.
- LiDAR data year is 2018; Copernicus DEM's underlying acquisitions are
  from the TanDEM-X mission timeframe (~2011-2015) — no correction for
  the several-year gap between epochs (relevant mainly in
  actively-changing terrain: quarries, construction, glacier retreat).
