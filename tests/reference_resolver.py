"""A literal, per-slot transcription of spec §7.7's absolute pass, and of §7.5's
relative pass: the resolver's test oracle.

It unpacks every source into one §7.1 ``Contribution`` per slot, sorts each
slot's contributions by ``(priority, seq)`` and composites them slot by slot
with the §7.3 and §7.4 pseudo-code, including §7.4's division by ``P``. It is
slow and simple on purpose, and shares no code with
:mod:`busk.engine.resolver`: the snap rules are re-derived from the attribute
registry here, not read from the compiled per-lane thresholds.

Phase 4 extends §7.1's contribution in two ways: its weight is per lane (the
source's scalar weight times its per-lane weight; a slot's lanes share it in
practice), and :func:`resolve_contributions` takes per-slot contributions
directly, each with its own sequence number, so tests can check how a
runtime splits its slots into sources.

Phase 5 adds the relative pass (phase-5-plan decision 13), lane by lane:
each present relative contribution, in ``(priority, seq, order)`` order,
takes ``A = max(c.weight for c in absolute contributions of the slot if
c.priority > r.priority, default 0)``, then ``v + amount·W`` or
``v · lerp(1, amount, W)`` with ``W = weight · w · (1 − A)``; ``add``
results with a clamp are clipped last.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from busk.compiler.slots import Slot, SlotTable
from busk.engine.contributions import Relative, Source


@dataclass(kw_only=True)
class Contribution:
    """§7.1: what one source offers one slot this tick."""

    slot: int
    sourceId: str
    priority: int
    seq: int
    value: NDArray[np.float64]  # every lane of the slot
    weight: NDArray[np.float64]  # per lane: the htpWeight (HTP) or ltpWeight (LTP) it gets
    intensityScale: float


def _per_lane(weights: NDArray[np.float64] | None, count: int) -> list[float]:
    """A source's per-lane weights as a list, 1 everywhere when it has none."""
    return [1.0] * count if weights is None else [float(w) for w in weights]


def contributions(slots: SlotTable, sources: Sequence[Source]) -> dict[int, list[Contribution]]:
    """Unpack each source's batched arrays into per-slot contributions."""
    owner = {
        lane: slot_.index
        for slot_ in slots.slots
        for lane in range(slot_.laneOffset, slot_.laneOffset + slot_.laneCount)
    }
    result: dict[int, list[Contribution]] = defaultdict(list)
    for source in sources:
        lanes: dict[int, tuple[float, float]] = {}  # lane → (value, effective weight)
        for position, value, w in zip(
            source.htpPos,
            source.htpValues,
            _per_lane(source.htpWeights, len(source.htpPos)),
            strict=True,
        ):
            lanes[int(slots.intensityLanes[position])] = (float(value), source.htpWeight * w)
        for lane, value, w in zip(
            source.ltpLanes,
            source.ltpValues,
            _per_lane(source.ltpWeights, len(source.ltpLanes)),
            strict=True,
        ):
            lanes[int(lane)] = (float(value), source.ltpWeight * w)
        for lane, value, w in zip(
            source.snapLanes,
            source.snapValues,
            _per_lane(source.snapWeights, len(source.snapLanes)),
            strict=True,
        ):
            lanes[int(lane)] = (float(value), source.ltpWeight * w)
        touched = sorted({owner[lane] for lane in lanes})
        for index in touched:
            slot_ = slots.slots[index]
            own = range(slot_.laneOffset, slot_.laneOffset + slot_.laneCount)
            result[index].append(
                Contribution(
                    slot=index,
                    sourceId=source.sourceId,
                    priority=source.priority,
                    seq=source.seq,
                    value=np.array([lanes[lane][0] for lane in own]),
                    weight=np.array([lanes[lane][1] for lane in own]),
                    intensityScale=source.intensityScale,
                )
            )
    return result


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def snapped(slot_: Slot, lane: int, weight: float) -> bool | None:
    """``None`` when the lane interpolates; otherwise whether ``weight`` has
    crossed the lane's snap point (§7.3; colour extras snap at the middle)."""
    definition = slot_.attribute
    if definition.fade == "snap":
        at = definition.snapAt or "start"
    elif definition.kind == "color" and lane >= 3:
        at = "middle"
    else:
        return None
    if at == "start":
        return weight > 0
    if at == "middle":
        return weight >= 0.5
    return weight >= 1


def composite_htp(cs: list[Contribution], default: float) -> float:
    """§7.4, verbatim."""
    v = default
    for _, members in itertools.groupby(cs, key=lambda c: c.priority):
        band = list(members)
        presence = max(c.weight[0] for c in band)
        if presence == 0:
            continue
        band_value = max(c.value[0] * c.intensityScale * c.weight[0] for c in band) / presence
        v = lerp(v, band_value, presence)
    return v


def composite_ltp(
    cs: list[Contribution], slot_: Slot, default: NDArray[np.float64]
) -> NDArray[np.float64]:
    """§7.3, verbatim, per lane, with snapping."""
    v = default.copy()
    for c in cs:
        for lane in range(slot_.laneCount):
            reached = snapped(slot_, lane, c.weight[lane])
            if reached is None:
                v[lane] = lerp(v[lane], c.value[lane], c.weight[lane])
            elif reached:
                v[lane] = c.value[lane]
    return v


def reference_resolve(
    slots: SlotTable,
    sources: Sequence[Source],
    base: NDArray[np.float64],
    relatives: Sequence[Relative] = (),
) -> NDArray[np.float64]:
    """§7.7's ``resolveFrame``: the absolute pass, then ``relatives``: a new frame."""
    return resolve_contributions(slots, contributions(slots, sources), base, relatives)


def resolve_contributions(
    slots: SlotTable,
    by_slot: Mapping[int, Sequence[Contribution]],
    base: NDArray[np.float64],
    relatives: Sequence[Relative] = (),
) -> NDArray[np.float64]:
    """§7.7's ``resolveFrame`` over per-slot contributions (slot index → its
    contributions, in any order), then ``relatives`` (in any order): a new
    frame."""
    frame = base.copy()
    for index, unsorted in by_slot.items():
        slot_ = slots.slots[index]
        cs = sorted(unsorted, key=lambda c: (c.priority, c.seq))
        if slot_.attribute.merge == "HTP":
            frame[slot_.laneOffset] = composite_htp(cs, float(frame[slot_.laneOffset]))
        else:
            frame[slot_.lanes] = composite_ltp(cs, slot_, frame[slot_.lanes])
    apply_relatives(slots, by_slot, relatives, frame)
    return frame


def apply_relatives(
    slots: SlotTable,
    by_slot: Mapping[int, Sequence[Contribution]],
    relatives: Sequence[Relative],
    frame: NDArray[np.float64],
) -> None:
    """§7.5 with continuous suppression, lane by lane, in place. Relatives
    with no weight contribute nothing (they are not present)."""
    owner = {
        lane: slot_
        for slot_ in slots.slots
        for lane in range(slot_.laneOffset, slot_.laneOffset + slot_.laneCount)
    }
    ordered = sorted(
        (r for r in relatives if r.weight > 0), key=lambda r: (r.priority, r.seq, r.order)
    )
    for r in ordered:
        for k, lane in enumerate(int(x) for x in r.lanes):
            slot_ = owner[lane]
            offset = lane - slot_.laneOffset
            above = [
                float(c.weight[offset])
                for c in by_slot.get(slot_.index, ())
                if c.priority > r.priority
            ]
            covered = max(above, default=0.0)
            own = 1.0 if r.weights is None else float(r.weights[k])
            w = r.weight * own * (1.0 - covered)
            amount = float(r.amounts[k])
            if r.op == "add":
                frame[lane] = frame[lane] + amount * w
            else:
                frame[lane] = frame[lane] * lerp(1.0, amount, w)
    for r in ordered:
        if r.op == "add" and r.clamp is not None:
            low, high = r.clamp
            for lane in r.lanes:
                frame[lane] = min(max(frame[lane], low), high)
