"""F3 Fixtures (spec §8.3, plan Phase 4): a row per fixture, single and
multi-element, patched, split and unpatched; the live cells and their source
colours from an ``OutputModel``; the selection marker; clicks, Shift-clicks and
the pane cursor. Edit mode (``docs/plans/tui-rig-plan.md`` §6.4, §6.5): the
rig's table and the FIXTURE panel, its header, category and mode, its limits,
orientation and location, and how far each reaches, a run's ``[delete]``
included. Headless, with a fake bridge."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from textual import events
from textual.pilot import Pilot
from textual.widget import Widget
from textual.widgets import Input
from tui_fakes import (
    FakeBridge,
    Reply,
    click_cell,
    column,
    drive,
    make_app,
    programmer,
    settle,
    show_model,
)

import busk
from busk_tui import attributes, colors
from busk_tui.model import (
    CommandDone,
    ElementOutput,
    FixtureInfo,
    GroupInfo,
    Limits,
    ModeInfo,
    Orientation,
    OutputChanged,
    OutputModel,
    Parked,
    ProfileInfo,
    ProgrammerChanged,
    ShowChanged,
    ShowModel,
)
from busk_tui.pages.fixtures import FixturesPage
from busk_tui.shell import BuskApp
from busk_tui.widgets.controls import MARKED, ButtonStrip
from busk_tui.widgets.dialogs import ConfirmDialog, FormDialog, TextDialog
from busk_tui.widgets.fixture_panel import (
    CATEGORIES,
    check_level,
    check_park,
    check_span,
    limit_text,
    location_text,
    parked_text,
    read_level,
    spans_text,
    what_text,
)
from busk_tui.widgets.fixturetable import (
    FixtureTable,
    fixture_cells,
    legend,
    limits_text,
    rig_cells,
    source_text,
    swatches,
)
from busk_tui.widgets.group_panel import WRITES, changes, group_cells
from busk_tui.widgets.legend import Legend
from busk_tui.widgets.location_form import check_place
from busk_tui.widgets.log import LogView
from busk_tui.widgets.options import LIT

SPOT = FixtureInfo(
    101, 1, "Spot 101", "Spot", "16ch", 16, (1, 1), location=(1.5, 2.0, 4.0, 0, 0, 0)
)
BAR = FixtureInfo(301, 12, "Bar 301", "Pixel Bar", "36ch", 36, (1, 49))
SPLIT = FixtureInfo(302, 4, "Bar 302", "Pixel Bar", "12ch", 12, (2, 1), split=True)
LOOSE = FixtureInfo(401, 1, "", "Par", "4ch", 4, None)
PROFILES = (
    ProfileInfo("Spot", frozenset(), (), "spot"),
    ProfileInfo("Pixel Bar", frozenset(), (), "pixel"),
    ProfileInfo('Par "LED"', frozenset(), ()),
    ProfileInfo("Par", frozenset(), ()),
)


def out(number: int, element: int = 1, **parts: Any) -> ElementOutput:
    given: dict[str, Any] = {
        "intensity": 1.0,
        "color": (1.0, 0.0, 0.0),
        "pan": None,
        "tilt": None,
        "zoom": None,
        "sources": (("intensity", "playback"), ("color", "playback")),
        "playback": 9,
    }
    given.update(parts)
    return ElementOutput(number, element, **given)


HEAD = out(
    101,
    intensity=0.8,
    pan=-45.4,
    tilt=10.0,
    zoom=21.0,
    sources=(("intensity", "programmer"), ("position", "effect"), ("beam", "none")),
    playback=None,
)
BAR_OUT = tuple(
    out(301, element, intensity=element / 12, sources=(("intensity", "effect"),), playback=11)
    for element in range(1, 13)
)
OUTPUT = OutputModel(1, (HEAD, *BAR_OUT))


def rig(**changes: Any) -> ShowModel:
    parts: dict[str, Any] = {"fixtures": (SPOT, BAR, SPLIT, LOOSE), "profiles": PROFILES}
    parts.update(changes)
    return show_model(**parts)


def on_f3(bridge: FakeBridge, output: OutputModel | None = OUTPUT) -> BuskApp:
    bridge.events += [
        ShowChanged(rig()),
        ProgrammerChanged(programmer(selection=((301, 1), (301, 2)))),
    ]
    if output is not None:
        bridge.events.append(OutputChanged(output))
    return make_app(bridge, page=3)


def styles(cells: dict[str, Any], name: str) -> str:
    return str(cells[name].spans[0].style)


def test_static_cells_for_single_multi_split_and_unpatched_fixtures() -> None:
    cells = [fixture_cells(f, (), False, None, "256") for f in (SPOT, BAR, SPLIT, LOOSE)]
    table = [
        tuple(c[name].plain for name in ("number", "name", "profile", "mode", "patch"))
        for c in cells
    ]
    assert table == [
        ("101", "Spot 101", "Spot", "16ch", "1.1"),
        ("301", "Bar 301", "Pixel Bar ×12", "36ch", "1.49"),
        ("302", "Bar 302", "Pixel Bar ×4", "12ch", "2.1 split"),
        ("401", "—", "Par", "4ch", "—"),
    ]
    assert styles(cells[3], "patch") == colors.RED  # unpatched
    assert [c["intensity"].plain for c in cells] == ["·"] * 4  # no output read yet


def test_live_cells_coloured_by_what_drives_them() -> None:
    head = fixture_cells(SPOT, (HEAD,), True, "spot", "256")
    assert head["marker"].plain == "▸"
    assert (head["intensity"].plain, head["pan"].plain, head["tilt"].plain) == (
        "80%",
        "-45°",
        "10°",
    )
    assert head["zoom"].plain == "21°"
    assert head["source"].plain == "prog"
    assert styles(head, "intensity") == colors.MAGENTA  # the programmer's
    assert styles(head, "pan") == colors.GREEN  # an effect moves it
    assert styles(head, "zoom") == colors.DIM  # nothing drives the beam
    assert head["category"].plain == "spot"
    bar = fixture_cells(BAR, BAR_OUT, False, "pixel", "256")
    assert bar["intensity"].plain == "8–100%"  # its elements differ
    assert bar["source"].plain == "fx P11"
    assert styles(bar, "intensity") == colors.GREEN
    assert "pan" not in bar  # no pan: blank


def test_the_source_and_its_words() -> None:
    assert [source_text(s, p) for s, p in (("programmer", None), ("effect", None), ("effect", 11),
            ("playback", 9), ("playback", None), ("none", None))] == [
        "prog", "fx", "fx P11", "P9", "pb", "—"]  # fmt: skip


def test_one_swatch_per_element_twelve_at_most() -> None:
    assert swatches((HEAD,), "256").plain == "██"
    many = tuple(out(301, element) for element in range(1, 25))
    assert swatches(many, "256").plain == "█" * 12
    dark = swatches((out(101, intensity=0.0),), "256")
    assert str(dark.spans[0].style) == f"color({colors.UNLIT})"
    white = swatches((out(101, color=None),), "truecolor")  # no colour: white light
    assert str(white.spans[0].style) == "#ffffff"


def test_the_page_lists_every_fixture_and_lights_the_selection() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        assert bridge.watching == (True, False)
        table = app.query_one(FixtureTable)
        assert column(table, "number") == ["101", "301", "302", "401"]
        assert column(table, "marker") == ["", "▸", "", ""]
        assert table.lit == frozenset({1})
        assert column(table, "intensity") == ["80%", "8–100%", "·", "·"]
        assert "4 fixtures · 1 selected" in str(app.query_one(FixturesPage).header.content)
        assert "unpatched" in app.query_one("#fixtures-legend", Legend).render().plain
        bridge.events.append(OutputChanged(OutputModel(2, (out(101, intensity=0.5), *BAR_OUT))))
        await settle(pilot, app)
        assert column(table, "intensity")[0] == "50%"
        assert column(table, "source")[0] == "P9"

    drive(app, body)


def test_clicks_select_and_shift_clicks_add_or_take_out() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        table = app.query_one(FixtureTable)
        await click_cell(pilot, table, 0, "name")
        await pilot.click(table, offset=(10, 1), shift=True)  # 101, not selected: added
        await pilot.click(table, offset=(10, 2), shift=True)  # 301, selected: taken out
        assert [(s.line, s.origin, s.performance) for s in bridge.sent] == [
            ("sel fixture 101", "ui", False),
            ("sel + fixture 101", "ui", False),
            ("sel - fixture 301", "ui", False),
        ]

    drive(app, body)


def test_the_rows_go_by_number_as_list_fixtures_has_them() -> None:
    bridge = FakeBridge()
    fixtures = tuple(FixtureInfo(n, 1, f"Par {n}", "Par", "4ch", 4, (1, n)) for n in (901, 150, 3))
    bridge.events.append(ShowChanged(rig(fixtures=fixtures)))
    app = make_app(bridge, page=3)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(FixturesPage)
        assert column(page.table, "number") == ["3", "150", "901"]
        await pilot.click(page.table, offset=(20, 2))
        assert bridge.lines() == ["sel fixture 150"]
        assert [item.line for item in page.items()[2:5]] == [
            "sel fixture 3", "sel fixture 150", "sel fixture 901",
        ]  # fmt: skip

    drive(app, body)


def test_the_pane_cursor_stops_on_add_and_edit_then_the_rows() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        items = app.current_page.items()
        assert [item.label for item in items[:2]] == ["+ add", "edit"]
        assert [item.line for item in items[2:]] == [
            "sel fixture 101", "sel fixture 301", "sel fixture 302", "sel fixture 401"
        ]  # fmt: skip
        await pilot.press("tab", *["down"] * 4, "enter")  # 302: selected, and chosen
        assert bridge.lines() == ["sel fixture 302"]
        assert app.query_one(FixturesPage).panel.chosen == 302

    drive(app, body)


def test_nothing_to_show() -> None:
    bridge = FakeBridge()
    bridge.events.append(ShowChanged(show_model()))
    app = make_app(bridge, page=3)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        assert "no fixtures" in app.query_one(FixtureTable).render().plain
        page = app.query_one(FixturesPage)
        page.set_editing(True)
        await pilot.pause()
        assert "no fixtures" in page.rig.render().plain
        assert "click a fixture" in str(page.panel.hint.content)

    drive(app, body)


# ------------------------------------------------------------- edit mode

HEADS = ProfileInfo(
    "Head",
    frozenset({"intensity", "pan", "tilt"}),
    (("pan", -270.0, 270.0), ("tilt", -135.0, 135.0)),
    "spot",
    (ModeInfo("16ch", 16, 1),),
)
PAR = ProfileInfo("Flat Par", frozenset({"intensity"}), (), None, (ModeInfo("4ch", 4, 1),))
SCANNER = ProfileInfo("Scanner", frozenset({"intensity", "pan"}), (("pan", -90.0, 90.0),))
MODES = (ModeInfo("4ch", 4, 1), ModeInfo("8ch", 8, 1))
TWO_MODES = ProfileInfo("Two Modes", frozenset({"intensity"}), (), "wash", MODES)
TILTED = Limits(tilt=(-90.0, 10.0))
FIXTURES = (
    FixtureInfo(101, 1, "Head 1", "Head", "16ch", 16, (1, 1), limits=TILTED),
    FixtureInfo(102, 1, "Head 2", "Head", "16ch", 16, (1, 17)),
    FixtureInfo(103, 1, "Head 3", "Head", "16ch", 16, (1, 33)),
    FixtureInfo(201, 1, "Par 1", "Flat Par", "4ch", 4, (1, 49), limits=Limits(intensity=0.5)),
    FixtureInfo(301, 1, "Scan 1", "Scanner", "8ch", 8, None),
    FixtureInfo(401, 1, "Two 1", "Two Modes", "4ch", 4, (1, 60)),
)


def editing_rig(*fixtures: FixtureInfo) -> ShowModel:
    return show_model(fixtures=fixtures or FIXTURES, profiles=(HEADS, PAR, SCANNER, TWO_MODES))


def on_the_rig(bridge: FakeBridge, *selected: int) -> BuskApp:
    """F3 on the rig above, with ``selected`` selected."""
    bridge.events += [
        ShowChanged(editing_rig()),
        ProgrammerChanged(programmer(selection=tuple((n, 1) for n in selected))),
    ]
    return make_app(bridge, page=3)


async def enter(pilot: Pilot[int], app: BuskApp, chosen: int | None = 101) -> FixturesPage:
    """Edit mode, with ``chosen`` chosen."""
    await settle(pilot, app)
    page = app.query_one(FixturesPage)
    page.set_editing(True)
    page.panel.choose(chosen)
    await pilot.pause()
    return page


async def tap(pilot: Pilot[int], widget: Widget, app: BuskApp) -> None:
    """A click on ``widget``, scrolled into sight first, and what it sends taken."""
    widget.scroll_visible(animate=False)
    await pilot.pause()
    await pilot.click(widget)
    await settle(pilot, app)


async def tap_chip(pilot: Pilot[int], strip: ButtonStrip, label: str, app: BuskApp) -> None:
    for y, line in enumerate(strip.lines(strip.size.width)):
        x = line.plain.find(f"[{label}]")
        if x >= 0:
            await pilot.click(strip, offset=(x + 1, y))
            await settle(pilot, app)
            return
    raise AssertionError(f"no chip [{label}]")


def chip_style(strip: ButtonStrip, label: str) -> str:
    button = next(b for b in strip.buttons if b.label.plain == f"[{label}]")
    return str(button.label.spans[0].style)


def test_rig_cells_say_what_the_panel_sets() -> None:
    plain = FixtureInfo(101, 1, "Head", "Head", "16ch", 16, (1, 1))
    full = FixtureInfo(
        102, 1, "Head", "Head", "16ch", 16, (1, 17),
        location=(1.0, 2.0, 3.0, 0.0, 0.0, 0.0),
        limits=Limits((-90.0, 90.0), (-10.0, 10.0), 0.5),
    )  # fmt: skip
    cells = rig_cells(plain, False, False, "spot")
    assert (cells["limits"].plain, cells["place"].plain) == ("", "·")
    assert str(cells["number"].spans[0].style) == colors.MID
    cells = rig_cells(full, True, True, "spot")
    assert (cells["limits"].plain, cells["place"].plain) == ("pan tilt int", "●")
    assert cells["marker"].plain == "▸"
    assert str(cells["number"].spans[0].style) == LIT  # the chosen one
    assert limits_text(Limits(tilt=(0.0, 1.0))) == "tilt"
    assert limits_text(Limits(intensity=0.0)) == "int"  # a limit of 0 is a limit


def test_edit_swaps_the_tables_and_stops_the_output_read() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(FixturesPage)
        assert bridge.watching == (True, False)
        assert (page.table.display, page.rig.display, page.panel.display) == (True, False, False)
        await pilot.click(page.edit)
        await settle(pilot, app)
        assert page.editing
        assert (page.table.display, page.rig.display, page.panel.display) == (False, True, True)
        assert not page.legend.display
        assert bridge.watching == (False, False)
        assert column(page.rig, "patch") == ["1.1", "1.49", "2.1 split", "—"]
        assert column(page.rig, "place") == ["●", "·", "·", "·"]
        assert str(page.edit.render()) == "[edit ●]"
        assert "click chooses" in str(page.header.content)
        await pilot.click(page.panel.done)
        await settle(pilot, app)
        assert not page.editing
        assert (page.table.display, page.rig.display, page.panel.display) == (True, False, False)
        assert page.legend.display
        assert bridge.watching == (True, False)
        assert str(page.edit.render()) == "[edit]"
        assert column(page.table, "intensity")[0] == "80%"
        await pilot.click(page.edit)
        await pilot.click(page.edit)  # the toggle leaves as [done] does
        await settle(pilot, app)
        assert not page.editing

    drive(app, body)


def test_output_does_not_touch_the_rigs_table() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(FixturesPage)
        page.set_editing(True)
        await pilot.pause()
        rows = page.rig.rows
        bridge.events.append(OutputChanged(OutputModel(2, (out(101, intensity=0.5),))))
        await settle(pilot, app)
        assert page.rig.rows is rows
        page.set_editing(False)  # what came meanwhile shows on the way out
        await pilot.pause()
        assert column(page.table, "intensity")[0] == "50%"

    drive(app, body)


def test_a_click_selects_and_chooses_in_edit_mode_and_shift_adds() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge, 201)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, None)
        assert "click a fixture" in str(page.panel.hint.content)
        assert page.panel.hint.display
        assert not page.panel.body.display
        assert str(page.panel.border_title) == "FIXTURE"
        await click_cell(pilot, page.rig, 1, "name")
        await settle(pilot, app)
        assert page.panel.chosen == 102
        assert page.panel.body.display
        assert not page.panel.hint.display
        assert str(page.panel.border_title) == "FIXTURE · 102 Head 2"
        assert str(page.rig.rows[1]["number"].spans[0].style) == LIT
        await pilot.click(page.rig, offset=(10, 3), shift=True)  # 103, added
        await pilot.click(page.rig, offset=(10, 4), shift=True)  # 201, taken out
        await settle(pilot, app)
        assert bridge.lines() == ["sel fixture 102", "sel + fixture 103", "sel - fixture 201"]
        assert page.panel.chosen == 201

    drive(app, body)


def test_a_choice_made_before_edit_mode_shows_in_the_panel() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(FixturesPage)
        await click_cell(pilot, page.table, 1, "name")
        await pilot.click(page.edit)
        await settle(pilot, app)
        assert str(page.panel.border_title) == "FIXTURE · 102 Head 2"

    drive(app, body)


def test_rename_through_a_dialog() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        await tap(pilot, page.panel.rename, app)
        dialog = app.screen
        assert isinstance(dialog, TextDialog)
        assert dialog.initial == "Head 1"
        await pilot.press("enter")  # the same name: nothing to send
        await settle(pilot, app)
        assert bridge.sent == []
        await tap(pilot, page.panel.rename, app)
        await pilot.press("backspace", "enter")  # empty: refused
        assert isinstance(app.screen, TextDialog)
        assert "cannot be empty" in str(app.screen.error.content)
        await pilot.press(*'A "new" one', "enter")
        await settle(pilot, app)
        assert bridge.lines() == ['rename fixture 101 "A \\"new\\" one"']

    drive(app, body)


def renumbered() -> ShowModel:
    moved = FixtureInfo(150, 1, "Head 1", "Head", "16ch", 16, (1, 1), limits=TILTED)
    return editing_rig(moved, *FIXTURES[1:])


def test_renumber_through_a_dialog_and_the_choice_follows() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        await tap(pilot, page.panel.renumber, app)
        assert isinstance(app.screen, TextDialog)
        assert "102–103, 201, 301, 401" in app.screen.note
        await pilot.press(*"102", "enter")
        assert isinstance(app.screen, TextDialog)
        assert "102 is taken" in str(app.screen.error.content)
        await pilot.press("ctrl+u", *"150", "enter")
        await settle(pilot, app)
        assert bridge.lines() == ["fixture 101 number 150"]
        assert page.panel.chosen == 150  # its done came first
        bridge.events.append(ShowChanged(renumbered()))
        await settle(pilot, app)
        assert page.panel.chosen == 150
        assert str(page.panel.border_title) == "FIXTURE · 150 Head 1"

    drive(app, body)


def test_the_number_it_has_sends_nothing() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        await tap(pilot, page.panel.renumber, app)
        await pilot.press("enter")
        await settle(pilot, app)
        assert not isinstance(app.screen, TextDialog)
        assert bridge.sent == []

    drive(app, body)


def test_the_choice_follows_a_renumber_whose_show_comes_before_its_done() -> None:
    bridge = FakeBridge(auto_reply=False)
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        await tap(pilot, page.panel.renumber, app)
        await pilot.press(*"150", "enter")
        await pilot.pause()
        bridge.events.append(ShowChanged(renumbered()))
        await settle(pilot, app)
        assert page.panel.chosen is None  # 101 has gone, and nothing says where yet
        sent = bridge.sent[-1]
        bridge.events.append(CommandDone(sent.ticket, sent.line, sent.origin, True, (), 0.0, False))
        await settle(pilot, app)
        assert page.panel.chosen == 150

    drive(app, body)


def test_a_refused_renumber_keeps_the_choice() -> None:
    bridge = FakeBridge(replies={"fixture 101 number 150": Reply(False, "error: no")})
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        await tap(pilot, page.panel.renumber, app)
        await pilot.press(*"150", "enter")
        await settle(pilot, app)
        assert page.panel.chosen == 101

    drive(app, body)


def test_delete_asks_busk_and_takes_the_panel_back(club: busk.OfflineShow) -> None:
    bridge = FakeBridge(show=club)
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        await tap(pilot, page.panel.delete, app)
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)
        assert dialog.question == club.confirmation("delete fixture 101 cascade")
        assert "It leaves groups" in dialog.question
        await pilot.press("n")
        await settle(pilot, app)
        assert bridge.sent == []
        assert ("info", "cancelled: delete fixture 101 cascade") in app.query_one(LogView).entries
        assert page.panel.chosen == 101
        await tap(pilot, page.panel.delete, app)
        await pilot.press("y")
        await settle(pilot, app)
        assert bridge.lines() == ["delete fixture 101 cascade"]
        assert page.panel.chosen is None
        assert page.panel.hint.display
        assert not page.panel.body.display

    drive(app, body)


def test_a_refused_delete_keeps_the_choice() -> None:
    bridge = FakeBridge(replies={"delete fixture 101 cascade": Reply(False, "error: no")})
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        await tap(pilot, page.panel.delete, app)
        assert page.panel.chosen == 101

    drive(app, body)


def test_delete_on_a_run_asks_busk_and_sends_one_line(club: busk.OfflineShow) -> None:
    """101 thru 102 selected, with 102 chosen: one ``thru`` line, one ``undo``."""
    bridge = FakeBridge(show=club)
    app = on_the_rig(bridge, 101, 102)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 102)
        panel = page.panel
        assert (panel.delete.label, panel.delete.inert) == ("delete 101 thru 102", False)
        await tap(pilot, panel.delete, app)
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)
        assert dialog.question == club.confirmation("delete fixture 101 thru 102 cascade")
        assert dialog.question.startswith("Delete 2 fixtures from 101 to 102?")
        await pilot.press("y")
        await settle(pilot, app)
        assert bridge.lines() == ["delete fixture 101 thru 102 cascade"]
        assert panel.chosen is None

    drive(app, body)


def test_a_refused_run_delete_keeps_the_choice() -> None:
    bridge = FakeBridge(replies={"delete fixture 101 thru 103 cascade": Reply(False, "error: no")})
    app = on_the_rig(bridge, 101, 102, 103)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 102)
        await tap(pilot, page.panel.delete, app)
        assert bridge.lines() == ["delete fixture 101 thru 103 cascade"]
        assert page.panel.chosen == 102

    drive(app, body)


def test_delete_follows_the_reach_of_limits(club: busk.OfflineShow) -> None:
    """A run while the chosen fixture is selected; it alone when it is not;
    grey with a fixture left out between."""
    bridge = FakeBridge(show=club)
    app = on_the_rig(bridge, 101, 103)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 201)
        panel = page.panel
        assert (panel.delete.label, panel.delete.inert) == ("delete", False)
        panel.choose(101)
        await pilot.pause()
        assert (panel.delete.label, panel.delete.inert) == ("delete", True)
        assert str(panel.limits_heading.content.plain) == "LIMITS · 101, 103 (2)"
        await tap(pilot, panel.delete, app)
        assert bridge.lines() == []

    drive(app, body)


def test_a_fixture_that_leaves_the_show_takes_the_panel_back() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        bridge.events.append(ShowChanged(editing_rig(*FIXTURES[1:])))  # at the prompt, or by undo
        await settle(pilot, app)
        assert page.panel.chosen is None
        assert page.panel.hint.display
        bridge.events.append(ShowChanged(editing_rig()))  # undo brings it back: not chosen again
        await settle(pilot, app)
        assert page.panel.chosen is None

    drive(app, body)


def test_a_fixture_leaving_out_of_edit_mode_is_not_chosen_on_the_way_in() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(FixturesPage)
        await click_cell(pilot, page.table, 0, "name")
        bridge.events.append(ShowChanged(editing_rig(*FIXTURES[1:])))
        await settle(pilot, app)
        await pilot.click(page.edit)
        await settle(pilot, app)
        assert page.panel.hint.display

    drive(app, body)


def test_what_it_is_and_the_category_chips() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel = page.panel
        assert str(panel.what.content) == "Head · 16ch · 16 channels"
        assert str(panel.category.content) == "category of 3 fixtures"
        assert [b.label.plain[1:-1] for b in panel.categories.buttons] == list(CATEGORIES)
        assert chip_style(panel.categories, "spot") == LIT
        assert chip_style(panel.categories, "wash") == colors.MID
        await tap_chip(pilot, panel.categories, "wash", app)
        await tap_chip(pilot, panel.categories, "spot", app)  # lit: busk would spend a step on it
        await tap_chip(pilot, panel.categories, "none", app)
        assert bridge.lines() == ['profile "Head" category wash', 'profile "Head" category none']
        panel.choose(201)  # no category: none is lit, and busk would refuse it
        await pilot.pause()
        assert str(panel.category.content) == "category of 1 fixture"
        assert chip_style(panel.categories, "none") == LIT
        assert panel.categories.buttons[-1].note

    drive(app, body)


def test_what_it_is_says_one_channel_and_its_elements() -> None:
    dimmer = FixtureInfo(1, 1, "Dimmer", "Dimmer", "1ch", 1)
    assert what_text(dimmer).plain == "Dimmer · 1ch · 1 channel"
    bar = FixtureInfo(2, 12, "Bar", "Pixel Bar", "36ch", 36)
    assert what_text(bar).plain == "Pixel Bar ×12 · 36ch · 36 channels"


def test_a_quote_in_a_profile_name_is_escaped_in_its_chips() -> None:
    bridge = FakeBridge()
    par = ProfileInfo('Par "LED"', frozenset({"intensity"}), ())
    fixture = FixtureInfo(501, 1, "Par 501", 'Par "LED"', "4ch", 4, (1, 1))
    bridge.events.append(ShowChanged(show_model(fixtures=(fixture,), profiles=(par,))))
    app = make_app(bridge, page=3)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 501)
        assert r"""profile "Par \"LED\"" category par""" in [
            button.line.text for button in page.panel.categories.buttons
        ]

    drive(app, body)


def test_the_mode_chips_show_only_for_a_profile_of_several_modes() -> None:
    bridge = FakeBridge(replies={'fixture 401 mode "8ch"': Reply(False, "error: past channel 512")})
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel = page.panel
        assert not panel.modes.display
        panel.choose(401)
        await pilot.pause()
        assert panel.modes.display
        assert chip_style(panel.modes, "4ch") == LIT
        await tap_chip(pilot, panel.modes, "4ch", app)  # lit: nothing to change
        assert bridge.sent == []
        await tap_chip(pilot, panel.modes, "8ch", app)
        assert bridge.lines() == ['fixture 401 mode "8ch"']
        assert ("error", "past channel 512") in app.query_one(LogView).entries

    drive(app, body)


def test_chips_hidden_for_the_next_fixture_are_no_stops() -> None:
    """A strip keeps its buttons while it is hidden."""
    lost = FixtureInfo(501, 1, "Lost", "Gone", "4ch", 4, (1, 1))
    bridge = FakeBridge()
    bridge.events.append(ShowChanged(editing_rig(*FIXTURES, lost)))
    app = make_app(bridge, page=3)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 401)
        panel = page.panel
        assert 'fixture 401 mode "8ch"' in [stop.item.label for stop in panel.stops()]
        panel.choose(101)
        await pilot.pause()
        assert not [s for s in panel.stops() if " mode " in s.item.label]
        assert [s for s in panel.stops() if "category" in s.item.label]
        panel.choose(501)
        await pilot.pause()
        assert not [s for s in panel.stops() if "category" in s.item.label]

    drive(app, body)


def test_a_fixture_of_a_profile_the_show_has_no_info_for_still_shows() -> None:
    bridge = FakeBridge()
    fixture = FixtureInfo(501, 1, "Lost", "Gone", "4ch", 4, (1, 1))
    bridge.events.append(ShowChanged(show_model(fixtures=(fixture,))))
    app = make_app(bridge, page=3)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 501)
        assert not page.panel.categories.display
        assert not page.panel.orientation.display
        assert [n for n, row in page.panel.limits.items() if row.display] == ["intensity"]
        assert not [s for s in page.panel.stops() if "category" in s.item.label]

    drive(app, body)


@pytest.mark.parametrize(
    ("columns", "beside", "fits"), [(150, True, True), (100, True, True), (99, False, False)]
)
def test_the_panel_sits_beside_the_table_or_under_it(
    columns: int, beside: bool, fits: bool
) -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel, sheet = page.panel, page.sheet
        if beside:
            assert panel.region.width == 52
            assert panel.region.y == sheet.region.y
            assert panel.region.x > sheet.region.right - 1
        else:
            assert panel.region.width == sheet.region.width
            assert panel.region.y >= sheet.region.bottom
        assert (panel.styles.max_height is not None) == beside
        lines = page.rig.lines(page.rig.size.width)
        assert "1.17" in lines[2].plain  # the patch stays at any width
        assert "tilt" in lines[1].plain  # and so do the limits

    drive(app, body, size=(columns, 48))


def test_below_100_columns_a_click_scrolls_the_panel_into_sight() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        assert page.scroll_offset.y == 0
        await click_cell(pilot, page.rig, 1, "name")
        await pilot.pause()
        await pilot.pause()
        assert page.scroll_offset.y > 0

    drive(app, body, size=(99, 30))


def test_beside_the_table_a_click_leaves_the_page_where_it_is() -> None:
    bridge = FakeBridge()
    many = tuple(FixtureInfo(n, 1, f"Head {n}", "Head", "16ch", 16, (1, 1)) for n in range(1, 61))
    bridge.events.append(ShowChanged(editing_rig(*many)))
    app = make_app(bridge, page=3)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        page.scroll_to(y=20, animate=False)
        await pilot.pause()
        assert page.scroll_offset.y == 20
        await pilot.click(page.rig, offset=(10, 25))
        await pilot.pause()
        await pilot.pause()
        assert page.scroll_offset.y == 20

    drive(app, body, size=(150, 26))


def test_a_long_panel_scrolls_on_its_own_beside_the_table() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        assert page.panel.region.height <= 20
        assert page.panel.max_scroll_y > 0
        assert page.max_scroll_y > 0  # for GROUPS, under the table
        page.groups.display = False
        await pilot.pause()
        assert page.max_scroll_y == 0  # never for the panel

    drive(app, body, size=(150, 26))


def test_the_pane_cursor_stops_on_every_control_and_no_inert_one() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 102)
        labels = [item.label for item in page.items()]
        rows = [f"fixture {f.number} {f.name}" for f in FIXTURES]
        chips = [f'profile "Head" category {word}' for word in CATEGORIES if word != "spot"]
        assert labels == [
            "+ add", "edit",
            *rows,
            "rename…", "number…", "delete", "profile…",
            *chips,
            "[none]", "address…", "next free",
            "pan limit…", "tilt limit…", "intensity limit…",  # no fixture here has one to remove
            "park…",
            "invert pan", "invert tilt", "swap pan/tilt",
            "pan offset…", "tilt offset…",
            "location…",
            "done",
        ]  # fmt: skip
        assert len(labels) == len(set(labels))  # the cursor finds its place again by the label
        page.panel.choose(101)
        await pilot.pause()
        labels = [item.label for item in page.items()]
        assert "tilt none" in labels
        assert "no limits" in labels
        page.panel.choose(None)
        await pilot.pause()
        assert [item.label for item in page.items()][-2:] == [rows[-1], "done"]

    drive(app, body)


def test_the_pane_cursor_marks_the_table_that_shows() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        await pilot.press("tab", "down", "down")
        line = page.rig.line(1, page.rig.size.width)
        assert MARKED in [str(span.style) for span in line.spans]

    drive(app, body)


def test_the_pane_cursor_takes_a_panel_control() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 102)
        items = page.items()
        index = next(i for i, item in enumerate(items) if item.label == "invert pan")
        await pilot.press("tab", *["down"] * index, "enter")
        await settle(pilot, app)
        assert bridge.lines() == ["fixture 102 orientation.invertPan true"]

    drive(app, body)


# ---------------------------------------------------------------- limits


def test_the_words_of_a_limit_and_a_place() -> None:
    limits = Limits((-180.5, 180.0), None, 0.5)
    assert limit_text("pan", limits).plain == "-180.5° to 180°"
    assert limit_text("tilt", limits).plain == "none"
    assert limit_text("intensity", limits).plain == "at most 50%"
    assert limit_text("intensity", Limits(intensity=0.0)).plain == "at most 0%"
    assert location_text(None).plain == "LOCATION no place"
    place = location_text((1.5, 2.0, 4.0, 0.0, 0.0, 90.0))
    assert place.plain == "LOCATION x 1.5 y 2 z 4 rx 0 ry 0 rz 90"
    assert spans_text([(101, 102), (201, 201)]) == "101 thru 102, 201"


@pytest.mark.parametrize(
    ("values", "problem"),
    [
        (("-90", "10"), None),
        (("10", "10"), None),  # busk takes a limit of one value
        (("-90.5", " 10 "), None),
        (("10", "-90"), "10 is above -90"),
        (("x", "10"), "two numbers, in degrees"),
        (("", "10"), "two numbers, in degrees"),
        (("nan", "10"), "two numbers, in degrees"),
        (("-inf", "10"), "two numbers, in degrees"),
    ],
)
def test_a_limits_form_checks_its_two_ends(values: tuple[str, str], problem: str | None) -> None:
    assert check_span(values) == problem


@pytest.mark.parametrize(
    ("text", "level"),
    [("50", 0.5), ("50%", 0.5), (" 50 % ", 0.5), ("0", 0.0), ("100", 1.0), ("12.5", 0.125),
     ("101", None), ("-1", None), ("x", None), ("", None), ("nan", None)],
)  # fmt: skip
def test_a_level_is_read_from_0_to_100(text: str, level: float | None) -> None:
    assert read_level(text) == level
    assert (check_level((text,)) is None) == (level is not None)


def test_a_places_form_takes_six_numbers() -> None:
    assert check_place(("1", "-2.5", "0", "0", "0", "90")) is None
    assert check_place(("1", "x", "0", "0", "0", "90")) == "six numbers"
    assert check_place(("1", "inf", "0", "0", "0", "90")) == "six numbers"


def test_the_rows_of_limits_follow_the_profile() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 102)
        panel = page.panel

        def shown() -> list[str]:
            return [name for name, row in panel.limits.items() if row.display]

        assert shown() == ["pan", "tilt", "intensity"]
        panel.choose(201)
        await pilot.pause()
        assert shown() == ["intensity"]  # always
        panel.choose(301)
        await pilot.pause()
        assert shown() == ["pan", "intensity"]

    drive(app, body)


def test_a_limit_starts_at_itself_else_at_the_profiles_range() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel = page.panel
        await tap(pilot, panel.limits["tilt"].buttons[0], app)
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert [field.value for field in dialog.inputs] == ["-90", "10"]
        assert dialog.labels == ("from", "to")
        assert dialog.note == "the profile goes from -135° to 135°"
        await pilot.press("escape")
        await settle(pilot, app)
        await tap(pilot, panel.limits["pan"].buttons[0], app)
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert [field.value for field in dialog.inputs] == ["-270", "270"]
        await pilot.press("escape")
        await settle(pilot, app)
        await tap(pilot, panel.limits["intensity"].buttons[0], app)
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert [field.value for field in dialog.inputs] == ["100%"]
        assert dialog.labels == ("at most",)
        await pilot.press("escape")
        await settle(pilot, app)
        assert bridge.sent == []

    drive(app, body)


def test_each_limit_through_its_dialog_and_the_dialogs_refusals() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel = page.panel
        await tap(pilot, panel.limits["tilt"].buttons[0], app)
        await pilot.press(*"50", "tab", *"-50", "enter")
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert "50 is above -50" in str(dialog.error.content)
        assert bridge.sent == []
        await pilot.press("ctrl+u", *"60", "enter")
        await settle(pilot, app)
        assert bridge.lines() == ["fixture 101 limits tilt 50 60"]
        await tap(pilot, panel.limits["intensity"].buttons[0], app)
        await pilot.press(*"120", "enter")
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert "from 0 to 100%" in str(dialog.error.content)
        await pilot.press("ctrl+u", *"40", "enter")
        await settle(pilot, app)
        assert bridge.lines()[1:] == ["fixture 101 limits intensity 40%"]

    drive(app, body)


def test_none_shows_where_the_reach_has_that_limit_and_no_limits_is_inert_without_any() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 102)
        panel = page.panel

        def nones() -> list[str]:
            return [name for name, row in panel.limits.items() if row.buttons[1].display]

        assert nones() == []
        assert panel.no_limits.inert
        await tap(pilot, panel.no_limits, app)
        assert bridge.sent == []
        panel.choose(101)
        await pilot.pause()
        assert nones() == ["tilt"]
        assert not panel.no_limits.inert
        await tap(pilot, panel.limits["tilt"].buttons[1], app)
        await tap(pilot, panel.no_limits, app)
        assert bridge.lines() == ["fixture 101 limits tilt none", "fixture 101 limits none"]

    drive(app, body)


def test_an_intensity_limit_of_zero_can_be_removed() -> None:
    bridge = FakeBridge()
    dark = FixtureInfo(201, 1, "Par 1", "Flat Par", "4ch", 4, (1, 49), limits=Limits(intensity=0.0))
    bridge.events.append(ShowChanged(editing_rig(dark)))
    app = make_app(bridge, page=3)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 201)
        drop = page.panel.limits["intensity"].buttons[1]
        assert drop.display
        await tap(pilot, drop, app)
        assert bridge.lines() == ["fixture 201 limits intensity none"]

    drive(app, body)


def test_limits_go_out_as_a_line_per_run_of_the_selection() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge, 101, 102)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 101)
        panel = page.panel
        assert str(panel.limits_heading.content) == "LIMITS · 101 thru 102 (2)"
        await tap(pilot, panel.limits["tilt"].buttons[0], app)
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.lines() == ["fixture 101 thru 102 limits tilt -90 10"]  # one line

    drive(app, body)


def test_a_fixture_between_that_is_not_selected_parts_the_lines() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge, 101, 103)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 101)
        panel = page.panel
        assert str(panel.limits_heading.content) == "LIMITS · 101, 103 (2)"
        await tap(pilot, panel.limits["intensity"].buttons[0], app)
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.lines() == [
            "fixture 101 limits intensity 100%",
            "fixture 103 limits intensity 100%",
        ]

    drive(app, body)


def test_a_gap_in_the_numbers_does_not_part_the_lines() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge, 103, 201)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 103)
        assert str(page.panel.limits_heading.content) == "LIMITS · 103 thru 201 (2)"

    drive(app, body)


def test_a_removal_leaves_out_a_run_with_nothing_to_remove() -> None:
    """busk refuses a span where no fixture has the limit: 103 has none."""
    bridge = FakeBridge()
    app = on_the_rig(bridge, 101, 103)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 101)
        panel = page.panel
        await tap(pilot, panel.limits["tilt"].buttons[1], app)
        await tap(pilot, panel.no_limits, app)
        assert bridge.lines() == ["fixture 101 limits tilt none", "fixture 101 limits none"]

    drive(app, body)


def test_the_reach_is_the_chosen_fixture_alone_while_it_is_not_selected() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge, 101, 102)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 201)
        panel = page.panel
        assert str(panel.limits_heading.content) == "LIMITS · 201"
        await tap(pilot, panel.limits["intensity"].buttons[1], app)
        assert bridge.lines() == ["fixture 201 limits intensity none"]

    drive(app, body)


def test_the_selection_changing_moves_the_reach() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 102)
        panel = page.panel
        assert str(panel.limits_heading.content) == "LIMITS · 102"
        assert not panel.limits["tilt"].buttons[1].display
        bridge.events.append(ProgrammerChanged(programmer(selection=((101, 1), (102, 1)))))
        await settle(pilot, app)
        assert str(panel.limits_heading.content) == "LIMITS · 101 thru 102 (2)"
        assert str(panel.orientation_heading.content) == "ORIENTATION · 101 thru 102 (2)"
        assert panel.limits["tilt"].buttons[1].display  # 101 has it
        assert panel.limits["tilt"].value.content.plain == "none"  # the chosen one's

    drive(app, body)


def test_a_paste_too_long_for_a_number_stays_in_the_dialog() -> None:
    """``int`` raises past 4,300 digits, which would end the TUI."""
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 102)
        await tap(pilot, page.panel.renumber, app)
        dialog = app.screen
        assert isinstance(dialog, TextDialog)
        dialog.query_one(Input).post_message(events.Paste("7" * 5000))
        await pilot.pause()
        await pilot.press("enter")
        await settle(pilot, app)
        assert app.screen is dialog
        assert "a whole number" in str(dialog.error.content)
        assert bridge.lines() == []

    drive(app, body)


# ----------------------------------------------------------- orientation


def test_the_toggles_follow_the_document_and_a_line_goes_per_run() -> None:
    bridge = FakeBridge()
    turned = Orientation(invertPan=True, panOffset=30.0)
    fixtures = (
        FixtureInfo(101, 1, "Head 1", "Head", "16ch", 16, (1, 1), orientation=turned),
        *FIXTURES[1:],
    )
    bridge.events += [
        ShowChanged(editing_rig(*fixtures)),
        ProgrammerChanged(programmer(selection=((101, 1), (102, 1), (103, 1)))),
    ]
    app = make_app(bridge, page=3)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 102)
        panel = page.panel
        assert not panel.toggles["invertPan"].reverse  # lit from the chosen fixture
        await tap(pilot, panel.toggles["invertPan"], app)
        assert bridge.lines() == ["fixture 101 thru 103 orientation.invertPan true"]
        panel.choose(101)
        await pilot.pause()
        assert panel.toggles["invertPan"].reverse
        assert panel.toggles["invertPan"].intent == "record"
        assert not panel.toggles["invertTilt"].reverse
        assert panel.offsets["panOffset"].value.content.plain == "30°"
        bridge.sent.clear()
        await tap(pilot, panel.toggles["invertPan"], app)
        assert bridge.lines() == ["fixture 101 thru 103 orientation.invertPan false"]

    drive(app, body)


def test_orientation_leaves_out_what_is_not_selected_and_a_run_with_nothing_to_change() -> None:
    bridge = FakeBridge()
    turned = Orientation(invertPan=True)
    fixtures = (
        FixtureInfo(101, 1, "Head 1", "Head", "16ch", 16, (1, 1), orientation=turned),
        *FIXTURES[1:],
    )
    bridge.events += [
        ShowChanged(editing_rig(*fixtures)),
        ProgrammerChanged(programmer(selection=((101, 1), (103, 1), (201, 1)))),
    ]
    app = make_app(bridge, page=3)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 103)
        panel = page.panel
        await tap(pilot, panel.toggles["invertPan"], app)
        # 102 parts the runs, and 101 is there already: busk would spend an undo step on it
        assert bridge.lines() == ["fixture 103 thru 201 orientation.invertPan true"]
        bridge.sent.clear()
        await tap(pilot, panel.toggles["invertTilt"], app)
        assert bridge.lines() == [
            "fixture 101 orientation.invertTilt true",
            "fixture 103 thru 201 orientation.invertTilt true",
        ]

    drive(app, body)


def test_orientation_shows_only_where_it_means_something() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 201)
        panel = page.panel
        labels = [stop.item.label for stop in panel.stops()]
        assert not panel.orientation.display  # a par
        assert not {"invert pan", "invert tilt", "swap pan/tilt"} & set(labels)
        panel.choose(301)  # pan and no tilt
        await pilot.pause()
        assert panel.orientation.display
        assert [k for k, button in panel.toggles.items() if button.display] == ["invertPan"]
        assert [k for k, row in panel.offsets.items() if row.display] == ["panOffset"]
        labels = [stop.item.label for stop in panel.stops()]
        assert "swap pan/tilt" not in labels
        assert "tilt offset…" not in labels
        panel.choose(101)
        await pilot.pause()
        assert all(button.display for button in panel.toggles.values())

    drive(app, body)


def test_an_offset_through_its_dialog() -> None:
    bridge = FakeBridge()
    app = on_the_rig(bridge, 101, 102)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 101)
        await tap(pilot, page.panel.offsets["tiltOffset"].buttons[0], app)
        dialog = app.screen
        assert isinstance(dialog, TextDialog)
        assert dialog.title_text == "TILT OFFSET · 101 thru 102"
        assert dialog.initial == "0"
        await pilot.press(*"up", "enter")
        assert isinstance(app.screen, TextDialog)
        assert "a number" in str(app.screen.error.content)
        await pilot.press("ctrl+u", *"-12.5", "enter")
        await settle(pilot, app)
        assert bridge.lines() == ["fixture 101 thru 102 orientation.tiltOffset -12.5"]

    drive(app, body)


# -------------------------------------------------------------- location


def test_a_first_location_a_change_and_no_place() -> None:
    bridge = FakeBridge()
    placed = FixtureInfo(
        102, 1, "Head 2", "Head", "16ch", 16, (1, 17), location=(1.5, 2.0, 4.0, 0.0, 0.0, 90.0)
    )
    bridge.events += [
        ShowChanged(editing_rig(FIXTURES[0], placed, *FIXTURES[2:])),
        ProgrammerChanged(programmer(selection=((101, 1), (102, 1)))),
    ]
    app = make_app(bridge, page=3)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 101)
        panel = page.panel
        assert str(panel.place.content) == "LOCATION no place"
        assert not panel.no_place.display
        await tap(pilot, panel.locate, app)
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert dialog.labels == ("x", "y", "z", "rx", "ry", "rz")
        assert [field.value for field in dialog.inputs] == ["0"] * 6
        await pilot.press(*"north", "enter")
        assert isinstance(app.screen, FormDialog)
        assert "six numbers" in str(app.screen.error.content)
        await pilot.press("ctrl+u", *"1", "tab", *"-2.5", "enter")
        await settle(pilot, app)
        assert bridge.lines() == [
            'fixture 101 location {"x": 1, "y": -2.5, "z": 0, "rx": 0, "ry": 0, "rz": 0}'
        ]  # the chosen one only, though 102 is selected too
        bridge.sent.clear()
        panel.choose(102)
        await pilot.pause()
        assert str(panel.place.content) == "LOCATION x 1.5 y 2 z 4 rx 0 ry 0 rz 90"
        assert column(page.rig, "place")[:2] == ["·", "●"]
        await tap(pilot, panel.locate, app)
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert [field.value for field in dialog.inputs] == ["1.5", "2", "4", "0", "0", "90"]
        await pilot.press("enter")  # the same place: nothing to send
        await settle(pilot, app)
        assert bridge.sent == []
        await tap(pilot, panel.locate, app)
        await pilot.press("ctrl+u", *"3", "enter")
        await settle(pilot, app)
        assert bridge.lines() == [
            'fixture 102 location {"x": 3, "y": 2, "z": 4, "rx": 0, "ry": 0, "rz": 90}'
        ]
        bridge.sent.clear()
        await tap(pilot, panel.no_place, app)
        assert bridge.lines() == ["fixture 102 location none"]

    drive(app, body)


# ---------------------------------------- groups and park (pending plan Phase 12)

GROUPS = (
    GroupInfo(1, "Heads", ((101, 1), (102, 1), (103, 1))),
    GroupInfo(2, "Floor", ((201, 1), (301, 1))),
    GroupInfo(5, "Empty"),
)
STRIP = ProfileInfo("Strip", frozenset({"intensity", "color", "color.w"}), (), "pixel")
PIXELS = FixtureInfo(501, 4, "Strip 1", "Strip", "16ch", 16, (2, 1))


def grouped_rig(**changes: Any) -> ShowModel:
    """The rig above with three groups and a strip of four pixels."""
    rig = editing_rig(*FIXTURES, PIXELS)
    parts: dict[str, Any] = {"groups": GROUPS, "profiles": (*rig.profiles, STRIP)}
    parts.update(changes)
    return replace(rig, **parts)


def on_the_groups(bridge: FakeBridge, *selected: tuple[int, int], **changes: Any) -> BuskApp:
    """F3 on :func:`grouped_rig`, with ``selected`` elements selected."""
    bridge.events += [
        ShowChanged(grouped_rig(**changes)),
        ProgrammerChanged(programmer(selection=selected)),
    ]
    return make_app(bridge, page=3)


def select(bridge: FakeBridge, *selected: tuple[int, int]) -> None:
    bridge.events.append(ProgrammerChanged(programmer(selection=selected)))


def test_a_groups_row_and_what_merge_replace_and_remove_would_change() -> None:
    heads, _, empty = GROUPS
    cells = group_cells(heads, True, FIXTURES)
    assert [cells[name].plain for name in ("number", "name", "members")] == [
        "1", "Heads", "101 thru 103",
    ]  # fmt: skip
    assert str(cells["number"].spans[0].style) == LIT
    assert str(group_cells(heads, False, FIXTURES)["number"].spans[0].style) == colors.MID
    assert group_cells(empty, False, FIXTURES)["members"].plain == "—"
    pixels = GroupInfo(7, "Ends", ((501, 1), (501, 4), (501, 2)))
    assert group_cells(pixels, False, (PIXELS,))["members"].plain == "501.1, 501.4, 501.2"
    members = ((101, 1), (102, 1))
    table = [
        (how, selection, changes(how, members, selection))
        for how in WRITES
        for selection in ((), ((101, 1),), ((102, 1), (101, 1)), ((101, 1), (102, 1)),
                          ((301, 1),), ((101, 1), (301, 1)))
    ]  # fmt: skip
    assert [found for *_, found in table] == [
        False, False, False, False, True, True,  # merge: something they lack
        False, True, True, False, True, True,  # replace: not them, in their order
        False, True, True, True, False, True,  # remove: one of them
    ]  # fmt: skip


def test_groups_show_in_edit_mode_under_the_table_and_a_click_only_chooses() -> None:
    bridge = FakeBridge()
    app = on_the_groups(bridge, (201, 1))

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(FixturesPage)
        assert not page.groups.display
        page = await enter(pilot, app, None)
        groups = page.groups
        assert groups.display
        assert groups.region.y >= page.sheet.region.bottom
        assert str(groups.border_title) == "GROUPS"
        assert "3 groups · click chooses" in str(groups.count.content)
        assert column(groups.table, "number") == ["1", "2", "5"]
        assert column(groups.table, "members") == ["101 thru 103", "201, 301", "—"]
        bridge.events.append(ShowChanged(grouped_rig(groups=GROUPS[::-1])))  # a renumber's order
        await settle(pilot, app)
        assert column(groups.table, "number") == ["1", "2", "5"]
        assert not groups.choice.display
        assert not groups.with_row.display
        await click_cell(pilot, groups.table, 1, "name")
        await settle(pilot, app)
        assert bridge.sent == []  # the selection stays
        assert page.panel.chosen is None  # the rig's choice too
        assert groups.chosen == 2
        assert groups.table.chosen == 1
        assert str(groups.label.content) == "group 2 Floor"
        assert str(groups.with_words.content) == "selection 201"
        page.set_editing(False)
        await pilot.pause()
        assert not groups.display

    drive(app, body)


def test_below_100_columns_groups_come_between_the_table_and_the_panel() -> None:
    bridge = FakeBridge()
    app = on_the_groups(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        assert page.sheet.region.bottom <= page.groups.region.y
        assert page.groups.region.bottom <= page.panel.region.y
        assert page.groups.region.width == page.sheet.region.width

    drive(app, body, size=(99, 80))


def test_record_takes_the_selection_as_a_new_group_and_chooses_it() -> None:
    bridge = FakeBridge()
    app = on_the_groups(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, None)
        groups = page.groups
        assert groups.record.inert  # nothing selected
        await tap(pilot, groups.record, app)
        assert not isinstance(app.screen, FormDialog)
        groups.ask_record()  # a pane cursor's stale stop
        await pilot.pause()
        assert not isinstance(app.screen, FormDialog)
        select(bridge, (301, 1), (101, 1))
        await settle(pilot, app)
        assert not groups.record.inert
        await tap(pilot, groups.record, app)
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert [field.value for field in dialog.inputs] == ["6", ""]
        assert dialog.note.splitlines() == [
            "taken: 1–2, 5",
            "members: 301, 101",
            "no name: busk names it Group <number>",
        ]
        await pilot.press("ctrl+u", "2", "tab", *"Spots", "enter")
        assert "2 is taken" in str(dialog.error.content)
        await pilot.press("shift+tab", "ctrl+u", "8", "enter")
        await settle(pilot, app)
        assert bridge.lines() == ['record group 8 "Spots"']
        assert groups.chosen == 8  # before the show has it: nothing shows for it yet
        assert not groups.choice.display
        new = GroupInfo(8, "Spots", ((301, 1), (101, 1)))
        bridge.events.append(ShowChanged(grouped_rig(groups=(*GROUPS, new))))
        await settle(pilot, app)
        assert groups.table.chosen == 3
        assert str(groups.label.content) == "group 8 Spots"
        bridge.sent.clear()
        await tap(pilot, groups.record, app)
        await pilot.press("enter")  # no name: busk's
        await settle(pilot, app)
        assert bridge.lines() == ["record group 9"]  # after the highest, as F4 and F1 do

    drive(app, body)


def test_merge_runs_replace_and_remove_ask_and_each_is_grey_when_it_changes_nothing() -> None:
    bridge = FakeBridge()
    app = on_the_groups(bridge, (102, 1))

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, None)
        groups = page.groups
        groups.choose(1)
        await pilot.pause()

        def inert() -> list[str]:
            return [how for how, button in groups.writes.items() if button.inert]

        assert inert() == ["merge"]  # 102 is a member
        await tap(pilot, groups.writes["merge"], app)
        assert bridge.sent == []
        await tap(pilot, groups.writes["remove"], app)
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)
        assert dialog.question.splitlines() == [
            'Take the selection out of group 1 "Heads"?',
            "It keeps 2 of its 3 members.",
        ]
        await pilot.press("y")
        await settle(pilot, app)
        assert bridge.lines() == ["record group 1 remove"]
        bridge.sent.clear()
        await tap(pilot, groups.writes["replace"], app)
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)
        assert dialog.question == 'Replace the members of group 1 "Heads" with the selection?'
        await pilot.press("n")
        await settle(pilot, app)
        assert bridge.sent == []
        select(bridge, (201, 1), (101, 1))
        await settle(pilot, app)
        assert inert() == []
        await tap(pilot, groups.writes["merge"], app)  # no question
        assert bridge.lines() == ["record group 1 merge"]
        select(bridge, (401, 1))
        await settle(pilot, app)
        assert inert() == ["remove"]
        select(bridge, (101, 1), (102, 1), (103, 1))
        await settle(pilot, app)
        assert inert() == ["merge", "replace"]
        await tap(pilot, groups.writes["remove"], app)
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)
        assert dialog.question.splitlines()[1] == "It stays, with no members."
        await pilot.press("n")
        select(bridge)
        await settle(pilot, app)
        assert inert() == list(WRITES)
        assert str(groups.with_words.content) == "selection nothing"
        bridge.sent.clear()
        for how in WRITES:  # a pane cursor's stale stop sends nothing either
            groups.write(how)
        await settle(pilot, app)
        assert bridge.sent == []

    drive(app, body)


def test_rename_and_renumber_a_group_and_the_choice_follows() -> None:
    bridge = FakeBridge()
    app = on_the_groups(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, None)
        groups = page.groups
        groups.choose(2)
        await pilot.pause()
        await tap(pilot, groups.rename, app)
        assert isinstance(app.screen, TextDialog)
        await pilot.press("enter")  # the name it has
        await settle(pilot, app)
        await tap(pilot, groups.rename, app)
        await pilot.press("ctrl+u", "enter")
        dialog = app.screen
        assert isinstance(dialog, TextDialog)
        assert "cannot be empty" in str(dialog.error.content)
        await pilot.press(*"Floor 'n' bar", "enter")
        await settle(pilot, app)
        assert bridge.lines() == ["rename group 2 \"Floor 'n' bar\""]
        bridge.sent.clear()
        await tap(pilot, groups.renumber, app)
        dialog = app.screen
        assert isinstance(dialog, TextDialog)
        assert dialog.note == "taken: 1, 5"
        await pilot.press("ctrl+u", "5", "enter")
        assert "5 is taken" in str(dialog.error.content)
        await pilot.press("ctrl+u", "2", "enter")  # its own: nothing to send
        await settle(pilot, app)
        assert bridge.sent == []
        await tap(pilot, groups.renumber, app)
        await pilot.press("ctrl+u", "9", "enter")
        await settle(pilot, app)
        assert bridge.lines() == ["group 2 number 9"]
        assert groups.chosen == 9
        select(bridge, (101, 1))  # the old show still: the choice waits for the new one
        await settle(pilot, app)
        assert groups.chosen == 9
        moved = (GROUPS[0], GroupInfo(9, "Floor", GROUPS[1].members), GROUPS[2])
        bridge.events.append(ShowChanged(grouped_rig(groups=moved)))
        await settle(pilot, app)
        assert str(groups.label.content) == "group 9 Floor"

    drive(app, body)


def test_delete_asks_busk_and_a_group_that_leaves_the_show_is_chosen_no_more(
    club: busk.OfflineShow,
) -> None:
    bridge = FakeBridge(show=club)
    app = on_the_groups(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, None)
        groups = page.groups
        groups.choose(2)
        await pilot.pause()
        await tap(pilot, groups.delete, app)
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)
        assert dialog.question == club.confirmation("delete group 2 cascade")
        assert "master" in dialog.question
        await pilot.press("n")
        await settle(pilot, app)
        assert bridge.sent == []
        assert groups.chosen == 2
        await tap(pilot, groups.delete, app)
        await pilot.press("y")
        await settle(pilot, app)
        assert bridge.lines() == ["delete group 2 cascade"]
        assert groups.chosen is None
        assert not groups.choice.display
        groups.choose(1)
        bridge.events.append(ShowChanged(grouped_rig(groups=GROUPS[1:])))
        await settle(pilot, app)
        assert groups.chosen is None
        assert column(groups.table, "number") == ["2", "5"]

    drive(app, body)


@pytest.mark.parametrize("button", ["rename", "renumber"])
def test_a_group_that_leaves_the_show_under_its_dialog_gets_no_line(button: str) -> None:
    bridge = FakeBridge()
    app = on_the_groups(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, None)
        groups = page.groups
        groups.choose(2)
        await pilot.pause()
        await tap(pilot, getattr(groups, button), app)
        assert isinstance(app.screen, TextDialog)
        bridge.events.append(ShowChanged(grouped_rig(groups=GROUPS[:1])))  # deleted meanwhile
        await settle(pilot, app)
        assert groups.chosen is None
        await pilot.press("ctrl+u", "8", "enter")
        await settle(pilot, app)
        assert bridge.sent == []

    drive(app, body)


def test_a_refused_delete_or_renumber_keeps_the_group_chosen() -> None:
    bridge = FakeBridge(
        replies={
            "delete group 1 cascade": Reply(False, "error: no"),
            "group 1 number 4": Reply(False, "error: no"),
        }
    )
    app = on_the_groups(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, None)
        groups = page.groups
        groups.choose(1)
        await pilot.pause()
        await tap(pilot, groups.delete, app)
        await tap(pilot, groups.renumber, app)
        await pilot.press("ctrl+u", "4", "enter")
        await settle(pilot, app)
        assert bridge.lines() == ["delete group 1 cascade", "group 1 number 4"]
        assert groups.chosen == 1

    drive(app, body)


def test_the_pane_cursor_stops_on_the_groups() -> None:
    bridge = FakeBridge()
    app = on_the_groups(bridge, (102, 1))

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, None)
        rows = [f"fixture {f.number} {f.name}" for f in (*FIXTURES, PIXELS)]
        labels = [item.label for item in page.items()]
        assert labels == [
            "+ add", "edit", *rows,
            "record group…", "group 1 Heads", "group 2 Floor", "group 5 Empty",
            "done",
        ]  # fmt: skip
        page.groups.choose(1)
        await pilot.pause()
        labels = [item.label for item in page.items()]
        assert labels[len(rows) + 6 : -1] == [
            "group rename…", "group number…", "group delete", "group replace", "group remove",
        ]  # fmt: skip
        assert len(labels) == len(set(labels))
        page.items()[len(rows) + 4].action()  # group 2
        await pilot.pause()
        assert page.groups.chosen == 2

    drive(app, body)


def test_the_source_column_reads_park_first_in_amber() -> None:
    parked = out(101, sources=(("intensity", "park"), ("position", "programmer")), playback=None)
    head = fixture_cells(SPOT, (parked, HEAD), False, "spot", "256")
    assert head["source"].plain == "park"
    assert styles(head, "intensity") == colors.AMBER
    assert styles(head, "pan") == colors.MAGENTA
    assert source_text("park", None) == "park"
    keys = [text.plain for text in legend()]
    assert keys[:5] == ["■ park", "■ programmer", "■ playback", "■ effect", "■ nothing"]
    assert str(legend()[0].spans[0].style) == colors.AMBER


def test_what_park_holds_on_a_fixture_and_the_park_forms_check() -> None:
    red = (("r", 1.0), ("g", 0.0), ("b", 0.0))
    park = (
        Parked(501, 1, "intensity", 0.0),
        Parked(201, 1, "intensity", 0.5),
        Parked(501, 2, "intensity", 0.0),
        Parked(501, 1, "color", red),
        Parked(501, 2, "color", red),
        Parked(501, 3, "color", red),
        Parked(501, 4, "color", red),
    )
    show = grouped_rig(park=park)
    assert parked_text(PIXELS, show).plain.splitlines() == [
        "intensity 0% · 501.1 thru 501.2",
        "color 1.00 0.00 0.00",
    ]
    assert parked_text(FIXTURES[0], show).plain == "nothing parked"
    assert parked_text(FIXTURES[0], None).plain == "nothing parked"
    check = check_park(("intensity", "color"))
    assert check(("intensity", "0")) is None
    assert check((" color ", "1 0 0")) is None
    assert check(("pan", "0")) == "an attribute these fixtures take, as the note lists them"
    assert check(("color.w", "0.5")) is not None
    assert check(("intensity", " ")) == "a value: 0, 50%, -45, 1 0 0, or an option"


def test_park_through_its_dialog_on_the_chosen_fixture() -> None:
    bridge = FakeBridge()
    app = on_the_groups(bridge, park=(Parked(101, 1, "pan", -45.0),))

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 101)
        panel = page.panel
        assert str(panel.park_heading.content) == "PARK · 101"
        assert str(panel.parked.content) == "pan -45°"
        assert panel.parkable() == ("intensity", "pan", "tilt")
        await tap(pilot, panel.park, app)
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert dialog.title_text == "PARK · 101"
        assert [field.value for field in dialog.inputs] == ["intensity", "0"]
        assert dialog.note.splitlines() == [
            "attributes: intensity pan tilt",
            "value: 0 to 1 or 50%, degrees, r g b, or an option",
        ]
        await pilot.press("ctrl+u", *"gobo1", "enter")
        assert "an attribute these fixtures take" in str(dialog.error.content)
        assert bridge.sent == []
        await pilot.press("ctrl+u", *"tilt", "tab", "ctrl+u", *"-20", "enter")
        await settle(pilot, app)
        assert bridge.lines() == ["park fixture 101 tilt -20"]

    drive(app, body)


def test_a_long_list_of_attributes_wraps_in_the_park_form_and_it_starts_at_the_first() -> None:
    many = frozenset(attributes.FAMILY_OF) - {"control"}
    big = ProfileInfo("Big", many, (), "spot")
    mover = ProfileInfo("Mover", frozenset({"tilt", "pan"}), (), "spot")
    show = editing_rig(
        *FIXTURES,
        FixtureInfo(601, 1, "Big 1", "Big", "16ch", 16, (3, 1)),
        FixtureInfo(602, 1, "Mover 1", "Mover", "2ch", 2, (3, 20)),
    )
    bridge = FakeBridge()
    bridge.events.append(ShowChanged(replace(show, profiles=(*show.profiles, big, mover))))
    app = make_app(bridge, page=3)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 601)
        await tap(pilot, page.panel.park, app)
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        *lines, _ = dialog.note.splitlines()
        assert len(lines) > 1
        assert all(len(line) <= 54 for line in lines)
        assert " ".join(lines).split()[1:] == [a for a in attributes.FAMILY_OF if a in many]
        assert dialog.inputs[0].value == "intensity"
        await pilot.press("escape")
        page.panel.choose(602)  # no intensity: busk's order, pan first
        await pilot.pause()
        assert page.panel.parkable() == ("pan", "tilt")
        await tap(pilot, page.panel.park, app)
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert dialog.inputs[0].value == "pan"

    drive(app, body)


def test_park_reaches_the_selected_elements_while_the_chosen_fixture_is_selected() -> None:
    bridge = FakeBridge()
    app = on_the_groups(bridge, (101, 1), (102, 1), (501, 2), (501, 3))

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 501)
        panel = page.panel
        assert str(panel.park_heading.content) == "PARK · 101 thru 102, 501.2 thru 501.3"
        assert panel.parkable() == ("intensity", "pan", "tilt", "color")
        await tap(pilot, panel.park, app)
        await pilot.press("tab", "ctrl+u", *"50%", "enter")
        await settle(pilot, app)
        assert bridge.lines() == [
            "park fixture 101 thru 102, fixture 501.2 thru 501.3 intensity 50%"
        ]
        bridge.sent.clear()
        panel.choose(201)  # not selected: the whole of it
        await pilot.pause()
        assert str(panel.park_heading.content) == "PARK · 201"
        assert panel.parkable() == ("intensity",)
        await tap(pilot, panel.park, app)
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.lines() == ["park fixture 201 intensity 0"]
        bridge.sent.clear()
        panel.choose(501)
        select(bridge, (502, 1))
        await settle(pilot, app)
        assert str(panel.park_heading.content) == "PARK · 501"  # every pixel

    drive(app, body)


def test_park_is_grey_where_the_profile_says_nothing() -> None:
    bridge = FakeBridge()
    bridge.events.append(ShowChanged(rig()))  # profiles with no attributes
    app = make_app(bridge, page=3)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 101)
        assert page.panel.park.inert
        await tap(pilot, page.panel.park, app)
        assert not isinstance(app.screen, FormDialog)
        page.panel.ask_park()  # a pane cursor's stale stop
        await pilot.pause()
        assert not isinstance(app.screen, FormDialog)
        assert "park…" not in [item.label for item in page.items()]

    drive(app, body)
