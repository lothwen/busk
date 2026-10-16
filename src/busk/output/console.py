"""Console output: a debug sink of the output scheduler (spec §14).

``busk run --console`` adds this sink to the output scheduler
(:mod:`busk.output.scheduler`), which services it on the output thread after
the routes, once per cycle. It is a debugging aid, not a route protocol
(phase-1.5-plan decision 9).

Each :meth:`ConsoleOutput.service` prints the universes of the engine's
latest frame whose bytes changed since they were last printed, so a static
show prints exactly once. Universes are named from the frame's output layout
when it has one (a live edit may add or reorder universes) and tracked by
id.

Line format (pinned by tests)::

    [frame 1] U1 Stage: 101=255 102=255

The listed channels are the non-zero ones, 1-based; an all-zero universe
prints ``all 0``.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Protocol, TextIO

from busk.compiler.compile import CompiledUniverse
from busk.engine.loop import Frame


class FrameSource(Protocol):
    """Anything that publishes frames, such as :class:`~busk.engine.loop.Engine`."""

    @property
    def latest(self) -> Frame | None: ...


class ConsoleOutput:
    """Prints changed universes of the latest frame to a text stream."""

    def __init__(
        self,
        engine: FrameSource,
        universes: Sequence[CompiledUniverse] = (),
        stream: TextIO | None = None,
    ) -> None:
        """``universes`` name the rows of frames without a layout (hand-built
        ones); an engine's frames carry their own."""
        self._engine = engine
        self._universes = tuple(universes)
        self._stream = sys.stdout if stream is None else stream
        self._last_frame: Frame | None = None
        self._printed: dict[str, bytes] = {}  # universe id → bytes last printed

    def service(self, now: float) -> None:
        """Print every universe that changed since it was last printed.

        ``now`` is the output cycle's time. Printing does not need it; it
        keeps the call shaped like the drivers' ``send``.
        """
        frame = self._engine.latest
        if frame is None or frame is self._last_frame:
            return
        self._last_frame = frame
        universes = self._universes if frame.layout is None else frame.layout.universes
        wrote = False
        for universe, data in zip(universes, frame.universes, strict=True):
            if data != self._printed.get(universe.id):
                self._printed[universe.id] = data
                self._stream.write(_format_line(frame.seq, universe, data) + "\n")
                wrote = True
        if wrote:
            self._stream.flush()


def _format_line(seq: int, universe: CompiledUniverse, data: bytes) -> str:
    channels = " ".join(f"{index + 1}={value}" for index, value in enumerate(data) if value)
    return f"[frame {seq}] U{universe.number} {universe.name}: {channels or 'all 0'}"
