"""
Dialogs and secondary windows.

Modal dialogs subclass Dialog and set `self.result`. Non-modal tool windows
(sprint timer, diagnostics report) are plain Toplevels so you can keep writing
with them open.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .. import structures
from ..config import (
    THEMES,
    open_in_default_app,
    projects_root,
    reveal_in_explorer,
    settings,
)
from ..model import CHARACTER_ROLES, SCENE_STATUSES
from .widgets import (
    AutoScrollbar,
    Form,
    ScrollFrame,
    ScrolledText,
    WritingCheck,
    add_editing_keys,
    center_window,
)


# ==========================================================================
# Base
# ==========================================================================


class Dialog(tk.Toplevel):
    """A modal dialog. Subclasses build `body` and read/write `self.result`."""

    def __init__(self, parent, title: str, width: int = 520, height: int = 480) -> None:
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.result: Any = None
        self.transient(parent)
        self.resizable(True, True)

        container = ttk.Frame(self, padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        self.body_frame = ttk.Frame(container)
        self.body_frame.grid(row=0, column=0, sticky="nsew")
        self.body_frame.columnconfigure(0, weight=1)

        self.buttons = ttk.Frame(container)
        self.buttons.grid(row=1, column=0, sticky="e", pady=(12, 0))

        self.build(self.body_frame)
        self.build_buttons(self.buttons)

        # The floor is 80% of the asked-for size, never below a usable box.
        # The button row lives in its own grid row that does not shrink, so a
        # squeezed dialog loses body height and keeps OK/Cancel reachable.
        center_window(self, width, height,
                      min_width=max(360, int(width * 0.8)),
                      min_height=max(260, int(height * 0.8)))
        self.deiconify()
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.bind("<Escape>", lambda _e: self.on_cancel())
        self.grab_set()
        self.focus_force()

    def build(self, parent: ttk.Frame) -> None:  # pragma: no cover - override
        raise NotImplementedError

    def build_buttons(self, parent: ttk.Frame) -> None:
        ttk.Button(parent, text="Cancel", command=self.on_cancel).grid(
            row=0, column=0, padx=(0, 6)
        )
        ok = ttk.Button(parent, text="OK", command=self.on_ok)
        ok.grid(row=0, column=1)
        self.bind("<Return>", lambda _e: self.on_ok())

    def on_ok(self) -> None:
        self.result = self.collect()
        if self.result is not None:
            self.destroy()

    def on_cancel(self) -> None:
        self.result = None
        self.destroy()

    def collect(self) -> Any:  # pragma: no cover - override
        return True

    def show(self) -> Any:
        self.wait_window()
        return self.result


# ==========================================================================
# New project
# ==========================================================================


class NewProjectDialog(Dialog):
    def __init__(self, parent) -> None:
        self.vars: Dict[str, tk.Variable] = {}
        super().__init__(parent, "New Novel", 620, 600)

    def build(self, parent: ttk.Frame) -> None:
        scroll = ScrollFrame(parent)
        scroll.grid(row=0, column=0, sticky="nsew")
        parent.rowconfigure(0, weight=1)
        body = scroll.body
        body.columnconfigure(1, weight=1)

        row = 0

        def field(label: str, key: str, default: str = "",
                  width: int = 34) -> ttk.Entry:
            nonlocal row
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w",
                                            padx=(2, 8), pady=4)
            var = tk.StringVar(value=default)
            self.vars[key] = var
            entry = ttk.Entry(body, textvariable=var, width=width)
            entry.grid(row=row, column=1, sticky="ew", pady=4)
            row += 1
            return entry

        title_entry = field("Title", "title", "Untitled Novel")
        field("Subtitle (optional)", "subtitle")
        field("Author", "author")
        field("Series (optional)", "series")
        field("Genre", "genre")

        ttk.Label(body, text="Structure").grid(row=row, column=0, sticky="w",
                                               padx=(2, 8), pady=4)
        structure_var = tk.StringVar(value=structures.THREE_ACT.name)
        self.vars["structure"] = structure_var
        combo = ttk.Combobox(body, textvariable=structure_var,
                             values=structures.framework_names(),
                             state="readonly", width=32)
        combo.grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        self.structure_note = ttk.Label(body, text=structures.THREE_ACT.note,
                                        wraplength=380, style="Hint.TLabel",
                                        justify="left")
        self.structure_note.grid(row=row, column=1, sticky="w", pady=(0, 6))
        row += 1

        def on_structure(_event=None) -> None:
            key = structures.key_for_name(structure_var.get())
            self.structure_note.configure(text=structures.framework(key).note)

        combo.bind("<<ComboboxSelected>>", on_structure)

        # Prefilled from Preferences. These two settings existed and were
        # editable but nothing ever read them, so changing them did nothing.
        field("Target word count", "target_words",
              str(settings["default_target_words"]), 14)
        field("Daily word target", "daily_words",
              str(settings["default_daily_target"]), 14)
        field("Deadline (YYYY-MM-DD, optional)", "deadline", "", 18)

        ttk.Separator(body, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=10
        )
        row += 1

        ttk.Label(body, text="Extra template packs",
                  style="Section.TLabel").grid(row=row, column=0, columnspan=2,
                                               sticky="w", pady=(0, 4))
        row += 1

        pack_info = [
            ("fantasy", "Fantasy / Sci-Fi",
             "Full world bible is always created. This adds nothing extra "
             "for now."),
            ("mystery", "Mystery / Crime",
             "Adds a Clue Tracker: clue, red herring, planted where, paid off."),
            ("romance", "Romance",
             "Adds a Relationship Arc Tracker keyed to Romancing the Beat."),
        ]
        for key, label, hint in pack_info:
            var = tk.BooleanVar(value=key == "fantasy")
            self.vars[f"pack_{key}"] = var
            ttk.Checkbutton(body, text=label, variable=var).grid(
                row=row, column=0, columnspan=2, sticky="w", padx=(2, 0)
            )
            row += 1
            ttk.Label(body, text=hint, style="Hint.TLabel", wraplength=440,
                      justify="left").grid(row=row, column=0, columnspan=2,
                                           sticky="w", padx=(22, 0), pady=(0, 4))
            row += 1

        ttk.Separator(body, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=10
        )
        row += 1

        ttk.Label(body, text="Location").grid(row=row, column=0, sticky="w",
                                              padx=(2, 8))
        location_var = tk.StringVar(value=str(projects_root()))
        self.vars["parent"] = location_var
        location_frame = ttk.Frame(body)
        location_frame.grid(row=row, column=1, sticky="ew")
        location_frame.columnconfigure(0, weight=1)
        ttk.Entry(location_frame, textvariable=location_var).grid(
            row=0, column=0, sticky="ew"
        )

        def browse() -> None:
            chosen = filedialog.askdirectory(
                parent=self, initialdir=location_var.get(),
                title="Where should this novel live?",
            )
            if chosen:
                location_var.set(chosen)

        ttk.Button(location_frame, text="...", width=3, command=browse).grid(
            row=0, column=1, padx=(4, 0)
        )
        row += 1

        ttk.Label(body, text="A folder will be created here named after the "
                             "title, holding every document for this novel.",
                  style="Hint.TLabel", wraplength=440, justify="left").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )

        title_entry.selection_range(0, "end")
        title_entry.focus_set()

    def collect(self) -> Optional[Dict[str, Any]]:
        title = self.vars["title"].get().strip()
        if not title:
            messagebox.showwarning("Title needed",
                                   "Give the novel a title. You can change it "
                                   "later.", parent=self)
            return None

        def as_int(key: str, fallback: int) -> int:
            raw = self.vars[key].get().strip().replace(",", "")
            try:
                return max(0, int(float(raw)))
            except ValueError:
                return fallback

        deadline = self.vars["deadline"].get().strip()
        if deadline:
            try:
                date.fromisoformat(deadline)
            except ValueError:
                messagebox.showwarning(
                    "Check the deadline",
                    "Use the form YYYY-MM-DD, for example 2027-03-01, "
                    "or leave it empty.",
                    parent=self,
                )
                return None

        packs = [
            key for key in ("fantasy", "mystery", "romance")
            if self.vars[f"pack_{key}"].get()
        ]
        return {
            "title": title,
            "subtitle": self.vars["subtitle"].get().strip(),
            "author": self.vars["author"].get().strip(),
            "series": self.vars["series"].get().strip(),
            "genre": self.vars["genre"].get().strip(),
            "structure": structures.key_for_name(self.vars["structure"].get()),
            "target_words": as_int("target_words",
                                   settings["default_target_words"]),
            "daily_words": as_int("daily_words",
                                  settings["default_daily_target"]),
            "deadline": deadline,
            "packs": packs,
            "parent": Path(self.vars["parent"].get().strip() or projects_root()),
        }


# ==========================================================================
# Project settings
# ==========================================================================


class ProjectSettingsDialog(Dialog):
    def __init__(self, parent, project) -> None:
        self.project = project
        super().__init__(parent, "Project Settings", 560, 620)

    def build(self, parent: ttk.Frame) -> None:
        scroll = ScrollFrame(parent)
        scroll.grid(row=0, column=0, sticky="nsew")
        parent.rowconfigure(0, weight=1)
        self.form = Form(scroll.body)
        data = self.project.data

        self.form.heading("Book")
        self.form.entry("Title", data, "title")
        self.form.entry("Subtitle", data, "subtitle")
        self.form.entry("Author", data, "author")
        self.form.entry("Surname (for header)", data, "author_surname")
        self.form.entry("Series", data, "series")
        self.form.integer("Book number", data, "book_number")
        self.form.entry("Genre", data, "genre")
        self.form.multiline("Logline", data, "logline", height=3)
        self.form.combo("Point of view", data, "pov_style",
                        ["First person", "Third limited", "Third omniscient",
                         "Second person", "Mixed"])
        self.form.combo("Tense", data, "tense", ["Past", "Present", "Mixed"])

        self.form.heading("Targets")
        self.form.integer("Total words", data.targets, "total_words")
        self.form.integer("Words per day", data.targets, "daily_words")
        self.form.integer("Words per session", data.targets, "session_words")
        self.form.entry("Deadline (YYYY-MM-DD)", data.targets, "deadline")
        self.form.hint("Leave the deadline empty to turn off the countdown.")

        self.form.heading("Manuscript Format")
        self.form.hint("Applies when compiling and when creating new scenes.")

    def collect(self) -> bool:
        deadline = self.project.data.targets.deadline
        self.form.commit()
        raw = (self.project.data.targets.deadline or "").strip()
        if raw:
            try:
                date.fromisoformat(raw)
            except ValueError:
                messagebox.showwarning(
                    "Check the deadline",
                    "Use YYYY-MM-DD, or leave it empty.", parent=self,
                )
                self.project.data.targets.deadline = deadline
                return False
        if not self.project.data.author_surname and self.project.data.author:
            self.project.data.author_surname = \
                self.project.data.author.strip().split()[-1]
        self.project.mark_dirty()
        return True


# ==========================================================================
# App preferences
# ==========================================================================


class PreferencesDialog(Dialog):
    def __init__(self, parent) -> None:
        self.vars: Dict[str, tk.Variable] = {}
        super().__init__(parent, "Preferences", 520, 560)

    def build(self, parent: ttk.Frame) -> None:
        scroll = ScrollFrame(parent)
        scroll.grid(row=0, column=0, sticky="nsew")
        parent.rowconfigure(0, weight=1)
        body = scroll.body
        body.columnconfigure(1, weight=1)
        row = 0

        def add(label: str, key: str, values: Optional[Sequence] = None,
                width: int = 20) -> None:
            nonlocal row
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w",
                                            padx=(2, 8), pady=3)
            current = settings[key]
            if isinstance(current, bool):
                var: tk.Variable = tk.BooleanVar(value=current)
                ttk.Checkbutton(body, variable=var).grid(row=row, column=1,
                                                         sticky="w", pady=3)
            elif values:
                var = tk.StringVar(value=str(current))
                ttk.Combobox(body, textvariable=var,
                             values=[str(v) for v in values],
                             state="readonly", width=width).grid(
                    row=row, column=1, sticky="w", pady=3)
            else:
                var = tk.StringVar(value=str(current))
                ttk.Entry(body, textvariable=var, width=width).grid(
                    row=row, column=1, sticky="w", pady=3)
            self.vars[key] = var
            row += 1

        def heading(text: str) -> None:
            nonlocal row
            ttk.Label(body, text=text.upper(), style="Section.TLabel").grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(12, 4)
            )
            row += 1

        heading("Editor")
        add("Theme", "theme", list(THEMES.keys()))
        add("Editor font", "editor_font",
            ["Georgia", "Cambria", "Consolas", "Courier New", "Calibri",
             "Segoe UI", "Times New Roman", "Verdana", "Iosevka", "Lucida Console"])
        add("Editor font size", "editor_font_size", list(range(9, 29)))
        add("Autosave seconds", "autosave_seconds", [10, 15, 20, 30, 45, 60, 120])
        add("Typewriter scrolling", "typewriter_scroll")

        heading("Checking as you write")
        add("Underline mistakes as I type", "live_writing_check")

        heading("New novels")
        add("Default target word count", "default_target_words",
            [50000, 60000, 70000, 80000, 90000, 100000, 120000, 150000])
        add("Default words per day", "default_daily_target",
            [250, 500, 750, 1000, 1500, 2000, 3000])

        heading("Sprints")
        add("Sprint minutes", "sprint_minutes", [5, 10, 15, 20, 25, 30, 45, 60])

        heading("Maps")
        add("Ask before closing an unsaved map", "map_prompt_on_close")

        heading("Manuscript output")
        add("Manuscript font", "manuscript_font",
            ["Times New Roman", "Courier New", "Georgia", "Garamond", "Cambria"])
        add("Manuscript font size", "manuscript_font_size", [11, 12, 13])
        add("Line spacing", "manuscript_line_spacing", [1.0, 1.5, 2.0])
        add("Margin (inches)", "manuscript_margin", [0.8, 1.0, 1.25])
        add("First-line indent", "manuscript_first_line_indent", [0.0, 0.3, 0.5])
        add("Scene separator", "scene_separator", ["#", "* * *", "---", "~"])

        heading("Safety")
        add("Backup when opening", "backup_on_open")
        add("Backup when closing", "backup_on_close")
        add("Backups to keep", "backup_retention", [5, 10, 25, 50, 100])
        add("Snapshot on every save", "snapshot_on_save")
        add("Snapshots per document", "snapshot_retention_per_doc",
            [10, 20, 40, 80, 200])

    def collect(self) -> bool:
        from ..config import DEFAULT_SETTINGS

        updates: Dict[str, Any] = {}
        for key, var in self.vars.items():
            raw = var.get()
            # The TYPE comes from the shipped default, not from whatever is
            # currently stored. Reading it from the stored value meant a
            # settings file corrupted into holding a string where a number
            # belongs would be written straight back out as a string, and the
            # corruption would survive every visit to this dialog.
            default = DEFAULT_SETTINGS.get(key, settings[key])
            if isinstance(default, bool):
                updates[key] = bool(raw)
            elif isinstance(default, int):
                try:
                    updates[key] = int(float(str(raw)))
                except ValueError:
                    continue
            elif isinstance(default, float):
                try:
                    value = float(str(raw))
                except ValueError:
                    continue
                # A non-finite number would reach every consumer of this
                # setting and crash the first one that does arithmetic on it.
                if value != value or value in (float("inf"), float("-inf")):
                    continue
                updates[key] = value
            else:
                updates[key] = str(raw)
        settings.update(updates)
        return True


# ==========================================================================
# Compile
# ==========================================================================


class CompileDialog(Dialog):
    def __init__(self, parent, project) -> None:
        self.project = project
        self.vars: Dict[str, tk.Variable] = {}
        super().__init__(parent, "Compile Manuscript", 560, 560)

    def build(self, parent: ttk.Frame) -> None:
        scroll = ScrollFrame(parent)
        scroll.grid(row=0, column=0, sticky="nsew")
        parent.rowconfigure(0, weight=1)
        body = scroll.body
        body.columnconfigure(1, weight=1)
        row = 0

        data = self.project.data
        included = data.compile_scenes()
        words = sum(s.word_count for s in included)

        ttk.Label(
            body,
            text=f"{len(included)} scenes, {words:,} words will be compiled "
                 f"into a single Word document.",
            wraplength=460, justify="left", style="Section.TLabel",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 10))
        row += 1

        def check(label: str, key: str, default: bool, hint: str = "") -> None:
            nonlocal row
            var = tk.BooleanVar(value=default)
            self.vars[key] = var
            ttk.Checkbutton(body, text=label, variable=var).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=1
            )
            row += 1
            if hint:
                ttk.Label(body, text=hint, style="Hint.TLabel",
                          wraplength=430, justify="left").grid(
                    row=row, column=0, columnspan=2, sticky="w",
                    padx=(22, 0), pady=(0, 4))
                row += 1

        check("Title page", "title_page", True,
              "Contact block, rounded word count, title a third down the page "
              "- standard submission format.")
        check("Running header", "running_header", True,
              "Surname / TITLE / page number, from page two onward.")
        check("Chapter headings", "chapter_headings", True)
        check("Include chapter titles", "include_chapter_titles", True,
              "Generic titles like 'Chapter One' are not repeated.")
        check("Table of contents", "table_of_contents", False,
              "Inserts a Word TOC field. Right-click it in Word and choose "
              "Update Field to fill it in.")
        check("'THE END' at the end", "the_end", True)

        ttk.Separator(body, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=10)
        row += 1
        ttk.Label(body, text="WORKING DRAFT OPTIONS",
                  style="Section.TLabel").grid(row=row, column=0, columnspan=2,
                                               sticky="w", pady=(0, 4))
        row += 1

        check("Include scene synopses", "include_synopses", False,
              "Prints each scene's synopsis above it. For your eyes only - "
              "never send this out.")
        check("Include scene status", "include_status_notes", False)

        ttk.Separator(body, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=10)
        row += 1

        ttk.Label(body, text="Chapter numbering").grid(
            row=row, column=0, sticky="w", padx=(2, 8))
        numbering = tk.StringVar(value="Words (Chapter One)")
        self.vars["chapter_numbering"] = numbering
        ttk.Combobox(body, textvariable=numbering, state="readonly", width=26,
                     values=["Words (Chapter One)", "Digits (Chapter 1)",
                             "No number"]).grid(row=row, column=1, sticky="w")
        row += 1

        ttk.Label(body, text="Contact block").grid(
            row=row, column=0, sticky="nw", padx=(2, 8), pady=(8, 0))
        self.contact = tk.Text(body, height=5, wrap="none", borderwidth=1,
                               relief="solid", highlightthickness=0)
        default_contact = "\n".join(
            bit for bit in [data.author, "", "", ""] if bit is not None
        )
        self.contact.insert("1.0", data.author or "")
        self.contact.grid(row=row, column=1, sticky="ew", pady=(8, 0))
        row += 1
        ttk.Label(body, text="Name, address, phone, email - one per line. "
                             "Appears top-left of the title page.",
                  style="Hint.TLabel", wraplength=430, justify="left").grid(
            row=row, column=1, sticky="w", pady=(2, 0))

    def build_buttons(self, parent: ttk.Frame) -> None:
        ttk.Button(parent, text="Cancel", command=self.on_cancel).grid(
            row=0, column=0, padx=(0, 6))
        ttk.Button(parent, text="Compile", command=self.on_ok).grid(row=0, column=1)
        self.bind("<Return>", lambda _e: self.on_ok())

    def collect(self) -> Dict[str, Any]:
        numbering_map = {
            "Words (Chapter One)": "word",
            "Digits (Chapter 1)": "digit",
            "No number": "none",
        }
        return {
            "title_page": bool(self.vars["title_page"].get()),
            "running_header": bool(self.vars["running_header"].get()),
            "chapter_headings": bool(self.vars["chapter_headings"].get()),
            "include_chapter_titles": bool(self.vars["include_chapter_titles"].get()),
            "table_of_contents": bool(self.vars["table_of_contents"].get()),
            "the_end": bool(self.vars["the_end"].get()),
            "include_synopses": bool(self.vars["include_synopses"].get()),
            "include_status_notes": bool(self.vars["include_status_notes"].get()),
            "chapter_numbering": numbering_map.get(
                self.vars["chapter_numbering"].get(), "word"
            ),
            "contact_block": self.contact.get("1.0", "end-1c"),
        }


# ==========================================================================
# Text report window (diagnostics, stats, search results)
# ==========================================================================


class ReportWindow(tk.Toplevel):
    """Non-modal, monospaced, read-only. Used for every generated report."""

    def __init__(self, parent, title: str, body: str,
                 width: int = 860, height: int = 640,
                 actions: Optional[Sequence[Tuple[str, Callable[[], None]]]] = None,
                 header: Optional[Callable[[ttk.Frame], None]] = None
                 ) -> None:
        super().__init__(parent)
        self.title(title)
        theme = THEMES.get(settings["theme"], THEMES["warm"])

        container = ttk.Frame(self, padding=8)
        container.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        # `header` builds an optional block above the text (the About window's
        # logo); everything below it shifts down one row.
        top = 0
        if header is not None:
            head = ttk.Frame(container)
            head.grid(row=0, column=0, sticky="ew", pady=(0, 10))
            header(head)
            top = 1
        container.rowconfigure(top, weight=1)
        container.columnconfigure(0, weight=1)

        self.viewer = ScrolledText(container, height=30, wrap="word",
                                   font=("Consolas", 10))
        self.viewer.grid(row=top, column=0, sticky="nsew")
        self.viewer.text.configure(
            background=theme["bg"], foreground=theme["fg"],
            insertbackground=theme["caret"], selectbackground=theme["select"],
        )
        self.viewer.set_report(body)

        self._body = body
        self._bar = ttk.Frame(container)
        self._bar.grid(row=top + 1, column=0, sticky="ew", pady=(8, 0))
        self._extra: List[ttk.Button] = []

        for label, command in (actions or []):
            self.add_action(label, command)

        self._copy_button = ttk.Button(self._bar, text="Copy to clipboard",
                                      command=self._copy)
        self._close_button = ttk.Button(self._bar, text="Close",
                                        command=self.destroy)
        self._layout_bar()

        center_window(self, width, height, min_width=480, min_height=320)
        self.bind("<Escape>", lambda _e: self.destroy())

    def add_action(self, label: str, command: Callable[[], None],
                   first: bool = False) -> None:
        """Add a button to the bar. Callers may do this after construction."""
        button = ttk.Button(self._bar, text=label, command=command)
        if first:
            self._extra.insert(0, button)
        else:
            self._extra.append(button)
        if hasattr(self, "_copy_button"):
            self._layout_bar()

    def _layout_bar(self) -> None:
        for child in self._bar.winfo_children():
            child.grid_forget()
        column = 0
        for button in self._extra:
            button.grid(row=0, column=column, padx=(0, 6))
            column += 1
        self._copy_button.grid(row=0, column=column, padx=(0, 6))
        self._bar.columnconfigure(column + 1, weight=1)
        self._close_button.grid(row=0, column=column + 2, sticky="e")

    def _copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._body)

    def set_body(self, body: str) -> None:
        self._body = body
        self.viewer.set_report(body)


# ==========================================================================
# Search
# ==========================================================================


class SearchWindow(tk.Toplevel):
    def __init__(self, parent, project, on_open: Callable[[str, str], None]) -> None:
        super().__init__(parent)
        self.project = project
        self.on_open = on_open
        self.title("Find in Project")

        container = ttk.Frame(self, padding=10)
        container.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)
        container.columnconfigure(0, weight=1)

        top = ttk.Frame(container)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)

        self.query = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.query)
        entry.grid(row=0, column=0, sticky="ew")
        entry.bind("<Return>", lambda _e: self.run())
        ttk.Button(top, text="Find", command=self.run).grid(
            row=0, column=1, padx=(6, 0))

        self.summary = ttk.Label(container, text="Searches scene prose, "
                                                "character sheets and notes.",
                                 style="Hint.TLabel")
        self.summary.grid(row=1, column=0, sticky="w", pady=(6, 4))

        columns = ("kind", "name", "snippet")
        self.tree = ttk.Treeview(container, columns=columns, show="headings",
                                 height=18)
        for key, label, width in (("kind", "Where", 100),
                                  ("name", "Item", 200),
                                  ("snippet", "Match", 520)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w",
                             stretch=(key == "snippet"))
        self.tree.grid(row=2, column=0, sticky="nsew")
        scrollbar = AutoScrollbar(container, orient="vertical",
                                  command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=2, column=1, sticky="ns")
        self.tree.bind("<Double-1>", self._open_selected)
        self.tree.bind("<Return>", self._open_selected)

        ttk.Button(container, text="Close", command=self.destroy).grid(
            row=3, column=0, sticky="e", pady=(8, 0))

        center_window(self, 940, 560, min_width=560, min_height=360)
        self.bind("<Escape>", lambda _e: self.destroy())
        entry.focus_set()

    def run(self) -> None:
        needle = self.query.get().strip()
        self.tree.delete(*self.tree.get_children())
        if len(needle) < 2:
            self.summary.configure(text="Type at least two characters.")
            return
        self.summary.configure(text="Searching...")
        self.update_idletasks()
        results = self.project.search(needle)
        for kind, name, snippet in results:
            self.tree.insert("", "end", values=(kind, name, snippet))
        self.summary.configure(
            text=f"{len(results)} matches for '{needle}'. "
                 f"Double-click to open."
        )

    def _open_selected(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        kind, name, _snippet = self.tree.item(selection[0], "values")
        self.on_open(kind, name)


# ==========================================================================
# Sprint timer
# ==========================================================================


class SprintWindow(tk.Toplevel):
    """
    A countdown that reports words written during the sprint.

    Deliberately small and always-on-top so it does not compete with the page.
    """

    def __init__(self, parent, minutes: int, word_getter: Callable[[], int]) -> None:
        super().__init__(parent)
        self.title("Sprint")
        self.word_getter = word_getter
        self.total_seconds = max(60, minutes * 60)
        self.remaining = self.total_seconds
        self.start_words = word_getter()
        self.running = True
        self._job: Optional[str] = None

        container = ttk.Frame(self, padding=14)
        container.grid(row=0, column=0, sticky="nsew")

        self.clock = ttk.Label(container, text=self._format(self.remaining),
                               font=("Consolas", 30))
        self.clock.grid(row=0, column=0, columnspan=3)

        self.words = ttk.Label(container, text="0 words", style="Section.TLabel")
        self.words.grid(row=1, column=0, columnspan=3, pady=(4, 10))

        self.pause_button = ttk.Button(container, text="Pause",
                                       command=self.toggle)
        self.pause_button.grid(row=2, column=0, padx=(0, 4))
        ttk.Button(container, text="+5 min",
                   command=lambda: self.extend(5)).grid(row=2, column=1, padx=4)
        ttk.Button(container, text="Stop", command=self.stop).grid(
            row=2, column=2, padx=(4, 0))

        self.attributes("-topmost", True)
        center_window(self, 260, 170)
        self.protocol("WM_DELETE_WINDOW", self.stop)
        self.tick()

    @staticmethod
    def _format(seconds: int) -> str:
        minutes, secs = divmod(max(0, seconds), 60)
        return f"{minutes:02d}:{secs:02d}"

    def tick(self) -> None:
        if not self.winfo_exists():
            return
        if self.running:
            self.remaining -= 1
        written = max(0, self.word_getter() - self.start_words)
        self.clock.configure(text=self._format(self.remaining))
        rate = ""
        elapsed = self.total_seconds - self.remaining
        if elapsed > 60 and written:
            rate = f"  ({written / (elapsed / 60.0):.0f}/min)"
        self.words.configure(text=f"{written} words{rate}")

        if self.remaining <= 0:
            self.finish(written)
            return
        self._job = self.after(1000, self.tick)

    def toggle(self) -> None:
        self.running = not self.running
        self.pause_button.configure(text="Pause" if self.running else "Resume")

    def extend(self, minutes: int) -> None:
        self.remaining += minutes * 60
        self.total_seconds += minutes * 60
        self.clock.configure(text=self._format(self.remaining))

    def finish(self, written: int) -> None:
        self.running = False
        try:
            self.bell()
        except tk.TclError:
            pass
        messagebox.showinfo(
            "Sprint done",
            f"{written} words in {self.total_seconds // 60} minutes.\n\n"
            f"{'Good session. Stop while it still feels good.' if written else 'Nothing written - that is information, not failure. Try the block diagnostic.'}",
            parent=self,
        )
        self.destroy()

    def stop(self) -> None:
        self.running = False
        if self._job:
            try:
                self.after_cancel(self._job)
            except (ValueError, tk.TclError):
                pass
        self.destroy()


# ==========================================================================
# Writer's block diagnostic
# ==========================================================================


class BlockDiagnosticDialog(Dialog):
    """
    Five yes/no questions, asked in order of how common each cause is.

    The first 'yes' wins, because the interventions conflict: resting is the
    right answer for exhaustion and the wrong one for avoidance.
    """

    def __init__(self, parent) -> None:
        self.index = 0
        self.answers: Dict[str, bool] = {}
        super().__init__(parent, "Writer's Block Diagnostic", 620, 420)

    def build(self, parent: ttk.Frame) -> None:
        self.frame = ttk.Frame(parent)
        self.frame.grid(row=0, column=0, sticky="nsew")
        parent.rowconfigure(0, weight=1)
        self.frame.columnconfigure(0, weight=1)

        self.intro = ttk.Label(
            self.frame,
            text="Not all blocks are the same, and the fixes contradict each "
                 "other. Answer honestly - the first yes decides.",
            wraplength=540, justify="left", style="Hint.TLabel",
        )
        self.intro.grid(row=0, column=0, sticky="w", pady=(0, 14))

        self.question = ttk.Label(self.frame, text="", wraplength=540,
                                  justify="left", font=("Segoe UI", 13))
        self.question.grid(row=1, column=0, sticky="w")

        self.detail = ttk.Label(self.frame, text="", wraplength=540,
                                justify="left", style="Hint.TLabel")
        self.detail.grid(row=2, column=0, sticky="w", pady=(8, 0))

        self.progress = ttk.Label(self.frame, text="", style="Hint.TLabel")
        self.progress.grid(row=3, column=0, sticky="w", pady=(16, 0))

        self._show()

    def build_buttons(self, parent: ttk.Frame) -> None:
        ttk.Button(parent, text="Close", command=self.on_cancel).grid(
            row=0, column=0, padx=(0, 12))
        self.no_button = ttk.Button(parent, text="No",
                                    command=lambda: self._answer(False))
        self.no_button.grid(row=0, column=1, padx=(0, 6))
        self.yes_button = ttk.Button(parent, text="Yes",
                                      command=lambda: self._answer(True))
        self.yes_button.grid(row=0, column=2)

    def _show(self) -> None:
        block = structures.BLOCK_TYPES[self.index]
        self.question.configure(text=block.question)
        self.detail.configure(
            text=f"Typical symptom: {block.symptom.lower()}."
        )
        self.progress.configure(
            text=f"Question {self.index + 1} of {len(structures.BLOCK_TYPES)}"
        )

    def _answer(self, yes: bool) -> None:
        block = structures.BLOCK_TYPES[self.index]
        self.answers[block.key] = yes
        if yes:
            self._prescribe(block)
            return
        self.index += 1
        if self.index >= len(structures.BLOCK_TYPES):
            self._nothing_matched()
            return
        self._show()

    def _prescribe(self, block) -> None:
        self.result = block.key
        body = [
            f"{block.name.upper()}  ({block.share} of blocks)",
            "",
            f"Root cause:  {block.root_cause}",
            f"Symptom:     {block.symptom}",
            f"Timeline:    {block.timeline}",
            "",
            "WHAT TO DO",
            "",
        ]
        body += [f"  {i}. {step}" for i, step in enumerate(block.interventions, 1)]
        body += [
            "",
            "-" * 56,
            "",
            f"The fix in one line: {block.fix}",
        ]
        if block.key == "physiological":
            body += [
                "",
                "Note: this is the most common cause by a wide margin, and "
                "the only one where trying harder makes it worse.",
            ]
        parent = self.master
        self.destroy()
        ReportWindow(parent, f"Diagnosis: {block.name}", "\n".join(body),
                     width=680, height=560)

    def _nothing_matched(self) -> None:
        parent = self.master
        self.result = ""
        self.destroy()
        ReportWindow(
            parent, "No clear diagnosis",
            "None of the five patterns matched.\n\n"
            "That usually means one of two things:\n\n"
            "  1. The problem is the story, not you. A block that is not "
            "physiological, motivational, cognitive, behavioural or "
            "compositional is often a structural fault - you are trying to "
            "write a scene that cannot work as planned. Open the scene's "
            "craft check and see whether it has a goal, a conflict and a "
            "disaster.\n\n"
            "  2. You are between projects and this one has not started "
            "properly. Go back to Premise & Logline.\n\n"
            "Either way: the answer is not more discipline.",
            width=680, height=460,
        )


# ==========================================================================
# Outline / beat editor
# ==========================================================================


class OutlineWindow(tk.Toplevel):
    """Edit the chosen framework's beats: plan, link scenes, tick off."""

    def __init__(self, parent, project, on_change: Callable[[], None]) -> None:
        super().__init__(parent)
        self.project = project
        self.on_change = on_change
        self.title("Outline")
        self._current: Optional[str] = None
        # True while this window is rebuilding its own widgets, so the
        # selection events that causes are not mistaken for user edits.
        self._loading = False

        container = ttk.Frame(self, padding=10)
        container.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)
        container.columnconfigure(0, weight=1)

        # -- framework picker ------------------------------------------
        top = ttk.Frame(container)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(top, text="Framework").grid(row=0, column=0, padx=(0, 6))
        current = structures.framework(project.data.structure)
        self.framework_var = tk.StringVar(value=current.name)
        combo = ttk.Combobox(top, textvariable=self.framework_var,
                             values=structures.framework_names(),
                             state="readonly", width=30)
        combo.grid(row=0, column=1)
        combo.bind("<<ComboboxSelected>>", self._switch_framework)
        self.note = ttk.Label(top, text=current.note, style="Hint.TLabel",
                              wraplength=520, justify="left")
        self.note.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        top.columnconfigure(2, weight=1)

        # -- beat list -------------------------------------------------
        left = ttk.Frame(container)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        columns = ("at", "target", "done", "scenes")
        self.tree = ttk.Treeview(left, columns=columns, height=20)
        self.tree.heading("#0", text="Beat")
        self.tree.column("#0", width=210, anchor="w")
        for key, label, width in (("at", "At", 45), ("target", "Word", 70),
                                  ("done", "Done", 45), ("scenes", "Scenes", 130)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = AutoScrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # -- beat detail ------------------------------------------------
        right = ttk.Frame(container)
        right.grid(row=1, column=1, sticky="nsew")
        right.rowconfigure(3, weight=1)
        right.columnconfigure(0, weight=1)

        self.beat_name = ttk.Label(right, text="Select a beat",
                                    font=("Segoe UI", 12, "bold"))
        self.beat_name.grid(row=0, column=0, sticky="w")
        self.beat_prompt = ttk.Label(right, text="", wraplength=380,
                                      justify="left", style="Hint.TLabel")
        self.beat_prompt.grid(row=1, column=0, sticky="w", pady=(4, 8))
        ttk.Label(right, text="Your plan for this beat").grid(
            row=2, column=0, sticky="w")
        self.answer = ScrolledText(right, height=10, wrap="word")
        self.answer.grid(row=3, column=0, sticky="nsew", pady=(2, 8))
        add_editing_keys(self.answer.text)
        self.answer.nf_check = WritingCheck(self.answer.text)

        self.done_var = tk.BooleanVar()
        ttk.Checkbutton(right, text="Written", variable=self.done_var,
                        command=self._toggle_done).grid(row=4, column=0, sticky="w")

        ttk.Label(right, text="Scenes covering this beat").grid(
            row=5, column=0, sticky="w", pady=(10, 2))
        # Seven rows visible, and a novel has far more scenes than that, so
        # the list needs a scrollbar or the rest cannot be linked at all.
        scene_holder = ttk.Frame(right)
        scene_holder.grid(row=6, column=0, sticky="ew")
        scene_holder.columnconfigure(0, weight=1)
        self.scene_list = tk.Listbox(scene_holder, selectmode="extended",
                                     height=7, exportselection=False,
                                     activestyle="none")
        self.scene_list.grid(row=0, column=0, sticky="ew")
        scene_bar = AutoScrollbar(scene_holder, orient="vertical",
                                  command=self.scene_list.yview)
        scene_bar.grid(row=0, column=1, sticky="ns")
        self.scene_list.configure(yscrollcommand=scene_bar.set)

        buttons = ttk.Frame(right)
        buttons.grid(row=7, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="Save beat", command=self._save_beat).grid(
            row=0, column=0, padx=(0, 4))
        ttk.Button(buttons, text="Write Outline.docx",
                   command=self._write_doc).grid(row=0, column=1, padx=4)
        ttk.Button(buttons, text="Close", command=self._close).grid(
            row=0, column=2, padx=(4, 0))

        self._refresh()
        center_window(self, 1080, 660, min_width=700, min_height=440)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # -- data -----------------------------------------------------------
    def _refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        total = self.project.data.targets.total_words
        for beat in sorted(self.project.data.beats, key=lambda b: b.order):
            target = beat.target_word(total)
            scenes = ", ".join(
                (self.project.data.scene(sid).title
                 if self.project.data.scene(sid) else "?")
                for sid in beat.scene_ids
            )
            self.tree.insert(
                "", "end", iid=beat.key, text=beat.name,
                values=(
                    f"{int(beat.pct * 100)}%" if beat.pct is not None else "-",
                    f"{target:,}" if target else "-",
                    "yes" if beat.done else "",
                    scenes,
                ),
            )
        self._populate_scene_list()

    def _populate_scene_list(self) -> None:
        self.scene_list.delete(0, "end")
        self._scene_ids: List[str] = []
        for chapter in self.project.data.ordered_chapters():
            for scene in self.project.data.scenes_in(chapter.id):
                self._scene_ids.append(scene.id)
                self.scene_list.insert("end", f"{chapter.title} - {scene.title}")

    def _apply_scene_selection(self, beat) -> None:
        """
        Mirror a beat's linked scenes into the listbox.

        Kept separate because it must run in two places: when a beat is
        selected, and again immediately after any refresh that rebuilt the
        listbox. The listbox selection is the authoritative source of
        scene_ids, so it must never be left empty while a save can still fire.
        """
        self.scene_list.selection_clear(0, "end")
        for index, scene_id in enumerate(self._scene_ids):
            if scene_id in beat.scene_ids:
                self.scene_list.selection_set(index)

    def _on_select(self, _event=None) -> None:
        # Ignore selection events we caused ourselves while rebuilding, or the
        # save below reads a listbox that has just been emptied.
        if self._loading:
            return
        self._save_beat(quiet=True)
        selection = self.tree.selection()
        if not selection:
            return
        key = selection[0]
        beat = self.project.data.beat(key)
        if not beat:
            return
        self._current = key
        self.beat_name.configure(text=beat.name)
        self.beat_prompt.configure(text=beat.prompt)
        self.answer.set_value(beat.answer)
        self.done_var.set(beat.done)
        self._apply_scene_selection(beat)

    def _save_beat(self, quiet: bool = False) -> None:
        if not self._current:
            return
        beat = self.project.data.beat(self._current)
        if not beat:
            return
        answer = self.answer.get_value().strip()
        chosen = [self._scene_ids[i] for i in self.scene_list.curselection()]
        changed = (answer != beat.answer or chosen != beat.scene_ids
                   or bool(self.done_var.get()) != beat.done)
        beat.answer = answer
        beat.scene_ids = chosen
        beat.done = bool(self.done_var.get())
        if changed:
            self.project.mark_dirty()
            if not quiet:
                # _refresh() empties and rebuilds both the tree and the scene
                # listbox. Deleting the selected tree row queues a
                # <<TreeviewSelect>>, and when it drained it re-entered here
                # with an empty listbox and wrote scene_ids = [] - silently
                # destroying every link on the beat just saved. The guard stops
                # the re-entry and the restore puts the selection back, so the
                # listbox is never observably empty.
                self._loading = True
                try:
                    self._refresh()
                    self._apply_scene_selection(beat)
                    self.tree.selection_set(self._current)
                finally:
                    self._loading = False

    def _toggle_done(self) -> None:
        self._save_beat()

    def _switch_framework(self, _event=None) -> None:
        self._save_beat(quiet=True)
        key = structures.key_for_name(self.framework_var.get())
        framework = structures.framework(key)
        self.note.configure(text=framework.note)
        self.project.apply_structure(key, write_doc=False)
        # Clear _current before the rebuild so the selection events it queues
        # cannot save the old framework's widget contents onto a new beat.
        self._current = None
        self.beat_name.configure(text="Select a beat")
        self.beat_prompt.configure(text="")
        self.answer.set_value("")
        self._refresh()
        self.on_change()

    def _write_doc(self) -> None:
        self._save_beat(quiet=True)
        path = self.project.write_outline_doc()
        if messagebox.askyesno(
            "Outline written",
            f"Saved to:\n{path.name}\n\nOpen it in Word now?", parent=self,
        ):
            open_in_default_app(path)

    def _close(self) -> None:
        self._save_beat(quiet=True)
        self.on_change()
        self.destroy()


# ==========================================================================
# Timeline editor
# ==========================================================================


class TimelineWindow(tk.Toplevel):
    def __init__(self, parent, project, on_change: Callable[[], None]) -> None:
        super().__init__(parent)
        self.project = project
        self.on_change = on_change
        self.title("Timeline")

        container = ttk.Frame(self, padding=10)
        container.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)
        container.columnconfigure(0, weight=1)

        ttk.Label(
            container,
            text="Chronological order, which is not the same as reading order. "
                 "Dates are free text - 'Day 3', '1247', 'the Autumn before' - "
                 "and are sorted by any numbers they contain.",
            wraplength=760, justify="left", style="Hint.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        columns = ("when", "title", "kind", "who", "where", "scene", "visible")
        self.tree = ttk.Treeview(container, columns=columns, show="headings",
                                 height=18)
        widths = {"when": 90, "title": 240, "kind": 80, "who": 150,
                  "where": 110, "scene": 150, "visible": 80}
        labels = {"when": "When", "title": "Event", "kind": "Kind",
                  "who": "Who", "where": "Where", "scene": "Scene",
                  "visible": "Visibility"}
        for key in columns:
            self.tree.heading(key, text=labels[key])
            self.tree.column(key, width=widths[key], anchor="w")
        self.tree.grid(row=1, column=0, sticky="nsew")
        scrollbar = AutoScrollbar(container, orient="vertical",
                                  command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.tree.bind("<Double-1>", lambda _e: self._edit())

        bar = ttk.Frame(container)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(bar, text="Add event", command=self._add).grid(row=0, column=0)
        ttk.Button(bar, text="Edit", command=self._edit).grid(
            row=0, column=1, padx=4)
        ttk.Button(bar, text="Delete", command=self._delete).grid(row=0, column=2)
        ttk.Button(bar, text="Write Timeline.docx",
                   command=self._write).grid(row=0, column=3, padx=(12, 0))
        ttk.Button(bar, text="Close", command=self._close).grid(
            row=0, column=5, sticky="e")
        bar.columnconfigure(4, weight=1)

        self._refresh()
        center_window(self, 1020, 600, min_width=680, min_height=420)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        data = self.project.data
        for event in self.project.ordered_events():
            who = ", ".join(
                (data.entity(cid).name if data.entity(cid) else "?")
                for cid in event.character_ids
            )
            location = data.entity(event.location_id)
            scene = data.scene(event.scene_id)
            self.tree.insert(
                "", "end", iid=event.id,
                values=(event.story_date, event.title, event.kind, who,
                        location.name if location else "",
                        scene.title if scene else "",
                        "on page" if event.on_page else "backstory"),
            )

    def _selected(self):
        selection = self.tree.selection()
        if not selection:
            return None
        return next((e for e in self.project.data.events
                     if e.id == selection[0]), None)

    def _add(self) -> None:
        event = self.project.add_event("New event", "")
        self._refresh()
        self.tree.selection_set(event.id)
        self._edit()

    def _edit(self) -> None:
        event = self._selected()
        if not event:
            return
        dialog = _EventDialog(self, self.project, event)
        if dialog.show():
            event.sort_key = _sort_key(event.story_date, event.order)
            self.project.mark_dirty()
            self._refresh()
            self.on_change()

    def _delete(self) -> None:
        event = self._selected()
        if not event:
            return
        if messagebox.askyesno("Delete event",
                               f"Delete '{event.title}'?", parent=self):
            self.project.delete_event(event.id)
            self._refresh()
            self.on_change()

    def _write(self) -> None:
        path = self.project.write_timeline_doc()
        if messagebox.askyesno("Timeline written",
                               f"Saved to {path.name}.\n\nOpen it in Word?",
                               parent=self):
            open_in_default_app(path)

    def _close(self) -> None:
        self.on_change()
        self.destroy()


def _sort_key(story_date: str, fallback: int) -> float:
    from ..project import _date_sort_key

    return _date_sort_key(story_date, fallback)


class _EventDialog(Dialog):
    def __init__(self, parent, project, event) -> None:
        self.project = project
        self.event = event
        super().__init__(parent, "Timeline Event", 520, 520)

    def build(self, parent: ttk.Frame) -> None:
        scroll = ScrollFrame(parent)
        scroll.grid(row=0, column=0, sticky="nsew")
        parent.rowconfigure(0, weight=1)
        self.form = Form(scroll.body)
        data = self.project.data

        self.form.entry("Event", self.event, "title")
        self.form.entry("When", self.event, "story_date")
        self.form.hint("Free text. Numbers in it drive the sort order.")
        self.form.combo("Kind", self.event, "kind",
                        ["event", "birth", "death", "reveal", "backstory",
                         "meeting", "battle", "journey"])
        self.form.check("Happens on the page", self.event, "on_page")
        self.form.multiline("Description", self.event, "description", height=4)

        self.form.separator()
        characters = [(e.id, e.name) for e in data.entities_of("character")]
        locations = [(e.id, e.name) for e in data.entities_of("location")]
        scenes = [
            (s.id, f"{s.title}")
            for s in data.ordered_scenes()
        ]
        if characters:
            self.form.multipicker("Who", self.event, "character_ids", characters)
        if locations:
            self.form.picker("Where", self.event, "location_id", locations)
        if scenes:
            self.form.picker("Scene", self.event, "scene_id", scenes)

    def collect(self) -> bool:
        self.form.commit()
        return True


# ==========================================================================
# Backups
# ==========================================================================


class BackupsWindow(tk.Toplevel):
    def __init__(self, parent, project) -> None:
        super().__init__(parent)
        self.project = project
        self.title("Backups")

        container = ttk.Frame(self, padding=10)
        container.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)
        container.columnconfigure(0, weight=1)

        ttk.Label(
            container,
            text="Each backup is a verified zip of the whole project. "
                 "Restoring always extracts to a NEW folder - it never writes "
                 "over what you are working on.",
            wraplength=700, justify="left", style="Hint.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        columns = ("when", "size", "name")
        self.tree = ttk.Treeview(container, columns=columns, show="headings",
                                 height=15)
        for key, label, width in (("when", "When", 170), ("size", "Size", 90),
                                  ("name", "File", 420)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w")
        self.tree.grid(row=1, column=0, sticky="nsew")
        scrollbar = AutoScrollbar(container, orient="vertical",
                                  command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=1, column=1, sticky="ns")

        bar = ttk.Frame(container)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(bar, text="Back up now", command=self._create).grid(
            row=0, column=0)
        ttk.Button(bar, text="Verify", command=self._verify).grid(
            row=0, column=1, padx=4)
        ttk.Button(bar, text="Restore to new folder...",
                   command=self._restore).grid(row=0, column=2, padx=4)
        ttk.Button(bar, text="Show in Explorer",
                   command=self._reveal).grid(row=0, column=3, padx=4)
        ttk.Button(bar, text="Close", command=self.destroy).grid(
            row=0, column=5, sticky="e")
        bar.columnconfigure(4, weight=1)

        self._refresh()
        center_window(self, 800, 520, min_width=560, min_height=380)
        self.bind("<Escape>", lambda _e: self.destroy())

    def _refresh(self) -> None:
        from .. import backup

        self.tree.delete(*self.tree.get_children())
        self._paths: Dict[str, Path] = {}
        for when, size, path in backup.list_backups(self.project):
            iid = str(path)
            self._paths[iid] = path
            self.tree.insert("", "end", iid=iid, values=(when, size, path.name))

    def _selected(self) -> Optional[Path]:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Pick a backup",
                                "Select a backup from the list first.",
                                parent=self)
            return None
        return self._paths.get(selection[0])

    def _create(self) -> None:
        from .. import backup

        path, message = backup.create_backup(self.project, reason="manual")
        self._refresh()
        if path:
            messagebox.showinfo("Backed up", message, parent=self)
        else:
            messagebox.showerror("Backup failed", message, parent=self)

    def _verify(self) -> None:
        from .. import backup

        path = self._selected()
        if not path:
            return
        ok, message = backup.verify_backup(path)
        if ok:
            messagebox.showinfo("Verified",
                                f"{path.name}\n\nThe archive is intact and "
                                f"contains the project manifest.", parent=self)
        else:
            messagebox.showerror("Problem", f"{path.name}\n\n{message}",
                                 parent=self)

    def _restore(self) -> None:
        from .. import backup

        path = self._selected()
        if not path:
            return
        target = filedialog.askdirectory(
            parent=self, title="Choose an EMPTY folder to restore into",
            initialdir=str(self.project.root.parent),
        )
        if not target:
            return
        ok, message = backup.restore_backup(path, Path(target))
        if ok:
            messagebox.showinfo("Restored", message, parent=self)
            reveal_in_explorer(Path(target))
        else:
            messagebox.showerror("Restore failed", message, parent=self)

    def _reveal(self) -> None:
        reveal_in_explorer(self.project.folder("backups"))


# ==========================================================================
# Snapshots for one document
# ==========================================================================


class SnapshotsDialog(Dialog):
    def __init__(self, parent, project, document: Path, label: str) -> None:
        self.project = project
        self.document = Path(document)
        self.label = label
        super().__init__(parent, f"Versions of {label}", 640, 460)

    def build(self, parent: ttk.Frame) -> None:
        from .. import backup

        ttk.Label(
            parent,
            text="A copy is kept every time this document is saved. Restoring "
                 "one keeps the current version alongside it, so nothing is "
                 "lost either way.",
            wraplength=560, justify="left", style="Hint.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        holder = ttk.Frame(parent)
        holder.grid(row=1, column=0, sticky="nsew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(holder, height=14, activestyle="none",
                                  exportselection=False)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        snap_bar = AutoScrollbar(holder, orient="vertical",
                                 command=self.listbox.yview)
        snap_bar.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=snap_bar.set)
        parent.rowconfigure(1, weight=1)

        self.snapshots = backup.list_snapshots(self.project, self.document.stem)
        for when, path in self.snapshots:
            self.listbox.insert("end", f"{when}    {path.name[:40]}")
        if not self.snapshots:
            self.listbox.insert("end", "No versions saved yet.")

    def build_buttons(self, parent: ttk.Frame) -> None:
        ttk.Button(parent, text="Close", command=self.on_cancel).grid(
            row=0, column=0, padx=(0, 6))
        ttk.Button(parent, text="Open selected in Word",
                   command=self._open).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(parent, text="Restore selected",
                   command=self.on_ok).grid(row=0, column=2)

    def _index(self) -> Optional[int]:
        selection = self.listbox.curselection()
        if not selection or not self.snapshots:
            return None
        return selection[0]

    def _open(self) -> None:
        index = self._index()
        if index is None:
            return
        open_in_default_app(self.snapshots[index][1])

    def collect(self) -> Optional[bool]:
        from .. import backup

        index = self._index()
        if index is None:
            messagebox.showinfo("Pick a version",
                                "Select a version to restore.", parent=self)
            return None
        when, path = self.snapshots[index]
        if not messagebox.askyesno(
            "Restore version",
            f"Replace the current '{self.label}' with the version from "
            f"{when}?\n\nThe current version will be kept as a copy "
            f"next to it.",
            parent=self,
        ):
            return None
        if backup.restore_snapshot(path, self.document):
            return True
        messagebox.showerror("Could not restore",
                            "The file may be open in Word. Close it and "
                            "try again.", parent=self)
        return None


# ==========================================================================
# Simple prompts
# ==========================================================================


class TextPrompt(Dialog):
    def __init__(self, parent, title: str, prompt: str, initial: str = "",
                 hint: str = "") -> None:
        self.prompt = prompt
        self.initial = initial
        self.hint = hint
        super().__init__(parent, title, 460, 210)

    def build(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text=self.prompt, wraplength=400,
                  justify="left").grid(row=0, column=0, sticky="w")
        self.var = tk.StringVar(value=self.initial)
        entry = ttk.Entry(parent, textvariable=self.var, width=48)
        entry.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        entry.selection_range(0, "end")
        entry.focus_set()
        if self.hint:
            ttk.Label(parent, text=self.hint, style="Hint.TLabel",
                      wraplength=400, justify="left").grid(
                row=2, column=0, sticky="w", pady=(6, 0))

    def collect(self) -> Optional[str]:
        value = self.var.get().strip()
        return value or None


class ChoiceDialog(Dialog):
    def __init__(self, parent, title: str, prompt: str,
                 options: Sequence[Tuple[str, str]]) -> None:
        self.prompt = prompt
        self.options = list(options)
        super().__init__(parent, title, 460, 240)

    def build(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text=self.prompt, wraplength=400,
                  justify="left").grid(row=0, column=0, sticky="w")
        self.var = tk.StringVar(value=self.options[0][1] if self.options else "")
        combo = ttk.Combobox(parent, textvariable=self.var, state="readonly",
                             values=[label for _v, label in self.options],
                             width=44)
        combo.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        combo.focus_set()

    def collect(self) -> Optional[str]:
        label = self.var.get()
        for value, text in self.options:
            if text == label:
                return value
        return None
