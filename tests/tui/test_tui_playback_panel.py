"""F1's edit mode (``docs/plans/tui-pending-plan.md``, Phase 10): the grid of the
page's slots, the PLAYBACK panel, its lines and its dialogs. Headless, with a
fake bridge."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, get_type_hints

import pytest
from rich.text import Text
from textual.pilot import Pilot
from textual.widgets import Input, OptionList, Static
from tui_fakes import (
    FakeBridge,
    Reply,
    drive,
    live_state,
    make_app,
    playback,
    programmer,
    settle,
    show_model,
)

from busk.model.playback import Playback, PlaybackFlash
from busk_tui import commands
from busk_tui.model import (
    CommandDone,
    CueInfo,
    CueListInfo,
    LiveChanged,
    PageInfo,
    PageView,
    PlaybackInfo,
    ProgrammerChanged,
    ShowChanged,
    ShowModel,
)
from busk_tui.pages.busk import BuskHeader, BuskPage
from busk_tui.pages.busk_console import ConsoleLayout
from busk_tui.pages.busk_stack import StackLayout
from busk_tui.pages.busk_stage import StageLayout
from busk_tui.shell import BuskApp
from busk_tui.widgets.controls import ActionButton, ButtonStrip
from busk_tui.widgets.dialogs import ConfirmDialog, FormDialog, TextDialog
from busk_tui.widgets.log import LogView
from busk_tui.widgets.playback_panel import (
    TOGGLES,
    TYPED,
    CueListDialog,
    PickDialog,
    PlaybackDialog,
    PlaybackEditor,
    PlaybackPanel,
    SlotTile,
    check_buttons,
    check_colour,
    check_key,
    check_percent,
    check_whole,
    colour_text,
    in_hand,
    list_text,
    percent_value,
    playback_text,
    read_signed,
    slots_text,
    tab_word,
    whole_value,
)

SIZE = (150, 70)
"""Tall enough to click the panel's last row."""

RICH = PlaybackInfo(
    9,
    "Song",
    2,
    (1.0, 0.5, 0.0),
    ("go", "back", "goto"),
    "2",
    priority=60,
    fader="crossfade",
    ltpFaderMode="followFader",
    ltpThreshold=0.05,
    autoStart=False,
    autoRelease=False,
    flashLevel=0.5,
    flashLtp=False,
    flashBoost=10,
    exclusivity="base",
    protectFromSwop=True,
    releaseTime=2.5,
    uiColorText="#ff8000",
)
PLAIN = PlaybackInfo(1, "Warm", 1, None, ("toggle", "flash"))
OTHERS = (PlaybackInfo(3, "Chase", 3, None, ("go",)), PlaybackInfo(4, "Wash", 4, None, ("toggle",)))


def club(**changes: Any) -> ShowModel:
    """Page 1 has P1, P9, an empty slot and P3; page 2 has P4 and P9."""
    parts: dict[str, Any] = {
        "pages": (PageInfo(1, "Main", (1, 9, None, 3)), PageInfo(2, "Washes", (4, 9))),
        "playbacks": (
            PLAIN,
            *OTHERS,
            RICH,
        ),
        "cueLists": (
            CueListInfo(4, "Wash", "sequence", None, (CueInfo("1", "Wash", ()),)),
            CueListInfo(1, "Warm", "sequence", None, (CueInfo("1", "Warm", ()),)),
            CueListInfo(
                2,
                "Song",
                "sequence",
                None,
                (CueInfo("1", "Intro", ()), CueInfo("2", "Verse", ()), CueInfo("2.5", "Pre", ())),
            ),
            CueListInfo(3, "Chase", "chase", "bpm x 1", ()),
        ),
    }
    parts.update(changes)
    return show_model(**parts)


def live(**changes: Any) -> Any:
    parts: dict[str, Any] = {
        "playbacks": (
            playback(1, "Warm"),
            playback(3, "Chase"),
            playback(4, "Wash"),
            playback(9, "Song"),
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


def editor_of(app: BuskApp) -> PlaybackEditor:
    return app.query_one(PlaybackEditor)


def panel_of(app: BuskApp) -> PlaybackPanel:
    return app.query_one(PlaybackPanel)


def tile_of(app: BuskApp, number: int) -> SlotTile:
    return next(
        tile
        for tile in editor_of(app).tiles
        if tile.info is not None and tile.info.number == number
    )


def lines(bridge: FakeBridge) -> list[str]:
    return [sent.line for sent in bridge.sent]


def label_of(widget: Static) -> str:
    content = widget.content
    return content.plain if isinstance(content, Text) else str(content)


def row_of(strip: ButtonStrip) -> list[str]:
    return [button.label.plain.strip("[]") for button in strip.buttons]


def value_of(panel: PlaybackPanel, name: str) -> str:
    content = panel.settings[name].value.content
    return content.plain if isinstance(content, Text) else str(content)


def chips_of(panel: PlaybackPanel, name: str) -> tuple[list[str], list[str]]:
    """A strip's labels, and the lines of those a click runs."""
    strip = panel.strips[name]
    labels = [button.label.plain.strip("[]") for button in strip.buttons]
    return labels, [button.line.text for button in strip.buttons if not button.note]


async def open_editor(pilot: Pilot[int], app: BuskApp, on: int | None = None) -> PlaybackPanel:
    await settle(pilot, app)
    await pilot.click(app.query_one("#busk-edit"))
    await settle(pilot, app)
    if on is not None:
        await pilot.click(tile_of(app, on))
        await settle(pilot, app)
    return panel_of(app)


async def click_chip(pilot: Pilot[int], strip: ButtonStrip, label: str) -> None:
    for y, line in enumerate(line.plain for line in strip.lines(strip.size.width)):
        if f"[{label}]" in line:
            await pilot.click(strip, offset=(line.index(f"[{label}]") + 1, y))
            await pilot.pause()
            return
    raise AssertionError(f"no {label!r} in {strip.buttons}")


async def press(pilot: Pilot[int], app: BuskApp, button: ActionButton) -> None:
    await pilot.click(button)
    await settle(pilot, app)


async def type_in(pilot: Pilot[int], app: BuskApp, text: str) -> None:
    app.screen.query_one(Input).value = text
    await pilot.press("enter")
    await settle(pilot, app)


# ------------------------------------------------------------ entering it


@pytest.mark.parametrize(
    ("layout", "shown"), [("A", ConsoleLayout), ("B", StackLayout), ("C", StageLayout)]
)
def test_edit_puts_the_grid_in_every_layouts_place_and_done_gives_it_back(
    layout: str, shown: type
) -> None:
    bridge = FakeBridge()
    app = make_app(bridge, layout=layout)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app)
        assert not app.query_one(shown).display
        assert editor_of(app).display
        edit = app.query_one("#busk-edit", ActionButton)
        assert edit.label == "edit ●"
        assert edit.reverse
        await pilot.click(panel.done)
        await settle(pilot, app)
        assert app.query_one(shown).display
        assert not editor_of(app).display
        assert edit.label == "edit"
        assert not edit.reverse

    drive(app, body, size=SIZE)


def test_the_edit_button_turns_it_off_too() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app)
        await pilot.click(app.query_one("#busk-edit"))
        await settle(pilot, app)
        assert app.query_one(StackLayout).display
        assert not editor_of(app).display

    drive(app, body, size=SIZE)


def test_a_layout_chosen_in_edit_mode_waits_for_done() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app)
        app.action_layout("A")
        await settle(pilot, app)
        assert app.query_one(BuskHeader).shown_layout == "A"
        assert not app.query_one(ConsoleLayout).display
        assert not app.query_one(StackLayout).display
        await pilot.click(panel.done)
        await settle(pilot, app)
        assert app.query_one(ConsoleLayout).display

    drive(app, body, size=SIZE)


@pytest.mark.parametrize(("layout", "watching"), [("A", (True, False)), ("B", (False, True))])
def test_edit_mode_reads_no_output_and_no_effects(layout: str, watching: tuple[bool, bool]) -> None:
    bridge = FakeBridge()
    app = make_app(bridge, layout=layout)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app)
        await pilot.pause()
        assert bridge.watching == (False, False)
        await pilot.click(panel.done)
        await settle(pilot, app)
        assert bridge.watching == watching

    drive(app, body, size=SIZE)


def test_the_strips_show_what_changed_while_they_were_away() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app)
        before = app.query_one(StackLayout).rows
        bridge.events.append(
            ShowChanged(club(playbacks=(replace(PLAIN, buttons=("go",)), *OTHERS, RICH)))
        )
        await settle(pilot, app)
        assert app.query_one(StackLayout).rows is before  # not drawn while hidden
        await pilot.click(panel.done)
        await settle(pilot, app)
        row = app.query_one(StackLayout).rows[0]
        assert [button.label for button in row.buttons] == ["GO"]

    drive(app, body, size=SIZE)


# --------------------------------------------------------------- the grid


def test_the_grid_has_a_tile_per_slot_past_the_faders_cap_too() -> None:
    bridge = FakeBridge()
    app = make_app(bridge, faders=4)
    slots = (1, 9, None, 3, 4, None)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, club(pages=(PageInfo(1, "Main", slots),)))
        await open_editor(pilot, app)
        tiles = editor_of(app).tiles
        assert [tile.slot for tile in tiles] == [1, 2, 3, 4, 5, 6]
        assert [None if t.info is None else t.info.number for t in tiles] == list(slots)
        assert app.query_one(BuskHeader).left.plain.startswith("page 1 Main · slots 1–6")
        assert str(editor_of(app).slots.border_title) == "SLOTS · page 1 Main"

    drive(app, body, size=SIZE)


def test_a_tile_says_its_slot_its_playback_and_its_name() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app)
        tiles = editor_of(app).tiles
        first, second = tiles[1].render().plain.split("\n")
        assert first.split() == ["2", "P9"]
        assert second == "Song"
        assert tiles[2].render().plain == "3\nempty"

    drive(app, body, size=SIZE)


def test_a_show_with_no_pages_has_its_playbacks_by_number() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, club(pages=()), page=None)
        await open_editor(pilot, app)
        numbers = [t.info.number for t in editor_of(app).tiles if t.info is not None]
        assert numbers == [1, 3, 4, 9]
        assert str(editor_of(app).slots.border_title) == "SLOTS · click selects"

    drive(app, body, size=SIZE)


def test_a_click_on_a_tile_selects_and_runs_nothing() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app)
        assert tile_of(app, 1).has_class("-chosen")
        await pilot.click(tile_of(app, 9))
        await settle(pilot, app)
        assert app.view.playback == 9
        assert tile_of(app, 9).has_class("-chosen")
        assert not tile_of(app, 1).has_class("-chosen")
        assert panel.chosen() == RICH
        assert bridge.sent == []

    drive(app, body, size=SIZE)


def test_a_click_on_an_empty_slot_takes_it_in_hand_and_selects_nothing() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        editor = editor_of(app)
        await pilot.click(editor.tiles[2])
        await settle(pilot, app)
        assert app.view.playback == 9
        assert bridge.sent == []
        assert editor.slot == 3
        assert editor.tiles[2].has_class("-chosen")
        assert not tile_of(app, 9).has_class("-chosen")
        assert label_of(editor.slot_label) == "slot 3 · empty"
        assert row_of(editor.slot_edits) == ["new playback…", "place…"]

    drive(app, body, size=SIZE)


def test_another_page_shows_its_slots_and_the_panel_follows_the_selection() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app)
        assert panel.chosen() == PLAIN
        bridge.events.append(LiveChanged(live(seq=2, page=PageView(2, "Washes"))))
        await settle(pilot, app)
        assert [t.info and t.info.number for t in editor_of(app).tiles] == [4, 9, None]
        assert app.view.playback == 4  # P1 is not on it: the playback in its slot
        chosen = panel.chosen()
        assert chosen is not None
        assert chosen.number == 4
        assert tile_of(app, 4).has_class("-chosen")

    drive(app, body, size=SIZE)


def test_the_arrows_move_the_panel() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app)
        await pilot.press("right")
        await settle(pilot, app)
        assert panel.chosen() == RICH
        assert tile_of(app, 9).has_class("-chosen")

    drive(app, body, size=SIZE)


def test_the_tiles_stay_for_a_setting_and_go_for_a_name() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app)
        before = list(editor_of(app).tiles)
        bridge.events.append(
            ShowChanged(club(playbacks=(replace(PLAIN, priority=70), *OTHERS, RICH)))
        )
        await settle(pilot, app)
        assert editor_of(app).tiles == before
        bridge.events.append(
            ShowChanged(club(playbacks=(replace(PLAIN, name="Amber"), *OTHERS, RICH)))
        )
        await settle(pilot, app)
        assert tile_of(app, 1).render().plain.endswith("Amber")
        assert tile_of(app, 1).has_class("-chosen")  # still marked on the new tile

    drive(app, body, size=SIZE)


# ------------------------------------------------------------ what it shows


def test_the_panel_shows_all_a_playback_holds() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        assert str(panel.border_title) == "PLAYBACK · P9 Song"
        assert value_of(panel, "cue list") == "2 Song"
        assert value_of(panel, "buttons") == "go back goto"
        assert value_of(panel, "band") == "60"
        assert value_of(panel, "exclusive") == "base"
        assert value_of(panel, "flash level") == "50%"
        assert value_of(panel, "flash boost") == "10"
        assert value_of(panel, "threshold") == "5%"
        assert value_of(panel, "goto cue") == "2"
        assert value_of(panel, "release") == "2.5 s"
        assert value_of(panel, "colour").endswith("#ff8000")
        lit = {name: panel.strips[name] for name in ("fader", "LTP mode", *TOGGLES)}
        expected = {
            "fader": "crossfade",
            "LTP mode": "followFader",
            "flash LTP": "off",
            "auto start": "off",
            "auto release": "off",
            "swop protect": "on",
        }
        for name, word in expected.items():
            assert [b.label.plain for b in lit[name].buttons if b.note] == [f"[{word}]"]

    drive(app, body, size=SIZE)


def test_what_a_playback_is_without_says_none() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)
    bare = replace(PLAIN, buttons=())

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, club(playbacks=(bare, *OTHERS, RICH)))
        panel = await open_editor(pilot, app)
        for name in ("buttons", "exclusive", "flash boost", "goto cue", "colour"):
            assert value_of(panel, name) == "none"
        for name in ("exclusive", "flash boost", "goto cue", "colour"):
            assert not panel.settings[name].buttons[1].display, name

    drive(app, body, size=SIZE)


def test_a_colour_is_drawn_and_a_word_is_only_a_word() -> None:
    assert colour_text(RICH, "truecolor").plain == "██ #ff8000"
    words = colour_text(replace(RICH, uiColor=None, uiColorText="red"), "truecolor")
    assert words.plain == "red"
    assert colour_text(PLAIN, "truecolor").plain == "none"


def test_a_playback_the_show_does_not_have_gets_the_hint() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        bridge.events.append(
            ShowChanged(club(pages=(PageInfo(1, "Main", (1,)),), playbacks=(PLAIN,)))
        )
        await settle(pilot, app)
        app.view.playback = 77
        app._changed.add("playback")
        app._redraw()
        await pilot.pause()
        assert panel.hint.display
        assert not panel.body.display
        assert panel.done.display
        assert [stop.item.label for stop in panel.stops()] == ["done"]

    drive(app, body, size=SIZE)


# --------------------------------------------------- one control, one line


@pytest.mark.parametrize(
    ("strip", "chip", "line"),
    [
        ("fader", "size", "playback 9 fader size"),
        ("fader", "none", "playback 9 fader none"),
        ("LTP mode", "ignoreFader", "playback 9 ltpFaderMode ignoreFader"),
        ("flash LTP", "on", "playback 9 flash.includeLtp true"),
        ("auto start", "on", "playback 9 autoStart true"),
        ("auto release", "on", "playback 9 autoRelease true"),
        ("swop protect", "off", "playback 9 protectFromSwop false"),
    ],
)
def test_a_chip_is_one_line(strip: str, chip: str, line: str) -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        await click_chip(pilot, panel.strips[strip], chip)
        await settle(pilot, app)
        assert lines(bridge) == [line]

    drive(app, body, size=SIZE)


def test_the_lit_chip_runs_nothing() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        await click_chip(pilot, panel.strips["fader"], "crossfade")
        await click_chip(pilot, panel.strips["swop protect"], "on")
        await settle(pilot, app)
        assert bridge.sent == []

    drive(app, body, size=SIZE)


TYPED_CASES = [
    ("band", "70", "playback 9 priority 70"),
    ("band", "-5", "playback 9 priority -5"),
    ("exclusive", "wash 1", 'playback 9 exclusivity "wash 1"'),
    ("exclusive", "2", 'playback 9 exclusivity "2"'),
    ("flash level", "75", "playback 9 flash.level 0.75"),
    ("flash level", "14.3%", "playback 9 flash.level 0.143"),
    ("flash boost", "-3", "playback 9 flash.priorityBoost -3"),
    ("threshold", "2.5", "playback 9 ltpThreshold 0.025"),
    ("release", "0.125", "playback 9 releaseTime 0.125"),
    ("colour", "#00FF80", 'playback 9 uiColor "#00FF80"'),
]


@pytest.mark.parametrize(("name", "text", "line"), TYPED_CASES)
def test_a_typed_setting_is_one_line(name: str, text: str, line: str) -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        await press(pilot, app, panel.settings[name].buttons[0])
        assert isinstance(app.screen, TextDialog)
        await type_in(pilot, app, f" {text} ")
        assert not isinstance(app.screen, TextDialog)
        assert lines(bridge) == [line]

    drive(app, body, size=SIZE)


@pytest.mark.parametrize("name", sorted(TYPED))
def test_a_typed_setting_left_as_it_was_sends_nothing(name: str) -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        await press(pilot, app, panel.settings[name].buttons[0])
        await pilot.press("enter")
        await settle(pilot, app)
        assert not isinstance(app.screen, TextDialog)
        assert bridge.sent == []

    drive(app, body, size=SIZE)


def test_the_same_number_typed_otherwise_sends_nothing() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        await press(pilot, app, panel.settings["flash level"].buttons[0])
        await type_in(pilot, app, "50%")
        await press(pilot, app, panel.settings["band"].buttons[0])
        await type_in(pilot, app, "060")
        assert bridge.sent == []

    drive(app, body, size=SIZE)


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("band", "1.5"),
        ("band", ""),
        ("exclusive", "  "),
        ("flash level", "101"),
        ("flash level", "x"),
        ("flash boost", "abc"),
        ("threshold", "-1"),
        ("release", "-1"),
        ("colour", "ff8000"),
        ("colour", "#ff80"),
    ],
)
def test_a_dialog_keeps_what_busk_would_refuse(name: str, text: str) -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        await press(pilot, app, panel.settings[name].buttons[0])
        await type_in(pilot, app, text)
        assert isinstance(app.screen, TextDialog)
        assert bridge.sent == []

    drive(app, body, size=SIZE)


def test_a_setting_it_has_no_value_for_starts_empty_and_sends_what_is_typed() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app)
        await press(pilot, app, panel.settings["flash boost"].buttons[0])
        field = app.screen.query_one(Input)
        assert field.value == ""
        await type_in(pilot, app, "0")
        assert lines(bridge) == ["playback 1 flash.priorityBoost 0"]

    drive(app, body, size=SIZE)


@pytest.mark.parametrize(
    ("name", "line"),
    [
        ("exclusive", "playback 9 exclusivity none"),
        ("flash boost", "playback 9 flash.priorityBoost none"),
        ("colour", "playback 9 uiColor none"),
        ("goto cue", "playback 9 gotoCue none"),
    ],
)
def test_none_takes_an_optional_setting_away(name: str, line: str) -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        assert panel.settings[name].buttons[1].display
        await press(pilot, app, panel.settings[name].buttons[1])
        assert lines(bridge) == [line]

    drive(app, body, size=SIZE)


def test_rename_is_one_line_and_refuses_no_name() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        await press(pilot, app, panel.rename)
        await type_in(pilot, app, "  ")
        assert isinstance(app.screen, TextDialog)
        await type_in(pilot, app, "Song")  # the same: nothing to send
        assert bridge.sent == []
        await press(pilot, app, panel.rename)
        await type_in(pilot, app, 'Say "hi"')
        assert lines(bridge) == [r'rename playback 9 "Say \"hi\""']

    drive(app, body, size=SIZE)


def test_a_new_number_is_one_line_and_the_selection_follows_it() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)
    moved = replace(RICH, number=30)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        await press(pilot, app, panel.renumber)
        await type_in(pilot, app, "3")  # taken
        assert isinstance(app.screen, TextDialog)
        await type_in(pilot, app, "9")  # its own: nothing to send
        assert bridge.sent == []
        await press(pilot, app, panel.renumber)
        bridge.events.append(
            ShowChanged(
                club(
                    pages=(PageInfo(1, "Main", (1, 30, None, 3)),),
                    playbacks=(PLAIN, *OTHERS, moved),
                )
            )
        )
        await type_in(pilot, app, "30")
        await settle(pilot, app)
        assert lines(bridge) == ["playback 9 number 30"]
        assert app.view.playback == 30
        assert panel.chosen() == moved

    drive(app, body, size=SIZE)


def test_a_new_number_refused_leaves_the_selection() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)
    bridge.replies["playback 9 number 30"] = Reply(ok=False, text="no")

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        await press(pilot, app, panel.renumber)
        await type_in(pilot, app, "30")
        await settle(pilot, app)
        assert app.view.playback == 9

    drive(app, body, size=SIZE)


@pytest.mark.parametrize(
    ("text", "line"),
    [
        ("go flash", 'playback 9 buttons ["go", "flash"]'),
        ("go none swop", 'playback 9 buttons ["go", "none", "swop"]'),
        ("", "playback 9 buttons []"),
    ],
)
def test_the_buttons_are_one_line(text: str, line: str) -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        await press(pilot, app, panel.settings["buttons"].buttons[0])
        assert app.screen.query_one(Input).value == "go back goto"
        await type_in(pilot, app, text)
        assert lines(bridge) == [line]

    drive(app, body, size=SIZE)


def test_the_buttons_left_as_they_were_send_nothing() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        await press(pilot, app, panel.settings["buttons"].buttons[0])
        await type_in(pilot, app, "go  back goto ")
        assert bridge.sent == []

    drive(app, body, size=SIZE)


def test_a_word_that_is_no_button_stays_in_the_dialog() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        await press(pilot, app, panel.settings["buttons"].buttons[0])
        await type_in(pilot, app, "go [blink]")
        assert isinstance(app.screen, TextDialog)
        assert str(app.screen.error.content) == "each one of the words above"
        assert bridge.sent == []

    drive(app, body, size=SIZE)


def test_goto_takes_a_cue_of_its_list() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        goto = panel.settings["goto cue"].buttons[0]
        await press(pilot, app, goto)
        assert app.screen.query_one(Input).value == "2"
        await type_in(pilot, app, "7")
        assert isinstance(app.screen, TextDialog)
        assert str(app.screen.error.content) == "a cue of list 2"
        await type_in(pilot, app, "2")  # its own: nothing to send
        assert bridge.sent == []
        await press(pilot, app, goto)
        await type_in(pilot, app, "2.5")
        assert lines(bridge) == ["playback 9 goto 2.5"]

    drive(app, body, size=SIZE)


def test_goto_is_grey_on_a_list_with_no_cues() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, club(pages=(PageInfo(1, "Main", (3,)),)))
        panel = await open_editor(pilot, app)
        assert app.view.playback == 3
        assert panel.settings["goto cue"].buttons[0].inert
        assert value_of(panel, "cue list") == "3 Chase"

    drive(app, body, size=SIZE)


# ---------------------------------------------------------- the cue list


def test_the_picker_lists_the_cue_lists_by_number_from_the_one_it_runs() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        await press(pilot, app, panel.settings["cue list"].buttons[0])
        dialog = app.screen
        assert isinstance(dialog, CueListDialog)
        assert [info.number for info in dialog.lists] == [1, 2, 3, 4]
        assert dialog.query_one(OptionList).highlighted == 1
        await pilot.press("down", "enter")
        await settle(pilot, app)
        assert lines(bridge) == ["playback 9 cuelist 3"]

    drive(app, body, size=SIZE)


def test_the_picker_sends_nothing_for_the_list_it_runs_or_on_escape() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        await press(pilot, app, panel.settings["cue list"].buttons[0])
        await pilot.press("enter")
        await settle(pilot, app)
        assert not isinstance(app.screen, CueListDialog)
        await press(pilot, app, panel.settings["cue list"].buttons[0])
        await pilot.press("escape")
        await settle(pilot, app)
        assert not isinstance(app.screen, CueListDialog)
        assert bridge.sent == []

    drive(app, body, size=SIZE)


def test_a_click_on_the_picker_chooses() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        await press(pilot, app, panel.settings["cue list"].buttons[0])
        await pilot.click(app.screen.query_one(OptionList), offset=(3, 3))
        await settle(pilot, app)
        assert lines(bridge) == ["playback 9 cuelist 4"]

    drive(app, body, size=SIZE)


def test_a_picker_row_says_what_the_list_is() -> None:
    song = CueListInfo(9, "Song", "sequence", None, (CueInfo("1", "a", ()),))
    assert list_text(song).plain == "   9 Song · 1 cue"
    chase = CueListInfo(
        10, "Beat", "chase", "bpm x 1", (CueInfo("1", "a", ()), CueInfo("2", "b", ()))
    )
    assert list_text(chase).plain == "  10 Beat · 2 cues · chase"


@pytest.mark.parametrize("state", ["active", "releasing"])
def test_a_running_playback_keeps_its_list_and_says_why(state: str) -> None:
    bridge = FakeBridge()
    app = make_app(bridge)
    running = (playback(1, "Warm"), playback(9, "Song", state=state, cue="1"))

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, playbacks=running)
        panel = await open_editor(pilot, app, 9)
        button = panel.settings["cue list"].buttons[0]
        assert button.inert
        assert panel.why.display
        assert "P9 is running" in str(panel.why.content)
        await pilot.click(button)
        await settle(pilot, app)
        assert not isinstance(app.screen, CueListDialog)
        assert bridge.sent == []

    drive(app, body, size=SIZE)


def test_a_playback_that_stops_can_change_its_list_again() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)
    running = (playback(1, "Warm"), playback(9, "Song", state="active", cue="1"))

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, playbacks=running)
        panel = await open_editor(pilot, app, 9)
        bridge.events.append(LiveChanged(live(seq=2)))
        await settle(pilot, app)
        assert not panel.settings["cue list"].buttons[0].inert
        assert not panel.why.display

    drive(app, body, size=SIZE)


def test_a_running_playback_takes_its_other_settings() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)
    running = (playback(1, "Warm"), playback(9, "Song", state="active", cue="1"))

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, playbacks=running)
        panel = await open_editor(pilot, app, 9)
        await click_chip(pilot, panel.strips["fader"], "size")
        await press(pilot, app, panel.settings["release"].buttons[0])
        await type_in(pilot, app, "4")
        assert lines(bridge) == ["playback 9 fader size", "playback 9 releaseTime 4"]

    drive(app, body, size=SIZE)


# ----------------------------------------------------------- with the rest


def test_undo_redraws_the_panel() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        assert value_of(panel, "band") == "60"
        changed = replace(RICH, priority=70, exclusivity=None, fader="size")
        bridge.events.append(ShowChanged(club(playbacks=(PLAIN, *OTHERS, changed))))
        await settle(pilot, app)
        assert value_of(panel, "band") == "70"
        assert value_of(panel, "exclusive") == "none"
        assert not panel.settings["exclusive"].buttons[1].display
        assert [b.label.plain for b in panel.strips["fader"].buttons if b.note] == ["[size]"]
        bridge.events.append(ShowChanged(club()))  # undo
        await settle(pilot, app)
        assert value_of(panel, "band") == "60"
        assert value_of(panel, "exclusive") == "base"
        assert panel.settings["exclusive"].buttons[1].display

    drive(app, body, size=SIZE)


def test_the_f_keys_and_the_prompt_still_work_in_edit_mode() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        await pilot.press("f3")
        assert app.page == 3
        await pilot.press("f1")
        await settle(pilot, app)
        page = app.query_one(BuskPage)
        assert page.editing
        assert editor_of(app).display
        assert not app.query_one(StackLayout).display
        assert bridge.watching == (False, False)
        await pilot.press("r", "e", "n", "enter")
        await settle(pilot, app)
        assert lines(bridge) == ["ren"]
        assert app.query_one(LogView).entries[-1] == ("typed", "ren")

    drive(app, body, size=SIZE)


def test_space_still_runs_go_on_the_selected_playback() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        await pilot.press("space")
        await settle(pilot, app)
        assert lines(bridge) == ["go 9"]

    drive(app, body, size=SIZE)


def test_the_pane_cursor_reaches_the_tiles_and_the_panels_controls() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        labels = [item.line or item.label for item in app.current_page.items()]
        assert labels[:4] == ["page 2", "[+ page…]", "[rename…]", "delete page 1 cascade"]
        assert labels[4:9] == ["P1 Warm", "P9 Song", "slot 3", "P3 Chase", "slot 5"]
        assert labels[9:11] == ["[place…]", "page 1 slot 2 clear"]
        assert labels[11:14] == ["rename…", "number…", "delete"]
        assert "cue list list…" in labels
        assert "buttons buttons…" in labels
        assert "playback 9 fader size" in labels
        assert "playback 9 fader crossfade" not in labels  # lit: nothing to run
        assert "band band…" in labels
        assert "exclusive none" in labels
        assert "playback 9 autoStart true" in labels
        assert "colour colour…" in labels
        assert labels[-5:] == [
            "done",
            "layout A console",
            "layout B stack",
            "layout C stage",
            "edit",
        ]

    drive(app, body, size=SIZE)


def test_the_pane_cursor_chooses_a_tile_runs_a_chip_and_leaves() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app)
        tile = next(i for i, item in enumerate(app.current_page.items()) if item.label == "P9 Song")
        await pilot.press("tab", *["down"] * tile, "enter")
        await settle(pilot, app)
        assert app.view.playback == 9
        assert app.cursor.current is not None
        assert app.cursor.current.label == "P9 Song"
        items = app.current_page.items()
        target = next(i for i, item in enumerate(items) if item.line == "playback 9 fader size")
        index = app.cursor.index
        assert index is not None
        await pilot.press(*["down"] * (target - index), "enter")
        await settle(pilot, app)
        assert lines(bridge) == ["playback 9 fader size"]
        items = app.current_page.items()
        target = next(i for i, item in enumerate(items) if item.label == "done")
        index = app.cursor.index
        assert index is not None
        await pilot.press(*["down"] * (target - index), "enter")
        await settle(pilot, app)
        assert not app.query_one(BuskPage).editing
        assert app.query_one(StackLayout).display

    drive(app, body, size=SIZE)


def test_the_pane_cursor_has_no_stop_on_a_grey_button() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)
    running = (playback(1, "Warm"), playback(9, "Song", state="active", cue="1"))

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, playbacks=running)
        await open_editor(pilot, app, 9)
        labels = [item.line or item.label for item in app.current_page.items()]
        assert "cue list list…" not in labels
        assert sum(1 for label in labels if label.startswith("P") and label[1].isdigit()) == 3

    drive(app, body, size=SIZE)


def test_the_pane_cursor_opens_the_edit_mode_from_the_header() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        count = len(app.current_page.items())
        await pilot.press("tab", *["down"] * (count - 1), "enter")
        await settle(pilot, app)
        assert app.query_one(BuskPage).editing
        assert app.cursor.current is not None
        assert app.cursor.current.label == "edit"
        await pilot.press("enter")
        await settle(pilot, app)
        assert not app.query_one(BuskPage).editing

    drive(app, body, size=SIZE)


def test_below_100_columns_the_panel_goes_under_the_slots_and_a_click_reveals_it() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, club(pages=(PageInfo(1, "Main", (1, 9, 3, 4) * 5),)))  # room to scroll
        panel = await open_editor(pilot, app)
        slots = editor_of(app).slots
        assert panel.region.y >= slots.region.bottom
        assert panel.region.x == slots.region.x
        await pilot.click(tile_of(app, 9))
        await pilot.pause()
        await pilot.pause()
        page = app.query_one(BuskPage)
        assert page.scroll_offset.y > 0
        row = editor_of(app).slot_row
        assert page.region.y <= row.region.y < page.region.y + 4  # at the top, in sight
        assert panel.region.y < page.region.bottom  # and the panel under it

    drive(app, body, size=(99, 30))  # short enough that the panel alone would fill the view


def test_at_100_columns_the_panel_is_beside_the_slots() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app)
        assert panel.region.x > editor_of(app).slots.region.x
        assert panel.region.width == 52

    drive(app, body, size=(100, 60))


def test_the_tiles_take_as_many_columns_as_fit() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app)
        grid = editor_of(app).grid
        assert grid.styles.grid_size_columns == (grid.size.width + 1) // 16
        assert tile_of(app, 1).region.y == tile_of(app, 9).region.y

    drive(app, body, size=SIZE)


# ------------------------------------------------------------ small checks


def test_the_panel_holds_every_property_of_a_playback() -> None:
    """A new property of busk's fails here until it is on the panel, or named
    as left out. The plan's list has neither notes nor tags."""
    held = {
        "name": "rename",
        "number": "renumber",
        "cueListId": "cue list",
        "buttons": "buttons",
        "fader": "fader",
        "ltpFaderMode": "LTP mode",
        "gotoCue": "goto cue",
        "flash": "flash",
    }
    typed = {typed.prop for typed in TYPED.values()}
    toggles = {prop for prop, _ in TOGGLES.values()}
    left_out = {"id", "notes", "tags"}
    for prop in get_type_hints(Playback, include_extras=False):
        assert prop in held or prop in typed or prop in toggles or prop in left_out, prop
    for prop in get_type_hints(PlaybackFlash, include_extras=False):
        assert f"flash.{prop}" in typed | toggles, prop


@pytest.mark.parametrize(
    ("text", "value"), [("5", 5), ("-5", -5), ("0", 0), ("1.5", None), ("x", None), ("", None)]
)
def test_a_signed_number(text: str, value: int | None) -> None:
    assert read_signed(text) == value


def test_the_small_checks() -> None:
    assert check_whole(" -3 ") is None
    assert check_whole("1e3") == "a whole number"
    assert whole_value("-3") == "-3"
    assert check_percent("100") is None
    assert check_percent("0%") is None
    assert check_percent("100.1") == "a level from 0 to 100%"
    assert percent_value("14.3") == "0.143"
    assert percent_value("100%") == "1"
    assert check_key("a") is None
    assert check_key(" ") == "a key cannot be empty"
    assert check_colour("#AbCdEf") is None
    assert check_colour("#abcde") == "a colour as #rrggbb"
    assert check_buttons("") is None
    assert check_buttons("go none") is None
    assert check_buttons("go NONE") == "each one of the words above"


# -------------------------------------------------------- pages and slots


async def click_tile(pilot: Pilot[int], app: BuskApp, slot: int) -> None:
    await pilot.click(editor_of(app).tiles[slot - 1])
    await settle(pilot, app)


async def tap(pilot: Pilot[int], app: BuskApp, strip: ButtonStrip, label: str) -> None:
    await click_chip(pilot, strip, label)
    await settle(pilot, app)


async def pick(pilot: Pilot[int], app: BuskApp, number: int) -> None:
    """Choose the row of the open picker with ``number``."""
    dialog = app.screen
    assert isinstance(dialog, PickDialog)
    dialog.options.highlighted = dialog.numbers.index(number)
    await pilot.press("enter")
    await settle(pilot, app)


async def form(pilot: Pilot[int], app: BuskApp, *values: str) -> None:
    """Fill the open form's fields, and press Enter."""
    dialog = app.screen
    assert isinstance(dialog, FormDialog)
    for field, value in zip(dialog.inputs, values, strict=False):
        field.value = value
    await pilot.press("enter")
    await settle(pilot, app)


def ask_everything(bridge: FakeBridge, question: str = "Delete it?") -> None:
    bridge.confirmation = lambda line: question  # type: ignore[method-assign]


@pytest.mark.parametrize(
    ("slots", "tiles"),
    [
        ((), [None]),
        ((1,), [1, None]),
        ((1, None), [1, None]),
        ((None, 3), [None, 3, None]),
    ],
)
def test_the_grid_ends_in_an_empty_tile(
    slots: tuple[int | None, ...], tiles: list[int | None]
) -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, club(pages=(PageInfo(1, "Main", slots),)))
        await open_editor(pilot, app)
        assert [t.info and t.info.number for t in editor_of(app).tiles] == tiles
        assert app.query_one(BuskHeader).left.plain.startswith(
            f"page 1 Main · slots {f'1–{len(slots)}' if slots else 'none'}"
        )

    drive(app, body, size=SIZE)


@pytest.mark.parametrize(
    ("slot", "slots", "selected", "moved", "hand"),
    [
        (None, (1, 9, None), 9, False, 2),  # the selected playback's
        (None, (1, 9, None), 5, False, None),  # it is not on the page
        (3, (1, 9, None), 9, True, 3),  # an empty slot stays
        (1, (1, 9, None), 9, True, 2),  # the selection moved off what it holds
        (1, (1, 9, None), 9, False, 1),  # it did not: a new show, or a click on its way
        (2, (9, 9), 9, True, 2),  # the second of two
        (1, (9, 9), 9, True, 1),
        (4, (1, 9), 9, False, 2),  # one the grid no longer has
        (4, (1, 9), 5, False, None),
    ],
)
def test_the_slot_in_hand(
    slot: int | None,
    slots: tuple[int | None, ...],
    selected: int,
    moved: bool,
    hand: int | None,
) -> None:
    assert in_hand(slot, slots, selected, moved) == hand


def test_the_row_says_what_the_slot_in_hand_holds_and_follows_the_selection() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app)
        editor = editor_of(app)
        assert label_of(editor.slot_label) == "slot 1 · P1 Warm"  # the selected playback's
        assert row_of(editor.slot_edits) == ["place…", "clear"]
        assert tile_of(app, 1).has_class("-chosen")
        await pilot.press("right")
        await settle(pilot, app)
        assert label_of(editor.slot_label) == "slot 2 · P9 Song"
        assert tile_of(app, 9).has_class("-chosen")
        assert not tile_of(app, 1).has_class("-chosen")

    drive(app, body, size=SIZE)


def test_nothing_is_in_hand_when_the_selection_is_not_on_the_page() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, club(pages=(PageInfo(1, "Main", (None, 9)),)))
        await settle(pilot, app)
        app.view.playback = 1
        await open_editor(pilot, app)
        editor = editor_of(app)
        assert editor.slot is None
        assert label_of(editor.slot_label) == "click a slot"
        assert editor.slot_edits.buttons == ()

    drive(app, body, size=SIZE)


def test_new_playback_is_a_list_then_a_form_then_one_line_and_selects_it() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        editor = editor_of(app)
        await click_tile(pilot, app, 3)
        await tap(pilot, app, editor.slot_edits, "new playback…")
        dialog = app.screen
        assert isinstance(dialog, CueListDialog)
        assert dialog.title_text == "NEW PLAYBACK · 1.3"
        assert dialog.options.highlighted == 0  # no list to start at
        await pick(pilot, app, 2)
        form_screen = app.screen
        assert isinstance(form_screen, FormDialog)
        assert form_screen.title_text == "NEW PLAYBACK · 1.3"
        assert [field.value for field in form_screen.inputs] == ["10", "Song"]  # the list's name
        assert form_screen.note.startswith("taken: 1, 3–4, 9\n")
        await form(pilot, app, "30", "Encore")
        assert lines(bridge) == ['playback add 30 cuelist 2 at 1.3 "Encore"']
        await settle(pilot, app)
        assert app.view.playback == 30

    drive(app, body, size=SIZE)


def test_a_new_playback_with_no_name_leaves_it_to_busk() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        await click_tile(pilot, app, 5)  # the empty tile past the last slot
        await tap(pilot, app, editor_of(app).slot_edits, "new playback…")
        await pick(pilot, app, 3)
        await form(pilot, app, "12", "  ")
        assert lines(bridge) == ["playback add 12 cuelist 3 at 1.5"]

    drive(app, body, size=SIZE)


def test_escape_at_either_step_of_a_new_playback_sends_nothing() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        editor = editor_of(app)
        await click_tile(pilot, app, 3)
        await tap(pilot, app, editor.slot_edits, "new playback…")
        await pilot.press("escape")
        await settle(pilot, app)
        assert not isinstance(app.screen, PickDialog)
        await tap(pilot, app, editor.slot_edits, "new playback…")
        await pick(pilot, app, 1)
        assert isinstance(app.screen, FormDialog)
        await pilot.press("escape")
        await settle(pilot, app)
        assert not isinstance(app.screen, FormDialog)
        assert bridge.sent == []
        assert app.view.playback == 9

    drive(app, body, size=SIZE)


def test_a_taken_number_stays_in_the_new_playback_form() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        await click_tile(pilot, app, 3)
        await tap(pilot, app, editor_of(app).slot_edits, "new playback…")
        await pick(pilot, app, 1)
        await form(pilot, app, "9", "Other")
        assert isinstance(app.screen, FormDialog)
        assert bridge.sent == []

    drive(app, body, size=SIZE)


def test_a_new_playback_refused_leaves_the_selection() -> None:
    bridge = FakeBridge()
    line = 'playback add 30 cuelist 1 at 1.3 "Warm"'
    bridge.replies[line] = Reply(ok=False, text="slot 3 is in use on page 1")
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        await click_tile(pilot, app, 3)
        await tap(pilot, app, editor_of(app).slot_edits, "new playback…")
        await pick(pilot, app, 1)
        await form(pilot, app, "30")
        assert lines(bridge) == [line]
        await settle(pilot, app)
        assert app.view.playback == 9

    drive(app, body, size=SIZE)


def test_a_show_with_no_cue_lists_has_no_new_playback() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, club(cueLists=()))
        await open_editor(pilot, app, 9)
        editor = editor_of(app)
        await click_tile(pilot, app, 3)
        new, place = editor.slot_edits.buttons
        assert new.note
        assert not place.note
        await tap(pilot, app, editor.slot_edits, "new playback…")
        assert not isinstance(app.screen, PickDialog)
        assert "new playback…" not in [item.label.strip("[]") for item in app.current_page.items()]

    drive(app, body, size=SIZE)


def test_a_show_with_no_playbacks_has_nothing_to_place() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, club(playbacks=(), pages=(PageInfo(1, "Main", ()),)), playbacks=())
        await open_editor(pilot, app)
        editor = editor_of(app)
        await click_tile(pilot, app, 1)
        new, place = editor.slot_edits.buttons
        assert not new.note
        assert place.note

    drive(app, body, size=SIZE)


def test_place_lists_every_playback_with_where_it_sits_and_is_one_line() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        await tap(pilot, app, editor_of(app).slot_edits, "place…")
        dialog = app.screen
        assert isinstance(dialog, PlaybackDialog)
        assert dialog.title_text == "PLACE · 1.2"
        assert dialog.numbers == [1, 3, 4, 9]
        assert dialog.options.highlighted == 3  # what the slot holds
        await pick(pilot, app, 4)
        assert lines(bridge) == ["page 1 slot 2 playback 4"]
        await settle(pilot, app)
        assert app.view.playback == 4

    drive(app, body, size=SIZE)


def test_place_on_an_empty_slot_starts_at_the_selected_playback() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        await click_tile(pilot, app, 3)
        await tap(pilot, app, editor_of(app).slot_edits, "place…")
        dialog = app.screen
        assert isinstance(dialog, PlaybackDialog)
        assert dialog.numbers[dialog.options.highlighted or 0] == 9
        await pilot.press("enter")
        await settle(pilot, app)
        assert lines(bridge) == ["page 1 slot 3 playback 9"]  # a playback on two slots

    drive(app, body, size=SIZE)


def test_place_starts_at_what_the_slot_holds_though_another_is_selected() -> None:
    """P4 reached the slot in hand by a line typed at the prompt."""
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        editor = editor_of(app)
        bridge.events.append(ShowChanged(club(pages=(PageInfo(1, "Main", (1, 4, 9, 3)),))))
        await settle(pilot, app)
        assert app.view.playback == 9
        assert editor.slot == 2  # the selection has not moved, so the hand has not
        await tap(pilot, app, editor.slot_edits, "place…")
        dialog = app.screen
        assert isinstance(dialog, PlaybackDialog)
        assert dialog.numbers[dialog.options.highlighted or 0] == 4

    drive(app, body, size=SIZE)


def test_placing_what_the_slot_holds_or_escape_sends_nothing() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        editor = editor_of(app)
        await tap(pilot, app, editor.slot_edits, "place…")
        await pick(pilot, app, 9)
        await tap(pilot, app, editor.slot_edits, "place…")
        await pilot.press("escape")
        await settle(pilot, app)
        assert bridge.sent == []

    drive(app, body, size=SIZE)


@pytest.mark.parametrize("show_first", [True, False])
def test_the_slot_placed_on_stays_in_hand_whichever_comes_first(show_first: bool) -> None:
    """P9 is on slot 2 too, and a new show before the reply moves the hand."""
    bridge = FakeBridge(auto_reply=False)
    app = make_app(bridge)
    placed = club(pages=(PageInfo(1, "Main", (1, 9, 9, 3)),))

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 1)
        editor = editor_of(app)
        await click_tile(pilot, app, 3)
        await tap(pilot, app, editor.slot_edits, "place…")
        await pick(pilot, app, 9)
        sent = bridge.sent[-1]
        assert sent.line == "page 1 slot 3 playback 9"
        reply = CommandDone(sent.ticket, sent.line, sent.origin, True, (), 0.0, False)
        bridge.events += (
            [ShowChanged(placed), reply] if show_first else [reply, ShowChanged(placed)]
        )
        await settle(pilot, app)
        await settle(pilot, app)
        assert app.view.playback == 9
        assert editor.slot == 3
        assert label_of(editor.slot_label) == "slot 3 · P9 Song"
        await tap(pilot, app, editor.slot_edits, "clear")
        assert bridge.sent[-1].line == "page 1 slot 3 clear"

    drive(app, body, size=SIZE)


def test_a_tile_clicked_stays_in_hand_while_the_selection_catches_up() -> None:
    """A frame from the engine between the click and the selection."""
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, club(pages=(PageInfo(1, "Main", (1, 9, None, 9)),)))
        await open_editor(pilot, app, 1)
        editor = editor_of(app)
        view = app.view
        editor.on_slot_tile_picked(SlotTile.Picked(4, 9))
        page = app.query_one(BuskPage)
        assert view.playback == 1
        page.update_view(view, frozenset({"live"}))
        assert editor.slot == 4
        await settle(pilot, app)
        assert app.view.playback == 9
        assert editor.slot == 4

    drive(app, body, size=SIZE)


def test_a_click_on_a_tile_the_grid_has_lost_raises_nothing() -> None:
    """A click on its way when the page gets shorter."""
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        editor = editor_of(app)
        editor.on_slot_tile_picked(SlotTile.Picked(40, None))
        await settle(pilot, app)
        assert editor.slot == 2  # back on the selection's
        assert app.view.playback == 9

    drive(app, body, size=SIZE)


def test_the_arrows_take_the_slot_of_the_selection_in_hand() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        editor = editor_of(app)
        assert editor.slot == 2
        await pilot.press("right")
        await settle(pilot, app)
        assert app.view.playback == 3
        assert editor.slot == 4

    drive(app, body, size=SIZE)


def test_a_placement_answered_on_another_page_leaves_the_hand_alone() -> None:
    bridge = FakeBridge(auto_reply=False)
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        editor = editor_of(app)
        await click_tile(pilot, app, 3)
        await tap(pilot, app, editor.slot_edits, "place…")
        await pick(pilot, app, 4)
        sent = bridge.sent[-1]
        bridge.events.append(LiveChanged(live(seq=2, page=PageView(2, "Washes"))))
        await settle(pilot, app)
        bridge.events.append(CommandDone(sent.ticket, sent.line, sent.origin, True, (), 0.0, False))
        await settle(pilot, app)
        await settle(pilot, app)
        assert app.view.playback == 4
        assert editor.slot == 1  # P4's slot on page 2, not slot 3 of page 1

    drive(app, body, size=SIZE)


def test_clear_is_one_line_and_asks_nothing_and_the_slot_stays_in_hand() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        editor = editor_of(app)
        await tap(pilot, app, editor.slot_edits, "clear")
        assert lines(bridge) == ["page 1 slot 2 clear"]
        bridge.events.append(ShowChanged(club(pages=(PageInfo(1, "Main", (1, None, None, 3)),))))
        await settle(pilot, app)
        assert editor.slot == 2
        assert label_of(editor.slot_label) == "slot 2 · empty"
        assert editor.tiles[1].has_class("-chosen")

    drive(app, body, size=SIZE)


def test_a_playback_on_two_slots_of_a_page_keeps_the_one_clicked() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)
    slots = (1, 9, None, 9)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, club(pages=(PageInfo(1, "Main", slots),)))
        await open_editor(pilot, app)
        editor = editor_of(app)
        await click_tile(pilot, app, 4)
        assert app.view.playback == 9
        assert editor.slot == 4
        assert editor.tiles[3].has_class("-chosen")
        assert not editor.tiles[1].has_class("-chosen")
        await tap(pilot, app, editor.slot_edits, "clear")
        assert lines(bridge) == ["page 1 slot 4 clear"]

    drive(app, body, size=SIZE)


def test_delete_is_busks_question_then_one_line_and_the_selection_moves_on() -> None:
    bridge = FakeBridge()
    ask_everything(bridge, 'Delete playback 9 "Song"? It leaves pages 1, 2.')
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        panel = await open_editor(pilot, app, 9)
        await press(pilot, app, panel.delete)
        assert isinstance(app.screen, ConfirmDialog)
        assert "It leaves pages 1, 2." in app.screen.question
        await pilot.press("n")
        await settle(pilot, app)
        assert bridge.sent == []
        await press(pilot, app, panel.delete)
        await pilot.press("y")
        await settle(pilot, app)
        assert lines(bridge) == ["delete playback 9 cascade"]
        bridge.events.append(
            ShowChanged(
                club(
                    pages=(
                        PageInfo(1, "Main", (1, None, None, 3)),
                        PageInfo(2, "Washes", (4, None)),
                    ),
                    playbacks=(PLAIN, *OTHERS),
                )
            )
        )
        await settle(pilot, app)
        assert app.view.playback == 1
        chosen = panel.chosen()
        assert chosen is not None
        assert chosen.number == 1

    drive(app, body, size=SIZE)


def test_a_tab_per_page_by_number_and_the_page_shown_runs_nothing() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)
    pages = (PageInfo(2, "Washes", (4, 9)), PageInfo(1, "Main", (1, 9, None, 3)))

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, club(pages=pages))
        await open_editor(pilot, app)
        tabs = editor_of(app).tabs
        assert row_of(tabs) == ["1 Main", "2 Washes", "+ page…"]
        first, second, _ = tabs.buttons
        assert first.note  # the page shown
        assert second.line == commands.go_page(2)
        await tap(pilot, app, tabs, "2 Washes")
        assert lines(bridge) == ["page 2"]
        assert bridge.sent[0].performance

    drive(app, body, size=SIZE)


def test_another_page_takes_nothing_in_hand_from_the_last() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        editor = editor_of(app)
        await click_tile(pilot, app, 3)  # empty, and past the end of page 2
        bridge.events.append(LiveChanged(live(seq=2, page=PageView(2, "Washes"))))
        await settle(pilot, app)
        assert app.view.playback == 9  # on page 2 too
        assert editor.slot == 2
        assert label_of(editor.slot_label) == "slot 2 · P9 Song"
        assert label_of(editor.page_label) == "page 2 Washes"
        tabs = editor.tabs.buttons
        assert [button.note for button in tabs] == [False, True, False]

    drive(app, body, size=SIZE)


def test_a_long_page_name_is_cut_on_its_tab() -> None:
    assert tab_word(PageInfo(3, "Encore", ())) == "3 Encore"
    assert tab_word(PageInfo(3, "x" * 16, ())) == "3 " + "x" * 16
    assert tab_word(PageInfo(3, "x" * 17, ())) == "3 " + "x" * 15 + "…"


def test_a_new_page_is_one_line_and_stays_on_the_page_it_was_on() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app)
        await tap(pilot, app, editor_of(app).tabs, "+ page…")
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert dialog.title_text == "NEW PAGE"
        assert [field.value for field in dialog.inputs] == ["3", ""]
        await form(pilot, app, "7", 'The "End"')
        assert lines(bridge) == [r'page add 7 "The \"End\""']
        await settle(pilot, app)
        assert lines(bridge) == [r'page add 7 "The \"End\""']  # no page 7 to follow it

    drive(app, body, size=SIZE)


def test_a_new_page_with_no_name_leaves_it_to_busk_and_a_taken_number_stays() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app)
        await tap(pilot, app, editor_of(app).tabs, "+ page…")
        await form(pilot, app, "2")
        assert isinstance(app.screen, FormDialog)
        assert bridge.sent == []
        await form(pilot, app, "4")
        assert lines(bridge) == ["page add 4"]

    drive(app, body, size=SIZE)


def test_rename_page_is_one_line_and_left_as_it_was_sends_nothing() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app)
        edits = editor_of(app).page_edits
        assert row_of(edits) == ["rename…", "delete"]
        await tap(pilot, app, edits, "rename…")
        assert isinstance(app.screen, TextDialog)
        assert app.screen.title_text == "RENAME · page 1"
        await type_in(pilot, app, "Main")
        assert bridge.sent == []
        await tap(pilot, app, edits, "rename…")
        await type_in(pilot, app, "  ")
        assert isinstance(app.screen, TextDialog)  # no name: it stays
        await type_in(pilot, app, "Set 2")
        assert lines(bridge) == ['rename page 1 "Set 2"']

    drive(app, body, size=SIZE)


def test_delete_page_is_busks_question_then_one_line() -> None:
    bridge = FakeBridge()
    ask_everything(bridge, 'Delete page 1 "Main"?')
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app)
        edits = editor_of(app).page_edits
        await tap(pilot, app, edits, "delete")
        assert isinstance(app.screen, ConfirmDialog)
        await pilot.press("y")
        await settle(pilot, app)
        assert lines(bridge) == ["delete page 1 cascade"]

    drive(app, body, size=SIZE)


def test_the_page_shown_deleted_gives_way_to_the_one_the_engine_moved_to() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        editor = editor_of(app)
        bridge.events += [
            ShowChanged(club(pages=(PageInfo(2, "Washes", (4, 9)),))),
            LiveChanged(live(seq=2, page=PageView(2, "Washes"))),
        ]
        await settle(pilot, app)
        assert [t.info and t.info.number for t in editor.tiles] == [4, 9, None]
        assert row_of(editor.tabs) == ["2 Washes", "+ page…"]
        assert label_of(editor.page_label) == "page 2 Washes"
        assert app.view.playback == 9

    drive(app, body, size=SIZE)


def test_a_show_with_no_pages_only_adds_one() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, club(pages=()), page=None)
        panel = await open_editor(pilot, app)
        editor = editor_of(app)
        assert row_of(editor.tabs) == ["+ page…"]
        assert not editor.page_row.display
        assert not editor.slot_row.display
        assert [t.info and t.info.number for t in editor.tiles] == [1, 3, 4, 9]  # no spare one
        assert str(editor.slots.border_title) == "SLOTS · click selects"
        await click_tile(pilot, app, 4)
        assert app.view.playback == 9
        assert panel.chosen() == RICH
        assert tile_of(app, 9).has_class("-chosen")
        await tap(pilot, app, editor.tabs, "+ page…")
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert [field.value for field in dialog.inputs] == ["1", ""]
        await form(pilot, app, "1", "Main")
        assert lines(bridge) == ['page add 1 "Main"']
        labels = [item.line or item.label for item in app.current_page.items()]
        assert "[place…]" not in labels
        assert "[rename…]" not in labels

    drive(app, body, size=SIZE)


def test_a_new_page_has_a_tile_to_start_on() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, club(pages=(PageInfo(1, "Main", ()),)))
        await open_editor(pilot, app)
        editor = editor_of(app)
        assert [t.slot for t in editor.tiles] == [1]
        await click_tile(pilot, app, 1)
        await tap(pilot, app, editor.slot_edits, "place…")
        await pick(pilot, app, 3)
        assert lines(bridge) == ["page 1 slot 1 playback 3"]

    drive(app, body, size=SIZE)


def test_the_pane_cursor_takes_an_empty_slot_in_hand() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await open_editor(pilot, app, 9)
        editor = editor_of(app)
        items = app.current_page.items()
        target = next(i for i, item in enumerate(items) if item.label == "slot 3")
        await pilot.press("tab", *["down"] * target, "enter")
        await settle(pilot, app)
        assert editor.slot == 3
        assert app.cursor.current is not None
        assert app.cursor.current.label == "slot 3"
        assert row_of(editor.slot_edits) == ["new playback…", "place…"]

    drive(app, body, size=SIZE)


def test_where_a_playback_sits() -> None:
    pages = (PageInfo(1, "Main", (1, 9, None, 9)), PageInfo(2, "Washes", (9,)))
    assert slots_text(9, pages) == "1.2 1.4 2.1"
    assert slots_text(1, pages) == "1.1"
    assert slots_text(30, pages) == ""
    assert playback_text(RICH, pages).plain == "   9 Song · 1.2 1.4 2.1"
    assert playback_text(PLAIN, ()).plain == "   1 Warm · on no page"
