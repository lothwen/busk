"""The bridge's conversion (``busk_tui.bridge``) of real busk objects, from an
:class:`busk.OfflineShow` of the club-night show: the playbacks of the
snapshot, the show model the pages use (profiles, fixtures with their patch,
preset summaries, cues as stored, effect settings, templates, bindings), the
routes and surfaces, the programmer's values and effects, the running
effects and the output with its sources."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

import busk
from busk_tui.bridge import (
    effects_model,
    fixture_info,
    live_state,
    output_model,
    profile_info,
    programmer_model,
    route_views,
    show_model,
    surface_views,
)
from busk_tui.model import (
    EffectInfo,
    ElementOutput,
    FixtureInfo,
    GroupInfo,
    HeldValue,
    MasterView,
    PageInfo,
    PlaybackView,
    ProfileInfo,
    StoredValue,
    Targets,
    TemplateInfo,
)


@pytest.fixture
def show(club_path: Path, tmp_path: Path) -> busk.OfflineShow:
    document, _ = busk.load_show(club_path)
    return busk.OfflineShow(document, path=tmp_path / "club.show")


def masters_by_id(show: busk.OfflineShow) -> dict[str, MasterView]:
    model = show_model(show.show)
    return {
        master["id"]: view for master, view in zip(show.show["masters"], model.masters, strict=True)
    }


def test_the_show_model_has_what_f1_and_f7_show(club: busk.OfflineShow) -> None:
    model = show_model(club.show)
    assert model.pages[0] == PageInfo(1, "Main", tuple(range(1, 14)))
    assert model.pages[1].slots == (14, 15, 16, 17, 19, 20, None, 18, 9, 10, 11, 12, 13)
    assert [p.number for p in model.playbacks] == list(range(1, 21))
    assert model.playback(9) is not None
    assert model.playback(9).cueList == 9
    song = model.cue_list(9)
    assert song is not None
    assert (song.mode, song.chase) == ("sequence", None)
    assert [cue.name for cue in song.cues] == ["Intro", "Verse", "Pre", "Chorus", "Outro"]
    chorus = song.cues[3]
    assert (chorus.number, chorus.name) == ("4", "Chorus")
    assert [(effect.id, effect.template) for effect in chorus.effects] == [("rainbow", "Rainbow")]
    chase = model.cue_list(10)
    assert chase is not None
    assert (chase.mode, chase.chase) == ("chase", "bpm x 1 bounce")
    assert model.masters == (
        MasterView("Grand Master", "grand", None, ()),
        MasterView("Speed 1", "speed", None, (0.25, 0.5, 1.0, 2.0, 4.0)),
        MasterView("FX", "size", None, ()),
        MasterView("Wash level", "group", GroupInfo(2, "Washes"), ()),
        MasterView("Fade", "fadeTime", None, ()),
    )
    assert [g.name for g in model.groups] == ["Heads", "Washes", "Bar", "All"]
    colors = [(p.number, p.name, p.color) for p in model.presets if p.pool == "color"]
    assert colors == [
        (1, "Blue", (0.0, 0.0, 1.0)),
        (2, "Red", (1.0, 0.0, 0.0)),
        (3, "Green", (0.0, 1.0, 0.0)),
        (4, "Amber", (1.0, 0.5, 0.0)),
    ]
    position = [p for p in model.presets if p.pool == "position"]
    assert [p.color for p in position] == [None, None]
    bar = FixtureInfo(
        301, 12, "COLORband PiX 301", "Chauvet DJ COLORband PiX", "36-CH", 36, (1, 49)
    )
    assert bar in model.fixtures
    assert (
        FixtureInfo(101, 1, "Spot 101", "Generic Spot 16ch", "16ch", 16, (1, 1)) in model.fixtures
    )


def test_a_chase_names_its_master_when_the_show_has_two(show: busk.OfflineShow) -> None:
    assert show.execute('master add speed "Speed 2" bpm 90').ok
    assert show.execute('cuelist 10 chase bpm "Speed 2" x 0.5 forward').ok
    assert show.execute("cuelist 1 chase hz 2.5 random").ok
    model = show_model(show.show)
    assert model.cue_list(10).chase == 'bpm "Speed 2" x 0.5 forward'  # type: ignore[union-attr]
    assert model.cue_list(1).chase == "hz 2.5 random"  # type: ignore[union-attr]


def test_a_ui_color_is_a_hex_colour_or_nothing(show: busk.OfflineShow) -> None:
    assert show.execute('playback 1 uiColor "#ff8000"').ok
    assert show.execute('playback 2 uiColor "orange"').ok
    model = show_model(show.show)
    assert model.playback(1).uiColor == (1.0, 128 / 255, 0.0)  # type: ignore[union-attr]
    assert model.playback(2).uiColor is None  # type: ignore[union-attr]


def test_a_colour_preset_with_white_and_one_mixed(show: busk.OfflineShow) -> None:
    assert show.execute("sel group 2").ok
    assert show.execute("set color 0.5 0 0 w 0.25").ok
    assert show.execute('record preset color 5 "Pink"').ok
    assert show.execute("sel fixture 201").ok
    assert show.execute("set color 1 0 0 w 0").ok
    assert show.execute("sel fixture 202").ok
    assert show.execute("set color 0 0 1 w 0").ok
    assert show.execute("sel fixture 201 thru 202").ok
    assert show.execute('record preset color 6 target "Two"').ok
    by_number = {p.number: p for p in show_model(show.show).presets if p.pool == "color"}
    assert by_number[5].color == (0.75, 0.25, 0.25)
    assert by_number[6].color is None


def test_the_playbacks_of_the_snapshot(show: busk.OfflineShow) -> None:
    for line in ("go 9", "fader 9 70%", "fader 10 50%", "go 10", "fader 18 40%", "flash 3 on"):
        assert show.execute(line).ok, line
    show.tick(0.1)
    state = live_state(show.snapshot, masters_by_id(show))
    assert [p.number for p in state.playbacks] == list(range(1, 21))
    song = state.playback(9)
    assert song == PlaybackView(
        number=9,
        name="Song",
        state="active",
        level=0.7,
        flash=False,
        fader="master",
        chase=False,
        cue="1",
        cueName="Intro",
        next="2",
        cueCount=5,
        progress=None,
        color=(0.0, 0.0, 1.0),
    )
    chase = state.playback(10)
    assert chase is not None
    assert chase.chase
    assert chase.cueCount == 4
    manual = state.playback(18)
    assert manual is not None
    assert (manual.fader, manual.progress) == ("crossfade", 0.4)
    assert state.playback(3).flash  # type: ignore[union-attr]
    assert state.playback(8).fader == "none"  # type: ignore[union-attr]
    assert state.playback(1).state == "idle"  # type: ignore[union-attr]


def test_the_programmer_lists_its_effects_and_the_stopped(show: busk.OfflineShow) -> None:
    assert show.execute("sel group 1").ok
    assert show.execute('effect add "Circle"').ok
    effect_id = show.programmer.effects[0]["id"]
    assert show.execute(f"effect stop {effect_id}").ok
    model = programmer_model(show.programmer, show.show)
    assert model.effects == (
        EffectInfo(
            effect_id,
            "Circle",
            Targets(elements=((101, 1), (102, 1))),
            rate="bpm x 1",
            size=20.0,
        ),
    )
    assert model.stopped == frozenset({effect_id})
    assert model.selection == ((101, 1), (102, 1))


def test_the_running_effects(show: busk.OfflineShow) -> None:
    assert show.execute("go 11").ok
    assert show.execute("fader 11 100%").ok
    _ = show.effects  # the first read turns the capture on
    show.tick(0.1)
    show.tick(0.2)
    model = effects_model(show.effects)
    (circle,) = model.effects
    assert (circle.playback, circle.cue, circle.id) == (11, "1", "fx1")
    assert len(circle.wave) == 20
    assert circle.colors == ()
    assert 0.0 < circle.presence <= 1.0


def test_what_each_profile_takes_and_its_ranges(club: busk.OfflineShow) -> None:
    profiles = {profile.name: profile for profile in show_model(club.show).profiles}
    spot = profiles["Generic Spot 16ch"]
    assert spot.attributes == frozenset(
        {"intensity", "pan", "tilt", "color", "color.w", "gobo1", "zoom", "shutter", "strobeRate"}
    )
    # panRange 540 and tiltRange 270 centred, zoomRange; no maxStrobeHz: the strobe range's
    assert spot.ranges == (
        ("pan", -270.0, 270.0),
        ("tilt", -135.0, 135.0),
        ("zoom", 12.0, 30.0),
        ("strobeRate", 1.0, 20.0),
    )
    par = profiles["Eurolite LED ML-56 RGBW"]  # dimmed virtually: no intensity channel
    assert par.attributes == frozenset({"intensity", "color", "color.w"})
    bar = profiles["Chauvet DJ COLORband PiX"]  # maxStrobeHz, but nothing takes a strobe rate
    assert bar == ProfileInfo(
        "Chauvet DJ COLORband PiX", frozenset({"intensity", "color"}), (), "pixel"
    )
    assert (spot.category, par.category) == ("spot", "par")


def test_a_profile_without_physical_ranges_uses_its_channels_else_the_defaults(
    club: busk.OfflineShow,
) -> None:
    spot = next(p for p in club.show["profiles"] if p["name"] == "Generic Spot 16ch")
    bare = {**spot, "physical": {}}
    assert profile_info(bare).range("pan") == (-270.0, 270.0)  # its pan channel spans these
    mode = {**spot["modes"][0], "channels": [
        {**channel, "capabilities": [{"kind": "function", "dmx": [0, 255], "fn": "open"}]}
        if channel["attribute"] == "tilt" else channel
        for channel in spot["modes"][0]["channels"]
    ]}  # fmt: skip
    assert profile_info({**bare, "modes": [mode]}).range("tilt") == (-135.0, 135.0)


def test_presets_summarise_each_attribute(show: busk.OfflineShow) -> None:
    for line in ("sel group 1", "set zoom 20", 'record preset beam 1 "Narrow"', "sel fixture 101",
                 "set zoom 25", "sel group 1", 'record preset beam 2 target "Two"'):  # fmt: skip
        assert show.execute(line).ok, line
    by_key = {(p.pool, p.number): p for p in show_model(show.show).presets}
    assert by_key["position", 1].values == (("pan", None), ("tilt", 40.0))  # pan -30 and 30
    assert by_key["beam", 1].values == (("zoom", 20.0),)
    assert by_key["beam", 2].values == (("zoom", None),)
    assert by_key["color", 1].values == ()  # its colour is ``color``


def test_the_programmers_values(show: busk.OfflineShow) -> None:
    for line in ("sel group 1", "set intensity 50%", "set pan -45", "set shutter strobe",
                 "sel fixture 201", "preset color 2", "sel fixture 202",
                 "set color 1 0.5 0 w 0.25"):  # fmt: skip
        assert show.execute(line).ok, line
    values = programmer_model(show.programmer, show.show).values
    assert HeldValue(101, 1, "intensity", 0.5, None) in values
    assert HeldValue(102, 1, "pan", -45.0, None) in values
    assert HeldValue(101, 1, "shutter", "strobe", None) in values
    assert HeldValue(201, 1, "color", (("r", 1.0), ("g", 0.0), ("b", 0.0)), "Red") in values
    assert (
        HeldValue(202, 1, "color", (("r", 1.0), ("g", 0.5), ("b", 0.0), ("w", 0.25)), None)
        in values
    )


def test_the_output(show: busk.OfflineShow) -> None:
    for line in ("sel group 1", "set intensity 50%", "set pan -45", "sel fixture 201",
                 "preset color 2", "set intensity 100%"):  # fmt: skip
        assert show.execute(line).ok, line
    show.tick(0.1)
    model = output_model(show.output)
    head = model.element(101, 1)
    assert head is not None
    assert (head.intensity, head.pan, head.tilt, head.zoom) == (0.5, -45.0, 0.0, 21.0)
    sources = (("intensity", "programmer"), ("color", "programmer"))
    assert model.element(201, 1) == ElementOutput(
        201, 1, 1.0, (1.0, 0.0, 0.0), None, None, None, sources
    )
    assert head.source("position") == "programmer"
    assert head.source("focus") is None  # the head has no focus
    assert [out.element for out in model.fixtures if out.number == 301] == list(range(1, 13))
    assert model.element(999, 1) is None


# ---------------------------------------------------------- F4 and F5


def test_cues_with_their_timing_triggers_and_entries_as_stored(club: busk.OfflineShow) -> None:
    model = show_model(club.show)
    song = model.cue_list(9)
    assert song is not None
    assert song.tracking
    intro, verse, pre, chorus, outro = song.cues
    washes, heads = Targets(group=GroupInfo(2, "Washes")), Targets(group=GroupInfo(1, "Heads"))
    assert (intro.fadeIn, intro.fadeOut, intro.curve, intro.trigger) == (
        3.0,
        3.0,
        "easeInOut",
        "go",
    )
    assert intro.values == (
        StoredValue("intensity", washes, "literal", value=0.6),
        StoredValue("color", washes, "preset", preset="Blue", color=(0.0, 0.0, 1.0)),
    )
    assert verse.families == (("position", 4.0, 0.0),)
    assert verse.values[1] == StoredValue("pan", heads, "preset", preset="Audience")
    assert verse.values[3].color == (1.0, 0.75, 0.45)
    assert verse.values[3].value == (("r", 1.0), ("g", 0.75), ("b", 0.45))
    assert (pre.fadeIn, pre.fadeOut, pre.trigger, pre.delay) == (1.0, 3.0, "wait", 8.0)
    assert (outro.trigger, outro.delay) == ("follow", 4.0)
    assert chorus.effects == (
        EffectInfo(
            "rainbow",
            "Rainbow",
            Targets(group=GroupInfo(3, "Bar")),
            rate="hz 0.25",
            phase=(0.0, 360.0),
        ),
    )
    chase = model.cue_list(10)
    assert chase is not None
    assert (chase.crossfade, chase.tracking) == (0.25, False)
    assert chase.cues[0].values[0].targets == Targets(elements=((201, 1),))
    circle = model.cue_list(11).cues[0].effects[0]  # type: ignore[union-attr]
    assert (circle.rate, circle.size, circle.phase) == ("bpm x 0.5", 15.0, (0.0, 180.0))
    assert model.runs(9) == (9,)


def test_a_recorded_spread_a_bezier_and_a_spread_entry(show: busk.OfflineShow) -> None:
    for line in ("sel group 2", "set intensity spread 0 to 1", "preset color 2", "record cue 30",
                 "cue 30/1 time 2 bezier 0.25 0.1 0.25 1"):  # fmt: skip
        assert show.execute(line).ok, line
    cue = show_model(show.show).cue_list(30).cues[0]  # type: ignore[union-attr]
    assert cue.curve == "bezier 0.25 0.1 0.25 1"
    assert [(value.attribute, value.kind) for value in cue.values] == [
        ("intensity", "perTarget"),  # busk records a spread value per target
        ("color", "preset"),
    ]
    doc = copy.deepcopy(show.show)
    entry = {"targets": {"kind": "group", "groupId": doc["groups"][0]["id"]},
             "attribute": "intensity",
             "value": {"kind": "spread", "from": 0.2, "to": 0.8, "curve": "center"}}  # fmt: skip
    doc["cueLists"][0]["cues"][0]["entries"].append(entry)
    spread = show_model(doc).cue_list(1).cues[0].values[-1]  # type: ignore[union-attr]
    assert spread == StoredValue(
        "intensity", Targets(group=GroupInfo(1, "Heads")), "spread", value=0.2, to=0.8
    )


def test_a_programmer_effect_with_levels_and_a_named_speed_master(show: busk.OfflineShow) -> None:
    assert show.execute('master add speed "Speed 2" bpm 90').ok
    assert show.execute("sel group 2").ok
    assert show.execute('effect add "Wave" bpm "Speed 2" x 2 bounce wings 2 groups 3').ok
    (wave,) = programmer_model(show.programmer, show.show).effects
    assert (wave.template, wave.rate, wave.direction) == ("Wave", 'bpm "Speed 2" x 2', "bounce")
    assert (wave.low, wave.high, wave.wings, wave.groups, wave.blocks) == (0.0, 1.0, 2, 3, 1)
    assert wave.targets == Targets(elements=((201, 1), (202, 1), (203, 1), (204, 1)))


def test_the_templates_effect_add_takes(club: busk.OfflineShow) -> None:
    templates = show_model(club.show, club.effect_templates).templates
    assert [(t.name, t.source) for t in templates] == [
        ("Circle", "show"), ("Pulse", "show"), ("Wave", "show"), ("Rainbow", "show"),
        ("Chase", "library"), ("Saw", "library"), ("Sweep", "library"), ("Flicker", "library"),
    ]  # fmt: skip
    assert templates[0] == TemplateInfo(
        "Circle", "show", "pan add sine, tilt add sine +90°", size=20.0
    )
    assert (templates[2].low, templates[2].high) == (0.0, 1.0)
    assert templates[4].phase == (0.0, 360.0)
    assert show_model(club.show).templates == ()


# ------------------------------------------------------------ F3, F8, F9


RIG_LINES = (
    "route add 1 artnet 0.0.1 unicast 10.0.0.50",
    "route add 1 dmxusb enttecPro /dev/ttyUSB0",
    "route add 1 sacn 2 unicast 10.0.0.9",
    'surface add osc "TouchOSC" port 8000 feedback 10.0.0.5:9000',
    'surface add web "Tablet" port 8081 on 127.0.0.1',
    'bind "TouchOSC" osc "/1/push1" blackout momentary led note 1 40',
    'bind "TouchOSC" osc "/1/f" fader playback 9',
    'bind "TouchOSC" osc "/1/p" page 2',
    'bind "TouchOSC" osc "/1/r" release all 2',
    'bind "TouchOSC" osc "/1/o" output off',
    'bind "nanoKONTROL2" clock tap',
    'bind "nanoKONTROL2" note 1 36 button 1 1 motor',
    "fixture 102 patch none",
    'fixture 101 location {"x": 1.5, "y": 2, "z": 4, "rx": 0, "ry": 0, "rz": 90}',
)


def test_fixtures_with_their_mode_patch_and_place(show: busk.OfflineShow) -> None:
    for line in RIG_LINES:
        assert show.execute(line).ok, line
    model = show_model(show.show)
    spot, loose = model.fixture(101), model.fixture(102)
    assert spot is not None
    assert loose is not None
    assert (spot.mode, spot.footprint, spot.patch) == ("16ch", 16, (1, 1))
    assert spot.location == (1.5, 2.0, 4.0, 0.0, 0.0, 90.0)
    assert (loose.patch, loose.location, loose.split) == (None, None, False)
    split = copy.deepcopy(show.show["fixtures"][6])  # busk does not run element patches yet
    split["elementPatch"] = {1: {"universeId": split["patch"]["universeId"], "address": 101}}
    modes = {(p["id"], m["id"]): m for p in show.show["profiles"] for m in p["modes"]}
    universes = {u["id"]: u["number"] for u in show.show["universes"]}
    assert fixture_info(split, modes, {}, universes).split


def test_routes_in_the_words_of_route_add(show: busk.OfflineShow) -> None:
    for line in RIG_LINES[:3]:
        assert show.execute(line).ok, line
    routes = show.show["output"]["routes"]
    status = (
        busk.RouteStatus(id=routes[1]["id"], label="Art-Net r2", universe=1, state="failed",
                         detail="no route to host", packets=10, errors=3),
    )  # fmt: skip
    views = route_views(show.show, status)
    assert [(v.protocol, v.address, v.destination) for v in views] == [
        ("sACN", "1", "multicast eth0"),
        ("ArtNet", "0.0.1", "unicast 10.0.0.50"),
        ("DMX-USB", "enttecPro", "/dev/ttyUSB0"),
        ("sACN", "2", "unicast 10.0.0.9"),
    ]
    assert (views[1].state, views[1].detail, views[1].packets, views[1].errors) == (
        "failed", "no route to host", 10, 3
    )  # fmt: skip
    assert views[0].state is None  # no status: nothing runs it


def test_surfaces_in_the_words_of_surface_add(show: busk.OfflineShow) -> None:
    for line in RIG_LINES[3:5]:
        assert show.execute(line).ok, line
    surfaces = show.show["surfaces"]
    status = (
        busk.SurfaceStatus(id=surfaces[0]["id"], name="nanoKONTROL2", kind="midi",
                           state="failed", detail="unplugged; waiting for it", urls=()),
        busk.SurfaceStatus(id=surfaces[1]["id"], name="Phone", kind="web", state="ok",
                           detail="", urls=("http://10.0.0.2:8080/?k=abc",)),
    )  # fmt: skip
    views = surface_views(show.show, status)
    assert [(v.name, v.kind, v.device, v.pickup, v.state) for v in views] == [
        ("nanoKONTROL2", "midi", '"nanoKONTROL2"', "soft", "failed"),
        ("Phone", "web", "port 8080", "jump", "ok"),
        ("TouchOSC", "osc", "port 8000 feedback 10.0.0.5:9000", "jump", None),
        ("Tablet", "web", "port 8081 on 127.0.0.1", "jump", None),
    ]
    assert views[0].detail == "unplugged; waiting for it"
    assert views[1].urls == ("http://10.0.0.2:8080/?k=abc",)


def test_bindings_in_the_words_of_bind(show: busk.OfflineShow) -> None:
    for line in RIG_LINES[3:12]:
        assert show.execute(line).ok, line
    bindings = show_model(show.show).bindings
    words = {(b.input, b.what, b.feedback, b.target) for b in bindings}
    assert ("cc 1 0", "fader 1", "", ("slot", 0)) in words
    assert ("cc 1 32", "button 1 1", "led", None) in words
    assert ("cc 1 23", "master gm", "", ("master", "Grand Master")) in words
    assert ("cc 1 22", 'master "FX"', "", ("master", "FX")) in words
    assert ("cc 1 46", "tap", "led", None) in words  # one speed master: no name
    assert ("cc 1 61", "page -1", "", None) in words
    assert ("cc 1 60", "release all", "", None) in words
    assert ('osc "/1/push1"', "blackout momentary", "led note 1 40", None) in words
    assert ('osc "/1/f"', "fader playback 9", "", ("playback", 9)) in words
    assert ('osc "/1/p"', "page 2", "", None) in words
    assert ('osc "/1/r"', "release all 2", "", None) in words
    assert ('osc "/1/o"', "output off", "", None) in words
    assert ("clock", "tap", "", None) in words
    assert ("note 1 36", "button 1 1", "motor", None) in words
    clock = next(b for b in bindings if b.kind == "clock")
    assert (clock.surface, clock.channel, clock.number) == ("nanoKONTROL2", None, "")


def test_a_tap_names_its_master_when_the_show_has_two(show: busk.OfflineShow) -> None:
    assert show.execute('master add speed "Speed 2"').ok
    assert show.execute('bind "nanoKONTROL2" cc 1 99 tap "Speed 2"').ok
    taps = [b.what for b in show_model(show.show).bindings if b.what.startswith("tap")]
    assert taps == ['tap "Speed 1"', 'tap "Speed 2"']


def test_the_output_says_what_drives_each_family(show: busk.OfflineShow) -> None:
    for line in ("fader 11 100%", "go 11", "sel fixture 201", "set intensity 50%"):
        assert show.execute(line).ok, line
    show.tick(0.5)
    model = output_model(show.output)
    head, wash = model.element(101, 1), model.element(201, 1)
    assert head is not None
    assert wash is not None
    assert head.source("position") == "effect"  # P11's Circle
    assert wash.source("intensity") == "programmer"
    assert (head.playback, wash.playback) == (None, None)
