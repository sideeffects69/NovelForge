"""
The Map Maker window: does it fit, and does every control in it work?

`test_maps.py` covers the engine without a window. This opens the real editor in
the sandbox (a throwaway novel and settings, native dialogs stubbed) and uses it.
"""

import sys
import unittest

from tests import require_isolation

require_isolation()

from tests.gui_support import Sandbox  # noqa: E402
from tests.test_gui_walk import Walker, descendants  # noqa: E402
from tools.uishots.clipping import clipped_content  # noqa: E402


@unittest.skipUnless(sys.platform == "win32", "NovelForge is Windows-only")
class MapMaker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from novelforge import mapgen
        from novelforge.ui.mapeditor import MapEditor

        cls.box = Sandbox(title="Map Test Novel", name="maptest").start()
        cls.app = cls.box.app
        cls.editor = MapEditor(cls.app, cls.app.project)
        cls.box.pump(0.6)
        cls.editor.gm = mapgen.generate(mapgen.preset("Classic fantasy world", 7))
        cls.editor.map_file = None
        cls.editor._after_load()
        cls.box.pump(0.6)

    @classmethod
    def tearDownClass(cls):
        try:
            if cls.editor.winfo_exists():
                cls.editor.destroy()
        finally:
            cls.box.stop()

    # ------------------------------------------------------------------
    def test_it_fits_its_window_in_every_theme(self):
        ed, box = self.editor, self.box
        problems = {}
        for theme in ("premium", "warm", "light", "dark"):
            self.app.cmd_theme(theme)
            box.pump(0.5)
            found = clipped_content(ed)
            if found:
                problems[theme] = found[:4]
        self.app.cmd_theme("warm")
        box.pump(0.3)
        self.assertEqual(problems, {})
        self.assertEqual(box.errors, [])

    def test_every_tool_on_the_rail_can_be_chosen(self):
        from novelforge.ui.mapeditor import TOOLS

        ed = self.editor
        chosen = []
        for button, icon in ed._rail_buttons:
            self.assertIsNotNone(ed.icons.get(icon, "#ffffff"), f"no icon for {icon}")
            button.invoke()
            self.box.pump(0.05)
            key = str(button.cget("value"))
            chosen.append(key)
            self.assertEqual(ed.tool.get(), key)
            label = next(l for k, l, _h in TOOLS if k == key)
            self.assertEqual(ed.tool_name.cget("text"), label)
            self.assertTrue(ed.tool_hint.cget("text"))
        self.assertEqual(chosen, [k for k, _l, _h in TOOLS])
        ed.tool.set("select")
        ed._on_tool_change()

    def test_both_dropdowns_open_and_every_item_in_them_works(self):
        ed, box = self.editor, self.box
        walker = Walker(box)
        for name, menu in (("Export", ed.export_menu), ("More", ed.more_menu)):
            self.assertFalse(menu.is_open)
            menu.open()
            box.pump(0.15)
            self.assertTrue(menu.is_open, f"{name} did not open")
            menu.close()
            for label, _command in menu.items:
                if label == "-":
                    continue
                menu.open()
                box.pump(0.15)
                button = next(w for w in descendants(menu.popup)
                              if w.winfo_class() == "TButton"
                              and str(w.cget("text")) == label)
                walker.run(f"{name} > {label}", button.invoke, settle=0.4)
                self.assertFalse(menu.is_open, f"choosing {label!r} left the list open")
        self.assertEqual(walker.problems, [])

    def test_a_dropdown_closes_on_escape_and_when_toggled(self):
        ed, box = self.editor, self.box
        menu = ed.export_menu
        menu.toggle()
        box.pump(0.1)
        self.assertTrue(menu.is_open)
        menu.popup.event_generate("<Escape>")
        box.pump(0.1)
        self.assertFalse(menu.is_open)
        menu.toggle()
        menu.toggle()
        box.pump(0.1)
        self.assertFalse(menu.is_open)

    def test_zooming_shows_at_once_and_redraws_only_when_it_settles(self):
        ed, box = self.editor, self.box
        ed.cmd_zoom_fit()
        box.pump(0.3)
        calls = []
        real = ed.redraw
        ed.redraw = lambda: (calls.append(1), real())[1]
        try:
            start = ed.zoom
            left, _top, right, _bottom = ed.canvas.bbox("all")
            for _ in range(6):
                ed._zoom_by(1.15)
            self.assertGreater(ed.zoom, start * 1.5)
            self.assertEqual(calls, [], "every wheel tick rebuilt the whole map")
            # ...and yet the picture is already bigger: the items on screen are
            # scaled at once, not left as they were until the redraw arrives.
            now = ed.canvas.bbox("all")
            self.assertGreater((now[2] - now[0]) / float(right - left), 1.8,
                               "zooming did nothing on screen until the redraw")
            box.pump(0.6)
            self.assertEqual(len(calls), 1, "the settled zoom should redraw exactly once")
        finally:
            ed.redraw = real
        ed.cmd_zoom_fit()
        box.pump(0.3)

    def test_redrawing_does_not_rebuild_the_map(self):
        from novelforge import mapmaker as mm

        ed = self.editor
        ed.redraw()                                    # warm the cache
        real, calls = mm._build_primitives, []
        mm._build_primitives = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
        try:
            for _ in range(3):
                ed.redraw()
        finally:
            mm._build_primitives = real
        self.assertEqual(calls, [], "a redraw with nothing changed rebuilt the display list")

    def test_surprise_me_builds_a_world_that_fills_the_window(self):
        ed, box = self.editor, self.box
        ed.cmd_surprise()
        box.pump(0.6)
        self.assertTrue(any(s.kind == "land" for s in ed.gm.shapes))
        self.assertTrue(ed._auto_fit)
        self.assertGreater(ed.zoom, 0.25)
        self.assertGreater(len(ed.canvas.find_all()), 200)
        self.assertEqual(box.errors, [])

    def test_drawing_a_shape_and_undoing_it(self):
        ed = self.editor
        before = len(ed.gm.shapes)
        ed.terrain_kind.set("forest")
        ed._commit_shape([(200, 200), (500, 200), (500, 420), (200, 420)])
        self.assertEqual(len(ed.gm.shapes), before + 1)
        self.assertEqual(ed.gm.shapes[-1].kind, "forest")
        ed.cmd_undo()
        self.assertEqual(len(ed.gm.shapes), before)

    def test_an_empty_map_says_how_to_begin(self):
        from novelforge import mapmaker as mm

        ed, box = self.editor, self.box
        kept = (ed.gm, ed.map_file)
        try:
            ed.gm, ed.map_file = mm.GameMap(name="Blank"), None
            ed._after_load()
            box.pump(0.4)
            words = [ed.canvas.itemcget(i, "text").lower()
                     for i in ed.canvas.find_all() if ed.canvas.type(i) == "text"]
            self.assertTrue(any("empty map" in w for w in words), words)
        finally:
            ed.gm, ed.map_file = kept
            ed._after_load()
            box.pump(0.3)


if __name__ == "__main__":
    unittest.main()
