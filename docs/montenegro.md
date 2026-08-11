# Montenegro — design decisions

Montenegro is the second country in this project (after Austria), and the
first where several of Austria's smooth assumptions didn't hold. This file
consolidates the whole story: data sourcing, scope, the vertical-datum
investigation (a real correction, not a formality), and the EGM96/EGM2008
undulation side-study.

## Data source: why this couldn't be automated end-to-end

Austria's obstacle data was a public Excel export — fetchable directly.
Montenegro's isn't. Its obstacle data lives in the VFR AIP Serbia/Montenegro
(published by SMATSA, the joint Serbia/Montenegro air navigation services
provider) section **ENR 5.4 "Air Navigation Obstacles"**, and both routes to
it are account-gated:

- **SMATSA's own eAIP**: a JavaScript-rendered site that couldn't be
  reliably scripted in this environment (guessed AIRAC-cycle URLs 404, and
  the corporate site's "eAIP" link is a client-side app).
- **Eurocontrol's EAD (European AIS Database)**: EAD Basic (free public
  browsing) requires registration; the full AIXM dataset requires signing a
  separate EAD User Agreement.

Both routes need a human to register an account — something this pipeline's
tooling does not do on a user's behalf (account creation and credential
entry are outside what's automated here, by design). The user registered
for EAD Basic themselves, logged in, browsed to Montenegro's ENR 5.4, and
downloaded the PDF: `data/obstacles/montenegro/VFR_LY_ENR_5_4_en_*.pdf`.
`pipeline/obstacles_montenegro.py` parses that PDF directly (via pymupdf
text extraction, anchored on each obstacle's `LY_OBST_NNNN` designation —
see that file's docstring for the chunk-parsing approach).

## Scope: NOT a full obstacle inventory

ENR 5.4's own text states it covers only **"permanent obstacles in Area 1
[Beograd FIR] with height of 328 FT (100 M) AGL and higher."** This is a
structurally different scope from Austria's dataset (a dedicated national
obstacle database with no height floor). Consequences:

- **n = 51** for Montenegro vs. **n ≈ 1,932** for Austria — not because
  Montenegro genuinely has ~38x fewer obstacles, but because this list only
  captures the tallest structures.
- Only **two obstacle types appear**: Antenna (2) and Wind turbine (49,
  all part of the Nikšić-Krnovo and Ulcinj-Možura wind farms) — no towers,
  buildings, chimneys, cranes, etc. Austria's much broader type mix is a
  product of its dataset's broader height coverage, not a difference
  between the countries' actual obstacle inventories.
- The source document covers **both Serbia and Montenegro** in one combined
  table (Serbia's obstacles listed first, under "a) Srbija"); only the
  Montenegro section ("b) Crna Gora") is parsed. The two countries share one
  designation-numbering sequence, so Montenegro's IDs are non-contiguous
  (0019–0046, then 0077–0099 in the AIRAC AMDT 3/26 edition) — expected,
  not a sign of missing rows (parser reports 0 errors against all 51).

Do not read Montenegro's smaller n as "this pipeline covers Montenegro's
obstacles less thoroughly than Austria's" — it's an accurate reflection of
what the available source data actually contains.

## Vertical datum: a real correction, caught by a sanity check

**What was expected going in**: EPSG.io lists **Trieste height (EPSG:5195)**
— normal-orthometric heights referenced to mean Adriatic Sea level at
Trieste's Molo Sartorio gauge — as the applicable vertical datum for
"Montenegro onshore." This is also the same historical lineage as Austria's
GHA height (EPSG:5778, "Adria Triest") used for its LiDAR DHM — both trace
back to the same Austro-Hungarian-era Adriatic gauge network. It looked like
a clean, EPSG-registered answer, unlike Romania's undocumented national
datum (see the Romania research earlier in this project's history — parked
for now, see below).

**What actually happened**: registering `SOURCE_VERTICAL_CRS["ME"] =
TRIESTE_HEIGHT` (5195) and converting a real obstacle's elevation
(LY_OBST_0019, base elevation 6.71 m) produced an EGM2008 value of
**-32.44 m** — a ~39 m "correction" at a valley site a few hundred metres
from a river. That's implausible on its face (Austria's real corrections
were all under 1 m), so it was checked rather than trusted:

```
geoid_to_ellipsoidal(lon, lat, 6.71, EPSG:5195) -> 6.71   (0.0 m undulation applied)
```

**PROJ silently applies zero undulation for EPSG:5195** — it has no real
transformation grid for this CRS, and instead of raising an error, the
compound-CRS transform quietly no-ops, passing the orthometric height
through unchanged as if it were already ellipsoidal. That's a wrong answer
that looks exactly as valid as a right one — worse than an outright failure,
because nothing about the code path signals it. This is precisely the class
of mistake `vertical_datum.py`'s "never assume a datum" principle exists to
catch, extended one level further: even a **correctly identified, correctly
EPSG-registered datum is useless if the conversion library can't actually
transform it** — registering the right CRS code is necessary but not
sufficient.

**The fix, grounded in the source's own stated practice, not a fallback
guess**: SMATSA's AIP GEN 2.1 (Serbia/Montenegro), section 4.2 "Geoid
model," states in its own words:

> "Earth Gravitational Model 1996 (EGM 96) is in use. This model is used
> only for transformation of ellipsoidal heights in orthometric, for points
> with required accuracy below 1 M."

I.e. SMATSA itself uses EGM96 as the practical vertical reference for
exactly this kind of sub-metre-accuracy conversion — not a generic
ICAO/AIXM default assumed without checking (the opposite mistake pattern
from Austria, where EGM96 was explicitly confirmed as **wrong**). Re-running
the same test point with EGM96 gives a sane, small correction:

```
geoid_to_ellipsoidal(lon, lat, 6.71, EGM96) -> 45.74   (39.03 m undulation applied - PROJ DOES have this grid)
to_egm2008(lon, lat, 6.71, EGM96) -> 6.60   (net correction: -0.115 m)
```

`SOURCE_VERTICAL_CRS["ME"]` is registered as `EGM96` in `vertical_datum.py`
(with `TRIESTE_HEIGHT = 5195` kept in the module as a documented, explicitly
commented-as-unusable constant — not deleted, so the next person doesn't
re-discover the same dead end from scratch). All 51 Montenegro obstacles'
`geoid_correction_m` values are in the expected -0.1 to -1.0 m range (see
`data/obstacles/montenegro/obstacles_simple_points.csv`).

## No local ground-truth DEM

Unlike Austria (national LiDAR DHM from BEV), Montenegro has no confirmed
nationwide high-resolution elevation dataset in this project's hands —
ANCPI-equivalent-style national LiDAR-derived elevation data is a
Romania-side finding, not Montenegro's; Montenegro's own national Geoportal
(`geoportal.co.me`, Real Estate Administration) was not investigated for
elevation products, as it wasn't the priority blocker. Consequently
Montenegro's obstacle comparison and reports use **Copernicus DEM GLO-30
only** — no LiDAR section, unlike the Austria reports.

## EGM96 vs. EGM2008 undulation — a dedicated raster

Because CopDEM is natively EGM2008 but Montenegro's obstacle data's
practical reference is EGM96 (see above), the size of that geoid difference
across the whole country is worth showing as its own layer, not just as a
per-obstacle number buried in a CSV column. `pipeline/
build_egm96_undulation_raster.py` builds:

- `data/egm96_egm2008_undulation_montenegro.tif` — EGM2008 − EGM96, in
  metres, at every CopDEM pixel (5727×7050, same grid as
  `dem_mosaic_montenegro.vrt`).
- `data/dem_mosaic_montenegro_egm96.tif` — CopDEM's own elevation values
  recalculated onto EGM96 (`CopDEM_EGM2008 − correction`), i.e. what CopDEM
  would read if it were natively published on Montenegro's practical
  reference geoid.

**Method**: geoid undulation is a function of position only, not of the
height being converted (a compound-CRS geoid↔ellipsoidal transform is a
pure additive shift — same principle already established and used in
`vertical_datum.py` and `build_lidar_diff_raster.py` for Austria's GHA
correction). That means the correction can be computed once per position
(at an arbitrary height, 0.0 m here) and reused for every pixel regardless
of its actual elevation. Evaluating it at all ~40M pixels via pyproj would
still be far too slow for a smooth, low-frequency signal like this, so it's
computed on a coarse ~3km grid (every 100 native pixels) and bilinearly
upsampled (`scipy.ndimage.zoom`) to the full CopDEM grid — verified against
the exact per-point value already computed for LY_OBST_0019 (raster:
-0.121 m vs. per-point: -0.115 m; the ~0.006 m gap is expected smoothing
from the coarse grid, not an error).

**Result** (whole-country stats, see
`reports/egm96_egm2008_undulation_montenegro.html` for the full illustrated
note — histogram, full-country map, and two zoomed insets):

| | value |
|---|---|
| mean | -0.495 m |
| median | ~-0.44 m |
| stdev | ~0.4 m |
| min | -1.743 m |
| max | +0.296 m |

The correction is a smooth, large-scale (low-frequency) signal — it varies
gradually across the country (a real north-south gradient: mean -0.857 m
around Nikšić/Krnovo in the interior/north vs. -0.290 m around the Ulcinj
coast in the south, a ~0.57 m shift over ~94 km) rather than the noisier,
terrain-driven pattern of CopDEM's own per-point error against the obstacle
data (mean ~5 m, see `reports/obstacles_dem_diff_analysis_montenegro.html`).
It's not large enough to explain CopDEM's own error on its own, but it is
large enough that skipping it would have silently biased every Montenegro
number in this project by up to ~1.7 m in the worst case.

## QGIS project

`copdem_montenegro.qgs` (generated by
`pipeline/build_qgis_project_montenegro.py`, same generator schema as
Austria's original `build_qgis_project.py` output) loads, foreground to
background:

1. DEM vs. obstacle base — difference (`error_single_m`, same diverging
   blue/red classes as Austria's diff layer)
2. Obstacles (simple points), labeled with type + AGL height
3. EGM96 vs. EGM2008 undulation correction (new — diverging blue/white/red)
4. Copernicus DEM GLO-30, recalculated to EGM96 (new)
5. Copernicus DEM GLO-30 mosaic, native EGM2008
6. VHR background — **ESRI World Imagery** (Esri/ArcGIS Online XYZ tiles),
   not a Montenegro-specific national source: this is the same background
   the user already migrated Austria's *live* project to (see
   `copdem_austria.qgs`'s "ESRI Satellite (ArcGIS/World_Imagery)" layer —
   originally basemap.at, an Austria-only national WMTS), so both country
   projects now share one VHR convention instead of researching a separate
   national source for each new country.

No LiDAR layer (see "No local ground-truth DEM" above).

## Parked: Romania

Romania was the original next-country target before Montenegro. Its
obstacle data (ROMATSA/aisro.ro, AIP ENR 5.4) requires an **email request**
to ROMATSA rather than any self-service download, and its national vertical
datum ("Marea Neagră 1975" / Black Sea 1975) has **no standard EPSG code**
— a harder, differently-shaped problem than Montenegro's (which had a
registered-but-unusable EPSG code; Romania has no registered code at all).
Deferred at the user's direction in favour of Montenegro; not started.
