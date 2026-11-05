"""Support-structure analysis and generation helpers.

The optional triangulation/rendering dependencies are imported lazily so
submodules such as ``pyslm.support.render`` remain usable even when the
full support geometry stack is unavailable.
"""

from importlib import import_module

__all__ = [
    "BaseSupportGenerator",
    "BlockSupportBase",
    "BlockSupportGenerator",
    "GridBlockSupport",
    "GridBlockSupportGenerator",
    "SupportStructure",
    "approximateProjectionSupportCost",
    "approximateSupportMapByCentroid",
    "approximateSupportMomentArea",
    "extrudeFace",
    "generateHeightMap",
    "generateHeightMap2",
    "geometry",
    "getAdjacentFaces",
    "getApproximateSupportArea",
    "getFaceZProjectionWeight",
    "getOverhangMesh",
    "getSupportAngles",
    "gridBlockSupport",
    "projectHeightMap",
    "render",
    "support",
    "utils",
]


def __getattr__(name):
    if name == "geometry":
        return import_module(".geometry", __name__)
    if name == "utils":
        return import_module(".utils", __name__)
    if name == "support":
        return import_module(".support", __name__)
    if name == "gridBlockSupport":
        return import_module(".gridBlockSupport", __name__)
    if name == "render":
        return import_module(".render", __name__)
    if name == "extrudeFace":
        from .geometry import extrudeFace
        return extrudeFace
    if name in {
        "getOverhangMesh",
        "getSupportAngles",
        "getAdjacentFaces",
        "getFaceZProjectionWeight",
        "generateHeightMap",
        "generateHeightMap2",
        "getApproximateSupportArea",
        "approximateProjectionSupportCost",
        "approximateSupportMapByCentroid",
        "approximateSupportMomentArea",
    }:
        from . import utils
        return getattr(utils, name)
    if name in {
        "SupportStructure",
        "BaseSupportGenerator",
        "BlockSupportBase",
        "BlockSupportGenerator",
    }:
        from . import support
        return getattr(support, name)
    if name in {"GridBlockSupport", "GridBlockSupportGenerator"}:
        from . import gridBlockSupport
        return getattr(gridBlockSupport, name)
    if name == "projectHeightMap":
        from .render import projectHeightMap
        return projectHeightMap
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
