import logging
from typing import Iterable, Iterator, List, Optional, Tuple, Union

import networkx as nx

import numpy as np
import trimesh

from . import geometry
from ..core import Part

def getAdjacentFaces(mesh: trimesh.Trimesh):
    """
    Returns a list of connected faces
    :param mesh: A Trimesh mesh for locating the connected faces

    :return: Returns a list of connectivity for each face
    """
    graph = nx.Graph()
    graph.add_edges_from(mesh.face_adjacency)

    adjacentFaces = {node: list(graph.neighbors(node)) for node in graph.nodes}
    return adjacentFaces


def getSupportAngles(part: Part,
                     unitNormal: Optional[np.ndarray] = None,
                     useConnectivity: Optional[bool] = True) -> np.ndarray:
    """
    Returns the support angles for each triangular face normal. This is mainly used for the benefit of visualising the
    support angles for a part.

    :param part: The :class:`Part` to calculate the support or overhang angles
    :param unitNormal: The up-vector direction used to calculate the angle against
    :param useConnectivity: Use face connectivity to get the interpolated support angle
    :return: The support angles across the whole part geometry
    """

    # Upward vector for support angles
    v0 = np.array([[0., 0., -1.0]]) if unitNormal is None else np.asanyarray(unitNormal)

    # Identify Support Angles
    v1 = part.geometry.face_normals
    theta = np.arccos(np.clip(np.dot(v0, v1.T), -1.0, 1.0))
    theta = np.degrees(theta).flatten()

    if useConnectivity:
        thetaAvg = theta.copy()
        adjacencyList = getAdjacentFaces(part.geometry)
        for face in adjacencyList.keys():
            conFaces = [face] + adjacencyList[face]
            thetaAvg[face] = np.mean(theta[conFaces])

        return thetaAvg
    else:
        return theta


def getFaceZProjectionWeight(mesh: trimesh.Trimesh,
                             useConnectivity: bool = False) -> np.ndarray:
    """
    Utility which returns the inverse projection of the faces relative to the +ve Z direction in order to isolate side
    faces. This could be considered the inverse component of the overhang angle. It is calculated by using the
    following trigonometric identify :math:`\\sin(\\theta) = \\sqrt{1-\\cos^2(\\theta)`.

    :param mesh: The mesh to identify the projection weights
    :param useConnectivity: Uses mesh connectivity to interpolate the surface normals across
    """

    v0 = np.array([[0., 0., 1.0]])
    v1 = mesh.face_normals

    sin_theta = np.sqrt((1 - np.dot(v0, v1.T) ** 2)).reshape(-1)

    if useConnectivity:
        sinThetaAvg = sin_theta.copy()
        adjacencyList = getAdjacentFaces(mesh)
        for face in adjacencyList.keys():
            conFaces = [face] + adjacencyList[face]
            sinThetaAvg[face] = np.mean(sinThetaAvg[conFaces])
        return sinThetaAvg
    else:
        return sin_theta


def getOverhangMesh(part: Part,
                    overhangAngle: float,
                    splitMesh: bool = False,
                    useConnectivity: bool = False) -> Union[trimesh.Trimesh, List[trimesh.Trimesh]]:
    """
    Gets the overhang mesh from a :class:`Part`. If the individual regions for the overhang mesh require separating,
    the parameter :code:`splitMesh` should be set to `True`. This will split mesh regions by their facial connectivity
    using Trimesh.

    :param part: The part to extract the overhang mesh from
    :param overhangAngle: The overhang angle in degrees
    :param splitMesh: If the overhang mesh should be split into separate Trimesh entities by network connectivity
    :param useConnectivity: Uses mesh connectivity to interpolate the surface normals across
    :return: The extracted overhang mesh
    """

    # Upward vector for support angles
    v0 = np.array([[0., 0., 1.0]])

    theta = getSupportAngles(part, unitNormal=v0, useConnectivity=useConnectivity)

    supportFaceIds = np.argwhere(theta > 180.0 - overhangAngle).flatten()

    overhangMesh = trimesh.Trimesh(vertices=part.geometry.vertices,
                                   faces=part.geometry.faces[supportFaceIds])

    if splitMesh:
        return overhangMesh.split(only_watertight=False)
    else:
        return overhangMesh


def approximateSupportMomentArea(part: Part, overhangAngle: float) -> float:
    """
    The support moment area is a metric, which projects the distance from the baseplate (:math:`z=0`) for
    each support surface multiplied by the area. It gives a two parameter component cost function for the support area.

    .. note::
        This is an approximation that does not account for any self-intersections. It does not use ray queries to
        project the distance towards the mesh, therefore is more useful estimating the overall cost of the support
        structures, during initial support optimisation.

    :param part: The part to analyse
    :param overhangAngle: The overhang angle in degrees

    :return: The approximate cost function
    """
    overhangMesh = getOverhangMesh(part, overhangAngle, splitMesh=False)

    zHeights = overhangMesh.triangles_center[:, 2]

    # Use the projected area by flattening the support faces
    overhangMesh.vertices[:, 2] = 0.0
    faceAreas = overhangMesh.area_faces

    return float(np.sum(faceAreas * zHeights))


def getApproximateSupportArea(part: Part, overhangAngle: float, projected: bool = False) -> float:
    """
    The support area is a metric of the total area of support surfaces, including the flattened or projected area.

    .. note::
        This is an approximation that does not account for any self-intersections. It does not use ray queries to
        project the distance towards the mesh, therefore is more useful estimating the overall cost of the support
        structures, during initial support optimisation.

    :param part: The part to analyse
    :param overhangAngle: The overhang angle in degrees
    :param projected: If True, the projected area is used
    :return: The approximate cost function
    """
    overhangMesh = getOverhangMesh(part, overhangAngle)

    zHeights = overhangMesh.triangles_center[:,2]

    # Use the projected area by flattening the support faces
    if projected:
        overhangMesh.vertices[:, 2] = 0.0

    faceAreas = overhangMesh.area_faces

    return faceAreas


def approximateSupportMapByCentroid(part: Part, overhangAngle: float,
                                    includeTriangleVertices: bool = False) -> Tuple[np.ndarray]:
    """
    This method to approximate the surface area, projects  a single ray :math:`(0,0,-1)`, form each triangle in the
    overhang mesh -originating from the centroid or optionally each triangle vertex by setting the
    :code:`includeTriangleVertices` parameter. A self-intersection test with the mesh is performed  and this is used to
    calculate the distance from the hit location or if no intersection is made the baseplate (:math:`z=0.0`),
    which may be used later to generate a support heightmap.

    :param part: The :class:`Part` to analyse
    :param overhangAngle: The desired overhang angle in degrees
    :param includeTriangleVertices: Optional parameter projects also from the triangular vertices
    :return: A tuple with the support map
    """

    overhangMesh = getOverhangMesh(part, overhangAngle)

    coords = overhangMesh.triangles_center

    if includeTriangleVertices:
        coords = np.vstack([coords, overhangMesh.vertices])

    ray_dir = np.tile(np.array([[0., 0., -1.0]]), (coords.shape[0], 1))

    # Find the first intersection hit of rays project from the triangle.
    hitLoc, index_ray, _ = part.geometry.ray.intersects_location(ray_origins=coords,
                                                                         ray_directions=ray_dir,
                                                                         multiple_hits=False)

    heightMap = np.zeros((coords.shape[0], 1), dtype=np.float32)
    heightMap[index_ray] = hitLoc[:, 2].reshape(-1, 1)

    heightMap = np.abs(heightMap - coords[:, 2])

    return heightMap


def approximateProjectionSupportCost(part: Part, overhangAngle: float,
                                     includeTriangleVertices: bool = False) -> float:
    """
    Provides a support structure cost using ray projection from the overhang regions which allows for self-intersection
    checks.

    :param part: The part to determine the overall approximate support cost
    :param overhangAngle: The overhang angle in degree
    :param includeTriangleVertices: Optional parameter projects also from the triangular vertices
    :return: The cost function for support generation
    """

    overhangMesh = getOverhangMesh(part, overhangAngle)

    heightMap = approximateSupportMapByCentroid(part, overhangAngle, includeTriangleVertices)

    # Project the overhang area
    overhangMesh.vertices[:, 2] = 0.0
    faceAreas = overhangMesh.area_faces

    return np.sum(faceAreas * heightMap), heightMap


def generateHeightMap(mesh: trimesh.Trimesh,
                      upVec: Iterable = (0.0, 0.0, 1.0),
                      resolution: float = 0.5,
                      offsetPoly: Optional[trimesh.path.Path2D] = None) -> Tuple[np.ndarray]:
    """
    Generates the height map of the upper and lower depths. This is done by projecting rays at a resolution
    (attr:`~BlockSupportGenerator.rayProjectionResolution`) across the entire polygon region (offsetPoly) in both
    vertical directions (+z, -z) and are intersected with the upper and lower support surface. A sequence of
    height maps are generated from these ray intersections.

    :param mesh: The upper surface (typically overhang surface region)
    :param upVec: The projection vector (default is pointing vertically in the +Z direction)
    :param resolution: The resolution of the height map to generate
    :param offsetPoly: The polygon region defining the support region
    :return: A tuple containing various height maps
    """

    if not offsetPoly:
        # Generate a polygon covering the part's bounding box
        offsetPoly = trimesh.load_path(geometry.generatePolygonBoundingBox(mesh.bounds.reshape(2, 3)))

    # Rasterise the surface of overhang to generate projection points
    supportArea = np.array(offsetPoly.rasterize(resolution, offsetPoly.bounds[0, :])).T

    coords = np.argwhere(supportArea).astype(np.float32) * resolution
    coords += offsetPoly.bounds[0, :] + 1e-5  # An offset is required due to rounding error

    logging.info('\t - start projecting rays')
    logging.info('\t - number of rays with resolution ({:.3f}): {:d}'.format(resolution, len(coords)))

    """
    Project upwards to intersect with the upper surface
    """
    # Set the z-coordinates for the ray origin
    coords = np.insert(coords, 2, values=-1e5, axis=1)
    rays = np.repeat([upVec], coords.shape[0], axis=0)

    # Find the first location of any triangles which intersect with the part
    hitLoc, _, _ = mesh.ray.intersects_location(ray_origins=coords,
                                                                ray_directions=rays,
                                                                multiple_hits=False)
    logging.info('\t - finished projecting rays')

    # Create a height map of the projection rays
    heightMap = np.ones(supportArea.shape) * -1.0

    if len(hitLoc) > 0:
        hitLocCpy = hitLoc.copy()
        hitLocCpy[:, :2] -= offsetPoly.bounds[0, :]
        hitLocCpy[:, :2] /= resolution

        hitLocIdx = np.ceil(hitLocCpy[:, :2]).astype(np.int32)

        # Assign the heights
        heightMap[hitLocIdx[:, 0], hitLocIdx[:, 1]] = hitLoc[:, 2]

    return heightMap


def generateHeightMap2(mesh: trimesh.Trimesh,
                       upVec: Iterable = (0.0, 0.0, 1.0),
                       resolution: float = 0.5,
                       offsetPoly: Optional[trimesh.path.Path2D] = None) -> Tuple[np.ndarray]:
    """
    Generates the height map of the upper and lower depths. This is done by projecting rays at a resolution
    (attr:`~BlockSupportGenerator.rayProjectionResolution`) across the entire polygon region (offsetPoly) in both
    vertical directions (+z, -z) and are intersected with the upper and lower support surface. A sequence of
    height maps are generated from these ray intersections.

    :param mesh: The upper surface (typically overhang surface region)
    :param upVec: The projection vector (default is pointing vertically in the +Z direction)
    :param resolution: The resolution of the height map to generate
    :param offsetPoly: The polygon region defining the support region
    :return: A tuple containing various height maps
    """

    if not offsetPoly:
        # Generate a polygon covering the part's bounding box
        offsetPoly = trimesh.load_path(geometry.generatePolygonBoundingBox(mesh.bounds.reshape(2, 3)))

    # Rasterise the surface of overhang to generate projection points
    supportArea = np.array(offsetPoly.rasterize(resolution, offsetPoly.bounds[0, :])).T

    coords = np.argwhere(supportArea).astype(np.float32) * resolution
    coords += offsetPoly.bounds[0, :] + 1e-5  # An offset is required due to rounding error

    logging.info('\t - start projecting rays')
    logging.info('\t - number of rays with resolution ({:.3f}): {:d}'.format(resolution, len(coords)))

    """
    Project upwards to intersect with the upper surface
    """
    # Set the z-coordinates for the ray origin
    coords = np.insert(coords, 2, values=-1e5, axis=1)
    rays = np.repeat([upVec], coords.shape[0], axis=0)

    # Find the first location of any triangles which intersect with the part
    hitLoc, _, _ = mesh.ray.intersects_location(ray_origins=coords,
                                                                ray_directions=rays,
                                                                multiple_hits=False)
    logging.info('\t - finished projecting rays')

    # Create a height map of the projection rays
    heightMap = np.ones(supportArea.shape) * -1.0

    if len(hitLoc) > 0:
        hitLocCpy = hitLoc.copy()
        hitLocCpy[:, :2] -= offsetPoly.bounds[0, :]
        hitLocCpy[:, :2] /= resolution

        hitLocIdx = np.ceil(hitLocCpy[:, :2]).astype(np.int32)

        # Assign the heights
        heightMap[hitLocIdx[:, 0], hitLocIdx[:, 1]] = hitLoc[:, 2]

    return heightMap



def _expandRanges(starts: np.ndarray, lengths: np.ndarray) -> np.ndarray:
    """Concatenate ``arange(s, s + n)`` for every ``(s, n)`` pair without a Python loop."""
    lengths = np.asarray(lengths, dtype=np.int64)
    total = int(lengths.sum())
    if total == 0:
        return np.empty(0, dtype=np.int64)
    offsets = np.cumsum(lengths) - lengths
    return np.repeat(np.asarray(starts, dtype=np.int64) - offsets, lengths) + np.arange(total, dtype=np.int64)


def _iterVerticalHits(mesh: trimesh.Trimesh, xy: np.ndarray,
                      maxPairs: int = 4_000_000) -> Iterator[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """
    Intersect vertical lines through the given XY positions with a mesh, in vectorised batches.

    Triangles with no projected area in the XY plane - vertical walls and degenerate triangles - never produce a
    crossing. Candidate triangle/line pairs are found with a uniform 2D bin grid; for every strip of bins the Y range
    of a triangle is clipped to the strip, so long thin triangles do not test every line in their bounding box.

    :param mesh: The mesh to intersect
    :param xy: The (n, 2) line positions
    :param maxPairs: Upper bound on candidate triangle/line pairs evaluated per batch, to cap memory use
    :return: Batches of ``(lineIndex, z, sign)``, where ``sign`` is +1 for faces whose projection is counter-clockwise
    """
    xy = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
    if len(xy) == 0 or mesh is None or len(mesh.faces) == 0:
        return

    tris = np.asarray(mesh.triangles, dtype=np.float64)
    scale = float(max(np.max(np.ptp(tris[:, :, :2].reshape(-1, 2), axis=0)),
                      np.max(np.ptp(xy, axis=0)), np.max(np.ptp(tris[:, :, 2])))) or 1.0

    # Twice the signed XY area; its sign encodes whether the face points up or down
    det = ((tris[:, 1, 0] - tris[:, 0, 0]) * (tris[:, 2, 1] - tris[:, 0, 1])
           - (tris[:, 2, 0] - tris[:, 0, 0]) * (tris[:, 1, 1] - tris[:, 0, 1]))
    keep = np.abs(det) > (1e-12 * scale * scale)
    tris, det = tris[keep], det[keep]
    if len(tris) == 0:
        return

    # Offset the lines by a tiny irrational amount so a line never passes exactly through a shared triangle edge or
    # vertex, where it could otherwise be counted twice or not at all.
    q = xy + np.array([np.sqrt(2.0), np.sqrt(3.0)]) * (1e-7 * scale)

    txy = tris[:, :, :2]
    lo = np.minimum(q.min(axis=0), txy.min(axis=(0, 1)))
    hi = np.maximum(q.max(axis=0), txy.max(axis=(0, 1)))
    span = np.maximum(hi - lo, 1e-9)
    nBins = int(np.clip(np.sqrt(len(q)), 1, 1024))
    binSize = span / nBins

    pbx = np.clip(((q[:, 0] - lo[0]) / binSize[0]).astype(np.int64), 0, nBins - 1)
    pby = np.clip(((q[:, 1] - lo[1]) / binSize[1]).astype(np.int64), 0, nBins - 1)
    pointBin = pbx * nBins + pby
    order = np.argsort(pointBin, kind='stable')
    binCounts = np.bincount(pointBin, minlength=nBins * nBins)
    binStarts = np.concatenate(([0], np.cumsum(binCounts)))

    tx0 = np.clip(((txy[:, :, 0].min(axis=1) - lo[0]) / binSize[0]).astype(np.int64), 0, nBins - 1)
    tx1 = np.clip(((txy[:, :, 0].max(axis=1) - lo[0]) / binSize[0]).astype(np.int64), 0, nBins - 1)
    rowsPerTri = tx1 - tx0 + 1

    # Process the triangles in chunks so that the (triangle, bin column) pairs stay bounded in memory
    rowChunk = max(maxPairs // 4, 1)
    rowCumulative = np.cumsum(rowsPerTri)
    triStart = 0
    while triStart < len(tris):
        done = rowCumulative[triStart - 1] if triStart > 0 else 0
        triEnd = max(int(np.searchsorted(rowCumulative, done + rowChunk, side='right')), triStart + 1)
        chunk = np.arange(triStart, triEnd)
        triStart = triEnd

        # Each (triangle, bin column) pair covers one contiguous run of the sorted lines. The Y range of the run is
        # the extent of the triangle clipped to that column strip, rather than the triangle's bounding box.
        pairTri = np.repeat(chunk, rowsPerTri[chunk])
        pairRow = _expandRanges(tx0[chunk], rowsPerTri[chunk])
        # Widen each strip slightly so rounding in the bin assignment never drops a line on a strip boundary
        stripLo = lo[0] + pairRow * binSize[0] - 1e-9 * scale
        stripHi = stripLo + binSize[0] + 2e-9 * scale

        yMin = np.full(len(pairTri), np.inf)
        yMax = np.full(len(pairTri), -np.inf)
        for i, j in ((0, 1), (1, 2), (2, 0)):
            p0, p1 = txy[pairTri, i], txy[pairTri, j]
            ex0 = np.maximum(np.minimum(p0[:, 0], p1[:, 0]), stripLo)
            ex1 = np.minimum(np.maximum(p0[:, 0], p1[:, 0]), stripHi)
            valid = ex0 <= ex1
            dx = p1[:, 0] - p0[:, 0]
            flat = np.abs(dx) < 1e-15
            slope = np.where(flat, 0.0, (p1[:, 1] - p0[:, 1]) / np.where(flat, 1.0, dx))
            ya = np.where(flat, p0[:, 1], p0[:, 1] + (ex0 - p0[:, 0]) * slope)
            yb = np.where(flat, p1[:, 1], p0[:, 1] + (ex1 - p0[:, 0]) * slope)
            yMin = np.where(valid, np.minimum(yMin, np.minimum(ya, yb)), yMin)
            yMax = np.where(valid, np.maximum(yMax, np.maximum(ya, yb)), yMax)

        found = np.isfinite(yMin)
        pairTri, pairRow = pairTri[found], pairRow[found]
        ty0 = np.clip(((yMin[found] - 1e-9 * scale - lo[1]) / binSize[1]).astype(np.int64), 0, nBins - 1)
        ty1 = np.clip(((yMax[found] + 1e-9 * scale - lo[1]) / binSize[1]).astype(np.int64), 0, nBins - 1)
        runStart = binStarts[pairRow * nBins + ty0]
        runLen = binStarts[pairRow * nBins + ty1 + 1] - runStart

        cumulative = np.cumsum(runLen)
        batchStart = 0
        while batchStart < len(runLen):
            done = cumulative[batchStart - 1] if batchStart > 0 else 0
            batchEnd = max(int(np.searchsorted(cumulative, done + maxPairs, side='right')), batchStart + 1)
            sl = slice(batchStart, batchEnd)
            batchStart = batchEnd

            lengths = runLen[sl]
            if lengths.sum() == 0:
                continue
            t = np.repeat(pairTri[sl], lengths)
            p = order[_expandRanges(runStart[sl], lengths)]

            a, b, c = tris[t, 0], tris[t, 1], tris[t, 2]
            qx, qy = q[p, 0], q[p, 1]
            w0 = (b[:, 0] - qx) * (c[:, 1] - qy) - (c[:, 0] - qx) * (b[:, 1] - qy)
            w1 = (c[:, 0] - qx) * (a[:, 1] - qy) - (a[:, 0] - qx) * (c[:, 1] - qy)
            w2 = (a[:, 0] - qx) * (b[:, 1] - qy) - (b[:, 0] - qx) * (a[:, 1] - qy)
            d = det[t]
            hit = np.where(d > 0,
                           (w0 >= 0) & (w1 >= 0) & (w2 >= 0),
                           (w0 <= 0) & (w1 <= 0) & (w2 <= 0))
            if not np.any(hit):
                continue
            zHit = (w0[hit] * a[hit, 2] + w1[hit] * b[hit, 2] + w2[hit] * c[hit, 2]) / d[hit]
            yield p[hit], zHit, np.sign(d[hit]).astype(np.int64)


def pointsInsideMesh(mesh: trimesh.Trimesh, points: np.ndarray, maxPairs: int = 4_000_000) -> np.ndarray:
    """
    Fast inside/outside test of points against a closed (watertight) mesh.

    A vertical ray is cast upwards from every point and the signed crossings with the mesh are summed (a generalised
    winding number along +Z). This is far quicker than :meth:`trimesh.Trimesh.contains` for the many thousands of
    samples used when generating lattice supports, and is unaffected by degenerate triangles.

    :param mesh: A closed mesh. The result is independent of the face winding orientation.
    :param points: The (n, 3) query points
    :param maxPairs: Upper bound on candidate triangle/point pairs evaluated per batch, to cap memory use
    :return: A boolean array, :code:`True` for points inside the mesh
    """
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    winding = np.zeros(len(pts), dtype=np.int64)
    for p, z, sign in _iterVerticalHits(mesh, pts[:, :2], maxPairs):
        above = z > pts[p, 2]
        winding += np.bincount(p[above], weights=sign[above], minlength=len(pts)).astype(np.int64)
    return winding != 0


def verticalIntervals(mesh: trimesh.Trimesh, xy: np.ndarray,
                      maxPairs: int = 4_000_000) -> Tuple[np.ndarray, np.ndarray]:
    """
    Find where vertical lines lie inside a closed (watertight) mesh.

    :param mesh: A closed mesh
    :param xy: The (n, 2) line positions
    :param maxPairs: Upper bound on candidate triangle/line pairs evaluated per batch, to cap memory use
    :return: The line index of every interval and the (m, 2) ``[zLow, zHigh]`` intervals, ordered by line then height
    """
    xy = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
    lines, heights = [], []
    for p, z, _sign in _iterVerticalHits(mesh, xy, maxPairs):
        lines.append(p)
        heights.append(z)
    if not lines:
        return np.empty(0, dtype=np.int64), np.empty((0, 2))

    lines = np.concatenate(lines)
    heights = np.concatenate(heights)
    order = np.lexsort((heights, lines))
    lines, heights = lines[order], heights[order]

    # Consecutive crossings along each line alternately enter and leave the closed mesh
    rank = np.arange(len(lines)) - np.searchsorted(lines, lines, side='left')
    entry = np.flatnonzero((rank % 2 == 0) & (np.r_[lines[1:], -1] == lines))
    intervals = np.stack((heights[entry], heights[entry + 1]), axis=1)
    return lines[entry], intervals


def cylinderSegments(segments: np.ndarray, radius: float, sections: int = 8) -> Tuple[trimesh.Trimesh, np.ndarray]:
    """
    Build capped cylinders along many line segments in a single vectorised operation. The result matches calling
    :func:`trimesh.creation.cylinder` for every segment and concatenating the meshes, without the per-segment
    overhead.

    :param segments: The (n, 2, 3) segment end points
    :param radius: Cylinder radius
    :param sections: Number of sides around each cylinder
    :return: The combined mesh and, for every face, the index of the segment it belongs to
    """
    segments = np.asarray(segments, dtype=np.float64).reshape(-1, 2, 3)
    if len(segments) == 0:
        return trimesh.Trimesh(), np.empty(0, dtype=np.int64)

    template = trimesh.creation.cylinder(radius=radius, height=1.0, sections=sections)
    tVerts = np.asarray(template.vertices, dtype=np.float64)
    tFaces = np.asarray(template.faces, dtype=np.int64)

    axis = segments[:, 1] - segments[:, 0]
    length = np.linalg.norm(axis, axis=1)
    direction = axis / np.maximum(length, 1e-12)[:, None]

    # Rotation taking +Z onto each direction (Rodrigues); the antiparallel case is a half-turn about X
    v = np.cross(np.broadcast_to(np.array([0.0, 0.0, 1.0]), direction.shape), direction)
    cosA = direction[:, 2]
    vx = np.zeros((len(direction), 3, 3))
    vx[:, 0, 1], vx[:, 0, 2] = -v[:, 2], v[:, 1]
    vx[:, 1, 0], vx[:, 1, 2] = v[:, 2], -v[:, 0]
    vx[:, 2, 0], vx[:, 2, 1] = -v[:, 1], v[:, 0]
    flipped = cosA <= -1.0 + 1e-9
    k = 1.0 / np.where(flipped, 1.0, 1.0 + cosA)
    rot = np.eye(3)[None] + vx + np.einsum('nij,njk->nik', vx, vx) * k[:, None, None]
    rot[flipped] = np.diag([1.0, -1.0, -1.0])

    local = np.broadcast_to(tVerts, (len(segments),) + tVerts.shape).copy()
    local[:, :, 2] *= length[:, None]
    midpoints = (segments[:, 0] + segments[:, 1]) / 2.0
    verts = np.einsum('nij,nvj->nvi', rot, local) + midpoints[:, None, :]

    faces = tFaces[None, :, :] + (np.arange(len(segments)) * len(tVerts))[:, None, None]
    faceSegment = np.repeat(np.arange(len(segments)), len(tFaces))
    mesh = trimesh.Trimesh(vertices=verts.reshape(-1, 3), faces=faces.reshape(-1, 3), process=False)
    return mesh, faceSegment
