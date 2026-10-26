"""The command line (spec §6.1, §7, plan step 0.4): typing and running lines,
the log's line types, history, hints and completion, the engine's question,
quitting, Ctrl+C and the pane cursor. Headless, with a fake bridge; with
``show=club``, its help, answers and questions are busk's own."""

from __future__ import annotations

import pytest
from textual import events
from textual.pilot import Pilot
from tui_fakes import FakeBridge, Reply, drive, make_app, settle, show_model

import busk
from busk_tui import colors
from busk_tui.model import EngineNews, FixtureInfo, SessionChanged, SessionState, ShowChanged
from busk_tui.widgets.dialogs import ConfirmDialog, QuitDialog
from busk_tui.widgets.fixturetable import FixtureTable
from busk_tui.widgets.help import HelpOverlay
from busk_tui.widgets.log import LogView, log_line
from busk_tui.widgets.prompt import HintRow, Prompt


def hint_text(app: object) -> str:
    rendered = app.query_one(HintRow).render()  # type: ignore[attr-defined]
    return str(rendered)


async def type_line(pilot: Pilot[int], line: str) -> None:
    for character in line:
        await pilot.press("space" if character == " " else character)


def test_a_typed_line_is_echoed_and_sent() -> None:
    bridge = FakeBridge(replies={"sel group 1": Reply(text="2 targets selected")})
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await type_line(pilot, "sel group 1")
        await pilot.press("enter")
        await settle(pilot, app)
        (sent,) = bridge.sent
        assert (sent.line, sent.origin, sent.key, sent.performance) == (
            "sel group 1",
            "typed",
            None,
            False,
        )
        assert app.query_one(Prompt).value == ""
        entries = list(app.query_one(LogView).entries)[-2:]
        assert entries == [("typed", "sel group 1"), ("result", "2 targets selected")]

    drive(app, body)


def test_an_empty_line_sends_nothing() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        app.prompt.value = "   "  # (Space on an empty prompt is GO)
        await pilot.press("enter")
        assert bridge.sent == []

    drive(app, body)


def test_errors_results_and_news_have_their_types() -> None:
    bridge = FakeBridge(replies={"go 99": Reply(ok=False, text="error: no playback 99\n  more")})
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await type_line(pilot, "go 99")
        await pilot.press("enter")
        bridge.events += [
            EngineNews("info", "sACN r1: U1 → universe 1"),
            EngineNews("warning", "send failed"),
        ]
        await settle(pilot, app)
        entries = list(app.query_one(LogView).entries)[-5:]
        assert entries == [
            ("typed", "go 99"),
            ("error", "no playback 99"),
            ("error", "  more"),
            ("info", "sACN r1: U1 → universe 1"),
            ("warning", "send failed"),
        ]

    drive(app, body)


@pytest.mark.parametrize(
    ("kind", "prefix", "color"),
    [
        ("typed", "busk> ", colors.GREEN),
        ("ui", " ui> ", colors.BORDER),
        ("result", "      ", colors.MID),
        ("error", " ✗ ", colors.RED),
        ("info", " · ", colors.DIM),
        ("warning", " ! ", colors.AMBER),
    ],
)
def test_the_log_line_types(kind: str, prefix: str, color: str) -> None:
    line = log_line(kind, "text")  # type: ignore[arg-type]
    assert line.plain == prefix + "text"
    assert color in str(line.spans[0].style)
    assert log_line("error", "issue", first=False).plain == "   issue"


def test_history_walks_back_and_returns_to_the_draft() -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        prompt = app.query_one(Prompt)
        for line in ("gm 50%", "blackout on", "blackout on"):
            await type_line(pilot, line)
            await pilot.press("enter")
        assert prompt.history == ["gm 50%", "blackout on"]
        await type_line(pilot, "dra")
        await pilot.press("up")
        assert prompt.value == "blackout on"
        await pilot.press("up", "up")
        assert prompt.value == "gm 50%"
        await pilot.press("down")
        assert prompt.value == "blackout on"
        await pilot.press("down")
        assert prompt.value == "dra"
        await pilot.press("down")
        assert prompt.value == "dra"

    drive(app, body)


def test_esc_clears_the_prompt() -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        await type_line(pilot, "gm 5")
        await pilot.press("escape")
        assert app.query_one(Prompt).value == ""

    drive(app, body)


def test_the_global_keys_type_while_a_line_is_typed() -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        await type_line(pilot, "set")
        await pilot.press("question_mark")
        assert app.query_one(Prompt).value == "set?"
        assert not app.query_one(HelpOverlay).is_open
        await pilot.press("f4")  # the F-keys act always
        assert app.page == 4
        assert app.query_one(Prompt).value == "set?"
        await pilot.press("escape", "question_mark")
        assert app.query_one(HelpOverlay).is_open
        assert app.query_one(Prompt).value == ""

    drive(app, body)


def test_the_hint_row_follows_the_line(club: busk.OfflineShow) -> None:
    app = make_app(FakeBridge(show=club))

    async def body(pilot: Pilot[int]) -> None:
        assert hint_text(app).startswith("type a command · help for syntax")
        await type_line(pilot, "blind ")
        assert hint_text(app).startswith("next: off on    clear | blind on|off")
        await pilot.press("escape")
        await type_line(pilot, "fixture 999 ")
        assert hint_text(app).startswith("error: no fixture 999")
        await pilot.press("escape")
        await type_line(pilot, "se")
        assert hint_text(app) == "sel · set"
        await pilot.press("left")  # the cursor moves: the hint is about the line before it
        assert hint_text(app).startswith("safety · save · sel · set")

    drive(app, body)


def test_tab_completes_the_word(club: busk.OfflineShow) -> None:
    app = make_app(FakeBridge(show=club))

    async def body(pilot: Pilot[int]) -> None:
        prompt = app.query_one(Prompt)
        await type_line(pilot, "blind of")
        await pilot.press("tab")
        assert (prompt.value, prompt.cursor_position) == ("blind off ", 10)
        await pilot.press("escape")
        await type_line(pilot, "u")
        await pilot.press("tab")
        assert prompt.value == "un"
        assert list(app.query_one(LogView).entries)[-1] == (
            "info",
            "unbind  undo  universe  unpark",
        )

    drive(app, body)


def test_a_line_the_engine_asks_about_runs_only_on_yes(club: busk.OfflineShow) -> None:
    bridge = FakeBridge(show=club)
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await type_line(pilot, "output off")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)
        assert app.screen.question == "Turn all DMX output off?"
        assert bridge.sent == []
        await pilot.press("f2", "escape")  # the page keys wait; Esc is No
        await pilot.pause()
        assert app.page == 1
        assert bridge.sent == []
        assert list(app.query_one(LogView).entries)[-1] == ("info", "cancelled: output off")
        for no in ("n", "enter"):
            await type_line(pilot, "output off")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press(no)
            await pilot.pause()
            assert bridge.sent == []
        await type_line(pilot, "output off")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("y")
        await settle(pilot, app)
        assert bridge.lines() == ["output off"]
        assert ("typed", "output off") in app.query_one(LogView).entries

    drive(app, body)


def test_a_click_on_no_cancels(club: busk.OfflineShow) -> None:
    bridge = FakeBridge(show=club)
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await type_line(pilot, "output off")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.click("#choice-no")
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmDialog)
        assert bridge.sent == []

    drive(app, body)


def test_a_reply_that_quits_opens_the_quit_dialog_and_cancel_carries_on() -> None:
    bridge = FakeBridge(replies={"quit": Reply(quit=True)})
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await type_line(pilot, "quit")
        await pilot.press("enter")
        await settle(pilot, app)
        assert isinstance(app.screen, QuitDialog)
        assert app.screen.dirty is None  # not known yet
        await pilot.press("c")
        await pilot.pause()
        assert not isinstance(app.screen, QuitDialog)
        assert app.is_running

    drive(app, body)


def test_save_and_quit_saves_then_quits() -> None:
    bridge = FakeBridge(replies={"quit": Reply(quit=True)})
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(SessionChanged(SessionState(1, 0, dirty=True)))
        await type_line(pilot, "quit")
        await pilot.press("enter")
        await settle(pilot, app)
        assert isinstance(app.screen, QuitDialog)
        await pilot.press("s")
        await settle(pilot, app)
        assert bridge.lines() == ["quit", "save"]

    drive(app, body)
    assert app.return_code == 0


def test_a_failed_save_does_not_quit() -> None:
    bridge = FakeBridge(
        replies={"quit": Reply(quit=True), "save": Reply(ok=False, text="error: disk full")}
    )
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(SessionChanged(SessionState(1, 0, dirty=True)))
        await type_line(pilot, "quit")
        await pilot.press("enter")
        await settle(pilot, app)
        await pilot.press("s")
        await settle(pilot, app)
        assert app.is_running
        assert list(app.query_one(LogView).entries)[-1] == ("error", "disk full")

    drive(app, body)


def test_without_unsaved_edits_quit_just_quits() -> None:
    bridge = FakeBridge(replies={"exit": Reply(quit=True)})
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(SessionChanged(SessionState(0, 0, dirty=False)))
        await settle(pilot, app)
        await type_line(pilot, "exit")
        await pilot.press("enter")
        await settle(pilot, app)
        assert isinstance(app.screen, QuitDialog)
        await pilot.press("s")  # no save offered
        await pilot.pause()
        assert isinstance(app.screen, QuitDialog)
        await pilot.press("q")
        await pilot.pause()

    drive(app, body)
    assert app.return_code == 0
    assert bridge.lines() == ["exit"]


def test_ctrl_c_clears_then_says_how_to_quit_then_asks() -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        await type_line(pilot, "gm 5")
        await pilot.press("ctrl+c")
        assert app.query_one(Prompt).value == ""
        assert not isinstance(app.screen, QuitDialog)
        await pilot.press("ctrl+c")
        assert hint_text(app) == "press Ctrl+C again to quit"
        await pilot.press("x", "backspace")  # anything else in between: start again
        await pilot.press("ctrl+c")
        assert not isinstance(app.screen, QuitDialog)
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert isinstance(app.screen, QuitDialog)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, QuitDialog)

    drive(app, body)


def test_ctrl_q_asks_too() -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        await pilot.press("ctrl+q")
        await pilot.pause()
        assert isinstance(app.screen, QuitDialog)

    drive(app, body)


def test_a_typed_help_opens_the_overlay_with_its_reply() -> None:
    bridge = FakeBridge(replies={"help": Reply(text="    go N | back N\n    gm <level>")})
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await type_line(pilot, "help")
        await pilot.press("enter")
        await settle(pilot, app)
        overlay = app.query_one(HelpOverlay)
        assert overlay.is_open
        assert overlay.text == "    go N | back N\n    gm <level>"
        assert list(app.query_one(LogView).entries)[-1] == ("typed", "help")

    drive(app, body)


def test_the_pane_cursor_moves_into_the_page_and_back() -> None:
    bridge = FakeBridge()
    fixtures = (FixtureInfo(101, 1, "Spot 101", "Spot"), FixtureInfo(102, 1, "Spot 102", "Spot"))
    bridge.events.append(ShowChanged(show_model(fixtures=fixtures)))
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await settle(pilot, app)
        await pilot.press("f3")
        prompt = app.query_one(Prompt)
        await pilot.press("tab")
        assert app.cursor.index == 0
        assert app.query_one(FixtureTable)._marked == (0, None)
        await pilot.press("down", "down")
        assert app.cursor.index == 2  # past the rows: the first edit
        await pilot.press("up")
        assert app.cursor.index == 1
        await pilot.press("enter")  # a row's line runs, and the cursor stays
        assert app.cursor.active
        assert bridge.lines() == ["sel fixture 102"]
        await pilot.press("escape", "tab", "escape")
        assert not app.cursor.active
        assert prompt.value == ""
        await pilot.press("tab", "g")  # typing gives the keyboard back
        assert not app.cursor.active
        assert prompt.value == "g"
        await pilot.press("escape", "tab", "down", "down", "enter")
        assert prompt.value == "fixture 102 patch "  # a line to finish, for the row chosen
        assert not app.cursor.active
        assert bridge.lines() == ["sel fixture 102"]
        await pilot.press("tab", "f2")  # another page: the cursor leaves
        assert not app.cursor.active

    drive(app, body)


def test_keys_in_one_burst_are_taken_in_order(club: busk.OfflineShow) -> None:
    """Tab after keys that came all at once (fast typing, a paste) completes
    the line they made: the prompt, not an app binding, takes it."""
    app = make_app(FakeBridge(show=club))

    async def body(pilot: Pilot[int]) -> None:
        for character in "blind of":
            key = "space" if character == " " else character
            app.post_message(events.Key(key, character))
        app.post_message(events.Key("tab", "\t"))
        app.post_message(events.Key("question_mark", "?"))
        await pilot.pause(0.2)
        assert app.query_one(Prompt).value == "blind off ?"
        assert not app.query_one(HelpOverlay).is_open

    drive(app, body)
