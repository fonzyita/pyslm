import importlib.util

import numpy as np
import pytest
import shapely.geometry
import trimesh

from pyslm.support import WallBlockSupport, WallSupportParameters


def _region(volume, **kwargs):
    params = WallSupportParameters(**kwargs)
    return WallBlockSupport(supportVolume=volume, parameters=params), params


def _block(extents, z0=0.0):
    volume = trimesh.creation.box(extents=extents)
    volume.apply_translation([0.0, 0.0, z0 + extents[2] / 2.0])
    return volume


def test_walls_fill_the_region_with_closed_solid_walls() -> None:
    volume = _block([20.0, 12.0, 10.0])
    region, params = _region(volume)

    mesh = region.geometry()

    assert len(mesh.faces) > 0
    if importlib.util.find_spec("triangle") is not None:
        # The robust ``triangle`` backend (required for support generation) yields closed walls
        assert mesh.is_watertight
    # The walls stay inside the footprint (a grid wall lying exactly on the boundary may protrude by half its
    # thickness) and stand on the build plate
    tolerance = params.wallThickness / 2.0 + 1e-6
    assert np.all(mesh.bounds[0, :2] >= volume.bounds[0, :2] - tolerance)
    assert np.all(mesh.bounds[1, :2] <= volume.bounds[1, :2] + tolerance)
    assert mesh.bounds[0, 2] == pytest.approx(0.0, abs=1e-6)
    # The teeth reach into the part by the penetration distance
    assert mesh.bounds[1, 2] == pytest.approx(10.0 + params.teethPenetration, abs=1e-3)


def test_teeth_have_the_requested_contact_length() -> None:
    volume = _block([20.0, 6.0, 8.0])
    region, params = _region(volume, useBorder=False, usePerforation=False)
    walls = region._gridWalls(volume, params)
    wall = next(w for w in walls if w.direction[0] == 1.0 and abs(w.origin[1]) < 1e-9)
    u = np.linspace(0.0, wall.length, int(wall.length / params.sampleStep) + 1)
    inside = (wall.origin[0] + u > -10.0) & (wall.origin[0] + u < 10.0)
    intervals = [np.array([[0.0, 8.0]]) if flag else np.empty((0, 2)) for flag in inside]

    outline = region._wallOutline(u, intervals, params)

    top = 8.0 + params.teethPenetration
    # Cut the teeth just below their tips: every cut segment is one tooth contact
    cut = outline.intersection(shapely.geometry.LineString([(-1e3, top - 1e-6), (1e3, top - 1e-6)]))
    segments = sorted(getattr(cut, "geoms", [cut]), key=lambda g: g.centroid.x)
    # The first and last tooth may be cut short by the end of the wall
    inner = segments[1:-1]
    assert len(inner) > 5
    assert np.allclose([g.length for g in inner], params.teethTopLength, atol=1e-4)
    # The teeth are spaced by the tooth base length plus the base interval
    assert np.allclose(np.diff([g.centroid.x for g in inner]), params.teethBaseLength + params.teethBaseInterval,
                       atol=1e-4)
    # The wall below the teeth is solid down to the build plate
    assert outline.bounds[1] == pytest.approx(0.0)


def test_lower_teeth_only_where_the_wall_stands_on_the_part() -> None:
    on_part = _block([16.0, 6.0, 6.0], z0=5.0)
    region, params = _region(on_part)
    mesh = region.geometry()
    assert mesh.bounds[0, 2] == pytest.approx(5.0 - params.teethPenetration, abs=1e-3)

    on_plate = _block([16.0, 6.0, 6.0])
    region, _ = _region(on_plate)
    assert region.geometry().bounds[0, 2] == pytest.approx(0.0, abs=1e-6)


def test_overlapping_shells_give_one_continuous_wall() -> None:
    # Support volumes are often unions of touching or overlapping shells
    lower = _block([12.0, 6.0, 5.0])
    upper = _block([12.0, 6.0, 5.0], z0=4.9)
    volume = trimesh.util.concatenate([lower, upper])
    region, params = _region(volume, usePerforation=False, useUpperTeeth=False, useBorder=False)

    mesh = region.geometry()
    pieces = mesh.split(only_watertight=False)

    assert mesh.bounds[1, 2] == pytest.approx(9.9, abs=1e-3)
    # One piece per grid wall: every wall spans the full height without a split at the shell boundary
    assert len(pieces) == len([w for w in region._gridWalls(volume, params)
                               if len(w.origin) and _crosses(w, volume)])


def _crosses(wall, volume) -> bool:
    end = wall.origin + wall.direction * wall.length
    lo, hi = volume.bounds[0, :2], volume.bounds[1, :2]
    if wall.direction[0] == 1.0:
        return lo[1] < wall.origin[1] < hi[1]
    return lo[0] < wall.origin[0] < hi[0] and end[1] > lo[1]


def test_parameters_are_validated() -> None:
    with pytest.raises(ValueError):
        WallSupportParameters(hatchSpacing=0.0).validate()
    with pytest.raises(ValueError):
        WallSupportParameters(teethTopLength=2.0, teethBaseLength=1.0).validate()
    WallSupportParameters().validate()


def test_holes_touching_the_boundary_are_filled_before_triangulation() -> None:
    from pyslm.support.wallSupport import _sanitizePolygon

    outer = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    touching_boundary = [(8.0, 5.0), (9.0, 6.0), (10.0, 5.0), (9.0, 4.0)]
    hole_a = [(2.0, 2.0), (3.0, 3.0), (4.0, 2.0), (3.0, 1.0)]
    hole_b = [(4.0, 2.0), (5.0, 3.0), (6.0, 2.0), (5.0, 1.0)]  # touches hole_a at (4, 2)
    hole_c = [(2.0, 7.0), (3.0, 8.0), (4.0, 7.0), (3.0, 6.0)]
    polygon = shapely.geometry.Polygon(outer, [touching_boundary, hole_a, hole_b, hole_c])
    assert polygon.is_valid

    cleaned = _sanitizePolygon(polygon)

    assert len(cleaned.interiors) == 2
    assert cleaned.area == pytest.approx(100.0 - 2 * 2.0)
