"""A committed show and what the programmer and record handlers read from it.

The session only ever holds a show that validates and compiles (phase-3-plan
decision 4). :class:`ShowState` keeps that show together with its compiled
form and two lookups built once per commit: the value resolver of the cue
compiler (preset scope lookup, spreads, encoding) and each fixture's
element count.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from busk.compiler.compile import CompiledShow
from busk.compiler.cues import CueCompiler
from busk.model.common import TargetRef
from busk.model.show import Show


@dataclass(frozen=True, kw_only=True)
class ShowState:
    """A valid show, its compiled form and shared lookups. Immutable."""

    show: Show
    compiled: CompiledShow
    values: CueCompiler = field(init=False)
    elements: Mapping[str, int] = field(init=False)  # fixture id → element count

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", CueCompiler(self.show, self.compiled.slots))
        object.__setattr__(self, "elements", MappingProxyType(element_counts(self.show)))

    def target_problem(self, target: TargetRef) -> str | None:
        """Why ``target`` does not exist in the show, or ``None`` if it does."""
        count = self.elements.get(target["fixtureId"])
        if count is None:
            return f"no fixture {target['fixtureId']!r}"
        if not 0 <= target["element"] < count:
            return f"fixture {target['fixtureId']!r} has no element {target['element']}"
        return None


def element_counts(show: Show) -> dict[str, int]:
    """Each fixture's number of elements, from its profile mode (a valid show)."""
    modes = {
        (profile["id"], mode["id"]): len(mode["elements"])
        for profile in show["profiles"]
        for mode in profile["modes"]
    }
    return {
        fixture["id"]: modes[(fixture["profileId"], fixture["modeId"])]
        for fixture in show["fixtures"]
    }
