# NovelForge 2.3: plan and status board

Written 2026-09-20 on the local branch `work/2.3`. **Nothing here is published**: no push, no tag, no release. Version numbers stay at 2.2.0 until the owner says to release.

## What was asked

1. Rebuild the map maker into a map *system* for fantasy novels and other kinds of book. First do web research on how map-making for novels works, then make a plan, then build.
2. Consider making NovelForge more like real installed software, but it must never hog RAM or run in the background. Skip it if it is not worth the effort.
3. Revamp the website, and study Obsidian and bring over its useful ideas.
4. Use as many agents as helps; add missing files and system-level tools.

The research is in `docs/research/`: `maps-fantasy.md`, `maps-other-types.md`, `obsidian.md`, `website.md` (each lists its sources and marks what could not be verified).

## Decisions

**Maps.** Fix first what is wrong, then add what novelists need.
- A real bug: the scale bar is drawn `min(0.16 x width, 230)` px long but `mapstory.read_scale` assumes `0.2 x width`, so every distance NovelForge computes is about 64-72% of what the caption says. One shared function will drive both.
- A spoiler leak: hidden layers still appear in the Word export. Add author-only layers and a reader edition.
- Book-ready output: trim presets, 300 dpi, greyscale print style, bleed/safe-area guides, alt text, an on-map legend.
- Curved, classed labels along rivers, ranges and coasts (a new `textpath` primitive in all three backends), and names for rivers, ranges, seas and lakes.
- World features: realms/borders grown from capitals, rain-shadow biomes, rougher hand-drawn coasts, a travel-time calculator over the drawn map, journey lines from scene order with a days-based continuity check.
- New map kinds, each a pure `params -> GameMap` function built from the existing primitives, all deterministic per seed: **dungeon and caves, floor plan, city/town/village (+castle), sector map and star system, treasure map.** A pin can open (or generate) a child map with a derived seed.
- Shared geometry kit `mapkit.py` first; the generators build on it.
- Licence care: Watabou's TownGeneratorOS is GPL-3.0 and NovelForge is MIT. Ideas only, never code.
- Skipped on purpose: Voronoi rewrite of the world generator, label annealing, fog of war, VTT export, 3D, hillshade underlay (risky with Tk zoom).

**Obsidian.** NovelForge already computes Obsidian's backlinks and unlinked mentions in `storygraph.py`; the UI never shows them beside the thing you are viewing. Build, in order: **Go to** (quick switcher, Ctrl+P), **Connections** panel (backlinks, unlinked mentions with a one-click Link, persisted mention index), **Scene Table** (Bases-style filtered, saved views, F3) with scene tags, **Obsidian vault export** (one-way; wikilinks only in the exported copy), **Peek** (hover reference card), **Plot Board** (JSON Canvas `.canvas`; largest, may slip). Not copied: typed `[[wikilinks]]` in prose (the prose becomes the manuscript), plugins, sync/publish, tabs and splits.

**Website.** The audit found: white-on-blue primary button at 2.93:1 contrast, Google Fonts loaded on every page despite "no tracking", every `lastmod` equal to the release date, the home page repeating other pages, and no docs or guides at all (the biggest gap). Plan: light and dark from the OS, docs section (about 24 pages, growing to 40) and guides (12, four first), search over a generated index under 10 KB of JavaScript, a `since` gate so pages about unreleased features cannot go live before the release, real per-page dates, no third-party requests, budgets enforced by tests. `llms.txt` is kept but is not relied on (measured adoption is very low); Search Console and Bing Webmaster Tools are what count. Screenshots of new features are taken only from the merged build.

**"Actual software".** Facts as of today: `Write.bat` already launches through `pythonw.exe` (no console behind the window) and nothing keeps running after the window closes. The packaging work measures memory and startup, adds an installable windowless launcher, a `doctor` self-check, a headless `map` command and a Start Menu shortcut, and honestly evaluates a portable `.exe`. Default recommendation until measured otherwise: keep Python plus `Write.bat`, add the shortcut and the pip launcher; an unsigned exe means SmartScreen and antivirus warnings and a ~50 MB download.

## How the build is run

- Every agent works in its own git worktree under `.claude/worktrees/`, on a branch off `work/2.3`, and commits early and often. The lead merges branches into `work/2.3` and runs the whole suite.
- Anything that opens a window runs through `python C:\nf_ui\gui_lock.py run -- <command>` so only one GUI test runs at a time on the shared screen. (The lock helper lives outside the repo.)
- All agents share one usage quota. Waves are kept small; reports are written to disk as they go.
- New behaviour gets tests, and each new test is proven able to fail. Rules in `CLAUDE.md` apply (speed, theme tokens, windows fit the screen, `.docx` is the truth).

## Status board (updated 2026-09-20 22:15)

Four builds were stopped at about 16:40 by the shared usage limit (the window reset at 20:50). Their work was committed as work-in-progress on their branches and they were resumed at about 22:15. All builds share one usage window (about five hours), so waves are kept small.

| Package | What | State |
|---|---|---|
| R1-R4 | Research: fantasy maps, other map types, Obsidian, website | done |
| O1 | Go to, Connections panel + mention index, scene tags | Go to done; Connections in progress (resumed) |
| MK | mapkit.py geometry kit | module written; tests pending (resumed) |
| MC1 | Book-ready maps: scale fix, units, author-only layers, print export, legend, child-map fields, new-kind registry | scale fix mostly done; rest pending (resumed) |
| WS1 | Website foundation: docs machinery, design, search, tests, small fixes | step 1 done, step 2 in progress (resumed; the site build was broken mid-rename on its branch) |
| MC2 | World features: realms, rain shadow, names, travel and journeys | brief written; waits for MK, MC1 |
| MC3 | Curved labels, coast roughening, cartouche | brief written; waits for MC1 |
| GA/GB/GC | Generators: dungeon + floor plan; city + castle; sector + system + treasure | briefs written; wait for MK, MC1 |
| MU | Map editor: generate dialogs, measure/travel/journey tools, print export, legend, sub-map links | after generators |
| O2 | Scene Table, saved views, vault export | brief written; after O1 |
| O3 | Peek, Plot Board (.canvas) | only if budget allows |
| WS2 | Docs and guides content, screenshots from the merged build | after features |
| PK | Packaging, CLI (doctor, map), shortcuts, exe evaluation | brief written |
| RF | Repo files: .gitattributes, SECURITY, issue forms, CHANGELOG, CITATION | brief written |
| QA | Full suite, screenshots, review, docs, CLAUDE.md | last |
