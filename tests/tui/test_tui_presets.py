"""F6 Presets (spec §8.6, plan Phase 2, ``docs/plans/tui-presets-plan.md``):
what presets apply to, a panel per pool that has presets or that the rig
can record into, the tiles' previews and lines, new presets showing at
once, the tables the PRESET panel uses, and edit mode: choosing, HOLDS and
its users, rename, renumber, delete, a new preset's number and name, the
pane cursor and the layout; the editors: the scope, the selection and
``[its fixtures]``, a section of encoder rows per family (a rotation's bar
signed), RECORDS, ``[record]``, ``[load]``, the writes and their hints,
the output read while the panel shows, the programmer followed, the hint
on what a scope keeps, and the rows no profile takes; the colour picker:
the field's cells, its marker and colour modes, a click and a drag, the
named chips, the readout, and the component rows once a colour is held;
option rows: what the selection offers, the lit option,
nothing selected, and their pane-cursor stops; spread: busk's rule, the
ends read back, the toggles, the bars, steps and curves, the last spread
sent, a drag, and the pane cursor. Headless, with a fake bridge."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from rich.text import Text
from textual.pilot import Pilot
from textual.widgets import Input
from tui_fakes import FakeBridge, Reply, drive, make_app, programmer, settle, show_model

import busk
from busk.compiler.cues import spread_fraction as busk_spread_fraction
from busk_tui import attributes, colors, commands
from busk_tui.bridge import selection_options
from busk_tui.bridge import show_model as model_of
from busk_tui.formats import cues_text, numbers_text
from busk_tui.model import (
    CueInfo,
    CueListInfo,
    ElementOutput,
    FixtureInfo,
    HeldValue,
    OutputChanged,
    OutputModel,
    PresetEntry,
    PresetInfo,
    ProfileInfo,
    ProgrammerChanged,
    ShowChanged,
    ShowModel,
)
from busk_tui.pages.presets import PresetsPage
from busk_tui.shell import BuskApp
from busk_tui.widgets import colorpicker, encoders
from busk_tui.widgets.colorpicker import (
    CHIPS,
    ColorField,
    ColorPicker,
    cell_color,
    chip_buttons,
    field_text,
    hex_text,
    ink,
    marker,
)
from busk_tui.widgets.controls import ButtonStrip
from busk_tui.widgets.dialogs import ConfirmDialog, TextDialog, free_step
from busk_tui.widgets.encoders import EncoderRow
from busk_tui.widgets.log import LogView
from busk_tui.widgets.options import LIT, OptionRow
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.preset_panel import HINTS, KEEPS, Chosen, PresetPanel
from busk_tui.widgets.prompt import HintRow
from busk_tui.widgets.spread import SpreadLine, SpreadRow
from busk_tui.widgets.tiles import PresetTile, preview

PRESETS = (
    PresetInfo("position", 2, "Centre", None, (("pan", 15.0), ("tilt", 10.0))),
    PresetInfo("color", 2, "Red", (1.0, 0.0, 0.0)),
    PresetInfo("color", 1, "Blue", (0.0, 0.0, 1.0)),
    PresetInfo("position", 1, "Audience", None, (("pan", None), ("tilt", 40.0))),
    PresetInfo("intensity", 1, "Half", None, (("intensity", 0.5),)),
)


def presets_show(*presets: PresetInfo) -> ShowModel:
    return show_model(
        presets=presets or PRESETS,
        fixtures=(FixtureInfo(101, 1, "Spot 101", "Spot"), FixtureInfo(102, 1, "Spot 102", "Spot")),
    )


def presets_app(bridge: FakeBridge) -> BuskApp:
    return make_app(bridge, page=6)


def started(bridge: FakeBridge, show: ShowModel | None = None, **changes: Any) -> None:
    bridge.events += [ShowChanged(show or presets_show()), ProgrammerChanged(programmer(**changes))]


def tiles(app: BuskApp) -> list[PresetTile]:
    return list(app.query(PresetTile))


def page(app: BuskApp) -> PresetsPage:
    return app.query_one(PresetsPage)


def tile(app: BuskApp, pool: str, number: int | None) -> PresetTile:
    """A preset's tile; ``number`` ``None``: the pool's record tile."""
    return next(
        t
        for t in tiles(app)
        if t.pool == pool and (t.preset is None if number is None else t.number == number)
    )


def plain(widget: Any) -> str:
    rendered = widget.content if hasattr(widget, "content") else widget.render()
    return rendered.plain if isinstance(rendered, Text) else str(rendered)


def test_previews() -> None:
    red = preview(PRESETS[1], "256")
    assert red.plain == "████"
    assert str(red.style) == "color(196)"
    assert preview(PresetInfo("color", 3, "Two", None), "256").plain == "mixed"
    wheel = PresetInfo("color", 4, "Wheel", None, (("colorWheel", "red"),))
    assert preview(wheel, "256").plain == "colorWheel red"
    assert preview(PRESETS[0], "256").plain == "15°/10°"
    assert preview(PRESETS[3], "256").plain == "mixed/40°"
    assert preview(PresetInfo("position", 3, "Pan", None, (("pan", -30.0),)), "256").plain == (
        "-30°/·"
    )
    assert preview(PRESETS[4], "256").plain == "▅ 50%"
    assert preview(
        PresetInfo("intensity", 2, "Full", None, (("intensity", 1.0),)), "256"
    ).plain == ("█ 100%")
    assert preview(PresetInfo("intensity", 3, "?", None, (("intensity", None),)), "256").plain == (
        "mixed"
    )
    beam = PresetInfo("beam", 1, "Narrow", None, (("zoom", 20.0), ("iris", 0.5)))
    assert preview(beam, "256").plain == "zoom 20°"
    assert preview(PresetInfo("focus", 1, "Sharp", None, (("focus", 0.3),)), "256").plain == (
        "focus 30%"
    )
    everything = PresetInfo("all", 1, "Look", (1.0, 0.0, 0.0), (("intensity", 1.0),))
    assert preview(everything, "256").plain == "████"


def test_a_panel_per_pool_with_presets_in_busks_order() -> None:
    bridge = FakeBridge()
    app = presets_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        titles = [str(panel.border_title) for panel in app.query_one(PresetsPage).query(Panel)]
        assert titles == ["COLOR", "POSITION", "INTENSITY"]
        assert [(t.pool, t.number, t.preset is None) for t in tiles(app)] == [
            ("color", 1, False),
            ("color", 2, False),
            ("color", 3, True),
            ("position", 1, False),
            ("position", 2, False),
            ("position", 3, True),
            ("intensity", 1, False),
            ("intensity", 2, True),
        ]
        first = plain(tiles(app)[0]).splitlines()
        assert first[0].startswith("1 ")
        assert first[0].endswith("████")
        assert first[1] == "Blue"

    drive(app, body)


def test_a_tile_runs_its_preset_and_the_last_opens_the_panel() -> None:
    bridge = FakeBridge()
    app = presets_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        found = tiles(app)
        assert not page(app).panel.display
        await pilot.click(found[1])
        await pilot.click(found[3])
        assert [(s.line, s.origin) for s in bridge.sent] == [
            ("preset color 2", "ui"),
            ("preset position 1", "ui"),
        ]
        await pilot.click(found[5])
        assert app.prompt.value == ""
        assert page(app).editing
        assert page(app).panel.display
        assert page(app).panel.chosen == Chosen("position", 3, new=True)
        assert str(page(app).panel.border_title) == "PRESET · new position 3"
        assert len(bridge.sent) == 2

    drive(app, body)


def test_what_presets_apply_to() -> None:
    bridge = FakeBridge()
    app = presets_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        header = app.query_one("#presets-header")
        assert plain(header) == (
            "applies to nothing: select fixtures first · click a tile to apply it"
        )
        bridge.events.append(
            ProgrammerChanged(programmer(version=2, selection=((101, 1), (102, 1))))
        )
        await settle(pilot, app)
        assert plain(header) == "applies to 101 thru 102 (2) · click a tile to apply it"
        assert plain(page(app).edit) == "[edit]"
        await pilot.click(page(app).edit)
        assert plain(header) == "applies to 101 thru 102 (2) · click a tile to edit it"
        assert plain(page(app).edit) == "[edit ●]"

    drive(app, body)


def test_a_new_preset_shows_at_once_and_an_empty_show_says_how() -> None:
    bridge = FakeBridge()
    app = presets_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, presets_show(PresetInfo("beam", 1, "Narrow", None, (("zoom", 20.0),))))
        await settle(pilot, app)
        assert [t.number for t in tiles(app)] == [1, 2]
        beam = PresetInfo("beam", 2, "Wide", None, (("zoom", 30.0),))
        narrow = PresetInfo("beam", 1, "Narrow", None, (("zoom", 20.0),))
        bridge.events.append(ShowChanged(presets_show(narrow, beam)))
        await settle(pilot, app)
        assert [(t.number, t.preset is None) for t in tiles(app)] == [
            (1, False),
            (2, False),
            (3, True),
        ]
        bridge.events.append(ShowChanged(show_model()))
        await settle(pilot, app)
        assert tiles(app) == []
        assert "no presets yet" in plain(app.query_one("#pools").children[0])

    drive(app, body)


def test_the_pane_cursor_runs_a_tile_and_opens_the_panel_on_a_record() -> None:
    bridge = FakeBridge()
    app = presets_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        await pilot.press("tab", "right", "right", "enter")  # Red (after edit): runs, stays
        assert [s.line for s in bridge.sent] == ["preset color 2"]
        assert tiles(app)[1].marked
        await pilot.press("right", "enter")  # the record tile: the panel, the cursor stays
        assert page(app).panel.chosen == Chosen("color", 3, new=True)
        assert tiles(app)[2].marked
        assert app.cursor.active
        assert app.prompt.value == ""

    drive(app, body)


def test_tiles_go_as_many_across_as_fit() -> None:
    bridge = FakeBridge()
    app = presets_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge)
        await settle(pilot, app)
        page = app.query_one(PresetsPage)
        assert page.grids[0].styles.grid_size_columns == (150 - 6 + 1) // 16
        await pilot.resize_terminal(60, 40)
        await pilot.pause()
        assert page.grids[0].styles.grid_size_columns == 3

    drive(app, body)


# ------------------------------------------------------------ the tables


def test_the_pools_the_rig_can_record_into(club: busk.OfflineShow) -> None:
    assert attributes.recordable(model_of(club.show)) == (
        "color", "position", "beam", "intensity", "all",
    )  # fmt: skip
    assert attributes.recordable(presets_show()) == ()  # profiles unknown: nothing to take
    assert attributes.recordable(None) == ()


def test_a_pools_editor_has_the_rows_and_options_the_rig_takes(club: busk.OfflineShow) -> None:
    model = model_of(club.show)

    def shown(pool: str) -> list[tuple[str, list[str], tuple[str, ...]]]:
        return [
            (section.family, [e.attribute for e in section.encoders], section.options)
            for section in attributes.pool_rows(pool, model)
        ]

    assert shown("color") == [("color", ["color.r", "color.g", "color.b", "color.w"], ())]
    assert shown("beam") == [
        ("beam", ["zoom"], ("gobo1",)),
        ("shutter", ["strobeRate"], ("shutter",)),
    ]
    assert shown("focus") == [("focus", [], ())]
    assert [family for family, _, _ in shown("all")] == [
        "intensity", "position", "color", "beam", "focus", "shutter",
    ]  # fmt: skip


def test_a_pools_editor_lists_the_rows_no_profile_takes(club: busk.OfflineShow) -> None:
    model = model_of(club.show)

    def absent(pool: str) -> dict[str, tuple[str, ...]]:
        return {section.family: section.absent for section in attributes.pool_rows(pool, model)}

    assert absent("color") == {
        "color": (
            "color.a", "color.uv", "cto", "colorMacroRate",
            "colorWheel", "colorMacro", "colorEffect",
        ),
    }  # fmt: skip
    assert absent("intensity") == {"intensity": ()}
    assert absent("focus") == {"focus": ("focus",)}
    for pool, families in attributes.POOL_FAMILIES.items():  # taken or not, every row is there
        sections = attributes.pool_rows(pool, model)
        found = {encoder.attribute for section in sections for encoder in section.encoders}
        found |= {name for section in sections for name in (*section.options, *section.absent)}
        rows = {e.attribute for family, row in attributes.ROWS if family in families for e in row}
        options = {name for family, row in attributes.OPTIONS if family in families for name in row}
        assert found == rows | options


def test_what_a_record_takes_and_who_is_not_selected() -> None:
    held = (
        HeldValue(101, 1, "pan", -30.0, None),
        HeldValue(102, 1, "pan", 30.0, None),
        HeldValue(101, 1, "intensity", 1.0, None),
        HeldValue(201, 1, "color", (("r", 1.0), ("g", 0.0), ("b", 0.0)), "Red", ("color", 2)),
        HeldValue(101, 1, "shutter", "strobe", None),
        HeldValue(101, 1, "strobeRate", 10.0, None),
    )
    state = programmer(values=held, selection=((101, 1),))
    position = attributes.records("position", state)
    assert position.attributes == (("pan", ((101, 1), (102, 1))),)
    assert position.unselected == 1
    beam = attributes.records("beam", state)
    assert beam.attributes == (("shutter", ((101, 1),)), ("strobeRate", ((101, 1),)))
    assert beam.unselected == 0
    assert [name for name, _ in attributes.records("all", state).attributes] == [
        "pan", "intensity", "color", "shutter", "strobeRate",
    ]  # fmt: skip
    assert attributes.records("all", state).unselected == 2  # 102 and 201
    assert attributes.records("focus", state) == attributes.Records((), 0)
    assert attributes.records("color", None) == attributes.Records((), 0)


def test_cues_and_numbers_compressed() -> None:
    lists = (
        CueListInfo(4, "Song", "sequence", None, (CueInfo("1", "", ()),)),
        CueListInfo(
            10, "Chase", "chase", None, tuple(CueInfo(str(n), "", ()) for n in (1, 2, 3, 4, 7))
        ),
    )
    cues = ((4, "1"), (10, "1"), (10, "2"), (10, "3"), (10, "4"), (10, "7"), (15, "1"))
    assert cues_text(cues, lists) == "4/1, 10/1–10/7, 15/1"  # 7 follows 4 in list 10
    assert cues_text(((10, "1"), (10, "3")), lists) == "10/1, 10/3"
    assert cues_text((), lists) == ""
    assert numbers_text((7, 1, 2, 3, 4, 9, 10)) == "1–4, 7, 9–10"
    assert numbers_text(()) == ""


def test_a_new_number_steps_over_the_taken() -> None:
    taken = frozenset({1, 2, 4})
    assert free_step(3, 1, taken) == 5
    assert free_step(3, -1, taken) == 3  # 2 and 1 are taken: it stays
    assert free_step(5, -1, taken) == 3
    assert free_step(1, -1, frozenset()) == 1


# -------------------------------------------------------------- edit mode


def club_app(club: busk.OfflineShow, **changes: Any) -> tuple[FakeBridge, BuskApp]:
    """F6 on the club show's model (heads selected unless ``changes`` say)."""
    bridge = FakeBridge()
    app = presets_app(bridge)
    changes.setdefault("selection", ((101, 1), (102, 1)))
    started(bridge, model_of(club.show), **changes)
    return bridge, app


def panel(app: BuskApp) -> PresetPanel:
    return page(app).panel


def test_every_pool_the_rig_can_record_into_shows(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        titles = [str(found.border_title) for found in page(app).query(Panel)]
        assert titles == ["COLOR", "POSITION", "BEAM", "INTENSITY", "ALL"]  # no focus channel
        beam = [t for t in tiles(app) if t.pool == "beam"]
        assert [(t.number, t.preset) for t in beam] == [(1, None)]
        await pilot.click(beam[0])
        assert panel(app).chosen == Chosen("beam", 1, new=True)
        assert beam[0].has_class("-chosen")
        assert bridge.sent == []

    drive(app, body)


def test_edit_mode_chooses_instead_of_applying(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click(tile(app, "color", 2))
        assert bridge.lines() == ["preset color 2"]
        await pilot.click(page(app).edit)
        assert panel(app).display
        assert "click a tile to edit it" in plain(panel(app).hint)
        await pilot.click(tile(app, "color", 2))
        assert bridge.lines() == ["preset color 2"]  # chosen, not applied
        assert panel(app).chosen == Chosen("color", 2)
        assert str(panel(app).border_title) == 'PRESET · color 2 "Red"'
        assert tile(app, "color", 2).has_class("-chosen")
        await pilot.click(tile(app, "position", 1))
        assert not tile(app, "color", 2).has_class("-chosen")
        await pilot.click(panel(app).done)
        assert not page(app).editing
        assert not panel(app).display
        assert not tile(app, "position", 1).has_class("-chosen")
        await pilot.click(tile(app, "position", 1))
        assert bridge.lines() == ["preset color 2", "preset position 1"]

    drive(app, body)


def test_what_a_preset_holds_and_the_cues_that_use_it(club: busk.OfflineShow) -> None:
    _, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "color", 2))
        await pilot.pause()
        assert plain(panel(app).holds).splitlines() == [
            "HOLDS · 1 value",
            "color  ████ 1 0 0  global",
        ]
        assert plain(panel(app).use).splitlines() == [
            "used by cue 4/1, 10/1–10/4, 15/1, 18/2",
            "to delete it, take it out of those first",
        ]
        page(app).choose(tile(app, "position", 1))
        await pilot.pause()
        assert plain(panel(app).holds).splitlines() == [
            "HOLDS · 4 values",
            "pan   -30°  target 101",
            "pan   30°   target 102",
            "tilt  40°   target 101",
            "tilt  40°   target 102",
        ]
        assert plain(panel(app).use).startswith("used by cue 6/1, 9/2\n")

    drive(app, body)


def test_holds_crops_a_long_scope_instead_of_wrapping(tupper: busk.OfflineShow) -> None:
    for line in ("sel group 4", "set gobo1 star", "set gobo1Rotation 90", "set zoom 30"):
        assert tupper.execute(line).ok
    assert tupper.execute('record preset beam 9 "Stars"').ok  # profile: the heads agree
    _, app = tupper_app(tupper, 4)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "beam", 9))
        await pilot.pause()
        holds = panel(app).holds
        assert plain(holds).splitlines() == [
            "HOLDS · 3 values",
            "gobo1          star   profile TupperDMX Moving Head",
            "gobo1Rotation  90°/s  profile TupperDMX Moving Head",
            "zoom           30°    profile TupperDMX Moving Head",
        ]
        assert holds.size == (47, 4)  # a line per value beside the pools: none wraps
        assert [holds.render_line(y).text.rstrip() for y in range(4)] == [
            "HOLDS · 3 values",
            "gobo1          star   profile TupperDMX Moving…",
            "gobo1Rotation  90°/s  profile TupperDMX Moving…",
            "zoom           30°    profile TupperDMX Moving…",
        ]
        await pilot.resize_terminal(99, 48)  # under the pools, as wide as the page: room
        await pilot.pause()
        assert holds.size.height == 4
        assert [holds.render_line(y).text.rstrip() for y in range(4)] == plain(holds).splitlines()

    drive(app, body)


def unused(club: busk.OfflineShow) -> ShowModel:
    """The club show with a preset no cue uses: color 5 "Crimson", global."""
    show = model_of(club.show)
    red = next(p for p in show.presets if p.name == "Red")
    crimson = PresetInfo("color", 5, "Crimson", (1.0, 0.25, 0.0), entries=red.entries)
    return ShowModel(**{**_fields(show), "presets": (*show.presets, crimson)})


def _fields(show: ShowModel) -> dict[str, Any]:
    return {name: getattr(show, name) for name in ShowModel.__dataclass_fields__}


def test_rename_and_renumber_through_a_dialog(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(ShowChanged(unused(club)))
        await settle(pilot, app)
        page(app).choose(tile(app, "color", 5))
        await pilot.pause()
        await pilot.click(panel(app).rename)
        dialog = app.screen
        assert isinstance(dialog, TextDialog)
        assert dialog.query_one(Input).value == "Crimson"
        dialog.query_one(Input).value = "  "
        await pilot.press("enter")
        assert app.screen is dialog  # refused: it stays
        assert plain(dialog.error) == "a name cannot be empty"
        dialog.query_one(Input).value = 'The "Scarlet"'
        await pilot.press("enter")
        assert not isinstance(app.screen, TextDialog)
        assert bridge.lines() == [r'''rename preset color 5 "The \"Scarlet\""''']
        await pilot.click(panel(app).renumber)
        dialog = app.screen
        assert isinstance(dialog, TextDialog)
        assert "taken in color: 1–4" in plain(dialog.query_one(".note"))
        for refused, why in (
            ("3", "3 is taken"),
            ("0", "a whole number from 1"),
            ("x", "a whole number from 1"),
        ):
            dialog.query_one(Input).value = refused
            await pilot.press("enter")
            assert app.screen is dialog
            assert plain(dialog.error) == why
        dialog.query_one(Input).value = "9"
        await pilot.press("enter")
        assert bridge.lines()[-1] == "preset color 5 number 9"
        assert len(bridge.lines()) == 2
        await settle(pilot, app)  # its CommandDone: the panel follows to 9
        assert panel(app).chosen == Chosen("color", 9)
        await pilot.click(panel(app).rename)
        await pilot.press("escape")
        assert not isinstance(app.screen, TextDialog)
        assert len(bridge.lines()) == 2

    drive(app, body)


def test_delete_is_inert_while_cues_use_it_and_asks_first(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(ShowChanged(unused(club)))
        await settle(pilot, app)
        page(app).choose(tile(app, "color", 2))
        await pilot.pause()
        assert panel(app).delete.inert
        await pilot.click(panel(app).delete)
        assert not isinstance(app.screen, ConfirmDialog)
        assert "delete" not in [stop.item.label for stop in panel(app).stops()]
        page(app).choose(tile(app, "color", 5))
        await pilot.pause()
        assert not panel(app).delete.inert
        assert plain(panel(app).use) == "used by no cue"
        await pilot.click(panel(app).delete)
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)
        assert dialog.question == 'Delete preset color 5 "Crimson"?'
        await pilot.press("n")
        assert ("info", "cancelled: delete preset color 5") in app.query_one(LogView).entries
        assert bridge.lines() == []
        await pilot.click(panel(app).delete)
        await pilot.press("y")
        assert bridge.lines() == ["delete preset color 5"]
        await settle(pilot, app)  # done: back to "click a tile"
        assert panel(app).chosen is None
        assert panel(app).hint.display

    drive(app, body)


def test_the_delete_question_says_the_programmer_holds_it(club: busk.OfflineShow) -> None:
    crimson = (("r", 1.0), ("g", 0.25), ("b", 0.0))
    held = tuple(
        HeldValue(number, 1, "color", crimson, "Crimson", ("color", 5)) for number in (201, 202)
    )
    bridge, app = club_app(club, values=held)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(ShowChanged(unused(club)))
        await settle(pilot, app)
        page(app).choose(tile(app, "color", 5))
        await pilot.pause()
        await pilot.click(panel(app).delete)
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)
        assert dialog.question.splitlines()[1] == (
            "The programmer holds it on 2 fixtures: they would show it as gone."
        )

    drive(app, body)


def test_a_new_presets_number_and_name_send_nothing(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click(tile(app, "color", None))
        assert panel(app).chosen == Chosen("color", 5, new=True)
        assert plain(panel(app).name_new) == "[name: Color 5…]"
        await pilot.click(panel(app).up)
        await pilot.click(panel(app).down)
        await pilot.click(panel(app).down)  # 4 … 1 are taken: it stays at 5
        assert panel(app).chosen == Chosen("color", 5, new=True)
        await pilot.click(panel(app).number_new)
        dialog = app.screen
        assert isinstance(dialog, TextDialog)
        dialog.query_one(Input).value = "2"
        await pilot.press("enter")
        assert plain(dialog.error) == "2 is taken"
        dialog.query_one(Input).value = "12"
        await pilot.press("enter")
        await pilot.click(panel(app).name_new)
        dialog = app.screen
        assert isinstance(dialog, TextDialog)
        assert plain(dialog.query_one(".note")) == "empty: busk names it Color 12"
        dialog.query_one(Input).value = "Crimson"
        await pilot.press("enter")
        assert panel(app).chosen == Chosen("color", 12, new=True, name="Crimson")
        assert str(panel(app).border_title) == "PRESET · new color 12"
        assert bridge.lines() == []

    drive(app, body)


def test_once_recorded_the_panel_shows_the_new_preset(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click(tile(app, "color", None))
        bridge.events.append(ShowChanged(unused(club)))  # color 5 recorded at the prompt
        await settle(pilot, app)
        assert panel(app).chosen == Chosen("color", 5)
        assert str(panel(app).border_title) == 'PRESET · color 5 "Crimson"'
        assert tile(app, "color", 5).has_class("-chosen")
        assert tile(app, "color", None).number == 6

    drive(app, body)


def test_a_refused_renumber_leaves_the_choice(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club)
    bridge.replies["preset color 5 number 9"] = Reply(ok=False, text="error: no")

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(ShowChanged(unused(club)))
        await settle(pilot, app)
        page(app).choose(tile(app, "color", 5))
        await pilot.pause()
        await pilot.click(panel(app).renumber)
        app.screen.query_one(Input).value = "9"
        await pilot.press("enter")
        await settle(pilot, app)
        assert panel(app).chosen == Chosen("color", 5)

    drive(app, body)


def test_the_pane_cursor_in_edit_mode(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(ShowChanged(unused(club)))
        await settle(pilot, app)
        await pilot.press("tab", "enter")  # [edit]
        assert page(app).editing
        labels = [item.label for item in app.cursor.items]
        assert labels[:3] == ["edit", "edit color 1", "edit color 2"]
        assert labels[-1] == "done"
        await pilot.press("right", "right", "enter")  # Red: chosen
        assert panel(app).chosen == Chosen("color", 2)
        await pilot.pause()
        scopes = ["scope global", "scope profile", "scope target"]
        groups = ["sel group 1", "sel group 2", "sel group 3", "sel group 4", "sel none"]
        its = "sel " + ", ".join(f"fixture {n}" for n in (101, 102, 201, 202, 203, 204, 301))
        rows = []
        for component in "rgbw":  # the name, [−] and [+], inert: a step pre-fills
            rows += [f"color.{component}", *[f"set color.{component} by {s}5%" for s in ("-", "")]]
        chips = [button.line.text for button in chip_buttons("256")]  # the field: mouse only
        bottom = ["preset color 2", "clear", "blind on", "done"]  # nothing to merge: inert
        red = ["rename…", "number…", *scopes, *groups, its, *chips, *rows, *bottom]  # delete: inert
        assert [item.label for item in page(app).items()][-len(red) :] == red
        page(app).choose(tile(app, "color", 5))
        labels = [item.label for item in page(app).items()]
        assert labels[labels.index("rename…") :][:4] == [
            "rename…",
            "number…",
            "delete",
            *scopes[:1],
        ]
        page(app).choose(tile(app, "color", None))
        await pilot.pause()
        labels = [item.label for item in page(app).items()]
        new = ["number down", "number up", "number…", "name…", *scopes, *groups]
        assert labels[labels.index("number down") :][: len(new)] == new
        assert labels[-3:] == ["clear", "blind on", "done"]  # nothing to record: inert
        assert bridge.lines() == []

    drive(app, body)


@pytest.mark.parametrize(("width", "beside"), [(150, True), (100, True), (99, False)])
def test_the_panel_beside_the_pools_and_under_them(
    club: busk.OfflineShow, width: int, beside: bool
) -> None:
    _, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click(page(app).edit)
        await pilot.pause()
        pools, shown = page(app).pools.region, panel(app).region
        if beside:
            assert shown.width == 52
            assert shown.x > pools.right
            columns = (width - 53 - 6 + 1) // 16  # the panel and its margin: 53 cells
            assert page(app).grids[0].styles.grid_size_columns == columns
            assert panel(app).styles.max_height is not None
        else:
            assert shown.width == pools.width
            assert shown.y >= pools.bottom
            assert panel(app).styles.max_height is None
        await pilot.click(tile(app, "color", 2))  # a click under the pools: into sight
        await pilot.pause()
        await pilot.pause()
        assert (page(app).scroll_y > 0) is not beside

    drive(app, body, size=(width, 40))


# ------------------------------------------------------------ the editors

RED = (("r", 1.0), ("g", 0.0), ("b", 0.0))


def holding(*numbers: int, attribute: str = "color", value: Any = RED) -> tuple[HeldValue, ...]:
    """The programmer's values: ``attribute`` at ``value`` on each fixture."""
    return tuple(HeldValue(number, 1, attribute, value, None) for number in numbers)


async def tap(pilot: Pilot[int], widget: Any) -> None:
    """A click on a widget of the panel, scrolled into sight first, once laid
    out (a panel just drawn is not yet: its widgets have no region)."""
    await pilot.pause()
    widget.scroll_visible(animate=False)
    await pilot.pause()
    await pilot.click(widget)


def lit(app: BuskApp) -> list[str]:
    return [name for name, button in panel(app).scopes.items() if button.reverse]


def test_the_scope_starts_at_the_pools_default_or_the_presets_own(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club, values=holding(101, 102))

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click(tile(app, "color", None))
        assert lit(app) == ["global"]
        await tap(pilot, panel(app).scopes["target"])
        assert lit(app) == ["target"]
        assert bridge.lines() == []  # a scope sends nothing
        await tap(pilot, panel(app).record)
        assert bridge.lines() == ["record preset color 5 target"]
        page(app).choose(tile(app, "position", None))
        assert lit(app) == ["target"]
        page(app).choose(tile(app, "color", 2))  # Red: its values are global
        assert lit(app) == ["global"]
        page(app).choose(tile(app, "color", None))  # chosen again: from its default
        assert lit(app) == ["global"]

    drive(app, body)


def test_the_hint_under_selection_says_what_the_scope_keeps(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "color", None))
        await pilot.pause()
        assert plain(panel(app).keeps) == KEEPS["global"]
        for scope in ("profile", "target", "global"):
            await tap(pilot, panel(app).scopes[scope])
            await pilot.pause()
            assert plain(panel(app).keeps) == KEEPS[scope]
            assert panel(app).keeps.size.height == 2  # the same height: nothing jumps
        assert bridge.lines() == []  # a hint, as a scope, sends nothing
        page(app).choose(tile(app, "position", None))
        assert plain(panel(app).keeps) == KEEPS["target"]
        page(app).choose(tile(app, "beam", None))
        assert plain(panel(app).keeps) == KEEPS["profile"]
        page(app).choose(tile(app, "color", 2))  # Red: its values are global
        assert plain(panel(app).keeps) == KEEPS["global"]
        children = list(panel(app).children)
        assert children.index(panel(app).keeps) == children.index(panel(app).selection) + 1

    drive(app, body)


def test_a_preset_of_the_show_starts_at_the_scope_its_values_share(club: busk.OfflineShow) -> None:
    show = model_of(club.show)
    blue = next(p for p in show.presets if p.name == "Blue")
    per_target = PresetInfo(
        "color", 5, "Per head", None,
        entries=(PresetEntry("target", (101, 1), "color", RED),
                 PresetEntry("target", (102, 1), "color", RED)),
    )  # fmt: skip
    mixed = PresetInfo("color", 6, "Mixed", None, entries=(*blue.entries, *per_target.entries))
    bridge, app = club_app(club, values=holding(101, 102))

    async def body(pilot: Pilot[int]) -> None:
        presets = (*show.presets, per_target, mixed)
        bridge.events.append(ShowChanged(ShowModel(**{**_fields(show), "presets": presets})))
        await settle(pilot, app)
        page(app).choose(tile(app, "color", 5))
        assert lit(app) == ["target"]
        await tap(pilot, panel(app).writes["merge"])
        page(app).choose(tile(app, "color", 6))
        assert lit(app) == ["global"]  # they differ: the pool's default
        assert bridge.lines() == ["record preset color 5 target merge"]

    drive(app, body)


def test_record_is_inert_until_the_programmer_holds_a_value(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click(tile(app, "color", None))
        assert plain(panel(app).records) == "RECORDS nothing: set a value above"
        assert panel(app).record.inert
        await tap(pilot, panel(app).record)
        assert bridge.lines() == []
        held = programmer(version=2, selection=((201, 1), (202, 1), (203, 1), (204, 1)),
                          values=holding(201, 202, 203, 204))  # fmt: skip
        bridge.events.append(ProgrammerChanged(held))  # from the prompt, say
        await settle(pilot, app)
        assert plain(panel(app).records) == "RECORDS\ncolor  on 201 thru 204 (4)"
        assert not panel(app).record.inert
        assert "record preset color 5 global" in [item.label for item in page(app).items()]
        await tap(pilot, panel(app).record)
        assert bridge.lines() == ["record preset color 5 global"]

    drive(app, body)


def test_records_says_how_many_it_takes_that_are_not_selected(club: busk.OfflineShow) -> None:
    values = (*holding(101, 102, 201), *holding(101, 102, attribute="pan", value=-30.0))
    _, app = club_app(club, values=values)  # the heads selected

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "color", None))
        assert plain(panel(app).records).splitlines() == [
            "RECORDS · 1 not selected, recorded too",
            "color  on 101 thru 102, 201 (3)",
        ]
        page(app).choose(tile(app, "position", None))
        assert plain(panel(app).records).splitlines() == ["RECORDS", "pan  on 101 thru 102 (2)"]

    drive(app, body)


def test_a_new_presets_record_names_it_only_when_given_a_name(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club, values=holding(101, 102))

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click(tile(app, "color", None))
        await pilot.click(panel(app).name_new)
        app.screen.query_one(Input).value = "Crimson"
        await pilot.press("enter")
        await tap(pilot, panel(app).record)
        assert bridge.lines() == ['record preset color 5 global "Crimson"']

    drive(app, body)


def test_its_fixtures_load_and_the_writes(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "position", 1))  # Audience: target values on the heads
        await pilot.pause()
        strip = panel(app).groups
        assert [b.label.plain for b in strip.buttons] == [
            "[Heads]", "[Washes]", "[Bar]", "[All]", "[none]", "[its fixtures]",
        ]  # fmt: skip
        assert strip.buttons[-1].line.text == "sel fixture 101, fixture 102"
        assert all(button.inert for button in panel(app).writes.values())  # nothing held
        assert not panel(app).load.inert
        await tap(pilot, panel(app).load)
        assert bridge.lines() == ["preset position 1"]
        pans = holding(101, 102, attribute="pan", value=-15.0)
        bridge.events.append(
            ProgrammerChanged(programmer(version=2, selection=((101, 1), (102, 1)), values=pans))
        )
        await settle(pilot, app)
        for how in ("merge", "replace", "remove"):
            await tap(pilot, panel(app).writes[how])
        assert bridge.lines()[1:] == [
            "record preset position 1 target merge",
            "record preset position 1 target replace",
            "record preset position 1 remove",  # every scope
        ]
        page(app).choose(tile(app, "color", 2))  # Red, global: every fixture with a colour
        await pilot.pause()
        assert strip.buttons[-1].line.text == (
            "sel fixture 101, fixture 102, fixture 201, fixture 202, fixture 203, fixture 204, "
            "fixture 301"
        )

    drive(app, body)


def test_load_is_inert_with_nothing_selected(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club, selection=())

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "color", 2))
        await pilot.pause()
        assert plain(panel(app).selection) == "SELECTION nothing selected"
        assert panel(app).load.inert
        await tap(pilot, panel(app).load)
        assert bridge.lines() == []
        assert "preset color 2" not in [item.label for item in page(app).items()]

    drive(app, body)


def test_a_new_preset_has_no_load_nor_writes_and_one_of_the_show_no_record(
    club: busk.OfflineShow,
) -> None:
    _, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "color", None))
        assert panel(app).record.display
        assert not panel(app).load.display
        assert not any(button.display for button in panel(app).writes.values())
        assert [b.label.plain for b in panel(app).groups.buttons][-1] == "[none]"
        page(app).choose(tile(app, "color", 2))
        assert not panel(app).record.display
        assert panel(app).load.display
        assert all(button.display for button in panel(app).writes.values())
        await tap(pilot, panel(app).done)
        await pilot.click(page(app).edit)  # nothing chosen: no editors
        assert panel(app).hint.display
        assert not panel(app).editors.display
        assert not panel(app).keeps.display
        assert not panel(app).clear.display
        assert [item.label for item in page(app).items()][-1] == "done"

    drive(app, body)


def test_the_editors_have_a_section_per_family_the_pool_records(club: busk.OfflineShow) -> None:
    _, app = club_app(club)

    def sections() -> list[tuple[str, list[str]]]:
        found = []
        for block in panel(app).editors.children:
            heading, *rows = block.children
            names = [row.encoder.attribute for row in rows if isinstance(row, EncoderRow)]
            found.append((plain(heading), names))
        return found

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "intensity", None))
        await pilot.pause()
        assert sections() == [("INTENSITY", ["intensity"])]
        page(app).choose(tile(app, "beam", None))
        await pilot.pause()
        assert sections() == [("BEAM", ["zoom"]), ("SHUTTER", ["strobeRate"])]
        page(app).choose(tile(app, "all", None))
        await pilot.pause()
        assert [name for name, _ in sections()] == [
            "INTENSITY", "POSITION", "COLOR", "BEAM", "FOCUS", "SHUTTER",
        ]  # fmt: skip

    drive(app, body)


def test_a_row_no_profile_takes_shows_dimmed_and_does_nothing(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "color", None))
        await pilot.pause()
        rows = list(panel(app).query(".pp-absent"))
        assert [plain(row).split()[0] for row in rows] == [
            "color.a", "color.uv", "cto", "colorMacroRate",
            "colorWheel", "colorMacro", "colorEffect",
        ]  # fmt: skip
        assert plain(rows[0]) == "color.a          no fixture takes it"
        assert {row.content.style for row in rows} == {colors.DIM}
        section = list(panel(app).editors.children[0].children)
        assert section[-len(rows) :] == rows  # after the rows that act
        assert not {stop.widget for stop in panel(app).stops()} & set(rows)
        await tap(pilot, rows[0])
        assert bridge.lines() == []
        page(app).choose(tile(app, "all", None))  # the rig takes nothing of the family
        await pilot.pause()
        block = next(b for b in panel(app).editors.children if plain(b.children[0]) == "FOCUS")
        assert [plain(row) for row in block.children[1:]] == [
            "focus            no fixture takes it"
        ]

    drive(app, body)


def test_a_long_attribute_keeps_a_gap_before_no_fixture_takes_it(club: busk.OfflineShow) -> None:
    _, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "beam", None))
        await pilot.pause()
        rows = {plain(row).split()[0]: row for row in panel(app).query(".pp-absent")}
        assert plain(rows["soundSensitivity"]) == "soundSensitivity no fixture takes it"
        assert rows["soundSensitivity"].size.height == 1  # no wrap at the panel's width

    drive(app, body)


def test_a_rotation_row_has_a_signed_bar() -> None:
    head = ProfileInfo("Head", frozenset({"gobo1Rotation"}), (("gobo1Rotation", -360.0, 360.0),))
    show = presets_show()
    show = ShowModel(**{**_fields(show), "profiles": (head,),
                        "fixtures": (FixtureInfo(101, 1, "Head 101", "Head"),)})  # fmt: skip
    bridge = FakeBridge()
    app = presets_app(bridge)
    values = holding(101, attribute="gobo1Rotation", value=90.0)

    async def body(pilot: Pilot[int]) -> None:
        started(bridge, show, selection=((101, 1),), values=values)
        await settle(pilot, app)
        page(app).choose(tile(app, "beam", None))
        await pilot.pause()
        await pilot.pause()
        (row,) = panel(app).rows
        assert row.bar.signed
        assert plain(row.value) == "90°/s"
        width = row.bar.size.width
        filled = row.bar.render().plain  # type: ignore[union-attr]
        assert filled.index("█") == round(width / 2)  # from the centre, rightward
        await pilot.click(row.bar, offset=((width - 1) // 4, 0))  # a quarter: -180°/s
        await pilot.pause()
        assert bridge.lines() == [
            f"set gobo1Rotation {round(-360 + 720 * ((width - 1) // 4) / (width - 1))}"
        ]

    drive(app, body)


def test_the_panel_reads_the_output_while_it_shows(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        assert bridge.watching == (False, False)
        await pilot.click(tile(app, "intensity", None))
        assert bridge.watching == (True, False)
        out = ElementOutput(101, 1, 0.4, None, 10.0, 20.0, 15.0)
        bridge.events.append(OutputChanged(OutputModel(1, (out,))))
        await settle(pilot, app)
        (row,) = panel(app).rows
        assert plain(row.value) == "40%"
        assert row.value.content.style == colors.DIM  # the output's: dim
        await tap(pilot, panel(app).done)
        assert bridge.watching == (False, False)
        await pilot.press("f2")
        assert bridge.watching == (True, False)  # F2 reads it too
        await pilot.press("f6")
        assert bridge.watching == (False, False)

    drive(app, body)


def test_the_editors_follow_the_programmer(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click(tile(app, "intensity", None))
        (row,) = panel(app).rows
        assert plain(row.value) == "—"
        assert row.minus.inert
        assert plain(panel(app).blind) == "[blind on]"
        held = programmer(version=2, selection=((101, 1), (102, 1)), blind=True,
                          values=holding(101, 102, attribute="intensity", value=0.7))  # fmt: skip
        bridge.events.append(ProgrammerChanged(held))  # typed at the prompt
        await settle(pilot, app)
        assert plain(row.value) == "70%"
        assert row.value.content.style == colors.MAGENTA
        assert not row.minus.inert
        assert plain(panel(app).blind) == "[blind off]"
        assert panel(app).blind.reverse
        await tap(pilot, panel(app).blind)
        await tap(pilot, row.plus)
        await tap(pilot, panel(app).clear)
        assert bridge.lines() == ["blind off", "set intensity by 5%", "clear"]

    drive(app, body)


def test_a_writes_hint_shows_under_the_mouse(club: busk.OfflineShow) -> None:
    _, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "color", 2))
        await pilot.pause()
        merge = panel(app).writes["merge"]
        merge.scroll_visible(animate=False)
        await pilot.pause()
        await pilot.hover(merge)
        await pilot.pause()
        assert plain(app.query_one(HintRow)) == HINTS["merge"]
        await pilot.hover(page(app).header)
        await pilot.pause()
        assert plain(app.query_one(HintRow)) != HINTS["merge"]

    drive(app, body)


# ------------------------------------------------------- the colour picker


def test_the_fields_cells_run_through_the_hue_and_the_saturation() -> None:
    width = 48
    assert cell_color(0, 4, width) == (1.0, 0.0, 0.0)  # red, saturated, at the left
    assert cell_color(4, 4, width) == (1.0, 0.5, 0.0)  # 30°
    assert cell_color(8, 4, width) == (1.0, 1.0, 0.0)  # 60°
    assert cell_color(16, 4, width) == (0.0, 1.0, 0.0)  # 120°
    assert cell_color(32, 4, width) == (0.0, 0.0, 1.0)  # 240°
    assert cell_color(47, 4, width) == (1.0, 0.0, 0.12)  # just short of red again
    assert cell_color(0, 0, width) == (1.0, 0.8, 0.8)  # palest at the top
    assert cell_color(0, 2, width) == (1.0, 0.4, 0.4)


def test_the_marker_is_the_cell_nearest_a_colour_at_full_value() -> None:
    width = 47
    for x in range(width):
        for y in range(5):
            assert marker(cell_color(x, y, width), width) == (x, y)
    assert marker((1.0, 0.0, 0.05), width) == (0, 4)  # the hue wraps round
    assert marker((1.0, 0.75, 0.75), width) == (0, 0)  # nearest saturation: 0.2
    assert marker((0.5, 0.0, 0.0), width) is None  # not at full value
    assert marker((1.0, 1.0, 1.0), width) is None  # a grey: no cell
    assert marker((1.0, 0.95, 0.95), width) is None
    assert marker(None, width) is None


def test_the_field_draws_in_each_colour_mode() -> None:
    def cells(mode: Any) -> list[str]:
        return [str(span.style) for span in field_text(12, mode, (0, 4)).spans]

    true, xterm, ansi = cells("truecolor"), cells("256"), cells("16")
    assert len(true) == len(xterm) == len(ansi) == 60
    assert true[0] == "#ffcccc"  # the palest red
    assert all(style.startswith("color(") and int(style[6:-1]) >= 16 for style in xterm[:48])
    assert all(style.startswith("color(") and int(style[6:-1]) < 16 for style in ansi[:48])
    assert (true[48], xterm[48], ansi[48]) == (
        f"{colors.BG} on #ff0000", f"{colors.BG} on color(196)", f"{colors.BG} on color(9)",
    )  # fmt: skip
    rows = field_text(12, "256", (0, 4)).plain.splitlines()
    assert rows[:4] == ["█" * 12] * 4
    assert rows[4] == "●" + "█" * 11


def test_the_named_chips_send_their_colour(club: busk.OfflineShow) -> None:
    lines = {button.label.plain.strip(): button.line.text for button in chip_buttons("256")}
    assert list(lines) == [name for name, _ in CHIPS]
    assert lines["red"] == "set color 1 0 0"
    assert lines["warm"] == "set color 1 0.75 0.45"
    pool = {p.name: p.color for p in model_of(club.show).presets if p.pool == "color"}
    for name in ("Blue", "Red", "Green", "Amber"):  # the club's own colours
        assert dict(CHIPS)[name.lower()] == pool[name]
    assert ink((1.0, 1.0, 0.0)) == colors.BG  # dark on a light colour
    assert ink((0.0, 0.0, 1.0)) == colors.FG
    assert hex_text((1.0, 0.25, 0.0)) == "#ff4000"


def sent(bridge: FakeBridge) -> list[tuple[str, str, str | None]]:
    return [(s.line, s.origin, s.key) for s in bridge.sent]


def picker(app: BuskApp) -> ColorPicker:
    (found,) = panel(app).pickers
    return found


def test_the_colour_section_starts_with_the_picker(club: busk.OfflineShow) -> None:
    _, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "color", None))
        await pilot.pause()
        (block,) = panel(app).editors.children
        heading, first, *rows = block.children
        assert plain(heading) == "COLOR"
        assert first is picker(app)
        assert rows[: len(panel(app).rows)] == panel(app).rows  # then the dimmed ones
        assert rows[0].encoder.attribute == "color.r"
        labels = [item.label for item in page(app).items()]
        chips = [labels.index(button.line.text) for button in chip_buttons("256")]
        assert chips == sorted(chips)
        assert max(chips) < labels.index("color.r")  # the chips, then the rows
        page(app).choose(tile(app, "position", None))
        await pilot.pause()
        assert panel(app).pickers == []
        page(app).choose(tile(app, "all", None))
        await pilot.pause()
        assert len(panel(app).pickers) == 1

    drive(app, body)


async def click_field(pilot: Pilot[int], field: ColorField, x: int, y: int) -> None:
    await pilot.pause()
    field.scroll_visible(animate=False)
    await pilot.pause()
    await pilot.click(field, offset=(x, y))


def test_a_click_on_the_field_sends_the_cells_colour(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click(tile(app, "color", None))
        field = picker(app).field
        await click_field(pilot, field, 8, 3)
        line = commands.set_color(*cell_color(8, 3, field.size.width)).text
        assert sent(bridge) == [(line, "ui", "set:color")]
        assert ("ui", line) in app.query_one(LogView).entries
        await pilot.pause()
        assert field.picked is None  # done: the programmer's colour from now on

    drive(app, body)


def test_the_field_sets_only_with_something_selected(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club, selection=())

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click(tile(app, "color", None))
        await click_field(pilot, picker(app).field, 8, 3)
        assert bridge.lines() == []
        assert plain(picker(app).readout) == "— nothing selected"

    drive(app, body)


def test_a_drag_on_the_field_sends_at_most_every_drag_s_and_logs_the_last(
    club: busk.OfflineShow, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click(tile(app, "color", None))
        field = picker(app).field
        field.scroll_visible(animate=False)
        await pilot.pause()
        width = field.size.width
        monkeypatch.setattr(colorpicker, "DRAG_S", 60.0)
        await pilot.mouse_down(field, offset=(0, 4))
        assert field.picked == (0, 4)
        for x in range(1, 6):
            await pilot.hover(field, offset=(x, 4))
        assert bridge.sent == []  # a click sends on release only; the moves wait
        assert field._later is not None
        field._report()  # the timer: the newest cell
        await pilot.pause()
        monkeypatch.setattr(colorpicker, "DRAG_S", 0.0)
        await pilot.hover(field, offset=(10, 2))
        await pilot.mouse_up(field, offset=(20, 0))
        lines = sent(bridge)
        assert {origin for _, origin, _ in lines[:-1]} == {"internal"}
        assert len(lines) >= 3
        assert lines[0][0] == commands.set_color(*cell_color(5, 4, width)).text
        last = commands.set_color(*cell_color(20, 0, width)).text
        assert lines[-1] == (last, "ui", "set:color")
        logged = [text for kind, text in app.query_one(LogView).entries if kind == "ui"]
        assert logged == [last]

    drive(app, body)


def test_the_marker_and_the_readout_follow_the_programmer(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click(tile(app, "color", None))
        field = picker(app).field
        assert field.held is None
        assert plain(picker(app).readout) == "— no colour held: pick one, then the rows act"
        heads = ((101, 1), (102, 1))
        held = programmer(version=2, selection=heads, values=holding(101, 102))
        bridge.events.append(ProgrammerChanged(held))  # from the prompt, say
        await settle(pilot, app)
        assert field.held == (1.0, 0.0, 0.0)
        assert field.render().plain.splitlines()[4].startswith("●")  # type: ignore[union-attr]
        assert plain(picker(app).readout) == "████ 1 0 0 · #ff0000"
        blue = tuple(HeldValue(n, 1, "color", (("r", 0.0), ("g", 0.0), ("b", 1.0)), "Blue")
                     for n in (101, 102))  # fmt: skip
        bridge.events.append(ProgrammerChanged(programmer(version=3, selection=heads, values=blue)))
        await settle(pilot, app)
        width = field.size.width
        row = field.render().plain.splitlines()[4]  # type: ignore[union-attr]
        assert row.index("●") == round(2 / 3 * width) % width
        assert plain(picker(app).readout) == "████ 0 0 1 · #0000ff Blue"

    drive(app, body)


def test_the_component_rows_act_once_a_colour_is_held(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.click(tile(app, "color", None))
        red = next(row for row in panel(app).rows if row.encoder.attribute == "color.r")
        assert not red.bar.settable
        assert red.plus.inert
        await tap_chip(pilot, "amber")
        assert bridge.lines() == ["set color 1 0.5 0"]
        amber = holding(101, 102, value=(("r", 1.0), ("g", 0.5), ("b", 0.0)))
        held = programmer(version=2, selection=((101, 1), (102, 1)), values=amber)
        bridge.events.append(ProgrammerChanged(held))
        await settle(pilot, app)
        assert red.bar.settable
        await tap(pilot, red.minus)
        assert bridge.lines()[-1] == "set color.r by -5%"

    async def tap_chip(pilot: Pilot[int], name: str) -> None:
        await tap_label(pilot, picker(app).chips, f" {name} ")

    drive(app, body)


async def tap_label(pilot: Pilot[int], strip: ButtonStrip, label: str) -> None:
    """A click on the button of ``strip`` that reads ``label``, scrolled into
    sight first, once laid out."""
    await pilot.pause()
    strip.scroll_visible(animate=False)
    await pilot.pause()
    for y, line in enumerate(strip.lines(strip.size.width)):
        x = line.plain.find(label)
        if x >= 0:
            await pilot.click(strip, offset=(x + 1, y))
            return
    raise AssertionError(f"no button {label}")


# ------------------------------------------------------------ option rows

TUPPER = Path(__file__).resolve().parents[2] / "examples" / "tupperdmx" / "tupper-demo.show"


@pytest.fixture
def tupper() -> busk.OfflineShow:
    """The TupperDMX demo show, to select on (not saved)."""
    document, _ = busk.load_show(TUPPER)
    return busk.OfflineShow(document)


def tupper_app(
    tupper: busk.OfflineShow, group: int | None, values: tuple[HeldValue, ...] = ()
) -> tuple[FakeBridge, BuskApp]:
    """F6 on the TupperDMX show's model, ``group`` selected with the options
    busk's completion offers it (``None``: nothing selected)."""
    show = model_of(tupper.show)
    selection: tuple[tuple[int, int], ...] = ()
    options: tuple[tuple[str, tuple[str, ...]], ...] = ()
    if group is not None:
        assert tupper.execute(f"sel group {group}").ok
        selection = tupper.programmer.selection
        options = selection_options(tupper.expected, selection, attributes.taken(show))
    bridge = FakeBridge()
    app = presets_app(bridge)
    started(bridge, show, selection=selection, options=options, values=values)
    return bridge, app


def option_row(app: BuskApp, attribute: str) -> OptionRow:
    return next(row for row in panel(app).options if row.attribute == attribute)


def chips_of(row: OptionRow) -> list[str]:
    """A row's chips, ``*`` before the lit one: ``["open", "*star"]``."""
    return [
        ("*" if str(button.label.spans[0].style) == LIT else "") + button.label.plain[1:-1]
        for button in row.chips.buttons
    ]


def test_option_rows_offer_what_the_selection_offers(tupper: busk.OfflineShow) -> None:
    bridge, app = tupper_app(tupper, 4)  # the heads

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "beam", None))
        await pilot.pause()
        assert [row.attribute for row in panel(app).options] == [
            "gobo1", "prism", "effect", "shutter",
        ]  # fmt: skip
        assert chips_of(option_row(app, "gobo1")) == [
            "open", "breakup", "dots", "lines", "star", "spiral", "triangles", "closed",
        ]  # fmt: skip
        assert chips_of(option_row(app, "prism")) == ["off", "prism3"]
        effect = option_row(app, "effect")
        assert not effect.chips.display
        assert plain(effect.none) == "the selection has no effect"
        (beam, shutter) = panel(app).editors.children
        acting = [child for child in beam.children if not child.has_class("pp-absent")]
        assert [type(child).__name__ for child in acting] == [
            "Static", "EncoderRow", "SpreadRow", "EncoderRow", "SpreadRow",
            "EncoderRow", "SpreadRow", "SpreadLine",
            "OptionRow", "OptionRow", "OptionRow",
        ]  # fmt: skip
        assert option_row(app, "shutter").parent is shutter
        await tap_label(pilot, option_row(app, "gobo1").chips, "[star]")
        await tap_label(pilot, option_row(app, "prism").chips, "[prism3]")
        assert bridge.lines() == ["set gobo1 star", "set prism prism3"]

    drive(app, body)


def test_the_lit_option_follows_the_programmer(tupper: busk.OfflineShow) -> None:
    bridge, app = tupper_app(tupper, 4)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "beam", None))
        await pilot.pause()
        gobo = option_row(app, "gobo1")
        assert "*star" not in chips_of(gobo)
        model = app.programmer
        assert model is not None
        heads = holding(501, 502, 503, 504, attribute="gobo1", value="star")
        bridge.events.append(ProgrammerChanged(replace(model, version=2, values=heads)))
        await settle(pilot, app)
        assert [chip for chip in chips_of(gobo) if chip.startswith("*")] == ["*star"]
        spiral = holding(501, attribute="gobo1", value="spiral")  # the first selected's
        bridge.events.append(ProgrammerChanged(replace(model, version=3, values=spiral)))
        await settle(pilot, app)
        assert [chip for chip in chips_of(gobo) if chip.startswith("*")] == ["*spiral"]

    drive(app, body)


def test_the_blinders_offer_their_effects(tupper: busk.OfflineShow) -> None:
    bridge, app = tupper_app(tupper, 2)  # two blinders of four cells

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "beam", None))
        await pilot.pause()
        assert chips_of(option_row(app, "effect")) == ["off", "autoProgram", "soundActive"]
        assert plain(option_row(app, "gobo1").none) == "the selection has no gobo1"
        rate = next(row for row in panel(app).rows if row.encoder.attribute == "effectRate")
        assert rate.bar.settable
        await tap_label(pilot, option_row(app, "effect").chips, "[soundActive]")
        assert bridge.lines() == ["set effect soundActive"]

    drive(app, body)


def test_option_rows_with_nothing_selected(tupper: busk.OfflineShow) -> None:
    _, app = tupper_app(tupper, None)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "beam", None))
        await pilot.pause()
        assert [plain(row.none) for row in panel(app).options] == ["nothing selected"] * 4
        assert not any(row.stops() for row in panel(app).options)

    drive(app, body)


def test_the_pane_cursor_stops_on_each_option(tupper: busk.OfflineShow) -> None:
    _, app = tupper_app(tupper, 4)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "beam", None))
        await pilot.pause()
        labels = [item.label for item in page(app).items()]
        options = ("open", "breakup", "dots", "lines", "star", "spiral", "triangles", "closed")
        gobos = [f"set gobo1 {option}" for option in options]
        start = labels.index("set gobo1 open")
        assert labels[start : start + 10] == [*gobos, "set prism off", "set prism prism3"]
        assert labels.index("strobeRate") < labels.index("set shutter open")
        assert labels.index("set gobo1 open") > labels.index("zoom")

    drive(app, body)


# ----------------------------------------------------------------- spread

HEADS = ((101, 1), (102, 1))
FAN = (HeldValue(101, 1, "pan", -30.0, None), HeldValue(102, 1, "pan", 30.0, None))


def test_the_spread_rule_is_busks() -> None:
    for curve in (None, "center", "edges"):
        for n in range(1, 8):
            for k in range(n):
                fraction = busk_spread_fraction(curve or "linear", k, n)
                assert attributes.spread_fraction(curve, k, n) == fraction


def test_a_spreads_ends_from_the_values_it_gave() -> None:
    ends, fraction = attributes.spread_ends, attributes.spread_fraction
    assert ends([]) is None
    assert ends([(0.0, -30.0), (1.0, 30.0)]) == (-30.0, 30.0)
    centre = [(fraction("center", k, 5), value) for k, value in enumerate((0, 5, 10, 5, 0))]
    assert ends(centre) == (0.0, 10.0)
    edges = [(fraction("edges", k, 4), attributes.spread_at(10, 40, fraction("edges", k, 4)))
             for k in range(4)]  # fmt: skip
    assert ends(edges) == pytest.approx((10.0, 40.0))  # no element is at from
    assert ends([(0.0, -30.0), (0.0, -30.0)]) == (-30.0, -30.0)  # two, centre: to is unknown


def test_a_spread_reads_the_programmer_else_the_output() -> None:
    show = presets_show()
    pan = next(e for e in attributes.ROWS[1][1] if e.attribute == "pan")
    chosen = attributes.selected(show, programmer(selection=HEADS), None)
    held = programmer(selection=HEADS, values=FAN)
    found = attributes.spread_reading(pan, show, chosen, held, None, None)
    assert (found.ends, found.source, found.steps) == ((-30.0, 30.0), "programmer", True)
    assert found.held == ((0.0, -30.0), (1.0, 30.0))
    outs = (ElementOutput(101, 1, 0.0, None, 10.0, None, None),
            ElementOutput(102, 1, 0.0, None, 20.0, None, None))  # fmt: skip
    seen = attributes.spread_reading(pan, show, chosen, programmer(selection=HEADS),
                                     OutputModel(1, outs), None)  # fmt: skip
    assert (seen.ends, seen.source, seen.steps, seen.settable) == (
        (10.0, 20.0),
        "output",
        False,
        True,
    )
    none = attributes.spread_reading(pan, show, chosen, programmer(), None, None)
    assert (none.ends, none.source, none.settable) == (None, None, False)


def spread_row(app: BuskApp, attribute: str) -> SpreadRow:
    return next(row for row in panel(app).spreads if row.encoder.attribute == attribute)


def encoder_row(app: BuskApp, attribute: str) -> EncoderRow:
    return next(row for row in panel(app).rows if row.encoder.attribute == attribute)


def spread_line(app: BuskApp, section: int = 0) -> SpreadLine:
    return panel(app).spread_lines[section]


async def position_fan(pilot: Pilot[int], app: BuskApp) -> SpreadRow:
    """A new position preset, pan toggled to a spread."""
    await settle(pilot, app)
    page(app).choose(tile(app, "position", None))
    await tap_label(pilot, spread_line(app).chips, "[pan]")
    await pilot.pause()
    return spread_row(app, "pan")


def test_a_spread_toggle_shows_a_row_as_from_and_to(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club, values=FAN)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "position", None))
        await pilot.pause()
        line = spread_line(app)
        assert [button.label.plain for button in line.chips.buttons] == ["[pan]", "[tilt]"]
        assert not spread_row(app, "pan").display
        await tap_label(pilot, line.chips, "[pan]")
        await pilot.pause()
        fan = spread_row(app, "pan")
        assert fan.display
        assert not encoder_row(app, "pan").display
        assert str(line.chips.buttons[0].label.spans[0].style) == LIT
        assert [plain(end.name_text) for end in fan.ends] == [
            "pan        from", "             to",
        ]  # fmt: skip
        assert [plain(end.value) for end in fan.ends] == ["-30°", "30°"]
        assert fan.ends[0].value.content.style == colors.MAGENTA
        assert not fan.ends[0].minus.inert
        await tap_label(pilot, line.chips, "[pan]")
        await pilot.pause()
        assert encoder_row(app, "pan").display
        assert not fan.display
        assert bridge.lines() == []  # a toggle sends nothing

    drive(app, body)


def test_only_numbers_take_a_spread_not_a_colours_components(club: busk.OfflineShow) -> None:
    _, app = club_app(club)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page(app).choose(tile(app, "all", None))
        await pilot.pause()
        names = [name for line in panel(app).spread_lines for name in line.names]
        assert names == [row.encoder.attribute for row in panel(app).rows
                         if not row.encoder.attribute.startswith("color.")]  # fmt: skip
        assert "pan" in names
        assert "intensity" in names

    drive(app, body)


def test_a_spread_bar_a_step_and_a_curve_send_the_whole_spread(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club, values=FAN)

    async def body(pilot: Pilot[int]) -> None:
        fan = await position_fan(pilot, app)
        assert fan.reading is not None
        top = fan.reading.span[1]
        await pilot.click(fan.bars[1], offset=(fan.bars[1].size.width - 1, 0))
        await pilot.pause()
        assert sent(bridge) == [(f"set pan spread -30 {top:g}", "ui", "set:pan")]
        assert plain(fan.ends[1].value) == f"{top:g}°"  # what was sent, at once
        await tap(pilot, fan.ends[0].plus)
        await tap(pilot, fan.curves["center"])
        await pilot.pause()
        assert fan.curves["center"].reverse
        await tap(pilot, fan.curves["edges"])
        await tap(pilot, fan.curves["edges"])  # lit: linear again
        await pilot.pause()
        assert bridge.lines()[1:] == [
            f"set pan spread -15 {top:g}",
            f"set pan spread -15 {top:g} center",
            f"set pan spread -15 {top:g} edges",
            f"set pan spread -15 {top:g}",
        ]
        assert not any(button.reverse for button in fan.curves.values())

    drive(app, body)


def test_with_nothing_held_a_spread_starts_from_the_output_or_flat(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club)
    outs = (ElementOutput(101, 1, 0.0, None, 10.0, None, None),
            ElementOutput(102, 1, 0.0, None, 20.0, None, None))  # fmt: skip

    async def body(pilot: Pilot[int]) -> None:
        fan = await position_fan(pilot, app)
        bridge.events.append(OutputChanged(OutputModel(1, outs)))
        await settle(pilot, app)
        assert [plain(end.value) for end in fan.ends] == ["10°", "20°"]
        assert fan.ends[0].value.content.style == colors.DIM
        assert fan.ends[0].minus.inert
        assert fan.ends[1].plus.inert
        await tap(pilot, fan.curves["center"])  # nothing held: lit, nothing sent
        assert fan.curves["center"].reverse
        await tap(pilot, fan.curves["center"])
        assert fan.reading is not None
        low = fan.reading.span[0]
        await pilot.click(fan.bars[0], offset=(0, 0))
        await pilot.pause()
        await tap_label(pilot, spread_line(app).chips, "[tilt]")
        await pilot.pause()
        tilt = spread_row(app, "tilt")
        assert [plain(end.value) for end in tilt.ends] == ["—", "—"]
        assert tilt.reading is not None
        await pilot.click(tilt.bars[1], offset=(0, 0))
        await pilot.pause()
        bottom = tilt.reading.span[0]
        assert bridge.lines() == [
            f"set pan spread {low:g} 20",  # the other end: the output's
            f"set tilt spread {bottom:g} {bottom:g}",  # no other end: flat
        ]

    drive(app, body)


def test_the_last_spread_sent_shows_where_the_values_cannot_tell(club: busk.OfflineShow) -> None:
    bridge, app = club_app(club, values=FAN)

    async def body(pilot: Pilot[int]) -> None:
        fan = await position_fan(pilot, app)
        await tap(pilot, fan.curves["center"])
        await pilot.pause()
        assert bridge.lines() == ["set pan spread -30 30 center"]
        both = tuple(HeldValue(n, 1, "pan", -30.0, None) for n in (101, 102))
        bridge.events.append(ProgrammerChanged(programmer(version=2, selection=HEADS, values=both)))
        await settle(pilot, app)
        assert [plain(end.value) for end in fan.ends] == ["-30°", "30°"]  # two: both at from
        moved = tuple(HeldValue(n, 1, "pan", -40.0, None) for n in (101, 102))
        bridge.events.append(
            ProgrammerChanged(programmer(version=3, selection=HEADS, values=moved))
        )
        await settle(pilot, app)
        assert [plain(end.value) for end in fan.ends] == ["-40°", "-40°"]  # changed elsewhere

    drive(app, body)


def test_a_spread_drag_sends_as_it_moves_and_logs_the_last(
    club: busk.OfflineShow, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge, app = club_app(club, values=FAN)

    async def body(pilot: Pilot[int]) -> None:
        fan = await position_fan(pilot, app)
        bar = fan.bars[1]
        monkeypatch.setattr(encoders, "DRAG_S", 0.0)
        await pilot.mouse_down(bar, offset=(2, 0))
        await pilot.hover(bar, offset=(6, 0))
        await pilot.mouse_up(bar, offset=(9, 0))
        lines = sent(bridge)
        assert len(lines) >= 2
        assert {origin for _, origin, _ in lines[:-1]} == {"internal"}
        assert lines[-1][1:] == ("ui", "set:pan")
        assert all(line.startswith("set pan spread -30 ") for line, _, _ in lines)
        logged = [text for kind, text in app.query_one(LogView).entries if kind == "ui"]
        assert logged == [lines[-1][0]]

    drive(app, body)


def test_the_pane_cursor_stops_on_the_spread_toggles_and_rows(club: busk.OfflineShow) -> None:
    _, app = club_app(club, values=FAN)

    async def body(pilot: Pilot[int]) -> None:
        await position_fan(pilot, app)
        labels = [item.label for item in page(app).items()]
        start = labels.index("pan from −")
        assert labels[start : start + 6] == [
            "pan from −", "pan from +", "pan to −", "pan to +", "pan center", "pan edges",
        ]  # fmt: skip
        assert "pan" not in labels  # the plain row is hidden
        assert labels.index("tilt") < labels.index("[pan]") < labels.index("[tilt]")
        item = page(app).items()[labels.index("[tilt]")]
        assert item.action is not None
        item.action()
        await pilot.pause()
        assert spread_row(app, "tilt").display

    drive(app, body)
