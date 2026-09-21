"""
The Connections panel: what links to what you are looking at, at the foot of the
inspector for a scene, a character or place or item, a note and a timeline event.

It replaces a bare "Linked scenes: 12" and a "Where mentioned?" button that scanned
the manuscript into a pop-up report. Here the same information sits beside the thing
itself:

    Linked (12)               declared in the inspector; a click jumps there
    Mentioned, not linked (3) the name is in the prose, no link made - [Link] makes it
    Research (1)              notes attached to it
    Timeline (2)              events that cover it or are about it

The data is `backlinks.py`. This file is only drawing, and it draws from the manifest
and the persisted mention index: it never opens a Word document while it is being
built. (Showing where a name sits in a scene - the "named 3x" click - reads that one
scene, on the click.)
"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional, Set, Tuple

from .. import backlinks, mentionindex, storygraph
from . import styling

#: Rows shown per section before "Show all".
LIMIT = 12


def ago(seconds: float) -> str:
    """How long ago, in a few words: "just now", "5 min ago", "3 days ago"."""
    seconds = max(0.0, seconds)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = int(seconds // 86400)
    return f"{days} day{'s' if days != 1 else ''} ago"


def status_line(info: backlinks.Connections) -> Tuple[str, str]:
    """(what to say about how current the mentions are, the button's label or "")."""
    fresh = info.freshness
    if info.source == "graph":
        return "Live from the story graph.", ""
    if fresh.unscanned:
        return ("Names in the prose have not been looked for yet. Scan reads the "
                "manuscript once."), "Scan"
    when = f"Scanned {ago(time.time() - fresh.scanned)}."
    if fresh.names_changed:
        return f"{when} The cast's names have changed since.", "Update"
    if fresh.changed_scenes:
        n = fresh.changed_scenes
        return f"{when} {n} scene{'s' if n != 1 else ''} changed since.", "Update"
    return when, "Update"


def rebuild_inspector(app) -> None:
    """
    Draw the inspector again after a link was made or a scan finished.

    For a scene only the inspector is rebuilt: going through `render_selection` would
    reload the editor from disk and put the caret back at the top of the page.
    """
    if not app.project:
        return
    if app.selection_kind == "scene":
        scene = app.project.data.scene(app.selection_id)
        if scene is not None:
            app._build_scene_inspector(scene)
            return
    app.render_selection()


def attach(app, form, kind: str, ident: str) -> "ConnectionsPanel":
    """Add the Connections section to the foot of an inspector `Form`."""
    form.heading("Connections")
    panel = ConnectionsPanel(form.parent, app, kind, ident)
    panel.grid(row=form._row_index, column=0, columnspan=2, sticky="ew",
               padx=(2, 6), pady=(0, 6))
    form._row_index += 1
    return panel


class ConnectionsPanel(ttk.Frame):
    def __init__(self, parent, app, kind: str, ident: str) -> None:
        super().__init__(parent)
        self.app = app
        self.kind, self.ident = kind, ident
        self.columnconfigure(0, weight=1)
        self._scale = getattr(app, "ui_scale", 1.0)
        self._wrap = int(190 * self._scale)
        self._width = 0
        self._all: Set[str] = set()             # sections opened with "Show all"
        self._context: Dict[Tuple[str, str], str] = {}   # shown snippets, by row
        # For tests and for anything that wants to poke the rows.
        self.title_labels: List[Tuple[backlinks.Row, ttk.Label]] = []
        self.link_buttons: List[Tuple[backlinks.Row, ttk.Button]] = []
        self.context_labels: List[ttk.Label] = []
        self.status_label: Optional[ttk.Label] = None
        self.update_button: Optional[ttk.Button] = None

        # A current graph is the freshest source; asking for it costs nothing when
        # none is built (it is never built from here).
        self.graph = storygraph.cached_graph(app.project)
        self.info = backlinks.connections(app.project, kind, ident, graph=self.graph)
        self._draw()
        self.bind("<Configure>", self._on_width, add="+")

    # ------------------------------------------------------------------
    def _on_width(self, event) -> None:
        # Titles wrap to the pane, so a wider pane is used and a narrow one is not
        # overrun. Guarded on the width: wrapping changes the height, which must not
        # start another pass.
        if event.width <= 1 or event.width == self._width:
            return
        self._width = event.width
        wrap = max(int(80 * self._scale), event.width - int(120 * self._scale))
        if wrap != self._wrap:
            self._wrap = wrap
            for _row, label in self.title_labels:
                label.configure(wraplength=wrap)
            if self.status_label is not None:
                self.status_label.configure(wraplength=max(60, event.width - int(80 * self._scale)))

    def _draw(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self.title_labels.clear()
        self.link_buttons.clear()
        self.context_labels.clear()
        info = self.info
        r = 0

        # -- how current the mentions are, and the button that brings them up to date
        head = ttk.Frame(self)
        head.grid(row=r, column=0, sticky="ew", pady=(0, 4))
        head.columnconfigure(0, weight=1)
        text, button = status_line(info)
        self.status_label = ttk.Label(head, text=text, style="Hint.TLabel",
                                      wraplength=int(200 * self._scale),
                                      justify="left")
        self.status_label.grid(row=0, column=0, sticky="w")
        self.update_button = None
        if button:
            self.update_button = ttk.Button(head, text=button, style="Compact.TButton",
                                            command=self.scan)
            self.update_button.grid(row=0, column=1, sticky="e", padx=(6, 0))
        r += 1

        if not info.sections:
            ttk.Label(self, text="Nothing connects to this yet.",
                      style="Hint.TLabel").grid(row=r, column=0, sticky="w")
            return

        for section in info.sections:
            title = ttk.Label(self, text=f"{section.title} ({len(section.rows)})",
                              font=(styling.UI_FONT, styling.BASE, "bold"))
            title.grid(row=r, column=0, sticky="w", pady=(8, 2))
            r += 1
            shown = section.rows if section.key in self._all \
                else section.rows[:LIMIT]
            for row in shown:
                self._row(r, section.key, row)
                r += 1
                if (section.key, row.iid) in self._context:
                    label = ttk.Label(self, text=self._context[(section.key, row.iid)],
                                      style="Hint.TLabel", justify="left",
                                      wraplength=self._wrap + int(60 * self._scale))
                    label.grid(row=r, column=0, sticky="w", padx=(14, 0), pady=(0, 3))
                    self.context_labels.append(label)
                    r += 1
            if len(section.rows) > len(shown):
                more = ttk.Button(
                    self, text=f"Show all {len(section.rows)}",
                    style="Compact.TButton",
                    command=lambda k=section.key: self._show_all(k))
                more.grid(row=r, column=0, sticky="w", pady=(3, 0))
                r += 1

    def _row(self, r: int, section_key: str, row: backlinks.Row) -> None:
        frame = ttk.Frame(self)
        frame.grid(row=r, column=0, sticky="ew", pady=1)
        frame.columnconfigure(0, weight=1)
        title = ttk.Label(frame, text=row.title, cursor="hand2",
                          wraplength=self._wrap, justify="left")
        title.grid(row=0, column=0, sticky="w", padx=(10, 0))
        self.title_labels.append((row, title))
        self._hover(title)
        title.bind("<Button-1>", lambda _e, x=row: self._open(x), add="+")

        column = 1
        if row.detail:
            detail = ttk.Label(frame, text=row.detail, style="Hint.TLabel")
            detail.grid(row=0, column=column, sticky="e", padx=(8, 0))
            column += 1
            if row.can_link and row.link_kind == "scene":
                # "named 3x" is also the way to see where: it reads that one scene.
                detail.configure(cursor="hand2")
                self._hover(detail)
                detail.bind("<Button-1>",
                            lambda _e, s=section_key, x=row: self._toggle_context(s, x),
                            add="+")
                styling.Tooltip(detail, "Click to see where it is named")
        if row.can_link:
            link = ttk.Button(frame, text="Link", style="Compact.TButton",
                              command=lambda x=row: self._link(x))
            link.grid(row=0, column=column, sticky="e", padx=(8, 0))
            self.link_buttons.append((row, link))
            styling.Tooltip(link, "Add it to this scene's links (Ctrl+Z undoes)"
                            if row.link_kind == "scene"
                            else "Add it to this event (Ctrl+Z undoes)")

    def _hover(self, label: ttk.Label) -> None:
        def enter(_e) -> None:
            label.configure(foreground=styling.current_tokens()["accent"])

        def leave(_e) -> None:
            label.configure(foreground="")

        label.bind("<Enter>", enter, add="+")
        label.bind("<Leave>", leave, add="+")

    # ------------------------------------------------------------------
    def _open(self, row: backlinks.Row) -> None:
        # After this click has finished: jumping rebuilds the inspector, which
        # destroys the very label that was clicked.
        self.after_idle(lambda: self._jump(row))

    def _jump(self, row: backlinks.Row) -> None:
        if not self.app.goto(row.kind, row.id):
            self.app.status.say("That is no longer in the binder.", 5)

    def _show_all(self, section_key: str) -> None:
        self._all.add(section_key)
        self._draw()

    def _toggle_context(self, section_key: str, row: backlinks.Row) -> None:
        key = (section_key, row.iid)
        if key in self._context:
            del self._context[key]
        else:
            # The one place a document is opened: this scene, because it was asked for.
            found = mentionindex.snippet(self.app.project, row.link_target,
                                         row.entity_id, self.graph)
            self._context[key] = found or ("(Not found any more - the scene has "
                                           "changed. Update to refresh.)")
        self._draw()

    def _link(self, row: backlinks.Row) -> None:
        self.after_idle(lambda: self._do_link(row))

    def _do_link(self, row: backlinks.Row) -> None:
        app = self.app
        if not app.project:
            return
        app.commit_all()                        # inspector edits first, so undo is clean
        entity = app.project.data.entity(row.entity_id)
        if backlinks.link_mention(app.project, row.link_kind, row.link_target,
                                  row.entity_id):
            app.project.save()
            app._sync_history_menu()
            name = entity.name if entity else "It"
            app.status.say(f"Linked {name}.  Ctrl+Z undoes it.", 8)
        rebuild_inspector(app)

    def scan(self) -> None:
        self.after_idle(self.app.cmd_scan_mentions)
