#!/usr/bin/env python3
"""Generate a brief illustrated note on the EGM96<->EGM2008 undulation
correction over Montenegro: summary stats, a histogram of the correction's
distribution, and static map renders ("screenshots") of the correction
raster — full-country plus two zoomed insets chosen to show the smooth
north-south gradient the numbers reveal (see build_egm96_undulation_raster.py
for how the raster itself was built and why the correction is
height-independent).

Output: reports/egm96_egm2008_undulation_montenegro.html (self-contained,
images embedded as base64 data URIs so the report is still one file).
"""
import base64
import io
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import _rasterio_compat  # noqa: F401
import rasterio

ROOT_DIR = Path(__file__).parent.parent
UNDULATION_TIF = ROOT_DIR / "data" / "egm96_egm2008_undulation_montenegro.tif"
OUTPUT_HTML = ROOT_DIR / "reports" / "egm96_egm2008_undulation_montenegro.html"

COLOR_NEG = "#2a78d6"
COLOR_POS = "#e34948"


def _fig_to_data_uri(fig, dpi=150):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _style_axes(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color("#c3c2b7")
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.tick_params(colors="#52514e", labelsize=9)
    ax.grid(axis="y", color="#e1e0d9", linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)


def plot_histogram(values):
    fig, ax = plt.subplots(figsize=(6.4, 2.8), dpi=150)
    counts, bin_edges, patches = ax.hist(values, bins=30, zorder=3)
    for count, lo, hi, patch in zip(counts, bin_edges[:-1], bin_edges[1:], patches):
        mid = (lo + hi) / 2
        patch.set_facecolor(COLOR_NEG if mid < 0 else COLOR_POS)
    if bin_edges[0] < 0 < bin_edges[-1]:
        ax.axvline(0, color="#c3c2b7", linewidth=1, zorder=2)
    _style_axes(ax)
    ax.set_xlabel("EGM2008 − EGM96 (m)", fontsize=9, color="#52514e")
    ax.set_ylabel("pixels (subsampled)", fontsize=9, color="#52514e")
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def plot_map(data, transform, title, vmin, vmax):
    fig, ax = plt.subplots(figsize=(6.0, 6.0 * data.shape[0] / data.shape[1]), dpi=150)
    extent = [transform.c, transform.c + transform.a * data.shape[1],
              transform.f + transform.e * data.shape[0], transform.f]
    im = ax.imshow(data, cmap="RdBu_r", vmin=vmin, vmax=vmax, extent=extent,
                    interpolation="nearest", aspect="auto")
    ax.set_title(title, fontsize=10, color="#0b0b0b")
    ax.set_xlabel("lon", fontsize=8, color="#52514e")
    ax.set_ylabel("lat", fontsize=8, color="#52514e")
    ax.tick_params(labelsize=7, colors="#52514e")
    cbar = fig.colorbar(im, ax=ax, shrink=0.85)
    cbar.set_label("EGM2008 − EGM96 (m)", fontsize=8, color="#52514e")
    cbar.ax.tick_params(labelsize=7, colors="#52514e")
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def build_report():
    with rasterio.open(UNDULATION_TIF) as src:
        full = src.read(1, out_shape=(src.height // 4, src.width // 4))  # subsample for the histogram/full map
        transform_sub = src.transform * src.transform.scale(src.width / full.shape[1], src.height / full.shape[0])
        full_native = src.read(1)
        transform = src.transform
        height, width = src.height, src.width

    valid = full_native[~np.isnan(full_native)]
    vmin, vmax = float(np.nanmin(full_native)), float(np.nanmax(full_native))
    stats = {
        "n": valid.size, "mean": float(valid.mean()), "median": float(np.median(valid)),
        "stdev": float(valid.std()), "min": vmin, "max": vmax,
    }

    hist_uri = plot_histogram(valid[::37])  # subsample for a fast, still-representative histogram

    full_map_uri = plot_map(full, transform_sub, "Montenegro — full extent", vmin, vmax)

    # North inset (~Niksic/Krnovo, higher elevation interior) and south
    # inset (~Ulcinj coast) - chosen to bracket the north-south gradient
    # the coarse-grid stats already show (undulation grows more negative
    # heading north in this bbox), not arbitrary crops.
    def _row_col(lon, lat):
        r, c = rasterio.transform.rowcol(transform, lon, lat)
        return r, c

    def _crop(center_lon, center_lat, half_deg=0.35):
        r0, c0 = _row_col(center_lon - half_deg, center_lat + half_deg)
        r1, c1 = _row_col(center_lon + half_deg, center_lat - half_deg)
        r0, r1 = max(0, r0), min(height, r1)
        c0, c1 = max(0, c0), min(width, c1)
        sub = full_native[r0:r1, c0:c1]
        sub_transform = rasterio.transform.from_origin(
            transform.c + c0 * transform.a, transform.f + r0 * transform.e,
            transform.a, -transform.e,
        )
        return sub, sub_transform

    north_data, north_tf = _crop(19.0, 42.8)   # Niksic/Krnovo area
    south_data, south_tf = _crop(19.15, 41.95)  # Ulcinj coast area
    north_uri = plot_map(north_data, north_tf, "North inset — Nikšić/Krnovo area", vmin, vmax)
    south_uri = plot_map(south_data, south_tf, "South inset — Ulcinj coast area", vmin, vmax)

    north_mean = float(np.nanmean(north_data))
    south_mean = float(np.nanmean(south_data))

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EGM96 vs EGM2008 undulation — Montenegro</title>
<style>
  :root {{
    color-scheme: light;
    --page: #f9f9f7; --surface: #fcfcfb;
    --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #898781;
    --border: rgba(11,11,11,0.10);
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) {{
      color-scheme: dark; --page: #0d0d0d; --surface: #1a1a19;
      --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
      --border: rgba(255,255,255,0.10);
    }}
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark; --page: #0d0d0d; --surface: #1a1a19;
    --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
    --border: rgba(255,255,255,0.10);
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--page); color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif; padding: 32px 20px 64px; }}
  .wrap {{ max-width: 900px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  p.lede {{ color: var(--text-secondary); font-size: 14px; margin: 0 0 28px; }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: 24px; margin-bottom: 24px; overflow-x: auto; }}
  .card h2 {{ font-size: 16px; margin: 0 0 12px; }}
  img {{ max-width: 100%; height: auto; display: block; margin: 0 auto; }}
  .kpi-row {{ display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 16px; }}
  .kpi-label {{ font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; }}
  .kpi-value {{ font-size: 20px; font-weight: 600; margin-top: 2px; }}
  .insets {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  .insets > div {{ flex: 1 1 320px; }}
  footer {{ color: var(--text-muted); font-size: 12px; margin-top: 8px; }}
  footer a {{ color: inherit; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>EGM96 vs. EGM2008 undulation — Montenegro</h1>
  <p class="lede">Why this exists: CopDEM is natively EGM2008, but Montenegro's obstacle data set's
     practical vertical reference is EGM96 (SMATSA's own AIP GEN 2.1 — see docs/montenegro.md).
     This note shows how large that difference actually is across Montenegro, and (a) illustrates
     it as its own layer, and (b) is the basis for a CopDEM raster recalculated onto EGM96
     (<code>data/dem_mosaic_montenegro_egm96.tif</code> = CopDEM &minus; this correction).
     Generated by <code>pipeline/analyze_egm96_undulation_montenegro.py</code> from
     <code>data/egm96_egm2008_undulation_montenegro.tif</code>.</p>

  <section class="card">
    <h2>Summary — EGM2008 &minus; EGM96 (m), whole raster</h2>
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-label">mean</div><div class="kpi-value">{stats['mean']:.3f}</div></div>
      <div class="kpi"><div class="kpi-label">median</div><div class="kpi-value">{stats['median']:.3f}</div></div>
      <div class="kpi"><div class="kpi-label">stdev</div><div class="kpi-value">{stats['stdev']:.3f}</div></div>
      <div class="kpi"><div class="kpi-label">min</div><div class="kpi-value">{stats['min']:.3f}</div></div>
      <div class="kpi"><div class="kpi-label">max</div><div class="kpi-value">{stats['max']:.3f}</div></div>
    </div>
    <p>Every metre of this is a metre CopDEM would be silently wrong by, if compared to
       Montenegro's obstacle elevations without correcting for the geoid difference —
       comparable in scale to a meaningful fraction of CopDEM's own typical error against
       the obstacle base elevations (see reports/obstacles_dem_diff_analysis_montenegro.html:
       CopDEM's single-cell error mean there is ~5m). This correction alone is not small
       enough to ignore, though it is one-directional and smooth (see insets below), unlike
       CopDEM's own noisier per-point error.</p>
    <h2 style="margin-top:24px;">Distribution</h2>
    <img src="{hist_uri}" alt="Histogram of EGM2008-EGM96 undulation across Montenegro">
  </section>

  <section class="card">
    <h2>Full-country map</h2>
    <img src="{full_map_uri}" alt="Map of EGM2008-EGM96 undulation across Montenegro">
  </section>

  <section class="card">
    <h2>Spatial pattern — two area insets</h2>
    <p>The correction is a smooth, large-scale (low-frequency) signal — it varies gradually
       across the country rather than jumping around like terrain-driven DEM error does. These
       two insets, chosen to bracket Montenegro's north-south extent, show the gradient
       directly: mean {north_mean:.3f} m in the north (Nikšić/Krnovo area, interior/higher
       elevation) vs. mean {south_mean:.3f} m in the south (Ulcinj coast) — a real, visible
       shift of about {abs(north_mean - south_mean):.2f} m over roughly {abs(42.8-41.95)*111:.0f} km,
       consistent with EGM96 vs. EGM2008's known long-wavelength differences in this region.</p>
    <div class="insets">
      <div><img src="{north_uri}" alt="North inset map"></div>
      <div><img src="{south_uri}" alt="South inset map"></div>
    </div>
  </section>

  <footer>
    Method: correction(lon,lat) = EGM2008 height &minus; EGM96 height for the SAME point,
    computed via pyproj compound-CRS transforms through WGS84 ellipsoidal height (see
    vertical_datum.py), on a coarse ~3km grid and bilinearly upsampled to CopDEM's native
    resolution (see build_egm96_undulation_raster.py for why this is exact — geoid undulation
    is a function of position only, not of the height being converted). Not obstacle-based —
    this is a whole-country raster comparison; see docs/montenegro.md for the full story
    including why Montenegro's TRUE national datum (Trieste height, EPSG:5195) couldn't be
    used directly.
  </footer>
</div>
</body>
</html>
"""
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html_doc, encoding="utf-8")
    print(f"wrote {OUTPUT_HTML}")


if __name__ == "__main__":
    build_report()
