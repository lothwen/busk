"""Effect clocks: Hz positions, beat lock and the tap nudge (phase-5-plan §5.4,
decisions 1–2, 14–15; step 5).

Speed masters here start counting at t = 0, at 120 BPM unless a test says
otherwise: a beat every 0.5 s, so ``beats(t) = 2t`` until the first event.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from builders import busk_rig, compile_doc, speed_master
from busk.compiler.effects import CompiledEffect
from busk.engine.effects import NUDGE_BEATS, EffectClock, tempo
from busk.engine.masters import SpeedMasterRuntime


def beat_master(
    bpm: float = 120.0, steps: tuple[float, ...] = (1.0,), master_id: str = "m-speed"
) -> SpeedMasterRuntime:
    doc = busk_rig(spots=1)
    doc["masters"].append(speed_master(master_id, bpm=bpm, steps=steps))
    return SpeedMasterRuntime(compile_doc(doc).masters[master_id], 0.0)  # type: ignore[index]


def effect(**fields: Any) -> CompiledEffect:
    """A compiled effect without layers: only its rate fields matter here."""
    doc: dict[str, Any] = {
        "key": "e1",
        "rate": "hz",
        "hz": 1.0,
        "masterId": None,
        "multiplier": 1.0,
        "speedMasterId": None,
        "direction": "forward",
        "size": 1.0,
        "sizeFadeIn": None,
        "sizeMasterId": None,
        "layers": (),
        "targets": (),
    }
    doc.update(fields)
    return CompiledEffect(**doc)


def off_grid(clock: EffectClock, t: float) -> float:
    """How far a BPM clock is from its grid at ``t``, in cycles: the distance
    from ``P − m·B`` to the nearest multiple of ``g = min(m, 1)``."""
    assert clock.master is not None
    g = min(clock.rate, 1.0)
    offset = (clock.position(t) - clock.rate * clock.master.beats(t)) / g
    return abs(offset - round(offset)) * g


def tap(clock: EffectClock, t: float) -> tuple[float, float]:
    """A tap on the clock's master as ``Playbacks.tap`` does it: read the
    position, tap, align. Returns the positions just before and after."""
    assert clock.master is not None
    before = clock.position(t)
    clock.master.tap(t)
    clock.align(t, before)
    return before, clock.position(t)


# ------------------------------------------------------------------ Hz clocks


def test_an_hz_clock_starts_at_zero() -> None:
    clock = EffectClock(10.0, 2.0)
    assert clock.position(10.0) == 0.0
    assert clock.position(11.25) == 2.5


def test_an_hz_rate_change_rebases_without_a_jump() -> None:
    clock = EffectClock(10.0, 2.0)
    clock.rerate(10.75, 4.0, None)  # at position 1.5
    assert clock.position(10.75) == 1.5
    assert clock.position(11.0) == 2.5


# ----------------------------------------------------------------- BPM clocks


@settings(max_examples=200, deadline=None)
@given(
    now=st.floats(0.0, 1000.0),
    m=st.sampled_from([0.25, 0.5, 1.0, 1.25, 2.0, 3.0, 4.0]),
    bpm=st.floats(30.0, 300.0),
)
def test_a_bpm_clock_starts_on_the_grid_nearest_zero(now: float, m: float, bpm: float) -> None:
    clock = EffectClock(now, m, beat_master(bpm))
    assert abs(clock.position(now)) <= min(m, 1.0) / 2 + 1e-9
    assert off_grid(clock, now) < 1e-6
    assert off_grid(clock, now + 7.3) < 1e-6  # and stays on it: no nudge at start
    assert clock.error == 0.0


def test_a_bpm_clock_follows_the_beat_count_through_set_bpm() -> None:
    master = beat_master()
    clock = EffectClock(3.0, 1.0, master)  # beat 6: P = beats − 6
    assert clock.position(4.0) == 2.0
    master.set_bpm(4.0, 60.0)  # beat 8, then a beat per second
    assert clock.position(4.0) == 2.0
    assert clock.position(5.5) == 3.5


def test_the_worked_example() -> None:
    """§5.4: a pulse at ×1 started at t = 3 (beat 6) on 120 BPM, so its grid
    is ``P = beats − 6``; four taps at 128 BPM."""
    master = beat_master()
    clock = EffectClock(3.0, 1.0, master)
    assert (clock.p0, clock.b0) == (0.0, 6.0)

    assert tap(clock, 10.0) == (14.0, 14.0)  # tap 1: nothing moves
    assert (clock.p0, clock.error) == (14.0, 0.0)

    assert tap(clock, 10.46875) == (14.9375, 14.9375)  # tap 2: 128 BPM, P continuous
    assert master.bpm == pytest.approx(128.0)
    assert (clock.p0, clock.error, clock.b0) == (15.0, -0.0625, 21.0)
    assert clock.position(10.703125) == pytest.approx(15.5 - 0.03125)  # half way: half the nudge
    assert clock.position(10.9375) == pytest.approx(16.0)  # closed by beat 22: on the grid

    assert tap(clock, 10.9375) == pytest.approx((16.0, 16.0))  # tap 3: on the grid
    assert (clock.p0, clock.error) == (16.0, pytest.approx(0.0, abs=1e-12))
    assert tap(clock, 11.40625) == pytest.approx((17.0, 17.0))  # tap 4
    assert off_grid(clock, 11.40625) < 1e-12


def test_a_second_tap_mid_nudge_is_continuous_too() -> None:
    master = beat_master()
    clock = EffectClock(0.0, 1.0, master)  # P = beats = 2t
    assert tap(clock, 0.3) == (0.6, 0.6)  # the tap lands on beat 1: P = 1 − 0.4 nudge
    assert (clock.p0, clock.error) == (1.0, pytest.approx(-0.4))
    before, after = tap(clock, 0.55)  # mid-nudge, P = 1.5 − 0.2; now 240 BPM, beat 2
    assert before == after == pytest.approx(1.3)
    assert master.bpm == pytest.approx(240.0)
    assert (clock.p0, clock.error) == (1.0, pytest.approx(0.3))  # nearest grid position
    assert clock.position(0.8) == pytest.approx(2.0)  # a beat later: on the grid
    assert off_grid(clock, 0.8) < 1e-12


@settings(max_examples=300, deadline=None)
@given(
    bpm=st.floats(40.0, 240.0),
    m=st.sampled_from([0.25, 0.5, 1.0, 1.5, 2.0, 4.0]),
    start=st.floats(0.0, 10.0),
    gaps=st.lists(st.floats(0.05, 3.0), min_size=1, max_size=6),
)
def test_taps_never_jump_and_land_on_the_grid_a_beat_later(
    bpm: float, m: float, start: float, gaps: list[float]
) -> None:
    master = beat_master(bpm)
    clock = EffectClock(start, m, master)
    t = start
    previous = clock.position(t)
    for gap in gaps:
        for k in range(1, 9):  # never backwards between events
            sample = clock.position(t + gap * k / 8)
            assert sample >= previous - 1e-9
            previous = sample
        t += gap
        before, after = tap(clock, t)
        assert after == pytest.approx(before, abs=1e-9)  # continuous at the tap
        assert abs(clock.error) <= min(m, 1.0) / 2 + 1e-9
    beat_later = master.time_of(master.beats(t) + NUDGE_BEATS)
    assert off_grid(clock, beat_later) < 1e-6


# ---------------------------------------------------------------------- rates


def test_a_bpm_rate_is_the_product_of_its_factors() -> None:
    master = beat_master(steps=(1.0, 4.0))
    master.set_level(1.0)
    speed = {"m-speed": master}
    pulse = effect(rate="bpm", hz=0.0, masterId="m-speed", multiplier=0.5)
    assert tempo(pulse, speed, None) == (0.5 * 4.0, master)
    assert tempo(pulse, speed, 0.75) == (0.5 * 4.0 * 2.0, master)  # rate fader ×2, quantised
    assert tempo(pulse, speed, 0.7) == (0.5 * 4.0 * 2.0, master)  # 4^0.4 ≈ 1.74 → ×2
    assert tempo(pulse, speed, 0.6) == (0.5 * 4.0, master)  # 4^0.2 ≈ 1.32 → ×1


def test_an_hz_rate_follows_the_rate_fader_and_its_speed_master_step() -> None:
    master = beat_master(steps=(1.0, 2.0))
    speed = {"m-speed": master}
    circle = effect(hz=2.0)
    assert tempo(circle, speed, None) == (2.0, None)
    assert tempo(circle, speed, 0.0) == (0.5, None)  # ×¼
    assert tempo(circle, speed, 0.75) == pytest.approx((4.0, None))  # ×2, not quantised
    stepped = effect(hz=2.0, speedMasterId="m-speed")
    assert tempo(stepped, speed, None) == (2.0, None)
    master.set_level(1.0)  # the ×2 step
    assert tempo(stepped, speed, None) == (4.0, None)  # no lock: only the step counts


def test_an_hz_effect_with_a_speed_master_ignores_its_taps() -> None:
    master = beat_master(steps=(1.0, 2.0))
    stepped = effect(hz=2.0, speedMasterId="m-speed")
    clock = EffectClock(1.0, *tempo(stepped, {"m-speed": master}, None))
    assert clock.master is None
    master.tap(1.3)
    master.tap(1.6)
    assert clock.position(2.0) == 2.0


def test_a_master_step_change_realigns_a_bpm_clock_with_a_nudge() -> None:
    master = beat_master(steps=(1.0, 2.0))
    speed = {"m-speed": master}
    pulse = effect(rate="bpm", hz=0.0, masterId="m-speed")
    clock = EffectClock(0.0, *tempo(pulse, speed, None))  # P = beats = 2t
    master.set_level(1.0)  # ×2 at t = 1.2 (beat 2.4, P = 2.4)
    clock.rerate(1.2, *tempo(pulse, speed, None))
    assert clock.rate == 2.0
    assert clock.position(1.2) == pytest.approx(2.4)
    assert clock.p0 == pytest.approx(2.0 * 2.4 + round(2.4 - 4.8))  # 2.8: nearest the old P
    assert clock.error == pytest.approx(-0.4)
    assert off_grid(clock, 1.7) < 1e-12  # a beat later: on the ×2 grid
    assert clock.position(1.7) == pytest.approx(4.8)


def test_a_rate_fader_rerates_an_hz_clock_without_a_jump() -> None:
    circle = effect(hz=1.0)
    clock = EffectClock(0.0, *tempo(circle, {}, 0.5))
    clock.rerate(2.5, *tempo(circle, {}, 1.0))  # ×4 from position 2.5
    assert clock.position(2.5) == 2.5
    assert clock.position(3.0) == 4.5


def test_the_same_rate_leaves_a_nudge_running() -> None:
    master = beat_master()
    clock = EffectClock(0.0, 1.0, master)
    tap(clock, 0.3)
    error = clock.error
    clock.rerate(0.4, 1.0, master)
    assert clock.error == error
    assert clock.position(0.4) == pytest.approx(1.2 - 0.4 * 0.8)  # beat 1.2, 0.8 of the nudge left


def test_switching_between_hz_and_bpm_is_continuous() -> None:
    master = beat_master()
    clock = EffectClock(0.0, 0.5)  # Hz: P = t/2
    clock.rerate(1.3, 1.0, master)  # to ×1 on the beat: beat 2.6, P = 0.65
    assert clock.position(1.3) == pytest.approx(0.65)
    assert clock.p0 == pytest.approx(0.6)  # 2.6 + round(0.65 − 2.6)
    assert off_grid(clock, 1.8) < 1e-12
    clock.rerate(2.0, 3.0, None)  # back to Hz, 3 cycles per second
    on = clock.position(2.0)
    assert (clock.error, clock.position(2.5)) == (0.0, pytest.approx(on + 1.5))


def test_a_new_master_at_the_same_rate_locks_to_it() -> None:
    master = beat_master()
    clock = EffectClock(0.0, 1.0)  # Hz: one cycle per second
    clock.rerate(1.3, 1.0, master)  # one cycle per beat now: P = 1.3 at beat 2.6
    assert clock.master is master
    assert clock.position(1.3) == pytest.approx(1.3)
    assert off_grid(clock, 1.8) < 1e-12
