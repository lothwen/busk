"""The bridge's conversion (``busk_tui.bridge``) of real busk objects, from an
:class:`busk.OfflineShow` of the club-night show: the playbacks of the
snapshot, the show model F1 and F7 use, the programmer's effects and the
running effects."""

from __future__ import annotations

from pathlib import Path

import pytest

import busk
from busk_tui.bridge import effects_model, live_state, programmer_model, show_model
from busk_tui.model import (
    CueInfo,
    EffectInfo,
    FixtureInfo,
    GroupInfo,
    MasterView,
    PageInfo,
    PlaybackView,
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
    assert song.cues[3] == CueInfo("4", "Chorus", (EffectInfo("rainbow", "Rainbow"),))
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
    assert FixtureInfo(301, 12) in model.fixtures
    assert FixtureInfo(101, 1) in model.fixtures


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
    assert model.effects == (EffectInfo(effect_id, "Circle"),)
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
