"""Slot table (§6.1–§6.2): allocation order, lanes, options and the default frame."""

from __future__ import annotations

import math

import numpy as np
import pytest

from builders import (
    APPENDIX_A,
    DEMO,
    channel,
    color,
    compile_doc,
    feature_matrix,
    fixture,
    fn,
    load_doc,
    mode,
    profile,
    rng,
    show,
)
from builders import slot as wheel_slot
from busk.compiler.compile import CompiledShow
from busk.compiler.slots import Slot
from busk.model.common import FixtureId, TargetRef


def slot_list(compiled: CompiledShow, fixture_id: str) -> list[tuple[int, str, int]]:
    """``(element, attribute, laneCount)`` of a fixture's slots, in table order."""
    return [
        (s.target["element"], s.attribute.id, s.laneCount)
        for s in compiled.slots.slots
        if s.target["fixtureId"] == fixture_id
    ]


def find(compiled: CompiledShow, fixture_id: str, attribute: str, element: int = 0) -> Slot:
    found = compiled.slots.find(
        TargetRef(fixtureId=FixtureId(fixture_id), element=element), attribute
    )
    assert found is not None
    return found


@pytest.fixture(scope="module")
def appendix() -> CompiledShow:
    return compile_doc(load_doc(APPENDIX_A))


@pytest.fixture(scope="module")
def demo() -> CompiledShow:
    return compile_doc(load_doc(DEMO))


def test_appendix_a_slots_in_registry_order(appendix: CompiledShow) -> None:
    # Registry (§5.3) order: gobo1 comes before zoom. strobeRate comes from the
    # shutter's strobe parameter; the par's intensity is its virtual dimmer.
    spot = [
        (0, "intensity", 1),
        (0, "pan", 1),
        (0, "tilt", 1),
        (0, "color", 4),  # r, g, b, w
        (0, "gobo1", 1),
        (0, "zoom", 1),
        (0, "shutter", 1),
        (0, "strobeRate", 1),
    ]
    assert slot_list(appendix, "fx-mh1") == spot
    assert slot_list(appendix, "fx-mh2") == spot
    assert slot_list(appendix, "fx-par1") == [(0, "intensity", 1), (0, "color", 3)]
    assert [s.index for s in appendix.slots.slots] == list(range(18))


def test_lanes_are_contiguous(appendix: CompiledShow) -> None:
    offset = 0
    for slot in appendix.slots.slots:
        assert slot.laneOffset == offset
        offset += slot.laneCount
    assert appendix.slots.laneCount == offset == 26
    assert appendix.slots.defaultFrame.shape == (26,)


def test_appendix_a_default_frame(appendix: CompiledShow) -> None:
    default = appendix.slots.defaultFrame

    def lanes(attribute: str) -> list[float]:
        return list(default[find(appendix, "fx-mh1", attribute).lanes])

    assert lanes("intensity") == [0.0]
    assert lanes("pan") == lanes("tilt") == [0.0]
    assert lanes("zoom") == [21.0]  # midpoint of zoomRange [12, 30]
    assert lanes("gobo1") == [0.0]  # options ("open", "breakup"): index of "open"
    assert lanes("shutter") == [1.0]  # options ("closed", "open", "strobe")
    assert lanes("strobeRate") == [0.0]
    r, g, b, w = lanes("color")
    assert (r, g, b) == (1.0, 1.0, 1.0)
    assert math.isnan(w)  # white is derived
    assert list(default[find(appendix, "fx-par1", "color").lanes]) == [1.0, 1.0, 1.0]


def test_options_and_wheels(appendix: CompiledShow, demo: CompiledShow) -> None:
    assert find(appendix, "fx-mh1", "shutter").options == ("closed", "open", "strobe")
    assert find(appendix, "fx-mh1", "gobo1").wheels == ("gobo1",)
    assert find(appendix, "fx-mh1", "shutter").wheels == ()
    # MH-X25: the duplicate "open" ranges collapse; shake and spin are not options.
    assert find(demo, "fx-mh1", "shutter").options == ("closed", "open", "strobe")
    assert find(demo, "fx-mh1", "gobo1").options == (
        "open",
        *(f"gobo{k}" for k in range(2, 9)),
    )
    assert find(demo, "fx-mh1", "colorWheel").options[:2] == ("open", "yellow")
    assert len(find(demo, "fx-mh1", "colorWheel").options) == 9  # no split colours


def test_mhx25_has_no_control_slots(demo: CompiledShow) -> None:
    assert [attribute for _, attribute, _ in slot_list(demo, "fx-mh1")] == [
        "intensity",
        "pan",
        "tilt",
        "positionSpeed",
        "colorWheel",
        "gobo1",
        "gobo1Rotation",
        "shutter",
        "strobeRate",
    ]


def test_colorband_has_twelve_virtually_dimmed_cells(demo: CompiledShow) -> None:
    assert slot_list(demo, "fx-bar1") == [
        (cell, attribute, lanes)
        for cell in range(12)
        for attribute, lanes in (("intensity", 1), ("color", 3))
    ]


def test_extras_follow_the_element_emitters(demo: CompiledShow) -> None:
    assert find(demo, "fx-wash1", "color").extras == ("w",)
    assert find(demo, "fx-bar1", "color", element=5).extras == ()
    matrix = compile_doc(feature_matrix())
    rgbawuv = find(matrix, "fx-rgbawuv", "color")
    assert rgbawuv.extras == ("w", "a", "uv")
    assert rgbawuv.laneCount == 6
    assert find(matrix, "fx-cmy", "color").extras == ()


def test_unpatched_fixtures_still_get_slots() -> None:
    compiled = compile_doc(feature_matrix())
    assert slot_list(compiled, "fx-unpatched") == [(0, "intensity", 1)]
    assert not [c for c in compiled.channels if c.fixtureId == "fx-unpatched"]


def test_virtual_intensity_is_decided_per_element() -> None:
    # A bar with a master dimmer on element 0 and RGB cells on elements 1 and 2.
    cells = [
        color(1 + 3 * (cell - 1) + k, component, element=cell)
        for cell in (1, 2)
        for k, component in enumerate(("red", "green", "blue"))
    ]
    channels = [channel(0, "intensity"), *cells]
    bar = show(
        [
            profile(
                "p",
                mode(channels, mode_id="dimmer", elements=3, strategy="dimmerChannel"),
                mode(channels, mode_id="virtual", elements=3, strategy="virtual"),
            )
        ],
        [fixture("a", 1, "p", 1, mode_id="dimmer"), fixture("b", 2, "p", 10, mode_id="virtual")],
    )
    compiled = compile_doc(bar)
    assert slot_list(compiled, "a") == [(0, "intensity", 1), (1, "color", 3), (2, "color", 3)]
    assert slot_list(compiled, "b") == [
        (0, "intensity", 1),
        (1, "intensity", 1),
        (1, "color", 3),
        (2, "intensity", 1),
        (2, "color", 3),
    ]


def test_zoom_midpoint_falls_back_to_the_capabilities() -> None:
    zoom = channel(1, "zoom", rng(0, 99, 8, 20), rng(100, 255, 20, 40))
    doc = show([profile("p", mode([channel(0, "intensity"), zoom]))], [fixture("f", 1, "p", 1)])
    compiled = compile_doc(doc)
    assert list(compiled.slots.defaultFrame[find(compiled, "f", "zoom").lanes]) == [24.0]
    doc["profiles"][0]["physical"] = {"zoomRange": [10, 50]}
    compiled = compile_doc(doc)
    assert list(compiled.slots.defaultFrame[find(compiled, "f", "zoom").lanes]) == [30.0]


def test_parameter_slots_without_a_channel() -> None:
    shutter = channel(1, "shutter", fn(0, 9, "open"), fn(10, 255, "strobe", ("strobeRate", 1, 25)))
    doc = show([profile("p", mode([channel(0, "intensity"), shutter]))], [fixture("f", 1, "p", 1)])
    assert slot_list(compile_doc(doc), "f") == [
        (0, "intensity", 1),
        (0, "shutter", 1),
        (0, "strobeRate", 1),
    ]


def test_find_and_by_key(appendix: CompiledShow) -> None:
    pan = find(appendix, "fx-mh2", "pan")
    assert appendix.slots.byKey["fx-mh2:0", "pan"] == pan.index
    assert appendix.slots.find(TargetRef(fixtureId=FixtureId("fx-par1"), element=0), "pan") is None
    assert appendix.slots.find(TargetRef(fixtureId=FixtureId("nope"), element=0), "pan") is None


def test_default_frame_is_read_only(appendix: CompiledShow) -> None:
    with pytest.raises(ValueError, match="read-only"):
        appendix.slots.defaultFrame[0] = 1.0


def test_two_compiles_give_identical_tables() -> None:
    first = compile_doc(load_doc(DEMO)).slots
    second = compile_doc(load_doc(DEMO)).slots
    assert first.slots == second.slots
    assert first.byKey == second.byKey
    assert np.array_equal(first.defaultFrame, second.defaultFrame, equal_nan=True)


def test_control_channels_and_their_parameters_get_no_slots() -> None:
    macro = channel(1, "control", fn(0, 255, "macroSpeed", ("strobeRate", 0, 10)))
    doc = show([profile("p", mode([channel(0, "intensity"), macro]))], [fixture("f", 1, "p", 1)])
    assert slot_list(compile_doc(doc), "f") == [(0, "intensity", 1)]


def macro_show(default: int) -> dict:
    """A fixture with a colour macro channel (defaultDmx ``default``): an
    ``off`` range, two presets (``red`` twice), a program with a speed, and a
    colour effect channel of functions only."""
    macro = channel(
        1,
        "colorMacro",
        fn(0, 9, "off"),
        wheel_slot(10, 19, "red", "macro1"),
        wheel_slot(20, 29, "blue", "macro1"),
        wheel_slot(30, 39, "red", "macro1"),
        fn(40, 199, "colourChange", ("colorMacroRate", 0, 1)),
        rng(200, 255, 0, 1),  # a range is never an option
        default=default,
    )
    effect = channel(2, "colorEffect", fn(0, 127, "jump"), fn(128, 255, "fade"), default=200)
    wheels = [
        {
            "id": "macro1",
            "kind": "color",
            "slots": [{"id": "red", "name": "Red"}, {"id": "blue", "name": "Blue"}],
        }
    ]
    return show(
        [profile("p", mode([channel(0, "intensity"), macro, effect]), wheels=wheels)],
        [fixture("f", 1, "p", 1)],
    )


def test_colour_macro_options_are_its_slots_and_functions() -> None:
    compiled = compile_doc(macro_show(0))
    assert slot_list(compiled, "f") == [
        (0, "intensity", 1),
        (0, "colorMacro", 1),
        (0, "colorMacroRate", 1),
        (0, "colorEffect", 1),
    ]
    macro = find(compiled, "f", "colorMacro")
    assert macro.options == ("off", "red", "blue", "colourChange")
    assert macro.wheels == ("macro1",)
    assert find(compiled, "f", "colorEffect").options == ("jump", "fade")
    assert list(compiled.slots.defaultFrame[find(compiled, "f", "colorMacroRate").lanes]) == [0.5]


@pytest.mark.parametrize(
    ("default", "option"),
    [
        (0, "off"),
        (15, "red"),
        (35, "red"),  # the second "red" range: still the option "red"
        (100, "colourChange"),
        (230, "off"),  # in no option: the first one
    ],
)
def test_colour_macros_default_to_the_option_holding_their_default_dmx(
    default: int, option: str
) -> None:
    compiled = compile_doc(macro_show(default))
    macro = find(compiled, "f", "colorMacro")
    index = compiled.slots.defaultFrame[macro.lanes][0]
    assert macro.options[int(index)] == option
    effect = find(compiled, "f", "colorEffect")
    assert effect.options[int(compiled.slots.defaultFrame[effect.lanes][0])] == "fade"


def effects_show(**speed: object) -> dict:
    """A fixture with a fixture effect channel (programs, a sound-active
    one with a rate, maintenance ranges), a colour macro with a ``reset``, and
    a speed channel built from ``speed`` (``channel`` keywords and ``caps``)."""
    caps = speed.pop("caps", [rng(0, 255, 0, 1)])
    effect = channel(
        1,
        "effect",
        fn(0, 9, "off"),
        fn(10, 19, "reset"),
        fn(20, 99, "autoProgram", ("effectRate", 0, 1)),
        fn(100, 109, "maintenance"),
        fn(110, 199, "soundActive", ("soundSensitivity", 0, 1)),
        fn(200, 255, "lampOff"),
        default=15,  # in "reset": no option, so the first one
    )
    macro = channel(2, "colorMacro", fn(0, 127, "reset"), wheel_slot(128, 255, "red", "macro1"))
    rate = channel(3, "effectRate", *caps, **speed)  # type: ignore[arg-type]
    wheels = [{"id": "macro1", "kind": "color", "slots": [{"id": "red", "name": "Red"}]}]
    return show(
        [profile("p", mode([channel(0, "intensity"), effect, macro, rate]), wheels=wheels)],
        [fixture("f", 1, "p", 1)],
    )


def default_of(compiled: CompiledShow, attribute: str) -> float:
    return float(compiled.slots.defaultFrame[find(compiled, "f", attribute).lanes][0])


def test_fixture_effect_options_leave_maintenance_out() -> None:
    compiled = compile_doc(effects_show())
    assert slot_list(compiled, "f") == [
        (0, "intensity", 1),
        (0, "colorMacro", 1),
        (0, "effect", 1),
        (0, "effectRate", 1),
        (0, "soundSensitivity", 1),
    ]
    effect = find(compiled, "f", "effect")
    assert effect.options == ("off", "autoProgram", "soundActive")
    assert effect.options[int(default_of(compiled, "effect"))] == "off"
    # The colour macro's reset is no option either.
    assert find(compiled, "f", "colorMacro").options == ("red",)


@pytest.mark.parametrize(
    ("speed", "value"),
    [
        ({"default": 255}, 1.0),
        ({"default": 51}, 0.2),
        ({"default": 51, "invert": True}, 0.8),  # read back as the converter maps it
        # Only the range holding defaultDmx counts: a dead band, then 1–255.
        ({"default": 0, "caps": [rng(0, 0, 0, 0), rng(1, 255, 0.5, 1)]}, 0.0),
        ({"default": 128, "caps": [rng(0, 0, 0, 0), rng(1, 255, 0.5, 1)]}, 0.75),
        # In a function: the registry's number.
        ({"default": 200, "caps": [rng(0, 127, 0, 1), fn(128, 255, "reverse")]}, 0.5),
    ],
)
def test_a_rate_starts_at_its_channels_default(speed: dict, value: float) -> None:
    compiled = compile_doc(effects_show(**speed))
    assert default_of(compiled, "effectRate") == pytest.approx(value)
    # The sound sensitivity is only a parameter: the registry's 0.
    assert default_of(compiled, "soundSensitivity") == 0.0


def test_scalars_that_do_not_follow_their_channel_keep_the_registry_default() -> None:
    frost = channel(1, "frost", default=255)
    doc = show([profile("p", mode([channel(0, "intensity"), frost]))], [fixture("f", 1, "p", 1)])
    assert default_of(compile_doc(doc), "frost") == 0.0
