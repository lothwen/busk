"""Presence envelopes (linear ramps, delays, steps, retargeting, settling) and
per-slot fades: ``ContributionSet`` (phase-4-plan §5.3)."""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from numpy.typing import NDArray

from busk.compiler.cues import SNAP_START
from busk.engine.curves import ease_in, ease_in_out, ease_out, linear, snap_end
from busk.engine.fades import (
    SETTLED,
    ContributionSet,
    Envelope,
    Part,
    SeqKind,
    SeqRule,
    Timing,
    Uniform,
)


def test_a_new_envelope_rests_at_zero() -> None:
    envelope = Envelope()
    assert envelope.value(0.0) == envelope.value(100.0) == 0.0
    assert envelope.settled(0.0)


def test_linear_ramp() -> None:
    envelope = Envelope()
    envelope.retarget(10.0, 1.0, 2.0)
    assert [envelope.value(t) for t in (9.0, 10.0, 10.5, 11.0, 11.5, 12.0, 20.0)] == [
        0.0,
        0.0,
        0.25,
        0.5,
        0.75,
        1.0,
        1.0,
    ]


def test_delay_holds_the_start_value() -> None:
    envelope = Envelope()
    envelope.retarget(0.0, 1.0, 1.0, delay=0.5)
    assert [envelope.value(t) for t in (0.0, 0.25, 0.5, 1.0, 1.5)] == [0.0, 0.0, 0.0, 0.5, 1.0]
    assert not envelope.settled(1.49)
    assert envelope.settled(1.5)


def test_zero_duration_is_a_step_at_start_plus_delay() -> None:
    envelope = Envelope()
    envelope.retarget(1.0, 1.0, 0.0, delay=0.25)
    assert envelope.value(1.2) == 0.0
    assert envelope.value(1.25) == 1.0
    assert envelope.settled(1.25)


def test_retarget_starts_from_the_current_value() -> None:
    # §7.8: a release 0.5 s into a 2 s fade-in goes 0.25 → 0 over the release time.
    envelope = Envelope()
    envelope.retarget(10.0, 1.0, 2.0)
    envelope.retarget(10.5, 0.0, 1.0)
    assert envelope.fromValue == 0.25
    assert [envelope.value(t) for t in (10.5, 11.0, 11.5)] == [0.25, 0.125, 0.0]
    assert not envelope.settled(11.4)
    assert envelope.settled(11.5)


def test_the_end_value_is_exact() -> None:
    envelope = Envelope(fromValue=0.3, toValue=0.3)
    envelope.retarget(0.1, 0.7, 0.3)  # 0.1 + 0.3 is not exactly 0.4 in binary
    assert envelope.value(0.25) == pytest.approx(0.5)
    assert envelope.value(0.4) == 0.7  # the target itself, not a lerp that lands near it
    assert envelope.settled(0.4)


@given(
    start=st.floats(0, 1e4),
    duration=st.floats(0, 100),
    target=st.floats(0, 1),
    times=st.lists(st.floats(0, 200), min_size=2, max_size=20),
)
def test_values_are_monotonic_and_bounded(
    start: float, duration: float, target: float, times: list[float]
) -> None:
    """§20: fades are monotonic between their start and end values."""
    envelope = Envelope(toValue=0.5, fromValue=0.5)
    envelope.retarget(start, target, duration)
    values = [envelope.value(start + t) for t in sorted(times)]
    low, high = min(0.5, target), max(0.5, target)
    assert all(low <= v <= high for v in values)
    steps = [b - a for a, b in itertools.pairwise(values)]
    assert all(step >= 0 for step in steps) if target >= 0.5 else all(step <= 0 for step in steps)


# -- ContributionSet ------------------------------------------------------------
#
# A small synthetic rig. Lanes of the logical frame and the slots that own them:
#
#   lane   0   1 2 3   4        5      6 7     8      9
#   slot   0   1 1 1   1        2      3 3     4      5
#          LTP r g b   extra    snap   pan     snap   LTP
#              (LTP)   (snap)          tilt
#
# Slot 1 is a colour slot: its r, g, b lanes are LTP and its extra snaps, so a
# change to any of them must change all four. HTP positions 0–3 are four
# intensity slots of one lane each.

LANE_SLOT = np.array([0, 1, 1, 1, 1, 2, 3, 3, 4, 5], dtype=np.intp)
SLOT_LANES: Mapping[int, tuple[tuple[int, ...], tuple[int, ...]]] = {
    0: ((0,), ()),
    1: ((1, 2, 3), (4,)),
    2: ((), (5,)),
    3: ((6, 7), ()),
    4: ((), (8,)),
    5: ((9,), ()),
}
HTP_POSITIONS = range(4)
MIDDLE = 0.5


@dataclass(frozen=True)
class Cue:
    """A fade target, as the arrays a ``CompiledCue`` carries."""

    htpPos: NDArray[np.intp]
    htpValues: NDArray[np.float64]
    ltpLanes: NDArray[np.intp]
    ltpValues: NDArray[np.float64]
    snapLanes: NDArray[np.intp]
    snapValues: NDArray[np.float64]
    snapThresholds: NDArray[np.float64]
    snap: Mapping[int, float] = field(default_factory=dict)  # for assertions


def cue(
    htp: Mapping[int, float] | None = None,
    ltp: Mapping[int, float] | None = None,
    snap: Mapping[int, float | tuple[float, float]] | None = None,
) -> Cue:
    """A target from ``{lane: value}`` maps; a snap value may carry its
    threshold as ``(value, threshold)`` (default: middle)."""
    htp, ltp, snap = htp or {}, ltp or {}, snap or {}
    pairs = {
        lane: entry if isinstance(entry, tuple) else (entry, MIDDLE) for lane, entry in snap.items()
    }
    lanes = sorted(pairs)
    return Cue(
        htpPos=np.array(sorted(htp), dtype=np.intp),
        htpValues=np.array([htp[k] for k in sorted(htp)], dtype=np.float64),
        ltpLanes=np.array(sorted(ltp), dtype=np.intp),
        ltpValues=np.array([ltp[k] for k in sorted(ltp)], dtype=np.float64),
        snapLanes=np.array(lanes, dtype=np.intp),
        snapValues=np.array([pairs[k][0] for k in lanes], dtype=np.float64),
        snapThresholds=np.array([pairs[k][1] for k in lanes], dtype=np.float64),
        snap={k: pairs[k][0] for k in lanes},
    )


@dataclass(frozen=True)
class CueRule:
    """A cue transition's timing, reduced to three choices: ``rise`` for
    every lane that enters or changes (HTP: going up), ``fall`` for HTP
    lanes going down, ``leave`` for lanes that leave."""

    rise: Timing
    fall: Timing
    leave: Timing

    @property
    def timings(self) -> tuple[Timing, ...]:
        return (self.rise, self.fall, self.leave)

    def entering(
        self, part: Part, at: NDArray[np.intp], falling: NDArray[np.bool_]
    ) -> NDArray[np.intp]:
        return np.where(falling, 1, 0).astype(np.intp)

    def leaving(self, part: Part, index: NDArray[np.intp]) -> NDArray[np.intp]:
        return np.full(index.size, 2, dtype=np.intp)


type Lanes = dict[int, tuple[float, float]]


def lanes(cs: ContributionSet, now: float) -> dict[str, Lanes]:
    """Every lane's ``(value, weight)`` at ``now``, by partition."""
    cs.evaluate(now)
    return {
        name: {
            int(i): (float(v), float(w))
            for i, v, w in zip(part.index, part.value, part.weight, strict=True)
        }
        for name, part in zip(("htp", "ltp", "snap"), cs.parts, strict=True)
    }


def seqs(cs: ContributionSet) -> dict[int, int]:
    """Every LTP and snap lane's sequence number."""
    return {
        int(i): int(n)
        for part in (cs.ltp, cs.snap)
        for i, n in zip(part.index, part.seq, strict=True)
    }


def settled_at(target: Cue, seq: int = 1) -> ContributionSet:
    """A set resting at ``target`` with every lane numbered ``seq``."""
    cs = ContributionSet(LANE_SLOT)
    cs.retarget(0.0, target, Uniform(Timing()), SeqRule.all(seq))
    assert cs.settled
    return cs


def test_a_new_set_is_empty_and_settled() -> None:
    cs = ContributionSet(LANE_SLOT)
    assert cs.empty
    assert cs.settled
    assert cs.unitWeights
    assert cs.groups == [SETTLED]
    assert lanes(cs, 5.0) == {"htp": {}, "ltp": {}, "snap": {}}


def test_entering_lanes_fade_in_at_their_target_value() -> None:
    cs = ContributionSet(LANE_SLOT)
    completion = cs.retarget(
        10.0, cue(htp={0: 0.8}, ltp={6: 0.3, 7: 0.7}), Uniform(Timing(2.0)), SeqRule.all(1)
    )
    assert completion == 12.0
    assert not cs.settled
    assert lanes(cs, 10.0)["htp"] == {0: (0.8, 0.0)}
    assert lanes(cs, 11.0) == {
        "htp": {0: (0.8, 0.5)},
        "ltp": {6: (0.3, 0.5), 7: (0.7, 0.5)},
        "snap": {},
    }
    assert lanes(cs, 12.0)["ltp"] == {6: (0.3, 1.0), 7: (0.7, 1.0)}
    assert cs.settled
    assert cs.unitWeights


def test_leaving_lanes_hold_their_value_and_fade_out() -> None:
    cs = settled_at(cue(htp={1: 1.0}, ltp={6: 0.3, 7: 0.7}, snap={5: 2.0}))
    completion = cs.retarget(1.0, cue(), Uniform(Timing(2.0)), SeqRule.fresh(2))
    assert completion == 3.0
    assert lanes(cs, 2.0) == {
        "htp": {1: (1.0, 0.5)},
        "ltp": {6: (0.3, 0.5), 7: (0.7, 0.5)},
        "snap": {5: (2.0, 0.5)},
    }
    assert seqs(cs) == {5: 1, 6: 1, 7: 1}  # lanes that leave keep their number
    assert lanes(cs, 3.0) == {"htp": {}, "ltp": {}, "snap": {}}  # gone, compacted
    assert cs.settled
    assert cs.empty


def test_a_value_change_fades_from_the_current_value() -> None:
    cs = settled_at(cue(ltp={9: 0.2}))
    assert cs.retarget(0.0, cue(ltp={9: 0.6}), Uniform(Timing(2.0)), SeqRule.fresh(2)) == 2.0
    value, weight = lanes(cs, 1.0)["ltp"][9]
    assert (value, weight) == (pytest.approx(0.4), 1.0)
    # Retargeted mid-fade, it starts from where it is: no jump.
    cs.retarget(1.0, cue(ltp={9: 0.0}), Uniform(Timing(1.0)), SeqRule.fresh(3))
    assert lanes(cs, 1.0)["ltp"][9] == (value, 1.0)
    assert lanes(cs, 1.5)["ltp"][9][0] == pytest.approx(0.2)
    assert lanes(cs, 2.0)["ltp"][9] == (0.0, 1.0)  # exactly the target


def test_unchanged_slots_keep_their_running_fade() -> None:
    """Decision 5: a 0-s GO halfway through a 10-s pan fade leaves the pan alone."""
    cs = settled_at(cue(ltp={6: 0.0, 7: 0.0, 9: 0.0}))
    cs.retarget(0.0, cue(ltp={6: 1.0, 7: 1.0, 9: 0.0}), Uniform(Timing(10.0)), SeqRule.fresh(2))
    pan = cs.groups[int(cs.ltp.group[cs.ltp.index == 6][0])]
    completion = cs.retarget(
        5.0, cue(ltp={6: 1.0, 7: 1.0, 9: 1.0}), Uniform(Timing()), SeqRule.fresh(3)
    )
    assert completion == 5.0  # only lane 9 started a fade, and it has no length
    assert cs.groups[int(cs.ltp.group[cs.ltp.index == 6][0])] is pan  # the 10-s fade runs on
    state = lanes(cs, 7.5)["ltp"]
    assert state[6][0] == pytest.approx(0.75)
    assert state[9] == (1.0, 1.0)
    assert seqs(cs) == {6: 2, 7: 2, 9: 3}
    assert lanes(cs, 10.0)["ltp"][6] == (1.0, 1.0)
    assert cs.settled


def test_a_slot_changes_as_a_whole() -> None:
    """A change to one lane of a colour slot changes its LTP and snap lanes alike."""
    colour = {1: 0.1, 2: 0.2, 3: 0.3}
    cs = settled_at(cue(ltp={**colour, 6: 0.5}, snap={4: math.nan}))
    cs.retarget(
        1.0,
        cue(ltp={**colour, 2: 0.9, 6: 0.5}, snap={4: math.nan}),
        Uniform(Timing(1.0)),
        SeqRule.fresh(2),
    )
    ltp_groups = dict(zip(cs.ltp.index.tolist(), cs.ltp.group.tolist(), strict=True))
    snap_groups = dict(zip(cs.snap.index.tolist(), cs.snap.group.tolist(), strict=True))
    assert ltp_groups[1] == ltp_groups[2] == ltp_groups[3] == snap_groups[4] != 0
    assert ltp_groups[6] == 0  # slot 3 did not change
    assert seqs(cs) == {1: 2, 2: 2, 3: 2, 4: 2, 6: 1}


def test_derived_colour_extras_are_not_changed_forever() -> None:
    """NaN ("derive") equals NaN: re-aiming at the same colour changes nothing."""
    target = cue(ltp={1: 0.1, 2: 0.2, 3: 0.3}, snap={4: math.nan})
    cs = settled_at(target)
    assert cs.retarget(4.0, target, Uniform(Timing(1.0)), SeqRule.fresh(2)) == 4.0
    assert cs.settled
    assert seqs(cs) == {1: 1, 2: 1, 3: 1, 4: 1}
    assert math.isnan(lanes(cs, 4.5)["snap"][4][0])


@pytest.mark.parametrize(
    ("threshold", "before", "switch"),
    [(SNAP_START, 1.0, 1.0 + 1e-9), (MIDDLE, 1.999, 2.0), (1.0, 2.999, 3.0)],
    ids=["start", "middle", "end"],
)
def test_a_snap_value_switches_at_its_threshold(
    threshold: float, before: float, switch: float
) -> None:
    """A 2-s fade after a 1-s delay: start switches as the fade begins, middle
    halfway, end when it finishes."""
    cs = settled_at(cue(snap={8: (1.0, threshold)}))
    cs.retarget(
        0.0, cue(snap={8: (3.0, threshold)}), Uniform(Timing(2.0, delay=1.0)), SeqRule.fresh(2)
    )
    assert lanes(cs, 1.0)["snap"][8] == (1.0, 1.0)  # end of the delay: not yet
    assert lanes(cs, before)["snap"][8] == (1.0, 1.0)
    assert lanes(cs, switch)["snap"][8] == (3.0, 1.0)


def test_snap_lanes_enter_at_their_value() -> None:
    """An entering snap lane holds its value; its presence fades (the resolver
    compares presence with the threshold)."""
    cs = ContributionSet(LANE_SLOT)
    cs.retarget(0.0, cue(snap={5: (2.0, 1.0)}), Uniform(Timing(2.0)), SeqRule.all(1))
    assert lanes(cs, 1.0)["snap"] == {5: (2.0, 0.5)}
    assert cs.snap.threshold.tolist() == [1.0]


SEQ_CASES: dict[SeqKind, dict[int, int]] = {
    #        unchanged  changed  leaves  new
    "fresh": {0: 1, 6: 2, 7: 2, 5: 1, 9: 2},
    "all": {0: 2, 6: 2, 7: 2, 5: 2, 9: 2},
    "keep": {0: 1, 6: 1, 7: 1, 5: 1, 9: 2},
    "mask": {0: 2, 6: 1, 7: 1, 5: 1, 9: 2},  # the mask is slot 0
}


@pytest.mark.parametrize("kind", list(SEQ_CASES))
def test_sequence_rules(kind: SeqKind) -> None:
    """Decision 4. Lane 0 is unchanged, slot 3 (lanes 6–7) changes value,
    slot 2 (lane 5) leaves and lane 9 enters."""
    cs = settled_at(cue(ltp={0: 0.5, 6: 0.2, 7: 0.2}, snap={5: 1.0}))
    rule = {
        "fresh": SeqRule.fresh(2),
        "all": SeqRule.all(2),
        "keep": SeqRule.keep(2),
        "mask": SeqRule.mask(2, np.array([0], dtype=np.intp)),
    }[kind]
    cs.retarget(1.0, cue(ltp={0: 0.5, 6: 0.7, 7: 0.2, 9: 0.4}), Uniform(Timing(1.0)), rule)
    assert seqs(cs) == SEQ_CASES[kind]


def test_scale_folds_a_release_level_into_the_slots() -> None:
    """Decision 8: re-activating a releasing playback starts each slot from its
    presence × the release level, then fades it in."""
    cs = settled_at(cue(htp={0: 1.0}, ltp={6: 0.5}))
    completion = cs.retarget(
        1.0,
        cue(htp={0: 1.0}, ltp={6: 0.5}),
        Uniform(Timing(2.0)),
        SeqRule.all(2),
        scale=0.5,
        ltpScale=0.25,
    )
    assert completion == 3.0
    assert lanes(cs, 1.0) == {"htp": {0: (1.0, 0.5)}, "ltp": {6: (0.5, 0.25)}, "snap": {}}
    assert lanes(cs, 2.0) == {"htp": {0: (1.0, 0.75)}, "ltp": {6: (0.5, 0.625)}, "snap": {}}
    assert lanes(cs, 3.0)["htp"] == {0: (1.0, 1.0)}
    assert cs.unitWeights


def test_htp_timing_follows_the_direction_of_the_intensity() -> None:
    """Decision 6: rising intensities take the in timing, falling ones the
    out timing, lanes that leave the leave timing."""
    rule = CueRule(rise=Timing(1.0), fall=Timing(4.0), leave=Timing(8.0))
    cs = settled_at(cue(htp={0: 0.8, 1: 0.2, 2: 0.5}))
    completion = cs.retarget(0.0, cue(htp={0: 0.3, 1: 0.9, 3: 0.1}), rule, SeqRule.fresh(2))
    assert completion == 8.0
    state = lanes(cs, 1.0)["htp"]
    assert state[1] == (0.9, 1.0)  # rising: done after 1 s
    assert state[3] == (0.1, 1.0)  # entering: rising
    assert state[0][0] == pytest.approx(0.8 - 0.5 / 4)  # falling: a quarter of the way
    assert state[2] == (0.5, 1.0 - 1.0 / 8)  # leaving


def test_falling_compares_with_the_effective_intensity() -> None:
    """A lane at 0.8 but only a quarter present is at 0.2: going to 0.5 rises."""
    rule = CueRule(rise=Timing(1.0), fall=Timing(4.0), leave=Timing(8.0))
    cs = ContributionSet(LANE_SLOT)
    cs.retarget(0.0, cue(htp={0: 0.8}), Uniform(Timing(4.0)), SeqRule.all(1))
    assert cs.retarget(1.0, cue(htp={0: 0.5}), rule, SeqRule.fresh(2)) == 2.0


def test_a_retarget_that_changes_nothing_completes_at_once() -> None:
    target = cue(htp={0: 1.0}, ltp={6: 0.5})
    cs = settled_at(target)
    assert cs.retarget(7.0, target, Uniform(Timing(3.0)), SeqRule.all(2)) == 7.0
    assert cs.settled
    assert seqs(cs) == {6: 2}  # re-assert: renumbered, nothing moves


def test_finished_fades_compact_to_the_static_fast_path() -> None:
    cs = settled_at(cue(htp={0: 1.0, 1: 1.0}, ltp={6: 0.5}))
    cs.retarget(0.0, cue(htp={0: 1.0}, ltp={6: 0.9}), Uniform(Timing(1.0)), SeqRule.fresh(2))
    version = cs.version
    lanes(cs, 0.5)
    assert cs.version == version  # evaluating mid-fade refills in place
    assert not cs.settled
    assert not cs.unitWeights
    lanes(cs, 1.0)
    assert cs.version == version + 1  # compacted: new arrays
    assert cs.settled
    assert cs.unitWeights
    assert cs.groups == [SETTLED]
    assert cs.htp.index.tolist() == [0]  # the lane that faded out is gone
    value, weight = cs.ltp.value, cs.ltp.weight
    lanes(cs, 2.0)
    assert cs.ltp.value is value
    assert cs.ltp.weight is weight
    assert cs.ltp.value.tolist() == [0.9]


def test_finished_groups_settle_exactly_while_others_run() -> None:
    """A lane whose fade has ended is exactly its target, even while another
    fade keeps the set running: never a lerp an ulp beside it."""
    rule = CueRule(rise=Timing(0.3), fall=Timing(0.3), leave=Timing(10.0))
    cs = settled_at(cue(htp={1: 1.0}, ltp={9: 0.1}))
    cs.retarget(0.1, cue(ltp={9: 0.7}), rule, SeqRule.fresh(2))  # 0.1 + 0.3 is inexact
    assert lanes(cs, 0.4)["ltp"][9] == (0.7, 1.0)
    assert not cs.settled  # lane 1 is still fading out


def test_groups_are_interned_and_unused_ones_dropped() -> None:
    cs = ContributionSet(LANE_SLOT)
    cs.retarget(0.0, cue(htp={0: 1.0}, ltp={6: 0.5, 7: 0.5}), Uniform(Timing(2.0)), SeqRule.all(1))
    assert len(cs.groups) == 2  # one timing, one group
    cs.retarget(
        0.0, cue(htp={0: 1.0, 1: 1.0}, ltp={6: 0.5, 7: 0.5}), Uniform(Timing(2.0)), SeqRule.keep(2)
    )
    assert len(cs.groups) == 2  # the same instant and timing: the same group
    cs.retarget(1.0, cue(htp={0: 0.5, 1: 0.5}), Uniform(Timing(3.0)), SeqRule.fresh(3))
    # Every lane now fades with the new timing: the first group is unused.
    assert [group.start for group in cs.groups] == [SETTLED.start, 1.0]


def test_remap_moves_running_fades() -> None:
    cs = ContributionSet(LANE_SLOT)
    cs.retarget(
        0.0,
        cue(htp={0: 1.0, 2: 0.5}, ltp={6: 0.2, 7: 0.4, 9: 0.8}),
        Uniform(Timing(2.0)),
        SeqRule.all(1),
    )
    before = lanes(cs, 1.0)
    lane_map = np.full(10, -1, dtype=np.intp)
    lane_map[[6, 9]] = [9, 6]  # swapped; lane 7 is gone
    pos_map = np.array([3, -1, -1, -1], dtype=np.intp)  # position 0 moved; 2 is gone
    cs.remap(LANE_SLOT, lane_map, pos_map)
    assert cs.ltp.index.tolist() == [6, 9]  # sorted again
    assert lanes_no_eval(cs) == {
        "htp": {3: before["htp"][0]},
        "ltp": {6: before["ltp"][9], 9: before["ltp"][6]},
        "snap": {},
    }
    assert lanes(cs, 2.0) == {
        "htp": {3: (1.0, 1.0)},
        "ltp": {6: (0.8, 1.0), 9: (0.2, 1.0)},
        "snap": {},
    }


def lanes_no_eval(cs: ContributionSet) -> dict[str, Lanes]:
    """The lanes as last evaluated, without evaluating again."""
    return {
        name: {
            int(i): (float(v), float(w))
            for i, v, w in zip(part.index, part.value, part.weight, strict=True)
        }
        for name, part in zip(("htp", "ltp", "snap"), cs.parts, strict=True)
    }


def test_freeze_holds_every_lane_where_it_is() -> None:
    """§7.8: a release 0.5 s into a 2 s fade-in holds the slots at 0.25 (the
    playback's release envelope then fades them)."""
    cs = ContributionSet(LANE_SLOT)
    cs.retarget(10.0, cue(htp={0: 1.0}, ltp={6: 0.5}), Uniform(Timing(2.0)), SeqRule.all(1))
    cs.freeze(10.5)
    assert cs.settled
    assert not cs.unitWeights
    assert lanes(cs, 20.0) == {"htp": {0: (1.0, 0.25)}, "ltp": {6: (0.5, 0.25)}, "snap": {}}
    # Re-activation fades the frozen slots back in from where they are.
    cs.retarget(20.0, cue(htp={0: 1.0}, ltp={6: 0.5}), Uniform(Timing(1.0)), SeqRule.all(2))
    assert lanes(cs, 20.5)["htp"] == {0: (1.0, 0.625)}


def test_freeze_drops_lanes_that_are_not_present_yet() -> None:
    cs = ContributionSet(LANE_SLOT)
    cs.retarget(0.0, cue(htp={0: 1.0}), Uniform(Timing(1.0, delay=1.0)), SeqRule.all(1))
    cs.freeze(0.5)
    assert cs.empty


def test_clear() -> None:
    cs = ContributionSet(LANE_SLOT)
    cs.retarget(0.0, cue(htp={0: 1.0}, ltp={6: 0.5}), Uniform(Timing(2.0)), SeqRule.all(1))
    version = cs.version
    cs.clear()
    assert cs.empty
    assert cs.settled
    assert cs.version > version


# -- the five §5.3 invariants (hypothesis) --------------------------------------

LEVELS = st.one_of(st.sampled_from([0.0, 0.25, 0.5, 1.0]), st.floats(0, 1))
SNAP_VALUES = st.sampled_from([math.nan, 0.0, 1.0, 2.0])
THRESHOLDS = st.sampled_from([SNAP_START, MIDDLE, 1.0])
# Every fade has a length, so a retarget never steps at ``now`` (a step at
# once, or ``snapStart`` without a delay, would be a jump by design).
TIMINGS = st.builds(
    Timing,
    duration=st.one_of(st.sampled_from([0.5, 1.0, 2.0]), st.floats(0.01, 5)),
    delay=st.one_of(st.just(0.0), st.floats(0, 2)),
    curve=st.sampled_from([linear, ease_in, ease_out, ease_in_out, snap_end]),
)


# A snap lane's threshold belongs to its attribute (``snapAt``, or ``middle``
# for colour extras), so it is the same in every cue: one draw per run.
LANE_THRESHOLDS = st.fixed_dictionaries(
    {lane: THRESHOLDS for _, snap_lanes in SLOT_LANES.values() for lane in snap_lanes}
)


@st.composite
def targets(draw: st.DrawFn, thresholds: Mapping[int, float]) -> Cue:
    """A cue that sets whole slots, with values that often repeat."""
    htp = {p: draw(LEVELS) for p in draw(st.sets(st.sampled_from(HTP_POSITIONS)))}
    ltp: dict[int, float] = {}
    snap: dict[int, float | tuple[float, float]] = {}
    for slot in sorted(draw(st.sets(st.sampled_from(sorted(SLOT_LANES))))):
        ltp_lanes, snap_lanes = SLOT_LANES[slot]
        ltp.update({lane: draw(LEVELS) for lane in ltp_lanes})
        snap.update({lane: (draw(SNAP_VALUES), thresholds[lane]) for lane in snap_lanes})
    return cue(htp, ltp, snap)


@dataclass(frozen=True)
class Step:
    """One retarget of a scripted run, ``after`` seconds after the previous."""

    after: float
    target: Cue
    rule: CueRule
    kind: SeqKind
    mask: tuple[int, ...]
    probes: tuple[float, ...]  # extra evaluations, as fractions of the gap before it

    def seq_rule(self, seq: int) -> SeqRule:
        if self.kind == "mask":
            return SeqRule.mask(seq, np.array(self.mask, dtype=np.intp))
        return SeqRule(self.kind, seq)


STEPS = LANE_THRESHOLDS.flatmap(
    lambda thresholds: st.lists(
        st.builds(
            Step,
            after=st.one_of(st.just(0.0), st.sampled_from([0.5, 1.0]), st.floats(0, 6)),
            target=targets(thresholds),
            rule=st.builds(CueRule, rise=TIMINGS, fall=TIMINGS, leave=TIMINGS),
            kind=st.sampled_from(["fresh", "all", "keep", "mask"]),
            mask=st.lists(st.sampled_from(sorted(SLOT_LANES)), max_size=3).map(tuple),
            probes=st.lists(st.floats(0, 1), max_size=4).map(lambda ps: tuple(sorted(ps))),
        ),
        min_size=1,
        max_size=6,
    )
)


def same(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """Equal ``(value, weight)``, with NaN equal to NaN."""
    return all(x == y or (math.isnan(x) and math.isnan(y)) for x, y in zip(a, b, strict=True))


def assert_slots_share(cs: ContributionSet) -> None:
    """Invariant 5: a slot's lanes share their group and their sequence number."""
    by_slot: dict[int, set[tuple[int, int]]] = {}
    for part in (cs.ltp, cs.snap):
        for lane, group, seq in zip(part.index, part.group, part.seq, strict=True):
            by_slot.setdefault(int(LANE_SLOT[lane]), set()).add((int(group), int(seq)))
    assert all(len(pairs) == 1 for pairs in by_slot.values()), by_slot


def assert_in_range(cs: ContributionSet) -> None:
    """Invariant 3: values between their from and to values, presence in 0..1."""
    for part in cs.parts:
        for f, t, v, fw, tw, w in zip(
            part.fromValue,
            part.toValue,
            part.value,
            part.fromWeight,
            part.toWeight,
            part.weight,
            strict=True,
        ):
            if part.snapping:
                assert same((v, 0.0), (f, 0.0)) or same((v, 0.0), (t, 0.0))
            else:
                assert min(f, t) - 1e-12 <= v <= max(f, t) + 1e-12
            assert min(fw, tw) - 1e-12 <= w <= max(fw, tw) + 1e-12
            assert 0.0 <= w <= 1.0


@settings(max_examples=150)
@given(steps=STEPS)
def test_retarget_never_jumps_and_slots_share(steps: list[Step]) -> None:
    """Invariants 1 and 5: a retarget leaves every lane's ``(value, weight)`` at
    ``now`` as it was (new lanes start at weight 0, dropped lanes were at 0)."""
    cs = ContributionSet(LANE_SLOT)
    now = 0.0
    for n, step in enumerate(steps, start=1):
        now += step.after
        before = lanes(cs, now)
        cs.retarget(now, step.target, step.rule, step.seq_rule(n))
        after = lanes_no_eval(cs)
        for name in ("htp", "ltp", "snap"):
            for lane, state in before[name].items():
                assert same(after[name].get(lane, (state[0], 0.0)), state) or (
                    lane not in after[name] and state[1] == 0.0
                )
            for lane, state in after[name].items():
                assert lane in before[name] or state[1] == 0.0
        assert_slots_share(cs)


@settings(max_examples=150)
@given(steps=STEPS)
def test_evaluation_is_pure_in_time_and_in_range(steps: list[Step]) -> None:
    """Invariants 2 and 3: a set evaluated at extra times between retargets
    agrees exactly with one evaluated only at the retargets, and every value
    and presence stays in range."""
    plain, probed = ContributionSet(LANE_SLOT), ContributionSet(LANE_SLOT)
    now = 0.0
    for n, step in enumerate(steps, start=1):
        for fraction in step.probes:
            lanes(probed, now + step.after * fraction)
            assert_in_range(probed)
        now += step.after
        assert lanes(plain, now) == lanes(probed, now) or _same_lanes(plain, probed, now)
        completions = [
            cs.retarget(now, step.target, step.rule, step.seq_rule(n)) for cs in (plain, probed)
        ]
        assert completions[0] == completions[1]
        assert seqs(plain) == seqs(probed)
        assert_in_range(probed)
    later = now + 20.0  # past every fade: both sets have compacted alike
    assert _same_lanes(plain, probed, later)
    assert plain.settled
    assert probed.settled


def _same_lanes(a: ContributionSet, b: ContributionSet, now: float) -> bool:
    """``lanes`` of two sets agree, with NaN equal to NaN."""
    x, y = lanes(a, now), lanes(b, now)
    return all(
        x[name].keys() == y[name].keys()
        and all(same(x[name][lane], y[name][lane]) for lane in x[name])
        for name in x
    )


@settings(max_examples=150)
@given(steps=STEPS)
def test_after_its_completion_the_set_is_its_target(steps: list[Step]) -> None:
    """Invariant 4: once every fade has completed, the set holds exactly the
    last target, fully present, on the static fast path."""
    cs = ContributionSet(LANE_SLOT)
    now = done = 0.0
    for n, step in enumerate(steps, start=1):
        now += step.after
        done = max(done, cs.retarget(now, step.target, step.rule, step.seq_rule(n)))
    target = steps[-1].target
    state = lanes(cs, done)
    assert cs.settled
    assert cs.unitWeights
    assert state["htp"] == {
        int(p): (float(v), 1.0) for p, v in zip(target.htpPos, target.htpValues, strict=True)
    }
    assert state["ltp"] == {
        int(p): (float(v), 1.0) for p, v in zip(target.ltpLanes, target.ltpValues, strict=True)
    }
    assert state["snap"].keys() == target.snap.keys()
    assert all(same(state["snap"][lane], (v, 1.0)) for lane, v in target.snap.items())
