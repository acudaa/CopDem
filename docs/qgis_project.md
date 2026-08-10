# QGIS project — design decisions, sources, and a real caveat

Scope: [`copdem_austria.qgs`](../copdem_austria.qgs), originally generated
by [`build_qgis_project.py`](../pipeline/build_qgis_project.py).

## Ownership shift: the live `.qgs` is now authoritative, not the generator

As of 2026-08-10, the project has been opened, edited, and resaved in real
QGIS (3.44.13) — both by hand (added an ESRI World Imagery background
layer in place of the original basemap.at WMTS) and by QGIS itself (a
resave expands the file enormously: legend state, map canvas extent, style
categories, elevation-profile symbols, etc. that the generator never
produced). **From this point on, edits go directly into `copdem_austria.qgs`
in place — the generator is not re-run to produce the project file
wholesale**, since doing so would discard everything QGIS/manual editing
added that the generator doesn't know how to reproduce.

`build_qgis_project.py` is kept in sync where practical (e.g. the label
placement fix below is mirrored into `_build_label_settings()` too) so a
*fresh* project for a new country starts from a working baseline, but it is
no longer the source of truth for `copdem_austria.qgs` specifically.

## Important caveat: not tested against a live QGIS instance

No QGIS installation was available in the environment this was built in, so
this project file was authored against documented/observed QGIS 3.x project
XML schema, then only validated for: well-formed XML, layer-tree IDs
matching `maplayer` IDs, and every local file datasource actually resolving
on disk. It was **not** confirmed to open cleanly in real QGIS. Two spots
carry genuine uncertainty (both noted inline in `build_qgis_project.py`
too):

- The exact structure of the "Map"-wrapped `<Option>` properties inside a
  `SimpleMarker` symbol layer — this changed between QGIS 3.x releases,
  and the newer nested form was chosen as the more likely match for a
  present-day install.
- Whether the `graduatedSymbol` renderer needs a `<classificationMethod>`
  element for the QGIS version in use (older attribute-only style was
  used here).
- Both point layers' `<labeling type="simple">` PAL settings XML
  (text-style/text-buffer/shadow/placement structure, shared by both via
  `_build_label_settings()`) — same situation as the CRS bug below:
  authored from documented/observed schema, not confirmed against a live
  install. If labels don't appear, or the buffer/shadow don't render, the
  expression and field values are still fine (check via the layer's
  Attribute Table); it's specifically the labeling XML structure worth
  re-checking in Layer Properties → Labels.

## Fixed after first real-world open: CRS and layer ordering

Two actual bugs, found by opening the file in real QGIS (not caught by this
project's own well-formed-XML/path-resolution checks, which is exactly why
that first caveat above is worth keeping):

- **"Layer CRS is unknown"**: the original `<spatialrefsys>` block only
  carried `authid`/`description`/acronyms — not enough for QGIS to
  positively resolve the CRS. Fixed by adding full `wkt` + `proj4` + `srid`
  definitions for both EPSG:4326 (all the local layers) and EPSG:3857 (the
  orthophoto's actual datasource CRS — which had also been wrongly forced
  to EPSG:4326 in its own `<srs>` block, mismatching its `crs=EPSG:3857`
  datasource parameter). `srsid` (QGIS's internal `srs.db` row number) is
  deliberately still omitted — guessing it wrong risks resolving to a
  different CRS entirely, whereas proj4+wkt+authid+srid together are
  sufficient without it.
- **Layer stacking order backwards**: the orthophoto (meant as background)
  was listed *first* in `<layer-tree-group>`, painting it over the DEM and
  points instead of under them. QGIS's layer-tree XML lists layers
  top-to-bottom as shown in the Layers panel, and the *top* of that panel
  draws *last* (foreground) — so the first XML child is the topmost/
  foreground layer, not the bottom one. Original code's own comment
  asserted the opposite convention. Fixed order, foreground to background:
  difference → obstacles → DEM → orthophoto.

**If a layer's data loads but its styling doesn't apply as designed**: that's
consistent with one of the above being off for your QGIS version — the fix
is a quick manual re-style (right-click layer → Properties → Symbology),
not a data problem. Please report back what you see; the generator script
is easy to adjust once we know which pattern your QGIS version actually
wants, and it can then be regenerated correctly for good.

## Layers included

| Layer | Source | Symbology |
|---|---|---|
| Austria VHR Orthophoto (background) | basemap.at WMTS, live (not downloaded) | Raw imagery, no styling — a basemap reference |
| Copernicus DEM GLO-30 (mosaic) | `data/dem_mosaic.vrt` (40 cached chunks) | Singleband pseudocolor, 5-stop interpolated ramp, blue→green→yellow→orange→red across the DEM's actual min/max (~103–3922 m) |
| Obstacles (simple points) | `obstacles_simple_points.geojson` (1932 points) | Grey circle markers. Point labels (see below). |
| DEM vs obstacle base — difference | `obstacles_dem_diff.geojson` | Graduated, 6 classes on `error_single_m`, diverging blue (DEM reads below the obstacle base) → red (DEM reads above it), centered on zero. Point labels (see below). |

## Point labels

Both point layers are labeled, each with a two-line, explicitly-prefixed
expression so it's unambiguous which number is which (per
[output_fields.md](output_fields.md)'s field definitions) — and both use a
white text buffer (halo) so the label stays legible regardless of what's
underneath it. The difference layer's labels additionally have a drop
shadow (as originally requested for that layer specifically).

**Difference layer:**

```
1px: 7.1 m
5x5 median: 3.4 m
```

- `1px:` is `error_single_m` — the single-pixel bilinear comparison.
- `5x5 median:` is `error_5x5_median_m` — the 5×5-window median comparison.
  For the 4 obstacles whose window fell off a chunk edge (no
  `error_5x5_median_m` value — see dem_extraction.md), this shows `n/a`
  rather than leaving the whole label blank; without the `coalesce()` in
  the label expression, QGIS's `||` string concatenation would have made
  the *entire* label (including the still-valid 1px line) disappear for
  those 4 points, not just the missing half.
- Both values rounded to 1 decimal place for readability.

**Obstacles layer:**

```
Type: Antennenmast / Antenna
AGL: 55.0 m
```

- `Type:` is `obstacle_type`, shown as-is (bilingual German/English, as the
  source provides it).
- `AGL:` is `height_agl_m` — the obstacle's height above ground level. No
  `coalesce()` needed here, unlike the diff layer's label: `height_agl_m`
  is well-formed for all 1932 kept records (see obstacle_ingestion.md).

Both label expressions and their settings (buffer, shadow) live in
`_build_diff_labeling()` / `_build_obstacles_labeling()` in
`build_qgis_project.py`, sharing a common `_build_label_settings()` helper
— change the expressions there for reference, but apply the actual change
directly in `copdem_austria.qgs` too (see "Ownership shift" above).

## Fixed: only the top layer's label was showing

**Root cause**: the obstacles layer and the difference layer plot at
*identical* coordinates — `obstacles_dem_diff.geojson` is literally
`obstacles_simple_points.geojson` plus extra columns, same 1932 points, same
(lon, lat) per point. Both layers' labels were using `placement="1"`
(offset-from-point) with `xOffset="0" yOffset="0"` — i.e. both anchored at
the exact same spot with zero separation — and QGIS's labeling engine had
`overlapHandling="PreventOverlap"` active (the default). With two labels
wanting the same physical space, PAL can only keep one per point; it kept
whichever layer draws on top (the difference layer, listed first in the
layer tree — see the "layer stacking order" fix above).

Different label *quadrants* were already set (`quadOffset="2"`
AboveRight for the diff layer vs. `quadOffset="8"` BelowRight for the
obstacles layer) but with the actual offset *distance* still at zero,
that alone wasn't enough — a quadrant with no distance still anchors right
at the point.

**Fix** (applied directly in `copdem_austria.qgs`, both layers'
`<placement>` elements):

| | Diff layer | Obstacles layer |
|---|---|---|
| `quadOffset` | `2` (AboveRight) | `8` (BelowRight) — unchanged |
| `yOffset` | `0` → `-4` (push up 4mm) | `0` → `4` (push down 4mm) |
| `dist` | `0` → `4` | `0` → `4` |
| `offsetUnits` | `MapUnit` → `MM` | `MapUnit` → `MM` |
| `priority` | `0` → `1` | `0` (unchanged) |

Two changes worth flagging:

- `offsetUnits` was `MapUnit`, meaning any offset would have been
  interpreted in real ground units (metres, since the project CRS is
  EPSG:3857) rather than a fixed physical distance on screen/print — at
  most zoom levels a few metres of ground offset is imperceptible, and it
  would scale unpredictably with zoom. Changed to `MM` for a stable,
  zoom-independent separation.
- Both `dist`/`distUnits` and `xOffset`/`yOffset`/`offsetUnits` were set
  (redundantly, as a hedge) since it wasn't certain from the XML alone
  which pair actually governs `placement="1"`'s offset — QGIS's Label
  Properties dialog exposes "Quadrant + Distance" for some placement modes
  and "Quadrant + Offset X/Y" for others, and setting both costs nothing if
  one is unused.

**If labels still collide at some zoom levels**: increase the `4` (mm)
values further, symmetrically on both layers, so the gap grows. If you'd
rather see both labels even when they touch, set `unplacedVisibility="1"`
in each layer's `<rendering>` element instead of/in addition to widening
the offset — that tells QGIS to draw colliding labels anyway rather than
dropping the loser.

## Background layer: now ESRI World Imagery, not basemap.at

The background layer was manually swapped to an ESRI World Imagery XYZ
layer during the live QGIS editing session (see "Ownership shift" above).
The basemap.at rationale below is kept for reference/history, not because
it's still what's in the project — check `copdem_austria.qgs`'s
`layer-tree-group` for the actual current background layer rather than
trusting this doc's "Layers included" table blindly, since that table
predates the swap too.

## Why basemap.at for the VHR background, and how the WMTS URL was verified (historical)

Austria's official basemap.at service (`bmaporthofoto30cm`, ~15-30 cm
resolution, open access, no registration) is the natural VHR background for
an Austria-scoped project — it's the same source the country's own AIP
charting uses as its topographic base.

The integration method matters here: basemap.at's own published QGIS
integration guide recommends adding the layer via its WMTS
`GetCapabilities` URL and letting QGIS negotiate tiling itself, rather than
constructing raw XYZ tile URLs by hand. That's what's used here
(`https://maps.wien.gv.at/basemap/1.0.0/WMTSCapabilities.xml`, layer
`bmaporthofoto30cm`, style `normal`, tile matrix set `google3857_0-17`,
format `image/jpeg`). This was a real course-correction during
development: hand-computed XYZ tile URLs (`.../bmaporthofoto30cm/normal/
google3857/{z}/{y}/{x}.jpeg`) reliably 404'd even with correctly-computed
Web Mercator tile indices — the working tile matrix set identifier turned
out to be `google3857_0-17`, not the more commonly-documented `google3857`,
and is only discoverable by actually reading the real `WMTSCapabilities.xml`
rather than assuming a commonly-cited URL pattern. The capabilities-based
QGIS provider avoids needing to get that right by hand at all.

## Why sample directly from `dem_mosaic.vrt` here but never in `extract_dem.py`

The mosaic VRT is fine, even good, for this purpose: QGIS visualization is
about the overall spatial pattern, and the ~4% cross-band resampling
described in [dem_extraction.md](dem_extraction.md) is invisible at any
reasonable viewing scale. It would not be fine for the actual numeric
accuracy comparison, which is why `extract_dem.py` deliberately avoids it.
Keep that split intact — don't repoint the extraction script at the VRT for
convenience.

## Explicit list of what this does NOT do

- No hillshade layer for the DEM (would help visually read terrain shape;
  straightforward to add later via a `hillshade` raster renderer or a
  second VRT-derived layer).
- No layer showing the 5×5-window-based error metrics (`error_5x5_median_m`
  etc.) — only `error_single_m` is symbolized. The diff GeoJSON carries all
  of them as attributes, so switching the graduated renderer's field is a
  quick manual change in QGIS if wanted.
- No print layout / map composition — this is a working/exploration
  project, not a finished cartographic product.
- Only Austria. Same generator structure should extend cleanly once
  Czechia/Montenegro/Romania have their own ingestion + extraction outputs,
  but that's not wired up yet.
