"""Programmer frames and slot remaps: what the session hands the engine
(phase-3-plan §5.7 "Building a frame").

Everything here runs on the session's thread, never the engine's: resolving
programmer values to lanes, splitting them the way the resolver merges them,
building the highlight, and computing the slot remap after a recompile are
O(slots) Python work the engine tick must not pay for.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Final

import numpy as np
from numpy.typing import NDArray

from busk.compiler.cues import CueCompiler, clamp_lanes, cue_from_values
from busk.compiler.effects import CompiledEffect
from busk.compiler.lanes import EncodeError, encode_value
from busk.compiler.slots import SlotIndex, SlotTable
from busk.engine.install import Highlight, ProgrammerFrame
from busk.model.attributes import AttributeValue
from busk.model.effect import EffectInstance
from busk.model.validate import validate_effect
from busk.session.programmer import Programmer, ProgSource, SlotKey, split_slot_key
from busk.session.state import ShowState


def build_frame(
    state: ShowState,
    programmer: Programmer,
    previous: Mapping[SlotKey, ProgSource],
    *,
    previous_effects: Sequence[EffectInstance] = (),
    written: Collection[SlotKey] = (),
    written_effects: Collection[str] = (),
    touch_all: bool = False,
) -> ProgrammerFrame:
    """The programmer resolved against ``state``'s compiled show.

    Each value whose slot exists is resolved like a cue entry (a preset
    reference through the §5.8 scope lookup) and clamped. Values whose slot
    is gone, whose preset no longer defines them, or whose discrete option
    the target no longer offers are left out (they stay in the programmer).

    ``touched`` holds the slots whose *source* differs from ``previous``, and
    the slots a command ``written`` (set again, even to the same value): a
    preset edited underneath a reference is not a touch. With ``touch_all``
    (blind switched off) every slot counts as touched, so leaving blind
    applies the programmer *now*.

    The effects compile like a cue's (:func:`programmer_effects`), and
    ``touchedEffects`` follows the same rule: the instances that differ
    from the one with their ``id`` in ``previous_effects``, and the ids a
    command ``written_effects``.

    ``highlight`` is :func:`highlight_of` the programmer: it follows the
    selection whether or not the programmer is blind.
    """
    slots = state.compiled.slots
    values: dict[SlotIndex, tuple[float, ...]] = {}
    touched: list[SlotIndex] = []
    for key, source in programmer.values.items():
        split = split_slot_key(key)
        slot = None if split is None else slots.find(*split)
        if slot is None:
            continue  # dormant: the slot does not exist (now)
        try:
            lanes = state.values.resolve(source, slot, 0, 1)
        except EncodeError:
            continue  # a discrete option this target no longer offers
        if lanes is None:
            continue  # the preset no longer defines this attribute here
        values[slot.index] = clamp_lanes(slot, lanes)
        if touch_all or key in written or previous.get(key) != source:
            touched.append(slot.index)
    order = sorted(values)
    lanes_out = [lane for index in order for lane in values[index]]
    effects = programmer_effects(state, programmer.effects)
    before = {effect["id"]: effect for effect in previous_effects}
    instances = {effect["id"]: effect for effect in programmer.effects}
    touched_effects = frozenset(
        effect.key
        for effect in effects
        if touch_all
        or effect.key in written_effects
        or before.get(effect.key) != instances[effect.key]
    )
    return ProgrammerFrame(
        slots=_readonly(np.array(order, dtype=np.int32)),
        lanes=_readonly(np.array(lanes_out, dtype=np.float64)),
        touched=_readonly(np.array(sorted(touched), dtype=np.int32)),
        blind=programmer.blind,
        fadeTime=programmer.fadeTime,
        cue=cue_from_values(slots, values),
        effects=effects,
        touchedEffects=touched_effects,
        highlight=highlight_of(state, programmer),
    )


HIGHLIGHT_VALUES: Final[tuple[tuple[str, AttributeValue], ...]] = (
    ("intensity", 1.0),
    ("shutter", {"slot": "open"}),
    ("color", {"r": 1.0, "g": 1.0, "b": 1.0}),  # extras left out: derived
)
"""What highlight forces on each selected target, attribute by attribute
(phase-7-plan decision 12)."""

_NO_HIGHLIGHT_DMX: Final = frozenset({"pan", "tilt"}) | {a for a, _ in HIGHLIGHT_VALUES}
"""Attributes whose channels never take ``highlightDmx``: pan and tilt
(highlight must not move a head), and the ones highlight sets logically."""


def highlight_of(state: ShowState, programmer: Programmer) -> Highlight | None:
    """The highlight of the programmer's selection against ``state``'s
    compiled show (phase-7-plan §5.12), or ``None`` while the mode is off or
    nothing selected can be highlighted.

    Each selected target gets :data:`HIGHLIGHT_VALUES`, where it has the
    slot (and, for the shutter, the ``open`` option). Its other channels
    with a ``highlightDmx`` get those bytes, split coarse, fine and ultra;
    bytes a later fixture owns are skipped. Pan and tilt never take part,
    and neither does a parked slot: park wins over highlight.
    """
    if not programmer.highlight or not programmer.selection:
        return None
    compiled = state.compiled
    slots = compiled.slots
    safety = compiled.safety
    parked = {int(s) for s in slots.laneSlot[safety.parkIntensity]}
    parked.update(int(s) for s in slots.laneSlot[safety.parkLanes])

    lanes: list[int] = []
    values: list[float] = []
    for target in programmer.selection:
        for attribute, value in HIGHLIGHT_VALUES:
            slot = slots.find(target, attribute)
            if slot is None or slot.index in parked:
                continue
            try:
                encoded = encode_value(slot, value)
            except EncodeError:
                continue  # a shutter without an "open" option
            lanes.extend(range(slot.laneOffset, slot.laneOffset + slot.laneCount))
            values.extend(encoded)

    selected = {(t["fixtureId"], t["element"]) for t in programmer.selection}
    positions: list[int] = []
    raw: list[int] = []
    for channel in compiled.channels:
        if channel.highlight is None or channel.slot in parked:
            continue
        slot = slots.slots[channel.slot]
        target = slot.target
        if slot.attribute.id in _NO_HIGHLIGHT_DMX or (
            (target["fixtureId"], target["element"]) not in selected
        ):
            continue
        last = len(channel.addresses) - 1
        for k, address in enumerate(channel.addresses):  # coarse byte first
            if address is not None:
                positions.append(channel.universe * 512 + address)
                raw.append((channel.highlight >> (8 * (last - k))) & 0xFF)

    if not lanes and not positions:
        return None
    return Highlight(
        lanes=_readonly(np.array(lanes, dtype=np.intp)),
        values=_readonly(np.array(values, dtype=np.float64)),
        bytes=_readonly(np.array(positions, dtype=np.intp)),
        byteValues=_readonly(np.array(raw, dtype=np.uint8)),
    )


def programmer_effects(
    state: ShowState, instances: Sequence[EffectInstance]
) -> tuple[CompiledEffect, ...]:
    """The programmer's effect ``instances`` compiled against ``state``, in
    order. An instance that no longer validates against the show (its
    template, a target or a master is gone) is dormant and left out, and so
    is one that would do nothing. Compile warnings are not reported: the
    programmer is rebuilt on every change."""
    if not instances:
        return ()
    compiler = CueCompiler(state.show, state.compiled.slots)  # its warnings are dropped
    compiled: list[CompiledEffect] = []
    for i, instance in enumerate(instances):
        path = f"programmer.effects[{i}]"
        if any(issue.severity == "error" for issue in validate_effect(state.show, instance, path)):
            continue  # dormant
        effect = compiler.effect(instance, path)
        if effect is not None:
            compiled.append(effect)
    return tuple(compiled)


def slot_remap(old: SlotTable, new: SlotTable) -> NDArray[np.int32] | None:
    """Old slot index → new slot index (``-1`` when the slot is gone), matched
    by ``(TargetKey, AttributeId)``; ``None`` when the slot keys are the same,
    in the same order."""
    if old is new:
        return None
    old_keys, new_keys = list(old.byKey), list(new.byKey)  # both in slot order
    if old_keys == new_keys:
        return None
    remap = np.array([new.byKey.get(key, -1) for key in old_keys], dtype=np.int32)
    return _readonly(remap)


def _readonly[T: np.generic](array: NDArray[T]) -> NDArray[T]:
    array.flags.writeable = False
    return array
