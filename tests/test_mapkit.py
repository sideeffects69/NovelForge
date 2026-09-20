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


def bbox_overlap(a, b):
    ax0, ay0, ax1, ay1 = mk.polygon_bbox(a)
    bx0, by0, bx1, by1 = mk.polygon_bbox(b)
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


class Bisecting(unittest.TestCase):
    def check_lots(self, poly, lots, min_area, min_angle=25.0):
        """Everything a generator relies on, for convex input."""
        self.assertAlmostEqual(sum(shoelace(l) for l in lots), shoelace(poly), places=5)
        for lot in lots:
            self.assertGreater(shoelace(lot), 0.0)                    # counter-clockwise
            self.assertGreaterEqual(shoelace(lot), min_area - 1e-9)   # big enough
            self.assertTrue(mk.is_convex(lot))
            for v in lot:
                self.assertTrue(inside_convex(poly, v, 1e-6))         # inside the block
            self.assertGreaterEqual(min(interior_angles(lot)), min_angle - 1e-6)
            self.assertGreaterEqual(mk.compactness(lot), 0.2)         # no slivers
        for i in range(len(lots)):
            for j in range(i + 1, len(lots)):
                if bbox_overlap(lots[i], lots[j]):
                    self.assertFalse(convex_overlap(lots[i], lots[j]))

    def test_lots_tile_a_convex_polygon_without_overlap_slivers_or_sharp_corners(self):
        rng = random.Random(20)
        split = 0
        for _ in range(120):
            poly = random_convex(rng)
            min_area = shoelace(poly) / rng.uniform(3, 60)
            lots = mk.bisect_polygon(poly, rng, min_area)
            self.check_lots(poly, lots, min_area)
            split += len(lots) > 1
        self.assertGreater(split, 110)                # nearly every one really was cut

    def test_a_stricter_minimum_angle_is_honoured(self):
        rng = random.Random(21)
        for _ in range(100):
            poly = random_convex(rng)
            min_area = shoelace(poly) / rng.uniform(4, 30)
            lots = mk.bisect_polygon(poly, rng, min_area, min_angle_deg=60.0, jitter=0.4)
            self.check_lots(poly, lots, min_area, min_angle=60.0)

    def test_a_square_block_is_not_cut_into_triangles(self):
        block = [(0.0, 0.0), (200.0, 0.0), (200.0, 140.0), (0.0, 140.0)]
        lots = []
        for seed in range(40):
            lots += mk.bisect_polygon(block, random.Random(seed), 300.0)
        self.assertGreater(len(lots), 2000)
        triangles = sum(1 for l in lots if len(l) == 3)
        self.assertLessEqual(triangles, len(lots) // 100)       # the city article's complaint
        self.assertGreaterEqual(min(min(interior_angles(l)) for l in lots), 25.0 - 1e-6)

    def test_lots_come_out_between_the_minimum_and_about_three_times_it(self):
        block = regular(8, 300.0)
        min_area = 1500.0
        lots = mk.bisect_polygon(block, random.Random(3), min_area)
        areas = [shoelace(l) for l in lots]
        self.assertGreaterEqual(min(areas), min_area - 1e-9)
        self.assertLessEqual(max(areas), 3.5 * min_area)

    def test_concave_polygons_are_tiled_too(self):
        rng = random.Random(22)
        cut = 0
        for _ in range(100):
            poly = random_star(rng)
            min_area = shoelace(poly) / rng.uniform(3, 25)
            lots = mk.bisect_polygon(poly, rng, min_area)
            self.assertAlmostEqual(sum(shoelace(l) for l in lots), shoelace(poly), places=5)
            for lot in lots:
                self.assertTrue(mk.polygon_is_simple(lot))
                self.assertGreaterEqual(shoelace(lot), min_area - 1e-9)
                self.assertTrue(mk.polygon_contains_polygon(poly, lot))
            # every sample point of the polygon belongs to exactly one lot
            for _ in range(15):
                p = (rng.uniform(-100, 100), rng.uniform(-100, 100))
                if not mk.point_in_polygon(p, poly):
                    continue
                if min(mk.distance_to_boundary(p, l) for l in lots) < 1e-6:
                    continue
                self.assertEqual(sum(mk.point_in_polygon(p, l) for l in lots), 1)
            cut += len(lots) > 1
        self.assertGreater(cut, 85)

    def test_the_l_shape_is_split_into_valid_lots(self):
        for seed in range(30):
            lots = mk.bisect_polygon(L_SHAPE, random.Random(seed), 20.0)
            self.assertAlmostEqual(sum(shoelace(l) for l in lots), 300.0, places=6)
            self.assertGreater(len(lots), 4)
            for lot in lots:
                self.assertTrue(mk.polygon_is_simple(lot))
                self.assertTrue(mk.polygon_contains_polygon(L_SHAPE, lot))
                # no lot reaches into the empty notch of the L
                self.assertFalse(mk.point_in_polygon((15.0, 15.0), lot))

    def test_a_polygon_smaller_than_the_minimum_is_one_lot(self):
        lots = mk.bisect_polygon(SQUARE, random.Random(1), 500.0)
        self.assertEqual(lots, [SQUARE])
        self.assertEqual(mk.bisect_polygon([], random.Random(1), 5.0), [])

    def test_the_same_rng_gives_the_same_lots_and_another_gives_others(self):
        poly = regular(7, 120.0)
        a = mk.bisect_polygon(poly, random.Random(5), 400.0)
        b = mk.bisect_polygon(poly, random.Random(5), 400.0)
        c = mk.bisect_polygon(poly, random.Random(6), 400.0)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_the_input_is_not_changed(self):
        poly = regular(6, 90.0)
        before = list(poly)
        mk.bisect_polygon(poly, random.Random(1), 300.0)
        self.assertEqual(poly, before)

    def test_bisecting_a_large_polygon_is_fast(self):
        poly = regular(8, 300.0)
        best = 1e9
        for _ in range(3):
            t = time.perf_counter()
            lots = mk.bisect_polygon(poly, random.Random(1), 1000.0)
            best = min(best, time.perf_counter() - t)
        self.assertGreater(len(lots), 150)
        self.assertLess(best, 0.05)


# ---------------------------------------------------------------------------
# Points and cells
# ---------------------------------------------------------------------------

BOX = (0.0, 0.0, 200.0, 140.0)
SMALL = (0.0, 0.0, 100.0, 70.0)


def random_sites(rng, n, box=BOX, margin=5.0):
    """n well-separated random sites (rejection sampling, so no near-duplicates)."""
    sites = []
    while len(sites) < n:
        p = (rng.uniform(box[0] + margin, box[2] - margin),
             rng.uniform(box[1] + margin, box[3] - margin))
        if all(mk.dist(p, q) > 1.0 for q in sites):
            sites.append(p)
    return sites


class PointsAndCells(unittest.TestCase):
    def test_sunflower_layout(self):
        pts = mk.sunflower(30, 50.0, -20.0, 40.0)
        self.assertEqual(len(pts), 30)
        self.assertEqual(pts[0], (50.0, -20.0))                        # centre first
        self.assertAlmostEqual(mk.dist(pts[-1], (50.0, -20.0)), 40.0)  # rim last
        radii = [mk.dist(p, (50.0, -20.0)) for p in pts]
        self.assertEqual(radii, sorted(radii))                         # index = distance order
        self.assertLessEqual(max(radii), 40.0 + 1e-9)
        # no two points on top of each other: spacing is about radius / sqrt(n)
        closest = min(mk.dist(a, b) for i, a in enumerate(pts) for b in pts[:i])
        self.assertGreater(closest, 0.3 * 40.0 / math.sqrt(30))
        self.assertEqual(mk.sunflower(0), [])
        self.assertEqual(mk.sunflower(1, 3, 4), [(3, 4)])
        self.assertEqual(mk.sunflower(30, 50.0, -20.0, 40.0), pts)      # deterministic
        self.assertNotEqual(mk.sunflower(30, 50.0, -20.0, 40.0, phase=1.0), pts)

    def test_sunflower_stays_evenly_spread_for_any_count(self):
        for n in range(2, 121, 7):
            pts = mk.sunflower(n, 0, 0, 100.0)
            closest = min(mk.dist(a, b) for i, a in enumerate(pts) for b in pts[:i])
            self.assertGreater(closest, 0.25 * 100.0 / math.sqrt(n))

    def test_voronoi_cells_tile_the_box_and_hold_their_sites(self):
        rng = random.Random(30)
        box_area = mk.rect_area(BOX)
        for _ in range(120):
            sites = random_sites(rng, rng.randint(2, 25))
            cells = mk.voronoi_cells(sites, BOX)
            self.assertEqual(len(cells), len(sites))
            self.assertAlmostEqual(sum(shoelace(c) for c in cells), box_area, places=4)
            for site, cell in zip(sites, cells):
                self.assertGreater(shoelace(cell), 0.0)                 # counter-clockwise
                self.assertTrue(mk.is_convex(cell))
                self.assertTrue(inside_convex(cell, site))              # holds its own site
                for v in cell:
                    self.assertTrue(mk.rect_contains(BOX, v, 1e-6))

    def test_every_point_belongs_to_the_cell_of_its_nearest_site(self):
        rng = random.Random(31)
        tested = 0
        for _ in range(100):
            sites = random_sites(rng, rng.randint(3, 20))
            cells = mk.voronoi_cells(sites, BOX)
            for _ in range(15):
                p = (rng.uniform(0, 200), rng.uniform(0, 140))
                ranked = sorted(range(len(sites)), key=lambda i: mk.dist(p, sites[i]))
                if mk.dist(p, sites[ranked[1]]) - mk.dist(p, sites[ranked[0]]) < 1e-6:
                    continue                                         # a tie: on a cell edge
                self.assertTrue(inside_convex(cells[ranked[0]], p, tol=1e-6))
                self.assertFalse(inside_convex(cells[ranked[1]], p, tol=-1e-7))
                tested += 1
        self.assertGreater(tested, 1300)

    def test_voronoi_copes_with_a_regular_grid_of_sites(self):
        sites = [(x * 20.0 + 10.0, y * 20.0 + 10.0) for x in range(10) for y in range(7)]
        cells = mk.voronoi_cells(sites, BOX)
        for cell in cells:
            self.assertAlmostEqual(shoelace(cell), 400.0, places=6)     # 20 x 20 squares
            self.assertEqual(len(cell), 4)

    def test_a_site_outside_the_box_may_have_no_cell(self):
        cells = mk.voronoi_cells([(50.0, 50.0), (150.0, 50.0), (1000.0, 1000.0)], BOX)
        self.assertEqual(cells[2], [])
        self.assertAlmostEqual(shoelace(cells[0]) + shoelace(cells[1]),
                               mk.rect_area(BOX), places=5)

    def test_voronoi_of_forty_sites_is_fast(self):
        sites = random_sites(random.Random(32), 40)
        best = 1e9
        for _ in range(3):
            t = time.perf_counter()
            mk.voronoi_cells(sites, BOX)
            best = min(best, time.perf_counter() - t)
        self.assertLess(best, 0.1)

    def test_lloyd_relaxation_evens_out_the_cells(self):
        rng = random.Random(33)
        better = 0
        trials = 60
        for _ in range(trials):
            sites = random_sites(rng, rng.randint(8, 25))
            relaxed = mk.lloyd_relax(sites, BOX, iterations=4)
            self.assertEqual(len(relaxed), len(sites))
            for p in relaxed:
                self.assertTrue(mk.rect_contains(BOX, p))

            def spread(pts):
                areas = [shoelace(c) for c in mk.voronoi_cells(pts, BOX)]
                mean = sum(areas) / len(areas)
                return math.sqrt(sum((a - mean) ** 2 for a in areas) / len(areas))

            better += spread(relaxed) < spread(sites)
        self.assertGreaterEqual(better, trials - 3)

    def test_lloyd_relaxation_is_deterministic_and_zero_iterations_change_nothing(self):
        sites = random_sites(random.Random(34), 12)
        self.assertEqual(mk.lloyd_relax(sites, BOX, 3), mk.lloyd_relax(sites, BOX, 3))
        self.assertEqual(mk.lloyd_relax(sites, BOX, 0), sites)

    def test_poisson_disc_respects_the_minimum_distance_and_the_box(self):
        rng = random.Random(35)
        for _ in range(120):
            r = rng.uniform(5.0, 20.0)
            pts = mk.poisson_disc(rng, SMALL, r)
            self.assertGreater(len(pts), 3)
            for p in pts:
                self.assertTrue(SMALL[0] <= p[0] < SMALL[2] and SMALL[1] <= p[1] < SMALL[3])
            ordered = sorted(pts)               # sweep by x: only near neighbours matter
            for i, a in enumerate(ordered):
                for b in ordered[i + 1:]:
                    if b[0] - a[0] >= r:
                        break
                    self.assertGreaterEqual(mk.dist(a, b), r - 1e-9)

    def test_poisson_disc_fills_the_box_without_holes(self):
        rng = random.Random(36)
        for _ in range(40):
            r = rng.uniform(6.0, 14.0)
            pts = mk.poisson_disc(rng, SMALL, r)
            # blue noise packs about one point per 1.5 r^2 (edge effects aside)
            self.assertGreater(len(pts), 0.35 * mk.rect_area(SMALL) / (r * r))
            for _ in range(60):
                probe = (rng.uniform(0, 100), rng.uniform(0, 70))
                self.assertLess(min(mk.dist(probe, p) for p in pts), 2.0 * r)

    def test_poisson_disc_is_deterministic(self):
        a = mk.poisson_disc(random.Random(7), BOX, 12.0)
        b = mk.poisson_disc(random.Random(7), BOX, 12.0)
        c = mk.poisson_disc(random.Random(8), BOX, 12.0)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_poisson_disc_edge_cases(self):
        self.assertEqual(mk.poisson_disc(random.Random(1), (0, 0, 0, 50), 5.0), [])
        with self.assertRaises(ValueError):
            mk.poisson_disc(random.Random(1), BOX, 0.0)
        self.assertEqual(len(mk.poisson_disc(random.Random(1), (0, 0, 3, 3), 50.0)), 1)


# ---------------------------------------------------------------------------
# Graphs
# ---------------------------------------------------------------------------

def kruskal_weight(points):
    """Weight of a minimum spanning tree, computed a different way (Kruskal)."""
    n = len(points)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    total = 0.0
    for w, i, j in sorted((mk.dist(points[i], points[j]), i, j)
                          for i in range(n) for j in range(i + 1, n)):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj
            total += w
    return total


def random_graph(rng, n, extra, weighted=True, connected=True):
    """A random undirected graph as a list of (a, b, w) edges over 0..n-1."""
    edges = {}
    if connected:
        for v in range(1, n):
            edges[(rng.randrange(v), v)] = rng.uniform(0.5, 9.0)
    for _ in range(extra):
        a, b = rng.randrange(n), rng.randrange(n)
        if a != b:
            edges[(min(a, b), max(a, b))] = rng.uniform(0.5, 9.0)
    return [(a, b, w if weighted else 1.0) for (a, b), w in edges.items()]


def floyd(n, edges):
    inf = float("inf")
    d = [[0.0 if i == j else inf for j in range(n)] for i in range(n)]
    for a, b, w in edges:
        d[a][b] = min(d[a][b], w)
        d[b][a] = min(d[b][a], w)
    for k in range(n):
        for i in range(n):
            for j in range(n):
                if d[i][k] + d[k][j] < d[i][j]:
                    d[i][j] = d[i][k] + d[k][j]
    return d


class Graphs(unittest.TestCase):
    def test_mst_is_a_connected_tree_of_minimum_weight(self):
        rng = random.Random(40)
        for _ in range(120):
            pts = random_sites(rng, rng.randint(2, 30))
            edges = mk.mst(pts)
            self.assertEqual(len(edges), len(pts) - 1)
            self.assertEqual(len(set(edges)), len(edges))
            self.assertTrue(all(i < j for i, j in edges))
            adj = mk.edges_to_adj(edges, nodes=range(len(pts)))
            self.assertEqual(len(mk.bfs_reachable(adj, 0)), len(pts))       # connected
            self.assertAlmostEqual(sum(mk.dist(pts[i], pts[j]) for i, j in edges),
                                   kruskal_weight(pts), places=6)           # minimal

    def test_mst_edge_cases_and_custom_metric(self):
        self.assertEqual(mk.mst([]), [])
        self.assertEqual(mk.mst([(1.0, 1.0)]), [])
        self.assertEqual(mk.mst([(0.0, 0.0), (3.0, 4.0)]), [(0, 1)])
        # with a metric that only looks at x, the tree follows the x order
        pts = [(5.0, 0.0), (1.0, 50.0), (3.0, -20.0), (9.0, 7.0)]
        edges = mk.mst(pts, metric=lambda a, b: abs(a[0] - b[0]))
        self.assertEqual(sorted(edges), sorted([(1, 2), (0, 2), (0, 3)]))

    def test_gabriel_edges_match_a_brute_force_definition(self):
        rng = random.Random(41)
        for _ in range(100):
            pts = random_sites(rng, rng.randint(3, 20))
            want = set()
            for i in range(len(pts)):
                for j in range(i + 1, len(pts)):
                    mx, my = (pts[i][0] + pts[j][0]) / 2, (pts[i][1] + pts[j][1]) / 2
                    r = mk.dist(pts[i], pts[j]) / 2
                    if all(mk.dist((mx, my), pts[k]) >= r - 1e-9
                           for k in range(len(pts)) if k not in (i, j)):
                        want.add((i, j))
            self.assertEqual(set(mk.gabriel_edges(pts)), want)

    def test_the_gabriel_graph_contains_the_minimum_spanning_tree(self):
        rng = random.Random(42)
        for _ in range(120):
            pts = random_sites(rng, rng.randint(2, 30))
            self.assertTrue(set(mk.mst(pts)) <= set(mk.gabriel_edges(pts)))

    def test_gabriel_graph_on_a_grid_keeps_points_on_the_circle(self):
        pts = [(x * 10.0, y * 10.0) for x in range(3) for y in range(3)]
        edges = set(mk.gabriel_edges(pts))
        self.assertIn((0, 1), edges)          # neighbours in a row
        self.assertIn((0, 3), edges)          # neighbours in a column
        self.assertNotIn((0, 2), edges)       # (0, 10) is at the centre of their circle
        self.assertIn((0, 4), edges)          # diagonal: the other two corners are on the circle

    def test_gabriel_of_sixty_points_is_fast(self):
        pts = random_sites(random.Random(43), 60)
        t = time.perf_counter()
        edges = mk.gabriel_edges(pts)
        self.assertLess(time.perf_counter() - t, 0.15)
        self.assertGreaterEqual(len(edges), 59)

    def test_dijkstra_matches_floyd_warshall_and_paths_add_up(self):
        rng = random.Random(44)
        for _ in range(120):
            n = rng.randint(2, 16)
            edges = random_graph(rng, n, rng.randint(0, 20), connected=rng.random() < 0.7)
            adj = mk.edges_to_wadj(edges, nodes=range(n))
            want = floyd(n, edges)
            src = rng.randrange(n)
            dist_, prev = mk.dijkstra(adj, src)
            for v in range(n):
                if want[src][v] == float("inf"):
                    self.assertNotIn(v, dist_)
                    self.assertIsNone(mk.shortest_path(adj, src, v))
                    continue
                self.assertAlmostEqual(dist_[v], want[src][v], places=9)
                path = mk.shortest_path(adj, src, v)
                self.assertEqual((path[0], path[-1]), (src, v))
                cost = 0.0
                for a, b in zip(path, path[1:]):
                    cost += min(w for x, w in adj[a] if x == b)
                self.assertAlmostEqual(cost, want[src][v], places=9)

    def test_dijkstra_can_stop_at_its_target_and_rejects_negative_weights(self):
        adj = mk.edges_to_wadj([(0, 1, 1.0), (1, 2, 1.0), (2, 3, 1.0), (0, 3, 10.0)])
        dist_, _ = mk.dijkstra(adj, 0, target=1)
        self.assertEqual(dist_[1], 1.0)
        self.assertNotIn(2, dist_)               # it stopped before looking further
        with self.assertRaises(ValueError):
            mk.dijkstra({0: [(1, -1.0)], 1: []}, 0)
        self.assertEqual(mk.dijkstra({}, "a"), ({"a": 0.0}, {}))

    def test_multi_source_dijkstra_gives_each_node_its_nearest_source(self):
        rng = random.Random(45)
        for _ in range(120):
            n = rng.randint(4, 18)
            edges = random_graph(rng, n, rng.randint(0, 15))
            adj = mk.edges_to_wadj(edges, nodes=range(n))
            want = floyd(n, edges)
            sources = rng.sample(range(n), rng.randint(1, min(4, n)))
            dist_, owner = mk.multi_source_dijkstra(adj, sources)
            self.assertEqual(set(dist_), set(range(n)))          # connected: all reached
            for v in range(n):
                nearest = min(want[s][v] for s in sources)
                self.assertAlmostEqual(dist_[v], nearest, places=9)
                self.assertAlmostEqual(want[owner[v]][v], nearest, places=9)
                self.assertIn(owner[v], sources)
            for s in sources:
                self.assertEqual((dist_[s], owner[s]), (0.0, s))

    def test_multi_source_ties_go_to_the_earlier_source(self):
        adj = mk.edges_to_wadj([("a", "m", 1.0), ("m", "b", 1.0)])
        _, owner = mk.multi_source_dijkstra(adj, ["a", "b"])
        self.assertEqual(owner["m"], "a")
        _, owner = mk.multi_source_dijkstra(adj, ["b", "a"])
        self.assertEqual(owner["m"], "b")

    def test_bfs_and_components_agree_with_a_plain_flood_fill(self):
        rng = random.Random(46)
        for _ in range(120):
            n = rng.randint(1, 20)
            edges = random_graph(rng, n, rng.randint(0, 6), weighted=False, connected=False)
            adj = mk.edges_to_adj(edges, nodes=range(n))
            comps = mk.connected_components(adj)
            self.assertEqual(sorted(v for c in comps for v in c), list(range(n)))
            for comp in comps:
                stack, seen = [comp[0]], {comp[0]}
                while stack:
                    u = stack.pop()
                    for v in adj[u]:
                        if v not in seen:
                            seen.add(v)
                            stack.append(v)
                self.assertEqual(seen, set(comp))
            hops = mk.bfs_reachable(adj, 0)
            self.assertEqual(set(hops), set(next(c for c in comps if 0 in c)))
            self.assertEqual(hops[0], 0)
            for a, b, _ in edges:
                if a in hops:
                    self.assertLessEqual(abs(hops[a] - hops[b]), 1)     # neighbours differ by <= 1

    def test_components_accept_tuple_nodes_and_neighbour_only_nodes(self):
        adj = {(0, 0): [(0, 1)], (0, 1): [(0, 0)], (5, 5): [(6, 6)]}
        comps = mk.connected_components(adj)
        self.assertEqual(sorted(len(c) for c in comps), [2, 2])

    def test_farthest_pair_is_the_diameter(self):
        rng = random.Random(47)
        for _ in range(100):
            n = rng.randint(1, 18)
            edges = random_graph(rng, n, rng.randint(0, 6), weighted=False,
                                 connected=rng.random() < 0.7)
            adj = mk.edges_to_adj(edges, nodes=range(n))
            a, b = mk.farthest_pair(adj)
            best = max(h for s in range(n) for h in mk.bfs_reachable(adj, s).values())
            self.assertEqual(mk.bfs_reachable(adj, a)[b], best)

    def test_farthest_pair_on_a_path_and_edge_cases(self):
        path = mk.edges_to_adj([(i, i + 1) for i in range(9)])
        self.assertEqual(set(mk.farthest_pair(path)), {0, 9})
        self.assertIsNone(mk.farthest_pair({}))
        self.assertEqual(mk.farthest_pair({"only": []}), ("only", "only"))
        big = mk.edges_to_adj([(i, i + 1) for i in range(400)])      # two-sweep branch
        self.assertEqual(set(mk.farthest_pair(big)), {0, 400})


# ---------------------------------------------------------------------------
# Rectangles and grids
# ---------------------------------------------------------------------------

def rect_area(r):
    return (r[2] - r[0]) * (r[3] - r[1])


def rect_overlap_area(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def contact_length(a, b, delta=1e-4):
    """Length of the wall two rectangles share, found by a different route
    from the kit's: grow one by a hair and see how much of the other it covers."""
    grown = (a[0] - delta, a[1] - delta, a[2] + delta, a[3] + delta)
    return rect_overlap_area(grown, b) / delta


class RectangleSplitting(unittest.TestCase):
    def test_bsp_leaves_tile_the_rectangle_and_cannot_be_cut_further(self):
        rng = random.Random(50)
        for _ in range(120):
            rect = (rng.uniform(-20, 20), rng.uniform(-20, 20), 0.0, 0.0)
            rect = (rect[0], rect[1], rect[0] + rng.uniform(20, 120), rect[1] + rng.uniform(20, 90))
            m = rng.uniform(4.0, 12.0)
            leaves = mk.bsp_split(rect, rng, m)
            self.assertAlmostEqual(sum(rect_area(l) for l in leaves), rect_area(rect), places=6)
            for i, l in enumerate(leaves):
                self.assertGreaterEqual(l[2] - l[0], m - 1e-9)
                self.assertGreaterEqual(l[3] - l[1], m - 1e-9)
                self.assertTrue(l[0] >= rect[0] - 1e-9 and l[2] <= rect[2] + 1e-9
                                and l[1] >= rect[1] - 1e-9 and l[3] <= rect[3] + 1e-9)
                # cut all the way down: no leaf is big enough to cut in two
                self.assertTrue(l[2] - l[0] < 2 * m and l[3] - l[1] < 2 * m)
                for other in leaves[:i]:
                    self.assertLess(rect_overlap_area(l, other), 1e-9)

    def test_bsp_max_leaf_stops_the_cutting_early(self):
        rng = random.Random(51)
        for _ in range(100):
            m = rng.uniform(4.0, 8.0)
            big = rng.uniform(2.5 * m, 5 * m)
            leaves = mk.bsp_split((0.0, 0.0, 120.0, 90.0), rng, m, max_leaf=big)
            self.assertAlmostEqual(sum(rect_area(l) for l in leaves), 120.0 * 90.0, places=6)
            for l in leaves:
                w, h = l[2] - l[0], l[3] - l[1]
                self.assertTrue((w <= big and h <= big) or (w < 2 * m and h < 2 * m))
                self.assertGreaterEqual(min(w, h), m - 1e-9)

    def test_bsp_integer_mode_cuts_on_whole_numbers(self):
        rng = random.Random(52)
        for _ in range(100):
            leaves = mk.bsp_split((0, 0, 64, 48), rng, 10, integer=True)
            self.assertEqual(sum(int(rect_area(l)) for l in leaves), 64 * 48)
            self.assertGreater(len(leaves), 4)
            for l in leaves:
                self.assertTrue(all(float(v).is_integer() for v in l), l)
                self.assertGreaterEqual(min(l[2] - l[0], l[3] - l[1]), 10)
        # without integer=True the cuts are free to land between the lines
        loose = mk.bsp_split((0, 0, 64, 48), random.Random(1), 10)
        self.assertFalse(all(float(v).is_integer() for l in loose for v in l))
        # fractional leaf size with whole-number cuts
        for l in mk.bsp_split((0, 0, 40, 31), random.Random(2), 6.5, integer=True):
            self.assertTrue(all(float(v).is_integer() for v in l), l)
            self.assertGreaterEqual(min(l[2] - l[0], l[3] - l[1]), 6.5)

    def test_bsp_is_deterministic_and_handles_small_inputs(self):
        a = mk.bsp_split((0, 0, 100, 80), random.Random(9), 8)
        self.assertEqual(a, mk.bsp_split((0, 0, 100, 80), random.Random(9), 8))
        self.assertNotEqual(a, mk.bsp_split((0, 0, 100, 80), random.Random(10), 8))
        self.assertEqual(mk.bsp_split((0, 0, 10, 10), random.Random(1), 8),
                         [(0.0, 0.0, 10.0, 10.0)])
        with self.assertRaises(ValueError):
            mk.bsp_split((0, 0, 10, 10), random.Random(1), 0)


class Treemap(unittest.TestCase):
    def random_items(self, rng, rect):
        n = rng.randint(1, 14)
        weights = [rng.uniform(0.2, 10.0) for _ in range(n)]
        total = sum(weights)
        area = rect_area(rect)
        return [("room%d" % i, w / total * area) for i, w in enumerate(weights)]

    def test_squarify_fills_the_rectangle_with_the_requested_areas(self):
        rng = random.Random(60)
        for _ in range(150):
            x0, y0 = rng.uniform(-30, 30), rng.uniform(-30, 30)
            rect = (x0, y0, x0 + rng.uniform(15, 150), y0 + rng.uniform(15, 100))
            items = self.random_items(rng, rect)
            out = mk.squarify(items, rect)
            self.assertEqual(list(out), [k for k, _ in items])            # input order kept
            for key, area in items:
                self.assertAlmostEqual(rect_area(out[key]), area, places=6)
            self.assertAlmostEqual(sum(rect_area(r) for r in out.values()),
                                   rect_area(rect), places=6)
            rects = list(out.values())
            for i, r in enumerate(rects):
                self.assertTrue(r[0] >= rect[0] - 1e-9 and r[2] <= rect[2] + 1e-9
                                and r[1] >= rect[1] - 1e-9 and r[3] <= rect[3] + 1e-9)
                self.assertGreaterEqual(r[2] - r[0], -1e-12)
                for other in rects[:i]:
                    self.assertLess(rect_overlap_area(r, other), 1e-7)

    def test_squarify_makes_squarer_rooms_than_one_long_strip(self):
        rng = random.Random(61)
        better = tried = 0
        for _ in range(100):
            rect = (0.0, 0.0, rng.uniform(40, 120), rng.uniform(30, 90))
            items = self.random_items(rng, rect)
            if len(items) < 5:
                continue
            tried += 1

            def aspect(r):
                w, h = r[2] - r[0], r[3] - r[1]
                return max(w / h, h / w) if min(w, h) > 0 else 1e9

            strip = sum(aspect((0, 0, rect[2] * a / rect_area(rect), rect[3]))
                        for _, a in items) / len(items)
            squares = sum(aspect(r) for r in mk.squarify(items, rect).values()) / len(items)
            better += squares < strip
        self.assertGreater(tried, 50)
        self.assertGreaterEqual(better, tried - 2)

    def test_squarify_scales_requests_that_do_not_add_up(self):
        out = mk.squarify([("a", 1.0), ("b", 3.0)], (0, 0, 20, 10))       # 4 units -> 200
        self.assertAlmostEqual(rect_area(out["a"]), 50.0)
        self.assertAlmostEqual(rect_area(out["b"]), 150.0)

    def test_squarify_edge_cases(self):
        self.assertEqual(mk.squarify([], (0, 0, 10, 10)), {})
        self.assertEqual(mk.squarify([("only", 5.0)], (0, 0, 10, 4)), {"only": (0, 0, 10, 4)})
        out = mk.squarify([("a", 30.0), ("nothing", 0.0), ("b", 10.0)], (0, 0, 8, 5))
        self.assertEqual(rect_area(out["nothing"]), 0.0)
        self.assertAlmostEqual(rect_area(out["a"]) + rect_area(out["b"]), 40.0)
        with self.assertRaises(ValueError):
            mk.squarify([("a", 1.0), ("a", 2.0)], (0, 0, 5, 5))
        with self.assertRaises(ValueError):
            mk.squarify([("a", -1.0)], (0, 0, 5, 5))

    def test_squarify_is_deterministic_with_equal_areas(self):
        items = [("r%d" % i, 10.0) for i in range(8)]
        self.assertEqual(mk.squarify(items, (0, 0, 20, 4)), mk.squarify(items, (0, 0, 20, 4)))


class SharedWalls(unittest.TestCase):
    def test_two_rooms_side_by_side(self):
        walls = mk.shared_walls([(0, 0, 10, 10), (10, 2, 20, 8)])
        self.assertEqual(walls, {(0, 1): ((10, 2), (10, 8))})
        self.assertEqual(mk.shared_walls([(0, 0, 10, 10), (10, 2, 20, 8)], min_len=7.0), {})
        stacked = mk.shared_walls([(0, 0, 10, 10), (3, 10, 25, 20)])
        self.assertEqual(stacked, {(0, 1): ((3, 10), (10, 10))})

    def test_corner_contact_and_gaps_are_not_walls(self):
        self.assertEqual(mk.shared_walls([(0, 0, 10, 10), (10, 10, 20, 20)]), {})
        self.assertEqual(mk.shared_walls([(0, 0, 10, 10), (11, 0, 20, 10)]), {})

    def test_shared_walls_match_the_grow_and_overlap_measure(self):
        rng = random.Random(62)
        for _ in range(120):
            rect = (0.0, 0.0, rng.uniform(30, 100), rng.uniform(30, 80))
            items = [("r%d" % i, rng.uniform(1, 10)) for i in range(rng.randint(3, 12))]
            rooms = list(mk.squarify(items, rect).values())
            min_len = rng.choice([0.0, 2.0, 5.0])
            walls = mk.shared_walls(rooms, min_len=min_len)
            threshold = max(min_len, 1e-3)
            for i in range(len(rooms)):
                for j in range(i + 1, len(rooms)):
                    length = contact_length(rooms[i], rooms[j])
                    if abs(length - threshold) < 2e-3:
                        continue                          # too close to the cut-off to judge
                    self.assertEqual((i, j) in walls, length > threshold, (i, j, length))
                    if (i, j) in walls:
                        (px, py), (qx, qy) = walls[(i, j)]
                        self.assertAlmostEqual(mk.dist((px, py), (qx, qy)), length, places=2)
            for (i, j), (p, q) in walls.items():
                self.assertLess(i, j)
                for r in (rooms[i], rooms[j]):
                    for pt in (p, q):
                        self.assertTrue(mk.rect_contains(r, pt, 1e-6))


def flood(cells, neighbours):
    """Connected components of a set of grid cells, by a plain flood fill."""
    remaining, groups = set(cells), []
    while remaining:
        start = remaining.pop()
        group, stack = {start}, [start]
        while stack:
            c, r = stack.pop()
            for dc, dr in neighbours:
                nb = (c + dc, r + dr)
                if nb in remaining:
                    remaining.discard(nb)
                    group.add(nb)
                    stack.append(nb)
        groups.append(group)
    return groups


FOUR = [(1, 0), (-1, 0), (0, 1), (0, -1)]
EIGHT = FOUR + [(1, 1), (1, -1), (-1, 1), (-1, -1)]


def covered(entry, pt):
    outer, holes = entry
    return mk.point_in_polygon(pt, outer) and not any(mk.point_in_polygon(pt, h) for h in holes)


class GridOutlines(unittest.TestCase):
    def test_simple_shapes(self):
        (outer, holes), = mk.cells_outline([(3, 4)])
        self.assertEqual(holes, [])
        self.assertAlmostEqual(shoelace(outer), 1.0)
        self.assertEqual(sorted(outer), [(3.0, 4.0), (3.0, 5.0), (4.0, 4.0), (4.0, 5.0)])
        (strip, _), = mk.cells_outline([(0, 0), (1, 0), (2, 0)])
        self.assertEqual(len(strip), 4)                       # collinear points merged
        self.assertAlmostEqual(shoelace(strip), 3.0)
        (ell, _), = mk.cells_outline([(0, 0), (1, 0), (0, 1)])
        self.assertEqual(len(ell), 6)
        self.assertAlmostEqual(shoelace(ell), 3.0)
        self.assertEqual(mk.cells_outline([]), [])

    def test_a_ring_of_cells_has_one_hole(self):
        ring = [(c, r) for c in range(3) for r in range(3) if (c, r) != (1, 1)]
        (outer, holes), = mk.cells_outline(ring)
        self.assertAlmostEqual(shoelace(outer), 9.0)
        self.assertEqual(len(holes), 1)
        self.assertAlmostEqual(shoelace(holes[0]), -1.0)      # holes wind the other way

    def test_an_island_inside_a_hole_is_its_own_shape(self):
        ring = [(c, r) for c in range(5) for r in range(5) if (c, r) != (2, 2)
                and not (1 <= c <= 3 and 1 <= r <= 3)] + [(2, 2)]
        entries = mk.cells_outline(ring)
        self.assertEqual(len(entries), 2)
        by_area = sorted(entries, key=lambda e: shoelace(e[0]))
        self.assertAlmostEqual(shoelace(by_area[0][0]), 1.0)
        self.assertEqual(by_area[0][1], [])
        self.assertEqual(len(by_area[1][1]), 1)
        self.assertAlmostEqual(shoelace(by_area[1][1][0]), -9.0)

    def test_cells_touching_only_at_a_corner_are_separate_shapes(self):
        for cells in ([(0, 0), (1, 1)], [(1, 0), (0, 1)]):
            entries = mk.cells_outline(cells)
            self.assertEqual(len(entries), 2)
            for outer, holes in entries:
                self.assertEqual(len(outer), 4)
                self.assertAlmostEqual(shoelace(outer), 1.0)
                self.assertTrue(mk.polygon_is_simple(outer))
        checker = [(c, r) for c in range(4) for r in range(4) if (c + r) % 2 == 0]
        entries = mk.cells_outline(checker)
        self.assertEqual(len(entries), 8)                     # every cell on its own

    def test_a_notch_plugged_only_at_the_corners_is_not_a_hole(self):
        # a C whose opening is filled by a cell that meets both tips only
        # diagonally: two separate shapes, and no ring closes round the notch
        cells = [(0, 0), (1, 0), (2, 0), (0, 1), (0, 2), (1, 2), (2, 2), (3, 1)]
        entries = mk.cells_outline(cells)
        self.assertEqual(sum(len(h) for _, h in entries), 0)
        self.assertEqual(len(entries), 2)
        for outer, _ in entries:
            self.assertTrue(mk.polygon_is_simple(outer))

    def test_a_pocket_joined_to_the_outside_at_one_corner_becomes_a_hole(self):
        # a 3x3 ring with one corner cell missing: the empty middle cell touches
        # the missing corner only diagonally; the ring must not visit that
        # corner twice, so the middle is cut out as a hole that meets the outline
        cells = [(c, r) for c in range(3) for r in range(3) if (c, r) not in ((1, 1), (0, 0))]
        (outer, holes), = mk.cells_outline(cells)
        self.assertTrue(mk.polygon_is_simple(outer))
        self.assertAlmostEqual(shoelace(outer), 8.0)
        self.assertEqual(len(outer), 6)
        self.assertEqual(len(holes), 1)
        self.assertAlmostEqual(shoelace(holes[0]), -1.0)
        self.assertIn((1.0, 1.0), outer)
        self.assertIn((1.0, 1.0), holes[0])                  # they meet at that corner

    def test_random_grids_are_traced_faithfully(self):
        rng = random.Random(63)
        for _ in range(150):
            cols, rows = rng.randint(3, 9), rng.randint(3, 8)
            density = rng.uniform(0.2, 0.95)
            cells = {(c, r) for c in range(cols) for r in range(rows) if rng.random() < density}
            if not cells:
                continue
            entries = mk.cells_outline(cells)
            # the areas add up to the cell count (holes are negative)
            total = sum(shoelace(o) + sum(shoelace(h) for h in hs) for o, hs in entries)
            self.assertAlmostEqual(total, float(len(cells)), places=9)
            # one entry per 4-connected group of cells
            self.assertEqual(len(entries), len(flood(cells, FOUR)))
            for outer, holes in entries:
                self.assertGreater(shoelace(outer), 0.0)
                for ring in [outer] + holes:
                    self.assertTrue(mk.polygon_is_simple(ring))
                    n = len(ring)
                    for i in range(n):
                        a, b, c = ring[i - 1], ring[i], ring[(i + 1) % n]
                        self.assertTrue(float(b[0]).is_integer() and float(b[1]).is_integer())
                        self.assertTrue(a[0] == b[0] or a[1] == b[1])           # rectilinear
                        self.assertNotEqual((b[0] - a[0]) * (c[1] - b[1])
                                            - (b[1] - a[1]) * (c[0] - b[0]), 0)  # no collinear
                for hole in holes:
                    self.assertLess(shoelace(hole), 0.0)
            # every filled cell is covered by exactly one entry, every empty one by none
            for c in range(-1, cols + 1):
                for r in range(-1, rows + 1):
                    centre = (c + 0.5, r + 0.5)
                    hits = sum(covered(e, centre) for e in entries)
                    self.assertEqual(hits, 1 if (c, r) in cells else 0, (c, r))

    def test_size_scales_the_outline_and_the_result_is_deterministic(self):
        cells = [(0, 0), (1, 0), (1, 1), (5, 5)]
        small = mk.cells_outline(cells)
        big = mk.cells_outline(cells, size=10.0)
        self.assertEqual(small, mk.cells_outline(cells))
        self.assertEqual(big, [([(x * 10, y * 10) for x, y in o],
                                [[(x * 10, y * 10) for x, y in h] for h in hs])
                               for o, hs in small])
        self.assertEqual(mk.cells_outline(iter(cells)), small)              # any iterable


class HexGrids(unittest.TestCase):
    def test_neighbours_are_one_step_away_in_the_documented_directions(self):
        rng = random.Random(64)
        size = 7.0
        for _ in range(150):
            col, row = rng.randint(-8, 8), rng.randint(-8, 8)
            cx, cy = mk.hex_center(col, row, size)
            nbs = mk.hex_neighbors(col, row)
            self.assertEqual(len(set(nbs)), 6)
            for k, (nc, nr) in enumerate(nbs):
                nx, ny = mk.hex_center(nc, nr, size)
                self.assertAlmostEqual(mk.dist((cx, cy), (nx, ny)), math.sqrt(3) * size, places=9)
                angle = math.degrees(math.atan2(ny - cy, nx - cx))
                turn = (angle - (30 + 60 * k) + 180) % 360 - 180        # wrapped difference
                self.assertAlmostEqual(turn, 0.0, places=6)
                self.assertIn((col, row), mk.hex_neighbors(nc, nr))          # symmetric
                self.assertEqual(mk.hex_distance((col, row), (nc, nr)), 1)

    def test_corners_form_a_regular_hexagon_that_meets_its_neighbours(self):
        rng = random.Random(65)
        size = 5.0
        for _ in range(100):
            col, row = rng.randint(-6, 6), rng.randint(-6, 6)
            corners = mk.hex_corners(col, row, size)
            centre = mk.hex_center(col, row, size)
            self.assertEqual(len(corners), 6)
            self.assertTrue(all(abs(mk.dist(c, centre) - size) < 1e-9 for c in corners))
            self.assertAlmostEqual(shoelace(corners), 1.5 * math.sqrt(3) * size * size)
            for k, (nc, nr) in enumerate(mk.hex_neighbors(col, row)):
                theirs = mk.hex_corners(nc, nr, size)
                mine = {(round(x, 6), round(y, 6)) for x, y in (corners[k], corners[(k + 1) % 6])}
                shared = {(round(x, 6), round(y, 6)) for x, y in theirs} & mine
                self.assertEqual(shared, mine)             # the edge k is theirs too

    def test_hexes_tile_the_plane(self):
        rng = random.Random(66)
        size = 6.0
        for _ in range(150):
            p = (rng.uniform(0, 100), rng.uniform(0, 100))
            cells = [(c, r) for c in range(-2, 18) for r in range(-2, 15)]
            nearest = min(cells, key=lambda cr: mk.dist(p, mk.hex_center(cr[0], cr[1], size)))
            self.assertTrue(mk.point_in_polygon(p, mk.hex_corners(nearest[0], nearest[1], size))
                            or mk.distance_to_boundary(
                                p, mk.hex_corners(nearest[0], nearest[1], size)) < 1e-9)

    def test_hex_distance_is_the_number_of_steps(self):
        rng = random.Random(67)
        for _ in range(60):
            a = (rng.randint(-6, 6), rng.randint(-6, 6))
            hops = {a: 0}
            frontier = [a]
            for step in range(1, 9):
                nxt = []
                for cell in frontier:
                    for nb in mk.hex_neighbors(*cell):
                        if nb not in hops:
                            hops[nb] = step
                            nxt.append(nb)
                frontier = nxt
            for b, h in hops.items():
                if h <= 8:
                    self.assertEqual(mk.hex_distance(a, b), h)
                    self.assertEqual(mk.hex_distance(b, a), h)


# @@TESTS@@
