"""F3's PATCH, its new fixture form and the profile picker
(``docs/plans/tui-rig-plan.md`` §6.5, §6.6): what an address means, a choice that
sends nothing until ``[patch]`` or ``[add]``, numbers free for a whole block, the
next ones after an add, and a fixture's profile changed through the picker.
From ``docs/plans/tui-pending-plan.md`` Phase 13: a run patched in one line, a
selection with a hole, a profile imported through the picker, and ``[update
profile]``. Headless, with a fake bridge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from textual.pilot import Pilot
from textual.widget import Widget
from textual.widgets import Input
from tui_fakes import FakeBridge, Reply, click_cell, column, drive, make_app, programmer, settle
from tui_fakes import show_model as make_show

from busk_tui import colors
from busk_tui.model import (
    CommandDone,
    FixtureInfo,
    ModeInfo,
    ProfileChoice,
    ProfileInfo,
    ProgrammerChanged,
    ShowChanged,
    ShowModel,
    UniverseView,
)
from busk_tui.pages.fixtures import FixturesPage
from busk_tui.shell import BuskApp
from busk_tui.widgets.controls import ButtonStrip
from busk_tui.widgets.dialogs import TextDialog
from busk_tui.widgets.dmxmap import Footprint
from busk_tui.widgets.fixture_form import mode_labels, range_text, taken_text
from busk_tui.widgets.fixture_panel import patch_heading, run_heading, swap_text
from busk_tui.widgets.log import LogView
from busk_tui.widgets.options import LIT
from busk_tui.widgets.patch_chooser import (
    channels_text,
    check_address,
    layout,
    span_text,
    takes_text,
)
from busk_tui.widgets.profile_picker import (
    FILES,
    ProfileDialog,
    check_path,
    choice_text,
    matches,
    modes_text,
    profile_path,
)

STAGE, BALCONY = UniverseView(1, "Stage"), UniverseView(2, "Balcony")
ONE = (ModeInfo("16ch", 16, 1),)
FOUR = (ModeInfo("4ch", 4, 1),)
TWO = (ModeInfo("3ch", 3, 1), ModeInfo("6ch", 6, 1))
PROFILES = (
    ProfileInfo("Head", frozenset({"intensity", "pan", "tilt"}), (), "spot", ONE),
    ProfileInfo("Par", frozenset({"intensity"}), (), "par", FOUR),
)
CHOICES = (
    ProfileChoice("Head", "show", "Generic", ONE),
    ProfileChoice("Par", "show", "Generic", FOUR),
    ProfileChoice("RGB Bar", "library", "Acme", TWO),
    ProfileChoice("Blinder", "library", "Acme", (ModeInfo("2ch", 2, 1),)),
)
FIXTURES = (
    FixtureInfo(101, 1, "Head 1", "Head", "16ch", 16, (1, 1)),
    FixtureInfo(102, 1, "Head 2", "Head", "16ch", 16, (1, 17)),
    FixtureInfo(201, 1, "Par 1", "Par", "4ch", 4, (1, 33)),
    FixtureInfo(203, 1, "Par 3", "Par", "4ch", 4, (1, 40)),  # 37–39 free
    FixtureInfo(301, 1, "Spare", "Par", "4ch", 4, None),
)


def rig(**changes: Any) -> ShowModel:
    parts: dict[str, Any] = {
        "universes": (STAGE, BALCONY),
        "fixtures": FIXTURES,
        "profiles": PROFILES,
        "choices": CHOICES,
    }
    parts.update(changes)
    return make_show(**parts)


def on_f3(bridge: FakeBridge, show: ShowModel | None = None) -> BuskApp:
    bridge.events += [ShowChanged(show or rig()), ProgrammerChanged(programmer())]
    return make_app(bridge, page=3)


async def enter(pilot: Pilot[int], app: BuskApp, chosen: int = 102) -> FixturesPage:
    """Edit mode, with ``chosen`` chosen."""
    await settle(pilot, app)
    page = app.query_one(FixturesPage)
    page.set_editing(True)
    page.panel.choose(chosen)
    await pilot.pause()
    return page


async def open_form(pilot: Pilot[int], app: BuskApp) -> FixturesPage:
    await settle(pilot, app)
    page = app.query_one(FixturesPage)
    await tap(pilot, page.add_button, app)
    return page


async def tap(pilot: Pilot[int], widget: Widget, app: BuskApp) -> None:
    widget.scroll_visible(animate=False)
    await pilot.pause()
    await pilot.click(widget)
    await settle(pilot, app)


async def tap_chip(pilot: Pilot[int], strip: ButtonStrip, label: str, app: BuskApp) -> None:
    strip.scroll_visible(animate=False)
    await pilot.pause()
    for y, line in enumerate(strip.lines(strip.size.width)):
        x = line.plain.find(f"[{label}")
        if x >= 0:
            await pilot.click(strip, offset=(x + 1, y))
            await settle(pilot, app)
            return
    raise AssertionError(f"no chip [{label}")


async def answer(pilot: Pilot[int], app: BuskApp, text: str) -> None:
    """Type ``text`` over what the open dialog's input holds, then Enter."""
    app.screen.query_one(Input).value = text
    await pilot.press("enter")
    await settle(pilot, app)


async def pick(pilot: Pilot[int], app: BuskApp, opener: Widget, name: str) -> None:
    """Open the picker with ``opener`` and choose ``name`` by filtering for it."""
    await tap(pilot, opener, app)
    assert isinstance(app.screen, ProfileDialog)
    await pilot.press(*name, "enter")
    await settle(pilot, app)


def lit(strip: ButtonStrip) -> list[str]:
    return [
        b.label.plain for b in strip.buttons if LIT in map(str, (s.style for s in b.label.spans))
    ]


def words(widget: Any) -> str:
    return str(widget.content)


# ---------------------------------------------------------------- the words


def test_a_span_of_channels() -> None:
    assert span_text(1, 85, 16) == "1.85–1.100"
    assert span_text(2, 7, 1) == "2.7"
    assert channels_text(16) == "16 channels"
    assert channels_text(1) == "1 channel"


def footprint(fixture: int, start: int, size: int) -> Footprint:
    return Footprint(fixture, start, size, colors.MID)


@pytest.mark.parametrize(
    ("address", "size", "own", "text", "color"),
    [
        (85, 16, (), "takes 1.85–1.100 · free", colors.GREEN),
        (8, 4, (), "takes 1.8–1.11 · overlaps fixture 7", colors.AMBER),
        (1, 40, (), "takes 1.1–1.40 · overlaps fixtures 7, 8", colors.AMBER),
        (8, 4, (7,), "takes 1.8–1.11 · free", colors.GREEN),  # it does not overlap itself
        (1, 40, (7,), "takes 1.1–1.40 · overlaps fixture 8", colors.AMBER),
        (1, 40, (7, 8), "takes 1.1–1.40 · free", colors.GREEN),  # a run moved over itself
        (505, 16, (), "takes 1.505–1.520 · past channel 512", colors.RED),
        (512, 1, (), "takes 1.512 · free", colors.GREEN),
        (None, 64, (), "no room for 64 channels", colors.RED),
        (None, 1, (), "no room for 1 channel", colors.RED),
    ],
)
def test_what_an_address_means(
    address: int | None, size: int, own: tuple[int, ...], text: str, color: str
) -> None:
    takes = takes_text(1, address, size, (footprint(7, 1, 16), footprint(8, 30, 4)), own)
    assert takes.plain == text
    assert str(takes.spans[-1].style) == color


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("1", None),
        (" 512 ", None),
        ("0", "a whole number from 1 to 512"),
        ("513", "a whole number from 1 to 512"),
        ("x", "a whole number from 1 to 512"),
        ("²", "a whole number from 1 to 512"),
        pytest.param("7" * 5000, "a whole number from 1 to 512", id="past-int"),
    ],
)
def test_an_address_goes_from_1_to_512(text: str, problem: str | None) -> None:
    assert check_address(text) == problem


def test_the_heading_says_where_it_is() -> None:
    assert patch_heading(FIXTURES[1]).plain == "PATCH 1.17–1.32"
    assert patch_heading(FIXTURES[4]).plain == "PATCH none"


def test_a_range_and_what_is_taken_in_it() -> None:
    assert range_text(302, 305) == "302 thru 305"
    assert range_text(302, 302) == ""
    assert taken_text([]) == ""
    assert taken_text([303]) == "303 is taken"
    assert taken_text([303, 304]) == "303–304 are taken"


def test_the_mode_chips_tell_several_modes_apart_by_what_they_take() -> None:
    assert mode_labels(FOUR) == {"4ch": "4ch"}
    assert mode_labels(TWO) == {"3ch": "3ch · 3", "6ch": "6ch · 6"}


def test_what_a_swap_would_make_of_the_fixture() -> None:
    assert swap_text(CHOICES[2], TWO[1]).plain == "to RGB Bar · 6 channels"
    assert swap_text(CHOICES[3], ModeInfo("1ch", 1, 1)).plain == "to Blinder · 1 channel"


# ------------------------------------------------------------------- PATCH


def test_patch_starts_at_the_fixtures_patch_and_sends_nothing() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel = page.panel
        chooser = panel.patching
        assert words(panel.patch_words) == "PATCH 1.17–1.32"
        assert lit(chooser.chips) == ["[1 Stage]"]
        assert words(chooser.value) == "17"
        assert words(chooser.takes) == "takes 1.17–1.32 · free"
        assert panel.send_patch.inert  # the choice equals the patch
        await tap(pilot, panel.send_patch, app)
        assert bridge.lines() == []

    drive(app, body)


def test_an_unpatched_fixture_starts_at_none() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 301)
        chooser = page.panel.patching
        assert words(page.panel.patch_words) == "PATCH none"
        assert lit(chooser.chips) == ["[none]"]
        assert words(chooser.value) == "none"
        assert words(chooser.takes) == "no patch"
        assert chooser.ask.inert
        assert chooser.next_free.inert
        assert page.panel.send_patch.inert

    drive(app, body)


def test_a_universe_chip_proposes_its_first_free_run_that_fits() -> None:
    small = FixtureInfo(401, 1, "Small", "Par", "2ch", 2, None)
    bridge = FakeBridge()
    app = on_f3(bridge, rig(fixtures=(*FIXTURES, small)))

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 401)
        chooser = page.panel.patching
        await tap_chip(pilot, chooser.chips, "1 Stage", app)
        assert chooser.at == (1, 37)  # two channels fit the gap
        page.panel.choose(301)
        await pilot.pause()
        await tap_chip(pilot, chooser.chips, "1 Stage", app)
        assert chooser.at == (1, 44)  # four do not
        assert bridge.lines() == []

    drive(app, body)


def test_next_free_and_another_universe_send_nothing() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        chooser = page.panel.patching
        await tap(pilot, chooser.next_free, app)
        assert chooser.at == (1, 44)
        assert words(chooser.takes) == "takes 1.44–1.59 · free"
        await tap_chip(pilot, chooser.chips, "2 Balcony", app)
        assert chooser.at == (2, 1)
        assert lit(chooser.chips) == ["[2 Balcony]"]
        assert words(chooser.takes) == "takes 2.1–2.16 · free"
        assert bridge.lines() == []

    drive(app, body)


def test_next_free_does_not_count_the_fixtures_own_channels() -> None:
    """Its own channels would give back where it is: the button is for moving it."""
    show = rig(fixtures=(FixtureInfo(1, 1, "Par", "Par", "4ch", 4, (1, 1)),))
    bridge = FakeBridge()
    app = on_f3(bridge, show)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 1)
        chooser = page.panel.patching
        await tap(pilot, chooser.next_free, app)
        assert chooser.at == (1, 5)

    drive(app, body)


def test_the_fixtures_own_universe_gives_back_its_patch() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        chooser = page.panel.patching
        await tap_chip(pilot, chooser.chips, "2 Balcony", app)
        assert not page.panel.send_patch.inert
        await tap_chip(pilot, chooser.chips, "1 Stage", app)
        assert chooser.at == (1, 17)
        assert page.panel.send_patch.inert

    drive(app, body)


def test_address_is_a_dialog_and_refuses_what_is_not_one() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        chooser = page.panel.patching
        await tap(pilot, chooser.ask, app)
        assert isinstance(app.screen, TextDialog)
        assert app.screen.initial == "17"
        assert app.screen.note == "takes 16 channels"
        await answer(pilot, app, "513")
        assert isinstance(app.screen, TextDialog)  # it stays, saying why
        await answer(pilot, app, "100")
        assert chooser.at == (1, 100)
        assert bridge.lines() == []

        await tap(pilot, chooser.ask, app)
        await pilot.press("escape")
        await settle(pilot, app)
        assert chooser.at == (1, 100)

    drive(app, body)


def test_the_takes_line_and_what_it_leaves_live() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel, chooser = page.panel, page.panel.patching
        await tap(pilot, chooser.ask, app)
        await answer(pilot, app, "100")
        assert words(chooser.takes) == "takes 1.100–1.115 · free"
        assert not panel.send_patch.inert

        await tap(pilot, chooser.ask, app)
        await answer(pilot, app, "30")
        assert words(chooser.takes) == "takes 1.30–1.45 · overlaps fixtures 201, 203"
        assert not panel.send_patch.inert  # allowed, as busk allows it

        await tap(pilot, chooser.ask, app)
        await answer(pilot, app, "500")
        assert words(chooser.takes) == "takes 1.500–1.515 · past channel 512"
        assert panel.send_patch.inert
        await tap(pilot, panel.send_patch, app)
        assert bridge.lines() == []

    drive(app, body)


def test_a_fixture_overlapping_only_itself_is_free() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 201)  # at 33–36
        chooser = page.panel.patching
        await tap(pilot, chooser.ask, app)
        await answer(pilot, app, "35")
        assert words(chooser.takes) == "takes 1.35–1.38 · free"

    drive(app, body)


def test_patch_sends_one_line_and_the_choice_then_follows_the_fixture() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel, chooser = page.panel, page.panel.patching
        await tap(pilot, chooser.next_free, app)
        await tap(pilot, panel.send_patch, app)
        assert bridge.lines() == ["fixture 102 patch 1.44"]

        moved = FixtureInfo(102, 1, "Head 2", "Head", "16ch", 16, (1, 44))
        fixtures = (FIXTURES[0], moved, *FIXTURES[2:])
        bridge.events.append(ShowChanged(rig(fixtures=fixtures)))
        await settle(pilot, app)
        assert words(panel.patch_words) == "PATCH 1.44–1.59"
        assert chooser.at == (1, 44)
        assert not chooser.held
        assert panel.send_patch.inert

        again = FixtureInfo(102, 1, "Head 2", "Head", "16ch", 16, (2, 1))
        bridge.events.append(ShowChanged(rig(fixtures=(FIXTURES[0], again, *FIXTURES[2:]))))
        await settle(pilot, app)
        assert chooser.at == (2, 1)  # moved at the prompt: it follows

    drive(app, body)


def test_none_then_patch_unpatches_it() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel, chooser = page.panel, page.panel.patching
        await tap_chip(pilot, chooser.chips, "none", app)
        assert chooser.at is None
        assert words(chooser.value) == "none"
        assert words(chooser.takes) == "no patch"
        assert chooser.ask.inert
        assert chooser.next_free.inert
        labels = [item.label for item in page.items()]
        assert "address…" not in labels
        assert "next free" not in labels
        await tap(pilot, panel.send_patch, app)
        assert bridge.lines() == ["fixture 102 patch none"]

    drive(app, body)


def test_a_refused_patch_keeps_the_choice() -> None:
    bridge = FakeBridge(replies={"fixture 102 patch 1.44": Reply(False, "error: no")})
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        chooser = page.panel.patching
        await tap(pilot, chooser.next_free, app)
        await tap(pilot, page.panel.send_patch, app)
        assert chooser.at == (1, 44)
        assert ("error", "no") in app.query_one(LogView).entries

    drive(app, body)


def test_a_universe_with_no_room_says_so_and_takes_no_line() -> None:
    full = FixtureInfo(1, 1, "Wall", "Wall", "512", 512, (2, 1))
    show = rig(fixtures=(*FIXTURES, full))
    bridge = FakeBridge()
    app = on_f3(bridge, show)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel, chooser = page.panel, page.panel.patching
        await tap_chip(pilot, chooser.chips, "2 Balcony", app)
        assert chooser.address is None
        assert words(chooser.value) == "none"
        assert words(chooser.takes) == "no room for 16 channels"
        assert panel.send_patch.inert
        await tap(pilot, chooser.ask, app)  # an overlap is still the operator's to make
        assert isinstance(app.screen, TextDialog)
        assert app.screen.initial == "1"
        await answer(pilot, app, "1")
        assert words(chooser.takes) == "takes 2.1–2.16 · overlaps fixture 1"
        assert not panel.send_patch.inert

    drive(app, body)


def test_no_universe_says_where_to_add_one() -> None:
    show = rig(universes=(), fixtures=(FIXTURES[4],))
    bridge = FakeBridge()
    app = on_f3(bridge, show)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 301)
        chooser = page.panel.patching
        assert [b.label.plain for b in chooser.chips.buttons] == [
            "[none]",
            "no universe: F8 adds one",
        ]
        assert lit(chooser.chips) == ["[none]"]

    drive(app, body)


def test_the_choice_stays_through_the_show_changing_and_goes_with_the_fixture() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel, chooser = page.panel, page.panel.patching
        await tap_chip(pilot, chooser.chips, "2 Balcony", app)
        bridge.events.append(ProgrammerChanged(programmer(selection=((101, 1),))))
        bridge.events.append(ShowChanged(rig(fixtures=FIXTURES[:4])))
        await settle(pilot, app)
        assert chooser.at == (2, 1)

        panel.choose(102)  # the same one again keeps it
        await pilot.pause()
        assert chooser.at == (2, 1)
        panel.choose(101)
        await pilot.pause()
        assert chooser.at == (1, 1)
        panel.choose(102)
        await pilot.pause()
        assert chooser.at == (1, 17)

    drive(app, body)


def test_a_universe_that_leaves_the_show_takes_the_choice_back_to_the_patch() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        chooser = page.panel.patching
        await tap_chip(pilot, chooser.chips, "2 Balcony", app)
        bridge.events.append(ShowChanged(rig(universes=(STAGE,))))
        await settle(pilot, app)
        assert chooser.at == (1, 17)
        assert not chooser.held

    drive(app, body)


def test_the_universes_chips_go_by_number_and_a_long_name_is_cut() -> None:
    long = UniverseView(1, "A very long name for a universe indeed")
    show = rig(universes=(UniverseView(7, "Roof"), long))
    bridge = FakeBridge()
    app = on_f3(bridge, show)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        labels = [b.label.plain for b in page.panel.patching.chips.buttons]
        assert labels == ["[none]", "[1 A very long name for a]", "[7 Roof]"]

    drive(app, body)


def test_the_pane_cursor_stops_on_patch_controls_and_takes_them() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        labels = [item.label for item in page.items()]
        start = labels.index("[none]")
        assert labels[start : start + 4] == ["[none]", "[2 Balcony]", "address…", "next free"]
        assert "patch" not in labels  # inert
        await pilot.press("tab", *["down"] * labels.index("next free"), "enter")
        await settle(pilot, app)
        assert page.panel.patching.at == (1, 44)
        labels = [item.label for item in page.items()]
        await pilot.press(*["down"] * (labels.index("patch") - labels.index("next free")), "enter")
        await settle(pilot, app)
        assert bridge.lines() == ["fixture 102 patch 1.44"]

    drive(app, body)


# ------------------------------------------------------------- a run of fixtures

SPARE = FixtureInfo(302, 1, "Spare 2", "Par", "4ch", 4, None)


def selecting(bridge: FakeBridge, *numbers: int) -> None:
    bridge.events.append(ProgrammerChanged(programmer(selection=tuple((n, 1) for n in numbers))))


def test_where_thru_puts_each_fixture_of_a_run() -> None:
    run = (FIXTURES[2], FIXTURES[3])  # 4 channels each
    assert layout(run, (1, 33)) == ((1, 33), (1, 37))
    assert layout(run, None) == (None, None)
    assert layout(FIXTURES[:2], (2, 100)) == ((2, 100), (2, 116))
    assert run_heading(FIXTURES[:2]).plain == "PATCH · 101 thru 102 (2) · 1.1–1.32"
    assert run_heading(run).plain == "PATCH · 201 thru 203 (2) · not in one block"
    assert run_heading((FIXTURES[4], SPARE)).plain == "PATCH · 301 thru 302 (2) · none"
    assert (
        run_heading((FIXTURES[3], FIXTURES[4])).plain
        == "PATCH · 203 thru 301 (2) · not in one block"
    )


def test_a_run_selected_is_placed_from_its_first_fixture_and_patched_in_one_line() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)
    selecting(bridge, 101, 102)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 102)
        panel, chooser = page.panel, page.panel.patching
        assert words(panel.patch_words) == "PATCH · 101 thru 102 (2) · 1.1–1.32"
        assert chooser.at == (1, 1)
        assert words(chooser.takes) == "takes 1.1–1.32 · free"  # its own channels
        assert panel.send_patch.inert  # laid out so already
        await tap(pilot, chooser.next_free, app)
        assert chooser.at == (1, 44)  # 32 channels, past its own
        assert words(chooser.takes) == "takes 1.44–1.75 · free"
        await tap(pilot, panel.send_patch, app)
        assert bridge.lines() == ["fixture 101 thru 102 patch 1.44"]

    drive(app, body)


def test_a_run_holds_the_numbers_between_and_a_gap_does_not_part_it() -> None:
    """201 and 203: no 202 in the show, so one run, not in one block."""
    bridge = FakeBridge()
    app = on_f3(bridge)
    selecting(bridge, 201, 203)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 203)
        panel, chooser = page.panel, page.panel.patching
        assert words(panel.patch_words) == "PATCH · 201 thru 203 (2) · not in one block"
        assert chooser.at == (1, 33)
        assert words(chooser.takes) == "takes 1.33–1.40 · free"
        assert not panel.send_patch.inert  # 203 would move to 37
        await tap(pilot, panel.send_patch, app)
        assert bridge.lines() == ["fixture 201 thru 203 patch 1.33"]

    drive(app, body)


def test_an_unpatched_run_starts_at_none_and_a_universe_proposes_room_for_it_all() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge, rig(fixtures=(*FIXTURES, SPARE)))
    selecting(bridge, 301, 302)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 301)
        panel, chooser = page.panel, page.panel.patching
        assert words(panel.patch_words) == "PATCH · 301 thru 302 (2) · none"
        assert chooser.at is None
        assert panel.send_patch.inert
        await tap_chip(pilot, chooser.chips, "1 Stage", app)
        assert chooser.at == (1, 44)  # 8 channels: not the 3 free at 37
        await tap(pilot, panel.send_patch, app)
        assert bridge.lines() == ["fixture 301 thru 302 patch 1.44"]

    drive(app, body)


def test_none_unpatches_a_run_and_the_first_fixtures_universe_gives_its_place_back() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)
    selecting(bridge, 101, 102)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 101)
        panel, chooser = page.panel, page.panel.patching
        await tap_chip(pilot, chooser.chips, "2 Balcony", app)
        assert chooser.at == (2, 1)
        await tap_chip(pilot, chooser.chips, "1 Stage", app)
        assert chooser.at == (1, 1)
        assert panel.send_patch.inert
        await tap_chip(pilot, chooser.chips, "none", app)
        await tap(pilot, panel.send_patch, app)
        assert bridge.lines() == ["fixture 101 thru 102 patch none"]

    drive(app, body)


def test_a_run_past_channel_512_is_not_sent() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)
    selecting(bridge, 101, 102)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 101)
        panel, chooser = page.panel, page.panel.patching
        await tap(pilot, chooser.ask, app)
        assert isinstance(app.screen, TextDialog)
        assert app.screen.note == "takes 32 channels"
        await answer(pilot, app, "490")
        assert words(chooser.takes) == "takes 1.490–1.521 · past channel 512"
        assert panel.send_patch.inert
        await tap(pilot, chooser.ask, app)
        await answer(pilot, app, "481")
        assert words(chooser.takes) == "takes 1.481–1.512 · free"
        await tap(pilot, panel.send_patch, app)
        assert bridge.lines() == ["fixture 101 thru 102 patch 1.481"]

    drive(app, body)


def test_a_choice_made_for_other_fixtures_goes_when_the_run_changes() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)
    selecting(bridge, 101)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 101)
        chooser = page.panel.patching
        await tap(pilot, chooser.next_free, app)
        assert (chooser.at, chooser.held) == ((1, 44), True)
        selecting(bridge, 101, 102)  # from the prompt: 101 stays chosen
        await settle(pilot, app)
        assert (chooser.at, chooser.held) == ((1, 1), False)
        assert words(page.panel.patch_words) == "PATCH · 101 thru 102 (2) · 1.1–1.32"

    drive(app, body)


def test_the_chosen_fixture_out_of_the_selection_is_patched_alone() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)
    selecting(bridge, 201, 203)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 101)
        panel = page.panel
        assert words(panel.patch_words) == "PATCH 1.1–1.16"
        assert str(panel.delete.label) == "delete"
        await tap(pilot, panel.patching.next_free, app)
        await tap(pilot, panel.send_patch, app)
        assert bridge.lines() == ["fixture 101 patch 1.44"]

    drive(app, body)


def test_a_selection_with_a_hole_greys_delete_and_patch_and_says_why() -> None:
    """101 and 201, with 102 between them: ``thru`` would take 102. From a
    run whose ``[patch]`` was live."""
    bridge = FakeBridge()
    app = on_f3(bridge)
    selecting(bridge, 201, 203)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 201)
        panel = page.panel
        assert not panel.send_patch.inert  # 201 thru 203, not in one block
        selecting(bridge, 101, 201)
        await settle(pilot, app)
        panel.choose(101)
        await pilot.pause()
        assert words(panel.patch_words) == "PATCH · 101, 201 (2)"
        assert panel.patch_note.display
        assert words(panel.patch_note) == "not one run: thru would take 102 too"
        assert not panel.patching.display
        assert panel.send_patch.inert
        assert (str(panel.delete.label), panel.delete.inert) == ("delete", True)
        labels = [item.label for item in page.items()]
        for label in ("delete", "patch", "[none]", "address…", "next free"):
            assert label not in labels
        await tap(pilot, panel.delete, app)
        await tap(pilot, panel.send_patch, app)
        assert bridge.lines() == []

        selecting(bridge, 101, 102, 203)  # 201 left out, 102 in
        await settle(pilot, app)
        assert words(panel.patch_note) == "not one run: thru would take 201 too"

        selecting(bridge, 101, 102, 103, 201)  # 103 is not in this show: one run
        await settle(pilot, app)
        assert words(panel.patch_words) == "PATCH · 101 thru 201 (3) · 1.1–1.36"
        assert not panel.patch_note.display
        assert panel.patching.display
        assert str(panel.delete.label) == "delete 101 thru 201"

    drive(app, body)


def test_the_pane_cursor_takes_a_runs_delete_and_patch() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)
    selecting(bridge, 101, 102)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 101)
        labels = [item.label for item in page.items()]
        assert "delete 101 thru 102" in labels
        await pilot.press("tab", *["down"] * labels.index("next free"), "enter")
        await settle(pilot, app)
        labels = [item.label for item in page.items()]
        await pilot.press(*["down"] * (labels.index("patch") - labels.index("next free")), "enter")
        await settle(pilot, app)
        assert bridge.lines() == ["fixture 101 thru 102 patch 1.44"]

    drive(app, body)


# ---------------------------------------------------------- the profile picker


def test_a_rows_words() -> None:
    assert modes_text(CHOICES[2]) == "3ch (3), 6ch (6)"
    row = choice_text(CHOICES[0]).plain
    assert row.startswith("● Generic")
    assert "Head" in row
    assert "16ch (16)" in row
    assert choice_text(CHOICES[2]).plain.startswith("  Acme")


def test_a_filter_takes_words_of_the_maker_and_the_name_in_any_case() -> None:
    assert matches(CHOICES[2], ["acme", "bar"])
    assert matches(CHOICES[2], ["BAR".casefold()])
    assert matches(CHOICES[2], [])
    assert not matches(CHOICES[2], ["acme", "head"])


async def picker(
    pilot: Pilot[int], app: BuskApp, choices: tuple[ProfileChoice, ...], chosen: str | None = None
) -> tuple[ProfileDialog, list[str | None]]:
    got: list[str | None] = []
    dialog = ProfileDialog(choices, chosen)
    app.push_screen(dialog, got.append)
    await pilot.pause()
    return dialog, got


def test_the_picker_lists_in_the_order_given_and_starts_on_the_first() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        dialog, got = await picker(pilot, app, CHOICES)
        assert [c.name for c in dialog.shown] == ["Head", "Par", "RGB Bar", "Blinder"]
        assert dialog.list.highlighted == 0
        await pilot.press("enter")
        await pilot.pause()
        assert got == ["Head"]

    drive(app, body)


def test_the_picker_starts_on_the_profile_last_chosen() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        dialog, _ = await picker(pilot, app, CHOICES, "RGB Bar")
        assert dialog.list.highlighted == 2

    drive(app, body)


def test_the_arrows_move_and_stop_at_the_ends() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        dialog, got = await picker(pilot, app, CHOICES)
        await pilot.press("up")
        assert dialog.list.highlighted == 0
        await pilot.press("down", "down")
        assert dialog.list.highlighted == 2
        await pilot.press("down", "down", "down")
        assert dialog.list.highlighted == 3
        assert dialog.field.has_focus  # the filter keeps the keyboard
        await pilot.press("enter")
        await pilot.pause()
        assert got == ["Blinder"]

    drive(app, body)


def test_esc_cancels() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        _, got = await picker(pilot, app, CHOICES)
        await pilot.press("escape")
        await pilot.pause()
        assert got == [None]

    drive(app, body)


def test_a_click_chooses() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        dialog, got = await picker(pilot, app, CHOICES)
        await pilot.click(dialog.list, offset=(4, 2))
        await pilot.pause()
        assert got == ["RGB Bar"]

    drive(app, body)


def test_the_filter_narrows_the_list_and_keeps_the_row_it_was_on() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        dialog, got = await picker(pilot, app, CHOICES, "Blinder")
        await pilot.press(*"acme")
        await pilot.pause()
        assert [c.name for c in dialog.shown] == ["RGB Bar", "Blinder"]
        assert dialog.list.highlighted == 1
        await pilot.press("space", *"rgb")
        await pilot.pause()
        assert [c.name for c in dialog.shown] == ["RGB Bar"]
        assert dialog.list.highlighted == 0
        await pilot.press("enter")
        await pilot.pause()
        assert got == ["RGB Bar"]

    drive(app, body)


def test_a_filter_in_capitals_finds_the_same() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        dialog, _ = await picker(pilot, app, CHOICES)
        await pilot.press(*"ACME")
        await pilot.pause()
        assert [c.name for c in dialog.shown] == ["RGB Bar", "Blinder"]

    drive(app, body)


def test_an_empty_result_says_so_and_enter_stays() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        dialog, got = await picker(pilot, app, CHOICES)
        await pilot.press(*"zzz")
        await pilot.pause()
        assert dialog.shown == ()
        assert not dialog.list.display
        assert dialog.none.display
        assert words(dialog.none) == "no profile has 'zzz'"
        await pilot.press("enter", "up", "down")
        await pilot.pause()
        assert got == []
        assert app.screen is dialog
        await pilot.press("backspace", "backspace", "backspace")
        await pilot.pause()
        assert len(dialog.shown) == 4
        assert dialog.list.display
        assert dialog.list.highlighted == 0

    drive(app, body)


def test_a_long_list_scrolls_to_the_row_and_pages() -> None:
    choices = tuple(ProfileChoice(f"Profile {n:03}", "library", "Maker", FOUR) for n in range(100))
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        dialog, _ = await picker(pilot, app, choices, "Profile 060")
        await pilot.pause()
        assert dialog.list.highlighted == 60
        top = dialog.list.scroll_offset.y
        assert top <= 60 < top + dialog.list.size.height  # in sight
        await pilot.press("pagedown")
        assert dialog.list.highlighted == 71
        await pilot.press("pageup", "pageup")
        assert dialog.list.highlighted == 49
        for _ in range(10):
            await pilot.press("pagedown")
        assert dialog.list.highlighted == 99

    drive(app, body)


# ------------------------------------------------------ importing a profile

DIMMER = {
    "name": "Test",
    "meta": {"lastModifyDate": "2026-01-02"},
    "availableChannels": {"Dimmer": {"capability": {"type": "Intensity"}}},
    "modes": [{"name": "All", "channels": ["Dimmer"]}],
}
"""An Open Fixture Library fixture: busk names it after its folder, ``acme Test``."""

IMPORTED = ProfileChoice("acme Test", "show", "acme", (ModeInfo("All", 1, 1),), "x", None)


def ofl_file(folder: Path) -> Path:
    (folder / "acme").mkdir(parents=True, exist_ok=True)
    file = folder / "acme" / "dim.json"
    file.write_text(json.dumps(DIMMER))
    return file


def test_a_path_is_taken_as_typed_from_home_or_from_here(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert profile_path(" acme/dim.json ") == tmp_path / "acme" / "dim.json"
    assert profile_path("~/spot.gdtf") == tmp_path / "home" / "spot.gdtf"
    assert profile_path("/srv/spot.gdtf") == Path("/srv/spot.gdtf")
    ofl_file(tmp_path)
    assert check_path("acme/dim.json") is None
    assert check_path("  ") == f"a path to {FILES}"
    assert check_path("acme/none.json") == f"no file at {tmp_path / 'acme' / 'none.json'}"
    assert check_path("acme") == f"no file at {tmp_path / 'acme'}"  # a folder


@pytest.mark.parametrize("how", ["click", "ctrl+o"])
def test_import_is_a_path_dialog_that_sends_one_line_and_the_picker_stays(
    tmp_path: Path, how: str
) -> None:
    file = ofl_file(tmp_path / 'a "rig"')
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        await tap(pilot, page.panel.form.choose, app)
        dialog = app.screen
        assert isinstance(dialog, ProfileDialog)
        if how == "click":
            await pilot.click(dialog.importer)
        else:
            await pilot.press("ctrl+o")
        await pilot.pause()
        assert isinstance(app.screen, TextDialog)
        assert app.screen.title_text == "IMPORT PROFILE"
        assert app.screen.note.startswith(FILES)
        await answer(pilot, app, str(tmp_path / "none.json"))
        assert isinstance(app.screen, TextDialog)  # it stays, saying why
        assert str(app.screen.error.content) == f"no file at {tmp_path / 'none.json'}"
        await answer(pilot, app, f" {file} ")
        assert app.screen is dialog
        assert bridge.lines() == [f"profile import {json.dumps(str(file))}"]
        assert dialog.importing

    drive(app, body)


def test_the_imported_profile_shows_at_once_and_the_list_lands_on_it(tmp_path: Path) -> None:
    file = ofl_file(tmp_path)
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await tap(pilot, form.choose, app)
        dialog = app.screen
        assert isinstance(dialog, ProfileDialog)
        await pilot.press(*"rgb")  # a filter that would hide it
        await pilot.press("ctrl+o")
        await answer(pilot, app, str(file))
        bridge.events.append(ShowChanged(rig(choices=(*CHOICES[:2], IMPORTED, *CHOICES[2:]))))
        await settle(pilot, app)
        assert app.screen is dialog
        assert dialog.field.value == ""
        assert [choice.name for choice in dialog.shown][2] == "acme Test"
        assert dialog.list.highlighted == 2
        assert not dialog.importing
        await pilot.press("enter")
        await settle(pilot, app)
        assert form.profile == "acme Test"
        assert form.chosen_mode() == ModeInfo("All", 1, 1)
        assert bridge.lines() == [f"profile import {json.dumps(str(file))}"]

    drive(app, body)


def test_a_library_profile_imported_into_the_show_is_the_one_landed_on(tmp_path: Path) -> None:
    """A file of a profile the library has, with its id: its row was there,
    as the library's, and is the show's now."""
    file = ofl_file(tmp_path)
    bridge = FakeBridge()
    app = on_f3(bridge)
    embedded = ProfileChoice("Blinder", "show", "Acme", (ModeInfo("2ch", 2, 1),), "1", "1")

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        await tap(pilot, page.panel.form.choose, app)
        dialog = app.screen
        assert isinstance(dialog, ProfileDialog)
        await pilot.press("ctrl+o")
        await answer(pilot, app, str(file))
        bridge.events.append(ShowChanged(rig(choices=(*CHOICES[:2], embedded, *CHOICES[2:3]))))
        await settle(pilot, app)
        assert dialog.shown[dialog.list.highlighted or 0].name == "Blinder"
        assert not dialog.importing

    drive(app, body)


def test_the_show_changing_keeps_the_row_the_picker_is_on() -> None:
    """With no import on its way, the list follows the show and stays put."""
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        await tap(pilot, page.panel.form.choose, app)
        dialog = app.screen
        assert isinstance(dialog, ProfileDialog)
        await pilot.press("down", "down")
        assert dialog.shown[dialog.list.highlighted or 0].name == "RGB Bar"
        bridge.events.append(ShowChanged(rig(choices=(*CHOICES[:2], IMPORTED, *CHOICES[2:]))))
        await settle(pilot, app)
        assert "acme Test" in [choice.name for choice in dialog.shown]
        assert dialog.shown[dialog.list.highlighted or 0].name == "RGB Bar"

    drive(app, body)


def test_a_refused_import_says_why_under_the_list(tmp_path: Path) -> None:
    """The log is behind the dialog. The list does not move for a later change."""
    file = ofl_file(tmp_path)
    line = f"profile import {json.dumps(str(file))}"
    why = "error: the show has a profile named 'acme Test'"
    bridge = FakeBridge(replies={line: Reply(False, why)})
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        await tap(pilot, page.panel.form.choose, app)
        dialog = app.screen
        assert isinstance(dialog, ProfileDialog)
        assert not dialog.error.display
        await pilot.press("ctrl+o")
        await answer(pilot, app, str(file))
        assert app.screen is dialog
        assert dialog.error.display
        assert str(dialog.error.content) == "the show has a profile named 'acme Test'"
        assert not dialog.importing
        bridge.events.append(ShowChanged(rig(choices=(*CHOICES[:2], IMPORTED, *CHOICES[2:]))))
        await settle(pilot, app)
        assert dialog.list.highlighted == 0
        bridge.replies.clear()
        await pilot.press("ctrl+o")
        await answer(pilot, app, str(file))
        assert not dialog.error.display  # a new try clears it

    drive(app, body)


def test_esc_on_the_path_leaves_the_picker_as_it_was() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        await tap(pilot, page.panel.form.choose, app)
        dialog = app.screen
        await pilot.press("ctrl+o", "escape")
        await settle(pilot, app)
        assert app.screen is dialog
        assert bridge.lines() == []

    drive(app, body)


# ------------------------------------------------------- the new fixture form


def test_add_enters_edit_mode_and_shows_the_form() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        panel = page.panel
        assert page.editing
        assert panel.adding
        assert panel.form.display
        assert not panel.body.display
        assert not panel.hint.display
        assert not panel.done.display
        assert str(panel.border_title) == "FIXTURE · new"
        assert page.add_button.inert  # it shows already
        form = panel.form
        assert form.choose.label == "choose…"
        assert words(form.number_value) == "302"
        assert words(form.count_value) == "1"
        assert form.patching.at == (1, 37)
        assert words(form.patching.takes) == "choose a profile"
        assert form.send.inert  # no profile yet
        assert bridge.lines() == []

    drive(app, body)


def test_the_hint_names_add() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(FixturesPage)
        page.set_editing(True)
        await pilot.pause()
        assert words(page.panel.hint) == "click a fixture, or [+ add]"

    drive(app, body)


def test_choosing_a_profile_sends_nothing_and_shows_its_modes() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await pick(pilot, app, form.choose, "rgb")
        assert form.choose.label == "RGB Bar…"
        assert [b.label.plain for b in form.modes.buttons] == ["[3ch · 3]", "[6ch · 6]"]
        assert lit(form.modes) == ["[3ch · 3]"]
        assert form.patching.at == (1, 37)  # three channels fit the gap
        assert words(form.patching.takes) == "takes 1.37–1.39 · free"
        assert not form.send.inert
        await tap_chip(pilot, form.modes, "6ch", app)
        assert lit(form.modes) == ["[6ch · 6]"]
        assert form.patching.at == (1, 44)  # six do not: the proposal follows the size
        assert bridge.lines() == []

    drive(app, body)


def test_a_library_profile_not_yet_embedded_shows_its_footprint() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await pick(pilot, app, form.choose, "blinder")
        assert "Blinder" not in [p.name for p in rig().profiles]
        assert words(form.patching.takes) == "takes 1.37–1.38 · free"

    drive(app, body)


def test_the_picker_starts_on_the_profile_chosen_before() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await pick(pilot, app, form.choose, "blinder")
        await tap(pilot, form.choose, app)
        assert isinstance(app.screen, ProfileDialog)
        assert app.screen.list.highlighted == 3
        await pilot.press("escape")
        await settle(pilot, app)
        assert form.profile == "Blinder"  # Esc keeps it

    drive(app, body)


def test_choosing_the_same_profile_again_keeps_its_mode() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await pick(pilot, app, form.choose, "rgb")
        await tap_chip(pilot, form.modes, "6ch", app)
        await tap(pilot, form.choose, app)
        await pilot.press("enter")
        await settle(pilot, app)
        assert lit(form.modes) == ["[6ch · 6]"]

    drive(app, body)


def test_add_sends_one_line_with_thru_and_the_address() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await pick(pilot, app, form.choose, "head")
        await tap(pilot, form.more, app)
        await tap(pilot, form.more, app)
        assert words(form.range) == "302 thru 304"
        assert words(form.patching.takes) == "takes 1.44–1.91 · free"
        await tap(pilot, form.send, app)
        assert bridge.lines() == ['fixture add 302 thru 304 "Head" mode "16ch" at 1.44']

    drive(app, body)


def test_add_with_none_sends_no_address_and_one_writes_no_thru() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await pick(pilot, app, form.choose, "par")
        await tap_chip(pilot, form.patching.chips, "none", app)
        await tap(pilot, form.send, app)
        assert bridge.lines() == ['fixture add 302 "Par" mode "4ch"']

    drive(app, body)


def test_a_name_with_a_quote_goes_out_escaped() -> None:
    choices = (ProfileChoice('Par "LED"', "library", "Acme", (ModeInfo('4"ch', 4, 1),)),)
    bridge = FakeBridge()
    app = on_f3(bridge, rig(choices=choices))

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await pick(pilot, app, form.choose, "par")
        await tap(pilot, form.send, app)
        assert bridge.lines() == [r'fixture add 302 "Par \"LED\"" mode "4\"ch" at 1.44']

    drive(app, body)


def test_after_add_the_form_stays_with_the_next_number_and_the_next_free_address() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await pick(pilot, app, form.choose, "par")
        await tap(pilot, form.more, app)
        await tap(pilot, form.send, app)
        assert words(form.number_value) == "304"
        assert page.panel.adding

        added = (
            FixtureInfo(302, 1, "Par 302", "Par", "4ch", 4, (1, 44)),
            FixtureInfo(303, 1, "Par 303", "Par", "4ch", 4, (1, 48)),
        )
        bridge.events.append(ShowChanged(rig(fixtures=(*FIXTURES, *added))))
        await settle(pilot, app)
        assert words(form.number_value) == "304"
        assert form.patching.at == (1, 52)
        assert form.profile == "Par"
        assert words(form.count_value) == "2"  # a rig goes in type by type
        assert not form.send.inert
        assert page.panel.chosen is None  # the new fixtures are not chosen
        assert bridge.lines() == ['fixture add 302 thru 303 "Par" mode "4ch" at 1.44']

    drive(app, body)


def test_the_next_number_steps_over_what_is_taken_after_the_block() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await pick(pilot, app, form.choose, "par")
        await tap(pilot, form.ask, app)
        await answer(pilot, app, "100")
        await tap(pilot, form.send, app)
        assert form.number == 103  # 101 and 102 are taken

    drive(app, body)


def test_the_next_address_comes_after_a_show_that_arrives_before_the_reply() -> None:
    bridge = FakeBridge(auto_reply=False)
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await pick(pilot, app, form.choose, "head")
        await tap(pilot, form.patching.ask, app)
        await answer(pilot, app, "200")
        await tap(pilot, form.send, app)
        added = FixtureInfo(302, 1, "Head 302", "Head", "16ch", 16, (1, 200))
        bridge.events.append(ShowChanged(rig(fixtures=(*FIXTURES, added))))
        await settle(pilot, app)
        assert form.patching.at == (1, 200)  # still the operator's
        assert form.clash() == [302]
        sent = bridge.sent[-1]
        bridge.events.append(CommandDone(sent.ticket, sent.line, sent.origin, True, (), 0.0, False))
        await settle(pilot, app)
        assert words(form.number_value) == "303"
        assert form.patching.at == (1, 44)

    drive(app, body)


def test_a_refused_add_leaves_the_form_as_it_is() -> None:
    line = 'fixture add 302 "Head" mode "16ch" at 1.44'
    bridge = FakeBridge(replies={line: Reply(False, "error: no")})
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await pick(pilot, app, form.choose, "head")
        await tap(pilot, form.send, app)
        assert bridge.lines() == [line]
        assert words(form.number_value) == "302"

    drive(app, body)


def test_a_number_starts_at_the_highest_plus_one_and_steps_over_taken_ones() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        assert form.number == 302
        await tap(pilot, form.fewer_number, app)  # 301 is taken
        assert form.number == 300
        await tap(pilot, form.more_number, app)
        assert form.number == 302

    drive(app, body)


def test_a_step_is_free_for_the_whole_count() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await tap(pilot, form.ask, app)
        await answer(pilot, app, "198")
        await tap(pilot, form.more, app)
        await tap(pilot, form.more_number, app)
        assert form.number == 199  # 199 and 200 are free
        await tap(pilot, form.more_number, app)
        assert form.number == 204  # 201 and 203 are taken: 204 and 205 are the next two
        assert form.clash() == []
        await tap(pilot, form.fewer_number, app)
        assert form.number == 199

    drive(app, body)


def test_a_taken_number_in_the_range_makes_add_inert_and_is_named() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await pick(pilot, app, form.choose, "par")
        await tap(pilot, form.ask, app)
        await answer(pilot, app, "200")
        assert not form.send.inert
        await tap(pilot, form.more, app)
        assert form.clash() == [201]
        assert words(form.taken_words) == "201 is taken"
        assert form.taken_words.display
        assert form.send.inert
        await tap(pilot, form.send, app)
        assert bridge.lines() == []
        await tap(pilot, form.more, app)
        await tap(pilot, form.more, app)
        await tap(pilot, form.more, app)
        assert words(form.taken_words) == "201, 203 are taken"
        await tap(pilot, form.fewer, app)
        await tap(pilot, form.fewer, app)
        await tap(pilot, form.fewer, app)
        await tap(pilot, form.fewer, app)
        assert form.count == 1
        assert form.fewer.inert
        assert not form.taken_words.display
        assert not form.send.inert

    drive(app, body)


def test_number_is_a_dialog_that_refuses_a_taken_one() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await tap(pilot, form.ask, app)
        assert isinstance(app.screen, TextDialog)
        assert app.screen.note == "taken: 101–102, 201, 203, 301"
        await answer(pilot, app, "201")
        assert isinstance(app.screen, TextDialog)
        await answer(pilot, app, "50")
        assert form.number == 50

    drive(app, body)


def test_the_address_is_proposed_for_the_whole_block_until_the_operator_gives_one() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await pick(pilot, app, form.choose, "rgb")
        assert form.patching.at == (1, 37)
        await tap(pilot, form.more, app)  # six channels: not in the gap
        assert form.patching.at == (1, 44)
        await tap(pilot, form.patching.ask, app)
        await answer(pilot, app, "300")
        await tap(pilot, form.more, app)
        assert form.patching.at == (1, 300)  # the operator's stays
        await tap(pilot, form.patching.next_free, app)
        assert form.patching.at == (1, 44)
        await tap(pilot, form.more, app)
        assert form.patching.at == (1, 44)

    drive(app, body)


@pytest.mark.parametrize("how", ["next free", "chip"])
def test_next_free_and_a_universe_hand_the_address_back_to_the_room(how: str) -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await pick(pilot, app, form.choose, "rgb")
        await tap(pilot, form.patching.ask, app)
        await answer(pilot, app, "300")
        if how == "chip":
            await tap_chip(pilot, form.patching.chips, "2 Balcony", app)
            assert form.patching.at == (2, 1)
            await tap_chip(pilot, form.patching.chips, "1 Stage", app)
        else:
            await tap(pilot, form.patching.next_free, app)
        assert form.patching.at == (1, 37)
        await tap(pilot, form.more, app)
        assert form.patching.at == (1, 44)  # it follows the size again

    drive(app, body)


def test_a_block_past_512_makes_add_inert() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await pick(pilot, app, form.choose, "head")
        await tap(pilot, form.patching.ask, app)
        await answer(pilot, app, "490")
        await tap(pilot, form.more, app)
        assert words(form.patching.takes) == "takes 1.490–1.521 · past channel 512"
        assert form.send.inert

    drive(app, body)


def test_a_block_that_ends_on_channel_512_fits() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await pick(pilot, app, form.choose, "head")
        await tap(pilot, form.patching.ask, app)
        await answer(pilot, app, "497")
        assert words(form.patching.takes) == "takes 1.497–1.512 · free"
        assert not form.send.inert

    drive(app, body)


def test_a_show_with_no_universe_adds_without_a_patch() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge, rig(universes=(), fixtures=()))

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        assert lit(form.patching.chips) == ["[none]"]
        assert form.number == 1
        assert form.fewer_number.inert  # nothing below it
        await pick(pilot, app, form.choose, "par")
        await tap(pilot, form.send, app)
        assert bridge.lines() == ['fixture add 1 "Par" mode "4ch"']

    drive(app, body)


def test_a_full_universe_takes_nothing_until_another_is_chosen() -> None:
    wall = FixtureInfo(1, 1, "Wall", "Wall", "512", 512, (1, 1))
    bridge = FakeBridge()
    app = on_f3(bridge, rig(fixtures=(wall,)))

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await pick(pilot, app, form.choose, "par")
        assert words(form.patching.takes) == "no room for 4 channels"
        assert form.send.inert
        await tap_chip(pilot, form.patching.chips, "2 Balcony", app)
        assert form.patching.at == (2, 1)
        assert not form.send.inert

    drive(app, body)


def test_a_universe_that_leaves_the_show_takes_the_form_to_none() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await tap_chip(pilot, form.patching.chips, "2 Balcony", app)
        bridge.events.append(ShowChanged(rig(universes=(STAGE,))))
        await settle(pilot, app)
        assert form.patching.universe is None
        assert lit(form.patching.chips) == ["[none]"]

    drive(app, body)


def test_a_profile_that_leaves_the_choices_takes_the_form_back_to_choosing() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        await pick(pilot, app, form.choose, "rgb")
        bridge.events.append(ShowChanged(rig(choices=CHOICES[:2])))
        await settle(pilot, app)
        assert form.choose.label == "choose…"
        assert not form.modes.display
        assert form.send.inert
        assert "[6ch · 6]" not in [item.label for item in page.items()]  # hidden: no stop

    drive(app, body)


def test_done_leaves_the_form_for_the_panel_and_the_next_one_keeps_only_the_profile() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 102)
        panel = page.panel
        await tap(pilot, page.add_button, app)
        form = panel.form
        await pick(pilot, app, form.choose, "par")
        await tap(pilot, form.more, app)
        await tap(pilot, form.done, app)
        assert page.editing
        assert not panel.adding
        assert panel.body.display
        assert panel.done.display
        assert not form.display
        assert str(panel.border_title) == "FIXTURE · 102 Head 2"
        assert not page.add_button.inert

        await tap(pilot, page.add_button, app)
        assert form.profile == "Par"
        assert form.count == 1

    drive(app, body)


def test_a_click_on_a_row_chooses_it_in_the_forms_place() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        await click_cell(pilot, page.rig, 0, "name")
        await settle(pilot, app)
        assert not page.panel.adding
        assert page.panel.chosen == 101
        assert str(page.panel.border_title) == "FIXTURE · 101 Head 1"
        assert not page.add_button.inert

    drive(app, body)


def test_leaving_edit_mode_leaves_the_form() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        await tap(pilot, page.edit, app)
        assert not page.editing
        assert not page.panel.adding
        await tap(pilot, page.edit, app)
        assert page.editing
        assert not page.panel.form.display

    drive(app, body)


def test_the_pane_cursor_stops_on_the_form_and_no_inert_control() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        rows = [f"fixture {f.number} {f.name}" for f in FIXTURES]
        labels = [item.label for item in page.items()]
        assert labels == [
            "edit",
            *rows,
            "choose…",
            "number −",
            "number +",
            "number…",
            "count +",
            "[none]",
            "[2 Balcony]",
            "address…",
            "next free",
            "done",
        ]
        await pick(pilot, app, form.choose, "rgb")
        await tap(pilot, form.more, app)
        labels = [item.label for item in page.items()]
        assert labels[len(rows) + 1 : len(rows) + 3] == ["RGB Bar…", "[6ch · 6]"]
        assert "count −" in labels
        assert labels[-2:] == ["add", "done"]
        assert len(labels) == len(set(labels))
        await pilot.press("tab", *["down"] * labels.index("add"), "enter")
        await settle(pilot, app)
        assert bridge.lines() == ['fixture add 302 thru 303 "RGB Bar" mode "3ch" at 1.44']

    drive(app, body)


def test_the_form_opens_at_its_top_in_a_panel_that_was_scrolled() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel = page.panel
        assert panel.max_scroll_y > 0
        panel.scroll_end(animate=False)
        await pilot.pause()
        assert panel.scroll_offset.y > 0
        page.add_fixture()
        await pilot.pause()
        await pilot.pause()
        assert panel.max_scroll_y > 0  # the form does not fit either
        assert panel.scroll_offset.y == 0

    drive(app, body, size=(150, 20))


def test_the_form_shows_under_the_table_below_100_columns() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        await pilot.pause()
        await pilot.pause()
        assert page.panel.region.x == page.sheet.region.x  # under the table
        assert page.scroll_offset.y > 0  # and brought into sight

    drive(app, body, size=(99, 30))


# ---------------------------------------------------- changing the profile


def test_profile_opens_the_picker_on_its_own_profile_and_sends_nothing() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel = page.panel
        assert not panel.swapping.display
        await tap(pilot, panel.ask_swap, app)
        assert isinstance(app.screen, ProfileDialog)
        assert app.screen.list.highlighted == 0  # Head
        await pilot.press("escape")
        await settle(pilot, app)
        assert not panel.swapping.display
        assert bridge.lines() == []

    drive(app, body)


def test_change_sends_the_profile_and_the_mode_chosen() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel = page.panel
        await pick(pilot, app, panel.ask_swap, "rgb")
        assert panel.swapping.display
        assert words(panel.swap_words) == "to RGB Bar · 3 channels"
        assert lit(panel.swap_modes) == ["[3ch · 3]"]
        await tap_chip(pilot, panel.swap_modes, "6ch", app)
        assert words(panel.swap_words) == "to RGB Bar · 6 channels"
        assert bridge.lines() == []
        await tap(pilot, panel.swap_send, app)
        assert bridge.lines() == ['fixture 102 profile "RGB Bar" mode "6ch"']
        assert not panel.swapping.display

    drive(app, body)


def test_a_refused_change_stays_and_cancel_drops_it() -> None:
    line = 'fixture 102 profile "RGB Bar" mode "3ch"'
    bridge = FakeBridge(replies={line: Reply(False, "error: no")})
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel = page.panel
        await pick(pilot, app, panel.ask_swap, "rgb")
        await tap(pilot, panel.swap_send, app)
        assert bridge.lines() == [line]
        assert panel.swapping.display
        await tap(pilot, panel.swap_keep, app)
        assert not panel.swapping.display
        assert bridge.lines() == [line]
        labels = [item.label for item in page.items()]
        assert "change" not in labels
        assert "cancel" not in labels

    drive(app, body)


def test_its_own_profile_takes_back_what_was_picked() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel = page.panel
        await pick(pilot, app, panel.ask_swap, "rgb")
        await tap(pilot, panel.ask_swap, app)
        assert isinstance(app.screen, ProfileDialog)
        assert app.screen.list.highlighted == 2  # RGB Bar, last chosen
        await pilot.press("up", "up", "enter")
        await settle(pilot, app)
        assert not panel.swapping.display

    drive(app, body)


def test_a_change_the_prompt_has_made_already_sends_nothing() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel = page.panel
        await pick(pilot, app, panel.ask_swap, "rgb")
        assert not panel.swap_send.inert
        moved = FixtureInfo(102, 1, "Head 2", "RGB Bar", "3ch", 3, (1, 17))
        fixtures = (FIXTURES[0], moved, *FIXTURES[2:])
        bridge.events.append(ShowChanged(rig(fixtures=fixtures)))
        await settle(pilot, app)
        assert panel.swap_send.inert
        await tap(pilot, panel.swap_send, app)
        assert bridge.lines() == []

    drive(app, body)


def test_a_form_field_is_not_redrawn_for_nothing() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        form = page.panel.form
        before = form.number_value.content
        form.draw()
        assert form.number_value.content is before  # a new str would mean it was updated
        form.step(1)
        assert form.number_value.content == "303"

    drive(app, body)


def test_a_change_goes_with_the_fixture_chosen() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel = page.panel
        await pick(pilot, app, panel.ask_swap, "rgb")
        panel.choose(101)
        await pilot.pause()
        assert not panel.swapping.display

    drive(app, body)


def test_a_two_mode_profile_hides_its_mode_lines_while_a_change_shows() -> None:
    fixture = FixtureInfo(1, 1, "Bar", "RGB Bar", "3ch", 3, (1, 1))
    bar = ProfileInfo("RGB Bar", frozenset({"intensity"}), (), None, TWO)
    show = rig(fixtures=(fixture,), profiles=(*PROFILES, bar))
    bridge = FakeBridge()
    app = on_f3(bridge, show)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app, 1)
        panel = page.panel
        assert panel.modes.display
        await pick(pilot, app, panel.ask_swap, "blinder")
        assert not panel.modes.display
        await tap(pilot, panel.swap_keep, app)
        assert panel.modes.display

    drive(app, body)


def test_the_pane_cursor_stops_on_a_change() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        await pick(pilot, app, page.panel.ask_swap, "rgb")
        labels = [item.label for item in page.items()]
        start = labels.index("profile…")
        assert labels[start : start + 4] == ["profile…", "[6ch · 6]", "change", "cancel"]

    drive(app, body)


def test_the_rig_table_follows_a_new_fixture() -> None:
    bridge = FakeBridge()
    app = on_f3(bridge)

    async def body(pilot: Pilot[int]) -> None:
        page = await open_form(pilot, app)
        added = FixtureInfo(150, 1, "Par 150", "Par", "4ch", 4, (1, 44))
        bridge.events.append(ShowChanged(rig(fixtures=(*FIXTURES, added))))
        await settle(pilot, app)
        assert column(page.rig, "number") == ["101", "102", "150", "201", "203", "301"]

    drive(app, body)


# ------------------------------------------------------------ update profile


def test_update_profile_is_grey_until_the_librarys_revision_differs() -> None:
    old = ProfileChoice("Head", "show", "Generic", ONE, "7", "1")
    bridge = FakeBridge()
    current = ProfileChoice("Head", "show", "Generic", ONE, "1", "1")
    app = on_f3(bridge, rig(choices=(current, *CHOICES[1:])))

    async def body(pilot: Pilot[int]) -> None:
        page = await enter(pilot, app)
        panel = page.panel
        assert panel.update_profile.inert
        assert "update profile" not in [item.label for item in page.items()]
        await tap(pilot, panel.update_profile, app)
        assert bridge.lines() == []
        bridge.events.append(ShowChanged(rig(choices=(old, *CHOICES[1:]))))
        await settle(pilot, app)
        assert not panel.update_profile.inert
        labels = [item.label for item in page.items()]
        assert labels[labels.index("profile…") + 1] == "update profile"
        await tap(pilot, panel.update_profile, app)
        assert bridge.lines() == ['profile update "Head"']
        panel.choose(201)  # a Par: its copy is the library's, or the library has none
        await pilot.pause()
        assert panel.update_profile.inert

    drive(app, body)
