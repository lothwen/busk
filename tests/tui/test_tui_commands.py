"""The lines the UI builds (``busk_tui.commands``): their format, their
performance marks, and the contract test: busk accepts every one of them on
the club-night show (plan §4.6)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, get_args, get_type_hints

import pytest

import busk
from busk.commands.record import POOL_FAMILIES
from busk.model.attributes import ATTRIBUTES
from busk.model.playback import ButtonFunction, FaderFunction, Playback
from busk.output import dmxusb
from busk_tui import attributes, commands, config
from busk_tui import bridge as bridge_module
from busk_tui.bridge import show_model
from busk_tui.commands import Line
from busk_tui.widgets import route_dialog
from busk_tui.widgets.chase_dialog import (
    DIRECTIONS,
    check_crossfade,
    check_multiplier,
    check_rate,
)
from busk_tui.widgets.cue_dialogs import CURVES, bezier_points, check_seconds, pair_words
from busk_tui.widgets.dialogs import check_cue, check_number, next_cue
from busk_tui.widgets.fixture_panel import CATEGORIES
from busk_tui.widgets.playback_panel import FADERS, FUNCTIONS, LTP_MODES, TOGGLES, TYPED
from busk_tui.widgets.route_dialog import network_line, usb_line
from busk_tui.widgets.template_panel import NEW_COLOUR, NEW_WAVE, WAVES

NEW_WAVE_JSON = (
    '[{"attribute": "intensity", "waveform": {"kind": "sine"}, '
    '"phaseOffset": 0.0, "mode": "multiply"}]'
)

TUPPER = Path(__file__).resolve().parents[2] / "examples" / "tupperdmx" / "tupper-demo.show"

OFL_DIMMER = {
    "name": "Test",
    "meta": {"lastModifyDate": "2026-01-02"},
    "availableChannels": {"Dimmer": {"capability": {"type": "Intensity"}}},
    "modes": [{"name": "All", "channels": ["Dimmer"]}],
}
"""An Open Fixture Library fixture: busk names it after its folder."""

ROUTE = "r-club"
"""The id the show of the contract test gives its route."""

BUILDERS: dict[str, tuple[Line, str, bool]] = {
    # name: (a line it builds, that line's text, whether busk runs it as a performance line)
    "help": (commands.help_(), "help", False),
    "undo": (commands.undo(), "undo", False),
    "redo": (commands.redo(), "redo", False),
    "save": (commands.save(), "save", False),
    "go": (commands.go(3), "go 3", True),
    "back": (commands.back(3), "back 3", True),
    "release": (commands.release(9), "release 9", True),
    "release_all": (commands.release_all(), "release all", True),
    "fader": (commands.fader(3, 0.72), "fader 3 72%", True),
    "flash on": (commands.flash(3, True), "flash 3 on", True),
    "flash off": (commands.flash(3, False), "flash 3 off", True),
    "button on": (commands.button(9, 1, True), "button 9 1 on", True),
    "button off": (commands.button(9, 1, False), "button 9 1 off", True),
    "gm": (commands.gm(0.8), "gm 80%", True),
    "master": (commands.master("Wash level", 0.4), 'master "Wash level" 40%', True),
    "blackout on": (commands.blackout(True), "blackout on", True),
    "blackout off": (commands.blackout(False), "blackout off", True),
    "output on": (commands.output(True), "output on", True),
    "output off": (commands.output(False), "output off", True),
    "tap": (commands.tap("Speed 1"), 'tap "Speed 1"', True),
    "bpm": (commands.bpm("Speed 1", 120.5), 'bpm "Speed 1" 120.5', True),
    "page next": (commands.page(1), "page next", True),
    "page prev": (commands.page(-1), "page prev", True),
    "sel group": (commands.sel_group(2), "sel group 2", False),
    "sel + group": (commands.sel_group(1, add=True), "sel + group 1", False),
    "preset": (commands.preset("color", 1), "preset color 1", False),
    "effect stop": (commands.effect_stop("fx5"), "effect stop fx5", False),
    "effect run": (commands.effect_run("fx5"), "effect run fx5", False),
    "effect remove": (commands.effect_remove("fx5"), "effect remove fx5", False),
    "effect stop, an id of two words": (
        commands.effect_stop("my fx"),
        'effect stop "my fx"',
        False,
    ),
    "effect run, an id of two words": (commands.effect_run("my fx"), 'effect run "my fx"', False),
    "effect remove, an id of two words": (
        commands.effect_remove("my fx"),
        'effect remove "my fx"',
        False,
    ),
    "effect add": (commands.effect_add("Chase"), 'effect add "Chase"', False),
    "effect replace": (
        commands.effect_replace("Circle", "fx5", ["hz 2", "reverse", "size 15"]),
        'effect add "Circle" id fx5 hz 2 reverse size 15',
        False,
    ),
    "effect replace, an id of two words": (
        commands.effect_replace("Circle", "my fx", ["hz 2"]),
        'effect add "Circle" id "my fx" hz 2',
        False,
    ),
    "effect clear": (commands.effect_clear(), "effect clear", False),
    "effect template add": (
        commands.effect_template_add("Beat", [NEW_WAVE]),
        f'effect template add "Beat" {NEW_WAVE_JSON}',
        False,
    ),
    "effect template update": (
        commands.effect_template_update("Beat", [NEW_WAVE]),
        f'effect template update "Beat" {NEW_WAVE_JSON}',
        False,
    ),
    "effect template rename": (
        commands.effect_template_rename("Beat", 'Say "hi"'),
        r'effect template rename "Beat" "Say \"hi\""',
        False,
    ),
    "effect template delete": (
        commands.effect_template_delete('Say "hi"'),
        r'effect template delete "Say \"hi\""',
        False,
    ),
    "rename playback": (
        commands.rename_playback(9, 'Say "hi"'),
        r'rename playback 9 "Say \"hi\""',
        False,
    ),
    "playback setting": (
        commands.playback_setting(9, "fader", "size"),
        "playback 9 fader size",
        False,
    ),
    "playback buttons": (
        commands.playback_buttons(9, ["go", "flash"]),
        'playback 9 buttons ["go", "flash"]',
        False,
    ),
    "page add": (commands.page_add(7, 'Say "hi"'), r'page add 7 "Say \"hi\""', False),
    "page add, no name": (commands.page_add(8), "page add 8", False),
    "rename page": (commands.rename_page(7, "Encore"), 'rename page 7 "Encore"', False),
    "go to a page": (commands.go_page(7), "page 7", True),
    "place a playback": (
        commands.place_playback(7, 2, 9),
        "page 7 slot 2 playback 9",
        False,
    ),
    "clear a slot": (commands.clear_slot(7, 2), "page 7 slot 2 clear", False),
    "playback add": (
        commands.playback_add(30, 9, 7, 3, 'Say "hi"'),
        r'playback add 30 cuelist 9 at 7.3 "Say \"hi\""',
        False,
    ),
    "playback add, no name": (
        commands.playback_add(31, 9, 8, 1),
        "playback add 31 cuelist 9 at 8.1",
        False,
    ),
    "delete playback": (commands.delete_playback(30), "delete playback 30 cascade", False),
    "delete page": (commands.delete_page(7), "delete page 7 cascade", False),
    "cue effect number": (
        commands.cue_effect(9, "4", "rainbow", "size", "0.5"),
        "cue 9/4 effect rainbow size 0.5",
        False,
    ),
    "cue effect word": (
        commands.cue_effect(9, "4", "rainbow", "direction", "bounce"),
        "cue 9/4 effect rainbow direction bounce",
        False,
    ),
    "cue effect rate in hz": (
        commands.cue_effect(9, "4", "rainbow", "rate", commands.rate_json("2", "", "1")),
        'cue 9/4 effect rainbow rate {"kind": "hz", "value": 2}',
        False,
    ),
    "cue effect phase": (
        commands.cue_effect(9, "4", "rainbow", "phase", commands.phase_json("-10", "20.5")),
        'cue 9/4 effect rainbow phase {"start": -10, "end": 20.5}',
        False,
    ),
    "cue effect remove": (
        commands.cue_effect_remove(9, "4", "rainbow"),
        "cue 9/4 effect rainbow remove",
        False,
    ),
    "sel targets": (
        commands.sel_targets("101 thru 102, 301.2"),
        "sel fixture 101 thru 102, fixture 301.2",
        False,
    ),
    "sel targets, one": (commands.sel_targets("101"), "sel fixture 101", False),
    "goto": (commands.goto(9, "3"), "goto 9 3", True),
    "record slot": (commands.record_slot(2, 7), "record slot 2.7", False),
    "record cue": (commands.record_cue(9), "record cue 9", False),
    "record cue at": (
        commands.record_cue(9, "2.5", name='The "Bridge"'),
        r'''record cue 9/2.5 "The \"Bridge\""''',
        False,
    ),
    "record cue at, busk names it": (commands.record_cue(9, "2.6"), "record cue 9/2.6", False),
    "record cue merge": (commands.record_cue(9, "2.5", "merge"), "record cue 9/2.5 merge", False),
    "record cue replace": (
        commands.record_cue(9, "2.5", "replace"),
        "record cue 9/2.5 replace",
        False,
    ),
    "record cue remove": (
        commands.record_cue(9, "2.5", "remove"),
        "record cue 9/2.5 remove",
        False,
    ),
    "delete cue": (commands.delete_cue(9, "2.6"), "delete cue 9/2.6", False),
    "cue release": (
        commands.cue_release(9, "1", "group 1", ("pan", "tilt")),
        "cue 9/1 release group 1 only pan tilt",
        False,
    ),
    "cue release, every attribute": (
        commands.cue_release(9, "1", "101 thru 102, 201"),
        "cue 9/1 release 101 thru 102, 201",
        False,
    ),
    "cue time": (commands.cue_time(9, "1", "1/3"), "cue 9/1 time 1/3", False),
    "cue time delay": (
        commands.cue_time(9, "1", "1/3", delay="0/1"),
        "cue 9/1 time 1/3 delay 0/1",
        False,
    ),
    "cue time curve": (
        commands.cue_time(9, "1", "1/3", curve="bezier 0.25 0.1 0.25 1"),
        "cue 9/1 time 1/3 bezier 0.25 0.1 0.25 1",
        False,
    ),
    "cue time, a family": (
        commands.cue_time(9, "1", "4", family="position", delay="1", curve="easeIn"),
        "cue 9/1 time position 4 delay 1 easeIn",
        False,
    ),
    "cue follow": (commands.cue_trigger(9, "2", "follow", "4"), "cue 9/2 follow 4", False),
    "cue wait": (commands.cue_trigger(9, "2", "wait", "0.5"), "cue 9/2 wait 0.5", False),
    "rename cue": (
        commands.rename_cue(9, "1", 'The "Intro"'),
        r'''rename cue 9/1 "The \"Intro\""''',
        False,
    ),
    "cuelist add": (
        commands.cuelist_add(30, 'The "Encore"'),
        r'''cuelist add 30 "The \"Encore\""''',
        False,
    ),
    "cuelist add, busk names it": (commands.cuelist_add(31), "cuelist add 31", False),
    "rename cuelist": (commands.rename_cuelist(30, "Encore"), 'rename cuelist 30 "Encore"', False),
    "cuelist tracking on": (commands.cuelist_tracking(30, True), "cuelist 30 tracking true", False),
    "cuelist tracking off": (
        commands.cuelist_tracking(30, False),
        "cuelist 30 tracking false",
        False,
    ),
    "chase hz": (
        commands.chase_settings(30, hz="0.125", direction="bounce", crossfade="0.5"),
        "cuelist 30 chase hz 0.125 bounce crossfade 0.5",
        False,
    ),
    "chase beat": (
        commands.chase_settings(30, multiplier="0.125", direction="random"),
        "cuelist 30 chase bpm x 0.125 random",
        False,
    ),
    "chase master": (
        commands.chase_settings(30, master="Speed 1", multiplier="2"),
        'cuelist 30 chase bpm "Speed 1" x 2 forward',
        False,
    ),
    "delete cuelist": (commands.delete_cuelist(30), "delete cuelist 30 cascade", False),
    "delete preset cascade": (
        commands.delete_preset("color", 4, cascade=True),
        "delete preset color 4 cascade",
        False,
    ),
    "cuelist chase": (commands.cuelist_chase(9), "cuelist 9 chase bpm x 1", False),
    "cuelist sequence": (commands.cuelist_sequence(10), "cuelist 10 sequence", False),
    "sel none": (commands.sel_none(), "sel none", False),
    "set level": (commands.set_level("intensity", 0.72), "set intensity 72%", False),
    "set component": (commands.set_level("color.r", 0.5), "set color.r 50%", False),
    "set degrees": (commands.set_number("pan", -45.0), "set pan -45", False),
    "set hz": (commands.set_number("strobeRate", 12.5), "set strobeRate 12.5", False),
    "set zoom": (commands.set_number("zoom", 20.0), "set zoom 20", False),
    "step up": (commands.step_level("intensity", 0.05), "set intensity by 5%", False),
    "step down": (commands.step_level("intensity", -0.02), "set intensity by -2%", False),
    "step component": (commands.step_level("color.w", 0.05), "set color.w by 5%", False),
    "step degrees": (commands.step_number("pan", -15.0), "set pan by -15", False),
    "step hz": (commands.step_number("strobeRate", 0.5), "set strobeRate by 0.5", False),
    "blind on": (commands.blind(True), "blind on", False),
    "blind off": (commands.blind(False), "blind off", False),
    "highlight on": (commands.highlight(True), "highlight on", False),
    "highlight off": (commands.highlight(False), "highlight off", False),
    "sel fixture": (commands.sel_fixture(101), "sel fixture 101", False),
    "sel + fixture": (commands.sel_fixture(102, add=True), "sel + fixture 102", False),
    "sel - fixture": (commands.sel_fixture(101, remove=True), "sel - fixture 101", False),
    "sel fixtures": (commands.sel_fixtures((201, 202)), "sel fixture 201, fixture 202", False),
    "sel + fixtures": (
        commands.sel_fixtures((203, 204), add=True),
        "sel + fixture 203, fixture 204",
        False,
    ),
    "sel heads": (commands.sel_fixtures((101, 102)), "sel fixture 101, fixture 102", False),
    "set color": (commands.set_color(1.0, 0.254, 0.0), "set color 1 0.25 0", False),
    "set option": (commands.set_option("gobo1", "breakup"), "set gobo1 breakup", False),
    "set spread": (commands.set_spread("pan", -30.0, 30.0), "set pan spread -30 30", False),
    "set spread center": (
        commands.set_spread("tilt", 10.0, 40.5, "center"),
        "set tilt spread 10 40.5 center",
        False,
    ),
    "set spread level": (
        commands.set_spread("intensity", 0.0, 1.0, "edges", level=True),
        "set intensity spread 0% 100% edges",
        False,
    ),
    "record preset": (
        commands.record_preset("color", 5, "global", name="Crimson"),
        'record preset color 5 global "Crimson"',
        False,
    ),
    "record preset merge": (
        commands.record_preset("color", 5, "target", "merge"),
        "record preset color 5 target merge",
        False,
    ),
    "record preset replace": (
        commands.record_preset("color", 5, "global", "replace"),
        "record preset color 5 global replace",
        False,
    ),
    "record preset remove": (
        commands.record_preset("color", 5, None, "remove"),
        "record preset color 5 remove",
        False,
    ),
    "rename preset": (
        commands.rename_preset("color", 5, "Scarlet"),
        'rename preset color 5 "Scarlet"',
        False,
    ),
    "renumber preset": (
        commands.renumber_preset("color", 5, 9),
        "preset color 5 number 9",
        False,
    ),
    "delete preset": (commands.delete_preset("color", 9), "delete preset color 9", False),
    # A group recorded from the heads, changed and taken away; values parked and let go.
    "record group": (commands.record_group(5, name="Floor"), 'record group 5 "Floor"', False),
    "record group unnamed": (commands.record_group(6), "record group 6", False),
    "record group merge": (commands.record_group(3, "merge"), "record group 3 merge", False),
    "record group remove": (commands.record_group(3, "remove"), "record group 3 remove", False),
    "record group replace": (commands.record_group(6, "replace"), "record group 6 replace", False),
    "rename group": (commands.rename_group(5, "Floor 2"), 'rename group 5 "Floor 2"', False),
    "renumber group": (commands.renumber_group(5, 7), "group 5 number 7", False),
    "delete group": (commands.delete_group(7), "delete group 7 cascade", False),
    "park": (
        commands.park("101 thru 102, 301.2", "intensity", "50%"),
        "park fixture 101 thru 102, fixture 301.2 intensity 50%",
        False,
    ),
    "park a colour": (
        commands.park("301.3 thru 301.5", "color", "1 0 0"),
        "park fixture 301.3 thru 301.5 color 1 0 0",
        False,
    ),
    "unpark": (commands.unpark("301.2", "intensity"), "unpark fixture 301.2 intensity", False),
    "unpark all": (commands.unpark_all(), "unpark all", False),
    "clear": (commands.clear(), "clear", False),
    # A universe, a rig in it and its routes, built up, changed and taken away.
    "universe add": (commands.universe_add(5, "Balcony"), 'universe add 5 "Balcony"', False),
    "universe add unnamed": (commands.universe_add(6), "universe add 6", False),
    "rename universe": (
        commands.rename_universe(5, "Roof"),
        'rename universe 5 "Roof"',
        False,
    ),
    "renumber universe": (commands.renumber_universe(5, 7), "universe 5 number 7", False),
    "fixture add": (
        commands.fixture_add(901, 903, "RGB Par 3ch", "3ch", (7, 1)),
        'fixture add 901 thru 903 "RGB Par 3ch" mode "3ch" at 7.1',
        False,
    ),
    "fixture add one": (
        commands.fixture_add(904, 904, "RGB Par 3ch", "3ch"),
        'fixture add 904 "RGB Par 3ch" mode "3ch"',
        False,
    ),
    "rename fixture": (commands.rename_fixture(904, "Spare"), 'rename fixture 904 "Spare"', False),
    "renumber fixture": (commands.renumber_fixture(904, 950), "fixture 904 number 950", False),
    "patch fixture": (commands.patch_fixture(950, (7, 100)), "fixture 950 patch 7.100", False),
    "unpatch fixture": (commands.patch_fixture(950, None), "fixture 950 patch none", False),
    "patch run": (
        commands.patch_fixture(901, (7, 200), 902),
        "fixture 901 thru 902 patch 7.200",
        False,
    ),
    "unpatch run": (
        commands.patch_fixture(901, None, 902),
        "fixture 901 thru 902 patch none",
        False,
    ),
    "limit range": (
        commands.limit_range(101, 102, "pan", -180.0, 180.5),
        "fixture 101 thru 102 limits pan -180 180.5",
        False,
    ),
    "limit one": (
        commands.limit_range(201, 201, "tilt", -90.0, 10.0),
        "fixture 201 limits tilt -90 10",
        False,
    ),
    "limit intensity": (
        commands.limit_intensity(101, 102, 0.5),
        "fixture 101 thru 102 limits intensity 50%",
        False,
    ),
    "no limit": (commands.no_limit(101, 102, "pan"), "fixture 101 thru 102 limits pan none", False),
    "no limits": (commands.no_limits(101, 102), "fixture 101 thru 102 limits none", False),
    "invert pan": (
        commands.orientation(101, 101, "invertPan", True),
        "fixture 101 orientation.invertPan true",
        False,
    ),
    "keep tilt": (
        commands.orientation(101, 102, "invertTilt", False),
        "fixture 101 thru 102 orientation.invertTilt false",
        False,
    ),
    "pan offset": (
        commands.orientation(101, 102, "panOffset", 30.5),
        "fixture 101 thru 102 orientation.panOffset 30.5",
        False,
    ),
    "location": (
        commands.location(101, (1.5, -2.0, 4.25, 0.0, 0.0, 90.0)),
        'fixture 101 location {"x": 1.5, "y": -2, "z": 4.25, "rx": 0, "ry": 0, "rz": 90}',
        False,
    ),
    "no location": (commands.no_location(101), "fixture 101 location none", False),
    "fixture mode": (commands.fixture_mode(101, "16ch"), 'fixture 101 mode "16ch"', False),
    "fixture profile": (
        commands.fixture_profile(903, "Stairville MH-X25 LED Spot", "12-channel"),
        'fixture 903 profile "Stairville MH-X25 LED Spot" mode "12-channel"',
        False,
    ),
    "category": (
        commands.category("Generic Spot 16ch", "wash"),
        'profile "Generic Spot 16ch" category wash',
        False,
    ),
    "no category": (
        commands.category("Generic Spot 16ch", "none"),
        'profile "Generic Spot 16ch" category none',
        False,
    ),
    "route add sacn": (commands.route_add(7, "sacn", "7"), "route add 7 sacn 7", False),
    "route add sacn unicast": (
        commands.route_add(7, "sacn", "8", "unicast 10.0.0.50"),
        "route add 7 sacn 8 unicast 10.0.0.50",
        False,
    ),
    "route add artnet": (
        commands.route_add(7, "artnet", "0.0.1", "broadcast eth0"),
        "route add 7 artnet 0.0.1 broadcast eth0",
        False,
    ),
    "route add dmxusb": (
        commands.route_add(7, "dmxusb", "enttecPro", "/dev/ttyUSB7", hz=30.0),
        "route add 7 dmxusb enttecPro /dev/ttyUSB7 hz 30",
        False,
    ),
    "route change": (
        commands.route_change(ROUTE, 1, "sacn", "9", "unicast 10.0.0.9"),
        f"route {ROUTE} change 1 sacn 9 unicast 10.0.0.9",
        False,
    ),
    "route off": (commands.route_on(ROUTE, False), f"route {ROUTE} off", False),
    "route on": (commands.route_on(ROUTE, True), f"route {ROUTE} on", False),
    "delete route": (commands.delete_route(ROUTE), f"delete route {ROUTE}", False),
    "delete run": (commands.delete_fixture(902, 903), "delete fixture 902 thru 903 cascade", False),
    "delete fixture": (commands.delete_fixture(901), "delete fixture 901 cascade", False),
    "delete universe": (commands.delete_universe(7), "delete universe 7 cascade", False),
}

PREFILLS = (
    commands.set_prefill("intensity"),
    commands.set_prefill("color"),
    commands.set_prefill("shutter"),
    commands.FADE_PREFILL,
    commands.cue_prefill(9, "3", "time"),
    commands.cue_prefill(9, "3", "follow"),
    commands.cue_prefill(9, "3", "wait"),
    commands.cue_prefill(9, "3", "go"),
    commands.bind_prefill("nanoKONTROL2"),
    commands.feedback_prefill("nanoKONTROL2", "cc 1 0"),
    commands.pickup_prefill("nanoKONTROL2"),
)
"""Lines the UI puts in the prompt to finish."""

WHOLE_PREFILLS = (commands.unbind_prefill("nanoKONTROL2", "cc 1 0"),)
"""Pre-fills that are whole lines: Enter runs them."""

PERFORMANCE_WORDS = {
    "go", "back", "goto", "release", "fader", "flash", "toggle", "button", "gm", "master",
    "blackout", "tap", "bpm", "page", "output",
}  # fmt: skip
"""The first words of busk's performance lines (``LiveShow.execute``);
``master add``, ``page add`` and ``page P slot S …`` are edits."""


@pytest.fixture
def show(club_path: Path, tmp_path: Path) -> busk.OfflineShow:
    """A club-night show of the test's own, saved to a file of its own, its
    route under the id the builders name."""
    document, _ = busk.load_show(club_path)
    document = copy.deepcopy(document)
    document["output"]["routes"][0]["id"] = ROUTE
    return busk.OfflineShow(document, path=tmp_path / "club.show")


def test_levels_are_whole_percent() -> None:
    assert commands.percent(0.72) == "72%"
    assert commands.percent(0.004) == "0%"
    assert commands.percent(0.996) == "100%"
    assert commands.percent(1.5) == "100%"
    assert commands.percent(-0.2) == "0%"


def test_names_are_quoted_with_jsons_escapes() -> None:
    assert commands.quoted("Grand Master") == '"Grand Master"'
    assert commands.quoted('Say "hi"') == r'''"Say \"hi\""'''
    assert commands.quoted("back\\slash") == r'''"back\\slash"'''
    assert commands.quoted("Jardín ✨") == '"Jardín ✨"'


@pytest.mark.parametrize(
    "name",
    ['say "hi"', "back\\slash", r"C:\new", "tab\there", "Jardín", "✨ Foyer", "\\", '"'],
)
def test_a_name_comes_back_from_busk_as_it_was_typed(show: busk.OfflineShow, name: str) -> None:
    """``\\n`` as typed is a backslash and an ``n``, not a new line."""
    assert show.expected(commands.rename_universe(1, name).text).error is None
    reply = show.execute(commands.rename_universe(1, name).text)
    assert reply.ok, reply.text
    assert show.show["universes"][0]["name"] == name


def test_a_word_is_bare_when_it_can_be() -> None:
    assert commands.word("eth0") == "eth0"
    assert commands.word("/dev/ttyUSB0") == "/dev/ttyUSB0"
    assert commands.word("a#b") == "a#b"
    assert commands.word("Ethernet 2") == '"Ethernet 2"'
    assert commands.word("#b") == '"#b"'
    assert commands.word("a,b") == '"a,b"'
    assert commands.word('a"b') == r'''"a\"b"'''
    assert commands.word("") == '""'


@pytest.mark.parametrize(
    "word",
    ["eth0", "10.0.0.50", "fe80::1%eth0", "a#b", "Ethernet 2", "#b", "a,b", 'a"b', "back\\slash"],
)
def test_a_word_comes_back_from_busk_as_it_was_typed(show: busk.OfflineShow, word: str) -> None:
    reply = show.execute(f"route add 1 sacn 3 unicast {commands.word(word)}")
    assert reply.ok, reply.text
    assert show.show["output"]["routes"][-1]["destination"]["host"] == word


def test_a_route_id_that_is_more_than_a_word_reaches_busk(club_path: Path) -> None:
    """A show written by hand may hold any id."""
    document, _ = busk.load_show(club_path)
    document = copy.deepcopy(document)
    document["output"]["routes"][0]["id"] = "main out"
    show = busk.OfflineShow(document)
    assert show.execute(commands.route_on("main out", False).text).ok
    assert not show.show["output"]["routes"][0]["enabled"]
    assert show.execute(commands.route_change("main out", 1, "sacn", "9").text).ok
    assert show.show["output"]["routes"][0]["universe"] == 9
    assert show.execute(commands.delete_route("main out").text).ok
    assert show.show["output"]["routes"] == []


def test_numbers_have_two_decimals_at_most() -> None:
    assert commands.number(120.0) == "120"
    assert commands.number(120.456) == "120.46"
    assert commands.number(99.5) == "99.5"
    assert commands.number(0.004) == "0"
    assert commands.number(-0.5) == "-0.5"


@pytest.mark.parametrize("value", [1_000_000.0, -123456.7, 1234567.5, 10.0**20])
def test_a_large_number_reaches_busk_as_typed(show: busk.OfflineShow, value: float) -> None:
    """Every digit, no exponent, nothing rounded but past two decimals."""
    text = commands.number(value)
    assert float(text) == value
    assert show.execute(commands.orientation(101, 101, "panOffset", value).text).ok
    assert show.execute(commands.limit_range(101, 101, "pan", value, value + 1).text).ok
    assert show.execute(commands.location(101, [value] * 6).text).ok
    fixture = next(f for f in show.show["fixtures"] if f["number"] == 101)
    assert fixture["orientation"]["panOffset"] == value
    assert list(fixture["limits"]["pan"]) == [value, value + 1]
    assert fixture["location"]["x"] == value


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_each_builder_is_marked_as_busk_runs_it(name: str) -> None:
    line, text, performance = BUILDERS[name]
    assert line.text == text
    assert line.performance is performance
    words = line.text.split()
    edit = words[0] == "page" and (words[1] == "add" or "slot" in words)
    assert (words[0] in PERFORMANCE_WORDS and not edit) is performance


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (120.0, "120"),
        (0.0, "0"),
        (-0.5, "-0.5"),
        (1e-05, "0.00001"),
        (1e22, "10000000000000000000000"),
        (0.1234567891, "0.1234567891"),
    ],
)
def test_exact_writes_every_digit_and_no_exponent(value: float, text: str) -> None:
    assert commands.exact(value) == text
    assert float(commands.exact(value)) == value


def test_the_beat_rate_as_a_cue_effect_takes_it() -> None:
    assert commands.rate_json(None, "m-1", "0.5") == (
        '{"kind": "bpm", "masterId": "m-1", "multiplier": 0.5}'
    )


def test_the_press_of_a_select_button_is_a_programmer_line(show: busk.OfflineShow) -> None:
    """busk runs it as ``SELECT_PLAYBACK``, not as a performance line, so the
    UI keeps it in order with the other programmer lines."""
    line = commands.button(9, 1, True, programmer=True)
    assert (line.text, line.performance) == ("button 9 1 on", False)
    assert show.execute('playback 9 buttons ["select"]').ok
    reply = show.execute(line.text)
    assert reply.ok, reply.text
    assert "selected" in reply.text


def test_a_rate_in_words() -> None:
    assert commands.effect_rate("2", None, "1") == "hz 2"
    assert commands.effect_rate(None, None, "0.5") == "bpm x 0.5"
    assert commands.effect_rate(None, "Speed 2", "2") == 'bpm "Speed 2" x 2'


SAME_MODE = "error: fixture 101 already runs 16ch"
"""busk's reply to the table's ``fixture mode``: the club's profiles have a
mode each, so the line names the one 101 runs. busk reads it and finds the
mode, then refuses a line that changes nothing."""


def test_busk_accepts_every_builders_line(show: busk.OfflineShow) -> None:
    """With the heads selected, holding a colour (for its components and
    ``by``), and two effects to stop, one with an id of two words; in the
    table's order (a preset is recorded, merged into, replaced, removed from,
    renamed, renumbered and deleted, and a universe and its rig likewise),
    ``sel none`` last."""
    assert show.execute("sel group 1").ok  # something to undo and redo, an effect to stop
    assert show.execute('effect add "Circle" id fx5').ok
    assert show.execute('effect add "Circle" id "my fx"').ok
    assert show.execute("preset color 2").ok
    for name, (line, _, _) in sorted(BUILDERS.items(), key=lambda item: item[0] == "sel none"):
        reply = show.execute(line.text)
        if name == "fixture mode":
            assert reply.text == SAME_MODE
            continue
        assert reply.ok, (name, reply.text)
    assert 7 not in [universe["number"] for universe in show.show["universes"]]
    assert show.show["output"]["routes"] == []  # the club's, and the ones on universe 7
    assert {901, 902, 903}.isdisjoint(fixture["number"] for fixture in show.show["fixtures"])


ROUTE_FORM: dict[str, tuple[Line, str, dict[str, Any]]] = {
    # name: (the form's line, its text, what busk stores of it)
    "sacn": (
        network_line(2, "sacn", "20", "multicast", ""),
        "route add 2 sacn 20",
        {"universe": 20, "destination": {"kind": "multicast", "iface": "eth0"}},
    ),
    "sacn multicast": (
        network_line(2, "sacn", "20", "multicast", "eth1"),
        "route add 2 sacn 20 multicast eth1",
        {"universe": 20, "destination": {"kind": "multicast", "iface": "eth1"}},
    ),
    "sacn multicast, an interface of two words": (
        network_line(2, "sacn", "20", "multicast", "Ethernet 2"),
        'route add 2 sacn 20 multicast "Ethernet 2"',
        {"universe": 20, "destination": {"kind": "multicast", "iface": "Ethernet 2"}},
    ),
    "sacn unicast": (
        network_line(2, "sacn", "20", "unicast", "10.0.0.50"),
        "route add 2 sacn 20 unicast 10.0.0.50",
        {"universe": 20, "destination": {"kind": "unicast", "host": "10.0.0.50"}},
    ),
    "artnet": (
        network_line(2, "artnet", "0.1.2", "broadcast", ""),
        "route add 2 artnet 0.1.2",
        {
            "portAddress": {"net": 0, "subNet": 1, "universe": 2},
            "destination": {"kind": "broadcast", "iface": "eth0"},
        },
    ),
    "artnet broadcast": (
        network_line(2, "artnet", "0.1.2", "broadcast", "eth1"),
        "route add 2 artnet 0.1.2 broadcast eth1",
        {"destination": {"kind": "broadcast", "iface": "eth1"}},
    ),
    "artnet unicast": (
        network_line(2, "artnet", "0.1.2", "unicast", "10.0.0.50"),
        "route add 2 artnet 0.1.2 unicast 10.0.0.50",
        {"destination": {"kind": "unicast", "host": "10.0.0.50"}},
    ),
    "enttecPro": (
        usb_line(2, "enttecPro", "/dev/ttyUSB3", 40.0),
        "route add 2 dmxusb enttecPro /dev/ttyUSB3 hz 40",
        {"device": {"driver": "enttecPro", "port": "/dev/ttyUSB3"}, "refreshHz": 40.0},
    ),
    "dmxking, a port of two words": (
        usb_line(2, "dmxking", "USB port", 30.5),
        'route add 2 dmxusb dmxking "USB port" hz 30.5',
        {"device": {"driver": "dmxking", "port": "USB port"}, "refreshHz": 30.5},
    ),
}


@pytest.mark.parametrize("name", sorted(ROUTE_FORM))
def test_busk_stores_what_the_route_form_says(show: busk.OfflineShow, name: str) -> None:
    line, text, stored = ROUTE_FORM[name]
    assert line.text == text
    assert not line.performance
    assert show.execute("universe add 2").ok
    reply = show.execute(line.text)
    assert reply.ok, reply.text
    route = show.show["output"]["routes"][-1]
    assert {key: route[key] for key in stored} == stored
    assert route["enabled"]


EDIT_FORM: dict[str, tuple[Line, str, dict[str, Any]]] = {
    # name: (the edit form's line for the club's route, its text, what busk stores of it)
    "sacn": (
        network_line(1, "sacn", "20", "multicast", "eth1", ROUTE),
        f"route {ROUTE} change 1 sacn 20 multicast eth1",
        {"protocol": "sacn", "universe": 20, "priority": 100,
         "destination": {"kind": "multicast", "iface": "eth1"}},
    ),
    "artnet": (
        network_line(1, "artnet", "0.1.2", "unicast", "10.0.0.50", ROUTE),
        f"route {ROUTE} change 1 artnet 0.1.2 unicast 10.0.0.50",
        {"protocol": "artnet", "portAddress": {"net": 0, "subNet": 1, "universe": 2},
         "destination": {"kind": "unicast", "host": "10.0.0.50"}},
    ),
    "dmxusb": (
        usb_line(1, "dmxking", "USB port", 30.5, ROUTE),
        f'route {ROUTE} change 1 dmxusb dmxking "USB port" hz 30.5',
        {"protocol": "dmxUsb", "device": {"driver": "dmxking", "port": "USB port"},
         "refreshHz": 30.5},
    ),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(EDIT_FORM))
def test_busk_changes_the_route_as_the_edit_form_says(show: busk.OfflineShow, name: str) -> None:
    """The route keeps its id, its place and whether it is on; another
    protocol leaves none of the old one's keys."""
    line, text, stored = EDIT_FORM[name]
    assert line.text == text
    assert not line.performance
    (before,) = show.show["output"]["routes"]
    reply = show.execute(line.text)
    assert reply.ok, reply.text
    (route,) = show.show["output"]["routes"]
    assert {key: route[key] for key in stored} == stored
    assert (route["id"], route["enabled"]) == (ROUTE, before["enabled"])
    keys = {"id", "universeId", "enabled", "protocol"}
    assert set(route) == keys | set(stored)


def test_the_form_reads_the_protocol_as_the_bridge_names_it() -> None:
    assert {
        name: key.lower() for key, name in bridge_module._PROTOCOLS.items()
    } == route_dialog.KEYS
    assert set(route_dialog.KEYS.values()) == set(route_dialog.PROTOCOLS)


@pytest.mark.parametrize(
    "text",
    [
        "1", "63999", " 7 ", "\u0663", "0", "64000", "-1", "1.5", "", "x", "²",
        pytest.param("7" * 5000, id="past-int"),
    ],
)  # fmt: skip
def test_the_route_form_and_busk_agree_on_an_sacn_universe(
    show: busk.OfflineShow, text: str
) -> None:
    """On universe 1, whose own route is the only one: no sACN universe is
    taken by another. To a host, so that no line is a copy of that route."""
    passes = route_dialog.check_sacn(text) is None
    assert passes is show.execute(f"route add 1 sacn {text.strip()} unicast 10.0.0.50").ok


@pytest.mark.parametrize(
    "text",
    [
        "0.0.0", "127.15.15", " 0.1.2 ", "\u0660.\u0660.\u0660", "128.0.0", "0.16.0", "0.0.16",
        "0.0", "0.0.0.0", "a.b.c", "0.0.", "0.0.-1", "0.0.²", "",
        pytest.param("0.0." + "7" * 5000, id="past-int"),
    ],
)  # fmt: skip
def test_the_route_form_and_busk_agree_on_a_port_address(show: busk.OfflineShow, text: str) -> None:
    passes = route_dialog.check_artnet(text) is None
    assert passes is show.execute(f"route add 1 artnet {text.strip()}").ok


@pytest.mark.parametrize("digits", [300, 301])
def test_a_number_dialog_and_busk_agree_on_how_long_a_number_runs(
    show: busk.OfflineShow, digits: int
) -> None:
    """The TUI has its own copy of busk's limit: busk's is not public."""
    number = "7" * digits
    passes = check_number((), None)(number) is None
    assert passes is show.execute(f"fixture 101 number {number}").ok


@pytest.mark.parametrize(
    ("universe", "address"),
    [
        (1, "0.0.0"), (2, "0.0.1"), (16, "0.0.15"), (17, "0.1.0"), (256, "0.15.15"),
        (257, "1.0.0"), (32768, "127.15.15"), (32769, "0.0.0"),
    ],
)  # fmt: skip
def test_art_net_counts_a_show_universe_from_0(universe: int, address: str) -> None:
    assert route_dialog.artnet_address(universe) == address
    assert route_dialog.check_artnet(address) is None


def test_the_route_form_starts_the_tupperdmx_show_where_its_route_is() -> None:
    document, _ = busk.load_show(TUPPER)
    (route,) = document["output"]["routes"]
    port = route["portAddress"]
    address = f"{port['net']}.{port['subNet']}.{port['universe']}"
    assert route_dialog.artnet_address(document["universes"][0]["number"]) == address


def test_the_route_forms_rates_are_what_a_widget_runs_at(show: busk.OfflineShow) -> None:
    """The form and busk take the same rates: those a widget runs at."""
    low, high = route_dialog.MIN_RATE, route_dialog.MAX_RATE
    assert dmxusb.output_rate(low) == low
    assert dmxusb.output_rate(high) == high
    assert dmxusb.output_rate(low - 1) == low
    assert dmxusb.output_rate(high + 1) == high
    assert route_dialog.check_rate(route_dialog.RATE) is None
    for text in ("1", "40", "30.5", " 25 "):
        assert route_dialog.check_rate(text) is None, text
    for text in ("0", "0.5", "40.5", "41", "-1", "", "x", "nan", "inf"):
        assert route_dialog.check_rate(text) is not None, text
    route = "route add 1 dmxusb enttecPro /dev/ttyUSB7 hz"
    for text in ("1", "40", "30.5"):
        assert show.execute(f"{route} {text}").ok, text
        assert show.execute("undo").ok
    for text in ("0", "0.5", "40.5", "41", "-1"):
        assert not show.execute(f"{route} {text}").ok, text


def test_the_route_forms_host_and_port_are_only_not_empty() -> None:
    assert route_dialog.check_host("10.0.0.50") is None
    assert route_dialog.check_port("/dev/ttyUSB0") is None
    for text in ("", "  "):
        assert route_dialog.check_host(text) is not None
        assert route_dialog.check_port(text) is not None


def test_busk_imports_the_file_at_the_path_the_picker_sends(
    show: busk.OfflineShow, tmp_path: Path
) -> None:
    """A path with a space, a quote and a backslash reaches busk whole."""
    folder = tmp_path / 'my "rig" \\ files' / "acme"
    folder.mkdir(parents=True)
    file = folder / "dim.json"
    file.write_text(json.dumps(OFL_DIMMER))
    line = commands.profile_import(str(file))
    assert line.text == f"profile import {json.dumps(str(file))}"
    assert not line.performance
    reply = show.execute(line.text)
    assert reply.ok, reply.text
    assert show.show["profiles"][-1]["name"] == "acme Test"


def test_busk_updates_the_profile_the_panel_names(club_path: Path) -> None:
    document, _ = busk.load_show(club_path)
    document = copy.deepcopy(document)
    document["profiles"][0]["revision"] = "7"
    show = busk.OfflineShow(document)
    line = commands.profile_update(document["profiles"][0]["name"])
    assert line.text == 'profile update "Generic Spot 16ch"'
    reply = show.execute(line.text)
    assert reply.ok, reply.text
    assert show.show["profiles"][0]["revision"] == "1"


def test_the_category_chips_are_what_busk_takes(club: busk.OfflineShow) -> None:
    words = club.expected('profile "Generic Spot 16ch" category ').words
    assert sorted(CATEGORIES) == sorted(words)


@pytest.mark.parametrize(
    "text", ["7", "2.5", "02", "2.50", "0", "2.", ".5", "1.2.3", "a", "-1", "²", "٣", "9" * 301]
)
def test_a_cue_form_and_busk_agree_on_a_cue_number(show: busk.OfflineShow, text: str) -> None:
    assert show.execute("sel group 1").ok
    assert show.execute("set intensity 50%").ok
    taken = [cue["number"] for cue in show.show["cueLists"][8]["cues"]]
    assert taken == ["1", "2", "3", "4", "5"]
    problem = check_cue(taken)(text)
    assert show.execute(f"record cue 9/{text}").ok is (problem is None), problem


def test_a_cue_form_says_what_comes_after_the_last_as_busk_does(show: busk.OfflineShow) -> None:
    assert show.execute("sel group 1").ok
    assert show.execute("set intensity 50%").ok
    assert show.execute("record cue 9/5.5").ok
    numbers = [cue["number"] for cue in show.show["cueLists"][8]["cues"]]
    assert show.execute("record cue 9").ok
    assert show.show["cueLists"][8]["cues"][-1]["number"] == next_cue(numbers) == "6"
    assert next_cue([]) == "1"


def test_the_chase_forms_words_are_busks(show: busk.OfflineShow) -> None:
    assert set(DIRECTIONS) <= set(show.expected("cuelist 9 chase hz 2 ").words)


@pytest.mark.parametrize("text", ["2", "0.125", ".5", "2.", "120"])
def test_what_the_chase_form_passes_as_a_rate_busk_takes(show: busk.OfflineShow, text: str) -> None:
    assert check_rate(text) is None
    assert check_multiplier(text) is None
    assert show.execute(f"cuelist 9 chase hz {text}").ok
    assert show.execute(f"cuelist 9 chase bpm x {text}").ok


@pytest.mark.parametrize("text", ["0", "-1", "abc", "", "9" * 301])
def test_a_rate_the_chase_form_refuses_busk_refuses_too(show: busk.OfflineShow, text: str) -> None:
    assert check_rate(text) is not None
    assert check_multiplier(text) is not None
    assert not show.execute(f"cuelist 9 chase hz {text}").ok


@pytest.mark.parametrize(("text", "ok"), [("0", True), ("1", True), ("0.25", True), ("1.5", False)])
def test_the_chase_form_and_busk_agree_on_a_crossfade(
    show: busk.OfflineShow, text: str, ok: bool
) -> None:
    assert (check_crossfade(text) is None) is ok
    assert show.execute(f"cuelist 9 chase hz 2 crossfade {text}").ok is ok


def test_the_timing_forms_words_are_busks(show: busk.OfflineShow) -> None:
    assert show.expected("cue 9/1 time ").words == attributes.TIMING_FAMILIES
    assert tuple(sorted(show.expected("cue 9/1 time 1 ").words, key=order)) == (*CURVES, "delay")


def order(word: str) -> int:
    """``delay`` after the curves, as the form has no chip for it."""
    return len(CURVES) if word == "delay" else CURVES.index(word)


@pytest.mark.parametrize(
    "text", ["0", "2", "0.125", ".5", "2.", "02", "-1", "-0", "+2", "1e3", "50%", "", "x"]
)
def test_a_time_form_and_busk_agree_on_seconds(show: busk.OfflineShow, text: str) -> None:
    """The forms take what busk takes for each time of a cue: its own, a
    family's fade and delay, and a trigger's delay."""
    ok = check_seconds(text) is None
    assert show.execute(f"cue 9/1 time {text}").ok is ok, text
    assert show.execute(f"cue 9/1 time {text}/{text} delay {text}/{text}").ok is ok, text
    assert show.execute(f"cue 9/1 time position {text} delay {text}").ok is ok, text
    assert show.execute(f"cue 9/1 follow {text}").ok is ok, text
    assert show.execute(f"cue 9/1 wait {text}").ok is ok, text


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("0.25 0.1 0.25 1", True),
        ("0 0 1 1", True),
        (".5 0 1. 1", True),
        ("0 0 1 1.5", False),
        ("-0 0 1 1", False),
        ("0 -0.5 1 1", False),
        ("0 0 1 +1", False),
        ("0 0 1 50%", False),
        ("0 0 1", False),
        ("0 0 1 1 1", False),
        ("a b c d", False),
    ],
)
def test_the_curve_form_and_busk_agree_on_bezier_points(
    show: busk.OfflineShow, text: str, ok: bool
) -> None:
    """A sign and a ``%`` too, in a cue's own curve and a family's."""
    assert (bezier_points(text) is not None) is ok
    assert show.execute(f"cue 9/1 time 1 bezier {text}").ok is ok, text
    assert show.execute(f"cue 9/1 time position 1 bezier {text}").ok is ok, text


def test_a_pair_of_times_keeps_every_digit_and_is_one_when_they_are_equal() -> None:
    assert commands.exact_pair(3.0, 3.0) == "3"
    assert commands.exact_pair(1.0, 3.0) == "1/3"
    assert commands.exact_pair(1.234567, 0.00001) == "1.234567/0.00001"
    assert pair_words(" 2 ", "2.0") == "2"
    assert pair_words("1", " 3 ") == "1/3"


def test_the_cue_timing_lines_do_what_they_say(show: busk.OfflineShow) -> None:
    def timing() -> Any:
        return show.show["cueLists"][8]["cues"][0]["timing"]

    def run(line: Line) -> None:
        reply = show.execute(line.text)
        assert reply.ok, (line.text, reply.text)

    run(commands.cue_time(9, "1", "1/3", delay="0.5/2", curve="easeIn"))
    run(commands.cue_time(9, "1", "4/6"))  # the delay and the curve stay
    assert (timing()["fadeIn"], timing()["fadeOut"]) == (4, 6)
    assert (timing()["delayIn"], timing()["delayOut"], timing()["curve"]) == (0.5, 2, "easeIn")
    run(commands.cue_time(9, "1", "2", family="position", delay="1", curve="snapEnd"))
    assert timing()["perFamily"]["position"] == {"fade": 2, "delay": 1, "curve": "snapEnd"}
    run(commands.cue_time(9, "1", "3", family="position"))  # set whole: the curve goes
    assert timing()["perFamily"]["position"] == {"fade": 3, "delay": 0}
    run(commands.cue_trigger(9, "1", "wait", "8"))
    assert show.show["cueLists"][8]["cues"][0]["trigger"] == {"kind": "wait", "delay": 8}
    run(commands.rename_cue(9, "1", "Fresh"))
    assert show.show["cueLists"][8]["cues"][0]["name"] == "Fresh"


def test_the_template_lines_do_what_they_say(show: busk.OfflineShow) -> None:
    def template(name: str) -> Any:
        return next(found for found in show.show["effects"] if found["name"] == name)

    def run(*lines: Line) -> None:
        for line in lines:
            reply = show.execute(line.text)
            assert reply.ok, (line.text, reply.text)

    run(commands.effect_template_add('Say "hi"', [NEW_WAVE]))
    assert template('Say "hi"')["layers"] == [NEW_WAVE]
    run(commands.effect_template_update('Say "hi"', [NEW_WAVE, NEW_COLOUR]))
    assert template('Say "hi"')["layers"] == [NEW_WAVE, NEW_COLOUR]
    run(commands.effect_template_rename('Say "hi"', "Fresh"))
    assert template("Fresh")["layers"] == [NEW_WAVE, NEW_COLOUR]
    run(commands.effect_template_delete("Fresh"))
    assert not any(found["name"] == "Fresh" for found in show.show["effects"])


def test_a_layer_with_a_number_of_every_digit_reaches_busk(show: busk.OfflineShow) -> None:
    layer = NEW_WAVE | {"waveform": {"kind": "square", "duty": 1e-7}, "phaseOffset": 1e22}
    assert show.execute(commands.effect_template_add("Tiny", [layer]).text).ok
    stored = next(found for found in show.show["effects"] if found["name"] == "Tiny")
    assert stored["layers"] == [layer]


@pytest.mark.parametrize("kind", sorted(WAVES))
def test_every_waveform_as_the_panel_starts_it_is_one_busk_takes(
    show: busk.OfflineShow, kind: str
) -> None:
    layer = NEW_WAVE | {"waveform": {"kind": kind} | WAVES[kind]}
    assert show.execute(commands.effect_template_add("Wave of mine", [layer]).text).ok


def test_the_cue_and_list_lines_do_what_they_say(show: busk.OfflineShow) -> None:
    def cue_list(number: int) -> Any:
        return next(found for found in show.show["cueLists"] if found["number"] == number)

    def run(*lines: Line) -> None:
        for line in lines:
            reply = show.execute(line.text)
            assert reply.ok, (line.text, reply.text)

    assert show.execute("sel group 1").ok
    assert show.execute("set intensity 50%").ok
    run(commands.cuelist_add(30, "Encore"))
    assert (cue_list(30)["name"], cue_list(30)["cues"]) == ("Encore", [])
    run(commands.record_cue(30, "2.5", name="Bridge"))
    cue = cue_list(30)["cues"][0]
    assert (cue["number"], cue["name"], len(cue["entries"])) == ("2.5", "Bridge", 1)
    run(commands.cue_release(30, "2.5", "group 1", ("pan", "tilt")))
    release = cue_list(30)["cues"][0]["releases"][0]
    assert (release["targets"]["kind"], release["attributes"]) == ("group", ["pan", "tilt"])
    run(commands.record_cue(30, "2.5", "remove"))
    assert cue_list(30)["cues"][0]["entries"] == []
    run(commands.cuelist_tracking(30, True))
    assert cue_list(30)["tracking"] is True
    run(commands.chase_settings(30, hz="0.125", direction="bounce", crossfade="0.5"))
    assert cue_list(30)["mode"] == "chase"
    assert cue_list(30)["chase"]["rate"] == {"kind": "hz", "value": 0.125}
    assert (cue_list(30)["chase"]["direction"], cue_list(30)["chase"]["crossfade"]) == (
        "bounce",
        0.5,
    )
    run(commands.rename_cuelist(30, "Last"))
    assert cue_list(30)["name"] == "Last"
    run(commands.delete_cue(30, "2.5"))
    assert cue_list(30)["cues"] == []
    assert show.confirmation(commands.delete_cuelist(30).text) == 'Delete cue list 30 "Last"?'
    run(commands.delete_cuelist(30))
    assert 30 not in [found["number"] for found in show.show["cueLists"]]


def test_the_playback_panels_words_are_busks() -> None:
    assert get_args(FaderFunction.__value__) == FADERS
    assert set(get_args(ButtonFunction.__value__)) == set(FUNCTIONS)
    assert get_args(get_type_hints(Playback)["ltpFaderMode"]) == LTP_MODES


def test_the_playback_panels_lines_do_what_they_say(show: busk.OfflineShow) -> None:
    def stored() -> Any:
        return next(found for found in show.show["playbacks"] if found["number"] == 9)

    def run(line: Line) -> None:
        reply = show.execute(line.text)
        assert reply.ok, (line.text, reply.text)

    def setting(prop: str, value: str) -> None:
        run(commands.playback_setting(9, prop, value))

    run(commands.rename_playback(9, "Hymn"))
    assert stored()["name"] == "Hymn"
    run(commands.playback_buttons(9, FUNCTIONS))
    assert tuple(stored()["buttons"]) == FUNCTIONS
    run(commands.playback_buttons(9, []))
    assert stored()["buttons"] == []
    for word in FADERS:
        setting("fader", word)
        assert stored()["fader"] == word
    for word in LTP_MODES:
        setting("ltpFaderMode", word)
        assert stored()["ltpFaderMode"] == word
    for prop, _ in TOGGLES.values():
        keys = prop.split(".")
        for value, expected in (("false", False), ("true", True)):
            setting(prop, value)
            holder = stored()
            for key in keys:
                holder = holder[key]
            assert holder is expected
    setting("goto", "2")
    assert stored()["gotoCue"] == "2"
    setting("gotoCue", "none")
    assert "gotoCue" not in stored()
    setting("cuelist", "11")
    assert stored()["cueListId"] == next(
        found["id"] for found in show.show["cueLists"] if found["number"] == 11
    )
    setting("number", "30")
    assert [p["number"] for p in show.show["playbacks"] if p["name"] == "Hymn"] == [30]


@pytest.mark.parametrize(
    ("name", "text", "stored"),
    [
        ("band", "-5", -5),
        ("exclusive", "wash 1", "wash 1"),
        ("exclusive", "none", "none"),  # a key of that name, not its absence
        ("exclusive", "2", "2"),
        ("flash level", "14.3", 0.143),
        ("flash boost", "-3", -3),
        ("threshold", "100%", 1.0),
        ("release", "0.125", 0.125),
        ("colour", "#00ff80", "#00ff80"),
    ],
)
def test_busk_stores_what_a_playback_dialog_sends(
    show: busk.OfflineShow, name: str, text: str, stored: object
) -> None:
    typed = TYPED[name]
    assert typed.check(text) is None
    line = commands.playback_setting(9, typed.prop, typed.value(text))
    reply = show.execute(line.text)
    assert reply.ok, reply.text
    holder = next(found for found in show.show["playbacks"] if found["number"] == 9)
    for key in typed.prop.split("."):
        holder = holder[key]
    assert holder == stored


@pytest.mark.parametrize("name", sorted(name for name, typed in TYPED.items() if typed.optional))
def test_busk_takes_an_optional_setting_away(show: busk.OfflineShow, name: str) -> None:
    typed = TYPED[name]
    text = {"flash boost": "4", "colour": "#ff8000"}.get(name, "a key")
    assert show.execute(commands.playback_setting(9, typed.prop, typed.value(text)).text).ok
    drop = commands.playback_setting(9, typed.prop, "none")
    reply = show.execute(drop.text)
    assert reply.ok, reply.text
    holder = next(found for found in show.show["playbacks"] if found["number"] == 9)
    for key in typed.prop.split(".")[:-1]:
        holder = holder[key]
    assert typed.prop.split(".")[-1] not in holder


def test_no_prefill_builder_is_left_unused() -> None:
    """A control that went takes its pre-fill with it (F3's did)."""
    package = Path(commands.__file__).parent
    source = "".join(
        path.read_text() for path in package.rglob("*.py") if path.name != "commands.py"
    )
    names = [name for name in vars(commands) if name.endswith("_prefill")]
    assert [name for name in names if f"commands.{name}(" not in source] == []


def test_the_group_and_park_lines_do_what_they_say(show: busk.OfflineShow) -> None:
    """What the lines leave in the document: members by fixture and element
    (from 0), and the park list."""

    def members(number: int) -> list[tuple[int, int]]:
        group = next(g for g in show.show["groups"] if g["number"] == number)
        return [(numbers[m["fixtureId"]], m["element"]) for m in group["members"]]

    numbers = {fixture["id"]: fixture["number"] for fixture in show.show["fixtures"]}
    assert show.execute("sel fixture 301.2 thru 301.3, fixture 101").ok
    assert show.execute(commands.record_group(5, name="Mixed").text).ok
    assert members(5) == [(301, 1), (301, 2), (101, 0)]
    assert show.execute("sel fixture 201").ok
    assert show.execute(commands.record_group(5, "merge").text).ok
    assert members(5) == [(301, 1), (301, 2), (101, 0), (201, 0)]
    assert show.execute("sel fixture 301.3").ok
    assert show.execute(commands.record_group(5, "remove").text).ok
    assert members(5) == [(301, 1), (101, 0), (201, 0)]
    assert show.execute(commands.record_group(5, "replace").text).ok
    assert members(5) == [(301, 2)]
    assert show.execute(commands.renumber_group(5, 8).text).ok
    assert show.execute(commands.rename_group(8, 'The "bar"').text).ok
    assert [(g["number"], g["name"]) for g in show.show["groups"]][-1] == (8, 'The "bar"')
    assert show.execute(commands.delete_group(8).text).ok
    assert [g["number"] for g in show.show["groups"]] == [1, 2, 3, 4]
    assert show.execute(commands.park("301.2 thru 301.3", "color", "0 0 1").text).ok
    assert show.execute(commands.park("102", "pan", "-45").text).ok
    park = [(numbers[e["slot"]["target"]["fixtureId"]], e["slot"]["target"]["element"],
             e["slot"]["attribute"], e["value"]) for e in show.show["park"]]  # fmt: skip
    assert park == [  # the club's two first
        (204, 0, "intensity", 0.0),
        (203, 0, "color", {"r": 1.0, "g": 0.0, "b": 0.0}),
        (301, 1, "color", {"r": 0.0, "g": 0.0, "b": 1.0}),
        (301, 2, "color", {"r": 0.0, "g": 0.0, "b": 1.0}),
        (102, 0, "pan", -45.0),
    ]
    assert show.execute(commands.unpark("301.2 thru 301.3", "color").text).ok
    assert len(show.show["park"]) == 3
    assert show.execute(commands.unpark_all().text).ok
    assert show.show["park"] == []


def test_the_rig_lines_do_what_they_say(show: busk.OfflineShow) -> None:
    """What the lines leave in the document: the show's own keys, by name."""
    for line in (
        commands.limit_range(101, 101, "pan", -180.0, 180.0),
        commands.limit_intensity(101, 101, 0.5),
        commands.no_limit(101, 101, "tilt"),
        commands.orientation(101, 101, "invertPan", True),
        commands.orientation(101, 102, "tiltOffset", 15.0),
        commands.location(101, (1.5, -2.0, 4.25, 0.0, 0.0, 90.0)),
        commands.category("Generic Spot 16ch", "wash"),
    ):
        reply = show.execute(line.text)
        assert reply.ok, (line, reply.text)
    fixture = next(f for f in show.show["fixtures"] if f["number"] == 101)
    assert fixture["limits"] == {"pan": (-180.0, 180.0), "intensityMax": 0.5}
    assert fixture["orientation"]["invertPan"] is True
    assert fixture["orientation"]["tiltOffset"] == 15.0
    assert show.show["fixtures"][1]["orientation"]["tiltOffset"] == 15.0
    assert fixture["location"] == {"x": 1.5, "y": -2, "z": 4.25, "rx": 0, "ry": 0, "rz": 90}
    assert show.show["profiles"][0]["category"] == "wash"
    assert show.execute(commands.no_location(101).text).ok
    assert show.execute(commands.no_limits(101, 101).text).ok
    fixture = next(f for f in show.show["fixtures"] if f["number"] == 101)
    assert "location" not in fixture
    assert "limits" not in fixture


def test_the_prefills_are_lines_busk_takes_so_far(show: busk.OfflineShow) -> None:
    assert show.execute("sel group 1").ok
    for line in PREFILLS:
        answer = show.expected(line)
        assert answer.error is None, (line, answer.error)
        assert answer.words or answer.values, line


def test_the_default_quick_lines_run(show: busk.OfflineShow) -> None:
    assert show.execute("sel group 4").ok
    for line in config.QUICK:
        reply = show.execute(line)
        assert reply.ok, (line, reply.text)


@pytest.mark.parametrize(
    ("attribute", "taken"),
    [("intensity", True), ("pan", True), ("tilt", True), ("zoom", True), ("shutter", True),
     ("strobeRate", True), ("iris", False), ("cto", False), ("focus", False)],
)  # fmt: skip
def test_the_heads_take_what_their_profile_says(
    show: busk.OfflineShow, attribute: str, taken: bool
) -> None:
    """The encoders' rows show by profile: the heads take these and refuse
    the others, as ``profile_info`` reads them."""
    assert show.execute("sel group 1").ok
    value = "strobe" if attribute == "shutter" else "0.5"
    assert show.execute(f"set {attribute} {value}").ok is taken


def test_the_whole_prefills_run(show: busk.OfflineShow) -> None:
    assert commands.location(101, (0.0,) * 6).text == (
        'fixture 101 location {"x": 0, "y": 0, "z": 0, "rx": 0, "ry": 0, "rz": 0}'
    )
    for line in WHOLE_PREFILLS:
        reply = show.execute(line)
        assert reply.ok, (line, reply.text)


def test_every_binding_of_the_show_unbinds_by_its_input(show: busk.OfflineShow) -> None:
    """F9's unbind pre-fill names a binding's input as busk reads it."""
    bindings = show_model(show.show).bindings
    assert len(bindings) > 50
    for binding in bindings:
        line = commands.unbind_prefill(binding.surface, binding.input)
        reply = show.execute(line)
        assert reply.ok, (line, reply.text)
    assert show.show["bindings"] == []


def test_the_families_are_busks() -> None:
    assert dict(attributes.FAMILY_OF) == {
        attribute: definition.family for attribute, definition in ATTRIBUTES.items()
    }
    assert attributes.family_of("color.w") == "color"
    assert attributes.family_of("nothing") is None


def test_the_pools_record_busks_families() -> None:
    assert dict(attributes.POOL_FAMILIES) == dict(POOL_FAMILIES)
    assert sorted(attributes.POOLS) == sorted(POOL_FAMILIES)
    assert sorted(attributes.DEFAULT_SCOPE) == sorted(POOL_FAMILIES)


UNITS = {"normalized": "level", "degrees": "degrees", "hz": "hz", "degPerSec": "degps"}


def test_every_scalar_has_a_row_and_every_discrete_attribute_options() -> None:
    """The PRESET panel's rows: a bar for each of busk's scalars, in its unit
    and under its family; options for each discrete attribute but
    ``control``, in registry order."""
    rows = {
        encoder.attribute: (family, encoder.unit)
        for family, encoders in attributes.ROWS
        for encoder in encoders
    }
    for attribute, definition in ATTRIBUTES.items():
        if definition.kind == "scalar":
            assert rows[attribute] == (definition.family, UNITS[definition.unit]), attribute
    assert all(attributes.family_of(name) == family for name, (family, _) in rows.items())
    discrete = [
        attribute
        for attribute, definition in ATTRIBUTES.items()
        if definition.kind == "discrete" and definition.family != "control"
    ]
    assert list(attributes.DISCRETE) == discrete
    assert all(
        attributes.family_of(attribute) == family
        for family, found in attributes.OPTIONS
        for attribute in found
    )


def test_f2_keeps_its_rows() -> None:
    assert [
        (family, [encoder.attribute for encoder in encoders])
        for family, encoders in attributes.FAMILIES
    ] == [
        ("intensity", ["intensity"]),
        ("position", ["pan", "tilt"]),
        ("color", ["color.r", "color.g", "color.b", "color.w", "cto"]),
        ("beam", ["zoom", "iris", "frost"]),
        ("focus", ["focus"]),
        ("shutter", ["strobeRate"]),
    ]


def test_each_scope_keeps_what_the_panels_hint_says(club_path: Path) -> None:
    """``preset_panel.KEEPS``: a global value reaches fixtures it was not
    recorded on, a profile value its profile's, a target value only its own;
    values that differ fall back to a narrower scope."""
    document, _ = busk.load_show(club_path)
    show = busk.OfflineShow(document)

    def run(*lines: str) -> busk.Reply:
        replies = [show.execute(line) for line in lines]
        return replies[-1]

    def applies(fixture: int, preset: str) -> bool:
        reply = run("clear", f"sel fixture {fixture}", f"preset {preset}")
        run("clear")
        return reply.ok

    run("sel fixture 201", "set color 1 0 0", "record preset color 30 global", "clear")
    assert applies(101, "color 30")
    assert applies(301, "color 30")
    run("sel fixture 101", "set zoom 20", "record preset beam 30 profile", "clear")
    assert applies(102, "beam 30")
    assert not applies(201, "beam 30")
    run("sel fixture 101", "set pan 10", "record preset position 30 target", "clear")
    assert applies(101, "position 30")
    assert not applies(102, "position 30")
    differ = run(
        "sel fixture 201", "set color 1 0 0", "sel fixture 202", "set color 0 1 0",
        "record preset color 31 global",
    )  # fmt: skip
    assert "2 target values (values differ)" in differ.text
    run("clear")


def test_busk_records_each_pool_at_the_default_scope(club_path: Path) -> None:
    """A record line without a scope: busk stores the values at the scope
    ``DEFAULT_SCOPE`` says. The heads get a focus channel for the focus
    pool (no profile of the show has one)."""
    document, _ = busk.load_show(club_path)
    document = copy.deepcopy(document)
    spot = next(p for p in document["profiles"] if p["name"] == "Generic Spot 16ch")
    for mode in spot["modes"]:
        for channel in mode["channels"]:
            if channel.get("component") == "white":
                del channel["component"]
                channel["attribute"] = "focus"
    show = busk.OfflineShow(document)
    for line in ("sel group 1", "set intensity 50%", "set pan 10", "set color 1 0 0",
                 "set zoom 20", "set focus 50%"):  # fmt: skip
        assert show.execute(line).ok, line
    for number, pool in enumerate(attributes.POOLS, start=11):
        reply = show.execute(f"record preset {pool} {number}")
        assert reply.ok, (pool, reply.text)
        stored = next(p for p in show.show["presets"] if (p["pool"], p["number"]) == (pool, number))
        assert {value["scope"]["kind"] for value in stored["values"]} == {
            attributes.DEFAULT_SCOPE[pool]
        }, pool
