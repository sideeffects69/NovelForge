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


# ---------------------------------------------------------------------------
# Polygon operations
# ---------------------------------------------------------------------------

def regular(n, radius, cx=0.0, cy=0.0, phase=0.3):
    return [(cx + radius * math.cos(phase + 2 * math.pi * k / n),
             cy + radius * math.sin(phase + 2 * math.pi * k / n)) for k in range(n)]


def min_edge_distance(convex_ccw, p):
    """Distance from an inside point to the outline of a convex CCW polygon,
    the long way round (half-plane distances), independent of the kit."""
    best = float("inf")
    for i in range(len(convex_ccw)):
        x0, y0 = convex_ccw[i]
        x1, y1 = convex_ccw[(i + 1) % len(convex_ccw)]
        best = min(best, ((x1 - x0) * (p[1] - y0) - (y1 - y0) * (p[0] - x0))
                   / math.hypot(x1 - x0, y1 - y0))
    return best


class Clipping(unittest.TestCase):
    def test_halfplane_splits_a_square_in_two(self):
        left = mk.clip_halfplane(SQUARE, (5, 0), (5, 10), keep_left=True)
        right = mk.clip_halfplane(SQUARE, (5, 0), (5, 10), keep_left=False)
        self.assertAlmostEqual(abs(shoelace(left)), 50.0)
        self.assertAlmostEqual(abs(shoelace(right)), 50.0)
        # walking up the line x = 5, "left" is the side with smaller x
        self.assertTrue(all(x <= 5 + 1e-9 for x, _ in left))
        self.assertTrue(all(x >= 5 - 1e-9 for x, _ in right))
        # a line that misses the polygon keeps all of it or none of it
        self.assertEqual(mk.clip_halfplane(SQUARE, (20, 0), (20, 10), keep_left=True),
                         SQUARE)
        self.assertEqual(mk.clip_halfplane(SQUARE, (20, 0), (20, 10), keep_left=False), [])

    def test_the_two_halves_of_any_convex_polygon_add_up(self):
        rng = random.Random(10)
        for _ in range(150):
            poly = random_convex(rng)
            a = (rng.uniform(-80, 80), rng.uniform(-80, 80))
            b = (a[0] + rng.uniform(-1, 1) + 0.01, a[1] + rng.uniform(-1, 1))
            l = mk.clip_halfplane(poly, a, b, True)
            r = mk.clip_halfplane(poly, a, b, False)
            self.assertAlmostEqual(abs(shoelace(l)) + abs(shoelace(r)),
                                   abs(shoelace(poly)), places=6)
            for piece in (l, r):
                for v in piece:
                    self.assertTrue(inside_convex(poly, v, tol=1e-6))

    def test_halfplane_keeps_the_side_it_is_asked_to(self):
        rng = random.Random(11)
        for _ in range(120):
            poly = random_convex(rng)
            t = rng.uniform(0, 6.28)
            a, b = (0.0, 0.0), (math.cos(t), math.sin(t))
            for keep_left in (True, False):
                for v in mk.clip_halfplane(poly, a, b, keep_left):
                    side = b[0] * v[1] - b[1] * v[0]        # cross(b, v) from origin
                    self.assertTrue(side >= -1e-7 if keep_left else side <= 1e-7)

    def test_halfplane_of_a_concave_polygon_keeps_the_area(self):
        # cut the L through the notch: both sides together still make the L
        l = mk.clip_halfplane(L_SHAPE, (15, 0), (15, 20), True)
        r = mk.clip_halfplane(L_SHAPE, (15, 0), (15, 20), False)
        self.assertAlmostEqual(abs(shoelace(l)) + abs(shoelace(r)), 300.0)

    def test_halfplane_does_not_change_its_input_and_rejects_a_point(self):
        original = list(SQUARE)
        mk.clip_halfplane(SQUARE, (5, 0), (5, 10))
        self.assertEqual(SQUARE, original)
        with self.assertRaises(ValueError):
            mk.clip_halfplane(SQUARE, (1, 1), (1, 1))

    def test_clip_convex_is_the_intersection(self):
        rng = random.Random(12)
        overlapping = 0
        for _ in range(150):
            a = random_convex(rng, rng.uniform(-30, 30), rng.uniform(-30, 30))
            b = random_convex(rng, rng.uniform(-30, 30), rng.uniform(-30, 30))
            ab = mk.clip_convex(a, b)
            ba = mk.clip_convex(b, a)
            self.assertAlmostEqual(abs(shoelace(ab)) if ab else 0.0,
                                   abs(shoelace(ba)) if ba else 0.0, places=5)
            for v in ab:
                self.assertTrue(inside_convex(a, v, 1e-6) and inside_convex(b, v, 1e-6))
            for _ in range(10):
                p = (rng.uniform(-130, 130), rng.uniform(-130, 130))
                if min(abs(min_edge_distance(a, p)), abs(min_edge_distance(b, p))) < 1e-6:
                    continue
                both = inside_convex(a, p) and inside_convex(b, p)
                self.assertEqual(bool(ab) and mk.point_in_polygon(p, ab), both)
            overlapping += bool(ab)
        self.assertGreater(overlapping, 60)         # the test really did overlap shapes

    def test_clip_convex_edge_cases(self):
        big = [(-50, -50), (50, -50), (50, 50), (-50, 50)]
        self.assertAlmostEqual(shoelace(mk.clip_convex(SQUARE, big)), 100.0)
        far = [(100, 100), (110, 100), (110, 110), (100, 110)]
        self.assertEqual(mk.clip_convex(SQUARE, far), [])
        # the clip shape may be wound either way
        self.assertAlmostEqual(abs(shoelace(mk.clip_convex(SQUARE, big[::-1]))), 100.0)


class Insetting(unittest.TestCase):
    def test_square_inset_is_a_smaller_square(self):
        inner = mk.inset_polygon(SQUARE, 2.0)
        self.assertAlmostEqual(shoelace(inner), 36.0)
        self.assertEqual(sorted((round(x, 6), round(y, 6)) for x, y in inner),
                         [(2.0, 2.0), (2.0, 8.0), (8.0, 2.0), (8.0, 8.0)])
        self.assertIsNone(mk.inset_polygon(SQUARE, 5.0))         # exactly gone
        self.assertIsNone(mk.inset_polygon(SQUARE, 5.1))
        self.assertIsNotNone(mk.inset_polygon(SQUARE, 4.9))

    def test_regular_polygons_shrink_exactly(self):
        for n in (3, 4, 5, 6, 8, 12):
            for d in (0.5, 3.0, 9.0):
                poly = regular(n, 20.0)
                apothem = 20.0 * math.cos(math.pi / n)
                inner = mk.inset_polygon(poly, d)
                if d >= apothem:
                    self.assertIsNone(inner)
                    continue
                self.assertAlmostEqual(abs(shoelace(inner)),
                                       abs(shoelace(poly)) * ((apothem - d) / apothem) ** 2,
                                       places=6)

    def test_convex_inset_lies_inside_and_keeps_its_distance(self):
        rng = random.Random(13)
        for _ in range(150):
            poly = random_convex(rng)
            d = rng.uniform(0.5, 25.0)
            inner = mk.inset_polygon(poly, d)
            if inner is None:
                # nothing left means no point is d away from every edge
                c = mk.polygon_centroid(poly)
                self.assertLess(min_edge_distance(poly, c), d + 1e-6)
                continue
            self.assertLess(shoelace(inner), shoelace(poly))
            for v in inner:
                self.assertGreaterEqual(min_edge_distance(poly, v), d - 1e-6)
            self.assertTrue(mk.is_convex(inner))

    def test_a_large_inset_collapses_to_none(self):
        rng = random.Random(14)
        for _ in range(120):
            poly = random_convex(rng)
            self.assertIsNone(mk.inset_polygon(poly, 1000.0))
            self.assertIsNone(mk.inset_polygon(poly, 101.0))   # more than any radius here

    def test_inset_keeps_the_winding_and_zero_returns_a_copy(self):
        cw = SQUARE[::-1]
        inner = mk.inset_polygon(cw, 1.0)
        self.assertLess(shoelace(inner), 0.0)
        self.assertAlmostEqual(abs(shoelace(inner)), 64.0)
        same = mk.inset_polygon(SQUARE, 0.0)
        self.assertEqual(same, SQUARE)
        self.assertIsNot(same, SQUARE)

    def test_concave_inset_of_the_l_shape_is_exact(self):
        inner = mk.inset_polygon(L_SHAPE, 2.0)
        self.assertIsNotNone(inner)
        self.assertAlmostEqual(shoelace(inner), 156.0)
        want = {(2.0, 2.0), (18.0, 2.0), (18.0, 8.0), (8.0, 8.0), (8.0, 18.0), (2.0, 18.0)}
        self.assertEqual({(round(x, 6), round(y, 6)) for x, y in inner}, want)
        # the arm is 10 wide: an inset of 5 or more takes it away entirely
        self.assertIsNone(mk.inset_polygon(L_SHAPE, 5.0))

    def test_concave_inset_is_valid_whenever_it_answers(self):
        rng = random.Random(15)
        answered = 0
        for _ in range(150):
            poly = random_star(rng)
            d = rng.uniform(1.0, 8.0)
            inner = mk.inset_polygon(poly, d)
            if inner is None:
                continue
            answered += 1
            self.assertTrue(mk.polygon_is_simple(inner))
            self.assertGreater(shoelace(inner), 0.0)
            self.assertLess(shoelace(inner), shoelace(poly))
            self.assertTrue(mk.polygon_contains_polygon(poly, inner))
            for v in inner:
                self.assertGreaterEqual(mk.distance_to_boundary(v, poly), d - 1e-6)
            for a, b in mk.polygon_edges(inner):
                for c, e in mk.polygon_edges(poly):
                    self.assertGreaterEqual(
                        min(mk.point_segment_distance(a, c, e),
                            mk.point_segment_distance(b, c, e),
                            mk.point_segment_distance(c, a, b),
                            mk.point_segment_distance(e, a, b)), d - 1e-6)
        self.assertGreater(answered, 90)           # it does answer for ordinary shapes

    def test_negative_inset_grows(self):
        grown = mk.inset_polygon(SQUARE, -1.0)
        self.assertAlmostEqual(shoelace(grown), 144.0)


class Offsetting(unittest.TestCase):
    def test_square_grows_with_sharp_corners(self):
        out = mk.offset_polygon(SQUARE, 2.0)
        self.assertAlmostEqual(shoelace(out), 196.0)
        self.assertEqual(len(out), 4)
        self.assertEqual(mk.offset_polygon(SQUARE, 0.0), SQUARE)

    def test_offset_contains_the_original_and_keeps_its_distance(self):
        rng = random.Random(16)
        for _ in range(150):
            poly = random_convex(rng)
            d = rng.uniform(0.5, 30.0)
            out = mk.offset_polygon(poly, d)
            self.assertGreater(shoelace(out), shoelace(poly))
            self.assertTrue(mk.polygon_is_simple(out))
            self.assertTrue(mk.polygon_contains_polygon(out, poly))
            for v in out:
                self.assertGreaterEqual(mk.distance_to_boundary(v, poly), d - 1e-6)

    def test_offset_then_inset_returns_to_the_start_for_convex_shapes(self):
        rng = random.Random(17)
        for _ in range(100):
            poly = random_convex(rng)
            d = rng.uniform(1.0, 10.0)
            back = mk.inset_polygon(mk.offset_polygon(poly, d, miter_limit=100.0), d)
            self.assertAlmostEqual(shoelace(back), shoelace(poly), places=4)

    def test_sharp_corners_are_bevelled_at_the_miter_limit(self):
        spike = [(0.0, 0.0), (100.0, 0.0), (90.0, 15.0)]         # a corner near 9 degrees
        limit = 2.5
        out = mk.offset_polygon(spike, 5.0, miter_limit=limit)
        self.assertGreater(len(out), 3)
        for v in out:
            self.assertLessEqual(min(mk.dist(v, c) for c in spike), limit * 5.0 + 1e-6)
        loose = mk.offset_polygon(spike, 5.0, miter_limit=1000.0)
        self.assertEqual(len(loose), 3)                          # no bevel
        self.assertGreater(max(min(mk.dist(v, c) for c in spike) for v in loose),
                           limit * 5.0)

    def test_concave_offset_is_always_a_simple_polygon_around_the_original(self):
        rng = random.Random(18)
        for _ in range(150):
            poly = random_star(rng)
            d = rng.uniform(1.0, 60.0)                      # up to "far too much"
            out = mk.offset_polygon(poly, d)
            self.assertTrue(mk.polygon_is_simple(out), (poly, d))
            self.assertTrue(mk.polygon_contains_polygon(out, poly), (poly, d))

    def test_offset_keeps_the_winding_and_a_negative_offset_shrinks(self):
        self.assertLess(shoelace(mk.offset_polygon(SQUARE[::-1], 1.0)), 0.0)
        self.assertAlmostEqual(shoelace(mk.offset_polygon(SQUARE, -1.0)), 64.0)
        self.assertEqual(mk.offset_polygon(SQUARE, -6.0), [])


# @@TESTS@@
