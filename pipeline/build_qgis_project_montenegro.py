#!/usr/bin/env python3
"""Generate copdem_montenegro.qgs — Montenegro's counterpart to
copdem_austria.qgs, same generator schema (proven to open cleanly in QGIS —
that's how the Austria project first started, before the user's live edits
layered on top; see build_qgis_project.py's own docstring/caveats, which
apply equally here).

Reuses the low-level, country-agnostic helpers from build_qgis_project.py
(marker symbols, label settings, WGS84 SRS block, DEM color ramp) rather
than duplicating them — only the per-layer path/name glue and the
Montenegro-specific extra layers are new here.

Layers, foreground to background (same ordering logic as Austria — first
XML child = top of Layers panel = drawn last/foreground):
  1. DEM vs obstacle base - difference (graduated, diverging)
  2. Obstacles (simple points)
  3. EGM96 vs EGM2008 undulation correction (new for Montenegro - see
     build_egm96_undulation_raster.py / docs/montenegro.md)
  4. CopDEM recalculated to EGM96 (new for Montenegro, same source)
  5. Copernicus DEM GLO-30 mosaic (native EGM2008)
  6. VHR background — ESRI World Imagery (Esri/ArcGIS Online XYZ tiles).
     NOT basemap.at (Austria-only, national) — used here because it's the
     SAME source the user already migrated Austria's live project to (see
     copdem_austria.qgs's "ESRI Satellite (ArcGIS/World_Imagery)" layer),
     so both country projects now share one VHR background convention
     instead of Austria using a national source and Montenegro needing its
     own separately-researched one. XYZ datasource string copied verbatim
     from that confirmed-working live layer.

No local ground-truth DEM for Montenegro (see docs/montenegro.md) — unlike
Austria's project, there is no LiDAR layer here.
"""
import sys
from pathlib import Path
from uuid import uuid4

import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).parent))
from build_qgis_project import (
    WGS84_SRS_XML, _uuid, _make_marker_symbol, _build_label_settings,
    _dem_range, _elevation_ramp_items,
)

ROOT_DIR = Path(__file__).parent.parent
DEM_VRT = ROOT_DIR / "data" / "dem_mosaic_montenegro.vrt"
DEM_EGM96_TIF = ROOT_DIR / "data" / "dem_mosaic_montenegro_egm96.tif"
UNDULATION_TIF = ROOT_DIR / "data" / "egm96_egm2008_undulation_montenegro.tif"
OBSTACLES_GEOJSON = ROOT_DIR / "data" / "obstacles" / "montenegro" / "obstacles_simple_points.geojson"
DIFF_GEOJSON = ROOT_DIR / "data" / "obstacles" / "montenegro" / "obstacles_dem_diff.geojson"
OUTPUT_QGS = ROOT_DIR / "copdem_montenegro.qgs"

# Verbatim from copdem_austria.qgs's live "ESRI Satellite (ArcGIS/World_Imagery)"
# layer — confirmed working, not re-derived from scratch.
ESRI_XYZ_DATASOURCE = (
    "crs=EPSG:3857&format&type=xyz"
    "&url=https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/%7Bz%7D/%7By%7D/%7Bx%7D"
    "&zmax=19&zmin=0"
)
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


def _build_dem_layer(layer_id, vrt_path, layer_name):
    vmin, vmax = _dem_range(vrt_path)
    maplayer = ET.Element("maplayer", type="raster", hasScaleBasedVisibilityFlag="0")
    ET.SubElement(maplayer, "id").text = layer_id
    ET.SubElement(maplayer, "datasource").text = f"./{vrt_path.relative_to(ROOT_DIR).as_posix()}"
    ET.SubElement(maplayer, "layername").text = layer_name
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


def _build_diverging_raster_layer(layer_id, tif_path, layer_name, vmin, vmax, unit_label="m"):
    """Diverging pseudocolor raster (blue-white-red), for the undulation
    correction layer — reuses the SAME blue/red convention as every other
    diverging chart/layer in this project (#2166ac..#b2182b family, matching
    the diff-layer marker colors in _build_diff_layer)."""
    maplayer = ET.Element("maplayer", type="raster", hasScaleBasedVisibilityFlag="0")
    ET.SubElement(maplayer, "id").text = layer_id
    ET.SubElement(maplayer, "datasource").text = f"./{tif_path.relative_to(ROOT_DIR).as_posix()}"
    ET.SubElement(maplayer, "layername").text = layer_name
    ET.SubElement(maplayer, "provider", encoding="UTF-8").text = "gdal"
    srs = ET.SubElement(maplayer, "srs")
    srs.append(ET.fromstring(WGS84_SRS_XML))

    pipe = ET.SubElement(maplayer, "pipe")
    renderer = ET.SubElement(pipe, "rasterrenderer", type="singlebandpseudocolor",
                              band="1", opacity="1", alphaBand="-1",
                              classificationMin=str(vmin), classificationMax=str(vmax))
    shader = ET.SubElement(renderer, "rastershader")
    ramp_shader = ET.SubElement(shader, "colorrampshader", colorRampType="INTERPOLATED", clip="0")
    stops = [(0.0, "#2166ac"), (0.5, "#f7f7f7"), (1.0, "#b2182b")]
    for frac, color in stops:
        value = vmin + frac * (vmax - vmin)
        ET.SubElement(ramp_shader, "item", value=f"{value:.4f}", label=f"{value:.2f} {unit_label}",
                      color=color, alpha="255")
    ET.SubElement(pipe, "brightnesscontrast", brightness="0", contrast="0")
    ET.SubElement(pipe, "huesaturation", saturation="0", grayscaleMode="0")
    ET.SubElement(pipe, "rasterresampler")
    return maplayer


def _build_obstacles_labeling():
    expression = (
        "'Type: ' || \"obstacle_type\""
        " || char(10) || "
        "'AGL: ' || round(\"height_agl_m\", 1) || ' m'"
    )
    return _build_label_settings(expression, with_shadow=False, quad_offset="8", offset_mm="4")


def _build_diff_labeling():
    expression = (
        "'1px: ' || round(\"error_single_m\", 1) || ' m'"
        " || char(10) || "
        "'5x5 median: ' || coalesce(round(\"error_5x5_median_m\", 1) || ' m', 'n/a')"
    )
    return _build_label_settings(expression, with_shadow=True, quad_offset="2", offset_mm="-4")


def _build_points_layer(layer_id, geojson_path, layer_name, color="#606060"):
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


def _build_diff_layer(layer_id, diff_geojson_path, layer_name):
    maplayer = ET.Element("maplayer", type="vector", hasScaleBasedVisibilityFlag="0",
                           geometry="Point", labelsEnabled="1")
    ET.SubElement(maplayer, "id").text = layer_id
    ET.SubElement(maplayer, "datasource").text = f"./{diff_geojson_path.relative_to(ROOT_DIR).as_posix()}"
    ET.SubElement(maplayer, "layername").text = layer_name
    ET.SubElement(maplayer, "provider", encoding="UTF-8").text = "ogr"
    srs = ET.SubElement(maplayer, "srs")
    srs.append(ET.fromstring(WGS84_SRS_XML))

    # Same diverging classes/colors as Austria's diff layer (see
    # build_qgis_project.py._build_diff_layer) - kept identical for visual
    # consistency across both country projects.
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


def _build_esri_background_layer(layer_id):
    maplayer = ET.Element("maplayer", type="raster", hasScaleBasedVisibilityFlag="0")
    ET.SubElement(maplayer, "id").text = layer_id
    ET.SubElement(maplayer, "datasource").text = ESRI_XYZ_DATASOURCE
    ET.SubElement(maplayer, "layername").text = "ESRI Satellite (ArcGIS/World_Imagery, background)"
    ET.SubElement(maplayer, "provider", encoding="UTF-8").text = "wms"
    srs = ET.SubElement(maplayer, "srs")
    srs.append(ET.fromstring(WEBMERCATOR_SRS_XML))
    pipe = ET.SubElement(maplayer, "pipe")
    ET.SubElement(pipe, "rasterrenderer", type="singlebandcolordata", band="1", opacity="1", alphaBand="-1")
    return maplayer


def build_project():
    diff_id = "obstacles_diff_mne_" + uuid4().hex[:8]
    obstacles_id = "obstacles_points_mne_" + uuid4().hex[:8]
    undulation_id = "egm96_undulation_mne_" + uuid4().hex[:8]
    dem_egm96_id = "dem_egm96_mne_" + uuid4().hex[:8]
    dem_id = "dem_mosaic_mne_" + uuid4().hex[:8]
    ortho_id = "esri_ortho_mne_" + uuid4().hex[:8]

    qgis_root = ET.Element("qgis", projectname="CopDem - Montenegro DEM Validation", version="3.34.0")
    ET.SubElement(qgis_root, "title").text = "CopDem - Montenegro DEM Validation"
    ET.SubElement(qgis_root, "homePath", path="")

    project_crs = ET.SubElement(qgis_root, "projectCrs")
    project_crs.append(ET.fromstring(WGS84_SRS_XML))

    layer_tree = ET.SubElement(qgis_root, "layer-tree-group")
    ET.SubElement(layer_tree, "layer-tree-layer", providerKey="ogr", id=diff_id,
                  name="DEM vs obstacle base - difference (error_single_m)")
    ET.SubElement(layer_tree, "layer-tree-layer", providerKey="ogr", id=obstacles_id,
                  name="Obstacles (simple points)")
    ET.SubElement(layer_tree, "layer-tree-layer", providerKey="gdal", id=undulation_id,
                  name="EGM96 vs EGM2008 undulation correction (m)")
    ET.SubElement(layer_tree, "layer-tree-layer", providerKey="gdal", id=dem_egm96_id,
                  name="Copernicus DEM GLO-30, recalculated to EGM96")
    ET.SubElement(layer_tree, "layer-tree-layer", providerKey="gdal", id=dem_id,
                  name="Copernicus DEM GLO-30 (Montenegro mosaic, native EGM2008)")
    ET.SubElement(layer_tree, "layer-tree-layer", providerKey="wms", id=ortho_id,
                  name="ESRI Satellite (ArcGIS/World_Imagery, background)")

    with __import__("rasterio").open(UNDULATION_TIF) as src:
        import numpy as np
        data = src.read(1, out_shape=(1, max(1, src.height // 10), max(1, src.width // 10)))
        u_vmin, u_vmax = float(np.nanmin(data)), float(np.nanmax(data))

    project_layers = ET.SubElement(qgis_root, "projectlayers")
    project_layers.append(_build_diff_layer(diff_id, DIFF_GEOJSON, "DEM vs obstacle base - difference (error_single_m)"))
    project_layers.append(_build_points_layer(obstacles_id, OBSTACLES_GEOJSON, "Obstacles (simple points)"))
    project_layers.append(_build_diverging_raster_layer(
        undulation_id, UNDULATION_TIF, "EGM96 vs EGM2008 undulation correction (m)", u_vmin, u_vmax))
    project_layers.append(_build_dem_layer(dem_egm96_id, DEM_EGM96_TIF, "Copernicus DEM GLO-30, recalculated to EGM96"))
    project_layers.append(_build_dem_layer(dem_id, DEM_VRT, "Copernicus DEM GLO-30 (Montenegro mosaic, native EGM2008)"))
    project_layers.append(_build_esri_background_layer(ortho_id))

    tree = ET.ElementTree(qgis_root)
    ET.indent(tree, space="  ")
    tree.write(OUTPUT_QGS, encoding="UTF-8", xml_declaration=True)
    print(f"wrote {OUTPUT_QGS}")

    ET.parse(OUTPUT_QGS)
    print("re-parsed OK (well-formed XML)")


if __name__ == "__main__":
    build_project()
