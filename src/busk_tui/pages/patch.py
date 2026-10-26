"""F8 Patch (spec §8.8, plan Phase 4): the universes, the output routes and
their state, and a DMX map per universe.

UNIVERSES: number, name, how many fixtures are patched in it, how many of
its channels they take (``188/512``) and how many pairs of them overlap
(red).

ROUTES: the universe, protocol, address and destination as ``route add``
takes them, the light (green while open, blinking while it sends, red when
it fails, grey when disabled or while nothing runs the output) with the
packets sent per second, and the state with busk's word for why (``failed:
…``, the send errors).

A DMX MAP per universe (:mod:`busk_tui.widgets.dmxmap`), and a legend of
the fixture types it shows. A click on a fixture's channels selects it
(``sel fixture 101``; both fixtures of an overlap); a Shift-click adds it
to the selection or takes it out. The pane cursor stops on each footprint.
"""

from __future__ import annotations

import time
from typing import Final

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical

from busk_tui import colors, commands
from busk_tui.model import FixtureInfo, ProfileInfo, RouteView, ShowModel
from busk_tui.nav import Item, Stop
from busk_tui.pages.base import Page, Part, View
from busk_tui.widgets.controls import RunLine
from busk_tui.widgets.dmxmap import OVERLAP, DmxMap, Footprint, footprints, overlaps, used
from busk_tui.widgets.frame import RouteLights, route_light
from busk_tui.widgets.legend import Legend
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.rows import Cells, Column, RowTable, cell

NARROW: Final = 100
"""Below this many columns UNIVERSES and ROUTES go one under the other."""

RATE_S: Final = 1.0
"""How often the packet rates are worked out again."""

NO_UNIVERSES: Final = 'no universes · universe add 1 "Stage"'
NO_ROUTES: Final = "no routes · route add 1 sacn 1"


class UniverseTable(RowTable):
    COLUMNS = (
        Column("number", "U", 3, right=True),
        Column("name", "name", 8, flex=True),
        Column("fixtures", "fixtures", 8, right=True),
        Column("used", "used", 7, right=True),
        Column("overlaps", "overlaps", 8, right=True),
    )


class RoutesTable(RowTable):
    COLUMNS = (
        Column("universe", "U", 3, right=True),
        Column("protocol", "proto", 7),
        Column("address", "address", 8),
        Column("destination", "destination", 12, flex=True, drop=2),
        Column("tx", "tx", 8),
        Column("state", "state", 10, flex=True, drop=1),
    )


def legend_colors(show: ShowModel) -> dict[str, str]:
    """Each profile's colour (:func:`busk_tui.colors.profile_colors`)."""
    return colors.profile_colors([(p.name, p.category) for p in show.profiles])


def legend(show: ShowModel, profile_colors: dict[str, str]) -> list[Text]:
    """The types the maps show (a category, or a profile without one), then
    what the glyphs mean."""
    profiles = {profile.name: profile for profile in show.profiles}
    seen: dict[str, str] = {}
    for fixture in show.fixtures:
        if fixture.patch is None:
            continue
        info: ProfileInfo | None = profiles.get(fixture.profile)
        name = info.category if info is not None and info.category else fixture.profile
        seen.setdefault(name, profile_colors.get(fixture.profile, colors.MID))
    keys = [Text.assemble(("█ ", color), (name, colors.DIM)) for name, color in seen.items()]
    keys += [
        Text.assemble(("█ ", colors.MID), ("start", colors.DIM)),
        Text.assemble(("▓ ", colors.MID), ("footprint", colors.DIM)),
        Text.assemble((f"{OVERLAP} ", colors.RED), ("overlap", colors.DIM)),
        Text.assemble(("· ", colors.TRACK), ("free", colors.DIM)),
        Text("hover a channel for its fixture; a click selects it", style=colors.DIM),
    ]
    return keys


def universe_cells(number: int, name: str, fixtures: int, prints: tuple[Footprint, ...]) -> Cells:
    pairs = overlaps(prints)
    return {
        "number": cell(str(number), colors.CYAN),
        "name": cell(name, colors.FG),
        "fixtures": cell(str(fixtures), colors.MID),
        "used": cell(f"{used(prints)}/512", colors.MID),
        "overlaps": cell(str(pairs), colors.RED) if pairs else cell("0", colors.DIM),
    }


def route_cells(route: RouteView, on: bool, rate: float | None) -> Cells:
    shown = "" if not rate else f"{round(rate)}/s"
    return {
        "universe": cell(str(route.universe), colors.CYAN),
        "protocol": cell(route.protocol, colors.FG),
        "address": cell(route.address, colors.FG),
        "destination": cell(route.destination, colors.MID),
        "tx": route_light(route, on, shown),
        "state": state_text(route),
    }


def state_text(route: RouteView) -> Text:
    """``open``, ``open · 3 errors``, ``failed: <why>``, ``disabled``,
    ``ignored: <why>``, or ``not running`` while nothing runs the output."""
    if route.state is None:
        return cell("disabled" if not route.enabled else "not running", colors.DIM)
    if route.state == "ok":
        text = cell("open", colors.GREEN)
        if route.errors:
            text.append(f" · {route.errors} errors", style=colors.AMBER)
        return text
    if route.state == "failed":
        return cell(f"failed: {route.detail}" if route.detail else "failed", colors.RED)
    words = route.state + (f": {route.detail}" if route.detail else "")
    return cell(words, colors.DIM)


class PatchPage(Page):
    """F8 (see the module docs)."""

    DEFAULT_CSS = f"""
    PatchPage #patch-row {{ height: auto; }}
    PatchPage #patch-row > Panel {{ width: 1fr; }}
    PatchPage #patch-row.stacked {{ layout: vertical; }}
    PatchPage #patch-row.stacked > Panel {{ width: 100%; }}
    PatchPage #dmx-maps {{ height: auto; }}
    PatchPage #patch-legend {{ margin-top: 1; color: {colors.DIM}; }}
    """

    def __init__(self, number: int, title: str) -> None:
        super().__init__(number, title)
        self.universes = UniverseTable(Text(NO_UNIVERSES, style=colors.DIM), id="universe-table")
        self.routes = RoutesTable(Text(NO_ROUTES, style=colors.DIM), id="route-table")
        self.maps_box = Vertical(id="dmx-maps")
        self.legend = Legend(id="patch-legend")
        self.maps: dict[int, tuple[Panel, DmxMap]] = {}
        self.shown_routes: tuple[RouteView, ...] = ()
        self._view = View()
        self._lights = RouteLights()
        self._on: tuple[bool, ...] = ()
        self._rates: tuple[float | None, ...] = ()
        self._mark: tuple[float, tuple[int, ...]] | None = None  # when, and each route's packets

    def compose(self) -> ComposeResult:
        with Horizontal(id="patch-row"):
            yield Panel("universes", self.universes, id="universes-panel")
            yield Panel("routes", self.routes, id="routes-panel")
        yield self.maps_box
        yield self.legend

    def on_mount(self) -> None:
        self.set_interval(RATE_S, self.tick)

    def on_resize(self, event: events.Resize) -> None:
        self.query_one("#patch-row").set_class(event.size.width < NARROW, "stacked")

    def update_view(self, view: View, changed: frozenset[Part]) -> None:
        self._view = view
        if "show" in changed:
            self._draw_patch()
        if changed & {"show", "routes"}:
            self.shown_routes = view.routes
            self._on = self._lights.update(view.routes, time.monotonic())
            self._draw_routes()

    # ---------------------------------------------------------- routes

    def tick(self, now: float | None = None) -> None:
        """Each second: the packets each route sent per second since the last
        tick, and the lights of routes that stopped sending."""
        if not self.is_attached or not self.display:
            self._mark = None
            return
        now = time.monotonic() if now is None else now
        packets = tuple(route.packets for route in self.shown_routes)
        mark = self._mark
        if mark is not None and len(mark[1]) == len(packets) and now > mark[0]:
            self._rates = tuple(
                max(0, count - before) / (now - mark[0])
                for count, before in zip(packets, mark[1], strict=True)
            )
        else:
            self._rates = ()
        self._mark = (now, packets)
        self._on = self._lights.update(self.shown_routes, now)
        self._draw_routes()

    def _draw_routes(self) -> None:
        rates = self._rates if len(self._rates) == len(self.shown_routes) else ()
        self.routes.show(
            [
                route_cells(route, on, rates[index] if rates else None)
                for index, (route, on) in enumerate(zip(self.shown_routes, self._on, strict=False))
            ]
        )

    # ----------------------------------------------------------- patch

    def _draw_patch(self) -> None:
        show = self._view.show
        if show is None:
            return
        profile_colors = legend_colors(show)
        prints = {
            universe.number: footprints(show.fixtures, universe.number, profile_colors)
            for universe in show.universes
        }
        counts = {
            universe.number: sum(
                1 for f in show.fixtures if f.patch is not None and f.patch[0] == universe.number
            )
            for universe in show.universes
        }
        self.universes.show(
            [
                universe_cells(u.number, u.name, counts[u.number], prints[u.number])
                for u in show.universes
            ]
        )
        numbers = tuple(universe.number for universe in show.universes)
        if numbers != tuple(self.maps):
            self.maps_box.remove_children()
            self.maps = {}
            for number in numbers:
                dmx_map = DmxMap(number)
                self.maps[number] = (Panel("dmx map", dmx_map, classes="dmx-panel"), dmx_map)
            self.maps_box.mount_all([panel for panel, _ in self.maps.values()])
        for universe in show.universes:
            panel, dmx_map = self.maps[universe.number]
            these = prints[universe.number]
            meta = f"U{universe.number} {universe.name} · {used(these)}/512"
            pairs = overlaps(these)
            if pairs:
                meta += f" · {pairs} overlap{'s' if pairs > 1 else ''}"
            panel.set_title("dmx map", meta)
            dmx_map.show(these)
        self.legend.show(legend(show, profile_colors))

    # ----------------------------------------------------------- clicks

    def on_dmx_map_clicked(self, message: DmxMap.Clicked) -> None:
        message.stop()
        programmer = self._view.programmer
        selected = set() if programmer is None else {n for n, _ in programmer.selection}
        fixtures = message.fixtures
        if len(fixtures) > 1:
            line = commands.sel_fixtures(fixtures, add=message.shift)
        elif message.shift:
            inside = fixtures[0] in selected
            line = commands.sel_fixture(fixtures[0], add=not inside, remove=inside)
        else:
            line = commands.sel_fixture(fixtures[0])
        self.post_message(RunLine(line))

    # ----------------------------------------------------- pane cursor

    def stops(self) -> list[Stop]:
        show = self._view.show
        names = {} if show is None else {f.number: f for f in show.fixtures}
        stops: list[Stop] = []
        for universe, (_, dmx_map) in self.maps.items():
            for index, print_ in enumerate(dmx_map.prints):
                fixture: FixtureInfo | None = names.get(print_.fixture)
                name = "" if fixture is None else f" {fixture.name}"
                label = f"{universe}.{print_.start} fixture {print_.fixture}{name}"
                line = commands.sel_fixture(print_.fixture).text
                stops.append(Stop(Item(label.rstrip(), line=line), dmx_map, index))
        return stops
