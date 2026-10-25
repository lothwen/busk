"""The panel (spec §4.3): a single-line border with its title, in cyan
capitals, inset on the top border, and an optional meta after ``·``."""

from __future__ import annotations

from rich.text import Text
from textual.containers import Vertical
from textual.widget import Widget

from busk_tui import colors


class Panel(Vertical):
    DEFAULT_CSS = f"""
    Panel {{
        height: auto; border: solid {colors.BORDER}; padding: 0 1;
        border-title-color: {colors.CYAN}; border-title-align: left;
    }}
    """

    def __init__(
        self,
        title: str,
        *children: Widget,
        meta: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(*children, id=id, classes=classes)
        self.set_title(title, meta)

    def set_title(self, title: str, meta: str | None = None) -> None:
        self.border_title = Text(title.upper() + ("" if meta is None else f" · {meta}"))
