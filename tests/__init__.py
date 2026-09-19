"""
Tests for NovelForge. Run from the repository root:

    python -m unittest discover -s tests -t .

This file runs before any test module imports `novelforge`, and that ordering is
the point. `novelforge.config` reads the settings file once, at import, into a
module-level singleton - so the throwaway settings and projects locations have
to be in the environment *before* the first import, or a test would read (and
could rewrite) the writer's real settings and open their real novel. Every test
module that touches the app goes through `require_isolation()` to prove it.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Short, shallow path: Windows' 260-character limit bites deep temp folders.
SANDBOX = Path(tempfile.mkdtemp(prefix="nf_"))
os.environ["NOVELFORGE_SETTINGS"] = str(SANDBOX / "settings.json")
os.environ["NOVELFORGE_PROJECTS"] = str(SANDBOX / "projects")


def require_isolation() -> None:
    """Refuse to run unless the app really is pointed at the sandbox."""
    from novelforge import config

    inside = str(SANDBOX).lower()
    if not (str(config.settings_file()).lower().startswith(inside)
            and str(config.projects_root()).lower().startswith(inside)):
        raise unittest.SkipTest(
            "novelforge was imported before the tests could isolate it; "
            "run with `python -m unittest discover -s tests -t .`")
