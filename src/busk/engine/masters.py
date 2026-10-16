"""Group and grand masters and blackout (spec §12, stages 9–10), and speed
masters (§11.3).

All three act on the **working frame**, which the resolver rebuilds from
scratch every tick, and never on runtime state. Releasing blackout or
raising a master therefore returns exactly to the live look (§2.8,
"non-destructive masters").

* **Group masters** (§12 step 1, phase-5-plan §5.8): each intensity lane ×
  the product of the levels of the group masters whose group holds its
  target. The per-lane product (:func:`group_factor`) is computed when a
  level or the show changes, never per tick.
* **Grand master**: then every intensity lane × the product of the grand
  masters' levels (a show normally has one; with several, their levels
  multiply).
* **Blackout**: every intensity lane → 0, flashes and override bands
  included. No source can outrank it: masters are fixed stages, not bands
  (§7.2). Since Phase 7 the engine passes ``blackout=False`` here and the
  safety stage (:mod:`busk.engine.safety`) applies blackout, after park
  has forced its intensities (phase-7-plan decision 11).

**Speed masters** (:class:`SpeedMasterRuntime`) are tempo sources, not
frame stages: each keeps a beat count that BPM-locked chases (and, from
Phase 5, effects) follow.

**Fade-time masters** (§5.13 "global fade override", phase-6-plan decision
12) are not frame stages either: while one is above 0, every playback
transition that *starts* takes :func:`fade_override`'s time instead of its
programmed timing. The engine keeps the current override in a
:class:`FadeOverride` that every playback runtime shares.
"""

from __future__ import annotations

import itertools
import math
import statistics
from collections.abc import Iterable, Mapping
from typing import Final

import numpy as np
from numpy.typing import NDArray

from busk.compiler.playbacks import CompiledMaster
from busk.model.common import MasterId
from busk.model.master import MAX_BPM

TAP_RUN: Final = 8
"""Taps kept per run: the tempo is the average of their intervals (decision 11)."""
TAP_GAP: Final = 2.0
"""Seconds: a tap longer than this after the previous one starts a new run."""
TAP_TOLERANCE: Final = 0.25
"""Intervals further than this fraction from the run's median are dropped."""
FADE_TIME_FULL: Final = 10.0
"""Seconds: the fade time of a fade-time master at full (decision 12)."""


def grand_master_level(levels: Iterable[float]) -> float:
    """The combined level of the grand masters: the product of their levels, 1 without any."""
    return math.prod(levels)


def fade_override(
    masters: Mapping[MasterId, CompiledMaster], levels: Mapping[MasterId, float]
) -> float | None:
    """The fade time that replaces programmed timing, or ``None`` when no
    fade-time master is up.

    It is ``FADE_TIME_FULL × level²`` for the highest level among the
    fade-time masters of ``masters`` (a knob at 30 % gives 0.9 s, at 50 %
    2.5 s); the square gives short times room at the bottom of the travel.
    A master without a level in ``levels`` counts as down.
    """
    up = [levels.get(master.id, 0.0) for master in masters.values() if master.kind == "fadeTime"]
    level = max(up, default=0.0)
    return FADE_TIME_FULL * level * level if level > 0.0 else None


class FadeOverride:
    """The current fade-time override, shared by the engine and every
    playback runtime (as the speed masters and size levels are). ``time``
    is ``None`` while no fade-time master is up. Only the engine thread
    writes it, on a fade-time master's ``SET_MASTER`` and on a live swap."""

    __slots__ = ("time",)

    def __init__(self) -> None:
        self.time: float | None = None


def group_factor(
    masters: Mapping[MasterId, CompiledMaster],
    levels: Mapping[MasterId, float],
    count: int,
) -> NDArray[np.float64] | None:
    """The group masters' factor for each of ``count`` intensity lanes (in
    ``intensityLanes`` order), or ``None`` when no group master scales
    anything: every level is 1, or no group master has a member to scale.

    Each lane's factor is the product of the ``levels`` of the group
    masters among ``masters`` whose ``positions`` hold it; a group master
    without a level counts as 1. The levels multiply in show order.
    """
    factor: NDArray[np.float64] | None = None
    for master in masters.values():
        level = levels.get(master.id, 1.0)
        if master.kind != "group" or level == 1.0 or not master.positions:
            continue
        if factor is None:
            factor = np.ones(count, dtype=np.float64)
        factor[np.array(master.positions, dtype=np.intp)] *= level
    return factor


def apply_masters(
    frame: NDArray[np.float64],
    intensity: NDArray[np.intp],
    grand_master: float,
    blackout: bool,
    group: NDArray[np.float64] | None = None,
) -> None:
    """Stages 9–10 on the logical ``frame``: scale its ``intensity`` lanes by
    the ``group`` factor (:func:`group_factor`, one per lane) and then by
    ``grand_master``, or zero them when ``blackout`` is on. At full levels
    with no blackout the frame is not touched."""
    if blackout:
        frame[intensity] = 0.0
        return
    if group is not None:
        frame[intensity] *= group
    if grand_master != 1.0:
        frame[intensity] *= grand_master


class SpeedMasterRuntime:
    """A speed master's tempo, beat count and multiplier step (§11.3,
    phase-4-plan decision 11 and §5.8). Owned by the engine thread.

    The beat count is a pure function of time between events (decision 1)::

        beats(t) = B0 + bpm / 60 · (t − T0)

    Events rebase it: :meth:`set_bpm` keeps the phase (``B0 := beats(t)``),
    and every :meth:`tap` moves it to the nearest whole beat. Nothing is
    integrated per tick, so the count does not depend on the tick schedule.

    The *level* (0..1, ``SET_MASTER``) selects one of the master's
    ``multiplierSteps`` (:meth:`CompiledMaster.multiplier
    <busk.compiler.playbacks.CompiledMaster.multiplier>`); the chases that
    follow the master multiply their rate by it.
    """

    __slots__ = ("B0", "T0", "bpm", "level", "master", "multiplier", "taps")

    def __init__(self, master: CompiledMaster, now: float) -> None:
        """Start counting at beat 0 at ``now``, at the master's default tempo
        and initial level."""
        self.master = master
        self.bpm = master.defaultBpm
        self.T0 = now
        self.B0 = 0.0
        self.taps: list[float] = []  # the current run, at most TAP_RUN taps
        self.level = master.initialLevel
        self.multiplier = master.multiplier(self.level)

    def beats(self, t: float) -> float:
        """The beat count at time ``t``."""
        return self.B0 + self.bpm / 60.0 * (t - self.T0)

    def time_of(self, beats: float) -> float:
        """The time the beat count reaches ``beats``, at the current tempo.

        Exact for any time after the last event: the tempo only changes at
        commands, which come after every due boundary (decision 2).
        """
        return self.T0 + (beats - self.B0) * 60.0 / self.bpm

    def set_bpm(self, t: float, bpm: float) -> None:
        """``SET_BPM`` at time ``t``: a new tempo from the current phase on."""
        self.B0 = self.beats(t)
        self.T0 = t
        self.bpm = bpm

    def set_level(self, level: float) -> None:
        """``SET_MASTER``: the level and the multiplier step it selects."""
        self.level = level
        self.multiplier = self.master.multiplier(level)

    def tap(self, t: float) -> None:
        """``TAP`` at time ``t`` (decision 11).

        * A tap more than :data:`TAP_GAP` after the previous one starts a new
          run; a tap at the same time as the previous one (a double trigger)
          is ignored.
        * From the second tap of a run on, the tempo is 60 over the mean of
          the intervals of the run's last :data:`TAP_RUN` taps, keeping those
          within :data:`TAP_TOLERANCE` of their median, or over the last
          interval if none is kept. It is capped at
          :data:`~busk.model.master.MAX_BPM`.
        * Every tap moves the phase to the nearest whole beat, counted under
          the tempo before the tap: the tap lands on a beat.
        """
        taps = self.taps
        if taps and t <= taps[-1]:
            return
        if taps and t - taps[-1] > TAP_GAP:
            taps.clear()
        taps.append(t)
        del taps[:-TAP_RUN]
        beat = math.floor(self.beats(t) + 0.5)  # halves round up, as levels do
        if len(taps) >= 2:
            intervals = [b - a for a, b in itertools.pairwise(taps)]
            median = statistics.median(intervals)
            kept = [i for i in intervals if abs(i - median) <= TAP_TOLERANCE * median]
            interval = statistics.fmean(kept) if kept else intervals[-1]
            self.bpm = min(60.0 / interval, MAX_BPM)
        self.B0 = float(beat)
        self.T0 = t

    def rebind(self, master: CompiledMaster) -> None:
        """Follow a live edit of the master: tempo, phase and level are kept,
        and the level selects a step of the edited ``multiplierSteps``."""
        self.master = master
        self.set_level(self.level)


def speed_masters(
    masters: Iterable[CompiledMaster],
    now: float,
    running: dict[MasterId, SpeedMasterRuntime] | None = None,
) -> dict[MasterId, SpeedMasterRuntime]:
    """A runtime for every speed master among ``masters``, in order.

    A master already ``running`` (same id, before a live edit) keeps its
    runtime, rebound to its edited settings; a new one starts counting at
    ``now`` (§5.8).
    """
    runtimes: dict[MasterId, SpeedMasterRuntime] = {}
    for master in masters:
        if master.kind != "speed":
            continue
        runtime = None if running is None else running.get(master.id)
        if runtime is None:
            runtime = SpeedMasterRuntime(master, now)
        else:
            runtime.rebind(master)
        runtimes[master.id] = runtime
    return runtimes
