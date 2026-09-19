"""
Walk the whole interface, the way a writer would click through it.

Every menu command, every toolbar button, every keyboard shortcut, every kind of
row in the binder and every right-click menu is used once, in a real window on a
throwaway novel. Then the flows a writer relies on are followed end to end:
first run, create a novel, open one, type, save, reopen, edit in Word and reload,
undo.

"It did not crash" is a low bar, so each step also checks that the app is still
alive and still on the sandbox novel, that nothing raised inside a Tk callback,
and that any window the step opened actually fits. Modal dialogs are closed by a
watcher, because a command that opens one does not return until it is gone.
"""

import os
import sys
import tkinter as tk
import types
import unittest
from pathlib import Path
from tkinter import filedialog
from unittest import mock

from tests import SANDBOX, require_isolation

require_isolation()

from novelforge import docxio  # noqa: E402
from novelforge.ui import dialogs, palette  # noqa: E402
from tests.gui_support import Sandbox, hang_guard  # noqa: E402
from tools.uishots.clipping import clipped_content  # noqa: E402
from tools.uishots.seed import build_demo_novel  # noqa: E402

# Closing the window would end the test run.
NOT_WALKED = {"Exit"}


def descendants(widget):
    stack = list(widget.winfo_children())
    while stack:
        w = stack.pop()
        yield w
        if not isinstance(w, tk.Toplevel):
            stack.extend(w.winfo_children())


def inspector_overflow(app):
    """Inspector fields wider than the pane they sit in."""
    right = app.inspector.canvas.winfo_rootx() + app.inspector.canvas.winfo_width()
    bad = []
    for w in descendants(app.inspector.body):
        try:
            if w.winfo_ismapped() and w.winfo_rootx() + w.winfo_width() > right + 2:
                bad.append(f"{w.winfo_class()} {str(w)[-30:]}")
        except tk.TclError:
            pass
    return bad


# Buttons that end the window they are in. A tour leaves them alone: OK would
# create or save things and change the open novel, and the window is closed for
# it afterwards anyway.
ENDS_WINDOW = {"ok", "cancel", "close", "done"}


def clickable_buttons(window):
    """Enabled, visible buttons in reading order (top to bottom, left to right)."""
    found = []
    for w in descendants(window):
        try:
            if (w.winfo_class() in ("TButton", "Button") and w.winfo_ismapped()
                    and str(w.cget("state")) != "disabled"
                    and str(w.cget("text")).strip().lower() not in ENDS_WINDOW):
                found.append(w)
        except tk.TclError:
            pass
    return sorted(found, key=lambda w: (w.winfo_rooty() // 8, w.winfo_rootx()))


class Walker:
    """Do one thing in the window, then tidy up whatever it opened."""

    def __init__(self, box, expect_title=None):
        self.box = box
        self.expect_title = expect_title
        self.problems = []
        self.steps = 0
        self.opened = []                  # (step, window title) for reporting

    def _inspect(self, label, window):
        try:
            window.update_idletasks()
            title = window.title()
            found = clipped_content(window)
        except tk.TclError:
            return
        self.opened.append((label, title))
        if found:
            self.problems.append(f"{label}: window {title!r} does not fit: {found[:3]}")

    def run(self, label, action, settle=0.3, watch=True):
        app = self.box.app
        before = set(self.box.toplevels())
        errors_before = len(self.box.errors)
        state = {"done": False}

        def watcher():
            # A modal dialog holds the grab and the command has not returned
            # yet - close it, or the command never returns.
            if state["done"]:
                return
            try:
                grabbed = app.grab_current()
                if isinstance(grabbed, tk.Toplevel) and grabbed not in before:
                    self._inspect(label, grabbed)
                    grabbed.destroy()
                app.after(100, watcher)
            except tk.TclError:
                pass

        if watch:
            app.after(150, watcher)
        try:
            action()
        except Exception as exc:                        # noqa: BLE001
            self.problems.append(f"{label}: raised {type(exc).__name__}: {exc}")
        finally:
            state["done"] = True
        self.box.pump(settle)
        for window in self.box.toplevels():
            if window not in before:
                self._inspect(label, window)
                try:
                    window.destroy()
                except tk.TclError:
                    pass
        self.steps += 1

        for message in self.box.errors[errors_before:]:
            self.problems.append(f"{label}: exception in a Tk callback: {message}")
        if not app.winfo_exists():
            self.problems.append(f"{label}: the main window is gone")
        elif self.expect_title and (
                app.project is None or app.project.data.title != self.expect_title):
            self.problems.append(f"{label}: the open novel changed")


    def tour(self, label, opener, settle=1.4):
        """
        Open a tool window, click every button in it (and on each of its tabs),
        then close it. Returns the labels of the buttons that were clicked.
        """
        box = self.box
        before = set(box.toplevels())
        clicked = []

        def visit():
            windows = [w for w in box.toplevels() if w not in before]
            if not windows:
                return
            window = windows[-1]
            pages = [None]
            notebooks = [w for w in descendants(window) if w.winfo_class() == "TNotebook"]
            for book in notebooks:
                pages = list(book.tabs())
            for page in pages:
                if page is not None:
                    notebooks[0].select(page)
                    box.pump(0.2)
                for button in clickable_buttons(window):
                    if not window.winfo_exists() or not button.winfo_exists():
                        break
                    text = str(button.cget("text")) or str(button)
                    if (page, text) in clicked:
                        continue
                    clicked.append((page, text))
                    self.run(f"{label} > {text}", button.invoke, settle=0.2)
            if window.winfo_exists():
                self._inspect(label, window)
                window.destroy()

        box.app.after(600, visit)
        self.run(label, opener, settle=settle, watch=False)
        return [text for _page, text in clicked]


@unittest.skipUnless(sys.platform == "win32", "NovelForge is Windows-only")
class EveryControl(unittest.TestCase):
    """Uses each menu entry, toolbar button, shortcut, row and right-click menu."""

    TITLE = "Walk Test Novel"

    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox(title=cls.TITLE, name="walk").start()
        cls.app = cls.box.app
        cls.scene = next(s for s in cls.app.project.data.scenes if s.word_count)

    @classmethod
    def tearDownClass(cls):
        cls.box.stop()

    def setUp(self):
        self.walker = Walker(self.box, expect_title=self.TITLE)
        self.app.tree.selection_set(f"scene:{self.scene.id}")
        self.box.pump(0.3)

    def check(self):
        self.assertEqual(self.walker.problems, [])

    # ------------------------------------------------------------------
    def test_every_menu_command_runs(self):
        app, walker = self.app, self.walker
        entries = [e for e in palette.collect(app.menubar)
                   if not e.path.split(palette.SEPARATOR)[-1].startswith(tuple(NOT_WALKED))]
        self.assertGreater(len(entries), 80, "the menus look emptier than they should")
        with hang_guard(240, "walking the menus"):
            for entry in entries:
                kind = entry.menu.type(entry.index)
                times = 2 if kind == "checkbutton" else 1     # toggle back
                for _ in range(times):
                    walker.run(entry.path,
                               lambda e=entry: e.menu.invoke(e.index))
        app.cmd_theme("warm")
        self.box.pump(0.3)
        self.assertGreater(walker.steps, 80)
        # Proof the walk is really looking: the commands opened, and the walker
        # inspected, a good many windows (a silent watcher would find none).
        self.assertGreater(len(walker.opened), 25, walker.opened)
        self.check()

        # The commands that make files really made them.
        root = app.project.root
        self.assertTrue(list((root / "_Backups").glob("*.zip")), "Back Up Now made no backup")
        self.assertTrue(app.project.compiled_path.exists(), "Compile made no manuscript")

    def test_every_toolbar_button_works(self):
        buttons = self.app._toolbar_buttons
        self.assertEqual([label for _b, _i, label in buttons],
                         ["New Scene", "Save", "Compile", "Diagnose", "Stats",
                          "Sprint", "Find", "Open in Word", "Commands"])
        with hang_guard(60, "toolbar buttons"):
            for button, _icon, label in buttons:
                self.walker.run(f"toolbar: {label}", button.invoke)
        self.assertGreaterEqual(len(self.walker.opened), 4, self.walker.opened)
        self.check()

    def test_every_button_inside_every_tool_window_works(self):
        app, walker = self.app, self.walker
        windows = [
            ("corkboard", app.cmd_corkboard),
            ("relationships", app.cmd_relationships),
            ("outline", app.cmd_outline_window),
            ("timeline", app.cmd_timeline_window),
            ("story graph", app.cmd_story_graph),
            ("find in project", app.cmd_search),
            ("find and replace", app.cmd_replace),
            ("sprint timer", app.cmd_sprint),
            ("backups", app.cmd_backups),
            ("versions of this document", app.cmd_snapshots),
            ("idea inbox", app.cmd_idea_inbox),
            ("drafts", app.cmd_drafts),
            ("place names", app.cmd_names),
            ("word frequency", app.cmd_word_frequency),
            ("block diagnostic", app.cmd_block_diagnostic),
            ("chapter map", app.cmd_chapter_map),
            ("continuity", app.cmd_continuity),
            ("project settings", app.cmd_project_settings),
            ("preferences", app.cmd_preferences),
            ("new novel", app.cmd_new_project),
            ("add a character", lambda: app.cmd_add_entity("character")),
            ("add an event", app.cmd_add_event),
            ("scene diagnostics", lambda: app.cmd_diagnostics("scene")),
            ("book diagnostics", lambda: app.cmd_diagnostics("book")),
            ("stats window", app.cmd_dashboard),
            ("verify project", app.cmd_verify_project),
            ("keyboard shortcuts", app.cmd_shortcuts),
            ("about", app.cmd_about),
            ("map maker", app.cmd_map_editor),
        ]
        clicked = {}
        with hang_guard(420, "clicking the buttons in every tool window"):
            for label, opener in windows:
                clicked[label] = walker.tour(label, opener,
                                             settle=2.2 if label == "map maker" else 1.4)
        # The tour must really have pressed things, or it proves nothing.
        total = sum(len(v) for v in clicked.values())
        if os.environ.get("NF_TEST_VERBOSE"):
            for label, texts in clicked.items():
                print(f"  {label:26s} {len(texts):2d} clicked: {', '.join(texts)}")
        self.assertGreater(total, 60, clicked)
        for label in ("corkboard", "outline", "map maker", "sprint timer"):
            self.assertTrue(clicked[label], f"nothing was clicked in the {label}")
        self.check()

    def test_every_keyboard_shortcut_is_wired_and_runs(self):
        app, walker = self.app, self.walker
        self.assertGreater(len(app.shortcuts), 30)
        event = types.SimpleNamespace(widget=app, x=0, y=0, delta=0, keysym="",
                                      x_root=0, y_root=0)
        with hang_guard(90, "keyboard shortcuts"):
            for sequence, handler in app.shortcuts.items():
                self.assertTrue(app.bind_all(sequence),
                                f"{sequence} is in the table but not bound")
                walker.run(f"shortcut {sequence}", lambda h=handler: h(event))
        if app._distraction_free:
            app.cmd_toggle_distraction_free()
        self.check()

    def test_a_real_keystroke_reaches_its_command(self):
        # The handler table is checked above; this proves a keystroke gets there.
        app = self.app
        app.focus_force()
        self.box.pump(0.3)
        if app.focus_get() is None:
            self.skipTest("this test window cannot take keyboard focus")
        app.editor.text.focus_set()
        app.editor.text.insert("end", " Typed by the test.")
        self.box.pump(0.3)
        self.assertEqual(app.status._save_state, "dirty")
        app.editor.text.event_generate("<Control-s>")
        self.box.pump(0.4)
        self.assertEqual(app.status._save_state, "saved")

    def test_every_kind_of_row_in_the_binder_builds_its_view(self):
        app, walker = self.app, self.walker

        def open_all(node=""):
            for child in app.tree.get_children(node):
                app.tree.item(child, open=True)
                open_all(child)

        open_all()
        self.box.pump(0.2)
        rows = []

        def collect(node=""):
            for child in app.tree.get_children(node):
                rows.append(child)
                collect(child)

        collect()
        self.assertGreater(len(rows), 40)
        kinds = {}
        with hang_guard(120, "selecting every binder row"):
            for iid in rows:
                walker.run(f"select {iid}",
                           lambda i=iid: app.tree.selection_set(i), settle=0.15)
                kind = app.selection_kind
                kinds.setdefault(kind, iid)
                wide = inspector_overflow(app)
                if wide:
                    walker.problems.append(f"{iid}: inspector fields past the pane: {wide[:3]}")
        self.assertTrue({"scene", "chapter", "entity"} <= set(kinds), kinds)
        self.check()

    def test_every_right_click_menu_builds_and_its_entries_run(self):
        app, walker = self.app, self.walker
        shown = []
        with mock.patch.object(tk.Menu, "tk_popup",
                               lambda menu, x, y, entry="": shown.append(menu)):
            kinds = {}
            for node in self._all_rows():
                app.tree.selection_set(node)
                app.tree.see(node)
                self.box.pump(0.05)
                kind = app.selection_kind
                if kind in kinds:
                    continue
                kinds[kind] = node
                box = app.tree.bbox(node)
                if not box:
                    continue
                shown.clear()
                event = types.SimpleNamespace(
                    x=box[0] + 5, y=box[1] + 5, x_root=100, y_root=100,
                    widget=app.tree)
                walker.run(f"right-click {kind}", lambda: app.on_tree_right_click(event),
                           settle=0.05)
                if not shown:
                    continue
                menu = shown[-1]
                last = menu.index("end")
                labels = [menu.entrycget(i, "label") for i in range(last + 1)
                          if menu.type(i) not in ("separator", "tearoff")]
                self.assertTrue(labels, f"the {kind} menu is empty")
                with hang_guard(60, f"{kind} context menu"):
                    for i in range(last + 1):
                        if menu.type(i) in ("separator", "tearoff", "cascade"):
                            continue
                        if menu.entrycget(i, "state") == "disabled":
                            continue
                        walker.run(f"{kind} menu > {menu.entrycget(i, 'label')}",
                                   lambda m=menu, n=i: m.invoke(n))
                app.tree.selection_set(f"scene:{self.scene.id}")
                self.box.pump(0.2)
            # the editor's own right-click menu
            shown.clear()
            app.editor.text.focus_set()
            walker.run("right-click in the editor", lambda: app.on_editor_right_click(
                types.SimpleNamespace(x=30, y=30, x_root=100, y_root=100,
                                      widget=app.editor.text)), settle=0.1)
            self.assertTrue(shown, "the editor's right-click menu did not appear")
        self.assertGreaterEqual(len(kinds), 4, kinds)
        self.check()

    def _all_rows(self):
        rows = []

        def walk(node=""):
            for child in self.app.tree.get_children(node):
                self.app.tree.item(child, open=True)
                rows.append(child)
                walk(child)

        walk()
        self.box.pump(0.2)
        return rows


@unittest.skipUnless(sys.platform == "win32", "NovelForge is Windows-only")
class WritingFlow(unittest.TestCase):
    """Type, save, reopen, edit in Word, reload, undo - on the real code paths."""

    TITLE = "Flow Test Novel"

    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox(title=cls.TITLE, name="flow").start()
        cls.app = cls.box.app

    @classmethod
    def tearDownClass(cls):
        cls.box.stop()

    def scene(self, title):
        return next(s for s in self.app.project.data.scenes if s.title == title)

    def select(self, scene):
        self.app.tree.selection_set(f"scene:{scene.id}")
        self.box.pump(0.4)

    def tearDown(self):
        self.assertEqual(self.box.errors, [])

    def test_typed_text_reaches_the_word_document_and_survives_reopening(self):
        app = self.app
        scene = self.scene("A Stranger at the Gate")
        self.select(scene)
        app.editor.text.insert("end", "\n\nA sentence typed in the test.")
        self.box.pump(0.4)
        self.assertEqual(app.status._save_state, "dirty")
        app.cmd_save(explicit=True)
        self.assertEqual(app.status._save_state, "saved")
        on_disk = docxio.read_prose(app.project.abs(scene.docx))
        self.assertIn("A sentence typed in the test.", on_disk)
        self.assertIn("gate began to rise", on_disk)         # nothing was lost

        root = app.project.root
        app.load_project(root)                               # close and reopen
        self.box.pump(0.5)
        self.select(self.scene("A Stranger at the Gate"))
        self.assertIn("A sentence typed in the test.", app.editor.get_value())

    def test_autosave_writes_without_being_asked(self):
        app = self.app
        scene = self.scene("The Warden's Price")
        self.select(scene)
        app.editor.text.insert("end", " Autosaved words.")
        self.box.pump(0.3)
        app._autosave()
        self.assertEqual(app.status._save_state, "saved")
        self.assertIn("Autosaved words.",
                      docxio.read_prose(app.project.abs(scene.docx)))

    def test_a_document_edited_in_word_is_picked_up_on_reload(self):
        app = self.app
        scene = self.scene("What the Fire Remembers")
        before = scene.word_count
        path = app.project.abs(scene.docx)
        docxio.write_prose(path, scene.title,
                           "Word rewrote this scene with a good many more "
                           "words than it held a moment ago, so the count "
                           "must change.",
                           font="Times New Roman", size=12, line_spacing=2.0,
                           margin=1.0, first_line_indent=0.5,
                           synopsis=scene.synopsis)
        later = os.path.getmtime(path) + 5
        os.utime(path, (later, later))               # Word saved a moment later
        app.cmd_sync_from_disk()
        self.box.pump(0.4)
        self.assertNotEqual(self.scene("What the Fire Remembers").word_count, before)
        self.select(self.scene("What the Fire Remembers"))
        self.assertIn("Word rewrote this scene", app.editor.get_value())

    def test_undo_and_redo_reverse_a_structural_change(self):
        app = self.app
        chapter = app.project.data.chapters[0]
        order = [s.title for s in app.project.data.scenes_in(chapter.id)]
        self.assertGreaterEqual(len(order), 2)
        self.select(self.scene(order[1]))
        app.cmd_move(-1)
        moved = [s.title for s in app.project.data.scenes_in(chapter.id)]
        self.assertEqual(moved[0], order[1])
        app.cmd_undo()
        self.assertEqual([s.title for s in app.project.data.scenes_in(chapter.id)],
                         order)
        app.cmd_redo()
        self.assertEqual([s.title for s in app.project.data.scenes_in(chapter.id)][0],
                         order[1])

    def test_switching_theme_keeps_the_writing_and_the_selection(self):
        app = self.app
        scene = self.scene("A Stranger at the Gate")
        self.select(scene)
        text = app.editor.get_value()
        for name in ("premium", "dark", "light", "warm"):
            app.cmd_theme(name)
            self.box.pump(0.25)
            self.assertEqual(app.editor.get_value(), text, name)
            self.assertEqual(app.current_scene_id, scene.id, name)


@unittest.skipUnless(sys.platform == "win32", "NovelForge is Windows-only")
class FirstRun(unittest.TestCase):
    """A fresh install: welcome screen, create a novel, open another."""

    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox(with_novel=False, name="first").start()
        cls.app = cls.box.app

    @classmethod
    def tearDownClass(cls):
        cls.box.stop()

    def test_the_welcome_screen_leads_to_a_working_novel(self):
        app, box = self.app, self.box
        self.assertTrue(app.welcome.winfo_ismapped(), "no welcome screen on a fresh install")
        self.assertFalse(app.gauge_frame.winfo_ismapped())

        options = {"title": "First Run Novel", "author": "A. Writer",
                   "genre": "Mystery", "structure": "three_act",
                   "target_words": 60000, "daily_words": 600, "deadline": "",
                   "packs": ["mystery"], "subtitle": "", "series": ""}
        with mock.patch.object(dialogs.NewProjectDialog, "show",
                               lambda self: dict(options)):
            with hang_guard(60, "creating a novel"):
                app.cmd_new_project()
        box.pump(0.6)
        self.assertEqual(app.project.data.title, "First Run Novel")
        self.assertFalse(app.welcome.winfo_ismapped(), "the welcome screen stayed")
        self.assertTrue(app.gauge_frame.winfo_ismapped())
        self.assertTrue(app.tree.get_children(), "the binder is empty")
        self.assertIn("askyesno", box.calls)         # offered to open the folder
        self.assertEqual(box.errors, [])

        # ...and File > Open on a second novel switches to it.
        second = build_demo_novel(Path(app.project.root).parent, "Second Novel")
        box._patch(filedialog, "askdirectory", lambda *a, **k: str(second.root))
        app.cmd_open_project()
        box.pump(0.6)
        self.assertEqual(app.project.data.title, "Second Novel")
        self.assertEqual(app.project_label.cget("text"), "Second Novel")
        self.assertEqual(box.errors, [])
        self.assertTrue(str(app.project.root).lower().startswith(str(SANDBOX).lower()))


if __name__ == "__main__":
    unittest.main()
