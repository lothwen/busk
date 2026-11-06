"""F8 Patch (spec §8.8, plan Phase 4): the universes, the output routes and
their state, and a DMX map per universe.

UNIVERSES, by number: its number, name, how many fixtures are patched in it,
how many of its channels they take (``188/512``) and how many pairs of them
overlap (red). A click chooses a universe (``▸``); nothing is chosen at
first. The strip under the table holds ``[+ universe…]``, a form for ``universe
add``, and for the chosen universe ``[rename…]`` and ``[number…]``, each a
dialog and then one line, and ``[delete]``: ``delete universe 2 cascade``,
after busk's question, which says what goes.

ROUTES: the universe, protocol, address and destination as ``route add``
takes them, the light (green while open, blinking while it sends, red when
it fails, grey when disabled or while nothing runs the output) with the
packets sent per second, and the state with busk's word for why (``failed:
…``, the send errors).

A DMX MAP per universe (:mod:`busk_tui.widgets.dmxmap`), and a legend of
the fixture types it shows. A click on a fixture's channels selects it
(``sel fixture 101``; both fixtures of an overlap); a Shift-click adds it
to the selection or takes it out.

A click on a free channel arms a place and sends nothing. The strip above the
maps then offers ``[patch 102 here]``, for exactly one selected fixture, and
``[add fixture here…]``, which opens F3's new fixture form there, and the map
draws what the fixture would take. A click on a fixture, or that universe's
map changing, clears the place.

The pane cursor stops on each universe and its strip, on what the place offers,
then on each footprint.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import partial
from typing import Final

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message

from busk_tui import colors, commands
from busk_tui.commands import Line
from busk_tui.formats import numbers_text
from busk_tui.model import FixtureInfo, ProfileInfo, RouteView, ShowModel, UniverseView
from busk_tui.nav import Item, Stop
from busk_tui.pages.base import Page, Part, View
from busk_tui.widgets.controls import ButtonStrip, RunLine, StripButton, button_label
from busk_tui.widgets.dialogs import (
    FormDialog,
    TextDialog,
    check_name,
    check_number,
    next_number,
)
from busk_tui.widgets.dmxmap import (
    CHANNELS,
    OVERLAP,
    DmxMap,
    Footprint,
    footprints,
    free_from,
    overlaps,
    used,
)
from busk_tui.widgets.frame import RouteLights, route_light
from busk_tui.widgets.legend import Legend
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.quick import strip_stops
from busk_tui.widgets.rows import Cells, Column, RowTable, cell

NARROW: Final = 100
"""Below this many columns UNIVERSES and ROUTES go one under the other."""

RATE_S: Final = 1.0
"""How often the packet rates are worked out again."""

NO_UNIVERSES: Final = 'no universes · universe add 1 "Stage"'
NO_ROUTES: Final = "no routes · route add 1 sacn 1"
NO_PLACE: Final = "click a free channel to place a fixture there"


class UniverseTable(RowTable):
    COLUMNS = (
        Column("marker", "", 1),
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


def universe_cells(
    number: int, name: str, fixtures: int, prints: tuple[Footprint, ...], chosen: bool
) -> Cells:
    pairs = overlaps(prints)
    return {
        "marker": cell("▸" if chosen else "", colors.CYAN),
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
    PatchPage #place-strip {{ margin-left: 1; }}
    PatchPage #dmx-maps {{ height: auto; }}
    PatchPage #patch-legend {{ margin-top: 1; color: {colors.DIM}; }}
    """

    class AddHere(Message):
        """``[add fixture here…]``: F3's new fixture form, at this place."""

        def __init__(self, universe: int, address: int) -> None:
            super().__init__()
            self.universe = universe
            self.address = address

    def __init__(self, number: int, title: str) -> None:
        super().__init__(number, title)
        self.universes = UniverseTable(Text(NO_UNIVERSES, style=colors.DIM), id="universe-table")
        self.universe_edits = ButtonStrip(id="universe-edits")
        self.routes = RoutesTable(Text(NO_ROUTES, style=colors.DIM), id="route-table")
        self.place_strip = ButtonStrip(id="place-strip")
        self.place_strip.display = False
        self.maps_box = Vertical(id="dmx-maps")
        self.legend = Legend(id="patch-legend")
        self.maps: dict[int, tuple[Panel, DmxMap]] = {}
        self.shown_universes: tuple[UniverseView, ...] = ()  # by number
        self.chosen: int | None = None  # the universe clicked last, by number
        self.place: tuple[int, int] | None = None  # the free channel clicked last
        self.shown_routes: tuple[RouteView, ...] = ()
        self._view = View()
        self._lights = RouteLights()
        self._on: tuple[bool, ...] = ()
        self._rates: tuple[float | None, ...] = ()
        self._mark: tuple[float, tuple[int, ...]] | None = None  # when, and each route's packets

    def compose(self) -> ComposeResult:
        with Horizontal(id="patch-row"):
            yield Panel("universes", self.universes, self.universe_edits, id="universes-panel")
            yield Panel("routes", self.routes, id="routes-panel")
        yield self.place_strip
        yield self.maps_box
        yield self.legend

    def on_mount(self) -> None:
        self.set_interval(RATE_S, self.tick)

    def on_resize(self, event: events.Resize) -> None:
        self.query_one("#patch-row").set_class(event.size.width < NARROW, "stacked")

    def update_view(self, view: View, changed: frozenset[Part]) -> None:
        self._view = view
        if "show" in changed:
            universes = () if view.show is None else view.show.universes
            self.shown_universes = tuple(sorted(universes, key=lambda u: u.number))
            if self.chosen_universe() is None:
                self.chosen = None
            self._draw_patch()
        if changed & {"show", "routes"}:
            self.shown_routes = view.routes
            self._on = self._lights.update(view.routes, time.monotonic())
            self._draw_routes()
        if "programmer" in changed:
            self._draw_place()

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
        shown = self.shown_universes
        self.universes.show(
            [
                universe_cells(
                    u.number, u.name, counts[u.number], prints[u.number], u.number == self.chosen
                )
                for u in shown
            ],
            chosen=next((row for row, u in enumerate(shown) if u.number == self.chosen), None),
        )
        self._draw_universe_edits()
        numbers = tuple(universe.number for universe in shown)
        if numbers != tuple(self.maps):
            self.maps_box.remove_children()
            self.maps = {}
            for number in numbers:
                dmx_map = DmxMap(number)
                self.maps[number] = (Panel("dmx map", dmx_map, classes="dmx-panel"), dmx_map)
            self.maps_box.mount_all([panel for panel, _ in self.maps.values()])
        for universe in shown:
            panel, dmx_map = self.maps[universe.number]
            these = prints[universe.number]
            meta = f"U{universe.number} {universe.name} · {used(these)}/512"
            pairs = overlaps(these)
            if pairs:
                meta += f" · {pairs} overlap{'s' if pairs > 1 else ''}"
            panel.set_title("dmx map", meta)
            if these != dmx_map.prints and self.place and self.place[0] == universe.number:
                self.place = None
            dmx_map.show(these)
        if self.place is not None and self.place[0] not in self.maps:
            self.place = None
        self._draw_place()
        self.legend.show(legend(show, profile_colors))

    def _draw_universe_edits(self) -> None:
        def ask(label: str, action: Callable[[], None]) -> StripButton:
            return StripButton(button_label(label, colors.MID), Line(""), action=action)

        buttons = [ask("+ universe…", self.ask_add)]
        universe = self.chosen_universe()
        if universe is not None:
            name = Text(f"U{universe.number} {universe.name}", style=colors.FG)
            delete = commands.delete_universe(universe.number)
            buttons += [
                StripButton(name, Line(""), note=True),
                ask("rename…", self.ask_name),
                ask("number…", self.ask_number),
                StripButton(button_label("delete", colors.RED), delete),
            ]
        self.universe_edits.show(buttons)

    # ---------------------------------------------------------- the place

    def selected(self) -> frozenset[int]:
        programmer = self._view.programmer
        return frozenset(() if programmer is None else (n for n, _ in programmer.selection))

    def placing(self) -> FixtureInfo | None:
        """What a place would patch: the fixture selected, if it is the only one."""
        selected, show = self.selected(), self._view.show
        return show.fixture(min(selected)) if len(selected) == 1 and show is not None else None

    def _draw_place(self) -> None:
        """The strip above the maps, and what the place takes on its map."""
        self.place_strip.display = bool(self.maps)
        fixture = self.placing()
        for universe, (_, dmx_map) in self.maps.items():
            if self.place is None or self.place[0] != universe:
                dmx_map.place(None)
            elif fixture is None:
                dmx_map.place(self.place[1])
            else:
                dmx_map.place(self.place[1], fixture.footprint, fixture.number)
        self.place_strip.show(self._place_buttons(fixture))

    def _place_buttons(self, fixture: FixtureInfo | None) -> list[StripButton]:
        def note(words: str) -> StripButton:
            return StripButton(Text(words, style=colors.DIM), Line(""), note=True)

        if self.place is None:
            return [note(NO_PLACE)]
        universe, channel = self.place
        free = free_from(self.maps[universe][1].prints, channel)
        buttons = [note(f"place {universe}.{channel} · {free} free from here ·")]
        if fixture is None:
            buttons.append(note("select one fixture to patch it here ·"))
        elif channel + fixture.footprint - 1 > CHANNELS:
            buttons.append(note(f"{fixture.number} would go past channel {CHANNELS} ·"))
        else:
            label = button_label(f"patch {fixture.number} here", colors.GREEN)
            buttons.append(StripButton(label, commands.patch_fixture(fixture.number, self.place)))
        label = button_label("add fixture here…", colors.MID)
        buttons.append(StripButton(label, Line(""), action=self.add_here))
        return buttons

    def add_here(self) -> None:
        if self.place is not None:
            self.post_message(self.AddHere(*self.place))

    # ------------------------------------------------------- the universes

    def chosen_universe(self) -> UniverseView | None:
        return next((u for u in self.shown_universes if u.number == self.chosen), None)

    def choose(self, number: int) -> None:
        """The universe the strip acts on."""
        self.chosen = number
        self._draw_patch()

    def _taken(self) -> frozenset[int]:
        return frozenset(universe.number for universe in self.shown_universes)

    def ask_add(self) -> None:
        """``[+ universe…]``: ``universe add 2 "Balcony"``. An empty name
        leaves naming it to busk."""
        taken = self._taken()
        check = check_number(taken, None)

        def given(values: tuple[str, ...] | None) -> None:
            if values is not None:
                number, name = values
                line = commands.universe_add(int(number.strip()), name.strip() or None)
                self.post_message(RunLine(line))

        note = "no name: busk names it Universe <number>"
        if taken:
            note = f"taken: {numbers_text(sorted(taken))}\n{note}"
        fields = (("number", str(next_number(taken))), ("name", ""))
        dialog = FormDialog("NEW UNIVERSE", fields, lambda values: check(values[0]), note)
        self.app.push_screen(dialog, given)

    def ask_name(self) -> None:
        """``[rename…]``: ``rename universe 2 "Roof"``."""
        universe = self.chosen_universe()
        if universe is None:
            return

        def given(text: str | None) -> None:
            if text is None or self.chosen != universe.number:
                return
            name = text.strip()
            if name != universe.name:
                self.post_message(RunLine(commands.rename_universe(universe.number, name)))

        title = f"RENAME · universe {universe.number}"
        self.app.push_screen(TextDialog(title, universe.name, check_name(True)), given)

    def ask_number(self) -> None:
        """``[number…]``: ``universe 2 number 7``. The choice follows it."""
        universe = self.chosen_universe()
        if universe is None:
            return
        taken = self._taken()
        others = sorted(taken - {universe.number})

        def given(text: str | None) -> None:
            if text is None or self.chosen != universe.number:
                return
            number = int(text.strip())
            if number == universe.number:
                return

            def renumbered(ok: bool) -> None:
                if ok and self.chosen in (universe.number, None):
                    self.choose(number)

            line = commands.renumber_universe(universe.number, number)
            self.post_message(RunLine(line, done=renumbered))

        title = f"NUMBER · universe {universe.number}"
        note = f"taken: {numbers_text(others)}" if others else ""
        check = check_number(taken, universe.number)
        self.app.push_screen(TextDialog(title, str(universe.number), check, note), given)

    # ----------------------------------------------------------- clicks

    def on_row_table_clicked(self, message: RowTable.Clicked) -> None:
        message.stop()
        if message.table is self.universes and message.row < len(self.shown_universes):
            self.choose(self.shown_universes[message.row].number)

    def on_dmx_map_place_clicked(self, message: DmxMap.PlaceClicked) -> None:
        message.stop()
        self.place = (message.universe, message.channel)
        self._draw_place()

    def on_dmx_map_clicked(self, message: DmxMap.Clicked) -> None:
        message.stop()
        self.place = None
        self._draw_place()
        selected = self.selected()
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
        self.universes.spots = [(row, None) for row in range(len(self.shown_universes))]
        for row, shown in enumerate(self.shown_universes):
            label = f"universe {shown.number} {shown.name}".rstrip()
            item = Item(label, action=partial(self.choose, shown.number))
            stops.append(Stop(item, self.universes, row))
        stops += strip_stops(self.universe_edits)
        stops += strip_stops(self.place_strip)
        for universe, (_, dmx_map) in self.maps.items():
            for index, print_ in enumerate(dmx_map.prints):
                fixture: FixtureInfo | None = names.get(print_.fixture)
                name = "" if fixture is None else f" {fixture.name}"
                label = f"{universe}.{print_.start} fixture {print_.fixture}{name}"
                line = commands.sel_fixture(print_.fixture).text
                stops.append(Stop(Item(label.rstrip(), line=line), dmx_map, index))
        return stops
