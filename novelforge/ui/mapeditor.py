"""
The map editor window.

Draws the shared primitive display list from `mapmaker` onto a Tkinter Canvas,
so the editing view and the exported PNG/SVG are the same picture.

Performance approach, in three layers:

* `mapmaker.build_primitives` remembers the display list until the map itself
  changes, so a redraw caused by zooming, panning or selecting rebuilds nothing;
  it only turns the list into canvas items (tens of milliseconds on a busy map).
* Even that is too slow for a mouse-motion event, so an in-progress stroke is
  drawn as one temporary canvas item and the full redraw happens when it ends,
  and panning moves the existing items (`canvas.move`).
* Zooming scales the items on screen at once (`canvas.scale`) and does one real
  redraw when the wheel has been quiet for a moment, to put line widths and type
  right.

The parchment texture is rendered once per zoom level and cached.
"""

from __future__ import annotations

import copy
import math
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .. import mapgen, mapmaker as mm
from ..config import open_in_default_app, reveal_in_explorer, settings, theme
from . import mapicons, styling
from .dialogs import ChoiceDialog, Dialog, ReportWindow, TextPrompt
from .widgets import (Card, Dropdown, Form, ScrollFrame, center_window,
                      display_scale)

Point = Tuple[float, float]

TOOLS = [
    ("select", "Select", "Click to select. Drag to move. Delete to remove."),
    ("terrain", "Draw terrain", "Click to place points. Double-click or Enter "
                                "to finish. Esc cancels."),
    ("freehand", "Freehand", "Hold the left button and draw. Best for coastlines."),
    ("pin", "Place pin", "Click to drop a marker."),
    ("label", "Add label", "Click to place a text label."),
    ("erase", "Erase", "Click anything to delete it."),
    ("pan", "Pan", "Drag to move the view. Middle-drag works with any tool."),
]

TOOL_ICONS = {"select": "select", "terrain": "terrain", "freehand": "freehand",
              "pin": "pin", "label": "label", "erase": "erase", "pan": "pan"}

UNDO_LIMIT = 40


class MapEditor(tk.Toplevel):
    def __init__(self, parent, project, on_change: Optional[Callable[[], None]] = None
                 ) -> None:
        super().__init__(parent)
        self.project = project
        self.on_change = on_change or (lambda: None)
        self.title("Map Maker")

        self.folder = project.folder("maps")
        # Load the writer's own name lists, writing the starter file the first
        # time, so anything they have edited is in force before the first name
        # is generated.
        try:
            mm.load_name_styles(self.folder)
        except Exception:
            pass
        self.gm: Optional[mm.GameMap] = None
        self.map_file: Optional[Path] = None
        self.dirty = False

        # view transform
        self.zoom = 0.55
        self.offset_x = 0.0
        self.offset_y = 0.0
        # True while the view is "fit to window" rather than the writer's own
        # pan/zoom. The first map is loaded while the window is still being
        # built - before the canvas has its real size - so fitting once at load
        # fitted it to a placeholder and it opened as a thumbnail. Staying in
        # this mode means the fit is redone as the canvas takes its final size.
        self._auto_fit = True

        # interaction state
        self.tool = tk.StringVar(value="select")
        self.terrain_kind = tk.StringVar(value="land")
        self.pin_kind = tk.StringVar(value="city")
        self.draft_points: List[Point] = []
        self.selected_kind = ""       # shape | pin | label
        self.selected_id = ""
        self._drag_from: Optional[Point] = None
        self._drag_origin: Optional[Any] = None
        self._panning = False
        self._pan_from: Optional[Tuple[int, int]] = None
        self._undo: List[dict] = []
        self._redo: List[dict] = []
        self._bg_cache: Dict[Tuple[str, int, int, int], Any] = {}
        self._bg_image = None         # keep a reference or Tk garbage-collects it
        self._form: Optional[Form] = None
        self._redraw_job: Optional[str] = None

        self._build()
        self._load_first()

        center_window(self, 1440, 900, min_width=900, min_height=540)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ==================================================================
    # Layout
    # ==================================================================

    def _build(self) -> None:
        t = styling.current_tokens()
        self.tokens = t
        scale = display_scale(self)
        self.icons = mapicons.IconCache(self, max(16, int(round(18 * scale))))
        # (widget, icon, colour token): icons are baked in a colour, so a theme
        # change has to draw them again.
        self._icon_buttons: List[Tuple[Any, str, str]] = []
        self._rail_buttons: List[Tuple[Any, str]] = []
        self.configure(background=t["window"])
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # -- the bar: what you do to a map, in order of how often ------------
        strip = Card(self, radius=12, padding=8, fit="height", ground="window")
        strip.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 8))
        bar = strip.body
        self.bar = bar
        column = 0

        def gap() -> None:
            nonlocal column
            ttk.Separator(bar, orient="vertical").grid(
                row=0, column=column, sticky="ns", padx=8, pady=4)
            column += 1

        def put(widget, padx=(0, 4)) -> None:
            nonlocal column
            widget.grid(row=0, column=column, padx=padx)
            column += 1

        self.map_picker = ttk.Combobox(bar, state="readonly", width=22)
        self.map_picker.bind("<<ComboboxSelected>>", self._on_pick_map)
        put(self.map_picker, padx=(0, 6))
        styling.Tooltip(self.map_picker, "Switch to another map in this novel")
        gap()
        put(self._bar_button("sparkle", "Surprise Me", self.cmd_surprise,
                             "Build a random world in one click", "Accent.TButton",
                             "on_accent"))
        put(ttk.Button(bar, text="Generate...", command=self.cmd_generate))
        gap()
        put(self._bar_button("plus", "", self.cmd_new_map, "New map"))
        put(self._bar_button("save", "", self.cmd_save, "Save this map  (Ctrl+S)"))
        gap()
        put(self._bar_button("undo", "", self.cmd_undo, "Undo  (Ctrl+Z)"))
        put(self._bar_button("redo", "", self.cmd_redo, "Redo  (Ctrl+Y)"))
        bar.columnconfigure(column, weight=1)                  # spacer
        column += 1
        export = self._bar_button("export", "Export", None,
                                  "Save the map as a picture, a vector drawing "
                                  "or a Word document")
        self.export_menu = Dropdown(export, [
            ("PNG picture...", self.cmd_export_png),
            ("SVG vector drawing...", self.cmd_export_svg),
            ("Word document...", self.cmd_export_docx),
        ])
        put(export)
        more = self._bar_button("more", "", None, "More: rename, delete, names, help")
        self.more_menu = Dropdown(more, [
            ("Rename map...", self.cmd_rename),
            ("Delete map...", self.cmd_delete_map),
            ("-", None),
            ("Name generator...", self.cmd_name_generator),
            ("Edit name lists...", self.cmd_edit_names),
            ("-", None),
            ("Help", self.cmd_help),
        ])
        put(more, padx=0)

        # -- the body: tools, the map, and what is selected -------------------
        body = ttk.Frame(self, style="Chrome.TFrame")
        body.grid(row=1, column=0, sticky="nsew", padx=10)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        left = ttk.Frame(body, style="Chrome.TFrame")
        left.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        left.rowconfigure(0, weight=1)

        # The tool rail: one icon per tool, the chosen one tinted.
        rail = Card(left, radius=12, padding=6, fit="both", ground="window")
        rail.grid(row=0, column=0, sticky="n", padx=(0, 8))
        for row, (key, label, _hint) in enumerate(TOOLS):
            button = ttk.Radiobutton(
                rail.body, value=key, variable=self.tool, style="Rail.Toolbutton",
                command=self._on_tool_change, takefocus=False)
            button.grid(row=row, column=0, pady=1)
            styling.Tooltip(button, label)
            self._rail_buttons.append((button, TOOL_ICONS[key]))
        self._paint_rail()

        # The palette: what the chosen tool draws with.
        palette = Card(left, radius=12, padding=10, fit="width", ground="window")
        palette.grid(row=0, column=1, sticky="ns")
        self.palette_scroll = ScrollFrame(palette.body)
        self.palette_scroll.pack(fill="both", expand=True)
        panel = self.palette_scroll.body
        panel.columnconfigure(0, weight=1)
        self.palette_scroll.canvas.configure(width=196)

        self.tool_name = ttk.Label(panel, text="", style="Project.TLabel")
        self.tool_name.grid(row=0, column=0, sticky="w")
        self.tool_hint = ttk.Label(panel, text="", style="Hint.TLabel",
                                   wraplength=180, justify="left")
        self.tool_hint.grid(row=1, column=0, sticky="w", pady=(2, 10))

        ttk.Label(panel, text="TERRAIN", style="Section.TLabel").grid(
            row=2, column=0, sticky="w")
        self.terrain_box = tk.Listbox(panel, height=9, exportselection=False,
                                      activestyle="none")
        for key in mm.TERRAIN_ORDER:
            self.terrain_box.insert("end", "  " + mm.TERRAIN[key]["label"])
        self.terrain_box.selection_set(0)
        self.terrain_box.bind("<<ListboxSelect>>", self._on_terrain_pick)
        self.terrain_box.grid(row=3, column=0, sticky="ew", pady=(4, 0))

        ttk.Label(panel, text="PIN TYPE", style="Section.TLabel").grid(
            row=4, column=0, sticky="w", pady=(12, 0))
        self.pin_box = ttk.Combobox(panel, state="readonly", width=20,
                                    values=list(mm.PIN_KINDS.values()))
        self.pin_box.current(list(mm.PIN_KINDS).index("city"))
        self.pin_box.bind("<<ComboboxSelected>>", self._on_pin_pick)
        self.pin_box.grid(row=5, column=0, sticky="ew", pady=(4, 0))

        ttk.Label(panel, text="LAYERS", style="Section.TLabel").grid(
            row=6, column=0, sticky="w", pady=(12, 0))
        self.layer_box = tk.Listbox(panel, height=4, exportselection=False,
                                    activestyle="none")
        self.layer_box.grid(row=7, column=0, sticky="ew", pady=(4, 0))
        self.layer_box.bind("<Double-1>", lambda _e: self._toggle_layer())
        layer_bar = ttk.Frame(panel)
        layer_bar.grid(row=8, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(layer_bar, text="Add", width=6, style="Compact.TButton",
                   command=self._add_layer).grid(row=0, column=0)
        ttk.Button(layer_bar, text="Show/Hide", width=10, style="Compact.TButton",
                   command=self._toggle_layer).grid(row=0, column=1, padx=(4, 0))

        # The map itself, on a desk.
        stage = Card(body, radius=12, padding=3)
        stage.grid(row=0, column=1, sticky="nsew")
        stage.body.rowconfigure(0, weight=1)
        stage.body.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(stage.body, background=t["window"],
                                highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.canvas.bind("<Button-3>", self._on_right)
        self.canvas.bind("<Button-2>", self._on_middle_down)
        self.canvas.bind("<B2-Motion>", self._on_middle_drag)
        self.canvas.bind("<ButtonRelease-2>", self._on_middle_up)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self.bind("<Escape>", lambda _e: self._cancel_draft())
        self.bind("<Return>", lambda _e: self._finish_draft())
        self.bind("<Delete>", lambda _e: self._delete_selected())
        self.bind("<Control-z>", lambda _e: self.cmd_undo())
        self.bind("<Control-y>", lambda _e: self.cmd_redo())
        self.bind("<Control-s>", lambda _e: self.cmd_save())
        self.bind("<plus>", lambda _e: self._zoom_by(1.2))
        self.bind("<minus>", lambda _e: self._zoom_by(1 / 1.2))

        # What is selected.
        inspector = Card(body, radius=12, padding=12, fit="width", ground="window")
        inspector.grid(row=0, column=2, sticky="ns", padx=(8, 0))
        inspector.body.rowconfigure(1, weight=1)
        inspector.body.columnconfigure(0, weight=1)
        ttk.Label(inspector.body, text="PROPERTIES", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 4))
        self.props = ScrollFrame(inspector.body)
        self.props.grid(row=1, column=0, sticky="nsew")
        self.props.canvas.configure(width=232)

        # -- the status strip: a message, the pointer, and the zoom -----------
        foot = ttk.Frame(self, padding=(16, 4, 12, 6), style="Chrome.TFrame")
        foot.grid(row=2, column=0, sticky="ew")
        foot.columnconfigure(0, weight=1)
        self.status = ttk.Label(foot, text="", style="Chrome.Status.TLabel", anchor="w")
        self.status.grid(row=0, column=0, sticky="ew")
        self.coords_label = ttk.Label(foot, text="", style="Chrome.Status.TLabel")
        self.coords_label.grid(row=0, column=1, sticky="e", padx=(8, 8))
        for index, (icon, tip, command) in enumerate((
                ("zoom_out", "Zoom out  (-)", lambda: self._zoom_by(1 / 1.2)),
                ("zoom_in", "Zoom in  (+)", lambda: self._zoom_by(1.2)),
                ("fit", "Fit the whole map in the window", self.cmd_zoom_fit))):
            self._bar_button(icon, "", command, tip, "Tool.TButton", parent=foot
                             ).grid(row=0, column=2 + index, padx=(2, 0))

        self._on_tool_change()

    def _bar_button(self, icon: str, text: str, command, tip: str,
                    style: str = "Quiet.TButton", colour: str = "panel_fg",
                    parent=None) -> ttk.Button:
        """A button with an icon (and optionally words), a tooltip, and a place in the recolouring list."""
        image = self.icons.get(icon, self.tokens[colour])
        button = ttk.Button(parent or self.bar, text=text, style=style,
                            command=command, image=image or "",
                            compound=("left" if text else "image") if image else "none")
        if image is None and not text:
            button.configure(text=tip.split("  ")[0])         # no Pillow: words instead
        styling.Tooltip(button, tip)
        self._icon_buttons.append((button, icon, colour))
        return button

    def _paint_rail(self) -> None:
        """Icons for the tool rail, in the two colours a tool button can be."""
        t = self.tokens
        for button, icon in self._rail_buttons:
            plain = self.icons.get(icon, t["panel_fg"])
            chosen = self.icons.get(icon, t["accent"])
            if plain and chosen:
                button.configure(image=(plain, "selected", chosen))

    def restyle(self) -> None:
        """A theme change: the desk, the icons, and the map's frame around them."""
        t = styling.current_tokens()
        self.tokens = t
        try:
            self.configure(background=t["window"])
            self.canvas.configure(background=t["window"])
            for button, icon, colour in self._icon_buttons:
                image = self.icons.get(icon, t[colour])
                if image:
                    button.configure(image=image)
            self._paint_rail()
        except tk.TclError:
            return
        if self.gm:
            self.redraw()

    # ==================================================================
    # Map list
    # ==================================================================

    def _refresh_map_list(self, select: str = "") -> None:
        self.maps = mm.list_maps(self.folder)
        names = [name for name, _p in self.maps]
        self.map_picker.configure(values=names)
        target = select or (self.gm.name if self.gm else "")
        if target in names:
            self.map_picker.current(names.index(target))
        elif self.gm:
            # A map that is on screen but not yet saved is not in the list.
            # Showing the first saved map's name instead said the opposite of
            # what the writer was looking at.
            self.map_picker.set(f"{self.gm.name}  (unsaved)")
        elif names:
            self.map_picker.current(0)
        else:
            self.map_picker.set("")

    def _load_first(self) -> None:
        self._refresh_map_list()
        if self.maps:
            self._open_map(self.maps[0][1])
        else:
            self.gm = mm.starter_map("The Known World", "world", "parchment")
            self.map_file = None
            # Not dirty: this is a default the tool made up, not something the
            # writer drew. Marking it unsaved meant that merely opening the
            # Map Maker and closing it again asked whether to save - which is
            # the single most irritating thing a window can do.
            self.dirty = False
            self._after_load()
            self._say("New map created with a starter coastline. "
                      "Press Save to keep it, or draw your own.")

    def _on_pick_map(self, _event=None) -> None:
        index = self.map_picker.current()
        if 0 <= index < len(self.maps):
            if not self._confirm_discard():
                self._refresh_map_list()
                return
            self._open_map(self.maps[index][1])

    def _open_map(self, path: Path) -> None:
        loaded = mm.load_map(path)
        if not loaded:
            messagebox.showerror("Could not open",
                                 f"{Path(path).name} is not a readable map file.",
                                 parent=self)
            return
        self.gm = loaded
        self.map_file = Path(path)
        self.dirty = False
        self._after_load()

    def _after_load(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._bg_cache.clear()
        self.selected_kind = self.selected_id = ""
        self.draft_points.clear()
        self._refresh_layers()
        self._refresh_map_list()
        self.cmd_zoom_fit()
        self._build_props()

    # ==================================================================
    # Coordinate transforms
    # ==================================================================

    def to_screen(self, x: float, y: float) -> Point:
        return (x * self.zoom + self.offset_x, y * self.zoom + self.offset_y)

    def to_map(self, sx: float, sy: float) -> Point:
        z = self.zoom or 1.0
        return ((sx - self.offset_x) / z, (sy - self.offset_y) / z)

    def _event_point(self, event) -> Point:
        return self.to_map(self.canvas.canvasx(event.x),
                           self.canvas.canvasy(event.y))

    def _on_canvas_configure(self, _event=None) -> None:
        if self._auto_fit and self.gm:
            self._fit_view(settle=False)     # the canvas size is already known
        self._schedule_redraw()

    def _pan_by(self, dx: int, dy: int) -> None:
        """
        Slide the view by a screen-pixel offset without rebuilding the canvas.

        Panning changes nothing about the map, only what part of it is under
        the window, so every existing canvas item is still correct - it just
        needs to move. `canvas.move` repositions items in place, which is
        far cheaper than the delete-everything-and-redraw a full `redraw()`
        does, and a pan drag fires one motion event per pixel. Doing a full
        redraw per event is what made panning a busy map feel glitchy.
        """
        if dx == 0 and dy == 0:
            return
        self._auto_fit = False
        self.offset_x += dx
        self.offset_y += dy
        self.canvas.move("all", dx, dy)

    # ==================================================================
    # Drawing
    # ==================================================================

    def _schedule_redraw(self, delay: int = 16) -> None:
        if self._redraw_job:
            try:
                self.after_cancel(self._redraw_job)
            except (ValueError, tk.TclError):
                pass
        self._redraw_job = self.after(delay, self.redraw)

    def _background_image(self):
        """Parchment texture, rendered once per zoom step and cached."""
        if not self.gm:
            return None
        width = max(1, int(self.gm.width * self.zoom))
        height = max(1, int(self.gm.height * self.zoom))
        if width * height > 12_000_000:      # refuse absurd allocations
            return None
        key = (self.gm.style, self.gm.seed, width, height)
        if key in self._bg_cache:
            return self._bg_cache[key]
        try:
            from PIL import Image, ImageTk

            image = mm._parchment_background(self.gm, self.zoom)
            if image.size != (width, height):
                image = image.resize((width, height), Image.BILINEAR)
            photo = ImageTk.PhotoImage(image, master=self.canvas)
        except Exception:
            return None
        # Only a couple of zoom levels are worth holding on to.
        if len(self._bg_cache) > 3:
            self._bg_cache.clear()
        self._bg_cache[key] = photo
        return photo

    def redraw(self) -> None:
        self._redraw_job = None
        if not self.gm:
            return
        canvas = self.canvas
        canvas.delete("all")
        palette = self.gm.palette()

        x0, y0 = self.to_screen(0, 0)
        x1, y1 = self.to_screen(self.gm.width, self.gm.height)

        photo = self._background_image()
        if photo is not None:
            self._bg_image = photo
            canvas.create_image(x0, y0, image=photo, anchor="nw")
        else:
            canvas.create_rectangle(x0, y0, x1, y1, fill=palette["paper"],
                                    outline=palette["ink_light"])

        for prim in mm.build_primitives(self.gm):
            self._draw_primitive(prim)
        self._draw_desk(x0, y0, x1, y1)

        if self.gm.is_empty():
            canvas.create_text(
                (x0 + x1) / 2, (y0 + y1) / 2, justify="center",
                fill=self.tokens["text_dim"], font=(styling.UI_FONT, 12),
                text="An empty map.\n\nPress Surprise Me for a whole world, or pick\n"
                     "a tool on the left and start drawing.")

        self._draw_draft()
        self._draw_selection()
        self._update_status()

    def _draw_desk(self, x0: float, y0: float, x1: float, y1: float) -> None:
        """
        Everything beyond the sheet, and the sheet's shadow.

        A Tk canvas does not clip, so a wide stroke near the map's edge (the
        pale shallows around a coast, say) spilled out onto the desk. The bands
        below paint the desk back over whatever strayed past the sheet, and the
        shadow is drawn on top of them so it still lies under the sheet's edge.
        """
        canvas = self.canvas
        desk = self.tokens["window"]
        far = 6000                                    # more than any canvas is wide
        # Float coordinates round, and a stray row of pixels sat just outside
        # the mask. The sheet's own border is inset 20px or more, so one pixel
        # off its edge costs nothing and closes the gap.
        x0, y0, x1, y1 = x0 + 1, y0 + 1, x1 - 1, y1 - 1

        def band(a: float, b: float, c: float, d: float, colour: str) -> None:
            if c > a and d > b:
                canvas.create_rectangle(a, b, c, d, fill=colour, outline="")

        band(-far, -far, far, y0, desk)               # above, below, left, right
        band(-far, y1, far, far, desk)
        band(-far, y0, x0, y1, desk)
        band(x1, y0, far, y1, desk)
        for grow, dark in ((11, 0.05), (8, 0.08), (5, 0.12), (2, 0.18)):
            colour = styling.mix(desk, "#000000", dark)
            left, top = x0 - grow + 2, y0 - grow + 5
            right, bottom = x1 + grow + 2, y1 + grow + 5
            band(left, top, right, y0, colour)        # the shadow, as a frame
            band(left, y1, right, bottom, colour)
            band(left, y0, x0, y1, colour)
            band(x1, y0, right, y1, colour)

    def _draw_primitive(self, prim: tuple) -> None:
        canvas = self.canvas
        head = prim[0]
        z = self.zoom
        try:
            if head == "polygon":
                _k, points, fill, outline, width, dash = prim
                if len(points) < 3:
                    return
                flat = [c for p in points for c in self.to_screen(p[0], p[1])]
                canvas.create_polygon(
                    flat, fill=fill or "", outline=outline or "",
                    width=max(1, width * z),
                    dash=(6, 4) if dash else None,
                )
            elif head == "line":
                _k, points, colour, width, dash = prim
                if len(points) < 2 or not colour:
                    return
                flat = [c for p in points for c in self.to_screen(p[0], p[1])]
                canvas.create_line(
                    flat, fill=colour, width=max(1, width * z),
                    capstyle="round", joinstyle="round", smooth=False,
                    dash=(6, 4) if dash else None,
                )
            elif head == "ellipse":
                _k, ax, ay, bx, by, fill, outline, width = prim
                sx0, sy0 = self.to_screen(ax, ay)
                sx1, sy1 = self.to_screen(bx, by)
                if abs(sx1 - sx0) < 1 or abs(sy1 - sy0) < 1:
                    return
                canvas.create_oval(sx0, sy0, sx1, sy1, fill=fill or "",
                                   outline=outline or "",
                                   width=max(1, width * z))
            elif head == "text":
                x, y, text, size, colour, anchor, italic, bold, tracking, halo =                     mm.text_parts(prim)
                sx, sy = self.to_screen(x, y)
                pixels = max(6, int(size * z))
                if pixels < 7:
                    return                    # unreadable; skip for speed
                style = []
                if bold:
                    style.append("bold")
                if italic:
                    style.append("italic")
                shown = text
                if tracking and abs(tracking) > 0.4:
                    shown = " ".join(text)    # approximate letter spacing
                font = ("Georgia", pixels, " ".join(style) if style else "normal")
                where = {"center": "center", "w": "w", "e": "e",
                         "n": "n", "s": "s"}.get(anchor, "center")
                if halo and pixels >= 9:
                    # Tk cannot outline text, so stamp the halo colour at the
                    # four diagonals first and lay the letters over it.
                    grow = max(1, round(pixels * 0.09))
                    for ox, oy in ((-grow, -grow), (grow, -grow),
                                   (-grow, grow), (grow, grow)):
                        canvas.create_text(sx + ox, sy + oy, text=shown,
                                           fill=halo, font=font, anchor=where)
                canvas.create_text(sx, sy, text=shown, fill=colour, font=font,
                                   anchor=where)
        except tk.TclError:
            return

    def _draw_draft(self) -> None:
        if len(self.draft_points) < 1:
            return
        palette = self.gm.palette() if self.gm else mm.STYLES["parchment"]
        flat = [c for p in self.draft_points for c in self.to_screen(p[0], p[1])]
        if len(self.draft_points) >= 2:
            self.canvas.create_line(flat, fill="#c0392b", width=2,
                                    dash=(5, 3), tags="draft")
        for px, py in self.draft_points:
            sx, sy = self.to_screen(px, py)
            self.canvas.create_oval(sx - 3, sy - 3, sx + 3, sy + 3,
                                    fill="#c0392b", outline="", tags="draft")

    def _draw_selection(self) -> None:
        if not (self.gm and self.selected_id):
            return
        marker = "#1f6fb2"
        if self.selected_kind == "shape":
            shape = self.gm.shape(self.selected_id)
            if not shape or not shape.points:
                return
            bx0, by0, bx1, by1 = shape.bounds()
            sx0, sy0 = self.to_screen(bx0 - 4, by0 - 4)
            sx1, sy1 = self.to_screen(bx1 + 4, by1 + 4)
            self.canvas.create_rectangle(sx0, sy0, sx1, sy1, outline=marker,
                                         width=1, dash=(4, 3))
            for px, py in shape.points:
                sx, sy = self.to_screen(px, py)
                self.canvas.create_rectangle(sx - 2.5, sy - 2.5, sx + 2.5,
                                             sy + 2.5, fill=marker, outline="")
        else:
            target = (self.gm.pin(self.selected_id)
                      if self.selected_kind == "pin"
                      else self.gm.label(self.selected_id))
            if not target:
                return
            sx, sy = self.to_screen(target.x, target.y)
            r = 14
            self.canvas.create_oval(sx - r, sy - r, sx + r, sy + r,
                                    outline=marker, width=2, dash=(4, 3))

    # ==================================================================
    # Undo
    # ==================================================================

    def _push_undo(self) -> None:
        if not self.gm:
            return
        self._undo.append(copy.deepcopy(self.gm.to_json()))
        if len(self._undo) > UNDO_LIMIT:
            self._undo.pop(0)
        self._redo.clear()
        self.dirty = True

    def cmd_undo(self) -> None:
        if not self._undo or not self.gm:
            self._say("Nothing to undo.")
            return
        self._redo.append(copy.deepcopy(self.gm.to_json()))
        self.gm = mm.GameMap.from_json(self._undo.pop())
        self.selected_kind = self.selected_id = ""
        self.dirty = True
        self._refresh_layers()
        self._build_props()
        self.redraw()
        self._say("Undone.")

    def cmd_redo(self) -> None:
        if not self._redo or not self.gm:
            self._say("Nothing to redo.")
            return
        self._undo.append(copy.deepcopy(self.gm.to_json()))
        self.gm = mm.GameMap.from_json(self._redo.pop())
        self.selected_kind = self.selected_id = ""
        self.dirty = True
        self._refresh_layers()
        self._build_props()
        self.redraw()
        self._say("Redone.")

    # ==================================================================
    # Tool handling
    # ==================================================================

    def _on_tool_change(self) -> None:
        tool = self.tool.get()
        label, hint = next(((l, h) for k, l, h in TOOLS if k == tool), ("", ""))
        self.tool_name.configure(text=label)
        self.tool_hint.configure(text=hint)
        if tool not in ("terrain", "freehand"):
            self._cancel_draft()
        cursor = {"pan": "fleur", "erase": "X_cursor", "pin": "crosshair",
                  "label": "xterm", "terrain": "crosshair",
                  "freehand": "pencil"}.get(tool, "arrow")
        try:
            self.canvas.configure(cursor=cursor)
        except tk.TclError:
            self.canvas.configure(cursor="")

    def _on_terrain_pick(self, _event=None) -> None:
        selection = self.terrain_box.curselection()
        if selection:
            self.terrain_kind.set(mm.TERRAIN_ORDER[selection[0]])
            if self.tool.get() not in ("terrain", "freehand"):
                self.tool.set("terrain")
                self._on_tool_change()

    def _on_pin_pick(self, _event=None) -> None:
        index = self.pin_box.current()
        if 0 <= index < len(mm.PIN_KINDS):
            self.pin_kind.set(list(mm.PIN_KINDS)[index])
            self.tool.set("pin")
            self._on_tool_change()

    def _on_click(self, event) -> None:
        if not self.gm:
            return
        point = self._event_point(event)
        tool = self.tool.get()

        if tool == "pan":
            self._pan_from = (event.x, event.y)
            return
        if tool == "terrain":
            self.draft_points.append(point)
            self.redraw()
            return
        if tool == "freehand":
            self.draft_points = [point]
            return
        if tool == "pin":
            self._place_pin(point)
            return
        if tool == "label":
            self._place_label(point)
            return
        if tool == "erase":
            self._erase_at(point)
            return

        # select
        kind, ident = self._hit_test(point)
        self.selected_kind, self.selected_id = kind, ident
        self._drag_from = point
        self._drag_origin = self._selection_origin()
        self._build_props()
        self.redraw()

    def _on_drag(self, event) -> None:
        if not self.gm:
            return
        tool = self.tool.get()
        if tool == "pan" and self._pan_from:
            self._pan_by(event.x - self._pan_from[0], event.y - self._pan_from[1])
            self._pan_from = (event.x, event.y)
            return
        if tool == "freehand":
            point = self._event_point(event)
            if not self.draft_points:
                self.draft_points = [point]
                return
            last = self.draft_points[-1]
            # Thin the stroke: one point per ~3 screen pixels keeps the
            # geometry manageable without visibly cornering.
            if math.hypot(point[0] - last[0], point[1] - last[1]) * self.zoom < 3:
                return
            self.draft_points.append(point)
            sx0, sy0 = self.to_screen(*last)
            sx1, sy1 = self.to_screen(*point)
            self.canvas.create_line(sx0, sy0, sx1, sy1, fill="#c0392b",
                                    width=2, tags="draft")
            return
        if tool == "select" and self.selected_id and self._drag_from:
            point = self._event_point(event)
            dx = point[0] - self._drag_from[0]
            dy = point[1] - self._drag_from[1]
            # The same 3-pixel dead-zone the freehand tool uses. Below it this
            # is a click, not a drag, and treating it as a drag marked the map
            # edited every time the writer selected something to look at it.
            if math.hypot(dx, dy) * self.zoom < 3:
                return
            self._move_selection(dx, dy)
            self._drag_from = point
            # Debounced, not immediate: a drag fires far more motion events
            # than a screen can paint, and each one rebuilds the whole
            # primitive list plus the label-collision pass. Coalescing to
            # one redraw per frame is what keeps dragging a pin smooth on a
            # map with a lot of names on it.
            self._schedule_redraw()

    def _on_release(self, event) -> None:
        tool = self.tool.get()
        if tool == "freehand" and len(self.draft_points) >= 2:
            self._commit_shape(self.draft_points, freehand=True)
            self.draft_points = []
            self.redraw()
        elif tool == "select" and self._drag_origin is not None:
            if self._selection_origin() != self._drag_origin:
                # Record the move as one undo step, not one per motion event.
                moved = self._drag_origin
                self._drag_origin = None
                self._undo.append(self._json_with_selection_at(moved))
                if len(self._undo) > UNDO_LIMIT:
                    self._undo.pop(0)
                self._redo.clear()
                self.dirty = True
            self._drag_origin = None
        self._pan_from = None
        self._drag_from = None

    def _on_double(self, _event=None) -> None:
        if self.tool.get() == "terrain":
            self._finish_draft()
        elif self.tool.get() == "select" and self.selected_kind == "pin":
            self._open_linked_location()

    def _on_right(self, event) -> None:
        if self.tool.get() == "terrain" and self.draft_points:
            self._finish_draft()
            return
        point = self._event_point(event)
        kind, ident = self._hit_test(point)
        if not ident:
            return
        self.selected_kind, self.selected_id = kind, ident
        self._build_props()
        self.redraw()

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Delete", command=self._delete_selected)
        if kind == "shape":
            menu.add_command(label="Name this area...", command=self._name_shape)
            menu.add_command(label="Bring to front", command=self._raise_shape)
        if kind == "pin":
            menu.add_command(label="Rename...", command=self._rename_pin)
            menu.add_command(label="Link to a Location sheet...",
                             command=self._link_pin)
            menu.add_command(label="Open linked Location",
                             command=self._open_linked_location)
        if kind == "label":
            menu.add_command(label="Edit text...", command=self._edit_label)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _on_middle_down(self, event) -> None:
        self._panning = True
        self._pan_from = (event.x, event.y)

    def _on_middle_drag(self, event) -> None:
        if not (self._panning and self._pan_from):
            return
        self._pan_by(event.x - self._pan_from[0], event.y - self._pan_from[1])
        self._pan_from = (event.x, event.y)

    def _on_middle_up(self, _event=None) -> None:
        self._panning = False
        self._pan_from = None

    def _on_motion(self, event) -> None:
        if not self.gm:
            return
        mx, my = self._event_point(event)
        self.coords_label.configure(
            text=f"{int(mx)}, {int(my)}   zoom {self.zoom * 100:.0f}%"
        )

    def _on_wheel(self, event) -> None:
        factor = 1.15 if event.delta > 0 else 1 / 1.15
        self._zoom_by(factor, event.x, event.y)

    def _zoom_by(self, factor: float, anchor_x: Optional[float] = None,
                 anchor_y: Optional[float] = None) -> None:
        old = self.zoom
        self.zoom = max(0.08, min(4.0, self.zoom * factor))
        if self.zoom == old:
            return
        self._auto_fit = False
        if anchor_x is None:
            anchor_x = self.canvas.winfo_width() / 2
        if anchor_y is None:
            anchor_y = self.canvas.winfo_height() / 2
        # Keep the point under the cursor fixed while zooming.
        self.offset_x = anchor_x - (anchor_x - self.offset_x) * (self.zoom / old)
        self.offset_y = anchor_y - (anchor_y - self.offset_y) * (self.zoom / old)
        # Show the zoom at once by scaling what is already on the canvas (about
        # the same point the offsets above keep fixed), and let one real redraw
        # follow when the wheel goes quiet to put line widths and type right.
        # A fast wheel or a trackpad fires many of these a second; rebuilding
        # the map for each is what made zooming feel like wading.
        ratio = self.zoom / old
        self.canvas.scale("all", anchor_x, anchor_y, ratio, ratio)
        self._schedule_redraw(140)

    def cmd_zoom_fit(self) -> None:
        if not self.gm:
            return
        self._fit_view()
        self.redraw()

    def _fit_view(self, settle: bool = True) -> None:
        """Set zoom and offset so the whole map fills the canvas. No drawing."""
        self._auto_fit = True
        if settle:
            self.canvas.update_idletasks()
        width = max(200, self.canvas.winfo_width())
        height = max(200, self.canvas.winfo_height())
        self.zoom = max(0.08, min(2.0,
                                  min(width / (self.gm.width + 60),
                                      height / (self.gm.height + 60))))
        self.offset_x = (width - self.gm.width * self.zoom) / 2
        self.offset_y = (height - self.gm.height * self.zoom) / 2

    # ==================================================================
    # Editing operations
    # ==================================================================

    def _current_layer(self) -> str:
        selection = self.layer_box.curselection()
        if selection and self.gm:
            names = self.gm.layer_names()
            if selection[0] < len(names):
                return names[selection[0]]
        return self.gm.layers[0].name if self.gm and self.gm.layers else "Base"

    def _commit_shape(self, points: Sequence[Point], freehand: bool = False) -> None:
        if not self.gm or len(points) < 2:
            return
        kind = self.terrain_kind.get()
        spec = mm.TERRAIN.get(kind, mm.TERRAIN["land"])
        closed = bool(spec["closed"])
        if closed and len(points) < 3:
            self._say("A filled area needs at least three points.")
            return
        self._push_undo()
        shape = mm.Shape(kind=kind, points=list(points), closed=closed,
                         layer=self._current_layer())
        self.gm.shapes.append(shape)
        self.selected_kind, self.selected_id = "shape", shape.id
        self._build_props()
        self._say(f"Added {spec['label'].lower()} "
                  f"({len(points)} points). Ctrl+Z undoes it.")

    def _finish_draft(self) -> None:
        if self.draft_points and len(self.draft_points) >= 2:
            self._commit_shape(self.draft_points)
        self.draft_points = []
        self.redraw()

    def _cancel_draft(self) -> None:
        if self.draft_points:
            self.draft_points = []
            self.redraw()
            self._say("Cancelled.")

    def _place_pin(self, point: Point) -> None:
        if not self.gm:
            return
        label = TextPrompt(self, "New pin", "Name of this place (optional)",
                           "", "Leave blank for an unlabelled marker.").show()
        self._push_undo()
        pin = mm.Pin(x=point[0], y=point[1], kind=self.pin_kind.get(),
                     label=label or "", layer=self._current_layer(),
                     size=8.0 if self.pin_kind.get() == "capital" else 7.0)
        self.gm.pins.append(pin)
        self.selected_kind, self.selected_id = "pin", pin.id
        self._build_props()
        self.redraw()
        self._say(f"Placed {mm.PIN_KINDS.get(pin.kind, pin.kind).lower()}.")

    def _place_label(self, point: Point) -> None:
        if not self.gm:
            return
        text = TextPrompt(self, "New label", "Label text", "",
                          "Region and ocean names look best in wide italics.").show()
        if not text:
            return
        self._push_undo()
        label = mm.MapLabel(x=point[0], y=point[1], text=text, size=18,
                            italic=True, tracking=3.0,
                            layer=self._current_layer())
        self.gm.labels.append(label)
        self.selected_kind, self.selected_id = "label", label.id
        self._build_props()
        self.redraw()

    def _hit_test(self, point: Point) -> Tuple[str, str]:
        """Pins, then labels, then shapes - smallest targets win."""
        if not self.gm:
            return "", ""
        visible = self.gm.visible_layers()
        tolerance = max(8.0, 12.0 / max(0.2, self.zoom))

        for pin in reversed(self.gm.pins):
            if pin.layer not in visible:
                continue
            if math.hypot(point[0] - pin.x, point[1] - pin.y) <= \
                    max(tolerance, pin.size * 2.0):
                return "pin", pin.id

        for label in reversed(self.gm.labels):
            if label.layer not in visible:
                continue
            half_w = max(20.0, len(label.text) * label.size * 0.32)
            if abs(point[0] - label.x) <= half_w and \
                    abs(point[1] - label.y) <= label.size:
                return "label", label.id

        for shape in reversed(self.gm.shapes):
            if shape.layer not in visible:
                continue
            if shape.closed and len(shape.points) >= 3:
                if mm.point_in_polygon(point, shape.points):
                    return "shape", shape.id
            if mm.distance_to_path(point, shape.points) <= tolerance:
                return "shape", shape.id
        return "", ""

    def _selection_origin(self):
        if not (self.gm and self.selected_id):
            return None
        if self.selected_kind == "shape":
            shape = self.gm.shape(self.selected_id)
            return list(shape.points) if shape else None
        target = (self.gm.pin(self.selected_id) if self.selected_kind == "pin"
                  else self.gm.label(self.selected_id))
        return (target.x, target.y) if target else None

    def _json_with_selection_at(self, origin) -> dict:
        """The map as it was before a drag, for a single clean undo step."""
        snapshot = copy.deepcopy(self.gm.to_json())
        if self.selected_kind == "shape" and isinstance(origin, list):
            for entry in snapshot.get("shapes", []):
                if entry.get("id") == self.selected_id:
                    entry["points"] = [[p[0], p[1]] for p in origin]
        elif isinstance(origin, tuple):
            bucket = "pins" if self.selected_kind == "pin" else "labels"
            for entry in snapshot.get(bucket, []):
                if entry.get("id") == self.selected_id:
                    entry["x"], entry["y"] = origin
        return snapshot

    def _move_selection(self, dx: float, dy: float) -> None:
        if not (self.gm and self.selected_id):
            return
        # A click is never perfectly still. Without this, the hand-tremor of
        # an ordinary click on a pin counted as an edit, and since unsaved
        # work is now saved rather than queried, merely looking at a map
        # would write it back to disk.
        if dx == 0 and dy == 0:
            return
        if self.selected_kind == "shape":
            shape = self.gm.shape(self.selected_id)
            if shape:
                shape.points = [(p[0] + dx, p[1] + dy) for p in shape.points]
        elif self.selected_kind == "pin":
            pin = self.gm.pin(self.selected_id)
            if pin:
                pin.x += dx
                pin.y += dy
        elif self.selected_kind == "label":
            label = self.gm.label(self.selected_id)
            if label:
                label.x += dx
                label.y += dy
        self.dirty = True

    def _erase_at(self, point: Point) -> None:
        kind, ident = self._hit_test(point)
        if not ident:
            return
        self.selected_kind, self.selected_id = kind, ident
        self._delete_selected()

    def _delete_selected(self) -> None:
        if not (self.gm and self.selected_id):
            return
        self._push_undo()
        if self.selected_kind == "shape":
            self.gm.shapes = [s for s in self.gm.shapes if s.id != self.selected_id]
        elif self.selected_kind == "pin":
            self.gm.pins = [p for p in self.gm.pins if p.id != self.selected_id]
        elif self.selected_kind == "label":
            self.gm.labels = [l for l in self.gm.labels if l.id != self.selected_id]
        self.selected_kind = self.selected_id = ""
        self._build_props()
        self.redraw()
        self._say("Deleted. Ctrl+Z restores it.")

    def _raise_shape(self) -> None:
        if not (self.gm and self.selected_kind == "shape"):
            return
        shape = self.gm.shape(self.selected_id)
        if not shape:
            return
        self._push_undo()
        self.gm.shapes = [s for s in self.gm.shapes if s.id != shape.id] + [shape]
        self.redraw()

    def _name_shape(self) -> None:
        if not (self.gm and self.selected_kind == "shape"):
            return
        shape = self.gm.shape(self.selected_id)
        if not shape:
            return
        name = TextPrompt(self, "Name area", "Name for this area",
                          shape.label).show()
        if name is None:
            return
        self._push_undo()
        shape.label = name
        self.redraw()

    def _rename_pin(self) -> None:
        if not (self.gm and self.selected_kind == "pin"):
            return
        pin = self.gm.pin(self.selected_id)
        if not pin:
            return
        name = TextPrompt(self, "Rename pin", "Place name", pin.label).show()
        if name is None:
            return
        self._push_undo()
        pin.label = name
        self._build_props()
        self.redraw()

    def _edit_label(self) -> None:
        if not (self.gm and self.selected_kind == "label"):
            return
        label = self.gm.label(self.selected_id)
        if not label:
            return
        text = TextPrompt(self, "Edit label", "Label text", label.text).show()
        if text is None:
            return
        self._push_undo()
        label.text = text
        self._build_props()
        self.redraw()

    def _link_pin(self) -> None:
        if not (self.gm and self.selected_kind == "pin"):
            return
        pin = self.gm.pin(self.selected_id)
        if not pin:
            return
        locations = self.project.data.entities_of("location")
        if not locations:
            if messagebox.askyesno(
                "No locations yet",
                "This project has no Location sheets to link to.\n\n"
                f"Create one called '{pin.label or 'this place'}' now?",
                parent=self,
            ) and pin.label:
                entity = self.project.add_entity("location", pin.label)
                self._push_undo()
                pin.entity_id = entity.id
                self.project.save()
                self.on_change()
                self._build_props()
                self._say(f"Created and linked a Location sheet for {pin.label}.")
            return
        options = [(e.id, e.name) for e in locations]
        chosen = ChoiceDialog(self, "Link pin",
                              f"Link '{pin.label or 'this pin'}' to which "
                              f"Location sheet?", options).show()
        if not chosen:
            return
        self._push_undo()
        pin.entity_id = chosen
        self._build_props()
        self._say("Linked. Double-click the pin to open its sheet in Word.")

    def _open_linked_location(self) -> None:
        if not (self.gm and self.selected_kind == "pin"):
            return
        pin = self.gm.pin(self.selected_id)
        if not pin:
            return
        if not pin.entity_id:
            self._link_pin()
            return
        entity = self.project.data.entity(pin.entity_id)
        if not entity or not entity.docx:
            self._say("That Location sheet no longer exists.")
            return
        path = self.project.abs(entity.docx)
        if path.exists():
            open_in_default_app(path)
            self._say(f"Opened {entity.name} in Word.")
        else:
            self._say(f"{path.name} is missing from disk.")

    # ==================================================================
    # Layers
    # ==================================================================

    def _refresh_layers(self) -> None:
        self.layer_box.delete(0, "end")
        if not self.gm:
            return
        for layer in self.gm.layers:
            mark = "" if layer.visible else "  (hidden)"
            self.layer_box.insert("end", f"{layer.name}{mark}")
        self.layer_box.selection_set(0)

    def _add_layer(self) -> None:
        if not self.gm:
            return
        name = TextPrompt(self, "New layer", "Layer name",
                          f"Layer {len(self.gm.layers) + 1}").show()
        if not name:
            return
        if self.gm.layer(name):
            messagebox.showinfo("Already exists",
                                f"There is already a layer called '{name}'.",
                                parent=self)
            return
        self._push_undo()
        self.gm.layers.append(mm.Layer(name=name))
        self._refresh_layers()
        self.layer_box.selection_clear(0, "end")
        self.layer_box.selection_set(len(self.gm.layers) - 1)

    def _toggle_layer(self) -> None:
        selection = self.layer_box.curselection()
        if not (self.gm and selection):
            return
        index = selection[0]
        if index >= len(self.gm.layers):
            return
        self._push_undo()
        self.gm.layers[index].visible = not self.gm.layers[index].visible
        self._refresh_layers()
        self.layer_box.selection_clear(0, "end")
        self.layer_box.selection_set(index)
        self.redraw()

    # ==================================================================
    # Properties pane
    # ==================================================================

    def _build_props(self) -> None:
        self.props.clear()
        self.props.scroll_to_top()
        if not self.gm:
            self._form = None
            return
        form = Form(self.props.body)
        self._form = form

        if self.selected_kind == "shape":
            shape = self.gm.shape(self.selected_id)
            if shape:
                form.heading(mm.TERRAIN.get(shape.kind, {}).get("label", shape.kind))
                form.combo("Kind", shape, "kind", mm.TERRAIN_ORDER)
                form.entry("Area name", shape, "label")
                form.integer("Line width", shape, "width")
                form.check("Closed area", shape, "closed")
                form.combo("Layer", shape, "layer", self.gm.layer_names())
                form.readonly("Points", str(len(shape.points)))
                form.button_row([
                    ("Apply", self._apply_props),
                    ("Fill colour", lambda: self._pick_colour(shape, "fill")),
                    ("Delete", self._delete_selected),
                ])
        elif self.selected_kind == "pin":
            pin = self.gm.pin(self.selected_id)
            if pin:
                form.heading("Pin")
                form.entry("Name", pin, "label")
                form.combo("Type", pin, "kind", list(mm.PIN_KINDS))
                form.combo("Label side", pin, "label_side", ["e", "w", "n", "s"])
                form.integer("Size", pin, "size")
                form.combo("Layer", pin, "layer", self.gm.layer_names())
                form.multiline("Notes", pin, "notes", height=4)
                linked = self.project.data.entity(pin.entity_id)
                form.readonly("Linked sheet", linked.name if linked else "(none)")
                form.button_row([
                    ("Apply", self._apply_props),
                    ("Link...", self._link_pin),
                    ("Delete", self._delete_selected),
                ])
        elif self.selected_kind == "label":
            label = self.gm.label(self.selected_id)
            if label:
                form.heading("Label")
                form.entry("Text", label, "text")
                form.integer("Size", label, "size")
                form.integer("Letter spacing", label, "tracking")
                form.check("Italic", label, "italic")
                form.check("Bold", label, "bold")
                form.combo("Layer", label, "layer", self.gm.layer_names())
                form.button_row([
                    ("Apply", self._apply_props),
                    ("Colour", lambda: self._pick_colour(label, "color")),
                    ("Delete", self._delete_selected),
                ])
        else:
            form.heading("Map")
            form.entry("Name", self.gm, "name")
            form.combo("Type", self.gm, "kind", list(mm.MAP_KINDS))
            form.combo("Style", self.gm, "style", list(mm.STYLES))
            form.integer("Width", self.gm, "width")
            form.integer("Height", self.gm, "height")
            form.combo("Grid", self.gm, "grid", list(mm.GRID_KINDS))
            form.integer("Grid size", self.gm, "grid_size")
            form.entry("Scale caption", self.gm, "scale_text")
            form.hint("For example '100 leagues'. Leave blank to hide the bar.")
            form.check("Compass rose", self.gm, "compass")
            form.check("Decorative border", self.gm, "border")
            form.check("Title on the map", self.gm, "title_on_map")
            form.integer("Texture seed", self.gm, "seed")
            form.multiline("Notes", self.gm, "notes", height=5)
            form.separator()
            form.readonly("Shapes", str(len(self.gm.shapes)))
            form.readonly("Pins", str(len(self.gm.pins)))
            form.readonly("Labels", str(len(self.gm.labels)))
            form.button_row([
                ("Apply", self._apply_props),
                ("Fit view", self.cmd_zoom_fit),
            ])
            form.hint("Click anything on the map to edit it instead.")

    def _apply_props(self) -> None:
        if not self._form:
            return
        before = copy.deepcopy(self.gm.to_json()) if self.gm else None
        if self._form.commit():
            if before is not None:
                self._undo.append(before)
                if len(self._undo) > UNDO_LIMIT:
                    self._undo.pop(0)
                self._redo.clear()
            self.dirty = True
            self._bg_cache.clear()
            self._refresh_layers()
            self._build_props()
            self.redraw()
            self._say("Applied.")
        else:
            self._say("Nothing changed.")

    def _pick_colour(self, obj, attr: str) -> None:
        current = getattr(obj, attr, "") or "#888888"
        try:
            chosen = colorchooser.askcolor(color=current, parent=self)[1]
        except tk.TclError:
            chosen = None
        if not chosen:
            return
        self._push_undo()
        setattr(obj, attr, chosen)
        self.redraw()

    # ==================================================================
    # Commands
    # ==================================================================

    def cmd_generate(self) -> None:
        """Build a whole world from parameters, then hand it to the editor."""
        if not self._confirm_discard():
            return
        params = _GenerateDialog(self).show()
        if not params:
            return
        from .. import mapgen

        self.configure(cursor="watch")
        self._say("Generating world - heightmap, coastlines, rivers, "
                  "biomes, settlements...")
        self.update_idletasks()
        try:
            generated = mapgen.generate(params)
        except Exception as exc:
            self.configure(cursor="")
            messagebox.showerror(
                "Generation failed",
                f"{type(exc).__name__}: {exc}\n\nTry a different seed or "
                f"less extreme settings.", parent=self,
            )
            return
        self.configure(cursor="")

        self.gm = generated
        self.map_file = None
        self.dirty = True
        self._after_load()
        counts: Dict[str, int] = {}
        for shape in generated.shapes:
            counts[shape.kind] = counts.get(shape.kind, 0) + 1
        self._say(
            f"Generated '{generated.name}': "
            f"{counts.get('land', 0)} landmasses, "
            f"{counts.get('river', 0)} rivers, {len(generated.pins)} settlements. "
            f"Everything is editable - press Save to keep it."
        )

    def cmd_surprise(self) -> None:
        """
        A whole world, one press, no questions.

        The Generate dialog exists for when the writer knows what they want.
        This is for when they do not: every choice is made from the system's
        entropy, so pressing it twice gives two different worlds. The seed is
        recorded on the map, so one you like can be reproduced.
        """
        if not self._confirm_discard():
            return
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            params = mapgen.random_params()
            generated = mapgen.generate(params)
        except Exception as exc:
            self.configure(cursor="")
            messagebox.showerror(
                "Could not generate a world",
                f"{type(exc).__name__}: {exc}\n\nPress it again - the next "
                f"seed will be a different world.", parent=self)
            return
        self.configure(cursor="")

        self.gm = generated
        self.map_file = None
        self.dirty = True
        self._after_load()
        counts: Dict[str, int] = {}
        for shape in generated.shapes:
            counts[shape.kind] = counts.get(shape.kind, 0) + 1
        self._say(
            f"'{generated.name}' - {counts.get('land', 0)} landmasses, "
            f"{counts.get('river', 0)} rivers, {counts.get('mountains', 0)} "
            f"ranges, {len(generated.pins)} settlements, named in the "
            f"'{params.name_flavour}' style. Press Surprise Me again for a "
            f"different world, or Save to keep this one."
        )

    def cmd_edit_names(self) -> None:
        """Open the writer's own name lists for editing."""
        path = mm.load_name_styles(self.folder)
        if not open_in_default_app(path):
            reveal_in_explorer(path.parent)
        self._say(
            f"Editing {path.name}. Add or replace styles, save the file, then "
            f"press Surprise Me - the new names are picked up straight away."
        )

    def cmd_new_map(self) -> None:
        if not self._confirm_discard():
            return
        result = _NewMapDialog(self).show()
        if not result:
            return
        self.gm = (mm.starter_map(result["name"], result["kind"], result["style"])
                   if result["starter"]
                   else mm.GameMap(name=result["name"], kind=result["kind"],
                                   style=result["style"]))
        self.gm.width = result["width"]
        self.gm.height = result["height"]
        self.map_file = None
        self.dirty = True
        self._after_load()
        self._say(f"Created '{self.gm.name}'. Press Save to write it to disk.")

    def cmd_save(self) -> None:
        if not self.gm:
            return
        try:
            new_path = mm.map_path(self.folder, self.gm)
            # A rename changes the filename; remove the file under the old name.
            if self.map_file and self.map_file != new_path and self.map_file.exists():
                try:
                    self.map_file.unlink()
                except OSError:
                    pass
            self.map_file = mm.save_map(self.folder, self.gm)
        except OSError as exc:
            messagebox.showerror("Could not save", str(exc), parent=self)
            return
        self.dirty = False
        self._refresh_map_list(self.gm.name)
        self.on_change()
        self._say(f"Saved {self.map_file.name}")

    def cmd_rename(self) -> None:
        if not self.gm:
            return
        name = TextPrompt(self, "Rename map", "Map name", self.gm.name).show()
        if not name:
            return
        self._push_undo()
        self.gm.name = name
        self.cmd_save()
        self._build_props()
        self.redraw()

    def cmd_delete_map(self) -> None:
        if not (self.gm and self.map_file):
            self._say("This map has not been saved yet.")
            return
        if not messagebox.askyesno(
            "Delete map",
            f"Permanently delete '{self.gm.name}'?\n\n"
            f"{self.map_file.name} will be removed. Any exported PNG or SVG "
            f"stays on disk.", parent=self,
        ):
            return
        mm.delete_map(self.map_file)
        self.map_file = None
        self.gm = None
        self._refresh_map_list()
        if self.maps:
            self._open_map(self.maps[0][1])
        else:
            self.canvas.delete("all")
            self.props.clear()
        self.on_change()
        self._say("Map deleted.")

    def cmd_export_png(self) -> None:
        if not self.gm:
            return
        target = self.folder / f"{_safe(self.gm.name)}.png"
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            mm.render_png(self.gm, target, scale=1.0, supersample=2)
        except Exception as exc:
            self.configure(cursor="")
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        self.configure(cursor="")
        size = target.stat().st_size / 1024
        self.on_change()
        if messagebox.askyesno(
            "PNG exported",
            f"{target.name}  ({size:.0f} KB, {self.gm.width}x{self.gm.height})\n\n"
            f"Open it now?", parent=self,
        ):
            open_in_default_app(target)

    def cmd_export_svg(self) -> None:
        if not self.gm:
            return
        target = self.folder / f"{_safe(self.gm.name)}.svg"
        try:
            mm.render_svg(self.gm, target)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        self.on_change()
        if messagebox.askyesno(
            "SVG exported",
            f"{target.name}\n\nSVG is scalable - it stays sharp at any size and "
            f"opens in any browser.\n\nOpen it now?", parent=self,
        ):
            open_in_default_app(target)

    def cmd_export_docx(self) -> None:
        if not self.gm:
            return
        self.configure(cursor="watch")
        self.update_idletasks()
        png = self.folder / f"{_safe(self.gm.name)}.png"
        target = self.folder / f"{_safe(self.gm.name)}.docx"
        try:
            mm.render_png(self.gm, png, scale=1.0, supersample=2)
            lookup = {e.id: e.name
                      for e in self.project.data.entities_of("location")}
            mm.render_docx(self.gm, png, target, lookup)
        except Exception as exc:
            self.configure(cursor="")
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        self.configure(cursor="")
        self.on_change()
        if messagebox.askyesno(
            "Added to your documents",
            f"{target.name}\n\nA Word document with the map image and a legend "
            f"of every pin. It lives in 13 Maps.\n\nOpen it now?", parent=self,
        ):
            open_in_default_app(target)

    def cmd_name_generator(self) -> None:
        def build() -> str:
            lines = ["PLACE NAME GENERATOR", "=" * 26, "",
                     "Rough-and-ready syllable mashing. Take what sounds right,",
                     "ignore the rest, press Refresh for another batch.", ""]
            for flavour in mm.NAME_SYLLABLES:
                names = mm.generate_names(flavour, 14)
                lines.append(flavour.upper())
                for i in range(0, len(names), 2):
                    lines.append("    " + "".join(
                        f"{n:<22s}" for n in names[i:i + 2]
                    ))
                lines.append("")
            return "\n".join(lines)

        window = ReportWindow(self, "Name generator", build(),
                              width=560, height=620)
        # Give Refresh a real action now that the window exists to update.
        window.add_action("Refresh", lambda: window.set_body(build()), first=True)

    def cmd_help(self) -> None:
        body = """MAP MAKER
=========

DRAWING A COASTLINE
  1. Pick "Freehand" and choose "Land / coast" in the terrain list.
  2. Hold the left mouse button and draw a rough blob.
  3. Let go. The line is smoothed and filled, and a coastal halo is
     added automatically.

  Prefer straight edges? Use "Draw terrain" instead: click each corner,
  then double-click (or press Enter) to close the shape. Esc cancels.

TERRAIN
  Filled areas    land, sea, forest, desert, marsh, ice, region
  Drawn lines     mountain range, hills, river, road, wall, route

  Mountains and hills are drawn ALONG the line you make - draw the spine
  of the range and peaks are scattered over it. Forests, deserts and
  marshes fill the area you enclose with trees, stippling or reeds.

  Rivers taper: thin at the source, wider at the mouth. Draw them from
  the mountains downward.

PLACES
  "Place pin" drops a marker: capital, city, town, castle, ruin, port,
  dungeon, treasure, and a dozen more. Right-click a pin to link it to
  a Location sheet - then double-click the pin to open that sheet in
  Word. Your map and your worldbuilding notes stay connected.

LABELS
  "Add label" places free text. Region and ocean names traditionally use
  wide letter spacing in italics, which is the default.

MOVING AROUND
  Mouse wheel       zoom (keeps the point under the cursor fixed)
  Middle-drag       pan, with any tool selected
  Fit               zoom to show the whole map
  Select + drag     move anything
  Delete            remove the selected thing
  Ctrl+Z / Ctrl+Y   undo / redo

LAYERS
  Put political borders on one layer and terrain on another, then hide
  the borders when you want a clean geography map. Double-click a layer
  to show or hide it.

STYLES
  Parchment   aged paper, sepia ink - the classic
  Ink         clean black on white, good for printing
  Dark        light lines on near-black
  Treasure    heavy aged paper; use a dashed "route" and a treasure pin

EXPORTING
  PNG       a picture, ready to paste anywhere
  SVG       scalable, stays sharp at any size, opens in a browser
  To Word   a .docx holding the map plus a legend table of every pin

  All three land in the "13 Maps" folder beside your novel.

A NOTE ON SCALE
  A person walks about 20 miles a day on a road, less across country.
  Set the scale caption and check your journeys against it - readers
  notice when a week's ride happens overnight.
"""
        ReportWindow(self, "Map maker help", body, width=760, height=720)

    # ==================================================================
    # Housekeeping
    # ==================================================================

    def _say(self, message: str) -> None:
        self.status.configure(text=message)

    def _update_status(self) -> None:
        if not self.gm:
            return
        marker = " *unsaved" if self.dirty else ""
        self.title(f"Map Maker - {self.gm.name}{marker}")

    def _confirm_discard(self) -> bool:
        """
        Make sure nothing is lost, without asking permission to do it.

        The old behaviour was a Yes/No/Cancel box every single time the window
        closed or the map changed. A writer who has drawn something wants to
        keep it; a writer who has not drawn anything is being interrupted for
        no reason. Neither of them wants to answer a question.

        So: unsaved work is simply saved. A map that already has a file goes
        back to that file; one that has never been saved gets a file named
        after itself. Only a save that actually *fails* is worth an interruption,
        because then there is a real decision to make.

        Set "map_prompt_on_close" if you would rather be asked.
        """
        if not (self.gm and self.dirty):
            return True

        if settings["map_prompt_on_close"]:
            answer = messagebox.askyesnocancel(
                "Unsaved map",
                f"'{self.gm.name}' has unsaved changes.\n\n"
                f"Yes - save it first\nNo - discard the changes\n"
                f"Cancel - go back",
                parent=self,
            )
            if answer is None:
                return False
            if answer:
                self.cmd_save()
            return True

        # cmd_save has already explained any failure. Keep offering to retry
        # until it works or the writer chooses to stay - never close on a
        # failed save, because closing is what loses the map.
        while True:
            self.cmd_save()
            if not self.dirty:
                return True
            if not messagebox.askretrycancel(
                "Could not save the map",
                f"'{self.gm.name}' could not be written to disk.\n\n"
                f"Retry - try saving again\n"
                f"Cancel - stay here, with the map still open",
                parent=self,
            ):
                return False

    def _close(self) -> None:
        if not self._confirm_discard():
            return
        if self._redraw_job:
            try:
                self.after_cancel(self._redraw_job)
            except (ValueError, tk.TclError):
                pass
        self.on_change()
        self.destroy()


def _safe(name: str) -> str:
    from ..atomic import safe_filename

    return safe_filename(name, "Map")


# ==========================================================================
# New map dialog
# ==========================================================================


class _GenerateDialog(Dialog):
    """
    Parameters for a procedurally generated world.

    Laid out as sliders because these are all "somewhere between" choices, not
    numbers anyone knows in advance. Presets fill everything in at once so the
    first click produces something good rather than something average.
    """

    def __init__(self, parent) -> None:
        from .. import mapgen

        self.mapgen = mapgen
        self.vars: Dict[str, tk.Variable] = {}
        self._value_labels: Dict[str, ttk.Label] = {}
        super().__init__(parent, "Generate a World", 620, 780)

    def build(self, parent: ttk.Frame) -> None:
        mapgen = self.mapgen
        scroll = ScrollFrame(parent)
        scroll.grid(row=0, column=0, sticky="nsew")
        parent.rowconfigure(0, weight=1)
        body = scroll.body
        body.columnconfigure(1, weight=1)
        self._row = 0

        def heading(text: str, hint: str = "") -> None:
            ttk.Label(body, text=text.upper(), style="Section.TLabel").grid(
                row=self._row, column=0, columnspan=3, sticky="w",
                pady=(14, 2))
            self._row += 1
            if hint:
                ttk.Label(body, text=hint, style="Hint.TLabel",
                          wraplength=520, justify="left").grid(
                    row=self._row, column=0, columnspan=3, sticky="w",
                    pady=(0, 4))
                self._row += 1

        def slider(label: str, key: str, value: float, lo: float, hi: float,
                   percent: bool = True, hint: str = "") -> None:
            ttk.Label(body, text=label).grid(row=self._row, column=0,
                                            sticky="w", padx=(2, 8))
            var = tk.DoubleVar(value=value)
            self.vars[key] = var
            scale = ttk.Scale(body, from_=lo, to=hi, variable=var,
                              orient="horizontal")
            scale.grid(row=self._row, column=1, sticky="ew", padx=(0, 6))
            shown = ttk.Label(body, text="", width=6, style="Hint.TLabel")
            shown.grid(row=self._row, column=2, sticky="e")
            self._value_labels[key] = shown

            def update(*_a) -> None:
                v = var.get()
                shown.configure(text=f"{v * 100:.0f}%" if percent
                                else f"{v:.0f}")
            var.trace_add("write", update)
            update()
            self._row += 1
            if hint:
                ttk.Label(body, text=hint, style="Hint.TLabel",
                          wraplength=500, justify="left").grid(
                    row=self._row, column=0, columnspan=3, sticky="w",
                    padx=(12, 0), pady=(0, 4))
                self._row += 1

        def combo(label: str, key: str, options: Dict[str, str],
                  current: str) -> None:
            ttk.Label(body, text=label).grid(row=self._row, column=0,
                                            sticky="w", padx=(2, 8), pady=3)
            var = tk.StringVar(value=options.get(current, ""))
            self.vars[key] = var
            widget = ttk.Combobox(body, textvariable=var, state="readonly",
                                  values=list(options.values()), width=40)
            widget.grid(row=self._row, column=1, columnspan=2, sticky="ew",
                        pady=3)
            self._row += 1

        def check(label: str, key: str, value: bool) -> None:
            var = tk.BooleanVar(value=value)
            self.vars[key] = var
            ttk.Checkbutton(body, text=label, variable=var).grid(
                row=self._row, column=0, columnspan=3, sticky="w", padx=(2, 0))
            self._row += 1

        # -- preset -----------------------------------------------------
        heading("Start from a preset",
                "Pick one, then adjust anything below. Every setting is "
                "editable afterwards and the whole map stays hand-editable.")
        preset_var = tk.StringVar(value="Classic fantasy world")
        self.vars["_preset"] = preset_var
        preset_box = ttk.Combobox(body, textvariable=preset_var,
                                  state="readonly", width=40,
                                  values=list(mapgen.PRESETS))
        preset_box.grid(row=self._row, column=0, columnspan=2, sticky="ew",
                        padx=(2, 6))
        ttk.Button(body, text="Apply", width=7,
                   command=self._apply_preset).grid(row=self._row, column=2)
        self._row += 1

        # -- seed -------------------------------------------------------
        heading("Seed",
                "Type anything - a word, a phrase, a number. The same seed and "
                "settings always rebuild the exact same world, so you can note "
                "it down or share it with someone else. Leave it blank for a "
                "random world every time.")
        seed_var = tk.StringVar(value="")
        self.vars["seed_text"] = seed_var
        seed_entry = ttk.Entry(body, textvariable=seed_var, width=26)
        seed_entry.grid(row=self._row, column=0, columnspan=2, sticky="ew",
                        padx=(2, 6))
        ttk.Button(body, text="Surprise me", width=13,
                   command=self._randomise).grid(row=self._row, column=2,
                                                 sticky="w")
        self._row += 1
        self._seed_hint = ttk.Label(body, text="", style="Hint.TLabel")
        self._seed_hint.grid(row=self._row, column=0, columnspan=3,
                             sticky="w", padx=(2, 0))
        self._row += 1

        def show_seed(*_a) -> None:
            raw = seed_var.get().strip()
            if not raw:
                self._seed_hint.configure(
                    text="Blank - a different world each time you generate.")
            else:
                self._seed_hint.configure(
                    text=f"'{raw}'  ->  seed {self.mapgen.seed_from_text(raw)}")

        seed_var.trace_add("write", show_seed)
        show_seed()

        ttk.Label(body, text="Map name").grid(row=self._row, column=0,
                                             sticky="w", padx=(2, 8), pady=3)
        name_var = tk.StringVar(value="")
        self.vars["name"] = name_var
        ttk.Entry(body, textvariable=name_var, width=30).grid(
            row=self._row, column=1, columnspan=2, sticky="ew", pady=3)
        self._row += 1
        ttk.Label(body, text="Leave blank and one will be invented for you.",
                  style="Hint.TLabel").grid(row=self._row, column=1,
                                            columnspan=2, sticky="w")
        self._row += 1

        # -- land and water ---------------------------------------------
        heading("Land and water")
        combo("Arrangement", "shape", mapgen.LANDMASS_SHAPES, "continents")
        slider("Land vs water", "land_fraction", 0.34, 0.05, 0.85, True,
               "How much of the page is land. 34% gives generous oceans; "
               "above 60% the sea becomes lakes.")
        slider("Continents", "continents", 3, 1, 12, False,
               "Major landmasses. Ignored for the supercontinent arrangement.")
        slider("Islands", "islands", 16, 0, 120, False)
        slider("Coast roughness", "roughness", 0.55, 0.0, 1.0, True,
               "Low gives smooth, rounded coasts. High gives fjords, "
               "peninsulas and deep bays.")
        slider("Ocean at the edges", "edge_water", 0.85, 0.0, 1.0, True,
               "How hard the border is pushed under water, so the world does "
               "not run off the page.")

        # -- relief -----------------------------------------------------
        heading("Relief and water")
        slider("Mountains", "mountains", 0.45, 0.0, 1.0)
        slider("Hills", "hills", 0.35, 0.0, 1.0)
        slider("Rivers", "rivers", 9, 0, 60, False,
               "Rivers follow the terrain downhill from high ground to the "
               "sea, so they always run the right way.")
        slider("Lakes", "lakes", 4, 0, 40, False)

        # -- climate ----------------------------------------------------
        heading("Climate",
                "Temperature comes from latitude and altitude, moisture from "
                "noise. Biomes are placed where the two agree.")
        combo("Climate", "climate", mapgen.CLIMATES, "temperate")
        slider("Forest", "forest", 0.40, 0.0, 1.0)
        slider("Desert", "desert", 0.15, 0.0, 1.0)
        slider("Marsh", "marsh", 0.10, 0.0, 1.0)
        check("Ice caps at the poles", "ice_caps", True)

        # -- civilisation -----------------------------------------------
        heading("Civilisation",
                "Sites are scored for habitability - coastal access, fresh "
                "water, gentle ground - and spaced apart.")
        slider("Capitals", "capitals", 2, 0, 20, False)
        slider("Cities", "cities", 6, 0, 40, False)
        slider("Towns", "towns", 12, 0, 60, False)
        slider("Villages", "villages", 10, 0, 60, False)
        slider("Ruins", "ruins", 5, 0, 40, False)
        slider("Landmarks", "landmarks", 4, 0, 40, False)
        check("Draw roads between settlements", "roads", True)
        check("Invent place names", "name_places", True)
        combo("Name style", "name_flavour",
              {k: k.title() for k in mm.NAME_SYLLABLES}, "plain")

        # -- presentation -----------------------------------------------
        heading("Presentation")
        combo("Style", "style",
              {k: v["label"] for k, v in mm.STYLES.items()}, "parchment")
        ttk.Label(body, text="Size (pixels)").grid(row=self._row, column=0,
                                                   sticky="w", padx=(2, 8))
        size_frame = ttk.Frame(body)
        size_frame.grid(row=self._row, column=1, columnspan=2, sticky="w")
        self.vars["width"] = tk.StringVar(value="1800")
        self.vars["height"] = tk.StringVar(value="1200")
        ttk.Entry(size_frame, textvariable=self.vars["width"],
                  width=7).grid(row=0, column=0)
        ttk.Label(size_frame, text=" x ").grid(row=0, column=1)
        ttk.Entry(size_frame, textvariable=self.vars["height"],
                  width=7).grid(row=0, column=2)
        self._row += 1
        ttk.Label(body, text="Scale caption").grid(row=self._row, column=0,
                                                   sticky="w", padx=(2, 8),
                                                   pady=3)
        self.vars["scale_text"] = tk.StringVar(value="200 leagues")
        ttk.Entry(body, textvariable=self.vars["scale_text"], width=20).grid(
            row=self._row, column=1, sticky="w", pady=3)
        self._row += 1
        check("Name the largest landmasses", "label_regions", True)

        ttk.Label(body, text="Generating takes about a second. Nothing is "
                             "saved until you press Save in the editor.",
                  style="Hint.TLabel", wraplength=520, justify="left").grid(
            row=self._row, column=0, columnspan=3, sticky="w", pady=(12, 0))

    def _randomise(self) -> None:
        self.vars["seed_text"].set(str(self.mapgen.random_seed()))

    def _apply_preset(self) -> None:
        name = self.vars["_preset"].get()
        params = self.mapgen.preset(name, seed=self._seed())
        for key, var in self.vars.items():
            # The seed and the name are the writer's, not the preset's.
            if key.startswith("_") or key in ("seed", "seed_text", "name"):
                continue
            if not hasattr(params, key):
                continue
            value = getattr(params, key)
            if key == "shape":
                var.set(self.mapgen.LANDMASS_SHAPES.get(value, ""))
            elif key == "climate":
                var.set(self.mapgen.CLIMATES.get(value, ""))
            elif key == "style":
                var.set(mm.STYLES.get(value, {}).get("label", ""))
            elif key == "name_flavour":
                var.set(str(value).title())
            elif isinstance(var, tk.BooleanVar):
                var.set(bool(value))
            elif isinstance(var, tk.DoubleVar):
                var.set(float(value))
            else:
                var.set(str(value))

    def _seed(self) -> int:
        return self.mapgen.seed_from_text(self.vars["seed_text"].get())

    def collect(self):
        mapgen = self.mapgen

        def reverse(options: Dict[str, str], shown: str, fallback: str) -> str:
            for key, label in options.items():
                if label == shown:
                    return key
            return fallback

        def number(key: str, fallback: int) -> int:
            try:
                return int(float(str(self.vars[key].get()).strip()))
            except (ValueError, AttributeError):
                return fallback

        params = mapgen.MapParams(
            seed=self._seed(),
            seed_text=self.vars["seed_text"].get().strip(),
            name=self.vars["name"].get().strip(),
            shape=reverse(mapgen.LANDMASS_SHAPES,
                          self.vars["shape"].get(), "continents"),
            land_fraction=self.vars["land_fraction"].get(),
            continents=int(self.vars["continents"].get()),
            islands=int(self.vars["islands"].get()),
            roughness=self.vars["roughness"].get(),
            edge_water=self.vars["edge_water"].get(),
            mountains=self.vars["mountains"].get(),
            hills=self.vars["hills"].get(),
            rivers=int(self.vars["rivers"].get()),
            lakes=int(self.vars["lakes"].get()),
            climate=reverse(mapgen.CLIMATES,
                            self.vars["climate"].get(), "temperate"),
            forest=self.vars["forest"].get(),
            desert=self.vars["desert"].get(),
            marsh=self.vars["marsh"].get(),
            ice_caps=bool(self.vars["ice_caps"].get()),
            capitals=int(self.vars["capitals"].get()),
            cities=int(self.vars["cities"].get()),
            towns=int(self.vars["towns"].get()),
            villages=int(self.vars["villages"].get()),
            ruins=int(self.vars["ruins"].get()),
            landmarks=int(self.vars["landmarks"].get()),
            roads=bool(self.vars["roads"].get()),
            name_places=bool(self.vars["name_places"].get()),
            name_flavour=self.vars["name_flavour"].get().lower(),
            width=number("width", 1800),
            height=number("height", 1200),
            style=reverse({k: v["label"] for k, v in mm.STYLES.items()},
                          self.vars["style"].get(), "parchment"),
            label_regions=bool(self.vars["label_regions"].get()),
            scale_text=self.vars["scale_text"].get().strip(),
        )
        return params.clamped()

    def build_buttons(self, parent: ttk.Frame) -> None:
        ttk.Button(parent, text="Cancel", command=self.on_cancel).grid(
            row=0, column=0, padx=(0, 6))
        ttk.Button(parent, text="Generate", command=self.on_ok).grid(
            row=0, column=1)
        self.bind("<Return>", lambda _e: self.on_ok())


class _NewMapDialog(Dialog):
    PRESETS = {
        "world": (1800, 1200),
        "continent": (1600, 1100),
        "region": (1400, 1000),
        "city": (1200, 1200),
        "building": (1000, 1000),
        "dungeon": (1200, 900),
        "treasure": (1200, 900),
        "battle": (1200, 900),
    }

    def __init__(self, parent) -> None:
        super().__init__(parent, "New Map", 480, 440)

    def build(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        row = 0

        ttk.Label(parent, text="Name").grid(row=row, column=0, sticky="w",
                                            padx=(0, 8), pady=4)
        self.name = tk.StringVar(value="The Known World")
        entry = ttk.Entry(parent, textvariable=self.name, width=30)
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        entry.selection_range(0, "end")
        entry.focus_set()
        row += 1

        ttk.Label(parent, text="Type").grid(row=row, column=0, sticky="w",
                                            padx=(0, 8), pady=4)
        self.kind = tk.StringVar(value="World")
        kind_box = ttk.Combobox(parent, textvariable=self.kind, state="readonly",
                                values=list(mm.MAP_KINDS.values()), width=28)
        kind_box.grid(row=row, column=1, sticky="ew", pady=4)
        kind_box.bind("<<ComboboxSelected>>", self._on_kind)
        row += 1

        ttk.Label(parent, text="Style").grid(row=row, column=0, sticky="w",
                                             padx=(0, 8), pady=4)
        self.style = tk.StringVar(value="Parchment")
        ttk.Combobox(parent, textvariable=self.style, state="readonly",
                     values=[s["label"] for s in mm.STYLES.values()],
                     width=28).grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        ttk.Label(parent, text="Size (pixels)").grid(row=row, column=0,
                                                     sticky="w", padx=(0, 8))
        size_frame = ttk.Frame(parent)
        size_frame.grid(row=row, column=1, sticky="w", pady=4)
        self.width = tk.StringVar(value="1800")
        self.height = tk.StringVar(value="1200")
        ttk.Entry(size_frame, textvariable=self.width, width=7).grid(row=0, column=0)
        ttk.Label(size_frame, text=" x ").grid(row=0, column=1)
        ttk.Entry(size_frame, textvariable=self.height, width=7).grid(row=0, column=2)
        row += 1

        ttk.Label(parent, text="Bigger is more detailed but slower to render. "
                               "1800 x 1200 prints well on A4.",
                  style="Hint.TLabel", wraplength=400, justify="left").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
        row += 1

        self.starter = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, text="Start me off with a coastline",
                        variable=self.starter).grid(row=row, column=0,
                                                    columnspan=2, sticky="w")
        row += 1
        ttk.Label(parent, text="An empty page is harder to start than something "
                               "to push around. You can delete every piece of it "
                               "in a few clicks.",
                  style="Hint.TLabel", wraplength=400, justify="left").grid(
            row=row, column=0, columnspan=2, sticky="w", padx=(22, 0))

    def _on_kind(self, _event=None) -> None:
        key = next((k for k, v in mm.MAP_KINDS.items()
                    if v == self.kind.get()), "world")
        width, height = self.PRESETS.get(key, (1600, 1100))
        self.width.set(str(width))
        self.height.set(str(height))

    def collect(self) -> Optional[dict]:
        name = self.name.get().strip()
        if not name:
            messagebox.showwarning("Name needed", "Give the map a name.",
                                   parent=self)
            return None

        def as_int(var: tk.StringVar, fallback: int) -> int:
            try:
                return max(300, min(6000, int(float(var.get().strip()))))
            except ValueError:
                return fallback

        kind = next((k for k, v in mm.MAP_KINDS.items()
                     if v == self.kind.get()), "world")
        style = next((k for k, v in mm.STYLES.items()
                      if v["label"] == self.style.get()), "parchment")
        return {
            "name": name, "kind": kind, "style": style,
            "width": as_int(self.width, 1800),
            "height": as_int(self.height, 1200),
            "starter": bool(self.starter.get()),
        }
