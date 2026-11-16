"""A cue list's tracked states as a display reads them (GAP-46 of
``docs/dev/tui/engine-gaps.md``).

``OfflineShow.tracking(L)`` and ``LiveShow.tracking(L)`` return a
:class:`TrackedCue` per cue of list ``L``, in list order: what each cue puts
on stage when the list is played by GO from its first cue, and where each
value comes from. It is read from the compiled show, not from the engine
(the pending plan's §5, call 22), so other playbacks, the masters, park and
the programmer change nothing in it.

A tracking list stores each cue's changes, and :mod:`busk.compiler.tracking`
works out each cue's state from them::

    state[0] = own[0]
    state[n] = own[n]                                if not tracking or cue n is a block
             = (state[n-1] − released(n)) | own[n]   otherwise

The compiler does that on lanes, which name no preset. This read runs the
same rule on show data, as :func:`busk.commands.record.inherited` does, so a
preset stays a preset, and it keeps, for each value, the cue that stores it.
Each entry is flattened to one source per slot by
:func:`~busk.session.programmer.entry_sources`: a literal, a ``perTarget``
value and a spread give each target its literal, and a preset stays a
reference. A value the compiler drops (no slot, no value for the target, a
discrete option the target does not offer) is not listed. The effects are
the compiled cue's own, which already carry the cue that stores them.

**A chase** tracks as a sequence does, in list order, whatever its
direction: the compiler works out the states once, and the engine plays
them in the chase's order.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, cast

from busk.commands.patch import deep_copy
from busk.compiler.effects import CompiledEffect
from busk.compiler.slots import SlotIndex, SlotTable
from busk.model.attributes import ATTRIBUTES, AttributeValue
from busk.model.common import AttributeId, TargetRef
from busk.model.cue import CueList
from busk.model.preset import PresetPool
from busk.session.programmer import (
    ProgSource,
    SlotKey,
    entry_sources,
    released_slots,
    split_slot_key,
)
from busk.session.state import ShowState

_ORDER: Final = {attribute: index for index, attribute in enumerate(ATTRIBUTES)}
"""The registry's order of the attributes, which the read lists them in."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TrackedValue:
    """One value of a cue's tracked state: what it gives one attribute of one
    fixture element (GAP-46 of ``docs/dev/tui/engine-gaps.md``).

    ``number``, ``element``, ``attribute``, ``value`` and ``preset`` are as
    in :class:`~busk.session.status.ProgrammerValue`: the fixture's number,
    the element counted from 1, the value in the show's units (for a preset,
    the value the preset gives this element) and the preset's ``(pool,
    number, name)``, or ``None`` for a value set directly. ``trackedFrom`` is
    the number of the cue that stores the value, ``None`` when this cue
    stores it.
    """

    number: int
    element: int
    attribute: AttributeId
    value: AttributeValue
    preset: tuple[PresetPool, int, str] | None
    trackedFrom: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class TrackedEffect:
    """One effect instance of a cue's tracked state (GAP-46).

    ``id`` is the instance's id, and ``trackedFrom`` the number of the cue
    whose ``effects`` hold it, ``None`` when this cue holds it: with them a
    display finds the instance, its template, targets and settings in the
    show's cue list, as with an
    :class:`~busk.engine.snapshot.EffectStatus`. A cue's releases take
    their slots out of the instances it tracks; one left with nothing to
    drive is not listed.
    """

    id: str
    trackedFrom: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class TrackedCue:
    """One cue of a list, as it plays when the list is played by GO from its
    first cue (GAP-46).

    ``number``, ``name`` and ``block`` are the cue's: a block cue tracks
    nothing from the cues before it. ``values`` are what the cue puts on
    stage, the values it stores and those it tracks, by fixture number,
    element and attribute (in the registry's order). ``released`` are the
    ``(number, element, attribute)`` slots it takes away: those its
    ``releases`` name that the cue before it held, as a value or through an
    effect instance it tracks, and that it does not set again itself (its
    own values win over its own releases; an instance it holds itself takes
    the place of a tracked one with its id, which is then not trimmed).
    ``effects`` are the effect instances it runs, the tracked ones first, as
    the engine runs them.

    In a list without tracking, every value and effect is the cue's own, and
    nothing is released; the same goes for the first cue and a block cue.
    """

    number: str
    name: str
    block: bool
    values: tuple[TrackedValue, ...]
    released: tuple[tuple[int, int, AttributeId], ...]
    effects: tuple[TrackedEffect, ...]


def tracked_cues(state: ShowState, cue_list: CueList) -> tuple[TrackedCue, ...]:
    """Every cue of ``cue_list``, a list of ``state``'s show, with its
    tracked state (see the module docs)."""
    slots = state.compiled.slots
    compiled = state.compiled.cueLists[cue_list["id"]].cues
    numbers = {fixture["id"]: fixture["number"] for fixture in state.show["fixtures"]}
    presets = {preset["id"]: preset for preset in state.show["presets"]}

    def element(target: TargetRef) -> tuple[int, int]:
        return numbers[target["fixtureId"]], target["element"] + 1

    def value(key: SlotKey, source: ProgSource, since: str | None) -> TrackedValue:
        split = split_slot_key(key)
        assert split is not None  # entry_sources made it
        target, attribute = split
        named: tuple[PresetPool, int, str] | None = None
        if source["kind"] == "preset":
            slot = slots.find(target, attribute)
            assert slot is not None  # entry_sources keeps only slots the target has
            preset = presets[source["presetId"]]
            found = state.values.preset_value(preset["id"], slot)
            assert found is not None  # nor a preset with no value for it
            given, named = found, (preset["pool"], preset["number"], preset["name"])
        else:
            given = source["value"]
        return TrackedValue(
            number=numbers[target["fixtureId"]],
            element=target["element"] + 1,
            attribute=attribute,
            value=cast(AttributeValue, deep_copy(given)),
            preset=named,
            trackedFrom=since,
        )

    cues: list[TrackedCue] = []
    held: dict[SlotKey, tuple[ProgSource, str]] = {}  # the state before: source, the cue storing it
    for n, (cue, made) in enumerate(zip(cue_list["cues"], compiled, strict=True)):
        number = cue["number"]
        own = {
            key: (source, number) for key, source in entry_sources(state, cue["entries"]).items()
        }
        released: list[tuple[int, int, AttributeId]] = []
        block = cue.get("block", False)
        if n > 0 and cue_list["tracking"] and not block:
            gone = released_slots(state, cue.get("releases", ()))
            mine = {effect.key for effect in made.effects if effect.cue == number}
            trimmed = _driven((e for e in compiled[n - 1].effects if e.key not in mine), slots)
            released = [
                (*element(slot.target), slot.attribute.id)
                for key, slot in gone.items()
                if (key in held or slot.index in trimmed) and key not in own
            ]
            own = {key: held[key] for key in held if key not in gone} | own
        held = own
        values = [
            value(key, source, None if since == number else since)
            for key, (source, since) in held.items()
        ]
        values.sort(key=lambda v: (v.number, v.element, _ORDER[v.attribute]))
        released.sort(key=lambda r: (r[0], r[1], _ORDER[r[2]]))
        cues.append(
            TrackedCue(
                number=number,
                name=cue["name"],
                block=block,
                values=tuple(values),
                released=tuple(released),
                effects=tuple(
                    TrackedEffect(id=e.key, trackedFrom=None if e.cue == number else e.cue)
                    for e in made.effects
                ),
            )
        )
    return tuple(cues)


def _driven(effects: Iterable[CompiledEffect], table: SlotTable) -> set[SlotIndex]:
    """The slots compiled ``effects`` write to."""
    found: set[SlotIndex] = set()
    for effect in effects:
        for layer in effect.layers:
            found.update(table.laneSlot[layer.frame_lanes(table)].tolist())
    return found
