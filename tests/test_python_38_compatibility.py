from typing import get_type_hints

from shapely.geometry import MultiPolygon, Polygon

from pyslm_app.services import ModelSession
from pyslm.hatching.hatching import Hatcher
from pyslm.support.support import BlockSupportBase
from pyslm.visualise import plotPolygon


def test_builtin_generic_annotations_are_runtime_evaluable() -> None:
    targets = (
        ModelSession.compare_orthogonal_orientations,
        Hatcher.clipLines,
        BlockSupportBase.triangulateSections,
    )

    for target in targets:
        get_type_hints(target)


def test_plot_polygon_accepts_multipolygon() -> None:
    polygons = MultiPolygon([
        Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
        Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]),
    ])

    fig, ax = plotPolygon(polygons)

    assert fig is not None
    assert ax is not None
    assert len(ax.lines) == 2
