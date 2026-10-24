"""Running a show from Python (phase-8-plan §5.4–§5.5).

Two facades over the same parts (a session, its console and an engine):

* :class:`OfflineShow` runs on a clock the caller drives: no threads, no
  sockets, and no files unless asked (a ``path`` to save to, a script to
  read). It is what ``tests/session_harness.py`` and the Phase 3–7 build
  tests wire by hand.
* :class:`LiveShow` runs in real time inside the caller's process: the
  engine and the DMX output as threads, and optionally the show's control
  surfaces (MIDI, OSC, the web remote). It has none of ``busk run``'s
  safety net: no watchdog, no process isolation, no autosave or crash
  recovery, so a crash of the host process stops the output. For a show
  on stage, use ``busk run``.

**Commands happen now** (decision 20). The engine applies commands and live
edits at its next tick. :class:`OfflineShow` ticks at the current engine
time after every :meth:`~OfflineShow.submit`, every
:meth:`~OfflineShow.execute` and every script line, so the command has taken
effect when the call returns; time does not move, so a fade or a chase is
where it was. Only :meth:`~OfflineShow.tick` moves time. A
:class:`LiveShow`'s engine ticks on its own, ``engineHz`` times a second.

Frames are :class:`DmxFrame`\\ s: the engine's frame by universe *number*,
without its compiled show and output layout, which are internal. The
``output`` of both facades is the same tick per fixture element, as logical
values with what drives them (:class:`~busk.engine.snapshot.OutputSnapshot`,
GAP-01 of ``docs/dev/tui/engine-gaps.md``), their ``effects`` the effect
instances that tick ran (:class:`~busk.engine.snapshot.EffectSnapshot`,
GAP-09), and their ``programmer`` is the programmer with fixtures by number
(:class:`~busk.session.status.ProgrammerStatus`, GAP-02). A :class:`LiveShow`'s
``routes`` are its output routes and what each does
(:class:`~busk.output.driver.RouteStatus`, GAP-07), and its ``surfaces`` its
control surfaces (:class:`~busk.io.surfaces.SurfaceStatus`, GAP-08).
``confirmation(line)`` is the question ``busk run``'s prompt asks before a
dangerous line (GAP-10), for a frontend to ask too, and ``effect_templates``
the templates ``effect add`` takes, the show's and the effect library's
(:class:`~busk.console.console.EffectTemplateInfo`, GAP-15). A line's
:class:`~busk.console.console.Reply` says whether it asked to quit, for a
frontend to end as ``busk run``'s prompt does (GAP-18), and ``status``
answers with ``busk run``'s status line (GAP-19).

Errors (§5.8): constructing a facade raises
:class:`~busk.persistence.show_file.ShowLoadError` for an invalid show and
:class:`~busk.compiler.compile.UnsupportedFeature` for a show busk cannot
run yet. ``submit``, ``execute`` and ``save`` never raise: they return a
result whose ``ok`` is ``False``. ``run_script`` raises
:class:`~busk.errors.ScriptError` at the first failing line, and
:class:`OSError` if the script cannot be read.

**Ctrl+C.** The console holds SIGINT back while a line runs, so a command is
never split (see :mod:`busk.console.console`). The facade then raises
:class:`KeyboardInterrupt` once the line is done, as Python would have: on
the main thread, the only one SIGINT reaches.

**Threads** (GAP-12 of ``docs/dev/tui/engine-gaps.md``). A
:class:`LiveShow` takes lines, commands and reads from any number of threads
at once. Lines from different threads run as if one after the other, a
script whole, except performance lines (``go``, ``fader``, ``gm`` …), which
never wait for another thread's line: they go straight to the engine's
queue, even while an edit compiles, a save writes or a script runs. An
:class:`OfflineShow` ticks its engine inside each call, so it takes them
from one thread at a time.

**Logging** (decision 18). Nothing here prints. A :class:`LiveShow` logs its
route lines (``sACN r1: …``) on ``busk.output``, its surface lines (the web
remote's URLs among them) on ``busk.surfaces`` and failed surface commands
on ``busk.session``: INFO for news, WARNING for failures.
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import Final, Literal, Self

from busk.commands.types import Command
from busk.compiler.compile import CompiledShow, compile_show
from busk.console.console import Console, EffectTemplateInfo, Reply, status_line
from busk.engine.clock import SWITCH_INTERVAL, Clock, FakeClock, MonotonicClock
from busk.engine.effect_status import EffectCapture, read_effects
from busk.engine.install import Stamp
from busk.engine.link import EngineLink, LocalEngine
from busk.engine.loop import Engine, Frame
from busk.engine.readout import Capture, read_output
from busk.engine.snapshot import EffectSnapshot, EngineSnapshot, OutputSnapshot
from busk.errors import ScriptError
from busk.io.bindings import BindingResolver
from busk.io.feedback import FeedbackWorker
from busk.io.surfaces import SurfaceManager, SurfaceStatus
from busk.model.show import Show
from busk.model.validate import Issue, has_errors, validate_show
from busk.output.artnet import ArtNetNetwork
from busk.output.console import ConsoleOutput
from busk.output.driver import RouteStatus
from busk.output.sacn import Sequences
from busk.output.scheduler import OutputScheduler, build_routes
from busk.persistence.paths import web_key
from busk.persistence.show_file import ShowLoadError, show_json
from busk.session.ids import IdFactory
from busk.session.library import ProfileLibrary
from busk.session.session import CommandResult, InputSink, Report, Session, SessionSnapshot
from busk.session.status import ProgrammerStatus, programmer_status
from busk.web.api import WebLink

_output_log = logging.getLogger("busk.output")
_surfaces_log = logging.getLogger("busk.surfaces")

SETTLE_S: Final = 15.0
"""How long :meth:`LiveShow.start`, and ``busk run``'s console before its
first command, wait for the engine's first snapshot."""

MONITOR_S: Final = 0.1
"""How often a :class:`LiveShow` (and ``busk run``'s console) looks at its
routes and surfaces."""


@dataclass(frozen=True, kw_only=True)
class DmxFrame:
    """One engine output: 512 DMX bytes per universe.

    ``universes`` maps each universe's *number* (as the show numbers it, not
    its row in the engine) to its bytes, in ascending number order. ``seq``
    counts the engine's ticks from 1, and ``time`` is the engine time of the
    tick that made the frame, in seconds.
    """

    seq: int
    time: float
    universes: Mapping[int, bytes]


def _dmx_frame(frame: Frame) -> DmxFrame:
    """The public form of an engine frame (one from another process too)."""
    assert frame.layout is not None  # only hand-built test frames lack it
    numbers = (universe.number for universe in frame.layout.universes)
    return DmxFrame(
        seq=frame.seq,
        time=frame.time,
        universes=MappingProxyType(dict(zip(numbers, frame.universes, strict=True))),
    )


def _checked(show: Show) -> tuple[Show, CompiledShow]:
    """``show`` validated in full and compiled.

    The whole document is validated, not just its semantics: a ``Show``
    built by hand has never been through the structural checks. Raises
    :class:`ShowLoadError` for any validation error, and
    :class:`~busk.compiler.compile.UnsupportedFeature` from compiling.
    """
    checked, issues = validate_show(show_json(show))
    if checked is None or has_errors(issues):
        raise ShowLoadError(issues)
    return checked, compile_show(checked)


def _optional_path(path: str | os.PathLike[str] | None) -> Path | None:
    return None if path is None else Path(path)


class _Facade:
    """What both facades share: a session and its console, built by the
    subclass, and the methods that only go through them."""

    _session: Session
    _console: Console
    _status: tuple[SessionSnapshot, ProgrammerStatus] | None = None  # the last programmer read
    _templates: tuple[Show, tuple[EffectTemplateInfo, ...]] | None = None  # and templates read

    # ----------------------------------------------------------- reading

    @property
    def show(self) -> Show:
        """The committed show document, with every edit so far."""
        return self._session.show

    @property
    def programmer(self) -> ProgrammerStatus:
        """The programmer: its selection, values and effects, blind,
        highlight and fade time, with fixtures by number (see
        :class:`~busk.session.status.ProgrammerStatus`). A new object, with
        a higher ``version``, only once one of them has changed."""
        snapshot = self._session.snapshot  # one read: published by reference assignment
        cached = self._status
        if cached is not None and cached[0] is snapshot:
            return cached[1]
        previous = None if cached is None else cached[1]
        status = programmer_status(snapshot.state, snapshot.programmer, previous)
        self._status = (snapshot, status)  # one assignment: other threads see the pair whole
        return status

    @property
    def effect_templates(self) -> tuple[EffectTemplateInfo, ...]:
        """The effect templates ``effect add "<name>"`` takes: the show's, in
        show order, then the effect library's that the show has no copy of,
        in library order, each with its layers in one line and the library's
        defaults (see :class:`~busk.console.console.EffectTemplateInfo`). The
        same tuple until one of them changes."""
        show = self._session.show  # one read: replaced, never changed, by an edit
        cached = self._templates
        if cached is not None and cached[0] is show:
            return cached[1]
        templates = self._console.effect_templates(show)
        if cached is not None and cached[1] == templates:
            templates = cached[1]
        self._templates = (show, templates)  # one assignment, as for the programmer
        return templates

    @property
    def warnings(self) -> tuple[Issue, ...]:
        """The compiler's warnings about :attr:`show` (cue values it drops,
        unpatched fixtures …), in document order."""
        return self._session.compiled.warnings

    # ---------------------------------------------------------- commands

    def submit(self, command: Command) -> CommandResult:
        """Carry out one command (any of :data:`~busk.commands.types.Command`).
        Never raises: a refused command has ``ok=False`` and a message."""
        result = self._session.submit(command)
        self._settle()
        return result

    def execute(self, line: str) -> Reply:
        """Run one console line (``help`` lists them). Never raises (apart
        from :class:`KeyboardInterrupt`, see the module docs): a failed line
        has ``ok=False`` and says why in its text.

        A :class:`LiveShow` takes lines from several threads at once. A
        performance line, one the engine carries out (``go N``, ``back N``,
        ``goto N C``, ``release N``, ``release all``, ``fader N L``, ``flash
        N on|off``, ``toggle N``, ``button N B on|off`` but for a select
        button's press, ``gm L``, ``master "name" L``, ``blackout on|off``,
        ``tap``, ``bpm``, ``page N|next|prev``, ``output on|off``), never
        waits for another thread's line. Any other line waits until the line
        another thread runs, a ``source`` script included, is done.

        ``quit`` (or ``exit``) stops nothing here: its reply has
        ``quit=True``, as has that of a ``source`` whose script stops at a
        ``quit``, and ending is the caller's business (GAP-18). ``busk run``
        ends after these lines, and a frontend ends the run by returning.

        ``status`` prints ``busk run``'s status line of the engine's newest
        snapshot, ``GM 80% | BO off | P1 Main | …`` (GAP-19). A
        :class:`LiveShow` prints it while it runs, and says ``no engine is
        running`` before :meth:`start` and after :meth:`stop`; a performance
        line sent just before shows in it once the engine has ticked."""
        reply = self._console.execute(line)
        self._interrupted()
        return reply

    def confirmation(self, line: str) -> str | None:
        """The yes/no question to ask before running ``line``, or ``None`` to
        run it at once. ``busk run``'s prompt asks ``Turn all DMX output
        off?`` before ``output off``, and a frontend that asks the same
        calls this first: :meth:`execute` never asks.

        ``None`` too for a line that does not parse (:meth:`execute` says
        why) and for ``source``, whose lines are never asked about. The
        question is text to show as it is. Asking changes nothing (no id
        is used up), and it only reads the show and the programmer, so a
        frontend may ask from its own thread.
        """
        return self._console.confirmation(line)

    def run_script(self, path: str | os.PathLike[str]) -> list[str]:
        """Run the console script at ``path``, line by line, and return the
        lines it wrote. A ``quit`` line ends it early (the script, not the
        show).

        Raises :class:`~busk.errors.ScriptError` at the first line that
        fails (the lines after it do not run; the edits before it stay),
        and :class:`OSError` if the file cannot be read.
        """
        path = Path(path)
        lines = path.read_text(encoding="utf-8").splitlines()
        output: list[str] = []
        failure: list[tuple[int, str]] = []
        ok = self._console.run_lines(
            path,
            lines,
            lambda text: output.extend(text.splitlines()),
            failed=lambda number, line: failure.append((number, line)),
        )
        self._interrupted()
        if not ok:
            number, line = failure[0]
            raise ScriptError(path, number, line, output)
        return output

    def save(self, path: str | os.PathLike[str] | None = None) -> CommandResult:
        """Save the show to ``path`` (default: the facade's ``path``, then
        wherever it was last saved). Sets ``meta.modified`` and backs up the
        file it replaces. Never raises: a failure has ``ok=False``."""
        return self._session.save(_optional_path(path))

    # ----------------------------------------------------------- helpers

    def _settle(self) -> None:
        """Called after each command: :class:`OfflineShow` ticks here."""

    def _interrupted(self) -> None:
        """Raise the Ctrl+C the console held back while a line ran (on the
        main thread: not in another thread whose line ended meanwhile)."""
        if threading.current_thread() is threading.main_thread() and self._console.interrupted:
            self._console.interrupted = False
            raise KeyboardInterrupt


class OfflineShow(_Facade):
    """A show on a clock you drive: a session, its console and an engine.

    Use it to build shows from console lines or command dicts, and to render
    frames deterministically (tests, previews, offline rendering). It
    starts no thread and opens no socket; it writes only the files it is
    asked to (``save``, a script's ``save`` line). Every command takes
    effect at the current engine time (see the module docs).

    ``path`` is where :meth:`save` and a ``save`` line write when they are
    given no path. ``library`` is the profile library ``fixture add`` uses
    (the built-in profiles by default). ``ids`` makes the ids of new
    entities: random by default, :class:`~busk.session.ids.CounterIds` for
    reproducible shows.

    Use it from one thread at a time: each call ticks its engine.

    Raises :class:`~busk.persistence.show_file.ShowLoadError` if ``show``
    does not validate, and :class:`~busk.compiler.compile.UnsupportedFeature`
    if it uses a feature busk cannot run yet.
    """

    def __init__(
        self,
        show: Show,
        *,
        path: str | os.PathLike[str] | None = None,
        library: ProfileLibrary | None = None,
        ids: IdFactory | None = None,
    ) -> None:
        show, compiled = _checked(show)
        self._clock = FakeClock()
        self._engine = Engine(compiled, self._clock)
        engine = self._engine
        self._session = Session(
            show,
            engine.bus,
            compiled=compiled,
            path=_optional_path(path),
            ids=ids,
            engine_state=lambda: engine.snapshot,
        )
        self._console = Console(
            self._session,
            library if library is not None else ProfileLibrary(),
            status=lambda: status_line(self.snapshot),
            settle=self._settle,
        )
        self._time = 0.0
        self._read: OutputSnapshot | None = None  # the last tick's output, once read
        self._effect_read: EffectSnapshot | None = None  # its effects, once read
        self._tick(0.0)

    @property
    def snapshot(self) -> EngineSnapshot:
        """The engine's published state: playbacks, masters, page, tempo."""
        snapshot = self._engine.snapshot
        assert snapshot is not None  # the constructor's tick published one
        return snapshot

    @property
    def output(self) -> OutputSnapshot:
        """The last tick's output, per fixture element: intensity, colour,
        pan, tilt and zoom, and what drives them (see
        :class:`~busk.engine.snapshot.FixtureOutput`). Made when first read
        after a tick, then the same object until the next one."""
        output = self._read
        if output is None or output.seq != self._engine.stats.ticks:
            output = read_output(self._engine.capture())
            self._read = output
        return output

    @property
    def effects(self) -> EffectSnapshot:
        """The effect instances the last tick ran, the playbacks' and the
        programmer's, each with its presence, size, rate, phase and next
        cycle (see :class:`~busk.engine.snapshot.EffectStatus`). Made when
        first read after a tick, then the same object until the next one."""
        effects = self._effect_read
        if effects is None or effects.seq != self._engine.stats.ticks:
            effects = read_effects(self._engine.capture_effects())
            self._effect_read = effects
        return effects

    @property
    def time(self) -> float:
        """The engine time of the last tick, in seconds (0.0 at first)."""
        return self._time

    def tick(self, t: float) -> DmxFrame:
        """Move engine time to ``t`` seconds and run one tick; return its
        frame. Fades, chases and effects advance by the time that passed.
        Raises :class:`ValueError` if ``t`` is before :attr:`time`."""
        if t < self._time:
            raise ValueError(f"time cannot go back: {t} is before {self._time}")
        return self._tick(t)

    def _tick(self, t: float) -> DmxFrame:
        self._clock.sleep_until(t)
        self._engine.tick(t)
        self._time = t
        latest = self._engine.latest
        assert latest is not None
        return _dmx_frame(latest)

    def _settle(self) -> None:
        """Let the engine apply what was just submitted, without moving time."""
        self._tick(self._time)


class _LocalRun:
    """An engine and its output scheduler as threads of this process: the
    engine side of a :class:`LiveShow`, and of ``busk run --threads``
    (``ThreadsBackend``, phase-8-plan step 10).

    ``say`` gets the route lines and the output's news, ``warn`` what
    failed; both default to the ``busk.output`` logger (INFO, WARNING). The
    CLI passes its printers, and follows the routes' status with its own
    reporter, not :meth:`poll`, since it prints every status change on
    stderr.
    """

    def __init__(
        self,
        engine: Engine,
        show: Show,
        compiled: CompiledShow,
        clock: Clock,
        *,
        output: bool = True,
        printer: ConsoleOutput | None = None,
        say: Report = _output_log.info,
        warn: Report = _output_log.warning,
    ) -> None:
        """Open the routes of ``show`` (unless ``output`` is false) and
        report their lines. ``printer`` prints the frames too (``busk run
        --console``). Starts no thread."""
        self.engine = engine
        self.scheduler: OutputScheduler | None = None
        self._say = say
        self._warn = warn
        if output:
            sequences = Sequences()
            artnet = ArtNetNetwork()
            routes, notices = build_routes(
                show["output"], compiled.universes, sequences, artnet=artnet
            )
            for route in routes:
                say(f"{route.label}: {route.description}")
            for notice in notices:
                self._notice(notice.text, failed=notice.failed)
            self.scheduler = OutputScheduler(
                engine,
                routes,
                clock,
                printer,
                layout=compiled.layout,
                sequences=sequences,
                artnet=artnet,
                notices=notices,
            )
        self._reported: dict[str, tuple[bool, str]] = {}  # route id → (ok, detail)
        self._stops = (threading.Event(), threading.Event())  # engine, output
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        """Start the engine thread, then the output thread."""
        engine_stop, output_stop = self._stops
        self._threads = [
            threading.Thread(
                target=self.engine.run, args=(engine_stop,), name="busk-engine", daemon=True
            )
        ]
        if self.scheduler is not None:
            self._threads.append(
                threading.Thread(
                    target=self.scheduler.run,
                    args=(output_stop,),
                    name="busk-output",
                    daemon=True,
                )
            )
        for thread in self._threads:
            thread.start()

    def poll(self) -> None:
        """Report what the output said since the last poll: its notices,
        and each route that started or stopped failing."""
        if self.scheduler is None:
            return
        notices = self.scheduler.notices
        while not notices.empty():
            notice = notices.get()
            self._notice(notice.text, failed=notice.failed)
        for route in self.scheduler.routes:
            status = route.driver.status()
            state = (status.ok, status.detail)
            if state == self._reported.get(route.id, (True, "")):
                continue
            self._reported[route.id] = state
            if status.ok:
                self._say(f"{route.label}: sending again")
            else:
                self._warn(f"{route.label}: send failed: {status.detail}")

    def stop(self) -> None:
        """Stop the engine, then the output: its last pass sends the last
        frame, then terminates the streams (sACN's Stream_Terminated)."""
        engine_stop, output_stop = self._stops
        engine_stop.set()
        if self._threads:
            self._threads[0].join()
        output_stop.set()
        for thread in self._threads[1:]:
            thread.join()

    def _notice(self, text: str, *, failed: bool) -> None:
        (self._warn if failed else self._say)(text)


class LiveShow(_Facade):
    """A show in real time inside your own process.

    :meth:`start` (or entering a ``with`` block) opens the show's output
    routes and starts the engine and output threads; with ``surfaces=True``
    it also opens the show's control surfaces (MIDI, OSC, the web remote)
    and follows the changes live edits make to them. :meth:`stop` (or
    leaving the block, whatever the exception) closes everything in
    ``busk run``'s order.

    **This is not** ``busk run``: there is no watchdog and no process
    isolation, so a crash or a stall of the host process stops the DMX
    output, and there is no autosave or crash recovery (save with
    :meth:`save`). Under heavy edits one process also overruns more ticks
    than ``busk run``'s three. For a show on stage, use ``busk run``: with
    ``--frontend MODULE:FUNCTION`` it hands your frontend its own
    ``LiveShow``.

    ``path``, ``library`` and the commands are as in :class:`OfflineShow`;
    commands sent before :meth:`start` apply at the engine's first tick.
    ``output=False`` opens no route (the frames are still made: read
    :attr:`frame`). ``state_dir`` is where the web remote's key is kept;
    without it the key is new on every run, and nothing is written.
    ``tune_interpreter=True`` lowers the interpreter's thread switch
    interval while the show runs, as ``busk run`` does, so the engine thread
    keeps its rate while edits compile; it is a process-wide setting, so it
    is off by default, and :meth:`stop` restores it.

    Any number of threads may command and read it at once (see
    :meth:`execute`): a frontend can send its performance lines from a
    thread of their own, so a ``go`` never waits for a ``save``.

    Raises :class:`~busk.persistence.show_file.ShowLoadError` if ``show``
    does not validate, and :class:`~busk.compiler.compile.UnsupportedFeature`
    if it uses a feature busk cannot run yet. Constructing opens nothing and
    starts no thread.
    """

    def __init__(
        self,
        show: Show,
        *,
        path: str | os.PathLike[str] | None = None,
        library: ProfileLibrary | None = None,
        output: bool = True,
        surfaces: bool = False,
        state_dir: str | os.PathLike[str] | None = None,
        tune_interpreter: bool = False,
    ) -> None:
        show, compiled = _checked(show)
        clock = MonotonicClock()
        engine = Engine(compiled, clock)
        session = Session(
            show,
            engine.bus,
            compiled=compiled,
            path=_optional_path(path),
            engine_state=lambda: engine.snapshot,
        )
        self._setup(
            Console(
                session,
                library if library is not None else ProfileLibrary(),
                status=self._status_line,
            ),
            LocalEngine(engine),
            clock,
            state_dir=_optional_path(state_dir),
            say=_surfaces_log.info,
            warn=_surfaces_log.warning,
        )
        self._engine: Engine | None = engine
        self._output = output
        self._open_surfaces = surfaces
        self._tune = tune_interpreter

    @classmethod
    def _attached(
        cls,
        show: Show,
        compiled: CompiledShow,
        link: EngineLink,
        clock: Clock,
        *,
        path: Path,
        library: ProfileLibrary,
        state_dir: Path,
        dirty: bool,
        stamp: Stamp,
        causes: bool,
        iface: str,
        status: Callable[[], str],
        about: Callable[[], Sequence[str]],
        poll: Callable[[], None],
        routes: Callable[[], tuple[RouteStatus, ...] | None],
        say: Report,
        warn: Report,
    ) -> Self:
        """The show of ``busk run`` (phase-8-plan §5.5's private seam, for
        :func:`~busk.process.console_host.run_console` only).

        The engine side is the CLI's: ``link`` is the
        :class:`~busk.engine.link.LocalEngine` of ``--threads`` or the
        console process's :class:`~busk.process.links.RemoteBus`, already
        made for ``compiled`` (with the ``--values`` base frame), running on
        ``clock``. ``show`` was loaded (and validated) and ``compiled`` by
        the CLI, so neither is done again. The session gets ``path``,
        ``dirty`` (a recovered show), ``stamp`` and ``causes`` (the event
        log); the console ``iface``, ``status`` and ``about``. ``routes``
        gives :attr:`routes`, as the CLI's output knows them. ``say`` and
        ``warn`` print the surface lines, the session's failures and the web
        key's.

        Such a show runs no engine and opens nothing by itself; it reads
        its frames, output and effects through ``link``. The CLI calls
        :meth:`_open` (the surfaces and feedback), then :meth:`start` (the
        feedback thread only). It polls with :meth:`_poll` between
        commands, or starts the monitor thread (:meth:`_start_monitor`) for
        the interactive prompt or a frontend; each poll calls ``poll``
        first (its status line and route reports). It waits for the engine
        itself, and stops the engine after :meth:`stop`.
        """
        session = Session(
            show,
            link.bus,
            compiled=compiled,
            path=path,
            dirty=dirty,
            engine_state=lambda: link.snapshot,
            stamp=stamp,
            causes=causes,
            report=warn,
        )
        live = cls.__new__(cls)
        live._setup(
            Console(session, library, iface=iface, status=status, about=about),
            link,
            clock,
            state_dir=state_dir,
            say=say,
            warn=warn,
        )
        live._on_poll = poll
        live._route_source = routes
        return live

    def _setup(
        self,
        console: Console,
        link: EngineLink,
        clock: Clock,
        *,
        state_dir: Path | None,
        say: Report,
        warn: Report,
    ) -> None:
        """The state both constructors share, for a show that has not
        started; :meth:`__init__` then gives it an engine of its own."""
        self._session = console.session
        self._console = console
        self._link = link
        self._clock = clock
        self._state_dir = state_dir
        self._say = say  # the surfaces' lines
        self._warn = warn  # their failures
        self._engine = None  # the engine this show runs itself (__init__'s)
        self._output = False
        self._open_surfaces = False
        self._tune = False
        self._on_poll: Callable[[], None] | None = None  # the first part of each poll
        self._route_source: Callable[[], tuple[RouteStatus, ...] | None] = self._local_routes
        self._routes: tuple[RouteStatus, ...] | None = None  # the last routes read
        self._phase: Literal["new", "running", "stopped"] = "new"
        self._run: _LocalRun | None = None
        self._surfaces: SurfaceManager | None = None
        self._feedback: FeedbackWorker | None = None
        self._stops = (threading.Event(), threading.Event())  # feedback, monitor
        self._threads: list[threading.Thread] = []
        self._switch_interval: float | None = None  # to restore, when tuned
        self._latest: tuple[Frame, DmxFrame] | None = None
        self._read: tuple[Capture, OutputSnapshot] | None = None  # the last output read
        self._effect_read: tuple[EffectCapture, EffectSnapshot] | None = None  # and effects

    # ----------------------------------------------------------- reading

    @property
    def snapshot(self) -> EngineSnapshot | None:
        """The engine's published state: playbacks, masters, page, tempo;
        ``None`` until the engine's first tick."""
        return self._link.snapshot

    @property
    def frame(self) -> DmxFrame | None:
        """The engine's newest frame; ``None`` until its first tick. ``busk
        run``'s show, whose engine runs in another process, asks for frames
        at the first read, which returns ``None``, as do the reads before
        the first frame comes."""
        self._link.watch(frames=True)
        latest = self._link.frame  # one read: published by reference assignment
        if latest is None:
            return None
        cached = self._latest
        if cached is None or cached[0] is not latest:
            cached = (latest, _dmx_frame(latest))
            self._latest = cached  # one assignment: other threads see the pair whole
        return cached[1]

    @property
    def output(self) -> OutputSnapshot | None:
        """The engine's newest output, per fixture element: intensity,
        colour, pan, tilt and zoom, and what drives them (see
        :class:`~busk.engine.snapshot.FixtureOutput`). Poll it, 10 to 20
        times a second for a display.

        The engine captures its output only once someone reads it: the
        first read turns that on for good and returns ``None``, as do the
        reads before the engine's next tick. ``busk run``'s show has it too,
        from its engine process, which then sends its captures to the
        console process: a capture of a show the console has replaced since
        is skipped."""
        self._link.watch(output=True)
        captured = self._link.output  # one read: published by reference assignment
        if captured is None:
            return None
        cached = self._read
        if cached is None or cached[0] is not captured:
            cached = (captured, read_output(captured))
            self._read = cached  # one assignment: other threads see the pair whole
        return cached[1]

    @property
    def effects(self) -> EffectSnapshot | None:
        """The effect instances the engine's newest tick ran, the playbacks'
        and the programmer's, each with its presence, size, rate, phase and
        next cycle (see :class:`~busk.engine.snapshot.EffectStatus`). Poll it
        with :attr:`output`.

        As with :attr:`output`, the engine captures its effects only once
        someone reads them: the first read turns that on for good and
        returns ``None``, as do the reads before the engine's next tick.
        ``busk run``'s show has them too: its engine process reads them and
        sends them to the console process."""
        self._link.watch(effects=True)
        captured = self._link.effects  # one read: published by reference assignment
        if captured is None or isinstance(captured, EffectSnapshot):
            return captured  # from another process, read there
        cached = self._effect_read
        if cached is None or cached[0] is not captured:
            cached = (captured, read_effects(captured))
            self._effect_read = cached  # one assignment: other threads see the pair whole
        return cached[1]

    @property
    def routes(self) -> tuple[RouteStatus, ...] | None:
        """The show's output routes, in show order, each with what it does:
        open (``"ok"``), ``"failed"`` and why, ``"disabled"`` or
        ``"ignored"``, and its packet and error counts (see
        :class:`~busk.output.driver.RouteStatus`). Poll it with the others;
        while nothing changed, the same object comes back.

        ``None`` before :meth:`start` and with ``output=False``: nothing
        runs the output. After :meth:`stop`, the routes as they ended. ``busk
        run``'s show has them from the process that runs its output."""
        routes = self._route_source()
        if routes is not None and routes == self._routes:
            return self._routes
        self._routes = routes
        return routes

    def _local_routes(self) -> tuple[RouteStatus, ...] | None:
        """:attr:`routes` of a show that runs its own engine and output."""
        run = self._run
        if run is None or run.scheduler is None:
            return None
        return run.scheduler.route_status()

    @property
    def surfaces(self) -> tuple[SurfaceStatus, ...] | None:
        """The show's control surfaces, in show order, each with what it
        does: open (``"ok"``; a web remote with its ``urls``), ``"failed"``
        and why, or ``"ignored"`` (see :class:`~busk.io.surfaces.SurfaceStatus`).
        It follows live edits within :data:`MONITOR_S` s, and MIDI devices
        plugged in and out at the next read of the port names (every 2 s).
        Poll it with the others; while nothing changed, the same object comes
        back.

        ``None`` before :meth:`start` and with ``surfaces=False``: no surface
        is open. After :meth:`stop`, the surfaces as they ended. ``busk
        run``'s show has them too: its console process opens them."""
        manager = self._surfaces
        return None if manager is None else manager.status()

    # ---------------------------------------------------- start and stop

    def start(self) -> None:
        """Open the routes (and the surfaces), start the threads, and return
        once the engine has published its first snapshot (after
        :data:`SETTLE_S` s without one, a warning is logged and it returns
        anyway). Routes and surfaces that fail to open are logged and
        retried, as in ``busk run``. Raises :class:`RuntimeError` if the
        show was started before: a ``LiveShow`` runs once."""
        if self._phase != "new":
            raise RuntimeError("this LiveShow has been started already; make a new one")
        self._phase = "running"
        session = self._session
        try:
            if self._engine is not None:
                run = _LocalRun(
                    self._engine,
                    session.show,
                    session.compiled,
                    self._clock,
                    output=self._output,
                )
                self._run = run
                self._on_poll = run.poll
            if self._open_surfaces:
                self._open()
            if self._tune:
                self._switch_interval = sys.getswitchinterval()
                sys.setswitchinterval(SWITCH_INTERVAL)
            if self._run is not None:
                self._run.start()
            if self._feedback is not None:
                feedback = threading.Thread(
                    target=self._feedback.run,
                    args=(self._stops[0],),
                    name="busk-feedback",
                    daemon=True,
                )
                self._threads.append(feedback)
                feedback.start()
            if self._run is not None:
                self._start_monitor()
        except BaseException:
            self.stop()
            raise
        if self._run is not None and not self._link.sync(SETTLE_S):
            _output_log.warning("engine: not answering; going on anyway")

    def stop(self) -> None:
        """Close the surfaces, then stop feedback, the session's worker, the
        engine and the output, in that order (as ``busk run`` does): no
        command arrives after the engine stopped, and the output's last pass
        sends the last frame, then terminates the streams. Restores the
        switch interval. Does nothing if the show is not running."""
        if self._phase != "running":
            return
        self._phase = "stopped"
        feedback_stop, monitor_stop = self._stops
        monitor_stop.set()
        for thread in self._threads:
            if thread.name == "busk-monitor":
                thread.join()
        if self._surfaces is not None:
            self._surfaces.close()
        feedback_stop.set()
        for thread in self._threads:
            thread.join()
        self._session.stop()
        if self._run is not None:
            self._run.stop()
            self._run.poll()  # what the output said last
        if self._switch_interval is not None:
            sys.setswitchinterval(self._switch_interval)
            self._switch_interval = None

    def __enter__(self) -> Self:
        """:meth:`start`, and the show itself."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """:meth:`stop`, whatever ended the block."""
        self.stop()

    # ----------------------------------------------------------- helpers

    def _open(self) -> None:
        """Build the input side (bindings, the web link, the surfaces) and
        feedback, and open the surfaces and their feedback ports."""
        link, session, clock = self._link, self._session, self._clock
        compiled = session.compiled

        def page() -> str | None:
            snapshot = link.snapshot
            return None if snapshot is None or snapshot.page is None else snapshot.page.id

        resolver = BindingResolver(
            session.show,
            compiled,
            InputSink(session),
            live=lambda: link.compiled,
            page=page,
            clock=clock.now,
            report=self._warn,
        )
        web = WebLink(
            snapshot=lambda: link.snapshot,
            compiled=lambda: link.compiled,
            submit=session.submit,
            clock=clock.now,
            key=self._web_key(),
        )
        surfaces = SurfaceManager(resolver.handle, web, say=self._say, warn=self._warn)
        surfaces.reconcile(compiled)
        self._surfaces = surfaces  # opened: :attr:`surfaces` lists them all at once
        self._feedback = FeedbackWorker(
            lambda: link.compiled,
            lambda: link.snapshot,
            resolver.lastInput,
            clock=clock.now,
            senders=surfaces.senders,
            report=self._warn,
            say=self._say,
            warn=self._warn,
        )
        self._feedback.open()

    def _status_line(self) -> str:
        """What ``status`` prints for a show that runs its own engine:
        ``busk run --threads``'s answer while it runs (``busk run``'s show
        has the CLI's, with the engine process's state)."""
        if self._phase != "running":
            return "no engine is running"
        snapshot = self._link.snapshot
        return "the engine has not ticked yet" if snapshot is None else status_line(snapshot)

    def _web_key(self) -> str:
        """The web remote's key: the state directory's, else a new one."""
        if self._state_dir is not None:
            try:
                return web_key(self._state_dir)
            except OSError as exc:  # a read-only state directory must not stop the show
                self._warn(f"web key not saved: {exc}; it changes on the next run")
        return secrets.token_urlsafe(6)

    def _poll(self) -> None:
        """One look around (the monitor's, every :data:`MONITOR_S` s): the
        output's reports (attached: the CLI's ``poll``), then the surfaces
        live edits opened, changed or removed, and MIDI devices plugged in
        and out."""
        if self._on_poll is not None:
            self._on_poll()
        if self._surfaces is not None:
            self._surfaces.reconcile(self._link.compiled)
            self._surfaces.poll(time.monotonic())

    def _start_monitor(self) -> None:
        """Run :meth:`_poll` on the ``busk-monitor`` thread until :meth:`stop`."""
        stop = self._stops[1]

        def monitor() -> None:
            while not stop.wait(MONITOR_S):
                self._poll()

        thread = threading.Thread(target=monitor, name="busk-monitor", daemon=True)
        self._threads.append(thread)
        thread.start()
