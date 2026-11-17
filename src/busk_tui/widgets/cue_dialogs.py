"""F4's timing forms (plan Phase 15): :class:`TimeDialog`, a cue's fade times
or one family's own, and :class:`CurveDialog`, its curve. Each starts at what
the cue holds and closes with the one line that changes it, the line F4's
pre-fills used to start: ``cue 9/3 time 1/3``, ``cue 9/3 time position 4
delay 1``, ``cue 9/3 time 1/3 easeIn``. The cue's fade times stay as they are
in a curve's line, and busk keeps the delay and the curve a line leaves out.
A family's line sets its timing whole, so it carries the family's own curve.
On a family with timing of its own, TIME's ``[none]`` (Ctrl+N) closes with
``cue 9/3 time position none``, which takes that timing away whole, so the
family fades with the cue again. A form that changes nothing closes with
``None``.

**Timing per target** (pending plan Phase 30, GAP-48). After a family, TIME's
``on`` row has ``[all]``, the family's own timing as above, then a chip for
each target the cue's entries of that family are on (``[Heads]``,
``[301]``). On a target the form has the fade and its ``to``, the delay and
its ``to``, and the fan's shape (``[linear]`` ``[centre]`` ``[edges]``), and
closes with ``cue 9/2 time group 1 position 4 delay 0 to 2``: a ``to`` fans
the time over the targets in their order. ``[none]`` closes with ``cue 9/2
time group 1 position none``, and the targets take the family's timing again.
The line sets that timing whole, so it carries the entry's own curve.

The delays, a follow or a wait, and the name are a field or two, so F4 opens
:class:`~busk_tui.widgets.dialogs.FormDialog` and
:class:`~busk_tui.widgets.dialogs.TextDialog` for them, with the checks here.

Modal dialogs, because their fields are typed and only a modal has the
keyboard. They send nothing: each closes with its line, for the page to run.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import ClassVar, Final

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from busk_tui import attributes, colors, commands
from busk_tui.attributes import TIMING_FAMILIES
from busk_tui.commands import Line, exact, exact_pair
from busk_tui.formats import selection_text, targets_text
from busk_tui.model import CueInfo, EntryTiming, FixtureInfo
from busk_tui.widgets.chase_dialog import plain_number
from busk_tui.widgets.controls import ActionButton
from busk_tui.widgets.dialogs import dialog_css
from busk_tui.widgets.route_dialog import PickRow, row

CUE: Final = "cue"
"""The TIME form's chip for the cue's own fade times."""

ALL: Final = "all"
"""The TIME form's ``on`` chip for a family's own timing, on all its targets."""

FANS: Final = {"linear": "linear", "center": "centre", "edges": "edges"}
"""busk's word for each shape of a fan, and its chip's label, as F6's spread
rows have them."""

TO: Final = "to: a time in seconds, such as 2; empty: no fan"
FAN_NEEDS_TO: Final = "{} shapes a fan: give the fade or the delay a to"

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


@dataclass(frozen=True, slots=True)
class OnTargets:
    """Targets that a cue's entries of one family are on, as TIME offers them."""

    label: str  # a group's name, or the elements: Heads, 101 thru 104
    words: str  # as the line takes them: group 1, fixture 101 thru 104
    timing: EntryTiming | None  # the own timing of the first entry on them that has one


def entry_targets(
    cue: CueInfo, family: str, fixtures: Sequence[FixtureInfo]
) -> dict[str, OnTargets]:
    """The targets of the cue's entries of ``family``, by their words, in
    the order stored. Entries on the same targets (pan and tilt, or a list
    in another order) are one, as busk's line takes them together."""
    found: dict[object, OnTargets] = {}
    for value in cue.values:
        targets = value.targets
        if attributes.family_of(value.attribute) != family:
            continue
        key: object
        if targets.group is not None:
            key, words = ("group", targets.group.number), f"group {targets.group.number}"
        elif targets.elements:
            key = frozenset(targets.elements)
            words = commands.targets(selection_text(targets.elements, fixtures))
        else:
            continue  # its fixtures are gone
        before = found.get(key)
        if before is None:
            found[key] = OnTargets(targets_text(targets, fixtures), words, value.timing)
        elif before.timing is None and value.timing is not None:
            found[key] = replace(before, timing=value.timing)
    return {on.words: on for on in found.values()}


def fan_shape(timing: EntryTiming | None) -> str:
    """The shape of the fan ``timing`` makes, as TIME's chips show it:
    ``linear`` where it has no ``to``, since a shape then does nothing."""
    if timing is None or (timing.fadeTo is None and timing.delayTo is None):
        return "linear"
    return timing.fan if timing.fan in FANS else "linear"


def _seconds(text: str) -> float | None:
    """A ``to`` field: its time, ``None`` when empty."""
    return float(text) if text else None


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
    CueDialog > Vertical > .note {{ width: 100%; }}
    CueDialog .none > .note {{ margin-left: 1; width: 1fr; }}
    CueDialog .to {{ color: {colors.MID}; width: 4; padding-left: 1; }}
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
    else the cue's in); on a family's targets (``on``), their own fade and
    delay, each with a ``to`` for a fan, and the fan's shape. ``[none]``, or
    Ctrl+N, on a family or targets with timing of their own closes with the
    line that takes it away. ``fixtures``: the show's, to name targets."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+n", "none", "None", show=False),
    ]

    def __init__(self, cue_list: int, cue: CueInfo, fixtures: Sequence[FixtureInfo] = ()) -> None:
        super().__init__("TIME", cue_list, cue)
        self.own = {own.family: own for own in cue.families}
        self.target = PickRow({key: key for key in (CUE, *TIMING_FAMILIES)})
        self.targets = {
            family: found
            for family in TIMING_FAMILIES
            if (found := entry_targets(cue, family, fixtures))
        }
        self.on = {
            family: PickRow({ALL: ALL} | {key: on.label for key, on in found.items()})
            for family, found in self.targets.items()
        }
        self.on_rows = {family: row("on", pick) for family, pick in self.on.items()}
        self.fade_in = Input(exact(cue.fadeIn), compact=True)
        self.fade_out = Input(exact(cue.fadeOut), compact=True)
        self.fade = Input("", compact=True)
        self.fade_to = Input("", compact=True)
        self.delay = Input("", compact=True)
        self.delay_to = Input("", compact=True)
        self.fan = PickRow(FANS)
        self.note = Static("", classes="note")
        self.cue_rows = (row("in", self.fade_in), row("out", self.fade_out))
        tos = (Static("to", classes="to"), Static("to", classes="to"))
        self.to_parts = (tos[0], self.fade_to, tos[1], self.delay_to)
        self.family_rows = (
            Horizontal(Static("fade", classes="label"), self.fade, tos[0], self.fade_to),
            Horizontal(Static("delay", classes="label"), self.delay, tos[1], self.delay_to),
        )
        self.fan_row = row("fan", self.fan)
        self.none = ActionButton("none", self.action_none)
        self.none_note = Static("", classes="note")
        self.none_row = Horizontal(self.none, self.none_note, classes="none")
        self.where: tuple[str, str] | None = None  # the family and targets the fields hold

    def rows(self) -> ComposeResult:
        yield row("for", self.target)
        yield from self.on_rows.values()
        yield from self.cue_rows
        yield from self.family_rows
        yield self.fan_row
        yield self.note
        yield self.none_row

    def on_mount(self) -> None:
        super().on_mount()
        self.fade_in.focus()

    def chosen(self) -> OnTargets | None:
        """The targets chosen on the ``on`` row; ``None``: the cue, or all."""
        pick = self.on.get(self.target.chosen)
        if pick is None or pick.chosen == ALL:
            return None
        return self.targets[self.target.chosen][pick.chosen]

    def draw(self) -> None:
        """The rows of what the chips say. The fields fill in with what the
        cue holds only when the family or the targets change, so that the
        fan's chips keep what was typed."""
        family, on = self.target.chosen, self.chosen()
        for name, found in self.on_rows.items():
            found.display = name == family
        for found in self.cue_rows:
            found.display = family == CUE
        for found in self.family_rows:
            found.display = family != CUE
        for part in (*self.to_parts, self.fan_row):
            part.display = on is not None
        where = (family, "" if on is None else on.words)
        fill, self.where = where != self.where, where
        if family == CUE:
            self.none_row.display = False
            self.note.update(
                "in: intensity rising, and families without their own\nout: intensity falling"
            )
        elif on is None:
            self._draw_family(family, fill)
        else:
            self._draw_targets(family, on, fill)

    def _draw_family(self, family: str, fill: bool) -> None:
        own = self.own.get(family)  # never the cue's: it is no family
        self.none_row.display = own is not None
        self.none_note.update(f"Ctrl+N · {family} fades with the cue again")
        if fill:
            self.fade.value = exact(self.cue.fadeIn if own is None else own.fade)
            self.delay.value = exact(self.cue.delayIn if own is None else own.delay)
        if own is None:
            self.note.update(f"{family} takes the cue's in now")
        else:
            curve = "" if own.curve is None else f"\nits curve, {own.curve}, stays"
            self.note.update(f"{family}'s own, in place of the cue's{curve}")

    def _draw_targets(self, family: str, on: OnTargets, fill: bool) -> None:
        """Targets' own timing: it starts at what they take now, the
        family's own, else the cue's in, and without a fan."""
        own, mine = self.own.get(family), on.timing
        if own is None:
            now, instead, back = "the cue's in", "the cue's", "the cue"
        else:
            now = instead = back = f"{family}'s own"
        self.none_row.display = mine is not None
        self.none_note.update(f"Ctrl+N · on {on.label}, {family} fades with {back} again")
        if fill:
            fade = self.cue.fadeIn if own is None else own.fade
            delay = self.cue.delayIn if own is None else own.delay
            tos: tuple[float | None, float | None] = (None, None)
            if mine is not None:
                fade = fade if mine.fade is None else mine.fade
                delay = delay if mine.delay is None else mine.delay
                tos = (mine.fadeTo, mine.delayTo)
            self.fade.value, self.delay.value = exact(fade), exact(delay)
            self.fade_to.value, self.delay_to.value = (
                "" if to is None else exact(to) for to in tos
            )
            if (shape := fan_shape(mine)) != self.fan.chosen:
                self.fan.pick(shape)
        if mine is None:
            first = f"on {on.label}, {family} takes {now} now"
        else:
            first = f"on {on.label}, {family}'s own, in place of {instead}"
        notes = [first, "to: a fan from the first target to the last"]
        if mine is not None and mine.curve is not None:
            notes.append(f"its curve, {mine.curve}, stays")
        self.note.update("\n".join(notes))

    def action_none(self) -> None:
        """``[none]``: the own timing of the chosen family or targets goes;
        not while the button is hidden (the cue, or none of their own)."""
        if not self.none_row.display:
            return
        family, on = self.target.chosen, self.chosen()
        if on is None:
            self.dismiss(commands.no_family_time(self.cue_list, self.cue.number, family))
        else:
            self.dismiss(commands.no_entry_time(self.cue_list, self.cue.number, on.words, family))

    def fields(self) -> tuple[Input, Input]:
        """The two fields shown: in and out, or a family's fade and delay."""
        if self.target.chosen == CUE:
            return (self.fade_in, self.fade_out)
        return (self.fade, self.delay)

    def problem(self) -> str | None:
        times = check_times(tuple(field.value for field in self.fields()))
        if times is not None or self.chosen() is None:
            return times
        tos = [field.value.strip() for field in (self.fade_to, self.delay_to)]
        if any(to and check_seconds(to) for to in tos):
            return TO
        if self.fan.chosen != "linear" and not any(tos):
            return FAN_NEEDS_TO.format(FANS[self.fan.chosen])
        return None

    def line(self) -> Line | None:
        family, cue = self.target.chosen, self.cue
        first, second = (field.value.strip() for field in self.fields())
        if family == CUE:
            if (float(first), float(second)) == (cue.fadeIn, cue.fadeOut):
                return None
            return commands.cue_time(self.cue_list, cue.number, pair_words(first, second))
        on = self.chosen()
        if on is not None:
            return self._targets_line(family, on, first, second)
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

    def _targets_line(self, family: str, on: OnTargets, fade: str, delay: str) -> Line | None:
        """``cue 9/2 time group 1 position 4 delay 0 to 2``, the times as
        typed; ``None`` when the targets hold that timing already."""
        fade_to, delay_to = (field.value.strip() for field in (self.fade_to, self.delay_to))
        fan, mine = self.fan.chosen, on.timing
        typed = (float(fade), _seconds(fade_to), float(delay), _seconds(delay_to), fan)
        if mine is not None and typed == (
            mine.fade,
            mine.fadeTo,
            mine.delay,
            mine.delayTo,
            fan_shape(mine),
        ):
            return None
        return commands.entry_time(
            self.cue_list,
            self.cue.number,
            on.words,
            family,
            fade,
            fade_to=fade_to or None,
            delay=delay if float(delay) else None,
            delay_to=delay_to or None,
            fan=None if fan == "linear" else fan,
            curve=None if mine is None else mine.curve,
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
