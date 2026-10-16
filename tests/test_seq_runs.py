"""Contributors and sequence runs (phase-4-plan §5.4).

A contributor whose slots carry their own sequence numbers is handed to the
resolver as one source per run of its numbers between the other
contributors' numbers in its band. These tests check the split rule, where
HTP goes, the run cache, and (hypothesis) that splitting then compositing
whole sources in ``(priority, seq)`` order equals the per-slot oracle.
"""

from __future__ import annotations

import numpy as np
from hypothesis import given

from busk.engine.contributions import Contributor, SequencedSource, Source, gather
from reference_resolver import resolve_contributions
from resolver_strategies import (
    COMPILED,
    SLOTS,
    Drawn,
    contributions_of,
    drawn_contributors,
    resolve,
)

# Slots of the first fixture of the every-lane-kind rig.
INTENSITY, PAN, GOBO, STROBE = SLOTS[0], SLOTS[1], SLOTS[4], SLOTS[6]
INTENSITY_2 = SLOTS[7]


def drawn(name: str, slots: dict[int, tuple[int, float]], priority: int = 50) -> Drawn:
    """A fully present contributor: ``slot index → (number, value)`` for
    one-lane slots, every weight 1."""
    return Drawn(
        name=name,
        priority=priority,
        htpWeight=1.0,
        ltpWeight=1.0,
        intensityScale=1.0,
        slots={index: (seq, (value,), 1.0) for index, (seq, value) in slots.items()},
    )


def sequenced(contributor: Drawn) -> SequencedSource:
    """``contributor`` as a :class:`SequencedSource`, each lane numbered by its slot."""
    whole = contributor.source(contributor.name, 0, contributor.slots)
    slot_seq = np.zeros(len(SLOTS), dtype=np.int64)
    for index, (seq, _, _) in contributor.slots.items():
        slot_seq[index] = seq
    owner = COMPILED.slots.laneSlot
    htp = [seq for i, (seq, _, _) in contributor.slots.items() if SLOTS[i].attribute.merge == "HTP"]
    made = SequencedSource(whole)
    made.assign(
        slot_seq[owner[whole.ltpLanes]], slot_seq[owner[whole.snapLanes]], max(htp, default=0)
    )
    return made


def runs(sources: list[Source]) -> list[tuple[str, int, list[int]]]:
    """Each source as ``(id, seq, slot indices of its LTP and snap lanes)``."""
    owner = COMPILED.slots.laneSlot
    return [
        (s.sourceId, s.seq, sorted({int(owner[lane]) for lane in (*s.ltpLanes, *s.snapLanes)}))
        for s in sources
    ]


def assert_equals_oracle(contributors: list[Contributor], drawn_: list[Drawn]) -> None:
    expected = resolve_contributions(
        COMPILED.slots, contributions_of(drawn_), COMPILED.slots.defaultFrame
    )
    frame = resolve(gather(contributors, []))
    np.testing.assert_allclose(frame, expected, rtol=0, atol=1e-12, equal_nan=True)


# ------------------------------------------------------------------ the rule


def test_without_boundaries_a_contributor_is_one_source_at_its_newest_number() -> None:
    a = sequenced(drawn("a", {PAN.index: (1, 10.0), STROBE.index: (4, 5.0)}))
    assert a.seqs == (1, 4)
    (only,) = a.sources(())
    assert only is a.whole
    assert only.seq == 4
    assert gather([a], []) == [a.whole]


def test_an_htp_number_is_not_a_sort_key() -> None:
    # The intensity's 9 is newer than the pan's 1, but HTP ignores order in a
    # band: sorting the source at 9 would put the pan above b's newer one.
    a_ = drawn("a", {PAN.index: (1, 10.0), INTENSITY.index: (9, 0.5)})
    b_ = drawn("b", {PAN.index: (5, 20.0)})
    a, b = sequenced(a_), b_.source("b", 5, b_.slots)
    assert a.seqs == (1,)
    assert a.whole.seq == 1
    assert [s.sourceId for s in gather([a, b], [])] == ["a", "b"]
    assert_equals_oracle([a, b], [a_, b_])


def test_interleaved_numbers_split_both_contributors() -> None:
    a_ = drawn("a", {PAN.index: (1, 10.0), STROBE.index: (5, 1.0)})
    b_ = drawn("b", {PAN.index: (3, 20.0), STROBE.index: (7, 2.0)})
    c_ = drawn("c", {PAN.index: (4, 30.0)}, priority=200)  # another band: no boundary
    contributors: list[Contributor] = [sequenced(a_), sequenced(b_), sequenced(c_)]
    assert runs(gather(contributors, [])) == [
        ("a", 1, [PAN.index]),
        ("b", 3, [PAN.index]),
        ("a", 5, [STROBE.index]),
        ("b", 7, [STROBE.index]),
        ("c", 4, [PAN.index]),
    ]
    assert_equals_oracle(contributors, [a_, b_, c_])


def test_runs_take_the_newest_number_between_boundaries() -> None:
    a_ = drawn("a", {PAN.index: (1, 10.0), GOBO.index: (2, 1.0), STROBE.index: (6, 1.0)})
    b_ = drawn("b", {STROBE.index: (4, 2.0)})
    a = sequenced(a_)
    assert runs(list(a.sources((4,)))) == [
        ("a", 2, [PAN.index, GOBO.index]),
        ("a", 6, [STROBE.index]),
    ]
    assert_equals_oracle([a, b_.source("b", 4, b_.slots)], [a_, b_])


def test_htp_positions_go_with_the_newest_run() -> None:
    a_ = drawn(
        "a",
        {
            INTENSITY.index: (2, 0.5),
            PAN.index: (1, 10.0),
            INTENSITY_2.index: (8, 0.25),
            STROBE.index: (5, 1.0),
        },
    )
    a = sequenced(a_)
    older, newest = a.sources((3,))
    assert older.htpPos.size == 0
    assert older.seq == 1
    assert newest.htpPos is a.whole.htpPos
    assert newest.htpValues is a.whole.htpValues
    assert newest.seq == 5


def test_an_htp_only_contributor_is_never_a_boundary() -> None:
    a_ = drawn("a", {PAN.index: (1, 10.0), STROBE.index: (5, 1.0)})
    b_ = drawn("b", {INTENSITY.index: (3, 1.0)})
    a, b = sequenced(a_), sequenced(b_)
    assert b.seqs == ()
    assert b.whole.seq == 3
    assert [s.sourceId for s in gather([a, b], [])] == ["b", "a"]  # a is not split
    assert_equals_oracle([a, b], [a_, b_])


# ------------------------------------------------------------------ the cache


def test_runs_are_cached_per_assignment_and_boundaries() -> None:
    a = sequenced(drawn("a", {PAN.index: (1, 10.0), GOBO.index: (3, 1.0), STROBE.index: (6, 1.0)}))
    first = list(a.sources((2,)))
    assert list(a.sources((2,))) == first  # same objects: nothing rebuilt
    assert all(x is y for x, y in zip(a.sources((2,)), first, strict=True))
    moved = list(a.sources((4,)))
    assert runs(moved) == [("a", 3, [PAN.index, GOBO.index]), ("a", 6, [STROBE.index])]
    again = list(a.sources((4,)))
    assert all(x is y for x, y in zip(again, moved, strict=True))
    a.assign(np.array([1, 6]), np.array([3]))  # new numbers: rebuilt for the same boundaries
    assert not any(x is y for x, y in zip(a.sources((4,)), moved, strict=True))


def test_runs_follow_the_whole_evaluated_in_place() -> None:
    a = sequenced(drawn("a", {PAN.index: (1, 10.0), STROBE.index: (6, 1.0)}))
    a.whole.ltpValues = a.whole.ltpValues.copy()  # a fade's own, writable arrays
    a.whole.ltpWeights = np.ones(2)
    a.assign(np.array([1, 6]), np.zeros(0, dtype=np.int64))
    a.sources((3,))
    a.whole.ltpValues[:] = (15.0, 2.0)  # the next tick's evaluation
    a.whole.ltpWeights[:] = (0.5, 0.25)
    a.whole.ltpWeight = 0.75
    older, newer = a.sources((3,))
    assert (older.ltpValues.tolist(), newer.ltpValues.tolist()) == ([15.0], [2.0])
    assert older.ltpWeights is not None
    assert newer.ltpWeights is not None
    assert (older.ltpWeights.tolist(), newer.ltpWeights.tolist()) == ([0.5], [0.25])
    assert older.ltpWeight == newer.ltpWeight == 0.75


# ------------------------------------------------------------------ hypothesis


@given(drawn_contributors())
def test_splitting_then_compositing_equals_the_per_slot_oracle(drawn_: list[Drawn]) -> None:
    # A contributor with one number is a plain Source; the others split.
    contributors: list[Contributor] = [
        sequenced(c) if len(c.numbers) > 1 else c.source(c.name, c.numbers[0], c.slots)
        for c in drawn_
        if c.slots
    ]
    assert_equals_oracle(contributors, drawn_)
