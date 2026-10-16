"""When an sACN route transmits (E1.31 §6.6; phase-1.5-plan decision 4).

A change is sent at once, then repeated on each of the next three cycles; after
that, unchanged data is suppressed except for a keep-alive every 0.9 s. The
table-driven cases run on a regular 44 Hz clock. The hypothesis properties run
on random change patterns, with cycle gaps of 1/44 s ± jitter and occasional
overruns of up to 0.2 s.

Each cycle asks :meth:`SendPolicy.due` exactly once and gets one answer, so a
route sends at most one packet per cycle by construction.

Since Phase 6 the policy takes its repeats and keep-alive as parameters. The
tests above the properties use ``SendPolicy()``, so they pin the sACN
defaults; the last property checks Art-Net's ``repeats=0, keepalive=1.0``.
"""

from __future__ import annotations

from collections.abc import Iterable
from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from busk.output.sacn import KEEPALIVE_S, REPEATS, SendPolicy

CYCLE = 1 / 44
TEN_SECONDS = 440  # cycles


def send_cycles(changes: Iterable[int], cycles: int) -> list[int]:
    """The cycles at which a fresh policy sends, on a regular 44 Hz clock, when
    the universe changes at the cycles in ``changes``."""
    policy = SendPolicy()
    changed = set(changes)
    return [k for k in range(cycles) if policy.due(k in changed, k * CYCLE)]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        pytest.param([0], [0, 1, 2, 3, *range(43, 440, 40)], id="one change, then 10 s static"),
        pytest.param(
            [0, 20],
            [0, 1, 2, 3, 20, 21, 22, 23, *range(63, 440, 40)],
            id="a change during suppression is sent at once and re-arms the repeats",
        ),
        pytest.param(
            [0, 2],
            [0, 1, 2, 3, 4, 5, *range(45, 440, 40)],
            id="a change during the repeats re-arms them",
        ),
        pytest.param(range(440), list(range(440)), id="a change every cycle"),
        pytest.param([], list(range(0, 440, 40)), id="never changed: keep-alives only"),
    ],
)
def test_send_cycles(changes: Iterable[int], expected: list[int]) -> None:
    assert send_cycles(changes, TEN_SECONDS) == expected


def test_keep_alives_fall_inside_the_e131_window() -> None:
    keep_alives = send_cycles([0], TEN_SECONDS)[REPEATS:]
    gaps = {round((b - a) * CYCLE, 6) for a, b in pairwise(keep_alives)}
    assert gaps == {round(40 * CYCLE, 6)}  # 0.909 s: inside 0.8–1.0 s, far inside 2.5 s


# ------------------------------------------------------------- properties


@st.composite
def schedules(draw: st.DrawFn) -> list[tuple[float, bool]]:
    """``(time, changed)`` for each cycle. Gaps are 1/44 s ± 3 ms, with about
    one overrun gap (up to 0.2 s) in 25; about one cycle in 30 has a change."""
    cycles = draw(
        st.lists(
            st.tuples(
                st.integers(0, 29),  # 0: the universe changed this cycle
                st.integers(0, 24),  # 0: the gap after this cycle is an overrun
                st.floats(-0.003, 0.003),  # jitter
                st.floats(CYCLE, 0.2),  # overrun gap
            ),
            min_size=1,
            max_size=600,
        )
    )
    now, schedule = 0.0, []
    for change, overrun, jitter, overrun_gap in cycles:
        schedule.append((now, change == 0))
        now += overrun_gap if overrun == 0 else CYCLE + jitter
    return schedule


@settings(max_examples=200, deadline=None)
@given(schedules())
def test_transmission_rules_hold(schedule: list[tuple[float, bool]]) -> None:
    policy = SendPolicy()
    sent = [policy.due(changed, now) for now, changed in schedule]
    times = [now for now, _ in schedule]
    changes = {k for k, (_, changed) in enumerate(schedule) if changed}
    repeats = {k + d for k in changes for d in range(1, REPEATS + 1) if k + d < len(schedule)}
    sends = [k for k, s in enumerate(sent) if s]
    largest_gap = max((b - a for a, b in pairwise(times)), default=0.0)

    assert sent[0], "the first cycle always sends"
    assert all(sent[k] for k in changes), "every change is sent in its own cycle"
    assert all(sent[k] for k in repeats), "the 3 cycles after a change send"
    for previous, k in pairwise(sends):
        gap = times[k] - times[previous]
        if k not in changes | repeats:
            assert gap >= KEEPALIVE_S, "while suppressed, sends are a keep-alive apart"
        assert gap <= KEEPALIVE_S + largest_gap, "no gap exceeds a keep-alive plus one cycle"
        if k not in changes | repeats and largest_gap <= CYCLE + 0.003:
            assert 0.8 <= gap <= 1.0, "regular cycles keep keep-alives inside E1.31's window"
    last = 0
    for k, s in enumerate(sent):
        if s:
            last = k
        else:
            assert times[k] - times[last] < KEEPALIVE_S, "a due keep-alive is never skipped"


@settings(max_examples=200, deadline=None)
@given(schedules())
def test_art_net_parameters_send_each_change_once_and_keep_alive_every_second(
    schedule: list[tuple[float, bool]],
) -> None:
    policy = SendPolicy(repeats=0, keepalive=1.0)
    sent = [policy.due(changed, now) for now, changed in schedule]
    times = [now for now, _ in schedule]
    changes = {k for k, (_, changed) in enumerate(schedule) if changed}

    assert sent[0], "the first cycle always sends"
    assert all(sent[k] for k in changes), "every change is sent in its own cycle"
    last = 0
    for k, s in enumerate(sent):
        if k == 0:
            continue
        if s and k not in changes:
            assert times[k] - times[last] >= 1.0, "an unchanged universe goes once a second"
        if not s:
            assert times[k] - times[last] < 1.0, "a due keep-alive is never skipped"
        if s:
            last = k
