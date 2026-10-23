"""GAP-12 of ``docs/dev/tui/engine-gaps.md``: lines from several threads.

* **Performance lines never wait** for another thread's line: not for an
  edit that compiles, a save that writes or a script that runs. The engine
  applies them while that line is still held.
* **Any other line waits** for the line another thread runs, and then runs
  against what it did: a programmer line, a query, an edit, ``undo``, a
  ``save``. A script, ``source`` or ``run_script``, runs whole.
* **Lines parsed against a show another thread is changing** wait and are
  parsed again: two ``effect add`` of a template neither has embedded both
  work. A line still uses up the ids of one parse.
* **Ctrl+C** stays with the main thread: another thread's line and script
  neither raise it nor stop for it.
* **Queries** survive a command another thread submits while they read.
* **Many threads** at once, and ``busk run``'s show, whose engine is in
  another process.
"""

from __future__ import annotations

import signal
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import pytest

from builders import APPENDIX_A, load_doc, show_of
from busk import LiveShow, OfflineShow
from busk.commands.types import Command
from busk.compiler.compile import compile_show
from busk.console.console import Console, Reply
from busk.engine.snapshot import EngineSnapshot
from busk.model.validate import has_errors, validate_show
from busk.persistence.show_file import show_json
from busk.session import session as session_module
from busk.session.ids import CounterIds
from test_frontend import attached, remote
from test_links import Host

TIMEOUT = 5.0
WAITS = 0.2
"""How long a line that must wait is watched: a line that does not wait
for the lock takes microseconds."""


@pytest.fixture
def live() -> Iterator[LiveShow]:
    """Appendix A, running, without output."""
    with LiveShow(show_of(load_doc(APPENDIX_A)), output=False) as show:
        yield show


@pytest.fixture
def threads() -> Iterator[ThreadPoolExecutor]:
    with ThreadPoolExecutor(max_workers=8) as pool:
        yield pool


class Gate:
    """Holds every call of ``session_module.<name>`` until :meth:`open`:
    ``compile_show`` holds an edit, with the session lock taken, and
    ``save_show`` a save."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
        self.entered, self._opened = threading.Event(), threading.Event()
        real = getattr(session_module, name)

        def held(*args: Any, **kwargs: Any) -> Any:
            if not self._opened.is_set():
                self.entered.set()
                assert self._opened.wait(TIMEOUT)
            return real(*args, **kwargs)

        monkeypatch.setattr(session_module, name, held)

    def wait(self) -> None:
        assert self.entered.wait(TIMEOUT), "the line never reached the gate"

    def open(self) -> None:
        self._opened.set()


def eventually(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + TIMEOUT
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def waits(future: Future[Any]) -> bool:
    """Whether ``future``'s line is still waiting after :data:`WAITS` s."""
    time.sleep(WAITS)
    return not future.done()


def ok(future: Future[Reply]) -> Reply:
    reply = future.result(TIMEOUT)
    assert reply.ok, reply.text
    return reply


def playback(snapshot: EngineSnapshot | None, number: int) -> Any:
    assert snapshot is not None
    return next(status for status in snapshot.playbacks if status.number == number)


def fixture_name(live: LiveShow, number: int) -> str:
    return next(f["name"] for f in live.show["fixtures"] if f["number"] == number)


# ------------------------------------------------ performance lines never wait


PERFORMANCE: dict[str, Callable[[EngineSnapshot], bool]] = {
    "go 1": lambda s: playback(s, 1).state == "active",
    "toggle 3": lambda s: playback(s, 3).state == "active",
    "fader 6 40%": lambda s: playback(s, 6).faderLevel == pytest.approx(0.4),
    "flash 3 on": lambda s: playback(s, 3).flash,
    "gm 50%": lambda s: s.grandMaster == pytest.approx(0.5),
    "bpm 140": lambda s: s.speed[0].bpm == pytest.approx(140),
    "blackout on": lambda s: s.blackout,
    "output off": lambda s: not s.outputEnabled,
}


def blocking_line(how: str, tmp_path: Path) -> str:
    """A line that holds the console while its gate is closed."""
    if how == "save":
        return f"save {tmp_path / 'saved.show'}"
    if how == "script":
        script = tmp_path / "edits.busk"
        script.write_text('sel fixture 101\nfixture 101 name "Edited"\nfixture 102 name "Too"\n')
        return f"source {script}"
    return 'fixture 101 name "Edited"'


@pytest.mark.parametrize("how", ["edit", "save", "script"])
def test_performance_lines_never_wait_for_another_threads_line(
    live: LiveShow,
    threads: ThreadPoolExecutor,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    how: str,
) -> None:
    gate = Gate(monkeypatch, "save_show" if how == "save" else "compile_show")
    held = threads.submit(live.execute, blocking_line(how, tmp_path))
    gate.wait()
    for line in PERFORMANCE:
        assert live.execute(line) == Reply("")
    eventually(
        lambda: all(check(cast(EngineSnapshot, live.snapshot)) for check in PERFORMANCE.values())
    )
    assert not held.done()  # the engine applied them all while the line was held
    gate.open()
    ok(held)


# --------------------------------------------- any other line waits, then runs


AFTER_THE_EDIT: dict[str, Callable[[Reply, LiveShow], bool]] = {
    "sel fixture 102": lambda reply, live: reply.text == "1 target selected",
    "list fixtures": lambda reply, live: "Edited" in reply.text,
    'fixture 102 name "Later"': lambda reply, live: fixture_name(live, 102) == "Later",
    "undo": lambda reply, live: fixture_name(live, 101) == "MH 1",  # it undid the edit
    "save": lambda reply, live: reply.text.startswith("saved "),
}


@pytest.mark.parametrize("line", AFTER_THE_EDIT)
def test_any_other_line_waits_for_another_threads_line_then_sees_it(
    threads: ThreadPoolExecutor, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, line: str
) -> None:
    show = show_of(load_doc(APPENDIX_A))
    with LiveShow(show, output=False, path=tmp_path / "a.show") as live:
        gate = Gate(monkeypatch, "compile_show")
        edit = threads.submit(live.execute, 'fixture 101 name "Edited"')
        gate.wait()
        later = threads.submit(live.execute, line)
        assert waits(later)
        gate.open()
        ok(edit)
        assert AFTER_THE_EDIT[line](ok(later), live)


@pytest.mark.parametrize("how", ["source", "run_script"])
def test_a_script_runs_whole(
    live: LiveShow,
    threads: ThreadPoolExecutor,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    how: str,
) -> None:
    script = tmp_path / "names.busk"
    script.write_text('fixture 101 name "A"\nfixture 101 name "B"\n')
    gate = Gate(monkeypatch, "compile_show")
    if how == "source":
        whole: Future[Any] = threads.submit(live.execute, f"source {script}")
    else:
        whole = threads.submit(live.run_script, script)
    gate.wait()  # the script's first line compiles
    other = threads.submit(live.execute, 'fixture 101 name "C"')
    assert waits(other)
    gate.open()
    whole.result(TIMEOUT)
    ok(other)
    assert fixture_name(live, 101) == "C"  # after the whole script, not between its lines


def test_a_line_parsed_against_a_show_another_thread_changes_is_parsed_again(
    live: LiveShow, threads: ThreadPoolExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both ``effect add`` lines embed the library's ``Saw`` when parsed
    against a show without it; the second, parsed again once the first is
    done, only adds its effect, with an id of its own."""
    assert live.execute("sel fixture 101 thru 102").ok
    gate = Gate(monkeypatch, "compile_show")
    first = threads.submit(live.execute, 'effect add "Saw"')
    gate.wait()  # embedding the template
    second = threads.submit(live.execute, 'effect add "Saw"')
    assert waits(second)
    gate.open()
    assert ok(first).text == "added effect template 'Saw'\nadded effect 'fx1' on 2 targets"
    assert ok(second).text == "added effect 'fx2' on 2 targets"
    assert [t["name"] for t in live.show["effects"]] == ["Pulse", "Saw"]


def test_a_line_uses_up_the_ids_of_one_parse() -> None:
    """Parsed twice, a line still takes the factory's next id: a scripted
    build with :class:`CounterIds` stays the same show."""
    offline = OfflineShow(show_of(load_doc(APPENDIX_A)), ids=CounterIds(100))
    assert offline.execute('universe add 2 "Spare"').ok
    assert offline.execute('master add size "Spare"').ok
    assert offline.show["universes"][-1]["id"] == "u-000000000064"  # 100
    assert offline.show["masters"][-1]["id"] == "m-000000000065"  # 101


def test_blank_lines_and_parse_errors_take_no_lock(
    live: LiveShow, threads: ThreadPoolExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = Gate(monkeypatch, "compile_show")
    held = threads.submit(live.execute, 'fixture 101 name "Edited"')
    gate.wait()
    assert live.execute("   # nothing") == Reply("")
    assert live.execute("go 99") == Reply("error: no playback 99", ok=False)
    gate.open()
    ok(held)


# ------------------------------------------------------------------ Ctrl+C


def test_ctrl_c_stays_with_the_main_thread(
    live: LiveShow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ctrl+C during the main thread's line: another thread's line and script,
    run meanwhile, neither raise it nor stop for it; the main thread raises
    it once its line is done."""
    script = tmp_path / "two.busk"
    script.write_text("gm 30%\ngm 40%\n")
    other: list[object] = []

    def elsewhere() -> None:
        try:
            other.append(live.execute("go 1"))
            other.append(live.run_script(script))
        except BaseException as exc:  # what the main thread's Ctrl+C must not cause
            other.append(exc)

    original = Console._execute

    def interrupted(console: Console, line: str) -> Reply:
        reply = original(console, line)
        if line == "gm 50%":
            signal.raise_signal(signal.SIGINT)  # held back until the line is done
            thread = threading.Thread(target=elsewhere)
            thread.start()
            thread.join(TIMEOUT)
        return reply

    monkeypatch.setattr(Console, "_execute", interrupted)
    with pytest.raises(KeyboardInterrupt):
        live.execute("gm 50%")
    assert other == [Reply(""), []]  # the script ran to its end
    eventually(lambda: live.snapshot is not None and live.snapshot.grandMaster == 0.4)


# ------------------------------------------------------------------ queries


def test_queries_survive_a_command_another_thread_submits_while_they_read(
    live: LiveShow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``list masters`` reads the show, then its compiled form, and ``list
    cues`` reads the show again after the parse: a master or a cue list that
    another thread's command deleted in between is left out, not an
    exception."""
    assert live.execute('master add size "Spare"').ok
    assert live.execute("sel fixture 101").ok
    assert live.execute("set intensity 50%").ok
    assert live.execute("record cue 50").ok
    spare = next(m["id"] for m in live.show["masters"] if m["name"] == "Spare")
    listed = next(cl["id"] for cl in live.show["cueLists"] if cl["number"] == 50)
    deletes = {
        "_list_masters": {"type": "DELETE", "path": ["masters", {"id": spare}]},
        "_list_cues": {"type": "DELETE", "path": ["cueLists", {"id": listed}]},
    }
    for name, command in deletes.items():
        original = getattr(Console, name)

        def deleted_first(
            console: Console, *args: Any, original: Any = original, command: Any = command
        ) -> Any:
            assert live.submit(cast(Command, command)).ok  # as another thread would
            return original(console, *args)

        monkeypatch.setattr(Console, name, deleted_first)
    masters = live.execute("list masters")
    assert masters.ok
    assert "Spare" not in masters.text
    assert live.execute("list cues 50") == Reply("no cue list 50")


# -------------------------------------------------------------- many threads


def test_lines_from_many_threads_all_run(live: LiveShow, threads: ThreadPoolExecutor) -> None:
    """Eight threads, each with its own lines: performance, programmer, edits
    and queries. Every line works, each thread's last edit is the one that
    stays, and the show still validates."""
    numbers = [101, 102, 201]

    def lines(k: int) -> list[str]:
        fixture = numbers[k % 3]
        mine: list[str] = []
        for i in range(25):
            mine += [
                f"fader 6 {(k * 25 + i) % 100}%",
                f"sel fixture {fixture}",
                f"set intensity {i}%",
                f'fixture {fixture} name "T{k}-{i}"' if k < 3 else "programmer",
                "go 1" if i % 2 else "back 1",
                "list fixtures" if i % 3 else "info",
            ]
        return mine

    def run(k: int) -> list[Reply]:
        return [live.execute(line) for line in lines(k)]

    replies = [
        reply
        for k, future in enumerate([threads.submit(run, k) for k in range(8)])
        for reply in future.result(30)
    ]
    assert [reply for reply in replies if not reply.ok] == []
    assert [fixture_name(live, number) for number in numbers] == ["T0-24", "T1-24", "T2-24"]
    checked, issues = validate_show(show_json(live.show))
    assert checked is not None
    assert not has_errors(issues)


# ------------------------------------------------------------ busk run's show


def test_busk_runs_show_sends_a_performance_line_while_an_edit_compiles(
    threads: ThreadPoolExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The attached show of ``busk run``, its engine in an engine host: the
    console's bus sends ``go 1`` while the session compiles an edit."""
    show = show_of(load_doc(APPENDIX_A))
    compiled = compile_show(show)
    bus = remote(compiled)
    host = Host()
    try:
        host.attach(bus)
        live = attached(bus, show, compiled)
        assert bus.sync(TIMEOUT)
        gate = Gate(monkeypatch, "compile_show")
        edit = threads.submit(live.execute, 'fixture 101 name "Edited"')
        gate.wait()
        assert live.execute("go 1") == Reply("")
        eventually(lambda: playback(bus.snapshot, 1).state == "active")
        assert not edit.done()
        gate.open()
        ok(edit)
    finally:
        host.stop()
