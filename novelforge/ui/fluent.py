"""
Rounded controls, drawn as images.

Tk's own themes give rectangles. ttk can, however, use an *image* as an element
and cut it "9-slice" style - corners kept crisp, edges and middle repeated to
fill the widget - which is how every rounded-looking ttk theme gets its buttons
and fields. The images here are drawn with Pillow (supersampled 4x, so corners
are smooth) from the current theme's tokens, so they always match the palette.

**ttk TILES the edges and middle, it does not stretch them** (Tk 8.6), and every
tile is a separate draw call. A first version gave the images a 2px middle, so
one text field took about a thousand draws - 200 ms - and every button, every
resize, every window paid it again: the app felt broken, and the test suite went
from 25 seconds to five minutes. `MIDDLE` below is the fix; keep it large.

On a theme change the *same* image objects are repainted in place, so every
widget updates without being rebuilt. Elements can only be created once per
window, which is why creation and repainting are separate.

Two Tk facts this depends on, both learned the hard way:

* ttk finds an element by the last dotted part of its name - a scroll bar looks
  for "...trough" and "...thumb", a combo box for "...downarrow" and
  "...textarea" - so the custom elements are named to end in those words.
* Elements are only ever created once per theme, and an image that Python has
  garbage-collected vanishes from every widget using it, so the kit keeps its
  images alive for the life of the window.

If anything here fails (an old Tk, no Pillow) `install` returns False and the
flat style from styling.py is what you get. Nothing else depends on this.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk
from typing import Dict, Optional, Tuple, Union

SUPERSAMPLE = 4

#: The flat middle of every 9-slice image, in pixels. ttk repeats it to fill a
#: widget, one draw per repeat, so a wider middle means fewer draws: 64px puts a
#: whole text field at about fifteen. The middle is a flat colour, so a widget
#: smaller than this just shows part of it.
#:
#: The catch: ttk sizes an image element from its image, so a 64px middle made
#: every button, field and tab ask for at least 82px. Every 9-slice element is
#: therefore created with `width=0, height=0` (a minimum of nothing; its padding
#: supplies the real size). Forget that and the whole interface balloons.
MIDDLE = 64

#: The side of the transparent image a scroll bar's trough uses. Bigger than
#: any scroll bar is wide, so it is tiled once or twice, not hundreds of times.
TROUGH = 128

#: The interior padding of every 9-slice element. It defaults to the border (9px
#: each side), which stacked on the style's own padding made a button 47px tall.
PAD = (3, 3, 3, 3)


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------


def _new(w: int, h: int):
    from PIL import Image

    return Image.new("RGBA", (w * SUPERSAMPLE, h * SUPERSAMPLE), (0, 0, 0, 0))


def _finish(big, w: int, h: int):
    from PIL import Image

    return big.resize((w, h), Image.LANCZOS)


def rounded(w: int, h: int, radius: int, fill: Optional[str],
            outline: Optional[str] = None, outline_width: int = 1):
    """A rounded rectangle, filled and/or outlined; transparent where it is neither."""
    from PIL import ImageDraw

    ss = SUPERSAMPLE
    big = _new(w, h)
    draw = ImageDraw.Draw(big)
    radius = max(0, min(radius, min(w, h) // 2))
    if outline:
        draw.rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=radius * ss,
                               fill=outline)
        inner = max(0, radius - outline_width)
        draw.rounded_rectangle(
            (outline_width * ss, outline_width * ss,
             (w - outline_width) * ss - 1, (h - outline_width) * ss - 1),
            radius=inner * ss, fill=fill if fill else (0, 0, 0, 0))
    elif fill:
        draw.rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=radius * ss,
                               fill=fill)
    return _finish(big, w, h)


def ellipse(size: int, fill: Optional[str], outline: Optional[str] = None,
            outline_width: int = 1, dot: Optional[str] = None):
    from PIL import ImageDraw

    ss = SUPERSAMPLE
    big = _new(size, size)
    draw = ImageDraw.Draw(big)
    if outline:
        draw.ellipse((0, 0, size * ss - 1, size * ss - 1), fill=outline)
        draw.ellipse((outline_width * ss, outline_width * ss,
                      (size - outline_width) * ss - 1, (size - outline_width) * ss - 1),
                     fill=fill if fill else (0, 0, 0, 0))
    elif fill:
        draw.ellipse((0, 0, size * ss - 1, size * ss - 1), fill=fill)
    if dot:
        m = size * ss * 0.30
        draw.ellipse((m, m, size * ss - m - 1, size * ss - m - 1), fill=dot)
    return _finish(big, size, size)


def tick(image, colour: str):
    """Draw a check mark on a square image (in place) and return it."""
    from PIL import ImageDraw

    size = image.width
    ss = SUPERSAMPLE
    big = image.resize((size * ss, size * ss))
    draw = ImageDraw.Draw(big)
    points = [(size * 0.27 * ss, size * 0.53 * ss), (size * 0.43 * ss, size * 0.69 * ss),
              (size * 0.74 * ss, size * 0.32 * ss)]
    draw.line(points, fill=colour, width=max(2, int(size * 0.13 * ss)), joint="curve")
    for x, y in (points[0], points[-1]):
        r = size * 0.065 * ss
        draw.ellipse((x - r, y - r, x + r, y + r), fill=colour)
    return _finish(big, size, size)


def chevron(size: int, colour: str):
    """A small downward chevron, for combo boxes."""
    from PIL import ImageDraw

    ss = SUPERSAMPLE
    big = _new(size, size)
    draw = ImageDraw.Draw(big)
    pts = [(size * 0.28 * ss, size * 0.40 * ss), (size * 0.50 * ss, size * 0.62 * ss),
           (size * 0.72 * ss, size * 0.40 * ss)]
    draw.line(pts, fill=colour, width=max(2, int(size * 0.11 * ss)), joint="curve")
    for x, y in (pts[0], pts[-1]):
        r = size * 0.055 * ss
        draw.ellipse((x - r, y - r, x + r, y + r), fill=colour)
    return _finish(big, size, size)


def meter(w: int, h: int, fraction: float, trough: str, fill: str):
    """A rounded progress meter: a full-width trough with the filled part over it."""
    from PIL import ImageDraw

    ss = SUPERSAMPLE
    big = _new(w, h)
    draw = ImageDraw.Draw(big)
    draw.rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=h * ss // 2, fill=trough)
    fraction = max(0.0, min(1.0, fraction))
    if fraction > 0:
        end = max(h, round(w * fraction))         # never thinner than a dot
        draw.rounded_rectangle((0, 0, end * ss - 1, h * ss - 1), radius=h * ss // 2,
                               fill=fill)
    return _finish(big, w, h)


def pill(w: int, h: int, inset_x: int, inset_y: int, fill: Optional[str]):
    """A capsule inside a (w x h) transparent canvas - scroll thumbs float, not touch."""
    from PIL import ImageDraw

    ss = SUPERSAMPLE
    big = _new(w, h)
    if fill:
        draw = ImageDraw.Draw(big)
        box = (inset_x * ss, inset_y * ss, (w - inset_x) * ss - 1, (h - inset_y) * ss - 1)
        draw.rounded_rectangle(box, radius=min(box[2] - box[0], box[3] - box[1]) // 2,
                               fill=fill)
    return _finish(big, w, h)


# --------------------------------------------------------------------------
# The kit
# --------------------------------------------------------------------------


class Kit:
    """The images and elements for one window. Created once; repainted on a theme change."""

    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self.photos: Dict[str, object] = {}
        self.elements_made = False

    def photo(self, key: str, image):
        from PIL import ImageTk

        current = self.photos.get(key)
        if current is None:
            current = ImageTk.PhotoImage(image, master=self.root)
            self.photos[key] = current
        else:
            current.paste(image)
        return current


def install(root: tk.Misc, style: ttk.Style, t: Dict[str, Union[str, bool]],
            scale: float = 1.0) -> bool:
    """
    Build (first call) or repaint (later calls) the rounded controls. True on success.

    `t` is `styling.tokens(...)`; `scale` the display scale, so radii stay
    proportionate on a 150% screen.
    """
    try:
        kit: Optional[Kit] = getattr(root, "_nf_fluent", None)
        if kit is None:
            kit = Kit(root)
            root._nf_fluent = kit            # type: ignore[attr-defined]
        _paint(kit, style, t, scale)
        return True
    except Exception:
        if os.environ.get("NOVELFORGE_DEBUG"):
            import traceback

            traceback.print_exc()
        return False


def _mix(a: str, b: str, amount: float) -> str:
    from .styling import mix

    return mix(a, b, amount)


def _paint(kit: Kit, style: ttk.Style, t: Dict, scale: float) -> None:
    radius = max(4, round(7 * scale))
    border = radius + 2                       # the 9-slice margin: corners stay crisp
    side = 2 * border + MIDDLE                # see MIDDLE: a tiny middle made drawing crawl

    def nine(key: str, fill: Optional[str], outline: Optional[str] = None,
             width: int = 1):
        return kit.photo(key, rounded(side, side, radius, fill, outline, width))

    accent, panel = t["accent"], t["panel"]
    accent_press = _mix(t["accent_hover"], "#000000", 0.18)

    # -- buttons: default, accent (primary), tool (toolbar, borderless) ----------
    default = {
        "n": nine("bn", t["raised"], t["border"]),
        "a": nine("ba", t["raised_hover"], t["border_strong"]),
        "p": nine("bp", t["raised_press"], t["border_strong"]),
        "d": nine("bd", panel, t["border"]),
        "f": nine("bf", t["raised"], accent, 2),
    }
    primary = {
        "n": nine("an", accent),
        "a": nine("aa", t["accent_hover"]),
        "p": nine("ap", accent_press),
        "d": nine("ad", _mix(accent, panel, 0.55)),
        "f": nine("af", accent, t["fg"], 2),
    }
    quiet = {
        "n": nine("tn", None),
        "a": nine("ta", t["hover"]),
        "p": nine("tp", t["raised_press"]),
        "d": nine("td", None),
        "f": nine("tf", None, accent, 2),
    }

    # -- text fields ---------------------------------------------------------
    field = {
        "n": nine("fn", t["field"], t["border"]),
        "a": nine("fa", t["field"], t["border_strong"]),
        "f": nine("ff", t["field"], accent, 2),
        "d": nine("fd", panel, t["border"]),
    }

    # -- check boxes and radio buttons ----------------------------------------
    box = max(14, round(18 * scale))
    corner = max(3, round(4.5 * scale))

    gap = max(6, round(8 * scale))          # air between the box and its label

    def with_gap(img):
        from PIL import Image

        out = Image.new("RGBA", (img.width + gap, img.height), (0, 0, 0, 0))
        out.paste(img, (0, 0))
        return out

    def square(key, fill, outline, mark=None, width=1):
        img = rounded(box, box, corner, fill, outline, width)
        if mark:
            img = tick(img, mark)
        return kit.photo(key, with_gap(img))

    check = {
        "u": square("cu", t["field"], t["border_strong"]),
        "uh": square("cuh", t["field"], accent, None, 2),
        "ud": square("cud", panel, t["border"]),
        "c": square("cc", accent, accent, t["on_accent"]),
        "ch": square("cch", t["accent_hover"], t["accent_hover"], t["on_accent"]),
        "cd": square("ccd", _mix(accent, panel, 0.55), None, t["on_accent"]),
    }
    radio = {
        "u": kit.photo("ru", with_gap(ellipse(box, t["field"], t["border_strong"]))),
        "uh": kit.photo("ruh", with_gap(ellipse(box, t["field"], accent, 2))),
        "ud": kit.photo("rud", with_gap(ellipse(box, panel, t["border"]))),
        "c": kit.photo("rc", with_gap(ellipse(box, t["field"], accent, 2, dot=accent))),
        "ch": kit.photo("rch", with_gap(ellipse(box, t["field"], t["accent_hover"], 2,
                                                dot=t["accent_hover"]))),
        "cd": kit.photo("rcd", with_gap(ellipse(box, panel, t["border"], 1,
                                                dot=t["dim"]))),
    }

    # -- combo box arrow -----------------------------------------------------
    arrow_px = max(14, round(18 * scale))
    arrow = {
        "n": kit.photo("wn", chevron(arrow_px, t["text_dim"])),
        "a": kit.photo("wa", chevron(arrow_px, accent)),
        "d": kit.photo("wd", chevron(arrow_px, t["dim"])),
    }

    # -- scroll bar thumbs: capsules that float, and a transparent trough ------
    thick = max(10, round(12 * scale))
    inset = max(2, round(3 * scale))
    length = 2 * thick + MIDDLE
    v_thumb = {
        "n": kit.photo("vn", pill(thick, length, inset, 0, t["thumb"])),
        "a": kit.photo("va", pill(thick, length, inset, 0, t["thumb_hover"])),
        "d": kit.photo("vd", pill(thick, length, inset, 0, None)),
    }
    h_thumb = {
        "n": kit.photo("hn", pill(length, thick, 0, inset, t["thumb"])),
        "a": kit.photo("ha", pill(length, thick, 0, inset, t["thumb_hover"])),
        "d": kit.photo("hd", pill(length, thick, 0, inset, None)),
    }
    # The scroll bar's trough draws nothing, but ttk still TILES its image over
    # the whole trough, one draw call per tile. A 2px image over a 400px bar was
    # about six hundred calls (and a window with three scroll bars, 800 ms to
    # open), so it is a large transparent square instead - see MIDDLE.
    clear = kit.photo("clear", rounded(TROUGH, TROUGH, 0, None))

    # -- the map maker's tool rail: quiet until pointed at, tinted when chosen --
    rail = {
        "n": nine("rn", None),
        "a": nine("ra", t["hover"]),
        "s": nine("rs", _mix(accent, panel, 0.80), accent, 1),
        "sa": nine("rsa", _mix(accent, panel, 0.70), accent, 1),
    }

    # -- notebook tabs ---------------------------------------------------------
    tab = {
        "n": nine("kn", None),
        "a": nine("ka", t["hover"]),
        "s": nine("ks", t["raised"], t["border"]),
    }

    b = (border, border, border, border)
    if not kit.elements_made:
        _create_elements(kit, style, b, border, thick, inset, default, primary, quiet,
                         field, check, radio, arrow, v_thumb, h_thumb, clear, tab,
                         rail)
    _apply_layouts(style)              # every time: styling.apply() resets some of them
    kit.elements_made = True


def _create_elements(kit, style, b, border, thick, inset, default, primary, quiet,
                     field, check, radio, arrow, v_thumb, h_thumb, clear, tab,
                     rail) -> None:
    element = style.element_create

    def states(images, order):
        """('state', 'state', image) tuples, most specific first, as ttk wants them."""
        return [(*spec, images[key]) for spec, key in order]

    element("NF.Button.bg", "image", default["n"],
            *states(default, [(("disabled",), "d"), (("pressed",), "p"),
                              (("focus",), "f"), (("active",), "a")]),
            border=b, sticky="nswe", width=0, height=0, padding=PAD)
    element("NF.Accent.bg", "image", primary["n"],
            *states(primary, [(("disabled",), "d"), (("pressed",), "p"),
                              (("focus",), "f"), (("active",), "a")]),
            border=b, sticky="nswe", width=0, height=0, padding=PAD)
    element("NF.Tool.bg", "image", quiet["n"],
            *states(quiet, [(("disabled",), "d"), (("pressed",), "p"),
                            (("focus",), "f"), (("active",), "a")]),
            border=b, sticky="nswe", width=0, height=0, padding=PAD)
    element("NF.Rail.bg", "image", rail["n"],
            *states(rail, [(("selected", "active"), "sa"), (("selected",), "s"),
                           (("active",), "a")]),
            border=b, sticky="nswe", width=0, height=0, padding=PAD)
    element("NF.Field.bg", "image", field["n"],
            *states(field, [(("disabled",), "d"), (("focus",), "f"), (("active",), "a")]),
            border=b, sticky="nswe", width=0, height=0, padding=PAD)
    element("NF.Combobox.downarrow", "image", arrow["n"],
            *states(arrow, [(("disabled",), "d"), (("active",), "a")]),
            sticky="", padding=(2, 0, 4, 0))
    element("NF.Check.indicator", "image", check["u"],
            *states(check, [(("selected", "disabled"), "cd"), (("disabled",), "ud"),
                            (("selected", "active"), "ch"), (("selected",), "c"),
                            (("active",), "uh")]),
            sticky="")
    element("NF.Radio.indicator", "image", radio["u"],
            *states(radio, [(("selected", "disabled"), "cd"), (("disabled",), "ud"),
                            (("selected", "active"), "ch"), (("selected",), "c"),
                            (("active",), "uh")]),
            sticky="")
    element("NF.Vertical.Scrollbar.trough", "image", clear, sticky="nswe",
            width=0, height=0)
    element("NF.Horizontal.Scrollbar.trough", "image", clear, sticky="nswe",
            width=0, height=0)
    element("NF.Vertical.Scrollbar.thumb", "image", v_thumb["n"],
            *states(v_thumb, [(("disabled",), "d"), (("pressed",), "a"), (("active",), "a")]),
            border=(inset + 2, thick, inset + 2, thick), sticky="nswe", width=thick,
            height=0)
    element("NF.Horizontal.Scrollbar.thumb", "image", h_thumb["n"],
            *states(h_thumb, [(("disabled",), "d"), (("pressed",), "a"), (("active",), "a")]),
            border=(thick, inset + 2, thick, inset + 2), sticky="nswe", height=thick,
            width=0)
    element("NF.Tab.bg", "image", tab["n"],
            *states(tab, [(("selected",), "s"), (("active",), "a")]),
            border=b, sticky="nswe", width=0, height=0, padding=PAD)



def _apply_layouts(style: ttk.Style) -> None:
    """The same parts clam uses, with the rounded backgrounds swapped in."""

    def button_layout(bg: str):
        return [(bg, {"sticky": "nswe", "children": [
            ("Button.padding", {"sticky": "nswe", "children": [
                ("Button.label", {"sticky": "nswe"})]})]})]

    style.layout("TButton", button_layout("NF.Button.bg"))
    style.layout("Accent.TButton", button_layout("NF.Accent.bg"))
    style.layout("Tool.TButton", button_layout("NF.Tool.bg"))
    style.layout("Menu.TButton", button_layout("NF.Tool.bg"))          # a drop-down's items
    style.layout("Quiet.TButton", button_layout("NF.Tool.bg"))         # quiet, inside a card
    style.layout("Rail.Toolbutton", [("NF.Rail.bg", {"sticky": "nswe", "children": [
        ("Toolbutton.padding", {"sticky": "nswe", "children": [
            ("Toolbutton.label", {"sticky": "nswe"})]})]})])
    style.layout("Compact.TButton", button_layout("NF.Button.bg"))
    style.layout("TEntry", [("NF.Field.bg", {"sticky": "nswe", "children": [
        ("Entry.padding", {"sticky": "nswe", "children": [
            ("Entry.textarea", {"sticky": "nswe"})]})]})])
    style.layout("TCombobox", [("NF.Field.bg", {"sticky": "nswe", "children": [
        ("NF.Combobox.downarrow", {"side": "right", "sticky": ""}),
        ("Combobox.padding", {"expand": "1", "sticky": "nswe", "children": [
            ("Combobox.textarea", {"sticky": "nswe"})]})]})])
    for kind, indicator in (("Checkbutton", "NF.Check.indicator"),
                            ("Radiobutton", "NF.Radio.indicator")):
        style.layout(f"T{kind}", [(f"{kind}.padding", {"sticky": "nswe", "children": [
            (indicator, {"side": "left", "sticky": ""}),
            (f"{kind}.focus", {"side": "left", "sticky": "w", "children": [
                (f"{kind}.label", {"sticky": "nswe"})]})]})])
    for prefix in ("", "Page."):        # "Page." ones sit on the writing sheet's colour
        style.layout(f"{prefix}Vertical.TScrollbar", [("NF.Vertical.Scrollbar.trough", {
            "sticky": "ns", "children": [
                ("NF.Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        style.layout(f"{prefix}Horizontal.TScrollbar", [("NF.Horizontal.Scrollbar.trough", {
            "sticky": "we", "children": [
                ("NF.Horizontal.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    style.layout("TNotebook.Tab", [("NF.Tab.bg", {"sticky": "nswe", "children": [
        ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
            ("Notebook.label", {"side": "top", "sticky": ""})]})]})])
