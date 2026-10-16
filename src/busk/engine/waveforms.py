"""Effect waveforms, vectorised over a layer's lanes (spec §10.3, phase-5-plan §5.1).

:func:`evaluate` maps each lane's phase *position* ``φ`` (in cycles, not
wrapped) to a wave value ``w ∈ [0, 1]``. The phase within the cycle is
``p = φ − floor(φ)``; ``random`` also uses the cycle number ``floor(φ)``.

| Waveform | ``w(p)`` |
|---|---|
| ``sine`` | ``0.5 − 0.5·cos(2πp)``: starts at 0, smooth |
| ``triangle`` | ``2p`` for ``p < ½``, else ``2 − 2p`` |
| ``square`` | ``1`` for ``p < duty``, else ``0`` |
| ``sawUp`` / ``sawDown`` | ``p`` / ``1 − p`` |
| ``pulse`` | up over ``attack``, 1 for ``width``, down over ``decay``, then 0 |
| ``step`` | ``steps[floor(p·n)]`` |
| ``random`` | ``u(c)``, or with ``smooth`` ``u(c) + (u(c+1) − u(c))·s(p)`` |
| ``curve`` | piecewise-linear through the points, periodic |

* ``pulse`` (decision 3): its parts are fractions of a cycle. A zero-length
  ramp is a step: with ``attack = 0`` the wave is 1 from ``p = 0``, with
  ``decay = 0`` it drops to 0 at ``attack + width``.
* ``random`` (decision 3): ``u(c)`` is a hash of ``(seed, member, c)``, not
  a stateful generator, so the value is a pure function of the phase and the
  frames never depend on the tick schedule. The hash chains splitmix64's
  mixer over the three numbers in ``uint64`` arithmetic, which wraps the
  same way on every platform; the top 53 bits give a float in ``[0, 1)``.
  ``s(p) = p²(3 − 2p)`` is smoothstep: the wave reaches ``u(c+1)`` exactly
  at the end of cycle ``c``, so it is continuous.
* ``curve``: :func:`busk.compiler.effects.compile_wave` extends the points
  by one period, so the evaluation is one ``np.interp``.

Every waveform is a handful of numpy calls over the whole layer; no Python
loop runs over members. The simple waves work in place in ``out``; ``pulse``,
``step``, ``random`` and ``curve`` allocate temporaries the size of the layer.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Final

import numpy as np
from numpy.typing import NDArray

from busk.compiler.effects import CompiledWave, WaveKind

type Floats = NDArray[np.float64]
type Members = NDArray[np.intp]

_TWO_PI: Final = 2.0 * math.pi
_MASK: Final = (1 << 64) - 1
_GOLDEN: Final = 0x9E3779B97F4A7C15
_MIX1: Final = 0xBF58476D1CE4E5B9
_MIX2: Final = 0x94D049BB133111EB
_TO_UNIT: Final = 2.0**-53


def evaluate(wave: CompiledWave, phase: Floats, member: Members, out: Floats) -> Floats:
    """Write ``w`` for each lane into ``out`` and return it.

    ``phase`` holds each lane's phase position ``φ`` in cycles; ``member``
    each lane's member index in the effect's targets (only ``random`` reads
    it). ``out`` must have the same shape as ``phase`` and must not be the
    same array.
    """
    np.floor(phase, out=out)
    np.subtract(phase, out, out=out)  # p = φ − floor(φ), in [0, 1]
    _WAVES[wave.kind](wave, phase, member, out)
    return out


# Each function below turns ``out``, holding p, into w.


def _sine(wave: CompiledWave, phase: Floats, member: Members, out: Floats) -> None:
    out *= _TWO_PI
    np.cos(out, out=out)
    out *= -0.5
    out += 0.5


def _triangle(wave: CompiledWave, phase: Floats, member: Members, out: Floats) -> None:
    # 1 − |2p − 1| is 2p below ½ and 2 − 2p above.
    out *= 2.0
    out -= 1.0
    np.abs(out, out=out)
    np.subtract(1.0, out, out=out)


def _square(wave: CompiledWave, phase: Floats, member: Members, out: Floats) -> None:
    np.less(out, wave.duty, out=out)


def _saw_up(wave: CompiledWave, phase: Floats, member: Members, out: Floats) -> None:
    pass


def _saw_down(wave: CompiledWave, phase: Floats, member: Members, out: Floats) -> None:
    np.subtract(1.0, out, out=out)


def _pulse(wave: CompiledWave, phase: Floats, member: Members, out: Floats) -> None:
    # w = clip(min(rise, fall), 0, 1): the rise p/a is below 1 only during the
    # attack, the fall 1 − (p − a − h)/d only after the hold.
    a, top, d = wave.attack, wave.attack + wave.width, wave.decay
    if d > 0.0:
        fall = (out - top) / d
        np.subtract(1.0, fall, out=fall)
    else:
        fall = (out < top).astype(np.float64)
    if a > 0.0:
        out /= a
        np.minimum(out, fall, out=out)
    else:
        out[...] = fall
    np.clip(out, 0.0, 1.0, out=out)


def _step(wave: CompiledWave, phase: Floats, member: Members, out: Floats) -> None:
    n = len(wave.steps)
    out *= n
    index = out.astype(np.intp)  # truncation is floor: p·n ≥ 0
    np.minimum(index, n - 1, out=index)  # p can round up to exactly 1
    np.take(wave.steps, index, out=out)


def _random(wave: CompiledWave, phase: Floats, member: Members, out: Floats) -> None:
    cycle = np.floor(phase).astype(np.int64)
    keyed = _mix(np.uint64(_mix_int(wave.seed)) ^ member.astype(np.uint64))
    value = _unit_hash(keyed, cycle)
    if wave.smooth:
        step = _unit_hash(keyed, cycle + 1) - value
        # smoothstep s(p) = p²(3 − 2p), then w = u(c) + (u(c+1) − u(c))·s(p)
        s = out * out
        out *= -2.0
        out += 3.0
        out *= s
        out *= step
        out += value
    else:
        out[...] = value


def _curve(wave: CompiledWave, phase: Floats, member: Members, out: Floats) -> None:
    out[...] = np.interp(out, wave.xs, wave.ys)


_WAVES: Final[Mapping[WaveKind, Callable[[CompiledWave, Floats, Members, Floats], None]]] = {
    "sine": _sine,
    "triangle": _triangle,
    "square": _square,
    "sawUp": _saw_up,
    "sawDown": _saw_down,
    "pulse": _pulse,
    "step": _step,
    "random": _random,
    "curve": _curve,
}

# ------------------------------------------------------------------- hashing


def _mix_int(x: int) -> int:
    """splitmix64's output function on one 64-bit integer (Python ints)."""
    z = (x + _GOLDEN) & _MASK
    z = ((z ^ (z >> 30)) * _MIX1) & _MASK
    z = ((z ^ (z >> 27)) * _MIX2) & _MASK
    return z ^ (z >> 31)


def _mix(x: NDArray[np.uint64]) -> NDArray[np.uint64]:
    """:func:`_mix_int` over an array; ``uint64`` arithmetic wraps silently."""
    z = x + np.uint64(_GOLDEN)
    z = (z ^ (z >> np.uint64(30))) * np.uint64(_MIX1)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(_MIX2)
    return z ^ (z >> np.uint64(31))


def _unit_hash(keyed: NDArray[np.uint64], cycle: NDArray[np.int64]) -> Floats:
    """``u(c) ∈ [0, 1)`` per lane, from the lane's (seed, member) key and its
    cycle number. Negative cycles hash as their two's complement."""
    bits = _mix(keyed ^ cycle.view(np.uint64)) >> np.uint64(11)
    return bits.astype(np.float64) * _TO_UNIT
