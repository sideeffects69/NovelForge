"""
Launch the real window against a seeded throwaway install and photograph it.

    python shots.py <sandbox> <out folder> <tag> [empty]

Normally run through `run.py`. The sandbox must already hold settings.json
(made by seed.py in an earlier process - see there for why).

Set NF_QUICK=1 to take only the main-window pictures, and NF_CLIENT_ONLY=1 to
crop away Windows' title bar and frame (for the website).
"""

import os
import sys
import time
import tkinter as tk
import traceback
from pathlib import Path

SANDBOX = Path(sys.argv[1])
OUT = Path(sys.argv[2])
TAG = sys.argv[3]
EMPTY = len(sys.argv) > 4 and sys.argv[4] == "empty"

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
os.environ["NOVELFORGE_SETTINGS"] = str(SANDBOX / "settings.json")
os.environ["NOVELFORGE_PROJECTS"] = str(SANDBOX / "projects")
OUT.mkdir(parents=True, exist_ok=True)

from tools.uishots.capture import capture  # noqa: E402
from tools.uishots.clipping import clipped_content  # noqa: E402

from novelforge import config  # noqa: E402
from novelforge.ui.app import App  # noqa: E402

# Nothing that is not the throwaway install may be read or written.
inside = str(SANDBOX).lower()
assert str(config.settings_file()).lower().startswith(inside), \
    f"settings are not isolated: {config.settings_file()}"
assert str(config.projects_root()).lower().startswith(inside), \
    f"projects are not isolated: {config.projects_root()}"

app = App()
errors = []
app.report_callback_exception = lambda et, ev, tb: errors.append(
    "".join(traceback.format_exception(et, ev, tb)))


def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


pump(1.2)                      # let start-up (after 120 ms) run
if EMPTY:
    assert app.project is None, "the empty install opened a project"
else:
    assert app.project is not None, "the demo novel did not open"
    assert app.project.data.title == "The Ashfall Crown", app.project.data.title
    assert str(app.project.root).lower().startswith(inside), \
        f"opened a novel outside the sandbox: {app.project.root}"
print(f"safe: theme={config.settings['theme']} scale={app.ui_scale}")

# Fully on a 1366x768 screen: a window hanging off the edge is photographed
# with black where the screen ends, which looks like a bug and is not.
app.geometry("1340x680+0+0")
pump(0.5)


def snap(name, widget=None):
    size = capture(widget or app, str(OUT / f"{TAG}-{name}.png"),
                   client_only=bool(os.environ.get("NF_CLIENT_ONLY")))
    print("  shot", name, size)


def window_shot(name, opener, delay_ms=900):
    """Open a window (modal or not), photograph the new Toplevel, close it."""
    before = set(app.winfo_children())

    def grab():
        for w in app.winfo_children():
            if isinstance(w, tk.Toplevel) and w not in before:
                try:
                    snap(name, w)
                    found = clipped_content(w)
                    if found:
                        print("  !! does not fit:", name, found[:6])
                finally:
                    w.destroy()
                return
        print("  !! no window appeared for", name)

    app.after(delay_ms, grab)          # scheduled first: a modal loop blocks
    try:
        opener()
    except Exception:
        traceback.print_exc()
    pump(delay_ms / 1000 + 0.6)
    for w in list(app.winfo_children()):
        if isinstance(w, tk.Toplevel) and w not in before:
            w.destroy()


if EMPTY:
    snap("main-welcome")
else:
    first = next(s for s in app.project.data.scenes if s.word_count)
    app.tree.selection_set(f"scene:{first.id}")
    pump(0.8)
    snap("main-scene")

    character = app.project.data.entities_of("character")[0]
    app.tree.selection_set(f"entity:{character.id}")
    pump(0.8)
    snap("main-character")

    app.cmd_dashboard(in_pane=True)
    pump(0.5)
    snap("main-dashboard")

    app.tree.selection_set(f"scene:{first.id}")
    pump(0.6)
    windows = [] if os.environ.get("NF_QUICK") else [
        ("win-preferences", app.cmd_preferences),
        ("win-corkboard", app.cmd_corkboard),
        ("win-relationships", app.cmd_relationships),
        ("win-outline", app.cmd_outline_window),
        ("win-timeline", app.cmd_timeline_window),
        ("win-storygraph", app.cmd_story_graph),
        ("win-search", app.cmd_search),
        ("win-shortcuts", app.cmd_shortcuts),
        ("win-diagnostics", lambda: app.cmd_diagnostics("scene")),
        ("win-map", app.cmd_map_editor),
    ]
    for name, opener in windows:
        window_shot(name, opener, 1500 if name == "win-map" else 900)

    found = clipped_content(app)
    print("  main window at 1340x680:", found or "everything fits")
    width, height = app.minsize()
    app.geometry(f"{width}x{max(height, 600)}+0+0")
    pump(0.9)
    found = clipped_content(app)
    print(f"  main window at its minimum {width}px:", found or "everything fits",
          "| toolbar icons only:", app._toolbar_compact)
    snap("main-min-width")

if errors:
    print("!! exceptions inside Tk callbacks:")
    print("\n".join(errors)[:2000])
app.after(50, app.destroy)
try:
    app.mainloop()
except Exception:
    pass
print("done")
