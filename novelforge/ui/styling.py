"""
The look of the whole app: one flat, modern ttk style applied to every theme.

Why this file exists
--------------------
Windows' native "vista" ttk theme draws buttons, entries, combo boxes, scroll
bars and progress bars with the operating system's own renderer, which ignores
every ttk.Style colour. That is why the app used to look like a 2005 dialog box
in every palette, and why the dark palettes had white boxes floating in them.
"clam" is drawn entirely by Tk, so it obeys colours - this module turns it into
a flat, quiet style and derives everything from the palette's nine base colours
(see `config.THEMES`), so adding a theme is still just adding one dict.

What it does not do: menus. The menu bar and dropdowns are owned by Windows and
cannot be recoloured from Tk without replacing them with hand-drawn widgets.

Speed: everything here runs once at start-up (and again on a theme change).
Nothing runs per keystroke or per mouse-move; tooltips only cost anything while
hovered.
"""

from __future__ import annotations

import ctypes
import os
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

from ..config import app_root, theme

UI_FONT = "Segoe UI"        # becomes Segoe UI Variable Text on Windows 11 (resolve_font)

# Type scale, in points. One place, so "a bit bigger" is a one-line change.
BASE, SMALL, LEAD, TITLE, DISPLAY, HERO = 10, 9, 12, 15, 21, 28


def resolve_font(root: tk.Misc) -> str:
    """Windows 11's own UI face if it is installed, otherwise plain Segoe UI."""
    global UI_FONT
    try:
        import tkinter.font as tkfont

        families = {name.lower() for name in tkfont.families(root)}
        for name in ("Segoe UI Variable Text", "Segoe UI"):
            if name.lower() in families:
                UI_FONT = name
                break
    except Exception:
        pass
    return UI_FONT


# --------------------------------------------------------------------------
# Colour maths
# --------------------------------------------------------------------------


def _rgb(colour: str) -> Tuple[int, int, int]:
    c = colour.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def mix(a: str, b: str, amount: float) -> str:
    """`a` moved `amount` (0..1) of the way towards `b`."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex([x + (y - x) * amount for x, y in zip(ra, rb)])


def _linear(channel: float) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(colour: str) -> float:
    r, g, b = _rgb(colour)
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio, 1 (identical) to 21 (black on white)."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def readable_on(background: str, light: str = "#ffffff",
                dark: str = "#0b1220") -> str:
    """Whichever of `light`/`dark` reads better on `background`."""
    return light if contrast(background, light) >= contrast(background, dark) \
        else dark


def ensure_contrast(colour: str, background: str, target: float = 3.6) -> str:
    """`colour`, pushed towards black or white only as far as needed to be legible."""
    if contrast(colour, background) >= target:
        return colour
    pole = "#000000" if luminance(background) > 0.5 else "#ffffff"
    for step in range(1, 11):
        candidate = mix(colour, pole, step / 10)
        if contrast(candidate, background) >= target:
            return candidate
    return pole


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------


def tokens(palette: Dict[str, str]) -> Dict[str, Union[str, bool]]:
    """
    The palette's nine base colours plus everything derived from them.

    Derived rather than stored so a theme stays nine numbers, and so a new one
    gets hover states, borders and legible secondary text for free.
    """
    t: Dict[str, Union[str, bool]] = dict(palette)
    dark = luminance(palette["panel"]) < 0.25
    white = "#ffffff"
    panel, fg, accent = palette["panel"], palette["panel_fg"], palette["accent"]

    t["dark"] = dark
    t["field"] = palette["bg"]                       # inset: editor colour
    t["raised"] = mix(panel, white, 0.07 if dark else 0.55)
    t["raised_hover"] = mix(t["raised"], accent, 0.20 if dark else 0.16)
    t["raised_press"] = mix(t["raised"], accent, 0.34 if dark else 0.28)
    t["hover"] = mix(panel, fg, 0.09 if dark else 0.08)
    t["border"] = mix(panel, fg, 0.20 if dark else 0.17)
    t["border_strong"] = mix(panel, fg, 0.36 if dark else 0.32)
    t["thumb"] = mix(panel, fg, 0.20 if dark else 0.18)
    t["thumb_hover"] = mix(panel, fg, 0.38 if dark else 0.36)
    t["row_select"] = mix(panel, accent, 0.30 if dark else 0.22)
    t["accent_hover"] = mix(accent, white if dark else "#000000", 0.16)
    t["on_accent"] = readable_on(accent)
    # Layered surfaces, back to front: the window behind everything, cards (the
    # binder, the editor, the inspector) standing on it, and the writing sheet
    # or a field inset into a card. A step apart each, so depth comes from tone
    # and a hairline, not from shadows Tk cannot draw.
    t["window"] = mix(panel, "#000000", 0.38) if dark else mix(panel, fg, 0.075)
    t["card_border"] = mix(panel, white, 0.075) if dark else mix(panel, fg, 0.10)

    # Secondary text: the palette's `dim` is fine for decoration but too faint
    # for hints someone actually needs to read (about 2:1 on the warm panel).
    # Take the dimmest blend of text and panel that still reaches 4.5:1.
    text_dim = fg
    for amount in (0.55, 0.50, 0.45, 0.40, 0.35, 0.30, 0.25, 0.20, 0.10, 0.0):
        candidate = mix(fg, panel, amount)
        if contrast(candidate, panel) >= 4.5:
            text_dim = candidate
            break
    t["text_dim"] = text_dim
    return t


def current_tokens() -> Dict[str, Union[str, bool]]:
    return tokens(theme())


# --------------------------------------------------------------------------
# Applying it
# --------------------------------------------------------------------------


def apply(root: tk.Misc, style: ttk.Style, palette: Dict[str, str],
          scale: float = 1.0) -> Dict[str, Union[str, bool]]:
    """Configure ttk and Tk's option database for `palette`. Returns the tokens."""
    t = tokens(palette)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    resolve_font(root)
    ui = (UI_FONT, BASE)
    bold = (UI_FONT, BASE, "bold")
    panel, fg = t["panel"], t["panel_fg"]
    window = t["window"]

    style.configure(
        ".", background=panel, foreground=fg, font=ui,
        bordercolor=t["border"], darkcolor=panel, lightcolor=panel,
        troughcolor=t["gutter"], focuscolor=t["accent"],
        selectbackground=t["select"], selectforeground=t["fg"],
        insertcolor=t["caret"], fieldbackground=t["field"],
    )
    style.map(".", foreground=[("disabled", t["dim"])])

    # -- labels ---------------------------------------------------------
    style.configure("TFrame", background=panel)
    style.configure("TLabel", background=panel, foreground=fg)
    style.configure("Section.TLabel", font=bold, foreground=t["accent"])
    style.configure("Field.TLabel", font=ui)
    style.configure("Hint.TLabel", font=(UI_FONT, SMALL), foreground=t["text_dim"])
    style.configure("Value.TLabel", font=ui)
    style.configure("Status.TLabel", font=ui, foreground=t["text_dim"])
    style.configure("Title.TLabel", font=(UI_FONT, TITLE, "bold"))
    style.configure("Hero.TLabel", font=(UI_FONT, HERO, "bold"))
    style.configure("Lead.TLabel", font=(UI_FONT, LEAD), foreground=t["text_dim"])
    style.configure("CardTitle.TLabel", font=(UI_FONT, BASE + 1, "bold"),
                    background=t["raised"])
    style.configure("CardText.TLabel", font=ui, foreground=t["text_dim"],
                    background=t["raised"])
    style.configure("Card.TFrame", background=t["raised"])
    style.configure("Rule.TFrame", background=t["border"])
    # The window's own chrome (menu bar, toolbar, status bar) sits on the backdrop,
    # not on a card, so it needs its own colour behind the text.
    style.configure("Page.TFrame", background=t["bg"])
    style.configure("Chrome.TFrame", background=window)
    style.configure("Chrome.TLabel", background=window, foreground=fg)
    style.configure("Chrome.Hint.TLabel", background=window, foreground=t["text_dim"],
                    font=(UI_FONT, SMALL))
    style.configure("Chrome.Status.TLabel", background=window,
                    foreground=t["text_dim"], font=ui)
    style.configure("Chrome.TSeparator", background=t["border"])
    # The editor's header: a small letter-spaced kicker over a large serif title.
    style.configure("Kicker.TLabel", font=(UI_FONT, SMALL, "bold"),
                    foreground=t["accent"])
    style.configure("Display.TLabel", font=("Georgia", DISPLAY))
    style.configure("Brand.TLabel", font=("Georgia", TITLE, "bold"))
    style.configure("Project.TLabel", font=(UI_FONT, LEAD, "bold"))

    # -- buttons --------------------------------------------------------
    def button(name: str, base: str, hover: str, press: str, text: str,
               border: str, pad: Tuple[int, int] = (14, 6),
               font=ui) -> None:
        style.configure(
            name, background=base, foreground=text, bordercolor=border,
            lightcolor=base, darkcolor=base, focuscolor=base,
            relief="flat", borderwidth=1, padding=pad, anchor="center",
            font=font,
        )
        state_bg = [("disabled", panel), ("pressed", press), ("active", hover)]
        style.map(
            name, background=state_bg,
            lightcolor=state_bg, darkcolor=state_bg,
            bordercolor=[("focus", t["accent"]), ("pressed", press),
                         ("active", hover if border == base else border)],
            foreground=[("disabled", t["dim"])],
        )

    button("TButton", t["raised"], t["raised_hover"], t["raised_press"], fg,
           t["border"])
    # For dense rows of buttons (the map editor's toolbar has fifteen): the
    # roomier default pushed the last four - and the coordinate readout - off
    # the edge of the window.
    button("Compact.TButton", t["raised"], t["raised_hover"], t["raised_press"],
           fg, t["border"], pad=(4, 3))
    style.configure("Compact.TButton", width=0)     # natural width; see Tool.TButton
    button("Accent.TButton", t["accent"], t["accent_hover"], t["accent_hover"],
           t["on_accent"], t["accent"], font=bold)
    # A quiet button for use *inside a card* (Tool.TButton is for the window's
    # own bar): rounded corners have to blend with whatever is behind them.
    button("Quiet.TButton", panel, t["hover"], t["raised_press"], fg, panel,
           pad=(9, 7))
    style.configure("Quiet.TButton", width=0)
    # Items in a drop-down list: flat, left-aligned, lit on hover.
    button("Menu.TButton", t["raised"], t["hover"], t["raised_press"], fg,
           t["raised"], pad=(12, 7))
    style.configure("Menu.TButton", width=0, anchor="w")
    # The tool rail's buttons: an icon, tinted when its tool is the chosen one.
    style.configure("Rail.Toolbutton", padding=(9, 9), anchor="center",
                    relief="flat", borderwidth=0, background=panel,
                    foreground=fg)
    # The toolbar's quiet buttons: no outline until you point at them.
    button("Tool.TButton", panel, t["hover"], t["raised_press"], fg, panel,
           pad=(10, 7))
    # clam gives every button an 11-character minimum width, which made the
    # toolbar buttons roomy enough to push the toolbar off a small screen.
    style.configure("Tool.TButton", width=0)

    # -- text fields ----------------------------------------------------
    focus = [("focus", t["accent"])]
    for name in ("TEntry", "TSpinbox"):
        style.configure(
            name, fieldbackground=t["field"], foreground=t["fg"],
            bordercolor=t["border"], lightcolor=t["field"],
            darkcolor=t["field"], insertcolor=t["caret"], padding=(9, 5),
            borderwidth=1, selectbackground=t["select"],
            selectforeground=t["fg"], arrowcolor=t["text_dim"],
            background=t["field"],
        )
        style.map(
            name, bordercolor=focus, lightcolor=focus, darkcolor=focus,
            fieldbackground=[("disabled", panel), ("readonly", panel)],
            foreground=[("disabled", t["dim"])],
        )
    style.configure(
        "TCombobox", fieldbackground=t["field"], background=t["field"],
        foreground=t["fg"], arrowcolor=t["text_dim"],
        bordercolor=t["border"], lightcolor=t["field"], darkcolor=t["field"],
        padding=(9, 5), arrowsize=14, selectbackground=t["field"],
        selectforeground=t["fg"],
    )
    style.map(
        "TCombobox",
        fieldbackground=[("disabled", panel), ("readonly", t["field"])],
        background=[("active", t["raised_hover"]), ("pressed", t["raised_press"])],
        selectbackground=[("readonly", t["field"])],
        selectforeground=[("readonly", t["fg"])],
        bordercolor=focus, lightcolor=focus, darkcolor=focus,
        arrowcolor=[("active", t["accent"])],
    )

    # -- check boxes and radio buttons ----------------------------------
    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(
            name, background=panel, foreground=fg, focuscolor=panel,
            indicatorbackground=t["field"], indicatorforeground=t["on_accent"],
            upperbordercolor=t["border_strong"],
            lowerbordercolor=t["border_strong"], indicatormargin=(2, 2, 6, 2),
            padding=(2, 2),
        )
        style.map(
            name,
            background=[("active", panel)],
            indicatorbackground=[("disabled", panel),
                                 ("selected", t["accent"]),
                                 ("active", t["raised_hover"])],
            upperbordercolor=[("selected", t["accent"]),
                              ("active", t["accent"])],
            lowerbordercolor=[("selected", t["accent"]),
                              ("active", t["accent"])],
            foreground=[("disabled", t["dim"])],
        )
    # A radio button's dot is drawn in the indicator foreground, on the field.
    style.map(
        "TRadiobutton",
        indicatorbackground=[("disabled", panel), ("selected", t["field"]),
                             ("active", t["raised_hover"])],
        indicatorforeground=[("selected", t["accent"])],
    )

    # -- scroll bars: a slim thumb, no arrow buttons --------------------
    for orient, sticky in (("Vertical", "ns"), ("Horizontal", "we")):
        name = f"{orient}.TScrollbar"
        style.layout(name, [(f"{orient}.Scrollbar.trough", {
            "sticky": sticky,
            "children": [(f"{orient}.Scrollbar.thumb",
                          {"expand": "1", "sticky": "nswe"})],
        })])
        style.configure(
            name, background=t["thumb"], troughcolor=panel,
            bordercolor=panel, lightcolor=t["thumb"], darkcolor=t["thumb"],
            gripcount=0, arrowsize=int(9 * scale), relief="flat",
            borderwidth=0,
        )
        # "disabled" is AutoScrollbar's way of saying there is nothing to
        # scroll: the thumb takes the trough's colour and disappears.
        thumb = [("disabled", panel), ("pressed", t["thumb_hover"]),
                 ("active", t["thumb_hover"])]
        style.map(name, background=thumb, lightcolor=thumb, darkcolor=thumb,
                  bordercolor=[("disabled", panel)])

    # -- lists and tables -----------------------------------------------
    style.configure(
        "Treeview", background=panel, fieldbackground=panel,
        foreground=fg, borderwidth=0, rowheight=int(round(30 * scale)),
        font=ui, relief="flat",
    )
    style.configure("Treeview", bordercolor=panel, lightcolor=panel, darkcolor=panel)
    style.map("Treeview", background=[("selected", t["row_select"])],
              foreground=[("selected", t["fg"])])
    style.configure(
        "Treeview.Heading", background=t["raised"], foreground=t["text_dim"],
        relief="flat", padding=(8, 5), font=(UI_FONT, SMALL, "bold"),
        bordercolor=t["border"], lightcolor=t["raised"], darkcolor=t["raised"],
    )
    style.map("Treeview.Heading", background=[("active", t["raised_hover"])])

    # -- progress -------------------------------------------------------
    for name in ("Horizontal.TProgressbar", "Target.Horizontal.TProgressbar"):
        style.configure(
            name, troughcolor=t["border"], background=t["accent"],
            bordercolor=t["border"], lightcolor=t["accent"],
            darkcolor=t["accent"], thickness=int(round(6 * scale)),
        )

    # -- tabs, splitters, rules, frames ---------------------------------
    style.configure("TNotebook", background=panel, borderwidth=0,
                    tabmargins=(0, 4, 0, 0))
    style.configure(
        "TNotebook.Tab", background=panel, foreground=t["text_dim"],
        padding=(16, 7), borderwidth=0, bordercolor=panel,
        lightcolor=panel, darkcolor=panel,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", t["raised"]), ("active", t["hover"])],
        lightcolor=[("selected", t["raised"])],
        foreground=[("selected", fg)],
        expand=[("selected", (0, 0, 0, 0))],
    )
    style.configure("TSeparator", background=t["border"])
    # Splitters sit between cards, so they take the backdrop's colour: the gap
    # between two cards is the window showing through.
    style.configure("TPanedwindow", background=window)
    style.configure("Sash", sashthickness=int(round(10 * scale)), gripcount=0,
                    background=window, bordercolor=window, lightcolor=window,
                    darkcolor=window)
    style.configure("TLabelframe", background=panel, bordercolor=t["border"],
                    lightcolor=panel, darkcolor=panel, relief="solid")
    style.configure("TLabelframe.Label", background=panel,
                    foreground=t["accent"], font=bold)
    style.configure("TScale", background=panel, troughcolor=t["gutter"],
                    bordercolor=t["border"], lightcolor=t["accent"],
                    darkcolor=t["accent"])

    # -- rounded controls: images swapped in for the flat clam parts ------
    # A failure leaves the flat style above in place, which is fine on its own.
    from . import fluent

    if fluent.install(root, style, t, scale):
        # A rounded image leaves its corners transparent, and ttk first fills the
        # WHOLE widget rectangle with the style's `background`. So with these
        # controls that colour has to be whatever is behind the widget, and must
        # not vary with state - states are the image's job now. Anything else
        # shows as a square of the wrong colour around each rounded corner.
        behind = (("TButton", panel), ("Accent.TButton", panel),
                  ("Compact.TButton", panel), ("Tool.TButton", window),
                  ("Quiet.TButton", panel), ("Menu.TButton", t["raised"]),
                  ("Rail.Toolbutton", panel),
                  ("TEntry", panel), ("TCombobox", panel), ("TSpinbox", panel),
                  ("Vertical.TScrollbar", panel), ("Horizontal.TScrollbar", panel),
                  ("Page.Vertical.TScrollbar", t["bg"]),
                  ("Page.Horizontal.TScrollbar", t["bg"]),
                  ("TNotebook.Tab", panel))
        for name, colour in behind:
            style.configure(name, background=colour)
            style.map(name, background=[])

    # -- classic Tk widgets (Text, Listbox, Canvas, ...) ----------------
    # ttk.Style cannot reach these. The option database can, and it only
    # supplies *defaults*: anything a widget sets explicitly still wins, so
    # the editor and map canvases keep their own colours.
    def db(pattern: str, value) -> None:
        root.option_add(pattern, value, 60)

    db("*Listbox.background", t["field"])
    db("*Listbox.foreground", t["fg"])
    db("*Listbox.selectBackground", t["row_select"])
    db("*Listbox.selectForeground", t["fg"])
    db("*Listbox.highlightThickness", 1)
    db("*Listbox.highlightBackground", t["border"])
    db("*Listbox.highlightColor", t["accent"])
    db("*Listbox.borderWidth", 0)
    db("*Listbox.relief", "flat")
    db("*Listbox.activeStyle", "none")
    db("*Listbox.font", ui)
    for cls in ("Text", "Entry", "Spinbox"):
        db(f"*{cls}.background", t["field"])
        db(f"*{cls}.foreground", t["fg"])
        db(f"*{cls}.insertBackground", t["caret"])
        db(f"*{cls}.selectBackground", t["select"])
        db(f"*{cls}.selectForeground", t["fg"])
        db(f"*{cls}.highlightThickness", 1)
        db(f"*{cls}.highlightBackground", t["border"])
        db(f"*{cls}.highlightColor", t["accent"])
        db(f"*{cls}.relief", "flat")
        db(f"*{cls}.borderWidth", 0)
    # Right-click menus are built on the spot with a bare tk.Menu; without
    # these they pop up in Windows' default white on a dark theme.
    db("*Menu.background", t["raised"])
    db("*Menu.foreground", t["panel_fg"])
    db("*Menu.activeBackground", t["row_select"])
    db("*Menu.activeForeground", t["fg"])
    db("*Menu.disabledForeground", t["dim"])
    db("*Menu.selectColor", t["accent"])
    db("*Menu.borderWidth", 1)
    db("*Menu.activeBorderWidth", 0)
    db("*Menu.relief", "flat")
    db("*Canvas.background", panel)
    db("*Canvas.highlightThickness", 0)
    db("*Toplevel.background", panel)
    db("*Frame.background", panel)
    db("*Label.background", panel)
    db("*Label.foreground", fg)
    for cls in ("Checkbutton", "Radiobutton"):
        db(f"*{cls}.background", panel)
        db(f"*{cls}.foreground", fg)
        db(f"*{cls}.activeBackground", panel)
        db(f"*{cls}.activeForeground", fg)
        db(f"*{cls}.selectColor", t["field"])
    # A combo box's drop-down list is a plain Tk Listbox living outside ttk.
    db("*TCombobox*Listbox.background", t["field"])
    db("*TCombobox*Listbox.foreground", t["fg"])
    db("*TCombobox*Listbox.selectBackground", t["row_select"])
    db("*TCombobox*Listbox.selectForeground", t["fg"])
    db("*TCombobox*Listbox.font", ui)
    db("*TCombobox*Listbox.highlightThickness", 0)

    try:
        root.configure(background=window)
    except tk.TclError:
        pass
    return t


def retheme(root: tk.Misc, t: Dict[str, Union[str, bool]],
            skip: Sequence[tk.Misc] = ()) -> None:
    """
    Recolour the classic Tk widgets that already exist, in every open window.

    ttk widgets follow the style by themselves, and widgets built *after* a
    theme change read the option database - but a Text, Listbox or Entry built
    before it keeps the old colours. The writer switches theme with the
    inspector already on screen and gets cream text boxes in a dark window
    until they click something else. `skip` is for widgets the app colours
    itself (the editor, whose text can be hidden in ghost mode).
    """
    skipped = set(skip)
    stack = list(root.winfo_children())
    while stack:
        widget = stack.pop()
        try:
            stack.extend(widget.winfo_children())
            if widget in skipped:
                continue
            repaint = getattr(widget, "restyle", None)
            if callable(repaint):                    # a Card, for instance
                repaint()
                continue
            kind = widget.winfo_class()
            if kind in ("Text", "Entry", "Spinbox"):
                widget.configure(
                    background=t["field"], foreground=t["fg"],
                    insertbackground=t["caret"], selectbackground=t["select"],
                    selectforeground=t["fg"], highlightbackground=t["border"],
                    highlightcolor=t["accent"])
            elif kind == "Listbox":
                widget.configure(
                    background=t["field"], foreground=t["fg"],
                    selectbackground=t["row_select"], selectforeground=t["fg"],
                    highlightbackground=t["border"], highlightcolor=t["accent"])
            elif kind == "Canvas" and getattr(widget.master, "canvas", None) is widget:
                widget.configure(background=t["panel"])     # a ScrollFrame's
        except tk.TclError:
            pass


# --------------------------------------------------------------------------
# Windows title bar
# --------------------------------------------------------------------------


def _colorref(colour: str) -> int:
    r, g, b = _rgb(colour)
    return r | (g << 8) | (b << 16)


def style_titlebar(window: tk.Misc, t: Optional[Dict] = None) -> None:
    """
    Tint a window's title bar to match the app instead of the Windows accent.

    Windows 11 only (build 22000+); on anything else the calls fail quietly and
    the normal title bar stays. Purely cosmetic, so it can never be allowed to
    raise.

    Tk creates the real top-level window lazily and rebuilds it when first
    mapped, which throws away anything set beforehand - so it is applied now
    *and* once more when the window appears.
    """
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return
    try:
        t = t or current_tokens()
        _paint_titlebar(window, t, windll)
        if not window.winfo_ismapped():
            def again(event, _t=t) -> None:
                if event.widget is not window:
                    return
                window.unbind("<Map>", token)
                _paint_titlebar(window, _t, windll)

            token = window.bind("<Map>", again, add="+")
    except Exception:
        pass


def _paint_titlebar(window: tk.Misc, t: Dict, windll) -> None:
    try:
        hwnd = windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        set_attr = windll.dwmapi.DwmSetWindowAttribute

        def put(attribute: int, value: int) -> None:
            v = ctypes.c_int(value)
            set_attr(ctypes.c_void_p(hwnd), attribute, ctypes.byref(v),
                     ctypes.sizeof(v))

        put(20, 1 if t["dark"] else 0)        # dark mode: light window buttons
        put(35, _colorref(t["panel"]))         # caption colour
        put(36, _colorref(t["panel_fg"]))      # caption text colour
        put(34, _colorref(t["border"]))        # window border colour
    except Exception:
        pass


# --------------------------------------------------------------------------
# Icons
# --------------------------------------------------------------------------

# Segoe MDL2 Assets / Segoe Fluent Icons code points. Both fonts ship with
# Windows 10/11 and share these, so no icon file has to be bundled. If neither
# font is present the buttons simply show their text.
GLYPHS: Dict[str, int] = {
    "new": 0xE710,
    "save": 0xE74E,
    "compile": 0xE82D,
    "sprint": 0xE916,
    "diagnose": 0xE9D9,
    "stats": 0xE9F9,
    "find": 0xE721,
    "word": 0xE8A7,
    "commands": 0xE700,
    "settings": 0xE713,
    "folder": 0xE8B7,
    "help": 0xE897,
    # binder rows
    "edit": 0xE70F, "list": 0xE71D, "person": 0xE77B, "pin": 0xE707,
    "box": 0xE7B8, "flag": 0xE7C1, "link": 0xE71B, "globe": 0xE774,
    "map": 0xE800, "calendar": 0xE787, "note": 0xE70B, "send": 0xE724,
    "doc": 0xE8A5, "clock": 0xE823,
}
_ICON_FONTS = ("SegoeIcons.ttf", "segmdl2.ttf")


class IconSet:
    """Toolbar icons rendered from the system icon font, per colour, cached."""

    def __init__(self, root: tk.Misc, scale: float = 1.0) -> None:
        self.root = root
        self.size = max(12, int(round(16 * scale)))
        self._font = None
        self._cache: Dict[Tuple[str, str], object] = {}
        try:
            from PIL import ImageFont

            fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
            for name in _ICON_FONTS:
                if (fonts / name).exists():
                    self._font = ImageFont.truetype(str(fonts / name), self.size)
                    break
        except Exception:
            self._font = None

    @property
    def available(self) -> bool:
        return self._font is not None

    def dot(self, colour: str, px: int = 0):
        """A small filled circle, centred in an icon-sized transparent square."""
        key = ("dot", colour)
        image = self._cache.get(key)
        if image is None:
            try:
                from PIL import Image, ImageDraw, ImageTk

                side = self.size + 4
                ss = 4
                big = Image.new("RGBA", (side * ss, side * ss), (0, 0, 0, 0))
                r = (px or max(7, round(self.size * 0.5))) * ss / 2
                c = side * ss / 2
                ImageDraw.Draw(big).ellipse((c - r, c - r, c + r, c + r), fill=colour)
                image = ImageTk.PhotoImage(big.resize((side, side), Image.LANCZOS),
                                           master=self.root)
            except Exception:
                return None
            self._cache[key] = image
        return image

    def get(self, name: str, colour: str):
        """A PhotoImage of the glyph in `colour`, or None (show text only)."""
        if self._font is None or name not in GLYPHS:
            return None
        key = (name, colour)
        image = self._cache.get(key)
        if image is None:
            try:
                from PIL import Image, ImageDraw, ImageTk

                side = self.size + 4
                canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
                ImageDraw.Draw(canvas).text(
                    (side / 2, side / 2), chr(GLYPHS[name]), font=self._font,
                    fill=colour, anchor="mm",
                )
                image = ImageTk.PhotoImage(canvas, master=self.root)
            except Exception:
                return None
            self._cache[key] = image
        return image


def _brand_source(t: Dict):
    """
    The logo as a PIL image: brand/icon.png (the writer's own N-mark), or - only
    if that file is missing - a plain accent-coloured "N", so a broken install
    still shows a mark instead of Tk's default feather.
    """
    from PIL import Image, ImageDraw, ImageFont

    brand = app_root() / "brand" / "icon.png"
    if brand.exists():
        try:
            return Image.open(brand).convert("RGBA")
        except Exception:
            pass
    size = 256
    source = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(source)
    draw.rounded_rectangle((8, 8, size - 8, size - 8), radius=56, fill=t["accent"])
    try:
        font = ImageFont.truetype(
            str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeuib.ttf"), 168)
    except Exception:
        font = ImageFont.load_default()
    draw.text((size / 2, size / 2 + 6), "N", font=font, fill=t["on_accent"], anchor="mm")
    return source


def _sized(source, px: int):
    """Downscale the logo; small sizes get a touch of sharpening so the mark stays legible."""
    from PIL import Image, ImageFilter

    out = source.resize((px, px), Image.LANCZOS)
    if px <= 64:
        out = out.filter(ImageFilter.UnsharpMask(radius=0.8, percent=70, threshold=2))
    return out


def app_icons(root: tk.Misc, t: Optional[Dict] = None) -> List[object]:
    """
    Window icons at several sizes - the title bar, the taskbar, Alt-Tab.

    Windows picks the size it needs from the list, so it is given the real range
    rather than one image that gets stretched.
    """
    t = t or current_tokens()
    try:
        from PIL import ImageTk

        source = _brand_source(t)
        return [ImageTk.PhotoImage(_sized(source, px), master=root)
                for px in (16, 24, 32, 48, 64, 128, 256)]
    except Exception:
        return []


def brand_image(root: tk.Misc, px: int, t: Optional[Dict] = None):
    """The logo as a PhotoImage `px` wide - for the welcome screen and About."""
    try:
        from PIL import ImageTk

        return ImageTk.PhotoImage(_sized(_brand_source(t or current_tokens()), px),
                                  master=root)
    except Exception:
        return None


# --------------------------------------------------------------------------
# Tooltips
# --------------------------------------------------------------------------


class Tooltip:
    """
    A small hover label. Bound once; costs nothing until the pointer rests.

    `text` may be a callable so the tip can reflect state at the moment it is
    shown (for instance "Save (Ctrl+S) - 3 unsaved changes").
    """

    def __init__(self, widget: tk.Misc, text: Union[str, Callable[[], str]],
                 delay: int = 550) -> None:
        self.widget = widget
        self.text = text
        self.delay = delay
        self._job: Optional[str] = None
        self._tip: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._leave, add="+")
        widget.bind("<ButtonPress>", self._leave, add="+")

    def _enter(self, _event=None) -> None:
        self._cancel()
        try:
            self._job = self.widget.after(self.delay, self._show)
        except tk.TclError:
            self._job = None

    def _leave(self, _event=None) -> None:
        self._cancel()
        self._hide()

    def _cancel(self) -> None:
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _hide(self) -> None:
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None

    def _show(self) -> None:
        self._job = None
        try:
            text = self.text() if callable(self.text) else self.text
            if not text or self._tip is not None or not self.widget.winfo_exists():
                return
            t = current_tokens()
            tip = tk.Toplevel(self.widget)
            tip.withdraw()
            tip.wm_overrideredirect(True)
            try:
                tip.wm_attributes("-topmost", True)
            except tk.TclError:
                pass
            outline = tk.Frame(tip, background=t["border_strong"])
            outline.pack()
            tk.Label(
                outline, text=text, justify="left", wraplength=320,
                background=t["raised"], foreground=t["panel_fg"],
                font=(UI_FONT, 9), padx=8, pady=5,
            ).pack(padx=1, pady=1)
            tip.update_idletasks()
            w, h = tip.winfo_reqwidth(), tip.winfo_reqheight()
            sw, sh = self.widget.winfo_screenwidth(), self.widget.winfo_screenheight()
            x = self.widget.winfo_rootx() + 6
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            if y + h > sh - 8:                       # no room below: go above
                y = self.widget.winfo_rooty() - h - 6
            x = max(8, min(x, sw - w - 8))
            tip.wm_geometry(f"+{x}+{max(8, y)}")
            tip.deiconify()
            self._tip = tip
        except tk.TclError:
            self._tip = None
