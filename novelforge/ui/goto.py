"""
Go to...: press Ctrl+P, type a few letters of anything, press Enter.

A scene, a chapter, a character (or one of their aliases), a note, a timeline
event, an outline beat, a map, an idea. With nothing typed it lists the last places
visited, and the one you are standing in is left out, so Ctrl+P then Enter hops
straight back to where you were.

Built like the command palette (`palette.py`) and for the same reasons: a small
borderless window that closes on Escape and when focus leaves it - which is also what
keeps the GUI walk, which fires every menu command, from ever hanging on it. The
ranking and the data are `navindex.py`; this file is only the window.

Nothing here reads a Word document. Every row comes from the manifest, so the list is
as fast in a three-hundred-scene novel as in a three-scene one.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import List, Optional

from .. import navindex
from ..config import settings
from ..model import ENTITY_TYPES, STATUS_COLOURS
from . import styling
from .widgets import AutoScrollbar

VISIBLE_ROWS = 10
PREVIEW_CHARS = 150
_SETTING = "goto_recent"

# Which drawn icon a row wears (the same ones the binder uses).
_ICONS = {
    "chapter": "folder", "character": "person", "location": "pin", "item": "box",
    "faction": "flag", "thread": "link", "note": "note", "event": "clock",
    "map": "map", "doc": "doc", "idea": "edit", "beat": "list",
}


# ==========================================================================
# Recents: remembered per novel, in the settings file
# ==========================================================================


def recents_for(app) -> navindex.Recents:
    """The visited list for the open novel, loaded from settings the first time."""
    project_id = app.project.data.id if app.project else ""
    held = getattr(app, "_nav_recents", None)
    if held is not None and held[0] == project_id:
        return held[1]
    stored = settings.get(_SETTING) or {}
    keys = stored.get(project_id, []) if isinstance(stored, dict) else []
    recents = navindex.Recents(keys if isinstance(keys, list) else [])
    app._nav_recents = (project_id, recents)
    return recents


def remember(app, key: str) -> None:
    """Note that `key` (a binder row, "scene:scn_1") was visited. Cheap."""
    if not app.project or not key:
        return
    if recents_for(app).push(key):
        # Written a couple of seconds later, once: selecting a run of rows with the
        # arrow keys must not rewrite the settings file for each one.
        if getattr(app, "_nav_persist_job", None) is None:
            try:
                app._nav_persist_job = app.after(2500, lambda: persist(app))
            except tk.TclError:
                app._nav_persist_job = None


def persist(app) -> None:
    app._nav_persist_job = None
    held = getattr(app, "_nav_recents", None)
    if not held or not held[0]:
        return
    stored = settings.get(_SETTING)
    stored = dict(stored) if isinstance(stored, dict) else {}
    stored.pop(held[0], None)
    stored[held[0]] = held[1].keys()
    while len(stored) > 20:                 # only the newest novels are remembered
        stored.pop(next(iter(stored)))
    settings[_SETTING] = stored


# ==========================================================================
# The window
# ==========================================================================


def binder_extras(app) -> List[navindex.Target]:
    """Maps and loose documents: not in the manifest, but the binder lists them."""
    found: List[navindex.Target] = []
    tree = app.tree

    def walk(node: str = ""):
        for child in tree.get_children(node):
            yield child
            yield from walk(child)

    for iid in walk():
        kind, _, _ident = iid.partition(":")
        if kind not in ("mapfile", "doc"):
            continue
        parent = tree.item(tree.parent(iid), "text") if tree.parent(iid) else ""
        found.append(navindex.make_target(
            iid, "map" if kind == "mapfile" else "doc",
            str(tree.item(iid, "text")), str(parent)))
    return found


def display_subtitle(target: navindex.Target) -> str:
    if not target.subtitle:
        return target.label
    if target.subtitle.startswith(target.label):
        return target.subtitle
    return f"{target.label} - {target.subtitle}"


class GoTo(tk.Toplevel):
    def __init__(self, app, initial: str = "") -> None:
        super().__init__(app)
        self.app = app
        self.withdraw()
        self.overrideredirect(True)
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass
        t = styling.current_tokens()
        scale = self._scale = getattr(app, "ui_scale", 1.0)

        self.targets = navindex.build_targets(app.project, binder_extras(app))
        self.recents = recents_for(app)
        self.shown: List[navindex.Target] = []
        self._job: Optional[str] = None
        self._icons = {}

        outline = tk.Frame(self, background=t["border_strong"])
        outline.pack(fill="both", expand=True)
        body = ttk.Frame(outline, padding=(10, 10, 10, 8))
        body.pack(fill="both", expand=True, padx=1, pady=1)
        body.columnconfigure(0, weight=1)

        self.query = tk.StringVar(value=initial)
        self.field = ttk.Entry(body, textvariable=self.query,
                               font=(styling.UI_FONT, 11))
        self.field.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.hint = ttk.Label(body, text="", style="Hint.TLabel")
        self.hint.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 6))

        self.tree = ttk.Treeview(body, columns=("sub",), show="tree",
                                 height=VISIBLE_ROWS, selectmode="browse")
        self._title_px = int(270 * scale)
        self._sub_px = int(270 * scale)
        self.tree.column("#0", width=self._title_px, stretch=True)
        self.tree.column("sub", width=self._sub_px, anchor="e", stretch=False)
        try:
            self._font = tkfont.Font(
                font=ttk.Style(self).lookup("Treeview", "font") or "TkDefaultFont")
        except tk.TclError:
            self._font = None
        self.tree.grid(row=2, column=0, sticky="nsew")
        bar = AutoScrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        bar.grid(row=2, column=1, sticky="ns")

        # A fixed two-line strip under the list, so choosing a row never makes the
        # window grow or shrink under the pointer.
        line = tkfont.Font(font=(styling.UI_FONT, styling.SMALL)).metrics("linespace")
        strip = ttk.Frame(body, height=2 * line + 4)
        strip.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        strip.grid_propagate(False)
        strip.columnconfigure(0, weight=1)
        self.preview = ttk.Label(strip, text="", style="Hint.TLabel",
                                 justify="left", anchor="nw",
                                 wraplength=int(520 * scale))
        self.preview.grid(row=0, column=0, sticky="nw")

        self.field.bind("<Down>", lambda _e: self._move(1) or "break")
        self.field.bind("<Up>", lambda _e: self._move(-1) or "break")
        self.field.bind("<Next>", lambda _e: self._move(VISIBLE_ROWS) or "break")
        self.field.bind("<Prior>", lambda _e: self._move(-VISIBLE_ROWS) or "break")
        self.field.bind("<Return>", lambda _e: self._run() or "break")
        self.field.bind("<Control-Return>",
                        lambda _e: self._run(open_in_word=True) or "break")
        self.bind("<Escape>", lambda _e: self.close())
        self.tree.bind("<ButtonRelease-1>", self._on_click)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_preview())
        self.query.trace_add("write", lambda *_a: self._schedule_refill())
        self.bind("<FocusOut>", lambda _e: self.after(150, self._maybe_close))

        self.refill()
        self._place()
        self.deiconify()
        self.lift()
        self.field.focus_force()
        if initial:
            self.field.icursor("end")

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

    def _icon(self, target: navindex.Target):
        icons = getattr(self.app, "icons", None)
        if icons is None:
            return ""
        t = styling.current_tokens()
        if target.kind == "scene":
            status = (target.attr("status") or [""])[0]
            colour = styling.ensure_contrast(
                STATUS_COLOURS.get(status, t["text_dim"]), t["field"], 2.6)
            return icons.dot(colour) or ""
        name = _ICONS.get(target.kind)
        if target.kind in ENTITY_TYPES:
            name = {"character": "person", "location": "pin", "item": "box",
                    "faction": "flag", "thread": "link"}[target.kind]
        return (icons.get(name, t["text_dim"]) if name else None) or ""

    # ------------------------------------------------------------------
    def _schedule_refill(self) -> None:
        # Coalesced, so a held key is one ranking per frame rather than one per repeat.
        if self._job is None:
            self._job = self.after(20, self.refill)

    def refill(self) -> None:
        """Rank for the current text and redraw the list."""
        self._job = None
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        text = self.query.get()
        if text.startswith(">"):
            self._hand_over(text[1:].strip())
            return
        query = navindex.parse_query(text)
        if query.empty:
            current = f"{self.app.selection_kind}:{self.app.selection_id}"
            self.shown = navindex.recent_targets(
                self.targets, self.recents.keys(), current)
            self.hint.configure(
                text="Recently visited  ·  Enter to go  ·  Esc to close"
                if self.recents.keys() else
                "Type a name to find it  ·  Enter to go  ·  Esc to close")
        else:
            self.shown = navindex.rank(self.targets, text)
            count = len(self.shown)
            self.hint.configure(
                text=f"{count} match{'es' if count != 1 else ''}  ·  "
                     f"Enter to go  ·  Ctrl+Enter opens in Word"
                if count else "Nothing matches  ·  Esc to close")
        self.tree.delete(*self.tree.get_children())
        for number, target in enumerate(self.shown):
            self.tree.insert(
                "", "end", iid=str(number),
                text="  " + self._fit(target.title, self._title_px - int(56 * self._scale)),
                image=self._icon(target),
                values=(self._fit(display_subtitle(target), self._sub_px - 14),))
        if self.shown:
            self.tree.selection_set("0")
            self.tree.see("0")
        self._show_preview()

    def _fit(self, text: str, pixels: int) -> str:
        """`text` cut to `pixels` wide with an ellipsis: a tree cell clips silently."""
        font = self._font
        if font is None or pixels <= 0 or font.measure(text) <= pixels:
            return text
        low, high = 0, len(text)
        while low < high:                       # longest prefix that still fits
            middle = (low + high + 1) // 2
            if font.measure(text[:middle].rstrip() + "…") <= pixels:
                low = middle
            else:
                high = middle - 1
        return text[:low].rstrip() + "…"

    def _show_preview(self) -> None:
        current = self.tree.selection()
        target = self.shown[int(current[0])] if current else None
        text = " ".join((target.preview if target else "").split())
        if len(text) > PREVIEW_CHARS:
            text = text[:PREVIEW_CHARS - 1].rstrip() + "…"
        self.preview.configure(text=text)

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

    # ------------------------------------------------------------------
    def _maybe_close(self) -> None:
        # Closed unless focus is somewhere inside this window: a click in the
        # binder or the editor is "I have changed my mind", not "keep it open".
        try:
            holder = self.focus_displayof()
            if holder is None or holder.winfo_toplevel() is not self:
                self.close()
        except tk.TclError:
            pass

    def close(self) -> None:
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except (ValueError, tk.TclError):
                pass
            self._job = None
        try:
            self.destroy()
        except tk.TclError:
            pass

    def _hand_over(self, rest: str) -> None:
        """A leading ">" means "I want a command": the command palette takes over."""
        app = self.app
        self.close()

        def open_palette() -> None:
            app.cmd_palette()
            opened = getattr(app, "_palette", None)
            if rest and opened is not None:
                try:
                    opened.query.set(rest)
                    opened.field.icursor("end")
                except tk.TclError:
                    pass

        app.after(20, open_palette)

    def _run(self, open_in_word: bool = False) -> None:
        current = self.tree.selection()
        if not current:
            return
        target = self.shown[int(current[0])]
        app = self.app
        self.close()
        # After this window has gone, so focus is back on the main window before
        # the jump (and before Word is asked to open anything).
        app.after(20, lambda: jump(app, target, open_in_word))


def jump(app, target: navindex.Target, open_in_word: bool = False) -> bool:
    """Take the app to a target. Shared by Go to and anything else that lists them."""
    kind, _, ident = target.key.partition(":")
    if kind == "idea":                      # ideas have no binder row: open the inbox
        remember(app, target.key)
        app.cmd_idea_inbox()
        return True
    if not app.goto(kind, ident):
        app.status.say("That is no longer in the binder.", 5)
        return False
    if open_in_word and kind in ("scene", "entity", "note", "doc"):
        app.after(60, app.cmd_open_in_word)
    return True
