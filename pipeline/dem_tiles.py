#!/usr/bin/env python3
"""Fetch Copernicus DEM GLO-30 coverage for a bounding box from CDSE, with
local caching, via the Sentinel Hub Process API.

Why Process API rather than raw OData product download: the OData catalogue
for COP-DEM_GLO-30-DGED returns raw per-acquisition SAR strip products (many
overlapping files per area) — the pre-mosaic inputs, not a clean final tile.
Process API returns the already-mosaicked, edge-matched product for an
arbitrary bbox, which is what a validation study actually wants to sample.

egm=false keeps heights in the product's native EGM2008 reference (see
vertical_datum.py for the pipeline's own, auditable geoid conversions,
rather than relying on any API's implicit "egm" conversion).

Process API has a per-request output size limit, so a bbox is split into a
grid of chunks sized to stay under it, each chunk cached as its own GeoTIFF.
"""
import math
from pathlib import Path

import requests

from cdse_auth import get_access_token

PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

CACHE_DIR = Path(__file__).parent.parent / "data" / "dem_tiles"

# Approximate bounding box for Austria (min_lon, min_lat, max_lon, max_lat)
AUSTRIA_BBOX = (9.5, 46.35, 17.2, 49.05)

# Approximate bounding box for Montenegro, with a small margin so the
# westernmost/southernmost obstacle points (Ulcinj-Mozura wind farm, near
# the coast/Albania border) aren't right at a chunk edge.
MONTENEGRO_BBOX = (18.35, 41.75, 20.45, 43.65)

METERS_PER_DEG_LAT = 111_320  # ~constant everywhere
TARGET_RESOLUTION_M = 30

# Sentinel Hub Process API's synchronous request hard limit is 2500x2500 px.
# Use it fully (minus a small margin for rounding) rather than an arbitrary
# smaller cap, so chunks stay close to the DEM's native ~1deg tile size.
MAX_CHUNK_PX = 2490


def _lat_deg_per_pixel():
    return TARGET_RESOLUTION_M / METERS_PER_DEG_LAT


def _lon_deg_per_pixel(lat_deg):
    # A degree of longitude shrinks by cos(latitude) relative to a degree of
    # latitude — correct for it so pixels are ~30 m on the ground in both
    # directions, instead of oversampling longitude at higher latitudes.
    meters_per_deg_lon = METERS_PER_DEG_LAT * math.cos(math.radians(lat_deg))
    return TARGET_RESOLUTION_M / meters_per_deg_lon

EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: ["DEM"],
    output: { id: "default", bands: 1, sampleType: "FLOAT32" }
  };
}
function evaluatePixel(sample) {
  return [sample.DEM];
}
"""


def _chunk_bbox(bbox):
    min_lon, min_lat, max_lon, max_lat = bbox
    mid_lat = (min_lat + max_lat) / 2
    chunk_lat_deg = MAX_CHUNK_PX * _lat_deg_per_pixel()
    chunk_lon_deg = MAX_CHUNK_PX * _lon_deg_per_pixel(mid_lat)

    lon_steps = max(1, math.ceil((max_lon - min_lon) / chunk_lon_deg))
    lat_steps = max(1, math.ceil((max_lat - min_lat) / chunk_lat_deg))
    lon_edges = [min_lon + i * (max_lon - min_lon) / lon_steps for i in range(lon_steps + 1)]
    lat_edges = [min_lat + i * (max_lat - min_lat) / lat_steps for i in range(lat_steps + 1)]
    chunks = []
    for i in range(lon_steps):
        for j in range(lat_steps):
            chunks.append((lon_edges[i], lat_edges[j], lon_edges[i + 1], lat_edges[j + 1]))
    return chunks


def _chunk_filename(chunk):
    min_lon, min_lat, max_lon, max_lat = chunk
    return f"dem_{min_lon:.4f}_{min_lat:.4f}_{max_lon:.4f}_{max_lat:.4f}.tif"


def fetch_chunk(chunk, access_token: str, dest_dir: Path, width: int, height: int) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_path = dest_dir / _chunk_filename(chunk)
    if out_path.exists():
        return out_path  # already cached

    min_lon, min_lat, max_lon, max_lat = chunk
    request_body = {
        "input": {
            "bounds": {
                "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
                "bbox": [min_lon, min_lat, max_lon, max_lat],
            },
            "data": [
                {
                    "type": "dem",
                    "dataFilter": {"demInstance": "COPERNICUS_30"},
                    "processing": {
                        "egm": False,  # keep native EGM2008 height
                        "upsampling": "BILINEAR",
                        "downsampling": "BILINEAR",
                    },
                }
            ],
        },
        "output": {
            "width": width,
            "height": height,
            "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],
        },
        "evalscript": EVALSCRIPT,
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "image/tiff",
    }
    resp = requests.post(PROCESS_URL, json=request_body, headers=headers, timeout=120)
    resp.raise_for_status()
    out_path.write_bytes(resp.content)
    return out_path


def _chunk_size_px(chunk):
    min_lon, min_lat, max_lon, max_lat = chunk
    mid_lat = (min_lat + max_lat) / 2
    width = max(1, round((max_lon - min_lon) / _lon_deg_per_pixel(mid_lat)))
    height = max(1, round((max_lat - min_lat) / _lat_deg_per_pixel()))
    return width, height


def ensure_coverage(bbox=AUSTRIA_BBOX, dest_dir: Path = CACHE_DIR) -> list[Path]:
    """Fetch (or reuse cached) DEM GeoTIFF chunks covering bbox."""
    chunks = _chunk_bbox(bbox)
    access_token = get_access_token()
    paths = []
    for chunk in chunks:
        width, height = _chunk_size_px(chunk)
        path = fetch_chunk(chunk, access_token, dest_dir, width, height)
        print(f"cached {path.name} ({width}x{height})")
        paths.append(path)
    return paths


if __name__ == "__main__":
    chunks = _chunk_bbox(AUSTRIA_BBOX)
    print(f"Austria bbox {AUSTRIA_BBOX} -> {len(chunks)} chunk(s)")
    for c in chunks:
        w, h = _chunk_size_px(c)
        print(" -", tuple(round(v, 4) for v in c), f"{w}x{h}px")
