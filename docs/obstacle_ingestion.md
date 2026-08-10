# Obstacle ingestion — design decisions and omissions

Scope: this documents [`obstacles_austria.py`](../obstacles_austria.py), v1.
It covers **only Austria**, and **only the simplest obstacle records**. The
intent is a small, well-understood, high-confidence slice to validate the
DEM comparison pipeline against, before taking on the harder cases. Every
exclusion below is a deferral, not a judgment that those records don't
matter — they're just not yet handled correctly, and it would be worse to
guess than to skip.

Keep this file in sync with the code: if a filter or column mapping changes
in `obstacles_austria.py`, update the corresponding section here in the same
change.

## Source

- File: Austro Control's public "Obstacle Data Set (ICAO) – Austria", Excel
  export, sheet `Alle - All` (the "all obstacles" tab, as opposed to the
  New/Changed/Deleted diff tabs).
- Downloaded from `austrocontrol.at` (open access, no registration). Not
  redistributed in this repo — `data/` is gitignored, partly for size and
  partly because the source's own disclaimer asserts copyright over the
  dataset's contents.
- Effective date of the version used: 2026-08-07 (v1.0, August 2026).
- Horizontal reference: WGS-84 (EPSG:4326). Vertical reference stated in the
  file's own metadata: **EVRS**.

## Scope decision: "Point / Punkt" geometry only

The source sheet's `Geometrie` column has five values. Only one is ingested
in v1:

| Geometry | Count | Included? | Why |
|---|---|---|---|
| `Point / Punkt` | 1939 | ✅ (subject to further filters below) | One coordinate, one elevation value — matches the pipeline's current per-point extraction design directly |
| `Curve / Linie` | 582 | ❌ deferred | Multi-point linear features (e.g. cable cars) — cells pack multiple coordinate/elevation values per row, needs dedicated parsing and a decision on how to compare a line feature to a point-sampled DEM |
| `Point (grouped) / Punkt (gruppiert)` | 246 | ❌ deferred | Multiple related point obstacles bundled in one record (e.g. wind farms) — same multi-value parsing problem, and the source's own metadata warns Excel truncates displayed lists beyond 25 coordinates per cell |
| `Curve (grouped) / Linie (gruppiert)` | 35 | ❌ deferred | Combination of the two problems above |
| `Surface / Fläche` | 7 | ❌ deferred | Areal features — no single point to compare against a DEM pixel without first deciding a representative point (centroid? highest point?) |

**Why point-only first:** every other geometry type requires deciding how to
reduce a multi-point or areal feature to something comparable against a
30 m DEM sample, which is a real methodological question, not just a
parsing one. Getting the simple case working and validated first means any
bugs found later in the multi-point logic are isolated to that logic, not
tangled up with basic extraction/datum-conversion bugs too.

## Further filters applied within Point-geometry records

Of the 1939 `Point / Punkt` rows, three additional exclusions bring the
kept count to **1932**:

| Filter | Excluded | Why |
|---|---|---|
| Multi-line coordinate cell | 5 | A true point should have exactly one coordinate line; a handful of rows tagged `Point` still carry a newline-separated multi-line `Koordinaten` cell (likely a data entry inconsistency in the source). Rather than guess which line is authoritative, these are skipped. |
| Missing identifier (`Kennung`) | 2 | The `id` column is empty for 2 rows. Since `id` is the stable join key for any future update/QC pass, rows without one are dropped rather than assigned a synthetic ID. |

No rows were excluded for unparseable AMSL height or unparseable decimal
coordinates — both fields were 100% well-formed across all 1939 Point rows
(checked programmatically, not just sampled).

## Column mapping and parsing decisions

| Output field | Source column | Decision |
|---|---|---|
| `lon`, `lat` | `Koordinaten (Dezimalgrad)` | Parsed from the decimal-degree field (not the DMS field) — it's already in the exact form needed, avoiding a DMS-parsing step that would just reintroduce rounding. The field is space-separated `"LAT LON"` (matches the DMS field's N-then-E order); confirmed via the metadata sheet that the horizontal CRS is EPSG:4326. |
| `elev_top_amsl_m` | `Maximale Höhe AMSL (M / FT)` | Metres value only (feet is redundant). This is the obstacle's **top** elevation — see the correction section above. Kept for reference/QC, not the primary comparison field. |
| `height_agl_m` | `Maximale Höhe AGL (M / FT)` | Same metres-only parsing. Used to derive base elevation (below), and kept standalone for the single-cell-vs-5×5 "capture signal" diagnostic. |
| `elev_base_amsl_m` | (computed) | `elev_top_amsl_m - height_agl_m`. **This is the obstacle base elevation** — what the DEM comparison actually targets. |
| `elev_vertical_crs_epsg` | (derived, constant `9274`) | See "Vertical datum" below — every Austria record gets the same source vertical CRS. |
| `elev_base_egm2008_m` | (computed) | `elev_base_amsl_m` converted to EGM2008 via `vertical_datum.to_egm2008()`, per-point (position-dependent — see [vertical_datum.py](../vertical_datum.py)). **This is the field `extract_dem.py` compares the DEM against.** |
| `elev_top_egm2008_m` | (computed) | Same conversion applied to the top elevation — kept for QC/reference, not used in the primary comparison. |
| `horizontal_accuracy_m`, `vertical_accuracy_elev_m`, `vertical_accuracy_agl_m` | `Horizontale Genauigkeit`, `Vertikale Genauigkeit ...` | Parsed to a float in metres where stated; **`None` (not `0`) where the source says `---`**. A missing accuracy claim must never be silently treated as a perfect (zero-error) claim — that would bias any accuracy-weighted analysis. Only ~8% of Point records have a stated accuracy at all. |
| `day_marking`, `lighted` | `Tageskenn-zeichnung`, `Befeuert` | Parsed `ja/yes` → `True`, `nein/no` → `False`. Not used in the DEM comparison itself; kept for possible future stratification (marked/lit obstacles may correlate with height/prominence). |
| — | `Datenqualitäts-anforderungen eingehalten` | **Not carried through at all.** Checked: this field is `---` (empty) for all 1932 kept records — it exists in the schema but is unpopulated in this data release, so there's nothing to extract. |
| — | `Horizontale Ausdehnung (Länge x Breite / Radius)` | **Not carried through.** Essentially always `---` for point obstacles (2 exceptions among all Point rows, not investigated) — extent doesn't meaningfully apply to a point geometry. |

## Critical correction: "Maximale Höhe AMSL" is the obstacle's TOP elevation, not its base

This was caught by a sanity check on the DEM comparison output, not during
ingestion itself, and is worth recording prominently because it produced
plausible-*looking* wrong numbers rather than an obvious failure.

**What happened:** v1 originally treated `Maximale Höhe AMSL` directly as
the obstacle's base elevation (matching this study's actual goal — see the
top of this doc). Running the DEM comparison against it gave a mean
"error" of **−42.6 m**, decisively too large to be real DEM error (Copernicus
DEM's known accuracy is a few metres).

**Root cause:** `Maximale Höhe AMSL` is the ICAO "ELEV" convention — the
elevation of the obstacle's **top**, not its base. The source's own footnote
(`* Fußpunkthöhe — Maximale Höhe AMSL gemessen am Fußpunkt des Hindernisses
/ ELEV measured at the base of the OBST`) marks the *exception*: records
flagged with `*` use base elevation instead. None of the 1932 kept Point
records carry that flag (confirmed: 0 occurrences), so 100% of them use the
default top-elevation convention.

**How this was confirmed, not just suspected:** correlation between the
(wrong) error and `height_agl_m` was **r = −0.95** — near-perfect — and
`error + height_agl_m` clustered at mean 5.25 m / stdev 8.8 m, a plausible
DEM-accuracy figure. That's the signature of "the obstacle's own height is
leaking into the error metric," not real terrain-comparison noise.

**Fix:** base elevation is computed as `elev_base_amsl_m = elev_top_amsl_m -
height_agl_m`, and *that* is what gets converted to EGM2008 and compared
against the DEM. Both top and base EGM2008 values are kept in the output
(`elev_top_egm2008_m`, `elev_base_egm2008_m`) so this can be sanity-checked
again later if needed. After the fix, `error_single_m` has mean 5.25 m /
stdev 8.8 m — consistent with the correlation check above, and in a
plausible range for Copernicus DEM's known accuracy.

**Lesson for future country sources:** don't assume a column named
"elevation" or "AMSL" for an obstacle record means base elevation — ICAO
obstacle data conventionally reports the top (that's the safety-relevant
figure for aviation), and this needs to be checked per source, not assumed
uniformly. Same category of mistake as the vertical-datum assumption below:
verify against the source's own documentation, then confirm numerically
before trusting results.

## Vertical datum: why EVRF2000 Austria, not the generic EGM96 assumption

This is the most consequential decision in the ingestion step, so it's
documented here in addition to the reasoning already in
[vertical_datum.py](../vertical_datum.py):

- The source file's own metadata states its vertical reference as `EVRS`
  (European Vertical Reference System) — **not** EGM96, which is the
  generic default one might otherwise assume from general ICAO/AIXM
  guidance.
- EVRS is realized nationally; Austria's realization is **EVRF2000 Austria
  height**, EPSG:**9274**, confirmed via EPSG.io and cross-checked
  numerically against reported literature values (see `vertical_datum.py`'s
  self-test, which reproduces the documented ~2.5 m EVRS/EGM96 divergence in
  the Tyrolean Alps).
- Using EGM96 instead of EPSG:9274 would have introduced up to ~2.5 m of
  systematic error in mountainous regions — comparable in magnitude to the
  DEM errors this whole study is trying to measure. Using EGM2008 instead
  (Copernicus DEM's own native reference) as a stand-in would have been
  closer (~0.1 m divergence from EPSG:9274 at the same test point) but
  still an unjustified assumption when the source explicitly states its own
  reference.
- Every kept record therefore carries `elev_amsl_vertical_crs_epsg = 9274`,
  and `elev_amsl_egm2008_m` is computed per-point (not with a single global
  offset) via `vertical_datum.to_egm2008()`, since geoid/quasigeoid
  separation varies spatially.
- The code asserts `Vertikales Referenzsystem == "EVRS"` on every row and
  raises if that ever changes in a future data release — a silent datum
  change from the source would otherwise be invisible.

## Known data-quality caveats carried into the output (not filtered out)

- **Accuracy is usually unknown, not zero.** ~92% of kept records have no
  stated horizontal or vertical accuracy. Any downstream analysis that
  weights or filters by accuracy needs to explicitly decide how to handle
  `None` (exclude? treat as worst-case? impute?) rather than defaulting to
  treating missing as perfect.
- **No independent data-quality flag is available** from this source for
  Point records (see the `Datenqualitäts-anforderungen eingehalten` note
  above) — there's no per-record "trust this one less" signal to lean on
  from Austria's data alone.
- The obstacle `Art` (type) field is preserved but not yet used for
  filtering or stratification. Distribution among kept records: predominantly
  `Antennenmast / Antenna` (1710 of 1932), then `Mast/Pole` (62),
  `Windkraftanlage/Windpower plant` (44), `Gebäude/Building` (36),
  `Schornstein/Stack` (30), `Gittermast/Mast` (28), `Turm/Tower` (16), and a
  handful of others. This is worth revisiting once stratification (per the
  overall workflow's step 5) is implemented — thin mast-type obstacles are
  the best candidates for isolating terrain accuracy from DSM
  self-contamination; wide ones (buildings, wind turbines) are not.

## Explicit list of what v1 does NOT do

- Does not ingest `Curve`, `Point (grouped)`, `Curve (grouped)`, or
  `Surface` geometries (870 records, ~31% of the full dataset).
- Does not sample the DEM yet — this module only produces the clean
  obstacle table (`obstacles_simple_points.csv`); single-cell / 5×5-window
  extraction is a separate step.
- Does not deduplicate or cross-validate against any independent obstacle
  source.
- Does not attempt to recover the 5 multi-line-coordinate "Point" rows or
  the 2 missing-ID rows — they're simply excluded, not fixed.
- Does not apply any obstacle-type filtering (e.g. excluding wind turbines
  as poor point-comparison candidates) — that's a stratification-stage
  decision, not an ingestion-stage one, so all 1932 clean points are kept
  and left for later stages to filter or weight as needed.
