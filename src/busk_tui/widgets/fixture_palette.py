"""Fixtures in their live output, shared by layout A's OUTPUT and layout C's
STAGE (spec §4.3 "Fixture swatch", §8.1).

A fixture is drawn as cells in its output colour at its intensity
(:func:`element_cells`): one glyph for a fixture of one element (``███`` in
OUTPUT, its type's glyph on the stage), one ``█`` per element for the
others. Its number is under it, cyan while it is selected, and the
selected fixture has the selection's background.

:class:`FixturePalette` is the widget both draw in. A subclass lays its
fixtures out for a width (:meth:`FixturePalette.draw`): the lines, and
where each fixture is (:class:`Spot`). The widget draws line by line, and
only the lines that changed are drawn again (the output changes ten times a
second while something moves). A click selects the fixture under the mouse
(``sel fixture 101``); a Shift-click adds it to the selection or takes it
out (``sel + fixture 101``, ``sel - fixture 101``). The pane cursor stops on
each fixture.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from rich.text import Text
from textual import events
from textual.geometry import Region, Size
from textual.strip import Strip
from textual.widget import Widget

from busk_tui import colors, commands
from busk_tui.colors import ColorMode
from busk_tui.commands import Line
from busk_tui.model import ElementOutput
from busk_tui.nav import Item, Stop
from busk_tui.widgets.controls import MARKED, RunLine

WHITE: Final = (1.0, 1.0, 1.0)
UNLIT: Final = f"color({colors.UNLIT})"

UNSIZED: Final = 100
"""The width a palette is laid out at before it has one of its own (in a
layout not shown yet), so that the pane cursor finds its fixtures, in
their order, at once."""


def element_cells(
    outputs: Sequence[ElementOutput], elements: int, glyph: str, cap: int, mode: ColorMode
) -> list[tuple[str, str]]:
    """A fixture of ``elements`` elements as cells, each ``(text, colour)``:
    ``glyph`` for one element, else one ``█`` per element, ``cap`` at most
    (evenly spaced beyond). An element without colour is white light; one
    with no output read yet is unlit."""
    if elements <= 1:
        out = outputs[0] if outputs else None
        return [(glyph, UNLIT if out is None else _color(out, mode))]
    shown = max(1, min(elements, cap))
    cells = []
    for index in range(shown):
        element = index * elements // shown
        out = outputs[element] if element < len(outputs) else None
        cells.append(("█", UNLIT if out is None else _color(out, mode)))
    return cells


def _color(out: ElementOutput, mode: ColorMode) -> str:
    return colors.swatch(out.color or WHITE, out.intensity, mode)


def select_line(number: int, shift: bool, selected: bool) -> Line:
    """A click on fixture ``number``: ``sel fixture N``; a Shift-click, ``sel
    + fixture N``, or ``sel - fixture N`` while it is selected."""
    if shift:
        return commands.sel_fixture(number, add=not selected, remove=selected)
    return commands.sel_fixture(number)


@dataclass(frozen=True, slots=True)
class Spot:
    """Where fixture ``number`` is drawn: ``height`` lines from line ``y``,
    ``width`` cells from cell ``x``."""

    number: int
    y: int
    x: int
    width: int
    height: int

    def holds(self, x: int, y: int) -> bool:
        return self.y <= y < self.y + self.height and self.x <= x < self.x + self.width


def centred(text: str, width: int) -> str:
    """``text`` centred in ``width`` cells (cut at ``width``)."""
    text = text[:width]
    left = (width - len(text)) // 2
    return " " * left + text + " " * (width - len(text) - left)


class FixturePalette(Widget):
    """Fixtures drawn by a subclass's :meth:`draw` (see the module docs)."""

    DEFAULT_CSS = "FixturePalette { height: auto; }"

    def __init__(self, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self.selected: frozenset[int] = frozenset()  # the fixtures with an element selected
        self.lines: list[Text] = []
        self.spots: list[Spot] = []
        self._width = 0
        self._hover: int | None = None  # a spot index
        self._marked: int | None = None
        self._strips: dict[int, Strip] = {}

    def draw(self, width: int) -> tuple[list[Text], list[Spot]]:
        """The lines in ``width`` cells, and where each fixture is."""
        return [], []

    def redraw(self) -> None:
        """Lay the fixtures out again (they or their output changed), and
        draw the lines that changed."""
        width = self.size.width or self._width or UNSIZED
        lines, spots = self.draw(width)
        before = self.lines
        moved = spots != self.spots
        self.lines, self.spots = lines, spots
        if moved:
            self._hover = None
        if len(lines) != len(before) or width != self._width:
            self._width = width
            self._strips.clear()
            self.refresh(layout=True)
            return
        if moved:
            self._strips.clear()
            self.refresh()
            return
        self._redraw_lines({y for y, line in enumerate(lines) if line != before[y]})

    def on_resize(self, event: events.Resize) -> None:
        self.redraw()

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        if width != self._width:
            self.lines, self.spots = self.draw(width)
            self._width = width
            self._strips.clear()
        return max(1, len(self.lines))

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        strip = self._strips.get(y)
        if strip is None:
            if y >= len(self.lines):
                return Strip.blank(width, self.rich_style)
            text = self.lines[y].copy()
            for index, style in ((self._hover, f"on {colors.SEL}"), (self._marked, MARKED)):
                if index is not None and index < len(self.spots):
                    spot = self.spots[index]
                    if spot.y <= y < spot.y + spot.height:
                        text.stylize(style, spot.x, spot.x + spot.width)
            text.no_wrap = True
            text.overflow = "crop"
            strip = Strip(text.render(self.app.console), text.cell_len)
            strip = strip.crop_extend(0, width, None).apply_style(self.rich_style)
            self._strips[y] = strip
        return strip

    def _redraw_lines(self, lines: set[int]) -> None:
        for y in lines:
            self._strips.pop(y, None)
            self.refresh(Region(0, y, self.size.width, 1))

    def _redraw_spot(self, index: int | None) -> None:
        if index is not None and index < len(self.spots):
            spot = self.spots[index]
            self._redraw_lines(set(range(spot.y, spot.y + spot.height)))

    def _under(self, event: events.MouseEvent) -> int | None:
        offset = event.get_content_offset(self)
        if offset is None:
            return None
        return next(
            (i for i, spot in enumerate(self.spots) if spot.holds(offset.x, offset.y)), None
        )

    def on_click(self, event: events.Click) -> None:
        index = self._under(event)
        if index is None:
            return
        event.stop()
        number = self.spots[index].number
        self.post_message(RunLine(select_line(number, event.shift, number in self.selected)))

    def on_mouse_move(self, event: events.MouseMove) -> None:
        index = self._under(event)
        if index != self._hover:
            before, self._hover = self._hover, index
            self._redraw_spot(before)
            self._redraw_spot(index)

    def on_leave(self, event: events.Leave) -> None:
        if self._hover is not None:
            before, self._hover = self._hover, None
            self._redraw_spot(before)

    def mark(self, index: int | None) -> None:
        """The pane cursor on spot ``index`` (``None``: nowhere)."""
        before, self._marked = self._marked, index
        self._redraw_spot(before)
        self._redraw_spot(index)

    def stops(self) -> list[Stop]:
        """The pane cursor's stops: each fixture, which Enter selects."""
        return [
            Stop(
                Item(f"fixture {spot.number}", line=commands.sel_fixture(spot.number).text),
                self,
                index,
            )
            for index, spot in enumerate(self.spots)
        ]
