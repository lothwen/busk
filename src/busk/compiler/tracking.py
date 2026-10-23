"""Tracked states and per-slot timing of a cue list (spec §9.1, §9.3).

A playback at cue *n* of a list holds the cue's **tracked state**. The
compiler precomputes every state, so a GOTO lands on exactly what stepping
through the list would give (phase-4-plan §5.2). It works on each cue's
:class:`~busk.compiler.cues.OwnCue`, its own values per slot, never on show
data::

    state[0] = own[0]
    state[n] = own[n]                                if not tracking or cue n is a block
             = (state[n-1] − released(n)) | own[n]   otherwise

A cue's own values win over its own ``releases``. That deviates from §9.3,
whose ``without`` runs after the merge and would release a value the cue
itself sets (phase-4-plan §9).

Effects track the same way, instance by instance, by ``id``
(phase-5-plan decision 8)::

    effects[0] = own[0].effects
    effects[n] = own[n].effects                         if not tracking or cue n is a block
               = trim(effects[n-1], released(n))
                 | own[n].effects                       otherwise

``trim`` takes the released slots out of every tracked instance
(:meth:`~busk.compiler.effects.CompiledEffect.without`) and drops the ones
left without lanes; an untouched instance stays the same object. ``|``
merges by ``id``: the cue's own instance replaces a tracked one in its
place, and new ones are appended. So a cue's own effects are never trimmed
by its own releases, as its own values are not.

Per-slot timing (decision 6)
----------------------------
Every slot of a state fades into the cue with timing from, in order:

1. the ``timing`` of the cue's own entry that set the slot, field by field
   (an entry's ``fade`` covers both rising and falling intensity);
2. ``perFamily[family]`` of the cue, if it has the slot's family;
3. the cue's ``fadeIn``/``delayIn``, or ``fadeOut``/``delayOut`` for an
   intensity that falls.

The curve comes from the entry, then the family, then the cue. Tracked-in
slots have no entry in the cue, so they take steps 2–3: timing always comes
from the destination cue. A slot that *leaves* the cue (held before, not in
the state) fades out with the family timing, else ``fadeOut`` for intensity
and ``fadeIn`` for every other family.

Equal timings are interned per cue, so ``CompiledCue.timings`` stays small.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from busk.compiler.cues import (
    CompiledCue,
    CueCompiler,
    OwnCue,
    SlotTiming,
    TimingTable,
    cue_from_values,
)
from busk.compiler.effects import CompiledEffect
from busk.compiler.readout import ReadoutLayout, cue_color
from busk.compiler.slots import FAMILIES, SlotIndex, SlotTable
from busk.model.attributes import AttributeFamily
from busk.model.common import TargetKey, TargetRef, target_key
from busk.model.cue import CueList, CueTiming, FamilyTiming
from busk.model.entry import FadeCurve, TimingOverride


@dataclass(frozen=True, kw_only=True)
class TrackedState:
    """What a playback holds at one cue: lanes per slot, their targets, and
    the effect instances it runs.

    ``targets`` are the cue's own targets in entry order, then the targets
    of the previous state that still have a slot here, in that state's order.
    ``effects`` are the instances by ``id``, tracked ones first in their
    order, with the cue's own ones in place of tracked ones of the same
    ``id`` and after them.
    """

    values: Mapping[SlotIndex, tuple[float, ...]]
    targets: tuple[TargetRef, ...]
    effects: Mapping[str, CompiledEffect]


def track(
    slots: SlotTable, own: Sequence[OwnCue], blocks: Sequence[bool], tracking: bool
) -> list[TrackedState]:
    """The tracked state of every cue of a list (see the module docs).

    ``own`` are the cues' own values in list order and ``blocks`` their
    ``block`` flags. Without ``tracking``, each state is the cue's own values.
    """
    states: list[TrackedState] = []
    for n, (cue, block) in enumerate(zip(own, blocks, strict=True)):
        if n == 0 or not tracking or block:
            states.append(TrackedState(values=cue.values, targets=cue.targets, effects=cue.effects))
            continue
        previous = states[-1]
        values = {
            index: lanes
            for index, lanes in previous.values.items()
            if index not in cue.released and index not in cue.values
        }
        held = {target_key(slots.slots[index].target) for index in values}
        values.update(cue.values)
        targets: dict[TargetKey, TargetRef] = {target_key(t): t for t in cue.targets}
        for target in previous.targets:
            key = target_key(target)
            if key in held:
                targets.setdefault(key, target)
        states.append(
            TrackedState(
                values=values,
                targets=tuple(targets.values()),
                effects=_track_effects(slots, previous.effects, cue),
            )
        )
    return states


def _track_effects(
    slots: SlotTable, previous: Mapping[str, CompiledEffect], cue: OwnCue
) -> dict[str, CompiledEffect]:
    """``trim(previous, cue.released) | cue.effects`` (see the module docs):
    an own instance takes the place of a tracked one with its ``id``, even
    one the releases would have trimmed away."""
    effects: dict[str, CompiledEffect] = {}
    for key, effect in previous.items():
        mine = cue.effects.get(key)
        if mine is not None:
            effects[key] = mine
            continue
        trimmed = effect.without(cue.released, slots)
        if trimmed is not None:
            effects[key] = trimmed
    for key, effect in cue.effects.items():
        effects.setdefault(key, effect)
    return effects


def _with_effect_targets(
    targets: tuple[TargetRef, ...], effects: Mapping[str, CompiledEffect]
) -> tuple[TargetRef, ...]:
    """``targets``, then the targets the ``effects`` drive that are not among
    them yet, in instance order (what ``SELECT_PLAYBACK`` selects)."""
    seen: dict[TargetKey, TargetRef] = {target_key(t): t for t in targets}
    for effect in effects.values():
        for target in effect.driven:
            seen.setdefault(target_key(target), target)
    return tuple(seen.values())


def _curve_key(curve: FadeCurve) -> object:
    """A hashable stand-in for ``curve``: Bézier curves are dicts."""
    return curve if isinstance(curve, str) else tuple(curve["bezier"])


class _Interner:
    """Hands out one index per distinct :class:`SlotTiming`, in first-use order."""

    def __init__(self) -> None:
        self.timings: list[SlotTiming] = []
        self._index: dict[tuple[float, float, object], int] = {}

    def __call__(self, fade: float, delay: float, curve: FadeCurve) -> int:
        key = (fade, delay, _curve_key(curve))
        index = self._index.get(key)
        if index is None:
            index = self._index[key] = len(self.timings)
            self.timings.append(SlotTiming(fade=fade, delay=delay, curve=curve))
        return index


class _CueTimer:
    """Decision 6 for one cue: the ``(in, out)`` timing indices of its slots."""

    def __init__(self, timing: CueTiming) -> None:
        self.timing = timing
        self.perFamily: Mapping[AttributeFamily, FamilyTiming] = timing.get("perFamily", {})
        self.intern = _Interner()
        self._defaults: dict[AttributeFamily, tuple[int, int]] = {}

    def defaults(self, family: AttributeFamily) -> tuple[float, float, float, float, FadeCurve]:
        """Steps 2–3: ``(fade in, delay in, fade out, delay out, curve)`` of a
        slot of ``family`` without an entry override."""
        timing = self.timing
        own = self.perFamily.get(family)
        if own is not None:
            curve = own.get("curve", timing["curve"])
            return own["fade"], own["delay"], own["fade"], own["delay"], curve
        if family == "intensity":
            return (
                timing["fadeIn"],
                timing["delayIn"],
                timing["fadeOut"],
                timing["delayOut"],
                timing["curve"],
            )
        fade, delay = timing["fadeIn"], timing["delayIn"]
        return fade, delay, fade, delay, timing["curve"]

    def slot(self, family: AttributeFamily, override: TimingOverride | None) -> tuple[int, int]:
        """The ``(in, out)`` indices of a slot of ``family``, set by an entry
        with ``override`` (or not set by one: ``None``)."""
        if override is None:
            known = self._defaults.get(family)
            if known is None:
                known = self._defaults[family] = self.slot(family, {})
            return known
        fade_in, delay_in, fade_out, delay_out, curve = self.defaults(family)
        fade_in, fade_out = override.get("fade", fade_in), override.get("fade", fade_out)
        delay_in, delay_out = override.get("delay", delay_in), override.get("delay", delay_out)
        curve = override.get("curve", curve)
        return self.intern(fade_in, delay_in, curve), self.intern(fade_out, delay_out, curve)

    def leave(self) -> tuple[int, ...]:
        """Per family code: the timing of a slot that leaves (it falls, so an
        intensity takes the out timing)."""
        return tuple(self.slot(family, None)[1] for family in FAMILIES)


def timing_table(
    slots: SlotTable,
    timing: CueTiming,
    values: Mapping[SlotIndex, object],
    overrides: Mapping[SlotIndex, TimingOverride],
) -> TimingTable:
    """The timing of every slot of ``values`` in a cue with ``timing``, with
    the cue's own entry ``overrides`` (decision 6, see the module docs)."""
    timer = _CueTimer(timing)
    leave = timer.leave()
    by_slot = {
        index: timer.slot(slots.slots[index].attribute.family, overrides.get(index))
        for index in values
    }
    return TimingTable(
        timings=tuple(timer.intern.timings),
        bySlot=by_slot,
        leave=leave,
        inTiming=SlotTiming(fade=timing["fadeIn"], delay=timing["delayIn"], curve=timing["curve"]),
        outTiming=SlotTiming(
            fade=timing["fadeOut"], delay=timing["delayOut"], curve=timing["curve"]
        ),
    )


def compile_cue_states(
    compiler: CueCompiler, cue_list: CueList, path: str, readout: ReadoutLayout
) -> tuple[CompiledCue, ...]:
    """Every cue of ``cue_list`` (found at ``path``, ``cueLists[i]``, in the
    show) compiled to its tracked state, values and effects, with per-slot
    timing. A cue's targets are its state's value targets, then the targets
    its effects drive. Its colour is read from it with the rig's ``readout``
    (:func:`~busk.compiler.readout.cue_color`)."""
    cues = cue_list["cues"]
    own = [compiler.own(cue, f"{path}.cues[{c}]") for c, cue in enumerate(cues)]
    blocks = [cue.get("block", False) for cue in cues]
    states = track(compiler.slots, own, blocks, cue_list["tracking"])
    compiled: list[CompiledCue] = []
    for cue, mine, state in zip(cues, own, states, strict=True):
        trigger = cue["trigger"]
        delay = 0.0 if trigger["kind"] == "go" else trigger["delay"]
        made = cue_from_values(
            compiler.slots,
            state.values,
            id=cue["id"],
            number=cue["number"],
            name=cue["name"],
            timing=timing_table(compiler.slots, cue["timing"], state.values, mine.overrides),
            trigger=trigger["kind"],
            triggerDelay=delay,
            targets=_with_effect_targets(state.targets, state.effects),
            effects=tuple(state.effects.values()),
        )
        compiled.append(replace(made, color=cue_color(readout, compiler.slots, made)))
    return tuple(compiled)
