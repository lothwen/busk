"""F5's EFFECT panel (``docs/plans/tui-pending-plan.md``, Phase 7): the settings
of the effect chosen in the table, one control per setting and one line per
change.

A cue's effect changes by its property: ``cue 9/4 effect rainbow size 0.5``.
A programmer effect has no such line, so a change restates it, with every other
setting as it is: ``effect add "Circle" id fx5 hz 2 forward size 15 …``.

* ``effect add`` takes its targets from the selection, so while the selection
  is not the effect's fixtures, in their order, its controls are grey and
  ``[its fixtures]`` selects them. Nothing moves an effect by surprise.
* A programmer effect on a group, or with one level of two, can come only from
  a binding, and no ``effect add`` line can say so: its controls stay grey.
* No line takes a setting away from a cue's effect: its ``[none]`` is grey
  while it has a master or a fade-in, and its levels only change. (GAP-41 of
  ``docs/dev/tui/engine-gaps.md``.) A fade-in of 0 is not none: without one, an
  effect comes in over its cue's time.

``effect add`` takes the two levels together, so a programmer effect has one
``[levels…]`` form; a cue's has ``[low…]`` and ``[high…]``, a line each.

The numbers are sent with every digit they hold, so a restated one is the same
number. A number given unchanged sends nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from operator import attrgetter
from typing import Final

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.commands import Line, exact, quoted
from busk_tui.formats import phase_text, selection_text, targets_text
from busk_tui.model import ChaseRate, EffectInfo, MasterView, ShowModel, Value
from busk_tui.nav import Item, Stop
from busk_tui.widgets.chase_dialog import RateDialog
from busk_tui.widgets.controls import ActionButton, ButtonStrip, RunLine
from busk_tui.widgets.dialogs import FormDialog, TextDialog, read_number, read_whole
from busk_tui.widgets.effects import FxRow
from busk_tui.widgets.fixture_panel import Setting, chips, put
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.preset_panel import PANEL_WIDTH
from busk_tui.widgets.quick import strip_stops
from busk_tui.widgets.rows import cell

type Selection = tuple[tuple[int, int], ...]

DIRECTIONS: Final = ("forward", "reverse", "bounce")
NONE: Final = "none"

BEAT_FOLLOWS: Final = "a beat rate follows its own master, whatever this says"
"""What a speed master does for an effect on a master's beat: nothing."""


def check_size(text: str) -> str | None:
    value = read_number(text)
    return None if value is not None and value >= 0 else "a size of 0 or more"


def check_seconds(text: str) -> str | None:
    value = read_number(text)
    return None if value is not None and value >= 0 else "seconds, 0 or more"


def check_count(text: str) -> str | None:
    value = read_whole(text.strip())
    return None if value is not None and value >= 1 else "a whole number from 1"


def check_level(text: str) -> str | None:
    return None if read_number(text) is not None else "a number"


def check_two(values: tuple[str, ...]) -> str | None:
    return None if all(read_number(value) is not None for value in values) else "two numbers"


@dataclass(frozen=True, slots=True)
class Number:
    """A setting that is one number."""

    option: str  # its word in ``effect add``
    prop: str  # a cue effect's property
    read: Callable[[EffectInfo], float | None]
    check: Callable[[str], str | None]
    note: str = ""


NUMBERS: Final[dict[str, Number]] = {
    "size": Number("size", "size", attrgetter("size"), check_size),
    "groups": Number(
        "groups",
        "groups",
        attrgetter("groups"),
        check_count,
        "phase groups the fixtures cycle through",
    ),
    "blocks": Number(
        "blocks",
        "blocks",
        attrgetter("blocks"),
        check_count,
        "fixtures in a row that share a phase",
    ),
    "wings": Number(
        "wings", "wings", attrgetter("wings"), check_count, "how many times the pattern mirrors"
    ),
    "fade-in": Number(
        "fadein",
        "sizeFadeIn",
        attrgetter("fadeIn"),
        check_seconds,
        "seconds its size takes to come in",
    ),
}


def effect_settings(info: EffectInfo) -> dict[str, str | None]:
    """Each setting ``effect add`` takes for ``info``, in its words."""
    pace, phase = info.pace, info.phase
    hz = None if pace.hz is None else exact(pace.hz)
    settings: dict[str, str | None] = {
        "rate": commands.effect_rate(hz, pace.master, exact(pace.multiplier)),
        "direction": info.direction,
        "size": f"size {exact(info.size)}",
        "low": None,
        "phase": f"phase {exact(phase[0])} {exact(phase[1])}",
        "groups": f"groups {info.groups}",
        "blocks": f"blocks {info.blocks}",
        "wings": f"wings {info.wings}",
    }
    if isinstance(info.low, float) and isinstance(info.high, float):
        settings["low"] = f"low {exact(info.low)} high {exact(info.high)}"
    if info.fadeIn is not None:
        settings["fadein"] = f"fadein {exact(info.fadeIn)}"
    if info.sizeMaster is not None:
        settings["sizemaster"] = f"sizemaster {quoted(info.sizeMaster)}"
    if info.speedMaster is not None:
        settings["speedmaster"] = f"speedmaster {quoted(info.speedMaster)}"
    return settings


def why_fixed(row: FxRow, selection: Selection) -> str | None:
    """Why this effect cannot change now, or ``None`` (see the module docs)."""
    info = row.info
    if row.cue is not None:
        return None
    if info.targets.group is not None or (info.low is None) != (info.high is None):
        return "no line can restate this effect"
    if not selection or selection != info.targets.elements:
        return "effect add takes the selection: select its fixtures to change it"
    return None


def levels_text(low: Value | None, high: Value | None) -> Text:
    """``0 to 1``, ``0 to none``, or ``none``."""
    if low is None and high is None:
        return cell(NONE, colors.DIM)
    words = [f"{value:g}" if isinstance(value, float) else NONE for value in (low, high)]
    return cell(" to ".join(words), colors.FG)


def number_text(value: float | None) -> Text:
    return cell(NONE, colors.DIM) if value is None else cell(f"{value:g}", colors.FG)


def start(value: Value | None, otherwise: str) -> str:
    """What a level's field starts at."""
    return exact(value) if isinstance(value, float) else otherwise


class EffectRateDialog(RateDialog):
    """An effect's rate: ``make`` turns the fields into the line."""

    def __init__(
        self,
        title: str,
        rate: ChaseRate,
        masters: Sequence[str],
        make: Callable[[str | None, str | None, str], Line | None],
    ) -> None:
        super().__init__(title, rate, masters)
        self.make = make

    def line(self) -> Line | None:
        master = None if self.master is None else self.master.chosen
        if self.kind.chosen == "hz":  # the other fields are hidden, and need not be numbers
            return self.make(self.hz.value.strip(), master, "1")
        return self.make(None, master, self.multiplier.value.strip())


class EffectPanel(Panel):
    """The EFFECT panel (see the module docs). The page shows it while an
    effect is chosen, and redraws it with :meth:`show_view`; ``leave`` is
    ``[done]``."""

    DEFAULT_CSS = f"""
    EffectPanel {{ width: {PANEL_WIDTH}; margin-left: 1; }}
    EffectPanel .ep-text {{ height: auto; }}
    EffectPanel #ep-what {{ margin-bottom: 1; }}
    EffectPanel #ep-why {{ color: {colors.AMBER}; }}
    EffectPanel #ep-its {{ margin-bottom: 1; }}
    EffectPanel .ep-chips {{ height: auto; }}
    EffectPanel Setting > .fp-name {{ width: 13; }}
    EffectPanel Setting > .fp-value {{ width: 18; }}
    EffectPanel .ep-chips > .ep-name {{ width: 13; color: {colors.MID}; }}
    EffectPanel .ep-chips > ButtonStrip {{ width: 1fr; }}
    EffectPanel #ep-note {{ color: {colors.DIM}; }}
    EffectPanel #ep-done {{ margin-top: 1; }}
    """

    def __init__(self, leave: Callable[[], None]) -> None:
        super().__init__("effect", id="effect-panel")
        self.row: FxRow | None = None
        self.show_model: ShowModel | None = None
        self.selection: Selection = ()
        self.what = Static("", id="ep-what", classes="ep-text")
        self.why = Static("", id="ep-why", classes="ep-text")
        self.its = ActionButton("its fixtures", self.select_its, "go", id="ep-its")
        self.rate = Setting("rate", ActionButton("rate…", self.ask_rate))
        self.direction = ButtonStrip()
        self.no_fade = ActionButton("none", self.drop_fade)
        self.numbers = {
            name: Setting(
                name,
                ActionButton(f"{name}…", partial(self.ask_number, name)),
                *([self.no_fade] if name == "fade-in" else []),
            )
            for name in NUMBERS
        }
        self.low = ActionButton("low…", partial(self.ask_level, "low"))
        self.high = ActionButton("high…", partial(self.ask_level, "high"))
        self.both = ActionButton("levels…", self.ask_levels)
        self.levels = Setting("low, high", self.low, self.high, self.both)
        self.phase = Setting("phase", ActionButton("phase…", self.ask_phase))
        self.size_masters = ButtonStrip()
        self.speed_masters = ButtonStrip()
        self.size_row = Horizontal(
            Static("size master", classes="ep-name"), self.size_masters, classes="ep-chips"
        )
        self.speed_row = Horizontal(
            Static("speed master", classes="ep-name"), self.speed_masters, classes="ep-chips"
        )
        self.note = Static(BEAT_FOLLOWS, id="ep-note", classes="ep-text")
        self.done = ActionButton("done", leave, id="ep-done")

    def settings(self) -> list[tuple[str, Setting]]:
        """The rows of one setting that come before the masters, in order
        (the direction's chips come after the rate's)."""
        numbers = [(name, self.numbers[name]) for name in ("groups", "blocks", "wings", "fade-in")]
        return [
            ("rate", self.rate),
            ("size", self.numbers["size"]),
            ("levels", self.levels),
            ("phase", self.phase),
            *numbers,
        ]

    def compose(self) -> ComposeResult:
        yield self.what
        yield self.why
        yield self.its
        yield self.rate
        yield Horizontal(Static("direction", classes="ep-name"), self.direction, classes="ep-chips")
        for _, setting in self.settings()[1:]:
            yield setting
        yield self.size_row
        yield self.speed_row
        yield self.note
        yield self.done

    # ------------------------------------------------------------ drawing

    def show_view(self, row: FxRow | None, show: ShowModel | None, selection: Selection) -> None:
        """Redraw with the effect chosen and the show as they are now."""
        self.row, self.show_model, self.selection = row, show, selection
        if row is not None:
            self.draw(row)

    def masters(self, kind: str) -> list[MasterView]:
        found = () if self.show_model is None else self.show_model.masters
        return [master for master in found if master.kind == kind]

    def draw(self, row: FxRow) -> None:
        info = row.info
        self.set_title("effect", f"{row.owner} {info.id}")
        fixtures = () if self.show_model is None else self.show_model.fixtures
        what = Text(info.template, style=colors.FG)
        what.append(f" · {targets_text(info.targets, fixtures)}", style=colors.CYAN)
        put(self.what, what)
        why = why_fixed(row, self.selection)
        self.why.display = why is not None
        put(self.why, Text("" if why is None else why, style=colors.AMBER))
        self.its.display = why is not None and bool(info.targets.elements)
        for _, setting in self.settings():
            for button in setting.buttons:
                button.change(inert=why is not None)
        put(self.rate.value, cell(info.rate, colors.FG))
        self.direction.show(chips(DIRECTIONS, info.direction, self._direction_line))
        for name, number in NUMBERS.items():
            put(self.numbers[name].value, number_text(number.read(info)))
        put(self.levels.value, levels_text(info.low, info.high))
        self.low.display = self.high.display = row.cue is not None
        self.both.display = row.cue is None
        self.no_fade.display = info.fadeIn is not None
        self.no_fade.change(inert=why is not None or row.cue is not None)
        put(self.phase.value, cell(phase_text(info.phase), colors.FG))
        self._draw_masters(self.size_row, self.size_masters, "size", info.sizeMaster)
        self._draw_masters(self.speed_row, self.speed_masters, "speed", info.speedMaster)
        self.note.display = info.pace.hz is None

    def _draw_masters(
        self, row: Horizontal, strip: ButtonStrip, kind: str, chosen: str | None
    ) -> None:
        names = [master.name for master in self.masters(kind)]
        row.display = bool(names)
        strip.show(chips((NONE, *names), chosen or NONE, partial(self._master_line, kind)))

    # -------------------------------------------------------------- lines

    def _line(self, option: str, words: str | None, prop: str, value: str | None) -> Line | None:
        """The one line that changes a setting. A programmer effect's: the
        whole effect, with ``option`` now ``words`` (``None``: left out). A
        cue's: its property ``prop`` at ``value`` (``None``: no line does
        that). ``None`` when no line can run."""
        row = self.row
        if row is None or why_fixed(row, self.selection) is not None:
            return None
        if row.cue is None:
            settings = effect_settings(row.info) | {option: words}
            words_of = [word for word in settings.values() if word is not None]
            return commands.effect_replace(row.info.template, row.info.id, words_of)
        return None if value is None else commands.cue_effect(*row.cue, row.info.id, prop, value)

    def _direction_line(self, word: str) -> Line | None:
        return self._line("direction", word, "direction", word)

    def _master_line(self, kind: str, name: str) -> Line | None:
        """A chip of the ``kind`` masters; ``none`` leaves the effect without one."""
        option, prop = f"{kind}master", f"{kind}MasterId"
        if name == NONE:
            return self._line(option, None, prop, None)
        master = next(found for found in self.masters(kind) if found.name == name)
        return self._line(option, f"{option} {quoted(name)}", prop, quoted(master.id))

    def _rate_line(self, hz: str | None, master: str | None, multiplier: str) -> Line | None:
        """What the rate form makes of its fields; nothing if it is the same rate."""
        row = self.row
        if row is None:
            return None
        rate, times = None if hz is None else float(hz), float(multiplier)
        pace = row.info.pace
        same_beat = (master, times) == (pace.master, pace.multiplier)
        if rate == pace.hz and (rate is not None or same_beat):
            return None
        hz_words = None if rate is None else exact(rate)
        speeds = self.masters("speed")
        named = next((found.id for found in speeds if found.name == master), None)
        master_id = named or (speeds[0].id if speeds else "")
        words = commands.effect_rate(hz_words, master, exact(times))
        value = commands.rate_json(hz_words, master_id, exact(times))
        return self._line("rate", words, "rate", value)

    def _run(self, line: Line | None) -> None:
        if line is not None:
            self.post_message(RunLine(line))

    # ------------------------------------------------------------ dialogs

    def ask_number(self, name: str) -> None:
        """``[size…]``, ``[groups…]`` and the like: one number, one line."""
        row = self.row
        if row is None:
            return
        number = NUMBERS[name]
        before = number.read(row.info)

        def given(text: str | None) -> None:
            if text is not None and float(text) != before:
                value = exact(float(text))
                self._run(self._line(number.option, f"{number.option} {value}", number.prop, value))

        title = f"{name.upper()} · {row.owner} {row.info.id}"
        value = exact(float(before or 0))
        self.app.push_screen(TextDialog(title, value, number.check, number.note), given)

    def drop_fade(self) -> None:
        """``[none]``: a programmer effect comes in over its fade time again."""
        self._run(self._line("fadein", None, "sizeFadeIn", None))

    def ask_rate(self) -> None:
        """``[rate…]``: the rate form."""
        row = self.row
        if row is None:
            return
        names = [master.name for master in self.masters("speed")]
        title = f"RATE · {row.owner} {row.info.id}"
        self.app.push_screen(
            EffectRateDialog(title, row.info.pace, names, self._rate_line), self._run
        )

    def ask_level(self, name: str) -> None:
        """A cue's ``[low…]`` or ``[high…]``."""
        row = self.row
        if row is None:
            return
        before = getattr(row.info, name)

        def given(text: str | None) -> None:
            if text is not None and float(text) != before:
                self._run(self._line(name, None, name, exact(float(text))))

        title = f"{name.upper()} · {row.owner} {row.info.id}"
        self.app.push_screen(TextDialog(title, start(before, "0"), check_level), given)

    def ask_levels(self) -> None:
        """A programmer effect's ``[levels…]``: ``effect add`` takes the two together."""
        row = self.row
        if row is None:
            return
        info = row.info

        def given(values: tuple[str, ...] | None) -> None:
            if values is not None and (float(values[0]), float(values[1])) != (info.low, info.high):
                low, high = exact(float(values[0])), exact(float(values[1]))
                self._run(self._line("low", f"low {low} high {high}", "low", None))

        title = f"LEVELS · {row.owner} {info.id}"
        fields = (("low", start(info.low, "0")), ("high", start(info.high, "1")))
        self.app.push_screen(FormDialog(title, fields, check_two), given)

    def ask_phase(self) -> None:
        """``[phase…]``: where the spread starts and ends, in degrees."""
        row = self.row
        if row is None:
            return
        phase = row.info.phase

        def given(values: tuple[str, ...] | None) -> None:
            if values is not None and (float(values[0]), float(values[1])) != phase:
                first, last = exact(float(values[0])), exact(float(values[1]))
                words = f"phase {first} {last}"
                self._run(self._line("phase", words, "phase", commands.phase_json(first, last)))

        title = f"PHASE · {row.owner} {row.info.id}"
        fields = (("from", exact(phase[0])), ("to", exact(phase[1])))
        self.app.push_screen(FormDialog(title, fields, check_two, "in degrees"), given)

    def select_its(self) -> None:
        """``[its fixtures]``: the effect's fixtures, in its order, selected."""
        row, show = self.row, self.show_model
        if row is not None and show is not None and row.info.targets.elements:
            elements = selection_text(row.info.targets.elements, show.fixtures)
            self._run(commands.sel_targets(elements))

    # -------------------------------------------------------- pane cursor

    def stops(self) -> list[Stop]:
        if self.row is None:
            return []
        stops: list[Stop] = []
        if self.its.display:
            stops.append(Stop(Item(self.its.label, action=self.select_its), self.its))
        stops += self.rate.stops("rate")
        stops += strip_stops(self.direction)
        for name, setting in self.settings()[1:]:
            stops += setting.stops(name)
        if self.size_row.display:
            stops += strip_stops(self.size_masters)
        if self.speed_row.display:
            stops += strip_stops(self.speed_masters)
        stops.append(Stop(Item(self.done.label, action=self.done.action), self.done))
        return stops
