"""The bridge (``busk_tui.bridge``) against a stub show: its two workers,
the reader's change detection, health, and stopping in both hosts. The
stub has what the bridge reads; its ``execute`` can be held, fail or raise."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from tui_fakes import Stub
from tui_fakes import stub_health as health
from tui_fakes import stub_programmer as programmer
from tui_fakes import stub_session as session_status
from tui_fakes import stub_snapshot as snapshot

import busk
from busk_tui import bridge as bridge_module
from busk_tui.bridge import Bridge, session_state, show_read
from busk_tui.model import (
    BridgeEvent,
    Busy,
    CommandDone,
    DmxChanged,
    EffectsChanged,
    ElementOutput,
    EngineFailed,
    EngineRunning,
    EngineStarting,
    EngineStopped,
    HealthChanged,
    InputsChanged,
    LiveChanged,
    OutputChanged,
    ProgrammerChanged,
    ScriptDone,
    ScriptLine,
    SessionChanged,
    SessionState,
    ShowChanged,
    ShowLoadFailed,
    SurfacesChanged,
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
    assert stub.ran[:1] == ["help"]
    session = events.until(lambda e: isinstance(e, SessionChanged), "SessionChanged")
    assert isinstance(session, SessionChanged)
    assert session.session == SessionState(undo=2, redo=1, dirty=True, path=Path("/tmp/t.show"))
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


def test_the_session_only_when_what_the_ui_shows_of_it_changes(
    running: tuple[Bridge, Events], stub: Stub
) -> None:
    """busk's session as the UI reads it: a new object with only another
    version (a programmer step) sends nothing; a save does."""
    _, events = running
    events.until(lambda e: isinstance(e, SessionChanged))
    stub.session = session_status(version=2)
    time.sleep(0.2)
    assert len(events.of(SessionChanged)) == 1
    stub.session = session_status(version=3, dirty=False, path="/tmp/copy.show")
    event = events.until(lambda e: isinstance(e, SessionChanged) and not e.session.dirty)
    assert isinstance(event, SessionChanged)
    assert event.session == SessionState(2, 1, dirty=False, path=Path("/tmp/copy.show"))
    assert "info" not in stub.ran  # no text is parsed


def test_the_session_of_a_show_without_a_file_has_no_path() -> None:
    assert session_state(session_status(path=None)) == SessionState(2, 1, dirty=True)


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


def test_the_show_again_when_what_fixture_add_takes_changes(
    running: tuple[Bridge, Events], stub: Stub
) -> None:
    """A ``--library`` file that changes gives a new tuple, on the same document."""
    _, events = running
    events.until(lambda e: isinstance(e, ShowChanged))
    mode = busk.FixtureModeInfo(name="3ch", footprint=3, elements=1)
    stub.fixture_profiles = (
        busk.FixtureProfileInfo(
            name="Par",
            id="p-1",
            source="library",
            manufacturer="Acme",
            revision="1",
            library_revision="1",
            modes=(mode,),
        ),
    )
    event = events.until(lambda e: isinstance(e, ShowChanged) and bool(e.show.choices))
    assert isinstance(event, ShowChanged)
    assert [(c.name, c.source) for c in event.show.choices] == [("Par", "library")]


def test_the_surfaces_on_a_new_status_and_a_new_document(
    running: tuple[Bridge, Events], stub: Stub
) -> None:
    _, events = running
    events.until(lambda e: isinstance(e, SurfacesChanged))  # none open yet: None
    show = busk.new_show("Stub")
    show["surfaces"] = [{"id": "s-1", "name": "Phone", "kind": "web", "match": {"port": 8080},
                         "faderPickup": "jump"}]  # fmt: skip
    stub.show = show
    event = events.until(lambda e: isinstance(e, SurfacesChanged) and bool(e.surfaces))
    assert isinstance(event, SurfacesChanged)
    assert [(v.name, v.state) for v in event.surfaces] == [("Phone", None)]
    status = (busk.SurfaceStatus(id="s-1", name="Phone", kind="web", state="ok", detail="",
                                 urls=("http://10.0.0.2:8080/?k=abc",)),)  # fmt: skip
    stub.surfaces = status
    event = events.until(
        lambda e: (
            isinstance(e, SurfacesChanged) and e.surfaces[:1] != () and e.surfaces[0].state == "ok"
        )
    )
    assert isinstance(event, SurfacesChanged)
    assert event.surfaces[0].urls == ("http://10.0.0.2:8080/?k=abc",)
    count = len(events.of(SurfacesChanged))
    time.sleep(0.2)  # the same status object: nothing new
    assert len(events.of(SurfacesChanged)) == count


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


def test_a_parked_family_reaches_the_model_as_park(
    running: tuple[Bridge, Events], stub: Stub
) -> None:
    """GAP-22's ``park``, which F3's source column reads (the pending plan's
    Phase 12)."""
    bridge, events = running
    parked = busk.FixtureOutput(
        number=101, element=1, intensity=0.0, color=None, pan=None, tilt=None, zoom=None,
        source={"intensity": "park", "color": "programmer"}, playback=None,
    )  # fmt: skip
    stub.output = busk.OutputSnapshot(seq=1, time=0.01, fixtures=(parked,))
    bridge.watch(output=True, effects=False)
    event = events.until(lambda e: isinstance(e, OutputChanged), "the output")
    assert isinstance(event, OutputChanged)
    element = event.output.element(101, 1)
    assert element is not None
    assert element.sources == (("intensity", "park"), ("color", "programmer"))


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
    sources = (("intensity", "programmer"),)
    assert first.output.element(101, 1) == ElementOutput(101, 1, 1.0, (1.0, 0.0, 0.0), -45.0,
                                                         10.0, None, sources)  # fmt: skip
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


def dmx_frame(seq: int, value: int = 0) -> busk.DmxFrame:
    universes = MappingProxyType({1: bytes([value]) + bytes(511), 2: bytes(512)})
    return busk.DmxFrame(seq=seq, time=seq / 100, universes=universes)


def test_the_dmx_frame_only_while_watched_and_only_when_it_changes(
    running: tuple[Bridge, Events], stub: Stub
) -> None:
    """F8's channel values (the pending plan's Phase 34)."""
    bridge, events = running
    stub.frame = dmx_frame(1, 255)
    time.sleep(0.2)
    assert events.of(DmxChanged) == []  # not watched
    bridge.watch(output=False, effects=False, dmx=True)
    first = events.until(lambda e: isinstance(e, DmxChanged), "the frame")
    assert isinstance(first, DmxChanged)
    assert first.dmx.seq == 1
    assert [number for number, _ in first.dmx.universes] == [1, 2]
    assert first.dmx.universe(1) == bytes([255]) + bytes(511)
    assert first.dmx.universe(3) is None
    stub.frame = dmx_frame(2, 255)  # a new tick, the same bytes
    time.sleep(0.2)
    assert len(events.of(DmxChanged)) == 1
    stub.frame = dmx_frame(3, 128)
    events.until(lambda e: isinstance(e, DmxChanged) and e.dmx.seq == 3, "a change")
    bridge.watch(output=False, effects=False)
    time.sleep(0.2)
    sent = len(events.of(DmxChanged))
    stub.frame = dmx_frame(4, 0)
    time.sleep(0.2)
    assert len(events.of(DmxChanged)) == sent  # not watched any more
    bridge.watch(output=False, effects=False, dmx=True)
    events.until(lambda e: isinstance(e, DmxChanged) and e.dmx.seq == 4, "sent again")


def came(
    seq: int, raw: int | None = 64, drives: tuple[str, ...] = ("fader 1",)
) -> busk.SurfaceInput:
    return busk.SurfaceInput(
        seq=seq, surfaceId="s-apc", surface="APC mini mk2", input="cc 1 48",
        raw=raw, value=0.5, drives=drives,
    )  # fmt: skip


def test_the_inputs_only_while_watched_and_whole_when_watched_again(
    running: tuple[Bridge, Events], stub: Stub
) -> None:
    """F9's MONITOR (the pending plan's Phase 37, busk's GAP-13)."""
    bridge, events = running
    stub.inputs = (came(1), came(2, raw=None, drives=()))
    time.sleep(0.2)
    assert events.of(InputsChanged) == []  # not watched
    bridge.watch(output=False, effects=False, inputs=True)
    first = events.until(lambda e: isinstance(e, InputsChanged), "the inputs")
    assert isinstance(first, InputsChanged)
    assert [(i.seq, i.surface, i.input, i.sent, i.drives) for i in first.inputs] == [
        (1, "APC mini mk2", "cc 1 48", "64", ("fader 1",)),
        (2, "APC mini mk2", "cc 1 48", "0.50", ()),
    ]
    time.sleep(0.2)  # the same tuple: nothing new
    assert len(events.of(InputsChanged)) == 1
    stub.inputs = (*stub.inputs[1:], came(3))
    later = events.until(lambda e: isinstance(e, InputsChanged) and e.inputs[-1].seq == 3, "new")
    assert isinstance(later, InputsChanged)
    assert later.inputs[0] is first.inputs[1]  # an input keeps its view
    assert [i.seq for i in later.inputs] == [2, 3]
    bridge.watch(output=False, effects=False)
    time.sleep(0.2)
    sent = len(events.of(InputsChanged))
    stub.inputs = (*stub.inputs, came(4))
    time.sleep(0.2)
    assert len(events.of(InputsChanged)) == sent  # not watched any more
    bridge.watch(output=False, effects=False, inputs=True)
    again = events.until(lambda e: isinstance(e, InputsChanged) and e.inputs[-1].seq == 4, "again")
    assert isinstance(again, InputsChanged)
    assert [i.seq for i in again.inputs] == [2, 3, 4]
    bridge.watch(output=False, effects=False)
    time.sleep(0.2)
    sent = len(events.of(InputsChanged))
    bridge.watch(output=False, effects=False, inputs=True)  # nothing new: sent all the same
    deadline = time.monotonic() + WAIT_S
    while len(events.of(InputsChanged)) == sent:
        assert time.monotonic() < deadline, "not sent again"
        time.sleep(0.01)


class SweepingStub(Stub):
    """A stub with a new input at every read."""

    count = 0

    @property  # type: ignore[override]
    def inputs(self) -> Any:
        self.count += 1
        return (came(self.count),)

    @inputs.setter
    def inputs(self, value: Any) -> None:
        pass


def test_the_inputs_go_ten_times_a_second_at_most() -> None:
    stub = SweepingStub()
    bridge = Bridge(stub, None)  # type: ignore[arg-type]
    bridge.start()
    try:
        events = Events(bridge)
        events.until(lambda e: isinstance(e, EngineRunning))
        bridge.watch(output=False, effects=False, inputs=True)
        events.until(lambda e: isinstance(e, InputsChanged), "the inputs")
        before = len(events.of(InputsChanged))
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:  # a drain keeps only the newest of each kind
            events.of(InputsChanged)
            time.sleep(0.02)
        sent = len(events.of(InputsChanged)) - before
        assert 7 <= sent <= 13, sent  # the reader looks 20 times a second
    finally:
        bridge.stop()


class ChangingStub(Stub):
    """A stub whose frame is new, with new bytes, at every read."""

    count = 0

    @property  # type: ignore[override]
    def frame(self) -> Any:
        self.count += 1
        return dmx_frame(self.count, self.count % 256)

    @frame.setter
    def frame(self, value: Any) -> None:
        pass


def test_the_dmx_frame_goes_ten_times_a_second_at_most() -> None:
    stub = ChangingStub()
    bridge = Bridge(stub, None)  # type: ignore[arg-type]
    bridge.start()
    try:
        events = Events(bridge)
        events.until(lambda e: isinstance(e, EngineRunning))
        bridge.watch(output=False, effects=False, dmx=True)
        events.until(lambda e: isinstance(e, DmxChanged), "the frame")
        before = len(events.of(DmxChanged))
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:  # a drain keeps only the newest of each kind
            events.of(DmxChanged)
            time.sleep(0.02)
        sent = len(events.of(DmxChanged)) - before
        assert 7 <= sent <= 13, sent  # the reader looks 20 times a second
    finally:
        bridge.stop()


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


# --------------------------------------------------------------- scripts


def script(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "rig.busk"
    path.write_text(text)
    return path


def test_a_script_runs_its_lines_in_turn_and_tells_each(
    running: tuple[Bridge, Events], stub: Stub, tmp_path: Path
) -> None:
    """After the lines sent before it, before those sent after it, on the
    ordered worker; blank lines and comments are told too (the UI leaves
    them out), and it leaves an undo step."""
    bridge, events = running
    path = script(tmp_path, "edit 1\n\n# a comment\nedit 2\n")
    bridge.send("before", "typed")
    ticket = bridge.run_script(path)
    bridge.send("after", "typed")
    events.done("after")
    assert stub.ran[-4:] == ["before", "edit 1", "edit 2", "after"]
    assert {stub.threads["edit 1"], stub.threads["edit 2"]} == {"busk-tui-ordered"}
    assert events.of(ScriptLine) == [
        ScriptLine(ticket, 1, 4, "edit 1", True, ("did edit 1",)),
        ScriptLine(ticket, 2, 4, "", True, ()),
        ScriptLine(ticket, 3, 4, "# a comment", True, ()),
        ScriptLine(ticket, 4, 4, "edit 2", True, ("did edit 2",)),
    ]
    assert events.of(ScriptDone) == [ScriptDone(ticket, path, True, 4, 4, stepped=True)]
    order = [type(e).__name__ for e in events.seen if isinstance(e, ScriptDone | CommandDone)]
    assert order[-3:] == ["CommandDone", "ScriptDone", "CommandDone"]


def test_each_line_is_told_as_it_runs_and_the_script_is_not_busy(
    running: tuple[Bridge, Events], stub: Stub, tmp_path: Path
) -> None:
    bridge, events = running
    gate = stub.gates["edit 2"] = threading.Event()
    path = script(tmp_path, "edit 1\nedit 2\n")
    bridge.run_script(path)
    bridge.send("typed meanwhile", "typed")
    events.until(lambda e: isinstance(e, ScriptLine) and e.number == 1, "line 1")
    time.sleep(0.05)
    assert not events.of(ScriptDone)
    assert "typed meanwhile" not in stub.ran  # it waits for the script
    assert bridge.busy is None  # the UI shows the script's own progress
    gate.set()
    events.done("typed meanwhile")
    assert stub.ran[-3:] == ["edit 1", "edit 2", "typed meanwhile"]


def test_a_refused_line_ends_the_script_there(
    running: tuple[Bridge, Events], stub: Stub, tmp_path: Path
) -> None:
    bridge, events = running
    path = script(tmp_path, "edit 1\nbad line\nedit 3\n")
    ticket = bridge.run_script(path)
    done = events.until(lambda e: isinstance(e, ScriptDone), "ScriptDone")
    assert done == ScriptDone(ticket, path, False, 2, 3, stepped=True)
    assert events.of(ScriptLine)[-1] == ScriptLine(
        ticket, 2, 3, "bad line", False, ("error: no such thing",)
    )
    assert "edit 3" not in stub.ran


def test_a_script_that_changes_nothing_leaves_no_step(
    running: tuple[Bridge, Events], tmp_path: Path
) -> None:
    bridge, events = running
    path = script(tmp_path, "# nothing to do\n")
    ticket = bridge.run_script(path)
    done = events.until(lambda e: isinstance(e, ScriptDone), "ScriptDone")
    assert done == ScriptDone(ticket, path, True, 1, 1, stepped=False)


def test_a_quit_line_ends_the_script_and_asks_to_quit(
    running: tuple[Bridge, Events], stub: Stub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge, events = running
    execute = stub.execute
    monkeypatch.setattr(
        stub, "execute", lambda line: busk.Reply("", quit=True) if line == "quit" else execute(line)
    )
    path = script(tmp_path, "edit 1\nquit\nedit 3\n")
    ticket = bridge.run_script(path)
    done = events.until(lambda e: isinstance(e, ScriptDone), "ScriptDone")
    assert done == ScriptDone(ticket, path, True, 2, 3, stepped=True, quit=True)


def test_a_script_that_cannot_be_read_says_why(
    running: tuple[Bridge, Events], tmp_path: Path
) -> None:
    bridge, events = running
    gone, binary = tmp_path / "gone.busk", tmp_path / "binary.busk"
    binary.write_bytes(b"\xff\xfe\x00")
    for path, why in ((gone, "No such file or directory"), (binary, "it is not UTF-8 text")):
        ticket = bridge.run_script(path)
        done = events.until(lambda e, t=ticket: isinstance(e, ScriptDone) and e.ticket == t)
        problem = f"cannot read {str(path)!r}: {why}"
        assert done == ScriptDone(ticket, path, False, 0, 0, stepped=False, problem=problem)


def test_the_reader_looks_four_times_a_second_while_a_script_runs(
    running: tuple[Bridge, Events], stub: Stub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The show changes at almost every line: each look would convert it all."""
    bridge, events = running
    looks: list[float] = []
    look = bridge._look

    def counted() -> None:
        looks.append(time.monotonic())
        look()

    monkeypatch.setattr(bridge, "_look", counted)
    gate = stub.gates["edit 2"] = threading.Event()
    bridge.run_script(script(tmp_path, "edit 1\nedit 2\n"))
    events.until(lambda e: isinstance(e, ScriptLine) and e.number == 1, "line 1")
    looks.clear()
    time.sleep(1.0)
    assert len(looks) <= 6  # 4 a second; 20 without the script
    gate.set()
    events.until(lambda e: isinstance(e, ScriptDone), "ScriptDone")


def test_stopping_the_bridge_ends_a_script_at_its_next_line(stub: Stub, tmp_path: Path) -> None:
    bridge = Bridge(stub, None)  # type: ignore[arg-type]
    gate = stub.gates["edit 2"] = threading.Event()
    bridge.start()
    events = Events(bridge)
    events.until(lambda e: isinstance(e, EngineRunning))
    bridge.run_script(script(tmp_path, "edit 1\nedit 2\nedit 3\n"))
    events.until(lambda e: isinstance(e, ScriptLine) and e.number == 1, "line 1")
    threading.Timer(0.1, gate.set).start()
    started = time.monotonic()
    bridge.stop(timeout=2.0)
    assert time.monotonic() - started < 1.0
    assert stub.ran[-2:] == ["edit 1", "edit 2"]  # the line it ran finished; no more
    assert not events.of(ScriptDone)
    assert not [t for t in threading.enumerate() if t.name.startswith("busk-tui")]


def test_questions_and_answers_go_to_the_show(running: tuple[Bridge, Events]) -> None:
    bridge, _ = running
    assert bridge.confirmation("output off") == "Really?"
    assert bridge.confirmation("go 1") is None
    answer = bridge.expected("route add 1 sa")
    assert (answer.words, answer.start) == (("sacn",), 14)


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


# ------------------------------------------------------------ show files


def test_a_show_file_read_as_busk_run_would_open_it(club_path: Path) -> None:
    found = show_read(club_path)
    doc, _ = busk.load_show(club_path)
    assert found.path == club_path
    assert found.title == "Club Night"
    assert (found.fixtures, found.cueLists, found.playbacks) == (
        len(doc["fixtures"]), len(doc["cueLists"]), len(doc["playbacks"]),
    )  # fmt: skip
    assert found.fixtures > 0
    assert found.saved == datetime.fromisoformat(doc["meta"]["modified"])
    assert found.errors == ()


def test_a_show_file_with_errors_cannot_be_opened(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{}")
    found = show_read(broken)
    assert found.title is None
    assert "schemaVersion: Field required" in found.errors  # busk's words


def test_a_show_that_does_not_compile_cannot_be_opened(club_path: Path, tmp_path: Path) -> None:
    doc, _ = busk.load_show(club_path)
    fixture = doc["fixtures"][0]
    fixture["elementPatch"] = {"0": dict(fixture["patch"])}  # type: ignore[typeddict-unknown-key]
    path = tmp_path / "split.show"
    busk.save_show(doc, path, backups=False)
    found = show_read(path)
    assert found.title == "Club Night"  # it loads
    (error,) = found.errors
    assert error.startswith("busk cannot run it yet: fixtures[0].elementPatch")


def test_a_file_that_is_no_show_or_none_cannot_be_opened(tmp_path: Path) -> None:
    text = tmp_path / "notes.show"
    text.write_text("hello")
    assert show_read(text).errors == ("Not a valid .show file: File is not a zip file",)
    missing = show_read(tmp_path / "missing.show")
    assert missing.errors == ("cannot read it: No such file or directory",)
