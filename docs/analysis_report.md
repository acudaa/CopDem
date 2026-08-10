# Analytical report — design decisions

Scope: [`pipeline/analyze_obstacles_diff.py`](../pipeline/analyze_obstacles_diff.py)
→ [`reports/obstacles_dem_diff_analysis.html`](../reports/obstacles_dem_diff_analysis.html).
A self-contained static HTML report (no build step, no CDN dependency) —
open the file directly in a browser, or regenerate it after any pipeline
re-run: `python pipeline/analyze_obstacles_diff.py`.

## What it covers, and why exactly these two fields

Per request: distribution + basic statistics for `error_single_m` and
`dem_5x5_median_egm2008_m`, whole-dataset and broken down by obstacle
type. Note these are two **different kinds** of field — `error_single_m`
is a signed error (DEM minus obstacle base), while
`dem_5x5_median_egm2008_m` is a raw DEM elevation value, not an error. The
report labels this explicitly (see each section's description line) so
the two aren't read as directly comparable quantities. See
[output_fields.md](output_fields.md) for full field definitions.

## Chart design (per the dataviz skill)

- **`error_single_m` is signed and centered near zero** → diverging
  blue/red (blue = DEM reads below the obstacle base, red = above),
  matching the same convention already used in the QGIS difference
  layer's symbology (see [qgis_project.md](qgis_project.md)) for
  consistency across deliverables.
- **`dem_5x5_median_egm2008_m` is an unsigned magnitude** (real elevation,
  never centered at zero) → sequential single blue hue, light→dark by
  magnitude — never a rainbow ramp for a statistical chart, per the
  skill's hard rule.
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
- No cross-check against the `error_5x5_median_m` (the *error* version of
  the window statistic) — only the raw elevation
  `dem_5x5_median_egm2008_m` was requested. Both fields are in the
  underlying CSV if that comparison is wanted later.
- No stratification by terrain slope/region — only by obstacle type, per
  what was asked.
