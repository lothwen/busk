"""The output readout: the engine's output per fixture element (GAP-01 of
``docs/dev/tui/engine-gaps.md``).

``OfflineShow.output`` and ``LiveShow.output`` read the logical frame the
safety stage left (stage 11) back per fixture element: intensity, colour,
pan, tilt and zoom in the show's units, and what drives each family. The rig
here has one fixture of each kind the readout tells apart: a spot with a
colour wheel, an RGBW par, a four-cell bar on one master dimmer, and an
unpatched dimmer.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from builders import (
    Doc,
    channel,
    color,
    fixture,
    fn,
    grand_master,
    mode,
    profile,
    rng,
    show,
    show_of,
    slot,
)
from busk.compiler.compile import compile_show
from busk.compiler.readout import EMPTY_READOUT
from busk.engine.snapshot import FixtureOutput, OutputSnapshot
from busk.process.wire import engine_view
from busk.runner import LiveShow, OfflineShow


def readout_rig() -> Doc:
    """Fixtures 101 (spot), 201 (RGBW par), 301 (bar of four RGB cells, its
    dimmer on the first) and 401 (unpatched dimmer), listed out of number
    order; one page and a grand master."""
    wheel = {
        "id": "color1",
        "kind": "color",
        "slots": [
            {"id": "open", "name": "Open"},
            {"id": "red", "name": "Red", "color": {"r": 1, "g": 0, "b": 0}},
            {"id": "cyan", "name": "Cyan", "color": {"r": 0, "g": 1, "b": 1}},
            {"id": "uv", "name": "UV"},  # no colour in the profile
        ],
    }
    spot = profile(
        "p-spot",
        mode(
            [
                channel(0, "intensity"),
                channel(1, "pan", rng(0, 255, -270, 270)),
                channel(2, "tilt", rng(0, 255, -135, 135)),
                channel(3, "zoom", rng(0, 255, 10, 40)),
                channel(
                    4,
                    "colorWheel",
                    slot(0, 63, "open"),
                    slot(64, 127, "red"),
                    slot(128, 191, "cyan"),
                    slot(192, 255, "uv"),
                ),
                channel(5, "shutter", fn(0, 255, "open")),
            ]
        ),
        wheels=[wheel],
        physical={"zoomRange": [10, 40]},
    )
    par = profile(
        "p-par",
        mode(
            [
                channel(0, "intensity"),
                color(1, "red"),
                color(2, "green"),
                color(3, "blue"),
                color(4, "white"),
            ]
        ),
    )
    cells = [
        color(1 + 3 * cell + k, component, element=cell)
        for cell in range(4)
        for k, component in enumerate(("red", "green", "blue"))
    ]
    bar = profile("p-bar", mode([channel(0, "intensity"), *cells], elements=4))
    dimmer = profile("p-dim", mode([channel(0, "intensity")]))
    doc = show(
        [spot, par, bar, dimmer],
        [
            fixture("f-bar", 301, "p-bar", 20),
            fixture("f-spot", 101, "p-spot", 1),
            fixture("f-dim", 401, "p-dim", None),
            fixture("f-par", 201, "p-par", 10),
        ],
    )
    doc["pages"] = [{"id": "pg-1", "number": 1, "name": "Main", "slots": []}]
    doc["masters"] = [grand_master()]
    return doc


@pytest.fixture
def offline() -> OfflineShow:
    return OfflineShow(show_of(readout_rig()))


def run(show_: OfflineShow | LiveShow, *lines: str) -> None:
    for line in lines:
        reply = show_.execute(line)
        assert reply.ok, f"{line}: {reply.text}"


def of(output: OutputSnapshot, number: int, element: int = 1) -> FixtureOutput:
    """Element ``element`` of fixture ``number`` in ``output``."""
    return next(f for f in output.fixtures if (f.number, f.element) == (number, element))


def rounded(value: Any) -> Any:
    """``value`` with its floats rounded to 6 places (colours are products)."""
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, tuple):
        return tuple(rounded(v) for v in value)
    return value


# ------------------------------------------------------------------ the list


def test_every_element_is_listed_by_fixture_number_then_element(offline: OfflineShow) -> None:
    output = offline.output
    assert [(f.number, f.element) for f in output.fixtures] == [
        (101, 1),
        (201, 1),
        (301, 1),
        (301, 2),
        (301, 3),
        (301, 4),
        (401, 1),  # unpatched, still programmable
    ]
    frame = offline.tick(2.5)
    assert (offline.output.seq, offline.output.time) == (frame.seq, frame.time)


def test_nothing_driven_reads_the_defaults_and_none(offline: OfflineShow) -> None:
    spot = of(offline.output, 101)
    assert (spot.intensity, spot.color, spot.pan, spot.tilt, spot.zoom) == (
        0.0,
        (1.0, 1.0, 1.0),  # the wheel's open slot: white
        0.0,
        0.0,
        25.0,  # zoom's default: the middle of the profile's zoomRange
    )
    assert dict(spot.source) == {
        "intensity": "none",
        "position": "none",
        "color": "none",
        "beam": "none",
        "shutter": "none",
    }
    assert spot.playback is None
    dimmer = of(offline.output, 401)
    assert (dimmer.color, dimmer.pan, dimmer.tilt, dimmer.zoom) == (None, None, None, None)
    assert dict(dimmer.source) == {"intensity": "none"}


def test_the_output_is_made_once_per_tick(offline: OfflineShow) -> None:
    first = offline.output
    assert offline.output is first
    run(offline, "sel fixture 201", "set intensity 50%")  # a command ticks at the same time
    second = offline.output
    assert second is not first
    assert (second.seq, second.time) == (first.seq + 2, first.time)  # `sel` ticks too
    assert of(second, 201).intensity == 0.5


# ---------------------------------------------------------------- the values


def test_values_are_logical_in_the_shows_units(offline: OfflineShow) -> None:
    run(offline, "sel fixture 101", "set intensity 50%", "set pan 45")
    run(offline, "set tilt -30", "set zoom 12")
    spot = of(offline.output, 101)
    assert (spot.intensity, spot.pan, spot.tilt, spot.zoom) == (0.5, 45.0, -30.0, 12.0)


@pytest.mark.parametrize(
    ("wheel_slot", "expected"),
    [
        ("open", (1.0, 1.0, 1.0)),
        ("red", (1.0, 0.0, 0.0)),
        ("cyan", (0.0, 1.0, 1.0)),
        ("uv", (1.0, 1.0, 1.0)),  # the profile gives the slot no colour: no filter shown
    ],
)
def test_the_colour_wheel_filters_white(
    offline: OfflineShow, wheel_slot: str, expected: tuple[float, float, float]
) -> None:
    run(offline, "sel fixture 101", f"set colorWheel {wheel_slot}")
    assert of(offline.output, 101).color == expected


def test_the_colour_is_rgb_plus_an_explicit_white(offline: OfflineShow) -> None:
    run(offline, "sel fixture 201", "set color 0.2 0.4 0.6")  # white derived: the same light
    assert rounded(of(offline.output, 201).color) == (0.2, 0.4, 0.6)
    run(offline, "set color 1 0 0 w 0.5")
    assert of(offline.output, 201).color == (1.0, 0.5, 0.5)


def test_cells_without_a_dimmer_take_the_master_dimmer(offline: OfflineShow) -> None:
    run(offline, "sel fixture 301", "set intensity 40%", "sel 301.3", "set color 0 1 0")
    output = offline.output
    assert [of(output, 301, cell).intensity for cell in range(1, 5)] == [0.4] * 4
    assert [of(output, 301, cell).source["intensity"] for cell in range(1, 5)] == ["programmer"] * 4
    assert of(output, 301, 3).color == (0.0, 1.0, 0.0)
    assert of(output, 301, 2).source["color"] == "none"


# -------------------------------------------------------------- the drivers


def test_a_playback_drives_what_its_cue_holds(offline: OfflineShow) -> None:
    run(offline, "sel fixture 201", "set intensity 80%", "set color 1 0 0")
    run(offline, 'record slot 1 "Red"', "clear", "fader 1 100%")
    par = of(offline.output, 201)
    assert (par.intensity, par.color) == (0.8, (1.0, 0.0, 0.0))
    assert dict(par.source) == {"intensity": "playback", "color": "playback"}
    assert par.playback == 1
    run(offline, "sel fixture 201", "set color 0 0 1")  # the programmer on top
    par = of(offline.output, 201)
    assert dict(par.source) == {"intensity": "playback", "color": "programmer"}
    assert par.playback == 1  # the intensity is still the playback's


def test_an_effect_drives_and_names_its_playback(offline: OfflineShow) -> None:
    run(offline, "sel fixture 101", "set intensity 100%", 'effect add "Pulse"')
    run(offline, "record slot 2", "clear", "fader 2 100%")
    offline.tick(0.3)
    spot = of(offline.output, 101)
    assert spot.source["intensity"] == "effect"
    assert spot.playback == 2
    assert 0.0 < spot.intensity < 1.0
    run(offline, "sel fixture 101", 'effect add "Circle"')  # a programmer effect
    offline.tick(0.6)
    spot = of(offline.output, 101)
    assert spot.source["position"] == "effect"
    assert spot.pan != 0.0


def test_in_a_family_the_programmer_wins_then_an_effect_then_a_playback(
    offline: OfflineShow,
) -> None:
    run(offline, "sel fixture 101", "set pan 10", "set tilt 20", "record slot 1", "clear")
    run(offline, "fader 1 100%")
    assert of(offline.output, 101).source["position"] == "playback"
    run(offline, "sel fixture 101", 'effect add "Sweep"')  # moves pan only
    offline.tick(0.25)
    assert of(offline.output, 101).source["position"] == "effect"  # the playback holds tilt
    run(offline, "set tilt 30")  # the effect still moves pan
    assert of(offline.output, 101).source["position"] == "programmer"


# -------------------------------------------- masters and the safety stage


def test_masters_and_blackout_scale_the_intensity_not_its_driver(offline: OfflineShow) -> None:
    run(offline, "sel fixture 201", "set intensity 80%")
    run(offline, "gm 50%")
    par = of(offline.output, 201)
    assert (par.intensity, par.source["intensity"]) == (0.4, "programmer")
    run(offline, "blackout on")
    par = of(offline.output, 201)
    assert (par.intensity, par.source["intensity"]) == (0.0, "programmer")


def test_park_is_nobodys_and_limits_clamp(offline: OfflineShow) -> None:
    run(offline, "sel fixture 201", "set intensity 80%", "park fixture 201 intensity 30%")
    par = of(offline.output, 201)
    assert (par.intensity, par.source["intensity"], par.playback) == (0.3, "none", None)
    run(offline, "fixture 101 limits tilt -10 10", "sel fixture 101", "set tilt 40")
    spot = of(offline.output, 101)
    assert (spot.tilt, spot.source["position"]) == (10.0, "programmer")


def test_the_highlight_is_the_programmers(offline: OfflineShow) -> None:
    run(offline, "sel fixture 201", "set color 1 0 0", 'record slot 1 "Red"', "clear")
    run(offline, "fader 1 100%", "sel fixture 201", "highlight on")
    par = of(offline.output, 201)
    assert (par.intensity, par.color) == (1.0, (1.0, 1.0, 1.0))
    assert dict(par.source) == {"intensity": "programmer", "color": "programmer"}
    assert par.playback is None


# ------------------------------------------------------------- live edits


def test_a_live_edit_reads_with_the_rig_it_made(offline: OfflineShow) -> None:
    run(offline, 'fixture add 501 "RGB Par 3ch" mode 3ch at 1.100', "sel fixture 501")
    run(offline, "set color 0 0 1")
    added = of(offline.output, 501)
    assert (added.color, added.source["color"]) == ((0.0, 0.0, 1.0), "programmer")
    assert [f.number for f in offline.output.fixtures][-1] == 501


def test_the_readout_is_compiled_with_the_rig_and_left_out_of_the_engine_process() -> None:
    shown = show_of(readout_rig())
    compiled = compile_show(shown)
    assert compiled.readout.numbers == (101, 201, 301, 301, 301, 301, 401)
    again = compile_show({**shown, "groups": []}, compiled)  # the same rig lists
    assert again.readout is compiled.readout
    assert engine_view(compiled).readout is EMPTY_READOUT


# --------------------------------------------------------------- LiveShow


def test_a_live_show_captures_its_output_once_it_is_read() -> None:
    with LiveShow(show_of(readout_rig()), output=False) as live:
        run(live, "sel fixture 201", "set intensity 60%")
        time.sleep(0.2)
        engine = live._engine
        assert engine is not None
        assert engine.output is None  # nobody asked: no capture
        assert live.output is None  # the first read asks …
        deadline = time.monotonic() + 2.0
        while live.output is None and time.monotonic() < deadline:
            time.sleep(0.02)  # … and the engine's next tick captures
        output = live.output
        assert output is not None
        assert of(output, 201).intensity == 0.6
        time.sleep(0.1)
        frame = live.frame
        newer = live.output
        assert frame is not None
        assert newer is not None
        assert newer.seq > output.seq  # every tick from then on
        assert abs(newer.seq - frame.seq) <= 1
