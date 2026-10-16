"""Console restarts (phase-7-plan decisions 7–8, §5.8, §6 step 10).

Real process trees (:mod:`process_harness`): Appendix A with its sACN route
sent to a localhost receiver. The tests kill the console with ``SIGKILL``;
the root starts a new one with ``--restarted``, which adopts the engine
that kept running. Its recovered show either has the stamp of the engine's
show (only the programmer goes to the engine) or not: then the show on
stage goes back to the last autosave, through the engine's own remap when
the slots changed. Beyond 3 restarts in 60 s the root gives the console
up, and the show runs on until Ctrl+C.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import time
from pathlib import Path
from typing import Any

import pytest

from builders import APPENDIX_A, load_doc, localhost_route
from process_harness import BuskRun, Collector, alive
from sacn_receiver import Receiver
from ws_client import WsClient

pytestmark = pytest.mark.skipif(
    not hasattr(socket, "send_fds") or not Path("/proc").is_dir(),
    reason="the process tree needs descriptor passing, the harness /proc",
)

BANNER = "busk console: restarted after a crash (killed by signal 9); type 'help'"
"""What a restarted console says first."""

WENT_BACK = "engine: running on; its show went back to the last autosave (later edits are lost)"
"""What a restarted console says when the engine ran a newer show than it recovered."""

PAR_202 = 199
"""The first DMX byte (index) of a par added at 1.200."""


def write(tmp_path: Path, web_port: int | None = None) -> Path:
    """Appendix A with its route to the receiver, a pulse that lights the
    moving heads by itself (``absolute``, not ``multiply``), and with
    ``web_port`` a phone remote."""
    doc: dict[str, Any] = localhost_route(load_doc(APPENDIX_A))
    doc["effects"][0]["layers"][0]["mode"] = "absolute"
    if web_port is not None:
        doc["surfaces"].append(
            {
                "id": "s-web",
                "name": "Phone",
                "kind": "web",
                "match": {"port": web_port, "host": "127.0.0.1"},
                "faderPickup": "jump",
            }
        )
    path = tmp_path / "club.json"
    path.write_text(json.dumps(doc))
    return path


def free_port() -> int:
    """A localhost TCP port that nothing listens on now."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def restart(run: BuskRun, console: int) -> int:
    """Kill the console; the new one's process id, once it said its banner."""
    since = run.mark()
    os.kill(console, signal.SIGKILL)
    run.wait_for(BANNER, since=since)
    return run.children(besides=console)["console"]


def blue(run: BuskRun) -> None:
    """Play the static Blue look (playback 3) with its master fader up, so
    intensities recorded into it show, and wait for the engine to show it."""
    run.send("go 3\nfader 3 1\nstatus\n")
    run.wait_for(lambda line: line.endswith("| 3 Blue on 1.00"))


def until(test: Any, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not test():
        assert time.monotonic() < deadline, "not in time"
        time.sleep(0.02)


def test_a_killed_console_comes_back_while_the_show_runs_on(
    tmp_path: Path, receiver: Receiver, state_directory: Path
) -> None:
    port = free_port()
    show = write(tmp_path, web_port=port)
    collector = Collector(receiver)
    web_line = f"Web s-web: http://127.0.0.1:{port}/?k="
    with BuskRun(show, sacn_port=receiver.port) as run:
        console = run.children()["console"]
        run.wait_for(lambda line: line.startswith(web_line))
        key = (state_directory / "web-key").read_text().strip()
        run.send("go 6\nfader 6 1\nstatus\n")
        run.wait_for(lambda line: line.endswith("| 6 Slow Pulse on 1.00"))
        phone = WsClient(port, key)
        assert [json.loads(phone.recv_text())["type"] for _ in range(3)] == [
            "hello",
            "show",
            "state",
        ]
        time.sleep(1.0)  # the pulse has grown in (sizeFadeIn 1 s)
        since = run.mark()
        killed = time.monotonic()
        os.kill(console, signal.SIGKILL)
        run.wait_for(BANNER, since=since)
        run.wait_for("console: restarted (killed by signal 9)", stderr=True)
        run.wait_for("engine: running on with the same show", since=since)  # equal stamps
        run.children(besides=console)
        # It adopted the engine: the pulse plays on at full size.
        run.status_until(lambda line: line.endswith("| 6 Slow Pulse on 1.00"))
        back = time.monotonic()
        # The phone's page reconnects by itself; the new console serves it.
        run.wait_for(lambda line: line.startswith(web_line), since=since)
        again = WsClient(port, key)
        messages = [json.loads(again.recv_text()) for _ in range(3)]
        assert [m["type"] for m in messages] == ["hello", "show", "state"]
        pulse = next(p for p in messages[2]["playbacks"] if p["id"] == "pb-pulse")
        assert pulse["state"] == "active"
        again.close()
        phone.close()
        run.send("quit\n")
        assert run.wait() == 0, run.err
    packets = [(at, p.data) for at, p in collector.stop() if not p.terminated]
    start = killed
    while start + 0.25 <= back:  # the pulse moved in every quarter second meanwhile
        assert len({data for at, data in packets if start <= at < start + 0.25}) >= 2, (
            f"no change {start - killed:.2f} s after the kill"
        )
        start += 0.25


def test_an_edit_not_yet_autosaved_is_undone_on_stage(tmp_path: Path, receiver: Receiver) -> None:
    show = write(tmp_path)
    collector = Collector(receiver)
    with BuskRun(show, sacn_port=receiver.port) as run:
        console = run.children()["console"]
        blue(run)
        before = collector.settle()
        edited_at = time.monotonic()
        run.send("sel group 1\nset intensity 1\nrecord cue 10/1 merge\nclear\n")
        until(lambda: collector.latest() != before)
        edited = collector.settle()  # Blue now lights the heads (after its 1 s fade)
        time.sleep(1.2)  # session.json has the cleared programmer
        # The show autosave comes 5 s after the edit: the console dies before.
        assert time.monotonic() - edited_at < 4.5
        restart(run, console)
        run.wait_for(WENT_BACK)
        time.sleep(1.2)  # Blue fades back to the recovered cue in 1 s
        after = collector.settle()
        run.status_until(lambda line: line.endswith("| 3 Blue on 1.00"))
        run.send("quit\n")
        assert run.wait() == 0, run.err
    collector.stop()
    assert edited != before
    assert after == before


def test_a_patch_not_yet_autosaved_is_undone_through_the_engines_remap(
    tmp_path: Path, receiver: Receiver
) -> None:
    show = write(tmp_path)
    collector = Collector(receiver)
    with BuskRun(show, sacn_port=receiver.port) as run:
        console = run.children()["console"]
        blue(run)
        before = collector.settle()
        patched_at = time.monotonic()
        # A new fixture: new slot keys, which the restarted console never saw.
        run.send(
            'fixture add 202 "RGB Par 3ch" mode "3ch" at 1.200\n'
            "sel fixture 202\nset intensity 1\nset color 1 0 0\n"
        )
        until(lambda: collector.latest()[PAR_202] == 255)
        time.sleep(1.2)  # session.json has the programmer on the new par
        assert time.monotonic() - patched_at < 4.5  # before the show autosave
        restart(run, console)
        run.wait_for(WENT_BACK)  # its programmer values stay, on a fixture that is gone
        until(lambda: collector.latest()[PAR_202] == 0)
        after = collector.settle()
        run.status_until(lambda line: line.endswith("| 3 Blue on 1.00"))  # on its remapped lanes
        run.send("quit\n")
        assert run.wait() == 0, run.err
    collector.stop()
    assert after == before


def test_the_root_gives_the_console_up_after_three_restarts_in_a_minute(
    tmp_path: Path, receiver: Receiver
) -> None:
    show = write(tmp_path)
    collector = Collector(receiver)
    with BuskRun(show, sacn_port=receiver.port) as run:
        children = run.children()
        console, engine = children["console"], children["engine"]
        run.send("go 6\nfader 6 1\nstatus\n")
        run.wait_for(lambda line: line.endswith("| 6 Slow Pulse on 1.00"))
        for _ in range(3):
            console = restart(run, console)
        os.kill(console, signal.SIGKILL)
        run.wait_for(
            "console: killed by signal 9; given up after 3 restarts in 60 s; "
            "the show runs on, Ctrl+C stops it",
            stderr=True,
        )
        given_up = time.monotonic()
        time.sleep(1.5)
        assert alive(engine)  # the same engine all along
        run.signal(signal.SIGINT)
        assert run.wait() == 70
    late = [p for at, p in collector.stop() if at > given_up]
    assert len({p.data for p in late if not p.terminated}) > 10  # the pulse ran on
    assert late[-1].terminated  # Ctrl+C stopped the output in order
