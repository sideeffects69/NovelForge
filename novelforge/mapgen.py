"""
Procedural map generation - build a world from parameters.

The pipeline, in order:

  1. **Landmass.** Each continent is a cluster of overlapping lobes, bent by a
     warp field so coasts wander instead of forming ovals, roughened with
     fractal noise, and pushed under water at the map edge. Islands are added
     around them, then a percentile picks the sea level - so "30% land" really
     gives 30% land on every seed.
  2. **Relief.** Every land cell gets an altitude: a broad rise inland, plus
     ridged noise so mountains form *chains* along crests rather than lumps.
  3. **Coastlines.** Marching squares on the height field, which gives smooth
     outlines that are exact to a fraction of a cell. The holes in a landmass
     become inland seas. The result is the same Shape objects the hand-drawing
     tools make, so generated and drawn maps are identical afterwards.
  4. **Drainage.** A priority flood fills every basin so that *every* land
     cell drains to the sea; the deep basins become lakes. Rivers are then
     traced *upstream* from their mouths along the biggest catchment, so each
     one starts in the hills and ends at the sea, with tributaries.
  5. **Biomes.** Temperature from latitude and altitude, moisture from noise
     and distance to water. The masks are blurred before they are outlined, so
     forests and deserts are soft irregular patches rather than pixel blobs.
  6. **Settlements.** Every land cell is scored for habitability - a harbour,
     fresh water, gentle ground - and the best sites are taken with a minimum
     spacing so cities are not all in one corner.
  7. **Roads.** A minimum spanning tree over the settlements, each edge routed
     by A* across the land (never through the sea, avoiding steep ground, and
     reusing roads that already exist so trunk roads form).
  8. **Names.** Regions are labelled where the land is deepest, and the ocean
     where the water is.

Everything is seeded, so the same parameters always rebuild the same world -
names included. Pure Python and the standard library; no numpy.
"""

from __future__ import annotations

import heapq
import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .mapmaker import (
    GameMap,
    Layer,
    MapLabel,
    Pin,
    Shape,
    _smooth,
    generate_name,
    name_for,
)

Point = Tuple[float, float]
Grid = List[List[float]]

# Working grid resolution. 256x171 is ~44,000 cells: fine enough for a
# convincing coastline, coarse enough to stay near a second in pure Python.
# Detail comes from the smooth contours, not from cell count. Roads and biomes
# work on a grid half as wide and half as tall, which is plenty for them.
GRID_W = 256
GRID_H = 171
HALF_W = (GRID_W + 1) // 2
HALF_H = (GRID_H + 1) // 2


# ==========================================================================
# Parameters
# ==========================================================================

CLIMATES = {
    "temperate": "Temperate - mixed forest, four seasons",
    "tropical": "Tropical - jungle and swamp, hot and wet",
    "arid": "Arid - desert and dry scrub",
    "arctic": "Arctic - ice, tundra, short summers",
    "varied": "Varied - everything from ice caps to desert",
}

LANDMASS_SHAPES = {
    "continents": "A few large continents",
    "archipelago": "Many islands, little mainland",
    "pangaea": "One great supercontinent",
    "inland_sea": "Land surrounding an inland sea",
    "coastline": "One continent filling most of the map",
}


def seed_from_text(text: str) -> int:
    """
    Turn anything typed into a seed, the way Minecraft does.

    A run of digits is used as the number itself, so "12345" is the seed 12345
    and can be shared as such. Anything else is hashed with Java's String
    hashCode, which is the algorithm Minecraft uses - so a seed shared as a
    phrase always rebuilds the same world on any machine.

    Empty input returns 0; callers treat that as "pick one at random".
    """
    text = (text or "").strip()
    if not text:
        return 0
    if text.lstrip("-").isdigit():
        try:
            return abs(int(text)) & 0x7FFFFFFF
        except ValueError:
            pass
    h = 0
    for ch in text:
        h = (31 * h + ord(ch)) & 0xFFFFFFFF
    # Fold to a signed 32-bit range, then make it positive, exactly as Java's
    # hashCode would land before Minecraft takes the absolute value.
    if h >= 0x80000000:
        h -= 0x100000000
    return abs(h) & 0x7FFFFFFF


def random_seed() -> int:
    """A fresh seed for the 'surprise me' button."""
    return random.Random().randrange(1, 0x7FFFFFFF)


@dataclass
class MapParams:
    """Everything the generator needs. All of it is exposed in the dialog."""

    # 0 means "choose one at random". Any other value is used as given, so an
    # explicit seed still reproduces exactly. Defaulting to a real number here
    # would make a blank seed box silently generate the same world every time.
    seed: int = 0
    # What the writer actually typed, kept verbatim so the map can show the
    # seed back to them and they can share or re-enter it.
    seed_text: str = ""
    name: str = ""

    # --- land and water ------------------------------------------------
    shape: str = "continents"
    land_fraction: float = 0.34      # 0.05 - 0.85, share of the map that is land
    continents: int = 3              # major landmasses
    islands: int = 14                # scattered small islands
    roughness: float = 0.55          # 0 smooth coast, 1 deeply indented
    edge_water: float = 0.85         # how strongly the border is forced to ocean

    # --- relief ---------------------------------------------------------
    mountains: float = 0.45          # share of land that is mountainous
    hills: float = 0.35
    rivers: int = 8
    lakes: int = 4

    # --- climate --------------------------------------------------------
    climate: str = "temperate"
    forest: float = 0.4
    desert: float = 0.15
    marsh: float = 0.1
    ice_caps: bool = True

    # --- civilisation ---------------------------------------------------
    capitals: int = 2
    cities: int = 6
    towns: int = 12
    villages: int = 10
    ruins: int = 5
    landmarks: int = 4
    roads: bool = True
    name_flavour: str = "plain"
    name_places: bool = True

    # --- presentation ---------------------------------------------------
    width: int = 1800
    height: int = 1200
    style: str = "parchment"
    label_regions: bool = True
    scale_text: str = "200 leagues"

    def clamped(self) -> "MapParams":
        """Bring every value into a range the generator can actually handle."""
        p = MapParams(**self.__dict__)
        p.land_fraction = max(0.05, min(0.85, float(p.land_fraction)))
        p.roughness = max(0.0, min(1.0, float(p.roughness)))
        p.edge_water = max(0.0, min(1.0, float(p.edge_water)))
        p.mountains = max(0.0, min(1.0, float(p.mountains)))
        p.hills = max(0.0, min(1.0, float(p.hills)))
        p.forest = max(0.0, min(1.0, float(p.forest)))
        p.desert = max(0.0, min(1.0, float(p.desert)))
        p.marsh = max(0.0, min(1.0, float(p.marsh)))
        p.continents = max(1, min(12, int(p.continents)))
        p.islands = max(0, min(120, int(p.islands)))
        p.rivers = max(0, min(60, int(p.rivers)))
        p.lakes = max(0, min(40, int(p.lakes)))
        for attr in ("capitals", "cities", "towns", "villages", "ruins",
                     "landmarks"):
            setattr(p, attr, max(0, min(80, int(getattr(p, attr)))))
        p.width = max(600, min(6000, int(p.width)))
        p.height = max(400, min(6000, int(p.height)))
        # A typed seed always wins over a stale numeric one.
        if p.seed_text.strip():
            p.seed = seed_from_text(p.seed_text)
        if not p.seed:
            p.seed = random_seed()
        p.seed = int(p.seed) & 0x7FFFFFFF
        if p.shape not in LANDMASS_SHAPES:
            p.shape = "continents"
        if p.climate not in CLIMATES:
            p.climate = "temperate"
        return p


# ==========================================================================
# Noise
# ==========================================================================


def _smoothstep(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def _value_noise(w: int, h: int, frequency: int, rng: random.Random) -> Grid:
    """
    One octave of value noise: a coarse random lattice, smoothly interpolated.

    The lattice is square, so features are as tall as they are wide however
    wide the map is.
    """
    frequency = max(1, frequency)
    scale = frequency / max(1, w - 1)
    gw = frequency + 3
    gh = int((h - 1) * scale) + 3
    lattice = [[rng.random() for _ in range(gw)] for _ in range(gh)]

    columns = []
    for x in range(w):
        fx = x * scale
        x0 = int(fx)
        columns.append((x0, x0 + 1, _smoothstep(fx - x0)))

    out: Grid = []
    for y in range(h):
        fy = y * scale
        y0 = int(fy)
        ty = _smoothstep(fy - y0)
        top, bottom = lattice[y0], lattice[y0 + 1]
        blend = [a + (b - a) * ty for a, b in zip(top, bottom)]
        out.append([blend[x0] + (blend[x1] - blend[x0]) * tx
                    for x0, x1, tx in columns])
    return out


def _fbm(w: int, h: int, octaves: int, base_frequency: int,
         rng: random.Random, persistence: float = 0.5) -> Grid:
    """Fractal Brownian motion: octaves of noise at doubling frequency."""
    out: Grid = [[0.0] * w for _ in range(h)]
    amplitude = 1.0
    total = 0.0
    frequency = max(1, base_frequency)
    for _ in range(max(1, octaves)):
        layer = _value_noise(w, h, frequency, rng)
        for y in range(h):
            out[y] = [o + v * amplitude for o, v in zip(out[y], layer[y])]
        total += amplitude
        amplitude *= persistence
        frequency *= 2
        if frequency > w:
            break
    inverse = 1.0 / total if total else 1.0
    return [[v * inverse for v in row] for row in out]


def _stretch(grid: Grid) -> Grid:
    """Rescale a field to span 0..1, so thresholds mean the same on every seed."""
    low = min(min(row) for row in grid)
    high = max(max(row) for row in grid)
    span = (high - low) or 1.0
    return [[(v - low) / span for v in row] for row in grid]


# ==========================================================================
# Small grid tools
# ==========================================================================


def _downsample(grid: List[List]) -> List[List]:
    """Every second cell in each direction (the half-resolution working grid)."""
    return [row[::2] for row in grid[::2]]


def _blur(grid: Grid, passes: int = 1) -> Grid:
    """A 3x3 box blur, `passes` times. Edges repeat their outermost cell."""
    for _ in range(passes):
        rows = []
        for row in grid:
            left = [row[0]] + row[:-1]
            right = row[1:] + [row[-1]]
            rows.append([(a + b + c) * (1.0 / 3.0)
                         for a, b, c in zip(left, row, right)])
        h = len(rows)
        blurred = []
        for y in range(h):
            above = rows[y - 1] if y else rows[0]
            below = rows[y + 1] if y < h - 1 else rows[-1]
            blurred.append([(a + b + c) * (1.0 / 3.0)
                            for a, b, c in zip(above, rows[y], below)])
        grid = blurred
    return grid


def _distance_from(source: List[List[bool]], w: int, h: int) -> Grid:
    """
    Distance, in cells, from every cell to the nearest True cell of `source`.

    Two sweeps of the 3-4 chamfer mask: exact enough for placing labels and
    scoring building sites, and linear in the number of cells.
    """
    far = 1e9
    dist = [[0.0 if flag else far for flag in row] for row in source]
    diagonal = 1.4142
    for y in range(h):
        row = dist[y]
        above = dist[y - 1] if y else None
        for x in range(w):
            v = row[x]
            if v == 0.0:
                continue
            if x:
                t = row[x - 1] + 1.0
                if t < v:
                    v = t
            if above is not None:
                t = above[x] + 1.0
                if t < v:
                    v = t
                if x:
                    t = above[x - 1] + diagonal
                    if t < v:
                        v = t
                if x < w - 1:
                    t = above[x + 1] + diagonal
                    if t < v:
                        v = t
            row[x] = v
    for y in range(h - 1, -1, -1):
        row = dist[y]
        below = dist[y + 1] if y < h - 1 else None
        for x in range(w - 1, -1, -1):
            v = row[x]
            if v == 0.0:
                continue
            if x < w - 1:
                t = row[x + 1] + 1.0
                if t < v:
                    v = t
            if below is not None:
                t = below[x] + 1.0
                if t < v:
                    v = t
                if x < w - 1:
                    t = below[x + 1] + diagonal
                    if t < v:
                        v = t
                if x:
                    t = below[x - 1] + diagonal
                    if t < v:
                        v = t
            row[x] = v
    return dist


def _label_regions(mask: List[List[bool]], w: int, h: int,
                   min_size: int = 6) -> List[List[Tuple[int, int]]]:
    """Flood-fill connected True regions. Returns a cell list per region."""
    seen = [[False] * w for _ in range(h)]
    regions: List[List[Tuple[int, int]]] = []
    for sy in range(h):
        for sx in range(w):
            if not mask[sy][sx] or seen[sy][sx]:
                continue
            stack = [(sx, sy)]
            seen[sy][sx] = True
            cells: List[Tuple[int, int]] = []
            while stack:
                x, y = stack.pop()
                cells.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and \
                            mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            if len(cells) >= min_size:
                regions.append(cells)
    regions.sort(key=len, reverse=True)
    return regions


def _simplify(points: Sequence[Point], tolerance: float) -> List[Point]:
    """
    Douglas-Peucker, written iteratively.

    A traced coastline can be thousands of points; recursion would risk the
    interpreter's stack limit on a pathological shape.
    """
    pts = list(points)
    if len(pts) < 3 or tolerance <= 0:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]

    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        ax, ay = pts[first]
        bx, by = pts[last]
        dx, dy = bx - ax, by - ay
        span = math.hypot(dx, dy)
        worst = 0.0
        worst_index = -1
        for i in range(first + 1, last):
            px, py = pts[i]
            if span < 1e-12:
                distance = math.hypot(px - ax, py - ay)
            else:
                distance = abs(dy * px - dx * py + bx * ay - by * ax) / span
            if distance > worst:
                worst = distance
                worst_index = i
        if worst > tolerance and worst_index > 0:
            keep[worst_index] = True
            stack.append((first, worst_index))
            stack.append((worst_index, last))

    return [p for p, k in zip(pts, keep) if k]


# ==========================================================================
# Contours - marching squares
# ==========================================================================


def _contours(field: Grid, w: int, h: int, level: float
              ) -> List[Tuple[float, List[Point]]]:
    """
    Every closed contour of `field` at `level`, as (signed area, points).

    Marching squares: each 2x2 block of samples is classified by which corners
    are above the level, and the line crosses its edges at the linearly
    interpolated spot - so the outline is smooth and exact to a fraction of a
    cell, unlike tracing the edge of a set of cells, which is a staircase.

    The field is padded with a rim below the level, so no contour is ever open.
    Segments are directed with "above" on their left, which makes a landmass
    and a lake inside it wind opposite ways; the sign of the area (negative for
    a landmass, positive for a hole, because y points down) tells them apart.
    Points are in grid coordinates: sample (x, y) is at (x, y).
    """
    below = level - 1.0
    pw, ph = w + 2, h + 2
    pad: Grid = [[below] * pw]
    pad.extend([below] + list(row) + [below] for row in field)
    pad.append([below] * pw)
    inside = [[v > level for v in row] for row in pad]

    vbase = pw * ph
    nxt: Dict[int, int] = {}
    for y in range(ph - 1):
        top, bottom = inside[y], inside[y + 1]
        for x in range(pw - 1):
            index = ((8 if top[x] else 0) | (4 if top[x + 1] else 0)
                     | (2 if bottom[x + 1] else 0) | (1 if bottom[x] else 0))
            if index == 0 or index == 15:
                continue
            north = y * pw + x                  # the four edges of this block
            south = north + pw
            west = vbase + y * pw + x
            east = west + 1
            if index == 1:
                nxt[south] = west
            elif index == 2:
                nxt[east] = south
            elif index == 3:
                nxt[east] = west
            elif index == 4:
                nxt[north] = east
            elif index == 6:
                nxt[north] = south
            elif index == 7:
                nxt[north] = west
            elif index == 8:
                nxt[west] = north
            elif index == 9:
                nxt[south] = north
            elif index == 11:
                nxt[east] = north
            elif index == 12:
                nxt[west] = east
            elif index == 13:
                nxt[south] = east
            elif index == 14:
                nxt[west] = south
            else:                                # 5 and 10: a saddle
                centre = (pad[y][x] + pad[y][x + 1] + pad[y + 1][x + 1]
                          + pad[y + 1][x]) * 0.25 > level
                if index == 5:
                    if centre:
                        nxt[north] = west
                        nxt[south] = east
                    else:
                        nxt[north] = east
                        nxt[south] = west
                else:
                    if centre:
                        nxt[east] = north
                        nxt[west] = south
                    else:
                        nxt[west] = north
                        nxt[east] = south

    def point(key: int) -> Point:
        if key < vbase:                          # an edge between (x,y) and (x+1,y)
            row, col = divmod(key, pw)
            a, b = pad[row][col], pad[row][col + 1]
            return (col + (level - a) / (b - a) - 1.0, row - 1.0)
        row, col = divmod(key - vbase, pw)       # between (x,y) and (x,y+1)
        a, b = pad[row][col], pad[row + 1][col]
        return (col - 1.0, row + (level - a) / (b - a) - 1.0)

    rings: List[Tuple[float, List[Point]]] = []
    seen: Set[int] = set()
    for start in list(nxt):
        if start in seen:
            continue
        ring = [start]
        seen.add(start)
        key = nxt[start]
        while key != start and key in nxt and key not in seen:
            ring.append(key)
            seen.add(key)
            key = nxt[key]
        if key != start or len(ring) < 3:
            continue
        points = [point(k) for k in ring]
        area = 0.0
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
            area += x1 * y2 - x2 * y1
        rings.append((area * 0.5, points))
    return rings


# ==========================================================================
# The landmass
# ==========================================================================


def _continent_centres(params: MapParams, rng: random.Random
                       ) -> List[Tuple[float, float, float]]:
    """(cx, cy, radius) in grid units for each major landmass."""
    shape = params.shape
    out: List[Tuple[float, float, float]] = []

    if shape == "pangaea":
        out.append((GRID_W * 0.5, GRID_H * 0.5, GRID_W * 0.34))
    elif shape == "coastline":
        out.append((GRID_W * 0.44, GRID_H * 0.5, GRID_W * 0.38))
    elif shape == "inland_sea":
        # A ring of land around a central sea.
        for i in range(6):
            a = 2 * math.pi * i / 6 + rng.uniform(-0.15, 0.15)
            out.append((GRID_W * 0.5 + math.cos(a) * GRID_W * 0.27,
                        GRID_H * 0.5 + math.sin(a) * GRID_H * 0.30,
                        GRID_W * rng.uniform(0.15, 0.19)))
    elif shape == "archipelago":
        for _ in range(max(2, params.continents)):
            out.append((rng.uniform(0.2, 0.8) * GRID_W,
                        rng.uniform(0.2, 0.8) * GRID_H,
                        GRID_W * rng.uniform(0.06, 0.11)))
    else:  # continents
        count = max(1, params.continents)
        offset = rng.uniform(0, 2 * math.pi)
        for i in range(count):
            # Spread the centres out rather than clustering them randomly.
            angle = offset + 2 * math.pi * i / count + rng.uniform(-0.35, 0.35)
            spread = rng.uniform(0.17, 0.29) if count > 1 else 0.0
            out.append((GRID_W * (0.5 + math.cos(angle) * spread * 1.25),
                        GRID_H * (0.5 + math.sin(angle) * spread * 1.15),
                        GRID_W * rng.uniform(0.13, 0.20)))
    return out


def _landmass_lobes(params: MapParams, rng: random.Random
                    ) -> List[Tuple[float, float, float]]:
    """
    Each landmass as a cluster of overlapping round lobes.

    One big oval always reads as an oval, however much noise is added to its
    edge. Several lobes of different sizes give the peninsulas, bays and
    lopsided outlines real continents have.
    """
    lobes: List[Tuple[float, float, float]] = []
    for cx, cy, radius in _continent_centres(params, rng):
        lobes.append((cx, cy, radius))
        for _ in range(rng.randint(3, 5)):
            angle = rng.uniform(0.0, 2.0 * math.pi)
            reach = radius * rng.uniform(0.5, 1.0)
            lobes.append((cx + math.cos(angle) * reach,
                          cy + math.sin(angle) * reach * 0.8,
                          radius * rng.uniform(0.32, 0.62)))
    return lobes


def _splat(grid: Grid, w: int, h: int, cx: float, cy: float, rx: float,
           ry: float, sharpness: float, amplitude: float,
           reach: float = 2.4) -> None:
    """Raise `grid` to a soft round bump around (cx, cy), never lowering it."""
    x0 = max(0, int(cx - rx * reach))
    x1 = min(w, int(cx + rx * reach) + 1)
    y0 = max(0, int(cy - ry * reach))
    y1 = min(h, int(cy + ry * reach) + 1)
    inv_rx = 1.0 / rx
    inv_ry = 1.0 / ry
    exp = math.exp
    for y in range(y0, y1):
        dy = (y - cy) * inv_ry
        dy2 = dy * dy
        row = grid[y]
        for x in range(x0, x1):
            dx = (x - cx) * inv_rx
            v = exp(-(dx * dx + dy2) * sharpness) * amplitude
            if v > row[x]:
                row[x] = v


def _dent(grid: Grid, w: int, h: int, cx: float, cy: float, radius: float) -> None:
    """Cut a soft round bite out of `grid` around (cx, cy): a bay, a gulf."""
    x0 = max(0, int(cx - radius * 2.4))
    x1 = min(w, int(cx + radius * 2.4) + 1)
    y0 = max(0, int(cy - radius * 2.4))
    y1 = min(h, int(cy + radius * 2.4) + 1)
    inv = 1.0 / radius
    exp = math.exp
    for y in range(y0, y1):
        dy = (y - cy) * inv
        row = grid[y]
        for x in range(x0, x1):
            dx = (x - cx) * inv
            row[x] *= 1.0 - 0.95 * exp(-(dx * dx + dy * dy) * 1.4)


def build_heightmap(params: MapParams) -> Grid:
    rng = random.Random(params.seed)
    w, h = GRID_W, GRID_H
    rough = params.roughness

    # Fine detail decides how ragged the coast is: a rugged coast needs more
    # octaves, and each keeps more of its strength.
    detail = _fbm(w, h, 5 + int(rough * 2), 4 + int(rough * 2), rng,
                  0.50 + rough * 0.10)
    warp_x = _fbm(w, h, 3, 2, rng, 0.55)
    warp_y = _fbm(w, h, 3, 2, rng, 0.55)
    fray_x = _fbm(w, h, 3, 9, rng, 0.55)
    fray_y = _fbm(w, h, 3, 9, rng, 0.55)

    lobes = _landmass_lobes(params, rng)
    land: Grid = [[0.0] * w for _ in range(h)]
    for cx, cy, radius in lobes:
        _splat(land, w, h, cx, cy, radius, radius * 0.8, 1.15, 1.0)

    # Bites out of the coast. A compact continent is a fat oval however much it
    # is warped; a few gulfs and bays give it the indented outline of a real one.
    if params.shape not in ("archipelago", "inland_sea") and lobes:
        for _ in range(2 + int(rough * 4)):
            cx, cy, radius = rng.choice(lobes)
            angle = rng.uniform(0.0, 2.0 * math.pi)
            reach = radius * rng.uniform(0.75, 1.1)
            _dent(land, w, h, cx + math.cos(angle) * reach,
                  cy + math.sin(angle) * reach * 0.8,
                  radius * rng.uniform(0.22, 0.42))

    # Islands: some scattered anywhere, the rest strung out near the mainland
    # the way real archipelagos are. They go in *before* the warp below, so
    # they are bent and frayed like everything else instead of being the
    # perfect circles that give an artificial map away.
    for _ in range(params.islands):
        radius = rng.uniform(2.6, 7.0)
        if lobes and rng.random() < 0.55:
            cx, cy, lobe_radius = rng.choice(lobes)
            angle = rng.uniform(0.0, 2.0 * math.pi)
            distance = lobe_radius * rng.uniform(1.15, 1.9)
            ix = cx + math.cos(angle) * distance
            iy = cy + math.sin(angle) * distance * 0.8
            ix = min(max(ix, w * 0.05), w * 0.95)
            iy = min(max(iy, h * 0.05), h * 0.95)
        else:
            ix, iy = rng.uniform(0.06, 0.94) * w, rng.uniform(0.06, 0.94) * h
        _splat(land, w, h, ix, iy, radius, radius * rng.uniform(0.6, 1.0),
               1.0, 0.95, reach=3.0)

    # Bend the whole landmass with two smooth displacement fields: a broad one
    # (headlands, gulfs) and a finer one (inlets, frayed edges). This is what
    # turns a cluster of circles into a coastline.
    broad = w * (0.15 + 0.12 * rough)
    fine = w * (0.06 + 0.08 * rough)
    warped: Grid = []
    top = w - 1.001
    side = h - 1.001
    for y in range(h):
        wx_row, wy_row = warp_x[y], warp_y[y]
        fx_row, fy_row = fray_x[y], fray_y[y]
        row = []
        for x in range(w):
            fx = x + (wx_row[x] - 0.5) * 2.0 * broad + (fx_row[x] - 0.5) * 2.0 * fine
            fy = y + (wy_row[x] - 0.5) * 2.0 * broad + (fy_row[x] - 0.5) * 2.0 * fine
            fx = 0.0 if fx < 0.0 else (top if fx > top else fx)
            fy = 0.0 if fy < 0.0 else (side if fy > side else fy)
            x0, y0 = int(fx), int(fy)
            tx, ty = fx - x0, fy - y0
            a, b = land[y0], land[y0 + 1]
            row.append((a[x0] + (a[x0 + 1] - a[x0]) * tx) * (1.0 - ty)
                       + (b[x0] + (b[x0 + 1] - b[x0]) * tx) * ty)
        warped.append(row)

    # Push the borders under water so the world does not run off the page - and
    # leave the ocean margins the furniture needs: the title runs along the
    # top, the scale bar and compass sit in the bottom corners.
    column_edge = [min(x / max(1, w - 1), 1.0 - x / max(1, w - 1)) / 0.11
                   for x in range(w)]
    height: Grid = []
    for y in range(h):
        ny = y / max(1, h - 1)
        row_edge = min(ny / 0.19, (1.0 - ny) / 0.13)
        detail_row = detail[y]
        land_row = warped[y]
        row = []
        for x in range(w):
            edge = column_edge[x] if column_edge[x] < row_edge else row_edge
            falloff = min(1.0, edge) ** 1.5
            falloff = 1.0 - (1.0 - falloff) * params.edge_water
            n = detail_row[x]
            value = land_row[x] * 0.75 * (0.30 + n * 1.35) + n * 0.24
            row.append(value * falloff)
        height.append(row)

    if params.shape == "inland_sea":
        # Carve the sea in the middle back out.
        for y in range(h):
            row = height[y]
            for x in range(w):
                dx = (x - w * 0.5) / (w * 0.19)
                dy = (y - h * 0.5) / (h * 0.20)
                d2 = dx * dx + dy * dy
                if d2 < 4.0:
                    row[x] *= min(1.0, d2 / 1.4) ** 1.2
    return height


def sea_level_for(height: Grid, land_fraction: float) -> float:
    """
    The threshold that yields exactly the requested land fraction.

    Taking a percentile of the sorted heights means "35% land" is honoured on
    every seed, instead of varying wildly with the noise.
    """
    values = sorted(v for row in height for v in row)
    if not values:
        return 0.5
    index = int((1.0 - land_fraction) * (len(values) - 1))
    return values[max(0, min(len(values) - 1, index))]


def _elevation(params: MapParams, height: Grid, mask: List[List[bool]],
               sea: float) -> Grid:
    """
    Altitude 0..1 for every land cell (0 on the sea): the bulk rise inland,
    plus ridged noise, whose crests become mountain chains.
    """
    w, h = GRID_W, GRID_H
    ridges = _fbm(w, h, 5, 3, random.Random(params.seed ^ 0x51DE), 0.55)
    top = sea + 1e-6
    for row, mrow in zip(height, mask):
        for v, is_land in zip(row, mrow):
            if is_land and v > top:
                top = v
    span = top - sea
    strength = 0.30 + params.mountains * 0.70
    alt: Grid = []
    for y in range(h):
        hrow, mrow, nrow = height[y], mask[y], ridges[y]
        row = [0.0] * w
        for x in range(w):
            if mrow[x]:
                base = (hrow[x] - sea) / span
                crest = 1.0 - abs(2.0 * nrow[x] - 1.0)     # 1 along a ridge line
                crest *= crest
                row[x] = base * 0.45 + crest * min(1.0, base * 3.0) * 0.55 * strength
        alt.append(row)
    peak = max(max(r) for r in alt) or 1.0
    return [[v / peak for v in r] for r in alt]


# ==========================================================================
# Drainage: basins, lakes, rivers
# ==========================================================================

_N8 = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def _drain(alt: Grid, mask: List[List[bool]], w: int, h: int):
    """
    Priority flood: make every land cell drain to the sea.

    Starting from the shore, cells are visited lowest first, and each one that
    is a dip (lower than the water that has already reached it) is raised to
    that level. The result is a surface with no pits, so following "downhill"
    from anywhere always ends at the sea - which is exactly what rivers need,
    and which steepest-descent on the raw noise can not promise. The size of
    each raised area is the lake that would sit there.

    Returns (land, filled, parent, order, flat_alt) over flattened indices
    y * w + x. `parent[i]` is the cell that `i` drains into (-1: the sea) and
    `order` lists cells so that a parent always comes before its children.
    """
    size = w * h
    land = bytearray(size)
    flat_alt = [0.0] * size
    for y in range(h):
        base = y * w
        mrow, arow = mask[y], alt[y]
        for x in range(w):
            if mrow[x]:
                land[base + x] = 1
                flat_alt[base + x] = arow[x]

    filled = list(flat_alt)
    parent = [-1] * size
    seen = bytearray(size)
    heap: List[Tuple[float, int]] = []
    for y in range(h):
        base = y * w
        for x in range(w):
            i = base + x
            if not land[i]:
                continue
            for dx, dy in _N8:
                nx, ny = x + dx, y + dy
                if not (0 <= nx < w and 0 <= ny < h) or not land[ny * w + nx]:
                    seen[i] = 1
                    heapq.heappush(heap, (flat_alt[i], i))
                    break

    order: List[int] = []
    while heap:
        level, i = heapq.heappop(heap)
        order.append(i)
        y, x = divmod(i, w)
        for dx, dy in _N8:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h:
                j = ny * w + nx
                if land[j] and not seen[j]:
                    seen[j] = 1
                    parent[j] = i
                    raised = flat_alt[j]
                    if raised <= level:
                        raised = level + 1e-6
                    filled[j] = raised
                    heapq.heappush(heap, (raised, j))
    return land, filled, parent, order, flat_alt


def _upstream(start: int, children: Dict[int, List[int]],
              acc: List[float], limit: int = 3000) -> List[int]:
    """The main stem above `start`: keep stepping to the biggest inflow. Source first."""
    path = [start]
    current = start
    while len(path) < limit:
        kids = children.get(current)
        if not kids:
            break
        current = max(kids, key=acc.__getitem__)
        path.append(current)
    path.reverse()
    return path


# ==========================================================================
# Path finding
# ==========================================================================

_STEPS = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
          (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142))


def _astar(cost: Grid, w: int, h: int, start: Tuple[int, int],
           goal: Tuple[int, int], limit: int = 30000
           ) -> Optional[List[Tuple[int, int]]]:
    """
    A cheapest path over `cost` (0 means impassable), or None.

    Weighted slightly toward the goal: roads do not need to be provably
    optimal, they need to look plausible and arrive quickly.
    """
    gx, gy = goal

    def guess(x: int, y: int) -> float:
        dx, dy = abs(x - gx), abs(y - gy)
        return (dx + dy - 0.5858 * min(dx, dy)) * 1.05

    best = {start: 0.0}
    came: Dict[Tuple[int, int], Tuple[int, int]] = {}
    heap = [(guess(*start), 0.0, start)]
    expanded = 0
    while heap:
        _f, g, current = heapq.heappop(heap)
        if current == goal:
            path = [current]
            while current in came:
                current = came[current]
                path.append(current)
            path.reverse()
            return path
        if g > best.get(current, 1e18):
            continue
        expanded += 1
        if expanded > limit:
            return None
        x, y = current
        for dx, dy, step in _STEPS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h:
                c = cost[ny][nx]
                if c <= 0.0:
                    continue
                ng = g + c * step
                key = (nx, ny)
                if ng < best.get(key, 1e18):
                    best[key] = ng
                    came[key] = current
                    heapq.heappush(heap, (ng + guess(nx, ny), ng, key))
    return None


# ==========================================================================
# The generator
# ==========================================================================


class _World:
    """The working data every stage reads. Not part of the map itself."""

    def __init__(self, params: MapParams, height: Grid, sea: float,
                 mask: List[List[bool]]) -> None:
        self.params = params
        self.w, self.h = GRID_W, GRID_H
        self.height = height
        self.sea = sea
        self.mask = mask
        self.sx = params.width / float(self.w)
        self.sy = params.height / float(self.h)
        self.alt: Grid = []
        # Filled in by the drainage stage.
        self.land = bytearray()
        self.acc: List[float] = []
        self.parent: List[int] = []
        self.order: List[int] = []
        self.lake: List[List[bool]] = []
        self.rivers: List[List[int]] = []
        # Half resolution: distance (in half cells) from each cell to water.
        self.shore: Grid = []
        self.land2: List[List[bool]] = []

    def to_map(self, point: Point) -> Point:
        """Grid coordinates (cell centres on whole numbers) to map pixels."""
        return ((point[0] + 0.5) * self.sx, (point[1] + 0.5) * self.sy)

    def cell(self, index: int) -> Tuple[int, int]:
        y, x = divmod(index, self.w)
        return x, y


class _Namer:
    """Deterministic names: the same seed must rebuild the same world, names included."""

    def __init__(self, params: MapParams) -> None:
        self.params = params
        self.counter = 0

    def next(self, role: str) -> str:
        self.counter += 1
        seed = (self.params.seed * 7919 + self.counter * 104729) & 0x7FFFFFFF
        return name_for(role, self.params.name_flavour, seed=seed)


def generate(params: MapParams) -> GameMap:
    """Build a complete GameMap from parameters."""
    params = params.clamped()
    rng = random.Random(params.seed ^ 0x5EED)
    w, h = GRID_W, GRID_H

    height = build_heightmap(params)
    sea = sea_level_for(height, params.land_fraction)
    mask = [[v > sea for v in row] for row in height]

    # Anything smaller than a few cells is a fleck of noise, not an island.
    regions = _label_regions(mask, w, h, min_size=6)
    mask = [[False] * w for _ in range(h)]
    for cells in regions:
        for x, y in cells:
            mask[y][x] = True
    floor = sea - 0.01
    for y in range(h):
        hrow, mrow = height[y], mask[y]
        for x in range(w):
            if not mrow[x] and hrow[x] > sea:
                hrow[x] = floor

    world = _World(params, height, sea, mask)
    world.alt = _elevation(params, height, mask, sea)

    gm = GameMap(
        name=params.name or generate_name(
            params.name_flavour, params.seed).title(),
        kind="world",
        style=params.style,
        width=params.width,
        height=params.height,
        seed=params.seed % 9973,
        scale_text=params.scale_text,
        layers=[Layer(name="Land"), Layer(name="Terrain"),
                Layer(name="Water"), Layer(name="Places")],
    )
    namer = _Namer(params)

    _drainage(world)
    _add_coasts(gm, world)
    _add_lakes(gm, world)
    _add_relief(gm, world)
    _add_rivers(gm, world)
    _add_biomes(gm, world)
    sites = _add_settlements(gm, world, rng, namer)
    if params.roads and len(sites) >= 2:
        _add_roads(gm, world, sites, rng)
    if params.label_regions:
        _add_labels(gm, world, regions, rng, namer)

    # Record the recipe on the map itself. Someone handed this file can type
    # the same seed and settings and get the identical world back.
    shown = params.seed_text.strip() or str(params.seed)
    gm.notes = (
        f"Generated world.\n\n"
        f"SEED: {shown}\n"
        f"(numeric seed {params.seed})\n\n"
        f"Arrangement: {LANDMASS_SHAPES.get(params.shape, params.shape)}\n"
        f"Climate: {CLIMATES.get(params.climate, params.climate)}\n"
        f"Land: {params.land_fraction:.0%}   Roughness: {params.roughness:.0%}\n"
        f"Continents {params.continents}, islands {params.islands}, "
        f"rivers {params.rivers}, lakes {params.lakes}\n"
        f"Mountains {params.mountains:.0%}, forest {params.forest:.0%}, "
        f"desert {params.desert:.0%}, marsh {params.marsh:.0%}\n\n"
        f"Same seed and settings always rebuild this exact world. "
        f"Everything here is fully editable - draw over it, move pins, "
        f"rename anything."
    ).strip()

    return gm


# -- stage 1: drainage ------------------------------------------------------


def _drainage(world: _World) -> None:
    w, h = world.w, world.h
    land, filled, parent, order, flat_alt = _drain(world.alt, world.mask, w, h)
    world.land, world.parent, world.order = land, parent, order

    accumulation = [1.0 if land[i] else 0.0 for i in range(w * h)]
    for i in reversed(order):
        p = parent[i]
        if p >= 0:
            accumulation[p] += accumulation[i]
    world.acc = accumulation

    # A basin deeper than this holds a lake.
    depth_floor = 0.010
    lake = [[False] * w for _ in range(h)]
    depth: Grid = [[0.0] * w for _ in range(h)]
    for i in order:
        d = filled[i] - flat_alt[i]
        if d > depth_floor:
            y, x = divmod(i, w)
            depth[y][x] = d
            lake[y][x] = True
    world.lake = lake
    world._depth = depth                    # type: ignore[attr-defined]
    world._depth_floor = depth_floor        # type: ignore[attr-defined]

    water2 = [[not (m and not l) for m, l in zip(mrow, lrow)]
              for mrow, lrow in zip(_downsample(world.mask), _downsample(lake))]
    world.land2 = [[not v for v in row] for row in water2]
    world.shore = _distance_from(water2, HALF_W, HALF_H)


# -- stage 2: coastlines ----------------------------------------------------


def _ring_shape(kind: str, layer: str, points: Sequence[Point], world: _World,
                tolerance: float) -> Optional[Shape]:
    coords = [world.to_map(p) for p in points]
    coords.append(coords[0])
    coords = _simplify(coords, tolerance)
    coords.pop()
    if len(coords) < 4:
        return None
    return Shape(kind=kind, points=coords, closed=True, layer=layer)


def _add_coasts(gm: GameMap, world: _World) -> None:
    rings = _contours(world.height, world.w, world.h, world.sea)
    # Largest first, so a lake is drawn after the land that holds it and an
    # island in that lake after the lake.
    rings.sort(key=lambda item: -abs(item[0]))
    tolerance = max(world.sx, world.sy) * 0.28
    for area, points in rings:
        if abs(area) < 3.0:
            continue
        kind, layer = ("land", "Land") if area < 0 else ("water", "Water")
        shape = _ring_shape(kind, layer, points, world, tolerance)
        if shape:
            gm.shapes.append(shape)


def _add_lakes(gm: GameMap, world: _World) -> None:
    """The basins the flood raised - as many as were asked for, biggest first."""
    if not world.params.lakes:
        world.lake = [[False] * world.w for _ in range(world.h)]
        return
    w, h = world.w, world.h
    basins = _label_regions(world.lake, w, h, min_size=4)[:world.params.lakes]
    keep = [[False] * w for _ in range(h)]
    field: Grid = [[0.0] * w for _ in range(h)]
    depth = world._depth                      # type: ignore[attr-defined]
    for cells in basins:
        for x, y in cells:
            keep[y][x] = True
            field[y][x] = depth[y][x]
    world.lake = keep                          # only the lakes that get drawn
    level = world._depth_floor * 0.5           # type: ignore[attr-defined]
    tolerance = max(world.sx, world.sy) * 0.3
    for area, points in sorted(_contours(field, w, h, level),
                               key=lambda item: item[0]):
        if area >= 0 or -area < 3.0:
            continue
        shape = _ring_shape("water", "Water", points, world, tolerance)
        if shape:
            gm.shapes.append(shape)
    # The lakes that were dropped are land again, for everything downstream.
    water2 = [[not (m and not l) for m, l in zip(mrow, lrow)]
              for mrow, lrow in zip(_downsample(world.mask),
                                    _downsample(world.lake))]
    world.land2 = [[not v for v in row] for row in water2]
    world.shore = _distance_from(water2, HALF_W, HALF_H)


# -- stage 3: relief --------------------------------------------------------


def _ridge_lines(cells: Sequence[Tuple[int, int]]) -> List[List[Tuple[int, int]]]:
    """
    Reduce a blob of high ground to lines to draw peaks along.

    One representative cell per column (or per row, whichever axis the blob is
    longer on) gives a spine that follows the range. A broad blob gets several
    parallel spines, so a massif is not drawn as one thin chain.
    """
    if not cells:
        return []
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    wide = (max(xs) - min(xs)) >= (max(ys) - min(ys))
    across = (max(ys) - min(ys)) if wide else (max(xs) - min(xs))
    bands = 1 if across < 9 else (2 if across < 17 else 3)
    lo = min(ys) if wide else min(xs)
    thickness = (across + 1) / bands
    groups: List[Dict[int, List[int]]] = [{} for _ in range(bands)]
    for x, y in cells:
        along, cross = (x, y) if wide else (y, x)
        band = min(bands - 1, int((cross - lo) / thickness))
        groups[band].setdefault(along, []).append(cross)
    lines = []
    for group in groups:
        line = []
        for along, values in sorted(group.items()):
            values.sort()
            median = values[len(values) // 2]
            line.append((along, median) if wide else (median, along))
        if len(line) >= 3:
            lines.append(line)
    return lines


def _add_relief(gm: GameMap, world: _World) -> None:
    params, w, h = world.params, world.w, world.h
    heights = sorted(world.alt[y][x] for y in range(h) for x in range(w)
                     if world.mask[y][x])
    if not heights:
        return

    def percentile(fraction: float) -> float:
        index = int(max(0.0, min(1.0, fraction)) * (len(heights) - 1))
        return heights[index]

    share_mountain = 0.05 + params.mountains * 0.22
    share_hills = 0.04 + params.hills * 0.15
    mountain_cut = percentile(1.0 - share_mountain)
    hill_cut = percentile(1.0 - share_mountain - share_hills)
    tolerance = max(world.sx, world.sy) * 0.7
    for kind, low, high, cap in (("mountains", mountain_cut, None, 30),
                                 ("hills", hill_cut, mountain_cut, 22)):
        band = [[world.mask[y][x] and world.alt[y][x] >= low
                 and (high is None or world.alt[y][x] < high)
                 for x in range(w)] for y in range(h)]
        made = 0
        for cells in _label_regions(band, w, h, min_size=7):
            for line in _ridge_lines(cells):
                if made >= cap:
                    break
                points = _simplify([world.to_map(c) for c in line], tolerance)
                if len(points) >= 2:
                    gm.shapes.append(Shape(kind=kind, points=points,
                                           closed=False, layer="Terrain"))
                    made += 1


# -- stage 4: rivers --------------------------------------------------------


def _add_rivers(gm: GameMap, world: _World) -> None:
    params, w = world.params, world.w
    if not params.rivers:
        return
    land, parent, acc = world.land, world.parent, world.acc
    children: Dict[int, List[int]] = {}
    for i in world.order:
        p = parent[i]
        if p >= 0:
            children.setdefault(p, []).append(i)

    lake = world.lake
    mouths = []
    for i in world.order:
        p = parent[i]
        if p < 0:                       # this cell drains straight into the sea
            x, y = world.cell(i)
            if not lake[y][x]:
                mouths.append(i)
    mouths.sort(key=lambda i: -acc[i])

    chosen: List[Tuple[int, int]] = []
    tolerance = max(world.sx, world.sy) * 0.45

    def emit(path: List[int], close_to: Optional[int] = None) -> bool:
        cells = [world.cell(i) for i in path]
        if close_to is not None:
            cells.append(world.cell(close_to))
        # A path over grid cells is a staircase of 45-degree steps: round the
        # corners off first, then thin out the points that leaves.
        points = _simplify(_smooth([world.to_map(c) for c in cells], 2),
                           tolerance)
        if len(points) < 3:
            return False
        gm.shapes.append(Shape(kind="river", points=points, closed=False,
                               layer="Water"))
        world.rivers.append(path)
        return True

    for mouth in mouths:
        if len(chosen) >= params.rivers:
            break
        mx, my = world.cell(mouth)
        if any(math.hypot(mx - cx, my - cy) < 9 for cx, cy in chosen):
            continue
        if acc[mouth] < 30:
            break
        path = _upstream(mouth, children, acc)
        if len(path) < 14 or not emit(path):
            continue
        chosen.append((mx, my))

        # Tributaries: side branches that carry a fair share of the water.
        made = 0
        for index in range(len(path) - 1, 0, -1):
            if made >= 2:
                break
            here = path[index]
            main_before = path[index - 1]
            for kid in children.get(here, ()):
                if kid == main_before or acc[kid] < max(20.0, acc[here] * 0.30):
                    continue
                branch = _upstream(kid, children, acc)
                if len(branch) >= 8 and emit(branch, close_to=here):
                    made += 1
                    break


# -- stage 5: biomes --------------------------------------------------------


def _add_biomes(gm: GameMap, world: _World) -> None:
    params = world.params
    w2, h2 = HALF_W, HALF_H
    alt = _downsample(world.alt)
    land = world.land2
    shore = world.shore
    moisture = _stretch(_fbm(w2, h2, 4, 5, random.Random(params.seed ^ 0xB10), 0.55))
    patches = _stretch(_fbm(w2, h2, 4, 7, random.Random(params.seed ^ 0xF0E), 0.6))

    warm = {"tropical": 0.30, "arid": 0.20, "temperate": 0.0,
            "arctic": -0.34, "varied": 0.0}.get(params.climate, 0.0)
    # How much of each biome the climate favours: (desert, forest, marsh).
    desert_x, forest_x, marsh_x = {
        "tropical": (0.3, 1.4, 1.6), "arid": (2.0, 0.35, 0.4),
        "arctic": (0.0, 0.7, 0.6), "temperate": (1.0, 1.0, 1.0),
        "varied": (1.0, 1.0, 1.0)}.get(params.climate, (1.0, 1.0, 1.0))

    # Each land cell's altitude, warmth and wetness.
    cells = []
    for y in range(h2):
        latitude = abs(y / max(1, h2 - 1) - 0.5) * 2.0       # 0 equator, 1 pole
        for x in range(w2):
            if not land[y][x]:
                continue
            a = alt[y][x]
            temperature = (1.0 - latitude) - a * 0.30 + warm
            wetness = moisture[y][x] - a * 0.20
            cells.append((y * w2 + x, a, temperature, wetness, patches[y][x]))

    # The share of the land each biome gets comes from the sliders and is
    # enforced by *ranking* the cells, not by fixed thresholds on noise - which
    # put a whole continent's interior in one biome on some seeds and none on
    # the next. Ice is for the poles and the highest peaks: a generous
    # threshold turned every range into a pale oval that read as a lake.
    chosen: Dict[int, str] = {}
    for index, _a, temperature, _wet, _patch in cells:
        if params.ice_caps and temperature < 0.07:
            chosen[index] = "ice"
    rest = [c for c in cells if c[0] not in chosen]
    total = len(rest)

    dry = sorted((c for c in rest if c[2] > 0.40), key=lambda c: c[3])
    for c in dry[:int(total * params.desert * 0.55 * desert_x)]:
        chosen[c[0]] = "desert"
    low = sorted((c for c in rest if c[1] < 0.16 and c[0] not in chosen),
                 key=lambda c: -c[3])
    for c in low[:int(total * params.marsh * 0.5 * marsh_x)]:
        chosen[c[0]] = "swamp"
    leafy = sorted((c for c in rest if c[1] < 0.62 and c[0] not in chosen),
                   key=lambda c: -(c[3] + (c[4] - 0.5) * 0.5))
    for c in leafy[:int(total * params.forest * 0.75 * forest_x)]:
        chosen[c[0]] = "forest"

    kinds = ("ice", "desert", "swamp", "forest")
    classes = {kind: [[0.0] * w2 for _ in range(h2)] for kind in kinds}
    for index, kind in chosen.items():
        classes[kind][index // w2][index % w2] = 1.0

    # Biomes fade out toward any shore, so they never hug a coast or lake.
    ramp = [[min(1.0, max(0.0, (shore[y][x] - 0.6) / 2.6)) for x in range(w2)]
            for y in range(h2)]
    tolerance = max(world.sx, world.sy) * 0.9
    limits = {"ice": (4, 10.0), "desert": (8, 14.0),
              "swamp": (8, 10.0), "forest": (22, 14.0)}
    for kind in kinds:
        grid = classes[kind]
        if not any(any(row) for row in grid):
            continue
        field = _blur(grid, 2)
        field = [[f * r for f, r in zip(frow, rrow)]
                 for frow, rrow in zip(field, ramp)]
        cap, least = limits[kind]
        rings = [(a, pts) for a, pts in _contours(field, w2, h2, 0.5)
                 if a < 0 and -a >= least]
        rings.sort(key=lambda item: item[0])
        for _area, points in rings[:cap]:
            scaled = [(px * 2.0, py * 2.0) for px, py in points]
            shape = _ring_shape(kind, "Terrain", scaled, world, tolerance)
            if shape:
                gm.shapes.append(shape)


# -- stage 6: settlements ---------------------------------------------------


def _add_settlements(gm: GameMap, world: _World, rng: random.Random,
                     namer: _Namer) -> List[Tuple[int, int]]:
    """Score every land cell for habitability, then take the best sites apart."""
    params, w, h = world.params, world.w, world.h
    shore, acc = world.shore, world.acc
    cells: List[Tuple[float, float, int, int, float, float]] = []
    for y in range(h):
        for x in range(w):
            if not world.mask[y][x] or world.lake[y][x]:
                continue
            altitude = world.alt[y][x]
            if altitude > 0.74:
                continue                           # nobody builds a capital on a peak
            distance = shore[y >> 1][x >> 1]
            if distance <= 0.0:
                continue
            fresh = min(1.0, acc[y * w + x] / 200.0)
            gentle = 1.0 - min(1.0, altitude * 1.5)
            score = gentle * 0.42 + fresh * 0.34
            if distance <= 1.6:
                score += 0.14                      # a harbour, but not a coast-hugging row
            elif distance <= 5.0:
                score += 0.12                      # near the sea, near a river's mouth
            cells.append((score + rng.uniform(0.0, 0.13), altitude, x, y,
                          distance, fresh))

    ranked = sorted(cells, reverse=True)
    coastal = [c for c in ranked if c[4] <= 1.6]
    upland = [c for c in ranked if 0.22 <= c[1] <= 0.62]
    anywhere = list(ranked)
    rng.shuffle(anywhere)

    plan = [
        ("capital", params.capitals, 26, 9.0, ranked),
        ("city", params.cities, 18, 7.5, ranked),
        ("port", max(0, params.cities // 3), 16, 7.0, coastal),
        ("town", params.towns, 11, 6.5, ranked),
        ("village", params.villages, 7, 5.5, ranked),
        ("castle", max(0, params.towns // 4), 12, 6.5, upland),
        ("ruin", params.ruins, 9, 6.0, anywhere),
        ("landmark", params.landmarks, 14, 6.5, anywhere),
    ]

    taken: List[Tuple[int, int]] = []
    sites: List[Tuple[int, int]] = []
    used_names: Set[str] = set()

    for kind, count, spacing, size, pool in plan:
        placed = 0
        for _score, _alt, x, y, _dist, _fresh in pool:
            if placed >= count:
                break
            if any(math.hypot(x - tx, y - ty) < spacing for tx, ty in taken):
                continue
            taken.append((x, y))
            if kind in ("capital", "city", "port", "town", "village", "castle"):
                sites.append((x, y))
            px, py = world.to_map((x, y))
            label = _place_name(params, namer, used_names) \
                if params.name_places else ""
            gm.pins.append(Pin(x=px, y=py, kind=kind, label=label, size=size,
                               label_side="e", layer="Places"))
            placed += 1
    return sites


def _place_name(params: MapParams, namer: _Namer, used: Set[str]) -> str:
    for _ in range(12):
        candidate = namer.next("settlement")
        if candidate not in used:
            used.add(candidate)
            return candidate
    # Every attempt collided, which happens as soon as the writer's own name
    # lists are small - three beginnings and three endings is nine possible
    # names for forty settlements. Distinguish it the way real places do.
    base = namer.next("settlement")
    for prefix in ("Upper ", "Lower ", "Little ", "Great ", "New ", "Old ",
                   "East ", "West ", "North ", "South "):
        if prefix + base not in used:
            used.add(prefix + base)
            return prefix + base
    number = 2
    while f"{base} {number}" in used:
        number += 1
    used.add(f"{base} {number}")
    return f"{base} {number}"


# -- stage 7: roads ---------------------------------------------------------


def _add_roads(gm: GameMap, world: _World, sites: Sequence[Tuple[int, int]],
               rng: random.Random) -> None:
    """
    Join the settlements with roads that follow the land.

    A minimum spanning tree decides which pairs are connected (so every place is
    reachable and the network is not a hairball), a few extra short links close
    loops, and each link is routed by A* over a cost grid: water is impassable,
    steep ground is dear, crossing a river costs a bridge, and roads that already
    exist are cheap, so later roads merge into earlier ones like trunk roads do.
    """
    sites = list(sites[:24])
    n = len(sites)
    if n < 2:
        return
    w2, h2 = HALF_W, HALF_H
    alt2 = _downsample(world.alt)
    land2 = world.land2
    cost: Grid = [[0.0] * w2 for _ in range(h2)]
    for y in range(h2):
        for x in range(w2):
            if not land2[y][x]:
                continue
            gx = alt2[y][min(x + 1, w2 - 1)] - alt2[y][max(x - 1, 0)]
            gy = alt2[min(y + 1, h2 - 1)][x] - alt2[max(y - 1, 0)][x]
            cost[y][x] = 1.0 + alt2[y][x] * 2.5 + (abs(gx) + abs(gy)) * 25.0
            if world.shore[y][x] < 1.6:
                cost[y][x] += 1.4          # a road on the very shore reads as a second coastline
    for path in world.rivers:
        for i in path:
            x, y = world.cell(i)
            if cost[y >> 1][x >> 1] > 0.0:
                cost[y >> 1][x >> 1] += 2.5

    def distance(a: int, b: int) -> float:
        return math.hypot(sites[a][0] - sites[b][0], sites[a][1] - sites[b][1])

    # Prim's algorithm from the first site (the capital).
    in_tree = [False] * n
    in_tree[0] = True
    nearest = [distance(0, j) for j in range(n)]
    link = [0] * n
    edges: List[Tuple[int, int]] = []
    for _ in range(n - 1):
        j = min((k for k in range(n) if not in_tree[k]), key=nearest.__getitem__)
        edges.append((link[j], j))
        in_tree[j] = True
        for k in range(n):
            if not in_tree[k]:
                d = distance(j, k)
                if d < nearest[k]:
                    nearest[k], link[k] = d, j
    tree = set(edges) | {(b, a) for a, b in edges}
    extras = sorted(((distance(a, b), a, b) for a in range(n)
                     for b in range(a + 1, n) if (a, b) not in tree))
    limit = world.w * 0.22
    edges.extend((a, b) for d, a, b in extras[:max(1, n // 5)] if d < limit)

    def passable(x: int, y: int) -> Optional[Tuple[int, int]]:
        for dx, dy in ((0, 0),) + _N8:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w2 and 0 <= ny < h2 and cost[ny][nx] > 0.0:
                return nx, ny
        return None

    tolerance = max(world.sx, world.sy) * 0.8
    for a, b in edges:
        start = passable(sites[a][0] >> 1, sites[a][1] >> 1)
        goal = passable(sites[b][0] >> 1, sites[b][1] >> 1)
        if not start or not goal or start == goal:
            continue
        path = _astar(cost, w2, h2, start, goal)
        if not path or len(path) < 2:
            continue
        for x, y in path:
            cost[y][x] *= 0.45             # the next road prefers this one
        points = [world.to_map((x * 2.0, y * 2.0)) for x, y in path]
        points[0] = world.to_map(sites[a])
        points[-1] = world.to_map(sites[b])
        points = _simplify(points, tolerance)
        if len(points) >= 2:
            gm.shapes.append(Shape(kind="road", points=points, closed=False,
                                   layer="Places"))


# -- stage 8: names on the map ---------------------------------------------


def _add_labels(gm: GameMap, world: _World,
                regions: Sequence[Sequence[Tuple[int, int]]],
                rng: random.Random, namer: _Namer) -> None:
    """Name the largest landmasses where the land is deepest, and the ocean where the water is."""
    params = world.params
    shore = world.shore
    # Only the two biggest landmasses get a name. More than that and the page
    # fills with large text that fights the place names for attention.
    suffixes = ["", "", " REACH", " LANDS", " MARCHES"]
    big = world.w * world.h * 0.012
    for cells in regions[:2]:
        if len(cells) < big:
            continue
        # The middle of the land, by distance from every shore - not the
        # average of its cells, which for a bent continent lies in the sea.
        x, y = max(cells, key=lambda c: shore[c[1] >> 1][c[0] >> 1])
        px, py = world.to_map((x, y))
        gm.labels.append(MapLabel(
            x=px, y=py, text=namer.next("region").upper() + rng.choice(suffixes),
            size=max(14, int(gm.height * 0.020)),
            italic=False, bold=True, tracking=4.0, layer="Places",
        ))

    text = f"THE {namer.next('water').upper()} OCEAN"
    size = max(14, int(gm.height * 0.020))
    width = len(text) * (size * 0.62 + 6.0)             # roughly, with the letter spacing
    spot, room = _open_water(world)
    if spot and room >= width * 0.5:
        px, py = world.to_map(spot)
    else:                                               # no sea wide enough: the bottom margin
        px, py = gm.width * 0.5, gm.height * 0.925
    gm.labels.append(MapLabel(x=px, y=py, text=text, size=size,
                              italic=True, tracking=6.0, layer="Places"))


def _open_water(world: _World) -> Tuple[Optional[Point], float]:
    """
    The point in the sea farthest from any land (kept off the map's edge), and
    the radius of clear water around it in map pixels. Lakes are not the sea.
    """
    w2, h2 = HALF_W, HALF_H
    land = _downsample(world.mask)
    far = _distance_from(land, w2, h2)            # distance to the nearest land
    best, spot = 0.0, None
    for y in range(int(h2 * 0.16), int(h2 * 0.84)):
        for x in range(int(w2 * 0.16), int(w2 * 0.84)):
            if y > h2 * 0.68 and x > w2 * 0.70:        # the compass lives there
                continue
            if not land[y][x] and far[y][x] > best:
                best, spot = far[y][x], (x * 2.0, y * 2.0)
    return spot, best * 2.0 * min(world.sx, world.sy)


# ==========================================================================
# Presets
# ==========================================================================

PRESETS: Dict[str, Dict] = {
    "Classic fantasy world": dict(
        shape="continents", land_fraction=0.34, continents=3, islands=16,
        roughness=0.55, mountains=0.45, rivers=9, climate="temperate",
        forest=0.45, capitals=2, cities=6, towns=12, villages=10),
    "Island archipelago": dict(
        shape="archipelago", land_fraction=0.18, continents=6, islands=45,
        roughness=0.7, mountains=0.3, rivers=4, climate="tropical",
        forest=0.6, marsh=0.2, capitals=1, cities=4, towns=8, villages=12),
    "Single supercontinent": dict(
        shape="pangaea", land_fraction=0.55, continents=1, islands=8,
        roughness=0.45, mountains=0.5, rivers=14, climate="varied",
        forest=0.35, desert=0.25, capitals=3, cities=10, towns=18),
    "Frozen north": dict(
        shape="continents", land_fraction=0.4, continents=2, islands=20,
        roughness=0.6, mountains=0.55, rivers=6, climate="arctic",
        forest=0.25, ice_caps=True, capitals=1, cities=3, towns=7,
        villages=9, ruins=8),
    "Desert kingdoms": dict(
        shape="coastline", land_fraction=0.5, continents=1, islands=5,
        roughness=0.4, mountains=0.35, rivers=3, climate="arid",
        forest=0.1, desert=0.6, capitals=2, cities=5, towns=9, ruins=7),
    "Inland sea": dict(
        shape="inland_sea", land_fraction=0.45, continents=6, islands=12,
        roughness=0.5, mountains=0.4, rivers=11, climate="temperate",
        forest=0.4, capitals=3, cities=8, towns=14),
    "Scattered isles": dict(
        shape="archipelago", land_fraction=0.1, continents=8, islands=70,
        roughness=0.8, mountains=0.2, rivers=2, climate="tropical",
        forest=0.55, capitals=1, cities=2, towns=5, villages=8, ruins=6),
}


def random_params(name: str = "") -> MapParams:
    """
    A whole world, decided for you.

    No seed to think of, no preset to pick, no sliders. Everything is drawn
    from the system's own entropy, so pressing the button twice gives two
    different worlds - which is what "random" is supposed to mean, and was not
    true while the seed defaulted to a fixed number and every choice had to be
    made in a dialog first.

    The seed is still recorded on the finished map, so a world you like can be
    reproduced exactly.
    """
    from .mapmaker import NAME_ROLES, name_styles

    rng = random.Random()          # seeded from the OS, not from a number
    params = preset(rng.choice(list(PRESETS)), rng.getrandbits(31))

    styles = name_styles() or ["plain"]
    params.name_flavour = rng.choice(styles)
    params.name_places = True

    # Give each kind of thing its own style. A world where the kingdoms, the
    # towns and the sea all sound alike reads as one culture; a world where
    # they differ reads as history.
    if len(styles) > 1:
        for role in list(NAME_ROLES):
            NAME_ROLES[role] = rng.choice(styles)
        # Regions and the realms on them share a tongue: they are the same
        # people, named at different scales.
        NAME_ROLES["region"] = NAME_ROLES["realm"]
        NAME_ROLES["river"] = NAME_ROLES["water"]

    # Size and population vary too, so successive worlds do not all feel like
    # the same map with the coastline moved.
    params.width = rng.choice([1400, 1600, 1800, 2000, 2200])
    params.height = int(params.width * rng.uniform(0.62, 0.78))
    params.cities = rng.randint(3, 9)
    params.towns = rng.randint(6, 18)

    if name:
        params.name = name
    else:
        first = generate_name(params.name_flavour).title()
        params.name = rng.choice([
            f"The {first} Reach", f"The {first} Lands", f"{first}",
            f"The Kingdoms of {first}", f"{first} and Beyond",
            f"The {first} Coast",
        ])
    return params


def preset(name: str, seed: int = 1) -> MapParams:
    params = MapParams(seed=seed)
    for key, value in PRESETS.get(name, {}).items():
        setattr(params, key, value)
    return params.clamped()
