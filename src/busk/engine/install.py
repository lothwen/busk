"""Installs: how live edits reach the engine (phase-3-plan §5.7).

The session (the single writer of editing state) never touches the engine.
After every programmer change or show edit it puts one immutable
:class:`Install` on the engine's command queue, behind any command that was
queued before it, so the engine sees edits in commit order and a programmer
frame always arrives after the compiled show it was built against. The
engine applies it at stage 1 of the next tick.

An install carries

* a new :class:`~busk.compiler.compile.CompiledShow` and, when the slot
  keys changed, a **remap** (old slot index → new, ``-1`` = gone), or
  ``None`` for a programmer-only update; and
* a :class:`ProgrammerFrame`: the programmer's values resolved to lanes
  against that compiled show; and
* the show's :data:`Stamp` (Phase 7), which names it across processes: a
  restarted console whose recovered show has the stamp of the engine's
  show sends only its programmer (phase-7-plan decision 8). The engine
  itself ignores it; and
* its **causes** (Phase 7, phase-7-plan §5.21): why the session made it,
  as the JSON of event-log records, which the engine records at the tick
  that applies it (:mod:`busk.persistence.eventlog`). Programmer changes
  that installed nothing (a selection) ride on the next install, before its
  own cause. None while logging is off.

**Live swap** (§6.4). Swapping in a compiled show keeps the runtime state:
per-slot runtime arrays are remapped with one vectorised operation (the
running fades of the playbacks and the programmer; a ``--values`` base
frame, lane by lane), and each running playback is re-pointed at its cue in
the new show. Since Phase 4 the playbacks fade to their edited cues with
the cue's timing, and the programmer to its new frame over its fade time
(phase-4-plan decision 14).

**The programmer as a source** (§7.6). Unless blind, the programmer is one
more source at band :data:`PROGRAMMER_PRIORITY` with an intensity scale of
1: its intensities override the playbacks (even lower ones) and its LTP
values sit on top of them. Masters and blackout still apply after the
resolve. Each programmer slot carries its own sequence number: an install
gives every *touched* slot (whose source changed) one fresh number from the
global counter. The resolver composites whole sources in ``(priority,
seq)`` order, so the programmer is a contributor that splits into sequence
runs (:mod:`busk.engine.contributions`). Usually there is no other band-100
source and the programmer is a single source.

**Programmer fades** (phase-4-plan §5.10). The programmer's slots are a
:class:`~busk.engine.fades.ContributionSet`. Each install retargets it at
the frame's lanes (at nothing while blind) with one linear fade of the
frame's ``fadeTime``: a value change fades from where the slot is, a clear
or ``BLIND on`` fades the slots out, ``BLIND off`` fades them in. Lanes
that fade out keep their sequence number, so they hold their place in the
band until they are gone. A fade time of 0 snaps, as in Phase 3.

**Programmer effects** (phase-5-plan §5.10). The frame also carries the
programmer's effect instances, compiled against its show, and the ids a
command added or changed (``touchedEffects``). They run in an
:class:`~busk.engine.effects.EffectBank` at band 100, each instance one
more contributor next to the static values, ordered with them by sequence
number. Each install retargets the bank (at nothing while blind) over the
frame's fade time: instances enter, change and leave over it, on their own
clocks. The install's one number goes to the touched instances too, and an
install that touches only effects still takes one.

**Highlight** (phase-7-plan decision 12, §5.12). While the programmer's
highlight mode is on, the frame carries a :class:`Highlight` of the
selected targets, built by the session. It is not a source: the engine's
safety stage writes its lanes after the masters (before park, blackout and
limits, which win over it), and its ``highlightDmx`` bytes over the
converted universes. It is live even while the programmer is blind.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

import numpy as np
from numpy.typing import NDArray

from busk.compiler.compile import CompiledShow
from busk.compiler.cues import EMPTY_CUE, CompiledCue
from busk.compiler.effects import CompiledEffect
from busk.compiler.slots import SlotTable
from busk.engine.contributions import SequencedSource, Source, wire
from busk.engine.effects import EffectBank, EffectScalars, EffectTiming, StrobeCap
from busk.engine.fades import ContributionSet, SeqRule, Timing, Uniform
from busk.engine.masters import SpeedMasterRuntime
from busk.model.common import MasterId

PROGRAMMER_PRIORITY: Final = 100
"""The programmer's band (§7.2)."""

_NO_SLOTS: Final = np.zeros(0, dtype=np.int32)
_NO_SLOTS.flags.writeable = False
_NO_LANES: Final = np.zeros(0, dtype=np.float64)
_NO_LANES.flags.writeable = False


@dataclass(frozen=True, kw_only=True)
class Highlight:
    """The programmer's highlight: what the selected targets show while
    ``HIGHLIGHT`` is on (decision 12). Built by the session.

    ``lanes`` are the intensity, shutter and colour lanes of the selected
    targets, with ``values`` to force there: intensity 1, the shutter's
    ``open`` option, colour white (extras ``NaN``: derive). ``bytes`` are
    flat positions (``row × 512 + address``) in the universe buffers of the
    targets' other channels that have a ``highlightDmx``, with
    ``byteValues`` its coarse, fine and ultra bytes. Pan, tilt and parked
    slots are never in either.
    """

    lanes: NDArray[np.intp]
    values: NDArray[np.float64]
    bytes: NDArray[np.intp]
    byteValues: NDArray[np.uint8]


@dataclass(frozen=True, kw_only=True)
class ProgrammerFrame:
    """The programmer resolved against one compiled show; built by the session.

    ``slots`` are the slot indices that hold a programmer value, ascending,
    with ``lanes`` their lanes concatenated in slot order. ``cue`` holds the
    same values split the way the resolver merges them (HTP, continuous LTP,
    snap lanes). ``touched`` are the slots whose source changed with this
    update (all of them when blind was switched off). ``fadeTime`` is the
    programmer's fade time: the engine fades to this frame over it.
    ``effects`` are the programmer's effect instances that compile (dormant
    ones are left out), in programmer order, and ``touchedEffects`` the ids
    among them that this update added or changed (all when blind was
    switched off). ``highlight`` is the highlight while that mode is on and
    there is something to highlight, else ``None``.
    """

    slots: NDArray[np.int32]
    lanes: NDArray[np.float64]
    touched: NDArray[np.int32]
    blind: bool
    fadeTime: float = 0.0
    cue: CompiledCue
    effects: tuple[CompiledEffect, ...] = ()
    touchedEffects: frozenset[str] = frozenset()
    highlight: Highlight | None = None


EMPTY_FRAME: Final = ProgrammerFrame(
    slots=_NO_SLOTS, lanes=_NO_LANES, touched=_NO_SLOTS, blind=False, cue=EMPTY_CUE
)
"""An empty programmer."""


type Stamp = tuple[str, int]
"""A show's stamp: ``(sessionId, n)`` for the ``n``-th show a session
installed (``0``: the show it started with). Equal stamps mean equal shows."""


@dataclass(frozen=True, kw_only=True)
class Install:
    """One live update for the engine, applied at stage 1 of a tick."""

    compiled: CompiledShow | None  # None: a programmer-only update
    remap: NDArray[np.int32] | None  # old slot index → new (−1 = gone); None: same slot keys
    programmer: ProgrammerFrame
    stamp: Stamp | None = None  # the stamp of `compiled` (None: unstamped, or no show)
    causes: tuple[bytes, ...] = ()
    """The event-log records of why it was made, in order: JSON objects
    without their time (``{"e": …}``, ``{"p": …}``, …; see
    :mod:`busk.persistence.eventlog`)."""
    source: object = field(default=None, compare=False, repr=False)
    """The session state this install shows, ``(show, programmer)``. Opaque
    to the engine and never sent to another process: a console's
    :class:`~busk.process.links.RemoteBus` keeps the last one, for the
    event-log record of its next reconnect."""


class ProgrammerRuntime:
    """The engine side of the programmer: its slots' fades and sequence numbers.

    Owned by the engine thread. It is a
    :class:`~busk.engine.contributions.Contributor` at band
    :data:`PROGRAMMER_PRIORITY`, backed by a
    :class:`~busk.engine.fades.ContributionSet` (see the module docstring):
    a :class:`~busk.engine.contributions.SequencedSource` whose lanes carry
    their slot's number, split into runs only when another band-100
    source's number falls between the programmer's own. It is present while
    the set holds any lane, fading out included.

    Its effects run in :attr:`bank`, whose instances are contributors of
    their own (the engine gathers them after the static values). ``speed``
    and ``sizeLevels`` are the engine's speed masters and size levels, and
    ``cap`` its strobe cap, shared with the playbacks: programmer effects
    lock to the same beat, follow the same size masters and run under the
    same cap, at full dynamics otherwise.
    """

    priority: Final = PROGRAMMER_PRIORITY

    def __init__(
        self,
        slots: SlotTable,
        speed: Mapping[MasterId, SpeedMasterRuntime] | None = None,
        sizeLevels: Mapping[MasterId, float] | None = None,
        cap: StrobeCap | None = None,
    ) -> None:
        self.contributions = ContributionSet(slots.laneSlot)
        self._source = SequencedSource(_source(EMPTY_CUE))
        self._seq = 0  # the last number an install took: the sort key of HTP-only lanes
        self._wired = -1  # the contributions version the source's arrays point at
        self.bank = EffectBank(
            "programmer", PROGRAMMER_PRIORITY, {} if speed is None else speed, cap=cap
        )
        """The programmer's running effects (phase-5-plan §5.10)."""
        self._scalars = EffectScalars(sizeLevels={} if sizeLevels is None else sizeLevels)
        self.highlight: Highlight | None = None
        """The last frame's highlight, which the engine's safety stage writes
        (Phase 7). Not faded, and live while blind."""

    @property
    def present(self) -> bool:
        """Whether the programmer may affect the live output: it holds lanes."""
        return not self.contributions.empty

    @property
    def seqs(self) -> tuple[int, ...]:
        """The distinct numbers of its LTP and snap lanes, ascending."""
        return self._source.seqs

    def sources(self, boundaries: tuple[int, ...]) -> Sequence[Source]:
        """The programmer's sources, split at ``boundaries`` (see
        :class:`~busk.engine.contributions.SequencedSource`)."""
        return self._source.sources(boundaries)

    def swap(
        self, slots: SlotTable, maps: tuple[NDArray[np.intp], NDArray[np.intp]] | None
    ) -> None:
        """Follow a new slot table: running fades move to their lanes in
        ``slots`` (``maps`` from :func:`lane_maps`; ``None`` when the table
        is the same). A frame built against ``slots`` must be installed next.
        Running effects move with them."""
        if maps is not None:
            self.contributions.remap(slots.laneSlot, *maps)
            self.bank.remap(*maps)

    def install(self, frame: ProgrammerFrame, now: float, next_seq: Callable[[], int]) -> None:
        """Fade to ``frame`` from ``now`` over its ``fadeTime``.

        One number from ``next_seq`` covers the whole update (Phase 3). The
        touched slots and effects take it, and so do lanes and effects that
        enter without one (a slot that came back with an undo, or that a
        preset edit defined; an effect whose template an undo restored).
        While blind nothing takes a number: the set and the bank only fade
        out, and leaving blind touches everything. The bank's clocks then
        follow their speed masters' current steps, which a swap may have
        edited (or the strobe cap). The frame's highlight is taken as it is.
        """
        self.highlight = frame.highlight
        contributions = self.contributions
        contributions.evaluate(now)  # lanes that have faded out are dropped first
        target = EMPTY_CUE if frame.blind else frame.cue
        effects = () if frame.blind else frame.effects
        numbered = not frame.blind and (
            frame.touched.size > 0
            or bool(frame.touchedEffects)
            or self._entering(target)
            or self._effects_entering(effects, now)
        )
        rule = SeqRule.keep(0)  # takes no number: nothing enters
        if numbered:
            self._seq = next_seq()
            rule = SeqRule.mask(self._seq, frame.touched.astype(np.intp))
        timing = Timing(duration=frame.fadeTime)
        contributions.retarget(now, target, Uniform(timing), rule)
        self.bank.retarget(
            now, effects, EffectTiming.uniform(timing), rule, touched=frame.touchedEffects
        )
        self.bank.rerate(now, None)

    def _effects_entering(self, effects: Sequence[CompiledEffect], now: float) -> bool:
        """Whether one of ``effects`` is not running at ``now`` (one that has
        faded out by then is not, whether or not a tick dropped it)."""
        return not all(self.bank.running(effect.key, now) for effect in effects)

    def _entering(self, target: CompiledCue) -> bool:
        """Whether ``target`` has an LTP or snap lane the set does not hold
        (HTP lanes carry no number)."""
        contributions = self.contributions
        return not (
            np.isin(target.ltpLanes, contributions.ltp.index).all()
            and np.isin(target.snapLanes, contributions.snap.index).all()
        )

    def update(self, now: float) -> None:
        """Evaluate the fades at ``now`` (stages 3–4), and re-point the source
        when the set's arrays were replaced; then the effects."""
        contributions = self.contributions
        contributions.evaluate(now)
        if contributions.version != self._wired:
            wire(self._source, contributions, self._seq)
            self._wired = contributions.version
        if self.bank.active:
            self.bank.update(now, self._scalars)


def _source(cue: CompiledCue) -> Source:
    """A fully present programmer source playing ``cue``."""
    source = Source.of_cue("programmer", PROGRAMMER_PRIORITY, cue)
    source.htpWeight = source.intensityScale = source.ltpWeight = 1.0
    return source


def remap_lanes(
    values: NDArray[np.float64],
    old: SlotTable,
    new: SlotTable,
    remap: NDArray[np.int32] | None,
) -> NDArray[np.float64]:
    """Carry a logical frame from ``old``'s lanes to ``new``'s (vectorised).

    Each slot's lanes move to its new slot when it still exists with the same
    lane count; every other lane of the result is ``new``'s default.
    """
    result = np.array(new.defaultFrame)
    if values.size == 0:
        return result
    lane_map, _ = lane_maps(old, new, remap)
    keep = lane_map >= 0
    result[lane_map[keep]] = values[keep]
    return result


def lane_maps(
    old: SlotTable, new: SlotTable, remap: NDArray[np.int32] | None
) -> tuple[NDArray[np.intp], NDArray[np.intp]]:
    """Where ``old``'s lanes and intensity positions are in ``new`` (−1: gone).

    A slot's lanes move with the slot (``remap``: old slot index → new, −1 =
    gone; ``None``: the same slot keys) when it keeps its lane count. The
    second map does the same for positions in ``intensityLanes``. Runtimes
    that hold per-lane state (the playbacks' fades) follow a live swap with
    them.
    """
    owner = old.laneSlot
    lane_map = np.full(owner.size, -1, dtype=np.intp)
    if owner.size and new.laneSlot.size:
        first_old, count_old = _lane_runs(old)
        first_new, count_new = _lane_runs(new)
        target = owner if remap is None else remap[owner].astype(np.intp)
        keep = (target >= 0) & (target < len(count_new))
        safe = np.where(keep, target, 0)
        keep &= count_new[safe] == count_old[owner]
        position = np.arange(owner.size) - first_old[owner]
        lane_map[keep] = (first_new[safe] + position)[keep]
    moved = lane_map[old.intensityLanes]
    intensity = new.intensityLanes
    at = np.minimum(np.searchsorted(intensity, moved), max(intensity.size - 1, 0))
    found = (moved >= 0) & (intensity.size > 0)
    if intensity.size:
        found &= intensity[at] == moved
    pos_map = np.where(found, at, -1).astype(np.intp)
    return lane_map, pos_map


def keys_remap(old: SlotTable, new: SlotTable) -> NDArray[np.int32] | None:
    """Old slot index → new slot index (``-1``: gone), matched by
    :attr:`SlotTable.keys`; ``None`` when the keys are the same, in order.

    The session computes remaps from the full tables. The engine host
    computes this one for an install that came without a remap from a
    console that never saw the engine's show: a restarted console installing
    the show it recovered (phase-7-plan decision 8).
    """
    if old.keys == new.keys:
        return None
    index = {key: k for k, key in enumerate(new.keys)}
    remap = np.array([index.get(key, -1) for key in old.keys], dtype=np.int32)
    remap.flags.writeable = False
    return remap


def _lane_runs(slots: SlotTable) -> tuple[NDArray[np.intp], NDArray[np.intp]]:
    """Each slot's first lane and lane count, from ``laneSlot``."""
    lane_slot = slots.laneSlot
    if lane_slot.size == 0:
        return np.zeros(0, dtype=np.intp), np.zeros(0, dtype=np.intp)
    starts = np.flatnonzero(np.r_[True, lane_slot[1:] != lane_slot[:-1]]).astype(np.intp)
    counts = np.diff(np.r_[starts, lane_slot.size]).astype(np.intp)
    return starts, counts
