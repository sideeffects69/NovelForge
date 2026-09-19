"""
Corkboard and relationship web - two canvas views of the same project.

**Corkboard**: every scene as an index card, coloured by status, grouped by
chapter. Drag a card onto another to reorder; drag it onto a chapter heading to
move it there. Editing a synopsis here is the fastest way to outline, because
you see the shape of the whole book while you do it.

**Relationship web**: characters as nodes, drawn with an edge wherever two of
them share a scene, thickness by how often. Laid out deterministically so the
picture does not jump around between openings.
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Dict, List, Optional, Tuple

from ..config import theme
from ..model import SCENE_STATUSES, STATUS_COLOURS
from .dialogs import ReportWindow
from .widgets import AutoScrollbar, ScrolledText, center_window

CARD_W = 210
CARD_H = 148
GAP_X = 18
GAP_Y = 22
HEAD_H = 30


class Corkboard(tk.Toplevel):
    def __init__(self, parent, project,
                 on_change: Optional[Callable[[], None]] = None,
                 on_open_scene: Optional[Callable[[str], None]] = None) -> None:
        super().__init__(parent)
        self.project = project
        self.on_change = on_change or (lambda: None)
        self.on_open_scene = on_open_scene or (lambda _sid: None)
        self.title("Corkboard")

        self.selected_id = ""
        self._cards: Dict[str, Tuple[float, float]] = {}   # scene id -> x, y
        self._headings: Dict[str, Tuple[float, float]] = {}  # chapter id -> x, y
        self._drag_id = ""
        self._drag_ghost: Optional[int] = None
        self._columns = 4
        self._editing = ""

        self._build()
        self.redraw()
        center_window(self, 1280, 860, min_width=720, min_height=460)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ==================================================================
    # Layout
    # ==================================================================

    def _build(self) -> None:
        palette = theme()
        root = ttk.Frame(self, padding=6)
        root.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        root.columnconfigure(0, weight=1)

        bar = ttk.Frame(root)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        for index, (label, command) in enumerate([
            ("Edit card", self._edit_selected),
            ("Open scene", self._open_selected),
            ("Move left", lambda: self._nudge(-1)),
            ("Move right", lambda: self._nudge(1)),
            ("Cycle status", self._cycle_status),
            ("Relationships", self.cmd_relationships),
            ("Help", self.cmd_help),
        ]):
            ttk.Button(bar, text=label, command=command, width=13).grid(
                row=0, column=index, padx=2)

        self.info = ttk.Label(bar, text="", style="Status.TLabel", anchor="e")
        self.info.grid(row=0, column=9, sticky="e", padx=(10, 0))
        bar.columnconfigure(9, weight=1)

        wrap = ttk.Frame(root)
        wrap.grid(row=1, column=0, sticky="nsew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(wrap, background=palette["panel"],
                                highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scroll = AutoScrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.grid(row=0, column=1, sticky="ns")

        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", lambda _e: self._edit_selected())
        self.canvas.bind("<Button-3>", self._on_right)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Configure>", lambda _e: self._on_resize())

        self.status = ttk.Label(root, text="", style="Status.TLabel", anchor="w")
        self.status.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self._say("Drag a card onto another to reorder. Double-click to edit "
                  "its synopsis.")

    def _on_resize(self) -> None:
        width = max(400, self.canvas.winfo_width())
        columns = max(1, int((width - GAP_X) // (CARD_W + GAP_X)))
        if columns != self._columns:
            self._columns = columns
            self.redraw()

    def _on_wheel(self, event) -> None:
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _say(self, message: str) -> None:
        self.status.configure(text=message)

    # ==================================================================
    # Drawing
    # ==================================================================

    def redraw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        self._cards.clear()
        self._headings.clear()
        palette = theme()
        data = self.project.data

        y = GAP_Y
        total_scenes = 0
        for chapter in data.ordered_chapters():
            scenes = data.scenes_in(chapter.id)
            words = sum(s.word_count for s in scenes)

            canvas.create_text(
                GAP_X, y, anchor="nw",
                text=f"{chapter.title.upper()}",
                font=("Segoe UI", 10, "bold"), fill=palette["accent"],
                tags=(f"head:{chapter.id}",),
            )
            canvas.create_text(
                GAP_X + 6, y + 15, anchor="nw",
                text=f"{len(scenes)} scenes   {words:,} words"
                     + ("" if chapter.include_in_compile else "   (excluded)"),
                font=("Segoe UI", 8), fill=palette["dim"],
                tags=(f"head:{chapter.id}",),
            )
            self._headings[chapter.id] = (GAP_X, y)
            y += HEAD_H + 8

            if not scenes:
                canvas.create_text(
                    GAP_X + 8, y, anchor="nw", text="(no scenes yet)",
                    font=("Segoe UI", 9, "italic"), fill=palette["dim"],
                )
                y += 26
            for index, scene in enumerate(scenes):
                column = index % self._columns
                if column == 0 and index:
                    y += CARD_H + GAP_Y
                x = GAP_X + column * (CARD_W + GAP_X)
                self._draw_card(scene, x, y)
                self._cards[scene.id] = (x, y)
                total_scenes += 1
            if scenes:
                y += CARD_H + GAP_Y
            y += 10

        if not data.chapters:
            canvas.create_text(
                GAP_X, GAP_Y, anchor="nw",
                text="No chapters yet. Add one in the main window (Ctrl+Shift+C).",
                font=("Segoe UI", 10), fill=palette["dim"],
            )

        canvas.configure(scrollregion=(0, 0,
                                       GAP_X + self._columns * (CARD_W + GAP_X),
                                       y + GAP_Y))
        counts: Dict[str, int] = {}
        for scene in data.scenes:
            counts[scene.status] = counts.get(scene.status, 0) + 1
        self.info.configure(
            text=f"{total_scenes} cards   "
                 + "   ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        )

    def _draw_card(self, scene, x: float, y: float) -> None:
        canvas = self.canvas
        palette = theme()
        colour = STATUS_COLOURS.get(scene.status, "#9a9a9a")
        selected = scene.id == self.selected_id
        tag = f"card:{scene.id}"

        # A soft drop shadow gives the cards physical separation.
        canvas.create_rectangle(x + 3, y + 3, x + CARD_W + 3, y + CARD_H + 3,
                                fill=palette["gutter"], outline="", tags=(tag,))
        canvas.create_rectangle(
            x, y, x + CARD_W, y + CARD_H,
            fill=palette["bg"],
            outline=palette["accent"] if selected else palette["dim"],
            width=2 if selected else 1, tags=(tag,),
        )
        # Status stripe down the left edge.
        canvas.create_rectangle(x, y, x + 5, y + CARD_H, fill=colour,
                                outline="", tags=(tag,))

        title = scene.title or "(untitled)"
        canvas.create_text(
            x + 14, y + 10, anchor="nw", width=CARD_W - 26,
            text=title[:70], font=("Segoe UI", 9, "bold"),
            fill=palette["fg"], tags=(tag,),
        )

        pov = self.project.data.entity(scene.pov_id)
        meta = " · ".join(bit for bit in [
            pov.name if pov else "",
            scene.scene_type,
            f"{scene.word_count:,}w",
        ] if bit)
        canvas.create_text(
            x + 14, y + 30, anchor="nw", width=CARD_W - 26, text=meta,
            font=("Segoe UI", 7), fill=palette["dim"], tags=(tag,),
        )

        synopsis = scene.synopsis or "(no synopsis - double-click to add one)"
        canvas.create_text(
            x + 14, y + 48, anchor="nw", width=CARD_W - 26,
            text=synopsis[:260],
            font=("Segoe UI", 8, "" if scene.synopsis else "italic"),
            fill=palette["fg"] if scene.synopsis else palette["dim"],
            tags=(tag,),
        )

        canvas.create_text(
            x + 14, y + CARD_H - 16, anchor="nw", text=scene.status,
            font=("Segoe UI", 7, "bold"), fill=colour, tags=(tag,),
        )
        if not scene.include_in_compile:
            canvas.create_text(
                x + CARD_W - 14, y + CARD_H - 16, anchor="ne", text="excluded",
                font=("Segoe UI", 7), fill=palette["dim"], tags=(tag,),
            )
        # A quiet marker for a scene with no thread - easy to miss otherwise.
        if not scene.thread_ids:
            canvas.create_text(
                x + CARD_W - 14, y + 10, anchor="ne", text="⁙?",
                font=("Segoe UI", 8), fill=palette["dim"], tags=(tag,),
            )

    # ==================================================================
    # Interaction
    # ==================================================================

    def _hit(self, event) -> Tuple[str, str]:
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        for scene_id, (x, y) in self._cards.items():
            if x <= cx <= x + CARD_W and y <= cy <= y + CARD_H:
                return "card", scene_id
        for chapter_id, (x, y) in self._headings.items():
            if y - 6 <= cy <= y + HEAD_H:
                return "head", chapter_id
        return "", ""

    def _on_click(self, event) -> None:
        kind, ident = self._hit(event)
        if kind == "card":
            self.selected_id = ident
            self._drag_id = ident
            self.redraw()
            scene = self.project.data.scene(ident)
            if scene:
                self._say(f"{scene.title} - {scene.word_count:,} words, "
                          f"{scene.status}.")
        else:
            self.selected_id = ""
            self._drag_id = ""
            self.redraw()

    def _on_drag(self, event) -> None:
        if not self._drag_id:
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        if self._drag_ghost is not None:
            self.canvas.delete(self._drag_ghost)
        self._drag_ghost = self.canvas.create_rectangle(
            cx - CARD_W / 2, cy - 22, cx + CARD_W / 2, cy + 22,
            outline=theme()["accent"], width=2, dash=(5, 3),
        )

    def _on_release(self, event) -> None:
        if self._drag_ghost is not None:
            self.canvas.delete(self._drag_ghost)
            self._drag_ghost = None
        if not self._drag_id:
            return
        dragged = self._drag_id
        self._drag_id = ""
        kind, ident = self._hit(event)

        if kind == "card" and ident != dragged:
            self._reorder_onto(dragged, ident)
        elif kind == "head":
            scene = self.project.data.scene(dragged)
            if scene and scene.chapter_id != ident:
                self.project.reassign_scene(dragged, ident)
                self.project.save()
                self.on_change()
                self.redraw()
                chapter = self.project.data.chapter(ident)
                self._say(f"Moved to {chapter.title if chapter else 'chapter'}.")

    def _reorder_onto(self, dragged_id: str, target_id: str) -> None:
        data = self.project.data
        dragged = data.scene(dragged_id)
        target = data.scene(target_id)
        if not (dragged and target):
            return

        if dragged.chapter_id != target.chapter_id:
            self.project.reassign_scene(dragged_id, target.chapter_id)
            dragged = data.scene(dragged_id)
            if not dragged:
                return

        siblings = data.scenes_in(target.chapter_id)
        siblings = [s for s in siblings if s.id != dragged_id]
        position = next((i for i, s in enumerate(siblings)
                         if s.id == target_id), len(siblings))
        siblings.insert(position, dragged)
        for index, scene in enumerate(siblings):
            scene.order = index
        self.project.mark_dirty()
        self.project.save()
        self.on_change()
        self.redraw()
        self._say(f"'{dragged.title}' moved before '{target.title}'.")

    def _nudge(self, delta: int) -> None:
        if not self.selected_id:
            self._say("Select a card first.")
            return
        self.project.move_scene(self.selected_id, delta)
        self.project.save()
        self.on_change()
        self.redraw()

    def _cycle_status(self) -> None:
        if not self.selected_id:
            self._say("Select a card first.")
            return
        scene = self.project.data.scene(self.selected_id)
        if not scene:
            return
        try:
            index = SCENE_STATUSES.index(scene.status)
        except ValueError:
            index = -1
        scene.status = SCENE_STATUSES[(index + 1) % len(SCENE_STATUSES)]
        self.project.mark_dirty()
        self.project.save()
        self.on_change()
        self.redraw()
        self._say(f"{scene.title} is now {scene.status}.")

    def _on_right(self, event) -> None:
        kind, ident = self._hit(event)
        if kind != "card":
            return
        self.selected_id = ident
        self.redraw()
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Edit card...", command=self._edit_selected)
        menu.add_command(label="Open scene in the editor",
                         command=self._open_selected)
        menu.add_command(label="Cycle status", command=self._cycle_status)
        menu.add_separator()
        menu.add_command(label="Move left", command=lambda: self._nudge(-1))
        menu.add_command(label="Move right", command=lambda: self._nudge(1))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _open_selected(self) -> None:
        if not self.selected_id:
            self._say("Select a card first.")
            return
        self.on_open_scene(self.selected_id)
        self._say("Opened in the main window.")

    def _edit_selected(self) -> None:
        if not self.selected_id:
            self._say("Select a card first.")
            return
        scene = self.project.data.scene(self.selected_id)
        if not scene:
            return
        if _CardDialog(self, scene, self.project).show():
            self.project.mark_dirty()
            self.project.save()
            self.on_change()
            self.redraw()
            self._say(f"Updated '{scene.title}'.")

    # ==================================================================
    # Relationship web
    # ==================================================================

    def cmd_relationships(self) -> None:
        RelationshipWeb(self, self.project)

    def cmd_help(self) -> None:
        ReportWindow(self, "Corkboard help", """CORKBOARD
=========

Every scene is an index card. The stripe down the left edge and the word
at the bottom show its status:

    Outline      grey      planned, not written
    Draft        amber     words exist
    Revised      blue      been through a pass
    Needs Work   red       you know what is wrong with it
    Final        green     done

REORDERING
  Drag a card onto another card to drop it in front of that one. Drag a
  card onto a CHAPTER HEADING to move it into that chapter. Or select a
  card and use Move left / Move right.

EDITING
  Double-click a card to edit its synopsis, status, point of view and the
  scene/sequel fields. This is the fastest way to outline - you can see
  the shape of the whole book while you type.

  "Cycle status" steps a card through the five statuses, which is quick
  when you are triaging a chapter.

THE ⁙? MARKER
  A card showing "⁙?" in its top-right corner is not linked to any plot
  thread. That usually means one of two things: the scene is doing no
  structural work, or you have not finished linking things up. Both are
  worth knowing.

WHAT TO USE IT FOR
  Print nothing, plan everything. Fill in every synopsis before you draft
  a chapter, then check the run of cards reads as a sequence of events
  where each one changes the situation. Any card whose synopsis you
  cannot write in one sentence is a card that does not know what it is
  for yet.
""", width=720, height=660)

    def _close(self) -> None:
        self.on_change()
        self.destroy()


# ==========================================================================
# Card editor
# ==========================================================================


class _CardDialog(tk.Toplevel):
    def __init__(self, parent, scene, project) -> None:
        super().__init__(parent)
        self.withdraw()
        self.scene = scene
        self.project = project
        self.result = False
        self.title(f"Card - {scene.title}")
        self.transient(parent)

        from .widgets import Form, ScrollFrame

        container = ttk.Frame(self, padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        scroll = ScrollFrame(container)
        scroll.grid(row=0, column=0, sticky="nsew")
        self.form = Form(scroll.body)
        data = project.data

        self.form.heading("Card")
        self.form.entry("Title", scene, "title")
        self.form.multiline("Synopsis", scene, "synopsis", height=4)
        self.form.hint("One sentence. If you cannot write it, the scene does "
                       "not know what it is for yet.")
        self.form.combo("Status", scene, "status", SCENE_STATUSES)
        self.form.combo("Type", scene, "scene_type", ["scene", "sequel"])
        self.form.check("Include when compiling", scene, "include_in_compile")

        characters = [(e.id, e.name) for e in data.entities_of("character")]
        threads = [(e.id, e.name) for e in data.entities_of("thread")]
        if characters:
            self.form.picker("POV", scene, "pov_id", characters)
        if threads:
            self.form.multipicker("Plot threads", scene, "thread_ids", threads, 4)

        if scene.scene_type == "scene":
            self.form.heading("Goal / Conflict / Disaster")
            self.form.multiline("Goal", scene, "goal", height=2)
            self.form.multiline("Conflict", scene, "conflict", height=2)
            self.form.multiline("Disaster", scene, "disaster", height=2)
        else:
            self.form.heading("Reaction / Dilemma / Decision")
            self.form.multiline("Reaction", scene, "reaction", height=2)
            self.form.multiline("Dilemma", scene, "dilemma", height=2)
            self.form.multiline("Decision", scene, "decision", height=2)

        self.form.heading("Value shift")
        self.form.entry("Starts as", scene, "value_start")
        self.form.entry("Ends as", scene, "value_end")

        buttons = ttk.Frame(container)
        buttons.grid(row=1, column=0, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).grid(
            row=0, column=0, padx=(0, 6))
        ttk.Button(buttons, text="Save", command=self._save).grid(row=0, column=1)

        center_window(self, 520, 700, min_width=420, min_height=400)
        self.deiconify()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()

    def _save(self) -> None:
        self.form.commit()
        self.result = True
        self.destroy()

    def show(self) -> bool:
        self.wait_window()
        return self.result


# ==========================================================================
# Relationship web
# ==========================================================================


class RelationshipWeb(tk.Toplevel):
    """
    Characters as nodes; an edge wherever two share a scene.

    Layout is a plain circle ordered by how connected each character is, which
    is deterministic - the picture is the same every time you open it, so you
    can actually learn to read it.
    """

    def __init__(self, parent, project) -> None:
        super().__init__(parent)
        self.project = project
        self.title("Character Relationships")

        root = ttk.Frame(self, padding=8)
        root.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        root.columnconfigure(0, weight=1)

        bar = ttk.Frame(root)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(bar, text="An edge means the two characters appear in a scene "
                            "together. Thicker means more often.",
                  style="Hint.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(bar, text="Report", command=self._report).grid(
            row=0, column=1, padx=(10, 0))
        ttk.Button(bar, text="Close", command=self.destroy).grid(
            row=0, column=2, padx=(4, 0))
        bar.columnconfigure(0, weight=1)

        palette = theme()
        self.canvas = tk.Canvas(root, background=palette["bg"],
                                highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _e: self.draw())

        self.status = ttk.Label(root, text="", style="Status.TLabel")
        self.status.grid(row=2, column=0, sticky="ew", pady=(4, 0))

        center_window(self, 1000, 780, min_width=640, min_height=440)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(60, self.draw)

    def _pairs(self) -> Dict[Tuple[str, str], int]:
        counts: Dict[Tuple[str, str], int] = {}
        for scene in self.project.data.scenes:
            present = sorted(set(
                [cid for cid in scene.character_ids]
                + ([scene.pov_id] if scene.pov_id else [])
            ))
            for i, a in enumerate(present):
                for b in present[i + 1:]:
                    counts[(a, b)] = counts.get((a, b), 0) + 1
        return counts

    def draw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        palette = theme()
        data = self.project.data

        characters = data.entities_of("character")
        if not characters:
            canvas.create_text(20, 20, anchor="nw",
                               text="No characters yet.",
                               fill=palette["dim"], font=("Segoe UI", 11))
            return

        pairs = self._pairs()
        degree: Dict[str, int] = {c.id: 0 for c in characters}
        for (a, b), count in pairs.items():
            if a in degree:
                degree[a] += count
            if b in degree:
                degree[b] += count

        # Most-connected first, so the busiest characters sit next to each
        # other and the hub of the story is visible at a glance.
        ordered = sorted(characters, key=lambda c: (-degree.get(c.id, 0),
                                                    c.name.lower()))
        width = max(400, canvas.winfo_width())
        height = max(400, canvas.winfo_height())
        cx, cy = width / 2, height / 2
        radius = min(width, height) * 0.36
        positions: Dict[str, Tuple[float, float]] = {}
        count = len(ordered)
        for index, entity in enumerate(ordered):
            angle = -math.pi / 2 + 2 * math.pi * index / max(1, count)
            positions[entity.id] = (cx + math.cos(angle) * radius,
                                    cy + math.sin(angle) * radius)

        peak = max(pairs.values()) if pairs else 1
        for (a, b), n in sorted(pairs.items(), key=lambda kv: kv[1]):
            if a not in positions or b not in positions:
                continue
            ax, ay = positions[a]
            bx, by = positions[b]
            canvas.create_line(ax, ay, bx, by,
                               fill=palette["dim"],
                               width=max(1, min(7, round(n / peak * 7))))

        for entity in ordered:
            x, y = positions[entity.id]
            connections = degree.get(entity.id, 0)
            r = 8 + min(16, connections * 1.4)
            fill = palette["accent"] if entity.is_pov else palette["panel"]
            canvas.create_oval(x - r, y - r, x + r, y + r, fill=fill,
                               outline=palette["fg"], width=2)
            pov_scenes = sum(1 for s in data.scenes if s.pov_id == entity.id)
            label = entity.name + (f"  ({pov_scenes} POV)" if pov_scenes else "")
            anchor = "w" if x >= cx else "e"
            offset = r + 6 if x >= cx else -(r + 6)
            canvas.create_text(x + offset, y, anchor=anchor, text=label,
                               font=("Segoe UI", 9,
                                     "bold" if entity.is_pov else "normal"),
                               fill=palette["fg"])

        isolated = [e.name for e in characters if degree.get(e.id, 0) == 0]
        message = f"{len(characters)} characters, {len(pairs)} shared-scene links."
        if isolated:
            message += (f"  Never share a scene with anyone: "
                        f"{', '.join(isolated[:6])}"
                        + (f" and {len(isolated) - 6} more" if len(isolated) > 6
                           else ""))
        self.status.configure(text=message)

    def _report(self) -> None:
        data = self.project.data
        pairs = self._pairs()
        characters = {e.id: e for e in data.entities_of("character")}

        lines = ["CHARACTER RELATIONSHIPS", "=" * 30, "",
                 "Built from which characters you have linked to each scene,",
                 "so it is only as complete as that linking.", ""]
        if pairs:
            lines.append("SHARED SCENES")
            lines.append("")
            for (a, b), count in sorted(pairs.items(), key=lambda kv: -kv[1]):
                name_a = characters[a].name if a in characters else "?"
                name_b = characters[b].name if b in characters else "?"
                lines.append(f"  {count:>3}   {name_a}  +  {name_b}")
            lines.append("")

        lines.append("PER CHARACTER")
        lines.append("")
        for entity in data.entities_of("character"):
            appears = [s for s in data.ordered_scenes()
                       if entity.id in s.character_ids or s.pov_id == entity.id]
            pov = [s for s in data.scenes if s.pov_id == entity.id]
            partners = {
                (characters[b].name if b in characters else "?") if a == entity.id
                else (characters[a].name if a in characters else "?")
                for (a, b) in pairs if entity.id in (a, b)
            }
            lines.append(f"  {entity.name}  ({entity.role or 'no role set'})")
            lines.append(f"      scenes {len(appears)}   POV scenes {len(pov)}   "
                         f"words in POV {sum(s.word_count for s in pov):,}")
            if partners:
                lines.append(f"      shares scenes with: "
                             f"{', '.join(sorted(partners))}")
            else:
                lines.append("      shares scenes with nobody")
            if appears:
                first, last = appears[0], appears[-1]
                lines.append(f"      first appears '{first.title}', "
                             f"last '{last.title}'")
            lines.append("")

        lines += [
            "-" * 52, "",
            "Worth checking: a character who shares scenes with nobody is",
            "either a device or a missed opportunity. A protagonist who never",
            "shares a scene with the antagonist needs a very good reason.",
        ]
        ReportWindow(self, "Relationship report", "\n".join(lines),
                     width=760, height=700)
