#!/usr/bin/env python3
"""Generate a self-contained static HTML analytical report for
obstacles_dem_diff.csv: distribution + summary statistics for
error_single_m (the single-cell DEM-vs-obstacle-base error) and
dem_5x5_median_egm2008_m (the 5x5-window median DEM elevation — a raw
elevation value, NOT an error, on EGM2008), for the whole dataset and
broken down by obstacle type.

Charts are hand-rolled inline SVG (no external chart library / CDN), per
the dataviz skill: histograms use the diverging blue/red pair for the
signed error field and sequential blue for the unsigned elevation field;
by-type bar charts are horizontal (obstacle type names are long); every
mark carries a hover tooltip.

See docs/output_fields.md for what each field means.
"""
import csv
import html
import statistics as st
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
DIFF_CSV = ROOT_DIR / "data" / "obstacles" / "austria" / "obstacles_dem_diff.csv"
OUTPUT_HTML = ROOT_DIR / "reports" / "obstacles_dem_diff_analysis.html"

FIELDS = {
    "error_single_m": {
        "label": "Single-cell error",
        "unit": "m",
        "kind": "diverging",  # signed, centered on 0
        "description": "DEM (single-cell, bilinear) minus obstacle base elevation, both on EGM2008. Positive = DEM reads above the true base.",
    },
    "dem_5x5_median_egm2008_m": {
        "label": "5×5-window median DEM elevation",
        "unit": "m",
        "kind": "sequential",  # unsigned magnitude, NOT an error
        "description": "Raw DEM elevation (EGM2008) — the median of the 25 cells around each obstacle. Not an error value; shown for its own distribution across the dataset.",
    },
}

MIN_TYPE_N_FOR_NOTE = 5  # types below this get an explicit low-n caveat, not excluded


def load_rows(csv_path=DIFF_CSV):
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def values_for(rows, field):
    return [float(r[field]) for r in rows if r.get(field)]


def compute_stats(values):
    if not values:
        return None
    sorted_vals = sorted(values)
    n = len(sorted_vals)

    def pct(p):
        idx = min(n - 1, max(0, round(p / 100 * (n - 1))))
        return sorted_vals[idx]

    return {
        "n": n,
        "mean": st.mean(values),
        "median": st.median(values),
        "stdev": st.stdev(values) if n > 1 else 0.0,
        "min": sorted_vals[0],
        "max": sorted_vals[-1],
        "p5": pct(5),
        "p95": pct(95),
    }


def histogram(values, n_bins=24):
    lo, hi = min(values), max(values)
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    width = (hi - lo) / n_bins
    counts = [0] * n_bins
    for v in values:
        idx = min(n_bins - 1, int((v - lo) / width))
        counts[idx] += 1
    return [(lo + i * width, lo + (i + 1) * width, counts[i]) for i in range(n_bins)]


def by_type_stats(rows, field):
    types = {}
    for r in rows:
        if not r.get(field):
            continue
        types.setdefault(r["obstacle_type"], []).append(float(r[field]))
    result = []
    for type_name, values in types.items():
        stats = compute_stats(values)
        stats["type"] = type_name
        result.append(stats)
    result.sort(key=lambda s: s["mean"])
    return result


# ---------------------------------------------------------------------------
# SVG rendering
# ---------------------------------------------------------------------------

def _fmt(v, decimals=1):
    return f"{v:,.{decimals}f}"


def svg_histogram(bins, kind, chart_id, width=640, height=220):
    pad_l, pad_r, pad_t, pad_b = 44, 16, 16, 28
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    max_count = max(c for _, _, c in bins) or 1
    n_bins = len(bins)
    bin_px = plot_w / n_bins
    gap = 2

    bars = []
    for i, (lo, hi, count) in enumerate(bins):
        bar_h = (count / max_count) * plot_h
        x = pad_l + i * bin_px
        y = pad_t + (plot_h - bar_h)
        w = max(1.0, bin_px - gap)
        mid = (lo + hi) / 2
        if kind == "diverging":
            color = "var(--series-neg)" if mid < 0 else "var(--series-pos)"
        else:
            color = "var(--series-seq)"
        bars.append(
            f'<rect class="bar" x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{bar_h:.2f}" '
            f'rx="3" fill="{color}" '
            f'data-tip="{_fmt(lo)}–{_fmt(hi)} {chart_id}: {count:,} obstacle{"s" if count != 1 else ""}"/>'
        )

    # zero line for diverging charts
    zero_line = ""
    if kind == "diverging":
        lo0, hi0 = bins[0][0], bins[-1][1]
        if lo0 < 0 < hi0:
            zero_x = pad_l + ((0 - lo0) / (hi0 - lo0)) * plot_w
            zero_line = (
                f'<line x1="{zero_x:.2f}" y1="{pad_t}" x2="{zero_x:.2f}" y2="{pad_t + plot_h}" '
                f'class="zero-line"/>'
            )

    # axis ticks: min, mid, max of bin range
    lo_all, hi_all = bins[0][0], bins[-1][1]
    ticks = []
    for frac in (0, 0.5, 1):
        val = lo_all + frac * (hi_all - lo_all)
        x = pad_l + frac * plot_w
        ticks.append(
            f'<text x="{x:.2f}" y="{height - 6}" class="axis-label" '
            f'text-anchor="{"start" if frac == 0 else "end" if frac == 1 else "middle"}">{_fmt(val, 0)}</text>'
        )
    y_ticks = []
    for frac in (0, 1):
        y = pad_t + (1 - frac) * plot_h
        val = frac * max_count
        y_ticks.append(
            f'<text x="{pad_l - 6}" y="{y + 4:.2f}" class="axis-label" text-anchor="end">{int(val):,}</text>'
        )

    baseline = f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" y2="{pad_t + plot_h}" class="baseline"/>'

    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="Histogram">'
        + "".join(bars) + zero_line + baseline + "".join(ticks) + "".join(y_ticks)
        + "</svg>"
    )


def svg_bar_by_type(type_stats, kind, chart_id, width=640):
    row_h = 26
    pad_l, pad_r, pad_t = 190, 60, 8
    plot_w = width - pad_l - pad_r
    height = pad_t * 2 + row_h * len(type_stats)

    vals = [s["mean"] for s in type_stats]
    if kind == "diverging":
        span = max(abs(min(vals)), abs(max(vals)), 0.001)
        lo, hi = -span, span
    else:
        lo = min(0, min(vals))
        hi = max(vals) * 1.05 if max(vals) > 0 else 1

    def xpos(v):
        return pad_l + ((v - lo) / (hi - lo)) * plot_w

    zero_x = xpos(0)
    bars = []
    labels = []
    for i, s in enumerate(type_stats):
        y = pad_t + i * row_h
        v = s["mean"]
        x0, x1 = sorted([xpos(0), xpos(v)])
        w = max(1.0, x1 - x0)
        if kind == "diverging":
            color = "var(--series-neg)" if v < 0 else "var(--series-pos)"
        else:
            color = "var(--series-seq)"
        type_label = html.escape(s["type"])
        bars.append(
            f'<rect class="bar hbar" x="{x0:.2f}" y="{y + 4:.2f}" width="{w:.2f}" height="{row_h - 10}" '
            f'rx="3" fill="{color}" '
            f'data-tip="{type_label} (n={s["n"]:,}): mean {_fmt(v)} m, median {_fmt(s["median"])} m"/>'
        )
        labels.append(
            f'<text x="{pad_l - 8}" y="{y + row_h / 2 + 4:.2f}" class="type-label" text-anchor="end">'
            f'{type_label}{" &#8224;" if s["n"] < MIN_TYPE_N_FOR_NOTE else ""}</text>'
        )
        value_label_x = x1 + 6 if v >= 0 else x0 - 6
        anchor = "start" if v >= 0 else "end"
        labels.append(
            f'<text x="{value_label_x:.2f}" y="{y + row_h / 2 + 4:.2f}" class="value-label" text-anchor="{anchor}">'
            f'{_fmt(v)}</text>'
        )

    zero_line = f'<line x1="{zero_x:.2f}" y1="{pad_t}" x2="{zero_x:.2f}" y2="{height - pad_t}" class="zero-line"/>' if kind == "diverging" else ""

    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="Mean by obstacle type">'
        + "".join(bars) + zero_line + "".join(labels) + "</svg>"
    )


def render_table(type_stats, field_key, field_meta):
    rows_html = []
    for s in type_stats:
        low_n_flag = " &#8224;" if s["n"] < MIN_TYPE_N_FOR_NOTE else ""
        rows_html.append(
            "<tr>"
            f"<td>{html.escape(s['type'])}{low_n_flag}</td>"
            f"<td class='num'>{s['n']:,}</td>"
            f"<td class='num'>{_fmt(s['mean'])}</td>"
            f"<td class='num'>{_fmt(s['median'])}</td>"
            f"<td class='num'>{_fmt(s['stdev'])}</td>"
            f"<td class='num'>{_fmt(s['min'])}</td>"
            f"<td class='num'>{_fmt(s['max'])}</td>"
            "</tr>"
        )
    return (
        "<table class='stats-table'><thead><tr>"
        "<th>Obstacle type</th><th>n</th><th>mean</th><th>median</th><th>stdev</th><th>min</th><th>max</th>"
        "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
    )


def render_overall_table(overall):
    rows_html = []
    for field_key, meta in FIELDS.items():
        s = overall[field_key]
        rows_html.append(
            "<tr>"
            f"<td>{html.escape(meta['label'])}</td>"
            f"<td class='num'>{s['n']:,}</td>"
            f"<td class='num'>{_fmt(s['mean'])}</td>"
            f"<td class='num'>{_fmt(s['median'])}</td>"
            f"<td class='num'>{_fmt(s['stdev'])}</td>"
            f"<td class='num'>{_fmt(s['p5'])}</td>"
            f"<td class='num'>{_fmt(s['p95'])}</td>"
            f"<td class='num'>{_fmt(s['min'])}</td>"
            f"<td class='num'>{_fmt(s['max'])}</td>"
            "</tr>"
        )
    return (
        "<table class='stats-table'><thead><tr>"
        "<th>Field</th><th>n</th><th>mean</th><th>median</th><th>stdev</th><th>p5</th><th>p95</th><th>min</th><th>max</th>"
        "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
    )


def build_report():
    rows = load_rows()
    overall = {}
    hist_svgs = {}
    type_stats = {}
    bar_svgs = {}

    for field_key, meta in FIELDS.items():
        values = values_for(rows, field_key)
        overall[field_key] = compute_stats(values)
        bins = histogram(values)
        hist_svgs[field_key] = svg_histogram(bins, meta["kind"], meta["label"])
        ts = by_type_stats(rows, field_key)
        type_stats[field_key] = ts
        bar_svgs[field_key] = svg_bar_by_type(ts, meta["kind"], meta["label"])

    n_total = len(rows)
    n_window = overall["dem_5x5_median_egm2008_m"]["n"]

    sections = []
    for field_key, meta in FIELDS.items():
        s = overall[field_key]
        sections.append(f"""
        <section class="card">
          <h2>{html.escape(meta['label'])} <span class="unit">({meta['unit']})</span></h2>
          <p class="desc">{html.escape(meta['description'])}</p>
          <div class="kpi-row">
            <div class="kpi"><div class="kpi-label">n</div><div class="kpi-value">{s['n']:,}</div></div>
            <div class="kpi"><div class="kpi-label">mean</div><div class="kpi-value">{_fmt(s['mean'])}</div></div>
            <div class="kpi"><div class="kpi-label">median</div><div class="kpi-value">{_fmt(s['median'])}</div></div>
            <div class="kpi"><div class="kpi-label">stdev</div><div class="kpi-value">{_fmt(s['stdev'])}</div></div>
            <div class="kpi"><div class="kpi-label">p5&#8211;p95</div><div class="kpi-value">{_fmt(s['p5'])} &#8211; {_fmt(s['p95'])}</div></div>
          </div>
          <h3>Distribution (whole dataset)</h3>
          {hist_svgs[field_key]}
          <h3>By obstacle type</h3>
          {render_table(type_stats[field_key], field_key, meta)}
          <p class="chart-caption">Mean {html.escape(meta['label'].lower())} by type (bar length = mean; hover for n and median). Types marked &#8224; have n &lt; {MIN_TYPE_N_FOR_NOTE} &#8212; too few points for the mean to be a stable estimate; shown for completeness, not to be read as a trend.</p>
          {bar_svgs[field_key]}
        </section>
        """)

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Obstacle vs. DEM — Analysis (Austria)</title>
<style>
  :root {{
    color-scheme: light;
    --page: #f9f9f7; --surface: #fcfcfb;
    --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #898781;
    --gridline: #e1e0d9; --baseline: #c3c2b7; --border: rgba(11,11,11,0.10);
    --series-seq: #2a78d6; --series-pos: #e34948; --series-neg: #2a78d6;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) {{
      color-scheme: dark;
      --page: #0d0d0d; --surface: #1a1a19;
      --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
      --gridline: #2c2c2a; --baseline: #383835; --border: rgba(255,255,255,0.10);
      --series-seq: #3987e5; --series-pos: #e66767; --series-neg: #3987e5;
    }}
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19;
    --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
    --gridline: #2c2c2a; --baseline: #383835; --border: rgba(255,255,255,0.10);
    --series-seq: #3987e5; --series-pos: #e66767; --series-neg: #3987e5;
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
  .card h2 {{ font-size: 17px; margin: 0 0 4px; }}
  .card h2 .unit {{ color: var(--text-muted); font-weight: 400; font-size: 14px; }}
  .card h3 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted); margin: 24px 0 10px; }}
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
  .type-label {{ font-size: 11px; fill: var(--text-secondary); }}
  .value-label {{ font-size: 10px; fill: var(--text-muted); font-variant-numeric: tabular-nums; }}
  .chart-caption {{ color: var(--text-muted); font-size: 12px; margin: 0 0 8px; max-width: 640px; }}
  table.stats-table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin-bottom: 8px; }}
  table.stats-table th {{ text-align: left; font-weight: 600; color: var(--text-secondary); border-bottom: 1px solid var(--gridline); padding: 6px 10px; white-space: nowrap; }}
  table.stats-table td {{ padding: 6px 10px; border-bottom: 1px solid var(--gridline); }}
  table.stats-table td.num, table.stats-table th:not(:first-child) {{ text-align: right; font-variant-numeric: tabular-nums; }}
  table.stats-table tbody tr:hover {{ background: rgba(128,128,128,0.06); }}
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
    <h1>Copernicus DEM vs. obstacle base &#8212; analysis (Austria)</h1>
    <p>{n_total:,} obstacles (simple points, v1 scope) &#8226; {n_window:,} with a valid 5&#215;5-window sample &#8226;
       generated by <code>pipeline/analyze_obstacles_diff.py</code> from <code>obstacles_dem_diff.csv</code>.
       Field definitions: see <a href="../docs/output_fields.md">docs/output_fields.md</a>.</p>
  </header>

  <section class="card">
    <h2>Overview</h2>
    {render_overall_table(overall)}
  </section>

  {"".join(sections)}

  <footer>
    &#8224; obstacle type with n &lt; {MIN_TYPE_N_FOR_NOTE} &#8212; too few points for a stable mean.
    See <a href="../docs/dem_extraction.md">docs/dem_extraction.md</a> for sampling method and known limitations
    (e.g. the 4 obstacles excluded from window stats near chunk edges).
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
