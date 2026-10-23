"""Fixture profiles: the library definition of a device model (spec §5.5).

A profile describes a fixture *model* (modes, channels, wheels, physical
ranges); a :class:`~busk.model.fixture.Fixture` is a patched *instance* of it.
Profiles are embedded in the show file so shows are portable.

Profile rules beyond what the types express (element numbering, channel
offsets inside the footprint, DMX values that fit the channel's resolution,
ordered capabilities, …) are checked by the semantic pass in
``busk.model.validate``.

The end of this module holds the *interpretation* of a profile that both the
validator and the compiler need (which capabilities are a channel's discrete
options, what a colour component means). Keeping it in one place guarantees
that what validation accepts is exactly what the compiler understands.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Final, Literal, NotRequired, TypedDict, get_args

from pydantic import Field, with_config

from busk.model.attributes import ColorValue
from busk.model.common import (
    STRICT,
    AttributeId,
    EntityBase,
    ModeId,
    NonNegativeInt,
    ProfileId,
    Unit,
)


@with_config(STRICT)
class FixturePhysical(TypedDict, total=False):
    """Physical characteristics; all optional and informational."""

    panRange: float  # total mechanical travel, degrees (e.g. 540)
    tiltRange: float  # e.g. 270
    zoomRange: tuple[float, float]  # beam angle min/max, degrees
    maxStrobeHz: float
    powerW: float
    weightKg: float


type ProfileCategory = Literal[
    "par", "spot", "wash", "beam", "pixel", "strobe", "blinder", "dimmer", "effect", "fog",
    "other",
]  # fmt: skip
"""What kind of fixture a profile is, for a display to group and draw its
fixtures by (GAP-16 of ``docs/dev/tui/engine-gaps.md``): ``par`` a static
wash light (a par, a PC, an LED colour changer), ``spot``, ``wash`` and
``beam`` moving heads, ``pixel`` a bar, strip or matrix of cells, ``strobe``,
``blinder``, ``dimmer`` a dimmed channel, ``effect`` a light effect (a
flower, a laser, a barrel scanner), ``fog`` a smoke or haze machine, and
``other``. Nothing busk outputs depends on it."""


@with_config(STRICT)
class FixtureProfile(EntityBase[ProfileId]):
    """A device model with one or more DMX modes."""

    manufacturer: str
    model: str
    revision: str  # bump when edited; fixtures record the revision they were patched with
    source: Literal["gdtf", "ofl", "user"]
    category: NotRequired[ProfileCategory]  # a label: setting it is no new revision
    physical: FixturePhysical
    wheels: list[Wheel]
    emitters: NotRequired[list[Emitter]]  # for additive/subtractive colour mixing (§13.3)
    modes: list[FixtureMode]


@with_config(STRICT)
class Wheel(TypedDict):
    """A colour, gobo, prism or animation wheel."""

    id: str  # "color1", "gobo1", "prism1"
    kind: Literal["color", "gobo", "prism", "animation"]
    slots: list[WheelSlot]


@with_config(STRICT)
class WheelSlot(TypedDict):
    """One position of a wheel, addressed by a stable id."""

    id: str  # stable: "open", "red", "breakup"
    name: str
    color: NotRequired[ColorValue]  # colour wheels: measured approximate colour
    facets: NotRequired[int]  # prisms
    image: NotRequired[str]  # gobo thumbnail (asset path)


@with_config(STRICT)
class Emitter(TypedDict):
    """A light source used for colour mixing, with its calibrated colour."""

    id: (
        Literal[
            "red", "green", "blue", "white", "amber", "lime", "cyan",
            "uv", "cyanFlag", "magentaFlag", "yellowFlag",
        ]
        | str
    )  # fmt: skip
    color: ColorValue  # emitter colour in linear RGB (calibration)
    subtractive: NotRequired[bool]  # CMY flags


@with_config(STRICT)
class FixtureMode(TypedDict):
    """One DMX personality of a profile (e.g. "16-ch basic")."""

    id: ModeId
    name: str  # "Extended 32ch"
    footprint: Annotated[int, Field(ge=1, le=512)]  # DMX channels used
    elements: Annotated[list[ElementDefinition], Field(min_length=1)]  # index 0 = "main"
    intensityStrategy: Literal["dimmerChannel", "virtual"]  # virtual = scale emitters (§13.2)
    dimmerCurve: NotRequired[Literal["linear", "square", "invSquare", "sCurve"] | list[Unit]]
    channels: list[ChannelDefinition]


@with_config(STRICT)
class ElementLayout(TypedDict):
    """Relative position of an element, for pixel layouts."""

    x: float
    y: float


@with_config(STRICT)
class ElementDefinition(TypedDict):
    """An individually controllable part of a fixture (a pixel, a cell)."""

    index: NonNegativeInt  # 0..n-1, in list order
    name: str  # "Main", "Cell 1"…
    layout: NotRequired[ElementLayout]


@with_config(STRICT)
class ChannelDefinition(TypedDict):
    """One logical channel of a mode: an attribute (or colour component) of an element.

    A 16- or 24-bit channel is a single definition: ``offset`` is the coarse
    byte and the fine/ultra bytes follow at ``fineOffsets``, or right after
    ``offset`` when ``fineOffsets`` is absent. ``defaultDmx``, ``highlightDmx``
    and capability ``dmx`` ranges are in the channel's full resolution
    (``0 .. 256**bytes − 1``).
    """

    offset: NonNegativeInt  # 0-based within the footprint (coarse byte)
    element: NonNegativeInt  # element index
    attribute: AttributeId
    component: NotRequired[str]  # colour only: emitter id ("red", "white", "cyanFlag")
    bytes: Literal[1, 2, 3]  # coarse, +fine, +ultra
    fineOffsets: NotRequired[list[NonNegativeInt]]  # usually [offset+1]; NOT always adjacent
    defaultDmx: NonNegativeInt  # raw value when no slot drives the channel (§13.5)
    highlightDmx: NotRequired[NonNegativeInt]  # value used by the highlight function
    invert: NotRequired[bool]  # 255 = minimum (common on dimmers of old fixtures)
    capabilities: list[Capability]  # ordered, non-overlapping DMX ranges


@with_config(STRICT)
class RangeCapability(TypedDict):
    """A linear map from a DMX range to a logical sub-range of the attribute."""

    kind: Literal["range"]
    dmx: tuple[NonNegativeInt, NonNegativeInt]  # inclusive, in the channel's full resolution
    value: tuple[float, float]  # logical units of the attribute


@with_config(STRICT)
class SlotCapability(TypedDict):
    """A DMX range selecting a wheel slot or other discrete position."""

    kind: Literal["slot"]
    dmx: tuple[NonNegativeInt, NonNegativeInt]
    wheel: NotRequired[str]
    slot: str


@with_config(STRICT)
class CapabilityParam(TypedDict):
    """A continuous parameter inside a function range (e.g. strobe 1–20 Hz)."""

    attribute: AttributeId
    value: tuple[float, float]


@with_config(STRICT)
class FunctionCapability(TypedDict):
    """A DMX range selecting a shutter function or special mode."""

    kind: Literal["function"]
    dmx: tuple[NonNegativeInt, NonNegativeInt]
    fn: (
        Literal[
            "open", "closed", "strobe", "pulse", "random", "reset", "lampOn", "lampOff",
            "maintenance",
        ]
        | str
    )  # fmt: skip
    param: NotRequired[CapabilityParam]


type Capability = Annotated[
    RangeCapability | SlotCapability | FunctionCapability, Field(discriminator="kind")
]


type DimmerCurve = Literal["linear", "square", "invSquare", "sCurve"] | tuple[float, ...]
"""A mode's intensity curve: a named curve or a table of equally spaced points
over ``0..1`` (§13.2). Show data stores a table as a list; compiled data as a
tuple, so it can live in frozen dataclasses."""

# ------------------------------------------------------- profile interpretation

PROFILE_CATEGORIES: Final[tuple[ProfileCategory, ...]] = get_args(ProfileCategory.__value__)
"""The categories a profile may have, in the order of :data:`ProfileCategory`."""

WHEEL_ATTRIBUTES: Final = frozenset({"colorWheel", "gobo1", "gobo2", "prism"})
"""Discrete attributes whose options are ``slot`` capabilities (wheel positions)."""

SHUTTER_FUNCTIONS: Final = frozenset({"open", "closed", "strobe", "pulse", "random"})
"""``fn`` values of the function capabilities that are ``shutter`` options (§5.4).
Every other function (reset, lamp on, custom effects) is never output."""

MACRO_ATTRIBUTES: Final = frozenset({"colorMacro", "colorEffect", "effect", "effect2"})
"""Discrete attributes whose options are every slot and function capability: the
colour presets, programs and effects built into a fixture, each chosen by name."""

MAINTENANCE_FUNCTIONS: Final = frozenset({"reset", "lampOn", "lampOff", "maintenance"})
"""``fn`` values that are never an option, on any channel: a fixture's resets,
lamp switching and other maintenance are reachable only as control channels."""

BUILTIN_EMITTERS: Final[Mapping[str, bool]] = MappingProxyType(
    {
        "red": False,
        "green": False,
        "blue": False,
        "white": False,
        "amber": False,
        "lime": False,
        "cyan": False,
        "uv": False,
        "cyanFlag": True,
        "magentaFlag": True,
        "yellowFlag": True,
    }
)
"""The built-in emitter ids of §5.5, mapped to whether they are subtractive.

A colour channel's ``component`` names an emitter declared in the profile's
``emitters`` or, failing that, one of these. Appendix A's par declares no
emitters at all and relies on the built-in ``red``/``green``/``blue``."""

ADDITIVE_PRIMARIES: Final = ("red", "green", "blue")
SUBTRACTIVE_PRIMARIES: Final = ("cyanFlag", "magentaFlag", "yellowFlag")

COLOR_EXTRAS: Final[tuple[tuple[Literal["w", "a", "uv"], str], ...]] = (
    ("w", "white"),
    ("a", "amber"),
    ("uv", "uv"),
)
"""The optional :class:`~busk.model.attributes.ColorValue` components, in lane
order, with the emitter id each one drives (§6.2)."""


def emitter_is_subtractive(profile: FixtureProfile, component: str) -> bool | None:
    """Whether ``component`` names a subtractive emitter (a CMY flag).

    A declared emitter wins over a built-in one with the same id. Returns
    ``None`` when the component is neither declared nor built in.
    """
    for emitter in profile.get("emitters", []):
        if emitter["id"] == component:
            return emitter.get("subtractive", False)
    return BUILTIN_EMITTERS.get(component)


def option_capabilities(
    channel: ChannelDefinition,
) -> list[tuple[str, SlotCapability | FunctionCapability]]:
    """The discrete options a channel offers, as ``(option id, capability)``.

    * A wheel or prism channel's options are its ``slot`` capabilities.
    * A ``shutter`` channel's options are its function capabilities whose
      ``fn`` is one of :data:`SHUTTER_FUNCTIONS`.
    * A colour macro, colour effect or fixture effect channel's options are
      all its slot and function capabilities (:data:`MACRO_ATTRIBUTES`)
      except maintenance (:data:`MAINTENANCE_FUNCTIONS`).

    Options keep DMX order. When an id appears twice, the first capability
    wins: real charts repeat ranges (the Stairville MH-X25 has two "open"
    ranges on its shutter and on its gobo wheel). Every other capability on
    the channel (shake, wheel spin, macros) is never output. Other attributes
    have no options.
    """
    options: dict[str, SlotCapability | FunctionCapability] = {}
    for capability in channel["capabilities"]:
        option = _option_id(channel["attribute"], capability)
        if option is not None and capability["kind"] != "range":
            options.setdefault(option, capability)
    return list(options.items())


def channel_default_option(channel: ChannelDefinition) -> str | None:
    """The option a channel outputs when nothing controls its attribute, for
    the attributes whose registry default is ``"channelDefault"``.

    It is the option of the capability whose DMX range holds the channel's
    ``defaultDmx``, else the channel's first option; ``None`` when it has no
    options. So an uncontrolled colour macro outputs what the fixture's own
    default selects, which is usually its "no function" range.
    """
    for capability in channel["capabilities"]:
        option = _option_id(channel["attribute"], capability)
        low, high = capability["dmx"]
        if option is not None and low <= channel["defaultDmx"] <= high:
            return option
    options = option_capabilities(channel)
    return options[0][0] if options else None


def _option_id(attribute: str, capability: Capability) -> str | None:
    """The option a capability is on a channel of ``attribute``, or ``None``."""
    if capability["kind"] == "slot" and (
        attribute in WHEEL_ATTRIBUTES or attribute in MACRO_ATTRIBUTES
    ):
        return capability["slot"]
    if capability["kind"] == "function" and (
        (attribute in MACRO_ATTRIBUTES and capability["fn"] not in MAINTENANCE_FUNCTIONS)
        or (attribute == "shutter" and capability["fn"] in SHUTTER_FUNCTIONS)
    ):
        return capability["fn"]
    return None
