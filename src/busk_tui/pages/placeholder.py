"""The pages not built yet: each names the phase that builds it and lists
lines to type meanwhile. The pane cursor stops on those lines, and Enter puts
one in the prompt to finish."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static

from busk_tui import colors
from busk_tui.nav import Item
from busk_tui.pages.base import Page

PLANNED: dict[int, tuple[int, tuple[str, ...]]] = {
    # F-key: (the phase that builds it, lines to type meanwhile)
    3: (4, ("list fixtures", "list profiles", "sel fixture ")),
    4: (3, ("list cuelists", "list cues ", "goto ", "record cue ")),
    5: (3, ("list effects", "effect add ", "effect stop ", "effect remove ")),
    8: (4, ("list universes", "list routes", "fixture ")),
    9: (4, ("list surfaces", "list bindings")),
}


class Placeholder(Page):
    """A page to come (see the module docs)."""

    DEFAULT_CSS = f"""
    Placeholder > Static {{
        border: solid {colors.BORDER}; border-title-color: {colors.CYAN};
        border-title-align: left; padding: 0 1; height: auto;
    }}
    """

    def __init__(self, number: int, title: str) -> None:
        super().__init__(number, title)
        self.phase, self.lines = PLANNED[number]
        self._cursor: int | None = None

    def compose(self) -> ComposeResult:
        body = Static(self._text(), id=f"placeholder-{self.number}")
        body.border_title = self.title.upper()
        yield body

    def items(self) -> list[Item]:
        return [Item(line.strip(), prefill=line) for line in self.lines]

    def current_item(self, index: int) -> Item | None:
        items = self.items()
        return items[index] if index < len(items) else None

    def show_cursor(self, index: int | None) -> None:
        self._cursor = index
        self.query_one(Static).update(self._text())

    def _text(self) -> Text:
        text = Text(f"This page comes in Phase {self.phase}. Meanwhile, type at the prompt:\n\n",
                    style=colors.MID)  # fmt: skip
        for index, line in enumerate(self.lines):
            here = index == self._cursor
            text.append("▸ " if here else "  ", style=colors.CYAN)
            text.append(line.rstrip() + ("…" if line.endswith(" ") else ""),
                        style=f"{colors.FG} on {colors.BAR}" if here else colors.FG)  # fmt: skip
            text.append("\n")
        text.append("\nTab on an empty prompt moves here; ↑ ↓ choose a line, Enter puts it in "
                    "the prompt, Esc goes back.", style=colors.DIM)  # fmt: skip
        return text
