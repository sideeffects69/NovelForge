"""
The main window.

Three panes: binder on the left, editor in the middle, inspector on the right.
Menus carry everything else.

Kept fast by three rules:
  1. Rendering never reads a Word document. Every number shown comes from the
     manifest, which is one small JSON file.
  2. Autosave and word counting are debounced on idle, not run per keystroke.
  3. Expensive sweeps are menu commands, and say so.
"""

from __future__ import annotations

import re
import tkinter as tk
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import (
    APP_NAME,
    APP_VERSION,
    backup,
    compiler,
    diagnostics,
    docxio,
    recovery,
    stats,
    structures,
)
from ..atomic import FileBusyError
from ..config import (
    THEMES,
    app_root,
    open_in_default_app,
    projects_root,
    reveal_in_explorer,
    settings,
    theme,
)
from ..model import (
    CHARACTER_ROLES,
    ENTITY_PLURAL,
    ENTITY_TYPES,
    SCENE_STATUSES,
    SCENE_TYPES,
    STATUS_COLOURS,
    now_iso,
)
from ..project import Project, ProjectError, list_projects
from . import dialogs, styling
from .writing import WritingIntelligence
from .widgets import (
    AutoScrollbar,
    Form,
    Gauge,
    ScrollFrame,
    ScrolledText,
    StatusBar,
    WritingCheck,
    add_editing_keys,
    bind_tree_shortcuts,
    center_window,
    clamp_to_screen,
    fit_size,
)

# Glyphs are plain Unicode so no font or icon file has to ship with the tool.
GROUP_ORDER = [
    ("manuscript", "✎  Manuscript"),
    ("beats", "◈  Outline & Beats"),
    ("character", "☺  Characters"),
    ("location", "⌂  Locations"),
    ("item", "❖  Items"),
    ("faction", "⚑  Factions"),
    ("thread", "⁙  Plot Threads"),
    ("world", "◍  World Bible"),
    ("maps", "⊕  Maps"),
    ("timeline", "⧗  Timeline"),
    ("notes", "✐  Notes & Research"),
    ("publishing", "✉  Publishing"),
]


class App(WritingIntelligence, tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        # Before anything is built or sized: every widget created afterwards
        # inherits the scaled fonts, and the geometry below is computed
        # against the real work area.
        self.ui_scale = _apply_scaling(self)
        self.project: Optional[Project] = None
        self.tracker: Optional[stats.SessionTracker] = None

        self.selection_kind: str = ""
        self.selection_id: str = ""
        self.current_scene_id: str = ""

        self._editor_dirty = False
        self._suppress_modified = False
        self._autosave_job: Optional[str] = None
        self._journal_job: Optional[str] = None
        self.editor_check: Optional[WritingCheck] = None
        self.live_check_var = tk.BooleanVar(value=settings["live_writing_check"])
        self._count_job: Optional[str] = None
        self._focus_job: Optional[str] = None
        self._form: Optional[Form] = None
        self._ghost_mode = False
        self._distraction_free = False

        self.title(APP_NAME)

        self._build_styles()
        self._build_menu()
        self._build_layout()
        self._bind_keys()

        # Sized after the menu bar exists, not before. Tk's geometry excludes
        # the menu bar, so the window is drawn one menu row taller than asked
        # for - and this is the window most likely to fill the screen, which
        # made it the one that ended up under the taskbar.
        #
        # A remembered geometry is only usable if it still lands on a screen
        # that exists. Restoring 1600x900 at +1920+0 after the second monitor
        # is unplugged puts the whole window somewhere unreachable.
        remembered = clamp_to_screen(self, settings["window_geometry"])
        if remembered:
            self.geometry(remembered)
        else:
            center_window(self, 1280, 800)
        # The floor is clamped too: a minsize bigger than the desktop is a
        # trap the user cannot get out of by resizing.
        # Wide enough that the toolbar is never clipped, whatever the labels or
        # fonts come to: measured, not guessed.
        self.update_idletasks()
        self._toolbar_full_width = self.toolbar.winfo_reqwidth()
        self.toolbar.bind("<Configure>", self._fit_toolbar)
        # With the icon font the toolbar can shrink to icons, so 900 is enough;
        # without it the labels must stay, and the window must be wide enough.
        needed = 0 if self.icons.available else self._toolbar_full_width + 16
        floor_w, floor_h = fit_size(
            self, max(int(900 * self.ui_scale), needed), int(560 * self.ui_scale))
        self.minsize(floor_w, floor_h)
        self._app_icons = styling.app_icons(self, self.tokens)
        if self._app_icons:
            try:
                self.iconphoto(True, *self._app_icons)
            except tk.TclError:
                pass

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(120, self._startup)

    # ==================================================================
    # Appearance
    # ==================================================================

    def _build_styles(self) -> None:
        self.style = ttk.Style(self)
        self._apply_theme()

    def _apply_theme(self) -> None:
        """
        (Re)apply the palette to every ttk style and Tk default.

        The look itself lives in `styling.py`; this only calls it and then
        refreshes the pieces of the main window that carry their own colours.
        """
        self.tokens = styling.apply(self, self.style, theme(), self.ui_scale)
        styling.style_titlebar(self, self.tokens)
        if hasattr(self, "tree"):
            self._configure_tree_tags()
        if hasattr(self, "_toolbar_buttons"):
            self._refresh_toolbar_icons()
        if hasattr(self, "status"):
            self.status.refresh_theme()
        if hasattr(self, "menu_strip"):
            self._build_menu_strip()
        if hasattr(self, "editor"):
            # Everything already on screen, tool windows included; the editor
            # is coloured by _style_editor (ghost mode hides its text).
            styling.retheme(self, self.tokens, skip=(self.editor.text,))
            # The placeholder "N" mark takes the accent colour (a real
            # brand/icon.png does not change), for every window opened from now.
            self._app_icons = styling.app_icons(self, self.tokens)
            if self._app_icons:
                try:
                    self.iconphoto(True, *self._app_icons)
                except tk.TclError:
                    pass
            welcome = getattr(self, "welcome", None)
            if welcome is not None and welcome.winfo_ismapped():
                welcome.destroy()                    # its card colours are baked in
                self.welcome = None
                self._show_welcome()

    def _configure_tree_tags(self) -> None:
        """
        Colour scene rows by status and mute structural rows.

        Reading the binder at a glance is the point: a chapter of red 'Needs
        Work' rows tells you where tomorrow goes without opening anything.
        """
        palette = theme()
        # The status colours were picked against a cream page; on a dark or tan
        # sidebar some of them nearly vanish, so each is nudged only as far as
        # needed to stay readable on the binder's own background.
        ground = self.tokens["panel"]

        def legible(colour: str, target: float = 3.6) -> str:
            return styling.ensure_contrast(colour, ground, target)

        for status, colour in STATUS_COLOURS.items():
            self.tree.tag_configure(f"status:{status}", foreground=legible(colour))
        self.tree.tag_configure("group", font=("Segoe UI", 9, "bold"),
                                foreground=legible(palette["accent"], 4.5))
        self.tree.tag_configure("muted", foreground=legible(palette["dim"], 3.0))
        self.tree.tag_configure("excluded", foreground=legible(palette["dim"], 3.0))
        self.tree.tag_configure("done", foreground=legible(
            STATUS_COLOURS.get("Final", "#4f8a5b")))
        self.tree.tag_configure("pov", font=("Segoe UI", 9, "bold"))

        if hasattr(self, "editor"):
            self._style_editor()
        if hasattr(self, "detail_text"):
            self.detail_text.text.configure(
                background=palette["bg"], foreground=palette["fg"],
                insertbackground=palette["caret"],
                selectbackground=palette["select"],
            )

    def _style_editor(self) -> None:
        palette = theme()
        font = (settings["editor_font"], settings["editor_font_size"])
        self.editor.text.configure(
            font=font,
            background=palette["bg"],
            foreground=palette["bg"] if self._ghost_mode else palette["fg"],
            insertbackground=palette["caret"],
            selectbackground=palette["select"],
            spacing1=2, spacing2=3, spacing3=8,
        )
        self.editor.text.tag_configure("dim", foreground=palette["dim"])
        self.editor.text.tag_configure(
            "bright", foreground=palette["bg"] if self._ghost_mode
            else palette["fg"]
        )

    # ==================================================================
    # Menu
    # ==================================================================

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        self.menubar = menubar

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Novel...", accelerator="Ctrl+Shift+N",
                              command=self.cmd_new_project)
        file_menu.add_command(label="Open Novel...", accelerator="Ctrl+O",
                              command=self.cmd_open_project)
        self.recent_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Open Recent", menu=self.recent_menu)
        file_menu.add_separator()
        file_menu.add_command(label="Save", accelerator="Ctrl+S",
                              command=lambda: self.cmd_save(explicit=True))
        file_menu.add_command(label="Reload from Word", accelerator="F2",
                              command=self.cmd_sync_from_disk)
        file_menu.add_command(label="Re-read Every Document (slow)",
                              command=lambda: self.cmd_sync_from_disk(force=True))
        file_menu.add_separator()
        file_menu.add_command(label="Back Up Now", accelerator="Ctrl+B",
                              command=self.cmd_backup)
        file_menu.add_command(label="Backups & Restore...",
                              command=self.cmd_backups)
        file_menu.add_command(label="Versions of this document...",
                              command=self.cmd_snapshots)
        file_menu.add_separator()
        file_menu.add_command(label="Project Settings...",
                              command=self.cmd_project_settings)
        file_menu.add_command(label="Preferences...",
                              command=self.cmd_preferences)
        file_menu.add_separator()
        file_menu.add_command(label="Open Project Folder",
                              command=self.cmd_open_folder)
        file_menu.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        add_menu = tk.Menu(menubar, tearoff=0)
        add_menu.add_command(label="Chapter", accelerator="Ctrl+Shift+C",
                             command=self.cmd_add_chapter)
        add_menu.add_command(label="Scene", accelerator="Ctrl+N",
                             command=self.cmd_add_scene)
        add_menu.add_separator()
        for entity_type in ENTITY_TYPES:
            add_menu.add_command(
                label=ENTITY_PLURAL[entity_type].rstrip("s")
                if entity_type != "thread" else "Plot Thread",
                command=lambda t=entity_type: self.cmd_add_entity(t),
            )
        add_menu.add_separator()
        add_menu.add_command(label="Note", command=lambda: self.cmd_add_note("note"))
        add_menu.add_command(label="Research Note",
                             command=lambda: self.cmd_add_note("research"))
        add_menu.add_command(label="Timeline Event",
                             command=self.cmd_add_event)
        menubar.add_cascade(label="Add", menu=add_menu)

        self.edit_menu = tk.Menu(menubar, tearoff=0)
        self.edit_menu.add_command(label="Undo", accelerator="Ctrl+Z",
                                   command=self.cmd_undo)
        self.edit_menu.add_command(label="Redo", accelerator="Ctrl+Y",
                                   command=self.cmd_redo)
        self.edit_menu.add_separator()
        # Find and Replace used to live in Tools, which is where every other
        # app on the writer's machine puts everything BUT find/replace - Word,
        # a browser, an IDE all put it in Edit. Moving it here is one less
        # thing to hunt for.
        self.edit_menu.add_command(label="Find in Project...",
                                   accelerator="Ctrl+F", command=self.cmd_search)
        self.edit_menu.add_command(label="Find and Replace...",
                                   accelerator="Ctrl+H", command=self.cmd_replace)
        self.edit_menu.add_separator()
        self.edit_menu.add_command(label="Open the Trash Folder",
                                   command=self.cmd_open_trash)
        menubar.add_cascade(label="Edit", menu=self.edit_menu)

        ms_menu = tk.Menu(menubar, tearoff=0)
        ms_menu.add_command(label="Compile Manuscript...", accelerator="F5",
                            command=self.cmd_compile)
        ms_menu.add_command(label="Quick Compile (last settings)",
                            accelerator="Shift+F5",
                            command=lambda: self.cmd_compile(quick=True))
        ms_menu.add_command(label="Open Compiled Manuscript",
                            command=self.cmd_open_compiled)
        ms_menu.add_separator()
        ms_menu.add_command(label="Export Plain Text",
                            command=self.cmd_export_text)
        ms_menu.add_command(label="Export Treatment (synopses)",
                            command=self.cmd_export_treatment)
        ms_menu.add_separator()
        ms_menu.add_command(label="Write Outline.docx",
                            command=self.cmd_write_outline)
        ms_menu.add_command(label="Write Reverse Outline",
                            command=self.cmd_reverse_outline)
        # Same kind of action as the two above - turn what's already in the
        # project into a reference document - so it lives with them rather
        # than in Plan, which is now everything that's read on screen.
        ms_menu.add_command(label="Write Story Bible",
                            command=self.cmd_story_bible)
        ms_menu.add_command(label="Sweep [Fix Later] Tags",
                            command=self.cmd_fix_later)
        ms_menu.add_separator()
        ms_menu.add_command(label="Import Loose .docx Files",
                            command=self.cmd_import_loose)
        menubar.add_cascade(label="Manuscript", menu=ms_menu)

        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Diagnose This Scene", accelerator="F7",
                               command=lambda: self.cmd_diagnostics("scene"))
        tools_menu.add_command(label="Diagnose This Chapter",
                               command=lambda: self.cmd_diagnostics("chapter"))
        tools_menu.add_command(label="Diagnose Whole Book",
                               command=lambda: self.cmd_diagnostics("book"))
        tools_menu.add_command(label="Scene Craft Check", accelerator="F8",
                               command=self.cmd_craft_check)
        tools_menu.add_separator()
        tools_menu.add_command(label="Statistics Dashboard", accelerator="F9",
                               command=self.cmd_dashboard)
        tools_menu.add_command(label="Word Frequency",
                               command=self.cmd_word_frequency)
        tools_menu.add_separator()
        tools_menu.add_command(label="Start Sprint", accelerator="F6",
                               command=self.cmd_sprint)
        tools_menu.add_command(label="Writer's Block Diagnostic",
                               command=self.cmd_block_diagnostic)
        tools_menu.add_separator()
        tools_menu.add_command(label="Spelling and Grammar",
                               accelerator="Shift+F7",
                               command=self.cmd_writing_check)
        tools_menu.add_checkbutton(
            label="Underline mistakes as I type",
            variable=self.live_check_var, command=self.cmd_toggle_live_check)
        tools_menu.add_command(label="Check Names in This Scene",
                               command=self.cmd_check_names)
        tools_menu.add_command(label="What the Editor Knows...",
                               command=self.cmd_lexicon_report)
        tools_menu.add_separator()
        tools_menu.add_command(label="Verify This Project", accelerator="F4",
                               command=self.cmd_verify_project)
        tools_menu.add_command(label="Continuity Check", accelerator="F10",
                               command=self.cmd_continuity)
        tools_menu.add_command(label="What Depends on This Scene?",
                               command=self.cmd_dependencies)
        tools_menu.add_separator()
        tools_menu.add_command(label="Rebuild This Sheet from Template",
                               command=self.cmd_rebuild_sheet)
        tools_menu.add_command(label="Check for Missing Files",
                               command=self.cmd_check_files)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        plan_menu = tk.Menu(menubar, tearoff=0)
        plan_menu.add_command(label="Story Graph...", accelerator="Ctrl+G",
                              command=self.cmd_story_graph)
        plan_menu.add_command(label="Ask Your Story...",
                              command=lambda: self.cmd_story_graph("ask"))
        plan_menu.add_command(label="Relationship Timeline...",
                              command=lambda:
                              self.cmd_story_graph("relationships"))
        plan_menu.add_separator()
        plan_menu.add_command(label="Idea Inbox...", accelerator="Ctrl+I",
                              command=self.cmd_idea_inbox)
        plan_menu.add_command(label="Drafts of This Scene...",
                              command=self.cmd_drafts)
        plan_menu.add_separator()
        plan_menu.add_command(label="Corkboard...", accelerator="Ctrl+K",
                              command=self.cmd_corkboard)
        plan_menu.add_command(label="Character Relationships...",
                              command=self.cmd_relationships)
        plan_menu.add_separator()
        plan_menu.add_command(label="Outline & Beats...", accelerator="Ctrl+L",
                              command=self.cmd_outline_window)
        plan_menu.add_command(label="Timeline...", accelerator="Ctrl+T",
                              command=self.cmd_timeline_window)
        plan_menu.add_command(label="Map Maker...", accelerator="Ctrl+M",
                              command=self.cmd_map_editor)
        plan_menu.add_command(label="Chapter Map...", accelerator="Ctrl+Shift+M",
                              command=self.cmd_chapter_map)
        plan_menu.add_command(label="Place Name Generator",
                              command=self.cmd_names)
        plan_menu.add_separator()
        self.structure_menu = tk.Menu(plan_menu, tearoff=0)
        for key in structures.FRAMEWORK_ORDER:
            framework = structures.framework(key)
            self.structure_menu.add_command(
                label=framework.name,
                command=lambda k=key: self.cmd_set_structure(k),
            )
        plan_menu.add_cascade(label="Story Structure", menu=self.structure_menu)
        menubar.add_cascade(label="Plan", menu=plan_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        self.focus_var = tk.BooleanVar(value=bool(settings["focus_mode"]))
        view_menu.add_checkbutton(label="Focus Mode (dim other paragraphs)",
                                  accelerator="F11", variable=self.focus_var,
                                  command=self.cmd_toggle_focus)
        self.typewriter_var = tk.BooleanVar(value=bool(settings["typewriter_scroll"]))
        view_menu.add_checkbutton(label="Typewriter Scrolling",
                                  variable=self.typewriter_var,
                                  command=self.cmd_toggle_typewriter)
        self.ghost_var = tk.BooleanVar(value=False)
        view_menu.add_checkbutton(label="Ghost Mode (hide what you type)",
                                  variable=self.ghost_var,
                                  command=self.cmd_toggle_ghost)
        view_menu.add_command(label="Distraction Free (hide side panes)",
                              accelerator="F12",
                              command=self.cmd_toggle_distraction_free)
        view_menu.add_separator()
        view_menu.add_command(label="Bigger Text", accelerator="Ctrl+=",
                              command=lambda: self.cmd_font_size(1))
        view_menu.add_command(label="Smaller Text", accelerator="Ctrl+-",
                              command=lambda: self.cmd_font_size(-1))
        view_menu.add_separator()
        self.theme_menu = tk.Menu(view_menu, tearoff=0)
        for name in THEMES:
            self.theme_menu.add_command(
                label=name.title(), command=lambda n=name: self.cmd_theme(n)
            )
        view_menu.add_cascade(label="Theme", menu=self.theme_menu)
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Command Palette...",
                              accelerator="Ctrl+Shift+P",
                              command=self.cmd_palette)
        help_menu.add_command(label="How to Use This", command=self.cmd_readme)
        help_menu.add_command(label="Keyboard Shortcuts", command=self.cmd_shortcuts)
        help_menu.add_command(label="Dialogue Rules Reference",
                              command=self.cmd_dialogue_rules)
        help_menu.add_command(label="Revision Checklist",
                              command=self.cmd_revision_checklist)
        help_menu.add_separator()
        help_menu.add_command(label=f"About {APP_NAME}", command=self.cmd_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self._refresh_recent()

    def _refresh_recent(self) -> None:
        self.recent_menu.delete(0, "end")
        found = list_projects()
        if not found:
            self.recent_menu.add_command(label="(none yet)", state="disabled")
            return
        for title, path in found[:15]:
            self.recent_menu.add_command(
                label=f"{title}",
                command=lambda p=path: self.load_project(p),
            )

    # ==================================================================
    # Layout
    # ==================================================================

    def _build_layout(self) -> None:
        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.grid(row=1, column=0, sticky="ew")
        self.toolbar = toolbar
        self.icons = styling.IconSet(self, self.ui_scale)
        self._toolbar_buttons: List[Tuple[ttk.Button, str, str]] = []
        self._toolbar_compact = False
        self._toolbar_fit_job: Optional[str] = None
        self._toolbar_full_width = 0

        # Grouped by what they are for - write, review, work - with a hairline
        # between groups, and a tooltip on each that names the shortcut so the
        # keyboard route is discoverable without opening the Help window.
        groups = [
            [("New Scene", "new", self.cmd_add_scene,
              "Add a scene to the current chapter  (Ctrl+N)"),
             ("Save", "save", lambda: self.cmd_save(explicit=True),
              "Save now  (Ctrl+S)")],
            [("Compile", "compile", self.cmd_compile,
              "Build the whole manuscript as one Word document  (F5)"),
             ("Diagnose", "diagnose", lambda: self.cmd_diagnostics("scene"),
              "Check this scene for prose problems  (F7)"),
             ("Stats", "stats", self.cmd_dashboard,
              "Word counts, pace and deadline  (F9)")],
            [("Sprint", "sprint", self.cmd_sprint,
              "Start a timed writing sprint  (F6)"),
             ("Find", "find", self.cmd_search,
              "Search the whole novel  (Ctrl+F)"),
             ("Open in Word", "word", self.cmd_open_in_word,
              "Open the selected document in Word")],
        ]
        column = 0
        for group_index, group in enumerate(groups):
            if group_index:
                ttk.Separator(toolbar, orient="vertical").grid(
                    row=0, column=column, sticky="ns", padx=6, pady=4)
                column += 1
            for label, icon, command, tip in group:
                self._add_toolbar_button(column, label, icon, command, tip)
                column += 1
        toolbar.columnconfigure(column, weight=1)      # spacer
        column += 1

        # Two bars: the book overall, and today against the daily target.
        gauges = ttk.Frame(toolbar)
        gauges.grid(row=0, column=column, sticky="e", padx=(8, 8))
        self.gauge_frame = gauges
        self.book_gauge = Gauge(gauges, "Book")
        self.book_gauge.grid(row=0, column=0, sticky="w")
        self.day_gauge = Gauge(gauges, "Today")
        self.day_gauge.grid(row=1, column=0, sticky="w", pady=(2, 0))
        column += 1
        self._add_toolbar_button(
            column, "Commands", "commands", self.cmd_palette,
            "Find any command by typing  (Ctrl+Shift+P)")

        self.panes = ttk.PanedWindow(self, orient="horizontal")
        self.panes.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 4))
        self.rowconfigure(2, weight=1)
        self.columnconfigure(0, weight=1)

        # -- binder ------------------------------------------------------
        self.binder_frame = ttk.Frame(self.panes)
        self.binder_frame.rowconfigure(1, weight=1)
        self.binder_frame.columnconfigure(0, weight=1)

        binder_head = ttk.Frame(self.binder_frame)
        binder_head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(2, 8))
        binder_head.columnconfigure(0, weight=1)
        self.project_label = ttk.Label(binder_head, text="No novel open",
                                       style="Title.TLabel")
        self.project_label.grid(row=0, column=0, sticky="w")
        # The pace line ("averaging ... finishing about ...") used to sit in the
        # toolbar and was the first thing to be pushed off the edge on a small
        # screen. Under the title it can wrap instead.
        self.header_label = ttk.Label(binder_head, text="", style="Hint.TLabel",
                                      justify="left", wraplength=300)
        self.header_label.grid(row=1, column=0, sticky="w", pady=(2, 0))
        binder_head.bind(
            "<Configure>",
            lambda e: self.header_label.configure(
                wraplength=max(120, e.width - 6)))

        self.tree = ttk.Treeview(self.binder_frame, columns=("meta",), height=28,
                                 show="tree")
        self.tree.column("#0", width=250, anchor="w", stretch=True)
        self.tree.column("meta", width=78, anchor="e", stretch=False)
        self.tree.grid(row=1, column=0, sticky="nsew")
        tree_scroll = AutoScrollbar(self.binder_frame, orient="vertical",
                                    command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.grid(row=1, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Double-1>", self.on_tree_double)
        self.tree.bind("<Button-3>", self.on_tree_right_click)
        bind_tree_shortcuts(self.tree)
        self._configure_tree_tags()
        self.panes.add(self.binder_frame, weight=0)

        # -- centre ------------------------------------------------------
        self.centre = ttk.Frame(self.panes)
        self.centre.rowconfigure(1, weight=1)
        self.centre.columnconfigure(0, weight=1)

        head = ttk.Frame(self.centre, padding=(4, 2))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        self.centre_title = ttk.Label(head, text="", style="Title.TLabel")
        self.centre_title.grid(row=0, column=0, sticky="w")
        self.centre_meta = ttk.Label(head, text="", style="Status.TLabel")
        self.centre_meta.grid(row=0, column=1, sticky="e")

        self.editor = ScrolledText(self.centre, height=26, wrap="word")
        self.detail_text = ScrolledText(self.centre, height=26, wrap="word",
                                        font=("Consolas", 10))
        self.detail_text.set_readonly(True)

        # _apply_theme styles this pane, but it runs from _build_styles, which
        # happens before this widget exists - so at startup the dashboard and
        # every report pane kept Tk's default white until the writer happened
        # to change theme. Style it now, on the way in.
        _detail_palette = theme()
        self.detail_text.text.configure(
            background=_detail_palette["bg"], foreground=_detail_palette["fg"],
            insertbackground=_detail_palette["caret"],
            selectbackground=_detail_palette["select"],
        )

        self.editor.grid(row=1, column=0, sticky="nsew")
        add_editing_keys(self.editor.text)
        self.editor.text.bind("<Button-3>", self.on_editor_right_click)
        self.editor.text.bind("<Control-space>", self.cmd_complete)
        self._completion = None
        # The editor has its own richer right-click menu, so the checker's
        # plain one stands aside.
        self.editor.text.nf_owns_menu = True
        self.editor_check = WritingCheck(self.editor.text, self.lexicon,
                                         on_summary=self._on_check_summary)
        self._style_editor()
        self.editor.text.bind("<<Modified>>", self.on_editor_modified)
        self.editor.text.bind("<KeyRelease>", self.on_editor_key)
        self.editor.text.bind("<ButtonRelease-1>", lambda _e: self._schedule_focus())

        self.detail_buttons = ttk.Frame(self.centre, padding=(2, 4))

        self.panes.add(self.centre, weight=3)

        # -- inspector ---------------------------------------------------
        self.inspector_frame = ttk.Frame(self.panes)
        self.inspector_frame.rowconfigure(1, weight=1)
        self.inspector_frame.columnconfigure(0, weight=1)
        ttk.Label(self.inspector_frame, text="INSPECTOR",
                  style="Section.TLabel").grid(row=0, column=0, sticky="w",
                                               pady=(0, 2), padx=2)
        self.inspector = ScrollFrame(self.inspector_frame)
        self.inspector.grid(row=1, column=0, sticky="nsew")
        self.panes.add(self.inspector_frame, weight=1)

        self.status = StatusBar(self)
        self.status.grid(row=3, column=0, sticky="ew")
        self._build_menu_strip()


    # ------------------------------------------------------------------
    # The menu bar, drawn by the app
    # ------------------------------------------------------------------

    def _build_menu_strip(self) -> None:
        """
        A menu bar the theme can actually paint.

        Windows owns the real menu bar and offers Tk no way to recolour it, so
        it was a white strip across the top of every theme - the one thing left
        that made a dark palette look unfinished. This is the same menus, shown
        through flat menu buttons in the app's own chrome. The tk.Menu tree
        built in _build_menu is still the single source of truth: each button
        gets a `clone` (Tk's own mechanism, which tracks later changes to the
        original, so "Undo Rename" and Open Recent stay live), and the command
        palette still walks the original.
        """
        t = self.tokens
        old = getattr(self, "menu_strip", None)
        if old is not None:
            old.destroy()
        self.menu_strip = ttk.Frame(self, padding=(6, 2, 6, 0))
        self.menu_strip.grid(row=0, column=0, sticky="ew")

        bar = self.menubar
        last = bar.index("end")
        for index in range(last + 1 if last is not None else 0):
            if bar.type(index) != "cascade":
                continue
            source = bar.nametowidget(bar.entrycget(index, "menu"))
            self._theme_menu(source)
            button = tk.Menubutton(
                self.menu_strip, text=bar.entrycget(index, "label"),
                background=t["panel"], foreground=t["panel_fg"],
                activebackground=t["hover"], activeforeground=t["panel_fg"],
                relief="flat", borderwidth=0, padx=10, pady=4,
                font=(styling.UI_FONT, 9), takefocus=0,
            )
            clone = f"{button}.menu"
            self.tk.call(str(source), "clone", clone, "normal")
            button.configure(menu=clone)
            button.grid(row=0, column=index, padx=(0, 1))

    def _theme_menu(self, menu: tk.Menu) -> None:
        """Colour a menu and every menu hanging off it (before it is cloned)."""
        t = self.tokens
        menu.configure(
            background=t["raised"], foreground=t["panel_fg"],
            activebackground=t["row_select"], activeforeground=t["fg"],
            disabledforeground=t["dim"], selectcolor=t["accent"],
            borderwidth=1, relief="flat", activeborderwidth=0,
        )
        last = menu.index("end")
        for index in range(last + 1 if last is not None else 0):
            if menu.type(index) == "cascade":
                try:
                    self._theme_menu(menu.nametowidget(menu.entrycget(index, "menu")))
                except (tk.TclError, KeyError):
                    pass

    def _add_toolbar_button(self, column: int, label: str, icon: str,
                            command: Callable[[], None], tip: str) -> None:
        image = self.icons.get(icon, self.tokens["panel_fg"])
        button = ttk.Button(
            self.toolbar, text=label, command=command, style="Tool.TButton",
            image=image or "", compound="left" if image else "none",
        )
        button.grid(row=0, column=column, padx=(0, 2))
        styling.Tooltip(button, tip)
        self._toolbar_buttons.append((button, icon, label))

    def _refresh_toolbar_icons(self) -> None:
        """Icons are baked in a colour, so a theme change has to redraw them."""
        for button, icon, _label in self._toolbar_buttons:
            image = self.icons.get(icon, self.tokens["panel_fg"])
            if image:
                button.configure(image=image)

    def _fit_toolbar(self, _event=None) -> None:
        """Debounced: the toolbar resizes continuously while a window is dragged."""
        if self._toolbar_fit_job is None:
            self._toolbar_fit_job = self.after(60, self._apply_toolbar_fit)

    def _apply_toolbar_fit(self) -> None:
        """
        Icons only when the labels no longer fit.

        Compared against the width the full toolbar needed when it was built,
        not its current requested width, so switching modes cannot feed back
        into the decision and flicker. Needs the icon font: without icons a
        label-less button would be blank, so the labels stay.
        """
        self._toolbar_fit_job = None
        if not self._toolbar_full_width or not self.icons.available:
            return
        compact = self.toolbar.winfo_width() < self._toolbar_full_width
        if compact == self._toolbar_compact:
            return
        self._toolbar_compact = compact
        for button, _icon, label in self._toolbar_buttons:
            if compact:
                button.configure(text="", compound="image")
            else:
                button.configure(text=label, compound="left")

    def _bind_keys(self) -> None:
        bindings = {
            "<Control-s>": lambda _e: self.cmd_save(explicit=True),
            "<Control-S>": lambda _e: self.cmd_save(explicit=True),
            "<Control-n>": lambda _e: self.cmd_add_scene(),
            "<Control-Shift-N>": lambda _e: self.cmd_new_project(),
            "<Control-Shift-C>": lambda _e: self.cmd_add_chapter(),
            "<Control-o>": lambda _e: self.cmd_open_project(),
            "<Control-f>": lambda _e: self.cmd_search(),
            "<Control-h>": lambda _e: self.cmd_replace(),
            "<F2>": lambda _e: self.cmd_sync_from_disk(),
            "<Control-b>": lambda _e: self.cmd_backup(),
            "<Control-l>": lambda _e: self.cmd_outline_window(),
            "<Control-t>": lambda _e: self.cmd_timeline_window(),
            "<Control-m>": lambda _e: self.cmd_map_editor(),
            "<Control-Shift-M>": lambda _e: self.cmd_chapter_map(),
            "<Control-z>": self.cmd_undo,
            "<Control-y>": self.cmd_redo,
            "<Control-Shift-Z>": self.cmd_redo,
            # Works even with the caret in the editor, where plain Ctrl+Z
            # belongs to the text.
            "<Control-Alt-z>": lambda _e: self.cmd_undo(),
            "<Control-Alt-y>": lambda _e: self.cmd_redo(),
            "<Control-Shift-P>": lambda _e: self.cmd_palette(),
            "<Control-k>": lambda _e: self.cmd_corkboard(),
            "<Control-g>": lambda _e: self.cmd_story_graph(),
            "<Control-i>": lambda _e: self.cmd_idea_inbox(),
            "<F4>": lambda _e: self.cmd_verify_project(),
            "<Shift-F7>": lambda _e: self.cmd_writing_check(),
            "<F10>": lambda _e: self.cmd_continuity(),
            "<F5>": lambda _e: self.cmd_compile(),
            "<Shift-F5>": lambda _e: self.cmd_compile(quick=True),
            "<F6>": lambda _e: self.cmd_sprint(),
            "<F7>": lambda _e: self.cmd_diagnostics("scene"),
            "<F8>": lambda _e: self.cmd_craft_check(),
            "<F9>": lambda _e: self.cmd_dashboard(),
            "<F11>": lambda _e: self._flip_focus(),
            "<F12>": lambda _e: self.cmd_toggle_distraction_free(),
            "<Control-equal>": lambda _e: self.cmd_font_size(1),
            "<Control-plus>": lambda _e: self.cmd_font_size(1),
            "<Control-minus>": lambda _e: self.cmd_font_size(-1),
        }
        # Kept so the tests can check every shortcut is wired to something that
        # runs, without needing a keyboard focus that a test window may lack.
        self.shortcuts = bindings
        for sequence, handler in bindings.items():
            self.bind_all(sequence, handler)

    # ==================================================================
    # Startup
    # ==================================================================

    def _startup(self) -> None:
        last = settings["last_project"]
        if last and (Path(last) / "project.json").exists():
            self.load_project(Path(last))
            self._after_open()
            return
        found = list_projects()
        if found:
            self.load_project(found[0][1])
            self._after_open()
            return
        self.status.say("No novel yet. File > New Novel to begin.", 0)
        self._show_welcome()

    def _after_open(self) -> None:
        """
        Recover first, then go back to where the writer was.

        In that order: restoring the caret into a scene whose text is about to
        be replaced by a recovered version would put it in the wrong place.
        """
        self._offer_recovery()
        self._restore_position()
        self._sync_history_menu()

    def _show_welcome(self) -> None:
        """First run: no novel yet. See welcome.py."""
        from .welcome import WelcomeView

        if getattr(self, "welcome", None) is None:
            self.welcome = WelcomeView(self)
        self.welcome.show()
        self.refresh_counters()          # no novel: clears the counters, hides the gauges

    # ==================================================================
    # Project loading
    # ==================================================================

    def load_project(self, root: Path) -> None:
        self.commit_all()
        try:
            project = Project.open(root)
        except (ProjectError, OSError) as exc:
            messagebox.showerror("Could not open", str(exc), parent=self)
            return

        # The graph cache is keyed by project root, but a project reopened from
        # disk may have been edited in Word since it was last cached.
        from .. import storygraph

        storygraph.invalidate(project)

        self.project = project
        if getattr(self, "welcome", None) is not None:
            self.welcome.hide()
        self.tracker = stats.SessionTracker(project.data)
        settings["last_project"] = str(root)
        self.current_scene_id = ""
        self.selection_kind = self.selection_id = ""

        self.title(f"{project.data.title} - {APP_NAME}")
        self.project_label.configure(text=project.data.title)

        changed_scenes, changed_entities = project.sync_from_disk()
        if changed_scenes or changed_entities:
            self.status.say(
                f"Picked up {changed_scenes} scenes and {changed_entities} "
                f"sheets edited outside the app."
            )

        if settings["backup_on_open"]:
            self.after(400, lambda: self._silent_backup("open"))

        warning = backup.backup_age_warning(project)
        if warning:
            self.status.say(warning, 12)

        self.refresh_tree()
        self.refresh_counters()
        self._refresh_recent()
        self.cmd_dashboard(in_pane=True)

    def _silent_backup(self, reason: str) -> None:
        if not self.project:
            return
        path, message = backup.create_backup(self.project, reason=reason)
        if path:
            self.status.say(f"Auto-backup: {message}")

    def require_project(self) -> bool:
        if self.project:
            return True
        messagebox.showinfo(
            "No novel open",
            "Open or create a novel first (File menu).", parent=self,
        )
        return False

    # ==================================================================
    # Binder tree
    # ==================================================================

    def refresh_tree(self, reselect: bool = True) -> None:
        if not self.project:
            return
        data = self.project.data
        want = f"{self.selection_kind}:{self.selection_id}" \
            if self.selection_kind else ""
        opened = {
            iid for iid in self.tree.get_children("")
            if self.tree.item(iid, "open")
        }

        self.tree.delete(*self.tree.get_children())

        for group_key, group_label in GROUP_ORDER:
            node = f"group:{group_key}"

            if group_key == "manuscript":
                total = data.word_count
                self.tree.insert("", "end", iid=node, text=group_label,
                                 values=(f"{total:,}",), open=True,
                                 tags=("group",))
                for chapter in data.ordered_chapters():
                    scenes = data.scenes_in(chapter.id)
                    words = sum(s.word_count for s in scenes)
                    chapter_iid = f"chapter:{chapter.id}"
                    self.tree.insert(
                        node, "end", iid=chapter_iid, text=chapter.title,
                        values=(f"{words:,}",),
                        open=chapter_iid in opened or len(data.chapters) <= 3,
                        tags=() if chapter.include_in_compile else ("excluded",),
                    )
                    for scene in scenes:
                        tags = [f"status:{scene.status}"]
                        mark = ""
                        if not scene.include_in_compile:
                            mark = "  (excluded)"
                            tags = ["excluded"]
                        self.tree.insert(
                            chapter_iid, "end", iid=f"scene:{scene.id}",
                            text=f"{scene.title}{mark}",
                            values=(f"{scene.word_count:,}",),
                            tags=tuple(tags),
                        )
                continue

            if group_key == "beats":
                done = sum(1 for b in data.beats if b.done)
                self.tree.insert("", "end", iid=node, text=group_label,
                                 values=(f"{done}/{len(data.beats)}",),
                                 open=node in opened, tags=("group",))
                for beat in sorted(data.beats, key=lambda b: b.order):
                    self.tree.insert(
                        node, "end", iid=f"beat:{beat.key}", text=beat.name,
                        values=("✓" if beat.done else
                                ("•" if beat.answer else "")),
                        tags=("done",) if beat.done
                        else (() if beat.answer else ("muted",)),
                    )
                continue

            if group_key in ENTITY_TYPES:
                items = data.entities_of(group_key)
                self.tree.insert("", "end", iid=node, text=group_label,
                                 values=(str(len(items)),),
                                 open=node in opened, tags=("group",))
                for entity in items:
                    label = entity.name
                    tags: Tuple[str, ...] = ()
                    if entity.is_pov:
                        label = f"{label}  ◆"
                        tags = ("pov",)
                    self.tree.insert(node, "end", iid=f"entity:{entity.id}",
                                     text=label, values=(entity.role[:14],),
                                     tags=tags)
                continue

            if group_key == "notes":
                self.tree.insert("", "end", iid=node, text=group_label,
                                 values=(str(len(data.notes)),),
                                 open=node in opened, tags=("group",))
                for note in sorted(data.notes, key=lambda n: n.order):
                    self.tree.insert(node, "end", iid=f"note:{note.id}",
                                     text=note.title, values=(note.kind,))
                self._add_folder_docs(node, "notes",
                                      skip={n.docx for n in data.notes})
                continue

            if group_key == "timeline":
                events = self.project.ordered_events()
                self.tree.insert("", "end", iid=node, text=group_label,
                                 values=(str(len(events)),), open=node in opened,
                                 tags=("group",))
                for event in events:
                    self.tree.insert(node, "end", iid=f"event:{event.id}",
                                     text=event.title or "(untitled)",
                                     values=(event.story_date[:12],),
                                     tags=() if event.on_page else ("muted",))
                continue

            if group_key == "maps":
                from .. import mapmaker

                found = mapmaker.list_maps(self.project.folder("maps"))
                self.tree.insert("", "end", iid=node, text=group_label,
                                 values=(str(len(found)),), open=node in opened,
                                 tags=("group",))
                for name, path in found:
                    self.tree.insert(
                        node, "end", iid=f"mapfile:{self.project.rel(path)}",
                        text=name, values=("map",),
                    )
                # Exported .docx maps show up as ordinary documents.
                self._add_folder_docs(node, "maps")
                continue

            # world bible, publishing: plain document lists
            folder_key = {"world": "world", "publishing": "publishing"}[group_key]
            self.tree.insert("", "end", iid=node, text=group_label,
                             values=("",), open=node in opened, tags=("group",))
            self._add_folder_docs(node, folder_key)

        if reselect and want and self.tree.exists(want):
            self.tree.selection_set(want)
            self.tree.see(want)

    def _add_folder_docs(self, parent: str, folder_key: str,
                         skip: Optional[set] = None) -> None:
        if not self.project:
            return
        folder = self.project.folder(folder_key)
        skip_names = {Path(s).name for s in (skip or set())}
        try:
            paths = sorted(folder.glob("*.docx"))
        except OSError:
            return
        for path in paths:
            if path.name.startswith("~$") or path.name in skip_names:
                continue
            rel = self.project.rel(path)
            self.tree.insert(parent, "end", iid=f"doc:{rel}",
                             text=path.stem, values=("docx",),
                             tags=("muted",))

    def _selected_key(self) -> Tuple[str, str]:
        selection = self.tree.selection()
        if not selection:
            return "", ""
        raw = selection[0]
        kind, _, ident = raw.partition(":")
        return kind, ident

    def on_tree_select(self, _event=None) -> None:
        kind, ident = self._selected_key()
        if kind == self.selection_kind and ident == self.selection_id:
            return
        self.commit_all()
        self.selection_kind, self.selection_id = kind, ident
        self.render_selection()

    def on_tree_double(self, _event=None) -> None:
        kind, ident = self._selected_key()
        if kind in ("entity", "doc", "note"):
            self.cmd_open_in_word()
        elif kind == "mapfile":
            self.cmd_map_editor(self.project.abs(ident) if self.project else None)
        elif kind == "beat":
            self.cmd_outline_window()
        elif kind == "event":
            self.cmd_timeline_window()

    def on_tree_right_click(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        kind, ident = self._selected_key()

        menu = tk.Menu(self, tearoff=0)
        if kind == "scene":
            menu.add_command(label="Rename...", command=self.cmd_rename)
            menu.add_command(label="Move Up", command=lambda: self.cmd_move(-1))
            menu.add_command(label="Move Down", command=lambda: self.cmd_move(1))
            menu.add_command(label="Move to Chapter...",
                             command=self.cmd_move_to_chapter)
            menu.add_separator()
            menu.add_command(label="Open in Word", command=self.cmd_open_in_word)
            menu.add_command(label="Drafts...", command=self.cmd_drafts)
            menu.add_command(label="Versions...", command=self.cmd_snapshots)
            menu.add_command(label="Craft Check", command=self.cmd_craft_check)
            menu.add_command(label="What depends on this?",
                             command=self.cmd_dependencies)
            menu.add_separator()
            menu.add_command(label="Delete...", command=self.cmd_delete)
        elif kind == "chapter":
            menu.add_command(label="Add Scene", command=self.cmd_add_scene)
            menu.add_command(label="Rename...", command=self.cmd_rename)
            menu.add_command(label="Move Up", command=lambda: self.cmd_move(-1))
            menu.add_command(label="Move Down", command=lambda: self.cmd_move(1))
            menu.add_separator()
            menu.add_command(label="Delete...", command=self.cmd_delete)
        elif kind == "entity":
            menu.add_command(label="Open Sheet in Word",
                             command=self.cmd_open_in_word)
            menu.add_command(label="Rename...", command=self.cmd_rename)
            menu.add_command(label="Where is this mentioned?",
                             command=self.cmd_mentions)
            menu.add_command(label="Rebuild Sheet from Template",
                             command=self.cmd_rebuild_sheet)
            menu.add_separator()
            menu.add_command(label="Delete...", command=self.cmd_delete)
        elif kind in ("doc", "note"):
            menu.add_command(label="Open in Word", command=self.cmd_open_in_word)
            menu.add_command(label="Show in Explorer",
                             command=self.cmd_reveal_selected)
            if kind == "note":
                menu.add_command(label="Link to scenes and characters...",
                                 command=self.cmd_note_links)
                menu.add_separator()
                menu.add_command(label="Delete...", command=self.cmd_delete)
        elif kind == "group":
            menu.add_command(label="Show Folder in Explorer",
                             command=self.cmd_reveal_selected)
        else:
            return
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ==================================================================
    # Rendering the selection
    # ==================================================================

    def render_selection(self) -> None:
        kind, ident = self.selection_kind, self.selection_id
        if not self.project:
            return
        data = self.project.data

        if kind == "scene":
            scene = data.scene(ident)
            if scene:
                self._render_scene(scene)
                return
        if kind == "chapter":
            chapter = data.chapter(ident)
            if chapter:
                self._render_chapter(chapter)
                return
        if kind == "entity":
            entity = data.entity(ident)
            if entity:
                self._render_entity(entity)
                return
        if kind == "note":
            note = data.note(ident)
            if note:
                self._render_note(note)
                return
        if kind == "doc":
            self._render_document(ident)
            return
        if kind == "mapfile":
            self._render_map(ident)
            return
        if kind == "beat":
            beat = data.beat(ident)
            if beat:
                self._render_beat(beat)
                return
        if kind == "event":
            self._render_event(ident)
            return
        self.cmd_dashboard(in_pane=True)

    # -- scene ----------------------------------------------------------
    def _render_scene(self, scene) -> None:
        self.current_scene_id = scene.id
        self._show_editor()
        text = self.project.scene_text(scene.id)

        # A document that exists but cannot be read comes back as "". Loading
        # that into the editor and letting autosave run replaced the file with
        # an empty one thirty seconds later - the tool destroying prose it had
        # merely failed to parse. Refuse to edit it instead.
        path = self.project.abs(scene.docx) if scene.docx else None
        if (path is not None and path.exists() and not text.strip()
                and not docxio.prose_readable(path)):
            self.editor.set_value("")
            self.editor.set_readonly(True)
            self._editor_dirty = False
            self._unreadable_scene = scene.id
            messagebox.showwarning(
                "This scene could not be read",
                f"'{scene.title}' is on disk but could not be opened.\n\n"
                f"It may be open in Word, or damaged. Editing here is "
                f"disabled so nothing overwrites it. Try File > Versions to "
                f"recover an earlier copy.",
                parent=self,
            )
            self.centre_title.configure(text=f"{scene.title}  (unreadable)")
            self._build_scene_inspector(scene)
            return
        if getattr(self, "_unreadable_scene", "") == scene.id:
            self._unreadable_scene = ""
        self.editor.set_readonly(False)
        self._suppress_modified = True
        self.editor.set_value(text)
        self._suppress_modified = False
        self._editor_dirty = False
        self.status.set_state("saved")

        self.centre_title.configure(text=scene.title)
        self._update_centre_meta(scene)
        self._build_scene_inspector(scene)
        self._schedule_focus()
        # Loading text does not raise a key event, so the check has to be
        # asked for - otherwise a scene only gets marked up once you type in
        # it, which reads as "the checker is not working".
        self._schedule_writing_check()
        self.editor.text.focus_set()

    def _update_centre_meta(self, scene) -> None:
        words = diagnostics.words_of(self.editor.get_value())
        target = f" / {scene.target_words:,}" if scene.target_words else ""
        self.centre_meta.configure(
            text=f"{len(words):,}{target} words   {scene.status}   "
                 f"{stats.reading_time(len(words))}"
        )

    def _build_scene_inspector(self, scene) -> None:
        data = self.project.data
        self.inspector.clear()
        self.inspector.scroll_to_top()
        form = Form(self.inspector.body, self.lexicon)
        self._form = form

        form.heading("Scene")
        form.entry("Title", scene, "title")
        form.multiline("Synopsis", scene, "synopsis", height=3)
        form.hint("One or two sentences. This is the index card.")
        form.combo("Status", scene, "status", SCENE_STATUSES)
        form.combo("Type", scene, "scene_type", SCENE_TYPES)
        form.check("Include when compiling", scene, "include_in_compile")
        form.integer("Word target", scene, "target_words")

        characters = [(e.id, e.name) for e in data.entities_of("character")]
        locations = [(e.id, e.name) for e in data.entities_of("location")]
        items = [(e.id, e.name) for e in data.entities_of("item")]
        factions = [(e.id, e.name) for e in data.entities_of("faction")]
        threads = [(e.id, e.name) for e in data.entities_of("thread")]

        form.heading("Links")
        if characters:
            form.picker("POV character", scene, "pov_id", characters)
            form.multipicker("Present", scene, "character_ids", characters)
        else:
            form.hint("Add characters (Add menu) to link them here.")
        if locations:
            form.multipicker("Locations", scene, "location_ids", locations, 4)
        if threads:
            form.multipicker("Plot threads", scene, "thread_ids", threads, 4)
        if items:
            form.multipicker("Items", scene, "item_ids", items, 3)
        if factions:
            form.multipicker("Factions", scene, "faction_ids", factions, 3)

        if scene.scene_type == "scene":
            form.heading("Scene: Goal / Conflict / Disaster")
            for attr, label, hint in structures.SCENE_UNIT:
                form.multiline(label, scene, attr, height=2)
                form.hint(hint)
        else:
            form.heading("Sequel: Reaction / Dilemma / Decision")
            for attr, label, hint in structures.SEQUEL_UNIT:
                form.multiline(label, scene, attr, height=2)
                form.hint(hint)

        form.heading("Value Shift")
        form.entry("Starts as", scene, "value_start")
        form.entry("Ends as", scene, "value_end")
        form.hint("If these are the same, nothing changed - and a scene where "
                  "nothing changes is an episode.")

        form.heading("Chronology")
        form.entry("Story date", scene, "story_date")
        form.entry("Time span", scene, "time_span")

        form.heading("Notes")
        form.multiline("Scene notes", scene, "notes", height=4)

        drafts = self.project.list_drafts(scene.id)
        research = self.project.notes_for(scene.id)
        if len(drafts) > 1 or research:
            form.separator()
            if len(drafts) > 1:
                form.readonly("Draft",
                              f"{scene.active_draft or 'Main'} "
                              f"(of {len(drafts)})")
            if research:
                form.readonly("Research",
                              ", ".join(n.title for n in research))

        form.button_row([
            ("Apply", self.cmd_apply_inspector),
            ("Craft check", self.cmd_craft_check),
            ("Drafts...", self.cmd_drafts),
            ("Open in Word", self.cmd_open_in_word),
        ])

    # -- chapter --------------------------------------------------------
    def _render_chapter(self, chapter) -> None:
        self.current_scene_id = ""
        scenes = self.project.data.scenes_in(chapter.id)
        words = sum(s.word_count for s in scenes)
        lines = [
            f"{len(scenes)} scenes, {words:,} words, "
            f"about {stats.reading_time(words)} of reading.",
            "",
        ]
        for scene in scenes:
            pov = self.project.data.entity(scene.pov_id)
            lines.append(
                f"  {scene.title:<40s} {scene.word_count:>6,}  "
                f"{scene.status:<11s} {pov.name if pov else ''}"
            )
            if scene.synopsis:
                lines.append(f"      {scene.synopsis}")
        if not scenes:
            lines.append("  No scenes yet. Add > Scene, or Ctrl+N.")

        self._show_detail(chapter.title, "\n".join(lines), [
            ("Add Scene", self.cmd_add_scene),
            ("Rename", self.cmd_rename),
            ("Show Folder", self.cmd_reveal_selected),
        ])
        self.centre_meta.configure(text=f"{words:,} words")

        self.inspector.clear()
        form = Form(self.inspector.body, self.lexicon)
        self._form = form
        form.heading("Chapter")
        form.entry("Title", chapter, "title")
        form.entry("Part / Book", chapter, "part")
        form.multiline("Synopsis", chapter, "synopsis", height=4)
        form.combo("Status", chapter, "status", SCENE_STATUSES)
        form.check("Include when compiling", chapter, "include_in_compile")
        form.check("Number this chapter", chapter, "number_in_compile")
        form.multiline("Notes", chapter, "notes", height=5)
        form.button_row([("Apply", self.cmd_apply_inspector)])

    # -- entity ---------------------------------------------------------
    def _render_entity(self, entity) -> None:
        self.current_scene_id = ""
        fields = self.project.entity_fields(entity.id)
        filled = sum(1 for v in fields.values() if v.strip())

        lines = [
            f"{entity.type.title()}  -  {filled} of {len(fields)} fields filled.",
            "",
            "The full sheet lives in Word. Double-click this item, or press",
            "'Open in Word', to fill it in. Changes come back automatically.",
            "",
        ]
        if fields:
            lines.append("-" * 60)
            for key, value in fields.items():
                if value.strip():
                    flat = value.replace("\n", "  |  ")
                    lines.append(f"{key}:")
                    lines.append(f"    {flat}")
            if filled == 0:
                lines.append("Nothing filled in yet.")

        self._show_detail(entity.name, "\n".join(lines), [
            ("Open in Word", self.cmd_open_in_word),
            ("Where mentioned?", self.cmd_mentions),
            ("Rebuild sheet", self.cmd_rebuild_sheet),
        ])
        self.centre_meta.configure(text=f"{filled}/{len(fields)} fields")

        self.inspector.clear()
        form = Form(self.inspector.body, self.lexicon)
        self._form = form
        form.heading(entity.type.title())
        form.entry("Name", entity, "name")
        if entity.type == "character":
            form.combo("Role", entity, "role", CHARACTER_ROLES)
            form.check("POV character", entity, "is_pov")
        else:
            form.entry("Type", entity, "role")
        form.multiline("One-line summary", entity, "summary", height=3)

        scenes_with = [
            s for s in self.project.data.ordered_scenes()
            if entity.id in (s.character_ids + s.location_ids + s.item_ids
                             + s.faction_ids + s.thread_ids)
            or s.pov_id == entity.id
        ]
        form.separator()
        form.readonly("Linked scenes", str(len(scenes_with)))
        if entity.type == "character":
            pov_scenes = [s for s in self.project.data.scenes
                          if s.pov_id == entity.id]
            form.readonly("POV scenes", str(len(pov_scenes)))
            form.readonly("Words in POV",
                          f"{sum(s.word_count for s in pov_scenes):,}")
        if entity.aliases:
            form.readonly("Aliases", ", ".join(entity.aliases))
        research = self.project.notes_for(entity.id)
        if research:
            form.readonly("Research", ", ".join(n.title for n in research))
        form.button_row([
            ("Apply", self.cmd_apply_inspector),
            ("Open in Word", self.cmd_open_in_word),
        ])

    # -- note -----------------------------------------------------------
    def _render_note(self, note) -> None:
        self.current_scene_id = ""
        from .. import docxio

        text = docxio.read_prose(self.project.abs(note.docx)) \
            if note.docx else ""
        self._show_detail(note.title, text or "(empty note)", [
            ("Open in Word", self.cmd_open_in_word),
            ("Show in Explorer", self.cmd_reveal_selected),
        ])
        self.centre_meta.configure(text=note.kind)
        self.inspector.clear()
        form = Form(self.inspector.body, self.lexicon)
        self._form = form
        form.heading("Note")
        form.entry("Title", note, "title")
        form.combo("Kind", note, "kind", ["note", "research", "scratchpad"])
        form.separator()
        linked = [
            (self.project.data.entity(t) or self.project.data.scene(t)
             or self.project.data.chapter(t))
            for t in (note.links or [])
        ]
        form.readonly(
            "Linked to",
            ", ".join(item.display for item in linked if item) or "nothing yet",
        )
        form.button_row([
            ("Apply", self.cmd_apply_inspector),
            ("Link to...", self.cmd_note_links),
        ])

    # -- plain document -------------------------------------------------
    def _render_document(self, relative: str) -> None:
        self.current_scene_id = ""
        from .. import docxio

        path = self.project.abs(relative)
        fields = docxio.read_field_sheet(path)
        if fields:
            filled = sum(1 for v in fields.values() if v.strip())
            lines = [f"{filled} of {len(fields)} fields filled.", ""]
            for key, value in fields.items():
                if value.strip():
                    lines.append(f"{key}:")
                    lines.append(f"    {value.replace(chr(10), '  |  ')}")
            if filled == 0:
                lines += ["Nothing filled in yet.", "",
                          "Open it in Word and start typing."]
            body = "\n".join(lines)
            meta = f"{filled}/{len(fields)} fields"
        else:
            body = docxio.read_prose(path) or "(empty document)"
            meta = f"{docxio.word_count(body):,} words"

        self._show_detail(path.stem, body, [
            ("Open in Word", self.cmd_open_in_word),
            ("Show in Explorer", self.cmd_reveal_selected),
        ])
        self.centre_meta.configure(text=meta)
        self.inspector.clear()
        form = Form(self.inspector.body, self.lexicon)
        self._form = None
        form.heading("Document")
        form.readonly("File", path.name)
        form.readonly("Folder", path.parent.name)
        try:
            size = path.stat().st_size / 1024
            when = datetime.fromtimestamp(path.stat().st_mtime)
            form.readonly("Size", f"{size:.0f} KB")
            form.readonly("Modified", when.strftime("%d %b %Y  %H:%M"))
        except OSError:
            pass
        form.hint("This document is edited in Word. The app reads it back "
                  "whenever it changes.")

    # -- map ------------------------------------------------------------
    def _render_map(self, relative: str) -> None:
        self.current_scene_id = ""
        from .. import mapmaker

        path = self.project.abs(relative)
        gm = mapmaker.load_map(path)
        if not gm:
            self._show_detail(path.name, "This map file could not be read.", [])
            return

        counts: Dict[str, int] = {}
        for shape in gm.shapes:
            counts[shape.kind] = counts.get(shape.kind, 0) + 1

        lines = [
            f"{mapmaker.MAP_KINDS.get(gm.kind, gm.kind)}   "
            f"{mapmaker.STYLES.get(gm.style, {}).get('label', gm.style)}   "
            f"{gm.width} x {gm.height}",
            "",
        ]
        if gm.scale_text:
            lines.append(f"Scale: {gm.scale_text}")
        lines += [
            f"{len(gm.shapes)} shapes, {len(gm.pins)} pins, "
            f"{len(gm.labels)} labels, {len(gm.layers)} layers",
            "",
        ]
        if counts:
            lines.append("TERRAIN")
            for kind, count in sorted(counts.items(), key=lambda kv: -kv[1]):
                label = mapmaker.TERRAIN.get(kind, {}).get("label", kind)
                lines.append(f"    {count:>3} x {label}")
            lines.append("")
        if gm.pins:
            lines.append("PLACES")
            for pin in sorted(gm.pins, key=lambda p: (p.kind, p.label.lower())):
                linked = self.project.data.entity(pin.entity_id)
                tail = f"   -> {linked.name}" if linked else ""
                lines.append(
                    f"    {mapmaker.PIN_KINDS.get(pin.kind, pin.kind):<16s} "
                    f"{pin.label or '(unnamed)'}{tail}"
                )
            lines.append("")
        if gm.notes.strip():
            lines += ["NOTES", "", gm.notes, ""]
        lines += ["Press Open Map Maker to draw on it."]

        self._show_detail(gm.name, "\n".join(lines), [
            ("Open Map Maker", lambda: self.cmd_map_editor(path)),
            ("Show in Explorer", self.cmd_reveal_selected),
        ])
        self.centre_meta.configure(
            text=f"{len(gm.pins)} pins   {gm.width}x{gm.height}"
        )

        self.inspector.clear()
        form = Form(self.inspector.body, self.lexicon)
        self._form = None
        form.heading("Map")
        form.readonly("Name", gm.name)
        form.readonly("Type", mapmaker.MAP_KINDS.get(gm.kind, gm.kind))
        form.readonly("Style", mapmaker.STYLES.get(gm.style, {}).get("label", gm.style))
        form.readonly("Size", f"{gm.width} x {gm.height}")
        form.readonly("Shapes", str(len(gm.shapes)))
        form.readonly("Pins", str(len(gm.pins)))
        linked = sum(1 for p in gm.pins if p.entity_id)
        form.readonly("Linked to sheets", f"{linked} of {len(gm.pins)}")
        form.separator()
        form.hint("Maps are edited in the Map Maker (Ctrl+M). Export to PNG, "
                  "SVG, or a Word document with a legend.")

    # -- beat -----------------------------------------------------------
    def _render_beat(self, beat) -> None:
        self.current_scene_id = ""
        data = self.project.data
        target = beat.target_word(data.targets.total_words)
        lines = [
            beat.prompt, "",
            f"Position: {int(beat.pct * 100)}% of the manuscript"
            if beat.pct is not None else "Position: not fixed",
        ]
        if target:
            lines.append(f"Target word: around {target:,}")
        lines += ["", "YOUR PLAN", "", beat.answer or "(nothing written yet)"]
        if beat.scene_ids:
            lines += ["", "SCENES COVERING THIS BEAT", ""]
            for scene_id in beat.scene_ids:
                scene = data.scene(scene_id)
                if scene:
                    lines.append(f"  {scene.title}  ({scene.word_count:,} words)")

        self._show_detail(beat.name, "\n".join(lines), [
            ("Edit in Outline", self.cmd_outline_window),
        ])
        self.centre_meta.configure(text="written" if beat.done else "not written")
        self.inspector.clear()
        form = Form(self.inspector.body, self.lexicon)
        self._form = form
        form.heading("Beat")
        form.readonly("Beat", beat.name)
        form.multiline("Plan", beat, "answer", height=8)
        form.check("Written", beat, "done")
        form.button_row([
            ("Apply", self.cmd_apply_inspector),
            ("Outline window", self.cmd_outline_window),
        ])

    # -- event ----------------------------------------------------------
    def _render_event(self, event_id: str) -> None:
        self.current_scene_id = ""
        data = self.project.data
        event = next((e for e in data.events if e.id == event_id), None)
        if not event:
            return
        who = ", ".join((data.entity(c).name if data.entity(c) else "?")
                        for c in event.character_ids)
        location = data.entity(event.location_id)
        scene = data.scene(event.scene_id)
        lines = [
            f"When: {event.story_date or '(unset)'}",
            f"Kind: {event.kind}",
            f"Visibility: {'on the page' if event.on_page else 'backstory'}",
            f"Who: {who or '-'}",
            f"Where: {location.name if location else '-'}",
            f"Scene: {scene.title if scene else '-'}",
            "", event.description or "(no description)",
        ]
        self._show_detail(event.title, "\n".join(lines), [
            ("Edit in Timeline", self.cmd_timeline_window),
        ])
        self.centre_meta.configure(text=event.story_date)
        self.inspector.clear()
        form = Form(self.inspector.body, self.lexicon)
        self._form = form
        form.heading("Event")
        form.entry("Title", event, "title")
        form.entry("When", event, "story_date")
        form.multiline("Description", event, "description", height=5)
        form.check("On the page", event, "on_page")
        form.button_row([
            ("Apply", self.cmd_apply_inspector),
            ("Timeline window", self.cmd_timeline_window),
        ])

    # -- view swapping --------------------------------------------------
    def _show_editor(self) -> None:
        self.detail_text.grid_remove()
        self.detail_buttons.grid_remove()
        self.editor.grid(row=1, column=0, sticky="nsew")

    def _show_detail(self, title: str, body: str,
                     actions: List[Tuple[str, Callable[[], None]]]) -> None:
        self.editor.grid_remove()
        self.detail_text.grid(row=1, column=0, sticky="nsew")
        self.detail_text.set_report(body)
        self.centre_title.configure(text=title)

        for child in self.detail_buttons.winfo_children():
            child.destroy()
        if actions:
            for index, (label, command) in enumerate(actions):
                ttk.Button(self.detail_buttons, text=label,
                           command=command).grid(row=0, column=index, padx=(0, 4))
            self.detail_buttons.grid(row=2, column=0, sticky="w")
        else:
            self.detail_buttons.grid_remove()

    # ==================================================================
    # Editor behaviour
    # ==================================================================

    def on_editor_modified(self, _event=None) -> None:
        if self._suppress_modified:
            return
        if not self.editor.text.edit_modified():
            return
        self._suppress_modified = True
        self.editor.text.edit_modified(False)
        self._suppress_modified = False

        if not self.current_scene_id:
            return
        self._editor_dirty = True
        self.status.set_state("dirty")
        self._schedule_autosave()
        self._schedule_journal()
        self._schedule_count()
        self._schedule_writing_check()

    def on_editor_key(self, event=None) -> None:
        if self.typewriter_var.get():
            self._typewriter_scroll()
        self._schedule_focus()

    def _schedule_autosave(self) -> None:
        if self._autosave_job:
            try:
                self.after_cancel(self._autosave_job)
            except (ValueError, tk.TclError):
                pass
        delay = max(5, int(settings["autosave_seconds"])) * 1000
        self._autosave_job = self.after(delay, self._autosave)

    def _autosave(self) -> None:
        self._autosave_job = None
        if self._editor_dirty and self.current_scene_id:
            self.save_editor(snapshot=False)
            self.status.say("Autosaved.", 3)

    # ------------------------------------------------------------------
    # Crash recovery journal
    # ------------------------------------------------------------------

    def _schedule_journal(self) -> None:
        """
        Write the recovery journal a couple of seconds after typing stops.

        Rescheduled on every keystroke, so continuous typing writes it once
        rather than on every character. It is a few kilobytes of JSON, not a
        Word document, so this is cheap enough to do far more often than
        autosave - which is the whole point: autosave every thirty seconds
        still loses thirty seconds.
        """
        if self._journal_job:
            try:
                self.after_cancel(self._journal_job)
            except (ValueError, tk.TclError):
                pass
        self._journal_job = self.after(1500, self._write_journal)

    def _write_journal(self) -> None:
        self._journal_job = None
        if not self.project:
            return
        try:
            scene = (self.project.data.scene(self.current_scene_id)
                     if self.current_scene_id else None)
            mtime = 0.0
            if scene and scene.docx:
                try:
                    mtime = self.project.abs(scene.docx).stat().st_mtime
                except OSError:
                    mtime = 0.0
            try:
                cursor = self.editor.text.index("insert")
                scroll = self.editor.text.yview()[0]
            except tk.TclError:
                cursor, scroll = "1.0", 0.0
            recovery.save(recovery.Session(
                project_root=str(self.project.root),
                scene_id=self.current_scene_id,
                scene_docx=scene.docx if scene else "",
                text=self.editor.get_value() if self.current_scene_id else "",
                dirty=bool(self._editor_dirty),
                cursor=cursor,
                scroll=float(scroll),
                docx_mtime=mtime,
                distraction_free=self._distraction_free,
                focus_mode=bool(settings["focus_mode"]),
                binder_selection=(self.tree.selection()[0]
                                  if self.tree.selection() else ""),
            ))
        except Exception:
            # The journal is a safety net. If it fails, writing carries on.
            pass

    def _offer_recovery(self) -> None:
        """On start-up, give back anything the last session did not save."""
        if not self.project:
            return
        try:
            pending = recovery.pending(self.project)
        except Exception:
            pending = None
        if pending is None:
            return
        if not messagebox.askyesno("Recover unsaved writing",
                                   pending.summary, parent=self):
            self.status.say("Recovery declined. The journal has been cleared.",
                            8)
            recovery.mark_clean_exit()
            return
        try:
            recovery.restore(self.project, pending)
        except Exception as exc:
            messagebox.showerror("Could not recover", str(exc), parent=self)
            return
        recovery.mark_clean_exit()
        self.refresh_tree()
        self.tree.selection_set(f"scene:{pending.session.scene_id}")
        self.render_selection()
        self.status.say(
            f"Recovered {pending.extra_words:,} words. The previous version "
            f"was kept next to the document.", 12)

    def _restore_position(self) -> None:
        """Put the writer back where they were: scene, caret and scroll."""
        session = recovery.load()
        if not session or not self.project:
            return
        try:
            if Path(session.project_root).resolve() != self.project.root.resolve():
                return
        except OSError:
            return
        if not session.scene_id or not self.project.data.scene(session.scene_id):
            return
        try:
            self.tree.selection_set(f"scene:{session.scene_id}")
            self.tree.see(f"scene:{session.scene_id}")
            self.render_selection()
            self.editor.text.mark_set("insert", session.cursor)
            self.editor.text.yview_moveto(session.scroll)
            self.editor.text.see("insert")
        except tk.TclError:
            pass
        if session.distraction_free and not self._distraction_free:
            self.cmd_toggle_distraction_free()

    def _schedule_count(self) -> None:
        if self._count_job:
            try:
                self.after_cancel(self._count_job)
            except (ValueError, tk.TclError):
                pass
        self._count_job = self.after(400, self._recount)

    def _recount(self) -> None:
        self._count_job = None
        if not (self.project and self.current_scene_id):
            return
        scene = self.project.data.scene(self.current_scene_id)
        if not scene:
            return
        live = len(diagnostics.words_of(self.editor.get_value()))
        target = f" / {scene.target_words:,}" if scene.target_words else ""
        self.centre_meta.configure(
            text=f"{live:,}{target} words   {scene.status}   "
                 f"{stats.reading_time(live)}"
        )
        others = self.project.data.word_count - scene.word_count
        self.refresh_counters(live_total=others + live)

    def _schedule_focus(self) -> None:
        if not self.focus_var.get():
            return
        if self._focus_job:
            try:
                self.after_cancel(self._focus_job)
            except (ValueError, tk.TclError):
                pass
        self._focus_job = self.after(140, self._apply_focus)

    def _apply_focus(self) -> None:
        self._focus_job = None
        text = self.editor.text
        try:
            text.tag_remove("dim", "1.0", "end")
            text.tag_remove("bright", "1.0", "end")
            if not self.focus_var.get():
                return
            text.tag_add("dim", "1.0", "end")
            start = text.index("insert linestart")
            end = text.index("insert lineend")
            # Widen to the whole paragraph (blank-line delimited).
            #
            # Both walks terminate naturally: Tk clamps "-1 line" at 1.0 and
            # "+1 line" at the end, so `previous == start` catches the edges.
            # The explicit cap is a second line of defence - this runs on a
            # keystroke timer, and a hang here would freeze the editor mid-
            # sentence. It also bounds the cost on a single enormous paragraph.
            MAX_LINES = 400
            for _ in range(MAX_LINES):
                previous = text.index(f"{start} -1 line linestart")
                if previous == start or not text.get(
                    previous, f"{previous} lineend"
                ).strip():
                    break
                start = previous
            for _ in range(MAX_LINES):
                following = text.index(f"{end} +1 line lineend")
                if following == end or not text.get(
                    f"{following} linestart", following
                ).strip():
                    break
                end = following
            text.tag_add("bright", start, end)
        except tk.TclError:
            pass

    def _typewriter_scroll(self) -> None:
        try:
            self.editor.text.see("insert")
            bbox = self.editor.text.bbox("insert")
            if not bbox:
                return
            height = self.editor.text.winfo_height()
            _x, y, _w, line_height = bbox
            middle = height // 2
            drift = y - middle
            if abs(drift) > line_height * 2:
                units = int(drift / max(1, line_height))
                self.editor.text.yview_scroll(units, "units")
        except tk.TclError:
            pass

    def save_editor(self, snapshot: bool = True) -> bool:
        if not (self.project and self.current_scene_id and self._editor_dirty):
            return False
        # Never write over a document we could not read. The editor is locked
        # for these, but the guard belongs here too: this is the function that
        # actually touches the file, and autosave reaches it on a timer.
        if getattr(self, "_unreadable_scene", "") == self.current_scene_id:
            self._editor_dirty = False
            return False
        scene = self.project.data.scene(self.current_scene_id)
        if not scene:
            return False
        body = self.editor.get_value()
        try:
            words = self.project.save_scene_text(scene.id, body, snapshot=snapshot)
        except FileBusyError as exc:
            self.status.say(str(exc), 15)
            return False
        except OSError as exc:
            self.status.say(f"Could not save: {exc}", 15)
            return False
        self._editor_dirty = False
        self.status.set_state("saved")
        if self.tracker:
            self.tracker.update(self.project.data.word_count, scene.id)
        item = f"scene:{scene.id}"
        if self.tree.exists(item):
            self.tree.item(item, values=(f"{words:,}",))
        chapter_item = f"chapter:{scene.chapter_id}"
        if self.tree.exists(chapter_item):
            chapter_words = sum(
                s.word_count for s in self.project.data.scenes_in(scene.chapter_id)
            )
            self.tree.item(chapter_item, values=(f"{chapter_words:,}",))
        if self.tree.exists("group:manuscript"):
            self.tree.item("group:manuscript",
                           values=(f"{self.project.data.word_count:,}",))
        self.refresh_counters()
        return True

    def commit_all(self) -> None:
        """Flush editor text and inspector fields. Call before any switch."""
        self.save_editor(snapshot=False)
        self.commit_inspector(refresh=False)

    def commit_inspector(self, refresh: bool = True) -> bool:
        if not self._form:
            return False
        try:
            changed = self._form.commit()
        except tk.TclError:
            return False
        if changed and self.project:
            self.project.mark_dirty()
            if refresh:
                self.refresh_tree()
                self.refresh_counters()
        return changed

    # ==================================================================
    # Status
    # ==================================================================

    @contextmanager
    def _busy(self, message: str):
        """
        Show a wait cursor and a status line around a slow synchronous action.

        Compiling a long novel or re-reading every document takes seconds.
        Without this the window simply stops responding and looks broken.
        """
        self.status.say(message, 0)
        try:
            self.configure(cursor="watch")
        except tk.TclError:
            pass
        self.update_idletasks()
        try:
            yield
        finally:
            try:
                self.configure(cursor="")
            except tk.TclError:
                pass
            self.update_idletasks()

    def refresh_counters(self, live_total: Optional[int] = None) -> None:
        if not self.project:
            self.status.set_counters("")
            self.header_label.configure(text="")
            if hasattr(self, "gauge_frame"):
                self.gauge_frame.grid_remove()
            for gauge in (getattr(self, "book_gauge", None),
                          getattr(self, "day_gauge", None)):
                if gauge is not None:
                    gauge.set(0, "")
            return
        data = self.project.data
        if not self.gauge_frame.winfo_ismapped():
            self.gauge_frame.grid()
        total = live_total if live_total is not None else data.word_count
        goal = data.targets.total_words
        bits = [f"{total:,} words"]
        if goal:
            bits.append(f"{total * 100 // max(1, goal)}% of {goal:,}")
        if self.tracker:
            session = self.tracker.added
            daily = data.targets.daily_words
            bits.append(f"today {session:,}" + (f"/{daily:,}" if daily else ""))
            if self.tracker.deleted:
                bits.append(f"cut {self.tracker.deleted:,}")
        run = stats.streak(data)
        if run:
            bits.append(f"streak {run}d")
        self.status.set_counters("     ".join(bits))

        projection = stats.Projection(data)
        self.header_label.configure(text=projection.pace_line())

        book_pct = min(100.0, total / goal * 100) if goal else 0
        self.book_gauge.set(book_pct, f"{book_pct:.0f}%" if goal else "no goal")
        daily = data.targets.daily_words
        if self.tracker and daily:
            added = self.tracker.added
            self.day_gauge.set(min(100.0, added / daily * 100),
                               f"{added:,} / {daily:,}")
        else:
            self.day_gauge.set(0, "" if daily else "no goal")

    # ==================================================================
    # Commands - project
    # ==================================================================

    def cmd_new_project(self) -> None:
        options = dialogs.NewProjectDialog(self).show()
        if not options:
            return
        self.commit_all()
        if self.project:
            self.project.save()
        packs = options.pop("packs", [])
        subtitle = options.pop("subtitle", "")
        series = options.pop("series", "")
        try:
            with self._busy("Creating folders and Word documents..."):
                project = Project.create(packs=packs, **options)
            if subtitle or series:
                project.data.subtitle = subtitle
                project.data.series = series
                project.save(force=True)
        except (ProjectError, OSError) as exc:
            self.status.say("")
            messagebox.showerror("Could not create", str(exc), parent=self)
            return
        self.load_project(project.root)
        count = len(list(project.root.rglob("*.docx")))
        self.status.say(f"Created '{project.data.title}' with {count} documents.", 12)
        if messagebox.askyesno(
            "Novel created",
            f"'{project.data.title}' is ready, with {count} Word documents.\n\n"
            f"Open the folder in Explorer?", parent=self,
        ):
            reveal_in_explorer(project.root)

    def cmd_open_project(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self, title="Choose a novel folder (the one holding project.json)",
            initialdir=str(projects_root()),
        )
        if chosen:
            self.load_project(Path(chosen))

    def cmd_save(self, explicit: bool = False) -> None:
        if not self.project:
            return
        self.commit_all()
        try:
            self.project.save(force=explicit)
        except FileBusyError as exc:
            messagebox.showwarning("File in use", str(exc), parent=self)
            return
        except OSError as exc:
            messagebox.showerror("Could not save", str(exc), parent=self)
            return
        if explicit:
            self.status.say("Saved.", 4)

    def cmd_sync_from_disk(self, force: bool = False) -> None:
        """
        Pick up edits made in Word.

        Unforced, this compares timestamps and only opens documents that
        actually changed - editing one scene in Word costs one file read, not
        two hundred. `force` re-reads everything, which is only needed if a
        clock or a sync client has left timestamps untrustworthy.
        """
        if not self.require_project():
            return
        self.commit_all()
        message = ("Re-reading every document..." if force
                   else "Checking for changes...")
        with self._busy(message):
            scenes, entities = self.project.sync_from_disk(force=force)
        self.refresh_tree()
        self.refresh_counters()
        if self.current_scene_id:
            scene = self.project.data.scene(self.current_scene_id)
            if scene:
                self._render_scene(scene)
        if scenes or entities:
            self.status.say(
                f"Updated {scenes} scenes and {entities} sheets from disk.", 8
            )
        else:
            self.status.say("Everything already up to date.", 5)

    def cmd_backup(self) -> None:
        if not self.require_project():
            return
        self.cmd_save()
        with self._busy("Backing up and verifying the archive..."):
            path, message = backup.create_backup(self.project, reason="manual")
        if path:
            self.status.say(message, 10)
        else:
            messagebox.showerror("Backup failed", message, parent=self)

    def cmd_backups(self) -> None:
        if not self.require_project():
            return
        self.cmd_save()
        dialogs.BackupsWindow(self, self.project)

    def cmd_snapshots(self) -> None:
        if not self.require_project():
            return
        path = self._selected_path()
        if not path:
            messagebox.showinfo("Pick a document",
                                "Select a scene or document first.", parent=self)
            return
        self.commit_all()
        dialog = dialogs.SnapshotsDialog(self, self.project, path, path.stem)
        if dialog.show():
            self.project.sync_from_disk(force=True)
            self.refresh_tree()
            if self.current_scene_id:
                scene = self.project.data.scene(self.current_scene_id)
                if scene:
                    self._render_scene(scene)
            self.status.say("Version restored.", 8)

    def cmd_project_settings(self) -> None:
        if not self.require_project():
            return
        self.commit_all()
        if dialogs.ProjectSettingsDialog(self, self.project).show():
            self.title(f"{self.project.data.title} - {APP_NAME}")
            self.project_label.configure(text=self.project.data.title)
            self.refresh_tree()
            self.refresh_counters()
            self.status.say("Project settings updated.", 5)

    def cmd_preferences(self) -> None:
        if dialogs.PreferencesDialog(self).show():
            self._apply_theme()
            self.focus_var.set(bool(settings["focus_mode"]))
            self.typewriter_var.set(bool(settings["typewriter_scroll"]))
            # Keep the Tools menu tick and the live marks in step with what
            # the dialog just wrote, or the two disagree until a restart.
            self.live_check_var.set(bool(settings["live_writing_check"]))
            if self.editor_check:
                if settings["live_writing_check"]:
                    self.editor_check.refresh()
                else:
                    self.editor_check.clear()
            self._apply_focus()
            self.render_selection()
            self.status.say("Preferences saved.", 5)

    def cmd_open_folder(self) -> None:
        if not self.require_project():
            return
        reveal_in_explorer(self.project.root)

    # ==================================================================
    # Commands - adding
    # ==================================================================

    def cmd_add_chapter(self) -> None:
        if not self.require_project():
            return
        self.commit_all()
        title = dialogs.TextPrompt(
            self, "New Chapter", "Chapter title",
            f"Chapter {len(self.project.data.chapters) + 1}",
            "A folder is created for this chapter's scene documents.",
        ).show()
        if not title:
            return
        chapter = self.project.add_chapter(title)
        self.project.save()
        self.refresh_tree()
        self.tree.selection_set(f"chapter:{chapter.id}")
        self.status.say(f"Added '{title}'.", 5)

    def cmd_add_scene(self) -> None:
        if not self.require_project():
            return
        self.commit_all()
        data = self.project.data
        if not data.chapters:
            self.cmd_add_chapter()
            if not data.chapters:
                return

        chapter_id = ""
        kind, ident = self.selection_kind, self.selection_id
        if kind == "chapter":
            chapter_id = ident
        elif kind == "scene":
            scene = data.scene(ident)
            chapter_id = scene.chapter_id if scene else ""
        if not chapter_id:
            chapter_id = data.ordered_chapters()[-1].id

        chapter = data.chapter(chapter_id)
        count = len(data.scenes_in(chapter_id))
        title = dialogs.TextPrompt(
            self, "New Scene",
            f"Scene title (in {chapter.title if chapter else 'chapter'})",
            f"Scene {count + 1}",
        ).show()
        if not title:
            return
        scene = self.project.add_scene(chapter_id, title)
        self.project.save()
        self.refresh_tree()
        self.tree.selection_set(f"scene:{scene.id}")
        self.status.say(f"Added '{title}'.", 5)

    def cmd_add_entity(self, entity_type: str) -> None:
        if not self.require_project():
            return
        self.commit_all()
        label = ENTITY_PLURAL[entity_type].rstrip("s") \
            if entity_type != "thread" else "Plot thread"
        name = dialogs.TextPrompt(
            self, f"New {label}", f"{label} name", "",
            "A Word sheet is created with every field worth recording.",
        ).show()
        if not name:
            return
        role = ""
        if entity_type == "character":
            role = dialogs.ChoiceDialog(
                self, "Role", f"What is {name}'s role in the story?",
                [(r, r) for r in CHARACTER_ROLES],
            ).show() or ""
        entity = self.project.add_entity(entity_type, name, role=role)
        self.project.save()
        self.refresh_tree()
        self.tree.selection_set(f"entity:{entity.id}")
        self.status.say(f"Created a sheet for '{name}'. "
                        f"Double-click to fill it in in Word.", 8)

    def cmd_add_note(self, kind: str) -> None:
        if not self.require_project():
            return
        self.commit_all()
        title = dialogs.TextPrompt(
            self, f"New {kind.title()}", "Title", "",
        ).show()
        if not title:
            return
        note = self.project.add_note(title, kind=kind)
        self.project.save()
        self.refresh_tree()
        self.tree.selection_set(f"note:{note.id}")

    def cmd_add_event(self) -> None:
        if not self.require_project():
            return
        self.commit_all()
        self.cmd_timeline_window()

    # ==================================================================
    # Commands - item operations
    # ==================================================================

    def _selected_path(self) -> Optional[Path]:
        if not self.project:
            return None
        kind, ident = self.selection_kind, self.selection_id
        data = self.project.data
        if kind == "scene":
            scene = data.scene(ident)
            return self.project.abs(scene.docx) if scene and scene.docx else None
        if kind == "entity":
            entity = data.entity(ident)
            return self.project.abs(entity.docx) if entity and entity.docx else None
        if kind == "note":
            note = data.note(ident)
            return self.project.abs(note.docx) if note and note.docx else None
        if kind in ("doc", "mapfile"):
            return self.project.abs(ident)
        if kind == "chapter":
            chapter = data.chapter(ident)
            return self.project.abs(chapter.folder) if chapter and chapter.folder \
                else None
        if kind == "group":
            # Every entry in GROUP_ORDER must appear here or selecting a group
            # header and pressing Open would raise a KeyError.
            mapping = {"manuscript": "manuscript", "world": "world",
                       "publishing": "publishing", "notes": "notes",
                       "timeline": "timeline", "beats": "outline",
                       "maps": "maps",
                       "character": "characters", "location": "locations",
                       "item": "items", "faction": "factions",
                       "thread": "threads"}
            key = mapping.get(ident)
            return self.project.folder(key) if key else self.project.root
        return None

    def cmd_open_in_word(self) -> None:
        if not self.require_project():
            return
        self.commit_all()
        self.project.save()
        path = self._selected_path()
        if not path or not path.exists():
            messagebox.showinfo(
                "Nothing to open",
                "Select a scene, sheet or document in the binder first.",
                parent=self,
            )
            return
        if path.is_dir():
            reveal_in_explorer(path)
            return
        if open_in_default_app(path):
            self.status.say(
                f"Opened {path.name} in Word. Use File > Reload from Word "
                f"when you come back.", 12
            )
        else:
            messagebox.showerror("Could not open",
                                 f"Windows would not open {path.name}.",
                                 parent=self)

    def cmd_reveal_selected(self) -> None:
        path = self._selected_path()
        if path:
            reveal_in_explorer(path)
        elif self.project:
            reveal_in_explorer(self.project.root)

    def cmd_rename(self) -> None:
        if not self.require_project():
            return
        self.commit_all()
        kind, ident = self.selection_kind, self.selection_id
        data = self.project.data
        current = ""
        if kind == "scene":
            scene = data.scene(ident)
            current = scene.title if scene else ""
        elif kind == "chapter":
            chapter = data.chapter(ident)
            current = chapter.title if chapter else ""
        elif kind == "entity":
            entity = data.entity(ident)
            current = entity.name if entity else ""
        elif kind == "note":
            note = data.note(ident)
            current = note.title if note else ""
        else:
            return

        new = dialogs.TextPrompt(
            self, "Rename", "New name", current,
            "The document file keeps its current filename; only the label "
            "shown here changes.",
        ).show()
        if not new or new == current:
            return
        with self.project.action(f"rename to '{new}'"):
            if kind == "scene":
                self.project.rename_scene(ident, new)
            elif kind == "chapter":
                self.project.rename_chapter(ident, new)
            elif kind == "entity":
                self.project.rename_entity(ident, new)
            elif kind == "note":
                note = data.note(ident)
                if note:
                    note.title = new
                    self.project.mark_dirty()
        self.project.save()
        self.refresh_tree()
        self.render_selection()
        self._sync_history_menu()

    def cmd_move(self, delta: int) -> None:
        if not self.require_project():
            return
        self.commit_all()
        kind, ident = self.selection_kind, self.selection_id
        if kind not in ("scene", "chapter"):
            return
        with self.project.action("move " + ("up" if delta < 0 else "down")):
            if kind == "scene":
                self.project.move_scene(ident, delta)
            else:
                self.project.move_chapter(ident, delta)
        self.project.save()
        self.refresh_tree()
        self._sync_history_menu()

    def cmd_move_to_chapter(self) -> None:
        if not self.require_project() or self.selection_kind != "scene":
            return
        self.commit_all()
        options = [(c.id, c.title) for c in self.project.data.ordered_chapters()]
        if len(options) < 2:
            messagebox.showinfo("Only one chapter",
                                "Add another chapter first.", parent=self)
            return
        chosen = dialogs.ChoiceDialog(
            self, "Move Scene", "Move this scene to which chapter?", options
        ).show()
        if not chosen:
            return
        with self.project.action("move scene to another chapter"):
            self.project.reassign_scene(self.selection_id, chosen)
        self.project.save()
        self.refresh_tree()
        self._sync_history_menu()

    def cmd_delete(self) -> None:
        if not self.require_project():
            return
        kind, ident = self.selection_kind, self.selection_id
        data = self.project.data
        label = ""
        if kind == "scene":
            scene = data.scene(ident)
            label = f"the scene '{scene.title}'" if scene else ""
        elif kind == "chapter":
            chapter = data.chapter(ident)
            count = len(data.scenes_in(ident)) if chapter else 0
            label = (f"the chapter '{chapter.title}' and its {count} scenes"
                     if chapter else "")
        elif kind == "entity":
            entity = data.entity(ident)
            label = f"the {entity.type} '{entity.name}'" if entity else ""
        elif kind == "note":
            note = data.note(ident)
            label = f"the note '{note.title}'" if note else ""
        if not label:
            return

        # Say what else breaks before the writer commits, not after. This is
        # the whole reason the dependency map exists: "delete chapter 8" is a
        # safe-looking action with consequences three hundred pages away.
        consequence = ""
        if kind == "scene":
            try:
                from .. import storygraph

                # Use the graph only if it is already built. Building it here
                # would read every scene document - twenty-five seconds on a
                # long novel - to decorate a confirmation box. A manifest-only
                # graph is instant and still catches declared links.
                graph = (storygraph.cached_graph(self.project)
                         or storygraph.build(self.project, read_prose=False,
                                             use_cache=False))
                consequence = storygraph.deletion_warning(
                    self.project, graph, ident)
            except Exception:
                consequence = ""
        if consequence:
            consequence = f"\n\nBefore you do:\n{consequence}\n"

        answer = messagebox.askyesnocancel(
            "Delete",
            f"Remove {label} from the project?{consequence}\n"
            f"Yes  - also delete the Word document(s) from disk\n"
            f"No   - keep the files, just remove them from the binder\n"
            f"Cancel - do nothing",
            parent=self,
        )
        if answer is None:
            return
        delete_files = bool(answer)

        with self.project.action(f"delete {label}"):
            if kind == "scene":
                self.project.delete_scene(ident, delete_files=delete_files)
                if self.current_scene_id == ident:
                    self.current_scene_id = ""
            elif kind == "chapter":
                self.project.delete_chapter(ident, delete_files=delete_files)
            elif kind == "entity":
                self.project.delete_entity(ident, delete_files=delete_files)
            elif kind == "note":
                self.project.delete_note(ident, delete_files=delete_files)

        self.selection_kind = self.selection_id = ""
        self._form = None
        self.project.save()
        self.refresh_tree()
        self.refresh_counters()
        self.cmd_dashboard(in_pane=True)
        self._sync_history_menu()
        self.status.say(
            "Removed. " + ("The documents are in the Trash folder, not gone."
                           if delete_files else "Files kept where they were.")
            + "  Ctrl+Z puts it back.", 10
        )

    def cmd_apply_inspector(self) -> None:
        if not self.project:
            return
        with self.project.action("that edit"):
            changed = self.commit_inspector()
        if changed:
            self.project.save()
            self.status.say("Applied.", 3)
            self.render_selection()
            self._sync_history_menu()
        else:
            self.status.say("Nothing changed.", 3)

    def cmd_rebuild_sheet(self) -> None:
        if not self.require_project():
            return
        if self.selection_kind != "entity":
            messagebox.showinfo(
                "Select a sheet",
                "Choose a character, location, item, faction or plot thread.",
                parent=self,
            )
            return
        self.commit_all()
        entity = self.project.data.entity(self.selection_id)
        if not entity:
            return
        if not messagebox.askyesno(
            "Rebuild sheet",
            f"Rewrite '{entity.name}' from the current template?\n\n"
            f"Everything you have typed is preserved and any new template "
            f"fields are added. Formatting changes you made in Word will be "
            f"lost.",
            parent=self,
        ):
            return
        try:
            path = self.project.rewrite_entity_sheet(entity.id)
        except ProjectError as exc:
            # Raised when the sheet could not be read: rewriting from an empty
            # read would have erased everything in it.
            messagebox.showwarning("Left untouched", str(exc), parent=self)
            return
        self.project.save()
        self.render_selection()
        self.status.say(f"Rebuilt {path.name if path else 'sheet'}.", 6)

    def cmd_mentions(self) -> None:
        if not self.require_project() or self.selection_kind != "entity":
            return
        self.commit_all()
        entity = self.project.data.entity(self.selection_id)
        if not entity:
            return
        with self._busy(f"Scanning the manuscript for {entity.name}..."):
            hits = self.project.find_mentions(entity.id)
        names = ", ".join(entity.all_names())
        lines = [
            f"Searching for: {names}", "",
        ]
        if hits:
            total = sum(count for _t, count in hits)
            lines.append(f"{total} mentions across {len(hits)} scenes.")
            lines.append("")
            for title, count in hits:
                lines.append(f"  {count:>4}  {title}")
        else:
            lines.append("Not mentioned by name in any scene yet.")
        linked = [
            s.title for s in self.project.data.ordered_scenes()
            if entity.id in (s.character_ids + s.location_ids + s.item_ids
                             + s.faction_ids + s.thread_ids)
            or s.pov_id == entity.id
        ]
        lines += ["", f"Linked in the inspector to {len(linked)} scenes:"]
        lines += [f"  {t}" for t in linked] or ["  (none)"]
        dialogs.ReportWindow(self, f"Mentions of {entity.name}",
                             "\n".join(lines), width=700, height=560)

    # ==================================================================
    # Commands - manuscript
    # ==================================================================

    def cmd_compile(self, quick: bool = False) -> None:
        if not self.require_project():
            return
        self.commit_all()
        self.project.save()
        data = self.project.data
        if not data.compile_scenes():
            messagebox.showinfo(
                "Nothing to compile",
                "No scenes are marked for compiling yet. Write a scene first.",
                parent=self,
            )
            return

        options = compiler.CompileOptions()
        if not quick:
            chosen = dialogs.CompileDialog(self, self.project).show()
            if not chosen:
                return
            options = compiler.CompileOptions(**chosen)

        count = len(data.compile_scenes())
        try:
            with self._busy(f"Compiling {count} scenes into one document..."):
                result = compiler.compile_manuscript(self.project, options)
        except FileBusyError as exc:
            self.status.say("")
            messagebox.showwarning(
                "Manuscript is open",
                f"{exc}\n\nThe compiled manuscript is open in Word. Close it "
                f"and compile again.", parent=self,
            )
            return
        except OSError as exc:
            self.status.say("")
            messagebox.showerror("Compile failed", str(exc), parent=self)
            return

        self.status.say(f"Compiled: {result.summary}", 12)
        message = (
            f"{result.path.name}\n\n{result.summary}\n\n"
            f"Saved in the _Compiled folder."
        )
        if result.skipped:
            message += f"\n\nExcluded on purpose: {', '.join(result.skipped[:6])}"
            if len(result.skipped) > 6:
                message += f" and {len(result.skipped) - 6} more"
        if result.missing:
            # Never let a scene disappear from the manuscript silently.
            message += (
                f"\n\nWARNING - {len(result.missing)} scenes could not be read "
                f"and are MISSING from the manuscript:\n"
                f"{', '.join(result.missing[:8])}"
            )
            if len(result.missing) > 8:
                message += f" and {len(result.missing) - 8} more"
            message += ("\n\nThey may be open in Word or still downloading "
                        "from OneDrive. Close Word and compile again.")
            self.status.say(
                f"Compiled, but {len(result.missing)} scenes were unreadable "
                f"and are missing.", 20
            )
        if messagebox.askyesno("Compiled", message + "\n\nOpen it in Word?",
                               parent=self):
            open_in_default_app(result.path)

    def cmd_open_compiled(self) -> None:
        if not self.require_project():
            return
        path = self.project.compiled_path
        if not path.exists():
            if messagebox.askyesno(
                "Not compiled yet",
                "There is no compiled manuscript yet. Compile now?",
                parent=self,
            ):
                self.cmd_compile()
            return
        open_in_default_app(path)

    def cmd_export_text(self) -> None:
        if not self.require_project():
            return
        self.commit_all()
        path, words = compiler.export_plain_text(self.project)
        self.status.say(f"Plain text written: {words:,} words -> {path.name}", 10)
        if messagebox.askyesno("Exported",
                               f"{path.name}\n{words:,} words\n\nOpen it?",
                               parent=self):
            open_in_default_app(path)

    def cmd_export_treatment(self) -> None:
        if not self.require_project():
            return
        self.commit_all()
        path = compiler.compile_outline_only(self.project)
        if messagebox.askyesno("Treatment written",
                               f"{path.name}\n\nOpen it in Word?", parent=self):
            open_in_default_app(path)

    def cmd_write_outline(self) -> None:
        if not self.require_project():
            return
        self.commit_all()
        path = self.project.write_outline_doc()
        if messagebox.askyesno("Outline written",
                               f"{path.name}\n\nOpen it in Word?", parent=self):
            open_in_default_app(path)

    def cmd_reverse_outline(self) -> None:
        if not self.require_project():
            return
        self.commit_all()
        path = self.project.write_reverse_outline()
        if messagebox.askyesno(
            "Reverse outline written",
            f"{path.name}\n\nThis is what you actually wrote, scene by scene. "
            f"Compare it with your Outline to see structural drift.\n\n"
            f"Open it in Word?", parent=self,
        ):
            open_in_default_app(path)

    def cmd_fix_later(self) -> None:
        if not self.require_project():
            return
        self.commit_all()
        with self._busy("Sweeping every scene for [bracket tags]..."):
            path, count = self.project.write_fix_later_doc()
        self.status.say(f"{count} open tags collected into {path.name}", 10)
        if count and messagebox.askyesno(
            "Fix Later",
            f"{count} open tags found.\n\nOpen the list in Word?", parent=self,
        ):
            open_in_default_app(path)
        elif not count:
            messagebox.showinfo("Fix Later",
                                "No [bracket tags] found in the manuscript.",
                                parent=self)

    def cmd_import_loose(self) -> None:
        if not self.require_project():
            return
        self.commit_all()
        added = self.project.import_loose_documents()
        self.project.save()
        self.refresh_tree()
        self.refresh_counters()
        if added:
            self.status.say(f"Adopted {added} loose .docx files as scenes.", 10)
        else:
            messagebox.showinfo(
                "Nothing to import",
                "No unrecognised .docx files were found in the chapter "
                "folders.\n\nTo import existing work, copy the files into a "
                "chapter folder under 00 Manuscript and run this again.",
                parent=self,
            )

    # ==================================================================
    # Commands - tools
    # ==================================================================

    def cmd_search(self) -> None:
        if not self.require_project():
            return
        self.commit_all()

        def open_result(kind: str, name: str) -> None:
            data = self.project.data
            if kind == "Scene":
                scene = next((s for s in data.scenes if s.title == name), None)
                if scene:
                    self.tree.selection_set(f"scene:{scene.id}")
                    self.tree.see(f"scene:{scene.id}")
                    return
            if kind == "Note":
                note = next((n for n in data.notes if n.title == name), None)
                if note:
                    self.tree.selection_set(f"note:{note.id}")
                    return
            entity = next((e for e in data.entities if e.name == name), None)
            if entity:
                item = f"entity:{entity.id}"
                if self.tree.exists(item):
                    self.tree.selection_set(item)
                    self.tree.see(item)

        dialogs.SearchWindow(self, self.project, open_result)

    def cmd_diagnostics(self, scope: str) -> None:
        if not self.require_project():
            return
        self.commit_all()
        from .. import docxio

        data = self.project.data
        if scope == "scene":
            if not self.current_scene_id:
                messagebox.showinfo("Select a scene",
                                    "Choose a scene in the binder first.",
                                    parent=self)
                return
            scene = data.scene(self.current_scene_id)
            text = self.editor.get_value()
            label = f"Diagnostics: {scene.title if scene else 'scene'}"
        elif scope == "chapter":
            scene = data.scene(self.current_scene_id)
            chapter_id = scene.chapter_id if scene else (
                self.selection_id if self.selection_kind == "chapter" else ""
            )
            chapter = data.chapter(chapter_id)
            if not chapter:
                messagebox.showinfo("Select a chapter",
                                    "Choose a chapter or one of its scenes.",
                                    parent=self)
                return
            chapter_scenes = [s for s in data.scenes_in(chapter.id) if s.docx]
            with self._busy(f"Reading {len(chapter_scenes)} scenes..."):
                text = "\n\n".join(
                    docxio.read_prose(self.project.abs(s.docx))
                    for s in chapter_scenes
                )
            label = f"Diagnostics: {chapter.title}"
        else:
            book_scenes = [s for s in data.compile_scenes() if s.docx]
            with self._busy(
                f"Reading all {len(book_scenes)} scenes - this takes a moment..."
            ):
                text = "\n\n".join(
                    docxio.read_prose(self.project.abs(s.docx))
                    for s in book_scenes
                )
            label = f"Diagnostics: {data.title}"

        self.status.say("")
        if not text.strip():
            messagebox.showinfo("Nothing written yet",
                                "There is no prose to analyse.", parent=self)
            return
        report = diagnostics.analyse(text)
        dialogs.ReportWindow(self, label, diagnostics.report_text(report, label))

    def cmd_craft_check(self) -> None:
        if not self.require_project():
            return
        self.commit_all()
        if not self.current_scene_id:
            messagebox.showinfo("Select a scene",
                                "Choose a scene in the binder first.",
                                parent=self)
            return
        scene = self.project.data.scene(self.current_scene_id)
        if not scene:
            return
        issues = diagnostics.scene_craft_check(scene)
        lines = [
            f"SCENE CRAFT CHECK - {scene.title}",
            "=" * 52, "",
            "This checks the scene's STRUCTURE, not its prose. It reads the",
            "inspector fields, so fill them in as you plan.", "",
        ]
        if issues:
            lines.append(f"{len(issues)} things to look at:")
            lines.append("")
            lines += [f"  {i}. {issue}" for i, issue in enumerate(issues, 1)]
        else:
            lines.append("Nothing flagged. This scene has a goal, opposition,")
            lines.append("a turn, a POV, a value shift and a thread. Good.")
        lines += [
            "", "-" * 52, "",
            "The pattern being checked is Dwight Swain's Scene and Sequel:",
            "", "  SCENE   Goal -> Conflict -> Disaster",
            "  SEQUEL  Reaction -> Dilemma -> Decision", "",
            "Alternating them is what produces pace. A run of scenes with no",
            "sequels exhausts a reader; a run of sequels stalls the book.",
        ]
        dialogs.ReportWindow(self, f"Craft check: {scene.title}",
                             "\n".join(lines), width=720, height=580)

    def cmd_dashboard(self, in_pane: bool = False) -> None:
        if not self.project:
            if not in_pane:
                self.require_project()
            return
        data = self.project.data
        projection = stats.Projection(data)
        lines = [
            data.title.upper(),
            "=" * max(12, len(data.title)),
            "",
        ]
        lines += stats.summary_lines(data)
        lines += [
            "",
            f"Last 30 days:  {stats.sparkline(data, 30)}",
            "",
            "-" * 60,
            "",
            "CHAPTERS",
            "",
        ]
        rows = stats.chapter_breakdown(data)
        if rows:
            for title, words, count, status in rows:
                bar = "#" * min(30, words // 400)
                lines.append(f"  {title[:26]:<26s} {words:>7,}  "
                             f"{count:>2} sc  {status:<11s} {bar}")
        else:
            lines.append("  No chapters yet.")

        lines += ["", "POINT OF VIEW", ""]
        pov = stats.pov_balance(data)
        if pov:
            for name, count, words, share in pov:
                lines.append(f"  {name[:26]:<26s} {count:>3} scenes  "
                             f"{words:>7,}  {share:>5.1f}%")
        else:
            lines.append("  No POV assigned yet.")

        lines += ["", "PLOT THREADS", ""]
        threads = stats.thread_coverage(data)
        if threads:
            for name, count, gap in threads:
                lines.append(f"  {name[:34]:<34s} {count:>3} scenes  "
                             f"largest gap {gap}")
            lines.append("")
            lines.append("  A thread absent for many consecutive scenes reads")
            lines.append("  to a reader as abandoned, even if you resolve it.")
        else:
            lines.append("  No plot threads defined.")

        if projection.deadline:
            lines += [
                "", "-" * 60, "", "DEADLINE", "",
                f"  Deadline      {projection.deadline.strftime('%d %B %Y')}",
                f"  Days left     {projection.days_left}",
                f"  Words left    {projection.remaining:,}",
                f"  Needed daily  {projection.required_daily:,}",
                f"  Your average  {projection.average:,.0f}",
            ]
            if projection.on_track is not None:
                lines.append(
                    "  Verdict       " + (
                        "on track" if projection.on_track
                        else "behind - raise the daily target or move the date"
                    )
                )

        body = "\n".join(lines)
        if in_pane:
            self._show_detail("Dashboard", body, [
                ("Compile", self.cmd_compile),
                ("Diagnose book", lambda: self.cmd_diagnostics("book")),
                ("Back up", self.cmd_backup),
            ])
            self.centre_meta.configure(text=projection.headline())
            self.inspector.clear()
            form = Form(self.inspector.body, self.lexicon)
            self._form = None
            form.heading("At a glance")
            form.readonly("Words", f"{data.word_count:,}")
            form.readonly("Target", f"{data.targets.total_words:,}")
            form.readonly("Progress", f"{projection.percent:.1f}%")
            form.readonly("Chapters", str(len(data.chapters)))
            form.readonly("Scenes", str(len(data.scenes)))
            form.readonly("Characters",
                          str(len(data.entities_of("character"))))
            form.readonly("Streak", f"{stats.streak(data)} days")
            form.readonly("Reading time", stats.reading_time(data.word_count))
            form.separator()
            form.hint("Select anything in the binder to start working. "
                      "Press F9 for this dashboard in its own window.")
        else:
            dialogs.ReportWindow(self, f"Statistics - {data.title}", body,
                                 width=800, height=700)

    def cmd_word_frequency(self) -> None:
        if not self.require_project():
            return
        self.commit_all()
        from collections import Counter

        from .. import docxio

        book_scenes = [s for s in self.project.data.compile_scenes() if s.docx]
        with self._busy(f"Reading {len(book_scenes)} scenes..."):
            text = "\n\n".join(
                docxio.read_prose(self.project.abs(s.docx))
                for s in book_scenes
            )
        if not text.strip():
            messagebox.showinfo("Nothing written yet",
                                "Write a scene first.", parent=self)
            return

        words = [w.lower() for w in diagnostics.words_of(text)]
        stop = {
            "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at",
            "for", "with", "as", "by", "from", "that", "this", "it", "its",
            "he", "she", "they", "him", "her", "them", "his", "their", "i",
            "you", "we", "us", "me", "my", "was", "were", "is", "are", "be",
            "been", "had", "has", "have", "do", "did", "not", "no", "so", "if",
            "then", "than", "when", "what", "who", "would", "could", "up",
            "out", "down", "back", "one", "all", "there", "her", "him", "into",
            "over", "just", "like", "about", "which", "will", "said",
        }
        content = Counter(w for w in words if w not in stop and len(w) > 2)
        total = len(words) or 1

        lines = [
            f"WORD FREQUENCY - {self.project.data.title}",
            "=" * 46, "",
            f"{total:,} words, {len(set(words)):,} unique "
            f"({len(set(words)) / total * 100:.1f}% variety)", "",
            "Most-used content words. A word appearing far more often than",
            "the rest is usually a crutch worth varying.", "",
        ]
        if not content:
            lines.append("  Nothing but common words so far.")
        # Computed once, outside the loop: most_common(1) on an empty Counter
        # raises IndexError, which a page of nothing but stopwords can produce.
        peak = content.most_common(1)[0][1] if content else 1
        for word, count in content.most_common(60):
            rate = count / total * 1000
            bar = "#" * max(1, min(34, round(count / peak * 34)))
            lines.append(f"  {word:<18s} {count:>6,}  {rate:>6.2f}/1k  {bar}")

        adverbs = Counter(w for w in words if w.endswith("ly") and len(w) > 4)
        if adverbs:
            lines += ["", "-" * 46, "", "MOST-USED -LY ADVERBS", ""]
            for word, count in adverbs.most_common(20):
                lines.append(f"  {word:<18s} {count:>6,}")

        dialogs.ReportWindow(self, "Word frequency", "\n".join(lines),
                             width=760, height=700)

    def cmd_sprint(self) -> None:
        if not self.require_project():
            return
        minutes = int(settings["sprint_minutes"])
        dialogs.SprintWindow(
            self, minutes,
            lambda: self._live_word_total(),
        )
        self.status.say(f"Sprint started: {minutes} minutes. Go.", 8)
        if self.current_scene_id:
            self.editor.text.focus_set()

    def _live_word_total(self) -> int:
        if not self.project:
            return 0
        if not self.current_scene_id:
            return self.project.data.word_count
        scene = self.project.data.scene(self.current_scene_id)
        if not scene:
            return self.project.data.word_count
        live = len(diagnostics.words_of(self.editor.get_value()))
        return self.project.data.word_count - scene.word_count + live

    def cmd_block_diagnostic(self) -> None:
        result = dialogs.BlockDiagnosticDialog(self).show()
        if result and self.tracker:
            self.tracker.session.block_type = result
            if self.project:
                self.project.mark_dirty()

    def cmd_check_files(self) -> None:
        if not self.require_project():
            return
        missing = self.project.missing_files()
        if not missing:
            messagebox.showinfo(
                "All present",
                f"Every document the project refers to exists on disk.\n\n"
                f"{len(list(self.project.root.rglob('*.docx')))} Word documents "
                f"in total.",
                parent=self,
            )
            return
        lines = [
            f"{len(missing)} documents are referenced but missing from disk:",
            "",
        ]
        lines += [f"  {kind:<12s} {name}" for kind, name in missing]
        lines += [
            "", "-" * 52, "",
            "This usually means a file was moved or renamed in Explorer, or",
            "OneDrive has not finished downloading it.",
            "",
            "If the file is genuinely gone, restore it from a backup",
            "(File > Backups & Restore) or delete the entry from the binder.",
        ]
        dialogs.ReportWindow(self, "Missing files", "\n".join(lines),
                             width=680, height=480)

    # ==================================================================
    # Commands - planning
    # ==================================================================

    def cmd_outline_window(self) -> None:
        if not self.require_project():
            return
        self.commit_all()

        def on_change() -> None:
            self.project.save()
            self.refresh_tree()
            self.refresh_counters()

        dialogs.OutlineWindow(self, self.project, on_change)

    def cmd_timeline_window(self) -> None:
        if not self.require_project():
            return
        self.commit_all()

        def on_change() -> None:
            self.project.save()
            self.refresh_tree()

        dialogs.TimelineWindow(self, self.project, on_change)

    def cmd_corkboard(self) -> None:
        if not self.require_project():
            return
        self.commit_all()
        from .corkboard import Corkboard

        def on_change() -> None:
            self.refresh_tree()
            self.refresh_counters()

        def open_scene(scene_id: str) -> None:
            item = f"scene:{scene_id}"
            if self.tree.exists(item):
                self.tree.selection_set(item)
                self.tree.see(item)
                self.lift()
                self.focus_force()

        Corkboard(self, self.project, on_change, open_scene)

    def cmd_relationships(self) -> None:
        if not self.require_project():
            return
        self.commit_all()
        from .corkboard import RelationshipWeb

        RelationshipWeb(self, self.project)

    # ------------------------------------------------------------------
    # The story graph and what hangs off it
    # ------------------------------------------------------------------

    def cmd_story_graph(self, tab: str = "") -> None:
        if not self.require_project():
            return
        self.commit_all()
        from .storyviews import StoryGraphWindow

        self.status.say("Reading the manuscript...")
        self.update_idletasks()
        StoryGraphWindow(self, self.project, start_tab=tab)
        self.status.say("")

    def cmd_continuity(self) -> None:
        self.cmd_story_graph("continuity")

    # ------------------------------------------------------------------
    # Undo of structural edits
    # ------------------------------------------------------------------

    def _typing(self) -> bool:
        """
        Is the caret somewhere that owns Ctrl+Z already?

        Only Text widgets: those have a real undo stack, and Tk has already
        run it by the time this fires. Entry and Combobox have no undo of
        their own, so Ctrl+Z in the inspector should undo the last structural
        edit rather than silently doing nothing - which is what it did when
        this was too broad.
        """
        try:
            focus = self.focus_get()
        except (KeyError, tk.TclError):
            return False
        return isinstance(focus, tk.Text)

    def cmd_undo(self, event=None):
        """
        Undo the last structural change - rename, move, delete, field edit.

        Typing has its own undo inside the text widget, and Tk has already run
        it by the time a Ctrl+Z *keypress* reaches here, so a keypress in the
        editor is left alone rather than undoing two things at once.

        Choosing Edit > Undo from the menu always undoes structure, whatever
        has focus. Without that distinction the menu item was dead most of the
        time: renaming something leaves the caret back in the editor, so the
        one moment you want to undo a rename is the moment focus says "this
        is typing".
        """
        if event is not None and self._typing():
            return None
        if not self.project:
            return None
        # Flush the editor first. Undo replaces the manifest, and the scene may
        # be re-rendered from disk immediately afterwards - so anything typed
        # since the last autosave was simply dropped, up to thirty seconds of
        # writing, with no way to get it back.
        self.commit_all()
        self.save_editor(snapshot=False)
        label = self.project.undo()
        if label is None:
            self.status.say("Nothing left to undo.", 4)
            return "break"
        self._after_history_change(f"Undone: {label}")
        return "break"

    def cmd_redo(self, event=None):
        if event is not None and self._typing():
            return None
        if not self.project:
            return None
        self.commit_all()
        self.save_editor(snapshot=False)
        label = self.project.redo()
        if label is None:
            self.status.say("Nothing to redo.", 4)
            return "break"
        self._after_history_change(f"Redone: {label}")
        return "break"

    def _after_history_change(self, message: str) -> None:
        """Rebuild everything the manifest feeds after an undo or redo."""
        from .. import storygraph

        storygraph.invalidate(self.project)
        self.project.save()
        # The open scene may have been deleted, or its text replaced.
        if self.current_scene_id and not self.project.data.scene(
                self.current_scene_id):
            self.current_scene_id = ""
            self.selection_kind = self.selection_id = ""
        self._form = None
        self.refresh_tree()
        self.render_selection()
        self.refresh_counters()
        self._sync_history_menu()
        self.status.say(message, 8)

    def _sync_history_menu(self) -> None:
        """Show what Ctrl+Z would actually undo, rather than a bare 'Undo'."""
        if not hasattr(self, "edit_menu"):
            return
        history = self.project.history if self.project else None
        try:
            if history and history.can_undo:
                self.edit_menu.entryconfigure(
                    0, label=f"Undo {history.undo_label()}", state="normal")
            else:
                self.edit_menu.entryconfigure(0, label="Undo", state="disabled")
            if history and history.can_redo:
                self.edit_menu.entryconfigure(
                    1, label=f"Redo {history.redo_label()}", state="normal")
            else:
                self.edit_menu.entryconfigure(1, label="Redo", state="disabled")
        except tk.TclError:
            pass

    def cmd_open_trash(self) -> None:
        """Deleted documents are moved here, not destroyed."""
        if not self.require_project():
            return
        folder = self.project.folder("trash")
        count = len(list(folder.glob("*")))
        reveal_in_explorer(folder)
        self.status.say(
            f"The trash holds {count} deleted "
            f"{'item' if count == 1 else 'items'}. Nothing here is removed "
            f"automatically.", 10)

    def cmd_verify_project(self) -> None:
        """One button: what is here, what is broken, and a score out of 100."""
        if not self.require_project():
            return
        self.commit_all()
        from .. import storygraph
        from .storyviews import build_graph_with_progress

        graph = build_graph_with_progress(self, self.project)
        body, score = storygraph.verify_project(self.project, graph)
        window = dialogs.ReportWindow(
            self, f"Project verification - {score}/100", body,
            width=760, height=700)
        window.add_action("Fix the links...",
                          lambda: self.cmd_story_graph("continuity"))
        self.status.say(f"Project health {score}/100.", 8)

    def cmd_story_bible(self) -> None:
        if not self.require_project():
            return
        self.commit_all()
        from .. import storygraph

        from .storyviews import build_graph_with_progress

        self.status.say("Building the story bible...")
        self.update_idletasks()
        try:
            graph = build_graph_with_progress(self, self.project)
            path = storygraph.write_story_bible(self.project, graph)
        except Exception as exc:
            self.status.say("")
            messagebox.showerror("Could not write it", str(exc), parent=self)
            return
        self.status.say(f"Story Bible written to {path.parent.name}.")
        self.refresh_tree()
        if messagebox.askyesno("Story Bible",
                               f"Written to:\n\n{path.name}\n\nOpen it now?",
                               parent=self):
            open_in_default_app(path)

    def cmd_dependencies(self) -> None:
        """What else in the book leans on the selected scene."""
        if not self.require_project():
            return
        kind, ident = self._selected_key()
        scene_id = ident if kind == "scene" else self.current_scene_id
        if not scene_id:
            messagebox.showinfo(
                "Pick a scene",
                "Select a scene in the binder first. This shows what the rest "
                "of the book would lose if that scene went away.",
                parent=self,
            )
            return
        self.commit_all()
        from .. import storygraph
        from .storyviews import build_graph_with_progress

        graph = build_graph_with_progress(self, self.project)
        body = storygraph.dependency_text(self.project, graph, scene_id)
        dialogs.ReportWindow(self, "Scene dependencies", body)

    def cmd_idea_inbox(self) -> None:
        if not self.require_project():
            return
        from .storyviews import IdeaInboxWindow

        IdeaInboxWindow(self, self.project, self.refresh_tree)

    def cmd_drafts(self) -> None:
        """Alternate versions of the selected scene."""
        if not self.require_project():
            return
        kind, ident = self._selected_key()
        scene_id = ident if kind == "scene" else self.current_scene_id
        if not scene_id:
            messagebox.showinfo(
                "Pick a scene",
                "Select a scene first. Drafts let you try a different version "
                "of it without copying the whole project.",
                parent=self,
            )
            return
        # The editor must be flushed first: switching drafts rewrites the very
        # file the editor is holding unsaved text for.
        self.commit_all()
        self.save_editor(snapshot=False)
        from .storyviews import DraftsDialog

        changed = DraftsDialog(self, self.project, scene_id).show()
        if changed:
            self.refresh_tree()
            # Re-render from disk: switching drafts replaced the file the
            # editor was showing, so what is on screen is now the wrong draft.
            self.render_selection()
            scene = self.project.data.scene(scene_id)
            if scene:
                self.status.say(f"Now writing the '{scene.active_draft}' draft.")

    def cmd_note_links(self) -> None:
        """Attach the selected note to what it is research for."""
        if not self.require_project():
            return
        kind, ident = self._selected_key()
        if kind != "note":
            messagebox.showinfo("Pick a note",
                                "Select a note or research document first.",
                                parent=self)
            return
        from .storyviews import NoteLinksDialog

        if NoteLinksDialog(self, self.project, ident).show():
            self.refresh_tree()
            self.render_selection()
            self.status.say("Note linked.")

    def cmd_map_editor(self, map_path: Optional[Path] = None) -> None:
        if not self.require_project():
            return
        self.commit_all()
        from .mapeditor import MapEditor

        def on_change() -> None:
            self.project.save()
            self.refresh_tree()

        editor = MapEditor(self, self.project, on_change)
        if map_path is not None and Path(map_path).exists():
            editor._open_map(Path(map_path))

    # ------------------------------------------------------------------
    # The editor's knowledge of this book
    # ------------------------------------------------------------------




        # Deliberately no FocusOut handler: showing the popup takes focus
        # away from the editor, which would fire it immediately and close the
        # popup in the same breath as opening it. Escape, accepting, or the
        # next completion all close it.



    # ------------------------------------------------------------------
    # Live spelling, usage and grammar
    # ------------------------------------------------------------------



















    def cmd_replace(self) -> None:
        """Find and replace across every document in the project."""
        if not self.require_project():
            return
        # The editor holds unsaved text that the sweep would not see, and
        # would then overwrite when the scene is next saved.
        self.commit_all()
        self.save_editor(snapshot=False)
        from .storyviews import ReplaceWindow

        def after() -> None:
            self.refresh_tree()
            self.render_selection()
            self.refresh_counters()
            self._sync_history_menu()

        ReplaceWindow(self, self.project, after)

    def cmd_chapter_map(self) -> None:
        """The map as it stands at any chapter of the book."""
        if not self.require_project():
            return
        self.commit_all()
        from .storyviews import ChapterMapWindow, build_graph_with_progress

        graph = build_graph_with_progress(self, self.project)
        ChapterMapWindow(self, self.project, graph)

    def cmd_names(self) -> None:
        from .. import mapmaker

        def build() -> str:
            lines = [
                "PLACE NAME GENERATOR", "=" * 26, "",
                "Five flavours of invented name. Steal what sounds right.", "",
            ]
            for flavour in mapmaker.NAME_SYLLABLES:
                names = mapmaker.generate_names(flavour, 16)
                lines.append(flavour.upper())
                for i in range(0, len(names), 3):
                    lines.append("    " + "".join(
                        f"{n:<20s}" for n in names[i:i + 3]
                    ))
                lines.append("")
            lines += [
                "-" * 52, "",
                "Lock a spelling the moment you use a name on the page, and",
                "record it in World Bible > Culture & Language. Inconsistent",
                "invented names are the most common continuity error there is.",
            ]
            return "\n".join(lines)

        window = dialogs.ReportWindow(self, "Name generator", build(),
                                      width=640, height=660)
        window.add_action("Refresh", lambda: window.set_body(build()), first=True)

    def cmd_set_structure(self, key: str) -> None:
        if not self.require_project():
            return
        self.commit_all()
        framework = structures.framework(key)
        current = self.project.data.structure
        if current == key:
            messagebox.showinfo("Already using it",
                                f"This novel already uses {framework.name}.",
                                parent=self)
            return
        if not messagebox.askyesno(
            "Change structure",
            f"Switch to {framework.name}?\n\n{framework.note}\n\n"
            f"Anything you have written against the current framework's beats "
            f"is kept and comes back if you switch back.",
            parent=self,
        ):
            return
        self.project.apply_structure(key, write_doc=False)
        self.project.save()
        self.refresh_tree()
        self.status.say(f"Structure is now {framework.name}.", 8)

    # ==================================================================
    # Commands - view
    # ==================================================================

    def cmd_toggle_focus(self) -> None:
        settings["focus_mode"] = bool(self.focus_var.get())
        self._apply_focus()
        self.status.say(
            "Focus mode on - other paragraphs dimmed."
            if self.focus_var.get() else "Focus mode off.", 4
        )

    def _flip_focus(self) -> None:
        self.focus_var.set(not self.focus_var.get())
        self.cmd_toggle_focus()

    def cmd_toggle_typewriter(self) -> None:
        settings["typewriter_scroll"] = bool(self.typewriter_var.get())
        self.status.say(
            "Typewriter scrolling on - the line you type stays centred."
            if self.typewriter_var.get() else "Typewriter scrolling off.", 4
        )

    def cmd_toggle_ghost(self) -> None:
        self._ghost_mode = bool(self.ghost_var.get())
        self._style_editor()
        if self._ghost_mode:
            self._apply_focus()
            self.status.say(
                "Ghost mode: your text is hidden so you cannot edit while "
                "drafting. Turn it off to read what you wrote.", 14
            )
        else:
            self.status.say("Ghost mode off.", 4)

    def cmd_toggle_distraction_free(self) -> None:
        self._distraction_free = not self._distraction_free
        if self._distraction_free:
            try:
                self.panes.forget(self.binder_frame)
                self.panes.forget(self.inspector_frame)
            except tk.TclError:
                pass
            self.toolbar.grid_remove()
            self.status.say("Distraction free. F12 to bring the panes back.", 8)
        else:
            try:
                self.panes.insert(0, self.binder_frame, weight=0)
                self.panes.add(self.inspector_frame, weight=1)
            except tk.TclError:
                pass
            self.toolbar.grid(row=1, column=0, sticky="ew")
        if self.current_scene_id:
            self.editor.text.focus_set()

    def cmd_font_size(self, delta: int) -> None:
        size = max(8, min(40, int(settings["editor_font_size"]) + delta))
        settings["editor_font_size"] = size
        self._style_editor()
        self.status.say(f"Editor text {size}pt.", 3)

    def cmd_theme(self, name: str) -> None:
        settings["theme"] = name
        self._apply_theme()
        self._apply_focus()
        self.status.say(f"{name.title()} theme.", 3)

    # ==================================================================
    # Commands - help
    # ==================================================================

    def cmd_readme(self) -> None:
        path = app_root() / "README.md"
        if path.exists():
            try:
                body = path.read_text(encoding="utf-8")
            except OSError:
                body = "Could not read README.md."
            dialogs.ReportWindow(self, "How to use this", body,
                                 width=860, height=720)
        else:
            self.cmd_shortcuts()

    def cmd_palette(self) -> None:
        """Ctrl+Shift+P: search every menu command by typing."""
        from .palette import CommandPalette

        existing = getattr(self, "_palette", None)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.close()
                    self._palette = None
                    return
            except tk.TclError:
                pass
        self._palette = CommandPalette(self)

    def cmd_shortcuts(self) -> None:
        body = """KEYBOARD SHORTCUTS
==================

FIND ANY COMMAND
  Ctrl+Shift+P      Command palette - type what you want, press Enter

FILE
  Ctrl+S            Save
  Ctrl+O            Open a novel
  Ctrl+Shift+N      New novel
  Ctrl+B            Back up now

WRITING
  Ctrl+N            New scene
  Ctrl+Shift+C      New chapter
  F11               Focus mode (dim other paragraphs)
  F12               Distraction free (hide side panes)
  Ctrl+=  Ctrl+-    Bigger / smaller text

UNDO
  Ctrl+Z            In the editor: undo typing.
                    Anywhere else: undo the last change to the project -
                    a rename, a move, a delete, an inspector edit.
  Ctrl+Y            Redo
  Ctrl+Alt+Z        Undo the last project change even while typing
  Edit menu         Shows exactly what Undo would take back

  Deleted documents go to the _Trash folder inside the project, not
  into thin air. Undo puts them back where they were.

TOOLS
  Ctrl+F            Find in project
  F5                Compile manuscript
  Shift+F5          Quick compile with defaults
  F6                Start a sprint
  F7                Diagnose the current scene
  F8                Scene craft check
  F9                Statistics dashboard
  F4                Verify this project (health check)
  F10               Continuity check

PLANNING
  Ctrl+L            Outline and beats
  Ctrl+T            Timeline
  Ctrl+K            Corkboard
  Ctrl+M            Map maker
  Ctrl+G            Story graph
  Ctrl+I            Idea inbox - catch a thought without stopping

BINDER
  Right-click       Context menu for any item
  Double-click      Open a sheet or document in Word
  Type letters      Jump to a matching item


HOW THE PIECES FIT
==================

  Scenes are Word documents. You can write them here, or open them in
  Word and write there. Either way the tool keeps up: it re-reads any
  document whose timestamp has changed.

  Character sheets, the world bible, the query letter and every other
  reference document are Word field sheets - a two-column table you
  fill in. Whatever you type comes back into the app automatically.

  Compiling gathers every scene into ONE Word document in standard
  manuscript format. That file lives in the _Compiled folder.

  Backups are verified zips of the whole project in _Backups.
  Snapshots are per-document version history in _Snapshots.
  Both prune themselves; neither ever overwrites your live work.

  Your typing is journalled a second and a half after you stop, on
  top of the thirty-second autosave. If the power goes out or Windows
  restarts, the next start offers the words back and puts the caret
  where you left it. Nothing is ever restored without asking first.

  Every document is written to a temporary file, checked that it is a
  valid Word file, and only then allowed to replace the real one. A
  failed save leaves the previous version exactly as it was.

  The Story Graph reads the whole manuscript and works out who appears
  where, what each scene introduces, and which threads never resolve.
  The continuity check, the relationship timeline, the story bible and
  the question box all run off it. None of it leaves this machine.

  Drafts are alternate versions of one scene. Switching parks the
  version you are leaving and brings the other in, so you can try a
  chapter three different ways without copying the project. Compiling
  always uses whichever draft you are currently in.
"""
        dialogs.ReportWindow(self, "Keyboard shortcuts", body,
                             width=760, height=700)

    def cmd_dialogue_rules(self) -> None:
        from .. import templates

        lines = ["DIALOGUE RULES (US / Chicago Manual of Style)",
                 "=" * 46, ""]
        for rule, detail in templates.DIALOGUE_RULES:
            lines += [rule.upper(), f"    {detail}", ""]
        dialogs.ReportWindow(self, "Dialogue rules", "\n".join(lines),
                             width=760, height=640)

    def cmd_revision_checklist(self) -> None:
        lines = [
            "THE FOUR PASSES OF REVISION", "=" * 34, "",
            "Do these in order. Doing them at once is why revision feels",
            "impossible - you cannot judge structure and hunt typos with the",
            "same part of your brain.", "",
        ]
        for _key, title, items in structures.REVISION_TIERS:
            lines += [title.upper(), ""]
            lines += [f"    [ ] {item}" for item in items]
            lines.append("")
        dialogs.ReportWindow(self, "Revision checklist", "\n".join(lines),
                             width=760, height=700)

    def cmd_about(self) -> None:
        docs = 0
        if self.project:
            docs = len(list(self.project.root.rglob("*.docx")))
        body = f"""{APP_NAME} {APP_VERSION}

A local novel-writing studio. Every artefact is a real Microsoft Word
document on your own disk. Nothing is uploaded, no account is needed,
and it works with no network connection at all.

WHAT IS ON DISK
  project.json      ordering, links, statistics, targets
  00 Manuscript     one .docx per scene, in chapter folders
  01 Outline        beat sheet, premise, reverse outline
  02-06             characters, locations, items, factions, threads
  07 World Bible    eight documents covering magic, politics, religion,
                    culture, technology, calendar, nature, history
  08 Timeline       chronological event table
  09-10             research and notes
  11 Publishing     query letter, synopsis, beta questionnaire, tracker
  12 Continuity     established facts, for book two
  _Compiled         the whole story in one manuscript
  _Snapshots        version history per document
  _Backups          verified zips of everything

{f"This project currently holds {docs} Word documents." if docs else ""}

Structural frameworks: Three-Act (Weiland), Save the Cat (Snyder),
Seven-Point (Wells), Story Circle (Harmon), Hero's Journey (Vogler),
Romancing the Beat (Hayes), Mystery, Freytag, Snowflake (Ingermanson).

Scene structure follows Swain and Bickham. Character arcs follow
Weiland's Lie/Truth framework. Prose diagnostics are heuristics -
your voice beats every rule in them.

Python {".".join(str(v) for v in __import__("sys").version_info[:3])}
"""
        def header(frame: ttk.Frame) -> None:
            self._about_logo = styling.brand_image(
                self, int(88 * self.ui_scale), self.tokens)
            if self._about_logo is not None:
                tk.Label(frame, image=self._about_logo, borderwidth=0,
                         background=self.tokens["panel"]).grid(
                    row=0, column=0, rowspan=3, padx=(4, 16))
            ttk.Label(frame, text=APP_NAME, style="Title.TLabel").grid(
                row=0, column=1, sticky="sw")
            ttk.Label(frame, text=f"Version {APP_VERSION}",
                      style="Status.TLabel").grid(row=1, column=1, sticky="w")
            ttk.Label(frame, text="Plan. Write. Build your story.",
                      style="Hint.TLabel").grid(row=2, column=1, sticky="nw")

        dialogs.ReportWindow(self, f"About {APP_NAME}", body,
                             width=720, height=700, header=header)

    # ==================================================================
    # Shutdown
    # ==================================================================

    def on_close(self) -> None:
        try:
            self.commit_all()
        except Exception as exc:
            # commit_all() moves whatever is on screen - the editor text, an
            # inspector field you just tabbed out of - into project.json and
            # the manuscript. A silent `pass` here used to mean a bug in one
            # committer could drop that unsaved edit with the window closing
            # normally and nothing on screen ever saying so. It gets the same
            # "close anyway?" choice as a failed project save, a few lines
            # below, rather than a different, quieter kind of data loss.
            if not messagebox.askyesno(
                "Could not save your last change",
                f"Something you just edited could not be saved:\n\n{exc}\n\n"
                f"Close anyway and risk losing it?", parent=self,
            ):
                return

        if self.project:
            if self.tracker:
                self.tracker.close()
            try:
                settings["window_geometry"] = self.geometry()
            except tk.TclError:
                pass
            try:
                self.project.save(force=True)
            except Exception as exc:
                if not messagebox.askyesno(
                    "Could not save",
                    f"Saving failed:\n\n{exc}\n\nClose anyway and lose the "
                    f"unsaved changes?", parent=self,
                ):
                    return

            if settings["backup_on_close"]:
                try:
                    self.status.say("Backing up before closing...", 0)
                    self.update_idletasks()
                    backup.create_backup(self.project, reason="close")
                except Exception:
                    pass

        # Record where we were. Mark the exit clean ONLY if there is genuinely
        # nothing unsaved: marking it clean is what suppresses the offer to
        # recover, so doing it after a save that failed threw away the only
        # remaining copy of the writer's last paragraph.
        try:
            self._write_journal()
            if not self._editor_dirty:
                recovery.mark_clean_exit()
            else:
                self.status.say("Some text could not be saved. It is kept in "
                                "the recovery journal and will be offered "
                                "back next time.", 0)
        except Exception:
            pass

        self.destroy()


# ==========================================================================
# Entry point
# ==========================================================================


def set_app_identity() -> None:
    """
    Give the process its own Windows identity.

    Without one, the taskbar groups every Tk window under python.exe and shows
    Python's icon on it, whatever icon the window sets. With one, the taskbar
    shows NovelForge's own logo and keeps its windows together. Purely cosmetic,
    so a failure is silent.
    """
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "NovelForge.Desktop")
    except Exception:
        pass


def enable_dpi_awareness() -> None:
    """
    Tell Windows we will handle display scaling ourselves.

    Without this, a Tk window on a 150% display is drawn at 100% and then
    bitmap-stretched by Windows: everything is soft and slightly blurred. With
    it, Windows hands us real pixels and Tk draws crisply - but then nothing
    scales unless we also tell Tk what the scaling factor is, which is what
    _apply_scaling below does. The two must happen together or text comes out
    tiny on a high-DPI screen.

    Must run before the first Tk window exists, and is a no-op off Windows.
    """
    try:
        import ctypes

        try:
            # Per-monitor v2 where available: correct when a window is dragged
            # between screens of different scaling.
            ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
            return
        except Exception:
            pass
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # system aware
            return
        except Exception:
            pass
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        # Any failure here costs sharpness, never correctness.
        pass


def _apply_scaling(root: tk.Tk) -> float:
    """
    Match Tk's idea of a point to the actual display, and scale the fonts.

    Returns the factor, where 1.0 is a normal 96 DPI screen and 2.0 is 200%.
    """
    try:
        dpi = float(root.winfo_fpixels("1i"))
    except Exception:
        return 1.0
    if dpi <= 0:
        return 1.0
    scale = dpi / 96.0
    if abs(scale - 1.0) < 0.05:
        return 1.0
    try:
        root.tk.call("tk", "scaling", dpi / 72.0)
        from tkinter import font as tkfont

        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont",
                     "TkHeadingFont", "TkFixedFont", "TkTooltipFont",
                     "TkIconFont", "TkSmallCaptionFont", "TkCaptionFont"):
            try:
                widget_font = tkfont.nametofont(name, root=root)
            except Exception:
                continue
            size = widget_font.cget("size")
            # Negative sizes are already pixels, which Tk scaling does not
            # touch, so those have to be scaled by hand.
            if size < 0:
                widget_font.configure(size=int(round(size * scale)))
    except Exception:
        return 1.0
    return scale


def _friendly_error(exc_type, value) -> str:
    """Turn an exception into something a novelist can act on."""
    text = str(value)
    if isinstance(value, FileBusyError):
        return text            # already written for a human
    if isinstance(value, PermissionError):
        return ("A file could not be written because something else has it "
                "open. This is almost always Microsoft Word - close the "
                "document and try again.")
    if isinstance(value, FileNotFoundError):
        return ("A file that should be there could not be found. It may have "
                "been moved or renamed outside the tool. Try "
                "Tools > Check for Missing Files.")
    if isinstance(value, (MemoryError,)):
        return ("The machine ran out of memory. Close some other programs "
                "and try again.")
    if isinstance(value, OSError) and getattr(value, "errno", None) == 28:
        return "The disk is full. Free some space and try again."
    if isinstance(value, UnicodeDecodeError):
        return ("A file could not be read as text. It may be damaged, or "
                "saved in an unusual format.")
    if isinstance(value, ProjectError):
        return text
    # Anything unrecognised: say plainly that it is a fault in the tool,
    # rather than showing the class name and hoping.
    return ("Something inside the tool went wrong while doing that. The "
            "action was stopped before it could change anything.")


def main() -> int:
    set_app_identity()
    enable_dpi_awareness()
    app = App()

    def report_error(exc_type, value, tb) -> None:
        """
        Say what happened in English, and put the technical part in a file.

        A writer confronted with "AttributeError: 'NoneType' object has no
        attribute 'docx'" learns nothing except that the tool is unreliable.
        The stack trace still matters - for a bug report - so it is written to
        a log rather than thrown at the screen.
        """
        details = "".join(traceback.format_exception(exc_type, value, tb))
        log = app_root() / "novelforge-errors.log"
        try:
            with open(log, "a", encoding="utf-8") as handle:
                handle.write(f"\n{'=' * 70}\n{now_iso()}\n{details}")
        except OSError:
            pass

        friendly = _friendly_error(exc_type, value)
        try:
            messagebox.showerror(
                "Something went wrong",
                f"{friendly}\n\n"
                f"Your writing is saved as you type and journalled every few "
                f"seconds, so this has almost certainly not lost anything.\n\n"
                f"Technical details were written to:\n{log.name}",
            )
        except Exception:
            print(details)

    app.report_callback_exception = report_error  # type: ignore[assignment]
    app.mainloop()
    return 0
