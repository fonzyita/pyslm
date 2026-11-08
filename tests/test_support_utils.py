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


def test_vertical_intervals_of_stacked_boxes() -> None:
    lower = trimesh.creation.box(extents=[4.0, 4.0, 2.0])
    upper = trimesh.creation.box(extents=[4.0, 4.0, 2.0])
    upper.apply_translation([0.0, 0.0, 5.0])
    mesh = trimesh.util.concatenate([lower, upper])

    lines, intervals = utils.verticalIntervals(mesh, np.array([[0.0, 0.0], [10.0, 0.0], [1.0, 1.0]]))

    assert lines.tolist() == [0, 0, 2, 2]
    assert np.allclose(intervals, [[-1.0, 1.0], [4.0, 6.0], [-1.0, 1.0], [4.0, 6.0]])


def _lattice_graph(region):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    volume = region.supportVolume
    cell, radius = region.latticeCellSize, region.trussWidth / 2.0
    columns, offsets, perimeter = region._latticeColumns(volume, cell, radius)
    nodes, node_column, vertical = region._latticePillars(volume, columns, offsets, cell, radius)
    bracing = region._latticeBracing(volume, columns, nodes, node_column, cell)
    edges = np.vstack([vertical, bracing])
    graph = coo_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(len(nodes),) * 2)
    pieces, _ = connected_components(graph, directed=False)
    return nodes, node_column, vertical, bracing, perimeter, pieces


def _grid_region(volume, use_skin=True):
    from pyslm.support import GridBlockSupport

    region = GridBlockSupport(supportVolume=volume)
    region.latticeCellSize = 5.0
    region.trussWidth = 0.4
    region.supportBorderDistance = 3.0
    region.useSupportSkin = use_skin
    return region


def test_conformal_lattice_is_connected_and_anchored() -> None:
    # A block whose upper surface is sloped, so a fixed lattice would be cut off mid-cell
    volume = trimesh.creation.box(extents=[30.0, 20.0, 12.0])
    volume.apply_translation([0.0, 0.0, 6.0])
    top = volume.vertices[:, 2] > 6.0
    volume.vertices[top, 2] += 0.3 * volume.vertices[top, 0]
    region = _grid_region(volume)

    nodes, node_column, vertical, bracing, perimeter, pieces = _lattice_graph(region)

    assert pieces == 1
    assert len(bracing) > 0 and perimeter.any()
    assert utils.pointsInsideMesh(volume, (nodes[bracing[:, 0]] + nodes[bracing[:, 1]]) / 2.0).all()
    # Every pillar starts on the lower surface and ends on the sloped upper surface
    for column in np.unique(node_column):
        z = nodes[node_column == column, 2]
        x = nodes[node_column == column, 0][0]
        assert np.isclose(z.min(), 0.0, atol=1e-6)
        assert np.isclose(z.max(), 12.0 + 0.3 * x, atol=0.05)

    mesh = region.generateSpaceFrame()
    assert len(mesh.faces) == len(mesh.face_attributes['order'])


def test_conformal_lattice_supports_regions_thinner_than_a_cell() -> None:
    # A 2 mm wide ring: no interior lattice fits, the braced perimeter wall carries the load
    ring = trimesh.creation.annulus(r_min=20.0, r_max=22.0, height=8.0, sections=96)
    ring.apply_translation([0.0, 0.0, 4.0])

    nodes, _, _, bracing, perimeter, pieces = _lattice_graph(_grid_region(ring))

    assert pieces == 1
    assert perimeter.all()
    assert len(bracing) > 0
