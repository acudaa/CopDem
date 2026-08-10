# Output field reference

What every column in the two pipeline output CSVs actually means. Written
separately from [obstacle_ingestion.md](obstacle_ingestion.md) and
[dem_extraction.md](dem_extraction.md) (which explain *why* each field
exists and the decisions behind it) so there's one place to look up *what a
field means* without re-reading the design rationale.

There are two output files, one built on top of the other:

- `data/obstacles/austria/obstacles_simple_points.csv` — from
  `obstacles_austria.py`. One row per obstacle.
- `data/obstacles/austria/obstacles_dem_diff.csv` — from `extract_dem.py`.
  Every column above, plus the DEM sample and error columns below.

Both are gitignored (not redistributed — see obstacle_ingestion.md's
licensing note); regenerate them locally by running the two scripts.

## The core question this pipeline answers, in one sentence

**How far off is the Copernicus DEM's elevation from the true ground
elevation at the obstacle's base, at that same location?** Every `error_*`
field below is a version of that same subtraction, on a common vertical
reference (EGM2008), just sampled from the DEM in a different way (a single
pixel vs. a small neighborhood).

## Sign convention — read this before interpreting any error field

**`error = DEM value − obstacle base elevation`**, always in that order,
always in metres, always on the EGM2008 vertical reference.

- **Positive error** → the DEM reads *higher* than the true ground at the
  obstacle's base. Plausible causes: the DSM is partly seeing the obstacle
  itself (or nearby vegetation/structures) rather than bare ground, or a
  genuine DEM overestimate.
- **Negative error** → the DEM reads *lower* than the true ground. Plausible
  causes: genuine DEM underestimate, local terrain the DEM smooths over
  (e.g. a small rise), or occasionally a wrong/imprecise obstacle
  coordinate placing the sample off the real base point.
- **Zero** → the DEM exactly matches the obstacle's base elevation at that
  point (not expected often at 30 m resolution — a value very close to zero
  is the realistic "good" outcome, not exactly zero).

This is the opposite subtraction order from "how much clearance is left"
or "how much does the obstacle exceed the DEM" — this pipeline is a DEM
*accuracy* study, not an obstacle clearance calculation, so the DEM is
always the minuend (the thing being evaluated), the obstacle base is always
the reference (assumed-true) value being evaluated against.

## `obstacles_simple_points.csv` fields

| Field | Meaning |
|---|---|
| `id` | Source dataset's stable identifier (`Kennung`) for the obstacle. |
| `region`, `district`, `location` | Administrative region (Bundesland), district (Bezirk), and name/local ID of the obstacle, straight from the source. |
| `obstacle_type` | What kind of obstacle (mast, building, wind turbine, etc.) — `Art` in the source. |
| `lon`, `lat` | WGS84 decimal-degree position (EPSG:4326). |
| `elev_top_amsl_m` | Elevation of the obstacle's **top**, in metres, on Austria's own vertical datum (EVRF2000 Austria) — the source's raw "Maximale Höhe AMSL" value. Reference only; not used in the DEM comparison. |
| `height_agl_m` | Obstacle height above ground level, in metres — the source's raw AGL value. |
| `elev_base_amsl_m` | Elevation of the obstacle's **base** (`elev_top_amsl_m − height_agl_m`), still on EVRF2000 Austria. **This is the ground-truth value the DEM gets compared against**, before the vertical-datum conversion below. |
| `elev_vertical_crs_epsg` | EPSG code of the vertical CRS the two fields above are expressed in — always `9274` (EVRF2000 Austria height) for this source. Recorded per-row so the provenance travels with the data. |
| `elev_base_egm2008_m` | `elev_base_amsl_m` converted to EGM2008 (Copernicus DEM's native vertical reference). **This is the actual value used as "obstacle base elevation" in every `error_*` field below.** |
| `elev_top_egm2008_m` | Same conversion applied to the top elevation. Reference/QC only. |
| `day_marking`, `lighted` | Whether the obstacle carries daytime marking / is lit (`True`/`False`), from the source. Not used in the comparison. |
| `horizontal_accuracy_m`, `vertical_accuracy_elev_m`, `vertical_accuracy_agl_m` | Stated positional/height accuracy from the source, in metres, where available — `null`/empty where the source doesn't state one (only ~8% of records have these). A blank here means "unknown," never "zero error." |

## `obstacles_dem_diff.csv` — adds these fields on top of everything above

| Field | Meaning |
|---|---|
| `dem_single_egm2008_m` | The Copernicus DEM's elevation at the obstacle's exact (lon, lat), bilinear-interpolated, on EGM2008. This single pixel can include part of the obstacle's own structure — see `capture_signal_m` below. |
| `error_single_m` | `dem_single_egm2008_m − elev_base_egm2008_m`. The headline single-pixel error — see "Sign convention" above. |
| `dem_5x5_min_egm2008_m`, `dem_5x5_median_egm2008_m`, `dem_5x5_mean_egm2008_m` | The minimum / median / mean DEM value across the 5×5-cell (~150 m × 150 m) neighborhood centered on the obstacle, on EGM2008. Three different ways to summarize "what's the DEM saying about the surrounding terrain," each with different bias trade-offs (min is slope-biased low; mean is most sensitive to obstacle self-contamination; median is the current best-guess default — see dem_extraction.md). |
| `dem_5x5_std_egm2008_m` | Standard deviation of the 25 raw DEM values in that window — a roughness/slope indicator, not an elevation value itself. A high value means the neighborhood isn't flat, so any single window statistic is a rougher approximation there. |
| `error_5x5_min_m`, `error_5x5_median_m`, `error_5x5_mean_m` | Each window statistic above, minus `elev_base_egm2008_m` — same subtraction order and sign convention as `error_single_m`, just using the window value instead of the single pixel. |
| `capture_signal_m` | `dem_single_egm2008_m − dem_5x5_median_egm2008_m` — **not** compared against the obstacle at all, this compares the DEM to itself. Positive means the single pixel at the obstacle's location reads higher than its own surroundings, consistent with the DSM partially capturing the obstacle's own height rather than showing bare ground there. This is a diagnostic for *why* `error_single_m` might be more positive than `error_5x5_*_m`, not an accuracy metric in its own right. |
| Window fields left blank | When the 5×5 window would extend past the edge of the obstacle's DEM chunk (4 of 1932 obstacles), every `dem_5x5_*`, `error_5x5_*`, and `capture_signal_m` field is left empty — `error_single_m` is still computed. See dem_extraction.md's "Known omission" section. |

## Worked example

Row for `LO_ODS_000001 - Sonnenberg` (an antenna mast):

- `elev_top_amsl_m` = 536 m, `height_agl_m` = 55 m → `elev_base_amsl_m` = 481 m (base = top − AGL)
- `elev_base_egm2008_m` ≈ 480.93 m (tiny shift from the EVRF2000 Austria → EGM2008 conversion)
- `dem_single_egm2008_m` ≈ 488.06 m
- `error_single_m` ≈ 488.06 − 480.93 = **+7.1 m** → the DEM reads about 7 m *above* the true base elevation at this exact pixel, plausible given a 55 m mast could be partly visible to the DSM at its base pixel.
