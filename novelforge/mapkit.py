"""
mapkit - the shared geometry kit behind NovelForge's map generators.

The dungeon, floor plan, city, castle, sector, journey and realm generators all
need the same handful of geometric tools (cut a polygon into building lots,
shrink it for a street, tile a rectangle into rooms, trace a set of grid cells
into a wall outline, ...). They live here once so each generator is only the
part that is specific to it.

Rules this module keeps, and callers may rely on:

* **Pure and deterministic.** No globals, no clock, no I/O, no tkinter or
  Pillow. Anything random takes a ``random.Random`` argument; the same
  arguments always give the same result. Seeds are made with ``stable_seed``
  (``zlib.crc32``), never ``hash()``, which Python salts per process.
* **Points** are ``(x, y)`` tuples of floats. **Polygons** are lists of points
  with no repeated closing point. **Rectangles and bounding boxes** share one
  form, ``(x0, y0, x1, y1)`` with ``x0 <= x1`` and ``y0 <= y1``.
* **Winding.** ``polygon_area`` is *signed*: positive when the vertices run
  counter-clockwise in a y-up frame. A Tk canvas has y pointing down, so a
  polygon that is "counter-clockwise" here looks clockwise on screen; the sign
  is just arithmetic, and every function here is consistent about it.
* **Graphs** are dictionaries. Unweighted: ``{node: [neighbour, ...]}``.
  Weighted: ``{node: [(neighbour, weight), ...]}``. Nodes can be anything
  hashable (ints, ``(col, row)`` tuples, ...); ``edges_to_adj`` and
  ``edges_to_wadj`` build them from edge lists.
* **Tolerances** are absolute (``EPS`` = 1e-9), sized for maps whose
  coordinates run from a few units to a few thousand.
* **Nothing is changed in place**; every function returns new lists. **Failure
  is a value, not an exception:** an empty polygon is ``[]``, a shrink that
  leaves nothing is ``None`` (``inset_polygon``), a missing route is ``None``.
  Exceptions are only for misuse (a zero ``min_leaf``, negative weights).

What is here, by need:

* seeding - ``stable_seed``, ``sub_rng``
* polygons - ``polygon_area``, ``polygon_centroid``, ``is_ccw``, ``ensure_ccw``,
  ``polygon_bbox``, ``point_in_polygon``, ``polygon_edges``,
  ``segments_intersect``, ``polygon_is_simple``, ``is_convex``,
  ``polygon_contains_polygon``, ``convex_hull``
* cutting and shrinking - ``clip_halfplane``, ``clip_convex``,
  ``inset_polygon``, ``offset_polygon``, ``bisect_polygon``
* points and cells - ``sunflower``, ``voronoi_cells``, ``lloyd_relax``,
  ``poisson_disc``
* graphs - ``mst``, ``gabriel_edges``, ``dijkstra``, ``multi_source_dijkstra``,
  ``bfs_reachable``, ``connected_components``, ``farthest_pair``
* rectangles and grids - ``bsp_split``, ``squarify``, ``shared_walls``,
  ``cells_outline``, ``hex_center``, ``hex_corners``, ``hex_neighbors``,
  ``hex_distance``
* paths - ``chaikin``, ``catmull_rom``, ``simplify``, ``resample``,
  ``polyline_length``, ``point_at``

Licence note: everything here is written from the published ideas (Sutherland-
Hodgman clipping, Bridson sampling, Bruls squarified treemaps, Lloyd
relaxation, Douglas-Peucker, Chaikin, centripetal Catmull-Rom); no code was
ported from GPL projects such as TownGeneratorOS.
"""

from __future__ import annotations

import bisect
import heapq
import math
import random
import zlib
from collections import deque
from typing import (Callable, Dict, Hashable, Iterable, List, Mapping,
                    Optional, Sequence, Tuple)

Point = Tuple[float, float]
Polygon = List[Point]
Rect = Tuple[float, float, float, float]      # (x0, y0, x1, y1)

EPS = 1e-9


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def stable_seed(*parts) -> int:
    """A 32-bit seed built from any parts, identical in every process.

    ``stable_seed(7, "walls")`` is ``zlib.crc32(b"7:walls")``. Python's own
    ``hash()`` of a string is salted per process, so it must never be used for
    anything that has to be the same tomorrow.
    """
    text = ":".join(map(str, parts))
    return zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF


def sub_rng(seed, stage) -> random.Random:
    """One independent ``Random`` per stage of a generator.

    Seeded from ``stable_seed(seed, stage)``, so adding a new stage to a
    generator never reshuffles what the earlier stages produced.
    """
    return random.Random(stable_seed(seed, stage))


# ---------------------------------------------------------------------------
# Small vector helpers
# ---------------------------------------------------------------------------

def dist(a: Point, b: Point) -> float:
    """Euclidean distance between two points."""
    return math.hypot(a[0] - b[0], a[1] - b[1])


def lerp(a: Point, b: Point, t: float) -> Point:
    """The point a fraction ``t`` of the way from ``a`` to ``b``."""
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def cross(o: Point, a: Point, b: Point) -> float:
    """z of (a - o) x (b - o): positive when o -> a -> b turns left (y-up)."""
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def rect_polygon(rect: Rect) -> Polygon:
    """The four corners of a rectangle, counter-clockwise (positive area)."""
    x0, y0, x1, y1 = rect
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def rect_area(rect: Rect) -> float:
    return (rect[2] - rect[0]) * (rect[3] - rect[1])


def rect_center(rect: Rect) -> Point:
    return ((rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0)


def rect_contains(rect: Rect, pt: Point, tol: float = 0.0) -> bool:
    """Is ``pt`` inside the rectangle (edges included, within ``tol``)?"""
    return (rect[0] - tol <= pt[0] <= rect[2] + tol
            and rect[1] - tol <= pt[1] <= rect[3] + tol)


# ---------------------------------------------------------------------------
# Polygon basics
# ---------------------------------------------------------------------------

def polygon_area(poly: Sequence[Point]) -> float:
    """Signed area (shoelace). Positive for counter-clockwise in a y-up frame."""
    n = len(poly)
    if n < 3:
        return 0.0
    ox, oy = poly[0]                 # relative to a vertex: steadier far from 0
    total = 0.0
    x0, y0 = poly[-1][0] - ox, poly[-1][1] - oy
    for px, py in poly:
        x1, y1 = px - ox, py - oy
        total += x0 * y1 - x1 * y0
        x0, y0 = x1, y1
    return total / 2.0


def polygon_perimeter(poly: Sequence[Point]) -> float:
    """Length of the closed outline."""
    n = len(poly)
    return sum(dist(poly[i], poly[(i + 1) % n]) for i in range(n)) if n > 1 else 0.0


def polygon_centroid(poly: Sequence[Point]) -> Point:
    """Centre of mass of the polygon's area (vertex average if it has none)."""
    if not poly:
        raise ValueError("polygon_centroid of an empty polygon")
    area = polygon_area(poly)
    ox, oy = poly[0]
    if abs(area) < EPS:
        n = len(poly)
        return (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)
    cx = cy = 0.0
    x0, y0 = poly[-1][0] - ox, poly[-1][1] - oy
    for px, py in poly:
        x1, y1 = px - ox, py - oy
        f = x0 * y1 - x1 * y0
        cx += (x0 + x1) * f
        cy += (y0 + y1) * f
        x0, y0 = x1, y1
    return (ox + cx / (6.0 * area), oy + cy / (6.0 * area))


def is_ccw(poly: Sequence[Point]) -> bool:
    """True when the polygon has positive signed area."""
    return polygon_area(poly) > 0.0


def ensure_ccw(poly: Sequence[Point]) -> Polygon:
    """A copy of ``poly`` wound counter-clockwise (positive area)."""
    pts = list(poly)
    if polygon_area(pts) < 0.0:
        pts.reverse()
    return pts


def polygon_bbox(poly: Sequence[Point]) -> Rect:
    """``(minx, miny, maxx, maxy)`` of the points."""
    if not poly:
        raise ValueError("polygon_bbox of an empty polygon")
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (min(xs), min(ys), max(xs), max(ys))


def polygon_edges(poly: Sequence[Point]) -> List[Tuple[Point, Point]]:
    """Every edge as ``(a, b)``, including the closing one."""
    n = len(poly)
    return [(poly[i], poly[(i + 1) % n]) for i in range(n)]


def point_in_polygon(pt: Point, poly: Sequence[Point]) -> bool:
    """Even-odd ray cast. A point exactly on the boundary may go either way;
    use ``distance_to_boundary`` when that matters."""
    x, y = pt
    inside = False
    n = len(poly)
    if n < 3:
        return False
    xj, yj = poly[-1]
    for xi, yi in poly:
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        xj, yj = xi, yi
    return inside


def point_segment_distance(p: Point, a: Point, b: Point) -> float:
    """Shortest distance from ``p`` to the segment ``a``-``b``."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if length2 <= 0.0:
        return dist(p, a)
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def distance_to_boundary(pt: Point, poly: Sequence[Point]) -> float:
    """Shortest distance from ``pt`` to the polygon's outline."""
    if not poly:
        raise ValueError("distance_to_boundary of an empty polygon")
    n = len(poly)
    return min(point_segment_distance(pt, poly[i], poly[(i + 1) % n])
               for i in range(n))


def _side(a: Point, b: Point, p: Point) -> int:
    """Which side of the line a->b is p on: 1 left, -1 right, 0 within EPS."""
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    if length <= 0.0:
        return 0
    d = cross(a, b, p) / length          # signed distance from the line
    return 0 if abs(d) <= EPS else (1 if d > 0 else -1)


def _in_box(a: Point, b: Point, p: Point) -> bool:
    """Is p inside the bounding box of a-b (with EPS slack)? Used once p is
    known to be collinear with a-b."""
    return (min(a[0], b[0]) - EPS <= p[0] <= max(a[0], b[0]) + EPS
            and min(a[1], b[1]) - EPS <= p[1] <= max(a[1], b[1]) + EPS)


def segments_intersect(a: Point, b: Point, c: Point, d: Point,
                       touching: bool = True) -> bool:
    """Do segments ``a``-``b`` and ``c``-``d`` meet?

    With ``touching=True`` (the default) sharing an endpoint, an endpoint
    resting on the other segment, and collinear overlap all count. With
    ``touching=False`` only a proper crossing counts (each segment's interior
    passes through the other's).
    """
    o1, o2 = _side(a, b, c), _side(a, b, d)
    o3, o4 = _side(c, d, a), _side(c, d, b)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    if not touching:
        return False
    if o1 == 0 and _in_box(a, b, c):
        return True
    if o2 == 0 and _in_box(a, b, d):
        return True
    if o3 == 0 and _in_box(c, d, a):
        return True
    if o4 == 0 and _in_box(c, d, b):
        return True
    return False


def polygon_is_simple(poly: Sequence[Point]) -> bool:
    """True for a proper simple polygon: at least 3 vertices, some area, no
    repeated vertex, and no edge touching any edge but its two neighbours
    (which may only meet at their shared vertex, never fold back over each
    other). O(n^2), meant for polygons of tens of vertices."""
    n = len(poly)
    if n < 3 or abs(polygon_area(poly)) < EPS:
        return False
    for i in range(n):
        if dist(poly[i], poly[(i + 1) % n]) <= EPS:
            return False
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        for j in range(i + 1, n):
            c, d = poly[j], poly[(j + 1) % n]
            if j == i + 1 or (i == 0 and j == n - 1):
                # Neighbouring edges share a vertex; they must not overlap.
                if j == i + 1:
                    s, u, v = b, a, d
                else:
                    s, u, v = a, b, c
                if (_side(s, v, u) == 0 and _in_box(s, v, u)) or \
                        (_side(s, u, v) == 0 and _in_box(s, u, v)):
                    return False
            elif segments_intersect(a, b, c, d):
                return False
    return True


def is_convex(poly: Sequence[Point]) -> bool:
    """True when every turn goes the same way and the outline winds exactly
    once (so a pentagram, whose turns all agree, is not convex)."""
    n = len(poly)
    if n < 3:
        return False
    sign = 0
    total = 0.0
    for i in range(n):
        p, q, r = poly[i], poly[(i + 1) % n], poly[(i + 2) % n]
        s = _side(p, q, r)
        if s != 0:
            if sign and s != sign:
                return False
            sign = s
        ux, uy = q[0] - p[0], q[1] - p[1]
        vx, vy = r[0] - q[0], r[1] - q[1]
        total += math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
    return sign != 0 and abs(abs(total) - 2.0 * math.pi) < 1e-6


def polygon_contains_polygon(outer: Sequence[Point], inner: Sequence[Point],
                             tol: float = 1e-6) -> bool:
    """Does ``outer`` contain ``inner`` (touching its outline is fine)?

    Every vertex of ``inner`` must be inside or within ``tol`` of the outline,
    and no edge of ``inner`` may properly cross an edge of ``outer``. Exact for
    convex ``outer``; for a concave one an inner edge that leaves and re-enters
    through a vertex exactly on the outline is not detected.
    """
    for p in inner:
        if not point_in_polygon(p, outer) and distance_to_boundary(p, outer) > tol:
            return False
    for a, b in polygon_edges(inner):
        for c, d in polygon_edges(outer):
            if segments_intersect(a, b, c, d, touching=False):
                return False
    # A vertex-only test misses a hole poking through the middle of an edge
    # only if the crossing test above missed it too; also check midpoints.
    for a, b in polygon_edges(inner):
        m = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        if not point_in_polygon(m, outer) and distance_to_boundary(m, outer) > tol:
            return False
    return True


# ---------------------------------------------------------------------------
# Polygon operations
# ---------------------------------------------------------------------------

def _clean(points: Iterable[Point]) -> Polygon:
    """Drop consecutive duplicates and a repeated closing point. Returns []
    when what is left has fewer than 3 points or no area."""
    out: Polygon = []
    for p in points:
        if not out or dist(p, out[-1]) > EPS:
            out.append((float(p[0]), float(p[1])))
    while len(out) > 1 and dist(out[0], out[-1]) <= EPS:
        out.pop()
    if len(out) < 3 or abs(polygon_area(out)) < EPS:
        return []
    return out


def convex_hull(points: Iterable[Point]) -> Polygon:
    """Convex hull, counter-clockwise, collinear points dropped (monotone
    chain). Fewer than 3 distinct points give back those points."""
    pts = sorted(set((float(x), float(y)) for x, y in points))
    if len(pts) < 3:
        return pts

    def half(seq):
        chain: Polygon = []
        for p in seq:
            while len(chain) >= 2 and cross(chain[-2], chain[-1], p) <= 0.0:
                chain.pop()
            chain.append(p)
        return chain

    lower, upper = half(pts), half(reversed(pts))
    return lower[:-1] + upper[:-1]


def _cut_point(p: Point, q: Point, sp: float, sq: float) -> Point:
    """Where p->q crosses the clip line, given the signed distances of its ends."""
    t = sp / (sp - sq) if sp != sq else 0.0
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)


def clip_halfplane(poly: Sequence[Point], a: Point, b: Point,
                   keep_left: bool = True) -> Polygon:
    """The part of ``poly`` on one side of the line through ``a`` and ``b``.

    "Left" is the side you turn towards walking from ``a`` to ``b`` (y-up), so
    for a counter-clockwise polygon it is the inside of the edge a->b. Returns
    ``[]`` when nothing is left. Exact for convex polygons. For a concave
    polygon the result can be a single polygon that joins its pieces along the
    line with zero-width bridges (Sutherland-Hodgman); ``polygon_is_simple``
    tells them apart.
    """
    if len(poly) < 3:
        return []
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length <= 0.0:
        raise ValueError("clip_halfplane needs two distinct points")
    sign = 1.0 if keep_left else -1.0

    def side(p: Point) -> float:            # distance to the line, + = kept side
        return sign * (dx * (p[1] - a[1]) - dy * (p[0] - a[0])) / length

    out: Polygon = []
    prev = poly[-1]
    sp = side(prev)
    for cur in poly:
        sc = side(cur)
        if sc >= -EPS:
            if sp < -EPS:
                out.append(_cut_point(prev, cur, sp, sc))
            out.append(cur)
        elif sp >= -EPS:
            out.append(_cut_point(prev, cur, sp, sc))
        prev, sp = cur, sc
    return _clean(out)


def clip_convex(poly: Sequence[Point], convex_clip: Sequence[Point]) -> Polygon:
    """``poly`` cut down to the inside of a convex polygon (any winding).

    The clip shape must be convex; ``poly`` may be anything ``clip_halfplane``
    accepts. Returns ``[]`` when they do not overlap.
    """
    out: Polygon = list(poly)
    for a, b in polygon_edges(ensure_ccw(convex_clip)):
        if dist(a, b) <= EPS:
            continue
        out = clip_halfplane(out, a, b, True)
        if not out:
            return []
    return out


def _mitered(pts: Sequence[Point], d: float,
             miter_limit: Optional[float] = None) -> Optional[Polygon]:
    """Every edge of a counter-clockwise polygon shifted ``d`` to its left
    (inward when d > 0, outward when d < 0) and neighbours joined at the point
    where their shifted lines meet (a mitre).

    Edges that shrink past nothing are dropped and their neighbours joined
    (the "edge event" of a straight skeleton). With ``miter_limit`` a sharp
    outward corner whose mitre would stick out more than that many ``|d|`` is
    cut off flat instead. Returns None when the shape cannot be joined up
    (fewer than 3 edges survive, or two neighbouring edges are anti-parallel).
    """
    n = len(pts)
    lines: List[Tuple[Point, Point]] = []          # (point on shifted line, direction)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        length = dist(a, b)
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        lines.append(((a[0] - uy * d, a[1] + ux * d), (ux, uy)))
    for _ in range(n + 1):
        m = len(lines)
        if m < 3:
            return None
        verts: List[Point] = []
        for j in range(m):
            (q1, u1), (q2, u2) = lines[j - 1], lines[j]
            c = u1[0] * u2[1] - u1[1] * u2[0]
            if abs(c) < 1e-12:
                if u1[0] * u2[0] + u1[1] * u2[1] < 0.0:
                    return None
                verts.append(q2)
            else:
                t = ((q2[0] - q1[0]) * u2[1] - (q2[1] - q1[1]) * u2[0]) / c
                verts.append((q1[0] + u1[0] * t, q1[1] + u1[1] * t))
        worst, worst_j = 1e-12, -1
        for j in range(m):
            nx, ny = verts[(j + 1) % m]
            run = (nx - verts[j][0]) * lines[j][1][0] + (ny - verts[j][1]) * lines[j][1][1]
            if run < worst:
                worst, worst_j = run, j
        if worst_j < 0:
            break
        del lines[worst_j]                       # this edge has shrunk away
    else:
        return None
    if miter_limit is None or d >= 0.0:
        return verts
    # Outward corners: bevel any mitre that would spike out too far.
    out: Polygon = []
    for j in range(len(verts)):
        u1, u2 = lines[j - 1][1], lines[j][1]
        c = u1[0] * u2[1] - u1[1] * u2[0]
        if c > 0.0:                                  # a convex corner
            phi = math.atan2(c, u1[0] * u2[0] + u1[1] * u2[1])   # how sharply it turns
            if math.cos(phi / 2.0) < 1.0 / miter_limit:          # mitre = |d| / cos(phi/2)
                h = abs(d) * math.tan(phi / 2.0)     # mitre point to the two feet
                mx, my = verts[j]
                out.append((mx - u1[0] * h, my - u1[1] * h))
                out.append((mx + u2[0] * h, my + u2[1] * h))
                continue
        out.append(verts[j])
    return out


def _offset_ok(orig: Sequence[Point], res: Sequence[Point], d: float,
               inward: bool) -> bool:
    """Validate an offset of counter-clockwise ``orig`` by ``d`` > 0.

    The result must be a simple counter-clockwise polygon, on the right side
    of the original (inside for an inset, containing it for an offset), never
    touching the original outline, and with every vertex at least ``d`` from
    it. For an inset the original's vertices must also stay ``d`` from the
    result's edges (the closest approach of two polygons that do not cross is
    always between a vertex of one and an edge of the other, so testing those
    pairs is exact). That last test is skipped for an offset: a bevelled
    corner cuts across closer than ``d`` to the corner it replaces, on purpose.
    """
    if len(res) < 3 or not polygon_is_simple(res) or polygon_area(res) <= 0.0:
        return False
    area, base = polygon_area(res), polygon_area(orig)
    if (area >= base) if inward else (area <= base):
        return False
    tol = 1e-6
    outer, inner = (orig, res) if inward else (res, orig)
    if not polygon_contains_polygon(outer, inner, tol):
        return False
    for a, b in polygon_edges(res):
        for c, e in polygon_edges(orig):
            if segments_intersect(a, b, c, e):
                return False
    for v in res:
        if distance_to_boundary(v, orig) < d - tol:
            return False
    if inward:
        for v in orig:
            if distance_to_boundary(v, res) < d - tol:
                return False
    return True


def _inset_convex(pts: Sequence[Point], d: float) -> Optional[Polygon]:
    """Exact inset of a convex counter-clockwise polygon: the polygon itself
    clipped by each of its edges moved inward by ``d``."""
    cur: Polygon = list(pts)
    for a, b in polygon_edges(pts):
        length = dist(a, b)
        nx, ny = -(b[1] - a[1]) / length, (b[0] - a[0]) / length
        cur = clip_halfplane(cur, (a[0] + nx * d, a[1] + ny * d),
                             (b[0] + nx * d, b[1] + ny * d), True)
        if not cur:
            return None
    return cur


def _inset_concave(pts: Sequence[Point], d: float) -> Optional[Polygon]:
    """Best-effort inset of a concave counter-clockwise polygon, validated."""
    for steps in (1, 2, 4, 8):
        cur: Optional[Polygon] = list(pts)
        for _ in range(steps):
            cur = _mitered(cur, d / steps)
            cur = _clean(cur) if cur else None
            if not cur or polygon_area(cur) <= 0.0:
                cur = None
                break
        if cur and _offset_ok(pts, cur, d, inward=True):
            return cur
    return None


def inset_polygon(poly: Sequence[Point], d: float) -> Optional[Polygon]:
    """``poly`` shrunk by ``d`` on every side, or None if nothing is left.

    Exact for convex polygons (the polygon clipped by each edge moved inward
    by ``d``). For concave polygons the edges are moved in and neighbours
    re-joined with sharp corners, edges that shrink away are dropped, and the
    outcome is *validated* (simple, inside the original, nowhere nearer than
    ``d`` to its outline); if that fails the shrink is retried in 2, 4 and 8
    smaller steps, and if it still fails, or the shape splits in two, the
    answer is None - treat that as "collapsed". The winding of the input is
    kept. ``d`` <= 0 returns a copy (a negative ``d`` grows the polygon; see
    ``offset_polygon``).
    """
    if d < 0.0:
        return offset_polygon(poly, -d) or None
    pts = _clean(poly)
    if not pts:
        return None
    was_cw = polygon_area(pts) < 0.0
    if was_cw:
        pts.reverse()
    if d == 0.0:
        res: Optional[Polygon] = pts
    elif is_convex(pts):
        res = _inset_convex(pts, d)
    else:
        res = _inset_concave(pts, d)
    if not res:
        return None
    return res[::-1] if was_cw else res


def offset_polygon(poly: Sequence[Point], d: float,
                   miter_limit: float = 2.5) -> Polygon:
    """``poly`` grown outward by ``d`` (for moats, walls and margins).

    Corners are sharp; a very acute corner is bevelled once its point would
    stick out more than ``miter_limit`` times ``d``. If a concave polygon is
    grown so far that it would cross itself, the growth is retried in smaller
    steps and, failing that, the offset of its convex hull is returned, so the
    result is always a simple polygon that contains the original. The winding
    of the input is kept. A negative ``d`` shrinks (``[]`` if nothing is left).
    """
    if d < 0.0:
        return inset_polygon(poly, -d) or []
    pts = _clean(poly)
    if not pts:
        return list(poly)
    was_cw = polygon_area(pts) < 0.0
    if was_cw:
        pts.reverse()
    res: Optional[Polygon] = pts if d == 0.0 else None
    if res is None:
        for steps in (1, 2, 4, 8):
            cur: Optional[Polygon] = list(pts)
            for _ in range(steps):
                cur = _mitered(cur, -d / steps, miter_limit)
                cur = _clean(cur) if cur else None
                if not cur:
                    break
            if cur and _offset_ok(pts, cur, d, inward=False):
                res = cur
                break
    if res is None:
        hull = convex_hull(pts)
        res = _mitered(hull, -d, miter_limit) or hull
    return res[::-1] if was_cw else res


def interior_angle(prev: Point, cur: Point, nxt: Point) -> float:
    """Interior angle in degrees (0-360) at ``cur`` of a counter-clockwise
    polygon whose neighbouring vertices are ``prev`` and ``nxt``; over 180
    means a reflex corner."""
    ux, uy = nxt[0] - cur[0], nxt[1] - cur[1]
    wx, wy = prev[0] - cur[0], prev[1] - cur[1]
    a = math.atan2(ux * wy - uy * wx, ux * wx + uy * wy)
    return math.degrees(a + 2.0 * math.pi if a < 0.0 else a)


def compactness(poly: Sequence[Point]) -> float:
    """Isoperimetric quotient 4*pi*area / perimeter^2: 1 for a circle, about
    0.785 for a square, 0.6 for an equilateral triangle, near 0 for a sliver."""
    per = polygon_perimeter(poly)
    return 4.0 * math.pi * abs(polygon_area(poly)) / (per * per) if per > 0 else 0.0


def _split_once(poly: Polygon, rng: random.Random, area: float, min_area: float,
                min_angle: float, jitter: float, min_compact: float,
                convex: bool) -> Optional[Tuple[Polygon, Polygon]]:
    """One cut across the longest side; up to six tries, then None."""
    n = len(poly)
    lengths = [dist(poly[i], poly[(i + 1) % n]) for i in range(n)]
    order = sorted(range(n), key=lambda i: (-lengths[i], i))
    parent_compact = compactness(poly)
    for attempt in range(6):
        i = order[min(attempt // 3, n - 1)]       # longest side, then second longest
        a, b = poly[i], poly[(i + 1) % n]
        if attempt % 3 == 2:
            ratio, tilt = 0.5, 0.0                # last try on a side: dead centre, square
        else:
            ratio = 0.5 + rng.uniform(-jitter, jitter)
            tilt = math.radians(rng.uniform(-jitter, jitter) * 60.0)
        ex, ey = (b[0] - a[0]) / lengths[i], (b[1] - a[1]) / lengths[i]
        ct, st = math.cos(tilt), math.sin(tilt)
        cx, cy = -ey * ct - ex * st, ex * ct - ey * st        # inward normal, tilted
        px, py = a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio
        p2 = (px + cx, py + cy)
        left = clip_halfplane(poly, (px, py), p2, True)
        right = clip_halfplane(poly, (px, py), p2, False)
        if not left or not right:
            continue
        al, ar = polygon_area(left), polygon_area(right)
        if al < min_area or ar < min_area or abs(al + ar - area) > 1e-6 * area:
            continue
        if not convex and not (polygon_is_simple(left) and polygon_is_simple(right)):
            continue
        ok = True
        for piece in (left, right):
            c = compactness(piece)
            if c < min_compact and c < parent_compact - 1e-12:
                ok = False                        # a sliver, and worse than what we cut
                break
            m = len(piece)
            for k in range(m):
                v = piece[k]
                if abs(cx * (v[1] - py) - cy * (v[0] - px)) > 1e-7:
                    continue                      # not a corner made by this cut
                ang = interior_angle(piece[k - 1], v, piece[(k + 1) % m])
                if ang < min_angle or ang > 360.0 - min_angle:
                    ok = False
                    break
            if not ok:
                break
        if ok:
            return left, right
    return None


def bisect_polygon(poly: Sequence[Point], rng: random.Random, min_area: float,
                   min_angle_deg: float = 25.0, jitter: float = 0.15,
                   min_compactness: float = 0.2, max_depth: int = 20) -> List[Polygon]:
    """Cut a polygon into building lots (the ward / block splitter).

    Recursively cuts across the longest side, near its middle: the cut point
    is at ``0.5 +/- jitter`` along the side and the cut leans up to
    ``jitter * 60`` degrees off square. A cut is refused - and another tried,
    then the polygon is left whole - if either piece would be smaller than
    ``min_area``, would make a corner sharper than ``min_angle_deg`` (or a
    reflex spike within that of a full turn), or would be a sliver (compactness
    under ``min_compactness`` *and* worse than the polygon being cut, so a
    long thin block is still cut down into shorter lots). Pieces are only
    split while their area is at least twice ``min_area``, so lots land
    between ``min_area`` and roughly three times it.

    The lots tile the polygon exactly (no gaps, no overlaps; inset each one
    for streets and alleys), are wound counter-clockwise, and come out in a
    fixed order. A polygon smaller than ``min_area`` comes back as the single
    lot. Corners the input already had are never blamed on a cut.
    """
    pts = _clean(poly)
    if not pts:
        return []
    pts = ensure_ccw(pts)
    convex = is_convex(pts)
    out: List[Polygon] = []
    stack: List[Tuple[Polygon, int]] = [(pts, 0)]
    while stack:
        piece, depth = stack.pop()
        area = polygon_area(piece)
        halves = None
        if depth < max_depth and area >= 2.0 * min_area:
            halves = _split_once(piece, rng, area, min_area, min_angle_deg,
                                 jitter, min_compactness, convex)
        if halves is None:
            out.append(piece)
        else:
            stack.append((halves[1], depth + 1))
            stack.append((halves[0], depth + 1))
    return out


# ---------------------------------------------------------------------------
# Points and cells
# ---------------------------------------------------------------------------

GOLDEN_ANGLE = math.pi * (3.0 - math.sqrt(5.0))         # about 2.39996 radians


def sunflower(n: int, cx: float = 0.0, cy: float = 0.0, radius: float = 1.0,
              phase: float = 0.0) -> List[Point]:
    """``n`` points on a golden-angle (Vogel) spiral: even spacing with no
    rows or columns, the classic seed layout for a town's wards.

    Point 0 is the centre and later points spiral outward, so index order is
    distance order; the last one lies exactly ``radius`` from the centre.
    ``phase`` turns the whole spiral (radians).
    """
    if n <= 0:
        return []
    if n == 1:
        return [(cx, cy)]
    out: List[Point] = []
    for i in range(n):
        r = radius * math.sqrt(i / (n - 1))
        a = phase + i * GOLDEN_ANGLE
        out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return out


def voronoi_cells(points: Sequence[Point], bbox: Rect) -> List[Polygon]:
    """The Voronoi cell of every site, clipped to ``bbox``.

    ``result[i]`` is the region of the box nearer to ``points[i]`` than to any
    other site: a convex counter-clockwise polygon, or ``[]`` if a site outside
    the box has no part of the box. The cells tile the box exactly. Built by
    cutting the box with each neighbour's bisector, nearest neighbours first,
    stopping once no farther site can reach the cell, so it is close to linear
    in practice; fine for a few hundred sites. Sites must be distinct (a
    coincident site is ignored).
    """
    n = len(points)
    box = rect_polygon(bbox)
    cells: List[Polygon] = []
    for i in range(n):
        p = points[i]
        px, py = p
        others = sorted(((points[j][0] - px) ** 2 + (points[j][1] - py) ** 2, j)
                        for j in range(n) if j != i)
        cell: Polygon = box
        reach2 = max((v[0] - px) ** 2 + (v[1] - py) ** 2 for v in cell)
        for d2, j in others:
            if d2 > 4.0 * reach2 * (1.0 + 1e-12):
                break                    # this and every farther bisector misses the cell
            if d2 <= 1e-18:
                continue
            qx, qy = points[j]
            mx, my = (px + qx) / 2.0, (py + qy) / 2.0
            cell = clip_halfplane(cell, (mx, my), (mx - (qy - py), my + (qx - px)), True)
            if not cell:
                break
            reach2 = max((v[0] - px) ** 2 + (v[1] - py) ** 2 for v in cell)
        cells.append(cell)
    return cells


def lloyd_relax(points: Sequence[Point], bbox: Rect,
                iterations: int = 1) -> List[Point]:
    """Lloyd's relaxation: move every site to the centroid of its Voronoi
    cell, ``iterations`` times. Evens out the cells while keeping the layout
    irregular; sites stay inside ``bbox``. The order and count are kept."""
    pts: List[Point] = [(float(x), float(y)) for x, y in points]
    for _ in range(max(0, iterations)):
        cells = voronoi_cells(pts, bbox)
        pts = [polygon_centroid(c) if c else p for c, p in zip(cells, pts)]
    return pts


def poisson_disc(rng: random.Random, bbox: Rect, min_dist: float,
                 k: int = 30) -> List[Point]:
    """Blue-noise points no closer than ``min_dist`` (Bridson's algorithm).

    Fills the box (``x0 <= x < x1``, ``y0 <= y < y1``) so evenly that no
    circle of radius ``2 * min_dist`` is empty, in a fixed order for a given
    ``rng``. ``k`` is the number of candidates tried around each point before
    it is retired (higher packs tighter and costs more).
    """
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    if min_dist <= 0.0:
        raise ValueError("poisson_disc needs a positive min_dist")
    if w <= 0.0 or h <= 0.0:
        return []
    cell = min_dist / math.sqrt(2.0)
    gw, gh = int(w / cell) + 1, int(h / cell) + 1
    grid = [-1] * (gw * gh)                       # each grid cell holds at most one point
    pts: List[Point] = []
    active: List[int] = []
    limit2 = min_dist * min_dist

    def add(p: Point) -> None:
        grid[int((p[1] - y0) / cell) * gw + int((p[0] - x0) / cell)] = len(pts)
        active.append(len(pts))
        pts.append(p)

    add((x0 + rng.random() * w, y0 + rng.random() * h))
    while active:
        slot = rng.randrange(len(active))
        bx, by = pts[active[slot]]
        for _ in range(k):
            ang = rng.random() * 2.0 * math.pi
            r = min_dist * (1.0 + rng.random())
            p = (bx + r * math.cos(ang), by + r * math.sin(ang))
            if not (x0 <= p[0] < x1 and y0 <= p[1] < y1):
                continue
            gx, gy = int((p[0] - x0) / cell), int((p[1] - y0) / cell)
            clear = True
            for yy in range(max(gy - 2, 0), min(gy + 3, gh)):
                for xx in range(max(gx - 2, 0), min(gx + 3, gw)):
                    j = grid[yy * gw + xx]
                    if j >= 0 and (pts[j][0] - p[0]) ** 2 + (pts[j][1] - p[1]) ** 2 < limit2:
                        clear = False
                        break
                if not clear:
                    break
            if clear:
                add(p)
                break
        else:
            active[slot] = active[-1]             # retire this point
            active.pop()
    return pts


# ---------------------------------------------------------------------------
# Graphs
# ---------------------------------------------------------------------------
#
# An unweighted graph is {node: [neighbour, ...]}; a weighted one is
# {node: [(neighbour, weight), ...]}. Both are undirected by convention (list
# each edge under both ends; ``edges_to_adj`` and ``edges_to_wadj`` do that),
# though nothing here breaks on a directed graph except ``farthest_pair`` and
# ``connected_components``, which assume the two-way form.

def edges_to_adj(edges: Iterable[Sequence], nodes: Optional[Iterable[Hashable]] = None
                 ) -> Dict[Hashable, List[Hashable]]:
    """Unweighted two-way adjacency from ``(a, b)`` edges (a third item, such
    as a weight, is ignored). ``nodes`` adds nodes that have no edge."""
    adj: Dict[Hashable, List[Hashable]] = {}
    if nodes is not None:
        for n in nodes:
            adj.setdefault(n, [])
    for e in edges:
        adj.setdefault(e[0], []).append(e[1])
        adj.setdefault(e[1], []).append(e[0])
    return adj


def edges_to_wadj(edges: Iterable[Sequence],
                  weight: Optional[Callable[[Hashable, Hashable], float]] = None,
                  nodes: Optional[Iterable[Hashable]] = None
                  ) -> Dict[Hashable, List[Tuple[Hashable, float]]]:
    """Weighted two-way adjacency from ``(a, b)`` or ``(a, b, w)`` edges.
    An edge without ``w`` costs ``weight(a, b)`` if given, else 1.0."""
    adj: Dict[Hashable, List[Tuple[Hashable, float]]] = {}
    if nodes is not None:
        for n in nodes:
            adj.setdefault(n, [])
    for e in edges:
        a, b = e[0], e[1]
        w = float(e[2]) if len(e) > 2 else (float(weight(a, b)) if weight else 1.0)
        adj.setdefault(a, []).append((b, w))
        adj.setdefault(b, []).append((a, w))
    return adj


def dijkstra(adj: Mapping[Hashable, Iterable[Tuple[Hashable, float]]],
             source: Hashable, target: Optional[Hashable] = None
             ) -> Tuple[Dict[Hashable, float], Dict[Hashable, Hashable]]:
    """Shortest paths from ``source`` over a weighted graph.

    Returns ``(dist, prev)``: ``dist[n]`` is the cost to reach ``n`` (absent if
    unreachable) and ``prev[n]`` the node before it on the way back to the
    source (``unwind_path`` turns that into a route). With ``target`` it stops
    as soon as that node is settled. Weights must not be negative. Ties are
    broken by discovery order, so the result is deterministic.
    """
    best: Dict[Hashable, float] = {source: 0.0}
    prev: Dict[Hashable, Hashable] = {}
    heap: List[Tuple[float, int, Hashable]] = [(0.0, 0, source)]
    tick = 1
    settled = set()
    while heap:
        d, _, u = heapq.heappop(heap)
        if u in settled:
            continue
        settled.add(u)
        if u == target:
            break
        for v, w in adj.get(u, ()):
            if w < 0.0:
                raise ValueError("dijkstra does not accept negative weights")
            nd = d + w
            if v not in best or nd < best[v]:
                best[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, tick, v))
                tick += 1
    return best, prev


def unwind_path(prev: Mapping[Hashable, Hashable], target: Hashable) -> List[Hashable]:
    """The route ``source -> ... -> target`` from a ``dijkstra`` ``prev`` map
    (just ``[target]`` if the target is the source or unreachable)."""
    path = [target]
    while path[-1] in prev:
        path.append(prev[path[-1]])
    path.reverse()
    return path


def shortest_path(adj: Mapping[Hashable, Iterable[Tuple[Hashable, float]]],
                  source: Hashable, target: Hashable) -> Optional[List[Hashable]]:
    """The cheapest route from ``source`` to ``target``, or None if there is none."""
    dist_, prev = dijkstra(adj, source, target)
    return unwind_path(prev, target) if target in dist_ else None


def multi_source_dijkstra(adj: Mapping[Hashable, Iterable[Tuple[Hashable, float]]],
                          sources: Sequence[Hashable]
                          ) -> Tuple[Dict[Hashable, float], Dict[Hashable, Hashable]]:
    """Cheapest cost from the nearest of several sources, and which one.

    Returns ``(dist, owner)``: ``owner[n]`` is the source that reaches ``n``
    most cheaply (the earlier source in ``sources`` wins a tie). Ownership
    regions are what make faction borders and city wards: a border lies where
    the owner changes.
    """
    best: Dict[Hashable, Tuple[float, int]] = {}
    heap: List[Tuple[float, int, int, Hashable]] = []
    tick = 0
    for idx, s in enumerate(sources):
        if s not in best:
            best[s] = (0.0, idx)
            heapq.heappush(heap, (0.0, idx, tick, s))
            tick += 1
    while heap:
        d, idx, _, u = heapq.heappop(heap)
        if best[u] != (d, idx):
            continue                                  # a better claim arrived later
        for v, w in adj.get(u, ()):
            if w < 0.0:
                raise ValueError("multi_source_dijkstra does not accept negative weights")
            cand = (d + w, idx)
            if v not in best or cand < best[v]:
                best[v] = cand
                heapq.heappush(heap, (cand[0], idx, tick, v))
                tick += 1
    return ({n: b[0] for n, b in best.items()},
            {n: sources[b[1]] for n, b in best.items()})


def bfs_reachable(adj: Mapping[Hashable, Iterable[Hashable]],
                  source: Hashable) -> Dict[Hashable, int]:
    """Every node reachable from ``source`` mapped to its hop count (the
    source itself is 0). Iterates in breadth-first order; ``n in result``
    answers "is it reachable"."""
    hops: Dict[Hashable, int] = {source: 0}
    queue = deque([source])
    while queue:
        u = queue.popleft()
        for v in adj.get(u, ()):
            if v not in hops:
                hops[v] = hops[u] + 1
                queue.append(v)
    return hops


def connected_components(adj: Mapping[Hashable, Iterable[Hashable]]
                         ) -> List[List[Hashable]]:
    """The connected pieces of a two-way graph, each as a list of nodes in
    breadth-first order, ordered by the first node of each in ``adj``. Nodes
    that only appear as somebody's neighbour count too."""
    seen = set()
    out: List[List[Hashable]] = []
    order = list(adj)
    for nbrs in adj.values():
        order.extend(nbrs)
    for start in order:
        if start in seen:
            continue
        comp = list(bfs_reachable(adj, start))
        seen.update(comp)
        out.append(comp)
    return out


def farthest_pair(adj: Mapping[Hashable, Iterable[Hashable]]
                  ) -> Optional[Tuple[Hashable, Hashable]]:
    """Two nodes as many hops apart as possible: a dungeon's entrance and
    exit, the two ends of a journey. Exact (a breadth-first search from every
    node) for up to 250 nodes, else the two-sweep estimate, which is exact on
    trees. For a disconnected graph only nodes in the same piece are paired.
    Returns ``(a, b)`` or None for an empty graph; ``a == b`` for one node.
    Ties go to the pair found first, so the answer is deterministic.
    """
    nodes: List[Hashable] = []
    known = set()
    for n in adj:
        for m in (n, *adj[n]):
            if m not in known:
                known.add(m)
                nodes.append(m)
    if not nodes:
        return None
    if len(nodes) > 250:
        far = list(bfs_reachable(adj, nodes[0]))[-1]
        return far, list(bfs_reachable(adj, far))[-1]
    best_pair: Tuple[Hashable, Hashable] = (nodes[0], nodes[0])
    best_hops = -1
    for a in nodes:
        for b, h in bfs_reachable(adj, a).items():
            if h > best_hops:
                best_hops, best_pair = h, (a, b)
    return best_pair


def mst(points: Sequence[Point],
        metric: Optional[Callable[[Point, Point], float]] = None
        ) -> List[Tuple[int, int]]:
    """Minimum spanning tree of the complete graph on ``points`` (Prim, O(n^2)).

    Returns ``n - 1`` edges as ``(i, j)`` index pairs with ``i < j`` in the
    order they join the tree, starting from point 0; ties go to the lower
    index. ``metric(p, q)`` replaces the straight-line distance (for lane
    costs or hex distance). The tree is what makes a level or a sector
    connected by construction.
    """
    n = len(points)
    if n < 2:
        return []
    d = metric or dist
    in_tree = [False] * n
    best = [math.inf] * n
    parent = [-1] * n
    best[0] = 0.0
    edges: List[Tuple[int, int]] = []
    for _ in range(n):
        u, ub = -1, math.inf
        for v in range(n):
            if not in_tree[v] and best[v] < ub:
                u, ub = v, best[v]
        in_tree[u] = True
        if parent[u] >= 0:
            edges.append((min(parent[u], u), max(parent[u], u)))
        for v in range(n):
            if not in_tree[v]:
                w = d(points[u], points[v])
                if w < best[v]:
                    best[v], parent[v] = w, u
    return edges


def gabriel_edges(points: Sequence[Point]) -> List[Tuple[int, int]]:
    """The Gabriel graph: ``(i, j)`` (``i < j``) is an edge when no other
    point lies inside the circle whose diameter is the segment between them.

    A sparse, natural-looking network that always contains the minimum
    spanning tree, so it is a good pool of "extra lanes / loops" to draw from
    once the tree guarantees connection. A point exactly on the circle does
    not block the edge.
    """
    n = len(points)
    edges: List[Tuple[int, int]] = []
    for i in range(n):
        pi = points[i]
        near = sorted(((points[k][0] - pi[0]) ** 2 + (points[k][1] - pi[1]) ** 2, k)
                      for k in range(n) if k != i)
        for d2ij, j in near:
            if j < i:
                continue
            pj = points[j]
            slack = 1e-9 * max(1.0, d2ij)
            clear = True
            for d2ik, k in near:
                if d2ik >= d2ij:
                    break                     # only points nearer to i than j can be inside
                if k == j:
                    continue
                pk = points[k]
                if (pi[0] - pk[0]) * (pj[0] - pk[0]) + (pi[1] - pk[1]) * (pj[1] - pk[1]) < -slack:
                    clear = False
                    break
            if clear:
                edges.append((i, j))
    return edges


# ---------------------------------------------------------------------------
# Rectangles and grids
# ---------------------------------------------------------------------------

def bsp_split(rect: Rect, rng: random.Random, min_leaf: float,
              ratio_range: Tuple[float, float] = (0.35, 0.65),
              max_leaf: Optional[float] = None, integer: bool = False) -> List[Rect]:
    """Binary space partition: cut ``rect`` into leaf rectangles.

    A rectangle is cut across its longer side (either, at random, when it is
    nearly square) at a fraction of its length drawn from ``ratio_range``,
    then each half is cut in turn. Every leaf is at least ``min_leaf`` on
    both sides; a rectangle is left whole once it cannot be cut that way, or
    once both its sides are at most ``max_leaf`` (leave it None to cut down
    as far as ``min_leaf`` allows). With ``integer=True`` every cut lands on
    a whole number, for grid maps. The leaves tile ``rect`` exactly and come
    out in a fixed order for a given ``rng``.
    """
    if min_leaf <= 0.0:
        raise ValueError("bsp_split needs a positive min_leaf")
    lo_r, hi_r = ratio_range
    out: List[Rect] = []
    stack: List[Rect] = [(float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))]

    def cut_range(a: float, b: float) -> Optional[Tuple[float, float]]:
        lo, hi = a + min_leaf, b - min_leaf
        if integer:
            lo, hi = math.ceil(lo - EPS), math.floor(hi + EPS)
        return (lo, hi) if lo <= hi + EPS else None

    while stack:
        x0, y0, x1, y1 = stack.pop()
        w, h = x1 - x0, y1 - y0
        cx, cy = cut_range(x0, x1), cut_range(y0, y1)
        if max_leaf is not None and w <= max_leaf and h <= max_leaf:
            cx = cy = None
        if cx is None and cy is None:
            out.append((x0, y0, x1, y1))
            continue
        if cx is not None and cy is not None:
            if w > 1.25 * h:
                across_x = True
            elif h > 1.25 * w:
                across_x = False
            else:
                across_x = rng.random() < 0.5
        else:
            across_x = cx is not None
        ratio = rng.uniform(lo_r, hi_r)
        if across_x:
            lo, hi = cx
            cut = min(max(x0 + w * ratio, lo), hi)
            if integer:
                cut = min(max(float(round(cut)), lo), hi)
            stack.append((cut, y0, x1, y1))
            stack.append((x0, y0, cut, y1))
        else:
            lo, hi = cy
            cut = min(max(y0 + h * ratio, lo), hi)
            if integer:
                cut = min(max(float(round(cut)), lo), hi)
            stack.append((x0, cut, x1, y1))
            stack.append((x0, y0, x1, cut))
    return out


def _worst_ratio(row: Sequence[float], side: float) -> float:
    """Worst aspect ratio in a treemap row laid along a side of length ``side``."""
    total = sum(row)
    lo = min(row)
    if lo <= 0.0 or total <= 0.0:
        return math.inf
    return max(side * side * max(row) / (total * total),
               total * total / (side * side * lo))


def squarify(items: Sequence[Tuple[Hashable, float]], rect: Rect
             ) -> Dict[Hashable, Rect]:
    """Squarified treemap: fill ``rect`` with one rectangle per item, each as
    close to square as the areas allow (Bruls, Huizing and van Wijk).

    ``items`` is ``[(key, area), ...]``; the result maps each key to its
    rectangle, in the same order as ``items``. Requested areas are scaled by
    one common factor so the rectangles fill ``rect`` exactly (when they
    already add up to its area, nothing is scaled and each rectangle has the
    area asked for). A zero-area item gets a zero-size rectangle. Keys must
    be distinct; areas must not be negative.
    """
    x0, y0, x1, y1 = rect
    keys = [k for k, _ in items]
    if len(set(keys)) != len(keys):
        raise ValueError("squarify keys must be distinct")
    areas = [float(a) for _, a in items]
    if any(a < 0.0 for a in areas):
        raise ValueError("squarify areas must not be negative")
    if not items:
        return {}
    total = sum(areas)
    if total <= 0.0 or x1 - x0 <= 0.0 or y1 - y0 <= 0.0:
        return {k: (x0, y0, x0, y0) for k in keys}
    scale = (x1 - x0) * (y1 - y0) / total
    order = sorted(range(len(items)), key=lambda i: (-areas[i], i))
    scaled = [areas[i] * scale for i in order]
    placed: Dict[Hashable, Rect] = {}
    n = len(order)
    start = 0
    while start < n:
        fw, fh = x1 - x0, y1 - y0
        if scaled[start] <= 0.0:                    # only zero-area items are left
            for j in range(start, n):
                placed[keys[order[j]]] = (x0, y0, x0, y0)
            break
        side = min(fw, fh)
        end = start + 1
        current = _worst_ratio(scaled[start:end], side)
        while end < n:
            trial = _worst_ratio(scaled[start:end + 1], side)
            if trial > current:
                break
            end, current = end + 1, trial
        row_sum = sum(scaled[start:end])
        if end == n:                                # last row takes what is left
            strip = fw if fw >= fh else fh
        elif fw >= fh:
            strip = row_sum / fh                    # a column on the left
        else:
            strip = row_sum / fw                    # a band along the top
        if fw >= fh:
            y = y0
            for j in range(start, end):
                nxt = y1 if j == end - 1 else y + scaled[j] / strip
                placed[keys[order[j]]] = (x0, y, x0 + strip, nxt)
                y = nxt
            x0 += strip
        else:
            x = x0
            for j in range(start, end):
                nxt = x1 if j == end - 1 else x + scaled[j] / strip
                placed[keys[order[j]]] = (x, y0, nxt, y0 + strip)
                x = nxt
            y0 += strip
        start = end
    return {k: placed[k] for k in keys}


def shared_walls(rects: Sequence[Rect], min_len: float = 0.0, tol: float = 1e-6
                 ) -> Dict[Tuple[int, int], Tuple[Point, Point]]:
    """Which axis-aligned rectangles share a wall, and where.

    Returns ``{(i, j): (p, q)}`` with ``i < j`` for every pair whose edges
    lie along a common line and overlap for at least ``min_len``; ``p`` to
    ``q`` is the shared stretch (left to right, or bottom to top). Corner
    contact does not count. Feed ``result`` keys to ``edges_to_adj`` for the
    room graph, and put doors on the stretch (keep ``min_len`` at least a
    door's width plus its margins so a door always fits).
    """
    out: Dict[Tuple[int, int], Tuple[Point, Point]] = {}
    n = len(rects)
    for i in range(n):
        ax0, ay0, ax1, ay1 = rects[i]
        for j in range(i + 1, n):
            bx0, by0, bx1, by1 = rects[j]
            if abs(ax1 - bx0) <= tol or abs(bx1 - ax0) <= tol:
                x = ax1 if abs(ax1 - bx0) <= tol else ax0
                lo, hi = max(ay0, by0), min(ay1, by1)
                if hi - lo > tol and hi - lo >= min_len - tol:
                    out[(i, j)] = ((x, lo), (x, hi))
                    continue
            if abs(ay1 - by0) <= tol or abs(by1 - ay0) <= tol:
                y = ay1 if abs(ay1 - by0) <= tol else ay0
                lo, hi = max(ax0, bx0), min(ax1, bx1)
                if hi - lo > tol and hi - lo >= min_len - tol:
                    out[(i, j)] = ((lo, y), (hi, y))
    return out


def cells_outline(cells: Iterable[Tuple[int, int]], size: float = 1.0
                  ) -> List[Tuple[Polygon, List[Polygon]]]:
    """Trace a set of grid cells into rectilinear polygons.

    ``cells`` are integer ``(col, row)`` pairs, each the unit square from
    ``(col, row)`` to ``(col + 1, row + 1)`` (scaled by ``size``). Returns one
    ``(outer_ring, [hole_rings, ...])`` per 4-connected group of cells: outer
    rings run counter-clockwise (positive area), holes clockwise, and
    collinear vertices are merged, so a 3x1 strip is a 4-point rectangle.

    Cells that touch only at a corner are not joined: two rooms meeting at a
    corner come out as two shapes. Every ring is a simple polygon (it never
    visits a vertex twice); where one shape wraps round a pocket and touches
    itself at a corner, the pocket becomes a hole whose ring meets the outer
    ring at that corner. Islands inside a hole are their own entries.
    """
    filled = {(int(c), int(r)) for c, r in cells}
    if not filled:
        return []
    edge_cell: Dict[Tuple[Tuple[int, int], Tuple[int, int]], Tuple[int, int]] = {}
    outgoing: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    for (c, r) in sorted(filled):
        sides = (
            ((c, r - 1), (c, r), (c + 1, r)),
            ((c + 1, r), (c + 1, r), (c + 1, r + 1)),
            ((c, r + 1), (c + 1, r + 1), (c, r + 1)),
            ((c - 1, r), (c, r + 1), (c, r)),
        )
        for neighbour, a, b in sides:
            if neighbour not in filled:               # boundary edge, cell on its left
                edge_cell[(a, b)] = (c, r)
                outgoing.setdefault(a, []).append(b)

    def next_edge(a: Tuple[int, int], b: Tuple[int, int]) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        """At b, leaving along an edge that came from a: turn left if you can."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        best, best_rank = None, 9
        for c in outgoing[b]:
            ex, ey = c[0] - b[0], c[1] - b[1]
            turn = dx * ey - dy * ex
            rank = 0 if turn > 0 else (1 if dx * ex + dy * ey > 0 else (2 if turn < 0 else 3))
            if rank < best_rank:
                best, best_rank = c, rank
        return b, best

    rings: List[Tuple[Tuple[int, int], List[Tuple[int, int]]]] = []
    seen = set()
    for edge in sorted(edge_cell):
        if edge in seen:
            continue
        walk: List[Tuple[int, int]] = []
        cur = edge
        while cur not in seen:
            seen.add(cur)
            walk.append(cur[0])
            cur = next_edge(*cur)
        # A shape that wraps round a pocket of empty cells and touches itself
        # at a corner visits that corner twice; cut the walk there so every
        # ring is simple (the pocket becomes a hole that meets the outline
        # at that one corner).
        loops: List[List[Tuple[int, int]]] = []
        stack: List[Tuple[int, int]] = []
        where: Dict[Tuple[int, int], int] = {}
        for v in walk:
            if v in where:
                i = where[v]
                loops.append(stack[i:])
                for w in stack[i + 1:]:
                    del where[w]
                del stack[i + 1:]
            else:
                where[v] = len(stack)
                stack.append(v)
        loops.append(stack)
        for loop in loops:
            pts = []                                  # merge collinear runs
            m = len(loop)
            for i in range(m):
                p, q, s = loop[i - 1], loop[i], loop[(i + 1) % m]
                if (q[0] - p[0]) * (s[1] - q[1]) - (q[1] - p[1]) * (s[0] - q[0]) != 0:
                    pts.append(q)
            rings.append((edge_cell[(loop[0], loop[1])], pts))

    # 4-connected components of the filled cells decide which holes go where
    comp: Dict[Tuple[int, int], int] = {}
    firsts: List[Tuple[int, int]] = []
    for start in sorted(filled, key=lambda cr: (cr[1], cr[0])):
        if start in comp:
            continue
        comp[start] = len(firsts)
        firsts.append(start)
        queue = deque([start])
        while queue:
            c, r = queue.popleft()
            for nb in ((c + 1, r), (c - 1, r), (c, r + 1), (c, r - 1)):
                if nb in filled and nb not in comp:
                    comp[nb] = comp[start]
                    queue.append(nb)
    outers: Dict[int, List[Polygon]] = {i: [] for i in range(len(firsts))}
    holes: Dict[int, List[Polygon]] = {i: [] for i in range(len(firsts))}
    for cell, pts in rings:
        poly = [(float(x * size), float(y * size)) for x, y in pts]
        if polygon_area(poly) > 0.0:
            outers[comp[cell]].append(poly)
        else:
            holes[comp[cell]].append(poly)
    result: List[Tuple[Polygon, List[Polygon]]] = []
    for i in range(len(firsts)):
        hs = sorted(holes[i], key=lambda p: (min(v[1] for v in p), min(v[0] for v in p)))
        for k, outer in enumerate(outers[i]):         # exactly one, by construction
            result.append((outer, hs if k == 0 else []))
    return result


_SQRT3 = math.sqrt(3.0)


def hex_center(col: int, row: int, size: float) -> Point:
    """Centre of a flat-top hexagon in offset coordinates (odd columns sit
    half a hex lower). ``size`` is the centre-to-corner distance."""
    return (size * 1.5 * col, size * _SQRT3 * (row + 0.5 * (col & 1)))


def hex_corners(col: int, row: int, size: float) -> Polygon:
    """The six corners, starting at the right-hand point and turning through
    increasing angle (clockwise on a y-down canvas)."""
    cx, cy = hex_center(col, row, size)
    return [(cx + size * math.cos(math.radians(60 * k)),
             cy + size * math.sin(math.radians(60 * k))) for k in range(6)]


_HEX_STEPS = (
    ((1, 0), (0, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)),      # even columns
    ((1, 1), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, 0)),        # odd columns
)


def hex_neighbors(col: int, row: int) -> List[Tuple[int, int]]:
    """The six adjacent hexes. Neighbour ``k`` is the one across the edge
    between corner ``k`` and corner ``k + 1`` of ``hex_corners``."""
    return [(col + dc, row + dr) for dc, dr in _HEX_STEPS[col & 1]]


def hex_distance(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    """Number of hex steps between two cells (parsecs on a sector map)."""
    def cube(col: int, row: int) -> Tuple[int, int, int]:
        z = row - (col - (col & 1)) // 2
        return col, -col - z, z
    ax, ay, az = cube(*a)
    bx, by, bz = cube(*b)
    return max(abs(ax - bx), abs(ay - by), abs(az - bz))


# ---------------------------------------------------------------------------
# Polylines
# ---------------------------------------------------------------------------

def polyline_length(pts: Sequence[Point], closed: bool = False) -> float:
    """Total length of the path (with the closing edge if ``closed``)."""
    n = len(pts)
    total = sum(dist(pts[i], pts[i + 1]) for i in range(n - 1))
    if closed and n > 1:
        total += dist(pts[-1], pts[0])
    return total


def polyline_cumulative(pts: Sequence[Point], closed: bool = False) -> List[float]:
    """Distance travelled along the path at each vertex: ``[0, d1, d2, ...]``.
    With ``closed`` there is one extra entry, the full perimeter, for the
    return to the first point. Hand it to ``point_at`` to place many points
    on one path without re-measuring it."""
    out = [0.0]
    for i in range(len(pts) - 1):
        out.append(out[-1] + dist(pts[i], pts[i + 1]))
    if closed and len(pts) > 1:
        out.append(out[-1] + dist(pts[-1], pts[0]))
    return out


def point_at(pts: Sequence[Point], distance: float, closed: bool = False,
             cumulative: Optional[Sequence[float]] = None) -> Tuple[Point, float]:
    """The point ``distance`` along the path and the direction of travel there.

    Returns ``(point, tangent_angle)``, the angle in radians as ``atan2(dy,
    dx)`` of the segment the point is on (at a vertex, the segment leaving
    it). An open path clamps ``distance`` to its ends; a closed one wraps
    round. Zero-length segments are skipped. A path with no length answers
    ``(pts[0], 0.0)``. Pass ``cumulative=polyline_cumulative(pts, closed)`` when
    calling repeatedly.
    """
    n = len(pts)
    if n == 0:
        raise ValueError("point_at needs at least one point")
    if n == 1:
        return (pts[0], 0.0)
    cum = cumulative if cumulative is not None else polyline_cumulative(pts, closed)
    total = cum[-1]
    if total <= 0.0:
        return (pts[0], 0.0)
    if closed:
        distance = distance % total
    else:
        distance = 0.0 if distance < 0.0 else total if distance > total else distance
    last = len(cum) - 2                                     # index of the final segment
    i = min(bisect.bisect_right(cum, distance) - 1, last)
    while i > 0 and cum[i + 1] - cum[i] <= 0.0:             # step back off a zero-length end
        i -= 1
    a = pts[i]
    b = pts[(i + 1) % n]
    seg = cum[i + 1] - cum[i]
    if seg <= 0.0:
        return (a, 0.0)
    t = (distance - cum[i]) / seg
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return ((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t),
            math.atan2(b[1] - a[1], b[0] - a[0]))


def chaikin(pts: Sequence[Point], iterations: int = 2, closed: bool = False) -> List[Point]:
    """Chaikin corner cutting: every corner is replaced by two points a
    quarter of the way along each neighbouring segment, ``iterations`` times.
    The curve converges on a smooth quadratic B-spline that stays inside the
    convex hull of the points. An open path keeps its two end points, giving
    ``2n - 2`` points per pass; a closed one gives ``2n``."""
    cur: List[Point] = [(float(x), float(y)) for x, y in pts]
    for _ in range(max(0, iterations)):
        n = len(cur)
        if n < 3:
            break
        out: List[Point] = []
        span = n if closed else n - 1
        for i in range(span):
            p, q = cur[i], cur[(i + 1) % n]
            if closed or i > 0:
                out.append((0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]))
            if closed or i < span - 1:
                out.append((0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]))
        cur = [cur[0]] + out + [cur[-1]] if not closed else out
    return cur


def catmull_rom(pts: Sequence[Point], samples_per_seg: int = 8, closed: bool = False,
                alpha: float = 0.5) -> List[Point]:
    """A smooth curve through every point (Catmull-Rom spline), sampled.

    ``alpha=0.5`` (centripetal) never makes loops or cusps within a segment,
    unlike the uniform variant, so it suits roads and journeys. Returns
    ``(n - 1) * samples_per_seg + 1`` points for an open path (the last one is
    the final input point) and ``n * samples_per_seg`` for a closed one. Every
    input point appears in the output. Consecutive duplicate points are
    dropped first.
    """
    base: List[Point] = []
    for p in pts:
        if not base or dist(p, base[-1]) > EPS:
            base.append((float(p[0]), float(p[1])))
    if closed and len(base) > 1 and dist(base[0], base[-1]) <= EPS:
        base.pop()
    n = len(base)
    samples = max(1, int(samples_per_seg))
    if n < 2:
        return base
    if n == 2 and not closed:
        line = [lerp(base[0], base[1], s / samples) for s in range(samples)]
        return line + [base[1]]                 # the last point exactly, not by rounding
    if closed:
        ext = [base[-1]] + base + [base[0], base[1]]
        segs = n
    else:
        head = (2 * base[0][0] - base[1][0], 2 * base[0][1] - base[1][1])
        tail = (2 * base[-1][0] - base[-2][0], 2 * base[-1][1] - base[-2][1])
        ext = [head] + base + [tail]
        segs = n - 1
    out: List[Point] = []
    for i in range(segs):
        p0, p1, p2, p3 = ext[i], ext[i + 1], ext[i + 2], ext[i + 3]
        t0 = 0.0
        t1 = t0 + dist(p0, p1) ** alpha
        t2 = t1 + dist(p1, p2) ** alpha
        t3 = t2 + dist(p2, p3) ** alpha
        for s in range(samples):
            if s == 0:
                out.append(p1)                      # the knot itself, exactly
                continue
            t = t1 + (t2 - t1) * s / samples

            def mix(a: Point, b: Point, ta: float, tb: float) -> Point:
                w = (t - ta) / (tb - ta)
                return (a[0] + (b[0] - a[0]) * w, a[1] + (b[1] - a[1]) * w)

            a1, a2, a3 = mix(p0, p1, t0, t1), mix(p1, p2, t1, t2), mix(p2, p3, t2, t3)
            b1, b2 = mix(a1, a2, t0, t2), mix(a2, a3, t1, t3)
            out.append(mix(b1, b2, t1, t2))
    if not closed:
        out.append(base[-1])
    return out


def simplify(pts: Sequence[Point], tolerance: float) -> List[Point]:
    """Douglas-Peucker: drop points until none is more than ``tolerance`` from
    the simplified path. The end points are always kept, and every original
    point lies within ``tolerance`` of the result. For a ring, pass
    ``ring + [ring[0]]`` and drop the last point of the answer."""
    n = len(pts)
    if n < 3:
        return list(pts)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        lo, hi = stack.pop()
        a, b = pts[lo], pts[hi]
        far, far_i = -1.0, -1
        for i in range(lo + 1, hi):
            d = point_segment_distance(pts[i], a, b)
            if d > far:
                far, far_i = d, i
        if far > tolerance:
            keep[far_i] = True
            stack.append((lo, far_i))
            stack.append((far_i, hi))
    return [p for p, k in zip(pts, keep) if k]


def resample(pts: Sequence[Point], step: float, closed: bool = False) -> List[Point]:
    """Points spaced ``step`` apart *along* the path, starting at its first
    point. An open path also ends at its last point (the final gap may be
    shorter); a closed one does not repeat its start. Use it to put arrows or
    day markers on a route at even intervals."""
    if step <= 0.0:
        raise ValueError("resample needs a positive step")
    n = len(pts)
    if n < 2:
        return [(float(x), float(y)) for x, y in pts]
    cum = polyline_cumulative(pts, closed)
    total = cum[-1]
    if total <= 0.0:
        return [pts[0]]
    out: List[Point] = []
    k = 0
    while k * step < total - EPS:
        out.append(point_at(pts, k * step, closed, cum)[0])
        k += 1
    if not closed:
        out.append((float(pts[-1][0]), float(pts[-1][1])))
    return out
