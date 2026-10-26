"""F9 Surfaces (spec §8.9, plan Phase 4): MIDI, OSC and web surfaces with
their states, the web remote's address and busk's reasons; bindings of each
input and action kind with the level of what they drive; the edits and the
pane cursor. Headless, with a fake bridge."""

from __future__ import annotations

from typing import Any

from textual.pilot import Pilot
from tui_fakes import (
    FakeBridge,
    click_cell,
    column,
    drive,
    live_state,
    make_app,
    playback,
    settle,
    show_model,
)

from busk_tui import colors
from busk_tui.model import (
    BindingInfo,
    LiveChanged,
    MasterLevel,
    PageInfo,
    PageView,
    ShowChanged,
    ShowModel,
    SurfacesChanged,
    SurfaceView,
)
from busk_tui.pages.surfaces import (
    BindingTable,
    SurfacesPage,
    SurfaceTable,
    binding_level,
    notes_text,
    surface_cells,
)
from busk_tui.shell import BuskApp

NANO = SurfaceView("nanoKONTROL2", "midi", '"nanoKONTROL2"', "soft", "failed",
                   "unplugged; waiting for it", ())  # fmt: skip
TOUCH = SurfaceView("TouchOSC", "osc", "port 8000 feedback 10.0.0.5:9000", "jump", "ok", "", ())
PHONE = SurfaceView("Phone", "web", "port 8080", "jump", "ok", "",
                    ("http://10.0.0.2:8080/?k=abc", "http://192.168.1.4:8080/?k=abc"))  # fmt: skip
PAD = SurfaceView("Pad", "hid", "", "jump", "ignored", "hid surfaces are not implemented", ())
SURFACES = (NANO, TOUCH, PHONE, PAD)

BINDINGS = (
    BindingInfo("nanoKONTROL2", "cc", 1, "0", "fader 1", "", ("slot", 0)),
    BindingInfo("nanoKONTROL2", "cc", 1, "1", "fader 2", "", ("slot", 1)),  # an empty slot
    BindingInfo("nanoKONTROL2", "note", 1, "36", "button 1 1", "led"),
    BindingInfo("nanoKONTROL2", "cc", 1, "16", "fader playback 9", "", ("playback", 9)),
    BindingInfo("nanoKONTROL2", "cc", 1, "23", "master gm", "", ("master", "Grand Master")),
    BindingInfo("nanoKONTROL2", "cc", 1, "22", 'master "FX"', "motor", ("master", "FX")),
    BindingInfo("nanoKONTROL2", "clock", None, "", 'tap "Speed 1"', ""),
    BindingInfo("TouchOSC", "osc", None, "/1/push1", "blackout momentary", "led note 1 40"),
    BindingInfo("TouchOSC", "osc", None, "/1/push2", "release all 2", ""),
    BindingInfo("TouchOSC", "osc", None, "/1/push3", "output off", ""),
    BindingInfo("TouchOSC", "osc", None, "/1/push4", "page +1", ""),
)
LIVE = live_state(
    page=PageView(1, "Main"),
    masters=(MasterLevel("Grand Master", "grand", 0.8), MasterLevel("FX", "size", 0.25)),
    playbacks=(playback(1, "Warm", level=0.72), playback(9, "Song", level=0.5)),
)


def rig(**changes: Any) -> ShowModel:
    parts: dict[str, Any] = {
        "pages": (PageInfo(1, "Main", (1, None)), PageInfo(2, "Song", (9, 1))),
        "bindings": BINDINGS,
    }
    parts.update(changes)
    return show_model(**parts)


def on_f9(bridge: FakeBridge) -> BuskApp:
    bridge.events += [ShowChanged(rig()), LiveChanged(LIVE), SurfacesChanged(SURFACES)]
    return make_app(bridge, page=9)


def test_surface_rows_by_state() -> None:
    cells = [surface_cells(s, n) for s, n in zip(SURFACES, (7, 4, 0, 0), strict=True)]
    rows = [
        tuple(c[name].plain for name in ("light", "name", "kind", "device", "binds", "state"))
        for c in cells
    ]
    assert rows == [
        ("●", "nanoKONTROL2", "midi", '"nanoKONTROL2"', "7", "failed"),
        ("●", "TouchOSC", "osc", "port 8000 feedback 10.0.0.5:9000", "4", "open"),
        ("●", "Phone", "web", "port 8080", "0", "open"),
        ("○", "Pad", "hid", "", "0", "ignored"),
    ]
    assert [str(c["light"].spans[0].style) for c in cells] == [
        colors.RED, colors.GREEN, colors.GREEN, colors.BORDER
    ]  # fmt: skip
    closed = surface_cells(SurfaceView("Phone", "web", "port 8080", "jump", None, "", ()), 0)
    assert closed["state"].plain == "not open"  # --no-surfaces


def test_the_notes_say_why_and_where_the_remote_is() -> None:
    assert notes_text(SURFACES).plain.splitlines() == [
        "nanoKONTROL2  unplugged; waiting for it",
        "Phone  http://10.0.0.2:8080/?k=abc",
        "Phone  http://192.168.1.4:8080/?k=abc",
        "Pad  hid surfaces are not implemented",
    ]


def test_the_level_of_what_a_binding_drives() -> None:
    show = rig()
    levels = [binding_level(b, show, LIVE) for b in BINDINGS]
    assert levels[:6] == [0.72, None, None, 0.5, 0.8, 0.25]
    assert levels[6:] == [None] * 5
    on_page_2 = live_state(page=PageView(2, "Song"), playbacks=LIVE.playbacks)
    assert binding_level(BINDINGS[0], show, on_page_2) == 0.5  # slot 1 is P9 there
    assert binding_level(BINDINGS[0], rig(pages=()), LIVE) is None  # no page: drives nothing


def test_the_page_lists_surfaces_and_bindings() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        assert bridge.watching == (False, False)
        surfaces = app.query_one(SurfaceTable)
        assert column(surfaces, "binds") == ["7", "4", "0", "0"]
        bindings = app.query_one(BindingTable)
        assert column(bindings, "input") == [
            "cc 1 0", "cc 1 1", "note 1 36", "cc 1 16", "cc 1 23", "cc 1 22", "clock",
            'osc "/1/push1"', 'osc "/1/push2"', 'osc "/1/push3"', 'osc "/1/push4"',
        ]  # fmt: skip
        assert column(bindings, "level")[:6] == ["72%", "—", "—", "50%", "80%", "25%"]
        assert column(bindings, "feedback")[7] == "led note 1 40"
        assert str(app.query_one("#bindings-panel").border_title) == "BINDINGS · 11"
        assert "unplugged; waiting for it" in app.query_one(SurfacesPage).notes.content.plain
        bridge.events.append(LiveChanged(live_state(playbacks=(playback(1, "Warm", level=0.3),))))
        await settle(pilot, app)
        assert column(bindings, "level")[0] == "30%"

    drive(app, body)


def test_the_edits_act_on_the_chosen_surface_and_binding() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(SurfacesPage)
        assert [b.prefill for b in page.surface_edits.buttons] == [
            'bind "nanoKONTROL2" ',
            'surface "nanoKONTROL2" pickup ',
        ]
        assert page.binding_edits.buttons == ()  # no binding chosen yet
        await click_cell(pilot, app.query_one(SurfaceTable), 1, "name")
        assert page.surface_edits.buttons[0].prefill == 'bind "TouchOSC" '
        bindings = app.query_one(BindingTable)
        await click_cell(pilot, bindings, 7, "what")
        assert bindings.chosen == 7
        assert [b.prefill for b in page.binding_edits.buttons] == [
            'unbind "TouchOSC" osc "/1/push1"',
            'feedback "TouchOSC" osc "/1/push1" ',
        ]
        await click_cell(pilot, bindings, 6, "what")  # a clock: unbind cannot name it
        assert page.binding_edits.buttons == ()
        assert 'clock on "nanoKONTROL2"' in page.binding_label.content.plain
        assert bridge.sent == []  # choosing runs nothing

    drive(app, body)


def test_the_pane_cursor_stops_on_surfaces_edits_and_bindings() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        labels = [item.label for item in app.current_page.items()]
        assert labels[:6] == [
            "surface nanoKONTROL2", "surface TouchOSC", "surface Phone", "surface Pad",
            'bind "nanoKONTROL2"', 'surface "nanoKONTROL2" pickup',
        ]  # fmt: skip
        assert labels[6] == "binding nanoKONTROL2 cc 1 0 fader 1"
        await pilot.press("tab", *["down"] * 6, "enter")  # chooses the first binding
        page = app.query_one(SurfacesPage)
        assert page.binding == 0
        await pilot.press(*["down"] * 11, "enter")  # its unbind: a whole line to run
        assert app.prompt.value == 'unbind "nanoKONTROL2" cc 1 0'
        assert bridge.sent == []

    drive(app, body)


def test_bindings_go_under_the_surfaces_below_132_columns() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        surfaces, bindings = app.query_one("#surfaces-panel"), app.query_one("#bindings-panel")
        assert bindings.region.x > surfaces.region.x
        await pilot.resize_terminal(120, 40)
        await pilot.pause()
        assert bindings.region.y > surfaces.region.y

    drive(app, body)


def test_nothing_to_show() -> None:
    bridge = FakeBridge()
    bridge.events += [ShowChanged(show_model()), SurfacesChanged(())]
    app = make_app(bridge, page=9)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        assert "no surfaces" in app.query_one(SurfaceTable).render().plain
        assert "no bindings" in app.query_one(BindingTable).render().plain
        assert not app.query_one(SurfacesPage).notes.display

    drive(app, body)
