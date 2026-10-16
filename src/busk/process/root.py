"""The root of ``busk run`` (phase-7-plan §5.1, §5.6, §5.9): the process the operator starts.

It runs no show code: no session, no compiler, no surfaces. It

* spawns the **engine** (``python -m busk.process.engine_host``, in a session
  of its own so terminal signals never reach it) and the **console**
  (``python -m busk.process.console_host`` with the run's own arguments, in
  the terminal's process group, with stdin, stdout and stderr inherited);
* brokers their link: a socket pair whose engine end goes to the engine in
  an ``ATTACH`` and whose console end the console inherits (``--link``);
* runs the **output scheduler** on its own thread, fed by :class:`FrameLink`
  (frames and layouts from the engine's control link), and prints the route
  lines and notices (:class:`~busk.process.report.RouteReporter`) and the
  ``--console`` frame lines;
* owns ``--duration`` (counted from the console's ``READY``) and
  ``--stats FILE`` (one JSON line per second);
* writes the **event log** (phase-7-plan §5.21): the records the engine
  sends in ``LOG`` batches go to an
  :class:`~busk.persistence.eventlog.EventLog` in ``<stateDir>/logs``, and
  the console hears each new file (``PROCESSES``). ``--no-log`` turns it
  off, in the engine too;
* shuts down in order once the console has exited: ``STOP`` to the engine,
  which sends its ``FINAL`` statistics; the output's last pass, which
  terminates the sACN streams; the statistics lines; the console's exit code.

**Signals** (§5.9). ``SIGINT`` is ignored while a console lives (the console
gets its own Ctrl+C); otherwise it shuts the run down. ``SIGTERM`` and
``SIGHUP`` are forwarded to the console as ``SIGTERM`` (it quits as on Ctrl+C
in a non-interactive run), with ``SIGKILL`` after :data:`TERM_KILL_S`.

**The watchdog** (decision 4) runs in the main loop (10 Hz) and uses the
engine's frames as its heartbeat:

* no new frame for :data:`~busk.output.scheduler.STALL_S`: the engine is
  *stalled*. The output holds the last frame (or darkens it) and says so;
  the console hears ``stalled`` (``ENGINE``), then ``running`` if frames
  come again;
* no new frame for :data:`KILL_S`, the engine process ended (a crash, or
  exit 70 after its tick errors), or no first frame :data:`STARTUP_S` after
  it was spawned: ``SIGKILL`` if it still lives, then a new engine and a new
  link pair, whose console end goes to the console in an ``ATTACH`` saying
  why (``engine: restarted (killed by signal 9)`` on stderr). The console
  re-sends its state and restores the last snapshot into it, unless the
  previous restore was less than :data:`RESTORE_GUARD` ago (a crash loop);
* a restart beyond :data:`RESTARTS` in :data:`RESTART_WINDOW`: the watchdog
  gives up. The output keeps holding, the console hears ``failed``, and the
  run ends with 70.

**Console restarts** (decision 7). A console that exits 0 (``quit``) or 1
(load, compile or script failure) ends the run with its code. One that dies
of a signal or exits 70 (an unexpected exception) is replaced: a new console
with the same arguments plus ``--restarted WHY``, on a new link pair whose
engine end goes to the engine in an ``ATTACH`` (``console: restarted (killed
by signal 9)`` on stderr). It adopts the running engine. The engine and
the output never stop meanwhile. Beyond :data:`RESTARTS` in
:data:`RESTART_WINDOW` the root gives the console up: the show runs on
without one until ``SIGINT``, ``SIGTERM`` or ``--duration`` ends the run,
with 70. An engine that dies after that is not restarted: no console could
give it the show.

**Who runs.** Each console hears the pids of the root and the engine and the
restarts so far (``PROCESSES``) when it starts and after every engine
restart; its ``info`` command shows them.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from types import FrameType
from typing import Any, Final, TextIO

from busk.compiler.compile import OutputLayout
from busk.engine.clock import MonotonicClock
from busk.engine.loop import Frame
from busk.output.console import ConsoleOutput
from busk.output.scheduler import STALL_S, OutputScheduler
from busk.persistence.eventlog import EventLog
from busk.persistence.paths import state_directory
from busk.process.report import RouteReporter, plural, print_statistics
from busk.process.wire import (
    Attach,
    Endpoint,
    EngineReport,
    Kind,
    LinkClosed,
    Processes,
    decode_frame,
    dumps,
    loads,
)

SUPERVISE_S: Final = 0.1
"""How often the root's main loop looks at its children, signals and routes."""

STATS_S: Final = 1.0
"""How often a ``--stats`` line is written."""

TERM_KILL_S: Final = 5.0
"""How long a console has to quit after ``SIGTERM`` before ``SIGKILL``."""

STOP_S: Final = 5.0
"""How long the engine has to send ``FINAL`` and exit after ``STOP``."""

EXIT_FAILED: Final = 70
"""The run's exit code when a child was given up (``EX_SOFTWARE``)."""

KILL_S: Final = 3.0
"""Seconds without a new frame after which the engine is killed and restarted."""

STARTUP_S: Final = 15.0
"""Seconds a new engine has for its first frame: its imports and the
console's full install of a §19-sized show."""

RESTARTS: Final = 3
"""Engine restarts allowed per :data:`RESTART_WINDOW`; one more gives up."""

RESTART_WINDOW: Final = 60.0
"""Seconds over which :data:`RESTARTS` are counted."""

RESTORE_GUARD: Final = 10.0
"""A restart this soon after one that restored skips the restore (decision 5)."""


class FrameLink:
    """The output scheduler's frame source in the root: what the engine
    sends on its control link. :meth:`serve` runs on the root's frame thread.

    Layout ids are per engine process (each counts from 1), so each
    :meth:`serve` call keeps its own table; :attr:`latest` stays across
    calls, so the output holds the last frame while no engine sends.
    Event-log batches go to ``log`` (``None``: dropped); a lock keeps the
    file to one writer when a restarted engine's thread overlaps the old
    one's.
    """

    def __init__(self, log: EventLog | None = None) -> None:
        self.log = log
        self._log_lock = threading.Lock()
        self.latest: Frame | None = None
        """The newest frame (its ``layout`` set, its ``compiled`` ``None``)."""
        self.frameAt = 0.0
        """``time.monotonic()`` when :attr:`latest` arrived."""
        self.report: EngineReport | None = None
        """The engine's latest statistics (``STATS``, then ``FINAL``)."""
        self.final = False
        """Whether :attr:`report` is the engine's ``FINAL``."""

    def serve(self, control: Endpoint) -> None:
        """Read one engine's control link until its end of file."""
        layouts: dict[int, OutputLayout] = {}
        while True:
            try:
                message = control.receive()
            except ValueError:
                continue  # an unknown kind: skipped, the stream is intact
            except (OSError, LinkClosed):
                return
            if message is None:
                return
            if message.kind == Kind.FRAME:
                self.latest = decode_frame(message.payload, layouts)
                self.frameAt = time.monotonic()
            elif message.kind == Kind.LAYOUT:
                ident, layout = loads(message.payload)
                layouts[ident] = layout
            elif message.kind in (Kind.STATS, Kind.FINAL):
                self.report = loads(message.payload)
                self.final = message.kind == Kind.FINAL
            elif message.kind == Kind.LOG and self.log is not None:
                with self._log_lock:
                    for t, item in loads(message.payload):
                        self.log.add(t, item)
                    self.log.flush()

    @property
    def engineHz(self) -> float | None:
        """The engine rate of the newest frame's show (``None`` before one)."""
        frame = self.latest
        return None if frame is None or frame.layout is None else frame.layout.engineHz


class Root:
    """Runs ``busk run`` as three processes (see the module docs).

    ``run_argv`` are the arguments after ``run``, passed to the console as
    they are; ``args`` is their parse.
    """

    def __init__(self, args: argparse.Namespace, run_argv: Sequence[str]) -> None:
        self._args = args
        self._argv = list(run_argv)
        self._log = (
            None
            if args.no_log
            else EventLog(state_directory(args.state_dir) / "logs", opened=self._log_opened)
        )
        self._log_path: Path | None = None  # the event log's file, once open
        self._frames = FrameLink(self._log)
        self._clock = MonotonicClock()
        printer = (
            ConsoleOutput(self._frames, (), sys.stdout)
            if args.console and not is_interactive(args)
            else None
        )
        self._scheduler = OutputScheduler(self._frames, [], self._clock, printer)
        self._reporter = RouteReporter(self._scheduler)
        self._engine: subprocess.Popen[bytes] | None = None
        self._engine_control: Endpoint | None = None
        self._console: subprocess.Popen[bytes] | None = None
        self._console_control: Endpoint | None = None
        self._ready_at: float | None = None  # when the console said READY
        self._terminate = False  # SIGTERM or SIGHUP came
        self._interrupted = False  # SIGINT came while no console lived
        self._kill_at: float | None = None  # SIGTERM went to the console: SIGKILL then
        self._routes_checked = False  # the "no output" warning was considered
        self._stats_file: TextIO | None = None
        self._frames_thread: threading.Thread | None = None  # serves the current engine
        self._engine_started = 0.0  # time.monotonic() at its spawn
        self._restart_times: list[float] = []  # within RESTART_WINDOW
        self._restored_at: float | None = None  # the last restart that restored
        self._news = "running"  # what the console last heard (ENGINE)
        self._console_times: list[float] = []  # console restarts within RESTART_WINDOW
        self.restarts = 0
        """Engine restarts so far."""
        self.failed = False
        """Whether the watchdog gave the engine up."""
        self.consoleRestarts = 0
        """Console restarts so far."""
        self.consoleFailed = False
        """Whether the console was given up (the show runs on without one)."""

    # -- lifecycle

    def run(self) -> int:
        """Spawn the children, supervise until the console ends (or, once it
        was given up, until a signal or ``--duration``), shut down; return the
        console's exit code (70 if a child was given up)."""
        previous = {
            number: signal.signal(number, self._signalled)
            for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
        }
        output_stop = threading.Event()
        output = threading.Thread(
            target=self._scheduler.run, args=(output_stop,), name="busk-output", daemon=True
        )
        try:
            if self._args.stats is not None:
                self._stats_file = self._args.stats.open("a", encoding="utf-8")
            with self._start_engine() as console_end:
                self._start_console(console_end, None)
            output.start()
            code = self._supervise()
        finally:
            self._shutdown(self._frames_thread, output, output_stop)
            for number, handler in previous.items():
                signal.signal(number, handler)
            if self._stats_file is not None:
                self._stats_file.close()
            if self._log is not None:
                self._log.close()
        engine_hz = self._frames.engineHz
        if engine_hz is not None:
            report = self._frames.report
            stats = None if report is None else report.stats
            print_statistics(stats, engine_hz, self._scheduler, restarts=self.restarts)
        return EXIT_FAILED if self.failed or self.consoleFailed else code

    def _supervise(self) -> int:
        """The main loop: until the console has exited (or a ``SIGINT`` with
        no console), restart a crashed console, report routes, forward
        signals, end ``--duration``, write ``--stats``; return the run's exit
        code."""
        stats_due = time.monotonic()
        duration = self._args.duration
        while True:
            self._report_routes()
            now = time.monotonic()
            console = self._console
            assert console is not None
            if not self.consoleFailed and (code := console.poll()) is not None:
                ended = self._console_ended(code, now)
                if ended is not None:
                    return ended
                console = self._console  # a new one, or the dead one given up
                assert console is not None
            if self._interrupted:
                return 0
            self._watch(now)
            due = (
                duration is not None
                and self._ready_at is not None
                and now >= self._ready_at + duration
            )
            if self.consoleFailed:
                if due:
                    return 0  # run() makes it 70
            elif self._terminate or due:
                self._terminate = False
                if self._kill_at is None:
                    self._kill_at = now + TERM_KILL_S
                    with contextlib.suppress(ProcessLookupError):
                        console.send_signal(signal.SIGTERM)
            if self._kill_at is not None and now >= self._kill_at:
                with contextlib.suppress(ProcessLookupError):
                    console.kill()
            if self._stats_file is not None and now >= stats_due:
                self._write_stats()
                stats_due = now + STATS_S
            time.sleep(SUPERVISE_S)

    def _console_ended(self, code: int, now: float) -> int | None:
        """The run's code for a console exit code: 0 and 1 as they are. A
        crash (a signal, or 70) starts a new console, or gives the console up:
        ``None``, the run goes on. Any other code, or a console the root had
        told to quit, is a failure (70), said on stderr."""
        if code in (0, 1):
            return code
        why = f"killed by signal {-code}" if code < 0 else f"exited with code {code}"
        crashed = code < 0 or code == EXIT_FAILED
        if self._kill_at is not None or not crashed:
            print(f"console: {why}", file=sys.stderr, flush=True)
            return EXIT_FAILED
        self._restart_console(why, now)
        return None

    def _restart_console(self, why: str, now: float) -> None:
        """Start a new console on a new link pair (decision 7), or give the
        console up after :data:`RESTARTS` in :data:`RESTART_WINDOW`."""
        self._console_times = [t for t in self._console_times if now - t < RESTART_WINDOW]
        if len(self._console_times) >= RESTARTS:
            self.consoleFailed = True
            print(
                f"console: {why}; given up after {plural(RESTARTS, 'restart')} "
                f"in {RESTART_WINDOW:g} s; the show runs on, Ctrl+C stops it",
                file=sys.stderr,
                flush=True,
            )
            return
        self._console_times.append(now)
        self.consoleRestarts += 1
        console_end, engine_end = socket.socketpair()
        with console_end, engine_end:
            control = self._engine_control
            if control is not None:  # else the next engine's ATTACH reaches the console
                with contextlib.suppress(OSError):
                    control.send(Kind.ATTACH, dumps(Attach()), [engine_end.fileno()])
            self._start_console(console_end, why)
        print(f"console: restarted ({why})", file=sys.stderr, flush=True)

    def _start_console(self, link: socket.socket, why: str | None) -> None:
        """Spawn a console on ``link`` (the console end of an engine link),
        with ``--restarted WHY`` when it replaces one that crashed, and read
        its control link. It hears the watchdog's news if it is not
        ``running``."""
        argv = self._argv if why is None else [*self._argv, "--restarted", why]
        self._console, control = _spawn_console(link, argv)
        self._console_control = control
        threading.Thread(target=self._read_console, args=(control,), daemon=True).start()
        if self._news != "running":
            with contextlib.suppress(OSError):
                control.send(Kind.ENGINE, dumps(self._news))
        self._tell_processes()

    def _tell_processes(self) -> None:
        """Send the console the run's pids and restarts (``PROCESSES``)."""
        control, engine = self._console_control, self._engine
        if control is None:
            return
        processes = Processes(
            root=os.getpid(),
            engine=None if engine is None or self.failed else engine.pid,
            engineRestarts=self.restarts,
            consoleRestarts=self.consoleRestarts,
            eventLog=None if self._log_path is None else str(self._log_path),
        )
        with contextlib.suppress(OSError):
            control.send(Kind.PROCESSES, dumps(processes))

    def _log_opened(self, path: Path) -> None:
        """The event log opened a new file (on the frame thread): tell the console."""
        self._log_path = path
        self._tell_processes()

    def _shutdown(
        self, frames: threading.Thread | None, output: threading.Thread, stop: threading.Event
    ) -> None:
        """``STOP`` to the engine and its ``FINAL``; then the output's last pass
        and the drivers' close (Stream_Terminated); the last route changes."""
        console = self._console
        if console is not None and console.poll() is None:  # only after a failure
            console.kill()
            console.wait()
        control = self._engine_control
        if control is not None:
            with contextlib.suppress(OSError):
                control.send(Kind.STOP)
        if frames is not None:
            frames.join(STOP_S)
        engine = self._engine
        if engine is not None:
            try:
                engine.wait(STOP_S)
            except subprocess.TimeoutExpired:
                engine.kill()
                engine.wait()
        if output.is_alive():
            stop.set()
            output.join()
        else:
            self._scheduler.close()  # never started: the routes may not exist, but be sure
        self._report_routes()
        for endpoint in (self._engine_control, self._console_control):
            if endpoint is not None:
                endpoint.sock.close()

    # -- the engine and its watchdog

    def _start_engine(self) -> socket.socket:
        """Spawn an engine, serve its control link on a new frame thread and
        attach it to a new link pair; return the pair's console end."""
        # The old engine's frame thread has ended (_stop_engine): its last
        # statistics must not appear next to the new engine's pid.
        self._frames.report = None
        self._frames.final = False
        self._engine, control = _spawn_engine(log=self._log is not None)
        self._engine_control = control
        self._engine_started = time.monotonic()
        self._frames_thread = threading.Thread(
            target=self._frames.serve, args=(control,), name="busk-frames", daemon=True
        )
        self._frames_thread.start()
        console_end, engine_end = socket.socketpair()
        with engine_end:
            control.send(Kind.ATTACH, dumps(Attach()), [engine_end.fileno()])
        return console_end

    def _watch(self, now: float) -> None:
        """Decision 4 (see the module docs), once per main-loop pass."""
        engine = self._engine
        if self.failed or engine is None:
            return
        code = engine.poll()
        if code is not None:
            why = f"killed by signal {-code}" if code < 0 else f"exited with code {code}"
            self._restart(why)
            return
        last = self._frames.frameAt
        if last < self._engine_started:  # no frame from this engine yet
            if now - self._engine_started > STARTUP_S:
                self._restart(f"no first frame in {STARTUP_S:g} s")
            return
        quiet = now - last
        if quiet >= KILL_S:
            self._restart(f"no new frame for {KILL_S:g} s")
        else:
            self._tell("stalled" if quiet >= STALL_S else "running")

    def _restart(self, why: str) -> None:
        """Kill the engine if it lives and start a new one, or give up."""
        now = time.monotonic()
        self._stop_engine()
        self._restart_times = [t for t in self._restart_times if now - t < RESTART_WINDOW]
        if len(self._restart_times) >= RESTARTS or self.consoleFailed:
            self.failed = True
            self._tell("failed")
            reason = (
                "no console to give a new one the show"
                if self.consoleFailed
                else f"given up after {plural(RESTARTS, 'restart')} in {RESTART_WINDOW:g} s"
            )
            print(
                f"engine: {why}; {reason}; the output holds the last frame",
                file=sys.stderr,
                flush=True,
            )
            self._tell_processes()
            return
        self._restart_times.append(now)
        self.restarts += 1
        restore = self._restored_at is None or now - self._restored_at >= RESTORE_GUARD
        if restore:
            self._restored_at = now
        self._tell("restarting")
        with self._start_engine() as console_end:
            attach = Attach(reason=f"engine restarted: {why}", restore=restore)
            control = self._console_control
            if control is not None:
                with contextlib.suppress(OSError):
                    control.send(Kind.ATTACH, dumps(attach), [console_end.fileno()])
        self._tell_processes()
        print(f"engine: restarted ({why})", file=sys.stderr, flush=True)

    def _stop_engine(self) -> None:
        """Kill the engine if it lives, reap it, and end its frame thread (so
        no frame of it arrives after a new engine started)."""
        engine, control, frames = self._engine, self._engine_control, self._frames_thread
        if engine is not None and engine.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                engine.kill()
        if engine is not None:
            engine.wait()
        if control is not None:
            control.shutdown()
        if frames is not None:
            frames.join(STOP_S)
        if control is not None:
            control.sock.close()
        self._engine = self._engine_control = self._frames_thread = None

    def _tell(self, news: str) -> None:
        """Send the console the watchdog's news (``ENGINE``) when it changed."""
        if news == self._news:
            return
        self._news = news
        control = self._console_control
        if control is not None:
            with contextlib.suppress(OSError):
                control.send(Kind.ENGINE, dumps(news))

    # -- what the root watches

    def _signalled(self, number: int, frame: FrameType | None) -> None:
        """``SIGINT``: ignored while a console lives, else the end. ``SIGTERM``,
        ``SIGHUP``: forwarded to the console by the main loop."""
        console = self._console
        alive = console is not None and console.poll() is None
        if number == signal.SIGINT:
            if not alive:
                self._interrupted = True
        else:
            self._terminate = True
            if not alive:
                self._interrupted = True

    def _read_console(self, control: Endpoint) -> None:
        """A console's control link: the first ``READY`` starts
        ``--duration``. The link closes when the console is gone."""
        while True:
            try:
                message = control.receive()
            except ValueError:
                continue
            except (OSError, LinkClosed):
                break
            if message is None:
                break
            if message.kind == Kind.READY and self._ready_at is None:
                self._ready_at = time.monotonic()
        control.sock.close()

    def _report_routes(self) -> None:
        """Print route changes; once the first layout opened the routes, warn
        when none is open and no frames are printed."""
        self._reporter.poll()
        if not self._routes_checked and self._scheduler.layout is not None:
            self._routes_checked = True
            if not self._scheduler.routes and not self._args.console:
                print(
                    "no output: no route is open (add --console to print frames)",
                    file=sys.stderr,
                    flush=True,
                )

    def _write_stats(self) -> None:
        """One ``--stats`` line (see :func:`stats_record`)."""
        assert self._stats_file is not None
        record = stats_record(self._engine, self._console, self._frames, self._scheduler)
        record["engine"]["restarts"] = self.restarts
        if self.failed or self._news != "running":
            record["engine"]["state"] = self._news
        record["console"]["restarts"] = self.consoleRestarts
        if self.consoleFailed:
            record["console"]["pid"] = record["console"]["rss"] = None
        self._stats_file.write(json.dumps(record) + "\n")
        self._stats_file.flush()


def stats_record(
    engine: subprocess.Popen[bytes] | None,
    console: subprocess.Popen[bytes] | None,
    frames: FrameLink,
    scheduler: OutputScheduler,
) -> dict[str, Any]:
    """A ``--stats`` line: the engine (pid, state, restarts, ticks, overruns,
    longest tick, tick, install and command errors, longest GC pause, RSS;
    the counters are the current engine process's), the console (pid,
    restarts, RSS), the root (RSS, late output cycles, longest gap between
    cycles) and each route's status. RSS is in bytes (``None`` where
    ``/proc`` cannot tell); times are in milliseconds."""
    report = frames.report
    stats = None if report is None else report.stats
    engine_pid = None if engine is None else engine.pid
    output = scheduler.stats
    routes = []
    for route in scheduler.routes:
        status = route.driver.status()
        routes.append(
            {
                "id": route.id,
                "label": route.label,
                "ok": status.ok,
                "detail": status.detail,
                "packets": status.packets,
                "errors": status.errors,
                "dropped": status.dropped,
                "faults": route.faults,
            }
        )
    return {
        "time": time.time(),
        "engine": {
            "pid": engine_pid,
            "state": "running" if frames.latest is not None else "starting",
            "restarts": 0,
            "ticks": None if stats is None else stats.ticks,
            "overruns": None if stats is None else stats.overruns,
            "maxTickMs": None if stats is None else stats.maxTickSeconds * 1000,
            "tickErrors": None if stats is None else stats.tickErrors,
            "installErrors": None if stats is None else stats.installErrors,
            "commandErrors": None if stats is None else stats.commandErrors,
            "gcPauseMs": None if report is None else report.gcPause * 1000,
            "rss": None if engine_pid is None else rss(engine_pid),
        },
        "console": {
            "pid": None if console is None else console.pid,
            "restarts": 0,
            "rss": None if console is None else rss(console.pid),
        },
        "root": {
            "rss": rss(os.getpid()),
            "lateCycles": output.lateCycles,
            "longestGapMs": output.longestGap * 1000,
        },
        "routes": routes,
    }


def rss(pid: int) -> int | None:
    """The resident set size of process ``pid`` in bytes, from
    ``/proc/<pid>/statm`` (``None`` where there is no ``/proc``, or no such
    process)."""
    try:
        resident = Path(f"/proc/{pid}/statm").read_text().split()[1]
    except (OSError, IndexError):
        return None
    return int(resident) * os.sysconf("SC_PAGE_SIZE")


def is_interactive(args: argparse.Namespace) -> bool:
    """Whether ``busk run args`` opens the interactive prompt: the console
    reads commands, there is no ``--duration``, and stdin is a terminal.
    (``--console`` frame lines are off at a prompt.)"""
    if args.no_console or args.duration is not None:
        return False
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError, OSError):
        return False


# ------------------------------------------------------------------ children


def _spawn_engine(*, log: bool) -> tuple[subprocess.Popen[bytes], Endpoint]:
    """Start an engine process in a session of its own (``log``: it sends
    event-log records); return it and the root's end of its control link."""
    ours, theirs = socket.socketpair()
    with theirs:
        command = [sys.executable, "-m", "busk.process.engine_host"]
        command += ["--control", str(theirs.fileno()), *(["--log"] if log else [])]
        process = subprocess.Popen(
            command,
            pass_fds=(theirs.fileno(),),
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    return process, Endpoint(ours)


def _spawn_console(
    link: socket.socket, argv: Sequence[str]
) -> tuple[subprocess.Popen[bytes], Endpoint]:
    """Start a console process with the run's arguments and the console end
    of an engine link; return it and the root's end of its control link."""
    ours, theirs = socket.socketpair()
    with theirs:
        command = [
            sys.executable,
            "-m",
            "busk.process.console_host",
            "--control",
            str(theirs.fileno()),
            "--link",
            str(link.fileno()),
            *argv,
        ]
        process = subprocess.Popen(command, pass_fds=(theirs.fileno(), link.fileno()))
    return process, Endpoint(ours)
