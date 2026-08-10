# DEM extraction and comparison — design decisions and omissions

Scope: [`extract_dem.py`](../extract_dem.py). Takes the clean obstacle table
from `obstacles_austria.py` and samples the cached Copernicus DEM tiles at
each point, per the single-cell + 5×5-window design agreed earlier.

## What gets sampled, and how

- **Single-cell**: bilinear interpolation at the obstacle's exact
  coordinate — not nearest-neighbor, so it reflects the true sub-pixel
  position rather than snapping to whichever cell center is closest.
- **5×5 window** (5 cells × 5 cells, ~150 m × 150 m, centered on the cell
  containing the point): all 25 raw values are read, then `min`, `median`,
  `mean`, and `std` are all computed and kept — no single statistic is
  picked as "the" answer yet, per the earlier decision to defer that choice
  until real data is in hand (it now is; see "Which 5×5 stat" below).
- `capture_signal_m = dem_single - dem_5x5_median`: positive means the
  single-cell value reads above the surrounding terrain, consistent with
  the DSM partly capturing the obstacle's own structure at that pixel.

## Sampling directly from source chunks, not the mosaic VRT

Each obstacle is matched to whichever cached DEM chunk file's bounding box
contains it, and sampled directly from that GeoTIFF via `rasterio`. The
mosaic VRT (`dem_mosaic.vrt`, built for the QGIS project) is **not** used
here, even though it covers the same area more conveniently. Reason:
adjacent DEM chunks were fetched at slightly different degrees-per-pixel
(the longitude pixel size varies by latitude band, to hold ~30 m ground
resolution — see `dem_tiles.py`), so a mosaic spanning multiple bands
necessarily resamples at least some source pixels onto a common grid. That
resampling is invisible and harmless for a visual QGIS layer; it has no
business anywhere near a numeric accuracy comparison.

## Known omission: cross-tile windows

If an obstacle's 5×5 window would extend past the edge of its containing
chunk, the window statistics are left blank (`dem_5x5_*` empty) — the
single-cell value is still computed and kept. **4 of 1932 obstacles** hit
this in the current Austria run. Not fixed in v1: correctly handling this
would mean either stitching neighboring chunks for the read, or building a
proper resampled mosaic and accepting the same cross-band resampling
concern noted above just for these edge cases. Given only 4 records are
affected, deferring is preferable to introducing that complexity now.

## Critical dependency: obstacle base elevation, not top

`error_single_m` and the `error_5x5_*` fields are computed against
`elev_base_egm2008_m`, not `elev_top_egm2008_m` — see
[obstacle_ingestion.md](obstacle_ingestion.md)'s "Critical correction"
section for why this matters and how the mistake was caught. Any future
change to `obstacles_austria.py`'s field names must be mirrored here.

## Sanity-check results (Austria, v1, 1932 obstacles)

| Metric | n | mean | median | stdev |
|---|---|---|---|---|
| `error_single_m` | 1932 | +5.25 m | +4.22 m | 8.77 m |
| `error_5x5_median_m` | 1928 | +1.44 m | +1.22 m | 9.30 m |
| `capture_signal_m` | 1928 | +3.81 m | +3.21 m | 4.28 m |

These are self-consistent and in a plausible range for Copernicus DEM's
known accuracy (a few metres), and the pattern matches the design
hypothesis: the 5×5-window estimate sits closer to zero error than the
single-cell estimate, and the single-vs-window gap (`capture_signal`) is
positive — consistent with the single DSM pixel partially capturing the
obstacle's own height rather than purely bare terrain. This is a sanity
check on plausibility, not a validated accuracy claim — no outlier
triage, stratification by terrain/obstacle type, or cross-check against an
independent reference has been done yet (workflow steps 5–7 from the
original conceptual plan).

## Which 5×5 stat to lead with

Still open. `median` looks like the more defensible default of the three
computed (min is slope-biased downward on sloped terrain per the earlier
design discussion; mean is most sensitive to the same obstacle-contamination
problem the window was meant to avoid) — but this hasn't been decided,
just observed to look reasonable on this first dataset. Revisit once
stratification by terrain slope is implemented, since that's where min vs
median would actually diverge more.

## Explicit list of what this step does NOT do

- No stratification by obstacle type, terrain slope, or land cover.
- No outlier investigation — the summary stats above are unfiltered.
- No cross-check against an independent reference (e.g. LiDAR DTM).
- No handling of the 4 cross-tile-window obstacles beyond leaving their
  window stats blank.
- Only covers the 1932 "simple point" obstacles from
  [obstacle_ingestion.md](obstacle_ingestion.md) — `Curve`, grouped, and
  `Surface` geometries aren't in this output at all.
