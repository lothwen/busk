"""GDTF import (phase-7-plan §5.19, step 15).

The files are synthetic (:mod:`gdtf_builder`, from DIN SPEC 15800):

* ``value/bytes`` DMX values at 1, 2 and 3 bytes; CIE xyY → linear RGB at
  known points (D65 white, the sRGB primaries);
* a 16-bit spot that converts like ``generic-spot-16ch.json``;
* an RGBW par, a 4-cell bar from geometry references, wheels and prisms, the
  scalar attributes;
* what is reported and not imported: mode masters, a second DMX break,
  virtual channels, DMX profiles, relations and macros;
* what is refused: a ``DOCTYPE``, a 40 MB ``description.xml``, files that are
  not GDTF;
* the library loads ``.gdtf`` files; ``busk import gdtf``.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest

from builders import ROOT, compile_doc, fixture, frame, show
from busk.cli import main
from busk.importers import ImportFailed, ImportReport
from busk.importers.gdtf import dmx_value, import_gdtf, read_gdtf, xyy_to_linear_rgb
from busk.model.common import FixtureId, TargetRef
from busk.session.library import ProfileLibrary
from conftest import fast_convert
from gdtf_builder import (
    D65,
    SRGB_BLUE,
    SRGB_GREEN,
    SRGB_RED,
    TYPE_ID,
    archive,
    channel,
    channel_set,
    description,
    emitter,
    function,
    geometry,
    mode,
    reference,
    slot,
    wheel,
)
from test_ofl import COLOURS, _sample

Doc = dict[str, Any]
GENERIC_SPOT = ROOT / "src" / "busk" / "library" / "profiles" / "generic-spot-16ch.json"


def imported(*modes: Any, **extra: Any) -> ImportReport:
    return import_gdtf(description(*modes, **extra))


def channels_of(report: ImportReport, mode: int = 0) -> list[Doc]:
    return cast(list[Doc], report.profile["modes"][mode]["channels"])


def at(report: ImportReport, offset: int, mode: int = 0, element: int = 0) -> Doc:
    return next(
        c for c in channels_of(report, mode) if c["offset"] == offset and c["element"] == element
    )


def caps(report: ImportReport, offset: int, mode: int = 0) -> list[tuple[Any, ...]]:
    """``(kind, low, high, what)`` per capability; ``what`` the value range,
    the slot or the function (with its parameter range)."""
    out: list[tuple[Any, ...]] = []
    for cap in at(report, offset, mode)["capabilities"]:
        low, high = cap["dmx"]
        if cap["kind"] == "range":
            out.append(("range", low, high, tuple(round(v, 6) for v in cap["value"])))
        elif cap["kind"] == "slot":
            out.append(("slot", low, high, cap["slot"]))
        elif "param" in cap:
            out.append(("function", low, high, cap["fn"], tuple(cap["param"]["value"])))
        else:
            out.append(("function", low, high, cap["fn"]))
    return out


def noted(report: ImportReport, *words: str) -> bool:
    return any(all(w in note for w in words) for note in report.notes)


def dimmer(offset: str = "1") -> Any:
    """A dimmer channel: every busk mode needs an intensity."""
    return channel(offset, function("Dimmer"))


# ------------------------------------------------------------------ values


@pytest.mark.parametrize(
    ("text", "nbytes", "raw"),
    [
        ("0/1", 1, 0),
        ("255/1", 1, 255),
        ("255/1", 2, 0xFFFF),  # byte mirroring, the spec's example
        ("128/1", 2, 0x8080),
        ("255/1s", 2, 0xFF00),  # byte shifting, the spec's example
        ("128/1s", 2, 0x8000),
        ("1/1", 3, 0x010101),
        ("128/1s", 3, 0x800000),
        ("4660/2", 3, 0x123412),  # 0x1234 mirrored to 24 bits
        ("4660/2s", 3, 0x123400),
        ("32768/2", 1, 0x80),  # finer: its top bytes
        ("32768/2", 2, 0x8000),
        ("8388608/3", 2, 0x8000),
        ("16777215/3", 3, 0xFFFFFF),
        ("12", 1, 12),  # a bare number: the channel's resolution
    ],
)
def test_dmx_values_at_1_2_and_3_bytes(text: str, nbytes: int, raw: int) -> None:
    assert dmx_value(text, nbytes) == raw


@pytest.mark.parametrize("text", ["256/1", "65536/2", "x/1", "1/5", "-1/1", ""])
def test_bad_dmx_values(text: str) -> None:
    with pytest.raises(ValueError, match="DMX value"):
        dmx_value(text, 1)


@pytest.mark.parametrize(
    ("xy", "luminance", "rgb"),
    [
        ((0.3127, 0.3290), 1.0, (1, 1, 1)),  # D65 white
        ((0.64, 0.33), 0.2126, (1, 0, 0)),  # the sRGB primaries, at their luminance
        ((0.30, 0.60), 0.7152, (0, 1, 0)),
        ((0.15, 0.06), 0.0722, (0, 0, 1)),
    ],
)
def test_cie_xyy_to_linear_rgb_at_known_points(
    xy: tuple[float, float], luminance: float, rgb: tuple[float, ...]
) -> None:
    assert xyy_to_linear_rgb(*xy, luminance) == pytest.approx(rgb, abs=1e-3)


def test_emitters_are_calibrated_by_their_colour_not_their_brightness() -> None:
    report = imported(
        mode(
            "RGBW",
            *(
                channel(str(k + 1), function(f"ColorAdd_{c}", emitter=c))
                for k, c in enumerate("RGBW")
            ),
        ),
        emitters=(
            emitter("R", SRGB_RED),
            emitter("G", SRGB_GREEN),
            emitter("B", SRGB_BLUE),
            emitter("W", D65),
        ),
    )
    colours = {e["id"]: e["color"] for e in report.profile.get("emitters", [])}
    assert colours == {
        "red": {"r": 1.0, "g": 0.0, "b": 0.0},
        "green": {"r": 0.0, "g": 1.0, "b": 0.0},
        "blue": {"r": 0.0, "g": 0.0, "b": 1.0},
        "white": {"r": 1.0, "g": 1.0, "b": 1.0},
    }
    # A deep red LED lies outside sRGB: clipped, still pure red.
    deep = imported(
        mode(
            "RGB",
            *(
                channel(str(k + 1), function(f"ColorAdd_{c}", emitter=c))
                for k, c in enumerate("RGB")
            ),
        ),
        emitters=(emitter("R", "0.700,0.300,30"),),
    )
    assert deep.profile.get("emitters", [])[0]["color"] == {"r": 1.0, "g": 0.0, "b": 0.0}


# ------------------------------------------------------------------ the spot


def spot() -> bytes:
    """``generic-spot-16ch.json`` written as GDTF, 16-bit pan, tilt and dimmer."""
    gobo = function(
        "Gobo1",
        "0/1",
        (0, 1),
        channel_set("Open", "0/1", 1),
        channel_set("Breakup", "10/1", 2),
        channel_set("", "20/1"),
        wheel="Gobo1",
    )
    shutter = (
        function(
            "Shutter1", "0/1", (0, 1), channel_set("Closed", "0/1"), channel_set("Open", "8/1")
        ),
        function("Shutter1Strobe", "16/1", (1, 20)),
        function("Shutter1StrobeEffect", "132/1"),
    )
    return description(
        mode(
            "16ch",
            channel("1,2", function("Pan", "0/1", (-270, 270), default="32768/2"), geometry="Yoke"),
            channel(
                "3,4", function("Tilt", "0/1", (-135, 135), default="32768/2"), geometry="Head"
            ),
            *(
                channel(str(5 + k), function(f"ColorAdd_{c}", emitter=c))
                for k, c in enumerate("RGBW")
            ),
            channel("9,10", function("Dimmer")),
            channel("11", function("Zoom", "0/1", (12, 30), default="128/1")),
            channel("12", gobo),
            channel("13", *shutter),
            channel("16", function("Control1")),
        ),
        name="Spot",
        manufacturer="Generic",
        wheels=(wheel("Gobo1", slot("Open"), slot("Breakup")),),
        emitters=(
            emitter("R", SRGB_RED),
            emitter("G", SRGB_GREEN),
            emitter("B", SRGB_BLUE),
            emitter("W", D65),
        ),
        geometries=(
            geometry(
                "Geometry",
                "Base",
                geometry("Axis", "Yoke", geometry("Axis", "Head", geometry("Beam", "Beam"))),
            ),
        ),
    )


def test_a_16_bit_spot_converts_like_generic_spot_16ch() -> None:
    """Every logical value of every attribute both profiles define converts
    to the same DMX (as the TupperDMX check of the OFL import)."""
    hand = json.loads(GENERIC_SPOT.read_text())
    report = import_gdtf(spot())
    profile = cast(Doc, report.profile)
    (gdtf_mode,) = profile["modes"]
    assert gdtf_mode["footprint"] == hand["modes"][0]["footprint"] == 16
    a = fixture("a", 1, hand["id"], 1, mode_id=hand["modes"][0]["id"])
    b = {
        **fixture("b", 2, profile["id"], 101, mode_id=gdtf_mode["id"]),
        "profileRevision": profile["revision"],
    }
    compiled = compile_doc(show([hand, profile], [a, b]))
    compared = 0
    attributes = set()
    for found in compiled.slots.slots:
        if found.target["fixtureId"] != "a":
            continue
        attribute = found.attribute.id
        other = compiled.slots.find(TargetRef(fixtureId=FixtureId("b"), element=0), attribute)
        assert other is not None, attribute
        attributes.add(attribute)
        if found.attribute.kind == "discrete":
            values: list[Any] = [{"slot": o} for o in found.options]
            assert set(found.options) <= set(other.options), attribute
        elif found.attribute.kind == "color":
            values = COLOURS
        else:
            values = _sample(hand["modes"][0], 0, attribute)
        for shutter in ["strobe"] if attribute == "strobeRate" else [None]:
            for value in values:
                keys: dict[Any, Any] = {("a", attribute): value, ("b", attribute): value}
                if shutter is not None:
                    keys |= {
                        ("a", "shutter"): {"slot": shutter},
                        ("b", "shutter"): {"slot": shutter},
                    }
                out = fast_convert(compiled, frame(compiled, keys))[0]
                assert out[100:116].tolist() == out[:16].tolist(), (attribute, value)
                compared += 1
    assert attributes == {
        "pan",
        "tilt",
        "color",
        "intensity",
        "zoom",
        "gobo1",
        "shutter",
        "strobeRate",
    }
    assert compared > 100
    assert profile["physical"] == {
        "panRange": 540,
        "tiltRange": 270,
        "zoomRange": (12, 30),
        "maxStrobeHz": 20,
    }
    assert noted(report, "Control1: no busk attribute (Control1); held at DMX 0")


# ------------------------------------------------------------------ the par and the bar


def test_an_rgbw_par() -> None:
    report = imported(
        mode(
            "6ch",
            channel("1", function("Dimmer"), highlight="255/1"),
            *(
                channel(str(2 + k), function(f"ColorAdd_{c}", emitter=c))
                for k, c in enumerate("RGBW")
            ),
            channel(
                "6",
                function(
                    "Shutter1",
                    "0/1",
                    (0, 1),
                    channel_set("Closed", "0/1"),
                    channel_set("Open", "10/1"),
                ),
                function("Shutter1Strobe", "20/1", (1, 25)),
                function("Shutter1StrobePulse", "120/1", (0.5, 10)),
                function("Shutter1StrobeRandom", "200/1", (2, 15)),
                function("NoFeature", "250/1"),
                initial="Shutter1.Shutter1",
            ),
        ),
        name="Par RGBW",
        emitters=(
            emitter("R", SRGB_RED),
            emitter("G", SRGB_GREEN),
            emitter("B", SRGB_BLUE),
            emitter("W", D65),
        ),
    )
    first = report.profile["modes"][0]
    assert first["intensityStrategy"] == "dimmerChannel"
    assert [(c["attribute"], c.get("component")) for c in channels_of(report)] == [
        ("intensity", None),
        ("color", "red"),
        ("color", "green"),
        ("color", "blue"),
        ("color", "white"),
        ("shutter", None),
    ]
    assert at(report, 0)["highlightDmx"] == 255
    assert caps(report, 0) == [("range", 0, 255, (0, 1))]
    assert caps(report, 5) == [
        ("function", 0, 9, "closed"),
        ("function", 10, 19, "open"),
        ("function", 20, 119, "strobe", (1, 25)),
        ("function", 120, 199, "pulse", (0.5, 10)),
        ("function", 200, 249, "random", (2, 15)),
        ("function", 250, 255, "open"),  # NoFeature on a shutter: open
    ]
    assert report.profile["physical"]["maxStrobeHz"] == 25
    assert not report.notes


def bar() -> bytes:
    """Four RGB cells from geometry references, listed out of DMX order, and
    a control channel on the bar itself."""
    cell = geometry("Geometry", "Cell", geometry("Beam", "Pixel"))
    references = [reference(f"Cell {n}", "Cell", ("1", 1 + 3 * (n - 1))) for n in (2, 4, 1, 3)]
    return description(
        mode(
            "13ch",
            *(
                channel(str(k + 1), function(f"ColorAdd_{c}"), geometry="Pixel")
                for k, c in enumerate("RGB")
            ),
            channel("13", function("Effects1"), geometry="Bar"),
            geometry="Bar",
        ),
        name="Bar",
        type_id="0B5C2D7E-1111-4A2B-8C3D-445566778899",
        geometries=(geometry("Geometry", "Bar", *references), cell),
    )


def test_a_four_cell_bar_from_geometry_references() -> None:
    report = import_gdtf(bar())
    first = report.profile["modes"][0]
    assert [e["name"] for e in first["elements"]] == ["Cell 1", "Cell 2", "Cell 3", "Cell 4"]
    assert first["footprint"] == 13
    assert first["intensityStrategy"] == "virtual"
    assert [
        (c["offset"], c["element"], c["attribute"], c.get("component")) for c in first["channels"]
    ] == [
        (3 * e + k, e, "color", ("red", "green", "blue")[k]) for e in range(4) for k in range(3)
    ] + [(12, 0, "control", None)]
    assert noted(report, "Bar_Effects1: no busk attribute (Effects1)")
    profile = cast(Doc, report.profile)
    bar_fixture = {
        **fixture("bar", 1, profile["id"], 1, mode_id=first["id"]),
        "profileRevision": profile["revision"],
    }
    compiled = compile_doc(show([profile], [bar_fixture]))
    red = {"r": 1, "g": 0, "b": 0}
    out = fast_convert(
        compiled, frame(compiled, {("bar", 2, "color"): red, ("bar", 2, "intensity"): 1.0})
    )
    assert out[0][6:9].tolist() == [255, 0, 0]  # cell 3 only
    assert out[0][:6].tolist() == [0] * 6


# ------------------------------------------------------------------ attributes


def test_wheels_rotation_and_prisms() -> None:
    red_slot = "0.640000,0.330000,20"
    report = imported(
        mode(
            "5ch",
            dimmer(),
            channel(
                "2",
                function(
                    "Color1",
                    "0/1",
                    (0, 1),
                    channel_set("Open", "0/1", 1),
                    channel_set("Red", "16/1", 2),
                    wheel="Colours",
                ),
                function("Color1WheelSpin", "128/1"),
            ),
            channel(
                "3",
                function("Gobo1Pos", "0/1", (0, 360)),
                function("Gobo1PosRotate", "128/1", (0, 200)),
                function("Gobo1PosRotate", "192/1", (0, -200)),
            ),
            channel(
                "4",
                function("NoFeature", "0/1"),
                function("Prism1", "8/1", (0, 1), channel_set("Prism", "8/1", 2), wheel="Prisms"),
            ),
            channel("5", function("Prism1PosRotate", "0/1", (-90, 90))),
        ),
        wheels=(
            wheel("Colours", slot("Open", D65), slot("Red", red_slot)),
            wheel("Prisms", slot("Open"), slot("3 facets", facets=3)),
        ),
    )
    wheels = {w["id"]: w for w in report.profile["wheels"]}
    assert wheels["colours"]["kind"] == "color"
    assert [(s["id"], s.get("color")) for s in wheels["colours"]["slots"]] == [
        ("open", {"r": 1.0, "g": 1.0, "b": 1.0}),
        ("red", {"r": 1.0, "g": 0.0, "b": 0.0}),
    ]
    assert [(s["id"], s.get("facets")) for s in wheels["prisms"]["slots"]] == [
        ("off", None),
        ("prism3", 3),
    ]
    assert at(report, 1)["attribute"] == "colorWheel"
    assert caps(report, 1) == [
        ("slot", 0, 15, "open"),
        ("slot", 16, 127, "red"),
        ("function", 128, 255, "color1WheelSpin"),
    ]
    assert at(report, 2)["attribute"] == "gobo1Rotation"
    assert caps(report, 2) == [
        ("range", 0, 0, (0, 0)),
        ("function", 1, 127, "index"),  # the index: a dead band
        ("range", 128, 191, (0, 200)),
        ("range", 192, 255, (0, -200)),
    ]
    assert at(report, 3)["attribute"] == "prism"
    assert caps(report, 3) == [("slot", 0, 7, "off"), ("slot", 8, 255, "prism3")]
    assert caps(report, 4) == [("range", 0, 255, (-90, 90))]
    assert at(report, 4)["attribute"] == "prismRotation"


def test_pan_tilt_zoom_focus_iris_frost_cto_and_speed() -> None:
    report = imported(
        mode(
            "9ch",
            channel("1", function("Pan", "0/1", (0, 540))),
            channel("2", function("Tilt", "0/1", (-135, 135))),
            dimmer("3"),
            channel("4", function("Zoom", "0/1", (40, 8))),
            channel("5", function("Focus1", "0/1", (0, 1))),
            channel("6", function("Iris", "0/1", (100, 0))),
            channel("7", function("Frost1", "0/1", (0, 1))),
            channel("8", function("CTO", "0/1", (6500, 3200))),
            channel("9", function("MSpeed", "0/1", (0.1, 20))),
        ),
    )
    attributes = [c["attribute"] for c in channels_of(report)]
    assert attributes == [
        "pan",
        "tilt",
        "intensity",
        "zoom",
        "focus",
        "iris",
        "frost",
        "cto",
        "positionSpeed",
    ]
    assert caps(report, 0) == [("range", 0, 255, (-270, 270))]  # centred on its travel
    assert noted(report, "pan 0…540° centred on its travel, ±270°")
    assert caps(report, 3) == [("range", 0, 255, (40, 8))]
    assert caps(report, 5) == [("range", 0, 255, (1, 0))]  # 100…0 scaled to 0…1
    assert noted(report, "Beam_Iris: physical 0…100 taken as 0…1")
    assert caps(report, 7) == [("range", 0, 255, (0, 1))]  # kelvin
    assert caps(report, 8) == [("range", 0, 255, (0, 1))]  # MSpeed: a time, fast first
    assert report.profile["physical"] == {"panRange": 540, "tiltRange": 270, "zoomRange": (8, 40)}


def test_colour_systems() -> None:
    cmy = imported(
        mode(
            "CMY",
            dimmer(),
            *(channel(str(2 + k), function(f"ColorSub_{c}")) for k, c in enumerate("CMY")),
        )
    )
    assert [c.get("component") for c in channels_of(cmy)[1:]] == [
        "cyanFlag",
        "magentaFlag",
        "yellowFlag",
    ]
    rgb = imported(
        mode(
            "RGBA",
            *(
                channel(str(1 + k), function(f"ColorRGB_{c}"))
                for k, c in enumerate(("Red", "Green", "Blue"))
            ),
            channel("4", function("ColorAdd_RY")),
            channel("5", function("ColorAdd_WW")),
        )
    )
    assert [c.get("component") for c in channels_of(rgb)] == [
        "red",
        "green",
        "blue",
        "amber",
        "warmWhite",
    ]
    assert noted(rgb, "ColorAdd_WW: a custom emitter with an estimated colour")
    alone = imported(
        mode(
            "RG",
            dimmer(),
            channel("2", function("ColorAdd_R")),
            channel("3", function("ColorAdd_G")),
        )
    )
    assert [c["attribute"] for c in channels_of(alone)] == ["intensity", "control", "control"]
    assert noted(alone, "busk colour mixes red, green and blue")


def test_unmapped_channels_are_control_held_at_their_default() -> None:
    report = imported(
        mode(
            "3ch",
            dimmer(),
            channel(
                "2",
                function("Control1", "0/1", default="12/1"),
                function("FixtureGlobalReset", "200/1"),
            ),
            channel("3", function("Dimmer", "0/1")),
        ),  # a second dimmer
    )
    control = at(report, 1)
    assert control["attribute"] == "control"
    assert control["defaultDmx"] == 12
    assert caps(report, 1) == [
        ("function", 0, 199, "control1"),
        ("function", 200, 255, "fixtureGlobalReset"),
    ]
    assert noted(
        report, "Beam_Control1: no busk attribute (Control1, FixtureGlobalReset); held at DMX 12"
    )
    assert at(report, 2)["attribute"] == "control"
    assert noted(report, "a second intensity channel; held as control")


def test_fine_bytes_wherever_the_mode_puts_them_and_defaults() -> None:
    report = imported(
        mode(
            "3ch",
            channel("1,3", function("Dimmer", default="32768/2")),
            channel("2", function("Pan", "0/1", (-270, 270))),
        ),
    )
    intensity = at(report, 0)
    assert (intensity["bytes"], intensity["fineOffsets"]) == (2, [2])
    assert intensity["defaultDmx"] == 32768
    assert caps(report, 0) == [("range", 0, 65535, (0, 1))]


def test_a_gdtf_1_0_channel_default_wins() -> None:
    node = channel("1", function("Dimmer", default="0/1"))
    node.set("Default", "255/1")
    report = imported(mode("1ch", node))
    assert at(report, 0)["defaultDmx"] == 255


# ------------------------------------------------------------------ reported, not imported


def test_mode_masters_breaks_virtual_channels_profiles_relations_and_macros() -> None:
    report = imported(
        mode(
            "odd",
            dimmer(),
            channel(
                "2",
                function("Gobo1", mode_master="Beam_Control1"),
                function("Gobo2", "0/1", mode_master="Beam_Control1"),
            ),
            channel(
                "3",
                function("Zoom", "0/1", (10, 30)),
                function("Focus1", "128/1", mode_master="Beam_Control1"),
            ),
            channel("1", function("Iris"), dmx_break="2"),
            channel(None, function("Frost1")),
            channel("4", function("Frost1", dmx_profile="Curve 1")),
            relations=True,
            macros=True,
        ),
    )
    channels = channels_of(report)
    assert [(c["offset"], c["attribute"]) for c in channels] == [
        (0, "intensity"),
        (1, "control"),
        (2, "zoom"),
        (3, "frost"),
    ]
    assert caps(report, 1) == [("function", 0, 255, "modeDependent")]
    assert caps(report, 2) == [("range", 0, 255, (10, 30))]  # the mastered function dropped
    assert report.profile["modes"][0]["footprint"] == 4
    for words in (
        ("Beam_Gobo1: 2 channel function(s) depend on a mode master; not imported",),
        ("Beam_Zoom: 1 channel function(s) depend on a mode master",),
        ("Beam_Iris: on DMX break 2; busk imports only the first break (1)",),
        ("Beam_Frost1: a virtual channel (no DMX offset); not imported",),
        ("Beam_Frost1: DMX profile 'Curve 1' imported as linear",),
        ("mode 'odd': its relations are not imported",),
        ("mode 'odd': its macros are not imported",),
    ):
        assert noted(report, *words), words


def test_a_mode_that_cannot_be_imported_is_skipped_and_reported() -> None:
    report = imported(mode("bad", channel("1", function("Dimmer", "x/1"))), mode("good", dimmer()))
    assert [m["name"] for m in report.profile["modes"]] == ["good"]
    assert noted(report, "mode 'bad' skipped: Beam_Dimmer: not a GDTF DMX value: 'x/1'")
    with pytest.raises(ImportFailed, match="no mode could be imported"):
        imported(mode("bad", channel("1", function("Dimmer", "x/1"))))


# ------------------------------------------------------------------ refused


def test_a_doctype_is_refused(tmp_path: Path) -> None:
    bomb = (
        b'<?xml version="1.0"?>\n<!DOCTYPE GDTF [<!ENTITY a "aaaaaaaaaa">'
        b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>\n<GDTF>&b;</GDTF>'
    )
    with pytest.raises(ImportFailed, match="DOCTYPE"):
        import_gdtf(bomb)
    with pytest.raises(ImportFailed, match="DOCTYPE"):
        read_gdtf(archive(tmp_path / "bomb.gdtf", bomb))


def test_a_40_mb_description_is_refused(tmp_path: Path) -> None:
    big = description(mode("1ch", dimmer())).replace(b"<GDTF", b" " * (40 << 20) + b"<GDTF", 1)
    path = archive(tmp_path / "big.gdtf", big)
    assert path.stat().st_size < 1 << 20  # small on disk: the cap is on what it inflates to
    with pytest.raises(ImportFailed, match="larger than 32 MB"):
        read_gdtf(path)


def test_files_that_are_not_gdtf(tmp_path: Path) -> None:
    (tmp_path / "text.gdtf").write_text("hello")
    with pytest.raises(ImportFailed, match="not a GDTF file"):
        read_gdtf(tmp_path / "text.gdtf")
    with pytest.raises(ImportFailed, match=r"no description\.xml"):
        read_gdtf(archive(tmp_path / "other.gdtf", b"<GDTF/>", member="readme.xml"))
    with pytest.raises(ImportFailed, match="not well-formed"):
        import_gdtf(b"<GDTF>")
    with pytest.raises(ImportFailed, match="no GDTF/FixtureType"):
        import_gdtf(b"<Other><FixtureType/></Other>")
    with pytest.raises(ImportFailed, match="no FixtureTypeID"):
        import_gdtf(description(mode("1ch", dimmer()), type_id=""))
    with pytest.raises(ImportFailed, match="not a GDTF file"):
        read_gdtf(tmp_path / "missing.gdtf")


# ------------------------------------------------------------------ identity, library, CLI


def test_id_name_and_revision() -> None:
    data = description(
        mode("1ch", dimmer()), name="Wash", revisions=("2023-01-01T00:00:00", "2024-05-06T07:08:09")
    )
    profile = import_gdtf(data).profile
    assert profile["id"] == f"gdtf-{TYPE_ID.lower()}"
    assert (profile["name"], profile["manufacturer"], profile["model"]) == (
        "Acme Wash",
        "Acme",
        "Wash",
    )
    assert profile["source"] == "gdtf"
    assert profile["revision"].startswith("2024-05-06-")
    edited = import_gdtf(data.replace(b'Name="Wash"', b'Name="Wash2"', 1)).profile
    assert edited["revision"] != profile["revision"]  # an edited file is a new revision
    assert import_gdtf(data, manufacturer="Other").profile["name"] == "Other Wash"
    assert [
        m["id"]
        for m in import_gdtf(description(mode("A", dimmer()), mode("A", dimmer()))).profile["modes"]
    ] == ["mode-a", "mode-a2"]


def test_the_library_loads_gdtf_files(tmp_path: Path) -> None:
    archive(tmp_path / "spot.gdtf", spot())
    archive(tmp_path / "broken.gdtf", b"<GDTF/>")
    library = ProfileLibrary([tmp_path], builtin=False)
    assert [p["name"] for p in library] == ["Generic Spot"]
    assert any("broken.gdtf" in p and "no GDTF/FixtureType" in p for p in library.problems)
    assert any("spot.gdtf: Beam_Control1: no busk attribute" in p for p in library.problems)


def test_busk_import_gdtf_writes_profiles_the_library_loads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = [
        str(archive(tmp_path / "spot.gdtf", spot())),
        str(archive(tmp_path / "bar.gdtf", bar())),
    ]
    out = tmp_path / "profiles"
    assert main(["import", "gdtf", *files, "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "'Generic Spot' (modes 16ch)" in printed
    assert "1 note (--report)" in printed
    library = ProfileLibrary([out], builtin=False)
    assert not library.problems
    assert sorted(p["name"] for p in library) == ["Acme Bar", "Generic Spot"]
    assert (
        main(["import", "gdtf", files[0], "--out", str(out), "--report", "--manufacturer", "Mine"])
        == 0
    )
    printed = capsys.readouterr().out
    assert "'Mine Spot'" in printed
    assert "  Beam_Control1: no busk attribute (Control1); held at DMX 0" in printed
    with zipfile.ZipFile(tmp_path / "bad.gdtf", "w") as bad:
        bad.writestr("description.xml", "<GDTF>")
    assert main(["import", "gdtf", str(tmp_path / "bad.gdtf"), "--out", str(out)]) == 1
    assert "bad.gdtf" in capsys.readouterr().err
