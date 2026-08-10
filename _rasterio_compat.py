"""Import this before `rasterio` in any module that uses it.

Windows-specific workaround: on some Python installs (e.g. a venv built on
top of an Anaconda base install), rasterio's bundled GDAL/PROJ DLLs can
shadow the interpreter's own pyexpat DLL, causing
`ImportError: DLL load failed while importing pyexpat` the first time
anything (including rasterio itself, via GDAL XML parsing) touches
xml.etree.ElementTree. Forcing the stdlib xml module to load first avoids
the conflict. Harmless no-op on installs that don't hit this issue.
"""
import xml.etree.ElementTree  # noqa: F401
