"""``busk-tui``'s parent process (``busk_tui.parent``, file-menu plan D3,
calls 9 and 11): one ``busk run`` after another, the hand-off file, the
signals and the exit codes; with fake runs, then with real processes."""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from busk_tui import parent

FIRST = ["busk", "run", "a.show"]


def then(show: Path) -> list[str]:
    return ["busk", "run", str(show)]


@dataclass
class FakeRun:
    """A run that, while the parent waits for it, may get the parent a
    signal and hand a show over, as the TUI does, then ends with ``code``."""

    command: list[str]
    environment: dict[str, str]
    code: int = 0
    hand: Path | None = None
    signal_parent: int | None = None
    signals: list[int] = field(default_factory=list)
    sigint: Any = None  # the parent's SIGINT handler while it waits

    def wait(self) -> int:
        self.sigint = signal.getsignal(signal.SIGINT)
        if self.signal_parent is not None:
            os.kill(os.getpid(), self.signal_parent)  # its handler runs before the next line
        if self.hand is not None:
            assert parent.hand_off(self.hand, self.environment)
        return self.code

    def send_signal(self, number: int) -> None:
        self.signals.append(number)


class Runs:
    """Starts one :class:`FakeRun` per command, each as ``script`` says."""

    def __init__(self, *script: dict[str, Any]) -> None:
        self.script = list(script)
        self.started: list[FakeRun] = []

    def __call__(self, command: list[str], environment: dict[str, str]) -> FakeRun:
        run = FakeRun(command, environment, **self.script[len(self.started)])
        self.started.append(run)
        return run


def test_a_show_handed_over_starts_next_and_without_one_the_runs_code_is_the_end() -> None:
    runs = Runs({"hand": Path("/s/b.show")}, {"hand": Path("/s/c.show")}, {"code": 3})
    assert parent.run(FIRST, then, {"KEEP": "1"}, runs) == 3
    assert [run.command for run in runs.started] == [FIRST, then(Path("/s/b.show")),
                                                     then(Path("/s/c.show"))]  # fmt: skip
    files = {run.environment[parent.NEXT] for run in runs.started}
    assert len(files) == 1  # the same file for every run
    assert all(run.environment["KEEP"] == "1" for run in runs.started)
    folder = Path(files.pop()).parent
    assert not folder.exists()  # gone with the parent's last run


def test_the_hand_off_folder_is_private() -> None:
    seen: list[int] = []

    class Looking(FakeRun):
        def wait(self) -> int:
            seen.append(stat.S_IMODE(Path(self.environment[parent.NEXT]).parent.stat().st_mode))
            return 0

    assert parent.run(FIRST, then, {}, lambda c, e: Looking(c, e)) == 0
    assert seen == [0o700]


@pytest.mark.parametrize("code", [1, 70])
def test_a_run_that_did_not_end_well_starts_nothing_more(code: int) -> None:
    runs = Runs({"hand": Path("/s/b.show"), "code": code})
    assert parent.run(FIRST, then, {}, runs) == code
    assert len(runs.started) == 1


def test_a_run_a_signal_killed_ends_with_128_and_the_signal() -> None:
    assert parent.run(FIRST, then, {}, Runs({"code": -signal.SIGKILL})) == 137


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGHUP])
def test_sigterm_and_sighup_are_passed_on_and_then_nothing_starts(number: int) -> None:
    before = signal.getsignal(number)
    runs = Runs({"signal_parent": number, "hand": Path("/s/b.show")})
    assert parent.run(FIRST, then, {}, runs) == 0
    (run,) = runs.started
    assert run.signals == [number]
    assert signal.getsignal(number) is before  # put back


def test_sigint_is_let_through_to_nobody_while_a_run_goes() -> None:
    before = signal.getsignal(signal.SIGINT)
    runs = Runs({"signal_parent": signal.SIGINT})
    assert parent.run(FIRST, then, {}, runs) == 0  # no KeyboardInterrupt
    (run,) = runs.started
    assert run.signals == []
    assert callable(run.sigint)  # a handler, not SIG_IGN, which the run would inherit
    assert signal.getsignal(signal.SIGINT) is before


def test_the_hand_off_file(tmp_path: Path) -> None:
    file = tmp_path / "next.json"
    assert not parent.hand_off(Path("/s/b.show"), {})  # no parent
    assert parent.hand_off(Path("/s/b.show"), {parent.NEXT: str(file)})
    assert json.loads(file.read_text()) == {"open": "/s/b.show"}
    assert [path.name for path in tmp_path.iterdir()] == ["next.json"]  # written whole
    assert parent.read_next(file) == Path("/s/b.show")
    assert not file.exists()  # read once
    assert parent.read_next(file) is None
    for text in ("{", "[]", '{"open": 3}', '{"open": ""}'):
        file.write_text(text)
        assert parent.read_next(file) is None
        assert not file.exists()


# ------------------------------------------------------------ real processes

PARENT = """
import os, sys
from busk_tui import parent
child = [sys.executable, "-c", sys.argv[1]]
sys.exit(parent.run(child, lambda show: child, dict(os.environ)))
"""

WAITS = """
import signal, sys, time
signal.signal(signal.SIGTERM, lambda n, f: sys.exit(3))
print("ready", signal.getsignal(signal.SIGINT) is signal.default_int_handler, flush=True)
time.sleep(30)
"""


def start_parent(child: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", PARENT, child], stdout=subprocess.PIPE, text=True
    )


def test_a_real_parent_ignores_sigint_and_passes_sigterm_on() -> None:
    process = start_parent(WAITS)
    try:
        assert process.stdout is not None
        assert process.stdout.readline().split() == ["ready", "True"]  # Ctrl+C is the run's
        process.send_signal(signal.SIGINT)
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(0.3)
        process.send_signal(signal.SIGTERM)
        assert process.wait(10) == 3  # the run's code: it took the SIGTERM
    finally:
        process.kill()
        process.wait()


def test_a_real_run_killed_ends_the_parent_with_128_and_the_signal() -> None:
    process = start_parent("import os, signal; os.kill(os.getpid(), signal.SIGKILL)")
    assert process.wait(10) == 128 + signal.SIGKILL
