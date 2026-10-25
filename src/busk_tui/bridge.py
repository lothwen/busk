"""The engine boundary: the only module of the TUI that imports busk.

A :class:`Bridge` holds one :class:`busk.LiveShow`: the one ``busk run``
hands its frontend (:meth:`Bridge.attached`), or, with ``--standalone``, one
it builds and runs in this process (:meth:`Bridge.standalone`). It turns
busk's objects into the view models of :mod:`busk_tui.model` and gives the
UI what :class:`~busk_tui.model.BridgeLike` promises, from four threads of its
own (plan §4.1):

* the **ordered** worker runs typed lines, edits and programmer lines, one at
  a time, in order (and, with ``--standalone``, builds and starts the show
  first);
* the **controls** worker runs the performance lines of the TUI's own
  controls, in order; they never wait for an ordered line (busk's GAP-12);
* the **reader** looks at the show's published state 20 times a second (the
  output and the running effects, while a page shows them, 10 times) and
  sends an event only when something changed;
* a **log handler** on the ``busk`` logger turns its records into
  :class:`~busk_tui.model.EngineNews`.

The UI thread never waits: :meth:`Bridge.send` queues a line and returns its
ticket, and :meth:`Bridge.drain` returns the events that have come since.
Only names of ``busk.__all__`` are used, and no reply text is parsed, except
``info``'s undo and unsaved-edits lines (:func:`session_from_info`), until
GAP-03 gives them typed.
"""

from __future__ import annotations

import itertools
import logging
import os
import re
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, SimpleQueue
from typing import Any, Final, Literal

from busk import (
    EffectSnapshot,
    EffectTemplateInfo,
    EngineHealth,
    EngineSnapshot,
    FixtureProfile,
    LiveShow,
    OutputSnapshot,
    ProfileLibrary,
    ProgrammerStatus,
    RouteStatus,
    Show,
    ShowLoadError,
    load_show,
)
from busk_tui import attributes, commands
from busk_tui.model import (
    Beat,
    BridgeEvent,
    Busy,
    CommandDone,
    Completion,
    Components,
    CueInfo,
    CueListInfo,
    EffectInfo,
    EffectsChanged,
    EffectsModel,
    EffectView,
    ElementOutput,
    EngineFailed,
    EngineNews,
    EngineRunning,
    EngineStarting,
    EngineState,
    EngineStopped,
    FixtureInfo,
    GroupInfo,
    HealthChanged,
    HeldValue,
    LiveChanged,
    LiveState,
    MasterLevel,
    MasterView,
    Origin,
    OutputChanged,
    OutputModel,
    PageInfo,
    PageView,
    PlaybackInfo,
    PlaybackView,
    PresetInfo,
    ProfileInfo,
    ProgrammerChanged,
    ProgrammerModel,
    Rgb,
    RoutesChanged,
    RouteView,
    SessionChanged,
    SessionState,
    ShowChanged,
    ShowLoadFailed,
    ShowModel,
    SpeedView,
    StoredValue,
    Summary,
    Targets,
    TemplateInfo,
    UniverseView,
    Value,
    newest_only,
)

POLL_S: Final = 0.05
"""How often the reader looks at the show (20 Hz)."""

LATE_S: Final = 1.0
"""The engine is late while its overruns grow over this long, or longer."""

OUTPUT_S: Final = 0.1
"""How often the reader looks at the output while it is watched (10 Hz, the
spec's least for live output): it is the costliest read, for busk, which
builds it on request, and for the TUI, which converts and draws it."""

EFFECTS_S: Final = 0.1
"""How often the reader looks at the running effects while they are watched
(10 Hz, the spec's least for effect waveforms): each read changes while an
effect runs, and F5 draws every row that runs again."""

_debug = logging.getLogger("busk_tui")

_PROTOCOLS: Final = {"sacn": "sACN", "artnet": "ArtNet", "dmxUsb": "DMX-USB"}


# ------------------------------------------------------------------ workers


@dataclass(slots=True)
class _Job:
    ticket: int
    line: str
    origin: Origin
    key: str | None
    then: Callable[[bool, str], None] | None = None  # the bridge's own follow-up, no event


class _Lane:
    """One worker's queue: first in, first out, except that a keyed line
    replaces an unsent one with the same key (a fader's newest move)."""

    def __init__(self) -> None:
        self._jobs: deque[_Job] = deque()
        self._ready = threading.Condition()
        self._closed = False

    def put(self, job: _Job) -> None:
        with self._ready:
            if self._closed:
                return
            if job.key is not None:
                for queued in self._jobs:
                    if queued.key == job.key:
                        self._jobs.remove(queued)  # the newest goes after the lines sent before it
                        break
            self._jobs.append(job)
            self._ready.notify()

    def get(self) -> _Job | None:
        """The next job; ``None`` once the lane is closed."""
        with self._ready:
            while not self._jobs and not self._closed:
                self._ready.wait()
            return None if self._closed else self._jobs.popleft()

    def close(self) -> None:
        """Drop the queued jobs and end :meth:`get`."""
        with self._ready:
            self._closed = True
            self._jobs.clear()
            self._ready.notify_all()


@dataclass(frozen=True, slots=True)
class _Standalone:
    """What ``--standalone`` builds its show from."""

    show: Show
    path: Path
    library: tuple[Path, ...]
    output: bool
    surfaces: bool
    state_dir: Path | None
    warnings: tuple[str, ...]


@dataclass(slots=True)
class _Seen:
    """What the reader saw last, so it sends only what changed."""

    doc: Show | None = None
    templates: tuple[EffectTemplateInfo, ...] | None = None
    show: ShowModel | None = None
    masters: dict[str, MasterView] = field(default_factory=dict)  # master id → its view
    seq: int | None = None
    live: LiveState | None = None
    programmer: int | None = None
    programmer_model: ProgrammerModel | None = None
    effects: tuple[EffectView, ...] | None = None  # None: send the next read, whatever it is
    effects_at: float = 0.0  # when the effects were last read (monotonic)
    output_seq: int | None = None
    output: tuple[ElementOutput, ...] | None = None  # None: send the next read, whatever it is
    output_at: float = 0.0  # when the output was last read (monotonic)
    routes: tuple[RouteStatus, ...] | Literal["unread"] | None = "unread"
    frame: int | None = None
    health: tuple[EngineState, bool] | None = None
    late_mark: tuple[float, int] | None = None  # (monotonic time, overruns) of the last look


class _News(logging.Handler):
    """The ``busk`` loggers' records, as events."""

    def __init__(self, put: Callable[[BridgeEvent], None]) -> None:
        super().__init__(logging.INFO)
        self._put = put

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = record.getMessage()
        except Exception:
            self.handleError(record)
            return
        self._put(EngineNews("warning" if record.levelno >= logging.WARNING else "info", text))


# ------------------------------------------------------------------ bridge


class Bridge:
    """The TUI's side of one show (see the module docs). Make one with
    :meth:`attached` or :meth:`standalone`."""

    def __init__(self, show: LiveShow | None, standalone: _Standalone | None) -> None:
        self._show = show
        self._standalone = standalone
        self._events: SimpleQueue[BridgeEvent] = SimpleQueue()
        self._ordered = _Lane()
        self._controls = _Lane()
        self._tickets = itertools.count(1)
        self._lock = threading.Lock()  # the show's arrival against stop()
        self._ready = threading.Event()  # the show runs: lines may go to it
        self._halt = threading.Event()
        self._poke = threading.Event()  # look at the show now, not at the next poll
        self._threads: list[threading.Thread] = []
        self._busy: Busy | None = None
        self._help: tuple[str, ...] = ()
        self._session: SessionState | None = None
        self._watching = (False, False)
        self._seen = _Seen()
        self._news = _News(self._events.put)
        self._log_level: int | None = None
        self._started = False
        self._stopped = False

    @classmethod
    def attached(cls, show: object) -> Bridge:
        """The bridge of ``busk run``'s show: it runs already, and the run,
        not the bridge, stops it. (``object``: the TUI's other modules do not
        import busk.)"""
        if not isinstance(show, LiveShow):
            raise TypeError(f"busk run should hand its frontend a busk.LiveShow, not {show!r}")
        return cls(show, None)

    @classmethod
    def standalone(
        cls,
        path: str | os.PathLike[str],
        *,
        library: Sequence[str | os.PathLike[str]] = (),
        output: bool = True,
        surfaces: bool = True,
        state_dir: str | os.PathLike[str] | None = None,
    ) -> Bridge:
        """The bridge of a show it runs itself, from the file at ``path``.
        Loads the file now and raises :class:`~busk_tui.model.ShowLoadFailed`
        if it does not load; :meth:`start` builds and starts the show."""
        path = Path(path)
        try:
            show, warnings = load_show(path)
        except ShowLoadError as exc:
            raise ShowLoadFailed(
                [f"{path}: {issue.severity} {issue}" for issue in exc.issues]
            ) from None
        except OSError as exc:
            raise ShowLoadFailed([f"{path}: cannot read: {exc.strerror or exc}"]) from None
        spec = _Standalone(
            show=show,
            path=path,
            library=tuple(Path(directory) for directory in library),
            output=output,
            surfaces=surfaces,
            state_dir=None if state_dir is None else Path(state_dir),
            warnings=tuple(f"{issue.severity} {issue}" for issue in warnings),
        )
        return cls(None, spec)

    # --------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Start the threads; never blocks. The ordered worker runs ``help``
        first (and with ``--standalone`` builds and starts the show before)."""
        if self._started:
            return
        self._started = True
        self._events.put(EngineStarting())
        logger = logging.getLogger("busk")
        self._log_level = logger.level
        if logger.getEffectiveLevel() > logging.INFO:
            logger.setLevel(logging.INFO)
        logger.addHandler(self._news)
        for name, target in (
            ("busk-tui-ordered", self._ordered_main),
            ("busk-tui-controls", self._controls_main),
            ("busk-tui-reader", self._reader_main),
        ):
            thread = threading.Thread(target=target, name=name, daemon=True)
            self._threads.append(thread)
            thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the threads: each worker finishes the line it runs, and the
        queued lines are dropped. A standalone show is stopped then (its
        routes send their last frame and terminate their streams); ``busk
        run``'s never is. Gives up after ``timeout`` s, with a warning.
        Harmless twice."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            show = self._show
        deadline = time.monotonic() + timeout
        self._halt.set()
        self._ordered.close()
        self._controls.close()
        self._poke.set()
        for thread in self._threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        logger = logging.getLogger("busk")
        logger.removeHandler(self._news)
        if self._log_level is not None:
            logger.setLevel(self._log_level)
        ordered_done = not self._threads or not self._threads[0].is_alive()
        if self._standalone is not None and show is not None and ordered_done:
            # (A worker still starting the show stops it itself once it has started.)
            stopper = threading.Thread(target=show.stop, name="busk-tui-stop", daemon=True)
            stopper.start()
            stopper.join(max(0.0, deadline - time.monotonic()))
            if stopper.is_alive():
                _debug.warning("the show did not stop within %.1f s", timeout)
                print(
                    f"busk-tui: the show did not stop within {timeout:g} s; leaving anyway",
                    file=sys.stderr,
                )
        self._events.put(EngineStopped())

    # ------------------------------------------------------------ the UI's

    def send(
        self, line: str, origin: Origin, key: str | None = None, performance: bool = False
    ) -> int:
        """Queue ``line``; return its ticket, which its
        :class:`~busk_tui.model.CommandDone` carries. A performance line from
        the UI's controls goes to the controls worker; a typed line always
        goes to the ordered one. With a ``key``, it replaces a queued, unsent
        line with the same key (which then has no ``CommandDone``)."""
        ticket = next(self._tickets)
        lane = self._controls if performance and origin != "typed" else self._ordered
        lane.put(_Job(ticket, line, origin, key))
        return ticket

    def confirmation(self, line: str) -> str | None:
        """The engine's question before ``line`` (busk's GAP-10), or ``None``."""
        show = self._show
        if show is None or not self._ready.is_set():
            return None
        try:
            return show.confirmation(line)
        except Exception:
            _debug.exception("confirmation(%r) raised", line)
            return None

    def expected(self, line: str) -> Completion:
        """What may come at the end of ``line`` (busk's GAP-20)."""
        show = self._show
        if show is None or not self._ready.is_set():
            return Completion(start=len(line))
        try:
            answer = show.expected(line)
        except Exception:
            _debug.exception("expected(%r) raised", line)
            return Completion(start=len(line))
        return Completion(
            words=answer.words,
            values=answer.values,
            runnable=answer.runnable,
            error=answer.error,
            start=answer.start,
        )

    def watch(self, output: bool, effects: bool) -> None:
        """Which of the show's output and effects the reader polls (each
        costs the reading process, so only while a page shows it). Once
        watched again, the next read is sent even if it has not changed."""
        if effects and not self._watching[1]:
            self._seen.effects = None
            self._seen.effects_at = 0.0
        if output and not self._watching[0]:
            self._seen.output_seq = self._seen.output = None
            self._seen.output_at = 0.0
        self._watching = (output, effects)

    def drain(self) -> list[BridgeEvent]:
        """The events since the last call, in order, with only the newest of
        each kind of state event."""
        events: list[BridgeEvent] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except Empty:
                return newest_only(events)

    @property
    def busy(self) -> Busy | None:
        """The ordered worker's line running now, and since when."""
        return self._busy

    @property
    def help_lines(self) -> tuple[str, ...]:
        """The text of ``help``, once the ordered worker has run it."""
        return self._help

    # -------------------------------------------------------------- workers

    def _ordered_main(self) -> None:
        if self._standalone is not None and not self._start_standalone(self._standalone):
            return
        show = self._show
        assert show is not None
        self._ready.set()
        self._run(_Job(0, commands.help_().text, "internal", None, then=self._take_help))
        self._refresh_session()
        warnings = (
            *(self._standalone.warnings if self._standalone is not None else ()),
            *(f"{issue.severity} {issue}" for issue in show.warnings),
        )
        self._events.put(EngineRunning(show.show["meta"]["title"], tuple(warnings)))
        self._poke.set()
        while (job := self._ordered.get()) is not None:
            if job.then is not None:  # the bridge's own: not shown as busy
                self._run(job)
                continue
            self._busy = Busy(job.line, time.monotonic())
            try:
                ok = self._run(job)
            finally:
                self._busy = None
            self._poke.set()  # the document may have changed: look now
            if ok:
                self._refresh_session()

    def _controls_main(self) -> None:
        while not self._ready.wait(0.1):
            if self._halt.is_set():
                return
        while (job := self._controls.get()) is not None:
            self._run(job)

    def _start_standalone(self, spec: _Standalone) -> bool:
        """Build and start the show of ``--standalone``; ``False`` after
        sending :class:`~busk_tui.model.EngineFailed`."""
        try:
            library = ProfileLibrary(spec.library)
            for problem in library.problems:
                self._events.put(EngineNews("warning", f"library: skipped {problem}"))
            show = LiveShow(
                spec.show,
                path=spec.path,
                library=library,
                output=spec.output,
                surfaces=spec.surfaces,
                state_dir=spec.state_dir,
                tune_interpreter=True,
            )
            with self._lock:
                if self._stopped:
                    return False
                self._show = show
            show.start()
        except Exception as exc:
            _debug.exception("the show did not start")
            self._events.put(EngineFailed(_failure(exc)))
            return False
        if self._halt.is_set():  # stop() came while it started
            show.stop()
            return False
        return True

    def _run(self, job: _Job) -> bool:
        """Run one line; send its ``CommandDone``, or hand the reply to the
        job's own follow-up. Return whether it succeeded."""
        show = self._show
        assert show is not None
        started = time.monotonic()
        try:
            reply = show.execute(job.line)
            ok, text, quit = reply.ok, reply.text, reply.quit
        except Exception as exc:
            _debug.exception("execute(%r) raised", job.line)
            ok, text, quit = False, f"internal error: {type(exc).__name__}: {exc}", False
        if job.then is not None:
            job.then(ok, text)
        else:
            self._events.put(
                CommandDone(
                    ticket=job.ticket,
                    line=job.line,
                    origin=job.origin,
                    ok=ok,
                    lines=tuple(text.splitlines()),
                    seconds=time.monotonic() - started,
                    quit=quit,
                )
            )
        return ok

    def _take_help(self, ok: bool, text: str) -> None:
        if ok:
            self._help = tuple(text.splitlines())

    def _refresh_session(self) -> None:
        """Read the undo depth and unsaved edits again (``info``, on the
        ordered worker: a query, which waits for the line another thread
        runs)."""
        self._run(_Job(0, "info", "internal", None, then=self._take_info))

    def _take_info(self, ok: bool, text: str) -> None:
        session = session_from_info(text) if ok else None
        if session is not None and session != self._session:
            self._session = session
            self._events.put(SessionChanged(session))

    # --------------------------------------------------------------- reader

    def _reader_main(self) -> None:
        while not self._halt.is_set():
            self._poke.wait(POLL_S)
            self._poke.clear()
            if self._halt.is_set() or not self._ready.is_set():
                continue
            try:
                self._look()
            except Exception:  # a bad read must not end the reader
                _debug.exception("reading the show failed")

    def _look(self) -> None:
        """One look at the show: an event for each part that changed."""
        show = self._show
        assert show is not None
        seen = self._seen
        put = self._events.put
        doc = show.show  # one read: replaced, never changed, by an edit
        templates = show.effect_templates  # the same tuple until one changes
        # Each part is marked seen only once converted: a conversion that
        # raises is tried again at the next look.
        new_doc = doc is not seen.doc
        if new_doc or templates is not seen.templates:
            model = show_model(doc, templates)
            masters: dict[str, MasterView] = {
                master["id"]: view
                for master, view in zip(doc["masters"], model.masters, strict=True)
            }
            seen.doc, seen.templates, seen.masters = doc, templates, masters
            if model != seen.show:
                seen.show = model
                put(ShowChanged(model))
        snapshot = show.snapshot
        if snapshot is not None and (snapshot.seq != seen.seq or new_doc):
            live = live_state(snapshot, seen.masters)
            seen.seq = snapshot.seq
            if live != seen.live:
                seen.live = live
                put(LiveChanged(live))
        programmer = show.programmer
        new_programmer = programmer.version != seen.programmer
        if new_programmer or new_doc:  # a new document may rename an effect's template
            changed = programmer_model(programmer, doc)
            seen.programmer = programmer.version
            if changed != seen.programmer_model:
                seen.programmer_model = changed
                put(ProgrammerChanged(changed))
        if new_doc or new_programmer:  # perhaps from a surface: undo and unsaved edits again
            self._ordered.put(_Job(0, "info", "internal", "session", then=self._take_info))
        routes = show.routes
        if routes is not seen.routes or new_doc:
            views = route_views(doc, routes)
            seen.routes = routes
            put(RoutesChanged(views))
        if self._watching[1] and time.monotonic() - seen.effects_at >= EFFECTS_S:
            seen.effects_at = time.monotonic()
            effects = show.effects
            if effects is not None:
                running = effects_model(effects)
                if running.effects != seen.effects:
                    seen.effects = running.effects
                    put(EffectsChanged(running))
        if self._watching[0] and time.monotonic() - seen.output_at >= OUTPUT_S:
            seen.output_at = time.monotonic()
            output = show.output
            if output is not None and output.seq != seen.output_seq:
                out = output_model(output)
                seen.output_seq = output.seq
                if out.fixtures != seen.output:
                    seen.output = out.fixtures
                    put(OutputChanged(out))
        frame = show.frame
        if frame is not None and frame.seq != seen.frame:
            seen.frame = frame.seq
            if snapshot is not None and snapshot.speed:
                beats = tuple(speed.beats(frame.time) for speed in snapshot.speed)
                put(Beat(frame.time, beats))
        self._look_at_health(show.health)

    def _look_at_health(self, health: EngineHealth | None) -> None:
        seen = self._seen
        state: EngineState = "starting" if health is None else health.state
        late = seen.health[1] if seen.health is not None else False
        if health is not None:
            now = time.monotonic()
            if seen.late_mark is None:
                seen.late_mark = (now, health.overruns)
            elif now - seen.late_mark[0] >= LATE_S:
                late = health.overruns > seen.late_mark[1]
                seen.late_mark = (now, health.overruns)
        if (state, late) != seen.health:
            seen.health = (state, late)
            self._events.put(HealthChanged(state, late))


# --------------------------------------------------------------- conversion


@dataclass(frozen=True, slots=True)
class _Names:
    """What the document's ids stand for, as the operator names them."""

    templates: dict[str, str]  # template id → name
    groups: dict[str, GroupInfo]  # group id → the group
    fixtures: dict[str, int]  # fixture id → number
    presets: dict[str, tuple[str, Rgb | None]]  # preset id → name, and the colour it gives
    speeds: dict[str, str]  # speed master id → name; empty with one speed master

    @classmethod
    def of(cls, doc: Show) -> _Names:
        speeds = [master for master in doc["masters"] if master["kind"] == "speed"]
        return cls(
            templates={template["id"]: template["name"] for template in doc["effects"]},
            groups={
                group["id"]: GroupInfo(group["number"], group["name"]) for group in doc["groups"]
            },
            fixtures={fixture["id"]: fixture["number"] for fixture in doc["fixtures"]},
            presets={
                preset["id"]: (preset["name"], _preset_color(preset["values"]))
                for preset in doc["presets"]
            },
            speeds={master["id"]: master["name"] for master in speeds} if len(speeds) > 1 else {},
        )


_newest_names: tuple[Show, _Names] | None = None


def _names(doc: Show) -> _Names:
    """``_Names.of(doc)``, kept for the newest document: the programmer's
    conversion needs it too, at each change of the programmer."""
    global _newest_names
    cached = _newest_names
    if cached is not None and cached[0] is doc:
        return cached[1]
    names = _Names.of(doc)
    _newest_names = (doc, names)  # one assignment: another thread sees the pair whole
    return names


def show_model(doc: Show, templates: Sequence[EffectTemplateInfo] = ()) -> ShowModel:
    """The document as the pages use it; ``templates``: what ``effect add``
    takes (``LiveShow.effect_templates``)."""
    names = _names(doc)
    groups = names.groups
    playbacks = {playback["id"]: playback["number"] for playback in doc["playbacks"]}
    lists = {cue_list["id"]: cue_list["number"] for cue_list in doc["cueLists"]}
    modes = {
        (profile["id"], mode["id"]): len(mode["elements"])
        for profile in doc["profiles"]
        for mode in profile["modes"]
    }
    profiles = {profile["id"]: profile["name"] for profile in doc["profiles"]}
    return ShowModel(
        title=doc["meta"]["title"],
        universes=tuple(UniverseView(u["number"], u["name"]) for u in doc["universes"]),
        masters=tuple(master_view(master, groups) for master in doc["masters"]),
        pages=tuple(
            PageInfo(
                page["number"],
                page["name"],
                tuple(None if slot is None else playbacks.get(slot) for slot in page["slots"]),
            )
            for page in doc["pages"]
        ),
        playbacks=tuple(
            sorted(
                (
                    PlaybackInfo(
                        number=playback["number"],
                        name=playback["name"],
                        cueList=lists.get(playback["cueListId"], 0),
                        uiColor=_hex_color(playback.get("uiColor")),
                    )
                    for playback in doc["playbacks"]
                ),
                key=lambda info: info.number,
            )
        ),
        cueLists=tuple(
            CueListInfo(
                number=cue_list["number"],
                name=cue_list["name"],
                mode=cue_list["mode"],
                chase=(None if "chase" not in cue_list else _chase_text(cue_list["chase"], names)),
                cues=tuple(cue_info(cue, names) for cue in cue_list["cues"]),
                crossfade=cue_list["chase"]["crossfade"] if "chase" in cue_list else 0.0,
                tracking=cue_list["tracking"],
            )
            for cue_list in doc["cueLists"]
        ),
        groups=tuple(groups.values()),
        presets=tuple(
            PresetInfo(
                preset["pool"],
                preset["number"],
                preset["name"],
                _preset_color(preset["values"]),
                _preset_summary(preset["values"]),
            )
            for preset in doc["presets"]
        ),
        fixtures=tuple(
            FixtureInfo(
                fixture["number"],
                modes.get((fixture["profileId"], fixture["modeId"]), 1),
                fixture["name"],
                profiles.get(fixture["profileId"], ""),
            )
            for fixture in doc["fixtures"]
        ),
        profiles=tuple(profile_info(profile) for profile in doc["profiles"]),
        templates=tuple(
            TemplateInfo(
                name=template.name,
                source=template.source,
                summary=template.summary,
                size=template.size,
                low=template.low,
                high=template.high,
                phase=template.phase,
            )
            for template in templates
        ),
    )


RANGED: Final = ("pan", "tilt", "zoom", "strobeRate")
"""The attributes whose range is the profile's (the others are 0..1)."""

DEFAULT_RANGES: Final = {"pan": (-270.0, 270.0), "tilt": (-135.0, 135.0), "zoom": (5.0, 60.0),
                         "strobeRate": (0.0, 25.0)}  # fmt: skip
"""A range the profile does not give (the spec's pan and tilt)."""


def profile_info(profile: FixtureProfile) -> ProfileInfo:
    """What a profile's modes take, as ``set`` names it, read from its
    channels: their attributes (``control`` is never set), the attribute a
    function range takes as its parameter (``strobeRate`` of a shutter's
    strobe), ``intensity`` where a mode dims its colour virtually, and
    ``color.w`` where a colour channel drives a white emitter. The ranges
    are the profile's ``physical`` ones (pan and tilt centred on 0), else
    those its channels' capabilities span, else :data:`DEFAULT_RANGES`."""
    attributes: set[str] = set()
    spans: dict[str, list[float]] = {}
    for mode in profile["modes"]:
        colored = False
        for channel in mode["channels"]:
            attribute = channel["attribute"]
            if attribute == "control":
                continue
            attributes.add(attribute)
            if attribute == "color":
                colored = True
                if channel.get("component") == "white":
                    attributes.add("color.w")
            for capability in channel["capabilities"]:
                if capability["kind"] == "range" and attribute in RANGED:
                    spans.setdefault(attribute, []).extend(capability["value"])
                elif capability["kind"] == "function" and "param" in capability:
                    param = capability["param"]
                    attributes.add(param["attribute"])
                    spans.setdefault(param["attribute"], []).extend(param["value"])
        if colored and mode["intensityStrategy"] == "virtual":
            attributes.add("intensity")
    physical = profile["physical"]
    given: dict[str, tuple[float, float]] = {}
    if "panRange" in physical:
        given["pan"] = (-physical["panRange"] / 2, physical["panRange"] / 2)
    if "tiltRange" in physical:
        given["tilt"] = (-physical["tiltRange"] / 2, physical["tiltRange"] / 2)
    if "zoomRange" in physical:
        given["zoom"] = (float(physical["zoomRange"][0]), float(physical["zoomRange"][1]))
    if "maxStrobeHz" in physical:
        given["strobeRate"] = (0.0, physical["maxStrobeHz"])
    ranges: list[tuple[str, float, float]] = []
    for attribute in RANGED:
        if attribute not in attributes:
            continue
        span = spans.get(attribute)
        low, high = given.get(
            attribute, (min(span), max(span)) if span else DEFAULT_RANGES[attribute]
        )
        ranges.append((attribute, low, high))
    return ProfileInfo(profile["name"], frozenset(attributes), tuple(ranges))


def master_view(master: Mapping[str, Any], groups: dict[str, GroupInfo]) -> MasterView:
    """A master of the document; ``groups``: the document's, by id."""
    group = groups.get(master["groupId"]) if master["kind"] == "group" else None
    steps = tuple(master["multiplierSteps"]) if master["kind"] == "speed" else ()
    return MasterView(master["name"], master["kind"], group, steps)


def effect_info(effect: Mapping[str, Any], names: _Names) -> EffectInfo:
    """A cue's or the programmer's effect instance."""
    phase = effect["phase"]
    return EffectInfo(
        id=effect["id"],
        template=names.templates.get(effect["templateId"], effect["templateId"]),
        targets=_targets(effect["targets"], names),
        rate=_rate_text(effect["rate"], names),
        direction=effect["direction"],
        size=float(effect["size"]),
        low=_value(effect["low"]) if "low" in effect else None,
        high=_value(effect["high"]) if "high" in effect else None,
        phase=(float(phase["start"]), float(phase["end"])),
        groups=effect["groups"],
        blocks=effect["blocks"],
        wings=effect["wings"],
    )


def cue_info(cue: Mapping[str, Any], names: _Names) -> CueInfo:
    """A cue with its timing, trigger, value entries and effects as stored."""
    timing, trigger = cue["timing"], cue["trigger"]
    return CueInfo(
        number=cue["number"],
        name=cue["name"],
        effects=tuple(effect_info(effect, names) for effect in cue["effects"]),
        fadeIn=float(timing["fadeIn"]),
        fadeOut=float(timing["fadeOut"]),
        delayIn=float(timing["delayIn"]),
        delayOut=float(timing["delayOut"]),
        curve=_curve_text(timing["curve"]),
        families=tuple(
            (family, float(own["fade"]), float(own["delay"]))
            for family, own in timing.get("perFamily", {}).items()
        ),
        trigger=trigger["kind"],
        delay=float(trigger.get("delay", 0.0)),
        values=tuple(stored_value(entry, names) for entry in cue["entries"]),
    )


def stored_value(entry: Mapping[str, Any], names: _Names) -> StoredValue:
    """A value entry as stored: a literal (with its colour), a preset by name
    (with the one colour it gives), a spread's two ends, or per target."""
    attribute, source = entry["attribute"], entry["value"]
    targets = _targets(entry["targets"], names)
    match source["kind"]:
        case "literal":
            value = _value(source["value"])
            color = attributes.rgb(value) if isinstance(value, tuple) else None
            return StoredValue(attribute, targets, "literal", value=value, color=color)
        case "preset":
            name, color = names.presets.get(source["presetId"], (source["presetId"], None))
            return StoredValue(attribute, targets, "preset", preset=name, color=color)
        case "spread":
            return StoredValue(
                attribute,
                targets,
                "spread",
                value=_value(source["from"]),
                to=_value(source["to"]),
            )
        case kind:
            return StoredValue(attribute, targets, kind)


def live_state(snapshot: EngineSnapshot, masters: dict[str, MasterView]) -> LiveState:
    """The snapshot as the UI shows it, masters by name (``masters``: the
    document's, by id; a master the document no longer has is left out)."""
    levels = tuple(
        MasterLevel(masters[master_id].name, masters[master_id].kind, level)
        for master_id, level in snapshot.masterLevels
        if master_id in masters
    )
    page = snapshot.page
    return LiveState(
        seq=snapshot.seq,
        gm=snapshot.grandMaster,
        blackout=snapshot.blackout,
        outputEnabled=snapshot.outputEnabled,
        page=None if page is None else PageView(page.number, page.name),
        fadeTime=snapshot.fadeTime,
        masters=levels,
        speed=tuple(
            SpeedView(speed.name, speed.bpm, speed.multiplier, speed.level)
            for speed in snapshot.speed
        ),
        playbacks=tuple(
            PlaybackView(
                number=playback.number,
                name=playback.name,
                state=playback.state,
                level=playback.faderLevel,
                flash=playback.flash,
                fader=playback.fader,
                chase=playback.chase,
                cue=playback.cue,
                cueName=playback.cueName,
                next=playback.next,
                cueCount=playback.cueCount,
                progress=playback.progress,
                color=playback.color,
            )
            for playback in snapshot.playbacks
        ),
    )


def programmer_model(programmer: ProgrammerStatus, doc: Show) -> ProgrammerModel:
    names = _names(doc)
    return ProgrammerModel(
        version=programmer.version,
        selection=programmer.selection,
        blind=programmer.blind,
        highlight=programmer.highlight,
        fadeTime=programmer.fadeTime,
        fixtures=len({value.number for value in programmer.values}),
        effects=tuple(effect_info(effect, names) for effect in programmer.effects),
        stopped=programmer.stopped,
        values=tuple(
            HeldValue(
                number=value.number,
                element=value.element,
                attribute=value.attribute,
                value=_value(value.value),
                preset=None if value.preset is None else value.preset[2],
            )
            for value in programmer.values
        ),
    )


def output_model(snapshot: OutputSnapshot) -> OutputModel:
    return OutputModel(
        seq=snapshot.seq,
        fixtures=tuple(
            ElementOutput(
                number=out.number,
                element=out.element,
                intensity=out.intensity,
                color=out.color,
                pan=out.pan,
                tilt=out.tilt,
                zoom=out.zoom,
            )
            for out in snapshot.fixtures
        ),
    )


def effects_model(snapshot: EffectSnapshot) -> EffectsModel:
    return EffectsModel(
        seq=snapshot.seq,
        effects=tuple(
            EffectView(
                playback=effect.playback,
                cue=effect.cue,
                id=effect.id,
                presence=effect.presence,
                size=effect.size,
                hz=effect.hz,
                phase=effect.phase,
                wave=effect.wave,
                colors=effect.colors,
            )
            for effect in snapshot.effects
        ),
    )


def route_views(doc: Show, status: tuple[RouteStatus, ...] | None) -> tuple[RouteView, ...]:
    """The document's routes in show order, each with its status by id
    (``status`` is ``None`` while nothing runs the output)."""
    by_id = {route.id: route for route in status or ()}
    numbers = {universe["id"]: universe["number"] for universe in doc["universes"]}
    views: list[RouteView] = []
    for route in doc["output"]["routes"]:
        found = by_id.get(route["id"])
        views.append(
            RouteView(
                protocol=_PROTOCOLS.get(route["protocol"], route["protocol"]),
                universe=numbers.get(route["universeId"], 0),
                enabled=route["enabled"],
                state=None if found is None else found.state,
                detail="" if found is None else found.detail,
                packets=0 if found is None else found.packets,
            )
        )
    return tuple(views)


_UNDO: Final = re.compile(r"undo: (\d+) steps?, redo: (\d+) steps?")


def session_from_info(text: str) -> SessionState | None:
    """The undo and redo depth and the unsaved-edits flag from the text of
    ``info``; ``None`` if it does not say them as busk 0.1 does.

    **Temporary** (question Q2 of the plan): busk's message text may change
    in any release. Remove this once GAP-03 gives them typed."""
    undo: tuple[int, int] | None = None
    dirty: bool | None = None
    for line in text.splitlines():
        if (match := _UNDO.fullmatch(line)) is not None:
            undo = (int(match[1]), int(match[2]))
        elif line.startswith("file: "):
            if line.endswith(", unsaved edits"):
                dirty = True
            elif line.endswith(", saved"):
                dirty = False
    if undo is None or dirty is None:
        return None
    return SessionState(undo=undo[0], redo=undo[1], dirty=dirty)


def _chase_text(chase: Mapping[str, Any], names: _Names) -> str:
    """A chase's rate and direction as ``cuelist N chase`` takes them."""
    return f"{_rate_text(chase['rate'], names)} {chase['direction']}"


def _rate_text(rate: Mapping[str, Any], names: _Names) -> str:
    """A rate as ``cuelist N chase`` and ``effect add`` take it: ``hz 0.25``,
    ``bpm x 1``; the speed master by name only when the show has more than
    one."""
    if rate["kind"] == "hz":
        return f"hz {rate['value']:g}"
    master = names.speeds.get(rate["masterId"])
    return "bpm" + ("" if master is None else f' "{master}"') + f" x {rate['multiplier']:g}"


def _curve_text(curve: Any) -> str:
    """A fade curve as ``cue L/C time`` takes it: ``easeInOut``, ``bezier
    0.25 0.1 0.25 1``."""
    if isinstance(curve, Mapping):
        return "bezier " + " ".join(f"{float(point):g}" for point in curve["bezier"])
    return str(curve)


def _targets(spec: Mapping[str, Any], names: _Names) -> Targets:
    """A target spec: a group by number and name, or fixture elements by
    number (counted from 1), leaving out a fixture the show no longer has."""
    if spec["kind"] == "group":
        return Targets(group=names.groups.get(spec["groupId"], GroupInfo(0, spec["groupId"])))
    return Targets(
        elements=tuple(
            (names.fixtures[ref["fixtureId"]], ref["element"] + 1)
            for ref in spec["refs"]
            if ref["fixtureId"] in names.fixtures
        )
    )


def _hex_color(text: str | None) -> Rgb | None:
    """A ``uiColor`` of the form ``#rrggbb``; ``None`` for anything else."""
    if text is None or re.fullmatch(r"#[0-9a-fA-F]{6}", text) is None:
        return None
    return (int(text[1:3], 16) / 255, int(text[3:5], 16) / 255, int(text[5:7], 16) / 255)


_COMPONENTS: Final = ("r", "g", "b", "w", "a", "uv")


def _value(value: Any) -> Value:
    """A stored value as the UI has it: a colour's components in busk's
    order, a discrete value's slot, a number."""
    if isinstance(value, Mapping):
        if "slot" in value:
            return str(value["slot"])
        components: Components = tuple(
            (key, float(value[key])) for key in _COMPONENTS if key in value
        )
        return components
    return float(value)


def _preset_summary(values: Sequence[Mapping[str, Any]]) -> tuple[tuple[str, Summary], ...]:
    """Each attribute but colour that a preset stores, in the order stored,
    with its value where every value of it is the same, else ``None``."""
    found: dict[str, set[float | str]] = {}
    for stored in values:
        if stored["attribute"] == "color":
            continue
        value = _value(stored["value"])
        if isinstance(value, float | str):
            found.setdefault(stored["attribute"], set()).add(value)
    return tuple(
        (attribute, next(iter(seen)) if len(seen) == 1 else None)
        for attribute, seen in found.items()
    )


def _preset_color(values: Sequence[Mapping[str, Any]]) -> Rgb | None:
    """The colour a preset gives when every one of its colour values is the
    same, with its white added; ``None`` otherwise."""
    found: set[Rgb] = set()
    for value in values:
        color = value["value"]
        if value["attribute"] != "color" or not isinstance(color, dict) or "r" not in color:
            continue
        white = float(color.get("w", 0.0))
        red, green, blue = (min(1.0, float(color[key]) + white) for key in ("r", "g", "b"))
        found.add((red, green, blue))
    return found.pop() if len(found) == 1 else None


def _failure(exc: Exception) -> str:
    if isinstance(exc, ShowLoadError):
        return "\n".join(f"{issue.severity} {issue}" for issue in exc.issues)
    return f"{type(exc).__name__}: {exc}"
