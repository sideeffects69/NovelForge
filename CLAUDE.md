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
- **`site/`** — the project's public website (a multi-page marketing and
  documentation site: features, the map maker, an honest comparison, FAQ,
  download help, changelog), hosted free on GitHub Pages at
  `https://sideeffects69.github.io/NovelForge/`. Plain HTML/CSS and one tiny
  script; **generated** from `tools/site/` by `tools/build_site.py` and the
  output is committed. This is **not the app** in any form. See the dedicated
  section below before touching it.

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
| `mapgen.py` | Procedural world generation: lobes + warp + noise → marching-squares coasts → priority-flood rivers → biomes → settlements → A* roads → labels. Deterministic per seed, names included |
| `mapmaker.py` | Map data model + `build_primitives()`, the single source of truth rendered by the editor, PNG export and SVG export; terrain stamps, shores, label halos, and the display-list caches |
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
| `widgets.py` | Small reusable widgets, incl. `center_window()` (see rule below), `Card` and `shell()`, `Dropdown`, `AutoScrollbar`, `Gauge`, `StatusBar`, and `ScrolledText.set_report()` |
| `styling.py` | The look of the whole app: theme tokens, the one ttk style, the Tk option-database defaults, title-bar tint, toolbar icons, tooltips (see "The look of the app") |
| `fluent.py` | The rounded controls: ttk *image elements* (9-slice, drawn with Pillow) for buttons, fields, tabs, scroll bars, check/radio boxes (see "The look of the app" - three traps live here) |
| `mapicons.py` | The map maker's tool and toolbar icons, drawn with Pillow (no icon font needed) |
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

    python -m unittest discover -s tests -t .        # about 5 minutes (97 tests)

Needs Windows and a display for the GUI half (skipped otherwise); the windows
open and close on the desktop while it runs. Do not run it as
`python tests/test_x.py`: the `-t .` form is what makes `tests/__init__.py` run
first. One module: `python -m unittest tests.test_gui_walk`. The walk tests
dominate the time (they use every menu command, button and shortcut, and each
step pumps the event loop for a few tenths of a second); the engine and site
tests take about twenty seconds.

**Run it streaming when you are debugging** (`python -u ... -v > file`): a
PowerShell `*>` redirect holds all output until the end, which makes a hung test
look like a slow one.

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
  maker is left out (its window is checked at 100% in `test_gui_maps.py`).
- `test_maps.py` - the map *engine*, no window: determinism (same seed, same
  world, names included), structure (settlements on land, roads never through
  the sea, long rivers, chains of mountains, lakes painted over land), the
  contour maths, the display-list caches, halos, exports. Fast.
- `test_gui_maps.py` - the Map Maker *window*: fits in every theme, every rail
  tool, both dropdowns and every item in them, instant zoom that redraws once,
  no rebuild on redraw, Surprise Me, drawing and undo, the empty-map hint.
- `test_gui_speed.py` - the rounded controls, measured in a bare window with no
  app around them: a window with one of every control and three tall scroll bars
  draws in under 0.4 s (about 0.05 here), a resize repaints in under 0.2 s, and
  controls stay control-sized (button under 50px, slim scroll bar). Each of the
  three bugs it guards - a 2px middle, a 2px trough, image elements without a
  zero minimum size - was re-introduced and the test failed (3.9 s, 0.57 s, 82px).
- `test_site.py` - the website as a crawler meets it: generated output is
  current, one `h1` and a sane heading order per page, title/description length,
  canonical/OG/icons, the Google verification tag, JSON-LD (no invented
  ratings), every internal link and `#anchor`, image alt text and sizes,
  sitemap/robots/llms consistency, no content hidden without JavaScript - and
  that the *claims* on the pages ("nine outline frameworks", "thirteen terrain
  types", "twenty pins", the version) match the code.
- `test_launch.py` - the real entry point: `python -m novelforge` as its own
  process (what `Write.bat` runs), once with a novel and once as a fresh
  install; waits for the window, posts WM_CLOSE (what the X button does), and
  checks a clean exit, saved geometry, the closing backup, and no
  `novelforge-errors.log`. **It finds the window by process id, never by title
  alone:** a fresh install is titled just "NovelForge", which a writer's own open
  window can also be, and the test closes whatever it finds.
- Every check here has been proven able to fail by breaking the thing it guards
  (a menu command, a corkboard button, the map toolbar's padding, the theme
  recolour, the display scaling, and for the newer files: roads across the sea,
  stub rivers, lakes under land, unseeded names, a salted `hash()`, a display
  list that is never remembered, a zoom with no preview, a dead link, a missing
  alt, a wrong claim on the site) and confirming the test names the culprit.
  Two of those mutation checks found tests that *could not* fail - one asserted
  only that a number appeared somewhere, not everywhere. Do
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

## Map maker: what exists (rebuilt 2026-09-20; check before "adding" anything)

**The engine (`mapgen.py`)** builds a world in about 0.7 s, in this order, on a
256x171 grid (roads and biomes on a half-resolution grid):
1. *Land*: each continent is a cluster of overlapping Gaussian lobes, bitten by a
   few "dents" (gulfs), islands added, then the whole field bent by a **broad and
   a fine domain warp** and roughened with fractal noise. Margins keep the sea at
   the top, bottom and sides so the title, scale and compass have room. Sea level
   is a percentile, so "30% land" is exact.
2. *Relief*: bulk rise inland plus **ridged noise**, so mountains are chains.
3. *Coasts*: **marching squares** on the height field (`_contours`) - smooth,
   sub-cell-accurate rings, land winding one way and lakes/inland seas the other
   (negative signed area = land, because y points down). The old Moore-boundary
   tracing gave staircases.
4. *Drainage*: **priority flood** (`_drain`) so every land cell drains to the
   sea; deep basins become lakes; rivers are traced **upstream from their mouths**
   along the biggest catchment (the old code started at high-flow cells near the
   coast and produced 30px stubs), with tributaries.
5. *Biomes*: shares of the land come from the sliders and are enforced by
   **ranking cells** (percentile), not fixed thresholds on noise (which put a whole
   interior in one biome on some seeds); masks are blurred, faded toward shores,
   contoured.
6. *Settlements*, then 7. *roads* (**A\*** over a cost grid, MST plus a few
   loops, existing roads cheap), then 8. *labels* (region names at the point
   deepest inland; the ocean name at the point farthest from land, never on a lake
   and never in the compass corner).
Everything is seeded - **names included** (`name_for(..., seed=)`; before, names
were different on every run, contradicting the "same seed, same world" promise
written on the map).

**Also present** (unchanged in spirit): the **Surprise Me** and **Generate...**
buttons; per-culture, per-role name lists in `Name Styles.json`; greedy
label-collision avoidance (`layout_pin_labels`), hiding a name rather than
overprinting; pins linked to Location sheets (right-click -> Link, double-click
opens the sheet in Word); layers; four art styles; PNG, SVG and Word export.
**One shared primitive list** (`build_primitives()`) is rendered identically by
the Tk canvas, the PNG exporter and the SVG exporter - keep it that way.

**Rendering facts that cost time:**
- **`PAINT_ORDER`: water and land share rank 1, so shapes paint in the order they
  were made.** Water used to be rank 0 (always underneath), which hid every lake
  under the land that held it - generated or hand-drawn. Emit big rings first
  (the generator sorts by area) so a lake follows its land and an island in a
  lake follows the lake.
- **The text primitive has an optional 11th element, a halo colour**; read every
  text primitive through `mapmaker.text_parts()` (the canvas fakes the outline
  with four offset copies, Pillow uses `stroke_width`, SVG `paint-order`).
- **Shores are painted for *all* coasts before any land** (a wide stroke round one
  island would otherwise cover a neighbour drawn earlier): pale shallows as stacked
  wide strokes, ripples as thin *offset rings* (`_offset_ring`, which skips vertices
  that would fold). An earlier version made ripples with sea-coloured "cover"
  strokes and left radial tick artifacts at sharp corners.
- **Seeds use `zlib.crc32`, never `hash()`** (`_stable_seed`): Python salts `str`
  hashes per process, which reshuffled every forest each time a map was opened.
- **Caches** on `GameMap`: `_prim_cache` (whole display list, keyed on a content
  fingerprint - views, zoom and selection are not in it) and `_shape_cache` (each
  shape's share, so dragging one vertex re-scatters one forest). `build_primitives`
  returns a *copy*. `_scatter_in_bounds` uses a Pillow-rasterised polygon mask
  instead of ray casting (100x faster).
- **A Tk canvas does not clip.** Wide strokes near the map edge spilled onto the
  desk; `MapEditor._draw_desk` paints desk-coloured bands over everything outside
  the sheet (shaved by a pixel - float coordinates round) and draws the shadow
  on top of them.

**The window (`mapeditor.py`)**: a card-strip of actions (map picker, primary
*Surprise Me*, *Generate...*, New, Save, Undo, Redo, and **Export** / **More**
dropdowns), a tool rail with drawn icons, a palette card (terrain, pin type,
layers), the map on a "desk" with a shadow, a properties card, and a status strip
with zoom. The picker shows an unsaved map as "Name  (unsaved)". Zoom scales the
items on screen at once (`canvas.scale`) and does **one** real redraw when the wheel
goes quiet (140 ms). Panning still uses `canvas.move`. Redraws reuse the cached
display list, so nothing is rebuilt for a zoom, a selection or a pan.

**Genuine gaps**: no town/city or building generator (those map kinds start as a
blank grid to draw by hand; Watabou's TownGeneratorOS is the reference), no
click-to-stamp brush for single trees or castles, no drawn political borders or
realm areas, and coasts are noise-and-warp rather than a Voronoi mesh (Azgaar's
generator is the reference if that is ever worth a rewrite).

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

## `site/` - the public website (multi-page and generated, 2026-09-20)

A real website for the desktop app, not a version of it: home, features, the map
maker, an honest comparison with Scrivener/Atticus/Obsidian/Word, FAQ, download
help, changelog, support, and a 404. Plain HTML/CSS and one tiny script
(`app.js`, scroll-reveal). Hosted free on GitHub Pages, deployed by
`.github/workflows/deploy-pages.yml` on any push to `main` that touches `site/**`.

**It is generated.** Edit `tools/site/pages/<slug>.html` (page bodies; `{{root}}`
is the path back to the top so it works under `/NovelForge/` and on its own domain,
`{{repo}}`, `{{version}}`, `{{author}}`) and the `PAGES` list / constants in
`tools/build_site.py`, then run `python tools/build_site.py` and **commit `site/`
too**. The generator writes the nav, footer, canonical URLs, Open Graph/Twitter
tags, favicon links, JSON-LD (SoftwareApplication, SoftwareSourceCode, WebSite,
BreadcrumbList, FAQPage built from the `<details>` on the FAQ and home pages),
`sitemap.xml` (with images), `robots.txt`, `llms.txt`, `llms-full.txt` (the
site's own text as plain markdown) and measures every local `<img>` so its
`width`/`height` are right. `--check` exits 1 if `site/` is stale; `tests/test_site.py`
runs that and much more. Add a page by adding it to `PAGES` and writing its body.

**Honesty rules for the copy** (the user was explicit): no invented ratings,
reviews or testimonials (the JSON-LD must not contain `aggregateRating`), say
"Windows only" plainly, say what NovelForge does *not* do (ebook typesetting,
collaboration, Mac), and mark competitor facts we are unsure of "See vendor"
rather than guessing. Every numeric claim (frameworks, terrain types, pins, art
styles, the version) is checked against the code by `test_site.py`.

**AI and search discoverability, and its limit.** `robots.txt` explicitly allows
GPTBot, ChatGPT-User, OAI-SearchBot, ClaudeBot, PerplexityBot, Google-Extended,
Applebot-Extended, CCBot and others; `llms.txt` is a short plain-text summary.
**But crawlers only read `robots.txt` and `llms.txt` at the root of a host**, and
this is a *project* page under `/NovelForge/`, so those two files inside `site/`
are not found by anything on their own; what counts is the host's root.
**That root belongs to another project** (checked 2026-09-20): the repository
`sideeffects69/sideeffects69.github.io` was created on 2026-09-19 for the owner's
other site, *Magic Apply - Jobs*. Its `robots.txt` already allows every crawler, so
NovelForge is crawlable and there is nothing to create - but its `Sitemap:` line
and its `llms.txt` name only Magic Apply. **Never create that repository and never
push anything over it.** Adding
`Sitemap: https://sideeffects69.github.io/NovelForge/sitemap.xml` to its
`robots.txt`, and a NovelForge line to its `llms.txt`, would help; that is a change
to another project's public repo, so it was offered to the user, not done.
`tools/site-root/README.md` (generated) says the same. Sitemap submission in
Search Console works regardless of location.

**Google Search Console** is a URL-prefix property for the project page, verified
by the `google-site-verification` meta tag on the home page (it is in
`build_site.py` as `VERIFICATION` and asserted by a test - do not lose it). The
user still has to press VERIFY and submit `sitemap.xml` themselves.

**Screenshots** (`site/assets/screenshots/`) come from a disposable demo novel
("The Ashfall Crown"), never the writer's own: `python tools/uishots/run.py --out
<dir> --themes premium --client-only` for the main window, dashboard, corkboard,
outline and story graph, plus `tools/site_assets.py` for the Map Maker with a
generated world, the command palette and the three sample map JPEGs. Use the
premium theme (the site is navy). Follow the isolation rules under "If you drive
the real GUI" - always assert the loaded novel is the demo one first.

**Progressive enhancement**: reveal-on-scroll hides content only under a `js`
class set inline in `<head>`, so scripting-off or a failed script leaves the page
readable (a test guards it).

**The donate QR images are duplicated**, not symlinked: `assets/donate/` (the
README, repo-relative paths) and `site/assets/donate/` (Pages only ever sees
`site/`). Update both if the codes are regenerated.

**The download link points at `/releases/latest`**, so it never needs updating;
just create the Release. The full CSS palette is in `site/style.css` custom
properties - copy those hex values rather than re-deriving them.

**The brand**: `brand/originals/*.jpg` are the writer's own logo files;
`python tools/brand.py` derives `brand/icon.png`, `icon.ico`, `banner.jpg` and every
`site/assets/brand/*` size, the favicon and the web manifest. The logo is used
everywhere on purpose ("do not skip on logos and favicons"): window/taskbar icon
(`styling.app_icons`, `set_app_identity`), welcome screen, About box, README,
website header, favicons and Open Graph image.

## The look of the app (rebuilt 2026-09-19, rounded and layered 2026-09-20)

The desktop UI was modernised in two passes and verified by photographing every
window in two themes (`tools/uishots/`), not by reading code.

**Layers.** A window backdrop (`tokens["window"]`, the darkest surface) with
rounded **cards** standing on it (`widgets.Card`, tone `panel`), the writing
sheet and text fields as `page`/`field` cards inside those, and controls on top.
The window's own chrome (menu strip, toolbar, status bar) uses `Chrome.*` styles
because it sits on the backdrop, not on a card. **Every tool window and dialog
gets the same shell** from `widgets.shell(window)`: the backdrop colour plus one
card, whose body you build in exactly as before (`Dialog`, the corkboard, outline,
story-graph windows... all use it; the map maker builds its own cards).

- **One flat "clam" style for every theme** (`ui/styling.py`), *derived* from the
  nine keys in `config.THEMES` (hover, borders, row selection, legible secondary
  text). Windows' native "vista" theme ignores every ttk colour, which is why the
  old app looked like a 2005 dialog and dark palettes had white boxes in them.
- **Rounded controls** (`ui/fluent.py`): ttk *image elements* - 9-slice PNGs drawn
  with Pillow (4x supersampled) from the tokens - for buttons (`TButton`,
  `Accent.`, `Tool.`, `Compact.`, `Quiet.`, `Menu.`), fields, tabs, scroll-bar
  thumbs, check and radio boxes, and `Rail.Toolbutton` (a tool rail that tints
  when selected). On a theme change the *same* `PhotoImage`s are repainted in
  place (`Kit.photo` -> `paste`), so live widgets update; elements are created
  once, layouts re-applied every `apply()`. **Three traps, each of which broke
  the app before it was understood:**
  1. **ttk tiles the edges and middle of a 9-slice image; it does not stretch
     them** (Tk 8.6), one draw call per tile. A first version had a 2px middle:
     one text field took ~1000 draws (~200 ms), every button, every resize, every
     window paid it, and the suite went from about a minute to five. `MIDDLE = 64`.
     **The same applies to any image element with `sticky="nswe"` and no border,
     even a transparent one:** the scroll bar's trough used a 2px clear image that
     ttk tiled over the whole bar (hundreds of calls each), and a window with three
     scroll bars took 0.8 s to open (0.09 s after the fix, `TROUGH = 128`). If a
     window is slow to open, suspect an element whose image is tiny.
  2. **An image element's minimum size is its image's size**, so that 64px middle
     made every button ask for 82px. Every 9-slice element is created with
     `width=0, height=0`, and `padding=PAD` (3px) - the default padding is the
     border (9px a side), which stacked on the style's own padding made a button
     47px tall instead of ~34.
  3. **ttk fills the whole widget rectangle with the style's `background`
     before drawing the element**, so a rounded control with transparent corners
     shows a square of that colour unless it is exactly the colour behind the
     widget - and it must not vary by state. `styling.apply` sets each style's
     background to what sits behind it (the `behind` list) and clears its state
     maps; states are the image's job.
  Also: ttk finds an element by the *last dotted part* of its name (`*.thumb`,
  `*.trough`, `*.downarrow`, `*.textarea`); PhotoImages must stay referenced;
  always pass `master=` to `ImageTk.PhotoImage` (a process that has had two Tk
  roots otherwise attaches images to the wrong one).
- **`Card`** is a Canvas: four anti-aliased corner images, two rectangles and
  four hairlines, with a `.body` frame inset by `padding`. `fit` makes it ask for
  its content's size ("height", "width" or "both") instead of Tk's default
  378x265 - needed for any card that is not simply filling a grid cell; `ground`
  says what it stands on. `restyle()` is a duck-typed hook: `styling.retheme`
  calls it (and any widget's `restyle`) on every descendant.
- **`Dropdown`** (`widgets.py`) is a small borderless window of `Menu.TButton`s,
  not a native menu. A posted native menu runs a modal loop on Windows, which
  freezes anything driving the window (the test walker included) and cannot be
  themed. It closes on Escape, on a choice and on focus loss.
- **Type scale** in `styling`: `BASE, SMALL, LEAD, TITLE, DISPLAY, HERO =
  10, 9, 12, 15, 21, 28`; `UI_FONT` resolves to Segoe UI Variable on Windows 11.
- **Classic Tk widgets** (Text, Listbox, Entry, Canvas...) that `ttk.Style`
  cannot reach take their colours from the Tk *option database* (`option_add`,
  priority 60): defaults only, anything set explicitly wins.
- **Title bar** is tinted through DWM (`styling.style_titlebar`; Windows 11, a
  silent no-op elsewhere) from `center_window()`. Tk rebuilds its top-level
  window when first mapped, throwing the attribute away, so it is re-applied on
  `<Map>`.
- **The menu bar is drawn by the app** (`App._build_menu_strip`), because
  Windows owns the native one and gives Tk no way to recolour it. The `tk.Menu`
  tree from `_build_menu` stays the source of truth and is never attached to the
  window; each strip button gets a `menu clone` of a top-level menu (`tk::MbPost`
  refuses a menu that is not a descendant of its menubutton; `clone` is what keeps
  dynamic entries live). Popup colours are set on the originals *before* cloning
  (`_theme_menu`). The detached bar's index 0 is a tearoff entry: skip by
  `type()`, never index blindly.
- **Icons.** The main toolbar uses the system icon font (Segoe Fluent Icons /
  MDL2 via Pillow, `styling.IconSet`), so no icon files ship; the map maker
  draws its own (`ui/mapicons.py`) because the font has no "freehand" or "erase".
  Icons are baked in a colour, so a theme change redraws them.
- **Command palette** (`palette.py`, Ctrl+Shift+P - Ctrl+K is the corkboard),
  built each time by walking the real menus, so it cannot drift from them.
- **First-run screen** (`welcome.py`) overlays the panes only when there is no
  novel.
- **Reports** (`ScrolledText.set_report`): every generated report is plain text
  with the same conventions (title over `====`, ALL-CAPS section names, `----`
  rules, `!!`/`~` severity markers); `set_report` styles those and keeps a
  monospace body so aligned tables still line up. Tk paints a tag's background
  across its line *spacing*, so a rule is a 1px line with blank lines around it.
  `ScrolledText` on a card sits in an inset rounded `field` card.
- **A theme change recolours what is already on screen** (`styling.retheme`).
- **Button rows wrap** (`widgets.flow`); `Compact.TButton` has a natural width.
  An explicit `width=` on a widget still wins over the style (the Sprint window
  uses `width=7`: three default buttons are ~110px each and do not fit it).
- **Scroll bars** are a slim thumb (`AutoScrollbar`), *disabled* rather than
  hidden when there is nothing to scroll (hiding changes the width the content
  has, and wrapped text can re-flow back and forth around the threshold).
- **Map editor** stays "fit to window" until the writer pans or zooms
  (`_auto_fit`). See "Map maker" for its layout.
- **Corkboard cards** are drawn with `corkboard.rounded()` - a smooth polygon
  through its corners - not `create_rectangle`, and use the theme tokens
  (`styling.current_tokens()`), not the older `config.theme()` dict.
- **`display_scale()`**: requested window sizes are for a 100% display and are
  multiplied by it in `center_window`; the app is per-monitor-DPI aware.
- **Not done, deliberately:** drop shadows and blur (a card's edge is a hairline;
  the map's shadow is stacked rectangles), smooth hover transitions, and
  `premium` as the default theme - `warm` still is (it would only affect new
  installs; left as the writer's decision, which has not been made).
- The centre header's title label is squeezed by about 19px at the 900px minimum
  window width (long scene titles are cut short). It predates this work; the clip
  detector reports it and the test ignores it.

## Lessons that cost real time (2026-09-20)

- **Look at a screenshot after every visual change, and time it.** The 64px tile
  fix made the suite fast and, unseen, made every button 82px tall; the cause was
  found only because a window was photographed. Speed *and* size regress silently.
- **A suite that suddenly takes five times longer is a performance bug, not a slow
  machine.** Profile with `cProfile` (it showed 100% of the time inside Tcl), then
  bisect widget types inside the running app. A `ttk.Style` call at runtime also
  costs ~2 s once (a global theme-changed pass over every widget) - do not
  benchmark after calling one.
- **Do not put regexes or backslashes in inline shell heredocs.** The command layer
  here collapses `\` and once turned `\b` into a literal backspace character, so a
  test silently matched nothing. Write patch scripts with the file tool and run
  them.
- **PowerShell has no heredocs**; use Bash for `python - <<'EOF'` and PowerShell for
  Windows-native launching (`msedge --headless`, `cmd /c`).
- **A Tk canvas never clips**, a `pack`ed child is silently unmapped when it does
  not fit (grid overflows instead), and float coordinates round: all three have
  produced "stray pixel" bugs.
- **`hash()` of a string is salted per process.** Use `zlib.crc32` for anything
  that must be the same tomorrow.
- **Headless Edge/Chrome cannot be narrower than ~500px**; to test a phone layout
  load the page in a 390px `<iframe>` from a wrapper file.
- **Test claims against the code**: the site said "nine frameworks" in six places;
  one test now compares them with `structures.framework_names()`.

## Releasing a new version

Releases are made on GitHub, and there is **no `gh` CLI** on the developer's
machine. The site's Download button points at `/releases/latest`, so it shows
the new version only once a *Release* exists - pushing a tag alone does not
change it.

1. Bump `APP_VERSION` in `novelforge/__init__.py` (the About box and the
   settings file read it). `web/package.json` has its own, unfinished version
   and is left alone.
2. Run the whole test suite, and `python tools/build_site.py --check`. If the
   site's version or copy changed, run `python tools/build_site.py` and commit `site/`
   (and `tools/site-root/`) with it.
3. Commit, `git tag vX.Y.Z`, `git push origin main vX.Y.Z`.
4. Create the Release for the tag. Follow `v1.0.0`'s shape: title
   "NovelForge X.Y" (`v1.0.0` is "NovelForge 1.0", `v2.1.0` is "NovelForge 2.1"),
   a short "What's new" written for a writer, a "Getting started" (install
   Python 3.13+, download **Source code (zip)**, double-click `Write.bat` - it
   installs python-docx and Pillow itself the first time), an
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
   Then download the tag's source zip into a short path (`C:\nf_rel`) and run
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

`site/` (the public website - generated, then served as plain files):
```
python tools/build_site.py            # regenerate site/ (and tools/site-root/)
python tools/build_site.py --check    # is it current?
python -m http.server 8000 --directory site   # then open localhost:8000
```
**After regenerating, `git status` may list every generated `site/` file as modified
when nothing changed:** the generator writes LF and this machine has
`core.autocrlf=true`. `git diff --stat -- site` is the truth (empty means only line
endings differ); if it is empty, `git checkout -- site` puts the files back as git
had them. Never run that with a non-empty diff.

Deploys automatically on every push to `main` that touches `site/**`
(`.github/workflows/deploy-pages.yml`) to
https://sideeffects69.github.io/NovelForge/ - no manual deploy step. `Write.bat`
installs `python-docx` and `Pillow` on first run if they are missing.
