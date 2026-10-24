"""The TUI's own view of the engine: frozen view models, the events the
bridge sends, and :class:`BridgeLike`, what the UI calls.

Nothing here imports busk or Textual. The bridge (:mod:`busk_tui.bridge`)
turns busk's objects into these, keyed by the numbers and names the operator
types, never by ids, and the pages and widgets see only these. Tests swap in
a fake bridge that implements :class:`BridgeLike` (``tests/tui/tui_fakes.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

type Origin = Literal["typed", "ui", "internal"]
"""Who sent a line: typed at the prompt (echoed ``busk>``), run by a control
of the UI (echoed ``ui>``), or sent by the TUI itself (not echoed)."""

type EngineState = Literal["starting", "running", "stalled", "restarting", "failed", "stopped"]
"""What the engine does (busk's ``EngineHealth.state``)."""

type RouteState = Literal["ok", "failed", "disabled", "ignored"]


class ShowLoadFailed(Exception):
    """The show file of ``--standalone`` does not load; ``messages`` say why,
    one line each."""

    def __init__(self, messages: list[str]) -> None:
        super().__init__("\n".join(messages))
        self.messages = messages


# ----------------------------------------------------------------- answers


@dataclass(frozen=True, slots=True)
class Completion:
    """What may come where the word being typed starts (busk's ``Expected``).

    ``words`` replace ``line[start:]`` on Tab; ``values`` describe anything
    else (``a fixture number``); ``runnable``: the line before ``start`` is a
    whole command; ``error``: the mistake that stops it."""

    words: tuple[str, ...] = ()
    values: tuple[str, ...] = ()
    runnable: bool = False
    error: str | None = None
    start: int = 0


@dataclass(frozen=True, slots=True)
class Busy:
    """The ordered worker's line running now, since ``since`` (monotonic s)."""

    line: str
    since: float


# ------------------------------------------------------------- view models


@dataclass(frozen=True, slots=True)
class PageView:
    number: int
    name: str


@dataclass(frozen=True, slots=True)
class SpeedView:
    """A speed master's tempo. Its beat count comes in :class:`Beat` events."""

    name: str
    bpm: float
    multiplier: float
    level: float


@dataclass(frozen=True, slots=True)
class MasterLevel:
    name: str
    kind: str  # grand, group, size, speed, fadeTime
    level: float


@dataclass(frozen=True, slots=True)
class LiveState:
    """The engine's published state (busk's ``EngineSnapshot``)."""

    seq: int
    gm: float
    blackout: bool
    outputEnabled: bool
    page: PageView | None
    fadeTime: float | None  # the fade-time master's override, seconds
    masters: tuple[MasterLevel, ...]
    speed: tuple[SpeedView, ...]


@dataclass(frozen=True, slots=True)
class ProgrammerModel:
    """The programmer (busk's ``ProgrammerStatus``)."""

    version: int
    selection: tuple[tuple[int, int], ...]  # (fixture number, element) pairs, in order
    blind: bool
    highlight: bool
    fadeTime: float
    fixtures: int  # the fixtures that hold a value


@dataclass(frozen=True, slots=True)
class RouteView:
    """One output route: from the show, with its status once the output runs.

    ``state`` is ``None`` while nothing runs the output (``--no-output``)."""

    protocol: str  # as the operator reads it: sACN, ArtNet, DMX-USB
    universe: int  # the show universe it sends
    enabled: bool
    state: RouteState | None
    detail: str
    packets: int


@dataclass(frozen=True, slots=True)
class UniverseView:
    number: int
    name: str


@dataclass(frozen=True, slots=True)
class MasterView:
    name: str
    kind: str


@dataclass(frozen=True, slots=True)
class ShowModel:
    """The parts of the show document the pages use."""

    title: str
    universes: tuple[UniverseView, ...]
    masters: tuple[MasterView, ...]
    pages: tuple[PageView, ...]


@dataclass(frozen=True, slots=True)
class SessionState:
    """Undo depth and unsaved edits, read from the text of ``info``: a
    temporary parser until GAP-03 gives them typed (question Q2)."""

    undo: int
    redo: int
    dirty: bool


# ------------------------------------------------------------------ events


@dataclass(frozen=True, slots=True)
class EngineStarting:
    pass


@dataclass(frozen=True, slots=True)
class EngineRunning:
    title: str
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EngineFailed:
    """``--standalone`` only: the show could not be built or started."""

    message: str


@dataclass(frozen=True, slots=True)
class EngineStopped:
    pass


@dataclass(frozen=True, slots=True)
class CommandDone:
    ticket: int
    line: str
    origin: Origin
    ok: bool
    lines: tuple[str, ...]  # the reply's text, line by line
    seconds: float
    quit: bool


@dataclass(frozen=True, slots=True)
class LiveChanged:
    state: LiveState


@dataclass(frozen=True, slots=True)
class Beat:
    """The engine time of the newest frame, and each speed master's beat
    count then, in the order of ``LiveState.speed``."""

    time: float
    beats: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class ShowChanged:
    show: ShowModel


@dataclass(frozen=True, slots=True)
class ProgrammerChanged:
    programmer: ProgrammerModel


@dataclass(frozen=True, slots=True)
class RoutesChanged:
    routes: tuple[RouteView, ...]


@dataclass(frozen=True, slots=True)
class HealthChanged:
    state: EngineState
    late: bool  # the engine's overruns grew over the last second or more


@dataclass(frozen=True, slots=True)
class SessionChanged:
    session: SessionState


@dataclass(frozen=True, slots=True)
class EngineNews:
    """A record of the ``busk`` loggers, shown as it is."""

    level: Literal["info", "warning"]
    text: str


type BridgeEvent = (
    EngineStarting
    | EngineRunning
    | EngineFailed
    | EngineStopped
    | CommandDone
    | LiveChanged
    | Beat
    | ShowChanged
    | ProgrammerChanged
    | RoutesChanged
    | HealthChanged
    | SessionChanged
    | EngineNews
)

STATE_EVENTS: tuple[type, ...] = (
    LiveChanged,
    Beat,
    ShowChanged,
    ProgrammerChanged,
    RoutesChanged,
    HealthChanged,
    SessionChanged,
)
"""The events that carry a whole state: of each kind, only the newest of a
batch matters."""


def newest_only(events: list[BridgeEvent]) -> list[BridgeEvent]:
    """``events`` in order, with only the last of each kind of state event."""
    last = {type(event): index for index, event in enumerate(events)}
    return [
        event
        for index, event in enumerate(events)
        if not isinstance(event, STATE_EVENTS) or last[type(event)] == index
    ]


# ---------------------------------------------------------------- protocol


class BridgeLike(Protocol):
    """What the UI calls (the real :class:`~busk_tui.bridge.Bridge`, and the
    tests' fake). Every member is safe on the UI thread and returns at once."""

    def start(self) -> None: ...

    def stop(self, timeout: float = 5.0) -> None: ...

    def send(
        self, line: str, origin: Origin, key: str | None = None, performance: bool = False
    ) -> int: ...

    def confirmation(self, line: str) -> str | None: ...

    def expected(self, line: str) -> Completion: ...

    def watch(self, output: bool, effects: bool) -> None: ...

    def drain(self) -> list[BridgeEvent]: ...

    @property
    def busy(self) -> Busy | None: ...

    @property
    def help_lines(self) -> tuple[str, ...]: ...
