"""The safety stage (spec §12, stage 11; phase-7-plan decision 11, §5.10).

It runs on the logical frame after the group and grand masters and before
profile conversion. Like the masters, it acts on the output frame only and
never on runtime state, so releasing any of its steps returns exactly to
the live look. The order is decision 11's:

=====  =========================================================
Step   On the logical frame
=====  =========================================================
1–2    group masters, grand master (:func:`~busk.engine.masters.apply_masters`)
3      highlight: the selected targets' intensity, shutter and colour
       (:class:`~busk.engine.install.Highlight`)
4      park, intensity lanes: forced, so the masters do not scale them
5      blackout: every intensity lane to 0, parked ones included
       (§12: park overrides blackout only for non-intensity slots)
6      park, every other lane
7      limits: pan and tilt clamped to the fixture's limits, intensity to
       its ``intensityMax``; parked values are clamped too
8      strobe cap: ``strobeRate`` lanes to ``safety.strobeMaxHz``
=====  =========================================================

Highlight sits before park, blackout and limits, so all three win over it
(decision 12). Its ``highlightDmx`` bytes are written after conversion by
the engine, not here.

A frame with no highlight, park entries, limits or cap costs one test per
step.
The stage reads :class:`~busk.compiler.safety.CompiledSafety`, so a live
swap brings the new show's park and limits in at the next tick.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from busk.compiler.safety import CompiledSafety
from busk.engine.install import Highlight


def apply_safety(
    frame: NDArray[np.float64],
    safety: CompiledSafety,
    intensity: NDArray[np.intp],
    *,
    blackout: bool,
    highlight: Highlight | None = None,
) -> None:
    """Run steps 3–8 on the logical ``frame`` in place; ``intensity`` are the
    slot table's intensity lanes, which blackout zeroes, and ``highlight``
    the programmer's highlight (``None`` when off)."""
    if highlight is not None:
        frame[highlight.lanes] = highlight.values
    if safety.parkIntensity.size:
        frame[safety.parkIntensity] = safety.parkIntensityValues
    if blackout:
        frame[intensity] = 0.0
    if safety.parkLanes.size:
        frame[safety.parkLanes] = safety.parkValues
    if safety.limitLanes.size:
        lanes = safety.limitLanes
        frame[lanes] = np.clip(frame[lanes], safety.limitLow, safety.limitHigh)
    if safety.strobeLanes.size:
        lanes = safety.strobeLanes
        assert safety.strobeMaxHz is not None
        frame[lanes] = np.minimum(frame[lanes], safety.strobeMaxHz)
