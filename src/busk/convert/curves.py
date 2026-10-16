"""Dimmer curves (spec §13.2), vectorised.

A mode's ``dimmerCurve`` shapes intensity before it reaches the fixture:
before a dimmer channel is mapped to DMX, and before virtual intensity
multiplies the emitters. For ``x`` in ``0..1``:

=============  ==========================================================
``linear``     ``x``
``square``     ``x²``
``invSquare``  ``1 − (1 − x)²``
``sCurve``     ``x²(3 − 2x)``, the smoothstep the spec uses for easeInOut
table          piecewise linear over equally spaced points (≥ 2 points)
=============  ==========================================================

Every curve maps 0 to 0 and 1 to 1 except a table, which maps them to its
first and last points. Inputs must already be clipped to ``0..1``.

The test suite's reference converter evaluates the same formulas one value
at a time, with the same operations in the same order. Its results are
therefore bit-identical, which is what lets a property test compare the
fast converter with it byte for byte.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from busk.model.profile import DimmerCurve

type FloatArray = NDArray[np.float64]
type CurveFunction = Callable[[FloatArray], FloatArray]


def curve_function(curve: DimmerCurve) -> CurveFunction:
    """Return a function that applies ``curve`` to an array of ``0..1`` values.

    The function may return its argument (``linear``) or a new array.
    """
    if curve == "linear":
        return _linear
    if curve == "square":
        return _square
    if curve == "invSquare":
        return _inv_square
    if curve == "sCurve":
        return _s_curve
    return _table(curve)


def _linear(x: FloatArray) -> FloatArray:
    return x


def _square(x: FloatArray) -> FloatArray:
    return x * x


def _inv_square(x: FloatArray) -> FloatArray:
    y = 1.0 - x
    return 1.0 - y * y


def _s_curve(x: FloatArray) -> FloatArray:
    return x * x * (3.0 - 2.0 * x)


def _table(points: tuple[float, ...]) -> CurveFunction:
    """Piecewise-linear interpolation over ``points`` at ``k / (n − 1)``.

    The segment index is clamped to ``n − 2`` so that ``x = 1`` uses the last
    segment with fraction 1 rather than indexing past the end.
    """
    table = np.array(points, dtype=np.float64)
    last = len(points) - 2

    def apply(x: FloatArray) -> FloatArray:
        position = x * (last + 1)
        k = np.minimum(np.floor(position), last).astype(np.intp)
        fraction = position - k
        low = table[k]
        return low + fraction * (table[k + 1] - low)

    return apply
