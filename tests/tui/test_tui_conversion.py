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
from busk_tui import attributes
from busk_tui.bridge import (
    effects_model,
    fixture_info,
    live_state,
    output_model,
    profile_info,
    programmer_model,
    route_views,
    selection_options,
    show_model,
    surface_views,
)
from busk_tui.model import (
    ChaseRate,
    EffectInfo,
    ElementOutput,
    FixtureInfo,
    GroupInfo,
    HeldValue,
    Limits,
    MasterView,
    ModeInfo,
    Orientation,
    PageInfo,
    PlaybackView,
    PresetEntry,
    ProfileChoice,
    ProfileInfo,
    StoredValue,
    Targets,
    TemplateInfo,
)

TUPPER = Path(__file__).resolve().parents[2] / "examples" / "tupperdmx" / "tupper-demo.show"


@pytest.fixture
def show(club_path: Path, tmp_path: Path) -> busk.OfflineShow:
    document, _ = busk.load_show(club_path)
    return busk.OfflineShow(document, path=tmp_path / "club.show")


@pytest.fixture
def tupper() -> busk.OfflineShow:
    """The TupperDMX demo show, to select on (not saved)."""
    document, _ = busk.load_show(TUPPER)
    return busk.OfflineShow(document)


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
    assert chase.rate == ChaseRate(None, None, 1.0, "bounce")
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
        301,
        12,
        "COLORband PiX 301",
        "Chauvet DJ COLORband PiX",
        "36-CH",
        36,
        (1, 49),
        limits=Limits(intensity=0.5),
    )
    assert bar in model.fixtures
    spot = FixtureInfo(
        101,
        1,
        "Spot 101",
        "Generic Spot 16ch",
        "16ch",
        16,
        (1, 1),
        limits=Limits(tilt=(-90.0, 10.0)),
    )
    assert spot in model.fixtures


def test_a_chase_names_its_master_when_the_show_has_two(show: busk.OfflineShow) -> None:
    assert show.execute('master add speed "Speed 2" bpm 90').ok
    assert show.execute('cuelist 10 chase bpm "Speed 2" x 0.5 forward').ok
    assert show.execute("cuelist 1 chase hz 2.5 random").ok
    model = show_model(show.show)
    assert model.cue_list(10).chase == 'bpm "Speed 2" x 0.5 forward'  # type: ignore[union-attr]
    assert model.cue_list(10).rate == ChaseRate(None, "Speed 2", 0.5, "forward")  # type: ignore[union-attr]
    assert model.cue_list(1).rate == ChaseRate(2.5, None, 1.0, "random")  # type: ignore[union-attr]
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
        "Chauvet DJ COLORband PiX",
        frozenset({"intensity", "color"}),
        (),
        "pixel",
        (ModeInfo("36-CH", 36, 12),),
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


def test_amber_and_uv_emitters_and_the_rotation_ranges(
    club: busk.OfflineShow, tupper: busk.OfflineShow
) -> None:
    par = next(p for p in club.show["profiles"] if p["name"] == "Eurolite LED ML-56 RGBW")

    def with_white_as(component: str) -> ProfileInfo:
        mode = {**par["modes"][0], "channels": [
            {**channel, "component": component} if channel.get("component") == "white" else channel
            for channel in par["modes"][0]["channels"]
        ]}  # fmt: skip
        return profile_info({**par, "modes": [mode]})

    assert with_white_as("amber").attributes == frozenset({"intensity", "color", "color.a"})
    assert with_white_as("uv").attributes == frozenset({"intensity", "color", "color.uv"})
    head = next(p for p in tupper.show["profiles"] if p["name"] == "TupperDMX Moving Head")
    info = profile_info(head)
    assert {"gobo1", "gobo1Rotation", "prism", "zoom"} <= info.attributes
    assert info.range("gobo1Rotation") == (-360.0, 360.0)  # its channel spans -360..-10, 10..360
    bare = {**head, "modes": [{**head["modes"][0], "channels": [
        {**channel, "capabilities": [{"kind": "function", "dmx": [0, 255], "fn": "goboIndex"}]}
        if channel["attribute"] == "gobo1Rotation" else channel
        for channel in head["modes"][0]["channels"]
    ]}]}  # fmt: skip
    assert profile_info(bare).range("gobo1Rotation") == (-360.0, 360.0)  # the default


def test_a_presets_entries_in_each_scope_and_the_cues_that_use_it(show: busk.OfflineShow) -> None:
    for line in ("sel group 1", "set zoom 20", 'record preset beam 1 "Narrow"'):
        assert show.execute(line).ok, line
    by_key = {(p.pool, p.number): p for p in show_model(show.show).presets}
    red = by_key["color", 2]
    assert red.entries == (
        PresetEntry("global", None, "color", (("r", 1.0), ("g", 0.0), ("b", 0.0))),
    )
    assert red.used_by == (
        (4, "1"), (10, "1"), (10, "2"), (10, "3"), (10, "4"), (15, "1"), (18, "2"),
    )  # fmt: skip
    assert red.palettes == ()
    assert by_key["position", 1].entries == (  # Audience: a fan, per target
        PresetEntry("target", (101, 1), "pan", -30.0),
        PresetEntry("target", (102, 1), "pan", 30.0),
        PresetEntry("target", (101, 1), "tilt", 40.0),
        PresetEntry("target", (102, 1), "tilt", 40.0),
    )
    narrow = by_key["beam", 1]
    assert narrow.entries == (PresetEntry("profile", "Generic Spot 16ch", "zoom", 20.0),)
    assert (narrow.used_by, narrow.palettes) == ((), ())


def test_an_effect_palette_that_takes_a_preset(show: busk.OfflineShow) -> None:
    doc = copy.deepcopy(show.show)
    red = next(p["id"] for p in doc["presets"] if p["name"] == "Red")
    rainbow = next(t for t in doc["effects"] if t["name"] == "Rainbow")
    layer = next(layer for layer in rainbow["layers"] if "palette" in layer)
    layer["palette"] += [{"presetId": red}, {"presetId": red}]
    by_name = {p.name: p for p in show_model(doc).presets}
    assert by_name["Red"].palettes == ("Rainbow",)
    assert by_name["Blue"].palettes == ()


def test_the_options_each_selection_offers(tupper: busk.OfflineShow) -> None:
    rig = attributes.taken(show_model(tupper.show))

    def options(line: str) -> dict[str, tuple[str, ...]]:
        assert tupper.execute(line).ok, line
        return dict(selection_options(tupper.expected, tupper.programmer.selection, rig))

    heads = options("sel group 4")
    assert list(heads) == ["gobo1", "prism", "effect", "shutter"]  # the rig's, registry order
    assert heads["gobo1"] == (
        "open", "breakup", "dots", "lines", "star", "spiral", "triangles", "closed",
    )  # fmt: skip
    assert heads["prism"] == ("off", "prism3")
    assert heads["effect"] == ()  # no head takes one
    blinders = options("sel group 2")
    assert blinders["effect"] == ("off", "autoProgram", "soundActive")
    assert blinders["shutter"] == ("open", "strobe")
    assert blinders["gobo1"] == ()
    assert tupper.execute("sel none").ok
    assert selection_options(tupper.expected, (), rig) == ()


def test_the_programmer_carries_the_options_it_is_given(tupper: busk.OfflineShow) -> None:
    assert tupper.execute("sel group 4").ok
    model = programmer_model(tupper.programmer, tupper.show, (("prism", ("off", "prism3")),))
    assert model.offered("prism") == ("off", "prism3")
    assert model.offered("gobo1") == ()


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
    red = (("r", 1.0), ("g", 0.0), ("b", 0.0))
    assert HeldValue(201, 1, "color", red, "Red", ("color", 2)) in values
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


def test_a_fixtures_limits_and_orientation(show: busk.OfflineShow) -> None:
    fixtures = {info.number: info for info in show_model(show.show).fixtures}
    assert fixtures[101].limits == Limits(tilt=(-90.0, 10.0))
    assert fixtures[102].limits == Limits(tilt=(-90.0, 10.0))
    assert fixtures[201].limits == Limits()
    assert fixtures[301].limits == Limits(intensity=0.5)
    assert fixtures[101].orientation == Orientation()
    for line in ("fixture 101 limits pan -180 180", "fixture 101 limits intensity 25%",
                 "fixture 101 orientation.invertPan true", "fixture 101 orientation.panOffset 30",
                 "fixture 101 orientation.swapPanTilt true"):  # fmt: skip
        assert show.execute(line).ok, line
    head = next(info for info in show_model(show.show).fixtures if info.number == 101)
    assert head.limits == Limits((-180.0, 180.0), (-90.0, 10.0), 0.25)
    assert head.orientation == Orientation(invertPan=True, swapPanTilt=True, panOffset=30.0)


def test_limits_survive_a_save(show: busk.OfflineShow, tmp_path: Path) -> None:
    """A loaded document holds a limit as JSON's list, a new one as a tuple."""
    assert show.execute("fixture 101 limits pan -180 180").ok
    assert show.execute("save").ok
    document, _ = busk.load_show(tmp_path / "club.show")
    head = next(info for info in show_model(document).fixtures if info.number == 101)
    assert head.limits == Limits((-180.0, 180.0), (-90.0, 10.0))


def test_the_modes_of_each_profile(club: busk.OfflineShow, tupper: busk.OfflineShow) -> None:
    assert [(p.name, p.modes) for p in show_model(club.show).profiles] == [
        ("Generic Spot 16ch", (ModeInfo("16ch", 16, 1),)),
        ("Eurolite LED ML-56 RGBW", (ModeInfo("4-channel", 4, 1),)),
        ("Chauvet DJ COLORband PiX", (ModeInfo("36-CH", 36, 12),)),
    ]
    model = show_model(tupper.show)
    assert all(profile.modes for profile in model.profiles)
    for fixture in model.fixtures:
        profile = model.profile(fixture.profile)
        assert profile is not None
        mode = next(mode for mode in profile.modes if mode.name == fixture.mode)
        assert (mode.footprint, mode.elements) == (fixture.footprint, fixture.elements)


def test_the_profiles_fixture_add_takes(club: busk.OfflineShow) -> None:
    choices = show_model(club.show, (), club.fixture_profiles).choices
    assert [(c.name, c.source) for c in choices] == [
        ("Generic Spot 16ch", "show"),
        ("Eurolite LED ML-56 RGBW", "show"),
        ("Chauvet DJ COLORband PiX", "show"),
        ("RGB Par 3ch", "library"),
        ("Stairville MH-X25 LED Spot", "library"),
    ]
    assert choices[3] == ProfileChoice(
        "RGB Par 3ch", "library", "Generic", (ModeInfo("3ch", 3, 1),)
    )
    assert choices[2].modes == (ModeInfo("36-CH", 36, 12),)
    assert show_model(club.show).choices == ()


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
    ids = [route["id"] for route in show.show["output"]["routes"]]
    assert [view.id for view in views] == ids
    assert all(view.id in show.execute("list routes").text for view in views)


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
