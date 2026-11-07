"""F3's FIXTURE panel (``docs/plans/tui-rig-plan.md`` §6.4, §6.5): the fixture
chosen in edit mode.

* Nothing chosen: how to choose one.
* ``[+ add]``: the new fixture form (:mod:`busk_tui.widgets.fixture_form`) in
  the panel's place, until its ``[done]``, or a click chooses a fixture.
* ``[rename…]`` and ``[number…]``, each a dialog and then one line
  (``rename fixture 102 "…"``, ``fixture 102 number 150``), and ``[delete]``:
  ``delete fixture 102 cascade``, after busk's question, which says what goes.
* What it is: its profile, mode and channels, and where the profile has two
  modes or more, a chip per mode (``fixture 102 mode "8ch"``). ``[profile…]``
  opens the picker, then shows that profile's modes and ``[change]``:
  ``fixture 102 profile "RGB Par 3ch" mode "3ch"``.
* Its profile's category, which every fixture of the profile shares: a chip
  per word (``profile "Generic Spot 16ch" category wash``).
* PATCH (:mod:`busk_tui.widgets.patch_chooser`): where it is, a choice of where
  to put it, and ``[patch]``: ``fixture 102 patch 1.85``, or ``… patch none``.
* LIMITS: a row per limit the fixture can use (pan and tilt where the profile
  takes them, intensity always). ``[limit…]`` is a form that starts at the
  limit, else at the profile's range; ``[none]`` removes that limit, and
  ``[no limits]`` all of them.
* ORIENTATION, where the profile takes pan or tilt: ``[invert pan]``,
  ``[invert tilt]`` and, with both, ``[swap pan/tilt]``, toggles that send at
  once, and an ``[offset…]`` dialog for each axis.
* LOCATION: its place, ``[location…]``, a form of the six values, and
  ``[no place]``.
* ``[done]`` leaves edit mode.

Two reaches (the plan's §4 call 4). The header, the mode, the profile, PATCH and
the location act on the chosen fixture. LIMITS and ORIENTATION act on every selected fixture
while the chosen one is selected, as their headings say: a ``thru`` line per run
of the show's numbers that are all selected.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from functools import cache, partial
from typing import Final

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.commands import Line
from busk_tui.formats import numbers_text, runs
from busk_tui.model import (
    FixtureInfo,
    Limits,
    Location,
    ModeInfo,
    ProfileChoice,
    ProfileInfo,
    ShowModel,
)
from busk_tui.nav import Item, Stop
from busk_tui.widgets.controls import ActionButton, ButtonStrip, RunLine, StripButton
from busk_tui.widgets.dialogs import (
    FormDialog,
    TextDialog,
    check_name,
    check_number,
    read_number,
)
from busk_tui.widgets.fixture_form import FixtureForm, find_choice, find_mode, mode_labels
from busk_tui.widgets.fixturetable import profile_text
from busk_tui.widgets.options import LIT, pick_chips
from busk_tui.widgets.patch_chooser import PatchChooser, channels_text, span_text
from busk_tui.widgets.preset_panel import PANEL_WIDTH
from busk_tui.widgets.profile_picker import ProfileDialog
from busk_tui.widgets.quick import strip_stops
from busk_tui.widgets.rows import cell

CATEGORIES: Final = (*colors.CATEGORY_COLORS, "none")
"""What ``profile "<name>" category`` takes (a test holds it to busk's)."""

AXES: Final = ("pan", "tilt")

TOGGLES: Final[dict[str, tuple[str, tuple[str, ...]]]] = {
    "invertPan": ("invert pan", ("pan",)),
    "invertTilt": ("invert tilt", ("tilt",)),
    "swapPanTilt": ("swap pan/tilt", AXES),
}
"""Each toggle's ``orientation`` key, its label and the attributes it needs."""

OFFSETS: Final[dict[str, str]] = {"panOffset": "pan", "tiltOffset": "tilt"}
"""Each offset's ``orientation`` key and its axis."""

PLACE: Final = ("x", "y", "z", "rx", "ry", "rz")
"""The fields of a location, in :data:`busk_tui.model.Location`'s order."""


def spans_text(spans: Iterable[tuple[int, int]]) -> str:
    """``101 thru 102, 201``."""
    return ", ".join(str(a) if a == b else f"{a} thru {b}" for a, b in spans)


def heading(title: str, spans: Sequence[tuple[int, int]], count: int) -> Text:
    """What a section acts on: ``LIMITS · 101 thru 102 (2)``."""
    text = Text(title, style=colors.CYAN)
    text.append(f" · {spans_text(spans)}", style=colors.FG)
    if count > 1:
        text.append(f" ({count})", style=colors.DIM)
    return text


def chips(words: Sequence[str], lit: str, line: Callable[[str], Line]) -> list[StripButton]:
    """A chip per word, each running ``line(word)``. The ``lit`` one is reversed
    and runs nothing: busk would spend an undo step on it, or refuse it."""
    buttons = []
    for word in words:
        label = Text()
        label.append(f"[{word}]", style=LIT if word == lit else colors.MID)
        if word == lit:
            buttons.append(StripButton(label, Line(""), note=True))
        else:
            buttons.append(StripButton(label, line(word)))
    return buttons


def what_text(fixture: FixtureInfo) -> Text:
    """``Generic Spot 16ch · 16ch · 16 channels``."""
    text = Text(profile_text(fixture), style=colors.FG)
    text.append(f" · {fixture.mode} · {channels_text(fixture.footprint)}", style=colors.DIM)
    return text


def swap_text(choice: ProfileChoice, mode: ModeInfo) -> Text:
    """What ``[change]`` would make of the fixture: ``to RGB Par 3ch · 3 channels``."""
    text = Text("to ", style=colors.DIM)
    text.append(choice.name, style=colors.FG)
    text.append(f" · {channels_text(mode.footprint)}", style=colors.DIM)
    return text


def patch_heading(fixture: FixtureInfo) -> Text:
    """``PATCH 1.17–1.32``, or ``PATCH none``."""
    text = Text("PATCH ", style=colors.CYAN)
    if fixture.patch is None:
        text.append("none", style=colors.DIM)
    else:
        text.append(span_text(*fixture.patch, fixture.footprint), style=colors.FG)
    return text


def limit_text(name: str, limits: Limits) -> Text:
    """``-90° to 10°``, ``at most 50%``, or ``none``."""
    limit = getattr(limits, name)
    if limit is None:
        return cell("none", colors.DIM)
    if name == "intensity":
        return cell(f"at most {commands.percent(limit)}", colors.FG)
    return cell(f"{commands.number(limit[0])}° to {commands.number(limit[1])}°", colors.FG)


def location_text(place: Location | None) -> Text:
    """``LOCATION x 1.5 y 2 z 4 rx 0 ry 0 rz 90``, or ``LOCATION no place``."""
    text = Text("LOCATION ", style=colors.CYAN)
    if place is None:
        text.append("no place", style=colors.DIM)
        return text
    pairs = zip(PLACE, place, strict=True)
    text.append(" ".join(f"{key} {commands.number(value)}" for key, value in pairs), colors.FG)
    return text


def check_span(values: tuple[str, ...]) -> str | None:
    """A pan or tilt limit's form: two numbers, the lower first."""
    low, high = (read_number(value) for value in values)
    if low is None or high is None:
        return "two numbers, in degrees"
    return f"{low:g} is above {high:g}" if low > high else None


def read_level(text: str) -> float | None:
    """A level as typed, ``50`` or ``50%``, as 0..1; ``None`` outside 0 to 100."""
    value = read_number(text.strip().removesuffix("%"))
    return None if value is None or not 0 <= value <= 100 else value / 100


def check_level(values: tuple[str, ...]) -> str | None:
    return None if read_level(values[0]) is not None else "a level from 0 to 100%"


def check_offset(text: str) -> str | None:
    return None if read_number(text) is not None else "a number, in degrees"


def check_place(values: tuple[str, ...]) -> str | None:
    if all(read_number(value) is not None for value in values):
        return None
    return "six numbers"


def put(widget: Static, text: Text) -> None:
    """``text`` in ``widget``, if it is not there already (no layout for nothing)."""
    if widget.content != text:
        widget.update(text)


class Setting(Horizontal):
    """A line of the panel: a name, what it is set to, and its buttons."""

    DEFAULT_CSS = f"""
    Setting {{ height: 1; }}
    Setting > .fp-name {{ width: 12; color: {colors.MID}; }}
    Setting > .fp-value {{ width: 19; text-wrap: nowrap; text-overflow: ellipsis; }}
    Setting > CommandButton {{ margin-right: 1; }}
    """

    def __init__(self, name: str, *buttons: ActionButton) -> None:
        self.value = Static("", classes="fp-value")
        self.buttons = buttons
        super().__init__(Static(name, classes="fp-name"), self.value, *buttons)

    def stops(self, name: str) -> list[Stop]:
        """A stop per button shown, each with a label of its own (the pane
        cursor finds its place again by the label)."""
        if not self.display:
            return []
        return [
            Stop(Item(f"{name} {button.label}", action=button.action), button)
            for button in self.buttons
            if button.display
        ]


class FixturePanel(VerticalScroll):
    """The FIXTURE panel (see the module docs). The page shows it in edit mode
    and redraws it with :meth:`show_view`; the panel calls ``changed`` when it
    changes what is chosen, and ``leave`` for ``[done]``."""

    DEFAULT_CSS = f"""
    FixturePanel {{
        width: {PANEL_WIDTH}; height: auto; margin-left: 1;
        border: solid {colors.BORDER}; padding: 0 1;
        border-title-color: {colors.CYAN}; border-title-align: left;
        scrollbar-size-vertical: 1;
        scrollbar-background: {colors.BG}; scrollbar-color: {colors.BORDER};
        scrollbar-background-hover: {colors.BG}; scrollbar-background-active: {colors.BG};
    }}
    FixturePanel .fp-section {{ height: auto; margin-bottom: 1; }}
    FixturePanel .fp-row {{ height: auto; }}
    FixturePanel .fp-row > CommandButton {{ margin-right: 1; }}
    FixturePanel .fp-text {{ height: auto; }}
    FixturePanel .fp-crop {{ text-wrap: nowrap; text-overflow: ellipsis; }}
    """

    def __init__(self, changed: Callable[[], None], leave: Callable[[], None]) -> None:
        super().__init__(id="fixture-panel")
        self.can_focus = False  # the prompt keeps the keyboard
        self.changed = changed
        self.chosen: int | None = None
        self.show: ShowModel | None = None
        self.selected: frozenset[int] = frozenset()
        self.adding = False  # the new fixture form shows
        self.hint = Static(
            Text("click a fixture, or [+ add]", style=colors.DIM), classes="fp-section"
        )
        self.rename = ActionButton("rename…", self.ask_name)
        self.renumber = ActionButton("number…", self.ask_number)
        self.delete = ActionButton("delete", self.ask_delete, "danger")
        self.what = Static("", classes="fp-text")
        self.ask_swap = ActionButton("profile…", self.ask_profile)
        self.swap: tuple[str, str | None] | None = None  # the profile to change to, and its mode
        self.swap_words = Static("", classes="fp-text fp-crop")
        self.swap_modes = ButtonStrip()
        self.swap_send = ActionButton("change", self.change_profile, "go")
        self.swap_keep = ActionButton("cancel", self.keep_profile)
        self.swapping = Vertical(
            self.swap_words,
            self.swap_modes,
            Horizontal(self.swap_send, self.swap_keep, classes="fp-row"),
            classes="fp-text",
        )
        self._swap_picks = cache(lambda mode: partial(self.pick_swap_mode, mode))
        self.modes = ButtonStrip()
        self.category = Static("", classes="fp-text")
        self.categories = ButtonStrip()
        self.patch_words = Static("", classes="fp-text fp-crop")
        self.patching = PatchChooser(self._draw_send)
        self.send_patch = ActionButton("patch", self.patch, "go", inert=True)
        self.limits_heading = Static("", classes="fp-text fp-crop")
        self.limits = {
            name: Setting(
                name,
                ActionButton("limit…", partial(self.ask_limit, name)),
                ActionButton("none", partial(self.drop_limit, name)),
            )
            for name in (*AXES, "intensity")
        }
        self.no_limits = ActionButton("no limits", self.drop_limits)
        self.orientation_heading = Static("", classes="fp-text fp-crop")
        self.toggles = {
            key: ActionButton(label, partial(self.toggle, key))
            for key, (label, _) in TOGGLES.items()
        }
        self.offsets = {
            key: Setting(
                f"{axis} offset", ActionButton("offset…", partial(self.ask_offset, key, axis))
            )
            for key, axis in OFFSETS.items()
        }
        self.orientation = Vertical(
            self.orientation_heading,
            Horizontal(*self.toggles.values(), classes="fp-row"),
            *self.offsets.values(),
            classes="fp-section",
        )
        self.place = Static("", classes="fp-text")
        self.locate = ActionButton("location…", self.ask_location)
        self.no_place = ActionButton("no place", self.drop_location)
        self.body = Vertical(
            Horizontal(self.rename, self.renumber, self.delete, classes="fp-row fp-section"),
            Vertical(
                self.what,
                Horizontal(self.ask_swap, classes="fp-row"),
                self.swapping,
                self.modes,
                classes="fp-section",
            ),
            Vertical(self.category, self.categories, classes="fp-section"),
            Vertical(
                self.patch_words,
                self.patching,
                Horizontal(self.send_patch, classes="fp-row"),
                classes="fp-section",
            ),
            Vertical(
                self.limits_heading,
                *self.limits.values(),
                Horizontal(self.no_limits, classes="fp-row"),
                classes="fp-section",
            ),
            self.orientation,
            Vertical(
                self.place,
                Horizontal(self.locate, self.no_place, classes="fp-row"),
                classes="fp-section",
            ),
            classes="fp-text",
        )
        self.form = FixtureForm(self.close_form)
        self.done = ActionButton("done", leave)

    def compose(self) -> ComposeResult:
        yield self.hint
        yield self.body
        yield self.form
        yield self.done

    # ------------------------------------------------------------ drawing

    def show_view(self, show: ShowModel | None, selected: frozenset[int]) -> None:
        """Redraw with the show and the selected fixtures as they are now."""
        self.show, self.selected = show, selected
        self.draw()

    def fixture(self) -> FixtureInfo | None:
        """The chosen fixture; ``None`` for one the show no longer has
        (deleted, or renumbered and not shown yet)."""
        if self.show is None or self.chosen is None:
            return None
        return self.show.fixture(self.chosen)

    def profile(self) -> ProfileInfo | None:
        fixture = self.fixture()
        return None if fixture is None or self.show is None else self.show.profile(fixture.profile)

    def draw(self) -> None:
        fixture = None if self.adding else self.fixture()
        self.form.display = self.adding
        self.done.display = not self.adding
        self.hint.display = fixture is None and not self.adding
        self.body.display = fixture is not None
        if self.adding:
            self.border_title = Text("FIXTURE · new")
            self.form.view(self.show)
            return
        if fixture is None:
            self.border_title = Text("FIXTURE")
            return
        self.border_title = Text(f"FIXTURE · {fixture.number} {fixture.name}".rstrip())
        self._draw_what(fixture)
        self._draw_patch(fixture)
        self._draw_limits(fixture)
        self._draw_orientation(fixture)
        put(self.place, location_text(fixture.location))
        self.no_place.display = fixture.location is not None

    def _draw_what(self, fixture: FixtureInfo) -> None:
        put(self.what, what_text(fixture))
        self._draw_swap(fixture)
        profile = self.profile()
        modes = [] if profile is None else [mode.name for mode in profile.modes]
        self.modes.display = len(modes) > 1 and self.swap is None
        if self.modes.display:
            self.modes.show(
                chips(modes, fixture.mode, partial(commands.fixture_mode, fixture.number))
            )
        self.category.display = self.categories.display = profile is not None
        if profile is not None and self.show is not None:
            count = sum(1 for other in self.show.fixtures if other.profile == profile.name)
            words = f"category of {count} fixture{'' if count == 1 else 's'}"
            put(self.category, Text(words, style=colors.DIM))
            lit = profile.category or "none"
            self.categories.show(chips(CATEGORIES, lit, partial(commands.category, profile.name)))

    def _swapped(self) -> tuple[ProfileChoice, ModeInfo] | None:
        """The profile and mode ``[change]`` would send."""
        if self.swap is None:
            return None
        choice = find_choice(self.show, self.swap[0])
        mode = find_mode(choice, self.swap[1])
        return None if choice is None or mode is None else (choice, mode)

    def _draw_swap(self, fixture: FixtureInfo) -> None:
        swapped = self._swapped()
        self.swapping.display = swapped is not None
        if swapped is None:
            self.swap = None
            return
        choice, mode = swapped
        put(self.swap_words, swap_text(choice, mode))
        self.swap_modes.show(pick_chips(mode_labels(choice.modes), mode.name, self._swap_picks))
        self.swap_send.change(inert=(choice.name, mode.name) == (fixture.profile, fixture.mode))

    def _draw_patch(self, fixture: FixtureInfo) -> None:
        put(self.patch_words, patch_heading(fixture))
        self.patching.view(self.show, fixture.footprint, fixture)
        self._draw_send()

    def _draw_send(self) -> None:
        """``[patch]`` is inert while the choice equals the patch, or does not fit."""
        fixture = self.fixture()
        same = fixture is None or self.patching.at == fixture.patch
        self.send_patch.change(inert=same or not self.patching.ready())

    def _draw_limits(self, fixture: FixtureInfo) -> None:
        put(self.limits_heading, heading("LIMITS", self.spans(), len(self.reached())))
        profile = self.profile()
        takes = frozenset() if profile is None else profile.attributes
        for name, row in self.limits.items():
            row.display = name == "intensity" or name in takes
            put(row.value, limit_text(name, fixture.limits))
            row.buttons[1].display = bool(self.spans_with(partial(_has_limit, name)))
        self.no_limits.change(inert=not self.spans_with(_has_limits))

    def _draw_orientation(self, fixture: FixtureInfo) -> None:
        profile = self.profile()
        takes = frozenset() if profile is None else profile.attributes
        self.orientation.display = bool(takes.intersection(AXES))
        put(self.orientation_heading, heading("ORIENTATION", self.spans(), len(self.reached())))
        for key, button in self.toggles.items():
            button.display = takes.issuperset(TOGGLES[key][1])
            on = getattr(fixture.orientation, key)
            button.change(intent="record" if on else "neutral", reverse=on)
        for key, row in self.offsets.items():
            row.display = OFFSETS[key] in takes
            put(
                row.value, cell(f"{commands.number(getattr(fixture.orientation, key))}°", colors.FG)
            )

    # ------------------------------------------------------------ the reach

    def reach(self) -> frozenset[int]:
        """What LIMITS and ORIENTATION act on, by number: every selected
        fixture while the chosen one is selected, else the chosen one."""
        if self.chosen is None:
            return frozenset()
        return self.selected if self.chosen in self.selected else frozenset({self.chosen})

    def reached(self) -> list[FixtureInfo]:
        """The fixtures of the reach the show has, by number."""
        reach = self.reach()
        found = () if self.show is None else self.show.fixtures
        return sorted((f for f in found if f.number in reach), key=lambda f: f.number)

    def spans(self) -> list[tuple[int, int]]:
        """The reach as ``thru`` spans, which cover every fixture between their ends."""
        return runs(
            self.reach(), [] if self.show is None else [f.number for f in self.show.fixtures]
        )

    def spans_with(self, has: Callable[[FixtureInfo], bool]) -> list[tuple[int, int]]:
        """The spans with a fixture that ``has`` it: busk refuses to remove
        what none of a span's fixtures have, and spends an undo step on a line
        that changes nothing."""
        found = [fixture.number for fixture in self.reached() if has(fixture)]
        return [(a, b) for a, b in self.spans() if any(a <= number <= b for number in found)]

    # ------------------------------------------------------------ actions

    def choose(self, chosen: int | None) -> None:
        """The fixture the panel shows, in the form's place if that shows.
        What was chosen for another fixture goes."""
        if chosen != self.chosen:
            self.patching.held = False
            self.swap = None
        self.chosen = chosen
        self.adding = False
        self.draw()
        self.changed()

    def open_form(self, at: tuple[int, int] | None = None) -> None:
        """``[+ add]``, or F8's ``[add fixture here…]``: the new fixture form."""
        self.form.open(self.show, at)
        self.adding = True
        self.draw()
        self.changed()
        self.scroll_home(animate=False)

    def close_form(self) -> None:
        """The form's ``[done]``: the panel again, on what is chosen."""
        self.adding = False
        self.draw()
        self.changed()

    def _run(self, lines: Iterable[Line]) -> None:
        for line in lines:
            self.post_message(RunLine(line))

    def ask_name(self) -> None:
        """``[rename…]``: ``rename fixture 102 "Spot left"``."""
        fixture = self.fixture()
        if fixture is None:
            return

        def given(text: str | None) -> None:
            if text is None or self.chosen != fixture.number:
                return
            name = text.strip()
            if name != fixture.name:
                self.post_message(RunLine(commands.rename_fixture(fixture.number, name)))

        title = f"RENAME · fixture {fixture.number}"
        self.app.push_screen(TextDialog(title, fixture.name, check_name(True)), given)

    def ask_number(self) -> None:
        """``[number…]``: ``fixture 102 number 150``. The choice follows it."""
        fixture = self.fixture()
        if fixture is None or self.show is None:
            return
        taken = frozenset(other.number for other in self.show.fixtures)
        others = sorted(taken - {fixture.number})

        def given(text: str | None) -> None:
            if text is None or self.chosen != fixture.number:
                return
            number = int(text.strip())
            if number == fixture.number:
                return

            def renumbered(ok: bool) -> None:
                if ok and self.chosen in (fixture.number, None):
                    self.choose(number)

            line = commands.renumber_fixture(fixture.number, number)
            self.post_message(RunLine(line, done=renumbered))

        title = f"NUMBER · fixture {fixture.number}"
        note = f"taken: {numbers_text(others)}" if others else ""
        check = check_number(taken, fixture.number)
        self.app.push_screen(TextDialog(title, str(fixture.number), check, note), given)

    def ask_delete(self) -> None:
        """``[delete]``: ``delete fixture 102 cascade``, after busk's question.
        Once it has gone nothing is chosen, so a second click reaches nothing."""
        fixture = self.fixture()
        if fixture is None:
            return

        def deleted(ok: bool) -> None:
            if ok and self.chosen == fixture.number:
                self.choose(None)

        self.post_message(RunLine(commands.delete_fixture(fixture.number), done=deleted))

    def ask_profile(self) -> None:
        """``[profile…]``: the picker, which sends nothing. The fixture's own
        profile takes back what was picked."""
        fixture = self.fixture()
        if fixture is None or self.show is None:
            return

        def given(name: str | None) -> None:
            if name is not None and self.chosen == fixture.number:
                self.swap = None if name == fixture.profile else (name, None)
                self.draw()

        start = fixture.profile if self.swap is None else self.swap[0]
        self.app.push_screen(ProfileDialog(self.show.choices, start), given)

    def pick_swap_mode(self, mode: str) -> None:
        if self.swap is not None:
            self.swap = (self.swap[0], mode)
            self.draw()

    def keep_profile(self) -> None:
        """``[cancel]``."""
        self.swap = None
        self.draw()

    def change_profile(self) -> None:
        """``[change]``: ``fixture 102 profile "RGB Par 3ch" mode "3ch"``. busk
        does not ask: ``undo`` takes it back."""
        fixture, swapped = self.fixture(), self._swapped()
        if fixture is None or swapped is None:
            return

        def changed(ok: bool) -> None:
            if ok:
                self.keep_profile()

        line = commands.fixture_profile(fixture.number, swapped[0].name, swapped[1].name)
        self.post_message(RunLine(line, done=changed))

    def patch(self) -> None:
        """``[patch]``: ``fixture 102 patch 1.85``, or ``fixture 102 patch none``."""
        fixture = self.fixture()
        if fixture is not None:
            self.post_message(RunLine(commands.patch_fixture(fixture.number, self.patching.at)))

    def ask_limit(self, name: str) -> None:
        """``[limit…]``: a line per span of the reach."""
        if name == "intensity":
            self._ask_intensity()
        else:
            self._ask_range(name)

    def _ask_intensity(self) -> None:
        """``fixture 301 limits intensity 50%``."""
        fixture = self.fixture()
        if fixture is None:
            return
        spans = self.spans()

        def given(values: tuple[str, ...] | None) -> None:
            level = None if values is None else read_level(values[0])
            if level is not None:
                self._run(commands.limit_intensity(a, b, level) for a, b in spans)

        top = 1.0 if fixture.limits.intensity is None else fixture.limits.intensity
        title = f"LIMIT · intensity · {spans_text(spans)}"
        fields = (("at most", commands.percent(top)),)
        self.app.push_screen(FormDialog(title, fields, check_level), given)

    def _ask_range(self, name: str) -> None:
        """``fixture 101 thru 102 limits tilt -90 10``. The form starts at the
        limit, else at the profile's range."""
        fixture, profile = self.fixture(), self.profile()
        if fixture is None:
            return
        spans = self.spans()

        def given(values: tuple[str, ...] | None) -> None:
            if values is not None:
                low, high = float(values[0]), float(values[1])
                self._run(commands.limit_range(a, b, name, low, high) for a, b in spans)

        travel = None if profile is None else profile.range(name)
        note = ""
        if travel is not None:
            note = f"the profile goes from {travel[0]:g}° to {travel[1]:g}°"
        low, high = getattr(fixture.limits, name) or travel or (0.0, 0.0)
        title = f"LIMIT · {name} · {spans_text(spans)}"
        fields = (("from", commands.number(low)), ("to", commands.number(high)))
        self.app.push_screen(FormDialog(title, fields, check_span, note), given)

    def drop_limit(self, name: str) -> None:
        """``[none]``: ``fixture 101 thru 102 limits tilt none``, the others stay."""
        spans = self.spans_with(partial(_has_limit, name))
        self._run(commands.no_limit(a, b, name) for a, b in spans)

    def drop_limits(self) -> None:
        """``[no limits]``: ``fixture 101 thru 102 limits none``."""
        self._run(commands.no_limits(a, b) for a, b in self.spans_with(_has_limits))

    def _orient(self, key: str, value: bool | float) -> None:
        """A ``thru`` line per span with a fixture not at ``value`` yet."""
        spans = self.spans_with(partial(_differs, key, value))
        self._run(commands.orientation(a, b, key, value) for a, b in spans)

    def toggle(self, key: str) -> None:
        """A toggle: the reach at the opposite of the chosen fixture's."""
        fixture = self.fixture()
        if fixture is not None:
            self._orient(key, not getattr(fixture.orientation, key))

    def ask_offset(self, key: str, axis: str) -> None:
        """``[offset…]``: ``fixture 101 thru 102 orientation.panOffset 30``."""
        fixture = self.fixture()
        if fixture is None:
            return

        def given(text: str | None) -> None:
            if text is not None:
                self._orient(key, float(text))

        title = f"{axis.upper()} OFFSET · {spans_text(self.spans())}"
        value = commands.number(getattr(fixture.orientation, key))
        self.app.push_screen(TextDialog(title, value, check_offset, "in degrees"), given)

    def ask_location(self) -> None:
        """``[location…]``: ``fixture 101 location {"x": 1, …}``, all six at once
        (``location.x`` fails until a location exists)."""
        fixture = self.fixture()
        if fixture is None:
            return

        def given(values: tuple[str, ...] | None) -> None:
            if values is None or self.chosen != fixture.number:
                return
            place = tuple(float(value) for value in values)
            if place != fixture.location:
                self.post_message(RunLine(commands.location(fixture.number, place)))

        starts = fixture.location or (0.0,) * len(PLACE)
        fields = tuple((key, commands.number(v)) for key, v in zip(PLACE, starts, strict=True))
        note = "x, y, z in metres · rx, ry, rz in degrees"
        title = f"LOCATION · fixture {fixture.number}"
        self.app.push_screen(FormDialog(title, fields, check_place, note), given)

    def drop_location(self) -> None:
        """``[no place]``: ``fixture 101 location none``."""
        fixture = self.fixture()
        if fixture is not None:
            self.post_message(RunLine(commands.no_location(fixture.number)))

    # -------------------------------------------------------- pane cursor

    def stops(self) -> list[Stop]:
        """The panel's controls, in reading order (an inert one is none)."""
        if self.adding:
            return self.form.stops()
        stops: list[Stop] = []
        if self.fixture() is not None:
            for button in (self.rename, self.renumber, self.delete, self.ask_swap):
                stops.append(Stop(Item(button.label, action=button.action), button))
            if self.swapping.display:
                stops += strip_stops(self.swap_modes)
                for button in (self.swap_send, self.swap_keep):
                    if not button.inert:
                        stops.append(Stop(Item(button.label, action=button.action), button))
            if self.modes.display:
                stops += strip_stops(self.modes)
            if self.categories.display:
                stops += strip_stops(self.categories)
            stops += self.patching.stops()
            if not self.send_patch.inert:
                stops.append(Stop(Item("patch", action=self.patch), self.send_patch))
            for name, row in self.limits.items():
                stops += row.stops(name)
            if not self.no_limits.inert:
                stops.append(Stop(Item("no limits", action=self.drop_limits), self.no_limits))
            for button in self.toggles.values():
                if button.display:
                    stops.append(Stop(Item(button.label, action=button.action), button))
            for key, row in self.offsets.items():
                stops += row.stops(OFFSETS[key])
            stops.append(Stop(Item("location…", action=self.ask_location), self.locate))
            if self.no_place.display:
                stops.append(Stop(Item("no place", action=self.drop_location), self.no_place))
        stops.append(Stop(Item("done", action=self.done.action), self.done))
        return stops


def _has_limit(name: str, fixture: FixtureInfo) -> bool:
    return getattr(fixture.limits, name) is not None


def _has_limits(fixture: FixtureInfo) -> bool:
    return fixture.limits != Limits()


def _differs(key: str, value: bool | float, fixture: FixtureInfo) -> bool:
    return bool(getattr(fixture.orientation, key) != value)
