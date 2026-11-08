"""The log (spec §5, §7.3): what was run and what the engine said.

Line types and their prefixes: a typed line ``busk> ``, a line a control
ran `` ui> ``, a result (6 spaces), an error `` ✗ ``, an info line `` · ``
(the TUI's messages and the engine's news) and a warning `` ! `` (the
engine's warnings). A line wider than the pane wraps at its words, the later
rows under the text and not the prefix, and a resize flows what is kept again.
At most :data:`MAX_LINES` are kept; the view follows the newest unless
scrolled back.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Final, Literal

from rich.console import Console
from rich.text import Text
from textual.events import Resize
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


def log_rows(
    console: Console, kind: Kind, text: str, width: int, *, first: bool = True
) -> list[Text]:
    """:func:`log_line` as rows of ``width`` cells, wrapped at the words (a
    word wider than a row folds): the rows after the first start under the
    text."""
    prefix, _, style = _PREFIX[kind]
    head, *rest = Text(text).wrap(console, max(1, width - len(prefix)))
    return [
        log_line(kind, head.plain, first=first),
        *(Text(" " * len(prefix) + row.plain, style=style) for row in rest),
    ]


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
        self._firsts: deque[bool] = deque(maxlen=MAX_LINES)  # alongside entries
        self._flow_width = 0  # what the rows are wrapped to; 0 until the pane has a width

    def add(self, kind: Kind, text: str) -> None:
        added = [((kind, line), i == 0) for i, line in enumerate(text.splitlines() or [""])]
        for entry, first in added:
            self.entries.append(entry)
            self._firsts.append(first)
        self._write_rows(added)

    def on_resize(self, event: Resize) -> None:
        """Flow what is kept again at a new width (the first one writes it all)."""
        super().on_resize(event)
        width = self.scrollable_content_region.width
        if width != self._flow_width:
            self._flow_width = width
            self.clear()
            self._write_rows(zip(self.entries, self._firsts, strict=True))

    def _write_rows(self, lines: Iterable[tuple[tuple[Kind, str], bool]]) -> None:
        """``lines`` (each an entry and whether it is a line's first), as one
        write, which keeps a reflow of a full log short. Nothing until the
        pane has a width."""
        width = self._flow_width
        if not width:
            return
        rows = Text("\n").join(
            row
            for (kind, line), first in lines
            for row in log_rows(self.app.console, kind, line, width, first=first)
        )
        if rows:
            self.write(rows, width=width)
