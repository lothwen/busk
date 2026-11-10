"""F4's timing forms (plan Phase 15): :class:`TimeDialog`, a cue's fade times
or one family's own, and :class:`CurveDialog`, its curve. Each starts at what
the cue holds and closes with the one line that changes it, the line F4's
pre-fills used to start: ``cue 9/3 time 1/3``, ``cue 9/3 time position 4
delay 1``, ``cue 9/3 time 1/3 easeIn``. The cue's fade times stay as they are
in a curve's line, and busk keeps the delay and the curve a line leaves out.
A family's line sets its timing whole, so it carries the family's own curve.
A form that changes nothing closes with ``None``.

The delays, a follow or a wait, and the name are a field or two, so F4 opens
:class:`~busk_tui.widgets.dialogs.FormDialog` and
:class:`~busk_tui.widgets.dialogs.TextDialog` for them, with the checks here.

Modal dialogs, because their fields are typed and only a modal has the
keyboard. They send nothing: each closes with its line, for the page to run.
"""

from __future__ import annotations

from typing import ClassVar, Final

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from busk_tui import colors, commands
from busk_tui.attributes import TIMING_FAMILIES
from busk_tui.commands import Line, exact, exact_pair
from busk_tui.model import CueInfo
from busk_tui.widgets.chase_dialog import plain_number
from busk_tui.widgets.dialogs import dialog_css
from busk_tui.widgets.route_dialog import PickRow, row

CUE: Final = "cue"
"""The TIME form's chip for the cue's own fade times."""

CURVES: Final = ("linear", "easeIn", "easeOut", "easeInOut", "snapStart", "snapEnd", "bezier")
"""The curves ``cue L/C time`` takes, ``bezier`` with four points."""

BEZIER: Final = "0.25 0.1 0.25 1"
"""Where the points start on a cue whose curve is not a Bézier."""

SECONDS: Final = "a time in seconds, such as 2 or 0.5"
POINTS: Final = "four numbers from 0 to 1: x1 y1 x2 y2"


def check_seconds(text: str) -> str | None:
    """A time's check: a number from 0, as busk reads one in ``cue L/C time``."""
    return None if plain_number(text.strip()) is not None else SECONDS


def check_times(values: tuple[str, ...]) -> str | None:
    """The first of ``values`` that is not a time."""
    return next((problem for value in values if (problem := check_seconds(value))), None)


def pair_words(first: str, second: str) -> str:
    """Two times as typed, as ``cue L/C time`` takes them: ``3`` when they
    are the same, else ``1/3``."""
    first, second = first.strip(), second.strip()
    return first if float(first) == float(second) else f"{first}/{second}"


def bezier_points(text: str) -> tuple[float, ...] | None:
    """``x1 y1 x2 y2`` as typed, each from 0 to 1, as busk keeps them;
    ``None`` if they are not."""
    values = [plain_number(word) for word in text.split()]
    if len(values) != 4 or any(value is None or value > 1 for value in values):
        return None
    return tuple(value for value in values if value is not None)


class CueDialog(ModalScreen[Line | None]):
    """A form of rows (:meth:`rows`) over what is wrong and the keys. Tab
    moves between the fields and the chips, ← → move the chips. Enter,
    anywhere, runs :meth:`problem`: what is wrong shows, and the dialog stays;
    else it closes with :meth:`line`. Esc cancels."""

    DEFAULT_CSS = (
        dialog_css("CueDialog")
        + f"""
    CueDialog > Vertical {{ width: 60; }}
    CueDialog Horizontal {{ width: 100%; height: auto; margin-top: 0; }}
    CueDialog .label {{ color: {colors.MID}; width: 8; }}
    CueDialog Input {{ width: 1fr; }}
    CueDialog PickRow {{ width: 1fr; }}
    CueDialog PickRow:focus {{ background: {colors.SEL}; }}
    CueDialog .error {{ color: {colors.RED}; width: 100%; height: auto; }}
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "ok", "OK", show=False),
    ]

    def __init__(self, title: str, cue_list: int, cue: CueInfo) -> None:
        super().__init__()
        self.title_text = f"{title} · cue {cue_list}/{cue.number}"
        self.cue_list = cue_list
        self.cue = cue
        self.error = Static("", classes="error")

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = self.title_text
            yield from self.rows()
            yield self.error
            yield Static("Tab: next · ← →: chips · Enter: OK · Esc: cancel", classes="note")

    def rows(self) -> ComposeResult:
        raise NotImplementedError

    def on_mount(self) -> None:
        self.draw()

    def draw(self) -> None:
        """The rows of what the chips say."""

    def on_pick_row_picked(self, message: PickRow.Picked) -> None:
        message.stop()
        self.error.update("")  # it may be of a field that just went
        self.draw()

    def problem(self) -> str | None:
        raise NotImplementedError

    def line(self) -> Line | None:
        """The line the fields make, once they pass; ``None``: they change nothing."""
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


class TimeDialog(CueDialog):
    """``[time…]``: for ``cue``, its fade in and out; for a family, that
    family's own fade and delay, which start at what it takes now (its own,
    else the cue's in)."""

    def __init__(self, cue_list: int, cue: CueInfo) -> None:
        super().__init__("TIME", cue_list, cue)
        self.own = {own.family: own for own in cue.families}
        self.target = PickRow({key: key for key in (CUE, *TIMING_FAMILIES)})
        self.fade_in = Input(exact(cue.fadeIn), compact=True)
        self.fade_out = Input(exact(cue.fadeOut), compact=True)
        self.fade = Input("", compact=True)
        self.delay = Input("", compact=True)
        self.note = Static("", classes="note")
        self.cue_rows = (row("in", self.fade_in), row("out", self.fade_out))
        self.family_rows = (row("fade", self.fade), row("delay", self.delay))

    def rows(self) -> ComposeResult:
        yield row("for", self.target)
        yield from self.cue_rows
        yield from self.family_rows
        yield self.note

    def on_mount(self) -> None:
        super().on_mount()
        self.fade_in.focus()

    def draw(self) -> None:
        family = self.target.chosen
        for found in self.cue_rows:
            found.display = family == CUE
        for found in self.family_rows:
            found.display = family != CUE
        if family == CUE:
            self.note.update(
                "in: intensity rising, and families without their own\nout: intensity falling"
            )
            return
        own = self.own.get(family)
        self.fade.value = exact(self.cue.fadeIn if own is None else own.fade)
        self.delay.value = exact(self.cue.delayIn if own is None else own.delay)
        if own is None:
            self.note.update(f"{family} takes the cue's in now")
        else:
            curve = "" if own.curve is None else f"\nits curve, {own.curve}, stays"
            self.note.update(f"{family}'s own, in place of the cue's{curve}")

    def fields(self) -> tuple[Input, Input]:
        """The two fields shown: in and out, or a family's fade and delay."""
        if self.target.chosen == CUE:
            return (self.fade_in, self.fade_out)
        return (self.fade, self.delay)

    def problem(self) -> str | None:
        return check_times(tuple(field.value for field in self.fields()))

    def line(self) -> Line | None:
        family, cue = self.target.chosen, self.cue
        first, second = (field.value.strip() for field in self.fields())
        if family == CUE:
            if (float(first), float(second)) == (cue.fadeIn, cue.fadeOut):
                return None
            return commands.cue_time(self.cue_list, cue.number, pair_words(first, second))
        own = self.own.get(family)
        if own is not None and (float(first), float(second)) == (own.fade, own.delay):
            return None
        return commands.cue_time(
            self.cue_list,
            cue.number,
            first,
            family=family,
            delay=second if float(second) else None,
            curve=None if own is None else own.curve,
        )


class CurveDialog(CueDialog):
    """``[curve…]``: the cue's curve, and with ``bezier`` its four points."""

    def __init__(self, cue_list: int, cue: CueInfo) -> None:
        super().__init__("CURVE", cue_list, cue)
        name, _, points = cue.curve.partition(" ")
        self.curve = PickRow({key: key for key in CURVES}, name if name in CURVES else None)
        self.points = Input(points or BEZIER, compact=True)
        self.points_row = row("points", self.points)

    def rows(self) -> ComposeResult:
        yield row("curve", self.curve)
        yield self.points_row

    def draw(self) -> None:
        self.points_row.display = self.curve.chosen == "bezier"

    def problem(self) -> str | None:
        if self.curve.chosen == "bezier" and bezier_points(self.points.value) is None:
            return POINTS
        return None

    def line(self) -> Line | None:
        chosen, cue = self.curve.chosen, self.cue
        if chosen == "bezier":
            points = bezier_points(self.points.value)
            name, _, before = cue.curve.partition(" ")
            if name == "bezier" and points == bezier_points(before):
                return None
            chosen = " ".join(["bezier", *self.points.value.split()])
        elif chosen == cue.curve:
            return None
        times = exact_pair(cue.fadeIn, cue.fadeOut)
        return commands.cue_time(self.cue_list, cue.number, times, curve=chosen)
