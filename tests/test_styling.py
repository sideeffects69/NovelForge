"""
Pure-logic tests for the theme maths and the command palette's matcher.
No window is opened, so these are instant and run anywhere.
"""

import unittest

from tests import require_isolation

require_isolation()

from novelforge.config import THEMES  # noqa: E402
from novelforge.ui import styling  # noqa: E402
from novelforge.ui.palette import score  # noqa: E402

BASE_KEYS = {"bg", "fg", "panel", "panel_fg", "accent", "dim", "select",
             "caret", "gutter"}


class ColourMaths(unittest.TestCase):
    def test_mix_endpoints_and_midpoint(self):
        self.assertEqual(styling.mix("#000000", "#ffffff", 0), "#000000")
        self.assertEqual(styling.mix("#000000", "#ffffff", 1), "#ffffff")
        self.assertEqual(styling.mix("#000000", "#ffffff", 0.5), "#808080")

    def test_contrast_matches_the_wcag_extremes(self):
        self.assertAlmostEqual(styling.contrast("#000000", "#ffffff"), 21.0, 1)
        self.assertAlmostEqual(styling.contrast("#777777", "#777777"), 1.0, 3)

    def test_three_digit_hex_is_accepted(self):
        self.assertEqual(styling.mix("#fff", "#000", 0), "#ffffff")

    def test_ensure_contrast_only_moves_what_is_too_faint(self):
        self.assertEqual(styling.ensure_contrast("#000000", "#ffffff"), "#000000")
        fixed = styling.ensure_contrast("#cccccc", "#ffffff", 4.5)
        self.assertGreaterEqual(styling.contrast(fixed, "#ffffff"), 4.5)


class EveryTheme(unittest.TestCase):
    def test_every_palette_has_the_nine_base_colours(self):
        for name, palette in THEMES.items():
            self.assertTrue(BASE_KEYS <= set(palette), name)

    def test_secondary_text_is_legible_in_every_theme(self):
        # `dim` sat around 2:1 on the warm panel - too faint to read hints in.
        for name, palette in THEMES.items():
            t = styling.tokens(palette)
            self.assertGreaterEqual(
                styling.contrast(t["text_dim"], t["panel"]), 4.5, name)

    def test_text_on_the_accent_colour_is_legible(self):
        for name, palette in THEMES.items():
            t = styling.tokens(palette)
            self.assertGreaterEqual(
                styling.contrast(t["on_accent"], t["accent"]), 3.0, name)

    def test_the_dark_flag_follows_the_panel(self):
        self.assertTrue(styling.tokens(THEMES["premium"])["dark"])
        self.assertTrue(styling.tokens(THEMES["dark"])["dark"])
        self.assertFalse(styling.tokens(THEMES["warm"])["dark"])
        self.assertFalse(styling.tokens(THEMES["light"])["dark"])

    def test_derived_colours_are_well_formed_hex(self):
        for name, palette in THEMES.items():
            for key, value in styling.tokens(palette).items():
                if isinstance(value, str) and value.startswith("#"):
                    self.assertRegex(value, r"^#[0-9a-f]{6}$", f"{name}.{key}")


class PaletteMatching(unittest.TestCase):
    def test_a_missing_word_rules_an_entry_out(self):
        self.assertIsNone(score(["backup"], "File › Save"))

    def test_letters_in_order_match(self):
        self.assertIsNotNone(score(["sgraph"], "Plan › Story Graph..."))

    def test_a_word_start_beats_a_mid_word_hit(self):
        word_start = score(["graph"], "Plan › Graph view")
        mid_word = score(["graph"], "Plan › Paragraph view")
        self.assertGreater(word_start, mid_word)

    def test_every_token_must_match(self):
        self.assertIsNone(score(["story", "zzz"], "Plan › Story Graph..."))
        self.assertIsNotNone(score(["story", "graph"], "Plan › Story Graph..."))


if __name__ == "__main__":
    unittest.main()
