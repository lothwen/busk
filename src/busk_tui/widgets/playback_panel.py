"""F1's edit mode (``docs/plans/tui-pending-plan.md``, Phase 10): a grid of the
slots of the page shown, and the PLAYBACK panel.

A tile is a slot and the playback in it. A click selects that playback, as a
click on ``Pn`` does on the strips, and the panel shows the selected playback,
so ← → move it too. Nothing on the grid performs.

The panel shows what a playback holds, and each thing changes by one control
and one line:

* ``[rename…]`` and ``[number…]``: ``rename playback 9 "…"``, ``playback 9
  number 30``.
* ``[list…]``: a picker of the cue lists, ``playback 9 cuelist 11``. busk refuses
  that while the playback runs, so the button is grey then and the panel says why.
* ``[buttons…]``: its functions as words, in order, ``playback 9 buttons ["go",
  "flash"]``.
* A chip per word for what is one of a few: the fader, the LTP mode, ``[on]`` and
  ``[off]`` (``playback 9 autoStart false``).
* A dialog for each of the others (``playback 9 priority 70``), and ``[none]`` on
  what it can be without (``playback 9 exclusivity none``).

A value left as it was sends nothing.

Over the grid, the pages: a tab per page (``page 2``), ``[+ page…]`` (``page add
3 "Encore"``), and the shown page's ``[rename…]`` and ``[delete]`` (``delete page
2 cascade``, after busk's question). The grid has one empty tile past the last
slot, since a new page has none and ``ASSIGN_PLAYBACK`` adds them.

Under it, the row of the slot in hand, the one last clicked: ``[new playback…]``
on an empty one (``playback add 30 cuelist 9 at 2.7 "Encore"``), ``[place…]``
(``page 2 slot 7 playback 9``) and ``[clear]`` on a full one (``page 2 slot 7
clear``). Selecting another playback takes its slot in hand.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from operator import attrgetter
from typing import ClassVar, Final

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from busk_tui import colors, commands
from busk_tui.colors import ColorMode
from busk_tui.commands import Line, exact, quoted
from busk_tui.formats import numbers_text
from busk_tui.model import CueListInfo, LiveState, PageInfo, PlaybackInfo, ShowModel
from busk_tui.nav import Item, Stop
from busk_tui.widgets.controls import (
    MARKED,
    ActionButton,
    ButtonStrip,
    RunLine,
    StripButton,
    button_label,
)
from busk_tui.widgets.dialogs import (
    FormDialog,
    TextDialog,
    check_name,
    check_number,
    cue_key,
    dialog_css,
    next_number,
    read_whole,
)
from busk_tui.widgets.effect_panel import check_seconds
from busk_tui.widgets.fixture_panel import Setting, chips, put, read_level
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.playbacks import LABELS, PlaybackRow
from busk_tui.widgets.preset_panel import PANEL_WIDTH
from busk_tui.widgets.quick import strip_stops
from busk_tui.widgets.rows import cell
from busk_tui.widgets.tiles import TILE_WIDTH

FADERS: Final = ("master", "crossfade", "rate", "size", "temp", "none")
LTP_MODES: Final = ("followFader", "threshold", "ignoreFader")
FUNCTIONS: Final = tuple(LABELS)
ON_OFF: Final = ("on", "off")
NONE: Final = "none"

COLOUR: Final = re.compile(r"#[0-9a-fA-F]{6}")
"""The colours F1 can draw: anything else in a ``uiColor`` is only words."""

NO_PLAYBACK: Final = "no playback selected: click one in the slots"

TAB_NAME: Final = 16
"""The most of a page's name a tab shows, so that one tab cannot fill the row."""


def read_signed(text: str) -> int | None:
    """A whole number as typed, of any sign; ``None`` if it is not one."""
    value = read_whole(text.removeprefix("-"))
    return value if value is None or not text.startswith("-") else -value


def check_whole(text: str) -> str | None:
    return None if read_signed(text.strip()) is not None else "a whole number"


def whole_value(text: str) -> str:
    return str(read_signed(text))


def check_percent(text: str) -> str | None:
    return None if read_level(text) is not None else "a level from 0 to 100%"


def percent_value(text: str) -> str:
    """A level typed in percent as busk stores it, 0..1, in as few digits as
    it was typed: ``14.3`` over 100 is a long way from ``0.143`` in a float."""
    return exact(round(float(text.removesuffix("%")) / 100, 6))


def check_key(text: str) -> str | None:
    return None if text.strip() else "a key cannot be empty"


def check_colour(text: str) -> str | None:
    return None if COLOUR.fullmatch(text.strip()) else "a colour as #rrggbb"


def check_buttons(text: str) -> str | None:
    """A word per button, each of the nine. The typed word is not quoted back:
    a dialog's error is markup."""
    return None if set(text.split()) <= set(FUNCTIONS) else "each one of the words above"


def number_value(text: str) -> str:
    return exact(float(text))


def boost_text(info: PlaybackInfo) -> str | None:
    return None if info.flashBoost is None else str(info.flashBoost)


@dataclass(frozen=True, slots=True)
class Typed:
    """A setting typed in a dialog: ``playback N <prop> <value>``."""

    prop: str
    button: str
    read: Callable[[PlaybackInfo], str | None]  # what the dialog starts at; None: it has none
    check: Callable[[str], str | None]
    value: Callable[[str], str]  # what was typed, stripped, as busk reads it
    note: str = ""
    unit: str = ""  # after the value, in the panel
    optional: bool = False  # it has a [none]


TYPED: Final[dict[str, Typed]] = {
    "band": Typed(
        "priority",
        "band…",
        lambda info: str(info.priority),
        check_whole,
        whole_value,
        "its priority band: a higher band wins",
    ),
    "exclusive": Typed(
        "exclusivity",
        "key…",
        attrgetter("exclusivity"),
        check_key,
        quoted,
        "playbacks with the same key release each other",
        optional=True,
    ),
    "flash level": Typed(
        "flash.level",
        "level…",
        lambda info: f"{info.flashLevel * 100:g}",
        check_percent,
        percent_value,
        "0 to 100%",
        unit="%",
    ),
    "flash boost": Typed(
        "flash.priorityBoost",
        "boost…",
        boost_text,
        check_whole,
        whole_value,
        "added to its band while it flashes",
        optional=True,
    ),
    "threshold": Typed(
        "ltpThreshold",
        "level…",
        lambda info: f"{info.ltpThreshold * 100:g}",
        check_percent,
        percent_value,
        "the fader level where its LTP values come in",
        unit="%",
    ),
    "release": Typed(
        "releaseTime",
        "time…",
        lambda info: exact(info.releaseTime),
        check_seconds,
        number_value,
        "the seconds its LTP values take to fade back",
        unit=" s",
    ),
    "colour": Typed(
        "uiColor",
        "colour…",
        attrgetter("uiColorText"),
        check_colour,
        quoted,
        "as #rrggbb: what F1 draws it in while no cue gives a colour",
        optional=True,
    ),
}

TOGGLES: Final[dict[str, tuple[str, Callable[[PlaybackInfo], bool]]]] = {
    "flash LTP": ("flash.includeLtp", attrgetter("flashLtp")),
    "auto start": ("autoStart", attrgetter("autoStart")),
    "auto release": ("autoRelease", attrgetter("autoRelease")),
    "swop protect": ("protectFromSwop", attrgetter("protectFromSwop")),
}

ORDER: Final = (
    "cue list",
    "buttons",
    "fader",
    "band",
    "exclusive",
    "flash level",
    "flash LTP",
    "flash boost",
    "LTP mode",
    "threshold",
    "auto start",
    "auto release",
    "goto cue",
    "swop protect",
    "release",
    "colour",
)
"""The panel's rows, in reading order."""


def on_off_line(number: int, prop: str, word: str) -> Line:
    """A toggle's chip: ``playback 9 autoStart false``."""
    return commands.playback_setting(number, prop, "true" if word == "on" else "false")


def value_text(value: str | None, unit: str = "") -> Text:
    """What a row is set to: ``50``, ``2%``; ``none``, dim, when it has none."""
    return cell(NONE, colors.DIM) if value is None else cell(value + unit, colors.FG)


def colour_text(info: PlaybackInfo, mode: ColorMode) -> Text:
    """``██ #ff8000``; only the words for a colour F1 cannot draw; ``none``."""
    if info.uiColorText is None:
        return value_text(None)
    text = Text()
    if info.uiColor is not None:
        text.append("██ ", style=colors.swatch(info.uiColor, 1.0, mode))
    text.append(info.uiColorText, style=colors.FG)
    return text


def list_text(info: CueListInfo) -> Text:
    """A row of the picker: ``9 Song · 5 cues``, ``10 Chase · 4 cues · chase``."""
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(f"{info.number:>4} ", style=colors.CYAN)
    text.append(info.name, style=colors.FG)
    count = len(info.cues)
    text.append(f" · {count} cue{'' if count == 1 else 's'}", style=colors.DIM)
    if info.mode == "chase":
        text.append(" · chase", style=colors.DIM)
    return text


def slots_text(number: int, pages: Sequence[PageInfo]) -> str:
    """Where a playback sits, as ``at`` takes it: ``1.9 2.9``; ``""``: nowhere."""
    return " ".join(
        f"{page.number}.{slot}"
        for page in pages
        for slot, there in enumerate(page.slots, start=1)
        if there == number
    )


def playback_text(info: PlaybackInfo, pages: Sequence[PageInfo]) -> Text:
    """A row of the picker: ``9 Song · 1.9 2.9``, ``30 Encore · on no page``."""
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(f"{info.number:>4} ", style=colors.CYAN)
    text.append(info.name, style=colors.FG)
    text.append(f" · {slots_text(info.number, pages) or 'on no page'}", style=colors.DIM)
    return text


class PickDialog(ModalScreen[int | None]):
    """Closes with the number of one of ``rows``, or ``None``: ↑ ↓ move, Enter
    or a click chooses, Esc cancels. It starts on ``chosen``, else the first."""

    DEFAULT_CSS = (
        dialog_css("PickDialog")
        + f"""
    PickDialog > Vertical {{ width: 60; }}
    PickDialog OptionList, PickDialog OptionList:focus {{
        height: auto; max-height: 12; padding: 0; border: none; background: {colors.BG};
        background-tint: transparent; scrollbar-size-vertical: 1;
    }}
    PickDialog OptionList > .option-list--option-highlighted {{
        background: {colors.SEL}; text-style: none;
    }}
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, title: str, rows: Sequence[tuple[int, Text]], chosen: int | None) -> None:
        super().__init__()
        self.title_text = title
        self.numbers = [number for number, _ in rows]
        self.chosen = chosen
        self.options = OptionList(*(Option(text) for _, text in rows))

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = self.title_text
            yield self.options
            yield Static("↑ ↓: move · Enter: choose · Esc: cancel", classes="note")

    def on_mount(self) -> None:
        numbers = self.numbers
        self.options.highlighted = numbers.index(self.chosen) if self.chosen in numbers else 0
        self.options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(self.numbers[event.option_index])

    def action_cancel(self) -> None:
        self.dismiss(None)


class CueListDialog(PickDialog):
    """The cue lists, by number."""

    def __init__(self, title: str, lists: Sequence[CueListInfo], chosen: int | None) -> None:
        self.lists = sorted(lists, key=lambda info: info.number)
        super().__init__(title, [(info.number, list_text(info)) for info in self.lists], chosen)


class PlaybackDialog(PickDialog):
    """The playbacks, by number, each with where it sits."""

    def __init__(
        self,
        title: str,
        playbacks: Sequence[PlaybackInfo],
        pages: Sequence[PageInfo],
        chosen: int | None,
    ) -> None:
        rows = [(info.number, playback_text(info, pages)) for info in playbacks]
        super().__init__(title, rows, chosen)


class PlaybackPanel(Panel):
    """The PLAYBACK panel (see the module docs). The editor redraws it with
    :meth:`show_view`; ``leave`` is ``[done]``."""

    DEFAULT_CSS = f"""
    PlaybackPanel {{ width: {PANEL_WIDTH}; margin-left: 1; }}
    PlaybackPanel .pp-text {{ height: auto; }}
    PlaybackPanel #pp-names {{ height: 1; margin-bottom: 1; }}
    PlaybackPanel #pp-names > CommandButton {{ margin-right: 1; }}
    PlaybackPanel #pp-why {{ color: {colors.AMBER}; }}
    PlaybackPanel Setting > .fp-name {{ width: 13; }}
    PlaybackPanel Setting > .fp-value {{ width: 18; }}
    PlaybackPanel Setting.-words {{ height: auto; }}
    PlaybackPanel Setting.-words > .fp-value {{ height: auto; text-wrap: wrap; }}
    PlaybackPanel .pp-chips {{ height: auto; }}
    PlaybackPanel .pp-chips > .pp-name {{ width: 13; color: {colors.MID}; }}
    PlaybackPanel .pp-chips > ButtonStrip {{ width: 1fr; }}
    PlaybackPanel #pp-done {{ margin-top: 1; }}
    """

    def __init__(self, leave: Callable[[], None]) -> None:
        super().__init__("playback", id="playback-panel")
        self.show_model: ShowModel | None = None
        self.number: int | None = None
        self._shown: object = None
        self.hint = Static(Text(NO_PLAYBACK, style=colors.DIM), classes="pp-text")
        self.rename = ActionButton("rename…", self.ask_name)
        self.renumber = ActionButton("number…", self.ask_number)
        self.delete = ActionButton("delete", self.ask_delete, "danger")
        self.why = Static("", id="pp-why", classes="pp-text")
        self.settings: dict[str, Setting] = {
            "cue list": Setting("cue list", ActionButton("list…", self.ask_list)),
            "buttons": Setting("buttons", ActionButton("buttons…", self.ask_buttons)),
            "goto cue": Setting(
                "goto cue",
                ActionButton("goto…", self.ask_goto),
                ActionButton("none", partial(self.drop, "gotoCue")),
            ),
        }
        self.settings["buttons"].add_class("-words")
        for name, typed in TYPED.items():
            extra = [ActionButton(NONE, partial(self.drop, typed.prop))] if typed.optional else []
            self.settings[name] = Setting(
                name, ActionButton(typed.button, partial(self.ask, name)), *extra
            )
        self.strips: dict[str, ButtonStrip] = {
            name: ButtonStrip() for name in ("fader", "LTP mode", *TOGGLES)
        }
        self.body = Vertical(classes="pp-text")
        self.done = ActionButton("done", leave, id="pp-done")

    def compose(self) -> ComposeResult:
        yield self.hint
        with self.body:
            yield Horizontal(self.rename, self.renumber, self.delete, id="pp-names")
            for name in ORDER:
                if name in self.settings:
                    yield self.settings[name]
                else:
                    label = Static(name, classes="pp-name")
                    yield Horizontal(label, self.strips[name], classes="pp-chips")
                if name == "cue list":
                    yield self.why
        yield self.done

    # ------------------------------------------------------------ drawing

    def chosen(self) -> PlaybackInfo | None:
        """The playback the panel shows; ``None`` for one the show does not have."""
        if self.show_model is None or self.number is None:
            return None
        return self.show_model.playback(self.number)

    def show_view(
        self, show: ShowModel | None, live: LiveState | None, number: int, mode: ColorMode
    ) -> None:
        """Redraw with the show and the selected playback as they are now."""
        self.show_model, self.number = show, number
        info = self.chosen()
        cue_list = None if show is None or info is None else show.cue_list(info.cueList)
        view = None if live is None else live.playback(number)
        running = view is not None and view.state != "idle"
        shows = (info, cue_list, running, mode)
        if shows != self._shown:
            self._shown = shows
            self.hint.display = info is None
            self.body.display = info is not None
            if info is None:
                self.set_title("playback")
            else:
                self.draw(info, cue_list, running, mode)

    def draw(
        self, info: PlaybackInfo, cue_list: CueListInfo | None, running: bool, mode: ColorMode
    ) -> None:
        number = info.number
        self.set_title("playback", f"P{number} {info.name}")
        name = "" if cue_list is None else f" {cue_list.name}"
        put(self.settings["cue list"].value, cell(f"{info.cueList}{name}", colors.FG))
        self.settings["cue list"].buttons[0].change(inert=running)
        self.why.display = running
        put(self.why, Text(f"P{number} is running: release it to change its list"))
        put(self.settings["buttons"].value, value_text(" ".join(info.buttons) or None))
        setting = partial(commands.playback_setting, number)
        self.strips["fader"].show(chips(FADERS, info.fader, partial(setting, "fader")))
        modes = chips(LTP_MODES, info.ltpFaderMode, partial(setting, "ltpFaderMode"))
        self.strips["LTP mode"].show(modes)
        for label, (prop, read) in TOGGLES.items():
            lit = "on" if read(info) else "off"
            self.strips[label].show(chips(ON_OFF, lit, partial(on_off_line, number, prop)))
        for label, typed in TYPED.items():
            value = typed.read(info)
            put(self.settings[label].value, value_text(value, typed.unit))
            if typed.optional:
                self.settings[label].buttons[1].display = value is not None
        put(self.settings["colour"].value, colour_text(info, mode))
        goto = self.settings["goto cue"]
        put(goto.value, value_text(info.gotoCue))
        goto.buttons[0].change(inert=cue_list is None or not cue_list.cues)
        goto.buttons[1].display = info.gotoCue is not None

    # ------------------------------------------------------------ actions

    def _run(self, line: Line) -> None:
        self.post_message(RunLine(line))

    def ask_name(self) -> None:
        """``[rename…]``: ``rename playback 9 "Song"``."""
        info = self.chosen()
        if info is None:
            return

        def given(text: str | None) -> None:
            if text is not None and text.strip() != info.name:
                self._run(commands.rename_playback(info.number, text.strip()))

        title = f"RENAME · P{info.number}"
        self.app.push_screen(TextDialog(title, info.name, check_name(True)), given)

    def ask_number(self) -> None:
        """``[number…]``: ``playback 9 number 30``. The selection follows it."""
        info, show = self.chosen(), self.show_model
        if info is None or show is None:
            return
        taken = frozenset(other.number for other in show.playbacks)
        others = sorted(taken - {info.number})

        def given(text: str | None) -> None:
            if text is None or int(text.strip()) == info.number:
                return
            number = int(text.strip())

            def renumbered(ok: bool) -> None:
                if ok:
                    self.post_message(PlaybackRow.Chosen(number))

            line = commands.playback_setting(info.number, "number", str(number))
            self.post_message(RunLine(line, done=renumbered))

        title = f"NUMBER · P{info.number}"
        note = f"taken: {numbers_text(others)}" if others else ""
        check = check_number(taken, info.number)
        self.app.push_screen(TextDialog(title, str(info.number), check, note), given)

    def ask_delete(self) -> None:
        """``[delete]``: ``delete playback 9 cascade``, after busk's question.
        Its slots go empty, its cue list stays."""
        info = self.chosen()
        if info is not None:
            self._run(commands.delete_playback(info.number))

    def ask_list(self) -> None:
        """``[list…]``: the picker, ``playback 9 cuelist 11``."""
        info, show = self.chosen(), self.show_model
        if info is None or show is None:
            return

        def given(number: int | None) -> None:
            if number is not None and number != info.cueList:
                self._run(commands.playback_setting(info.number, "cuelist", str(number)))

        title = f"CUE LIST · P{info.number}"
        self.app.push_screen(CueListDialog(title, show.cueLists, info.cueList), given)

    def ask_buttons(self) -> None:
        """``[buttons…]``: ``playback 9 buttons ["go", "flash"]``. No words: no
        buttons."""
        info = self.chosen()
        if info is None:
            return

        def given(text: str | None) -> None:
            if text is not None and tuple(text.split()) != info.buttons:
                self._run(commands.playback_buttons(info.number, text.split()))

        title = f"BUTTONS · P{info.number}"
        note = f"in order, a space between: {' '.join(FUNCTIONS)}"
        start = " ".join(info.buttons)
        self.app.push_screen(TextDialog(title, start, check_buttons, note), given)

    def ask_goto(self) -> None:
        """``[goto…]``: ``playback 9 goto 4``, a cue of the list it runs."""
        info, show = self.chosen(), self.show_model
        cue_list = None if info is None or show is None else show.cue_list(info.cueList)
        if info is None or cue_list is None:
            return
        cues = {cue_key(cue.number) for cue in cue_list.cues}

        def check(text: str) -> str | None:
            return None if cue_key(text.strip()) in cues else f"a cue of list {cue_list.number}"

        def given(text: str | None) -> None:
            if text is not None and text.strip() != info.gotoCue:
                self._run(commands.playback_setting(info.number, "goto", text.strip()))

        title = f"GOTO CUE · P{info.number}"
        note = f"the cue of list {cue_list.number} its goto buttons go to"
        self.app.push_screen(TextDialog(title, info.gotoCue or "", check, note), given)

    def ask(self, name: str) -> None:
        """A setting's dialog (:data:`TYPED`)."""
        info = self.chosen()
        if info is None:
            return
        typed = TYPED[name]
        before = typed.read(info)

        def given(text: str | None) -> None:
            if text is None:
                return
            value = typed.value(text.strip())
            if before is None or value != typed.value(before):
                self._run(commands.playback_setting(info.number, typed.prop, value))

        title = f"{name.upper()} · P{info.number}"
        self.app.push_screen(TextDialog(title, before or "", typed.check, typed.note), given)

    def drop(self, prop: str) -> None:
        """``[none]``: ``playback 9 exclusivity none``."""
        info = self.chosen()
        if info is not None:
            self._run(commands.playback_setting(info.number, prop, NONE))

    # -------------------------------------------------------- pane cursor

    def stops(self) -> list[Stop]:
        """The panel's controls, in reading order (a grey one is none)."""
        stops: list[Stop] = []
        if self.chosen() is not None:
            for button in (self.rename, self.renumber, self.delete):
                stops.append(Stop(Item(button.label, action=button.action), button))
            for name in ORDER:
                if name in self.settings:
                    stops += self.settings[name].stops(name)
                else:
                    stops += strip_stops(self.strips[name])
        stops.append(Stop(Item(self.done.label, action=self.done.action), self.done))
        return stops


class SlotTile(Widget):
    """One slot: its number (dim) and the playback's on the first line, its name
    on the second. A click takes the slot in hand and selects its playback."""

    DEFAULT_CSS = f"""
    SlotTile {{ height: 4; border: solid {colors.TRACK}; padding: 0 1; }}
    SlotTile.-chosen {{ border: solid {colors.MAGENTA}; }}
    SlotTile:hover {{ border: solid {colors.CYAN}; background: {colors.BAR}; }}
    """

    class Picked(Message):
        """The operator took slot ``slot`` in hand; it holds ``number``."""

        def __init__(self, slot: int, number: int | None) -> None:
            super().__init__()
            self.slot = slot
            self.number = number

    def __init__(self, slot: int, info: PlaybackInfo | None) -> None:
        super().__init__()
        self.slot = slot
        self.info = info
        self.marked = False

    def mark(self, index: int | None) -> None:
        self.marked = index is not None
        self.refresh()

    def render(self) -> Text:
        slot = str(self.slot)
        if self.info is None:
            text = Text(f"{slot}\nempty", style=colors.BORDER)
        else:
            number = f"P{self.info.number}"
            text = Text(slot, style=colors.DIM)
            text.append(" " * max(1, self.size.width - len(slot) - len(number)))
            text.append(number, style=colors.CYAN)
            text.append("\n")
            text.append(self.info.name, style=colors.FG)
        if self.marked:
            text.stylize(MARKED)
        text.no_wrap = True
        text.overflow = "ellipsis"
        return text

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.pick()

    def pick(self) -> None:
        self.post_message(self.Picked(self.slot, None if self.info is None else self.info.number))


class SlotGrid(Container):
    """The tiles, as many to a line as fit."""

    DEFAULT_CSS = """
    SlotGrid {
        layout: grid; grid-size: 1; grid-columns: 1fr; grid-rows: 4; grid-gutter: 0 1;
        height: auto;
    }
    """

    def on_resize(self, event: events.Resize) -> None:
        columns = max(1, (event.size.width + 1) // TILE_WIDTH)
        if columns != self.styles.grid_size_columns:
            self.styles.grid_size_columns = columns
            self.styles.grid_columns = " ".join(["1fr"] * columns)


def in_hand(
    slot: int | None, slots: Sequence[int | None], selected: int, moved: bool
) -> int | None:
    """The slot the row under the grid is about: ``slot``, while the grid has it,
    unless the selection ``moved`` off what it holds (an empty one stays, so a
    second click on ``[clear]`` finds nothing to clear); else the first that
    holds the selected playback; else none. Only the selection moving can take
    the hand elsewhere: a new show or a slot's new playback may come before the
    selection does."""
    if slot is not None and slot <= len(slots):
        holds = slots[slot - 1]
        if holds is None or holds == selected or not moved:
            return slot
    return slots.index(selected) + 1 if selected in slots else None


def tab_word(page: PageInfo) -> str:
    """A page's tab: ``2 Washes``, a long name cut."""
    name = page.name if len(page.name) <= TAB_NAME else f"{page.name[: TAB_NAME - 1]}…"
    return f"{page.number} {name}"


def page_tabs(pages: Sequence[PageInfo], shown: PageInfo | None) -> list[StripButton]:
    """A chip per page, by number. The page shown is lit, and runs nothing."""
    numbers = {tab_word(page): page.number for page in sorted(pages, key=attrgetter("number"))}
    lit = "" if shown is None else tab_word(shown)
    return chips(tuple(numbers), lit, lambda word: commands.go_page(numbers[word]))


def ask(label: str, action: Callable[[], None], color: str = colors.MID) -> StripButton:
    """A button that calls ``action`` (one callable per button: equal buttons
    compare equal)."""
    return StripButton(button_label(label, color), Line(""), action=action)


def grey(label: str) -> StripButton:
    """A button with nothing to do: no click, no pane cursor."""
    return StripButton(Text(f"[{label}]", style=colors.BORDER), Line(""), note=True)


class PlaybackEditor(Horizontal):
    """F1's edit mode (see the module docs): SLOTS, and the PLAYBACK panel to
    the right of it at 100 columns or more, else under it."""

    DEFAULT_CSS = """
    PlaybackEditor { height: auto; }
    PlaybackEditor > #slots-panel { width: 1fr; }
    PlaybackEditor .slot-row { height: auto; }
    PlaybackEditor .slot-label { width: auto; max-width: 40%; padding-right: 1; }
    PlaybackEditor .slot-strip { width: 1fr; }
    PlaybackEditor #page-row { margin-bottom: 1; }
    PlaybackEditor #slot-row { margin-top: 1; }
    """

    def __init__(self, leave: Callable[[], None]) -> None:
        super().__init__(id="playback-editor")
        self.tabs = ButtonStrip(id="page-tabs")
        self.page_label = Static("", classes="slot-label")
        self.page_edits = ButtonStrip(classes="slot-strip")
        self.page_row = Horizontal(
            self.page_label, self.page_edits, id="page-row", classes="slot-row"
        )
        self.grid = SlotGrid()
        self.slot_label = Static("", classes="slot-label")
        self.slot_edits = ButtonStrip(classes="slot-strip")
        self.slot_row = Horizontal(
            self.slot_label, self.slot_edits, id="slot-row", classes="slot-row"
        )
        self.slots = Panel(
            "slots", self.tabs, self.page_row, self.grid, self.slot_row, id="slots-panel"
        )
        self.panel = PlaybackPanel(leave)
        self.tiles: list[SlotTile] = []
        self.shape: object = None
        self.rows: object = None
        self.lit: int | None = None
        self.show_model: ShowModel | None = None
        self.page: PageInfo | None = None
        self.numbers: tuple[int | None, ...] = ()  # what each tile holds
        self.selected = 0
        self.slot: int | None = None  # the slot in hand, from 1

    def compose(self) -> ComposeResult:
        yield self.slots
        yield self.panel

    def show_view(
        self,
        show: ShowModel | None,
        live: LiveState | None,
        slots: tuple[int | None, ...],
        page: PageInfo | None,
        selected: int,
        mode: ColorMode,
    ) -> None:
        """Redraw with what shows now."""
        if page is None or self.page is None or page.number != self.page.number:
            self.slot = None  # a slot of another page means nothing here
        spare = page is not None and (not slots or slots[-1] is not None)
        moved = selected != self.selected
        self.show_model, self.page, self.selected = show, page, selected
        self.numbers = (*slots, None) if spare else slots
        self.draw(moved)
        self.panel.show_view(show, live, selected, mode)

    def draw(self, moved: bool = False) -> None:
        """The tiles, built again only when what they say changes, not for each
        setting of a playback; the slot in hand; the rows. ``moved``: the
        selection has changed."""
        show, page = self.show_model, self.page
        infos = [None if show is None or n is None else show.playback(n) for n in self.numbers]
        shape = (page, tuple(None if i is None else (i.number, i.name) for i in infos))
        if shape != self.shape:
            self.shape = shape
            where = "click selects" if page is None else f"page {page.number} {page.name}"
            self.slots.set_title("slots", where)
            self.tiles = [SlotTile(slot, info) for slot, info in enumerate(infos, start=1)]
            self.grid.remove_children()
            self.grid.mount_all(self.tiles)
            self.lit = None
        self.slot = in_hand(self.slot, self.numbers, self.selected, moved)
        if self.slot != self.lit:
            self.lit = self.slot
            for tile in self.tiles:
                tile.set_class(tile.slot == self.slot, "-chosen")
        rows = (
            shape,
            self.slot,
            None if show is None else (show.pages, show.cueLists, show.playbacks),
        )
        if rows != self.rows:
            self.rows = rows
            self.draw_rows(show, page)

    def draw_rows(self, show: ShowModel | None, page: PageInfo | None) -> None:
        """The tabs, and the rows of the page shown and of the slot in hand."""
        pages = () if show is None else show.pages
        self.tabs.show([*page_tabs(pages, page), ask("+ page…", self.ask_add_page)])
        self.page_row.display = self.slot_row.display = page is not None
        if show is None or page is None:
            return
        label = Text("page ", style=colors.DIM)
        label.append(f"{page.number} {page.name}", style=colors.FG)
        put(self.page_label, label)
        delete = StripButton(button_label("delete", colors.RED), commands.delete_page(page.number))
        self.page_edits.show([ask("rename…", self.ask_rename_page), delete])
        if self.slot is None:
            put(self.slot_label, Text("click a slot", style=colors.DIM))
            self.slot_edits.show([])
            return
        info = self.tiles[self.slot - 1].info
        place = ask("place…", self.ask_place) if show.playbacks else grey("place…")
        label = Text(f"slot {self.slot} · ", style=colors.DIM)
        if info is None:
            label.append("empty", style=colors.DIM)
            new = (
                ask("new playback…", self.ask_new, colors.MAGENTA)
                if show.cueLists
                else grey("new playback…")
            )
            self.slot_edits.show([new, place])
        else:
            label.append(f"P{info.number} {info.name}", style=colors.FG)
            clear = commands.clear_slot(page.number, self.slot)
            self.slot_edits.show([place, StripButton(button_label("clear", colors.MID), clear)])
        put(self.slot_label, label)

    # ------------------------------------------------------------ actions

    def on_slot_tile_picked(self, message: SlotTile.Picked) -> None:
        """A tile's click: its slot in hand, its playback selected."""
        self.slot = message.slot
        if message.number is not None:
            self.post_message(PlaybackRow.Chosen(message.number))
        self.draw()

    def _placed(self, number: int, ok: bool) -> None:
        if ok:
            self.post_message(PlaybackRow.Chosen(number))

    def ask_new(self) -> None:
        """``[new playback…]``: a cue list, then a number and a name; one line,
        ``playback add 30 cuelist 9 at 2.7 "Encore"``. The new one is selected."""
        show, page, slot = self.show_model, self.page, self.slot
        if show is None or page is None or slot is None:
            return
        names = {info.number: info.name for info in show.cueLists}
        taken = frozenset(info.number for info in show.playbacks)
        check = check_number(taken, None)
        title = f"NEW PLAYBACK · {page.number}.{slot}"

        def named(cue_list: int, values: tuple[str, ...] | None) -> None:
            if values is not None:
                number, name = int(values[0].strip()), values[1].strip()
                line = commands.playback_add(number, cue_list, page.number, slot, name or None)
                self.post_message(RunLine(line, done=partial(self._placed, number)))

        def listed(cue_list: int | None) -> None:
            if cue_list is None:
                return
            note = "no name: busk names it Playback <number>"
            if taken:
                note = f"taken: {numbers_text(sorted(taken))}\n{note}"
            fields = (("number", str(next_number(taken))), ("name", names[cue_list]))
            dialog = FormDialog(title, fields, lambda values: check(values[0]), note)
            self.app.push_screen(dialog, partial(named, cue_list))

        self.app.push_screen(CueListDialog(title, show.cueLists, None), listed)

    def ask_place(self) -> None:
        """``[place…]``: the picker, ``page 2 slot 7 playback 9``. What the slot
        held stays in the show, and what it holds now is selected."""
        show, page, slot = self.show_model, self.page, self.slot
        if show is None or page is None or slot is None:
            return
        occupant = self.numbers[slot - 1]

        def given(number: int | None) -> None:
            if number is not None and number != occupant:
                line = commands.place_playback(page.number, slot, number)
                self.post_message(RunLine(line, done=partial(self._placed, number)))

        title = f"PLACE · {page.number}.{slot}"
        start = self.selected if occupant is None else occupant
        self.app.push_screen(PlaybackDialog(title, show.playbacks, show.pages, start), given)

    def ask_add_page(self) -> None:
        """``[+ page…]``: ``page add 3 "Encore"``. It stays on the page it was
        on: another page moves what the surfaces play, and its tab is a click."""
        show = self.show_model
        taken = frozenset(() if show is None else (page.number for page in show.pages))
        check = check_number(taken, None)

        def given(values: tuple[str, ...] | None) -> None:
            if values is not None:
                self.post_message(
                    RunLine(commands.page_add(int(values[0].strip()), values[1].strip() or None))
                )

        note = "no name: busk names it Page <number>"
        if taken:
            note = f"taken: {numbers_text(sorted(taken))}\n{note}"
        fields = (("number", str(next_number(taken))), ("name", ""))
        dialog = FormDialog("NEW PAGE", fields, lambda values: check(values[0]), note)
        self.app.push_screen(dialog, given)

    def ask_rename_page(self) -> None:
        """``[rename…]``: ``rename page 2 "Encore"``."""
        page = self.page
        if page is None:
            return

        def given(text: str | None) -> None:
            if text is not None and text.strip() != page.name:
                self.post_message(RunLine(commands.rename_page(page.number, text.strip())))

        title = f"RENAME · page {page.number}"
        self.app.push_screen(TextDialog(title, page.name, check_name(True)), given)

    # -------------------------------------------------------- pane cursor

    def stops(self) -> list[Stop]:
        """The pages, each tile, the slot's controls, the PLAYBACK panel's."""
        stops = strip_stops(self.tabs)
        if self.page is not None:
            stops += strip_stops(self.page_edits)
        for tile in self.tiles:
            info = tile.info
            label = f"slot {tile.slot}" if info is None else f"P{info.number} {info.name}"
            stops.append(Stop(Item(label, action=tile.pick), tile))
        if self.page is not None:
            stops += strip_stops(self.slot_edits)
        return stops + self.panel.stops()
