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
from busk_tui.widgets.controls import MARKED, ActionButton, ButtonStrip, RunLine
from busk_tui.widgets.dialogs import (
    TextDialog,
    check_name,
    check_number,
    cue_key,
    dialog_css,
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


class CueListDialog(ModalScreen[int | None]):
    """Closes with a cue list's number, or ``None``: ↑ ↓ move, Enter or a click
    chooses, Esc cancels. It starts on ``chosen``."""

    DEFAULT_CSS = (
        dialog_css("CueListDialog")
        + f"""
    CueListDialog > Vertical {{ width: 60; }}
    CueListDialog OptionList, CueListDialog OptionList:focus {{
        height: auto; max-height: 12; padding: 0; border: none; background: {colors.BG};
        background-tint: transparent; scrollbar-size-vertical: 1;
    }}
    CueListDialog OptionList > .option-list--option-highlighted {{
        background: {colors.SEL}; text-style: none;
    }}
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, title: str, lists: Sequence[CueListInfo], chosen: int) -> None:
        super().__init__()
        self.title_text = title
        self.lists = sorted(lists, key=lambda info: info.number)
        self.chosen = chosen
        self.options = OptionList(*(Option(list_text(info)) for info in self.lists))

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = self.title_text
            yield self.options
            yield Static("↑ ↓: move · Enter: choose · Esc: cancel", classes="note")

    def on_mount(self) -> None:
        numbers = [info.number for info in self.lists]
        self.options.highlighted = numbers.index(self.chosen) if self.chosen in numbers else 0
        self.options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(self.lists[event.option_index].number)

    def action_cancel(self) -> None:
        self.dismiss(None)


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
            yield Horizontal(self.rename, self.renumber, id="pp-names")
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
            for button in (self.rename, self.renumber):
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
    on the second. A click selects the playback; an empty slot does nothing."""

    DEFAULT_CSS = f"""
    SlotTile {{ height: 4; border: solid {colors.TRACK}; padding: 0 1; }}
    SlotTile.-chosen {{ border: solid {colors.MAGENTA}; }}
    SlotTile.-full:hover {{ border: solid {colors.CYAN}; background: {colors.BAR}; }}
    """

    def __init__(self, slot: int, info: PlaybackInfo | None) -> None:
        super().__init__(classes="" if info is None else "-full")
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
        if self.info is not None:
            self.post_message(PlaybackRow.Chosen(self.info.number))


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


class PlaybackEditor(Horizontal):
    """F1's edit mode (see the module docs): SLOTS, and the PLAYBACK panel to
    the right of it at 100 columns or more, else under it."""

    DEFAULT_CSS = """
    PlaybackEditor { height: auto; }
    PlaybackEditor > #slots-panel { width: 1fr; }
    """

    def __init__(self, leave: Callable[[], None]) -> None:
        super().__init__(id="playback-editor")
        self.grid = SlotGrid()
        self.slots = Panel("slots", self.grid, id="slots-panel")
        self.panel = PlaybackPanel(leave)
        self.tiles: list[SlotTile] = []
        self.shape: object = None
        self.selected: int | None = None

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
        """Redraw with what shows now. The tiles are built again only when
        what they say changes, not for each setting of a playback."""
        infos = [None if show is None or n is None else show.playback(n) for n in slots]
        shape = (page, tuple(None if i is None else (i.number, i.name) for i in infos))
        if shape != self.shape:
            self.shape = shape
            where = "click selects" if page is None else f"page {page.number} {page.name}"
            self.slots.set_title("slots", where)
            self.tiles = [SlotTile(slot, info) for slot, info in enumerate(infos, start=1)]
            self.grid.remove_children()
            self.grid.mount_all(self.tiles)
            self.selected = None
        if selected != self.selected:
            self.selected = selected
            for tile in self.tiles:
                tile.set_class(tile.info is not None and tile.info.number == selected, "-chosen")
        self.panel.show_view(show, live, selected, mode)

    def stops(self) -> list[Stop]:
        """Each playback's tile, then the PLAYBACK panel's controls."""
        stops = []
        for tile in self.tiles:
            if tile.info is not None:
                number = tile.info.number
                item = Item(f"P{number} {tile.info.name}", action=partial(self.choose, number))
                stops.append(Stop(item, tile))
        return stops + self.panel.stops()

    def choose(self, number: int) -> None:
        self.post_message(PlaybackRow.Chosen(number))
