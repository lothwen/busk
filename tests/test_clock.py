"""Clock contracts (fake and real) and the fixed-rate schedule."""

from __future__ import annotations

import pytest

from busk.engine.clock import FakeClock, FixedRateSchedule, MonotonicClock

# --------------------------------------------------------------- FakeClock


def test_fake_clock_starts_where_told_and_only_moves_when_told() -> None:
    clock = FakeClock(start=5.0)
    assert clock.now() == 5.0
    assert clock.now() == 5.0
    clock.advance(0.25)
    assert clock.now() == 5.25


def test_fake_clock_sleep_until_jumps_forward_but_never_back() -> None:
    clock = FakeClock()
    clock.sleep_until(2.0)
    assert clock.now() == 2.0
    clock.sleep_until(1.0)  # already past: returns at once
    assert clock.now() == 2.0


def test_fake_clock_refuses_to_go_backwards() -> None:
    with pytest.raises(ValueError, match="backwards"):
        FakeClock().advance(-0.001)


def test_fake_clock_is_deterministic() -> None:
    def script(clock: FakeClock) -> list[float]:
        seen = []
        for step in (0.1, 0.2, 0.3):
            clock.advance(step)
            clock.sleep_until(clock.now() + 0.01)
            seen.append(clock.now())
        return seen

    assert script(FakeClock()) == script(FakeClock())


# ----------------------------------------------------------- MonotonicClock


def test_monotonic_clock_never_decreases() -> None:
    clock = MonotonicClock()
    readings = [clock.now() for _ in range(10_000)]
    assert readings == sorted(readings)


def test_monotonic_clock_sleep_until_returns_at_or_after_target() -> None:
    clock = MonotonicClock()
    for delay in (0.0, 0.001, 0.02):
        target = clock.now() + delay
        clock.sleep_until(target)
        assert clock.now() >= target


def test_monotonic_clock_sleep_until_past_returns_at_once() -> None:
    clock = MonotonicClock()
    start = clock.now()
    clock.sleep_until(start - 10)
    assert clock.now() - start < 0.05


# -------------------------------------------------------- FixedRateSchedule


def test_schedule_deadlines_are_exact_multiples_of_the_period() -> None:
    clock = FakeClock()
    schedule = FixedRateSchedule(clock, 100)
    times = []
    for _ in range(1000):
        assert schedule.wait_next() is False
        times.append(clock.now())
    # k / hz, not an accumulated sum of 0.01s: no floating-point drift.
    assert times == [k / 100 for k in range(1, 1001)]


def test_schedule_restarts_after_an_overrun() -> None:
    clock = FakeClock()
    schedule = FixedRateSchedule(clock, 100)
    assert schedule.wait_next() is False  # t = 0.01
    clock.advance(0.035)  # work overran: now 0.045, deadline 0.02 has passed
    assert schedule.wait_next() is True
    assert clock.now() == pytest.approx(0.045)  # no sleep, no catch-up
    assert schedule.wait_next() is False
    assert clock.now() == pytest.approx(0.055)


@pytest.mark.parametrize("hz", [0, -1])
def test_schedule_needs_a_positive_rate(hz: float) -> None:
    with pytest.raises(ValueError, match="positive"):
        FixedRateSchedule(FakeClock(), hz)
