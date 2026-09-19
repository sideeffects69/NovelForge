"""
Start the app the way a writer does, as its own process.

`Write.bat` runs `python -m novelforge`. Everything else in the GUI tests builds
the window from inside Python; this is the only test that goes through the real
entry point - argument handling, DPI set-up, the crash handler, and the close
path that saves settings and takes the closing backup. The window is closed by
posting WM_CLOSE, which is exactly what the X button does.

Runs against the same throwaway settings and projects folders as everything
else (they are in the environment, and the child process inherits them).
"""

import ctypes
import json
import os
import subprocess
import sys
import time
import unittest
from ctypes import wintypes
from pathlib import Path

from tests import REPO, SANDBOX, require_isolation

require_isolation()

from novelforge import config  # noqa: E402
from tools.uishots.seed import build_demo_novel  # noqa: E402

WM_CLOSE = 0x0010


def find_window(title: str, pid: int, timeout: float) -> int:
    """
    The window titled `title` that belongs to process `pid`.

    The process id is not optional. A fresh install's window is titled just
    "NovelForge", which is also what a writer's own open window could be
    called - and this test is about to close whatever it finds.
    """
    user32 = ctypes.windll.user32
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    end = time.time() + timeout
    while time.time() < end:
        found = []

        def each(hwnd, _lparam):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                owner = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                if buffer.value == title and owner.value == pid and user32.IsWindowVisible(hwnd):
                    found.append(hwnd)
            return True

        user32.EnumWindows(enum_proc(each), 0)
        if found:
            return found[0]
        time.sleep(0.25)
    return 0


@unittest.skipUnless(sys.platform == "win32", "NovelForge is Windows-only")
class StartedByDoubleClick(unittest.TestCase):
    def launch(self, env_extra, window_title):
        """Run `python -m novelforge`, wait for its window, close it. Returns the process."""
        crash_log = REPO / "novelforge-errors.log"
        log_before = crash_log.stat().st_size if crash_log.exists() else None
        env = dict(os.environ, **env_extra)
        proc = subprocess.Popen(
            [sys.executable, "-m", "novelforge"], cwd=str(REPO), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            hwnd = find_window(window_title, proc.pid, 25)
            self.assertTrue(hwnd, f"no window titled {window_title!r} appeared; "
                                  f"process exit code {proc.poll()}")
            self.assertIsNone(proc.poll(), "the app exited by itself")
            time.sleep(1.0)                     # let start-up finish before closing
            ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.fail("the app did not close when its window was closed")
        finally:
            if proc.poll() is None:
                proc.kill()
        out, err = proc.communicate()
        self.assertEqual(proc.returncode, 0, err)
        self.assertNotIn("Traceback", err, err)
        log_after = crash_log.stat().st_size if crash_log.exists() else None
        self.assertEqual(log_after, log_before, "the app wrote to novelforge-errors.log")
        return proc

    def test_opens_the_last_novel_and_closes_cleanly(self):
        projects = SANDBOX / "projects_launch"
        novel = build_demo_novel(projects, "Launch Test Novel")
        settings_file = SANDBOX / "settings_launch.json"
        settings_file.write_text(json.dumps({
            "last_project": str(novel.root), "theme": "premium",
            "backup_on_open": False, "backup_on_close": True}), encoding="utf-8")
        self.launch({"NOVELFORGE_SETTINGS": str(settings_file),
                     "NOVELFORGE_PROJECTS": str(projects)},
                    f"Launch Test Novel - {config.APP_NAME}")

        saved = json.loads(settings_file.read_text(encoding="utf-8"))
        self.assertRegex(saved.get("window_geometry", ""), r"^\d+x\d+",
                         "closing did not remember the window size")
        self.assertEqual(saved.get("last_project"), str(novel.root))
        self.assertTrue(list((novel.root / "_Backups").glob("*(close).zip")),
                        "closing the window took no backup")

    def test_a_fresh_install_starts_on_the_welcome_screen_and_closes_cleanly(self):
        projects = SANDBOX / "projects_fresh"
        projects.mkdir(exist_ok=True)
        self.launch({"NOVELFORGE_SETTINGS": str(SANDBOX / "settings_fresh.json"),
                     "NOVELFORGE_PROJECTS": str(projects)},
                    config.APP_NAME)                       # no novel: just "NovelForge"
        self.assertEqual(list(projects.iterdir()), [], "starting a fresh install made a novel")


if __name__ == "__main__":
    unittest.main()
