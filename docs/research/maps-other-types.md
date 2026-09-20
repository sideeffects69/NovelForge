# Maps beyond the world map: research for NovelForge 2.3

Date: 2026-09-20. Research only, no code changed. Sources are numbered [S1] to [S25] at the end, preceded by what I could not verify.

**Bottom line.** Build a shared geometry kit, then, in order: journey overlay, dungeon and caves, floor plan, city (with castle), sector map, treasure map. Each is a pure function `params -> GameMap` made only of the existing primitives (polygon, line, ellipse, text), so canvas, PNG and SVG stay identical.

**Conventions for every generator.** One `Random` per stage, seeded `crc32(f"{seed}:{stage}")` (never `hash()`), so adding a stage never reshuffles earlier ones; under 2 s; new `Shape.kind` values need entries in `TERRAIN` and `PAINT_ORDER`; each invariant below becomes a unit test over about 200 seeds.

## 1. City, town and village

**Who and needs.** Fantasy, historical and mystery fiction: the walled capital, the port, the starting village. Readers need the wall and gates, river or harbour, market square and a few named landmarks; authors need consistency ("the inn is two streets from the gate") more than realism. Watabou's stated goal is "a nice looking map, not an accurate model of a city" [S3]. **Style:** top-down, solid dark building blocks on pale ground, streets as negative space, thick wall with round towers, tinted wards, few labels.

**Algorithm: ward city (TownGeneratorOS idea, re-implemented).** Its skeleton is a spiral of Voronoi patches relaxed with Lloyd's method, patch classes (centre, citadel, inner, outer), a wall with gates, a graph that routes streets from gates to the centre, nine ward types chosen by a location score, then per-ward building geometry [S2].

```python
n = {"village": 8, "town": 18, "city": 32}[size]
pts = sunflower(n)                       # golden-angle spiral
for _ in range(3): pts = lloyd(pts)
cells = clip_voronoi(pts, bbox)          # half-plane clipping, O(n^2), ~30 ms
inner = nearest_cells(centre, k)         # centre cell = plaza
wall = edges_between(inner, outer)
gates = wall_vertices_at(angles, 3..5)
streets = union(dijkstra(g, plaza) for g in gates)
for c in inner: c.ward = pick(WARDS, score(c))
for c in cells:
    poly = inset(c.poly, street_w)
    for lot in bisect(poly, min_area):   # split longest side, jitter, recurse
        if rng() < c.ward.fill: buildings.append(inset(lot, alley_w))
```

Known weaknesses: the author admitted "too many triangular buildings" [S3] and the open-source version lacks water bodies [S1]. Fixes: a minimum-angle rule when bisecting; carve the river as a polygon before the Voronoi and drop cells whose centroid is wet.

**Invariants.** Every building lies inside its ward minus the street inset and overlaps no other; every gate reaches the plaza over the street graph; the wall is one closed ring; same seed, identical primitive list.

**Primitives.** Buildings and wards `polygon`; streets `line` (existing `road`); wall (existing `wall`) plus `ellipse` towers; river (existing `river`); names `text` with halo. New kinds `building`, `ward`, `plaza`, `street`. Landmarks become `Pin`s linkable to Location sheets.

**Verdict.** Highest value: the biggest hole (the blank city grid). Effort L (~600 lines). A village is the same code with n=8, no wall and a green: nearly free.

## 2. Building and floor plan

**Who and needs.** Mystery above all: Christie printed house plans in *Styles*, *Roger Ackroyd* (house plus murder-room detail) and *Vicarage*, and readers return to them to locate characters [S12]. Also inns, manors, towers, flats, ship decks. Must-haves: room names, doors, windows, stairs up/down, scale, north arrow, one mark for "where it happened". **Style:** architectural plan; solid wall fill, doors as gaps with swing arcs, thin window lines, stair treads, tinted floors.

**Algorithm: squarified treemap plus door graph.** Marson and Musse subdivide the outline into rooms of prescribed area, then connect rooms and place doors from a connection graph [S11].

```python
rooms = TEMPLATE[kind]                  # (name, target_area, zone)
bands = split(footprint, by_zone)       # public band touches entrance
for band in bands:
    cells += squarify(rooms_in(band), band)
adj = shared_walls(cells, min_len=door_w + 2*margin)
tree = spanning_tree(adj, root=hall, prefer=REQUIRED)
extra = sample(adj - tree, 0.15)        # loops
doors = [door_on(wall, rng) for wall in tree + extra]
windows = exterior_every(habitable, 2.0) - near(doors)
stairs = rect_in(hall)                  # identical rect on the next floor
```

The seed key includes the floor number, so floor 1 never changes when floor 2 is regenerated.

**Invariants.** Room areas sum to the footprint; no overlap; every room reachable from the entrance by BFS over doors; each door lies wholly on a shared wall; every habitable room has a window; stair rectangles match between floors.

**Primitives.** `polygon` walls and floors; `line` doors (gap plus arc polyline), windows, treads; `text` names. New kinds `room`, `partition`, `door`, `window`, `stairs`. Each floor is its own `GameMap`, linked to its siblings (section 10).

**Verdict.** High value for an audience nobody else serves; Effort M (~350 lines); all-rectangle geometry makes the invariants easy.

## 3. Dungeon and caves

**Who and needs.** Fantasy adventure, LitRPG, horror (catacombs, sewers), thrillers (bunker). Readers need rooms told apart (numbers), doors and secret doors, stairs, water. **Style:** old-school black wall lines, hatching outside walls, square grid (general knowledge, unverified).

**Algorithm: BSP rooms, spanning-tree corridors, loops.** BSP gives connectivity by construction [S10]; Rooms and Mazes gets it by opening one connector per region pair through a spanning tree [S8]. Watabou's One Page Dungeon adds "local symmetry": a root room with symmetrical children, then loops [S4]; mirroring some rooms gives the same designed look.

```python
leaves = bsp(rect(0, 0, W, H), min_leaf=10)       # 64 x 48 squares
rooms = [carve(l, margin=2) for l in leaves if rng() > .08]
mirror_some(rooms, axis_of(parent))               # local symmetry
edges = prim_mst(rooms, centre_dist) + loops(.15)
for a, b in edges:
    carve_L_corridor(a, b, width=1)
mark_doors(open | door | locked | secret(.05))
entrance, exit = furthest_pair(rooms, bfs)
place_stairs(entrance, exit)
assert one_component(open_cells)
outline = trace(open_cells)                       # rectilinear polygons
```

**Caves.** Cellular automaton: about 40% walls at the start, a cell becomes wall if 5 or more of its 8 neighbours are walls (the article adds a wider-neighbourhood test in early passes), 4 to 7 passes, then flood-fill and wall off everything unreached [S9]. Outline with the world generator's existing marching squares (`mapgen._contours`) so caves curve.

**Invariants.** One connected open component; rooms never overlap; corridors meet rooms only at doors; stairs in different rooms; cave open share 35-55% (else retry `seed+1`, deterministic).

**Primitives.** Floor `polygon`; walls as thick `line`; hatching as short cached `line` strokes; existing `square` grid; doors as small `polygon`s; stairs as parallel `line`s; room numbers `text` plus a key. New kinds `floor`, `cave`, `door`, `stairs`.

**Verdict.** High value; Effort M (~300 lines, +100 for caves). Best return per line.

## 4. Castle and fortress

**Who and needs.** Fantasy and historical fiction, one or two per book, where the siege, escape or throne room happens. Readers need approach, gate, walls, towers, keep, courtyards, moat. A concentric castle has two curtain-wall rings, the inner higher; a motte-and-bailey is a mound with a tower plus an enclosed courtyard [S13]. **Style:** plan view, thick walls, towers on the wall, small building blocks, blue moat, road to the gate.

**Algorithm: template rings plus lots** (my design; vocabulary from [S13]).

```python
outer = noisy_polygon(cx, cy, R, rough)
inner = inset(outer, gap) if concentric else None
for ring in (outer, inner):
    towers += corners(ring, turn > 25) + every(ring, L)
gate_out = edge_facing(approach)
gate_in = edge_at(approach + uniform(60, 180))   # staggered gates
keep = block(far side of inner from gate_out)
lots = bisect(bailey - keep - road, min_area)    # hall, stable, smithy, chapel
moat = offset(outer, +m)
road = polyline(map_edge, gate_out)
```

**Invariants.** A gate on every ring; concentric gates at least 60 degrees apart; every tower on a wall; keep inside the innermost ring; no lot crosses a wall or the keep; the road ends at a gate.

**Primitives.** Existing `wall` plus `ellipse` towers, `polygon` blocks, `water` polygon moat, `road` line. Reuses the city's inset/bisect helpers; the moat can use the existing `_offset_ring`.

**Verdict.** Medium value; Effort S after the city (~150 lines).

## 5. Star or sector map and system diagram

**Who and needs.** Science fiction and space opera. Readers need which stars are linked, distances, who owns what, where the plot's systems sit. Traveller's convention is the model: a subsector of 8x10 hexes, 50% chance of a system per hex, four-line world labels, trade routes between worlds within four parsecs, borders as metadata [S14]. **Style:** dark ground, star dots, thin lanes, faction tints, hex grid; the existing `dark` style and `hex` grid fit.

**Algorithm, sector.**

```python
sites = [h for h in hexes if rng() < density]
edges = mst(sites, dist)                          # connected
edges += [(a, b) for a, b in pairs(sites)
          if dist(a, b) <= JUMP and gabriel(a, b, sites)]
seeds = farthest_points(sites, k)
owner = multi_source_dijkstra(edges, seeds)       # border where owner changes
for s in sites: s.name = name_for(...); s.tags = roll(population, port)
```

**System diagram** (schematic, not to scale). Orbits grow by a random ratio; the worldbuilding rule of thumb is a period ratio of 1.5 to 3 between neighbours, i.e. 1.3 to 2.1 in radius [S15]. Draw on a log radius; gas giants beyond the frost line; a belt where an orbit is skipped.

**Invariants.** Lane graph is one component; no two systems in a hex; no lane passes through a third star; every system has one owner; orbit radii strictly increase.

**Primitives.** `ellipse` stars and planets; `line` lanes and orbit rings (dashed belts); `polygon` faction hexes; `text` with halo. New pin kinds `star`, `planet`, `station`, `gate`.

**Verdict.** A whole genre unserved; Effort M (~300 lines, no Voronoi). High novelty, low risk.

## 6. Journey or route map

**Who and needs.** Quest fantasy, road-trip fiction, voyages, marches. Readers follow the party and feel distance; authors need continuity ("how long did they walk?"). Reference: Strachey's *Journeys of Frodo*, 51 two-colour maps with roads in dashed black and red, off-road in red, direction arrows, dates in red, edge coordinates, a scale bar in miles per inch, even moon phases [S17].

**Algorithm: an overlay, not a new map.** Least-cost path over an existing map, with the A* the generator already uses for roads.

```python
def add_journey(gm, stops, mode="foot"):
    cost = terrain_cost(gm, mode)          # rasterised with Pillow
    path = []
    for a, b in pairs(stops):
        path += astar(cost, a, b)
    line = catmull_rom(simplify(path, 2))
    for leg in split_at(line, stops):
        leg.miles = length(leg) * units_per_px
        leg.days = leg.miles / PACE[mode]
    emit route Shape, arrows every ~120 px, "Day N" markers
```

Pace rules of thumb (foot about 20 miles a day, horse 30, wagon 15) are mine, unverified; make them editable.

**Invariants.** Path starts and ends at the stops; no impassable cell is crossed except at a bridge, ford or port; total length is the sum of legs; day numbers strictly increase; no randomness.

**Primitives.** Existing `route` kind (dashed `line`, `PAINT_ORDER` 12); arrowhead `polygon`s; `ellipse` plus `text` markers; a legend table ("Day 1-3, Bree to Weathertop, 60 miles").

**Verdict.** Very high value per effort; S (~120 lines) because A* and `route` exist. The travel table feeds the story bible and can be checked against the Timeline.

## 7. Treasure map

**Who and needs.** Adventure, pirate, YA, mystery; the map is a *plot object* characters read, so it must be partial, in-world and full of clues. *Treasure Island* began as a map Lloyd Osbourne drew and Stevenson elaborated and named; the original was lost in the post and redrawn, and the book popularised the tropes [S16]. **Style:** aged parchment, sepia ink, beach, hills, one landmark per clue, dashed trail, red X, compass rose, tiny ship; `STYLES["treasure"]` already exists.

**Algorithm: island plus clue trail** (composition of existing pieces).

```python
island = mapgen.generate(small_island(seed))
landing = deepest_bay(island)
marks = pick_features(island, 4)           # twin peaks, river mouth, lone tree
X = inland_point(min_shore=0.25, far_from=landing)
trail = simplify(astar(land_cost, landing, X), n=len(marks) + 1)
for m, a, b in zip(marks, trail, trail[1:]):
    clue = f"From the {m.name}, {bearing_word(a, b)}, {paces(a, b)} paces"
add_decor(ship, sea_monster, compass)
```

**Invariants.** X on land, away from the shore; trail entirely on land; every clue's bearing and pace count leads from its landmark to the next waypoint; same seed, same island and clue text.

**Primitives.** All exist (land, hills, forest, route). Additions: red X (two thick `line`s; needs an accent colour token because hard-coded colours are forbidden), torn-edge `polygon`, stains as blended `ellipse`s (Tk has no alpha; mix colours as `_mix` does).

**Verdict.** Medium value, the most shareable; Effort S (~150 lines) once the island generator can run small.

## 8. Battle map

**Who and needs.** Two needs. (a) *Battle diagram* in historical and military fiction: Cornwell's Sharpe novels carry battle plans and illustrated endpapers [S20]. Must-haves: ridge, stream, farms, woods; two colours for two sides; unit blocks; movement arrows; phases. Modern symbology uses a blue rectangle for friendly and a red diamond for hostile units [S19]; period fiction can simplify. (b) *Tactical grid map* for a fight scene: 5-foot squares, typically 20x20 to 40x30 [S18].

**Algorithm: terrain generated, forces hand-placed.**

```python
def battlefield(seed, w=1600, h=1100):
    height = ridge_noise + lobes(seed)
    hills = contours(height, every=H)         # marching squares
    stream = astar(height, high_edge, low_edge)
    village = flat_cell_near(stream)
    woods = mask(noise > t, avoid=village)
    zones = {"A": left_third, "B": right_third}
# one Layer per phase ("Morning", "Noon"); toggling layers steps through the battle
```

`GameMap` already has layers, so a phase is a layer holding unit rectangles and arrows.

**Invariants.** Deployment zones disjoint and each connected to the road or open ground; every unit on a passable cell; each arrow starts where the unit stood in the previous phase; the legend lists every unit kind used.

**Primitives.** Rotated `polygon` unit blocks with `text` codes; `line` plus head `polygon` arrows; existing hills, forest, river; existing `square` grid at 5 ft for tactical maps.

**Verdict.** Medium value; Effort M, mostly UI (unit and arrow tools). Terrain preset early (S), unit tools later.

## 9. Historical and contemporary schematics (neighbourhood, campus, political, transit)

**Who and needs.** Literary and crime fiction rarely carry maps, but children's and detective books do (Hundred Acre Wood, Swallows and Amazons) [S25]; historical fiction wants borders and campaign routes. Readers need a few named places and the distances between them.

**Neighbourhood, campus, estate.** Watabou's Neighbourhood Generator makes streets, buildings and squares from tags such as "leafy" or "square" and hands buildings to its mansion generator for interiors [S23]. Recommended: the city engine with a *warped-grid* street mode (jittered grid, one boulevard, optional river) feeding the same lot bisector; invariants as for the city. Tensor-field streets (basis fields blended, major and minor tensor lines traced at a separation distance [S6]) and Parish and Müller's L-system growth [S7] look better but need robust intersection clean-up: defer. Effort S once the city exists.

**Political / historical map.** Azgaar picks capitals at the best-scoring sites with a minimum spacing, then grows states by cost-based flood fill over elevation, rivers and roads [S5][S22]. Here: multi-source Dijkstra over the existing land grid from the capitals, owner mask contoured by `_contours` into `region` shapes; time slices are layers. Invariants: at most one owner per cell; each state connected and containing its capital; borders are closed rings. It closes the "no political borders" gap. Effort S-M.

**Transit or schematic.** Beck-style diagrams use only horizontal, vertical and 45-degree segments; automatic layout is a mixed-integer program [S24], too heavy. Offer a hand tool: stations snap to a grid, each link gets one 45-degree bend. Niche; Effort S; last.

## 10. Cross-cutting: linking, scale, grid, legends, print

**Linking (world pin, region, city, building).** Azgaar's city link passes a seed, a size and coast/port/river flags to the city generator (seen in a URL only, unverified) [S5]; Watabou's neighbourhood feeds its mansion generator [S23]. Do it deterministically: new `Pin.child_map_id` and `GameMap.parent = {map_id, pin_id}`; child seed `crc32(f"{parent.seed}:{pin.id}")`; child name = pin label; size class from pin kind (village, town, city, capital); coast/port/river flags read from the parent's geometry near the pin; culture inherited for names; `entity_id` copied so it is the same Location sheet. Show a breadcrumb ("World > Harrowgate > The Gilded Stag, ground floor"). Moving a pin never changes the child; changing its kind offers to regenerate.

**Scale and grid.** `mapstory.read_scale` parses `scale_text`, but `_UNITS` has no feet, yards, paces, metres, parsecs or AU: add them so distances and the chapter continuity check work on every kind. One helper, `apply_scale(gm, unit, per_cell)`, sets `scale_text` and `grid_size` together so they cannot disagree, rounding the bar to 1/2/5 steps. Defaults: dungeon, building and tactical battle 5 ft squares [S18]; sector hex, 1 parsec [S14]; city no grid, 100 ft bar; region miles; journey days per bar (my conventions, unverified).

**Legends.** Generate the legend from the kinds actually present (swatch plus name) as `polygon` and `text` primitives, so all three backends agree; plus per-kind keys (numbered rooms from pin notes, faction colours, unit symbols, journey table).

**Print.** Add a greyscale "Print" style: black ink on white, hatch and pattern fills instead of colour, no line thinner than about 0.5 pt at trim size, and a test that converts adjacent fills to luminance and asserts a minimum gap (the styling tests already do colour maths). Export presets: full page, double-page spread (names away from the fold), small inline figure; 300 dpi is standard practice (unverified). Maps sit in the front matter or as a frontispiece; endpaper maps can be dropped in paperback, library and e-book editions, so repeat essential ones inside [S21]; Christie's plans were missing from some editions and e-books [S12].

## 11. Recommended build order

Step 0 (S-M, prerequisite): `novelforge/mapkit.py` with polygon inset/offset/bisect, point-in-polygon, Voronoi by clipping, MST, grid-to-polygon tracing, `apply_scale`, legend builder, child-map linking.

| # | Kind | Effort | API | Main risk |
|---|------|--------|-----|-----------|
| 1 | Journey overlay | S | `add_journey(gm, stops: Sequence[str], mode="foot", name="Journey") -> GameMap` (adds a layer, returns `gm`) | pace defaults are guesses; make them editable |
| 2 | Dungeon and caves | M | `generate_dungeon(p: DungeonParams) -> GameMap` (`mode="rooms"` or `"cave"`, size, rooms, loops, symmetry, seed) | tracing rectilinear outlines; door rules |
| 3 | Floor plan | M | `generate_floorplan(p: FloorplanParams) -> GameMap` (`template`, `floor`, `footprint`, seed) | templates must feel right; stair alignment |
| 4 | City, town, village (+ castle, S) | L | `generate_city(p: CityParams) -> GameMap` (`size`, `walls`, `river`, `coast`, `port`, `culture`, seed); `generate_castle(p) -> GameMap` | slivers and triangles [S3]; rivers |
| 5 | Sector map and system | M | `generate_sector(p: SectorParams) -> GameMap`; `generate_system(p: SystemParams) -> GameMap` | new pin kinds and icons; scale units |
| 6 | Treasure map | S | `generate_treasure(p: TreasureParams) -> GameMap` (island, trail, clue text) | accent colour token; no alpha on Tk |

Deferred: battle terrain preset (S) and unit/arrow tools (M); political borders (S-M); neighbourhood grid mode (S after 4); transit tool (S, niche).

**Risks common to all.** (1) Geometry: pure-Python inset and bisect give slivers and self-intersections; run property tests over about 200 seeds per generator. (2) Speed: budget 2 s and cache per shape in `_shape_cache`; a city is roughly 1,000 polygons on a Tk canvas, so time a redraw and a pan. (3) Licence: TownGeneratorOS is GPL-3.0 [S1] and NovelForge is MIT, so re-implement from ideas, never port code; Watabou allows free use of *maps* its tools produce [S23], which says nothing about code. (4) Looks are not unit-testable: photograph each with `tools/uishots`, as was done for the map maker. (5) Each kind adds tool-rail entries and walk tests to a suite that already takes about five minutes. (6) Saved maps: new optional fields load safely (`from_dict` ignores unknown keys and missing ones take defaults).

## Unverified or weakly sourced

Pace figures, grid defaults, 300 dpi and the old-school dungeon look are my own knowledge. The MDPI Christie article returned 403 and the Waterloo paper was blocked, so those are search summaries; the castle, Traveller, orbit-ratio and Treasure Island points also come from search summaries, not full pages. The Azgaar link parameters were seen in a URL only.

## Sources

- S1 https://github.com/watabou/TownGeneratorOS (GPL-3.0, OpenFL/Haxe)
- S2 https://deepwiki.com/watabou/TownGeneratorOS/4.1-generation-process
- S3 https://watabou.itch.io/medieval-fantasy-city-generator/devlog/1579/some-answers-and-comments
- S4 https://itch.io/post/11093690 and https://watabou.itch.io/one-page-dungeon
- S5 https://azgaar.github.io/Fantasy-Map-Generator/ and https://deepwiki.com/Azgaar/Fantasy-Map-Generator
- S6 https://www.sci.utah.edu/~chengu/street_sig08/street_project.htm (Chen et al., SIGGRAPH 2008)
- S7 https://history.siggraph.org/learning/procedural-modeling-of-cities-by-parish-and-muller/
- S8 https://journal.stuffwithstuff.com/2014/12/21/rooms-and-mazes/
- S9 https://www.roguebasin.com/index.php/Cellular_Automata_Method_for_Generating_Random_Cave-Like_Levels
- S10 https://www.roguebasin.com/index.php/Basic_BSP_Dungeon_generation
- S11 https://www.researchgate.net/publication/47696530_Automatic_Real-Time_Generation_of_Floor_Plans_Based_on_Squarified_Treemaps_Algorithm
- S12 https://www.mdpi.com/2076-0787/8/1/23 and https://community-archive.agathachristie.com/discussion/1302/maps-floor-plan-in-agatha-cristies-novels
- S13 https://www.castlesworld.com/tools/concentric-castles.php and https://en.wikipedia.org/wiki/Bailey_(castle)
- S14 https://www.traveller-srd.com/core-rules/world-creation/ and https://wiki.travellerrpg.com/Trade_map_key
- S15 https://worldbuildingpasta.blogspot.com/2019/09/an-apple-pie-from-scratch-part-iva.html
- S16 https://robert-louis-stevenson.org/treasure-island-map/ and https://bigthink.com/strange-maps/378-x-m-aarrrh-ks-the-spot/
- S17 https://en.wikipedia.org/wiki/Journeys_of_Frodo
- S18 https://www.rpgmapeditor.com/guides/dnd-battle-map-size-guide
- S19 https://en.wikipedia.org/wiki/NATO_Joint_Military_Symbology
- S20 https://www.bernardcornwell.net/about-the-sharpe-books/
- S21 https://en.wikipedia.org/wiki/Endpaper and https://www.thebookdesigner.com/front-matter-book/
- S22 https://azgaar.wordpress.com/2017/11/21/settlements/
- S23 https://watabou.itch.io/neighbourhood
- S24 https://arxiv.org/abs/1904.03039 (extends Nöllenburg and Wolff's metro-map program)
- S25 https://www.atlasobscura.com/articles/writers-maps and https://en.wikipedia.org/wiki/Hundred_Acre_Wood
