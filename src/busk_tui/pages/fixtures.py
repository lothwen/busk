"""F3 Fixtures (spec §8.3, plan Phase 4, ``docs/plans/tui-rig-plan.md``): every
fixture, by number, with its patch and its live output
(:mod:`busk_tui.widgets.fixturetable`), and the FIXTURE panel of edit mode.

A header gives the counts and has the ``[edit]`` toggle. A click on a row
selects the fixture (``sel fixture 101``) and chooses it; a Shift-click adds
it to the selection or takes it out (``sel + fixture 101``, ``sel - fixture
101``) and chooses it. Selecting does not change the stage, so a click means
the same in edit mode.

In edit mode the FIXTURE panel (:mod:`busk_tui.widgets.fixture_panel`) shows
the chosen fixture, to the right of the table at 100 columns or more, else
under it. The rig's columns take the place of the live ones, the legend goes,
and the page stops reading the output; ``[done]`` leaves edit mode.

Out of it the page reads the output while it shows, and rows are drawn again
only when their fixture's output, patch or selection changes.
"""

from __future__ import annotations

from functools import partial
from typing import Final

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.model import ElementOutput, FixtureInfo, OutputModel
from busk_tui.nav import Item, Stop
from busk_tui.pages.base import Page, Part, View
from busk_tui.widgets.controls import ActionButton, RunLine
from busk_tui.widgets.fixture_panel import FixturePanel
from busk_tui.widgets.fixturetable import (
    FixtureTable,
    RigTable,
    by_fixture,
    fixture_cells,
    legend,
    rig_cells,
)
from busk_tui.widgets.legend import Legend
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.rows import Cells, RowTable

NO_FIXTURES: Final = 'no fixtures · fixture add 101 "<profile>" mode <mode> at 1.1'

CLICK_SELECTS: Final = "click selects, Shift-click adds"
CLICK_EDITS: Final = "click chooses, Shift-click adds to the selection"

NARROW: Final = 100
"""Below this many columns the FIXTURE panel goes under the table (spec §3)."""

ABOVE: Final = 3
"""The page's rows above the FIXTURE panel: its padding, the header and the
gap after it."""


class FixturesPage(Page):
    """F3 (see the module docs)."""

    DEFAULT_CSS = """
    FixturesPage #fixtures-head { height: 1; margin-bottom: 1; }
    FixturesPage #fixtures-header { width: 1fr; }
    FixturesPage #fixtures-body { height: auto; }
    FixturesPage #fixtures-panel { width: 1fr; }
    FixturesPage #fixtures-legend { margin-top: 1; }
    """

    def __init__(self, number: int, title: str) -> None:
        super().__init__(number, title)
        self.header = Static("", id="fixtures-header")
        self.edit = ActionButton("edit", self.toggle_edit, id="fixtures-edit")
        empty = Text(NO_FIXTURES, style=colors.DIM)
        self.table = FixtureTable(empty, id="fixture-table")
        self.rig = RigTable(empty, id="rig-table")
        self.rig.display = False
        self.legend = Legend(legend(), id="fixtures-legend")
        self.sheet = Panel("fixtures", id="fixtures-panel")
        self.panel = FixturePanel(self._draw, self.leave_edit)
        self.panel.display = False
        self.editing = False
        self.shown: tuple[FixtureInfo, ...] = ()
        self._view = View()
        self._width = 0
        self._outputs: tuple[OutputModel | None, dict[int, tuple[ElementOutput, ...]]] = (None, {})
        self._cells: dict[int, tuple[object, Cells]] = {}  # fixture → (what it shows, its cells)

    def compose(self) -> ComposeResult:
        with Horizontal(id="fixtures-head"):
            yield self.header
            yield self.edit
        with Horizontal(id="fixtures-body"):
            with self.sheet:
                yield self.table
                yield self.rig
                yield self.legend
            yield self.panel

    def on_resize(self, event: events.Resize) -> None:
        self._width = event.size.width
        beside = self._width >= NARROW
        self.panel.styles.max_height = max(8, event.size.height - ABOVE) if beside else None

    def watches(self, view: View) -> tuple[bool, bool]:
        """The output, for the live columns: not in edit mode, which has none."""
        return not self.editing, False

    def update_view(self, view: View, changed: frozenset[Part]) -> None:
        self._view = view
        if "show" in changed:
            fixtures = () if view.show is None else view.show.fixtures
            self.shown = tuple(sorted(fixtures, key=lambda fixture: fixture.number))
            if all(fixture.number != self.panel.chosen for fixture in self.shown):
                self.panel.chosen = None  # only here: a renumber's done may come before the show
        if changed & {"show", "programmer"} or (not self.editing and "output" in changed):
            self._draw()
        if changed & {"show", "programmer"}:
            self._draw_header()
            if self.editing:
                self.panel.show_view(view.show, self.selected())

    def selected(self) -> frozenset[int]:
        programmer = self._view.programmer
        return frozenset(() if programmer is None else (n for n, _ in programmer.selection))

    # ------------------------------------------------------------- draw

    def _draw_header(self) -> None:
        selected = self.selected()
        count = sum(1 for fixture in self.shown if fixture.number in selected)
        how = CLICK_EDITS if self.editing else CLICK_SELECTS
        text = Text(f"{len(self.shown)} fixtures · {count} selected · {how}", style=colors.DIM)
        if text != self.header.content:
            self.header.update(text)
        if self.editing:
            self.edit.change(label="edit ●", intent="record", reverse=True)
        else:
            self.edit.change(label="edit", intent="neutral", reverse=False)

    def _draw(self) -> None:
        show = self._view.show
        categories = {} if show is None else {p.name: p.category for p in show.profiles}
        selected = self.selected()
        lit = frozenset(i for i, fixture in enumerate(self.shown) if fixture.number in selected)
        if self.editing:
            rows = [
                rig_cells(f, f.number in selected, f.number == self.panel.chosen,
                          categories.get(f.profile))
                for f in self.shown
            ]  # fmt: skip
            self.rig.show(rows, lit=lit)
        else:
            self.table.show(self._live_rows(categories, selected), lit=lit)

    def _live_rows(
        self, categories: dict[str, str | None], selected: frozenset[int]
    ) -> list[Cells]:
        view = self._view
        if self._outputs[0] is not view.output:
            self._outputs = (view.output, by_fixture(view.output))
        outputs = self._outputs[1]
        rows: list[Cells] = []
        kept: dict[int, tuple[object, Cells]] = {}
        for fixture in self.shown:
            elements = outputs.get(fixture.number, ())
            shows = (fixture, elements, fixture.number in selected,
                     categories.get(fixture.profile), view.mode)  # fmt: skip
            cached = self._cells.get(fixture.number)
            if cached is None or cached[0] != shows:
                cached = (shows, fixture_cells(*shows))
            kept[fixture.number] = cached
            rows.append(cached[1])
        self._cells = kept
        return rows

    # -------------------------------------------------------- edit mode

    def toggle_edit(self) -> None:
        self.set_editing(not self.editing)

    def leave_edit(self) -> None:
        self.set_editing(False)

    def set_editing(self, on: bool) -> None:
        """Enter edit mode, with the panel on what is chosen, or leave it."""
        self.editing = on
        self.table.display = self.legend.display = not on
        self.rig.display = self.panel.display = on
        self._draw()
        self._draw_header()
        if on:
            self.panel.show_view(self._view.show, self.selected())
        self.post_message(Page.WatchesChanged(self))

    # ----------------------------------------------------------- clicks

    def on_row_table_clicked(self, message: RowTable.Clicked) -> None:
        message.stop()
        if message.row >= len(self.shown):
            return
        number = self.shown[message.row].number
        self.panel.choose(number)
        if message.shift:
            selected = number in self.selected()
            line = commands.sel_fixture(number, add=not selected, remove=selected)
        else:
            line = commands.sel_fixture(number)
        self.post_message(RunLine(line))
        if self.editing and self._width < NARROW:
            self.call_after_refresh(self.scroll_to_widget, self.panel, animate=False, top=True)

    # ----------------------------------------------------- pane cursor

    def stops(self) -> list[Stop]:
        """The edit toggle, each row, then the FIXTURE panel's controls."""
        stops = [Stop(Item("edit", action=self.toggle_edit), self.edit)]
        table = self.rig if self.editing else self.table
        table.spots = [(row, None) for row in range(len(self.shown))]
        for row, fixture in enumerate(self.shown):
            line = commands.sel_fixture(fixture.number).text
            label = f"fixture {fixture.number} {fixture.name}".rstrip()
            item = Item(label, line=line, action=partial(self.panel.choose, fixture.number))
            stops.append(Stop(item, table, row))
        if self.editing:
            stops += self.panel.stops()
        return stops
