# Working on NovelForge

This file is for whoever (human or AI) touches this code next. Read it before
changing anything — it exists because this whole project has been built by AI
pairing with a non-programmer, one conversation at a time, and every session
starts cold. The only continuity is what got written down. If you learn
something the next session would need, add it here instead of only saying it
in chat.

## What this is

NovelForge is a local-first novel-writing studio: character sheets, outline
frameworks, a timeline, a "story graph" that mines your prose for entities, a
fantasy map maker, diagnostics, and a compiler — all reading and writing real
`.docx` files on disk, no account, no cloud. See `README.md` for the
user-facing tour. This file is the developer-facing one.

**The user is a writer, not a programmer.** They cannot read a traceback and
decide what it means. "It's glitchy" or "it doesn't feel right" is a complete
and valid bug report — the job is to find the actual mechanism yourself, not
to ask them to narrow it down technically.

## Three codebases live here — don't confuse them

- **`novelforge/`** — Python 3.13 + Tkinter. **This is the whole desktop
  product.** Launched by `Write.bat` → `python -m novelforge`. Creating a
  novel, writing, the map maker, the corkboard, the outline, the timeline,
  every settings dialog, compiling, backups — all of it lives here and all
  of it works.
- **`web/`** — Next.js 15 + React 19, static-exported so end users only ever
  need Python. This is an **unfinished redesign of the desktop UI**,
  reachable only via `python -m novelforge --web`, and it talks to a local
  Python HTTP server (`novelforge/server.py`) for every piece of data - it
  cannot run without that server. Its shell, settings screen and editor are
  wired to the engine; the maps, dashboard, library, character and world
  screens **do not exist yet**. Do not treat anything in `web/` as the
  current app, and do not assume a feature exists there just because it
  exists in `novelforge/ui/`.
- **`site/`** — a plain static HTML/CSS marketing page, no JS logic of its
  own, no build step. This is **not the app** in any form - it's the
  project's public landing page (screenshots, feature list, install steps,
  download link, sponsor links), hosted for free on GitHub Pages at
  `https://sideeffects69.github.io/NovelForge/`. See the dedicated section
  below before touching it.

If a future session's goal is to finish migrating `novelforge/ui/` to
`web/`, that's a real, large, deliberate project — confirm with the user
before starting it, don't drift into it while fixing something else.

**A `web-online/` folder existed briefly in this repo's history (2026-09)** -
a from-scratch, deliberately simplified browser-only rewrite (chapters,
scenes, an editor, Export/Import) with no server at all, built after "make
it live online" was initially misread as "put a version of this in a
browser." It was removed at the user's explicit request: they wanted the
*actual* tool represented online, not a second simpler one standing in for
it, and they'd already decided against genuinely hosting the real engine on
the internet once the real trade-off was explained (real server cost, and
some way to keep users' novels apart from each other - a genuine reversal
of "no account, no cloud"). `site/` - a landing page for the real, still
Windows-only desktop app - is what they actually wanted instead. If a
future session is ever asked to "put NovelForge online" again: don't build
a third one. Ask which of these two already-considered-and-rejected paths
(a from-scratch browser rewrite, or genuine multi-user hosting) is actually
meant, or whether - as happened here - the real answer is a landing page
for the download, before writing any code.

## Module map (`novelforge/`)

The engine (no UI toolkit imports — this is what `web/` will eventually sit
on top of too):

| Module | What it owns |
|---|---|
| `model.py` | The project data model — everything that isn't prose text |
| `project.py` | Create/open/save a project; keeps `project.json` in step with disk |
| `docxio.py` | Reading and writing the two shapes of `.docx` this tool produces |
| `atomic.py` | Crash-safe, OneDrive-safe file writing (write-temp-then-replace) |
| `backup.py` | Snapshots and verified `.zip` backups |
| `recovery.py` | Crash recovery / "where was I" |
| `undo.py` | Undo/redo for everything that isn't typing (Tk's Text widget handles typing itself) |
| `compiler.py` | Assembles every scene into one manuscript-format document |
| `diagnostics.py` | Offline heuristic prose/developmental editing checks |
| `grammar.py` | Spelling/grammar without shipping a dictionary file |
| `lexicon.py` | The editor's own vocabulary — names, invented words — learned from the project |
| `stats.py` | Sessions, streaks, pace, deadline projection |
| `structures.py` | The nine outline frameworks, as data |
| `templates.py` | The field lists behind every generated `.docx` reference sheet |
| `storygraph.py` | Mines the manuscript for entities/mentions and builds the relationship graph |
| `mapgen.py` | Procedural world generation (heightmap → coastline → rivers → settlements → names) |
| `mapmaker.py` | Map data model + `build_primitives()`, the single source of truth rendered by the editor, PNG export and SVG export |
| `mapstory.py` | Where the map connects back to Locations/the story graph |
| `config.py` | App paths and the one settings JSON file |
| `server.py` | Local-only HTTP bridge (binds `127.0.0.1`) used by `--web`/`--serve` |
| `desktop.py` | pywebview shell around the server, for `--web` |

The UI (`novelforge/ui/`), Tkinter, all of it live:

| Module | What it owns |
|---|---|
| `app.py` | Main window: binder / editor / inspector, ~3800 lines, the hub everything else is opened from |
| `mapeditor.py` | The map maker window — canvas UI over `mapmaker`'s primitive list |
| `corkboard.py` | Corkboard and the character-relationship web, two canvas views |
| `storyviews.py` | The four story-graph windows |
| `writing.py` | Editor intelligence: completion, live spelling/grammar marks |
| `dialogs.py` | Modal `Dialog` subclasses and non-modal tool windows |
| `widgets.py` | Small reusable widgets, incl. `center_window()` (see rule below), `AutoScrollbar`, `Gauge`, `StatusBar`, and `ScrolledText.set_report()` |
| `styling.py` | The look of the whole app: theme tokens, the one ttk style, the Tk option-database defaults, title-bar tint, toolbar icons, tooltips (see "The look of the app") |
| `palette.py` | The Ctrl+Shift+P command palette, built by walking the real menus |
| `welcome.py` | The first-run screen, shown only when there is no novel |

**There is no `ui/theme.py` any more.** A ~600-line second design system
(WCAG-contrast-checked palettes, sv-ttk integration, elevation-based
surfaces) lived there but was never imported by anything — `config.py`'s
much simpler `theme()` dict (`bg`/`fg`/`panel`/`accent`, per theme name) is
and always was the one actually driving every widget. It was removed on
2026-09-18 after confirming zero call sites anywhere in the repo. If a
future session wants the richer palette, it existed in git history before
that date — but wiring an app-wide theme swap in blind, with no way to
visually check a Tkinter canvas from here and no test suite, is a real risk;
don't do it without actually running the app and looking at it, ideally with
the user watching.

*(2026-09-19: the theme layer was rebuilt anyway - see "The look of the app" -
but as `ui/styling.py`, derived from `config.THEMES`, and verified window by
window with `tools/uishots/`. The advice above about looking at real
screenshots is why that went well.)*

## Rules that are load-bearing, not style preference

**1. `.docx` is the truth; `project.json` is only metadata.** Ordering,
links, word counts, targets — never prose. This was a deliberate reversal of
the original plain-markdown blueprint, kept because OOXML is an open ISO
standard. Don't add a second place prose can live.

**2. Every window must fit the screen it opens on**, at any resolution or
Windows display scaling — see `README.md`'s "A rule for anyone changing this
code". Size windows through `center_window()` in `widgets.py`; never call
`.geometry()` directly. **Caveat:** the README says this is meant to be
enforced by a test that opens every window at six resolutions - **that test
still does not exist.** What exists (2026-09-19) is the GUI suite in `tests/`:
it opens every tool window and dialog, the main window at 1340x680 and at its
minimum size, and at a simulated 125% display scaling, and fails if any content
is clipped, hidden or squeezed. That is real and it has caught real regressions,
but it is three sizes, not six; adding 1024x768 and a large desktop is the
obvious next step. The developer's own screen is 1366x768 at 100% scaling, so
that is the size that matters first.

**Sizes asked of `center_window()` are for a 100% display** and are multiplied
by `display_scale()` before being clamped to the screen. The app is
per-monitor-DPI aware, so sizes are real pixels while text and controls grow
with the scale; a window sized in fixed pixels used to be too small for its own
contents at 125% (the sprint timer, the corkboard header). The 320x240 floor in
`fit_size()` scales too. At 100% the factor is exactly 1.0.

**3. Speed over polish, always.** The user's own words: *"make it work
amazing, no lags, super fast... I dont care of any fancy ui but make it
workable and user friendly."* Concretely:
   - Rendering never opens a `.docx` — every number the UI shows comes from
     `project.json`.
   - Debounce on idle, never do work per keystroke (autosave 30s idle, word
     recount 400ms).
   - Anything touching many files is an explicit menu command wrapped in
     `App._busy()`, never automatic or on a timer.
   - **On any Tkinter Canvas view** (`mapeditor.py`, `corkboard.py`): a full
     redraw (`canvas.delete("all")` + rebuild every item) is fine for a
     discrete action, but must never run synchronously off a
     `<Motion>`/`<B1-Motion>`-class event, which can fire dozens of times a
     second. Either debounce it (`after(16, redraw)`, coalescing to one
     frame — see `_schedule_redraw()` in `mapeditor.py`) or, better, mutate
     existing canvas items in place (`canvas.move(...)`, `canvas.coords(...)`)
     instead of rebuilding. **This exact mistake was the map maker's
     "glitchy" panning/dragging** — `_on_drag` and `_on_middle_drag` were
     calling a full synchronous `redraw()` on every pan motion event, which
     also recomputed pin-label collision placement (`layout_pin_labels`,
     roughly O(pins × placed)) from scratch every time, even though panning
     changes nothing about the map itself. Fixed by (a) panning via
     `canvas.move("all", dx, dy)` instead of a rebuild, and (b) caching
     `layout_pin_labels`'s result on the `GameMap` (`_label_cache`),
     invalidated by a content fingerprint, so a redraw triggered by
     view-only changes (pan/zoom) reuses it instead of recomputing it. If
     you build another canvas-based view, apply this from the start rather
     than rediscovering it.

**4. No hard-coded colours or fonts outside the theme tokens.** Colours come
from `config.THEMES` through `styling.tokens()`; fonts are Segoe UI via
`styling.UI_FONT`. A colour passed to a widget constructor overrides the Tk
option database that `styling.apply()` fills in, so for classic Tk widgets
prefer letting the database supply it. (Four themes exist: light, dark, warm,
premium - `ui/theme.py` no longer exists.)

## Tests

    python -m unittest discover -s tests -t .        # about 4 minutes (44 tests)

Needs Windows and a display for the GUI half (skipped otherwise); the windows
open and close on the desktop while it runs. Do not run it as
`python tests/test_x.py`: the `-t .` form is what makes `tests/__init__.py` run
first. One module: `python -m unittest tests.test_gui_walk`.

- **`tests/__init__.py` must run before anything imports `novelforge`.** It
  points `NOVELFORGE_SETTINGS` and `NOVELFORGE_PROJECTS` at a temp folder,
  because `config.settings` is read once at import into a singleton. Every test
  module calls `require_isolation()`, which skips rather than run against real
  data if novelforge was imported first. `Projects/`, `novelforge-settings.json`
  and `novelforge-session.json` are **gitignored**, so `git status` cannot tell
  you whether a test touched them - compare their modification times instead.
- `gui_support.py` - `Sandbox`: a real `App` on the demo novel
  (`tools/uishots/seed.py`), with every native dialog (`messagebox`,
  `filedialog`, `colorchooser`), `os.startfile` and `subprocess.Popen` stubbed
  (a real dialog blocks the run forever, and the others launch programs).
  Dialogs answer No/Cancel, so nothing destructive ever goes ahead. Each stub
  records that it was called. `hang_guard()` kills the run after a timeout
  instead of freezing it. `Sandbox.stop()` cancels pending `after` timers and
  always destroys the window: a window left alive stays tkinter's default root,
  and the next test's images are then created against the wrong interpreter
  ("image pyimageNN doesn't exist").
- `test_styling.py` - colour maths, every theme's contrast, palette matching.
  Pure logic, instant.
- `test_gui_smoke.py` - the layout: menu strip and clones, every theme fits,
  runtime theme switching recolours widgets already on screen, toolbar
  collapse, save indicator, palette, reports, dialogs checked for clipping, map
  opening fitted, distraction-free.
- `test_gui_walk.py` - uses every control once. Every menu command (toggles
  twice), every toolbar button, every shortcut handler, every row kind in the
  binder (and that the inspector's fields fit the pane), every right-click menu
  entry, **every button inside every tool window** (`Walker.tour`, which also
  visits each notebook tab), then the flows: first run -> create a novel ->
  open another; type -> save -> reopen; autosave; edit in Word -> reload;
  undo/redo; theme switching keeping the writing. A watcher closes any modal
  dialog a command opens (the command does not return until it is gone). Each
  step also checks nothing raised inside a Tk callback, the app still has the
  sandbox novel open, and any window it opened fits. This walk **does** invoke
  Open Recent and Story Structure, which the old advice below says never to walk
  - that advice is about the writer's real data; here `require_isolation()`
  guarantees the sandbox.
- `test_gui_scaling.py` - the whole interface at a simulated 125% display. The
  scale is simulated by setting `tk scaling` before the window is built. The map
  maker is left out: fifteen toolbar buttons need about 1500px at 125%, and
  Windows will not let a window exceed the real screen.
- `test_launch.py` - the real entry point: `python -m novelforge` as its own
  process (what `Write.bat` runs), once with a novel and once as a fresh
  install; waits for the window, posts WM_CLOSE (what the X button does), and
  checks a clean exit, saved geometry, the closing backup, and no
  `novelforge-errors.log`. **It finds the window by process id, never by title
  alone:** a fresh install is titled just "NovelForge", which a writer's own open
  window can also be, and the test closes whatever it finds.
- Every check here has been proven able to fail by breaking the thing it guards
  (a menu command, a corkboard button, the map toolbar's padding, the theme
  recolour, the display scaling) and confirming the test names the culprit. Do
  the same when you add or change one - a check that cannot fail proves nothing.
  The clip detector (`tools/uishots/clipping.py`) once passed a synthetic case it
  should have failed, because `pack` *unmaps* what does not fit instead of
  letting it overflow like grid/place.
- Still worth adding: 1024x768 and a large desktop; a look at the real Windows
  10 title bar (the tint is Windows 11 only).

## If you drive the real GUI to test it: this bit nearly wrote real user data

**Use `tools/uishots/run.py` (below) rather than writing another one.** It
already does everything here safely. The history that follows is why it is
built the way it is.

There was no harness at first, so a 2026-09 session built one: seed a
throwaway `Project.create()`, point `NOVELFORGE_SETTINGS` at a matching
throwaway settings file, launch the real `App()`, walk the menu tree calling
each command's Tcl name directly (`app.tk.call(cmd_name)` — exactly what a
real click does), and screenshot anything that opens via
`PIL.ImageGrab.grab()`. This is genuinely useful and caught a real bug (see
the map-toolbar entry below) — but it went wrong twice against the user's
**real** project before working safely, both times because the walker
doesn't know which menu entries are safe to invoke blindly:

1. **A shell/path timing bug**, not the app's fault: writing the throwaway
   settings file *after* something has already imported `novelforge.config`
   does nothing, because `config.settings = Settings()` is a module-level
   singleton read once at import time. `NOVELFORGE_SETTINGS` must point at a
   file that already has the right content *before the first
   `import novelforge...` of the process* - write it in a separate earlier
   process/step, not inline before constructing `App()` in the same one. Git
   Bash also silently rewrites `/tmp/...`-style paths differently depending
   on how they cross into a native `python.exe`'s environment - use
   PowerShell with explicit `C:\...` paths for this, not Bash, and keep the
   test project shallow (`C:\something`, not nested deep under a scratch
   directory) or `zipfile`/`docx` writes fail on Windows' ~260-char path
   limit.
2. **The real hazard, and not a bug in the app**: walking *every* menu entry
   blindly, including cascades, invoked `File > Open Recent > <the user's
   actual novel>` exactly as a real click would - which correctly switched
   the live app to it - and then correctly ran every later Manuscript/Tools
   command (compile, write outline, back up, write story bible...) against
   *that* project for the rest of the walk. A second run also walked into
   `Plan > Story Structure > <a framework>`, which correctly switched the
   real project's active outline framework. Both were the app working
   exactly as designed; the bug was testing methodology treating a
   real-data-backed cascade the same as a static one. Recovery both times
   was: diff `project.json` against the automatically-kept `project.json.bak`
   to see exactly what changed, delete anything the walk generated fresh
   (compared file *creation* time to *modified* time - equal means the file
   didn't exist before), and restore `project.json` from `.bak` if a setting
   actually changed.

**If you do this again:** assert the loaded project's title matches the
throwaway one immediately after `App()` starts, before invoking anything,
and abort loudly if it doesn't. Skip `Open Recent` and `Story Structure`
(and treat any other cascade backed by real persisted state the same way)
rather than walking into them. Everything else — the ~80 ordinary commands —
walked cleanly with zero exceptions across two full runs, which is a decent
amount of real confidence for an app with no test suite.

### `tools/uishots/` - seeing what the window actually looks like

    python tools/uishots/run.py --out shots --themes warm premium --welcome

Seeds a demo novel in a temp folder, launches the real window against it in a
fresh process per theme, saves PNGs, reports anything that does not fit its
window, and deletes the sandbox. Facts that cost time to learn:

- **Capture by window handle** (`PrintWindow`, `capture.py`), never a screen
  region: `ImageGrab` once photographed the writer's own open NovelForge
  window instead of the test window.
- **The developer's screen is 1366x768.** A window bigger than that is
  photographed with black where the screen ends. Those bands look like bugs -
  the "clipped inspector" and "missing status bar" chased during the 2026-09-19
  pass were exactly that - and are not. `shots.py` sizes the window to fit
  (1340x680+0+0).
- `cmd_theme` **persists into the sandbox's settings file**, so a script that
  cycles themes leaves the sandbox on the last one. Reseed.
- The settings file must exist before the first `import novelforge` (see the
  singleton note above), so seeding runs in its own process.
- Popup menus are native windows of class `#32768`, not Tk children:
  `EnumWindows` for the current pid, then `PrintWindow`. `keybd_event` reaches
  an open popup, so Down/Right/Enter drive it - that is how the in-app menu bar
  and the cascade were verified end to end.
- `pack` unmaps what does not fit; grid/place let it hang over the edge (see
  the clip detector under Tests).

## Menu organisation (as of 2026-09)

Two deliberate moves, made after actually walking every menu command and
looking at where things sat: **Find in Project / Find and Replace moved
from Tools to Edit** (every other app the user has ever used puts them
there), and **Write Story Bible moved from Plan to Manuscript**, next to
Write Outline.docx / Write Reverse Outline — all three are the same kind of
action (turn what's already in the project into a reference document), so
Manuscript is now consistently "things this generates" and Plan is
consistently "things you look at or fill in on screen." `README.md` was
updated to match (`Plan → Write Story Bible` → `Manuscript → Write Story
Bible`); it also had a pre-existing, unrelated error calling Write Reverse
Outline a Tools command when it was always under Manuscript - fixed too.
If you reorganise a menu again, grep the README for the old `"X → Y"`
phrasing first; it's prose, not generated from the menu code, so nothing
catches this automatically.

The menus are still one `tk.Menu` tree built in `App._build_menu`, but since
2026-09-19 that tree is never attached to the window - the app draws its own
menu bar from it (see "The look of the app"). Add commands to the tree exactly
as before; the bar, the palette and the tests all read it.

## Map maker: what already exists (check before "adding" it again)

The map maker is more built-out than a quick skim of `README.md` suggests
(the README's "Maps" section predates the two most recent map commits and
undersells current features). Before proposing an addition, confirm it
isn't already here:

- Procedural world generation (`mapgen.py`): heightmap via fractal value
  noise → coastline extraction → **downhill-flow rivers** (not just noise) →
  biome placement → habitability-scored settlement placement → roads.
- One-press **"Surprise Me"** (full random world from OS entropy, seed
  recorded for reproducibility) alongside a parameterised **"Generate..."**
  dialog.
- Per-culture procedural naming with **user-editable name lists**
  (`Name Styles.json` in the project's Maps folder, "Edit Names" in the UI),
  and **per-role styles** — settlements, realms, regions, seas and rivers can
  each sound different, or be pointed at the same style.
  Settlement-name collisions are disambiguated (Upper/Lower/Little/Great/...,
  then a numeral) rather than left blank.
  - **Greedy label-collision avoidance** for every pin/label
    (`layout_pin_labels` in `mapmaker.py`), with a documented fallback of
    hiding a name rather than printing it on top of another.
  - **Pins link to Location sheets** — right-click → Link, double-click to
    open the linked sheet in Word.
  - **Layers**, shown/hidden independently.
  - One shared primitive list (`build_primitives()`) rendered identically by
    the Tkinter canvas, the PNG exporter, and the SVG exporter — "what you
    see while editing is exactly what you export." Keep it that way; don't
    let PNG/SVG export drift into their own drawing logic.

**Genuine gaps**, worth considering later rather than assumed to already
exist: coastlines come from smoothed noise rather than a Voronoi/Delaunay
mesh, so they read as smooth rather than jagged/geologic (Azgaar's Fantasy
Map Generator, MIT-licensed, is the reference implementation if this is ever
worth the rewrite risk — it is a genuine rewrite of `mapgen.py`'s terrain
step, not a small change); there's no "zoom into a town" street-layout
generator (Watabou's TownGeneratorOS is the reference); and the hand-draw
tools have no click-to-stamp icon brush (mountain/tree/castle) — freehand and
click-to-place-points are the only ways to draw terrain by hand.

**Toolbar button widths must fit their own label.** The main toolbar's
buttons used one flat `width=8` for every label, which clipped "Surprise Me"
and "Edit Names" to "Surprise !" and "Edit Nam" — invisible from reading the
code, only visible in an actual screenshot. Fixed (2026-09) to
`width=max(8, len(label) + 1)` per button. Don't "fix" this by removing
`width=` entirely — with this many buttons in one un-wrapped row, letting
ttk pad every button to its natural size pushes the whole toolbar past the
window's edge and hides "Help" and the coordinate readout off-screen
instead, which is worse and easy to miss since nothing raises an exception.

## Security posture

Reviewed 2026-09, manually — the `security-review` skill's own frontmatter
shells out to `git diff origin/HEAD...`, which failed outright because this
repo had no remote configured. It has one now (`origin`, the GitHub repo), so
the skill may work; that hasn't been retried.

The threat model is deliberately small: single local user, no accounts, no
outbound network calls anywhere in `novelforge/`, and the one local server
(`server.py`, used only by the unfinished `--web`/`--serve` path) binds
`127.0.0.1` with a fresh random per-launch token required on every route
except `/api/health`. Within that model:

- **Fixed already**: `backup.py`'s zip-extraction path-traversal guard was
  a plain string `startswith`, which a sibling folder name (`"MyBook2"`
  starting with `"MyBook"`) could satisfy without actually being inside the
  destination - now checks `resolved == dest or dest in resolved.parents`.
  `config.py`'s "Reveal in Explorer" built a shell string via `os.system`
  from a raw path - now `subprocess.Popen` with an argument list, no shell.
- **Checked and clean**: no `eval`/`exec`/`pickle`/`os.system`/`shell=True`
  anywhere else in the codebase. The only other `zipfile.ZipFile(...,
  "r")` usages (`atomic.py`, `backup.py`'s `verify_backup`) only read
  metadata (`testzip`/`namelist`), never `extractall`. `server.py`'s static
  file server already had the *correct* traversal guard
  (`target.relative_to(WEB_ROOT.resolve())`) from the start - a good
  reference for what backup.py's guard should have looked like. No CORS
  headers are set anywhere, so the loopback server doesn't opt into
  cross-origin access even accidentally.
- **Not a bug, just worth knowing**: unhandled exceptions in any `/api/`
  route get their traceback echoed back in the JSON response
  (`server.py`'s `_api`). Harmless given the threat model (loopback-only,
  token-gated, single local user) and actually useful for debugging the
  unfinished web UI - just don't assume this is safe if `server.py` is ever
  exposed beyond loopback.

## `site/` — the public website (added 2026-09, replaced web-online/ same day)

A landing page for the desktop app, not a version of the app itself -
screenshots, the feature list, install steps, a download link to the
latest GitHub Release, and the sponsor links also in the README. Plain
HTML/CSS, no build step, one small JS file (`app.js`) doing exactly one
thing: an IntersectionObserver that adds `.is-visible` to `[data-reveal]`
elements as they scroll into view, skipped entirely under
`prefers-reduced-motion`. Hosted for free on GitHub Pages, deployed
automatically by `.github/workflows/deploy-pages.yml` on any push to
`main` that touches `site/**`.

**Redesigned 2026-09, twice.** First pass: fairly called "basic" - the user
pointed at obsidian.md, literatureandlatte.com/scrivener and atticus.io as
the bar. Added Fraunces (display) + Inter (body), a `.window-chrome`
wrapper (macOS-style traffic-light dots + title bar) around every
screenshot so a plain Tkinter capture reads as a polished product shot, a
head-to-head comparison table against Scrivener/Atticus/Obsidian (the same
pattern Atticus's own site uses against Vellum), and scroll-reveal via
`app.js`. Kept the warm/parchment identity at that point, reasoning that
copying a competitor's palette isn't the same thing as looking premium.

**Second pass, same day**: the user then supplied a real logo/brand
package (navy + electric-blue + ivory, a book/quill "N" mark) and a very
detailed design spec explicitly modelled on Obsidian + Scrivener + Linear +
"a sophisticated writer's desk at night," with exact hex values, a full
token list, and instructions to apply the identical palette to both the
desktop app and the website. That reasoning about the warm palette being
more distinctively premium didn't survive contact with an actual brand
package - the site now runs on that dark-navy/electric-blue system
(swapped Fraunces → Literata per the spec's typography section; kept the
`.window-chrome` and comparison-table patterns from the first pass, they
weren't palette-specific). The **desktop app got a real Preferences theme
option out of this too**: `THEMES["premium"]` in `config.py`, the same
9-key dict every other theme here already uses, selectable in Preferences
with zero other UI code needing to change (the dropdown already reads
`THEMES.keys()`). It is **not** selected by default - `warm` still is,
Classic in the spec's terms - since it hasn't had the scrutiny a default
deserves.

Getting it to actually look coherent, not just "the dict has navy values
now," took a real fix, not just new hex codes: `app.py`'s `_apply_theme()`
used to configure zero ttk style for `TButton`/`TEntry`/`TCombobox`, for
*any* theme - invisible against light backgrounds, but every toolbar
button and inspector field stayed a flat white box against the new dark
palette, because Windows' native "vista" ttk renderer draws those specific
widgets itself and ignores Tk colour overrides outright. Fixed by
switching to "clam" (fully Tk-drawn, actually obeys `ttk.Style`) **only**
when `settings["theme"] == "premium"` - Classic keeps the exact native
chrome it always had. `widgets.py`'s `Form.multiline()` had the identical
gap one level down (a bare `tk.Text`, styled for no theme, ever - a latent
bug in "dark" too, not new) and now reads `theme()` at creation time.
`mapeditor.py`'s two `tk.Listbox`es (terrain, layers) got the same
treatment. All of this was found by actually launching the app against
each palette and looking at a real screenshot, not by reading the colour
values and assuming they took - the white-box failure mode is invisible
in code review.

**Closed 2026-09-19:** the remaining unstyled `tk.Listbox`/`tk.Text` widgets
are now covered centrally by the Tk option database (below), not one at a time.
The rest of this section describes the first Premium pass; read "The look of
the app" for the current state. Tkinter still has no drop-shadow, backdrop-blur
or smooth hover-elevation; the parts of the spec written assuming a browser
(glow, 150ms transitions on every control) don't have a faithful desktop
equivalent without replacing native widgets with hand-drawn Canvas ones - a
real, separate, much larger project. Get explicit sign-off before ever
starting that.

The full CSS palette, exactly as specified, is recorded in `site/style.css`
as CSS custom properties (`--bg`, `--surface-1`...`--surface-3`, `--brand`,
etc.) - copy those hex values rather than re-deriving them if the desktop
app's token system is ever extended to match more closely.

**Screenshots** (`site/assets/screenshots/`) were taken against a disposable
demo project (`Kessa Ren` / "The Ashfall Crown"), seeded via
`Project.create()` directly and launched with `NOVELFORGE_SETTINGS`
pointed at a throwaway settings file - never the user's real project. If
you retake these, follow the same isolation, and add the hard safety
assertion (`assert app.project.data.title == "<expected demo title>"`)
*before* taking any screenshot or touching anything - see "If you drive
the real GUI to test it" above for exactly why that assertion exists and
what happens without it.

**The donate QR images are duplicated**, not symlinked: once at
`assets/donate/` (for the README, rendered by GitHub's own Markdown
renderer with repo-relative paths) and again at `site/assets/donate/` (for
the Pages deployment, which only ever sees the `site/` folder's own
contents - a path like `../assets/...` would point outside what actually
gets published, and 404). If the PayPal/UPI QR codes are ever regenerated,
update both copies.

**The download link points at `/releases/latest`**, not a specific
version, so it never needs updating when a new release is tagged - just
tag the release and the link is already current.

## The look of the app (rebuilt 2026-09-19)

The desktop UI was modernised in one pass and verified by photographing every
window in two themes (`tools/uishots/`), not by reading code. What exists, and
why each piece is the way it is:

- **One flat "clam" style for every theme** (`ui/styling.py`). Windows' native
  "vista" ttk theme ignores every ttk colour, which is why the app looked like a
  2005 dialog box and why the dark palettes had white boxes floating in them.
  `styling.apply()` runs at start-up and on a theme change and *derives*
  everything (hover, borders, row selection, legible secondary text) from the
  nine keys in `config.THEMES` - a theme is still one dict. This supersedes the
  earlier arrangement where only Premium used clam and Classic kept native
  chrome: warm and light are flat now too.
- **Classic Tk widgets** (Text, Listbox, Entry, Canvas...) that `ttk.Style`
  cannot reach take their colours from the Tk *option database* (`option_add`,
  priority 60). That supplies defaults only; anything set explicitly still wins,
  so the editor and map canvases keep their own colours.
- **Title bar** is tinted through DWM (`styling.style_titlebar`; Windows 11, a
  silent no-op elsewhere) from `center_window()`, so every window gets it. Tk
  rebuilds its top-level window when first mapped, which throws the attribute
  away, so it is re-applied on `<Map>`.
- **The menu bar is drawn by the app** (`App._build_menu_strip`), because
  Windows owns the native one and gives Tk no way to recolour it - a white
  strip across a dark window. The `tk.Menu` tree from `_build_menu` stays the
  source of truth and is never attached to the window; each button gets a
  `menu clone` of a top-level menu. Two Tk rules cost time: `tk::MbPost`
  refuses a menu that is not a *descendant of its menubutton* (so you cannot
  point a Menubutton at a shared menu), and `clone` is what keeps dynamic
  entries - the Undo label, Open Recent - live. Popup colours are set on the
  originals *before* cloning (`_theme_menu`); a theme change rebuilds the strip.
  The detached bar's index 0 is a tearoff entry: skip by `type()`, never index
  blindly. `menu_bar_height()` returns 0 for the main window now.
- **Toolbar**: icons come from the system icon font (Segoe Fluent Icons /
  MDL2 via Pillow, `styling.IconSet`), so no icon files ship; without the font
  the buttons just show their text. Below the width the labels need it shows
  icons only (tooltips name each button and its shortcut). The collapse is
  decided against the width the full toolbar needed when it was built, not its
  current width, so switching modes can't feed back and flicker.
- **Command palette** (`palette.py`, Ctrl+Shift+P - Ctrl+K is the corkboard).
  Built each time by walking the real menus, so it cannot drift from them; runs
  an entry with `menu.invoke`, exactly what a click does.
- **First-run screen** (`welcome.py`) overlays the panes only when there is no
  novel: start-up otherwise opens the first project, so it never shows a recent
  list.
- **Reports** (`ScrolledText.set_report`): every generated report is plain text
  built with the same conventions - a title over `====`, ALL-CAPS section names,
  `----` rules, `!!`/`~` severity markers. `set_report` styles those and keeps a
  monospace body so aligned tables still line up; nothing about how reports are
  generated changed. Used by the in-pane detail view, `ReportWindow`, and the
  story-graph tabs. Tk paints a tag's background across its line *spacing*, so
  a rule is a 1px line with separate blank lines around it, not spacing.
- **A theme change recolours what is already on screen** (`styling.retheme`,
  called from `_apply_theme`). ttk widgets follow the style by themselves and
  new classic Tk widgets read the option database, but a Text, Listbox or Entry
  built *before* the switch kept the old colours - View > Theme left the
  inspector's boxes cream in a dark window until another row was clicked. It
  walks every window, including open tool windows; the editor is skipped
  because `_style_editor` owns it (ghost mode hides its text). A report window's
  heading colours are baked in when it is rendered and are not redone.
  (Re-adding an option-database value at the same priority *does* take effect
  immediately; the stale colours were never the database's fault.)
- **Right-click menus** get themed colours from `*Menu.*` in the option database,
  since they are bare `tk.Menu`s built on the spot. The in-app menu bar's menus
  are coloured explicitly (`_theme_menu`) before being cloned.
- **Button rows wrap** (`widgets.flow`, used by `Form.button_row`): the scene
  inspector has four buttons in a ~330px pane and the last one hung off the
  edge once the buttons gained padding. It also survives a dragged sash.
  `Compact.TButton` has a natural width (clam's 11-character minimum is
  overridden); an explicit `width=` on a widget still wins, which the map
  toolbar relies on.
- **Always pass `master=` to `ImageTk.PhotoImage`.** Without it the image
  belongs to whichever Tk root is tkinter's default - fine with one window,
  wrong the moment a process has had two (the tests).
- The placeholder window icon follows the theme accent; a real
  `brand/icon.png` does not change with the theme.
- **Save-state indicator** in the status bar. `StatusBar.set_state` runs from
  the per-keystroke modified handler, so its unchanged path must stay one
  comparison (the Speed rule above).
- **Buttons**: `TButton` (default), `Accent.TButton` (primary), `Tool.TButton`
  (borderless, toolbar), `Compact.TButton` (dense rows). clam gives every
  button an 11-character *minimum* width; `Tool.TButton` overrides it to 0.
  **The map editor's toolbar has fifteen buttons in a row and overflowed off the
  edge - hiding Help and the coordinate readout - when the default padding
  grew;** it uses `Compact.TButton`, and the clipped-content test guards it.
- **Scroll bars** are a slim thumb (`AutoScrollbar`), and *disabled* rather than
  hidden when there is nothing to scroll: hiding changes the width the content
  has, and wrapped text can then re-flow back and forth around the threshold.
- **Map editor** stays "fit to window" until the writer pans or zooms
  (`_auto_fit`). The first map used to be fitted while the window was still
  being built and opened as a thumbnail (about a quarter of the canvas width,
  now about 96%).
- Secondary text uses `text_dim` (at least 4.5:1) rather than the palette's
  `dim` (about 2:1 on the warm panel); tree status colours are nudged only as
  far as needed to stay legible on the sidebar (`ensure_contrast`).
- **Not done, deliberately:** shadows, blur, rounded corners and smooth hover
  transitions (not available without hand-drawn Canvas widgets); the check-box
  indicator is clam's plain square with a cross; and `premium` is **not** the
  default theme - `warm` is. Changing `DEFAULT_SETTINGS["theme"]` would only
  affect new installs (an existing settings file persists its theme), and it was
  left as the writer's decision.
- The centre header's title label is squeezed by about 19px at the 900px
  minimum window width (long scene titles are cut short). It predates this work
  and is accepted; the clip detector reports it, and the test ignores it.

## Releasing a new version

Releases are made on GitHub, and there is **no `gh` CLI** on the developer's
machine. The site's Download button points at `/releases/latest`, so it shows
the new version only once a *Release* exists - pushing a tag alone does not
change it.

1. Bump `APP_VERSION` in `novelforge/__init__.py` (the About box and the
   settings file read it). `web/package.json` has its own, unfinished version
   and is left alone.
2. Run the whole test suite.
3. Commit, `git tag vX.Y.Z`, `git push origin main vX.Y.Z`.
4. Create the Release for the tag. Follow `v1.0.0`'s shape: title
   "NovelForge X.Y" (`v1.0.0` is "NovelForge 1.0", `v2.1.0` is "NovelForge 2.1"),
   a short "What's new" written for a writer, a "Getting started" (install
   Python 3.13+, download **Source code (zip)**, double-click `Write.bat`), an
   "Upgrading" note (novels live in `Projects/` and preferences in
   `novelforge-settings.json`, both inside the install folder - copy them
   across), and no attached files - people take GitHub's own source zip.
   Without `gh`, either use the website (Releases > Draft a new release > pick
   the tag > paste the notes) or the API, which is how 2.1.0 was made: POST
   `{tag_name, target_commitish, name, body, draft, prerelease, make_latest}` to
   `https://api.github.com/repos/sideeffects69/NovelForge/releases` with the
   token Git Credential Manager already holds. Get it with `git credential
   fill` (protocol=https, host=github.com) and `GCM_INTERACTIVE=never` so it can
   never open a prompt; keep it in memory, send it in one header, never print or
   store it. A `201` answer carries the release URL.
5. Anything pushed under `site/` deploys Pages by itself (about a minute; the
   run is visible under the repo's Actions tab).
6. Check it from the outside, not just from the working folder:
   `https://github.com/sideeffects69/NovelForge/releases/latest` must redirect to
   the new tag (that is the site's Download button); the Pages run for the push
   must be green (`api.github.com/repos/sideeffects69/NovelForge/actions/runs`);
   and the live screenshots must be byte-identical to `site/assets/screenshots/`.
   Then download the tag's source zip into a short path (`C:
f_rel`) and run
   the test suite from *that* - it proves the published copy is complete
   (nothing needed is gitignored), which the working folder cannot.

The `v1.0.0` release notes still link to the pre-rename username
(`om-abhyankar.github.io`), which is dead - GitHub Pages does not redirect a
renamed account. Use `sideeffects69` in anything new.

## Running it

```
Write.bat                          # the real app (Tkinter)
python -m novelforge                # same, from a shell
python -m novelforge --web          # incomplete web redesign - do not use for real writing
python -m novelforge --serve        # local server only, prints the URL
pip install python-docx Pillow      # the only two non-stdlib deps for novelforge/
```

`web/` (only if working on the redesign itself):
```
cd web
npm install
npm run dev      # localhost:4321
npm run build     # static export into web/out/, committed to the repo -
                   # this is what lets end users skip Node entirely
npm run test      # typecheck + lint + format check
```

`site/` (the public website - no build step):
```
cd site
python -m http.server 8000     # then open localhost:8000 in a browser
```
Deploys automatically on every push to `main` that touches `site/**`
(`.github/workflows/deploy-pages.yml`) to
https://sideeffects69.github.io/NovelForge/ - no manual deploy step, and
nothing to run locally to publish a change.
