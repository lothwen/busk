"""The console process (phase-7-plan §5.5): ``python -m busk.process.console_host``.

:func:`run_console` is what ``busk run`` did in one process up to Phase 6
(``cli._run``), without the engine and the output: load, recover and compile
the show, open the session, the surfaces, feedback, the web remote and
autosave, then read console commands until ``quit``, the end of stdin or of
``--script``, or a signal. What runs the engine is a :class:`Backend`:

* :class:`ThreadsBackend` (``busk run --threads``): the Phase 6 layout. The
  engine and the output scheduler run as threads of this process, behind a
  :class:`~busk.process.links.LocalEngine`; this process prints the route
  lines, owns ``--duration`` and prints the final statistics;
* :class:`ProcessBackend` (the console process): the session's bus is a
  :class:`~busk.process.links.RemoteBus` on the link the root handed over
  (``--link``). The root prints the route lines and the statistics, owns
  ``--duration`` (``SIGTERM`` when it is over, counted from this process's
  ``READY``) and restarts the engine.

Either way, everything that read ``engine.snapshot`` and
``engine.bus.compiled`` reads the backend's
:class:`~busk.process.links.EngineLink`. Before the first command (the
script's or stdin's) the console waits until the engine has applied the
start-up state (:meth:`EngineLink.sync <busk.process.links.EngineLink.sync>`),
so ``status`` right after start shows the recovered masters and page.

**Signals** (§5.9, console process only). ``SIGTERM`` and ``SIGHUP`` (the root
forwards its own) quit as Ctrl+C does in a non-interactive run: exit 0 with
the clean-exit autosave. One that comes while the console is still starting
takes effect once its command loop begins. End of file on the root's control
link (the root was killed) ends the process at once, without the clean-exit
autosave, so the next run recovers.

**Exit codes.** 0 after ``quit`` (or a signal), 1 when the show cannot be
loaded or compiled or ``--script`` fails, 70 on any unexpected exception
(decision 7: the root restarts a console that exits 70).

**Restarted** (``--restarted WHY``, decision 7). The root starts a new console
when one died of a signal or exited 70, with the same arguments. It
recovers whether or not the last exit was clean, adopts the running
engine's masters, tempos, page and playbacks instead of pushing its own,
runs neither ``--script`` nor ``--values``, and says
``busk console: restarted after a crash (WHY); type 'help'``. If its
recovered show has the stamp of the engine's show it sends only the
programmer; otherwise its show replaces the engine's, undoing on stage the
edits made after the last show autosave (decision 8). Either way it says
which (``engine: running on …``).

**The event log** (phase-7-plan §5.21). Unless ``--no-log``, the session
puts causes on its installs and every connection a ``start`` record
(:mod:`busk.persistence.eventlog`). With processes the root writes the file;
with ``--threads`` a :class:`~busk.persistence.eventlog.LogPump` of this
process does. ``info`` names the file.
"""

from __future__ import annotations

import argparse
import contextlib
import gc
import math
import os
import queue
import secrets
import signal
import socket
import sys
import threading
import time
import traceback
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from types import FrameType
from typing import Final, Protocol, TextIO, cast

import numpy as np
from numpy.typing import NDArray

from busk.commands.types import Command
from busk.compiler.compile import CompiledShow, UnsupportedFeature, compile_show
from busk.compiler.limitations import collect_limitations
from busk.compiler.values import compile_values
from busk.console.console import Console, interact
from busk.engine.clock import SWITCH_INTERVAL, Clock, MonotonicClock
from busk.engine.install import Stamp
from busk.engine.loop import Engine
from busk.engine.snapshot import EngineSnapshot
from busk.io.bindings import BindingResolver
from busk.io.feedback import FeedbackWorker
from busk.io.surfaces import SurfaceManager
from busk.model.show import Show
from busk.model.validate import Issue, has_errors
from busk.output.artnet import ArtNetNetwork
from busk.output.console import ConsoleOutput
from busk.output.sacn import Sequences
from busk.output.scheduler import OutputScheduler, build_routes
from busk.persistence.autosave import AutosaveWorker, Recovery, read_recovery
from busk.persistence.eventlog import EventLog, LogPump
from busk.persistence.paths import state_directory, web_key
from busk.persistence.show_file import ShowLoadError, load_show, newest_backup, utc_now
from busk.persistence.values_file import load_values
from busk.process.links import EngineLink, LocalEngine, RemoteBus, start_log
from busk.process.options import RunOptions
from busk.process.report import RouteReporter, plural, print_statistics, say, warn
from busk.process.root import is_interactive
from busk.process.wire import Attach, Endpoint, Kind, LinkClosed, Processes, loads
from busk.session.library import ProfileLibrary
from busk.session.session import InputSink, Session
from busk.web.api import WebLink

EXIT_FAILED: Final = 70
"""The exit code of a console that hit an unexpected exception (``EX_SOFTWARE``)."""

SETTLE_S: Final = 15.0
"""How long the console waits for the engine to apply the start-up state
before it reads commands anyway (the root's ``STARTUP_S``)."""


class Terminated(BaseException):
    """Raised in the main thread by ``SIGTERM`` or ``SIGHUP``: quit as on
    Ctrl+C in a non-interactive run. A :class:`BaseException`, so the
    console's command handling never swallows it."""


def add_run_arguments(run: argparse.ArgumentParser) -> None:
    """The options of ``busk run`` (also parsed by the console process,
    which the root starts with the same arguments)."""
    run.add_argument("show", type=Path, help="path to a .show or .json show file")
    run.add_argument(
        "--values",
        type=Path,
        metavar="FILE",
        help="logical values for slots no playback controls: a JSON list of park-style entries",
    )
    run.add_argument(
        "--duration",
        type=_positive_seconds,
        metavar="SECONDS",
        help="stop after this many seconds instead of waiting for Ctrl+C or quit",
    )
    run.add_argument(
        "--console",
        action="store_true",
        help="also print each universe to stdout when its bytes change",
    )
    run.add_argument(
        "--script", type=Path, metavar="FILE", help="run console commands from FILE first"
    )
    run.add_argument("--no-console", action="store_true", help="read no console commands")
    run.add_argument(
        "--iface", default="eth0", metavar="IF", help="interface for new multicast/broadcast routes"
    )
    run.add_argument("--state-dir", type=Path, metavar="D", help="busk's state directory")
    run.add_argument(
        "--library",
        type=Path,
        action="append",
        default=[],
        metavar="D",
        help="another directory of fixture profiles (repeatable)",
    )
    run.add_argument("--no-recover", action="store_true", help="ignore the last run's crash state")
    run.add_argument(
        "--threads",
        action="store_true",
        help="run the engine and the output as threads of one process (no watchdog)",
    )
    run.add_argument(
        "--stats",
        type=Path,
        metavar="FILE",
        help="append the processes' statistics to FILE as one JSON line per second",
    )
    run.add_argument(
        "--no-log", action="store_true", help="write no event log (<stateDir>/logs, busk replay)"
    )


def _positive_seconds(text: str) -> float:
    try:
        seconds = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if not seconds > 0:  # also rejects NaN
        raise argparse.ArgumentTypeError(f"must be positive: {text!r}")
    return seconds


# -------------------------------------------------------------------- backends


class Backend(Protocol):
    """What runs the engine for :func:`run_console`, called in this order:
    :meth:`connect`, :meth:`start`, :meth:`arm` (then :meth:`poll` every
    :data:`_SUPERVISE_S` and :meth:`ready` once), :meth:`disarm`,
    :meth:`stop`, :meth:`report`."""

    ownsDuration: bool
    """Whether this process ends the run when ``--duration`` is over."""

    def connect(
        self,
        show: Show,
        compiled: CompiledShow,
        base: NDArray[np.float64] | None,
        clock: Clock,
        *,
        interactive: bool,
        stamp: Stamp,
    ) -> EngineLink:
        """Make the engine side for the compiled show (``base``: the
        ``--values`` frame; ``stamp``: the show's stamp) and return the link
        the console uses."""
        ...

    def start(self) -> None:
        """Start the engine (threads) or connect to it (processes)."""
        ...

    def arm(self) -> None:
        """The command loop begins: signals may end it from now on."""
        ...

    def ready(self) -> None:
        """The engine has the start-up state; commands are read next."""
        ...

    def poll(self) -> None:
        """Print what happened to the output (threads) or the engine (processes)."""
        ...

    def engine_state(self) -> str | None:
        """``stalled``, ``restarting`` or ``failed`` while the engine is not
        running normally (the status shows ``engine …`` then), else ``None``."""
        ...

    def about(self) -> list[str]:
        """The lines ``info`` adds: the run's processes and restarts."""
        ...

    def disarm(self) -> None:
        """Shutdown begins: signals no longer interrupt it."""
        ...

    def stop(self) -> None:
        """Stop the engine (threads) or close the link (processes), after the
        inputs stopped."""
        ...

    def report(self) -> None:
        """Print the final statistics (threads only: the root prints them)."""
        ...


class ThreadsBackend:
    """``busk run --threads``: the engine and the output scheduler as threads
    of this process, as in Phase 6."""

    ownsDuration = True

    def __init__(self, options: RunOptions) -> None:
        self._options = options
        self._engine: Engine | None = None
        self._scheduler: OutputScheduler | None = None
        self._reporter: RouteReporter | None = None
        self._stops = (threading.Event(), threading.Event())  # engine, output
        self._threads: list[threading.Thread] = []
        self._switch_interval = sys.getswitchinterval()
        self._pump: LogPump | None = None  # the event log's writer

    def connect(
        self,
        show: Show,
        compiled: CompiledShow,
        base: NDArray[np.float64] | None,
        clock: Clock,
        *,
        interactive: bool,
        stamp: Stamp,
    ) -> EngineLink:
        """Open the routes (printing their lines) and build the engine. With
        the event log on, the engine keeps records and its first queued item
        is the connection's ``start`` (before the session installs)."""
        sequences = Sequences()
        artnet = ArtNetNetwork()
        routes, notices = build_routes(show["output"], compiled.universes, sequences, artnet=artnet)
        for route in routes:
            print(f"{route.label}: {route.description}")
        for notice in notices:
            print(notice.text, file=sys.stderr if notice.failed else sys.stdout)
        printing = self._options.console and not interactive
        if not routes and not self._options.console:
            print("no output: no route is open (add --console to print frames)", file=sys.stderr)
        engine = Engine(compiled, clock, base)
        printer = ConsoleOutput(engine, compiled.universes, sys.stdout) if printing else None
        self._scheduler = OutputScheduler(
            engine,
            routes,
            clock,
            printer,
            layout=compiled.layout,
            sequences=sequences,
            artnet=artnet,
        )
        self._reporter = RouteReporter(self._scheduler)
        self._engine = engine
        if not self._options.no_log:
            records = start_log(engine, show, base)
            logs = state_directory(self._options.state_dir) / "logs"
            self._pump = LogPump(records, EventLog(logs, report=warn))
        return LocalEngine(engine)

    def start(self) -> None:
        """Start the engine and output threads; keep the engine responsive
        while edits compile (see ``SWITCH_INTERVAL``)."""
        assert self._engine is not None
        assert self._scheduler is not None
        self._switch_interval = sys.getswitchinterval()
        sys.setswitchinterval(SWITCH_INTERVAL)
        engine_stop, output_stop = self._stops
        self._threads = [
            threading.Thread(
                target=self._engine.run, args=(engine_stop,), name="busk-engine", daemon=True
            ),
            threading.Thread(
                target=self._scheduler.run, args=(output_stop,), name="busk-output", daemon=True
            ),
        ]
        for thread in self._threads:
            thread.start()
        if self._pump is not None:
            self._pump.start()

    def arm(self) -> None:
        pass  # Ctrl+C is the only way out, as in Phase 6

    def ready(self) -> None:
        pass

    def poll(self) -> None:
        if self._reporter is not None:
            self._reporter.poll()

    def engine_state(self) -> str | None:
        return None

    def about(self) -> list[str]:
        path = None if self._pump is None else self._pump.log.path
        return [
            f"processes: one (--threads), pid {os.getpid()}",
            log_line(not self._options.no_log, path),
        ]

    def disarm(self) -> None:
        pass

    def stop(self) -> None:
        """The engine stops first, so the output thread's final pass sends the
        last frame it published; then the output thread terminates the
        streams."""
        engine_stop, output_stop = self._stops
        engine_stop.set()
        if self._threads:
            self._threads[0].join()
        output_stop.set()
        if self._threads:
            self._threads[1].join()
        if self._pump is not None:
            self._pump.stop()  # after the engine: its last records too
        sys.setswitchinterval(self._switch_interval)

    def report(self) -> None:
        if self._engine is not None and self._scheduler is not None:
            self.poll()  # the last route changes
            print_statistics(self._engine.stats, self._engine.compiled.engineHz, self._scheduler)


class ProcessBackend:
    """The console process's side: a :class:`~busk.process.links.RemoteBus`
    on the link the root handed over, and the root's control link.

    A thread reads the control link from construction on: ``ATTACH`` hands
    the bus a new engine link (one that comes before :meth:`connect` waits
    for it), ``ENGINE`` is the watchdog's news, ``PROCESSES`` the run's pids
    and restarts (for ``info``), and end of file means the root is gone: the
    process ends at once (decision 9).
    """

    ownsDuration = False

    def __init__(
        self,
        control: socket.socket,
        link: socket.socket,
        *,
        restarted: bool = False,
        log: bool = True,
    ) -> None:
        self._control = Endpoint(control)
        self._log = log  # the event log is on (the root writes it)
        self._restarted = restarted  # this console replaces one that crashed
        self._link: tuple[socket.socket, Attach | None] | None = (link, None)
        self._bus: RemoteBus | None = None
        self._lock = threading.Lock()  # guards _bus and _link
        self._armed = False
        self._terminating = False
        self._state = "running"  # the root's last ENGINE news
        self._processes: Processes | None = None  # the root's last PROCESSES
        self._reconnects = 0  # the bus's reconnects already reported
        threading.Thread(target=self._read_control, name="busk-control", daemon=True).start()

    def connect(
        self,
        show: Show,
        compiled: CompiledShow,
        base: NDArray[np.float64] | None,
        clock: Clock,
        *,
        interactive: bool,
        stamp: Stamp,
    ) -> EngineLink:
        """The session's bus: a :class:`RemoteBus` (attached in :meth:`start`)."""
        bus = RemoteBus(
            compiled,
            clock,
            sessionId=secrets.token_hex(8),
            restarted=self._restarted,
            base=base,
            stamp=stamp,
            log=show if self._log else None,
        )
        with self._lock:
            self._bus = bus
        return bus

    def start(self) -> None:
        """Say ``HELLO`` on the link the root gave (or the newest ``ATTACH``)."""
        with self._lock:
            bus, pending, self._link = self._bus, self._link, None
        if bus is not None and pending is not None:
            bus.attach(*pending)

    def handle_signals(self) -> None:
        """Turn ``SIGTERM`` and ``SIGHUP`` into :class:`Terminated` (main thread only)."""
        for number in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(number, self._signalled)

    def _signalled(self, number: int, frame: FrameType | None) -> None:
        self._terminating = True
        if self._armed:
            self._armed = False
            raise Terminated

    def arm(self) -> None:
        """Signals interrupt the command loop from now on; one that came during
        start-up takes effect now."""
        self._armed = True
        if self._terminating:
            self._armed = False
            raise Terminated

    def ready(self) -> None:
        """Tell the root that the command loop runs (``--duration`` starts)."""
        with contextlib.suppress(OSError):
            self._control.send(Kind.READY)

    def poll(self) -> None:
        """Say ``engine back: …`` after each reconnect but the first, and
        after the first one of a restarted console what it did with the
        running engine's show (``engine: running on …``)."""
        bus = self._bus
        if bus is None or bus.reconnects == self._reconnects:
            return
        first, self._reconnects = self._reconnects == 0, bus.reconnects
        if not first:
            print(engine_back(bus.restored, skipped=bus.restoreSkipped), flush=True)
        elif bus.adoption == "kept":
            print("engine: running on with the same show", flush=True)
        elif bus.adoption == "replaced":
            print(
                "engine: running on; its show went back to the last autosave "
                "(later edits are lost)",
                flush=True,
            )

    def engine_state(self) -> str | None:
        """``failed`` once the watchdog gave up, ``restarting`` while no engine
        is attached, ``stalled`` while the root says so; else ``None``."""
        state = self._state
        bus = self._bus
        if state == "failed":
            return state
        if bus is not None and not bus.attached:
            return "restarting"
        return "stalled" if state == "stalled" else None

    def about(self) -> list[str]:
        """The pids of the three processes and the restarts so far, as the
        root last said (``PROCESSES``)."""
        processes = self._processes
        if processes is None:
            return [f"processes: console {os.getpid()} (the root has not said more yet)"]
        engine = "none (given up)" if processes.engine is None else str(processes.engine)
        path = None if processes.eventLog is None else Path(processes.eventLog)
        return [
            f"processes: root {processes.root}, engine {engine}, console {os.getpid()}",
            f"restarts: engine {processes.engineRestarts}, console {processes.consoleRestarts}",
            log_line(self._log, path),
        ]

    def disarm(self) -> None:
        self._armed = False

    def stop(self) -> None:
        if self._bus is not None:
            self._bus.detach()

    def report(self) -> None:
        pass

    def _read_control(self) -> None:
        """Serve the root's control link; its end of file ends the process."""
        while True:
            try:
                message = self._control.receive()
            except ValueError:
                continue  # an unknown kind: skipped, the stream is intact
            except (OSError, LinkClosed):
                message = None
            if message is None:
                os._exit(0)  # the root is gone: no clean-exit autosave (decision 9)
            if message.kind == Kind.ATTACH and message.fds:
                for extra in message.fds[1:]:
                    os.close(extra)
                attach: Attach = loads(message.payload)
                sock = socket.socket(fileno=message.fds[0])
                with self._lock:
                    bus = self._bus if self._link is None else None
                    if bus is None:  # not started yet: the newest one wins
                        if self._link is not None:
                            self._link[0].close()
                        self._link = (sock, attach)
                if bus is not None:
                    bus.attach(sock, attach)
            elif message.kind == Kind.ENGINE:
                self._state = loads(message.payload)
            elif message.kind == Kind.PROCESSES:
                self._processes = loads(message.payload)
            else:
                for fd in message.fds:
                    os.close(fd)


# ------------------------------------------------------------------- the run


def run_console(options: RunOptions, backend: Backend, *, restarted: str | None = None) -> int:
    """Run the console of ``busk run`` (``options``: the run options) with
    ``backend`` running the engine; return the exit code (0 or 1).

    ``restarted`` (how the previous console ended, e.g. ``killed by signal
    9``) makes this console the replacement of one that crashed (see the
    module docs).
    """
    path: Path = options.show
    state_dir = state_directory(options.state_dir)
    show = _load(path)
    if show is None:
        return 1
    adopt = restarted is not None
    recovery = (
        None
        if options.no_recover and not adopt
        else read_recovery(state_dir, show["meta"]["id"], path, force=adopt)
    )
    recovered_from: Path | None = None
    if recovery is not None and recovery.showAutosave is not None:
        try:
            show, _ = load_show(recovery.showAutosave)
            recovered_from = recovery.showAutosave
        except (ShowLoadError, OSError) as exc:
            print(f"cannot recover {recovery.showAutosave}: {exc}", file=sys.stderr)
    # The stamp of the show loaded: the recovered one's if it is the show that
    # session.json describes (a restarted console compares it with the
    # engine's), else a new one.
    stamp: Stamp = (secrets.token_hex(8), 0)
    if adopt and recovery is not None and recovered_from == recovery.showAutosave:
        stamp = recovery.showStamp or stamp

    try:
        compiled = compile_show(show)
    except UnsupportedFeature as exc:
        print(f"error   {exc}", file=sys.stderr)
        return 1
    print_issues(compiled.warnings, sys.stderr)

    base = None
    if options.values is not None and not adopt:  # a running engine has its base frame
        base = _logical_frame(options.values, show, compiled)
        if base is None:
            return 1

    limitations = collect_limitations(show, compiled)
    if limitations:
        print("Ignored in Phase 7:")
        for limitation in limitations:
            print(f"  {limitation}")

    console_on = not options.no_console
    interactive = is_interactive(options)
    clock = MonotonicClock()
    link = backend.connect(show, compiled, base, clock, interactive=interactive, stamp=stamp)
    session = Session(
        show,
        link.bus,
        compiled=compiled,
        path=path,
        dirty=recovered_from is not None,
        engine_state=lambda: link.snapshot,
        stamp=stamp,
        causes=not options.no_log,
        report=warn,
    )
    if recovery is not None:
        _recover(session, recovery, recovered_from, adopt=adopt)
    library = ProfileLibrary(options.library)
    for problem in library.problems:
        print(f"library: skipped {problem}", file=sys.stderr)

    resolver = BindingResolver(
        show,
        compiled,
        InputSink(session),
        live=lambda: link.compiled,
        page=lambda: _page(link),
        clock=clock.now,
        report=warn,
    )
    try:
        key = web_key(state_dir)
    except OSError as exc:  # a read-only state directory must not stop the show
        key = secrets.token_urlsafe(6)
        print(f"web key not saved: {exc}; it changes on the next run", file=sys.stderr)
    web = WebLink(
        snapshot=lambda: link.snapshot,
        compiled=lambda: link.compiled,
        submit=session.submit,
        clock=clock.now,
        key=key,
    )
    surfaces = SurfaceManager(resolver.handle, web, say=say, warn=warn)
    surfaces.reconcile(compiled)
    feedback = FeedbackWorker(
        lambda: link.compiled,
        lambda: link.snapshot,
        resolver.lastInput,
        clock=clock.now,
        senders=surfaces.senders,
        report=warn,
        say=say,
        warn=warn,
    )
    feedback.open()  # its ports' lines print here; its thread, started later, owns them
    sys.stdout.flush()
    sys.stderr.flush()

    autosave = AutosaveWorker(
        session,
        state_dir,
        clock=clock,
        wall_clock=utc_now,
        masters=lambda: _levels(link),
        tempos=lambda: _tempos(link),
        page=lambda: _page(link),
    )
    if recovered_from is not None:
        autosave.mark_recovered(recovered_from)
    # Move the loaded show and its compiled form out of the cyclic GC's way:
    # full collections then scan only what was allocated since.
    gc.collect()
    gc.freeze()
    autosave_stop, feedback_stop = threading.Event(), threading.Event()
    threads = [
        threading.Thread(
            target=autosave.run, args=(autosave_stop,), name="busk-autosave", daemon=True
        ),
        threading.Thread(
            target=feedback.run, args=(feedback_stop,), name="busk-feedback", daemon=True
        ),
    ]
    backend.start()
    for thread in threads:
        thread.start()
    supervisor = Supervisor(link, surfaces, status_lines=not interactive, extra=backend.poll)
    console = Console(
        session,
        library,
        iface=options.iface,
        status=lambda: _status(link, backend),
        about=backend.about,
    )
    duration = options.duration
    end = math.inf if duration is None or not backend.ownsDuration else clock.now() + duration
    code = 0
    try:
        backend.arm()
        if not link.sync(SETTLE_S):
            print("engine: not answering; reading commands anyway", file=sys.stderr, flush=True)
        backend.ready()
        if adopt:
            print(f"busk console: restarted after a crash ({restarted}); type 'help'", flush=True)
        elif options.script is not None and not console.run_script(options.script, say):
            code = 1
        if code == 0 and not console.quit_requested:
            if interactive:
                supervisor.start()
                if not adopt:
                    print("busk console: type 'help' for the commands, 'quit' to stop.", flush=True)
                interact(console)
            elif console_on:
                _read_commands(console, supervisor, clock, end, waits=options.duration is not None)
            else:
                if options.duration is None:
                    print("Running; press Ctrl+C to stop.", file=sys.stderr, flush=True)
                _wait(supervisor, clock, end)
    except (KeyboardInterrupt, Terminated):
        pass
    finally:
        backend.disarm()
        # Input first (MIDI, OSC and web), so no command arrives after the
        # engine stopped, then feedback, which closes its ports, then the
        # engine (and, with threads, the output).
        supervisor.stop()
        surfaces.close()
        feedback_stop.set()
        threads[1].join()
        session.stop()
        backend.stop()
        autosave_stop.set()
        threads[0].join()
        supervisor.poll()  # report the last changes
        try:
            kept = autosave.finish(clock.now())
        except OSError as exc:
            kept = None
            print(f"autosave failed: {exc}", file=sys.stderr)
        if kept is not None:
            print(f"unsaved edits kept in {kept}")
        gc.unfreeze()
    backend.report()
    return code


def _load(path: Path) -> Show | None:
    """Load the show, printing why not (and the newest backup to try) on failure."""
    try:
        show, warnings = load_show(path)
    except ShowLoadError as exc:
        print_issues(exc.issues, sys.stderr)
        backup = newest_backup(path)
        if backup is not None:
            print(f"the newest backup is {backup}", file=sys.stderr)
        return None
    except OSError as exc:
        cannot_read(path, exc)
        return None
    print_issues(warnings, sys.stderr)
    return show


def _recover(
    session: Session, recovery: Recovery, autosave: Path | None, *, adopt: bool = False
) -> None:
    """Restore what a crashed run left (§18), and say what was recovered.

    The master levels (grand, group, size, speed and fade time) go first,
    then the speed masters' tempos (phase-4-plan §5.12), then the current
    page (Phase 6). Masters and a page the show no longer has are skipped, and so
    are programmer effects that no longer validate against it (each one
    reported). With ``adopt`` (a restarted console) only the programmer is
    restored: the running engine keeps its masters, tempos and page.
    """
    dropped = [*recovery.dropped, *session.restore_programmer(recovery.programmer)]
    programmer = session.programmer
    kinds: dict[str, str] = {ident: m.kind for ident, m in session.compiled.masters.items()}
    restored = tempos = 0
    page = None
    if not adopt:
        for ident, level in recovery.masterLevels.items():
            if ident in kinds:
                command = {"type": "SET_MASTER", "masterId": ident, "level": level}
                restored += session.submit(cast(Command, command)).ok
        for ident, bpm in recovery.speedBpm.items():
            if kinds.get(ident) == "speed":
                command = {"type": "SET_BPM", "masterId": ident, "bpm": bpm}
                tempos += session.submit(cast(Command, command)).ok
        page = next((p for p in session.compiled.pages if p.id == recovery.page), None)
        if page is not None:
            session.submit(cast(Command, {"type": "PAGE", "number": page.number}))
    modes = ["blind"] if programmer.blind else []
    if programmer.highlight:
        modes.append("highlight")
    if programmer.fadeTime:
        modes.append(f"fade {programmer.fadeTime:g} s")
    effects = f", {plural(len(programmer.effects), 'effect')}" if programmer.effects else ""
    parts = [
        f"programmer with {plural(len(programmer.values), 'value')}{effects}"
        + (f" ({', '.join(modes)})" if modes else "")
    ]
    if not adopt:
        parts.append(plural(restored, "master level"))
    if tempos:
        parts.append(plural(tempos, "tempo"))
    if page is not None:
        parts.append(f"page {page.number}")
    if autosave is not None:
        parts.append(f"unsaved edits from {autosave}")
    print(f"recovered {', '.join(parts)}")
    for entry in dropped:
        print(f"recovery: dropped {entry}", file=sys.stderr)


def _levels(link: EngineLink) -> Mapping[str, float]:
    snapshot = link.snapshot
    return {} if snapshot is None else dict(snapshot.masterLevels)


def _tempos(link: EngineLink) -> Mapping[str, float]:
    snapshot = link.snapshot
    return {} if snapshot is None else {status.id: status.bpm for status in snapshot.speed}


def _page(link: EngineLink) -> str | None:
    snapshot = link.snapshot
    return None if snapshot is None or snapshot.page is None else snapshot.page.id


def _status(link: EngineLink, backend: Backend) -> str:
    if (state := backend.engine_state()) is not None:
        return f"engine {state}"
    snapshot = link.snapshot
    return "the engine has not ticked yet" if snapshot is None else status_line(snapshot)


def log_line(on: bool, path: Path | None) -> str:
    """The event log's line of ``info``: its file, or why there is none."""
    if not on:
        return "event log: off (--no-log)"
    return "event log: not open yet" if path is None else f"event log: {path}"


def engine_back(snapshot: EngineSnapshot | None, *, skipped: bool) -> str:
    """What came back after an engine restart, e.g. ``engine back: restored
    7 playbacks, 6 master levels, page 2``."""
    if snapshot is None:
        why = " (it restarted within 10 s of the last restore)" if skipped else ""
        return f"engine back: nothing restored{why}"
    active = sum(status.state == "active" for status in snapshot.playbacks)
    parts = [plural(active, "playback"), plural(len(snapshot.masterLevels), "master level")]
    if snapshot.page is not None:
        parts.append(f"page {snapshot.page.number}")
    return f"engine back: restored {', '.join(parts)}"


def _logical_frame(path: Path, show: Show, compiled: CompiledShow) -> NDArray[np.float64] | None:
    """Load and compile the values file at ``path``; on any error print the
    issues to stderr and return ``None``."""
    try:
        entries, issues = load_values(path, show)
    except OSError as exc:
        cannot_read(path, exc)
        return None
    if entries is None or has_errors(issues):
        print_issues(issues, sys.stderr)
        return None
    frame, issues = compile_values(compiled, entries)
    print_issues(issues, sys.stderr)
    return frame


# ---------------------------------------------------------------- supervisor

_SUPERVISE_S: Final = 0.1
"""How often the supervisor checks the snapshot, the routes and the surfaces."""


_LEVEL_SHOWN: Final = frozenset({"master", "size", "temp"})
"""The fader functions whose level the status line shows."""


def status_line(snapshot: EngineSnapshot) -> str:
    """One line for the engine's state, e.g.
    ``GM 80% | BO off | P1 Main | Speed 1 128 BPM ×2 | Fade 2.5 s | 9 Song on 3 Pre 1.00``.

    ``OUT off`` follows while ``OUTPUT`` has turned DMX output off (Phase
    7). The current page shows its number and name (Phase 6). Each speed master
    shows its tempo and multiplier, and the fade-time override its time
    while a fade-time master is up (Phase 6). Every playback that is
    not idle, is flashing or has a ``master``, ``size`` or ``temp`` fader up
    is listed: its number and name, ``on`` (active) or ``rel`` (releasing),
    the current cue (number and name) of a sequence of several cues, while
    a ``crossfade`` fader drives a transition ``→`` before that cue and the
    progress after it (``18 Manual on → 2 Verse 50%``; Phase 6),
    ``swop`` while a swop button is held (Phase 6), else ``flash``, and
    that fader's level when above 0. A chase shows no step, a
    ``rate`` fader no level (0.5 is its resting state) and an effect no phase,
    so a running chase or effect does not print a line per step or tick
    (phase-4-plan §5.11, phase-5-plan §5.13).
    """
    parts = [f"GM {snapshot.grandMaster:.0%}", f"BO {'on' if snapshot.blackout else 'off'}"]
    if not snapshot.outputEnabled:
        parts.append("OUT off")
    if snapshot.page is not None:
        parts.append(f"P{snapshot.page.number} {snapshot.page.name}")
    if snapshot.speed:
        parts.append(
            " · ".join(
                f"{speed.name} {round(speed.bpm, 1):g} BPM ×{speed.multiplier:g}"
                for speed in snapshot.speed
            )
        )
    if snapshot.fadeTime is not None:
        parts.append(f"Fade {round(snapshot.fadeTime, 1):g} s")
    shown = []
    for playback in snapshot.playbacks:
        level = playback.faderLevel if playback.fader in _LEVEL_SHOWN else 0.0
        if playback.state == "idle" and not playback.flash and level == 0.0:
            continue
        words = [str(playback.number), playback.name]
        if playback.state != "idle":
            words.append("on" if playback.state == "active" else "rel")
            if not playback.chase and playback.cueCount > 1 and playback.cue is not None:
                if playback.progress is not None:
                    words.append("→")
                words.append(playback.cue)
                if playback.cueName:
                    words.append(playback.cueName)
            if playback.progress is not None:
                words.append(f"{playback.progress:.0%}")
        if playback.swop:  # a swop holds the flash up
            words.append("swop")
        elif playback.flash:
            words.append("flash")
        if level > 0.0:
            words.append(f"{level:.2f}")
        shown.append(" ".join(words))
    if shown:
        parts.append(" · ".join(shown))
    return " | ".join(parts)


class Supervisor:
    """What the main thread watched in Phase 2, now also usable from a thread.

    Every :data:`_SUPERVISE_S` seconds :meth:`poll` prints the
    :func:`status_line` if it changed (when ``status_lines``), runs
    ``extra`` (with threads, the route reporter:
    :class:`~busk.process.report.RouteReporter`), opens or closes the
    control surfaces that live edits added, changed or removed, and follows
    MIDI devices plugged in and out (:class:`~busk.io.surfaces.SurfaceManager`).
    """

    def __init__(
        self,
        link: EngineLink,
        surfaces: SurfaceManager,
        *,
        status_lines: bool,
        extra: Callable[[], None] | None = None,
    ) -> None:
        self._link = link
        self._surfaces = surfaces
        self._status_lines = status_lines
        self._extra = extra
        self._shown: EngineSnapshot | None = None
        self._line = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def poll(self) -> None:
        snapshot = self._link.snapshot  # one read: published by reference assignment
        if self._status_lines and snapshot is not None and snapshot is not self._shown:
            self._shown = snapshot
            if (text := status_line(snapshot)) != self._line:
                self._line = text
                print(text, flush=True)
        if self._extra is not None:
            self._extra()
        self._surfaces.reconcile(self._link.compiled)
        self._surfaces.poll(time.monotonic())

    def start(self) -> None:
        """Poll on a thread (while the main thread runs the console prompt)."""
        self._thread = threading.Thread(target=self._loop, name="busk-supervisor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(_SUPERVISE_S):
            self.poll()


def _wait(supervisor: Supervisor, clock: Clock, end: float) -> None:
    """Block until ``end`` (or Ctrl+C), polling the supervisor. The short waits
    keep Ctrl+C responsive on every platform."""
    sleep = threading.Event()  # never set: an interruptible sleep
    while (remaining := end - clock.now()) > 0:
        sleep.wait(min(_SUPERVISE_S, remaining))
        supervisor.poll()


def _read_commands(
    console: Console, supervisor: Supervisor, clock: Clock, end: float, *, waits: bool
) -> None:
    """Console commands from a non-terminal stdin, one per line.

    A reader thread feeds the lines in, so the main thread keeps supervising
    and stops at ``end``. The end of stdin (or stdin that cannot be read)
    quits, unless the run has a duration (``waits``).
    """
    lines: queue.SimpleQueue[str | None] = queue.SimpleQueue()

    def reader() -> None:
        try:
            for line in sys.stdin:
                lines.put(line)
        except (OSError, ValueError):
            pass  # no readable stdin (e.g. captured by a test runner): like its end
        lines.put(None)

    threading.Thread(target=reader, name="busk-stdin", daemon=True).start()
    ended = False
    while not console.quit_requested and (remaining := end - clock.now()) > 0:
        try:
            line = lines.get(timeout=min(_SUPERVISE_S, remaining))
        except queue.Empty:
            supervisor.poll()
            continue
        if line is None:
            ended = True
            if not waits:
                break
            continue
        if not ended:
            reply = console.execute(line)
            if reply.text:
                print(reply.text, flush=True)
            if console.interrupted:  # Ctrl+C during the command: stop, as between commands
                raise KeyboardInterrupt
        supervisor.poll()


# ------------------------------------------------------------------- helpers


def print_issues(issues: Iterable[Issue], stream: TextIO) -> None:
    """One line per issue: its severity, then the issue."""
    for issue in issues:
        print(f"{issue.severity:<7} {issue}", file=stream)


def cannot_read(path: Path, exc: OSError) -> int:
    """Say that ``path`` cannot be read; return the exit code 1."""
    print(f"busk: cannot read {str(path)!r}: {exc.strerror or exc}", file=sys.stderr)
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    """Run the console process on the inherited control and link descriptors."""
    parser = argparse.ArgumentParser(
        prog="python -m busk.process.console_host",
        description="busk's console process; the root of `busk run` starts it.",
    )
    parser.add_argument("--control", type=int, required=True, help="the control socket")
    parser.add_argument("--link", type=int, required=True, help="the engine link socket")
    parser.add_argument(
        "--restarted", metavar="WHY", help="replace a console that crashed (WHY: how it ended)"
    )
    add_run_arguments(parser)
    args = parser.parse_args(argv)
    backend = ProcessBackend(
        socket.socket(fileno=args.control),
        socket.socket(fileno=args.link),
        restarted=args.restarted is not None,
        log=not args.no_log,
    )
    backend.handle_signals()
    try:
        return run_console(RunOptions.from_arguments(args), backend, restarted=args.restarted)
    except (KeyboardInterrupt, Terminated):
        return 0  # during start-up, before the command loop
    except Exception:
        traceback.print_exc()
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
