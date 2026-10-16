"""Effect waveforms (spec §10.3, phase-5-plan §5.1 and decision 3).

The vectorised :func:`busk.engine.waveforms.evaluate` is checked against
values at key phases, against a scalar transcription of the plan's table
(:func:`scalar`, written piece by piece rather than with the vector code's
tricks), and for the properties the engine relies on: values in ``0..1``,
``random`` a pure function of (seed, member, cycle), ``smooth`` random and
curves continuous across the cycle boundary.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from busk.compiler.effects import compile_wave
from busk.engine.waveforms import evaluate

type Wave = dict[str, Any]


def run(wave: Wave, phases: list[float], members: list[int] | None = None) -> list[float]:
    phase = np.array(phases, dtype=np.float64)
    member = np.array(members if members is not None else [0] * len(phases), dtype=np.intp)
    out = np.empty_like(phase)
    assert evaluate(compile_wave(wave), phase, member, out) is out
    return [float(w) for w in out]


# ------------------------------------------------------- scalar transcription

_M = (1 << 64) - 1


def _mix(x: int) -> int:
    z = (x + 0x9E3779B97F4A7C15) & _M
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _M
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _M
    return z ^ (z >> 31)


def u(seed: int, member: int, cycle: int) -> float:
    """``splitmix64(seed, member, cycle)``: the mixer chained over the three."""
    return (_mix(_mix(_mix(seed & _M) ^ member) ^ (cycle & _M)) >> 11) / 2**53


def _curve(points: list[tuple[float, float]], p: float) -> float:
    """Linear interpolation over the points repeated one period either side,
    leaving out repeats of an ``x`` the points already have."""
    xs = {x for x, _ in points}
    periodic = sorted(
        [(x - 1, y) for x, y in points if x - 1 not in xs]
        + points
        + [(x + 1, y) for x, y in points if x + 1 not in xs]
    )
    lower = max(point for point in periodic if point[0] <= p)
    upper = min(point for point in periodic if point[0] > p)
    (x0, y0), (x1, y1) = lower, upper
    return y0 + (y1 - y0) * (p - x0) / (x1 - x0)


def scalar(wave: Wave, phi: float, member: int) -> float:
    """The plan's §5.1 table, one lane at a time."""
    p = phi - math.floor(phi)
    match wave["kind"]:
        case "sine":
            return 0.5 - 0.5 * math.cos(2 * math.pi * p)
        case "triangle":
            return 2 * p if p < 0.5 else 2 - 2 * p
        case "square":
            return 1.0 if p < wave["duty"] else 0.0
        case "sawUp":
            return p
        case "sawDown":
            return 1 - p
        case "pulse":
            a, h, d = wave["attack"], wave["width"], wave["decay"]
            if p < a:
                return p / a
            if p < a + h:
                return 1.0
            if p < a + h + d:
                return 1 - (p - a - h) / d
            return 0.0
        case "step":
            steps = wave["steps"]
            return float(steps[min(math.floor(p * len(steps)), len(steps) - 1)])
        case "random":
            c = math.floor(phi)
            here = u(wave["seed"], member, c)
            if not wave["smooth"]:
                return here
            return here + (u(wave["seed"], member, c + 1) - here) * p * p * (3 - 2 * p)
        case "curve":
            return _curve([(float(x), float(y)) for x, y in wave["points"]], p)
    raise AssertionError(wave)


# ------------------------------------------------------------- key phases

PULSE = {"kind": "pulse", "attack": 0.2, "width": 0.3, "decay": 0.1}
STEP = {"kind": "step", "steps": [0, 0.5, 1, 0.25]}
TENT = {"kind": "curve", "points": [[0, 0], [0.5, 1], [1, 0]]}
INNER = {"kind": "curve", "points": [[0.25, 1], [0.75, 0]]}  # extended both ways

KEY_PHASES = [
    ({"kind": "sine"}, [0, 0.25, 0.5, 0.75, 3.25, -0.75], [0, 0.5, 1, 0.5, 0.5, 0.5]),
    ({"kind": "triangle"}, [0, 0.25, 0.5, 0.75, 1.125], [0, 0.5, 1, 0.5, 0.25]),
    ({"kind": "square", "duty": 0.25}, [0, 0.2, 0.25, 0.9, -0.9], [1, 1, 0, 0, 1]),
    ({"kind": "square", "duty": 0}, [0, 0.5], [0, 0]),
    ({"kind": "square", "duty": 1}, [0, 0.999], [1, 1]),
    ({"kind": "sawUp"}, [0, 0.25, 0.75, 2.5], [0, 0.25, 0.75, 0.5]),
    ({"kind": "sawDown"}, [0, 0.25, 0.75, -0.25], [1, 0.75, 0.25, 0.25]),
    (PULSE, [0, 0.1, 0.2, 0.4, 0.5, 0.55, 0.6, 0.9], [0, 0.5, 1, 1, 1, 0.5, 0, 0]),
    (STEP, [0, 0.24, 0.25, 0.5, 0.99, 1.3], [0, 0, 0.5, 1, 0.25, 0.5]),
    (TENT, [0, 0.25, 0.5, 0.75, 0.9], [0, 0.5, 1, 0.5, 0.2]),
    (INNER, [0, 0.25, 0.5, 0.75, 0.875, 0.999], [0.5, 1, 0.5, 0, 0.25, 0.498]),
]


@pytest.mark.parametrize(
    ("wave", "phases", "expected"),
    KEY_PHASES,
    ids=[f"{wave['kind']}-{i}" for i, (wave, _, _) in enumerate(KEY_PHASES)],
)
def test_key_phases(wave: Wave, phases: list[float], expected: list[float]) -> None:
    assert run(wave, phases) == pytest.approx(expected, abs=1e-9)


def test_pulse_ramps_of_zero_length_are_steps() -> None:
    no_attack = {"kind": "pulse", "attack": 0, "width": 0.5, "decay": 0.25}
    assert run(no_attack, [0, 0.49, 0.5, 0.625, 0.75, 0.9]) == pytest.approx([1, 1, 1, 0.5, 0, 0])
    no_decay = {"kind": "pulse", "attack": 0.25, "width": 0.25, "decay": 0}
    assert run(no_decay, [0, 0.125, 0.25, 0.49, 0.5, 0.9]) == [0, 0.5, 1, 1, 0, 0]
    square = {"kind": "pulse", "attack": 0, "width": 0.5, "decay": 0}
    assert run(square, [0, 0.49, 0.5, 0.99]) == [1, 1, 0, 0]
    nothing = {"kind": "pulse", "attack": 0, "width": 0, "decay": 0}
    assert run(nothing, [0, 0.5, 0.99]) == [0, 0, 0]
    whole = {"kind": "pulse", "attack": 0.5, "width": 0, "decay": 0.5}  # a triangle
    assert run(whole, [0, 0.25, 0.5, 0.75]) == pytest.approx([0, 0.5, 1, 0.5])


# ----------------------------------------------------------------- random


def test_random_is_one_value_per_member_and_cycle() -> None:
    wave = {"kind": "random", "seed": 42, "smooth": False}
    w = run(wave, [0, 0.3, 0.99, 1, 1.5, -1, -0.5], members=[3] * 7)
    assert w == [u(42, 3, 0)] * 3 + [u(42, 3, 1)] * 2 + [u(42, 3, -1)] * 2
    assert len({u(42, 3, 0), u(42, 3, 1), u(42, 3, -1), u(42, 4, 0), u(43, 3, 0)}) == 5


def test_random_depends_on_nothing_but_seed_member_and_cycle() -> None:
    wave = {"kind": "random", "seed": 7, "smooth": True}
    phases = [0.1, 5.5, -3.25, 1000.75]
    members = [0, 1, 2, 3]
    alone = [run(wave, [phi], [m])[0] for phi, m in zip(phases, members, strict=True)]
    assert run(wave, phases, members) == alone
    assert run(wave, phases[::-1], members[::-1]) == alone[::-1]
    # The seed is reduced to 64 bits, as compile_wave stores it.
    assert run({**wave, "seed": 7 + 2**64}, phases, members) == alone


def test_random_values_spread_over_0_to_1() -> None:
    wave = {"kind": "random", "seed": 1, "smooth": False}
    w = np.array(run(wave, [float(c) for c in range(2000)], members=[5] * 2000))
    assert 0.0 <= w.min() < 0.01
    assert 0.99 < w.max() < 1.0
    assert abs(w.mean() - 0.5) < 0.03


@settings(max_examples=200, deadline=None)
@given(
    seed=st.integers(-(2**70), 2**70),
    member=st.integers(0, 10_000),
    cycle=st.integers(-10_000, 10_000),
)
def test_smooth_random_is_continuous_across_cycles(seed: int, member: int, cycle: int) -> None:
    wave = {"kind": "random", "seed": seed, "smooth": True}
    before, at, after = run(wave, [cycle - 1e-7, float(cycle), cycle + 1e-7], [member] * 3)
    assert at == pytest.approx(u(seed, member, cycle))
    assert before == pytest.approx(at, abs=1e-9)
    assert after == pytest.approx(at, abs=1e-9)
    mid = run(wave, [cycle + 0.5], [member])[0]
    low, high = sorted((u(seed, member, cycle), u(seed, member, cycle + 1)))
    assert low - 1e-12 <= mid <= high + 1e-12


# ------------------------------------------------------------------ curve

_points = st.lists(st.integers(0, 100), min_size=1, max_size=6, unique=True).flatmap(
    lambda xs: st.lists(st.floats(0, 1), min_size=len(xs), max_size=len(xs)).map(
        lambda ys: [[x / 100, y] for x, y in zip(sorted(xs), ys, strict=True)]
    )
)


def test_compile_wave_extends_curve_points_by_one_period() -> None:
    wave = compile_wave(INNER)  # type: ignore[arg-type]
    assert wave.xs.tolist() == [-0.25, 0.25, 0.75, 1.25]
    assert wave.ys.tolist() == [0, 1, 0, 1]
    assert compile_wave(TENT).xs.tolist() == [0, 0.5, 1]  # type: ignore[arg-type]
    one = compile_wave({"kind": "curve", "points": [(0.5, 0.3)]})
    assert (one.xs.tolist(), one.ys.tolist()) == ([-0.5, 0.5, 1.5], [0.3, 0.3, 0.3])


@settings(max_examples=200, deadline=None)
@given(points=_points)
def test_curve_is_continuous_across_the_cycle_boundary(points: list[list[float]]) -> None:
    if points[0][0] == 0 and points[-1][0] == 1:
        points[-1][1] = points[0][1]  # both ends given: continuous only if they agree
    wave = {"kind": "curve", "points": points}
    end, start = run(wave, [1 - 1e-12, 1.0])
    assert end == pytest.approx(start, abs=1e-6)
    assert run(wave, [x for x, _ in points]) == pytest.approx([y for _, y in points])


def test_a_curve_with_different_ends_jumps_where_it_says() -> None:
    saw = {"kind": "curve", "points": [[0, 0], [1, 1]]}
    assert run(saw, [0, 0.5, 1 - 1e-9, 1]) == pytest.approx([0, 0.5, 1, 0])


# ------------------------------------------------------------- properties

_unit = st.floats(0, 1)


@st.composite
def _pulse(draw: st.DrawFn) -> Wave:
    # A part is 0 or at least 1e-6 of a cycle: below that, a + h + d rounds to
    # a + h and the scalar table's empty decay disagrees at p = a + h alone.
    parts = [draw(st.one_of(st.just(0.0), st.floats(1e-6, 1))) for _ in range(3)]
    total = sum(parts)
    if total > 1:
        parts = [part / total for part in parts]
    return {"kind": "pulse", "attack": parts[0], "width": parts[1], "decay": parts[2]}


waves = st.one_of(
    st.sampled_from([{"kind": k} for k in ("sine", "triangle", "sawUp", "sawDown")]),
    st.builds(lambda duty: {"kind": "square", "duty": duty}, _unit),
    _pulse(),
    st.builds(lambda s: {"kind": "step", "steps": s}, st.lists(_unit, min_size=1, max_size=8)),
    st.builds(
        lambda seed, smooth: {"kind": "random", "seed": seed, "smooth": smooth},
        st.integers(-(2**70), 2**70),
        st.booleans(),
    ),
    st.builds(lambda p: {"kind": "curve", "points": p}, _points),
)
lanes = st.lists(
    st.tuples(st.floats(-1e6, 1e6, allow_nan=False), st.integers(0, 1000)),
    min_size=1,
    max_size=20,
)


@settings(max_examples=500, deadline=None)
@given(wave=waves, lanes=lanes)
def test_vectorised_equals_the_scalar_transcription(
    wave: Wave, lanes: list[tuple[float, int]]
) -> None:
    phases = [phi for phi, _ in lanes]
    members = [member for _, member in lanes]
    expected = [scalar(wave, phi, member) for phi, member in lanes]
    assert run(wave, phases, members) == pytest.approx(expected, abs=1e-9)


@settings(max_examples=300, deadline=None)
@given(wave=waves, lanes=lanes)
def test_every_wave_stays_within_0_and_1(wave: Wave, lanes: list[tuple[float, int]]) -> None:
    w = run(wave, [phi for phi, _ in lanes], [member for _, member in lanes])
    assert all(0.0 <= value <= 1.0 for value in w)
