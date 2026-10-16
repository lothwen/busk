"""Contributions, batched per source (spec §7.1, §19).

§7.1 describes one ``Contribution`` object per slot per tick. Done literally
that would be tens of thousands of Python objects per tick. Instead, as §19
suggests ("contributions stored per playback in arrays indexed by slot"),
each **source** exposes its contributions as numpy arrays of lane indices
and values, plus five scalars shared by all of them: ``priority``, ``seq``,
``htpWeight``, ``intensityScale`` and ``ltpWeight`` (phase-2-plan decision 1).

Because every contribution of a source shares ``(priority, seq)``,
compositing whole sources in ``(priority, seq)`` order is exactly §7.3/§7.4
applied per slot. ``tests/reference_resolver.py`` holds the literal per-slot
transcription of §7.7 as a test oracle.

Weights are split the way §7.1 splits them:

* ``htpWeight`` is the source's presence in the HTP merge (the band presence
  ``P`` of §7.4 is the maximum over a band);
* ``intensityScale`` scales its intensities (the fader of a ``master``
  playback, the level of a flash);
* ``ltpWeight`` is how far its LTP values sit on top of what is below them.

Phase 4 fades slot by slot (§5.18), so a source may also carry one weight
per lane: ``htpWeights``, ``ltpWeights`` and ``snapWeights``, parallel to
its position and lane arrays. A per-lane weight multiplies the scalar one:
the scalars keep carrying what applies to the whole source (the release
envelope, the LTP gate, a ``followFader`` fader), the arrays carry the
per-slot fades. ``None`` means 1 everywhere, Phase 2's fast path.

Contributors and sequence runs
------------------------------
In Phase 4 each slot of a source carries its own sequence number: a cue
stack's tracked slots keep the number of the GO that last changed them, and
the programmer numbers each touched slot (§5.18). The resolver still sorts
whole sources, so a **contributor** (a playback's main source, its flash,
the programmer) hands out one source per *run* of its numbers:

1. All numbers come from one global counter, so no two contributors share
   one. Only LTP and snap lanes count: HTP ignores order within a band.
2. A contributor's **boundaries** are the numbers of the *other* present
   contributors of its band that fall strictly between its own lowest and
   highest number.
3. Without boundaries (the usual case) it is one source, sorted at its
   newest number. Otherwise it is one source per run of its numbers between
   consecutive boundaries, each sorted at the newest number in the run; the
   HTP positions go with the newest run.

Every lane then composites in its own ``(priority, seq)`` order, which the
per-slot oracle (``tests/reference_resolver.py``) checks. A plain
:class:`Source` is the trivial contributor (one number, one run);
:class:`SequencedSource` is the general one.

Relative contributions
----------------------
Effects in ``add`` and ``multiply`` mode are not layers of the stack: they
offset or scale whatever the absolute pass resolved (§7.5). Each relative
layer of a running effect hands the resolver one :class:`Relative` per tick:
its lanes, its amounts and its weights. :func:`gather_relatives` collects
the present ones in the order the relative pass applies them,
``(priority, seq, order)`` (phase-5-plan §5.6).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from operator import attrgetter
from typing import Final, Literal, Protocol

import numpy as np
from numpy.typing import NDArray

from busk.compiler.cues import CompiledCue
from busk.engine.fades import ContributionSet, distinct


@dataclass(slots=True, kw_only=True)
class Source:
    """One source's contributions this tick (§7.1, batched).

    The arrays are views of a :class:`~busk.compiler.cues.CompiledCue`, or
    of a fade's evaluated arrays. A runtime owns its sources and mutates the
    scalars in place every tick, so gathering copies no lane data.

    The effective weight of a lane is its scalar times its per-lane weight,
    when the source has per-lane weights (see the module docstring).
    """

    sourceId: str
    priority: int
    seq: int
    htpPos: NDArray[np.intp]  # positions into SlotTable.intensityLanes
    htpValues: NDArray[np.float64]
    htpWeights: NDArray[np.float64] | None = None  # per position, times htpWeight
    ltpLanes: NDArray[np.intp]  # continuous LTP lanes of the logical frame
    ltpValues: NDArray[np.float64]
    ltpWeights: NDArray[np.float64] | None = None  # per LTP lane, times ltpWeight
    snapLanes: NDArray[np.intp]  # lanes that snap (discrete, positionSpeed, colour extras)
    snapValues: NDArray[np.float64]
    snapThresholds: NDArray[np.float64]  # per snap lane: the LTP weight it snaps at
    snapWeights: NDArray[np.float64] | None = None  # per snap lane, times ltpWeight
    htpWeight: float = 0.0
    intensityScale: float = 1.0
    ltpWeight: float = 0.0

    @classmethod
    def of_cue(cls, sourceId: str, priority: int, cue: CompiledCue) -> Source:
        """A source playing ``cue``, absent (all weights 0) until filled."""
        return cls(
            sourceId=sourceId,
            priority=priority,
            seq=0,
            htpPos=cue.htpPos,
            htpValues=cue.htpValues,
            ltpLanes=cue.ltpLanes,
            ltpValues=cue.ltpValues,
            snapLanes=cue.snapLanes,
            snapValues=cue.snapValues,
            snapThresholds=cue.snapThresholds,
        )

    @property
    def present(self) -> bool:
        """Whether the source may affect the frame this tick.

        Only the scalars are checked: a source whose per-lane weights are all
        0 is gathered, and the resolver leaves the frame as it is."""
        return self.htpWeight > 0.0 or self.ltpWeight > 0.0

    # -- the Contributor protocol: a source is a contributor with one run

    @property
    def seqs(self) -> tuple[int, ...]:
        """Its number, if it has LTP or snap lanes (HTP ignores order in a band)."""
        return (self.seq,) if self.ltpLanes.size or self.snapLanes.size else ()

    def sources(self, boundaries: tuple[int, ...]) -> tuple[Source, ...]:
        """Itself: one number never splits."""
        return (self,)


class Contributor(Protocol):
    """Anything that hands sources to the resolver (see the module docstring)."""

    @property
    def priority(self) -> int:
        """Its band; every source it hands out sits in it."""
        ...

    @property
    def present(self) -> bool:
        """Whether it may affect the frame this tick."""
        ...

    @property
    def seqs(self) -> tuple[int, ...]:
        """The distinct numbers of its LTP and snap lanes, ascending."""
        ...

    def sources(self, boundaries: tuple[int, ...]) -> Sequence[Source]:
        """Its sources this tick, split at ``boundaries`` (ascending): the
        other contributors' numbers between its lowest and highest."""
        ...


@dataclass(frozen=True, slots=True)
class Run:
    """A run of one contributor's numbers between two boundaries."""

    seq: int  # the newest number in the run: its sort key
    ltp: NDArray[np.intp]  # positions in the contributor's LTP arrays
    snap: NDArray[np.intp]  # positions in its snap arrays


def split_runs(
    ltpSeqs: NDArray[np.int64], snapSeqs: NDArray[np.int64], boundaries: tuple[int, ...]
) -> list[Run]:
    """Split LTP and snap lanes (given their numbers) into runs between
    consecutive ``boundaries``, oldest run first. Empty runs are left out; the
    last run is the newest, which takes the HTP positions."""
    bounds = np.asarray(boundaries, dtype=np.int64)
    ltpPart = np.searchsorted(bounds, ltpSeqs)
    snapPart = np.searchsorted(bounds, snapSeqs)
    runs = []
    for part in distinct(np.concatenate((ltpPart, snapPart))):
        ltp = np.flatnonzero(ltpPart == part)
        snap = np.flatnonzero(snapPart == part)
        newest = max(int(ltpSeqs[ltp].max(initial=0)), int(snapSeqs[snap].max(initial=0)))
        runs.append(Run(seq=newest, ltp=ltp, snap=snap))
    return runs


_NO_POSITIONS: Final = np.zeros(0, dtype=np.intp)
_NO_VALUES: Final = np.zeros(0, dtype=np.float64)


class SequencedSource:
    """A contributor whose lanes carry their own sequence numbers.

    ``whole`` holds all its lanes, values, weights and scalars, as one
    source. :meth:`assign` declares the number of each LTP and snap lane;
    it must be called again whenever ``whole``'s arrays are replaced (not
    when they are only refilled in place). Without boundaries ``whole`` is
    handed out as it is, sorted at the newest number. With boundaries the
    runs are built once per ``(assignment, boundaries)``; on each call their
    values and weights are refilled from ``whole`` with ``np.take``, and
    their scalars copied, so they follow a ``whole`` evaluated in place.
    """

    def __init__(self, whole: Source) -> None:
        self.whole = whole
        self.seqs: tuple[int, ...] = ()
        self._ltpSeqs = np.zeros(0, dtype=np.int64)
        self._snapSeqs = np.zeros(0, dtype=np.int64)
        self._single = (whole,)
        self._key: tuple[int, ...] | None = None  # the boundaries the runs were built for
        self._runs: list[tuple[Run, Source]] = []
        self._split: list[Source] = []

    @property
    def priority(self) -> int:
        return self.whole.priority

    @property
    def present(self) -> bool:
        return self.whole.present

    def assign(
        self, ltpSeqs: NDArray[np.int64], snapSeqs: NDArray[np.int64], htpSeq: int = 0
    ) -> None:
        """Declare the numbers of ``whole``'s LTP and snap lanes (parallel to
        its lane arrays). ``htpSeq`` is the sort key when it has neither."""
        self._ltpSeqs, self._snapSeqs = ltpSeqs, snapSeqs
        self.seqs = tuple(int(n) for n in distinct(np.concatenate((ltpSeqs, snapSeqs))))
        self.whole.seq = self.seqs[-1] if self.seqs else htpSeq
        self._key = None

    def sources(self, boundaries: tuple[int, ...]) -> Sequence[Source]:
        if not boundaries:
            return self._single
        if boundaries != self._key:
            runs = split_runs(self._ltpSeqs, self._snapSeqs, boundaries)
            self._runs = [(run, self._make(run, run is runs[-1])) for run in runs]
            self._split = [source for _, source in self._runs]
            self._key = boundaries
        self._fill()
        return self._split

    def _make(self, run: Run, newest: bool) -> Source:
        """A source for ``run``, with its lanes; values are filled per call."""
        whole = self.whole

        def per_lane(weights: NDArray[np.float64] | None, size: int) -> NDArray[np.float64] | None:
            return None if weights is None else np.empty(size)

        ltp, snap = run.ltp, run.snap
        return Source(
            sourceId=whole.sourceId,
            priority=whole.priority,
            seq=run.seq,
            htpPos=whole.htpPos if newest else _NO_POSITIONS,
            htpValues=whole.htpValues if newest else _NO_VALUES,
            htpWeights=whole.htpWeights if newest else None,
            ltpLanes=whole.ltpLanes[ltp],
            ltpValues=np.empty(ltp.size),
            ltpWeights=per_lane(whole.ltpWeights, ltp.size),
            snapLanes=whole.snapLanes[snap],
            snapValues=np.empty(snap.size),
            snapThresholds=whole.snapThresholds[snap],
            snapWeights=per_lane(whole.snapWeights, snap.size),
        )

    def _fill(self) -> None:
        """Refill each run's values, weights and scalars from ``whole``."""
        whole = self.whole
        for run, source in self._runs:
            np.take(whole.ltpValues, run.ltp, out=source.ltpValues)
            np.take(whole.snapValues, run.snap, out=source.snapValues)
            if whole.ltpWeights is not None and source.ltpWeights is not None:
                np.take(whole.ltpWeights, run.ltp, out=source.ltpWeights)
            if whole.snapWeights is not None and source.snapWeights is not None:
                np.take(whole.snapWeights, run.snap, out=source.snapWeights)
            source.htpWeight = whole.htpWeight
            source.intensityScale = whole.intensityScale
            source.ltpWeight = whole.ltpWeight


def wire(source: SequencedSource, contributions: ContributionSet, htpSeq: int) -> None:
    """Point ``source``'s whole arrays at ``contributions``' partitions and
    declare its lanes' sequence numbers (``htpSeq``: the sort key without
    LTP or snap lanes). A settled set at full presence drops the per-lane
    weights: the resolver's fast path.

    Call it whenever :attr:`ContributionSet.version` changed: the arrays
    are then new objects. Evaluating the set refills them in place."""
    whole = source.whole
    htp, ltp, snap = contributions.parts
    unit = contributions.unitWeights
    whole.htpPos, whole.htpValues = htp.index, htp.value
    whole.htpWeights = None if unit else htp.weight
    whole.ltpLanes, whole.ltpValues = ltp.index, ltp.value
    whole.ltpWeights = None if unit else ltp.weight
    whole.snapLanes, whole.snapValues = snap.index, snap.value
    whole.snapThresholds = snap.threshold
    whole.snapWeights = None if unit else snap.weight
    source.assign(ltp.seq, snap.seq, htpSeq)


SORT_KEY: Final = attrgetter("priority", "seq")
"""Compositing order (§7.2): ascending priority band, then ascending sequence."""


@dataclass(slots=True, kw_only=True)
class Relative:
    """One relative effect layer's contribution this tick (§7.5,
    phase-5-plan §5.6).

    ``lanes`` are frame lanes (intensity included: the relative pass runs on
    the frame after the HTP merge), unique within the layer. ``amounts`` are
    refilled per tick by the effect's runtime:

    * ``add``: an offset in attribute units, applied as ``v + amount·W``;
    * ``multiply``: a factor in ``0..1``, applied as ``v · lerp(1, amount, W)``.

    ``W`` is ``weight`` (the playback's weight for that kind of lane times
    the effect's presence) times ``weights`` (per lane, while versions of
    the effect mix; ``None`` means 1), times ``1 − A`` where ``A`` is the
    presence of absolute contributions of *higher* bands on the lane
    (continuous suppression, decision 13). ``order`` is the layer's place in
    its cue: it orders relatives that share ``(priority, seq)``. ``clamp`` is
    the registry range an ``add`` result is clipped to after the pass.
    """

    priority: int
    seq: int
    order: int
    op: Literal["add", "multiply"]
    lanes: NDArray[np.intp]
    amounts: NDArray[np.float64]
    weights: NDArray[np.float64] | None = None
    weight: float = 0.0
    clamp: tuple[float, float] | None = None

    @property
    def present(self) -> bool:
        """Whether it may change the frame this tick."""
        return self.weight > 0.0 and self.lanes.size > 0


RELATIVE_ORDER: Final = attrgetter("priority", "seq", "order")
"""The relative pass's order (§7.5): band, then sequence, then place in the cue."""


def gather_relatives(relatives: Iterable[Relative], out: list[Relative]) -> list[Relative]:
    """Refill ``out`` with the present ``relatives``, sorted by
    :data:`RELATIVE_ORDER`, and return it. ``out`` is reused tick after tick."""
    out.clear()
    out.extend(relative for relative in relatives if relative.present)
    out.sort(key=RELATIVE_ORDER)
    return out


def gather(contributors: Iterable[Contributor], out: list[Source]) -> list[Source]:
    """Refill ``out`` with the sources of the present ``contributors``, split
    into sequence runs and sorted by ``(priority, seq)``, and return it.
    ``out`` is reused tick after tick."""
    out.clear()
    present = [contributor for contributor in contributors if contributor.present]
    for contributor in present:
        seqs = contributor.seqs
        if len(seqs) < 2:  # one number never splits
            out.extend(contributor.sources(()))
        else:
            out.extend(contributor.sources(_boundaries(contributor, seqs, present)))
    out.sort(key=SORT_KEY)
    return out


def _boundaries(
    contributor: Contributor, seqs: tuple[int, ...], present: list[Contributor]
) -> tuple[int, ...]:
    """The other present contributors' numbers in ``contributor``'s band that
    fall strictly between its lowest and highest number, ascending."""
    low, high, band = seqs[0], seqs[-1], contributor.priority
    return tuple(
        sorted(
            n
            for other in present
            if other is not contributor and other.priority == band
            for n in other.seqs
            if low < n < high
        )
    )
