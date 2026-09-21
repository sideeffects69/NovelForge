"""
The map generators the Map Maker can offer, and how to ask each one for a map.

Every generator module (mapdungeon, mapfloor, maptown, mapspace, maptreasure, ...)
ends with a `GENERATORS` list of `GeneratorSpec`. The editor never imports those
modules by name: it calls `discover()`, so a generator is offered the moment its
module exists and nothing else has to change. The Generate dialog is built from a
spec's `fields`, so a new generator needs no dialog code.

    GENERATORS = [GeneratorSpec(
        key="dungeon", map_kind="dungeon", label="Dungeon or caves",
        blurb="Rooms and corridors, or a cave system.",
        fields=(Field("rooms", "Rooms", "int", 12, lo=4, hi=40),
                Field("mode", "Kind", "choice", "rooms", choices=("rooms", "cave"))),
        presets={"Small crypt": {"rooms": 6}},
        build=lambda values, seed, name: generate_dungeon(DungeonParams(seed=seed, name=name, **values)))]

`build(values, seed, name)` must return a complete `GameMap` and be deterministic for
the same arguments. Nothing here imports Tk: the registry is used headless too (the
command line, the tests).
"""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

# Modules that may hold GENERATORS, by name inside the novelforge package. A name whose
# module does not exist yet is skipped without complaint.
MODULES: Tuple[str, ...] = ("mapdungeon", "mapfloor", "maptown", "mapspace", "maptreasure")

# Modules that exist but failed to import, as (module, message): shown by the tests and
# `doctor`, never raised at the writer.
ERRORS: List[Tuple[str, str]] = []

FIELD_KINDS = ("int", "float", "choice", "bool", "text")


@dataclass(frozen=True)
class Field:
    """One control in a Generate dialog."""

    name: str                       # keyword the generator receives
    label: str                      # what the writer reads
    kind: str = "int"               # one of FIELD_KINDS
    default: Any = 0
    lo: Optional[float] = None      # int / float limits
    hi: Optional[float] = None
    choices: Tuple[Any, ...] = ()   # for kind "choice"
    help: str = ""                  # one short sentence, shown as a tooltip

    def __post_init__(self) -> None:
        if self.kind not in FIELD_KINDS:
            raise ValueError(f"field {self.name!r}: unknown kind {self.kind!r}")
        if self.kind == "choice" and not self.choices:
            raise ValueError(f"field {self.name!r}: a choice needs choices")

    def clamp(self, value: Any) -> Any:
        """The value made valid for this field: never raises, falls back to the default."""
        try:
            if self.kind == "bool":
                return bool(value)
            if self.kind == "text":
                return str(value)
            if self.kind == "choice":
                return value if value in self.choices else self.default
            number = int(value) if self.kind == "int" else float(value)
        except (TypeError, ValueError):
            return self.default
        if self.lo is not None:
            number = max(self.lo, number)
        if self.hi is not None:
            number = min(self.hi, number)
        return int(number) if self.kind == "int" else float(number)


@dataclass(frozen=True)
class GeneratorSpec:
    key: str                                            # unique, e.g. "dungeon"
    map_kind: str                                       # a mapmaker.MAP_KINDS key
    label: str
    blurb: str
    fields: Tuple[Field, ...]
    build: Callable[[Mapping[str, Any], int, str], Any]   # (values, seed, name) -> GameMap
    presets: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def defaults(self) -> Dict[str, Any]:
        return {f.name: f.default for f in self.fields}

    def values_for(self, preset: str = "", overrides: Optional[Mapping[str, Any]] = None
                   ) -> Dict[str, Any]:
        """Defaults, then a named preset, then the writer's own choices; each made valid."""
        values = self.defaults()
        values.update(self.presets.get(preset, {}) if preset else {})
        values.update(overrides or {})
        known = {f.name: f for f in self.fields}
        return {name: known[name].clamp(value) for name, value in values.items() if name in known}

    def generate(self, values: Optional[Mapping[str, Any]] = None, seed: int = 1, name: str = ""):
        """A finished GameMap for these values (missing ones take their defaults)."""
        return self.build(self.values_for(overrides=values), int(seed), name)


def discover(modules: Sequence[str] = MODULES) -> List[GeneratorSpec]:
    """
    Every generator that exists right now, in a stable order.

    A module that is not there yet is skipped; one that is there but breaks on
    import is recorded in ERRORS and skipped, so a bug in one generator can never
    stop the Map Maker opening.
    """
    found: List[GeneratorSpec] = []
    seen = set()
    for name in modules:
        qualified = name if "." in name else f"novelforge.{name}"
        try:
            if importlib.util.find_spec(qualified) is None:
                continue
            module = importlib.import_module(qualified)
        except Exception as error:  # noqa: BLE001 - deliberately broad, see above
            ERRORS.append((qualified, f"{type(error).__name__}: {error}"))
            continue
        for spec in getattr(module, "GENERATORS", ()) or ():
            if spec.key in seen:
                ERRORS.append((qualified, f"duplicate generator key {spec.key!r}"))
                continue
            seen.add(spec.key)
            found.append(spec)
    return found


def specs_for(map_kind: str, modules: Sequence[str] = MODULES) -> List[GeneratorSpec]:
    """The generators that produce this kind of map (may be empty: the world generator is separate)."""
    return [s for s in discover(modules) if s.map_kind == map_kind]
