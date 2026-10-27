"""F1 layout A, the console (spec §8.1, plan Phase 5).

OUTPUT, top left: a row per fixture type (the profile's category, plan §3
8; a profile with none has a row of its own, named after it), each fixture
in its live output colour and intensity (:mod:`busk_tui.widgets.fixture_palette`),
its number under it; the selected ones on the selection's background. A
click selects, a Shift-click adds or takes out.

PROGRAMMER, top right (a third of the width, at least 38 cells): the
selection, what the programmer holds (``2 fixtures · intensity color
pan``), the colour chips, the bars of the grand, size and group masters,
and the tempo row (the first speed master, TAP, B.O.).

PLAYBACKS, below: a column per slot of the current page, with a vertical
fader in the current cue's colour, ``[GO] [◂]`` and ``[FLASH]``, as many to a
line as fit, at least 11 cells each. Below 100 columns OUTPUT and
PROGRAMMER go one under the other.
"""

from __future__ import annotations

from typing import Final

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static

from busk_tui import colors
from busk_tui.colors import ColorMode
from busk_tui.formats import selection_text
from busk_tui.model import (
    ElementOutput,
    FixtureInfo,
    MasterView,
    OutputModel,
    ProgrammerModel,
    ShowModel,
)
from busk_tui.nav import Item, Stop
from busk_tui.pages.base import Part, View
from busk_tui.pages.busk_stack import BAR_MASTERS
from busk_tui.widgets.controls import ButtonStrip
from busk_tui.widgets.fixture_palette import FixturePalette, Spot, centred, element_cells
from busk_tui.widgets.fixturetable import by_fixture
from busk_tui.widgets.masters import MasterBars
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.playbacks import PlaybackColumn
from busk_tui.widgets.quick import color_chips, strip_stops
from busk_tui.widgets.tempo import TempoRow, beats_of, first_speed, speed_of
from busk_tui.widgets.vfader import ROWS

LABEL: Final = 9
"""OUTPUT's label column: at least this wide, wider for a profile's name."""

MAX_LABEL: Final = 20
COLUMN_WIDTH: Final = 11
"""A playback column at least this wide, its border included."""

NO_FIXTURES: Final = 'no fixtures · fixture add 101 "<profile>" mode <mode> at 1.1'

type Rows = list[tuple[str, list[FixtureInfo]]]


def output_rows(show: ShowModel | None) -> Rows:
    """OUTPUT's rows: one per category in :data:`colors.CATEGORY_ROWS`'s
    order, then one per profile without a category, named after it; each
    with its fixtures in show order."""
    if show is None:
        return []
    categories = {profile.name: profile.category for profile in show.profiles}
    by_category: dict[str, list[FixtureInfo]] = {}
    by_profile: dict[str, list[FixtureInfo]] = {}
    for fixture in show.fixtures:
        category = categories.get(fixture.profile)
        if category in colors.CATEGORY_ROWS:
            by_category.setdefault(category, []).append(fixture)
        else:
            by_profile.setdefault(fixture.profile, []).append(fixture)
    rows: Rows = [
        (name, by_category[category])
        for category, name in colors.CATEGORY_ROWS.items()
        if category in by_category
    ]
    rows += [(profile or "no profile", fixtures) for profile, fixtures in by_profile.items()]
    return rows


def programmer_summary(programmer: ProgrammerModel | None) -> Text:
    """``2 fixtures · intensity color pan · 1 effect · BLIND``, or
    ``programmer empty``."""
    if programmer is None or not (programmer.values or programmer.effects):
        text = Text("programmer empty", style=colors.DIM)
    else:
        attributes = list(dict.fromkeys(value.attribute for value in programmer.values))
        count = programmer.fixtures
        parts = [f"{count} fixture{'' if count == 1 else 's'}"] if count else []
        if attributes:
            parts.append(" ".join(attributes))
        effects = len(programmer.effects)
        if effects:
            parts.append(f"{effects} effect{'' if effects == 1 else 's'}")
        text = Text(" · ".join(parts), style=colors.MID)
    if programmer is not None and programmer.blind:
        text.append(" · ", style=colors.DIM)
        text.append("BLIND", style=colors.MAGENTA)
    return text


class OutputGrid(FixturePalette):
    """OUTPUT's fixtures (see the module docs)."""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.rows: Rows = []
        self.mode: ColorMode = "256"
        self._show: ShowModel | None = None
        self._outputs: tuple[OutputModel | None, dict[int, tuple[ElementOutput, ...]]] = (None, {})
        self._cells: dict[int, tuple[object, list[tuple[str, str]]]] = {}

    def show(
        self,
        show: ShowModel | None,
        output: OutputModel | None,
        programmer: ProgrammerModel | None,
        mode: ColorMode,
    ) -> None:
        if self._outputs[0] is not output:
            self._outputs = (output, by_fixture(output))
        self.selected = (
            frozenset() if programmer is None else frozenset(n for n, _ in programmer.selection)
        )
        if show is not self._show:
            self._show = show
            self.rows = output_rows(show)
        self.mode = mode
        self.redraw()

    def cells(self, fixture: FixtureInfo, room: int) -> list[tuple[str, str]]:
        """The fixture's cells, ``room`` at most (kept while its output stays)."""
        shows = (self._outputs[1].get(fixture.number, ()), fixture.elements, room, self.mode)
        cached = self._cells.get(fixture.number)
        if cached is None or cached[0] != shows:
            cached = (shows, element_cells(shows[0], fixture.elements, "███", room, self.mode))
            self._cells[fixture.number] = cached
        return cached[1]

    def draw(self, width: int) -> tuple[list[Text], list[Spot]]:
        if not self.rows:
            return [Text(NO_FIXTURES, style=colors.DIM)], []
        label_width = min(MAX_LABEL, max(LABEL, *(len(label) + 1 for label, _ in self.rows)))
        shown_fixtures = {fixture.number for _, items in self.rows for fixture in items}
        self._cells = {n: c for n, c in self._cells.items() if n in shown_fixtures}
        room = max(1, width - label_width)
        lines: list[Text] = []
        spots: list[Spot] = []
        for index, (label, items) in enumerate(self.rows):
            if index:
                lines.append(Text())
            placed: list[list[tuple[int, int, FixtureInfo, list[tuple[str, str]]]]] = [[]]
            x = 0
            for fixture in items:
                cells = self.cells(fixture, room)
                size = max(sum(len(c) for c, _ in cells), len(str(fixture.number)))
                if x and x + size > room:
                    placed.append([])
                    x = 0
                placed[-1].append((x, size, fixture, cells))
                x += size + 1
            for line, row in enumerate(placed):
                name = label if line == 0 else ""
                if len(name) >= label_width:
                    name = name[: label_width - 2] + "…"
                top = Text(name.ljust(label_width), style=colors.DIM)
                bottom = Text(" " * label_width)
                for x, size, fixture, cells in row:
                    left = label_width + x
                    top.append(" " * (left - top.cell_len))
                    bottom.append(" " * (left - bottom.cell_len))
                    shown = sum(len(c) for c, _ in cells)
                    pad = (size - shown) // 2
                    top.append(" " * pad)
                    for cell, style in cells:
                        top.append(cell, style=style)
                    top.append(" " * (size - shown - pad))
                    selected = fixture.number in self.selected
                    bottom.append(
                        centred(str(fixture.number), size),
                        style=colors.CYAN if selected else colors.DIM,
                    )
                    if selected:
                        top.stylize(f"on {colors.SEL}", left, left + size)
                        bottom.stylize(f"on {colors.SEL}", left, left + size)
                    spots.append(Spot(fixture.number, len(lines), left, size, 2))
                lines += [top, bottom]
        return lines, spots


class ColumnGrid(Container):
    """The playback columns, as many to a line as fit."""

    DEFAULT_CSS = f"""
    ColumnGrid {{ layout: grid; grid-size: 1; grid-columns: 1fr; grid-rows: {ROWS + 8};
                  height: auto; }}
    """

    def on_resize(self, event: events.Resize) -> None:
        columns = max(1, event.size.width // COLUMN_WIDTH)
        if columns != self.styles.grid_size_columns:
            self.styles.grid_size_columns = columns
            self.styles.grid_columns = " ".join(["1fr"] * columns)


class ConsoleLayout(Vertical):
    """Layout A (see the module docs)."""

    DEFAULT_CSS = """
    ConsoleLayout { height: auto; }
    ConsoleLayout > #console-top { height: auto; }
    ConsoleLayout #console-output { width: 2fr; }
    ConsoleLayout #console-programmer { width: 1fr; min-width: 38; }
    ConsoleLayout #console-summary { margin-bottom: 1; }
    ConsoleLayout #console-color-row { height: auto; margin-bottom: 1; }
    ConsoleLayout #console-color-label { width: 6; color: #767676; }
    ConsoleLayout #console-chips { width: 1fr; }
    ConsoleLayout #console-tempo { height: auto; margin-top: 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.slots: tuple[int | None, ...] | None = None
        self.columns: list[PlaybackColumn] = []
        self.grid = OutputGrid(id="console-grid")
        self.selection = Static("", id="console-selection")
        self.summary = Static("", id="console-summary")
        self.chips = ButtonStrip(id="console-chips")
        self.bars = MasterBars(BAR_MASTERS, id="console-bars")
        self.tempo_box = Vertical(id="console-tempo")
        self.tempo: TempoRow | None = None
        self.tempo_for: tuple[MasterView | None] | None = None  # the master the row was built for
        self.column_box = ColumnGrid(id="console-columns")
        self.output_panel = Panel("output", id="console-output")

    def compose(self) -> ComposeResult:
        with Horizontal(id="console-top"):
            with self.output_panel:
                yield self.grid
            with Panel("programmer", id="console-programmer"):
                yield self.selection
                yield self.summary
                with Horizontal(id="console-color-row"):
                    yield Static("color", id="console-color-label")
                    yield self.chips
                yield self.bars
                yield self.tempo_box
        with Panel("playbacks", id="console-playbacks"):
            yield self.column_box

    def update_view(
        self, view: View, changed: frozenset[Part], slots: tuple[int | None, ...]
    ) -> None:
        show, live = view.show, view.live
        if slots != self.slots:
            self.slots = slots
            self.columns = [PlaybackColumn(index + 1, number) for index, number in enumerate(slots)]
            self.column_box.remove_children()
            self.column_box.mount_all(self.columns)
        if changed & {"show", "live", "playback"}:
            for column in self.columns:
                if column.number is None:
                    continue
                info = None if show is None else show.playback(column.number)
                cue_list = None if show is None or info is None else show.cue_list(info.cueList)
                playback = None if live is None else live.playback(column.number)
                column.show(playback, info, cue_list, column.number == view.playback, view.mode)
        if changed & {"show", "programmer", "output"}:
            self.grid.show(show, view.output, view.programmer, view.mode)
        if changed & {"show", "programmer"}:
            self._show_programmer(view)
        if "show" in changed:
            self.bars.build(show, live)
            self._build_tempo(show)
        if changed & {"show", "live"} and live is not None:
            self.bars.show_levels(live)
            if self.tempo is not None:
                name = None if self.tempo.master is None else self.tempo.master.name
                self.tempo.show(None if name is None else speed_of(live, name), live.blackout)
        if changed & {"live", "beats"} and self.tempo is not None and self.tempo.master is not None:
            self.tempo.show_beats(beats_of(live, view.beats, self.tempo.master.name))

    def _show_programmer(self, view: View) -> None:
        show, programmer = view.show, view.programmer
        selection = () if programmer is None else programmer.selection
        compressed = "" if show is None else selection_text(selection, show.fixtures)
        text = Text("sel ", style=colors.DIM)
        text.append(compressed or "none", style=colors.CYAN if compressed else colors.DIM)
        if selection:
            text.append(f" ({len(selection)})", style=colors.DIM)
        self.selection.update(text)
        self.summary.update(programmer_summary(programmer))
        self.chips.show(color_chips(() if show is None else show.presets, view.mode))
        count = 0 if show is None else len(show.fixtures)
        self.output_panel.set_title("output", f"{count} fixtures · click selects, Shift-click adds")

    def _build_tempo(self, show: ShowModel | None) -> None:
        first = first_speed(show)
        if self.tempo_for == (first,):
            return
        self.tempo_for = (first,)
        self.tempo = TempoRow(first)
        self.tempo_box.remove_children()
        self.tempo_box.mount(self.tempo)

    def stops(self) -> list[Stop]:
        stops: list[Stop] = []
        for column in self.columns:
            for button in column.buttons:
                stops.append(Stop(Item(button.line.text, line=button.line.text), button))
        stops += strip_stops(self.chips)
        stops += self.bars.stops()
        if self.tempo is not None:
            stops += self.tempo.stops()
        return stops + self.grid.stops()
