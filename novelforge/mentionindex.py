"""
The mention index: which scenes name which characters, places and things.

Connections (see `backlinks.py`) needs one fact the manifest does not hold: where a
name appears in the prose. Finding out means opening the Word documents, which
takes seconds on a long novel, so it must never happen while a panel is being drawn
(rule 3 in CLAUDE.md). This module keeps the answer on disk, beside `project.json`,
in `mentions.json`:

    per scene   the document's modification time, how many times each entity is
                named (by name or alias), and where - up to twenty character
                offsets per entity, so a snippet can be cut later by reading just
                that one scene.

No prose is stored (rule 1: the .docx is the truth, and there is no second place
for prose to live). The file is derived data. Delete it and the worst outcome is
"not scanned yet" until the next scan; nothing is ever lost.

How it stays true without being slow:

  * `refresh()` re-reads only the scenes whose document changed since they were
    indexed - so a second scan of an unchanged novel opens nothing. It is an
    explicit command (`App.cmd_scan_mentions`, wrapped in `_busy`), never a timer.
  * `update_scene()` re-counts the scene being written, from the text already in
    hand when it is saved: one regex over one scene.
  * Every count depends on the whole cast (a new alias changes what a name is
    matched to), so the file also records a fingerprint of the names. When the
    cast's names change the index says so ("names changed - update") rather than
    quietly showing counts for a cast that no longer exists.

The counting is `storygraph`'s own (one combined pattern, longest name first), so
the two agree count for count: a test compares them.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import docxio, storygraph
from .atomic import read_json, write_json_atomic

MENTIONS_NAME = "mentions.json"
MAX_OFFSETS = 20
VERSION = 1
#: `update_scene` marks the index dirty; the file is rewritten at most this often
#: (and always by `flush`, which the app calls when the novel is closed).
WRITE_EVERY = 45.0


@dataclass
class SceneEntry:
    mtime: float = 0.0
    counts: Dict[str, int] = field(default_factory=dict)
    at: Dict[str, List[int]] = field(default_factory=dict)


@dataclass
class MentionIndex:
    names_key: str = ""
    scanned: float = 0.0                    # when a scan last finished (epoch seconds)
    scenes: Dict[str, SceneEntry] = field(default_factory=dict)
    # In memory only:
    file_mtime: float = 0.0
    dirty: bool = False
    last_write: float = 0.0

    @property
    def known(self) -> bool:
        """Has anything ever been scanned?"""
        return bool(self.scanned or self.scenes)


@dataclass
class Freshness:
    """How far the index has fallen behind the project."""

    scanned: float = 0.0
    names_changed: bool = False
    changed_scenes: int = 0                 # documents edited since they were indexed
    unscanned: bool = True                  # there is no index at all yet

    @property
    def current(self) -> bool:
        return not (self.unscanned or self.names_changed or self.changed_scenes)


# ==========================================================================
# Names -> a pattern (the same one the story graph uses)
# ==========================================================================

_COMPILED: Dict[str, Tuple[str, Dict[str, List[str]], Optional[re.Pattern]]] = {}


def names_key(lookup: Dict[str, List[str]]) -> str:
    """A fingerprint of every name and which entities answer to it."""
    blob = json.dumps(sorted((name, sorted(ids)) for name, ids in lookup.items()))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def _compiled(project) -> Tuple[str, Dict[str, List[str]], Optional[re.Pattern]]:
    """(fingerprint, name lookup, pattern) for the cast as it is now. Cached."""
    lookup = storygraph._build_name_lookup(project.data.entities)
    key = names_key(lookup)
    held = _COMPILED.get(str(project.root))
    if held and held[0] == key:
        return held
    built = (key, lookup, storygraph._mention_pattern(lookup))
    _COMPILED[str(project.root)] = built
    return built


def count_names(project, text: str) -> Dict[str, int]:
    """{entity id: times named} in any text at all - an event's description, say."""
    _key, lookup, pattern = _compiled(project)
    return scan_text(pattern, lookup, text)[0]


def scan_text(pattern: Optional[re.Pattern], lookup: Dict[str, List[str]],
              text: str) -> Tuple[Dict[str, int], Dict[str, List[int]]]:
    """Count the names in `text`: {entity: how many}, {entity: first offsets}."""
    counts: Counter = Counter()
    at: Dict[str, List[int]] = {}
    if pattern is None or not text:
        return {}, {}
    for match in pattern.finditer(text):
        for entity_id in lookup.get(match.group(1).lower(), []):
            counts[entity_id] += 1
            places = at.setdefault(entity_id, [])
            if len(places) < MAX_OFFSETS:
                places.append(match.start())
    return dict(counts), at


# ==========================================================================
# The file
# ==========================================================================

_INDEXES: Dict[str, MentionIndex] = {}


def path_for(project) -> Path:
    return Path(project.root) / MENTIONS_NAME


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _load(path: Path) -> MentionIndex:
    index = MentionIndex()
    raw = read_json(path) if path.exists() else None
    if not isinstance(raw, dict) or raw.get("version") != VERSION:
        return index
    index.names_key = str(raw.get("names_key", ""))
    try:
        index.scanned = float(raw.get("scanned", 0.0))
    except (TypeError, ValueError):
        index.scanned = 0.0
    scenes = raw.get("scenes")
    if isinstance(scenes, dict):
        for scene_id, row in scenes.items():
            if not isinstance(row, dict):
                continue
            try:
                counts = {str(k): int(v) for k, v in
                          (row.get("counts") or {}).items()}
                places = {str(k): [int(o) for o in v][:MAX_OFFSETS]
                          for k, v in (row.get("at") or {}).items()}
                index.scenes[str(scene_id)] = SceneEntry(
                    float(row.get("mtime", 0.0)), counts, places)
            except (TypeError, ValueError, AttributeError):
                continue                 # one bad row must not lose the others
    index.file_mtime = _mtime(path)
    return index


def get(project) -> MentionIndex:
    """
    The index for this project: from memory if we have it, else from the file.

    Reloaded if the file changed underneath us (another copy of the app, or a sync).
    """
    root = str(project.root)
    path = path_for(project)
    held = _INDEXES.get(root)
    if held is not None and (held.dirty or held.file_mtime == _mtime(path)):
        return held
    index = _load(path)
    _INDEXES[root] = index
    return index


def forget(project=None) -> None:
    """Drop the copy in memory (as a restart would). The file is left alone."""
    if project is None:
        _INDEXES.clear()
        _COMPILED.clear()
    else:
        _INDEXES.pop(str(project.root), None)
        _COMPILED.pop(str(project.root), None)


def save(project, index: Optional[MentionIndex] = None) -> None:
    index = index or get(project)
    payload: Dict[str, Any] = {
        "version": VERSION,
        "note": "Derived from your Word documents; safe to delete. No prose is stored.",
        "names_key": index.names_key,
        "scanned": index.scanned,
        "scenes": {
            scene_id: {"mtime": entry.mtime, "counts": entry.counts, "at": entry.at}
            for scene_id, entry in index.scenes.items()
        },
    }
    path = path_for(project)
    write_json_atomic(path, payload, indent=None)
    index.file_mtime = _mtime(path)
    index.dirty = False
    index.last_write = time.time()


def flush(project) -> None:
    """Write the index if `update_scene` changed it since it was last written."""
    held = _INDEXES.get(str(project.root))
    if held is not None and held.dirty:
        try:
            save(project, held)
        except OSError:
            pass                   # derived data: a failed write costs nothing


# ==========================================================================
# Keeping it true
# ==========================================================================


def _scene_mtime(project, scene) -> float:
    return docxio.docx_mtime(project.abs(scene.docx)) if scene.docx else 0.0


def freshness(project) -> Freshness:
    """
    How stale the index is, from `stat` calls alone (never a document open).

    Cheap enough to run every time a panel is drawn: one `stat` per scene.
    """
    index = get(project)
    if not index.known:
        return Freshness()
    key, _lookup, _pattern = _compiled(project)
    changed = 0
    for scene in project.data.scenes:
        entry = index.scenes.get(scene.id)
        if entry is None or entry.mtime != _scene_mtime(project, scene):
            changed += 1
    return Freshness(scanned=index.scanned, names_changed=index.names_key != key,
                     changed_scenes=changed, unscanned=False)


def refresh(project, progress: Optional[Callable[[int, int], None]] = None,
            force: bool = False) -> Tuple[int, int]:
    """
    Bring the index up to date. Returns (documents read, scenes in the book).

    Only scenes whose document changed are opened - so scanning an unchanged novel
    a second time reads nothing - unless the cast's names changed (every count
    depends on them) or `force` is set. A scene that cannot be read right now
    (locked by Word, still downloading from OneDrive) keeps its old entry rather
    than being recorded as having no mentions.
    """
    index = get(project)
    key, lookup, pattern = _compiled(project)
    if index.names_key != key:
        force = True
    scenes = list(project.data.scenes)
    total, read = len(scenes), 0
    for number, scene in enumerate(scenes):
        if progress is not None and (number % 5 == 0 or number == total - 1):
            try:
                progress(number + 1, total)
            except Exception:
                progress = None                 # a failing reporter must not stop it
        mtime = _scene_mtime(project, scene)
        entry = index.scenes.get(scene.id)
        if not force and entry is not None and entry.mtime == mtime:
            continue
        text = ""
        if scene.docx and mtime:
            text = docxio.read_prose(project.abs(scene.docx))
            if not text and not docxio.prose_readable(project.abs(scene.docx)):
                continue                        # unreadable, not empty: keep what we had
            read += 1
        counts, places = scan_text(pattern, lookup, text)
        index.scenes[scene.id] = SceneEntry(mtime, counts, places)
    live = {s.id for s in scenes}
    for gone in [k for k in index.scenes if k not in live]:
        del index.scenes[gone]
    index.names_key = key
    index.scanned = time.time()
    save(project, index)
    return read, total


def update_scene(project, scene_id: str, text: str) -> bool:
    """
    Re-count one scene from `text` (what was just saved). One regex, no reading.

    Returns False, changing nothing, when there is no index yet or the cast's names
    have changed since it was built: a count made against a different cast would
    sit next to counts made against the old one. A scan sorts that out.
    """
    try:
        index = get(project)
        scene = project.data.scene(scene_id)
        if scene is None or not index.known:
            return False
        key, lookup, pattern = _compiled(project)
        if index.names_key != key:
            return False
        counts, places = scan_text(pattern, lookup, text)
        index.scenes[scene_id] = SceneEntry(_scene_mtime(project, scene), counts,
                                            places)
        index.dirty = True
        if time.time() - index.last_write >= WRITE_EVERY:
            flush(project)
        return True
    except Exception:
        # Derived data: whatever goes wrong here must never get in the way of
        # saving the writer's prose, which has already been written by now.
        return False


# ==========================================================================
# Reading it
# ==========================================================================


def mention_counts(project, graph=None) -> Tuple[Dict[str, Dict[str, int]], str]:
    """
    {scene id: {entity id: times named}}, and where the numbers came from.

    A current story graph is the freshest source there is (it is checked against the
    files' modification times every time it is asked for), so it wins; else the
    index; else nothing. Never opens a document.
    """
    if graph is not None:
        table: Dict[str, Dict[str, int]] = {}
        for edge in graph.edges:
            if edge.kind == "mentions":
                table.setdefault(edge.source, {})[edge.target] = edge.weight
        return table, "graph"
    index = get(project)
    if not index.known:
        return {}, "none"
    return ({sid: dict(e.counts) for sid, e in index.scenes.items() if e.counts},
            "index")


def snippet(project, scene_id: str, entity_id: str, graph=None,
            width: int = 64) -> str:
    """
    A line of the scene around one mention of an entity, cut from the prose.

    This is the one place a document is opened, and only on a click: it reads a
    single scene (or none, if a current story graph already holds the text).
    """
    scene = project.data.scene(scene_id)
    entity = project.data.entity(entity_id)
    if scene is None or entity is None:
        return ""
    if graph is not None and scene_id in graph.scene_text:
        text = graph.scene_text[scene_id]
    else:
        text = project.scene_text(scene_id)
    if not text:
        return ""
    _key, lookup, pattern = _compiled(project)
    entry = get(project).scenes.get(scene_id)
    start = -1
    if pattern is not None:
        # Trust a stored offset only if a name really starts there now.
        for offset in (entry.at.get(entity_id, []) if entry else []):
            found = pattern.match(text, offset)
            if found and entity_id in lookup.get(found.group(1).lower(), []):
                start, length = offset, len(found.group(1))
                break
        else:
            for found in pattern.finditer(text):
                if entity_id in lookup.get(found.group(1).lower(), []):
                    start, length = found.start(), len(found.group(1))
                    break
    if start < 0:
        return ""
    left = max(0, start - width)
    right = min(len(text), start + length + width)
    line = " ".join(text[left:right].split())
    return ("..." if left else "") + line + ("..." if right < len(text) else "")
