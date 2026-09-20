"""
Book-ready maps: the scale that tells the truth, secrets that stay secret, print
and ebook export, the legend, and the links from a pin to the map inside it.

No window is opened here (one class near the bottom opens a hidden Tk canvas,
and skips itself where there is no display), so this is fast. Every check was
proven able to fail by breaking the thing it guards; the docstrings say what.
"""

import math
import tempfile
import unittest
import zlib
from pathlib import Path

from tests import require_isolation

require_isolation()

from novelforge import mapgen, mapmaker as mm, mapstory  # noqa: E402


def blank(width=1600, **kw):
    """A map with nothing on it but its furniture."""
    kw.setdefault("height", round(width * 0.6875))
    return mm.GameMap(name="Book", width=width, layers=[mm.Layer(name="Base")], **kw)


def drawn_bar_px(gm):
    """
    How long the scale bar is in the picture, read off the display list.

    Deliberately does not ask `scale_bar` (that would be checking a function
    against itself): it finds the bar's four blocks by where the design puts
    them - left margin 4.5% of the width, 5.2% of the height up from the bottom.
    """
    left = gm.width * 0.045
    top = gm.height - gm.height * 0.052
    blocks = [p for p in mm.build_primitives(gm)
              if p[0] == "polygon" and len(p[1]) == 4
              and abs(p[1][0][1] - top) < 1e-6 and p[1][0][0] >= left - 1e-6]
    assert len(blocks) == 4, f"expected the scale bar's 4 blocks, found {len(blocks)}"
    return max(pt[0] for p in blocks for pt in p[1]) - min(
        pt[0] for p in blocks for pt in p[1])


# The number in each caption, typed here by hand rather than parsed, so the
# test does not lean on the parser it is checking.
CAPTIONS = (("200 leagues", 200.0), ("100 miles", 100.0), ("50 km", 50.0),
            ("1,000 feet", 1000.0), ("3 AU", 3.0), ("12.5 miles", 12.5),
            ("5 leagues (15 miles)", 5.0))


class ScaleTellsTheTruth(unittest.TestCase):
    """The bar is drawn 16% of the width (at most 230 px); mapstory assumed 20%."""

    def test_a_distance_is_what_the_drawn_bar_says_it_is(self):
        # Breaking it: putting `width * 0.2` back into mapstory.read_scale
        # fails every width here (the drawn bar is 192, 230, 230 and 230 px
        # long at these widths; the old guess was 240, 320, 360 and 480).
        for width in (1200, 1600, 1800, 2400):
            for caption, amount in CAPTIONS:
                gm = blank(width, scale_text=caption)
                bar = drawn_bar_px(gm)
                for apart in (bar, bar * 0.5, 137.0, 611.0):
                    a = mm.Pin(x=100, y=200)
                    b = mm.Pin(x=100 + apart * 0.6, y=200 + apart * 0.8)  # 3-4-5
                    self.assertAlmostEqual(
                        mapstory.distance(gm, a, b), apart / bar * amount,
                        places=6, msg=f"{width}px wide, '{caption}', {apart:.0f}px apart")

    def test_two_pins_one_bar_apart_are_exactly_the_caption_apart(self):
        for width in (1200, 1600, 1800, 2400):
            gm = blank(width, scale_text="200 leagues")
            bar = drawn_bar_px(gm)
            a, b = mm.Pin(x=50, y=50), mm.Pin(x=50 + bar, y=50)
            self.assertAlmostEqual(mapstory.distance(gm, a, b), 200.0, places=6)

    def test_the_old_guess_of_a_fifth_of_the_width_is_gone(self):
        gm = blank(1800, scale_text="200 leagues")
        scale = mapstory.read_scale(gm)
        self.assertAlmostEqual(scale.bar_pixels, drawn_bar_px(gm), places=6)
        self.assertNotAlmostEqual(scale.bar_pixels, 1800 * 0.2, places=0)
        self.assertEqual(round(drawn_bar_px(gm)), 230)        # capped, as drawn since 2.2

    def test_old_maps_are_drawn_exactly_as_before(self):
        # The default bar is 16% of the width, capped at 230 px - what every map
        # saved before this change was drawn with, so nothing already made moves.
        for width, expected in ((1200, 192.0), (1400, 224.0), (1600, 230.0),
                                (1800, 230.0), (2400, 230.0)):
            gm = blank(width, scale_text="100 leagues")
            self.assertAlmostEqual(drawn_bar_px(gm), expected, places=6)

    def test_names_keep_off_the_bar_that_is_actually_drawn(self):
        # layout_pin_labels reserved `min(width * 0.16, 230)` itself, separately
        # from the drawing. A pin whose name sits just past the drawn bar must
        # keep its preferred side; if the reservation grows to a fifth of the
        # width (360 px) that side is blocked and the name is moved or dropped.
        gm = blank(1800, scale_text="200 leagues")
        left = gm.width * 0.045
        top = gm.height - gm.height * 0.052
        pin = mm.Pin(x=left + 300, y=top - 5, kind="town", label="Ash",
                     label_side="e")
        gm.pins.append(pin)
        self.assertEqual(mm.layout_pin_labels(gm)[pin.id], ("e", True))

    def test_a_bar_with_its_own_length_is_read_back_the_same_way(self):
        gm = blank(1800, scale_text="80 miles", scale_px=120.0)
        self.assertAlmostEqual(drawn_bar_px(gm), 120.0, places=6)
        self.assertAlmostEqual(mapstory.read_scale(gm).units_per_pixel, 80 / 120.0)

    def test_no_caption_no_bar_and_no_invented_distance(self):
        gm = blank(1600)
        self.assertFalse(mm.scale_bar(gm).label)
        self.assertFalse(mapstory.read_scale(gm).known)
        self.assertIsNone(mapstory.distance(gm, mm.Pin(), mm.Pin(x=90, y=0)))
        words = blank(1600, scale_text="a long walk")
        self.assertTrue(mm.scale_bar(words).label)             # still drawn ...
        self.assertFalse(mapstory.read_scale(words).known)     # ... but no number

    def test_a_map_from_an_older_file_still_opens_and_measures(self):
        old = {"id": "map_old", "name": "Old", "width": 1600, "height": 1100,
               "scale_text": "100 leagues", "layers": [{"name": "Base"}],
               "pins": [{"id": "p1", "x": 10, "y": 10, "label": "A"}]}
        gm = mm.GameMap.from_json(old)
        self.assertEqual(gm.scale_px, 0.0)
        self.assertFalse(gm.legend)
        self.assertEqual(gm.parent, {})
        self.assertAlmostEqual(mapstory.read_scale(gm).bar_pixels, 230.0)
        back = mm.GameMap.from_json(gm.to_json())
        self.assertEqual(back.scale_px, 0.0)


class NiceNumbers(unittest.TestCase):
    def test_floor_ceil_and_round_are_ones_twos_and_fives(self):
        floor = [(19.2, 10), (20, 20), (49.9, 20), (50, 50), (99, 50),
                 (100, 100), (0.037, 0.02), (0.5, 0.5), (1, 1), (7.4e3, 5000)]
        for value, expected in floor:
            self.assertAlmostEqual(mm.nice_number(value, "floor"), expected,
                                   msg=f"floor({value})", places=9)
        for value, expected in ((21, 50), (50, 50), (51, 100), (0.11, 0.2)):
            self.assertAlmostEqual(mm.nice_number(value, "ceil"), expected,
                                   msg=f"ceil({value})", places=9)
        for value, expected in ((3, 2), (4, 5), (140, 100), (160, 200)):
            self.assertAlmostEqual(mm.nice_number(value, "round"), expected,
                                   msg=f"round({value})", places=9)
        self.assertEqual(mm.nice_number(0), 0.0)
        self.assertEqual(mm.nice_number(-4), 0.0)

    def test_every_answer_is_a_one_two_or_five(self):
        for i in range(1, 400):
            value = 1.037 ** i
            for mode in ("floor", "ceil", "round"):
                answer = mm.nice_number(value, mode)
                lead = answer / 10.0 ** math.floor(math.log10(answer) + 1e-9)
                self.assertTrue(any(abs(lead - s) < 1e-6 for s in (1, 2, 5)),
                                f"{mode}({value}) = {answer}")


class UnitsAndCaptions(unittest.TestCase):
    MILES = (("10 ft", 10 / 5280), ("10 feet", 10 / 5280), ("3 yards", 9 / 5280),
             ("2 yd", 6 / 5280), ("40 paces", 100 / 5280), ("50 metres", 0.0310686),
             ("50 m", 0.0310686), ("2 km", 1.242742), ("2 kilometers", 1.242742),
             ("1 mile", 1.0), ("4 mi", 4.0), ("2 leagues", 6.0),
             ("3 days", 60.0))

    def test_every_unit_reads_and_converts(self):
        for caption, miles in self.MILES:
            gm = blank(1600, scale_text=caption)
            scale = mapstory.read_scale(gm)
            self.assertTrue(scale.known, caption)
            amount = float(caption.split()[0])
            self.assertAlmostEqual(scale.to_miles(amount), miles, delta=miles * 1e-3,
                                   msg=caption)

    def test_the_stars_are_measured_in_their_own_units(self):
        one = {"4 parsecs": 4, "4 pc": 4, "3 AU": 3, "3 au": 3,
               "6 light years": 6, "6 light-years": 6, "6 ly": 6}
        for caption, amount in one.items():
            scale = mapstory.read_scale(blank(1600, scale_text=caption))
            self.assertTrue(scale.known, caption)
            self.assertTrue(scale.astronomical, caption)
            self.assertIsNotNone(scale.to_miles(amount), caption)
        # a parsec is about 19 trillion miles - nobody wants that printed
        gm = blank(1600, scale_text="4 parsecs")
        text = mapstory.describe_distance(gm, mm.Pin(x=0, y=0), mm.Pin(x=230, y=0))
        self.assertEqual(text, "4 parsecs")

    def test_a_caption_with_thousands_and_decimals_and_trailing_words(self):
        self.assertEqual(mm.parse_scale_caption("1,500 miles"), (1500.0, "miles"))
        self.assertEqual(mm.parse_scale_caption("12.5 km"), (12.5, "km"))
        self.assertEqual(mm.parse_scale_caption("200 leagues wide"),
                         (200.0, "leagues"))
        self.assertEqual(mm.parse_scale_caption("3 Light Years"),
                         (3.0, "light years"))
        self.assertEqual(mm.parse_scale_caption("75"), (75.0, "units"))
        self.assertIsNone(mm.parse_scale_caption("a long walk"))
        self.assertIsNone(mm.parse_scale_caption("0 miles"))
        self.assertIsNone(mm.parse_scale_caption(""))

    def test_captions_agree_with_their_number(self):
        self.assertEqual(mm.scale_caption(1, "miles"), "1 mile")
        self.assertEqual(mm.scale_caption(5, "mile"), "5 miles")
        self.assertEqual(mm.scale_caption(10, "ft"), "10 ft")
        self.assertEqual(mm.scale_caption(1, "parsecs"), "1 parsec")
        self.assertEqual(mm.scale_caption(1000, "leagues"), "1,000 leagues")
        self.assertEqual(mm.scale_caption(0.5, "miles"), "0.5 miles")
        self.assertEqual(mm.scale_caption(2, "AU"), "2 AU")
        self.assertEqual(mm.scale_caption(3, "quarrels"), "3 quarrels")

    def test_a_scale_that_is_only_a_number_is_still_a_scale(self):
        scale = mapstory.read_scale(blank(1600, scale_text="75"))
        self.assertTrue(scale.known)
        self.assertEqual(scale.unit, "units")
        self.assertIsNone(scale.to_miles(75))                 # no unit, no miles


class ApplyScale(unittest.TestCase):
    CASES = (("ft", 5, 60, 1600), ("ft", 5, 40, 1200), ("miles", 10, 80, 1800),
             ("miles", 3, 50, 2400), ("parsecs", 1, 90, 1600),
             ("leagues", 25, 120, 1600), ("km", 0.5, 30, 1200))

    def test_the_caption_the_bar_and_the_grid_cannot_disagree(self):
        # Breaking it: leave `scale_px` unset in apply_scale and the bar is drawn
        # at its default length while the grid square still means per_cell.
        for unit, per_cell, cell, width in self.CASES:
            gm = blank(width, grid="square", grid_size=cell)
            bar = mm.apply_scale(gm, unit, per_cell)
            what = f"{per_cell} {unit} per {cell}px on {width}px"
            self.assertTrue(bar.known, what)
            # the caption carries a round number ...
            lead = bar.value / 10.0 ** math.floor(math.log10(bar.value) + 1e-9)
            self.assertTrue(any(abs(lead - s) < 1e-6 for s in (1, 2, 5)), what)
            # ... the picture draws exactly the bar that number needs ...
            self.assertAlmostEqual(drawn_bar_px(gm), bar.value / per_cell * cell,
                                   places=6, msg=what)
            # ... it fits where a bar goes, without shrinking to a stub ...
            room = min(width * 0.16, 230.0)
            self.assertLessEqual(drawn_bar_px(gm), room + 1e-6, what)
            self.assertGreaterEqual(drawn_bar_px(gm), room * 0.4 - 1e-6, what)
            # ... and one grid square is worth `per_cell`, as read by the story.
            a, b = mm.Pin(x=0, y=0), mm.Pin(x=cell, y=0)
            self.assertAlmostEqual(mapstory.distance(gm, a, b), per_cell,
                                   places=6, msg=what)
            self.assertAlmostEqual(mm.cell_units(gm), per_cell, places=6, msg=what)

    def test_five_feet_a_square_on_a_dungeon(self):
        gm = blank(1600, grid="square", grid_size=60)
        mm.apply_scale(gm, "ft", 5)
        self.assertEqual(gm.scale_text, "10 ft")
        self.assertAlmostEqual(gm.scale_px, 120.0)
        self.assertEqual(gm.grid_size, 60)

    def test_giving_the_square_size_sets_the_grid_too(self):
        gm = blank(1600, grid="square", grid_size=80)
        mm.apply_scale(gm, "ft", 5, cell_px=57.6)
        self.assertEqual(gm.grid_size, 58)                    # whole pixels
        a, b = mm.Pin(x=0, y=0), mm.Pin(x=58, y=0)
        self.assertAlmostEqual(mapstory.distance(gm, a, b), 5.0, places=6)

    def test_a_scale_is_saved_and_comes_back(self):
        gm = blank(1600, grid="square", grid_size=60)
        mm.apply_scale(gm, "ft", 5)
        again = mm.GameMap.from_json(gm.to_json())
        self.assertEqual((again.scale_text, again.scale_px, again.grid_size),
                         (gm.scale_text, gm.scale_px, gm.grid_size))
        self.assertAlmostEqual(drawn_bar_px(again), drawn_bar_px(gm))

    def test_nonsense_is_refused(self):
        gm = blank(1600)
        for bad in (0, -3, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                mm.apply_scale(gm, "miles", bad)

    def test_mapstory_offers_the_same_helper(self):
        self.assertIs(mapstory.apply_scale, mm.apply_scale)


class OtherScaleUsers(unittest.TestCase):
    def test_a_generated_world_measures_in_leagues_and_says_so(self):
        gm = mapgen.generate(mapgen.preset("Classic fantasy world", 7))
        bar = drawn_bar_px(gm)
        text = mapstory.describe_distance(gm, mm.Pin(x=0, y=0),
                                          mm.Pin(x=bar, y=0))
        self.assertEqual(text, "200 leagues (about 600 miles)")


if __name__ == "__main__":
    unittest.main()
