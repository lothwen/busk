"""The log (spec §5, §7.3): what was run and what the engine said.

Line types and their prefixes: a typed line ``busk> ``, a line a control
ran `` ui> ``, a result (6 spaces), an error `` ✗ ``, an info line `` · ``
(the TUI's messages and the engine's news) and a warning `` ! `` (the
engine's warnings). At most :data:`MAX_LINES` are kept; the view follows the
newest unless scrolled back.
"""

from __future__ import annotations

from collections import deque
from typing import Final, Literal

from rich.text import Text
from textual.widgets import RichLog

from busk_tui import colors

type Kind = Literal["typed", "ui", "result", "error", "info", "warning"]

MAX_LINES: Final = 2000

_PREFIX: Final[dict[Kind, tuple[str, str, str]]] = {
    # kind: (prefix, prefix colour, text colour)
    "typed": ("busk> ", f"bold {colors.GREEN}", colors.FG),
    "ui": (" ui> ", colors.BORDER, colors.DIM),
    "result": ("      ", colors.MID, colors.MID),
    "error": (" ✗ ", colors.RED, colors.RED),
    "info": (" · ", colors.DIM, colors.DIM),
    "warning": (" ! ", colors.AMBER, colors.AMBER),
}


def log_line(kind: Kind, text: str, *, first: bool = True) -> Text:
    """One line of the log; an error's lines after the first are indented
    instead of marked again."""
    prefix, prefix_style, style = _PREFIX[kind]
    line = Text()
    line.append(prefix if first or kind != "error" else " " * len(prefix), style=prefix_style)
    line.append(text, style=style)
    return line


class LogView(RichLog):
    """The log pane; ``entries`` keeps what it shows, for tests."""

    DEFAULT_CSS = f"""
    LogView {{
        height: 7; background: {colors.BG}; scrollbar-size-vertical: 1;
        scrollbar-background: {colors.BG}; scrollbar-color: {colors.BORDER};
        scrollbar-background-hover: {colors.BG}; scrollbar-background-active: {colors.BG};
        border-top: solid {colors.BORDER}; border-title-color: {colors.DIM};
        border-title-align: left; padding: 0 1;
    }}
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(max_lines=MAX_LINES, wrap=False, markup=False, auto_scroll=True, id=id)
        self.can_focus = False
        self.border_title = "LOG"
        self.entries: deque[tuple[Kind, str]] = deque(maxlen=MAX_LINES)

    def add(self, kind: Kind, text: str) -> None:
        for index, line in enumerate(text.splitlines() or [""]):
            self.entries.append((kind, line))
            self.write(log_line(kind, line, first=index == 0))
