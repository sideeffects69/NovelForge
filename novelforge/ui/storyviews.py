"""
The windows that sit on top of the story graph.

Four separate windows rather than one crowded one, because each answers a
different question and you want them open at different moments:

    StoryGraphWindow    what is in this book, and what is wrong with it
    IdeaInboxWindow     catch a thought now, decide where it goes later
    DraftsDialog        try a different version of this scene
    NoteLinksDialog     attach research to the thing it is research for

Everything here is read-mostly and cheap: the graph is built once per window
and reused, and the graph itself is cached between windows.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .. import storygraph
from ..config import THEMES, open_in_default_app, settings
from ..model import ENTITY_LABELS
from .dialogs import Dialog
from .widgets import shell, AutoScrollbar, ScrolledText, center_window


def _monospace(widget: ScrolledText) -> None:
    theme = THEMES.get(settings["theme"], THEMES["warm"])
    widget.text.configure(
        background=theme["bg"], foreground=theme["fg"],
        insertbackground=theme["caret"], selectbackground=theme["select"],
    )


def build_graph_with_progress(parent, project):
    """
    Build the story graph, showing a bar if it is going to take a while.

    A small novel builds in a fraction of a second and the window never
    appears; a 300,000 word one takes about twenty-five seconds the first
    time, and silence for that long reads as a hang. The bar is only created
    once the read is already under way, so the common case costs nothing.
    """
    cached = storygraph.cached_graph(project)
    if cached is not None:
        return cached

    state: Dict[str, Any] = {"window": None, "bar": None, "label": None}

    def report(done: int, total: int) -> None:
        if state["window"] is None:
            if total < 60:
                return          # fast enough that a dialog would only flicker
            window = tk.Toplevel(parent)
            window.title("Reading the manuscript")
            window.transient(parent)
            window.resizable(False, False)
            frame = ttk.Frame(window, padding=16)
            frame.grid(row=0, column=0, sticky="nsew")
            state["label"] = ttk.Label(
                frame, text="Reading the manuscript...", width=44)
            state["label"].grid(row=0, column=0, sticky="w", pady=(0, 8))
            ttk.Label(
                frame,
                text="This happens once. Afterwards it is instant until you "
                     "edit something.",
                wraplength=320, justify="left", style="Hint.TLabel",
            ).grid(row=2, column=0, sticky="w", pady=(8, 0))
            state["bar"] = ttk.Progressbar(frame, length=320, maximum=total)
            state["bar"].grid(row=1, column=0, sticky="ew")
            center_window(window, 380, 150)
            window.update()
            state["window"] = window
        if state["window"] is not None:
            state["bar"]["value"] = done
            state["label"].configure(text=f"Reading scene {done:,} of {total:,}")
            state["window"].update()

    try:
        return storygraph.build(project, progress=report)
    finally:
        if state["window"] is not None:
            try:
                state["window"].destroy()
            except Exception:
                pass
        parent.update_idletasks()


class ReplaceWindow(tk.Toplevel):
    """
    Find and replace across the whole project.

    Renaming a character is the reason this exists. On a 300,000 word
    manuscript it is the difference between ten seconds and an afternoon, and
    doing it by hand in Word means missing the scene cards, the character
    sheets and the aliases.

    Nothing is written until Replace All is pressed, and Preview is the
    default action so the writer always sees the damage first.
    """

    def __init__(self, parent, project, on_change: Callable[[], None]) -> None:
        super().__init__(parent)
        self.project = project
        self.on_change = on_change
        self.title(f"Find and Replace - {project.data.title}")
        self._previewed = ""

        frame = shell(self, 12)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(5, weight=1)

        ttk.Label(frame, text="Find").grid(row=0, column=0, sticky="w",
                                           padx=(0, 8), pady=2)
        self.find_entry = ttk.Entry(frame)
        self.find_entry.grid(row=0, column=1, sticky="ew", pady=2)
        self.find_entry.bind("<Return>", lambda _e: self.cmd_preview())

        ttk.Label(frame, text="Replace with").grid(row=1, column=0, sticky="w",
                                                   padx=(0, 8), pady=2)
        self.replace_entry = ttk.Entry(frame)
        self.replace_entry.grid(row=1, column=1, sticky="ew", pady=2)
        self.replace_entry.bind("<Return>", lambda _e: self.cmd_preview())

        options = ttk.Frame(frame)
        options.grid(row=2, column=1, sticky="w", pady=(6, 0))
        self.whole_word = tk.BooleanVar(value=True)
        self.match_case = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text="Whole words only",
                        variable=self.whole_word).grid(row=0, column=0,
                                                       padx=(0, 12))
        ttk.Checkbutton(options, text="Match case",
                        variable=self.match_case).grid(row=0, column=1)

        ttk.Label(frame, text="Look in").grid(row=3, column=0, sticky="nw",
                                              padx=(0, 8), pady=(8, 0))
        where = ttk.Frame(frame)
        where.grid(row=3, column=1, sticky="w", pady=(8, 0))
        self.scopes = {
            "manuscript": tk.BooleanVar(value=True),
            "cards": tk.BooleanVar(value=True),
            "sheets": tk.BooleanVar(value=True),
            "notes": tk.BooleanVar(value=True),
            "names": tk.BooleanVar(value=False),
        }
        for index, (key, label) in enumerate([
            ("manuscript", "The manuscript"),
            ("cards", "Scene and chapter cards"),
            ("sheets", "Character and place sheets"),
            ("notes", "Notes and research"),
            ("names", "Names and aliases themselves"),
        ]):
            ttk.Checkbutton(where, text=label,
                            variable=self.scopes[key]).grid(
                row=index // 2, column=index % 2, sticky="w", padx=(0, 16))

        ttk.Label(
            frame,
            text="Nothing is changed until you press Replace All. Every "
                 "document is copied to its version history first, so any "
                 "single file can be put back from File > Versions.",
            wraplength=620, justify="left", style="Hint.TLabel",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 6))

        self.results = ScrolledText(frame, height=16, wrap="none",
                                    font=("Consolas", 9))
        self.results.grid(row=5, column=0, columnspan=2, sticky="nsew")
        _monospace(self.results)
        self.results.set_readonly(True)

        bar = ttk.Frame(frame)
        bar.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(bar, text="Preview", command=self.cmd_preview).grid(
            row=0, column=0, padx=(0, 6))
        self.replace_button = ttk.Button(bar, text="Replace All",
                                         command=self.cmd_replace,
                                         state="disabled")
        self.replace_button.grid(row=0, column=1, padx=(0, 6))
        bar.columnconfigure(2, weight=1)
        ttk.Button(bar, text="Close", command=self.destroy).grid(
            row=0, column=3, sticky="e")

        center_window(self, 760, 620, min_width=560, min_height=420)
        self.find_entry.focus_set()
        self.bind("<Escape>", lambda _e: self.destroy())

    def _chosen(self) -> List[str]:
        return [key for key, var in self.scopes.items() if var.get()]

    def _show(self, text: str) -> None:
        self.results.set_report(text)

    def cmd_preview(self) -> None:
        needle = self.find_entry.get()
        if not needle.strip():
            self._show("Type something to find.")
            return
        scopes = self._chosen()
        if not scopes:
            self._show("Choose at least one place to look in.")
            return
        rows = self.project.preview_replace(
            needle, self.replace_entry.get(), scopes=scopes,
            match_case=self.match_case.get(),
            whole_word=self.whole_word.get())
        if not rows:
            self._show(f"'{needle}' does not appear anywhere you have chosen.")
            self.replace_button.configure(state="disabled")
            self._previewed = ""
            return

        total = sum(row[2] for row in rows)
        lines = [
            f"{total} occurrence{'' if total == 1 else 's'} of '{needle}' "
            f"in {len(rows)} place{'' if len(rows) == 1 else 's'}",
            "=" * 74, "",
        ]
        for kind, label, count, snippet in rows:
            lines.append(f"  {count:>4}  [{kind}] {label}")
            if snippet:
                lines.append(f"        {snippet}")
            lines.append("")
        self._show("\n".join(lines))
        self.replace_button.configure(state="normal")
        self._previewed = needle

    def cmd_replace(self) -> None:
        needle = self.find_entry.get()
        replacement = self.replace_entry.get()
        if not needle.strip():
            return
        if needle != self._previewed:
            self._show("The search changed. Preview it again first.")
            self.replace_button.configure(state="disabled")
            return
        rows = self.project.preview_replace(
            needle, replacement, scopes=self._chosen(),
            match_case=self.match_case.get(),
            whole_word=self.whole_word.get())
        total = sum(row[2] for row in rows)
        if not messagebox.askyesno(
            "Replace everywhere",
            f"Replace {total} occurrence"
            f"{'' if total == 1 else 's'} of '{needle}' with "
            f"'{replacement}'?\n\n"
            f"Across {len(rows)} place{'' if len(rows) == 1 else 's'}.\n\n"
            f"Every document is copied to its version history first.",
            parent=self,
        ):
            return

        with self.project.action(f"replace '{needle}' with '{replacement}'"):
            replaced, documents, problems = self.project.replace_everywhere(
                needle, replacement, scopes=self._chosen(),
                match_case=self.match_case.get(),
                whole_word=self.whole_word.get())
        self.project.save()

        from .. import storygraph

        storygraph.invalidate(self.project)
        self.on_change()

        lines = [
            "DONE",
            "=" * 74, "",
            f"  {replaced} replacement{'' if replaced == 1 else 's'}",
            f"  {documents} document{'' if documents == 1 else 's'} changed",
            "",
        ]
        if problems:
            lines += ["  These could not be changed:", ""]
            for label, reason in problems:
                lines.append(f"    {label}")
                lines.append(f"        {reason[:120]}")
            lines += ["", "  Close them in Word and run it again."]
        else:
            lines.append("  Ctrl+Z undoes the card and name changes. Prose is "
                         "in each document's version history.")
        self._show("\n".join(lines))
        self.replace_button.configure(state="disabled")
        self._previewed = ""


class ChapterMapWindow(tk.Toplevel):
    """
    The map as it stands at any chapter.

    Drag the slider to chapter eighteen and the map shows where everyone is by
    then, the route each of them took to get there, which places that chapter
    names, and which places you drew but the story has still never touched.

    Nothing is simulated. Every mark comes from the manuscript: a character is
    at the location of the last scene they appeared in, and a place is
    "mentioned" because its name is in the prose.
    """

    #: Kept deliberately few. A map with forty coloured overlays is a map you
    #: cannot read.
    HERE = "#2f7d4f"          # a character is here now
    ROUTE = "#7a6a52"         # travelled through
    MENTIONED = "#c08a3e"     # named in this chapter
    UNTOUCHED = "#9a9a9a"     # pinned, never mentioned

    def __init__(self, parent, project, graph) -> None:
        super().__init__(parent)
        self.project = project
        self.graph = graph
        self.title(f"Chapter Map - {project.data.title}")

        from .. import mapstory

        self.mapstory = mapstory
        self.maps = mapstory.load_maps(project)
        self.pins = mapstory.pin_index(project, self.maps)
        self.states = mapstory.chapter_states(project, graph)
        self.game_map = self.maps[0] if self.maps else None

        container = shell(self, 8)
        container.rowconfigure(1, weight=1)
        container.columnconfigure(0, weight=1)

        top = ttk.Frame(container)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        top.columnconfigure(2, weight=1)
        ttk.Label(top, text="Map").grid(row=0, column=0, padx=(0, 4))
        self.map_choice = ttk.Combobox(
            top, state="readonly", width=26,
            values=[m.name for m in self.maps] or ["(no maps yet)"])
        self.map_choice.grid(row=0, column=1, padx=(0, 12))
        if self.maps:
            self.map_choice.current(0)
        self.map_choice.bind("<<ComboboxSelected>>",
                             lambda _e: self._pick_map())

        self.chapter_label = ttk.Label(top, text="", style="Section.TLabel")
        self.chapter_label.grid(row=0, column=2, sticky="w")

        panes = ttk.PanedWindow(container, orient="horizontal")
        panes.grid(row=1, column=0, sticky="nsew")

        left = ttk.Frame(panes)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(left, background="#efe6d2",
                                highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _e: self.redraw())
        panes.add(left, weight=4)

        right = ttk.Frame(panes, padding=(8, 0, 0, 0))
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        ttk.Label(right, text="At this point in the book").grid(
            row=0, column=0, sticky="w")
        self.detail = ScrolledText(right, height=20, width=34, wrap="word",
                                   font=("Consolas", 9))
        self.detail.grid(row=1, column=0, sticky="nsew")
        _monospace(self.detail)
        self.detail.set_readonly(True)
        panes.add(right, weight=2)

        slider = ttk.Frame(container)
        slider.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        slider.columnconfigure(1, weight=1)
        ttk.Label(slider, text="Chapter").grid(row=0, column=0, padx=(0, 6))
        self.chapter_var = tk.IntVar(value=max(0, len(self.states) - 1))
        self.slider = ttk.Scale(
            slider, from_=0, to=max(0, len(self.states) - 1),
            orient="horizontal", command=lambda _v: self.redraw())
        self.slider.grid(row=0, column=1, sticky="ew")
        self.slider.set(max(0, len(self.states) - 1))

        bar = ttk.Frame(container)
        bar.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        for index, (text, colour) in enumerate([
            ("here now", self.HERE), ("travelled", self.ROUTE),
            ("named this chapter", self.MENTIONED),
            ("never mentioned", self.UNTOUCHED),
        ]):
            dot = tk.Canvas(bar, width=12, height=12, highlightthickness=0)
            dot.create_oval(2, 2, 11, 11, fill=colour, outline="")
            dot.grid(row=0, column=index * 2, padx=(0 if index == 0 else 10, 3))
            ttk.Label(bar, text=text, style="Hint.TLabel").grid(
                row=0, column=index * 2 + 1)
        bar.columnconfigure(8, weight=1)
        ttk.Button(bar, text="Close", command=self.destroy).grid(
            row=0, column=9, sticky="e")

        center_window(self, 1080, 720, min_width=700, min_height=460)
        self.bind("<Escape>", lambda _e: self.destroy())
        # The report pane asks for a wide text box, which drags the sash left
        # and leaves the map in a sliver. Put it back once the window has a
        # real width to divide.
        self.after(80, lambda: self._split(panes))
        self.after(140, self.redraw)

    def _split(self, panes: ttk.PanedWindow) -> None:
        try:
            panes.sashpos(0, int(self.winfo_width() * 0.62))
        except tk.TclError:
            pass

    # -- drawing ---------------------------------------------------------
    def _pick_map(self) -> None:
        index = self.map_choice.current()
        if 0 <= index < len(self.maps):
            self.game_map = self.maps[index]
            self.redraw()

    def _transform(self) -> Tuple[float, float, float]:
        """Scale and offset that fit the map inside the canvas."""
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        map_w = max(1, getattr(self.game_map, "width", 1600))
        map_h = max(1, getattr(self.game_map, "height", 1100))
        scale = min(width / map_w, height / map_h) * 0.94
        return scale, (width - map_w * scale) / 2, (height - map_h * scale) / 2

    def redraw(self) -> None:
        self.canvas.delete("all")
        if self.game_map is None:
            self.canvas.create_text(
                20, 20, anchor="nw", width=400, fill="#6b6152",
                text="No maps yet.\n\nDraw one with the Map Maker (Ctrl+M) and "
                     "link its pins to your locations. This view then shows "
                     "where everyone is, chapter by chapter.")
            return
        if not self.states:
            return

        index = int(round(float(self.slider.get())))
        index = max(0, min(index, len(self.states) - 1))
        state = self.states[index]
        self.chapter_label.configure(
            text=f"{state.chapter_title}   "
                 f"({index + 1} of {len(self.states)})")

        scale, offset_x, offset_y = self._transform()

        # The map itself, drawn from the same primitives the exporters use so
        # it looks like the map the writer drew rather than an approximation.
        try:
            from .. import mapmaker as mm

            # The primitive tuples differ by kind - polygons carry a fill and
            # an outline colour where lines carry one colour and a width - so
            # each is unpacked on its own terms rather than assumed.
            for primitive in mm.build_primitives(self.game_map):
                kind = primitive[0]
                payload = primitive[1] if kind != "ellipse" else ()

                def place(points):
                    flat = []
                    for x, y in points:
                        flat += [offset_x + x * scale, offset_y + y * scale]
                    return flat

                if kind == "polygon" and len(payload) >= 3:
                    fill, outline, width = primitive[2], primitive[3], primitive[4]
                    self.canvas.create_polygon(
                        place(payload), fill=fill or "",
                        outline=outline or "", width=max(1, width * scale))
                elif kind == "line" and len(payload) >= 2:
                    colour, width = primitive[2], primitive[3]
                    self.canvas.create_line(
                        place(payload), fill=colour,
                        width=max(1, width * scale))
                elif kind == "ellipse" and len(primitive) >= 7:
                    # (kind, x0, y0, x1, y1, fill, outline, width)
                    x0, y0, x1, y1 = primitive[1:5]
                    self.canvas.create_oval(
                        offset_x + x0 * scale, offset_y + y0 * scale,
                        offset_x + x1 * scale, offset_y + y1 * scale,
                        fill=primitive[5] or "", outline="")
                # Text from the map itself is skipped: this view draws its own
                # labels, and two sets on top of each other is unreadable.
        except Exception:
            self.canvas.create_rectangle(
                offset_x, offset_y,
                offset_x + self.game_map.width * scale,
                offset_y + self.game_map.height * scale,
                outline="#b8a888")

        # Who is where.
        here_now: Dict[str, List[str]] = {}
        for presence in state.characters.values():
            if presence.here:
                here_now.setdefault(presence.here, []).append(presence.name)
        travelled = {loc for p in state.characters.values() for loc in p.route}

        for entity_id, ref in self.pins.items():
            pin = ref.pin
            if getattr(ref, "map_id", "") != getattr(self.game_map, "id", ""):
                continue
            x = offset_x + pin.x * scale
            y = offset_y + pin.y * scale
            if entity_id in here_now:
                colour, radius = self.HERE, 7
            elif entity_id in state.mentioned_now:
                colour, radius = self.MENTIONED, 6
            elif entity_id in travelled:
                colour, radius = self.ROUTE, 5
            elif entity_id in state.mentioned_ever:
                colour, radius = self.ROUTE, 4
            else:
                colour, radius = self.UNTOUCHED, 4
            self.canvas.create_oval(x - radius, y - radius, x + radius,
                                    y + radius, fill=colour, outline="#2b2b2b")
            label = ref.label
            if entity_id in here_now:
                label += "  " + ", ".join(here_now[entity_id])
            # Flip the label to the other side near the right edge, or a pin
            # in the east of the map has its name run off the canvas.
            if x > self.canvas.winfo_width() * 0.7:
                self.canvas.create_text(x - radius - 4, y, anchor="e",
                                        text=label, font=("Georgia", 9),
                                        fill="#2b2b2b")
            else:
                self.canvas.create_text(x + radius + 4, y, anchor="w",
                                        text=label, font=("Georgia", 9),
                                        fill="#2b2b2b")

        # Routes, drawn behind nothing but readable enough.
        for presence in state.characters.values():
            points: List[float] = []
            for location_id in presence.route:
                ref = self.pins.get(location_id)
                if ref and getattr(ref, "map_id", "") == getattr(
                        self.game_map, "id", ""):
                    points += [offset_x + ref.pin.x * scale,
                               offset_y + ref.pin.y * scale]
            if len(points) >= 4:
                self.canvas.create_line(points, fill=self.ROUTE, width=2,
                                        dash=(5, 4), arrow="last",
                                        smooth=True)

        self._write_detail(state, here_now)

    def _write_detail(self, state, here_now: Dict[str, List[str]]) -> None:
        def name_of(entity_id: str) -> str:
            node = self.graph.nodes.get(entity_id)
            return node.name if node else "?"

        lines = [state.chapter_title, "=" * 40, ""]
        if state.characters:
            lines.append("WHERE EVERYONE IS")
            lines.append("")
            for presence in sorted(state.characters.values(),
                                   key=lambda p: p.name):
                lines.append(f"  {presence.name}")
                lines.append(f"      at {name_of(presence.here)}")
                if len(presence.route) > 1:
                    trail = " -> ".join(name_of(r) for r in presence.route[-4:])
                    lines.append(f"      via {trail}")
            lines.append("")
        if state.mentioned_now:
            lines += ["NAMED IN THIS CHAPTER", ""]
            for location_id in state.mentioned_now:
                lines.append(f"  {name_of(location_id)}")
            lines.append("")
        if state.untouched:
            lines += ["ON THE MAP, NEVER MENTIONED", ""]
            for location_id in state.untouched[:20]:
                lines.append(f"  {name_of(location_id)}")
            lines.append("")
        if not state.characters and not state.mentioned_now:
            lines += ["Nothing in this chapter names a place that is",
                      "linked to a location, so there is nothing to show.",
                      "",
                      "Link locations to scenes, or pin them on the map,",
                      "and this fills in."]
        self.detail.set_report("\n".join(lines))


def scrolled(parent, widget_factory, row: int = 0, column: int = 0):
    """
    Put a list or tree in a frame with a scrollbar and return it.

    Every list in this application can grow past the window: a novel has
    hundreds of scenes and a squeezed window has room for eight. Without this
    the rest are simply unreachable.
    """
    holder = ttk.Frame(parent)
    holder.grid(row=row, column=column, sticky="nsew")
    holder.rowconfigure(0, weight=1)
    holder.columnconfigure(0, weight=1)
    widget = widget_factory(holder)
    widget.grid(row=0, column=0, sticky="nsew")
    bar = AutoScrollbar(holder, orient="vertical", command=widget.yview)
    bar.grid(row=0, column=1, sticky="ns")
    widget.configure(yscrollcommand=bar.set)
    return widget


# ==========================================================================
# The story graph window
# ==========================================================================


class StoryGraphWindow(tk.Toplevel):
    """
    Everything the graph knows, in four tabs.

    Non-modal on purpose: the whole point of the continuity tab is to have it
    open beside the manuscript while you fix what it found.
    """

    def __init__(self, parent, project, start_tab: str = "") -> None:
        super().__init__(parent)
        self.project = project
        self.title(f"Story Graph - {project.data.title}")
        self.graph = build_graph_with_progress(parent, project)

        container = shell(self, 8)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        self.notebook = ttk.Notebook(container)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        self.views: Dict[str, ScrolledText] = {}
        for key, label in [("overview", "Overview"),
                           ("continuity", "Continuity"),
                           ("relationships", "Relationships")]:
            frame = ttk.Frame(self.notebook, padding=6)
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(0, weight=1)
            view = ScrolledText(frame, height=28, wrap="none",
                                font=("Consolas", 10))
            view.grid(row=0, column=0, sticky="nsew")
            _monospace(view)
            view.set_readonly(True)
            self.views[key] = view
            self.notebook.add(frame, text=label)

        self._build_ask_tab()

        bar = ttk.Frame(container)
        bar.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(bar, text="Refresh", command=self.refresh).grid(
            row=0, column=0, padx=(0, 6))
        ttk.Button(bar, text="Write Story Bible",
                   command=self.cmd_story_bible).grid(row=0, column=1,
                                                      padx=(0, 6))
        ttk.Button(bar, text="Copy this tab",
                   command=self._copy).grid(row=0, column=2, padx=(0, 6))
        bar.columnconfigure(3, weight=1)
        ttk.Button(bar, text="Close", command=self.destroy).grid(
            row=0, column=4, sticky="e")

        self.refresh()
        center_window(self, 940, 680, min_width=620, min_height=420)
        self.bind("<Escape>", lambda _e: self.destroy())
        if start_tab:
            self.show_tab(start_tab)

    # -- the question tab ------------------------------------------------
    def _build_ask_tab(self) -> None:
        frame = ttk.Frame(self.notebook, padding=6)
        frame.rowconfigure(3, weight=1)
        frame.columnconfigure(0, weight=1)

        ttk.Label(
            frame,
            text="Ask about your own book. This searches the graph and the "
                 "manuscript on this machine - it never invents anything and "
                 "never sends your writing anywhere.",
            wraplength=860, justify="left", style="Hint.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        row = ttk.Frame(frame)
        row.grid(row=1, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)
        self.question = ttk.Entry(row)
        self.question.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.question.bind("<Return>", lambda _e: self.cmd_ask())
        ttk.Button(row, text="Ask", command=self.cmd_ask).grid(row=0, column=1)

        examples = ttk.Frame(frame)
        examples.grid(row=2, column=0, sticky="w", pady=(6, 6))
        for index, text in enumerate(storygraph.SUGGESTED_QUESTIONS):
            ttk.Button(
                examples, text=text,
                command=lambda t=text: self._prefill(t),
            ).grid(row=index // 3, column=index % 3, padx=(0, 4), pady=2,
                   sticky="w")

        self.answer_view = ScrolledText(frame, height=20, wrap="word",
                                        font=("Consolas", 10))
        self.answer_view.grid(row=3, column=0, sticky="nsew")
        _monospace(self.answer_view)
        self.answer_view.set_readonly(True)
        self.notebook.add(frame, text="Ask")

    def _prefill(self, text: str) -> None:
        self.question.delete(0, "end")
        self.question.insert(0, text)
        self.question.focus_set()
        if "<" not in text:
            self.cmd_ask()

    def cmd_ask(self) -> None:
        question = self.question.get().strip()
        if not question:
            return
        reply = storygraph.answer(self.project, self.graph, question)
        self.answer_view.set_report(reply)

    # -- the report tabs -------------------------------------------------
    def refresh(self) -> None:
        self.graph = build_graph_with_progress(self, self.project)
        issues = storygraph.check_continuity(self.project, self.graph)
        bodies = {
            "overview": storygraph.overview_text(self.project, self.graph),
            "continuity": storygraph.continuity_text(self.project, issues),
            "relationships": storygraph.relationship_timeline_text(
                self.project, self.graph),
        }
        for key, body in bodies.items():
            view = self.views[key]
            view.set_report(body)

    def show_tab(self, key: str) -> None:
        order = ["overview", "continuity", "relationships", "ask"]
        if key in order:
            self.notebook.select(order.index(key))
            if key == "ask":
                self.question.focus_set()

    def _current_body(self) -> str:
        index = self.notebook.index("current")
        if index == 3:
            return self.answer_view.get_value()
        return list(self.views.values())[index].get_value()

    def _copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._current_body())

    def cmd_story_bible(self) -> None:
        try:
            path = storygraph.write_story_bible(self.project, self.graph)
        except Exception as exc:
            messagebox.showerror("Could not write it", str(exc), parent=self)
            return
        if messagebox.askyesno(
            "Story Bible written",
            f"Written to:\n\n{path.name}\n\nOpen it now?",
            parent=self,
        ):
            open_in_default_app(path)


# ==========================================================================
# Idea inbox
# ==========================================================================


class IdeaInboxWindow(tk.Toplevel):
    """
    Catch a thought without deciding anything about it.

    The cost of an idea is the interruption, so capture is one box and one key.
    Filing happens later, and the tool offers a shortlist of places it might
    belong - worked out by matching the idea's words against your scenes and
    characters, not by guessing.
    """

    def __init__(self, parent, project, on_change: Callable[[], None]) -> None:
        super().__init__(parent)
        self.project = project
        self.on_change = on_change
        self.title(f"Idea Inbox - {project.data.title}")
        self._suggestions: List[Tuple[str, str, float]] = []

        container = shell(self, 10)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)

        ttk.Label(
            container,
            text="Type it and press Enter. Decide where it goes another day.",
            style="Hint.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        capture = ttk.Frame(container)
        capture.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        capture.columnconfigure(0, weight=1)
        self.entry = ttk.Entry(capture, font=("Georgia", 11))
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.entry.bind("<Return>", lambda _e: self.cmd_capture())
        ttk.Button(capture, text="Catch it",
                   command=self.cmd_capture).grid(row=0, column=1)

        panes = ttk.PanedWindow(container, orient="horizontal")
        panes.grid(row=2, column=0, sticky="nsew")

        left = ttk.Frame(panes)
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)
        ttk.Label(left, text="Ideas").grid(row=0, column=0, sticky="w")
        self.tree = scrolled(left, lambda holder: ttk.Treeview(
            holder, columns=("status",), show="tree headings",
            selectmode="browse"), row=1)
        self.tree.heading("#0", text="Idea")
        self.tree.heading("status", text="Status")
        self.tree.column("#0", width=380, minwidth=140)
        self.tree.column("status", width=80, minwidth=60, anchor="center")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())
        panes.add(left, weight=3)

        right = ttk.Frame(panes)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        ttk.Label(right, text="Where it might belong").grid(
            row=0, column=0, sticky="w")
        self.suggestions = scrolled(right, lambda holder: tk.Listbox(
            holder, activestyle="none", exportselection=False), row=1)
        ttk.Button(right, text="File it here",
                   command=self.cmd_file_here).grid(row=2, column=0,
                                                    sticky="ew", pady=(6, 0))
        panes.add(right, weight=2)

        bar = ttk.Frame(container)
        bar.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        for index, (label, command) in enumerate([
            ("Keep without filing", self.cmd_keep),
            ("Turn into a note", self.cmd_to_note),
            ("Discard", self.cmd_discard),
            ("Delete", self.cmd_delete),
        ]):
            ttk.Button(bar, text=label, command=command).grid(
                row=0, column=index, padx=(0, 6))
        bar.columnconfigure(4, weight=1)
        ttk.Button(bar, text="Close", command=self.destroy).grid(
            row=0, column=5, sticky="e")

        self.refresh()
        center_window(self, 900, 560, min_width=620, min_height=400)
        self.entry.focus_set()
        self.bind("<Escape>", lambda _e: self.destroy())

    # -- data ------------------------------------------------------------
    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        ideas = sorted(self.project.data.ideas,
                       key=lambda i: (i.status != "new", i.created),
                       reverse=False)
        for idea in ideas:
            where = ""
            if idea.target_id:
                target = (self.project.data.entity(idea.target_id)
                          or self.project.data.scene(idea.target_id)
                          or self.project.data.chapter(idea.target_id))
                if target:
                    where = f"  -> {target.display}"
            self.tree.insert("", "end", iid=idea.id,
                             text=idea.summary + where,
                             values=(idea.status,))
        self.suggestions.delete(0, "end")
        self._suggestions = []

    def _selected(self) -> Optional[str]:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def _on_select(self) -> None:
        idea_id = self._selected()
        self.suggestions.delete(0, "end")
        self._suggestions = []
        if not idea_id:
            return
        self._suggestions = self.project.suggest_placements(idea_id)
        if not self._suggestions:
            self.suggestions.insert(
                "end", "Nothing obvious - file it by hand.")
            return
        for _target_id, label, score in self._suggestions:
            self.suggestions.insert("end", f"{int(score * 100):>3}%  {label}")

    # -- actions ---------------------------------------------------------
    def cmd_capture(self) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        idea = self.project.add_idea(text)
        self.entry.delete(0, "end")
        self.project.save()
        self.refresh()
        self.tree.selection_set(idea.id)
        self.on_change()

    def cmd_file_here(self) -> None:
        idea_id = self._selected()
        selection = self.suggestions.curselection()
        if not idea_id or not selection or not self._suggestions:
            messagebox.showinfo("Pick both",
                                "Choose an idea and a place for it.",
                                parent=self)
            return
        target_id = self._suggestions[selection[0]][0]
        self.project.set_idea_status(idea_id, "placed", target_id)
        self.project.save()
        self.refresh()
        self.on_change()

    def cmd_keep(self) -> None:
        idea_id = self._selected()
        if idea_id:
            self.project.set_idea_status(idea_id, "kept")
            self.project.save()
            self.refresh()

    def cmd_discard(self) -> None:
        idea_id = self._selected()
        if idea_id:
            self.project.set_idea_status(idea_id, "discarded")
            self.project.save()
            self.refresh()

    def cmd_delete(self) -> None:
        idea_id = self._selected()
        if not idea_id:
            return
        if messagebox.askyesno("Delete idea", "Remove it for good?",
                               parent=self):
            self.project.delete_idea(idea_id)
            self.project.save()
            self.refresh()
            self.on_change()

    def cmd_to_note(self) -> None:
        idea_id = self._selected()
        idea = self.project.data.idea(idea_id) if idea_id else None
        if not idea:
            return
        title = idea.summary[:60] or "Idea"
        note = self.project.add_note(title, kind="note", body=idea.text)
        if idea.target_id:
            self.project.set_note_links(note.id, [idea.target_id])
        self.project.set_idea_status(idea.id, "placed", idea.target_id)
        self.project.save()
        self.refresh()
        self.on_change()
        messagebox.showinfo("Note created",
                            f"'{title}' is now in Notes.", parent=self)


# ==========================================================================
# Branching drafts
# ==========================================================================


class DraftsDialog(Dialog):
    """
    Alternate versions of one scene.

    The live document is always the active draft, so nothing else in the tool
    has to know branches exist - compiling, word counts and backups all keep
    working on whichever version you are currently in.
    """

    def __init__(self, parent, project, scene_id: str) -> None:
        self.project = project
        self.scene_id = scene_id
        self.changed = False
        scene = project.data.scene(scene_id)
        super().__init__(parent, f"Drafts of {scene.display if scene else '?'}",
                         560, 420)

    def build(self, parent: ttk.Frame) -> None:
        ttk.Label(
            parent,
            text="Try a different version of this scene without copying the "
                 "project. Switching parks the version you are leaving and "
                 "brings the other one in - neither is ever lost.",
            wraplength=500, justify="left", style="Hint.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.listbox = scrolled(parent, lambda holder: tk.Listbox(
            holder, height=10, activestyle="none", exportselection=False),
            row=1)
        parent.rowconfigure(1, weight=1)
        self.listbox.bind("<Double-Button-1>", lambda _e: self.cmd_switch())

        row = ttk.Frame(parent)
        row.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        row.columnconfigure(0, weight=1)
        self.new_name = ttk.Entry(row)
        self.new_name.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.new_name.bind("<Return>", lambda _e: self.cmd_new())
        ttk.Button(row, text="New draft from this one",
                   command=self.cmd_new).grid(row=0, column=1)

        self._reload()

    def build_buttons(self, parent: ttk.Frame) -> None:
        ttk.Button(parent, text="Switch to selected",
                   command=self.cmd_switch).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(parent, text="Delete selected",
                   command=self.cmd_delete).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(parent, text="Close", command=self.on_cancel).grid(
            row=0, column=2)

    def _reload(self) -> None:
        self.listbox.delete(0, "end")
        self.rows = self.project.draft_summary(self.scene_id)
        for name, words, active in self.rows:
            mark = "* " if active else "  "
            self.listbox.insert("end", f"{mark}{name:<28s} {words:>7,} words")
        for index, (_n, _w, active) in enumerate(self.rows):
            if active:
                self.listbox.selection_set(index)

    def _pick(self) -> Optional[str]:
        selection = self.listbox.curselection()
        if not selection or not self.rows:
            messagebox.showinfo("Pick a draft", "Select one first.",
                                parent=self)
            return None
        return self.rows[selection[0]][0]

    def cmd_new(self) -> None:
        name = self.new_name.get().strip()
        if not name:
            messagebox.showinfo("Name it",
                                "Give the new draft a name first.", parent=self)
            return
        try:
            self.project.create_draft(self.scene_id, name)
        except Exception as exc:
            messagebox.showerror("Could not create it", str(exc), parent=self)
            return
        self.new_name.delete(0, "end")
        self.changed = True
        self.project.save()
        self._reload()

    def cmd_switch(self) -> None:
        name = self._pick()
        if not name:
            return
        try:
            self.project.switch_draft(self.scene_id, name)
        except Exception as exc:
            messagebox.showerror("Could not switch", str(exc), parent=self)
            return
        self.changed = True
        self.project.save()
        self._reload()

    def cmd_delete(self) -> None:
        name = self._pick()
        if not name:
            return
        if not messagebox.askyesno(
            "Delete draft",
            f"Delete the draft '{name}'? Its text goes with it.",
            parent=self,
        ):
            return
        try:
            self.project.delete_draft(self.scene_id, name)
        except Exception as exc:
            messagebox.showerror("Could not delete", str(exc), parent=self)
            return
        self.changed = True
        self.project.save()
        self._reload()

    def on_cancel(self) -> None:
        self.result = self.changed
        self.destroy()


# ==========================================================================
# Research linking
# ==========================================================================


class NoteLinksDialog(Dialog):
    """Attach a note to the scenes and people it is actually about."""

    def __init__(self, parent, project, note_id: str) -> None:
        self.project = project
        self.note_id = note_id
        note = project.data.note(note_id)
        super().__init__(parent,
                         f"Link '{note.title if note else '?'}' to...", 600, 520)

    def build(self, parent: ttk.Frame) -> None:
        ttk.Label(
            parent,
            text="Pick everything this note is research for. It will then show "
                 "up on those scenes and characters, instead of being lost in "
                 "a folder.",
            wraplength=540, justify="left", style="Hint.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.listbox = scrolled(parent, lambda holder: tk.Listbox(
            holder, height=18, selectmode="extended", activestyle="none",
            exportselection=False), row=1)
        parent.rowconfigure(1, weight=1)

        note = self.project.data.note(self.note_id)
        current = set(note.links or []) if note else set()

        self.targets: List[str] = []
        data = self.project.data
        for chapter in data.ordered_chapters():
            for scene in data.scenes_in(chapter.id):
                self.targets.append(scene.id)
                self.listbox.insert(
                    "end", f"Scene      {scene.display}  ({chapter.display})")
        for entity_type in ("character", "location", "item", "faction",
                            "thread"):
            for entity in data.entities_of(entity_type):
                self.targets.append(entity.id)
                label = ENTITY_LABELS.get(entity_type, entity_type)
                self.listbox.insert("end", f"{label:<10s} {entity.display}")

        for index, target_id in enumerate(self.targets):
            if target_id in current:
                self.listbox.selection_set(index)

    def collect(self) -> Optional[bool]:
        chosen = [self.targets[i] for i in self.listbox.curselection()]
        self.project.set_note_links(self.note_id, chosen)
        self.project.save()
        return True
