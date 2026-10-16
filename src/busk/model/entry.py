"""Value entries: the unit of stored intent (spec §5.9).

A value entry says *which targets*, *which attribute*, *what value* and
optionally *what timing*. Cues and the programmer store value entries.

Busking recommendation (§5.9): record with ``{"kind": "group"}`` targets and
``{"kind": "preset"}`` values whenever possible, so editing a group or a
preset updates every look that uses it.

This module sits below ``effect`` and ``cue`` in the import graph: effect
instances need :data:`TargetSpec`, and cues need both entries and effects.
"""

from __future__ import annotations

from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import Field, with_config

from busk.model.attributes import AttributeValue
from busk.model.common import STRICT, AttributeId, GroupId, PresetId, Seconds, TargetKey, TargetRef

# ------------------------------------------------------------------- targets


@with_config(STRICT)
class TargetList(TypedDict):
    """A fixed list of targets."""

    kind: Literal["targets"]
    refs: list[TargetRef]


@with_config(STRICT)
class GroupTarget(TypedDict):
    """A live reference to a group: follows later edits of the group."""

    kind: Literal["group"]
    groupId: GroupId


type TargetSpec = Annotated[TargetList | GroupTarget, Field(discriminator="kind")]

# ------------------------------------------------------------- value sources


@with_config(STRICT)
class LiteralSource(TypedDict):
    """The same value for every target."""

    kind: Literal["literal"]
    value: AttributeValue


@with_config(STRICT)
class PerTargetSource(TypedDict):
    """An explicit value per target, keyed by ``"fixtureId:element"``."""

    kind: Literal["perTarget"]
    values: dict[TargetKey, AttributeValue]


@with_config(STRICT)
class PresetSource(TypedDict):
    """A preset reference, resolved per target at compile time (§5.8 scope lookup)."""

    kind: Literal["preset"]
    presetId: PresetId


# Functional syntax because `from` is a Python keyword.
SpreadSource = TypedDict(
    "SpreadSource",
    {
        "kind": Literal["spread"],  # fan from → to across the ordered targets
        "from": AttributeValue,
        "to": AttributeValue,
        "curve": NotRequired[Literal["linear", "center", "edges"]],
    },
)
with_config(STRICT)(SpreadSource)

type ValueSource = Annotated[
    LiteralSource | PerTargetSource | PresetSource | SpreadSource,
    Field(discriminator="kind"),
]

# ------------------------------------------------------------------- entries


@with_config(STRICT)
class ValueEntry(TypedDict):
    """Targets × attribute × value, with optional per-entry timing."""

    targets: TargetSpec
    attribute: AttributeId
    value: ValueSource
    timing: NotRequired[TimingOverride]


@with_config(STRICT)
class TimingOverride(TypedDict, total=False):
    """Per-entry timing; overrides the cue's timing for this entry."""

    fade: Seconds
    delay: Seconds
    curve: FadeCurve


@with_config(STRICT)
class BezierCurve(TypedDict):
    """A cubic Bézier easing curve, CSS-style control points."""

    bezier: tuple[float, float, float, float]


type FadeCurve = (
    Literal[
        "linear", "easeIn", "easeOut",
        "easeInOut",  # smoothstep t²(3−2t)
        "snapStart", "snapEnd",
    ]
    | BezierCurve
)  # fmt: skip
