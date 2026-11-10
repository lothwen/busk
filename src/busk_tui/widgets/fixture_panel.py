"""F3's FIXTURE panel (``docs/plans/tui-rig-plan.md`` §6.4, §6.5): the fixture
chosen in edit mode.

* Nothing chosen: how to choose one.
* ``[+ add]``: the new fixture form (:mod:`busk_tui.widgets.fixture_form`) in
  the panel's place, until its ``[done]``, or a click chooses a fixture.
* ``[rename…]`` and ``[number…]``, each a dialog and then one line
  (``rename fixture 102 "…"``, ``fixture 102 number 150``), and ``[delete]``:
  ``delete fixture 102 cascade``, or ``[delete 101 thru 104]`` for a run,
  after busk's question, which says what goes.
* What it is: its profile, mode and channels, and where the profile has two
  modes or more, a chip per mode (``fixture 102 mode "8ch"``). ``[profile…]``
  opens the picker, then shows that profile's modes and ``[change]``:
  ``fixture 102 profile "RGB Par 3ch" mode "3ch"``. ``[update profile]``, grey
  unless the library's revision of the profile differs from the show's: ``profile
  update "Generic Spot 16ch"``, for every fixture of the profile.
* Its profile's category, which every fixture of the profile shares: a chip
  per word (``profile "Generic Spot 16ch" category wash``).
* PATCH (:mod:`busk_tui.widgets.patch_chooser`): where it is, a choice of where
  to put it, and ``[patch]``: ``fixture 102 patch 1.85``, or ``… patch none``;
  for a run, ``fixture 101 thru 104 patch 1.85``, each after the one before.
* LIMITS: a row per limit the fixture can use (pan and tilt where the profile
  takes them, intensity always). ``[limit…]`` is a form that starts at the
  limit, else at the profile's range; ``[none]`` removes that limit, and
  ``[no limits]`` all of them.
* PARK: what park holds on the fixture, a line per attribute and value, and
  ``[park…]``, a form of an attribute and a value: ``park fixture 101 thru
  102, fixture 301.2 intensity 0``. F7's PARKED panel unparks.
* ORIENTATION, where the profile takes pan or tilt: ``[invert pan]``,
  ``[invert tilt]`` and, with both, ``[swap pan/tilt]``, toggles that send at
  once, and an ``[offset…]`` dialog for each axis.
* LOCATION: its place, ``[location…]``, a form of the six values, and
  ``[no place]``.
* ``[done]`` leaves edit mode.

Two reaches (the plan's §4 call 4). ``[rename…]``, ``[number…]``, the mode, the
profile and the location act on the chosen fixture. LIMITS and ORIENTATION act
on every selected fixture while the chosen one is selected, as their headings
say: a ``thru`` line per run of the show's numbers that are all selected.
``[delete]`` and PATCH act on the same fixtures while they are one run, in one
``thru`` line, and are grey while they are several
(``docs/plans/tui-pending-plan.md`` §5 call 7): several lines would be several
undo steps. PARK acts on the selected elements while the chosen fixture is
selected, so a pixel can be parked, else on the chosen fixture; one line, its
targets as its heading says.
"""

from __future__ import annotations

import textwrap
from collections.abc import Callable, Iterable, Sequence
from functools import cache, partial
from typing import Final

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from busk_tui import attributes, colors, commands
from busk_tui.commands import Line
from busk_tui.formats import numbers_text, runs, selection_text
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
from busk_tui.widgets.location_form import PLACE, open_location_form
from busk_tui.widgets.options import LIT, pick_chips
from busk_tui.widgets.parked import held_text, parked_rows
from busk_tui.widgets.patch_chooser import PatchChooser, channels_text, layout, span_text
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


def chips(words: Sequence[str], lit: str, line: Callable[[str], Line | None]) -> list[StripButton]:
    """A chip per word, each running ``line(word)``. The ``lit`` one is reversed
    and runs nothing: busk would spend an undo step on it, or refuse it. A word
    with no line is grey, and runs nothing either."""
    buttons = []
    for word in words:
        found = None if word == lit else line(word)
        label = Text()
        style = LIT if word == lit else colors.BORDER if found is None else colors.MID
        label.append(f"[{word}]", style=style)
        if found is None:
            buttons.append(StripButton(label, Line(""), note=True))
        else:
            buttons.append(StripButton(label, found))
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


def run_heading(run: Sequence[FixtureInfo]) -> Text:
    """Where a run is: ``PATCH · 101 thru 104 (4) · 1.1–1.64`` while it is
    one block as ``thru`` lays it out, else ``none`` or ``not in one block``."""
    text = heading("PATCH", [(run[0].number, run[-1].number)], len(run))
    text.append(" · ", style=colors.FG)
    start, now = run[0].patch, tuple(fixture.patch for fixture in run)
    if start is not None and layout(run, start) == now:
        text.append(span_text(*start, sum(f.footprint for f in run)), style=colors.FG)
    elif all(patch is None for patch in now):
        text.append("none", style=colors.DIM)
    else:
        text.append("not in one block", style=colors.DIM)
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


def check_park(takes: Sequence[str]) -> Callable[[tuple[str, ...]], str | None]:
    """A park form's check: an attribute of ``takes``, and a value. What only
    busk can tell (a value it does not read) is refused in the log."""

    def check(values: tuple[str, ...]) -> str | None:
        if values[0].strip() not in takes:
            return "an attribute these fixtures take, as the note lists them"
        return None if values[1].strip() else "a value: 0, 50%, -45, 1 0 0, or an option"

    return check


def parked_text(fixture: FixtureInfo, show: ShowModel | None) -> Text:
    """What park holds on ``fixture``, a line per attribute and value, with
    the elements when it is not all of them: ``intensity 0% · 301.2 thru
    301.5``; ``nothing parked``."""
    park = () if show is None else [p for p in show.park if p.number == fixture.number]
    rows = parked_rows(park, () if show is None else show.fixtures)
    if not rows:
        return Text("nothing parked", style=colors.DIM)
    lines = []
    for row in rows:
        line = held_text(row)
        if not row.whole():
            line.append(f" · {row.where}", style=colors.DIM)
        lines.append(line)
    return Text("\n").join(lines)


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
        """A stop per button shown and not grey, each with a label of its own
        (the pane cursor finds its place again by the label)."""
        if not self.display:
            return []
        return [
            Stop(Item(f"{name} {button.label}", action=button.action), button)
            for button in self.buttons
            if button.display and not button.inert
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
        self.selection: tuple[tuple[int, int], ...] = ()  # the selected elements, in order
        self.adding = False  # the new fixture form shows
        self.hint = Static(
            Text("click a fixture, or [+ add]", style=colors.DIM), classes="fp-section"
        )
        self.rename = ActionButton("rename…", self.ask_name)
        self.renumber = ActionButton("number…", self.ask_number)
        self.delete = ActionButton("delete", self.ask_delete, "danger")
        self.what = Static("", classes="fp-text")
        self.ask_swap = ActionButton("profile…", self.ask_profile)
        self.update_profile = ActionButton("update profile", self.send_update, inert=True)
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
        self.patch_note = Static("", classes="fp-text")
        self.patching = PatchChooser(self._draw_send)
        self._placing: tuple[int, ...] = ()  # the numbers PATCH places now
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
        self.park_heading = Static("", classes="fp-text fp-crop")
        self.parked = Static("", classes="fp-text")
        self.park = ActionButton("park…", self.ask_park)
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
                Horizontal(self.ask_swap, self.update_profile, classes="fp-row"),
                self.swapping,
                self.modes,
                classes="fp-section",
            ),
            Vertical(self.category, self.categories, classes="fp-section"),
            Vertical(
                self.patch_words,
                self.patch_note,
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
            Vertical(
                self.park_heading,
                self.parked,
                Horizontal(self.park, classes="fp-row"),
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

    def show_view(self, show: ShowModel | None, selection: tuple[tuple[int, int], ...]) -> None:
        """Redraw with the show and the selected elements as they are now."""
        self.show, self.selection = show, selection
        self.selected = frozenset(number for number, _ in selection)
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
        run = self.run()
        many = run is not None and len(run) > 1
        label = f"delete {spans_text(self.spans())}" if many else "delete"
        self.delete.change(label=label, inert=run is None)
        self._draw_what(fixture)
        self._draw_patch(fixture)
        self._draw_limits(fixture)
        self._draw_park(fixture)
        self._draw_orientation(fixture)
        put(self.place, location_text(fixture.location))
        self.no_place.display = fixture.location is not None

    def _draw_what(self, fixture: FixtureInfo) -> None:
        put(self.what, what_text(fixture))
        choice = find_choice(self.show, fixture.profile)
        self.update_profile.change(inert=choice is None or not choice.outdated())
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
        """The chosen fixture's patch, or the run's; a reach of several runs
        says what ``thru`` would take too."""
        run = self.run()
        self.patching.display = run is not None
        self.patch_note.display = run is None
        if run is None:
            put(self.patch_words, heading("PATCH", self.spans(), len(self.reached())))
            put(self.patch_note, Text(f"not one run: {self._between()}", style=colors.DIM))
            self.send_patch.change(inert=True)
            return
        placing = tuple(f.number for f in run)
        if placing != self._placing:
            self.patching.held = False  # a choice made for other fixtures
            self._placing = placing
        put(self.patch_words, patch_heading(fixture) if len(run) == 1 else run_heading(run))
        self.patching.view(self.show, sum(f.footprint for f in run), run)
        self._draw_send()

    def _between(self) -> str:
        """The fixtures a ``thru`` from the reach's first to its last would take
        that are not in it: ``thru would take 102 too``."""
        reach, found = self.reach(), () if self.show is None else self.show.fixtures
        first, last = min(reach), max(reach)
        left = [f.number for f in found if first < f.number < last and f.number not in reach]
        return f"thru would take {numbers_text(left)} too"

    def _draw_send(self) -> None:
        """``[patch]`` is inert while the choice would change nothing, or does
        not fit."""
        run = self.run()
        same = run is None or layout(run, self.patching.at) == tuple(f.patch for f in run)
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

    def _draw_park(self, fixture: FixtureInfo) -> None:
        heading = Text("PARK", style=colors.CYAN)
        heading.append(f" · {self.park_where()}", style=colors.FG)
        put(self.park_heading, heading)
        put(self.parked, parked_text(fixture, self.show))
        self.park.change(inert=not self.parkable())

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

    def run(self) -> list[FixtureInfo] | None:
        """What ``[delete]`` and PATCH act on: the reach while it is one span,
        which ``thru`` takes whole, else ``None``."""
        return self.reached() if len(self.spans()) == 1 else None

    def park_reach(self) -> tuple[tuple[int, int], ...]:
        """What ``[park…]`` acts on: the selected elements while the chosen
        fixture is selected, else every element of the chosen one."""
        fixture = self.fixture()
        if fixture is None:
            return ()
        if fixture.number in self.selected:
            return self.selection
        return tuple((fixture.number, element) for element in range(1, fixture.elements + 1))

    def park_where(self) -> str:
        """The park reach as busk's targets take it, without the word:
        ``101 thru 102, 301.2``."""
        return selection_text(self.park_reach(), () if self.show is None else self.show.fixtures)

    def parkable(self) -> tuple[str, ...]:
        """The attributes the park reach's profiles take, in busk's order (a
        colour's components go with ``color``)."""
        show = self.show
        if show is None:
            return ()
        numbers = {number for number, _ in self.park_reach()}
        takes: set[str] = set()
        for fixture in show.fixtures:
            profile = show.profile(fixture.profile) if fixture.number in numbers else None
            if profile is not None:
                takes |= profile.attributes
        return tuple(name for name in attributes.FAMILY_OF if name in takes)

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
        """``[delete]``: ``delete fixture 102 cascade``, or ``delete fixture 101
        thru 104 cascade`` for a run, after busk's question. Once it has gone
        nothing is chosen, so a second click reaches nothing."""
        run = self.run()
        if not run:
            return
        numbers = {fixture.number for fixture in run}

        def deleted(ok: bool) -> None:
            if ok and self.chosen in numbers:
                self.choose(None)

        line = commands.delete_fixture(run[0].number, run[-1].number)
        self.post_message(RunLine(line, done=deleted))

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

    def send_update(self) -> None:
        """``[update profile]``: ``profile update "Generic Spot 16ch"``. busk
        does not ask: ``undo`` takes it back."""
        fixture = self.fixture()
        if fixture is not None:
            self.post_message(RunLine(commands.profile_update(fixture.profile)))

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
        """``[patch]``: ``fixture 102 patch 1.85``, or ``fixture 102 patch none``;
        ``fixture 101 thru 104 patch 1.85`` for a run."""
        run = self.run()
        if run:
            line = commands.patch_fixture(run[0].number, self.patching.at, run[-1].number)
            self.post_message(RunLine(line))

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

    def ask_park(self) -> None:
        """``[park…]``: ``park fixture 301.2 thru 301.5 intensity 0``, an
        attribute the reach takes and a value as busk reads it."""
        takes, where = self.parkable(), self.park_where()
        if not takes:
            return

        def given(values: tuple[str, ...] | None) -> None:
            if values is not None:
                attribute, value = (text.strip() for text in values)
                self.post_message(RunLine(commands.park(where, attribute, value)))

        lines = textwrap.wrap("attributes: " + " ".join(takes), 54)
        note = "\n".join([*lines, "value: 0 to 1 or 50%, degrees, r g b, or an option"])
        fields = (("attribute", takes[0]), ("value", "0"))  # busk's order: intensity first
        self.app.push_screen(FormDialog(f"PARK · {where}", fields, check_park(takes), note), given)

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
        """``[location…]``: the form of the six values, for the chosen fixture."""
        fixture = self.fixture()
        if fixture is not None:
            open_location_form(self, fixture, lambda: self.chosen == fixture.number)

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
            buttons = (self.rename, self.renumber, self.delete, self.ask_swap, self.update_profile)
            for button in buttons:
                if not button.inert:
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
            if self.patching.display:  # not for several runs
                stops += self.patching.stops()
            if not self.send_patch.inert:
                stops.append(Stop(Item("patch", action=self.patch), self.send_patch))
            for name, row in self.limits.items():
                stops += row.stops(name)
            if not self.no_limits.inert:
                stops.append(Stop(Item("no limits", action=self.drop_limits), self.no_limits))
            if not self.park.inert:
                stops.append(Stop(Item("park…", action=self.ask_park), self.park))
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
