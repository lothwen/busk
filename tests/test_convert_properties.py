"""Property tests for conversion (hypothesis).

* **Differential:** the vectorised converter equals the per-channel
  reference converter byte for byte, on random frames that include
  out-of-range values, fractional option indices and ``NaN`` extras.
* **Round-trip:** inverting a single-segment channel's raw value lands within
  one DMX step of the (clamped) input (§20).
* **Monotonicity:** on an ascending segment, raw never decreases as the
  value increases.
* **Safety:** intensity 0 puts every dimmer at its 0-intensity value and
  every virtually dimmed emitter at 0, whatever the other lanes say. Phase
  2's blackout relies on this.
* ``split_raw`` recombines exactly.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from numpy.typing import NDArray

from builders import (
    APPENDIX_A,
    DEMO,
    benchmark_rig,
    channel,
    compile_doc,
    effects_rig,
    feature_matrix,
    fixture,
    frame,
    load_doc,
    macro_rig,
    mode,
    profile,
    random_frame,
    rng,
    show,
)
from busk.compiler.compile import CompiledShow
from busk.convert.dmx import split_raw
from conftest import fast_convert
from reference_convert import curve, map_segments, reference_convert

SHOWS: dict[str, Callable[[], CompiledShow]] = {
    "appendix A": lambda: compile_doc(load_doc(APPENDIX_A)),
    "demo": lambda: compile_doc(load_doc(DEMO)),
    "feature matrix": lambda: compile_doc(feature_matrix()),
    "colour macros": lambda: compile_doc(macro_rig()),
    "fixture effects": lambda: compile_doc(effects_rig()),
}


@pytest.fixture(scope="module", params=list(SHOWS))
def compiled(request: pytest.FixtureRequest) -> CompiledShow:
    return SHOWS[request.param]()


# ---------------------------------------------------------------- frames

UNIT = st.one_of(st.floats(-0.25, 1.25), st.sampled_from([0.0, 0.25, 0.5, 0.75, 1.0]))
SCALAR = st.one_of(
    UNIT,
    st.integers(-800, 800).map(lambda k: k / 2),  # whole and half values hit exact boundaries
    st.floats(-1000, 1000),
)
EXTRA = st.one_of(st.just(math.nan), UNIT)  # NaN = "derive this emitter"


def frames(compiled: CompiledShow) -> st.SearchStrategy[NDArray[np.float64]]:
    """Random logical frames for ``compiled``, lane by lane."""
    lanes: list[st.SearchStrategy[float]] = []
    for slot in compiled.slots.slots:
        kind = slot.attribute.kind
        if kind == "scalar":
            lanes.append(SCALAR)
        elif kind == "discrete":
            n = len(slot.options)
            lanes.append(st.one_of(st.integers(-2, n + 1).map(float), st.floats(-3, n + 2)))
        else:
            lanes += [UNIT] * 3 + [EXTRA] * len(slot.extras)
    return st.tuples(*lanes).map(lambda values: np.array(values, dtype=np.float64))


# ----------------------------------------------------------------- properties


@settings(max_examples=150, deadline=None)
@given(data=st.data())
def test_fast_converter_equals_reference(compiled: CompiledShow, data: st.DataObject) -> None:
    logical = data.draw(frames(compiled))
    assert np.array_equal(fast_convert(compiled, logical), reference_convert(compiled, logical))


def test_fast_converter_equals_reference_at_scale() -> None:
    compiled = compile_doc(benchmark_rig(universes=4))
    generator = np.random.default_rng(1)
    for _ in range(10):
        logical = random_frame(compiled, generator)
        assert np.array_equal(fast_convert(compiled, logical), reference_convert(compiled, logical))


@settings(max_examples=100, deadline=None)
@given(data=st.data())
def test_intensity_zero_is_dark(compiled: CompiledShow, data: st.DataObject) -> None:
    logical = data.draw(frames(compiled))
    slots = compiled.slots.slots
    for slot in slots:
        if slot.attribute.id == "intensity":
            logical[slot.laneOffset] = 0.0
    out = fast_convert(compiled, logical)
    checked = 0
    for record in compiled.channels:
        if record.kind == "range" and slots[record.slot].attribute.id == "intensity":
            assert record.curve is not None
            expected = map_segments(curve(record.curve, 0.0), record.segments)
        elif record.kind == "color" and record.intensitySlot is not None:
            expected = map_segments(0.0, record.segments)  # every emitter off
        else:
            continue
        checked += 1
        for address, byte in zip(record.addresses, split_raw(expected, record.bytes), strict=True):
            if address is not None:
                assert out[record.universe, address] == byte
    assert checked


def single_channel(v0: float, v1: float, d0: int, d1: int) -> CompiledShow:
    """A fixture whose 16-bit pan maps logical ``v0 → v1`` to DMX ``d0 → d1``."""
    doc = show(
        [
            profile(
                "p",
                mode([channel(0, "intensity"), channel(1, "pan", rng(d0, d1, v0, v1), nbytes=2)]),
            )
        ],
        [fixture("f", 1, "p", 1)],
    )
    return compile_doc(doc)


def pan_raw(compiled: CompiledShow, value: float) -> int:
    out = fast_convert(compiled, frame(compiled, {("f", "pan"): value}))
    return int(out[0, 1]) << 8 | int(out[0, 2])


type SegmentArgs = tuple[float, float, int, int]


@st.composite
def segments(draw: st.DrawFn, *, ascending: bool = False) -> SegmentArgs:
    """``(v0, v1, d0, d1)`` with ``d0 < d1`` and a non-trivial value span."""
    v0 = draw(st.floats(-1000, 1000))
    span = draw(st.floats(1e-3, 1000))
    v1 = v0 + span if ascending or draw(st.booleans()) else v0 - span
    d0 = draw(st.integers(0, 65534))
    d1 = draw(st.integers(d0 + 1, 65535))
    return v0, v1, d0, d1


VALUES = st.floats(-2000, 2000)


@settings(max_examples=150, deadline=None)
@given(segment=segments(), value=VALUES)
def test_round_trip_within_one_dmx_step(segment: SegmentArgs, value: float) -> None:
    v0, v1, d0, d1 = segment
    raw = pan_raw(single_channel(*segment), value)
    assert d0 <= raw <= d1
    back = v0 + (raw - d0) / (d1 - d0) * (v1 - v0)
    clamped = min(max(value, min(v0, v1)), max(v0, v1))
    step = abs(v1 - v0) / (d1 - d0)
    assert abs(back - clamped) <= step * (1 + 1e-9)


@settings(max_examples=150, deadline=None)
@given(segment=segments(ascending=True), a=VALUES, b=VALUES)
def test_monotonic_on_an_ascending_segment(segment: SegmentArgs, a: float, b: float) -> None:
    low, high = sorted((a, b))
    compiled = single_channel(*segment)
    assert pan_raw(compiled, low) <= pan_raw(compiled, high)


def test_split_raw_recombines_every_16_bit_value() -> None:
    raw = np.arange(65536, dtype=np.int64)
    coarse, fine = split_raw(raw, 2)
    assert np.array_equal(coarse << 8 | fine, raw)
    assert all(
        split_raw(int(r), 2) == (int(c), int(f))
        for r, c, f in zip(raw[::97], coarse[::97], fine[::97], strict=True)
    )


@given(st.integers(0, 2**24 - 1))
def test_split_raw_recombines_24_bit_values(raw: int) -> None:
    coarse, fine, ultra = split_raw(np.array([raw], dtype=np.int64), 3)
    assert int(coarse[0]) << 16 | int(fine[0]) << 8 | int(ultra[0]) == raw
    assert split_raw(raw, 3) == (int(coarse[0]), int(fine[0]), int(ultra[0]))
