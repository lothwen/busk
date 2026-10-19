"""Open Fixture Library import (phase-7-plan §5.18, step 14).

* One case per row of §5.18's capability table, then the channel rules
  (fine aliases, value resolution, percentages, ``null`` entries, matrix
  inserts, switching channels) and the profile's identity.
* **The TupperDMX check**: the user's five OFL files
  (``tests/fixtures/ofl/tupperdmx``) against their hand transcriptions
  (``examples/tupperdmx/profiles``): every logical value of every attribute
  both define converts to the same DMX, except the smoke machine's dead band.
* ``examples/tupperdmx/build-ofl.busk`` builds the same show on imported
  profiles; the library imports OFL files on load; ``busk import ofl``.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from builders import ROOT, compile_doc, fixture, frame, show, show_of
from busk.cli import main
from busk.compiler.compile import compile_show
from busk.console.console import Console
from busk.engine.clock import FakeClock
from busk.engine.loop import Engine
from busk.importers import ImportFailed, ImportReport
from busk.importers.ofl import import_ofl, read_ofl
from busk.model.common import FixtureId, TargetRef
from busk.model.validate import validate_show
from busk.persistence.show_file import new_show
from busk.runner import OfflineShow
from busk.session.ids import CounterIds
from busk.session.library import ProfileLibrary
from busk.session.session import Session
from conftest import fast_convert
from harness import Harness, fader

OFL = Path(__file__).parent / "fixtures" / "ofl" / "tupperdmx"
TRANSCRIBED = ROOT / "examples" / "tupperdmx" / "profiles"
TUPPER = [
    ("blinder", "tupperdmx-blinder"),
    ("ledbar", "tupperdmx-ledbar"),
    ("moving-head", "tupperdmx-moving-head"),
    ("par-rgbw", "tupperdmx-par-rgbw"),
    ("smoke-machine", "tupperdmx-smoke-machine"),
]

type Doc = dict[str, Any]


def ofl(channels: Doc, modes: list[Doc] | None = None, **extra: Any) -> Doc:
    """A minimal OFL fixture; its one mode lists every channel unless given."""
    return {
        "name": "Test",
        "meta": {"lastModifyDate": "2026-01-02"},
        "availableChannels": channels,
        "modes": modes or [{"name": "All", "channels": list(channels)}],
        **extra,
    }


def imported(
    channels: Doc, modes: list[Doc] | None = None, *, lamp: bool = False, **extra: Any
) -> ImportReport:
    """Import :func:`ofl`'s fixture. ``lamp`` adds an intensity channel at the
    end of every mode: busk needs intensity or colour in a mode, and many
    cases test neither."""
    data = ofl(channels, modes, **extra)
    if lamp:
        data["availableChannels"]["Lamp"] = {"capability": {"type": "Intensity"}}
        for mode in data["modes"]:
            mode["channels"].append("Lamp")
    return import_ofl(data, manufacturer="Test", key="test")


def lamped(channels: Doc, modes: list[Doc] | None = None, **extra: Any) -> ImportReport:
    """:func:`imported` with ``lamp``: the case's channels come first."""
    return imported(channels, modes, lamp=True, **extra)


def one(capability: Doc, **channel: Any) -> Doc:
    return {"capability": capability, **channel}


def many(*capabilities: tuple[int, int, Doc], **channel: Any) -> Doc:
    return {
        "capabilities": [{"dmxRange": [lo, hi], **cap} for lo, hi, cap in capabilities],
        **channel,
    }


def channels_of(report: ImportReport, mode: int = 0) -> list[Doc]:
    return cast(list[Doc], report.profile["modes"][mode]["channels"])


def at(report: ImportReport, offset: int, mode: int = 0) -> Doc:
    return next(c for c in channels_of(report, mode) if c["offset"] == offset)


def caps(report: ImportReport, offset: int, mode: int = 0) -> list[tuple[Any, ...]]:
    """A channel's capabilities as tuples: ``(kind, dmx, value | slot | fn, param)``."""
    out: list[tuple[Any, ...]] = []
    for cap in at(report, offset, mode)["capabilities"]:
        dmx = tuple(cap["dmx"])
        if cap["kind"] == "range":
            out.append(("range", dmx, tuple(cap["value"])))
        elif cap["kind"] == "slot":
            out.append(("slot", dmx, cap["slot"]))
        else:
            param = cap.get("param")
            out.append(("fn", dmx, cap["fn"], None if param is None else tuple(param["value"])))
    return out


def noted(report: ImportReport, *words: str) -> bool:
    return any(all(word in note for word in words) for note in report.notes)


# ------------------------------------------------------------------ the table


def test_intensity_is_a_range_with_brightness_or_0_to_1() -> None:
    report = imported({
        "Dimmer": one({"type": "Intensity"}),
        "Dimmer 2": one({"type": "Intensity", "brightnessStart": "10%", "brightnessEnd": "off"}),
    }, [{"name": "1", "channels": ["Dimmer"]},
        {"name": "2", "channels": ["Dimmer 2"]}])  # fmt: skip
    assert at(report, 0)["attribute"] == "intensity"
    assert caps(report, 0) == [("range", (0, 255), (0.0, 1.0))]
    assert caps(report, 0, mode=1) == [("range", (0, 255), (0.1, 0.0))]
    assert report.profile["modes"][0]["intensityStrategy"] == "dimmerChannel"


def test_colour_intensity_is_a_component_and_odd_colours_are_custom_emitters() -> None:
    colours = ["Red", "Green", "Blue", "White", "Amber", "UV", "Lime", "Magenta", "Warm White"]
    report = imported({c: one({"type": "ColorIntensity", "color": c}) for c in colours})
    components = [c.get("component") for c in channels_of(report)]
    assert components == [
        "red", "green", "blue", "white", "amber", "uv", "lime", "magenta", "warmWhite",
    ]  # fmt: skip
    assert {c["attribute"] for c in channels_of(report)} == {"color"}
    assert [e["id"] for e in report.profile["emitters"]] == ["magenta", "warmWhite"]
    assert noted(report, "Magenta", "estimated colour")
    assert report.profile["modes"][0]["intensityStrategy"] == "virtual"


def test_a_white_only_mode_makes_each_die_an_intensity_element() -> None:
    report = imported({
        "Master": one({"type": "Intensity"}),
        "Warm": one({"type": "ColorIntensity", "color": "Warm White"}, name="Warm die"),
        "Cold": one({"type": "ColorIntensity", "color": "Cold White"}, name="Cold die"),
        "Strobe": many((0, 9, {"type": "ShutterStrobe", "shutterEffect": "Open"}),
                       (10, 255, {"type": "ShutterStrobe", "shutterEffect": "Strobe",
                                  "speedStart": "1Hz", "speedEnd": "10Hz"})),
    })  # fmt: skip
    mode = report.profile["modes"][0]
    assert [e["name"] for e in mode["elements"]] == ["Warm die", "Cold die"]
    master, warm, cold, strobe = channels_of(report)
    assert (master["attribute"], master["defaultDmx"]) == ("control", 255)
    assert (warm["attribute"], warm["element"]) == ("intensity", 0)
    assert (cold["attribute"], cold["element"]) == ("intensity", 1)
    assert (strobe["attribute"], strobe["element"]) == ("shutter", 0)
    assert "emitters" not in report.profile
    assert noted(report, "Master", "held at full")


def test_cyan_magenta_and_yellow_without_rgb_are_subtractive_flags() -> None:
    report = imported({
        "Dimmer": one({"type": "Intensity"}),
        **{c: one({"type": "ColorIntensity", "color": c}) for c in ("Cyan", "Magenta", "Yellow")},
    })  # fmt: skip
    assert [c.get("component") for c in channels_of(report)[1:]] == [
        "cyanFlag", "magentaFlag", "yellowFlag",
    ]  # fmt: skip


def test_colour_channels_without_every_primary_are_held_as_control() -> None:
    report = imported({
        "Dimmer": one({"type": "Intensity"}),
        "Red": one({"type": "ColorIntensity", "color": "Red"}),
        "Green": one({"type": "ColorIntensity", "color": "Green"}),
    })  # fmt: skip
    assert [c["attribute"] for c in channels_of(report)] == ["intensity", "control", "control"]
    assert noted(report, "Red", "red, green and blue")


def test_shutter_strobe_gives_shutter_functions_and_strobe_rates() -> None:
    report = lamped({"Shutter": many(
        (0, 9, {"type": "ShutterStrobe", "shutterEffect": "Closed"}),
        (10, 19, {"type": "ShutterStrobe", "shutterEffect": "Open"}),
        (20, 99, {"type": "ShutterStrobe", "shutterEffect": "Strobe",
                  "speedStart": "1Hz", "speedEnd": "25Hz"}),
        (100, 149, {"type": "ShutterStrobe", "shutterEffect": "Pulse",
                    "speedStart": "slow", "speedEnd": "fast"}),
        (150, 199, {"type": "ShutterStrobe", "shutterEffect": "RampUp"}),
        (200, 249, {"type": "ShutterStrobe", "shutterEffect": "Strobe", "randomTiming": True,
                    "speedStart": "60bpm", "speedEnd": "600bpm"}),
        (250, 255, {"type": "ShutterStrobe", "shutterEffect": "Lightning"}),
    )})  # fmt: skip
    assert caps(report, 0) == [
        ("fn", (0, 9), "closed", None),
        ("fn", (10, 19), "open", None),
        ("fn", (20, 99), "strobe", (1.0, 25.0)),
        ("fn", (100, 149), "pulse", (1.0, 20.0)),
        ("fn", (150, 199), "rampUp", None),
        ("fn", (200, 249), "random", (1.0, 10.0)),
        ("fn", (250, 255), "lightning", None),
    ]
    assert report.profile["physical"]["maxStrobeHz"] == 25.0
    assert noted(report, "Shutter", "1–20 Hz", "estimate")


def test_strobe_speed_is_strobe_rate() -> None:
    report = lamped(
        {
            "Speed": one({"type": "StrobeSpeed", "speedStart": "0Hz", "speedEnd": "30Hz"}),
        }
    )
    assert at(report, 0)["attribute"] == "strobeRate"
    assert caps(report, 0) == [("range", (0, 255), (0.0, 30.0))]


def test_pan_and_tilt_are_centred_on_their_travel() -> None:
    report = lamped({
        "Pan": one({"type": "Pan", "angleStart": "0deg", "angleEnd": "630deg"}),
        "Tilt": one({"type": "Tilt", "angleStart": "-135deg", "angleEnd": "135deg"}),
        "Odd": one({"type": "Pan", "angleStart": "0%", "angleEnd": "100%"}),
    })  # fmt: skip
    assert caps(report, 0) == [("range", (0, 255), (-315.0, 315.0))]
    assert caps(report, 1) == [("range", (0, 255), (-135.0, 135.0))]
    assert at(report, 2)["attribute"] == "control"  # no degrees: no travel to centre
    physical = report.profile["physical"]
    assert (physical["panRange"], physical["tiltRange"]) == (630.0, 270.0)


def test_pan_tilt_speed_is_position_speed_fast_0_slow_1() -> None:
    report = lamped({"Speed": many(
        (0, 0, {"type": "PanTiltSpeed", "speed": "fast"}),
        (1, 200, {"type": "PanTiltSpeed", "speedStart": "fast", "speedEnd": "slow"}),
        (201, 255, {"type": "PanTiltSpeed", "speedStart": "100%", "speedEnd": "50%"}),
    )})  # fmt: skip
    assert at(report, 0)["attribute"] == "positionSpeed"
    assert caps(report, 0) == [
        ("range", (0, 0), (0.0, 0.0)),
        ("range", (1, 200), (0.0, 1.0)),
        ("range", (201, 255), (0.0, 0.5)),
    ]


WHEELS = {
    "Color Wheel": {"slots": [
        {"type": "Open"},
        {"type": "Color", "name": "Deep Red", "colors": ["#ff0000"]},
        {"type": "Color", "name": "Split", "colors": ["#00ff00", "#0000ff"]},
    ]},
    "Gobo Wheel": {"slots": [{"type": "Open"}, {"type": "Gobo", "name": "Breakup"},
                             {"type": "Closed"}]},
    "Gobo Wheel 2": {"slots": [{"type": "Open"}, {"type": "Gobo"}]},
}  # fmt: skip


def test_wheel_slots_choose_the_wheel_attribute_and_slot_ids() -> None:
    report = lamped({
        "Color Wheel": many((0, 9, {"type": "WheelSlot", "slotNumber": 1}),
                            (10, 19, {"type": "WheelSlot", "slotNumber": 2}),
                            (20, 29, {"type": "WheelSlot", "slotNumber": 1.5}),
                            (30, 255, {"type": "WheelSlot", "slotNumber": 3})),
        "Gobo Wheel": many((0, 63, {"type": "WheelSlot", "slotNumber": 1}),
                           (64, 127, {"type": "WheelSlot", "slotNumber": 2}),
                           (128, 255, {"type": "WheelSlot", "slotNumber": 3})),
        "Gobo Wheel 2": many((0, 127, {"type": "WheelSlot", "slotNumber": 1}),
                             (128, 255, {"type": "WheelSlot", "slotNumber": 2})),
    }, wheels=WHEELS)  # fmt: skip
    assert [c["attribute"] for c in channels_of(report)[:-1]] == ["colorWheel", "gobo1", "gobo2"]
    assert caps(report, 0) == [
        ("slot", (0, 9), "open"),
        ("slot", (10, 19), "deepRed"),
        ("fn", (20, 29), "wheelSlot", None),  # a split slot: never output
        ("slot", (30, 255), "split"),
    ]
    assert caps(report, 1) == [
        ("slot", (0, 63), "open"),
        ("slot", (64, 127), "breakup"),
        ("slot", (128, 255), "closed"),
    ]
    assert caps(report, 2) == [("slot", (0, 127), "open"), ("slot", (128, 255), "gobo2")]
    wheels = {w["id"]: w for w in report.profile["wheels"]}
    assert list(wheels) == ["color1", "gobo1", "gobo2"]
    colours = {s["id"]: s.get("color") for s in wheels["color1"]["slots"]}
    assert colours["deepRed"] == {"r": 1.0, "g": 0.0, "b": 0.0}
    assert colours["split"] == {"r": 0.0, "g": 0.5, "b": 0.5}  # linear RGB, averaged


def test_wheel_rotation_speeds_are_degrees_per_second_and_angles_are_stopped() -> None:
    report = lamped({
        "Gobo Wheel": one({"type": "WheelSlot", "slotNumber": 1}),
        "Gobo Rotation": many(*[(lo, hi, {"type": "WheelSlotRotation", "wheel": "Gobo Wheel",
                                          **cap}) for lo, hi, cap in (
            (0, 63, {"angleStart": "0deg", "angleEnd": "360deg"}),
            (64, 127, {"speedStart": "slow CW", "speedEnd": "fast CW"}),
            (128, 191, {"speedStart": "fast CCW", "speedEnd": "slow CCW"}),
            (192, 255, {"speedStart": "1rpm", "speedEnd": "60rpm"}),
        )]),
    }, wheels=WHEELS)  # fmt: skip
    rotation = at(report, 1)
    assert rotation["attribute"] == "gobo1Rotation"
    assert caps(report, 1) == [
        ("range", (0, 0), (0.0, 0.0)),  # the angle range's first value: stopped
        ("fn", (1, 63), "index", None),
        ("range", (64, 127), (10.0, 360.0)),
        ("range", (128, 191), (-360.0, -10.0)),
        ("range", (192, 255), (6.0, 360.0)),
    ]
    assert noted(report, "Gobo Rotation", "10–360 °/s", "estimate")


def test_wheel_rotation_on_the_wheel_channel_is_never_output() -> None:
    report = lamped({"Gobo Wheel": many(
        (0, 63, {"type": "WheelSlot", "slotNumber": 1}),
        (64, 127, {"type": "WheelSlot", "slotNumber": 2}),
        (128, 191, {"type": "WheelShake", "slotNumberStart": 1, "slotNumberEnd": 2}),
        (192, 255, {"type": "WheelRotation", "speedStart": "slow CW", "speedEnd": "fast CW"}),
    )}, wheels=WHEELS)  # fmt: skip
    assert caps(report, 0) == [
        ("slot", (0, 63), "open"),
        ("slot", (64, 127), "breakup"),
        ("fn", (128, 191), "wheelShake", None),
        ("fn", (192, 255), "wheelRotation", None),
    ]


def test_whole_wheel_rotation_is_never_output() -> None:
    """``WheelRotation`` spins the whole wheel, not the gobo in its slot, as
    GDTF's ``Gobo(n)WheelSpin``: no attribute, on its own channel or on a
    gobo rotation channel."""
    spin = {"type": "WheelRotation", "wheel": "Gobo Wheel"}
    report = lamped({
        "Gobo Wheel": one({"type": "WheelSlot", "slotNumber": 1}),
        "Wheel Spin": one({**spin, "speedStart": "slow CW", "speedEnd": "fast CW"}),
        "Gobo Rotation": many(
            (0, 127, {"type": "WheelSlotRotation", "wheel": "Gobo Wheel",
                      "speedStart": "1rpm", "speedEnd": "60rpm"}),
            (128, 191, {**spin, "angleStart": "0deg", "angleEnd": "360deg"}),
            (192, 255, {**spin, "speedStart": "1rpm", "speedEnd": "60rpm"})),
    }, wheels=WHEELS)  # fmt: skip
    assert at(report, 1)["attribute"] == "control"
    assert noted(report, "Wheel Spin", "no busk attribute (WheelRotation)")
    assert at(report, 2)["attribute"] == "gobo1Rotation"
    assert caps(report, 2) == [
        ("range", (0, 127), (6.0, 360.0)),
        ("fn", (128, 191), "wheelRotation", None),
        ("fn", (192, 255), "wheelRotation", None),
    ]


def test_prism_slots_come_from_the_prism_wheel_or_a_new_one() -> None:
    wheels = {"Prism": {"slots": [{"type": "Open"}, {"type": "Prism", "facets": 5}]}}
    report = lamped({
        "Prism": many((0, 63, {"type": "NoFunction"}), (64, 255, {"type": "Prism"})),
        "Prism Rotation": many(
            (0, 127, {"type": "PrismRotation", "angleStart": "0deg", "angleEnd": "360deg"}),
            (128, 255, {"type": "PrismRotation", "speedStart": "0rpm", "speedEnd": "30rpm"})),
    }, wheels=wheels)  # fmt: skip
    assert caps(report, 0) == [("slot", (0, 63), "off"), ("slot", (64, 255), "prism5")]
    assert at(report, 1)["attribute"] == "prismRotation"
    assert caps(report, 1)[-1] == ("range", (128, 255), (0.0, 180.0))
    alone = lamped({"Prism": many((0, 9, {"type": "NoFunction"}), (10, 255, {"type": "Prism"}))})
    assert caps(alone, 0) == [("slot", (0, 9), "off"), ("slot", (10, 255), "prism")]
    assert alone.profile["wheels"][0]["id"] == "prism1"


def test_zoom_focus_iris_frost_and_colour_temperature() -> None:
    report = lamped({
        "Zoom": one({"type": "Zoom", "angleStart": "10deg", "angleEnd": "40deg"}),
        "Zoom 2": one({"type": "Zoom", "angleStart": "narrow", "angleEnd": "wide"}),
        "Focus": one({"type": "Focus", "distanceStart": "near", "distanceEnd": "far"}),
        "Iris": one({"type": "Iris", "openPercentStart": "open", "openPercentEnd": "closed"}),
        "Frost": one({"type": "Frost", "frostIntensityStart": "0%", "frostIntensityEnd": "100%"}),
        "CTO": one({"type": "ColorTemperature", "colorTemperatureStart": "6500K",
                    "colorTemperatureEnd": "3200K"}),
    }, [{"name": "1", "channels": ["Zoom", "Focus", "Iris", "Frost", "CTO"]},
        {"name": "2", "channels": ["Zoom 2"]}],
       physical={"lens": {"degreesMinMax": [5, 50]}})  # fmt: skip
    assert [c["attribute"] for c in channels_of(report)[:-1]] == [
        "zoom", "focus", "iris", "frost", "cto",
    ]  # fmt: skip
    assert [caps(report, k)[0][2] for k in range(5)] == [
        (10.0, 40.0), (0.0, 1.0), (1.0, 0.0), (0.0, 1.0), (0.0, 1.0),
    ]  # fmt: skip
    assert caps(report, 0, mode=1) == [("range", (0, 255), (5.0, 50.0))]
    assert report.profile["physical"]["zoomRange"] == (5.0, 50.0)


def test_fog_output_is_intensity_after_its_dead_band() -> None:
    report = imported({"Fog": many(
        (0, 9, {"type": "NoFunction"}),
        (10, 255, {"type": "FogOutput", "fogOutputStart": "weak", "fogOutputEnd": "strong"}),
    )})  # fmt: skip
    assert at(report, 0)["attribute"] == "intensity"
    assert caps(report, 0) == [
        ("range", (0, 0), (0.0, 0.0)),
        ("fn", (1, 9), "noFunction", None),
        ("range", (10, 255), (0.0, 1.0)),
    ]


def test_no_function_is_the_dead_band_of_the_channels_other_capability() -> None:
    report = lamped({
        "Strobe": many((0, 9, {"type": "NoFunction"}),
                       (10, 255, {"type": "ShutterStrobe", "shutterEffect": "Strobe"})),
        "Gobo Wheel": many((0, 9, {"type": "NoFunction"}),
                           (10, 127, {"type": "WheelSlot", "slotNumber": 1}),
                           (128, 255, {"type": "WheelSlot", "slotNumber": 2})),
    }, wheels=WHEELS)  # fmt: skip
    assert caps(report, 0) == [("fn", (0, 9), "open", None), ("fn", (10, 255), "strobe", None)]
    assert caps(report, 1) == [
        ("fn", (0, 9), "noFunction", None),
        ("slot", (10, 127), "open"),
        ("slot", (128, 255), "breakup"),
    ]


def preset(name: str | None = None, *colours: str, **more: Any) -> Doc:
    capability: Doc = {"type": "ColorPreset", **more}
    if name is not None:
        capability["comment"] = name
    if colours:
        capability["colors"] = list(colours)
    return capability


def macro_default(report: ImportReport, offset: int = 0, mode: int = 0) -> str:
    """The option the imported channel outputs when nothing controls it."""
    profile = cast(Doc, report.profile)
    mode_id = profile["modes"][mode]["id"]
    rig = {**fixture("f", 1, profile["id"], 1, mode_id=mode_id),
           "profileRevision": profile["revision"]}  # fmt: skip
    compiled = compile_doc(show([profile], [rig]))
    channel = at(report, offset, mode)
    slot = compiled.slots.find(TargetRef(fixtureId=FixtureId("f"), element=channel["element"]),
                               channel["attribute"])  # fmt: skip
    assert slot is not None
    return slot.options[int(compiled.slots.defaultFrame[slot.lanes][0])]


def test_colour_presets_are_slots_of_a_macro_wheel_and_effects_options_with_a_speed() -> None:
    """The Wild Wash Pro 648's colour macro: no NoFunction, a black first
    preset, "Red" twice, and two programs with a speed."""
    report = lamped({"Color Macro": many(
        (0, 5, preset("LEDs off (blackout)", "#000000")),
        (6, 13, preset("Red", "#ff0000")),
        (14, 21, preset("Split", "#ff0000", "#0000ff")),
        (22, 29, preset("Red", "#ff0000")),  # the same preset again: the same option
        (30, 37, preset("Red", "#ff8080")),  # another colour of that name: a new one
        (38, 192, {"type": "Effect", "effectName": "Colour change",
                   "speedStart": "slow", "speedEnd": "fast"}),
        (193, 255, {"type": "Effect", "effectName": "Gradual colour change",
                    "speedStart": "fast reverse", "speedEnd": "50%"}),
    )})  # fmt: skip
    assert at(report, 0)["attribute"] == "colorMacro"
    assert caps(report, 0) == [
        ("slot", (0, 5), "lEDsOffBlackout"),
        ("slot", (6, 13), "red"),
        ("slot", (14, 21), "split"),
        ("slot", (22, 29), "red"),
        ("slot", (30, 37), "red2"),
        ("fn", (38, 192), "colourChange", (0.0, 1.0)),
        ("fn", (193, 255), "gradualColourChange", (1.0, 0.5)),
    ]
    assert {c["wheel"] for c in at(report, 0)["capabilities"] if c["kind"] == "slot"} == {"macro1"}
    (wheel,) = report.profile["wheels"]
    assert (wheel["id"], wheel["kind"]) == ("macro1", "color")
    assert [(s["id"], s["name"], s.get("color")) for s in wheel["slots"]] == [
        ("lEDsOffBlackout", "LEDs off (blackout)", {"r": 0.0, "g": 0.0, "b": 0.0}),
        ("red", "Red", {"r": 1.0, "g": 0.0, "b": 0.0}),
        ("split", "Split", {"r": 0.5, "g": 0.0, "b": 0.5}),
        ("red2", "Red", {"r": 1.0, "g": 0.2159, "b": 0.2159}),
    ]
    assert macro_default(report) == "lEDsOffBlackout"  # defaultValue 0: as the chart says
    assert not noted(report, "Color Macro")


def test_no_function_on_a_macro_channel_is_off_and_the_default_selects() -> None:
    report = lamped({"Macro": many(
        (0, 9, {"type": "NoFunction"}),
        (10, 19, preset("Red", "#ff0000")),
        (20, 29, preset(None, colorsStart=["#ff0000"], colorsEnd=["#ffff00"])),  # a sweep
        (30, 39, preset(None, colorTemperature="3200K")),
        (40, 255, {"type": "Effect", "effectName": "Sound", "soundControlled": True}),
        defaultValue=15,
    )})  # fmt: skip
    assert caps(report, 0) == [
        ("fn", (0, 9), "off", None),
        ("slot", (10, 19), "red"),
        ("slot", (20, 29), "preset"),
        ("slot", (30, 39), "preset2"),
        ("fn", (40, 255), "sound", None),
    ]
    assert [s.get("color") for s in report.profile["wheels"][0]["slots"]][1:] == [None, None]
    assert macro_default(report) == "red"  # defaultValue 15


def test_colour_jump_and_fade_programs_are_a_colour_effect() -> None:
    jump = {"type": "Effect", "effectPreset": "ColorJump"}
    programs = [(16 * k, 16 * k + 15, {**jump, "comment": f"Program {k + 1}"}) for k in range(3)]
    report = lamped({
        "Programs": many(
            *programs,
            (48, 127, {"type": "Effect", "effectPreset": "ColorFade",
                       "speedStart": "stop", "speedEnd": "fast"}),
            (128, 255, {"type": "Effect", "effectPreset": "ColorFade", "speed": "120bpm"}),
        ),
        # A preset channel whose first range is a program stays a colour macro.
        "Macro": many((0, 99, {"type": "Effect", "effectPreset": "ColorJump"}),
                      (100, 255, preset("Blue", "#0000ff"))),
    })  # fmt: skip
    assert at(report, 0)["attribute"] == "colorEffect"
    assert caps(report, 0) == [
        ("fn", (0, 15), "program1", None),
        ("fn", (16, 31), "program2", None),
        ("fn", (32, 47), "program3", None),
        ("fn", (48, 127), "colorFade", (0.0, 1.0)),
        ("fn", (128, 255), "colorFade2", None),
    ]
    assert noted(report, "Programs", "colorFade2 has no colorMacroRate", "120bpm")
    assert at(report, 1)["attribute"] == "colorMacro"
    assert caps(report, 1) == [("fn", (0, 99), "colorJump", None), ("slot", (100, 255), "blue")]
    assert macro_default(report) == "program1"


def test_strobes_keep_their_rate_beside_colour_programs() -> None:
    """A strobe channel with a sound-to-colour range stays a shutter (BeamZ
    PLS25); a strobe range on a macro channel keeps its strobeRate, so the
    strobe cap holds over it."""
    report = lamped({
        "Strobe": many((0, 0, {"type": "NoFunction"}),
                       (1, 10, {"type": "Effect", "effectPreset": "ColorJump",
                                "soundControlled": True}),
                       (11, 255, {"type": "ShutterStrobe", "shutterEffect": "Strobe",
                                  "speedStart": "1Hz", "speedEnd": "25Hz"})),
        "Macro": many((0, 127, preset("Red", "#ff0000")),
                      (128, 255, {"type": "ShutterStrobe", "shutterEffect": "Strobe",
                                  "speedStart": "2Hz", "speedEnd": "10Hz"})),
    })  # fmt: skip
    assert at(report, 0)["attribute"] == "shutter"
    assert caps(report, 0)[-1] == ("fn", (11, 255), "strobe", (1.0, 25.0))
    assert at(report, 1)["attribute"] == "colorMacro"
    assert caps(report, 1) == [("slot", (0, 127), "red"), ("fn", (128, 255), "strobe", (2.0, 10.0))]
    assert at(report, 1)["capabilities"][1]["param"]["attribute"] == "strobeRate"


def test_a_per_pixel_macro_channel_shares_one_wheel_and_a_second_one_is_held() -> None:
    matrix = {
        "matrix": {"pixelCount": [2, 1, 1]},
        "templateChannels": {"Macro $pixelKey": many(
            (0, 127, {"type": "NoFunction"}), (128, 255, preset("Red", "#ff0000")))},
    }  # fmt: skip
    insert = {"insert": "matrixChannels", "repeatFor": "eachPixelXYZ",
              "channelOrder": "perPixel", "templateChannels": ["Macro $pixelKey"]}  # fmt: skip
    report = imported(
        {"Dimmer": one({"type": "Intensity"}),
         "Gel": many((0, 127, preset("Amber", "#ff8000")), (128, 255, preset("Blue", "#0000ff")))},
        [{"name": "Pixels", "channels": ["Dimmer", insert, "Gel"]}],
        **matrix,
    )  # fmt: skip
    placed = [(c["offset"], c["element"], c["attribute"]) for c in channels_of(report)]
    assert placed == [(0, 0, "intensity"), (1, 0, "colorMacro"), (2, 1, "colorMacro"),
                      (3, 0, "control")]  # fmt: skip
    assert [w["id"] for w in report.profile["wheels"]] == ["macro1"]
    assert noted(report, "Gel", "a second colorMacro channel; held as control")


def test_a_wheel_or_shutter_without_its_default_option_is_held_as_control() -> None:
    """busk outputs ``open`` (``off`` for a prism) when nothing controls a
    discrete attribute, so its channel must offer it (validation)."""
    report = lamped({
        "Gobo Wheel": many((0, 127, {"type": "WheelSlot", "slotNumber": 2}),
                           (128, 255, {"type": "WheelSlot", "slotNumber": 3}), defaultValue=5),
        "Strobe": one({"type": "ShutterStrobe", "shutterEffect": "Strobe"}),
    }, wheels=WHEELS)  # fmt: skip
    assert [(c["attribute"], c["defaultDmx"]) for c in channels_of(report)[:-1]] == [
        ("control", 5), ("control", 0),
    ]  # fmt: skip
    assert noted(report, "Gobo Wheel", "offers no 'open'", "held at DMX 5")
    assert noted(report, "Strobe", "offers no 'open'")


@pytest.mark.parametrize(
    "capability",
    [
        {"type": "Effect", "effectName": "Auto program"},
        {"type": "EffectSpeed", "speedStart": "slow", "speedEnd": "fast"},
        {"type": "Maintenance", "comment": "Reset"},
        {"type": "Generic"},
        {"type": "Speed", "speedStart": "slow", "speedEnd": "fast"},
        {"type": "Rotation", "speedStart": "slow CW", "speedEnd": "fast CW"},
        {"type": "FogType", "fogType": "Haze"},
    ],
)
def test_everything_else_is_a_control_channel_held_at_its_default(capability: Doc) -> None:
    report = imported({
        "Dimmer": one({"type": "Intensity"}),
        "Other": one(capability, defaultValue=42),
    })  # fmt: skip
    other = at(report, 1)
    assert (other["attribute"], other["defaultDmx"]) == ("control", 42)
    assert [kind for kind, *_ in caps(report, 1)] == ["fn"]
    assert noted(report, "Other", capability["type"], "held at DMX 42")


# ------------------------------------------------------------------ channels


def test_fine_aliases_place_fine_bytes_wherever_the_mode_puts_them() -> None:
    report = lamped({
        "Pan": one({"type": "Pan", "angleStart": "0deg", "angleEnd": "540deg"},
                   fineChannelAliases=["Pan fine"]),
        "Tilt": one({"type": "Tilt", "angleStart": "0deg", "angleEnd": "270deg"},
                    fineChannelAliases=["Tilt fine"]),
        "Dimmer": one({"type": "Intensity"}, fineChannelAliases=["Dimmer fine", "Dimmer fine^2"]),
    }, [{"name": "Odd", "channels": ["Pan", "Tilt", "Tilt fine", "Pan fine"]},
        {"name": "24", "channels": ["Dimmer fine^2", "Dimmer", "Dimmer fine"]},
        {"name": "Next", "channels": ["Pan", "Pan fine"]}])  # fmt: skip
    pan, tilt, _ = channels_of(report)
    assert (pan["bytes"], pan["fineOffsets"]) == (2, [3])
    assert (tilt["bytes"], "fineOffsets" in tilt) == (2, False)  # adjacent: the default
    assert caps(report, 0) == [("range", (0, 65535), (-270.0, 270.0))]
    dimmer, _ = channels_of(report, 1)
    assert (dimmer["offset"], dimmer["bytes"], dimmer["fineOffsets"]) == (1, 3, [2, 0])
    assert caps(report, 1, mode=1) == [("range", (0, 0xFFFFFF), (0.0, 1.0))]
    adjacent, _ = channels_of(report, 2)
    assert (adjacent["bytes"], "fineOffsets" in adjacent) == (2, False)


def test_ranges_scale_to_the_bytes_the_mode_uses() -> None:
    halves = [
        (0, 127, {"type": "Intensity", "brightnessStart": "0%", "brightnessEnd": "50%"}),
        (128, 255, {"type": "Intensity", "brightnessStart": "50%", "brightnessEnd": "100%"}),
    ]
    report = imported(
        {
            "D8": many(*halves, fineChannelAliases=["D8 fine"], dmxValueResolution="8bit"),
            "D16": many(
                *[(lo * 256, hi * 256 + 255, cap) for lo, hi, cap in halves],
                fineChannelAliases=["D16 fine"],
            ),
        },
        [
            {"name": "fine", "channels": ["D8", "D8 fine"]},
            {"name": "coarse", "channels": ["D8"]},
            {"name": "coarse 16", "channels": ["D16"]},
        ],
    )
    assert [dmx for _, dmx, _ in caps(report, 0)] == [(0, 32767), (32768, 65535)]
    assert [dmx for _, dmx, _ in caps(report, 0, mode=1)] == [(0, 127), (128, 255)]
    assert [dmx for _, dmx, _ in caps(report, 0, mode=2)] == [(0, 127), (128, 255)]


def test_a_second_channel_of_an_attribute_is_held_and_reported_once() -> None:
    report = imported({"A": one({"type": "Intensity"}), "B": one({"type": "Intensity"})})
    assert [c["attribute"] for c in channels_of(report)] == ["intensity", "control"]
    assert [note for note in report.notes if note.startswith("B:")] == [
        "B: a second intensity channel; held as control"
    ]


def test_default_and_highlight_values_may_be_percentages() -> None:
    channel = one(
        {"type": "Intensity"},
        fineChannelAliases=["D fine"],
        defaultValue="50%",
        highlightValue="100%",
    )
    report = imported(
        {"D": channel, "E": one({"type": "Intensity"}, defaultValue=200)},
        [{"name": "8", "channels": ["D"]}, {"name": "16", "channels": ["D", "D fine"]},
         {"name": "E", "channels": ["E"]}],
    )  # fmt: skip
    assert (at(report, 0)["defaultDmx"], at(report, 0)["highlightDmx"]) == (128, 255)
    assert (at(report, 0, 1)["defaultDmx"], at(report, 0, 1)["highlightDmx"]) == (32768, 65535)
    assert at(report, 0, 2)["defaultDmx"] == 200


def test_null_entries_leave_an_offset_unused() -> None:
    report = imported(
        {c: one({"type": "ColorIntensity", "color": c}) for c in ("Red", "Green", "Blue")},
        [{"name": "Gap", "channels": ["Red", None, "Green", "Blue", None]}],
    )
    mode = report.profile["modes"][0]
    assert mode["footprint"] == 5
    assert [c["offset"] for c in mode["channels"]] == [0, 2, 3]


MATRIX = {
    "matrix": {"pixelCount": [3, 1, 1]},
    "templateChannels": {
        f"{c} $pixelKey": {"capability": {"type": "ColorIntensity", "color": c}}
        for c in ("Red", "Green", "Blue")
    },
}


@pytest.mark.parametrize("order", ["perPixel", "perChannel"])
def test_matrix_inserts_make_one_element_per_pixel(order: str) -> None:
    insert = {
        "insert": "matrixChannels",
        "repeatFor": "eachPixelXYZ",
        "channelOrder": order,
        "templateChannels": ["Red $pixelKey", "Green $pixelKey", "Blue $pixelKey"],
    }
    report = imported(
        {"Dimmer": one({"type": "Intensity"})},
        [{"name": "Pixels", "channels": ["Dimmer", insert]}],
        **copy.deepcopy(MATRIX),
    )
    mode = report.profile["modes"][0]
    assert [e["name"] for e in mode["elements"]] == ["Pixel 1", "Pixel 2", "Pixel 3"]
    assert mode["elements"][2]["layout"] == {"x": 2.0, "y": 0.0}
    placed = [
        (c["offset"], c["element"], c.get("component", c["attribute"])) for c in mode["channels"]
    ]
    if order == "perPixel":
        expected = [(1 + 3 * p + k, p, colour) for p in range(3)
                    for k, colour in enumerate(("red", "green", "blue"))]  # fmt: skip
    else:
        expected = [(1 + 3 * k + p, p, colour)
                    for k, colour in enumerate(("red", "green", "blue"))
                    for p in range(3)]  # fmt: skip
    assert placed == [(0, 0, "intensity"), *sorted(expected)]


def test_a_switching_channel_keeps_its_triggers_default() -> None:
    report = lamped(
        {
            "Mode": many(
                (0, 127, {"type": "Generic", "switchChannels": {"Function": "Strobe"}}),
                (128, 255, {"type": "Generic", "switchChannels": {"Function": "Program"}}),
                defaultValue=0,
            ),
            "Strobe": one({"type": "StrobeSpeed", "speedStart": "1Hz", "speedEnd": "10Hz"}),
            "Program": one({"type": "Effect", "effectName": "Chase"}),
        },
        [{"name": "Switch", "channels": ["Mode", "Function"]}],
    )
    assert at(report, 1)["attribute"] == "strobeRate"
    assert noted(report, "Function", "switching channel", "Strobe", "Mode")


# ------------------------------------------------------------------ identity and failures


def test_id_name_and_revision() -> None:
    data = ofl({"Dimmer": one({"type": "Intensity"})})
    profile = import_ofl(data, manufacturer="Acme Co", key="spot-1").profile
    assert profile["id"] == "ofl-acme-co-spot-1"
    assert (profile["name"], profile["model"], profile["source"]) == ("Acme Co Test", "Test", "ofl")
    assert profile["revision"].startswith("2026-01-02-")
    edited = copy.deepcopy(data)
    edited["availableChannels"]["Dimmer"]["defaultValue"] = 10
    assert import_ofl(edited, manufacturer="Acme Co", key="spot-1").profile["revision"] not in (
        profile["revision"],
    )
    again = import_ofl(copy.deepcopy(data), manufacturer="Acme Co", key="spot-1")
    assert again.profile["revision"] == profile["revision"]


def test_a_busk_that_imports_differently_makes_a_new_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IMPORT_VERSION (color-macros-plan Q5): a show embedding an older import
    sees the library's revision, and ``profile update`` takes it."""
    folder = tmp_path / "acme"
    folder.mkdir()
    (folder / "wash.json").write_text(json.dumps(ofl({"Dimmer": one({"type": "Intensity"})})))
    monkeypatch.setattr("busk.importers.ofl.IMPORT_VERSION", 1)
    old = OfflineShow(show_of(show([], [])), library=ProfileLibrary([folder], builtin=False))
    assert old.execute('fixture add 1 "acme Test" mode All at 1.1').ok
    embedded = old.show["profiles"][0]["revision"]
    monkeypatch.undo()
    new = OfflineShow(old.show, library=ProfileLibrary([folder], builtin=False))
    revision = new.execute("library").text.split("revision ")[1].split(")")[0]
    assert revision != embedded
    assert revision.startswith("2026-01-02-")
    assert new.execute("list profiles").text == (
        f"acme Test (revision {embedded} → {revision} in the library): All"
    )
    reply = new.execute('profile update "acme Test"')
    assert reply.text == f"updated profile 'acme Test' to revision '{revision}' (1 fixture)"
    assert new.show["fixtures"][0]["profileRevision"] == revision


def test_a_mode_that_cannot_be_imported_is_skipped_and_reported() -> None:
    report = imported(
        {"Dimmer": one({"type": "Intensity"})},
        [{"name": "Good", "channels": ["Dimmer"]}, {"name": "Bad", "channels": ["Nope"]}],
    )
    assert [m["name"] for m in report.profile["modes"]] == ["Good"]
    assert noted(report, "mode 'Bad' skipped", "Nope")
    with pytest.raises(ImportFailed, match="no mode"):
        imported({"Dimmer": one({"type": "Intensity"})}, [{"name": "Bad", "channels": ["Nope"]}])
    with pytest.raises(ImportFailed, match="not an OFL fixture"):
        import_ofl({"name": "x"}, manufacturer="M", key="k")


def test_the_manufacturer_comes_from_the_repository_layout(tmp_path: Path) -> None:
    data = json.dumps(ofl({"Dimmer": one({"type": "Intensity"})}))
    (tmp_path / "fixtures" / "acme").mkdir(parents=True)
    (tmp_path / "fixtures" / "acme" / "spot.json").write_text(data)
    (tmp_path / "fixtures" / "loose.json").write_text(data)
    assert read_ofl(tmp_path / "fixtures" / "acme" / "spot.json").profile["manufacturer"] == "acme"
    assert read_ofl(tmp_path / "fixtures" / "loose.json").profile["manufacturer"] == "Unknown"
    named = read_ofl(tmp_path / "fixtures" / "loose.json", manufacturer="Acme")
    assert named.profile["id"] == "ofl-acme-loose"
    with pytest.raises(ImportFailed):
        read_ofl(tmp_path / "missing.json")


# ------------------------------------------------------------------ the TupperDMX check


def _sample(mode: Doc, element: int, attribute: str) -> list[Any]:
    """Logical values of ``attribute`` across what the hand transcription
    defines: every range's span (and every function parameter's) in steps."""
    spans = [
        tuple(cap["value"]) if cap["kind"] == "range" else tuple(cap["param"]["value"])
        for channel in mode["channels"]
        if channel["element"] == element
        for cap in channel["capabilities"]
        if (cap["kind"] == "range" and channel["attribute"] == attribute)
        or (cap["kind"] == "function" and cap.get("param", {}).get("attribute") == attribute)
    ]
    if not spans:
        return []
    low, high = min(min(s) for s in spans), max(max(s) for s in spans)
    return sorted({*np.linspace(low, high, 41).tolist(), 0.0 if low <= 0 <= high else low})


COLOURS = [
    {"r": 1, "g": 0, "b": 0}, {"r": 0, "g": 1, "b": 0}, {"r": 0, "g": 0, "b": 1},
    {"r": 1, "g": 1, "b": 1}, {"r": 0.2, "g": 0.5, "b": 0.8}, {"r": 0, "g": 0, "b": 0},
]  # fmt: skip


@pytest.mark.parametrize(("ofl_file", "transcription"), TUPPER)
def test_the_tupperdmx_check(ofl_file: str, transcription: str) -> None:
    """Every logical value of every attribute both profiles define converts
    to the same DMX, in every mode the hand transcription has. The one
    expected difference: the smoke machine's DMX 0–7 dead band (OFL
    ``NoFunction``), so intensity above 0 starts at DMX 8."""
    hand = json.loads((TRANSCRIBED / f"{transcription}.json").read_text())
    report = read_ofl(OFL / f"{ofl_file}.json", manufacturer="TupperDMX")
    imported_ = cast(Doc, report.profile)
    compared = 0
    for hand_mode in hand["modes"]:
        mode = next(m for m in imported_["modes"] if m["name"] == hand_mode["name"])
        assert mode["footprint"] == hand_mode["footprint"]
        a = fixture("a", 1, hand["id"], 1, mode_id=hand_mode["id"])
        b = {**fixture("b", 2, imported_["id"], 101, mode_id=mode["id"]),
             "profileRevision": imported_["revision"]}  # fmt: skip
        compiled = compile_doc(show([hand, imported_], [a, b]))
        footprint = hand_mode["footprint"]
        for slot in compiled.slots.slots:
            if slot.target["fixtureId"] != "a":
                continue
            element, attribute = slot.target["element"], slot.attribute.id
            other = compiled.slots.find(
                TargetRef(fixtureId=FixtureId("b"), element=element), attribute
            )
            if other is None:
                continue
            if slot.attribute.kind == "discrete":
                values: list[Any] = [{"slot": o} for o in slot.options if o in other.options]
            elif slot.attribute.kind == "color":
                values = COLOURS
            else:
                values = _sample(hand_mode, element, attribute)
            shutters: list[str | None] = [None]
            if attribute == "strobeRate":  # the rate shows only under its function
                shutters = ["strobe", "pulse", "random"]
            for shutter in shutters:
                for value in values:
                    keys: dict[Any, Any] = {("a", element, attribute): value,
                                            ("b", element, attribute): value}  # fmt: skip
                    if shutter is not None:
                        a_shutter = compiled.slots.find(slot.target, "shutter")
                        if a_shutter is None or shutter not in a_shutter.options:
                            continue
                        keys |= {("a", element, "shutter"): {"slot": shutter},
                                 ("b", element, "shutter"): {"slot": shutter}}  # fmt: skip
                    out = fast_convert(compiled, frame(compiled, keys))[0]
                    hand_dmx = out[:footprint].tolist()
                    ofl_dmx = out[100 : 100 + footprint].tolist()
                    compared += 1
                    if ofl_file == "smoke-machine" and attribute == "intensity" and value > 0:
                        assert ofl_dmx[0] >= 8, value  # the dead band, expected
                        assert ofl_dmx[1:] == hand_dmx[1:]
                        continue
                    assert ofl_dmx == hand_dmx, (hand_mode["name"], attribute, value, shutter)
    assert compared > 0


def test_only_the_import_has_the_moving_heads_18ch_and_the_smoke_machines_2ch() -> None:
    for ofl_file, transcription in TUPPER:
        hand = json.loads((TRANSCRIBED / f"{transcription}.json").read_text())
        imported_ = read_ofl(OFL / f"{ofl_file}.json", manufacturer="TupperDMX").profile
        extra = {m["name"] for m in imported_["modes"]} - {m["name"] for m in hand["modes"]}
        assert extra == {"moving-head": {"18ch"}, "smoke-machine": {"2ch"}}.get(ofl_file, set())


def test_the_smoke_machines_dead_band() -> None:
    report = read_ofl(OFL / "smoke-machine.json", manufacturer="TupperDMX")
    assert caps(report, 0) == [
        ("range", (0, 0), (0.0, 0.0)),
        ("fn", (1, 7), "noFunction", None),
        ("range", (8, 255), (0.0, 1.0)),
    ]


# ------------------------------------------------------------------ build-ofl.busk


def _build(script: str, library: ProfileLibrary) -> Any:
    """The show a TupperDMX build script makes (its ``save`` skipped)."""
    ids = CounterIds()
    start = new_show("TupperDMX demo", ids=ids, now=datetime(2026, 10, 15, tzinfo=UTC),
                     cid="0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f")  # fmt: skip
    compiled = compile_show(start)
    session = Session(start, Engine(compiled, FakeClock()).bus, compiled=compiled, ids=ids)
    console = Console(session, library)
    for line in (ROOT / "examples" / "tupperdmx" / script).read_text().splitlines():
        if line.strip() != "save":
            reply = console.execute(line)
            assert reply.ok, (line, reply.text)
    return session.show


def test_build_ofl_makes_the_same_show_on_imported_profiles() -> None:
    hand = _build("build.busk", ProfileLibrary([TRANSCRIBED]))
    ofl_show = _build("build-ofl.busk", ProfileLibrary([OFL]))
    issues = {
        name: [(i.severity, i.path) for i in validate_show(json.dumps(doc))[1]]
        for name, doc in (("hand", hand), ("ofl", ofl_show))
    }
    assert issues["ofl"] == issues["hand"]
    assert issues["hand"] == [
        ("warning", "fixtures[8].patch.address"),
        ("warning", "fixtures[10].patch.address"),
    ]
    looks = [p["id"] for p in hand["playbacks"]]
    assert len(looks) == 8
    frames = []
    for show_doc in (hand, ofl_show):
        compiled = compile_doc(cast(Doc, show_doc))
        per_look = []
        for playback in show_doc["playbacks"]:
            harness = Harness(compiled)
            harness.submit(fader(playback["id"], 1.0))
            harness.tick(0.0)
            per_look.append(harness.tick(5.0).universe)  # past every 1 s fade
        frames.append(per_look)
    for look, hand_dmx, ofl_dmx in zip(looks, *frames, strict=True):
        assert ofl_dmx == hand_dmx, look  # the looks are 0 or 100 % fog: the profiles agree


# ------------------------------------------------------------------ library and CLI


def test_the_library_imports_ofl_files_on_load(tmp_path: Path) -> None:
    folder = tmp_path / "Acme"  # the manufacturer, as in the OFL repository layout
    folder.mkdir()
    for name in ("par-rgbw", "smoke-machine"):
        (folder / f"{name}.json").write_text((OFL / f"{name}.json").read_text())
    (folder / "broken.json").write_text(json.dumps({"availableChannels": {}, "modes": []}))
    library = ProfileLibrary([folder], builtin=False)
    assert [p["id"] for p in library] == ["ofl-acme-par-rgbw", "ofl-acme-smoke-machine"]
    assert library.find("acme par-rgbw") is not None
    assert any("broken.json" in p and "no mode" in p for p in library.problems)
    assert any("smoke-machine.json: Fog Type: no busk attribute" in p for p in library.problems)


def test_busk_import_ofl_writes_profiles_the_library_loads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = [str(OFL / f"{name}.json") for name, _ in TUPPER]
    out = tmp_path / "profiles"
    code = main(["import", "ofl", *files, "--manufacturer", "TupperDMX", "--out", str(out)])
    assert code == 0
    printed = capsys.readouterr().out
    assert "'TupperDMX moving-head' (modes 12ch, 18ch)" in printed
    assert "4 notes (--report)" in printed
    library = ProfileLibrary([out], builtin=False)
    assert not library.problems
    assert sorted(p["name"] for p in library) == sorted(f"TupperDMX {n}" for n, _ in TUPPER)
    code = main(["import", "ofl", files[4], "--manufacturer", "TupperDMX", "--out", str(out),
                 "--report"])  # fmt: skip
    assert code == 0
    assert "  Fog Type: no busk attribute (FogType); held at DMX 0" in capsys.readouterr().out
    (tmp_path / "bad.json").write_text("{")
    assert main(["import", "ofl", str(tmp_path / "bad.json"), "--out", str(out)]) == 1
    assert "bad.json" in capsys.readouterr().err


def test_imported_profiles_drive_an_engine() -> None:
    """The moving head's 18ch mode on a real engine: a 16-bit pan."""
    profile = cast(Doc, read_ofl(OFL / "moving-head.json", manufacturer="T").profile)
    mode = next(m for m in profile["modes"] if m["name"] == "18ch")
    head = {**fixture("h", 1, profile["id"], 1, mode_id=mode["id"]),
            "profileRevision": profile["revision"]}  # fmt: skip
    compiled = compile_doc(show([profile], [head]))
    out = fast_convert(compiled, frame(compiled, {("h", "pan"): 135.0}))[0]
    coarse, fine = int(out[0]), int(out[1])
    assert abs((coarse * 256 + fine) - 0.75 * 65535) <= 1
