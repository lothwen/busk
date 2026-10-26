"""A legend: keys (a glyph and what it means) in a line that wraps between
keys, never inside one (Textual would break a key at its spaces)."""

from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text
from textual.geometry import Size
from textual.widget import Widget

GAP = "   "


class Legend(Widget):
    DEFAULT_CSS = "Legend { height: auto; }"

    def __init__(self, keys: Sequence[Text] = (), *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.keys = tuple(keys)

    def show(self, keys: Sequence[Text]) -> None:
        if tuple(keys) != self.keys:
            self.keys = tuple(keys)
            self.refresh(layout=True)

    def lines(self, width: int) -> list[Text]:
        lines = [Text()]
        for key in self.keys:
            line = lines[-1]
            if line.cell_len and line.cell_len + len(GAP) + key.cell_len > width:
                lines.append(Text())
            elif line.cell_len:
                line.append(GAP)
            lines[-1].append_text(key)
        return lines

    def render(self) -> Text:
        return Text("\n").join(self.lines(self.size.width))

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return len(self.lines(width))
