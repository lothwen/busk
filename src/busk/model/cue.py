"""Cue lists and cues (spec §5.11).

Every playback runs a cue list. A look is a one-cue list, a song stack is a
``sequence`` list advanced by GO, a chase is a list in ``chase`` mode advanced
by its rate, and an effect playback is a one-cue list holding only an effect.

Cue numbers are decimal strings (``"1"``, ``"1.5"``, ``"12.25"``) to avoid
floating-point surprises. Validation requires ``\\d+(\\.\\d+)?`` and compares
numbers as integer tuples, so ``"1.10"`` sorts after ``"1.9"``.
"""

from __future__ import annotations

import re
from typing import Annotated, Final, Literal, NotRequired, TypedDict

from pydantic import Field, with_config

from busk.model.attributes import AttributeFamily
from busk.model.common import STRICT, AttributeId, CueId, CueListId, EntityBase, Seconds, Unit
from busk.model.effect import EffectInstance, Rate
from busk.model.entry import FadeCurve, TargetSpec, ValueEntry

CUE_NUMBER: Final = re.compile(r"[0-9]+(?:\.[0-9]+)?")
"""A valid cue number: digits with an optional decimal part."""


def cue_number_key(number: str) -> tuple[int, ...] | None:
    """A cue number as comparable integer parts (``"1.10"`` > ``"1.9"``), or
    ``None`` when it is not ``digits[.digits]``."""
    if CUE_NUMBER.fullmatch(number) is None:
        return None
    return tuple(int(part) for part in number.split("."))


@with_config(STRICT)
class ChaseSettings(TypedDict):
    """How a ``chase`` cue list steps through its cues."""

    rate: Rate
    direction: Literal["forward", "reverse", "bounce", "random"]
    crossfade: Unit  # fraction of the step time spent fading


@with_config(STRICT)
class CueList(EntityBase[CueListId]):
    """An ordered list of cues; ``chase`` settings are required in ``chase`` mode."""

    number: int
    mode: Literal["sequence", "chase"]
    tracking: bool  # values persist until changed (§9.3)
    wrap: bool  # after the last cue: wrap to the first, or stay/release
    releaseAtEnd: bool  # GO past the last cue releases the playback
    chase: NotRequired[ChaseSettings]
    cues: list[Cue]  # sorted by `number`


@with_config(STRICT)
class CueRelease(TypedDict):
    """Explicitly release attributes of some targets in a cue."""

    targets: TargetSpec
    attributes: list[AttributeId] | Literal["all"]


@with_config(STRICT)
class GoTrigger(TypedDict):
    """The cue waits for a manual GO."""

    kind: Literal["go"]


@with_config(STRICT)
class FollowTrigger(TypedDict):
    """Auto-GO ``delay`` seconds after the previous cue *completes*."""

    kind: Literal["follow"]
    delay: Seconds


@with_config(STRICT)
class WaitTrigger(TypedDict):
    """Auto-GO ``delay`` seconds after the previous cue *starts*."""

    kind: Literal["wait"]
    delay: Seconds


type CueTrigger = Annotated[GoTrigger | FollowTrigger | WaitTrigger, Field(discriminator="kind")]


@with_config(STRICT)
class Cue(TypedDict):
    """One state of a cue list: value entries, effects and timing."""

    id: CueId  # unique within its cue list
    number: str  # decimal as string: "1", "1.5", "12.25"
    name: str
    entries: list[ValueEntry]
    effects: list[EffectInstance]
    releases: NotRequired[list[CueRelease]]  # explicit release
    block: NotRequired[bool]  # tracking stop: this cue is a full hard state
    timing: CueTiming
    trigger: CueTrigger


@with_config(STRICT)
class FamilyTiming(TypedDict):
    """Timing override for one attribute family."""

    fade: Seconds
    delay: Seconds
    curve: NotRequired[FadeCurve]


@with_config(STRICT)
class CueTiming(TypedDict):
    """Default timing of a cue (§9.1)."""

    fadeIn: Seconds  # intensity rising & all LTP attributes
    fadeOut: Seconds  # intensity falling
    delayIn: Seconds
    delayOut: Seconds
    curve: FadeCurve
    perFamily: NotRequired[dict[AttributeFamily, FamilyTiming]]
