"""Find content that does not fit its window. Shared by the tests and the shots."""

import tkinter as tk
from typing import List

_TEXT_WIDGETS = ("TButton", "TLabel", "Button", "Label", "TCheckbutton",
                 "TMenubutton")


def clipped_content(window: tk.Misc) -> List[str]:
    """
    Widgets that do not fit `window`, described one per string.

    The geometry managers fail differently, so there are three symptoms:

    * grid/place let a widget hang past the edge - it is still mapped, and its
      right edge lands beyond the window's;
    * pack quietly *unmaps* what does not fit - managed, but not mapped, under
      a parent that is;
    * either can squeeze a button below the width its label needs.

    Scrollable contents (canvases, text widgets) overflow by design and are not
    descended into. A check that cannot fail proves nothing: tests/ includes a
    deliberate regression run showing this does fire on a clipped toolbar.
    """
    bad: List[str] = []
    right_edge = window.winfo_rootx() + window.winfo_width()
    stack = [w for w in window.winfo_children()
             if not isinstance(w, tk.Toplevel)]
    while stack:
        w = stack.pop()
        try:
            parent_shown = w.master is not None and w.master.winfo_ismapped()
            if not w.winfo_ismapped():
                if w.winfo_manager() in ("pack", "grid", "place") and parent_shown:
                    bad.append(f"hidden {w.winfo_class()} {w}")
                continue
            edge = w.winfo_rootx() + w.winfo_width()
            if edge > right_edge + 2 and w.winfo_width() > 1:
                bad.append(f"past edge {w.winfo_class()} {w} (+{edge - right_edge}px)")
            elif (w.winfo_class() in _TEXT_WIDGETS
                  and w.winfo_reqwidth() > w.winfo_width() + 1):
                bad.append(f"squeezed {w.winfo_class()} {w} "
                           f"({w.winfo_width()}<{w.winfo_reqwidth()})")
            if isinstance(w, (tk.Canvas, tk.Text)):
                continue
            stack.extend(c for c in w.winfo_children()
                         if not isinstance(c, tk.Toplevel))
        except tk.TclError:
            pass
    return bad
