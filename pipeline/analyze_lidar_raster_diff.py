#!/usr/bin/env python3
"""Generate a self-contained static HTML analytical report for
data/dem_diff_lidar_10m.tif: distribution + summary statistics for the
whole-country CopDEM-vs-LiDAR raster difference (10m grid, EGM2008, see
docs/lidar_comparison.md for how this raster was built).

Separate from reports/obstacles_dem_diff_analysis.html on purpose - that
report analyzes point comparisons AT obstacle locations (both DEM sources
vs. obstacle base elevation); this one analyzes the raster comparison
BETWEEN the two DEM sources, over the whole country, not just at obstacle
points. Different question, different report, per how it was asked for.

The raster is ~1.85 billion pixels - too large to read in full for
statistics. Stats and the histogram are computed from a SUBSAMPLED read
(rasterio's decimated read via out_shape), not the full raster. This is
whole-country terrain, not point samples, so there's no "obstacle type"
equivalent to break down by - this report is a single distribution, not
a by-category breakdown like the obstacle report.
"""
import html
import statistics as st
from pathlib import Path

import _rasterio_compat  # noqa: F401
import numpy as np
import rasterio
from rasterio.enums import Resampling

ROOT_DIR = Path(__file__).parent.parent
RASTER_PATH = ROOT_DIR / "data" / "dem_diff_lidar_10m.tif"
OUTPUT_HTML = ROOT_DIR / "reports" / "copdem_lidar_raster_diff_analysis.html"

# Subsample factor: read at 1/SUBSAMPLE of native resolution in each
# dimension. At the raster's ~58061x31793 native size, /15 gives a
# ~3871x2120 (~8.2M pixel) sample - large enough for stable statistics
# and a smooth histogram, small enough to hold comfortably in memory.
SUBSAMPLE = 15


def _fmt(v, decimals=2):
    return f"{v:,.{decimals}f}"


def load_subsampled(raster_path=RASTER_PATH, subsample=SUBSAMPLE):
    with rasterio.open(raster_path) as src:
        out_shape = (1, src.height // subsample, src.width // subsample)
        data = src.read(1, out_shape=out_shape, resampling=Resampling.average)
        native_shape = (src.height, src.width)
        native_res = src.res
    return data, native_shape, native_res


def compute_stats(values):
    sorted_vals = np.sort(values)
    n = len(sorted_vals)

    def pct(p):
        idx = min(n - 1, max(0, round(p / 100 * (n - 1))))
        return float(sorted_vals[idx])

    return {
        "n": n,
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "stdev": float(np.std(values, ddof=1)) if n > 1 else 0.0,
        "min": float(sorted_vals[0]),
        "max": float(sorted_vals[-1]),
        "p1": pct(1),
        "p5": pct(5),
        "p95": pct(95),
        "p99": pct(99),
    }


def histogram(values, n_bins=30):
    lo, hi = float(np.min(values)), float(np.max(values))
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    counts, edges = np.histogram(values, bins=n_bins, range=(lo, hi))
    return [(edges[i], edges[i + 1], int(counts[i])) for i in range(n_bins)]


def svg_histogram(bins, width=760, height=260):
    pad_l, pad_r, pad_t, pad_b = 50, 16, 16, 30
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    max_count = max(c for _, _, c in bins) or 1
    n_bins = len(bins)
    bin_px = plot_w / n_bins
    gap = 1.5

    bars = []
    for i, (lo, hi, count) in enumerate(bins):
        bar_h = (count / max_count) * plot_h
        x = pad_l + i * bin_px
        y = pad_t + (plot_h - bar_h)
        w = max(1.0, bin_px - gap)
        mid = (lo + hi) / 2
        color = "var(--series-neg)" if mid < 0 else "var(--series-pos)"
        bars.append(
            f'<rect class="bar" x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{bar_h:.2f}" '
            f'rx="2" fill="{color}" '
            f'data-tip="{_fmt(lo,1)} to {_fmt(hi,1)} m: {count:,} cells (subsampled)"/>'
        )

    zero_line = ""
    lo0, hi0 = bins[0][0], bins[-1][1]
    if lo0 < 0 < hi0:
        zero_x = pad_l + ((0 - lo0) / (hi0 - lo0)) * plot_w
        zero_line = (
            f'<line x1="{zero_x:.2f}" y1="{pad_t}" x2="{zero_x:.2f}" y2="{pad_t + plot_h}" class="zero-line"/>'
        )

    ticks = []
    for frac in (0, 0.25, 0.5, 0.75, 1):
        val = lo0 + frac * (hi0 - lo0)
        x = pad_l + frac * plot_w
        anchor = "start" if frac == 0 else "end" if frac == 1 else "middle"
        ticks.append(f'<text x="{x:.2f}" y="{height - 8}" class="axis-label" text-anchor="{anchor}">{_fmt(val,0)}</text>')
    y_ticks = []
    for frac in (0, 1):
        y = pad_t + (1 - frac) * plot_h
        val = frac * max_count
        y_ticks.append(f'<text x="{pad_l - 6}" y="{y + 4:.2f}" class="axis-label" text-anchor="end">{int(val):,}</text>')

    baseline = f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" y2="{pad_t + plot_h}" class="baseline"/>'

    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="Histogram of CopDEM minus LiDAR">'
        + "".join(bars) + zero_line + baseline + "".join(ticks) + "".join(y_ticks)
        + "</svg>"
    )


def render_stats_table(s):
    rows = [
        ("n (subsampled cells)", f"{s['n']:,}"),
        ("mean", _fmt(s["mean"])),
        ("median", _fmt(s["median"])),
        ("stdev", _fmt(s["stdev"])),
        ("p1", _fmt(s["p1"])),
        ("p5", _fmt(s["p5"])),
        ("p95", _fmt(s["p95"])),
        ("p99", _fmt(s["p99"])),
        ("min", _fmt(s["min"])),
        ("max", _fmt(s["max"])),
    ]
    rows_html = "".join(f"<tr><td>{html.escape(k)}</td><td class='num'>{v}</td></tr>" for k, v in rows)
    return f"<table class='stats-table'><tbody>{rows_html}</tbody></table>"


def build_report():
    data, native_shape, native_res = load_subsampled()
    valid = data[~np.isnan(data)]
    coverage_pct = 100 * valid.size / data.size

    stats = compute_stats(valid)
    bins = histogram(valid)
    hist_svg = svg_histogram(bins)

    native_px = native_shape[0] * native_shape[1]

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CopDEM vs. LiDAR &#8212; raster difference analysis (Austria)</title>
<style>
  :root {{
    color-scheme: light;
    --page: #f9f9f7; --surface: #fcfcfb;
    --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #898781;
    --gridline: #e1e0d9; --baseline: #c3c2b7; --border: rgba(11,11,11,0.10);
    --series-pos: #e34948; --series-neg: #2a78d6;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) {{
      color-scheme: dark;
      --page: #0d0d0d; --surface: #1a1a19;
      --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
      --gridline: #2c2c2a; --baseline: #383835; --border: rgba(255,255,255,0.10);
      --series-pos: #e66767; --series-neg: #3987e5;
    }}
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19;
    --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
    --gridline: #2c2c2a; --baseline: #383835; --border: rgba(255,255,255,0.10);
    --series-pos: #e66767; --series-neg: #3987e5;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--page); color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    padding: 32px 20px 64px;
  }}
  .wrap {{ max-width: 900px; margin: 0 auto; }}
  header h1 {{ font-size: 22px; margin: 0 0 4px; }}
  header p {{ color: var(--text-secondary); margin: 0 0 28px; font-size: 14px; }}
  .card {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: 24px; margin-bottom: 24px; overflow-x: auto;
  }}
  .card-title {{ font-size: 17px; margin: 0 0 4px; font-weight: 600; }}
  .card h4 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted); margin: 24px 0 10px; }}
  .desc {{ color: var(--text-secondary); font-size: 13px; margin: 0 0 16px; max-width: 640px; }}
  .kpi-row {{ display: flex; gap: 24px; flex-wrap: wrap; }}
  .kpi-label {{ font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; }}
  .kpi-value {{ font-size: 20px; font-weight: 600; margin-top: 2px; }}
  .chart {{ display: block; max-width: 100%; height: auto; overflow: visible; }}
  .bar {{ transition: opacity 0.1s; cursor: pointer; }}
  .bar:hover, .bar:focus {{ opacity: 0.75; outline: none; }}
  .zero-line {{ stroke: var(--baseline); stroke-width: 1; }}
  .baseline {{ stroke: var(--baseline); stroke-width: 1; }}
  .axis-label {{ font-size: 10px; fill: var(--text-muted); font-variant-numeric: tabular-nums; }}
  table.stats-table {{ border-collapse: collapse; width: 100%; max-width: 360px; font-size: 13px; margin-bottom: 8px; }}
  table.stats-table td {{ padding: 6px 10px; border-bottom: 1px solid var(--gridline); }}
  table.stats-table td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  table.stats-table tr:hover {{ background: rgba(128,128,128,0.06); }}
  footer {{ color: var(--text-muted); font-size: 12px; margin-top: 8px; }}
  footer a {{ color: inherit; }}
  #tooltip {{
    position: fixed; pointer-events: none; z-index: 10;
    background: var(--text-primary); color: var(--surface);
    font-size: 12px; padding: 6px 10px; border-radius: 6px;
    max-width: 280px; opacity: 0; transition: opacity 0.08s;
  }}
  #tooltip.visible {{ opacity: 1; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>CopDEM vs. LiDAR &#8212; raster difference analysis (Austria)</h1>
    <p>Whole-country per-cell comparison, 10&#160;m grid (LiDAR's native resolution &#8212; CopDEM
       upsampled onto it), EGM2008 &#8212; not obstacle-based; see
       <a href="obstacles_dem_diff_analysis.html">obstacles_dem_diff_analysis.html</a> for the
       point comparisons at obstacle locations. Generated by
       <code>pipeline/analyze_lidar_raster_diff.py</code> from <code>data/dem_diff_lidar_10m.tif</code>.
       Raster build method and the LiDAR vertical-datum source (GHA height, EPSG:5778):
       <a href="../docs/lidar_comparison.md">docs/lidar_comparison.md</a>.</p>
  </header>

  <section class="card">
    <h3 class="card-title">CopDEM &#8722; LiDAR (m)</h3>
    <p class="desc">Positive = CopDEM reads above LiDAR. Computed from a subsampled read
       (every {SUBSAMPLE}th pixel in each direction &#8212; {stats['n']:,} sample cells from
       {native_px:,} native 10&#160;m cells; the full raster is too large to load in full for
       statistics). {coverage_pct:.1f}% of the sampled area has valid data in both sources
       (the rest is outside Austria's LiDAR coverage or outside CopDEM's fetched extent).</p>
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-label">mean</div><div class="kpi-value">{_fmt(stats['mean'])}</div></div>
      <div class="kpi"><div class="kpi-label">median</div><div class="kpi-value">{_fmt(stats['median'])}</div></div>
      <div class="kpi"><div class="kpi-label">stdev</div><div class="kpi-value">{_fmt(stats['stdev'])}</div></div>
      <div class="kpi"><div class="kpi-label">p5&#8211;p95</div><div class="kpi-value">{_fmt(stats['p5'])} &#8211; {_fmt(stats['p95'])}</div></div>
      <div class="kpi"><div class="kpi-label">p1&#8211;p99</div><div class="kpi-value">{_fmt(stats['p1'])} &#8211; {_fmt(stats['p99'])}</div></div>
    </div>
    <h4>Distribution</h4>
    {hist_svg}
    <h4>Summary statistics</h4>
    {render_stats_table(stats)}
  </section>

  <footer>
    No by-category breakdown here (unlike the obstacle report) &#8212; this is a whole-country
    raster comparison with no natural category to group by. Min/max reflect the &#177;100&#160;m
    sanity clip applied during raster construction (a defensive guard, not a real signal &#8212;
    see docs/lidar_comparison.md); p1/p99 are shown instead as the more meaningful tail measure.
  </footer>
</div>
<div id="tooltip"></div>
<script>
  const tip = document.getElementById('tooltip');
  document.querySelectorAll('[data-tip]').forEach(el => {{
    el.setAttribute('tabindex', '0');
    const show = (evt) => {{
      tip.textContent = el.getAttribute('data-tip');
      tip.classList.add('visible');
      const x = evt.clientX !== undefined ? evt.clientX : el.getBoundingClientRect().left;
      const y = evt.clientY !== undefined ? evt.clientY : el.getBoundingClientRect().top;
      tip.style.left = Math.min(x + 12, window.innerWidth - 290) + 'px';
      tip.style.top = Math.max(y - 36, 4) + 'px';
    }};
    const hide = () => tip.classList.remove('visible');
    el.addEventListener('pointermove', show);
    el.addEventListener('pointerenter', show);
    el.addEventListener('pointerleave', hide);
    el.addEventListener('focus', show);
    el.addEventListener('blur', hide);
  }});
</script>
</body>
</html>
"""
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html_doc, encoding="utf-8")
    print(f"wrote {OUTPUT_HTML}")


if __name__ == "__main__":
    build_report()
