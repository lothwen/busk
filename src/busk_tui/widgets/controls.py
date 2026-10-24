"""Buttons and chips (spec §4.3), and :class:`RunLine`, how every control asks
for a line to be run.

A control never talks to the bridge: it posts :class:`RunLine`, which
bubbles up to the app. The app asks the engine's question first if there is
one (``output off``), echoes the line (``ui>``) unless it is ``internal``,
and sends it.
"""

from __future__ import annotations

from typing import Literal

from rich.text import Text
from textual import events
from textual.message import Message
from textual.widgets import Static

from busk_tui import colors
from busk_tui.commands import Line
from busk_tui.model import Origin

type Intent = Literal["go", "neutral", "record", "tempo", "danger"]

INTENT_COLORS: dict[Intent, str] = {
    "go": colors.GREEN,
    "neutral": colors.MID,
    "record": colors.MAGENTA,
    "tempo": colors.AMBER,
    "danger": colors.RED,
}


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
    """``[LABEL]`` in its intent's colour; a click runs its line."""

    DEFAULT_CSS = """
    CommandButton { width: auto; height: 1; }
    CommandButton:hover { background: #303030; }
    """

    def __init__(
        self, label: str, line: Line, intent: Intent = "neutral", *, id: str | None = None
    ) -> None:
        super().__init__(Text(f"[{label}]", style=INTENT_COLORS[intent]), id=id)
        self.line = line

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(RunLine(self.line))


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
