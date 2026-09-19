"""
Take pictures of the real NovelForge window, safely.

    python tools/uishots/run.py                          # warm + premium, everything
    python tools/uishots/run.py --themes premium --quick # main window only
    python tools/uishots/run.py --out shots --welcome    # also the first-run screen
    python tools/uishots/run.py --client-only --themes premium   # for the website

For each theme it makes a throwaway install in a temp folder (a seeded demo
novel, and a settings file pointing at it), launches the real window against
that in a fresh process, saves PNGs into --out, and deletes the install.

Why so careful: this drives the real application, and an earlier session's
version of this went wrong twice against a writer's actual novel. Two things
make that impossible now. NOVELFORGE_SETTINGS and NOVELFORGE_PROJECTS point at
the throwaway install before the package is first imported, and shots.py
asserts the loaded novel is the demo one and lives inside the sandbox before it
touches anything.

Windows only, needs a display. It prints anything that does not fit its window.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def run(cmd, env=None) -> int:
    return subprocess.run(cmd, cwd=REPO, env=env).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="uishots-out", help="folder for the PNGs")
    parser.add_argument("--themes", nargs="+", default=["warm", "premium"])
    parser.add_argument("--quick", action="store_true",
                        help="main window only, skip the tool windows")
    parser.add_argument("--client-only", action="store_true",
                        help="crop away the title bar and frame (for the website)")
    parser.add_argument("--welcome", action="store_true",
                        help="also photograph the first-run (no novel) screen")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    failures = 0
    jobs = [(theme, False) for theme in args.themes]
    if args.welcome:
        jobs.append((args.themes[0], True))
    for theme, empty in jobs:
        # Short, shallow path: Windows' 260-character limit bites deep folders.
        sandbox = Path(tempfile.mkdtemp(prefix="nfui_"))
        try:
            print(f"\n== {theme}{' (first run)' if empty else ''} ==")
            seed = [sys.executable, str(HERE / "seed.py"), str(sandbox), theme]
            shots = [sys.executable, str(HERE / "shots.py"), str(sandbox),
                     str(out), theme + ("-first-run" if empty else "")]
            if empty:
                seed.append("empty")
                shots.append("empty")
            env = dict(os.environ)
            env["NF_QUICK"] = "1" if (args.quick or empty) else ""
            env["NF_CLIENT_ONLY"] = "1" if args.client_only else ""
            failures += bool(run(seed)) + bool(run(shots, env))
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)
    print(f"\nPictures are in {out}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
