"""The new fixture form of F3's FIXTURE panel (``docs/plans/tui-rig-plan.md``
§4 calls 9 and 10, §6.6): ``fixture add 302 thru 305 "Generic Spot 16ch" mode
"16ch" at 1.85``, built control by control.

* ``[choose…]`` opens the profile picker, and a chip per mode follows it, with
  the first lit.
* ``number`` starts at the show's highest plus one. ``[−]`` and ``[+]`` step over
  numbers that are not free for the whole count, and ``[number…]`` takes any
  free one. A taken number in the range makes ``[add]`` inert and is named.
* ``count``: how many, one after the other.
* PATCH (:mod:`busk_tui.widgets.patch_chooser`), for the whole block.
* ``[add]`` sends the line, and the form stays, with the next number and the
  next free address, because a rig goes in type by type. ``[done]`` leaves it.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache, partial

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.formats import numbers_text
from busk_tui.model import ModeInfo, ProfileChoice, ShowModel
from busk_tui.nav import Item, Stop
from busk_tui.widgets.controls import ActionButton, ButtonStrip, RunLine
from busk_tui.widgets.dialogs import TextDialog, check_number, free_step, next_number
from busk_tui.widgets.options import pick_chips
from busk_tui.widgets.patch_chooser import PatchChooser
from busk_tui.widgets.profile_picker import ProfileDialog
from busk_tui.widgets.quick import strip_stops


def mode_labels(modes: tuple[ModeInfo, ...]) -> dict[str, str]:
    """Each mode's chip, with what it takes when there are several to tell apart."""
    if len(modes) == 1:
        return {modes[0].name: modes[0].name}
    return {mode.name: f"{mode.name} · {mode.footprint}" for mode in modes}


def find_choice(show: ShowModel | None, name: str | None) -> ProfileChoice | None:
    """The profile ``fixture add`` takes under ``name``."""
    choices = () if show is None else show.choices
    return next((choice for choice in choices if choice.name == name), None)


def find_mode(choice: ProfileChoice | None, name: str | None) -> ModeInfo | None:
    """The mode ``name`` of ``choice``, else its first."""
    modes = () if choice is None else choice.modes
    return next((mode for mode in modes if mode.name == name), modes[0] if modes else None)


def range_text(first: int, last: int) -> str:
    """``302 thru 305``, or nothing for one fixture."""
    return "" if first == last else f"{first} thru {last}"


def taken_text(numbers: list[int]) -> str:
    """``303 is taken``, ``303–304 are taken``, or nothing."""
    if not numbers:
        return ""
    return f"{numbers_text(numbers)} {'is' if len(numbers) == 1 else 'are'} taken"


class FixtureForm(Vertical):
    """The form (see the module docs). The panel opens it with :meth:`open`
    and redraws it with :meth:`view`; ``leave`` is ``[done]``."""

    DEFAULT_CSS = f"""
    FixtureForm {{ height: auto; }}
    FixtureForm Horizontal {{ height: auto; }}
    FixtureForm .ff-name {{ width: 9; color: {colors.MID}; }}
    FixtureForm .ff-value {{ width: auto; margin-right: 1; }}
    FixtureForm .ff-range {{ width: 1fr; margin-left: 2; color: {colors.DIM}; }}
    FixtureForm ButtonStrip {{ width: 1fr; }}
    FixtureForm CommandButton {{ margin-right: 1; }}
    FixtureForm .ff-taken {{ height: auto; color: {colors.RED}; }}
    FixtureForm .ff-patch {{ margin-top: 1; color: {colors.CYAN}; }}
    FixtureForm .ff-end {{ margin-top: 1; }}
    """

    def __init__(self, leave: Callable[[], None]) -> None:
        super().__init__()
        self.show: ShowModel | None = None
        self.profile: str | None = None  # kept from one add to the next
        self.mode: str | None = None
        self.number = 1
        self.count = 1
        self.choose = ActionButton("choose…", self.ask_profile)
        self.modes = ButtonStrip()
        self.fewer_number = ActionButton("−", partial(self.step, -1))
        self.more_number = ActionButton("+", partial(self.step, 1))
        self.number_value = Static("", classes="ff-value")
        self.ask = ActionButton("number…", self.ask_number)
        self.fewer = ActionButton("−", partial(self.change_count, -1))
        self.more = ActionButton("+", partial(self.change_count, 1))
        self.count_value = Static("", classes="ff-value")
        self.range = Static("", classes="ff-range")
        self.taken_words = Static("", classes="ff-taken")
        self.patching = PatchChooser(self.draw)
        self.send = ActionButton("add", self.add, "go", inert=True)
        self.done = ActionButton("done", leave)
        self._picks = cache(lambda mode: partial(self.pick_mode, mode))

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static("profile", classes="ff-name")
            yield self.choose
        with Horizontal():
            yield Static("mode", classes="ff-name")
            yield self.modes
        with Horizontal():
            yield Static("number", classes="ff-name")
            yield self.fewer_number
            yield self.number_value
            yield self.more_number
            yield self.ask
        with Horizontal():
            yield Static("count", classes="ff-name")
            yield self.fewer
            yield self.count_value
            yield self.more
            yield self.range
        yield self.taken_words
        yield Static("PATCH", classes="ff-patch")
        yield self.patching
        with Horizontal(classes="ff-end"):
            yield self.send
            yield self.done

    # ------------------------------------------------------------ drawing

    def open(self, show: ShowModel | None, at: tuple[int, int] | None) -> None:
        """A new form: the profile last chosen, one fixture, the next number,
        at ``at``, else in the first universe's free room."""
        self.show = show
        self.count = 1
        self.number = next_number(self.taken())
        if at is not None:
            self.patching.start(*at)
        else:
            universes = () if show is None else show.universes
            self.patching.start(min((u.number for u in universes), default=None))

    def view(self, show: ShowModel | None) -> None:
        self.show = show
        self.draw()

    def choice(self) -> ProfileChoice | None:
        return find_choice(self.show, self.profile)

    def chosen_mode(self) -> ModeInfo | None:
        return find_mode(self.choice(), self.mode)

    def taken(self) -> frozenset[int]:
        """The numbers the show's fixtures have."""
        return frozenset(() if self.show is None else (f.number for f in self.show.fixtures))

    def blocked(self) -> frozenset[int]:
        """The numbers the block cannot start at."""
        return frozenset(number - by for number in self.taken() for by in range(self.count))

    def clash(self) -> list[int]:
        """The block's numbers that are taken."""
        taken = self.taken()
        block = range(self.number, self.number + self.count)
        return [number for number in block if number in taken]

    def draw(self) -> None:
        choice, mode = self.choice(), self.chosen_mode()
        self.choose.change(label="choose…" if choice is None else f"{choice.name}…")
        self.modes.display = choice is not None
        if choice is not None and mode is not None:
            self.modes.show(pick_chips(mode_labels(choice.modes), mode.name, self._picks))
        self.fewer_number.change(inert=self._stepped(-1) == self.number)
        self.fewer.change(inert=self.count == 1)
        last = self.number + self.count - 1
        for widget, words in (
            (self.number_value, str(self.number)),
            (self.count_value, str(self.count)),
            (self.range, range_text(self.number, last)),
            (self.taken_words, taken_text(self.clash())),
        ):
            if widget.content != words:
                widget.update(words)
        self.taken_words.display = bool(self.clash())
        self.patching.view(self.show, None if mode is None else mode.footprint * self.count)
        self.send.change(inert=not self.ready())

    def ready(self) -> bool:
        return self.chosen_mode() is not None and not self.clash() and self.patching.ready()

    # ------------------------------------------------------------ actions

    def ask_profile(self) -> None:
        """``[choose…]``: the picker, which sends nothing."""
        if self.show is None:
            return

        def given(name: str | None) -> None:
            if name is not None and name != self.profile:
                self.profile, self.mode = name, None
                self.draw()

        self.app.push_screen(ProfileDialog(self.show.choices, self.profile), given)

    def pick_mode(self, mode: str) -> None:
        self.mode = mode
        self.draw()

    def _stepped(self, by: int) -> int:
        return free_step(self.number, by, self.blocked())

    def step(self, by: int) -> None:
        """``[−]`` ``[+]`` by the number: to the next one free for the whole count."""
        self.number = self._stepped(by)
        self.draw()

    def change_count(self, by: int) -> None:
        self.count += by
        self.draw()

    def ask_number(self) -> None:
        """``[number…]``: any free number."""

        def given(text: str | None) -> None:
            if text is not None:
                self.number = int(text.strip())
                self.draw()

        taken = self.taken()
        note = f"taken: {numbers_text(sorted(taken))}" if taken else ""
        check = check_number(taken, None)
        self.app.push_screen(
            TextDialog("NUMBER · new fixture", str(self.number), check, note), given
        )

    def add(self) -> None:
        """``[add]``: one line. The form stays, for the next ones."""
        choice, mode = self.choice(), self.chosen_mode()
        if choice is None or mode is None:
            return
        last = self.number + self.count - 1

        def added(ok: bool) -> None:
            if ok:
                self.number = free_step(last, 1, self.blocked())
                self.patching.held = False
                self.draw()

        line = commands.fixture_add(self.number, last, choice.name, mode.name, self.patching.at)
        self.post_message(RunLine(line, done=added))

    # -------------------------------------------------------- pane cursor

    def stops(self) -> list[Stop]:
        """Its controls, in reading order (an inert one is none)."""
        stops = [Stop(Item(self.choose.label, action=self.ask_profile), self.choose)]
        if self.modes.display:
            stops += strip_stops(self.modes)
        for label, button in (
            ("number −", self.fewer_number),
            ("number +", self.more_number),
            ("number…", self.ask),
            ("count −", self.fewer),
            ("count +", self.more),
        ):
            if not button.inert:
                stops.append(Stop(Item(label, action=button.action), button))
        stops += self.patching.stops()
        if not self.send.inert:
            stops.append(Stop(Item("add", action=self.add), self.send))
        stops.append(Stop(Item("done", action=self.done.action), self.done))
        return stops
