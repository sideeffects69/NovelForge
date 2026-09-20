"""
The shared geometry kit (novelforge/mapkit.py), tested without a window.

Every generator in release 2.3 (dungeon, floor plan, city, castle, sector,
journey, realms) stands on these functions, so what is checked here is the
*property* each generator relies on - lots inside their block and never
overlapping, cells that tile their box, graphs that stay connected - over
hundreds of random inputs, not a couple of hand-picked shapes. Several checks
use their own arithmetic (a separating-axis test, brute-force nearest site, a
half-plane test) rather than the kit's, so a bug in the kit cannot excuse
itself.

No tkinter, no Pillow: the whole module runs in a few seconds.
"""

import math
import os
import random
import subprocess
import sys
import time
import unittest
import zlib

from novelforge import mapkit as mk


# ---------------------------------------------------------------------------
# Test-only helpers (deliberately independent of the code under test)
# ---------------------------------------------------------------------------

def shoelace(poly):
    """Signed area, written out again here so tests do not lean on the kit."""
    s = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def random_convex(rng, cx=0.0, cy=0.0, radius=100.0, n=None):
    """A convex polygon (counter-clockwise) inscribed in a circle.

    Arcs between neighbouring vertices stay under about 95 degrees, so every
    interior angle is at least about 85 degrees - the tests can then say that
    an angle below the minimum was made by a cut, not inherited.
    """
    n = n or rng.randint(5, 9)
    base = 2 * math.pi / n
    start = rng.uniform(0, 2 * math.pi)
    angles = []
    a = start
    for _ in range(n):
        angles.append(a)
        a += base * rng.uniform(0.75, 1.25)
    scale = 2 * math.pi / (a - start)          # close the circle exactly
    angles = [start + (t - start) * scale for t in angles]
    r = radius * rng.uniform(0.5, 1.0)
    return [(cx + r * math.cos(t), cy + r * math.sin(t)) for t in angles]


def random_star(rng, cx=0.0, cy=0.0, radius=100.0, n=None):
    """A simple, usually concave polygon: one vertex per angle around a centre
    with a random radius (star-shaped, so never self-intersecting)."""
    n = n or rng.randint(6, 14)
    start = rng.uniform(0, 2 * math.pi)
    step = 2 * math.pi / n
    pts = []
    for k in range(n):
        # angles stay in order with gaps well under 180 degrees, so the
        # polygon is star-shaped around (cx, cy) and cannot cross itself
        t = start + (k + rng.uniform(-0.3, 0.3)) * step
        r = radius * rng.uniform(0.45, 1.0)
        pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return pts


def convex_overlap(a, b, depth=1e-6):
    """Separating-axis test for two convex polygons: do they overlap by more
    than ``depth``? (Touching along an edge is not an overlap.)"""
    for poly in (a, b):
        for i in range(len(poly)):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % len(poly)]
            nx, ny = y1 - y0, x0 - x1
            length = math.hypot(nx, ny)
            if length == 0:
                continue
            nx, ny = nx / length, ny / length
            pa = [nx * x + ny * y for x, y in a]
            pb = [nx * x + ny * y for x, y in b]
            if min(pa) >= max(pb) - depth or min(pb) >= max(pa) - depth:
                return False                  # a separating axis exists
    return True


def inside_convex(poly, pt, tol=1e-7):
    """Inside-or-on a counter-clockwise convex polygon, by half-planes."""
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        length = math.hypot(x1 - x0, y1 - y0)
        if ((x1 - x0) * (pt[1] - y0) - (y1 - y0) * (pt[0] - x0)) / length < -tol:
            return False
    return True


def interior_angles(poly):
    """Interior angle at every vertex in degrees (unsigned; convex input)."""
    out = []
    n = len(poly)
    for i in range(n):
        p, q, r = poly[i - 1], poly[i], poly[(i + 1) % n]
        ux, uy = p[0] - q[0], p[1] - q[1]
        vx, vy = r[0] - q[0], r[1] - q[1]
        c = (ux * vx + uy * vy) / (math.hypot(ux, uy) * math.hypot(vx, vy))
        out.append(math.degrees(math.acos(max(-1.0, min(1.0, c)))))
    return out


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

class Seeding(unittest.TestCase):
    def test_stable_seed_is_a_fixed_number_in_every_process(self):
        # Literals, so a change to the recipe (or a switch to hash()) is loud.
        self.assertEqual(mk.stable_seed(7, "walls"), 3702061753)
        self.assertEqual(mk.stable_seed("city", 12, "river", 3), 3756073603)
        self.assertEqual(mk.stable_seed(7, "walls"), zlib.crc32(b"7:walls"))

    def test_stable_seed_ignores_the_hash_salt_of_another_process(self):
        env = dict(os.environ, PYTHONHASHSEED="12345")
        code = ("from novelforge import mapkit as m;"
                "print(m.stable_seed('Ashfall', 4, 'roads'))")
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = subprocess.run([sys.executable, "-c", code], cwd=here, env=env,
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(int(out.stdout.strip()), mk.stable_seed("Ashfall", 4, "roads"))

    def test_sub_rng_is_repeatable_and_stages_are_independent(self):
        a, b = mk.sub_rng(99, "walls"), mk.sub_rng(99, "walls")
        self.assertEqual([a.random() for _ in range(5)],
                         [b.random() for _ in range(5)])
        streets_alone = mk.sub_rng(99, "streets").random()
        walls = mk.sub_rng(99, "walls")
        for _ in range(50):                    # spend a whole stage...
            walls.random()
        # ...and another stage still starts from the same place
        self.assertEqual(mk.sub_rng(99, "streets").random(), streets_alone)
        self.assertNotEqual(mk.sub_rng(99, "walls").random(), streets_alone)
        self.assertNotEqual(mk.sub_rng(1, "walls").random(),
                            mk.sub_rng(2, "walls").random())


# ---------------------------------------------------------------------------
# Polygon basics
# ---------------------------------------------------------------------------

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
L_SHAPE = [(0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (10.0, 10.0),
           (10.0, 20.0), (0.0, 20.0)]


class PolygonBasics(unittest.TestCase):
    def test_area_sign_and_size(self):
        self.assertAlmostEqual(mk.polygon_area(SQUARE), 100.0)
        self.assertAlmostEqual(mk.polygon_area(SQUARE[::-1]), -100.0)
        self.assertAlmostEqual(mk.polygon_area(L_SHAPE), 300.0)
        self.assertEqual(mk.polygon_area([(0, 0), (1, 1)]), 0.0)

    def test_area_matches_the_shoelace_and_ignores_translation(self):
        rng = random.Random(1)
        for _ in range(120):
            poly = random_star(rng)
            self.assertAlmostEqual(mk.polygon_area(poly), shoelace(poly), places=6)
            moved = [(x + 5000.0, y - 3000.0) for x, y in poly]
            self.assertAlmostEqual(mk.polygon_area(moved), shoelace(poly), places=4)

    def test_centroid(self):
        self.assertEqual(mk.polygon_centroid(SQUARE), (5.0, 5.0))
        tri = [(0.0, 0.0), (6.0, 0.0), (0.0, 9.0)]
        cx, cy = mk.polygon_centroid(tri)
        self.assertAlmostEqual(cx, 2.0)
        self.assertAlmostEqual(cy, 3.0)
        # the L's centre of mass is off the middle of its box, toward the corner
        lx, ly = mk.polygon_centroid(L_SHAPE)
        self.assertAlmostEqual(lx, ly)
        self.assertLess(lx, 10.0)

    def test_centroid_of_a_convex_polygon_is_inside_it(self):
        rng = random.Random(2)
        for _ in range(150):
            poly = random_convex(rng, rng.uniform(-50, 50), rng.uniform(-50, 50))
            c = mk.polygon_centroid(poly)
            self.assertTrue(inside_convex(poly, c))

    def test_winding_helpers(self):
        self.assertTrue(mk.is_ccw(SQUARE))
        self.assertFalse(mk.is_ccw(SQUARE[::-1]))
        self.assertEqual(mk.ensure_ccw(SQUARE[::-1]), SQUARE[::-1][::-1])
        self.assertEqual(mk.ensure_ccw(SQUARE), SQUARE)
        original = SQUARE[::-1]
        mk.ensure_ccw(original)
        self.assertEqual(original, SQUARE[::-1])        # the input is not changed

    def test_bbox_and_edges(self):
        self.assertEqual(mk.polygon_bbox(L_SHAPE), (0.0, 0.0, 20.0, 20.0))
        edges = mk.polygon_edges(SQUARE)
        self.assertEqual(len(edges), 4)
        self.assertEqual(edges[-1], ((0.0, 10.0), (0.0, 0.0)))     # closing edge

    def test_point_in_polygon_matches_half_planes_on_convex_polygons(self):
        rng = random.Random(3)
        checked = 0
        for _ in range(150):
            poly = random_convex(rng)
            for _ in range(15):
                p = (rng.uniform(-120, 120), rng.uniform(-120, 120))
                if abs(mk.distance_to_boundary(p, poly)) < 1e-6:
                    continue                    # boundary points may go either way
                self.assertEqual(mk.point_in_polygon(p, poly),
                                 inside_convex(poly, p, tol=0.0), (poly, p))
                checked += 1
        self.assertGreater(checked, 1500)

    def test_point_in_polygon_handles_concave_shapes(self):
        self.assertTrue(mk.point_in_polygon((5, 15), L_SHAPE))
        self.assertTrue(mk.point_in_polygon((15, 5), L_SHAPE))
        self.assertFalse(mk.point_in_polygon((15, 15), L_SHAPE))    # the notch
        self.assertFalse(mk.point_in_polygon((-1, 5), L_SHAPE))

    def test_distance_helpers(self):
        self.assertAlmostEqual(mk.point_segment_distance((5, 3), (0, 0), (10, 0)), 3.0)
        self.assertAlmostEqual(mk.point_segment_distance((-3, 4), (0, 0), (10, 0)), 5.0)
        self.assertAlmostEqual(mk.point_segment_distance((1, 1), (2, 2), (2, 2)),
                               math.sqrt(2))
        self.assertAlmostEqual(mk.distance_to_boundary((5, 4), SQUARE), 4.0)
        self.assertAlmostEqual(mk.distance_to_boundary((15, 15), L_SHAPE), 5.0)

    def test_segments_intersect(self):
        f = mk.segments_intersect
        self.assertTrue(f((0, 0), (10, 10), (0, 10), (10, 0)))          # X
        self.assertFalse(f((0, 0), (4, 4), (5, 5), (9, 9)))             # collinear, apart
        self.assertTrue(f((0, 0), (6, 6), (5, 5), (9, 9)))              # collinear overlap
        self.assertFalse(f((0, 0), (10, 0), (0, 1), (10, 1)))           # parallel
        self.assertTrue(f((0, 0), (10, 0), (10, 0), (10, 5)))           # shared end
        self.assertTrue(f((0, 0), (10, 0), (5, 0), (5, 5)))             # T junction
        self.assertFalse(f((0, 0), (10, 0), (5, 1), (5, 5)))            # stops short
        # touching=False counts only genuine crossings
        self.assertFalse(f((0, 0), (10, 0), (10, 0), (10, 5), touching=False))
        self.assertFalse(f((0, 0), (10, 0), (5, 0), (5, 5), touching=False))
        self.assertTrue(f((0, 0), (10, 10), (0, 10), (10, 0), touching=False))

    def test_segments_intersect_agrees_with_a_brute_force_sampler(self):
        rng = random.Random(4)
        for _ in range(300):
            a, b, c, d = [(rng.uniform(0, 10), rng.uniform(0, 10)) for _ in range(4)]
            # parametric solve, written independently
            rx, ry = b[0] - a[0], b[1] - a[1]
            sx, sy = d[0] - c[0], d[1] - c[1]
            den = rx * sy - ry * sx
            if abs(den) < 1e-6:
                continue
            t = ((c[0] - a[0]) * sy - (c[1] - a[1]) * sx) / den
            u = ((c[0] - a[0]) * ry - (c[1] - a[1]) * rx) / den
            expected = 0 < t < 1 and 0 < u < 1
            if min(abs(t), abs(1 - t), abs(u), abs(1 - u)) < 1e-6:
                continue
            self.assertEqual(mk.segments_intersect(a, b, c, d), expected)

    def test_simple_polygons(self):
        self.assertTrue(mk.polygon_is_simple(SQUARE))
        self.assertTrue(mk.polygon_is_simple(L_SHAPE))
        rng = random.Random(5)
        for _ in range(150):
            self.assertTrue(mk.polygon_is_simple(random_star(rng)))
            self.assertTrue(mk.polygon_is_simple(random_convex(rng)))

    def test_not_simple_polygons(self):
        bowtie = [(0, 0), (10, 10), (10, 0), (0, 10)]
        self.assertFalse(mk.polygon_is_simple(bowtie))
        self.assertFalse(mk.polygon_is_simple([(0, 0), (5, 0)]))            # too few
        self.assertFalse(mk.polygon_is_simple([(0, 0), (5, 0), (10, 0)]))   # no area
        self.assertFalse(mk.polygon_is_simple(SQUARE + [SQUARE[-1]]))       # repeated vertex
        # an edge that folds straight back over its neighbour
        self.assertFalse(mk.polygon_is_simple([(0, 0), (10, 0), (5, 0), (5, 8)]))
        # a vertex pinched onto another edge
        pinched = [(0, 0), (10, 0), (10, 10), (5, 0), (0, 10)]
        self.assertFalse(mk.polygon_is_simple(pinched))

    def test_convexity(self):
        self.assertTrue(mk.is_convex(SQUARE))
        self.assertTrue(mk.is_convex(SQUARE[::-1]))
        self.assertFalse(mk.is_convex(L_SHAPE))
        star = [(math.cos(k * 4 * math.pi / 5), math.sin(k * 4 * math.pi / 5))
                for k in range(5)]                                   # pentagram
        self.assertFalse(mk.is_convex(star))
        rng = random.Random(6)
        for _ in range(100):
            self.assertTrue(mk.is_convex(random_convex(rng)))

    def test_polygon_contains_polygon(self):
        inner = [(2, 2), (8, 2), (8, 8), (2, 8)]
        self.assertTrue(mk.polygon_contains_polygon(SQUARE, inner))
        self.assertTrue(mk.polygon_contains_polygon(SQUARE, SQUARE))         # touching
        self.assertFalse(mk.polygon_contains_polygon(SQUARE, [(5, 5), (15, 5), (15, 8)]))
        # both vertices are in the L, but the edge between them crosses the notch
        self.assertFalse(mk.polygon_contains_polygon(
            L_SHAPE, [(2, 19), (19, 2), (19, 4)]))
        self.assertTrue(mk.polygon_contains_polygon(L_SHAPE, [(2, 2), (18, 2), (18, 8)]))


# @@TESTS@@
