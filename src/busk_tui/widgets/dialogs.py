"""The two dialogs: the engine's question before a line, and quitting.

Both are modal: while one is open, its keys are the only ones.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Static

from busk_tui import colors

type QuitChoice = Literal["save", "quit", "cancel"]

QUIT_CHOICES: dict[str, QuitChoice] = {"save": "save", "quit": "quit", "cancel": "cancel"}


def _css(name: str) -> str:
    return f"""
    {name} {{ align: center middle; background: black 55%; }}
    {name} > Vertical {{
        width: auto; max-width: 80; height: auto; padding: 1 2;
        background: {colors.BG}; border: solid {colors.CYAN};
        border-title-color: {colors.CYAN}; border-title-align: left;
    }}
    {name} .question {{ color: {colors.FG}; width: auto; }}
    {name} .note {{ color: {colors.DIM}; width: auto; }}
    {name} Horizontal {{ height: 1; width: auto; margin-top: 1; }}
    {name} .choice {{ width: auto; margin-right: 2; }}
    {name} .choice:hover {{ background: {colors.SEL}; }}
    """


class Choice(Static):
    """``[k Label]``: a click or its key chooses it."""

    class Chosen(Message):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def __init__(self, key: str, label: str, value: str, color: str) -> None:
        text = Text("[", style=color)
        text.append(key, style=f"bold {color}")
        text.append(f" {label}]", style=color)
        super().__init__(text, classes="choice", id=f"choice-{value}")
        self.value = value

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(self.Chosen(self.value))


class ConfirmDialog(ModalScreen[bool]):
    """The engine's yes/no question before a line; No unless ``y``."""

    DEFAULT_CSS = _css("ConfirmDialog")
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "choose('yes')", "Yes", show=False),
        Binding("n,escape,enter", "choose('no')", "No", show=False),
    ]

    def __init__(self, question: str, line: str) -> None:
        super().__init__()
        self.question = question
        self.line = line

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = "CONFIRM"
            yield Static(self.question, classes="question")
            yield Static(Text(f"busk> {self.line}"), classes="note")
            with Horizontal():
                yield Choice("y", "Yes", "yes", colors.RED)
                yield Choice("n", "No", "no", colors.MID)

    def action_choose(self, value: str) -> None:
        self.dismiss(value == "yes")

    def on_choice_chosen(self, message: Choice.Chosen) -> None:
        self.action_choose(message.value)


class QuitDialog(ModalScreen[QuitChoice]):
    """Save and quit / quit without saving / cancel. ``dirty`` says whether
    there are unsaved edits (without any, it offers Quit and Cancel);
    ``None`` when that is not known."""

    DEFAULT_CSS = _css("QuitDialog")
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("s", "choose('save')", "Save and quit", show=False),
        Binding("q", "choose('quit')", "Quit", show=False),
        Binding("c,escape", "choose('cancel')", "Cancel", show=False),
    ]

    def __init__(self, dirty: bool | None) -> None:
        super().__init__()
        self.dirty = dirty

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = "QUIT"
            if self.dirty:
                yield Static("Quit busk? There are unsaved edits.", classes="question")
            else:
                yield Static("Quit busk?", classes="question")
            if self.dirty is None:
                yield Static("The TUI cannot tell whether there are unsaved edits.", classes="note")
            with Horizontal():
                if self.dirty is not False:
                    yield Choice("s", "Save and quit", "save", colors.GREEN)
                    yield Choice("q", "Quit without saving", "quit", colors.RED)
                else:
                    yield Choice("q", "Quit", "quit", colors.RED)
                yield Choice("c", "Cancel", "cancel", colors.MID)

    def action_choose(self, value: str) -> None:
        if value == "save" and self.dirty is False:
            return
        self.dismiss(QUIT_CHOICES[value])

    def on_choice_chosen(self, message: Choice.Chosen) -> None:
        self.action_choose(message.value)
