"""F4's TRACK panel and ``[block]`` (the pending plan's Phase 28, Q10 (a)).

The club show's Song (list 9, tracking): Intro sets the washes (201–204) at
60% in preset Blue; Verse the heads (101, 102) at 70%, a warm white and
preset Audience; Pre the bar (301) and the washes at 30%; Chorus everything
at full white; Outro the heads at 20%, and releases their pan and tilt.

* The panel's table, from the real bridge's conversion of the club show's
  ``tracking(9)``: a row per fixture, a column per family the list uses,
  own values bright, tracked ones dim with the cue they come from, a
  colour's swatch, a preset by its name, ``✕``, ``·``, ``mixed``, and each
  cell's hint.
* The bridge reads the tracked states only while asked, and again only
  after a show edit.
* F4 with a fake bridge: the panel follows the chosen cue and the list
  shown, says what a block cue and a list without tracking are, gives the
  hint row a cell's words, and ``[block]``.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from rich.text import Text
from textual.pilot import Pilot
from tui_fakes import FakeBridge, Stub, column, drive, live_state, make_app, playback, settle

import busk
from busk_tui import bridge as busk_bridge
from busk_tui import colors
from busk_tui.bridge import Bridge
from busk_tui.model import (
    EngineRunning,
    LiveChanged,
    ShowChanged,
    TrackCue,
    TrackingChanged,
    TrackSheet,
    TrackValue,
)
from busk_tui.pages.cues import BLOCK_LIT, NOTHING_ON_STAGE, READING, CuesPage
from busk_tui.shell import BuskApp
from busk_tui.widgets.controls import ButtonStrip
from busk_tui.widgets.prompt import HintRow
from busk_tui.widgets.rows import Cells, fit
from busk_tui.widgets.trackpanel import NOTHING, TrackTable, families, family_cell, track

FIXTURES = ["101", "102", "201", "202", "203", "204", "301"]
SONG = ("intensity", "color", "position")


def sheet_of(show: busk.OfflineShow, cue_list: int = 9) -> TrackSheet:
    cues = show.tracking(cue_list)
    assert cues is not None
    return busk_bridge.track_sheet(cue_list, cues)


def styles(text: Text) -> list[str]:
    """The styles of a cell's spans, in order."""
    return [str(span.style) for span in text.spans]


def column_of(rows: Sequence[Cells], name: str) -> list[str]:
    return [row[name].plain for row in rows]


def blocked(club: busk.OfflineShow) -> busk.OfflineShow:
    """The club show with Pre (9/3) a block cue."""
    show = busk.OfflineShow(copy.deepcopy(club.show))
    assert show.execute("cue 9/3 block on").ok
    return show


# ---------------------------------------------------------------- the table


def test_a_row_per_fixture_and_a_column_per_family_the_list_uses(club: busk.OfflineShow) -> None:
    sheet = sheet_of(club)
    assert families(sheet) == SONG
    pre = track(sheet.cues[2], 9, SONG, "256")
    assert [c.name for c in pre.columns] == ["fixture", *SONG]
    assert [c.flex for c in pre.columns] == [False, False, False, True]  # the last takes the room
    rows = {row["fixture"].plain: row for row in pre.rows}
    assert list(rows) == FIXTURES
    assert rows["101"]["intensity"].plain == "70% ← 9/2"
    assert styles(rows["101"]["intensity"]) == [colors.DIM, colors.MID]  # tracked: dim
    washes = rows["201"]["intensity"]
    assert (washes.plain, styles(washes)) == ("30%", [colors.FG])
    assert rows["201"]["color"].plain == "██ Blue ← 9/1"
    assert styles(rows["201"]["color"])[0] == colors.swatch((0.0, 0.0, 1.0), 1.0, "256")
    assert rows["301"]["color"].plain == "██ Amber"  # its own
    assert rows["101"]["color"].plain == "██ 1.00 0.75 0.45 ← 9/2"
    assert rows["101"]["position"].plain == "Audience ← 9/2"  # one preset: its name once
    assert rows["201"]["position"].plain == NOTHING
    hints = dict(zip(rows, pre.hints, strict=True))
    assert hints["201"]["color"] == "201 color Blue, tracked from 9/1"
    assert hints["301"]["intensity"] == "301 intensity 100%, stored in this cue"
    assert hints["101"]["position"] == (
        "101 pan Audience, tracked from 9/2 · tilt Audience, tracked from 9/2"
    )
    assert "position" not in hints["201"]


def test_a_release_is_said_and_the_columns_stay_from_cue_to_cue(club: busk.OfflineShow) -> None:
    sheet = sheet_of(club)
    outro = track(sheet.cues[4], 9, SONG, "256")
    heads = outro.rows[0]
    assert (heads["fixture"].plain, heads["position"].plain) == ("101", "✕ released")
    assert styles(heads["position"]) == [colors.AMBER]
    assert outro.hints[0]["position"] == "101 pan released · tilt released"
    intro = track(sheet.cues[0], 9, SONG, "256")
    assert [c.name for c in intro.columns] == ["fixture", *SONG]  # no heads yet, and position
    assert column_of(intro.rows, "fixture") == ["201", "202", "203", "204"]


def test_several_attributes_are_named_and_each_says_where_it_comes_from() -> None:
    def value(attribute: str, given: Any, since: str | None, element: int = 1) -> TrackValue:
        return TrackValue(101, element, attribute, given, None, since)

    def plain(held: dict[str, list[TrackValue]], released: frozenset[str] = frozenset()) -> str:
        return family_cell(held, set(released), 9, "256")[0].plain

    pan, tilt = value("pan", -30.0, "2"), value("tilt", 40.0, "2")
    assert plain({"pan": [pan], "tilt": [tilt]}) == "pan -30° tilt 40° ← 9/2"
    own_pan = value("pan", -30.0, None)
    assert plain({"pan": [own_pan], "tilt": [tilt]}) == "pan -30° · tilt 40° ← 9/2"
    assert plain({"tilt": [tilt]}, frozenset({"pan"})) == "pan ✕ · tilt 40° ← 9/2"
    assert plain({"tilt": [tilt]}) == "tilt 40° ← 9/2"
    beam = {"gobo1": [value("gobo1", "star", None)], "zoom": [value("zoom", 20.0, None)]}
    assert plain(beam) == "gobo1 star zoom 20°"
    bar = [value("intensity", 1.0, None, 1), value("intensity", 0.5, None, 2)]
    text, hint = family_cell({"intensity": bar}, set(), 9, "256")
    assert (text.plain, hint) == ("mixed", "intensity mixed, stored in this cue")
    bar = [value("intensity", 1.0, "3", 1), value("intensity", 1.0, "4", 2)]
    text, hint = family_cell({"intensity": bar}, set(), 9, "256")
    assert (text.plain, hint) == ("100% ← several cues", "intensity 100%, from several cues")


def test_a_list_without_tracking_has_only_each_cues_own(club: busk.OfflineShow) -> None:
    """The chase (list 10): each step sets one wash, and tracks nothing."""
    sheet = sheet_of(club, 10)
    step = track(sheet.cues[1], 10, families(sheet), "256")
    assert column_of(step.rows, "fixture") == ["202"]
    assert "←" not in step.rows[0]["intensity"].plain + step.rows[0]["color"].plain


# --------------------------------------------------------------- the bridge


@pytest.fixture
def stub(club: busk.OfflineShow) -> Stub:
    tracked = club.tracking(9)
    assert tracked is not None
    return Stub(show=club.show, tracked={9: tracked})


@pytest.fixture
def running(stub: Stub) -> Iterator[Bridge]:
    bridge = Bridge(stub, None)  # type: ignore[arg-type]
    bridge.start()
    deadline = time.monotonic() + 5.0
    while not any(isinstance(e, EngineRunning) for e in bridge.drain()):
        assert time.monotonic() < deadline
        time.sleep(0.01)
    yield bridge
    bridge.stop(timeout=1.0)


def sheets(bridge: Bridge, wait: float = 0.3) -> list[TrackSheet]:
    time.sleep(wait)
    return [event.sheet for event in bridge.drain() if isinstance(event, TrackingChanged)]


def sheet_cues(show: busk.OfflineShow) -> tuple[busk.TrackedCue, ...]:
    cues = show.tracking(9)
    assert cues is not None
    return cues


def test_the_bridge_reads_a_lists_states_while_asked_and_again_after_an_edit(
    running: Bridge, stub: Stub, club: busk.OfflineShow
) -> None:
    assert (sheets(running), stub.tracking_reads) == ([], [])  # nobody asked
    running.track(9)
    (sheet,) = sheets(running)
    assert sheet == sheet_of(club)
    assert stub.tracking_reads == [9]
    assert (sheets(running), stub.tracking_reads) == ([], [9])  # no edit: no read
    stub.show = copy.deepcopy(club.show)  # an edit that leaves the list as it was
    assert (sheets(running), stub.tracking_reads) == ([], [9, 9])
    stub.tracked = {9: sheet_cues(blocked(club))}
    stub.show = copy.deepcopy(club.show)
    (changed,) = sheets(running)
    assert changed.cues[2].block
    running.track(None)
    stub.show = copy.deepcopy(club.show)
    assert (sheets(running), len(stub.tracking_reads)) == ([], 3)
    running.track(9)  # asked again: sent again, the same
    (again,) = sheets(running)
    assert again == changed
    running.track(30)  # a list the show lacks: read once, nothing sent
    assert (sheets(running), stub.tracking_reads[-1:]) == ([], [30])
    assert (sheets(running), stub.tracking_reads.count(30)) == ([], 1)


# ------------------------------------------------------------------- F4


def on_song(bridge: FakeBridge, show: busk.OfflineShow) -> BuskApp:
    """F4, on the club show, with P9 on cue 2."""
    app = make_app(bridge, page=4)
    live = live_state(playbacks=(playback(9, "Song", state="active", level=1.0, cue="2"),))
    bridge.events += [ShowChanged(busk_bridge.show_model(show.show)), LiveChanged(live)]
    return app


async def to_song(pilot: Pilot[int], app: BuskApp) -> CuesPage:
    await settle(pilot, app)
    app._select_playback(9)
    await settle(pilot, app)
    return app.query_one(CuesPage)


def title(page: CuesPage) -> str:
    return str(page.track_panel.border_title)


def note(page: CuesPage) -> str:
    content = page.track_note.content
    return content.plain if page.track_note.display and isinstance(content, Text) else ""


def hint_of(app: BuskApp) -> str:
    """What the hint row shows."""
    rendered = app.query_one(HintRow).render()
    return rendered.plain if isinstance(rendered, Text) else str(rendered)


def test_track_follows_the_chosen_cue_and_the_list_the_bridge_reads(
    club: busk.OfflineShow,
) -> None:
    bridge = FakeBridge(show=club)
    app = on_song(bridge, club)

    async def body(pilot: Pilot[int]) -> None:
        page = await to_song(pilot, app)
        table = app.query_one(TrackTable)
        assert bridge.tracking == 9  # F4 shows list 9: the bridge reads it
        assert title(page) == "TRACK 9/2 · Verse"  # the cue P9 is on
        assert (table.rows, table.empty.plain) == ((), READING)
        bridge.events.append(TrackingChanged(sheet_of(club)))
        await settle(pilot, app)
        assert [c.name for c in table.columns()] == ["fixture", *SONG]
        assert column(table, "fixture") == FIXTURES[:6]  # the bar comes in at Pre
        assert column(table, "intensity")[2] == "60% ← 9/1"
        assert note(page) == ""
        page.choose_cue("3", go=False)
        await settle(pilot, app)
        assert title(page) == "TRACK 9/3 · Pre"
        assert column(table, "color")[2:4] == ["██ Blue ← 9/1", "██ Blue ← 9/1"]
        assert bridge.sent == []
        await app.run_action("page(1)")
        assert bridge.tracking is None  # F1 shows no tracked states
        await app.run_action("page(4)")
        assert bridge.tracking == 9
        page.choose_list(10)
        await settle(pilot, app)
        assert bridge.tracking == 10
        assert table.empty.plain == READING  # list 9's sheet is not list 10's
        assert note(page) == "cue list 10 does not track: each value is the cue's own"
        bridge.events.append(TrackingChanged(sheet_of(club, 10)))
        await settle(pilot, app)
        assert title(page) == "TRACK 10/1 · Chase"
        assert column(table, "fixture") == ["201"]

    drive(app, body)


def test_a_block_cue_a_cue_with_nothing_and_a_list_with_no_cues(club: busk.OfflineShow) -> None:
    show = blocked(club)
    for line in ("sel fixture 101", "set intensity 50%", "record cue 30/1", "cuelist add 31"):
        assert show.execute(line).ok, line
    bridge = FakeBridge(show=show)
    app = on_song(bridge, show)

    async def body(pilot: Pilot[int]) -> None:
        page = await to_song(pilot, app)
        table = app.query_one(TrackTable)
        bridge.events.append(TrackingChanged(sheet_of(show)))
        page.choose_cue("3", go=False)
        await settle(pilot, app)
        assert note(page) == "a block cue: it tracks nothing from the cues before it"
        assert column(table, "fixture") == ["201", "202", "203", "204", "301"]  # no heads
        assert column(table, "color")[0] == NOTHING  # Blue does not track into a block cue
        page.choose_list(30)
        bridge.events.append(TrackingChanged(TrackSheet(30, (TrackCue("1", "", False, ()),))))
        await settle(pilot, app)
        assert table.rows == ()
        assert table.empty.plain == NOTHING_ON_STAGE.format(30, "1")
        page.choose_list(31)
        await settle(pilot, app)
        assert not page.track_panel.display  # no cue: no panel

    drive(app, body)


def test_the_hint_row_says_where_a_value_comes_from(club: busk.OfflineShow) -> None:
    bridge = FakeBridge(show=club)
    app = on_song(bridge, club)

    async def body(pilot: Pilot[int]) -> None:
        page = await to_song(pilot, app)
        table = app.query_one(TrackTable)
        bridge.events.append(TrackingChanged(sheet_of(club)))
        await settle(pilot, app)
        before = hint_of(app)
        x = 0
        for shown, width in fit(table.columns(), table.size.width):
            if shown.name == "color":
                break
            x += width + 1
        table.scroll_visible(animate=False)
        await pilot.pause()
        await pilot.hover(table, offset=(x, 3))  # 201 in the Verse
        await pilot.pause()
        assert hint_of(app) == "201 color Blue, tracked from 9/1"
        await pilot.hover(page.edits, offset=(0, 0))
        await pilot.pause()
        assert hint_of(app) == before

    drive(app, body)


def test_at_80_columns_the_three_families_show(club: busk.OfflineShow) -> None:
    bridge = FakeBridge(show=club)
    app = on_song(bridge, club)

    async def body(pilot: Pilot[int]) -> None:
        await to_song(pilot, app)
        table = app.query_one(TrackTable)
        bridge.events.append(TrackingChanged(sheet_of(club)))
        await settle(pilot, app)
        shown = [c.name for c, _ in fit(table.columns(), table.size.width)]
        assert shown == ["fixture", *SONG]
        assert column(table, "color")[0] == "██ 1.00 0.75 0.45"

    drive(app, body, size=(80, 40))


async def click_label(pilot: Pilot[int], strip: ButtonStrip, label: str) -> None:
    for y, line in enumerate(text.plain for text in strip.lines(strip.size.width)):
        if f"[{label}]" in line:
            await pilot.click(strip, offset=(line.index(f"[{label}]") + 1, y))
            await pilot.pause()
            return
    raise AssertionError(f"no [{label}] in {strip.render().plain!r}")


def test_block_is_lit_on_a_block_cue_and_sends_its_line_without_a_question(
    club: busk.OfflineShow,
) -> None:
    show = blocked(club)
    bridge = FakeBridge(show=show)
    app = on_song(bridge, show)

    def label(page: CuesPage) -> Text:
        return next(b.label for b in page.edits.buttons if b.label.plain == "[block]")

    async def body(pilot: Pilot[int]) -> None:
        page = await to_song(pilot, app)
        assert styles(label(page)) == [colors.AMBER]  # the Verse
        await click_label(pilot, page.edits, "block")
        page.choose_cue("3", go=False)
        await settle(pilot, app)
        assert styles(label(page)) == [BLOCK_LIT]
        await click_label(pilot, page.edits, "block")
        await settle(pilot, app)
        assert [sent.line for sent in bridge.sent] == ["cue 9/2 block on", "cue 9/3 block off"]
        assert app.screen is app.screen_stack[0]  # no question was asked

    drive(app, body)
