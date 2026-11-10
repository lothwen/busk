"""The route form (``docs/plans/tui-rig-plan.md`` §6.7): what ``route add``
takes, by protocol, for one universe. Given a route of the show, it starts at
what the route holds and makes ``route <id> change …`` (GAP-37) of the same
words, for the route's own universe; a form that changes nothing sends nothing.

- sACN: the sACN universe, starting at the show universe's number, then
  ``multicast`` with an interface or ``unicast`` with a host;
- Art-Net: ``net.sub.universe``, starting where Art-Net counts the show
  universe (from 0, so universe 1 is ``0.0.0``), then ``broadcast`` or
  ``unicast``;
- DMX-USB: ``enttecPro`` or ``dmxking``, the port, and the rate.

A modal dialog, because its fields are typed and only a modal has the keyboard.
It sends nothing: it closes with the line, for the page to run. An interface
left empty is left to busk, which has ``--iface``. What only busk can tell, such
as an sACN universe another universe sends, or a route the universe has already,
is refused in the log, as for every control.
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
from busk_tui.model import RouteView
from busk_tui.widgets.controls import ButtonStrip
from busk_tui.widgets.dialogs import dialog_css, read_number, read_whole
from busk_tui.widgets.options import pick_chips

PROTOCOLS: Final = {"sacn": "sACN", "artnet": "Art-Net", "dmxusb": "DMX-USB"}
KEYS: Final = {"sACN": "sacn", "ArtNet": "artnet", "DMX-USB": "dmxusb"}
"""Each protocol as :class:`~busk_tui.model.RouteView` names it, and its chip."""
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
    universe: int,
    protocol: Literal["sacn", "artnet"],
    address: str,
    way: str,
    where: str,
    route: str | None = None,
) -> Line:
    """``route add 2 sacn 2 multicast eth0``; no ``where``: ``route add 2 sacn
    2``. With a ``route``: ``route r-1 change 2 sacn 2 …``."""
    destination = f"{way} {commands.word(where)}" if where else None
    if route is not None:
        return commands.route_change(route, universe, protocol, address, destination)
    return commands.route_add(universe, protocol, address, destination)


def usb_line(universe: int, driver: str, port: str, rate: float, route: str | None = None) -> Line:
    """``route add 2 dmxusb enttecPro /dev/ttyUSB0 hz 40``; with a ``route``:
    ``route r-1 change 2 dmxusb …``."""
    if route is not None:
        return commands.route_change(route, universe, "dmxusb", driver, commands.word(port), rate)
    return commands.route_add(universe, "dmxusb", driver, commands.word(port), rate)


def ways(protocol: str) -> dict[str, str]:
    """The chips of ``protocol``: its open way, then ``unicast``."""
    return {"open": OPEN_WAYS[protocol], "unicast": "unicast"}


class PickRow(ButtonStrip, can_focus=True):
    """One of ``labels``, as chips (``chosen``: where it starts, else the
    first): a click moves ``chosen``, and so do ← → while it has the focus."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "step(-1)", "Previous", show=False),
        Binding("right", "step(1)", "Next", show=False),
    ]

    class Picked(Message):
        """``chosen`` moved."""

    def __init__(self, labels: Mapping[str, str], chosen: str | None = None) -> None:
        super().__init__()
        self.labels = labels
        self.chosen = next(iter(labels)) if chosen is None else chosen
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
    """Closes with a ``route add`` line for ``universe``, or with ``route``
    a ``route <id> change`` line, or ``None`` (see the module docs). Tab moves
    between the fields and the chips, ← → move the chips. Enter, anywhere,
    runs the checks: what is wrong shows, and the dialog stays. Esc cancels."""

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

    def __init__(self, universe: int, name: str, route: RouteView | None = None) -> None:
        super().__init__()
        self.universe = universe
        self.route = route
        head = "NEW ROUTE" if route is None else f"EDIT ROUTE {route.id}"
        self.title_text = Text(f"{head} · U{universe} {name}")  # a name in it is not markup
        protocol = "sacn" if route is None else KEYS.get(route.protocol, "sacn")
        addresses = {"sacn": str(universe), "artnet": artnet_address(universe), "dmxusb": ""}
        if route is not None:
            addresses[protocol] = route.address
        address = addresses[protocol]
        way, _, where = ("", "", "") if route is None else route.destination.partition(" ")
        usb = protocol == "dmxusb"
        self.protocol = PickRow(PROTOCOLS, protocol)
        self.sacn = Input(addresses["sacn"], compact=True)
        self.artnet = Input(addresses["artnet"], compact=True)
        self.way = PickRow(
            ways("sacn" if usb else protocol), "unicast" if way == "unicast" else "open"
        )
        self.where_label = Static("interface", classes="label")
        self.where = Input("" if usb else where, placeholder=ANY_INTERFACE, compact=True)
        self.driver = PickRow(DRIVERS, address if usb and address in DRIVERS else None)
        port = route.destination if route is not None and usb else ""
        self.port = Input(port, placeholder=A_PORT, compact=True)
        rate = None if route is None else route.rate
        self.rate = Input(RATE if rate is None else commands.number(rate), compact=True)
        self.error = Static("", classes="error")
        self.sacn_row = row("universe", self.sacn)
        self.artnet_row = row("address", self.artnet)
        self.network = Vertical(row("send by", self.way), row(self.where_label, self.where))
        self.usb = Vertical(
            row("driver", self.driver), row("port", self.port), row("rate (Hz)", self.rate)
        )
        self.held = None if route is None else self.line()  # what the route sends now

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
        route, universe = None if self.route is None else self.route.id, self.universe
        match self.protocol.chosen:
            case "sacn":
                address = self.sacn.value.strip()
                return network_line(universe, "sacn", address, way, where, route)
            case "artnet":
                address = self.artnet.value.strip()
                return network_line(universe, "artnet", address, way, where, route)
            case _:
                port, rate = self.port.value.strip(), float(self.rate.value)
                return usb_line(universe, self.driver.chosen, port, rate, route)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_ok()

    def action_ok(self) -> None:
        """The line, or ``None`` when it is what the route sends already."""
        problem = self.problem()
        if problem is None:
            line = self.line()
            self.dismiss(None if line == self.held else line)
        else:
            self.error.update(problem)

    def action_cancel(self) -> None:
        self.dismiss(None)
