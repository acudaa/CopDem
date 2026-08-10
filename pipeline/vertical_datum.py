#!/usr/bin/env python3
"""Vertical reference system conversions for the DEM validation pipeline.

Copernicus DEM GLO-30 heights are referenced to the EGM2008 geoid
(EPSG:3855). Obstacle elevation data's vertical reference is NOT uniform
across states — the generic ICAO/AIXM assumption is EGM96, but individual
states' actual published datasets can differ significantly. Confirmed case:
Austria's obstacle data set states "EVRS" and is realized as EVRF2000
Austria height (EPSG:9274), a national height system whose separation from
EGM96 reaches ~2.5 m in the Alps — but only ~0.1 m from EGM2008. Using the
wrong assumed datum here would inject Alpine-scale spurious error into
exactly the terrain this study most needs to get right.

Conclusion: never assume a source's vertical datum — read it from the
source's own documentation per state, register it below, and use its exact
EPSG code. This module is intentionally generic over the source vertical
CRS rather than hardcoded to EGM96, for exactly that reason.

Conversions use pyproj's compound-CRS mechanism ("EPSG:4326+<vertical>"),
which accounts for the fact that geoid/quasigeoid undulation varies
spatially — height alone is not enough, the horizontal position must be
passed too.

Requires network access the first time each grid is used, so PROJ can fetch
it from the PROJ CDN (https://cdn.proj.org). Grids are cached locally by
PROJ after first use.
"""
from pyproj import CRS, Transformer
from pyproj.network import set_network_enabled

set_network_enabled(True)

WGS84_3D = 4979              # WGS84 ellipsoidal height
EGM96 = 5773                 # EGM96 geoid height (generic ICAO/AIXM default —
                              # verify per state before trusting this)
EGM2008 = 3855                # EGM2008 geoid height (Copernicus DEM's native reference)

# Per-source vertical datum registry — the per-state audit called for in the
# workflow's step 2. Add an entry here only after confirming it against the
# state's own AIP/obstacle-dataset documentation, not by assumption.
SOURCE_VERTICAL_CRS = {
    "AT": 9274,   # Austria obstacle data set: "EVRS", realized as EVRF2000 Austria height
}

_transformer_cache = {}


def _compound_crs(vertical_epsg: int) -> CRS:
    return CRS.from_user_input(f"EPSG:4326+{vertical_epsg}")


def _get_transformer(src_epsg, dst_epsg) -> Transformer:
    key = (src_epsg, dst_epsg)
    if key not in _transformer_cache:
        src = CRS.from_epsg(src_epsg) if src_epsg == WGS84_3D else _compound_crs(src_epsg)
        dst = CRS.from_epsg(dst_epsg) if dst_epsg == WGS84_3D else _compound_crs(dst_epsg)
        _transformer_cache[key] = Transformer.from_crs(src, dst, always_xy=True)
    return _transformer_cache[key]


def geoid_to_ellipsoidal(lon: float, lat: float, height: float, vertical_epsg: int) -> float:
    """Convert a geoid-referenced height (e.g. EGM96 or EGM2008) to WGS84
    ellipsoidal height at the given position."""
    transformer = _get_transformer(vertical_epsg, WGS84_3D)
    _, _, h = transformer.transform(lon, lat, height)
    return h


def ellipsoidal_to_geoid(lon: float, lat: float, height: float, vertical_epsg: int) -> float:
    """Convert a WGS84 ellipsoidal height to a geoid-referenced height
    (e.g. EGM96 or EGM2008) at the given position."""
    transformer = _get_transformer(WGS84_3D, vertical_epsg)
    _, _, h = transformer.transform(lon, lat, height)
    return h


def to_egm2008(lon: float, lat: float, height: float, source_vertical_epsg: int) -> float:
    """Convert a height in any registered source vertical CRS to EGM2008
    (Copernicus DEM's native reference) — the general-purpose entry point
    the obstacle-ingestion pipeline should use, instead of assuming EGM96."""
    if source_vertical_epsg == EGM2008:
        return height
    h_ellipsoidal = geoid_to_ellipsoidal(lon, lat, height, source_vertical_epsg)
    return ellipsoidal_to_geoid(lon, lat, h_ellipsoidal, EGM2008)


def egm96_to_egm2008(lon: float, lat: float, height_egm96: float) -> float:
    """Convert an EGM96-referenced height to EGM2008. Only valid where EGM96
    has actually been confirmed as the source's real vertical datum —
    see SOURCE_VERTICAL_CRS."""
    return to_egm2008(lon, lat, height_egm96, EGM96)


if __name__ == "__main__":
    # Self-test: round-trip a sample point (Vienna area) and check we get
    # back (close to) the original value, plus report the actual
    # EGM96 <-> EGM2008 separation at that point.
    lon, lat = 16.37, 48.21  # Vienna
    h_egm96 = 200.0

    h_ellip = geoid_to_ellipsoidal(lon, lat, h_egm96, EGM96)
    h_back = ellipsoidal_to_geoid(lon, lat, h_ellip, EGM96)
    print(f"EGM96 {h_egm96:.3f} m -> ellipsoidal {h_ellip:.3f} m -> back {h_back:.3f} m "
          f"(round-trip error: {abs(h_back - h_egm96):.6f} m)")

    h_egm2008 = egm96_to_egm2008(lon, lat, h_egm96)
    print(f"EGM96 {h_egm96:.3f} m -> EGM2008 {h_egm2008:.3f} m "
          f"(geoid separation at Vienna: {h_egm2008 - h_egm96:+.3f} m)")

    # Austria's actual obstacle-data datum: EVRF2000 Austria height (EPSG:9274)
    lon_at, lat_at = 10.9, 46.9  # Oetztal Alps, Tyrol — largest known EGM96 divergence
    h_evrf_at = 500.0
    h_egm2008_at = to_egm2008(lon_at, lat_at, h_evrf_at, SOURCE_VERTICAL_CRS["AT"])
    h_egm96_at = to_egm2008(lon_at, lat_at, h_evrf_at, SOURCE_VERTICAL_CRS["AT"])
    print(f"\nEVRF2000 Austria {h_evrf_at:.3f} m -> EGM2008 {h_egm2008_at:.3f} m "
          f"(separation: {h_egm2008_at - h_evrf_at:+.3f} m)")
    h_egm96_equiv = ellipsoidal_to_geoid(
        lon_at, lat_at, geoid_to_ellipsoidal(lon_at, lat_at, h_evrf_at, SOURCE_VERTICAL_CRS["AT"]), EGM96
    )
    print(f"For comparison, EVRF2000 Austria vs EGM96 separation: "
          f"{h_egm96_equiv - h_evrf_at:+.3f} m (this is the error avoided by NOT "
          f"assuming the generic ICAO/AIXM EGM96 default)")
