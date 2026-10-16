"""The engine process (phase-7-plan §5.4, step 7).

A real ``python -m busk.process.engine_host`` child, with the test playing
the root (the control link) and the console (a link handed over with
``ATTACH``) over socket pairs: layouts before frames, frames at the engine
rate, snapshots after commands, ``STOP`` and ``FINAL``, the root's end of
file, a root that stops reading, and a second console replacing the first.
The exit after ten consecutive tick errors runs an :class:`EngineHost` in
this process with a faulty engine.
"""

from __future__ import annotations

import itertools
import select
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from typing import Any, cast

import pytest

from builders import APPENDIX_A, ROOT, compile_doc, load_doc
from busk.commands.types import Command, CommandEnvelope, CommandOrigin
from busk.compiler.compile import CompiledShow, OutputLayout
from busk.engine.clock import MonotonicClock
from busk.engine.install import EMPTY_FRAME, Install
from busk.engine.loop import Engine
from busk.engine.snapshot import EngineSnapshot
from busk.process.engine_host import EXIT_FAILED, TICK_ERRORS_EXIT, EngineHost
from busk.process.wire import (
    Attach,
    EngineReport,
    Hello,
    Kind,
    Message,
    ShowEncoder,
    Welcome,
    decode_frame,
    dumps,
    loads,
    receive,
    send,
)

TIMEOUT = 10.0  # generous: a child imports NumPy and busk before it answers


def read(sock: socket.socket, timeout: float = TIMEOUT) -> Message | None:
    """The next message, or ``None`` at end of file; fails after ``timeout``."""
    ready, _, _ = select.select([sock], [], [], timeout)
    assert ready, "no message in time"
    return receive(sock)


def expect(sock: socket.socket, kind: Kind, timeout: float = TIMEOUT) -> Message:
    """Skip messages until one of ``kind``."""
    deadline = time.monotonic() + timeout
    while True:
        message = read(sock, max(deadline - time.monotonic(), 0.0))
        assert message is not None, f"end of file before {kind.name}"
        if message.kind == kind:
            return message


def collect(sock: socket.socket, seconds: float) -> list[Message]:
    """Every message that arrives within ``seconds``."""
    deadline = time.monotonic() + seconds
    messages = []
    while (remaining := deadline - time.monotonic()) > 0:
        ready, _, _ = select.select([sock], [], [], remaining)
        if ready:
            message = receive(sock)
            assert message is not None
            messages.append(message)
    return messages


def envelope(ident: str, **command: Any) -> CommandEnvelope:
    return CommandEnvelope(
        id=ident, issuedAt=0.0, origin=CommandOrigin(), command=cast(Command, command)
    )


def appendix() -> CompiledShow:
    return compile_doc(load_doc(APPENDIX_A))


def attach(root: socket.socket) -> socket.socket:
    """Hand the engine a new console link, as the root does; the console's end."""
    console, end = socket.socketpair()
    send(root, Kind.ATTACH, dumps(Attach()), fds=[end.fileno()])
    end.close()
    return console


def hello(console: socket.socket) -> Welcome:
    send(console, Kind.HELLO, dumps(Hello(sessionId="test")))
    welcome = loads(expect(console, Kind.WELCOME).payload)
    assert isinstance(welcome, Welcome)
    return welcome


def install(console: socket.socket, compiled: CompiledShow) -> None:
    chunks = ShowEncoder().encode(Install(compiled=compiled, remap=None, programmer=EMPTY_FRAME))
    for chunk in chunks[:-1]:
        send(console, Kind.CHUNK, chunk)
    send(console, Kind.INSTALL, chunks[-1])


def snapshot_where(console: socket.socket, test: Any) -> EngineSnapshot:
    """Skip snapshots until one passes ``test``."""
    deadline = time.monotonic() + TIMEOUT
    while True:
        snapshot = loads(expect(console, Kind.SNAPSHOT, deadline - time.monotonic()).payload)
        if test(snapshot):
            return cast(EngineSnapshot, snapshot)


def state(snapshot: EngineSnapshot, ident: str) -> str:
    return next(status.state for status in snapshot.playbacks if status.id == ident)


class Child:
    """An engine host child process; the test is its root."""

    def __init__(self, sndbuf: int | None = None) -> None:
        self.root, end = socket.socketpair()
        if sndbuf is not None:  # a small send buffer: a root that stops reading blocks it soon
            end.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, sndbuf)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "busk.process.engine_host", "--control", str(end.fileno())],
            pass_fds=[end.fileno()],
            start_new_session=True,
        )
        end.close()

    def start(self, compiled: CompiledShow) -> socket.socket:
        """Attach a console, say hello and install ``compiled``; the console's end."""
        console = attach(self.root)
        assert hello(console).fresh
        install(console, compiled)
        return console

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=TIMEOUT)
        self.root.close()


@pytest.fixture
def child() -> Iterator[Child]:
    process = Child()
    yield process
    process.close()


def test_the_layout_arrives_before_the_first_frame(child: Child) -> None:
    compiled = appendix()
    child.start(compiled)
    layouts: dict[int, OutputLayout] = {}
    while (message := read(child.root)) is not None and message.kind != Kind.FRAME:
        if message.kind == Kind.LAYOUT:
            ident, layout = loads(message.payload)
            layouts[ident] = layout
    assert message is not None
    frame = decode_frame(message.payload, layouts)  # a KeyError if its layout had not come
    assert frame.layout == compiled.layout
    assert frame.seq >= 1
    assert len(frame.universes) == 1


def test_frames_arrive_at_about_the_engine_rate(child: Child) -> None:
    compiled = appendix()
    child.start(compiled)
    expect(child.root, Kind.FRAME)
    frames = [m for m in collect(child.root, 1.0) if m.kind == Kind.FRAME]
    layouts: dict[int, OutputLayout] = {1: compiled.layout}
    seqs = [decode_frame(m.payload, layouts).seq for m in frames]
    assert seqs == sorted(seqs)
    assert 0.75 * compiled.engineHz <= len(frames) <= 1.1 * compiled.engineHz


def test_snapshots_follow_commands(child: Child) -> None:
    console = child.start(appendix())
    snapshot_where(console, lambda s: state(s, "pb-blue") == "idle")
    send(console, Kind.COMMAND, dumps(envelope("1", type="TRIGGER_PLAYBACK", playbackId="pb-blue")))
    snapshot_where(console, lambda s: state(s, "pb-blue") == "active")
    send(console, Kind.COMMAND, dumps(envelope("2", type="BLACKOUT", on=True)))
    assert snapshot_where(console, lambda s: s.blackout).blackout
    report = loads(expect(console, Kind.STATS, 2.5).payload)  # every second
    assert isinstance(report, EngineReport)
    assert report.stats.commandsApplied == 2


def test_stop_gives_final_stats_and_exit_0(child: Child) -> None:
    child.start(appendix())
    expect(child.root, Kind.FRAME)
    send(child.root, Kind.STOP)
    report = loads(expect(child.root, Kind.FINAL).payload)
    assert isinstance(report, EngineReport)
    assert report.pid == child.process.pid
    assert report.stats.ticks > 0
    assert report.stats.tickErrors == 0
    assert child.process.wait(timeout=TIMEOUT) == 0


def test_the_root_going_away_ends_the_engine(child: Child) -> None:
    child.start(appendix())
    expect(child.root, Kind.FRAME)
    child.root.close()
    assert child.process.wait(timeout=TIMEOUT) == 0


def test_a_stop_before_any_show_still_says_final(child: Child) -> None:
    send(child.root, Kind.STOP)
    report = loads(expect(child.root, Kind.FINAL).payload)
    assert report.stats.ticks == 0
    assert child.process.wait(timeout=TIMEOUT) == 0


def test_a_root_that_stops_reading_skips_frames_and_never_the_tick() -> None:
    child = Child(sndbuf=4096)
    try:
        compiled = appendix()
        child.start(compiled)
        expect(child.root, Kind.FRAME)
        time.sleep(2.0)  # the root reads nothing: the publisher blocks, the engine must not
        layouts = {1: compiled.layout}
        seqs = [
            decode_frame(m.payload, layouts).seq
            for m in collect(child.root, 0.5)
            if m.kind == Kind.FRAME
        ]
        gaps = [after - before for before, after in itertools.pairwise(seqs)]
        assert max(gaps) > 50  # the publisher sent the newest frame, not the backlog
        send(child.root, Kind.STOP)
        report = loads(expect(child.root, Kind.FINAL).payload)
        assert report.stats.overruns == 0
        assert report.stats.ticks >= 2.0 * compiled.engineHz
        assert child.process.wait(timeout=TIMEOUT) == 0
    finally:
        child.close()


def test_a_second_attach_replaces_the_console_link(child: Child) -> None:
    first = child.start(appendix())
    snapshot_where(first, lambda s: True)
    send(first, Kind.COMMAND, dumps(envelope("1", type="TRIGGER_PLAYBACK", playbackId="pb-song")))
    snapshot_where(first, lambda s: state(s, "pb-song") == "active")
    second = attach(child.root)
    while read(first) is not None:  # the first link ends
        pass
    welcome = hello(second)
    assert not welcome.fresh
    assert welcome.snapshot is not None
    assert state(welcome.snapshot, "pb-song") == "active"
    send(second, Kind.COMMAND, dumps(envelope("2", type="TRIGGER_PLAYBACK", playbackId="pb-blue")))
    snapshot_where(second, lambda s: state(s, "pb-blue") == "active")
    first.close()
    second.close()


def test_commands_before_the_first_show_wait_for_it(child: Child) -> None:
    console = attach(child.root)
    assert hello(console).fresh
    send(console, Kind.COMMAND, dumps(envelope("1", type="TRIGGER_PLAYBACK", playbackId="pb-blue")))
    install(console, appendix())
    snapshot_where(console, lambda s: state(s, "pb-blue") == "active")


# ------------------------------------------------------------- giving up


class Faulty(Engine):
    """An engine whose every tick raises."""

    def tick(self, now: float) -> None:
        raise RuntimeError("a bug")


def test_ten_consecutive_tick_errors_exit_70() -> None:
    root, end = socket.socketpair()
    host = EngineHost(end, make_engine=Faulty, freeze=False)
    codes: list[int] = []
    thread = threading.Thread(target=lambda: codes.append(host.run()), daemon=True)
    thread.start()
    console = attach(root)
    assert hello(console).fresh
    install(console, appendix())
    thread.join(timeout=TIMEOUT)
    assert codes == [EXIT_FAILED]
    report = loads(expect(root, Kind.FINAL).payload)
    assert report.stats.tickErrors >= TICK_ERRORS_EXIT
    assert report.stats.ticks == 0
    console.close()
    root.close()
    end.close()


# ------------------------------------------------------------- the benches


def test_the_benches_process_engine_runs_a_show() -> None:
    """``bench/engines.py`` spawns its engine the way the root does (the
    ``--processes`` runs of ``edit_latency.py`` and ``surface_load.py``),
    so a change to the root's spawn must reach it."""
    sys.path.insert(0, str(ROOT / "bench"))
    try:
        import engines
    finally:
        sys.path.remove(str(ROOT / "bench"))
    engine = engines.make_engine(appendix(), MonotonicClock(), processes=True)
    engine.start()
    try:
        assert engine.snapshot is not None
    finally:
        stats = engine.stop()
    assert stats.ticks > 0
