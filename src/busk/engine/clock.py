"""Clocks and fixed-rate scheduling (spec §11.1–§11.2).

All engine time comes from one injected monotonic clock: never wall-clock
time, never frame counts. Tests inject :class:`FakeClock`, which makes the
engine fully deterministic (§2.7). :class:`FixedRateSchedule` turns any clock
into the deadlines of a fixed-rate loop (the engine tick, the output cycle).
"""

from __future__ import annotations

import time
from typing import Final, Protocol

SWITCH_INTERVAL: Final = 0.0001
"""The GIL switch interval of every busk process that runs an engine or a
session (phase-3-plan §5.11; ``busk run``, and Phase 7's engine host).

Live edits are CPU-bound Python on the console's thread. Each time the engine
thread releases the GIL inside a large numpy kernel, it waits up to one
switch interval to get it back (the "convoy effect"), so a tick that releases
it N times is delayed by up to N intervals. CPython's default of 5 ms made
the reference rig's ticks stall up to 90 ms during edits; 0.1 ms keeps them
near 20–30 ms (bench/edit_latency.py). With one runnable thread the interval
costs nothing."""


class Clock(Protocol):
    """A monotonic time source, in seconds."""

    def now(self) -> float:
        """Return the current time. Never decreases."""
        ...

    def sleep_until(self, t: float) -> None:
        """Block until :meth:`now` is at least ``t``; return at once if it already is."""
        ...


class MonotonicClock:
    """The real clock: :func:`time.monotonic` and :func:`time.sleep`."""

    def now(self) -> float:
        return time.monotonic()

    def sleep_until(self, t: float) -> None:
        # Loop because a sleep may end marginally early; the contract is
        # "at or after t".
        while (remaining := t - time.monotonic()) > 0:
            time.sleep(remaining)


class FakeClock:
    """A deterministic clock for tests: time moves only when told to.

    :meth:`sleep_until` jumps straight to the target time instead of sleeping,
    so a whole engine run executes instantly and reproducibly.
    """

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, dt: float) -> None:
        """Move time forward by ``dt`` seconds (simulates work taking time)."""
        if dt < 0:
            raise ValueError("a monotonic clock cannot go backwards")
        self._now += dt

    def sleep_until(self, t: float) -> None:
        self._now = max(self._now, t)


class FixedRateSchedule:
    """Deadlines for a loop that runs at a fixed rate (§11.2).

    Iteration ``k`` is due at ``epoch + k / hz``. Computing each deadline from
    an integer count, instead of adding the period to the previous deadline,
    keeps the schedule free of accumulated floating-point drift.

    **Drop, don't spiral.** When an iteration ends after the next one was due,
    the schedule restarts from the current time instead of running late
    iterations back to back to catch up, which would only fall further behind.
    """

    def __init__(self, clock: Clock, hz: float) -> None:
        if hz <= 0:
            raise ValueError("the rate must be positive")
        self._clock = clock
        self._hz = hz
        self._epoch = clock.now()
        self._k = 0

    def wait_next(self) -> bool:
        """Sleep until the next deadline. Return ``True`` if it had already
        passed (an overrun); the schedule then restarts from now."""
        self._k += 1
        deadline = self._epoch + self._k / self._hz
        now = self._clock.now()
        if deadline < now:
            self._epoch, self._k = now, 0
            return True
        self._clock.sleep_until(deadline)
        return False
