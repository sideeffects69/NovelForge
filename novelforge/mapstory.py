"""
Where the map meets the story.

A map has always been a picture in this tool: you draw it, you look at it, and
nothing else in the project knows it exists. Meanwhile the story graph knows
exactly which scenes mention which locations, in what order, and the timeline
knows when. The two have simply never been introduced.

This module introduces them:

    pin_index(project)              which entity each pin stands for
    attach(project, graph)          pins become nodes in the story graph
    distance(gm, a, b)              how far apart two pins are, in world units
    chapter_state(project, graph, n)  where everyone is by the end of chapter n
    check_maps(project, graph)      continuity questions only a map can ask

The last two are the point. "Ada is at the Low Well in chapter nine and the
Iron Keep in chapter ten, and those are four hundred leagues apart" is not a
question a manuscript can answer on its own, and it is exactly the question
that ruins epic fantasy.

Nothing here simulates anything. There are no tectonics, no climate, no
economy. It reads the maps you drew and the prose you wrote and points at the
places they disagree.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from . import mapmaker as mm

#: Words that mean "a unit of distance" in the scale caption, and how many
#: miles one of them is: feet, yards, paces, metres, kilometres, miles, leagues
#: (three miles), days' march, parsecs, AU and light-years, spelled out,
#: plural or abbreviated (ft, yd, m, km, mi, pc, AU, ly). Only used to phrase
#: warnings in something familiar; the checks themselves work in whatever unit
#: the writer chose. The table itself lives in `mapmaker.UNIT_TABLE`, next to
#: the code that formats a caption, so the two cannot drift apart.
_UNITS: Dict[str, float] = {
    word: row[3]
    for word, row in mm._UNIT_BY_WORD.items()
}

#: Units for which "about N miles" is no help and a horse-speed check is
#: meaningless.
_ASTRONOMICAL = mm.ASTRONOMICAL_UNITS

# One scale, one implementation: the map maker owns how a scale bar is drawn
# and what it is worth; these are the names the rest of the app already reads.
apply_scale = mm.apply_scale
scale_bar = mm.scale_bar
nice_number = mm.nice_number


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def load_maps(project) -> List[Any]:
    """Every saved map in the project, worst case a few small JSON files."""
    folder = project.folder("maps")
    maps: List[Any] = []
    try:
        paths = sorted(folder.glob("*.json"))
    except OSError:
        return maps
    for path in paths:
        try:
            game_map = mm.load_map(path)
        except Exception:
            continue
        if game_map is not None:
            maps.append(game_map)
    return maps


def map_signature(project) -> Tuple:
    """Cheap fingerprint of the maps, for the graph cache."""
    try:
        return tuple(sorted(
            (p.name, p.stat().st_mtime)
            for p in project.folder("maps").glob("*.json")
        ))
    except OSError:
        return ()


@dataclass
class PinRef:
    """One pin, and which map it is on."""

    pin: Any
    map_name: str
    map_id: str

    @property
    def entity_id(self) -> str:
        return getattr(self.pin, "entity_id", "") or ""

    @property
    def label(self) -> str:
        return getattr(self.pin, "label", "") or "(unnamed pin)"


def pin_index(project, maps: Optional[Sequence[Any]] = None
              ) -> Dict[str, PinRef]:
    """entity id -> the pin that stands for it, first map wins."""
    index: Dict[str, PinRef] = {}
    for game_map in (maps if maps is not None else load_maps(project)):
        for pin in game_map.pins:
            entity_id = getattr(pin, "entity_id", "")
            if entity_id and entity_id not in index:
                index[entity_id] = PinRef(pin, game_map.name, game_map.id)
    return index


# --------------------------------------------------------------------------
# Maps inside maps
# --------------------------------------------------------------------------

child_seed = mm.child_seed
link_child = mm.link_child
unlink_child = mm.unlink_child


class Crumb(NamedTuple):
    """One step of a breadcrumb: a map, and the pin (on the map before it) that opens it."""

    map_id: str
    name: str
    #: The pin on the previous crumb's map that this map is inside; "" for the top.
    pin_id: str = ""
    pin_label: str = ""


def breadcrumb(maps: Sequence[Any], game_map) -> List[Crumb]:
    """
    Where a map sits in the nest of maps, top first, ending with `game_map`:
    World, then Harrowgate (a pin on it), then The Gilded Stag.

    Follows each map's `parent` link up through `maps` (what `load_maps`
    returns). A link to a map that no longer exists ends the chain there, and a
    loop (which should never be saved) is cut rather than followed forever, so
    this always returns something, at worst just `game_map` itself.
    """
    by_id = {getattr(m, "id", ""): m for m in maps}
    chain = [game_map]
    seen = {getattr(game_map, "id", "")}
    current = game_map
    while len(chain) < 32:
        link = getattr(current, "parent", None) or {}
        parent = by_id.get(link.get("map_id", ""))
        if parent is None or getattr(parent, "id", "") in seen:
            break
        chain.append(parent)
        seen.add(parent.id)
        current = parent
    chain.reverse()
    crumbs: List[Crumb] = []
    for i, item in enumerate(chain):
        pin_id, pin_label = "", ""
        if i:
            pin_id = (getattr(item, "parent", None) or {}).get("pin_id", "")
            pin = chain[i - 1].pin(pin_id) if pin_id else None
            pin_label = getattr(pin, "label", "") or ""
        crumbs.append(Crumb(getattr(item, "id", ""), getattr(item, "name", "") or "",
                            pin_id, pin_label))
    return crumbs


def breadcrumb_text(maps: Sequence[Any], game_map, sep: str = " > ") -> str:
    """The breadcrumb as one line: "World > Harrowgate > The Gilded Stag"."""
    return sep.join(c.name or "(unnamed map)" for c in breadcrumb(maps, game_map))


# --------------------------------------------------------------------------
# Joining the story graph
# --------------------------------------------------------------------------


def attach(project, graph, maps: Optional[Sequence[Any]] = None) -> int:
    """
    Add every pin to the story graph and link it to what it depicts.

    Returns how many pins were attached. Called from storygraph.build, so
    every consumer of the graph - the dependency map, the story bible, the
    question box - sees pins without knowing this module exists.
    """
    from .storygraph import Node

    count = 0
    for game_map in (maps if maps is not None else load_maps(project)):
        map_node_id = f"map:{game_map.id or game_map.name}"
        graph.add_node(Node(map_node_id, "map", game_map.name, 0, game_map))
        for pin in game_map.pins:
            pin_id = f"pin:{game_map.id}:{pin.id}"
            graph.add_node(Node(pin_id, "pin",
                                pin.label or "(unnamed pin)", 0, pin))
            graph.add_edge(map_node_id, pin_id, "covers")
            if pin.entity_id and pin.entity_id in graph.nodes:
                # "depicts" rather than "linked": the pin is a picture of the
                # place, not another appearance of it, and counting it as an
                # appearance would make every pinned location look visited.
                graph.add_edge(pin_id, pin.entity_id, "depicts")
            count += 1
    return count


# --------------------------------------------------------------------------
# Distance
# --------------------------------------------------------------------------


@dataclass
class Scale:
    """How many world units one pixel is, read from the map's scale caption."""

    units_per_pixel: float = 0.0
    unit: str = ""
    #: How long the scale bar is on screen, in pixels.
    bar_pixels: float = 0.0

    @property
    def known(self) -> bool:
        return self.units_per_pixel > 0

    @property
    def astronomical(self) -> bool:
        """Parsecs, AU, light-years: distances a "miles" phrasing cannot help."""
        return self.unit.lower() in _ASTRONOMICAL

    def to_miles(self, amount: float) -> Optional[float]:
        factor = _UNITS.get(self.unit.lower())
        return amount * factor if factor else None


def read_scale(game_map) -> Scale:
    """
    Work out the map's scale from its caption, e.g. "100 leagues".

    The caption says what the *drawn scale bar* is worth, so the length in
    pixels comes from the very function that draws it (`mapmaker.scale_bar`).
    It used to be assumed here as a fifth of the map's width while the picture
    drew 16% (at most 230 px), which made every distance 64-72% of the truth.
    If the caption has no number, the scale is unknown and every distance check
    quietly stands down rather than inventing a number.
    """
    bar = mm.scale_bar(game_map)
    if not bar.known:
        return Scale()
    return Scale(units_per_pixel=bar.units_per_pixel, unit=bar.unit or "units",
                 bar_pixels=bar.px)


def distance(game_map, a, b) -> Optional[float]:
    """Straight-line distance between two pins, in the map's own units."""
    scale = read_scale(game_map)
    if not scale.known:
        return None
    pixels = math.hypot(a.x - b.x, a.y - b.y)
    return pixels * scale.units_per_pixel


def describe_distance(game_map, a, b) -> str:
    value = distance(game_map, a, b)
    if value is None:
        return ""
    scale = read_scale(game_map)
    miles = scale.to_miles(value)
    # Small distances (a room in feet) need their decimals; a whole kingdom
    # does not.
    shown = (f"{value:,.0f}" if value >= 10 or value == 0
             else f"{value:,.1f}".rstrip("0").rstrip("."))
    text = f"{shown} {scale.unit}"
    if miles and not scale.astronomical \
            and mm.unit_info(scale.unit) is not None \
            and mm.unit_info(scale.unit)[0] != "mile":
        text += f" (about {miles:,.0f} miles)" if miles >= 10 \
            else f" (about {miles:,.2f} miles)"
    return text


# --------------------------------------------------------------------------
# Chapter map view
# --------------------------------------------------------------------------


@dataclass
class Presence:
    """Where one character is, and how they got there."""

    entity_id: str
    name: str
    #: Entity ids of locations, in the order the character appeared at them.
    route: List[str] = field(default_factory=list)

    @property
    def here(self) -> str:
        return self.route[-1] if self.route else ""


@dataclass
class ChapterState:
    """The world as it stands at the end of one chapter."""

    chapter_id: str
    chapter_title: str
    index: int
    #: character id -> where they are and where they have been
    characters: Dict[str, Presence] = field(default_factory=dict)
    #: location ids named in this chapter
    mentioned_now: List[str] = field(default_factory=list)
    #: location ids named anywhere so far
    mentioned_ever: List[str] = field(default_factory=list)
    #: location ids visited in a scene, ever
    visited: List[str] = field(default_factory=list)
    #: pinned locations nobody has been to or spoken of
    untouched: List[str] = field(default_factory=list)


def _locations_in(graph, scene_id: str) -> List[str]:
    out: List[str] = []
    for edge in graph.out_edges(scene_id, ("linked", "mentions")):
        node = graph.nodes.get(edge.target)
        if node is not None and node.kind == "location":
            out.append(edge.target)
    return list(dict.fromkeys(out))


def _characters_in(graph, scene_id: str) -> List[str]:
    out: List[str] = []
    for edge in graph.out_edges(scene_id, ("linked", "pov", "mentions")):
        node = graph.nodes.get(edge.target)
        if node is not None and node.kind == "character":
            out.append(edge.target)
    return list(dict.fromkeys(out))


def chapter_states(project, graph) -> List[ChapterState]:
    """
    Replay the book chapter by chapter, tracking where everyone is.

    A character's position is the location of the last scene they appeared in.
    Where a scene names several places, the one *linked* to the scene wins
    over one merely mentioned in passing - a scene can talk about somewhere
    far away without anybody going there.
    """
    data = project.data
    pinned = set(pin_index(project))
    states: List[ChapterState] = []

    presence: Dict[str, Presence] = {}
    mentioned_ever: List[str] = []
    visited: List[str] = []

    for index, chapter in enumerate(data.ordered_chapters()):
        mentioned_now: List[str] = []
        for scene in data.scenes_in(chapter.id):
            here = [loc for loc in scene.location_ids if loc in graph.nodes]
            named = _locations_in(graph, scene.id)
            for loc in named:
                if loc not in mentioned_now:
                    mentioned_now.append(loc)
                if loc not in mentioned_ever:
                    mentioned_ever.append(loc)
            where = here[0] if here else (named[0] if named else "")
            if where and where not in visited:
                visited.append(where)
            if not where:
                continue
            for character_id in _characters_in(graph, scene.id):
                node = graph.nodes.get(character_id)
                entry = presence.setdefault(
                    character_id,
                    Presence(character_id, node.name if node else "?"))
                if entry.here != where:
                    entry.route.append(where)

        states.append(ChapterState(
            chapter_id=chapter.id,
            chapter_title=chapter.display,
            index=index,
            characters={k: Presence(v.entity_id, v.name, list(v.route))
                        for k, v in presence.items()},
            mentioned_now=list(mentioned_now),
            mentioned_ever=list(mentioned_ever),
            visited=list(visited),
            untouched=[p for p in pinned
                       if p not in mentioned_ever
                       and graph.nodes.get(p) is not None
                       and graph.nodes[p].kind == "location"],
        ))
    return states


# --------------------------------------------------------------------------
# Continuity that only a map can check
# --------------------------------------------------------------------------


def check_maps(project, graph) -> List:
    """Map-aware continuity findings, in storygraph's Issue shape."""
    from .storygraph import Issue

    issues: List[Issue] = []
    data = project.data
    maps = load_maps(project)
    if not maps:
        return issues

    index = pin_index(project, maps)
    by_map = {m.id: m for m in maps}

    # 1. Pins pointing at nothing --------------------------------------
    for game_map in maps:
        for pin in game_map.pins:
            if pin.entity_id and not data.entity(pin.entity_id):
                issues.append(Issue(
                    "high", "Map link",
                    f"Pin '{pin.label or pin.id}' on '{game_map.name}' points "
                    f"at a deleted place",
                    "Open the map and re-link the pin, or remove it.",
                    game_map.name,
                ))

    # 2. Pinned, but the book never goes there --------------------------
    for entity_id, ref in index.items():
        entity = data.entity(entity_id)
        if entity is None:
            continue
        appearances = graph.scenes_with(entity_id)
        if not appearances:
            issues.append(Issue(
                "medium", "On the map only",
                f"'{entity.name}' is on '{ref.map_name}' but no scene goes "
                f"there",
                "You drew it, so it matters to you. Either a scene wants to "
                "visit it, or the reader will never know it exists.",
                entity.name,
            ))

    # 3. Somewhere the book uses, that is not on any map ----------------
    drawn = set(index)
    for location in data.entities_of("location"):
        if location.id in drawn:
            continue
        if len(graph.scenes_with(location.id)) >= 3:
            issues.append(Issue(
                "low", "Not on the map",
                f"'{location.name}' appears in "
                f"{len(graph.scenes_with(location.id))} scenes but is not "
                f"pinned on any map",
                "Somewhere the story keeps returning to is usually worth "
                "putting on the map.",
                location.name,
            ))

    # 4. Travel that cannot have happened -------------------------------
    # Only checked where both places are pinned on the *same* map and that map
    # has a scale. Anything else and the distance is a guess, and a warning
    # built on a guess is worse than no warning.
    for state in chapter_states(project, graph):
        for presence in state.characters.values():
            if len(presence.route) < 2:
                continue
            previous, current = presence.route[-2], presence.route[-1]
            first, second = index.get(previous), index.get(current)
            if not first or not second or first.map_id != second.map_id:
                continue
            game_map = by_map.get(first.map_id)
            if game_map is None:
                continue
            gap = distance(game_map, first.pin, second.pin)
            if gap is None:
                continue
            scale = read_scale(game_map)
            if scale.astronomical:
                continue          # 300 miles means nothing between the stars
            miles = scale.to_miles(gap)
            if miles is None or miles < 300:
                continue
            here = data.entity(current)
            there = data.entity(previous)
            issues.append(Issue(
                "medium", "Travel",
                f"'{presence.name}' crosses "
                f"{describe_distance(game_map, first.pin, second.pin)} "
                f"in {state.chapter_title}",
                f"From {there.name if there else '?'} to "
                f"{here.name if here else '?'}. Worth checking the journey "
                f"has room to happen on the page.",
                presence.name,
            ))

    return issues


def summary_text(project, graph) -> str:
    """A short report on how well the maps and the manuscript agree."""
    maps = load_maps(project)
    if not maps:
        return ("No maps yet.\n\n"
                "Draw one with the Map Maker (Ctrl+M), link its pins to your "
                "locations, and this becomes a report on where your story "
                "actually goes.")

    index = pin_index(project, maps)
    states = chapter_states(project, graph)
    last = states[-1] if states else None
    lines = [
        "MAPS AND THE STORY",
        "=" * 62,
        f"{len(maps)} "
        f"{'map' if len(maps) == 1 else 'maps'}, "
        f"{sum(len(m.pins) for m in maps)} pins, "
        f"{len(index)} of them linked to a place in the project.",
        "",
    ]
    for game_map in maps:
        scale = read_scale(game_map)
        lines.append(
            f"  {game_map.name:<28s} {len(game_map.pins):>3} pins   "
            + (f"scale: {game_map.scale_text}" if scale.known
               else "no scale set")
        )
    lines.append("")
    if last:
        lines += [
            "-" * 62,
            "BY THE END OF THE BOOK",
            "-" * 62,
            "",
            f"  {len(last.visited)} locations are visited in a scene",
            f"  {len(last.mentioned_ever)} are named at least once",
            f"  {len(last.untouched)} are pinned but never mentioned",
            "",
        ]
        if last.characters:
            lines += ["  Where everyone finishes:", ""]
            for presence in sorted(last.characters.values(),
                                   key=lambda p: p.name):
                node = graph.nodes.get(presence.here)
                lines.append(f"    {presence.name:<26s} "
                             f"{node.name if node else '(nowhere named)'}"
                             f"   ({len(presence.route)} moves)")
            lines.append("")
    if not any(read_scale(m).known for m in maps):
        lines += [
            "-" * 62,
            "",
            "None of your maps has a scale caption, so travel distances",
            "cannot be checked. Set one in the Map Maker - 'Scale caption',",
            "something like '100 leagues' - and impossible journeys start",
            "being reported.",
            "",
        ]
    return "\n".join(lines)
