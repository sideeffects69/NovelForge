"""
Getting around the book, in a real window: Go to (Ctrl+P) and the Connections panel.

Go to: it opens from the menu, the palette and the keyboard - including with the
caret in the editor, where Ctrl+P must not also move it - lists the last places
visited when the box is empty, jumps to what is chosen, closes on Escape and when
focus leaves, and fits at 100% and 125%.
"""

import sys
import tkinter as tk
import unittest

from tests import SANDBOX, require_isolation

require_isolation()

from novelforge.config import settings  # noqa: E402
from tests.gui_support import Sandbox  # noqa: E402
from tools.uishots.clipping import clipped_content  # noqa: E402

TITLE = "Navigation Test Novel"


def open_goto(app, stay=True):
    """
    Open Go to the way Ctrl+P does, and return the window.

    `stay` stops it closing itself when this test window cannot hold keyboard
    focus (which is what it is meant to do when focus leaves); the one test about
    closing turns it off.
    """
    app.cmd_goto()
    window = app._goto
    assert window.winfo_exists()
    if stay:
        window._maybe_close = lambda: None
    return window


@unittest.skipUnless(sys.platform == "win32", "NovelForge is Windows-only")
class GoToWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox(title=TITLE, name="nav").start()
        cls.app = cls.box.app
        data = cls.app.project.data
        cls.scenes = [s for s in data.ordered_scenes() if s.word_count]
        cls.warden = next(e for e in data.entities if e.name == "Warden Tholve")

    @classmethod
    def tearDownClass(cls):
        settings["goto_recent"] = {}
        settings["palette_recent"] = []
        cls.box.stop()

    def setUp(self):
        self.assertEqual(self.app.project.data.title, TITLE)
        self.assertTrue(str(self.app.project.root).lower().startswith(str(SANDBOX).lower()))
        self._reset()

    def tearDown(self):
        self._close()
        self.assertEqual(self.box.errors, [], "exception raised inside a Tk callback")

    def _close(self):
        window = getattr(self.app, "_goto", None)
        if window is not None:
            try:
                window.close()
            except tk.TclError:
                pass
        self.app._goto = None

    def _reset(self):
        self._close()
        self.app._nav_recents = None
        settings["goto_recent"] = {}
        self.app.goto("scene", self.scenes[0].id)
        self.box.pump(0.3)

    # -- opening --------------------------------------------------------
    def test_edit_menu_has_go_to_and_the_palette_finds_it(self):
        from novelforge.ui import palette

        entry = next((e for e in palette.collect(self.app.menubar)
                      if e.path.endswith("Go to...")), None)
        self.assertIsNotNone(entry, "Edit > Go to... is missing")
        self.assertIn("Edit", entry.path)
        self.assertEqual(entry.accelerator, "Ctrl+P")
        entry.menu.invoke(entry.index)
        self.box.pump(0.2)
        self.assertTrue(self.app._goto.winfo_exists())

    def test_ctrl_p_is_wired_and_a_second_press_closes_it(self):
        app = self.app
        self.assertIn("<Control-p>", app.shortcuts)
        self.assertTrue(app.bind_all("<Control-p>"))
        window = open_goto(app)
        app.shortcuts["<Control-p>"](None)              # what the key does
        self.box.pump(0.1)
        self.assertFalse(window.winfo_exists(), "Ctrl+P again should close it")

    def test_ctrl_p_in_the_editor_opens_go_to_and_leaves_the_caret_alone(self):
        app, box = self.app, self.box
        # The Text class binding must be ours (one that stops there): Tk's own is
        # "cursor up a line" on some platforms, and both must not run.
        self.assertIn("break", str(app.tk.call("bind", "Text", "<Control-p>")))
        app.goto("scene", self.scenes[0].id)
        box.pump(0.5)
        app.focus_force()
        box.pump(0.3)
        if app.focus_get() is None:
            self.skipTest("this test window cannot take keyboard focus")
        text = app.editor.text
        text.focus_set()
        last = int(text.index("end-1c").split(".")[0])
        text.mark_set("insert", f"{min(3, last)}.2")
        box.pump(0.1)
        caret, body = text.index("insert"), app.editor.get_value()
        text.event_generate("<Control-p>")
        box.pump(0.3)
        window = getattr(app, "_goto", None)
        self.assertTrue(window is not None and window.winfo_exists(),
                        "Ctrl+P with the caret in the editor did not open Go to")
        self.assertEqual(text.index("insert"), caret, "the caret moved")
        self.assertEqual(app.editor.get_value(), body, "the text changed")

    def test_no_novel_open_asks_for_one_instead_of_opening(self):
        app = self.app
        project, app.project = app.project, None
        asked = self.box.calls.count("showinfo")
        try:
            app.cmd_goto()
        finally:
            app.project = project
        self.assertIsNone(getattr(app, "_goto", None))
        self.assertEqual(self.box.calls.count("showinfo"), asked + 1)

    # -- typing and jumping --------------------------------------------
    def test_typing_finds_a_character_by_name_and_enter_goes_there(self):
        app, box = self.app, self.box
        window = open_goto(app)
        window.query.set("tholve")
        window.refill()
        self.assertTrue(window.shown)
        self.assertEqual(window.shown[0].key, f"entity:{self.warden.id}")
        self.assertEqual(window.tree.selection(), ("0",))
        window._run()
        box.pump(0.4)
        self.assertEqual((app.selection_kind, app.selection_id),
                         ("entity", self.warden.id))
        self.assertEqual(app.tree.selection(), (f"entity:{self.warden.id}",))
        self.assertEqual(app.centre_title.cget("text"), "Warden Tholve")
        self.assertFalse(window.winfo_exists(), "Enter should close the box")

    def test_enter_on_a_scene_selects_its_row_and_opens_it_in_the_editor(self):
        app, box = self.app, self.box
        target = self.scenes[1]
        window = open_goto(app)
        window.query.set(target.title.lower())
        window.refill()
        self.assertEqual(window.shown[0].key, f"scene:{target.id}")
        window._run()
        box.pump(0.5)
        self.assertEqual(app.current_scene_id, target.id)
        self.assertEqual(app.tree.selection(), (f"scene:{target.id}",))
        self.assertTrue(app.editor.winfo_ismapped())
        self.assertEqual(app.centre_title.cget("text"), target.title)

    def test_it_can_open_something_inside_a_collapsed_chapter(self):
        app, box = self.app, self.box
        target = self.scenes[-1]
        parent = app.tree.parent(f"scene:{target.id}")
        app.tree.item(parent, open=False)
        box.pump(0.1)
        window = open_goto(app)
        window.query.set(target.title.lower())
        window.refill()
        window._run()
        box.pump(0.4)
        self.assertTrue(app.tree.item(parent, "open"), "the chapter was left closed")
        self.assertEqual(app.tree.selection(), (f"scene:{target.id}",))

    def test_every_kind_of_thing_can_be_reached(self):
        app, box = self.app, self.box
        data = app.project.data
        wanted = {
            "chapter": data.chapters[0].title,
            "location": "vaelmoor",
            "note": "siege engines",
            "event": "kessa reaches",
            "beat": data.beats[0].name,
        }
        window = open_goto(app)
        for kind, text in wanted.items():
            window.query.set(text)
            window.refill()
            self.assertTrue(any(t.kind == kind for t in window.shown),
                            f"nothing of kind {kind!r} for {text!r}: "
                            f"{[t.title for t in window.shown]}")
        # A map or a loose document: whatever the binder lists is offered too.
        binder_docs = [i for i in _walk(app.tree) if i.startswith(("doc:", "mapfile:"))]
        if binder_docs:
            row = binder_docs[0]
            window.query.set(str(app.tree.item(row, "text")).lower())
            window.refill()
            self.assertIn(row, [t.key for t in window.shown])

    def test_an_idea_opens_the_idea_inbox(self):
        app, box = self.app, self.box
        idea = app.project.data.ideas[0]
        window = open_goto(app)
        window.query.set("warden knew")
        window.refill()
        self.assertEqual(window.shown[0].key, f"idea:{idea.id}")
        opened = []
        original = app.cmd_idea_inbox
        app.cmd_idea_inbox = lambda: opened.append(True)
        try:
            window._run()
            box.pump(0.3)
        finally:
            app.cmd_idea_inbox = original
        self.assertEqual(opened, [True])

    def test_arrow_keys_move_the_choice_and_the_preview_follows(self):
        app = self.app
        window = open_goto(app)
        window.query.set("kessa")
        window.refill()
        self.assertGreater(len(window.shown), 1)
        first = window.preview.cget("text")
        window._move(1)
        self.assertEqual(window.tree.selection(), ("1",))
        window._move(-5)
        self.assertEqual(window.tree.selection(), ("0",))
        self.assertEqual(window.preview.cget("text"), first)

    def test_a_leading_greater_than_hands_over_to_the_command_palette(self):
        app, box = self.app, self.box
        window = open_goto(app)
        window.query.set(">story graph")
        window.refill()
        box.pump(0.3)
        self.assertFalse(window.winfo_exists())
        opened = getattr(app, "_palette", None)
        try:
            self.assertIsNotNone(opened, "the command palette never opened")
            # (Not "still open": a palette closes itself if this test window
            # cannot hold keyboard focus.)
            self.assertEqual(opened.query.get(), "story graph")
        finally:
            if opened is not None:
                opened.close()

    # -- the empty box --------------------------------------------------
    def test_the_empty_box_lists_the_last_places_and_enter_hops_back(self):
        app, box = self.app, self.box
        a, b, c = self.scenes[0], self.scenes[1], self.warden
        app.goto("scene", a.id)
        app.goto("scene", b.id)
        app.goto("entity", c.id)
        box.pump(0.3)
        window = open_goto(app)
        # Where you are is left out; the one before it comes first.
        self.assertEqual([t.key for t in window.shown][:2],
                         [f"scene:{b.id}", f"scene:{a.id}"])
        self.assertNotIn(f"entity:{c.id}", [t.key for t in window.shown])
        window._run()
        box.pump(0.4)
        self.assertEqual((app.selection_kind, app.selection_id), ("scene", b.id))

    def test_the_empty_box_is_never_empty_in_a_new_novel(self):
        app = self.app
        self._reset()
        app.tree.selection_remove(*app.tree.selection())
        app.selection_kind = app.selection_id = ""
        app._nav_recents = None
        settings["goto_recent"] = {}
        window = open_goto(app)
        self.assertTrue(window.shown)

    def test_visits_are_remembered_across_a_restart(self):
        from novelforge.ui import goto

        app, box = self.app, self.box
        app.goto("scene", self.scenes[1].id)
        app.goto("entity", self.warden.id)
        goto.persist(app)                             # what the idle timer does
        stored = settings.get("goto_recent")[app.project.data.id]
        self.assertEqual(stored[:2], [f"entity:{self.warden.id}",
                                      f"scene:{self.scenes[1].id}"])
        app._nav_recents = None                       # as if the app had restarted
        self.assertEqual(goto.recents_for(app).keys()[:2], stored[:2])

    def test_selecting_rows_does_not_rewrite_settings_each_time(self):
        app = self.app
        pending = getattr(app, "_nav_persist_job", None)
        if pending:
            app.after_cancel(pending)
        app._nav_persist_job = None
        writes = []
        original = type(settings).save
        type(settings).save = lambda self_: writes.append(1)
        try:
            for scene in self.scenes:
                app.goto("scene", scene.id)
            self.assertEqual(writes, [], "settings were rewritten on every selection")
            self.assertIsNotNone(app._nav_persist_job, "nothing scheduled a save")
        finally:
            type(settings).save = original

    # -- closing --------------------------------------------------------
    def test_escape_closes_it(self):
        app, box = self.app, self.box
        window = open_goto(app)
        box.pump(0.2)
        if window.focus_displayof() is None:
            self.skipTest("this test window cannot take keyboard focus")
        window.field.focus_force()
        window.field.event_generate("<Escape>")
        box.pump(0.2)
        self.assertFalse(window.winfo_exists())

    def test_it_closes_when_focus_goes_somewhere_else_but_not_while_typing(self):
        app = self.app
        window = open_goto(app, stay=False)
        window.focus_displayof = lambda: window.field           # focus stays inside
        window._maybe_close()
        self.assertTrue(window.winfo_exists(), "closed while focus was still in it")
        window.focus_displayof = lambda: app.tree               # clicked in the binder
        window._maybe_close()
        self.assertFalse(window.winfo_exists())
        window = open_goto(app, stay=False)
        window.focus_displayof = lambda: None                   # another program
        window._maybe_close()
        self.assertFalse(window.winfo_exists())

    # -- looks ----------------------------------------------------------
    def test_it_fits_whatever_is_typed(self):
        app, box = self.app, self.box
        window = open_goto(app)
        box.pump(0.3)                       # let it be drawn: hidden means unmapped
        for text in ("", "kessa", "the", "zzzz", "status:draft"):
            window.query.set(text)
            window.refill()
            box.pump(0.1)
            self.assertEqual(clipped_content(window), [], f"typed {text!r}")
        self.assertLessEqual(window.winfo_width(), window.winfo_screenwidth())

    def test_the_window_does_not_change_size_as_the_choice_changes(self):
        app = self.app
        window = open_goto(app)
        self.box.pump(0.2)
        window.query.set("kessa")
        window.refill()
        window.update_idletasks()
        size = (window.winfo_reqwidth(), window.winfo_reqheight())
        for step in (1, 1, -1, 3):
            window._move(step)
            window.update_idletasks()
            self.assertEqual((window.winfo_reqwidth(), window.winfo_reqheight()), size)

    # -- the palette's recents ------------------------------------------
    def test_the_palette_floats_the_commands_you_ran_last_to_the_top(self):
        from novelforge.ui import palette

        entries = palette.collect(self.app.menubar)
        older = next(e for e in entries if e.path.endswith("Word Frequency"))
        newer = next(e for e in entries if e.path.endswith("Bigger Text"))
        settings["palette_recent"] = []
        palette.note_run(older.path)
        palette.note_run(newer.path)
        self.assertEqual(settings.get("palette_recent")[:2], [newer.path, older.path])
        opened = palette.CommandPalette(self.app)
        try:
            self.assertEqual([e.path for e in opened.shown[:2]],
                             [newer.path, older.path])
            self.assertEqual(len(opened.shown), len(entries), "nothing may be dropped")
            # Typing still finds everything; a recent command edges ahead of an
            # otherwise equal one.
            opened.query.set("text")
            opened.update_idletasks()
            self.assertIn(newer.path, [e.path for e in opened.shown])
        finally:
            opened.close()
            settings["palette_recent"] = []


def _walk(tree, node=""):
    for child in tree.get_children(node):
        yield child
        yield from _walk(tree, child)


@unittest.skipUnless(sys.platform == "win32", "NovelForge is Windows-only")
class GoToAtScale(unittest.TestCase):
    """Go to on a 125% display (see test_gui_scaling for how that is simulated)."""

    SCALE = 1.25

    @classmethod
    def setUpClass(cls):
        import novelforge.ui.app as app_module

        probe = tk.Tk()
        cls._real_scaling = probe.tk.call("tk", "scaling")
        probe.destroy()
        cls.app_module = app_module
        cls._original = app_module._apply_scaling
        scale = cls.SCALE

        def simulated(root):
            root.tk.call("tk", "scaling", scale * 96 / 72)
            return cls._original(root)

        app_module._apply_scaling = simulated
        try:
            cls.box = Sandbox(title="Scaled Navigation Novel", name="nav_scaled").start()
        except BaseException:
            app_module._apply_scaling = cls._original
            raise
        cls.app = cls.box.app

    @classmethod
    def tearDownClass(cls):
        try:
            cls.box.stop()
        finally:
            cls.app_module._apply_scaling = cls._original
            probe = tk.Tk()
            probe.tk.call("tk", "scaling", cls._real_scaling)
            probe.destroy()

    def test_the_app_noticed_the_scale(self):
        self.assertAlmostEqual(self.app.ui_scale, self.SCALE, delta=0.05)

    def test_go_to_fits_and_grows_with_the_display(self):
        window = open_goto(self.app)
        try:
            self.box.pump(0.3)
            for text in ("", "kessa", "the"):
                window.query.set(text)
                window.refill()
                self.box.pump(0.1)
                self.assertEqual(clipped_content(window), [], f"typed {text!r}")
            # 100% is about 560px; it must have grown, not just avoided clipping.
            self.assertGreaterEqual(window.winfo_width(), int(540 * self.SCALE) - 20,
                                    window.winfo_width())
        finally:
            window.close()
        self.assertEqual(self.box.errors, [])


if __name__ == "__main__":
    unittest.main()
