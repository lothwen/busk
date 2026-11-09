"""The dialogs: a question before a line (the engine's, or the TUI's own),
quitting, a line of text to type (a name, a number), and a form of several
(:class:`FormDialog`); and the checks and steps of the names and numbers
typed in them.

All are modal: while one is open, its keys are the only ones.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Collection, Sequence
from typing import ClassVar, Final, Literal

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from busk_tui import colors

type QuitChoice = Literal["save", "quit", "cancel"]

QUIT_CHOICES: dict[str, QuitChoice] = {"save": "save", "quit": "quit", "cancel": "cancel"}

MAX_DIGITS: Final = 300
"""The most digits busk reads in a row, past which it refuses a line."""

CUE_NUMBER: Final = re.compile(rf"[0-9]{{1,{MAX_DIGITS}}}(?:\.[0-9]{{1,{MAX_DIGITS}}})?")
"""A cue number as busk reads one: ``3``, ``2.5``."""


def check_name(renaming: bool) -> Callable[[str], str | None]:
    """A name dialog's check: not empty when renaming."""

    def check(text: str) -> str | None:
        if renaming and not text.strip():
            return "a name cannot be empty"
        return None

    return check


def check_number(taken: Collection[int], own: int | None) -> Callable[[str], str | None]:
    """A number dialog's check: a whole number from 1, not one of ``taken``
    (``own``, the number it has now, may stay)."""

    def check(text: str) -> str | None:
        number = read_whole(text.strip())
        if number is None or number < 1:
            return "a whole number from 1"
        if number != own and number in taken:
            return f"{number} is taken"
        return None

    return check


def cue_key(text: str) -> tuple[int, ...] | None:
    """A cue number as busk compares them (``02.5`` is ``2.5``, and ``2.50``
    is another cue); ``None`` if it is not one."""
    if CUE_NUMBER.fullmatch(text) is None:
        return None
    return tuple(int(part) for part in text.split("."))


def check_cue(taken: Collection[str]) -> Callable[[str], str | None]:
    """A cue number dialog's check: a cue number that none of ``taken`` is."""
    keys = {cue_key(number) for number in taken}

    def check(text: str) -> str | None:
        number = text.strip()
        key = cue_key(number)
        if key is None:
            return "a cue number, such as 3 or 2.5"
        return f"cue {number} exists" if key in keys else None

    return check


def next_cue(taken: Sequence[str]) -> str:
    """What a new cue starts at: as busk's ``record cue L``, the next whole
    number after the last of ``taken`` (in cue order), else 1."""
    return str(int(taken[-1].split(".")[0]) + 1) if taken else "1"


def read_whole(text: str) -> int | None:
    """A whole number as typed, with no sign; ``None`` if it is not one. It
    keeps from ``int`` what would raise there: ``²``, which ``isdigit`` takes,
    and a paste past 4,300 digits."""
    return int(text) if text.isdecimal() and len(text) <= MAX_DIGITS else None


def read_number(text: str) -> float | None:
    """A number as typed, of any sign, with decimals; ``None`` if it is not
    one (``float`` also reads ``nan`` and ``inf``, which busk has no use for)."""
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def free_step(number: int, by: int, taken: Collection[int]) -> int:
    """The next free number from ``number`` in the direction of ``by``,
    at least 1; ``number`` itself when there is none below."""
    found = number + by
    while found in taken:
        found += by
    return found if found >= 1 else number


def next_number(taken: Collection[int]) -> int:
    """What a new one starts at: the highest number plus one, else 1."""
    return max(taken, default=0) + 1


def dialog_css(name: str) -> str:
    return f"""
    {name} {{ align: center middle; background: black 55%; }}
    {name} > Vertical {{
        width: auto; max-width: 80; height: auto; padding: 1 2;
        background: {colors.BG}; border: solid {colors.CYAN};
        border-title-color: {colors.CYAN}; border-title-align: left;
    }}
    {name} .question {{ color: {colors.FG}; width: auto; max-width: 74; }}
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
    """A yes/no question before a line, the engine's or the TUI's own; No
    unless ``y``."""

    DEFAULT_CSS = dialog_css("ConfirmDialog")
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
            yield Static(Text(self.question), classes="question")  # names in it are not markup
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

    DEFAULT_CSS = dialog_css("QuitDialog")
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


class TextDialog(ModalScreen[str | None]):
    """A line of text to type, under ``title`` and a ``note``: Enter runs
    ``check`` on it, which returns what is wrong with it (shown, and the
    dialog stays) or ``None`` (the dialog closes with the text); Esc
    cancels (``None``)."""

    DEFAULT_CSS = (
        dialog_css("TextDialog")
        + f"""
    TextDialog > Vertical {{ width: 60; }}
    TextDialog Input {{ width: 100%; margin-top: 1; }}
    TextDialog .error {{ color: {colors.RED}; width: 100%; height: auto; }}
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self, title: str, value: str, check: Callable[[str], str | None], note: str = ""
    ) -> None:
        super().__init__()
        self.title_text = title
        self.initial = value
        self.check = check
        self.note = note
        self.error = Static("", classes="error")

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = self.title_text
            if self.note:
                yield Static(self.note, classes="note")
            yield Input(self.initial)
            yield self.error
            yield Static("Enter: OK · Esc: cancel", classes="note")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        problem = self.check(event.value)
        if problem is None:
            self.dismiss(event.value)
        else:
            self.error.update(problem)

    def action_cancel(self) -> None:
        self.dismiss(None)


class FormDialog(ModalScreen[tuple[str, ...] | None]):
    """Several lines of text to type, under ``title`` and a ``note``: each of
    ``fields`` is a label and what its input starts at. Tab moves between
    them. Enter, in any of them, runs ``check`` on all the values, which
    returns what is wrong with them (shown, and the dialog stays) or ``None``
    (the dialog closes with the values, in order); Esc cancels (``None``)."""

    DEFAULT_CSS = (
        dialog_css("FormDialog")
        + f"""
    FormDialog > Vertical {{ width: 60; }}
    FormDialog Horizontal {{ width: 100%; margin-top: 0; }}
    FormDialog .lead {{ margin-bottom: 1; }}
    FormDialog .label {{ color: {colors.MID}; width: auto; }}
    FormDialog Input {{ width: 1fr; }}
    FormDialog .error {{ color: {colors.RED}; width: 100%; height: auto; }}
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        title: str,
        fields: Sequence[tuple[str, str]],
        check: Callable[[tuple[str, ...]], str | None],
        note: str = "",
    ) -> None:
        super().__init__()
        self.title_text = title
        self.labels = tuple(label for label, _ in fields)
        self.inputs = tuple(Input(value, compact=True) for _, value in fields)
        self.check = check
        self.note = note
        self.error = Static("", classes="error")

    def compose(self) -> ComposeResult:
        width = max(len(label) for label in self.labels) + 1
        with Vertical() as box:
            box.border_title = self.title_text
            if self.note:
                yield Static(self.note, classes="note lead")
            for label, field in zip(self.labels, self.inputs, strict=True):
                with Horizontal():
                    yield Static(Text(f"{label:<{width}}"), classes="label")
                    yield field
            yield self.error
            yield Static("Tab: next · Enter: OK · Esc: cancel", classes="note")

    def on_mount(self) -> None:
        self.inputs[0].focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        values = tuple(field.value for field in self.inputs)
        problem = self.check(values)
        if problem is None:
            self.dismiss(values)
        else:
            self.error.update(problem)

    def action_cancel(self) -> None:
        self.dismiss(None)
