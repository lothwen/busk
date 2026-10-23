"""The console's side of the engine (phase-7-plan §5.5).

Everything in the console that talks to the engine (the session, the
feedback worker, the web link, the binding resolver, autosave, the status
line) goes through an :class:`~busk.engine.link.EngineLink`: the bus's
compiled show, the published snapshot and statistics, ``submit`` and
``install``.

* :class:`~busk.engine.link.LocalEngine` (``busk run --threads``): an
  in-process :class:`~busk.engine.loop.Engine` and its bus, as in Phase 6.
  It lives in :mod:`busk.engine.link`, shared with
  :class:`~busk.runner.LiveShow` (phase-8-plan step 10).
* :class:`RemoteBus` (processes): a :class:`~busk.commands.bus.CommandBus`
  that validates as the in-process bus does, then writes to the engine
  process over a link the root hands it (:meth:`RemoteBus.attach`).

**Reconnects.** On each ``ATTACH`` the bus says ``HELLO`` and reads the
``WELCOME``:

* **fresh** (a new engine): it sends its whole state, the show the session
  last installed and its programmer frame, then a ``RESTORE`` of the last
  snapshot the previous engine published (unless the root says not to,
  decision 5), then the commands queued meanwhile;
* **not fresh** (this console is the restarted one, decision 7): it adopts
  the engine's snapshot. If its show has the stamp of the engine's show
  (decision 8), it sends only its programmer frame, and its encoder is
  seeded with that show, as the engine's decoder is, so later edits share
  the engine's objects (:attr:`RemoteBus.adoption` ``"kept"``). Otherwise it
  installs its show, whose remap the engine computes from slot keys: the
  edits made after the last show autosave are undone on stage
  (``"replaced"``). Then the queued commands.

**The event log** (phase-7-plan §5.21). With ``log`` on, each reconnect's
install carries a ``start`` cause: the session state that install shows
(the ``source`` of the session's last install), how the connection went
(``fresh``, ``kept``, ``replaced``) and its frame's touched slots, so a
replay starts afresh from every connection
(:func:`~busk.persistence.eventlog.start_cause`).

**While no engine is attached** commands are queued, at most
:data:`QUEUE_MAX` (the oldest are kept; the rest are dropped and counted),
so a blackout pressed during a restart still happens (decision 6).
Installs are not queued: the reconnect sends the session's current state.

**What the console watches** (GAP-11 of ``docs/dev/tui/engine-gaps.md``).
Besides snapshots, the engine sends what the console asked for with
:meth:`RemoteBus.watch` (a ``WATCH``, sent again after each reconnect): its
frames, its output captures, which the bus reads with its own copy of the
show of the capture's stamp, and its effect snapshots. The bus keeps the
newest of each, across reconnects too, as it keeps the snapshot.
"""

from __future__ import annotations

import socket
import threading
import time
from collections import deque
from dataclasses import replace
from typing import Final, Literal, cast

import numpy as np
from numpy.typing import NDArray

from busk.commands.bus import CommandBus
from busk.commands.types import CommandEnvelope
from busk.compiler.compile import CompiledShow, OutputLayout
from busk.engine.clock import Clock
from busk.engine.install import EMPTY_FRAME, Install, ProgrammerFrame, Stamp
from busk.engine.loop import Engine, EngineStats, Frame, Record
from busk.engine.readout import Capture
from busk.engine.snapshot import EffectSnapshot, EngineSnapshot, Restore
from busk.model.show import Show
from busk.persistence.eventlog import start_cause
from busk.process.wire import (
    Attach,
    Endpoint,
    EngineReport,
    Hello,
    Kind,
    LinkClosed,
    OutputCapture,
    ShowEncoder,
    Watch,
    Welcome,
    decode_frame,
    dumps,
    loads,
)
from busk.session.programmer import EMPTY, Programmer, to_json

QUEUE_MAX: Final = 1024
"""Commands a detached console keeps for the next engine (decision 6)."""


def start_log(engine: Engine, show: Show, base: NDArray[np.float64] | None = None) -> deque[Record]:
    """Turn the event log on for an in-process engine that has not ticked
    (``busk run --threads``): give it a record deque, and queue the
    connection's ``start`` first, before the session installs anything
    (the programmer is still empty). Returns the deque, for a writer."""
    records: deque[Record] = deque()
    engine.records = records
    start = start_cause(
        show=show,
        programmer=to_json(EMPTY),
        connect="fresh",
        engine_hz=engine.compiled.engineHz,
        base=None if base is None else base.tolist(),
    )
    engine.bus.install(Install(compiled=None, remap=None, programmer=EMPTY_FRAME, causes=(start,)))
    return records


class RemoteBus(CommandBus):
    """The session's bus in the console process, and its
    :class:`~busk.engine.link.EngineLink`.

    ``sessionId`` and ``restarted`` go in every ``HELLO``, and so does
    ``base``, the ``--values`` base frame against ``compiled``'s slots.
    ``stamp`` is the stamp of ``compiled`` (the session's); later installs
    bring their own. One
    lock serialises every writer (MIDI callbacks, OSC and web threads, the
    console and the session), so an install and the commands validated
    against its show keep their order (phase-3-plan §5.7).

    ``log`` is the show ``compiled`` was made from, with the event log on
    (``None``: off): the state of the first reconnect's ``start`` record
    until the session installs.
    """

    def __init__(
        self,
        compiled: CompiledShow,
        clock: Clock,
        *,
        sessionId: str,
        restarted: bool = False,
        base: NDArray[np.float64] | None = None,
        stamp: Stamp | None = None,
        log: Show | None = None,
    ) -> None:
        super().__init__(compiled, clock)
        self._hello = Hello(sessionId=sessionId, restarted=restarted, base=base)
        self._writer = threading.Lock()
        self._link: Endpoint | None = None  # set once a link's reconnect is done
        self._connecting: Endpoint | None = None  # a link waiting for its WELCOME
        self._encoder = ShowEncoder()
        self._shown = compiled  # the show of the session's last install
        self._stamp = stamp  # … its stamp
        self._readout = (stamp, compiled)  # both in one assignment, for the reader thread
        self._frame: ProgrammerFrame = EMPTY_FRAME  # its last programmer frame
        self._log = log is not None
        self._source: tuple[Show, Programmer] | None = (  # its state, for the event log
            None if log is None else (log, EMPTY)
        )
        self._pending: list[CommandEnvelope] = []
        self._snapshot: EngineSnapshot | None = None
        self._stats = EngineStats()
        self._watch = Watch()  # what the console asked the engine for
        self._latest: Frame | None = None  # the newest DMX frame
        self._output: Capture | None = None
        self._effects: EffectSnapshot | None = None
        self._changed = threading.Condition()  # a reconnect completed, or a SYNCED came
        self._token = 0  # the last sync token sent …
        self._synced = 0  # … and the last one the engine answered
        self.dropped = 0
        """Commands dropped because :data:`QUEUE_MAX` were already queued."""
        self.reconnects = 0
        """Links whose reconnect completed."""
        self.restored: EngineSnapshot | None = None
        """The snapshot the last reconnect restored into a fresh engine (``None``: none)."""
        self.restoreSkipped = False
        """Whether the root said not to restore at the last reconnect (decision 5)."""
        self.adoption: Literal["kept", "replaced"] | None = None
        """What the last reconnect to a running engine did with its show
        (decision 8): ``"kept"`` (the same stamp: only the programmer went),
        ``"replaced"`` (this console's show went); ``None`` after a fresh one."""

    @property
    def bus(self) -> CommandBus:
        """This bus: the session submits to it."""
        return self

    @property
    def snapshot(self) -> EngineSnapshot | None:
        """The latest snapshot an engine published (kept while detached:
        it is what a fresh engine restores)."""
        return self._snapshot

    @property
    def stats(self) -> EngineStats:
        """The latest statistics an engine sent."""
        return self._stats

    @property
    def attached(self) -> bool:
        """Whether an engine takes commands now."""
        return self._link is not None

    @property
    def frame(self) -> Frame | None:
        """The newest frame an engine sent, with its layout and no compiled
        show (``None`` until one came: see :meth:`watch`)."""
        return self._latest

    @property
    def output(self) -> Capture | None:
        """The newest output capture an engine sent, with this console's
        compiled show of its stamp (``None`` until one came)."""
        return self._output

    @property
    def effects(self) -> EffectSnapshot | None:
        """The newest effect snapshot an engine sent (``None`` until one came)."""
        return self._effects

    def watch(self, *, frames: bool = False, output: bool = False, effects: bool = False) -> None:
        """Ask the engine for its frames, output captures or effects from
        now on, besides what was asked before (``WATCH``; every new engine
        is asked again)."""
        if _joined(self._watch, frames, output, effects) == self._watch:
            return  # nothing new: no lock, no message
        with self._writer:
            self._watch = _joined(self._watch, frames, output, effects)
            link = self._link
            if link is None:
                return  # the reconnect sends it
            try:
                link.send(Kind.WATCH, dumps(self._watch))
            except OSError:
                self._lost(link)

    def enqueue(self, envelope: CommandEnvelope) -> None:
        """Send a validated envelope to the engine, or queue it while none
        is attached (:meth:`CommandBus.submit` ends here)."""
        with self._writer:
            link = self._link
            if link is not None:
                try:
                    link.send(Kind.COMMAND, dumps(envelope))
                    return
                except OSError:
                    self._lost(link)
            self._keep(envelope)

    def install(self, item: Install) -> None:
        """Send a live edit; while detached, only remember it: the reconnect
        sends the show and programmer frame of the last one."""
        with self._writer:
            self._frame = item.programmer
            if item.compiled is not None:
                self._shown, self._stamp = item.compiled, item.stamp
                self._readout = (item.stamp, item.compiled)
            if item.source is not None:
                self._source = cast(tuple[Show, Programmer], item.source)
            link = self._link
            if link is None:
                return
            try:
                link.send_install(self._encoder.encode(replace(item, source=None)))
            except OSError:
                self._lost(link)

    def sync(self, timeout: float) -> bool:
        """Wait for an engine to be attached, then until it has applied what
        was sent before this call and :attr:`snapshot` shows it (``SYNC``,
        ``SYNCED``); ``False`` after ``timeout`` seconds."""
        deadline = time.monotonic() + timeout
        with self._changed:
            if not self._changed.wait_for(lambda: self._link is not None, timeout):
                return False
        with self._writer:
            link = self._link
            if link is None:
                return False  # lost meanwhile
            self._token += 1
            token = self._token
            try:
                link.send(Kind.SYNC, dumps(token))
            except OSError:
                self._lost(link)
                return False
        with self._changed:
            remaining = max(0.0, deadline - time.monotonic())
            return self._changed.wait_for(lambda: self._synced >= token, remaining)

    def attach(self, sock: socket.socket, attach: Attach | None = None) -> None:
        """Serve ``sock`` as the engine link (the root's ``ATTACH``): say
        ``HELLO``, then reconnect in a reader thread once the ``WELCOME``
        comes. A previous link is shut down."""
        endpoint = Endpoint(sock)
        with self._writer:
            previous = self._link or self._connecting
            self._link, self._connecting = None, endpoint
        if previous is not None:
            previous.shutdown()
        endpoint.send(Kind.HELLO, dumps(self._hello))
        restore = True if attach is None else attach.restore
        threading.Thread(
            target=self._read, args=(endpoint, restore), name="engine-link", daemon=True
        ).start()

    def detach(self) -> None:
        """Shut the link down (at exit)."""
        with self._writer:
            link = self._link or self._connecting
            self._link = self._connecting = None
        if link is not None:
            link.shutdown()

    def _read(self, link: Endpoint, restore: bool) -> None:
        """Reconnect on the ``WELCOME``, then keep the snapshot and
        statistics up to date until the link ends."""
        try:
            while (message := link.receive()) is not None and message.kind != Kind.WELCOME:
                pass  # nothing comes before the WELCOME; skip it if it does
            if message is not None:
                self._reconnect(link, loads(message.payload), restore)
                layouts: dict[int, OutputLayout] = {}  # this engine's, by id
                while (message := link.receive()) is not None:
                    if message.kind == Kind.SNAPSHOT:
                        self._snapshot = loads(message.payload)
                    elif message.kind == Kind.STATS:
                        report: EngineReport = loads(message.payload)
                        self._stats = report.stats
                    elif message.kind == Kind.SYNCED:
                        with self._changed:
                            self._synced = max(self._synced, loads(message.payload))
                            self._changed.notify_all()
                    elif message.kind == Kind.LAYOUT:
                        ident, layout = loads(message.payload)
                        layouts[ident] = layout
                    elif message.kind == Kind.FRAME:
                        self._latest = decode_frame(message.payload, layouts)
                    elif message.kind == Kind.OUTPUT:
                        self._captured(loads(message.payload))
                    elif message.kind == Kind.EFFECTS:
                        self._effects = loads(message.payload)
        except (OSError, LinkClosed, ValueError):
            pass  # the link ended; the root attaches the next one
        with self._writer:
            self._lost(link)
        link.sock.close()

    def _captured(self, capture: OutputCapture) -> None:
        """Keep an output capture, with this console's copy of the show of
        its stamp; drop one of a show the session has replaced since (the
        engine sends the newest show's once it runs it), or of an
        unstamped show, which nothing names."""
        stamp, compiled = self._readout  # one read: the stamp and show of one install
        if capture.stamp is None or capture.stamp != stamp:
            return
        self._output = Capture(
            seq=capture.seq,
            time=capture.time,
            compiled=compiled,
            values=capture.values,
            owners=capture.owners,
            origins=capture.origins,
        )

    def _reconnect(self, link: Endpoint, welcome: Welcome, restore: bool) -> None:
        """Send the whole state (and, to a fresh engine, the restore; to a
        running one, only the programmer if it runs this show), then the
        queued commands; from then on commands go straight out."""
        with self._writer:
            if self._connecting is not link:
                return  # replaced while it said hello
            kept = not welcome.fresh and welcome.stamp is not None and welcome.stamp == self._stamp
            self._encoder = ShowEncoder(self._shown if kept else None)
            if not welcome.fresh:
                self._snapshot = welcome.snapshot  # adopt the running engine's state
            self.adoption = None if welcome.fresh else "kept" if kept else "replaced"
            install = Install(
                compiled=None if kept else self._shown,
                remap=None,
                programmer=self._frame,
                stamp=None if kept else self._stamp,
                causes=self._start(welcome.fresh, kept),
            )
            link.send_install(self._encoder.encode(install))
            if self._watch != Watch():  # a new link watches nothing
                link.send(Kind.WATCH, dumps(self._watch))
            restored = self._snapshot if welcome.fresh and restore else None
            if restored is not None:
                link.send(Kind.RESTORE, dumps(Restore(snapshot=restored)))
            self.restored = restored
            self.restoreSkipped = welcome.fresh and not restore
            for envelope in self._pending:
                link.send(Kind.COMMAND, dumps(envelope))
            self._pending.clear()
            self._link, self._connecting = link, None
            self.reconnects += 1
        with self._changed:
            self._changed.notify_all()

    def _start(self, fresh: bool, kept: bool) -> tuple[bytes, ...]:
        """The causes of a reconnect's install, its ``start`` (the writer
        lock is held); none with the event log off."""
        if not self._log or self._source is None:
            return ()
        show, programmer = self._source
        frame = self._frame
        start = start_cause(
            show=show,
            programmer=to_json(programmer),
            connect="fresh" if fresh else "kept" if kept else "replaced",
            touched=frame.touched.tolist(),
            touched_effects=frame.touchedEffects,
            engine_hz=self._shown.engineHz,
            base=None if self._hello.base is None else self._hello.base.tolist(),
        )
        return (start,)

    def _lost(self, link: Endpoint) -> None:
        """``link`` failed or ended (the writer lock is held)."""
        if self._link is link:
            self._link = None
        if self._connecting is link:
            self._connecting = None
        link.shutdown()

    def _keep(self, envelope: CommandEnvelope) -> None:
        """Queue a command for the next engine (the writer lock is held)."""
        if len(self._pending) < QUEUE_MAX:
            self._pending.append(envelope)
        else:
            self.dropped += 1


def _joined(watch: Watch, frames: bool, output: bool, effects: bool) -> Watch:
    """``watch`` and what is asked for besides."""
    return Watch(
        frames=watch.frames or frames,
        output=watch.output or output,
        effects=watch.effects or effects,
    )
