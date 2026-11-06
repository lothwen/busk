"""PATCH, in F3's FIXTURE panel and its new fixture form
(``docs/plans/tui-rig-plan.md`` §4 calls 5 and 6, §6.5): a universe and an
address, and what that address means.

It sends nothing: the panel's ``[patch]`` and the form's ``[add]`` do, once
:meth:`PatchChooser.ready` says the place can take the line. A universe chip
proposes its first run of free channels that fits, and so does ``[next
free]``. ``[address…]`` is a dialog. The ``takes`` line says ``free``, ``overlaps
fixture 301`` (allowed, as busk allows it), ``past channel 512`` (not ready), or
``no room for 64 channels``.

The choice follows the show until the operator makes one (:attr:`PatchChooser.held`):
in the panel it is the fixture's patch, and in the form the universe's free room.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import cache, partial
from typing import Final

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from busk_tui import colors
from busk_tui.commands import Line
from busk_tui.model import FixtureInfo, ShowModel
from busk_tui.nav import Item, Stop
from busk_tui.widgets.controls import ActionButton, ButtonStrip, StripButton
from busk_tui.widgets.dialogs import TextDialog
from busk_tui.widgets.dmxmap import CHANNELS, Footprint, clashes, first_free, footprints
from busk_tui.widgets.options import pick_chips
from busk_tui.widgets.quick import strip_stops

NO_UNIVERSE: Final = "no universe: F8 adds one"

NAME_CELLS: Final = 24
"""A universe's chip shows this much of its name: a chip never wraps."""


def channels_text(size: int) -> str:
    """``16 channels``, or ``1 channel``."""
    return f"{size} channel{'' if size == 1 else 's'}"


def span_text(universe: int, address: int, size: int) -> str:
    """``1.85–1.100``, or ``1.85`` for one channel."""
    if size == 1:
        return f"{universe}.{address}"
    return f"{universe}.{address}–{universe}.{address + size - 1}"


def takes_text(
    universe: int, address: int | None, size: int, prints: Sequence[Footprint], own: int | None
) -> Text:
    """What ``size`` channels from ``address`` would mean (``None``: there is
    no room for them), ``own`` being the fixture to place."""
    if address is None:
        return Text.assemble((f"no room for {channels_text(size)}", colors.RED))
    text = Text.assemble((f"takes {span_text(universe, address, size)} · ", colors.DIM))
    found = clashes(prints, address, size, own)
    if address + size - 1 > CHANNELS:
        text.append(f"past channel {CHANNELS}", style=colors.RED)
    elif found:
        noun = "fixture" if len(found) == 1 else "fixtures"
        text.append(f"overlaps {noun} {', '.join(map(str, found))}", style=colors.AMBER)
    else:
        text.append("free", style=colors.GREEN)
    return text


def check_address(text: str) -> str | None:
    text = text.strip()
    if text.isdecimal() and 1 <= int(text) <= CHANNELS:
        return None
    return f"a whole number from 1 to {CHANNELS}"


class PatchChooser(Vertical):
    """A universe and an address (see the module docs). The owner redraws it
    with :meth:`view`; it calls ``changed`` when the operator changes the choice."""

    DEFAULT_CSS = f"""
    PatchChooser {{ height: auto; }}
    PatchChooser Horizontal {{ height: auto; }}
    PatchChooser .pc-name {{ width: 9; color: {colors.MID}; }}
    PatchChooser .pc-address {{ width: auto; margin-right: 1; }}
    PatchChooser ButtonStrip {{ width: 1fr; }}
    PatchChooser CommandButton {{ margin-right: 1; }}
    PatchChooser .pc-takes {{ height: 1; text-wrap: nowrap; text-overflow: ellipsis; }}
    """

    def __init__(self, changed: Callable[[], None]) -> None:
        super().__init__()
        self.changed = changed
        self.show: ShowModel | None = None
        self.channels: int | None = 1  # how many to place; None: not known yet
        self.own: FixtureInfo | None = None  # the fixture to place; None: new fixtures
        self.universe: int | None = None
        self.address: int | None = None  # None: no universe, or no room in it
        self.held = False  # the operator's choice: the show changing leaves it
        self.chips = ButtonStrip()
        self.value = Static("", classes="pc-address")
        self.ask = ActionButton("address…", self.ask_address)
        self.next_free = ActionButton("next free", self.propose)
        self.takes = Static("", classes="pc-takes")
        self._picks = cache(lambda universe: partial(self.pick, universe))

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static("universe", classes="pc-name")
            yield self.chips
        with Horizontal():
            yield Static("address", classes="pc-name")
            yield self.value
            yield self.ask
            yield self.next_free
        yield self.takes

    # ------------------------------------------------------------ drawing

    def view(
        self, show: ShowModel | None, size: int | None, own: FixtureInfo | None = None
    ) -> None:
        """Redraw for ``size`` channels of ``own``, or of new fixtures."""
        self.show, self.channels, self.own = show, size, own
        if self.universe is not None and self.universe not in self.numbers():
            self.universe, self.address, self.held = None, None, False
        if own is not None:
            patch = own.patch or (None, None)
            if not self.held or (self.universe, self.address) == patch:
                self.universe, self.address = patch
                self.held = False
        elif self.universe is not None and not self.held:
            self.address = first_free(self.prints(), size or 1)
        self.draw()

    def numbers(self) -> list[int]:
        """The show's universes, by number."""
        return [] if self.show is None else sorted(u.number for u in self.show.universes)

    def prints(self) -> tuple[Footprint, ...]:
        """What the chosen universe has patched."""
        if self.show is None or self.universe is None:
            return ()
        return footprints(self.show.fixtures, self.universe, {})

    def draw(self) -> None:
        universes = [] if self.show is None else self.show.universes
        labels: dict[int | None, str] = {None: "none"}
        for universe in sorted(universes, key=lambda u: u.number):
            labels[universe.number] = f"{universe.number} {universe.name}"[:NAME_CELLS].rstrip()
        buttons = pick_chips(labels, self.universe, self._picks)
        if not universes:
            words = Text(NO_UNIVERSE, style=colors.DIM)
            buttons.append(StripButton(words, Line(""), note=True))
        self.chips.show(buttons)
        address = "none" if self.address is None else str(self.address)
        if self.value.content != address:
            self.value.update(address)
        self.ask.change(inert=self.universe is None)
        self.next_free.change(inert=self.universe is None)
        text = self._takes_text()
        if self.takes.content != text:
            self.takes.update(text)

    def _takes_text(self) -> Text:
        if self.universe is None:
            return Text.assemble(("no patch", colors.DIM))
        if self.channels is None:
            return Text.assemble(("choose a profile", colors.DIM))
        own = None if self.own is None else self.own.number
        return takes_text(self.universe, self.address, self.channels, self.prints(), own)

    # ---------------------------------------------------------- the choice

    @property
    def at(self) -> tuple[int, int] | None:
        """The place as a line takes it; ``None``: no patch."""
        if self.universe is None or self.address is None:
            return None
        return self.universe, self.address

    def ready(self) -> bool:
        """Whether a line can go: no patch, or a place that fits."""
        if self.universe is None:
            return True
        return self.address is not None and self.address + (self.channels or 1) - 1 <= CHANNELS

    def start(self, universe: int | None, address: int | None = None) -> None:
        """Where the choice starts: at ``address``, held, else in the free room."""
        self.universe, self.address, self.held = universe, address, address is not None

    def _choose(self, universe: int | None, address: int | None, held: bool) -> None:
        self.universe, self.address, self.held = universe, address, held
        self.draw()
        self.changed()

    def pick(self, universe: int | None) -> None:
        """A universe chip. The fixture's own universe gives back its patch."""
        own = self.own
        if own is not None and own.patch is not None and own.patch[0] == universe:
            self._choose(*own.patch, False)
            return
        self.universe = universe
        self.propose()

    def propose(self) -> None:
        """The first run of free channels that fits, the fixture's own not
        among them: ``[next free]`` is for moving it."""
        found = None if self.universe is None else first_free(self.prints(), self.channels or 1)
        self._choose(self.universe, found, self.own is not None)

    def ask_address(self) -> None:
        """``[address…]``: any address, which the ``takes`` line then reads."""
        universe = self.universe
        if universe is None:
            return

        def given(text: str | None) -> None:
            if text is not None:
                self._choose(universe, int(text.strip()), True)

        value = "1" if self.address is None else str(self.address)
        note = f"takes {channels_text(self.channels)}" if self.channels else ""
        title = f"ADDRESS · universe {universe}"
        self.app.push_screen(TextDialog(title, value, check_address, note), given)

    # -------------------------------------------------------- pane cursor

    def stops(self) -> list[Stop]:
        """Its chips and buttons (an inert one is none)."""
        stops = strip_stops(self.chips)
        for button in (self.ask, self.next_free):
            if not button.inert:
                stops.append(Stop(Item(button.label, action=button.action), button))
        return stops
