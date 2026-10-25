"""Encoder rows (spec §8.2, plan Phase 2 "Encoders").

A row is an attribute as ``set`` names it, ``[−]``, a bar, ``[+]`` and the
value of the first selected element (:mod:`busk_tui.attributes`): magenta
from the programmer, dim from the output, ``—`` with neither.

* The bar sets the value: a click sends ``set pan -45``; a drag sends
  ``set`` lines while it moves, about ten a second, and logs the last one on
  release (question Q7). Each is an undo step of its own until busk can
  group them (GAP-06).
* ``[−]`` ``[+]`` (5 %, 15° for pan and tilt) and the wheel (2 %, 5°)
  send ``set <attribute> by <change>``, which acts only where the
  programmer holds the attribute (question Q11): elsewhere they are inert.
* A click on the attribute's name puts ``set <attribute> `` in the prompt.

What the row sent shows at once, magenta, until busk has run it and the
programmer shows it (the pending value).
"""

from __future__ import annotations

import time
from typing import Final

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.timer import Timer
from textual.widgets import Static

from busk_tui import attributes, colors, commands
from busk_tui.attributes import Encoder, Reading
from busk_tui.commands import Line
from busk_tui.model import Origin
from busk_tui.nav import Item, Stop
from busk_tui.widgets.bars import HBar
from busk_tui.widgets.controls import MARKED, CommandButton, FillPrompt, RunLine

DRAG_S: Final = 0.1
"""A drag sends at most one line this often (question Q7: about 10 Hz)."""

PENDING_S: Final = 1.0
"""A pending value shows at most this long once its line is done."""


class EncoderBar(HBar):
    """The row's bar: it reports where it is set (:class:`Moved`) and the
    wheel's notches (:class:`Stepped`), and the row turns them into lines.
    A click reports once, on release; a drag reports as it moves, at most
    every :data:`DRAG_S`, and then on release."""

    class Moved(Message):
        def __init__(self, bar: EncoderBar, level: float, final: bool) -> None:
            super().__init__()
            self.bar = bar
            self.level = level
            self.final = final

    class Stepped(Message):
        def __init__(self, bar: EncoderBar, up: bool) -> None:
            super().__init__()
            self.bar = bar
            self.up = up

    def __init__(self, color: str) -> None:
        super().__init__(color=color, classes="enc-bar")
        self.settable = False
        self.steps = False
        self._sent_at = 0.0
        self._later: Timer | None = None

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if not self.settable:
            return
        event.stop()
        self.dragging = True
        self.capture_mouse()
        self.level = self.level_at(event.x)
        self._sent_at = time.monotonic()  # a click sends on release only
        self.refresh()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self.dragging:
            return
        level = self.level_at(event.x)
        if level == self.level:
            return
        self.level = level
        self.refresh()
        wait = DRAG_S - (time.monotonic() - self._sent_at)
        if wait <= 0:
            self._report()
        elif self._later is None:
            self._later = self.set_timer(wait, self._report)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if not self.dragging:
            return
        event.stop()
        self._cancel()
        self.dragging = False
        self.release_mouse()
        self.level = self.level_at(event.x)
        self.refresh()
        self.post_message(self.Moved(self, self.level, final=True))

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if self.steps:
            event.stop()
            self.post_message(self.Stepped(self, up=True))

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        if self.steps:
            event.stop()
            self.post_message(self.Stepped(self, up=False))

    def _report(self) -> None:
        self._later = None
        if self.dragging:
            self._sent_at = time.monotonic()
            self.post_message(self.Moved(self, self.level, final=False))

    def _cancel(self) -> None:
        if self._later is not None:
            self._later.stop()
            self._later = None


class EncoderRow(Horizontal):
    """One encoder (see the module docs). The page redraws it with :meth:`show`."""

    DEFAULT_CSS = """
    EncoderRow { height: 1; }
    EncoderRow > .enc-name { width: 11; text-wrap: nowrap; text-overflow: ellipsis; }
    EncoderRow > CommandButton { width: 3; }
    EncoderRow > .enc-bar { width: 1fr; margin: 0 1; }
    EncoderRow > .enc-value { width: 7; text-align: right; }
    """

    def __init__(self, encoder: Encoder) -> None:
        super().__init__()
        self.encoder = encoder
        self.reading: Reading | None = None
        self.version: int | None = None  # the programmer's, as last shown
        self.pending: float | None = None  # the value sent, not yet shown by the programmer
        self.pending_after: tuple[int | None, float] | None = None  # line done: version, when
        self._serial = 0
        self.marked = False
        self.name_text = Static(self._label(), classes="enc-name")
        self.minus = CommandButton("−", Line(""), inert=True)
        self.bar = EncoderBar(encoder.color)
        self.plus = CommandButton("+", Line(""), inert=True)
        self.shown = Text("—", style=colors.DIM)
        self.value = Static(self.shown, classes="enc-value")

    def compose(self) -> ComposeResult:
        yield self.name_text
        yield self.minus
        yield self.bar
        yield self.plus
        yield self.value

    @property
    def prefill(self) -> str:
        return commands.set_prefill(self.encoder.attribute)

    def show(self, reading: Reading, version: int | None) -> None:
        """Draw ``reading``, the programmer being at ``version``."""
        self.version = version
        after = self.pending_after
        if after is not None and (after[0] != version or time.monotonic() - after[1] > PENDING_S):
            self.pending = self.pending_after = None
        self.reading = reading
        self._draw()

    def _draw(self) -> None:
        reading = self.reading
        if reading is None:
            return
        encoder = self.encoder
        self.bar.settable = reading.settable
        self.bar.steps = reading.steps
        down = attributes.step_line(encoder, -encoder.step)
        up = attributes.step_line(encoder, encoder.step)
        self.minus.change(line=down, inert=not reading.steps)
        self.plus.change(line=up, inert=not reading.steps)
        value, source = reading.value, reading.source
        if self.pending is not None:
            value, source = self.pending, "programmer"
        if value is None:
            self.bar.show_level(0.0, colors.TRACK)
            self._show_value(Text("—", style=colors.DIM))
            return
        color = encoder.color if source == "programmer" else f"{encoder.color} dim"
        self.bar.show_level(attributes.to_level(value, reading.span), color)
        text = attributes.number_text(encoder.attribute, value)
        self._show_value(Text(text, style=colors.MAGENTA if source == "programmer" else colors.DIM))

    def _show_value(self, text: Text) -> None:
        if text != self.shown:
            self.shown = text
            self.value.update(text, layout=False)  # a fixed cell: no layout (it moves at 20 Hz)

    def on_encoder_bar_moved(self, message: EncoderBar.Moved) -> None:
        message.stop()
        if self.reading is None:
            return
        value = attributes.to_value(message.level, self.reading.span, self.encoder.unit)
        self._send(
            attributes.set_line(self.encoder, value), "ui" if message.final else "internal", value
        )

    def on_encoder_bar_stepped(self, message: EncoderBar.Stepped) -> None:
        message.stop()
        by = self.encoder.wheel if message.up else -self.encoder.wheel
        self.post_message(RunLine(attributes.step_line(self.encoder, by), "internal"))

    def _send(self, line: Line, origin: Origin, value: float) -> None:
        self._serial += 1
        serial = self._serial
        self.pending, self.pending_after = value, None
        self._draw()

        def done(ok: bool) -> None:
            if serial != self._serial:
                return  # a newer line was sent since
            if ok:
                self.pending_after = (self.version, time.monotonic())
            else:
                self.pending = self.pending_after = None
                self._draw()

        self.post_message(RunLine(line, origin, f"set:{self.encoder.attribute}", done))

    def on_click(self, event: events.Click) -> None:
        if event.widget is self.name_text:
            event.stop()
            self.post_message(FillPrompt(self.prefill))

    def mark(self, index: int | None) -> None:
        self.marked = index is not None
        self.name_text.update(self._label())

    def _label(self) -> Text:
        return Text(self.encoder.attribute, style=MARKED if self.marked else colors.MID)

    def stops(self) -> list[Stop]:
        """The name (Enter: ``set <attribute> ``), ``[−]`` and ``[+]``; a step
        that is inert puts the ``set`` in the prompt instead."""
        stops = [Stop(Item(self.encoder.attribute, prefill=self.prefill), self)]
        for button in (self.minus, self.plus):
            item = (
                Item(button.line.text, prefill=self.prefill)
                if button.inert
                else Item(button.line.text, line=button.line.text)
            )
            stops.append(Stop(item, button))
        return stops
