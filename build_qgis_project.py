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

# Bug fixed here: the original block only had authid/description/acronyms
# and no wkt/proj4/srid — QGIS reported "layer CRS is unknown" because that
# wasn't enough for it to positively resolve the CRS. srsid (QGIS's internal
# srs.db row number) is deliberately omitted rather than guessed, since a
# wrong srsid could resolve to the wrong CRS entirely; proj4+wkt+authid+srid
# together are enough for QGIS to define the CRS correctly without it.
WGS84_SRS_XML = """<spatialrefsys>
  <wkt>GEOGCRS["WGS 84",DATUM["World Geodetic System 1984",ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]]],PRIMEM["Greenwich",0,ANGLEUNIT["degree",0.0174532925199433]],CS[ellipsoidal,2],AXIS["geodetic latitude (Lat)",north,ORDER[1],ANGLEUNIT["degree",0.0174532925199433]],AXIS["geodetic longitude (Lon)",east,ORDER[2],ANGLEUNIT["degree",0.0174532925199433]],USAGE[SCOPE["unknown"],AREA["World"],BBOX[-90,-180,90,180]],ID["EPSG",4326]]</wkt>
  <proj4>+proj=longlat +datum=WGS84 +no_defs</proj4>
  <srid>4326</srid>
  <authid>EPSG:4326</authid>
  <description>WGS 84</description>
  <projectionacronym>longlat</projectionacronym>
  <ellipsoidacronym>EPSG:7030</ellipsoidacronym>
  <geographicflag>true</geographicflag>
</spatialrefsys>"""

# The basemap.at WMTS datasource explicitly requests crs=EPSG:3857 — the
# orthophoto layer's own <srs> needs to match that, not be force-set to
# WGS84 like every other (EPSG:4326-native) layer here.
WEBMERCATOR_SRS_XML = """<spatialrefsys>
  <wkt>PROJCRS["WGS 84 / Pseudo-Mercator",BASEGEOGCRS["WGS 84",DATUM["World Geodetic System 1984",ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]]],PRIMEM["Greenwich",0,ANGLEUNIT["degree",0.0174532925199433]],ID["EPSG",4326]],CONVERSION["Popular Visualisation Pseudo-Mercator",METHOD["Popular Visualisation Pseudo Mercator",ID["EPSG",1024]],PARAMETER["Latitude of natural origin",0,ANGLEUNIT["degree",0.0174532925199433],ID["EPSG",8801]],PARAMETER["Longitude of natural origin",0,ANGLEUNIT["degree",0.0174532925199433],ID["EPSG",8802]],PARAMETER["False easting",0,LENGTHUNIT["metre",1],ID["EPSG",8806]],PARAMETER["False northing",0,LENGTHUNIT["metre",1],ID["EPSG",8807]]],CS[Cartesian,2],AXIS["easting (X)",east,ORDER[1],LENGTHUNIT["metre",1]],AXIS["northing (Y)",north,ORDER[2],LENGTHUNIT["metre",1]],USAGE[SCOPE["unknown"],AREA["World between 85.06 S and 85.06 N"],BBOX[-85.06,-180,85.06,180]],ID["EPSG",3857]]</wkt>
  <proj4>+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 +x_0=0 +y_0=0 +k=1 +units=m +nadgrids=@null +wktext +no_defs</proj4>
  <srid>3857</srid>
  <authid>EPSG:3857</authid>
  <description>WGS 84 / Pseudo-Mercator</description>
  <projectionacronym>merc</projectionacronym>
  <ellipsoidacronym>EPSG:7030</ellipsoidacronym>
  <geographicflag>false</geographicflag>
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
    # NOTE: hardcodes the obstacles-layer label (obstacle_type/height_agl_m
    # fields) below - fine while this is only called for the obstacles
    # layer (currently true), but would break if ever reused for a
    # differently-schematized point layer without also parameterizing the
    # labeling call.
    maplayer = ET.Element("maplayer", type="vector", hasScaleBasedVisibilityFlag="0",
                           geometry="Point", labelsEnabled="1")
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

    maplayer.append(_build_obstacles_labeling())
    return maplayer


def _diff_ranges(breaks_colors):
    """breaks_colors: list of (lower, upper, label, color)."""
    return breaks_colors


def _build_label_settings(expression, font_size="8", with_shadow=False):
    """Shared PAL labeling builder for both point layers. Buffer (white
    halo behind the text) is always on - both layers requested it, and it's
    the standard way to keep a label legible over a busy/colored background
    regardless of what's directly under any given point. Shadow is
    additionally requested for the difference layer only.
    """
    labeling = ET.Element("labeling", type="simple")
    settings = ET.SubElement(labeling, "settings")
    text_style = ET.SubElement(settings, "text-style", fieldName=expression, isExpression="1",
                                fontFamily="MS Shell Dlg 2", fontSize=font_size, fontSizeUnit="Point",
                                textColor="0,0,0,255", textOpacity="1", multilineHeight="1")
    ET.SubElement(text_style, "text-buffer",
                  bufferDraw="1", bufferSize="1", bufferSizeUnit="MM",
                  bufferColor="255,255,255,255", bufferOpacity="1", bufferNoFill="0")

    if with_shadow:
        # Drop shadow, explicitly requested (difference layer only) for
        # visibility over the DEM/orthophoto background.
        ET.SubElement(settings, "shadow",
                      shadowDraw="1", shadowUnder="0",
                      shadowOffsetAngle="135", shadowOffsetDist="1", shadowOffsetGlobal="1",
                      shadowOffsetUnit="MM", shadowRadius="1.5", shadowRadiusUnit="MM",
                      shadowRadiusAlphaOnly="0", shadowOpacity="0.7",
                      shadowColor="0,0,0,255", shadowScale="100")

    ET.SubElement(settings, "placement", placement="0")  # 0 = AroundPoint
    return labeling


def _build_diff_labeling():
    """One line per value, each prefixed so it's clear which number is
    which. Uses coalesce() around the 5x5-median half since that field is
    blank for the 4 obstacles whose window fell off a chunk edge (see
    docs/dem_extraction.md) - without it, QGIS's || concatenation would
    make the WHOLE label text null for those 4 points, not just that half.
    """
    expression = (
        "'1px: ' || round(\"error_single_m\", 1) || ' m'"
        " || char(10) || "
        "'5x5 median: ' || coalesce(round(\"error_5x5_median_m\", 1) || ' m', 'n/a')"
    )
    return _build_label_settings(expression, with_shadow=True)


def _build_obstacles_labeling():
    """Obstacle type + height above ground, one per line, each prefixed.
    height_agl_m is well-formed for all 1932 kept records (see
    obstacle_ingestion.md - 0 unparseable AGL values among clean Point
    rows), so no coalesce() is needed here unlike the diff layer's label.
    """
    expression = (
        "'Type: ' || \"obstacle_type\""
        " || char(10) || "
        "'AGL: ' || round(\"height_agl_m\", 1) || ' m'"
    )
    return _build_label_settings(expression, with_shadow=False)


def _build_diff_layer(layer_id):
    maplayer = ET.Element("maplayer", type="vector", hasScaleBasedVisibilityFlag="0",
                           geometry="Point", labelsEnabled="1")
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

    maplayer.append(_build_diff_labeling())
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
    srs.append(ET.fromstring(WEBMERCATOR_SRS_XML))  # matches datasource's crs=EPSG:3857, not WGS84
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
    # Bug fixed here: QGIS's layer-tree XML lists layers top-to-bottom as
    # they appear in the Layers panel, and the TOP of that panel is drawn
    # LAST (foreground/highest z-order) - the FIRST XML child is the
    # topmost/foreground layer, the LAST XML child is the bottom/background
    # one. The original order had this backwards (orthophoto listed first,
    # so it painted over everything else). Correct order, first-to-last:
    # diff (foreground) -> obstacles -> DEM -> orthophoto (background).
    ET.SubElement(layer_tree, "layer-tree-layer", providerKey="ogr", id=diff_id,
                  name="DEM vs obstacle base - difference (error_single_m)")
    ET.SubElement(layer_tree, "layer-tree-layer", providerKey="ogr", id=obstacles_id,
                  name="Obstacles (simple points)")
    ET.SubElement(layer_tree, "layer-tree-layer", providerKey="gdal", id=dem_id,
                  name="Copernicus DEM GLO-30 (Austria mosaic)")
    ET.SubElement(layer_tree, "layer-tree-layer", providerKey="wms", id=ortho_id,
                  name="Austria VHR Orthophoto (basemap.at, background)")

    project_layers = ET.SubElement(qgis_root, "projectlayers")
    project_layers.append(_build_diff_layer(diff_id))
    project_layers.append(_build_points_layer(obstacles_id, OBSTACLES_GEOJSON, "Obstacles (simple points)"))
    project_layers.append(_build_dem_layer(dem_id))
    project_layers.append(_build_orthophoto_layer(ortho_id))

    tree = ET.ElementTree(qgis_root)
    ET.indent(tree, space="  ")
    tree.write(OUTPUT_QGS, encoding="UTF-8", xml_declaration=True)
    print(f"wrote {OUTPUT_QGS}")

    # Sanity: re-parse to confirm well-formed XML.
    ET.parse(OUTPUT_QGS)
    print("re-parsed OK (well-formed XML)")


if __name__ == "__main__":
    build_project()
