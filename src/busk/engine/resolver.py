"""The attribute resolver: many sources → one logical frame (spec §7, stages 6–7).

The resolver composites the gathered sources, sorted by ``(priority, seq)``,
over the frame of uncontrolled slots (the defaults):

**LTP** (§7.3) is a layer stack. Each source moves its lanes from whatever is
below towards its own values by its ``ltpWeight``::

    v = v + (value − v) · w          # w = 1 replaces exactly; w = 0 is skipped

so the newest source wins, a source fading in at 0.25 sits a quarter of the
way from what is below it, a release glides back to the next source down,
and a higher band sits above a lower one whatever the activation order.
Lanes that cannot be interpolated **snap**: each takes the source's value
once the weight reaches the lane's own threshold (start, middle or end).

**HTP** (§7.4) runs per band, over a dense array of every intensity lane::

    P = max(htpWeight)                          # band presence, per lane
    M = max(value · intensityScale · htpWeight) # per lane
    v = v · (1 − P) + M

which is §7.4's ``lerp(v, M / P, P)`` with the division cancelled out.
Where a band does not touch a lane, ``P = M = 0`` and the lane keeps its
value. The base band over a default of 0 is classic HTP; a higher band
crossfades from the result below to its own value by its presence.

**Per-lane weights** (Phase 4). A source fading slot by slot carries one
weight per lane, which multiplies its scalar weight (see
:mod:`busk.engine.contributions`). LTP lanes then use::

    v = v · (1 − w) + value · w      # per lane

which is exact at both ends, ``w = 0`` keeping ``v`` and ``w = 1`` giving
``value``, so a slot whose fade has finished outputs its value to the last
bit (a DMX byte can sit on a rounding boundary). A snap lane takes the
value once its own weight reaches its threshold, and HTP takes the per-lane
weight as the presence and the multiplier of the value. A source without
per-lane weights takes Phase 2's scalar path unchanged.

**Range.** Inputs are clamped at compile time (phase-2-plan decision 8) and
every step is a convex combination (the LTP lerp, and ``v(1 − P) + M`` with
``M ≤ P``), so in-range inputs stay in range without a per-tick clamp.

**The relative pass** (§7.5, phase-5-plan §5.6). Effects in ``add`` and
``multiply`` mode (:class:`~busk.engine.contributions.Relative`) apply after
the absolute pass, on the frame, in ``(priority, seq, order)`` order::

    W = weight · weights · (1 − A)
    add:      v = v + amount · W
    multiply: v = v · (1 + (amount − 1) · W)      # v · lerp(1, amount, W)

``A`` is the **coverage** of the relative's band on the lane: the highest
effective presence there of absolute sources in *higher* bands (LTP lanes by
their LTP weight, intensity by their HTP weight). §7.5 suspends a relative
effect where a higher band controls the slot; taking ``1 − A`` makes that
continuous, so a higher band fading in fades the effect out with it instead
of cutting it when it arrives (decision 13). Sources in the same band or
below never suppress. Snap lanes are not covered: validation keeps relative
layers off snapping attributes, so no relative ever lands on one.

Coverage is built per distinct relative band, walking the sources from the
top band down, and only when some source sits above a relative band.
``add`` results on attributes with a registry range are clipped to it once,
after the pass (§7.7 clamps last); every other step stays in range on its
own (multiply amounts and weights are in ``0..1``). Without relatives the
resolver does exactly what it did before.

**Cost.** Python loops run over sources and bands only, never over slots;
each source costs a few fancy-index operations. The scratch arrays are
allocated once.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import numpy as np
from numpy.typing import NDArray

from busk.compiler.slots import SlotTable
from busk.engine.contributions import Relative, Source


class Resolver:
    """Resolves sources into a logical frame for one slot table."""

    def __init__(self, slots: SlotTable) -> None:
        self._intensity = slots.intensityLanes
        count = len(self._intensity)
        self._value = np.zeros(count)  # v: the HTP composite so far, dense over intensity lanes
        self._presence = np.zeros(count)  # P of the current band
        self._max = np.zeros(count)  # M of the current band
        self._cover = np.zeros(slots.laneCount)  # A: coverage above a relative band, per lane

    def resolve(
        self,
        sources: Sequence[Source],
        base: NDArray[np.float64],
        frame: NDArray[np.float64],
        relatives: Sequence[Relative] = (),
    ) -> None:
        """Write the composite of ``sources`` over ``base`` into ``frame``,
        then apply ``relatives`` to it.

        ``sources`` must be sorted by ``(priority, seq)`` (see
        :func:`~busk.engine.contributions.gather`) and ``relatives`` by
        ``(priority, seq, order)``, present ones only
        (:func:`~busk.engine.contributions.gather_relatives`). ``base`` is
        the frame uncontrolled slots output: the defaults, or a ``--values``
        frame.
        """
        np.copyto(frame, base)
        value, presence, maximum = self._value, self._presence, self._max
        np.take(frame, self._intensity, out=value)
        index, count = 0, len(sources)
        while index < count:
            band = sources[index].priority
            touched = False  # did any source of this band bring intensity?
            while index < count and sources[index].priority == band:
                source = sources[index]
                index += 1
                weight = source.ltpWeight
                if weight > 0.0:
                    lanes = source.ltpLanes
                    if lanes.size:
                        weights = source.ltpWeights
                        if weights is not None:
                            w = _times(weights, weight)
                            below = frame[lanes]
                            frame[lanes] = below * (1.0 - w) + source.ltpValues * w
                        elif weight >= 1.0:
                            frame[lanes] = source.ltpValues
                        else:
                            below = frame[lanes]
                            frame[lanes] = below + (source.ltpValues - below) * weight
                    lanes = source.snapLanes
                    if lanes.size:
                        weights = source.snapWeights
                        if weights is not None:
                            reached = source.snapThresholds <= _times(weights, weight)
                            frame[lanes[reached]] = source.snapValues[reached]
                        elif weight >= 1.0:  # every threshold is at most 1
                            frame[lanes] = source.snapValues
                        else:
                            reached = source.snapThresholds <= weight
                            frame[lanes[reached]] = source.snapValues[reached]
                weight = source.htpWeight
                if weight > 0.0 and source.htpPos.size:
                    if not touched:
                        presence.fill(0.0)
                        maximum.fill(0.0)
                        touched = True
                    positions = source.htpPos
                    weights = source.htpWeights
                    if weights is not None:
                        w = _times(weights, weight)
                        presence[positions] = np.maximum(presence[positions], w)
                        maximum[positions] = np.maximum(
                            maximum[positions], source.htpValues * source.intensityScale * w
                        )
                    else:
                        presence[positions] = np.maximum(presence[positions], weight)
                        maximum[positions] = np.maximum(
                            maximum[positions],
                            source.htpValues * (source.intensityScale * weight),
                        )
            if touched:
                np.subtract(1.0, presence, out=presence)
                value *= presence
                value += maximum
        frame[self._intensity] = value
        if relatives:
            self._relative_pass(sources, frame, relatives)

    def _relative_pass(
        self, sources: Sequence[Source], frame: NDArray[np.float64], relatives: Sequence[Relative]
    ) -> None:
        """Apply ``relatives`` to the resolved ``frame`` (see the module docs)."""
        cover = self._coverage(sources, relatives)
        clamped: list[Relative] = []
        for relative in relatives:
            lanes = relative.lanes
            weight: float | NDArray[np.float64] = relative.weight
            if relative.weights is not None:
                weight = _times(relative.weights, relative.weight)
            above = cover.get(relative.priority)
            if above is not None:
                weight = weight * (1.0 - above[lanes])
            if relative.op == "add":
                frame[lanes] += relative.amounts * weight
                if relative.clamp is not None:
                    clamped.append(relative)
            else:
                frame[lanes] *= 1.0 + (relative.amounts - 1.0) * weight
        for relative in clamped:
            low, high = cast(tuple[float, float], relative.clamp)
            lanes = relative.lanes
            frame[lanes] = np.clip(frame[lanes], low, high)

    def _coverage(
        self, sources: Sequence[Source], relatives: Sequence[Relative]
    ) -> dict[int, NDArray[np.float64]]:
        """The coverage ``A`` of each relative band that has sources above it.

        Sources are walked from the top band down into one running maximum;
        each relative band, highest first, takes the coverage of everything
        above it (a copy, unless it is the last band: then the running array
        itself). A band with nothing above it is left out: ``A = 0``."""
        bands = sorted({relative.priority for relative in relatives}, reverse=True)
        running = self._cover
        cover: dict[int, NDArray[np.float64]] = {}
        index, raised = len(sources), False
        for k, band in enumerate(bands):
            while index > 0 and sources[index - 1].priority > band:
                index -= 1
                if not raised:
                    running.fill(0.0)
                    raised = True
                self._raise(running, sources[index])
            if raised:
                cover[band] = running if k == len(bands) - 1 else running.copy()
        return cover

    def _raise(self, running: NDArray[np.float64], source: Source) -> None:
        """Raise ``running`` to ``source``'s effective presence on its LTP lanes
        and intensity lanes."""
        weight = source.ltpWeight
        lanes = source.ltpLanes
        if weight > 0.0 and lanes.size:
            weights = source.ltpWeights
            presence = weight if weights is None else _times(weights, weight)
            running[lanes] = np.maximum(running[lanes], presence)
        weight = source.htpWeight
        if weight > 0.0 and source.htpPos.size:
            lanes = self._intensity[source.htpPos]
            weights = source.htpWeights
            presence = weight if weights is None else _times(weights, weight)
            running[lanes] = np.maximum(running[lanes], presence)


def _times(weights: NDArray[np.float64], weight: float) -> NDArray[np.float64]:
    """Per-lane weights times the source's scalar weight. A latched playback
    fading slot by slot has a scalar of 1: then the array is used as it is."""
    return weights if weight == 1.0 else weights * weight
