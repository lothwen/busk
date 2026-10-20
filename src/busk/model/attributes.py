"""Attribute registry and attribute values (spec §5.3–§5.4).

Attributes are the shared vocabulary between show data, the resolver and
fixture profiles. The registry is static, compiled into the application, and
tied to schema version 1: adding or changing an attribute is a schema change.

:data:`ATTRIBUTES` preserves the order of the spec's §5.3 table. Later phases
rely on that order (for example to allocate slots deterministically).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import Discriminator, Tag, with_config

from busk.model.common import STRICT, AttributeId, Unit

# -------------------------------------------------------------------- values


@with_config(STRICT)
class ColorValue(TypedDict):
    """A target colour in linear RGB, each component ``0..1`` (§5.4).

    The optional extras request explicit emitters; when absent, the fixture
    profile derives them from ``r``, ``g`` and ``b`` (§13.3).
    """

    r: Unit
    g: Unit
    b: Unit
    w: NotRequired[Unit]
    a: NotRequired[Unit]
    uv: NotRequired[Unit]


@with_config(STRICT)
class DiscreteValue(TypedDict):
    """A discrete position: a wheel slot, prism state or shutter function (§5.4).

    For ``shutter``, ``slot`` is one of ``"open"``, ``"closed"``, ``"strobe"``,
    ``"pulse"`` or ``"random"``.
    """

    wheel: NotRequired[str]  # wheel id within the profile (gobo/colour/prism)
    slot: str  # stable slot id, e.g. "open", "breakup", "red"


type ValueKind = Literal["scalar", "color", "discrete"]


def value_kind(value: object) -> ValueKind | None:
    """Return the shape of a JSON attribute value, or ``None`` if it has none.

    Numbers are scalars, objects with a ``slot`` key are discrete values and
    any other object is a colour. Booleans are not numbers here, even though
    ``bool`` is a subclass of ``int`` in Python.

    This doubles as the pydantic discriminator of :data:`AttributeValue`, so a
    malformed value reports errors for the one shape it resembles instead of
    one error per union member.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return "scalar"
    if isinstance(value, dict):
        return "discrete" if "slot" in value else "color"
    return None


type AttributeValue = Annotated[
    Annotated[float, Tag("scalar")]
    | Annotated[ColorValue, Tag("color")]
    | Annotated[DiscreteValue, Tag("discrete")],
    Discriminator(
        value_kind,
        custom_error_type="attribute_value",
        custom_error_message=(
            "Input should be a number, a colour {r, g, b} or a discrete value {slot}"
        ),
    ),
]
"""Any value stored in show data: ``float | ColorValue | DiscreteValue`` (§5.4)."""

# ------------------------------------------------------------------ registry

type AttributeFamily = Literal[
    "intensity", "position", "color", "beam", "focus", "shutter", "control"
]

type AttributeUnit = Literal["normalized", "degrees", "hz", "degPerSec", "none"]


@dataclass(frozen=True, kw_only=True)
class ScalarRange:
    """Inclusive logical range of a scalar attribute."""

    min: float
    max: float


@dataclass(frozen=True, kw_only=True)
class AttributeDefinition:
    """One entry of the attribute registry (§5.3).

    ``default`` is the value a slot takes when no source controls it. Two
    defaults are not an :data:`AttributeValue`, and the slot compiler resolves
    them per fixture: ``zoom``'s is "the profile's midpoint", the sentinel
    ``"profileMidpoint"`` (Phase 1); the fixture programs' (``colorMacro``,
    ``effect`` …) is "the channel's default option", the sentinel
    ``"channelDefault"`` (see :func:`~busk.model.profile.channel_default_option`).

    A scalar that ``followsChannel`` (the programs' rates and parameters)
    starts instead at the value its channel's ``defaultDmx`` stands for, so
    an unprogrammed fixture outputs its own default; ``default`` is then the
    value of a slot without a channel, or whose ``defaultDmx`` lies in no
    range.
    """

    id: AttributeId
    family: AttributeFamily
    kind: ValueKind
    unit: AttributeUnit
    range: ScalarRange | None = None  # scalar only; logical range
    merge: Literal["HTP", "LTP"]
    fade: Literal["fade", "snap"]  # discrete values always snap
    snapAt: Literal["start", "middle", "end"] | None = None  # None means "start"
    wraps: bool | None = None  # e.g. continuous rotation index
    default: AttributeValue | Literal["profileMidpoint", "channelDefault"]
    home: AttributeValue | None = None  # optional value used by the HOME command
    followsChannel: bool = False  # scalar only: start at the channel's defaultDmx


_NORMALIZED = ScalarRange(min=0.0, max=1.0)
_WHITE = ColorValue(r=1.0, g=1.0, b=1.0)


def _scalar(
    attribute: AttributeId,
    family: AttributeFamily,
    unit: AttributeUnit,
    default: float | Literal["profileMidpoint"],
    *,
    merge: Literal["HTP", "LTP"] = "LTP",
    fade: Literal["fade", "snap"] = "fade",
    follows: bool = False,
) -> AttributeDefinition:
    """Build a scalar definition. Normalised scalars get the ``0..1`` range;
    degree, Hz and deg/s scalars have no registry range because their range
    depends on the fixture profile."""
    return AttributeDefinition(
        id=attribute,
        family=family,
        kind="scalar",
        unit=unit,
        range=_NORMALIZED if unit == "normalized" else None,
        merge=merge,
        fade=fade,
        snapAt="start" if fade == "snap" else None,
        default=default,
        followsChannel=follows,
    )


def _discrete(
    attribute: AttributeId, family: AttributeFamily, default_slot: str | None
) -> AttributeDefinition:
    """Build a discrete definition. Discrete values cannot be interpolated, so
    they always snap, at the start of a fade (§7.3). A ``None`` default slot
    is the channel's own default option (``"channelDefault"``)."""
    return AttributeDefinition(
        id=attribute,
        family=family,
        kind="discrete",
        unit="none",
        merge="LTP",
        fade="snap",
        snapAt="start",
        default="channelDefault" if default_slot is None else DiscreteValue(slot=default_slot),
    )


ATTRIBUTES: Mapping[AttributeId, AttributeDefinition] = MappingProxyType(
    {
        definition.id: definition
        for definition in (
            _scalar("intensity", "intensity", "normalized", 0.0, merge="HTP"),
            _scalar("pan", "position", "degrees", 0.0),
            _scalar("tilt", "position", "degrees", 0.0),
            _scalar("positionSpeed", "position", "normalized", 0.0, fade="snap"),  # 0 = fastest
            AttributeDefinition(
                id="color",
                family="color",
                kind="color",
                # The table's unit is "linear RGB": each component is normalised 0..1.
                unit="normalized",
                merge="LTP",
                fade="fade",
                default=_WHITE,
            ),
            _discrete("colorWheel", "color", "open"),
            _scalar("cto", "color", "normalized", 0.0),
            # Colour presets and programs built into the fixture, and their speed.
            _discrete("colorMacro", "color", None),
            _scalar("colorMacroRate", "color", "normalized", 0.5, follows=True),  # 1 fastest
            _discrete("colorEffect", "color", None),
            _discrete("gobo1", "beam", "open"),
            _discrete("gobo2", "beam", "open"),
            _scalar("gobo1Rotation", "beam", "degPerSec", 0.0),
            _scalar("gobo2Rotation", "beam", "degPerSec", 0.0),
            _discrete("prism", "beam", "off"),
            _scalar("prismRotation", "beam", "degPerSec", 0.0),
            _scalar("zoom", "beam", "degrees", "profileMidpoint"),
            _scalar("iris", "beam", "normalized", 1.0),  # 1 = open
            _scalar("frost", "beam", "normalized", 0.0),
            # Programs built into the fixture ("fixture effects"), and their parameters.
            _discrete("effect", "beam", None),
            _discrete("effect2", "beam", None),
            _scalar("effectRate", "beam", "normalized", 0.5, follows=True),  # 1 fastest
            _scalar("effectFade", "beam", "normalized", 0.0, fade="snap", follows=True),
            _scalar("effectAdjust", "beam", "normalized", 0.5, follows=True),
            _scalar("effectRotation", "beam", "degPerSec", 0.0, follows=True),
            _scalar("effectSync", "beam", "normalized", 0.0, fade="snap", follows=True),
            _scalar("soundSensitivity", "beam", "normalized", 0.0, fade="snap", follows=True),
            _scalar("focus", "focus", "normalized", 0.5),
            _discrete("shutter", "shutter", "open"),
            _scalar("strobeRate", "shutter", "hz", 0.0),
            # Lamp on, reset…: reachable only through explicit commands, never busked (§5.5).
            _discrete("control", "control", "none"),
        )
    }
)
"""The built-in v1 attribute catalogue, keyed by attribute id, in §5.3 table order."""
