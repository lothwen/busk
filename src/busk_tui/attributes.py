"""busk's attributes as F2's encoders, the programmer table, the preset
tiles and F6's PRESET panel show them (spec §8.2, plan Phase 2 "Encoders",
``docs/plans/tui-presets-plan.md``): no busk, no Textual.

:data:`ROWS` is a small table, as command words are: each encoder's
attribute as ``set`` names it (``intensity``, ``color.r``, ``strobeRate``),
its unit, its bar colour and its steps; F2 shows the rows of
:data:`FAMILIES`, the PRESET panel all of them. An encoder shows when some
profile of the show's fixtures takes its attribute. Beside it, busk's
families (:data:`FAMILY_OF`), what each preset pool records
(:data:`POOL_FAMILIES`) and at which scope by default
(:data:`DEFAULT_SCOPE`), and the discrete attributes (:data:`OPTIONS`).

An encoder shows the first selected fixture element (spec §8.2): the
value the programmer holds (a preset with its value), else the output's
(intensity, pan, tilt and zoom, after the masters), else nothing. Its
``[−]`` ``[+]`` and the wheel send ``set <attribute> by <change>``, which
busk applies only where the programmer holds the attribute, so they act
only then (question Q11). Its bar sends an absolute ``set``; busk takes a
colour component's only where the programmer holds a colour (GAP-05), so
a component's bar, too, sets only then.

A spread (``set pan spread -30 30``) gives each selected element its own
value, by busk's rule (:func:`spread_fraction`); the programmer keeps those
values, not the spread, so a spread row reads its ends back from them
(:func:`spread_reading`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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

type Unit = Literal["level", "degrees", "hz", "degps"]
type Source = Literal["programmer", "output"]
type Curve = Literal["center", "edges"]

BLUE: Final = "#5f87ff"
"""The blue encoder's bar (xterm 69, spec §8.2)."""

FAMILY_OF: Final[Mapping[str, str]] = {
    "intensity": "intensity",
    "pan": "position", "tilt": "position", "positionSpeed": "position",
    "color": "color", "colorWheel": "color", "cto": "color", "colorMacro": "color",
    "colorMacroRate": "color", "colorEffect": "color",
    "gobo1": "beam", "gobo2": "beam", "gobo1Rotation": "beam", "gobo2Rotation": "beam",
    "prism": "beam", "prismRotation": "beam", "zoom": "beam", "iris": "beam", "frost": "beam",
    "effect": "beam", "effect2": "beam", "effectRate": "beam", "effectFade": "beam",
    "effectAdjust": "beam", "effectRotation": "beam", "effectSync": "beam",
    "soundSensitivity": "beam",
    "focus": "focus",
    "shutter": "shutter", "strobeRate": "shutter",
    "control": "control",
}  # fmt: skip
"""Each of busk's attributes and its family (busk's attribute registry)."""

TIMING_FAMILIES: Final = ("intensity", "position", "color", "beam", "focus", "shutter")
"""The families a cue may time on their own (``cue L/C time position 4``), in busk's order."""

POOLS: Final = ("color", "position", "beam", "intensity", "focus", "all")
"""busk's preset pools, in the order F6 shows them (spec §8.6's four first)."""

POOL_FAMILIES: Final[Mapping[str, frozenset[str]]] = {
    "color": frozenset({"color"}),
    "position": frozenset({"position"}),
    "beam": frozenset({"beam", "shutter"}),
    "intensity": frozenset({"intensity"}),
    "focus": frozenset({"focus"}),
    "all": frozenset({"intensity", "position", "color", "beam", "focus", "shutter"}),
}
"""The families each pool records: ``record preset <pool> N`` records the
programmer's values in these (``all``: every family but ``control``)."""

DEFAULT_SCOPE: Final[Mapping[str, str]] = {
    "color": "global",
    "intensity": "global",
    "beam": "profile",
    "focus": "profile",
    "position": "target",
    "all": "target",
}
"""The scope busk records a pool's values at when the line names none."""

OPTIONS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("color", ("colorWheel", "colorMacro", "colorEffect")),
    ("beam", ("gobo1", "gobo2", "prism", "effect", "effect2")),
    ("shutter", ("shutter",)),
)
"""The discrete attributes by family, each set to one of the options the
selection offers (``set gobo1 star``)."""

DISCRETE: Final = tuple(attribute for _, found in OPTIONS for attribute in found)
"""Every discrete attribute ``set`` takes, in busk's registry order."""


def family_of(attribute: str) -> str | None:
    """The family of an attribute as ``set`` names it (``color.w``: colour's)."""
    return FAMILY_OF.get(attribute.split(".", 1)[0])


@dataclass(frozen=True, slots=True)
class Encoder:
    """One encoder row. ``step`` and ``wheel`` are what ``[−]`` ``[+]`` and
    one wheel notch change: a level's as 0..1, else in the unit. F2 shows
    the rows marked ``program``; F6's PRESET panel shows every row."""

    attribute: str  # as set names it
    unit: Unit
    color: str
    step: float
    wheel: float
    program: bool = True

    @property
    def held_as(self) -> str:
        """The attribute the programmer holds it in: ``color`` for a component."""
        return "color" if self.component is not None else self.attribute

    @property
    def component(self) -> str | None:
        """``r``, ``g``, ``b``, ``w``, ``a`` or ``uv`` for a colour component."""
        return self.attribute[6:] if self.attribute.startswith("color.") else None

    @property
    def taken_as(self) -> str:
        """The attribute a profile must take for the row to show."""
        return "color" if self.component in ("r", "g", "b") else self.attribute


def _level(attribute: str, color: str, *, program: bool = True) -> Encoder:
    return Encoder(attribute, "level", color, 0.05, 0.02, program)


def _rotation(attribute: str) -> Encoder:
    """A rotation in degrees per second, signed: ``-`` turns the other way."""
    return Encoder(attribute, "degps", colors.AMBER, 15.0, 5.0, program=False)


ROWS: Final[tuple[tuple[str, tuple[Encoder, ...]], ...]] = (
    ("intensity", (_level("intensity", colors.FG),)),
    (
        "position",
        (
            Encoder("pan", "degrees", colors.CYAN, 15.0, 5.0),
            Encoder("tilt", "degrees", colors.CYAN, 15.0, 5.0),
            _level("positionSpeed", colors.CYAN, program=False),
        ),
    ),
    (
        "color",
        (
            _level("color.r", colors.RED),
            _level("color.g", colors.GREEN),
            _level("color.b", BLUE),
            _level("color.w", colors.FG),
            _level("color.a", colors.AMBER, program=False),
            _level("color.uv", colors.MAGENTA, program=False),
            _level("cto", colors.AMBER),
            _level("colorMacroRate", colors.AMBER, program=False),
        ),
    ),
    (
        "beam",
        (
            Encoder("zoom", "degrees", colors.AMBER, 2.0, 1.0),
            _level("iris", colors.AMBER),
            _level("frost", colors.AMBER),
            _rotation("gobo1Rotation"),
            _rotation("gobo2Rotation"),
            _rotation("prismRotation"),
            _level("effectRate", colors.AMBER, program=False),
            _level("effectFade", colors.AMBER, program=False),
            _level("effectAdjust", colors.AMBER, program=False),
            _rotation("effectRotation"),
            _level("effectSync", colors.AMBER, program=False),
            _level("soundSensitivity", colors.AMBER, program=False),
        ),
    ),
    ("focus", (_level("focus", colors.AMBER),)),
    ("shutter", (Encoder("strobeRate", "hz", colors.AMBER, 1.0, 0.5),)),
)
"""Every encoder row by family, in the order shown: one table for F2's
panels and F6's PRESET panel."""

FAMILIES: Final[tuple[tuple[str, tuple[Encoder, ...]], ...]] = tuple(
    (family, tuple(encoder for encoder in encoders if encoder.program)) for family, encoders in ROWS
)
"""F2's encoder panels, in the order shown, and their rows."""

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


def recordable(show: ShowModel | None) -> tuple[str, ...]:
    """The pools the rig can record into: those with a family that some
    profile of the show's fixtures takes an attribute of."""
    families = {family_of(attribute) for attribute in taken(show)}
    return tuple(pool for pool in POOLS if POOL_FAMILIES[pool] & families)


@dataclass(frozen=True, slots=True)
class Section:
    """One family of a pool's editor: its encoder rows and its discrete
    attributes, those the rig takes, and the attributes of either kind that
    no profile of the show takes (``absent``)."""

    family: str
    encoders: tuple[Encoder, ...]
    options: tuple[str, ...]
    absent: tuple[str, ...]


def pool_rows(pool: str, show: ShowModel | None) -> list[Section]:
    """The sections of ``pool``'s editor, by family in the order shown (the
    ``all`` pool has every family). A family the rig takes nothing of is
    there too, with its rows ``absent``."""
    rig = taken(show)
    families = POOL_FAMILIES[pool]
    discrete = dict(OPTIONS)
    sections: list[Section] = []
    for family, encoders in ROWS:
        if family not in families:
            continue
        rows = tuple(encoder for encoder in encoders if encoder.taken_as in rig)
        options = tuple(attribute for attribute in discrete.get(family, ()) if attribute in rig)
        absent = tuple(encoder.attribute for encoder in encoders if encoder.taken_as not in rig)
        absent += tuple(attribute for attribute in discrete.get(family, ()) if attribute not in rig)
        sections.append(Section(family, rows, options, absent))
    return sections


@dataclass(frozen=True, slots=True)
class Records:
    """What ``record preset <pool> N`` records now: each attribute of the
    pool's families that the programmer holds, with the elements it holds
    it for, in the programmer's order; and how many of those elements are
    not selected (busk records them too)."""

    attributes: tuple[tuple[str, tuple[tuple[int, int], ...]], ...]
    unselected: int


def records(pool: str, programmer: ProgrammerModel | None) -> Records:
    """``pool``'s :class:`Records` with the programmer as it is."""
    if programmer is None:
        return Records((), 0)
    families = POOL_FAMILIES[pool]
    found: dict[str, list[tuple[int, int]]] = {}
    for value in programmer.values:
        if family_of(value.attribute) in families:
            found.setdefault(value.attribute, []).append((value.number, value.element))
    selected = set(programmer.selection)
    outside = {element for elements in found.values() for element in elements} - selected
    return Records(
        tuple((attribute, tuple(elements)) for attribute, elements in found.items()),
        len(outside),
    )


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
    a level to whole percent, degrees (and degrees per second) to whole
    degrees (to a tenth over a span under 60), Hz to a tenth."""
    low, high = span
    value = low + max(0.0, min(1.0, level)) * (high - low)
    if unit == "level":
        return round(value, 2)
    if unit in ("degrees", "degps") and high - low >= 60:
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


def spreads(encoder: Encoder) -> bool:
    """Whether a row takes a spread (``set pan spread -30 30``): every row
    but a colour's component, which busk refuses (``set color.r spread``)."""
    return encoder.component is None


def spread_fraction(curve: Curve | None, k: int, n: int) -> float:
    """How far from ``from`` towards ``to`` member ``k`` of ``n`` selected
    elements is, busk's rule: ``u = k / (n − 1)`` (0 when ``n`` is 1), then
    ``u`` (linear, ``None``), ``1 − |2u − 1|`` (``center``) or ``|2u − 1|``
    (``edges``)."""
    u = k / (n - 1) if n > 1 else 0.0
    if curve == "center":
        return 1.0 - abs(2.0 * u - 1.0)
    if curve == "edges":
        return abs(2.0 * u - 1.0)
    return u


def spread_at(start: float, end: float, fraction: float) -> float:
    """A spread's value at ``fraction``, as busk computes it."""
    return start + (end - start) * fraction


def spread_ends(points: Sequence[tuple[float, float]]) -> tuple[float, float] | None:
    """The ``from`` and ``to`` of a spread that gives ``points``, (fraction,
    value) pairs: the line through the points at the lowest and the highest
    fraction. With one fraction only (one element; two with ``center``),
    ``to`` cannot be told, and is ``from``."""
    if not points:
        return None
    low = min(points, key=lambda point: point[0])
    high = max(points, key=lambda point: point[0])
    if high[0] - low[0] < 1e-9:
        return (low[1], low[1])
    slope = (high[1] - low[1]) / (high[0] - low[0])
    start = low[1] - slope * low[0]
    return (start, start + slope)


@dataclass(frozen=True, slots=True)
class SpreadReading:
    """What a spread row shows: its ``ends`` (``None``: nothing) and where
    they come from, whether its bars set (``settable``: something is
    selected) and its steps act (``steps``: the programmer holds the
    attribute on the selection), the range its bars span, and the
    programmer's values on the selection as (fraction, value) pairs."""

    ends: tuple[float, float] | None
    source: Source | None
    settable: bool
    steps: bool
    span: tuple[float, float]
    held: tuple[tuple[float, float], ...]


def spread_reading(
    encoder: Encoder,
    show: ShowModel | None,
    chosen: Selected,
    programmer: ProgrammerModel | None,
    output: OutputModel | None,
    curve: Curve | None,
) -> SpreadReading:
    """``encoder``'s spread over the selection: the ends that give the
    programmer's values, else the output's (busk keeps no spread, only the
    value it gave each element)."""
    span = value_range(encoder, show, chosen.profile)
    selection = () if programmer is None else programmer.selection
    count = len(selection)
    index = {element: k for k, element in enumerate(selection)}
    held: list[tuple[float, float]] = []
    for value in () if programmer is None else programmer.values:
        k = index.get((value.number, value.element))
        if value.attribute != encoder.attribute or k is None:
            continue
        if isinstance(value.value, float):
            held.append((spread_fraction(curve, k, count), value.value))
    if held:
        return SpreadReading(spread_ends(held), "programmer", True, True, span, tuple(held))
    seen: list[tuple[float, float]] = []
    if output is not None:
        for k, element in enumerate(selection):
            found = output_value(encoder, output.element(*element))
            if found is not None:
                seen.append((spread_fraction(curve, k, count), found))
    ends = spread_ends(seen)
    return SpreadReading(ends, None if ends is None else "output", bool(selection), False, span, ())


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
