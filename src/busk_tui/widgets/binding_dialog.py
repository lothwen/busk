"""F9's binding form (``docs/plans/tui-pending-plan.md`` Phase 41): what
``bind`` takes after the surface, in three parts. Given a binding of the
show, it starts at what the binding holds and makes ``binding <id> change
…`` (busk's GAP-63) of the same words; a form that changes nothing sends
nothing.

- **The control**, by the surface's kind: on MIDI the chips ``cc``, ``note``
  and ``clock`` (no clock without a speed master: a clock only taps), a
  channel and a number; on OSC a path. ``[learn]`` fills them from the next
  control moved on the surface, passing a pitch bend and the clock over, as
  F9's own ``[learn]`` does; the page hands it the inputs.
- **What it drives**: the chips ``fader``, ``button``, ``master``, ``tap``,
  ``blackout``, ``page``, ``release all`` and ``output`` (no ``master``
  without a master, no ``tap`` without a speed master), then each one's
  fields: a slot or a playback; a slot and a button; the masters as chips,
  the grand master's ``gm``; the speed master, when the show has more than
  one; ``toggle`` or ``momentary``; ``+N``, ``-N`` or a page; a release
  time; on or off. A clock taps, and has no other chip.
- **Feedback**: ``none``, ``led``, ``motor`` and, on OSC, ``display``, on
  the control itself or on another, given as the control is (a clock's on
  another always: it has no address of its own).

The form checks what it can, as busk reads it: a channel from 1 to 16, a
number from 0 to 127, a path, a slot, a button and a playback from 1, a page
step or number, a time in seconds. busk refuses the rest (a playback or a
page the show has not), in the log, as for every control.

A modal dialog, because its fields are typed and only a modal has the
keyboard. It sends nothing: it closes with the line, for the page to run.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from typing import ClassVar, Final

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, Static

from busk_tui import colors, commands
from busk_tui.commands import Line
from busk_tui.model import BindingInfo, InputView, MasterView, ShowModel, SurfaceView
from busk_tui.widgets.chase_dialog import plain_number
from busk_tui.widgets.controls import ButtonStrip, StripButton
from busk_tui.widgets.cue_dialogs import check_seconds
from busk_tui.widgets.dialogs import dialog_css
from busk_tui.widgets.route_dialog import PickRow, row
from busk_tui.widgets.rows import cell

CONTROLS: Final = {"midi": ("cc", "note", "clock"), "osc": ("osc",)}
"""The controls each kind of surface sends, as ``bind`` takes them; the
other kinds take no binding."""

ACTIONS: Final = ("fader", "button", "master", "tap", "blackout", "page", "release all", "output")
"""What a binding drives, as ``bind`` takes it, and its chip."""

FEEDBACKS: Final = {"midi": ("none", "led", "motor"), "osc": ("none", "led", "motor", "display")}
"""The feedback each kind of surface takes (MIDI has no display)."""

PASSED_OVER: Final = frozenset({"bend", "clock"})
"""The inputs learn mode passes over: ``bind`` cannot take a pitch bend, and a
device sends the clock on its own."""

LEARN_LIT: Final = f"bold {colors.BG} on {colors.AMBER}"
"""``[learn]`` while armed: reversed, as a lit toggle."""

NUMBERS: Final = {"cc": "a CC number", "note": "a note number"}
A_PATH: Final = "/fader/1"
PAGE: Final = re.compile(r"[+-]\d+")
"""A page step, as busk reads it."""

FADER_OF: Final = {"slot": "slot", "playback": "playback"}
BLACKOUTS: Final = {"toggle": "toggle", "momentary": "momentary"}
OUTPUTS: Final = {"on": "on", "off": "off"}
WHERE: Final = {"own": "this control", "other": "another"}
TO_PAGE: Final = "+1, -1 or a page number"
RELEASE: Final = "empty: each playback's own release"
CLOCK_TAPS: Final = "tap: a clock taps the tempo"
LEARN_NOTE: Final = "the next control moved fills these"


def read_int(text: str) -> int | None:
    """A whole number as busk reads one (Python's ``int``: a sign, ``_``,
    any script's digits); ``None`` if it is not one."""
    try:
        return int(text)
    except ValueError:  # a paste past 4,300 digits too
        return None


def within(what: str, low: int, high: int | None = None) -> Callable[[str], str | None]:
    """A whole number's check, from ``low`` (to ``high``), as busk reads it."""
    words = f"{what} from {low}" + ("" if high is None else f" to {high}")

    def check(text: str) -> str | None:
        number = read_int(text.strip())
        if number is None or number < low or (high is not None and number > high):
            return words
        return None

    return check


check_channel = within("a MIDI channel", 1, 16)


def check_number(kind: str) -> Callable[[str], str | None]:
    """A CC's or a note's number: from 0 to 127."""
    return within(NUMBERS[kind], 0, 127)


def check_path(text: str) -> str | None:
    """An OSC path: busk takes one that starts with ``/``."""
    return None if text.strip().startswith("/") else f"an OSC path, such as {A_PATH}"


check_slot = within("a slot", 1)
check_button = within("a button", 1)
check_playback = within("a playback", 1)


def check_page(text: str) -> str | None:
    """``+N``, ``-N`` or a page number, as busk reads them."""
    given = text.strip()
    return None if PAGE.fullmatch(given) or given.isdecimal() else TO_PAGE


def check_release(text: str) -> str | None:
    """A release time: empty (each playback's own), or seconds."""
    return check_seconds(text) if text.strip() else None


def page_words(text: str) -> str:
    """A page as busk stores it: ``+1``, ``-2``, ``2``."""
    given = text.strip()
    return f"{int(given):+d}" if PAGE.fullmatch(given) else str(int(given))


def what_words(action: str, values: Sequence[str], masters: Sequence[MasterView]) -> str:
    """What a binding drives as ``bind`` takes it, from the form's chip and
    fields (as :class:`~busk_tui.model.BindingInfo` keeps them): ``fader 1``,
    ``fader playback 18``, ``button 1 2``, ``master gm``, ``master "FX"``,
    ``tap``, ``tap "Speed 2"`` (named when the show has several), ``blackout
    momentary``, ``page +1``, ``release all 2``, ``output off``."""
    match action:
        case "fader":
            of, number = values
            return f"fader {number}" if of == "slot" else f"fader playback {number}"
        case "button":
            return f"button {values[0]} {values[1]}"
        case "master":
            grand = next((m.name for m in masters if m.kind == "grand"), None)
            return "master gm" if values[0] == grand else f"master {commands.quoted(values[0])}"
        case "tap":
            speeds = sum(1 for m in masters if m.kind == "speed")
            return "tap" if speeds < 2 else f"tap {commands.quoted(values[0])}"
        case "blackout":
            return "blackout momentary" if values[0] == "momentary" else "blackout"
        case "release all":
            return f"release all {values[0]}" if values[0] else "release all"
    return f"{action} {values[0]}"  # page, output


def feedback_words(binding: BindingInfo) -> str:
    """A binding's feedback as ``bind`` takes it: ``led``, ``led note 1
    40``; ``""`` for none."""
    if not binding.feedback_kind or binding.feedback_to is None:
        return binding.feedback_kind
    return f"{binding.feedback_kind} {commands.control(*binding.feedback_to)}"


def binding_words(
    binding: BindingInfo, masters: Sequence[MasterView], to: str | None = None
) -> str:
    """What ``bind`` takes after the surface for ``binding``, as the form
    starts from it; with ``to`` (``cc 1 49``), moved to that control, what it
    drives and its feedback kept: a feedback on its own control follows it
    there."""
    control = commands.control(binding.kind, binding.channel, binding.number) if to is None else to
    what = what_words(binding.action, binding.values, masters)
    return " ".join(filter(None, [control, what, feedback_words(binding)]))


def control_parts(words: str) -> tuple[str, int | None, str]:
    """A control as busk words one (``cc 1 48``, ``osc "/fader/1"``), as
    :class:`~busk_tui.model.BindingInfo` keeps it: kind, channel, number."""
    kind, _, rest = words.partition(" ")
    if kind == "osc":
        return kind, None, json.loads(rest)
    if kind in ("cc", "note"):
        channel, number = rest.split()
        return kind, int(channel), number
    return kind, None, rest


def unworded(binding: BindingInfo, surface: SurfaceView | None) -> str | None:
    """Why the form cannot word ``binding``, one from a show file (so only
    ``[delete]`` takes it); ``None`` when it can."""
    kind = "" if surface is None else surface.kind
    sends = CONTROLS.get(kind)
    if surface is None or sends is None:
        on = "a web remote" if kind == "web" else f"a {kind} surface" if kind else "no surface"
        return f"a binding on {on} does nothing: [delete] removes it"
    if binding.kind not in sends:
        return f"{surface.name} does not send {binding.input}: [delete] removes it"
    if not binding.action:
        return f"bind cannot make {binding.what}: [delete] removes it"
    elsewhere = binding.feedback_to
    if binding.feedback_kind and binding.feedback_kind not in FEEDBACKS[kind]:
        return f"{surface.name} has no {binding.feedback_kind}: [delete] removes it"
    if elsewhere is not None and elsewhere[0] not in sends:
        return f"{surface.name} has no {commands.control(*elsewhere)}: [delete] removes it"
    return None


def _chosen(value: str, keys: Sequence[str]) -> str | None:
    """Where a row of chips starts: ``value``, if it is one of them."""
    return value if value in keys else None


class BindingDialog(ModalScreen[Line | None]):
    """Closes with a ``bind`` line for ``surface``, or with ``binding`` a
    ``binding <id> change`` line, or ``None`` (see the module docs). Tab moves
    between the fields and the chips, ← → move the chips. Enter, anywhere,
    runs the checks: what is wrong shows, and the dialog stays. Esc cancels."""

    DEFAULT_CSS = (
        dialog_css("BindingDialog")
        + f"""
    BindingDialog > Vertical {{ width: 64; }}
    BindingDialog Vertical Vertical {{ width: 100%; height: auto; }}
    BindingDialog Vertical .part {{ margin-top: 1; }}
    BindingDialog Horizontal {{ width: 100%; height: auto; margin-top: 0; }}
    BindingDialog .label {{ color: {colors.MID}; width: 11; }}
    BindingDialog Input {{ width: 1fr; }}
    BindingDialog PickRow {{ width: 1fr; }}
    BindingDialog PickRow:focus {{ background: {colors.SEL}; }}
    BindingDialog ButtonStrip {{ width: 1fr; }}
    BindingDialog .taps {{ color: {colors.DIM}; width: 1fr; }}
    BindingDialog .error {{ color: {colors.RED}; width: 100%; height: auto; }}
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "ok", "OK", show=False),
    ]

    def __init__(
        self, surface: SurfaceView, show: ShowModel | None, binding: BindingInfo | None = None
    ) -> None:
        super().__init__()
        self.surface = surface
        self.binding = binding
        self.masters = () if show is None else show.masters
        self.learning = False
        self.midi = surface.kind == "midi"
        kind = "MIDI" if self.midi else "OSC"
        if binding is None:
            self.title_text = Text(f"NEW BINDING · {commands.quoted(surface.name)} · {kind}")
        else:
            words = f"EDIT BINDING {binding.input} · {commands.quoted(surface.name)}"
            self.title_text = Text(words)
        speeds = [m for m in self.masters if m.kind == "speed"]
        start = binding or BindingInfo(surface.name, "", None, "", "", "")
        # the control
        controls = [c for c in CONTROLS["midi"] if speeds or c != "clock"]
        self.control = PickRow({c: c for c in controls}, _chosen(start.kind, controls))
        own = start.kind in ("cc", "note")
        self.channel = Input(str(start.channel) if own else "1", compact=True)
        self.number = Input(start.number if own else "0", compact=True)
        path = start.number if start.kind == "osc" else ""
        self.path = Input(path, placeholder=A_PATH, compact=True)
        self.learn = ButtonStrip()
        self.learn_note = LEARN_NOTE
        # what it drives
        values: dict[str, tuple[str, ...]] = {start.action: start.values}  # the others: defaults
        actions = [a for a in ACTIONS if (a != "master" or self.masters) and (a != "tap" or speeds)]
        self.action = PickRow({a: a for a in actions}, _chosen(start.action, actions))
        of, number = values.get("fader", ("slot", "1"))
        self.fader_of = PickRow(FADER_OF, of)
        self.fader_label = Static(of, classes="label")
        self.fader = Input(number, compact=True)
        slot, button = values.get("button", ("1", "1"))
        self.slot, self.button = Input(slot, compact=True), Input(button, compact=True)
        names = {m.name: "gm" if m.kind == "grand" else m.name for m in self.masters}
        (master,) = values.get("master", ("",))
        self.master = PickRow(names, _chosen(master, list(names))) if names else None
        taps = {m.name: m.name for m in speeds}
        (tap,) = values.get("tap", ("",))
        self.speed = PickRow(taps, _chosen(tap, list(taps))) if len(taps) > 1 else None
        (blackout,) = values.get("blackout", ("toggle",))
        self.blackout = PickRow(BLACKOUTS, blackout)
        (page,) = values.get("page", ("+1",))
        self.page = Input(page, placeholder=TO_PAGE, compact=True)
        (release,) = values.get("release all", ("",))
        self.release = Input(release, placeholder=RELEASE, compact=True)
        (output,) = values.get("output", ("on",))
        self.output = PickRow(OUTPUTS, output)
        # feedback
        feedbacks = FEEDBACKS[surface.kind]
        self.feedback = PickRow({f: f for f in feedbacks}, start.feedback_kind or "none")
        elsewhere = start.feedback_to
        self.where = PickRow(WHERE, "own" if elsewhere is None else "other")
        to_kind, to_channel, to_number = elsewhere or ("cc", 1, "0")
        to_midi = to_kind in ("cc", "note")
        self.to_control = PickRow({"cc": "cc", "note": "note"}, _chosen(to_kind, ("cc", "note")))
        self.to_channel = Input(str(to_channel) if to_midi else "1", compact=True)
        self.to_number = Input(to_number if to_midi else "0", compact=True)
        to_path = to_number if to_kind == "osc" else ""
        self.to_path = Input(to_path, placeholder=A_PATH, compact=True)
        self.error = Static("", classes="error")
        self._rows()
        self.held = None if binding is None else self.line()  # what the binding is now

    def _rows(self) -> None:
        """The rows, each shown by :meth:`_draw` when its chips call for it."""
        self.numbered = Vertical(row("channel", self.channel), row("number", self.number))
        self.midi_rows = Vertical(row("control", self.control), self.numbered)
        self.osc_row = row("path", self.path)
        self.action_row = row("drives", self.action)
        self.taps_row = row("drives", Static(CLOCK_TAPS, classes="taps"))
        self.fields: dict[str, Widget] = {
            "fader": Vertical(row("fader", self.fader_of), row(self.fader_label, self.fader)),
            "button": Vertical(row("slot", self.slot), row("button", self.button)),
            "blackout": row("blackout", self.blackout),
            "page": row("page", self.page),
            "release all": row("release", self.release),
            "output": row("output", self.output),
        }
        if self.master is not None:
            self.fields["master"] = row("master", self.master)
        if self.speed is not None:
            self.fields["tap"] = row("speed", self.speed)
        self.where_row = row("on", self.where)
        self.to_rows = Vertical(
            row("control", self.to_control),
            row("channel", self.to_channel),
            row("number", self.to_number),
        )
        self.to_path_row = row("path", self.to_path)

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = self.title_text
            with Vertical():
                yield self.midi_rows
                yield self.osc_row
                yield row("", self.learn)
            with Vertical(classes="part"):
                yield self.action_row
                yield self.taps_row
                yield from self.fields.values()
            with Vertical(classes="part"):
                yield row("feedback", self.feedback)
                yield self.where_row
                yield self.to_rows
                yield self.to_path_row
            yield self.error
            yield Static("Tab: next · ← →: chips · Enter: OK · Esc: cancel", classes="note")

    def on_mount(self) -> None:
        self._draw()
        self._draw_learn()
        (self.control if self.midi else self.path).focus()  # the first field shown

    def clock(self) -> bool:
        return self.midi and self.control.chosen == "clock"

    def chosen_action(self) -> str:
        """What the binding drives: a clock taps."""
        return "tap" if self.clock() else self.action.chosen

    def elsewhere(self) -> bool:
        """Whether its feedback lights another control: a clock's always."""
        return self.feedback.chosen != "none" and (self.clock() or self.where.chosen == "other")

    def _draw(self) -> None:
        """The rows the chips chosen call for."""
        clock, action = self.clock(), self.chosen_action()
        self.midi_rows.display = self.midi
        self.numbered.display = not clock
        self.osc_row.display = not self.midi
        self.action_row.display = not clock
        self.taps_row.display = clock
        for key, fields in self.fields.items():
            fields.display = key == action
        self.fader_label.update(self.fader_of.chosen)
        self.where_row.display = self.feedback.chosen != "none" and not clock
        self.to_rows.display = self.elsewhere() and self.midi
        self.to_path_row.display = self.elsewhere() and not self.midi

    # ------------------------------------------------------------ learn

    def _draw_learn(self) -> None:
        learn = cell("[learn]", LEARN_LIT if self.learning else colors.MID)  # a span: lit or not
        self.learn.show(
            [
                StripButton(learn, Line(""), action=self.toggle_learn),
                StripButton(Text(self.learn_note, style=colors.DIM), Line(""), note=True),
            ]
        )

    def toggle_learn(self) -> None:
        """``[learn]``: arm it, or disarm it."""
        self.learning = not self.learning
        name = commands.quoted(self.surface.name)
        self.learn_note = f"move a control on {name}…" if self.learning else LEARN_NOTE
        self._draw_learn()

    def learned(self, heard: InputView) -> None:
        """The control that came in, from the page (see the module docs):
        its fields filled, and learn mode disarmed."""
        kind, channel, number = control_parts(heard.input)
        if kind == "osc":
            self.path.value = number
        else:
            self.control.pick(kind)
            self.channel.value, self.number.value = str(channel), number
        self.learning = False
        drives = f" drives {', '.join(heard.drives)} already" if heard.drives else ""
        self.learn_note = f"learned {heard.input}{drives}"
        self._draw_learn()

    # ------------------------------------------------------------ check

    def on_pick_row_picked(self, message: PickRow.Picked) -> None:
        message.stop()
        self.error.update("")  # it may be of a field that just went
        self._draw()

    def problem(self) -> str | None:
        """What is wrong with the fields shown, first to last."""
        checks: list[tuple[Callable[[str], str | None], Input]] = []
        if not self.midi:
            checks.append((check_path, self.path))
        elif not self.clock():
            number = check_number(self.control.chosen)
            checks += [(check_channel, self.channel), (number, self.number)]
        match self.chosen_action():
            case "fader":
                slot = self.fader_of.chosen == "slot"
                checks.append((check_slot if slot else check_playback, self.fader))
            case "button":
                checks += [(check_slot, self.slot), (check_button, self.button)]
            case "page":
                checks.append((check_page, self.page))
            case "release all":
                checks.append((check_release, self.release))
        if self.elsewhere() and self.midi:
            to = self.to_control.chosen
            checks += [(check_channel, self.to_channel), (check_number(to), self.to_number)]
        elif self.elsewhere():
            checks.append((check_path, self.to_path))
        return next((found for check, field in checks if (found := check(field.value))), None)

    # ------------------------------------------------------------- line

    def line(self) -> Line:
        """The line the fields shown make, once they pass: their numbers as
        busk stores them (``07`` is sent ``7``)."""
        words = " ".join(filter(None, [self._control(), self._what(), self._feedback()]))
        if self.binding is None:
            return commands.bind(self.surface.name, words)
        return commands.binding_change(self.binding.id, words)

    def _control(self) -> str:
        if not self.midi:
            return commands.control("osc", None, self.path.value.strip())
        if self.clock():
            return "clock"
        return _midi(self.control.chosen, self.channel, self.number)

    def _what(self) -> str:
        action = self.chosen_action()
        values: tuple[str, ...]
        match action:
            case "fader":
                values = (self.fader_of.chosen, _whole(self.fader))
            case "button":
                values = (_whole(self.slot), _whole(self.button))
            case "master":
                values = ("" if self.master is None else self.master.chosen,)
            case "tap":
                values = ("" if self.speed is None else self.speed.chosen,)
            case "blackout":
                values = (self.blackout.chosen,)
            case "page":
                values = (page_words(self.page.value),)
            case "release all":
                time = plain_number(self.release.value.strip())
                values = ("" if time is None else commands.exact(time),)
            case _:
                values = (self.output.chosen,)
        return what_words(action, values, self.masters)

    def _feedback(self) -> str:
        kind = self.feedback.chosen
        if kind == "none":
            return ""
        if not self.elsewhere():
            return kind
        if self.midi:
            return f"{kind} {_midi(self.to_control.chosen, self.to_channel, self.to_number)}"
        return f"{kind} {commands.control('osc', None, self.to_path.value.strip())}"

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_ok()

    def action_ok(self) -> None:
        """The line, or ``None`` when it is what the binding is already."""
        problem = self.problem()
        if problem is None:
            line = self.line()
            self.dismiss(None if line == self.held else line)
        else:
            self.error.update(problem)

    def action_cancel(self) -> None:
        self.dismiss(None)


def _whole(field: Input) -> str:
    """A whole number typed in ``field``, as busk stores it."""
    number = read_int(field.value.strip())
    return field.value.strip() if number is None else str(number)


def _midi(kind: str, channel: Input, number: Input) -> str:
    return commands.control(kind, read_int(channel.value.strip()), _whole(number))
