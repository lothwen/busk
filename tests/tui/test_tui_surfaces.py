"""F9 Surfaces (spec §8.9, plan Phase 4): MIDI, OSC and web surfaces with
their states, the web remote's address and busk's reasons; bindings of each
input and action kind with the level of what they drive; the edits and the
pane cursor. Since the pending plan's Phase 37 (busk's GAP-13): MONITOR, the
last number each control sent, and learn mode. Since Phase 39: surfaces added,
changed, renamed and deleted from controls, and their pickup. Headless, with a
fake bridge."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from rich.text import Text
from textual.pilot import Pilot
from textual.widgets import Input
from tui_fakes import (
    FakeBridge,
    Reply,
    click_cell,
    column,
    drive,
    live_state,
    make_app,
    playback,
    settle,
    show_model,
)

import busk
from busk_tui import colors, commands
from busk_tui.model import (
    BindingInfo,
    InputsChanged,
    InputView,
    LiveChanged,
    MasterLevel,
    MasterView,
    PageInfo,
    PageView,
    ShowChanged,
    ShowModel,
    SurfacesChanged,
    SurfaceView,
)
from busk_tui.pages.surfaces import (
    LEARN_LIT,
    NO_INPUTS,
    NOT_OPEN,
    UNBOUND,
    BindingTable,
    MonitorTable,
    SurfacesPage,
    SurfaceTable,
    binding_level,
    merged,
    monitor_cells,
    notes_text,
    surface_cells,
)
from busk_tui.shell import BuskApp
from busk_tui.widgets.binding_dialog import (
    BindingDialog,
    binding_words,
    control_parts,
    unworded,
    what_words,
)
from busk_tui.widgets.controls import ButtonStrip
from busk_tui.widgets.dialogs import ConfirmDialog, TextDialog
from busk_tui.widgets.options import LIT
from busk_tui.widgets.prompt import HintRow
from busk_tui.widgets.surface_dialog import (
    NO_DEVICES,
    SurfaceDialog,
    check_feedback,
    check_port,
    check_surface_name,
    finders,
    found_by,
)

NANO = SurfaceView("nanoKONTROL2", "midi", '"nanoKONTROL2"', "soft", "failed",
                   "unplugged; waiting for it", (), midi="nanoKONTROL2")  # fmt: skip
TOUCH = SurfaceView("TouchOSC", "osc", "port 8000 feedback 10.0.0.5:9000", "jump", "ok", "", (),
                    port=8000, host="10.0.0.5", feedback_port=9000)  # fmt: skip
PHONE = SurfaceView("Phone", "web", "port 8080", "jump", "ok", "",
                    ("http://10.0.0.2:8080/?k=abc", "http://192.168.1.4:8080/?k=abc"),
                    port=8080)  # fmt: skip
PAD = SurfaceView("Pad", "hid", "", "jump", "ignored", "hid surfaces are not implemented", ())
SURFACES = (NANO, TOUCH, PHONE, PAD)

BINDINGS = (
    BindingInfo("nanoKONTROL2", "cc", 1, "0", "fader 1", "", ("slot", 0),
                id="b-1", action="fader", values=("slot", "1")),
    BindingInfo("nanoKONTROL2", "cc", 1, "1", "fader 2", "", ("slot", 1),  # an empty slot
                id="b-2", action="fader", values=("slot", "2")),
    BindingInfo("nanoKONTROL2", "note", 1, "36", "button 1 1", "led",
                id="b-3", action="button", values=("1", "1"), feedback_kind="led"),
    BindingInfo("nanoKONTROL2", "cc", 1, "16", "fader playback 9", "", ("playback", 9),
                id="b-4", action="fader", values=("playback", "9")),
    BindingInfo("nanoKONTROL2", "cc", 1, "23", "master gm", "", ("master", "Grand Master"),
                id="b-5", action="master", values=("Grand Master",)),
    BindingInfo("nanoKONTROL2", "cc", 1, "22", 'master "FX"', "motor", ("master", "FX"),
                id="b-6", action="master", values=("FX",), feedback_kind="motor"),
    BindingInfo("nanoKONTROL2", "clock", None, "", 'tap "Speed 1"', "",
                id="b-7", action="tap", values=("Speed 1",)),
    BindingInfo("TouchOSC", "osc", None, "/1/push1", "blackout momentary", "led note 1 40",
                id="b-8", action="blackout", values=("momentary",), feedback_kind="led",
                feedback_to=("note", 1, "40")),  # a note on OSC, from a show file
    BindingInfo("TouchOSC", "osc", None, "/1/push2", "release all 2", "",
                id="b-9", action="release all", values=("2",)),
    BindingInfo("TouchOSC", "osc", None, "/1/push3", "output off", "",
                id="b-10", action="output", values=("off",)),
    BindingInfo("TouchOSC", "osc", None, "/1/push4", "page +1", "",
                id="b-11", action="page", values=("+1",)),
)  # fmt: skip
MASTERS = (
    MasterView("Grand Master", "grand", None, ()),
    MasterView("FX", "size", None, ()),
    MasterView("Speed 1", "speed", None, (0.5, 1, 2)),
    MasterView("Speed 2", "speed", None, (0.5, 1, 2)),
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
        "masters": MASTERS,
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
        assert [b.prefill for b in page.surface_edits.buttons if b.prefill] == []  # none since 41
        assert page.binding_edits.buttons == ()  # no binding chosen yet
        await click_cell(pilot, app.query_one(SurfaceTable), 1, "name")
        assert labels(page.surface_edits)[-2:] == ["[+ binding…]", "[learn]"]
        bindings = app.query_one(BindingTable)
        await click_cell(pilot, bindings, 9, "what")
        assert bindings.chosen == 9
        assert labels(page.binding_edits) == ["[edit…]", "[learn]", "[delete]"]
        assert not any(button.note for button in page.binding_edits.buttons)
        await click_cell(pilot, bindings, 6, "what")  # a clock's: the form words it now
        assert labels(page.binding_edits) == ["[edit…]", "[learn]", "[delete]"]
        assert 'clock on "nanoKONTROL2"' in page.binding_label.content.plain
        assert bridge.sent == []  # choosing runs nothing

    drive(app, body)


def test_the_pane_cursor_stops_on_surfaces_edits_and_bindings() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        labels = [item.label for item in app.current_page.items()]
        assert labels[:4] == [
            "surface nanoKONTROL2", "surface TouchOSC", "surface Phone", "surface Pad"
        ]  # fmt: skip
        assert labels[4:12] == [
            "[+ surface…]", 'surface "nanoKONTROL2" pickup jump',  # soft is lit: no stop
            "[edit…]", "[rename…]", 'delete surface "nanoKONTROL2" cascade',
            "[+ binding…]", "[learn]", "binding nanoKONTROL2 cc 1 0 fader 1",
        ]  # fmt: skip
        await pilot.press("tab", *["down"] * 11, "enter")  # chooses the first binding
        page = app.query_one(SurfacesPage)
        assert page.binding == 0
        assert [item.label for item in app.current_page.items()][-3:] == [
            "[edit…]", "[learn]", "[delete]"
        ]  # fmt: skip
        await pilot.press(*["down"] * 13, "enter")  # its [delete]: the TUI asks first
        assert isinstance(app.screen, ConfirmDialog)
        await pilot.press("n")
        await settle(pilot, app)
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


# ------------------------------------------------------------------ MONITOR


def heard(seq: int, control: str, raw: int | None, *drives: str, on: str = "TouchOSC") -> InputView:
    value = 0.5 if raw is None else raw / 127
    return InputView(seq, on, control, raw, value, drives)


def text(widget: Any) -> str:
    rendered = widget.render()
    return rendered.plain if isinstance(rendered, Text) else str(rendered)


async def click_learn(pilot: Pilot[int], strip: ButtonStrip) -> None:
    lines = [line.plain for line in strip.lines(strip.size.width)]
    y = next(y for y, line in enumerate(lines) if "[learn]" in line)
    await pilot.click(strip, offset=(lines[y].index("[learn]") + 1, y))
    await pilot.pause()


def learn_style(page: SurfacesPage) -> str:
    button = page.surface_edits.buttons[-1]
    assert button.label.plain == "[learn]"
    return str(button.label.spans[0].style)


def test_inputs_in_a_row_from_one_control_make_one_line() -> None:
    first = merged((), [heard(1, "cc 1 0", 10), heard(2, "cc 1 0", 20), heard(3, "cc 1 1", 5)])
    assert [(h.seq, h.input) for h in first] == [(2, "cc 1 0"), (3, "cc 1 1")]
    turns = merged(first, [heard(4, "cc 1 0", 30), heard(5, "cc 1 0", 31), heard(6, "cc 1 1", 6)])
    assert [(h.seq, h.input) for h in turns] == [
        (2, "cc 1 0"), (3, "cc 1 1"), (5, "cc 1 0"), (6, "cc 1 1")
    ]  # fmt: skip
    other = merged((), [heard(1, "cc 1 0", 1), heard(2, "cc 1 0", 2, on="nanoKONTROL2")])
    assert len(other) == 2  # the same numbers on another surface: another control
    many = merged((), [heard(n, f"cc 1 {n % 2}", n) for n in range(1, 31)])
    assert [h.seq for h in many] == list(range(17, 31))  # the newest 14


def test_a_monitor_line_says_what_came_and_what_it_drives() -> None:
    bound = monitor_cells(heard(1, "cc 1 48", 102, "fader 1", on="APC mini mk2"))
    assert [bound[name].plain for name in ("input", "sent", "drives", "surface")] == [
        "cc 1 48", "102", "→ fader 1", "APC mini mk2"
    ]  # fmt: skip
    assert str(bound["drives"].spans[0].style) == colors.AMBER
    unbound = monitor_cells(heard(2, 'osc "/x"', None))
    assert (unbound["sent"].plain, unbound["drives"].plain) == ("0.50", "→ —")
    assert str(unbound["drives"].spans[0].style) == colors.DIM
    two = monitor_cells(heard(3, "bend 1", -8192, "fader 1", "blackout"))
    assert (two["sent"].plain, two["drives"].plain) == ("-8192", "→ fader 1, blackout")


def test_monitor_and_the_in_column_follow_what_comes_in() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        assert bridge.watching_inputs
        monitor, bindings = app.query_one(MonitorTable), app.query_one(BindingTable)
        assert NO_INPUTS in text(monitor)  # TouchOSC is open
        assert str(app.query_one("#monitor-panel").border_title) == "MONITOR"
        assert column(bindings, "sent")[:2] == ["—", "—"]
        log = (
            heard(1, "cc 1 0", 64, "fader 1", on="nanoKONTROL2"),
            heard(2, "cc 1 0", 100, "fader 1", on="nanoKONTROL2"),
            heard(3, 'osc "/1/push2"', None, "release all 2"),
            heard(4, "cc 2 9", 7, on="nanoKONTROL2"),
        )
        bridge.events.append(InputsChanged(log[:3]))
        await settle(pilot, app)
        assert column(monitor, "input") == ["cc 1 0", 'osc "/1/push2"']
        assert column(monitor, "sent") == ["100", "0.50"]
        assert column(bindings, "sent")[0] == "100"  # in: what the fader sent
        assert column(bindings, "level")[0] == "72%"  # val: the level of what it drives
        assert column(bindings, "sent")[8] == "0.50"
        bridge.events.append(InputsChanged(log[1:]))  # busk's newest: the first one gone
        await settle(pilot, app)
        assert column(monitor, "input") == ["cc 1 0", 'osc "/1/push2"', "cc 2 9"]
        assert column(monitor, "drives")[2] == "→ —"
        app.action_page(1)
        await settle(pilot, app)
        assert not bridge.watching_inputs  # read only while F9 shows
        app.action_page(9)
        await settle(pilot, app)
        assert bridge.watching_inputs
        assert column(monitor, "input") == ["cc 1 0", 'osc "/1/push2"', "cc 2 9"]  # kept

    drive(app, body)


def test_with_no_surface_open_monitor_says_so() -> None:
    bridge = FakeBridge()
    bridge.events += [ShowChanged(rig()), SurfacesChanged((NANO, PAD))]
    app = make_app(bridge, page=9)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        assert NOT_OPEN in text(app.query_one(MonitorTable))

    drive(app, body)


def test_learn_mode_puts_the_next_control_of_the_surface_in_the_prompt() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        before = heard(1, 'osc "/1/push1"', None, "blackout momentary")
        bridge.events.append(InputsChanged((before,)))  # came before learn mode
        await settle(pilot, app)
        page = app.query_one(SurfacesPage)
        await click_cell(pilot, app.query_one(SurfaceTable), 1, "name")  # TouchOSC
        assert learn_style(page) == colors.MID
        await click_learn(pilot, page.surface_edits)
        assert page.learning
        assert learn_style(page) == LEARN_LIT
        others = (
            heard(2, "cc 1 5", 3, on="nanoKONTROL2"),  # another surface
            heard(3, "bend 1", 100),  # bind cannot take it
            heard(4, "clock", None),  # comes on its own
        )
        bridge.events.append(InputsChanged((before, *others)))  # busk's log: the old one too
        await settle(pilot, app)
        assert page.learning
        assert app.prompt.value == ""
        bridge.events.append(InputsChanged((*others, heard(5, 'osc "/2/fader3"', None))))
        await settle(pilot, app)
        assert app.prompt.value == 'bind "TouchOSC" osc "/2/fader3" '
        assert "unbind it" not in text(app.query_one(HintRow))  # it drives nothing yet
        assert not page.learning
        assert learn_style(page) == colors.MID
        assert bridge.sent == []  # nothing is sent until the operator sends the line
        bridge.events.append(InputsChanged((heard(6, 'osc "/2/fader4"', None),)))
        await settle(pilot, app)
        assert app.prompt.value == 'bind "TouchOSC" osc "/2/fader3" '  # disarmed

    drive(app, body)


def test_learning_a_bound_control_says_what_it_drives() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(SurfacesPage)
        await click_learn(pilot, page.surface_edits)  # on nanoKONTROL2, the first
        bridge.events.append(InputsChanged((heard(1, "cc 1 0", 90, "fader 1", on="nanoKONTROL2"),)))
        await settle(pilot, app)
        assert app.prompt.value == 'bind "nanoKONTROL2" cc 1 0 '
        hint = app.query_one(HintRow)
        assert text(hint) == "cc 1 0 drives fader 1: unbind it to replace it"
        await pilot.press("f")
        await pilot.pause()
        assert text(hint) != "cc 1 0 drives fader 1: unbind it to replace it"  # typed on
        await pilot.press("backspace")  # the pre-fill again: the line has changed since
        await pilot.pause()
        assert app.prompt.value == 'bind "nanoKONTROL2" cc 1 0 '
        assert text(hint) != "cc 1 0 drives fader 1: unbind it to replace it"

    drive(app, body)


def test_esc_a_second_click_another_surface_or_page_disarm_learn_mode() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(SurfacesPage)
        await click_learn(pilot, page.surface_edits)
        app.prompt.value = "go 1"
        await pilot.press("escape")
        assert not page.learning
        assert app.prompt.value == "go 1"  # Esc disarmed: the prompt stays
        await pilot.press("escape")
        assert app.prompt.value == ""
        await click_learn(pilot, page.surface_edits)
        await click_learn(pilot, page.surface_edits)
        assert not page.learning
        await click_learn(pilot, page.surface_edits)
        await click_cell(pilot, app.query_one(SurfaceTable), 1, "name")
        assert not page.learning
        await click_learn(pilot, page.surface_edits)
        app.action_page(1)
        await pilot.pause()
        assert not page.learning
        app.action_page(9)
        await settle(pilot, app)
        bridge.events.append(InputsChanged((heard(1, 'osc "/1/push1"', None),)))
        await settle(pilot, app)
        assert app.prompt.value == ""

    drive(app, body)


def test_monitor_comes_between_surfaces_and_bindings() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        surfaces, monitor, bindings = (
            app.query_one(f"#{name}-panel") for name in ("surfaces", "monitor", "bindings")
        )
        assert monitor.region.x == surfaces.region.x
        assert monitor.region.y > surfaces.region.y
        assert bindings.region.x > monitor.region.right - 1  # beside them
        await pilot.resize_terminal(99, 40)
        await pilot.pause()
        assert surfaces.region.y < monitor.region.y < bindings.region.y
        assert monitor.region.width == bindings.region.width
        bridge.events.append(
            InputsChanged((heard(1, "cc 1 48", 102, "fader 1", on="APC mini mk2"),))
        )
        await settle(pilot, app)
        line = app.query_one(MonitorTable).line(1, app.query_one(MonitorTable).size.width).plain
        assert line.split() == ["cc", "1", "48", "102", "→", "fader", "1", "APC", "mini", "mk2"]

    drive(app, body)


# ------------------------------------------------- surfaces set up (Phase 39)


async def tap(pilot: Pilot[int], strip: ButtonStrip, label: str) -> None:
    """A click on the button ``label`` (``[edit…]``) of ``strip``."""
    lines = [line.plain for line in strip.lines(strip.size.width)]
    y = next(y for y, line in enumerate(lines) if label in line)
    await pilot.click(strip, offset=(lines[y].index(label) + 1, y))
    await pilot.pause()


def labels(strip: ButtonStrip) -> list[str]:
    return [button.label.plain for button in strip.buttons]


def form(app: BuskApp) -> SurfaceDialog:
    dialog = app.screen
    assert isinstance(dialog, SurfaceDialog)
    return dialog


async def open_form(pilot: Pilot[int], app: BuskApp, label: str = "[+ surface…]") -> SurfaceDialog:
    """The form, from ``label`` of the chosen surface's strip, its devices read."""
    await tap(pilot, app.query_one(SurfacesPage).surface_edits, label)
    dialog = form(app)
    if dialog.kind.chosen == "midi":
        await until_read(pilot, dialog)
    return dialog


async def until_read(pilot: Pilot[int], dialog: SurfaceDialog) -> None:
    for _ in range(100):  # the bridge is asked on a worker thread
        if dialog.chips.devices is not None:
            return
        await pilot.pause(0.01)
    raise AssertionError("the devices were never read")


def test_the_chosen_surfaces_strip_by_kind() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await pilot.resize_terminal(99, 40)
        await settle(pilot, app)
        page = app.query_one(SurfacesPage)
        strip = page.surface_edits
        assert labels(strip) == [
            "[+ surface…]", '"nanoKONTROL2"', "[soft]", "[jump]", "[edit…]", "[rename…]",
            "[delete]", "[+ binding…]", "[learn]",
        ]  # fmt: skip
        assert len(strip.lines(strip.size.width)) == 1  # one line at 99 columns
        soft, jump, delete = strip.buttons[2], strip.buttons[3], strip.buttons[6]
        assert soft.note  # its own, lit: a click would change nothing
        assert jump.line.text == 'surface "nanoKONTROL2" pickup jump'
        assert delete.line.text == 'delete surface "nanoKONTROL2" cascade'
        page.choose_surface("TouchOSC")
        assert strip.buttons[2].line.text == 'surface "TouchOSC" pickup soft'
        assert strip.buttons[3].note  # jump
        page.choose_surface("Pad")  # hid: busk does not open it
        assert labels(strip) == ["[+ surface…]", '"Pad"', "[rename…]", "[delete]", "[+ binding…]"]
        assert strip.buttons[-1].note  # grey: it takes no binding
        page.choose_surface("Phone")  # a web remote sends commands of its own: no [learn]
        assert labels(strip)[-2:] == ["[delete]", "[+ binding…]"]
        assert strip.buttons[-1].note
        bridge.events.append(SurfacesChanged(()))
        await settle(pilot, app)
        assert labels(strip) == ["[+ surface…]"]
        assert "[+ surface…]" in text(app.query_one(SurfaceTable))

    drive(app, body)


def test_a_pickup_chip_sends_its_line_and_the_lit_one_nothing() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        strip = app.query_one(SurfacesPage).surface_edits
        await tap(pilot, strip, "[soft]")
        assert bridge.sent == []
        await tap(pilot, strip, "[jump]")
        assert bridge.lines() == ['surface "nanoKONTROL2" pickup jump']

    drive(app, body)


def test_delete_asks_busks_question_counting_the_bindings(club: busk.OfflineShow) -> None:
    bridge = FakeBridge(show=club)  # busk's own question
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        strip = app.query_one(SurfacesPage).surface_edits
        await tap(pilot, strip, "[delete]")
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)
        assert dialog.question == 'Delete surface "nanoKONTROL2"? It leaves 51 bindings.'
        await pilot.press("n")
        await settle(pilot, app)
        assert bridge.sent == []
        app.query_one(SurfacesPage).choose_surface("Phone")  # none: busk asks all the same
        await tap(pilot, strip, "[delete]")
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)
        assert dialog.question == 'Delete surface "Phone"?'
        await pilot.press("y")
        await settle(pilot, app)
        assert bridge.lines() == ['delete surface "Phone" cascade']

    drive(app, body)


def test_rename_sends_the_new_name_and_the_choice_follows() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(SurfacesPage)
        page.choose_surface("TouchOSC")
        await tap(pilot, page.surface_edits, "[rename…]")
        dialog = app.screen
        assert isinstance(dialog, TextDialog)
        field = dialog.query_one(Input)
        assert field.value == "TouchOSC"
        await pilot.press("enter")  # the name it has: nothing
        await settle(pilot, app)
        assert bridge.sent == []
        await tap(pilot, page.surface_edits, "[rename…]")
        field = app.screen.query_one(Input)
        field.value = "phone"  # another's, in another case
        await pilot.press("enter")
        assert 'a surface named "phone" exists' in text(app.screen.query_one(".error"))
        bridge.replies['rename surface "TouchOSC" "Desk"'] = Reply(ok=False, text="error: …")
        field.value = "Desk"
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.lines() == ['rename surface "TouchOSC" "Desk"']
        assert page.surface == "TouchOSC"  # busk refused it: the choice stays
        del bridge.replies['rename surface "TouchOSC" "Desk"']
        await tap(pilot, page.surface_edits, "[rename…]")
        app.screen.query_one(Input).value = "Desk"
        await pilot.press("enter")
        await settle(pilot, app)
        assert page.surface == "Desk"  # once busk has it, it is the chosen one

    drive(app, body)


def test_a_new_midi_surface_from_the_devices_plugged_in() -> None:
    bridge = FakeBridge(devices=("nanoKONTROL2", "APC mini mk2"))
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        dialog = await open_form(pilot, app)
        assert str(dialog.title_text) == "NEW SURFACE"
        assert dialog.kind.chosen == "midi"
        assert labels(dialog.chips) == ["[nanoKONTROL2 · in use]", "[APC mini mk2]"]
        assert str(dialog.chips.buttons[0].label.spans[0].style) == colors.DIM
        await pilot.press("enter")
        assert text(dialog.error) == "a device, such as nanoKONTROL2"
        await tap(pilot, dialog.chips, "[nanoKONTROL2")
        assert dialog.device.value == "nanoKONTROL2"
        assert dialog.found_note.display
        assert text(dialog.found_note) == 'surface "nanoKONTROL2" finds it already'
        await pilot.press("enter")
        assert text(dialog.error) == 'a surface named "nanoKONTROL2" exists'
        await tap(pilot, dialog.chips, "[APC mini mk2]")
        assert dialog.device.value == "APC mini mk2"
        assert str(dialog.chips.buttons[1].label.spans[0].style) == LIT  # the one it holds
        assert not dialog.found_note.display
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.lines() == ['surface add midi "APC mini mk2"']
        assert app.query_one(SurfacesPage).surface == "APC mini mk2"  # chosen once busk has it

    drive(app, body)


def test_a_device_not_plugged_in_is_typed() -> None:
    bridge = FakeBridge()  # no device plugged in
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        dialog = await open_form(pilot, app)
        assert labels(dialog.chips) == [NO_DEVICES]
        dialog.device.focus()
        await pilot.press(*"X-Touch", "enter")
        await settle(pilot, app)
        assert bridge.lines() == ['surface add midi "X-Touch"']

    drive(app, body)


def test_a_new_osc_and_web_surface_and_what_the_form_refuses() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        dialog = await open_form(pilot, app)
        await pilot.press("right")  # the kind's chips have the keyboard
        assert dialog.kind.chosen == "osc"
        assert not dialog.midi.display
        assert dialog.ports["osc"].value == "8000"
        await pilot.press("enter")
        assert text(dialog.error) == "a name cannot be empty"
        dialog.name_field.value = "Touch 2"
        await pilot.press("enter")
        assert text(dialog.error) == 'port 8000 is in use by surface "TouchOSC"'
        dialog.ports["osc"].value = "70000"
        await pilot.press("enter")
        assert text(dialog.error) == "a port from 1 to 65535"
        dialog.ports["osc"].value = "9000"
        dialog.wheres["osc"].value = ":"
        await pilot.press("enter")
        assert text(dialog.error) == "a host, host:port or :port, the port from 1 to 65535"
        dialog.wheres["osc"].value = "10.0.0.2:9001"
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.lines() == ['surface add osc "Touch 2" port 9000 feedback 10.0.0.2:9001']

        dialog = await open_form(pilot, app)
        await pilot.press("left")  # round to web
        assert dialog.kind.chosen == "web"
        assert dialog.ports["web"].value == "8080"
        dialog.name_field.value = "Tablet"
        await pilot.press("enter")
        assert text(dialog.error) == 'port 8080 is in use by surface "Phone"'
        dialog.ports["web"].value = "8000"  # TouchOSC's, but not a web remote's
        dialog.wheres["web"].value = "10.0.0.5"
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.lines()[-1] == 'surface add web "Tablet" port 8000 on 10.0.0.5'

    drive(app, body)


def test_the_keyboard_moves_through_the_kind_the_devices_and_the_fields() -> None:
    bridge = FakeBridge(devices=("nanoKONTROL2", "APC mini mk2"))
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        dialog = await open_form(pilot, app)
        assert dialog.kind.has_focus
        await pilot.press("tab")
        assert dialog.chips.has_focus
        await pilot.press("right")
        assert dialog.device.value == "nanoKONTROL2"
        await pilot.press("right")
        assert dialog.device.value == "APC mini mk2"
        await pilot.press("right")  # round to the first
        assert dialog.device.value == "nanoKONTROL2"
        await pilot.press("tab")
        assert dialog.device.has_focus
        await pilot.press("escape")
        await settle(pilot, app)
        assert not isinstance(app.screen, SurfaceDialog)
        assert bridge.sent == []

    drive(app, body)


def test_edit_starts_at_the_surface_and_sends_only_a_change() -> None:
    bridge = FakeBridge(devices=("nanoKONTROL2", "APC mini mk2"))
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(SurfacesPage)
        page.choose_surface("TouchOSC")
        dialog = await open_form(pilot, app, "[edit…]")
        assert str(dialog.title_text) == 'EDIT SURFACE "TouchOSC" · OSC'
        assert not dialog.kind_row.is_attached  # its kind stays
        assert not dialog.name_row.is_attached  # [rename…] renames it
        assert (dialog.ports["osc"].value, dialog.wheres["osc"].value) == ("8000", "10.0.0.5:9000")
        assert dialog.ports["osc"].has_focus
        await pilot.press("enter")  # as it is: nothing
        await settle(pilot, app)
        assert bridge.sent == []
        dialog = await open_form(pilot, app, "[edit…]")
        dialog.ports["osc"].value = "8080"  # the web remote's: another kind
        dialog.wheres["osc"].value = ""
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.lines() == ['surface "TouchOSC" change port 8080']

        page.choose_surface("nanoKONTROL2")
        dialog = await open_form(pilot, app, "[edit…]")
        assert dialog.device.value == "nanoKONTROL2"
        assert dialog.device.has_focus
        assert labels(dialog.chips) == ["[nanoKONTROL2]", "[APC mini mk2]"]  # its own: not in use
        dialog.device.value = "Phone"  # another's name: busk finds a surface by name first
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.lines()[-1] == 'surface "nanoKONTROL2" change "Phone"'
        dialog = await open_form(pilot, app, "[edit…]")
        await tap(pilot, dialog.chips, "[APC mini mk2]")
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.lines()[-1] == 'surface "nanoKONTROL2" change "APC mini mk2"'

        page.choose_surface("Phone")
        dialog = await open_form(pilot, app, "[edit…]")
        assert (dialog.ports["web"].value, dialog.wheres["web"].value) == ("8080", "")
        dialog.wheres["web"].value = "127.0.0.1"
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.lines()[-1] == 'surface "Phone" change port 8080 on 127.0.0.1'

    drive(app, body)


def test_the_forms_checks() -> None:
    names = check_surface_name(["Touch", "nanoKONTROL2"], "Touch")
    assert names("touch") is None  # its own, in another case
    assert names("NANOkontrol2") == 'a surface named "NANOkontrol2" exists'
    assert names("  ") == "a name cannot be empty"
    ports = check_port(SURFACES, "osc", None)
    assert [ports(t) for t in ("1", "65535", " 9000 ", "08001")] == [None] * 4
    assert {ports(t) for t in ("0", "65536", "-1", "+9", "1.5", "", "²")} == {
        "a port from 1 to 65535"
    }
    assert ports("8000") == 'port 8000 is in use by surface "TouchOSC"'
    assert check_port(SURFACES, "osc", "TouchOSC")("8000") is None
    ok = ("", "10.0.0.2", "10.0.0.2:9001", ":9001", "host:", "fe80::1")
    assert [check_feedback(t) for t in ok] == [None] * len(ok)
    assert all(check_feedback(t) for t in (":", "host:0", "host:65536", "host:x", ":-1"))
    found = finders(SURFACES, None)
    assert found == {"nanokontrol2": "nanoKONTROL2"}
    assert found_by("NANOKONTROL2 MIDI 1", found) == "nanoKONTROL2"  # busk finds it in the name
    assert found_by("APC mini mk2", found) is None
    assert finders(SURFACES, "nanoKONTROL2") == {}


# ------------------------------------------------- bindings set up (Phase 41)


def binding_form(app: BuskApp) -> BindingDialog:
    dialog = app.screen
    assert isinstance(dialog, BindingDialog)
    return dialog


async def open_binding_form(pilot: Pilot[int], app: BuskApp, edit: bool = False) -> BindingDialog:
    """The binding form, from the chosen surface's ``[+ binding…]`` or the
    chosen binding's ``[edit…]``."""
    page = app.query_one(SurfacesPage)
    await pilot.pause()  # a binding just chosen: its strip laid out
    if edit:
        await tap(pilot, page.binding_edits, "[edit…]")
    else:
        await tap(pilot, page.surface_edits, "[+ binding…]")
    return binding_form(app)


async def sent(pilot: Pilot[int], app: BuskApp, bridge: FakeBridge) -> str:
    """Enter on the form, and the line it ran."""
    await pilot.press("enter")
    await settle(pilot, app)
    assert not isinstance(app.screen, BindingDialog)
    return bridge.lines()[-1]


def test_a_new_binding_drives_each_kind_of_target() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        dialog = await open_binding_form(pilot, app)
        assert str(dialog.title_text) == 'NEW BINDING · "nanoKONTROL2" · MIDI'
        assert dialog.control.has_focus  # the control's chips first
        assert labels(dialog.action) == [
            "[fader]", "[button]", "[master]", "[tap]", "[blackout]", "[page]", "[release all]",
            "[output]",
        ]  # fmt: skip
        assert labels(dialog.feedback) == ["[none]", "[led]", "[motor]"]  # MIDI has no display
        assert await sent(pilot, app, bridge) == 'bind "nanoKONTROL2" cc 1 0 fader 1'

        async def made(choose: Any) -> str:
            dialog = await open_binding_form(pilot, app)
            choose(dialog)
            await pilot.pause()
            return await sent(pilot, app, bridge)

        def fader_playback(dialog: BindingDialog) -> None:
            dialog.number.value = "07"  # sent as busk stores it
            dialog.action.pick("fader")
            dialog.fader_of.pick("playback")
            dialog.fader.value = "18"
            dialog.feedback.pick("motor")

        assert await made(fader_playback) == ('bind "nanoKONTROL2" cc 1 7 fader playback 18 motor')

        def button_led_elsewhere(dialog: BindingDialog) -> None:
            dialog.control.pick("note")
            dialog.channel.value, dialog.number.value = "2", "60"
            dialog.action.pick("button")
            dialog.slot.value, dialog.button.value = "3", "2"
            dialog.feedback.pick("led")
            dialog.where.pick("other")
            dialog.to_control.pick("note")
            dialog.to_channel.value, dialog.to_number.value = "2", "61"

        assert await made(button_led_elsewhere) == (
            'bind "nanoKONTROL2" note 2 60 button 3 2 led note 2 61'
        )
        masters = [
            ("Grand Master", "master gm"), ("FX", 'master "FX"'), ("Speed 2", 'master "Speed 2"')
        ]  # fmt: skip
        for name, words in masters:

            def master(dialog: BindingDialog, name: str = name) -> None:
                dialog.action.pick("master")
                assert dialog.master is not None
                assert labels(dialog.master) == ["[gm]", "[FX]", "[Speed 1]", "[Speed 2]"]
                dialog.master.pick(name)

            assert await made(master) == f'bind "nanoKONTROL2" cc 1 0 {words}'
        others: list[tuple[str, str, str]] = [
            ("tap", "", 'tap "Speed 1"'),  # two speed masters: named
            ("blackout", "momentary", "blackout momentary"),
            ("blackout", "toggle", "blackout"),
            ("page", "-1", "page -1"),
            ("page", "+01", "page +1"),
            ("page", "2", "page 2"),
            ("release all", "", "release all"),
            ("release all", "2.50", "release all 2.5"),
            ("output", "off", "output off"),
        ]
        for action, value, words in others:

            def other(dialog: BindingDialog, action: str = action, value: str = value) -> None:
                dialog.action.pick(action)
                if action == "blackout":
                    dialog.blackout.pick(value)
                elif action == "page":
                    dialog.page.value = value
                elif action == "release all":
                    dialog.release.value = value
                elif action == "output":
                    dialog.output.pick(value)

            assert await made(other) == f'bind "nanoKONTROL2" cc 1 0 {words}'

    drive(app, body)


def test_a_clock_taps_and_its_feedback_lights_another_control() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        dialog = await open_binding_form(pilot, app)
        await pilot.press("right", "right")  # the control's chips: clock
        assert dialog.control.chosen == "clock"
        assert not dialog.numbered.display  # no channel, no number
        assert not dialog.action_row.display
        assert dialog.taps_row.display  # a clock only taps
        assert dialog.speed is not None
        dialog.speed.pick("Speed 2")
        dialog.feedback.pick("led")
        await pilot.pause()
        assert not dialog.where_row.display  # a clock has no address of its own
        assert dialog.to_rows.display
        dialog.to_number.value = "46"
        assert (
            await sent(pilot, app, bridge) == 'bind "nanoKONTROL2" clock tap "Speed 2" led cc 1 46'
        )

    drive(app, body)


def test_a_show_without_speed_masters_offers_no_clock_or_tap() -> None:
    bridge = FakeBridge()
    bridge.events += [
        ShowChanged(rig(masters=MASTERS[:1])),  # the grand master alone
        SurfacesChanged(SURFACES),
    ]
    app = make_app(bridge, page=9)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        dialog = await open_binding_form(pilot, app)
        assert labels(dialog.control) == ["[cc]", "[note]"]
        assert "[tap]" not in labels(dialog.action)
        dialog.action.pick("master")
        assert dialog.master is not None
        assert labels(dialog.master) == ["[gm]"]

    drive(app, body)


def test_an_osc_binding_has_a_path_and_display_feedback() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        app.query_one(SurfacesPage).choose_surface("TouchOSC")
        dialog = await open_binding_form(pilot, app)
        assert str(dialog.title_text) == 'NEW BINDING · "TouchOSC" · OSC'
        assert not dialog.midi_rows.display
        assert dialog.path.has_focus
        assert labels(dialog.feedback) == ["[none]", "[led]", "[motor]", "[display]"]
        await pilot.press("enter")
        assert text(dialog.error) == "an OSC path, such as /fader/1"
        dialog.path.value = "fader/1"
        await pilot.press("enter")
        assert text(dialog.error) == "an OSC path, such as /fader/1"
        dialog.path.value = "/fader/1"
        dialog.feedback.pick("display")
        dialog.where.pick("other")
        await pilot.press("enter")
        assert text(dialog.error) == "an OSC path, such as /fader/1"  # the display's
        dialog.to_path.value = '/label "1"'
        assert await sent(pilot, app, bridge) == (
            r'bind "TouchOSC" osc "/fader/1" fader 1 display osc "/label \"1\""'
        )

    drive(app, body)


def test_the_form_says_what_is_wrong_first_to_last() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        dialog = await open_binding_form(pilot, app)
        wrong = [
            (dialog.channel, "17", "a MIDI channel from 1 to 16"),
            (dialog.number, "128", "a CC number from 0 to 127"),
            (dialog.fader, "0", "a slot from 1"),
        ]
        for field, value, _ in wrong:
            field.value = value
        for field, _, problem in wrong:
            await pilot.press("enter")
            assert text(dialog.error) == problem
            field.value = "1"
        dialog.action.pick("page")
        dialog.page.value = "next"
        await pilot.press("enter")
        assert text(dialog.error) == "+1, -1 or a page number"
        dialog.action.pick("release all")
        await pilot.pause()
        assert text(dialog.error) == ""  # it was of a field that went
        dialog.release.value = "-2"
        await pilot.press("enter")
        assert text(dialog.error) == "a time in seconds, such as 2 or 0.5"
        await pilot.press("escape")
        await settle(pilot, app)
        assert bridge.sent == []

    drive(app, body)


def test_edit_starts_at_the_binding_and_sends_only_a_change() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(SurfacesPage)
        for row in (0, 2, 3, 4, 5, 6, 8, 9, 10):  # 7 is from a show file: no [edit…]
            page.choose_binding(row)
            dialog = await open_binding_form(pilot, app, edit=True)
            binding = BINDINGS[row]
            assert dialog.held == commands.binding_change(
                binding.id, binding_words(binding, MASTERS)
            )
            await pilot.press("enter")  # as it is: nothing
            await settle(pilot, app)
        assert bridge.sent == []

        page.choose_binding(4)  # cc 1 23 master gm
        dialog = await open_binding_form(pilot, app, edit=True)
        assert str(dialog.title_text) == 'EDIT BINDING cc 1 23 · "nanoKONTROL2"'
        assert dialog.number.value == "23"
        assert dialog.master is not None
        assert dialog.master.chosen == "Grand Master"
        dialog.master.pick("FX")
        dialog.feedback.pick("motor")
        assert await sent(pilot, app, bridge) == 'binding b-5 change cc 1 23 master "FX" motor'

        page.choose_binding(2)  # note 1 36 button 1 1 led
        dialog = await open_binding_form(pilot, app, edit=True)
        assert (dialog.control.chosen, dialog.feedback.chosen) == ("note", "led")
        assert (dialog.slot.value, dialog.button.value) == ("1", "1")
        dialog.feedback.pick("none")  # a feedback left out goes, as busk's change has it
        assert await sent(pilot, app, bridge) == "binding b-3 change note 1 36 button 1 1"

        page.choose_binding(6)  # the clock's
        dialog = await open_binding_form(pilot, app, edit=True)
        assert dialog.control.chosen == "clock"
        assert dialog.speed is not None
        assert dialog.speed.chosen == "Speed 1"
        dialog.control.pick("cc")
        dialog.number.value = "46"
        await pilot.pause()
        assert dialog.action_row.display
        assert dialog.action.chosen == "tap"
        assert await sent(pilot, app, bridge) == 'binding b-7 change cc 1 46 tap "Speed 1"'

    drive(app, body)


def test_the_forms_learn_fills_the_control_while_it_is_open_over_f9() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(SurfacesPage)
        await click_learn(pilot, page.surface_edits)  # F9's: the form's disarms it
        assert page.learning
        dialog = await open_binding_form(pilot, app)
        assert not page.learning
        assert page.form is dialog
        await tap(pilot, dialog.learn, "[learn]")
        assert dialog.learning
        assert str(dialog.learn.buttons[0].label.spans[0].style) == LEARN_LIT
        assert labels(dialog.learn)[1] == 'move a control on "nanoKONTROL2"…'
        others = (
            heard(1, "cc 1 5", 3, on="TouchOSC"),  # another surface
            heard(2, "bend 1", 100, on="nanoKONTROL2"),  # bind cannot take it
            heard(3, "clock", None, on="nanoKONTROL2"),  # comes on its own
        )
        bridge.events.append(InputsChanged(others))
        await settle(pilot, app)
        assert dialog.learning
        bridge.events.append(
            InputsChanged((heard(4, "note 2 61", 90, "button 1 1", on="nanoKONTROL2"),))
        )
        await settle(pilot, app)
        assert not dialog.learning
        assert (dialog.control.chosen, dialog.channel.value, dialog.number.value) == (
            "note", "2", "61"
        )  # fmt: skip
        assert labels(dialog.learn)[1] == "learned note 2 61 drives button 1 1 already"
        assert app.prompt.value == ""  # the form's: nothing in the prompt
        assert await sent(pilot, app, bridge) == 'bind "nanoKONTROL2" note 2 61 fader 1'
        assert page.form is None

        page.choose_surface("TouchOSC")
        dialog = await open_binding_form(pilot, app)
        await tap(pilot, dialog.learn, "[learn]")
        bridge.events.append(InputsChanged((heard(5, 'osc "/2/fader3"', None),)))
        await settle(pilot, app)
        assert dialog.path.value == "/2/fader3"

    drive(app, body)


def test_a_bindings_learn_moves_it_to_the_next_control() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(SurfacesPage)
        await click_learn(pilot, page.surface_edits)
        page.choose_binding(2)  # note 1 36 button 1 1 led
        await settle(pilot, app)
        await tap(pilot, page.binding_edits, "[learn]")
        assert page.moving
        assert not page.learning  # one learn mode at a time
        assert str(page.binding_edits.buttons[1].label.spans[0].style) == LEARN_LIT
        others = (
            heard(1, "note 1 36", 90, on="nanoKONTROL2"),  # its own control
            heard(2, "cc 1 5", 3, on="TouchOSC"),  # another surface
            heard(3, "bend 1", 100, on="nanoKONTROL2"),
        )
        bridge.events.append(InputsChanged(others))
        await settle(pilot, app)
        assert page.moving
        assert bridge.sent == []
        bridge.events.append(InputsChanged((heard(4, "note 1 37", 90, on="nanoKONTROL2"),)))
        await settle(pilot, app)
        assert bridge.lines() == ["binding b-3 change note 1 37 button 1 1 led"]
        assert not page.moving

        page.choose_binding(7)  # led on note 1 40: a show file's, which [learn] cannot keep
        assert page.binding_edits.buttons[1].note
        page.choose_binding(9)  # osc "/1/push3" output off
        await tap(pilot, page.binding_edits, "[learn]")
        assert page.moving
        await pilot.press("escape")
        assert not page.moving
        await tap(pilot, page.binding_edits, "[learn]")
        page.choose_binding(10)  # another binding disarms it
        assert not page.moving
        await tap(pilot, page.binding_edits, "[learn]")
        await click_learn(pilot, page.surface_edits)  # so does the surface's
        assert (page.learning, page.moving) == (True, False)
        await tap(pilot, page.binding_edits, "[learn]")
        app.action_page(1)  # and another page
        await pilot.pause()
        assert not page.moving
        app.action_page(9)
        await settle(pilot, app)
        bridge.events.append(InputsChanged((heard(5, 'osc "/9"', None),)))
        await settle(pilot, app)
        assert bridge.lines() == ["binding b-3 change note 1 37 button 1 1 led"]

    drive(app, body)


def test_delete_asks_first_and_sends_delete_binding() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(SurfacesPage)
        page.choose_binding(4)
        await pilot.pause()
        await tap(pilot, page.binding_edits, "[delete]")
        await settle(pilot, app)
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)
        assert dialog.question == 'Delete binding cc 1 23 → master gm on "nanoKONTROL2"?'
        await pilot.press("n")
        await settle(pilot, app)
        assert bridge.sent == []
        page.choose_binding(7)  # one the form cannot word goes all the same
        await pilot.pause()
        await tap(pilot, page.binding_edits, "[delete]")
        await settle(pilot, app)
        await pilot.press("y")
        await settle(pilot, app)
        assert bridge.lines() == ["delete binding b-8"]

    drive(app, body)


ODD = (
    BindingInfo("nanoKONTROL2", "bend", 1, "", "fader 3", "", id="b-20",
                action="fader", values=("slot", "3")),
    BindingInfo("Pad", "hw", None, "fader1", "fader 4", "", id="b-21",
                action="fader", values=("slot", "4")),
    BindingInfo("nanoKONTROL2", "cc", 1, "70", "command RECORD", "", id="b-22"),
    BindingInfo("Phone", "cc", 1, "71", "blackout", "", id="b-23",
                action="blackout", values=("toggle",)),
    BindingInfo("nanoKONTROL2", "cc", 1, "72", "blackout", "display", id="b-24",
                action="blackout", values=("toggle",), feedback_kind="display"),
)  # fmt: skip
"""Bindings from a show file that ``bind`` cannot make."""


def test_a_binding_the_form_cannot_word_says_why_under_the_mouse() -> None:
    assert [unworded(b, next(s for s in SURFACES if s.name == b.surface)) for b in ODD] == [
        "nanoKONTROL2 does not send bend 1: [delete] removes it",
        "a binding on a hid surface does nothing: [delete] removes it",
        "bind cannot make command RECORD: [delete] removes it",
        "a binding on a web remote does nothing: [delete] removes it",
        "nanoKONTROL2 has no display: [delete] removes it",
    ]
    assert unworded(BINDINGS[7], TOUCH) == "TouchOSC has no note 1 40: [delete] removes it"
    assert (
        unworded(BINDINGS[0], None) == "a binding on no surface does nothing: [delete] removes it"
    )
    assert [b for b in BINDINGS if unworded(b, NANO if b.surface == NANO.name else TOUCH)] == [
        BINDINGS[7]
    ]
    bridge = FakeBridge()
    bridge.events += [ShowChanged(rig(bindings=ODD)), SurfacesChanged(SURFACES)]
    app = make_app(bridge, page=9)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(SurfacesPage)
        hint = app.query_one(HintRow)
        for row in range(len(ODD)):
            page.choose_binding(row)
            assert labels(page.binding_edits) == ["[edit…]", "[learn]", "[delete]"]
            edit, learn, delete = page.binding_edits.buttons
            assert edit.note
            assert learn.note
            assert not delete.note
        page.choose_binding(0)
        await settle(pilot, app)
        before = text(hint)
        await pilot.hover(page.binding_edits, offset=(1, 0))
        await pilot.pause()
        assert text(hint) == "nanoKONTROL2 does not send bend 1: [delete] removes it"
        await tap(pilot, page.binding_edits, "[edit…]")  # grey: nothing opens
        assert not isinstance(app.screen, BindingDialog)
        await pilot.hover(app.query_one(BindingTable), offset=(1, 1))
        await pilot.pause()
        assert text(hint) == before
        page.choose_surface("Phone")
        await pilot.pause()
        grey = labels(page.surface_edits).index("[+ binding…]")
        lines = [line.plain for line in page.surface_edits.lines(page.surface_edits.size.width)]
        y = next(y for y, line in enumerate(lines) if "[+ binding…]" in line)
        await pilot.hover(page.surface_edits, offset=(lines[y].index("[+ binding…]") + 1, y))
        await pilot.pause()
        assert page.surface_edits.buttons[grey].note
        assert text(hint) == UNBOUND["web"]
        assert bridge.sent == []

    drive(app, body)


def test_the_choice_follows_its_binding_by_id() -> None:
    bridge = FakeBridge()
    app = on_f9(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(SurfacesPage)
        page.choose_binding(4)  # b-5
        moved = replace(BINDINGS[4], number="24")
        bridge.events.append(ShowChanged(rig(bindings=(moved, *BINDINGS[:4], *BINDINGS[5:]))))
        await settle(pilot, app)
        assert page.binding == 0
        assert app.query_one(BindingTable).chosen == 0
        assert 'cc 1 24 on "nanoKONTROL2"' in page.binding_label.content.plain
        await pilot.pause()
        await tap(pilot, page.binding_edits, "[learn]")
        assert page.moving
        bridge.events.append(ShowChanged(rig(bindings=BINDINGS[5:])))  # it went
        await settle(pilot, app)
        assert page.binding is None
        assert page.binding_edits.buttons == ()
        assert not page.moving  # its learn mode went with it
        app.prompt.value = "go 1"
        await pilot.press("escape")  # nothing armed: Esc goes on to the prompt
        assert app.prompt.value == ""

    drive(app, body)


def test_the_binding_strip_follows_surfaces_that_come_after_the_show() -> None:
    """What the form can word depends on the surface's kind: a binding chosen
    before busk said which surfaces there are is redrawn once it does."""
    bridge = FakeBridge()
    bridge.events.append(ShowChanged(rig()))
    app = make_app(bridge, page=9)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        page = app.query_one(SurfacesPage)
        page.choose_binding(0)
        assert page.binding_edits.buttons[0].note  # no surface yet: grey
        bridge.events.append(SurfacesChanged(SURFACES))
        await settle(pilot, app)
        assert labels(page.binding_edits) == ["[edit…]", "[learn]", "[delete]"]
        assert not page.binding_edits.buttons[0].note

    drive(app, body)


def test_the_words_a_binding_is_made_of() -> None:
    assert what_words("fader", ("slot", "3"), MASTERS) == "fader 3"
    assert what_words("fader", ("playback", "18"), MASTERS) == "fader playback 18"
    assert what_words("master", ("Grand Master",), MASTERS) == "master gm"
    assert what_words("master", ('The "A"',), MASTERS) == r'master "The \"A\""'
    assert what_words("tap", ("Speed 1",), MASTERS) == 'tap "Speed 1"'
    assert what_words("tap", ("Speed 1",), MASTERS[:3]) == "tap"  # the only one: unnamed
    assert what_words("release all", ("",), MASTERS) == "release all"
    assert binding_words(BINDINGS[2], MASTERS, "note 1 37") == "note 1 37 button 1 1 led"
    assert binding_words(BINDINGS[7], MASTERS) == 'osc "/1/push1" blackout momentary led note 1 40'
    assert control_parts('osc "/a \\"b\\""') == ("osc", None, '/a "b"')
    assert control_parts("cc 1 48") == ("cc", 1, "48")
    assert control_parts("clock") == ("clock", None, "")
