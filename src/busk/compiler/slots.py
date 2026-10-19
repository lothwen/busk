"""The slot table: one slot per ``(target, attribute)`` of the rig (spec §6.1–§6.2).

A **slot** is the engine's unit of control: "the pan of fixture MH 1" or "the
colour of cell 3 of the bar". Every slot owns a contiguous run of float
**lanes** in the logical frame, the array the resolver writes each tick and
the converter turns into DMX:

========  =====  ==========================================================
Kind      Lanes  Encoding
========  =====  ==========================================================
scalar    1      the logical value (degrees, 0..1, Hz…)
color     3–6    ``r, g, b``, then the element's extras in the order
                 ``w, a, uv``; ``NaN`` in an extra means "derive it"
discrete  1      the index of the value in the slot's option list, as a float
========  =====  ==========================================================

Allocation is deterministic: fixtures in show order, elements in index
order, and each element's attributes in registry order (the §5.3 table). An
element gets a slot for

* every attribute that has a channel on it, except ``control``: control
  channels are untouched channels (§13.5) and keep their ``defaultDmx``;
* ``intensity`` when it is dimmed virtually (see
  :class:`~busk.compiler.rig.ElementInfo`), even without an intensity
  channel. This is the virtual dimmer of §13.2;
* every scalar attribute that parameterises a function capability of one of
  its (non-control) channels, such as ``strobeRate`` for a shutter's strobe
  range.

Unpatched fixtures get slots, because they are still programmable; they just
have no channels to convert.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, cast, get_args

import numpy as np
from numpy.typing import NDArray

from busk.compiler.lanes import encode_value
from busk.compiler.rig import ColorExtra, RigFixture
from busk.model.attributes import (
    ATTRIBUTES,
    AttributeDefinition,
    AttributeFamily,
    AttributeValue,
    DiscreteValue,
)
from busk.model.common import AttributeId, FixtureId, TargetKey, TargetRef, target_key
from busk.model.profile import ChannelDefinition, channel_default_option, option_capabilities

type SlotIndex = int
"""Dense index of a slot in :attr:`SlotTable.slots`."""

FAMILIES: Final[tuple[AttributeFamily, ...]] = get_args(AttributeFamily.__value__)
"""The attribute families in registry order. A family's *code* is its index
here: :attr:`SlotTable.laneFamily` and ``CompiledCue.leave`` use codes."""

FAMILY_CODES: Final[Mapping[AttributeFamily, int]] = MappingProxyType(
    {family: code for code, family in enumerate(FAMILIES)}
)
"""Family → code, the inverse of :data:`FAMILIES`."""


@dataclass(frozen=True, kw_only=True)
class Slot:
    """One controllable ``(target, attribute)`` and where its lanes live.

    ``options`` (discrete slots) are the option ids the lane indexes into, in
    DMX order: wheel slot ids, shutter functions, or a colour macro's presets
    and programs. ``wheels`` are the ids of
    the wheels those options belong to, used to check a value's optional
    ``wheel``. ``extras`` (colour slots) name the lanes after ``r, g, b``.
    """

    index: SlotIndex
    target: TargetRef
    attribute: AttributeDefinition
    laneOffset: int
    laneCount: int
    options: tuple[str, ...] = ()
    wheels: tuple[str, ...] = ()
    extras: tuple[ColorExtra, ...] = ()

    @property
    def lanes(self) -> slice:
        """This slot's lanes in a logical frame."""
        return slice(self.laneOffset, self.laneOffset + self.laneCount)


@dataclass(frozen=True, kw_only=True)
class SlotTable:
    """Every slot of the rig and the logical frame they share.

    ``defaultFrame`` holds each slot's registry default (§5.3): the value a
    slot has when no source controls it. It is read-only; the engine copies
    it into its working frame every tick.

    ``intensityLanes`` are the lanes of every HTP slot, ascending. Intensity
    is the registry's only HTP attribute, so these are exactly the lanes the
    resolver merges highest-takes-precedence (§7.4) and the lanes masters
    and blackout scale (§12). Read-only.

    ``laneSlot`` maps every lane to the index of the slot that owns it. The
    engine uses it to split the programmer's lanes by each slot's sequence
    number (Phase 3). Read-only.

    ``laneFamily`` holds every lane's family code (:data:`FAMILY_CODES`). A
    slot that leaves a cue fades with the cue's timing for its family
    (``CompiledCue.leave``, phase-4-plan §5.2). Read-only.

    ``keys`` are the keys of :attr:`byKey` in slot order (Phase 7). The
    engine process receives the table without ``slots`` and ``byKey``
    (:func:`busk.process.wire.engine_view`) and matches slots by these keys
    when it must compute a remap itself (phase-7-plan decision 8).
    """

    slots: tuple[Slot, ...]
    laneCount: int
    byKey: Mapping[tuple[TargetKey, AttributeId], SlotIndex]
    defaultFrame: NDArray[np.float64]
    intensityLanes: NDArray[np.intp]
    laneSlot: NDArray[np.intp]
    laneFamily: NDArray[np.int8]
    keys: tuple[tuple[TargetKey, AttributeId], ...] = ()

    def find(self, target: TargetRef, attribute: AttributeId) -> Slot | None:
        """The slot of ``attribute`` on ``target``, or ``None`` if it has none."""
        index = self.byKey.get((target_key(target), attribute))
        return None if index is None else self.slots[index]


def build_slots(rig: Sequence[RigFixture]) -> SlotTable:
    """Allocate the slots and lanes of ``rig`` and build the default frame."""
    slots: list[Slot] = []
    defaults: list[float] = []
    lane = 0
    for fixture in rig:
        for element in range(len(fixture.elements)):
            target = TargetRef(fixtureId=FixtureId(fixture.fixture["id"]), element=element)
            for definition, channel in _element_attributes(fixture, element):
                slot = _make_slot(fixture, element, target, definition, channel, len(slots), lane)
                slots.append(slot)
                default = _default_value(fixture, element, definition, channel)
                defaults.extend(encode_value(slot, default))
                lane += slot.laneCount
    frame = np.array(defaults, dtype=np.float64)
    frame.flags.writeable = False
    # Slots are allocated in lane order, so these lanes are already ascending.
    intensity = np.array(
        [slot.laneOffset for slot in slots if slot.attribute.merge == "HTP"], dtype=np.intp
    )
    intensity.flags.writeable = False
    lane_slot = np.repeat(
        np.arange(len(slots), dtype=np.intp), [slot.laneCount for slot in slots]
    ).astype(np.intp)
    lane_slot.flags.writeable = False
    codes = np.array([FAMILY_CODES[slot.attribute.family] for slot in slots], dtype=np.int8)
    lane_family = codes[lane_slot]
    lane_family.flags.writeable = False
    by_key = {(target_key(slot.target), slot.attribute.id): slot.index for slot in slots}
    return SlotTable(
        slots=tuple(slots),
        laneCount=lane,
        byKey=MappingProxyType(by_key),
        defaultFrame=frame,
        intensityLanes=intensity,
        laneSlot=lane_slot,
        laneFamily=lane_family,
        keys=tuple(by_key),
    )


def _element_attributes(
    fixture: RigFixture, element: int
) -> list[tuple[AttributeDefinition, ChannelDefinition | None]]:
    """The attributes of ``element`` that get a slot, in registry order, each
    with the element's channel for it (``None`` for derived slots)."""
    channels: dict[AttributeId, ChannelDefinition] = {}
    derived: set[AttributeId] = set()
    for channel in fixture.channels[element]:
        if channel["attribute"] == "control":
            continue  # untouched (§13.5): neither the channel nor its params get slots
        # Colour has one channel per component; any one of them will do.
        channels.setdefault(channel["attribute"], channel)
        for capability in channel["capabilities"]:
            if capability["kind"] == "function" and "param" in capability:
                derived.add(capability["param"]["attribute"])
    if fixture.elements[element].virtualIntensity:
        derived.add("intensity")
    return [
        (definition, channels.get(attribute))
        for attribute, definition in ATTRIBUTES.items()
        if attribute in channels or attribute in derived
    ]


def _make_slot(
    fixture: RigFixture,
    element: int,
    target: TargetRef,
    definition: AttributeDefinition,
    channel: ChannelDefinition | None,
    index: SlotIndex,
    lane: int,
) -> Slot:
    if definition.kind == "color":
        extras = fixture.elements[element].extras
        return Slot(
            index=index,
            target=target,
            attribute=definition,
            laneOffset=lane,
            laneCount=3 + len(extras),
            extras=extras,
        )
    if definition.kind == "discrete":
        # Discrete attributes always come from a channel: params are scalar.
        options = option_capabilities(cast(ChannelDefinition, channel))
        wheels = [cap["wheel"] for _, cap in options if cap["kind"] == "slot" and "wheel" in cap]
        return Slot(
            index=index,
            target=target,
            attribute=definition,
            laneOffset=lane,
            laneCount=1,
            options=tuple(option for option, _ in options),
            wheels=tuple(dict.fromkeys(wheels)),
        )
    return Slot(index=index, target=target, attribute=definition, laneOffset=lane, laneCount=1)


def _default_value(
    fixture: RigFixture,
    element: int,
    definition: AttributeDefinition,
    channel: ChannelDefinition | None,
) -> AttributeValue:
    """The registry default, with ``zoom``'s "profile midpoint" and the colour
    macros' "channel default" resolved."""
    if definition.default == "profileMidpoint":
        return _profile_midpoint(fixture, element, definition.id)
    if definition.default == "channelDefault":
        # Validation guarantees the channel offers at least one option.
        option = channel_default_option(cast(ChannelDefinition, channel))
        return DiscreteValue(slot=cast(str, option))
    return definition.default


def _profile_midpoint(fixture: RigFixture, element: int, attribute: AttributeId) -> float:
    """Midpoint of the profile's range for ``attribute`` (only ``zoom`` uses it).

    ``physical.zoomRange`` is the authority. Without it, the midpoint of the
    logical values the element's capabilities reach for the attribute is
    used: its channel's range capabilities and any function parameter.
    """
    zoom_range = fixture.profile["physical"].get("zoomRange")
    if attribute == "zoom" and zoom_range is not None:
        return (zoom_range[0] + zoom_range[1]) / 2
    values: list[float] = []
    for channel in fixture.channels[element]:
        for capability in channel["capabilities"]:
            if capability["kind"] == "range" and channel["attribute"] == attribute:
                values.extend(capability["value"])
            elif (
                capability["kind"] == "function"
                and "param" in capability
                and capability["param"]["attribute"] == attribute
            ):
                values.extend(capability["param"]["value"])
    return (min(values) + max(values)) / 2
