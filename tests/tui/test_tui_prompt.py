"""The command line (spec §6.1, §7, plan step 0.4): typing and running lines,
the log's line types, history, hints and completion, the engine's question,
quitting, Ctrl+C and the pane cursor. Headless, with a fake bridge; with
``show=club``, its help, answers and questions are busk's own."""

from __future__ import annotations

import asyncio

import pytest
from rich.cells import cell_len
from rich.console import Console
from textual import events
from textual.app import App, ComposeResult
from textual.pilot import Pilot
from tui_fakes import FakeBridge, Reply, drive, make_app, settle, show_model

import busk
from busk_tui import colors
from busk_tui.model import EngineNews, FixtureInfo, SessionChanged, SessionState, ShowChanged
from busk_tui.widgets.dialogs import ConfirmDialog, QuitDialog
from busk_tui.widgets.fixturetable import FixtureTable
from busk_tui.widgets.help import HelpOverlay
from busk_tui.widgets.log import LogView, log_line, log_rows
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


LOG_KINDS = [
    ("typed", "busk> "),
    ("ui", " ui> "),
    ("result", "      "),
    ("error", " ✗ "),
    ("info", " · "),
    ("warning", " ! "),
]


def strip_rows(log: LogView) -> list[str]:
    return [strip.text.rstrip() for strip in log.lines]


@pytest.mark.parametrize(("kind", "prefix"), LOG_KINDS)
def test_a_wrapped_line_goes_on_under_its_text(kind: str, prefix: str) -> None:
    words = [f"word{n}" for n in range(30)]
    rows = log_rows(Console(), kind, " ".join(words), 40)  # type: ignore[arg-type]
    assert len(rows) > 1
    assert rows[0].plain.startswith(prefix + "word0")
    assert all(row.plain.startswith(" " * len(prefix) + "word") for row in rows[1:])
    assert all(row.cell_len <= 40 for row in rows)
    assert [word for row in rows for word in row.plain.removeprefix(prefix).split()] == words


def test_the_rows_of_a_line_keep_its_prefix_and_text_colours() -> None:
    first, second = log_rows(Console(), "error", "aaaa bbbb", 8)
    assert (first.plain.rstrip(), second.plain) == (" ✗ aaaa", "   bbbb")
    assert colors.RED in str(first.spans[0].style)
    assert colors.RED in str(second.style)


def test_a_word_wider_than_a_row_folds() -> None:
    rows = log_rows(Console(), "info", "x" * 25, 13)
    assert [row.plain for row in rows] == [" · " + "x" * 10, "   " + "x" * 10, "   " + "x" * 5]


def test_an_empty_line_and_one_that_fits_are_one_row() -> None:
    assert [row.plain for row in log_rows(Console(), "result", "", 40)] == ["      "]
    assert [row.plain for row in log_rows(Console(), "info", "ok", 40)] == [" · ok"]
    assert log_rows(Console(), "error", "ok", 40, first=False)[0].plain == "   ok"


def test_a_300_character_reply_shows_every_word_at_99_columns() -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        log = app.query_one(LogView)
        before = len(log.lines)
        words = [f"word{n:03}" for n in range(38)]
        text = " ".join(words)
        assert len(text) > 300
        log.add("result", text)
        await pilot.pause()
        rows = strip_rows(log)[before:]
        room = log.scrollable_content_region.width
        assert room == 99 - 3  # the padding and the scrollbar
        assert len(rows) == 4
        assert all(cell_len(row) <= room for row in rows)
        assert " ".join(rows).split() == words
        assert log.max_scroll_x == 0
        assert list(log.entries)[-1] == ("result", text)  # one item for the line
        assert log.is_vertical_scroll_end

    drive(app, body, size=(99, 30))


def test_a_resize_flows_the_kept_lines_again() -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        log = app.query_one(LogView)
        log.add("error", "first\nsecond " + "word " * 30)
        log.add("info", "short")
        await pilot.pause()
        kept = list(log.entries)
        wide = strip_rows(log)
        await pilot.resize_terminal(60, 30)
        await pilot.pause()
        assert list(log.entries) == kept
        narrow = strip_rows(log)
        room = log.scrollable_content_region.width
        assert room == 60 - 3
        assert len(narrow) > len(wide)
        assert all(cell_len(row) <= room for row in narrow)
        assert log.max_scroll_x == 0
        assert " ✗ first" in narrow
        assert not any(row.startswith(" ✗ second") for row in narrow)
        assert any(row.startswith("   second") for row in narrow)  # first=False survives it
        assert narrow[-1] == " · short"
        assert log.is_vertical_scroll_end
        await pilot.resize_terminal(99, 30)
        await pilot.pause()
        assert strip_rows(log) == wide  # back as it was

    drive(app, body, size=(99, 30))


def test_a_line_added_before_the_pane_has_a_width_shows_once_it_has_one() -> None:
    class Host(App[None]):
        def compose(self) -> ComposeResult:
            view = LogView()
            view.add("info", "early")
            yield view

    async def main() -> None:
        host = Host()
        async with host.run_test(size=(80, 20)) as pilot:
            await pilot.pause()
            assert strip_rows(host.query_one(LogView)) == [" · early"]

    asyncio.run(main())


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
        assert app.cursor.index == 0  # [+ add], then [edit]
        await pilot.press("down", "down")
        assert app.query_one(FixtureTable)._marked == (0, None)
        await pilot.press("down", "down")
        assert app.cursor.index == 3  # the last row: it stops at the end
        await pilot.press("up")
        assert app.cursor.index == 2
        await pilot.press("down", "enter")  # a row's line runs, and the cursor stays
        assert app.cursor.active
        assert bridge.lines() == ["sel fixture 102"]
        await pilot.press("escape", "tab", "escape")
        assert not app.cursor.active
        assert prompt.value == ""
        await pilot.press("tab", "g")  # typing gives the keyboard back
        assert not app.cursor.active
        assert prompt.value == "g"
        await pilot.press("escape", "tab")
        assert app.cursor.active
        await pilot.press("f7")  # another page: the cursor leaves
        assert not app.cursor.active
        await pilot.press("tab", "enter")  # the grand master: a line to finish
        assert prompt.value == "gm "
        assert not app.cursor.active
        assert bridge.lines() == ["sel fixture 102"]

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
