"""Rate forms: :class:`RateDialog`, a rate in Hz or on a speed master's beat
(which master, when the show has several, and a multiplier), and
:class:`ChaseDialog`, F4's: what ``cuelist N chase`` takes, for one list.

A chase's rate comes with a direction and a crossfade. The form starts at the
settings the list keeps, and sending it makes the list a chase, as the line
does. A show with no speed master offers Hz only.

A modal dialog, because its fields are typed and only a modal has the keyboard.
It sends nothing: it closes with the line, for the page to run.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import ClassVar, Final

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from busk_tui import colors, commands
from busk_tui.commands import Line
from busk_tui.model import ChaseRate, CueListInfo
from busk_tui.widgets.dialogs import MAX_DIGITS, dialog_css
from busk_tui.widgets.route_dialog import PickRow, row

KINDS: Final = {"hz": "Hz", "bpm": "beat"}
DIRECTIONS: Final = {name: name for name in ("forward", "reverse", "bounce", "random")}

HZ: Final = "2"
"""Where the Hz field starts on a rate that is not in Hz."""

PLAIN: Final = re.compile(r"[0-9]+(?:\.[0-9]*)?|\.[0-9]+")
"""A number the line can carry as typed: no sign, no ``%``, no exponent."""


def plain_number(text: str) -> float | None:
    """``text`` as a number, if it is a :data:`PLAIN` one busk reads."""
    return float(text) if PLAIN.fullmatch(text) and len(text) <= MAX_DIGITS else None


def check_rate(text: str) -> str | None:
    value = plain_number(text.strip())
    return None if value is not None and value > 0 else "a rate above 0 Hz"


def check_multiplier(text: str) -> str | None:
    value = plain_number(text.strip())
    return None if value is not None and value > 0 else "a multiplier above 0"


def check_crossfade(text: str) -> str | None:
    value = plain_number(text.strip())
    return None if value is not None and value <= 1 else "a crossfade from 0 to 1"


class RateDialog(ModalScreen[Line | None]):
    """Closes with :meth:`line`, or ``None`` (see the module docs). Tab moves
    between the fields and the chips, ← → move the chips. Enter, anywhere,
    runs the checks: what is wrong shows, and the dialog stays. Esc cancels.
    Below the rate go the rows of :meth:`more`."""

    DEFAULT_CSS = (
        dialog_css("RateDialog")
        + f"""
    RateDialog > Vertical {{ width: 60; }}
    RateDialog Vertical Vertical {{ width: 100%; height: auto; }}
    RateDialog Horizontal {{ width: 100%; margin-top: 0; }}
    RateDialog .label {{ color: {colors.MID}; width: 11; }}
    RateDialog Input {{ width: 1fr; }}
    RateDialog PickRow {{ width: 1fr; }}
    RateDialog PickRow:focus {{ background: {colors.SEL}; }}
    RateDialog .error {{ color: {colors.RED}; width: 100%; height: auto; }}
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "ok", "OK", show=False),
    ]

    def __init__(self, title: str, rate: ChaseRate | None, masters: Sequence[str]) -> None:
        super().__init__()
        self.title_text = Text(title)
        in_hz = not masters or (rate is not None and rate.hz is not None)
        self.kind = PickRow(KINDS if masters else {"hz": KINDS["hz"]}, "hz" if in_hz else "bpm")
        self.hz = Input(
            HZ if rate is None or rate.hz is None else commands.exact(rate.hz), compact=True
        )
        self.master = (
            None
            if len(masters) < 2
            else PickRow(
                {name: name for name in masters},
                rate.master if rate is not None and rate.master in masters else None,
            )
        )
        multiple = "1" if rate is None or rate.hz is not None else commands.exact(rate.multiplier)
        self.multiplier = Input(multiple, compact=True)
        self.error = Static("", classes="error")
        self.hz_row = row("rate (Hz)", self.hz)
        self.master_row = None if self.master is None else row("master", self.master)
        self.multiplier_row = row("multiplier", self.multiplier)

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = self.title_text
            yield row("rate", self.kind)
            yield self.hz_row
            if self.master_row is not None:
                yield self.master_row
            yield self.multiplier_row
            yield from self.more()
            yield self.error
            yield Static("Tab: next · ← →: chips · Enter: OK · Esc: cancel", classes="note")

    def more(self) -> ComposeResult:
        """The rows under the rate."""
        return ()

    def on_mount(self) -> None:
        self._draw()

    def _draw(self) -> None:
        """The fields of the rate chosen."""
        in_hz = self.kind.chosen == "hz"
        self.hz_row.display = in_hz
        self.multiplier_row.display = not in_hz
        if self.master_row is not None:
            self.master_row.display = not in_hz

    def on_pick_row_picked(self, message: PickRow.Picked) -> None:
        message.stop()
        self.error.update("")  # it may be of a field that just went
        self._draw()

    def problem(self) -> str | None:
        """What is wrong with the fields shown, first to last."""
        if self.kind.chosen == "hz":
            return check_rate(self.hz.value)
        return check_multiplier(self.multiplier.value)

    def line(self) -> Line | None:
        """The line the fields shown make, once they pass; ``None``: none to run."""
        raise NotImplementedError

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


class ChaseDialog(RateDialog):
    """Closes with a ``cuelist N chase`` line, or ``None``."""

    def __init__(self, cue_list: CueListInfo, masters: Sequence[str]) -> None:
        rate = cue_list.rate
        super().__init__(f"CHASE · cuelist {cue_list.number} {cue_list.name}", rate, masters)
        self.number = cue_list.number
        self.direction = PickRow(DIRECTIONS, None if rate is None else rate.direction)
        self.crossfade = Input(commands.exact(cue_list.crossfade), compact=True)

    def more(self) -> ComposeResult:
        yield row("direction", self.direction)
        yield row("crossfade", self.crossfade)

    def problem(self) -> str | None:
        return super().problem() or check_crossfade(self.crossfade.value)

    def line(self) -> Line:
        direction, crossfade = self.direction.chosen, self.crossfade.value.strip()
        if self.kind.chosen == "hz":
            return commands.chase_settings(
                self.number, hz=self.hz.value.strip(), direction=direction, crossfade=crossfade
            )
        return commands.chase_settings(
            self.number,
            master=None if self.master is None else self.master.chosen,
            multiplier=self.multiplier.value.strip(),
            direction=direction,
            crossfade=crossfade,
        )
