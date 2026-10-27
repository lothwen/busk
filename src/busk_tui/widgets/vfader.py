"""The vertical fader (spec §4.3): 10 rows × 4 cells.

Full rows are ``████``, the top partial row ``▁▂▃▄▅▆▇`` four times, and
empty rows ``░░░░`` in the track colour. The fill is the current cue's
colour. It is an :class:`~busk_tui.widgets.bars.HBar` on its side: a click
or a drag sets the level from the y position (the bottom row 0, the top
100 %), the wheel steps it 5 %, a drag's moves go unlogged and keyed, and
the line is logged once, on release.
"""

from __future__ import annotations

from typing import Final

from rich.text import Text
from textual import events

from busk_tui import colors
from busk_tui.widgets.bars import HBar

ROWS: Final = 10
WIDTH: Final = 4
EIGHTHS: Final = " ▁▂▃▄▅▆▇"


def fader_text(level: float, color: str, rows: int = ROWS, width: int = WIDTH) -> Text:
    """``level`` (0..1) as a fader ``rows`` high and ``width`` wide, the top
    row first, quantised to eighths of a row."""
    level = max(0.0, min(1.0, level))
    full, part = divmod(round(level * rows * 8), 8)
    lines = []
    for row in range(rows - 1, -1, -1):  # the top row first
        if row < full:
            lines.append(("█" * width, color))
        elif row == full and part:
            lines.append((EIGHTHS[part] * width, color))
        else:
            lines.append(("░" * width, colors.TRACK))
    text = Text()
    for index, (cells, style) in enumerate(lines):
        if index:
            text.append("\n")
        text.append(cells, style=style)
    return text


class VFader(HBar):
    """A vertical fader (see the module docs)."""

    DEFAULT_CSS = f"VFader {{ width: {WIDTH}; height: {ROWS}; }}"

    def render(self) -> Text:
        return fader_text(
            self.level, self.color, self.size.height or ROWS, self.size.width or WIDTH
        )

    def level_at(self, y: int) -> float:
        """The level a click on row ``y`` sets: 1 at the top row, 0 at the bottom."""
        return max(0.0, min(1.0, 1 - y / max(1, self.size.height - 1)))

    def level_under(self, event: events.MouseEvent) -> float:
        return self.level_at(event.y)
