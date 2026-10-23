"""The engine process (phase-7-plan §5.4): ``python -m busk.process.engine_host --control N``.

The root starts it in a session of its own (terminal signals never reach
it) with one end of a *control* socket pair as descriptor ``N``. It waits
for the root's :attr:`~busk.process.wire.Kind.ATTACH`, which hands it the
engine end of a console link, and builds its
:class:`~busk.engine.loop.Engine` from the first install the console sends.

**Threads.**

* the *engine thread* is :meth:`Engine.run <busk.engine.loop.Engine.run>`,
  started with the first install. After every tick it wakes the publishers
  and counts tick errors: :data:`TICK_ERRORS_EXIT` in a row end the process
  with code 70, for a clean restart instead of the watchdog's kill;
* a *link thread* per console link reads it: envelopes go onto the engine's
  queue as they are (the console validated them), chunks into the link's
  :class:`~busk.process.wire.ShowDecoder` (with a GIL yield between them),
  complete installs, restores and sync markers onto the queue. A ``HELLO``
  gets a ``WELCOME`` with the stamp of the show the engine runs, and seeds the
  link's decoder with that show (decision 8: a restarted console with the
  same stamp shares it). A second ``ATTACH`` replaces the link: the old one is shut
  down and its thread ends. End of file on a link leaves the engine
  ticking with what it has, waiting for the next ``ATTACH``;
* the *frame publisher* sends layouts and frames to the root, the
  statistics every second, and with ``--log`` the engine's event-log
  records in a ``LOG`` batch every
  :data:`~busk.persistence.eventlog.FLUSH_S` (phase-7-plan §5.21). It
  sends the newest frame whenever the socket takes it: a root that stops
  reading makes it skip frames, never the tick wait. A layout goes out
  before the first frame made with it;
* the *console publisher* sends each new snapshot and the statistics every
  second to the current console link, and ``SYNCED`` once the engine has
  drained a ``SYNC`` (after the snapshot of that tick). After each tick it
  also sends what the console watches (``WATCH``, GAP-11): the newest
  frame (its layout first when it is new), the output capture of a tick of
  the newest show, without that show (``OUTPUT``: the console reads it with
  its own copy), and the effects, read here (``EFFECTS``: a capture holds
  the compiled effects, larger than the snapshot). The engine captures its
  output and effects only while the console watches them, and then at most
  every :data:`WATCH_S`; a new link watches nothing;
* the *control thread* reads the root: ``ATTACH``, ``STOP``. End of file
  (the root is gone) ends the process at once.

**Stop.** The engine finishes its tick, the frame publisher makes a last
pass, and a ``FINAL`` report goes to the root; the process exits 0 (70
after the tick errors).

**Garbage collection.** After each install the host freezes the collector
(``gc.freeze()``), so collections never scan compiled shows (decision 3).
The longest collection is timed with ``gc.callbacks`` and reported.
"""

from __future__ import annotations

import argparse
import contextlib
import gc
import os
import socket
import sys
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from busk.commands.types import CommandEnvelope
from busk.compiler.compile import CompiledShow, OutputLayout
from busk.engine.clock import SWITCH_INTERVAL, Clock, MonotonicClock
from busk.engine.effect_status import EffectCapture, read_effects
from busk.engine.install import Install, Stamp, keys_remap
from busk.engine.loop import Engine, EngineStats, Frame
from busk.engine.readout import Capture
from busk.engine.snapshot import EngineSnapshot, Sync
from busk.persistence.eventlog import FLUSH_S, take
from busk.process.wire import (
    Endpoint,
    EngineReport,
    Hello,
    Kind,
    LinkClosed,
    OutputCapture,
    ShowDecoder,
    Watch,
    Welcome,
    dumps,
    encode_frame,
    loads,
)

TICK_ERRORS_EXIT: Final = 10
"""Consecutive tick errors after which the engine exits with code 70."""

EXIT_FAILED: Final = 70
"""The exit code of an engine that gave up (``EX_SOFTWARE``)."""

STATS_S: Final = 1.0
"""How often the statistics go to the root and the console."""

EARLY_MAX: Final = 1024
"""Envelopes kept while no show has come yet (more are dropped)."""

WATCH_S: Final = 0.04
"""The shortest time between two output captures, and between two effect
reads, that go to a console which watches them: 25 a second, more than a
display polls (10 to 20 times a second). Frames go after every tick."""

type EngineFactory = Callable[[CompiledShow, Clock, NDArray[np.float64] | None], Engine]


class EngineHost:
    """Runs one engine for the root and whichever console is attached.

    ``make_engine`` builds the engine from the first install's show (tests
    pass a faulty one). ``freeze`` freezes the garbage collector after each
    install; in-process tests turn it off, since it acts on the whole
    process. ``log`` keeps the engine's event-log records and sends them to
    the root (``LOG``).
    """

    def __init__(
        self,
        control: socket.socket,
        *,
        clock: Clock | None = None,
        make_engine: EngineFactory = Engine,
        freeze: bool = True,
        log: bool = False,
    ) -> None:
        self.engine: Engine | None = None
        """Built from the first install; ``None`` until then."""
        self._root = Endpoint(control)
        self._clock: Clock = MonotonicClock() if clock is None else clock
        self._make_engine = make_engine
        self._freeze = freeze
        self._log = log
        self._lock = threading.Lock()  # guards engine creation, the link, the early queue
        self._link: Endpoint | None = None  # the current console link
        self._welcomed: Endpoint | None = None  # the current link, once its WELCOME went out
        self._watch = Watch()  # what the current link watches
        self._base: NDArray[np.float64] | None = None  # from the first console's Hello
        self._early: list[CommandEnvelope] = []  # envelopes before the first show
        self._sync_seq = 0  # the host's sync tokens …
        self._syncs: list[tuple[int, Endpoint, int]] = []  # … waiting: (ours, link, theirs)
        self._shown: CompiledShow | None = None  # the show of the last install queued
        self._stamp: Stamp | None = None  # … and its stamp
        self._engine_thread: threading.Thread | None = None
        self._stop = threading.Event()  # stops the engine thread
        self._finishing = threading.Event()  # publishers make their last pass
        self._done = threading.Event()  # run() may return
        self._frames = threading.Event()  # a tick happened: the frame publisher wakes
        self._snapshots = threading.Event()  # the console publisher wakes
        self._code = 0
        self.orphaned = False
        """The root went away: the process should end without ceremony."""
        self._gc_started = 0.0
        self._gc_pause = 0.0

    # -- lifecycle

    def run(self) -> int:
        """Serve until ``STOP`` (0), :data:`TICK_ERRORS_EXIT` tick errors in
        a row (70), or the root's end of file (0, :attr:`orphaned`)."""
        gc.callbacks.append(self._time_gc)
        try:
            threads = [
                threading.Thread(target=self._read_control, name="control", daemon=True),
                threading.Thread(target=self._publish_frames, name="frames", daemon=True),
                threading.Thread(target=self._publish_console, name="console", daemon=True),
            ]
            for thread in threads:
                thread.start()
            self._done.wait()
            if self.orphaned:
                return self._code
            self._stop.set()
            if self._engine_thread is not None:
                self._engine_thread.join(timeout=2.0)
            self._finishing.set()
            self._frames.set()
            self._snapshots.set()
            for thread in threads[1:]:
                thread.join(timeout=2.0)
            with contextlib.suppress(OSError):
                self._root.send(Kind.FINAL, dumps(self.report()))
            with self._lock:
                link = self._link
            if link is not None:
                link.shutdown()
            return self._code
        finally:
            gc.callbacks.remove(self._time_gc)

    def _finish(self, code: int) -> None:
        """End :meth:`run` with ``code`` (the first reason wins)."""
        if not self._done.is_set():
            self._code = code
            self._stop.set()
            self._done.set()

    def report(self) -> EngineReport:
        """The statistics as they are now."""
        engine = self.engine
        stats = EngineStats() if engine is None else engine.stats
        return EngineReport(stats=stats, gcPause=self._gc_pause, pid=os.getpid())

    def _time_gc(self, phase: str, info: dict[str, Any]) -> None:
        if phase == "start":
            self._gc_started = time.perf_counter()
        else:
            self._gc_pause = max(self._gc_pause, time.perf_counter() - self._gc_started)

    # -- the root

    def _read_control(self) -> None:
        """Serve the root's messages until ``STOP`` or end of file."""
        while True:
            try:
                message = self._root.receive()
            except ValueError:
                continue  # an unknown kind: its payload was read, the stream is intact
            except (OSError, LinkClosed):
                message = None
            if message is None:
                self.orphaned = True
                self._finish(0)
                return
            if message.kind == Kind.ATTACH and message.fds:
                for extra in message.fds[1:]:
                    os.close(extra)
                self.on_link(socket.socket(fileno=message.fds[0]))
            elif message.kind == Kind.STOP:
                self._finish(0)
                return
            else:
                for fd in message.fds:
                    os.close(fd)

    def on_link(self, sock: socket.socket) -> None:
        """``ATTACH``: serve ``sock`` as the console link; the previous link
        is shut down (its thread then ends and closes it)."""
        endpoint = Endpoint(sock)
        with self._lock:
            previous, self._link, self._welcomed = self._link, endpoint, None
            self._watched(Watch())
        if previous is not None:
            previous.shutdown()
        threading.Thread(target=self._read_link, args=(endpoint,), name="link", daemon=True).start()

    # -- a console link

    def _read_link(self, link: Endpoint) -> None:
        """Serve one console link until its end of file."""
        decoder = ShowDecoder()
        while True:
            try:
                message = link.receive()
            except ValueError:
                continue
            except (OSError, LinkClosed):
                message = None
            if message is None:
                break
            try:
                if message.kind == Kind.HELLO:
                    decoder = ShowDecoder(self._hello(link, loads(message.payload)))
                elif message.kind == Kind.COMMAND:
                    self._command(loads(message.payload))
                elif message.kind in (Kind.CHUNK, Kind.INSTALL):
                    install = decoder.feed(message.payload)
                    time.sleep(0)  # a GIL yield between chunks
                    if install is not None:
                        self._install(install)
                elif message.kind == Kind.RESTORE:
                    engine = self.engine
                    if engine is not None:
                        engine.bus.restore(loads(message.payload))
                elif message.kind == Kind.SYNC:
                    self._sync(link, loads(message.payload))
                elif message.kind == Kind.WATCH:
                    with self._lock:
                        if self._link is link:  # a replaced console watches nothing any more
                            self._watched(loads(message.payload))
            except Exception:  # a bad message must not end the link
                print(f"engine: bad {message.kind.name} message from the console", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
        with self._lock:
            if self._link is link:
                self._link = self._welcomed = None
        link.sock.close()

    def _hello(self, link: Endpoint, hello: Hello) -> CompiledShow | None:
        """Answer a console: fresh when there is no show yet (keep its base
        frame for the engine), else with the running engine's snapshot and
        the stamp of its show. Return that show, which seeds the link's
        decoder."""
        with self._lock:
            engine, shown, stamp = self.engine, self._shown, self._stamp
            if engine is None:
                self._base = hello.base
        welcome = Welcome(
            fresh=engine is None,
            stamp=None if engine is None else stamp,
            snapshot=None if engine is None else engine.snapshot,
        )
        link.send(Kind.WELCOME, dumps(welcome))
        with self._lock:
            if self._link is link:
                self._welcomed = link  # the console publisher may write to it now
        self._snapshots.set()
        return None if engine is None else shown

    def _watched(self, watch: Watch) -> None:
        """What the current link watches is now ``watch``: the engine
        captures its output and effects only while they are watched (the
        lock is held)."""
        self._watch = watch
        engine = self.engine
        if engine is not None:
            engine.captureOutput = watch.output
            engine.captureEffects = watch.effects

    def _sync(self, link: Endpoint, token: int) -> None:
        """Queue a sync marker under a token of the host's own (consoles
        number theirs from 1); the console publisher answers ``SYNCED`` with
        the console's token once the engine has drained it. Without an
        engine there is nothing to wait for: answer at once."""
        engine = self.engine
        if engine is None:
            link.send(Kind.SYNCED, dumps(token))
            return
        with self._lock:
            self._sync_seq += 1
            self._syncs.append((self._sync_seq, link, token))
            engine.bus.mark(Sync(token=self._sync_seq))

    def _command(self, envelope: CommandEnvelope) -> None:
        """Queue an envelope as it is: the console validated it."""
        with self._lock:
            engine = self.engine
            if engine is None:
                if len(self._early) < EARLY_MAX:
                    self._early.append(envelope)
                return
        engine.bus.enqueue(envelope)

    def _install(self, install: Install) -> None:
        """Queue a complete install. The first one with a show builds the
        engine and starts it. An install without a remap whose slot keys
        differ from the show queued before it gets one computed from the
        keys (decision 8)."""
        with self._lock:
            engine = self.engine
            if engine is None:
                if install.compiled is None:
                    return  # a programmer frame for no show: nothing to run it on
                try:
                    engine = self._make_engine(install.compiled, self._clock, self._base)
                except ValueError:  # a base frame for other slots (a repatch since): none
                    print("engine: --values frame dropped: the show was repatched", file=sys.stderr)
                    engine = self._make_engine(install.compiled, self._clock, None)
                if self._log:
                    engine.records = deque()
                engine.captureOutput = self._watch.output
                engine.captureEffects = self._watch.effects
                engine.bus.install(replace(install, compiled=None, remap=None))
                for envelope in self._early:
                    engine.bus.enqueue(envelope)
                self._early.clear()
                self._shown, self._stamp = install.compiled, install.stamp
                self.engine = engine
                self._engine_thread = threading.Thread(
                    target=engine.run, args=(self._stop, self._ticked), name="engine", daemon=True
                )
                self._engine_thread.start()
            else:
                shown, compiled = self._shown, install.compiled
                if compiled is not None:
                    if (
                        install.remap is None
                        and shown is not None
                        and compiled.slots is not shown.slots
                    ):
                        install = replace(install, remap=keys_remap(shown.slots, compiled.slots))
                    self._shown, self._stamp = compiled, install.stamp
                engine.bus.install(install)
        if self._freeze:
            gc.freeze()

    # -- the engine thread

    def _ticked(self) -> None:
        """After every tick: wake the publishers; give up after
        :data:`TICK_ERRORS_EXIT` tick errors in a row."""
        self._frames.set()
        self._snapshots.set()
        engine = self.engine
        if engine is not None and engine.stats.consecutiveTickErrors >= TICK_ERRORS_EXIT:
            self._finish(EXIT_FAILED)

    # -- publishers

    def _publish_frames(self) -> None:
        """Send the newest frame after each tick (its layout first when it is
        new), the statistics every second and the event-log records every
        :data:`FLUSH_S`, to the root."""
        root = self._root
        sent: Frame | None = None
        layout: OutputLayout | None = None
        layout_id = 0
        due = time.monotonic() + STATS_S
        log_due = time.monotonic() + FLUSH_S
        try:
            while True:
                self._frames.wait(STATS_S)
                self._frames.clear()
                last = self._finishing.is_set()
                engine = self.engine
                frame = None if engine is None else engine.latest
                if frame is not None and frame is not sent and frame.layout is not None:
                    if frame.layout is not layout:
                        layout, layout_id = frame.layout, layout_id + 1
                        root.send(Kind.LAYOUT, dumps((layout_id, layout)))
                    root.send(Kind.FRAME, encode_frame(frame, layout_id))
                    sent = frame
                now = time.monotonic()
                records = None if engine is None else engine.records
                if records and (now >= log_due or last):
                    root.send(Kind.LOG, dumps(take(records)))
                    log_due = now + FLUSH_S
                if now >= due:
                    root.send(Kind.STATS, dumps(self.report()))
                    due = now + STATS_S
                if last:
                    return
        except OSError:
            return  # the root is gone: the control thread sees it too

    def _publish_console(self) -> None:
        """Send each new snapshot, and the statistics every second, to the
        current console link once it has had its ``WELCOME`` (the first
        message a console reads). A newly drained sync token follows the
        snapshot of its tick (``SYNCED``), and what the link watches follows
        that (:class:`_Watched`)."""
        link: Endpoint | None = None
        sent: EngineSnapshot | None = None
        watched = _Watched()
        due = time.monotonic() + STATS_S
        while not self._finishing.is_set():
            self._snapshots.wait(STATS_S)
            self._snapshots.clear()
            with self._lock:
                current, watch, shown, stamp = self._welcomed, self._watch, self._shown, self._stamp
            if current is not link:
                # A new console gets the next snapshot anyway, and a new layout first.
                link, sent, watched = current, None, _Watched()
            engine = self.engine
            if link is None or engine is None:
                continue
            try:
                drained = engine.synced  # first: the snapshot read next is at least that new
                snapshot = engine.snapshot
                if snapshot is not None and snapshot is not sent:
                    link.send(Kind.SNAPSHOT, dumps(snapshot))
                    sent = snapshot
                with self._lock:
                    done = [entry for entry in self._syncs if entry[0] <= drained]
                    self._syncs = [entry for entry in self._syncs if entry[0] > drained]
                for _, owner, token in done:
                    if owner is link:  # a replaced console waits for nothing any more
                        link.send(Kind.SYNCED, dumps(token))
                now = time.monotonic()
                watched.send(link, engine, watch, shown, stamp, now)
                if now >= due:
                    link.send(Kind.STATS, dumps(self.report()))
                    due = now + STATS_S
            except OSError:
                link.shutdown()  # the console is gone; its link thread ends


class _Watched:
    """What the console publisher has sent one link of what it watches
    (:class:`~busk.process.wire.Watch`), so that each pass sends only what
    is new: the newest frame (after its layout, when that is new), output
    capture and effects. It also paces the engine: once a capture or the
    effects went, the engine captures them again only :data:`WATCH_S`
    later, so a display's polls cost it a capture each, not one per tick."""

    def __init__(self) -> None:
        self.frame: Frame | None = None
        self.layout: OutputLayout | None = None
        self.layoutId = 0  # per link, as the root's are per engine
        self.output: Capture | None = None
        self.effects: EffectCapture | None = None
        self.outputDue = 0.0  # when the engine may capture the output again
        self.effectsDue = 0.0  # … and its effects

    def send(
        self,
        link: Endpoint,
        engine: Engine,
        watch: Watch,
        shown: CompiledShow | None,
        stamp: Stamp | None,
        now: float,
    ) -> None:
        """Send ``link`` what ``watch`` asks for and is new, at ``now``
        (``time.monotonic()``). An output capture goes only from a tick of
        ``shown``, the show last installed (its stamp ``stamp``): the
        console has no copy of an older one."""
        engine.captureOutput = watch.output and now >= self.outputDue
        engine.captureEffects = watch.effects and now >= self.effectsDue
        if watch.frames:
            frame = engine.latest
            if frame is not None and frame is not self.frame and frame.layout is not None:
                if frame.layout is not self.layout:
                    self.layout, self.layoutId = frame.layout, self.layoutId + 1
                    link.send(Kind.LAYOUT, dumps((self.layoutId, frame.layout)))
                link.send(Kind.FRAME, encode_frame(frame, self.layoutId))
                self.frame = frame
        if watch.output:
            captured = engine.output
            if captured is not None and captured is not self.output:
                self.output, self.outputDue = captured, now + WATCH_S
                engine.captureOutput = False
                if captured.compiled is shown:
                    capture = OutputCapture(
                        seq=captured.seq,
                        time=captured.time,
                        stamp=stamp,
                        values=captured.values,
                        owners=captured.owners,
                        origins=captured.origins,
                    )
                    link.send(Kind.OUTPUT, dumps(capture))
        if watch.effects:
            effects = engine.effects
            if effects is not None and effects is not self.effects:
                self.effects, self.effectsDue = effects, now + WATCH_S
                engine.captureEffects = False
                link.send(Kind.EFFECTS, dumps(read_effects(effects)))


def main(argv: Sequence[str] | None = None) -> int:
    """Run an engine host on the inherited control descriptor."""
    parser = argparse.ArgumentParser(
        prog="python -m busk.process.engine_host",
        description="busk's engine process; the root of `busk run` starts it.",
    )
    parser.add_argument(
        "--control", type=int, required=True, help="the control socket's descriptor"
    )
    parser.add_argument("--log", action="store_true", help="send event-log records to the root")
    args = parser.parse_args(argv)
    sys.setswitchinterval(SWITCH_INTERVAL)
    host = EngineHost(socket.socket(fileno=args.control), log=args.log)
    code = host.run()
    if host.orphaned:
        os._exit(code)  # at once: nobody is left to read anything
    return code


if __name__ == "__main__":
    sys.exit(main())
