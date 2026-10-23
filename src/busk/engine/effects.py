"""Running effects: clocks, runtimes and banks (spec §10, phase-5-plan §5.4–5.5).

An effect *instance* runs as an :class:`EffectRuntime`: one clock, and one
or more *versions* (compiled forms) mixed by their presence. The effects of
one source (a playback's main or flash, or the programmer) form an
:class:`EffectBank`, which follows that source's cue changes.

Effect clocks
-------------
An :class:`EffectClock` keeps a running instance's *position* ``P(t)``, in
cycles, as a pure function of time between events (decision 1):

* Hz: ``P(t) = p0 + rate·(t − t0)``, ``rate`` in cycles per second;
* BPM: ``P(t) = p0 + rate·(beats(t) − b0) + nudge(t)``, ``rate`` in cycles
  per beat of the speed master, so a ``SET_BPM`` moves the effect with the
  beat count without touching the clock.

**Beat lock** (decision 2). A BPM clock starts on its master's grid, at the
grid position nearest 0 (:func:`busk.engine.chase.grid_position`, the rule
chases use). A tap moves the master's phase, and a rate change moves the
grid: both *align* the clock to the grid position nearest where it is. The
difference ``e`` is not applied at once. It decays linearly to 0 over
:data:`NUDGE_BEATS` beats of the master::

    nudge(t) = e · max(0, 1 − (beats(t) − errorBeat) / NUDGE_BEATS)

so ``P`` is continuous at the event, and one beat later the effect is
exactly on the grid. ``|e|`` is at most half a grid step, less than the
distance the clock covers in a beat, so ``P`` never runs backwards. An Hz
clock *rebases* on a rate change instead, and ignores taps.

**Rates** (decision 14 and 15). :func:`tempo` gives an effect's rate and the
master it locks to:

* BPM: ``multiplier`` × the master's multiplier step × :func:`~busk.engine.
  chase.beat_factor` of the playback's ``rate`` fader;
* Hz: ``hz`` × :func:`~busk.engine.chase.rate_factor` of the ``rate`` fader
  × the step of ``speedMasterId``, if any. The clock does not lock to that
  master: only its step matters.

**The strobe cap** (phase-7-plan decision 13, §5.11). With
``safety.strobeMaxHz`` set (a :class:`StrobeCap` shared by every bank), an
effect with an intensity layer flashes no faster than the cap: its rate ×
the largest :func:`flashes_per_cycle` of its intensity layers. An Hz rate
is clamped; a BPM rate halves its cycles per beat until it is under the
cap, so it stays on the beat grid. The capped rate depends on the master's
tempo, so ``SET_BPM`` and taps re-rate the banks while a cap is set (the
re-rate is the usual align-and-nudge, so nothing jumps). Effects without an
intensity layer, and chases, are never capped.

Versions and presence
---------------------
A running instance keeps a :class:`Version` per compiled form it has had,
newest last, each with a presence :class:`~busk.engine.fades.Envelope`
(decision 9). :meth:`EffectBank.retarget` moves a bank to a cue's
instances, by ``key``:

* **enter** (a key not running): a new clock, and a version fading in over
  ``sizeFadeIn``, else with :attr:`EffectTiming.change` (the cue's in
  timing);
* **leave** (a running key the cue lacks): every version fades out with
  :attr:`EffectTiming.leave` (the cue's out timing). The effect keeps moving
  while it fades;
* **change** (same key, another compiled form): the new version fades in,
  and the older ones out, with :attr:`EffectTiming.change`, on the **same
  clock**, which follows the new version's rate.

Per lane, the versions' outputs are averaged weighted by presence, and the
lane's weight is ``min(1, Σ presence)``, so a change of size is an exact
morph of the amplitude. With one version (the steady state) the outputs are
used as they are and the presence goes into the scalar weights: no
per-lane weights exist.

Only the newest version of a current instance fades towards 1; every other
version fades towards 0, and a retarget sends any that does not on its way
out.

Manual transitions (phase-6-plan §5.6)
--------------------------------------
A ``crossfade`` fader drives a transition by hand: its presences follow a
virtual clock (the ``fadeAt`` of :meth:`EffectBank.update`) while the
effects keep moving in real time. When the fader lets go of a transition
(a button took it over, or it completed), :meth:`EffectBank.hold` stops
every presence at its value on that clock, so the bank can go back to real
time without a jump.

Outputs (decisions 6 and 12)
----------------------------
Each tick :meth:`EffectRuntime.update` evaluates every layer of every
version at its members' phases ``φ = b + phase``, where ``b`` is the
clock's position mapped by the effect's direction (:func:`base_phase`). The
*dynamics* ``d`` are the size master's level × the owner's ``size`` fader
(:class:`EffectScalars`).

* **Absolute** layers fill the runtime's :attr:`~EffectRuntime.source`:
  intensity as HTP positions, other scalars and colour ``r, g, b`` as LTP
  lanes, colour extras as snap lanes held at ``NaN`` ("derive") that switch
  at half presence. Dynamics scale their presence: the HTP weight is
  ``env × presence × d`` (times the owner's ``intensityScale``), the LTP
  weight ``ltpWeight × presence × d``.
* **Relative** layers fill one :class:`~busk.engine.contributions.Relative`
  each, with ``d`` in the amount: ``add`` gives ``size·d·(2w − 1)``,
  ``multiply`` ``1 − size·d·(1 − w)``. Their weight is the owner's weight
  for that kind of lane (``env × intensityScale`` on intensity,
  ``ltpWeight`` otherwise) × presence.

The runtime's source is a contributor of its bank's band with one number,
:attr:`EffectRuntime.seq` (decision 10); a runtime with only relative
layers has an absent source.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from typing import Final

import numpy as np
from numpy.typing import NDArray

from busk.compiler.cues import CompiledCue, SlotTiming
from busk.compiler.effects import CompiledEffect, CompiledLayer, EffectDirection
from busk.engine.chase import beat_factor, grid_position, rate_factor
from busk.engine.contributions import Origin, Relative, Source
from busk.engine.curves import curve_of
from busk.engine.fades import Envelope, SeqRule, Timing, distinct
from busk.engine.masters import SpeedMasterRuntime
from busk.engine.waveforms import evaluate
from busk.model.common import MasterId

NUDGE_BEATS: Final = 1.0
"""Beats over which a BPM clock closes the gap to its grid after an event."""


_CAP_SLACK: Final = 1.0 + 1e-9
"""A BPM rate exactly at the cap is allowed, even when the tempo carries
rounding (a tap at 1/3 s is 180.00000000000003 BPM)."""


class StrobeCap:
    """The show's strobe-rate cap (``safety.strobeMaxHz``), shared by every
    effect bank as the speed masters are. ``hz`` is ``None`` while the show
    sets no cap. Only the engine thread writes it, at start and on a live
    swap (before the playbacks rebind, so their re-rate sees it)."""

    __slots__ = ("hz",)

    def __init__(self, hz: float | None = None) -> None:
        self.hz = hz


def flashes_per_cycle(layer: CompiledLayer) -> int:
    """How often ``layer``'s wave flashes in one cycle (decision 13).

    Every waveform flashes once, except ``step``, which counts its rises
    (cyclically: a last step below the first rises at the cycle boundary),
    and ``curve``, which counts its peaks (plateaus count once). A wave that
    never changes flashes 0 times. A layer without a wave (colour) has 0.
    """
    wave = layer.wave
    if wave is None:
        return 0
    if wave.kind == "step":
        steps = wave.steps
        return int(np.count_nonzero(steps > np.roll(steps, 1)))
    if wave.kind == "curve":
        # The extended points close the period on values already in it, so
        # their cyclic sequence, with runs of equal values merged, has the
        # curve's peaks as its local maxima.
        ys = [float(y) for y in wave.ys]
        merged = [y for i, y in enumerate(ys) if y != ys[i - 1]] or ys[:1]
        if len(merged) < 2:
            return 0
        n = len(merged)
        return sum(1 for i, y in enumerate(merged) if y > merged[i - 1] and y > merged[(i + 1) % n])
    return 1


def _effect_flashes(effect: CompiledEffect) -> int:
    """The largest flash count of ``effect``'s intensity layers (0: none)."""
    return max(
        (flashes_per_cycle(layer) for layer in effect.layers if layer.attribute == "intensity"),
        default=0,
    )


def tempo(
    effect: CompiledEffect,
    speed: Mapping[MasterId, SpeedMasterRuntime],
    level: float | None,
    cap: float | None = None,
) -> tuple[float, SpeedMasterRuntime | None]:
    """The rate of ``effect`` and the speed master its clock locks to.

    ``speed`` holds the running speed masters and ``level`` is the
    playback's ``rate`` fader level, ``None`` without one. A BPM effect runs
    in cycles per beat of its master; an Hz effect in cycles per second,
    with no master to lock to. ``cap`` is the strobe cap in flashes per
    second (see the module docs), ``None`` for none.
    """
    flashes = 0 if cap is None else _effect_flashes(effect)
    if effect.rate == "bpm":
        assert effect.masterId is not None
        master = speed[effect.masterId]
        factor = 1.0 if level is None else beat_factor(level)
        rate = effect.multiplier * master.multiplier * factor
        if flashes and cap is not None:
            per_beat = master.bpm / 60.0 * flashes  # flashes per second at 1 cycle per beat
            while rate * per_beat > cap * _CAP_SLACK:
                rate /= 2.0
        return rate, master
    factor = 1.0 if level is None else rate_factor(level)
    if effect.speedMasterId is not None:
        factor *= speed[effect.speedMasterId].multiplier
    rate = effect.hz * factor
    if flashes and cap is not None:
        rate = min(rate, cap / flashes)
    return rate, None


class EffectClock:
    """A running effect's position ``P(t)``, in cycles (decisions 1–2).

    With a speed ``master`` the clock is BPM-locked and ``rate`` is in
    cycles per beat; without one it runs at ``rate`` cycles per second.
    ``error`` is the nudge still to close since beat ``errorBeat``.
    """

    __slots__ = ("b0", "error", "errorBeat", "master", "p0", "rate", "t0")

    def __init__(self, now: float, rate: float, master: SpeedMasterRuntime | None = None) -> None:
        """Start at ``now``: an Hz clock at position 0, a BPM clock at the
        grid position nearest 0, without a nudge (presence fades the effect
        in, so where it starts never shows as a jump)."""
        self.master = master
        self.rate = rate
        self.t0 = now
        self.p0 = 0.0
        self.b0 = 0.0
        self.error = 0.0
        self.errorBeat = 0.0
        if master is not None:
            self.p0, self.b0 = grid_position(master, rate, now, 0.0)

    def position(self, t: float) -> float:
        """The position at time ``t``, in cycles."""
        master = self.master
        if master is None:
            return self.p0 + self.rate * (t - self.t0)
        beats = master.beats(t)
        position = self.p0 + self.rate * (beats - self.b0)
        if self.error:
            left = 1.0 - (beats - self.errorBeat) / NUDGE_BEATS
            if left > 0.0:
                position += self.error * left
        return position

    @property
    def hz(self) -> float:
        """The rate in cycles per second: a BPM clock's at its master's tempo
        now (a nudge in progress left out)."""
        master = self.master
        return self.rate if master is None else self.rate * master.bpm / 60.0

    def align(self, now: float, p_ref: float) -> None:
        """Re-align a BPM clock at ``now`` to its master's grid, near the
        position ``p_ref``: after a tap, the position before the master's
        phase moved; after a rate change, the position under the old rate.

        The clock moves to the grid position nearest ``p_ref`` and nudges
        the difference away over :data:`NUDGE_BEATS`, so ``P(now) = p_ref``.
        """
        master = self.master
        assert master is not None
        self.p0, self.b0 = grid_position(master, self.rate, now, p_ref)
        self.error = p_ref - self.p0
        self.errorBeat = self.b0

    def rerate(self, now: float, rate: float, master: SpeedMasterRuntime | None) -> None:
        """Run at ``rate``, locked to ``master`` (``None``: Hz), from ``now`` on.

        The position is continuous: an Hz clock rebases at its current
        position, a BPM clock aligns there (a nudge). A newer version of an
        instance may switch between Hz and BPM, or to another master, the
        same way. The same rate on the same master changes nothing, so a
        nudge in progress runs on.
        """
        if rate == self.rate and master is self.master:
            return
        position = self.position(now)
        self.rate = rate
        self.master = master
        if master is None:
            self.p0 = position
            self.t0 = now
            self.error = 0.0
        else:
            self.align(now, position)


# -- timing and scalars --------------------------------------------------------


def timing_of(timing: SlotTiming) -> Timing:
    """A cue's :class:`~busk.compiler.cues.SlotTiming` as a fade
    :class:`~busk.engine.fades.Timing`."""
    return Timing(duration=timing.fade, delay=timing.delay, curve=curve_of(timing.curve))


@dataclass(frozen=True, slots=True)
class EffectTiming:
    """How the instances of one retarget fade (decision 9, phase-5-plan §5.5).

    ``change`` is the timing of entering and changed instances, ``leave``
    that of leaving ones. An instance with a ``sizeFadeIn`` enters over that
    (linear, no delay) instead.

    ==========================  =====================  ===============  ===============
    Built with                  enter                  change           leave
    ==========================  =====================  ===============  ===============
    :meth:`of_cue` (a cue)      ``sizeFadeIn``, else   its in timing    its out timing
                                its in timing
    :meth:`uniform` (``t``)     ``sizeFadeIn``, else   ``t``            ``t``
                                ``t``
    ==========================  =====================  ===============  ===============

    :meth:`uniform` is for chase steps (the step cross-fade), the
    programmer (its fade time) and a fade-time master's override (Phase 6).
    """

    change: Timing
    leave: Timing

    @classmethod
    def of_cue(cls, cue: CompiledCue) -> EffectTiming:
        """The timing of a move to ``cue``: its in and out timing."""
        return cls(timing_of(cue.inTiming), timing_of(cue.outTiming))

    @classmethod
    def uniform(cls, timing: Timing) -> EffectTiming:
        """One timing for everything (``sizeFadeIn`` still applies)."""
        return cls(timing, timing)

    def enter(self, effect: CompiledEffect) -> Timing:
        """The timing ``effect`` enters with."""
        if effect.sizeFadeIn is not None:
            return Timing(duration=effect.sizeFadeIn)
        return self.change


def _no_levels() -> dict[MasterId, float]:
    return {}


@dataclass(slots=True)
class EffectScalars:
    """What a bank's owner contributes to its effects this tick (decision 12).

    ``htpWeight`` is the owner's HTP presence (a playback's envelope),
    ``intensityScale`` its intensity scale (a ``master`` fader, a flash
    level) and ``ltpWeight`` its LTP weight. ``size`` is its ``size`` fader
    level (1 without one) and ``sizeLevels`` the size masters' levels,
    shared and read live.
    """

    htpWeight: float = 1.0
    intensityScale: float = 1.0
    ltpWeight: float = 1.0
    size: float = 1.0
    sizeLevels: Mapping[MasterId, float] = field(default_factory=_no_levels)

    def dynamics(self, effect: CompiledEffect) -> float:
        """``d`` for ``effect``: its size master's level × the ``size`` fader."""
        if effect.sizeMasterId is None:
            return self.size
        return self.sizeLevels.get(effect.sizeMasterId, 1.0) * self.size


def base_phase(direction: EffectDirection, position: float) -> float:
    """The base phase ``b`` at clock position ``position`` (decision 4):
    ``P`` forward, ``−P`` in reverse, and for ``bounce`` a triangle of
    period 2, up for one cycle and back down the next."""
    if direction == "forward":
        return position
    if direction == "reverse":
        return -position
    folded = position % 2.0
    return folded if folded <= 1.0 else 2.0 - folded


# -- runtimes ------------------------------------------------------------------


@dataclass(slots=True)
class Version:
    """One compiled form of a running instance, and its presence: rising
    to 1 while it enters, falling to 0 while it leaves or is replaced."""

    effect: CompiledEffect
    presence: Envelope = field(default_factory=Envelope)


_SNAP_AT: Final = 0.5
"""The presence at which a colour layer's extras switch to "derive"."""
_ORDER_BITS: Final = 16
"""A relative's ``order`` is its runtime's place ≪ this, plus its place in the runtime."""


def palette_colours(
    palette: NDArray[np.float64], phase: NDArray[np.float64], snap: bool, out: NDArray[np.float64]
) -> None:
    """A palette cycle, row by row: at phase position ``φ`` (``p = φ −
    floor(φ)``), position ``x = p·K`` among the row's ``K`` colours, holding
    colour ``floor(x)`` (snap) or blending it into the next, wrapping to the
    first (fade). ``palette`` has shape ``(rows, K, 3)``, ``phase`` one
    position per row, and ``out`` gets one ``r, g, b`` per row."""
    count = palette.shape[1]
    position = (phase - np.floor(phase)) * count
    index = np.minimum(np.floor(position).astype(np.intp), count - 1)  # p can round to 1
    rows = np.arange(palette.shape[0])
    if snap:
        out[:] = palette[rows, index]
        return
    blend = (position - index)[:, None]
    here, after = palette[rows, index], palette[rows, (index + 1) % count]
    out[:] = here + (after - here) * blend


class _Part:
    """One layer of one version, writing into a channel at ``at`` (positions
    in the channel's lanes, row by row; three per row for a colour layer),
    with scratch arrays for its phases and outputs."""

    __slots__ = ("at", "layer", "out", "phase", "version")

    def __init__(self, version: int, layer: CompiledLayer, at: NDArray[np.intp]) -> None:
        self.version = version
        self.layer = layer
        self.at = at
        self.phase = np.empty(layer.member.size)
        self.out = np.empty(at.size)

    def evaluate(self, base: float, size: float) -> None:
        """Fill :attr:`out` with the layer's output at base phase ``base``:
        values for an absolute layer, amounts (``size`` = size × d) for a
        relative one."""
        layer, out = self.layer, self.out
        np.add(layer.phase, base, out=self.phase)
        if layer.palette is not None:
            palette_colours(layer.palette, self.phase, layer.blend == "snap", out.reshape(-1, 3))
            return
        assert layer.wave is not None
        evaluate(layer.wave, self.phase, layer.member, out)
        if layer.mode == "absolute":  # lerp(low, high, w)
            out *= layer.high - layer.low
            out += layer.low
        elif layer.mode == "add":  # size·d·(2w − 1)
            out *= 2.0 * size
            out -= size
        else:  # multiply: 1 − size·d·(1 − w)
            out *= size
            out += 1.0 - size


type _Rows = tuple[int, CompiledLayer, NDArray[np.intp]]
"""A layer of version ``v``, and the lanes it writes in a channel, flattened."""


class _Channel:
    """The lanes one kind of output writes, over every version: ``lanes``
    ascending and distinct, ``values`` refilled per tick, and ``weights`` per
    lane while several versions mix (``None`` with one)."""

    __slots__ = ("lanes", "parts", "values", "weights")

    def __init__(self, parts: list[_Rows], mixed: bool) -> None:
        flat = [lanes for _, _, lanes in parts]
        self.lanes = distinct(np.concatenate(flat)) if flat else np.zeros(0, dtype=np.intp)
        self.parts = [
            _Part(version, layer, np.searchsorted(self.lanes, lanes).astype(np.intp))
            for version, layer, lanes in parts
        ]
        self.values = np.zeros(self.lanes.size)
        self.weights = np.zeros(self.lanes.size) if mixed else None

    def fill(self, weights: Sequence[float]) -> None:
        """Collect the parts' outputs, evaluated already. With one version they
        are copied; with several, ``weights`` (per version) average them per
        lane, and each lane's weight is ``min(1, Σ weight)``."""
        values = self.values
        if self.weights is None:
            for part in self.parts:
                values[part.at] = part.out
            return
        total = self.weights
        values.fill(0.0)
        total.fill(0.0)
        for part in self.parts:
            weight = weights[part.version]
            values[part.at] += part.out * weight
            total[part.at] += weight
        np.divide(values, total, out=values, where=total > 0.0)
        np.minimum(total, 1.0, out=total)

    def presence(self, weights: Sequence[float]) -> None:
        """Only the per-lane weights (snap lanes hold a constant value)."""
        total = self.weights
        if total is None:
            return
        total.fill(0.0)
        for part in self.parts:
            total[part.at] += weights[part.version]
        np.minimum(total, 1.0, out=total)


type _Key = tuple[str, str, int]
"""A relative layer's identity across versions: mode, attribute, and how
many layers of that mode and attribute come before it in its template."""


class EffectRuntime:
    """One running instance of one source (phase-5-plan §5.5).

    ``source`` (absolute layers) is a contributor of the bank's band, at
    number ``seq``; ``relatives`` hold one :class:`Relative` per relative
    layer. Both are refilled in place by :meth:`update`, and replaced when
    the versions change. ``position``, ``presences`` and ``dynamics`` are
    what the last :meth:`update` evaluated: the clock's position, and each
    version's presence and dynamics ``d`` (what the effect status reads,
    :mod:`busk.engine.effect_status`).
    """

    __slots__ = (
        "_htp",
        "_ltp",
        "_relative",
        "_snap",
        "clock",
        "dynamics",
        "key",
        "place",
        "position",
        "presences",
        "relatives",
        "seq",
        "source",
        "versions",
    )

    def __init__(
        self, key: str, seq: int, clock: EffectClock, sourceId: str, origin: Origin | None = None
    ) -> None:
        self.key = key
        self.seq = seq
        self.clock = clock
        self.place = 0  # its place in the bank: orders relatives that share a number
        self.versions: list[Version] = []
        self.position = 0.0
        self.presences: list[float] = []
        self.dynamics: list[float] = []
        none = np.zeros(0, dtype=np.intp)
        self.source = Source(
            sourceId=sourceId,
            priority=0,
            seq=seq,
            htpPos=none,
            htpValues=np.zeros(0),
            ltpLanes=none,
            ltpValues=np.zeros(0),
            snapLanes=none,
            snapValues=np.zeros(0),
            snapThresholds=np.zeros(0),
            origin=origin,
        )
        self.relatives: list[Relative] = []
        self._htp = self._ltp = self._snap = _Channel([], False)
        self._relative: list[_Channel] = []

    @property
    def newest(self) -> Version:
        """The version the instance is moving to."""
        return self.versions[-1]

    def layout(self) -> None:
        """Rebuild the channels, the source's arrays and the relatives after
        the versions changed. Relative layers mix across versions by
        :data:`_Key`; layers are taken newest version first, in template
        order, so the newest template orders the relatives."""
        mixed = len(self.versions) > 1
        htp: list[_Rows] = []
        ltp: list[_Rows] = []
        snap: list[_Rows] = []
        relative: dict[_Key, list[_Rows]] = {}
        for v in reversed(range(len(self.versions))):
            seen: dict[tuple[str, str], int] = {}
            for layer in self.versions[v].effect.layers:
                rows = (v, layer, layer.lanes.ravel())
                if layer.mode != "absolute":
                    count = seen.get((layer.mode, layer.attribute), 0)
                    seen[layer.mode, layer.attribute] = count + 1
                    relative.setdefault((layer.mode, layer.attribute, count), []).append(rows)
                elif layer.htp:
                    htp.append(rows)
                else:
                    ltp.append(rows)
                    if layer.extras.size:
                        snap.append((v, layer, layer.extras))
        self._htp, self._ltp, self._snap = (_Channel(parts, mixed) for parts in (htp, ltp, snap))
        self._snap.values.fill(math.nan)
        source = self.source
        source.htpPos, source.htpValues = self._htp.lanes, self._htp.values
        source.htpWeights = self._htp.weights
        source.ltpLanes, source.ltpValues = self._ltp.lanes, self._ltp.values
        source.ltpWeights = self._ltp.weights
        source.snapLanes, source.snapValues = self._snap.lanes, self._snap.values
        source.snapThresholds = np.full(self._snap.lanes.size, _SNAP_AT)
        source.snapWeights = self._snap.weights
        self._relative = [_Channel(parts, mixed) for parts in relative.values()]
        self.relatives = [
            Relative(
                priority=source.priority,
                seq=self.seq,
                order=0,
                op="add" if key[0] == "add" else "multiply",
                lanes=channel.lanes,
                amounts=channel.values,
                weights=channel.weights,
                clamp=channel.parts[0].layer.clamp,
                origin=source.origin,
            )
            for key, channel in zip(relative, self._relative, strict=True)
        ]

    def ramp(self, now: float, version: Version, to: float, timing: Timing, scale: float) -> float:
        """Fade ``version``'s presence from its value at ``now`` × ``scale``
        to ``to`` with ``timing``; returns when the fade ends."""
        version.presence = Envelope(
            start=now,
            delay=timing.delay,
            duration=timing.duration,
            fromValue=version.presence.value(now) * scale,
            toValue=to,
            curve=timing.curve,
        )
        return now + timing.delay + timing.duration

    def prune(self, now: float) -> bool:
        """Drop the versions whose presence has settled at 0 by ``now``;
        returns whether any version is left. Both :meth:`update` and
        :meth:`EffectBank.retarget` prune first, so what runs never depends
        on how often the engine ticked."""
        versions = self.versions
        kept = [v for v in versions if not _gone(v, now)]
        if len(kept) != len(versions):
            self.versions = kept
            if not kept:
                return False
            self.layout()
        return True

    def update(
        self, now: float, priority: int, scalars: EffectScalars, fadeAt: float | None = None
    ) -> bool:
        """Evaluate the instance at ``now`` into :attr:`source` and
        :attr:`relatives`, after :meth:`prune`; returns ``False`` when no
        version is left (the runtime is done). The presences are taken at
        ``fadeAt`` (default ``now``): a manual transition's virtual time."""
        fade_at = now if fadeAt is None else fadeAt
        if not self.prune(fade_at):
            return False
        versions = self.versions
        position = self.clock.position(now)
        presence = [v.presence.value(fade_at) for v in versions]
        dynamics = [scalars.dynamics(v.effect) for v in versions]
        self.position, self.presences, self.dynamics = position, presence, dynamics
        relative = self._relative
        for channel in (self._htp, self._ltp, *relative):
            for part in channel.parts:
                effect = versions[part.version].effect
                part.evaluate(
                    base_phase(effect.direction, position), effect.size * dynamics[part.version]
                )
        absolute = [p * d for p, d in zip(presence, dynamics, strict=True)]
        self._htp.fill(absolute)
        self._ltp.fill(absolute)
        self._snap.presence(absolute)
        for channel in relative:
            channel.fill(presence)
        # One version: its presence is a scalar. Several: it is in the per-lane weights.
        share, scale = (absolute[0], presence[0]) if len(versions) == 1 else (1.0, 1.0)
        source = self.source
        source.priority = priority
        source.seq = self.seq
        source.intensityScale = scalars.intensityScale
        source.htpWeight = scalars.htpWeight * share if source.htpPos.size else 0.0
        has_ltp = source.ltpLanes.size or source.snapLanes.size
        source.ltpWeight = scalars.ltpWeight * share if has_ltp else 0.0
        intensity = scalars.htpWeight * scalars.intensityScale * scale
        other = scalars.ltpWeight * scale
        base_order = self.place << _ORDER_BITS
        for k, (rel, channel) in enumerate(zip(self.relatives, relative, strict=True)):
            rel.priority = priority
            rel.seq = self.seq
            rel.order = base_order + k
            rel.weight = intensity if channel.parts[0].layer.attribute == "intensity" else other
        return True


def _gone(version: Version, now: float) -> bool:
    """Whether ``version`` has faded out by ``now``: what pruning drops."""
    return version.presence.toValue == 0.0 and version.presence.settled(now)


# -- banks ---------------------------------------------------------------------


class EffectBank:
    """The running effects of one source: a playback's main or flash, or the
    programmer (phase-5-plan §5.5).

    ``speed`` is the engine's dict of speed masters, shared and read live;
    ``rateLevel`` the owner's ``rate`` fader level (``None`` without one);
    ``cap`` the engine's strobe cap, shared and read live; ``origin`` what
    its instances' sources and relative layers belong to (the readout's).
    Runtimes are kept oldest first: leaving instances, then the current
    ones in cue order, which is the order :meth:`contributors` hands them
    out, so a later instance wins a tie.
    """

    def __init__(
        self,
        sourceId: str,
        priority: int,
        speed: Mapping[MasterId, SpeedMasterRuntime],
        rateLevel: float | None = None,
        cap: StrobeCap | None = None,
        origin: Origin | None = None,
    ) -> None:
        self.sourceId = sourceId
        self.priority = priority
        self.speed = speed
        self.rateLevel = rateLevel
        self.cap = StrobeCap() if cap is None else cap
        self.origin = origin
        self.runtimes: dict[str, EffectRuntime] = {}

    @property
    def active(self) -> bool:
        """Whether any instance is running."""
        return bool(self.runtimes)

    def retarget(
        self,
        now: float,
        effects: Sequence[CompiledEffect],
        timing: EffectTiming,
        seqs: SeqRule,
        scale: float = 1.0,
        touched: AbstractSet[str] = frozenset(),
    ) -> float:
        """Move to ``effects`` from ``now`` (decisions 9–11); returns the
        completion time: the latest end of the presence fades started, or
        ``now``.

        Versions that have faded out by ``now`` are pruned first, as an
        update at ``now`` would: an instance that faded out restarts on a new
        clock however often the engine ticked. Every presence is then
        multiplied by ``scale`` (re-activating a releasing playback folds
        its release level in), and fades back to its target from there.
        Without a scale, an instance whose newest version is
        unchanged (the same object, else :meth:`CompiledEffect.same`) keeps
        its fades; if it was leaving it fades back in. Numbers follow
        ``seqs`` (decision 10): ``all`` numbers every instance, ``fresh`` the
        ones that enter or change, ``mask`` the keys in ``touched``, and a
        new instance always takes ``seqs.seq``.
        """
        force = scale != 1.0
        ends = [now]
        running = {key: rt for key, rt in self.runtimes.items() if rt.prune(now)}
        current: dict[str, EffectRuntime] = {}
        for effect in effects:
            runtime = running.get(effect.key)
            if runtime is None:
                clock = EffectClock(now, *self._tempo(effect, self.rateLevel))
                runtime = EffectRuntime(
                    effect.key, seqs.seq, clock, f"{self.sourceId}:{effect.key}", self.origin
                )
                runtime.versions.append(Version(effect))
                ends.append(runtime.ramp(now, runtime.newest, 1.0, timing.enter(effect), 1.0))
                runtime.layout()
                moved = True
            else:
                moved = self._move(runtime, now, effect, timing, scale, ends)
            if seqs.kind == "all" or (
                (seqs.kind == "fresh" and moved) or (seqs.kind == "mask" and effect.key in touched)
            ):
                runtime.seq = seqs.seq
            current[effect.key] = runtime
        leaving = {key: runtime for key, runtime in running.items() if key not in current}
        for runtime in leaving.values():
            for version in runtime.versions:
                if force or version.presence.toValue != 0.0:
                    ends.append(runtime.ramp(now, version, 0.0, timing.leave, scale))
            if seqs.kind == "all":
                runtime.seq = seqs.seq
        self.runtimes = leaving | current
        for place, runtime in enumerate(self.runtimes.values()):
            runtime.place = place
        return max(ends)

    def _move(
        self,
        runtime: EffectRuntime,
        now: float,
        effect: CompiledEffect,
        timing: EffectTiming,
        scale: float,
        ends: list[float],
    ) -> bool:
        """Aim a running instance at ``effect``; returns whether it entered or
        changed. The ends of the fades it starts are appended to ``ends``."""
        force = scale != 1.0
        newest = runtime.newest
        if newest.effect is effect or newest.effect.same(effect):
            newest.effect = effect  # the same structure; its cue may be numbered anew
            entering = newest.presence.toValue != 1.0
            if entering or force:
                ends.append(runtime.ramp(now, newest, 1.0, timing.enter(effect), scale))
            for version in runtime.versions[:-1]:  # older versions leave; a held one too
                if force or version.presence.toValue != 0.0:
                    ends.append(runtime.ramp(now, version, 0.0, timing.change, scale))
            return entering
        for version in runtime.versions:
            if force or version.presence.toValue != 0.0:
                ends.append(runtime.ramp(now, version, 0.0, timing.change, scale))
        runtime.versions.append(Version(effect))
        ends.append(runtime.ramp(now, runtime.newest, 1.0, timing.change, 1.0))
        runtime.clock.rerate(now, *self._tempo(effect, self.rateLevel))
        runtime.layout()
        return True

    def _tempo(
        self, effect: CompiledEffect, rateLevel: float | None
    ) -> tuple[float, SpeedMasterRuntime | None]:
        """:func:`tempo` of ``effect`` with this bank's masters and cap."""
        return tempo(effect, self.speed, rateLevel, self.cap.hz)

    def running(self, key: str, now: float) -> bool:
        """Whether instance ``key`` still runs at ``now``: some version of it
        has not faded out, as :meth:`retarget` finds after pruning."""
        runtime = self.runtimes.get(key)
        return runtime is not None and not all(_gone(v, now) for v in runtime.versions)

    def update(self, now: float, scalars: EffectScalars, fadeAt: float | None = None) -> None:
        """Evaluate every instance at ``now``, with presences at ``fadeAt``
        (default ``now``; a manual transition's virtual time); instances
        whose versions have all faded out are dropped, with their clocks."""
        done = [
            key
            for key, runtime in self.runtimes.items()
            if not runtime.update(now, self.priority, scalars, fadeAt)
        ]
        for key in done:
            del self.runtimes[key]

    def hold(self, at: float) -> None:
        """Hold every presence at its value at ``at`` from now on (a manual
        transition stops where the fader left it, phase-6-plan §5.6), so the
        bank can be evaluated at any time after. Versions that have faded
        out by ``at`` are dropped, and instances left without versions.

        A presence whose fade has ended by ``at`` holds exactly its target.
        A retarget then fades every held version on to where it belongs."""
        for key in list(self.runtimes):
            runtime = self.runtimes[key]
            if not runtime.prune(at):
                del self.runtimes[key]
                continue
            for version in runtime.versions:
                presence = version.presence
                value = presence.toValue if at >= presence.end else presence.value(at)
                version.presence = Envelope(start=-math.inf, fromValue=value, toValue=value)

    def locked(self, master: SpeedMasterRuntime) -> list[EffectClock]:
        """The clocks locked to ``master``. A tap reads their positions before
        the master taps, and aligns each one after (§5.4)."""
        return [rt.clock for rt in self.runtimes.values() if rt.clock.master is master]

    def rerate(self, now: float, rateLevel: float | None) -> None:
        """Follow a rate change at ``now``: the owner's ``rate`` fader moved to
        ``rateLevel``, a speed master's step changed, or (while a strobe cap
        is set) its tempo, or the cap itself. Every clock re-rates to its
        newest version's rate; one whose rate is unchanged is left alone."""
        self.rateLevel = rateLevel
        for runtime in self.runtimes.values():
            runtime.clock.rerate(now, *self._tempo(runtime.newest.effect, rateLevel))

    def remap(self, laneMap: NDArray[np.intp], posMap: NDArray[np.intp]) -> None:
        """Move every version onto a new slot table (a live swap, §5.10):
        :meth:`CompiledEffect.remapped`. Versions left without lanes are
        dropped, and instances left without versions."""
        for key in list(self.runtimes):
            runtime = self.runtimes[key]
            versions = []
            for version in runtime.versions:
                effect = version.effect.remapped(laneMap, posMap)
                if effect is not None:
                    versions.append(Version(effect, version.presence))
            if not versions:
                del self.runtimes[key]
                continue
            runtime.versions = versions
            runtime.layout()

    def clear(self) -> None:
        """Stop every instance at once (the owner went idle)."""
        self.runtimes.clear()

    def contributors(self) -> Iterator[Source]:
        """Each instance's source, oldest first; a source of only relative
        layers is never present."""
        for runtime in self.runtimes.values():
            yield runtime.source

    def relatives(self) -> Iterator[Relative]:
        """Every instance's relative layers, as filled by the last :meth:`update`."""
        for runtime in self.runtimes.values():
            yield from runtime.relatives
