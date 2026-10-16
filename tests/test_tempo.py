"""Speed masters: the beat count, tap tempo, ``SET_BPM`` and multiplier steps
(§11.3, phase-4-plan decision 11 and §5.8)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from builders import busk_rig, compile_doc, grand_master, speed_master
from busk.compiler.compile import CompiledShow
from busk.compiler.playbacks import CompiledMaster
from busk.engine.install import EMPTY_FRAME, Install
from busk.engine.masters import SpeedMasterRuntime
from harness import Harness, master, set_bpm, tap


def compiled_master(
    bpm: float = 120.0,
    steps: Sequence[float] = (0.25, 0.5, 1.0, 2.0, 4.0),
    initial: float | None = None,
) -> CompiledMaster:
    """The compiled form of one speed master."""
    doc = busk_rig(spots=1)
    doc["masters"].append(speed_master(bpm=bpm, steps=steps, initial=initial))
    return compile_doc(doc).masters["m-speed"]  # type: ignore[index]


def runtime(bpm: float = 120.0, now: float = 0.0) -> SpeedMasterRuntime:
    return SpeedMasterRuntime(compiled_master(bpm), now)


def taps(rt: SpeedMasterRuntime, *times: float) -> SpeedMasterRuntime:
    for t in times:
        rt.tap(t)
    return rt


# ---------------------------------------------------------------- beat count


def test_the_beat_count_starts_at_zero_at_the_default_tempo() -> None:
    rt = runtime(bpm=120.0, now=10.0)
    assert rt.beats(10.0) == 0.0
    assert rt.beats(11.0) == pytest.approx(2.0)
    assert rt.time_of(5.0) == pytest.approx(12.5)
    assert rt.time_of(rt.beats(13.37)) == pytest.approx(13.37)


def test_set_bpm_keeps_the_phase() -> None:
    rt = runtime(bpm=120.0)
    rt.set_bpm(11.25, 60.0)  # at beat 22.5
    assert rt.bpm == 60.0
    assert rt.beats(11.25) == pytest.approx(22.5)
    assert rt.beats(12.25) == pytest.approx(23.5)  # one beat per second from here
    assert rt.time_of(24.0) == pytest.approx(12.75)
    assert rt.taps == []  # a typed tempo is not a tap


# ---------------------------------------------------------------- tap tempo


def test_two_taps_set_the_tempo() -> None:
    rt = taps(runtime(bpm=120.0), 10.0)
    assert rt.bpm == 120.0  # one tap only moves the phase
    rt.tap(10.4)
    assert rt.bpm == pytest.approx(150.0)


def test_eight_steady_taps_and_only_the_last_eight_count() -> None:
    rt = taps(runtime(bpm=90.0), *(0.5 * k for k in range(8)))
    assert rt.bpm == pytest.approx(120.0)
    # Three slow taps, then eight at 0.5 s: the slow intervals leave the window.
    rt = taps(runtime(bpm=90.0), 0.0, 0.6, 1.2, *(1.7 + 0.5 * k for k in range(7)))
    assert len(rt.taps) == 8
    assert rt.bpm == pytest.approx(120.0)


def test_an_outlier_interval_is_dropped() -> None:
    # Intervals 0.5, 0.5, 0.5, 0.8, 0.5: the median is 0.5 and 0.8 is 60 % off.
    rt = taps(runtime(bpm=90.0), 0.0, 0.5, 1.0, 1.5, 2.3, 2.8)
    assert rt.bpm == pytest.approx(120.0)
    # 0.6 is within 25 % of the median, so it is averaged in.
    rt = taps(runtime(bpm=90.0), 0.0, 0.5, 1.0, 1.6, 2.1)
    assert rt.bpm == pytest.approx(60 / 0.525)


def test_with_no_interval_near_the_median_the_last_one_counts() -> None:
    rt = taps(runtime(bpm=90.0), 0.0, 0.4, 1.6)  # 0.4 and 1.2 around a median of 0.8
    assert rt.bpm == pytest.approx(50.0)


def test_a_gap_over_two_seconds_starts_a_new_run() -> None:
    rt = taps(runtime(bpm=90.0), 0.0, 0.5)
    assert rt.bpm == pytest.approx(120.0)
    rt.tap(3.0)  # 2.5 s later: the first tap of a new run
    assert rt.bpm == pytest.approx(120.0)
    assert rt.taps == [3.0]
    rt.tap(3.4)  # only the new run's interval counts
    assert rt.bpm == pytest.approx(150.0)
    rt = taps(runtime(bpm=90.0), 0.0, 2.0)  # exactly 2 s is not a gap
    assert rt.bpm == pytest.approx(30.0)


def test_every_tap_moves_the_phase_to_the_nearest_beat() -> None:
    rt = runtime(bpm=120.0)
    rt.tap(10.2)  # beat 20.4 → 20
    assert rt.beats(10.2) == 20.0
    assert rt.beats(10.7) == pytest.approx(21.0)
    rt = runtime(bpm=120.0)
    rt.tap(10.4)  # beat 20.8 → 21: the phase can move forward
    assert rt.beats(10.4) == 21.0


def test_the_second_tap_rounds_the_phase_under_the_old_tempo() -> None:
    rt = taps(runtime(bpm=120.0), 10.2)  # beat 20 at 10.2
    rt.tap(10.6)  # beat 20.8 at 120 BPM → 21; then 150 BPM from there
    assert rt.bpm == pytest.approx(150.0)
    assert rt.beats(10.6) == 21.0
    assert rt.beats(11.0) == pytest.approx(22.0)


def test_a_repeated_tap_at_the_same_time_is_ignored() -> None:
    rt = taps(runtime(bpm=90.0), 1.0, 1.0)
    assert rt.bpm == 90.0
    assert rt.taps == [1.0]
    rt.tap(1.5)
    assert rt.bpm == pytest.approx(120.0)


def test_tapped_tempo_is_capped_at_999_bpm() -> None:
    rt = taps(runtime(bpm=120.0), 0.0, 0.05)
    assert rt.bpm == 999.0


# ---------------------------------------------------------------- multiplier steps


@pytest.mark.parametrize(
    ("level", "multiplier"),
    [
        (0.0, 0.25),
        (0.12, 0.25),
        (0.125, 0.5),  # step 0.5 rounds up
        (0.5, 1.0),
        (0.6, 1.0),
        (0.625, 2.0),
        (0.875, 4.0),
        (1.0, 4.0),
    ],
)
def test_the_level_selects_a_multiplier_step(level: float, multiplier: float) -> None:
    rt = runtime()
    rt.set_level(level)
    assert rt.level == level
    assert rt.multiplier == multiplier


@pytest.mark.parametrize(
    ("steps", "initial", "level", "multiplier"),
    [
        ((0.25, 0.5, 1.0, 2.0, 4.0), None, 0.5, 1.0),  # the step whose value is 1
        ((0.5, 1.0, 2.0), None, 0.5, 1.0),
        ((1.0, 2.0), None, 0.0, 1.0),
        ((0.5, 1.0, 2.0), 1.0, 1.0, 2.0),  # initialLevel wins
        ((0.5, 3.0), None, 0.0, 0.5),  # no step of 1: the nearest by ratio
        ((2.0,), None, 1.0, 2.0),  # one step: any level selects it
    ],
)
def test_the_default_level(
    steps: tuple[float, ...], initial: float | None, level: float, multiplier: float
) -> None:
    compiled = compiled_master(steps=steps, initial=initial)
    assert compiled.multiplierSteps == steps
    assert compiled.initialLevel == level
    rt = SpeedMasterRuntime(compiled, 0.0)
    assert (rt.level, rt.multiplier) == (level, multiplier)


def test_compiled_speed_fields() -> None:
    compiled = compiled_master(bpm=128.0)
    assert (compiled.kind, compiled.defaultBpm, compiled.tap) == ("speed", 128.0, True)


# ---------------------------------------------------------------- through the engine


@pytest.fixture(scope="module")
def show() -> CompiledShow:
    doc = busk_rig(spots=1)
    doc["masters"] += [grand_master(), speed_master(), speed_master("m-other", bpm=90.0)]
    return compile_doc(doc)


def test_masters_start_counting_at_the_first_tick(show: CompiledShow) -> None:
    harness = Harness(show)
    harness.tick(5.0)
    speed = harness.engine.runtime.speed
    assert list(speed) == ["m-speed", "m-other"]
    assert speed["m-speed"].beats(5.0) == 0.0
    assert speed["m-speed"].beats(6.0) == pytest.approx(2.0)
    assert speed["m-other"].bpm == 90.0
    assert harness.engine.runtime.masterLevels == {"m-gm": 1.0}  # grand masters only


def test_tap_set_bpm_and_set_master_through_the_engine(show: CompiledShow) -> None:
    harness = Harness(show)
    harness.run(
        [
            (10.0, tap("m-speed")),
            (10.4, tap("m-speed")),
            (12.0, set_bpm("m-other", 60.0)),
            (13.0, master("m-speed", 1.0)),
            (13.0, master("m-gm", 0.5)),
        ],
        ticks=[0.0],
    )
    speed = harness.engine.runtime.speed
    tapped, other = speed["m-speed"], speed["m-other"]
    assert tapped.bpm == pytest.approx(150.0)
    assert tapped.beats(10.4) == 21.0  # 20 at 10.0, then 20.8 → 21
    assert tapped.multiplier == 4.0
    assert other.bpm == 60.0
    assert other.beats(12.0) == pytest.approx(18.0)  # 1.5 beats a second until 12 s
    assert other.beats(13.0) == pytest.approx(19.0)
    assert other.multiplier == 1.0  # untouched
    assert harness.engine.runtime.masterLevels == {"m-gm": 0.5}
    assert harness.engine.stats.commandErrors == 0


def edited(show: CompiledShow, *masters: dict[str, Any]) -> Install:
    """A live edit that replaces the show's masters."""
    doc = busk_rig(spots=1)
    doc["masters"] += list(masters)
    compiled = compile_doc(doc)
    assert compiled.slots.byKey == show.slots.byKey
    return Install(compiled=compiled, remap=None, programmer=EMPTY_FRAME)


def test_a_master_added_by_an_edit_starts_at_its_install_tick(show: CompiledShow) -> None:
    harness = Harness(show)
    harness.run([(3.0, tap("m-speed")), (3.5, tap("m-speed"))], ticks=[0.0])
    harness.submit(set_bpm("m-speed", 100.0), master("m-speed", 0.75))
    harness.tick(4.0)
    harness.engine.bus.install(
        edited(show, speed_master(bpm=60.0, steps=(1.0, 3.0)), speed_master("m-new", bpm=150.0))
    )
    harness.tick(7.25)
    speed = harness.engine.runtime.speed
    assert list(speed) == ["m-speed", "m-new"]  # m-other is gone
    kept, new = speed["m-speed"], speed["m-new"]
    # The surviving master keeps its tempo, phase and level; its step comes
    # from the edited steps.
    assert kept.bpm == 100.0
    assert kept.beats(4.0) == pytest.approx(8.0)  # beat 7 at 3.5, then 2 beats/s for 0.5 s
    assert kept.beats(7.25) == pytest.approx(8.0 + 100 / 60 * 3.25)
    assert (kept.level, kept.multiplier) == (0.75, 3.0)
    assert (new.bpm, new.beats(7.25), new.beats(8.25)) == (150.0, 0.0, pytest.approx(2.5))


def test_a_command_for_a_deleted_master_is_a_command_error(show: CompiledShow) -> None:
    harness = Harness(show)
    harness.tick(0.0)
    harness.engine.bus.install(edited(show))  # deletes every speed master
    harness.submit(tap("m-speed"))  # validated against the show before the edit
    harness.tick(1.0)
    assert harness.engine.stats.commandErrors == 1
    assert harness.engine.runtime.speed == {}
