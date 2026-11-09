"""F1 Busk, layout B (spec §8.1, plan Phase 1): the slots and the selected
playback, the playback rows, the keys, the mouse controls, and the right
column (tempo, masters, effects, selection). Headless, with a fake bridge."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, get_args

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

from busk.model.playback import ButtonFunction
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
    HeldValue,
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
from busk_tui.widgets.controls import ButtonStrip, CommandButton
from busk_tui.widgets.effects import EffectRow, effect_lines, sparkline
from busk_tui.widgets.log import LogView
from busk_tui.widgets.masters import BlackoutButton, MasterBar
from busk_tui.widgets.playbacks import (
    HINTS,
    LABELS,
    PlaybackHeader,
    PlaybackRow,
    cue_text,
    own_buttons,
    own_controls,
    playback_color,
)
from busk_tui.widgets.prompt import HintRow
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
            PlaybackInfo(1, "Warm", 1, None, ("toggle", "flash", "release")),
            PlaybackInfo(2, "Song", 2, None, ("go", "back", "flash")),
            PlaybackInfo(3, "Chase", 3, (1.0, 0.5, 0.0), ("go", "back", "swop")),
            PlaybackInfo(4, "Wash", 4, None, ("toggle", "flash")),
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
        assert empty.buttons == [empty.record]
        assert empty.held == []
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
        flash = rows(app)[2].held[0]
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


def test_own_buttons_and_a_click_on_pn() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        song = rows(app)[2]
        await pilot.click(song.buttons[0])
        await pilot.click(song.buttons[1])
        assert sent(bridge) == [
            ("button 2 1 on", "ui", None, True),
            ("button 2 2 on", "ui", None, True),
        ]
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


def test_a_swop_is_held_while_the_button_is_down() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        swop = rows(app)[3].held[0]
        assert plain(swop) == "[SW]"
        await pilot.mouse_down(swop)
        assert swop.held
        assert sent(bridge) == [("button 3 3 on", "ui", None, True)]
        await pilot.mouse_up(swop)
        assert not swop.held
        assert sent(bridge) == [
            ("button 3 3 on", "ui", None, True),
            ("button 3 3 off", "ui", None, True),
        ]

    drive(app, body)


# ------------------------------------------------ the playback's own buttons


def own(number: int, *buttons: str, goto: str | None = None) -> PlaybackInfo:
    """Playback ``number`` of :func:`club` with ``buttons``."""
    base = next(info for info in club().playbacks if info.number == number)
    return replace(base, buttons=buttons, gotoCue=goto)


def with_buttons(*changed: PlaybackInfo, **changes: Any) -> ShowModel:
    """:func:`club` with some of its playbacks replaced."""
    numbers = {info.number for info in changed}
    kept = tuple(info for info in club().playbacks if info.number not in numbers)
    playbacks = tuple(sorted((*kept, *changed), key=lambda info: info.number))
    return club(playbacks=playbacks, **changes)


def test_every_function_of_the_model_has_a_label_and_a_hint() -> None:
    functions = set(get_args(ButtonFunction.__value__))
    assert set(LABELS) == functions
    assert set(HINTS) == functions - {"none"}
    assert all(len(label) <= 2 for label in LABELS.values())  # two fit a column, see LABELS


@pytest.mark.parametrize(
    ("functions", "labels"),
    [  # every set the club show has
        (("toggle", "flash", "release"), ["[TG]", "[FL]", "[RL]"]),
        (("toggle", "flash"), ["[TG]", "[FL]"]),
        (("toggle", "swop", "release"), ["[TG]", "[SW]", "[RL]"]),
        (("go", "back", "release"), ["[GO]", "[◂]", "[RL]"]),
        (("go", "back", "release", "goto"), ["[GO]", "[◂]", "[RL]", "[GT]"]),
    ],
)
def test_a_row_has_the_playbacks_own_buttons(functions: tuple[str, ...], labels: list[str]) -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, show=with_buttons(own(2, *functions, goto="2")))
        await settle(pilot, app)
        row = rows(app)[2]
        assert [plain(button) for button in row.buttons] == labels
        for left, right in zip(row.buttons, row.buttons[1:], strict=False):
            assert right.region.x == left.region.right + 1  # a cell between two
        expected = []
        for index, (button, function) in enumerate(zip(row.buttons, functions, strict=True), 1):
            if function in ("flash", "swop"):
                await pilot.mouse_down(button)
                await pilot.mouse_up(button)
                expected += [f"button 2 {index} on", f"button 2 {index} off"]
            else:
                await pilot.click(button)
                expected.append(f"button 2 {index} on")
        assert [line for line, *_ in sent(bridge)] == expected

    drive(app, body)


def test_a_none_keeps_its_place_and_does_nothing() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, show=with_buttons(own(2, "none", "release")))
        await settle(pilot, app)
        blank, release = rows(app)[2].buttons
        assert plain(blank) == "[—]"
        assert isinstance(blank, CommandButton)
        assert blank.inert
        await pilot.click(blank)
        await pilot.click(release)
        assert [line for line, *_ in sent(bridge)] == ["button 2 2 on"]
        lines = [item.line for item in app.current_page.items()]
        assert "button 2 1 on" not in lines
        assert "button 2 2 on" in lines

    drive(app, body)


def test_a_select_press_goes_in_order_with_the_programmer_lines() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, show=with_buttons(own(2, "select", "go")))
        await settle(pilot, app)
        select, go = rows(app)[2].buttons
        await pilot.click(select)
        await pilot.click(go)
        assert sent(bridge) == [
            ("button 2 1 on", "ui", None, False),
            ("button 2 2 on", "ui", None, True),
        ]

    drive(app, body)


def test_a_goto_is_grey_without_a_goto_cue() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, show=with_buttons(own(2, "goto"), own(1, "goto", goto="1")))
        await settle(pilot, app)
        idle, live_goto = rows(app)[2].buttons[0], rows(app)[1].buttons[0]
        assert isinstance(idle, CommandButton)
        assert isinstance(live_goto, CommandButton)
        assert idle.inert
        assert "no goto cue" in str(idle.hint)
        assert not live_goto.inert
        await pilot.click(idle)
        await pilot.click(live_goto)
        assert [line for line, *_ in sent(bridge)] == ["button 1 1 on"]

    drive(app, body)


def test_what_starts_a_list_with_no_cues_is_grey() -> None:
    """``go`` is refused there, but ``button`` would mark it active on no cue."""
    show = with_buttons(
        own(2, "go", "toggle", "back", "flash", "release"),
        cueLists=(*club().cueLists[:1], replace(SONG, cues=()), *club().cueLists[2:]),
    )
    assert own_buttons(show, 2) == (
        ("go", "go: its cue list has no cues"),
        ("toggle", "toggle: its cue list has no cues"),
        ("back", None),
        ("flash", None),
        ("release", None),
    )


def test_what_starts_the_playback_is_green_and_the_rest_neutral() -> None:
    controls = own_controls(2, [(name, None) for name in ("go", "toggle", "back", "release")])
    assert [control.intent for control in controls if isinstance(control, CommandButton)] == [
        "go",
        "go",
        "neutral",
        "neutral",
    ]


def test_own_buttons_of_nothing() -> None:
    assert own_buttons(None, 1) == ()
    assert own_buttons(club(), None) == ()
    assert own_buttons(club(), 99) == ()


def test_a_held_button_shows_lit_and_says_what_it_is() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        row = rows(app)[3]
        swop = row.held[0]
        await pilot.hover(swop)
        await pilot.pause()
        assert plain(app.query_one(HintRow)) == HINTS["swop"]
        await pilot.hover(row.label)
        await pilot.pause()
        assert plain(app.query_one(HintRow)) != HINTS["swop"]
        bridge.events.append(
            LiveChanged(live(seq=2, playbacks=(playback(3, "Chase", flash=True),)))
        )
        await settle(pilot, app)
        assert swop.lit

    drive(app, body)


def test_a_held_button_lets_go_when_its_strip_goes() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        swop = rows(app)[3].held[0]
        await pilot.mouse_down(swop)
        assert sent(bridge) == [("button 3 3 on", "ui", None, True)]
        bridge.events.append(LiveChanged(live(seq=2, page=PageView(2, "Washes"))))
        await settle(pilot, app)
        await pilot.pause()
        assert sent(bridge)[-1] == ("button 3 3 off", "ui", None, True)
        assert app.mouse_captured is None

    drive(app, body)


def test_letting_go_of_a_held_button_is_sent_once() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        swop = rows(app)[3].held[0]
        await pilot.mouse_down(swop)
        await pilot.mouse_up(swop)
        bridge.events.append(LiveChanged(live(seq=2, page=PageView(2, "Washes"))))
        await settle(pilot, app)
        await pilot.pause()
        assert [line for line, *_ in sent(bridge)] == ["button 3 3 on", "button 3 3 off"]

    drive(app, body)


def test_the_buttons_column_is_as_wide_as_its_widest_row() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, show=with_buttons(own(2, "go", "back", "release", "goto", goto="1")))
        await settle(pilot, app)
        shown = rows(app)
        widths = {row.box.region.width for row in shown.values()}
        assert widths == {19}
        header = app.query_one(PlaybackHeader)
        assert header.buttons.region.width == 19
        assert header.buttons.region.x == shown[2].box.region.x
        assert len({row.bar.region.x for row in shown.values()}) == 1

    drive(app, body, size=(150, 40))


def test_four_buttons_fit_a_row_at_100_columns() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, show=with_buttons(own(2, "go", "back", "release", "goto", goto="1")))
        await settle(pilot, app)
        panel = app.query_one("#playbacks").content_region
        row = rows(app)[2]
        assert len(row.buttons) == 4
        assert all(panel.contains_region(button.region) for button in row.buttons)

    drive(app, body, size=(100, 40))


def test_space_and_the_brackets_work_on_a_strip_with_no_go() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, show=with_buttons(own(1, "toggle", "release")))
        await settle(pilot, app)
        await pilot.press("space", "right_square_bracket")
        assert [line for line, *_ in sent(bridge)] == ["go 1", "fader 1 85%"]

    drive(app, body)


# -------------------------------------------------------------- an empty slot


def holding() -> Any:
    return programmer(values=(HeldValue(101, 1, "intensity", 0.5, None),), fixtures=1)


def test_record_on_an_empty_slot_is_grey_until_there_is_something_to_record() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        record = rows(app)[-4].record
        assert record is not None
        assert plain(record) == "[record]"
        assert record.inert
        assert "record slot 1.4" not in [item.line for item in app.current_page.items()]
        await pilot.click(record)
        assert sent(bridge) == []
        bridge.events.append(ProgrammerChanged(holding()))
        await settle(pilot, app)
        assert not record.inert
        assert "record slot 1.4" in [item.line for item in app.current_page.items()]
        await pilot.click(record)
        assert sent(bridge) == [("record slot 1.4", "ui", None, False)]
        bridge.events.append(ProgrammerChanged(programmer(version=3)))
        await settle(pilot, app)
        assert record.inert

    drive(app, body)


def test_a_stopped_effect_is_nothing_to_record() -> None:
    fx = EffectInfo("fx1", "Circle")
    assert not programmer(effects=(fx,), stopped=frozenset({"fx1"})).recordable()
    assert programmer(effects=(fx,)).recordable()
    assert not programmer().recordable()
    assert holding().recordable()


def test_a_slot_in_a_show_with_no_pages_has_no_record() -> None:
    row = PlaybackRow(1, None)
    assert row.record is None
    assert row.buttons == []


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
        labels = [item.line or item.prefill or item.label for item in app.current_page.items()]
        assert labels == [
            "button 1 1 on", "button 1 3 on", "button 2 1 on", "button 2 2 on",
            "button 3 1 on", "button 3 2 on",
            'tap "Speed 1"', 'bpm "Speed 1" 119', 'bpm "Speed 1" 121',
            "gm ", 'master "FX" ', 'master "Washes" ', "blackout on",
            "sel group 1", "sel group 2", "preset color 1", "preset color 2",
            "layout A console", "layout B stack", "layout C stage",
        ]  # fmt: skip
        await pilot.press("tab", "down", "down", "down")  # P2's second button
        await pilot.press("enter", "enter")
        assert app.cursor.active  # a line runs and the cursor stays
        assert [line for line, *_ in sent(bridge)] == ["button 2 2 on", "button 2 2 on"]
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
