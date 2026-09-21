# Obsidian, studied for NovelForge 2.3

Research only; no code was written. Date: 2026-09-20. Anything not confirmed from a primary source is marked (unverified). Obsidian's help moved from help.obsidian.md to obsidian.md/help; URLs below are the new ones.

**One-paragraph answer.** Obsidian is a folder of plain files plus a derived index of links, properties and tags, with a fast way to move around it. NovelForge already owns the hard part (a typed story graph, scenes and characters with properties) but shows almost none of it where the writer is looking. So the useful Obsidian ideas for a novelist are: connections beside whatever you are viewing, jump-to-anything, saved table views, a free-form plot board, hover reference cards, and an export door into Obsidian itself. What would be wrong to copy: markup typed in prose, plugins, sync, tabs.

## 1. How Obsidian works

**Vault and files.** A vault is a folder of plain files. Native formats: `.md`, `.base` (YAML), `.canvas` (JSON Canvas), images, audio, video, PDF. Settings sit in a hidden `.obsidian/` folder (`workspace.json` = current layout, `workspaces.json` = saved layouts). The link/tag index is a derived cache in IndexedDB: files are the truth, the index is rebuildable. Steph Ango's "File over app": "the files you create are more important than the tools you use to create them"; hence open formats. The homepage says "Free without limits" for personal use; Sync and Publish are separate services whose terms I could not check (the /sync help page returned 404; unverified).

**Links.** `[[Note]]`, `[[Note|alias]]`, `[[Note#Heading]]`, `[[Note#^block-id]]`, folder paths from the vault root. Renaming a file rewrites every link (default on). A per-link alias changes one link; the `aliases` property makes a note findable under other names everywhere. `# | ^ : %% [[ ]]` in a note name break links (forum thread, search result only). Shortest-unique-name resolution is (unverified). Hovering a link previews it (hold Ctrl in the editor).

**Backlinks.** Two lists per note: *linked mentions* (notes that `[[link]]` to it) and *unlinked mentions* (its name as plain text elsewhere, each with a one-click "link"). Shown in the sidebar (follows the active note), a pinned tab, or the foot of the note; toggles for collapse, more context, sort, search filter.

**Graph.** Global (every note) or local (active note; a Depth slider adds ring after ring). Filters: search, tags, attachments, existing-files-only, orphans. Groups colour nodes by a search query. Display: arrows, text fade, node size, an Animate replay; four physics forces (centre, repel, link, distance).

**Quick Switcher, palette, hotkeys.** Ctrl+O: keyboard-only fuzzy search of note names and aliases; Enter opens, Ctrl+Enter opens in a new tab, no match + Enter creates the note, empty box lists recents; above 10,000 items it switches to a simpler ranking for speed. Ctrl+P: fuzzy command list ("scf" finds Save current file), recents first (1.8.3), pinnable. Hotkeys: any command to any key. The palette discovers; hotkeys promote.

**Properties, tags, templates, daily notes.** Properties are YAML front matter between `---` lines: text, list, number, checkbox, date, date-time, tags; built-ins `tags`, `aliases`, `cssclasses`. Nested tags use a slash (`#inbox/to-read`); searching the parent matches children. Templates: a folder, "Insert template", `{{title}} {{date}} {{time}}`. Daily notes: a date-named note from a template, opened by one command.

**Bases (`.base`, YAML).** `filters` (and/or/not of `file.hasTag("x")`, `file.folder("Scenes")`, `status != "done"`), `formulas`, `properties` (display names), `summaries`, and `views` (`type: table|list|cards`, `order` = columns, `groupBy`, own filters). Kanban layout arrived in 1.14.0 (changelog, 2026-09-02). `file.backlinks` is documented as performance-heavy. In essence: a saved filter, a column list and a sort over notes that already have properties.

**Canvas and JSON Canvas 1.0 (MIT).** Infinite board of text cards, note cards (live vault files), media, web pages; edges dragged from a card's edge dot, double-click to label; groups; colours. Space-drag pans, Ctrl+wheel zooms, Shift+1 fits all, Alt+drag duplicates. File: `{"nodes":[...],"edges":[...]}`; array order is z-order. Node: `id, type (text|file|link|group), x, y, width, height` (integers), optional `color`; text has `text`; file has `file` and optional `subpath` (`#heading`/block); link has `url`; group has `label`, `background`, `backgroundStyle`. Edge: `id, fromNode, toNode`; optional `fromSide/toSide` (top|right|bottom|left), `fromEnd/toEnd` (none|arrow; defaults none/arrow), `color`, `label`. Colours: hex or presets `"1"` red to `"6"` purple.

**Search, embeds, outline.** Operators `file: path: content: tag: line: block: section: task:`, `[property:value]`, space = AND, `OR`, `-NOT`, parentheses, "phrases", `/regex/`; a ```` ```query ```` block embeds live results. `![[Note#Heading]]` transcludes text. Outline lists the active note's headings; dragging one reorders the note.

**Layout.** Tabs (Ctrl+T), split right/down, stacked tabs, pinned tabs, pop-out windows, *linked views* (a Graph/Backlinks/Outline tab that follows another tab), Workspaces = named saved layouts.

**Plugins.** Community plugins are JavaScript that "inherit Obsidian's access levels": they can read files, use the network and install programs; Restricted Mode is the default. Dataview treats YAML and `[key:: value]` fields as a database (`TABLE ... FROM ... WHERE`).

**Fiction use.** Pattern (Loreteller, DEV "Novelist" vault): `Manuscript/` with one note per scene, `Characters/`, `Worldbuilding/`, `Plot/`, `Research/`, `Templates/`. "One character, one note"; link from scenes to lore "not the reverse"; link an entity on first mention per note. Scene front matter: `pov: "[[Elena]]"`, `chapter`, `act`, `status: draft`, `conflict`; Dataview lists scenes with no conflict or still in draft. Plugins: Longform (scene files, an index note whose `scenes:` list orders them, word goals, a compile that strips links, "never alters" your notes), Novel Word Count, Templater, Calendar, Kanban, StoryLine, World Builder. Their own honest limits: heavy setup, "wrong for writers who want something that works the moment you open it", sync needs outside help, plugins "essential rather than optional". NovelForge starts where those plugins end.

## 1A. What NovelForge already has (read from code)

- **Model** (`model.py`): `Scene` (status, POV, character/location/item/faction/thread ids, goal/conflict, story_date, word counts), `Entity` (aliases, tags, summary, `cache` of sheet fields), `Note.links`, `TimelineEvent`, `Idea`. `from_dict` ignores unknown keys, so a new defaulted field is safe.
- **A link graph** (`storygraph.py`): declared edges (`linked`, `pov`, `references`, `covers`...) plus *detected* `mentions` edges (one combined regex over every name and alias). That is Obsidian's linked and unlinked mentions, already computed. Cold build reads every scene (~25 s at 300,000 words); `_signature()` uses mtimes; `cached_graph()` returns only a warm one. The cache is in memory, so every launch is cold.
- **Binder** (`ui/app.py`): Treeview rows `scene:<id>`, `entity:<id>`, `note:<id>`, `event:<id>`, `beat:<key>`, `mapfile:<rel>`; jump = `tree.selection_set(iid)` then `on_tree_select()`.
- **Inspector**: the entity view shows a bare "Linked scenes: 12" and a "Where mentioned?" button that rescans into a modal report (`cmd_mentions`, `Project.find_mentions`).
- **Palette** (`ui/palette.py`, Ctrl+Shift+P): walks the menus; finds commands, never the book's own things. There is no jump-to-scene/character box, only type-ahead in the binder.
- **Keys**: Ctrl+O is Open novel (so not Obsidian's Quick Switcher key). Free at app level (checked against `accelerator=` and the text-widget bindings): Ctrl+P, F3, Ctrl+Shift+B. Editor-local Ctrl+Shift+K/T/U/L/S/P are taken.
- **Corkboard** (`ui/corkboard.py`): ordered scene cards on a Canvas; not free-form, no arbitrary edges. Reusable: `Tooltip` (`styling.py`), `Dropdown`, `App._busy()`, `build_graph_with_progress`, `project.action(label)` (undoable change), `atomic.write_text_atomic`, `docxio.read_paragraphs_with_format`.

## 2. Fit table

| Obsidian feature | NovelForge today | Value | Effort | Risk | Verdict |
|---|---|---|---|---|---|
| Vault of plain files | `.docx` + `project.json` (rule 1); no Markdown | H | M | low if one-way | **Adapt**: export-only vault |
| Wikilinks typed in prose | none; names detected by regex | L | M | high (prose compiles) | **Skip** typing; generate in export |
| Aliases | `Entity.aliases` feed mentions | H | S | low | Have; add to Go to |
| Backlinks, linked + unlinked | graph has both; UI shows a count + modal | H | M | low with an index | **Build**: Connections |
| "Link" an unlinked mention | continuity check flags it; no action | H | S | low | **Build** (in Connections) |
| Global graph | Ctrl+G windows, relationship web | M | - | - | Have |
| Local graph, depth, groups | none per selection | M | M | med (canvas) | Adapt later: static rings |
| Quick Switcher | binder type-ahead only | H | S | low | **Build**: Go to, Ctrl+P |
| Command palette | Ctrl+Shift+P | M | S | low | Adapt: recents, `>` prefix |
| Custom hotkeys | fixed | L | M | med (Tk defaults) | Skip |
| Tabs, splits, workspaces | one editor + inspector | M | L | high (`app.py` hub) | Skip |
| Hover page preview | tooltips on controls only | H | M | low if dict-only | **Build**: Peek |
| Embeds / transclusion | none | L | M | med | Skip |
| Nested tags | entity/idea tags; scenes only a colour label | M | M | low | Adapt: scene tags, `a/b` match |
| Properties (YAML) | fields live in JSON | H (interop) | S | low | Adapt via export |
| Bases table/cards/kanban | corkboard (ordered, unfilterable) | H | M | low | **Build**: Scene Table |
| Canvas / JSON Canvas | corkboard scene-only; web read-only | H | L | med | **Build**, scoped: Plot Board |
| Search operators | Ctrl+F plain text | M | S | low | Adapt: in Go to + table |
| Live query blocks | none | L | M | med | Skip |
| Templates, daily notes, outline | sheets, sessions/sprint, Ctrl+L | L | - | - | Have |
| Community plugins, Dataview JS | none | L | L | high (security) | Skip (saved views cover it) |
| Sync, Publish | OneDrive-safe saves | L | L | high (cloud) | Skip |
| Graph animate, physics | none | L | M | med | Skip |

## 3. Concrete designs

**Shared speed contract (rule 3).** Nothing here opens a `.docx` while drawing or runs per keystroke. Sources are `project.json`, `Entity.cache`, a warm graph, or a persisted mention index. Scanning is an explicit `App._busy()` command that re-reads only scenes whose mtime changed. Engines are Tk-free modules with instant pure tests (like `test_maps.py`); each window gets a `Sandbox` test at 100% and 125% that fails on clipping (`tests/gui_support.py`). Every check should be proven able to fail by breaking the thing it guards.

### 3.1 Connections panel (backlinks) - Build
- **Data.** Declared links (`scene.*_ids`, `note.links`, `event.scene_id`, `beat.scene_ids`) are instant from the manifest. Mentions come from a warm graph, else from a new persisted `mentions.json` beside `project.json`: per scene `{mtime, counts by entity, up to 20 character offsets}`. No prose is stored (rule 1); a click reads one scene to cut a snippet.
- **UI.** A Connections section at the foot of the inspector for scene, entity, note and event, replacing "Linked scenes: N" and the modal. Rows jump to the binder item. "Mentioned, not linked" rows carry **[Link]**, which adds the entity to that scene's Present/Locations list through `project.action("Link mention")` (undoable).
- **Files.** New `backlinks.py` (`connections(project, kind, id, graph=None)`, `link_mention`), `mentionindex.py` (`refresh(project, progress)` re-reads changed scenes only; `update_scene(project, id, text)` called from commit/autosave for the open scene, one regex), `ui/connections.py`. Touch `app.py`: a few lines in `_render_entity`/`_build_scene_inspector`/`_render_note`, plus a shared `App.goto(kind, id)`.
- **Tests.** Counts equal `storygraph.build` mentions; unlinked = mentioned minus declared; Link then undo restores; a restart reuses the index; unchanged scenes are not re-read (count `read_prose` calls); rendering with `read_prose` patched to raise still works.

```
CONNECTIONS   Ada Vane                     [Update]  scanned 2 min ago
Linked (12)      Ch1 The Gate  POV ◆      Ch3 Ashfall Road  present
Mentioned, not linked (3)
   Ch7 The Ledger   "...Ada slid the key..."            [Link]
Research (1)     Salt trade routes
Timeline (2)     Ada crosses the pass     Ada's trial
```

### 3.2 Go to... (Quick Switcher) - Build
- **Data.** One flat list from the manifest: scenes (title, synopsis, chapter), chapters, entities (name, aliases, role, summary), notes, events, beats, maps, ideas. Rebuilt lazily when a cheap manifest signature changes.
- **UI.** **Ctrl+P** (Ctrl+O is Open novel; Ctrl+Shift+P stays the command palette, the VS Code pairing) and Edit > Go to... (menu entry so the walk tests and palette see it). Borderless window styled like `palette.py`: kind icon, title, dim subtitle ("Character - Protagonist"), a preview strip with the synopsis or summary. Empty box: last 12 visited. `>` hands over to the command palette; `status:draft pov:ada` filters (operator-lite, shared with 3.3). Enter jumps, Ctrl+Enter opens in Word, Shift+Enter creates a scene/character named as typed.
- **Fast.** Reuses `palette.score()`; caps at 60 rows; no I/O. Like the palette it must close on Escape and focus loss, so the GUI walk (which fires every menu command) cannot hang on it.
- **Files.** `navindex.py` (targets, ranking, recents), `ui/goto.py`, a binding and menu entry in `app.py`, README key table.
- **Tests.** Alias finds the entity; whole word beats fuzzy; empty box shows recents; 5,000 targets rank in under 50 ms; Enter selects the right binder row.

```
+------------------------------------------------------+
| ada v                                                |
|  Character  Ada Vane        Protagonist        <-    |
|  Scene      Ada at the Gate  Ch 1 - Draft            |
|  Note       Ada's cipher     research                |
|  synopsis: Ada reaches the gate and finds it barred. |
+------------------------------------------------------+
```

### 3.3 Scene Table (Bases-lite) - Build
- **Data.** Scenes, chapters, entities from the manifest. Columns: Chapter, Scene, Status, POV, Locations, Words, Target, Story date, Type, Tags. `ProjectData.saved_views: List[dict]` (default empty): name, filter string, sort, columns, group-by, the same shape as a `.base` view so export maps one to one.
- **UI.** Plan > Scene Table, **F3**. A `ttk.Treeview` (headers sort; rows coloured by `STATUS_COLOURS`), a filter box with operators (`status:draft -status:final pov:Ada in:"Ch 3" tag:clue`), a Views dropdown (save/switch), group headers, double-click jumps, right-click "Set status" on a multi-selection via `project.action`.
- **Fast.** Manifest only; 1,000 rows insert in well under 100 ms; filter re-runs debounced 150 ms.
- **Files.** `views.py` (parse/apply/sort/group/save), `ui/scenetable.py`, `model.py`, menu entry. **Trap:** `ProjectData.to_json()` lists its keys by hand, so `saved_views` must be added there (and type-checked in `from_json` like `rows()`) or it silently never saves. `Scene.tags` needs nothing, since scenes serialise through `dataclasses.asdict`.
- **Tests.** Quotes, negation, `tag:a` matching `a/b`; an unknown operator shows an error rather than silently matching nothing; a saved view and a scene tag both survive save and reopen (this is the test that catches the trap).

```
Scene Table   View: Revision pass v  [Save view]   status:draft pov:Ada
 Chapter       Scene         Status  POV  Words  Target  Story date
 1 Ashfall     The Gate      Draft   Ada  2,140  2,500   1187-03-02
 9 scenes . 14,820 words . sorted by Story date        [Set status v]
```

### 3.4 Peek (hover reference card) - Build, small
- **Data.** Name-to-entity map from `Entity.all_names()` (rebuilt when entities change); card = name, role, summary, three sheet fields from `entity_fields(refresh=False)` (`Entity.cache`, no I/O).
- **UI.** Rest the pointer 450 ms over a recognised name in the editor, a Connections row or a Go to row: a small card appears; Esc or moving away closes it. Off in F12 distraction-free; View menu toggle.
- **Fast.** `<Motion>` only stores coordinates and re-arms an `after()` timer (as `Tooltip` does); the word under the pointer (`text.index("@x,y")`) is resolved when the timer fires. Never per keystroke.
- **Files.** `ui/peek.py` (a positional variant of `Tooltip`), a few lines where the editor is built.
- **Tests.** Pure `word_at` + lookup; hover shows the card; patched `read_prose` never called; hidden in F12.

### 3.5 Plot Board (`.canvas`) - Build, scoped (largest; may slip to 2.4)
- **Data.** A JSON Canvas file per board in a new `14 Boards/` folder (add to `config.FOLDERS`; grep the tests for folder counts first). Scene/character/location/note cards are `file` nodes whose `id` is the NovelForge id and whose `file` is the deterministic vault path from 4.1, so the same board opens correctly in an exported vault (the spec only says `id` is a unique string; how Obsidian treats non-hex ids on re-save is unverified). Free text = `text` nodes, `group` nodes, edges with label/sides/arrows/colours.
- **UI.** Plan > Plot Board, **Ctrl+Shift+B**. Obsidian gestures: drag to move, wheel zoom, space/middle-drag pan, Shift+1 fit, double-click empty for a text card, drag from a card's edge dot to make an arrow, double-click an arrow to label it, colour swatches, "Add" via the Go to list, "Fill from story" (top-N characters, edges from `graph.co_occurring`).
- **Fast.** Items moved with `canvas.coords`/`move`; pan is `canvas.move("all")`; zoom is `canvas.scale` plus one debounced real redraw (as `mapeditor.py`); tested at 300 cards / 500 edges.
- **Files.** `jsoncanvas.py` (engine: load/validate/atomic save, z-order = array order, integer coordinates, unknown keys preserved), `ui/board.py`, menu entry.
- **Tests.** Spec example round-trips; dangling edge ends are dropped with a warning, not a crash; a drag never triggers a synchronous full redraw; GUI fit at 100%/125%.

### 3.6 Small adapt items (ride along with 3.2 and 3.3)
- **Scene tags**: `Scene.tags: List[str]`, nested `a/b` (parent matches children, like Obsidian), edited in the inspector, filterable everywhere.
- **Palette recents**: the last few run commands float to the top (Obsidian 1.8.3), stored in memory and settings.

## 4. Interoperability

### 4.1 Obsidian vault export - Build
File > Export > Obsidian vault... (`vaultexport.py`), wrapped in `_busy()`. **One-way, read-only snapshot**: `.docx` stays the truth (rule 1); a `README.md` in the vault says so. Nothing is imported back except boards.

```
<Novel> Vault/   README.md
  Scenes/<Chapter 03 - The Gate>/<012 The Gate>.md    Chapters/  Timeline/
  Characters/ Locations/ Items/ Factions/ Plot Threads/  Notes/
  Boards/*.canvas     Bases/Scenes.base  Characters.base
```

Scene note (every value emitted with `json.dumps`, a valid YAML scalar, so no YAML dependency; links quoted as in the guides):

```yaml
---
nf_id: scn_a1b2c3d4
type: scene
chapter: "[[Chapter 03 - The Gate]]"
status: Draft
pov: "[[Ada Vane]]"
characters: ["[[Ada Vane]]", "[[Corin]]"]
locations: ["[[Ashfall Gate]]"]
story_date: "1187-03-02"
words: 2140
tags: [scene, status/draft]
---
```

- **Body.** Synopsis quote, then prose from `docxio.read_paragraphs_with_format` (each paragraph carries runs with `bold`/`italic` flags, checked in `docxio.py`; italics become `*x*`). The first mention of each known name per scene becomes `[[Ada Vane|Ada]]`; a name shared by two entities stays plain. **This is where wikilinks belong: in the exported copy, never the manuscript.** Obsidian's graph and backlinks then light up with no work from the writer.
- **Entities.** `nf_id, type, role, aliases: [...], tags` plus the sheet fields as `##` sections (from `Entity.cache`). Timeline events get notes with `story_date`, `characters`, `scene`.
- **Names.** `atomic.safe_filename` plus removal of `# | ^ : [ ] %%`; duplicates get ` (2)`; one function `note_path(kind, id)` is shared with the boards.
- **Bases.** `Scenes.base` (table) and `Characters.base` (cards) using the syntax verified from the help example; not opened in Obsidian here (unverified).
- **Re-export.** Idempotent; overwrites only files whose front matter has `nf_id`; never deletes; leaves `.obsidian/` alone; `atomic.write_text_atomic`. Reuses a warm graph's `scene_text`, else reads each scene once (the confirm dialog says roughly how long).
- **Tests.** Every wikilink target exists; no forbidden characters; front matter parses; two exports are byte-identical; a hand-added note survives; scene count equals the manifest; only first mentions linked.

### 4.2 JSON Canvas read/write
`jsoncanvas.py` reads canvases made in Obsidian too (File > Import board...): `text` nodes become text cards; a `file` node resolves by NovelForge id, else by the vault-path table, else stays a plain labelled card. Unknown node types and keys are kept on save (whether Obsidian keeps unknown keys is unverified). "Save a copy as .canvas" and the vault export both write the same file, so a board plotted in NovelForge opens in Obsidian and back.

## 5. What would be WRONG to copy

1. **`[[wikilinks]]` typed in prose.** Prose is the manuscript and compiles to Word; every `[[` would need stripping (Longform ships a compile step just for that), the spelling/grammar/word counts would see brackets, and it hands the writer a chore `storygraph` already does. Detect; generate links only in exports.
2. **Markdown as a second home for prose.** Breaks rule 1. Export stays one-way.
3. **A plugin or scripting system.** Arbitrary code with full file and network access, against "no outbound network", and a support burden. Saved views give the Dataview value.
4. **Sync/Publish.** Accounts and cloud contradict the product; OneDrive-safe atomic saves already exist.
5. **Tabs, splits, stacked notes, workspaces.** A layout rewrite of the ~3,800-line `app.py` hub; Peek + Connections + Go to cover "look at the sheet while writing".
6. **Physics graph with animation.** Per-frame force maths breaks the canvas rule; static rings if a local graph is built.
7. **Custom hotkeys, live query blocks.** The writer's first rule is that it works out of the box.

## 6. Recommended order for 2.3

Go to (S) -> Connections + mention index (M) -> Scene Table + scene tags (M) -> vault export (M) -> Peek (M) -> Plot Board (L; may be 2.4). Each is independently shippable; none changes how prose is stored.

## Sources

Obsidian help: https://obsidian.md/help/links , /plugins/backlinks , /plugins/graph , /plugins/quick-switcher , /plugins/command-palette , /hotkeys , /properties , /bases , /bases/syntax , /plugins/canvas , /tags , /plugins/templates , /plugins/daily-notes , /plugins/outline , /plugins/search , /embeds , /plugins/workspaces , /tabs , /plugins/page-preview , /data-storage , /plugin-security , /file-formats (all under https://obsidian.md/help). Others: https://obsidian.md/changelog , https://obsidian.md/ , https://jsoncanvas.org/spec/1.0/ , https://jsoncanvas.org/ , https://stephango.com/file-over-app , https://blacksmithgu.github.io/obsidian-dataview/ , https://loreteller.com/learn/obsidian-fiction-writers-guide/ , https://dev.to/sakalakis/ive-built-an-obsidian-vault-for-novel-writing-worldbuilding-59am , https://www.xda-developers.com/would-never-try-writing-novel-in-obsidian-without-these-plugins/ , https://www.obsidianstats.com/plugins/longform . Search results only, not fetched: https://community.obsidian.md/plugins/storyline , https://forum.obsidian.md/t/why-am-i-getting-links-will-not-work-with-file-names-containing-any/52558 . Not reachable: /help/plugins/sync (404), so Sync and Publish pricing is unchecked. Local code read: `novelforge/model.py`, `storygraph.py`, `project.py`, `config.py`, `ui/app.py`, `ui/palette.py`, `ui/corkboard.py`, `ui/styling.py`, `README.md`.
