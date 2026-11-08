"""Application services backed by PySLM and Trimesh."""

from __future__ import annotations

import logging
from time import perf_counter
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any, Callable, List, Literal, Optional, Sequence, Set, Tuple

import numpy as np


@dataclass(frozen=True)
class OrientationCandidate:
    """A PySLM-scored orthogonal build orientation."""

    rotation: Tuple[float, float, float]
    support_moment_area: float
    projected_overhang_area: float
    build_height: float


@dataclass(frozen=True)
class EnclosedShellCandidate:
    """A closed, inward-oriented shell nested within an outer mesh shell."""

    volume: float
    bounds: Tuple[Tuple[float, float, float], Tuple[float, float, float]]


@dataclass(frozen=True)
class InternalVoidCandidate:
    """A sampled free-space component not connected to the mesh exterior."""

    volume: float
    bounds: Tuple[Tuple[float, float, float], Tuple[float, float, float]]
    voxel_count: int


@dataclass(frozen=True)
class InternalVoidScreening:
    """Resolution and results of a voxel-based internal-void screening."""

    build_rotation: Tuple[float, float, float]
    voxel_pitch: float
    grid_shape: Tuple[int, int, int]
    sampled_voxel_count: int
    candidates: Tuple[InternalVoidCandidate, ...]
    probe_diameter: Optional[float]
    probe_blocked_candidates: Tuple[InternalVoidCandidate, ...]
    visualization_mesh: Optional[Any]
    probe_blocked_visualization_mesh: Optional[Any]


@dataclass(frozen=True)
class MeshDiagnostics:
    """Mesh integrity facts and explicitly qualified cavity indicators."""

    triangle_count: int
    body_count: int
    watertight: bool
    winding_consistent: bool
    valid_volume: bool
    euler_number: int
    degenerate_face_count: int
    enclosed_shell_candidates: Tuple[EnclosedShellCandidate, ...]


class ModelSession:
    """Owns the active PySLM part and derived analysis/support meshes."""

    _MAX_SCREENING_VOXELS = 250_000
    _SCREENING_BATCH_SIZE = 25_000

    def __init__(self) -> None:
        self.part: Optional[Any] = None
        self.source_path: Optional[Path] = None
        self._source_geometry: Optional[Any] = None
        self._diagnostic_geometry: Optional[Any] = None
        self.overhang_mesh: Optional[Any] = None
        self.support_regions: List[Any] = []
        self.support_meshes: List[Any] = []
        self._removed_supports: List[Tuple[int, Any, Any]] = []

    @property
    def has_part(self) -> bool:
        return self.part is not None

    @property
    def can_restore_support_region(self) -> bool:
        return bool(self._removed_supports)

    def load_stl(self, file_path: str) -> Tuple[float, float, float]:
        path = Path(file_path)
        if path.suffix.lower() != ".stl":
            raise ValueError("Selezionare un file STL.")
        if not path.is_file():
            raise FileNotFoundError(f"File non trovato: {path}")

        from pyslm import Part
        import trimesh

        part = Part(path.stem)
        part.setGeometry(str(path), fixGeometry=True)
        mesh = part.geometry
        if mesh is None or len(mesh.faces) == 0:
            raise ValueError("Il file STL non contiene una mesh triangolare valida.")

        center = mesh.bounds.mean(axis=0)
        part.origin = [-float(center[0]), -float(center[1]), 0.0]
        part.dropToPlatform()

        diagnostic_geometry = trimesh.load_mesh(
            str(path), process=False, validate=False
        )
        if isinstance(diagnostic_geometry, trimesh.Scene):
            diagnostic_geometry = diagnostic_geometry.to_geometry()
        if not isinstance(diagnostic_geometry, trimesh.Trimesh):
            raise ValueError("Impossibile leggere la mesh STL per la diagnostica.")
        diagnostic_geometry.merge_vertices()

        self.part = part
        self.source_path = path
        self._source_geometry = part.geometry.copy()
        self._diagnostic_geometry = diagnostic_geometry
        self.overhang_mesh = None
        self.clear_supports()
        return tuple(float(value) for value in part.extents)

    def set_orientation(self, x_degrees: float, y_degrees: float, z_degrees: float) -> None:
        part = self._require_part()
        part.rotation = [x_degrees, y_degrees, z_degrees]
        self._center_on_platform(part)
        self.overhang_mesh = None
        self.clear_supports()

    def compare_orthogonal_orientations(
        self, overhang_angle: float
    ) -> List[OrientationCandidate]:
        from pyslm import Part
        from pyslm.support import approximateSupportMomentArea, getApproximateSupportArea
        import trimesh

        source_geometry = self._require_source_geometry()
        candidates: List[OrientationCandidate] = []
        seen_rotations: Set[Tuple[float, ...]] = set()

        for rotation in product((0.0, 90.0, 180.0, 270.0), repeat=3):
            radians = tuple(float(value) for value in np.deg2rad(rotation))
            matrix = trimesh.transformations.euler_matrix(*radians, axes="rxyz")[:3, :3]
            key = tuple(float(value) for value in matrix.round(8).flatten())
            if key in seen_rotations:
                continue
            seen_rotations.add(key)

            candidate_part = Part("orientation-candidate")
            candidate_part.setGeometryByMesh(source_geometry.copy())
            candidate_part.rotation = rotation
            self._center_on_platform(candidate_part)

            support_moment_area = float(
                approximateSupportMomentArea(candidate_part, float(overhang_angle))
            )
            projected_area = float(
                getApproximateSupportArea(
                    candidate_part, float(overhang_angle), projected=True
                ).sum()
            )
            candidates.append(
                OrientationCandidate(
                    rotation=rotation,
                    support_moment_area=support_moment_area,
                    projected_overhang_area=projected_area,
                    build_height=float(candidate_part.extents[2]),
                )
            )

        if len(candidates) != 24:
            raise RuntimeError(
                f"Attese 24 orientazioni ortogonali distinte, ottenute {len(candidates)}."
            )
        return sorted(
            candidates,
            key=lambda candidate: (
                candidate.support_moment_area,
                candidate.projected_overhang_area,
                candidate.build_height,
            ),
        )

    def analyze_overhangs(self, overhang_angle: float) -> Any:
        part = self._require_part()
        from pyslm.support import getOverhangMesh

        self.overhang_mesh = getOverhangMesh(
            part,
            float(overhang_angle),
            splitMesh=False,
            useConnectivity=False,
        )
        return self.overhang_mesh

    def analyze_mesh(self) -> MeshDiagnostics:
        self._require_part()
        mesh = self._require_diagnostic_geometry()
        if len(mesh.faces) == 0:
            raise ValueError("Il file STL non contiene facce da analizzare.")

        components = mesh.split(only_watertight=False)
        enclosed_candidates = []
        positive_shells = [
            component
            for component in components
            if component.is_watertight and component.volume > 0.0
        ]

        for component in components:
            if not component.is_watertight or component.volume >= 0.0:
                continue
            center = component.bounds.mean(axis=0).reshape(1, 3)
            for container in positive_shells:
                if abs(float(container.volume)) <= abs(float(component.volume)):
                    continue
                if bool(container.contains(center)[0]):
                    bounds = tuple(
                        tuple(float(value) for value in bound)
                        for bound in component.bounds
                    )
                    enclosed_candidates.append(
                        EnclosedShellCandidate(
                            volume=abs(float(component.volume)),
                            bounds=bounds,
                        )
                    )
                    break

        valid_volume = bool(mesh.is_volume)
        return MeshDiagnostics(
            triangle_count=len(mesh.faces),
            body_count=int(mesh.body_count),
            watertight=bool(mesh.is_watertight),
            winding_consistent=bool(mesh.is_winding_consistent),
            valid_volume=valid_volume,
            euler_number=int(mesh.euler_number),
            degenerate_face_count=int((mesh.area_faces <= 1e-12).sum()),
            enclosed_shell_candidates=tuple(enclosed_candidates),
        )

    def screen_internal_voids(
        self, voxel_pitch: float, probe_diameter: Optional[float] = None
    ) -> InternalVoidScreening:
        """Find free-space voxel components enclosed by a valid STL mesh.

        The optional spherical-probe screen estimates clearance-limited access;
        neither screen determines powder evacuation.
        """
        part = self._require_part()
        mesh = self._require_diagnostic_geometry().copy()
        mesh.apply_transform(part.getTransform())
        pitch = float(voxel_pitch)
        if not np.isfinite(pitch) or pitch <= 0.0:
            raise ValueError("Il passo voxel deve essere un numero finito positivo.")
        probe = None if probe_diameter is None else float(probe_diameter)
        if probe is not None and (not np.isfinite(probe) or probe <= 0.0):
            raise ValueError(
                "Il diametro della sonda deve essere un numero finito positivo."
            )
        if not mesh.is_volume:
            raise ValueError(
                "Lo screening richiede una mesh chiusa con orientamento coerente "
                "e volume valido."
            )

        import scipy.ndimage

        minimum, maximum = mesh.bounds
        grid_shape = tuple(
            int(np.ceil((maximum[axis] - minimum[axis]) / pitch)) + 2
            for axis in range(3)
        )
        voxel_count = int(np.prod(grid_shape, dtype=np.int64))
        if voxel_count > self._MAX_SCREENING_VOXELS:
            raise ValueError(
                f"Lo screening richiede {voxel_count:,} voxel, oltre il limite "
                f"di {self._MAX_SCREENING_VOXELS:,}. Aumentare il passo voxel."
            )

        grid_origin = minimum - pitch
        inside = np.empty(voxel_count, dtype=bool)
        y_size, z_size = grid_shape[1:]
        for start in range(0, voxel_count, self._SCREENING_BATCH_SIZE):
            stop = min(start + self._SCREENING_BATCH_SIZE, voxel_count)
            flat = np.arange(start, stop, dtype=np.int64)
            x_index = flat // (y_size * z_size)
            y_index = (flat // z_size) % y_size
            z_index = flat % z_size
            points = grid_origin + (
                np.column_stack((x_index, y_index, z_index)) + 0.5
            ) * pitch
            inside[start:stop] = mesh.contains(points)

        structure = scipy.ndimage.generate_binary_structure(3, 1)
        labels, label_count = scipy.ndimage.label(
            ~inside.reshape(grid_shape), structure=structure
        )
        boundary_labels = np.unique(
            np.concatenate(
                (
                    labels[0, :, :].ravel(),
                    labels[-1, :, :].ravel(),
                    labels[:, 0, :].ravel(),
                    labels[:, -1, :].ravel(),
                    labels[:, :, 0].ravel(),
                    labels[:, :, -1].ravel(),
                )
            )
        )
        exterior_labels = set(int(label) for label in boundary_labels if label)
        component_sizes = np.bincount(labels.ravel(), minlength=label_count + 1)
        component_slices = scipy.ndimage.find_objects(
            labels, max_label=label_count
        )
        candidates = []
        internal_void_mask = np.zeros(grid_shape, dtype=bool)
        for label in range(1, label_count + 1):
            count = int(component_sizes[label])
            if count == 0 or label in exterior_labels:
                continue
            internal_void_mask |= labels == label
            lower = grid_origin + np.array(
                [axis_slice.start for axis_slice in component_slices[label - 1]],
                dtype=float,
            ) * pitch
            upper = grid_origin + (
                np.array(
                    [axis_slice.stop for axis_slice in component_slices[label - 1]],
                    dtype=float,
                )
            ) * pitch
            bounds = tuple(
                tuple(float(value) for value in bound)
                for bound in (lower, upper)
            )
            candidates.append(
                InternalVoidCandidate(
                    volume=count * pitch**3,
                    bounds=bounds,
                    voxel_count=count,
                )
            )

        probe_blocked_candidates = []
        probe_blocked_mask = np.zeros(grid_shape, dtype=bool)
        if probe is not None:
            free_space = ~inside.reshape(grid_shape)
            center_clearance = scipy.ndimage.distance_transform_edt(
                free_space, sampling=pitch
            )
            conservative_radius = probe / 2.0 + pitch * np.sqrt(3.0) / 2.0
            probe_passable = free_space & (center_clearance >= conservative_radius)
            probe_labels, probe_label_count = scipy.ndimage.label(
                probe_passable, structure=structure
            )
            probe_boundary_labels = np.unique(
                np.concatenate(
                    (
                        probe_labels[0, :, :].ravel(),
                        probe_labels[-1, :, :].ravel(),
                        probe_labels[:, 0, :].ravel(),
                        probe_labels[:, -1, :].ravel(),
                        probe_labels[:, :, 0].ravel(),
                        probe_labels[:, :, -1].ravel(),
                    )
                )
            )
            probe_exterior_labels = set(
                int(label) for label in probe_boundary_labels if label
            )
            probe_component_sizes = np.bincount(
                probe_labels.ravel(), minlength=probe_label_count + 1
            )
            probe_component_slices = scipy.ndimage.find_objects(
                probe_labels, max_label=probe_label_count
            )
            for label in range(1, probe_label_count + 1):
                count = int(probe_component_sizes[label])
                if count == 0 or label in probe_exterior_labels:
                    continue
                component_slices = probe_component_slices[label - 1]
                probe_blocked_mask |= probe_labels == label
                lower = grid_origin + np.array(
                    [axis_slice.start for axis_slice in component_slices],
                    dtype=float,
                ) * pitch
                upper = grid_origin + np.array(
                    [axis_slice.stop for axis_slice in component_slices],
                    dtype=float,
                ) * pitch
                bounds = tuple(
                    tuple(float(value) for value in bound)
                    for bound in (lower, upper)
                )
                probe_blocked_candidates.append(
                    InternalVoidCandidate(
                        volume=count * pitch**3,
                        bounds=bounds,
                        voxel_count=count,
                    )
                )

        visualization_mesh = None
        probe_blocked_visualization_mesh = None
        if candidates:
            import trimesh

            visualization_mesh = trimesh.voxel.ops.matrix_to_marching_cubes(
                internal_void_mask, pitch=pitch
            )
            visualization_mesh.apply_translation(grid_origin + pitch / 2.0)
        if probe_blocked_candidates:
            import trimesh

            probe_blocked_visualization_mesh = (
                trimesh.voxel.ops.matrix_to_marching_cubes(
                    probe_blocked_mask, pitch=pitch
                )
            )
            probe_blocked_visualization_mesh.apply_translation(
                grid_origin + pitch / 2.0
            )

        return InternalVoidScreening(
            build_rotation=tuple(float(value) for value in part.rotation),
            voxel_pitch=pitch,
            grid_shape=grid_shape,
            sampled_voxel_count=voxel_count,
            candidates=tuple(
                sorted(candidates, key=lambda candidate: candidate.volume, reverse=True)
            ),
            probe_diameter=probe,
            probe_blocked_candidates=tuple(
                sorted(
                    probe_blocked_candidates,
                    key=lambda candidate: candidate.volume,
                    reverse=True,
                )
            ),
            visualization_mesh=visualization_mesh,
            probe_blocked_visualization_mesh=probe_blocked_visualization_mesh,
        )

    def generate_supports(
        self,
        support_type: Literal["block", "grid_truss"],
        overhang_angle: float,
        ray_resolution: float,
        outer_edge_gap: float,
        inner_edge_gap: float,
        simplify_factor: float,
        minimum_area: float,
        grid_spacing: float,
        truss_width: float,
        lattice_cell_size: float,
        border_distance: float,
        use_skin: bool,
        upper_teeth: bool,
        lower_teeth: bool,
    ) -> Sequence[Any]:
        """Identify the support regions, build their geometry and store the result."""
        regions = self.identify_support_regions(
            support_type, overhang_angle, ray_resolution, outer_edge_gap,
            inner_edge_gap, simplify_factor, minimum_area, grid_spacing,
            truss_width, lattice_cell_size, border_distance, use_skin,
            upper_teeth, lower_teeth,
        )
        generated_regions, meshes = self.build_support_geometry(regions)
        self.apply_generated_supports(generated_regions, meshes)
        return self.support_meshes

    def identify_support_regions(
        self,
        support_type: Literal["block", "grid_truss"],
        overhang_angle: float,
        ray_resolution: float,
        outer_edge_gap: float,
        inner_edge_gap: float,
        simplify_factor: float,
        minimum_area: float,
        grid_spacing: float,
        truss_width: float,
        lattice_cell_size: float,
        border_distance: float,
        use_skin: bool,
        upper_teeth: bool,
        lower_teeth: bool,
    ) -> List[Any]:
        """Identify the support regions; uses OpenGL, so call it on the GUI thread."""
        part = self._require_part()
        from pyslm.support import geometry as support_geometry

        support_geometry._require_triangulation_backend()
        from pyslm.support import BlockSupportGenerator, GridBlockSupportGenerator

        if support_type == "block":
            generator = BlockSupportGenerator()
        elif support_type == "grid_truss":
            generator = GridBlockSupportGenerator()
        else:
            raise ValueError(f"Tipo di supporto PySLM non valido: {support_type}")

        generator.rayProjectionResolution = float(ray_resolution)
        generator.outerSupportEdgeGap = float(outer_edge_gap)
        generator.innerSupportEdgeGap = float(inner_edge_gap)
        generator.simplifyPolygonFactor = float(simplify_factor)
        generator.minimumAreaThreshold = float(minimum_area)
        # PySLM disables these by default. Without them, overhangs whose
        # downward projection reaches the build plate without intersecting the
        # part are silently omitted, which is common for this desktop workflow.
        generator._useApproxBasePlateSupport = True
        if support_type == "grid_truss":
            generator.gridSpacing = [float(grid_spacing), float(grid_spacing)]
            generator.trussWidth = float(truss_width)
            generator.latticeCellSize = float(lattice_cell_size)
            generator.supportBorderDistance = float(border_distance)
            generator.useSupportSkin = bool(use_skin)
            generator.useUpperSupportTeeth = bool(upper_teeth)
            generator.useLowerSupportTeeth = bool(lower_teeth)

        generation_start = perf_counter()
        regions = generator.identifySupportRegions(part, float(overhang_angle), True)
        logging.info(
            "Support region identification completed in %.2fs (%d regions)",
            perf_counter() - generation_start,
            len(regions),
        )
        return list(regions)

    @staticmethod
    def build_support_geometry(
        regions: Sequence[Any],
        progress: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[List[Any], List[Any]]:
        """Build the mesh of every identified support region.

        This step does not use OpenGL or touch the session state, so the desktop
        application runs it on a worker thread. ``progress`` is called with the
        number of processed regions and the total before each region and once
        at the end.
        """
        build_start = perf_counter()
        generated_regions = []
        meshes = []
        skipped_empty_regions = 0
        for index, region in enumerate(regions):
            if progress is not None:
                progress(index, len(regions))
            support_volume = getattr(region, "supportVolume", None)
            if (
                support_volume is None
                or len(support_volume.vertices) == 0
                or len(support_volume.faces) == 0
                or support_volume.bounds is None
            ):
                logging.warning(
                    "Skipping support region %d: PySLM produced an empty support volume.",
                    index + 1,
                )
                skipped_empty_regions += 1
                continue

            region_start = perf_counter()
            mesh = region.geometry()
            logging.info(
                "Support region %d geometry completed in %.2fs (%d faces)",
                index + 1,
                perf_counter() - region_start,
                0 if mesh is None else len(mesh.faces),
            )
            if mesh is not None and len(mesh.faces) > 0:
                generated_regions.append(region)
                meshes.append(mesh)
        if progress is not None:
            progress(len(regions), len(regions))

        if regions and not generated_regions and not skipped_empty_regions:
            raise RuntimeError(
                "PySLM ha individuato regioni di supporto ma non ha prodotto mesh esportabili."
            )
        logging.info(
            "Support geometry completed in %.2fs (%d of %d regions retained)",
            perf_counter() - build_start,
            len(generated_regions),
            len(regions),
        )
        return generated_regions, meshes

    def apply_generated_supports(self, regions: Sequence[Any], meshes: Sequence[Any]) -> None:
        self.support_regions = list(regions)
        self.support_meshes = list(meshes)
        self._removed_supports = []

    def remove_support_region(self, index: int) -> Any:
        if index < 0 or index >= len(self.support_regions):
            raise IndexError(f"Indice regione supporto non valido: {index}")
        if index >= len(self.support_meshes):
            raise RuntimeError(
                "La corrispondenza tra regione supporto e mesh è incoerente."
            )

        region = self.support_regions.pop(index)
        mesh = self.support_meshes.pop(index)
        self._removed_supports.append((index, region, mesh))
        return region

    def restore_last_removed_support_region(self) -> int:
        if not self._removed_supports:
            raise RuntimeError("Non ci sono regioni rimosse da ripristinare.")

        index, region, mesh = self._removed_supports.pop()
        self.support_regions.insert(index, region)
        self.support_meshes.insert(index, mesh)
        return index

    def clear_supports(self) -> None:
        self.support_regions = []
        self.support_meshes = []
        self._removed_supports = []

    def export_part(self, file_path: str) -> None:
        self._write_stl(self._require_part().geometry, file_path)

    def export_supports(self, file_path: str) -> None:
        if not self.support_meshes:
            raise ValueError("Non ci sono supporti generati da esportare.")
        self._write_stl(self._concatenated_supports(), file_path)

    def export_assembly(self, file_path: str) -> None:
        if not self.support_meshes:
            raise ValueError("Generare i supporti prima di esportare il modello completo.")
        from trimesh.util import concatenate

        meshes = [self._require_part().geometry] + list(self.support_meshes)
        self._write_stl(concatenate(meshes), file_path)

    def get_metrics(self) -> Tuple[Tuple[float, float, float], Optional[float]]:
        part = self._require_part()
        volume: Optional[float]
        try:
            volume = float(part.volume)
        except (RuntimeError, ValueError):
            volume = None
        return tuple(float(value) for value in part.extents), volume

    def _concatenated_supports(self) -> Any:
        from trimesh.util import concatenate

        return concatenate(self.support_meshes)

    @staticmethod
    def _write_stl(mesh: Any, file_path: str) -> None:
        destination = Path(file_path)
        if destination.suffix.lower() != ".stl":
            raise ValueError("Il percorso di esportazione deve avere estensione .stl.")
        data = mesh.export(file_type="stl")
        destination.write_bytes(data)

    def _require_part(self) -> Any:
        if self.part is None:
            raise RuntimeError("Importare prima un componente STL.")
        return self.part

    def _require_source_geometry(self) -> Any:
        if self._source_geometry is None:
            raise RuntimeError("Importare prima un componente STL.")
        return self._source_geometry

    def _require_diagnostic_geometry(self) -> Any:
        if self._diagnostic_geometry is None:
            raise RuntimeError("Importare prima un componente STL.")
        return self._diagnostic_geometry

    @staticmethod
    def _center_on_platform(part: Any) -> None:
        bounds = part.geometry.bounds
        origin = part.origin.copy()
        origin[0] -= float((bounds[0, 0] + bounds[1, 0]) / 2.0)
        origin[1] -= float((bounds[0, 1] + bounds[1, 1]) / 2.0)
        part.origin = origin
        part.dropToPlatform()
