"""The vectorised converter: logical frame → DMX bytes (spec §4.2 stage 12, §13).

:class:`Converter` runs a fixed sequence of numpy kernels over a
:class:`~busk.convert.plan.ConversionPlan`:

1. **Range inputs.** ``V = (L[lane] + offset) · sign`` for every range
   channel, which applies pan/tilt orientation. Then, per dimmer curve,
   ``V = curve(clip(V, 0, 1))`` for the intensity channels.
2. **Colour inputs.** Per colour slot: clip ``r, g, b``; derive white as
   ``min(r, g, b)`` and subtract it when the slot's ``w`` lane is ``NaN``
   (an explicit ``w`` is used as given, with nothing subtracted); take
   explicit ``a``/``uv`` or 0; compute the CMY flags ``1 − r`` etc. for
   subtractive slots. Each of those rows is computed only for the slots
   that have it. Virtual intensity scales the additive rows by
   ``curve(clip(intensity, 0, 1))``. Each colour channel then picks its
   ``(emitter role, slot)`` entry.
3. **Segment maps, V → raw.** One uniform map for every value; channels
   with several range segments pick the first segment containing ``v``, or
   the nearest one (the first on ties), with ``v`` clamped into it.
4. **Options.** ``i = clip(rint(L[lane]), 0, n − 1)``; the chosen option's
   parameter lane is mapped through its segment (a constant map for options
   without a parameter).
5. **Split and scatter.** Per resolution, :func:`~busk.convert.dmx.split_raw`
   on the raw values, then each byte is written to its unique address.

Rounding is round-half-even (``np.rint``, the same rule as Python's
``round``). Python loops run only over the plan's few groups (curves and
resolutions), never over channels or slots. The scratch buffers are
allocated once; the numpy temporaries the kernels still create are not
tracked by the cyclic garbage collector, so they cause no GC pauses (§19).

The test suite holds a per-channel reference transcription of §13
(``tests/reference_convert.py``) that performs the same floating-point
operations in the same order, and a property test checks that both
converters agree byte for byte.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from busk.convert.curves import CurveFunction, curve_function
from busk.convert.dmx import UNIVERSE_SIZE, split_raw
from busk.convert.plan import COLOR_ROWS, ConversionPlan, IntArray, SegmentMaps

type FloatArray = NDArray[np.float64]


class Converter:
    """Converts logical frames to universe buffers with one plan.

    A converter owns scratch buffers, so each thread needs its own (the
    engine thread is the only one that converts).
    """

    def __init__(self, plan: ConversionPlan) -> None:
        self._plan = plan
        r, c, o = plan.rangeCount, plan.colorCount, plan.optionCount
        self._values = np.zeros(r + c)  # V
        self._range_values = self._values[:r]
        self._color_values = self._values[r:]
        self._t = np.zeros(r + c)
        self._raw = np.zeros(r + c + o, dtype=np.int64)
        self._value_raw = self._raw[: r + c]
        self._option_raw = self._raw[r + c :]
        self._option_index = np.zeros(o)
        columns = plan.colors.columns
        self._matrix = np.zeros((COLOR_ROWS, columns))  # the last row (ZERO_ROW) stays 0
        self._factor = np.ones(columns)
        self._dimmers: list[tuple[CurveFunction, IntArray]] = [
            (curve_function(group.curve), group.positions) for group in plan.ranges.dimmerGroups
        ]
        self._virtual: list[tuple[CurveFunction, IntArray, IntArray]] = [
            (curve_function(group.curve), group.columns, group.lanes)
            for group in plan.colors.virtualGroups
        ]

    def convert(self, frame: FloatArray, out: NDArray[np.uint8]) -> None:
        """Convert the logical ``frame`` into ``out``.

        ``frame`` holds ``plan.laneCount`` float64 lanes. ``out`` is the
        C-contiguous ``(universes, 512)`` buffer; it must already hold the
        base images, because only slot-driven channels are written (untouched
        channels keep their ``defaultDmx``, unpatched addresses stay 0).
        """
        plan = self._plan
        if frame.shape != (plan.laneCount,):
            raise ValueError(f"frame has shape {frame.shape}; expected ({plan.laneCount},)")
        if out.shape != (plan.universeCount, UNIVERSE_SIZE) or not out.flags.c_contiguous:
            raise ValueError(
                f"out must be a C-contiguous ({plan.universeCount}, {UNIVERSE_SIZE}) array"
            )
        self._range_inputs(frame)
        if plan.colorCount:
            self._color_inputs(frame)
        _map(plan.segments, self._values, self._t, self._value_raw)
        self._multi_segments()
        if plan.optionCount:
            self._options(frame)
        self._scatter(out.reshape(-1))

    # -- kernels

    def _range_inputs(self, frame: FloatArray) -> None:
        ranges = self._plan.ranges
        values = self._range_values
        np.take(frame, ranges.lanes, out=values)
        values += ranges.offsets
        values *= ranges.signs
        for curve, positions in self._dimmers:
            values[positions] = curve(np.clip(values[positions], 0.0, 1.0))

    def _color_inputs(self, frame: FloatArray) -> None:
        colors = self._plan.colors
        matrix = self._matrix
        rgb = matrix[:3]  # rows 0–2 start as the clipped r, g, b
        np.take(frame, colors.rgbLanes, out=rgb)
        np.clip(rgb, 0.0, 1.0, out=rgb)
        subtractive = colors.subtractiveColumns
        if subtractive.size:
            matrix[6:9, subtractive] = 1.0 - rgb[:, subtractive]
        white = colors.white
        if white.columns.size:
            # Derived (NaN lane): w = min(r, g, b), subtracted from r, g and b.
            # Explicit: used as given, nothing subtracted.
            lane = np.take(frame, white.lanes)
            derive = np.isnan(lane)
            red, green, blue = rgb[:, white.columns]
            minimum = np.minimum(np.minimum(red, green), blue)
            value = _explicit(lane)
            np.copyto(value, minimum, where=derive)
            matrix[3, white.columns] = value
            rgb[:, white.columns] -= minimum * derive
        if colors.amber.columns.size:
            matrix[4, colors.amber.columns] = _explicit(np.take(frame, colors.amber.lanes))
        if colors.uv.columns.size:
            matrix[5, colors.uv.columns] = _explicit(np.take(frame, colors.uv.lanes))
        # Virtual intensity scales every additive emitter (rows 0–5).
        if self._virtual:
            factor = self._factor
            for curve, columns, lanes in self._virtual:
                factor[columns] = curve(np.clip(np.take(frame, lanes), 0.0, 1.0))
            matrix[:6] *= factor
        np.take(matrix, colors.pick, out=self._color_values)

    def _multi_segments(self) -> None:
        segments = self._plan.segments
        positions = segments.multiPositions
        if not positions.size:
            return
        value = self._values[positions][:, np.newaxis]
        distance = np.maximum(
            np.maximum(segments.multiLow - value, value - segments.multiHigh), 0.0
        )
        chosen = np.argmin(distance, axis=1)[:, np.newaxis]  # first minimum on ties

        def pick(table: FloatArray) -> FloatArray:
            return np.take_along_axis(table, chosen, axis=1)[:, 0]

        t = (value[:, 0] - pick(segments.multiV0)) / pick(segments.multiSpan)
        np.clip(t, 0.0, 1.0, out=t)
        t *= pick(segments.multiDSpan)
        t += pick(segments.multiD0)
        self._raw[positions] = np.rint(t)

    def _options(self, frame: FloatArray) -> None:
        options = self._plan.options
        index = self._option_index
        np.take(frame, options.lanes, out=index)
        np.rint(index, out=index)
        np.clip(index, 0.0, options.last, out=index)
        chosen = index.astype(np.intp)
        chosen += options.first
        maps = options.maps
        value = np.take(frame, np.take(options.paramLanes, chosen))
        t = (value - np.take(maps.v0, chosen)) / np.take(maps.span, chosen)
        np.clip(t, 0.0, 1.0, out=t)
        t *= np.take(maps.dspan, chosen)
        t += np.take(maps.d0, chosen)
        np.rint(t, out=t)
        np.copyto(self._option_raw, t, casting="unsafe")

    def _scatter(self, flat: NDArray[np.uint8]) -> None:
        raw = self._raw
        for group in self._plan.byteGroups:
            values = np.take(raw, group.channels)
            for byte, (owned, addresses) in zip(
                split_raw(values, group.bytes), group.targets, strict=True
            ):
                flat[addresses] = byte if owned is None else byte[owned]


def _map(maps: SegmentMaps, values: FloatArray, t: FloatArray, raw: NDArray[np.int64]) -> None:
    """``raw = rint(d0 + clip((v − v0) / span, 0, 1) · dspan)`` for every value."""
    np.subtract(values, maps.v0, out=t)
    t /= maps.span
    np.clip(t, 0.0, 1.0, out=t)
    t *= maps.dspan
    t += maps.d0
    np.rint(t, out=t)
    np.copyto(raw, t, casting="unsafe")


def _explicit(lane: FloatArray) -> FloatArray:
    """An explicit extra (``w``/``a``/``uv``) clipped to 0..1; ``NaN`` → 0."""
    return np.clip(np.nan_to_num(lane, nan=0.0), 0.0, 1.0)
