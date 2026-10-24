"""The help overlay (spec §8.10): the engine's ``help`` as it is, then the
keys, in a panel over the dimmed pages.

It is a layer over the pages, not a screen of its own, so the prompt keeps
the keyboard while it is open. F10, Alt+0 or ``?`` on an empty prompt open
and close it; a typed ``help`` fills it with its reply; Esc or a click
outside the panel (the app sees those) closes it.
"""

from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from busk_tui import colors

KEYS: tuple[tuple[str, str], ...] = (
    ("F1–F9", "pages (Alt+1–9 over SSH)"),
    ("F10 ?", "this help (Alt+0)"),
    ("esc", "close help, leave the pane, clear"),
    ("enter", "run the line"),
    ("↑ ↓", "earlier and later lines"),
    ("tab", "complete the word"),
    ("tab", "on an empty prompt: into the page"),
    ("ctrl+c", "clear; twice: quit"),
)


def key_grid(keys: Sequence[tuple[str, str]] = KEYS) -> Text:
    text = Text()
    for index, (key, action) in enumerate(keys):
        if index:
            text.append("\n")
        text.append(f"{key:<10}", style=colors.CYAN)
        text.append(action, style=colors.MID)
    return text


class HelpOverlay(VerticalScroll):
    """The help panel, on the layer over the pages (``#upper`` centres it
    there); the app dims the pages while it is open."""

    DEFAULT_CSS = f"""
    HelpOverlay {{
        layer: overlay; display: none;
        width: 110; max-width: 100%; height: auto; max-height: 88%;
        background: {colors.BG}; border: solid {colors.CYAN};
        border-title-color: {colors.CYAN}; border-title-align: left;
        padding: 0 2; scrollbar-size-vertical: 1;
    }}
    HelpOverlay > #help-text {{ color: {colors.MID}; width: auto; }}
    HelpOverlay > #help-keys {{
        border-top: solid {colors.BORDER}; margin-top: 1; width: auto;
    }}
    """

    def __init__(self) -> None:
        super().__init__(id="help")
        self.can_focus = False
        self.border_title = "HELP · esc to close"
        self.text = ""

    def compose(self) -> ComposeResult:
        yield Static("", id="help-text")
        yield Static(key_grid(), id="help-keys")

    @property
    def is_open(self) -> bool:
        return bool(self.display)

    def open(self, lines: Sequence[str]) -> None:
        self.text = "\n".join(lines) if lines else "(the engine has not answered help yet)"
        self.query_one("#help-text", Static).update(Text(self.text))
        self.display = True
        self.scroll_home(animate=False)

    def close(self) -> None:
        self.display = False

    def scroll_page(self, pages: int) -> None:
        if pages > 0:
            self.scroll_page_down(animate=False)
        else:
            self.scroll_page_up(animate=False)
