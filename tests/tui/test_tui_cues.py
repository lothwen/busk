"""F4 Cues (spec §8.4, plan Phase 3): the list browser, the chosen list's
meta line and cue rows as stored, ``▶`` from the snapshot, going to a cue,
the edits' pre-fills, the buttons, which list shows, and the pane cursor.
Headless, with a fake bridge."""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from rich.text import Text
from textual.pilot import Pilot
from textual.screen import Screen
from textual.widgets import Input
from tui_fakes import (
    FakeBridge,
    Reply,
    click_cell,
    column,
    drive,
    live_state,
    make_app,
    playback,
    programmer,
    settle,
    show_model,
)

import busk
from busk_tui import bridge as busk_bridge
from busk_tui import colors
from busk_tui.formats import delay_text, stored_text, time_text
from busk_tui.model import (
    ChaseRate,
    CommandDone,
    CueInfo,
    CueListInfo,
    EffectInfo,
    FamilyTiming,
    FixtureInfo,
    GroupInfo,
    HeldValue,
    LiveChanged,
    MasterView,
    PageInfo,
    PlaybackInfo,
    ProgrammerChanged,
    ShowChanged,
    ShowModel,
    StoredValue,
    Targets,
)
from busk_tui.pages.cues import CuesPage, meta_text, mode_line
from busk_tui.shell import BuskApp
from busk_tui.widgets.chase_dialog import ChaseDialog
from busk_tui.widgets.controls import ButtonStrip
from busk_tui.widgets.cue_dialogs import BEZIER, POINTS, SECONDS, CurveDialog, TimeDialog
from busk_tui.widgets.cuetable import CueListTable, CueTable, cue_cells
from busk_tui.widgets.dialogs import ConfirmDialog, FormDialog, TextDialog
from busk_tui.widgets.log import LogView

HEADS = Targets(group=GroupInfo(1, "Heads"))
WASHES = Targets(group=GroupInfo(2, "Washes"))

SONG = CueListInfo(
    9,
    "Song",
    "sequence",
    None,
    (
        CueInfo(
            "1",
            "Intro",
            (),
            fadeIn=3.0,
            fadeOut=3.0,
            curve="easeInOut",
            values=(
                StoredValue("intensity", WASHES, "literal", value=0.6),
                StoredValue("color", WASHES, "preset", preset="Blue", color=(0.0, 0.0, 1.0)),
            ),
        ),
        CueInfo(
            "2",
            "Verse",
            (),
            fadeIn=2.0,
            fadeOut=2.0,
            families=(FamilyTiming("position", 4.0),),
            values=(
                StoredValue(
                    "color",
                    HEADS,
                    "literal",
                    value=(("r", 1.0), ("g", 0.5), ("b", 0.0)),
                    color=(1.0, 0.5, 0.0),
                ),
            ),
        ),
        CueInfo(
            "3",
            "Pre",
            (),
            fadeIn=1.0,
            fadeOut=3.0,
            delayIn=1.0,
            delayOut=2.0,
            trigger="wait",
            delay=8.0,
            values=(
                StoredValue(
                    "intensity",
                    Targets(elements=((101, 1), (102, 1))),
                    "spread",
                    value=0.0,
                    to=1.0,
                ),
                StoredValue("intensity", WASHES, "literal", value=0.3),
            ),
        ),
        CueInfo(
            "4",
            "",
            (EffectInfo("rainbow", "Rainbow", WASHES),),
            trigger="follow",
            delay=4.0,
            values=(StoredValue("color", HEADS, "perTarget"),),
        ),
    ),
    tracking=True,
)
CHASE = CueListInfo(
    10,
    "Chase",
    "chase",
    "bpm x 1 bounce",
    (CueInfo("1", "Step 1", ()), CueInfo("2", "Step 2", ())),
    crossfade=0.25,
    rate=ChaseRate(None, None, 1.0, "bounce"),
)
LOOP = CueListInfo(
    11,
    "Loop",
    "sequence",
    "hz 2 forward",
    (CueInfo("1", "Go", ()),),
    crossfade=0.5,
    rate=ChaseRate(2.0, None, 1.0, "forward"),
)
SPARE = CueListInfo(
    21, "Spare", "sequence", None, (CueInfo("1", "One", ()), CueInfo("2", "Two", ()))
)


def cues_show(**changes: Any) -> ShowModel:
    parts: dict[str, Any] = {
        "pages": (PageInfo(1, "Main", (9, 10, 11)),),
        "playbacks": (
            PlaybackInfo(9, "Song", 9, None),
            PlaybackInfo(10, "Chase", 10, None),
            PlaybackInfo(11, "Loop", 11, None),
            PlaybackInfo(12, "Loop 2", 11, None),
        ),
        "cueLists": (SONG, CHASE, LOOP, SPARE),
        "fixtures": (FixtureInfo(101, 1), FixtureInfo(102, 1)),
    }
    parts.update(changes)
    return show_model(**parts)


def live(**changes: Any) -> Any:
    parts: dict[str, Any] = {
        "playbacks": (
            playback(9, "Song", state="active", level=0.8, cue="2", cueName="Verse", cueCount=4),
            playback(10, "Chase", chase=True, cueCount=2),
            playback(11, "Loop"),
            playback(12, "Loop 2", state="active", level=0.5, cue="1"),
        ),
    }
    parts.update(changes)
    return live_state(**parts)


def started(bridge: FakeBridge, **changes: Any) -> None:
    bridge.events += [ShowChanged(cues_show()), LiveChanged(live(**changes))]


def on_f4(bridge: FakeBridge) -> BuskApp:
    return make_app(bridge, page=4)


def page(app: BuskApp) -> CuesPage:
    return app.query_one(CuesPage)


def plain(widget: Any) -> str:
    rendered = widget.content if hasattr(widget, "content") else widget.render()
    return rendered.plain if isinstance(rendered, Text) else str(rendered)


def words(strip: ButtonStrip) -> str:
    """What a strip shows, however it wraps."""
    return " ".join(strip.render().plain.split("\n"))


def held(**changes: Any) -> ProgrammerChanged:
    """The programmer holds a value on 101, and 101 and 102 are selected."""
    value = HeldValue(101, 1, "intensity", 0.5, None)
    parts: dict[str, Any] = {"values": (value,), "selection": ((101, 1), (102, 1)), "fixtures": 1}
    parts.update(changes)
    return ProgrammerChanged(programmer(**parts))


async def click_label(pilot: Pilot[int], strip: ButtonStrip, label: str) -> None:
    lines = [line.plain for line in strip.lines(strip.size.width)]
    for y, line in enumerate(lines):
        if label in line:
            await pilot.click(strip, offset=(line.index(label) + 1, y))
            return
    raise AssertionError(f"no {label!r} in {lines}")


async def open_edit(pilot: Pilot[int], app: BuskApp, label: str) -> Screen[Any]:
    """The dialog of one of the chosen cue's edits."""
    await click_label(pilot, app.query_one("#cue-edits", ButtonStrip), label)
    await pilot.pause()
    return app.screen


async def ok(pilot: Pilot[int]) -> None:
    await pilot.press("enter")
    await pilot.pause()


def note_of(dialog: Screen[Any]) -> str:
    """A dialog's first note: what its fields mean."""
    return str(dialog.query(".note").first().render())


def on_cue(app: BuskApp, number: str) -> None:
    """``number`` chosen, as a click on its row, without going to it."""
    page(app).choose_cue(number, go=False)


# ------------------------------------------------------------- formatting


def test_times_triggers_and_values_as_stored() -> None:
    intro, verse, pre, fourth = SONG.cues
    assert time_text(intro) == "3"
    assert time_text(verse) == "2, position 4"
    assert time_text(pre) == "1/3"
    assert delay_text(intro) == ""
    assert delay_text(pre) == "1/2"
    cells = cue_cells(SONG, pre, False, "256")
    assert [cells[name].plain for name in ("cue", "time", "delay", "follow", "wait")] == [
        "9/3", "1/3", "1/2", "—", "8",
    ]  # fmt: skip
    assert cells["intensity"].plain == "spread 0%→100%, 30%"
    assert cue_cells(SONG, intro, False, "256")["color"].plain == "██ Blue"
    assert cue_cells(SONG, verse, False, "256")["color"].plain == "██ 1.00 0.50 0.00"
    four = cue_cells(SONG, fourth, True, "256")
    assert (four["marker"].plain, four["name"].plain, four["follow"].plain) == ("▶", "—", "4")
    assert four["color"].plain == "░░ per target"
    assert four["fx"].plain == "rainbow"
    assert four["intensity"].plain == "—"
    assert stored_text(StoredValue("gobo", HEADS, "literal", value="breakup")) == "breakup"
    colour_spread = StoredValue("color", HEADS, "spread", value=(("r", 1.0),), to=(("r", 0.0),))
    assert stored_text(colour_spread) == "spread"


def test_the_meta_line() -> None:
    show = cues_show()
    state = live()
    assert meta_text(SONG, show, state).plain == (
        "mode sequence · tracking   playback P9 @ 80%   groups Washes, Heads"
        "   fixtures 101 thru 102"
    )
    assert meta_text(CHASE, show, state).plain == (
        "mode chase bpm x 1 bounce crossfade 0.25   playback P10 @ 0%"
    )
    assert meta_text(LOOP, show, state).plain == "mode sequence   playback P11 @ 0%, P12 @ 50%"
    assert meta_text(SPARE, show, state).plain == (
        "mode sequence   no playback: assign the list to a playback first"
    )


# ------------------------------------------------------------------ page


def test_the_lists_and_the_selected_playbacks_list() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        lists = app.query_one(CueListTable)
        assert column(lists, "number") == ["9", "10", "11", "21"]
        assert column(lists, "kind") == ["seq", "chase", "seq", "seq"]
        assert column(lists, "cues") == ["4", "2", "1", "2"]
        assert column(lists, "playback") == ["P9", "P10", "P11", "—"]
        assert app.view.playback == 9  # the page's first slot
        assert lists.chosen == 0
        assert str(page(app).panel.border_title) == "CUELIST 9 · Song"
        cues = app.query_one(CueTable)
        assert column(cues, "cue") == ["9/1", "9/2", "9/3", "9/4"]
        assert column(cues, "marker") == ["", "▶", "", ""]
        assert cues.chosen == 1  # nothing chosen: the current cue
        await pilot.press("right")  # P10: its list
        await settle(pilot, app)
        assert lists.chosen == 1
        assert column(cues, "cue") == ["10/1", "10/2"]

    drive(app, body)


def test_the_marker_follows_the_snapshot() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        bridge.events.append(
            LiveChanged(live(seq=2, playbacks=(playback(9, "Song", state="active", cue="3"),)))
        )
        await settle(pilot, app)
        cues = app.query_one(CueTable)
        assert column(cues, "marker") == ["", "", "▶", ""]
        bridge.events.append(LiveChanged(live(seq=3, playbacks=(playback(9, "Song"),))))
        await settle(pilot, app)
        assert column(cues, "marker") == ["", "", "", ""]
        assert cues.chosen == 0  # idle: the first

    drive(app, body)


def test_a_row_goes_to_its_cue_and_an_edit_cell_opens_its_dialog() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        cues = app.query_one(CueTable)
        await click_cell(pilot, cues, 2, "name")
        assert [(s.line, s.origin, s.performance) for s in bridge.sent] == [
            ("goto 9 3", "ui", True)
        ]
        assert cues.chosen == 2
        for name, kind in (
            ("time", TimeDialog),
            ("delay", FormDialog),
            ("curve", CurveDialog),
            ("follow", TextDialog),
            ("wait", TextDialog),
        ):
            await click_cell(pilot, cues, 2, name)
            await pilot.pause()
            dialog = app.screen
            assert isinstance(dialog, kind), name
            assert dialog.title_text == f"{name.upper()} · cue 9/3"
            await pilot.press("escape")
            await pilot.pause()
            assert app.prompt.value == ""
        await click_cell(pilot, cues, 0, "time")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, TimeDialog)
        assert dialog.title_text == "TIME · cue 9/1"
        assert cues.chosen == 0  # an edit chooses the row, without going to it
        await pilot.press("escape")
        await pilot.pause()
        assert [s.line for s in bridge.sent] == ["goto 9 3"]

    drive(app, body)


def test_the_edits_act_on_the_chosen_cue() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        assert plain(app.query_one("#cue-edit-label")) == "edit cue 9/2 Verse"
        edits = app.query_one("#cue-edits", ButtonStrip)
        assert words(edits) == (
            "[time…] [delay…] [curve…] [go…] [follow…] [wait…] [rename…]"
            " [release…] [record at…] [merge] [replace] [remove] [delete]"
        )
        await click_label(pilot, edits, "go…")  # a whole line: Enter runs it
        assert app.prompt.value == "cue 9/2 go"
        await pilot.press("escape")
        dialog = await open_edit(pilot, app, "rename…")
        assert isinstance(dialog, TextDialog)
        assert (dialog.title_text, dialog.query_one(Input).value) == ("RENAME · cue 9/2", "Verse")
        await pilot.press("escape")
        await pilot.pause()
        dialog = await open_edit(pilot, app, "delay…")
        assert isinstance(dialog, FormDialog)
        assert dialog.title_text == "DELAY · cue 9/2"
        await pilot.press("escape")
        await pilot.pause()
        assert bridge.sent == []

    drive(app, body)


def test_the_buttons() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        buttons = app.query_one("#cue-buttons", ButtonStrip)
        assert buttons.render().plain == ("[GO] [BACK] [record cue 9] [cuelist 9 chase bpm x 1]")
        for label in ("GO", "BACK", "record cue 9", "cuelist 9 chase bpm x 1"):
            await click_label(pilot, buttons, label)
        assert [(s.line, s.performance) for s in bridge.sent] == [
            ("go 9", True),
            ("back 9", True),
            ("record cue 9", False),
            ("cuelist 9 chase bpm x 1", False),
        ]
        page(app).choose_list(10)
        await settle(pilot, app)
        assert buttons.render().plain == "[GO] [BACK] [record cue 10] [cuelist 10 sequence]"
        page(app).choose_list(11)  # a sequence that keeps its chase settings
        await settle(pilot, app)
        assert "[cuelist 11 chase hz 2 forward crossfade 0.5]" in buttons.render().plain

    drive(app, body)


SAY_HI = 'master add speed "Say \\"hi\\"" bpm 90'


@pytest.mark.parametrize(
    ("masters", "chase", "toggle"),
    [
        (
            (),
            "cuelist 10 chase hz 1.23456789 forward crossfade 0.125",
            "cuelist 10 chase hz 1.23456789 forward crossfade 0.125",
        ),
        (
            (),
            "cuelist 10 chase bpm x 0.123456789 reverse",
            "cuelist 10 chase bpm x 0.123456789 reverse",
        ),
        ((), "cuelist 10 chase hz 0.0000001 bounce", "cuelist 10 chase hz 0.0000001 bounce"),
        (
            (),
            "cuelist 10 chase bpm x 3 random crossfade 1",
            "cuelist 10 chase bpm x 3 random crossfade 1",
        ),
        (
            ('master add speed "Speed 2" bpm 90',),
            'cuelist 10 chase bpm "Speed 2" x 0.5 bounce',
            'cuelist 10 chase bpm "Speed 2" x 0.5 bounce',
        ),
        (
            ('master add speed "Speed 2" bpm 90',),
            'cuelist 10 chase bpm "Speed 1" x 2 forward',  # the first of two: named too
            'cuelist 10 chase bpm "Speed 1" x 2 forward',
        ),
        (
            (SAY_HI,),
            'cuelist 10 chase bpm "Say \\"hi\\"" x 1.5 random crossfade 0.333',
            'cuelist 10 chase bpm "Say \\"hi\\"" x 1.5 random crossfade 0.333',
        ),
    ],
)
def test_the_toggle_back_to_a_chase_keeps_what_busk_stored(
    club_path: Path, masters: tuple[str, ...], chase: str, toggle: str
) -> None:
    """A chase, then a sequence, then the toggle: the list's ``chase`` as it was."""
    document, _ = busk.load_show(club_path)
    show = busk.OfflineShow(document)
    for line in (*masters, chase, "cuelist 10 sequence"):
        assert show.execute(line).ok, line

    def stored() -> Any:
        return copy.deepcopy(next(c for c in show.show["cueLists"] if c["number"] == 10))

    before = stored()
    assert before["mode"] == "sequence"
    cue_list = busk_bridge.show_model(show.show).cue_list(10)
    assert cue_list is not None
    line = mode_line(cue_list)
    assert line.text == toggle
    assert show.execute(line.text).ok, line.text
    after = stored()
    assert after["mode"] == "chase"
    assert after["chase"] == before["chase"]


def test_the_toggle_on_a_list_never_chased_is_on_the_beat(club_path: Path) -> None:
    document, _ = busk.load_show(club_path)
    show = busk.OfflineShow(document)
    cue_list = busk_bridge.show_model(show.show).cue_list(9)  # Song: no chase settings
    assert cue_list is not None
    assert cue_list.rate is None
    line = mode_line(cue_list)
    assert line.text == "cuelist 9 chase bpm x 1"
    assert show.execute(line.text).ok
    song = next(c for c in show.show["cueLists"] if c["number"] == 9)
    assert (song["mode"], song["chase"]["rate"]["multiplier"]) == ("chase", 1)


def test_the_toggle_writes_numbers_as_they_are() -> None:
    """No rounding and no exponent, for a list the model gives."""
    rate = ChaseRate(1.23456789, None, 1.0, "bounce")
    many = CueListInfo(10, "Chase", "sequence", "hz 1.23457 bounce", (), 0.125, rate=rate)
    assert mode_line(many).text == "cuelist 10 chase hz 1.23456789 bounce crossfade 0.125"
    beat = ChaseRate(None, None, 1e-7, "reverse")
    tiny = CueListInfo(10, "Chase", "sequence", "bpm x 1e-07 reverse", (), 0.0, rate=beat)
    assert mode_line(tiny).text == "cuelist 10 chase bpm x 0.0000001 reverse"
    named = ChaseRate(None, 'Say "hi"', 2.0, "forward")
    quoted = CueListInfo(10, "Chase", "sequence", 'bpm "Say "hi"" x 2 forward', (), rate=named)
    assert mode_line(quoted).text == 'cuelist 10 chase bpm "Say \\"hi\\"" x 2 forward'
    assert mode_line(replace(quoted, mode="chase")).text == "cuelist 10 sequence"


def test_a_list_click_selects_its_playback_and_a_list_without_one_only_shows() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        lists = app.query_one(CueListTable)
        await click_cell(pilot, lists, 2, "name")  # Loop: P11 and P12 run it
        await settle(pilot, app)
        assert app.view.playback == 11
        assert lists.chosen == 2
        await click_cell(pilot, lists, 3, "name")  # Spare: no playback
        await settle(pilot, app)
        assert app.view.playback == 11
        assert lists.chosen == 3
        buttons = app.query_one("#cue-buttons", ButtonStrip)
        assert buttons.render().plain == "[record cue 21] [cuelist 21 chase bpm x 1]"
        cues = app.query_one(CueTable)
        await click_cell(pilot, cues, 1, "name")
        assert bridge.sent == []  # no go-to without a playback
        assert cues.chosen == 1
        assert plain(app.query_one("#cue-edit-label")) == "edit cue 21/2 Two"
        await pilot.press("left")  # P10 … the list follows the selected playback again
        await settle(pilot, app)
        assert lists.chosen == 1

    drive(app, body)


def test_the_list_s_playback_is_the_selected_one_when_it_runs_it() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        app._select_playback(12)
        await settle(pilot, app)
        cues = app.query_one(CueTable)
        assert column(cues, "marker") == ["▶"]  # P12 is on cue 1
        await click_cell(pilot, cues, 0, "cue")
        assert bridge.sent[-1].line == "goto 12 1"

    drive(app, body)


def test_the_pane_cursor_goes_to_cues_then_buttons_edits_and_lists() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        items = app.current_page.items()
        assert [(i.line or i.prefill or i.label) for i in items] == [
            "goto 9 1", "goto 9 2", "goto 9 3", "goto 9 4",
            "go 9", "back 9", "record cue 9", "cuelist 9 chase bpm x 1",
            "cuelist 9 tracking false", "[chase…]", "[rename…]", "delete cuelist 9 cascade",
            "[time…]", "[delay…]", "[curve…]", "cue 9/2 go",
            "[follow…]", "[wait…]", "[rename…]", "[release…]", "[delete]",
            "cuelist 9 Song", "cuelist 10 Chase", "cuelist 11 Loop", "cuelist 21 Spare",
            "[+ list…]",
        ]  # fmt: skip
        await pilot.press("tab", "down", "down", "enter")  # cue 3: goes, and is chosen
        assert app.cursor.active
        assert [s.line for s in bridge.sent] == ["goto 9 3"]
        assert plain(app.query_one("#cue-edit-label")) == "edit cue 9/3 Pre"
        await pilot.press(*["down"] * 20, "enter")  # list 10: chosen, the cursor stays
        await settle(pilot, app)
        assert app.cursor.active
        assert app.query_one(CueListTable).chosen == 1
        assert app.view.playback == 10
        # the cues of list 10 come first now: the cursor reaches them
        labels = [(i.line or i.label) for i in app.current_page.items()]
        assert labels[:2] == ["goto 10 1", "goto 10 2"]
        await pilot.press(*["up"] * 40, "enter")
        assert bridge.sent[-1].line == "goto 10 1"

    drive(app, body)


def test_an_empty_show_and_an_empty_list() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(ShowChanged(show_model()))
        await settle(pilot, app)
        assert "no cue lists" in app.query_one(CueListTable).render().plain
        assert not page(app).panel.display
        empty = CueListInfo(5, "Empty", "sequence", None, ())
        bridge.events.append(ShowChanged(show_model(cueLists=(empty,))))
        await settle(pilot, app)
        assert page(app).panel.display
        assert app.query_one(CueTable).render().plain == (
            "no cues · record cue 5 records the programmer as one"
        )

    drive(app, body)


# ------------------------------------------------------- a cue's controls


def test_what_records_is_grey_with_nothing_to_record() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        edits = app.query_one("#cue-edits", ButtonStrip)
        gone = ["[record at…]", "[merge]", "[replace]", "[remove]"]
        shown = {button.label.plain: button for button in edits.buttons}
        for label in gone:
            assert shown[label].note, label  # no click, no pane cursor
            assert shown[label].label.style == colors.BORDER, label
        items = [i.line or i.label for i in app.current_page.items()]
        assert not set(gone) & set(items)
        await click_label(pilot, edits, "merge")
        await click_label(pilot, edits, "record at…")
        assert bridge.sent == []
        assert not isinstance(app.screen, FormDialog)

        bridge.events.append(held())
        await settle(pilot, app)
        shown = {button.label.plain: button for button in edits.buttons}
        assert not any(shown[label].note for label in gone)

        bridge.events.append(held(values=(), effects=(EffectInfo("fx1", "Rainbow", WASHES),)))
        await settle(pilot, app)
        assert not edits.buttons[-2].note  # an effect that runs records
        bridge.events.append(
            held(
                values=(),
                effects=(EffectInfo("fx1", "Rainbow", WASHES),),
                stopped=frozenset(("fx1",)),
            )
        )
        await settle(pilot, app)
        assert edits.buttons[-2].note  # a stopped one does not

    drive(app, body)


def test_merge_runs_and_replace_and_remove_ask_first() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        bridge.events.append(held())
        await settle(pilot, app)
        edits = app.query_one("#cue-edits", ButtonStrip)
        await click_label(pilot, edits, "merge")
        assert [(s.line, s.origin) for s in bridge.sent] == [("record cue 9/2 merge", "ui")]
        for label, question, line in (
            (
                "replace",
                'Replace what cue 9/2 "Verse" holds with the programmer?',
                "record cue 9/2 replace",
            ),
            (
                "remove",
                'Remove the programmer\'s attributes from cue 9/2 "Verse"?',
                "record cue 9/2 remove",
            ),
        ):
            bridge.sent.clear()
            await click_label(pilot, edits, label)
            await pilot.pause()
            dialog = app.screen
            assert isinstance(dialog, ConfirmDialog)
            assert dialog.question == question
            await pilot.press("n")
            await pilot.pause()
            assert bridge.sent == []
            assert ("info", f"cancelled: {line}") in app.query_one(LogView).entries
            await click_label(pilot, edits, label)
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            assert bridge.lines() == [line]

    drive(app, body)


def test_delete_asks_and_says_when_a_playback_is_on_the_cue() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        edits = app.query_one("#cue-edits", ButtonStrip)
        await click_label(pilot, edits, "delete")  # P9 is on cue 2
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)
        assert dialog.question.splitlines() == [
            'Delete cue 9/2 "Verse"?',
            "P9 is on it, and will leave it at once.",
        ]
        await pilot.press("n")
        await pilot.pause()
        assert bridge.sent == []
        await click_cell(pilot, app.query_one(CueTable), 3, "time")  # cue 4, no name: chosen
        await pilot.press("escape")
        await click_label(pilot, edits, "delete")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)
        assert dialog.question == "Delete cue 9/4?"
        await pilot.press("y")
        await pilot.pause()
        assert [(s.line, s.origin) for s in bridge.sent] == [("delete cue 9/4", "ui")]

    drive(app, body)


def test_two_playbacks_on_the_cue_are_both_named() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        bridge.events.append(
            LiveChanged(
                live(
                    seq=2,
                    playbacks=(
                        playback(11, "Loop", state="active", cue="1"),
                        playback(12, "Loop 2", state="active", cue="1"),
                    ),
                )
            )
        )
        page(app).choose_list(11)
        await settle(pilot, app)
        await click_label(pilot, app.query_one("#cue-edits", ButtonStrip), "delete")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)
        assert dialog.question.splitlines()[1] == "P11, P12 are on it, and will leave it at once."

    drive(app, body)


def test_record_at_refuses_a_cue_that_exists_and_chooses_the_new_one() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        bridge.events.append(held())
        await settle(pilot, app)
        edits = app.query_one("#cue-edits", ButtonStrip)
        await click_label(pilot, edits, "record at…")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert [field.value for field in dialog.inputs] == ["5", ""]  # after the last, as busk
        for typed, problem in (
            ("3", "cue 3 exists"),
            ("03", "cue 03 exists"),
            ("two", "a cue number, such as 3 or 2.5"),
            ("", "a cue number, such as 3 or 2.5"),
            ("1.2.3", "a cue number, such as 3 or 2.5"),
        ):
            dialog.inputs[0].value = typed
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen is dialog, typed
            assert str(dialog.error.render()) == problem
        assert bridge.sent == []
        dialog.inputs[0].value = " 2.5 "
        dialog.inputs[1].value = ' The "Bridge" '
        await pilot.press("enter")
        await pilot.pause()
        assert bridge.lines() == [r'''record cue 9/2.5 "The \"Bridge\""''']
        await settle(pilot, app)
        added = CueInfo("2.5", "The Bridge", ())
        with_it = (*SONG.cues[:2], added, *SONG.cues[2:])
        bridge.events.append(
            ShowChanged(cues_show(cueLists=(CueListInfo(9, "Song", "sequence", None, with_it),)))
        )
        await settle(pilot, app)
        assert app.query_one(CueTable).chosen == 2
        assert plain(app.query_one("#cue-edit-label")) == "edit cue 9/2.5 The Bridge"

    drive(app, body)


def test_record_at_without_a_name_and_on_a_list_with_no_cues() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)
    empty = CueListInfo(5, "Empty", "sequence", None, ())

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(ShowChanged(show_model(cueLists=(empty,))))
        bridge.events.append(held())
        await settle(pilot, app)
        edits = app.query_one("#cue-edits", ButtonStrip)
        assert edits.render().plain == "[record at…]"
        assert plain(app.query_one("#cue-edit-label")) == ""
        await click_label(pilot, edits, "record at…")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert dialog.inputs[0].value == "1"
        await pilot.press("enter")
        await pilot.pause()
        assert bridge.lines() == ["record cue 5/1"]

    drive(app, body)


def test_a_refused_record_at_chooses_nothing() -> None:
    bridge = FakeBridge(replies={"record cue 9/7": Reply(ok=False, text="error: no")})
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        bridge.events.append(held())
        await settle(pilot, app)
        await click_label(pilot, app.query_one("#cue-edits", ButtonStrip), "record at…")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        dialog.inputs[0].value = "7"
        await pilot.press("enter")
        await settle(pilot, app)
        assert page(app).cue is None
        assert ("error", "no") in app.query_one(LogView).entries

    drive(app, body)


def test_a_record_at_that_runs_after_another_list_was_chosen_chooses_nothing() -> None:
    bridge = FakeBridge(auto_reply=False)
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        bridge.events.append(held())
        await settle(pilot, app)
        await click_label(pilot, app.query_one("#cue-edits", ButtonStrip), "record at…")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        sent = bridge.sent[-1]
        assert sent.line == "record cue 9/5"
        page(app).choose_list(10)
        bridge.events.append(
            CommandDone(
                ticket=sent.ticket,
                line=sent.line,
                origin="ui",
                ok=True,
                lines=(),
                seconds=0.0,
                quit=False,
            )
        )
        await settle(pilot, app)
        assert page(app).list == 10
        assert page(app).cue is None

    drive(app, body)


def test_release_takes_targets_and_attributes() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        bridge.events.append(held())
        await settle(pilot, app)
        edits = app.query_one("#cue-edits", ButtonStrip)
        await click_label(pilot, edits, "release…")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert [field.value for field in dialog.inputs] == ["101 thru 102", ""]  # the selection
        await pilot.press("enter")
        await pilot.pause()
        assert bridge.lines() == ["cue 9/2 release 101 thru 102"]
        bridge.sent.clear()
        await click_label(pilot, edits, "release…")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        dialog.inputs[0].value = "   "
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is dialog
        assert str(dialog.error.render()) == "the targets: group 1, or 101 thru 104"
        dialog.inputs[0].value = " group 1 "
        dialog.inputs[1].value = " pan  tilt "
        await pilot.press("enter")
        await pilot.pause()
        assert bridge.lines() == ["cue 9/2 release group 1 only pan tilt"]

    drive(app, body)


def test_release_starts_empty_with_nothing_selected() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        await click_label(pilot, app.query_one("#cue-edits", ButtonStrip), "release…")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert dialog.inputs[0].value == ""
        await pilot.press("escape")
        await pilot.pause()
        assert bridge.sent == []

    drive(app, body)


# --------------------------------------------- a cue's timing and name


def one_cue(cue: CueInfo) -> ShowChanged:
    """The show with list 9 holding ``cue`` alone."""
    song = CueListInfo(9, "Song", "sequence", None, (cue,))
    return ShowChanged(cues_show(cueLists=(song, CHASE, LOOP, SPARE)))


def test_the_time_form_starts_at_the_cues_times_and_sends_what_changed() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        on_cue(app, "3")  # in 1, out 3
        await settle(pilot, app)
        dialog = await open_edit(pilot, app, "time…")
        assert isinstance(dialog, TimeDialog)
        assert dialog.target.chosen == "cue"
        assert (dialog.fade_in.value, dialog.fade_out.value) == ("1", "3")
        assert all(found.display for found in dialog.cue_rows)
        assert not any(found.display for found in dialog.family_rows)
        assert dialog.focused is dialog.fade_in
        assert note_of(dialog) == (
            "in: intensity rising, and families without their own\nout: intensity falling"
        )
        await ok(pilot)  # unchanged: nothing to send
        assert app.screen is not dialog
        assert bridge.sent == []
        for first, second, line in (
            ("2", "3", "cue 9/3 time 2/3"),
            ("3", " 3.0 ", "cue 9/3 time 3"),
        ):
            dialog = await open_edit(pilot, app, "time…")
            assert isinstance(dialog, TimeDialog)
            dialog.fade_in.value, dialog.fade_out.value = first, second
            await ok(pilot)
            assert bridge.lines()[-1] == line
        dialog = await open_edit(pilot, app, "time…")
        assert isinstance(dialog, TimeDialog)
        for typed in ("-1", "x", "", "1e3", "50%"):
            dialog.fade_out.value = typed
            await ok(pilot)
            assert app.screen is dialog, typed
            assert str(dialog.error.render()) == SECONDS
        await pilot.press("escape")
        await pilot.pause()
        assert len(bridge.sent) == 2

        on_cue(app, "4")  # 0 s, no family of its own
        await settle(pilot, app)
        dialog = await open_edit(pilot, app, "time…")
        assert isinstance(dialog, TimeDialog)
        dialog.target.pick("intensity")
        await pilot.pause()
        assert (dialog.fade.value, dialog.delay.value) == ("0", "0")
        await ok(pilot)  # what it takes now, but not its own yet: sent
        assert bridge.lines()[-1] == "cue 9/4 time intensity 0"

    drive(app, body)


def test_the_time_form_sets_a_familys_own_and_keeps_its_curve() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)
    intro = CueInfo(
        "1",
        "Intro",
        (),
        fadeIn=3.0,
        fadeOut=1.0,
        delayIn=0.5,
        families=(FamilyTiming("position", 4.0), FamilyTiming("beam", 2.0, 0.5, "snapEnd")),
    )

    async def family(pilot: Pilot[int], name: str) -> TimeDialog:
        dialog = await open_edit(pilot, app, "time…")
        assert isinstance(dialog, TimeDialog)
        dialog.target.pick(name)
        await pilot.pause()
        return dialog

    async def body(pilot: Pilot[int]) -> None:
        bridge.events += [one_cue(intro), LiveChanged(live())]
        await settle(pilot, app)
        dialog = await family(pilot, "position")
        assert not any(found.display for found in dialog.cue_rows)
        assert all(found.display for found in dialog.family_rows)
        assert (dialog.fade.value, dialog.delay.value) == ("4", "0")
        assert note_of(dialog) == "position's own, in place of the cue's"
        await ok(pilot)  # unchanged
        assert bridge.sent == []
        dialog = await family(pilot, "position")
        dialog.fade.value = "5"
        await ok(pilot)
        assert bridge.lines() == ["cue 9/1 time position 5"]
        dialog = await family(pilot, "beam")
        assert (dialog.fade.value, dialog.delay.value) == ("2", "0.5")
        assert note_of(dialog) == "beam's own, in place of the cue's\nits curve, snapEnd, stays"
        dialog.delay.value = "1"
        await ok(pilot)
        assert bridge.lines()[-1] == "cue 9/1 time beam 2 delay 1 snapEnd"
        dialog = await family(pilot, "color")  # none of its own: what it takes now, the cue's in
        assert (dialog.fade.value, dialog.delay.value) == ("3", "0.5")
        assert note_of(dialog) == "color takes the cue's in now"
        await ok(pilot)  # it is new: sent as it is
        assert bridge.lines()[-1] == "cue 9/1 time color 3 delay 0.5"
        dialog = await family(pilot, "focus")
        dialog.delay.value = "0"
        await ok(pilot)
        assert bridge.lines()[-1] == "cue 9/1 time focus 3"
        dialog = await family(pilot, "shutter")
        dialog.fade.value = "x"
        await ok(pilot)
        assert str(dialog.error.render()) == SECONDS
        dialog.target.pick("cue")
        await pilot.pause()
        assert str(dialog.error.render()) == ""  # it was of a field that went
        assert (dialog.fade_in.value, dialog.fade_out.value) == ("3", "1")
        await pilot.press("escape")
        await pilot.pause()
        assert len(bridge.sent) == 4

    drive(app, body)


def test_the_time_forms_chips_by_keys() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        dialog = await open_edit(pilot, app, "time…")
        assert isinstance(dialog, TimeDialog)
        await pilot.press("shift+tab")
        assert dialog.focused is dialog.target
        await pilot.press("right", "right")
        await pilot.pause()
        assert dialog.target.chosen == "position"  # cue 9/2's own: 4
        await pilot.press("tab")
        assert dialog.focused is dialog.fade
        await pilot.press(*"6", "enter")  # Tab selects what it holds: typing replaces it
        await pilot.pause()
        assert bridge.lines() == ["cue 9/2 time position 6"]

    drive(app, body)


def test_the_time_forms_none_shows_only_on_a_family_with_its_own() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)
    intro = CueInfo(
        "1",
        "Intro",
        (),
        fadeIn=3.0,
        families=(FamilyTiming("position", 4.0), FamilyTiming("beam", 2.0, 0.5, "snapEnd")),
    )

    async def body(pilot: Pilot[int]) -> None:
        bridge.events += [one_cue(intro), LiveChanged(live())]
        await settle(pilot, app)
        dialog = await open_edit(pilot, app, "time…")
        assert isinstance(dialog, TimeDialog)
        assert not dialog.none_row.display  # the cue's own times
        await pilot.press("ctrl+n")  # hidden: nothing
        await pilot.pause()
        assert app.screen is dialog
        for family, shown in (
            ("intensity", False),
            ("position", True),
            ("color", False),
            ("beam", True),
            ("focus", False),
            ("shutter", False),
        ):
            dialog.target.pick(family)
            await pilot.pause()
            assert dialog.none_row.display is shown, family
            if not shown:
                await pilot.press("ctrl+n")
                await pilot.pause()
                assert app.screen is dialog, family
        dialog.target.pick("beam")
        await pilot.pause()
        assert plain(dialog.none_note) == "Ctrl+N · beam fades with the cue again"
        assert note_of(dialog) == "beam's own, in place of the cue's\nits curve, snapEnd, stays"
        dialog.target.pick("cue")
        await pilot.pause()
        assert not dialog.none_row.display
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is not dialog
        assert bridge.sent == []

    drive(app, body)


def test_the_time_forms_none_takes_a_familys_own_away_by_click_or_key() -> None:
    """No question first: ``undo`` brings it back."""
    bridge = FakeBridge()
    app = on_f4(bridge)
    intro = CueInfo(
        "1",
        "Intro",
        (),
        fadeIn=3.0,
        families=(FamilyTiming("position", 4.0), FamilyTiming("beam", 2.0, 0.5, "snapEnd")),
    )

    async def body(pilot: Pilot[int]) -> None:
        bridge.events += [one_cue(intro), LiveChanged(live())]
        await settle(pilot, app)
        dialog = await open_edit(pilot, app, "time…")
        assert isinstance(dialog, TimeDialog)
        dialog.target.pick("position")
        await pilot.pause()
        dialog.fade.value = "9"  # [none] does not send the fields
        await pilot.click(dialog.none)
        await pilot.pause()
        assert app.screen is not dialog
        assert bridge.lines() == ["cue 9/1 time position none"]
        dialog = await open_edit(pilot, app, "time…")
        assert isinstance(dialog, TimeDialog)
        await pilot.press("shift+tab")
        assert dialog.focused is dialog.target
        await pilot.press(*["right"] * 4)  # beam
        await pilot.press("tab")
        assert dialog.focused is dialog.fade  # Ctrl+N works from a field too
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert app.screen is not dialog
        assert bridge.lines() == ["cue 9/1 time position none", "cue 9/1 time beam none"]

    drive(app, body)


def test_the_curve_form_names_a_curve_or_a_beziers_points() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def curve(pilot: Pilot[int]) -> CurveDialog:
        dialog = await open_edit(pilot, app, "curve…")
        assert isinstance(dialog, CurveDialog)
        return dialog

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        on_cue(app, "1")  # easeInOut, in and out 3
        await settle(pilot, app)
        dialog = await curve(pilot)
        assert dialog.curve.chosen == "easeInOut"
        assert not dialog.points_row.display
        await ok(pilot)
        assert bridge.sent == []
        dialog = await curve(pilot)
        dialog.curve.pick("easeIn")
        await ok(pilot)
        assert bridge.lines() == ["cue 9/1 time 3 easeIn"]
        dialog = await curve(pilot)
        dialog.curve.pick("bezier")
        await pilot.pause()
        assert dialog.points_row.display
        assert dialog.points.value == BEZIER
        for typed in ("0 0 1 2", "1 0 0", "a b c d", ""):
            dialog.points.value = typed
            await ok(pilot)
            assert app.screen is dialog, typed
            assert str(dialog.error.render()) == POINTS
        dialog.curve.pick("linear")
        await pilot.pause()
        assert str(dialog.error.render()) == ""
        assert not dialog.points_row.display
        await ok(pilot)  # the points it hides are not checked
        assert bridge.lines()[-1] == "cue 9/1 time 3 linear"
        dialog = await curve(pilot)
        dialog.curve.pick("bezier")
        dialog.points.value = " 0.42  0 0.58 1 "
        await ok(pilot)
        assert bridge.lines()[-1] == "cue 9/1 time 3 bezier 0.42 0 0.58 1"

    drive(app, body)


def test_the_curve_form_starts_at_a_beziers_points() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)
    cue = CueInfo("1", "Intro", (), fadeIn=1.5, fadeOut=0.25, curve="bezier 0.42 0 0.58 1")

    async def body(pilot: Pilot[int]) -> None:
        bridge.events += [one_cue(cue), LiveChanged(live())]
        await settle(pilot, app)
        dialog = await open_edit(pilot, app, "curve…")
        assert isinstance(dialog, CurveDialog)
        assert dialog.curve.chosen == "bezier"
        assert dialog.points_row.display
        assert dialog.points.value == "0.42 0 0.58 1"
        dialog.points.value = "0.420 0 0.58 1.0"  # the same points
        await ok(pilot)
        assert bridge.sent == []
        dialog = await open_edit(pilot, app, "curve…")
        assert isinstance(dialog, CurveDialog)
        dialog.points.value = "0.42 0 0.6 1"
        await ok(pilot)
        assert bridge.lines() == ["cue 9/1 time 1.5/0.25 bezier 0.42 0 0.6 1"]

    drive(app, body)


def test_the_delay_form_keeps_the_fade_times_to_every_digit() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)
    cue = CueInfo("1", "Intro", (), fadeIn=1.234, fadeOut=1.234)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        on_cue(app, "3")  # fades 1/3, delays 1/2
        await settle(pilot, app)
        dialog = await open_edit(pilot, app, "delay…")
        assert isinstance(dialog, FormDialog)
        assert [field.value for field in dialog.inputs] == ["1", "2"]
        assert note_of(dialog) == (
            "in: before intensity rises and the rest move\nout: before intensity falls"
        )
        await ok(pilot)
        assert bridge.sent == []
        for first, second, line in (
            ("0", "2", "cue 9/3 time 1/3 delay 0/2"),
            ("2.5", "2.50", "cue 9/3 time 1/3 delay 2.5"),
        ):
            dialog = await open_edit(pilot, app, "delay…")
            assert isinstance(dialog, FormDialog)
            dialog.inputs[0].value, dialog.inputs[1].value = first, second
            await ok(pilot)
            assert bridge.lines()[-1] == line
        dialog = await open_edit(pilot, app, "delay…")
        assert isinstance(dialog, FormDialog)
        dialog.inputs[1].value = "-1"
        await ok(pilot)
        assert app.screen is dialog
        assert str(dialog.error.render()) == SECONDS
        await pilot.press("escape")
        await pilot.pause()

        bridge.events.append(one_cue(cue))
        await settle(pilot, app)
        dialog = await open_edit(pilot, app, "delay…")
        assert isinstance(dialog, FormDialog)
        dialog.inputs[0].value = "1"
        await ok(pilot)
        assert bridge.lines()[-1] == "cue 9/1 time 1.234 delay 1/0"  # F4 shows 1.23

    drive(app, body)


def test_follow_and_wait_start_at_the_trigger_and_say_what_it_is() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def trigger(pilot: Pilot[int], kind: str) -> TextDialog:
        dialog = await open_edit(pilot, app, f"{kind}…")
        assert isinstance(dialog, TextDialog)
        assert dialog.title_text.startswith(f"{kind.upper()} · cue 9/")
        return dialog

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        on_cue(app, "3")  # wait 8
        await settle(pilot, app)
        dialog = await trigger(pilot, "wait")
        assert dialog.query_one(Input).value == "8"
        assert note_of(dialog) == (
            "it goes by itself this many seconds\nafter the cue before has started"
        )
        await ok(pilot)
        assert bridge.sent == []
        dialog = await trigger(pilot, "wait")
        dialog.query_one(Input).value = "4"
        await ok(pilot)
        assert bridge.lines() == ["cue 9/3 wait 4"]
        dialog = await trigger(pilot, "follow")
        assert dialog.query_one(Input).value == "0"
        assert note_of(dialog) == (
            "it goes by itself this many seconds\nafter the cue before has finished\nnow: wait 8"
        )
        await ok(pilot)  # another trigger: sent as it is
        assert bridge.lines()[-1] == "cue 9/3 follow 0"

        on_cue(app, "2")  # a manual GO
        await settle(pilot, app)
        dialog = await trigger(pilot, "follow")
        assert note_of(dialog).endswith("\nnow: a manual GO")
        dialog.query_one(Input).value = "x"
        await ok(pilot)
        assert app.screen is dialog
        assert str(dialog.error.render()) == SECONDS
        dialog.query_one(Input).value = " 2.5 "
        await ok(pilot)
        assert bridge.lines()[-1] == "cue 9/2 follow 2.5"

        on_cue(app, "4")  # follow 4
        await settle(pilot, app)
        dialog = await trigger(pilot, "wait")
        assert note_of(dialog).endswith("\nnow: follow 4")
        await pilot.press("escape")
        await pilot.pause()
        assert len(bridge.sent) == 3

    drive(app, body)


def test_rename_a_cue() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        on_cue(app, "3")
        await settle(pilot, app)
        dialog = await open_edit(pilot, app, "rename…")
        assert isinstance(dialog, TextDialog)
        assert dialog.query_one(Input).value == "Pre"
        await ok(pilot)  # unchanged: nothing to send
        assert bridge.sent == []
        dialog = await open_edit(pilot, app, "rename…")
        assert isinstance(dialog, TextDialog)
        dialog.query_one(Input).value = "   "
        await ok(pilot)
        assert app.screen is dialog
        dialog.query_one(Input).value = ' My "Pre" '
        await ok(pilot)
        assert bridge.lines() == [r'''rename cue 9/3 "My \"Pre\""''']

    drive(app, body)


def test_the_prompt_has_the_keyboard_unless_a_dialog_is_open() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        cues = app.query_one(CueTable)
        for close in ("escape", "enter"):
            await click_cell(pilot, cues, 1, "wait")
            await pilot.pause()
            assert isinstance(app.screen, TextDialog)
            await pilot.press("9")  # the dialog's: it replaces the 0 it starts at
            assert app.prompt.value == ""
            await pilot.press(close)
            await pilot.pause()
            assert not isinstance(app.screen, TextDialog)
            await pilot.press(*"go")
            assert app.prompt.value == "go"
            await pilot.press("escape")
        assert bridge.lines() == ["cue 9/2 wait 9"]

    drive(app, body)


# ------------------------------------------------------ a list's controls


def test_the_list_row_says_what_it_acts_on() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        assert plain(app.query_one("#cue-list-label")) == "list 9 Song"
        strip = app.query_one("#cue-list-edits", ButtonStrip)
        assert words(strip) == "[tracking off] [chase…] [rename…] [delete]"
        await click_label(pilot, strip, "tracking off")
        assert bridge.lines() == ["cuelist 9 tracking false"]
        page(app).choose_list(10)  # a list without tracking
        await settle(pilot, app)
        assert words(strip) == "[tracking on] [chase…] [rename…] [delete]"
        await click_label(pilot, strip, "tracking on")
        assert bridge.lines() == ["cuelist 9 tracking false", "cuelist 10 tracking true"]

    drive(app, body)


def test_a_new_list_refuses_a_number_taken_and_shows() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        add = page(app).list_add
        assert add.render().plain == "[+ list…]"
        await click_label(pilot, add, "+ list…")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert [field.value for field in dialog.inputs] == ["22", ""]  # the highest plus one
        assert "taken: 9–11, 21" in str(dialog.query(".note").first().render())
        dialog.inputs[0].value = "10"
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is dialog
        assert str(dialog.error.render()) == "10 is taken"
        dialog.inputs[0].value = "30"
        dialog.inputs[1].value = " Encore "
        await pilot.press("enter")
        await pilot.pause()
        assert bridge.lines() == ['cuelist add 30 "Encore"']
        added = CueListInfo(30, "Encore", "sequence", None, ())
        bridge.events.append(ShowChanged(cues_show(cueLists=(SONG, CHASE, LOOP, SPARE, added))))
        await settle(pilot, app)
        assert page(app).list == 30
        assert str(page(app).panel.border_title) == "CUELIST 30 · Encore"

    drive(app, body)


def test_a_refused_new_list_stays_on_the_list_shown() -> None:
    bridge = FakeBridge(replies={"cuelist add 22": Reply(ok=False, text="error: no")})
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        await click_label(pilot, page(app).list_add, "+ list…")
        await pilot.pause()
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.lines() == ["cuelist add 22"]
        assert page(app).list == 9
        assert ("error", "no") in app.query_one(LogView).entries

    drive(app, body)


def test_a_new_list_without_a_name_and_the_first_of_a_show() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(ShowChanged(show_model()))
        await settle(pilot, app)
        await click_label(pilot, page(app).list_add, "+ list…")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert dialog.inputs[0].value == "1"
        assert "taken" not in str(dialog.query(".note").first().render())
        await pilot.press("enter")
        await pilot.pause()
        assert bridge.lines() == ["cuelist add 1"]

    drive(app, body)


def test_rename_a_list() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        strip = app.query_one("#cue-list-edits", ButtonStrip)
        await click_label(pilot, strip, "rename…")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, TextDialog)
        assert dialog.query_one(Input).value == "Song"
        await pilot.press("enter")  # unchanged: nothing to send
        await pilot.pause()
        assert bridge.sent == []
        await click_label(pilot, strip, "rename…")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, TextDialog)
        dialog.query_one(Input).value = "   "
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is dialog
        dialog.query_one(Input).value = ' My "Song" '
        await pilot.press("enter")
        await pilot.pause()
        assert bridge.lines() == [r'''rename cuelist 9 "My \"Song\""''']

    drive(app, body)


def test_delete_a_list_sends_the_cascade_after_busks_question(club: Any) -> None:
    bridge = FakeBridge(show=club)
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        strip = app.query_one("#cue-list-edits", ButtonStrip)
        await click_label(pilot, strip, "delete")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)
        assert dialog.question == club.confirmation("delete cuelist 9 cascade")
        assert dialog.question.startswith('Delete cue list 9 "Song" and playback 9?')
        await pilot.press("n")
        await pilot.pause()
        assert bridge.sent == []
        await click_label(pilot, strip, "delete")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert bridge.lines() == ["delete cuelist 9 cascade"]

    drive(app, body)


def test_a_deleted_list_or_cue_leaves_f4_on_what_exists() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        cues = app.query_one(CueTable)
        await click_cell(pilot, cues, 3, "name")  # cue 4: chosen
        await settle(pilot, app)
        assert plain(app.query_one("#cue-edit-label")) == "edit cue 9/4"
        without = (SONG.cues[0], SONG.cues[1], SONG.cues[2])
        shorter = CueListInfo(9, "Song", "sequence", None, without, tracking=True)
        bridge.events.append(ShowChanged(cues_show(cueLists=(shorter, CHASE, LOOP, SPARE))))
        await settle(pilot, app)
        assert column(cues, "cue") == ["9/1", "9/2", "9/3"]
        assert cues.chosen == 1  # the chosen cue went: the one P9 is on
        assert plain(app.query_one("#cue-edit-label")) == "edit cue 9/2 Verse"

        gone = cues_show(
            cueLists=(CHASE, LOOP, SPARE),
            playbacks=tuple(p for p in cues_show().playbacks if p.number != 9),
        )
        bridge.events.append(ShowChanged(gone))
        await settle(pilot, app)
        assert page(app).list == 10
        assert str(page(app).panel.border_title) == "CUELIST 10 · Chase"

        bridge.events.append(ShowChanged(cues_show(cueLists=(), playbacks=())))
        await settle(pilot, app)
        assert page(app).list is None
        assert not page(app).panel.display
        assert [i.line or i.label for i in app.current_page.items()] == ["[+ list…]"]

    drive(app, body)


# ----------------------------------------------------------- the chase form


def with_speeds(*names: str) -> ShowModel:
    return cues_show(
        masters=(
            MasterView("Grand Master", "grand", None, ()),
            *(MasterView(name, "speed", None, ()) for name in names),
        )
    )


async def open_chase(pilot: Pilot[int], app: BuskApp, bridge: FakeBridge) -> ChaseDialog:
    await click_label(pilot, app.query_one("#cue-list-edits", ButtonStrip), "chase…")
    await pilot.pause()
    dialog = app.screen
    assert isinstance(dialog, ChaseDialog)
    return dialog


def test_the_chase_form_starts_at_the_settings_the_list_keeps() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events += [ShowChanged(with_speeds("Speed 1")), LiveChanged(live())]
        await settle(pilot, app)
        page(app).choose_list(10)  # a beat, bouncing, crossfade 0.25
        await settle(pilot, app)
        dialog = await open_chase(pilot, app, bridge)
        assert dialog.kind.chosen == "bpm"
        assert dialog.direction.chosen == "bounce"
        assert (dialog.multiplier.value, dialog.crossfade.value) == ("1", "0.25")
        assert not dialog.hz_row.display
        assert dialog.multiplier_row.display
        assert dialog.master_row is None  # one speed master: busk finds it
        await pilot.press("enter")
        await pilot.pause()
        assert bridge.lines() == ["cuelist 10 chase bpm x 1 bounce crossfade 0.25"]
        page(app).choose_list(11)  # Hz, kept while it is a sequence
        await settle(pilot, app)
        dialog = await open_chase(pilot, app, bridge)
        assert (dialog.kind.chosen, dialog.hz.value, dialog.crossfade.value) == ("hz", "2", "0.5")
        assert dialog.hz_row.display
        assert not dialog.multiplier_row.display
        await pilot.press("enter")
        await pilot.pause()
        assert bridge.lines()[-1] == "cuelist 11 chase hz 2 forward crossfade 0.5"

    drive(app, body)


def test_the_chase_form_on_a_list_with_no_settings_sends_each_field() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events += [ShowChanged(with_speeds("Speed 1")), LiveChanged(live())]
        await settle(pilot, app)
        dialog = await open_chase(pilot, app, bridge)  # Song: no chase settings
        assert dialog.kind.chosen == "bpm"
        assert dialog.direction.chosen == "forward"
        assert (dialog.hz.value, dialog.multiplier.value, dialog.crossfade.value) == ("2", "1", "0")
        dialog.multiplier.value = "0.125"
        dialog.direction.pick("reverse")
        dialog.crossfade.value = "0.125"
        await pilot.press("enter")
        await pilot.pause()
        assert bridge.lines() == ["cuelist 9 chase bpm x 0.125 reverse crossfade 0.125"]

        dialog = await open_chase(pilot, app, bridge)
        dialog.kind.pick("hz")
        await pilot.pause()
        dialog.hz.value = "4"
        await pilot.press("enter")
        await pilot.pause()
        assert bridge.lines()[-1] == "cuelist 9 chase hz 4 forward"

    drive(app, body)


def test_the_chase_form_names_a_master_when_the_show_has_several() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)
    two = CueListInfo(
        9,
        "Song",
        "chase",
        'bpm "Speed 2" x 2 forward',
        (),
        rate=ChaseRate(None, "Speed 2", 2.0, "forward"),
    )

    async def body(pilot: Pilot[int]) -> None:
        show = cues_show(
            cueLists=(two,),
            masters=(
                MasterView("Speed 1", "speed", None, ()),
                MasterView("Speed 2", "speed", None, ()),
            ),
        )
        bridge.events += [ShowChanged(show), LiveChanged(live())]
        await settle(pilot, app)
        dialog = await open_chase(pilot, app, bridge)
        assert dialog.master is not None
        assert dialog.master.chosen == "Speed 2"
        assert dialog.master_row is not None
        assert dialog.master_row.display
        dialog.master.pick("Speed 1")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert bridge.lines() == ['cuelist 9 chase bpm "Speed 1" x 2 forward']
        dialog = await open_chase(pilot, app, bridge)
        dialog.kind.pick("hz")
        await pilot.pause()
        assert dialog.master_row is not None
        assert not dialog.master_row.display

    drive(app, body)


@pytest.mark.parametrize("crossfade", ["0.1234567", "0.125", "1", "0.0000001"])
def test_the_chase_form_taken_as_it_opened_keeps_what_busk_stored(
    club_path: Path, crossfade: str
) -> None:
    """On busk itself: the form, opened on a chase and taken, sends the
    list's ``chase`` back as it was, every digit of the crossfade kept."""
    document, _ = busk.load_show(club_path)
    show = busk.OfflineShow(document)
    assert show.execute(f"cuelist 10 chase hz 1.23456789 bounce crossfade {crossfade}").ok

    def stored() -> Any:
        return copy.deepcopy(next(c for c in show.show["cueLists"] if c["number"] == 10))

    before = stored()
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events += [ShowChanged(busk_bridge.show_model(show.show)), LiveChanged(live())]
        await settle(pilot, app)
        page(app).choose_list(10)
        await settle(pilot, app)
        dialog = await open_chase(pilot, app, bridge)
        assert dialog.crossfade.value == crossfade
        await pilot.press("enter")
        await pilot.pause()

    drive(app, body)
    (line,) = bridge.lines()
    assert line.endswith(f" crossfade {crossfade}")
    assert show.execute(line).ok, line
    assert stored() == before


def test_the_chase_form_offers_hz_alone_without_a_speed_master() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events += [ShowChanged(with_speeds()), LiveChanged(live())]
        await settle(pilot, app)
        dialog = await open_chase(pilot, app, bridge)
        assert list(dialog.kind.labels) == ["hz"]
        assert dialog.kind.chosen == "hz"
        assert dialog.hz_row.display
        await pilot.press("enter")
        await pilot.pause()
        assert bridge.lines() == ["cuelist 9 chase hz 2 forward"]

    drive(app, body)


def test_the_chase_form_says_what_is_wrong_and_stays() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events += [ShowChanged(with_speeds("Speed 1")), LiveChanged(live())]
        await settle(pilot, app)
        dialog = await open_chase(pilot, app, bridge)
        for field, typed, problem in (
            (dialog.multiplier, "0", "a multiplier above 0"),
            (dialog.multiplier, "-1", "a multiplier above 0"),
            (dialog.multiplier, "1e3", "a multiplier above 0"),
            (dialog.multiplier, "", "a multiplier above 0"),
        ):
            field.value = typed
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen is dialog
            assert str(dialog.error.render()) == problem
        dialog.multiplier.value = "1"
        for typed in ("1.5", "x", "50%"):
            dialog.crossfade.value = typed
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen is dialog
            assert str(dialog.error.render()) == "a crossfade from 0 to 1"
        dialog.crossfade.value = "0"
        dialog.kind.pick("hz")
        await pilot.pause()
        assert str(dialog.error.render()) == ""  # it may have been of a field that went
        for typed in ("0", ".", ""):
            dialog.hz.value = typed
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen is dialog
            assert str(dialog.error.render()) == "a rate above 0 Hz"
        await pilot.press("escape")
        await pilot.pause()
        assert bridge.sent == []

    drive(app, body)


def test_tab_reaches_the_chase_forms_chips() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events += [ShowChanged(with_speeds("Speed 1")), LiveChanged(live())]
        await settle(pilot, app)
        dialog = await open_chase(pilot, app, bridge)
        assert dialog.focused is dialog.kind
        await pilot.press("left")
        await pilot.pause()
        assert dialog.kind.chosen == "hz"
        assert dialog.hz_row.display
        await pilot.press("tab", "tab")  # Hz, then the direction
        assert dialog.focused is dialog.direction
        await pilot.press("right")
        await pilot.pause()
        assert dialog.direction.chosen == "reverse"

    drive(app, body)


# ----------------------------------------------------- reach and widths


def test_the_pane_cursor_reaches_each_control_and_takes_it() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        bridge.events.append(held())
        await settle(pilot, app)
        items = app.current_page.items()
        labels = [i.line or i.prefill or i.label for i in items]
        for label in (
            "cuelist 9 tracking false", "[chase…]", "[rename…]", "delete cuelist 9 cascade",
            "[time…]", "[delay…]", "[curve…]", "[follow…]", "[wait…]",
            "[release…]", "[record at…]", "record cue 9/2 merge", "[replace]", "[remove]",
            "[delete]", "[+ list…]",
        ):  # fmt: skip
            assert label in labels, label
        for label, which, dialog_type in (
            ("[record at…]", 0, FormDialog),
            ("[release…]", 0, FormDialog),
            ("[+ list…]", 0, FormDialog),
            ("[rename…]", 0, TextDialog),  # the list's
            ("[rename…]", 1, TextDialog),  # the cue's
            ("[time…]", 0, TimeDialog),
            ("[delay…]", 0, FormDialog),
            ("[curve…]", 0, CurveDialog),
            ("[follow…]", 0, TextDialog),
            ("[wait…]", 0, TextDialog),
            ("[chase…]", 0, ChaseDialog),
            ("[replace]", 0, ConfirmDialog),
            ("[remove]", 0, ConfirmDialog),
            ("[delete]", 0, ConfirmDialog),
        ):
            before = [i.line or i.prefill or i.label for i in app.current_page.items()]
            at = [k for k, found in enumerate(before) if found == label][which]
            await pilot.press("tab", *["down"] * at, "enter")
            await pilot.pause()
            assert isinstance(app.screen, dialog_type), label
            if label == "[rename…]":
                title = ("RENAME · cuelist 9", "RENAME · cue 9/2")[which]
                assert app.screen.title_text == title
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("escape")  # the prompt has the keyboard again
            await pilot.pause()
        assert bridge.sent == []

    drive(app, body)


def test_at_99_columns_the_strips_wrap_and_every_button_shows() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        bridge.events.append(held())
        await settle(pilot, app)
        edits = app.query_one("#cue-edits", ButtonStrip)
        lines = edits.lines(edits.size.width)
        assert len(lines) >= 2
        assert all(line.cell_len <= edits.size.width for line in lines)
        shown = " ".join(line.plain for line in lines)
        for label in ("[time…]", "[release…]", "[record at…]", "[merge]", "[replace]", "[remove]"):
            assert label in shown, label
        await click_label(pilot, edits, "delete")  # on the row it wrapped to
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)

    drive(app, body, size=(99, 40))


def test_a_long_name_leaves_room_for_the_buttons() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)
    long = "L" * 400
    song = CueListInfo(9, long, "sequence", None, (CueInfo("1", long, ()),))

    async def body(pilot: Pilot[int]) -> None:
        bridge.events += [ShowChanged(cues_show(cueLists=(song,))), LiveChanged(live())]
        await settle(pilot, app)
        for strip in ("#cue-edits", "#cue-list-edits"):
            found = app.query_one(strip, ButtonStrip)
            assert found.size.width >= 30, strip
            assert "[delete]" in found.render().plain, strip

    drive(app, body, size=(99, 40))


def test_stacked_below_100_columns_the_chosen_list_comes_first() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        chosen, browser = page(app).panel, page(app).browser
        assert chosen.region.y > browser.region.y or chosen.region.x > browser.region.x
        await pilot.resize_terminal(99, 40)
        await pilot.pause()
        assert chosen.region.y < browser.region.y
        assert chosen.region.width == browser.region.width
        await pilot.resize_terminal(120, 40)
        await pilot.pause()
        assert chosen.region.x > browser.region.x

    drive(app, body)
