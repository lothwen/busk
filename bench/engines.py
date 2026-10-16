"""The engine under a benchmark: a thread, or a real engine process (phase-7-plan §5.26).

``bench/edit_latency.py`` and ``bench/surface_load.py`` measure the engine
while a session edits the show or surfaces move faders. With
``--processes`` they measure the Phase 7 layout: the engine runs in an
engine host process, and the bench plays both the root and the console.
As the root, :class:`ProcessEngine` spawns the engine host, serves its
control link (frames, ``STATS``, ``FINAL``) and hands it a link pair with
``ATTACH``; as the console, its :attr:`~ProcessEngine.bus` is a
:class:`~busk.process.links.RemoteBus` on the other end, which the
session submits and installs through. Without ``--processes``,
:class:`ThreadEngine` runs the engine on a thread of the bench, as
``busk run --threads`` does.

Both have the same face: build one with the compiled show and the clock,
build the session on :attr:`bus`, :meth:`start`, read :meth:`stats`, and
:meth:`stop`.
"""

from __future__ import annotations

import contextlib
import dataclasses
import socket
import subprocess
import threading
import time
from typing import Final

from busk.commands.bus import CommandBus
from busk.compiler.compile import CompiledShow
from busk.engine.clock import Clock
from busk.engine.loop import Engine, EngineStats
from busk.engine.snapshot import EngineSnapshot
from busk.process.links import RemoteBus
from busk.process.root import FrameLink, _spawn_engine
from busk.process.wire import Attach, Endpoint, EngineReport, Kind, dumps

START_S: Final = 15.0
"""Seconds an engine process has to import, load the show and answer a sync."""

REPORT_S: Final = 2.5
"""Seconds to wait for a ``STATS`` newer than the last (the host sends one a second)."""


class ThreadEngine:
    """The engine on a thread of this process (``busk run --threads``)."""

    def __init__(self, compiled: CompiledShow, clock: Clock) -> None:
        self.engine = Engine(compiled, clock)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self.engine.run, args=(self._stop,), daemon=True)

    @property
    def bus(self) -> CommandBus:
        return self.engine.bus

    @property
    def snapshot(self) -> EngineSnapshot | None:
        return self.engine.snapshot

    @property
    def compiled(self) -> CompiledShow:
        """The show the engine runs now (the last install's)."""
        return self.engine.bus.compiled

    @property
    def gcPause(self) -> float | None:
        """Not measured in this layout: the bench's collections are the engine's."""
        return None

    def start(self) -> None:
        self._thread.start()

    def stats(self) -> EngineStats:
        """A copy of the engine's counters as they are now."""
        return dataclasses.replace(self.engine.stats)

    def stop(self) -> EngineStats:
        """Stop the engine thread; return its final counters."""
        self._stop.set()
        self._thread.join()
        return self.stats()


class ProcessEngine:
    """The engine in an engine host process, with the bench as root and console.

    :meth:`start` spawns the host and attaches :attr:`bus` to it; the
    ``RemoteBus`` then sends the show (its full install) and every command
    or live edit the session makes. Statistics come from the host's
    ``STATS``, once a second, so :meth:`stats` waits for the next one.
    """

    def __init__(self, compiled: CompiledShow, clock: Clock) -> None:
        self.remote = RemoteBus(compiled, clock, sessionId="bench")
        self.frames = FrameLink()
        """The root's view of the engine: its newest frame and report."""
        self.pid: int | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._control: Endpoint | None = None
        self._reader: threading.Thread | None = None

    @property
    def bus(self) -> CommandBus:
        return self.remote

    @property
    def snapshot(self) -> EngineSnapshot | None:
        """The engine's newest snapshot, as the console process sees it."""
        return self.remote.snapshot

    @property
    def compiled(self) -> CompiledShow:
        """The show of the session's last install."""
        return self.remote.compiled

    @property
    def gcPause(self) -> float | None:
        """The engine process's longest garbage-collection pause, in seconds."""
        report = self.frames.report
        return None if report is None else report.gcPause

    def start(self) -> None:
        """Spawn the engine host, attach the bus and wait until the engine
        runs the show (a sync answered)."""
        process, control = _spawn_engine(log=False)  # a bench writes no event log
        self._process, self._control, self.pid = process, control, process.pid
        self._reader = threading.Thread(
            target=self.frames.serve, args=(control,), name="bench-frames", daemon=True
        )
        self._reader.start()
        console_end, engine_end = socket.socketpair()
        with engine_end:
            control.send(Kind.ATTACH, dumps(Attach()), [engine_end.fileno()])
        self.remote.attach(console_end)
        if not self.remote.sync(START_S):
            with contextlib.suppress(RuntimeError):
                self.stop()
            raise RuntimeError(f"the engine process did not answer within {START_S:g} s")

    def stats(self) -> EngineStats:
        """The counters of the next ``STATS`` the engine sends (so two calls
        bracket what happened between them, to within a second)."""
        return self._next_report().stats

    def stop(self) -> EngineStats:
        """``STOP`` the engine host, wait for its ``FINAL`` and its exit;
        return the final counters."""
        process, control = self._process, self._control
        assert process is not None, "never started"
        assert control is not None
        control.send(Kind.STOP)
        if self._reader is not None:
            self._reader.join(timeout=5.0)
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        self.remote.detach()
        control.sock.close()
        report = self.frames.report
        if report is None or not self.frames.final:
            raise RuntimeError("the engine process sent no FINAL")
        return report.stats

    def _next_report(self) -> EngineReport:
        last = self.frames.report
        deadline = time.monotonic() + REPORT_S
        while self.frames.report is last:
            if time.monotonic() > deadline:
                raise RuntimeError(f"no STATS from the engine process for {REPORT_S:g} s")
            time.sleep(0.01)
        report = self.frames.report
        assert report is not None
        return report


def make_engine(
    compiled: CompiledShow, clock: Clock, *, processes: bool
) -> ThreadEngine | ProcessEngine:
    """The engine for one measurement: in an engine process or on a thread."""
    return ProcessEngine(compiled, clock) if processes else ThreadEngine(compiled, clock)
