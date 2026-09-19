"""
Rebuild every logo, icon and favicon from the three originals in brand/originals/.

    python tools/brand.py

The originals are what the writer supplied: `icon.jpg` (the N-mark on a rounded
navy tile), `logo.jpg` (the stacked emblem + wordmark) and `banner.jpg` (the wide
hero with the feature strip). They are JPEGs, so the icon arrives with a solid
black background instead of transparent corners - this cuts the rounded tile
out and produces everything else from it:

    brand/icon.png, brand/icon.ico          the application icon (window, taskbar,
                                            desktop shortcut)
    brand/banner.jpg                        README header
    site/favicon.ico + site/assets/brand/   favicons, touch icons, web manifest
                                            icons, the social-share image, the
                                            logo and banner for the pages

Nothing here is redrawn or "improved": pixels come from the originals, resized.
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

REPO = Path(__file__).resolve().parents[1]
ORIGINALS = REPO / "brand" / "originals"
BRAND = REPO / "brand"
SITE = REPO / "site"
SITE_BRAND = SITE / "assets" / "brand"

# Measured from icon.jpg (1254 x 1254, black corners): the outer edge of the bright
# ring, and the corner radius (where the ring crosses the diagonal). The mask is cut
# on the ring itself: just outside it the JPEG carries compression noise (a pure-blue
# streak along the top edge) that shows as a fringe on a light or blue background.
TILE = (59, 58, 1193, 1173)
RADIUS = 300
NAVY = (8, 31, 63)          # the tile's own colour, sampled from the interior
SITE_NAVY = "#070d17"


def cut_tile() -> Image.Image:
    """The icon tile with transparent rounded corners, as a 1024 x 1024 RGBA."""
    src = Image.open(ORIGINALS / "icon.jpg").convert("RGB")
    width, height = src.size
    scale = 4                                   # supersample the mask for clean edges
    mask = Image.new("L", (width * scale, height * scale), 0)
    left, top, right, bottom = TILE
    ImageDraw.Draw(mask).rounded_rectangle(
        (left * scale, top * scale, right * scale, bottom * scale),
        radius=RADIUS * scale, fill=255)
    mask = mask.resize((width, height), Image.LANCZOS)
    rgba = src.convert("RGBA")
    rgba.putalpha(mask)
    tile = rgba.crop((left - 1, top - 1, right + 1, bottom + 1))
    side = max(tile.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(tile, ((side - tile.width) // 2, (side - tile.height) // 2))
    return square.resize((1024, 1024), Image.LANCZOS)


def small(image: Image.Image, size: int) -> Image.Image:
    """Downscale for small icons, with a little sharpening so the mark stays legible."""
    out = image.resize((size, size), Image.LANCZOS)
    if size <= 64:
        out = out.filter(ImageFilter.UnsharpMask(radius=0.8, percent=70, threshold=2))
    return out


def full_bleed(tile: Image.Image, size: int, padding: float = 0.0) -> Image.Image:
    """Opaque square: the tile on its own navy. iOS and 'maskable' icons round it themselves."""
    canvas = Image.new("RGB", (size, size), NAVY)
    inner = int(size * (1 - 2 * padding))
    scaled = small(tile, inner)
    canvas.paste(scaled, ((size - inner) // 2, (size - inner) // 2), scaled)
    return canvas


def main() -> None:
    BRAND.mkdir(exist_ok=True)
    SITE_BRAND.mkdir(parents=True, exist_ok=True)
    tile = cut_tile()

    # -- the application icon ----------------------------------------------
    tile.save(BRAND / "icon.png", optimize=True)
    sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]
    tile.resize((256, 256), Image.LANCZOS).save(BRAND / "icon.ico", sizes=sizes)

    # -- the wide banner (README header, hero) -------------------------------
    banner = Image.open(ORIGINALS / "banner.jpg").convert("RGB")
    banner.save(BRAND / "banner.jpg", quality=88, optimize=True, progressive=True)
    banner.resize((1600, 800), Image.LANCZOS).save(
        SITE_BRAND / "banner.jpg", quality=84, optimize=True, progressive=True)

    # -- social-share image: 1200 x 630 crop of the banner --------------------
    crop_w = round(banner.height * 1200 / 630)          # keep the banner's full height
    left = max(0, (banner.width - crop_w) // 2 - 20)    # a little more of the logo side
    share = banner.crop((left, 0, left + crop_w, banner.height)).resize((1200, 630), Image.LANCZOS)
    share.save(SITE_BRAND / "og-image.jpg", quality=88, optimize=True, progressive=True)

    # -- the stacked logo -----------------------------------------------------
    logo = Image.open(ORIGINALS / "logo.jpg").convert("RGB")
    logo.resize((720, 720), Image.LANCZOS).save(
        SITE_BRAND / "logo.jpg", quality=86, optimize=True, progressive=True)

    # -- favicons and touch icons ---------------------------------------------
    tile.resize((256, 256), Image.LANCZOS).save(
        SITE / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    for size in (16, 32, 48):
        small(tile, size).save(SITE_BRAND / f"favicon-{size}.png", optimize=True)
    for size in (96, 192, 512):
        small(tile, size).save(SITE_BRAND / f"icon-{size}.png", optimize=True)
    small(tile, 256).save(SITE_BRAND / "icon-256.png", optimize=True)
    full_bleed(tile, 180).save(SITE_BRAND / "apple-touch-icon.png", optimize=True)
    full_bleed(tile, 512, padding=0.10).save(SITE_BRAND / "maskable-512.png", optimize=True)

    manifest = {
        "name": "NovelForge",
        "short_name": "NovelForge",
        "description": "A free, local-first novel-writing studio for Windows.",
        "start_url": "./",
        "display": "browser",
        "theme_color": SITE_NAVY,
        "background_color": SITE_NAVY,
        "icons": [
            {"src": "assets/brand/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "assets/brand/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "assets/brand/maskable-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    }
    (SITE / "site.webmanifest").write_text(json.dumps(manifest, indent=2) + "\n",
                                           encoding="utf-8")
    print("brand assets rebuilt")


if __name__ == "__main__":
    main()
