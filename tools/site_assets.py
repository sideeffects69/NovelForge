"""
Make the website's pictures: screenshots of the app and sample maps.

    python tools/uishots/run.py --out shots --themes premium --client-only
    python tools/site_assets.py --shots shots

The first command photographs the real window (main window, dashboard,
corkboard, outline, story graph) against a disposable demo novel. This script
copies those into `site/assets/screenshots/` under the names the pages use, then
takes the three pictures the harness cannot - the Map Maker showing a generated
world, the command palette over the main window, and the sample maps - and
writes them beside them. Windows only, needs a display.

Everything runs against a throwaway novel and settings file (`tests.gui_support`
sets that up before the app is imported); the demo novel's title is asserted
before anything is photographed, for the reason given in CLAUDE.md ("If you drive
the real GUI to test it").
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SITE = ROOT / "site" / "assets"

# Where each page picture comes from in the uishots output.
FROM_HARNESS = {
    "main-editor": "premium-main-scene.png",
    "dashboard": "premium-main-dashboard.png",
    "corkboard": "premium-win-corkboard.png",
    "outline": "premium-win-outline.png",
    "story-graph": "premium-win-storygraph.png",
}

SAMPLES = (("map-classic", "Classic fantasy world", 7),
           ("map-archipelago", "Island archipelago", 3),
           ("map-inland-sea", "Inland sea", 5))


def copy_harness_shots(folder: Path) -> None:
    from PIL import Image

    (SITE / "screenshots").mkdir(parents=True, exist_ok=True)
    for name, source in FROM_HARNESS.items():
        src = folder / source
        if not src.exists():
            print(f"  missing {src.name} (run tools/uishots/run.py first)")
            continue
        Image.open(src).convert("RGB").save(SITE / "screenshots" / f"{name}.png", optimize=True)
        print("  screenshots/", name)


def sample_maps() -> None:
    from PIL import Image

    from novelforge import mapgen, mapmaker as mm

    (SITE / "maps").mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="nfmaps_"))
    try:
        for name, preset, seed in SAMPLES:
            gm = mapgen.generate(mapgen.preset(preset, seed))
            png = scratch / f"{name}.png"
            mm.render_png(gm, png, scale=2 / 3)                 # 1800x1200 -> 1200x800
            Image.open(png).convert("RGB").save(
                SITE / "maps" / f"{name}.jpg", quality=88, optimize=True, progressive=True)
            print(f"  maps/{name}.jpg  ('{gm.name}', {preset}, seed {seed})")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def app_pictures() -> None:
    import tests  # noqa: F401  (points settings and projects at a throwaway folder)
    from PIL import Image, ImageDraw, ImageFilter

    from novelforge import mapgen
    from novelforge.ui.mapeditor import MapEditor
    from novelforge.ui.palette import CommandPalette
    from tests.gui_support import Sandbox
    from tools.uishots.capture import capture

    box = Sandbox(title="The Ashfall Crown", name="siteassets").start()
    app = box.app
    assert app.project.data.title == "The Ashfall Crown", app.project.data.title
    scratch = Path(tempfile.mkdtemp(prefix="nfshots_"))
    out = SITE / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    try:
        app.cmd_theme("premium")
        app.geometry("1340x680+0+0")
        box.pump(0.8)

        # The Map Maker with a generated world.
        editor = MapEditor(app, app.project)
        box.pump(0.8)
        editor.gm = mapgen.generate(mapgen.preset("Classic fantasy world", 7))
        editor.map_file = None
        editor.dirty = True
        editor._after_load()
        counts: dict = {}
        for shape in editor.gm.shapes:
            counts[shape.kind] = counts.get(shape.kind, 0) + 1
        editor._say(f"Generated '{editor.gm.name}': {counts.get('land', 0)} landmasses, "
                    f"{counts.get('river', 0)} rivers, {len(editor.gm.pins)} settlements. "
                    f"Everything is editable - press Save to keep it.")
        editor.geometry("1340x680+0+0")
        box.pump(1.4)
        capture(editor, str(scratch / "map.png"), client_only=True)
        Image.open(scratch / "map.png").convert("RGB").save(out / "map-maker.png", optimize=True)
        print("  screenshots/ map-maker")
        editor.destroy()
        box.pump(0.4)

        # The command palette over the main window (two windows, so composite them).
        scene = next(s for s in app.project.data.scenes if s.word_count)
        app.tree.selection_set(f"scene:{scene.id}")
        box.pump(0.6)
        app.cmd_palette()
        box.pump(0.6)
        palette = next(w for w in app.winfo_children() if isinstance(w, CommandPalette))
        palette.query.set("story")
        box.pump(0.5)
        capture(app, str(scratch / "main.png"), client_only=True)
        capture(palette, str(scratch / "palette.png"))
        main = Image.open(scratch / "main.png").convert("RGBA")
        pal = Image.open(scratch / "palette.png").convert("RGBA")
        x = palette.winfo_rootx() - app.winfo_rootx()
        y = palette.winfo_rooty() - app.winfo_rooty()
        shadow = Image.new("RGBA", main.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rectangle((x + 4, y + 10, x + pal.width + 4, y + pal.height + 12),
                                         fill=(0, 0, 0, 150))
        main = Image.alpha_composite(main, shadow.filter(ImageFilter.GaussianBlur(14)))
        main.paste(pal, (x, y))
        main.convert("RGB").save(out / "command-palette.png", optimize=True)
        print("  screenshots/ command-palette")
        palette.destroy()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        box.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--shots", help="the folder tools/uishots/run.py wrote its PNGs to")
    parser.add_argument("--skip-app", action="store_true",
                        help="only the sample maps (no window is opened)")
    args = parser.parse_args()

    print("Sample maps")
    sample_maps()
    if args.shots:
        print("Screenshots from the harness")
        copy_harness_shots(Path(args.shots))
    if not args.skip_app:
        print("Screenshots of the map maker and the palette")
        app_pictures()
    print("Now run: python tools/build_site.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
