"""The busking engine end to end: release-0 equivalence, determinism, tick-schedule
independence (§2.5), snapshots on change only, live-safety and memory."""

from __future__ import annotations

import gc
import tracemalloc
from typing import Any

import numpy as np
import pytest

from builders import APPENDIX_A, ROOT, compile_doc, lanes_of, load_doc, slot_of
from busk.compiler.compile import CompiledShow
from busk.engine.clock import FakeClock
from busk.engine.loop import Engine
from busk.engine.snapshot import EngineSnapshot, SpeedStatus
from busk.model.common import MasterId
from harness import (
    Harness,
    Script,
    blackout,
    fader,
    flash,
    go,
    master,
    release,
    set_bpm,
    tap,
    toggle,
    trigger,
)

GOLDEN = ROOT / "tests" / "fixtures" / "golden_7_8.json"


@pytest.fixture(scope="module")
def compiled() -> CompiledShow:
    """The §7.8 rig: Verse, Chorus, Blue and Red (exclusive) and Audience."""
    return compile_doc(load_doc(GOLDEN))


BUSY: Script = [
    (0.0, master("m-gm", 0.8)),
    (0.0, fader("pb-verse", 1.0)),
    (0.5, fader("pb-chorus", 0.01)),  # below the threshold: LTP waits
    (1.25, fader("pb-chorus", 0.6)),  # … and latches here
    (2.0, toggle("pb-red")),
    (3.3, trigger("pb-blue")),  # releases Red (exclusivity)
    (4.0, flash("pb-red", True)),
    (4.5, fader("pb-aud", 0.3)),
    (4.75, flash("pb-red", False)),
    (5.2, fader("pb-aud", 0.9)),
    (6.0, blackout(True)),
    (6.4, blackout(False)),
    (7.1, release("pb-blue", 0.7)),
    (8.0, go("pb-red")),
    (9.0, fader("pb-verse", 0.0)),  # autoRelease, 2 s
    (10.0, fader("pb-aud", 0.0)),
]
SHARED = [0.25, 1.0, 1.3, 2.5, 3.31, 4.2, 4.8, 5.5, 6.2, 7.5, 9.1, 10.0, 11.5, 12.0]


def grid(hz: float, until: float = 12.0) -> list[float]:
    return [k / hz for k in range(int(until * hz) + 1)]


def test_release_in_zero_seconds_gives_the_frame_without_the_playback(
    compiled: CompiledShow,
) -> None:
    """§20: releasing a source with release time 0 yields exactly the frame
    computed without it."""
    base = [
        (0.0, fader("pb-verse", 1.0)),
        (0.0, fader("pb-chorus", 0.6)),
        (0.5, fader("pb-aud", 0.5)),
    ]
    with_blue = Harness(compiled).run(
        [*base, (1.0, toggle("pb-blue")), (2.0, release("pb-blue", 0))], ticks=[1.5]
    )
    without = Harness(compiled).run(base, ticks=[1.5, 2.0])
    assert with_blue[1.5].universe != without[1.5].universe  # Blue was on its way in
    assert with_blue[2.0].universe == without[2.0].universe
    np.testing.assert_array_equal(with_blue[2.0].logical, without[2.0].logical)


def test_two_runs_give_identical_frame_sequences(compiled: CompiledShow) -> None:
    first = Harness(compiled).run(BUSY, ticks=grid(100))
    second = Harness(compiled).run(BUSY, ticks=grid(100))
    assert [o.frame for o in first.values()] == [o.frame for o in second.values()]
    assert [o.snapshot for o in first.values()] == [o.snapshot for o in second.values()]


def random_times(seed: int, count: int = 300) -> list[float]:
    return sorted(np.random.default_rng(seed).uniform(0, 12, count).tolist())


@pytest.mark.parametrize(
    "ticks",
    [grid(37), random_times(1), random_times(2, 40), []],
    ids=["37 Hz", "random", "sparse random", "shared times only"],
)
def test_frames_do_not_depend_on_the_tick_schedule(
    compiled: CompiledShow, ticks: list[float]
) -> None:
    """§2.5: changing the engine rate never changes how the show looks."""
    reference = Harness(compiled).run(BUSY, ticks=[*grid(100), *SHARED])
    other = Harness(compiled).run(BUSY, ticks=[*ticks, *SHARED])
    for t in SHARED:
        assert other[t].universe == reference[t].universe, f"t = {t}"
        np.testing.assert_array_equal(other[t].logical, reference[t].logical)


def test_the_busy_script_does_what_it_says(compiled: CompiledShow) -> None:
    run = Harness(compiled).run(BUSY, ticks=[*SHARED, 1.8])

    def states(t: float) -> dict[str, str]:
        snapshot = run[t].snapshot
        assert snapshot is not None
        return {status.id: status.state for status in snapshot.playbacks}

    def color(t: float) -> list[float]:
        return lanes_of(compiled, run[t].logical, "fx-mh2", "color")[:3]

    # Verse is halfway through its 2 s fade from white; Chorus is up but unlatched.
    assert color(1.0) == pytest.approx([1.0, 0.9, 0.8])
    assert color(1.8) == pytest.approx([1.0, 1.0, 1.0])  # latched at 1.25 with its 0.5 s fade
    assert color(2.5) == pytest.approx([1.0, 0.75, 0.75])  # Red, a quarter of the way in
    assert states(3.31)["pb-red"] == "releasing"
    assert lanes_of(compiled, run[6.2].logical, "fx-mh1", "intensity") == [0.0]  # blackout
    assert states(12.0) == {
        "pb-verse": "idle",  # autoRelease at 9 s, 2 s release
        "pb-chorus": "active",
        "pb-blue": "idle",
        "pb-red": "active",
        "pb-aud": "idle",
    }


def test_snapshots_are_published_only_on_change(compiled: CompiledShow) -> None:
    harness = Harness(compiled)
    first = harness.tick(0.0).snapshot
    assert first is not None
    assert first.seq == 1
    assert harness.tick(0.01).snapshot is first  # nothing happened
    harness.submit(release("pb-blue"))  # a no-op on an idle playback
    assert harness.tick(0.02).snapshot is first
    harness.submit(toggle("pb-blue"))
    active = harness.tick(0.03).snapshot
    assert active is not None
    assert active.seq == 2
    harness.submit(toggle("pb-blue"))  # release, 1 s
    releasing = harness.tick(0.04).snapshot
    assert releasing is not None
    assert releasing.seq == 3
    assert harness.tick(0.5).snapshot is releasing
    idle = harness.tick(1.04).snapshot  # the release finished: a new snapshot
    assert idle is not None
    assert (idle.seq, {s.id: s.state for s in idle.playbacks}["pb-blue"]) == (4, "idle")


def test_snapshots_show_the_current_cue_and_the_speed_masters() -> None:
    compiled = compile_doc(load_doc(APPENDIX_A))  # pb-song plays cl-song; m-speed at 120 BPM
    harness = Harness(compiled)
    initial = compiled.masters[MasterId("m-speed")].initialLevel  # the ×1 step
    first = harness.tick(0.0).snapshot
    assert first is not None
    assert first.masterLevels == (("m-gm", 1.0), ("m-speed", initial))  # show order
    assert first.speed == (
        SpeedStatus(
            id="m-speed", name="Speed 1", bpm=120.0, multiplier=1.0, level=initial,
            beatTime=0.0, beat=0.0,
        ),
    )  # fmt: skip
    assert {s.id: s.cue for s in first.playbacks}["pb-song"] is None  # idle
    harness.submit(go("pb-song"), set_bpm("m-speed", 128), master("m-speed", 1.0))
    second = harness.tick(0.01).snapshot
    assert second is not None
    assert second.speed == (  # SET_BPM rebased the anchor: 0.01 s at 120 BPM is 0.02 beats
        SpeedStatus(
            id="m-speed", name="Speed 1", bpm=128.0, multiplier=4.0, level=1.0,
            beatTime=0.01, beat=0.02,
        ),
    )  # fmt: skip
    assert dict(second.masterLevels)["m-speed"] == 1.0
    assert {s.id: s.cue for s in second.playbacks}["pb-song"] == "1"
    harness.submit(go("pb-song"))
    third = harness.tick(0.02).snapshot
    assert third is not None
    assert {s.id: s.cue for s in third.playbacks}["pb-song"] == "2"


def test_beat_anchors_change_only_at_taps_and_tempo_changes() -> None:
    """A speed master publishes its beat anchor, not its phase (phase-6-plan
    §5.7): a running master publishes nothing, a level change keeps the
    anchor, and a tap or SET_BPM moves it without a jump in the count."""
    harness = Harness(compile_doc(load_doc(APPENDIX_A)))  # m-speed at 120 BPM
    first = harness.tick(0.0).snapshot
    assert first is not None
    assert first.time == 0.0
    for t in (0.5, 1.0, 7.25):
        assert harness.tick(t).snapshot is first  # the beats run; nothing is published
    harness.submit(master("m-speed", 1.0))
    levelled = harness.tick(7.5).snapshot
    assert levelled is not None
    assert levelled.time == 7.5
    assert (levelled.speed[0].beatTime, levelled.speed[0].beat) == (0.0, 0.0)
    harness.submit(tap("m-speed"))
    tapped = harness.tick(8.1).snapshot  # 16.2 beats: the tap lands on beat 16
    assert tapped is not None
    (speed,) = tapped.speed
    assert (speed.beatTime, speed.beat, speed.bpm) == (8.1, 16.0, 120.0)
    harness.submit(set_bpm("m-speed", 60))
    rebased = harness.tick(9.1).snapshot
    assert rebased is not None
    (speed,) = rebased.speed
    assert speed.beatTime == 9.1
    assert speed.beat == pytest.approx(18.0)  # 1 s more at 120 BPM: the phase is kept
    assert harness.tick(20.0).snapshot is rebased
    assert speed.beats(11.1) == pytest.approx(20.0)  # then 2 s at 60 BPM


def test_snapshots_list_group_and_size_levels_and_not_effect_phases() -> None:
    """``masterLevels`` holds every master's own level in show order, so
    autosave and recovery bring group and size masters back; an effect
    changes the frame every tick but publishes nothing (phase-5-plan §5.13)."""
    doc = load_doc(APPENDIX_A)  # pb-pulse: a BPM pulse on g-mh, `size` fader
    doc["masters"] += [
        {"id": "m-heads", "kind": "group", "name": "Heads", "groupId": "g-mh"},
        {"id": "m-fx", "kind": "size", "name": "FX", "initialLevel": 0.8},
    ]
    compiled = compile_doc(doc)
    harness = Harness(compiled)
    initial = compiled.masters[MasterId("m-speed")].initialLevel
    first = harness.tick(0.0).snapshot
    assert first is not None
    assert first.masterLevels == (
        ("m-gm", 1.0), ("m-speed", initial), ("m-heads", 1.0), ("m-fx", 0.8)
    )  # fmt: skip
    harness.submit(master("m-heads", 0.4), master("m-fx", 0.3))
    levels = harness.tick(0.01).snapshot
    assert levels is not None
    assert levels.masterLevels == (
        ("m-gm", 1.0), ("m-speed", initial), ("m-heads", 0.4), ("m-fx", 0.3)
    )  # fmt: skip
    # The pulse multiplies the Verse's intensity.
    harness.submit(fader("pb-song", 1.0), go("pb-song"), toggle("pb-pulse"), fader("pb-pulse", 1))
    running = harness.tick(0.02).snapshot
    assert running is not None
    assert {s.id: s.state for s in running.playbacks}["pb-pulse"] == "active"
    levels_seen = set()
    for k in range(50):  # the Verse is in and the pulse at full size: only the pulse moves
        result = harness.tick(3.0 + k * 0.05)
        assert result.snapshot is running
        levels_seen.add(lanes_of(compiled, result.logical, "fx-mh1", "intensity")[0])
    assert len(levels_seen) > 10  # 1 Hz, 20 ticks a cycle


def song(snapshot: EngineSnapshot | None) -> tuple[str | None, str | None, str | None]:
    """pb-song's ``(cue, cueName, next)`` in ``snapshot``."""
    assert snapshot is not None
    status = {s.id: s for s in snapshot.playbacks}["pb-song"]
    return status.cue, status.cueName, status.next


def test_the_cue_and_what_go_goes_to_change_only_at_events() -> None:
    """cl-song is ``1 Verse, 2 Chorus``: no wrap, no releaseAtEnd."""
    compiled = compile_doc(load_doc(APPENDIX_A))
    harness = Harness(compiled)
    idle = harness.tick(0.0).snapshot
    assert song(idle) == (None, None, "1")  # GO starts at the first cue
    harness.submit(go("pb-song"))
    verse = harness.tick(0.01).snapshot
    assert song(verse) == ("1", "Verse", "2")
    assert harness.tick(0.5).snapshot is verse  # mid-fade, beats going by: no event
    harness.submit(go("pb-song"))
    chorus = harness.tick(1.0).snapshot
    assert song(chorus) == ("2", "Chorus", None)  # the end of a list that does not wrap
    harness.submit(release("pb-song", 1.0))
    releasing = harness.tick(1.5).snapshot
    assert song(releasing) == ("2", "Chorus", "1")  # GO would start it again
    assert harness.tick(2.0).snapshot is releasing
    assert song(harness.tick(2.6).snapshot) == (None, None, "1")  # released


def test_a_chase_publishes_its_step_and_the_next_one() -> None:
    doc = load_doc(APPENDIX_A)
    doc["cueLists"][0].update(
        mode="chase",
        chase={"rate": {"kind": "hz", "value": 2.0}, "direction": "forward", "crossfade": 0},
    )
    harness = Harness(compile_doc(doc))
    harness.tick(0.0)
    harness.submit(go("pb-song"))
    first = harness.tick(0.01).snapshot
    assert song(first) == ("1", "Verse", "2")
    assert harness.tick(0.4).snapshot is first
    second = harness.tick(0.51).snapshot  # a step: a new snapshot
    assert song(second) == ("2", "Chorus", "1")  # a chase wraps
    assert {s.id: s.chase for s in first.playbacks if s.id in ("pb-song", "pb-blue")} == {
        "pb-song": True,
        "pb-blue": False,
    }


def test_a_command_that_raises_is_counted_and_ticking_goes_on(
    compiled: CompiledShow, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = Harness(compiled)
    playbacks = harness.engine.runtime.playbacks

    def boom(*args: Any) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr(playbacks, "trigger", boom)
    harness.submit(trigger("pb-blue"), fader("pb-verse", 1.0))
    observed = harness.tick(0.0)
    stats = harness.engine.stats
    assert (stats.commandErrors, stats.commandsApplied, stats.ticks) == (1, 1, 1)
    assert observed.frame.seq == 1
    assert observed.snapshot is not None
    verse = {s.id: s for s in observed.snapshot.playbacks}["pb-verse"]
    assert (verse.state, verse.faderLevel) == ("active", 1.0)  # the next command applied
    later = harness.tick(2.0)
    assert lanes_of(compiled, later.logical, "fx-mh1", "intensity") == [0.4]


def test_commands_apply_at_the_tick_that_drains_them(compiled: CompiledShow) -> None:
    clock = FakeClock()
    engine = Engine(compiled, clock)
    engine.bus.submit(toggle("pb-blue"))  # issued at 0 …
    engine.tick(1.0)  # … applied at 1.0: the 2 s fade starts here
    engine.tick(2.0)
    assert lanes_of(compiled, engine.logical, "fx-mh1", "color")[:3] == pytest.approx(
        [0.5, 0.5, 1.0]
    )


def test_the_base_frame_feeds_uncontrolled_slots(compiled: CompiledShow) -> None:
    base = compiled.slots.defaultFrame.copy()
    base[slot_of(compiled, "fx-mh2", "tilt").lanes] = 40.0  # as `busk run --values` would
    harness = Harness(compiled, base)
    harness.submit(fader("pb-verse", 1.0))
    harness.tick(0.0)
    observed = harness.tick(5.0)  # Verse is fully in
    assert lanes_of(compiled, observed.logical, "fx-mh2", "tilt") == [40.0]
    assert lanes_of(compiled, observed.logical, "fx-mh2", "intensity") == [0.4]


def test_steady_ticking_does_not_grow_memory(compiled: CompiledShow) -> None:
    harness = Harness(compiled)
    harness.run(BUSY[:6], ticks=grid(100, until=5.0))  # a steady look: every fade has ended
    engine = harness.engine
    gc.collect()
    tracemalloc.start()
    try:
        for k in range(1000):  # warm up under tracing
            engine.tick(5.0 + k / 100)
        before = tracemalloc.take_snapshot()
        for k in range(10_000):
            engine.tick(15.0 + k / 100)
        gc.collect()
        after = tracemalloc.take_snapshot()
    finally:
        tracemalloc.stop()
    growth = sum(stat.size_diff for stat in after.compare_to(before, "filename"))
    assert growth < 16 * 1024, f"{growth} bytes after 10 000 ticks"
