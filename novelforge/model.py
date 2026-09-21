"""
The project data model.

Prose and long-form answers live in Word documents. This module holds the
*metadata* around them: ordering, links between entities, statistics, targets
and status. Keeping the two separate means you can rename a character in Word
without the tool losing track of which scenes they appear in.

Entities are stored as flat lists with an `order` integer rather than a nested
tree, which makes reordering and reparenting a single field change.
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Type, TypeVar

# --------------------------------------------------------------------------
# Vocabularies
# --------------------------------------------------------------------------

SCENE_STATUSES = ["Outline", "Draft", "Revised", "Needs Work", "Final"]

STATUS_COLOURS = {
    "Outline": "#9a9a9a",
    "Draft": "#c08a3e",
    "Revised": "#4f7fa8",
    "Needs Work": "#b1544a",
    "Final": "#4f8a5b",
}

ENTITY_TYPES = ["character", "location", "item", "faction", "thread"]

ENTITY_LABELS = {
    "character": "Character",
    "location": "Location",
    "item": "Item",
    "faction": "Faction",
    "thread": "Plot Thread",
}

ENTITY_PLURAL = {
    "character": "Characters",
    "location": "Locations",
    "item": "Items",
    "faction": "Factions",
    "thread": "Plot Threads",
}

CHARACTER_ROLES = [
    "Protagonist", "Antagonist", "Deuteragonist", "Love interest", "Mentor",
    "Ally", "Foil", "Rival", "Threshold guardian", "Trickster",
    "Supporting", "Walk-on",
]

SCENE_TYPES = ["scene", "sequel"]

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

T = TypeVar("T")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def today_iso() -> str:
    return date.today().isoformat()


def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
    """
    Build a dataclass from a dict, ignoring unknown keys.

    Forward compatibility: a manifest written by a newer version with extra
    fields still loads here instead of raising TypeError.
    """
    known = {f.name for f in dataclasses.fields(cls)}  # type: ignore[arg-type]
    return cls(**{k: v for k, v in data.items() if k in known})  # type: ignore[call-arg]


def to_dict(obj: Any) -> Dict[str, Any]:
    return dataclasses.asdict(obj)


# --------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------


@dataclass
class Entity:
    """
    A character, location, item, faction or plot thread.

    One shape for all five because they differ only in which template built
    their document. `cache` holds the last-read field values from that document
    so the binder and inspector can show details without reopening the file.
    """

    id: str = ""
    type: str = "character"
    name: str = ""
    docx: str = ""              # path relative to the project root
    order: int = 0
    role: str = ""              # narrative role, or thread/faction type
    summary: str = ""           # one line shown in the binder
    is_pov: bool = False
    color: str = ""
    tags: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    cache: Dict[str, str] = field(default_factory=dict)
    cache_mtime: float = 0.0
    created: str = field(default_factory=now_iso)
    modified: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id(self.type[:4])

    @property
    def display(self) -> str:
        return self.name or "(untitled)"

    def all_names(self) -> List[str]:
        """
        Every string that plausibly refers to this entity.

        Prose says "Ada", not "Ada Vane", so the full name alone finds almost
        nothing. Individual name parts and alias parts are included too.
        Returned longest-first so a regex alternation prefers "Ada Vane" over
        the bare "Ada" and counts one mention rather than two.
        """
        particles = {"the", "and", "of", "or", "a", "an", "de", "la", "le",
                     "van", "von", "der", "den", "bin", "al"}
        unique: Dict[str, str] = {}

        def offer(raw: str, is_whole_name: bool = False) -> None:
            cleaned = (raw or "").strip(" ,.;:'\"()[]")
            if not cleaned:
                return
            # The length and particle filters exist to stop a fragment like
            # "Al" or "the" matching half the manuscript. They must not apply
            # to a whole name, or a character called "Al" would be unfindable.
            if not is_whole_name:
                if len(cleaned) < 3 or cleaned.lower() in particles:
                    return
            unique.setdefault(cleaned.lower(), cleaned)

        offer(self.name, is_whole_name=True)
        for part in self.name.split():
            offer(part)
        for alias in self.aliases:
            offer(alias, is_whole_name=True)
            for part in alias.split():
                offer(part)
        return sorted(unique.values(), key=len, reverse=True)


@dataclass
class Scene:
    """A unit of prose. The manuscript is an ordered list of these."""

    id: str = ""
    title: str = ""
    docx: str = ""
    chapter_id: str = ""
    order: int = 0

    synopsis: str = ""
    status: str = "Outline"
    scene_type: str = "scene"       # scene (goal/conflict/disaster) or sequel
    label: str = ""

    # Free-form labels, nested with a slash (clue/red-herring); a search for
    # "clue" finds both. Edited in the inspector; see tags.py.
    tags: List[str] = field(default_factory=list)

    # links
    pov_id: str = ""
    character_ids: List[str] = field(default_factory=list)
    location_ids: List[str] = field(default_factory=list)
    item_ids: List[str] = field(default_factory=list)
    faction_ids: List[str] = field(default_factory=list)
    thread_ids: List[str] = field(default_factory=list)
    beat_key: str = ""

    # scene / sequel structure
    goal: str = ""
    conflict: str = ""
    disaster: str = ""
    reaction: str = ""
    dilemma: str = ""
    decision: str = ""

    # value shift - the reverse outliner reads these
    value_start: str = ""
    value_end: str = ""

    # chronology
    story_date: str = ""
    time_span: str = ""

    # counts
    word_count: int = 0
    target_words: int = 0
    include_in_compile: bool = True

    # Branching drafts. `docx` is always the live file, so compiling, reading
    # and word counts never need to know which branch is current. Switching
    # copies the live file out to the named branch and the target branch in.
    # That keeps every other code path in the project untouched.
    active_draft: str = "Main"
    drafts: List[str] = field(default_factory=list)

    notes: str = ""
    docx_mtime: float = 0.0
    created: str = field(default_factory=now_iso)
    modified: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id("scn")

    @property
    def display(self) -> str:
        return self.title or "(untitled scene)"

    @property
    def status_colour(self) -> str:
        return STATUS_COLOURS.get(self.status, "#9a9a9a")


@dataclass
class Chapter:
    id: str = ""
    title: str = ""
    order: int = 0
    part: str = ""                  # optional Part/Book grouping
    synopsis: str = ""
    status: str = "Outline"
    number_in_compile: bool = True  # emit "Chapter N" heading
    include_in_compile: bool = True
    folder: str = ""                # relative folder holding its scene files
    notes: str = ""
    created: str = field(default_factory=now_iso)
    modified: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id("chp")

    @property
    def display(self) -> str:
        return self.title or "(untitled chapter)"


@dataclass
class Beat:
    """One beat of the chosen structural framework, as instantiated in a project."""

    key: str = ""
    name: str = ""
    pct: Optional[float] = None
    prompt: str = ""
    answer: str = ""                # what the writer plans for this beat
    scene_ids: List[str] = field(default_factory=list)
    done: bool = False
    order: int = 0

    def target_word(self, total: int) -> Optional[int]:
        if self.pct is None or not total:
            return None
        return int(round(self.pct * total))


@dataclass
class TimelineEvent:
    id: str = ""
    title: str = ""
    story_date: str = ""            # in-world date as the writer writes it
    sort_key: float = 0.0           # numeric ordering, independent of format
    description: str = ""
    kind: str = "event"             # event | birth | death | reveal | backstory
    character_ids: List[str] = field(default_factory=list)
    location_id: str = ""
    scene_id: str = ""
    on_page: bool = True            # does the reader witness it?
    order: int = 0

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id("evt")


@dataclass
class Note:
    id: str = ""
    title: str = ""
    docx: str = ""
    kind: str = "note"              # note | research | scratchpad
    order: int = 0
    #: Ids of scenes, characters, locations - anything this note is research
    #: *for*. A note nobody can find from the thing it explains may as well not
    #: exist, which is the failing of every folder-based research pile.
    links: List[str] = field(default_factory=list)
    created: str = field(default_factory=now_iso)
    modified: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id("not")


@dataclass
class Idea:
    """
    A thought caught before it escaped.

    The whole value is in capturing without deciding, so this has no required
    fields beyond the text itself. Deciding where it belongs happens later, in
    the inbox, with the tool offering suggestions.
    """

    id: str = ""
    text: str = ""
    status: str = "new"             # new | placed | kept | discarded
    target_id: str = ""             # where it was filed, once it was
    tags: List[str] = field(default_factory=list)
    created: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id("idea")

    @property
    def summary(self) -> str:
        flat = " ".join(self.text.split())
        return flat[:70] + ("..." if len(flat) > 70 else "")


@dataclass
class Session:
    """
    One writing session, for statistics and streaks.

    `words_net` can be negative on a revision day - that is real information,
    so it is recorded rather than clamped. `words_added` counts only growth,
    which is what a daily target should be measured against.
    """

    date: str = field(default_factory=today_iso)
    started: str = field(default_factory=now_iso)
    ended: str = ""
    minutes: float = 0.0
    words_start: int = 0
    words_end: int = 0
    words_added: int = 0            # sum of positive deltas
    words_deleted: int = 0          # sum of negative deltas, as a positive number
    scenes_touched: List[str] = field(default_factory=list)
    block_type: str = ""            # from the diagnostic, if run
    note: str = ""

    @property
    def words_net(self) -> int:
        return self.words_end - self.words_start


@dataclass
class Targets:
    total_words: int = 90000
    daily_words: int = 1000
    deadline: str = ""              # ISO date, or empty
    session_words: int = 500


# --------------------------------------------------------------------------
# The project manifest
# --------------------------------------------------------------------------


@dataclass
class ProjectData:
    """Everything the manifest holds. Serialised to project.json."""

    schema_version: int = 1
    id: str = ""
    title: str = "Untitled Novel"
    subtitle: str = ""
    author: str = ""
    author_surname: str = ""
    series: str = ""
    book_number: int = 0
    genre: str = ""
    logline: str = ""
    pov_style: str = "Third limited"
    tense: str = "Past"
    structure: str = "three_act"

    targets: Targets = field(default_factory=Targets)

    # Beat answers keyed "framework:beat_key". Switching structural frameworks
    # rebuilds `beats` from scratch, and frameworks do not share beat keys, so
    # without this an experiment with Save the Cat would discard everything
    # typed against Three-Act. Nothing here is ever deleted automatically.
    beat_archive: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    chapters: List[Chapter] = field(default_factory=list)
    scenes: List[Scene] = field(default_factory=list)
    entities: List[Entity] = field(default_factory=list)
    beats: List[Beat] = field(default_factory=list)
    events: List[TimelineEvent] = field(default_factory=list)
    notes: List[Note] = field(default_factory=list)
    sessions: List[Session] = field(default_factory=list)
    ideas: List[Idea] = field(default_factory=list)
    #: Invented words the writer has accepted - place names, magic terms,
    #: anything the general language would call a mistake. This is how the
    #: tool learns your world instead of arguing with it.
    accepted_words: List[str] = field(default_factory=list)

    created: str = field(default_factory=now_iso)
    modified: str = field(default_factory=now_iso)
    opened: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id("prj")

    # -- serialisation --------------------------------------------------
    def to_json(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "author": self.author,
            "author_surname": self.author_surname,
            "series": self.series,
            "book_number": self.book_number,
            "genre": self.genre,
            "logline": self.logline,
            "pov_style": self.pov_style,
            "tense": self.tense,
            "structure": self.structure,
            "targets": to_dict(self.targets),
            "beat_archive": self.beat_archive,
            "chapters": [to_dict(c) for c in self.chapters],
            "scenes": [to_dict(s) for s in self.scenes],
            "entities": [to_dict(e) for e in self.entities],
            "beats": [to_dict(b) for b in self.beats],
            "events": [to_dict(e) for e in self.events],
            "notes": [to_dict(n) for n in self.notes],
            "sessions": [to_dict(s) for s in self.sessions],
            "ideas": [to_dict(i) for i in self.ideas],
            "accepted_words": list(self.accepted_words),
            "created": self.created,
            "modified": self.modified,
            "opened": self.opened,
        }

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "ProjectData":
        obj = from_dict(cls, {k: v for k, v in data.items()
                              if k not in {"targets", "chapters", "scenes",
                                           "entities", "beats", "events",
                                           "notes", "sessions", "ideas"}})
        # Type-check each container, not just truthiness: a manifest that a
        # sync conflict or a hand edit turned into the wrong shape must degrade
        # to "no chapters" rather than raise on start-up.
        def rows(key: str) -> List[Dict[str, Any]]:
            value = data.get(key)
            if not isinstance(value, list):
                return []
            return [item for item in value if isinstance(item, dict)]

        targets = data.get("targets")
        obj.targets = from_dict(Targets, targets if isinstance(targets, dict) else {})
        archive = data.get("beat_archive")
        obj.beat_archive = dict(archive) if isinstance(archive, dict) else {}
        obj.chapters = [from_dict(Chapter, d) for d in rows("chapters")]
        obj.scenes = [from_dict(Scene, d) for d in rows("scenes")]
        obj.entities = [from_dict(Entity, d) for d in rows("entities")]
        obj.beats = [from_dict(Beat, d) for d in rows("beats")]
        obj.events = [from_dict(TimelineEvent, d) for d in rows("events")]
        obj.notes = [from_dict(Note, d) for d in rows("notes")]
        obj.sessions = [from_dict(Session, d) for d in rows("sessions")]
        obj.ideas = [from_dict(Idea, d) for d in rows("ideas")]
        return obj

    # -- lookups --------------------------------------------------------
    def scene(self, scene_id: str) -> Optional[Scene]:
        return next((s for s in self.scenes if s.id == scene_id), None)

    def chapter(self, chapter_id: str) -> Optional[Chapter]:
        return next((c for c in self.chapters if c.id == chapter_id), None)

    def entity(self, entity_id: str) -> Optional[Entity]:
        return next((e for e in self.entities if e.id == entity_id), None)

    def note(self, note_id: str) -> Optional[Note]:
        return next((n for n in self.notes if n.id == note_id), None)

    def idea(self, idea_id: str) -> Optional[Idea]:
        return next((i for i in self.ideas if i.id == idea_id), None)

    def open_ideas(self) -> List[Idea]:
        return [i for i in self.ideas if i.status == "new"]

    def beat(self, key: str) -> Optional[Beat]:
        return next((b for b in self.beats if b.key == key), None)

    def entities_of(self, entity_type: str) -> List[Entity]:
        return sorted(
            (e for e in self.entities if e.type == entity_type),
            key=lambda e: (e.order, e.name.lower()),
        )

    def ordered_chapters(self) -> List[Chapter]:
        return sorted(self.chapters, key=lambda c: c.order)

    def scenes_in(self, chapter_id: str) -> List[Scene]:
        return sorted(
            (s for s in self.scenes if s.chapter_id == chapter_id),
            key=lambda s: s.order,
        )

    def ordered_scenes(self) -> List[Scene]:
        """Every scene in reading order, following chapter order."""
        out: List[Scene] = []
        for chapter in self.ordered_chapters():
            out.extend(self.scenes_in(chapter.id))
        # Orphans (no chapter, or a chapter that was deleted) go last so they
        # are visible rather than silently dropped.
        known = {c.id for c in self.chapters}
        orphans = [s for s in self.scenes if s.chapter_id not in known]
        out.extend(sorted(orphans, key=lambda s: s.order))
        return out

    def compile_scenes(self) -> List[Scene]:
        included_chapters = {c.id for c in self.chapters if c.include_in_compile}
        return [
            s for s in self.ordered_scenes()
            if s.include_in_compile and s.chapter_id in included_chapters
        ]

    # -- statistics -----------------------------------------------------
    @property
    def word_count(self) -> int:
        return sum(s.word_count for s in self.scenes)

    @property
    def compiled_word_count(self) -> int:
        return sum(s.word_count for s in self.compile_scenes())

    def next_order(self, items: List[Any]) -> int:
        return max((getattr(i, "order", 0) for i in items), default=-1) + 1

    def session_for_today(self) -> Optional[Session]:
        today = today_iso()
        return next((s for s in reversed(self.sessions) if s.date == today), None)

    def touch(self) -> None:
        self.modified = now_iso()
