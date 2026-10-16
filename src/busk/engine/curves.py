"""Fade curves: how a fade moves from its start to its end (spec §5.9, phase-4-plan decision 7).

A curve maps the *progress* of a fade, ``t = elapsed / duration`` in
``[0, 1)``, to the *fraction* of the way from the start value to the end
value, in ``[0, 1]``:

==============  =================================================================
Curve           f(t) on 0 ≤ t < 1
==============  =================================================================
``linear``      t
``easeIn``      t²
``easeOut``     t(2 − t)
``easeInOut``   t²(3 − 2t), the smoothstep §5.9 specifies
``snapStart``   1: the value jumps as soon as the fade starts (after its delay)
``snapEnd``     0: the value jumps when the fade ends
``bezier``      CSS ``cubic-bezier(x1, y1, x2, y2)`` with fixed end points (0, 0)
                and (1, 1): y(s) where x(s) = t
==============  =================================================================

Every curve but ``snapStart`` has f(0) = 0, and :func:`fade_fraction` returns
exactly 1 once a fade has ended, so a fade always lands exactly on its end
value. Validation keeps all four Bézier control values in ``0..1``; the
curve then stays in ``0..1`` and is monotone, so every interpolation the
engine computes with it is convex and in range (phase-2-plan decision 8).

Values and presence of one fade use the same curve; snapping lanes switch
value when the fraction reaches their threshold (§7.3).
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Final, cast

from busk.model.entry import FadeCurve

type Curve = Callable[[float], float]
"""``f(t)``: fade progress ``t ∈ [0, 1)`` → fraction of the way, in ``[0, 1]``."""


def linear(t: float) -> float:
    """``t``: constant speed."""
    return t


def ease_in(t: float) -> float:
    """``t²``: starts slowly."""
    return t * t


def ease_out(t: float) -> float:
    """``t(2 − t)``: ends slowly."""
    return t * (2.0 - t)


def ease_in_out(t: float) -> float:
    """``t²(3 − 2t)`` (smoothstep): starts and ends slowly."""
    return t * t * (3.0 - 2.0 * t)


def snap_start(t: float) -> float:
    """``1``: the whole change happens as soon as the fade starts."""
    return 1.0


def snap_end(t: float) -> float:
    """``0``: nothing changes until the fade ends."""
    return 0.0


NAMED: Final[dict[str, Curve]] = {
    "linear": linear,
    "easeIn": ease_in,
    "easeOut": ease_out,
    "easeInOut": ease_in_out,
    "snapStart": snap_start,
    "snapEnd": snap_end,
}
"""The named curves of :data:`~busk.model.entry.FadeCurve`."""

_TOLERANCE: Final = 1e-7
"""How close x(s) must get to t when solving a Bézier curve."""

_NEWTON_STEPS: Final = 8
_FLAT: Final = 1e-6
"""A slope below this stops Newton's method; bisection takes over."""


def bezier(x1: float, y1: float, x2: float, y2: float) -> Curve:
    """The CSS ``cubic-bezier(x1, y1, x2, y2)`` easing curve.

    The curve is the cubic Bézier through (0, 0), (x1, y1), (x2, y2) and
    (1, 1). For a progress ``t`` it finds the parameter ``s`` with
    ``x(s) = t`` (Newton's method from ``s = t``, then bisection if the slope
    is nearly flat or Newton did not converge; tolerance 1e-7) and returns
    ``y(s)``. ``x1`` and ``x2`` must be in ``0..1`` so that ``x`` is
    monotone and ``s`` unique.
    """
    # Polynomial coefficients: x(s) = ((ax·s + bx)·s + cx)·s, likewise y.
    cx = 3.0 * x1
    bx = 3.0 * (x2 - x1) - cx
    ax = 1.0 - cx - bx
    cy = 3.0 * y1
    by = 3.0 * (y2 - y1) - cy
    ay = 1.0 - cy - by

    def x_of(s: float) -> float:
        return ((ax * s + bx) * s + cx) * s

    def solve(t: float) -> float:
        s = t
        for _ in range(_NEWTON_STEPS):
            error = x_of(s) - t
            if abs(error) < _TOLERANCE:
                return s
            slope = (3.0 * ax * s + 2.0 * bx) * s + cx
            if abs(slope) < _FLAT:
                break
            s -= error / slope
        low, high = 0.0, 1.0
        s = t
        while high - low > _TOLERANCE:
            x = x_of(s)
            if abs(x - t) < _TOLERANCE:
                return s
            if x < t:
                low = s
            else:
                high = s
            s = (low + high) / 2.0
        return s

    def curve(t: float) -> float:
        s = min(max(solve(t), 0.0), 1.0)
        return min(max(((ay * s + by) * s + cy) * s, 0.0), 1.0)

    return curve


@functools.cache
def _bezier_of(points: tuple[float, float, float, float]) -> Curve:
    return bezier(*points)


def curve_of(spec: FadeCurve) -> Curve:
    """The curve a show's :data:`~busk.model.entry.FadeCurve` names.

    Bézier curves are built once per distinct set of control values, so
    equal curves are the same object (fade groups compare them by identity).
    """
    if isinstance(spec, str):
        return NAMED[spec]
    x1, y1, x2, y2 = cast(tuple[float, float, float, float], tuple(spec["bezier"]))
    return _bezier_of((float(x1), float(y1), float(x2), float(y2)))


def fade_fraction(elapsed: float, duration: float, curve: Curve = linear) -> float:
    """How far a fade is, ``elapsed`` seconds after it started (its delay excluded).

    * ``elapsed < 0`` (still in its delay): 0;
    * ``elapsed ≥ duration``: exactly 1. A zero duration is therefore a step
      at the end of the delay;
    * otherwise ``curve(elapsed / duration)``.
    """
    if elapsed < 0.0:
        return 0.0
    if elapsed >= duration:
        return 1.0
    return curve(elapsed / duration)
