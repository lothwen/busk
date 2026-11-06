"""F8 Patch (spec §8.8, plan Phase 4): footprints, overlaps (the TupperDMX
show's double-patched heads give two) and the used count; the DMX map's
glyphs and colours by category, or by profile without one; the hover text
and the click lines; the route states, their lights and packet rates; the
universes' strip, and the place a click on a free channel arms
(``docs/plans/tui-rig-plan.md`` §6.3). Headless, with a fake bridge."""

from __future__ import annotations

from typing import Any

from textual.pilot import Pilot
from textual.widgets import Input
from tui_fakes import FakeBridge, Reply, column, drive, make_app, programmer, settle, show_model

import busk
from busk_tui import bridge as bridge_module
from busk_tui import colors
from busk_tui.formats import runs
from busk_tui.model import (
    CommandDone,
    FixtureInfo,
    ProfileInfo,
    ProgrammerChanged,
    RoutesChanged,
    RouteView,
    ShowChanged,
    ShowModel,
    UniverseView,
)
from busk_tui.pages.fixtures import FixturesPage
from busk_tui.pages.patch import (
    NO_PLACE,
    PatchPage,
    RoutesTable,
    UniverseTable,
    legend,
    route_cells,
)
from busk_tui.shell import BuskApp
from busk_tui.widgets.controls import ButtonStrip
from busk_tui.widgets.dialogs import ConfirmDialog, FormDialog, TextDialog
from busk_tui.widgets.dmxmap import (
    OVERLAP,
    DmxMap,
    Footprint,
    channel_text,
    clashes,
    first_free,
    footprints,
    free_from,
    overlaps,
    owners,
    used,
)
from busk_tui.widgets.log import LogView
from busk_tui.widgets.prompt import HintRow

TUPPER = (  # the TupperDMX show's patch: (number, profile, footprint, address)
    (101, "LED Bar", 7, 1), (201, "Blinder", 8, 33), (202, "Blinder", 8, 65),
    (301, "Smoke", 1, 73), (401, "Par", 6, 74), (402, "Par", 6, 80), (403, "Par", 6, 86),
    (501, "Head", 12, 92), (502, "Head", 12, 92), (503, "Head", 12, 116), (504, "Head", 12, 116),
)  # fmt: skip
FIXTURES = tuple(
    FixtureInfo(number, 1, f"{profile} {number}", profile, "", footprint, (1, address))
    for number, profile, footprint, address in TUPPER
)
PROFILES = (
    ProfileInfo("LED Bar", frozenset(), ()),
    ProfileInfo("Blinder", frozenset(), ()),
    ProfileInfo("Smoke", frozenset(), (), "fog"),
    ProfileInfo("Par", frozenset(), (), "par"),
    ProfileInfo("Head", frozenset(), (), "spot"),
)
COLORS = colors.profile_colors([(p.name, p.category) for p in PROFILES])


def route(state: Any, packets: int = 0, **parts: Any) -> RouteView:
    given: dict[str, Any] = {
        "protocol": "ArtNet",
        "universe": 1,
        "enabled": state != "disabled",
        "state": state,
        "detail": "",
        "packets": packets,
        "address": "0.0.0",
        "destination": "unicast 127.0.0.1",
    }
    given.update(parts)
    return RouteView(**given)


def rig(**changes: Any) -> ShowModel:
    parts: dict[str, Any] = {
        "universes": (UniverseView(1, "Stage"), UniverseView(2, "Pixels")),
        "fixtures": FIXTURES,
        "profiles": PROFILES,
    }
    parts.update(changes)
    return show_model(**parts)


def on_f8(bridge: FakeBridge, routes: tuple[RouteView, ...] = ()) -> BuskApp:
    bridge.events += [
        ShowChanged(rig()),
        ProgrammerChanged(programmer(selection=((101, 1),))),
        RoutesChanged(routes or (route("ok", 10),)),
    ]
    return make_app(bridge, page=8)


def test_footprints_overlaps_and_the_used_count() -> None:
    prints = footprints(FIXTURES, 1, COLORS)
    assert [(p.fixture, p.start, p.end) for p in prints][-4:] == [
        (501, 92, 103), (502, 92, 103), (503, 116, 127), (504, 116, 127)
    ]  # fmt: skip
    assert used(prints) == 66
    assert overlaps(prints) == 2
    assert footprints(FIXTURES, 2, COLORS) == ()
    channels = owners(prints)
    assert [p.fixture for p in channels[93]] == [501, 502]
    assert channels[7] == ()  # channel 8: free


def block(*spans: tuple[int, int]) -> tuple[Footprint, ...]:
    """Footprints from ``(start, size)``: fixture 1, 2 … in order."""
    return tuple(Footprint(n, start, size, "") for n, (start, size) in enumerate(spans, 1))


def test_the_first_run_of_free_channels_that_fits() -> None:
    assert first_free((), 1) == 1
    assert first_free((), 512) == 1
    assert first_free((), 513) is None
    gaps = block((1, 8), (12, 4), (30, 2))  # free: 9–11, 16–29, 32–512
    assert first_free(gaps, 3) == 9
    assert first_free(gaps, 4) == 16
    assert first_free(gaps, 14) == 16
    assert first_free(gaps, 15) == 32
    assert first_free(gaps, 481) == 32  # to channel 512, whole
    assert first_free(gaps, 482) is None
    assert first_free(block((1, 512)), 1) is None  # a full universe
    assert first_free(block((1, 511)), 1) == 512
    assert first_free(block((2, 511)), 1) == 1


def test_how_many_free_channels_start_at_a_channel() -> None:
    gaps = block((10, 5), (20, 1))
    assert free_from(gaps, 1) == 9
    assert free_from(gaps, 15) == 5
    assert free_from(gaps, 21) == 492
    assert free_from(gaps, 512) == 1
    assert free_from(gaps, 10) == 0
    assert free_from((), 1) == 512


def test_what_a_place_clashes_with_leaves_out_the_fixture_itself() -> None:
    prints = block((10, 4), (14, 4), (12, 4))  # 1: 10–13, 2: 14–17, 3: 12–15
    assert clashes(prints, 1, 9) == ()
    assert clashes(prints, 1, 10) == (1,)
    assert clashes(prints, 13, 1) == (1, 3)
    assert clashes(prints, 13, 2) == (1, 2, 3)
    assert clashes(prints, 13, 2, own=3) == (1, 2)
    assert clashes(prints, 18, 4) == ()
    assert clashes(prints, 10, 4, own=1) == (3,)


def test_the_thru_runs_of_a_selection() -> None:
    numbers = (101, 102, 201, 202, 203, 301)
    assert runs({101, 102}, numbers) == [(101, 102)]
    assert runs({201}, numbers) == [(201, 201)]  # one number
    assert runs({102, 201}, numbers) == [(102, 201)]  # a gap in the numbers holds no fixture
    assert runs({201, 203}, numbers) == [(201, 201), (203, 203)]  # 202 is between, not selected
    assert runs({101, 102, 203, 301}, numbers) == [(101, 102), (203, 301)]
    assert runs(set(), numbers) == []
    assert runs({999}, numbers) == []  # not in the show
    assert runs({203, 201, 202}, reversed(numbers)) == [(201, 203)]  # a show in any order


def test_colours_by_category_else_by_profile_in_show_order() -> None:
    assert COLORS == {
        "LED Bar": colors.AMBER,  # no category: the first of the unset colours
        "Blinder": colors.CYAN,  # the second
        "Smoke": colors.MID,
        "Par": colors.AMBER,
        "Head": colors.CYAN,
    }
    keys = [key.plain for key in legend(rig(), COLORS)]
    assert keys[:5] == ["█ LED Bar", "█ Blinder", "█ fog", "█ par", "█ spot"]
    assert f"{OVERLAP} overlap" in keys


def test_what_the_hint_row_says_of_a_channel() -> None:
    prints = footprints(FIXTURES, 1, COLORS)
    channels = owners(prints)
    assert channel_text(1, 3, channels[2]) == "1.3 · fixture 101 · ch 3/7"
    assert channel_text(1, 94, channels[93]) == (
        "1.94 · overlap · fixture 501 · ch 3/12 · fixture 502 · ch 3/12"
    )
    assert channel_text(1, 200, channels[199]) == "1.200 · free"


def test_the_map_draws_starts_footprints_overlaps_and_free_channels() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        dmx_map = app.query_one(DmxMap)
        lines = dmx_map.lines(dmx_map.size.width)
        assert len(lines) == 8
        assert lines[0].plain[:13] == "   1 █▓▓▓▓▓▓·"
        assert lines[1].plain.startswith("  65 █▓▓▓▓▓▓▓█")  # 202, then the smoke's one channel
        assert lines[1].plain[5 + 27 : 5 + 39] == OVERLAP * 12  # 501 and 502, 92 to 103
        assert dmx_map.lines(60)[2].plain.startswith("  65 ")  # narrow: 32 to a row
        spans = {(s.start, str(s.style)) for s in lines[0].spans}
        assert (5, colors.AMBER) in spans  # the bar, no category: amber
        panels = [str(p.border_title) for p in app.query(".dmx-panel")]
        assert panels == ["DMX MAP · U1 Stage · 66/512 · 2 overlaps", "DMX MAP · U2 Pixels · 0/512"]
        universes = app.query_one(UniverseTable)
        assert column(universes, "used") == ["66/512", "0/512"]
        assert column(universes, "overlaps") == ["2", "0"]
        assert column(universes, "fixtures") == ["11", "0"]

    drive(app, body)


def test_hover_tells_the_channel_and_a_click_selects() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        dmx_map = app.query(DmxMap).first()
        await pilot.hover(dmx_map, offset=(5 + 2, 0))  # channel 3
        await pilot.pause()
        assert str(app.query_one(HintRow).render()) == "1.3 · fixture 101 · ch 3/7"
        await pilot.hover(app.query_one(UniverseTable))
        await pilot.pause()
        assert "type a command" in str(app.query_one(HintRow).render())
        await pilot.click(dmx_map, offset=(5 + 2, 0))  # 101, selected
        await pilot.click(dmx_map, offset=(5 + 2, 0), shift=True)
        await pilot.click(dmx_map, offset=(5 + 9, 1))  # 401 at 74
        await pilot.click(dmx_map, offset=(5 + 9, 1), shift=True)
        await pilot.click(dmx_map, offset=(5 + 30, 1))  # 94: 501 and 502
        await pilot.click(dmx_map, offset=(5 + 30, 1), shift=True)
        await pilot.click(dmx_map, offset=(5 + 50, 3))  # free: no line
        assert bridge.lines() == [
            "sel fixture 101",
            "sel - fixture 101",
            "sel fixture 401",
            "sel + fixture 401",
            "sel fixture 501, fixture 502",
            "sel + fixture 501, fixture 502",
        ]

    drive(app, body)


def test_route_cells_by_state() -> None:
    cells = [
        route_cells(route("ok"), True, 44.0),
        route_cells(route("ok", errors=3), False, None),
        route_cells(route("failed", detail="interface eth9 is down"), True, None),
        route_cells(route("disabled"), True, None),
        route_cells(route("ignored", detail="enttecOpen is not driven"), True, None),
        route_cells(route(None), True, None),
    ]
    assert [c["tx"].plain for c in cells] == ["● 44/s", "○ ", "● ", "○ ", "○ ", "○ "]
    assert [c["state"].plain for c in cells] == [
        "open",
        "open · 3 errors",
        "failed: interface eth9 is down",
        "disabled",
        "ignored: enttecOpen is not driven",
        "not running",
    ]
    assert str(cells[2]["state"].spans[0].style) == colors.RED
    assert (cells[0]["address"].plain, cells[0]["destination"].plain) == (
        "0.0.0",
        "unicast 127.0.0.1",
    )


def test_the_packet_rate_and_a_steady_light_once_sending_stops() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge, (route("ok", 100),))

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(PatchPage)
        table = app.query_one(RoutesTable)
        page.tick(now=1000.0)
        assert column(table, "tx") == ["● "]  # no rate before two ticks
        bridge.events.append(RoutesChanged((route("ok", 144),)))
        await settle(pilot, app)
        page.tick(now=1001.0)
        assert column(table, "tx")[0].endswith(" 44/s")  # 44 packets in the second
        page.tick(now=1002.0)  # nothing new: it stopped sending
        assert column(table, "tx") == ["● "]

    drive(app, body)


def test_the_pane_cursor_stops_on_each_footprint() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        items = app.current_page.items()
        assert [item.label for item in items[3:5]] == [
            "1.1 fixture 101 LED Bar 101",
            "1.33 fixture 201 Blinder 201",
        ]
        assert len(items) == 3 + 11  # two universes, [+ universe…], the footprints
        await pilot.press("tab", "down", "down", "down", "down", "enter")
        assert bridge.lines() == ["sel fixture 201"]
        assert app.query(DmxMap).first()._marked is not None

    drive(app, body)


# ------------------------------------------------------------- the universes


def strip_of(app: BuskApp) -> ButtonStrip:
    return app.query_one("#universe-edits", ButtonStrip)


def strip_words(app: BuskApp) -> list[str]:
    return [button.label.plain for button in strip_of(app).buttons]


async def tap(pilot: Pilot[int], app: BuskApp, label: str) -> None:
    """A click on ``[label]`` in the universes' strip."""
    strip = strip_of(app)
    for y, line in enumerate(strip.lines(strip.size.width)):
        x = line.plain.find(f"[{label}]")
        if x >= 0:
            await pilot.click(strip, offset=(x + 1, y))
            await pilot.pause()
            return
    raise AssertionError(f"no button [{label}]")


async def choose(pilot: Pilot[int], app: BuskApp, row: int) -> None:
    await pilot.click(app.query_one(UniverseTable), offset=(8, row + 1))
    await pilot.pause()


async def answer(pilot: Pilot[int], app: BuskApp, text: str) -> None:
    """Type ``text`` over what the open dialog's input holds, then Enter."""
    app.screen.query_one(Input).value = text
    await pilot.press("enter")
    await pilot.pause()


def test_a_click_chooses_a_universe_and_the_strip_follows_it() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        table = app.query_one(UniverseTable)
        assert strip_words(app) == ["[+ universe…]"]  # nothing chosen: [delete] is not armed
        assert table.chosen is None
        assert column(table, "marker") == ["", ""]
        await choose(pilot, app, 1)
        assert table.chosen == 1
        assert column(table, "marker") == ["", "▸"]
        assert strip_words(app) == [
            "[+ universe…]", "U2 Pixels", "[rename…]", "[number…]", "[delete]",
        ]  # fmt: skip
        await choose(pilot, app, 0)
        assert table.chosen == 0
        assert strip_words(app)[1] == "U1 Stage"
        assert bridge.lines() == []  # a stray click sends nothing

    drive(app, body)


def test_the_universes_go_by_number_as_list_universes_has_them() -> None:
    bridge = FakeBridge()
    universes = (UniverseView(7, "Roof"), UniverseView(1, "Stage"), UniverseView(2, "Pixels"))
    bridge.events.append(ShowChanged(rig(universes=universes)))
    app = make_app(bridge, page=8)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        assert column(app.query_one(UniverseTable), "number") == ["1", "2", "7"]
        await choose(pilot, app, 2)
        assert strip_words(app)[1] == "U7 Roof"
        panels = [str(p.border_title) for p in app.query(".dmx-panel")]
        assert [title.split(" · ")[1] for title in panels] == ["U1 Stage", "U2 Pixels", "U7 Roof"]

    drive(app, body)


def test_add_a_universe_through_its_form() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await tap(pilot, app, "+ universe…")
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert [field.value for field in dialog.inputs] == ["3", ""]  # the highest plus one
        assert "taken: 1–2" in str(dialog.query(".note").first().render())
        dialog.inputs[0].value = "2"
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is dialog  # refused: it stays
        assert str(dialog.error.render()) == "2 is taken"
        assert bridge.lines() == []
        dialog.inputs[0].value = "5"
        dialog.inputs[1].value = ' The "Roof" '
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, FormDialog)
        assert bridge.lines() == [r'''universe add 5 "The \"Roof\""''']
        await tap(pilot, app, "+ universe…")
        await pilot.press("enter")  # as it opens: the next number, and busk names it
        await pilot.pause()
        assert bridge.lines()[-1] == "universe add 3"
        await tap(pilot, app, "+ universe…")
        await pilot.press("escape")
        await pilot.pause()
        assert len(bridge.lines()) == 2

    drive(app, body)


def test_the_first_universe_of_a_show_is_number_one() -> None:
    bridge = FakeBridge()
    bridge.events.append(ShowChanged(show_model()))
    app = make_app(bridge, page=8)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await tap(pilot, app, "+ universe…")
        dialog = app.screen
        assert isinstance(dialog, FormDialog)
        assert dialog.inputs[0].value == "1"
        assert "taken" not in str(dialog.query(".note").first().render())

    drive(app, body)


def test_rename_a_universe_through_a_dialog() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await choose(pilot, app, 1)
        await tap(pilot, app, "rename…")
        dialog = app.screen
        assert isinstance(dialog, TextDialog)
        assert dialog.query_one(Input).value == "Pixels"
        await answer(pilot, app, "  ")
        assert app.screen is dialog
        assert str(dialog.error.render()) == "a name cannot be empty"
        await answer(pilot, app, "Pixels")  # the same: nothing to send
        assert bridge.lines() == []
        await tap(pilot, app, "rename…")
        await answer(pilot, app, "Roof")
        assert bridge.lines() == ['rename universe 2 "Roof"']

    drive(app, body)


def test_renumber_a_universe_and_the_choice_and_the_maps_follow() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        before = list(app.query(DmxMap))
        await choose(pilot, app, 1)
        await tap(pilot, app, "number…")
        dialog = app.screen
        assert isinstance(dialog, TextDialog)
        assert dialog.query_one(Input).value == "2"
        assert "taken: 1" in str(dialog.query_one(".note").render())
        await answer(pilot, app, "1")
        assert app.screen is dialog
        assert str(dialog.error.render()) == "1 is taken"
        await answer(pilot, app, "2")  # its own: nothing to send
        assert bridge.lines() == []
        await tap(pilot, app, "number…")
        await answer(pilot, app, "7")
        assert bridge.lines() == ["universe 2 number 7"]
        await settle(pilot, app)  # the line's done, before the show has it
        assert app.current_page.chosen == 7  # type: ignore[attr-defined]
        assert strip_words(app) == ["[+ universe…]"]
        universes = (UniverseView(1, "Stage"), UniverseView(7, "Pixels"))
        bridge.events.append(ShowChanged(rig(universes=universes)))
        await settle(pilot, app)
        assert strip_words(app)[1] == "U7 Pixels"
        assert app.query_one(UniverseTable).chosen == 1
        panels = [str(p.border_title) for p in app.query(".dmx-panel")]
        assert panels == ["DMX MAP · U1 Stage · 66/512 · 2 overlaps", "DMX MAP · U7 Pixels · 0/512"]
        after = list(app.query(DmxMap))
        assert [m.universe for m in after] == [1, 7]
        assert not set(after) & set(before)

    drive(app, body)


def test_the_choice_survives_the_show_moving_first_and_a_refused_number_keeps_it() -> None:
    bridge = FakeBridge(replies={"universe 2 number 7": Reply(False, "no")})
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await choose(pilot, app, 1)
        await tap(pilot, app, "number…")
        await answer(pilot, app, "7")
        await settle(pilot, app)
        assert app.current_page.chosen == 2  # type: ignore[attr-defined]
        bridge.replies.clear()
        bridge.auto_reply = False  # the show reads the new number before the line is done
        await tap(pilot, app, "number…")
        await answer(pilot, app, "8")
        universes = (UniverseView(1, "Stage"), UniverseView(8, "Pixels"))
        bridge.events.append(ShowChanged(rig(universes=universes)))
        await settle(pilot, app)
        assert app.current_page.chosen is None  # type: ignore[attr-defined]
        sent = bridge.sent[-1]
        bridge.events.append(CommandDone(sent.ticket, sent.line, "ui", True, (), 0.0, False))
        await settle(pilot, app)
        assert strip_words(app)[1] == "U8 Pixels"

    drive(app, body)


def test_a_universe_that_leaves_the_show_takes_the_choice_with_it() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await choose(pilot, app, 1)
        await tap(pilot, app, "rename…")
        bridge.events.append(ShowChanged(rig(universes=(UniverseView(1, "Stage"),))))
        await settle(pilot, app)
        await answer(pilot, app, "Roof")  # the dialog was open: nothing to rename now
        assert bridge.lines() == []
        assert strip_words(app) == ["[+ universe…]"]
        assert app.query_one(UniverseTable).chosen is None

    drive(app, body)


def test_delete_asks_busks_question_and_sends_on_yes(club: busk.OfflineShow) -> None:
    bridge = FakeBridge(show=club)
    bridge.events.append(ShowChanged(bridge_module.show_model(club.show)))
    app = make_app(bridge, page=8)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await choose(pilot, app, 0)
        await tap(pilot, app, "delete")
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)
        assert str(dialog.query_one(".question").render()) == (
            'Delete universe 1 "Stage"? 7 fixtures lose their patch and 1 route goes.'
        )
        await pilot.press("n")
        await pilot.pause()
        assert bridge.lines() == []
        log = app.query_one(LogView).entries
        assert ("info", "cancelled: delete universe 1 cascade") in log
        await tap(pilot, app, "delete")
        await pilot.press("y")
        await pilot.pause()
        assert bridge.lines() == ["delete universe 1 cascade"]

    drive(app, body)


def test_the_pane_cursor_stops_on_the_universes_and_their_strip_at_any_width() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def stops(pilot: Pilot[int], columns: int) -> None:
        await pilot.resize_terminal(columns, 48)
        await settle(pilot, app)
        labels = [item.label for item in app.current_page.items()]
        assert labels[:3] == ["universe 1 Stage", "universe 2 Pixels", "[+ universe…]"]
        await pilot.press("tab", "down", "enter")  # universe 2, chosen from the keys
        await pilot.pause()
        labels = [item.label for item in app.current_page.items()]
        assert labels[:7] == [
            "universe 1 Stage", "universe 2 Pixels", "[+ universe…]", "[rename…]", "[number…]",
            "delete universe 2 cascade", "1.1 fixture 101 LED Bar 101",
        ]  # fmt: skip
        assert app.cursor.current is not None
        assert app.cursor.current.label == "universe 2 Pixels"  # it stays on the row
        assert app.query_one(UniverseTable).chosen == 1
        strip = strip_of(app)
        assert strip.region.y > app.query_one(UniverseTable).region.y
        await pilot.press("down", "down")  # past [+ universe…], which the note does not stop
        assert strip._marked == 2
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, TextDialog)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("escape")  # out of the cursor
        assert not app.cursor.active

    async def body(pilot: Pilot[int]) -> None:
        await stops(pilot, 150)
        await stops(pilot, 99)
        assert bridge.lines() == []

    drive(app, body)


def test_a_name_with_markup_in_it_is_only_words() -> None:
    bridge = FakeBridge()
    name = "x[/]y [red]z"
    bridge.events.append(ShowChanged(rig(universes=(UniverseView(1, name),))))
    app = make_app(bridge, page=8)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await choose(pilot, app, 0)
        assert strip_words(app)[1] == f"U1 {name}"
        assert column(app.query_one(UniverseTable), "name") == [name]
        title = str(app.query_one(".dmx-panel").border_title)  # as markup: its brackets escaped
        assert r"x\[/]y \[red]z" in title
        await tap(pilot, app, "rename…")
        assert app.screen.query_one(Input).value == name

    drive(app, body)


def test_the_strip_wraps_inside_a_narrow_panel() -> None:
    bridge = FakeBridge()
    universes = (UniverseView(1, "A universe with a very long name for a strip to hold"),)
    bridge.events.append(ShowChanged(rig(universes=universes)))
    app = make_app(bridge, page=8)

    async def body(pilot: Pilot[int]) -> None:
        await pilot.resize_terminal(100, 40)
        await settle(pilot, app)
        await choose(pilot, app, 0)
        strip = strip_of(app)
        lines = strip.lines(strip.size.width)
        assert len(lines) > 1
        assert strip.size.height == len(lines)
        assert all(line.cell_len <= strip.size.width for line in lines)
        assert any(line.plain.startswith("U1 A universe") and "…" in line.plain for line in lines)
        await tap(pilot, app, "delete")  # a line down, and it still reaches its button
        assert bridge.lines() == ["delete universe 1 cascade"]

    drive(app, body)


# --------------------------------------------------------------- the place


def place_strip(app: BuskApp) -> ButtonStrip:
    return app.query_one("#place-strip", ButtonStrip)


def place_words(app: BuskApp) -> list[str]:
    return [button.label.plain for button in place_strip(app).buttons]


async def click_free(pilot: Pilot[int], app: BuskApp, channel: int = 10) -> DmxMap:
    """A click on ``channel`` of the first universe's map."""
    dmx_map = app.query(DmxMap).first()
    await pilot.click(dmx_map, offset=(5 + (channel - 1) % 64, (channel - 1) // 64))
    await settle(pilot, app)
    return dmx_map


async def tap_place(pilot: Pilot[int], app: BuskApp, label: str) -> None:
    strip = place_strip(app)
    for y, line in enumerate(strip.lines(strip.size.width)):
        x = line.plain.find(f"[{label}]")
        if x >= 0:
            await pilot.click(strip, offset=(x + 1, y))
            await settle(pilot, app)
            return
    raise AssertionError(f"no button [{label}]")


def place_cells(dmx_map: DmxMap, first: int, last: int) -> list[tuple[str, str]]:
    """Channels ``first`` to ``last`` of a map's first line: each glyph and style."""
    line = dmx_map.lines(dmx_map.size.width)[0]
    cells = []
    for channel in range(first, last + 1):
        column = 5 + channel - 1
        styles = [str(s.style) for s in line.spans if s.start <= column < s.end]
        cells.append((line.plain[column], styles[-1]))
    return cells


def test_a_place_draws_what_it_takes_and_red_where_it_would_overlap() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        dmx_map = app.query(DmxMap).first()
        dmx_map.place(6, 4)  # 6 and 7 are 101's, 8 and 9 free
        assert place_cells(dmx_map, 5, 10) == [
            ("▓", colors.AMBER),
            ("░", colors.RED),
            ("░", colors.RED),
            ("░", colors.CYAN),
            ("░", colors.CYAN),
            ("·", colors.TRACK),
        ]
        dmx_map.place(6, 4, 101)  # moving 101 itself, nothing to overlap
        assert place_cells(dmx_map, 6, 7) == [("░", colors.CYAN), ("░", colors.CYAN)]
        dmx_map.place(None)
        assert place_cells(dmx_map, 6, 8) == [
            ("▓", colors.AMBER),
            ("▓", colors.AMBER),
            ("·", colors.TRACK),
        ]

    drive(app, body)


def test_a_click_on_a_free_channel_arms_a_place_and_sends_nothing() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        assert place_words(app) == [NO_PLACE]
        dmx_map = await click_free(pilot, app)
        assert bridge.lines() == []
        assert app.query_one(PatchPage).place == (1, 10)
        assert place_words(app) == [
            "place 1.10 · 23 free from here ·",
            "[patch 101 here]",
            "[add fixture here…]",
        ]
        assert place_cells(dmx_map, 10, 16) == [("░", colors.CYAN)] * 7  # 101 takes seven
        assert place_cells(dmx_map, 17, 17) == [("·", colors.TRACK)]

    drive(app, body)


def test_the_strip_holds_its_row_so_the_map_stays_under_the_mouse() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        before = app.query(DmxMap).first().region.y
        dmx_map = await click_free(pilot, app)
        assert dmx_map.region.y == before

    drive(app, body)


def test_a_second_free_channel_moves_the_place() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await click_free(pilot, app, 10)
        dmx_map = await click_free(pilot, app, 20)
        assert place_words(app)[0] == "place 1.20 · 13 free from here ·"
        assert place_cells(dmx_map, 10, 10) == [("·", colors.TRACK)]

    drive(app, body)


def test_patch_here_sends_one_line_and_the_map_changing_clears_the_place() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        dmx_map = await click_free(pilot, app)
        await tap_place(pilot, app, "patch 101 here")
        assert bridge.lines() == ["fixture 101 patch 1.10"]
        assert app.query_one(PatchPage).place == (1, 10)  # until the show says so

        moved = FixtureInfo(101, 1, "LED Bar 101", "LED Bar", "", 7, (1, 10))
        bridge.events.append(ShowChanged(rig(fixtures=(moved, *FIXTURES[1:]))))
        await settle(pilot, app)
        assert app.query_one(PatchPage).place is None
        assert place_words(app) == [NO_PLACE]
        assert place_cells(dmx_map, 10, 11) == [("█", colors.AMBER), ("▓", colors.AMBER)]

    drive(app, body)


def test_the_map_of_another_universe_changing_leaves_the_place() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await click_free(pilot, app)
        added = FixtureInfo(601, 1, "Par 601", "Par", "", 6, (2, 1))
        bridge.events.append(ShowChanged(rig(fixtures=(*FIXTURES, added))))
        await settle(pilot, app)
        assert app.query_one(PatchPage).place == (1, 10)

    drive(app, body)


def test_a_universe_that_leaves_the_show_takes_its_place_with_it() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        maps = list(app.query(DmxMap))
        maps[1].scroll_visible(animate=False)
        await pilot.pause()
        await pilot.click(maps[1], offset=(5, 0))
        await settle(pilot, app)
        assert app.query_one(PatchPage).place == (2, 1)
        bridge.events.append(ShowChanged(rig(universes=(UniverseView(1, "Stage"),))))
        await settle(pilot, app)
        assert app.query_one(PatchPage).place is None
        assert place_words(app) == [NO_PLACE]

    drive(app, body)


def test_a_click_on_a_fixture_clears_the_place_and_selects_it() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        dmx_map = await click_free(pilot, app)
        await pilot.click(dmx_map, offset=(5 + 2, 0))
        await settle(pilot, app)
        assert app.query_one(PatchPage).place is None
        assert place_words(app) == [NO_PLACE]
        assert place_cells(dmx_map, 10, 10) == [("·", colors.TRACK)]
        assert bridge.lines() == ["sel fixture 101"]

    drive(app, body)


def test_no_selection_and_two_selected_say_so_and_the_offer_follows_the_selection() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def select(pilot: Pilot[int], *selection: tuple[int, int]) -> None:
        bridge.events.append(ProgrammerChanged(programmer(selection=selection)))
        await settle(pilot, app)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        dmx_map = await click_free(pilot, app)
        words = "select one fixture to patch it here ·"
        await select(pilot)
        assert place_words(app)[1:] == [words, "[add fixture here…]"]
        assert place_cells(dmx_map, 10, 11) == [("░", colors.CYAN), ("·", colors.TRACK)]
        await select(pilot, (101, 1), (201, 1))
        assert place_words(app)[1:] == [words, "[add fixture here…]"]
        await select(pilot, (201, 1), (201, 2), (201, 3))  # one fixture, three elements
        assert place_words(app)[1] == "[patch 201 here]"
        assert place_cells(dmx_map, 10, 18) == [*[("░", colors.CYAN)] * 8, ("·", colors.TRACK)]
        assert bridge.lines() == []

    drive(app, body)


def test_a_fixture_that_would_go_past_512_says_so_instead() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        dmx_map = app.query(DmxMap).first()
        await pilot.click(dmx_map, offset=(5 + 60, 7))  # 509: four are left, 101 takes seven
        await settle(pilot, app)
        assert place_words(app) == [
            "place 1.509 · 4 free from here ·",
            "101 would go past channel 512 ·",
            "[add fixture here…]",
        ]
        await pilot.click(dmx_map, offset=(5 + 57, 7))  # 506: seven to 512, whole
        await settle(pilot, app)
        assert place_words(app)[1] == "[patch 101 here]"

    drive(app, body)


def test_add_fixture_here_opens_f3s_form_at_that_place_and_the_count_keeps_it() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await click_free(pilot, app)
        await tap_place(pilot, app, "add fixture here…")
        assert app.page == 3
        page = app.query_one(FixturesPage)
        assert page.editing
        assert page.panel.adding
        form = page.panel.form
        assert form.patching.at == (1, 10)
        assert bridge.lines() == []
        form.change_count(1)
        await pilot.pause()
        assert form.patching.at == (1, 10)
        form.step(1)
        await pilot.pause()
        assert form.patching.at == (1, 10)

    drive(app, body)


def test_a_show_with_no_universe_has_no_strip_for_a_place() -> None:
    bridge = FakeBridge()
    bridge.events.append(ShowChanged(show_model()))
    app = make_app(bridge, page=8)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        assert not place_strip(app).display

    drive(app, body)


def test_the_pane_cursor_stops_on_what_a_place_offers_and_takes_it() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(PatchPage)
        before = [item.label for item in page.items()]
        await click_free(pilot, app)
        labels = [item.label for item in page.items()]
        offered = ["fixture 101 patch 1.10", "[add fixture here…]"]
        assert labels == [*before[:3], *offered, *before[3:]]
        await pilot.press("tab", *["down"] * 3, "enter")
        await settle(pilot, app)
        assert bridge.lines() == ["fixture 101 patch 1.10"]

    drive(app, body)


def test_universes_and_routes_go_one_under_the_other_below_100_columns() -> None:
    bridge = FakeBridge()
    app = on_f8(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        universes, routes = app.query_one("#universes-panel"), app.query_one("#routes-panel")
        assert routes.region.x > universes.region.x
        await pilot.resize_terminal(99, 40)
        await pilot.pause()
        assert routes.region.y > universes.region.y

    drive(app, body)


def test_nothing_to_show() -> None:
    bridge = FakeBridge()
    bridge.events += [ShowChanged(show_model()), RoutesChanged(())]
    app = make_app(bridge, page=8)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        assert "no universes" in app.query_one(UniverseTable).render().plain
        assert "no routes" in app.query_one(RoutesTable).render().plain
        assert len(app.query(DmxMap)) == 0

    drive(app, body)
