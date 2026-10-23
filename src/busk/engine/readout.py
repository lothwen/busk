"""Reading the engine's output back per fixture element (GAP-01 of
``docs/dev/tui/engine-gaps.md``).

A display that shows what each fixture does (its intensity, colour, position
and what drives them) needs the logical values the engine resolved, not the
DMX bytes: turning bytes back into values would need the patch, fine bytes,
inversion, curves and colour mixing. So the readout reads the logical frame
as the safety stage left it (stage 11), in two halves:

* :func:`capture`, on the engine thread at the end of a tick: a copy of that
  frame, and per lane what drives it. The sources' and relatives' share is
  :meth:`Resolver.attribute <busk.engine.resolver.Resolver.attribute>`;
  the safety stage's own comes on top: the highlight is the programmer's,
  and a parked lane is nobody's. It allocates two arrays and a small tuple,
  so the engine captures only while someone reads the output
  (:attr:`Engine.captureOutput <busk.engine.loop.Engine.captureOutput>`).
* :func:`read_output`, on any thread: the public
  :class:`~busk.engine.snapshot.OutputSnapshot` of a capture, with the
  readout lookups of the show the tick ran
  (:class:`~busk.compiler.readout.ReadoutLayout`). numpy does the per-lane
  work; one Python loop over the elements builds the
  :class:`~busk.engine.snapshot.FixtureOutput`\\ s.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

import numpy as np
from numpy.typing import NDArray

from busk.compiler.compile import CompiledShow
from busk.compiler.readout import emitted
from busk.compiler.slots import FAMILIES, FAMILY_CODES
from busk.engine.contributions import PROGRAMMER, Origin, OriginKind, Relative, Source
from busk.engine.install import Highlight
from busk.engine.resolver import Resolver
from busk.engine.snapshot import FixtureOutput, OutputSnapshot, OutputSource

SOURCES: Final[tuple[OutputSource, ...]] = ("none", "playback", "effect", "programmer")
"""The output sources by rank: a family's source is the highest-ranked one
that drives one of its lanes."""

_RANKS: Final[Mapping[OriginKind, int]] = {"playback": 1, "effect": 2, "programmer": 3}
_INTENSITY: Final = FAMILY_CODES["intensity"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Capture:
    """The engine's output at one tick, raw: what :func:`read_output` reads.

    ``owners`` holds, per lane, the index in ``origins`` of what drives it,
    ``-1`` for nothing. Both arrays are read-only.
    """

    seq: int  # the tick's, as in its Frame
    time: float
    compiled: CompiledShow  # the show the tick ran
    values: NDArray[np.float64]  # the logical frame after the safety stage
    owners: NDArray[np.intp]
    origins: tuple[Origin | None, ...]


def capture(
    *,
    seq: int,
    time: float,
    compiled: CompiledShow,
    frame: NDArray[np.float64],
    resolver: Resolver,
    sources: Sequence[Source],
    relatives: Sequence[Relative],
    highlight: Highlight | None,
) -> Capture:
    """Capture ``frame`` (the logical frame after the safety stage) and what
    drives each of its lanes: ``sources`` and ``relatives`` as the tick
    resolved them with ``resolver``, then the programmer's ``highlight``,
    then park. Engine thread only, before the next tick changes them."""
    owners = np.empty(frame.size, dtype=np.intp)
    resolver.attribute(sources, relatives, owners)
    origins = (
        *(source.origin for source in sources),
        *(relative.origin for relative in relatives),
        PROGRAMMER,
    )
    if highlight is not None:
        owners[highlight.lanes] = len(origins) - 1
    safety = compiled.safety
    owners[safety.parkIntensity] = -1
    owners[safety.parkLanes] = -1
    owners.flags.writeable = False
    values = frame.copy()
    values.flags.writeable = False
    return Capture(
        seq=seq, time=time, compiled=compiled, values=values, owners=owners, origins=origins
    )


def read_output(captured: Capture) -> OutputSnapshot:
    """The public form of ``captured`` (see :class:`~busk.engine.snapshot.FixtureOutput`)."""
    layout = captured.compiled.readout
    count = len(layout.numbers)
    # Per origin, and a last entry for "nothing" (owner −1): rank and playback number.
    ranks = np.zeros(len(captured.origins) + 1, dtype=np.intp)
    numbers: list[int | None] = [None] * (len(captured.origins) + 1)
    playbacks = captured.compiled.playbacks
    for k, origin in enumerate(captured.origins):
        if origin is None:
            continue
        ranks[k] = _RANKS[origin.kind]
        playback = None if origin.playback is None else playbacks.get(origin.playback)
        numbers[k] = None if playback is None else playback.number
    # Lane −1 reads the last entry of each padded array: NaN, nothing, rank −1.
    values = np.append(captured.values, math.nan)
    owners = np.append(captured.owners, -1)
    lane_ranks = np.append(ranks[captured.owners], -1)

    families = np.full((count, len(FAMILIES)), -1, dtype=np.intp)
    if layout.runStart.size:
        best = np.maximum.reduceat(lane_ranks[:-1], layout.runStart)
        np.maximum.at(families, (layout.runElement, layout.runFamily), best)
    intensity, rgb = emitted(layout, values)
    dimmer = np.where(layout.intensity >= 0, layout.intensity, layout.master)
    families[:, _INTENSITY] = lane_ranks[dimmer]
    drivers = owners[dimmer]

    fixtures = tuple(
        FixtureOutput(
            number=number,
            element=element,
            intensity=level,
            color=(color[0], color[1], color[2]) if colored else None,
            pan=_degrees(pan),
            tilt=_degrees(tilt),
            zoom=_degrees(zoom),
            source=MappingProxyType(
                {FAMILIES[code]: SOURCES[rank] for code, rank in enumerate(row) if rank >= 0}
            ),
            playback=numbers[driver],
        )
        for number, element, level, color, colored, pan, tilt, zoom, row, driver in zip(
            layout.numbers,
            layout.elements,
            intensity.tolist(),
            rgb.tolist(),
            layout.colored.tolist(),
            values[layout.pan].tolist(),
            values[layout.tilt].tolist(),
            values[layout.zoom].tolist(),
            families.tolist(),
            drivers.tolist(),
            strict=True,
        )
    )
    return OutputSnapshot(seq=captured.seq, time=captured.time, fixtures=fixtures)


def _degrees(value: float) -> float | None:
    """A lane read through the padding: ``NaN`` means the element has no such lane."""
    return None if math.isnan(value) else value
