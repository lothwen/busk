"""Reference converter: spec §13 transcribed one channel at a time.

This is the test oracle for the vectorised :class:`busk.convert.converter.Converter`.
It reads the readable :class:`~busk.compiler.channels.CompiledChannel`
records (the fast converter reads the plan built from the same records) and
converts each channel with plain Python floats.

It deliberately performs the same floating-point operations in the same
order as the fast converter, so the two agree bit for bit, and
``test_convert_properties.py`` compares them byte for byte on random
frames. The golden suites in ``test_convert.py`` and
``test_real_fixtures.py`` run against both.

The rules, in §13 order (see ``busk.compiler.channels`` for how the records
encode them):

* **range**: ``v = (lane + offsetDeg) · sign``; intensity channels then
  apply the mode's curve to ``clip(v, 0, 1)``; then the segment map;
* **colour**: clip ``r, g, b``. Additive: a ``NaN`` white lane derives
  ``w = min(r, g, b)`` and subtracts it from r, g and b; an explicit ``w``
  is used as given; explicit ``a``/``uv`` or 0; any other emitter 0; virtual
  intensity multiplies by ``curve(clip(intensity))``. Subtractive:
  ``1 − r``, ``1 − g``, ``1 − b``; any other flag 0;
* **option**: ``i = clip(round(lane), 0, n − 1)``; its raw value, or its
  parameter lane through the parameter segment;
* **segment map**: the first segment containing ``v``, else the nearest one
  (first on ties) with ``v`` clamped into it; ``t = (v − v0) / (v1 − v0)``,
  ``raw = round(d0 + t · (d1 − d0))``, half to even; a zero-span segment
  outputs ``(d0 + d1) // 2``;
* the raw value is split with ``split_raw`` and written to the owned
  addresses, over a copy of the base images.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from busk.compiler.channels import CompiledChannel, Segment
from busk.compiler.compile import CompiledShow
from busk.compiler.slots import Slot
from busk.convert.dmx import split_raw
from busk.model.profile import DimmerCurve


def reference_convert(compiled: CompiledShow, frame: NDArray[np.float64]) -> NDArray[np.uint8]:
    """Convert ``frame`` channel by channel; return new universe buffers."""
    assert frame.shape == (compiled.slots.laneCount,)
    out = np.array(compiled.baseImages)  # a writable copy
    lanes = [float(x) for x in frame]
    slots = compiled.slots.slots
    for channel in compiled.channels:
        if channel.kind == "range":
            raw = _range(channel, lanes, slots)
        elif channel.kind == "color":
            raw = _color(channel, lanes, slots)
        else:
            raw = _option(channel, lanes, slots)
        for address, byte in zip(channel.addresses, split_raw(raw, channel.bytes), strict=True):
            if address is not None:
                out[channel.universe, address] = byte
    return out


def _lane(lanes: list[float], slots: Sequence[Slot], slot: int, k: int = 0) -> float:
    return lanes[slots[slot].laneOffset + k]


def _range(channel: CompiledChannel, lanes: list[float], slots: Sequence[Slot]) -> int:
    v = (_lane(lanes, slots, channel.slot) + channel.offsetDeg) * channel.sign
    if channel.curve is not None:
        v = curve(channel.curve, clip(v))
    return map_segments(v, channel.segments)


def _color(channel: CompiledChannel, lanes: list[float], slots: Sequence[Slot]) -> int:
    slot = slots[channel.slot]
    r, g, b = (clip(_lane(lanes, slots, channel.slot, k)) for k in range(3))
    if channel.subtractive:
        flags = {"cyanFlag": 1.0 - r, "magentaFlag": 1.0 - g, "yellowFlag": 1.0 - b}
        return map_segments(flags.get(channel.component or "", 0.0), channel.segments)
    extras = {
        extra: _lane(lanes, slots, channel.slot, 3 + k) for k, extra in enumerate(slot.extras)
    }
    w = s = 0.0
    if "w" in extras:
        if math.isnan(extras["w"]):
            w = min(r, g, b)  # derive white and subtract it (§13.3, the fast method)
            s = w
        else:
            w = clip(extras["w"])  # explicit: used as given
    emitters = {
        "red": r - s,
        "green": g - s,
        "blue": b - s,
        "white": w,
        "amber": _explicit(extras.get("a")),
        "uv": _explicit(extras.get("uv")),
    }
    value = emitters.get(channel.component or "", 0.0)
    if channel.intensitySlot is not None:
        assert channel.curve is not None
        value = value * curve(channel.curve, clip(_lane(lanes, slots, channel.intensitySlot)))
    return map_segments(value, channel.segments)


def _option(channel: CompiledChannel, lanes: list[float], slots: Sequence[Slot]) -> int:
    index = min(max(round(_lane(lanes, slots, channel.slot)), 0), len(channel.options) - 1)
    option = channel.options[index]
    if option.param is None:
        return option.raw
    param_slot, segment = option.param
    return map_segments(_lane(lanes, slots, param_slot), (segment,))


# ---------------------------------------------------------------- formulas


def clip(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def _explicit(x: float | None) -> float:
    """An explicit extra emitter: ``None`` (absent) or ``NaN`` (derive) → 0."""
    return 0.0 if x is None or math.isnan(x) else clip(x)


def curve(shape: DimmerCurve, x: float) -> float:
    """§13.2 dimmer curves for ``x`` in ``0..1``."""
    if shape == "linear":
        return x
    if shape == "square":
        return x * x
    if shape == "invSquare":
        y = 1.0 - x
        return 1.0 - y * y
    if shape == "sCurve":
        return x * x * (3.0 - 2.0 * x)
    n = len(shape)
    position = x * (n - 1)
    k = min(math.floor(position), n - 2)
    fraction = position - k
    return shape[k] + fraction * (shape[k + 1] - shape[k])


def map_segments(v: float, segments: Sequence[Segment]) -> int:
    """Map logical ``v`` to a raw DMX value through range segments."""
    chosen = next((s for s in segments if s.low <= v <= s.high), None)
    if chosen is None:  # nearest segment, the first on ties; v is clamped below
        chosen = min(segments, key=lambda s: max(s.low - v, v - s.high))
    if chosen.v0 == chosen.v1:
        return (chosen.d0 + chosen.d1) // 2
    t = clip((v - chosen.v0) / (chosen.v1 - chosen.v0))
    return round(chosen.d0 + t * (chosen.d1 - chosen.d0))
