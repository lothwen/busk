"""Lane encoding (§6.2): ``encode_value(slot, value)`` for each kind."""

from __future__ import annotations

import math

import pytest

from builders import compile_doc, feature_matrix
from busk.compiler.compile import CompiledShow
from busk.compiler.lanes import EncodeError, encode_value
from busk.compiler.slots import Slot
from busk.model.common import FixtureId, TargetRef


@pytest.fixture(scope="module")
def matrix() -> CompiledShow:
    return compile_doc(feature_matrix())


def slot(matrix: CompiledShow, fixture_id: str, attribute: str) -> Slot:
    found = matrix.slots.find(TargetRef(fixtureId=FixtureId(fixture_id), element=0), attribute)
    assert found is not None
    return found


def test_scalar(matrix: CompiledShow) -> None:
    assert encode_value(slot(matrix, "fx-swap", "pan"), 22.5) == (22.5,)
    assert encode_value(slot(matrix, "fx-dim16", "intensity"), 1) == (1.0,)


def test_colour_without_extras(matrix: CompiledShow) -> None:
    assert encode_value(slot(matrix, "fx-par", "color"), {"r": 1, "g": 0.5, "b": 0}) == (
        1.0,
        0.5,
        0.0,
    )


def test_missing_extras_are_nan(matrix: CompiledShow) -> None:
    lanes = encode_value(slot(matrix, "fx-rgbawuv", "color"), {"r": 1, "g": 0.5, "b": 0, "a": 0.25})
    assert lanes[:3] == (1.0, 0.5, 0.0)
    assert math.isnan(lanes[3])  # w: derive
    assert lanes[4] == 0.25  # a: explicit
    assert math.isnan(lanes[5])  # uv: not given


def test_extras_the_element_lacks_are_dropped(matrix: CompiledShow) -> None:
    value = {"r": 0, "g": 0, "b": 1, "w": 1, "a": 1, "uv": 1}
    assert encode_value(slot(matrix, "fx-rgbw", "color"), value) == (0.0, 0.0, 1.0, 1.0)
    assert encode_value(slot(matrix, "fx-par", "color"), value) == (0.0, 0.0, 1.0)


def test_discrete_option_index(matrix: CompiledShow) -> None:
    shutter = slot(matrix, "fx-shutter", "shutter")
    assert shutter.options == ("closed", "open", "strobe", "pulse", "random")
    assert encode_value(shutter, {"slot": "closed"}) == (0.0,)
    assert encode_value(shutter, {"slot": "random"}) == (4.0,)


def test_unknown_option_raises(matrix: CompiledShow) -> None:
    shutter = slot(matrix, "fx-shutter", "shutter")
    with pytest.raises(EncodeError, match=r"fx-shutter:0 has no 'shutter' option 'macro'"):
        encode_value(shutter, {"slot": "macro"})  # a function, but not a shutter option
