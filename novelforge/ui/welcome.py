"""
The first-run screen.

Shown only when there is no novel to open - a fresh install - so it has one job:
make the first two minutes obvious. What this is, the two things you can do,
and a one-line tour of what is inside. It lies over the three panes rather than
replacing them, so the moment a novel opens the normal window is already
underneath.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import APP_NAME, APP_VERSION
from . import styling

CARDS = [
    ("Write",
     "A binder for chapters and scenes, an editor that stays out of the way, "
     "autosave, and spelling and grammar checked as you type."),
    ("Plan",
     "Nine outline frameworks, a corkboard, a timeline, and a story graph "
     "that finds your characters and places in your own prose."),
    ("Build",
     "A map maker for your world, offline editing diagnostics, and one click "
     "to compile the whole manuscript into a Word document."),
]


class WelcomeView(ttk.Frame):
    def __init__(self, app) -> None:
        super().__init__(app)
        self.app = app

        column = ttk.Frame(self)
        column.place(relx=0.5, rely=0.47, anchor="center")

        self._logo = styling.brand_image(app, int(112 * getattr(app, "ui_scale", 1.0)))
        if self._logo is not None:
            tk.Label(column, image=self._logo, borderwidth=0,
                     background=styling.current_tokens()["panel"]
                     ).grid(row=0, column=0, pady=(0, 16))
        ttk.Label(column, text=f"Welcome to {APP_NAME}",
                  style="Hero.TLabel").grid(row=1, column=0)
        ttk.Label(
            column, style="Lead.TLabel", justify="center", wraplength=560,
            text="A quiet studio for writing a novel. Everything is saved as "
                 "real Word documents on this computer - nothing is uploaded, "
                 "and there is no account.",
        ).grid(row=2, column=0, pady=(8, 22))

        actions = ttk.Frame(column)
        actions.grid(row=3, column=0, pady=(0, 30))
        ttk.Button(actions, text="Start a new novel", style="Accent.TButton",
                   padding=(22, 9), command=app.cmd_new_project
                   ).grid(row=0, column=0, padx=6)
        ttk.Button(actions, text="Open an existing novel", padding=(22, 9),
                   command=app.cmd_open_project).grid(row=0, column=1, padx=6)

        cards = ttk.Frame(column)
        cards.grid(row=4, column=0, pady=(0, 24))
        t = styling.current_tokens()
        for index, (title, text) in enumerate(CARDS):
            edge = tk.Frame(cards, background=t["border"])
            edge.grid(row=0, column=index, padx=6, sticky="nsew")
            cards.columnconfigure(index, uniform="card")
            card = ttk.Frame(edge, style="Card.TFrame", padding=(16, 14))
            card.pack(padx=1, pady=1, fill="both", expand=True)
            ttk.Label(card, text=title, style="CardTitle.TLabel"
                      ).grid(row=0, column=0, sticky="w")
            ttk.Label(card, text=text, style="CardText.TLabel", wraplength=190,
                      justify="left").grid(row=1, column=0, sticky="w",
                                           pady=(6, 0))

        ttk.Label(
            column, style="Hint.TLabel", justify="center",
            text=f"Press Ctrl+Shift+P at any time to find a command by typing."
                 f"   ·   {APP_NAME} {APP_VERSION}",
        ).grid(row=5, column=0)

    def show(self) -> None:
        self.place(in_=self.app.panes, x=0, y=0, relwidth=1, relheight=1)
        self.lift()

    def hide(self) -> None:
        self.place_forget()
