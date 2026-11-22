"""A fake bridge for the UI tests, a way to drive the app headless, and a
stub show for the real bridge.

:class:`FakeBridge` implements ``BridgeLike``. It records the lines sent and
answers each with a ``CommandDone`` at once (``replies`` by line, ok and
empty otherwise), and runs a script's lines the same way, with a
``ScriptLine`` each and a ``ScriptDone`` (:func:`script_events`). With
``show``, a real :class:`busk.OfflineShow`, its help, ``expected`` answers
and questions are the real ones; without it, the help is ``HELP`` and
nothing is asked. It reads profile and show files as the real bridge does.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import shutil
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from textual.pilot import Pilot

import busk
from busk_tui import config
from busk_tui.bridge import plot_read, profile_read, show_read
from busk_tui.model import (
    BridgeEvent,
    Busy,
    CommandDone,
    Completion,
    LiveState,
    MasterLevel,
    MasterView,
    Origin,
    PageView,
    PlaybackView,
    PlotRead,
    ProfileRead,
    ProgrammerModel,
    ScriptDone,
    ScriptLine,
    ShowModel,
    ShowRead,
    SpeedView,
    newest_only,
)
from busk_tui.shell import BuskApp
from busk_tui.widgets.rows import RowTable, fit

HELP = (
    "    sel <targets> | sel + <targets> | sel - <targets> | sel none",
    "        <targets> = <t>[, <t>…]",
    "    set <attribute> <value> | set <attribute> by <change>",
    "    set <attribute> spread <from> [to] <to> [center|edges]",
    "    clear | blind on|off | highlight on|off | fade <seconds> | programmer",
    "    undo | redo | save [PATH] | list <kind> | library | info",
    "    status | help | source FILE | quit",
)


@dataclass
class Reply:
    ok: bool = True
    text: str = ""
    quit: bool = False


@dataclass
class Sent:
    line: str
    origin: Origin
    key: str | None
    performance: bool
    ticket: int


@dataclass
class FakeBridge:
    show: Any = None  # a busk.OfflineShow for real help, expected and confirmation
    replies: dict[str, Reply] = field(default_factory=dict)
    auto_reply: bool = True
    sent: list[Sent] = field(default_factory=list)
    events: list[BridgeEvent] = field(default_factory=list)
    started: bool = False
    stopped: bool = False
    watching: tuple[bool, bool] = (False, False)
    watching_dmx: bool = False
    watching_inputs: bool = False
    tracking: int | None = None  # the cue list whose tracked states the UI asked for
    busy_line: Busy | None = None
    scripts: list[tuple[int, Path]] = field(default_factory=list)  # (ticket, path) run
    _tickets: Any = field(default_factory=lambda: itertools.count(1))

    def start(self) -> None:
        self.started = True

    def stop(self, timeout: float = 5.0) -> None:
        self.stopped = True

    def send(
        self, line: str, origin: Origin, key: str | None = None, performance: bool = False
    ) -> int:
        ticket = next(self._tickets)
        self.sent.append(Sent(line, origin, key, performance, ticket))
        if self.auto_reply:
            reply = self.replies.get(line, Reply())
            self.events.append(
                CommandDone(
                    ticket=ticket,
                    line=line,
                    origin=origin,
                    ok=reply.ok,
                    lines=tuple(reply.text.splitlines()),
                    seconds=0.0,
                    quit=reply.quit,
                )
            )
        return ticket

    def run_script(self, path: Path) -> int:
        ticket = next(self._tickets)
        self.scripts.append((ticket, path))
        if self.auto_reply:
            self.events += script_events(ticket, path, self.replies)
        return ticket

    def confirmation(self, line: str) -> str | None:
        return None if self.show is None else self.show.confirmation(line)

    def expected(self, line: str) -> Completion:
        if self.show is None:
            return Completion(start=len(line))
        answer = self.show.expected(line)
        return Completion(answer.words, answer.values, answer.runnable, answer.error, answer.start)

    def watch(self, output: bool, effects: bool, dmx: bool = False, inputs: bool = False) -> None:
        self.watching = (output, effects)
        self.watching_dmx = dmx
        self.watching_inputs = inputs

    def track(self, cue_list: int | None) -> None:
        self.tracking = cue_list

    def drain(self) -> list[BridgeEvent]:
        events, self.events = self.events, []
        return newest_only(events)

    @property
    def busy(self) -> Busy | None:
        return self.busy_line

    @property
    def help_lines(self) -> tuple[str, ...]:
        if self.show is None:
            return HELP
        return tuple(self.show.execute("help").text.splitlines())

    def read_profile(self, path: Path) -> ProfileRead:
        return profile_read(path)  # busk's own reading: the files are real

    def read_show(self, path: Path) -> ShowRead:
        return show_read(path)

    def read_plot(
        self,
        path: Path,
        audience: str | None = None,
        origin: tuple[float, float, float] | None = None,
    ) -> PlotRead:
        if self.show is None:
            return PlotRead(path, problem="the show has not started yet")
        return plot_read(self.show, path, audience, origin)  # busk's own check, of a real file

    def lines(self) -> list[str]:
        return [sent.line for sent in self.sent]


def script_events(
    ticket: int, path: Path, replies: dict[str, Reply] | None = None
) -> list[ScriptLine | ScriptDone]:
    """What the bridge sends as it runs the script at ``path``: a
    ``ScriptLine`` per line (``replies`` by line, ok and empty otherwise;
    blank lines and comments ok and empty), up to the first refused or
    ``quit`` one, and the ``ScriptDone``. It leaves an undo step if a line
    that is not blank or a comment ran, and busk took it."""
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    events: list[ScriptLine | ScriptDone] = []
    reply = Reply()
    for number, line in enumerate(lines, start=1):
        reply = (replies or {}).get(line, Reply())
        events.append(
            ScriptLine(ticket, number, len(lines), line, reply.ok, tuple(reply.text.splitlines()))
        )
        if not reply.ok or reply.quit:
            break
    stepped = any(event.ok and event.line and not event.line.startswith("#") for event in events)
    quit = reply.ok and reply.quit
    return [*events, ScriptDone(ticket, path, reply.ok, len(events), len(lines), stepped, quit)]


def live_state(**changes: Any) -> LiveState:
    """A live state with a page, a speed master and every master kind."""
    state: dict[str, Any] = {
        "seq": 1,
        "gm": 1.0,
        "blackout": False,
        "outputEnabled": True,
        "page": PageView(1, "Main"),
        "fadeTime": None,
        "masters": (MasterLevel("Grand Master", "grand", 1.0),),
        "speed": (SpeedView("Speed 1", 120.0, 1.0, 0.5),),
        "playbacks": (),
    }
    state.update(changes)
    return LiveState(**state)


def playback(number: int, name: str, **changes: Any) -> PlaybackView:
    """An idle playback with a one-cue list, its fader a master."""
    view: dict[str, Any] = {
        "number": number,
        "name": name,
        "state": "idle",
        "level": 0.0,
        "flash": False,
        "fader": "master",
        "chase": False,
        "cue": None,
        "cueName": None,
        "next": "1",
        "cueCount": 1,
        "progress": None,
        "color": None,
    }
    view.update(changes)
    return PlaybackView(**view)


def show_model(**changes: Any) -> ShowModel:
    """A show with a grand master and nothing else."""
    show: dict[str, Any] = {
        "title": "Club Night",
        "universes": (),
        "masters": (MasterView("Grand Master", "grand", None, ()),),
        "pages": (),
        "playbacks": (),
        "cueLists": (),
        "groups": (),
        "presets": (),
        "fixtures": (),
    }
    show.update(changes)
    return ShowModel(**show)


def programmer(**changes: Any) -> ProgrammerModel:
    state: dict[str, Any] = {
        "version": 1,
        "selection": (),
        "blind": False,
        "highlight": False,
        "fadeTime": 0.0,
        "fixtures": 0,
        "effects": (),
        "stopped": frozenset(),
    }
    state.update(changes)
    return ProgrammerModel(**state)


def make_app(bridge: FakeBridge | None = None, **settings: Any) -> BuskApp:
    return BuskApp(bridge or FakeBridge(), config.Settings(**settings))


def drive(
    app: BuskApp,
    body: Callable[[Pilot[int]], Awaitable[None]],
    size: tuple[int, int] = (150, 48),
) -> None:
    """Run ``app`` headless at ``size`` and ``body`` with its pilot."""

    async def main() -> None:
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await body(pilot)

    asyncio.run(main())


async def settle(pilot: Pilot[int], app: BuskApp) -> None:
    """Let the app take what its bridge sent, and redraw."""
    await pilot.pause()
    app.drain()
    await pilot.pause()


# ------------------------------------------------------------- tables


def column(table: RowTable, name: str) -> list[str]:
    """The text of one column of a table, row by row."""
    return [cells[name].plain for cells in table.rows]


async def click_cell(pilot: Pilot[int], table: RowTable, row: int, name: str) -> None:
    """Click row ``row`` of ``table``, in its column ``name``."""
    x = 0
    for shown, width in fit(table.columns(), table.size.width):
        if shown.name == name:
            break
        x += width + 1
    else:
        raise AssertionError(f"no column {name!r} shown")
    await pilot.click(table, offset=(x, row + 1))


# ------------------------------------------------------------ a stub show

STUB_WAIT_S = 5.0


def stub_snapshot(seq: int, gm: float = 1.0) -> busk.EngineSnapshot:
    return busk.EngineSnapshot(
        seq=seq, time=seq / 100, grandMaster=gm, blackout=False, playbacks=()
    )


def stub_programmer(version: int) -> busk.ProgrammerStatus:
    return busk.ProgrammerStatus(
        version=version,
        selection=((101, 1),),
        blind=False,
        highlight=False,
        fadeTime=0.0,
        values=(),
        effects=(),
        stopped=frozenset(),
    )


def stub_health(state: str = "running", overruns: int = 0) -> busk.EngineHealth:
    return busk.EngineHealth(state=state, ticks=100, overruns=overruns, lastTickAge=0.01)  # type: ignore[arg-type]


def stub_session(
    version: int = 1, dirty: bool = True, path: str | None = "/tmp/t.show"
) -> busk.SessionStatus:
    return busk.SessionStatus(
        showVersion=version,
        programmerVersion=1,
        dirty=dirty,
        path=path,
        undoSteps=2,
        redoSteps=1,
        nextUndo="set intensity 50%",
        nextRedo="clear",
    )


@dataclass
class Stub:
    """What the bridge reads of a ``LiveShow``, and an ``execute`` to steer."""

    show: Any = field(default_factory=lambda: busk.new_show("Stub"))
    snapshot: busk.EngineSnapshot | None = field(default_factory=lambda: stub_snapshot(1))
    programmer: busk.ProgrammerStatus = field(default_factory=lambda: stub_programmer(1))
    routes: Any = None
    surfaces: Any = None
    inputs: tuple[busk.SurfaceInput, ...] = ()
    health: busk.EngineHealth | None = field(default_factory=stub_health)
    session: busk.SessionStatus = field(default_factory=stub_session)
    frame: Any = None
    effects: Any = None
    output: Any = None
    effect_templates: tuple[busk.EffectTemplateInfo, ...] = ()
    tracked: dict[int, tuple[busk.TrackedCue, ...]] = field(default_factory=dict)  # by list
    tracking_reads: list[int] = field(default_factory=list)
    fixture_profiles: tuple[busk.FixtureProfileInfo, ...] = ()
    warnings: tuple[Any, ...] = ()
    gates: dict[str, threading.Event] = field(default_factory=dict)  # line → held until set
    raises: set[str] = field(default_factory=set)
    ran: list[str] = field(default_factory=list)
    threads: dict[str, str] = field(default_factory=dict)  # line → the thread that ran it
    stops: int = 0
    stop_hangs: bool = False
    released: threading.Event = field(default_factory=threading.Event)  # ends a hanging stop

    def execute(self, line: str) -> busk.Reply:
        self.threads[line] = threading.current_thread().name
        if line in self.gates:
            self.gates[line].wait(STUB_WAIT_S)
        if line in self.raises:
            raise RuntimeError("boom")
        self.ran.append(line)
        if line == "help":
            return busk.Reply("    help | quit")
        if line.startswith("bad"):
            return busk.Reply("error: no such thing", ok=False)
        return busk.Reply(f"did {line}")

    def confirmation(self, line: str) -> str | None:
        return "Really?" if line == "output off" else None

    def run_script(self, path: Path, *, each: Any = None) -> list[str]:
        """As busk's: each line through :meth:`execute` (blank lines and
        comments not), told to ``each``, up to the first refused one, with
        the session's undo steps one more once a line has run and been taken."""
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
        stepped = False
        for number, line in enumerate(lines, start=1):
            reply = busk.Reply("") if not line or line.startswith("#") else self.execute(line)
            if line and not line.startswith("#") and reply.ok and not stepped:
                stepped = True
                steps = self.session.undoSteps + 1
                self.session = replace(self.session, undoSteps=steps, nextUndo=f"source {path}")
            if each is not None:
                each(number, len(lines), line, reply)
            if not reply.ok:
                raise busk.ScriptError(path, number, line, [])
            if reply.quit:
                break
        return []

    def tracking(self, cue_list: int) -> tuple[busk.TrackedCue, ...] | None:
        self.tracking_reads.append(cue_list)
        return self.tracked.get(cue_list)

    def expected(self, line: str) -> Any:
        return busk.Expected(words=("sacn",), start=len(line))

    def stop(self) -> None:
        self.stops += 1
        if self.stop_hangs:
            self.released.wait(STUB_WAIT_S)


def crashed(show: Path, state_dir: Path, *, edits: bool = False) -> Path:
    """Leave in busk's ``state_dir`` what a ``busk run`` of the show file
    ``show`` leaves when it is killed: a ``session.json`` saying that the run
    did not end cleanly; with ``edits``, an autosave of the show newer than
    the file. Returns the ``session.json``."""
    from busk.persistence.autosave import SESSION_FILE
    from busk.persistence.paths import autosave_directory

    document, _ = busk.load_show(show)
    folder = autosave_directory(state_dir, document["meta"]["id"])
    folder.mkdir(parents=True)
    session: dict[str, object] = {"cleanExit": False, "showPath": str(show)}
    if edits:
        autosave = folder / "show-1.show"
        shutil.copy(show, autosave)
        os.utime(show, (1, 1))  # older than the autosave
        session["showAutosave"] = str(autosave)
    written = folder / SESSION_FILE
    written.write_text(json.dumps(session))
    return written
