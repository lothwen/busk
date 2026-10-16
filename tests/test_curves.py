"""Fade curves (phase-4-plan decision 7): formulas, endpoints, monotonicity,
fade fractions around delays and zero durations, and Bézier against CSS."""

from __future__ import annotations

import itertools

import pytest
from hypothesis import given
from hypothesis import strategies as st

from busk.engine.curves import NAMED, bezier, curve_of, fade_fraction, linear
from busk.engine.fades import Envelope

GRID = [k / 64 for k in range(64)]  # progress values in [0, 1)

FORMULAS = {
    "linear": lambda t: t,
    "easeIn": lambda t: t * t,
    "easeOut": lambda t: t * (2 - t),
    "easeInOut": lambda t: t * t * (3 - 2 * t),
    "snapStart": lambda t: 1.0,
    "snapEnd": lambda t: 0.0,
}


@pytest.mark.parametrize("name", list(FORMULAS))
def test_each_named_curve_follows_its_formula(name: str) -> None:
    curve = curve_of(name)  # type: ignore[arg-type]
    assert curve is NAMED[name]
    for t in GRID:
        assert curve(t) == pytest.approx(FORMULAS[name](t), abs=1e-15)


@pytest.mark.parametrize("name", list(FORMULAS))
def test_every_curve_ends_exactly_at_one(name: str) -> None:
    curve = NAMED[name]
    assert fade_fraction(2.0, 2.0, curve) == 1.0
    assert fade_fraction(5.0, 2.0, curve) == 1.0


@pytest.mark.parametrize("name", [n for n in FORMULAS if n != "snapStart"])
def test_every_curve_but_snap_start_starts_at_zero(name: str) -> None:
    assert fade_fraction(0.0, 2.0, NAMED[name]) == 0.0


def test_snap_start_jumps_as_the_fade_starts_after_its_delay() -> None:
    curve = NAMED["snapStart"]
    assert fade_fraction(-0.001, 1.0, curve) == 0.0  # still in the delay
    assert fade_fraction(0.0, 1.0, curve) == 1.0


def test_snap_end_jumps_when_the_fade_ends() -> None:
    curve = NAMED["snapEnd"]
    assert fade_fraction(0.999, 1.0, curve) == 0.0
    assert fade_fraction(1.0, 1.0, curve) == 1.0


@pytest.mark.parametrize("name", list(FORMULAS))
def test_named_curves_are_monotone_and_in_range(name: str) -> None:
    values = [NAMED[name](t) for t in GRID] + [1.0]
    assert all(0.0 <= v <= 1.0 for v in values)
    assert all(b >= a for a, b in itertools.pairwise(values))


def test_smoothstep_is_symmetric() -> None:
    curve = NAMED["easeInOut"]
    assert curve(0.25) == 0.15625
    assert curve(0.5) == 0.5
    assert curve(0.75) == 1 - curve(0.25)


# ---------------------------------------------------------------- fractions


def test_fade_fraction_is_zero_during_the_delay() -> None:
    assert fade_fraction(-1.5, 2.0) == 0.0
    assert fade_fraction(-1e-12, 2.0) == 0.0


def test_fade_fraction_divides_elapsed_by_duration() -> None:
    assert fade_fraction(0.5, 2.0) == 0.25
    assert fade_fraction(1.0, 2.0, NAMED["easeIn"]) == 0.25


def test_a_zero_duration_is_a_step_at_the_end_of_the_delay() -> None:
    assert fade_fraction(-1e-9, 0.0) == 0.0
    assert fade_fraction(0.0, 0.0) == 1.0
    assert fade_fraction(0.0, 0.0, NAMED["snapEnd"]) == 1.0


# ------------------------------------------------------------------- Bézier

# CSS `ease` = cubic-bezier(0.25, 0.1, 0.25, 1), solved by exact rational
# bisection outside this code base (to 2^-80 in s).
CSS_EASE = {0.25: 0.40851059135539586, 0.5: 0.802403387584857, 0.75: 0.9604589783489741}


@pytest.mark.parametrize(("t", "expected"), list(CSS_EASE.items()))
def test_bezier_matches_the_css_ease_curve(t: float, expected: float) -> None:
    assert bezier(0.25, 0.1, 0.25, 1.0)(t) == pytest.approx(expected, abs=1e-6)


def test_a_bezier_on_the_diagonal_is_linear() -> None:
    curve = bezier(0.25, 0.25, 0.75, 0.75)
    for t in GRID:
        assert curve(t) == pytest.approx(t, abs=1e-6)


def test_a_bezier_with_a_flat_start_still_solves() -> None:
    # x1 = x2 = 0 makes dx/ds = 0 at s = 0: Newton stalls, bisection finishes.
    curve = bezier(0.0, 0.0, 0.0, 1.0)
    assert curve(0.0) == 0.0
    assert 0.0 < curve(0.001) < curve(0.5) < curve(0.999) <= 1.0


def test_bezier_specs_are_built_once() -> None:
    a = curve_of({"bezier": (0.4, 0.0, 0.2, 1.0)})
    b = curve_of({"bezier": (0.4, 0, 0.2, 1)})  # ints from JSON: the same curve
    assert a is b
    assert a is not curve_of({"bezier": (0.4, 0.0, 0.2, 0.9)})


UNIT = st.floats(0, 1)


@given(UNIT, UNIT, UNIT, UNIT, st.lists(st.floats(0, 1, exclude_max=True), min_size=2))
def test_bezier_stays_in_range_and_is_monotone(
    x1: float, y1: float, x2: float, y2: float, times: list[float]
) -> None:
    """With control values in 0..1 (validation), every fade stays convex."""
    curve = bezier(x1, y1, x2, y2)
    values = [curve(t) for t in sorted(times)]
    assert all(0.0 <= v <= 1.0 for v in values)
    # The solver stops within 1e-7 of t; on a steep curve that is a little more in y.
    assert all(b >= a - 1e-5 for a, b in itertools.pairwise(values))


# ---------------------------------------------------------------- envelopes


def test_an_envelope_follows_its_curve() -> None:
    envelope = Envelope()
    envelope.retarget(10.0, 0.6, 3.0, curve=NAMED["easeInOut"])
    assert envelope.value(10.75) == pytest.approx(0.6 * 0.15625)
    assert envelope.value(11.5) == pytest.approx(0.3)
    assert envelope.value(13.0) == 0.6


def test_a_snap_start_envelope_jumps_after_its_delay() -> None:
    envelope = Envelope()
    envelope.retarget(0.0, 1.0, 2.0, delay=0.5, curve=NAMED["snapStart"])
    assert [envelope.value(t) for t in (0.0, 0.49, 0.5, 1.0)] == [0.0, 0.0, 1.0, 1.0]
    assert not envelope.settled(2.4)
    assert envelope.settled(2.5)


def test_retargeting_resets_the_curve() -> None:
    envelope = Envelope()
    envelope.retarget(0.0, 1.0, 1.0, curve=NAMED["easeIn"])
    envelope.retarget(0.5, 0.0, 1.0)  # a release: linear again, from 0.25
    assert envelope.curve is linear
    assert envelope.value(1.0) == pytest.approx(0.125)
