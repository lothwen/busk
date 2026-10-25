"""F1 Busk, layout B (spec §8.1, plan Phase 1): the slots and the selected
playback, the playback rows, the keys, the mouse controls, and the right
column (tempo, masters, effects, selection). Headless, with a fake bridge."""

from __future__ import annotations

from typing import Any

import pytest
from rich.text import Text
from textual import events
from textual.pilot import Pilot
from textual.widget import Widget
from tui_fakes import (
    FakeBridge,
    drive,
    live_state,
    make_app,
    playback,
    programmer,
    settle,
    show_model,
)

from busk_tui import colors
from busk_tui.formats import selection_text
from busk_tui.model import (
    CueInfo,
    CueListInfo,
    EffectInfo,
    EffectsChanged,
    EffectsModel,
    EffectView,
    FixtureInfo,
    GroupInfo,
    LiveChanged,
    MasterLevel,
    MasterView,
    PageInfo,
    PageView,
    PlaybackInfo,
    PresetInfo,
    ProgrammerChanged,
    ShowChanged,
    ShowModel,
    SpeedView,
)
from busk_tui.pages.busk import BuskHeader, follow, step, visible_slots
from busk_tui.shell import BuskApp
from busk_tui.widgets.controls import ButtonStrip
from busk_tui.widgets.effects import EffectRow, effect_lines, sparkline
from busk_tui.widgets.log import LogView
from busk_tui.widgets.masters import BlackoutButton, MasterBar
from busk_tui.widgets.playbacks import PlaybackRow, cue_text, playback_color
from busk_tui.widgets.tempo import Tempo

SONG = CueListInfo(
    2,
    "Song",
    "sequence",
    None,
    (
        CueInfo("1", "Intro", ()),
        CueInfo("2", "Verse", ()),
        CueInfo("4", "", (EffectInfo("rainbow", "Rainbow"),)),
    ),
)
CHASE = CueListInfo(
    3, "Chase", "chase", "bpm x 1 bounce", (CueInfo("1", "Step 1", ()), CueInfo("2", "Step 2", ()))
)


def club(**changes: Any) -> ShowModel:
    """A small show: page 1 has P1, P2, P3 and an empty slot; page 2 has P4, P1."""
    parts: dict[str, Any] = {
        "pages": (PageInfo(1, "Main", (1, 2, 3, None)), PageInfo(2, "Washes", (4, 1))),
        "playbacks": (
            PlaybackInfo(1, "Warm", 1, None),
            PlaybackInfo(2, "Song", 2, None),
            PlaybackInfo(3, "Chase", 3, (1.0, 0.5, 0.0)),
            PlaybackInfo(4, "Wash", 4, None),
        ),
        "cueLists": (
            CueListInfo(1, "Warm", "sequence", None, (CueInfo("1", "Warm", ()),)),
            SONG,
            CHASE,
            CueListInfo(4, "Wash", "sequence", None, (CueInfo("1", "Wash", ()),)),
        ),
        "groups": (GroupInfo(1, "Heads"), GroupInfo(2, "Wash level")),
        "presets": (
            PresetInfo("color", 1, "Blue", (0.0, 0.0, 1.0)),
            PresetInfo("color", 2, "Mixed", None),
            PresetInfo("position", 1, "Audience", None),
        ),
        "masters": (
            MasterView("Grand Master", "grand", None, ()),
            MasterView("Speed 1", "speed", None, (0.5, 1.0, 2.0)),
            MasterView("FX", "size", None, ()),
            MasterView("Washes", "group", GroupInfo(2, "Wash level"), ()),
            MasterView("Fade", "fadeTime", None, ()),
        ),
        "fixtures": (FixtureInfo(101, 1), FixtureInfo(102, 1), FixtureInfo(301, 4)),
    }
    parts.update(changes)
    return show_model(**parts)


def live(**changes: Any) -> Any:
    parts: dict[str, Any] = {
        "playbacks": (
            playback(
                1,
                "Warm",
                state="active",
                level=0.8,
                cue="1",
                cueName="Warm",
                next=None,
                color=(1.0, 0.75, 0.45),
            ),
            playback(2, "Song", cueCount=3),
            playback(
                3,
                "Chase",
                state="active",
                level=0.5,
                chase=True,
                cue="2",
                cueName="Step 2",
                next="1",
                cueCount=2,
            ),
            playback(4, "Wash"),
        ),
        "masters": (
            MasterLevel("Grand Master", "grand", 1.0),
            MasterLevel("Speed 1", "speed", 0.5),
            MasterLevel("FX", "size", 0.6),
            MasterLevel("Washes", "group", 0.3),
            MasterLevel("Fade", "fadeTime", 0.0),
        ),
    }
    parts.update(changes)
    return live_state(**parts)


def started(bridge: FakeBridge, show: ShowModel | None = None, **live_changes: Any) -> None:
    bridge.events += [
        ShowChanged(show or club()),
        LiveChanged(live(**live_changes)),
        ProgrammerChanged(programmer()),
    ]


def rows(app: BuskApp) -> dict[int | None, PlaybackRow]:
    return {
        row.number if row.number is not None else -row.slot: row for row in app.query(PlaybackRow)
    }


def plain(widget: Any) -> str:
    rendered = widget.render()
    return rendered.plain if isinstance(rendered, Text) else str(rendered)


def scroll(widget: Widget, *, up: bool) -> events.MouseEvent:
    kind = events.MouseScrollUp if up else events.MouseScrollDown
    return kind(widget, 0, 0, 0, 0, 0, False, False, False)


def styles_of(text: Text, needle: str) -> list[str]:
    index = text.plain.index(needle)
    return [str(span.style) for span in text.spans if span.start <= index < span.end]


# ------------------------------------------------------------ slots, selection


def test_the_slots_are_the_current_pages_at_most_faders() -> None:
    show = club()
    on_page_2 = live(page=PageView(2, "Washes"))
    assert visible_slots(show, live(), 20) == (1, 2, 3, None)
    assert visible_slots(show, on_page_2, 20) == (4, 1)
    assert visible_slots(show, live(), 2) == (1, 2)
    assert visible_slots(show, live(page=PageView(9, "Gone")), 20) == (1, 2, 3, None)
    assert visible_slots(club(pages=()), live(page=None), 3) == (1, 2, 3)
    assert visible_slots(None, None, 20) == ()


def test_the_selected_playback_follows_its_slot() -> None:
    assert follow(2, (1, 2, 3), (2, 7)) == 2  # still shown
    assert follow(2, (1, 2, 3), (6, 7, 8)) == 7  # the same slot
    assert follow(3, (1, 2, 3), (6, None)) == 6  # its slot is empty or gone: the first
    assert follow(9, (), (4, 5)) == 4
    assert follow(9, (1,), (None,)) == 9  # nothing to choose


def test_left_and_right_wrap_and_skip_empty_slots() -> None:
    slots = (1, None, 3, 4)
    assert step(1, slots, 1) == 3
    assert step(4, slots, 1) == 1
    assert step(1, slots, -1) == 4
    assert step(9, slots, 1) == 1
    assert step(9, slots, -1) == 4
    assert step(9, (None,), 1) == 9


def test_the_selection_is_compressed() -> None:
    fixtures = (FixtureInfo(101, 1), FixtureInfo(102, 1), FixtureInfo(103, 1), FixtureInfo(301, 4))
    whole = ((101, 1), (102, 1), (103, 1), (301, 1), (301, 2), (301, 3), (301, 4))
    assert selection_text(whole, fixtures) == "101 thru 103, 301"
    assert (
        selection_text(((301, 2), (301, 3), (301, 4), (101, 1)), fixtures)
        == "301.2 thru 301.4, 101"
    )
    assert selection_text(((103, 1), (101, 1)), fixtures) == "103, 101"
    assert selection_text(((301, 1), (301, 3)), fixtures) == "301.1, 301.3"
    assert selection_text((), fixtures) == ""


# ------------------------------------------------------------ row content


def test_the_cue_column() -> None:
    song = playback(2, "Song", state="active", cue="2", cueName="Verse", next="4", cueCount=3)
    assert cue_text(song, SONG).plain == "2/3 Verse → cue 4"
    assert colors.DIM in styles_of(cue_text(song, SONG), "→")[0]
    idle = playback(2, "Song", cueCount=3)
    assert cue_text(idle, SONG).plain == "—/3 → Intro"
    last = playback(2, "Song", state="releasing", cue="4", next=None, cueCount=3)
    assert cue_text(last, SONG).plain == "3/3 cue 4"
    chase = playback(3, "Chase", state="active", chase=True, cue="2", cueName="Step 2", cueCount=2)
    assert cue_text(chase, CHASE).plain == "chase 2 Step 2 bpm x 1 bounce"
    fading = playback(2, "Song", state="active", cue="2", next="4", cueCount=3, progress=0.42)
    text = cue_text(fading, SONG)
    assert text.plain == "2/3 Verse 42% → cue 4"
    assert colors.AMBER in styles_of(text, "42%")[0]


def test_a_playback_is_drawn_in_its_cues_colour_else_its_own_else_the_foreground() -> None:
    info = PlaybackInfo(3, "Chase", 3, (1.0, 0.5, 0.0))
    lit = playback(3, "Chase", color=(0.0, 0.0, 1.0))
    assert playback_color(lit, info, "truecolor") == "#0000ff"
    assert playback_color(playback(3, "Chase"), info, "truecolor") == "#ff8000"
    assert playback_color(playback(3, "Chase"), None, "256") == colors.FG


def test_rows_from_the_live_state() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        shown = rows(app)
        assert sorted(n for n in shown if n is not None and n > 0) == [1, 2, 3]
        warm, song, chase, empty = shown[1], shown[2], shown[3], shown[-4]
        assert warm.has_class("-selected")
        assert not song.has_class("-selected")
        assert colors.CYAN in str(warm.label.render().spans[0].style)  # type: ignore[union-attr]
        assert plain(warm.level) == "80"
        assert plain(warm.cue) == "1/1 Warm"
        assert warm.bar.level == 0.8
        assert warm.bar.color == colors.swatch((1.0, 0.75, 0.45), 1.0, app.view.mode)
        assert plain(song.level) == "0"
        assert colors.DIM in str(song.level.render().spans[0].style)  # type: ignore[union-attr]
        assert plain(chase.cue) == "chase 2 Step 2 bpm x 1 bounce"
        assert chase.bar.color == colors.swatch((1.0, 0.5, 0.0), 1.0, app.view.mode)
        assert (plain(empty.label), plain(empty.name_text)) == ("·", "—")
        assert empty.buttons == []
        assert empty.flash is None
        header = app.query_one(BuskHeader).left.plain
        assert header == "page 1 Main · slots 1–4 · sel none"

    drive(app, body)


@pytest.mark.parametrize(
    ("changes", "level", "name", "level_color"),
    [
        ({"state": "releasing", "level": 0.4, "cue": "1"}, "40", "Wash", colors.AMBER),
        (
            {"fader": "size", "level": 1.0, "state": "active", "cue": "1"},
            "100",
            "Wash size",
            colors.FG,
        ),
        ({"fader": "crossfade"}, "0", "Wash xfade", colors.DIM),
        ({"fader": "none", "level": 0.7}, "—", "Wash no fader", colors.DIM),
    ],
)
def test_the_fader_functions_and_states(
    changes: dict[str, Any], level: str, name: str, level_color: str
) -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, page=PageView(2, "Washes"), playbacks=(playback(4, "Wash", **changes),))
        await settle(pilot, app)
        row = rows(app)[4]
        assert plain(row.level) == level
        assert plain(row.name_text) == name
        assert level_color in str(row.level.render().spans[0].style)  # type: ignore[union-attr]
        assert (row.bar.command is None) is (changes.get("fader") == "none")

    drive(app, body)


def test_a_held_flash_shows_lit() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        flash = rows(app)[2].flash
        assert flash is not None
        assert not flash.lit
        bridge.events.append(LiveChanged(live(seq=2, playbacks=(playback(2, "Song", flash=True),))))
        await settle(pilot, app)
        assert flash.lit
        assert f"on {colors.AMBER}" in str(flash.render().spans[0].style)  # type: ignore[union-attr]

    drive(app, body)


# -------------------------------------------------------------------- keys


def sent(bridge: FakeBridge) -> list[tuple[str, str, str | None, bool]]:
    return [(s.line, s.origin, s.key, s.performance) for s in bridge.sent]


def test_space_runs_go_on_the_selected_playback_and_arrows_choose_it() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        await pilot.press("space")
        await pilot.press("right", "right", "space")  # P3
        await pilot.press("right", "space")  # the empty slot is skipped: wraps to P1
        await pilot.press("left", "space")  # P3 again
        assert sent(bridge) == [
            ("go 1", "ui", None, True),
            ("go 3", "ui", None, True),
            ("go 1", "ui", None, True),
            ("go 3", "ui", None, True),
        ]
        assert ("ui", "go 3") in app.query_one(LogView).entries
        assert app.playback == 3
        assert rows(app)[3].has_class("-selected")
        app._show_context()
        assert " · P3" in app._context_text

    drive(app, body)


def test_brackets_step_the_fader_from_the_level_last_sent() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        await pilot.press("right", "left_square_bracket")  # P2 at 0: stays at 0
        await pilot.press(
            "right_square_bracket", "right_square_bracket"
        )  # before the engine shows it
        assert sent(bridge) == [
            ("fader 2 0%", "ui", "fader:2", True),
            ("fader 2 5%", "ui", "fader:2", True),
            ("fader 2 10%", "ui", "fader:2", True),
        ]
        app._nudged = None  # long ago: from the engine's level
        await pilot.press("left", "right_square_bracket")  # P1 at 80
        assert sent(bridge)[-1] == ("fader 1 85%", "ui", "fader:1", True)

    drive(app, body)


def test_page_up_and_down_change_the_page_and_the_selection_follows() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        await pilot.press("right")  # P2, in slot 2
        await pilot.press("pagedown", "pageup")
        assert sent(bridge) == [("page next", "ui", None, True), ("page prev", "ui", None, True)]
        bridge.events.append(LiveChanged(live(seq=2, page=PageView(2, "Washes"))))
        await settle(pilot, app)
        assert app.playback == 1  # slot 2 of page 2
        assert sorted(n for n in rows(app) if n is not None) == [1, 4]
        assert app.query_one(BuskHeader).left.plain.startswith("page 2 Washes · slots 1–2")

    drive(app, body)


def test_the_keys_type_while_the_prompt_has_text() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        await pilot.press("g", "space", "left_square_bracket", "right_square_bracket", "left")
        assert app.prompt.value == "g []"
        assert bridge.sent == []

    drive(app, body)


# ---------------------------------------------------------- mouse controls


def test_go_back_and_a_click_on_pn() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        song = rows(app)[2]
        await pilot.click(song.buttons[0])
        await pilot.click(song.buttons[1])
        assert sent(bridge) == [("go 2", "ui", None, True), ("back 2", "ui", None, True)]
        await pilot.click(song.label)
        assert app.playback == 2

    drive(app, body)


def test_a_fader_drag_is_sent_as_it_moves_and_logged_on_release() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        bar = rows(app)[2].bar
        width = bar.size.width
        await pilot.mouse_down(bar, offset=(0, 0))
        await pilot.hover(bar, offset=(width // 2, 0))
        await pilot.mouse_up(bar, offset=(width - 1, 0))
        lines = sent(bridge)
        assert lines[-1] == ("fader 2 100%", "ui", "fader:2", True)
        assert all(key == "fader:2" and performance for _, _, key, performance in lines)
        assert {origin for _, origin, _, _ in lines[:-1]} == {"internal"}
        logged = [text for kind, text in app.query_one(LogView).entries if kind == "ui"]
        assert logged == ["fader 2 100%"]
        bridge.sent.clear()
        bar.post_message(scroll(bar, up=False))  # the wheel: sent, not logged
        await pilot.pause()
        assert sent(bridge) == [("fader 2 95%", "internal", "fader:2", True)]

    drive(app, body)


def test_flash_is_held_while_the_button_is_down() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        flash = rows(app)[3].flash
        assert flash is not None
        await pilot.mouse_down(flash)
        assert flash.held
        assert sent(bridge) == [("flash 3 on", "ui", None, True)]
        await pilot.mouse_up(flash)
        assert not flash.held
        assert sent(bridge) == [("flash 3 on", "ui", None, True), ("flash 3 off", "ui", None, True)]

    drive(app, body)


# ------------------------------------------------------------ right column


def test_tempo_masters_and_blackout() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        tempo = app.query_one("#page-1").query_one(Tempo)
        assert tempo.digits.text == "120.0"
        await pilot.click(tempo.tap)
        await pilot.click(tempo.slower)
        await pilot.click(tempo.faster)
        assert [line for line, *_ in sent(bridge)] == [
            'tap "Speed 1"',
            'bpm "Speed 1" 119',
            'bpm "Speed 1" 121',
        ]
        bars = {bar.label: bar for bar in app.query_one("#page-1").query(MasterBar)}
        assert list(bars) == ["GM", "FX", "Washes"]  # no speed or fade-time master here
        assert (bars["FX"].level, bars["FX"].bar.color) == (0.6, colors.GREEN)
        assert (bars["Washes"].level, bars["Washes"].bar.color) == (0.3, colors.AMBER)
        blackout = app.query_one("#page-1").query_one(BlackoutButton)
        assert blackout.line.text == "blackout on"
        assert not blackout.reverse
        bridge.events.append(
            LiveChanged(live(seq=2, blackout=True, speed=(SpeedView("Speed 1", 128.0, 1.0, 0.5),)))
        )
        await settle(pilot, app)
        assert blackout.line.text == "blackout off"
        assert blackout.reverse
        assert tempo.digits.text == "128.0"
        assert tempo.slower.line.text == 'bpm "Speed 1" 127'
        bridge.sent.clear()
        await pilot.click(blackout)
        assert sent(bridge) == [("blackout off", "ui", None, True)]

    drive(app, body)


def test_a_show_without_a_speed_master_says_so() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, show=club(masters=(MasterView("Grand Master", "grand", None, ()),)))
        await settle(pilot, app)
        assert not app.query_one("#page-1").query(Tempo)
        assert "no speed master" in plain(app.query_one("#tempo-body").children[0])

    drive(app, body)


def effects() -> EffectsModel:
    return EffectsModel(
        seq=5,
        effects=(
            EffectView(
                9, "4", "rainbow", 1.0, 1.0, 0.25, 0.0, (), ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
            ),
            EffectView(None, None, "fx5", 0.5, 1.0, 2.0, 0.0, (0.0, 0.5, 1.0, 0.5), ()),
        ),
    )


def test_effect_lines_from_the_show_the_programmer_and_what_runs() -> None:
    show = club(playbacks=(*club().playbacks, PlaybackInfo(9, "Song", 2, None)))
    stopped = programmer(
        effects=(EffectInfo("fx5", "Circle"), EffectInfo("fx6", "Pulse")),
        stopped=frozenset({"fx6"}),
    )
    lines = effect_lines(show, stopped, effects())
    assert [(e.owner, e.id, e.template, e.running, e.presence, e.toggle.text) for e in lines] == [
        ("P9", "rainbow", "Rainbow", True, 1.0, "release 9"),
        ("prog", "fx5", "Circle", True, 0.5, "effect stop fx5"),
        ("prog", "fx6", "Pulse", False, 0.0, "effect run fx6"),
    ]
    assert lines[1].wave == (0.0, 0.5, 1.0, 0.5)
    assert effect_lines(None, None, None) == []


def test_sparklines() -> None:
    wave = sparkline((0.0, 0.5, 1.0, 0.5), (), True, "256", width=8)
    assert wave.plain == "▁▁▅▅██▅▅"
    assert {str(span.style) for span in wave.spans} == {colors.GREEN}
    hues = sparkline((), ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)), True, "truecolor", width=4)
    assert hues.plain == "████"
    assert [str(span.style) for span in hues.spans] == ["#ff0000", "#ff0000", "#0000ff", "#0000ff"]
    assert sparkline((0.0, 1.0), (), False, "256", width=3).plain == "▁▁▁"
    assert sparkline((), (), True, "256", width=3).plain == "▁▁▁"
    assert sparkline((), (), True, "256", width=3).style == colors.BORDER


def test_the_effects_panel_and_its_toggles() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, show=club(playbacks=(*club().playbacks, PlaybackInfo(9, "Song", 2, None))))
        bridge.events += [
            ProgrammerChanged(programmer(
                effects=(EffectInfo("fx5", "Circle"), EffectInfo("fx6", "Pulse")),
                stopped=frozenset({"fx6"}),
            )),
            EffectsChanged(effects()),
        ]  # fmt: skip
        await settle(pilot, app)
        shown = list(app.query(EffectRow))
        assert [plain(row.who) for row in shown] == ["P9 rainbow", "prog fx5", "prog fx6"]
        assert [(row.state.label, row.state.dim) for row in shown] == [
            ("RUN", False),
            ("RUN", True),  # fading in
            ("off", False),
        ]
        for row in shown:
            await pilot.click(row.state)
        assert [line for line, *_ in sent(bridge)] == [
            "release 9",
            "effect stop fx5",
            "effect run fx6",
        ]
        bridge.events.append(EffectsChanged(EffectsModel(6, ())))
        bridge.events.append(ProgrammerChanged(programmer(version=2)))
        await settle(pilot, app)
        await pilot.pause()
        assert not app.query(EffectRow)
        assert "no effects run" in plain(app.query_one("#page-1 EffectList").children[0])

    drive(app, body)


def test_the_selection_panel() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        bridge.events.append(ProgrammerChanged(programmer(selection=((101, 1), (102, 1)))))
        await settle(pilot, app)
        assert plain(app.query_one("#selection-text")) == "101 thru 102 (2)"
        assert app.query_one(BuskHeader).left.plain.endswith("sel 101 thru 102")
        groups = app.query_one("#group-buttons", ButtonStrip)
        assert groups.render().plain == "[Heads] [Wash level]"
        chips = app.query_one("#color-chips", ButtonStrip)
        assert chips.render().plain == "██ ░░"  # type: ignore[union-attr]
        await pilot.click(groups, offset=(1, 0))
        await pilot.click(groups, offset=(10, 0), shift=True)
        await pilot.click(chips, offset=(0, 0))
        await pilot.click(chips, offset=(3, 0))
        assert [line for line, *_ in sent(bridge)] == [
            "sel group 1",
            "sel + group 2",
            "preset color 1",
            "preset color 2",
        ]

    drive(app, body)


# --------------------------------------------------------- keyboard reach


def test_the_pane_cursor_reaches_every_control() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        labels = [item.line or item.prefill for item in app.current_page.items()]
        assert labels == [
            "go 1", "back 1", "go 2", "back 2", "go 3", "back 3",
            'tap "Speed 1"', 'bpm "Speed 1" 119', 'bpm "Speed 1" 121',
            "gm ", 'master "FX" ', 'master "Washes" ', "blackout on",
            "sel group 1", "sel group 2", "preset color 1", "preset color 2",
        ]  # fmt: skip
        await pilot.press("tab", "down", "down", "down")  # back 2
        await pilot.press("enter", "enter")
        assert app.cursor.active  # a line runs and the cursor stays
        assert [line for line, *_ in sent(bridge)] == ["back 2", "back 2"]
        await pilot.press(*["down"] * 6, "enter")  # gm: a line to finish
        assert not app.cursor.active
        assert app.prompt.value == "gm "

    drive(app, body)


def test_the_blackout_items_line_follows_the_state() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        await pilot.press("tab", *["down"] * 12)
        assert app.cursor.current is not None
        assert app.cursor.current.line == "blackout on"
        bridge.events.append(LiveChanged(live(seq=2, blackout=True)))
        await settle(pilot, app)
        await pilot.press("enter")
        assert sent(bridge)[-1][0] == "blackout off"

    drive(app, body)


def test_f1_watches_the_effects_and_other_pages_do_not() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        assert bridge.watching == (False, True)
        await pilot.press("f7")
        assert bridge.watching == (False, False)
        await pilot.press("f1")
        assert bridge.watching == (False, True)

    drive(app, body)


def test_layouts_a_and_c_come_later() -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        app.action_layout("A")
        assert list(app.query_one(LogView).entries)[-1] == (
            "info",
            "layout A (console) comes in Phase 5; F1 shows B",
        )

    drive(app, body)


def test_layout_b_stacks_below_100_columns() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        playbacks = app.query_one("#playbacks")
        side = app.query_one("#busk-side")
        assert side.region.y > playbacks.region.y
        assert side.region.width == playbacks.region.width

    drive(app, body, size=(99, 40))
