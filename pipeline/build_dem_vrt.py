#!/usr/bin/env python3
"""Build a GDAL VRT mosaic of the cached DEM chunks, for QGIS visualization
ONLY — never used for the actual numeric comparison (see
docs/dem_extraction.md for why: chunks span slightly different
degrees-per-pixel across latitude bands, so a common-grid mosaic implies
resampling some sources; fine for display, wrong for analysis).

Hand-built (no osgeo/GDAL Python bindings or gdalbuildvrt CLI available in
this environment) but follows the standard VRT XML schema, so any real GDAL
install can also open/rebuild it normally.
"""
import xml.etree.ElementTree as ET
from pathlib import Path

import _rasterio_compat  # noqa: F401
import rasterio

DEM_DIR = Path(__file__).parent.parent / "data" / "dem_tiles"
OUTPUT_VRT = Path(__file__).parent.parent / "data" / "dem_mosaic.vrt"


def build_vrt(dem_dir=DEM_DIR, output_vrt=OUTPUT_VRT):
    tiles = sorted(dem_dir.glob("dem_*.tif"))
    if not tiles:
        raise FileNotFoundError(f"No DEM tiles found in {dem_dir}")

    metas = []
    for path in tiles:
        with rasterio.open(path) as src:
            metas.append({
                "path": path,
                "bounds": src.bounds,
                "width": src.width,
                "height": src.height,
                "nodata": src.nodata,
            })

    # Target grid: use the resolution of the middle-latitude chunk as a
    # representative compromise (see module docstring — this is a display
    # convenience, not a precision decision).
    mid = metas[len(metas) // 2]
    px_w = (mid["bounds"].right - mid["bounds"].left) / mid["width"]
    px_h = (mid["bounds"].top - mid["bounds"].bottom) / mid["height"]

    min_x = min(m["bounds"].left for m in metas)
    max_x = max(m["bounds"].right for m in metas)
    min_y = min(m["bounds"].bottom for m in metas)
    max_y = max(m["bounds"].top for m in metas)

    vrt_width = round((max_x - min_x) / px_w)
    vrt_height = round((max_y - min_y) / px_h)

    root = ET.Element("VRTDataset", rasterXSize=str(vrt_width), rasterYSize=str(vrt_height))
    srs = ET.SubElement(root, "SRS")
    srs.text = "EPSG:4326"
    geotransform = ET.SubElement(root, "GeoTransform")
    geotransform.text = f"{min_x}, {px_w}, 0.0, {max_y}, 0.0, {-px_h}"

    band = ET.SubElement(root, "VRTRasterBand", dataType="Float32", band="1")
    ET.SubElement(band, "NoDataValue").text = "nan"
    color_interp = ET.SubElement(band, "ColorInterp")
    color_interp.text = "Gray"

    for m in metas:
        b = m["bounds"]
        dst_x_off = round((b.left - min_x) / px_w)
        dst_y_off = round((max_y - b.top) / px_h)
        dst_w = round((b.right - b.left) / px_w)
        dst_h = round((b.top - b.bottom) / px_h)

        source = ET.SubElement(band, "SimpleSource")
        ET.SubElement(source, "SourceFilename", relativeToVRT="1").text = f"dem_tiles/{m['path'].name}"
        ET.SubElement(source, "SourceBand").text = "1"
        ET.SubElement(source, "SrcRect", xOff="0", yOff="0",
                      xSize=str(m["width"]), ySize=str(m["height"]))
        ET.SubElement(source, "DstRect", xOff=str(dst_x_off), yOff=str(dst_y_off),
                      xSize=str(dst_w), ySize=str(dst_h))

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    output_vrt.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_vrt, encoding="unicode" if False else "UTF-8", xml_declaration=False)
    print(f"wrote {output_vrt} ({vrt_width}x{vrt_height}, {len(metas)} sources)")


if __name__ == "__main__":
    build_vrt()
