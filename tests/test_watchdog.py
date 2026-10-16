"""The root's watchdog and engine restarts (phase-7-plan decisions 4–6, §5.6, §6 step 9).

Real process trees (:mod:`process_harness`): Appendix A with its sACN route
sent to a localhost receiver, whose packets a
:class:`~process_harness.Collector` timestamps.
"""

from __future__ import annotations

import itertools
import json
import os
import signal
import socket
import time
from pathlib import Path
from typing import Any

import pytest

from builders import APPENDIX_A, compile_doc, load_doc, localhost_route
from process_harness import BuskRun, Collector
from sacn_receiver import Receiver

pytestmark = pytest.mark.skipif(
    not hasattr(socket, "send_fds") or not Path("/proc").is_dir(),
    reason="the process tree needs descriptor passing, the harness /proc",
)

KEEPALIVE_SLACK = 1.2
"""The longest gap allowed between two packets of the universe: sACN's
0.9 s keep-alive, plus scheduling slack."""


def write(tmp_path: Path, **output: Any) -> tuple[Path, dict[str, Any]]:
    doc = localhost_route(load_doc(APPENDIX_A))
    doc["output"].update(output)
    path = tmp_path / "club.json"
    path.write_text(json.dumps(doc))
    return path, doc


def lit(run: BuskRun) -> None:
    """Play the static Blue look (playback 3) and wait for the engine to show it."""
    run.send("go 3\nstatus\n")
    run.wait_for(lambda line: line.endswith("| 3 Blue on"))


def test_a_killed_engine_comes_back_with_the_same_frame_and_no_gap(
    tmp_path: Path, receiver: Receiver
) -> None:
    show, _ = write(tmp_path)
    collector = Collector(receiver)
    with BuskRun(show, sacn_port=receiver.port) as run:
        engine = run.children()["engine"]
        lit(run)
        before = collector.settle()
        os.kill(engine, signal.SIGKILL)
        run.wait_for("engine: restarted (killed by signal 9)", stderr=True)
        run.wait_for("engine back: restored 1 playback, 2 master levels, page 1")
        run.children(besides=engine)
        time.sleep(0.5)
        after = collector.settle()
        run.send("quit\n")
        assert run.wait() == 0, run.err
    packets = [(at, p) for at, p in collector.stop() if not p.terminated]
    assert after == before
    for (t0, p0), (t1, p1) in itertools.pairwise(packets):
        assert p1.sequence == (p0.sequence + 1) % 256  # the root's stream never restarted
        assert t1 - t0 < KEEPALIVE_SLACK
    assert any(line.endswith(", 1 restart") for line in run.out), run.out


def test_stats_lines_never_give_a_new_engine_the_old_ones_counters(
    tmp_path: Path, receiver: Receiver
) -> None:
    """Found by the soak (step 19): until the new engine's first ``STATS``,
    the ``--stats`` lines paired its pid with the killed engine's ticks."""
    show, _ = write(tmp_path)
    stats = tmp_path / "stats.jsonl"
    with BuskRun(show, "--stats", str(stats), sacn_port=receiver.port) as run:
        engine = run.children()["engine"]
        lit(run)
        time.sleep(3.5)  # lines with the first engine's counters, past the next one's first
        os.kill(engine, signal.SIGKILL)
        run.wait_for("engine: restarted (killed by signal 9)", stderr=True)
        run.children(besides=engine)
        time.sleep(2.5)  # the new engine's first STATS, and a line after it
        run.send("quit\n")
        assert run.wait() == 0, run.err
    records = [json.loads(line)["engine"] for line in stats.read_text().splitlines()]
    assert len({r["pid"] for r in records}) == 2
    counted = [r for r in records if r["ticks"] is not None]
    for previous, record in itertools.pairwise(counted):
        if record["pid"] == previous["pid"]:
            assert record["ticks"] >= previous["ticks"], (previous, record)


def test_a_command_in_the_gap_follows_the_restore_and_a_second_restart_skips_it(
    tmp_path: Path, receiver: Receiver
) -> None:
    show, _ = write(tmp_path)
    with BuskRun(show, sacn_port=receiver.port) as run:
        engine = run.children()["engine"]
        lit(run)
        os.kill(engine, signal.SIGKILL)
        # Typed once the console knows: a command written to the link in the
        # moment before it notices the engine died is lost with it.
        run.status_until("engine restarting")
        run.send("blackout on\n")  # queued while no engine runs
        run.wait_for(lambda line: line.startswith("engine back: restored"))
        engine = run.children(besides=engine)["engine"]
        run.status_until(lambda line: line.startswith("GM 100% | BO on") and "3 Blue on" in line)
        # Within RESTORE_GUARD of that restore: the next engine starts clean.
        os.kill(engine, signal.SIGKILL)
        run.wait_for("engine back: nothing restored (it restarted within 10 s of the last restore)")
        run.status_until("GM 100% | BO off | P1 Main | Speed 1 120 BPM ×1")
        run.send("quit\n")
        assert run.wait() == 0, run.err


def test_a_stopped_engine_stalls_at_1_s_and_restarts_at_3_s(
    tmp_path: Path, receiver: Receiver
) -> None:
    show, _ = write(tmp_path)
    with BuskRun(show, sacn_port=receiver.port) as run:
        engine = run.children()["engine"]
        lit(run)
        os.kill(engine, signal.SIGSTOP)
        stopped = time.monotonic()
        run.wait_for("engine: no new frame for 1.0 s; holding the last frame", stderr=True)
        stalled = time.monotonic() - stopped
        run.status_until("engine stalled", timeout=1.5)
        run.wait_for("engine: restarted (no new frame for 3 s)", stderr=True)
        restarted = time.monotonic() - stopped
        run.wait_for(lambda line: line.startswith("engine back: restored"))
        assert run.children(besides=engine)["engine"] != engine
        run.send("quit\n")
        assert run.wait() == 0, run.err
    assert 0.9 <= stalled < 2.0
    assert 2.9 <= restarted < 4.5


def test_without_hold_a_stalled_engine_turns_intensity_off(
    tmp_path: Path, receiver: Receiver
) -> None:
    show, doc = write(tmp_path, holdLastFrameOnEngineStall=False)
    layout = compile_doc(doc).layout
    collector = Collector(receiver)
    first = int(layout.darkPositions[0])  # MH 1's dimmer
    with BuskRun(show, sacn_port=receiver.port) as run:
        engine = run.children()["engine"]
        run.send("sel group 1\nset intensity 1\n")  # MH 1 and 2 at full
        deadline = time.monotonic() + 10
        while not (collector.packets and collector.latest()[first]):
            assert time.monotonic() < deadline, "never lit"
            time.sleep(0.05)
        before = collector.settle()
        os.kill(engine, signal.SIGSTOP)
        run.wait_for("engine: no new frame for 1.0 s; intensity off", stderr=True)
        time.sleep(0.2)
        dark = collector.latest()
        os.kill(engine, signal.SIGKILL)  # let the test end without the restart
        run.send("quit\n")
        run.wait()
    collector.stop()
    positions = [int(p) for p in layout.darkPositions]  # one universe: row 0
    assert [dark[p] for p in positions] == [int(v) for v in layout.darkValues]
    assert [before[p] for p in positions] != [dark[p] for p in positions]
    unlit = set(range(512)) - set(positions)
    assert all(dark[k] == before[k] for k in unlit)  # heads stay where they are


def test_the_watchdog_gives_up_after_three_restarts_in_a_minute(
    tmp_path: Path, receiver: Receiver
) -> None:
    show, _ = write(tmp_path)
    collector = Collector(receiver)
    with BuskRun(show, sacn_port=receiver.port) as run:
        engine = run.children()["engine"]
        lit(run)
        for _ in range(3):
            os.kill(engine, signal.SIGKILL)
            engine = run.children(besides=engine)["engine"]
        os.kill(engine, signal.SIGKILL)
        run.wait_for(
            lambda line: line.startswith("engine: killed by signal 9; given up after 3 restarts"),
            stderr=True,
        )
        given_up = time.monotonic()
        run.status_until("engine failed")
        time.sleep(2.0)
        run.send("quit\n")
        assert run.wait() == 70
    late = [p for at, p in collector.stop() if at > given_up + 0.5]
    assert len(late) >= 2  # keep-alives of the held frame
    assert late[-1].terminated
