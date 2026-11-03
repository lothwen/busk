"""Spread rows of F6's PRESET panel (``docs/plans/tui-presets-plan.md`` §5.6,
question Q5): a fan over the selection, ``set pan spread -30 30``.

* A section's :class:`SpreadLine` reads ``spread [pan] [tilt] …``, a toggle
  per row that takes a spread (every row but a colour's component). It
  sends nothing: a row toggled on shows as a :class:`SpreadRow`.
* A :class:`SpreadRow` has two bars, ``from`` (the first selected element)
  and ``to`` (the last), and ``[centre]`` and ``[edges]``, which mirror the
  fan: ``center`` puts ``to`` in the middle and ``from`` at the ends,
  ``edges`` the other way round. A bar, a step or a curve sends the whole
  spread, ``set pan spread -30 30 center``; a drag sends about ten a second
  and logs the last, as an encoder's bar does.

busk keeps no spread, only the value it gave each element, so the row
reads its ends back from the programmer's values (or dim, the output's):
:func:`busk_tui.attributes.spread_reading`. Where those cannot tell the ends
(two elements and ``center``: both are ``from``), the row shows the spread
it last sent, as long as the programmer still holds what that gave. As on
an encoder, ``[−]`` ``[+]`` and the wheel act only where the programmer
holds the attribute; they move one end and send the spread again.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Collection, Sequence
from functools import partial
from typing import Final

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from busk_tui import attributes, colors, commands
from busk_tui.attributes import Curve, Encoder, Selected, SpreadReading
from busk_tui.commands import Line
from busk_tui.model import Origin, OutputModel, ProgrammerModel, ShowModel
from busk_tui.nav import Item, Stop
from busk_tui.widgets.controls import ActionButton, ButtonStrip, RunLine, StripButton
from busk_tui.widgets.encoders import PENDING_S, EncoderBar
from busk_tui.widgets.options import LIT
from busk_tui.widgets.quick import strip_stops

NAME_WIDTH: Final = 16
"""The name column, as the panel's encoder and option rows have it."""

CURVES: Final[tuple[tuple[Curve, str, str], ...]] = (
    ("center", "centre", "mirrored: from at both ends, to in the middle"),
    ("edges", "edges", "mirrored: to at both ends, from in the middle"),
)
"""busk's word for each mirrored curve, its button's label, and what the
mouse on the button shows in the hint row."""

type Ends = tuple[float, float]


def end_label(attribute: str, end: int) -> Text:
    """An end's name, a cell short of the name column, as an encoder's
    leaves a gap before ``[−]``: ``pan        from``, then ``to`` under it."""
    if end == 0:
        name = attribute if len(attribute) <= 10 else attribute[:9] + "…"
        text = Text(f"{name:<10}", style=colors.MID)
        text.append(" from", style=colors.DIM)
        return text
    return Text(f"{'to':>{NAME_WIDTH - 1}}", style=colors.DIM)


def as_sent(value: float, encoder: Encoder) -> float:
    """``value`` as busk reads it back from the line: a level to whole
    percent (0..1), any other number to two decimals."""
    if encoder.unit == "level":
        return round(max(0.0, min(1.0, value)) * 100) / 100
    return round(value, 2)


def spread_line(encoder: Encoder, ends: Ends, curve: Curve | None) -> Line:
    return commands.set_spread(
        encoder.attribute, ends[0], ends[1], curve, level=encoder.unit == "level"
    )


def toggle_label(attribute: str, on: bool) -> Text:
    """A toggle's label, lit (reversed, as the programmer's option) while
    on: the style is a span, so a chip lit or not compares different."""
    label = Text()
    label.append(f"[{attribute}]", style=LIT if on else colors.MID)
    return label


class SpreadLine(Horizontal):
    """``spread`` and a toggle per row of the section that takes one (see
    the module docs). ``toggle`` is the panel's, called with the attribute."""

    DEFAULT_CSS = f"""
    SpreadLine {{ height: auto; }}
    SpreadLine > .sp-word {{ width: {NAME_WIDTH}; color: {colors.DIM}; }}
    SpreadLine > ButtonStrip {{ width: 1fr; }}
    """

    def __init__(self, names: Sequence[str], toggle: Callable[[str], None]) -> None:
        super().__init__()
        self.names = tuple(names)
        self.actions = {name: partial(toggle, name) for name in self.names}  # one per button
        self.chips = ButtonStrip()

    def compose(self) -> ComposeResult:
        yield Static("spread", classes="sp-word")
        yield self.chips

    def show(self, on: Collection[str]) -> None:
        """Light the toggles of the rows that show as spreads."""
        self.chips.show(
            [
                StripButton(toggle_label(name, name in on), Line(""), action=self.actions[name])
                for name in self.names
            ]
        )

    def stops(self) -> list[Stop]:
        return strip_stops(self.chips)


class SpreadEnd(Horizontal):
    """One end of a :class:`SpreadRow`: its name, ``[−]``, a bar, ``[+]``
    and its value, as an encoder row draws them."""

    DEFAULT_CSS = f"""
    SpreadEnd {{ height: 1; }}
    SpreadEnd > .enc-name {{ width: {NAME_WIDTH}; text-wrap: nowrap; }}
    SpreadEnd > ActionButton {{ width: 3; }}
    SpreadEnd > .enc-bar {{ width: 1fr; margin: 0 1; }}
    SpreadEnd > .enc-value {{ width: 7; text-align: right; }}
    """

    def __init__(
        self, label: Text, bar: EncoderBar, minus: Callable[[], None], plus: Callable[[], None]
    ) -> None:
        super().__init__()
        self.name_text = Static(label, classes="enc-name")
        self.minus = ActionButton("−", minus, inert=True)
        self.bar = bar
        self.plus = ActionButton("+", plus, inert=True)
        self.shown = Text("—", style=colors.DIM)
        self.value = Static(self.shown, classes="enc-value")

    def compose(self) -> ComposeResult:
        yield self.name_text
        yield self.minus
        yield self.bar
        yield self.plus
        yield self.value

    def show_value(self, text: Text) -> None:
        if text != self.shown:
            self.shown = text
            self.value.update(text, layout=False)  # a fixed cell: no layout


class SpreadRow(Vertical):
    """One attribute as a spread (see the module docs). The panel redraws
    it with :meth:`show`; it reads the spread for its own :attr:`curve`."""

    DEFAULT_CSS = f"""
    SpreadRow {{ height: auto; }}
    SpreadRow > .sp-curves {{ height: 1; padding-left: {NAME_WIDTH}; }}
    SpreadRow > .sp-curves > ActionButton {{ margin-right: 1; }}
    """

    def __init__(self, encoder: Encoder) -> None:
        super().__init__()
        self.encoder = encoder
        self.curve: Curve | None = None
        self.reading: SpreadReading | None = None
        self.version: int | None = None  # the programmer's, as last shown
        self.pending: Ends | None = None  # sent, not yet shown by the programmer
        self.pending_after: tuple[int | None, float] | None = None  # line done: version, when
        self.sent: tuple[float, float, Curve | None] | None = None  # the last spread done
        self._seen: (
            tuple[ShowModel | None, Selected, ProgrammerModel | None, OutputModel | None] | None
        ) = None
        self._serial = 0
        signed = encoder.unit == "degps"
        self.bars = (
            EncoderBar(encoder.color, signed=signed),
            EncoderBar(encoder.color, signed=signed),
        )
        self.ends = tuple(
            SpreadEnd(
                end_label(encoder.attribute, end),
                self.bars[end],
                partial(self.step, end, -encoder.step),
                partial(self.step, end, encoder.step),
            )
            for end in (0, 1)
        )
        self.curves = {
            curve: ActionButton(label, partial(self.set_curve, curve), hint=hint)
            for curve, label, hint in CURVES
        }

    def compose(self) -> ComposeResult:
        yield from self.ends
        yield Horizontal(*self.curves.values(), classes="sp-curves")

    def show(
        self,
        show: ShowModel | None,
        chosen: Selected,
        programmer: ProgrammerModel | None,
        output: OutputModel | None,
    ) -> None:
        """Draw the spread the programmer (else the output) holds on the
        selection, read for the row's curve."""
        self._seen = (show, chosen, programmer, output)
        version = None if programmer is None else programmer.version
        self.version = version
        after = self.pending_after
        if after is not None and (after[0] != version or time.monotonic() - after[1] > PENDING_S):
            self.pending = self.pending_after = None
        self.reading = attributes.spread_reading(self.encoder, *self._seen, self.curve)
        self._draw()

    def shown_ends(self) -> tuple[Ends | None, attributes.Source | None]:
        """The ends drawn, and where they come from: what was just sent,
        else the last spread sent while the programmer still holds what it
        gave, else what the reading tells."""
        reading = self.reading
        if self.pending is not None:
            return self.pending, "programmer"
        if reading is None:
            return None, None
        sent = self.sent
        if sent is not None and sent[2] == self.curve and reading.held:
            start, end, _ = sent
            if all(
                abs(attributes.spread_at(start, end, fraction) - value) <= 1e-6
                for fraction, value in reading.held
            ):
                return (start, end), "programmer"
        return reading.ends, reading.source

    def _draw(self) -> None:
        reading = self.reading
        if reading is None:
            return
        ends, source = self.shown_ends()
        for end, part in enumerate(self.ends):
            part.bar.settable = reading.settable
            part.bar.steps = reading.steps
            part.minus.change(inert=not reading.steps)
            part.plus.change(inert=not reading.steps)
            if ends is None:
                part.bar.show_level(0.5 if part.bar.signed else 0.0, colors.TRACK)
                part.show_value(Text("—", style=colors.DIM))
                continue
            value = ends[end]
            color = self.encoder.color if source == "programmer" else f"{self.encoder.color} dim"
            part.bar.show_level(attributes.to_level(value, reading.span), color)
            text = attributes.number_text(self.encoder.attribute, value)
            part.show_value(
                Text(text, style=colors.MAGENTA if source == "programmer" else colors.DIM)
            )
        for curve, button in self.curves.items():
            lit = curve == self.curve
            button.change(intent="record" if lit else "neutral", reverse=lit)

    # ------------------------------------------------------------ actions

    def on_encoder_bar_moved(self, message: EncoderBar.Moved) -> None:
        message.stop()
        reading = self.reading
        if reading is None:
            return
        end = 0 if message.bar is self.bars[0] else 1
        value = attributes.to_value(message.level, reading.span, self.encoder.unit)
        ends, _ = self.shown_ends()
        new = [value, value] if ends is None else list(ends)  # no other end yet: a flat fan
        new[end] = value
        self._send((new[0], new[1]), "ui" if message.final else "internal")

    def on_encoder_bar_stepped(self, message: EncoderBar.Stepped) -> None:
        message.stop()
        end = 0 if message.bar is self.bars[0] else 1
        wheel = self.encoder.wheel
        self.step(end, wheel if message.up else -wheel, "internal")

    def step(self, end: int, by: float, origin: Origin = "ui") -> None:
        """``[−]`` ``[+]`` and the wheel: one end moved by ``by`` (a level's
        as 0..1), within the bar's range; only where the programmer holds
        the attribute."""
        reading = self.reading
        ends, _ = self.shown_ends()
        if reading is None or not reading.steps or ends is None:
            return
        low, high = reading.span
        new = list(ends)
        new[end] = max(low, min(high, new[end] + by))
        self._send((new[0], new[1]), origin)

    def set_curve(self, curve: Curve) -> None:
        """``[centre]`` ``[edges]``: the curve, or linear again for the lit
        one; sent with the ends shown, where the programmer holds the
        attribute."""
        ends, _ = self.shown_ends()  # read for the curve before
        steps = self.reading is not None and self.reading.steps
        self.curve = None if self.curve == curve else curve
        if self._seen is not None:
            self.reading = attributes.spread_reading(self.encoder, *self._seen, self.curve)
        if ends is not None and steps:
            self._send(ends, "ui")
        else:
            self._draw()

    def _send(self, ends: Ends, origin: Origin) -> None:
        ends = (as_sent(ends[0], self.encoder), as_sent(ends[1], self.encoder))
        curve = self.curve
        self._serial += 1
        serial = self._serial
        self.pending, self.pending_after = ends, None
        self._draw()

        def done(ok: bool) -> None:
            if serial != self._serial:
                return  # a newer line was sent since
            if ok:
                self.pending_after = (self.version, time.monotonic())
                self.sent = (ends[0], ends[1], curve)
            else:
                self.pending = self.pending_after = None
                self._draw()

        key = f"set:{self.encoder.attribute}"
        self.post_message(RunLine(spread_line(self.encoder, ends, curve), origin, key, done))

    # -------------------------------------------------------- pane cursor

    def stops(self) -> list[Stop]:
        """Each end's ``[−]`` ``[+]`` (an inert one puts ``set <attribute>
        spread `` in the prompt), then the curves."""
        prefill = f"set {self.encoder.attribute} spread "
        stops: list[Stop] = []
        for end, part in enumerate(self.ends):
            for button, by in ((part.minus, -self.encoder.step), (part.plus, self.encoder.step)):
                label = f"{self.encoder.attribute} {'from' if end == 0 else 'to'} {button.label}"
                item = (
                    Item(label, prefill=prefill)
                    if button.inert
                    else Item(label, action=partial(self.step, end, by))
                )
                stops.append(Stop(item, button))
        for curve, button in self.curves.items():
            item = Item(f"{self.encoder.attribute} {curve}", action=partial(self.set_curve, curve))
            stops.append(Stop(item, button))
        return stops
