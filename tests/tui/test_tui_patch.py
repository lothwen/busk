"""F8 Patch (spec §8.8, plan Phase 4): footprints, overlaps (the TupperDMX
show's double-patched heads give two) and the used count; the DMX map's
glyphs and colours by category, or by profile without one; the hover text
and the click lines; the route states, their lights and packet rates.
Headless, with a fake bridge."""

from __future__ import annotations

from typing import Any

from textual.pilot import Pilot
from tui_fakes import FakeBridge, column, drive, make_app, programmer, settle, show_model

from busk_tui import colors
from busk_tui.model import (
    FixtureInfo,
    ProfileInfo,
    ProgrammerChanged,
    RoutesChanged,
    RouteView,
    ShowChanged,
    ShowModel,
    UniverseView,
)
from busk_tui.pages.patch import PatchPage, RoutesTable, UniverseTable, legend, route_cells
from busk_tui.shell import BuskApp
from busk_tui.widgets.dmxmap import (
    OVERLAP,
    DmxMap,
    channel_text,
    footprints,
    overlaps,
    owners,
    used,
)
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
        await pilot.click(dmx_map, offset=(5 + 50, 3))  # free: nothing
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
        assert [item.label for item in items[:2]] == [
            "1.1 fixture 101 LED Bar 101",
            "1.33 fixture 201 Blinder 201",
        ]
        assert len(items) == 11
        await pilot.press("tab", "down", "enter")
        assert bridge.lines() == ["sel fixture 201"]
        assert app.query(DmxMap).first()._marked is not None

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
