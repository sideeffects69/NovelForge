"""
GUI smoke test: launch the real main window against a throwaway install and
exercise it.

This exists because the failures that matter here are the ones nobody sees from
reading code - a toolbar pushed past the edge of its window, a button that
vanished, a theme that leaves one widget white, a first map that opens as a
thumbnail. It checks the window really lays out, on every theme.

Needs Windows (the app is Windows-only) and a display; skipped otherwise.
Message boxes and file dialogs are stubbed (see gui_support.py): a native modal
box would freeze the test.
"""

import sys
import tkinter as tk
import unittest

from tests import SANDBOX, require_isolation

require_isolation()

from novelforge.config import THEMES  # noqa: E402
from tests.gui_support import Sandbox  # noqa: E402
from tools.uishots.clipping import clipped_content  # noqa: E402

TITLE = "Smoke Test Novel"


def _everything(root):
    """Every widget under `root`, tool windows included."""
    stack = list(root.winfo_children())
    while stack:
        widget = stack.pop()
        yield widget
        stack.extend(widget.winfo_children())


@unittest.skipUnless(sys.platform == "win32", "NovelForge is Windows-only")
class MainWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox(title=TITLE, name="smoke").start()
        cls.app = cls.box.app
        cls.errors = cls.box.errors
        cls.scene_id = next(s.id for s in cls.app.project.data.scenes
                            if s.word_count)

    @classmethod
    def tearDownClass(cls):
        cls.box.stop()

    def pump(self, seconds):
        self.box.pump(seconds)

    def setUp(self):
        # Every test starts from the same sandbox project, on the warm theme.
        self.assertIsNotNone(self.app.project)
        self.assertEqual(self.app.project.data.title, TITLE)
        self.assertTrue(
            str(self.app.project.root).lower().startswith(str(SANDBOX).lower()),
            "the test opened something outside its sandbox")

    def tearDown(self):
        self.assertEqual(self.errors, [], "exception raised inside a Tk callback")

    # ------------------------------------------------------------------
    def test_the_menu_bar_is_drawn_by_the_app_and_every_menu_is_there(self):
        self.assertEqual(self.app.cget("menu"), "")            # no native bar
        labels = [b.cget("text") for b in self.app.menu_strip.winfo_children()]
        self.assertEqual(labels, ["File", "Add", "Edit", "Manuscript", "Tools",
                                  "Plan", "View", "Help"])

    def test_the_theme_menu_offers_every_theme(self):
        entries = [self.app.theme_menu.entrycget(i, "label")
                   for i in range(self.app.theme_menu.index("end") + 1)]
        self.assertEqual(sorted(e.lower() for e in entries), sorted(THEMES))

    def test_menu_clones_follow_changes_to_the_original(self):
        # Undo/Redo and Open Recent are rewritten at runtime; the bar shows
        # clones of them, so a clone that stopped tracking would go stale.
        bar = self.app.menubar
        first = next(i for i in range(bar.index("end") + 1)
                     if bar.type(i) == "cascade")       # index 0 is a tearoff
        file_menu = bar.nametowidget(bar.entrycget(first, "menu"))
        original = file_menu.entrycget(0, "label")
        button = self.app.menu_strip.winfo_children()[0]
        clone = str(button.cget("menu"))
        try:
            file_menu.entryconfigure(0, label="Renamed at runtime")
            self.assertEqual(self.app.tk.call(clone, "entrycget", 0, "-label"),
                             "Renamed at runtime")
        finally:
            file_menu.entryconfigure(0, label=original)

    def test_the_main_window_fits_on_every_theme(self):
        try:
            for name in THEMES:
                self.app.cmd_theme(name)
                self.pump(0.3)
                self.assertEqual(clipped_content(self.app), [], name)
                self.assertTrue(self.app.menu_strip.winfo_exists(), name)
        finally:
            self.app.cmd_theme("warm")
            self.pump(0.2)

    def test_switching_theme_recolours_what_is_already_on_screen(self):
        # View > Theme used to restyle only what was built afterwards, so the
        # inspector's text boxes stayed cream in a dark window until the writer
        # clicked something else.
        from novelforge.ui import styling
        from tkinter import Menu

        app = self.app
        app.tree.selection_set(f"scene:{self.scene_id}")      # inspector has Text + Listbox
        self.pump(0.5)
        opened = tk.Toplevel(app)                             # a tool window left open
        stray = tk.Text(opened)
        stray.pack()
        try:
            for name in ("premium", "light", "dark", "warm"):
                app.cmd_theme(name)
                self.pump(0.3)
                want = styling.current_tokens()
                wrong = []
                for widget in _everything(app):
                    if widget.winfo_class() in ("Text", "Entry", "Spinbox", "Listbox"):
                        have = str(widget.cget("background")).lower()
                        if have != want["field"]:
                            wrong.append(f"{widget.winfo_class()} {str(widget)[-28:]} {have}")
                self.assertEqual(wrong, [], f"{name}: stale colours")
                popup = Menu(app, tearoff=0)
                self.assertEqual(str(popup.cget("background")).lower(), want["raised"],
                                 f"{name}: right-click menus ignore the theme")
                popup.destroy()
        finally:
            opened.destroy()
            app.cmd_theme("warm")
            self.pump(0.2)

    def test_the_toolbar_collapses_to_icons_instead_of_overflowing(self):
        if not self.app.icons.available:
            self.skipTest("no icon font on this machine")
        width, height = self.app.minsize()
        try:
            self.app.geometry(f"{width}x{max(height, 600)}+0+0")
            self.pump(0.6)
            self.assertTrue(self.app._toolbar_compact)
            toolbar_problems = [p for p in clipped_content(self.app)
                                if "Tool" in p or "Gauge" in p or "toolbar" in p]
            self.assertEqual(toolbar_problems, [])
        finally:
            self.app.geometry("1340x680+0+0")
            self.pump(0.6)
        self.assertFalse(self.app._toolbar_compact)     # and comes back

    def test_save_state_follows_the_editor(self):
        app = self.app
        app.tree.selection_set(f"scene:{self.scene_id}")
        self.pump(0.6)
        self.assertEqual(app.status._save_state, "saved")
        app.editor.text.insert("end", " More.")
        self.pump(0.4)
        self.assertEqual(app.status._save_state, "dirty")
        self.assertIn("Unsaved", app.status.state_label.cget("text"))
        app.save_editor(snapshot=False)
        self.assertEqual(app.status._save_state, "saved")

    def test_the_command_palette_finds_commands_from_the_menus(self):
        from novelforge.ui import palette

        entries = palette.collect(self.app.menubar)
        paths = [e.path for e in entries]
        self.assertGreater(len(entries), 60)
        self.assertTrue(any(p.endswith("Story Graph...") for p in paths))
        opened = palette.CommandPalette(self.app)
        try:
            opened.query.set("story graph")
            self.pump(0.2)
            self.assertTrue(opened.shown)
            self.assertTrue(opened.shown[0].path.endswith("Story Graph..."))
            opened.query.set("zzzzqq")
            self.pump(0.2)
            self.assertEqual(opened.shown, [])
        finally:
            opened.close()

    def test_reports_get_real_headings_not_underlines(self):
        from novelforge.ui.widgets import ScrolledText

        view = ScrolledText(self.app, height=10)
        try:
            view.set_report("MY REPORT\n=========\n\nCHAPTERS\n  One   12\n\n"
                            "----------\nplain line")
            shown = view.get_value()
            self.assertNotIn("=====", shown)
            self.assertNotIn("-----", shown)
            self.assertIn("MY REPORT", shown)
            self.assertIn("  One   12", shown)          # tables keep alignment
            names = view.text.tag_names("1.0")
            self.assertIn("rp_h1", names)
        finally:
            view.destroy()

    def test_dialogs_and_reports_fit_their_windows(self):
        app = self.app
        app.tree.selection_set(f"scene:{self.scene_id}")
        self.pump(0.4)
        openers = [
            ("preferences", app.cmd_preferences),
            ("project settings", app.cmd_project_settings),
            ("corkboard", app.cmd_corkboard),
            ("outline", app.cmd_outline_window),
            ("timeline", app.cmd_timeline_window),
            ("story graph", app.cmd_story_graph),
            ("search", app.cmd_search),
            ("shortcuts", app.cmd_shortcuts),
            ("diagnostics", lambda: app.cmd_diagnostics("scene")),
            ("map maker", app.cmd_map_editor),
            ("sprint", app.cmd_sprint),
            ("names", app.cmd_names),
        ]
        problems = {}
        for name, opener in openers:
            before = set(app.winfo_children())

            def inspect(name=name, before=before):
                for w in app.winfo_children():
                    if isinstance(w, tk.Toplevel) and w not in before:
                        # Let layout that is still pending finish: a widget that
                        # has been placed but not yet drawn reads as "hidden",
                        # and how long a window takes to build is not what this
                        # test is about (a slow build is guarded separately).
                        w.update_idletasks()
                        found = clipped_content(w)
                        if found:
                            problems[name] = found[:3]
                        w.destroy()
                        return
                problems[name] = ["no window appeared"]

            app.after(700, inspect)          # runs inside a modal loop too
            opener()
            self.pump(1.0)
            for w in list(app.winfo_children()):
                if isinstance(w, tk.Toplevel) and w not in before:
                    w.destroy()
        self.assertEqual(problems, {})

    def test_the_first_map_opens_fitted_to_the_window(self):
        app = self.app
        before = set(app.winfo_children())
        app.cmd_map_editor()
        self.pump(1.2)
        editor = next(w for w in app.winfo_children()
                      if isinstance(w, tk.Toplevel) and w not in before)
        try:
            share = editor.gm.width * editor.zoom / max(1, editor.canvas.winfo_width())
            self.assertGreater(share, 0.75,
                               "the map opened as a thumbnail, not fitted")
            editor._pan_by(25, 10)               # the writer takes over the view
            zoom, offset = editor.zoom, editor.offset_x
            editor.geometry("1100x640+0+0")
            self.pump(0.6)
            self.assertEqual((editor.zoom, editor.offset_x), (zoom, offset),
                             "a resize moved a view the writer had set")
        finally:
            editor.destroy()

    def test_distraction_free_keeps_the_menu_and_hides_the_toolbar(self):
        app = self.app
        app.cmd_toggle_distraction_free()
        self.pump(0.3)
        try:
            self.assertFalse(app.toolbar.winfo_ismapped())
            self.assertTrue(app.menu_strip.winfo_ismapped())
        finally:
            app.cmd_toggle_distraction_free()
            self.pump(0.3)
        self.assertTrue(app.toolbar.winfo_ismapped())


if __name__ == "__main__":
    unittest.main()
