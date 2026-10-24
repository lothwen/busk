"""The colour swatch (spec §4.3): ``███`` in a fixture's or a preset's colour."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from busk_tui import colors


def swatch_text(color: str | None, width: int = 3) -> Text:
    """``width`` full blocks in ``color`` (a Rich colour); unlit when ``None``."""
    return Text("█" * width, style=f"color({colors.UNLIT})" if color is None else color)


class Swatch(Static):
    DEFAULT_CSS = "Swatch { width: auto; height: 1; }"

    def __init__(self, color: str | None = None, width: int = 3, *, id: str | None = None) -> None:
        super().__init__(swatch_text(color, width), id=id)
        self.width = width

    def show(self, color: str | None) -> None:
        self.update(swatch_text(color, self.width))
