"""busk's attributes as F2's encoders, the programmer table and the preset
tiles show them (spec §8.2, plan Phase 2 "Encoders"): no busk, no Textual.

:data:`FAMILIES` is a small table, as command words are: each encoder's
attribute as ``set`` names it (``intensity``, ``color.r``, ``strobeRate``),
its unit, its bar colour and its steps. An encoder shows when some profile
of the show's fixtures takes its attribute.

An encoder shows the first selected fixture element (spec §8.2): the
value the programmer holds (a preset with its value), else the output's
(intensity, pan, tilt and zoom, after the masters), else nothing. Its
``[−]`` ``[+]`` and the wheel send ``set <attribute> by <change>``, which
busk applies only where the programmer holds the attribute, so they act
only then (question Q11). Its bar sends an absolute ``set``; busk takes a
colour component's only where the programmer holds a colour (GAP-05), so
a component's bar, too, sets only then.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

from busk_tui import colors, commands
from busk_tui.commands import Line
from busk_tui.model import (
    Components,
    ElementOutput,
    HeldValue,
    OutputModel,
    ProfileInfo,
    ProgrammerModel,
    ShowModel,
    Summary,
    Value,
)

type Unit = Literal["level", "degrees", "hz"]
type Source = Literal["programmer", "output"]

BLUE: Final = "#5f87ff"
"""The blue encoder's bar (xterm 69, spec §8.2)."""


@dataclass(frozen=True, slots=True)
class Encoder:
    """One encoder row. ``step`` and ``wheel`` are what ``[−]`` ``[+]`` and
    one wheel notch change: a level's as 0..1, else in the unit."""

    attribute: str  # as set names it
    unit: Unit
    color: str
    step: float
    wheel: float

    @property
    def held_as(self) -> str:
        """The attribute the programmer holds it in: ``color`` for a component."""
        return "color" if self.component is not None else self.attribute

    @property
    def component(self) -> str | None:
        """``r``, ``g``, ``b`` or ``w`` for a colour component."""
        return self.attribute[6:] if self.attribute.startswith("color.") else None

    @property
    def taken_as(self) -> str:
        """The attribute a profile must take for the row to show."""
        return "color" if self.component in ("r", "g", "b") else self.attribute


def _level(attribute: str, color: str) -> Encoder:
    return Encoder(attribute, "level", color, 0.05, 0.02)


FAMILIES: Final[tuple[tuple[str, tuple[Encoder, ...]], ...]] = (
    ("intensity", (_level("intensity", colors.FG),)),
    (
        "position",
        (
            Encoder("pan", "degrees", colors.CYAN, 15.0, 5.0),
            Encoder("tilt", "degrees", colors.CYAN, 15.0, 5.0),
        ),
    ),
    (
        "color",
        (
            _level("color.r", colors.RED),
            _level("color.g", colors.GREEN),
            _level("color.b", BLUE),
            _level("color.w", colors.FG),
            _level("cto", colors.AMBER),
        ),
    ),
    (
        "beam",
        (
            Encoder("zoom", "degrees", colors.AMBER, 2.0, 1.0),
            _level("iris", colors.AMBER),
            _level("frost", colors.AMBER),
        ),
    ),
    ("focus", (_level("focus", colors.AMBER),)),
    ("shutter", (Encoder("strobeRate", "hz", colors.AMBER, 1.0, 0.5),)),
)
"""The encoder panels, in the order shown, and their rows."""

DEGREES: Final = frozenset({"pan", "tilt", "zoom"})
HZ: Final = frozenset({"strobeRate"})
DEGREES_PER_S: Final = frozenset(
    {"gobo1Rotation", "gobo2Rotation", "prismRotation", "effectRotation"}
)
"""busk's attributes by unit; every other number is a level, 0..1."""


def taken(show: ShowModel | None) -> frozenset[str]:
    """The attributes the profiles of the show's fixtures take."""
    if show is None:
        return frozenset()
    used = {fixture.profile for fixture in show.fixtures}
    found: set[str] = set()
    for profile in show.profiles:
        if profile.name in used:
            found |= profile.attributes
    return frozenset(found)


def shown(show: ShowModel | None) -> list[tuple[str, tuple[Encoder, ...]]]:
    """The panels with the rows that show: those the rig takes."""
    rig = taken(show)
    panels: list[tuple[str, tuple[Encoder, ...]]] = []
    for family, encoders in FAMILIES:
        rows = tuple(encoder for encoder in encoders if encoder.taken_as in rig)
        if rows:
            panels.append((family, rows))
    return panels


def value_range(
    encoder: Encoder, show: ShowModel | None, profile: ProfileInfo | None
) -> tuple[float, float]:
    """The values the bar spans: 0..1 for a level; else the range of
    ``profile`` (the first selected fixture's), else the widest of the
    profiles that take the attribute."""
    if encoder.unit == "level" or show is None:
        return (0.0, 1.0)
    found = None if profile is None else profile.range(encoder.attribute)
    if found is not None:
        return found
    spans = [p.range(encoder.attribute) for p in show.profiles]
    known = [span for span in spans if span is not None]
    if not known:
        return (0.0, 1.0)
    return (min(low for low, _ in known), max(high for _, high in known))


def to_level(value: float, span: tuple[float, float]) -> float:
    """``value`` as a bar's level, 0..1."""
    low, high = span
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def to_value(level: float, span: tuple[float, float], unit: Unit) -> float:
    """The value a bar's ``level`` stands for, rounded as it is sent:
    a level to whole percent, degrees to whole degrees (to a tenth over
    a span under 60), Hz to a tenth."""
    low, high = span
    value = low + max(0.0, min(1.0, level)) * (high - low)
    if unit == "level":
        return round(value, 2)
    if unit == "degrees" and high - low >= 60:
        return float(round(value))
    return round(value, 1)


def component(value: Value, key: str) -> float | None:
    """A colour's component; ``None`` for a value that is not a colour."""
    if not isinstance(value, tuple):
        return None
    return next((amount for name, amount in value if name == key), None)


@dataclass(frozen=True, slots=True)
class Selected:
    """What every row reads, found once per redraw: the first selected
    element, its fixture's profile, its values in the programmer (by
    attribute) and in the output, and the attributes the programmer holds
    for any selected element."""

    first: tuple[int, int] | None
    profile: ProfileInfo | None
    values: Mapping[str, HeldValue]
    held: frozenset[str]
    out: ElementOutput | None


def selected(
    show: ShowModel | None, programmer: ProgrammerModel | None, output: OutputModel | None
) -> Selected:
    selection = () if programmer is None else programmer.selection
    first = selection[0] if selection else None
    fixture = None if first is None or show is None else show.fixture(first[0])
    profile = None if fixture is None or show is None else show.profile(fixture.profile)
    chosen = set(selection)
    values: dict[str, HeldValue] = {}
    held: set[str] = set()
    for value in () if programmer is None else programmer.values:
        element = (value.number, value.element)
        if element in chosen:
            held.add(value.attribute)
            if element == first:
                values.setdefault(value.attribute, value)
    out = None if output is None or first is None else output.element(*first)
    return Selected(first, profile, values, frozenset(held), out)


@dataclass(frozen=True, slots=True)
class Reading:
    """What an encoder row shows: its ``value`` (``None``: nothing) and where
    it comes from, whether its bar sets (``settable``) and its steps and
    wheel act (``steps``), and the range its bar spans."""

    value: float | None
    source: Source | None
    preset: str | None  # the preset the programmer's value comes from
    settable: bool
    steps: bool
    span: tuple[float, float]


def reading(encoder: Encoder, show: ShowModel | None, chosen: Selected) -> Reading:
    """``encoder``'s row for the first selected element (see the module docs)."""
    span = value_range(encoder, show, chosen.profile)
    holds = encoder.held_as in chosen.held
    settable = chosen.first is not None and (encoder.component is None or holds)
    value: float | None = None
    source: Source | None = None
    preset: str | None = None
    held = chosen.values.get(encoder.held_as)
    if held is not None:
        key = encoder.component
        if key is None:
            value = held.value if isinstance(held.value, float) else None
        else:  # a component the colour lacks starts at 0 (busk's GAP-05)
            value = component(held.value, key)
            value = 0.0 if value is None and key in ("w", "a", "uv") else value
        source = None if value is None else "programmer"
        preset = held.preset
    if value is None:
        value = output_value(encoder, chosen.out)
        source = None if value is None else "output"
    return Reading(value, source, preset, settable, holds, span)


def output_value(encoder: Encoder, out: ElementOutput | None) -> float | None:
    """The output's value of an encoder that has one (the colour is shown
    whole, as one swatch)."""
    if out is None:
        return None
    match encoder.attribute:
        case "intensity":
            return out.intensity
        case "pan":
            return out.pan
        case "tilt":
            return out.tilt
        case "zoom":
            return out.zoom
    return None


def set_line(encoder: Encoder, value: float) -> Line:
    """The absolute ``set`` of a bar."""
    if encoder.unit == "level":
        return commands.set_level(encoder.attribute, value)
    return commands.set_number(encoder.attribute, value)


def step_line(encoder: Encoder, by: float) -> Line:
    """``set <attribute> by <by>``: ``by`` a level's as 0..1, else in the unit."""
    if encoder.unit == "level":
        return commands.step_level(encoder.attribute, by)
    return commands.step_number(encoder.attribute, by)


# ------------------------------------------------------------- formatting


def number_text(attribute: str, value: float) -> str:
    """A number in its attribute's unit: ``55%``, ``-45°``, ``10Hz``, ``90°/s``."""
    if attribute in DEGREES:
        return f"{round(value, 1):g}°"
    if attribute in HZ:
        return f"{round(value, 1):g}Hz"
    if attribute in DEGREES_PER_S:
        return f"{round(value, 1):g}°/s"
    return f"{round(value * 100)}%"


def summary_text(attribute: str, value: Summary) -> str:
    """A value as a table or a tile shows it; ``mixed`` for ``None``."""
    if value is None:
        return "mixed"
    if isinstance(value, str):
        return value
    return number_text(attribute, value)


def rgb_text(value: Components) -> str:
    """A colour's components, two decimals each: ``1.00 0.50 0.00`` (and the
    white, ``w0.25``, when it has one)."""
    parts = [f"{amount:.2f}" for name, amount in value if name in ("r", "g", "b")]
    white = component(value, "w")
    if white is not None:
        parts.append(f"w{white:.2f}")
    return " ".join(parts)


def rgb(value: Components) -> tuple[float, float, float]:
    """A colour as a swatch draws it, its white added."""
    white = component(value, "w") or 0.0
    red, green, blue = ((component(value, key) or 0.0) + white for key in ("r", "g", "b"))
    return (min(1.0, red), min(1.0, green), min(1.0, blue))
