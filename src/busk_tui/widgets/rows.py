"""The table (spec §4.3): a header row (bg 235, cyan), then one line per row,
no row borders. The chosen row has bg 235, the row under the mouse bg 236.

A :class:`RowTable` is one widget, drawn line by line: a page hands it new
rows (:meth:`RowTable.show`), and only the lines that changed are drawn
again, without a layout pass while the number of rows stays (F5's running
effects change 20 times a second, the others not). Its columns are a
class's :data:`COLUMNS`, or a table's own (:meth:`RowTable.columns`); when
the table is narrower than all of them, the columns with the highest
``drop`` go first, and a ``flex`` column takes the room left. A click posts
:class:`RowTable.Clicked` with the row and the name of the column under the
mouse; the page decides what it does. In a table that :attr:`~RowTable.DRAGS`
(F3's), a press on a row dragged to another posts :class:`RowTable.Dragged`
instead, and the rows between are drawn as the row under the mouse is until
the mouse lets go. The pane cursor marks a row, or one cell of it
(:attr:`RowTable.spots`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar

from rich.text import Text
from textual import events
from textual.geometry import Region, Size
from textual.message import Message
from textual.strip import Strip
from textual.widget import Widget

from busk_tui import colors
from busk_tui.widgets.controls import MARKED, adds

type Cells = Mapping[str, Text]
"""One row: each column's text, by column name (a missing one is blank)."""


@dataclass(frozen=True, slots=True)
class Column:
    name: str  # what a click names
    title: str
    width: int  # in cells; a flex column's least
    drop: int = 0  # when narrow, the highest go first; 0 never goes
    flex: bool = False
    right: bool = False


def cell(text: str, style: str) -> Text:
    """A cell's text in one style (a span, so that two cells compare by it)."""
    return Text.assemble((text, style))


def fit(columns: Sequence[Column], width: int) -> list[tuple[Column, int]]:
    """The columns shown in ``width`` cells, a space between two, with their
    widths: those with the highest ``drop`` left out until the rest fit, and
    the room left to the flex columns."""
    shown = list(columns)
    while len(shown) > 1 and _need(shown) > width:
        worst = max(shown, key=lambda column: column.drop)
        if worst.drop == 0:
            break
        shown.remove(worst)
    room = max(0, width - _need(shown))
    flex = [column for column in shown if column.flex]
    widths = []
    for column in shown:
        extra = 0
        if column.flex and flex:
            share, rest = divmod(room, len(flex))
            extra = share + (1 if flex.index(column) < rest else 0)
        widths.append((column, column.width + extra))
    return widths


def _need(columns: Sequence[Column]) -> int:
    return sum(column.width for column in columns) + max(0, len(columns) - 1)


class RowTable(Widget):
    """Rows under a header (see the module docs)."""

    DEFAULT_CSS = "RowTable { height: auto; }"

    COLUMNS: ClassVar[tuple[Column, ...]] = ()

    DRAGS: ClassVar[bool] = False
    """Whether a press dragged from one row to another posts :class:`Dragged`
    (else it is a click where the mouse lets go, as Textual makes it)."""

    class Clicked(Message):
        """A click on ``row`` (counted from 0), in the column ``cell``
        (``None``: between two); ``adds``: a Ctrl-click
        (:func:`~busk_tui.widgets.controls.adds`)."""

        def __init__(self, table: RowTable, row: int, cell: str | None, adds: bool) -> None:
            super().__init__()
            self.table = table
            self.row = row
            self.cell = cell
            self.adds = adds

    class Dragged(Message):
        """A press on row ``start`` let go on row ``end``, another one (either
        may be the higher); ``adds``: Ctrl was held at the press."""

        def __init__(self, table: RowTable, start: int, end: int, adds: bool) -> None:
            super().__init__()
            self.table = table
            self.start = start
            self.end = end
            self.adds = adds

    def __init__(
        self, empty: Text | None = None, *, id: str | None = None, classes: str | None = None
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.empty = empty or Text()
        self.rows: tuple[Cells, ...] = ()
        self.chosen: int | None = None
        self.lit: frozenset[int] = frozenset()
        self.spots: list[tuple[int, str | None]] = []  # the pane cursor's stops: row, cell
        self._hover: int | None = None
        self._press: tuple[int, bool] | None = None  # a drag's first row, and whether it adds
        self._reach = 0  # the row a drag has reached
        self._dragged = False  # a drag just ended: the click Textual makes of it is not one
        self._marked: tuple[int, str | None] | None = None
        self._strips: dict[int, Strip] = {}  # line → as drawn, until it changes
        self._width = 0

    def show(
        self,
        rows: Sequence[Cells],
        chosen: int | None = None,
        empty: Text | None = None,
        lit: frozenset[int] = frozenset(),
    ) -> None:
        """New rows, the chosen one, what shows without rows (``None``: as
        before), and other rows drawn as the chosen one is (``lit``: F3's
        selected fixtures); the lines that differ are drawn again."""
        rows = tuple(rows)
        empty = self.empty if empty is None else empty
        if rows == self.rows and chosen == self.chosen and empty == self.empty and lit == self.lit:
            return
        before, was, was_lit = self.rows, self.chosen, self.lit
        self.rows, self.chosen, self.empty, self.lit = rows, chosen, empty, lit
        if self._hover is not None and self._hover >= len(rows):
            self._hover = None
        if len(rows) != len(before) or not rows:
            self._strips.clear()
            self.refresh(layout=True)
            return
        changed = {row for row, cells in enumerate(rows) if cells != before[row]}
        if chosen != was:
            changed |= {row for row in (was, chosen) if row is not None}
        self._redraw_rows(changed | (lit ^ was_lit))

    def columns(self) -> tuple[Column, ...]:
        """The table's columns: its class's :data:`COLUMNS`, unless a table
        makes its own (F4's TRACK panel, a column per family the list uses)."""
        return self.COLUMNS

    def mark(self, index: int | None) -> None:
        """The pane cursor on spot ``index`` (``None``: nowhere)."""
        before = self._marked
        self._marked = None if index is None or index >= len(self.spots) else self.spots[index]
        self._redraw_rows({spot[0] for spot in (before, self._marked) if spot is not None})

    def _redraw_rows(self, rows: set[int]) -> None:
        for row in rows:
            self._strips.pop(row + 1, None)
            self.refresh(Region(0, row + 1, self.size.width, 1))

    def lines(self, width: int) -> list[Text]:
        """Every line: the header and the rows, or the empty text."""
        return [self.line(y, width) for y in range(self.get_content_height(Size(), Size(), width))]

    def line(self, y: int, width: int) -> Text:
        """Line ``y``: the header (0), else row ``y - 1``."""
        if not self.rows:
            return self.empty.copy()
        shown = fit(self.columns(), width)
        if y == 0:
            header = Text(style=f"{colors.CYAN} on {colors.BAR}")
            for index, (column, size) in enumerate(shown):
                if index:
                    header.append(" ")
                header.append_text(_sized(Text(column.title), size, column.right))
            header.pad_right(max(0, width - header.cell_len))
            return header
        row = y - 1
        cells = self.rows[row]
        line = Text()
        for index, (column, size) in enumerate(shown):
            if index:
                line.append(" ")
            piece = _sized(cells.get(column.name, Text()), size, column.right)
            if self._marked == (row, column.name):
                piece.stylize(MARKED)
            line.append_text(piece)
        line.pad_right(max(0, width - line.cell_len))
        if self._marked == (row, None):
            line.stylize(MARKED)
        elif row == self._hover or row in self._run():
            line.stylize(f"on {colors.SEL}")
        elif row == self.chosen or row in self.lit:
            line.stylize(f"on {colors.BAR}")
        return line

    def render(self) -> Text:
        """The whole table as one text (what :meth:`render_line` draws)."""
        text = Text("\n").join(self.lines(self.size.width))
        text.no_wrap = True
        return text

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        if width != self._width:
            self._width = width
            self._strips.clear()
        strip = self._strips.get(y)
        if strip is None:
            if y >= self.get_content_height(Size(), Size(), width):
                return Strip.blank(width, self.rich_style)
            text = self.line(y, width)
            text.no_wrap = True
            text.overflow = "crop"
            segments = Strip(text.render(self.app.console), text.cell_len)
            strip = segments.crop_extend(0, width, None).apply_style(self.rich_style)
            self._strips[y] = strip
        return strip

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return len(self.rows) + 1 if self.rows else 1

    def _under(self, event: events.MouseEvent) -> tuple[int | None, str | None]:
        """The row and the column under the mouse (found from where the
        columns are, not from the text: styles with meta cost every draw)."""
        offset = event.get_content_offset(self)
        if offset is None or not 0 < offset.y <= len(self.rows):
            return None, None
        left = 0
        for column, size in fit(self.columns(), self.size.width):
            if left <= offset.x < left + size:
                return offset.y - 1, column.name
            left += size + 1
        return offset.y - 1, None

    def _reach_of(self, event: events.MouseEvent) -> int:
        """The row level with the mouse, during a drag: the first or the last
        while it is above or below the rows."""
        y = event.get_content_offset_capture(self).y - 1
        return max(0, min(len(self.rows) - 1, y))

    def _run(self) -> range:
        """The rows a drag covers now (none while there is no drag)."""
        if self._press is None:
            return range(0)
        start = self._press[0]
        return range(min(start, self._reach), max(start, self._reach) + 1)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._dragged = False
        if not self.DRAGS or event.button != 1:
            return
        row, _ = self._under(event)
        if row is None:
            return
        self._press, self._reach = (row, adds(event)), row
        self.capture_mouse()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._press is None:
            return
        (start, add), end = self._press, self._reach_of(event)
        run = set(self._run())
        self._press = None
        self.release_mouse()
        self._redraw_rows(run)
        if end != start:
            self._dragged = True
            self.post_message(self.Dragged(self, start, end, add))

    def on_click(self, event: events.Click) -> None:
        if self._dragged:  # Textual's click of a drag let go on this table
            self._dragged = False
            event.stop()
            return
        row, name = self._under(event)
        if row is None:
            return
        event.stop()
        self.post_message(self.Clicked(self, row, name, adds(event)))

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._press is not None:
            run = set(self._run())
            self._reach = self._reach_of(event)
            self._redraw_rows(run ^ set(self._run()))
        row, _ = self._under(event)
        if row != self._hover:
            before, self._hover = self._hover, row
            self._redraw_rows({hover for hover in (before, row) if hover is not None})

    def on_leave(self, event: events.Leave) -> None:
        if self._hover is not None:
            before, self._hover = self._hover, None
            self._redraw_rows({before})


def _sized(text: Text, width: int, right: bool) -> Text:
    """``text`` in exactly ``width`` cells: cut with ``…``, padded."""
    piece = text.copy()
    piece.truncate(width, overflow="ellipsis")
    if right:
        return Text(" " * (width - piece.cell_len)) + piece
    piece.pad_right(width - piece.cell_len)
    return piece
