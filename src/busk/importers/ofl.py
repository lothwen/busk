"""Open Fixture Library import (phase-7-plan §5.18, decision 20).

:func:`import_ofl` turns one OFL fixture (the JSON of
``fixtures/<manufacturer>/<key>.json`` in the OFL repository) into a busk
:class:`~busk.model.profile.FixtureProfile`; :func:`read_ofl` reads a file
and works out the manufacturer. Every OFL mode becomes a busk mode, unless
the profile validator rejects it (the mode is then skipped and reported).

**Channels.** Each channel of a mode becomes one busk channel. Its attribute
is that of its first capability busk can drive (by capability ``type``):

======================================  ==========================================
OFL                                     busk
======================================  ==========================================
``Intensity``, ``FogOutput``            ``intensity`` (fog is intensity, so the
                                        masters and blackout apply to it)
``ColorIntensity``                      a ``color`` component (custom emitters
                                        with an estimated colour for Magenta,
                                        Yellow, Indigo, Warm and Cold White);
                                        Cyan, Magenta and Yellow with no red,
                                        green or blue are subtractive flags
``ShutterStrobe``, ``StrobeSpeed``      ``shutter`` functions, ``strobeRate``
``Pan``, ``Tilt``                       ``pan``, ``tilt``, centred on the travel
``PanTiltSpeed``                        ``positionSpeed`` (fast 0, slow 1)
``WheelSlot``                           ``colorWheel``, ``gobo1``, ``gobo2``, ``prism``
``WheelSlotRotation``                   ``gobo1Rotation`` … in °/s, CW positive
                                        (``WheelRotation``, the whole wheel
                                        spinning, is never output)
``Prism``, ``PrismRotation``            ``prism`` slots, ``prismRotation``
``Zoom``, ``Focus``, ``Iris``,          ``zoom`` (degrees), ``focus``, ``iris``,
``Frost``, ``ColorTemperature``         ``frost``, ``cto``
``ColorPreset``                         ``colorMacro``: each preset a slot of the
                                        channel's macro wheel
``Effect`` ``ColorJump``, ``ColorFade``  ``colorEffect`` (on a channel with
                                        nothing else busk drives)
everything else                         a ``control`` channel held at the OFL
                                        ``defaultValue`` and reported
======================================  ==========================================

Failing all of these, a channel takes the attribute of its first program
capability (:data:`PROGRAMS`), so a strobe or wheel channel with programs
keeps its attribute:

======================================  ==========================================
OFL                                     busk
======================================  ==========================================
``Effect``                              ``effect`` (``effect2`` for an element's
                                        second effect channel; a third is held)
``EffectSpeed``                         ``effectRate`` (``colorMacroRate`` in a
                                        mode with a colour macro or effect and no
                                        other effect channel: OFL does not say
                                        whose speed it is)
``EffectDuration``                      ``effectFade``
``EffectParameter``                     ``effectAdjust``
``SoundSensitivity``                    ``soundSensitivity``
======================================  ==========================================

These scalars are on 0…1: ``slow``, ``stop``, ``instant``, ``short``, ``off``,
``low`` and ``small`` are 0, ``fast``, ``long``, ``high`` and ``big`` 1, and a
percentage is its fraction; seconds, Hz, bpm and plain numbers are rescaled
over the channel's span, ``stop`` and ``instant`` counting as 0 Hz and 0 s
(reported). Reverse speeds are functions never output.

The channel's other capabilities are functions busk never outputs, except
two kinds of dead band: ``NoFunction`` and the angle (index) range of a
rotation channel. On a scalar attribute a dead band's first DMX value is the
attribute's rest value (intensity 0, rotation stopped, a program's speed or
sensitivity 0) and the rest is never output; on ``shutter`` it is ``open``,
on ``prism`` the ``off`` slot.

**Colour macros and fixture effects.** On a ``colorMacro``, ``colorEffect``,
``effect`` or ``effect2`` channel every capability is an option, except
``Maintenance`` (named ``maintenance``, never output). A preset is a slot of
a wheel made for the channel (``macro1`` …, its colour the mean of the
preset's ``colors``; sweeps and colour temperatures have none),
``NoFunction`` is ``off``, and any other capability a function named after
its effect name, comment or type. On a colour channel an ``Effect``'s speed
becomes the option's ``colorMacroRate`` (slow 0, fast 1, percentages of full
speed). On an effect channel a program's first speed, duration, parameter or
sound sensitivity becomes its ``effectRate``, ``effectFade``,
``effectAdjust`` or ``soundSensitivity`` (a second one is reported). A
strobe keeps its ``strobeRate``, so the strobe cap holds. A repeated name is
one option when the two capabilities are the same (the second "Red" of a
chart), else a numbered one. Nothing controlling the channel, it outputs the
option its ``defaultValue`` selects.

**Modelling rules** (decision 20).

* A mode whose colour channels are only whites or UV makes each of them its
  own ``intensity`` element, and holds the master ``Intensity`` channel at
  full (busk colour needs red, green and blue; the masters then dim the dies
  once, not twice).
* Speeds given only as ``slow…fast`` are estimates: strobe 1–20 Hz, rotation
  10–360 °/s. Each estimate is reported.
* An element whose colour channels lack a primary (busk colour mixes red,
  green and blue, or cyan, magenta and yellow) keeps them as control
  channels, reported.

**DMX values.** ``fineChannelAliases`` give 16- and 24-bit channels, their
fine bytes wherever the mode puts them. Ranges are written in the channel's
``dmxValueResolution`` (default: its finest) and scaled to the bytes the mode
uses: a coarse-only mode drops the fine bytes, an 8-bit range on a 16-bit
channel covers ``start·256 … end·256 + 255``. ``defaultValue`` and
``highlightValue`` (numbers or percentages) give ``defaultDmx`` and
``highlightDmx``. ``null`` mode entries leave an offset unused. A switching
channel keeps the channel its trigger's default selects (reported).

**Matrices.** ``matrixChannels`` inserts make one element per pixel or pixel
group, in ``repeatFor`` order, ``perPixel`` or ``perChannel``. Channels
outside the matrix go on element 0, the first pixel.

**Identity.** The id is ``ofl-<manufacturer>-<key>``, the name
``<manufacturer> <OFL name>``, and the revision the OFL ``lastModifyDate``
plus a short hash of the fixture's content and
:data:`~busk.importers.IMPORT_VERSION`, so an edited file, or a busk that
imports it differently, is a new revision (§17: a show never takes it
silently).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import Any, Final, Literal, cast

from busk.importers import IMPORT_VERSION, ImportFailed, ImportReport
from busk.model.attributes import ATTRIBUTES, ColorValue
from busk.model.common import ModeId
from busk.model.profile import (
    MACRO_ATTRIBUTES,
    MAINTENANCE_FUNCTIONS,
    Capability,
    CapabilityParam,
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

STROBE_ESTIMATE: Final = (1.0, 20.0)
"""Hz taken for a strobe speed given only as ``slow`` … ``fast``."""

ROTATION_ESTIMATE: Final = (10.0, 360.0)
"""°/s taken for a rotation speed given only as ``slow`` … ``fast``."""

ADDITIVE: Final[Mapping[str, str]] = {
    "Red": "red",
    "Green": "green",
    "Blue": "blue",
    "White": "white",
    "Amber": "amber",
    "UV": "uv",
    "Cyan": "cyan",
    "Lime": "lime",
}
"""OFL colours that are busk's built-in additive emitters."""

CUSTOM: Final[Mapping[str, tuple[str, ColorValue]]] = {
    "Magenta": ("magenta", ColorValue(r=1.0, g=0.0, b=1.0)),
    "Yellow": ("yellow", ColorValue(r=1.0, g=1.0, b=0.0)),
    "Indigo": ("indigo", ColorValue(r=0.07, g=0.0, b=0.22)),
    "Warm White": ("warmWhite", ColorValue(r=1.0, g=0.62, b=0.3)),
    "Cold White": ("coldWhite", ColorValue(r=0.85, g=0.92, b=1.0)),
}
"""OFL colours with no built-in emitter: a custom one, its colour (linear
RGB) an estimate."""

FLAGS: Final[Mapping[str, str]] = {
    "Cyan": "cyanFlag",
    "Magenta": "magentaFlag",
    "Yellow": "yellowFlag",
}
"""Cyan, magenta and yellow in a mode with no red, green or blue: CMY mixing."""

WHITES: Final = frozenset({"White", "Warm White", "Cold White", "UV"})
"""The colours of decision 20's white-only rule."""

PROGRAMS: Final[Mapping[str, str]] = {
    "Effect": "effect",
    "EffectSpeed": "effectRate",
    "EffectDuration": "effectFade",
    "EffectParameter": "effectAdjust",
    "SoundSensitivity": "soundSensitivity",
}
"""Capability types of the programs built into a fixture, and the attribute
each gives a channel on which nothing else busk drives (the last resort)."""

PROGRAM_PARAMETERS: Final = (
    ("speed", "effectRate"),
    ("duration", "effectFade"),
    ("parameter", "effectAdjust"),
    ("soundSensitivity", "soundSensitivity"),
)
"""The properties of a program capability that become an option's parameter,
in the order in which the first one present wins."""

_RESOLUTIONS: Final = {"8bit": 1, "16bit": 2, "24bit": 3}
_REST: Final[Mapping[str, float]] = {
    "intensity": 0.0,
    "strobeRate": 0.0,
    "gobo1Rotation": 0.0,
    "gobo2Rotation": 0.0,
    "prismRotation": 0.0,
    "iris": 1.0,
    "frost": 0.0,
    "cto": 0.0,
    "colorMacroRate": 0.0,
    "effectRate": 0.0,
    "effectFade": 0.0,
    "effectAdjust": 0.0,
    "effectRotation": 0.0,
    "effectSync": 0.0,
    "soundSensitivity": 0.0,
}
"""The value a dead band stands for, per scalar attribute that has one."""

_ENTITY = re.compile(r"^(-?\d+(?:\.\d+)?(?:e-?\d+)?)\s*(%|deg|Hz|bpm|rpm|s|ms|K|lm|m)?$")
_WORDS: Final[Mapping[str, Mapping[str, float]]] = {
    "speed": {"slow": 0, "stop": 0, "fast": 1},
    "duration": {"instant": 0, "short": 0, "long": 1},
    "parameter": {
        "off": 0, "low": 0, "small": 0, "slow": 0, "instant": 0, "short": 0,
        "high": 1, "big": 1, "fast": 1, "long": 1,
    },
    "soundSensitivity": {"off": 0, "low": 0, "high": 1},
}  # fmt: skip
"""The keywords of a program property, on 0…1."""
_UNITS: Final[Mapping[str | None, tuple[str, float]]] = {
    "Hz": ("Hz", 1.0),
    "bpm": ("Hz", 1 / 60),
    "s": ("s", 1.0),
    "ms": ("s", 0.001),
    None: ("", 1.0),
}
"""A program property's units with a physical value: its dimension and scale."""


# ------------------------------------------------------------------ entry points


def read_ofl(path: str | os.PathLike[str], *, manufacturer: str | None = None) -> ImportReport:
    """Import the OFL fixture file at ``path``.

    The manufacturer is ``manufacturer``, else the OFL repository layout's
    directory (``fixtures/<manufacturer>/<key>.json``) unless the file's
    directory is named ``fixtures``, else ``"Unknown"``. The key is the
    file's stem. Raises :class:`ImportFailed` (also for unreadable files).
    """
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImportFailed(str(exc)) from exc
    if manufacturer is None:
        manufacturer = manufacturer_of(path)
    return import_ofl(data, manufacturer=manufacturer, key=path.stem)


def manufacturer_of(path: Path) -> str:
    """The manufacturer the OFL repository layout gives a fixture file: its
    directory's name (``fixtures/<manufacturer>/<key>.json``), or
    ``"Unknown"`` when the directory is named ``fixtures``."""
    folder = path.resolve().parent.name
    return folder if folder and folder != "fixtures" else "Unknown"


def is_ofl(data: object) -> bool:
    """Whether a JSON document is an OFL fixture (it has ``availableChannels``)."""
    return isinstance(data, Mapping) and "availableChannels" in data


def import_ofl(data: Mapping[str, Any], *, manufacturer: str, key: str) -> ImportReport:
    """The busk profile of the OFL fixture ``data`` and the import's notes."""
    if not is_ofl(data) or not isinstance(data.get("modes"), list):
        raise ImportFailed("not an OFL fixture: it has no availableChannels or modes")
    fixture = _Fixture(data)
    modes: list[FixtureMode] = []
    mode_ids: set[str] = set()
    for ofl_mode in data["modes"]:
        name = str(ofl_mode.get("name", "?"))
        try:
            mode = _ModeBuilder(fixture, ofl_mode, _unique(_slug(name, "mode-"), mode_ids)).build()
        except _SkipMode as exc:
            fixture.note(f"mode {name!r} skipped: {exc}")
            continue
        problem = _check(fixture.profile([mode], manufacturer, key))
        if problem:
            fixture.note(f"mode {name!r} skipped: {problem}")
            continue
        mode_ids.add(mode["id"])
        modes.append(mode)
    if not modes:
        reasons = "; ".join(fixture.notes) or "it has no modes"
        raise ImportFailed(f"no mode could be imported ({reasons})")
    profile = fixture.profile(modes, manufacturer, key)
    problem = _check(profile)
    if problem:
        raise ImportFailed(problem)
    return ImportReport(profile=profile, notes=fixture.notes)


def _check(profile: FixtureProfile) -> str:
    """The profile validator's first error, or ``""``."""
    # Imported here: the library imports this module to read OFL files on load.
    from busk.session.library import validate_profile

    return validate_profile(profile)[1]


# ------------------------------------------------------------------ the fixture


class _SkipMode(Exception):
    """A mode that cannot be imported; the message says why."""


class _Unmapped(Exception):
    """A capability busk cannot express on its attribute: the channel becomes control."""


@dataclass
class _Cap:
    """One OFL capability, its DMX range in the channel's value resolution."""

    low: int
    high: int
    data: Mapping[str, Any]

    @property
    def type(self) -> str:
        return str(self.data.get("type", ""))


@dataclass
class _Channel:
    """One OFL channel (a template one is instantiated per pixel)."""

    key: str
    name: str
    data: Mapping[str, Any]
    resolution: int  # bytes of the DMX values in its capabilities and defaults
    caps: list[_Cap]
    pixel: str | None = None

    @classmethod
    def parse(cls, key: str, data: Mapping[str, Any], pixel: str | None = None) -> _Channel:
        fines = data.get("fineChannelAliases", [])
        resolution = _RESOLUTIONS.get(data.get("dmxValueResolution", ""), 1 + len(fines))
        top = _top(resolution)
        if "capability" in data:
            caps = [_Cap(0, top, data["capability"])]
        else:
            caps = [
                _Cap(int(c["dmxRange"][0]), int(c["dmxRange"][1]), c)
                for c in data.get("capabilities", [])
            ]
        if not caps:
            raise ImportFailed(f"channel {key!r} has no capability")
        name = str(data.get("name", key))
        if pixel is not None:
            name = name.replace("$pixelKey", pixel)
        return cls(key, name, data, resolution, caps, pixel)

    @property
    def fines(self) -> list[str]:
        aliases = [str(alias) for alias in self.data.get("fineChannelAliases", [])]
        if self.pixel is not None:
            aliases = [alias.replace("$pixelKey", self.pixel) for alias in aliases]
        return aliases


@dataclass
class _Wheel:
    """An OFL wheel as a busk wheel, and the attributes its channels drive."""

    name: str
    id: str
    kind: Literal["color", "gobo", "prism", "animation"]
    slots: list[WheelSlot]
    attribute: str | None  # colorWheel, gobo1, gobo2, prism; None: never busked
    rotation: str | None  # gobo1Rotation, gobo2Rotation, prismRotation

    def as_wheel(self) -> Wheel:
        return Wheel(id=self.id, kind=self.kind, slots=self.slots)


@dataclass
class _Macro:
    """The options of a colour macro or effect channel, per capability: a slot
    of the channel's macro wheel, or a function."""

    wheel: str | None  # the macro wheel's id; None: the channel has no presets
    options: list[tuple[Literal["slot", "function"], str]]


@dataclass
class _Fixture:
    """The parsed OFL fixture and what the import learns across its modes."""

    data: Mapping[str, Any]
    lines: list[str] = field(default_factory=list)  # the notes, in order
    wheels: dict[str, _Wheel] = field(default_factory=dict)  # by OFL name, in file order
    emitters: dict[str, Emitter] = field(default_factory=dict)  # custom ones used
    physical: FixturePhysical = field(default_factory=FixturePhysical)
    macros: dict[int, _Macro] = field(default_factory=dict)  # by id() of the OFL channel

    def __post_init__(self) -> None:
        self._read_wheels()

    @property
    def notes(self) -> tuple[str, ...]:
        return tuple(self.lines)

    def note(self, line: str) -> None:
        if line not in self.lines:
            self.lines.append(line)

    def profile(self, modes: list[FixtureMode], manufacturer: str, key: str) -> FixtureProfile:
        name = str(self.data.get("name", key))
        profile: dict[str, Any] = {
            "id": f"ofl-{_slug(manufacturer)}-{_slug(key)}",
            "name": f"{manufacturer} {name}",
            "manufacturer": manufacturer,
            "model": name,
            "revision": _revision(self.data),
            "source": "ofl",
            "notes": f"Imported from the Open Fixture Library fixture {key!r}."
            + (f" {self.data['comment']}" if self.data.get("comment") else ""),
            "physical": self._physical(),
            "wheels": [wheel.as_wheel() for wheel in self.wheels.values()],
            "modes": modes,
        }
        if self.emitters:
            profile["emitters"] = list(self.emitters.values())
        return cast(FixtureProfile, profile)

    # -- channels

    def channel(self, name: str) -> tuple[_Channel, int] | None:
        """The channel a mode entry names, and which byte: 0 coarse, k the
        k-th fine alias. Template channels resolve per pixel key."""
        available: Mapping[str, Any] = self.data["availableChannels"]
        if name in available:
            return _Channel.parse(name, available[name]), 0
        for key, data in available.items():
            fines = data.get("fineChannelAliases", [])
            if name in fines:
                return _Channel.parse(key, data), fines.index(name) + 1
        pixels = [*self.pixel_keys(), *self.data.get("matrix", {}).get("pixelGroups", {})]
        for template, data in self.data.get("templateChannels", {}).items():
            names = [template, *data.get("fineChannelAliases", [])]
            for pixel in pixels:
                for k, pattern in enumerate(names):
                    if pattern.replace("$pixelKey", pixel) == name:
                        return _Channel.parse(template.replace("$pixelKey", pixel), data, pixel), k
        return None

    def switched(self, alias: str) -> tuple[str, str] | None:
        """For a switching channel ``alias``: the channel its trigger's
        default selects, and the trigger's name."""
        for key, data in self.data["availableChannels"].items():
            channel = _Channel.parse(key, data)
            if not any(alias in cap.data.get("switchChannels", {}) for cap in channel.caps):
                continue
            default = _raw(data.get("defaultValue", 0), channel.resolution, channel.resolution)
            for cap in channel.caps:
                if cap.low <= default <= cap.high and alias in cap.data.get("switchChannels", {}):
                    return str(cap.data["switchChannels"][alias]), channel.name
            first = next(c for c in channel.caps if alias in c.data.get("switchChannels", {}))
            return str(first.data["switchChannels"][alias]), channel.name
        return None

    # -- matrix

    def pixel_keys(self) -> list[str]:
        """Every pixel key, in XYZ order (x fastest)."""
        return [key for key, _ in self._pixels()]

    def pixel_order(self, repeat: Any) -> list[str]:
        """The pixel (or group) keys of a ``repeatFor``."""
        if isinstance(repeat, list):
            return [str(key) for key in repeat]
        if repeat == "eachPixelGroup":
            groups = list(self.data.get("matrix", {}).get("pixelGroups", {}))
            for group in groups:
                self.group_members(group)  # constraints are refused here
            return groups
        if repeat == "eachPixelABC":
            return sorted(self.pixel_keys(), key=_natural)
        match = re.fullmatch(r"eachPixel([XYZ]{3})", str(repeat))
        if match is None or len(set(match.group(1))) != 3:
            raise _SkipMode(f"unknown repeatFor {repeat!r}")
        axes = ["XYZ".index(letter) for letter in match.group(1)]
        pixels = self._pixels()
        return [key for key, at in sorted(pixels, key=lambda p: [p[1][a] for a in reversed(axes)])]

    def group_members(self, group: str) -> list[str] | None:
        """The pixels of a pixel group (``None``: not a group)."""
        groups = self.data.get("matrix", {}).get("pixelGroups", {})
        if group not in groups:
            return None
        members = groups[group]
        if members == "all":
            return self.pixel_keys()
        if isinstance(members, list):
            return [str(member) for member in members]
        raise _SkipMode(f"pixel group {group!r} is given by constraints, which are not supported")

    def position(self, pixel: str) -> tuple[int, int, int] | None:
        return next((at for key, at in self._pixels() if key == pixel), None)

    def _pixels(self) -> list[tuple[str, tuple[int, int, int]]]:
        matrix = self.data.get("matrix")
        if not matrix:
            return []
        found: list[tuple[str, tuple[int, int, int]]] = []
        if "pixelKeys" in matrix:
            for z, plane in enumerate(matrix["pixelKeys"]):
                for y, row in enumerate(plane):
                    for x, key in enumerate(row):
                        if key is not None:
                            found.append((str(key), (x, y, z)))
        else:
            counts = [int(n) for n in matrix.get("pixelCount", [1, 1, 1])]
            spread = [axis for axis, n in enumerate(counts) if n > 1]
            for z, y, x in product(range(counts[2]), range(counts[1]), range(counts[0])):
                at = (x, y, z)
                if len(spread) <= 1:
                    key = str(sum(at) + 1)
                else:
                    key = "(" + ", ".join(str(at[axis] + 1) for axis in spread) + ")"
                found.append((key, at))
        return found

    # -- wheels and physical

    def _read_wheels(self) -> None:
        counts: dict[str, int] = {}
        for name, wheel in self.data.get("wheels", {}).items():
            types = {slot.get("type") for slot in wheel.get("slots", [])}
            kind: Literal["color", "gobo", "prism", "animation"]
            if "Prism" in types:
                kind = "prism"
            elif "Color" in types:
                kind = "color"
            elif types & {"AnimationGoboStart", "AnimationGoboEnd"}:
                kind = "animation"
            else:
                kind = "gobo"
            counts[kind] = n = counts.get(kind, 0) + 1
            attribute, rotation = {
                "color": ("colorWheel" if n == 1 else None, None),
                "gobo": (f"gobo{n}", f"gobo{n}Rotation") if n <= 2 else (None, None),
                "prism": ("prism", "prismRotation") if n == 1 else (None, None),
                "animation": (None, None),
            }[kind]
            ids: set[str] = set()
            slots = [_wheel_slot(slot, k, kind, ids) for k, slot in enumerate(wheel["slots"])]
            self.wheels[name] = _Wheel(name, f"{kind}{n}", kind, slots, attribute, rotation)

    def prism_wheel(self, name: str) -> _Wheel:
        """The prism wheel a ``Prism`` capability on channel ``name`` uses:
        the wheel of that name, else the first prism wheel, else a new one
        with ``off`` and ``prism`` slots."""
        wheel = self.wheels.get(name)
        if wheel is not None and wheel.kind == "prism":
            return wheel
        wheel = next((w for w in self.wheels.values() if w.kind == "prism"), None)
        if wheel is None:
            slots = [WheelSlot(id="off", name="Open"), WheelSlot(id="prism", name="Prism")]
            wheel = _Wheel("Prism", "prism1", "prism", slots, "prism", "prismRotation")
            self.wheels["\0prism"] = wheel
        return wheel

    def macro(self, channel: _Channel) -> _Macro:
        """The options of a colour macro or effect channel (module docstring),
        worked out once per OFL channel, so a template's pixels share its wheel."""
        found = self.macros.get(id(channel.data))
        if found is not None:
            return found
        taken: set[str] = set()
        seen: dict[str, tuple[Literal["slot", "function"], str]] = {}  # capability → option
        slots: list[WheelSlot] = []
        options: list[tuple[Literal["slot", "function"], str]] = []
        for cap in channel.caps:
            if cap.type == "NoFunction":
                options.append(("function", "off"))
                continue
            if cap.type == "Maintenance":  # never an option (MAINTENANCE_FUNCTIONS)
                options.append(("function", "maintenance"))
                continue
            rest = {k: v for k, v in cap.data.items() if k != "dmxRange"}
            same = json.dumps(rest, sort_keys=True)
            if same not in seen:
                kind: Literal["slot", "function"] = (
                    "slot" if cap.type == "ColorPreset" else "function"
                )
                ident = _unique(_camel(_macro_name(cap)) or "function", taken)
                taken.add(ident)
                seen[same] = (kind, ident)
                if kind == "slot":
                    slot = WheelSlot(id=ident, name=str(cap.data.get("comment") or ident))
                    if cap.data.get("colors"):
                        slot["color"] = _mean_colour(cap.data["colors"])
                    slots.append(slot)
            options.append(seen[same])
        wheel = None
        if slots:
            wheel = f"macro{sum(1 for w in self.wheels.values() if w.id.startswith('macro')) + 1}"
            self.wheels[f"\0{wheel}"] = _Wheel(channel.name, wheel, "color", slots, None, None)
        found = self.macros[id(channel.data)] = _Macro(wheel, options)
        return found

    def _physical(self) -> FixturePhysical:
        physical = dict(self.physical)
        ofl = self.data.get("physical", {})
        if isinstance(ofl.get("weight"), int | float):
            physical["weightKg"] = float(ofl["weight"])
        if isinstance(ofl.get("power"), int | float):
            physical["powerW"] = float(ofl["power"])
        lens = ofl.get("lens", {}).get("degreesMinMax")
        if lens and lens[0] < lens[1]:
            physical["zoomRange"] = (float(lens[0]), float(lens[1]))
        return cast(FixturePhysical, physical)

    def lens(self) -> tuple[float, float] | None:
        lens = self.data.get("physical", {}).get("lens", {}).get("degreesMinMax")
        return None if not lens else (float(lens[0]), float(lens[1]))

    def widen(self, key: Literal["panRange", "tiltRange", "maxStrobeHz"], value: float) -> None:
        if value > self.physical.get(key, 0.0):
            self.physical[key] = value


def _wheel_slot(slot: Mapping[str, Any], k: int, kind: str, ids: set[str]) -> WheelSlot:
    """A busk slot for OFL wheel slot ``k`` (0-based)."""
    kind_of = str(slot.get("type", "Open"))
    name = str(slot.get("name", ""))
    if kind_of == "Open":
        ident, name = ("off" if kind == "prism" else "open"), name or "Open"
    elif kind_of == "Closed":
        ident, name = "closed", name or "Closed"
    elif kind_of == "Prism":
        facets = slot.get("facets")
        ident = f"prism{facets}" if facets else "prism"
        name = name or (f"{facets}-facet prism" if facets else "Prism")
    else:
        ident = _camel(name) or f"{_camel(kind_of)}{k + 1}"
        name = name or f"{kind_of} {k + 1}"
    result = WheelSlot(id=_unique(ident, ids), name=name)
    ids.add(result["id"])
    if kind_of == "Prism" and slot.get("facets"):
        result["facets"] = int(slot["facets"])
    if kind_of == "Color" and slot.get("colors"):
        result["color"] = _mean_colour(slot["colors"])
    return result


def _mean_colour(colours: list[str]) -> ColorValue:
    """The mean of sRGB ``#rrggbb`` colours, in linear RGB."""
    rgb = [_linear_rgb(colour) for colour in colours]
    return ColorValue(
        r=sum(c[0] for c in rgb) / len(rgb),
        g=sum(c[1] for c in rgb) / len(rgb),
        b=sum(c[2] for c in rgb) / len(rgb),
    )


def _macro_name(cap: _Cap) -> str:
    """What a colour macro channel's option is named after."""
    for key in ("effectName", "comment", "effectPreset", "shutterEffect"):
        if cap.data.get(key):
            return str(cap.data[key])
    return "preset" if cap.type == "ColorPreset" else cap.type


# ------------------------------------------------------------------ one mode


@dataclass
class _Placed:
    """A channel in a mode: its offsets per byte (0 coarse, k fine)."""

    channel: _Channel
    offsets: dict[int, int]
    element: int = 0
    attribute: str = "control"
    component: str | None = None


class _ModeBuilder:
    """Builds one busk mode from one OFL mode."""

    def __init__(self, fixture: _Fixture, mode: Mapping[str, Any], ident: str) -> None:
        self.fixture = fixture
        self.mode = mode
        self.ident = ident
        self.elements: list[ElementDefinition] = []
        self.pixels: dict[str, int] = {}  # pixel or group key → element

    def build(self) -> FixtureMode:
        entries = list(self._entries())
        if not entries:
            raise _SkipMode("it has no channels")
        if len(entries) > 512:
            raise _SkipMode(f"its {len(entries)} channels do not fit a universe")
        placed: dict[str, _Placed] = {}
        for offset, name in enumerate(entries):
            if name is None:
                continue
            channel, k = self._resolve(name)
            if channel.pixel is not None:
                self._element_of(channel.pixel)
            placed.setdefault(channel.key, _Placed(channel, {})).offsets[k] = offset
        channels = sorted(placed.values(), key=lambda p: min(p.offsets.values()))
        self._assign(channels)
        definitions = [self._definition(p) for p in channels]
        definitions.sort(key=lambda d: d["offset"])
        intensity = any(d["attribute"] == "intensity" for d in definitions)
        return FixtureMode(
            id=ModeId(self.ident),
            name=str(self.mode.get("name", self.ident)),
            footprint=len(entries),
            elements=self.elements or [ElementDefinition(index=0, name="Main")],
            intensityStrategy="dimmerChannel" if intensity else "virtual",
            dimmerCurve="linear",
            channels=definitions,
        )

    def _entries(self) -> Iterator[str | None]:
        """The mode's channel names per offset (``None``: unused)."""
        for entry in self.mode.get("channels", []):
            if entry is None or isinstance(entry, str):
                yield entry
            elif isinstance(entry, Mapping) and entry.get("insert") == "matrixChannels":
                pixels = self.fixture.pixel_order(entry.get("repeatFor"))
                templates: list[str | None] = entry.get("templateChannels", [])
                if entry.get("channelOrder") == "perChannel":
                    order = [(t, p) for t in templates for p in pixels]
                else:
                    order = [(t, p) for p in pixels for t in templates]
                for template, pixel in order:
                    yield None if template is None else template.replace("$pixelKey", pixel)
            else:
                raise _SkipMode(f"unsupported channel entry {entry!r}")

    def _resolve(self, name: str) -> tuple[_Channel, int]:
        found = self.fixture.channel(name)
        if found is None:
            switched = self.fixture.switched(name)
            if switched is None:
                raise _SkipMode(f"channel {name!r} is not defined")
            target, trigger = switched
            self.fixture.note(
                f"{name}: a switching channel; kept as {target}, the channel the default "
                f"of {trigger} selects"
            )
            found = self.fixture.channel(target)
            if found is None:
                raise _SkipMode(f"switched channel {target!r} is not defined")
        return found

    def _element_of(self, pixel: str) -> int:
        if pixel not in self.pixels:
            index = len(self.elements)
            element = ElementDefinition(index=index, name=f"Pixel {pixel}")
            at = self.fixture.position(pixel)
            if at is not None:
                element["layout"] = {"x": float(at[0]), "y": float(at[1])}
            self.elements.append(element)
            self.pixels[pixel] = index
        return self.pixels[pixel]

    # -- attributes

    def _assign(self, channels: list[_Placed]) -> None:
        """Choose each channel's element, attribute and colour component."""
        colours = {p.channel.key: _colour(p.channel) for p in channels}
        named = {c for c in colours.values() if c is not None}
        subtractive = (
            not named & {"Red", "Green", "Blue"} and {"Cyan", "Magenta", "Yellow"} <= named
        )
        white_only = not self.pixels and bool(named) and named <= WHITES
        if white_only:  # decision 20: each white or UV die is an intensity element
            for p in channels:
                if colours[p.channel.key] is not None:
                    p.element = len(self.elements)
                    self.elements.append(ElementDefinition(index=p.element, name=p.channel.name))
        for p in channels:
            if p.channel.pixel is not None:
                p.element = self.pixels[p.channel.pixel]
            colour = colours[p.channel.key]
            if colour is not None:
                if white_only:
                    p.attribute = "intensity"
                elif subtractive and colour in FLAGS:
                    p.attribute, p.component = "color", FLAGS[colour]
                else:
                    p.attribute, p.component = "color", self._emitter(colour)
            else:
                p.attribute = self._attribute(p.channel)
        if white_only:
            for p in channels:
                if p.attribute == "intensity" and colours[p.channel.key] is None:
                    p.attribute = "master"  # held at full: the dies are the intensity
        attributes = {p.attribute for p in channels}
        if "effect" not in attributes and attributes & {"colorMacro", "colorEffect"}:
            for p in channels:
                if p.attribute == "effectRate":  # OFL says not whose speed it is
                    p.attribute = "colorMacroRate"
                    self.fixture.note(
                        f"{p.channel.name}: an effect speed in a mode with colour programs "
                        "and no other effect channel; taken as their colorMacroRate"
                    )
        self._dedupe(channels)

    def _emitter(self, colour: str) -> str:
        if colour in ADDITIVE:
            return ADDITIVE[colour]
        ident, value = CUSTOM[colour]
        if ident not in self.fixture.emitters:
            self.fixture.emitters[ident] = Emitter(id=ident, color=value)
            self.fixture.note(f"{colour}: a custom emitter with an estimated colour")
        return ident

    def _attribute(self, channel: _Channel) -> str:
        """The attribute of the channel's first capability busk can drive;
        failing that, of its first program capability (:data:`PROGRAMS`)."""
        for cap in channel.caps:
            attribute = self._candidate(channel, cap)
            if attribute is not None:
                return attribute
        for cap in channel.caps:
            if cap.type in PROGRAMS:
                return PROGRAMS[cap.type]
        return "control"

    def _candidate(self, channel: _Channel, cap: _Cap) -> str | None:
        kind, data = cap.type, cap.data
        if kind in ("Intensity", "FogOutput"):
            return "intensity"
        if kind == "ShutterStrobe":
            return "shutter"
        if kind == "StrobeSpeed":
            return "strobeRate"
        if kind in ("Pan", "Tilt"):
            return kind.lower() if _angles(data) is not None else None
        if kind == "PanTiltSpeed":
            return "positionSpeed"
        if kind == "WheelSlot":
            slot = data.get("slotNumber")
            wheel = self.fixture.wheels.get(str(data.get("wheel", channel.key)))
            if wheel is None or not isinstance(slot, int):
                return None
            return wheel.attribute
        if kind == "WheelSlotRotation":
            wheel = self.fixture.wheels.get(str(data.get("wheel", channel.key)))
            if wheel is None or not _has_speed(data):
                return None
            return wheel.rotation if wheel.kind in ("gobo", "prism") else None
        if kind == "Prism":
            return "prism"
        if kind == "ColorPreset":
            return "colorMacro"
        if kind == "Effect" and data.get("effectPreset") in ("ColorJump", "ColorFade"):
            # Only when nothing else on the channel is: a strobe channel with
            # a sound-to-colour range stays a shutter.
            others = (self._candidate(channel, c) for c in channel.caps if c.type != "Effect")
            return None if any(other is not None for other in others) else "colorEffect"
        if kind == "PrismRotation":
            return "prismRotation" if _has_speed(data) else None
        return {
            "Zoom": "zoom",
            "Focus": "focus",
            "Iris": "iris",
            "Frost": "frost",
            "ColorTemperature": "cto",
        }.get(kind)

    def _dedupe(self, channels: list[_Placed]) -> None:
        """Keep one channel per element and attribute (and component); an
        element's colour channels only when they make a mixing system."""
        seen: set[tuple[int, str, str | None]] = set()
        for p in channels:
            if p.attribute in ("control", "master", "held"):
                continue
            slot = (p.element, p.attribute, p.component)
            if slot in seen and p.attribute == "effect":
                if (p.element, "effect2", None) not in seen:
                    p.attribute, slot = "effect2", (p.element, "effect2", None)
                else:
                    self.fixture.note(
                        f"{p.channel.name}: an effect channel after effect and effect2; "
                        "held as control"
                    )
                    p.attribute = "held"  # reported above
            elif slot in seen:
                self.fixture.note(
                    f"{p.channel.name}: a second {p.attribute} channel; held as control"
                )
                p.attribute, p.component = "held", None  # reported above
            seen.add(slot)
        by_element: dict[int, set[str]] = {}
        for p in channels:
            if p.attribute == "color" and p.component is not None:
                by_element.setdefault(p.element, set()).add(p.component)
        for p in channels:
            components = by_element.get(p.element, set())
            if p.attribute == "color" and not (
                {"red", "green", "blue"} <= components
                or {"cyanFlag", "magentaFlag", "yellowFlag"} <= components
            ):
                self.fixture.note(
                    f"{p.channel.name}: busk colour mixes red, green and blue (or cyan, "
                    "magenta and yellow); held as control"
                )
                p.attribute, p.component = "held", None  # reported above

    # -- channel definitions

    def _definition(self, p: _Placed) -> ChannelDefinition:
        channel = p.channel
        coarse = p.offsets.get(0)
        fines: list[int] = []
        for k in range(1, len(channel.fines) + 1):
            if k not in p.offsets:
                break
            fines.append(p.offsets[k])
        if coarse is None:  # a fine byte without its coarse one: never driven
            self.fixture.note(f"{channel.name}: its coarse channel is not in the mode; held at 0")
            coarse, fines = min(p.offsets.values()), []
            p.attribute, p.component = "fine", None
        nbytes = 1 + len(fines)
        definition: dict[str, Any] = {
            "offset": coarse,
            "element": p.element,
            "attribute": p.attribute,
            "bytes": nbytes,
        }
        if fines and fines != list(range(coarse + 1, coarse + 1 + len(fines))):
            definition["fineOffsets"] = fines
        default = _raw(channel.data.get("defaultValue", 0), channel.resolution, nbytes)
        capabilities: list[Capability]
        if p.attribute == "fine":
            definition["attribute"], default = "control", 0
            capabilities = [_function(0, 255, "fine")]
        elif p.attribute == "master":
            definition["attribute"], default = "control", _top(nbytes)
            capabilities = self._controls(channel, nbytes)
            self.fixture.note(
                f"{channel.name}: the master intensity of white-only dies; held at full"
            )
        elif p.attribute in ("control", "held"):  # "held": already reported
            definition["attribute"] = "control"
            capabilities = self._controls(channel, nbytes)
            if p.attribute == "control":
                types = ", ".join(dict.fromkeys(cap.type for cap in channel.caps))
                self.fixture.note(
                    f"{channel.name}: no busk attribute ({types}); held at DMX {default}"
                )
        else:
            try:
                capabilities = self._capabilities(p, nbytes)
            except _Unmapped as exc:
                self.fixture.note(f"{channel.name}: {exc}; held at DMX {default}")
                definition["attribute"] = "control"
                capabilities = self._controls(channel, nbytes)
        default_option = _default_option(definition["attribute"])
        if default_option is not None and default_option not in {
            option
            for option, _ in option_capabilities(
                cast(Any, {**definition, "capabilities": capabilities})
            )
        }:
            self.fixture.note(
                f"{channel.name}: offers no {default_option!r}, which busk outputs when nothing "
                f"controls {definition['attribute']}; held at DMX {default}"
            )
            definition["attribute"] = "control"
            capabilities = self._controls(channel, nbytes)
        elif definition["attribute"] in MACRO_ATTRIBUTES and _maintenance_default(
            capabilities, default
        ):
            self.fixture.note(
                f"{channel.name}: its default selects a maintenance range, which busk never "
                f"outputs; held at DMX {default}"
            )
            definition["attribute"] = "control"
            capabilities = self._controls(channel, nbytes)
        if p.component is not None and definition["attribute"] == "color":
            definition["component"] = p.component
        definition["defaultDmx"] = default
        if "highlightValue" in channel.data:
            definition["highlightDmx"] = _raw(
                channel.data["highlightValue"], channel.resolution, nbytes
            )
        definition["capabilities"] = capabilities
        return cast(ChannelDefinition, definition)

    def _capabilities(self, p: _Placed, nbytes: int) -> list[Capability]:
        """A driven channel's capabilities (raises :class:`_Unmapped`)."""
        channel, attribute = p.channel, p.attribute
        if attribute in MACRO_ATTRIBUTES:
            return self._macro(channel, attribute, nbytes)
        coloured = _colour(channel) is not None  # a colour component or a white die
        out: list[Capability] = []
        for cap, low, high in self._scaled(channel, nbytes):
            mapped = self._candidate(channel, cap) or PROGRAMS.get(cap.type)
            if attribute == "colorMacroRate" and mapped == "effectRate":  # _assign's speed
                mapped = attribute
            if (coloured and cap.type == "ColorIntensity") or mapped == attribute:
                out.extend(self._mapped(channel, cap, attribute, low, high))
            elif cap.type == "NoFunction" or (
                cap.type in ("WheelSlotRotation", "PrismRotation") and not _has_speed(cap.data)
            ):
                out.extend(self._dead_band(channel, attribute, low, high, cap))
            else:
                out.append(_function(low, high, _fn(cap)))
        if ATTRIBUTES[cast(Any, attribute)].kind == "scalar" and not any(
            capability["kind"] == "range" for capability in out
        ):
            raise _Unmapped(f"no range drives {attribute}")
        return out

    def _controls(self, channel: _Channel, nbytes: int) -> list[Capability]:
        return [_function(low, high, _fn(cap)) for cap, low, high in self._scaled(channel, nbytes)]

    def _macro(self, channel: _Channel, attribute: str, nbytes: int) -> list[Capability]:
        """A colour macro, colour effect or fixture effect channel: every
        capability an option."""
        macro = self.fixture.macro(channel)
        program = attribute in ("effect", "effect2")
        out: list[Capability] = []
        for cap, low, high in self._scaled(channel, nbytes):
            kind, option = macro.options[channel.caps.index(cap)]
            if kind == "slot":
                wheel = cast(str, macro.wheel)
                out.append(SlotCapability(kind="slot", dmx=(low, high), wheel=wheel, slot=option))
                continue
            capability = _function(low, high, option)
            if cap.type == "ShutterStrobe" and _has_speed(cap.data):
                rate = self._strobe(channel, cap)
                capability["param"] = {"attribute": "strobeRate", "value": rate}
            elif program:
                param = self._program_parameter(channel, cap, option)
                if param is not None:
                    capability["param"] = param
            elif cap.type == "Effect" and _has_speed(cap.data):
                try:
                    speed = _pair(cap.data, "speed", _macro_speed)
                except _Unmapped as exc:
                    self.fixture.note(f"{channel.name}: {option} has no colorMacroRate ({exc})")
                else:
                    capability["param"] = {"attribute": "colorMacroRate", "value": speed}
            out.append(capability)
        return out

    def _program_parameter(
        self, channel: _Channel, cap: _Cap, option: str
    ) -> CapabilityParam | None:
        """A program option's parameter: the first of its speed, duration,
        parameter and sound sensitivity (:data:`PROGRAM_PARAMETERS`)."""
        if cap.type not in PROGRAMS:
            return None
        found = [
            (prop, attribute)
            for prop, attribute in PROGRAM_PARAMETERS
            if prop in cap.data or f"{prop}Start" in cap.data
        ]
        if not found:
            return None
        (prop, attribute), *others = found
        if others:
            self.fixture.note(
                f"{channel.name}: {option} takes its {prop} as {attribute}; its "
                f"{', '.join(other for other, _ in others)} is not imported"
            )
        try:
            value = _pair(cap.data, prop, lambda text: self._program_value(channel, prop, text))
        except _Unmapped as exc:
            self.fixture.note(f"{channel.name}: {option} has no {attribute} ({exc})")
            return None
        return CapabilityParam(attribute=attribute, value=value)

    def _program_value(self, channel: _Channel, prop: str, text: str) -> float:
        """A program property on 0…1: a keyword (``slow`` 0, ``fast`` 1 …; a
        reverse speed counts as forward), a percentage, else a physical value
        rescaled over the channel's span of that property, in which ``stop``
        and ``instant`` are 0 Hz and 0 s (reported)."""
        word = text.split()[0] if text.strip() else text
        if word in _WORDS[prop]:
            return float(_WORDS[prop][word])
        number, unit = _entity(word)
        if number is None or (unit not in _UNITS and unit != "%"):
            raise _Unmapped(f"{prop} {text!r}")
        if unit == "%":
            return number / 100
        dimension, scale = _UNITS[unit]
        values: list[float] = []
        for cap in channel.caps:
            for key in (prop, f"{prop}Start", f"{prop}End"):
                first = str(cap.data.get(key, "")).split()[:1]
                if not first:
                    continue
                if {"stop": "Hz", "instant": "s"}.get(first[0]) == dimension:  # 0 Hz, 0 s
                    values.append(0.0)
                    continue
                found, other = _entity(first[0])
                if found is not None and other in _UNITS and _UNITS[other][0] == dimension:
                    values.append(found * _UNITS[other][1])
        low, high = min(values), max(values)
        self.fixture.note(
            f"{channel.name}: {prop} {_fmt(low)}…{_fmt(high)}{dimension and ' ' + dimension} "
            "taken as 0…1"
        )
        return (number * scale - low) / (high - low) if high > low else 0.0

    def _scaled(self, channel: _Channel, nbytes: int) -> Iterator[tuple[_Cap, int, int]]:
        """The capabilities with their ranges at ``nbytes``; ranges that a
        coarser channel makes overlap are trimmed, empty ones dropped."""
        previous = -1
        for cap in channel.caps:
            low = max(_scale(cap.low, channel.resolution, nbytes, high=False), previous + 1)
            high = _scale(cap.high, channel.resolution, nbytes, high=True)
            if low > high:
                continue
            previous = high
            yield cap, low, high

    def _dead_band(
        self, channel: _Channel, attribute: str, low: int, high: int, cap: _Cap
    ) -> list[Capability]:
        """A ``NoFunction`` or index range on an attribute (module docstring)."""
        name = "noFunction" if cap.type == "NoFunction" else "index"
        if attribute == "shutter":
            return [_function(low, high, "open")]
        if attribute == "prism":
            wheel = self.fixture.prism_wheel(channel.key)
            off = next((s["id"] for s in wheel.slots if s["id"] == "off"), None)
            if off is not None:
                return [SlotCapability(kind="slot", dmx=(low, high), wheel=wheel.id, slot=off)]
        rest = _REST.get(attribute)
        if rest is None:
            return [_function(low, high, name)]
        band: list[Capability] = [RangeCapability(kind="range", dmx=(low, low), value=(rest, rest))]
        if high > low:
            band.append(_function(low + 1, high, name))
        return band

    def _mapped(
        self, channel: _Channel, cap: _Cap, attribute: str, low: int, high: int
    ) -> list[Capability]:
        data = cap.data
        if attribute == "shutter":
            return [self._shutter(channel, cap, low, high)]
        if attribute in ("colorWheel", "gobo1", "gobo2") or (
            attribute == "prism" and cap.type == "WheelSlot"
        ):
            wheel = self.fixture.wheels[str(data.get("wheel", channel.key))]
            slot = wheel.slots[(int(data["slotNumber"]) - 1) % len(wheel.slots)]
            return [SlotCapability(kind="slot", dmx=(low, high), wheel=wheel.id, slot=slot["id"])]
        if attribute == "prism":
            wheel = self.fixture.prism_wheel(str(data.get("wheel", channel.key)))
            prism = next(s for s in wheel.slots if s["id"].startswith("prism"))
            return [SlotCapability(kind="slot", dmx=(low, high), wheel=wheel.id, slot=prism["id"])]
        if attribute in ("effectRate", "colorMacroRate") and _reverse(data):
            self.fixture.note(f"{channel.name}: reverse speeds are never output")
            return [_function(low, high, "reverse")]
        values = self._values(channel, cap, attribute)
        return [RangeCapability(kind="range", dmx=(low, high), value=values)]

    def _shutter(self, channel: _Channel, cap: _Cap, low: int, high: int) -> Capability:
        effect = str(cap.data.get("shutterEffect", ""))
        fn = {"Open": "open", "Closed": "closed", "Strobe": "strobe", "Pulse": "pulse"}.get(
            effect, _camel(effect) or "shutter"
        )
        if fn == "strobe" and cap.data.get("randomTiming"):
            fn = "random"
        capability = FunctionCapability(kind="function", dmx=(low, high), fn=fn)
        if fn in ("strobe", "pulse", "random") and _has_speed(cap.data):
            rate = self._strobe(channel, cap)
            capability["param"] = {"attribute": "strobeRate", "value": rate}
        return capability

    def _strobe(self, channel: _Channel, cap: _Cap) -> tuple[float, float]:
        def hz(text: str) -> float:
            number, unit = _entity(text)
            if unit == "Hz" and number is not None:
                return number
            if unit == "bpm" and number is not None:
                return number / 60
            if text == "stop":
                return 0.0
            estimate = _keyword_speed(text, STROBE_ESTIMATE)
            self.fixture.note(
                f"{channel.name}: strobe speeds given as slow…fast taken as "
                f"{_fmt(STROBE_ESTIMATE[0])}–{_fmt(STROBE_ESTIMATE[1])} Hz (an estimate)"
            )
            return estimate

        rate = _pair(cap.data, "speed", hz)
        self.fixture.widen("maxStrobeHz", max(rate))
        return rate

    def _values(self, channel: _Channel, cap: _Cap, attribute: str) -> tuple[float, float]:
        """A range capability's logical values (raises :class:`_Unmapped`)."""
        data = cap.data
        if attribute == "intensity":
            if cap.type == "FogOutput":
                return _pair(
                    data, "fogOutput", _fraction({"off": 0, "weak": 0, "strong": 1}), (0, 1)
                )
            return _pair(data, "brightness", _fraction({"off": 0, "dark": 0, "bright": 1}), (0, 1))
        if attribute == "color":
            return _pair(data, "brightness", _fraction({"off": 0, "dark": 0, "bright": 1}), (0, 1))
        if attribute == "strobeRate":
            return self._strobe(channel, cap)
        if attribute in ("pan", "tilt"):
            angles = [
                a for c in channel.caps if c.type == cap.type for a in (_angles(c.data) or ())
            ]
            centre = (min(angles) + max(angles)) / 2
            self.fixture.widen(
                "panRange" if attribute == "pan" else "tiltRange", max(angles) - min(angles)
            )
            start, end = cast(tuple[float, float], _angles(data))
            return start - centre, end - centre
        if attribute == "positionSpeed":
            return _pair(data, "speed", _position_speed)
        if attribute.endswith("Rotation"):
            return self._rotation(channel, cap)
        if attribute == "zoom":
            return _pair(data, "angle", self._zoom_angle)
        if attribute == "focus":
            return _pair(data, "distance", _fraction({"near": 0, "far": 1}), (0, 1))
        if attribute == "iris":
            return _pair(data, "openPercent", _fraction({"closed": 0, "open": 1}), (1, 0))
        if attribute == "frost":
            return _pair(data, "frostIntensity", _fraction({"off": 0, "low": 0, "high": 1}), (0, 1))
        if attribute == "cto":
            return _pair(data, "colorTemperature", self._cto, (0, 1))
        prop = _PROPERTIES.get(attribute)
        if prop is not None:
            return _pair(data, prop, lambda text: self._program_value(channel, prop, text), (0, 1))
        raise _Unmapped(f"no mapping for {cap.type}")

    def _rotation(self, channel: _Channel, cap: _Cap) -> tuple[float, float]:
        def speed(text: str) -> float:
            number, unit = _entity(text)
            if number is not None and unit == "rpm":
                return number * 6
            if number is not None and unit == "Hz":
                return number * 360
            if text == "stop":
                return 0.0
            words = text.split()
            sign = -1.0 if words[-1] == "CCW" else 1.0
            if number is not None and unit == "%":
                estimate = sign * abs(number) / 100 * ROTATION_ESTIMATE[1]
            else:
                estimate = sign * _keyword_speed(words[0], ROTATION_ESTIMATE)
            self.fixture.note(
                f"{channel.name}: rotation speeds given as slow…fast taken as "
                f"{_fmt(ROTATION_ESTIMATE[0])}–{_fmt(ROTATION_ESTIMATE[1])} °/s, "
                "CW positive (an estimate)"
            )
            return estimate

        return _pair(cap.data, "speed", speed)

    def _zoom_angle(self, text: str) -> float:
        number, unit = _entity(text)
        if number is not None and unit == "deg":
            return number
        lens = self.fixture.lens()
        if lens is None:
            raise _Unmapped(f"zoom {text!r} without the lens's degrees")
        if text in ("narrow", "wide"):
            return lens[0] if text == "narrow" else lens[1]
        if number is not None and unit == "%":
            return lens[0] + number / 100 * (lens[1] - lens[0])
        raise _Unmapped(f"zoom {text!r}")

    def _cto(self, text: str) -> float:
        if text in ("warm", "CTO"):
            return 1.0
        if text in ("default", "cold", "CTB"):
            return 0.0
        number, unit = _entity(text)
        if number is not None and unit == "K":
            return min(1.0, max(0.0, (6500 - number) / (6500 - 3200)))
        raise _Unmapped(f"colour temperature {text!r}")


# ------------------------------------------------------------------ values


def _default_option(attribute: str) -> str | None:
    """The option a discrete attribute outputs when nothing controls it
    (``open``, ``off``), which its channel must offer; ``None`` for others,
    and for the colour macros, whose default is the channel's own."""
    definition = ATTRIBUTES.get(cast(Any, attribute))
    if definition is None or definition.kind != "discrete" or attribute == "control":
        return None
    if definition.default == "channelDefault":
        return None
    return cast(str, cast(Mapping[str, Any], definition.default)["slot"])


def _maintenance_default(capabilities: list[Capability], default: int) -> bool:
    """Whether a program channel's ``defaultDmx`` lies in a maintenance range.
    busk could then only output another of its options when nothing controls
    it (perhaps a program the fixture does not run today), so the channel is
    held instead."""
    for capability in capabilities:
        low, high = capability["dmx"]
        if low <= default <= high:
            return capability["kind"] == "function" and capability["fn"] in MAINTENANCE_FUNCTIONS
    return False


def _colour(channel: _Channel) -> str | None:
    """The OFL colour of a ``ColorIntensity`` channel (its first capability)."""
    cap = channel.caps[0]
    if cap.type != "ColorIntensity":
        return None
    colour = str(cap.data.get("color", ""))
    return colour if colour in ADDITIVE or colour in CUSTOM else None


def _entity(text: str) -> tuple[float | None, str | None]:
    """An OFL entity's number and unit (``"12deg"`` → ``(12.0, "deg")``)."""
    match = _ENTITY.match(text.strip())
    if match is None:
        return None, None
    return float(match.group(1)), match.group(2)


def _pair(
    data: Mapping[str, Any],
    prop: str,
    parse: Any,
    default: tuple[float, float] | None = None,
) -> tuple[float, float]:
    """``prop`` or ``propStart``/``propEnd`` parsed; ``default`` if absent."""
    if prop in data:
        value = float(parse(str(data[prop])))
        return value, value
    if f"{prop}Start" in data:
        return float(parse(str(data[f"{prop}Start"]))), float(parse(str(data[f"{prop}End"])))
    if default is None:
        raise _Unmapped(f"no {prop}")
    return float(default[0]), float(default[1])


def _fraction(words: Mapping[str, float]) -> Any:
    """A parser for keyword-or-percentage entities on ``0..1``."""

    def parse(text: str) -> float:
        if text in words:
            return float(words[text])
        number, unit = _entity(text)
        if number is not None and unit == "%":
            return number / 100
        raise _Unmapped(f"{text!r} has no 0–1 meaning")

    return parse


def _position_speed(text: str) -> float:
    """``positionSpeed``: fast 0, slow 1, a percentage of full speed inverted."""
    if text.startswith("fast"):
        return 0.0
    if text.startswith("slow"):
        return 1.0
    number, unit = _entity(text)
    if number is not None and unit == "%":
        return 1 - number / 100
    raise _Unmapped(f"pan/tilt speed {text!r}")


def _macro_speed(text: str) -> float:
    """A program's speed as ``colorMacroRate``: slow or stop 0, fast 1, a
    percentage of full speed; reverse runs at the same speed."""
    word = text.split()[0] if text.strip() else text
    if word in ("slow", "stop"):
        return 0.0
    if word == "fast":
        return 1.0
    number, unit = _entity(word)
    if number is not None and unit == "%":
        return number / 100
    raise _Unmapped(f"speed {text!r}")


def _keyword_speed(word: str, estimate: tuple[float, float]) -> float:
    if word == "slow":
        return estimate[0]
    if word == "fast":
        return estimate[1]
    number, unit = _entity(word)
    if number is not None and unit == "%":
        return estimate[0] + number / 100 * (estimate[1] - estimate[0])
    raise _Unmapped(f"speed {word!r}")


def _has_speed(data: Mapping[str, Any]) -> bool:
    return "speed" in data or "speedStart" in data


_PROPERTIES: Final[Mapping[str, str]] = {
    "colorMacroRate": "speed",
    "effectRate": "speed",
    "effectFade": "duration",
    "effectAdjust": "parameter",
    "soundSensitivity": "soundSensitivity",
}
"""The program property a scalar channel of these attributes maps."""


def _reverse(data: Mapping[str, Any]) -> bool:
    """Whether a speed runs in reverse (``slow reverse``, a negative percentage)."""
    texts = [str(data[key]) for key in ("speed", "speedStart", "speedEnd") if key in data]
    return any("reverse" in text or text.strip().startswith("-") for text in texts)


def _angles(data: Mapping[str, Any]) -> tuple[float, float] | None:
    """A ``Pan``/``Tilt`` capability's angles in degrees (``None``: not in degrees)."""
    texts = (
        (data["angle"], data["angle"]) if "angle" in data
        else (data.get("angleStart"), data.get("angleEnd"))
    )  # fmt: skip
    angles = [_entity(str(text)) for text in texts]
    if any(number is None or unit != "deg" for number, unit in angles):
        return None
    return cast(float, angles[0][0]), cast(float, angles[1][0])


def _raw(value: Any, resolution: int, nbytes: int) -> int:
    """A ``defaultValue``-like value as raw DMX at ``nbytes``."""
    if isinstance(value, str):
        number, unit = _entity(value)
        if number is None or unit != "%":
            return 0
        return round(number / 100 * (_top(nbytes)))
    return _scale(int(value), resolution, nbytes, high=False)


def _top(nbytes: int) -> int:
    """The largest raw value of a channel of ``nbytes`` bytes."""
    return (1 << (8 * nbytes)) - 1


def _scale(raw: int, resolution: int, nbytes: int, *, high: bool) -> int:
    """``raw`` (at ``resolution`` bytes) at ``nbytes``: finer fills the new
    bytes with ``0`` (``0xff…`` for a range's ``high`` end), coarser drops them."""
    if nbytes >= resolution:
        shift = 8 * (nbytes - resolution)
        return (raw << shift) | ((1 << shift) - 1 if high else 0)
    return raw >> (8 * (resolution - nbytes))


def _function(low: int, high: int, fn: str) -> FunctionCapability:
    return FunctionCapability(kind="function", dmx=(low, high), fn=fn)


def _fn(cap: _Cap) -> str:
    """A never-output function's name: the effect, shutter effect, comment or type."""
    data = cap.data
    for key in ("effectName", "effectPreset", "shutterEffect", "comment"):
        if data.get(key):
            return _camel(str(data[key])) or _camel(cap.type)
    return _camel(cap.type) or "function"


def _linear_rgb(hex_colour: str) -> tuple[float, float, float]:
    """An sRGB ``#rrggbb`` as linear RGB."""
    text = hex_colour.lstrip("#")
    channels = [int(text[k : k + 2], 16) / 255 for k in (0, 2, 4)]

    def linear(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (round(linear(c), 4) for c in channels)
    return r, g, b


def _revision(data: Mapping[str, Any]) -> str:
    """``lastModifyDate`` plus 7 hex digits of the hash of the content and
    the importers' version."""
    content = json.dumps(data, sort_keys=True).encode() + _version()
    digest = hashlib.sha256(content).hexdigest()[:7]
    date = data.get("meta", {}).get("lastModifyDate")
    return f"{date}-{digest}" if date else digest


def _version() -> bytes:
    """What :data:`~busk.importers.IMPORT_VERSION` adds to a revision's hash."""
    return f"\0busk-import-{IMPORT_VERSION}".encode()


def _slug(text: str, prefix: str = "") -> str:
    return prefix + (re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x")


def _camel(text: str) -> str:
    words: list[str] = re.findall(r"[A-Za-z0-9]+", text)
    if not words:
        return ""
    return words[0][0].lower() + words[0][1:] + "".join(w[0].upper() + w[1:] for w in words[1:])


def _unique(ident: str, taken: set[str]) -> str:
    if ident not in taken:
        return ident
    n = 2
    while f"{ident}{n}" in taken:
        n += 1
    return f"{ident}{n}"


def _natural(key: str) -> list[Any]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", key)]


def _fmt(value: float) -> str:
    return f"{value:g}"
