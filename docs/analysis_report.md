# Analytical report — design decisions

Scope: [`pipeline/analyze_obstacles_diff.py`](../pipeline/analyze_obstacles_diff.py)
→ [`reports/obstacles_dem_diff_analysis.html`](../reports/obstacles_dem_diff_analysis.html).
A self-contained static HTML report (no build step, no CDN dependency) —
open the file directly in a browser, or regenerate it after any pipeline
re-run: `python pipeline/analyze_obstacles_diff.py`.

## Correction: the report originally showed the wrong field

The first version of this report used `dem_5x5_median_egm2008_m` for the
second field, per the literal original request. That field is a **raw DEM
elevation** (EGM2008), not an error — its mean across the dataset is
~814 m, simply because that's the average terrain elevation across
~1,932 obstacle sites in mountainous Austria. A reader reasonably read
that 814 m as a DEM discrepancy and flagged it as obviously wrong. It
wasn't a computation bug — the number was correct for what it was — but
putting a raw elevation value in a report titled "DEM vs. obstacle base
— analysis," right next to a genuine error metric (`error_single_m`),
with the distinction living only in a caption line, was a bad
presentation call. A caption is not enough insulation against a plausible
misreading when the surrounding structure implies "these are both error
numbers."

**Fixed**: the report now uses `error_5x5_median_m` — the actual 5×5-window
discrepancy (5×5-window median DEM value minus obstacle base elevation,
same EGM2008 basis, same sign convention as `error_single_m`) — mean
+1.4 m, matching the number already established in
[dem_extraction.md](dem_extraction.md)'s sanity-check table. If the raw
elevation distribution (`dem_5x5_median_egm2008_m`) is ever wanted again,
it should get its own clearly separate section — e.g. "terrain context,"
never framed alongside error metrics without a structural (not just
textual) distinction.

## What it covers

Distribution + basic statistics for the single-cell and 5×5-window-median
errors, whole-dataset and broken down by obstacle type — **for both DEM
sources compared in this project**: Copernicus DEM GLO-30
(`error_single_m`, `error_5x5_median_m`) and Austria's LiDAR-derived DHM
(`error_single_lidar_m`, `error_5x5_median_lidar_m`). All four are signed
errors on the same basis (DEM/LiDAR minus obstacle base elevation,
EGM2008), directly comparable to each other. See
[output_fields.md](output_fields.md) for full field definitions.

Sections are grouped under a "Copernicus DEM GLO-30" / "Austria LiDAR DEM"
header per source, not shown as four undifferentiated cards — the two
products' typical error differs by roughly an order of magnitude (CopDEM
~5 m mean, LiDAR ~0 m mean; see
[lidar_comparison.md](lidar_comparison.md)), and after the field-mislabeling
incident above, grouping by source is a structural safeguard against a
similar misreading, not just another caption.

**LiDAR caveat, restated here because it matters for every LiDAR number in
this report**: the LiDAR DEM's vertical datum (EVRF2000 Austria) is an
*instructed* assumption, not independently verified the way every other
datum decision in this project was — see lidar_comparison.md's "Vertical
reference" section.

## Chart design (per the dataviz skill)

- **Both fields are signed and centered near zero** → diverging blue/red
  for both (blue = DEM reads below the obstacle base, red = above),
  matching the same convention already used in the QGIS difference
  layer's symbology (see [qgis_project.md](qgis_project.md)) for
  consistency across deliverables.
- **By-type breakdown uses horizontal bars**, not vertical columns —
  obstacle type names are long ("Windkraftanlage / Windpower plant"),
  and horizontal bars keep labels readable without rotation or
  truncation.
- The diverging blue/red pair was run through the skill's palette
  validator (`validate_palette.js`) for both light and dark mode — all
  checks pass (CVD separation, normal-vision floor, contrast) in both.
- Every mark (histogram bin, bar) carries a hover/focus tooltip with the
  exact value — per the skill's interaction rules, tooltips supplement
  values already visible in the tables, they don't gate access to them.

## Low-n obstacle types: shown, not hidden, but flagged

Obstacle type counts range from 1,710 (`Antennenmast / Antenna`) down to
several types with **n = 1** (`Denkmal / Monument`, `Navigationsanlage /
Navaid`, `Gasometer / Tank`). Rather than excluding these from the
by-type breakdown (which would silently drop obstacle types the source
data does contain) or silently including them without comment (which
would let a single data point read as a "type-level trend"), every type
with n < 5 is marked `†` in both the table and the bar chart, with a
footnote explaining what that means. `stdev` for `n = 1` is reported as
`0.0` (mathematically correct for a single-point sample — not "unknown"),
which is itself part of why the `†` flag matters: a zero-variance,
single-point "distribution" needs the caveat to not be over-read as a
tight, confident estimate.

## Not included

- No comparison across countries (Austria only, matching the pipeline's
  current scope).
- No terrain-elevation-context section (see "Correction" above) — the raw
  `dem_5x5_median_egm2008_m` distribution isn't shown anywhere in the
  current report, though it's still in the underlying CSV.
- No direct CopDEM-vs-LiDAR section (each is only compared against the
  obstacle base, not against each other) — that comparison exists as the
  raster layer in QGIS (see [lidar_comparison.md](lidar_comparison.md)),
  not in this report.
- No stratification by terrain slope/region — only by obstacle type, per
  what was asked.
