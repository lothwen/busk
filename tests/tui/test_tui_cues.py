"""F4 Cues (spec §8.4, plan Phase 3): the list browser, the chosen list's
meta line and cue rows as stored, ``▶`` from the snapshot, going to a cue,
the edits' pre-fills, the buttons, which list shows, and the pane cursor.
Headless, with a fake bridge."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.pilot import Pilot
from tui_fakes import (
    FakeBridge,
    click_cell,
    column,
    drive,
    live_state,
    make_app,
    playback,
    settle,
    show_model,
)

from busk_tui.formats import delay_text, stored_text, time_text
from busk_tui.model import (
    CueInfo,
    CueListInfo,
    EffectInfo,
    FixtureInfo,
    GroupInfo,
    LiveChanged,
    PageInfo,
    PlaybackInfo,
    ShowChanged,
    ShowModel,
    StoredValue,
    Targets,
)
from busk_tui.pages.cues import CuesPage, meta_text
from busk_tui.shell import BuskApp
from busk_tui.widgets.controls import ButtonStrip
from busk_tui.widgets.cuetable import CueListTable, CueTable, cue_cells

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
            families=(("position", 4.0, 0.0),),
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
)
LOOP = CueListInfo(11, "Loop", "sequence", "hz 2 forward", (CueInfo("1", "Go", ()),), crossfade=0.5)
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


async def click_label(pilot: Pilot[int], strip: ButtonStrip, label: str) -> None:
    lines = [line.plain for line in strip.lines(strip.size.width)]
    for y, line in enumerate(lines):
        if label in line:
            await pilot.click(strip, offset=(line.index(label) + 1, y))
            return
    raise AssertionError(f"no {label!r} in {lines}")


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


def test_a_row_goes_to_its_cue_and_an_edit_cell_prefills() -> None:
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
        for name, prefill in (
            ("time", "cue 9/3 time "),
            ("delay", "cue 9/3 time 1/3 delay "),
            ("curve", "cue 9/3 time 1/3 "),
            ("follow", "cue 9/3 follow "),
            ("wait", "cue 9/3 wait "),
        ):
            await click_cell(pilot, cues, 2, name)
            assert app.prompt.value == prefill
            await pilot.press("escape")
        await click_cell(pilot, cues, 0, "time")
        assert app.prompt.value == "cue 9/1 time "
        assert cues.chosen == 0  # an edit chooses the row, without going to it
        assert [s.line for s in bridge.sent] == ["goto 9 3"]

    drive(app, body)


def test_the_edits_prefill_the_chosen_cue() -> None:
    bridge = FakeBridge()
    app = on_f4(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        assert plain(app.query_one("#cue-edit-label")) == "edit cue 9/2 Verse"
        edits = app.query_one("#cue-edits", ButtonStrip)
        assert edits.render().plain == (
            "[time…] [delay…] [curve…] [go…] [follow…] [wait…] [rename…]"
        )
        await click_label(pilot, edits, "go…")
        assert app.prompt.value == "cue 9/2 go"
        await pilot.press("escape")
        await click_label(pilot, edits, "rename…")
        assert app.prompt.value == 'rename cue 9/2 "'
        await pilot.press("escape")
        await click_label(pilot, edits, "delay…")
        assert app.prompt.value == "cue 9/2 time 2 delay "
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
            "cue 9/2 time ", "cue 9/2 time 2 delay ", "cue 9/2 time 2 ", "cue 9/2 go",
            "cue 9/2 follow ", "cue 9/2 wait ", 'rename cue 9/2 "',
            "cuelist 9 Song", "cuelist 10 Chase", "cuelist 11 Loop", "cuelist 21 Spare",
        ]  # fmt: skip
        await pilot.press("tab", "down", "down", "enter")  # cue 3: goes, and is chosen
        assert app.cursor.active
        assert [s.line for s in bridge.sent] == ["goto 9 3"]
        assert plain(app.query_one("#cue-edit-label")) == "edit cue 9/3 Pre"
        await pilot.press(*["down"] * 14, "enter")  # list 10: chosen, the cursor stays
        await settle(pilot, app)
        assert app.cursor.active
        assert app.query_one(CueListTable).chosen == 1
        assert app.view.playback == 10
        # the cues of list 10 come first now: the cursor reaches them
        labels = [(i.line or i.label) for i in app.current_page.items()]
        assert labels[:2] == ["goto 10 1", "goto 10 2"]
        await pilot.press(*["up"] * 30, "enter")
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
