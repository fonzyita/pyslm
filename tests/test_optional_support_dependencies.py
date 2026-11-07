import pytest
from shapely.geometry import Polygon

from pyslm.support import geometry


def test_triangulation_reports_missing_triangle_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(geometry, "triangulate", None)
    polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])

    with pytest.raises(
        RuntimeError,
        match=r'optional .triangle. package.*PythonSLM\[triangulation\]',
    ):
        geometry.triangulateShapelyPolygon(polygon)


def test_triangulation_reports_missing_mapbox_earcut_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(geometry, "triangulate", lambda *_args: {})
    monkeypatch.setattr(geometry, "triangulate_float32", None)
    polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])

    with pytest.raises(RuntimeError, match="optional 'mapbox-earcut' package"):
        geometry.triangulateShapelyPolygon(polygon)
