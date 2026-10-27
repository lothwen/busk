"""F1 layout C, the stage (spec §8.1, plan Phase 5).

STAGE, left: the rig from above, the audience at the bottom. Fixtures are
placed by their ``location`` (plan §3, 6: x right, y downstage, z up, in
metres): a row per height and depth (rounded to 0.1 m), upstage at the top
and, at the same depth, the higher first, labelled ``y 2.0`` over ``z
5.0``; along the row, each fixture at its x, on one scale for all rows, on
a dashed line. A fixture is its type's glyph (``■`` par, ``◆`` spot, ``●``
wash, ``▲`` strobe; one ``█`` per element for a fixture of several) in its
live output colour and intensity, its number under it, and on a fixture
with pan or tilt the pan as an arrow (``↑`` at 0°, clockwise) and the tilt
(``↗ 30°``). Fixtures without a place are in a row of their own, under
AUDIENCE, and ``[location…]`` puts ``fixture N location {…}`` in the
prompt for the first selected fixture (else the first without a place). A
click selects, a Shift-click adds or takes out.

The right column: compact PLAYBACKS (``Pn``, name, bar, level, ``[GO]``),
MASTERS (the grand, size and group masters, and the tempo row), QUICK
(group buttons, colour chips). Below 100 columns it goes under the stage.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.colors import ColorMode
from busk_tui.commands import Line
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
from busk_tui.widgets.controls import ButtonStrip, StripButton, button_label
from busk_tui.widgets.fixture_palette import FixturePalette, Spot, centred, element_cells
from busk_tui.widgets.fixturetable import COLOR_CELLS, by_fixture
from busk_tui.widgets.masters import MasterBars
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.playbacks import PlaybackRow
from busk_tui.widgets.quick import color_chips, group_buttons, strip_stops
from busk_tui.widgets.tempo import TempoRow, beats_of, first_speed, speed_of

LABEL: Final = 9
"""The row labels' column; the stage starts a cell after it."""

ARROWS: Final = "↑↗→↘↓↙←↖"
"""The pan, 0° up, by eighths of a turn clockwise."""

MOVER: Final = 7
"""A mover's width, whatever its tilt (``↖ -135°``): fixtures stay put as
their tilt changes."""

NO_FIXTURES: Final = 'no fixtures · fixture add 101 "<profile>" mode <mode> at 1.1'
NO_PLACES: Final = "no fixture has a place on stage: select one, then [location…]"


@dataclass(frozen=True, slots=True)
class StageRow:
    """Fixtures at depth ``y`` and height ``z`` (metres, to 0.1), by x."""

    y: float
    z: float
    fixtures: tuple[tuple[float, FixtureInfo], ...]  # (x, fixture), by x


def stage_rows(fixtures: Sequence[FixtureInfo]) -> tuple[list[StageRow], list[FixtureInfo]]:
    """The rows of the fixtures with a place, upstage first (the smallest
    y), the higher first at the same depth; and the fixtures without one,
    in show order."""
    rows: dict[tuple[float, float], list[tuple[float, FixtureInfo]]] = {}
    unplaced = []
    for fixture in fixtures:
        if fixture.location is None:
            unplaced.append(fixture)
            continue
        x, y, z = fixture.location[:3]
        rows.setdefault((round(y, 1), round(z, 1)), []).append((x, fixture))
    ordered = sorted(rows.items(), key=lambda item: (item[0][0], -item[0][1]))
    return [
        StageRow(y, z, tuple(sorted(placed, key=lambda pair: (pair[0], pair[1].number))))
        for (y, z), placed in ordered
    ], unplaced


def place(
    widths: Sequence[int], centres: Sequence[float], room: int
) -> list[list[tuple[int, int]]]:
    """Where items ``widths`` wide go in ``room`` cells, as near their
    ``centres`` as they can with a cell between two: lines of ``(item,
    left)``. Items that do not fit on one line are spread evenly over as
    many as they need, in order."""
    count = len(widths)
    if not count:
        return []
    if sum(widths) + count - 1 > room:
        lines: list[list[int]] = [[]]
        used = 0
        for index, width in enumerate(widths):
            if lines[-1] and used + 1 + width > room:
                lines.append([])
                used = 0
            used += width + (1 if lines[-1] else 0)
            lines[-1].append(index)
        return [_spread(line, widths, room) for line in lines]
    lefts = [max(0, min(room - w, round(c - w / 2))) for w, c in zip(widths, centres, strict=True)]
    for index in range(1, count):
        lefts[index] = max(lefts[index], lefts[index - 1] + widths[index - 1] + 1)
    lefts[-1] = min(lefts[-1], room - widths[-1])
    for index in range(count - 2, -1, -1):
        lefts[index] = min(lefts[index], lefts[index + 1] - 1 - widths[index])
    return [list(enumerate(lefts))]


def _spread(items: Sequence[int], widths: Sequence[int], room: int) -> list[tuple[int, int]]:
    """``items`` evenly over ``room`` cells (each in a share of its own)."""
    share = room / len(items)
    placed = []
    edge = 0
    for slot, index in enumerate(items):
        left = max(edge, round(share * (slot + 0.5) - widths[index] / 2))
        left = max(0, min(left, room - widths[index]))
        placed.append((index, left))
        edge = left + widths[index] + 1
    return placed


def pan_text(outputs: Sequence[ElementOutput]) -> str:
    """``↗ 30°``: the pan as an arrow and the tilt in degrees, of the first
    element that has them; ``·`` before the output is known."""
    pan = next((out.pan for out in outputs if out.pan is not None), None)
    tilt = next((out.tilt for out in outputs if out.tilt is not None), None)
    if pan is None and tilt is None:
        return "·"
    arrow = "" if pan is None else ARROWS[round((pan % 360) / 45) % 8]
    angle = "" if tilt is None else f"{round(tilt)}°"
    return f"{arrow} {angle}".strip()


@dataclass(frozen=True, slots=True)
class _Item:
    fixture: FixtureInfo
    cells: list[tuple[str, str]]
    arrow: str | None  # a mover's pan and tilt; None: not a mover
    width: int


class StagePlot(FixturePalette):
    """STAGE's fixtures (see the module docs)."""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.rows: list[StageRow] = []
        self.unplaced: list[FixtureInfo] = []
        self.items: dict[int, _Item] = {}
        self._outputs: tuple[OutputModel | None, dict[int, tuple[ElementOutput, ...]]] = (None, {})
        self._cached: dict[int, tuple[object, _Item]] = {}
        self._fixtures: tuple[FixtureInfo, ...] | None = None

    def show(
        self,
        show: ShowModel | None,
        output: OutputModel | None,
        programmer: ProgrammerModel | None,
        mode: ColorMode,
    ) -> None:
        if self._outputs[0] is not output:
            self._outputs = (output, by_fixture(output))
        outputs = self._outputs[1]
        self.selected = (
            frozenset() if programmer is None else frozenset(n for n, _ in programmer.selection)
        )
        fixtures = () if show is None else show.fixtures
        if fixtures is not self._fixtures:
            self._fixtures = fixtures
            self.rows, self.unplaced = stage_rows(fixtures)
        profiles = {} if show is None else {p.name: p for p in show.profiles}
        items: dict[int, _Item] = {}
        cached: dict[int, tuple[object, _Item]] = {}
        for fixture in fixtures:
            profile = profiles.get(fixture.profile)
            category = None if profile is None else profile.category
            mover = profile is not None and bool(profile.attributes & {"pan", "tilt"})
            shows = (fixture, outputs.get(fixture.number, ()), category, mover, mode)
            before = self._cached.get(fixture.number)
            if before is None or before[0] != shows:
                glyph = colors.CATEGORY_GLYPHS.get(category or "", colors.OTHER_GLYPH)
                cells = element_cells(shows[1], fixture.elements, glyph, COLOR_CELLS, mode)
                arrow = pan_text(shows[1]) if mover else None
                width = max(len(cells), len(str(fixture.number)), MOVER if mover else 0)
                before = (shows, _Item(fixture, cells, arrow, width))
            cached[fixture.number] = before
            items[fixture.number] = before[1]
        self._cached = cached
        self.items = items
        self.redraw()

    def draw(self, width: int) -> tuple[list[Text], list[Spot]]:
        if not self.items:
            return [Text(NO_FIXTURES, style=colors.DIM)], []
        room = max(1, width - LABEL - 1)
        lines: list[Text] = []
        spots: list[Spot] = []
        xs = [x for row in self.rows for x, _ in row.fixtures]
        low, high = (min(xs), max(xs)) if xs else (0.0, 0.0)
        widest = max(item.width for item in self.items.values())
        for index, row in enumerate(self.rows):
            if index:
                lines.append(Text())
            items = [self.items[fixture.number] for _, fixture in row.fixtures]
            span = max(1, room - widest)
            centres = [
                room / 2 if high == low else widest / 2 + (x - low) / (high - low) * span
                for x, _ in row.fixtures
            ]
            for part, placed in enumerate(place([i.width for i in items], centres, room)):
                labels = (f"y {row.y:.1f}", f"z {row.z:.1f}") if part == 0 else ("", "")
                drawn = [(items[i], left) for i, left in placed]
                self._draw_line(lines, spots, drawn, labels, width, "┄")
        if not self.rows:
            lines.append(Text(" " * (LABEL + 1) + NO_PLACES, style=colors.DIM))
        lines.append(Text())
        word = "  AUDIENCE  "
        side = max(0, (room - len(word)) // 2)
        dots = ("· " * (side // 2 + 1))[:side]
        lines.append(Text(" " * (LABEL + 1) + dots + word + dots[::-1], style=colors.BORDER))
        if self.unplaced:
            lines.append(Text())
            labels = ("no place", "")
            line: list[tuple[_Item, int]] = []
            x = 0
            for fixture in self.unplaced:
                item = self.items[fixture.number]
                if x and x + item.width > room:
                    self._draw_line(lines, spots, line, labels, width)
                    labels, line, x = ("", ""), [], 0
                line.append((item, x))
                x += item.width + 2
            self._draw_line(lines, spots, line, labels, width)
        return lines, spots

    def _draw_line(
        self,
        lines: list[Text],
        spots: list[Spot],
        placed: list[tuple[_Item, int]],
        labels: tuple[str, str],
        width: int,
        truss: str = " ",
    ) -> None:
        """One line of fixtures, ``width`` cells wide: their glyphs on the
        truss, their numbers, and the movers' pan and tilt (when one has
        them)."""
        y = len(lines)
        top = Text(labels[0].ljust(LABEL + 1)[: LABEL + 1], style=colors.MID)
        middle = Text(labels[1].ljust(LABEL + 1)[: LABEL + 1], style=colors.BORDER)
        movers = any(item.arrow is not None for item, _ in placed)
        bottom = Text(" " * (LABEL + 1))
        for item, left in placed:
            start = LABEL + 1 + left
            if start > top.cell_len:
                top.append(truss * (start - top.cell_len), style=colors.BORDER)
            middle.append(" " * (start - middle.cell_len))
            bottom.append(" " * (start - bottom.cell_len))
            shown = sum(len(cell) for cell, _ in item.cells)
            pad = (item.width - shown) // 2
            top.append(" " * pad)
            for cell, style in item.cells:
                top.append(cell, style=style)
            top.append(" " * (item.width - shown - pad))
            number = item.fixture.number
            selected = number in self.selected
            middle.append(
                centred(str(number), item.width), style=colors.CYAN if selected else colors.DIM
            )
            bottom.append(centred(item.arrow or "", item.width), style=colors.DIM)
            height = 3 if movers else 2
            if selected:
                for text in (top, middle, bottom)[:height]:
                    text.stylize(f"on {colors.SEL}", start, start + item.width)
            spots.append(Spot(number, y, start, item.width, height))
        if truss != " " and top.cell_len < width:
            top.append(truss * (width - top.cell_len), style=colors.BORDER)
        lines += [top, middle, bottom] if movers else [top, middle]

    def edited(self) -> FixtureInfo | None:
        """The fixture ``[location…]`` is for: the first selected, else the
        first without a place, else the first."""
        fixtures = [item.fixture for item in self.items.values()]
        for fixture in fixtures:
            if fixture.number in self.selected:
                return fixture
        if self.unplaced:
            return self.unplaced[0]
        return fixtures[0] if fixtures else None


def location_button(fixture: FixtureInfo) -> StripButton:
    text = commands.location_prefill(fixture.number, fixture.location)
    return StripButton(button_label("location…", colors.MID), Line(text), prefill=text)


class StageLayout(Horizontal):
    """Layout C (see the module docs)."""

    DEFAULT_CSS = """
    StageLayout { height: auto; }
    StageLayout > #stage-panel { width: 3fr; }
    StageLayout > #stage-side { width: 1fr; min-width: 40; height: auto; }
    StageLayout #stage-rows, StageLayout #stage-tempo { height: auto; }
    StageLayout #stage-tempo { margin-top: 1; }
    StageLayout #stage-edit-row { height: auto; margin-top: 1; }
    StageLayout #stage-edit-label { width: auto; padding-right: 1; }
    StageLayout #stage-edits { width: 1fr; }
    StageLayout #stage-groups { margin-bottom: 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.slots: tuple[int | None, ...] | None = None
        self.rows: list[PlaybackRow] = []
        self.plot = StagePlot(id="stage-plot")
        self.edit_label = Static("", id="stage-edit-label")
        self.edits = ButtonStrip(id="stage-edits")
        self.rows_box = Vertical(id="stage-rows")
        self.bars = MasterBars(BAR_MASTERS, id="stage-bars")
        self.tempo_box = Vertical(id="stage-tempo")
        self.tempo: TempoRow | None = None
        self.tempo_for: tuple[MasterView | None] | None = None
        self.groups = ButtonStrip(id="stage-groups")
        self.chips = ButtonStrip(id="stage-chips")

    def compose(self) -> ComposeResult:
        with Panel("stage", id="stage-panel", meta="click selects, Shift-click adds"):
            yield self.plot
            with Horizontal(id="stage-edit-row"):
                yield self.edit_label
                yield self.edits
        with Vertical(id="stage-side"):
            with Panel("playbacks", id="stage-playbacks"):
                yield self.rows_box
            with Panel("masters", id="stage-masters"):
                yield self.bars
                yield self.tempo_box
            with Panel("quick", id="stage-quick"):
                yield self.groups
                yield self.chips

    def update_view(
        self, view: View, changed: frozenset[Part], slots: tuple[int | None, ...]
    ) -> None:
        show, live = view.show, view.live
        if slots != self.slots:
            self.slots = slots
            self.rows = [
                PlaybackRow(index + 1, number, compact=True) for index, number in enumerate(slots)
            ]
            self.rows_box.remove_children()
            self.rows_box.mount_all(self.rows)
        if changed & {"show", "live", "playback"}:
            for row in self.rows:
                if row.number is None:
                    continue
                info = None if show is None else show.playback(row.number)
                cue_list = None if show is None or info is None else show.cue_list(info.cueList)
                playback = None if live is None else live.playback(row.number)
                row.show(playback, info, cue_list, row.number == view.playback, view.mode)
        if changed & {"show", "programmer", "output"}:
            self.plot.show(show, view.output, view.programmer, view.mode)
        if changed & {"show", "programmer"}:
            self._show_edits()
            self.groups.show(group_buttons(() if show is None else show.groups))
            self.chips.show(color_chips(() if show is None else show.presets, view.mode))
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

    def _show_edits(self) -> None:
        fixture = self.plot.edited()
        label = Text()
        buttons = []
        if fixture is not None:
            label.append("place ", style=colors.DIM)
            label.append(f"fixture {fixture.number}", style=colors.CYAN)
            if fixture.name:
                label.append(f" {fixture.name}", style=colors.FG)
            buttons.append(location_button(fixture))
        if label != self.edit_label.content:
            self.edit_label.update(label)
        self.edits.show(buttons)

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
        for row in self.rows:
            for button in row.buttons:
                stops.append(Stop(Item(button.line.text, line=button.line.text), button))
        stops += self.bars.stops()
        if self.tempo is not None:
            stops += self.tempo.stops()
        stops += strip_stops(self.groups)
        stops += strip_stops(self.chips)
        return stops + self.plot.stops() + strip_stops(self.edits)
