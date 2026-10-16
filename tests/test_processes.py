"""``busk run`` as three processes: root, engine and console (phase-7-plan §5.1, §5.6, §5.9).

Real process trees (:mod:`process_harness`), the Phase 1 demo with its sACN
route sent to a localhost receiver.
"""

from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from builders import DEMO, load_doc, localhost_route
from process_harness import SITE, BuskRun, alive, wait_gone
from sacn_receiver import Receiver

pytestmark = pytest.mark.skipif(
    not hasattr(socket, "send_fds") or not Path("/proc").is_dir(),
    reason="the process tree needs descriptor passing, the harness /proc",
)

ENGINE = re.compile(
    r"^engine: (?P<ticks>\d+) ticks @ 100 Hz, \d+ overruns, max tick [\d.]+ ms, "
    r"(?P<commands>\d+) commands?, \d+ command errors?$"
)
ROUTE_COUNTS = re.compile(r"^sACN r1: (?P<packets>\d+) packets?, 0 errors$")


@pytest.fixture
def show(tmp_path: Path) -> Path:
    path = tmp_path / "demo.json"
    path.write_text(json.dumps(localhost_route(load_doc(DEMO))))
    return path


def test_quit_ends_the_tree_and_the_root_prints_the_statistics(
    show: Path, receiver: Receiver
) -> None:
    with BuskRun(show, sacn_port=receiver.port) as run:
        pids = run.children()
        run.send("status\n")
        run.wait_for("GM 100% | BO off")
        assert receiver.receive(5.0).data  # the root sends the engine's frames
        run.signal(signal.SIGINT)  # the root ignores Ctrl+C while a console lives
        run.send("blackout on\nstatus\n")
        run.wait_for("GM 100% | BO on")
        run.send("quit\n")
        assert run.wait() == 0, run.err
    assert wait_gone(list(pids.values()), 2.0)
    assert any(line.startswith("sACN r1: ") and "→" in line for line in run.out), run.out
    engine = next(m for line in run.out if (m := ENGINE.match(line)))
    assert int(engine["ticks"]) > 0
    assert int(engine["commands"]) >= 1  # blackout on
    counts = next(m for line in run.out if (m := ROUTE_COUNTS.match(line)))
    assert int(counts["packets"]) > 0
    packets = receiver.drain()
    assert packets
    assert packets[-1].terminated  # the output closed its stream at the end


def test_a_failing_script_exits_1(show: Path, tmp_path: Path) -> None:
    script = tmp_path / "bad.busk"
    script.write_text("gm 50%\nno such command\n")
    with BuskRun(show, "--script", str(script)) as run:
        pids = run.children()
        assert run.wait() == 1
    assert wait_gone(list(pids.values()), 2.0)


def test_sigterm_to_the_root_stops_in_order(show: Path, receiver: Receiver) -> None:
    with BuskRun(show, sacn_port=receiver.port) as run:
        run.children()
        receiver.receive(5.0)
        run.send("status\n")
        run.wait_for("GM 100% | BO off")  # the console's command loop runs
        run.signal(signal.SIGTERM)
        assert run.wait() == 0, run.err
    assert any(ENGINE.match(line) for line in run.out), run.out
    packets = receiver.drain()
    assert packets[-1].terminated


def test_kill_9_of_the_root_ends_both_children_within_a_second(show: Path) -> None:
    with BuskRun(show) as run:
        pids = run.children()
        run.send("status\n")
        run.wait_for("GM 100% | BO off")
        run.signal(signal.SIGKILL)
        run.process.wait(5)
        assert wait_gone(list(pids.values()), 1.0), [pid for pid in pids.values() if alive(pid)]


def test_duration_console_frames_and_stats(show: Path, tmp_path: Path) -> None:
    stats = tmp_path / "stats.jsonl"
    with BuskRun(show, "--duration", "1.5", "--console", "--stats", str(stats)) as run:
        run.close_stdin()  # with --duration, the end of stdin does not quit
        pids = run.children()
        assert run.wait() == 0, run.err
    assert any(line.startswith("[frame ") and " U1 " in line for line in run.out), run.out
    assert any(ENGINE.match(line) for line in run.out)
    records = [json.loads(line) for line in stats.read_text().splitlines()]
    assert len(records) >= 2
    for record in records:
        assert set(record) == {"time", "engine", "console", "root", "routes"}
        assert record["engine"]["pid"] == pids["engine"]
        assert record["console"]["pid"] == pids["console"]
        assert record["root"]["lateCycles"] >= 0
    assert any(record["engine"]["state"] == "running" for record in records)
    assert any([route["id"] for route in record["routes"]] == ["r1"] for record in records)


def test_start_up_lines_match_the_threads_layout(show: Path, receiver: Receiver) -> None:
    def lines(*extra: str) -> tuple[set[str], set[str]]:
        result = subprocess.run(
            [sys.executable, "-m", "busk", "run", str(show), "--duration", "0.5", *extra],
            input="",
            capture_output=True,
            text=True,
            timeout=60,
            env={**_env(), "BUSK_TEST_SACN_PORT": str(receiver.port)},
            check=False,
        )
        assert result.returncode == 0, result.stderr
        out = {
            line
            for line in result.stdout.splitlines()
            if not ENGINE.match(line) and not ROUTE_COUNTS.match(line)
        }
        return out, set(result.stderr.splitlines())

    assert lines() == lines("--threads")


def _env() -> dict[str, str]:
    paths = [str(SITE), os.environ.get("PYTHONPATH", "")]
    return {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in paths if p)}


def info_until(run: BuskRun, wanted: str, timeout: float = 20.0) -> list[str]:
    """Type ``info`` every 0.3 s until its reply has the line ``wanted``;
    return the stdout lines from that ``info`` on."""
    deadline = time.monotonic() + timeout
    while True:
        since = run.mark()
        run.send("info\n")
        try:
            run.wait_for(wanted, since=since, timeout=0.3)
            return run.out[since:]
        except TimeoutError:
            if time.monotonic() > deadline:
                raise


def test_info_names_the_three_processes_and_counts_restarts(show: Path, receiver: Receiver) -> None:
    """``info`` ends with the pids the root sent (``PROCESSES``) and the
    restarts so far; an engine restart updates both."""
    with BuskRun(show, sacn_port=receiver.port) as run:
        pids = run.children()
        lines = info_until(run, "restarts: engine 0, console 0")
        assert (
            f"processes: root {run.pid}, engine {pids['engine']}, console {pids['console']}"
            in lines
        )
        os.kill(pids["engine"], signal.SIGKILL)
        engine = run.children(besides=pids["engine"])["engine"]
        lines = info_until(run, "restarts: engine 1, console 0")
        assert f"processes: root {run.pid}, engine {engine}, console {pids['console']}" in lines
        run.send("quit\n")
        assert run.wait() == 0, run.err
