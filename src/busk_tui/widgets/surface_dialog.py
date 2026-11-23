"""F9's surface form (``docs/plans/tui-pending-plan.md`` Phase 39): what
``surface add`` takes, by kind. Given a surface of the show, it starts at what
the surface holds, its kind fixed, and makes ``surface "<name>" change …``
(busk's GAP-61) of the same words; a form that changes nothing sends nothing.

- MIDI: the device. The MIDI devices plugged in to the console's host (busk's
  GAP-62) are chips, read as the form opens: a click puts one in the field
  under them, and the chip of the device the field holds is lit. A chip
  reads ``in use``, dim, where another surface finds that device already,
  and with it in the field a line names that surface. A device that is not
  plugged in is typed. busk names a new MIDI surface after its device
  (pending plan §5, call 32).
- OSC: the name, the port (8000) and where feedback goes: empty for the
  sender, else a host, ``host:port`` or ``:port``.
- web: the name, the port (8080) and the address to listen on: empty for
  every interface.

The line always carries the port. The form checks what the show tells it:
an empty name or device, a name another surface has in any case, a port
outside 1 to 65535 or one another surface of the kind listens on, and a
feedback target busk cannot read. What only busk can tell is refused in the
log, as for every control.

A modal dialog, because its fields are typed and only a modal has the
keyboard. It sends nothing: it closes with the line, for the page to run.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from functools import cache, partial
from typing import ClassVar, Final, Literal, cast

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from busk_tui import colors, commands
from busk_tui.commands import Line
from busk_tui.model import SurfaceView
from busk_tui.widgets.controls import ButtonStrip, ReadDevices, StripButton
from busk_tui.widgets.dialogs import dialog_css, read_whole
from busk_tui.widgets.options import LIT
from busk_tui.widgets.route_dialog import PickRow, row

KINDS: Final = {"midi": "MIDI", "osc": "OSC", "web": "web"}
"""Each kind as ``surface add`` takes it, and its chip."""

PORTS: Final = {"osc": 8000, "web": 8080}
"""Where a port starts: busk's own defaults."""

TOP_PORT: Final = 65535

A_DEVICE: Final = "nanoKONTROL2"
TYPED: Final = "click one above, or type its name"
IN_USE: Final = "in use"
TO_SENDER: Final = "empty: the sender · host, host:port or :port"
EVERY_INTERFACE: Final = "empty: every interface"
READING: Final = "reading the devices plugged in…"
NO_DEVICES: Final = "no MIDI device is plugged in: type its name"
NAMED: Final = "busk names it after its device: [rename…] renames it"

type Kind = Literal["midi", "osc", "web"]


def check_surface_name(taken: Collection[str], own: str | None) -> Callable[[str], str | None]:
    """A surface name's check: not empty, and not a name another surface
    has, in any case, as busk refuses it (``own``, the surface's own, may
    change)."""
    folded = {name.casefold() for name in taken if name != own}

    def check(text: str) -> str | None:
        name = text.strip()
        if not name:
            return "a name cannot be empty"
        if name.casefold() in folded:
            return f"a surface named {commands.quoted(name)} exists"
        return None

    return check


def check_device(text: str) -> str | None:
    return None if text.strip() else f"a device, such as {A_DEVICE}"


def read_port(text: str) -> int | None:
    """A port as busk reads it, from 1 to 65535; ``None`` if it is not one."""
    port = read_whole(text.strip())
    return port if port is not None and 1 <= port <= TOP_PORT else None


def check_port(
    surfaces: Sequence[SurfaceView], kind: str, own: str | None
) -> Callable[[str], str | None]:
    """A port's check: from 1 to 65535, and not one another surface of
    ``kind`` listens on (``own``'s may stay)."""

    def check(text: str) -> str | None:
        port = read_port(text)
        if port is None:
            return f"a port from 1 to {TOP_PORT}"
        user = next(
            (s for s in surfaces if s.kind == kind and s.port == port and s.name != own), None
        )
        if user is not None:
            return f"port {port} is in use by surface {commands.quoted(user.name)}"
        return None

    return check


def check_feedback(text: str) -> str | None:
    """Where OSC feedback goes, as busk reads it: empty, a host, ``host:port``
    or ``:port``, the port from 1 to 65535."""
    given = text.strip()
    if not given:
        return None
    host, colon, port = given.rpartition(":")
    if not colon:
        host, port = given, ""
    if (host or port) and (not port or read_port(port) is not None):
        return None
    return f"a host, host:port or :port, the port from 1 to {TOP_PORT}"


def finders(surfaces: Sequence[SurfaceView], own: str | None) -> dict[str, str]:
    """Each MIDI surface but ``own`` by the device it opens, casefolded, as
    busk finds a port whose name contains it."""
    return {
        s.midi.casefold(): s.name for s in surfaces if s.kind == "midi" and s.midi and s.name != own
    }


def found_by(device: str, found: dict[str, str]) -> str | None:
    """The surface that finds ``device`` already, if one does."""
    folded = device.casefold()
    return next((name for needle, name in found.items() if needle in folded), None)


class DeviceChips(ButtonStrip, can_focus=True):
    """The MIDI devices plugged in, a chip each (see the module docs): a
    click, or ← → while it has the focus, puts one in ``field``."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "step(-1)", "Previous", show=False),
        Binding("right", "step(1)", "Next", show=False),
    ]

    def __init__(self, field: Input, found: dict[str, str]) -> None:
        super().__init__()
        self.field = field
        self.found = found
        self.devices: tuple[str, ...] | None = None  # None: still reading
        self._picks = cache(lambda device: partial(self.pick, device))
        self.draw()

    def set_devices(self, devices: tuple[str, ...]) -> None:
        self.devices = devices
        self.draw()

    def draw(self) -> None:
        if not self.devices:
            words = READING if self.devices is None else NO_DEVICES
            self.show([StripButton(Text(words, style=colors.DIM), Line(""), note=True)])
            return
        held = self.field.value.strip()
        buttons = []
        for device in self.devices:
            used = found_by(device, self.found) is not None
            words = f"[{device} · {IN_USE}]" if used else f"[{device}]"
            label = Text()  # a span: lit or not compare different
            label.append(words, style=LIT if device == held else colors.DIM if used else colors.MID)
            buttons.append(StripButton(label, Line(""), action=self._picks(device)))
        self.show(buttons)

    def pick(self, device: str) -> None:
        self.field.value = device  # Input.Changed redraws the chips

    def action_step(self, by: int) -> None:
        if not self.devices:
            return
        held = self.field.value.strip()
        at = self.devices.index(held) if held in self.devices else (-1 if by > 0 else 0)
        self.pick(self.devices[(at + by) % len(self.devices)])


class SurfaceDialog(ModalScreen[Line | None]):
    """Closes with a ``surface add`` line, or with ``surface`` a ``surface
    "<name>" change`` line, or ``None`` (see the module docs). Tab moves
    between the fields and the chips, ← → move the chips. Enter, anywhere,
    runs the checks: what is wrong shows, and the dialog stays. Esc cancels."""

    DEFAULT_CSS = (
        dialog_css("SurfaceDialog")
        + f"""
    SurfaceDialog > Vertical {{ width: 64; }}
    SurfaceDialog Vertical Vertical {{ width: 100%; height: auto; }}
    SurfaceDialog Horizontal {{ width: 100%; height: auto; margin-top: 0; }}
    SurfaceDialog .label {{ color: {colors.MID}; width: 11; }}
    SurfaceDialog Input {{ width: 1fr; }}
    SurfaceDialog PickRow {{ width: 1fr; }}
    SurfaceDialog PickRow:focus {{ background: {colors.SEL}; }}
    SurfaceDialog DeviceChips {{ width: 1fr; }}
    SurfaceDialog DeviceChips:focus {{ background: {colors.SEL}; }}
    SurfaceDialog .found {{ color: {colors.DIM}; width: 100%; height: auto; }}
    SurfaceDialog .error {{ color: {colors.RED}; width: 100%; height: auto; }}
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "ok", "OK", show=False),
    ]

    def __init__(self, surfaces: Sequence[SurfaceView], surface: SurfaceView | None = None) -> None:
        super().__init__()
        self.surfaces = tuple(surfaces)
        self.surface = surface
        own = None if surface is None else surface.name
        if surface is None:
            self.title_text = Text("NEW SURFACE")
        else:
            words = KINDS.get(surface.kind, surface.kind)
            self.title_text = Text(f"EDIT SURFACE {commands.quoted(surface.name)} · {words}")
        kind = "midi" if surface is None else surface.kind
        self.kind = PickRow(KINDS, kind)
        self.device = Input(
            "" if surface is None else surface.midi, placeholder=TYPED, compact=True
        )
        self.found = finders(self.surfaces, own)
        self.chips = DeviceChips(self.device, self.found)
        self.found_note = Static("", classes="found")
        self.name_field = Input("", placeholder="a name, such as Touch", compact=True)
        port = None if surface is None else surface.port
        self.ports = {
            key: Input(str(start if port is None else port), compact=True)
            for key, start in PORTS.items()
        }
        where = "" if surface is None else surface.where
        self.wheres = {
            "osc": Input(where, placeholder=TO_SENDER, compact=True),
            "web": Input(where, placeholder=EVERY_INTERFACE, compact=True),
        }
        self.check_name = check_surface_name([s.name for s in self.surfaces], own)
        self.port_checks = {key: check_port(self.surfaces, key, own) for key in PORTS}
        self.error = Static("", classes="error")
        self.kind_row = row("kind", self.kind)
        self.midi = Vertical(
            row("plugged in", self.chips),
            row("device", self.device),
            self.found_note,
            *([Static(Text(NAMED), classes="note")] if surface is None else []),
        )
        self.name_row = row("name", self.name_field)
        self.listening = {
            "osc": Vertical(row("port", self.ports["osc"]), row("feedback", self.wheres["osc"])),
            "web": Vertical(row("port", self.ports["web"]), row("address", self.wheres["web"])),
        }
        self.held = None if surface is None else self.line()  # what the surface is now

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = self.title_text
            if self.surface is None:
                yield self.kind_row
            yield self.midi
            if self.surface is None:
                yield self.name_row
            yield from self.listening.values()
            yield self.error
            yield Static("Tab: next · ← →: chips · Enter: OK · Esc: cancel", classes="note")

    def on_mount(self) -> None:
        self._draw()
        if self.kind.chosen == "midi":  # a new surface starts at MIDI
            self.post_message(ReadDevices(self.devices_read))
        if self.surface is not None:  # a new one starts at the kind's chips, the first
            kind = self.kind.chosen
            (self.device if kind == "midi" else self.ports[kind]).focus()

    def devices_read(self, devices: tuple[str, ...]) -> None:
        if self.chips.is_attached:
            self.chips.set_devices(devices)

    def _draw(self) -> None:
        """The fields of the kind chosen."""
        kind = self.kind.chosen
        self.midi.display = kind == "midi"
        self.name_row.display = kind != "midi"
        for key, fields in self.listening.items():
            fields.display = kind == key
        self._draw_found()

    def _draw_found(self) -> None:
        """Which surface finds the device the field holds already."""
        device = self.device.value.strip()
        name = found_by(device, self.found) if device else None
        self.found_note.display = name is not None
        if name is not None:
            self.found_note.update(Text(f"surface {commands.quoted(name)} finds it already"))

    def on_pick_row_picked(self, message: PickRow.Picked) -> None:
        message.stop()
        self.error.update("")  # it may be of a field that just went
        self._draw()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input is self.device:
            self.chips.draw()
            self._draw_found()

    def problem(self) -> str | None:
        """What is wrong with the fields shown, first to last."""
        kind = self.kind.chosen
        if kind == "midi":
            found = check_device(self.device.value)
            if found is None and self.surface is None:
                return self.check_name(self.device.value)
            return found
        found = None if self.surface is not None else self.check_name(self.name_field.value)
        found = found or self.port_checks[kind](self.ports[kind].value)
        if found is None and kind == "osc":
            return check_feedback(self.wheres["osc"].value)
        return found

    def line(self) -> Line:
        """The line the fields shown make, once they pass."""
        kind = cast(Kind, self.kind.chosen)
        if kind == "midi":
            device = self.device.value.strip()
            if self.surface is None:
                return commands.surface_add_midi(device)
            return commands.surface_change_midi(self.surface.name, device)
        port = read_port(self.ports[kind].value) or PORTS[kind]
        where = self.wheres[kind].value.strip()
        if self.surface is None:
            return commands.surface_add(kind, self.name_field.value.strip(), port, where)
        return commands.surface_change(self.surface.name, kind, port, where)

    def new_name(self) -> str:
        """The name busk gives the surface the line adds."""
        if self.kind.chosen == "midi":
            return self.device.value.strip()
        return self.name_field.value.strip()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_ok()

    def action_ok(self) -> None:
        """The line, or ``None`` when it is what the surface is already."""
        problem = self.problem()
        if problem is None:
            line = self.line()
            self.dismiss(None if line == self.held else line)
        else:
            self.error.update(problem)

    def action_cancel(self) -> None:
        self.dismiss(None)
