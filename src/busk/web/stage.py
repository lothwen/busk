"""The stage view: the show's rig in 3D, lit by the engine's frames (``static/stage.html``).

The page is served at ``/stage`` beside the phone page, behind the same key,
and reads the same WebSocket: it sends ``{"type": "stage"}``, and from then
on gets a ``rig`` message, and a ``look`` message each time a fixture's look
changes (:class:`~busk.web.api.WebApi`). It draws with three.js, which it
loads from jsDelivr: the browser needs the internet the first time.

The rig
-------
:func:`build_rig` reads the show the session holds. Each fixture stands
where its ``location`` puts it (``fixture 101 location {"x": …, "y": …,
"z": …, "rx": …, "ry": …, "rz": …}``), read as:

* metres from the middle of the stage's downstage edge, at deck height;
  x towards stage right, y downstage (into the audience), z up;
* rx, ry and rz in degrees, turned about x, then y, then z. At 0 a fixture
  stands on its base and throws its beam straight up, so a hung one is rx
  180, and one facing the audience is rx -90. A moving head at pan 0, tilt
  0 points along its base; positive tilt swings the beam towards the
  fixture's front (its +y), positive pan turns it anticlockwise.

A fixture without a location is put in a row with the others of its kind
(:func:`place_the_rest`). The kind comes from the profile's ``category``:
spot, wash and beam draw a moving head, pixel a bar, blinder and strobe a
blinder, fog a smoke machine, anything else a can. Without a category, a
profile with pan or tilt is a head, one with several elements a bar (with
colour) or a blinder (without), and anything else a can.

The looks
---------
:class:`StageFeed` reads each fixture's footprint out of the engine's newest
frame (what busk sends, after the masters, park, blackout and limits, also
while ``output off`` holds) through its profile mode: intensity, colour (the
emitters, CMY flags and colour-wheel slots), the shutter and strobe rate,
pan, tilt and zoom (:meth:`StageFixture.decode`). Not drawn: gobos, prisms,
frost, and the programs a fixture runs by itself. An unpatched fixture stays
at its channels' defaults.

Messages
--------
``rig``: ``title``, ``stage`` (``width``, ``depth``, ``height``: the deck,
sized to the rig) and ``fixtures`` (``number``, ``name``, ``kind``,
``cells``, ``loc``), in show order. ``look``: ``looks``, one list per fixture
in the rig's order: ``r, g, b`` of each cell with its intensity in, then
pan, tilt, zoom (degrees), the shutter (:data:`SHUTTER`) and the strobe rate
(Hz).
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from busk.engine.loop import Frame
from busk.model.common import UniverseId
from busk.model.fixture import Location
from busk.model.profile import Capability, FixtureMode, FixtureProfile
from busk.model.show import Show

type RGB = tuple[float, float, float]

KINDS: Final = {
    "spot": "head", "wash": "head", "beam": "head",
    "pixel": "bar", "blinder": "blinder", "strobe": "blinder", "fog": "fog",
}  # fmt: skip
"""What a profile category is drawn as; any other category is a ``par``."""

BEAM_ANGLE: Final = {"head": 18.0, "par": 25.0, "blinder": 50.0, "bar": 90.0, "fog": 0.0}
"""Beam angle (degrees) of a fixture without a zoom channel or a zoom range."""

EMITTERS: Final[dict[str, RGB]] = {
    "red": (1.0, 0.0, 0.0), "green": (0.0, 1.0, 0.0), "blue": (0.0, 0.0, 1.0),
    "white": (1.0, 1.0, 1.0), "amber": (1.0, 0.45, 0.0), "lime": (0.6, 1.0, 0.0),
    "cyan": (0.0, 1.0, 1.0), "uv": (0.3, 0.0, 1.0),
    "cyanFlag": (0.0, 1.0, 1.0), "magentaFlag": (1.0, 0.0, 1.0), "yellowFlag": (1.0, 1.0, 0.0),
}  # fmt: skip
"""Emitter colours (linear RGB) for a profile that lists no emitters of its own."""

SUBTRACTIVE: Final = frozenset({"cyanFlag", "magentaFlag", "yellowFlag"})

SHUTTER: Final = {"open": 0, "closed": 1, "strobe": 2, "pulse": 3, "random": 4}
"""Shutter functions, as the page draws them; any other function is open."""

ROWS: Final = {
    "head": (-3.0, 6.0, 180.0, 1.0),
    "par": (-1.0, 5.5, 180.0, 1.0),
    "blinder": (-5.5, 6.5, -120.0, 1.0),
    "bar": (-0.3, 0.05, -90.0, 1.1),
    "fog": (-2.0, 0.15, -90.0, 1.5),
}
"""Where fixtures without a location go: (y, z, rx, spacing) per kind."""

DECK_HEIGHT: Final = 1.2
"""Metres from the audience's floor to the stage's."""


# ==========================================================================
# The rig: the show's fixtures and how to read their DMX
# ==========================================================================


@dataclass
class Channel:
    """One channel of a mode, ready to read out of a fixture's footprint."""

    attribute: str
    element: int
    component: str
    offsets: tuple[int, ...]  # coarse byte first, within the footprint
    top: int  # the largest raw value: 255, 65535, …
    invert: bool
    default: int  # raw value, in full resolution
    capabilities: Sequence[Capability]

    def read(self, piece: bytes) -> tuple[int, Capability | None]:
        raw = 0
        for offset in self.offsets:
            raw = raw << 8 | piece[offset]
        if self.invert:
            raw = self.top - raw
        for capability in self.capabilities:
            low, high = capability["dmx"]
            if low <= raw <= high:
                return raw, capability
        return raw, None


def between(dmx: tuple[int, int], raw: int, values: tuple[float, float]) -> float:
    """``raw`` mapped from the DMX range ``dmx`` onto ``values``."""
    low, high = dmx
    first, last = values
    return first if high == low else first + (last - first) * (raw - low) / (high - low)


@dataclass
class StageFixture:
    """A fixture of the rig: where it is, and how to read its footprint."""

    index: int
    number: int
    name: str
    kind: str
    elements: int
    footprint: int
    universe: UniverseId | None  # None when not patched
    start: int  # 0-based
    channels: list[Channel]
    emitters: dict[str, tuple[RGB, bool]]  # id: (rgb, subtractive)
    slot_colors: dict[str, RGB]  # colour-wheel slot id: rgb
    beam: float  # degrees, without a zoom channel
    location: Location | None  # None until placed, when the show has not
    last: bytes = b""

    def resting(self) -> bytes:
        """The footprint with every channel at its default: what the fixture
        shows before any DMX arrives."""
        piece = bytearray(self.footprint)
        for channel in self.channels:
            value = channel.default
            for offset in reversed(channel.offsets):
                piece[offset] = value & 0xFF
                value >>= 8
        return bytes(piece)

    def decode(self, piece: bytes) -> list[float]:
        """The fixture's look: r, g, b of each element (with its intensity
        in), then pan, tilt, zoom, the shutter function and the strobe rate."""
        count = self.elements
        level: list[float | None] = [None] * count
        added = [[0.0, 0.0, 0.0] for _ in range(count)]
        mixed = [False] * count
        tint = [[1.0, 1.0, 1.0] for _ in range(count)]
        pan = tilt = hz = 0.0
        zoom = self.beam
        shutter = 0
        for channel in self.channels:
            raw, capability = channel.read(piece)
            if capability is None:
                continue
            attribute, element = channel.attribute, channel.element
            if capability["kind"] == "range":
                value = between(capability["dmx"], raw, capability["value"])
                if attribute == "intensity":
                    level[element] = value
                elif attribute == "color":
                    rgb, subtractive = self.emitters.get(
                        channel.component, ((0.0, 0.0, 0.0), False)
                    )
                    for i in range(3):
                        if subtractive:
                            tint[element][i] *= 1.0 - value * (1.0 - rgb[i])
                        else:
                            added[element][i] += value * rgb[i]
                    mixed[element] = mixed[element] or not subtractive
                elif attribute == "pan":
                    pan = value
                elif attribute == "tilt":
                    tilt = value
                elif attribute == "zoom":
                    zoom = value
                elif attribute == "strobeRate":
                    hz = value
            elif capability["kind"] == "slot" and attribute == "color":
                rgb = self.slot_colors.get(capability["slot"], (1.0, 1.0, 1.0))
                tint[element] = [t * c for t, c in zip(tint[element], rgb, strict=True)]
            elif capability["kind"] == "function" and attribute == "shutter":
                shutter = SHUTTER.get(capability["fn"], 0)
                param = capability.get("param")
                if param and param["attribute"] == "strobeRate":
                    hz = between(capability["dmx"], raw, param["value"])
        look: list[float] = []
        for element in range(count):
            # An element without its own intensity or colour has the fixture's
            # (element 0's); a fixture with no intensity at all mixes its level
            # into its colour.
            own = level[element] if level[element] is not None else level[0]
            base = added[element] if mixed[element] else added[0] if mixed[0] else [1.0, 1.0, 1.0]
            filters = (
                tint[element]
                if element == 0
                else [a * b for a, b in zip(tint[element], tint[0], strict=True)]
            )
            gain = 1.0 if own is None else own
            look += [round(c * f * gain, 3) for c, f in zip(base, filters, strict=True)]
        return [*look, round(pan, 2), round(tilt, 2), round(zoom, 2), shutter, round(hz, 2)]


def kind_of(profile: FixtureProfile, mode: FixtureMode) -> str:
    """What the page draws a fixture of ``profile`` in ``mode`` as."""
    category = profile.get("category")
    if category:
        return KINDS.get(category, "par")
    attributes = {channel["attribute"] for channel in mode["channels"]}
    if attributes & {"pan", "tilt"}:
        return "head"
    if len(mode["elements"]) > 1:
        return "bar" if "color" in attributes else "blinder"
    return "par"


def channels_of(mode: FixtureMode) -> list[Channel]:
    channels = []
    for definition in mode["channels"]:
        size = definition["bytes"]
        fine = definition.get("fineOffsets") or [definition["offset"] + i for i in range(1, size)]
        channels.append(Channel(
            attribute=definition["attribute"],
            element=definition["element"],
            component=definition.get("component", ""),
            offsets=(definition["offset"], *fine[: size - 1]),
            top=(1 << (8 * size)) - 1,
            invert=definition.get("invert", False),
            default=definition["defaultDmx"],
            capabilities=definition["capabilities"],
        ))  # fmt: skip
    return channels


def build_rig(show: Show) -> list[StageFixture]:
    """The show's fixtures, in show order, each with a location."""
    profiles = {profile["id"]: profile for profile in show["profiles"]}
    fixtures: list[StageFixture] = []
    for index, entry in enumerate(show["fixtures"]):
        profile = profiles[entry["profileId"]]
        mode = next(m for m in profile["modes"] if m["id"] == entry["modeId"])
        kind = kind_of(profile, mode)
        emitters = {key: (rgb, key in SUBTRACTIVE) for key, rgb in EMITTERS.items()}
        for emitter in profile.get("emitters", []):
            color = emitter["color"]
            emitters[emitter["id"]] = ((color["r"], color["g"], color["b"]),
                                       emitter.get("subtractive", False))  # fmt: skip
        slot_colors = {
            slot["id"]: (slot["color"]["r"], slot["color"]["g"], slot["color"]["b"])
            for wheel in profile["wheels"] if wheel["kind"] == "color"
            for slot in wheel["slots"] if "color" in slot
        }  # fmt: skip
        zoom_range = profile["physical"].get("zoomRange")
        patch = entry["patch"]
        fixtures.append(StageFixture(
            index=index,
            number=entry["number"],
            name=entry["name"],
            kind=kind,
            elements=len(mode["elements"]),
            footprint=mode["footprint"],
            universe=patch["universeId"] if patch else None,
            start=patch["address"] - 1 if patch else 0,
            channels=channels_of(mode),
            emitters=emitters,
            slot_colors=slot_colors,
            beam=sum(zoom_range) / 2 if zoom_range else BEAM_ANGLE[kind],
            location=entry.get("location"),
        ))  # fmt: skip
    place_the_rest(fixtures)
    return fixtures


def place_the_rest(fixtures: list[StageFixture]) -> None:
    """A row per kind for the fixtures the show has not placed, in number order."""
    rows: dict[str, list[StageFixture]] = defaultdict(list)
    for fixture in sorted(fixtures, key=lambda f: f.number):
        if fixture.location is None:
            rows[fixture.kind].append(fixture)
    for kind, row in rows.items():
        y, z, rx, spacing = ROWS[kind]
        for i, fixture in enumerate(row):
            x = (i - (len(row) - 1) / 2) * spacing
            fixture.location = {"x": x, "y": y, "z": z, "rx": rx, "ry": 0.0, "rz": 0.0}


def rig_message(show: Show, fixtures: list[StageFixture]) -> dict[str, object]:
    """What the page builds the stage from."""
    places = [f.location for f in fixtures if f.location is not None]
    xs = [abs(place["x"]) for place in places] or [0.0]
    ys = [-place["y"] for place in places if place["y"] <= 0] or [0.0]
    return {
        "type": "rig",
        "title": show["meta"]["title"] or "busk",
        "stage": {"width": 2 * max(6.0, max(xs) + 1.0), "depth": max(6.0, max(ys) + 1.5),
                  "height": DECK_HEIGHT},
        "fixtures": [{"number": f.number, "name": f.name, "kind": f.kind, "cells": f.elements,
                      "loc": f.location} for f in fixtures],
    }  # fmt: skip


def dumps(message: dict[str, object]) -> str:
    return json.dumps(message, separators=(",", ":"))


# ==========================================================================
# The feed: the engine's frames in, each fixture's look out
# ==========================================================================


class StageFeed:
    """The rig of the show the session holds, and each fixture's look in the
    engine's newest frame, as the texts of the ``rig`` and ``look`` messages.

    Not thread-safe: the web API calls it under its lock.
    """

    def __init__(self) -> None:
        self._show: Show | None = None
        self._fixtures: list[StageFixture] = []
        self._looks: list[list[float]] = []
        self._frame: Frame | None = None
        self.rig: str | None = None
        """The ``rig`` message's text; ``None`` before the first :meth:`update`."""
        self.look: str | None = None
        """The ``look`` message's text; ``None`` before the first :meth:`update`."""

    def update(self, show: Show, frame: Frame | None) -> tuple[str | None, str | None]:
        """Read ``show`` (when it is not the one read last) and ``frame``;
        return the texts of the ``rig`` and ``look`` messages that changed,
        ``None`` for one that did not.

        Any show change rebuilds the rig (in milliseconds), but the ``rig``
        message changes only when what the page draws does: the page reloads
        for a new one.
        """
        rig = look = None
        rebuilt = show is not self._show
        if rebuilt:
            self._show = show
            self._fixtures = build_rig(show)
            self._looks = [fixture.decode(fixture.resting()) for fixture in self._fixtures]
            text = dumps(rig_message(show, self._fixtures))
            if text != self.rig:
                self.rig = rig = text
        changed = rebuilt
        if frame is not None and (rebuilt or frame is not self._frame):
            self._frame = frame
            assert frame.layout is not None  # only hand-built test frames lack it
            rows = {universe.id: row for row, universe in enumerate(frame.layout.universes)}
            for fixture in self._fixtures:
                row = rows.get(fixture.universe) if fixture.universe is not None else None
                if row is None:
                    continue
                piece = frame.universes[row][fixture.start : fixture.start + fixture.footprint]
                if piece != fixture.last and len(piece) == fixture.footprint:
                    fixture.last = piece
                    self._looks[fixture.index] = fixture.decode(piece)
                    changed = True
        if changed:
            text = dumps({"type": "look", "looks": self._looks})
            if text != self.look:
                self.look = look = text
        return rig, look
