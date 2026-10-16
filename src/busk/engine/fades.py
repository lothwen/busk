"""Fades: presence envelopes and per-slot fades (spec §5.18 ``FadeState``, ``ContributionState``).

Envelopes
---------
Phase 2 fades a source's *weight*, not its values (phase-2-plan, Context):
fade-in on activation, fade-out on release. An :class:`Envelope` is the
presence half of §5.18's ``FadeState``. Phase 4 gives it a ``curve``
(:mod:`busk.engine.curves`); release envelopes stay linear.

An envelope is a pure function of time: :meth:`Envelope.value` depends only
on ``now`` and the last :meth:`~Envelope.retarget`, never on how often it is
evaluated. That is what makes the engine's output independent of its tick
schedule (§2.5).

Per-slot fades (phase-4-plan §5.3)
----------------------------------
A cue transition fades every slot on its own: a value fade and a presence
fade, with the slot's own timing (in or out, per family, per entry) and
curve. §5.18 describes one ``ContributionState`` per slot; a
:class:`ContributionSet` stores them as numpy arrays over one source's
lanes, in three :class:`Partition` s the way the resolver merges them: HTP
positions, continuous LTP lanes and snap lanes.

* **Timing groups.** Every lane belongs to one :class:`FadeState` (a
  :class:`Timing` started at some time). One GO creates a handful of groups:
  in, out, per family, per entry. Per tick each group is evaluated once, as
  a Python scalar, and the fractions are gathered per lane with
  ``np.take``. Group 0 is :data:`SETTLED`: its fraction is always 1.
* **Evaluate.** ``value = from + (to − from)·f``, except that a snap lane
  switches from ``from`` to ``to`` once ``f`` reaches its threshold (§7.3);
  presence moves the same way, ``weight = fromWeight + (toWeight −
  fromWeight)·f``. Values and presence share their curve.
* **Settle and compact.** Before each evaluation, the lanes of every group
  that has finished are *settled*: ``from := to``, group 0. A finished lane
  is then exactly its target, never a lerp that lands an ulp beside it (DMX
  bytes sit on half-to-even boundaries). When every group has finished the
  set *compacts*: lanes that faded out are dropped and the set is
  :attr:`~ContributionSet.settled`; from then until the next retarget its
  arrays are static and :meth:`~ContributionSet.evaluate` does nothing.
* **Retarget.** :meth:`ContributionSet.retarget` aims the set at a new
  :class:`Target` (a cue's state) without a jump: a lane whose target is
  the same as in the running transition keeps its running fade; every other
  lane fades from its current ``(value, weight)`` with the timing that a
  :class:`TimingRule` gives it. Lanes that are not in the target hold their
  value and fade out. A :class:`SeqRule` says which lanes take a fresh
  sequence number (decision 4).
* **Slots.** A slot's lanes always share their group and their sequence
  number: a change to any lane of a slot changes the whole slot. A colour
  slot spans two partitions (``r, g, b`` are LTP, the extras snap), so this
  is reduced through ``SlotTable.laneSlot`` across both.

Everything a set holds is a pure function of ``now`` between retargets:
settling and compacting depend only on ``now``, so a set evaluated at every
tick and one evaluated only at the end agree exactly (decision 1).

Retargeting runs at command time on the engine thread: a few vectorised set
operations over the source's lanes.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

import numpy as np
from numpy.typing import NDArray

from busk.engine.curves import Curve, fade_fraction, linear


@dataclass(slots=True)
class Envelope:
    """A ramp from ``fromValue`` to ``toValue`` along ``curve``.

    The ramp waits ``delay`` seconds after ``start``, then moves over
    ``duration`` seconds. Before it begins the value is ``fromValue``; once it
    ends it is exactly ``toValue``. A zero duration is a step at
    ``start + delay``. A new envelope rests at 0.
    """

    start: float = 0.0
    delay: float = 0.0
    duration: float = 0.0
    fromValue: float = 0.0
    toValue: float = 0.0
    curve: Curve = linear

    def value(self, now: float) -> float:
        """The envelope's value at ``now``."""
        fraction = fade_fraction(now - self.start - self.delay, self.duration, self.curve)
        if fraction >= 1.0:
            return self.toValue  # exactly: not a lerp that lands near it
        return self.fromValue + (self.toValue - self.fromValue) * fraction

    def retarget(
        self,
        now: float,
        to: float,
        duration: float,
        delay: float = 0.0,
        curve: Curve = linear,
    ) -> None:
        """Start a new ramp at ``now`` towards ``to``.

        The ramp starts from the envelope's *current* value, so a release in
        the middle of a fade-in glides down from wherever the weight is, and
        lasts exactly ``duration`` (§7.8: "0.25 → 0" over the release time).
        """
        self.fromValue = self.value(now)
        self.start = now
        self.delay = delay
        self.duration = duration
        self.toValue = to
        self.curve = curve

    def settled(self, now: float) -> bool:
        """Whether the ramp has ended: the value is ``toValue`` from now on."""
        return now - self.start - self.delay >= self.duration

    @property
    def end(self) -> float:
        """When the ramp ends (a due event's own time, e.g. a release's end)."""
        return self.start + self.delay + self.duration


# -- per-slot fades ----------------------------------------------------------

type Part = Literal["htp", "ltp", "snap"]
"""A partition of a source's lanes: HTP positions, continuous LTP lanes, snap lanes."""


@dataclass(frozen=True, slots=True)
class Timing:
    """How one fade moves: wait ``delay`` seconds, then move over ``duration``
    seconds along ``curve``. ``Timing()`` is a step at once."""

    duration: float = 0.0
    delay: float = 0.0
    curve: Curve = linear


@dataclass(frozen=True, slots=True)
class FadeState:
    """One timing group (§5.18 ``FadeState``): a :class:`Timing` started at ``start``.

    Every lane in the group moves by the same fraction. The group has
    finished from :attr:`end` on, and its fraction is then exactly 1, so the
    completion time a retarget reports and the time its lanes settle agree.
    """

    start: float
    delay: float
    duration: float
    curve: Curve

    @property
    def end(self) -> float:
        """When the fade has finished: ``start + delay + duration``."""
        return self.start + self.delay + self.duration

    def finished(self, now: float) -> bool:
        """Whether the fade has finished at ``now``."""
        return now >= self.end

    def fraction(self, now: float) -> float:
        """How far the fade is at ``now``: 0 during its delay, 1 once finished."""
        if now >= self.end:
            return 1.0
        return fade_fraction(now - self.start - self.delay, self.duration, self.curve)


SETTLED: Final = FadeState(start=-math.inf, delay=0.0, duration=0.0, curve=linear)
"""Group 0 of every set: finished since forever, fraction 1."""


class Target(Protocol):
    """What a set is aimed at: a cue's state as sorted lane arrays.

    :class:`~busk.compiler.cues.CompiledCue` is one; so is a programmer
    frame's cue. Lanes are unique and ascending within each partition.
    """

    @property
    def htpPos(self) -> NDArray[np.intp]: ...
    @property
    def htpValues(self) -> NDArray[np.float64]: ...
    @property
    def ltpLanes(self) -> NDArray[np.intp]: ...
    @property
    def ltpValues(self) -> NDArray[np.float64]: ...
    @property
    def snapLanes(self) -> NDArray[np.intp]: ...
    @property
    def snapValues(self) -> NDArray[np.float64]: ...
    @property
    def snapThresholds(self) -> NDArray[np.float64]: ...


class TimingRule(Protocol):
    """Which :class:`Timing` each changed lane of a retarget fades with.

    A rule answers with indices into its :attr:`timings`, one per lane, so
    a retarget over thousands of lanes stays vectorised. A cue transition
    picks the cue's in, out, per-family or per-entry timing (decision 6); a
    chase step or a programmer change uses one :class:`Uniform` timing.
    Lanes of one slot must get the same timing.
    """

    @property
    def timings(self) -> Sequence[Timing]:
        """The distinct timings the rule hands out."""
        ...

    def entering(
        self, part: Part, at: NDArray[np.intp], falling: NDArray[np.bool_]
    ) -> NDArray[np.intp]:
        """The timing of each changed lane that is in the target. ``at`` are
        the lanes' positions in the target's arrays of ``part``; ``falling``
        says whether the lane's intensity goes down (HTP only: target below
        the current value × presence; all false for LTP and snap)."""
        ...

    def leaving(self, part: Part, index: NDArray[np.intp]) -> NDArray[np.intp]:
        """The timing of each changed lane that is not in the target, given
        by its lane (HTP: its intensity position)."""
        ...


@dataclass(frozen=True, slots=True)
class Uniform:
    """A :class:`TimingRule` with one timing for every lane: a chase step,
    a programmer change."""

    timing: Timing

    @property
    def timings(self) -> tuple[Timing, ...]:
        return (self.timing,)

    def entering(
        self, part: Part, at: NDArray[np.intp], falling: NDArray[np.bool_]
    ) -> NDArray[np.intp]:
        return np.zeros(at.size, dtype=np.intp)

    def leaving(self, part: Part, index: NDArray[np.intp]) -> NDArray[np.intp]:
        return np.zeros(index.size, dtype=np.intp)


type SeqKind = Literal["fresh", "all", "keep", "mask"]


@dataclass(frozen=True, slots=True, eq=False)
class SeqRule:
    """Which LTP and snap lanes a retarget numbers ``seq`` (phase-4-plan decision 4).

    =========  ========================================  ===========================
    Rule       Lanes that get ``seq``                    Every other lane
    =========  ========================================  ===========================
    ``fresh``  changed lanes that enter or change value  keeps its number
    ``all``    every lane                                —
    ``keep``   none                                      keeps its number
    ``mask``   the lanes of ``slots``                    keeps its number
    =========  ========================================  ===========================

    Under every rule a lane without a number yet (a new lane) gets ``seq``.
    ``fresh`` is for manual moves (GO, BACK, GOTO), ``all`` for activation
    and re-assert, ``keep`` for automatic advances and live edits, ``mask``
    for the programmer's touched slots. HTP lanes carry no number: HTP
    ignores order within a band.
    """

    kind: SeqKind
    seq: int
    slots: NDArray[np.intp] | None = None  # mask: the slots that get ``seq``

    @classmethod
    def fresh(cls, seq: int) -> SeqRule:
        """Changed lanes that enter or change value get ``seq``."""
        return cls("fresh", seq)

    @classmethod
    def all(cls, seq: int) -> SeqRule:
        """Every lane gets ``seq``."""
        return cls("all", seq)

    @classmethod
    def keep(cls, seq: int) -> SeqRule:
        """Every lane keeps its number; new lanes get ``seq``."""
        return cls("keep", seq)

    @classmethod
    def mask(cls, seq: int, slots: NDArray[np.intp]) -> SeqRule:
        """The lanes of ``slots`` get ``seq``; new lanes too."""
        return cls("mask", seq, slots)


_NO_INDEX: Final = np.zeros(0, dtype=np.intp)
_NO_VALUES: Final = np.zeros(0, dtype=np.float64)
_NO_SEQS: Final = np.zeros(0, dtype=np.int64)


class Partition:
    """One partition of a :class:`ContributionSet`: parallel arrays, sorted by ``index``.

    ``index`` are HTP positions (into ``SlotTable.intensityLanes``) or lanes
    of the logical frame. Per lane the partition holds its fade's from and to
    value and presence, its timing group (0 = settled), its sequence number
    (LTP and snap; 0 = none yet) and, for snap lanes, the presence at which
    the value switches (``threshold``, also used by the resolver).

    ``value`` and ``weight`` are the lanes evaluated at the set's last
    :meth:`~ContributionSet.evaluate`, refilled in place: a source reads
    them directly. A partition's arrays are replaced (never resized) when
    the set changes shape; :attr:`ContributionSet.version` counts that.
    """

    __slots__ = (
        "_fraction",
        "delta",
        "fromValue",
        "fromWeight",
        "group",
        "index",
        "seq",
        "snapping",
        "threshold",
        "toValue",
        "toWeight",
        "value",
        "weight",
        "weightDelta",
    )

    def __init__(
        self,
        snapping: bool,
        index: NDArray[np.intp],
        fromValue: NDArray[np.float64],
        toValue: NDArray[np.float64],
        fromWeight: NDArray[np.float64],
        toWeight: NDArray[np.float64],
        group: NDArray[np.intp],
        seq: NDArray[np.int64],
        threshold: NDArray[np.float64],
    ) -> None:
        """Take ownership of the arrays. ``value`` and ``weight`` start as the
        targets; a set that is still fading refills them before use."""
        self.snapping = snapping
        self.index = index
        self.fromValue = fromValue
        self.toValue = toValue
        self.fromWeight = fromWeight
        self.toWeight = toWeight
        self.group = group
        self.seq = seq
        self.threshold = threshold
        # Precomputed so a tick is one multiply-add per array. Snap values do
        # not interpolate (and may be NaN), so they need no delta.
        self.delta = _NO_VALUES if snapping else toValue - fromValue
        self.weightDelta = toWeight - fromWeight
        self.value = toValue.copy()
        self.weight = toWeight.copy()
        self._fraction = np.empty(index.size)

    @classmethod
    def empty(cls, snapping: bool) -> Partition:
        """A partition without lanes."""
        return cls(
            snapping,
            _NO_INDEX,
            _NO_VALUES,
            _NO_VALUES,
            _NO_VALUES,
            _NO_VALUES,
            _NO_INDEX,
            _NO_SEQS,
            _NO_VALUES,
        )

    @classmethod
    def at_rest(
        cls,
        snapping: bool,
        index: NDArray[np.intp],
        value: NDArray[np.float64],
        weight: NDArray[np.float64],
        seq: NDArray[np.int64],
        threshold: NDArray[np.float64],
    ) -> Partition:
        """A settled partition holding ``(value, weight)`` per lane."""
        return cls(
            snapping,
            index,
            value,
            value.copy(),
            weight,
            weight.copy(),
            np.zeros(index.size, dtype=np.intp),
            seq,
            threshold,
        )

    @property
    def size(self) -> int:
        """The number of lanes."""
        return int(self.index.size)

    def take(
        self,
        positions: NDArray[np.intp],
        index: NDArray[np.intp] | None = None,
        evaluated: bool = True,
    ) -> Partition:
        """The lanes at ``positions``, in that order, optionally renamed to ``index``.

        With ``evaluated`` the last evaluated ``value`` and ``weight`` are
        carried over, so the result reads the same as this partition until
        the next evaluation; without it they start as the targets."""
        part = Partition(
            self.snapping,
            self.index[positions] if index is None else index,
            self.fromValue[positions],
            self.toValue[positions],
            self.fromWeight[positions],
            self.toWeight[positions],
            self.group[positions],
            self.seq[positions],
            self.threshold[positions],
        )
        if evaluated:
            part.value = self.value[positions]
            part.weight = self.weight[positions]
        return part

    def settle(self, finished: NDArray[np.bool_]) -> None:
        """Land the lanes of the ``finished`` groups (a mask over group ids)
        on their targets and move them to group 0."""
        lanes = finished[self.group]
        if not lanes.any():
            return
        self.fromValue[lanes] = self.toValue[lanes]
        self.fromWeight[lanes] = self.toWeight[lanes]
        if not self.snapping:
            self.delta[lanes] = 0.0
        self.weightDelta[lanes] = 0.0
        self.group[lanes] = 0

    def evaluate(self, fractions: NDArray[np.float64]) -> None:
        """Refill ``value`` and ``weight`` from each lane's group fraction."""
        fraction = np.take(fractions, self.group, out=self._fraction)
        if self.snapping:
            np.copyto(self.value, self.fromValue)
            np.copyto(self.value, self.toValue, where=fraction >= self.threshold)
        else:
            np.multiply(self.delta, fraction, out=self.value)
            self.value += self.fromValue
        np.multiply(self.weightDelta, fraction, out=self.weight)
        self.weight += self.fromWeight


class ContributionSet:
    """A source's per-slot fades: §5.18's ``ContributionState`` for each of its
    slots, as arrays (see the module docstring).

    The engine thread owns it. ``laneSlot`` (``SlotTable.laneSlot``) maps
    each lane of the logical frame to its slot, so that a slot's lanes
    change together. ``version`` increases whenever a partition's arrays
    are replaced (retarget, compaction, freeze, remap, clear): a source that
    reads the arrays must then be re-pointed at them, and its sequence
    numbers re-declared.
    """

    def __init__(self, laneSlot: NDArray[np.intp]) -> None:
        self.laneSlot = laneSlot
        self.version = 0
        self.htp = Partition.empty(False)
        self.ltp = Partition.empty(False)
        self.snap = Partition.empty(True)
        self.groups: list[FadeState] = [SETTLED]
        self._live: list[int] = []  # groups that have not finished yet
        self.settled = True
        self.unitWeights = True

    @property
    def parts(self) -> tuple[Partition, Partition, Partition]:
        """The three partitions: HTP, LTP, snap."""
        return (self.htp, self.ltp, self.snap)

    @property
    def empty(self) -> bool:
        """Whether the set holds no lanes at all."""
        return not (self.htp.size or self.ltp.size or self.snap.size)

    # -- evaluation

    def evaluate(self, now: float) -> None:
        """Fill every partition's ``value`` and ``weight`` for ``now``.

        Finished groups are settled first, and a set whose groups have all
        finished compacts. ``now`` must not go back between calls."""
        if self.settled:
            return
        done = [g for g in self._live if self.groups[g].finished(now)]
        if done:
            finished = np.zeros(len(self.groups), dtype=np.bool_)
            finished[done] = True
            for part in self.parts:
                part.settle(finished)
            self._live = [g for g in self._live if not finished[g]]
            if not self._live:
                self._compact()
                self.version += 1
                return
        self._fill(now)

    def _fill(self, now: float) -> None:
        fractions = np.array([group.fraction(now) for group in self.groups])
        for part in self.parts:
            part.evaluate(fractions)

    def _compact(self) -> None:
        """Every group has finished and every lane is settled: drop the lanes
        that faded out and go static."""
        self.htp, self.ltp, self.snap = (
            part.take(np.flatnonzero(part.toWeight > 0.0), evaluated=False) for part in self.parts
        )
        self._rest()

    def _rest(self) -> None:
        """Mark the set settled after its partitions were made static."""
        self.groups = [SETTLED]
        self._live = []
        self.settled = True
        self.unitWeights = all(bool((part.weight == 1.0).all()) for part in self.parts)

    # -- changes

    def retarget(
        self,
        now: float,
        target: Target,
        timing: TimingRule,
        seqs: SeqRule,
        scale: float = 1.0,
        ltpScale: float | None = None,
    ) -> float:
        """Aim the set at ``target`` from ``now``, and return the completion
        time: the latest end among the fades this call started (``now`` if
        it started none).

        Per lane (phase-4-plan §5.3):

        1. the current ``(value, weight)`` at ``now``, with the weight
           times ``scale`` (HTP) or ``ltpScale`` (LTP and snap; default
           ``scale``): re-activating a releasing playback folds its release
           level into its slots. A lane not present yet starts at the target
           value with weight 0;
        2. the target: ``(target value, 1)`` for the target's lanes, ``(current
           value, 0)`` (hold and fade out) for the others;
        3. a lane is *changed* if it is new, or its target differs from the
           running fade's ``(toValue, toWeight)`` (NaN equals NaN), or its
           weight was scaled; a change to any lane changes its whole slot;
        4. changed lanes fade from their current state with the timing the
           rule gives them, in groups interned by timing; unchanged lanes keep
           their running fade;
        5. sequence numbers follow ``seqs``;
        6. lanes at weight 0 that are not in the target are dropped.

        The set's state at ``now`` is unchanged, except where a fade has no
        length (a zero delay and duration, or ``snapStart`` without a delay)
        or a weight was scaled: no jumps.
        """
        self.evaluate(now)
        ltp_scale = scale if ltpScale is None else ltpScale
        htp = _Draft(self.htp, target.htpPos, target.htpValues, None, scale)
        ltp = _Draft(self.ltp, target.ltpLanes, target.ltpValues, None, ltp_scale)
        snap = _Draft(
            self.snap, target.snapLanes, target.snapValues, target.snapThresholds, ltp_scale
        )
        # A slot's lanes change together; a colour slot spans LTP and snap.
        # HTP slots have one lane each.
        ltp_slots, snap_slots = self.laneSlot[ltp.index], self.laneSlot[snap.index]
        hit = np.zeros(int(self.laneSlot[-1]) + 1 if self.laneSlot.size else 0, dtype=np.bool_)
        hit[ltp_slots[ltp.changed]] = True
        hit[snap_slots[snap.changed]] = True
        ltp.changed = hit[ltp_slots]
        snap.changed = hit[snap_slots]

        started = _Groups(self.groups, now, timing.timings)
        named: tuple[tuple[_Draft, Part], ...] = ((htp, "htp"), (ltp, "ltp"), (snap, "snap"))
        groups = [started.assign(draft, timing, part) for draft, part in named]
        completion = started.completion()
        seq_arrays = (
            np.zeros(htp.index.size, dtype=np.int64),
            _numbers(ltp, ltp_slots, seqs),
            _numbers(snap, snap_slots, seqs),
        )
        self.htp, self.ltp, self.snap = (
            draft.build(group, seq)
            for draft, group, seq in zip((htp, ltp, snap), groups, seq_arrays, strict=True)
        )
        self._regroup(now)
        self.version += 1
        return completion

    def _regroup(self, now: float) -> None:
        """After a retarget: settle groups that have already finished, drop
        the groups no lane uses, and compact or evaluate at ``now``."""
        finished = np.array([group.finished(now) for group in self.groups])
        for part in self.parts:
            part.settle(finished)
        in_use = np.zeros(len(self.groups), dtype=np.bool_)
        in_use[0] = True
        for part in self.parts:
            in_use[part.group] = True
        used = np.flatnonzero(in_use)
        renumber = np.zeros(len(self.groups), dtype=np.intp)
        renumber[used] = np.arange(used.size)
        for part in self.parts:
            part.group = renumber[part.group]
        self.groups = [self.groups[int(g)] for g in used]
        self._live = list(range(1, len(self.groups)))
        if not self._live:
            self._compact()
            return
        self.settled = False
        self.unitWeights = False
        self._fill(now)

    def freeze(self, now: float) -> None:
        """Stop every fade where it is at ``now``: each lane holds its current
        ``(value, weight)`` from now on.

        A releasing cue stack freezes its slots and fades the playback's
        release envelope instead (decision 8), so a release in the middle of
        a transition glides down from where the slots are."""
        self.evaluate(now)
        if self.settled:
            return
        parts = []
        for part in self.parts:
            keep = np.flatnonzero(part.weight > 0.0)
            parts.append(
                Partition.at_rest(
                    part.snapping,
                    part.index[keep],
                    part.value[keep],
                    part.weight[keep],
                    part.seq[keep],
                    part.threshold[keep],
                )
            )
        self.htp, self.ltp, self.snap = parts
        self._rest()
        self.version += 1

    def remap(
        self,
        laneSlot: NDArray[np.intp],
        laneMap: NDArray[np.integer[Any]],
        posMap: NDArray[np.integer[Any]],
    ) -> None:
        """Follow a new slot table (a live swap that moved slots).

        ``laneMap`` maps each old lane to its new lane and ``posMap`` each old
        intensity position to its new one, −1 where it is gone. Running fades
        carry on untouched on their new lanes; lanes that are gone are
        dropped at once."""
        self.laneSlot = laneSlot
        self.htp = _moved(self.htp, posMap)
        self.ltp = _moved(self.ltp, laneMap)
        self.snap = _moved(self.snap, laneMap)
        self.version += 1

    def clear(self) -> None:
        """Drop every lane: the source contributes nothing."""
        self.htp = Partition.empty(False)
        self.ltp = Partition.empty(False)
        self.snap = Partition.empty(True)
        self._rest()
        self.version += 1


def _moved(part: Partition, mapping: NDArray[np.integer[Any]]) -> Partition:
    """``part`` with its index mapped through ``mapping`` (−1 = gone), re-sorted."""
    new = mapping[part.index].astype(np.intp)
    keep = np.flatnonzero(new >= 0)
    order = keep[np.argsort(new[keep], kind="stable")]
    return part.take(order, new[order])


def distinct[T: np.generic](values: NDArray[T]) -> NDArray[T]:
    """The ascending distinct elements of ``values``.

    The engine thread calls this on lane arrays in retargets and when
    sources are split into sequence runs, so it avoids ``np.unique`` and
    ``np.union1d``: NumPy 2.3+ hashes there, which on a few thousand lanes
    holding a handful of numbers is about ten times slower than a sort.
    """
    ordered = np.sort(values)
    keep = np.empty(ordered.size, dtype=np.bool_)
    keep[:1] = True
    np.not_equal(ordered[1:], ordered[:-1], out=keep[1:])
    return ordered[keep]


def _union(a: NDArray[np.intp], b: NDArray[np.intp]) -> NDArray[np.intp]:
    """The ascending union of two arrays of lanes."""
    return distinct(np.concatenate((a, b)).astype(np.intp, copy=False))


class _Draft:
    """One partition being retargeted: the union of its lanes and the target's.

    Lanes are sorted. ``mine`` marks the partition's current lanes, ``at``
    each lane's position in the target (−1: not in it). ``value`` and
    ``weight`` are the current state (scaled), ``toValue`` and ``toWeight``
    the target, ``changed`` whether the lane starts a new fade.

    ``same`` is the common case of a tracking list, where every cue holds
    the slots of the one before: the target has exactly the partition's
    lanes. It skips the union and the scatters, which dominate a retarget
    (a burst of GOs, or a live edit that retargets every playback, runs
    them back to back on the engine thread).
    """

    def __init__(
        self,
        part: Partition,
        lanes: NDArray[np.intp],
        values: NDArray[np.float64],
        thresholds: NDArray[np.float64] | None,
        scale: float,
    ) -> None:
        self.part = part
        self.same = part.index.size == lanes.size and np.array_equal(part.index, lanes)
        if self.same:
            self._same_lanes(values, thresholds, scale)
            return
        index = _union(part.index, lanes)
        size = index.size
        mine = np.zeros(size, dtype=np.bool_)
        mine[np.searchsorted(index, part.index)] = True
        at = np.full(size, -1, dtype=np.intp)
        at[np.searchsorted(index, lanes)] = np.arange(lanes.size)
        aimed = at >= 0

        value = np.empty(size)
        value[aimed] = values  # a new lane starts at its target value
        value[mine] = part.value
        weight = np.zeros(size)
        weight[mine] = part.weight * scale
        to_value = value.copy()  # lanes that leave hold their value
        to_value[aimed] = values
        to_weight = aimed.astype(np.float64)

        running_value = np.full(size, np.nan)
        running_value[mine] = part.toValue
        running_weight = np.full(size, -1.0)
        running_weight[mine] = part.toWeight
        same_value = (to_value == running_value) | (np.isnan(to_value) & np.isnan(running_value))
        changed = ~mine | (to_weight != running_weight) | (aimed & ~same_value)
        changed[mine] |= weight[mine] != part.weight  # a scaled presence fades anew

        self.index, self.mine, self.at, self.aimed = index, mine, at, aimed
        self.value, self.weight = value, weight
        self.toValue, self.toWeight = to_value, to_weight
        self.changed = changed
        if thresholds is None:
            self.threshold = np.zeros(size)
        else:
            self.threshold = np.empty(size)
            self.threshold[mine] = part.threshold  # lanes that leave keep theirs
            self.threshold[aimed] = thresholds

    def _same_lanes(
        self,
        values: NDArray[np.float64],
        thresholds: NDArray[np.float64] | None,
        scale: float,
    ) -> None:
        """:meth:`__init__` when the target's lanes are the partition's:
        every lane is mine and aimed, at its own position."""
        part = self.part
        size = part.index.size
        everywhere = np.ones(size, dtype=np.bool_)
        self.index, self.mine, self.aimed = part.index, everywhere, everywhere
        self.at = np.arange(size, dtype=np.intp)
        self.value = part.value.copy()  # refilled in place by the next evaluation
        self.weight = part.weight * scale
        self.toValue, self.toWeight = values, np.ones(size)
        same_value = (values == part.toValue) | (np.isnan(values) & np.isnan(part.toValue))
        self.changed = ~same_value | (part.toWeight != 1.0) | (self.weight != part.weight)
        self.threshold = np.zeros(size) if thresholds is None else thresholds.copy()

    def build(self, group: NDArray[np.intp], seq: NDArray[np.int64]) -> Partition:
        """The retargeted partition: changed lanes start from their current
        state in ``group``; unchanged lanes keep their running fade; lanes at
        weight 0 that are not in the target are dropped."""
        part, changed = self.part, self.changed
        if self.same:  # every lane stays, in place
            return Partition(
                part.snapping,
                self.index,
                np.where(changed, self.value, part.fromValue),
                np.where(changed, self.toValue, part.toValue),
                np.where(changed, self.weight, part.fromWeight),
                np.where(changed, self.toWeight, part.toWeight),
                np.where(changed, group, part.group),
                seq,
                self.threshold,
            )
        from_value, to_value = self.value.copy(), self.toValue.copy()
        from_weight, to_weight = self.weight.copy(), self.toWeight.copy()
        running = ~changed  # always lanes of the partition
        source = np.cumsum(self.mine)[running] - 1  # their positions in ``part``
        from_value[running] = part.fromValue[source]
        to_value[running] = part.toValue[source]
        from_weight[running] = part.fromWeight[source]
        to_weight[running] = part.toWeight[source]
        group[running] = part.group[source]

        keep = np.flatnonzero(self.aimed | (self.weight > 0.0))
        return Partition(
            part.snapping,
            self.index[keep],
            from_value[keep],
            to_value[keep],
            from_weight[keep],
            to_weight[keep],
            group[keep],
            seq[keep],
            self.threshold[keep],
        )


class _Groups:
    """The timing groups of one retarget: the set's groups, plus new ones
    started at ``now``, interned by timing (with the groups an earlier call
    started at the same instant, too)."""

    def __init__(self, groups: list[FadeState], now: float, timings: Sequence[Timing]) -> None:
        self.groups = groups
        self.now = now
        self.timings = timings
        self.started: set[int] = set()
        self._byTiming = {
            (group.delay, group.duration, group.curve): g
            for g, group in enumerate(groups)
            if g > 0 and group.start == now
        }

    def assign(self, draft: _Draft, rule: TimingRule, part: Part) -> NDArray[np.intp]:
        """A group per lane of ``draft``: new groups for its changed lanes, 0
        for the others (which keep their running group in :meth:`_Draft.build`)."""
        group = np.zeros(draft.index.size, dtype=np.intp)
        entering = draft.changed & draft.aimed
        leaving = draft.changed & ~draft.aimed
        if entering.any():
            if part == "htp":
                falling = (draft.toValue < draft.value * draft.weight)[entering]
            else:
                falling = np.zeros(int(entering.sum()), dtype=np.bool_)
            group[entering] = self._intern(rule.entering(part, draft.at[entering], falling))
        if leaving.any():
            group[leaving] = self._intern(rule.leaving(part, draft.index[leaving]))
        return group

    def _intern(self, indices: NDArray[np.intp]) -> NDArray[np.intp]:
        """The group of each timing index, creating groups as needed."""
        present = np.zeros(len(self.timings), dtype=np.bool_)
        present[indices] = True
        distinct = np.flatnonzero(present)
        table = np.zeros(int(distinct[-1]) + 1, dtype=np.intp)
        for i in distinct:
            timing = self.timings[int(i)]
            key = (timing.delay, timing.duration, timing.curve)
            g = self._byTiming.get(key)
            if g is None:
                g = len(self.groups)
                self.groups.append(FadeState(self.now, timing.delay, timing.duration, timing.curve))
                self._byTiming[key] = g
            self.started.add(g)
            table[i] = g
        return table[indices]

    def completion(self) -> float:
        """The latest end among the groups this retarget started, or ``now``."""
        return max((self.groups[g].end for g in self.started), default=self.now)


def _numbers(draft: _Draft, slots: NDArray[np.intp], rule: SeqRule) -> NDArray[np.int64]:
    """The sequence number of each lane of an LTP or snap ``draft`` under ``rule``."""
    if draft.same:
        seq = draft.part.seq.copy()
    else:
        seq = np.zeros(draft.index.size, dtype=np.int64)
        seq[draft.mine] = draft.part.seq
    if rule.kind == "fresh":
        seq[draft.changed & draft.aimed] = rule.seq
    elif rule.kind == "all":
        seq[:] = rule.seq
    elif rule.kind == "mask" and rule.slots is not None:
        seq[np.isin(slots, rule.slots)] = rule.seq
    seq[seq == 0] = rule.seq
    return seq
