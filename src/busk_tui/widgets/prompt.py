"""The prompt row and the hint row (spec §5, §7).

The prompt always has the keyboard. It keeps the history (↑ ↓), and offers
each key to the app first (``offer``), in the order the keys were typed: Tab,
Esc, Ctrl+C, the keys that act only on an empty prompt, and those of the pane
cursor.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.widgets import Input, Static

from busk_tui import colors
from busk_tui.hints import Hint


class Prompt(Input):
    """The command line: an input with a history."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "history(-1)", "Earlier line", show=False),
        Binding("down", "history(1)", "Later line", show=False),
    ]

    DEFAULT_CSS = f"""
    Prompt {{
        border: none; height: 1; padding: 0; width: 1fr;
        background: {colors.BAR}; color: {colors.FG};
    }}
    Prompt:focus {{ border: none; background: {colors.BAR}; }}
    Prompt > .input--cursor {{ background: {colors.FG}; color: {colors.BAR}; }}
    Prompt > .input--placeholder {{ color: {colors.DIM}; }}
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(select_on_focus=False, id=id)
        self.offer: Callable[[str], bool] | None = None
        """Called with each key before the prompt handles it; ``True``: it
        was used, and the prompt does nothing with it (see the app)."""
        self.history: list[str] = []
        self._walk: int | None = None  # where ↑ ↓ are in the history
        self._draft = ""  # the line that was being typed before ↑

    async def _on_key(self, event: events.Key) -> None:
        # Textual then runs Input's own _on_key, unless the default is prevented.
        if self.offer is not None and self.offer(event.key):
            event.stop()
            event.prevent_default()

    def remember(self, line: str) -> None:
        """Add a line run from the prompt to the history (not a repeat)."""
        if line and (not self.history or self.history[-1] != line):
            self.history.append(line)
        self._walk = None

    def clear_line(self) -> None:
        self.value = ""
        self._walk = None

    def action_history(self, step: int) -> None:
        if not self.history:
            return
        if self._walk is None:
            if step > 0:
                return
            self._draft = self.value
            walk = len(self.history) - 1
        else:
            walk = self._walk + step
        if walk >= len(self.history):
            self._walk = None
            self.value = self._draft
        else:
            self._walk = max(0, walk)
            self.value = self.history[self._walk]
        self.cursor_position = len(self.value)


class PromptRow(Horizontal):
    """``busk>``, the prompt, and the context on the right."""

    DEFAULT_CSS = f"""
    PromptRow {{ height: 1; background: {colors.BAR}; }}
    PromptRow > #prompt-label {{ width: auto; color: {colors.GREEN}; text-style: bold; }}
    PromptRow > #context {{ width: auto; color: {colors.DIM}; padding: 0 1; }}
    """

    def compose(self) -> ComposeResult:
        yield Static("busk> ", id="prompt-label")
        yield Prompt(id="prompt")
        yield Static("", id="context")


class HintRow(Static):
    """The syntax hint under the prompt (spec §7.2). It changes with every
    key, and is one line whatever it holds: it is drawn again without a
    layout pass (one costs F1 7–8 ms)."""

    DEFAULT_CSS = (
        f"HintRow {{ height: 1; color: {colors.DIM}; text-wrap: nowrap; text-overflow: ellipsis; }}"
    )

    def show(self, hint: Hint) -> None:
        text = Text()
        if hint.expected:
            text.append(hint.expected, style=colors.RED if hint.error else colors.MID)
            if hint.syntax:
                text.append("    ")
        text.append(hint.syntax, style=colors.DIM)
        self.update(text, layout=False)

    def show_text(self, text: str, style: str = colors.AMBER) -> None:
        """A plain message instead (Ctrl+C's, what is under the mouse)."""
        self.update(Text(text, style=style), layout=False)
