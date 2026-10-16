"""The Phase 1 done criterion: logical values produce the DMX that the
manufacturers' charts give, for three real fixtures (``examples/real-fixtures.json``).

Patch: MH-X25 ``MH 1`` at 1 and ``MH 2`` (invertPan) at 13, ML-56 RGBW
``Wash 1`` at 25, COLORband PiX ``Bar 1`` at 29–64.

Every expected value is read off the chart (Stairville MH-X25 manual §7.6,
12-channel mode; Eurolite LED ML-56 RGBW manual, 4-channel mode; Chauvet DJ
COLORband PiX manual Rev. 6, 36-CH) and worked out by hand; the derivation
is in the comments. Options output the centre of their chart range.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from builders import DEMO, channels_at, compile_doc, frame, load_doc, nonzero
from busk.compiler.compile import CompiledShow
from busk.compiler.values import compile_values
from busk.model.validate import validate_show
from busk.persistence.values_file import load_values
from conftest import Convert

MH1 = range(1, 13)
MH2 = range(13, 25)


@pytest.fixture(scope="module")
def demo() -> CompiledShow:
    return compile_doc(load_doc(DEMO))


def mh1(demo: CompiledShow, convert: Convert, **values: Any) -> dict[int, int]:
    """MH 1's 12 channels for the given attribute values."""
    out = convert(demo, frame(demo, {("fx-mh1", name): v for name, v in values.items()}))
    return channels_at(out[0], MH1)


# ----------------------------------------------------------------- MH-X25


def test_mhx25_defaults(convert: Convert, demo: CompiledShow) -> None:
    assert mh1(demo, convert) == {
        1: 128,  # pan 0° = 32768 → coarse 128 (ch 1) …
        2: 128,  # … tilt 0° (ch 2)
        3: 0,  # pan fine (ch 3: the fine bytes are not adjacent)
        4: 0,  # tilt fine
        5: 0,  # pan/tilt speed 0 = fastest
        6: 2,  # colour wheel white: centre of 0–4
        7: 5,  # shutter OPEN: centre of 4–7 (DMX 0 would be blackout)
        8: 0,  # dimmer
        9: 3,  # gobo open: centre of 0–7
        10: 0,  # gobo rotation stopped at index 0°
        11: 0,  # special functions: untouched, defaultDmx 0 ("not in use")
        12: 0,  # built-in programmes: untouched, defaultDmx 0 ("not in use")
    }


def test_mhx25_position(convert: Convert, demo: CompiledShow) -> None:
    channels = mh1(demo, convert, pan=90, tilt=-45)
    # Pan 90° on 0–540°: (90 + 270) / 540 × 65535 = 43690 = 0xAAAA → 170 / 170.
    # Tilt −45° on 0–270°: (−45 + 135) / 270 × 65535 = 21845 = 0x5555 → 85 / 85.
    assert channels_at_keys(channels, [1, 3, 2, 4]) == {1: 170, 3: 170, 2: 85, 4: 85}


def test_mhx25_inverted_pan(convert: Convert, demo: CompiledShow) -> None:
    out = convert(demo, frame(demo, {("fx-mh2", "pan"): 90}))
    # −90° → 180 / 540 × 65535 = 21845 = 0x5555; MH 2 is at 13.
    assert channels_at(out[0], [13, 15]) == {13: 85, 15: 85}


COLOR_WHEEL = {
    "open": 2,  # 0–4 (the manual's 0–7 overlaps yellow; see the profile notes)
    "yellow": 7,  # 5–9
    "pink": 12,  # 10–14
    "green": 17,  # 15–19
    "peachblow": 22,  # 20–24
    "lightBlue": 27,  # 25–29
    "yellowGreen": 32,  # 30–34
    "red": 37,  # 35–39
    "darkBlue": 42,  # 40–44
}


@pytest.mark.parametrize(("slot", "dmx"), COLOR_WHEEL.items())
def test_mhx25_colour_wheel(convert: Convert, demo: CompiledShow, slot: str, dmx: int) -> None:
    assert mh1(demo, convert, colorWheel={"slot": slot})[6] == dmx


GOBO_WHEEL = {"open": 3, **{f"gobo{k}": 8 * (k - 1) + 3 for k in range(2, 9)}}  # 8–15 → 11 …


@pytest.mark.parametrize(("slot", "dmx"), GOBO_WHEEL.items())
def test_mhx25_gobo_wheel(convert: Convert, demo: CompiledShow, slot: str, dmx: int) -> None:
    assert mh1(demo, convert, gobo1={"slot": slot})[9] == dmx


@pytest.mark.parametrize(
    ("shutter", "rate", "dmx"),
    [
        ("closed", 0, 1),  # blackout: centre of 0–3
        ("open", 0, 5),  # the first "open" range (4–7) wins over 216–255
        ("strobe", 0, 8),  # 0…13 Hz across 8–215
        ("strobe", 13, 215),
        ("strobe", 6.5, 112),  # 8 + 0.5 × 207 = 111.5 → 112 (half to even)
        ("strobe", 5, 88),  # 8 + 5/13 × 207 = 87.6 → 88
        ("strobe", 30, 215),  # beyond the fixture's 13 Hz: clamped
    ],
)
def test_mhx25_shutter(
    convert: Convert, demo: CompiledShow, shutter: str, rate: float, dmx: int
) -> None:
    assert mh1(demo, convert, shutter={"slot": shutter}, strobeRate=rate)[7] == dmx


@pytest.mark.parametrize(("level", "dmx"), [(0, 0), (0.5, 128), (1, 255)])  # 127.5 → 128
def test_mhx25_dimmer(convert: Convert, demo: CompiledShow, level: float, dmx: int) -> None:
    assert mh1(demo, convert, intensity=level)[8] == dmx


@pytest.mark.parametrize(
    ("speed", "dmx"),
    [
        (0, 0),  # stopped: gobo index 0°
        (10, 64),  # CW 64–147 over 10–360 °/s (estimated speeds)
        (185, 106),  # 64 + 0.5 × 83 = 105.5 → 106
        (360, 147),
        (-10, 148),  # CCW 148–231 over −10…−360 °/s
        (-185, 190),  # 148 + 41.5 = 189.5 → 190
        (-360, 231),
        (4, 0),  # between stop and the slowest CW speed: the nearer (stop)
        (1000, 147),  # clamped to the fastest CW speed
    ],
)
def test_mhx25_gobo_rotation(convert: Convert, demo: CompiledShow, speed: float, dmx: int) -> None:
    assert mh1(demo, convert, gobo1Rotation=speed)[10] == dmx


def test_mhx25_position_speed(convert: Convert, demo: CompiledShow) -> None:
    assert mh1(demo, convert, positionSpeed=1)[5] == 255  # slowest


def test_mhx25_control_channels_are_untouched(convert: Convert, demo: CompiledShow) -> None:
    channels = mh1(demo, convert, intensity=1, pan=90, shutter={"slot": "strobe"}, strobeRate=13)
    assert channels_at_keys(channels, [11, 12]) == {11: 0, 12: 0}


# -------------------------------------------------------------------- ML-56


@pytest.mark.parametrize(
    ("intensity", "color", "dmx"),
    [
        # Intensity 0.8, {1, 0.5, 0}: W = min = 0; R = 0.8 → 204; G = 0.4 → 102.
        (0.8, {"r": 1, "g": 0.5, "b": 0}, {25: 204, 26: 102, 27: 0, 28: 0}),
        # White is made by the white LED alone: W = 1, R = G = B = 0.
        (1, {"r": 1, "g": 1, "b": 1}, {25: 0, 26: 0, 27: 0, 28: 255}),
        # A pastel: W = 0.5; R = 0.5 → 128 (127.5, half to even), G = B = 0.
        (1, {"r": 1, "g": 0.5, "b": 0.5}, {25: 128, 26: 0, 27: 0, 28: 128}),
        # Virtual intensity 0: every emitter off, whatever the colour.
        (0, {"r": 1, "g": 1, "b": 1}, {25: 0, 26: 0, 27: 0, 28: 0}),
    ],
)
def test_ml56_rgbw(
    convert: Convert,
    demo: CompiledShow,
    intensity: float,
    color: dict[str, float],
    dmx: dict[int, int],
) -> None:
    values = {("fx-wash1", "intensity"): intensity, ("fx-wash1", "color"): color}
    assert channels_at(convert(demo, frame(demo, values))[0], range(25, 29)) == dmx


# ----------------------------------------------------------- COLORband PiX


def test_pix_cells_are_independent(convert: Convert, demo: CompiledShow) -> None:
    values: dict[Any, Any] = {}
    for cell in range(12):
        values["fx-bar1", cell, "intensity"] = 1
        values["fx-bar1", cell, "color"] = (
            {"r": 1, "g": 0, "b": 0} if cell % 2 == 0 else {"r": 0, "g": 0, "b": 1}
        )
    out = convert(demo, frame(demo, values))
    # Cell k is at 29 + 3k (R, G, B): red cells light their R, blue cells their B.
    expected = {29 + 3 * k + (0 if k % 2 == 0 else 2): 255 for k in range(12)}
    assert {n: v for n, v in nonzero(out[0]).items() if n >= 29} == expected


def test_pix_cell_intensity_is_per_cell(convert: Convert, demo: CompiledShow) -> None:
    values: dict[Any, Any] = {
        ("fx-bar1", 3, "intensity"): 0.5,  # only cell 4 (index 3) is up
        ("fx-bar1", 3, "color"): {"r": 1, "g": 0.5, "b": 0.25},
    }
    out = convert(demo, frame(demo, values))
    # 0.5 → 127.5 → 128; 0.25 → 63.75 → 64; 0.125 → 31.875 → 32. Cell 4 is at 38–40.
    assert {n: v for n, v in nonzero(out[0]).items() if n >= 29} == {38: 128, 39: 64, 40: 32}


# ------------------------------------------------------ the demo values file


DEMO_GOLDEN = {
    # MH 1: pan 90 / tilt −45, red, gobo 3, open shutter, full dimmer.
    1: 170, 2: 85, 3: 170, 4: 85, 6: 37, 7: 5, 8: 255, 9: 19,
    # MH 2 (invertPan): pan 90 → 85/85, tilt 0 → 128/0, white wheel, strobe 5 Hz, full.
    13: 85, 14: 128, 15: 85, 18: 2, 19: 88, 20: 255, 21: 3,
    # Wash 1: intensity 0.8, {1, 0.5, 0}.
    25: 204, 26: 102,
    # Bar 1: cells alternating red and blue at full.
    29: 255, 34: 255, 35: 255, 40: 255, 41: 255, 46: 255,
    47: 255, 52: 255, 53: 255, 58: 255, 59: 255, 64: 255,
}  # fmt: skip


def test_demo_values_file(convert: Convert, demo: CompiledShow, values_path: Path) -> None:
    show, _ = validate_show(DEMO.read_bytes())
    assert show is not None
    entries, issues = load_values(values_path, show)
    assert entries is not None
    assert issues == []
    logical, issues = compile_values(demo, entries)
    assert logical is not None
    assert issues == []
    assert nonzero(convert(demo, logical)[0]) == DEMO_GOLDEN


def channels_at_keys(channels: dict[int, int], keys: list[int]) -> dict[int, int]:
    return {key: channels[key] for key in keys}
