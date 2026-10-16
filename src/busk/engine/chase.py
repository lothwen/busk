"""Chases: step timing, beat lock and cue order (spec §9.4, phase-4-plan §5.7).

A chase is a cue list in ``chase`` mode. Its playback steps through the cues
by itself, at a rate in steps per second (Hz) or steps per beat of a speed
master (BPM), and fades into each step over ``crossfade`` × the step length.

**Position** (decisions 1 and 10). A :class:`ChaseClock` keeps the chase's
position ``p(t)``, in steps, as a pure function of time between events: a
*step boundary* occurs each time it crosses an integer.

* Hz: ``p(t) = p0 + rate · (t − t0)``;
* BPM: ``p(t) = p0 + rate · (beats(t) − b0)``, with the speed master's beat
  count, so a ``SET_BPM`` moves the boundaries without touching the clock.

A rate change *rebases* an Hz clock, so the position never jumps. A BPM clock
*aligns* instead (:meth:`ChaseClock.align`): it picks the position nearest
the current one from which the boundaries fall on the master's beat grid,
and never goes back a step. Activation, taps and rate changes all align.

**Cue order** is separate from the position: :class:`CueOrder` picks the cue
each boundary (or GO, BACK) moves to, by direction. ``random`` draws from a
generator seeded with the playback id and its activation number, so a show
plays the same "random" chase on every run.

**Rate faders** (decision 12) scale the rate by :func:`rate_factor`; a BPM
chase uses :func:`beat_factor`, the same factor rounded to a power of two,
so it stays on the beat grid.

The playback runtime (:mod:`busk.engine.playback_runtime`) owns a
:class:`ChaseRuntime` while a chase list plays, fires its boundaries as due
events (decision 2) and retargets the slots at each one.
"""

from __future__ import annotations

import math
import random
import zlib
from typing import Final, Literal

from busk.compiler.playbacks import CompiledChase
from busk.engine.masters import SpeedMasterRuntime
from busk.model.common import PlaybackId

type Direction = Literal["forward", "reverse", "bounce", "random"]

RATE_RANGE: Final = 4.0
"""A ``rate`` fader scales a chase's rate from ×¼ (at 0) to ×4 (at 1)."""


def _round(x: float) -> int:
    """``x`` to the nearest integer, halves up: one rule for every rounding here."""
    return math.floor(x + 0.5)


def rate_factor(level: float) -> float:
    """The factor a ``rate`` fader at ``level`` applies to an Hz chase:
    4^(2·level − 1), so ×¼ at 0, ×1 at 0.5 (the fader's resting level) and
    ×4 at 1 (decision 12)."""
    return math.pow(RATE_RANGE, 2.0 * level - 1.0)


def beat_factor(level: float) -> float:
    """:func:`rate_factor` rounded to a power of two, for a BPM chase: ×¼, ×½,
    ×1, ×2 or ×4, so its steps stay on the beat grid (decision 12)."""
    return 2.0 ** _round(4.0 * level - 2.0)


def chase_seed(playback: PlaybackId, activation: int) -> int:
    """The seed of a ``random`` chase: ``crc32(playbackId) · 2³² + activationSeq``."""
    return zlib.crc32(playback.encode()) * 2**32 + activation


def grid_position(
    master: SpeedMasterRuntime, rate: float, now: float, p_ref: float
) -> tuple[float, float]:
    """The beat-grid position nearest ``p_ref`` for a clock running at
    ``rate`` cycles (or steps) per beat of ``master``, and the master's beat
    count at ``now``. Chase clocks and effect clocks
    (:class:`busk.engine.effects.EffectClock`) share the rule.

    With ``B`` the beat count, ``m`` the rate and ``g = min(m, 1)``::

        p0 = m·B + g·round((p_ref − m·B) / g)

    A clock at ``p0`` now, moving ``m`` per beat, crosses whole numbers on
    beats and their subdivisions for ``m ≥ 1``, and on every ``1/m``-th whole
    beat for ``m < 1``. ``p0`` is at most ``g/2`` from ``p_ref``; halves
    round up.
    """
    beats = master.beats(now)
    g = min(rate, 1.0)
    return rate * beats + g * _round((p_ref - rate * beats) / g), beats


class ChaseClock:
    """A chase's position in steps, and its step boundaries (phase-4-plan §5.7).

    ``done`` is the last boundary already processed: the boundaries still
    to come are ``done + 1, done + 2, …``. With a speed ``master`` the clock
    is BPM-locked and ``rate`` is in steps per beat; without one it runs in
    steps per second.
    """

    __slots__ = ("b0", "done", "master", "p0", "rate", "t0")

    def __init__(self, now: float, rate: float, master: SpeedMasterRuntime | None = None) -> None:
        """Start at ``now``. An Hz clock starts at position 0, so its first
        boundary is one step away. A BPM clock aligns to the beat grid at the
        position nearest 0, and counts the boundary nearest that as done, so
        its first boundary is between half a step and one and a half steps
        away (decision 11)."""
        self.master = master
        self.rate = rate
        self.t0 = now
        self.b0 = 0.0
        self.p0 = 0.0
        if master is not None:
            self.p0, self.b0 = grid_position(master, rate, now, 0.0)
        self.done = math.floor(self.p0 + 0.5)

    def position(self, t: float) -> float:
        """The position at time ``t``, in steps."""
        if self.master is None:
            return self.p0 + self.rate * (t - self.t0)
        return self.p0 + self.rate * (self.master.beats(t) - self.b0)

    def boundary_time(self, k: int) -> float:
        """When the position reaches ``k``. A BPM clock inverts the master's
        current tempo, which is exact for every boundary not yet fired: tempo
        changes are commands, and due boundaries fire before commands
        (decision 2)."""
        if self.master is None:
            return self.t0 + (k - self.p0) / self.rate
        return self.master.time_of(self.b0 + (k - self.p0) / self.rate)

    def step_seconds(self) -> float:
        """The length of one step now, in seconds."""
        if self.master is None:
            return 1.0 / self.rate
        return 60.0 / (self.master.bpm * self.rate)

    def last_due(self, until: float) -> int:
        """The last boundary due by ``until``: the largest ``k`` whose time is
        at or before it, or :attr:`done` if none is. Boundaries are compared
        as times, so a boundary due exactly at a tick fires on that tick."""
        k = max(self.done, math.floor(self.position(until)))
        while self.boundary_time(k + 1) <= until:
            k += 1
        while k > self.done and self.boundary_time(k) > until:
            k -= 1
        return k

    def rebase(self, now: float, rate: float) -> None:
        """An Hz clock's new rate from ``now`` on; the position is continuous."""
        self.p0 = self.position(now)
        self.t0 = now
        self.rate = rate

    def align(self, now: float, rate: float, p_ref: float) -> bool:
        """Re-align a BPM clock at ``now`` to the beat grid, at ``rate`` steps
        per beat, near the position ``p_ref`` (decision 11): after a tap,
        ``p_ref`` is the position before the master's phase moved; after a
        rate change, the position under the old rate.

        The new position is the grid position nearest ``p_ref``, but never
        before ``floor(p_ref)``: the chase never goes back a step. If that
        lands past the last boundary processed, the chase owes a step now:
        :attr:`done` moves on and the method returns ``True``.
        """
        self.rate = rate
        assert self.master is not None
        p0, self.b0 = grid_position(self.master, rate, now, p_ref)
        floor_ref = math.floor(p_ref)
        if p0 < floor_ref:  # the next grid position instead: on the grid, not back
            g = min(rate, 1.0)
            p0 += g * math.ceil((floor_ref - p0) / g)
        self.p0 = p0
        if math.floor(p0) > self.done:
            self.done = math.floor(p0)
            return True
        return False


class CueOrder:
    """Which cue a chase moves to, by direction (decision 10).

    ============  ============================================  ====================
    Direction     Step (a boundary, GO)                         BACK
    ============  ============================================  ====================
    ``forward``   the next cue, wrapping                        the previous cue
    ``reverse``   the previous cue, wrapping; starts at the     the next cue
                  last cue
    ``bounce``    on in its direction, turning at either end    one step against its
                                                                direction
    ``random``    a draw from the other cues: never the same    a draw, as a step
    ============  ============================================  ====================

    A one-cue chase stays put. A ``random`` chase has no order to step back
    in, so BACK draws too.
    """

    __slots__ = ("count", "direction", "heading", "random")

    def __init__(self, direction: Direction, count: int, seed: int) -> None:
        self.direction = direction
        self.count = count
        self.heading = 1  # bounce: +1 up the list, −1 down
        self.random = random.Random(seed)

    def first(self) -> int:
        """The cue a chase starts at: the last one for ``reverse``, else the first."""
        return self.count - 1 if self.direction == "reverse" else 0

    def step(self, cue: int) -> int:
        """The cue after ``cue``: a boundary or a GO."""
        n = self.count
        if n <= 1:
            return cue
        if self.direction == "forward":
            return (cue + 1) % n
        if self.direction == "reverse":
            return (cue - 1) % n
        if self.direction == "bounce":
            if not 0 <= cue + self.heading < n:
                self.heading = -self.heading
            return cue + self.heading
        return self._draw(cue)

    def peek(self, cue: int) -> int | None:
        """The cue :meth:`step` would move to from ``cue``, without moving (a
        bounce does not turn): what the snapshot shows as ``next``. ``None``
        for a ``random`` chase, whose next cue is not drawn yet."""
        n = self.count
        if n <= 1:
            return cue
        if self.direction == "random":
            return None
        if self.direction == "bounce":
            heading = self.heading if 0 <= cue + self.heading < n else -self.heading
            return cue + heading
        return (cue + (1 if self.direction == "forward" else -1)) % n

    def back(self, cue: int) -> int:
        """The cue before ``cue``: a BACK."""
        n = self.count
        if n <= 1:
            return cue
        if self.direction == "forward":
            return (cue - 1) % n
        if self.direction == "reverse":
            return (cue + 1) % n
        if self.direction == "bounce":
            after = cue - self.heading
            return after if 0 <= after < n else cue + self.heading
        return self._draw(cue)

    def _draw(self, cue: int) -> int:
        """A uniform draw from every cue but ``cue``."""
        drawn = self.random.randrange(self.count - 1)
        return drawn if drawn < cue else drawn + 1


class ChaseRuntime:
    """A playing chase: its settings, :class:`ChaseClock` and :class:`CueOrder`.

    ``level`` is the playback's ``rate`` fader level, or ``None`` when its
    fader is not a ``rate`` fader. The rate is in steps per second for an Hz
    chase, and in steps per beat for a BPM one: ``multiplier`` × the
    master's step multiplier × :func:`beat_factor`.
    """

    __slots__ = ("clock", "master", "order", "settings")

    def __init__(
        self,
        settings: CompiledChase,
        master: SpeedMasterRuntime | None,
        level: float | None,
        count: int,
        seed: int,
        now: float,
    ) -> None:
        self.settings = settings
        self.master = master
        self.order = CueOrder(settings.direction, count, seed)
        self.clock = ChaseClock(now, self.rate(level), master)

    def rate(self, level: float | None) -> float:
        """The chase's rate with its ``rate`` fader at ``level`` (``None``: no
        rate fader)."""
        settings = self.settings
        if self.master is None:
            return settings.hz * (1.0 if level is None else rate_factor(level))
        factor = 1.0 if level is None else beat_factor(level)
        return settings.multiplier * self.master.multiplier * factor

    def crossfade(self) -> float:
        """How long a step fades in now: ``crossfade`` × the step length."""
        return self.settings.crossfade * self.clock.step_seconds()

    def rerate(self, now: float, level: float | None) -> bool:
        """Follow a rate change at ``now`` (the rate fader, the master's
        step): an Hz clock rebases, a BPM clock aligns at its current
        position. Returns whether the chase owes a step now."""
        rate = self.rate(level)
        clock = self.clock
        if rate == clock.rate:
            return False
        if self.master is None:
            clock.rebase(now, rate)
            return False
        return clock.align(now, rate, clock.position(now))
