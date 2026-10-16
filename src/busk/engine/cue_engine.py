"""The cue engine: how a sequence moves between cues (spec §8.1, §9.2).

Pure functions over a :class:`~busk.compiler.playbacks.CompiledCueList`, so
the sequence rules can be tested without an engine (phase-4-plan §5.6), and
:class:`CueTiming`, the timing rule of a fade into a cue. The playback
runtime (:mod:`busk.engine.playback_runtime`) applies them.

Sequence rules (phase-4-plan decision 9)
----------------------------------------
* **GO** moves to the next cue. At the last cue it wraps to the first
  (``wrap``), or releases the playback (``releaseAtEnd``), or else
  re-asserts the current cue. A one-cue list that wraps lands on its own
  cue, which the runtime treats as a re-assert too.
* **BACK** moves to the previous cue, or wraps to the last one. At the
  first cue without ``wrap`` it does nothing.
* **Auto-GO.** After a forward move the *next* cue's trigger is scheduled:
  ``wait d`` fires ``d`` seconds after the transition started, ``follow d``
  ``d`` seconds after it completed (the latest end among the fades it
  started). ``go`` cues wait for a manual GO. There is no auto-GO when the
  list has no next cue, or when the next cue is the current one.
"""

from __future__ import annotations

from typing import Final, Literal

import numpy as np
from numpy.typing import NDArray

from busk.compiler.cues import CompiledCue
from busk.compiler.playbacks import CompiledCueList
from busk.compiler.slots import FAMILY_CODES
from busk.engine.curves import curve_of
from busk.engine.fades import Part, Timing

type AtEnd = Literal["release", "reassert"]
"""What GO does at the last cue of a list that does not wrap."""

_INTENSITY: Final = FAMILY_CODES["intensity"]


def next_cue(cues: CompiledCueList, current: int) -> int | AtEnd:
    """Where GO goes from cue index ``current``: the next index, the first
    one when the list wraps, else ``"release"`` (``releaseAtEnd``) or
    ``"reassert"``."""
    if current + 1 < len(cues.cues):
        return current + 1
    if cues.wrap and cues.cues:
        return 0
    return "release" if cues.releaseAtEnd else "reassert"


def previous_cue(cues: CompiledCueList, current: int) -> int | None:
    """Where BACK goes from cue index ``current``: the previous index, the
    last one when the list wraps, else ``None`` (nothing happens)."""
    if current > 0:
        return current - 1
    if cues.wrap and cues.cues:
        return len(cues.cues) - 1
    return None


def schedule(cues: CompiledCueList, current: int, started: float, completes: float) -> float | None:
    """When the cue after ``current`` fires by itself, for a transition into
    ``current`` that started at ``started`` and completes at ``completes``:
    ``wait d`` → ``started + d``, ``follow d`` → ``completes + d``. ``None``
    for a ``go`` cue, and when GO would not move to another cue."""
    after = next_cue(cues, current)
    if isinstance(after, str) or after == current:
        return None
    cue = cues.cues[after]
    if cue.trigger == "wait":
        return started + cue.triggerDelay
    if cue.trigger == "follow":
        return completes + cue.triggerDelay
    return None


class CueTiming:
    """The :class:`~busk.engine.fades.TimingRule` of a fade into ``cue``
    (phase-4-plan decision 6).

    A lane in the cue takes its own timing: HTP lanes the in timing when
    their intensity rises and the out timing when it falls, every other
    lane its LTP or snap timing. A lane that leaves takes the cue's timing
    for its family, ``cue.leave[family]``, found through ``laneFamily``
    (the slot table's family code per lane).
    """

    def __init__(self, cue: CompiledCue, laneFamily: NDArray[np.int8]) -> None:
        self.cue = cue
        self.laneFamily = laneFamily
        self.timings = tuple(
            Timing(duration=t.fade, delay=t.delay, curve=curve_of(t.curve)) for t in cue.timings
        )

    def entering(
        self, part: Part, at: NDArray[np.intp], falling: NDArray[np.bool_]
    ) -> NDArray[np.intp]:
        cue = self.cue
        if part == "htp":
            return np.where(falling, cue.htpOut[at], cue.htpIn[at]).astype(np.intp)
        timing = cue.ltpTiming if part == "ltp" else cue.snapTiming
        return timing[at].astype(np.intp)

    def leaving(self, part: Part, index: NDArray[np.intp]) -> NDArray[np.intp]:
        leave = self.cue.leave
        if part == "htp":  # every HTP lane is an intensity
            return np.full(index.size, leave[_INTENSITY], dtype=np.intp)
        return leave[self.laneFamily[index]].astype(np.intp)
