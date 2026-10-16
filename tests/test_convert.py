"""Golden conversion tests (§13), run against both converters.

Every expected byte is worked out by hand from the spec's formula, written
with literal numbers in the comments; none was produced by running the code.
The ``convert`` fixture (``conftest.py``) runs each test once with the
per-channel reference converter and once with the vectorised one.

Synthetic cases use the feature-matrix show (``builders.feature_matrix``);
its patch is listed in ``builders.MATRIX_PATCH``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from builders import (
    APPENDIX_A,
    channels_at,
    compile_doc,
    feature_matrix,
    frame,
    issues_of,
    load_doc,
    nonzero,
)
from busk.compiler.compile import CompiledShow
from busk.model.common import FixtureId, TargetRef
from conftest import Convert


@pytest.fixture(scope="module")
def appendix() -> CompiledShow:
    return compile_doc(load_doc(APPENDIX_A))


@pytest.fixture(scope="module")
def matrix() -> CompiledShow:
    return compile_doc(feature_matrix())


def test_feature_matrix_validates_with_only_the_deliberate_overlap() -> None:
    assert [(i.severity, i.path) for i in issues_of(feature_matrix())] == [
        ("warning", "fixtures[15].patch.address")  # fx-late overlaps fx-early
    ]


# ------------------------------------------------------------- Appendix A


def test_spec_7_8_worked_example(convert: Convert, appendix: CompiledShow) -> None:
    # §7.8: MH1 intensity 0.48, colour {.75, .75, 1}, pan 22.5°.
    values = {
        ("fx-mh1", "intensity"): 0.48,
        ("fx-mh1", "color"): {"r": 0.75, "g": 0.75, "b": 1.0},
        ("fx-mh1", "pan"): 22.5,
    }
    out = convert(appendix, frame(appendix, values))
    assert channels_at(out[0], [9, 10, 1, 2, 5, 6, 7, 8]) == {
        # Dimmer, 16-bit: 0.48 × 65535 = 31456.8 → 31457 = 122·256 + 225.
        9: 122,
        10: 225,
        # Pan: (22.5 + 270) / 540 × 65535 = 35497.8 → 35498 = 138·256 + 170.
        1: 138,
        2: 170,
        # RGBW: W = min = 0.75; R = G = 0; B = 0.25 → 63.75 → 64; W → 191.25 → 191.
        5: 0,
        6: 0,
        7: 64,
        8: 191,
    }


def test_appendix_a_defaults_open_the_shutters(convert: Convert, appendix: CompiledShow) -> None:
    out = convert(appendix, frame(appendix))
    assert nonzero(out[0]) == {
        # MH 1 at 1: pan/tilt 0° → 32767.5 → 32768 (half to even) = 128·256 + 0.
        1: 128,
        3: 128,
        # Colour white {1,1,1}, W derived: R = G = B = 0, W = 1 → 255.
        8: 255,
        # Zoom: midpoint of zoomRange [12, 30] = 21 → 9/18 × 255 = 127.5 → 128.
        11: 128,
        # Gobo open: centre of 0–9 = 4. Shutter open: centre of 8–15 = 11
        # (Phase 0 output the closed defaultDmx 0 here).
        12: 4,
        13: 11,
        # MH 2 at 17, the same; invertPan of 0° is still the centre.
        17: 128,
        19: 128,
        24: 255,
        27: 128,
        28: 4,
        29: 11,
        # The par at 101 is virtual at intensity 0: dark.
    }


def test_inverted_pan(convert: Convert, appendix: CompiledShow) -> None:
    out = convert(appendix, frame(appendix, {("fx-mh2", "pan"): 22.5}))
    # −22.5° → (247.5 / 540) × 65535 = 30036.875 → 30037 = 117·256 + 85.
    assert channels_at(out[0], [17, 18]) == {17: 117, 18: 85}


def test_appendix_a_par_is_dimmed_virtually(convert: Convert, appendix: CompiledShow) -> None:
    values = {("fx-par1", "intensity"): 0.5, ("fx-par1", "color"): {"r": 1, "g": 0.5, "b": 0}}
    out = convert(appendix, frame(appendix, values))
    # 1 × 0.5 → 127.5 → 128; 0.5 × 0.5 = 0.25 → 63.75 → 64; 0.
    assert channels_at(out[0], [101, 102, 103]) == {101: 128, 102: 64, 103: 0}


# ------------------------------------------------- resolution and rounding


def test_rounding_is_half_to_even(convert: Convert, matrix: CompiledShow) -> None:
    out = convert(matrix, frame(matrix))
    # fx-half's focus (default 0.5) on dmx [0, 253]: 126.5 → 126; half-up would give 127.
    assert channels_at(out[0], [14]) == {14: 126}


@pytest.mark.parametrize(
    ("level", "coarse", "fine"),
    [
        (0.0, 0, 0),
        (0.25, 64, 0),  # 16383.75 → 16384 = 64·256
        (0.5, 128, 0),  # 32767.5 → 32768 (even)
        (1.0, 255, 255),
    ],
)
def test_16_bit_dimmer(
    convert: Convert, matrix: CompiledShow, level: float, coarse: int, fine: int
) -> None:
    out = convert(matrix, frame(matrix, {("fx-dim16", "intensity"): level}))
    assert channels_at(out[0], [1, 2]) == {1: coarse, 2: fine}


def test_24_bit_split_with_non_adjacent_fine_bytes(convert: Convert, matrix: CompiledShow) -> None:
    out = convert(matrix, frame(matrix, {("fx-ultra", "pan"): -100}))
    # (−100 + 270) / 540 × 16777215 = 2852126550 / 540 = 5281715.83 → 5281716 = 0x5097B4:
    # coarse 0x50 at offset 0 (ch 8), fine 0x97 at offset 4 (ch 12), ultra 0xB4 at offset 2 (ch 10).
    assert channels_at(out[0], [8, 12, 10, 11]) == {8: 0x50, 12: 0x97, 10: 0xB4, 11: 0}


@pytest.mark.parametrize(
    ("level", "expected"),
    [(0.0, 255), (1.0, 0), (0.25, 191)],  # segment [1 → 0]: t = 0.75 → 191.25 → 191
)
def test_inverted_dimmer(
    convert: Convert, matrix: CompiledShow, level: float, expected: int
) -> None:
    out = convert(matrix, frame(matrix, {("fx-diminv", "intensity"): level}))
    assert channels_at(out[0], [3]) == {3: expected}


CURVES = {
    # fixture: (channel, {level: byte})
    "fx-square": (4, {0.0: 0, 0.25: 16, 0.5: 64, 1.0: 255}),  # 15.94, 63.75
    "fx-invsquare": (5, {0.0: 0, 0.25: 112, 0.5: 191, 1.0: 255}),  # 0.4375 → 111.56; 0.75 → 191.25
    "fx-scurve": (6, {0.0: 0, 0.25: 40, 0.5: 128, 1.0: 255}),  # 0.15625 → 39.84; 0.5 → 127.5
    "fx-table": (7, {0.0: 0, 0.25: 38, 0.5: 102, 1.0: 255}),  # [0 .2 .6 1]: 0.15 → 38.25; 0.4
}


@pytest.mark.parametrize("fixture_id", list(CURVES))
@pytest.mark.parametrize("level", [0.0, 0.25, 0.5, 1.0])
def test_dimmer_curves(
    convert: Convert, matrix: CompiledShow, fixture_id: str, level: float
) -> None:
    number, expected = CURVES[fixture_id]
    out = convert(matrix, frame(matrix, {(fixture_id, "intensity"): level}))
    assert channels_at(out[0], [number]) == {number: expected[level]}


def test_dimmer_input_is_clipped_before_the_curve(convert: Convert, matrix: CompiledShow) -> None:
    out = convert(matrix, frame(matrix, {("fx-invsquare", "intensity"): 1.5}))
    assert channels_at(out[0], [5]) == {5: 255}  # 1 − (1 − 1.5)² = 0.75 without clipping


# ------------------------------------------------------- multi-segment maps


@pytest.mark.parametrize(
    ("rotation", "expected"),
    [
        (0, 4),  # the zero-span stop outputs its centre: (0 + 9) // 2
        (55, 55),  # CW: t = 45/90 = 0.5 → 10 + 45
        (-55, 150),  # CCW: t = 0.5 → 101 + 49.5 = 150.5 → 150 (even)
        (100, 100),
        (-10, 101),
        (4, 4),  # gap: the stop (4 away) is nearer than CW (6 away)
        (6, 10),  # gap: CW is nearer; clamped to its start
        (5, 4),  # gap, a tie: the first segment wins
        (1000, 100),  # beyond CW: clamped
        (-1000, 200),  # beyond CCW: clamped
    ],
)
def test_multi_segment_channel(
    convert: Convert, matrix: CompiledShow, rotation: float, expected: int
) -> None:
    out = convert(matrix, frame(matrix, {("fx-multi", "gobo1Rotation"): rotation}))
    assert channels_at(out[0], [16]) == {16: expected}


# ------------------------------------------------------------------ colour


def test_virtual_intensity_zero_darkens_every_emitter(
    convert: Convert, matrix: CompiledShow
) -> None:
    values = {
        ("fx-rgbawuv", "color"): {"r": 1, "g": 1, "b": 1, "w": 1, "a": 1, "uv": 1},
        ("fx-par", "color"): {"r": 1, "g": 1, "b": 1},
    }
    out = convert(matrix, frame(matrix, values))  # intensity defaults to 0
    assert channels_at(out[0], range(22, 29)) == dict.fromkeys(range(22, 29), 0)
    assert channels_at(out[0], [48, 49, 50]) == {48: 0, 49: 0, 50: 0}


def test_rgbw_white_extraction(convert: Convert, matrix: CompiledShow) -> None:
    out = convert(matrix, frame(matrix, {("fx-rgbw", "color"): {"r": 1, "g": 0.5, "b": 0.25}}))
    # W = min = 0.25 → 63.75 → 64; R = 0.75 → 191.25 → 191; G = 0.25 → 64; B = 0.
    assert channels_at(out[0], [18, 19, 20, 21]) == {18: 191, 19: 64, 20: 0, 21: 64}


def test_explicit_white_is_used_as_given(convert: Convert, matrix: CompiledShow) -> None:
    value = {"r": 1, "g": 0.5, "b": 0.25, "w": 1}
    out = convert(matrix, frame(matrix, {("fx-rgbw", "color"): value}))
    # Nothing is subtracted: 255, 127.5 → 128, 63.75 → 64, 255.
    assert channels_at(out[0], [18, 19, 20, 21]) == {18: 255, 19: 128, 20: 64, 21: 255}


def test_amber_and_uv_default_to_zero(convert: Convert, matrix: CompiledShow) -> None:
    values = {("fx-rgbawuv", "intensity"): 1, ("fx-rgbawuv", "color"): {"r": 1, "g": 1, "b": 1}}
    out = convert(matrix, frame(matrix, values))
    # W derived = 1, R = G = B = 0; A and UV are not derived; lime is never mixed.
    assert channels_at(out[0], range(22, 29)) == {22: 0, 23: 0, 24: 0, 25: 255, 26: 0, 27: 0, 28: 0}


def test_explicit_extras_and_the_curve_of_virtual_intensity(
    convert: Convert, matrix: CompiledShow
) -> None:
    values = {
        ("fx-rgbawuv", "intensity"): 0.5,  # square curve → 0.25
        ("fx-rgbawuv", "color"): {"r": 0.5, "g": 0.5, "b": 0.5, "a": 1, "uv": 0.5},
    }
    out = convert(matrix, frame(matrix, values))
    # W = 0.5 × 0.25 = 0.125 → 31.875 → 32; A = 0.25 → 63.75 → 64; UV = 0.125 → 32.
    assert channels_at(out[0], range(22, 29)) == {
        22: 0,
        23: 0,
        24: 0,
        25: 32,
        26: 64,
        27: 32,
        28: 0,
    }


def test_cmy_in_a_second_universe(convert: Convert, matrix: CompiledShow) -> None:
    out = convert(matrix, frame(matrix, {("fx-cmy", "color"): {"r": 1, "g": 0.5, "b": 0}}))
    # C = 1 − 1 = 0; M = 0.5 → 127.5 → 128; Y = 1 → 255.
    assert channels_at(out[1], [2, 3, 4]) == {2: 0, 3: 128, 4: 255}
    assert nonzero(out[1]) == {3: 128, 4: 255}  # the CMY dimmer at u2/1 is at 0


def test_cmy_white_is_all_flags_out(convert: Convert, matrix: CompiledShow) -> None:
    assert nonzero(convert(matrix, frame(matrix))[1]) == {}


# ----------------------------------------------------------------- shutter


@pytest.mark.parametrize(
    ("shutter", "rate", "expected"),
    [
        ("open", 0, 11),  # centre of 8–15
        ("closed", 0, 3),  # centre of 0–7
        ("random", 0, 154),  # centre of 150–159
        ("strobe", 1, 16),
        ("strobe", 20, 131),
        ("strobe", 10.5, 74),  # t = 9.5 / 19 = 0.5 → 16 + 57.5 = 73.5 → 74 (even)
        ("strobe", 50, 131),  # clamped to the top of the parameter range
        ("strobe", 0, 16),  # strobeRate's default is below the range: clamped
        ("pulse", 12, 144),  # zero-span parameter: centre of 140–149
    ],
)
def test_shutter(
    convert: Convert, matrix: CompiledShow, shutter: str, rate: float, expected: int
) -> None:
    values: dict[Any, Any] = {
        ("fx-shutter", "shutter"): {"slot": shutter},
        ("fx-shutter", "strobeRate"): rate,
    }
    out = convert(matrix, frame(matrix, values))
    assert channels_at(out[0], [30]) == {30: expected}


@pytest.mark.parametrize(("index", "expected"), [(99.0, 154), (-3.0, 3), (1.4, 11), (2.5, 16)])
def test_option_index_is_rounded_and_clipped(
    convert: Convert, matrix: CompiledShow, index: float, expected: int
) -> None:
    # Options: 0 closed, 1 open, 2 strobe, 3 pulse, 4 random. 2.5 → 2 (half to even).
    logical = frame(matrix, {("fx-shutter", "strobeRate"): 1})
    found = matrix.slots.find(TargetRef(fixtureId=FixtureId("fx-shutter"), element=0), "shutter")
    assert found is not None
    logical[found.laneOffset] = index
    assert channels_at(convert(matrix, logical)[0], [30]) == {30: expected}


# --------------------------------------------------------------- pan/tilt


def test_swap_offsets_and_inverts(convert: Convert, matrix: CompiledShow) -> None:
    out = convert(matrix, frame(matrix, {("fx-swap", "pan"): 30, ("fx-swap", "tilt"): -20}))
    assert channels_at(out[0], [32, 33, 34, 35]) == {
        # Pan channel reads tilt: −20 + panOffset 10 = −10 → 260/540 × 65535 = 31553.9 → 31554
        # = 123·256 + 66.
        32: 123,
        33: 66,
        # Tilt channel reads pan: 30 + tiltOffset −5 = 25, inverted → −25
        # → 110/270 × 65535 = 26699.4 → 26699 = 104·256 + 75.
        34: 104,
        35: 75,
    }


def test_offset_then_invert(convert: Convert, matrix: CompiledShow) -> None:
    out = convert(matrix, frame(matrix))
    # Pan 0 + 45 = 45, inverted → −45 → 225/540 × 65535 = 27306.25 → 27306 = 106·256 + 170.
    # Tilt 0 → 32767.5 → 32768.
    assert channels_at(out[0], [37, 38, 39, 40]) == {37: 106, 38: 170, 39: 128, 40: 0}


# ------------------------------------------------ untouched, unpatched, overlap


def test_untouched_channels_keep_default_dmx(convert: Convert, matrix: CompiledShow) -> None:
    assert channels_at(convert(matrix, frame(matrix))[0], [47]) == {47: 77}
    full = frame(matrix, {("fx-control", "intensity"): 1})
    assert channels_at(convert(matrix, full)[0], [46, 47]) == {46: 255, 47: 77}


def test_unpatched_addresses_stay_zero(convert: Convert, matrix: CompiledShow) -> None:
    out = convert(matrix, frame(matrix, {("fx-unpatched", "intensity"): 1}))
    assert not out[0, 50:].any()
    assert not out[1, 4:].any()
    assert out[0, 10] == 0  # inside fx-ultra's footprint, but no channel uses offset 3


def test_overlap_the_later_fixture_owns_shared_bytes(
    convert: Convert, matrix: CompiledShow
) -> None:
    values = {("fx-early", "iris"): 1, ("fx-late", "intensity"): 0.5}
    out = convert(matrix, frame(matrix, values))
    # fx-early's iris (ch 43) is lost to fx-late's dimmer: 0.5 → 127.5 → 128.
    # Focus defaults to 0.5 → 128 on both; fx-late's iris defaults to 1 → 255.
    assert channels_at(out[0], [41, 42, 43, 44, 45]) == {41: 0, 42: 128, 43: 128, 44: 128, 45: 255}


def test_converting_twice_gives_the_same_bytes(convert: Convert, matrix: CompiledShow) -> None:
    logical = frame(matrix, {("fx-rgbw", "color"): {"r": 0.3, "g": 0.6, "b": 0.9}})
    assert np.array_equal(convert(matrix, logical), convert(matrix, logical))
