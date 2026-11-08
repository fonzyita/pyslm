"""
Block supports built from thin perforated walls, in the style of commercial L-PBF/SLM build-preparation software.

Each support region identified by :class:`~pyslm.support.BlockSupportGenerator` is filled with a grid of vertical walls
along X and Y and, optionally, a wall following the region boundary. Every wall follows the support volume from its
lower surface (build plate or part) to the overhang, has triangular teeth where it touches the part, may be perforated
and fragmented, and is given a real thickness so it can be exported as a solid mesh.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any, List, Optional, Sequence, Tuple

import numpy as np
import shapely
import shapely.geometry
import trimesh

from ..core import Part
from . import utils
from .support import BlockSupportBase, BlockSupportGenerator


@dataclass(frozen=True)
class WallSupportParameters:
    """Parameters of :class:`WallBlockSupport` (all lengths in mm)."""

    hatchSpacing: float = 2.5
    """Distance between neighbouring walls of the X and Y grid"""

    wallThickness: float = 0.3
    """Physical thickness of every wall"""

    useBorder: bool = True
    """Add a wall following the boundary of the support region"""

    useUpperTeeth: bool = True
    """Triangular teeth where the walls touch the overhang"""

    useLowerTeeth: bool = True
    """Triangular teeth where the walls stand on the part (never on the build plate)"""

    teethHeight: float = 0.8
    teethTopLength: float = 0.3
    """Length of the contact of each tooth with the part"""

    teethBaseLength: float = 1.0
    """Length of each tooth where it joins the wall"""

    teethBaseInterval: float = 0.3
    """Gap between the bases of neighbouring teeth"""

    teethPenetration: float = 0.1
    """Distance each tooth extends into the part to make contact"""

    usePerforation: bool = True
    perforationSize: float = 2.0
    """Diagonal of the diamond-shaped perforations"""

    perforationWeb: float = 1.0
    """Material left between neighbouring perforations"""

    perforationMargin: float = 1.0
    """Solid band kept below the teeth and above the base of each wall"""

    fragmentationInterval: float = 0.0
    """Distance between cuts splitting each wall into fragments; 0 disables fragmentation"""

    fragmentationGap: float = 0.4
    """Width of each fragmentation cut"""

    sampleStep: float = 0.2
    """Distance between samples of the support volume along each wall"""

    plateTolerance: float = 0.05
    """Heights at or below this are treated as the build plate"""

    def validate(self) -> None:
        positive = ('hatchSpacing', 'wallThickness', 'teethHeight', 'teethTopLength', 'teethBaseLength',
                    'perforationSize', 'perforationWeb', 'sampleStep')
        for name in positive:
            if getattr(self, name) <= 0:
                raise ValueError(f'{name} must be positive')
        for name in ('teethBaseInterval', 'teethPenetration', 'perforationMargin', 'fragmentationInterval',
                     'fragmentationGap', 'plateTolerance'):
            if getattr(self, name) < 0:
                raise ValueError(f'{name} must not be negative')
        if self.teethTopLength > self.teethBaseLength:
            raise ValueError('The tooth contact length cannot exceed the tooth base length')


@dataclass
class _Wall:
    origin: np.ndarray      # (2,) start point in XY
    direction: np.ndarray   # (2,) unit vector along the wall
    length: float


def _wallTransform(wall: _Wall, thickness: float) -> np.ndarray:
    """Matrix mapping the local wall frame (u along the wall, z up, w through the thickness) to world coordinates."""
    d = np.r_[wall.direction, 0.0]
    n = np.cross(d, [0.0, 0.0, 1.0])  # keeps the frame right-handed so face normals point outwards
    m = np.eye(4)
    m[:3, 0] = d
    m[:3, 1] = [0.0, 0.0, 1.0]
    m[:3, 2] = n
    m[:3, 3] = np.r_[wall.origin, 0.0] - n * thickness / 2.0
    return m


def _strips(u: np.ndarray, intervals: List[np.ndarray]) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Group the per-sample inside intervals into continuous strips ``(u, zLow, zHigh)`` along a wall."""
    finished = []
    active: List[Tuple[List[float], List[float], List[float]]] = []
    for i, ivs in enumerate(intervals):
        claimed = np.zeros(len(ivs), dtype=bool)
        still = []
        for strip in active:
            lo, hi = strip[1][-1], strip[2][-1]
            overlap = np.flatnonzero((ivs[:, 0] < hi) & (ivs[:, 1] > lo)) if len(ivs) else np.empty(0, dtype=int)
            if len(overlap) == 1 and not claimed[overlap[0]]:
                k = overlap[0]
                claimed[k] = True
                strip[0].append(u[i])
                strip[1].append(ivs[k, 0])
                strip[2].append(ivs[k, 1])
                still.append(strip)
            else:
                finished.append(strip)
        for k in np.flatnonzero(~claimed):
            still.append(([u[i]], [ivs[k, 0]], [ivs[k, 1]]))
        active = still
    finished.extend(active)
    return [(np.asarray(s[0]), np.asarray(s[1]), np.asarray(s[2])) for s in finished if len(s[0]) >= 2]


class WallBlockSupport(BlockSupportBase):
    """
    A block support region filled with thin perforated walls with teeth, similar to the block supports of commercial
    SLM build-preparation software. The walls are generated by :meth:`geometry` from the region's
    :attr:`~BlockSupportBase.supportVolume`.
    """

    def __init__(self, supportObject: Optional[Part] = None,
                 supportVolume: Optional[trimesh.Trimesh] = None,
                 supportSurface: Optional[trimesh.Trimesh] = None,
                 intersectsPart: bool = False,
                 parameters: Optional[WallSupportParameters] = None):
        super().__init__(supportObject, supportVolume, supportSurface, intersectsPart)
        self.parameters = parameters if parameters is not None else WallSupportParameters()

    def __str__(self) -> str:
        return 'WallBlockSupport'

    def geometry(self) -> trimesh.Trimesh:
        """Generate the solid mesh of all the support walls in this region."""
        params = self.parameters
        params.validate()
        volume = self._supportVolume
        if volume is None or len(volume.faces) == 0:
            return trimesh.Trimesh()

        start = perf_counter()
        walls = self._gridWalls(volume, params)
        gridCount = len(walls)
        if params.useBorder:
            walls += self._borderWalls(volume, params)

        meshes = self._buildWalls(volume, walls, params)
        mesh = _concatenate(meshes)
        logging.info('Wall support generated %d walls (%d grid, %d border) in %.2fs (%d faces)',
                     len(meshes), gridCount, len(walls) - gridCount, perf_counter() - start, len(mesh.faces))
        return mesh

    @staticmethod
    def _gridWalls(volume: trimesh.Trimesh, params: WallSupportParameters) -> List[_Wall]:
        """Walls along X and Y on a grid aligned to multiples of the hatch spacing, spanning the region."""
        bounds = np.asarray(volume.bounds, dtype=float)
        s = params.hatchSpacing
        walls = []
        x0, x1 = bounds[0, 0] - s, bounds[1, 0] + s
        y0, y1 = bounds[0, 1] - s, bounds[1, 1] + s
        for y in np.arange(np.ceil(y0 / s), np.floor(y1 / s) + 1) * s:
            walls.append(_Wall(np.array([x0, y]), np.array([1.0, 0.0]), x1 - x0))
        for x in np.arange(np.ceil(x0 / s), np.floor(x1 / s) + 1) * s:
            walls.append(_Wall(np.array([x, y0]), np.array([0.0, 1.0]), y1 - y0))
        return walls

    @staticmethod
    def _borderWalls(volume: trimesh.Trimesh, params: WallSupportParameters) -> List[_Wall]:
        """Straight wall panels along the boundary of the region, inset by half the wall thickness."""
        from scipy import ndimage
        import skimage.measure

        bounds = np.asarray(volume.bounds, dtype=float)
        extent = bounds[1, :2] - bounds[0, :2]
        pitch = float(np.clip(params.wallThickness / 3.0, 0.05, 0.2))
        pitch = max(pitch, float(np.sqrt(np.prod(extent + 4 * pitch) / 4e6)))
        origin = bounds[0, :2] - 2.0 * pitch
        shape = np.ceil((extent + 4.0 * pitch) / pitch).astype(int) + 1
        rx = origin[0] + np.arange(shape[0]) * pitch
        ry = origin[1] + np.arange(shape[1]) * pitch
        samples = np.stack(np.meshgrid(rx, ry, indexing='ij'), axis=-1).reshape(-1, 2)

        lines, _ = utils.verticalIntervals(volume, samples)
        inside = np.zeros(len(samples), dtype=bool)
        inside[lines] = True
        distance = ndimage.distance_transform_edt(inside.reshape(shape)) * pitch - 0.5 * pitch
        if distance.max() <= 0:
            return []

        level = min(params.wallThickness / 2.0 + 0.05, 0.5 * float(distance.max()))
        padded = np.pad(distance, 1, mode='constant', constant_values=-pitch)
        walls = []
        for contour in skimage.measure.find_contours(padded, level):
            loop = origin + (contour - 1.0) * pitch
            if len(loop) < 3:
                continue
            line = shapely.geometry.LineString(loop).simplify(max(pitch, 0.1))
            points = np.asarray(line.coords)
            for a, b in zip(points[:-1], points[1:]):
                length = float(np.linalg.norm(b - a))
                if length < 0.5 * params.sampleStep:
                    continue
                walls.append(_Wall(a, (b - a) / length, length))
        return walls

    def _buildWalls(self, volume: trimesh.Trimesh, walls: Sequence[_Wall],
                    params: WallSupportParameters) -> List[trimesh.Trimesh]:
        # Sample every wall and find where each sample line lies inside the support volume, in a single pass
        samplesU = []
        for wall in walls:
            count = max(int(np.ceil(wall.length / params.sampleStep)), 1)
            samplesU.append(np.linspace(0.0, wall.length, count + 1))
        counts = np.array([len(u) for u in samplesU])
        if counts.sum() == 0:
            return []
        xy = np.vstack([wall.origin + u[:, None] * wall.direction for wall, u in zip(walls, samplesU)])
        lines, intervals = utils.verticalIntervals(volume, xy, mergeGap=0.25)
        # Intervals shorter than the strut-scale tolerance come from lines grazing the boundary of the volume
        keep = (intervals[:, 1] - intervals[:, 0]) > 1e-3
        lines, intervals = lines[keep], intervals[keep]
        lineStart = np.searchsorted(lines, np.arange(len(xy)), side='left')
        lineEnd = np.searchsorted(lines, np.arange(len(xy)), side='right')

        meshes = []
        first = 0
        for wall, u in zip(walls, samplesU):
            sampleIntervals = [intervals[lineStart[i]:lineEnd[i]] for i in range(first, first + len(u))]
            first += len(u)
            if not any(len(iv) for iv in sampleIntervals):
                continue
            outline = self._wallOutline(u, sampleIntervals, params)
            if outline is None or outline.is_empty:
                continue
            mesh = self._extrudeWall(outline, wall, params.wallThickness)
            if mesh is not None and len(mesh.faces) > 0:
                meshes.append(mesh)
        return meshes

    def _wallOutline(self, u: np.ndarray, sampleIntervals: List[np.ndarray],
                     params: WallSupportParameters) -> Optional[Any]:
        """The 2D outline of one wall in its own (u, z) plane, with teeth, perforations and fragmentation."""
        bases, cuts = [], []
        for su, lo, hi in _strips(u, sampleIntervals):
            base, stripCuts = self._stripOutline(su, lo, hi, params)
            if base is not None and not base.is_empty:
                bases.append(base)
                cuts += stripCuts
        if not bases:
            return None
        solid = shapely.union_all(bases)

        # Morphological opening removes slivers thinner than ~0.2 mm left where sample lines graze the edge of the
        # support volume; mitred joins keep the corners (and later the teeth) sharp. Mitred offsets can overshoot at
        # acute corners, so the result is clipped back to the original outline.
        e = 0.1
        outline = solid.buffer(-e, join_style=2).buffer(e, join_style=2).intersection(solid)
        if outline.is_empty:
            return None

        if params.fragmentationInterval > 0:
            g = params.fragmentationGap / 2.0
            cuts += [shapely.geometry.box(c - g, -1e3, c + g, 1e3)
                     for c in np.arange(params.fragmentationInterval, u[-1], params.fragmentationInterval)]
        if cuts:
            outline = outline.difference(shapely.union_all(cuts))
        return outline

    @staticmethod
    def _notches(su: np.ndarray, surface: np.ndarray, sign: float, params: WallSupportParameters) -> List[Any]:
        """Cut-outs between the teeth along one edge of a strip.

        ``surface`` is the edge height at each sample (already including the penetration) and ``sign`` is +1 for the
        upper edge (teeth point up) and -1 for the lower edge (teeth point down).
        """
        a, b, h = params.teethTopLength, params.teethBaseLength, params.teethHeight
        period = b + max(params.teethBaseInterval, 1e-3)
        z = lambda x: np.interp(x, su, surface)
        notches = []
        # Teeth are aligned to the wall coordinate, so neighbouring strips share the same pattern
        k0 = np.floor(su[0] / period) - 1
        k1 = np.ceil(su[-1] / period) + 1
        for k in np.arange(k0, k1):
            c0, c1 = k * period + b / 2.0, (k + 1) * period + b / 2.0  # centres of two neighbouring teeth
            tipL, tipR = c0 + a / 2.0, c1 - a / 2.0
            baseL, baseR = c0 + b / 2.0, c1 - b / 2.0
            inner = su[(su > tipL) & (su < tipR)]
            cap = [(x, z(x) + sign * 1.0) for x in np.r_[tipL, inner, tipR]]
            ring = ([(tipL, z(tipL))] + cap + [(tipR, z(tipR)),
                                               (baseR, z(baseR) - sign * h),
                                               (baseL, z(baseL) - sign * h)])
            notch = shapely.geometry.Polygon(ring)
            if not notch.is_valid:
                notch = shapely.make_valid(notch)
            notches.append(notch)
        return notches

    def _stripOutline(self, su: np.ndarray, lo: np.ndarray, hi: np.ndarray,
                      params: WallSupportParameters) -> Tuple[Optional[Any], List[Any]]:
        """Solid outline of one strip (including the tooth penetration) and the cuts to subtract from it."""
        # Extend the strip by half a sample at both ends so neighbouring strips overlap instead of leaving a slit
        half = 0.5 * params.sampleStep
        su = np.r_[su[0] - half, su, su[-1] + half]
        lo = np.r_[lo[0], lo, lo[-1]]
        hi = np.r_[hi[0], hi, hi[-1]]

        p, h = params.teethPenetration, params.teethHeight
        onPart = lo > params.plateTolerance
        lowerTeeth = params.useLowerTeeth and bool(onPart.any())

        top = hi + (p if params.useUpperTeeth else 0.0)
        bottom = np.where(onPart & lowerTeeth, np.maximum(lo - p, 0.0), lo)
        ring = np.vstack([np.column_stack([su, top]), np.column_stack([su[::-1], bottom[::-1]])])
        strip = shapely.geometry.Polygon(ring)
        if not strip.is_valid:
            strip = shapely.make_valid(strip)
        if strip.is_empty:
            return None, []

        cuts = []
        if params.useUpperTeeth:
            cuts += self._notches(su, top, 1.0, params)
        if lowerTeeth:
            # Only notch the lower edge where it stands on the part; on the build plate the wall stays solid
            for notch in self._notches(su, bottom, -1.0, params):
                xs = np.asarray(notch.bounds)[[0, 2]]
                span = (su >= xs[0]) & (su <= xs[1])
                if span.any() and onPart[span].all():
                    cuts.append(notch)

        if params.usePerforation:
            cuts += self._perforations(su, lo, hi, params)
        return strip, cuts

    @staticmethod
    def _perforations(su: np.ndarray, lo: np.ndarray, hi: np.ndarray, params: WallSupportParameters) -> List[Any]:
        """Diamond perforations kept clear of the teeth and of the base of the strip."""
        h, m, d = params.teethHeight, params.perforationMargin, params.perforationSize
        upper = hi - (h if params.useUpperTeeth else 0.0) - m
        lowerTeeth = params.useLowerTeeth & (lo > params.plateTolerance)
        lower = lo + np.where(lowerTeeth, h, 0.0) + m
        if not np.any(upper - lower > d):
            return []

        pitch = d + params.perforationWeb
        r = d / 2.0
        # Diamond tiling: rows half a pitch apart, alternate rows shifted by half a pitch
        rows = np.arange(np.floor(lower.min() / (pitch / 2.0)), np.ceil(upper.max() / (pitch / 2.0)) + 1)
        cols = np.arange(np.floor(su[0] / pitch) - 1, np.ceil(su[-1] / pitch) + 2)
        x = cols[None, :] * pitch + (rows[:, None] % 2) * pitch / 2.0
        zc = np.broadcast_to(rows[:, None] * pitch / 2.0, x.shape)
        x, zc = x.ravel(), zc.ravel()
        # Keep half a web of material between the holes and the ends of the strip
        endMargin = 0.5 * params.perforationWeb
        inside = (x - r >= su[0] + endMargin) & (x + r <= su[-1] - endMargin)
        x, zc = x[inside], zc[inside]
        if len(x) == 0:
            return []
        # A hole fits when the allowed band covers it at its left corner, centre and right corner
        probes = np.stack([x - r, x, x + r], axis=1)
        fits = ((zc + r <= np.interp(probes, su, upper).min(axis=1))
                & (zc - r >= np.interp(probes, su, lower).max(axis=1)))
        x, zc = x[fits], zc[fits]
        return list(shapely.polygons(np.stack([np.column_stack([x - r, zc]), np.column_stack([x, zc + r]),
                                               np.column_stack([x + r, zc]), np.column_stack([x, zc - r])], axis=1)))

    @staticmethod
    def _extrudeWall(outline: Any, wall: _Wall, thickness: float) -> Optional[trimesh.Trimesh]:
        # Snapping to a 0.1 um grid removes duplicate and nearly coincident vertices left by the Boolean operations,
        # which would otherwise produce non-manifold edges in the extruded wall
        outline = shapely.set_precision(outline, 1e-4)
        polygons = [_sanitizePolygon(g) for g in getattr(outline, 'geoms', [outline])
                    if isinstance(g, shapely.geometry.Polygon)]
        meshes = []
        engine = _triangulationEngine()
        for polygon in polygons:
            if polygon.is_empty or polygon.area < 1e-6:
                continue
            try:
                meshes.append(trimesh.creation.extrude_polygon(polygon, thickness, engine=engine))
            except Exception:
                logging.debug('Could not triangulate a support wall polygon', exc_info=True)
        if not meshes:
            return None
        mesh = _concatenate(meshes)
        mesh.apply_transform(_wallTransform(wall, thickness))
        return mesh


def _sanitizePolygon(polygon: shapely.geometry.Polygon, tolerance: float = 1e-3) -> shapely.geometry.Polygon:
    """Fill holes that touch the outer boundary or another hole.

    Such polygons are valid, but the ``triangle`` library crashes the whole process (access violation) on them.
    """
    if polygon.is_empty or not polygon.interiors:
        return polygon
    exterior = polygon.exterior
    holes = np.array([shapely.geometry.Polygon(ring) for ring in polygon.interiors], dtype=object)
    keep = shapely.distance(shapely.get_exterior_ring(holes), exterior) > tolerance
    # Of every pair of holes closer than the tolerance, fill the later one
    tree = shapely.STRtree(holes)
    near = tree.query(shapely.buffer(holes, tolerance, quad_segs=1), predicate='intersects')
    later = near[1][near[1] > near[0]]
    keep[later] = False
    if keep.all():
        return polygon
    return shapely.geometry.Polygon(exterior, [h.exterior for h in holes[keep]])


def _triangulationEngine() -> str:
    """Prefer the robust ``triangle`` backend; earcut can mis-triangulate perforated walls (non-closed meshes)."""
    try:
        import triangle
        return 'triangle'
    except ImportError:
        return 'earcut'


def _concatenate(meshes: Sequence[trimesh.Trimesh]) -> trimesh.Trimesh:
    meshes = [m for m in meshes if m is not None and len(m.faces) > 0]
    if not meshes:
        return trimesh.Trimesh()
    offsets = np.cumsum([0] + [len(m.vertices) for m in meshes[:-1]])
    vertices = np.vstack([m.vertices for m in meshes])
    faces = np.vstack([m.faces + o for m, o in zip(meshes, offsets)])
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


class WallBlockSupportGenerator(BlockSupportGenerator):
    """Identifies block support regions and returns them as :class:`WallBlockSupport` regions."""

    def __init__(self, parameters: Optional[WallSupportParameters] = None) -> None:
        super().__init__()
        self.parameters = parameters if parameters is not None else WallSupportParameters()

    def __str__(self) -> str:
        return 'WallBlockSupportGenerator'

    def identifySupportRegions(self, part: Part, overhangAngle: float,
                               findSelfIntersectingSupport: bool = True) -> List[WallBlockSupport]:
        blocks = super().identifySupportRegions(part, overhangAngle, findSelfIntersectingSupport)
        return [WallBlockSupport(block.supportObject, block.supportVolume, block.supportSurface,
                                 block.intersectsPart, replace(self.parameters))
                for block in blocks]
