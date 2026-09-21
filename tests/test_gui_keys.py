"""
The writer's shortcuts must never touch the writer's prose.

Tk gives every Text and Entry emacs-style key bindings of its own - Ctrl+K kills the
rest of the line, Ctrl+H deletes a character, Ctrl+T swaps two, Ctrl+O and Ctrl+I insert
a newline and a tab - and they run BEFORE the app-wide shortcuts. NovelForge's own
shortcuts use the same keys (Ctrl+K corkboard, Ctrl+H replace, Ctrl+T timeline, Ctrl+O
open, Ctrl+I idea inbox), so with the caret in the editor pressing one used to change
the manuscript first and then do its job; autosave then wrote the damage to the .docx.

This presses every Ctrl shortcut the app defines with the caret in the editor and in a
one-line field, with the commands themselves stubbed, and checks that the text and the
caret are untouched and that the command ran exactly once. It is generic on purpose:
a shortcut added later that collides with a Tk default fails here.

It first checks that the sample text really went into the widget. (An earlier version
of this test passed on unfixed code because the editor was read-only with no scene
open, so nothing could change: a check that cannot fail proves nothing.)
"""

import re
import sys
import tkinter as tk
import unittest
from tkinter import ttk

from tests import require_isolation

require_isolation()

from tests.gui_support import Sandbox  # noqa: E402

TITLE = "Shortcut Safety Novel"
SAMPLE = "hello world\nsecond line"
ONE_LINE = "hello world"

# Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z are deliberately the text widget's own while the caret
# is in it (see App._bind_keys); the app-wide handler decides. Not a collision.
LEAVE_TO_THE_TEXT = {"<Control-z>", "<Control-y>", "<Control-Shift-Z>"}

# The editor deliberately gives these keys its own meaning (widgets.py, the editor's
# "Sublime-style" shortcuts), which shadows the app-wide Outline and Command Palette
# shortcuts the menus advertise while the caret is in the editor. Known and reported,
# not silently changed: the test pins what they do so a change is a decision.
EDITOR_OWNS = {"<Control-l>": "select the line", "<Control-Shift-P>": "select the paragraph"}


@unittest.skipUnless(sys.platform == "win32", "NovelForge is Windows-only")
class ShortcutsLeaveTheTextAlone(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox(title=TITLE, name="keys").start()
        cls.app = cls.box.app
        data = cls.app.project.data
        cls.scene = next(s for s in data.ordered_scenes() if s.word_count)

    @classmethod
    def tearDownClass(cls):
        cls.box.stop()

    def setUp(self):
        self.assertEqual(self.app.project.data.title, TITLE)
        self.app.focus_force()
        self.box.pump(0.3)
        if self.app.focus_get() is None:
            self.skipTest("this test window cannot take keyboard focus")
        self.calls = []
        self._patched = []
        # Every command becomes a recorder, so a shortcut that "works" opens nothing.
        for name in dir(type(self.app)):
            if name.startswith("cmd_"):
                setattr(self.app, name, self._recorder(name))
                self._patched.append(name)

    def tearDown(self):
        for name in self._patched:
            try:
                delattr(self.app, name)
            except AttributeError:
                pass
        self.assertEqual(self.box.errors, [], "exception raised inside a Tk callback")

    def _recorder(self, name):
        def record(*_args, **_kwargs):
            self.calls.append(name)
        return record

    def _control_shortcuts(self, editor=False):
        # "<Control-S>" is the CapsLock twin of Ctrl+S; a synthetic key press cannot
        # emulate CapsLock, so it is left out.
        found = [seq for seq in self.app.shortcuts
                 if seq.startswith("<Control-") and seq not in LEAVE_TO_THE_TEXT
                 and not re.fullmatch(r"<Control-[A-Z]>", seq)
                 and not (editor and seq in EDITOR_OWNS)]
        self.assertGreaterEqual(len(found), 10, "the shortcut table looks empty")
        return found

    def _press_all(self, widget, sample, load, read, set_caret, get_caret, editor=False):
        problems = []
        for sequence in self._control_shortcuts(editor):
            load(sample)
            set_caret(5)
            widget.focus_force()
            self.box.pump(0.03)
            # Guard against passing vacuously: the widget must really hold the sample.
            self.assertEqual(read(), sample, "the sample text did not go into the widget")
            before, caret = read(), get_caret()
            self.calls.clear()
            widget.event_generate(sequence)
            self.box.pump(0.05)
            after = read()
            if after != before:
                problems.append(f"{sequence} changed the text: {before!r} -> {after!r}")
            elif get_caret() != caret:
                problems.append(f"{sequence} moved the caret: {caret} -> {get_caret()}")
            if len(self.calls) != 1:
                problems.append(f"{sequence} ran its command {len(self.calls)} times: {self.calls}")
        return problems

    def test_no_shortcut_touches_the_text_in_the_editor(self):
        # The editor is read-only until a scene is open, so open one, for real.
        self.app.goto("scene", self.scene.id)
        self.box.pump(0.6)
        text = self.app.editor.text
        self.assertEqual(str(text.cget("state")), "normal", "the editor is not editable")

        def load(sample):
            text.delete("1.0", "end")
            text.insert("1.0", sample)

        problems = self._press_all(
            text, SAMPLE, load,
            read=lambda: text.get("1.0", "end-1c"),
            set_caret=lambda n: text.mark_set("insert", f"1.{n}"),
            get_caret=lambda: text.index("insert"), editor=True)
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_the_keys_the_editor_owns_only_select(self):
        # Ctrl+L and Ctrl+Shift+P are the editor's own (select line / paragraph) and
        # shadow the Outline and Command Palette shortcuts while the caret is in the
        # editor. Pin that: they must never edit, and must not also run the app command.
        self.app.goto("scene", self.scene.id)
        self.box.pump(0.6)
        text = self.app.editor.text
        for sequence, what in EDITOR_OWNS.items():
            with self.subTest(sequence=sequence, does=what):
                text.delete("1.0", "end")
                text.insert("1.0", SAMPLE)
                text.tag_remove("sel", "1.0", "end")
                text.mark_set("insert", "1.5")
                text.focus_force()
                self.box.pump(0.05)
                self.calls.clear()
                text.event_generate(sequence)
                self.box.pump(0.05)
                self.assertEqual(text.get("1.0", "end-1c"), SAMPLE, "it edited the text")
                self.assertTrue(text.tag_ranges("sel"), f"{sequence} should {what}")
                self.assertEqual(self.calls, [], "the app command ran as well")

    def test_no_shortcut_touches_the_text_in_a_one_line_field(self):
        holder = tk.Toplevel(self.app)
        try:
            entry = ttk.Entry(holder)
            entry.pack()
            holder.geometry("+60+60")
            self.box.pump(0.2)

            def load(sample):
                entry.delete(0, "end")
                entry.insert(0, sample)

            problems = self._press_all(
                entry, ONE_LINE, load,
                read=lambda: entry.get(),
                set_caret=lambda n: entry.icursor(n),
                get_caret=lambda: entry.index("insert"))
        finally:
            holder.destroy()
        self.assertEqual(problems, [], "\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
