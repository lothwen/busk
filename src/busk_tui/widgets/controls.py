"""Buttons and chips (spec §4.3), and :class:`RunLine`, how every control asks
for a line to be run.

A control never talks to the bridge: it posts :class:`RunLine`, which
bubbles up to the app. The app asks the engine's question first if there is
one (``output off``), echoes the line (``ui>``) unless it is ``internal``,
and sends it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from rich.text import Text
from textual import events
from textual.message import Message
from textual.widgets import Static

from busk_tui import colors
from busk_tui.commands import Line
from busk_tui.model import Origin

type Intent = Literal["go", "neutral", "record", "tempo", "danger", "off"]

INTENT_COLORS: dict[Intent, str] = {
    "go": colors.GREEN,
    "neutral": colors.MID,
    "record": colors.MAGENTA,
    "tempo": colors.AMBER,
    "danger": colors.RED,
    "off": colors.DIM,
}

MARKED = f"bold {colors.BG} on {colors.CYAN}"
"""The pane cursor on a control (cyan: the UI's focus)."""

NBSP = "\u00a0"  # keeps a label together where a row of buttons wraps


class RunLine(Message):
    """Run ``line``. ``origin`` ``ui`` echoes it, ``internal`` does not (a
    drag's moves, the wheel). With a ``key``, a newer line with the same key
    replaces this one if it has not been sent yet."""

    def __init__(self, line: Line, origin: Origin = "ui", key: str | None = None) -> None:
        super().__init__()
        self.line = line
        self.origin: Origin = origin
        self.key = key


class CommandButton(Static):
    """``[LABEL]`` in its intent's colour, or reversed (a lit toggle, TAP);
    a click runs its line. The owner changes it with :meth:`change`."""

    DEFAULT_CSS = """
    CommandButton { width: auto; height: 1; }
    CommandButton:hover { background: #303030; }
    """

    def __init__(
        self,
        label: str,
        line: Line,
        intent: Intent = "neutral",
        *,
        reverse: bool = False,
        dim: bool = False,
        id: str | None = None,
    ) -> None:
        self.label = label
        self.line = line
        self.intent: Intent = intent
        self.reverse = reverse
        self.dim = dim
        self.marked = False
        super().__init__(self._text(), id=id)

    def change(
        self,
        label: str | None = None,
        line: Line | None = None,
        intent: Intent | None = None,
        *,
        reverse: bool | None = None,
        dim: bool | None = None,
    ) -> None:
        """A new label, line, intent or look; redrawn only if it shows differently."""
        before = self._text()
        self.label = self.label if label is None else label
        self.line = self.line if line is None else line
        self.intent = self.intent if intent is None else intent
        self.reverse = self.reverse if reverse is None else reverse
        self.dim = self.dim if dim is None else dim
        if self._text() != before:
            self.update(self._text())

    def mark(self, index: int | None) -> None:
        """Draw the pane cursor on it (any ``index``), or not (``None``)."""
        self.marked = index is not None
        self.update(self._text())

    def _text(self) -> Text:
        color = INTENT_COLORS[self.intent]
        if self.marked:
            style = MARKED
        elif self.reverse:
            style = f"bold {colors.BG} on {color}"
        else:
            style = f"{color} dim" if self.dim else color
        return Text(f"[{self.label}]", style=style)

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(RunLine(self.line))


@dataclass(frozen=True, slots=True)
class StripButton:
    """One button of a :class:`ButtonStrip`: its label as drawn, its line,
    and the line a Shift-click runs instead (``None``: the same)."""

    label: Text
    line: Line
    shift: Line | None = None


class ButtonStrip(Static):
    """A row of buttons that wraps; a click runs the line of the button
    under the mouse, or its ``shift`` line on a Shift-click."""

    DEFAULT_CSS = "ButtonStrip { height: auto; }"

    def __init__(self, buttons: Sequence[StripButton] = (), *, id: str | None = None) -> None:
        self.buttons = tuple(buttons)
        self._hover: int | None = None
        self._marked: int | None = None
        super().__init__(self._text(), id=id)

    def show(self, buttons: Sequence[StripButton]) -> None:
        if tuple(buttons) != self.buttons:
            self.buttons = tuple(buttons)
            self._hover = self._marked = None
            self.update(self._text())

    def mark(self, index: int | None) -> None:
        self._marked = index
        self.update(self._text())

    def _text(self) -> Text:
        text = Text()
        for index, button in enumerate(self.buttons):
            if index:
                text.append(" ")
            label = button.label.copy()
            if index == self._marked:
                label.stylize(MARKED)
            elif index == self._hover:
                label.stylize(f"on {colors.SEL}")
            label.apply_meta({"button": index})
            text.append_text(label)
        return text

    def _under(self, event: events.MouseEvent) -> int | None:
        index = event.style.meta.get("button")
        return index if isinstance(index, int) and index < len(self.buttons) else None

    def on_click(self, event: events.Click) -> None:
        index = self._under(event)
        if index is None:
            return
        event.stop()
        button = self.buttons[index]
        line = button.shift if event.shift and button.shift is not None else button.line
        self.post_message(RunLine(line))

    def on_mouse_move(self, event: events.MouseMove) -> None:
        index = self._under(event)
        if index != self._hover:
            self._hover = index
            self.update(self._text())

    def on_leave(self, event: events.Leave) -> None:
        if self._hover is not None:
            self._hover = None
            self.update(self._text())


def button_label(label: str, color: str) -> Text:
    """``[label]`` for a :class:`StripButton`, kept in one piece."""
    return Text(f"[{label.replace(' ', NBSP)}]", style=color)


def chip(label: str, on: bool, color: str) -> Text:
    """A status chip: off, the label in the border colour on no background;
    on, the background in ``color`` and the label in the screen's."""
    if on:
        return Text(f" {label} ", style=f"bold {colors.BG} on {color}")
    return Text(f" {label} ", style=colors.BORDER)


class Chip(Static):
    """A status chip widget (see :func:`chip`)."""

    DEFAULT_CSS = "Chip { width: auto; height: 1; }"

    def __init__(self, label: str, color: str, *, on: bool = False, id: str | None = None) -> None:
        super().__init__(chip(label, on, color), id=id)
        self.label = label
        self.color = color
        self.on = on

    def show(self, on: bool) -> None:
        if on != self.on:
            self.on = on
            self.update(chip(self.label, on, self.color))
