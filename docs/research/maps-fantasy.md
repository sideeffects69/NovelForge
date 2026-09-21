# Fantasy maps for novels: research for NovelForge 2.3

Research only, no code. Sources are numbered [n] (list at the end); "unverified" marks anything not read on the page itself.

## 1. The real workflow, sketch to finished map

Two camps exist and a tool should serve both. Map first: Tolkien wrote in 1954 that he "wisely started with a map, and made the story fit (generally with meticulous care for distances)", since the reverse gives "confusions and impossibilities" [20]. Story first: a working novelist cycles through generated worlds until the plot's features fit, then writes around that geography [21].

1. Fix the map's job and page size first: reader map or private planning map, trim size, bleed, gutter for a double-page spread [13].
2. Rough the silhouette: continents, seas, the two or three features the plot needs. Painting strokes that become elevation (mapgen4) or cycling through generated seeds (Azgaar) are both accepted [4][21].
3. Build in layers: landmass, mountains, water, forests, settlements, roads, with labels in their own top group [14].
4. Let geography place settlements (river mouths, harbours, junctions) and route the roads [16].
5. Borders, regions, names; a scale so prose distances can be checked [20].
6. Type and furniture: compass, scale, legend, title, border [14].
7. Several sketch revisions before inking, to catch placement problems [13].
8. Proof for the medium (section 4), and cut a reader edition from the private master. Tolkien's published contour map left out the hobbits' dated route, probably to avoid spoilers, and many mapped places never appear in the text [20].

Generators compress steps 2-4 into seconds; brush tools make 2-6 manual but pretty. None of the tools found checks a map against the manuscript.

## 2. What looks right, what looks fake

- Coasts: rough and fractal at every zoom, most intricate where mountains meet the sea; smooth ovals read as fake [16]. Heavier coast lines than river lines, plus ocean hatching or ripples, separate land from water in black and white [13].
- Mountains: chains and rows with foothills, often parallel to coasts and continuing past them as peninsulas and islands [16][17].
- Rivers, the biggest tell [15][16]: they do not split (only deltas branch), do not run coast to coast, start in mountains, lakes or wetlands, merge downstream, cross contours at right angles, and a lake has one outlet. They meander in S-curves [14].
- Biomes: forests and farms near water, swamps in low wet ground, deserts in the rain shadow of ranges, gradual transitions [16][17].
- Settlements at river mouths, harbours, bends and road junctions; roads link centres, follow rivers and coasts, cross ranges at the lowest pass, wind over hills [16].
- Borders: natural ones follow mountains, deserts and empty land; imposed ones may follow rivers or run straight [16]. O'Leary-style generators grow each city's territory by movement cost, then smooth it [3].
- Labels [18][19][14]: point names top-right first, never straight left or right, coastal towns named on the water side; settlement names stay horizontal. Rivers, roads and ranges: text beside the line, curved gently, on the straightest stretch, repeated on long features. Areas (regions, seas): inside the feature, letter-spaced capitals, curved to its long axis. Italic for water, serif for natural and sans-serif for man-made features, size for rank, halo over detail, leader lines when tight.
- Furniture: compass rose, scale marker and legend are expected on a fantasy map [14]; a title, border and ocean texture finish it [13]. A cartouche (a decorated title panel) is a common parchment-map device, but no source read says so (unverified).
- Styles: parchment, ink-on-white and dark atlas are the usual looks; the black-and-white book style must survive with no colour to separate biomes [13].
- The mapgen4 trick: coasts and rivers top-down, mountains and trees in side view, is what feels hand-drawn [4].

## 3. Tool landscape

| Tool | What users value | Steal for a Tkinter + Pillow app |
|---|---|---|
| Azgaar [1][2] | Open source, works offline; generated terrain plus heightmap, river and coastline editors; cultures, states, towns; markers with notes; journeys; scale and distance tools. Built for games, not book art; rejected hexagons and regular grids as implausible and skipped automatic label placement for speed | States, journeys, distance tool: yes. An irregular-mesh rewrite: no |
| Wonderdraft [6][8][9] | Pay once, offline, you own the maps; brushed coasts "automatically beautified"; path tools for rivers, roads, borders; tree and mountain symbol brushes; label presets, reportedly curved along paths [7, low quality]; maps 512-8192 px. Complaint: labels unreadable at other zooms [7] | Coast beautify, path text, presets: yes. Asset packs: no |
| Inkarnate [7][8][9] | Easy, browser-based, big stamp library; complaints: confusing layers, paywalled features, no fog of war, disliked lettering | Ease matters more than art volume; compete on procedural symbols and story links |
| Campaign Cartographer [9][12] | Depth, many styles, add-ons for cities and dungeons; but "dated" UI and steep learning curve | Do not build a CAD |
| Worldographer [10] | Hex maps from world to battle scale, generators, notes on any location, printing; travel tools not listed | Notes on locations: NovelForge has them |
| Watabou [11] | Tiny rule-based city generator; author says it aims to look nice, not be accurate; PNG and JSON export | Later: a town plan |
| mapgen4, O'Leary [4][3] | Paint rough strokes, simulate rain and rivers; territory and label annealing | See section 5 |

Fits Tkinter + Pillow: anything that reduces to vector primitives, small grids and masks. Does not fit: GPU relief, huge art libraries, live 3D.

## 4. How novelists use maps

- Continuity and distance: Tolkien's rule [20]. A map-to-manuscript check is the unmet need.
- Journeys: routes and journeys exist in Azgaar [1] and Wonderdraft's path tool [6]; none ties them to chapters.
- Travel time: none of the tool pages read lists a travel-time calculator (Worldographer's list omits travel tools [10]); writers fall back on rules of thumb such as the game convention of 24 miles a day [26]. Section 6 gives real figures.
- Reader versus private: hide spoilers and unused places; the author's master keeps everything [20].
- Print [22][23]: 300 ppi at printed size; greyscale for black-and-white interiors, text 24 pt or smaller in 100% black; bleed 0.125 in on top, bottom and outside edges only; keep text and non-bleeding art 0.5 in from trim (IngramSpark) [22]. KDP inside margin grows with page count (0.375 in for 24-150 pages, 0.5 in for 151-300, 0.625 in for 301-500), outside at least 0.25 in [23]. IngramSpark wants single pages, no spreads [22], so a two-page map must be built, and kept clear of the fold, by the author [13]. Most novel maps are black and white for cost [13].
- Ebook [24]: images with text (maps) should span at least 80% of screen width; JPEG or PNG, sRGB, transparency becomes white; alt text on every image; captions as real text.

## 5. Techniques for pure Python + Pillow

Costs are my unmeasured estimates for pure Python on this codebase's grids; effort S is under a day, M a few days, L a week or more. Prototype and time before committing.

| Technique | How | Cost | Gain |
|---|---|---|---|
| Text along a path | Smooth the line, find the straightest stretch as long as the text, place each glyph by arc length with the tangent angle, sit it above the line, repeat on long lines. Tk canvas text takes an `angle` option [31], one item per glyph; Pillow: draw glyph, rotate, paste; SVG `textPath` | Code M; about 1 ms per label | Very high |
| Cost-based realms | Multi-source Dijkstra from capitals over the half-res grid (about 11k cells); crossing rivers, ridges, sea costs a lot; trace each realm mask with existing `_contours`, smooth, draw dashed [3] | Code M; 50-100 ms | High |
| Travel A* on a rasterised map | Fill land, forest, hills, mountains, water polygons into a 128x86 grid with Pillow; roads cheap, rivers directional; reuse `_astar`; works for hand-drawn maps | Code M; 10-30 ms a query | High, unique |
| Rain-shadow moisture | Sweep the height grid along a wind direction; moisture drops on uphill steps; feed biome ranking [16][17] | Code S; about 50 ms | Medium-high |
| Coast roughening | Render-time midpoint displacement seeded by shape id; amplitude by segment length | Code S; 5 ms a coast | Medium-high |
| Hillshade underlay | Slope times light on the stored height grid, multiply over land; needs a raster primitive in three backends; `canvas.scale` moves but never resizes images [31], so zoom needs a redraw | Code M-L; 50-100 ms (estimate) | High but risky; generated maps only |
| Blue-noise scatter | Bridson Poisson-disc for trees and peaks, as [5] advises for object placement | Code S | Medium |
| Print export | `convert("L")`, `save(dpi=(300, 300))`, resize to trim width at 300 dpi, draw bleed and safe-area guides | Code S; 100 ms | High for authors |
| Label annealing | O'Leary's optimiser [3]; Azgaar rejected it for speed [2] | Seconds | Skip; keep greedy, add the OS candidate order [18] |

## 6. Travel-time facts

| Case | Figure | Source |
|---|---|---|
| Infantry, road, normal | 8-12 miles/day; 15-20 for small units in good conditions | [25] |
| Forced march | about 35 miles/day, unsustainable | [25] |
| Off road | "significantly slower"; wagons worst; big armies single digits | [25] |
| Small mounted group with remounts | up to 60 miles/day | [25] |
| Game convention, 8 h/day | slow 18, normal 24, fast 30 miles; difficult terrain halves it; gallop about 8 mph for an hour | [26] |
| Courier relay | 38-62 miles/day normal, 100+ emergency; stations 25 Roman miles apart | [27] |
| Roman ship | 4-5 knots, 6 at best; winter sailing closed; wind direction decides | [28] |
| River keelboat | up to 6 mph; upstream returns took months; 5-15 miles/day upstream is a search summary | [29] |
| Ox wagon | about 15 miles/day (search summary only) | [U2] |

A large force moves at its baggage's speed (about 20 wagons per 1,000 men) [25]. ORBIS models road, river, coastal and open sea, by transport type and season [30]; its constants were not readable. Proposed calculator: pick party type, pin A and B, cheapest path on a cost grid (base speed over a terrain multiplier: road 1.0, open 0.7, forest, hills, swamp lower, mountains about 0.4), rivers fast downstream and slow up, seas by wind season; answer "about 9 days on foot", route drawn. Multipliers are opinions [26][25]: make them editable.

## 7. What NovelForge has, and the gaps

Has (CLAUDE.md, code): seeded generator with continents, relief, marching-squares coasts, drainage, rivers, biomes, settlements, A* roads and names; hand tools; 13 terrain kinds, 20 pin kinds, 8 map kinds, 4 styles, layers, grid; pins linked to Location sheets; compass, scale bar, title, border, halo text, letter spacing; PNG, SVG and Word export; and, not seen in any other tool read, `mapstory.py`: pins in the story graph, straight-line distance, "where is everyone at chapter N", and continuity checks.

Findings from reading the code (not run):
- Bug: `_scale_primitives` draws the bar min(0.16 x width, 230) px long, but `read_scale` in `mapstory.py` assumes 0.2 x width. On a 1800 px map every distance is computed as about 64% of what the caption means (72% at 1600). Fix first.
- The travel check ignores roads, terrain and mode (a flat 300-mile threshold).
- The generator names only the two largest landmasses and the ocean; no river, range, lake or sea is named, and labels have no angle. A shape's label is drawn at the mean of its vertices, which can lie off a winding river.
- The PNG export dialog fixes scale 1.0 and has no dpi, greyscale or trim option (the API allows 0.2-4x). A generated 1800 px map is exactly 6 in at 300 ppi; the 1600 px default is 5.3 in.
- Hiding a layer drops its shapes, pins and labels from PNG and SVG, so a reader edition is nearly free. But `render_docx` lists every pin with its notes, and every named shape, whatever the layer: a spoiler leak. There is no author-only flag.

| # | Feature | Why authors want it | Effort | Risk | Verdict |
|---|---|---|---|---|---|
| 1 | Numeric scale, round scale bar, measure tool; fix the 0.16/0.2 bug | Trustworthy distances | S | Low | Build now |
| 2 | Curved, classed labels; name rivers, ranges, seas, lakes | Biggest "looks professional" gap [18][19] | M | Med: new primitive in three backends | Build now |
| 3 | Travel-time calculator | "How long did Ada take?" | M | Med: multipliers are opinions | Build now |
| 4 | Journey lines from scenes; days-based continuity check | Nothing read does it; catches impossible trips | S-M | Low | Build now (after 1, 3) |
| 5 | Print and ebook export: trim presets, 300 dpi, greyscale style, safe area and gutter, author-only layers (also fixing the Word legend leak), alt text | A book needs it [22][23][24] | S-M | Low | Build now |
| 6 | Realms and borders from capitals | Epic-fantasy staple; stated gap | M | Med: tracing, tuning | Build now |
| 7 | Coast roughening for hand-drawn coasts | Hand-drawn maps look smooth | S | Low-med: seeding | Build now |
| 8 | Rain-shadow biomes | Deserts behind ranges | S-M | Low; regenerating an old seed changes the world | Build now, note in changelog |
| 9 | Click-to-stamp trees, peaks, castles | Loved in Wonderdraft [6] | S-M | Low | Later |
| 10 | Pin opens a sub-map (world, region, city) | Nested worlds | S | Low | Later |
| 10b | On-map legend and cartouche title panel | Expected furniture [14] | S-M | Low | Later |
| 11 | Hillshade underlay | Painted relief | M-L | High: Tk zoom, edited maps | Later |
| 12 | Town plan generator | City-set novels | L | High | Later |
| 13 | Voronoi mesh rewrite, label annealing, hex-crawl, fog of war, VTT export, 3D | Game-master features | L | High | Skip |

Suggested order for 2.3: row 1 first (it corrects numbers already shown), then 5 (independent, low risk, serves the publishing goal), then 2, then 3 and 4 together, then the generator work in 6, 7 and 8. Rows 6 and 8 change what a seed generates from now on; saved maps are unaffected because they store their shapes, so only re-generating from an old seed would differ.

## Sources

Read on the page: [1] https://github.com/Azgaar/Fantasy-Map-Generator/wiki. [2] https://azgaar.wordpress.com/2017/03/30/first-post/. [3] https://github.com/rlguy/FantasyMapGenerator/blob/master/README.md (an implementation of O'Leary's notes). [4] https://www.redblobgames.com/maps/mapgen4/. [5] https://www.redblobgames.com/maps/terrain-from-noise/. [6] http://wonderdraft.net/. [8] https://www.dndbeyond.com/forums/dungeons-dragons-discussion/dungeon-masters-only/128462-world-mapping-wonderdraft-vs-inkarnate (forum users). [9] https://blog.worldanvil.com/2020/03/12/map-making-software-for-worldbuilding/ (2020). [10] https://worldographer.com/. [11] https://watabou.itch.io/medieval-fantasy-city-generator. [12] https://en.wikipedia.org/wiki/Campaign_Cartographer. [13] https://novelpad.co/blog/how-to-create-a-fantasy-map. [14] https://designingmaps.com/2018/06/designing-fantasy-outdoors-maps/. [15] https://www.mapeffects.co/tutorials/river-sins. [16] https://mythcreants.com/blog/crafting-plausible-maps/. [17] https://worldographer.com/2022/11/fantasy-map-making-geography-101/. [18] https://docs.os.uk/more-than-maps/geographic-data-visualisation/guide-to-cartography/text-on-maps. [19] https://en.wikipedia.org/wiki/Typography_(cartography). [20] https://en.wikipedia.org/wiki/Tolkien%27s_maps. [21] https://brynnorel.substack.com/p/but-what-about-the-map. [22] https://www.ingramspark.com/blog/file-requirements-for-print-books. [23] https://kdp.amazon.com/en_US/help/topic/GVBQ3CMEQW3W2VL6. [24] https://kdp.amazon.com/en_US/help/topic/G75V4YX5X8GRGXWV. [25] https://acoup.blog/2019/10/06/new-acquisitions-how-fast-do-armies-move/. [26] https://5thsrd.org/adventuring/movement/ (game convention). [27] https://en.wikipedia.org/wiki/Cursus_publicus. [28] https://www.worldhistory.org/article/1028/roman-shipbuilding--navigation/. [29] https://www.encyclopedia.com/history/news-wires-white-papers-and-books/flatboats-and-keelboats (maximum speed and "months" only). [30] https://orbis.stanford.edu/ (interface only). [31] https://www.tcl-lang.org/man/tcl8.6/TkCmd/canvas.htm.

Low quality: [7] https://loreteller.com/learn/inkarnate-vs-wonderdraft/ (aggregator; it wrongly says Wonderdraft has no procedural generation, which [6] contradicts).

Unverified: [U1] Martin O'Leary, https://mewo2.com/notes/terrain/ (404 on 2026-09-20; known through [3] and search summaries). [U2] Ox-wagon pace and the river ranges, from search summaries of OCTA and Wikipedia pages (fetch returned 403). Imhof's "Positioning Names on Maps" (1975) is known only through [19] and search summaries. Tk 8.6 and Pillow 12.3 were confirmed by running `python -c` (no window opened).
