import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh

from pyslm_app.services import ModelSession


MODEL_PATH = Path(__file__).parent.parent / "models" / "cube.stl"


def test_load_orient_and_measure_stl() -> None:
    session = ModelSession()

    extents = session.load_stl(str(MODEL_PATH))
    initial_volume = session.get_metrics()[1]
    assert all(value > 0 for value in extents)
    assert initial_volume is not None and initial_volume > 0
    assert session.part is not None
    assert session.part.geometry.bounds[0, 2] == pytest.approx(session.build_lift, abs=1e-6)

    session.set_orientation(15.0, 0.0, 30.0)
    oriented_extents, oriented_volume = session.get_metrics()
    assert all(value > 0 for value in oriented_extents)
    assert oriented_volume == pytest.approx(initial_volume)
    assert session.part.geometry.bounds[0, 2] == pytest.approx(session.build_lift, abs=1e-6)


def test_build_lift_raises_part_and_invalidates_supports() -> None:
    session = ModelSession()
    assert session.build_lift == pytest.approx(3.0)
    session.load_stl(str(MODEL_PATH))
    height = float(np.ptp(session.part.geometry.bounds[:, 2]))
    session.support_meshes = [trimesh.creation.box(extents=[1.0] * 3)]
    session.support_regions = [SimpleNamespace()]

    session.set_build_lift(5.5)

    assert session.part.geometry.bounds[0, 2] == pytest.approx(5.5, abs=1e-6)
    assert float(np.ptp(session.part.geometry.bounds[:, 2])) == pytest.approx(height)
    assert session.support_meshes == [] and session.support_regions == []

    session.set_orientation(0.0, 30.0, 0.0)
    assert session.part.geometry.bounds[0, 2] == pytest.approx(5.5, abs=1e-6)

    session.set_build_lift(0.0)
    assert session.part.geometry.bounds[0, 2] == pytest.approx(0.0, abs=1e-6)
    with pytest.raises(ValueError):
        session.set_build_lift(-1.0)


def test_mesh_diagnostics_report_mesh_integrity() -> None:
    session = ModelSession()
    session.load_stl(str(MODEL_PATH))

    diagnostics = session.analyze_mesh()

    assert diagnostics.triangle_count == 12
    assert diagnostics.body_count == 1
    assert diagnostics.watertight
    assert diagnostics.winding_consistent
    assert diagnostics.valid_volume
    assert diagnostics.degenerate_face_count == 0
    assert not diagnostics.enclosed_shell_candidates


def test_mesh_diagnostics_detect_nested_inward_shell(tmp_path: Path) -> None:
    from trimesh.util import concatenate

    outer = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    inner = trimesh.creation.box(extents=[4.0, 4.0, 4.0])
    inner.invert()
    nested_mesh = concatenate([outer, inner])
    mesh_path = tmp_path / "nested-shell.stl"
    mesh_path.write_bytes(nested_mesh.export(file_type="stl"))

    session = ModelSession()
    session.load_stl(str(mesh_path))
    diagnostics = session.analyze_mesh()

    assert diagnostics.body_count == 2
    assert diagnostics.valid_volume
    assert len(diagnostics.enclosed_shell_candidates) == 1
    assert diagnostics.enclosed_shell_candidates[0].volume == pytest.approx(64.0)


def test_voxel_screen_reports_enclosed_void_volume(tmp_path: Path) -> None:
    from trimesh.util import concatenate

    outer = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    inner = trimesh.creation.box(extents=[4.0, 4.0, 4.0])
    inner.invert()
    mesh_path = tmp_path / "nested-shell.stl"
    mesh_path.write_bytes(concatenate([outer, inner]).export(file_type="stl"))

    session = ModelSession()
    session.load_stl(str(mesh_path))
    result = session.screen_internal_voids(0.5)

    assert result.voxel_pitch == pytest.approx(0.5)
    assert result.sampled_voxel_count == result.grid_shape[0] * result.grid_shape[1] * result.grid_shape[2]
    assert len(result.candidates) == 1
    assert result.candidates[0].volume == pytest.approx(64.0)
    lift = session.build_lift
    assert result.candidates[0].bounds == (
        (-2.0, -2.0, 3.0 + lift),
        (2.0, 2.0, 7.0 + lift),
    )
    assert result.visualization_mesh is not None
    assert np.asarray(result.visualization_mesh.bounds) == pytest.approx(
        np.asarray(result.candidates[0].bounds)
    )
    assert result.probe_blocked_visualization_mesh is None
    assert result.probe_diameter is None
    assert not result.probe_blocked_candidates


def test_voxel_screen_reports_clearance_limited_probe_space(
    tmp_path: Path,
) -> None:
    from trimesh.util import concatenate

    outer = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    inner = trimesh.creation.box(extents=[4.0, 4.0, 4.0])
    inner.invert()
    mesh_path = tmp_path / "nested-shell.stl"
    mesh_path.write_bytes(concatenate([outer, inner]).export(file_type="stl"))

    session = ModelSession()
    session.load_stl(str(mesh_path))
    small_probe = session.screen_internal_voids(0.5, probe_diameter=0.5)
    large_probe = session.screen_internal_voids(0.5, probe_diameter=5.0)

    assert small_probe.probe_diameter == pytest.approx(0.5)
    assert len(small_probe.probe_blocked_candidates) == 1
    assert small_probe.probe_blocked_candidates[0].volume == pytest.approx(27.0)
    assert small_probe.probe_blocked_visualization_mesh is not None
    assert np.asarray(
        small_probe.probe_blocked_visualization_mesh.bounds
    ) == pytest.approx(np.asarray(small_probe.probe_blocked_candidates[0].bounds))
    assert large_probe.probe_diameter == pytest.approx(5.0)
    assert not large_probe.probe_blocked_candidates
    assert large_probe.probe_blocked_visualization_mesh is None


def test_voxel_screen_uses_current_build_orientation(tmp_path: Path) -> None:
    from trimesh.util import concatenate

    outer = trimesh.creation.box(extents=[12.0, 12.0, 12.0])
    inner = trimesh.creation.box(extents=[2.0, 4.0, 6.0])
    inner.invert()
    mesh_path = tmp_path / "oriented-cavity.stl"
    mesh_path.write_bytes(concatenate([outer, inner]).export(file_type="stl"))

    session = ModelSession()
    session.load_stl(str(mesh_path))
    initial = session.screen_internal_voids(0.5)
    session.set_orientation(90.0, 0.0, 0.0)
    rotated = session.screen_internal_voids(0.5)

    assert initial.build_rotation == (0.0, 0.0, 0.0)
    assert rotated.build_rotation == (90.0, 0.0, 0.0)
    initial_bounds = np.asarray(initial.candidates[0].bounds)
    rotated_bounds = np.asarray(rotated.candidates[0].bounds)
    assert (initial_bounds[1] - initial_bounds[0]) == pytest.approx((2.0, 4.0, 6.0))
    assert (rotated_bounds[1] - rotated_bounds[0]) == pytest.approx((2.0, 6.0, 4.0))


def test_voxel_screen_does_not_report_torus_hole_as_enclosed(
    tmp_path: Path,
) -> None:
    mesh_path = tmp_path / "torus.stl"
    mesh_path.write_bytes(
        trimesh.creation.torus(major_radius=5, minor_radius=2).export(
            file_type="stl"
        )
    )

    session = ModelSession()
    session.load_stl(str(mesh_path))

    assert not session.screen_internal_voids(0.5).candidates
    assert not session.screen_internal_voids(
        0.5, probe_diameter=1.0
    ).probe_blocked_candidates


def test_voxel_screen_rejects_invalid_mesh_and_resolution() -> None:
    session = ModelSession()
    session.load_stl(str(MODEL_PATH))
    open_mesh = trimesh.creation.box()
    open_mesh.update_faces([False] + [True] * (len(open_mesh.faces) - 1))
    session._diagnostic_geometry = open_mesh

    with pytest.raises(ValueError, match="passo voxel"):
        session.screen_internal_voids(0.0)
    with pytest.raises(ValueError, match="diametro della sonda"):
        session.screen_internal_voids(0.5, probe_diameter=0.0)
    with pytest.raises(ValueError, match="mesh chiusa"):
        session.screen_internal_voids(0.5)

    session._diagnostic_geometry = trimesh.creation.box(extents=[10.0] * 3)
    with pytest.raises(ValueError, match="Aumentare il passo voxel"):
        session.screen_internal_voids(0.01)


def test_export_oriented_stl(tmp_path: Path) -> None:
    session = ModelSession()
    session.load_stl(str(MODEL_PATH))
    session.set_orientation(10.0, 20.0, 30.0)

    destination = tmp_path / "oriented.stl"
    session.export_part(str(destination))

    exported_mesh = trimesh.load_mesh(destination, process=False)
    assert len(exported_mesh.faces) > 0
    assert exported_mesh.bounds[0, 2] == pytest.approx(session.build_lift, abs=1e-5)


def test_remove_support_region_keeps_meshes_aligned_and_exportable(
    tmp_path: Path,
) -> None:
    session = ModelSession()
    session.load_stl(str(MODEL_PATH))
    removed_mesh = trimesh.creation.box(extents=[1.0, 1.0, 1.0])
    kept_mesh = trimesh.creation.box(extents=[2.0, 2.0, 2.0])
    removed_region = SimpleNamespace(supportSurface=trimesh.creation.box())
    kept_region = SimpleNamespace(supportSurface=trimesh.creation.box(extents=[2.0] * 3))
    session.support_regions = [removed_region, kept_region]
    session.support_meshes = [removed_mesh, kept_mesh]

    removed = session.remove_support_region(0)

    assert removed is removed_region
    assert session.support_regions == [kept_region]
    assert session.support_meshes == [kept_mesh]
    destination = tmp_path / "remaining-support.stl"
    session.export_supports(str(destination))
    exported_mesh = trimesh.load_mesh(destination, process=False)
    assert len(exported_mesh.faces) == len(kept_mesh.faces)


def test_remove_support_region_rejects_out_of_range_index() -> None:
    session = ModelSession()
    session.support_regions = [object()]
    session.support_meshes = [trimesh.creation.box()]

    with pytest.raises(IndexError, match="Indice regione supporto non valido"):
        session.remove_support_region(1)


def test_restore_removed_support_regions_preserves_order() -> None:
    session = ModelSession()
    regions = [SimpleNamespace(supportSurface=None) for _ in range(3)]
    meshes = [trimesh.creation.box(extents=[size] * 3) for size in (1.0, 2.0, 3.0)]
    session.support_regions = regions.copy()
    session.support_meshes = meshes.copy()

    session.remove_support_region(0)
    session.remove_support_region(1)
    assert session.can_restore_support_region
    assert session.support_regions == [regions[1]]

    assert session.restore_last_removed_support_region() == 1
    assert session.support_regions == [regions[1], regions[2]]
    assert session.restore_last_removed_support_region() == 0
    assert session.support_regions == regions
    assert session.support_meshes == meshes
    assert not session.can_restore_support_region


def test_clearing_supports_clears_undo_history() -> None:
    session = ModelSession()
    session.support_regions = [object()]
    session.support_meshes = [trimesh.creation.box()]

    session.remove_support_region(0)
    session.clear_supports()

    assert not session.can_restore_support_region
    with pytest.raises(RuntimeError, match="Non ci sono regioni rimosse"):
        session.restore_last_removed_support_region()


def test_viewer_highlights_selected_support_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("PyQt5")
    pytest.importorskip("pyqtgraph")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt5 import QtWidgets

    from pyslm_app.viewer import MeshView

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    viewer = MeshView()
    viewer.show_meshes(
        trimesh.creation.box(extents=[5.0] * 3),
        supports=[
            trimesh.creation.box(extents=[1.0] * 3),
            trimesh.creation.box(extents=[2.0] * 3),
        ],
        internal_voids=trimesh.creation.box(extents=[0.5] * 3),
        probe_blocked_regions=trimesh.creation.box(extents=[0.25] * 3),
    )
    assert viewer._internal_void_item is not None
    assert viewer._probe_blocked_item is not None
    assert np.allclose(
        viewer._part_item.opts["meshdata"].faceColors()[:, 3], 0.22
    )
    assert np.allclose(
        viewer._part_item.opts["meshdata"].faceColors()[0, :3],
        MeshView._PART_COLOR[:3],
    )
    assert not viewer._part_item.opts["drawEdges"]
    assert viewer._part_item.opts["shader"] == "pyslmStudioMetalPart"
    assert viewer._part_item.opts["smooth"]
    normal_color = np.asarray(viewer._SUPPORT_COLOR)
    selected_color = np.asarray(viewer._SELECTED_SUPPORT_COLOR)
    first_face_colors = viewer._support_items[0].opts["meshdata"].faceColors()
    second_face_colors = viewer._support_items[1].opts["meshdata"].faceColors()
    assert np.allclose(first_face_colors, normal_color)
    assert np.allclose(second_face_colors, normal_color)

    viewer.set_selected_support(1)
    assert np.allclose(
        viewer._support_items[0].opts["meshdata"].faceColors(), normal_color
    )
    assert np.allclose(
        viewer._support_items[1].opts["meshdata"].faceColors(), selected_color
    )
    viewer.set_selected_support(None)
    assert np.allclose(
        viewer._support_items[1].opts["meshdata"].faceColors(), normal_color
    )
    with pytest.raises(IndexError, match="Indice supporto selezionato non valido"):
        viewer.set_selected_support(2)

    viewer.close()
    app.processEvents()


def test_viewer_uses_opaque_shaded_meshes_and_preserves_input_normals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("PyQt5")
    pytest.importorskip("pyqtgraph")
    from OpenGL.GL import GL_BLEND

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt5 import QtWidgets

    from pyslm_app.viewer import MeshView

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    part = trimesh.creation.box(extents=[5.0] * 3)
    part.faces[[0, 1]] = part.faces[[1, 0]]
    original_faces = part.faces.copy()
    viewer = MeshView()
    viewer.show_meshes(part, overhang=trimesh.creation.box(extents=[1.0] * 3))

    assert np.array_equal(part.faces, original_faces)
    assert np.allclose(
        viewer._part_item.opts["meshdata"].faceColors()[:, 3], 1.0
    )
    assert np.allclose(
        viewer._overhang_item.opts["meshdata"].faceColors()[:, 3], 1.0
    )
    assert viewer._part_item.opts["shader"] == "pyslmStudioMetalPart"
    assert viewer._part_item.opts["smooth"]
    assert not viewer._part_item._GLGraphicsItem__glOpts[GL_BLEND]
    assert not viewer._overhang_item._GLGraphicsItem__glOpts[GL_BLEND]

    viewer.close()
    app.processEvents()


def test_support_generation_reports_missing_triangle_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pyslm.support import geometry as support_geometry

    session = ModelSession()
    session.load_stl(str(MODEL_PATH))
    monkeypatch.setattr(support_geometry, "triangulate", None)

    with pytest.raises(
        RuntimeError,
        match=r"optional 'triangle'.*Microsoft C\+\+ Build Tools",
    ):
        session.generate_supports(
            support_type="block",
            overhang_angle=45.0,
            ray_resolution=0.6,
            outer_edge_gap=0.3,
            inner_edge_gap=0.2,
            simplify_factor=0.5,
            minimum_area=2.0,
            grid_spacing=5.0,
            truss_width=1.0,
            lattice_cell_size=5.0,
            border_distance=1.0,
            use_skin=True,
            upper_teeth=True,
            lower_teeth=True,
        )


def test_support_generation_skips_empty_grid_regions(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import pyslm.support as support_module
    from pyslm.support import geometry as support_geometry

    empty_region = SimpleNamespace(
        supportVolume=trimesh.Trimesh(),
        geometry=lambda: pytest.fail("Empty support region should not be evaluated"),
    )

    class FakeGridSupportGenerator:
        def identifySupportRegions(
            self, _part: object, _angle: float, _find_self_intersections: bool
        ) -> list:
            return [empty_region]

    monkeypatch.setattr(
        support_module, "BlockSupportGenerator", FakeGridSupportGenerator
    )
    monkeypatch.setattr(
        support_module, "GridBlockSupportGenerator", FakeGridSupportGenerator
    )
    monkeypatch.setattr(support_geometry, "triangulate", lambda *_args: {})
    monkeypatch.setattr(support_geometry, "triangulate_float32", lambda *_args: [])
    session = ModelSession()
    session.load_stl(str(MODEL_PATH))

    meshes = session.generate_supports(
        support_type="grid_truss",
        overhang_angle=45.0,
        ray_resolution=0.6,
        outer_edge_gap=0.3,
        inner_edge_gap=0.2,
        simplify_factor=0.5,
        minimum_area=2.0,
        grid_spacing=5.0,
        truss_width=1.0,
        lattice_cell_size=5.0,
        border_distance=1.0,
        use_skin=True,
        upper_teeth=True,
        lower_teeth=True,
    )

    assert meshes == []
    assert session.support_regions == []
    assert "Skipping support region 1" in caplog.text


def test_support_generator_buffers_all_disconnected_polygons() -> None:
    from pyslm.support.support import BlockSupportGenerator
    from shapely.geometry import Polygon

    generator = BlockSupportGenerator()
    generator.innerSupportEdgeGap = 0.2
    generator.simplifyPolygonFactor = 0.5
    generator.rayProjectionResolution = 0.2
    disjoint_polygons = [
        Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
        Polygon([(20, 0), (30, 0), (30, 10), (20, 10)]),
    ]

    buffered_polygons = generator._bufferSupportPolygons(disjoint_polygons)

    assert len(buffered_polygons) == 2
    assert all(polygon.area == pytest.approx(92.16) for polygon in buffered_polygons)


def test_flatten_support_region_preserves_multiple_outlines() -> None:
    from pyslm.support.support import SupportStructure

    mesh = trimesh.Trimesh(
        vertices=[
            [0, 0, 1],
            [2, 0, 1],
            [2, 2, 1],
            [0, 2, 1],
            [5, 0, 1],
            [7, 0, 1],
            [7, 2, 1],
            [5, 2, 1],
        ],
        faces=[[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]],
        process=False,
    )

    flattened = SupportStructure.flattenSupportRegion(mesh)

    assert flattened.area == pytest.approx(8.0)
    assert len(flattened.geoms) == 2


def test_grid_support_polygon_repair_keeps_disconnected_components() -> None:
    from shapely.geometry import Polygon
    from shapely import make_valid

    from pyslm.support.gridBlockSupport import _polygonal_parts

    invalid_polygon = Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])
    repaired_parts = _polygonal_parts(make_valid(invalid_polygon))

    assert len(repaired_parts) == 2
    assert all(polygon.is_valid for polygon in repaired_parts)


def test_changing_voxel_screen_settings_clears_stale_overlay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("PyQt5")
    pytest.importorskip("pyqtgraph")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt5 import QtWidgets

    from pyslm_app.main import MainWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow()
    window._load_stl(str(MODEL_PATH))
    window._internal_void_mesh = trimesh.creation.box(extents=[1.0] * 3)
    window._probe_blocked_mesh = trimesh.creation.box(extents=[0.5] * 3)
    window._refresh_viewer()
    assert window.viewer._internal_void_item is not None
    assert window.viewer._probe_blocked_item is not None

    window.void_pitch_input.setValue(0.75)

    assert window._internal_void_mesh is None
    assert window._probe_blocked_mesh is None
    assert window.viewer._internal_void_item is None
    assert window.viewer._probe_blocked_item is None
    assert "Eseguire di nuovo" in window.geometry_diagnostics.toPlainText()

    window.close()
    app.processEvents()


def test_compare_orthogonal_orientations_uses_pyslm_estimates() -> None:
    pytest.importorskip("triangle")
    pytest.importorskip("mapbox_earcut")
    pytest.importorskip("vispy")

    session = ModelSession()
    session.load_stl(str(MODEL_PATH))
    current_rotation = session.part.rotation.copy()
    current_bounds = session.part.geometry.bounds.copy()

    candidates = session.compare_orthogonal_orientations(45.0)

    assert len(candidates) == 24
    assert len({candidate.rotation for candidate in candidates}) == 24
    scores = [candidate.support_moment_area for candidate in candidates]
    assert scores == sorted(scores)
    assert all(candidate.projected_overhang_area >= 0 for candidate in candidates)
    assert all(candidate.build_height > 0 for candidate in candidates)
    assert (session.part.rotation == current_rotation).all()
    assert (session.part.geometry.bounds == current_bounds).all()


def test_height_map_render_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    from pyslm.support import render

    class FailedCanvas:
        rgb = None

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def show(self, **_kwargs: object) -> None:
            pass

        def update(self) -> None:
            pass

        def close(self) -> None:
            pass

    expected_image = np.full((2, 2), 3.0, dtype=np.float32)
    monkeypatch.setattr(
        render, "_projectHeightMapVertical", lambda *_args: expected_image
    )
    monkeypatch.setattr(render, "Canvas", FailedCanvas)
    image = render.projectHeightMap(trimesh.creation.box(), useOpenGL=True)

    assert np.array_equal(image, expected_image)


def test_height_map_for_empty_mesh_returns_blank_image() -> None:
    from pyslm.support import render

    image = render.projectHeightMap(
        trimesh.Trimesh(),
        resolution=1.0,
        bbox=np.array([[0.0, 0.0, 0.0], [2.0, 3.0, 1.0]]),
    )

    assert image.shape == (3, 2)
    assert np.count_nonzero(image) == 0


@pytest.mark.parametrize(
    ("flip_direction", "expected"),
    [
        (False, [[0.75, 1.25], [1.75, 2.25]]),
        (True, [[1.75, 2.25], [0.75, 1.25]]),
    ],
)
def test_cpu_height_map_ray_projection(
    flip_direction: bool, expected: list
) -> None:
    pytest.importorskip("rtree")
    from pyslm.support.render import _projectHeightMapRay

    mesh = trimesh.Trimesh(
        vertices=[[0, 0, 0], [2, 0, 1], [2, 2, 3], [0, 2, 2]],
        faces=[[0, 1, 2], [0, 2, 3]],
        process=False,
    )
    image = _projectHeightMapRay(
        mesh,
        1.0,
        flip_direction,
        np.array([[0, 0, -1], [2, 2, 4]], dtype=float),
    )

    assert np.allclose(image, expected)


@pytest.mark.skipif(
    os.environ.get("PYSLM_RUN_SUPPORT_INTEGRATION") != "1",
    reason="Requires PySLM support extras and an available OpenGL desktop context.",
)
@pytest.mark.parametrize("support_type", ["walls", "block", "grid_truss"])
def test_generate_and_export_supports(tmp_path: Path, support_type: str) -> None:
    for module in ("triangle", "mapbox_earcut", "manifold3d", "vispy"):
        pytest.importorskip(module)

    model_path = Path(__file__).parent.parent / "models" / "frameGuide.stl"
    supports_path = tmp_path / "supports.stl"
    assembly_path = tmp_path / "assembly.stl"
    script = """
import json
import sys
from pyslm_app.services import ModelSession

session = ModelSession()
session.load_stl(sys.argv[2])
meshes = session.generate_supports(
    support_type=sys.argv[1],
    overhang_angle=45.0,
    ray_resolution=0.6,
    outer_edge_gap=0.3,
    inner_edge_gap=0.2,
    simplify_factor=0.5,
    minimum_area=2.0,
    grid_spacing=5.0,
    truss_width=1.0,
    lattice_cell_size=5.0,
    border_distance=1.0,
    use_skin=True,
    upper_teeth=True,
    lower_teeth=True,
)
if not session.support_regions or not meshes:
    raise RuntimeError("PySLM did not generate support geometry")
session.export_supports(sys.argv[3])
session.export_assembly(sys.argv[4])
print(json.dumps({
    "regions": len(session.support_regions),
    "faces": sum(len(mesh.faces) for mesh in meshes),
}))
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            support_type,
            str(model_path),
            str(supports_path),
            str(assembly_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    generation = json.loads(result.stdout.strip().splitlines()[-1])
    assert generation["regions"] > 0
    assert generation["faces"] > 0

    supports = trimesh.load_mesh(supports_path, process=False)
    assembly = trimesh.load_mesh(assembly_path, process=False)
    assert len(supports.faces) > 0
    assert len(assembly.faces) > len(supports.faces)


def test_surfaces_resting_on_build_plate_are_not_support_regions() -> None:
    import pyslm
    from pyslm.support import GridBlockSupportGenerator

    # A finely tessellated base is classified as an overhang (a two-triangle
    # base is smoothed away by the connectivity filter).
    plate = trimesh.creation.box(extents=[20.0, 20.0, 5.0])
    for _ in range(3):
        plate = plate.subdivide()
    part = pyslm.Part("plate_block")
    part.setGeometryByMesh(plate)
    part.dropToPlatform()

    generator = GridBlockSupportGenerator()
    generator.minimumAreaThreshold = 1.0

    # The only downward-facing surface is the base, which sits on the plate and
    # must not become an (always empty) support region.
    assert generator.identifySupportRegions(part, 45.0, True) == []
