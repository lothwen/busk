"""GAP-11 of ``docs/dev/tui/engine-gaps.md``: a frontend on ``busk run``.

* **The carry.** The engine process sends a console what it watches besides
  snapshots: the console publisher's :class:`_Watched` (only what is watched
  and new; an output capture only of the newest show; captures paced, every
  frame sent), then a
  :class:`RemoteBus` against an engine host in this process (frames with
  their layout, output captures read with the console's own show, effect
  snapshots; a capture of a show the console has replaced is skipped; a new
  engine is asked again, a new console link watches nothing).
* **The attached show** reads them through its link: ``busk run
  --threads``'s :class:`LocalEngine`, and the console process's
  :class:`RemoteBus`.
* **``busk run --frontend``**, real process trees running
  ``tests/process_site/frontend_probe.py``: the frontend gets the show
  (frames, output, effects, routes, the programmer, the effect templates,
  lines that run, a profile's category, the playbacks' colours) and busk run's lines as
  ``busk.run`` records, none printed
  over it; one that raises is restarted with its console while the engine
  runs on; ``SIGTERM`` ends the run through it; with ``--threads`` too. A
  frontend that cannot be loaded ends the run with 1; the options it cannot
  be combined with are refused.
* **The lines**: ``say`` and ``warn`` diverted, the root's ``NEWS`` and
  the engine's stderr, the console process saying ``NEWS``.
"""

from __future__ import annotations

import io
import json
import logging
import os
import signal
import socket
import threading
import types
from collections.abc import Iterator
from pathlib import Path
from typing import NoReturn

import numpy as np
import pytest

import test_route_status
from builders import APPENDIX_A, load_doc, localhost_route
from busk import LiveShow
from busk.cli import main
from busk.compiler.compile import CompiledShow, compile_show
from busk.engine.clock import FakeClock, MonotonicClock
from busk.engine.install import EMPTY_FRAME, Install
from busk.engine.link import LocalEngine
from busk.engine.loop import Engine
from busk.engine.readout import read_output
from busk.engine.snapshot import EffectSnapshot
from busk.model.show import Show
from busk.process import console_host
from busk.process.console_host import ProcessBackend, _load_frontend
from busk.process.engine_host import WATCH_S, _Watched
from busk.process.links import RemoteBus
from busk.process.options import RunOptions
from busk.process.report import diverted, logged, say, warn
from busk.process.root import Root, relay
from busk.process.wire import (
    Endpoint,
    Kind,
    OutputCapture,
    Watch,
    Welcome,
    dumps,
    loads,
    receive,
    send,
)
from busk.session.library import ProfileLibrary
from process_harness import BuskRun
from sacn_receiver import Receiver
from test_links import Host, appendix, command, until

STAMP = ("console-1", 0)
BLUE = (0.0, 0.0, 1.0)


@pytest.fixture
def hosts() -> Iterator[list[Host]]:
    """Engine hosts in this process, stopped at the end, as in ``test_links``."""
    made: list[Host] = []
    yield made
    for host in made:
        if host.thread.is_alive():
            host.stop()


def remote(compiled: CompiledShow) -> RemoteBus:
    """A console's bus for ``compiled``, stamped as the CLI stamps it."""
    return RemoteBus(compiled, MonotonicClock(), sessionId="console-1", stamp=STAMP)


def attached(link: LocalEngine | RemoteBus, show: Show, compiled: CompiledShow) -> LiveShow:
    """``busk run``'s show on ``link``, as its console makes it."""
    return LiveShow._attached(
        show,
        compiled,
        link,
        FakeClock(),
        path=Path("unused.show"),
        library=ProfileLibrary(),
        state_dir=Path("unused"),
        dirty=False,
        stamp=STAMP,
        causes=False,
        iface="lo",
        status=lambda: "",
        about=lambda: (),
        poll=lambda: None,
        routes=lambda: None,
        say=lambda text: None,
        warn=lambda text: None,
    )


# --------------------------------------------------------------- the carry


class Sent:
    """An :class:`Endpoint` stand-in that keeps the kinds it is sent."""

    def __init__(self) -> None:
        self.kinds: list[Kind] = []
        self.payloads: list[bytes] = []

    def send(self, kind: Kind, payload: bytes = b"") -> None:
        self.kinds.append(kind)
        self.payloads.append(payload)

    def taken(self) -> list[Kind]:
        kinds, self.kinds = self.kinds, []
        return kinds


def test_the_publisher_sends_what_is_watched_once_and_output_only_of_the_newest_show() -> None:
    _, compiled = appendix()
    engine = Engine(compiled, FakeClock())
    engine.captureOutput = engine.captureEffects = True
    engine.tick(0.0)
    watched, link = _Watched(), Sent()
    everything = Watch(frames=True, output=True, effects=True)
    watched.send(link, engine, Watch(), compiled, STAMP, 0.0)
    assert link.taken() == []  # nothing watched, nothing sent …
    assert (engine.captureOutput, engine.captureEffects) == (False, False)  # … nor captured
    watched.send(link, engine, everything, compiled, STAMP, 0.0)
    assert link.taken() == [Kind.LAYOUT, Kind.FRAME, Kind.OUTPUT, Kind.EFFECTS]
    capture: OutputCapture = loads(link.payloads[2])
    assert (capture.seq, capture.stamp) == (1, STAMP)
    assert isinstance(loads(link.payloads[3]), EffectSnapshot)  # read in the engine process
    watched.send(link, engine, everything, compiled, STAMP, 0.01)
    assert link.taken() == []  # nothing new since


def test_the_publisher_paces_the_captures_and_sends_every_frame() -> None:
    _, compiled = appendix()
    engine = Engine(compiled, FakeClock())
    watched, link = _Watched(), Sent()
    everything = Watch(frames=True, output=True, effects=True)
    watched.send(link, engine, everything, compiled, STAMP, 0.0)
    assert (engine.captureOutput, engine.captureEffects) == (True, True)  # the first ones at once
    engine.tick(0.0)
    watched.send(link, engine, everything, compiled, STAMP, 0.0)
    assert link.taken() == [Kind.LAYOUT, Kind.FRAME, Kind.OUTPUT, Kind.EFFECTS]
    assert (engine.captureOutput, engine.captureEffects) == (False, False)  # paused …
    engine.tick(0.01)
    watched.send(link, engine, everything, compiled, STAMP, 0.01)
    assert link.taken() == [Kind.FRAME]  # … while frames go after every tick
    watched.send(link, engine, everything, compiled, STAMP, WATCH_S)
    assert (engine.captureOutput, engine.captureEffects) == (True, True)  # … until WATCH_S later
    engine.tick(WATCH_S)
    watched.send(link, engine, everything, compiled, STAMP, WATCH_S + 0.01)
    assert link.taken() == [Kind.FRAME, Kind.OUTPUT, Kind.EFFECTS]
    watched.send(link, engine, everything, compiled, STAMP, 1.0)
    engine.tick(1.0)
    newer = compile_show(appendix()[0])  # installed, not yet run
    watched.send(link, engine, everything, newer, ("console-1", 1), 1.0)
    assert link.taken() == [Kind.FRAME, Kind.EFFECTS]  # no capture of an older show


def test_nothing_but_snapshots_comes_until_the_console_watches(hosts: list[Host]) -> None:
    _, compiled = appendix()
    bus = remote(compiled)
    hosts.append(host := Host())
    host.attach(bus)
    until(lambda: bus.snapshot is not None and host.engine.stats.ticks > 5)
    assert (bus.frame, bus.output, bus.effects) == (None, None, None)
    assert not host.engine.captureOutput
    assert not host.engine.captureEffects


def test_watched_frames_come_with_their_layout(hosts: list[Host]) -> None:
    _, compiled = appendix()
    bus = remote(compiled)
    hosts.append(host := Host())
    host.attach(bus)
    bus.watch(frames=True)
    until(lambda: bus.frame is not None)
    first = bus.frame
    assert first is not None
    assert first.layout is not None
    assert first.compiled is None  # made in another process
    assert [universe.number for universe in first.layout.universes] == [1]
    assert [len(universe) for universe in first.universes] == [512]
    until(lambda: bus.frame is not None and bus.frame.seq > first.seq)  # the newest, tick by tick
    assert (bus.output, bus.effects) == (None, None)  # only what is watched
    assert not host.engine.captureOutput


def test_a_watched_output_is_read_with_the_consoles_own_show(hosts: list[Host]) -> None:
    _, compiled = appendix()
    bus = remote(compiled)
    hosts.append(host := Host())
    host.attach(bus)
    bus.watch(output=True)
    bus.submit(command(type="TRIGGER_PLAYBACK", playbackId="pb-blue"))

    def blue() -> bool:
        captured = bus.output
        return captured is not None and read_output(captured).fixtures[0].color == BLUE

    until(blue)
    captured = bus.output
    assert captured is not None
    assert captured.compiled is compiled  # the console's, with its readout lookups
    latest = host.engine.latest
    assert latest is not None
    assert latest.compiled is not compiled
    first = read_output(captured).fixtures[0]
    assert (first.number, first.source["color"], first.playback) == (101, "playback", None)
    assert bus.frame is None
    assert bus.effects is None


def test_watched_effects_come_read(hosts: list[Host]) -> None:
    _, compiled = appendix()
    bus = remote(compiled)
    hosts.append(host := Host())
    host.attach(bus)
    bus.watch(effects=True)
    bus.submit(command(type="TRIGGER_PLAYBACK", playbackId="pb-pulse"))
    until(lambda: bus.effects is not None and len(bus.effects.effects) == 1)
    effects = bus.effects
    assert isinstance(effects, EffectSnapshot)
    assert [(e.playback, e.cue, e.id) for e in effects.effects] == [(6, "1", "ei-1")]
    assert not host.engine.captureOutput  # only what is watched


def test_a_new_engine_is_asked_for_what_the_console_watches(hosts: list[Host]) -> None:
    _, compiled = appendix()
    bus = remote(compiled)
    hosts.append(first := Host())
    first.attach(bus)
    bus.watch(output=True, effects=True)
    until(lambda: bus.output is not None and bus.effects is not None)
    hosts.append(second := Host())  # the watchdog's new engine
    second.attach(bus)  # the first one's link is shut down: it sends nothing more
    until(lambda: bus.reconnects == 2)
    output, effects = bus.output, bus.effects
    until(lambda: bus.output is not output and bus.effects is not effects)  # the new engine's


def test_a_new_console_link_watches_nothing(hosts: list[Host]) -> None:
    _, compiled = appendix()
    bus = remote(compiled)
    hosts.append(host := Host())
    host.attach(bus)
    bus.watch(output=True)
    until(lambda: bus.output is not None)
    restarted = RemoteBus(
        compiled, MonotonicClock(), sessionId="console-2", restarted=True, stamp=STAMP
    )
    host.attach(restarted)  # the root's new console
    until(lambda: restarted.attached and not host.engine.captureOutput)
    assert restarted.output is None
    restarted.watch(output=True)
    until(lambda: restarted.output is not None)
    restarted.detach()


def test_a_capture_of_a_show_the_console_replaced_is_skipped() -> None:
    """The test plays the engine on the link."""
    _, compiled = appendix()
    bus = remote(compiled)
    console, engine = socket.socketpair()

    def drain() -> None:
        """Read what the bus sends (its HELLO, the install) until the end."""
        try:
            while receive(engine) is not None:
                pass
        except OSError:
            pass

    threading.Thread(target=drain, daemon=True).start()
    lanes = compiled.slots.laneCount

    def output(seq: int, stamp: tuple[str, int]) -> None:
        capture = OutputCapture(
            seq=seq,
            time=seq / 10,
            stamp=stamp,
            values=np.zeros(lanes),
            owners=np.full(lanes, -1, dtype=np.intp),
            origins=(),
        )
        send(engine, Kind.OUTPUT, dumps(capture))

    try:
        bus.attach(console)
        send(engine, Kind.WELCOME, dumps(Welcome(fresh=True)))
        until(lambda: bus.attached)
        output(1, STAMP)
        until(lambda: bus.output is not None)
        assert bus.output is not None
        assert bus.output.compiled is compiled
        newer = compile_show(appendix()[0])
        bus.install(Install(compiled=newer, remap=None, programmer=EMPTY_FRAME, stamp=("c", 1)))
        output(2, STAMP)  # a tick of the show the console replaced
        output(3, ("c", 1))
        until(lambda: bus.output is not None and bus.output.seq == 3)
        assert bus.output is not None
        assert bus.output.compiled is newer
        assert read_output(bus.output).fixtures[0].number == 101
    finally:
        bus.detach()
        engine.close()


# --------------------------------------------------------- the attached show


def test_busk_run_with_threads_reads_the_engine_it_runs() -> None:
    show, compiled = appendix()
    engine = Engine(compiled, FakeClock())
    live = attached(LocalEngine(engine), show, compiled)
    assert (live.frame, live.output, live.effects) == (None, None, None)  # no tick yet
    assert live.execute("go 3").ok
    engine.tick(0.0)
    engine.tick(5.0)  # after the cue's 1 s fade
    frame, output, effects = live.frame, live.output, live.effects
    assert frame is not None
    assert list(frame.universes) == [1]
    assert output is not None
    assert output.seq == frame.seq == 2
    assert output.fixtures[0].color == BLUE
    assert effects is not None
    assert effects.effects == ()


def test_busk_runs_console_process_reads_them_from_the_engine_process(hosts: list[Host]) -> None:
    show, compiled = appendix()
    bus = remote(compiled)
    live = attached(bus, show, compiled)
    hosts.append(host := Host())
    host.attach(bus)
    assert (live.frame, live.output, live.effects) == (None, None, None)  # the first reads ask
    assert live.execute("go 6").ok
    until(lambda: live.effects is not None and len(live.effects.effects) == 1)
    until(lambda: live.frame is not None and live.output is not None)
    frame, output = live.frame, live.output
    assert frame is not None
    assert output is not None
    assert list(frame.universes) == [1]
    assert len(frame.universes[1]) == 512
    assert [element.number for element in output.fixtures] == [101, 102, 201]


# ----------------------------------------------------- busk run --frontend


def run_show(tmp_path: Path) -> Path:
    show = tmp_path / "show.json"
    show.write_text(json.dumps(localhost_route(load_doc(APPENDIX_A))))
    return show


def plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **steps: object) -> Path:
    """Write the probe's plan (see ``frontend_probe``); its report's path."""
    report = tmp_path / "report.json"
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({**steps, "report": str(report)}))
    monkeypatch.setenv("BUSK_TEST_FRONTEND", str(path))
    return report


def frontend(tmp_path: Path, *options: str) -> tuple[str, ...]:
    return (*options, "--frontend", "frontend_probe:main", "--state-dir", str(tmp_path / "state"))


def test_busk_run_calls_the_frontend_with_its_show(
    tmp_path: Path, receiver: Receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = plan(
        tmp_path,
        monkeypatch,
        lines=[
            "go 6",
            "go 3",
            "sel fixture 101",
            "route add 1 sacn 7 unicast 127.0.0.1",
            'profile "RGB Par 3ch" category par',
        ],
        effectOf=6,
        colorOf=3,
        records=["universe 7"],  # the root's line for the new route
        routes=2,
    )
    with BuskRun(
        run_show(tmp_path), *frontend(tmp_path, "--no-log"), sacn_port=receiver.port
    ) as busk:
        assert busk.wait() == 0, busk.err
    report = json.loads(report_path.read_text())
    assert report["timeout"] is None, report
    assert report["calls"] == 1
    replies = report["replies"]
    assert [ok for _, _, ok in replies] == [True, True, True, True, True]
    assert report["frame"]["seq"] > 0
    assert report["frame"]["universes"] == {"1": 512}
    assert [number for number, _, _ in report["output"]["fixtures"]] == [101, 102, 201]
    assert report["effects"] == [[6, "1", "ei-1"]]
    route = replies[3][1].removeprefix("added route ")
    assert report["routes"] == [["r1", "ok"], [route, "ok"]]
    assert report["selection"] == [[101, 1]]
    assert report["templates"][:2] == [["Pulse", "show"], ["Circle", "library"]]
    assert report["categories"] == [["Generic Spot 16ch", None], ["RGB Par 3ch", "par"]]
    assert report["colors"] == [[1, None], [3, [0.0, 0.0, 1.0]], [6, None]]  # Blue; an effect
    said = [message for name, level, message in report["records"] if name == "busk.run"]
    assert any(message.startswith(f"sACN {route}: U1 Stage → universe 7") for message in said)
    assert not any(
        "universe 7" in line for line in busk.out + busk.err
    )  # nothing over the frontend


def test_a_frontend_that_raises_comes_back_with_its_console(
    tmp_path: Path, receiver: Receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = plan(tmp_path, monkeypatch, crash=True, records=["engine: running on"])
    with BuskRun(
        run_show(tmp_path), *frontend(tmp_path, "--no-log"), sacn_port=receiver.port
    ) as busk:
        assert busk.wait() == 0, busk.err
    report = json.loads(report_path.read_text())
    assert report["timeout"] is None, report
    assert report["calls"] == 2  # the restarted console called it again
    assert "RuntimeError: the probe crashes on its first call" in busk.err
    assert "console: restarted (exited with code 70)" in busk.err
    assert not any("engine: restarted" in line for line in busk.err)  # the engine ran on
    assert not any("engine: running on" in line for line in busk.out)  # said to the frontend


def test_sigterm_ends_the_run_through_the_frontend(
    tmp_path: Path, receiver: Receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The root passes it on, and the console raises it in the frontend's thread."""
    report_path = plan(tmp_path, monkeypatch, sleep=60)
    sleeping = tmp_path / "plan.sleeping"
    with BuskRun(
        run_show(tmp_path), *frontend(tmp_path, "--no-log"), sacn_port=receiver.port
    ) as busk:
        until(sleeping.exists, timeout=20.0)
        busk.signal(signal.SIGTERM)
        assert busk.wait(timeout=10.0) == 0, busk.err
    assert json.loads(report_path.read_text())["timeout"] is None
    assert not any("console: restarted" in line for line in busk.err)  # an end, not a crash


def test_busk_run_with_threads_gives_the_frontend_the_same(
    tmp_path: Path, receiver: Receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = plan(tmp_path, monkeypatch, lines=["go 3", "go 6"], effectOf=6)
    options = frontend(tmp_path, "--threads", "--no-log")
    with BuskRun(run_show(tmp_path), *options, sacn_port=receiver.port) as busk:
        assert busk.wait() == 0, busk.err
    report = json.loads(report_path.read_text())
    assert report["timeout"] is None, report
    assert report["frame"]["universes"] == {"1": 512}
    assert [number for number, _, _ in report["output"]["fixtures"]] == [101, 102, 201]
    assert report["effects"] == [[6, "1", "ei-1"]]
    assert report["routes"] == [["r1", "ok"]]


def test_a_frontend_that_cannot_be_loaded_ends_the_run_with_1(tmp_path: Path) -> None:
    options = ("--frontend", "no_such_frontend:main", "--state-dir", str(tmp_path / "state"))
    with BuskRun(run_show(tmp_path), *options, "--no-log") as busk:
        assert busk.wait() == 1
    assert (
        "busk: cannot load the frontend 'no_such_frontend:main': "
        "ModuleNotFoundError: No module named 'no_such_frontend'"
    ) in busk.err
    assert not any("restarted" in line for line in busk.err)  # not a crash: no restart


def test_a_frontend_name_must_name_a_function(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).parent / "process_site"))
    assert _load_frontend("frontend_probe:main") is not None
    assert _load_frontend("frontend_probe:WAIT_S") is None
    assert _load_frontend("frontend_probe:missing") is None
    err = capsys.readouterr().err.splitlines()
    assert err == [
        "busk: cannot load the frontend 'frontend_probe:WAIT_S': it is not callable",
        "busk: cannot load the frontend 'frontend_probe:missing': AttributeError: "
        "module 'frontend_probe' has no attribute 'missing'",
    ]


@pytest.mark.parametrize(
    ("options", "error"),
    [
        (["--frontend", "probe"], "argument --frontend: expected MODULE:FUNCTION: 'probe'"),
        (["--frontend", ":main"], "argument --frontend: expected MODULE:FUNCTION: ':main'"),
        (["--frontend", "m:f", "--console"], "--frontend cannot be combined with --console"),
        (
            ["--frontend", "m:f", "--no-console", "--duration", "1"],
            "--frontend cannot be combined with --no-console, --duration",
        ),
    ],
)
def test_busk_run_refuses_a_frontend_it_cannot_run(
    options: list[str], error: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_:
        main(["run", "x.show", *options])
    assert exit_.value.code == 2
    assert capsys.readouterr().err.splitlines()[-1].endswith(f": error: {error}")


# ----------------------------------------------------------------- the lines


def test_lines_go_where_they_are_diverted(capsys: pytest.CaptureFixture[str]) -> None:
    taken: list[tuple[bool, str]] = []

    def take(failed: bool, text: str) -> bool:
        taken.append((failed, text))
        return text != "refused"

    with diverted(take):
        say("news")
        warn("a failure")
        warn("refused")  # printed after all
    say("printed")
    assert taken == [(False, "news"), (True, "a failure"), (True, "refused")]
    assert capsys.readouterr() == ("printed\n", "refused\n")


def test_lines_logged_are_busk_run_records(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="busk")
    with diverted(logged):
        say("sACN r1: sending again")
        warn("engine: restarted (killed by signal 9)")
    assert [(r.name, r.levelname, r.getMessage()) for r in caplog.records] == [
        ("busk.run", "INFO", "sACN r1: sending again"),
        ("busk.run", "WARNING", "engine: restarted (killed by signal 9)"),
    ]


def test_the_root_sends_its_lines_to_the_console_while_there_is_one(tmp_path: Path) -> None:
    root = Root(RunOptions(show=tmp_path / "unused.show", no_log=True, frontend="m:f"), [])
    assert not root._forward(True, "engine: restarted (killed by signal 9)")  # no console yet
    ours, console = socket.socketpair()
    root._console_control = Endpoint(ours)
    try:
        assert root._forward(True, "engine: restarted (killed by signal 9)")
        message = receive(console)
        assert message is not None
        assert message.kind == Kind.NEWS
        assert loads(message.payload) == (True, "engine: restarted (killed by signal 9)")
        ours.close()  # the console is gone: its link was closed
        assert not root._forward(False, "sACN r1: sending again")
    finally:
        console.close()
        root._scheduler.close()


def test_the_engines_stderr_is_relayed_line_by_line() -> None:
    taken: list[tuple[bool, str]] = []
    stream = io.BytesIO(b"engine: bad COMMAND message from the console\nTraceback \xff\n")
    with diverted(lambda failed, text: taken.append((failed, text)) is None):
        relay(stream)
    assert taken == [
        (True, "engine: bad COMMAND message from the console"),
        (True, "Traceback �"),
    ]
    assert stream.closed


def test_the_console_process_says_the_roots_news(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control link's reader, run on the test's thread, as in
    ``test_route_status``: no thread is started, and the end of file that
    ends the process raises instead."""

    def exit_(code: int) -> NoReturn:
        raise test_route_status.Exited(code)

    fake = types.SimpleNamespace(
        Thread=lambda **kwargs: types.SimpleNamespace(start=lambda: None), Lock=threading.Lock
    )
    monkeypatch.setattr(console_host, "threading", fake)
    monkeypatch.setattr(os, "_exit", exit_)
    control, root = socket.socketpair()
    link, engine = socket.socketpair()
    taken: list[tuple[bool, str]] = []
    try:
        backend = ProcessBackend(control, link)
        send(root, Kind.NEWS, dumps((False, "sACN r2: U1 Stage → universe 7")))
        send(root, Kind.NEWS, dumps((True, "engine: restarted (killed by signal 9)")))
        root.close()
        with (
            diverted(lambda failed, text: taken.append((failed, text)) is None),
            pytest.raises(test_route_status.Exited),
        ):
            backend._read_control()
        assert taken == [
            (False, "sACN r2: U1 Stage → universe 7"),
            (True, "engine: restarted (killed by signal 9)"),
        ]
    finally:
        for sock in (control, root, link, engine):
            sock.close()
