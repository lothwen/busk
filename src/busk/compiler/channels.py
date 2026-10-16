"""Compiled channels: every slot-driven DMX channel, pre-resolved (spec §13).

There is one :class:`CompiledChannel` per channel of a patched fixture that a
slot drives. Control channels are not compiled: they are untouched channels
and keep the ``defaultDmx`` the base image already holds (§13.5).

A record is the readable form of everything conversion needs, resolved at
compile time so the tick does no lookups:

* **where** it writes: universe row and 0-based byte addresses, coarse byte
  first. An address is ``None`` when a later fixture in show order owns that
  byte. That is the base image's overlap rule, and it keeps every written
  address unique;
* **what** it reads: its input slot and, for colour, the virtual-intensity
  slot;
* **how** it maps: range segments (after ``invert``), pan/tilt orientation,
  the dimmer curve, the emitter it drives, or its option table;
* its ``highlightDmx``, if any, which the programmer's highlight writes
  (phase-7-plan §5.12; the converter never reads it).

The vectorised converter flattens these records into arrays
(:mod:`busk.convert.plan`); the test suite's reference converter reads them
one by one.

Conversion rules that the records encode
----------------------------------------
* **Capabilities are authoritative for scalars**, pan and tilt included. A
  pan range of ±270° is just a capability with ``value [-270, 270]``;
  ``physical.panRange`` is informational.
* ``invert`` reverses each range capability's value direction (``v0`` and
  ``v1`` swap), so DMX ranges and ``defaultDmx`` always stay wire values.
  It does not affect option tables or function parameters.
* **Orientation** (pan and tilt, every element): the input is the other
  attribute's slot when ``swapPanTilt`` is set, then
  ``deg = (input + offset) * sign``, where the offset and the inversion are
  the *channel's* own settings: the pan channel uses ``panOffset`` and
  ``invertPan`` even when it reads the tilt value.
* **Options** output the centre of their DMX range, ``(lo + hi) // 2``,
  never an edge that some fixtures misread (§13.4).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from busk.compiler.rig import RigFixture, byte_offsets
from busk.compiler.slots import SlotIndex, SlotTable
from busk.model.common import FixtureId, TargetRef, UniverseId
from busk.model.profile import (
    Capability,
    ChannelDefinition,
    DimmerCurve,
    emitter_is_subtractive,
    option_capabilities,
)

type ChannelKind = Literal["range", "color", "option"]


@dataclass(frozen=True, kw_only=True)
class Segment:
    """A linear map from logical values ``v0 → v1`` to raw DMX ``d0 → d1``.

    Raw values are in the channel's full resolution (``0 .. 256**bytes − 1``).
    ``v0 > v1`` is allowed: it is how ``invert`` and descending charts (a
    counter-clockwise speed range) are expressed. A zero-span segment
    (``v0 == v1``) outputs the centre of its DMX range.
    """

    v0: float
    v1: float
    d0: int
    d1: int

    @property
    def low(self) -> float:
        return min(self.v0, self.v1)

    @property
    def high(self) -> float:
        return max(self.v0, self.v1)


@dataclass(frozen=True, kw_only=True)
class OptionOut:
    """What a discrete option outputs: a fixed raw value, or for a function
    with a parameter (a strobe range) the parameter slot mapped through the
    capability's DMX range."""

    raw: int  # centre of the capability's DMX range
    param: tuple[SlotIndex, Segment] | None = None


@dataclass(frozen=True, kw_only=True)
class CompiledChannel:
    """One slot-driven DMX channel of a patched fixture (see module docs)."""

    fixtureId: FixtureId
    offset: int  # coarse byte within the footprint, for diagnostics
    universe: int  # row in the universe buffers
    addresses: tuple[int | None, ...]  # 0-based; coarse[, fine[, ultra]]; None = not owned
    kind: ChannelKind
    slot: SlotIndex  # main input (after pan/tilt swap)
    segments: tuple[Segment, ...] = ()  # range, color
    offsetDeg: float = 0.0  # range: pan/tilt orientation offset
    sign: float = 1.0  # range: -1.0 when pan/tilt is inverted
    curve: DimmerCurve | None = None  # intensity channels; colour with virtual intensity
    component: str | None = None  # color: the emitter id this channel drives
    subtractive: bool = False  # color: the emitter is a CMY flag
    intensitySlot: SlotIndex | None = None  # color: virtual intensity
    options: tuple[OptionOut, ...] = ()  # option
    highlight: int | None = None  # highlightDmx, full resolution (Phase 7 highlight)

    @property
    def bytes(self) -> int:
        """The channel's resolution in bytes (1, 2 or 3)."""
        return len(self.addresses)


def build_channels(
    rig: Sequence[RigFixture], slots: SlotTable, rows: Mapping[UniverseId, int]
) -> tuple[CompiledChannel, ...]:
    """Compile the slot-driven channels of every patched fixture in ``rig``.

    ``rows`` maps universe ids to rows of the universe buffers. Records come
    in fixture order, then mode channel order.
    """
    owners = _byte_owners(rig, rows)
    compiled: list[CompiledChannel] = []
    for fixture in rig:
        patch = fixture.fixture["patch"]
        if patch is None:
            continue
        row = rows[patch["universeId"]]
        start = patch["address"] - 1
        for channel in fixture.mode["channels"]:
            if channel["attribute"] == "control":
                continue
            addresses = tuple(
                address if owners[row, address] == fixture.index else None
                for address in (start + offset for offset in byte_offsets(channel))
            )
            compiled.append(_compile_channel(fixture, channel, slots, row, addresses))
    return tuple(compiled)


def _byte_owners(
    rig: Sequence[RigFixture], rows: Mapping[UniverseId, int]
) -> dict[tuple[int, int], int]:
    """Which fixture owns each patched byte: the later one in show order.

    Every channel counts, driven or untouched, exactly as the compiler writes
    the base image, so a byte belongs to the fixture whose ``defaultDmx`` the
    base image holds there.
    """
    owners: dict[tuple[int, int], int] = {}
    for fixture in rig:
        patch = fixture.fixture["patch"]
        if patch is None:
            continue
        row = rows[patch["universeId"]]
        start = patch["address"] - 1
        for channel in fixture.mode["channels"]:
            for offset in byte_offsets(channel):
                owners[row, start + offset] = fixture.index
    return owners


def _compile_channel(
    fixture: RigFixture,
    channel: ChannelDefinition,
    slots: SlotTable,
    row: int,
    addresses: tuple[int | None, ...],
) -> CompiledChannel:
    element = channel["element"]
    fixture_id = FixtureId(fixture.fixture["id"])
    target = TargetRef(fixtureId=fixture_id, element=element)
    attribute = channel["attribute"]
    offset = channel["offset"]
    own = _slot(slots, target, attribute)
    segments = _segments(channel)
    highlight = channel.get("highlightDmx")

    if attribute == "color":
        component = channel["component"]
        info = fixture.elements[element]
        return CompiledChannel(
            fixtureId=fixture_id,
            offset=offset,
            universe=row,
            addresses=addresses,
            kind="color",
            slot=own,
            segments=segments,
            component=component,
            subtractive=bool(emitter_is_subtractive(fixture.profile, component)),
            curve=fixture.dimmer_curve if info.virtualIntensity else None,
            intensitySlot=_slot(slots, target, "intensity") if info.virtualIntensity else None,
            highlight=highlight,
        )

    if slots.slots[own].attribute.kind == "discrete":
        return CompiledChannel(
            fixtureId=fixture_id,
            offset=offset,
            universe=row,
            addresses=addresses,
            kind="option",
            slot=own,
            options=tuple(
                _option(capability, slots, target) for _, capability in option_capabilities(channel)
            ),
            highlight=highlight,
        )

    source, degrees, sign = own, 0.0, 1.0
    if attribute in ("pan", "tilt"):
        orientation = fixture.fixture["orientation"]
        if orientation["swapPanTilt"]:
            source = _slot(slots, target, "tilt" if attribute == "pan" else "pan")
        if attribute == "pan":
            degrees, inverted = orientation["panOffset"], orientation["invertPan"]
        else:
            degrees, inverted = orientation["tiltOffset"], orientation["invertTilt"]
        sign = -1.0 if inverted else 1.0
    return CompiledChannel(
        fixtureId=fixture_id,
        offset=offset,
        universe=row,
        addresses=addresses,
        kind="range",
        slot=source,
        segments=segments,
        offsetDeg=float(degrees),
        sign=sign,
        curve=fixture.dimmer_curve if attribute == "intensity" else None,
        highlight=highlight,
    )


def _slot(slots: SlotTable, target: TargetRef, attribute: str) -> SlotIndex:
    slot = slots.find(target, attribute)
    if slot is None:  # the slot compiler allocates one for every driven channel
        raise AssertionError(f"no {attribute!r} slot for {target}")
    return slot.index


def _segments(channel: ChannelDefinition) -> tuple[Segment, ...]:
    """The channel's range capabilities as segments, with ``invert`` applied."""
    invert = channel.get("invert", False)
    segments: list[Segment] = []
    for capability in channel["capabilities"]:
        if capability["kind"] != "range":
            continue
        v0, v1 = capability["value"]
        if invert:
            v0, v1 = v1, v0
        d0, d1 = capability["dmx"]
        segments.append(Segment(v0=float(v0), v1=float(v1), d0=d0, d1=d1))
    return tuple(segments)


def _option(capability: Capability, slots: SlotTable, target: TargetRef) -> OptionOut:
    low, high = capability["dmx"]
    if capability["kind"] == "function" and "param" in capability:
        param = capability["param"]
        v0, v1 = param["value"]
        return OptionOut(
            raw=(low + high) // 2,
            param=(
                _slot(slots, target, param["attribute"]),
                Segment(v0=float(v0), v1=float(v1), d0=low, d1=high),
            ),
        )
    return OptionOut(raw=(low + high) // 2)
