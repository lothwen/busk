"""F3 Fixtures (spec §8.3, plan Phase 4): every fixture with its patch and
its live output (:mod:`busk_tui.widgets.fixturetable`).

A click on a row selects the fixture (``sel fixture 101``); a Shift-click
adds it to the selection or takes it out (``sel + fixture 101``, ``sel -
fixture 101``). The row clicked last is the one the edits under the table
act on (else the first selected fixture, else the first): its patch, its
place on stage (``location``), its profile's category and its name, each
put in the prompt to finish.

The page reads the output while it shows. Rows are drawn again only when
their fixture's output, patch or selection changes.
"""

from __future__ import annotations

from functools import partial
from typing import ClassVar, Final

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.commands import Line
from busk_tui.model import ElementOutput, FixtureInfo, OutputModel
from busk_tui.nav import Item, Stop
from busk_tui.pages.base import Page, Part, View
from busk_tui.widgets.controls import ButtonStrip, RunLine, StripButton, button_label
from busk_tui.widgets.fixturetable import FixtureTable, by_fixture, fixture_cells, legend
from busk_tui.widgets.legend import Legend
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.quick import strip_stops
from busk_tui.widgets.rows import Cells, RowTable

NO_FIXTURES: Final = 'no fixtures · fixture add 101 "<profile>" mode <mode> at 1.1'


class FixturesPage(Page):
    """F3 (see the module docs)."""

    WATCH_OUTPUT: ClassVar[bool] = True

    DEFAULT_CSS = """
    FixturesPage #fixtures-legend { margin-top: 1; }
    FixturesPage #fixture-edit-row { height: auto; margin-top: 1; }
    FixturesPage #fixture-edit-label { width: auto; padding-right: 1; }
    FixturesPage #fixture-edits { width: 1fr; }
    """

    def __init__(self, number: int, title: str) -> None:
        super().__init__(number, title)
        self.table = FixtureTable(Text(NO_FIXTURES, style=colors.DIM), id="fixture-table")
        self.panel = Panel("fixtures", id="fixtures-panel")
        self.edit_label = Static("", id="fixture-edit-label")
        self.edits = ButtonStrip(id="fixture-edits")
        self.chosen: int | None = None  # the fixture clicked last
        self.shown: tuple[FixtureInfo, ...] = ()
        self._view = View()
        self._outputs: tuple[OutputModel | None, dict[int, tuple[ElementOutput, ...]]] = (None, {})
        self._cells: dict[int, tuple[object, Cells]] = {}  # fixture → (what it shows, its cells)

    def compose(self) -> ComposeResult:
        with self.panel:
            yield self.table
            yield Legend(legend(), id="fixtures-legend")
            with Horizontal(id="fixture-edit-row"):
                yield self.edit_label
                yield self.edits

    def update_view(self, view: View, changed: frozenset[Part]) -> None:
        self._view = view
        if changed & {"show", "programmer", "output"}:
            self._draw()
        if changed & {"show", "programmer"}:
            meta = f"{len(self.shown)} fixtures · {len(self.table.lit)} selected"
            self.panel.set_title("fixtures", f"{meta} · click selects, Shift-click adds")
            self._draw_edits()

    def selected(self) -> set[int]:
        programmer = self._view.programmer
        return set() if programmer is None else {number for number, _ in programmer.selection}

    def edited(self) -> FixtureInfo | None:
        """The fixture the edits act on: the one clicked last, else the
        first selected, else the first."""
        selected = self.selected()
        for wanted in (self.chosen, *(f.number for f in self.shown if f.number in selected)):
            found = next((f for f in self.shown if f.number == wanted), None)
            if found is not None:
                return found
        return self.shown[0] if self.shown else None

    # ------------------------------------------------------------- draw

    def _draw(self) -> None:
        view, show = self._view, self._view.show
        self.shown = () if show is None else show.fixtures
        categories = {} if show is None else {p.name: p.category for p in show.profiles}
        if self._outputs[0] is not view.output:
            self._outputs = (view.output, by_fixture(view.output))
        outputs = self._outputs[1]
        selected = self.selected()
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
        lit = frozenset(i for i, fixture in enumerate(self.shown) if fixture.number in selected)
        self.table.show(rows, lit=lit)

    def _draw_edits(self) -> None:
        fixture = self.edited()
        if fixture is None:
            self._update(self.edit_label, Text())
            self.edits.show([])
            return
        label = Text("edit ", style=colors.DIM)
        label.append(f"fixture {fixture.number}", style=colors.CYAN)
        if fixture.name:
            label.append(f" {fixture.name}", style=colors.FG)
        self._update(self.edit_label, label)
        prefills = [
            ("patch", commands.patch_prefill(fixture.number)),
            ("location", commands.location_prefill(fixture.number, fixture.location)),
            ("category", _category_prefill(fixture.profile)),
            ("rename", commands.rename_fixture_prefill(fixture.number)),
        ]
        self.edits.show(
            [
                StripButton(button_label(f"{name}…", colors.MID), Line(text), prefill=text)
                for name, text in prefills
                if text is not None
            ]
        )

    @staticmethod
    def _update(widget: Static, text: Text) -> None:
        if text != widget.content:
            widget.update(text)

    # ----------------------------------------------------------- clicks

    def on_row_table_clicked(self, message: RowTable.Clicked) -> None:
        message.stop()
        if message.table is self.table and message.row < len(self.shown):
            number = self.shown[message.row].number
            self.choose(number)
            if message.shift:
                selected = number in self.selected()
                line = commands.sel_fixture(number, add=not selected, remove=selected)
            else:
                line = commands.sel_fixture(number)
            self.post_message(RunLine(line))

    def choose(self, number: int) -> None:
        """The fixture the edits act on."""
        self.chosen = number
        self._draw_edits()

    # ----------------------------------------------------- pane cursor

    def stops(self) -> list[Stop]:
        stops: list[Stop] = []
        self.table.spots = [(row, None) for row in range(len(self.shown))]
        for row, fixture in enumerate(self.shown):
            line = commands.sel_fixture(fixture.number).text
            label = f"fixture {fixture.number} {fixture.name}".rstrip()
            item = Item(label, line=line, action=partial(self.choose, fixture.number))
            stops.append(Stop(item, self.table, row))
        return stops + strip_stops(self.edits)


def _category_prefill(profile: str) -> str | None:
    """``profile "<name>" category ``; ``None`` for a name busk cannot read
    (a double quote in it), or no profile."""
    if not profile:
        return None
    try:
        return commands.category_prefill(profile)
    except ValueError:
        return None
