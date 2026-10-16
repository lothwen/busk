"""DMX value helpers (spec §13.1)."""

from __future__ import annotations

from typing import Final, overload

import numpy as np
from numpy.typing import NDArray

UNIVERSE_SIZE: Final = 512
"""Channels per DMX universe."""


@overload
def split_raw(raw: int, nbytes: int) -> tuple[int, ...]: ...


@overload
def split_raw(raw: NDArray[np.int64], nbytes: int) -> tuple[NDArray[np.int64], ...]: ...


def split_raw(
    raw: int | NDArray[np.int64], nbytes: int
) -> tuple[int, ...] | tuple[NDArray[np.int64], ...]:
    """Split a raw channel value into its DMX bytes, most significant first.

    This is the §13.1 split: for a 16-bit channel ``(coarse, fine)``, for a
    24-bit channel ``(coarse, fine, ultra)``::

        coarse = raw >> 8·(n−1) & 0xFF
        fine   = raw >> 8·(n−2) & 0xFF      # n ≥ 2
        ultra  = raw & 0xFF                 # n = 3

    >>> split_raw(32768, 2)
    (128, 0)
    >>> split_raw(0x123456, 3)
    (18, 52, 86)

    ``raw`` may also be an integer array (the converter splits every channel
    of one resolution at once); the result is then one array per byte.
    Arrays are not range-checked: the converter only produces values inside
    the channel's DMX range. For a plain ``int``, raises :class:`ValueError`
    if ``raw`` does not fit in ``nbytes`` bytes, rather than silently
    dropping its high bits.
    """
    if isinstance(raw, np.ndarray):
        shifts = (8 * (nbytes - 1 - i) for i in range(nbytes))
        return tuple((raw >> shift if shift else raw) & 0xFF for shift in shifts)
    if not 0 <= raw < 256**nbytes:
        raise ValueError(f"raw value {raw} does not fit in {nbytes} byte(s)")
    return tuple((raw >> (8 * (nbytes - 1 - i))) & 0xFF for i in range(nbytes))
