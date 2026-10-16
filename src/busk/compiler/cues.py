"""Compiled cues: value entries expanded into lanes (spec §6.3 steps 1–4).

A cue stores *intent*: "group Moving Heads, colour, preset Blue". The engine
needs flat arrays: "these lanes take these values". For every cue the
compiler

1. expands each entry's ``TargetSpec`` into its ordered targets (a group
   into its members);
2. resolves the entry's ``ValueSource`` per target: a literal as is, a
   ``perTarget`` map by target key, a preset through the scope lookup
   (target → profile → global, §5.8), a spread by the target's index;
3. drops targets that have no slot for the attribute (a colour preset on a
   dimmer-only fixture does nothing);
4. encodes the value into the slot's lanes and clamps it to the attribute's
   range (phase-2-plan decision 8);
5. keeps the last value per slot, so "all heads blue, MH 1 red" works;
6. partitions the lanes the way the resolver merges them: HTP (intensity),
   continuous LTP, and **snap lanes** that cannot be interpolated (discrete
   attributes, ``positionSpeed``, colour extras), each with its threshold;
7. builds the arrays, sorted by lane.

Steps 1–5 give a cue's *own* values (:class:`OwnCue`). Tracking (§9.3) and
per-slot timing (§9.1) work on those, list by list
(:mod:`busk.compiler.tracking`); :func:`cue_from_values` then does steps
6–7 for each tracked state.

A cue's **effects** compile next to its values, instance by instance
(:func:`busk.compiler.effects.compile_effect`): they are separate
contributors of the playback, not values of its slots (phase-5-plan
decision 7), so they are not merged into the lanes above.

Rules §6.3 leaves open (phase-2-plan decision 9)
------------------------------------------------
* **Spread** uses each member's index ``k`` in the full expanded list of
  ``n`` targets: ``u = k / (n − 1)``, and ``u = 0`` when ``n = 1``. Members
  without the attribute keep their position. The curve gives the fraction
  ``f``: ``u`` (linear), ``1 − |2u − 1|`` (center) or ``|2u − 1|`` (edges),
  and the value is ``lerp(from, to, f)`` per lane.
* A **discrete value** whose option the target does not offer (or whose
  ``wheel`` is not the target's) is dropped for that target and reported as
  a compile warning: a global "breakup" gobo on a fixture without that gobo.
* A ``perTarget`` source without a key for a target contributes nothing to
  that target; so does a preset with no value in any matching scope.

**Snapping** (decision 7). A snap lane takes the source's value once the
source's LTP weight reaches the lane's threshold: ``snapAt`` ``start``
(weight > 0), ``middle`` (≥ 0.5) or ``end`` (≥ 1). Colour extras (``w``,
``a``, ``uv``) snap at ``middle``: a ``NaN`` ("derive") lane cannot be
interpolated against an explicit value. Phase 4 stores the threshold per
lane (phase-4-plan §5.2): with per-lane presence the resolver compares
lane by lane anyway, and one snap partition keeps fades simple.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal, cast

import numpy as np
from numpy.typing import NDArray

from busk.compiler.effects import CompiledEffect, compile_effect
from busk.compiler.lanes import EncodeError, encode_value
from busk.compiler.slots import FAMILIES, Slot, SlotIndex, SlotTable
from busk.model.attributes import ATTRIBUTES, AttributeValue, ColorValue, DiscreteValue
from busk.model.common import (
    AttributeId,
    CueId,
    EffectId,
    PresetId,
    ProfileId,
    TargetKey,
    TargetRef,
    target_key,
)
from busk.model.cue import Cue, CueRelease
from busk.model.effect import EffectInstance, EffectTemplate
from busk.model.entry import FadeCurve, TargetSpec, TimingOverride, ValueSource
from busk.model.preset import Preset
from busk.model.show import Show
from busk.model.validate import Issue

SNAP_START: Final = math.ulp(0.0)
"""The ``start`` threshold, 5e-324: for a weight ``w ≥ 0``, ``w >= SNAP_START``
is exactly ``w > 0``, so every snap lane needs one comparison."""

SNAP_THRESHOLDS: Final[Mapping[str, float]] = {"start": SNAP_START, "middle": 0.5, "end": 1.0}
"""The LTP weight at which a snap lane takes the source's value (§7.3)."""

_EXTRA_SNAP_AT: Final = "middle"
"""Where colour extras snap (decision 7)."""


def _readonly[T: np.generic](array: NDArray[T]) -> NDArray[T]:
    array.flags.writeable = False
    return array


type TriggerKind = Literal["go", "follow", "wait"]
"""What moves a playback into a cue (§9.2): a manual GO, or an auto-GO."""


@dataclass(frozen=True, kw_only=True)
class SlotTiming:
    """How a slot fades into a cue: ``delay`` seconds, then ``fade`` seconds
    along ``curve`` (§5.9). The engine turns it into a fade per slot."""

    fade: float
    delay: float
    curve: FadeCurve


INSTANT: Final = SlotTiming(fade=0.0, delay=0.0, curve="linear")
"""No delay, no fade: the timing of a cue built without one."""


@dataclass(frozen=True, kw_only=True)
class TimingTable:
    """A cue's timing, per slot (phase-4-plan decision 6).

    ``timings`` are the cue's distinct :class:`SlotTiming` s. ``bySlot``
    gives each slot of the cue its ``(in, out)`` indices into them: the
    timing it fades with when its intensity rises (every non-intensity slot
    always uses ``in``) and when it falls. ``leave`` gives, per family code
    (:data:`~busk.compiler.slots.FAMILIES`), the timing of a slot that leaves
    the cue. ``inTiming`` is the cue's own ``fadeIn``, ``delayIn`` and
    ``curve``, which the engine's LTP gate fades in with; ``outTiming`` its
    ``fadeOut``, ``delayOut`` and ``curve``, which effects that leave the
    cue fade out with (phase-5-plan decision 9).
    """

    timings: tuple[SlotTiming, ...]
    bySlot: Mapping[SlotIndex, tuple[int, int]]
    leave: tuple[int, ...]
    inTiming: SlotTiming
    outTiming: SlotTiming

    @staticmethod
    def instant(slots: Iterable[SlotIndex]) -> TimingTable:
        """Every one of ``slots`` (and every slot that leaves) cuts at once."""
        return TimingTable(
            timings=(INSTANT,),
            bySlot=dict.fromkeys(slots, (0, 0)),
            leave=(0,) * len(FAMILIES),
            inTiming=INSTANT,
            outTiming=INSTANT,
        )


NO_CUE_ID: Final = CueId("")
"""The id of a cue that is not in the show (:data:`EMPTY_CUE`, test cues)."""

_NO_LANES: Final = _readonly(np.zeros(0, dtype=np.intp))
_NO_VALUES: Final = _readonly(np.zeros(0, dtype=np.float64))
_NO_TIMINGS: Final = _readonly(np.zeros(0, dtype=np.int16))


@dataclass(frozen=True, kw_only=True)
class CompiledCue:
    """One cue's tracked state as flat, read-only arrays.

    * ``htpPos`` are positions into ``SlotTable.intensityLanes`` (the
      resolver merges intensity in a dense array over those lanes), with
      ``htpValues`` the cue's intensities;
    * ``ltpLanes`` / ``ltpValues`` are the continuous LTP lanes of the
      logical frame, interpolated by weight;
    * ``snapLanes`` / ``snapValues`` are the lanes that snap, each with its
      threshold in ``snapThresholds`` (one of :data:`SNAP_THRESHOLDS`).

    The arrays hold what a playback holds *at* this cue: its own values
    and, in a tracking list, the values it tracks from the cues before it
    (:mod:`busk.compiler.tracking`). Lanes are unique within a cue, so
    fancy-index updates never see duplicate indices. ``targets`` are the
    targets of that state: the cue's own entry targets in entry order, the
    tracked ones, then the ones its effects drive (the ``select`` button).

    **Timing** (phase-4-plan §5.2, decision 6). ``timings`` holds the
    distinct :class:`SlotTiming` s of the cue; per lane, an index into it
    says how that lane fades into the cue: ``htpIn`` when its intensity
    rises, ``htpOut`` when it falls, ``ltpTiming`` and ``snapTiming`` for
    the other lanes. ``leave`` holds, per family code, the timing of a lane
    that leaves the cue. ``inTiming`` and ``outTiming`` are the cue's own in
    and out timing (effects enter and change with the first and leave with
    the second, phase-5-plan decision 9).

    ``effects`` are the effect instances the playback runs at this cue, in
    cue order; each is a separate contributor of the playback
    (phase-5-plan §5.3).

    ``trigger`` and ``triggerDelay`` say what moves a playback *into* this
    cue: a manual GO, or an auto-GO ``triggerDelay`` seconds after the
    previous transition starts (``wait``) or completes (``follow``).
    """

    id: CueId
    number: str
    name: str
    htpPos: NDArray[np.intp]
    htpValues: NDArray[np.float64]
    ltpLanes: NDArray[np.intp]
    ltpValues: NDArray[np.float64]
    snapLanes: NDArray[np.intp]
    snapValues: NDArray[np.float64]
    snapThresholds: NDArray[np.float64]
    inTiming: SlotTiming
    outTiming: SlotTiming
    timings: tuple[SlotTiming, ...]
    htpIn: NDArray[np.int16]  # per HTP position: its timing when rising
    htpOut: NDArray[np.int16]  # per HTP position: its timing when falling
    ltpTiming: NDArray[np.int16]  # per LTP lane
    snapTiming: NDArray[np.int16]  # per snap lane
    leave: NDArray[np.int16]  # per family code: the timing of a slot that leaves
    trigger: TriggerKind
    triggerDelay: float
    targets: tuple[TargetRef, ...]
    effects: tuple[CompiledEffect, ...]


EMPTY_CUE: Final = CompiledCue(
    id=NO_CUE_ID,
    number="",
    name="",
    htpPos=_NO_LANES,
    htpValues=_NO_VALUES,
    ltpLanes=_NO_LANES,
    ltpValues=_NO_VALUES,
    snapLanes=_NO_LANES,
    snapValues=_NO_VALUES,
    snapThresholds=_NO_VALUES,
    inTiming=INSTANT,
    outTiming=INSTANT,
    timings=(INSTANT,),
    htpIn=_NO_TIMINGS,
    htpOut=_NO_TIMINGS,
    ltpTiming=_NO_TIMINGS,
    snapTiming=_NO_TIMINGS,
    leave=_readonly(np.zeros(len(FAMILIES), dtype=np.int16)),
    trigger="go",
    triggerDelay=0.0,
    targets=(),
    effects=(),
)
"""What a playback with an empty cue list plays: nothing, instantly."""


@dataclass(frozen=True, kw_only=True)
class OwnCue:
    """A cue's *own* values (steps 1–5), before tracking.

    ``values`` are the encoded, clamped lanes per slot, the last entry
    winning. ``overrides`` holds the ``timing`` of the entry that set a slot
    last, for the slots where that entry has one. ``targets`` are every
    target the entries expand to, in entry order, deduplicated.
    ``released`` are the slots the cue's ``releases`` name. ``effects`` are
    the cue's compiled effect instances by ``id``, in cue order, without the
    ones that do nothing.
    """

    values: Mapping[SlotIndex, tuple[float, ...]]
    overrides: Mapping[SlotIndex, TimingOverride]
    targets: tuple[TargetRef, ...]
    released: frozenset[SlotIndex]
    effects: Mapping[str, CompiledEffect]


@dataclass(kw_only=True)
class _ScopedValues:
    """One preset's values for one attribute, by scope (§5.8)."""

    byTarget: dict[TargetKey, AttributeValue] = field(default_factory=dict)
    byProfile: dict[ProfileId, AttributeValue] = field(default_factory=dict)
    globalValue: AttributeValue | None = None


def _index_presets(
    presets: Sequence[Preset],
) -> dict[PresetId, dict[AttributeId, _ScopedValues]]:
    """``preset → attribute → values by scope``, built once per show. With
    duplicates (a validation error) the first value wins."""
    index: dict[PresetId, dict[AttributeId, _ScopedValues]] = {}
    for preset in presets:
        attributes = index.setdefault(preset["id"], {})
        for value in preset["values"]:
            scoped = attributes.setdefault(value["attribute"], _ScopedValues())
            scope = value["scope"]
            if scope["kind"] == "target":
                scoped.byTarget.setdefault(target_key(scope["target"]), value["value"])
            elif scope["kind"] == "profile":
                scoped.byProfile.setdefault(scope["profileId"], value["value"])
            elif scoped.globalValue is None:
                scoped.globalValue = value["value"]
    return index


def spread_value(start: AttributeValue, end: AttributeValue, fraction: float) -> AttributeValue:
    """A spread's value at ``fraction`` of the way from ``start`` to ``end``, as
    an attribute value (Phase 3: the programmer and cue merges flatten spreads).

    It encodes to exactly the lanes :meth:`CueCompiler.resolve` computes for the
    same spread: scalars and colour components use the same ``a + (b − a)·f``,
    and a colour extra is kept only when both ends have it (otherwise the
    compiler's lane is ``NaN``, "derive", which is what leaving it out means).
    Discrete values cannot be spread (validation rejects them).
    """
    if isinstance(start, int | float) and isinstance(end, int | float):
        return start + (end - start) * fraction
    first, last = cast(ColorValue, start), cast(ColorValue, end)
    color: dict[str, float] = {}
    for component in ("r", "g", "b", "w", "a", "uv"):
        if component in first and component in last:
            a, b = first[component], last[component]
            color[component] = a + (b - a) * fraction
    return cast(ColorValue, color)


def spread_fraction(curve: str, k: int, n: int) -> float:
    """The fraction ``f`` of the way from ``from`` to ``to`` for member ``k`` of
    ``n`` (decision 9): ``u = k / (n − 1)`` (0 when ``n = 1``), then ``u``
    (linear), ``1 − |2u − 1|`` (center) or ``|2u − 1|`` (edges)."""
    u = k / (n - 1) if n > 1 else 0.0
    if curve == "center":
        return 1.0 - abs(2.0 * u - 1.0)
    if curve == "edges":
        return abs(2.0 * u - 1.0)
    return u


def cue_from_values(
    slots: SlotTable,
    values: Mapping[SlotIndex, Sequence[float]],
    *,
    id: CueId = NO_CUE_ID,
    number: str = "",
    name: str = "",
    timing: TimingTable | None = None,
    trigger: TriggerKind = "go",
    triggerDelay: float = 0.0,
    targets: tuple[TargetRef, ...] = (),
    effects: tuple[CompiledEffect, ...] = (),
) -> CompiledCue:
    """Steps 6–7: a :class:`CompiledCue` from encoded, clamped lanes per slot.

    The lanes are split the way the resolver merges them: HTP slots by their
    position in ``slots.intensityLanes``, snapping lanes with their
    thresholds, every other lane into the continuous LTP arrays; each set
    sorted by lane. Each slot must have all its lanes. Every lane takes its
    slot's timing from ``timing``, which must cover every slot of
    ``values``; without one, every lane cuts at once. ``effects`` are
    passed through.
    """
    if timing is None:
        timing = TimingTable.instant(values)
    # Rows: (index, value, in timing[, out timing]); snap rows end with a threshold.
    htp: list[tuple[float, ...]] = []
    ltp: list[tuple[float, ...]] = []
    snap: list[tuple[float, ...]] = []
    for index, lanes in values.items():
        slot = slots.slots[index]
        definition = slot.attribute
        timing_in, timing_out = timing.bySlot[index]
        if definition.merge == "HTP":
            position = int(np.searchsorted(slots.intensityLanes, slot.laneOffset))
            htp.append((position, lanes[0], timing_in, timing_out))
            continue
        for j, value in enumerate(lanes):
            lane = slot.laneOffset + j
            if definition.fade == "snap":
                snap_at = definition.snapAt or "start"
            elif definition.kind == "color" and j >= 3:
                snap_at = _EXTRA_SNAP_AT
            else:
                ltp.append((lane, value, timing_in))
                continue
            snap.append((lane, value, timing_in, SNAP_THRESHOLDS[snap_at]))
    htp_pos, htp_values, htp_in, htp_out = _columns(htp, np.intp, np.float64, np.int16, np.int16)
    ltp_lanes, ltp_values, ltp_timing = _columns(ltp, np.intp, np.float64, np.int16)
    snap_lanes, snap_values, snap_timing, snap_thresholds = _columns(
        snap, np.intp, np.float64, np.int16, np.float64
    )
    return CompiledCue(
        id=id,
        number=number,
        name=name,
        htpPos=htp_pos,
        htpValues=htp_values,
        ltpLanes=ltp_lanes,
        ltpValues=ltp_values,
        snapLanes=snap_lanes,
        snapValues=snap_values,
        snapThresholds=snap_thresholds,
        inTiming=timing.inTiming,
        outTiming=timing.outTiming,
        timings=timing.timings,
        htpIn=htp_in,
        htpOut=htp_out,
        ltpTiming=ltp_timing,
        snapTiming=snap_timing,
        leave=_readonly(np.array(timing.leave, dtype=np.int16)),
        trigger=trigger,
        triggerDelay=triggerDelay,
        targets=targets,
        effects=effects,
    )


def _columns(rows: list[tuple[float, ...]], *dtypes: type[np.generic]) -> tuple[NDArray[Any], ...]:
    """Rows sorted by their first item (unique within a cue), as read-only
    column arrays of ``dtypes``."""
    rows.sort(key=lambda row: row[0])
    columns: list[tuple[float, ...]] = list(zip(*rows, strict=True)) if rows else [()] * len(dtypes)
    return tuple(
        _readonly(np.array(column, dtype=dtype))
        for column, dtype in zip(columns, dtypes, strict=True)
    )


class CueCompiler:
    """Resolves the cues of one show against its slot table (steps 1–5).

    Lookup tables (groups, fixture profiles, the preset index) are built
    once. Every dropped discrete value is appended to
    :attr:`warnings` as a compile warning with the entry's path.
    :func:`busk.compiler.tracking.compile_cue_states` turns a list's
    :meth:`own` values into compiled cues.

    :attr:`readGroups`, :attr:`readPresets` and :attr:`readTemplates`
    collect the ids of the groups, presets and effect templates the compiled
    entries, releases and effects referenced, so a later recompile can tell
    whether a compiled cue list is still valid (Phase 3, §6.4).
    """

    def __init__(self, show: Show, slots: SlotTable) -> None:
        self._slots = slots
        self._groups = {group["id"]: group["members"] for group in show["groups"]}
        self._profiles = {fixture["id"]: fixture["profileId"] for fixture in show["fixtures"]}
        self._presets = _index_presets(show["presets"])
        self._templates = {template["id"]: template for template in show["effects"]}
        self.warnings: list[Issue] = []
        self.readGroups: set[str] = set()
        self.readPresets: set[str] = set()
        self.readTemplates: set[str] = set()

    @property
    def slots(self) -> SlotTable:
        """The slot table the cues compile against."""
        return self._slots

    def own(self, cue: Cue, path: str) -> OwnCue:
        """Steps 1–5 for ``cue``, found at ``path`` (``cueLists[i].cues[c]``)
        in the show: its own values, their timing overrides, its targets, the
        slots it releases and its compiled effects."""
        values: dict[SlotIndex, tuple[float, ...]] = {}
        overrides: dict[SlotIndex, TimingOverride] = {}
        targets: dict[TargetKey, TargetRef] = {}
        for e, entry in enumerate(cue["entries"]):
            self._read(entry["targets"])
            if entry["value"]["kind"] == "preset":
                self.readPresets.add(entry["value"]["presetId"])
            members = self.expand(entry["targets"])
            for k, target in enumerate(members):
                targets.setdefault(target_key(target), target)
                slot = self._slots.find(target, entry["attribute"])
                if slot is None:
                    continue  # step 3: the target does not have the attribute
                try:
                    lanes = self.resolve(entry["value"], slot, k, len(members))
                except EncodeError as exc:
                    self.warnings.append(
                        Issue(
                            "warning",
                            f"{path}.entries[{e}].value",
                            f"{exc}; dropped for that target",
                        )
                    )
                    continue
                if lanes is None:
                    continue
                values[slot.index] = clamp_lanes(slot, lanes)  # a later entry wins …
                if "timing" in entry:
                    overrides[slot.index] = entry["timing"]
                else:
                    overrides.pop(slot.index, None)  # … with its timing, or none
        effects: dict[str, CompiledEffect] = {}
        for i, instance in enumerate(cue["effects"]):
            compiled = self.effect(instance, f"{path}.effects[{i}]")
            if compiled is not None:
                effects[instance["id"]] = compiled
        return OwnCue(
            values=values,
            overrides=overrides,
            targets=tuple(targets.values()),
            released=self.released(cue.get("releases", ())),
            effects=effects,
        )

    def effect(self, instance: EffectInstance, path: str) -> CompiledEffect | None:
        """The compiled form of effect ``instance``, found at ``path`` in the
        show; ``None`` (with a compile warning) when it would do nothing."""
        return compile_effect(self, instance, path)

    def template(self, template: EffectId) -> EffectTemplate:
        """Effect template ``template``, noted in :attr:`readTemplates`."""
        self.readTemplates.add(template)
        return self._templates[template]

    def targets(self, spec: TargetSpec) -> Sequence[TargetRef]:
        """:meth:`expand`, noting the group ``spec`` reads in :attr:`readGroups`."""
        self._read(spec)
        return self.expand(spec)

    def released(self, releases: Iterable[CueRelease]) -> frozenset[SlotIndex]:
        """The slots ``releases`` name: each release's targets, then its
        attributes, or every attribute a target has a slot for (``"all"``).
        Targets without a named attribute are skipped."""
        released: set[SlotIndex] = set()
        for release in releases:
            self._read(release["targets"])
            attributes = release["attributes"]
            names = list(ATTRIBUTES) if attributes == "all" else attributes
            for target in self.expand(release["targets"]):
                for attribute in names:
                    slot = self._slots.find(target, attribute)
                    if slot is not None:
                        released.add(slot.index)
        return frozenset(released)

    def _read(self, spec: TargetSpec) -> None:
        """Note the group ``spec`` reads, if any (:attr:`readGroups`)."""
        if spec["kind"] == "group":
            self.readGroups.add(spec["groupId"])

    def expand(self, spec: TargetSpec) -> Sequence[TargetRef]:
        """Step 1: a target spec's ordered targets (a group follows its members)."""
        if spec["kind"] == "group":
            return self._groups[spec["groupId"]]
        return spec["refs"]

    def resolve(self, source: ValueSource, slot: Slot, k: int, n: int) -> tuple[float, ...] | None:
        """Step 2: the lanes ``source`` gives ``slot``'s target, member ``k`` of
        ``n``; ``None`` when the source has no value for that target.

        Raises :class:`~busk.compiler.lanes.EncodeError` for a discrete value
        the target does not offer.
        """
        if source["kind"] == "literal":
            return _encode(slot, source["value"])
        if source["kind"] == "perTarget":
            value = source["values"].get(target_key(slot.target))
            return None if value is None else _encode(slot, value)
        if source["kind"] == "preset":
            value = self.preset_value(source["presetId"], slot)
            return None if value is None else _encode(slot, value)
        f = spread_fraction(source.get("curve", "linear"), k, n)
        start, end = _encode(slot, source["from"]), _encode(slot, source["to"])
        return tuple(a + (b - a) * f for a, b in zip(start, end, strict=True))

    def preset_value(self, preset: PresetId, slot: Slot) -> AttributeValue | None:
        """The §5.8 scope lookup: target scope, then profile, then global."""
        scoped = self._presets.get(preset, {}).get(slot.attribute.id)
        if scoped is None:
            return None
        value = scoped.byTarget.get(target_key(slot.target))
        if value is None:
            value = scoped.byProfile.get(self._profiles[slot.target["fixtureId"]])
        return scoped.globalValue if value is None else value


def _encode(slot: Slot, value: AttributeValue) -> tuple[float, ...]:
    """:func:`~busk.compiler.lanes.encode_value`, plus the check of a discrete
    value's optional ``wheel`` against the target's wheels."""
    if slot.attribute.kind == "discrete":
        wheel = cast(DiscreteValue, value).get("wheel")
        if wheel is not None and wheel not in slot.wheels:
            offered = ", ".join(repr(w) for w in slot.wheels) or "none"
            raise EncodeError(
                f"{target_key(slot.target)} has no {slot.attribute.id!r} on wheel {wheel!r} "
                f"(its wheels: {offered})"
            )
    return encode_value(slot, value)


def clamp_lanes(slot: Slot, lanes: tuple[float, ...]) -> tuple[float, ...]:
    """Clamp at compile time, not every tick (decision 8): normalised scalars and
    every colour lane to ``0..1`` (``NaN`` extras stay ``NaN``). Degrees and Hz
    are left to conversion, which clamps them into the fixture's ranges."""
    definition = slot.attribute
    if definition.kind == "color":
        return tuple(lane if math.isnan(lane) else min(max(lane, 0.0), 1.0) for lane in lanes)
    if definition.kind == "scalar" and definition.range is not None:
        low, high = definition.range.min, definition.range.max
        return (min(max(lanes[0], low), high),)
    return lanes
