#!/usr/bin/env python3
"""Generate a QGIS project file (.qgs, plain XML — not the zipped .qgz) that
loads and symbolizes all the data layers built so far:

  1. Background VHR imagery: Austria's official basemap.at orthophoto
     (~15-30cm resolution), via its public WMTS GetCapabilities endpoint —
     no download needed, QGIS fetches tiles live. See
     docs/qgis_project.md for why this source and how it was verified.
  2. Copernicus DEM GLO-30 mosaic (dem_mosaic.vrt), singleband pseudocolor,
     elevation ramp.
  3. Obstacles (simple points, 1932), small grey markers.
  4. DEM-vs-obstacle-base difference (obstacles_dem_diff.geojson), graduated
     by error_single_m, diverging blue (DEM reads low) / red (DEM reads
     high) centered on zero.

This script is a generator, not a hand-maintained XML file, specifically so
it can be regenerated if any input path or data range changes — re-run it
rather than hand-editing the .qgs after a data refresh.

Caveat (see docs/qgis_project.md): built without a live QGIS instance to
test-open it against, since none is available in this environment. Layer
structure and renderer XML follow QGIS 3.x's documented/observed project
schema, but if QGIS reports a warning on first open, the fix is normally a
quick manual Symbology re-save, not a data problem.
"""
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

import xml.etree.ElementTree
import rasterio

ROOT_DIR = Path(__file__).parent
DEM_VRT = ROOT_DIR / "data" / "dem_mosaic.vrt"
OBSTACLES_GEOJSON = ROOT_DIR / "data" / "obstacles" / "austria" / "obstacles_simple_points.geojson"
DIFF_GEOJSON = ROOT_DIR / "data" / "obstacles" / "austria" / "obstacles_dem_diff.geojson"
OUTPUT_QGS = ROOT_DIR / "copdem_austria.qgs"

BASEMAP_AT_WMTS_CAPABILITIES = "https://maps.wien.gv.at/basemap/1.0.0/WMTSCapabilities.xml"

WGS84_SRS_XML = """<spatialrefsys>
  <geographicflag>true</geographicflag>
  <authid>EPSG:4326</authid>
  <description>WGS 84</description>
  <projectionacronym>longlat</projectionacronym>
  <ellipsoidacronym>EPSG:7030</ellipsoidacronym>
  <geographicflag>true</geographicflag>
</spatialrefsys>"""


def _uuid():
    return "{" + str(uuid4()) + "}"


def _dem_range(vrt_path):
    with rasterio.open(vrt_path) as src:
        data = src.read(1, out_shape=(1, max(1, src.height // 10), max(1, src.width // 10)))
    import numpy as np
    return float(np.nanmin(data)), float(np.nanmax(data))


def _elevation_ramp_items(vmin, vmax):
    # 5-stop terrain-style ramp: blue-green -> yellow -> orange -> red.
    stops = [
        (0.00, "#3288bd"),
        (0.25, "#abdda4"),
        (0.50, "#ffffbf"),
        (0.75, "#fdae61"),
        (1.00, "#d53e4f"),
    ]
    items = []
    for frac, color in stops:
        value = vmin + frac * (vmax - vmin)
        items.append((value, color))
    return items


def _make_marker_symbol(parent, name, color, size="2.2", outline="#404040"):
    symbol = ET.SubElement(parent, "symbol", type="marker", name=name, alpha="1",
                            clip_to_extent="1", force_rhr="0")
    # NOTE: "class" and "pass" are Python reserved words, so they can't be
    # passed as SubElement kwargs (class_= would literally write the
    # attribute name "class_", not "class" - ElementTree does not strip
    # trailing underscores). Use attrib= with the real QGIS attribute names.
    layer = ET.SubElement(symbol, "layer", attrib={
        "class": "SimpleMarker", "enabled": "1", "locked": "0", "pass": "0",
    })
    # QGIS 3.16+ nests symbol-layer properties inside an outer Option
    # type="Map" wrapper (older 3.x used a flatter structure). Using the
    # current nested form since that's what a present-day QGIS install
    # most likely expects.
    props_map = ET.SubElement(layer, "Option", type="Map")
    props = {
        "name": "circle",
        "color": color,
        "outline_color": outline,
        "outline_style": "solid",
        "outline_width": "0.2",
        "size": size,
        "size_unit": "MM",
        "outline_width_unit": "MM",
        "horizontal_anchor_point": "1",
        "vertical_anchor_point": "1",
    }
    for k, v in props.items():
        ET.SubElement(props_map, "Option", type="QString", name=k, value=v)
    return symbol


def _build_dem_layer(layer_id):
    vmin, vmax = _dem_range(DEM_VRT)
    maplayer = ET.Element("maplayer", type="raster", hasScaleBasedVisibilityFlag="0")
    ET.SubElement(maplayer, "id").text = layer_id
    ET.SubElement(maplayer, "datasource").text = f"./{DEM_VRT.relative_to(ROOT_DIR).as_posix()}"
    ET.SubElement(maplayer, "layername").text = "Copernicus DEM GLO-30 (Austria mosaic)"
    ET.SubElement(maplayer, "provider", encoding="UTF-8").text = "gdal"
    srs = ET.SubElement(maplayer, "srs")
    srs.append(ET.fromstring(WGS84_SRS_XML))

    pipe = ET.SubElement(maplayer, "pipe")
    renderer = ET.SubElement(pipe, "rasterrenderer", type="singlebandpseudocolor",
                              band="1", opacity="1", alphaBand="-1",
                              classificationMin=str(vmin), classificationMax=str(vmax))
    shader = ET.SubElement(renderer, "rastershader")
    ramp_shader = ET.SubElement(shader, "colorrampshader", colorRampType="INTERPOLATED", clip="0")
    for value, color in _elevation_ramp_items(vmin, vmax):
        ET.SubElement(ramp_shader, "item", value=f"{value:.2f}", label=f"{value:.0f} m",
                      color=color, alpha="255")
    ET.SubElement(pipe, "brightnesscontrast", brightness="0", contrast="0")
    ET.SubElement(pipe, "huesaturation", saturation="0", grayscaleMode="0")
    ET.SubElement(pipe, "rasterresampler")
    return maplayer


def _build_points_layer(layer_id, geojson_path, layer_name, color="#606060"):
    maplayer = ET.Element("maplayer", type="vector", hasScaleBasedVisibilityFlag="0",
                           geometry="Point")
    ET.SubElement(maplayer, "id").text = layer_id
    ET.SubElement(maplayer, "datasource").text = f"./{geojson_path.relative_to(ROOT_DIR).as_posix()}"
    ET.SubElement(maplayer, "layername").text = layer_name
    ET.SubElement(maplayer, "provider", encoding="UTF-8").text = "ogr"
    srs = ET.SubElement(maplayer, "srs")
    srs.append(ET.fromstring(WGS84_SRS_XML))

    renderer = ET.SubElement(maplayer, "renderer-v3", type="singleSymbol",
                              symbollevels="0", enableorderby="0", forceraster="0")
    symbols = ET.SubElement(renderer, "symbols")
    _make_marker_symbol(symbols, "0", color)
    return maplayer


def _diff_ranges(breaks_colors):
    """breaks_colors: list of (lower, upper, label, color)."""
    return breaks_colors


def _build_diff_layer(layer_id):
    maplayer = ET.Element("maplayer", type="vector", hasScaleBasedVisibilityFlag="0",
                           geometry="Point")
    ET.SubElement(maplayer, "id").text = layer_id
    ET.SubElement(maplayer, "datasource").text = f"./{DIFF_GEOJSON.relative_to(ROOT_DIR).as_posix()}"
    ET.SubElement(maplayer, "layername").text = "DEM vs obstacle base - difference (error_single_m)"
    ET.SubElement(maplayer, "provider", encoding="UTF-8").text = "ogr"
    srs = ET.SubElement(maplayer, "srs")
    srs.append(ET.fromstring(WGS84_SRS_XML))

    # Diverging classes centered on 0. Negative = DEM reads BELOW the
    # obstacle base (blue); positive = DEM reads ABOVE it (red) - e.g. DSM
    # capturing part of the obstacle, or genuine overestimation.
    ranges = [
        (-1e6, -15, "< -15 m (DEM well below base)", "#2166ac"),
        (-15, -5, "-15 to -5 m", "#67a9cf"),
        (-5, 0, "-5 to 0 m", "#d1e5f0"),
        (0, 5, "0 to 5 m", "#fddbc7"),
        (5, 15, "5 to 15 m", "#ef8a62"),
        (15, 1e6, "> 15 m (DEM well above base)", "#b2182b"),
    ]
    renderer = ET.SubElement(maplayer, "renderer-v3", type="graduatedSymbol", attr="error_single_m",
                              graduatedMethod="GraduatedColor", symbollevels="0",
                              enableorderby="0", forceraster="0")
    ranges_el = ET.SubElement(renderer, "ranges")
    symbols_el = ET.SubElement(renderer, "symbols")
    for i, (lower, upper, label, color) in enumerate(ranges):
        symbol_name = str(i)
        ET.SubElement(ranges_el, "range", lower=str(lower), upper=str(upper),
                      symbol=symbol_name, label=label, render="true", uuid=_uuid())
        _make_marker_symbol(symbols_el, symbol_name, color, size="2.8")
    return maplayer


def _build_orthophoto_layer(layer_id):
    maplayer = ET.Element("maplayer", type="raster", hasScaleBasedVisibilityFlag="0")
    ET.SubElement(maplayer, "id").text = layer_id
    datasource = (
        "contextualWMSLegend=0&crs=EPSG:3857&dpiMode=7&format=image/jpeg"
        "&layers=bmaporthofoto30cm&styles=normal&tileMatrixSet=google3857_0-17"
        f"&url={BASEMAP_AT_WMTS_CAPABILITIES}"
    )
    ET.SubElement(maplayer, "datasource").text = datasource
    ET.SubElement(maplayer, "layername").text = "Austria VHR Orthophoto (basemap.at, background)"
    ET.SubElement(maplayer, "provider", encoding="UTF-8").text = "wms"
    srs = ET.SubElement(maplayer, "srs")
    srs.append(ET.fromstring(WGS84_SRS_XML))
    pipe = ET.SubElement(maplayer, "pipe")
    ET.SubElement(pipe, "rasterrenderer", type="singlebandcolordata", band="1", opacity="1", alphaBand="-1")
    return maplayer


def build_project():
    dem_id = "dem_mosaic_" + uuid4().hex[:8]
    obstacles_id = "obstacles_points_" + uuid4().hex[:8]
    diff_id = "obstacles_diff_" + uuid4().hex[:8]
    ortho_id = "basemap_at_ortho_" + uuid4().hex[:8]

    qgis_root = ET.Element("qgis", projectname="CopDem - Austria DEM Validation", version="3.34.0")
    ET.SubElement(qgis_root, "title").text = "CopDem - Austria DEM Validation"
    ET.SubElement(qgis_root, "homePath", path="")

    project_crs = ET.SubElement(qgis_root, "projectCrs")
    project_crs.append(ET.fromstring(WGS84_SRS_XML))

    layer_tree = ET.SubElement(qgis_root, "layer-tree-group")
    # Draw order: last child drawn on top. List diff+obstacles above DEM, DEM above orthophoto.
    ET.SubElement(layer_tree, "layer-tree-layer", providerKey="wms", id=ortho_id,
                  name="Austria VHR Orthophoto (basemap.at, background)")
    ET.SubElement(layer_tree, "layer-tree-layer", providerKey="gdal", id=dem_id,
                  name="Copernicus DEM GLO-30 (Austria mosaic)")
    ET.SubElement(layer_tree, "layer-tree-layer", providerKey="ogr", id=obstacles_id,
                  name="Obstacles (simple points)")
    ET.SubElement(layer_tree, "layer-tree-layer", providerKey="ogr", id=diff_id,
                  name="DEM vs obstacle base - difference (error_single_m)")

    project_layers = ET.SubElement(qgis_root, "projectlayers")
    project_layers.append(_build_orthophoto_layer(ortho_id))
    project_layers.append(_build_dem_layer(dem_id))
    project_layers.append(_build_points_layer(obstacles_id, OBSTACLES_GEOJSON, "Obstacles (simple points)"))
    project_layers.append(_build_diff_layer(diff_id))

    tree = ET.ElementTree(qgis_root)
    ET.indent(tree, space="  ")
    tree.write(OUTPUT_QGS, encoding="UTF-8", xml_declaration=True)
    print(f"wrote {OUTPUT_QGS}")

    # Sanity: re-parse to confirm well-formed XML.
    ET.parse(OUTPUT_QGS)
    print("re-parsed OK (well-formed XML)")


if __name__ == "__main__":
    build_project()
