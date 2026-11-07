import logging

import numpy as np
import trimesh

try:
    from vispy import app, gloo
    from vispy.util.transforms import translate, rotate, ortho
except Exception:  # pragma: no cover - optional dependency
    app = None
    gloo = None
    translate = rotate = ortho = None

import matplotlib.pyplot as plt
#app.use_app('pyside6')  # Set backend

vert = """

uniform   mat4 u_model;
uniform   mat4 u_view;
uniform   mat4 u_projection;

attribute vec3 a_position;
attribute vec3 a_color;

varying vec4 v_color;

void main()
{
    v_color = vec4(a_color, 1.0);
    gl_Position = u_projection * u_view * u_model * vec4(a_position,1.0);
}
"""

frag = """
varying vec4 v_color;

void main()
{
    //gl_FragColor = vec4( (gl_FragCoord.z / 1e5)+0.,(gl_FragCoord.z / 1e5)+0.,(gl_FragCoord.z / 1e5)+0.5,1.0);
    gl_FragColor = vec4( v_color.z,v_color.z,v_color.z,1.0);
}
"""


if app is not None:
    class Canvas(app.Canvas):
        @property
        def resolution(self):
            return self._resolution

        @resolution.setter
        def resolution(self, res: float):
            self._resolution = res

        @property
        def visSize(self):
            return self._visSize

        @property
        def mesh(self) -> trimesh.Trimesh:
            return self._mesh

        @property
        def bbox(self) -> np.ndarray:
            return self._bbox

        def setMesh(self, mesh: trimesh.Trimesh):
            self.vertices = np.copy(mesh.vertices).astype(np.float32)
            self.filled = np.copy(mesh.faces).astype(np.int32)
            self.verticesColor = np.copy(mesh.vertices).astype(np.float32)

            self._bbox = mesh.bounds
            self._mesh = mesh

        def __enter__(self):
            self._backend._vispy_warmup()
            return self

        def __init__(self, mesh: trimesh.Trimesh = None, rasterResolution: float = 0.05, flipDir=False, bbox=None):
            self.flipDir = flipDir
            self.rgb = None
            self.vertices = None
            self.filled = None
            self.verticesColor = None
            self._resolution = rasterResolution
            self._mesh = None
            self._bbox = None

            if mesh is not None:
                self.setMesh(mesh)

            if bbox is not None:
                self._bbox = np.asarray(bbox, dtype=float)

            if not np.isfinite(self.resolution) or self.resolution <= 0:
                raise ValueError("Height-map resolution must be a positive finite number.")
            if self._bbox is None or self._bbox.shape != (2, 3):
                raise ValueError("Height-map bounds must have shape (2, 3).")

            meshExtents = np.diff(self.bbox, axis=0)[0]
            if (
                not np.all(np.isfinite(self.bbox))
                or np.any(meshExtents[:2] <= 0)
                or np.any(meshExtents < 0)
            ):
                raise ValueError("Height-map bounds must have finite, non-zero X/Y extents.")

            self._visSize = np.maximum(
                np.ceil(meshExtents[:2] / self.resolution).astype(int), 1
            )

            app.Canvas.__init__(self, 'interactive', show=False, resizable=True, autoswap=False, decorate=False,
                                size=(int(self.visSize[0]), int(self.visSize[1])))

            self.filled = self.filled.astype(np.uint32).flatten()
            self.filled_buf = gloo.IndexBuffer(self.filled)

            vertex_data = np.zeros(self.vertices.shape[0], dtype=[('a_position', np.float32, 3),
                                                                  ('a_color', np.float32, 3)])

            vertex_data['a_position'] = self.vertices.astype(np.float32)
            vertex_data['a_color'] = self.vertices.astype(np.float32)

            self.program = gloo.Program(vert, frag)
            self.program.bind(gloo.VertexBuffer(vertex_data))

            avg = np.mean(self.bbox, axis=0)

            if flipDir:
                self.view = rotate(0, [1, 0, 0])
            else:
                self.view = np.dot(np.dot(translate((-avg[0], -avg[1], -avg[2])),
                                  rotate(-180, [1, 0, 0])),
                                  translate((avg[0], avg[1], avg[2])))

            self.model = np.eye(4, dtype=np.float32)
            shape = int(self._visSize[1]), int(self._visSize[0])

            self._rendertex = gloo.Texture2D((shape + (4,)), format='rgba', internalformat='rgba32f')
            self._depthRenderBuffer = gloo.RenderBuffer(shape, format='depth')
            self._fbo = gloo.FrameBuffer(self._rendertex, self._depthRenderBuffer)

            gloo.set_viewport(0, 0, self.physical_size[0], self.physical_size[1])
            gloo.set_viewport(0, 0, self._visSize[0], self._visSize[1])
            self._update_projection()
            self.program['u_model'] = self.model
            self.program['u_view'] = self.view

            gloo.set_clear_color((0.0, 0.0, 0.0, 0.0))
            gloo.set_state('opaque')

            self.update()

        def _update_projection(self):
            depth = max(float(np.max(np.diff(self.bbox, axis=0))), 1.0) * 2.0
            self.projection = ortho(
                self.bbox[0, 0],
                self.bbox[1, 0],
                self.bbox[0, 1],
                self.bbox[1, 1],
                -depth,
                depth,
            )
            self.program['u_projection'] = self.projection

        def on_resize(self, event):
            gloo.set_viewport(0, 0, self._visSize[0] * 2, self._visSize[1] * 2)
            self.finalSize = (event.physical_size[0], event.physical_size[1])
            self._update_projection()

        def on_draw(self, event):
            with self._fbo:
                gloo.clear()
                gloo.set_clear_color((0.0, 0.0, 0.0, 0.0))
                gloo.set_viewport(0, 0, *self.finalSize)
                gloo.set_viewport(0, 0, self._visSize[0], self._visSize[1])
                gloo.set_state(blend=True, depth_test=True, polygon_offset_fill=False, cull_face=False)
                self.program.draw('triangles', self.filled_buf)
                self.rgb = gloo.read_pixels((0, 0, self._visSize[0], self._visSize[1]), True, out_type='float')
else:
    class Canvas:
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "PySLM height-map rendering requires the optional 'vispy' package. "
                "Install it with: pip install vispy"
            )


def projectHeightMap(mesh: trimesh.Trimesh,
                     resolution: float = 0.05,
                     flipDir: bool = False,
                     bbox: np.ndarray = None) -> np.ndarray:

    if not np.isfinite(resolution) or resolution <= 0:
        raise ValueError("Height-map resolution must be a positive finite number.")

    if bbox is None:
        if mesh is None or len(mesh.vertices) == 0:
            raise ValueError("Bounds are required to map an empty mesh.")
        bbox = mesh.bounds
    else:
        bbox = np.asarray(bbox, dtype=float)

    extents = np.diff(bbox, axis=0)[0] if bbox.shape == (2, 3) else None
    if (
        extents is None
        or not np.all(np.isfinite(bbox))
        or np.any(extents[:2] <= 0)
        or np.any(extents < 0)
    ):
        raise ValueError("Height-map bounds must have finite, non-zero X/Y extents.")

    image_size = np.maximum(np.ceil(extents[:2] / resolution).astype(int), 1)
    if mesh is None or len(mesh.faces) == 0:
        return np.zeros((image_size[1], image_size[0]), dtype=np.float32)

    c = None
    render_error = None

    try:
        c = Canvas(mesh, resolution, flipDir, bbox)
        c.show(visible=True)
        c.update()
        app.process_events()
    except Exception as exc:
        render_error = exc
        logging.warning("OpenGL height-map rendering failed; trying CPU ray tracing: %s", exc)
    finally:
        if c is not None:
            try:
                c.close()
            except Exception as exc:
                if render_error is None:
                    render_error = exc
                logging.warning("Could not close the OpenGL height-map canvas: %s", exc)

    if c is None or c.rgb is None:
        logging.warning("OpenGL returned no height map; trying CPU ray tracing.")
        try:
            return _projectHeightMapRay(mesh, resolution, flipDir, bbox)
        except Exception as exc:
            message = (
                "PySLM could not render the support height map with OpenGL, and "
                "CPU ray tracing also failed. Check the OpenGL context and install "
                "the optional 'rtree' package for CPU fallback."
            )
            if render_error is not None:
                message += " OpenGL error: {}".format(render_error)
            raise RuntimeError(message) from exc
    return c.rgb[:, :, 1]


def _projectHeightMapRay(
    mesh: trimesh.Trimesh,
    resolution: float,
    flipDir: bool,
    bbox: np.ndarray,
) -> np.ndarray:
    """Rasterize the nearest mesh surface along vertical rays without OpenGL."""
    extents = np.diff(bbox, axis=0)[0]
    image_size = np.maximum(np.ceil(extents[:2] / resolution).astype(int), 1)
    width, height = image_size
    pixel_size = extents[:2] / image_size
    direction_z = -1.0 if flipDir else 1.0
    initial_z = bbox[1, 2] if flipDir else bbox[0, 2]
    combine = np.maximum.at if flipDir else np.minimum.at
    pad = max(float(np.max(extents)), 1.0)
    result = np.zeros(width * height, dtype=np.float32)
    for start in range(0, len(result), 100_000):
        end = min(start + 100_000, len(result))
        ray_indices = np.arange(start, end)
        rows, columns = np.divmod(ray_indices, width)
        x_coords = bbox[0, 0] + (columns + 0.5) * pixel_size[0]
        y_offsets = (rows + 0.5) * pixel_size[1]
        y_coords = bbox[1, 1] - y_offsets if flipDir else bbox[0, 1] + y_offsets
        origins = np.column_stack(
            (
                x_coords,
                y_coords,
                np.full(len(ray_indices), initial_z - direction_z * pad),
            )
        )
        directions = np.zeros_like(origins)
        directions[:, 2] = direction_z
        locations, local_ray_indices, _ = mesh.ray.intersects_location(
            ray_origins=origins,
            ray_directions=directions,
            multiple_hits=True,
        )
        if len(local_ray_indices):
            batch_result = np.full(
                len(ray_indices), -np.inf if flipDir else np.inf, dtype=np.float32
            )
            hit_mask = np.zeros(len(ray_indices), dtype=bool)
            hit_mask[local_ray_indices] = True
            combine(
                batch_result,
                local_ray_indices,
                locations[:, 2].astype(np.float32),
            )
            batch_result[~hit_mask] = 0.0
            result[start:end] = batch_result
    return result.reshape((height, width))
