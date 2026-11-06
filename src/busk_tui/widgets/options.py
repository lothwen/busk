"""Option rows of F6's PRESET panel (``docs/plans/tui-presets-plan.md`` §5.6).

A row is a discrete attribute as ``set`` names it (``gobo1``, ``prism``,
``shutter`` …), then a chip per option the selection offers, from busk's
own completion (:meth:`busk_tui.model.ProgrammerModel.offered`). A click
sends ``set gobo1 star``. The programmer's option for the first selected
element is lit. With no option to offer, the row says why: nothing is
selected, or the selection has no such attribute.

:func:`pick_chips` is the same chip for a choice that sends nothing (F3's
universe and mode).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.attributes import Selected
from busk_tui.commands import Line
from busk_tui.model import ProgrammerModel
from busk_tui.nav import Stop
from busk_tui.widgets.controls import ButtonStrip, StripButton
from busk_tui.widgets.quick import strip_stops

LIT = f"bold {colors.BG} on {colors.MAGENTA}"
"""The programmer's option: reversed, in the programmer's colour."""


def option_buttons(attribute: str, offered: Sequence[str], lit: str | None) -> list[StripButton]:
    """A chip per option, ``lit`` reversed. The style is a span, not the
    label's base style, so a chip lit or not compares different."""
    buttons = []
    for option in offered:
        label = Text()
        label.append(f"[{option}]", style=LIT if option == lit else colors.MID)
        buttons.append(StripButton(label, commands.set_option(attribute, option)))
    return buttons


def pick_chips[K](
    labels: Mapping[K, str], lit: K, pick: Callable[[K], Callable[[], None]]
) -> list[StripButton]:
    """A chip per key, labelled as ``labels`` has it, each calling ``pick(key)``
    (one callable per key: equal buttons compare equal). The ``lit`` one is
    reversed, and a note: it is chosen already."""
    buttons = []
    for key, word in labels.items():
        label = Text()
        label.append(f"[{word}]", style=LIT if key == lit else colors.MID)
        if key == lit:
            buttons.append(StripButton(label, Line(""), note=True))
        else:
            buttons.append(StripButton(label, Line(""), action=pick(key)))
    return buttons


def none_text(attribute: str, selected: bool) -> Text:
    """Why a row offers nothing."""
    if not selected:
        return Text("nothing selected", style=colors.DIM)
    return Text(f"the selection has no {attribute}", style=colors.DIM)


class OptionRow(Horizontal):
    """One discrete attribute (see the module docs). The panel redraws it
    with :meth:`show`."""

    DEFAULT_CSS = f"""
    OptionRow {{ height: auto; }}
    OptionRow > .opt-name {{
        width: 16; color: {colors.MID}; text-wrap: nowrap; text-overflow: ellipsis;
    }}
    OptionRow > ButtonStrip {{ width: 1fr; }}
    OptionRow > .opt-none {{ width: 1fr; height: 1; }}
    """

    def __init__(self, attribute: str) -> None:
        super().__init__()
        self.attribute = attribute
        self.name_text = Static(attribute, classes="opt-name")
        self.chips = ButtonStrip()
        self.none = Static(none_text(attribute, False), classes="opt-none")
        self.chips.display = False

    def compose(self) -> ComposeResult:
        yield self.name_text
        yield self.chips
        yield self.none

    def show(self, programmer: ProgrammerModel | None, chosen: Selected) -> None:
        """Draw the options the selection offers, the first selected
        element's lit."""
        offered = () if programmer is None else programmer.offered(self.attribute)
        held = chosen.values.get(self.attribute)
        lit = held.value if held is not None and isinstance(held.value, str) else None
        self.chips.display = bool(offered)
        self.none.display = not offered
        if offered:
            self.chips.show(option_buttons(self.attribute, offered, lit))
        else:
            text = none_text(self.attribute, chosen.first is not None)
            if self.none.content != text:
                self.none.update(text)

    def stops(self) -> list[Stop]:
        """A stop per chip."""
        return strip_stops(self.chips) if self.chips.display else []
