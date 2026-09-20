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
    of the original (inside for an inset, containing it for an offset), and
    nowhere closer to the original outline than ``d``. The closest approach
    of two polygons that do not cross is always between a vertex of one and
    an edge of the other, so testing those pairs is exact.
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
            if compactness(piece) < min_compact:
                ok = False
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
    under ``min_compactness``). Pieces are only split while their area is at
    least twice ``min_area``, so lots land between ``min_area`` and roughly
    three times it.

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


# @@APPEND@@
