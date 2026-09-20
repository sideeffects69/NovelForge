"""
Scene tags: free-form labels a writer puts on a scene, nested with a slash.

    clue            a plain tag
    clue/red-herring   a tag inside another: searching for `clue` finds both

This is Obsidian's rule for nested tags and the only rule that matters here: a tag
matches itself and everything beneath it, never a look-alike (`clue` does not match
`clueless`). Matching ignores case; a tag keeps the spelling it was typed with.

Tags live on `Scene.tags` in the manifest. This module is the small amount of logic
around them - turning what was typed into a clean list, and matching - so the
inspector, Go to and the Scene Table all agree on what a tag is.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List

MAX_LENGTH = 60
_SPLIT = re.compile(r"[,;\n]+")


def clean(tag: str) -> str:
    """One tag as it is stored: no `#`, no spaces (they become `-`), no stray slashes."""
    tag = (tag or "").strip().lstrip("#").strip()
    tag = re.sub(r"\s+", "-", tag)
    tag = re.sub(r"/{2,}", "/", tag).strip("/")
    return tag[:MAX_LENGTH].rstrip("/")


def parse(text: str) -> List[str]:
    """
    A typed line ("clue, a/b; #red herring") as a clean list, without repeats.

    A repeat is the same tag in another case: `Clue` after `clue` is dropped.
    """
    seen, out = set(), []
    for piece in _SPLIT.split(text or ""):
        tag = clean(piece)
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            out.append(tag)
    return out


def format(tags: Iterable[str]) -> str:
    """A list of tags as one editable line."""
    return ", ".join(t for t in (tags or []) if t)


def matches(tags: Iterable[str], wanted: str) -> bool:
    """Does any of `tags` equal `wanted` or sit beneath it (`a` matches `a/b`)?"""
    wanted = clean(wanted).lower()
    if not wanted:
        return False
    for tag in tags or []:
        tag = clean(tag).lower()
        if tag == wanted or tag.startswith(wanted + "/"):
            return True
    return False


def all_tags(scenes: Iterable[Any]) -> List[str]:
    """Every distinct tag in use, sorted: what an auto-complete would offer."""
    found = {}
    for scene in scenes:
        for tag in getattr(scene, "tags", None) or []:
            found.setdefault(tag.lower(), tag)
    return sorted(found.values(), key=str.lower)


class TagsField:
    """
    Lets an ordinary text field in the inspector edit a list of tags.

    `Form.entry` reads and writes a *string* attribute. This stands in for the
    scene: reading `.tags` gives the tags as one comma-separated line, and writing it
    parses what was typed back into the scene's list. Nothing about the form itself
    has to know tags exist.
    """

    def __init__(self, scene: Any) -> None:
        object.__setattr__(self, "_scene", scene)

    @property
    def tags(self) -> str:
        return format(self._scene.tags)

    @tags.setter
    def tags(self, value: str) -> None:
        self._scene.tags = parse(value)
