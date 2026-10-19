"""GDTF import (phase-7-plan §5.19, decision 21).

:func:`read_gdtf` reads a ``.gdtf`` file (a ZIP archive) and
:func:`import_gdtf` turns its ``description.xml`` into a busk
:class:`~busk.model.profile.FixtureProfile`. GDTF is DIN SPEC 15800; busk
imports a subset of it and reports, in the import notes, what it leaves out.

**Reading.** Only ``description.xml`` is read, at most
:data:`DESCRIPTION_CAP` bytes uncompressed. It is parsed by expat with a
``DOCTYPE`` refused outright, so no entity can be declared, let alone
expanded (no "billion laughs", no external entities).

**What is read**: the ``FixtureType`` (``Name``, ``Manufacturer``,
``FixtureTypeID``, the newest ``Revision``), its ``Wheels``, the
``PhysicalDescriptions/Emitters``, the ``Geometries`` (to find
``GeometryReference`` instances), and each ``DMXMode``'s ``DMXChannels``:
``Offset`` (``"1,2"`` = coarse, fine), ``Default``, ``Highlight``,
``LogicalChannel@Attribute``, the ``ChannelFunction``\\ s (``DMXFrom``,
``PhysicalFrom``/``To``, ``Wheel``, ``Emitter``) and their ``ChannelSet``\\ s
(``WheelSlotIndex``).

**DMX values** are written ``value/bytes`` (:func:`dmx_value`): ``128/1`` on
a 16-bit channel is byte-mirrored to ``0x8080``; ``128/1s`` is byte-shifted
to ``0x8000``. A channel function spans from its ``DMXFrom`` to the next
function's, a channel set likewise within its function.

**Attributes.** A channel's busk attribute is that of its logical channel's
GDTF attribute, else of its first channel function busk can drive:

==========================================  ===================================
GDTF                                        busk
==========================================  ===================================
``Dimmer``, ``Fog1``, ``Haze1``             ``intensity`` (fog is intensity, so
                                            the masters and blackout apply)
``Pan``, ``Tilt``                           ``pan``, ``tilt`` (physical degrees,
                                            centred on the channel's travel)
``ColorAdd_R/G/B/W/A/RY/UV/C/GY``,          the emitters ``red``, ``green``,
``ColorRGB_Red/Green/Blue/Cyan``            ``blue``, ``white``, ``amber``,
                                            ``uv``, ``cyan``, ``lime``; the
                                            function's emitter colour (CIE xyY →
                                            linear sRGB) calibrates them
``ColorAdd_M/Y/WW/CW``, other ``ColorAdd_``  custom emitters, coloured by the
                                            file's emitter or estimated
``ColorSub_C/M/Y``                          ``cyanFlag``, ``magentaFlag``,
                                            ``yellowFlag``
``Color1``, ``Gobo1``, ``Gobo2``,           ``colorWheel``, ``gobo1``,
``Prism1``                                  ``gobo2``, ``prism`` (slots from
                                            the wheel, by ``WheelSlotIndex``)
``Gobo1PosRotate``, ``Gobo2PosRotate``,     ``gobo1Rotation``, ``gobo2Rotation``,
``Prism1PosRotate``                         ``prismRotation`` (°/s)
``Zoom``, ``Focus1``, ``Iris``,             ``zoom`` (degrees), ``focus``,
``Frost1``, ``CTO``                         ``iris``, ``frost``, ``cto``
``Shutter1``                                ``shutter``: channel sets named
                                            Open and Closed; ``Shutter1Strobe``,
                                            ``…StrobePulse``, ``…StrobeRandom``
                                            → ``strobe``, ``pulse``, ``random``
                                            with their ``strobeRate`` in Hz
``Shutter1Strobe``, ``StrobeFrequency``     ``strobeRate`` (a channel of its own)
``PositionMSpeed``                          ``positionSpeed`` (0 = fastest)
``ColorMacro1``, ``ColorEffects1``          ``colorMacro``, ``colorEffect``
``ColorMacro1Rate``                         ``colorMacroRate`` (0…1)
everything else                             a ``control`` channel held at its
                                            default and reported
==========================================  ===================================

The channel's other functions are never output, except dead bands, as in the
OFL import (:mod:`busk.importers.ofl`): ``NoFeature``, and the index
(``…Pos``) function of a rotation channel, whose first DMX value is the
attribute's rest value. Normalised attributes (``intensity``, ``focus``,
``iris``, ``frost``) take the physical values when they lie in 0…1, else
the channel's physical span is scaled to 0…1 (reported); ``cto`` outside
0…1 is read as kelvin.

**Colour macros.** On a ``colorMacro`` or ``colorEffect`` channel every
function and channel set is an option. The channel sets of a colour
function (``Color1``, ``ColorMacro1``, ``ColorEffects1``) linked to a wheel
are slots of that wheel (by ``WheelSlotIndex``); every other set,
and a function without sets, is a function named after it. ``NoFeature`` and
sets named like "No function", "Safe", "Open" or "No macro" are ``off``. A
strobe function keeps its rate as ``strobeRate`` (so the strobe cap holds),
a ``ColorMacro1Rate`` function its own as ``colorMacroRate``. Nothing
controlling the channel, it outputs the option its default selects.
``ColorMacro2``, ``ColorEffects2`` and later are ``control``.

**Elements.** One per ``GeometryReference`` under the mode's geometry, in
DMX order, named after the reference: the mode's channels on the referenced
geometry (or below it) are templates, placed at each instance's ``Break``
``DMXOffset``. Other channels go on element 0. A mode without references has
one element.

**Reported and not imported**: channel functions with a ``ModeMaster``,
channels on a DMX break other than the mode's first (busk patches one
address per fixture), virtual channels (no ``Offset``), ``DMXProfile``
curves (imported as linear), relations and macros.

**Identity.** The id is ``gdtf-<FixtureTypeID>``, the name ``<Manufacturer>
<Name>``, and the revision the newest revision's date plus a short hash of
``description.xml``, so an edited file is a new revision (§17).
"""

from __future__ import annotations

import hashlib
import os
import re
import zipfile
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal, cast
from xml.etree import ElementTree as ET
from xml.parsers import expat

from busk.importers import ImportFailed, ImportReport
from busk.importers.ofl import (
    _REST,
    CUSTOM,
    _camel,
    _check,
    _default_option,
    _function,
    _slug,
    _top,
    _unique,
)
from busk.model.attributes import ColorValue
from busk.model.common import ModeId
from busk.model.profile import (
    MACRO_ATTRIBUTES,
    Capability,
    ChannelDefinition,
    ElementDefinition,
    Emitter,
    FixtureMode,
    FixturePhysical,
    FixtureProfile,
    FunctionCapability,
    RangeCapability,
    SlotCapability,
    Wheel,
    WheelSlot,
    option_capabilities,
)

DESCRIPTION_CAP: Final = 32 * 1024 * 1024
"""The largest ``description.xml`` read, uncompressed, in bytes."""

ATTRIBUTES: Final[Mapping[str, str]] = {
    "Dimmer": "intensity",
    "Fog1": "intensity",
    "Haze1": "intensity",
    "Pan": "pan",
    "Tilt": "tilt",
    "Color1": "colorWheel",
    "CTO": "cto",
    "Gobo1": "gobo1",
    "Gobo2": "gobo2",
    "Gobo1PosRotate": "gobo1Rotation",
    "Gobo2PosRotate": "gobo2Rotation",
    "Prism1": "prism",
    "Prism1PosRotate": "prismRotation",
    "Zoom": "zoom",
    "Focus1": "focus",
    "Iris": "iris",
    "Frost1": "frost",
    "Shutter1": "shutter",
    "Shutter1Strobe": "strobeRate",
    "StrobeFrequency": "strobeRate",
    "PositionMSpeed": "positionSpeed",
    "ColorMacro1": "colorMacro",
    "ColorMacro1Rate": "colorMacroRate",
    "ColorEffects1": "colorEffect",
}
"""GDTF attributes busk drives (colours apart), by busk attribute."""

ADDITIVE: Final[Mapping[str, str]] = {
    "R": "red",
    "G": "green",
    "B": "blue",
    "W": "white",
    "A": "amber",
    "RY": "amber",
    "UV": "uv",
    "C": "cyan",
    "GY": "lime",
}
"""``ColorAdd_`` suffixes that are busk's built-in additive emitters."""

CUSTOM_ADDITIVE: Final[Mapping[str, str]] = {
    "M": "Magenta",
    "Y": "Yellow",
    "WW": "Warm White",
    "CW": "Cold White",
}
"""``ColorAdd_`` suffixes with a custom emitter and an estimated colour (the
OFL import's :data:`~busk.importers.ofl.CUSTOM`, by its colour name)."""

RGB: Final[Mapping[str, str]] = {
    "Red": "R",
    "Green": "G",
    "Blue": "B",
    "Cyan": "C",
    "Magenta": "M",
    "Yellow": "Y",
}
"""``ColorRGB_`` suffixes, as the ``ColorAdd_`` suffix they mean."""

SUBTRACTIVE: Final[Mapping[str, str]] = {"C": "cyanFlag", "M": "magentaFlag", "Y": "yellowFlag"}
"""``ColorSub_`` suffixes: busk's subtractive flags."""

SHUTTER: Final[Mapping[str, str]] = {
    "Shutter1Strobe": "strobe",
    "Shutter1StrobePulse": "pulse",
    "Shutter1StrobeRandom": "random",
}
"""Channel functions of a ``Shutter1`` channel that are strobing shutter options."""

WHEEL_KINDS: Final[Mapping[str, Literal["color", "gobo", "prism"]]] = {
    "colorWheel": "color",
    "gobo1": "gobo",
    "gobo2": "gobo",
    "prism": "prism",
    "colorMacro": "color",
    "colorEffect": "color",
}

_XYZ_TO_SRGB: Final = (
    (3.2404542, -1.5371385, -0.4985314),
    (-0.9692660, 1.8760108, 0.0415560),
    (0.0556434, -0.2040259, 1.0572252),
)
"""CIE XYZ → linear sRGB (D65 white), IEC 61966-2-1."""

_DMX: Final = re.compile(r"(\d+)(?:/([1-4])(s?))?")
_INDEX: Final = re.compile(r"(Gobo[12]|Prism1)Pos")
"""The index (angle) function of a rotation channel: a dead band."""
_NORMALISED: Final = frozenset({"intensity", "focus", "iris", "frost", "colorMacroRate"})
_OFF: Final = re.compile(
    r"(no ?(function|fonction|feature|macro|colou?r ?macro|effect)s?|off|none|open|safe|normal)"
    r"\b.*",
    re.IGNORECASE,
)
"""Channel set names that mean "no macro" on a colour macro channel: ``off``."""

_Values = Callable[[tuple[float, float]], tuple[float, float]]
"""Physical values of a channel function → the attribute's logical values."""


# ------------------------------------------------------------------ entry points


def read_gdtf(path: str | os.PathLike[str], *, manufacturer: str | None = None) -> ImportReport:
    """Import the GDTF file at ``path`` (the manufacturer: ``manufacturer``,
    else the file's own). Raises :class:`ImportFailed`, also for files that
    cannot be read or are not ZIP archives."""
    try:
        with zipfile.ZipFile(path) as archive:
            description = _description(archive)
    except ImportFailed:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
        raise ImportFailed(f"not a GDTF file: {exc}") from exc
    return import_gdtf(description, manufacturer=manufacturer)


def import_gdtf(description: bytes, *, manufacturer: str | None = None) -> ImportReport:
    """The busk profile of a GDTF ``description.xml`` and the import's notes."""
    root = parse_description(description)
    fixture_type = root.find("FixtureType")
    if root.tag != "GDTF" or fixture_type is None:
        raise ImportFailed("not a GDTF description: it has no GDTF/FixtureType")
    if not fixture_type.get("FixtureTypeID"):
        raise ImportFailed("the fixture type has no FixtureTypeID")
    fixture = _FixtureType(fixture_type, description, manufacturer)
    modes: list[FixtureMode] = []
    mode_ids: set[str] = set()
    for node in fixture_type.iterfind("DMXModes/DMXMode"):
        name = node.get("Name", "?")
        try:
            mode = _ModeBuilder(fixture, node, _unique(_slug(name, "mode-"), mode_ids)).build()
        except _SkipMode as exc:
            fixture.note(f"mode {name!r} skipped: {exc}")
            continue
        problem = _check(fixture.profile([mode]))
        if problem:
            fixture.note(f"mode {name!r} skipped: {problem}")
            continue
        mode_ids.add(mode["id"])
        modes.append(mode)
    if not modes:
        reasons = "; ".join(fixture.notes) or "it has no DMX modes"
        raise ImportFailed(f"no mode could be imported ({reasons})")
    profile = fixture.profile(modes)
    problem = _check(profile)
    if problem:
        raise ImportFailed(problem)
    return ImportReport(profile=profile, notes=fixture.notes)


def parse_description(data: bytes) -> ET.Element:
    """``description.xml`` as an element tree. A ``DOCTYPE`` is refused
    before anything in it is read, so the file cannot declare entities."""
    builder = ET.TreeBuilder()
    parser = expat.ParserCreate()

    def doctype(*_: object) -> None:
        raise ImportFailed("description.xml declares a DOCTYPE, which busk refuses")

    parser.StartDoctypeDeclHandler = doctype
    parser.StartElementHandler = builder.start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    try:
        parser.Parse(data, True)
    except expat.ExpatError as exc:
        raise ImportFailed(f"description.xml is not well-formed XML: {exc}") from exc
    return builder.close()


def dmx_value(text: str, nbytes: int) -> int:
    """A GDTF DMX value (``"value/bytes"``) as a raw value of a channel of
    ``nbytes`` bytes.

    A coarser value is byte-mirrored, as the spec says: its bytes repeat to
    fill the channel (``255/1`` on 16 bits is 65535, ``128/1`` is 0x8080).
    With an ``s`` suffix it is byte-shifted instead (``255/1s`` is 65280). A
    finer value keeps its top bytes. A bare number is taken at the channel's
    resolution. Raises :class:`ValueError` for anything else.
    """
    match = _DMX.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"not a GDTF DMX value: {text!r}")
    value = int(match[1])
    given = int(match[2]) if match[2] else nbytes
    if value > _top(given):
        raise ValueError(f"DMX value {text!r} does not fit {given} byte(s)")
    if given >= nbytes:
        return value >> (8 * (given - nbytes))
    if match[3]:
        return value << (8 * (nbytes - given))
    parts = value.to_bytes(given, "big")
    return int.from_bytes(bytes(parts[k % given] for k in range(nbytes)), "big")


def xyy_to_linear_rgb(x: float, y: float, luminance: float) -> tuple[float, float, float]:
    """CIE xyY as linear sRGB (D65), unclipped: out-of-gamut colours have
    negative components. ``y == 0`` is black."""
    if y <= 0:
        return 0.0, 0.0, 0.0
    big_x, big_z = x * luminance / y, (1 - x - y) * luminance / y
    r, g, b = (row[0] * big_x + row[1] * luminance + row[2] * big_z for row in _XYZ_TO_SRGB)
    return r, g, b


def _description(archive: zipfile.ZipFile) -> bytes:
    """The archive's ``description.xml``, refused above :data:`DESCRIPTION_CAP`
    (by its declared size, and by what it really inflates to)."""
    try:
        info = archive.getinfo("description.xml")
    except KeyError:
        raise ImportFailed("not a GDTF file: it has no description.xml") from None
    too_big = ImportFailed(
        f"description.xml is larger than {DESCRIPTION_CAP // (1024 * 1024)} MB; not read"
    )
    if info.file_size > DESCRIPTION_CAP:
        raise too_big
    with archive.open(info) as member:
        data = member.read(DESCRIPTION_CAP + 1)
    if len(data) > DESCRIPTION_CAP:
        raise too_big
    return data


def _colour(text: str | None) -> ColorValue | None:
    """A GDTF colour (``"x,y,Y"``) as linear RGB, clipped at 0 and scaled so
    its largest component is 1 (the colour, not the brightness), to three
    decimals. ``None`` when missing or black."""
    if not text:
        return None
    try:
        x, y, _ = (float(part) for part in text.split(","))
    except ValueError:
        return None
    rgb = [max(0.0, c) for c in xyy_to_linear_rgb(x, y, 1.0)]
    top = max(rgb)
    if top <= 0:
        return None
    r, g, b = (round(c / top, 3) for c in rgb)
    return ColorValue(r=r, g=g, b=b)


# ------------------------------------------------------------------ the fixture type


class _SkipMode(Exception):
    """A mode that cannot be imported; the message says why."""


class _Unmapped(Exception):
    """A function busk cannot express on its attribute: the channel becomes control."""


@dataclass
class _Set:
    """A channel set: a named span of a channel function."""

    name: str
    low: int
    high: int = 0
    slot: int | None = None  # WheelSlotIndex, 1-based


@dataclass
class _Function:
    """A channel function at its channel's resolution."""

    name: str
    attribute: str
    low: int
    physical: tuple[float, float]
    wheel: str | None
    emitter: str | None
    default: int
    sets: list[_Set]
    high: int = 0


@dataclass
class _Channel:
    """A DMX channel of a mode, before it is placed (template channels of a
    geometry reference are placed once per instance)."""

    name: str
    geometry: str
    attribute: str  # the logical channel's GDTF attribute
    offsets: list[int]  # relative, 1-based, coarse first
    dmx_break: str  # "1", "2" … or "Overwrite"
    functions: list[_Function]
    default: int
    highlight: int | None
    held: bool = False  # every function depends on a mode master


@dataclass
class _Instance:
    """A ``GeometryReference``: an element of the mode."""

    name: str
    geometry: str
    breaks: list[tuple[str, int]]  # (DMXBreak, DMXOffset), in file order

    def offset(self, dmx_break: str) -> tuple[str, int] | None:
        """The break and 1-based DMX offset of this instance's channels on
        ``dmx_break`` (``Overwrite``: the reference's last break)."""
        if dmx_break == "Overwrite":
            return self.breaks[-1] if self.breaks else None
        return next(((b, o) for b, o in self.breaks if b == dmx_break), None)


@dataclass
class _FixtureType:
    """The parsed fixture type and what the import learns across its modes."""

    node: ET.Element
    description: bytes
    manufacturer: str | None
    lines: list[str] = field(default_factory=list)  # the notes, in order
    wheels: dict[str, Wheel] = field(default_factory=dict)  # by GDTF name, as used
    emitters: dict[str, Emitter] = field(default_factory=dict)  # declared, by busk id
    physical: FixturePhysical = field(default_factory=FixturePhysical)
    geometries: dict[str, ET.Element] = field(default_factory=dict)
    parents: dict[str, str | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for top in self.node.iterfind("Geometries/*"):
            self._index(top, None)
        self.colours = {
            node.get("Name", ""): _colour(node.get("Color"))
            for node in self.node.iterfind("PhysicalDescriptions/Emitters/Emitter")
        }

    @property
    def notes(self) -> tuple[str, ...]:
        return tuple(self.lines)

    def note(self, line: str) -> None:
        if line not in self.lines:
            self.lines.append(line)

    def profile(self, modes: list[FixtureMode]) -> FixtureProfile:
        node = self.node
        name = node.get("Name", "?")
        manufacturer = self.manufacturer or node.get("Manufacturer") or "Unknown"
        ident = node.get("FixtureTypeID", "").lower()
        notes = f"Imported from the GDTF fixture type {name!r} ({ident})."
        if node.get("Description"):
            notes += f" {node.get('Description')}"
        profile: dict[str, Any] = {
            "id": f"gdtf-{ident}",
            "name": f"{manufacturer} {name}",
            "manufacturer": manufacturer,
            "model": name,
            "revision": self._revision(),
            "source": "gdtf",
            "notes": notes,
            "physical": dict(self.physical),
            "wheels": list(self.wheels.values()),
            "modes": modes,
        }
        if self.emitters:
            profile["emitters"] = list(self.emitters.values())
        return cast(FixtureProfile, profile)

    def _revision(self) -> str:
        """The newest revision's date plus 7 hex digits of the file's hash."""
        digest = hashlib.sha256(self.description).hexdigest()[:7]
        dates = [r.get("Date", "") for r in self.node.iterfind("Revisions/Revision")]
        newest = max(dates, default="")
        return f"{newest[:10]}-{digest}" if newest else digest

    # -- geometry

    def _index(self, node: ET.Element, parent: str | None) -> None:
        name = node.get("Name")
        if name is None or node.tag == "Break":
            return
        self.geometries.setdefault(name, node)
        self.parents.setdefault(name, parent)
        for child in node:
            self._index(child, name)

    def top_of(self, geometry: str) -> str:
        """The top-level geometry ``geometry`` is part of."""
        seen: set[str] = set()
        while (parent := self.parents.get(geometry)) is not None and geometry not in seen:
            seen.add(geometry)
            geometry = parent
        return geometry

    def instances(self, top: str) -> list[_Instance]:
        """The geometry references under ``top``, in DMX order."""
        node = self.geometries.get(top)
        if node is None:
            return []
        found: list[_Instance] = []
        for ref in node.iter("GeometryReference"):
            breaks = [
                (b.get("DMXBreak", "1"), int(b.get("DMXOffset", "1")))
                for b in ref.iterfind("Break")
            ]
            found.append(_Instance(ref.get("Name", "?"), ref.get("Geometry", ""), breaks))
        return sorted(found, key=lambda i: min(((_break(b), o) for b, o in i.breaks),
                                               default=(0, 0))[1])  # fmt: skip

    # -- wheels and emitters

    def wheel(self, name: str, attribute: str) -> Wheel | None:
        """The busk wheel of GDTF wheel ``name``, built the first time an
        attribute uses it (GDTF wheels have no kind; the attribute gives it)."""
        if name in self.wheels:
            return self.wheels[name]
        node = next((w for w in self.node.iterfind("Wheels/Wheel") if w.get("Name") == name), None)
        if node is None:
            return None
        kind = WHEEL_KINDS[attribute]
        ids: set[str] = set()
        slots: list[WheelSlot] = []
        for k, slot in enumerate(node.iterfind("Slot")):
            slots.append(_wheel_slot(slot, k, kind, ids))
        wheel = Wheel(id=_unique(_camel(name) or "wheel", {w["id"] for w in self.wheels.values()}),
                      kind=kind, slots=slots)  # fmt: skip
        self.wheels[name] = wheel
        return wheel

    def component(self, attribute: str, function: _Function) -> str | None:
        """The busk emitter of a colour attribute (``ColorAdd_R`` …), declaring
        it when the file gives its colour or busk must estimate one."""
        match = re.fullmatch(r"Color(Add|RGB|Sub)_(\w+)", attribute)
        if match is None:
            return None
        system, suffix = match.groups()
        if system == "Sub":
            return SUBTRACTIVE.get(suffix)
        if system == "RGB":
            if suffix not in RGB:
                return None
            suffix = RGB[suffix]
        colour = self.colours.get(function.emitter or "")
        if suffix in ADDITIVE:
            ident = ADDITIVE[suffix]
            if colour is not None:  # the file's measured colour calibrates the built-in one
                self.emitters.setdefault(ident, Emitter(id=ident, color=colour))
            return ident
        if suffix in CUSTOM_ADDITIVE:
            ident, estimate = CUSTOM[CUSTOM_ADDITIVE[suffix]]
            if colour is None:
                self.note(f"{attribute}: a custom emitter with an estimated colour")
            self.emitters.setdefault(ident, Emitter(id=ident, color=colour or estimate))
            return ident
        if colour is None or not function.emitter:
            return None
        ident = _camel(function.emitter)
        self.emitters.setdefault(ident, Emitter(id=ident, color=colour))
        return ident

    def widen(self, key: Literal["panRange", "tiltRange", "maxStrobeHz"], value: float) -> None:
        if value > self.physical.get(key, 0.0):
            self.physical[key] = value

    def widen_zoom(self, low: float, high: float) -> None:
        old = self.physical.get("zoomRange")
        if old is not None:
            low, high = min(low, old[0]), max(high, old[1])
        if low < high:
            self.physical["zoomRange"] = (low, high)


def _wheel_slot(node: ET.Element, k: int, kind: str, ids: set[str]) -> WheelSlot:
    """A busk slot for GDTF wheel slot ``k`` (0-based). A prism wheel's slot
    with no facets is ``off``, one with N facets ``prism<N>``."""
    name = node.get("Name", "")
    facets = len(node.findall("Facet"))
    if kind == "prism":
        ident = f"prism{facets}" if facets else "off"
        name = name or (f"{facets}-facet prism" if facets else "Off")
    elif name.casefold() == "open":
        ident = "open"
    elif name.casefold() in ("closed", "close"):
        ident = "closed"
    else:
        ident = _camel(name) or f"slot{k + 1}"
    slot = WheelSlot(id=_unique(ident, ids), name=name or f"Slot {k + 1}")
    ids.add(slot["id"])
    if kind == "prism" and facets:
        slot["facets"] = facets
    if kind == "color":
        colour = _colour(node.get("Color"))
        if colour is not None:
            slot["color"] = colour
    return slot


# ------------------------------------------------------------------ one mode


@dataclass
class _Placed:
    """A channel in a mode: its 0-based offsets (coarse first) and element."""

    channel: _Channel
    offsets: list[int]
    element: int = 0
    attribute: str = "control"
    component: str | None = None
    source: str = ""  # the GDTF attribute that chose ``attribute``


class _ModeBuilder:
    """Builds one busk mode from one GDTF ``DMXMode``."""

    def __init__(self, fixture: _FixtureType, mode: ET.Element, ident: str) -> None:
        self.fixture = fixture
        self.mode = mode
        self.ident = ident

    def build(self) -> FixtureMode:
        name = self.mode.get("Name", self.ident)
        for path, what in (("Relations/Relation", "relations"), ("FTMacros/FTMacro", "macros")):
            if self.mode.find(path) is not None:
                self.fixture.note(f"mode {name!r}: its {what} are not imported")
        instances = self.fixture.instances(self.mode.get("Geometry", ""))
        placed = self._place(instances)
        if not placed:
            raise _SkipMode("it has no channels on its first DMX break")
        footprint = max(o for p in placed for o in p.offsets) + 1
        if footprint > 512:
            raise _SkipMode(f"its {footprint} channels do not fit a universe")
        self._assign(placed)
        definitions = sorted((self._definition(p) for p in placed), key=lambda d: d["offset"])
        intensity = any(d["attribute"] == "intensity" for d in definitions)
        elements = [ElementDefinition(index=k, name=i.name) for k, i in enumerate(instances)]
        return FixtureMode(
            id=ModeId(self.ident),
            name=name,
            footprint=footprint,
            elements=elements or [ElementDefinition(index=0, name="Main")],
            intensityStrategy="dimmerChannel" if intensity else "virtual",
            dimmerCurve="linear",
            channels=definitions,
        )

    # -- placing channels

    def _place(self, instances: list[_Instance]) -> list[_Placed]:
        """Every channel at its offsets: templates once per instance; then
        only those on the mode's first DMX break."""
        candidates: list[tuple[int, _Placed]] = []  # (DMX break, placed)
        for node in self.mode.iterfind("DMXChannels/DMXChannel"):
            channel = self._channel(node)
            if channel is None:
                continue
            top = self.fixture.top_of(channel.geometry)
            refs = [k for k, i in enumerate(instances) if i.geometry == top]
            place: list[tuple[int, tuple[str, int] | None]]
            if not refs:
                if channel.dmx_break == "Overwrite":
                    self.fixture.note(f"{channel.name}: an Overwrite break outside a "
                                      "geometry reference; not imported")  # fmt: skip
                    continue
                place = [(0, (channel.dmx_break, 1))]
            else:
                place = [(k, instances[k].offset(channel.dmx_break)) for k in refs]
            for element, at in place:
                if at is None:
                    self.fixture.note(f"{channel.name}: its geometry reference has no "
                                      f"break {channel.dmx_break}; not imported")  # fmt: skip
                    continue
                dmx_break, base = at
                offsets = [base + o - 2 for o in channel.offsets]  # both 1-based
                candidates.append((_break(dmx_break), _Placed(channel, offsets, element)))
        if not candidates:
            return []
        first = min(b for b, _ in candidates)
        for b, p in candidates:
            if b != first:
                self.fixture.note(f"{p.channel.name}: on DMX break {b}; busk imports only "
                                  f"the first break ({first})")  # fmt: skip
        return [p for b, p in candidates if b == first]

    def _channel(self, node: ET.Element) -> _Channel | None:
        """A ``DMXChannel`` with its functions sorted and spanned, or
        ``None`` (reported) for a channel busk cannot place."""
        logical = node.findall("LogicalChannel")
        attribute = logical[0].get("Attribute", "") if logical else ""
        geometry = node.get("Geometry", "")
        name = node.get("Name") or f"{geometry}_{attribute}"
        text = node.get("Offset", "")
        if text in ("", "None"):
            self.fixture.note(f"{name}: a virtual channel (no DMX offset); not imported")
            return None
        try:
            offsets = [int(o) for o in text.split(",")]
        except ValueError:
            raise _SkipMode(f"{name}: bad Offset {text!r}") from None
        if len(offsets) > 3:
            self.fixture.note(f"{name}: {len(offsets)} bytes; busk channels have at most 3")
            return None
        nbytes = len(offsets)
        try:
            functions, mastered = self._functions(name, logical, nbytes)
            default = self._default(node, functions, nbytes)
            highlight = node.get("Highlight")
            highlight_dmx = (
                None if highlight in (None, "", "None") else dmx_value(highlight, nbytes)
            )
        except ValueError as exc:
            raise _SkipMode(f"{name}: {exc}") from None
        if mastered:
            self.fixture.note(f"{name}: {mastered} channel function(s) depend on a mode "
                              "master; not imported")  # fmt: skip
        channel = _Channel(name, geometry, attribute, offsets, node.get("DMXBreak", "1"),
                           functions, default, highlight_dmx)  # fmt: skip
        if not functions:
            channel.held = True  # reported above: every function has a mode master
        return channel

    def _functions(
        self, name: str, logical: list[ET.Element], nbytes: int
    ) -> tuple[list[_Function], int]:
        """The channel's functions without a mode master, by ``DMXFrom``, each
        spanning to the next one; and how many had a mode master."""
        functions: list[_Function] = []
        mastered = 0
        for node in (f for lc in logical for f in lc.iterfind("ChannelFunction")):
            if node.get("ModeMaster"):
                mastered += 1
                continue
            if node.get("DMXProfile"):
                self.fixture.note(f"{name}: DMX profile {node.get('DMXProfile')!r} "
                                  "imported as linear")  # fmt: skip
            sets = [_set(s, nbytes) for s in node.iterfind("ChannelSet")]
            functions.append(
                _Function(
                    name=node.get("Name", ""),
                    attribute=node.get("Attribute", "NoFeature"),  # the spec's default
                    low=dmx_value(node.get("DMXFrom", "0/1"), nbytes),
                    physical=(
                        float(node.get("PhysicalFrom", "0")),
                        float(node.get("PhysicalTo", "1")),
                    ),
                    wheel=node.get("Wheel") or None,
                    emitter=node.get("Emitter") or None,
                    default=dmx_value(node.get("Default", "0/1"), nbytes),
                    sets=sorted(sets, key=lambda s: s.low),
                )
            )
        functions.sort(key=lambda f: f.low)
        kept: list[_Function] = []
        for k, function in enumerate(functions):
            function.high = functions[k + 1].low - 1 if k + 1 < len(functions) else _top(nbytes)
            if function.high < function.low:
                continue  # an empty span: two functions from the same DMX value
            sets = [s for s in function.sets if function.low <= s.low <= function.high]
            for j, s in enumerate(sets):
                s.high = sets[j + 1].low - 1 if j + 1 < len(sets) else function.high
            function.sets = [s for s in sets if s.high >= s.low]
            kept.append(function)
        return kept, mastered

    def _default(self, node: ET.Element, functions: list[_Function], nbytes: int) -> int:
        """``DMXChannel@Default`` (GDTF 1.0), else the default of the
        channel's ``InitialFunction`` (1.1), else of its first function."""
        if node.get("Default"):
            return dmx_value(node.get("Default", ""), nbytes)
        initial = node.get("InitialFunction", "").rsplit(".", 1)[-1]
        chosen = next((f for f in functions if initial and f.name == initial), None)
        if chosen is None and functions:
            chosen = functions[0]
        return chosen.default if chosen is not None else 0

    # -- attributes

    def _assign(self, placed: list[_Placed]) -> None:
        """Choose each channel's attribute and colour component."""
        for p in placed:
            if p.channel.held:
                p.attribute = "held"
                continue
            channel = p.channel
            candidates = [(channel.attribute, channel.functions[0])]
            candidates += [(f.attribute, f) for f in channel.functions]
            for attribute, function in candidates:
                component = self.fixture.component(attribute, function)
                if component is not None:
                    p.attribute, p.component, p.source = "color", component, attribute
                    break
                if attribute in ATTRIBUTES:
                    p.attribute, p.source = ATTRIBUTES[attribute], attribute
                    break
        self._dedupe(placed)

    def _dedupe(self, placed: list[_Placed]) -> None:
        """Keep one channel per element and attribute (and component); an
        element's colour channels only when they make a mixing system."""
        seen: set[tuple[int, str, str | None]] = set()
        for p in placed:
            if p.attribute in ("control", "held"):
                continue
            slot = (p.element, p.attribute, p.component)
            if slot in seen:
                self.fixture.note(
                    f"{p.channel.name}: a second {p.attribute} channel; held as control"
                )
                p.attribute, p.component = "held", None
            seen.add(slot)
        by_element: dict[int, set[str]] = {}
        for p in placed:
            if p.attribute == "color" and p.component is not None:
                by_element.setdefault(p.element, set()).add(p.component)
        for p in placed:
            components = by_element.get(p.element, set())
            if p.attribute == "color" and not (
                {"red", "green", "blue"} <= components
                or {"cyanFlag", "magentaFlag", "yellowFlag"} <= components
            ):
                self.fixture.note(
                    f"{p.channel.name}: busk colour mixes red, green and blue (or cyan, "
                    "magenta and yellow); held as control"
                )
                p.attribute, p.component = "held", None

    # -- channel definitions

    def _definition(self, p: _Placed) -> ChannelDefinition:
        channel = p.channel
        coarse, fines = p.offsets[0], p.offsets[1:]
        nbytes = len(p.offsets)
        definition: dict[str, Any] = {
            "offset": coarse,
            "element": p.element,
            "attribute": p.attribute,
            "bytes": nbytes,
        }
        if fines and fines != list(range(coarse + 1, coarse + 1 + len(fines))):
            definition["fineOffsets"] = fines
        capabilities: list[Capability]
        if p.attribute in ("control", "held"):  # "held": already reported
            definition["attribute"] = "control"
            capabilities = self._controls(channel, nbytes)
            if p.attribute == "control":
                kinds = ", ".join(dict.fromkeys(
                    a for a in [channel.attribute, *(f.attribute for f in channel.functions)] if a
                ))  # fmt: skip
                self.fixture.note(
                    f"{channel.name}: no busk attribute ({kinds}); held at DMX {channel.default}"
                )
        else:
            try:
                capabilities = self._capabilities(p)
            except _Unmapped as exc:
                self.fixture.note(f"{channel.name}: {exc}; held at DMX {channel.default}")
                definition["attribute"] = "control"
                capabilities = self._controls(channel, nbytes)
        option = _default_option(definition["attribute"])
        if option is not None and option not in {
            o
            for o, _ in option_capabilities(cast(Any, {**definition, "capabilities": capabilities}))
        }:
            self.fixture.note(
                f"{channel.name}: offers no {option!r}, which busk outputs when nothing "
                f"controls {definition['attribute']}; held at DMX {channel.default}"
            )
            definition["attribute"] = "control"
            capabilities = self._controls(channel, nbytes)
        if p.component is not None and definition["attribute"] == "color":
            definition["component"] = p.component
        definition["defaultDmx"] = channel.default
        if channel.highlight is not None:
            definition["highlightDmx"] = channel.highlight
        definition["capabilities"] = capabilities
        return cast(ChannelDefinition, definition)

    def _controls(self, channel: _Channel, nbytes: int) -> list[Capability]:
        if not channel.functions:
            return [_function(0, _top(nbytes), "modeDependent")]
        return [_function(f.low, f.high, _fn(f)) for f in channel.functions]

    def _capabilities(self, p: _Placed) -> list[Capability]:
        """A driven channel's capabilities (raises :class:`_Unmapped`)."""
        attribute = p.attribute
        if attribute in MACRO_ATTRIBUTES:
            return self._macro(p)
        mapped = [f for f in p.channel.functions if self._maps(p, f)]
        values = self._value_map(p, mapped)
        out: list[Capability] = []
        for f in p.channel.functions:
            if attribute == "shutter":
                out.extend(self._shutter(f))
            elif f in mapped:
                if attribute in WHEEL_KINDS:
                    out.extend(self._slots(p, f))
                else:
                    out.append(RangeCapability(kind="range", dmx=(f.low, f.high),
                                               value=values(f.physical)))  # fmt: skip
            elif f.attribute == "NoFeature" or (
                attribute.endswith("Rotation") and _INDEX.fullmatch(f.attribute)
            ):
                out.extend(self._dead_band(p, f))
            else:
                out.append(_function(f.low, f.high, _fn(f)))
        return out

    def _maps(self, p: _Placed, f: _Function) -> bool:
        """Whether function ``f`` drives the channel's attribute."""
        if p.attribute == "color":
            return f.attribute == p.source
        return ATTRIBUTES.get(f.attribute) == p.attribute

    def _value_map(self, p: _Placed, mapped: list[_Function]) -> _Values:
        """The function turning a mapped function's physical values into the
        attribute's logical ones, and the fixture's physical ranges widened."""
        attribute, name = p.attribute, p.channel.name
        if not mapped:
            raise _Unmapped(f"no channel function drives {attribute}")
        ends = [v for f in mapped for v in f.physical]
        low, high = min(ends), max(ends)
        if attribute in ("pan", "tilt"):
            centre = (low + high) / 2
            if centre:
                self.fixture.note(f"{name}: {attribute} {low:g}…{high:g}° centred on its "
                                  f"travel, ±{(high - low) / 2:g}°")  # fmt: skip
            self.fixture.widen("panRange" if attribute == "pan" else "tiltRange", high - low)
            return lambda v: (v[0] - centre, v[1] - centre)
        if attribute == "zoom":
            self.fixture.widen_zoom(low, high)
        elif attribute == "strobeRate":
            self.fixture.widen("maxStrobeHz", high)
        elif attribute == "positionSpeed":  # 0 = fastest; PositionMSpeed is a time
            return _rescaled(low, high)
        elif attribute == "cto" and not 0 <= low <= high <= 1:  # kelvin
            return lambda v: (_kelvin(v[0]), _kelvin(v[1]))
        elif attribute in _NORMALISED and not 0 <= low <= high <= 1:
            self.fixture.note(f"{name}: physical {low:g}…{high:g} taken as 0…1")
            return _rescaled(low, high)
        return lambda v: v

    def _slots(self, p: _Placed, f: _Function) -> list[Capability]:
        """A wheel function's channel sets as slot capabilities."""
        wheel = self.fixture.wheel(f.wheel or "", p.attribute)
        if wheel is None:
            raise _Unmapped(f"{f.name or f.attribute} names no wheel of the file")
        if not f.sets:
            raise _Unmapped(f"{f.name or f.attribute} has no channel sets")
        out: list[Capability] = []
        if f.sets[0].low > f.low:
            out.append(_function(f.low, f.sets[0].low - 1, _fn(f)))
        for s in f.sets:
            if s.slot is not None and 1 <= s.slot <= len(wheel["slots"]):
                out.append(SlotCapability(kind="slot", dmx=(s.low, s.high), wheel=wheel["id"],
                                          slot=wheel["slots"][s.slot - 1]["id"]))  # fmt: skip
            else:
                out.append(_function(s.low, s.high, _camel(s.name) or _fn(f)))
        return out

    def _macro(self, p: _Placed) -> list[Capability]:
        """A colour macro or effect channel: every function and channel set
        an option (module docstring)."""
        taken: set[str] = set()
        seen: dict[tuple[int, str], str] = {}  # (function, name) → option

        def name(k: int, text: str) -> str:
            if _OFF.fullmatch(text.strip()):
                return "off"
            if (k, text) not in seen:
                seen[k, text] = _unique(_camel(text) or "function", taken)
                taken.add(seen[k, text])
            return seen[k, text]

        out: list[Capability] = []
        for k, f in enumerate(p.channel.functions):
            if f.attribute == "NoFeature":
                out.append(_function(f.low, f.high, "off"))
                continue
            default_name = re.fullmatch(re.escape(f.attribute) + r" \d+", f.name)
            own = f.attribute if not f.name or default_name else f.name
            rate = ATTRIBUTES.get(f.attribute)
            if f.attribute in SHUTTER or rate in ("strobeRate", "colorMacroRate"):
                option = _function(f.low, f.high, name(k, SHUTTER.get(f.attribute, own)))
                if rate == "colorMacroRate":
                    option["param"] = {"attribute": "colorMacroRate", "value": _unit(f.physical)}
                else:
                    self.fixture.widen("maxStrobeHz", max(f.physical))
                    option["param"] = {"attribute": "strobeRate", "value": f.physical}
                out.append(option)
                continue
            colour = WHEEL_KINDS.get(ATTRIBUTES.get(f.attribute, "")) == "color"
            wheel = self.fixture.wheel(f.wheel, p.attribute) if f.wheel and colour else None
            if not f.sets or f.sets[0].low > f.low:
                out.append(_function(f.low, f.sets[0].low - 1 if f.sets else f.high, name(k, own)))
            for s in f.sets:
                if wheel is not None and s.slot is not None and 1 <= s.slot <= len(wheel["slots"]):
                    out.append(SlotCapability(kind="slot", dmx=(s.low, s.high), wheel=wheel["id"],
                                              slot=wheel["slots"][s.slot - 1]["id"]))  # fmt: skip
                else:
                    out.append(_function(s.low, s.high, name(k, s.name or own)))
        return out

    def _shutter(self, f: _Function) -> list[Capability]:
        """A function of a ``Shutter1`` channel."""
        if f.attribute in SHUTTER:
            low, high = f.physical
            self.fixture.widen("maxStrobeHz", max(low, high))
            strobe = FunctionCapability(
                kind="function", dmx=(f.low, f.high), fn=SHUTTER[f.attribute]
            )
            strobe["param"] = {"attribute": "strobeRate", "value": (low, high)}
            return [strobe]
        if f.attribute == "NoFeature":
            return [_function(f.low, f.high, "open")]
        if f.attribute != "Shutter1":
            return [_function(f.low, f.high, _fn(f))]
        if not f.sets:
            return [_function(f.low, f.high, _shutter_state(f.name) or _fn(f))]
        out: list[Capability] = []
        if f.sets[0].low > f.low:
            out.append(_function(f.low, f.sets[0].low - 1, _fn(f)))
        out.extend(_function(s.low, s.high, _shutter_state(s.name) or _fn(f)) for s in f.sets)
        return out

    def _dead_band(self, p: _Placed, f: _Function) -> list[Capability]:
        """A ``NoFeature`` or index function on an attribute: its first DMX
        value is the attribute's rest value, the rest is never output."""
        name = "noFunction" if f.attribute == "NoFeature" else "index"
        if p.attribute == "prism":
            wheel = next(
                (self.fixture.wheel(g.wheel, "prism") for g in p.channel.functions
                 if g.wheel and ATTRIBUTES.get(g.attribute) == "prism"), None,
            )  # fmt: skip
            if wheel is not None and any(s["id"] == "off" for s in wheel["slots"]):
                return [SlotCapability(kind="slot", dmx=(f.low, f.high), wheel=wheel["id"],
                                       slot="off")]  # fmt: skip
        rest = _REST.get(p.attribute)
        if rest is None:
            return [_function(f.low, f.high, name)]
        band: list[Capability] = [RangeCapability(kind="range", dmx=(f.low, f.low),
                                                  value=(rest, rest))]  # fmt: skip
        if f.high > f.low:
            band.append(_function(f.low + 1, f.high, name))
        return band


# ------------------------------------------------------------------ helpers


def _set(node: ET.Element, nbytes: int) -> _Set:
    """A ``ChannelSet``; its span's end is filled in once its function's is known."""
    slot = node.get("WheelSlotIndex")
    return _Set(node.get("Name", ""), dmx_value(node.get("DMXFrom", "0/1"), nbytes),
                slot=int(slot) if slot else None)  # fmt: skip


def _break(text: str) -> int:
    """A DMX break number (``Overwrite`` was resolved by the instance)."""
    try:
        return int(text)
    except ValueError:
        return 1


def _kelvin(k: float) -> float:
    """A colour temperature as ``cto`` (6500 K → 0, 3200 K → 1), as the OFL import."""
    return min(1.0, max(0.0, (6500 - k) / (6500 - 3200)))


def _rescaled(low: float, high: float) -> _Values:
    """Physical ``low…high`` scaled to 0…1."""
    span = high - low or 1.0

    def scale(v: tuple[float, float]) -> tuple[float, float]:
        a, b = ((x - low) / span for x in v)
        return (a, b)

    return scale


def _unit(physical: tuple[float, float]) -> tuple[float, float]:
    """A rate's physical span as ``colorMacroRate``: as it is within 0…1, else
    0…1 in its direction."""
    low, high = physical
    if min(low, high) >= 0 and max(low, high) <= 1:
        return physical
    return (0.0, 1.0) if low <= high else (1.0, 0.0)


def _shutter_state(name: str) -> str | None:
    """``open`` or ``closed`` from a channel set's or function's name."""
    folded = name.casefold()
    if "open" in folded:
        return "open"
    if "clos" in folded:
        return "closed"
    return None


def _fn(f: _Function) -> str:
    """A never-output function's name: its GDTF attribute, camelCase."""
    return _camel(f.attribute) or _camel(f.name) or "function"
