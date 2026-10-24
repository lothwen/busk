"""The quit signal (GAP-18 of ``docs/dev/tui/engine-gaps.md``).

``Reply.quit`` is true for the lines after which ``busk run``'s prompt ends
the run: ``quit`` and ``exit``, however typed, and a ``source`` whose script
stops at a ``quit`` (in a script it sources, too). The facades stop nothing:
the caller ends, or carries on, and the next line's reply is false again. A
script stops at its own ``quit`` line, never at an earlier line's. ``busk
run`` still ends after these lines: at the prompt, after ``--script``, and
reading stdin. Appendix A's show: group 1 is fixtures 101 and 102.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from builders import APPENDIX_A, load_doc, offline, show_of
from busk import LiveShow, OfflineShow, Reply, ScriptError
from busk.compiler.compile import compile_show
from busk.console.console import interact
from busk.engine.clock import FakeClock
from busk.engine.link import LocalEngine
from busk.engine.loop import Engine
from busk.session.library import ProfileLibrary

QUIT = Reply("", quit=True)


@pytest.fixture
def show() -> OfflineShow:
    return OfflineShow(show_of(load_doc(APPENDIX_A)))


def script(directory: Path, name: str, *lines: str) -> Path:
    path = directory / name
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


def selection(show: OfflineShow | LiveShow) -> list[int]:
    return [number for number, _ in show.programmer.selection]


def eventually(condition: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


# --------------------------------------------------------------- the lines


@pytest.mark.parametrize("line", ["quit", "exit", "QUIT", "Exit", "  quit  ", "quit   # bye"])
def test_quit_and_exit_say_so_however_they_are_typed(show: OfflineShow, line: str) -> None:
    assert show.execute(line) == QUIT


@pytest.mark.parametrize(
    "line",
    ["", "# quit", "help", "info", "go 1", "sel group 1", "output off", "undo", "status"],
)
def test_every_other_line_does_not(show: OfflineShow, line: str) -> None:
    assert not show.execute(line).quit


@pytest.mark.parametrize(
    ("line", "error"),
    [("quit now", "unexpected 'now'"), ("quits", "unknown command 'quits' (try 'help')")],
)
def test_a_quit_that_does_not_parse_is_an_error_and_does_not_quit(
    show: OfflineShow, line: str, error: str
) -> None:
    assert show.execute(line) == Reply(f"error: {error}", ok=False)


def test_the_show_carries_on_and_only_that_line_says_so(show: OfflineShow) -> None:
    """A frontend that asked, and was told no: nothing has stopped."""
    seq = show.tick(1.0).seq
    assert show.execute("quit") == QUIT
    assert show.execute("sel group 1") == Reply("2 targets selected")
    assert show.execute("go 1") == Reply("")
    assert show.snapshot.playbacks[0].state == "active"
    assert show.tick(2.0).seq > seq
    assert selection(show) == [101, 102]


def test_the_reply_of_quit_changes_nothing(show: OfflineShow) -> None:
    before, programmer = show.show, show.programmer
    assert show.execute("quit") == QUIT
    assert show.show is before
    assert show.programmer is programmer


# --------------------------------------------------------------- scripts


def test_a_source_whose_script_quits_says_so(show: OfflineShow, tmp_path: Path) -> None:
    path = script(tmp_path, "a.busk", "sel fixture 101", "quit", "sel + fixture 102")
    assert show.execute(f"source {path}") == Reply("1 target selected", quit=True)
    assert selection(show) == [101]  # the line after the quit did not run


def test_a_quit_in_a_nested_source_ends_every_script(show: OfflineShow, tmp_path: Path) -> None:
    inner = script(tmp_path, "inner.busk", "sel + fixture 102", "quit", "sel + fixture 201")
    outer = script(tmp_path, "outer.busk", "sel fixture 101", f"source {inner}", "clear")
    reply = show.execute(f"source {outer}")
    assert reply == Reply("1 target selected\n2 targets selected", quit=True)
    assert selection(show) == [101, 102]


def test_a_source_that_does_not_quit_does_not_say_so(show: OfflineShow, tmp_path: Path) -> None:
    done = script(tmp_path, "done.busk", "sel fixture 101", "# quit")
    assert show.execute(f"source {done}") == Reply("1 target selected")
    failing = script(tmp_path, "failing.busk", "sel group 9", "quit")
    reply = show.execute(f"source {failing}")
    assert (reply.ok, reply.quit) == (False, False)  # it stopped at the error, before the quit
    missing = show.execute(f"source {tmp_path / 'missing.busk'}")
    assert (missing.ok, missing.quit) == (False, False)


def test_run_script_stops_at_quit_and_the_show_runs_on(show: OfflineShow, tmp_path: Path) -> None:
    path = script(tmp_path, "a.busk", "sel fixture 101", "quit", "sel + fixture 102")
    assert show.run_script(path) == ["1 target selected"]
    assert selection(show) == [101]
    assert show.execute("go 1") == Reply("")


def test_a_quit_line_earlier_does_not_cut_a_later_script_short(
    show: OfflineShow, tmp_path: Path
) -> None:
    """It used to: the console's flag stayed set, so the next ``source`` or
    ``run_script`` stopped after its first line, and said nothing."""
    path = script(tmp_path, "a.busk", "sel fixture 101", "sel + fixture 102", "sel + fixture 201")
    assert show.execute("quit") == QUIT
    reply = show.execute(f"source {path}")
    assert reply == Reply("1 target selected\n2 targets selected\n3 targets selected")
    assert show.execute("quit") == QUIT
    assert show.execute("sel none").ok
    assert show.run_script(path)[-1] == "3 targets selected"
    assert selection(show) == [101, 102, 201]


def test_a_failing_script_after_a_quit_still_raises(show: OfflineShow, tmp_path: Path) -> None:
    path = script(tmp_path, "a.busk", "sel fixture 101", "sel group 9")
    assert show.execute("quit") == QUIT
    with pytest.raises(ScriptError) as raised:
        show.run_script(path)
    assert (raised.value.line, raised.value.text) == (2, "sel group 9")


# ------------------------------------------------------------- live shows


def test_a_live_show_runs_on_after_quit_from_another_thread() -> None:
    with LiveShow(show_of(load_doc(APPENDIX_A)), output=False) as live:
        replies: list[Reply] = []
        sender = threading.Thread(target=lambda: replies.append(live.execute("quit")))
        sender.start()
        sender.join()
        assert replies == [QUIT]
        frame = live.frame
        assert frame is not None
        assert live.execute("go 1") == Reply("")
        eventually(
            lambda: live.snapshot is not None and live.snapshot.playbacks[0].state == "active"
        )
        eventually(lambda: (latest := live.frame) is not None and latest.seq > frame.seq)


def test_quits_from_one_thread_never_cut_another_threads_scripts(tmp_path: Path) -> None:
    path = script(tmp_path, "a.busk", "sel fixture 101", "sel + fixture 102", "sel + fixture 201")
    with LiveShow(show_of(load_doc(APPENDIX_A)), output=False) as live:
        quits: list[Reply] = []
        written: list[list[str]] = []

        def quitter() -> None:
            quits.extend(live.execute("quit") for _ in range(50))

        def scripter() -> None:
            written.extend(live.run_script(path) for _ in range(50))

        threads = [threading.Thread(target=quitter), threading.Thread(target=scripter)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert quits == [QUIT] * 50
        assert all(len(lines) == 3 for lines in written), written
        assert selection(live) == [101, 102, 201]


# ---------------------------------------------------------------- busk run


def attached() -> LiveShow:
    """The show ``busk run``'s console process runs, on an engine of its own."""
    shown = show_of(load_doc(APPENDIX_A))
    compiled = compile_show(shown)
    clock = FakeClock()
    return LiveShow._attached(
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


def test_busk_runs_prompt_ends_after_a_source_that_quits(tmp_path: Path) -> None:
    """The lines whose reply says quit are the ones the prompt ends after:
    no line is asked for after the ``source``."""
    live = attached()
    path = script(tmp_path, "a.busk", "sel fixture 101", "quit", "sel + fixture 102")
    feed = iter(["sel none", f"source {path}"])
    written: list[str] = []
    interact(live._console, ask=lambda prompt: next(feed), write=written.append)
    assert written == ["0 targets selected", "1 target selected"]
    assert live._console.quit_requested


@pytest.mark.parametrize("where", ["script", "source"])
def test_busk_run_ends_after_a_script_that_quits(tmp_path: Path, where: str) -> None:
    """``--script``'s ``quit`` ends the run before stdin is read, and a
    ``source`` read from stdin ends it before the next line."""
    show = tmp_path / "show.json"
    show.write_text(json.dumps(offline(load_doc(APPENDIX_A))), encoding="utf-8")
    path = script(tmp_path, "a.busk", "sel fixture 101", "quit", "sel + fixture 102")
    options = ["--script", str(path)] if where == "script" else []
    stdin = ("" if where == "script" else f"source {path}\n") + "sel group 1\n"
    result = subprocess.run(
        [sys.executable, "-m", "busk", "run", "--threads", str(show), *options],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "XDG_STATE_HOME": str(tmp_path / "state")},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout.splitlines()
    assert "1 target selected" in out
    assert "2 targets selected" not in out  # neither the script's last line nor stdin's
