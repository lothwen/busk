"""The colour picker of F6's PRESET panel (``docs/plans/tui-presets-plan.md``
§4 calls 11 and 12, §5.6). Its parts, top to bottom:

* :class:`ColorField`: a cell per pick. The columns run through the hue,
  360° over the field's width with red at the left. The five rows run
  through the saturation, from 0.2 at the top to 1, all at full value. A
  click sends ``set color r g b`` (two decimals; busk derives the white,
  amber and UV emitters) on release. A drag sends at most every
  :data:`DRAG_S` and logs the last line, as an encoder bar does. The cell
  nearest the programmer's colour is marked when that colour is at full
  value and is not a grey. The field is mouse only, and sets only while
  something is selected.
* the named chips (:data:`CHIPS`): `` red `` on its colour, ``set color 1 0 0``.
* the readout: the programmer's colour for the first selected element, as
  a swatch, its components and its hex value, and the preset it comes from.

It draws with :func:`busk_tui.colors.swatch`, so it works in truecolour,
256 and 16 colours: colours are coarser in 256 and 16, but what it sends
is the same. The colour's component rows (``color.r`` …) are the panel's
encoder rows, under the picker.
"""

from __future__ import annotations

import colorsys
import time
from typing import Final

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static

from busk_tui import attributes, colors, commands
from busk_tui.attributes import Selected
from busk_tui.colors import ColorMode
from busk_tui.model import Components, Origin
from busk_tui.nav import Stop
from busk_tui.widgets.controls import ButtonStrip, RunLine, StripButton
from busk_tui.widgets.quick import strip_stops

type RGB = tuple[float, float, float]

DRAG_S: Final = 0.1
"""A drag sends at most one line this often, as an encoder bar's."""

SATURATIONS: Final = (0.2, 0.4, 0.6, 0.8, 1.0)
"""The field's rows, top to bottom."""

CHIPS: Final[tuple[tuple[str, RGB], ...]] = (
    ("red", (1.0, 0.0, 0.0)),
    ("orange", (1.0, 0.25, 0.0)),
    ("amber", (1.0, 0.5, 0.0)),
    ("yellow", (1.0, 1.0, 0.0)),
    ("lime", (0.5, 1.0, 0.0)),
    ("green", (0.0, 1.0, 0.0)),
    ("cyan", (0.0, 1.0, 1.0)),
    ("sky", (0.0, 0.5, 1.0)),
    ("blue", (0.0, 0.0, 1.0)),
    ("violet", (0.5, 0.0, 1.0)),
    ("magenta", (1.0, 0.0, 1.0)),
    ("pink", (1.0, 0.4, 0.7)),
    ("white", (1.0, 1.0, 1.0)),
    ("warm", (1.0, 0.75, 0.45)),
    ("cool", (0.75, 0.85, 1.0)),
)
"""The named chips (§4 call 12). Red, green, blue and amber are the club's
own presets' values; warm is the club's Warm."""

FULL: Final = 0.995
"""A colour at full value: its brightest component at least this."""

GREY: Final = 0.1
"""A colour less saturated than this is a grey: the field has no cell for it."""


def cell_color(x: int, y: int, width: int) -> RGB:
    """The colour of the field's cell ``(x, y)``, to two decimals."""
    hue = x / max(1, width)
    red, green, blue = colorsys.hsv_to_rgb(hue, SATURATIONS[y], 1.0)
    return (round(red, 2), round(green, 2), round(blue, 2))


def marker(color: RGB | None, width: int) -> tuple[int, int] | None:
    """The cell nearest ``color``; ``None`` for no colour, one not at full
    value, or a grey."""
    if color is None or width < 1:
        return None
    hue, saturation, value = colorsys.rgb_to_hsv(*color)
    if value < FULL or saturation < GREY:
        return None
    x = round(hue * width) % width
    y = min(range(len(SATURATIONS)), key=lambda row: abs(SATURATIONS[row] - saturation))
    return (x, y)


def field_text(width: int, mode: ColorMode, mark: tuple[int, int] | None) -> Text:
    """The field ``width`` cells wide, the cell ``mark`` marked ``●``."""
    text = Text()
    for y in range(len(SATURATIONS)):
        if y:
            text.append("\n")
        for x in range(width):
            style = colors.swatch(cell_color(x, y, width), 1.0, mode)
            if (x, y) == mark:
                text.append("●", style=f"{colors.BG} on {style}")
            else:
                text.append("█", style=style)
    return text


def ink(color: RGB) -> str:
    """The text colour that reads on ``color``: the screen's on a light
    colour, the foreground on a dark one."""
    red, green, blue = color
    return colors.BG if 0.299 * red + 0.587 * green + 0.114 * blue > 0.45 else colors.FG


def chip_buttons(mode: ColorMode) -> list[StripButton]:
    """A button per named chip: `` red `` on its colour."""
    return [
        StripButton(
            Text(f" {name} ", style=f"{ink(rgb)} on {colors.swatch(rgb, 1.0, mode)}"),
            commands.set_color(*rgb),
        )
        for name, rgb in CHIPS
    ]


def rgb_of(value: Components) -> RGB:
    """A colour's red, green and blue, as the field and ``set color`` take
    them (a missing one is 0)."""
    red, green, blue = (attributes.component(value, key) or 0.0 for key in ("r", "g", "b"))
    return (red, green, blue)


def hex_text(color: RGB) -> str:
    """``#ff4000``."""
    return "#" + "".join(f"{round(max(0.0, min(1.0, part)) * 255):02x}" for part in color)


def components_text(value: Components) -> str:
    """A colour's components as ``set color`` takes them: ``1 0.5 0 w 0.25``."""
    return " ".join(
        ("" if name in ("r", "g", "b") else f"{name} ") + commands.number(amount)
        for name, amount in value
    )


def readout_text(chosen: Selected, mode: ColorMode) -> Text:
    """The programmer's colour for the first selected element: ``████ 1 0.25
    0 · #ff4000``, and its preset; else what to do."""
    held = chosen.values.get("color")
    if held is None or not isinstance(held.value, tuple):
        text = Text("—", style=colors.DIM)
        if chosen.first is None:
            text.append(" nothing selected", style=colors.DIM)
        else:
            text.append(" no colour held: pick one, then the rows act", style=colors.DIM)
        return text
    value = held.value
    text = Text("████", style=colors.swatch(attributes.rgb(value), 1.0, mode))
    text.append(f" {components_text(value)}", style=colors.FG)
    text.append(f" · {hex_text(rgb_of(value))}", style=colors.DIM)
    if held.preset is not None:
        text.append(f" {held.preset}", style=colors.MAGENTA)
    return text


class ColorField(Widget):
    """The hue × saturation field (see the module docs). The owner redraws
    it with :meth:`show`."""

    DEFAULT_CSS = f"ColorField {{ height: {len(SATURATIONS)}; width: 1fr; }}"

    def __init__(self) -> None:
        super().__init__()
        self.mode: ColorMode = "256"
        self.held: RGB | None = None  # the programmer's colour
        self.settable = False
        self.dragging = False
        self.picked: tuple[int, int] | None = None  # the cell sent, until its line is done
        self._serial = 0
        self._sent_at = 0.0
        self._later: Timer | None = None

    def show(self, held: RGB | None, mode: ColorMode, settable: bool) -> None:
        """The programmer's colour, the terminal's colours, and whether a
        click sets."""
        self.settable = settable
        if (held, mode) != (self.held, self.mode):
            self.held, self.mode = held, mode
            self.refresh()

    def render(self) -> Text:
        width = self.size.width
        mark = self.picked if self.picked is not None else marker(self.held, width)
        return field_text(width, self.mode, mark)

    def cell_at(self, x: int, y: int) -> tuple[int, int]:
        """The cell under ``(x, y)``, within the field (a drag may leave it)."""
        width = max(1, self.size.width)
        return (max(0, min(width - 1, x)), max(0, min(len(SATURATIONS) - 1, y)))

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if not self.settable:
            return
        event.stop()
        self.dragging = True
        self.capture_mouse()
        self._pick(self.cell_at(event.x, event.y))
        self._sent_at = time.monotonic()  # a click sends on release only

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self.dragging:
            return
        cell = self.cell_at(event.x, event.y)
        if cell == self.picked:
            return
        self._pick(cell)
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
        self._pick(self.cell_at(event.x, event.y))
        self._send("ui")

    def _pick(self, cell: tuple[int, int]) -> None:
        if cell != self.picked:
            self.picked = cell
            self.refresh()

    def _report(self) -> None:
        self._later = None
        if self.dragging:
            self._sent_at = time.monotonic()
            self._send("internal")

    def _send(self, origin: Origin) -> None:
        if self.picked is None:
            return
        self._serial += 1
        serial = self._serial

        def done(ok: bool) -> None:
            if serial == self._serial and not self.dragging:
                self.picked = None  # the programmer's colour from now on
                self.refresh()

        line = commands.set_color(*cell_color(*self.picked, self.size.width))
        self.post_message(RunLine(line, origin, "set:color", done))

    def _cancel(self) -> None:
        if self._later is not None:
            self._later.stop()
            self._later = None


class ColorPicker(Vertical):
    """The field, the named chips and the readout (see the module docs)."""

    DEFAULT_CSS = """
    ColorPicker { height: auto; }
    ColorPicker > ButtonStrip { margin-top: 1; }
    ColorPicker > .cp-readout { height: auto; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.field = ColorField()
        self.chips = ButtonStrip()
        self.readout = Static("", classes="cp-readout")
        self.mode: ColorMode | None = None

    def compose(self) -> ComposeResult:
        yield self.field
        yield self.chips
        yield self.readout

    def show(self, chosen: Selected, mode: ColorMode) -> None:
        """Draw with the first selected element's colour as the programmer holds it."""
        held = chosen.values.get("color")
        color = rgb_of(held.value) if held is not None and isinstance(held.value, tuple) else None
        self.field.show(color, mode, chosen.first is not None)
        if mode != self.mode:
            self.mode = mode
            self.chips.show(chip_buttons(mode))
        text = readout_text(chosen, mode)
        if self.readout.content != text:
            self.readout.update(text)

    def stops(self) -> list[Stop]:
        """The chips (the field is mouse only)."""
        return strip_stops(self.chips)
