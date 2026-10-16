"""Chases: step timing, crossfades, directions, beat lock and rate faders
(phase-4-plan §5.7, decisions 10–12; step 11).

The rig is four Appendix A spots, ``fx-mh1…4``. The chase ``cl-chase`` on
playback ``pb`` has one cue per spot: cue ``k`` puts ``fx-mhk`` at full, so
the lit spot shows the step. The speed master ``m-speed`` runs at 120 BPM
(a beat every 0.5 s) from the first tick, at t = 0.
"""

from __future__ import annotations

import itertools
import random
import zlib
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from builders import (
    Doc,
    busk_rig,
    compile_doc,
    cue,
    cue_list,
    entry,
    lanes_of,
    literal,
    playback,
    speed_master,
    targets,
)
from busk.compiler.compile import CompiledShow
from busk.compiler.playbacks import CompiledChase
from busk.engine.chase import (
    ChaseClock,
    ChaseRuntime,
    CueOrder,
    beat_factor,
    chase_seed,
    rate_factor,
)
from busk.engine.masters import SpeedMasterRuntime
from busk.engine.playback_runtime import PlaybackRuntime
from harness import (
    Harness,
    Observation,
    Script,
    back,
    fader,
    go,
    goto,
    master,
    release,
    set_bpm,
    tap,
    trigger,
)

SPOTS = ("fx-mh1", "fx-mh2", "fx-mh3", "fx-mh4")


def hz(value: float) -> Doc:
    return {"kind": "hz", "value": value}


def bpm(multiplier: float = 1.0) -> Doc:
    return {"kind": "bpm", "masterId": "m-speed", "multiplier": multiplier}


def chase_show(
    rate: Doc,
    direction: str = "forward",
    crossfade: float = 0.0,
    curve: str = "linear",
    fader_kind: str = "none",
    cues: int = 4,
) -> CompiledShow:
    doc = busk_rig(spots=4)
    doc["masters"].append(speed_master())
    steps = [
        cue(
            f"c{k}",
            entry(targets(SPOTS[k - 1]), "intensity", literal(1.0)),
            number=str(k),
            curve=curve,
            fade_in=7.0,  # ignored in chase mode: the crossfade sets the timing
        )
        for k in range(1, cues + 1)
    ]
    chase = cue_list("cl-chase", 1, *steps)
    chase.update(mode="chase", chase={"rate": rate, "direction": direction, "crossfade": crossfade})
    doc["cueLists"].append(chase)
    doc["playbacks"].append(playback("pb", 1, "cl-chase", fader=fader_kind))
    return compile_doc(doc)


def runtime(harness: Harness) -> PlaybackRuntime:
    return harness.engine.runtime.playbacks.runtimes["pb"]


def levels(compiled: CompiledShow, seen: Observation) -> tuple[float, ...]:
    return tuple(round(lanes_of(compiled, seen.logical, spot, "intensity")[0], 9) for spot in SPOTS)


def lit(compiled: CompiledShow, seen: Observation) -> int | None:
    """The index of the one spot at full, or ``None``."""
    full = [k for k, level in enumerate(levels(compiled, seen)) if level == 1.0]
    return full[0] if len(full) == 1 else None


def cues_at(compiled: CompiledShow, script: Script, times: list[float]) -> list[int | None]:
    harness = Harness(compiled)
    seen = harness.run(script, [0.0, *times])
    return [lit(compiled, seen[t]) for t in times]


# ---------------------------------------------------------------- pure parts


@pytest.mark.parametrize(
    ("level", "factor", "beat"),
    [
        (0.0, 0.25, 0.25),
        (0.125, 0.25**0.75, 0.5),  # halves round up
        (0.5, 1.0, 1.0),
        (0.6, 4**0.2, 1.0),
        (0.7, 4**0.4, 2.0),
        (0.75, 2.0, 2.0),
        (1.0, 4.0, 4.0),
    ],
)
def test_rate_fader_factors(level: float, factor: float, beat: float) -> None:
    assert rate_factor(level) == pytest.approx(factor)
    assert beat_factor(level) == beat


def walk(order: CueOrder, start: int, count: int) -> list[int]:
    cues = [start]
    for _ in range(count):
        cues.append(order.step(cues[-1]))
    return cues


@pytest.mark.parametrize(
    ("direction", "first", "steps", "back"),
    [
        ("forward", 0, [0, 1, 2, 3, 0, 1], 3),
        ("reverse", 3, [3, 2, 1, 0, 3, 2], 0),
        ("bounce", 0, [0, 1, 2, 3, 2, 1, 0, 1, 2], 1),
    ],
)
def test_cue_order(direction: Any, first: int, steps: list[int], back: int) -> None:
    order = CueOrder(direction, 4, seed=0)
    assert order.first() == first
    assert walk(order, first, len(steps) - 1) == steps
    assert CueOrder(direction, 4, seed=0).back(first) == back


def test_bounce_back_turns_at_the_ends() -> None:
    order = CueOrder("bounce", 3, seed=0)
    assert order.back(0) == 1  # heading up: back would leave the list, so it turns
    assert walk(order, 0, 2) == [0, 1, 2]
    assert order.step(2) == 1  # turned: heading down now
    assert order.back(1) == 2


def test_random_never_repeats_and_is_deterministic() -> None:
    seed = chase_seed("pb", 3)
    assert seed == zlib.crc32(b"pb") * 2**32 + 3
    first = walk(CueOrder("random", 4, seed), 0, 200)
    assert first == walk(CueOrder("random", 4, seed), 0, 200)
    assert first != walk(CueOrder("random", 4, chase_seed("pb", 4)), 0, 200)
    assert all(a != b for a, b in itertools.pairwise(first))
    assert set(first) == {0, 1, 2, 3}


def test_a_one_cue_chase_stays_put() -> None:
    for direction in ("forward", "reverse", "bounce", "random"):
        order = CueOrder(direction, 1, seed=1)  # type: ignore[arg-type]
        assert (order.first(), order.step(0), order.back(0), order.peek(0)) == (0, 0, 0, 0)


@pytest.mark.parametrize("direction", ["forward", "reverse", "bounce"])
def test_peek_is_the_next_step_without_taking_it(direction: Any) -> None:
    order = CueOrder(direction, 4, seed=0)
    cue = order.first()
    for _ in range(9):  # a bounce turns at both ends on the way
        ahead = order.peek(cue)
        assert order.peek(cue) == ahead  # peeking does not move the order
        cue = order.step(cue)
        assert cue == ahead


def test_a_random_chase_has_no_peek() -> None:
    assert CueOrder("random", 4, seed=0).peek(2) is None  # its next cue is not drawn yet


def beat_master(bpm_: float = 120.0, steps: tuple[float, ...] = (1.0,)) -> SpeedMasterRuntime:
    doc = busk_rig(spots=1)
    doc["masters"].append(speed_master(bpm=bpm_, steps=steps))
    return SpeedMasterRuntime(compile_doc(doc).masters["m-speed"], 0.0)  # type: ignore[index]


def on_grid(beats: float, m: float) -> bool:
    """Whether a boundary at ``beats`` is on the grid of ``m`` steps per beat:
    a beat or a subdivision for m ≥ 1, a whole beat (every 1/m) for m < 1."""
    position = beats * m if m >= 1 else beats
    return abs(position - round(position)) < 1e-9


@settings(max_examples=200, deadline=None)
@given(
    now=st.floats(0.0, 1000.0),
    m=st.sampled_from([0.25, 0.5, 1.0, 1.25, 2.0, 3.0, 4.0]),
    bpm_=st.floats(30.0, 300.0),
)
def test_activation_aligns_the_first_step(now: float, m: float, bpm_: float) -> None:
    clock = ChaseClock(now, m, beat_master(bpm_))
    first = clock.done + 1
    assert 0.5 - 1e-9 <= first - clock.position(now) <= 1.5 + 1e-9
    beats = clock.master.beats(clock.boundary_time(first))  # type: ignore[union-attr]
    assert on_grid(beats, m)
    assert on_grid(clock.master.beats(clock.boundary_time(first + 1)), m)  # type: ignore[union-attr]


def test_an_hz_clock_starts_at_zero_and_rebases() -> None:
    clock = ChaseClock(10.0, 2.0)
    assert (clock.done, clock.position(10.0), clock.boundary_time(1)) == (0, 0.0, 10.5)
    assert clock.step_seconds() == 0.5
    clock.rebase(10.75, 4.0)  # at position 1.5
    assert clock.position(10.75) == 1.5
    assert clock.boundary_time(2) == pytest.approx(10.875)
    assert clock.last_due(10.875) == 2
    assert clock.last_due(10.874) == 1


def test_a_chase_rate_is_the_product_of_its_factors() -> None:
    settings_ = CompiledChase(
        rate="bpm", hz=0.0, masterId=None, multiplier=0.5, direction="forward", crossfade=0.5
    )
    master_ = beat_master(steps=(1.0, 4.0))
    master_.set_level(1.0)
    chase = ChaseRuntime(settings_, master_, 0.75, 4, seed=0, now=0.0)
    assert chase.clock.rate == 0.5 * 4.0 * 2.0
    assert chase.crossfade() == pytest.approx(0.5 * 60 / (120 * 4.0))


# ---------------------------------------------------------------- Hz chases


def test_hz_steps_at_exact_times() -> None:
    show = chase_show(hz(2.0))
    times = [1.0, 1.49, 1.5, 1.99, 2.0, 2.5, 3.0, 3.25]
    assert cues_at(show, [(1.0, trigger("pb"))], times) == [0, 0, 1, 1, 2, 3, 0, 0]


def test_the_crossfade_with_the_cue_curve() -> None:
    show = chase_show(hz(1.0), crossfade=0.5, curve="easeIn")
    harness = Harness(show)
    seen = harness.run([(0.0, trigger("pb"))], [0.25, 0.5, 0.9, 1.0, 1.25, 1.5])
    assert levels(show, seen[0.0]) == (0.0, 0.0, 0.0, 0.0)
    assert levels(show, seen[0.25]) == (0.25, 0.0, 0.0, 0.0)  # the first step fades in too
    assert levels(show, seen[0.5]) == (1.0, 0.0, 0.0, 0.0)
    assert levels(show, seen[0.9]) == (1.0, 0.0, 0.0, 0.0)
    assert levels(show, seen[1.0]) == (1.0, 0.0, 0.0, 0.0)  # the step starts its fade
    assert levels(show, seen[1.25]) == (0.75, 0.25, 0.0, 0.0)
    assert levels(show, seen[1.5]) == (0.0, 1.0, 0.0, 0.0)


@pytest.mark.parametrize(
    ("direction", "expected"),
    [
        ("forward", [0, 1, 2, 3, 0, 1, 2]),
        ("reverse", [3, 2, 1, 0, 3, 2, 1]),
        ("bounce", [0, 1, 2, 3, 2, 1, 0]),
    ],
)
def test_directions_through_the_engine(direction: str, expected: list[int]) -> None:
    show = chase_show(hz(1.0), direction=direction)
    assert cues_at(show, [(0.0, trigger("pb"))], [float(k) for k in range(7)]) == expected


def test_random_is_the_same_on_every_run_and_never_repeats() -> None:
    show = chase_show(hz(1.0), direction="random")
    times = [float(k) for k in range(40)]
    first = cues_at(show, [(0.0, trigger("pb"))], times)
    assert first == cues_at(show, [(0.0, trigger("pb"))], times)
    assert first[0] == 0
    assert all(a != b for a, b in itertools.pairwise(first))
    assert set(first) == {0, 1, 2, 3}


def test_a_rate_change_mid_step_does_not_jump() -> None:
    show = chase_show(hz(1.0), fader_kind="rate")
    harness = Harness(show)
    assert runtime(harness).faderLevel == 0.5  # a rate fader rests at ×1
    times = [2.5, 2.6, 2.625, 2.87, 2.875]
    seen = harness.run([(0.0, trigger("pb")), (2.5, fader("pb", 1.0))], times)  # ×4 at 2.5
    assert [lit(show, seen[t]) for t in times] == [2, 2, 3, 3, 0]
    assert runtime(harness).chase.clock.position(2.5) == pytest.approx(2.5)  # type: ignore[union-attr]


def test_go_back_and_goto_keep_the_grid() -> None:
    show = chase_show(hz(1.0))
    script = [
        (0.0, trigger("pb")),
        (0.5, go("pb")),  # one step now …
        (1.5, back("pb")),
        (2.25, goto("pb", "4")),
    ]
    times = [0.5, 0.99, 1.0, 1.5, 2.0, 2.25, 2.99, 3.0]
    #           GO   … the boundary at 1 still comes
    assert cues_at(show, script, times) == [1, 1, 2, 1, 2, 3, 3, 0]


def test_go_on_an_idle_chase_starts_it_and_triggers_are_ignored() -> None:
    show = chase_show(hz(1.0), direction="reverse")
    harness = Harness(show)
    harness.run([(0.0, go("pb"))], [0.5])
    assert runtime(harness).cue == 3
    assert runtime(harness).auto is None


def test_a_releasing_chase_keeps_stepping() -> None:
    show = chase_show(hz(1.0))
    harness = Harness(show)
    seen = harness.run([(0.0, trigger("pb")), (0.5, release("pb", 2.0))], [1.0, 2.0, 2.5])
    assert runtime(harness).state == "idle"
    assert levels(show, seen[1.0]) == (0.0, 0.75, 0.0, 0.0)  # stepped, at the release level
    assert levels(show, seen[2.0]) == (0.0, 0.0, 0.25, 0.0)
    assert levels(show, seen[2.5]) == (0.0, 0.0, 0.0, 0.0)


def test_a_fast_chase_skips_whole_laps_between_ticks() -> None:
    show = chase_show(hz(1000.0), crossfade=1.0)
    every = Harness(show).run([(0.0, trigger("pb"))], [k / 1000 for k in range(1, 1001)])
    sparse = Harness(show).run([(0.0, trigger("pb"))], [0.5, 1.0])
    assert sparse[1.0].universe == every[1.0].universe
    assert sparse[0.5].universe == every[0.5].universe


# ---------------------------------------------------------------- BPM chases


def boundary_times(harness: Harness, count: int) -> list[float]:
    clock = runtime(harness).chase.clock  # type: ignore[union-attr]
    return [clock.boundary_time(clock.done + k) for k in range(1, count + 1)]


@pytest.mark.parametrize(
    ("multiplier", "start", "expected"),
    [
        (1.0, 1.2, [1.5, 2.0, 2.5]),  # beat 2.4: the first step 0.6 steps away
        (1.0, 1.3, [2.0, 2.5, 3.0]),  # beat 2.6: 1.4 steps away
        (2.0, 1.3, [1.5, 1.75, 2.0]),  # half beats
        (0.5, 1.3, [2.5, 3.5, 4.5]),  # every second beat, on whole beats
        (0.25, 0.0, [2.0, 4.0, 6.0]),
    ],
)
def test_bpm_boundaries_fall_on_beats(
    multiplier: float, start: float, expected: list[float]
) -> None:
    harness = Harness(chase_show(bpm(multiplier)))
    harness.run([(start, trigger("pb"))], [0.0])
    assert boundary_times(harness, 3) == pytest.approx(expected)


def test_set_bpm_moves_the_boundaries_with_the_beats() -> None:
    show = chase_show(bpm())
    harness = Harness(show)
    harness.run([(0.0, trigger("pb")), (1.25, set_bpm("m-speed", 60.0))], [])
    assert boundary_times(harness, 2) == pytest.approx([1.75, 2.75])  # beat 2.5 at 1.25
    assert runtime(harness).chase.clock.done == 2  # type: ignore[union-attr]


def test_the_worked_example() -> None:
    """§5.7: ×1 at 120 BPM from t = 60; taps at 70 and 70.46875 (128 BPM);
    then the master's step goes to ×2 at t = 80."""
    show = chase_show(bpm())
    harness = Harness(show)
    harness.run([(60.0, trigger("pb"))], [0.0])
    clock = runtime(harness).chase.clock  # type: ignore[union-attr]
    assert (clock.p0, clock.b0, clock.done) == (0.0, 120.0, 0)

    harness.run([(70.0, tap("m-speed"))], [])
    assert (clock.p0, clock.done) == (20.0, 20)  # the boundary at 70 fired first; no step
    harness.run([(70.46875, tap("m-speed"))], [70.4])
    assert harness.engine.runtime.speed["m-speed"].bpm == pytest.approx(128.0)
    assert (clock.p0, clock.b0, clock.done) == (21.0, 141.0, 21)  # stepped on the tap
    assert runtime(harness).cue == 21 % 4
    assert clock.boundary_time(22) == pytest.approx(70.46875 + 60 / 128)

    harness.run([(80.0, master("m-speed", 0.75))], [79.99])  # ×2
    assert clock.rate == 2.0
    assert clock.p0 == pytest.approx(41 + 2 / 3)
    assert clock.done == 41  # no step now
    assert clock.boundary_time(42) == pytest.approx(80.078125)
    assert clock.boundary_time(43) - clock.boundary_time(42) == pytest.approx(30 / 128)


def test_a_tap_steps_forward_restarts_or_waits_but_never_goes_back() -> None:
    show = chase_show(bpm())
    harness = Harness(show)
    harness.run([(0.0, trigger("pb"))], [])
    clock = runtime(harness).chase.clock  # type: ignore[union-attr]
    harness.run([(1.4, tap("m-speed"))], [1.3])  # beat 2.8 → 3: one step early
    assert (clock.done, runtime(harness).cue) == (3, 3)
    assert boundary_times(harness, 1) == pytest.approx([1.9])
    harness.run([(2.0, tap("m-speed"))], [])  # beat 4.2 → 4: the step restarts, at 100 BPM
    assert (clock.done, runtime(harness).cue) == (4, 0)
    assert boundary_times(harness, 1) == pytest.approx([2.6])


def test_never_back_stays_on_the_grid() -> None:
    """At 1.25 steps per beat, a tap can put the nearest grid position before
    the step on show: the chase takes the next grid position instead."""
    show = chase_show(bpm(1.25))
    harness = Harness(show)
    harness.run([(0.0, trigger("pb"))], [])
    clock = runtime(harness).chase.clock  # type: ignore[union-attr]
    harness.run([(1.6, tap("m-speed"))], [1.5])  # beat 3.2 → 3; position 4.0 (just stepped)
    assert clock.done == 4
    assert clock.position(1.6) == pytest.approx(4.75)  # not 3.75: never back
    master_ = harness.engine.runtime.speed["m-speed"]
    for t in boundary_times(harness, 3):
        assert on_grid(master_.beats(t), 1.25)


def test_rate_faders_on_bpm_chases_are_quantised() -> None:
    show = chase_show(bpm(), fader_kind="rate")
    harness = Harness(show)
    harness.run([(0.0, trigger("pb")), (1.1, fader("pb", 0.7))], [])  # ×2, not ×1.74
    clock = runtime(harness).chase.clock  # type: ignore[union-attr]
    assert clock.rate == 2.0
    assert boundary_times(harness, 3) == pytest.approx([1.25, 1.5, 1.75])
    harness.run([(1.3, fader("pb", 0.65))], [])  # still ×2: nothing moves
    assert boundary_times(harness, 1) == pytest.approx([1.5])


def test_the_speed_master_step_scales_the_chase() -> None:
    show = chase_show(bpm())
    harness = Harness(show)
    harness.run([(0.0, trigger("pb")), (1.0, master("m-speed", 0.25))], [])  # ×½
    assert runtime(harness).chase.clock.rate == 0.5  # type: ignore[union-attr]
    assert boundary_times(harness, 2) == pytest.approx([2.0, 3.0])


# ---------------------------------------------------------------- schedule independence


def busy_script() -> Script:
    return [
        (0.13, trigger("pb")),
        (1.07, tap("m-speed")),
        (1.52, tap("m-speed")),
        (1.97, tap("m-speed")),
        (2.31, go("pb")),
        (2.9, master("m-speed", 0.75)),
        (3.33, back("pb")),
        (3.71, set_bpm("m-speed", 97.0)),
        (4.4, goto("pb", "2")),
        (5.05, fader("pb", 0.9)),
        (6.2, release("pb", 1.5)),
    ]


@pytest.mark.parametrize("direction", ["forward", "bounce", "random"])
@pytest.mark.parametrize("rate", [bpm(1.0), bpm(0.5), hz(3.0)], ids=["bpm1", "bpm0.5", "hz3"])
def test_frames_do_not_depend_on_the_tick_schedule(direction: str, rate: Doc) -> None:
    show = chase_show(
        rate, direction=direction, crossfade=0.6, curve="easeInOut", fader_kind="rate"
    )
    checks = [0.5 + 0.37 * k for k in range(22)]
    steady = Harness(show).run(busy_script(), [k / 100 for k in range(800)] + checks)
    rng = random.Random(7)
    sparse = sorted({rng.uniform(0.0, 8.0) for _ in range(60)})
    irregular = Harness(show).run(busy_script(), [0.0, *sparse, *checks])
    for t in checks:
        assert irregular[t].universe == steady[t].universe, t
    assert any(lit(show, steady[t]) is not None for t in checks)  # the chase did run


# ---------------------------------------------------------------- effects


def test_a_chase_steps_its_effects_with_the_crossfade() -> None:
    """phase-5-plan §5.7: a chase step retargets the effects with the step
    cross-fade (½ of a 1 s step here). ``a``, in both cues, is unchanged by
    the steps and keeps its clock; ``b``, in cue 2 only, enters and leaves
    at each step, starting a new clock each time it enters."""
    doc = busk_rig(spots=2)
    doc["effects"] = [
        {
            "id": "t-saw",
            "name": "Saw",
            "layers": [
                {"attribute": "intensity", "waveform": {"kind": "sawUp"}, "phaseOffset": 0,
                 "mode": "absolute"},
            ],
        }
    ]  # fmt: skip

    def saw(instance_id: str, fixture: str) -> Doc:
        return {
            "id": instance_id,
            "templateId": "t-saw",
            "targets": targets(fixture),
            "rate": hz(1.0),
            "direction": "forward",
            "size": 1.0,
            "phase": {"start": 0, "end": 0},
            "groups": 1,
            "blocks": 1,
            "wings": 1,
        }

    one, two = cue("c1", number="1"), cue("c2", number="2")
    one["effects"] = [saw("a", "fx-mh1")]
    two["effects"] = [saw("a", "fx-mh1"), saw("b", "fx-mh2")]
    chase = cue_list("cl-chase", 1, one, two)
    chase.update(mode="chase", chase={"rate": hz(1.0), "direction": "forward", "crossfade": 0.5})
    doc["cueLists"].append(chase)
    doc["playbacks"].append(playback("pb", 1, "cl-chase", fader="none"))
    compiled = compile_doc(doc)
    seen = Harness(compiled).run([(0.0, trigger("pb"))], [1.25, 1.75, 2.25, 2.75, 3.25])
    got = {
        t: [lanes_of(compiled, obs.logical, name, "intensity")[0] for name in ("fx-mh1", "fx-mh2")]
        for t, obs in seen.items()
    }
    assert got[1.25] == pytest.approx([0.25, 0.5 * 0.25])  # b half in, at P = ¼
    assert got[1.75] == pytest.approx([0.75, 0.75])
    assert got[2.25] == pytest.approx([0.25, 0.5 * 0.25])  # b half out, still moving
    assert got[2.75] == pytest.approx([0.75, 0.0])
    assert got[3.25] == pytest.approx([0.25, 0.5 * 0.25])  # b again, on a new clock
