"""The bridge (``busk_tui.bridge``) against a stub show: its two workers,
the reader's change detection, health, and stopping in both hosts. The
stub has what the bridge reads; its ``execute`` can be held, fail or raise."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from tui_fakes import INFO, Stub
from tui_fakes import stub_health as health
from tui_fakes import stub_programmer as programmer
from tui_fakes import stub_snapshot as snapshot

import busk
from busk_tui import bridge as bridge_module
from busk_tui.bridge import Bridge, session_from_info
from busk_tui.model import (
    BridgeEvent,
    Busy,
    CommandDone,
    EffectsChanged,
    ElementOutput,
    EngineFailed,
    EngineRunning,
    EngineStarting,
    EngineStopped,
    HealthChanged,
    LiveChanged,
    OutputChanged,
    ProgrammerChanged,
    SessionChanged,
    SessionState,
    ShowChanged,
    ShowLoadFailed,
)

WAIT_S = 5.0


class Events:
    """What a bridge sent, gathered by draining it."""

    def __init__(self, bridge: Bridge) -> None:
        self.bridge = bridge
        self.seen: list[BridgeEvent] = []

    def until(self, test: Callable[[BridgeEvent], bool], what: str = "") -> BridgeEvent:
        deadline = time.monotonic() + WAIT_S
        index = 0
        while time.monotonic() < deadline:
            self.seen += self.bridge.drain()
            for event in self.seen[index:]:
                if test(event):
                    return event
            index = len(self.seen)
            time.sleep(0.01)
        raise AssertionError(f"no event {what}; saw {self.seen}")

    def done(self, line: str) -> CommandDone:
        event = self.until(lambda e: isinstance(e, CommandDone) and e.line == line, line)
        assert isinstance(event, CommandDone)
        return event

    def of(self, kind: type) -> list[Any]:
        self.seen += self.bridge.drain()
        return [event for event in self.seen if isinstance(event, kind)]


@pytest.fixture
def stub() -> Stub:
    return Stub()


@pytest.fixture
def running(stub: Stub) -> Iterator[tuple[Bridge, Events]]:
    """A bridge on the stub, as under busk run, started and running."""
    bridge = Bridge(stub, None)  # type: ignore[arg-type]
    bridge.start()
    events = Events(bridge)
    events.until(lambda e: isinstance(e, EngineRunning), "EngineRunning")
    yield bridge, events
    for gate in stub.gates.values():
        gate.set()
    bridge.stop(timeout=1.0)


def test_it_starts_runs_help_and_says_so(running: tuple[Bridge, Events], stub: Stub) -> None:
    bridge, events = running
    assert isinstance(events.seen[0], EngineStarting)
    assert bridge.help_lines == ("    help | quit",)
    assert stub.ran[:2] == ["help", "info"]
    (session,) = events.of(SessionChanged)
    assert session.session == SessionState(undo=2, redo=1, dirty=True)
    running_event = events.of(EngineRunning)[0]
    assert running_event.title == "Stub"


def test_lines_run_in_order_on_each_worker(running: tuple[Bridge, Events], stub: Stub) -> None:
    bridge, events = running
    for number in range(5):
        bridge.send(f"edit {number}", "typed")
        bridge.send(f"fader {number}", "ui", performance=True)
    events.done("edit 4")
    events.done("fader 4")
    edits = [line for line in stub.ran if line.startswith("edit")]
    faders = [line for line in stub.ran if line.startswith("fader")]
    assert edits == [f"edit {n}" for n in range(5)]
    assert faders == [f"fader {n}" for n in range(5)]
    assert {stub.threads[f"edit {n}"] for n in range(5)} == {"busk-tui-ordered"}
    assert {stub.threads[f"fader {n}"] for n in range(5)} == {"busk-tui-controls"}


def test_a_typed_performance_line_waits_its_turn(
    running: tuple[Bridge, Events], stub: Stub
) -> None:
    bridge, events = running
    bridge.send("go 1", "typed", performance=True)
    events.done("go 1")
    assert stub.threads["go 1"] == "busk-tui-ordered"


def test_a_control_runs_while_an_ordered_line_is_held(
    running: tuple[Bridge, Events], stub: Stub
) -> None:
    bridge, events = running
    gate = stub.gates["save"] = threading.Event()
    started = time.monotonic()
    bridge.send("save", "typed")
    bridge.send("fader 1 50%", "ui", performance=True)
    assert time.monotonic() - started < 0.05  # send() never waits
    done = events.done("fader 1 50%")
    assert done.ok
    assert "save" not in stub.ran
    busy = bridge.busy
    assert isinstance(busy, Busy)
    assert busy.line == "save"
    gate.set()
    events.done("save")
    assert bridge.busy is None


def test_busy_follows_the_ordered_worker_only(running: tuple[Bridge, Events], stub: Stub) -> None:
    bridge, events = running
    gate = stub.gates["fader 2 10%"] = threading.Event()
    bridge.send("fader 2 10%", "ui", performance=True)
    time.sleep(0.1)
    assert bridge.busy is None
    gate.set()
    events.done("fader 2 10%")


def test_a_line_that_raises_is_an_internal_error_and_the_next_runs(
    running: tuple[Bridge, Events], stub: Stub
) -> None:
    bridge, events = running
    stub.raises.add("explode")
    bridge.send("explode", "typed")
    bridge.send("after", "typed")
    done = events.done("explode")
    assert not done.ok
    assert done.lines == ("internal error: RuntimeError: boom",)
    assert events.done("after").ok


def test_a_refused_line_and_a_reply(running: tuple[Bridge, Events]) -> None:
    bridge, events = running
    ticket = bridge.send("bad line", "typed")
    done = events.done("bad line")
    assert (done.ticket, done.ok, done.lines, done.origin) == (
        ticket,
        False,
        ("error: no such thing",),
        "typed",
    )
    bridge.send("sel group 1", "ui")
    assert events.done("sel group 1").lines == ("did sel group 1",)


def test_a_newer_keyed_line_replaces_an_unsent_one(
    running: tuple[Bridge, Events], stub: Stub
) -> None:
    bridge, events = running
    gate = stub.gates["hold"] = threading.Event()
    bridge.send("hold", "ui", performance=True)
    time.sleep(0.05)
    for level in (10, 20, 30):
        bridge.send(f"fader 3 {level}%", "internal", key="fader:3", performance=True)
    bridge.send("fader 4 10%", "internal", key="fader:4", performance=True)
    gate.set()
    events.done("fader 4 10%")
    assert [line for line in stub.ran if line.startswith("fader")] == [
        "fader 3 30%",
        "fader 4 10%",
    ]
    assert not [e for e in events.of(CommandDone) if e.line in ("fader 3 10%", "fader 3 20%")]


def test_live_state_only_on_a_new_seq_and_a_smaller_one_counts(
    running: tuple[Bridge, Events], stub: Stub
) -> None:
    _, events = running
    events.until(lambda e: isinstance(e, LiveChanged), "the first LiveChanged")
    time.sleep(0.2)
    assert len(events.of(LiveChanged)) == 1
    stub.snapshot = snapshot(7, gm=0.5)
    event = events.until(lambda e: isinstance(e, LiveChanged) and e.state.seq == 7)
    assert isinstance(event, LiveChanged)
    assert event.state.gm == 0.5
    stub.snapshot = snapshot(1, gm=0.25)  # an engine restart counts from 1 again
    events.until(lambda e: isinstance(e, LiveChanged) and e.state.gm == 0.25, "after a restart")


def test_the_programmer_only_on_a_new_version(running: tuple[Bridge, Events], stub: Stub) -> None:
    _, events = running
    events.until(lambda e: isinstance(e, ProgrammerChanged))
    stub.programmer = replace(stub.programmer)  # a new object, the same version
    time.sleep(0.2)
    assert len(events.of(ProgrammerChanged)) == 1
    stub.programmer = programmer(2)
    event = events.until(lambda e: isinstance(e, ProgrammerChanged) and e.programmer.version == 2)
    assert isinstance(event, ProgrammerChanged)
    assert event.programmer.selection == ((101, 1),)


def test_the_show_only_on_a_new_document(running: tuple[Bridge, Events], stub: Stub) -> None:
    _, events = running
    events.until(lambda e: isinstance(e, ShowChanged))
    time.sleep(0.2)
    assert len(events.of(ShowChanged)) == 1
    renamed = busk.new_show("Renamed")
    stub.show = renamed
    event = events.until(lambda e: isinstance(e, ShowChanged) and e.show.title == "Renamed")
    assert isinstance(event, ShowChanged)
    assert [master.kind for master in event.show.masters] == ["grand"]


def fx_snapshot(seq: int, presence: float = 1.0) -> busk.EffectSnapshot:
    status = busk.EffectStatus(
        playback=11, cue="1", id="fx1", presence=presence, size=1.0, hz=1.0, phase=0.0,
        wave=(0.0, 1.0), colors=(),
    )  # fmt: skip
    return busk.EffectSnapshot(seq=seq, time=seq / 100, effects=(status,))


def test_effects_only_while_watched_and_only_when_they_change(
    running: tuple[Bridge, Events], stub: Stub
) -> None:
    bridge, events = running
    stub.effects = fx_snapshot(1)
    time.sleep(0.2)
    assert events.of(EffectsChanged) == []  # not watched
    bridge.watch(output=False, effects=True)
    first = events.until(lambda e: isinstance(e, EffectsChanged), "the effects")
    assert isinstance(first, EffectsChanged)
    assert [(e.playback, e.id) for e in first.effects.effects] == [(11, "fx1")]
    stub.effects = fx_snapshot(2)  # a new tick, the same effects
    time.sleep(0.2)
    assert len(events.of(EffectsChanged)) == 1
    stub.effects = fx_snapshot(3, presence=0.5)
    events.until(lambda e: isinstance(e, EffectsChanged) and e.effects.seq == 3, "a change")
    bridge.watch(output=False, effects=False)
    time.sleep(0.2)
    sent = len(events.of(EffectsChanged))
    bridge.watch(output=False, effects=True)  # watched again: sent again, unchanged
    deadline = time.monotonic() + WAIT_S
    while len(events.of(EffectsChanged)) == sent:
        assert time.monotonic() < deadline, "not sent again"
        time.sleep(0.01)


def out_snapshot(seq: int, intensity: float = 1.0) -> busk.OutputSnapshot:
    element = busk.FixtureOutput(
        number=101, element=1, intensity=intensity, color=(1.0, 0.0, 0.0), pan=-45.0, tilt=10.0,
        zoom=None, source={"intensity": "programmer"}, playback=None,
    )  # fmt: skip
    return busk.OutputSnapshot(seq=seq, time=seq / 100, fixtures=(element,))


def test_the_output_only_while_watched_and_only_when_it_changes(
    running: tuple[Bridge, Events], stub: Stub
) -> None:
    bridge, events = running
    stub.output = out_snapshot(1)
    time.sleep(0.2)
    assert events.of(OutputChanged) == []  # not watched
    bridge.watch(output=True, effects=False)
    first = events.until(lambda e: isinstance(e, OutputChanged), "the output")
    assert isinstance(first, OutputChanged)
    assert first.output.element(101, 1) == ElementOutput(101, 1, 1.0, (1.0, 0.0, 0.0), -45.0,
                                                         10.0, None)  # fmt: skip
    stub.output = out_snapshot(2)  # a new tick, the same output
    time.sleep(0.2)
    assert len(events.of(OutputChanged)) == 1
    stub.output = out_snapshot(3, intensity=0.5)
    events.until(lambda e: isinstance(e, OutputChanged) and e.output.seq == 3, "a change")
    bridge.watch(output=False, effects=False)
    time.sleep(0.2)
    sent = len(events.of(OutputChanged))
    bridge.watch(output=True, effects=False)  # watched again: sent again, unchanged
    deadline = time.monotonic() + WAIT_S
    while len(events.of(OutputChanged)) == sent:
        assert time.monotonic() < deadline, "not sent again"
        time.sleep(0.01)


class CountingStub(Stub):
    """A stub that counts how often its output and its effects are read."""

    reads = 0
    effect_reads = 0

    @property
    def output(self) -> Any:
        self.reads += 1
        return self._output

    @output.setter
    def output(self, value: Any) -> None:
        self._output = value

    @property
    def effects(self) -> Any:
        self.effect_reads += 1
        return self._effects

    @effects.setter
    def effects(self, value: Any) -> None:
        self._effects = value


@pytest.mark.parametrize("what", ["output", "effects"])
def test_the_output_and_the_effects_are_read_ten_times_a_second_while_watched(
    what: str,
) -> None:
    stub = CountingStub()
    stub.output = out_snapshot(1)
    stub.effects = fx_snapshot(1)
    bridge = Bridge(stub, None)  # type: ignore[arg-type]
    bridge.start()
    try:
        Events(bridge).until(lambda e: isinstance(e, EngineRunning))
        time.sleep(0.5)
        assert (stub.reads, stub.effect_reads) == (0, 0)
        bridge.watch(output=what == "output", effects=what == "effects")
        time.sleep(1.0)
        reads = stub.reads if what == "output" else stub.effect_reads
        assert 7 <= reads <= 13, reads  # the reader looks 20 times a second
    finally:
        bridge.stop()


def test_health_on_a_new_state_and_late_while_overruns_grow(
    running: tuple[Bridge, Events], stub: Stub, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, events = running
    monkeypatch.setattr(bridge_module, "LATE_S", 0.1)
    events.until(lambda e: isinstance(e, HealthChanged) and e.state == "running")
    stub.health = health("stalled")
    events.until(lambda e: isinstance(e, HealthChanged) and e.state == "stalled")
    stub.health = health("running", overruns=5)
    events.until(lambda e: isinstance(e, HealthChanged) and e.late, "late")
    events.until(lambda e: isinstance(e, HealthChanged) and e.state == "running" and not e.late)


def test_under_busk_run_stop_never_stops_the_show(stub: Stub) -> None:
    bridge = Bridge(stub, None)  # type: ignore[arg-type]
    bridge.start()
    Events(bridge).until(lambda e: isinstance(e, EngineRunning))
    bridge.stop()
    bridge.stop()
    assert stub.stops == 0
    assert isinstance(bridge.drain()[-1], EngineStopped)
    assert not [t for t in threading.enumerate() if t.name.startswith("busk-tui")]


def test_lines_queued_at_stop_are_dropped(stub: Stub) -> None:
    bridge = Bridge(stub, None)  # type: ignore[arg-type]
    gate = stub.gates["slow"] = threading.Event()
    bridge.start()
    Events(bridge).until(lambda e: isinstance(e, EngineRunning))
    bridge.send("slow", "typed")
    bridge.send("never", "typed")
    time.sleep(0.05)
    threading.Timer(0.1, gate.set).start()
    bridge.stop(timeout=2.0)
    assert "slow" in stub.ran  # the line it ran finished
    assert "never" not in stub.ran


def test_questions_and_answers_go_to_the_show(running: tuple[Bridge, Events]) -> None:
    bridge, _ = running
    assert bridge.confirmation("output off") == "Really?"
    assert bridge.confirmation("go 1") is None
    answer = bridge.expected("route add 1 sa")
    assert (answer.words, answer.start) == (("sacn",), 14)


def test_the_info_parser() -> None:
    assert session_from_info(INFO) == SessionState(undo=2, redo=1, dirty=True)
    saved = INFO.replace(", unsaved edits", ", saved").replace("2 steps", "1 step")
    assert session_from_info(saved) == SessionState(undo=1, redo=1, dirty=False)
    assert session_from_info("something else") is None


def test_the_info_parser_reads_busks_own_info(club: busk.OfflineShow) -> None:
    assert session_from_info(club.execute("info").text) == SessionState(0, 0, dirty=False)


# ------------------------------------------------------------ standalone


@pytest.fixture
def show_file(tmp_path: Path) -> Path:
    path = tmp_path / "small.show"
    busk.save_show(busk.new_show("Small"), path, backups=False)
    return path


def test_a_show_that_does_not_load_is_said_before_anything_starts(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text('{"schemaVersion": 1}')
    with pytest.raises(ShowLoadFailed) as failed:
        Bridge.standalone(broken)
    assert all(message.startswith(f"{broken}: error ") for message in failed.value.messages)
    with pytest.raises(ShowLoadFailed, match="cannot read"):
        Bridge.standalone(tmp_path / "missing.show")


def test_a_show_that_does_not_start_is_engine_failed(
    show_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Failing(busk.LiveShow):
        def start(self) -> None:
            raise OSError("no such interface")

    monkeypatch.setattr(bridge_module, "LiveShow", Failing)
    bridge = Bridge.standalone(show_file, output=False, surfaces=False)
    bridge.start()
    event = Events(bridge).until(lambda e: isinstance(e, EngineFailed))
    assert isinstance(event, EngineFailed)
    assert event.message == "OSError: no such interface"
    bridge.stop(timeout=1.0)


def test_standalone_stop_stops_the_show_once_and_honours_its_timeout(
    show_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stubs: list[Stub] = []

    def made(*args: Any, **kwargs: Any) -> Stub:
        made_stub = Stub(stop_hangs=True)
        made_stub.start = lambda: None  # type: ignore[attr-defined]
        stubs.append(made_stub)
        return made_stub

    monkeypatch.setattr(bridge_module, "LiveShow", made)
    bridge = Bridge.standalone(show_file, output=False, surfaces=False)
    bridge.start()
    Events(bridge).until(lambda e: isinstance(e, EngineRunning))
    started = time.monotonic()
    bridge.stop(timeout=0.5)
    assert time.monotonic() - started < 2.0
    bridge.stop(timeout=0.5)
    assert stubs[0].stops == 1
    assert "did not stop within 0.5 s" in capsys.readouterr().err
    stubs[0].released.set()
    for thread in threading.enumerate():
        if thread.name == "busk-tui-stop":
            thread.join(1.0)


def test_attached_takes_only_a_live_show() -> None:
    with pytest.raises(TypeError, match=r"busk\.LiveShow"):
        Bridge.attached(object())
