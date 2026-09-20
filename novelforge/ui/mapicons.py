"""
Icons for the map maker, drawn with Pillow.

The main window takes its icons from Windows' icon font, which is fine there
but leaves nothing to show for a tool with no matching glyph (there is no
"freehand" or "erase" in it) and nothing at all on a machine without the font.
These are drawn from a few lines and polygons on a 24-unit grid, four times
oversampled so the edges are smooth, in whatever colour the theme asks for.
"""

from __future__ import annotations

import math
from typing import Dict, Tuple

NAMES = ("select", "terrain", "freehand", "pin", "label", "erase", "pan",
         "undo", "redo", "zoom_in", "zoom_out", "fit", "export", "more",
         "sparkle", "plus", "save")

_SS = 4


def draw(name: str, px: int, colour: str):
    """A transparent px-by-px RGBA image of the icon in `colour`."""
    from PIL import Image, ImageDraw

    size = px * _SS
    scale = size / 24.0
    big = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)

    def pts(points):
        return [(x * scale, y * scale) for x, y in points]

    def stroke(points, width=2.0):
        w = max(1, int(width * scale))
        d.line(pts(points), fill=colour, width=w, joint="curve")
        for x, y in (points[0], points[-1]):               # round caps
            r = width * scale / 2.0
            d.ellipse((x * scale - r, y * scale - r, x * scale + r, y * scale + r),
                      fill=colour)

    def dot(x, y, r, fill=None):
        d.ellipse(((x - r) * scale, (y - r) * scale, (x + r) * scale,
                   (y + r) * scale), fill=fill or colour)

    def ring(x, y, r, width=1.9):
        d.ellipse(((x - r) * scale, (y - r) * scale, (x + r) * scale,
                   (y + r) * scale), outline=colour, width=max(1, int(width * scale)))

    def arc(cx, cy, r, start, end, step=10):
        sign = 1 if end >= start else -1
        angles = list(range(int(start), int(end) + sign, sign * step))
        if angles[-1] != end:
            angles.append(end)
        return [(cx + r * math.cos(math.radians(a)),
                 cy - r * math.sin(math.radians(a))) for a in angles]

    if name == "select":
        d.polygon(pts([(6.2, 3), (6.2, 18.6), (10.3, 14.8), (13.2, 21.2),
                       (15.9, 20), (13, 13.7), (18.8, 13.5)]), fill=colour)
    elif name == "terrain":
        shape = [(4.5, 17.5), (7, 6.5), (15, 4.5), (20, 11), (14.5, 19.5)]
        stroke(shape + [shape[0]], 1.7)
        for x, y in shape:
            dot(x, y, 2.3)
    elif name == "freehand":
        wave = [(3 + i * 0.9, 12.5 + 5.0 * math.sin(i * 0.62)) for i in range(21)]
        stroke(wave, 2.2)
    elif name == "pin":
        dot(12, 9.4, 6.4)
        d.polygon(pts([(6.6, 12.6), (12, 22.2), (17.4, 12.6)]), fill=colour)
        dot(12, 9.4, 2.5, fill=(0, 0, 0, 0))
    elif name == "label":
        d.rectangle(pts([(4.5, 4.5), (19.5, 8)])[0] + pts([(4.5, 4.5), (19.5, 8)])[1],
                    fill=colour)
        d.rectangle(pts([(10.4, 4.5), (13.6, 20.5)])[0] + pts([(10.4, 4.5), (13.6, 20.5)])[1],
                    fill=colour)
    elif name == "erase":
        body = [(3.6, 15.4), (12.2, 6.2), (21, 13.6), (12.8, 22.2)]
        stroke(body + [body[0]], 1.8)
        stroke([(8.1, 10.8), (16.6, 18)], 1.6)
    elif name == "pan":
        stroke([(12, 6), (12, 18)], 2.0)
        stroke([(6, 12), (18, 12)], 2.0)
        for head in ([(12, 2.2), (8.4, 6.8), (15.6, 6.8)],
                     [(12, 21.8), (8.4, 17.2), (15.6, 17.2)],
                     [(2.2, 12), (6.8, 8.4), (6.8, 15.6)],
                     [(21.8, 12), (17.2, 8.4), (17.2, 15.6)]):
            d.polygon(pts(head), fill=colour)
    elif name in ("undo", "redo"):
        curve = arc(12, 13.5, 6.6, 160, -30)
        way = -1.0                                   # undo points left, redo is its mirror
        if name == "redo":
            curve = [(24 - x, y) for x, y in curve]
            way = 1.0
        stroke(curve, 2.1)
        tip = curve[0]
        d.polygon(pts([(tip[0] - 0.4 * way, tip[1] - 5.2),
                       (tip[0] - 0.4 * way, tip[1] + 3.6),
                       (tip[0] + 5.2 * way, tip[1] - 0.6)]), fill=colour)
    elif name in ("zoom_in", "zoom_out"):
        ring(10.2, 10.2, 6.6, 1.9)
        stroke([(15.3, 15.3), (20.6, 20.6)], 2.4)
        stroke([(7, 10.2), (13.4, 10.2)], 1.8)
        if name == "zoom_in":
            stroke([(10.2, 7), (10.2, 13.4)], 1.8)
    elif name == "fit":
        for corner in ([(4, 9), (4, 4), (9, 4)], [(15, 4), (20, 4), (20, 9)],
                       [(20, 15), (20, 20), (15, 20)], [(9, 20), (4, 20), (4, 15)]):
            stroke(corner, 2.0)
    elif name == "export":
        stroke([(12, 15), (12, 3.8)], 2.0)
        stroke([(7.4, 8.4), (12, 3.8), (16.6, 8.4)], 2.0)
        stroke([(4.2, 13.5), (4.2, 20), (19.8, 20), (19.8, 13.5)], 2.0)
    elif name == "more":
        for x in (5.5, 12, 18.5):
            dot(x, 12, 2.0)
    elif name == "sparkle":
        d.polygon(pts([(11, 2.2), (13.3, 8.6), (19.8, 11), (13.3, 13.4), (11, 19.8),
                       (8.7, 13.4), (2.2, 11), (8.7, 8.6)]), fill=colour)
        d.polygon(pts([(19, 14.6), (20.1, 17.4), (22.9, 18.5), (20.1, 19.6),
                       (19, 22.4), (17.9, 19.6), (15.1, 18.5), (17.9, 17.4)]), fill=colour)
    elif name == "plus":
        stroke([(12, 5), (12, 19)], 2.4)
        stroke([(5, 12), (19, 12)], 2.4)
    elif name == "save":
        stroke([(4.5, 4.5), (17, 4.5), (19.5, 7), (19.5, 19.5), (4.5, 19.5), (4.5, 4.5)], 1.8)
        d.rectangle(pts([(8, 4.5), (15.5, 9.4)])[0] + pts([(8, 4.5), (15.5, 9.4)])[1],
                    fill=colour)
        d.rectangle(pts([(7.6, 13.6), (16.4, 19.5)])[0] + pts([(7.6, 13.6), (16.4, 19.5)])[1],
                    outline=colour, width=max(1, int(1.6 * scale)))
    return big.resize((px, px), Image.LANCZOS)


class IconCache:
    """PhotoImages of these icons, per colour, kept alive for the window's life."""

    def __init__(self, master, px: int) -> None:
        self.master = master
        self.px = px
        self._images: Dict[Tuple[str, str], object] = {}

    def get(self, name: str, colour: str):
        key = (name, colour)
        image = self._images.get(key)
        if image is None:
            try:
                from PIL import ImageTk

                image = ImageTk.PhotoImage(draw(name, self.px, colour),
                                           master=self.master)
            except Exception:
                return None
            self._images[key] = image
        return image
