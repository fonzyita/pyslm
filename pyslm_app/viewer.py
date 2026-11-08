"""Interactive OpenGL mesh viewer built on PyQtGraph."""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Tuple

import numpy as np
import pyqtgraph.opengl as gl
from pyqtgraph.opengl import shaders as gl_shaders
from PyQt5 import QtGui


_VERTEX_SHADER_SOURCE = """
varying vec3 surfaceNormal;
varying vec3 eyePosition;
varying vec3 worldPosition;
void main() {
    vec4 position = gl_ModelViewMatrix * gl_Vertex;
    eyePosition = position.xyz;
    // Mesh items are drawn without a transform, so vertex coordinates are world coordinates
    worldPosition = gl_Vertex.xyz;
    surfaceNormal = normalize(gl_NormalMatrix * gl_Normal);
    gl_FrontColor = gl_Color;
    gl_BackColor = gl_Color;
    gl_Position = gl_ProjectionMatrix * position;
}
"""

_FRAGMENT_SHADER_SOURCE = """
varying vec3 surfaceNormal;
varying vec3 eyePosition;
varying vec3 worldPosition;
uniform float uBrightness;
// Section plane a*x + b*y + c*z + d = 0; fragments on its positive side are cut away
uniform float uClipPlane[4];
uniform float uClipEnabled;
// Colour of the cut faces; a fourth component below 0.5 means "darkened surface colour"
uniform float uCapColor[4];
void main() {
    if (uClipEnabled > 0.5) {
        float side = uClipPlane[0] * worldPosition.x + uClipPlane[1] * worldPosition.y
                   + uClipPlane[2] * worldPosition.z + uClipPlane[3];
        if (side > 0.0) discard;
        if (!gl_FrontFacing) {
            // Through the cut the inside (back faces) of a closed solid is visible: paint it as a flat filled
            // section so the cut reads as a solid face
            vec3 cap = uCapColor[3] > 0.5
                ? vec3(uCapColor[0], uCapColor[1], uCapColor[2])
                : gl_Color.rgb * 0.55;
            gl_FragColor = vec4(clamp(cap * uBrightness, 0.0, 1.0), 1.0);
            return;
        }
    }
    vec3 normal = normalize(surfaceNormal);
    if (!gl_FrontFacing) normal = -normal;
    vec3 viewDirection = normalize(-eyePosition);
    vec3 keyLight = normalize(vec3(-0.45, 0.65, 0.75));
    vec3 fillLight = normalize(vec3(0.65, 0.25, 0.55));
    float keyDiffuse = max(dot(normal, keyLight), 0.0);
    float fillDiffuse = max(dot(normal, fillLight), 0.0);
    float keySpecular = pow(
        max(dot(reflect(-keyLight, normal), viewDirection), 0.0), 24.0
    );
    float fillSpecular = pow(
        max(dot(reflect(-fillLight, normal), viewDirection), 0.0), 30.0
    );
    vec3 baseColor = gl_Color.rgb;
    float lightLevel = 0.48 + 0.52 * keyDiffuse + 0.22 * fillDiffuse;
    vec3 color = baseColor * lightLevel;
    color += vec3(0.88, 0.89, 0.90) * (0.045 * keySpecular + 0.018 * fillSpecular);
    gl_FragColor = vec4(clamp(color * uBrightness, 0.0, 1.0), gl_Color.a);
}
"""


class _ContextShaderProgram(gl_shaders.ShaderProgram):
    """A pyqtgraph shader program compiled separately for every OpenGL context.

    pyqtgraph compiles a program once per process and reuses its id everywhere. When Qt recreates the OpenGL context
    of the viewer (e.g. after a style or window change) or a second viewer exists, that id is invalid in the new
    context and the meshes fail to draw ("Error while drawing item", ``glUseProgram`` invalid operation).
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._programs: dict = {}

    def program(self) -> int:
        from OpenGL.GL import shaders as gl_compile

        context = QtGui.QOpenGLContext.currentContext()
        key = id(context)
        if key not in self._programs:
            try:
                compiled = [gl_compile.compileShader(shader.code, shader.shaderType) for shader in self.shaders]
                self._programs[key] = gl_compile.compileProgram(*compiled)
            except Exception:
                self._programs[key] = -1
                raise
            if context is not None:
                # Forget the program when its context goes away, so a new context with a reused id recompiles
                context.aboutToBeDestroyed.connect(lambda key=key: self._programs.pop(key, None))
        return self._programs[key]


def _studio_shader(name: str) -> Any:
    return _ContextShaderProgram(
        name,
        [
            gl_shaders.VertexShader(_VERTEX_SHADER_SOURCE),
            gl_shaders.FragmentShader(_FRAGMENT_SHADER_SOURCE),
        ],
        uniforms={
            "uBrightness": [1.0],
            "uClipPlane": [0.0, 0.0, 1.0, 0.0],
            "uClipEnabled": [0.0],
            "uCapColor": [0.0, 0.0, 0.0, 0.0],
        },
    )


_STUDIO_SHADER = _studio_shader("pyslmStudioMetal")
_PART_SHADER = _studio_shader("pyslmStudioMetalPart")
# Cut faces: the part in brick red, supports and overlays in a darker shade of their own colour
_PART_SHADER["uCapColor"] = [0.80, 0.30, 0.22, 1.0]
_STUDIO_SHADER["uCapColor"] = [0.0, 0.0, 0.0, 0.0]
_SECTION_AXES = {"x": 0, "y": 1, "z": 2}


class MeshView(gl.GLViewWidget):
    """Renders the part, its overhang faces, and generated support meshes."""

    _PART_COLOR = (0.91, 0.86, 0.73, 1.0)
    _OVERHANG_COLOR = (0.94, 0.25, 0.16, 1.0)
    _SUPPORT_COLOR = (0.48, 0.66, 0.80, 1.0)  # matte light blue
    _SELECTED_SUPPORT_COLOR = (0.16, 0.66, 1.0, 1.0)  # intense bright blue
    _OVERHANG_DISPLAY_OFFSET = 0.03

    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._grid_color: Tuple[int, int, int, int] = (160, 164, 168, 85)
        self.setBackgroundColor((211, 213, 215))
        self.opts["distance"] = 160.0
        self._part_item: Optional[Any] = None
        self._overhang_item: Optional[Any] = None
        self._support_items: List[Any] = []
        self._grid_item: Optional[Any] = None
        self._axis_item: Optional[Any] = None
        self._brightness_percent = 50
        self._scene_bounds: Optional[np.ndarray] = None
        self._section: Optional[Tuple[str, float, bool]] = None
        self._install_reference_items(100.0)

    def set_theme_colors(self, background: Tuple[int, int, int], grid: Tuple[int, int, int, int]) -> None:
        """Background of the 3D view and colour of the build-plate grid."""
        self.setBackgroundColor(tuple(background))
        self._grid_color = tuple(grid)
        if self._grid_item is not None:
            self._grid_item.setColor(self._grid_color)
        self.update()

    def set_brightness(self, percent: int) -> None:
        """Set part brightness; 50% preserves the current renderer output."""
        self._brightness_percent = max(0, min(100, int(percent)))
        _PART_SHADER["uBrightness"] = [self._brightness_percent / 50.0]
        self.update()

    @property
    def scene_bounds(self) -> Optional[np.ndarray]:
        """(2, 3) bounds of the part and supports currently shown, or ``None``."""
        return None if self._scene_bounds is None else self._scene_bounds.copy()

    @property
    def section(self) -> Optional[Tuple[str, float, bool]]:
        """The active section ``(axis, position, flipped)`` or ``None``."""
        return self._section

    def set_section(self, axis: str, position: float, flipped: bool = False) -> None:
        """Cut the part and supports with a plane normal to ``axis`` at ``position`` (mm).

        Everything above the plane along the axis is hidden (below when ``flipped``) and the cut faces are drawn
        filled, updating instantly on the GPU.
        """
        index = _SECTION_AXES[axis.lower()]
        normal = [0.0, 0.0, 0.0]
        normal[index] = -1.0 if flipped else 1.0
        plane = [*normal, -normal[index] * float(position)]
        for shader in (_PART_SHADER, _STUDIO_SHADER):
            shader["uClipPlane"] = plane
            shader["uClipEnabled"] = [1.0]
        self._section = (axis.lower(), float(position), bool(flipped))
        self.update()

    def clear_section(self) -> None:
        for shader in (_PART_SHADER, _STUDIO_SHADER):
            shader["uClipEnabled"] = [0.0]
        self._section = None
        self.update()

    def show_meshes(
        self,
        part: Optional[Any],
        overhang: Optional[Any] = None,
        supports: Iterable[Any] = (),
        selected_support_index: Optional[int] = None,
        internal_voids: Optional[Any] = None,
        probe_blocked_regions: Optional[Any] = None,
    ) -> None:
        self._remove_dynamic_items()
        if part is None:
            self._scene_bounds = None
            return

        support_meshes = [mesh for mesh in supports if len(mesh.faces) > 0]
        if selected_support_index is not None and not (
            0 <= selected_support_index < len(support_meshes)
        ):
            raise IndexError(
                f"Indice supporto selezionato non valido: {selected_support_index}"
            )

        extents = np.asarray(part.extents, dtype=float)
        size = max(float(np.max(extents)), 1.0)
        self._install_reference_items(size)
        bounds = [np.asarray(part.bounds, dtype=float)]
        bounds += [np.asarray(mesh.bounds, dtype=float) for mesh in support_meshes]
        self._scene_bounds = np.array([np.min([b[0] for b in bounds], axis=0),
                                       np.max([b[1] for b in bounds], axis=0)])

        # Draw supports first so the opaque part hides the intentional
        # penetration used to create reliable support contact.
        for index, mesh in enumerate(support_meshes):
            color = (
                self._SELECTED_SUPPORT_COLOR
                if index == selected_support_index
                else self._SUPPORT_COLOR
            )
            item = self._mesh_item(mesh, color, "opaque")
            self._support_items.append(item)
            self.addItem(item)

        display_part = part.copy()
        # STL files often store every triangle with its own duplicate vertices.
        # Weld a display copy, then create crease-aware smoothing groups so
        # smooth regions share normals while hard transitions remain separate.
        display_part.merge_vertices()
        display_part.fix_normals(multibody=True)
        display_part = self._split_display_mesh_by_normal_angle(display_part)
        part_color = (
            (*self._PART_COLOR[:3], 0.22)
            if internal_voids is not None
            else self._PART_COLOR
        )
        part_options = "translucent" if internal_voids is not None else "opaque"
        self._part_item = self._mesh_item(
            display_part,
            part_color,
            part_options,
            repair_normals=True,
            shader_name="pyslmStudioMetalPart",
        )
        self.addItem(self._part_item)

        if overhang is not None and len(overhang.faces) > 0:
            display_overhang = self._offset_surface_for_display(
                overhang, self._OVERHANG_DISPLAY_OFFSET
            )
            self._overhang_item = self._mesh_item(
                display_overhang, self._OVERHANG_COLOR, "opaque", smooth=False
            )
            self.addItem(self._overhang_item)

        self._internal_void_item = None
        if internal_voids is not None and len(internal_voids.faces) > 0:
            self._internal_void_item = self._mesh_item(
                internal_voids, (1.0, 0.55, 0.12, 0.75), "translucent"
            )
            self.addItem(self._internal_void_item)

        self._probe_blocked_item = None
        if probe_blocked_regions is not None and len(probe_blocked_regions.faces) > 0:
            self._probe_blocked_item = self._mesh_item(
                probe_blocked_regions, (0.95, 0.18, 0.28, 0.82), "translucent"
            )
            self.addItem(self._probe_blocked_item)

        self._selected_support_index = selected_support_index
        center = np.asarray(part.bounds, dtype=float).mean(axis=0)
        self.setCameraPosition(
            pos=QtGui.QVector3D(*map(float, center)),
            distance=max(size * 3.0, 10.0),
            elevation=25.0,
            azimuth=42.0,
        )

    def set_selected_support(self, index: Optional[int]) -> None:
        if index is not None and not 0 <= index < len(self._support_items):
            raise IndexError(f"Indice supporto selezionato non valido: {index}")

        self._selected_support_index = index
        for support_index, item in enumerate(self._support_items):
            color = (
                self._SELECTED_SUPPORT_COLOR
                if support_index == index
                else self._SUPPORT_COLOR
            )
            face_colors = np.tile(
                np.asarray(color, dtype=np.float32),
                (len(item.opts["meshdata"].faceColors()), 1),
            )
            item.opts["meshdata"].setFaceColors(face_colors)
            item.meshDataChanged()

    def _remove_dynamic_items(self) -> None:
        for item in [
            self._part_item,
            self._overhang_item,
            getattr(self, "_internal_void_item", None),
            getattr(self, "_probe_blocked_item", None),
            *self._support_items,
        ]:
            if item is not None:
                self.removeItem(item)
        self._part_item = None
        self._overhang_item = None
        self._internal_void_item = None
        self._probe_blocked_item = None
        self._support_items = []

    def _install_reference_items(self, model_size: float) -> None:
        if self._grid_item is not None:
            self.removeItem(self._grid_item)
        if self._axis_item is not None:
            self.removeItem(self._axis_item)

        grid_size = max(model_size * 2.5, 50.0)
        spacing = max(float(round(model_size / 20.0)), 1.0)
        self._grid_item = gl.GLGridItem()
        self._grid_item.setSize(x=grid_size, y=grid_size)
        self._grid_item.setSpacing(x=spacing, y=spacing)
        self._grid_item.setColor(self._grid_color)
        # Slightly below the build plate, so supports standing on it do not z-fight with the grid
        self._grid_item.translate(0.0, 0.0, -0.02 * max(model_size / 100.0, 0.1))
        self.addItem(self._grid_item)

        self._axis_item = gl.GLAxisItem()
        axis_size = max(model_size * 0.35, 10.0)
        self._axis_item.setSize(x=axis_size, y=axis_size, z=axis_size)
        self.addItem(self._axis_item)

    @staticmethod
    def _mesh_item(
        mesh: Any,
        color: Tuple[float, float, float, float],
        options: str,
        draw_edges: bool = False,
        edge_color: Tuple[float, float, float, float] = (0.5, 0.5, 0.5, 1.0),
        smooth: bool = True,
        repair_normals: bool = False,
        shader_name: str = "pyslmStudioMetal",
    ) -> Any:
        mesh_data = gl.MeshData(
            vertexes=np.asarray(mesh.vertices, dtype=np.float32),
            faces=np.asarray(mesh.faces, dtype=np.uint32),
            faceColors=np.tile(np.asarray(color, dtype=np.float32), (len(mesh.faces), 1)),
        )
        if smooth and repair_normals:
            MeshView._repair_vertex_normals(mesh_data)
        return gl.GLMeshItem(
            meshdata=mesh_data,
            smooth=smooth,
            drawEdges=draw_edges,
            edgeColor=edge_color,
            shader=shader_name,
            glOptions=options,
        )

    @staticmethod
    def _repair_vertex_normals(mesh_data: Any) -> None:
        """Build finite display normals, tolerating degenerate STL triangles."""
        vertices = np.asarray(mesh_data.vertexes(), dtype=np.float64)
        faces = np.asarray(mesh_data.faces(), dtype=np.int64)
        triangles = vertices[faces]
        face_normals = np.cross(
            triangles[:, 1] - triangles[:, 0],
            triangles[:, 2] - triangles[:, 0],
        )
        face_lengths = np.linalg.norm(face_normals, axis=1)
        valid_faces = face_lengths > 1e-12
        face_normals[valid_faces] /= face_lengths[valid_faces, np.newaxis]
        face_normals[~valid_faces] = 0.0

        # Angle weighting avoids bands where STL triangle sizes vary sharply.
        corner_angles = np.zeros((len(faces), 3), dtype=np.float64)
        for corner in range(3):
            first = triangles[:, (corner + 1) % 3] - triangles[:, corner]
            second = triangles[:, (corner + 2) % 3] - triangles[:, corner]
            cross_length = np.linalg.norm(np.cross(first, second), axis=1)
            dot = np.einsum("ij,ij->i", first, second)
            corner_angles[:, corner] = np.arctan2(cross_length, dot)
        corner_angles[~valid_faces] = 0.0

        vertex_normals = np.zeros_like(vertices)
        for corner in range(3):
            np.add.at(vertex_normals, faces[:, corner], face_normals * corner_angles[:, corner, np.newaxis])
        lengths = np.linalg.norm(vertex_normals, axis=1)
        valid_vertices = lengths > 1e-12
        vertex_normals[valid_vertices] /= lengths[valid_vertices, np.newaxis]
        vertex_normals[~valid_vertices] = (0.0, 0.0, 1.0)
        # MeshData's GLMeshItem renderer reads this cache for smooth shading.
        mesh_data._vertexNormals = vertex_normals.astype(np.float32)

    @staticmethod
    def _split_display_mesh_by_normal_angle(mesh: Any, threshold_degrees: float = 70.0) -> Any:
        """Split only display vertices across creases, like angle-based face groups."""
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        import trimesh

        faces = np.asarray(mesh.faces, dtype=np.int64)
        adjacency = np.asarray(mesh.face_adjacency, dtype=np.int64)
        if len(adjacency) == 0:
            return mesh

        normals = np.asarray(mesh.face_normals, dtype=np.float64)
        cos_threshold = np.cos(np.radians(threshold_degrees))
        smooth = np.einsum(
            "ij,ij->i", normals[adjacency[:, 0]], normals[adjacency[:, 1]]
        ) >= cos_threshold
        # Connect face-corners only across a smooth shared edge. Components of
        # this corner graph are local to each original vertex; unlike grouping
        # whole faces globally, they cannot bridge a crease via a distant path.
        links = adjacency[smooth]
        shared_edges = np.asarray(mesh.face_adjacency_edges, dtype=np.int64)[smooth]
        first_corners = []
        second_corners = []
        for endpoint in range(2):
            shared_vertex = shared_edges[:, endpoint]
            first_corner = np.argmax(faces[links[:, 0]] == shared_vertex[:, None], axis=1)
            second_corner = np.argmax(faces[links[:, 1]] == shared_vertex[:, None], axis=1)
            first_corners.append(links[:, 0] * 3 + first_corner)
            second_corners.append(links[:, 1] * 3 + second_corner)
        corner_links_first = np.concatenate(first_corners)
        corner_links_second = np.concatenate(second_corners)
        graph = coo_matrix(
            (
                np.ones(len(corner_links_first) * 2, dtype=np.uint8),
                (
                    np.r_[corner_links_first, corner_links_second],
                    np.r_[corner_links_second, corner_links_first],
                ),
            ),
            shape=(len(faces) * 3, len(faces) * 3),
        ).tocsr()
        _, corner_groups = connected_components(graph, directed=False)

        # Duplicate vertices across local crease groups to retain hard edges.
        corner_pairs = np.column_stack(
            (corner_groups, faces.reshape(-1))
        )
        unique_pairs, inverse = np.unique(corner_pairs, axis=0, return_inverse=True)
        vertices = np.asarray(mesh.vertices, dtype=np.float64)[unique_pairs[:, 1]]
        grouped_faces = inverse.reshape((-1, 3))
        return trimesh.Trimesh(vertices=vertices, faces=grouped_faces, process=False)

    @staticmethod
    def _offset_surface_for_display(mesh: Any, distance: float) -> Any:
        """Move a display-only surface along its face normals to avoid z-fighting."""
        import trimesh

        triangles = np.asarray(mesh.vertices, dtype=float)[np.asarray(mesh.faces)]
        triangles = triangles + np.asarray(mesh.face_normals)[:, np.newaxis, :] * distance
        vertices = triangles.reshape((-1, 3))
        faces = np.arange(len(vertices), dtype=np.uint32).reshape((-1, 3))
        return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
