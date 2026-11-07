"""The new route form (``docs/plans/tui-rig-plan.md`` §6.7): what ``route add``
takes, by protocol, for one universe.

- sACN: the sACN universe, starting at the show universe's number, then
  ``multicast`` with an interface or ``unicast`` with a host;
- Art-Net: ``net.sub.universe``, starting where Art-Net counts the show
  universe (from 0, so universe 1 is ``0.0.0``), then ``broadcast`` or
  ``unicast``;
- DMX-USB: ``enttecPro`` or ``dmxking``, the port, and the rate.

A modal dialog, because its fields are typed and only a modal has the keyboard.
It sends nothing: it closes with the line, for the page to run. An interface
left empty is left to busk, which has ``--iface``. What only busk can tell, such
as an sACN universe another universe sends, is refused in the log, as for every
control.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache, partial
from typing import ClassVar, Final, Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, Static

from busk_tui import colors, commands
from busk_tui.commands import Line
from busk_tui.widgets.controls import ButtonStrip
from busk_tui.widgets.dialogs import dialog_css, read_number, read_whole
from busk_tui.widgets.options import pick_chips

PROTOCOLS: Final = {"sacn": "sACN", "artnet": "Art-Net", "dmxusb": "DMX-USB"}
DRIVERS: Final = {"enttecPro": "enttecPro", "dmxking": "dmxking"}
OPEN_WAYS: Final = {"sacn": "multicast", "artnet": "broadcast"}
"""How each protocol reaches a network, as opposed to one host."""

SACN_TOP: Final = 63999
ARTNET_TOPS: Final = (127, 15, 15)
RATE: Final = "40"
MIN_RATE: Final = 1
MAX_RATE: Final = 40
"""What a widget runs at: busk keeps a route's rate to these."""

ANY_INTERFACE: Final = "empty: busk's own (--iface)"
A_HOST: Final = "10.0.0.50"
A_PORT: Final = "/dev/ttyUSB0"


def artnet_address(universe: int) -> str:
    """The show universe as Art-Net counts it, from 0: 1 is ``0.0.0``, 17 ``0.1.0``."""
    port = universe - 1
    return f"{port >> 8 & 127}.{port >> 4 & 15}.{port & 15}"


def check_sacn(text: str) -> str | None:
    """An sACN universe's check."""
    number = read_whole(text.strip())
    if number is not None and 1 <= number <= SACN_TOP:
        return None
    return f"an sACN universe from 1 to {SACN_TOP}"


def check_artnet(text: str) -> str | None:
    """A port address's check."""
    parts = [read_whole(part) for part in text.strip().split(".")]
    if len(parts) == len(ARTNET_TOPS) and all(
        part is not None and part <= top for part, top in zip(parts, ARTNET_TOPS, strict=True)
    ):
        return None
    net, sub, universe = ARTNET_TOPS
    return f"net.sub.universe, up to {net}.{sub}.{universe}"


def check_host(text: str) -> str | None:
    return None if text.strip() else f"a host, such as {A_HOST}"


def check_port(text: str) -> str | None:
    return None if text.strip() else f"a port, such as {A_PORT}"


def check_rate(text: str) -> str | None:
    """A refresh rate's check: what a widget runs at, as busk takes it."""
    rate = read_number(text)
    if rate is None or not MIN_RATE <= rate <= MAX_RATE:
        return f"a rate from {MIN_RATE} to {MAX_RATE} Hz"
    return None


def network_line(
    universe: int, protocol: Literal["sacn", "artnet"], address: str, way: str, where: str
) -> Line:
    """``route add 2 sacn 2 multicast eth0``; no ``where``: ``route add 2 sacn 2``."""
    destination = f"{way} {commands.word(where)}" if where else None
    return commands.route_add(universe, protocol, address, destination)


def usb_line(universe: int, driver: str, port: str, rate: float) -> Line:
    """``route add 2 dmxusb enttecPro /dev/ttyUSB0 hz 40``."""
    return commands.route_add(universe, "dmxusb", driver, commands.word(port), rate)


def ways(protocol: str) -> dict[str, str]:
    """The chips of ``protocol``: its open way, then ``unicast``."""
    return {"open": OPEN_WAYS[protocol], "unicast": "unicast"}


class PickRow(ButtonStrip, can_focus=True):
    """One of ``labels``, as chips: a click moves ``chosen``, and so do ← →
    while it has the focus."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "step(-1)", "Previous", show=False),
        Binding("right", "step(1)", "Next", show=False),
    ]

    class Picked(Message):
        """``chosen`` moved."""

    def __init__(self, labels: Mapping[str, str]) -> None:
        super().__init__()
        self.labels = labels
        self.chosen = next(iter(labels))
        self._picks = cache(lambda key: partial(self.pick, key))
        self._draw()

    def _draw(self) -> None:
        self.show(pick_chips(self.labels, self.chosen, self._picks))

    def relabel(self, labels: Mapping[str, str]) -> None:
        """New words for the same keys."""
        self.labels = labels
        self._draw()

    def pick(self, key: str) -> None:
        self.chosen = key
        self._draw()
        self.post_message(self.Picked())

    def action_step(self, by: int) -> None:
        keys = list(self.labels)
        self.pick(keys[(keys.index(self.chosen) + by) % len(keys)])


def row(label: Static | str, field: Widget) -> Horizontal:
    return Horizontal(Static(label, classes="label") if isinstance(label, str) else label, field)


class RouteDialog(ModalScreen[Line | None]):
    """Closes with a ``route add`` line for ``universe``, or ``None`` (see the
    module docs). Tab moves between the fields and the chips, ← → move the
    chips. Enter, anywhere, runs the checks: what is wrong shows, and the
    dialog stays. Esc cancels."""

    DEFAULT_CSS = (
        dialog_css("RouteDialog")
        + f"""
    RouteDialog > Vertical {{ width: 60; }}
    RouteDialog Vertical Vertical {{ width: 100%; height: auto; }}
    RouteDialog Horizontal {{ width: 100%; margin-top: 0; }}
    RouteDialog .label {{ color: {colors.MID}; width: 11; }}
    RouteDialog Input {{ width: 1fr; }}
    RouteDialog PickRow {{ width: 1fr; }}
    RouteDialog PickRow:focus {{ background: {colors.SEL}; }}
    RouteDialog .error {{ color: {colors.RED}; width: 100%; height: auto; }}
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "ok", "OK", show=False),
    ]

    def __init__(self, universe: int, name: str) -> None:
        super().__init__()
        self.universe = universe
        self.title_text = Text(f"NEW ROUTE · U{universe} {name}")  # a name in it is not markup
        self.protocol = PickRow(PROTOCOLS)
        self.sacn = Input(str(universe), compact=True)
        self.artnet = Input(artnet_address(universe), compact=True)
        self.way = PickRow(ways("sacn"))
        self.where_label = Static("interface", classes="label")
        self.where = Input(placeholder=ANY_INTERFACE, compact=True)
        self.driver = PickRow(DRIVERS)
        self.port = Input(placeholder=A_PORT, compact=True)
        self.rate = Input(RATE, compact=True)
        self.error = Static("", classes="error")
        self.sacn_row = row("universe", self.sacn)
        self.artnet_row = row("address", self.artnet)
        self.network = Vertical(row("send by", self.way), row(self.where_label, self.where))
        self.usb = Vertical(
            row("driver", self.driver), row("port", self.port), row("rate (Hz)", self.rate)
        )

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = self.title_text
            yield row("protocol", self.protocol)
            yield self.sacn_row
            yield self.artnet_row
            yield self.network
            yield self.usb
            yield self.error
            yield Static("Tab: next · ← →: chips · Enter: OK · Esc: cancel", classes="note")

    def on_mount(self) -> None:
        self._draw()

    def _draw(self) -> None:
        """The fields of the protocol chosen, and what its way sends to."""
        protocol = self.protocol.chosen
        self.sacn_row.display = protocol == "sacn"
        self.artnet_row.display = protocol == "artnet"
        self.network.display = protocol != "dmxusb"
        self.usb.display = protocol == "dmxusb"
        if protocol != "dmxusb":
            self.way.relabel(ways(protocol))
        unicast = self.way.chosen == "unicast"
        self.where_label.update("host" if unicast else "interface")
        self.where.placeholder = A_HOST if unicast else ANY_INTERFACE

    def on_pick_row_picked(self, message: PickRow.Picked) -> None:
        message.stop()
        self.error.update("")  # it may be of a field that just went
        self._draw()

    def problem(self) -> str | None:
        """What is wrong with the fields shown, first to last."""
        match self.protocol.chosen:
            case "sacn":
                found = check_sacn(self.sacn.value)
            case "artnet":
                found = check_artnet(self.artnet.value)
            case _:
                return check_port(self.port.value) or check_rate(self.rate.value)
        if found is None and self.way.chosen == "unicast":
            return check_host(self.where.value)
        return found

    def line(self) -> Line:
        """The line the fields shown make, once they pass."""
        way, where = self.way.labels[self.way.chosen], self.where.value.strip()
        match self.protocol.chosen:
            case "sacn":
                return network_line(self.universe, "sacn", self.sacn.value.strip(), way, where)
            case "artnet":
                return network_line(self.universe, "artnet", self.artnet.value.strip(), way, where)
            case _:
                rate = float(self.rate.value)
                return usb_line(self.universe, self.driver.chosen, self.port.value.strip(), rate)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_ok()

    def action_ok(self) -> None:
        problem = self.problem()
        if problem is None:
            self.dismiss(self.line())
        else:
            self.error.update(problem)

    def action_cancel(self) -> None:
        self.dismiss(None)
