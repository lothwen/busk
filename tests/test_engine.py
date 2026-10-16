"""Engine: fixed-rate ticking, drop-don't-spiral, overrun counting, determinism."""

from __future__ import annotations

import dataclasses
import itertools
import json
import threading
from typing import Any

import numpy as np
import pytest

from busk.compiler.compile import CompiledShow, compile_show
from busk.engine.clock import FakeClock
from busk.engine.loop import Engine, Frame
from busk.engine.snapshot import Sync
from busk.model.common import FixtureId, TargetRef
from busk.model.validate import validate_show
from reference_convert import reference_convert


@pytest.fixture
def compiled(appendix_a: dict[str, Any]) -> CompiledShow:
    show, _ = validate_show(json.dumps(appendix_a))
    assert show is not None
    return compile_show(show)


class RecordingEngine(Engine):
    """Records every published frame, stops after ``ticks`` frames and can
    simulate a slow tick by advancing the fake clock inside it."""

    def __init__(
        self,
        compiled: CompiledShow,
        clock: FakeClock,
        stop: threading.Event,
        ticks: int,
        stall: tuple[int, float] | None = None,  # (tick number, seconds)
    ) -> None:
        super().__init__(compiled, clock)
        self.fake_clock = clock
        self.stop = stop
        self.limit = ticks
        self.stall = stall
        self.frames: list[Frame] = []

    def tick(self, now: float) -> None:
        super().tick(now)
        assert self.latest is not None
        self.frames.append(self.latest)
        if self.stall is not None and self.stats.ticks == self.stall[0]:
            self.fake_clock.advance(self.stall[1])
        if len(self.frames) >= self.limit:
            self.stop.set()


def run_engine(
    compiled: CompiledShow, ticks: int, stall: tuple[int, float] | None = None
) -> RecordingEngine:
    stop = threading.Event()
    engine = RecordingEngine(compiled, FakeClock(), stop, ticks, stall)
    engine.run(stop)
    return engine


def test_nothing_is_published_before_the_first_tick(compiled: CompiledShow) -> None:
    assert Engine(compiled, FakeClock()).latest is None


APPENDIX_A_DEFAULTS = {
    # Converted slot defaults (see test_convert.py for the derivation): pan/tilt
    # centred, white from the white emitter, zoom midpoint, gobo and shutter open.
    1: 128, 3: 128, 8: 255, 11: 128, 12: 4, 13: 11,
    17: 128, 19: 128, 24: 255, 27: 128, 28: 4, 29: 11,
}  # fmt: skip


def nonzero(data: bytes) -> dict[int, int]:
    return {index + 1: value for index, value in enumerate(data) if value}


def test_tick_publishes_numbered_frames_of_the_converted_defaults(compiled: CompiledShow) -> None:
    engine = Engine(compiled, FakeClock())
    for seq, now in enumerate((0.0, 0.01, 0.02), start=1):
        engine.tick(now)
        frame = engine.latest
        assert frame is not None
        assert (frame.seq, frame.time) == (seq, now)
        assert len(frame.universes) == 1
        assert nonzero(frame.universes[0]) == APPENDIX_A_DEFAULTS
    assert engine.stats.ticks == 3


def test_tick_converts_the_given_logical_frame(compiled: CompiledShow) -> None:
    logical = compiled.slots.defaultFrame.copy()
    intensity = compiled.slots.find(
        TargetRef(fixtureId=FixtureId("fx-mh1"), element=0), "intensity"
    )
    assert intensity is not None
    logical[intensity.laneOffset] = 1.0
    before = logical.copy()
    engine = Engine(compiled, FakeClock(), logical)
    engine.tick(0.0)
    engine.tick(0.01)
    assert engine.latest is not None
    # MH 1's 16-bit dimmer at 9/10 goes to full; everything else keeps its default.
    assert nonzero(engine.latest.universes[0]) == {**APPENDIX_A_DEFAULTS, 9: 255, 10: 255}
    assert np.array_equal(logical, before, equal_nan=True)  # copied each tick, never modified


def test_logical_frame_must_match_the_slot_table(compiled: CompiledShow) -> None:
    with pytest.raises(ValueError, match="logical frame has shape"):
        Engine(compiled, FakeClock(), np.zeros(compiled.slots.laneCount + 1))


def test_frames_equal_the_reference_converter(compiled: CompiledShow) -> None:
    engine = Engine(compiled, FakeClock())
    engine.tick(0.0)
    assert engine.latest is not None
    expected = reference_convert(compiled, compiled.slots.defaultFrame)
    assert engine.latest.universes == tuple(row.tobytes() for row in expected)


def test_frames_are_immutable_snapshots(compiled: CompiledShow) -> None:
    engine = Engine(compiled, FakeClock())
    engine.tick(0.0)
    first = engine.latest
    engine.tick(0.01)
    assert first is not None
    assert engine.latest is not first  # a new object each tick: no tearing
    assert all(type(universe) is bytes and len(universe) == 512 for universe in first.universes)
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.seq = 99  # type: ignore[misc]


def test_run_ticks_at_exact_multiples_of_the_period(compiled: CompiledShow) -> None:
    engine = run_engine(compiled, ticks=500)
    assert [frame.time for frame in engine.frames] == [k / 100 for k in range(500)]
    assert [frame.seq for frame in engine.frames] == list(range(1, 501))
    assert engine.stats.overruns == 0
    assert engine.stats.maxTickSeconds == 0.0  # a fake clock does not move by itself


def test_a_slow_tick_is_dropped_not_caught_up(compiled: CompiledShow) -> None:
    # Tick 3 (due at 0.02 s) takes 35 ms at 100 Hz, so ticks due at 0.03,
    # 0.04 and 0.05 are already late when it ends at 0.055.
    engine = run_engine(compiled, ticks=10, stall=(3, 0.035))
    times = [frame.time for frame in engine.frames]
    assert engine.stats.overruns == 1
    assert engine.stats.maxTickSeconds == pytest.approx(0.035)
    assert times[3] == pytest.approx(0.055)  # the next tick runs at the stall's end
    gaps = [later - earlier for earlier, later in itertools.pairwise(times)]
    assert min(gaps) >= 0.01 - 1e-9  # no catch-up burst
    assert times[4:] == pytest.approx([0.055 + k / 100 for k in range(1, 7)])


def test_two_runs_produce_identical_frames(compiled: CompiledShow) -> None:
    first = run_engine(compiled, ticks=50, stall=(7, 0.02)).frames
    second = run_engine(compiled, ticks=50, stall=(7, 0.02)).frames
    assert first == second


def test_run_returns_promptly_when_already_stopped(compiled: CompiledShow) -> None:
    stop = threading.Event()
    stop.set()
    engine = Engine(compiled, FakeClock())
    engine.run(stop)
    assert engine.latest is None
    assert engine.stats.ticks == 0


# ---------------------------------------------- tick errors and the bounded drain (Phase 7)


class FailingEngine(RecordingEngine):
    """A recording engine whose ``tick`` raises on the calls numbered in
    ``failures`` (1-based); it stops after ``calls`` calls."""

    def __init__(
        self, compiled: CompiledShow, stop: threading.Event, failures: set[int], calls: int
    ) -> None:
        super().__init__(compiled, FakeClock(), stop, ticks=calls)
        self.failures = failures
        self.calls = 0
        self.max_calls = calls

    def tick(self, now: float) -> None:
        self.calls += 1
        if self.calls >= self.max_calls:
            self.stop.set()
        if self.calls in self.failures:
            raise RuntimeError("a bug")
        super().tick(now)


def test_a_tick_that_raises_is_counted_and_the_schedule_goes_on(compiled: CompiledShow) -> None:
    stop = threading.Event()
    engine = FailingEngine(compiled, stop, failures={2, 3}, calls=6)
    engine.run(stop)
    assert engine.stats.tickErrors == 2
    assert engine.stats.consecutiveTickErrors == 0  # reset by the good ticks after
    assert [frame.time for frame in engine.frames] == pytest.approx([0.0, 0.03, 0.04, 0.05])
    assert engine.stats.overruns == 0


def test_consecutive_tick_errors_are_counted(compiled: CompiledShow) -> None:
    stop = threading.Event()
    engine = FailingEngine(compiled, stop, failures={3, 4, 5}, calls=5)
    engine.run(stop)
    assert (engine.stats.tickErrors, engine.stats.consecutiveTickErrors) == (3, 3)


def test_a_flood_of_commands_is_applied_over_several_ticks_in_order(
    compiled: CompiledShow,
) -> None:
    engine = Engine(compiled, FakeClock())
    for k in range(1, 601):
        engine.bus.submit({"type": "SET_MASTER", "masterId": "m-gm", "level": k / 1000})
    engine.tick(0.0)
    assert engine.stats.commandsApplied == 512  # MAX_DRAIN
    assert engine.runtime.masterLevels["m-gm"] == 0.512
    engine.tick(0.01)
    assert engine.stats.commandsApplied == 600
    assert engine.runtime.masterLevels["m-gm"] == 0.6


def test_a_sync_marker_is_published_after_the_snapshot_of_its_tick(
    compiled: CompiledShow,
) -> None:
    engine = Engine(compiled, FakeClock())
    engine.bus.submit({"type": "BLACKOUT", "on": True})
    engine.bus.mark(Sync(token=7))
    assert engine.synced == 0
    engine.tick(0.0)
    assert engine.synced == 7
    assert engine.snapshot is not None
    assert engine.snapshot.blackout  # what was queued before the marker shows
    assert engine.stats.commandsApplied == 1  # the marker is not a command
    # Behind a flood, the marker waits for the tick that drains it.
    for k in range(600):
        engine.bus.submit({"type": "SET_MASTER", "masterId": "m-gm", "level": k / 1000})
    engine.bus.mark(Sync(token=8))
    engine.tick(0.01)
    assert engine.synced == 7
    engine.tick(0.02)
    assert engine.synced == 8
