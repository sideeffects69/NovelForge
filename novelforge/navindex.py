"""
Go to...: everything the quick switcher can jump to, and how it is ranked.

The switcher is the "type three letters, press Enter" way round the book: a scene,
a chapter, a character or one of their aliases, a note, a timeline event, an outline
beat, a map, an idea. This module owns the *data* half - a flat list of targets built
from the manifest, a ranking, and the list of places visited last. The window that
shows it is `ui/goto.py`.

Nothing here opens a Word document or a file of any kind. Every target comes from
`project.json` (plus, for maps and loose documents, rows the binder already lists),
which is what keeps the box instant however long the novel is: rule 3 in CLAUDE.md.

Ranking reuses the command palette's scorer, so typing "sgraph" finds "Story Graph"
here exactly as it does there: a whole-word hit beats a mid-word hit beats letters
found in order, and an earlier hit beats a later one. On top of that, a match on the
title beats a match on a description, an exact title beats a partial one, and a
character beats a scene of the same name, because the person typing "ada" almost
always means Ada.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .model import ENTITY_LABELS, ENTITY_TYPES

#: Rows the switcher shows, and the last-visited list it opens with.
MAX_ROWS = 60
RECENT_LIMIT = 12

KIND_LABELS = {
    "scene": "Scene", "chapter": "Chapter", "note": "Note", "event": "Event",
    "beat": "Beat", "map": "Map", "doc": "Document", "idea": "Idea",
    **ENTITY_LABELS,
}

# A character beats a scene of the same name; everything else keeps its order.
_KIND_BIAS = {**{kind: 12 for kind in ENTITY_TYPES}, "chapter": 6,
              "event": 3, "beat": 3, "note": 3}

#: Operators the box understands (`status:draft pov:ada`). Anything else with a
#: colon is treated as plain text, so "re: the gate" still searches.
OPERATORS = ("kind", "type", "status", "pov", "tag", "in", "chapter")


# ==========================================================================
# Targets
# ==========================================================================


@dataclass(frozen=True)
class Target:
    """One thing the box can open. `key` is the binder row it selects."""

    key: str                        # "scene:scn_1", "entity:chr_2", "idea:idea_3"...
    kind: str                       # scene | chapter | character | ... | idea
    title: str
    subtitle: str = ""              # "Character - Protagonist", "Ch 1 - Draft"
    preview: str = ""               # synopsis / summary, shown under the list
    aliases: Tuple[str, ...] = ()
    attrs: Tuple[Tuple[str, str], ...] = ()     # for operators: status, pov, tag, in

    # Lower-cased once, here, instead of once per keystroke per target.
    names: Tuple[str, ...] = ()
    sub_text: str = ""
    preview_text: str = ""

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind.title())

    def attr(self, name: str) -> List[str]:
        return [v for k, v in self.attrs if k == name]


def make_target(key: str, kind: str, title: str, subtitle: str = "",
                preview: str = "", aliases: Sequence[str] = (),
                attrs: Sequence[Tuple[str, str]] = ()) -> Target:
    title = (title or "").strip() or "(untitled)"
    aliases = tuple(a.strip() for a in aliases if a and a.strip())
    label = KIND_LABELS.get(kind, kind.title())
    return Target(
        key=key, kind=kind, title=title, subtitle=subtitle, preview=preview,
        aliases=aliases,
        attrs=tuple((k, v) for k, v in attrs if v),
        names=tuple(n.lower() for n in (title, *aliases)),
        sub_text=f"{label} {subtitle}".lower(),
        preview_text=" ".join((preview or "").split()).lower(),
    )


def build_targets(project, extra: Iterable[Target] = ()) -> List[Target]:
    """
    Every target in the manifest, scenes in reading order first.

    `extra` carries what the manifest does not list - maps and loose documents,
    which the binder already knows about - so this module never touches the disk.
    """
    data = project.data
    out: List[Target] = []
    chapters = {c.id: c for c in data.chapters}
    entities = {e.id: e for e in data.entities}
    per_chapter = Counter(s.chapter_id for s in data.scenes)

    for chapter in data.ordered_chapters():
        count = per_chapter.get(chapter.id, 0)
        out.append(make_target(
            f"chapter:{chapter.id}", "chapter", chapter.title,
            f"{count} scene{'s' if count != 1 else ''}", chapter.synopsis,
            attrs=[("status", chapter.status)]))

    for scene in data.ordered_scenes():
        chapter = chapters.get(scene.chapter_id)
        pov = entities.get(scene.pov_id)
        where = chapter.title if chapter else ""
        # Status first: it is short, and a long chapter title is what gets trimmed.
        subtitle = f"{scene.status} - {where}" if where else scene.status
        attrs = [("status", scene.status), ("in", where),
                 ("pov", pov.name if pov else "")]
        attrs += [("tag", tag) for tag in getattr(scene, "tags", []) or []]
        out.append(make_target(f"scene:{scene.id}", "scene", scene.title, subtitle,
                               scene.synopsis, attrs=attrs))

    for entity in sorted(data.entities, key=lambda e: (e.type, e.order,
                                                        e.name.lower())):
        label = ENTITY_LABELS.get(entity.type, entity.type.title())
        subtitle = f"{label} - {entity.role}" if entity.role else label
        attrs = [("tag", tag) for tag in entity.tags or []]
        out.append(make_target(f"entity:{entity.id}", entity.type, entity.name,
                               subtitle, entity.summary, entity.aliases, attrs))

    for note in sorted(data.notes, key=lambda n: n.order):
        out.append(make_target(f"note:{note.id}", "note", note.title, note.kind))

    for event in sorted(data.events, key=lambda e: (e.sort_key, e.order)):
        subtitle = " - ".join(x for x in (event.story_date, event.kind) if x)
        out.append(make_target(f"event:{event.id}", "event", event.title, subtitle,
                               event.description))

    for beat in sorted(data.beats, key=lambda b: b.order):
        out.append(make_target(f"beat:{beat.key}", "beat", beat.name,
                               "Outline beat", beat.answer or beat.prompt))

    for idea in data.ideas:
        if idea.status == "discarded":
            continue
        out.append(make_target(f"idea:{idea.id}", "idea", idea.summary,
                               f"Idea - {idea.status}", idea.text,
                               attrs=[("tag", tag) for tag in idea.tags or []]))

    out.extend(extra)
    return out


# ==========================================================================
# Queries
# ==========================================================================

_TOKEN = re.compile(r'(\w+):"([^"]*)"|(\w+):(\S*)|"([^"]+)"|(\S+)')


@dataclass
class Query:
    tokens: List[str]                           # free words, lower-cased
    filters: List[Tuple[str, str]]              # (operator, value), lower-cased

    @property
    def empty(self) -> bool:
        return not self.tokens and not self.filters


def parse_query(text: str) -> Query:
    """
    Split a typed query into free words and `operator:value` filters.

        ada gate                 two words, both must match
        status:draft pov:ada     only drafts whose POV is Ada
        in:"the iron gate"       a quoted value may hold spaces
        kind:character           only characters

    A known operator with nothing after it yet ("status:") is ignored, so the list
    does not empty itself halfway through typing one. An unknown "word:" is just text.
    """
    tokens: List[str] = []
    filters: List[Tuple[str, str]] = []
    for m in _TOKEN.finditer((text or "").lower()):
        if m.group(1) is not None or m.group(3) is not None:
            key = m.group(1) if m.group(1) is not None else m.group(3)
            value = (m.group(2) if m.group(1) is not None else m.group(4)).strip()
            if key in OPERATORS:
                if value:
                    filters.append((key, value))
                continue
            tokens.append(m.group(0))
        elif m.group(5) is not None:
            tokens.extend(m.group(5).split())
        else:
            tokens.append(m.group(6))
    return Query(tokens, filters)


def tag_matches(tags: Iterable[str], wanted: str) -> bool:
    """`a` matches the tag `a` and every tag beneath it (`a/b`), never `ab`."""
    wanted = wanted.strip().strip("#").lower().strip("/")
    if not wanted:
        return False
    for tag in tags:
        tag = tag.strip().strip("#").lower().strip("/")
        if tag == wanted or tag.startswith(wanted + "/"):
            return True
    return False


def _passes(target: Target, filters: Sequence[Tuple[str, str]]) -> bool:
    for key, value in filters:
        if key in ("kind", "type"):
            if not (target.kind.startswith(value)
                    or target.label.lower().startswith(value)):
                return False
        elif key == "tag":
            if not tag_matches(target.attr("tag"), value):
                return False
        elif key in ("in", "chapter"):
            if not any(value in v.lower() for v in target.attr("in")):
                return False
        elif key == "pov":
            if not any(value in v.lower() for v in target.attr("pov")):
                return False
        elif key == "status":
            if not any(v.lower().startswith(value) for v in target.attr("status")):
                return False
    return True


def _default_scorer() -> Callable[[Sequence[str], str], Optional[int]]:
    # The palette's scorer, imported when first needed: this module is engine code
    # and should not pull the window toolkit in just to be imported.
    from .ui.palette import score

    return score


def _substring_score(tokens: Sequence[str], text: str) -> Optional[int]:
    """Every token must appear as-is; earlier is better. No fuzzy matching."""
    total = 0
    for token in tokens:
        at = text.find(token)
        if at < 0:
            return None
        starts_word = at == 0 or text[at - 1] in " .,;:-("
        total += 60 - min(at, 55) + (20 if starts_word else 0)
    return total


def score_target(target: Target, query: Query,
                 scorer: Optional[Callable] = None) -> Optional[int]:
    """How well a target matches, or None if it does not."""
    tokens = query.tokens
    if not tokens:
        return 0
    scorer = scorer or _default_scorer()
    best: Optional[int] = None

    # The title and each alias, scored on their own so an alias is as good as a name.
    for order, name in enumerate(target.names):
        value = scorer(tokens, name)
        if value is None:
            continue
        value *= 3
        joined = " ".join(tokens)
        if name == joined:
            value += 300 if order == 0 else 250
        elif name.startswith(joined):
            value += 100 if order == 0 else 80
        if order:
            value -= 5
        best = value if best is None else max(best, value)
    if best is not None:
        return best + _KIND_BIAS.get(target.kind, 0)

    # "scene draft", "character protagonist": the kind and subtitle line.
    value = scorer(tokens, target.sub_text)
    if value is not None:
        return value + _KIND_BIAS.get(target.kind, 0)

    # A word from the synopsis or summary. Whole words only, never fuzzy, and never
    # ahead of a title hit.
    value = _substring_score(tokens, target.preview_text)
    if value is not None:
        return value // 2
    return None


def rank(targets: Sequence[Target], text: str, limit: int = MAX_ROWS,
         scorer: Optional[Callable] = None) -> List[Target]:
    """
    The best `limit` targets for a typed query, best first.

    Ties keep the order they arrived in (reading order for scenes), so the list does
    not shuffle as more letters are typed.
    """
    query = parse_query(text)
    if query.empty:
        return []
    scorer = scorer or _default_scorer()
    filters = query.filters
    scored: List[Tuple[int, int, Target]] = []
    for order, target in enumerate(targets):
        if filters and not _passes(target, filters):
            continue
        value = score_target(target, query, scorer)
        if value is not None:
            scored.append((-value, order, target))
    scored.sort(key=lambda item: item[:2])
    return [target for _v, _o, target in scored[:limit]]


# ==========================================================================
# Recents
# ==========================================================================


class Recents:
    """The last places visited, newest first. Keys are binder rows ("scene:scn_1")."""

    def __init__(self, keys: Iterable[str] = (), limit: int = RECENT_LIMIT * 2) -> None:
        self.limit = limit
        self._keys: List[str] = []
        for key in keys:
            if isinstance(key, str) and key and key not in self._keys:
                self._keys.append(key)
        del self._keys[limit:]

    def push(self, key: str) -> bool:
        """Note a visit. Returns False if it was already the most recent."""
        if not key or key.endswith(":") or key.startswith("group:"):
            return False
        if self._keys[:1] == [key]:
            return False
        if key in self._keys:
            self._keys.remove(key)
        self._keys.insert(0, key)
        del self._keys[self.limit:]
        return True

    def keys(self) -> List[str]:
        return list(self._keys)

    def __len__(self) -> int:
        return len(self._keys)


def recent_targets(targets: Sequence[Target], recents: Sequence[str],
                   current: str = "", limit: int = RECENT_LIMIT) -> List[Target]:
    """
    What the box shows before anything is typed: the last places visited.

    The place you are in now is left out, so Ctrl+P then Enter hops back to the
    previous one - the same trick as Alt+Tab. With no history at all (a new novel)
    it offers the chapters and the first scenes, so the box is never empty.
    """
    by_key: Dict[str, Target] = {t.key: t for t in targets}
    shown = [by_key[k] for k in recents if k != current and k in by_key]
    if shown:
        return shown[:limit]
    fallback = [t for t in targets if t.kind == "chapter"][:4]
    fallback += [t for t in targets if t.kind == "scene"][:limit]
    return [t for t in fallback if t.key != current][:limit]
