"""The bridge on a real show: ``--standalone`` with no output and no
surfaces, on the club-night show."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from busk_tui.bridge import Bridge
from busk_tui.model import (
    BridgeEvent,
    CommandDone,
    EffectsChanged,
    EngineRunning,
    HealthChanged,
    LiveChanged,
    ProgrammerChanged,
    RoutesChanged,
    SessionChanged,
    ShowChanged,
)

WAIT_S = 15.0  # the show's start


class Drained:
    def __init__(self, bridge: Bridge) -> None:
        self.bridge = bridge
        self.seen: list[BridgeEvent] = []

    def until(self, test: Callable[[BridgeEvent], bool], timeout: float = WAIT_S) -> BridgeEvent:
        deadline = time.monotonic() + timeout
        index = 0
        while time.monotonic() < deadline:
            self.seen += self.bridge.drain()
            for event in self.seen[index:]:
                if test(event):
                    return event
            index = len(self.seen)
            time.sleep(0.01)
        raise AssertionError(f"not within {timeout} s; saw {[type(e).__name__ for e in self.seen]}")


@pytest.fixture
def live(club_path: Path, tmp_path: Path) -> Iterator[tuple[Bridge, Drained]]:
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    bridge.start()
    drained = Drained(bridge)
    drained.until(lambda e: isinstance(e, EngineRunning))
    yield bridge, drained
    bridge.stop()


def test_it_reaches_running_with_the_shows_state(live: tuple[Bridge, Drained]) -> None:
    bridge, drained = live
    running = next(e for e in drained.seen if isinstance(e, EngineRunning))
    assert running.title == "Club Night"
    assert bridge.help_lines
    assert bridge.help_lines[0].startswith("    sel <targets>")
    drained.until(lambda e: isinstance(e, HealthChanged) and e.state == "running")
    shown = drained.until(lambda e: isinstance(e, ShowChanged))
    assert isinstance(shown, ShowChanged)
    assert [page.name for page in shown.show.pages] == ["Main", "Washes"]
    routes = drained.until(lambda e: isinstance(e, RoutesChanged))
    assert isinstance(routes, RoutesChanged)
    assert [(r.protocol, r.universe, r.state) for r in routes.routes] == [("sACN", 1, None)]


def test_a_performance_line_shows_within_a_second(live: tuple[Bridge, Drained]) -> None:
    bridge, drained = live
    sent = time.monotonic()
    bridge.send("gm 50%", "ui", performance=True)
    event = drained.until(lambda e: isinstance(e, LiveChanged) and e.state.gm == 0.5, 1.0)
    assert isinstance(event, LiveChanged)
    assert time.monotonic() - sent < 1.0
    names = [master.name for master in event.state.masters]
    assert names == ["Grand Master", "Speed 1", "FX", "Wash level", "Fade"]


def test_a_fader_moved_elsewhere_shows(live: tuple[Bridge, Drained]) -> None:
    """As from a surface or the web remote: not through the bridge. (Measured
    on the club-night show: 26 ms at the median, 76 ms at most, with the
    app's 25 ms drain; the bound here is loose for a loaded machine.)"""
    bridge, drained = live
    show = bridge._show
    assert show is not None
    sent = time.monotonic()
    threading.Thread(target=show.execute, args=("fader 2 35%",)).start()
    drained.until(
        lambda e: isinstance(e, LiveChanged) and e.state.playback(2).level == 0.35,  # type: ignore[union-attr]
        timeout=1.0,
    )
    assert time.monotonic() - sent < 0.5


def test_the_playbacks_and_while_watched_the_effects(live: tuple[Bridge, Drained]) -> None:
    bridge, drained = live
    bridge.send("go 11", "ui", performance=True)
    bridge.send("fader 11 100%", "ui", performance=True)
    event = drained.until(
        lambda e: isinstance(e, LiveChanged) and e.state.playback(11).level == 1.0  # type: ignore[union-attr]
    )
    assert isinstance(event, LiveChanged)
    circle = event.state.playback(11)
    assert circle is not None
    assert (circle.name, circle.state, circle.fader, circle.cueName) == (
        "Circle",
        "active",
        "size",
        "Circle",
    )
    assert not [e for e in drained.seen if isinstance(e, EffectsChanged)]
    bridge.watch(output=False, effects=True)
    running = drained.until(lambda e: isinstance(e, EffectsChanged) and bool(e.effects.effects))
    assert isinstance(running, EffectsChanged)
    (effect,) = running.effects.effects
    assert (effect.playback, effect.cue, effect.id, len(effect.wave)) == (11, "1", "fx1", 20)


def test_a_selection_and_its_undo_step(live: tuple[Bridge, Drained]) -> None:
    bridge, drained = live
    bridge.send("sel group 1", "typed")
    done = drained.until(lambda e: isinstance(e, CommandDone) and e.line == "sel group 1")
    assert isinstance(done, CommandDone)
    assert done.ok
    event = drained.until(lambda e: isinstance(e, ProgrammerChanged) and e.programmer.selection)
    assert isinstance(event, ProgrammerChanged)
    assert event.programmer.selection == ((101, 1), (102, 1))
    drained.until(lambda e: isinstance(e, SessionChanged) and e.session.undo == 1)


def test_after_stop_no_busk_thread_is_left(club_path: Path, tmp_path: Path) -> None:
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    bridge.start()
    Drained(bridge).until(lambda e: isinstance(e, EngineRunning))
    bridge.stop()
    assert not [thread.name for thread in threading.enumerate() if thread.name.startswith("busk")]
