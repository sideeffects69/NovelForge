"""
Application paths and user settings.

Settings live in a single JSON file next to the novelforge package so the
whole tool stays portable - copy the folder, keep your preferences.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict

from . import APP_NAME, APP_VERSION

# --------------------------------------------------------------------------
# Locations
# --------------------------------------------------------------------------


def app_root() -> Path:
    """The folder containing the novelforge package (your 'Writing Bot' dir)."""
    return Path(__file__).resolve().parent.parent


def projects_root() -> Path:
    """
    Where novel projects live. Created on first access.

    NOVELFORGE_PROJECTS overrides the location, for the same reason
    NOVELFORGE_SETTINGS exists: startup falls back to opening the first
    project found here when no `last_project` is remembered, so any test
    that launches the real window against an "empty" install would
    otherwise open - and could write to - a real novel. It also lets
    projects live on another drive.
    """
    override = os.environ.get("NOVELFORGE_PROJECTS")
    p = Path(override) if override else app_root() / "Projects"
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_file() -> Path:
    """
    Where preferences are kept.

    NOVELFORGE_SETTINGS overrides the location. That exists so the tests can
    run against a throwaway file instead of the real one - without it, a test
    that opens a project in a temp folder rewrites `last_project` and the next
    real start tries to open a directory that has since been deleted. It is
    also a genuine convenience: it lets one copy of the tool be run with
    different preferences, say from a USB stick.
    """
    override = os.environ.get("NOVELFORGE_SETTINGS")
    if override:
        path = Path(override)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return app_root() / "novelforge-settings.json"


# --------------------------------------------------------------------------
# Folder names inside a project. Numbered so Windows Explorer sorts them
# in a sensible reading order rather than alphabetically.
# --------------------------------------------------------------------------

FOLDERS: Dict[str, str] = {
    "manuscript": "00 Manuscript",
    "outline": "01 Outline",
    "characters": "02 Characters",
    "locations": "03 Locations",
    "items": "04 Items",
    "factions": "05 Factions",
    "threads": "06 Plot Threads",
    "world": "07 World Bible",
    "timeline": "08 Timeline",
    "research": "09 Research",
    "notes": "10 Notes",
    "publishing": "11 Publishing",
    "continuity": "12 Continuity",
    "maps": "13 Maps",
    "compiled": "_Compiled",
    "snapshots": "_Snapshots",
    "backups": "_Backups",
    "drafts": "_Drafts",
    "trash": "_Trash",
}

MANIFEST_NAME = "project.json"


# --------------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------------

DEFAULT_SETTINGS: Dict[str, Any] = {
    # -- manuscript typography ------------------------------------------
    # Times New Roman is the modern industry default; Courier New is the
    # classic Shunn standard-manuscript face. Both are accepted.
    "manuscript_font": "Times New Roman",
    "manuscript_font_size": 12,
    "manuscript_line_spacing": 2.0,
    "manuscript_first_line_indent": 0.5,
    "manuscript_margin": 1.0,
    "scene_separator": "#",
    # -- editor ----------------------------------------------------------
    "editor_font": "Georgia",
    "editor_font_size": 13,
    # editor_wrap_width and composition_block_pause_seconds used to live here
    # and nothing ever read either of them. Removed rather than left as knobs
    # that do nothing. An old settings file that still contains them keeps
    # them harmlessly - Settings.load preserves unknown keys so a downgrade
    # loses nothing.
    "theme": "warm",  # light | dark | warm
    "focus_mode": False,
    "typewriter_scroll": False,
    "autosave_seconds": 30,
    # -- sprints ---------------------------------------------------------
    "sprint_minutes": 25,
    # -- targets ---------------------------------------------------------
    "default_target_words": 90000,
    "default_daily_target": 1000,
    # -- safety ----------------------------------------------------------
    "backup_on_open": True,
    "backup_on_close": True,
    "backup_retention": 25,
    "snapshot_on_save": True,
    "snapshot_retention_per_doc": 40,
    # Off by default: the Map Maker keeps unsaved work by saving it, rather
    # than by asking. Turn this on to be asked instead.
    "map_prompt_on_close": False,
    # -- writing check ----------------------------------------------------
    "live_writing_check": True,
    # -- session ---------------------------------------------------------
    "last_project": "",
    "window_geometry": "1400x880",
}


class Settings:
    """Thin dict-like wrapper that persists to JSON on every change."""

    def __init__(self) -> None:
        self._data: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.load()

    # -- dict interface -------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self._data.get(key, DEFAULT_SETTINGS.get(key))

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULT_SETTINGS.get(key, default))

    def update(self, values: Dict[str, Any]) -> None:
        self._data.update(values)
        self.save()

    def as_dict(self) -> Dict[str, Any]:
        return dict(self._data)

    # -- persistence ----------------------------------------------------
    def load(self) -> None:
        path = settings_file()
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
            if isinstance(stored, dict):
                # Unknown keys are kept so a downgrade doesn't lose them.
                self._data.update(stored)
        except (ValueError, OSError, UnicodeDecodeError):
            # A corrupt settings file must never stop the app from starting.
            # ValueError covers json.JSONDecodeError; UnicodeDecodeError is a
            # *different* branch of the hierarchy and a file that is not valid
            # UTF-8 would otherwise crash before the window ever appeared.
            pass

    def save(self) -> None:
        from .atomic import write_json_atomic

        payload = dict(self._data)
        payload["_app"] = APP_NAME
        payload["_version"] = APP_VERSION
        try:
            write_json_atomic(settings_file(), payload)
        except OSError:
            pass


# Module-level singleton - the app has exactly one settings file.
settings = Settings()


# --------------------------------------------------------------------------
# Colour themes for the editor and binder
# --------------------------------------------------------------------------

THEMES: Dict[str, Dict[str, str]] = {
    "light": {
        "bg": "#ffffff",
        "fg": "#1a1a1a",
        "panel": "#f2f2f4",
        "panel_fg": "#1a1a1a",
        "accent": "#2f5d8a",
        "dim": "#9a9a9a",
        "select": "#cfe0f0",
        "caret": "#1a1a1a",
        "gutter": "#e6e6e9",
    },
    "dark": {
        "bg": "#1d1f21",
        "fg": "#d8d4cf",
        "panel": "#26282b",
        "panel_fg": "#d8d4cf",
        "accent": "#7aa2c4",
        "dim": "#5e6266",
        "select": "#3a4552",
        "caret": "#e8e4df",
        "gutter": "#2f3134",
    },
    "warm": {
        "bg": "#f6efe2",
        "fg": "#33291d",
        "panel": "#e9dfcc",
        "panel_fg": "#33291d",
        "accent": "#8a5a2b",
        "dim": "#a3937c",
        "select": "#dcc9a6",
        "caret": "#33291d",
        "gutter": "#ded2ba",
    },
    # A writer's desk at night: deep navy workspace, ivory manuscript text,
    # electric blue as the one accent - not a repaint of every pixel blue.
    # Same 9 keys as every other theme here, so nothing that reads
    # theme() needed to change to support it.
    "premium": {
        "bg": "#0a1220",
        "fg": "#f4f1e8",
        "panel": "#0c1524",
        "panel_fg": "#dce5ef",
        "accent": "#2b9cf4",
        "dim": "#7f8da0",
        "select": "#1b3150",
        "caret": "#56c8ff",
        "gutter": "#142238",
    },
}


def theme() -> Dict[str, str]:
    """
    The active palette.

    str() because a hand-edited settings file could hold a number or null for
    the theme, and an unhashable or non-string key would raise rather than fall
    back - which would take the whole window down on start-up.
    """
    name = settings["theme"]
    return THEMES.get(str(name) if name is not None else "", THEMES["warm"])


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def reveal_in_explorer(path: Path) -> None:
    """Open a folder, or select a file inside its folder, in Explorer."""
    path = Path(path)
    try:
        if path.is_dir():
            os.startfile(str(path))  # noqa: S606 - intentional shell open
        else:
            # A list of args, not a shell string: Windows filenames can
            # legally contain characters (&, |, ^, ...) that cmd.exe treats
            # as metacharacters, so building this as a string for os.system
            # let an oddly-named file or a typed backup label change what
            # actually runs. subprocess with a list bypasses the shell
            # entirely, so the path is passed through literally either way.
            subprocess.Popen(["explorer", f"/select,{path}"])
    except OSError:
        pass


def open_in_default_app(path: Path) -> bool:
    """Hand a file to Word (or whatever owns .docx). True if it launched."""
    try:
        os.startfile(str(Path(path)))  # noqa: S606
        return True
    except (OSError, AttributeError):
        return False
