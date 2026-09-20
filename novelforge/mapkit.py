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
"""

from __future__ import annotations

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


# @@APPEND@@
