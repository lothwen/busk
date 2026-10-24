"""The horizontal bar (spec §4.3): a level as ``█`` cells on a ``░`` track.

The fill is quantised to eighths of a cell (``▏▎▍▌▋▊▉``). A bar with a
``command`` is a control: a click or a drag sets the level from the x
position, the wheel steps it by ``step``. While it is dragged, each move is
sent unlogged and keyed, so the bridge keeps only the newest unsent one, and
the line is logged once, on release (spec §6.2). The wheel's lines are not
logged.
"""

from __future__ import annotations

from collections.abc import Callable

from rich.text import Text
from textual import events
from textual.widget import Widget

from busk_tui import colors
from busk_tui.commands import Line
from busk_tui.model import Origin
from busk_tui.widgets.controls import RunLine

EIGHTHS = " ▏▎▍▌▋▊▉"


def bar_text(level: float, width: int, color: str) -> Text:
    """``level`` (0..1) as a bar ``width`` cells wide."""
    level = max(0.0, min(1.0, level))
    eighths = round(level * width * 8)
    full, part = divmod(eighths, 8)
    text = Text()
    text.append("█" * full, style=color)
    if part:
        text.append(EIGHTHS[part], style=color)
    text.append("░" * (width - full - (1 if part else 0)), style=colors.TRACK)
    return text


class HBar(Widget):
    """A horizontal bar; a control when it has a ``command`` (see the module
    docs). The owner sets the level it shows with :meth:`show_level`, which
    a drag in progress ignores."""

    DEFAULT_CSS = "HBar { height: 1; width: 1fr; }"

    def __init__(
        self,
        level: float = 0.0,
        *,
        color: str = colors.FG,
        command: Callable[[float], Line] | None = None,
        key: str | None = None,
        step: float = 0.05,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.level = level
        self.color = color
        self.command = command
        self.key = key
        self.step = step
        self.dragging = False

    def render(self) -> Text:
        return bar_text(self.level, self.size.width, self.color)

    def show_level(self, level: float) -> None:
        """The level to show, unless a drag is in progress."""
        if not self.dragging and level != self.level:
            self.level = level
            self.refresh()

    def level_at(self, x: int) -> float:
        """The level a click at cell ``x`` sets: 0 at the first cell, 1 at the last."""
        return max(0.0, min(1.0, x / max(1, self.size.width - 1)))

    def _set(self, level: float, origin: Origin) -> None:
        self.level = round(max(0.0, min(1.0, level)), 4)
        self.refresh()
        if self.command is not None:
            self.post_message(RunLine(self.command(self.level), origin, self.key))

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if self.command is None:
            return
        event.stop()
        self.dragging = True
        self.capture_mouse()
        self._set(self.level_at(event.x), "internal")

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self.dragging:
            level = self.level_at(event.x)
            if level != self.level:
                self._set(level, "internal")

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self.dragging:
            event.stop()
            self.dragging = False
            self.release_mouse()
            self._set(self.level_at(event.x), "ui")  # the one line the log shows

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if self.command is not None:
            event.stop()
            self._set(self.level + self.step, "internal")

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        if self.command is not None:
            event.stop()
            self._set(self.level - self.step, "internal")
