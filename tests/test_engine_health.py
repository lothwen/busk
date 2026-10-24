"""``LiveShow.health`` (GAP-21 of ``docs/dev/tui/engine-gaps.md``).

How the engine is doing: its state, its tick and overrun counts, and how
long ago it last ticked.

* **A show that runs its own engine** (a :class:`LiveShow`, and ``busk run
  --threads``'s show, which has no watchdog): the frames say it. Starting
  until the first, stalled after 1 s (``STALL_S``) without a new one, from
  ``start()`` while there is none; the counts are the engine's own. Real
  threads: an engine held mid-tick stalls and runs again, and slow ticks
  count as overruns.
* **``busk run``'s show** with processes: the state is the watchdog's word,
  as the root last said it to the console; the counts come from the engine
  process. The first read asks for frames. ``busk run --frontend`` in
  ``test_frontend.py``: what a frontend reads, and an engine that stops,
  stalls and is restarted.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Literal, NoReturn

import pytest

from builders import APPENDIX_A, load_doc, show_of
from busk import EngineHealth, LiveShow
from busk.compiler.compile import CompiledShow, compile_show
from busk.engine.clock import Clock, FakeClock, MonotonicClock
from busk.engine.link import EngineLink, LocalEngine
from busk.engine.loop import Engine
from busk.model.show import Show
from busk.output.scheduler import STALL_S
from busk.process import console_host
from busk.process.console_host import ProcessBackend
from busk.process.links import RemoteBus
from busk.process.wire import Kind, dumps, send
from busk.runner import Watchdog
from busk.session.library import ProfileLibrary
from test_links import Host

type Said = Literal["stalled", "restarting", "failed"] | None


def live_show() -> LiveShow:
    return LiveShow(show_of(load_doc(APPENDIX_A)), output=False)


def health_of(live: LiveShow) -> EngineHealth:
    health = live.health
    assert health is not None
    return health


def eventually(condition: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


@pytest.fixture
def hosts() -> Iterator[list[Host]]:
    """Engine hosts in this process, stopped at the end, as in ``test_links``."""
    made: list[Host] = []
    yield made
    for host in made:
        if host.thread.is_alive():
            host.stop()


def attach(
    shown: Show, compiled: CompiledShow, link: EngineLink, clock: Clock, watchdog: Watchdog | None
) -> LiveShow:
    """``busk run``'s show on ``link``, as its console makes it."""
    return LiveShow._attached(
        shown,
        compiled,
        link,
        clock,
        path=Path("unused.show"),
        library=ProfileLibrary(),
        state_dir=Path("unused"),
        dirty=False,
        stamp=("s", 0),
        causes=False,
        iface="lo",
        status=lambda: "",
        about=lambda: (),
        poll=lambda: None,
        routes=lambda: None,
        say=lambda text: None,
        warn=lambda text: None,
        watchdog=watchdog,
    )


def attached(watchdog: Watchdog | None = None) -> tuple[LiveShow, Engine, FakeClock]:
    """``busk run``'s show on an engine in this process that the test
    ticks (as with ``--threads``), with ``watchdog`` (as with processes)."""
    shown = show_of(load_doc(APPENDIX_A))
    compiled = compile_show(shown)
    clock = FakeClock()
    engine = Engine(compiled, clock)
    return attach(shown, compiled, LocalEngine(engine), clock, watchdog), engine, clock


# ------------------------------------------- a show that runs its own engine


def test_a_live_show_has_no_health_until_it_starts() -> None:
    live = live_show()
    assert live.health is None
    with live:
        assert live.health is not None


def test_a_running_show_ticks_and_its_newest_tick_is_recent() -> None:
    with live_show() as live:
        first = health_of(live)  # start() returns after the first tick
        assert first.state == "running"
        assert first.ticks >= 1
        assert first.lastTickAge is not None
        assert 0.0 <= first.lastTickAge < STALL_S
        eventually(lambda: health_of(live).ticks > first.ticks)
        assert health_of(live) is not health_of(live)  # a new object every read


def test_before_the_first_tick_it_is_starting_and_after_1_s_stalled() -> None:
    live, engine, clock = attached()
    live.start()
    assert live.health == EngineHealth(state="starting", ticks=0, overruns=0, lastTickAge=None)
    clock.advance(0.75)
    assert health_of(live).state == "starting"
    clock.advance(0.25)  # STALL_S since start()
    assert live.health == EngineHealth(state="stalled", ticks=0, overruns=0, lastTickAge=None)
    engine.tick(clock.now())
    assert live.health == EngineHealth(state="running", ticks=1, overruns=0, lastTickAge=0.0)


def test_a_show_whose_engine_makes_no_new_frame_for_1_s_is_stalled_until_it_does() -> None:
    live, engine, clock = attached()
    live.start()
    engine.tick(clock.now())
    clock.advance(0.75)
    assert live.health == EngineHealth(state="running", ticks=1, overruns=0, lastTickAge=0.75)
    clock.advance(0.25)
    assert live.health == EngineHealth(state="stalled", ticks=1, overruns=0, lastTickAge=1.0)
    clock.advance(5.0)
    assert health_of(live).lastTickAge == 6.0
    engine.tick(clock.now())
    assert live.health == EngineHealth(state="running", ticks=2, overruns=0, lastTickAge=0.0)


def test_the_counts_are_the_engines() -> None:
    live, engine, clock = attached()
    live.start()
    for _ in range(3):
        engine.tick(clock.now())
    engine.stats.overruns = 2  # Engine.run counts them; nothing runs it here
    health = health_of(live)
    assert (health.ticks, health.overruns) == (3, 2)


def test_a_stopped_show_says_so_with_its_last_counts() -> None:
    live, engine, clock = attached()
    live.start()
    engine.tick(clock.now())
    live.stop()
    assert live.health == EngineHealth(state="stopped", ticks=1, overruns=0, lastTickAge=0.0)
    clock.advance(2.0)
    assert live.health == EngineHealth(state="stopped", ticks=1, overruns=0, lastTickAge=2.0)


def test_an_engine_held_mid_tick_stalls_after_1_s_and_runs_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with live_show() as live:
        engine = live._engine
        assert engine is not None
        tick = engine.tick
        holding, released = threading.Event(), threading.Event()

        def held(now: float) -> None:
            if not released.is_set():
                holding.set()
                released.wait(10.0)
            tick(now)

        monkeypatch.setattr(engine, "tick", held)
        assert holding.wait(1.0)
        since = time.monotonic()
        try:
            eventually(lambda: health_of(live).state == "stalled")
            assert time.monotonic() - since >= STALL_S - 0.1  # its last frame came just before
            stalled = health_of(live)
            assert stalled.lastTickAge is not None
            assert stalled.lastTickAge >= STALL_S
        finally:
            released.set()
        eventually(lambda: health_of(live).state == "running")
        assert health_of(live).ticks > stalled.ticks


def test_ticks_that_end_late_count_as_overruns(monkeypatch: pytest.MonkeyPatch) -> None:
    with live_show() as live:
        engine = live._engine
        assert engine is not None
        tick, period = engine.tick, 1 / engine.compiled.engineHz

        def slow(now: float) -> None:
            time.sleep(1.5 * period)
            tick(now)

        before = health_of(live)
        monkeypatch.setattr(engine, "tick", slow)
        eventually(lambda: health_of(live).overruns >= before.overruns + 5)
        late = health_of(live)
        assert late.state == "running"  # late, but not stalled
        assert late.ticks > before.ticks


# ------------------------------------------------------------- busk run


def test_busk_runs_show_has_the_watchdogs_word() -> None:
    said: list[Said] = [None]
    live, engine, clock = attached(watchdog=lambda: said[0])
    live.start()
    assert live.health == EngineHealth(state="running", ticks=0, overruns=0, lastTickAge=None)
    engine.tick(clock.now())
    for word in ("stalled", "restarting", "failed"):
        said[0] = word
        assert live.health == EngineHealth(state=word, ticks=1, overruns=0, lastTickAge=0.0)
    said[0] = None
    clock.advance(5.0)  # no new frame for 5 s: the root decides, not the frames
    assert health_of(live).state == "running"
    said[0] = "failed"
    live.stop()
    assert health_of(live).state == "stopped"


def test_busk_runs_show_reads_the_engine_process(hosts: list[Host]) -> None:
    """The first read asks for the frames; the counts come once a second."""
    shown = show_of(load_doc(APPENDIX_A))
    compiled = compile_show(shown)
    clock = MonotonicClock()
    bus = RemoteBus(compiled, clock, sessionId="console-1", stamp=("s", 0))
    live = attach(shown, compiled, bus, clock, lambda: None)
    hosts.append(host := Host())
    host.attach(bus)
    live.start()
    assert health_of(live).lastTickAge is None  # asked for: the engine sends from now on
    eventually(lambda: health_of(live).lastTickAge is not None)
    eventually(lambda: health_of(live).ticks > 0)
    health = health_of(live)
    assert health.state == "running"
    assert health.lastTickAge is not None
    assert 0.0 <= health.lastTickAge < STALL_S
    assert health.ticks <= host.engine.stats.ticks


class Exited(Exception):
    """What the patched ``os._exit`` raises instead of ending the test process."""


@pytest.mark.parametrize(
    ("news", "state"), [("running", "running"), ("stalled", "stalled"), ("failed", "failed")]
)
def test_the_console_process_says_what_the_root_last_said(
    monkeypatch: pytest.MonkeyPatch, news: str, state: str
) -> None:
    """The control link's reader, run on the test's thread, as in
    ``test_route_status``: the root's ``ENGINE`` news is the show's state."""

    def exit_(code: int) -> NoReturn:
        raise Exited(code)

    fake = types.SimpleNamespace(
        Thread=lambda **kwargs: types.SimpleNamespace(start=lambda: None),
        Lock=threading.Lock,
    )
    monkeypatch.setattr(console_host, "threading", fake)
    monkeypatch.setattr(os, "_exit", exit_)
    control, root = socket.socketpair()
    link, engine = socket.socketpair()
    try:
        backend = ProcessBackend(control, link)
        send(root, Kind.ENGINE, dumps(news))
        root.close()  # the root is gone: end of file after the news
        with pytest.raises(Exited):
            backend._read_control()
        live, _, _ = attached(watchdog=backend.engine_state)
        live.start()
        assert health_of(live).state == state
    finally:
        for sock in (control, root, link, engine):
            sock.close()
