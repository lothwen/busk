"""A fake bridge for the UI tests, a way to drive the app headless, and a
stub show for the real bridge.

:class:`FakeBridge` implements ``BridgeLike``. It records the lines sent and
answers each with a ``CommandDone`` at once (``replies`` by line, ok and
empty otherwise). With ``show``, a real :class:`busk.OfflineShow`, its help,
``expected`` answers and questions are the real ones; without it, the help is
``HELP`` and nothing is asked.
"""

from __future__ import annotations

import asyncio
import itertools
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from textual.pilot import Pilot

import busk
from busk_tui import config
from busk_tui.model import (
    BridgeEvent,
    Busy,
    CommandDone,
    Completion,
    LiveState,
    MasterLevel,
    Origin,
    PageView,
    ProgrammerModel,
    SpeedView,
    newest_only,
)
from busk_tui.shell import BuskApp

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
    busy_line: Busy | None = None
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

    def confirmation(self, line: str) -> str | None:
        return None if self.show is None else self.show.confirmation(line)

    def expected(self, line: str) -> Completion:
        if self.show is None:
            return Completion(start=len(line))
        answer = self.show.expected(line)
        return Completion(answer.words, answer.values, answer.runnable, answer.error, answer.start)

    def watch(self, output: bool, effects: bool) -> None:
        self.watching = (output, effects)

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

    def lines(self) -> list[str]:
        return [sent.line for sent in self.sent]


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
    }
    state.update(changes)
    return LiveState(**state)


def programmer(**changes: Any) -> ProgrammerModel:
    state: dict[str, Any] = {
        "version": 1,
        "selection": (),
        "blind": False,
        "highlight": False,
        "fadeTime": 0.0,
        "fixtures": 0,
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


INFO = """show: t (show-1)
file: /tmp/t.show, unsaved edits
0 universes, 0 fixtures, 0 groups, 0 presets, 0 cue lists, 0 playbacks, 0 bindings
undo: 2 steps, redo: 1 step
programmer: 0 selected, 0 values, blind off"""


@dataclass
class Stub:
    """What the bridge reads of a ``LiveShow``, and an ``execute`` to steer."""

    show: Any = field(default_factory=lambda: busk.new_show("Stub"))
    snapshot: busk.EngineSnapshot | None = field(default_factory=lambda: stub_snapshot(1))
    programmer: busk.ProgrammerStatus = field(default_factory=lambda: stub_programmer(1))
    routes: Any = None
    health: busk.EngineHealth | None = field(default_factory=stub_health)
    frame: Any = None
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
        if line == "info":
            return busk.Reply(INFO)
        if line.startswith("bad"):
            return busk.Reply("error: no such thing", ok=False)
        return busk.Reply(f"did {line}")

    def confirmation(self, line: str) -> str | None:
        return "Really?" if line == "output off" else None

    def expected(self, line: str) -> Any:
        return busk.Expected(words=("sacn",), start=len(line))

    def stop(self) -> None:
        self.stops += 1
        if self.stop_hangs:
            self.released.wait(STUB_WAIT_S)
