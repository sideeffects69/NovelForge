"""
Connections: everything that leads to, or from, the thing you are looking at.

Obsidian shows a note's *linked* mentions (notes that `[[link]]` to it) and its
*unlinked* mentions (its name written out somewhere with no link), each with a
one-click "link". NovelForge already knows both halves - the links a writer sets in
the inspector, and the names it can find in the prose - but showed only a bare
"Linked scenes: 12" and a "Where mentioned?" button that opened a report. This module
produces the two halves as data, for the panel in `ui/connections.py` to draw:

    Linked                  declared in the inspector (POV, present, locations...),
                            from the manifest
    Mentioned, not linked   the name is in the prose but no link was made: each row
                            can be linked in one undoable step
    Research                notes attached to it
    Timeline                events that cover it, or are about it
    Outline                 beats that cover a scene

Where the prose is concerned this never opens a Word document. Mentions come from a
current story graph if one is passed in, else from the persisted index
(`mentionindex.py`); a click on a row later reads one scene to cut a snippet. So
building a panel costs the same in a three-hundred-scene novel as in a three-scene one.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from . import mentionindex, storygraph
from .model import ENTITY_LABELS, now_iso

#: Sections, in the order the panel shows them.
SECTION_TITLES = {
    "linked": "Linked",
    "unlinked": "Mentioned, not linked",
    "research": "Research",
    "timeline": "Timeline",
    "outline": "Outline",
}

#: Which list on a scene each kind of entity is linked through.
_SCENE_LISTS = {"character": "character_ids", "location": "location_ids",
                "item": "item_ids", "faction": "faction_ids",
                "thread": "thread_ids"}


@dataclass
class Row:
    """One line in the panel. `kind` and `id` are the binder row it jumps to."""

    kind: str                   # scene | entity | note | event | beat | chapter
    id: str
    title: str
    detail: str = ""            # "POV", "Character", "named 3x"
    count: int = 0              # times named, for a mentioned-but-not-linked row
    # A row that can be linked says what to link, and into what.
    link_kind: str = ""         # "scene" or "event"; "" means there is no button
    link_target: str = ""       # the scene or event that would gain the link
    entity_id: str = ""         # the character, place... that would be linked

    @property
    def iid(self) -> str:
        return f"{self.kind}:{self.id}"

    @property
    def can_link(self) -> bool:
        return bool(self.link_kind and self.link_target and self.entity_id)


@dataclass
class Section:
    key: str
    rows: List[Row] = field(default_factory=list)

    @property
    def title(self) -> str:
        return SECTION_TITLES[self.key]


@dataclass
class Connections:
    kind: str
    id: str
    name: str
    sections: List[Section] = field(default_factory=list)
    source: str = "none"                    # graph | index | none
    freshness: mentionindex.Freshness = field(
        default_factory=mentionindex.Freshness)

    def section(self, key: str) -> Optional[Section]:
        return next((s for s in self.sections if s.key == key), None)

    def rows(self, key: str) -> List[Row]:
        found = self.section(key)
        return found.rows if found else []

    @property
    def total(self) -> int:
        return sum(len(s.rows) for s in self.sections)


# ==========================================================================
# Building
# ==========================================================================


def _declared(scene) -> Set[str]:
    return storygraph._declared_ids(scene)


def connections(project, kind: str, ident: str, graph=None) -> Connections:
    """
    The connections of a scene, an entity (character, place, item...), a note or a
    timeline event. `kind` is the binder's own: "scene", "entity", "note", "event".

    Pass a current story graph as `graph` if one is to hand; otherwise mentions come
    from the persisted index. Either way no document is opened.
    """
    data = project.data
    result = Connections(kind, ident, "")
    if graph is not None:
        result.source = "graph"
        result.freshness = mentionindex.Freshness(
            scanned=time.time(), unscanned=False)
        counts, _src = mentionindex.mention_counts(project, graph)
    else:
        counts, result.source = mentionindex.mention_counts(project)
        result.freshness = mentionindex.freshness(project)

    if kind == "scene" and data.scene(ident):
        _for_scene(project, data.scene(ident), counts, result)
    elif kind == "entity" and data.entity(ident):
        _for_entity(project, data.entity(ident), counts, result)
    elif kind == "note" and data.note(ident):
        _for_note(project, data.note(ident), result)
    elif kind == "event" and any(e.id == ident for e in data.events):
        _for_event(project, next(e for e in data.events if e.id == ident), result)
    return result


def _add(result: Connections, key: str, rows: List[Row]) -> None:
    if rows:
        result.sections.append(Section(key, rows))


def _for_scene(project, scene, counts, result: Connections) -> None:
    data = project.data
    result.name = scene.title
    declared = _declared(scene)

    linked: List[Row] = []
    seen: Set[str] = set()
    ordered = ([scene.pov_id] + scene.character_ids + scene.location_ids
               + scene.item_ids + scene.faction_ids + scene.thread_ids)
    for entity_id in ordered:
        entity = data.entity(entity_id) if entity_id else None
        if entity is None or entity_id in seen:
            continue                            # a dangling id is the continuity check's job
        seen.add(entity_id)
        detail = "POV" if entity_id == scene.pov_id else ENTITY_LABELS.get(
            entity.type, entity.type.title())
        linked.append(Row("entity", entity.id, entity.name, detail))
    _add(result, "linked", linked)

    mentioned = []
    for entity_id, n in (counts.get(scene.id) or {}).items():
        entity = data.entity(entity_id)
        if entity is None or entity_id in declared or n <= 0:
            continue
        if entity.type not in _SCENE_LISTS:
            continue
        mentioned.append(Row("entity", entity.id, entity.name, f"named {n}x",
                             count=n, link_kind="scene", link_target=scene.id,
                             entity_id=entity.id))
    mentioned.sort(key=lambda r: (-r.count, r.title.lower()))
    _add(result, "unlinked", mentioned)

    _add(result, "research", [Row("note", n.id, n.title, n.kind)
                              for n in project.notes_for(scene.id)])
    _add(result, "timeline", [Row("event", e.id, e.title or "(untitled)",
                                  e.story_date)
                              for e in project.ordered_events()
                              if e.scene_id == scene.id])
    _add(result, "outline", [Row("beat", b.key, b.name, "covers this scene")
                             for b in sorted(data.beats, key=lambda b: b.order)
                             if scene.id in b.scene_ids])


def _for_entity(project, entity, counts, result: Connections) -> None:
    data = project.data
    result.name = entity.name
    role = {"character": "present", "location": "set here", "item": "appears",
            "faction": "involved", "thread": "runs through"}.get(entity.type, "")

    linked: List[Row] = []
    mentioned: List[Row] = []
    for scene in data.ordered_scenes():
        if entity.id == scene.pov_id:
            linked.append(Row("scene", scene.id, scene.title, "POV"))
        elif entity.id in _declared(scene):
            linked.append(Row("scene", scene.id, scene.title, role))
        else:
            n = (counts.get(scene.id) or {}).get(entity.id, 0)
            if n > 0 and entity.type in _SCENE_LISTS:
                mentioned.append(Row(
                    "scene", scene.id, scene.title, f"named {n}x", count=n,
                    link_kind="scene", link_target=scene.id, entity_id=entity.id))
    _add(result, "linked", linked)
    _add(result, "unlinked", mentioned)

    _add(result, "research", [Row("note", n.id, n.title, n.kind)
                              for n in project.notes_for(entity.id)])
    _add(result, "timeline", [Row("event", e.id, e.title or "(untitled)",
                                  e.story_date)
                              for e in project.ordered_events()
                              if entity.id in e.character_ids
                              or e.location_id == entity.id])


def _for_note(project, note, result: Connections) -> None:
    data = project.data
    result.name = note.title
    linked: List[Row] = []
    for target in note.links or []:
        entity, scene, chapter = data.entity(target), data.scene(target), \
            data.chapter(target)
        if entity:
            linked.append(Row("entity", entity.id, entity.name,
                              ENTITY_LABELS.get(entity.type, entity.type.title())))
        elif scene:
            linked.append(Row("scene", scene.id, scene.title, "Scene"))
        elif chapter:
            linked.append(Row("chapter", chapter.id, chapter.title, "Chapter"))
    _add(result, "linked", linked)


def _for_event(project, event, result: Connections) -> None:
    data = project.data
    result.name = event.title or "(untitled)"
    linked: List[Row] = []
    scene = data.scene(event.scene_id) if event.scene_id else None
    if scene:
        linked.append(Row("scene", scene.id, scene.title, "covers"))
    for entity_id in event.character_ids:
        entity = data.entity(entity_id)
        if entity:
            linked.append(Row("entity", entity.id, entity.name, "about"))
    place = data.entity(event.location_id) if event.location_id else None
    if place:
        linked.append(Row("entity", place.id, place.name, "at"))
    _add(result, "linked", linked)

    # An event's own words are in the manifest, so this half needs no index at all.
    named = mentionindex.count_names(
        project, f"{event.title}. {event.description}")
    mentioned = []
    for entity_id, n in named.items():
        entity = data.entity(entity_id)
        if entity is None or entity_id in event.character_ids \
                or entity_id == event.location_id:
            continue
        if entity.type == "character" or (
                entity.type == "location" and not event.location_id):
            mentioned.append(Row(
                "entity", entity.id, entity.name, f"named {n}x", count=n,
                link_kind="event", link_target=event.id, entity_id=entity.id))
    mentioned.sort(key=lambda r: (-r.count, r.title.lower()))
    _add(result, "unlinked", mentioned)


# ==========================================================================
# Linking
# ==========================================================================


def link_mention(project, kind: str, target_id: str, entity_id: str) -> bool:
    """
    Turn a mention into a link: add the entity to the scene's Present / Locations /
    Items... list, or (for a timeline event) to its characters or its place.

    One undoable step through `project.action` - Ctrl+Z takes it back. Returns False,
    changing nothing, when there is nothing to do (already linked, wrong kind).
    """
    data = project.data
    entity = data.entity(entity_id)
    if entity is None:
        return False
    if kind == "scene":
        scene = data.scene(target_id)
        attr = _SCENE_LISTS.get(entity.type)
        if scene is None or attr is None:
            return False
        if entity_id == scene.pov_id or entity_id in getattr(scene, attr):
            return False
        with project.action("Link mention"):
            getattr(scene, attr).append(entity_id)
            scene.modified = now_iso()
            project.mark_dirty()
        return True
    if kind == "event":
        event = next((e for e in data.events if e.id == target_id), None)
        if event is None:
            return False
        if entity.type == "character" and entity_id not in event.character_ids:
            with project.action("Link mention"):
                event.character_ids.append(entity_id)
                project.mark_dirty()
            return True
        if entity.type == "location" and not event.location_id:
            with project.action("Link mention"):
                event.location_id = entity_id
                project.mark_dirty()
            return True
    return False
