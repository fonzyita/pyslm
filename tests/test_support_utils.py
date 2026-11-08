import numpy as np
import pytest
import trimesh

from pyslm.support import utils


@pytest.mark.parametrize(
    "mesh",
    [
        trimesh.creation.box(extents=[3.0, 4.0, 5.0]),
        trimesh.creation.icosphere(subdivisions=3, radius=2.0),
        trimesh.creation.torus(major_radius=3.0, minor_radius=1.0),
    ],
    ids=["box", "sphere", "torus"],
)
def test_points_inside_mesh_matches_trimesh(mesh: trimesh.Trimesh) -> None:
    rng = np.random.default_rng(0)
    bounds = mesh.bounds
    points = rng.uniform(bounds[0] - 0.5, bounds[1] + 0.5, size=(5000, 3))

    assert np.array_equal(utils.pointsInsideMesh(mesh, points), mesh.contains(points))


def test_points_inside_mesh_ignores_winding_and_degenerate_faces() -> None:
    box = trimesh.creation.box(extents=[2.0, 2.0, 2.0])
    inverted = trimesh.Trimesh(box.vertices, box.faces[:, ::-1], process=False)
    # A zero-area triangle must not contribute a crossing
    degenerate = trimesh.Trimesh(
        np.vstack([inverted.vertices, [[0.0, 0.0, 0.5]] * 3]),
        np.vstack([inverted.faces, [[8, 9, 10]]]),
        process=False,
    )
    points = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 2.0], [0.9, -0.9, 0.9], [1.1, 0.0, 0.0]])

    assert utils.pointsInsideMesh(degenerate, points).tolist() == [True, False, True, False]


def test_points_inside_mesh_handles_long_thin_triangles() -> None:
    # Long slivers spanning the whole part stress the strip-clipped candidate search
    mesh = trimesh.creation.box(extents=[100.0, 1.0, 1.0])
    rng = np.random.default_rng(1)
    points = rng.uniform([-55.0, -1.0, -1.0], [55.0, 1.0, 1.0], size=(20000, 3))

    assert np.array_equal(utils.pointsInsideMesh(mesh, points), mesh.contains(points))


def test_cylinder_segments_match_trimesh_cylinders() -> None:
    rng = np.random.default_rng(2)
    segments = rng.normal(size=(20, 2, 3))
    segments[0, 1] = segments[0, 0] + [0.0, 0.0, -2.0]  # antiparallel to +Z
    segments[1, 1] = segments[1, 0] + [0.0, 0.0, 3.0]  # parallel to +Z

    mesh, face_segment = utils.cylinderSegments(segments, 0.2, sections=8)
    reference = [trimesh.creation.cylinder(radius=0.2, segment=s, sections=8) for s in segments]

    assert len(mesh.faces) == sum(len(r.faces) for r in reference)
    assert np.isclose(mesh.volume, sum(r.volume for r in reference))
    assert np.array_equal(np.bincount(face_segment), [len(r.faces) for r in reference])
    for index, segment in enumerate(segments):
        vertices = mesh.vertices[np.unique(mesh.faces[face_segment == index])]
        axis = segment[1] - segment[0]
        projection = (vertices - segment[0]) @ axis / (axis @ axis)
        assert np.isclose(projection.min(), 0.0) and np.isclose(projection.max(), 1.0)


def test_cylinder_segments_empty() -> None:
    mesh, face_segment = utils.cylinderSegments(np.empty((0, 2, 3)), 0.2)

    assert len(mesh.faces) == 0
    assert len(face_segment) == 0
