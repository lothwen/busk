"""``status`` under the facades (GAP-19 of ``docs/dev/tui/engine-gaps.md``).

``status`` prints ``busk run``'s status line of the engine's newest
snapshot. An :class:`OfflineShow`'s is the current tick's, so each line of a
script shows in the next ``status``. A :class:`LiveShow` prints it while it
runs, and ``no engine is running`` before ``start()`` and after ``stop()``.
``busk run``'s show keeps the CLI's answer, which knows the engine process's
state. Asking changes nothing. Appendix A's show: playback 1 is ``Song`` (two
cues), 3 is ``Blue``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import pytest

import busk.cli
import busk.console.console
from builders import APPENDIX_A, load_doc, show_of
from busk import LiveShow, OfflineShow, Reply
from busk.compiler.compile import compile_show
from busk.engine.clock import FakeClock
from busk.engine.link import LocalEngine
from busk.engine.loop import Engine
from busk.session.library import ProfileLibrary

IDLE = "GM 100% | BO off | P1 Main | Speed 1 120 BPM ×1"


@pytest.fixture
def show() -> OfflineShow:
    return OfflineShow(show_of(load_doc(APPENDIX_A)))


def live_show() -> LiveShow:
    return LiveShow(show_of(load_doc(APPENDIX_A)), output=False)


def eventually(condition: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


# ------------------------------------------------------------- offline


def test_status_is_the_status_line_of_the_snapshot(show: OfflineShow) -> None:
    assert show.execute("status") == Reply(IDLE)
    assert show.execute("status") == Reply(busk.cli.status_line(show.snapshot))


def test_status_follows_each_line(show: OfflineShow) -> None:
    tempo = "P1 Main | Speed 1 120 BPM ×1"
    lines = {
        "gm 0.8": f"GM 80% | BO off | {tempo}",
        "go 1": f"GM 80% | BO off | {tempo} | 1 Song on 1 Verse",
        "fader 1 0.5": f"GM 80% | BO off | {tempo} | 1 Song on 1 Verse 0.50",
        "go 3": f"GM 80% | BO off | {tempo} | 1 Song on 1 Verse 0.50 · 3 Blue on",
        "blackout on": f"GM 80% | BO on | {tempo} | 1 Song on 1 Verse 0.50 · 3 Blue on",
    }
    for line, status in lines.items():
        assert show.execute(line).ok
        assert show.execute("status") == Reply(status), line


def test_each_status_in_a_script_shows_the_lines_before_it(
    show: OfflineShow, tmp_path: Path
) -> None:
    path = tmp_path / "a.busk"
    path.write_text("status\ngo 3\nstatus\nblackout on\nstatus\n", encoding="utf-8")
    on = f"{IDLE} | 3 Blue on"
    assert show.execute(f"source {path}") == Reply(f"{IDLE}\n{on}\n{on.replace('BO off', 'BO on')}")
    assert show.run_script(path)[0] == on.replace("BO off", "BO on")


def test_asking_changes_nothing(show: OfflineShow) -> None:
    assert show.execute("sel fixture 101").ok
    document, programmer, snapshot = show.show, show.programmer, show.snapshot
    assert show.execute("status").ok
    assert show.show is document
    assert show.programmer is programmer
    assert show.snapshot is snapshot


# ---------------------------------------------------------------- live


def test_a_live_show_says_no_engine_runs_until_it_starts() -> None:
    live = live_show()
    assert live.execute("status") == Reply("no engine is running")
    assert live.execute("go 3") == Reply("")  # applies at the engine's first tick
    with live:
        eventually(lambda: live.execute("status") == Reply(f"{IDLE} | 3 Blue on"))


def test_a_live_show_follows_its_engine() -> None:
    with live_show() as live:
        assert live.execute("status") == Reply(IDLE)  # start() returns after the first tick
        assert live.execute("go 1") == Reply("")
        assert live.execute("gm 0.5") == Reply("")
        status = "GM 50% | BO off | P1 Main | Speed 1 120 BPM ×1 | 1 Song on 1 Verse"
        eventually(lambda: live.execute("status") == Reply(status))
        snapshot = live.snapshot
        assert snapshot is not None
        assert busk.cli.status_line(snapshot) == status


def test_a_live_show_says_no_engine_runs_once_it_stopped() -> None:
    live = live_show()
    with live:
        assert live.execute("go 3").ok
        eventually(lambda: live.execute("status").text.endswith("3 Blue on"))
    assert live.execute("status") == Reply("no engine is running")
    assert live.snapshot is not None  # the last one stays; the engine does not


def test_a_started_show_whose_engine_has_not_ticked_says_so() -> None:
    """The moment between :meth:`LiveShow.start` and the first tick, or a
    start whose engine never answered: as ``busk run --threads`` says."""
    live = live_show()
    live._phase = "running"  # what start() sets before the engine thread starts
    assert live.snapshot is None
    assert live.execute("status") == Reply("the engine has not ticked yet")


# ------------------------------------------------------------ busk run


def test_busk_runs_show_keeps_the_clis_status() -> None:
    """The CLI's answer also says when the engine process stalls, restarts
    or failed (``engine restarting``)."""
    shown = show_of(load_doc(APPENDIX_A))
    compiled = compile_show(shown)
    clock = FakeClock()
    live = LiveShow._attached(
        shown,
        compiled,
        LocalEngine(Engine(compiled, clock)),
        clock,
        path=Path("unused.show"),
        library=ProfileLibrary(),
        state_dir=Path("unused"),
        dirty=False,
        stamp=("s", 0),
        causes=False,
        iface="lo",
        status=lambda: "engine restarting",
        about=lambda: (),
        poll=lambda: None,
        routes=lambda: None,
        say=lambda text: None,
        warn=lambda text: None,
    )
    assert live.execute("status") == Reply("engine restarting")


def test_the_clis_status_line_is_the_facades() -> None:
    assert busk.cli.status_line is busk.console.console.status_line
