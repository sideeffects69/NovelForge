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
# Imported now, not inside a test: once a Sandbox is up, `subprocess.Popen` is a stub,
# and asyncio (which unittest.mock pulls in) subclasses the real one when first loaded.
from unittest import mock

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


# ==========================================================================
# The Connections panel
# ==========================================================================


def descendants(widget):
    stack = list(widget.winfo_children())
    while stack:
        w = stack.pop()
        yield w
        if not isinstance(w, tk.Toplevel):
            stack.extend(w.winfo_children())


def find_panel(app):
    from novelforge.ui.connections import ConnectionsPanel

    return next((w for w in descendants(app.inspector.body)
                 if isinstance(w, ConnectionsPanel)), None)


def inspector_overflow(app):
    """Inspector widgets wider than the pane they sit in."""
    right = app.inspector.canvas.winfo_rootx() + app.inspector.canvas.winfo_width()
    bad = []
    for w in descendants(app.inspector.body):
        try:
            if w.winfo_ismapped() and w.winfo_rootx() + w.winfo_width() > right + 2:
                bad.append(f"{w.winfo_class()} {str(w)[-30:]}")
        except tk.TclError:
            pass
    return bad


def label_texts(app):
    return [str(w.cget("text")) for w in descendants(app.inspector.body)
            if w.winfo_class() in ("TLabel", "Label")]


def seed_ledger(app):
    """
    A scene that names three people and a place without linking any of them, and a
    scan, so there is something in "Mentioned, not linked". Returns the scene id.
    """
    from novelforge import mentionindex

    project = app.project
    chapter = project.data.chapters[0]
    scene = project.add_scene(
        chapter.id, "The Ledger", synopsis="Kessa finds the ledger.",
        body=("Kessa Ren slid the key across the desk. Warden Tholve watched her, "
              "and Vaelmoor slept. Kessa said nothing of the Emberblade."))
    project.save(force=True)
    app.refresh_tree()
    mentionindex.forget(project)
    mentionindex.refresh(project)
    return scene.id


@unittest.skipUnless(sys.platform == "win32", "NovelForge is Windows-only")
class ConnectionsPanelWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox(title="Connections Panel Novel", name="conn").start()
        cls.app = cls.box.app
        cls.ledger = seed_ledger(cls.app)
        data = cls.app.project.data
        cls.kessa = next(e for e in data.entities if e.name == "Kessa Ren")
        cls.tholve = next(e for e in data.entities if e.name == "Warden Tholve")
        cls.opening = next(s for s in data.scenes if s.title == "A Stranger at the Gate")
        cls.note = data.notes[0]
        cls.event = data.events[1]
        cls.app.project.set_note_links(cls.note.id, [cls.kessa.id])
        cls.app.project.mark_dirty()

    @classmethod
    def tearDownClass(cls):
        cls.box.stop()

    def setUp(self):
        self.assertTrue(str(self.app.project.root).lower().startswith(str(SANDBOX).lower()))

    def tearDown(self):
        self.assertEqual(self.box.errors, [], "exception raised inside a Tk callback")

    def show(self, kind, ident, settle=0.4):
        # Selecting what is already selected draws nothing, so draw it: an earlier
        # test may have left the inspector showing something else.
        same = (self.app.selection_kind, self.app.selection_id) == (kind, ident)
        self.assertTrue(self.app.goto(kind, ident))
        if same:
            self.app.render_selection()
        self.box.pump(settle)
        panel = find_panel(self.app)
        self.assertIsNotNone(panel, f"no Connections panel for {kind}")
        return panel

    def titles(self, panel, key=None):
        return [row.title for row, _label in panel.title_labels
                if key is None or row in panel.info.rows(key)]

    # -- where it appears -----------------------------------------------
    def test_a_character_shows_the_panel_instead_of_the_old_count_and_pop_up(self):
        panel = self.show("entity", self.kessa.id)
        texts = label_texts(self.app)
        self.assertNotIn("Linked scenes", texts)
        self.assertTrue(any(t.startswith("Linked (") for t in texts), texts)
        self.assertTrue(any(t.startswith("Mentioned, not linked (") for t in texts), texts)
        self.assertIn("A Stranger at the Gate", self.titles(panel, "linked"))
        self.assertEqual(self.titles(panel, "unlinked"), ["The Ledger"])
        buttons = [str(w.cget("text")) for w in descendants(self.app.detail_buttons)
                   if w.winfo_class() == "TButton"]
        self.assertNotIn("Where mentioned?", buttons)
        self.assertIn("CONNECTIONS", texts)

    def test_a_scene_shows_who_it_links_and_who_it_only_names(self):
        panel = self.show("scene", self.ledger)
        self.assertEqual(self.titles(panel, "linked"), [])
        self.assertEqual(sorted(self.titles(panel, "unlinked")),
                         ["Kessa Ren", "The Emberblade", "Vaelmoor", "Warden Tholve"])
        self.assertEqual({row.title for row, _b in panel.link_buttons},
                         {"Kessa Ren", "The Emberblade", "Vaelmoor", "Warden Tholve"})
        opening = self.show("scene", self.opening.id)
        self.assertIn("Kessa Ren", self.titles(opening, "linked"))
        self.assertEqual(opening.link_buttons, [])

    def test_a_note_and_an_event_have_it_too(self):
        note = self.show("note", self.note.id)
        self.assertEqual(self.titles(note, "linked"), ["Kessa Ren"])
        self.assertNotIn("Linked to", label_texts(self.app))
        event = self.show("event", self.event.id)
        self.assertGreaterEqual(event.info.total, 0)
        self.assertTrue(any(t.startswith("CONNECTIONS") for t in label_texts(self.app)))

    def test_no_document_is_opened_while_any_of_it_is_drawn(self):
        from novelforge import docxio
        from novelforge.ui.connections import ConnectionsPanel

        app = self.app
        for entity in app.project.data.entities:      # warm the sheet caches first
            app.project.entity_fields(entity.id)
        boom = AssertionError("a Word document was opened while drawing Connections")
        scene = app.project.data.scene(self.ledger)
        with mock.patch.object(docxio, "read_prose", side_effect=boom), \
                mock.patch.object(docxio, "Document", side_effect=boom):
            app._build_scene_inspector(scene)
            self.assertIsNotNone(find_panel(app))
            app._render_entity(self.kessa)
            self.assertIsNotNone(find_panel(app))
            app._render_event(self.event.id)
            self.assertIsNotNone(find_panel(app))
            for kind, ident in (("note", self.note.id), ("event", self.event.id),
                                ("entity", self.tholve.id), ("scene", self.ledger)):
                panel = ConnectionsPanel(app.inspector.body, app, kind, ident)
                panel.update_idletasks()
                panel.destroy()

    # -- using it -------------------------------------------------------
    def test_clicking_a_row_jumps_to_that_item_in_the_binder(self):
        panel = self.show("entity", self.kessa.id)
        row, label = next((r, l) for r, l in panel.title_labels
                          if r.title == "A Stranger at the Gate")
        label.event_generate("<Button-1>", x=2, y=2)
        self.box.pump(0.5)
        self.assertEqual((self.app.selection_kind, self.app.selection_id),
                         ("scene", self.opening.id))
        self.assertEqual(self.app.tree.selection(), (f"scene:{self.opening.id}",))
        # and from a scene back to a character
        panel = self.show("scene", self.opening.id)
        _row, label = next((r, l) for r, l in panel.title_labels
                           if r.title == "Warden Tholve")
        label.event_generate("<Button-1>", x=2, y=2)
        self.box.pump(0.5)
        self.assertEqual((self.app.selection_kind, self.app.selection_id),
                         ("entity", self.tholve.id))

    def test_link_moves_the_row_leaves_the_editor_alone_and_ctrl_z_undoes_it(self):
        app, box = self.app, self.box
        panel = self.show("scene", self.ledger)
        app.editor.text.mark_set("insert", "1.4")
        caret, body = app.editor.text.index("insert"), app.editor.get_value()
        _row, button = next((r, b) for r, b in panel.link_buttons
                            if r.title == "Warden Tholve")
        button.invoke()
        box.pump(0.6)
        scene = app.project.data.scene(self.ledger)
        self.assertIn(self.tholve.id, scene.character_ids)
        again = find_panel(app)
        self.assertIsNot(again, panel, "the panel was not redrawn")
        self.assertIn("Warden Tholve", self.titles(again, "linked"))
        self.assertNotIn("Warden Tholve", self.titles(again, "unlinked"))
        self.assertEqual(app.editor.get_value(), body)
        self.assertEqual(app.editor.text.index("insert"), caret,
                         "linking reloaded the editor")
        self.assertEqual(app.project.history.undo_label(), "Link mention")
        self.assertIn("Undo Link mention", app.edit_menu.entrycget(0, "label"))
        # Ctrl+Z from anywhere but the text takes it back, and the panel follows.
        app.cmd_undo()
        box.pump(0.5)
        scene = app.project.data.scene(self.ledger)
        self.assertNotIn(self.tholve.id, scene.character_ids)
        self.assertIn("Warden Tholve", self.titles(find_panel(app), "unlinked"))
        app.cmd_redo()
        box.pump(0.5)
        self.assertIn(self.tholve.id, app.project.data.scene(self.ledger).character_ids)
        app.cmd_undo()
        box.pump(0.4)

    def test_linking_from_a_character_moves_the_scene_between_sections(self):
        app, box = self.app, self.box
        panel = self.show("entity", self.kessa.id)
        _row, button = next((r, b) for r, b in panel.link_buttons if r.title == "The Ledger")
        button.invoke()
        box.pump(0.6)
        again = find_panel(app)
        self.assertIn("The Ledger", self.titles(again, "linked"))
        self.assertEqual(self.titles(again, "unlinked"), [])
        self.assertIn(self.kessa.id, app.project.data.scene(self.ledger).character_ids)
        app.cmd_undo()
        box.pump(0.4)
        self.assertNotIn(self.kessa.id, app.project.data.scene(self.ledger).character_ids)

    def test_named_3x_shows_where_by_reading_just_that_scene(self):
        from novelforge import docxio

        app, box = self.app, self.box
        panel = self.show("scene", self.ledger)
        kessa_row = next(r for r, _b in panel.link_buttons if r.title == "Kessa Ren")
        detail = next(w for w in descendants(panel)
                      if w.winfo_class() == "TLabel" and str(w.cget("text")) == "named 2x")
        self.assertEqual(panel.context_labels, [])
        with mock.patch.object(docxio, "read_prose", wraps=docxio.read_prose) as reads:
            detail.event_generate("<Button-1>", x=2, y=2)
            box.pump(0.4)
        self.assertEqual(reads.call_count, 1, "one scene, on the click")
        panel = find_panel(app)
        self.assertEqual(len(panel.context_labels), 1)
        self.assertIn("Kessa", str(panel.context_labels[0].cget("text")))
        self.assertEqual(kessa_row.count, 2)

    def test_more_than_twelve_rows_are_folded_until_asked_for(self):
        from novelforge import backlinks
        from novelforge.ui.connections import LIMIT

        panel = self.show("entity", self.kessa.id)
        rows = [backlinks.Row("scene", f"s{n}", f"Scene {n}", "present")
                for n in range(LIMIT + 8)]
        panel.info.sections = [backlinks.Section("linked", rows)]
        panel._draw()
        self.box.pump(0.2)
        self.assertEqual(len(panel.title_labels), LIMIT)
        more = next(w for w in descendants(panel)
                    if w.winfo_class() == "TButton"
                    and str(w.cget("text")) == f"Show all {LIMIT + 8}")
        more.invoke()
        self.box.pump(0.2)
        self.assertEqual(len(panel.title_labels), LIMIT + 8)

    # -- keeping it honest ----------------------------------------------
    def test_an_unscanned_novel_offers_scan_and_scanning_brings_it_current(self):
        from novelforge import mentionindex

        app, box = self.app, self.box
        mentionindex.forget(app.project)
        mentionindex.path_for(app.project).unlink()
        panel = self.show("scene", self.ledger)
        self.assertEqual(str(panel.update_button.cget("text")), "Scan")
        self.assertIn("not been looked for", str(panel.status_label.cget("text")))
        self.assertEqual(panel.link_buttons, [])
        panel.update_button.invoke()
        box.pump(0.8)
        again = find_panel(app)
        self.assertIsNot(again, panel)
        self.assertEqual(str(again.update_button.cget("text")), "Update")
        self.assertTrue(str(again.status_label.cget("text")).startswith("Scanned just now"))
        self.assertTrue(mentionindex.freshness(app.project).current)
        self.assertTrue(again.link_buttons)

    def test_a_scene_edited_since_the_scan_is_reported(self):
        from novelforge import mentionindex
        import time

        app, box = self.app, self.box
        mentionindex.refresh(app.project)
        time.sleep(0.05)
        app.project.save_scene_text(self.opening.id, "Kessa Ren, alone.", snapshot=False)
        panel = self.show("entity", self.kessa.id)
        self.assertIn("1 scene changed since", str(panel.status_label.cget("text")))
        mentionindex.refresh(app.project)

    def test_saving_the_open_scene_recounts_it_without_a_scan(self):
        from novelforge import mentionindex

        app, box = self.app, self.box
        mentionindex.refresh(app.project)
        self.show("scene", self.ledger)
        mara = next(e for e in app.project.data.entities if e.name == "Mara Voss")
        app.editor.text.insert("end", " Mara Voss laughed. Mara Voss left.")
        box.pump(0.3)
        self.assertTrue(app.save_editor(snapshot=False))
        entry = mentionindex.get(app.project).scenes[self.ledger]
        self.assertEqual(entry.counts.get(mara.id), 2)
        self.assertTrue(mentionindex.freshness(app.project).current,
                        "the save made the index look stale")
        # The panel is redrawn when asked (a save must not rebuild the inspector
        # under someone who is typing in it), and then offers Mara as a mention.
        from novelforge.ui.connections import rebuild_inspector

        rebuild_inspector(app)
        box.pump(0.4)
        self.assertIn("Mara Voss", self.titles(find_panel(app), "unlinked"))

    def test_the_scan_is_a_menu_command_the_palette_can_find(self):
        from novelforge.ui import palette

        entry = next((e for e in palette.collect(self.app.menubar)
                      if e.path.endswith("Scan for Mentions (Connections)")), None)
        self.assertIsNotNone(entry)
        self.assertIn("Tools", entry.path)

    # -- looks ----------------------------------------------------------
    def test_it_fits_the_inspector_for_every_kind_of_thing(self):
        app = self.app
        for kind, ident in (("scene", self.ledger), ("entity", self.kessa.id),
                            ("note", self.note.id), ("event", self.event.id)):
            self.show(kind, ident, settle=0.5)
            self.assertEqual(inspector_overflow(app), [], kind)
        from tools.uishots.clipping import clipped_content as clipped

        self.assertEqual(clipped(app), [])

    def test_it_follows_a_theme_change(self):
        app = self.app
        self.show("scene", self.ledger)
        try:
            for name in ("dark", "premium", "warm"):
                app.cmd_theme(name)
                self.box.pump(0.4)
                self.assertIsNotNone(find_panel(app), name)
                self.assertEqual(inspector_overflow(app), [], name)
        finally:
            app.cmd_theme("warm")
            self.box.pump(0.3)


# ==========================================================================
# Scene tags in the inspector
# ==========================================================================


@unittest.skipUnless(sys.platform == "win32", "NovelForge is Windows-only")
class SceneTagsInTheInspector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox(title="Scene Tags Novel", name="tags").start()
        cls.app = cls.box.app
        cls.scene = next(s for s in cls.app.project.data.scenes if s.word_count)

    @classmethod
    def tearDownClass(cls):
        cls.box.stop()

    def tearDown(self):
        self.assertEqual(self.box.errors, [], "exception raised inside a Tk callback")

    def tags_row(self):
        return next(r for r in self.app._form.rows if r["attr"] == "tags")

    def test_the_field_is_there_and_tags_apply_save_and_undo(self):
        app, box = self.app, self.box
        app.goto("scene", self.scene.id)
        box.pump(0.4)
        self.assertIn("Tags", label_texts(app))
        row = self.tags_row()
        self.assertEqual(row["var"].get(), "")
        depth = len(app.project.history)
        app.cmd_apply_inspector()                       # untouched: nothing to do
        self.assertEqual(len(app.project.history), depth)
        row["var"].set("Clue, a/b , #red herring, clue")
        app.cmd_apply_inspector()
        box.pump(0.4)
        self.assertEqual(app.project.data.scene(self.scene.id).tags,
                         ["Clue", "a/b", "red-herring"])
        self.assertEqual(self.tags_row()["var"].get(), "Clue, a/b, red-herring")
        app.project.save()
        from novelforge.project import Project

        self.assertEqual(Project.open(app.project.root).data.scene(self.scene.id).tags,
                         ["Clue", "a/b", "red-herring"])
        app.cmd_undo()
        box.pump(0.4)
        self.assertEqual(app.project.data.scene(self.scene.id).tags, [])

    def test_go_to_finds_it_by_tag_and_by_a_parent_tag(self):
        from novelforge import navindex

        app, box = self.app, self.box
        app.project.data.scene(self.scene.id).tags = ["clue/red-herring"]
        window = open_goto(app)
        try:
            for query in ("tag:clue", "tag:clue/red-herring"):
                window.query.set(query)
                window.refill()
                self.assertEqual([t.key for t in window.shown],
                                 [f"scene:{self.scene.id}"], query)
            window.query.set("tag:red")
            window.refill()
            self.assertEqual(window.shown, [])
        finally:
            window.close()
            app.project.data.scene(self.scene.id).tags = []


@unittest.skipUnless(sys.platform == "win32", "NovelForge is Windows-only")
class ConnectionsAtScale(unittest.TestCase):
    """The panel on a 125% display."""

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
            cls.box = Sandbox(title="Scaled Connections Novel", name="conn_scaled").start()
        except BaseException:
            app_module._apply_scaling = cls._original
            raise
        cls.app = cls.box.app
        cls.ledger = seed_ledger(cls.app)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.box.stop()
        finally:
            cls.app_module._apply_scaling = cls._original
            probe = tk.Tk()
            probe.tk.call("tk", "scaling", cls._real_scaling)
            probe.destroy()

    def test_the_panel_fits_at_125_percent(self):
        from tools.uishots.clipping import clipped_content as clipped

        app, box = self.app, self.box
        self.assertAlmostEqual(app.ui_scale, self.SCALE, delta=0.05)
        kessa = next(e for e in app.project.data.entities if e.name == "Kessa Ren")
        for kind, ident in (("scene", self.ledger), ("entity", kessa.id)):
            app.goto(kind, ident)
            box.pump(0.5)
            self.assertIsNotNone(find_panel(app), kind)
            self.assertEqual(inspector_overflow(app), [], kind)
        self.assertEqual(clipped(app), [])
        self.assertEqual(box.errors, [])


if __name__ == "__main__":
    unittest.main()
