"""Hypothesis strategies and builders shared by the resolver's property tests
(``test_resolver_properties.py``) and the sequence-run tests (``test_seq_runs.py``).

They work on one rig with every kind of lane (:data:`COMPILED`). A
:class:`Drawn` contributor is random input in its plainest form: per slot, a
sequence number, the lanes and a weight. The tests turn it into what the
engine hands the resolver (sources) and into what the oracle reads (per-slot
§7.1 contributions), and compare the two frames.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
from hypothesis import strategies as st
from numpy.typing import NDArray

from builders import compile_doc, lane_kinds_rig
from busk.compiler.compile import CompiledShow
from busk.compiler.cues import cue_from_values
from busk.compiler.slots import Slot
from busk.engine.contributions import SORT_KEY, Relative, Source, gather_relatives
from busk.engine.resolver import Resolver
from reference_resolver import Contribution

COMPILED: CompiledShow = compile_doc(lane_kinds_rig(fixtures=3, pars=2))
"""Three fixtures with every lane kind, and two virtually dimmed pars."""

SLOTS = COMPILED.slots.slots
UNIT = st.floats(0, 1)
WEIGHT = st.one_of(st.sampled_from([0.0, 0.25, 0.5, 1.0]), UNIT)
EXTRA = st.one_of(st.just(math.nan), UNIT)  # NaN = "derive this emitter"

type Contributions = dict[int, list[Contribution]]
"""Per-slot contributions, as the oracle reads them: slot index → contributions."""


def lanes_for(slot: Slot) -> st.SearchStrategy[tuple[float, ...]]:
    """In-range lanes for ``slot``, as the cue compiler would produce them."""
    definition = slot.attribute
    if definition.kind == "discrete":
        return st.integers(0, len(slot.options) - 1).map(lambda k: (float(k),))
    if definition.kind == "color":
        return st.tuples(UNIT, UNIT, UNIT, *(EXTRA for _ in slot.extras))
    if definition.unit == "degrees":
        return st.floats(-90, 90).map(lambda v: (v,))
    if definition.unit == "hz":
        return st.floats(0, 20).map(lambda v: (v,))
    return UNIT.map(lambda v: (v,))


def set_lane_weights(source: Source, by_slot: dict[int, float]) -> None:
    """Give ``source`` per-lane weights, one per slot (``slot index → weight``):
    a slot's lanes share their weight, as they share their fade."""
    owner = COMPILED.slots.laneSlot

    def per_lane(lanes: NDArray[np.intp]) -> NDArray[np.float64]:
        return np.array([by_slot[int(owner[lane])] for lane in lanes], dtype=np.float64)

    source.htpWeights = per_lane(COMPILED.slots.intensityLanes[source.htpPos])
    source.ltpWeights = per_lane(source.ltpLanes)
    source.snapWeights = per_lane(source.snapLanes)


@dataclass(frozen=True)
class Drawn:
    """One random contributor: its band, its scalar weights and, per slot,
    ``slot index → (sequence number, lanes, per-slot weight)``."""

    name: str
    priority: int
    htpWeight: float
    ltpWeight: float
    intensityScale: float
    slots: dict[int, tuple[int, tuple[float, ...], float]]

    @property
    def numbers(self) -> list[int]:
        """Its distinct sequence numbers, ascending."""
        return sorted({seq for seq, _, _ in self.slots.values()})

    def source(self, sourceId: str, seq: int, indices: Iterable[int]) -> Source:
        """A source playing the slots ``indices`` at ``seq``, with this
        contributor's scalars and the slots' weights."""
        chosen = list(indices)
        values = {index: self.slots[index][1] for index in chosen}
        made = Source.of_cue(sourceId, self.priority, cue_from_values(COMPILED.slots, values))
        made.seq = seq
        made.htpWeight, made.ltpWeight = self.htpWeight, self.ltpWeight
        made.intensityScale = self.intensityScale
        set_lane_weights(made, {index: self.slots[index][2] for index in chosen})
        return made

    def contributions(self) -> list[Contribution]:
        """Its per-slot §7.1 contributions, each with the slot's own number."""
        made = []
        for index, (seq, lanes, weight) in self.slots.items():
            slot = SLOTS[index]
            scalar = self.htpWeight if slot.attribute.merge == "HTP" else self.ltpWeight
            made.append(
                Contribution(
                    slot=index,
                    sourceId=self.name,
                    priority=self.priority,
                    seq=seq,
                    value=np.array(lanes),
                    weight=np.full(slot.laneCount, scalar * weight),
                    intensityScale=self.intensityScale,
                )
            )
        return made


@st.composite
def drawn_contributors(draw: st.DrawFn, max_size: int = 4) -> list[Drawn]:
    """Random contributors with one to three numbers each, spread over their
    slots. Numbers come from one counter, so no two contributors share one."""
    numbers = iter(draw(st.permutations(range(1, 3 * max_size + 1))))
    made = []
    for k in range(draw(st.integers(0, max_size))):
        own = [next(numbers) for _ in range(draw(st.integers(1, 3)))]
        chosen = draw(st.lists(st.sampled_from(SLOTS), unique_by=lambda s: s.index, max_size=8))
        made.append(
            Drawn(
                name=f"c{k}",
                priority=draw(st.sampled_from((0, 50, 200))),
                htpWeight=draw(WEIGHT),
                ltpWeight=draw(WEIGHT),
                intensityScale=draw(UNIT),
                slots={
                    slot.index: (draw(st.sampled_from(own)), draw(lanes_for(slot)), draw(WEIGHT))
                    for slot in chosen
                },
            )
        )
    return made


def contributions_of(drawn: Sequence[Drawn]) -> Contributions:
    """Every contributor's per-slot contributions, for the oracle."""
    by_slot: Contributions = defaultdict(list)
    for contributor in drawn:
        for contribution in contributor.contributions():
            by_slot[contribution.slot].append(contribution)
    return by_slot


def one_source_per_number(drawn: Sequence[Drawn]) -> list[Source]:
    """The plainest correct split: one source per sequence number, sorted by
    ``(priority, seq)``."""
    made = [
        contributor.source(
            f"{contributor.name}/{seq}",
            seq,
            (index for index, (number, _, _) in contributor.slots.items() if number == seq),
        )
        for contributor in drawn
        for seq in contributor.numbers
    ]
    made.sort(key=SORT_KEY)
    return made


def resolve(ordered: Sequence[Source], relatives: Sequence[Relative] = ()) -> NDArray[np.float64]:
    """Resolve ``ordered`` (sorted) over :data:`COMPILED`'s defaults, then the
    present ``relatives`` (in any order)."""
    frame = np.empty(COMPILED.slots.laneCount)
    present = gather_relatives(relatives, [])
    Resolver(COMPILED.slots).resolve(ordered, COMPILED.slots.defaultFrame, frame, present)
    return frame


RELATIVE_ATTRIBUTES = ("intensity", "pan", "strobeRate")
"""The rig's attributes a relative layer may drive: scalars that fade."""


@st.composite
def relatives(
    draw: st.DrawFn, priorities: tuple[int, ...] = (0, 50, 200), max_size: int = 4
) -> list[Relative]:
    """Random relative contributions, each on one attribute like a compiled
    layer: ``add`` amounts in attribute units (intensity adds clamped to its
    range), ``multiply`` amounts in ``0..1``, with or without per-lane weights."""
    made = []
    for order in range(draw(st.integers(0, max_size))):
        attribute = draw(st.sampled_from(RELATIVE_ATTRIBUTES))
        chosen = draw(
            st.lists(
                st.sampled_from([slot for slot in SLOTS if slot.attribute.id == attribute]),
                unique_by=lambda s: s.index,
                min_size=1,
            )
        )
        op = draw(st.sampled_from(("add", "multiply")))
        amount = st.floats(-50, 50) if op == "add" else UNIT
        per_lane = draw(st.booleans())
        made.append(
            Relative(
                priority=draw(st.sampled_from(priorities)),
                seq=draw(st.integers(1, 20)),
                order=order,
                op=op,
                lanes=np.array([slot.laneOffset for slot in chosen], dtype=np.intp),
                amounts=np.array([draw(amount) for _ in chosen]),
                weights=np.array([draw(WEIGHT) for _ in chosen]) if per_lane else None,
                weight=draw(WEIGHT),
                clamp=(0.0, 1.0) if op == "add" and attribute == "intensity" else None,
            )
        )
    return made
