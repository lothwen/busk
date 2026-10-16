"""Compiled channels: addresses, orientation folding, segments, options, ownership."""

from __future__ import annotations

import dataclasses

import pytest

from builders import APPENDIX_A, DEMO, compile_doc, feature_matrix, load_doc
from busk.compiler.channels import CompiledChannel, OptionOut, Segment
from busk.compiler.compile import CompiledShow
from busk.model.common import FixtureId, TargetRef


@pytest.fixture(scope="module")
def appendix() -> CompiledShow:
    return compile_doc(load_doc(APPENDIX_A))


@pytest.fixture(scope="module")
def demo() -> CompiledShow:
    return compile_doc(load_doc(DEMO))


@pytest.fixture(scope="module")
def matrix() -> CompiledShow:
    return compile_doc(feature_matrix())


def channels_of(compiled: CompiledShow, fixture_id: str) -> list[CompiledChannel]:
    return [c for c in compiled.channels if c.fixtureId == fixture_id]


def slot_index(compiled: CompiledShow, fixture_id: str, attribute: str, element: int = 0) -> int:
    found = compiled.slots.find(
        TargetRef(fixtureId=FixtureId(fixture_id), element=element), attribute
    )
    assert found is not None
    return found.index


def test_appendix_a_channel_table(appendix: CompiledShow) -> None:
    def row(c: CompiledChannel) -> tuple[object, ...]:
        attribute = appendix.slots.slots[c.slot].attribute.id
        return (c.offset, c.addresses, c.kind, attribute, c.component)

    # MH 1 at address 1 (0-based 0). Pan/tilt fine bytes follow their coarse bytes.
    assert [row(c) for c in channels_of(appendix, "fx-mh1")] == [
        (0, (0, 1), "range", "pan", None),
        (2, (2, 3), "range", "tilt", None),
        (4, (4,), "color", "color", "red"),
        (5, (5,), "color", "color", "green"),
        (6, (6,), "color", "color", "blue"),
        (7, (7,), "color", "color", "white"),
        (8, (8, 9), "range", "intensity", None),
        (10, (10,), "range", "zoom", None),
        (11, (11,), "option", "gobo1", None),
        (12, (12,), "option", "shutter", None),
    ]
    # MH 2 at 17; the par at 101.
    assert [c.addresses[0] for c in channels_of(appendix, "fx-mh2")] == [
        16, 18, 20, 21, 22, 23, 24, 26, 27, 28,
    ]  # fmt: skip
    assert [c.addresses for c in channels_of(appendix, "fx-par1")] == [(100,), (101,), (102,)]
    assert {c.universe for c in appendix.channels} == {0}


def test_appendix_a_segments_and_curves(appendix: CompiledShow) -> None:
    pan, tilt, red, *_, intensity, zoom, _, _ = channels_of(appendix, "fx-mh1")
    assert pan.segments == (Segment(v0=-270.0, v1=270.0, d0=0, d1=65535),)
    assert tilt.segments == (Segment(v0=-135.0, v1=135.0, d0=0, d1=65535),)
    assert zoom.segments == (Segment(v0=12.0, v1=30.0, d0=0, d1=255),)
    assert intensity.curve == "linear"
    assert pan.curve is None
    assert red.curve is None  # MH 1 has a dimmer channel: no virtual intensity
    assert red.intensitySlot is None


def test_appendix_a_option_tables(appendix: CompiledShow) -> None:
    *_, gobo, shutter = channels_of(appendix, "fx-mh1")
    assert gobo.options == (OptionOut(raw=4), OptionOut(raw=14))  # centres of 0–9, 10–19
    strobe_rate = slot_index(appendix, "fx-mh1", "strobeRate")
    assert shutter.options == (
        OptionOut(raw=3),  # closed 0–7
        OptionOut(raw=11),  # open 8–15
        OptionOut(raw=73, param=(strobe_rate, Segment(v0=1.0, v1=20.0, d0=16, d1=131))),
    )


def test_virtual_par_reads_its_intensity_slot(appendix: CompiledShow) -> None:
    intensity = slot_index(appendix, "fx-par1", "intensity")
    for record in channels_of(appendix, "fx-par1"):
        assert (record.intensitySlot, record.curve) == (intensity, "linear")


def test_inverted_pan_folds_into_the_sign(appendix: CompiledShow) -> None:
    pan = channels_of(appendix, "fx-mh2")[0]
    assert (pan.sign, pan.offsetDeg) == (-1.0, 0.0)
    assert channels_of(appendix, "fx-mh1")[0].sign == 1.0


def test_swap_reads_the_other_slot_with_the_channels_own_offset(matrix: CompiledShow) -> None:
    pan, tilt = channels_of(matrix, "fx-swap")[1:3]
    # The pan channel reads the tilt slot, with panOffset (10) and invertPan (off).
    assert (pan.slot, pan.offsetDeg, pan.sign) == (slot_index(matrix, "fx-swap", "tilt"), 10.0, 1.0)
    # The tilt channel reads the pan slot, with tiltOffset (−5) and invertTilt (on).
    assert (tilt.slot, tilt.offsetDeg, tilt.sign) == (
        slot_index(matrix, "fx-swap", "pan"),
        -5.0,
        -1.0,
    )


def test_mhx25_fine_bytes_are_not_adjacent(demo: CompiledShow) -> None:
    pan, tilt = channels_of(demo, "fx-mh1")[:2]
    assert (pan.addresses, tilt.addresses) == ((0, 2), (1, 3))


def test_invert_swaps_segment_values(matrix: CompiledShow) -> None:
    (dimmer,) = channels_of(matrix, "fx-diminv")
    assert dimmer.segments == (Segment(v0=1.0, v1=0.0, d0=0, d1=255),)


def test_mhx25_option_tables(demo: CompiledShow) -> None:
    by_attribute = {demo.slots.slots[c.slot].attribute.id: c for c in channels_of(demo, "fx-mh1")}
    # The first "open" range wins; shake and spin ranges are not options.
    assert [o.raw for o in by_attribute["gobo1"].options] == [3, 11, 19, 27, 35, 43, 51, 59]
    assert [o.raw for o in by_attribute["colorWheel"].options] == [2, 7, 12, 17, 22, 27, 32, 37, 42]
    closed, opened, strobe = by_attribute["shutter"].options
    assert (closed.raw, opened.raw) == (1, 5)
    assert strobe.param == (
        slot_index(demo, "fx-mh1", "strobeRate"),
        Segment(v0=0.0, v1=13.0, d0=8, d1=215),
    )
    rotation = by_attribute["gobo1Rotation"]
    assert rotation.segments == (
        Segment(v0=0.0, v1=0.0, d0=0, d1=0),
        Segment(v0=10.0, v1=360.0, d0=64, d1=147),
        Segment(v0=-10.0, v1=-360.0, d0=148, d1=231),
    )


def test_control_channels_are_not_compiled(demo: CompiledShow) -> None:
    offsets = [c.offset for c in channels_of(demo, "fx-mh1")]
    assert offsets == [0, 1, 4, 5, 6, 7, 8, 9]  # 10 and 11 are control channels


def test_overlap_the_earlier_fixture_loses_exactly_the_shared_bytes(matrix: CompiledShow) -> None:
    # fx-early at 41–43 and fx-late at 43–45 share channel 43 (address 42).
    assert [c.addresses for c in channels_of(matrix, "fx-early")] == [(40,), (41,), (None,)]
    assert [c.addresses for c in channels_of(matrix, "fx-late")] == [(42,), (43,), (44,)]


def test_written_addresses_are_unique(matrix: CompiledShow, demo: CompiledShow) -> None:
    for compiled in (matrix, demo):
        written = [
            (c.universe, address)
            for c in compiled.channels
            for address in c.addresses
            if address is not None
        ]
        assert len(written) == len(set(written))


def test_second_universe_rows(matrix: CompiledShow) -> None:
    assert {c.universe for c in channels_of(matrix, "fx-cmy")} == {1}
    assert [c.subtractive for c in channels_of(matrix, "fx-cmy")] == [False, True, True, True]


def test_records_are_frozen(appendix: CompiledShow) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        appendix.channels[0].sign = -1.0  # type: ignore[misc]
