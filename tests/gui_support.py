"""
Shared set-up for the GUI tests: a real main window on a demo novel, with
everything that would open a native window or leave the sandbox stubbed out.

Why the stubs matter: a native message box is a modal loop the test cannot
click, so an unstubbed one freezes the run for good. And "open in Word",
"show in Explorer" and friends would launch real programs. Each stub records
that it was called, so a test can still assert "it would have asked".
"""

import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import unittest
from contextlib import contextmanager
from tkinter import colorchooser, filedialog, messagebox

from tests import SANDBOX, require_isolation

require_isolation()

from novelforge import config  # noqa: E402
from tools.uishots.seed import build_demo_novel  # noqa: E402

# What each native dialog answers. Cancel/No wherever there is a choice, so a
# command that asks "are you sure?" never goes ahead with something destructive.
_ANSWERS = {
    (messagebox, "showinfo"): "ok",
    (messagebox, "showwarning"): "ok",
    (messagebox, "showerror"): "ok",
    (messagebox, "askyesno"): False,
    (messagebox, "askokcancel"): False,
    (messagebox, "askyesnocancel"): None,
    (messagebox, "askretrycancel"): False,
    (filedialog, "askopenfilename"): "",
    (filedialog, "asksaveasfilename"): "",
    (filedialog, "askdirectory"): "",
    (colorchooser, "askcolor"): (None, None),
}


@contextmanager
def hang_guard(seconds: float, what: str):
    """
    Kill the run rather than freeze it. A GUI test that blocks - almost always
    a native dialog nothing answers - would otherwise hang the suite forever.
    """
    def bail():
        sys.stderr.write(f"\nGUI test hung for {seconds:.0f}s in: {what}\n"
                         f"(probably a native dialog that is not stubbed)\n")
        sys.stderr.flush()
        os._exit(3)

    timer = threading.Timer(seconds, bail)
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()


class Sandbox:
    """
    A real App on a demo novel (or on nothing, for a first-run test).

        box = Sandbox().start()
        ...                        # box.app, box.calls, box.errors, box.pump()
        box.stop()
    """

    def __init__(self, with_novel: bool = True, title: str = "Walk Test Novel",
                 name: str = "box") -> None:
        self.with_novel = with_novel
        self.title = title
        self.name = name
        self.calls = []            # what the stubs were asked, in order
        self.errors = []           # exceptions raised inside Tk callbacks
        self._patched = []
        self._env = {}
        self.app = None
        self.project = None

    # -- lifecycle ------------------------------------------------------
    def start(self) -> "Sandbox":
        try:
            probe = tk.Tk()
            probe.destroy()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"no display available: {exc}")

        # Own projects folder, so a first-run test really finds no novels.
        self._env["NOVELFORGE_PROJECTS"] = os.environ.get("NOVELFORGE_PROJECTS")
        projects = SANDBOX / f"projects_{self.name}"
        os.environ["NOVELFORGE_PROJECTS"] = str(projects)
        assert str(config.projects_root()).lower().startswith(str(SANDBOX).lower())

        self._stub_natives()
        config.settings["theme"] = "warm"
        if self.with_novel:
            self.project = build_demo_novel(config.projects_root(), self.title)
            config.settings["last_project"] = str(self.project.root)
        else:
            config.settings["last_project"] = ""

        from novelforge.ui.app import App

        self.app = App()
        self.app.report_callback_exception = (
            lambda et, ev, tb: self.errors.append(f"{et.__name__}: {ev}"))
        self.pump(1.0)
        self.app.geometry("1340x680+0+0")
        self.pump(0.4)
        if self.with_novel:
            assert self.app.project is not None
            assert self.app.project.data.title == self.title
            assert str(self.app.project.root).lower().startswith(
                str(SANDBOX).lower()), "opened a novel outside the sandbox"
        else:
            assert self.app.project is None
        return self

    def stop(self) -> None:
        if self.app is not None:
            # Pending timers would otherwise fire after the window is gone (the
            # next test's event loop runs them) and print "bgerror". Each is
            # cancelled on its own, and destroy() always runs: a window left
            # alive stays tkinter's default root, and the next test's images
            # would then be created against the wrong window.
            try:
                pending = self.app.tk.splitlist(self.app.tk.call("after", "info"))
            except tk.TclError:
                pending = ()
            for ident in pending:
                try:
                    self.app.after_cancel(ident)
                except tk.TclError:
                    pass
            try:
                self.app.destroy()
            except tk.TclError:
                pass
        for target, name, original in reversed(self._patched):   # last in, first out
            setattr(target, name, original)
        self._patched.clear()
        old = self._env.get("NOVELFORGE_PROJECTS")
        if old is None:
            os.environ.pop("NOVELFORGE_PROJECTS", None)
        else:
            os.environ["NOVELFORGE_PROJECTS"] = old

    # -- helpers --------------------------------------------------------
    def pump(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            self.app.update()
            time.sleep(0.02)

    def _patch(self, target, name, value) -> None:
        self._patched.append((target, name, getattr(target, name)))
        setattr(target, name, value)

    def _stub_natives(self) -> None:
        for (module, name), answer in _ANSWERS.items():
            def stub(*_a, _n=name, _answer=answer, **_k):
                self.calls.append(_n)
                return _answer
            self._patch(module, name, stub)

        def launched(label):
            def stub(*args, **_k):
                self.calls.append(label)
                return None
            return stub

        self._patch(os, "startfile", launched("startfile"))
        self._patch(subprocess, "Popen", launched("Popen"))

    def toplevels(self):
        return [w for w in self.app.winfo_children() if isinstance(w, tk.Toplevel)]
