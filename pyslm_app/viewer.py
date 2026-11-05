"""Interactive OpenGL mesh viewer built on PyQtGraph."""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Tuple

import numpy as np
import pyqtgraph.opengl as gl
from PyQt5 import QtGui


class MeshView(gl.GLViewWidget):
    """Renders the part, its overhang faces, and generated support meshes."""

    _SUPPORT_COLOR = (0.18, 0.76, 0.68, 1.0)
    _SELECTED_SUPPORT_COLOR = (1.0, 0.62, 0.16, 1.0)

    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self.setBackgroundColor((19, 24, 31))
        self.opts["distance"] = 160.0
        self._part_item: Optional[Any] = None
        self._overhang_item: Optional[Any] = None
        self._support_items: List[Any] = []
        self._grid_item: Optional[Any] = None
        self._axis_item: Optional[Any] = None
        self._install_reference_items(100.0)

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
        part_color = (
            (0.72, 0.77, 0.82, 0.22)
            if internal_voids is not None
            else (0.72, 0.77, 0.82, 1.0)
        )
        part_options = "translucent" if internal_voids is not None else "opaque"
        self._part_item = self._mesh_item(part, part_color, part_options)
        self.addItem(self._part_item)

        if overhang is not None and len(overhang.faces) > 0:
            self._overhang_item = self._mesh_item(overhang, (0.95, 0.22, 0.18, 0.72), "translucent")
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

        for index, mesh in enumerate(support_meshes):
            color = (
                self._SELECTED_SUPPORT_COLOR
                if index == selected_support_index
                else self._SUPPORT_COLOR
            )
            item = self._mesh_item(mesh, color, "opaque")
            self._support_items.append(item)
            self.addItem(item)

        self._selected_support_index = selected_support_index
        self.setCameraPosition(
            pos=QtGui.QVector3D(0.0, 0.0, size / 2.0),
            distance=max(size * 2.6, 10.0),
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
        self._grid_item.setColor((82, 94, 108, 100))
        self.addItem(self._grid_item)

        self._axis_item = gl.GLAxisItem()
        axis_size = max(model_size * 0.35, 10.0)
        self._axis_item.setSize(x=axis_size, y=axis_size, z=axis_size)
        self.addItem(self._axis_item)

    @staticmethod
    def _mesh_item(mesh: Any, color: Tuple[float, float, float, float], options: str) -> Any:
        mesh_data = gl.MeshData(
            vertexes=np.asarray(mesh.vertices, dtype=np.float32),
            faces=np.asarray(mesh.faces, dtype=np.uint32),
            faceColors=np.tile(np.asarray(color, dtype=np.float32), (len(mesh.faces), 1)),
        )
        return gl.GLMeshItem(
            meshdata=mesh_data,
            smooth=False,
            drawEdges=False,
            glOptions=options,
        )
