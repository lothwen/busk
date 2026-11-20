"""The File menu, under the status bar's ``busk ▾`` badge (file-menu plan
Phases 2 and 3): a click on the badge or Alt+F opens it. ↑ ↓ move, Enter or a
click chooses, and Esc, Alt+F or a click outside close it.

It runs nothing: it closes with what was chosen (:data:`FileChoice`), or
``None``, and the app does it.
"""

from __future__ import annotations

from typing import ClassVar, Final, Literal, cast

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from busk_tui import colors

type FileChoice = Literal["new", "open", "open_recent", "save", "save_as", "import_script", "quit"]

ITEMS: Final[tuple[tuple[FileChoice, str, str], ...]] = (
    ("new", "New…", "Ctrl+N"),
    ("open", "Open…", "Ctrl+O"),
    ("open_recent", "Open recent…", ""),
    ("save", "Save", "Ctrl+S"),
    ("save_as", "Save as…", ""),
    ("import_script", "Import script…", ""),
    ("quit", "Quit", "Ctrl+Q"),
)
"""Each item: what it chooses, its label, and the key that does it from the prompt."""

WIDTH: Final = 22
"""An item's label and key, side by side."""


def item_text(label: str, key: str) -> Text:
    """``Save            Ctrl+S``: the label, and its key on the right, dim."""
    text = Text(label, style=colors.FG)
    text.append(" " * (WIDTH - len(label) - len(key)))
    text.append(key, style=colors.DIM)
    return text


class FileMenu(ModalScreen[FileChoice | None]):
    """The menu (see the module docs), at the screen's top left, under the badge."""

    DEFAULT_CSS = f"""
    FileMenu {{ align: left top; }}
    FileMenu > OptionList {{
        width: {WIDTH + 4}; height: auto; margin-top: 1; padding: 0 1;
        background: {colors.BG}; border: solid {colors.CYAN};
        border-title-color: {colors.CYAN}; border-title-align: left;
    }}
    FileMenu > OptionList > .option-list--option-highlighted {{
        background: {colors.SEL}; text-style: none;
    }}
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", "Close", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.menu = OptionList(
            *(Option(item_text(label, key), id=item) for item, label, key in ITEMS)
        )
        self.menu.border_title = "FILE"

    def compose(self) -> ComposeResult:
        yield self.menu

    def on_mount(self) -> None:
        self.menu.highlighted = 0
        self.menu.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(cast(FileChoice, event.option.id))

    def on_click(self, event: events.Click) -> None:
        """A click outside the menu closes it."""
        if event.widget is self:
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
