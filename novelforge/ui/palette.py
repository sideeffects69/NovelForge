"""
Command palette: press Ctrl+Shift+P, type a few letters, press Enter.

The menu bar holds ~100 commands under nine headings, which is fine once you
know where things live and slow when you don't. The palette is the other way
in: say what you want ("story graph", "backup", "theme") and run it.

It is built by walking the real menu bar each time it opens, so it can never
drift out of step with the menus - a command added to a menu is searchable the
moment it exists, dynamic labels ("Undo Rename") are current, and disabled
entries are left out. Running an entry is `menu.invoke(index)`, exactly what a
click does.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import List, Optional, Sequence

from ..config import settings
from . import styling
from .widgets import AutoScrollbar

SEPARATOR = "  ›  "          # "File  >  Save"
MAX_ROWS = 10

#: The last few commands run from the palette float to the top (Obsidian does the
#: same), remembered in the settings file. Newest first.
RECENT_SETTING = "palette_recent"
RECENT_LIMIT = 6


def recent_paths() -> List[str]:
    stored = settings.get(RECENT_SETTING)
    return [p for p in stored if isinstance(p, str)] if isinstance(stored, list) else []


def note_run(path: str) -> None:
    """Remember that `path` was just run from the palette."""
    kept = [p for p in recent_paths() if p != path]
    settings[RECENT_SETTING] = [path, *kept][:RECENT_LIMIT]


@dataclass
class Entry:
    path: str                       # "File > Save"
    accelerator: str
    menu: tk.Menu
    index: int


def collect(menu: tk.Menu, prefix: Sequence[str] = ()) -> List[Entry]:
    """Every enabled command under `menu`, in menu order."""
    found: List[Entry] = []
    try:
        last = menu.index("end")
    except tk.TclError:
        return found
    if last is None:
        return found
    for index in range(last + 1):
        try:
            kind = menu.type(index)
            if kind in ("separator", "tearoff"):
                continue
            label = menu.entrycget(index, "label")
            if kind == "cascade":
                sub = menu.nametowidget(menu.entrycget(index, "menu"))
                found.extend(collect(sub, (*prefix, label)))
                continue
            if menu.entrycget(index, "state") == "disabled":
                continue
            try:
                accelerator = menu.entrycget(index, "accelerator")
            except tk.TclError:
                accelerator = ""
            found.append(Entry(SEPARATOR.join((*prefix, label)),
                               accelerator, menu, index))
        except tk.TclError:
            continue
    return found


def score(tokens: Sequence[str], text: str) -> Optional[int]:
    """
    How well `text` matches every token, or None if any token is missing.

    A whole-word hit beats a mid-word hit beats letters found in order
    ("sgraph" -> "Story Graph"), and earlier beats later.
    """
    haystack = text.lower()
    total = 0
    for token in tokens:
        at = haystack.find(token)
        if at >= 0:
            starts_word = at == 0 or haystack[at - 1] in " ›.-("
            total += 100 - min(at, 60) + (40 if starts_word else 0)
            continue
        position, gaps = -1, 0
        for char in token:
            nxt = haystack.find(char, position + 1)
            if nxt < 0:
                return None
            if position >= 0:
                gaps += nxt - position - 1
            position = nxt
        total += max(1, 40 - gaps)
    return total


class CommandPalette(tk.Toplevel):
    def __init__(self, app) -> None:
        super().__init__(app)
        self.app = app
        self.withdraw()
        self.overrideredirect(True)
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass
        t = styling.current_tokens()

        self.entries = collect(app.menubar)
        self.recent = recent_paths()
        self.shown: List[Entry] = []

        outline = tk.Frame(self, background=t["border_strong"])
        outline.pack(fill="both", expand=True)
        body = ttk.Frame(outline, padding=(10, 10, 10, 8))
        body.pack(fill="both", expand=True, padx=1, pady=1)
        body.columnconfigure(0, weight=1)

        self.query = tk.StringVar()
        self.field = ttk.Entry(body, textvariable=self.query,
                               font=(styling.UI_FONT, 11))
        self.field.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(body, text="Type to search every command  ·  "
                             "Enter to run  ·  Esc to close",
                  style="Hint.TLabel").grid(row=1, column=0, columnspan=2,
                                            sticky="w", pady=(4, 6))

        self.tree = ttk.Treeview(body, columns=("keys",), show="tree",
                                 height=MAX_ROWS, selectmode="browse")
        scale = getattr(app, "ui_scale", 1.0)
        self.tree.column("#0", width=int(400 * scale), stretch=True)
        self.tree.column("keys", width=int(130 * scale), anchor="e",
                         stretch=False)
        self.tree.tag_configure("keys", foreground=t["text_dim"])
        self.tree.grid(row=2, column=0, sticky="nsew")
        bar = AutoScrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        bar.grid(row=2, column=1, sticky="ns")

        self.field.bind("<Down>", lambda _e: self._move(1) or "break")
        self.field.bind("<Up>", lambda _e: self._move(-1) or "break")
        self.field.bind("<Next>", lambda _e: self._move(MAX_ROWS) or "break")
        self.field.bind("<Prior>", lambda _e: self._move(-MAX_ROWS) or "break")
        self.field.bind("<Return>", lambda _e: self._run() or "break")
        self.bind("<Escape>", lambda _e: self.close())
        self.tree.bind("<ButtonRelease-1>", self._on_click)
        self.query.trace_add("write", lambda *_a: self._refill())
        self.bind("<FocusOut>", lambda _e: self.after(150, self._maybe_close))

        self._refill()
        self._place()
        self.deiconify()
        self.lift()
        self.field.focus_force()

    # ------------------------------------------------------------------
    def _place(self) -> None:
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        app = self.app
        x = app.winfo_rootx() + (app.winfo_width() - w) // 2
        y = app.winfo_rooty() + max(40, int(app.winfo_height() * 0.14))
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x = max(8, min(x, sw - w - 8))
        y = max(8, min(y, sh - h - 48))
        self.geometry(f"+{x}+{y}")

    def _refill(self) -> None:
        tokens = self.query.get().lower().split()
        recent_rank = {path: place for place, path in enumerate(self.recent)}
        if tokens:
            ranked = []
            for order, entry in enumerate(self.entries):
                value = score(tokens, entry.path)
                if value is not None:
                    # A command you ran lately edges ahead of an equal match.
                    if entry.path in recent_rank:
                        value += 30 - 4 * recent_rank[entry.path]
                    ranked.append((-value, order, entry))
            ranked.sort(key=lambda item: item[:2])
            self.shown = [entry for _v, _o, entry in ranked[:60]]
        else:
            # Nothing typed: what you ran last first, then the menus in order.
            first = sorted((e for e in self.entries if e.path in recent_rank),
                           key=lambda e: recent_rank[e.path])
            self.shown = first + [e for e in self.entries
                                  if e.path not in recent_rank]
        self.tree.delete(*self.tree.get_children())
        for number, entry in enumerate(self.shown):
            self.tree.insert("", "end", iid=str(number), text=entry.path,
                             values=(entry.accelerator,), tags=("keys",))
        if self.shown:
            self.tree.selection_set("0")
            self.tree.see("0")

    def _move(self, step: int) -> None:
        if not self.shown:
            return
        current = self.tree.selection()
        index = int(current[0]) if current else -1
        index = max(0, min(len(self.shown) - 1, index + step))
        self.tree.selection_set(str(index))
        self.tree.see(str(index))

    def _on_click(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self._run()

    def _maybe_close(self) -> None:
        try:
            if self.focus_displayof() is None:
                self.close()
        except tk.TclError:
            pass

    def close(self) -> None:
        try:
            self.destroy()
        except tk.TclError:
            pass

    def _run(self) -> None:
        current = self.tree.selection()
        if not current:
            return
        entry = self.shown[int(current[0])]
        app = self.app
        note_run(entry.path)
        self.close()
        # After the palette has gone, so focus is back on the main window when
        # the command opens its own dialog.
        app.after(20, lambda: self._invoke(entry))

    @staticmethod
    def _invoke(entry: Entry) -> None:
        try:
            entry.menu.invoke(entry.index)
        except tk.TclError:
            pass
