"""Confirmation before dangerous lines (GAP-10 of ``docs/dev/tui/engine-gaps.md``).

``OfflineShow.confirmation(line)`` and ``LiveShow.confirmation(line)`` give
the yes/no question ``busk run``'s prompt asks before running ``line``, or
``None`` to run it at once, so a frontend asks the same without parsing the
line. Only ``output off`` asks. Asking changes nothing (no id is used up, no
step is committed), and ``execute`` never asks. Appendix A's show, with its
surface "MIDI Controller".
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from builders import APPENDIX_A, ROOT, load_doc, show_of
from busk import CounterIds, LiveShow, OfflineShow, Reply, new_show
from busk.compiler.compile import compile_show
from busk.console.console import interact
from busk.engine.clock import FakeClock
from busk.engine.link import LocalEngine
from busk.engine.loop import Engine
from busk.persistence.show_file import show_json
from busk.session.library import ProfileLibrary

QUESTION = "Turn all DMX output off?"
CLUB_NIGHT = ROOT / "examples" / "club-night.busk"
CID = "0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f"


@pytest.fixture
def offline() -> OfflineShow:
    return OfflineShow(show_of(load_doc(APPENDIX_A)))


def eventually(condition: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


@pytest.mark.parametrize("line", ["output off", "OUTPUT OFF", "  output   off  # panic"])
def test_output_off_asks_however_it_is_typed(offline: OfflineShow, line: str) -> None:
    assert offline.confirmation(line) == QUESTION


@pytest.mark.parametrize(
    "line",
    [
        "output on",
        "release all",
        "release all 2",
        "blackout on",
        "gm 0",
        "clear",
        "go 1",
        "undo",
        "info",
        "help",
        "quit",
        "",
        "# output off",
        'bind "MIDI Controller" note 1 61 output off',  # binds it: the control never asks
    ],
)
def test_every_other_line_runs_at_once(offline: OfflineShow, line: str) -> None:
    assert offline.confirmation(line) is None


@pytest.mark.parametrize(
    ("line", "error"),
    [("output of", "expected on or off, got 'of'"), ("output", "expected on or off")],
)
def test_a_line_that_does_not_parse_is_left_to_execute(
    offline: OfflineShow, line: str, error: str
) -> None:
    assert offline.confirmation(line) is None
    assert offline.execute(line) == Reply(f"error: {error}", ok=False)


def test_execute_never_asks(offline: OfflineShow) -> None:
    """The frontend asks, then runs the line; asking again is the same
    question, whatever the output is now."""
    assert offline.execute("output off") == Reply("")
    assert not offline.snapshot.outputEnabled
    assert offline.confirmation("output off") == QUESTION


def test_source_is_not_asked_about_and_its_lines_never_ask(
    offline: OfflineShow, tmp_path: Path
) -> None:
    script = tmp_path / "panic.busk"
    script.write_text("output off\n", encoding="utf-8")
    assert offline.confirmation(f"source {script}") is None
    assert offline.execute(f"source {script}").ok
    assert not offline.snapshot.outputEnabled


# ------------------------------------------------------- asking changes nothing


def test_asking_before_every_line_builds_the_same_show() -> None:
    """``examples/club-night.busk`` with reproducible ids, asked about line by
    line or not: the same show, byte for byte, and the same programmer. The
    console parses with a factory of its own, so no id is used up."""

    def build(ask: bool) -> OfflineShow:
        ids = CounterIds()
        now = datetime(2026, 10, 23, tzinfo=UTC)
        offline = OfflineShow(new_show("Club Night", cid=CID, now=now, ids=ids), ids=ids)
        for line in CLUB_NIGHT.read_text(encoding="utf-8").splitlines():
            if line == "save":
                continue
            if ask:
                assert offline.confirmation(line) is None, line
            assert offline.execute(line).ok, line
        return offline

    asked, built = build(ask=True), build(ask=False)
    assert show_json(asked.show) == show_json(built.show)
    assert asked.programmer == built.programmer


def test_asking_commits_nothing(offline: OfflineShow) -> None:
    assert offline.execute("sel fixture 101").ok
    show, programmer = offline.show, offline.programmer
    for line in ("output off", 'universe add 2 "Spare"', "set intensity 50%", "record cue 1"):
        offline.confirmation(line)
    assert offline.show is show
    assert offline.programmer is programmer
    assert offline.snapshot.outputEnabled
    assert offline.execute("undo") == Reply("undid: 1 target selected")


# ------------------------------------------------------------------- hosts


def test_a_live_show_asks_before_it_starts_and_from_another_thread() -> None:
    live = LiveShow(show_of(load_doc(APPENDIX_A)), output=False)
    assert live.confirmation("output off") == QUESTION
    with live:
        asked: list[str | None] = []
        reader = threading.Thread(
            target=lambda: asked.extend(live.confirmation(line) for line in ("output off", "go 1"))
        )
        reader.start()
        reader.join()
        assert asked == [QUESTION, None]
        assert live.execute("output off") == Reply("")
        eventually(lambda: live.snapshot is not None and not live.snapshot.outputEnabled)


def test_busk_runs_prompt_asks_what_its_show_answers() -> None:
    """The console process's show answers what its prompt asks, which adds
    only ``[y/N]``."""
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
        status=lambda: "",
        about=lambda: (),
        poll=lambda: None,
        routes=lambda: None,
        say=lambda text: None,
        warn=lambda text: None,
    )
    assert live.confirmation("output off") == QUESTION
    assert live.confirmation("output on") is None
    feed = iter(["output on", "output off", "n", "quit"])
    prompts: list[str] = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return next(feed)

    written: list[str] = []
    interact(live._console, ask=ask, write=written.append)
    assert prompts == ["busk> ", "busk> ", f"{QUESTION} [y/N] ", "busk> "]
    assert written == ["cancelled"]
