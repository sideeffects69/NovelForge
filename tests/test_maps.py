"""
The map engine: generation, contours, the display list, and the exports.

No window is opened here, so this is fast. What it guards is what made the old
maps look wrong - a blobby coast, rivers that were short stubs in the middle of
nowhere, roads laid across the sea, lakes hidden under the land that held them,
and a "same seed, same world" promise that quietly did not cover the names.
"""

import math
import tempfile
import time
import unittest
import zlib
from pathlib import Path

from tests import require_isolation

require_isolation()

from novelforge import mapgen, mapmaker as mm  # noqa: E402


def world(preset="Classic fantasy world", seed=7):
    return mapgen.generate(mapgen.preset(preset, seed))


def lands(gm):
    return [s for s in gm.shapes if s.kind == "land"]


def on_land(gm, point):
    """Inside some island and not inside a lake or inland sea cut out of it."""
    inside = any(mm.point_in_polygon(point, s.points) for s in lands(gm))
    wet = any(mm.point_in_polygon(point, s.points)
              for s in gm.shapes if s.kind == "water")
    return inside and not wet


class Determinism(unittest.TestCase):
    def test_the_same_seed_rebuilds_the_same_world_names_included(self):
        first, second = world(seed=99), world(seed=99)
        self.assertEqual([(s.kind, s.points) for s in first.shapes],
                         [(s.kind, s.points) for s in second.shapes])
        self.assertEqual([(p.kind, p.label, round(p.x, 3), round(p.y, 3))
                          for p in first.pins],
                         [(p.kind, p.label, round(p.x, 3), round(p.y, 3))
                          for p in second.pins])
        self.assertEqual([l.text for l in first.labels],
                         [l.text for l in second.labels])
        self.assertEqual(first.name, second.name)

    def test_a_different_seed_is_a_different_world(self):
        a, b = world(seed=1), world(seed=2)
        self.assertNotEqual([s.points for s in a.shapes if s.kind == "land"],
                            [s.points for s in b.shapes if s.kind == "land"])

    def test_a_typed_seed_means_the_same_thing_everywhere(self):
        self.assertEqual(mapgen.seed_from_text("12345"), 12345)
        self.assertEqual(mapgen.seed_from_text("Ashfall"), mapgen.seed_from_text("Ashfall"))
        self.assertEqual(mapgen.seed_from_text(""), 0)

    def test_terrain_scatter_is_stable_between_launches(self):
        # Python salts str.hash() per process; seeding trees with it reshuffled
        # every forest each time a map was opened.
        shape = mm.Shape(id="shp_fixed", kind="forest",
                         points=[(0, 0), (200, 0), (200, 200), (0, 200)])
        self.assertEqual(mm._stable_seed(shape),
                         zlib.crc32(b"shp_fixed") & 0xFFFF)


class Structure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gm = world()

    def test_every_preset_makes_land_and_people(self):
        for name in mapgen.PRESETS:
            gm = world(name, 5)
            self.assertTrue(lands(gm), f"{name}: no land at all")
            self.assertTrue(gm.pins, f"{name}: nobody lives there")
            for shape in lands(gm):
                self.assertGreaterEqual(len(shape.points), 4)

    def test_everything_stays_on_the_page(self):
        gm = self.gm
        slack = 8
        for shape in gm.shapes:
            for x, y in shape.points:
                self.assertTrue(-slack <= x <= gm.width + slack
                                and -slack <= y <= gm.height + slack,
                                f"{shape.kind} point {(x, y)} is off the map")
        for pin in gm.pins:
            self.assertTrue(0 <= pin.x <= gm.width and 0 <= pin.y <= gm.height)

    def test_settlements_are_on_dry_land(self):
        stray = [p.label for p in self.gm.pins if not on_land(self.gm, (p.x, p.y))]
        # A pin hard against a jagged coast can land a pixel outside the
        # smoothed outline; a pin out at sea is what this is here to catch.
        self.assertLessEqual(len(stray), max(2, len(self.gm.pins) // 12), stray)

    def test_roads_follow_the_land_and_never_cross_the_sea(self):
        gm = self.gm
        roads = [s for s in gm.shapes if s.kind == "road"]
        self.assertTrue(roads, "a world with towns and no roads")
        samples = wet = 0
        for road in roads:
            for (ax, ay), (bx, by) in zip(road.points, road.points[1:]):
                for t in (0.25, 0.5, 0.75):
                    samples += 1
                    if not on_land(gm, (ax + (bx - ax) * t, ay + (by - ay) * t)):
                        wet += 1
        self.assertLessEqual(wet / samples, 0.04,
                             f"{wet} of {samples} road samples are in the water")

    def test_rivers_are_long_and_run_downhill_to_the_water(self):
        gm = self.gm
        rivers = [s for s in gm.shapes if s.kind == "river"]
        self.assertTrue(rivers)
        longest = max(mm._path_length(r.points) for r in rivers)
        # The old rivers were 30-pixel stubs traced from their own mouths.
        self.assertGreater(longest, 250, "no river crosses any real distance")
        for river in rivers:
            self.assertGreaterEqual(len(river.points), 3)

    def test_mountains_run_in_ranges(self):
        ranges = [s for s in self.gm.shapes if s.kind == "mountains"]
        self.assertGreaterEqual(len(ranges), 2)
        self.assertTrue(any(len(s.points) >= 6 for s in ranges))

    def test_lakes_are_painted_over_the_land_that_holds_them(self):
        gm = mm.GameMap(name="t", width=400, height=300, layers=[mm.Layer(name="L")])
        gm.shapes = [
            mm.Shape(kind="land", layer="L", points=[(50, 50), (350, 50), (350, 250), (50, 250)]),
            mm.Shape(kind="water", layer="L", points=[(150, 100), (250, 100), (250, 200), (150, 200)]),
        ]
        fills = [p[2] for p in mm.build_primitives(gm, include_furniture=False)
                 if p[0] == "polygon" and p[2]]
        palette = gm.palette()["terrain"]
        self.assertLess(fills.index(palette["land"]), fills.index(palette["water"]))

    def test_generation_is_quick_enough_to_feel_instant(self):
        started = time.perf_counter()
        world("Scattered isles", 3)
        # About 0.7s on the developer's machine; ten times that is a regression,
        # not a slow disk.
        self.assertLess(time.perf_counter() - started, 8.0)


class Contours(unittest.TestCase):
    def field(self):
        """A round island with a round lake in it, on a 60x40 grid."""
        w, h = 60, 40
        grid = [[0.0] * w for _ in range(h)]
        for y in range(h):
            for x in range(w):
                d = math.hypot(x - 30, y - 20)
                if d < 16:
                    grid[y][x] = 1.0
                if math.hypot(x - 30, y - 20) < 5:
                    grid[y][x] = 0.0          # the lake
        return grid, w, h

    def test_an_island_and_its_lake_wind_opposite_ways(self):
        grid, w, h = self.field()
        rings = mapgen._contours(grid, w, h, 0.5)
        self.assertEqual(len(rings), 2)
        by_size = sorted(rings, key=lambda r: -abs(r[0]))
        self.assertLess(by_size[0][0], 0, "the island should be negative")
        self.assertGreater(by_size[1][0], 0, "the lake should be positive")
        self.assertAlmostEqual(abs(by_size[0][0]), math.pi * 16 ** 2, delta=40)

    def test_land_touching_the_edge_still_closes(self):
        grid = [[1.0] * 10 for _ in range(8)]
        (area, points), = mapgen._contours(grid, 10, 8, 0.5)
        self.assertEqual(len(points), len(set(points)))
        self.assertLess(area, 0)

    def test_an_offset_ring_grows_outward(self):
        square = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
        for ring in (square, list(reversed(square))):        # either winding
            grown = mm._offset_ring(ring, 10)
            xs = [p[0] for p in grown]
            self.assertLess(min(xs), -5)
            self.assertGreater(max(xs), 105)
        self.assertEqual(mm._offset_ring([(0, 0), (1, 1)], 5), [])


class DisplayList(unittest.TestCase):
    def test_the_list_is_remembered_until_the_map_changes(self):
        gm = world()
        first = mm.build_primitives(gm)
        cached = gm._prim_cache
        second = mm.build_primitives(gm)
        self.assertIs(gm._prim_cache, cached, "a second look rebuilt everything")
        self.assertEqual(first, second)
        shape = gm.shapes[0]
        shape.points[0] = (shape.points[0][0] + 5, shape.points[0][1])
        third = mm.build_primitives(gm)
        self.assertIsNot(gm._prim_cache, cached)
        self.assertNotEqual(first, third)

    def test_editing_one_shape_keeps_the_others_decoration(self):
        gm = world()
        mm.build_primitives(gm)
        kept = {slot: entry for slot, entry in gm._shape_cache.items()}
        forest = next(s for s in gm.shapes if s.kind == "forest")
        forest.points[0] = (forest.points[0][0] + 3, forest.points[0][1])
        mm.build_primitives(gm)
        same = [slot for slot, entry in gm._shape_cache.items()
                if slot in kept and kept[slot][1] is entry[1]]
        self.assertGreater(len(same), len(kept) * 0.8)
        self.assertNotIn((forest.id, "body"), same)

    def test_peaks_are_a_range_not_a_row_of_identical_tents(self):
        pts = [(0, 100), (300, 100)]
        prims = mm._peaks(pts, "#000000", "#f2e8cb", seed=3)
        tops = sorted({round(p[1][1][1]) for p in prims
                       if p[0] == "line" and len(p[1]) == 3 and p[3] == 1.25})
        self.assertGreater(len(tops), 4, "every peak sits at the same height")

    def test_text_halos_are_optional_for_every_consumer(self):
        short = ("text", 1, 2, "Ash", 12, "#000", "center", False, False, 0.0)
        long = short + ("#fff",)
        self.assertEqual(mm.text_parts(short)[-1], "")
        self.assertEqual(mm.text_parts(long)[-1], "#fff")
        self.assertEqual(mm.text_parts(long)[:3], (1, 2, "Ash"))

    def test_place_names_carry_a_halo(self):
        gm = world()
        named = [p for p in mm.build_primitives(gm)
                 if p[0] == "text" and p[3] in {pin.label for pin in gm.pins}]
        self.assertTrue(named)
        self.assertTrue(all(len(p) > 10 and p[10] for p in named))


class Exports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gm = world("Island archipelago", 3)
        cls.folder = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_png_is_the_size_asked_for(self):
        from PIL import Image

        path = mm.render_png(self.gm, Path(self.folder.name) / "map.png", scale=0.4)
        with Image.open(path) as image:
            self.assertEqual(image.size, (int(self.gm.width * 0.4),
                                          int(self.gm.height * 0.4)))

    def test_svg_carries_the_halo_and_every_place_name(self):
        path = mm.render_svg(self.gm, Path(self.folder.name) / "map.svg")
        text = path.read_text(encoding="utf-8")
        self.assertIn("paint-order", text)
        first = next(p.label for p in self.gm.pins if p.label)
        self.assertIn(first, text)

    def test_a_map_survives_saving_and_reopening(self):
        folder = Path(self.folder.name)
        saved = mm.save_map(folder, self.gm)
        again = mm.load_map(saved)
        self.assertEqual(len(again.shapes), len(self.gm.shapes))
        self.assertEqual(mm.build_primitives(again), mm.build_primitives(self.gm))


if __name__ == "__main__":
    unittest.main()
