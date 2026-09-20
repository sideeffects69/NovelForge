"""
The rounded controls must be fast to draw and sane in size.

They are ttk *image elements*, and ttk tiles their images (one draw call per
tile) and sizes an element from its image. Both facts have already broken the
app once each: a 2px middle made one text field cost 200 ms to draw, then a 64px
middle made every button 82px tall, and a transparent 2px scroll-bar trough made
a window with three scroll bars take 800 ms to open. None of that shows in a
unit test of the pictures, so this measures the widgets themselves, in a bare
window with no application around it.
"""

import sys
import time
import tkinter as tk
import unittest
from tkinter import ttk

from tests import require_isolation

require_isolation()


@unittest.skipUnless(sys.platform == "win32", "NovelForge is Windows-only")
class RoundedControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from novelforge import config
        from novelforge.ui import styling

        cls.root = tk.Tk()
        cls.root.geometry("+20+20")
        cls.style = ttk.Style(cls.root)
        styling.apply(cls.root, cls.style, config.THEMES["premium"], 1.0)
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def crowd(self):
        """A window with one of everything, and three tall scroll bars."""
        top = tk.Toplevel(self.root)
        top.geometry("760x640+40+40")
        frame = ttk.Frame(top)
        frame.pack(fill="both", expand=True)
        for row in range(6):
            ttk.Entry(frame).grid(row=row, column=0, padx=4, pady=2)
            ttk.Combobox(frame, values=["a", "b"], state="readonly").grid(row=row, column=1, padx=4)
            ttk.Button(frame, text="Button").grid(row=row, column=2, padx=4)
            ttk.Button(frame, text="Accent", style="Accent.TButton").grid(row=row, column=3, padx=4)
            ttk.Checkbutton(frame, text="Check").grid(row=row, column=4, padx=4)
        for column in range(3):
            ttk.Scrollbar(frame, orient="vertical").grid(
                row=0, column=5 + column, rowspan=6, sticky="ns", ipady=120)
        return top

    def test_a_window_full_of_controls_draws_in_a_blink(self):
        top = self.crowd()
        try:
            started = time.perf_counter()
            top.update()
            elapsed = time.perf_counter() - started
        finally:
            top.destroy()
        # About 0.05s here. The 2px-middle bug took 2s for a smaller window and
        # the 2px-trough bug 0.8s more, so this stays generous and still fails.
        self.assertLess(elapsed, 0.4, f"drawing the controls took {elapsed:.2f}s")

    def test_a_repaint_is_as_quick_as_the_first_draw(self):
        top = self.crowd()
        try:
            top.update()
            started = time.perf_counter()
            for width in (780, 760, 780, 760):
                top.geometry(f"{width}x640+40+40")
                top.update()
            elapsed = (time.perf_counter() - started) / 4
        finally:
            top.destroy()
        self.assertLess(elapsed, 0.2, f"a resize repaint took {elapsed:.2f}s")

    def test_controls_are_the_size_of_controls(self):
        top = tk.Toplevel(self.root)
        try:
            widgets = {
                "button": ttk.Button(top, text="Button"),
                "accent": ttk.Button(top, text="Accent", style="Accent.TButton"),
                "tool": ttk.Button(top, text="Tool", style="Tool.TButton"),
                "quiet": ttk.Button(top, text="+", style="Quiet.TButton"),
                "compact": ttk.Button(top, text="Compact", style="Compact.TButton"),
                "entry": ttk.Entry(top),
                "combobox": ttk.Combobox(top, values=["a"]),
                "rail": ttk.Radiobutton(top, style="Rail.Toolbutton", text="x", value="a"),
            }
            bar = ttk.Scrollbar(top, orient="vertical")
            for i, widget in enumerate(widgets.values()):
                widget.grid(row=i, column=0)
            bar.grid(row=0, column=1, rowspan=8, sticky="ns")
            top.update()
            heights = {name: w.winfo_reqheight() for name, w in widgets.items()}
            # ~35px for a button and ~31 for a field. The 64px-middle bug made
            # every one of these at least 82 (and a scroll bar 88px wide).
            for name, height in heights.items():
                self.assertLess(height, 50, f"{name} is {height}px tall: {heights}")
            self.assertLess(bar.winfo_reqwidth(), 30, "the scroll bar is not slim")
            self.assertGreater(heights["button"], 24, "the button has no room to breathe")
        finally:
            top.destroy()


if __name__ == "__main__":
    unittest.main()
