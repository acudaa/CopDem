# CopDem

Evaluating the vertical accuracy of Copernicus DEM GLO-30 against European
aeronautical obstacle databases, starting with Austria. See
[docs/](docs/) for the full methodology, design decisions, and every
omission/caveat along the way — start with
[docs/output_fields.md](docs/output_fields.md) if you just want to know
what a column in the output data means.

## Repo layout

- **`pipeline/`** — the actual DEM validation pipeline (Python scripts, run
  from the repo root, e.g. `python pipeline/obstacles_austria.py`):
  - `cdse_auth.py` — CDSE OAuth token acquisition
  - `dem_tiles.py` — fetches Copernicus DEM GLO-30 from CDSE, cached locally
  - `vertical_datum.py` — geoid/national-datum → EGM2008 conversion
  - `obstacles_austria.py` — ingests Austria's obstacle dataset (simple
    points only, v1 — see [docs/obstacle_ingestion.md](docs/obstacle_ingestion.md))
  - `extract_dem.py` — samples the DEM at each obstacle, computes DEM-vs-
    obstacle-base error (see [docs/dem_extraction.md](docs/dem_extraction.md))
  - `build_dem_vrt.py`, `export_geojson.py`, `build_qgis_project.py` —
    build the QGIS visualization inputs (see [docs/qgis_project.md](docs/qgis_project.md))
  - `_rasterio_compat.py` — a Windows/rasterio DLL-load workaround; import
    it before `rasterio` in any script that needs it
- **`copdem_austria.qgs`** (+ `copdem_austria_attachments.zip`) — the QGIS
  project. **Now edited live in QGIS, not regenerated from
  `build_qgis_project.py`** — see [docs/qgis_project.md](docs/qgis_project.md)'s
  "Ownership shift" section before touching either.
- **`docs/`** — methodology and design-decision documentation. Read before
  the code if you're new here.
- **`data/`** — gitignored. Cached DEM tiles, downloaded obstacle datasets,
  and pipeline outputs. Not redistributed (size, and source licensing —
  see obstacle_ingestion.md). Regenerate locally by running the pipeline
  scripts in order (auth → DEM fetch → obstacle ingest → extract → export).
- **`build_site.py`, `content/`, `templates/`, `site/`** — a separate,
  minor concern: a small static-site generator (Markdown → HTML), deployed
  to GitHub Pages via [.github/workflows/deploy.yml](.github/workflows/deploy.yml).
  Currently just a placeholder page — not yet wired up to publish anything
  about the DEM validation work itself.

## Pipeline quick start

```bash
python -m venv .venv
.venv/Scripts/activate  # Windows
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your CDSE credentials (never
commit `.env` — it's gitignored). Then, from the repo root:

```bash
python pipeline/dem_tiles.py          # fetch + cache Austria's DEM coverage
python pipeline/obstacles_austria.py  # ingest Austria's obstacle dataset
python pipeline/extract_dem.py        # sample DEM at each obstacle, compute error
python pipeline/export_geojson.py     # export for QGIS
python pipeline/build_dem_vrt.py      # build the DEM mosaic VRT for QGIS
```

## Static site (separate concern)

```bash
python build_site.py
```

Output goes to `site/`. Open `site/index.html` in a browser to preview.
Edit or add Markdown files under `content/` — each needs a small front
matter block:

```
title: Page Title
---
# Heading

Body text...
```

Pushing to `main` triggers [.github/workflows/deploy.yml](.github/workflows/deploy.yml),
which builds the site and publishes it to GitHub Pages automatically.
