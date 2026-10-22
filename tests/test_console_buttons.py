"""Playback buttons from the console (GAP-04 of ``docs/dev/tui/engine-gaps.md``).

``flash N on|off``, ``button N <b> on|off`` and ``toggle N`` are the console
lines for what a frontend's buttons do: a flash held while the button is
down, a playback's own buttons by number, and a toggle. They are
performance lines like ``go N``: nothing to reply, and refused the same
way. Appendix A: playback 1 "Song" (cues 1 and 2) has the buttons go and
back, playback 3 "Blue" (blue on both heads and the par) toggle and flash.
"""

from __future__ import annotations

import json
import socket
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from builders import APPENDIX_A, load_doc, localhost_route, show_of
from busk import LiveShow, OfflineShow, PlaybackStatus, Reply
from process_harness import BuskRun
from sacn_receiver import Receiver

BLUE, WHITE = (0.0, 0.0, 1.0), (1.0, 1.0, 1.0)


@pytest.fixture
def offline() -> OfflineShow:
    return OfflineShow(show_of(load_doc(APPENDIX_A)))


def run(show: OfflineShow | LiveShow, *lines: str) -> None:
    for line in lines:
        assert show.execute(line) == Reply(""), line


def playback(show: OfflineShow | LiveShow, number: int) -> PlaybackStatus:
    snapshot = show.snapshot
    assert snapshot is not None
    return next(p for p in snapshot.playbacks if p.number == number)


def colors(offline: OfflineShow) -> set[tuple[float, float, float] | None]:
    return {element.color for element in offline.output.fixtures}


def eventually(condition: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_a_flash_is_up_from_on_to_off(offline: OfflineShow) -> None:
    run(offline, "flash 3 on")
    assert colors(offline) == {BLUE}
    assert (playback(offline, 3).flash, playback(offline, 3).state) == (True, "idle")
    run(offline, "flash 3 off")
    assert not playback(offline, 3).flash
    assert colors(offline) == {WHITE}


def test_toggle_activates_an_idle_playback_and_releases_an_active_one(
    offline: OfflineShow,
) -> None:
    run(offline, "toggle 3")
    assert playback(offline, 3).state == "active"
    run(offline, "toggle 3")
    assert playback(offline, 3).state == "releasing"


def test_a_button_does_what_its_function_does_on_its_edges(offline: OfflineShow) -> None:
    """Song's go and back act on the press only; Blue's flash on both
    edges, its toggle on the press."""
    seen = []
    for line in ("button 1 1 on", "button 1 1 off", "button 1 1 on", "button 1 2 on",
                 "button 1 2 off", "button 3 2 on", "button 3 2 off", "button 3 1 on"):  # fmt: skip
        run(offline, line)
        blue = playback(offline, 3)
        seen.append((playback(offline, 1).cue, blue.flash, blue.state))
    assert seen == [
        ("1", False, "idle"),
        ("1", False, "idle"),
        ("2", False, "idle"),
        ("1", False, "idle"),
        ("1", False, "idle"),
        ("1", True, "idle"),
        ("1", False, "idle"),
        ("1", False, "active"),
    ]


def test_a_select_button_selects_the_playbacks_targets_on_the_press(
    offline: OfflineShow,
) -> None:
    """As a bound control's press: the programmer's ``SELECT_PLAYBACK``, which
    replies and is undone like ``sel playback N``. The release does nothing."""
    assert offline.execute('playback 3 buttons ["toggle", "select"]').ok
    assert offline.execute("button 3 2 on") == Reply("3 targets selected")
    assert offline.programmer.selection == ((101, 1), (102, 1), (201, 1))
    run(offline, "button 3 2 off")
    assert offline.programmer.selection == ((101, 1), (102, 1), (201, 1))
    assert offline.execute("undo") == Reply("undid: 3 targets selected")
    assert offline.programmer.selection == ()


def test_release_all_drops_a_flash_held_from_the_console(offline: OfflineShow) -> None:
    run(offline, "flash 3 on")
    assert offline.execute("release all").ok
    assert not playback(offline, 3).flash
    run(offline, "flash 3 off")  # the button's own release, later: nothing to do
    assert colors(offline) == {WHITE}


@pytest.mark.parametrize("line", ["flash 9 on", "toggle 9", "button 9 1 on"])
def test_a_missing_playback_is_refused_as_go_refuses_it(offline: OfflineShow, line: str) -> None:
    refused = Reply("error: no playback 9", ok=False)
    assert offline.execute(line) == offline.execute("go 9") == refused


# ------------------------------------------------------------------- hosts


def test_a_live_show_flashes_while_the_button_is_held() -> None:
    live = LiveShow(show_of(load_doc(APPENDIX_A)), output=False)
    with live:
        run(live, "flash 3 on")
        eventually(lambda: live.snapshot is not None and playback(live, 3).flash)
        run(live, "flash 3 off")
        eventually(lambda: not playback(live, 3).flash)


@pytest.mark.skipif(
    not hasattr(socket, "send_fds") or not Path("/proc").is_dir(),
    reason="the process tree needs descriptor passing, the harness /proc",
)
def test_busk_run_takes_them_at_its_prompt(tmp_path: Path, receiver: Receiver) -> None:
    """The console process sends them to the engine process, as it does ``go``."""
    show = tmp_path / "show.json"
    show.write_text(json.dumps(localhost_route(load_doc(APPENDIX_A))))
    with BuskRun(show, sacn_port=receiver.port) as busk:
        busk.send("flash 3 on\n")
        busk.status_until(lambda line: line.endswith("| 3 Blue flash"))
        busk.send("flash 3 off\ntoggle 3\nbutton 3 2 on\n")
        busk.status_until(lambda line: line.endswith("| 3 Blue on flash"))
        busk.send("quit\n")
        assert busk.wait() == 0, busk.err
