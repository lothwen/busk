"""Importing (file-menu plan Phase 7): Import script… runs a script through
the bridge, its lines in the log as they run and a bar in the hint row, and
another show, or Close, waits for it; Import profile… in the File menu. On the fake
bridge, then on the real engine."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from rich.text import Text
from textual.pilot import Pilot
from tui_fakes import FakeBridge, Reply, drive, make_app, script_events, settle

from busk_tui import config, parent, shell
from busk_tui.bridge import Bridge
from busk_tui.model import ScriptDone, SessionChanged, SessionState
from busk_tui.shell import LOG_S, BuskApp
from busk_tui.widgets.controls import ShowHint
from busk_tui.widgets.dialogs import QuitDialog
from busk_tui.widgets.file_menu import ITEMS, FileMenu
from busk_tui.widgets.file_picker import Entry, FileDialog, home_text
from busk_tui.widgets.log import LogView
from busk_tui.widgets.profile_picker import ProfileDialog
from busk_tui.widgets.prompt import HintRow, import_text, progress_text

WAIT = "lines typed now wait"


def hint(app: BuskApp) -> str:
    content = app.query_one(HintRow).content
    return content.plain if isinstance(content, Text) else str(content)


def entries(app: BuskApp) -> list[tuple[str, str]]:
    return list(app.query_one(LogView).entries)


def pane(app: BuskApp) -> list[str]:
    """The log's rows as the pane shows them."""
    return [strip.text.rstrip() for strip in app.query_one(LogView).lines]


def script(folder: Path, text: str, name: str = "rig.busk") -> Path:
    path = folder / name
    path.write_text(text)
    return path


async def choose(pilot: Pilot[int], item: str) -> None:
    """Open the menu with Alt+F and choose ``item``."""
    await pilot.press("alt+f")
    await pilot.pause()
    index = [choice for choice, _, _ in ITEMS].index(item)  # type: ignore[comparison-overlap]
    await pilot.press(*["down"] * index, "enter")
    await pilot.pause()


# --------------------------------------------------------------- the bar


def test_progress_is_drawn_to_half_a_cell() -> None:
    assert progress_text(0.0, 10).plain == "─" * 10
    assert progress_text(0.05, 10).plain == "╸" + "─" * 9
    assert progress_text(0.5, 10).plain == "━" * 5 + "─" * 5
    assert progress_text(1.0, 10).plain == "━" * 10


def test_the_import_bar_says_how_far_and_shrinks_to_fit() -> None:
    def bar(cells: int) -> str:
        return progress_text(812 / 2189, cells).plain

    for width, cells in ((150, 30), (80, 23), (40, 10)):  # 10 at least: the row cuts the end
        shown = import_text("festival.busk", 812, 2189, width).plain
        assert shown == f"IMPORT festival.busk  {bar(cells)}  812 / 2189 · {WAIT}"
    assert len(import_text("festival.busk", 812, 2189, 80)) == 80
    starting = import_text("rig.busk", 0, 0, 150).plain
    assert starting == f"IMPORT rig.busk  {'─' * 30}  starting · {WAIT}"


def test_the_bar_takes_the_hint_rows_place_until_the_script_ends(tmp_path: Path) -> None:
    path = script(tmp_path, "sel 1\nsel 2\nsel 3\nsel 4\n")
    bridge = FakeBridge(auto_reply=False)
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        app.start_import(path)
        await settle(pilot, app)
        assert hint(app) == import_text("rig.busk", 0, 0, 150).plain
        ((ticket, _),) = bridge.scripts
        lines = script_events(ticket, path)
        bridge.events.append(lines[0])
        await settle(pilot, app)
        assert hint(app) == import_text("rig.busk", 1, 4, 150).plain
        await pilot.pause(LOG_S)
        await settle(pilot, app)
        assert pane(app)[-1] == " ui> rig.busk:1  sel 1"  # the pane, 5 times a second
        await pilot.press("g", "m")  # typing keeps it
        assert hint(app) == import_text("rig.busk", 1, 4, 150).plain
        app.post_message(ShowHint("over a cell"))  # so does the mouse
        await pilot.pause()
        assert hint(app) == import_text("rig.busk", 1, 4, 150).plain
        await pilot.press("ctrl+c", "ctrl+c")  # the line, then the word on quitting
        bridge.events.append(lines[1])
        await settle(pilot, app)
        assert hint(app) == "press Ctrl+C again to quit"
        await pilot.press("x")
        assert hint(app) == import_text("rig.busk", 2, 4, 150).plain
        bridge.events += lines[2:]
        await settle(pilot, app)
        assert not hint(app).startswith("IMPORT")
        assert app.importing is None

    drive(app, body)


# ---------------------------------------------------------------- the log


def test_each_line_and_its_reply_reach_the_log_in_order_but_blanks_and_comments(
    tmp_path: Path,
) -> None:
    path = script(tmp_path, "# a rig\n\nsel group 1\nrecord group 9\n")
    bridge = FakeBridge(replies={"sel group 1": Reply(text="2 targets selected")})
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        app.start_import(path)
        await settle(pilot, app)
        assert entries(app)[-5:] == [
            ("info", f"importing {home_text(path)}"),
            ("ui", "rig.busk:3  sel group 1"),
            ("result", "2 targets selected"),
            ("ui", "rig.busk:4  record group 9"),
            ("info", "imported rig.busk: 4 lines (Ctrl+Z undoes it)"),
        ]
        assert pane(app)[-4:] == [  # all of it, once, as the import ends
            " ui> rig.busk:3  sel group 1",
            "      2 targets selected",
            " ui> rig.busk:4  record group 9",
            " · imported rig.busk: 4 lines (Ctrl+Z undoes it)",
        ]
        assert bridge.lines() == []

    drive(app, body)


def test_the_pane_takes_the_lines_at_each_flush_and_at_the_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each write to the pane lays the screen out again: while a script
    imports, the entries have each line at once, the pane at the next flush
    (here never) or at the end."""
    monkeypatch.setattr(shell, "LOG_S", 60.0)
    path = script(tmp_path, "sel 1\nsel 2\n")
    bridge = FakeBridge(auto_reply=False)
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        app.start_import(path)
        ((ticket, _),) = bridge.scripts
        lines = script_events(ticket, path)
        bridge.events.append(lines[0])
        await settle(pilot, app)
        assert ("ui", "rig.busk:1  sel 1") in entries(app)
        assert " ui> rig.busk:1  sel 1" not in pane(app)
        bridge.events += lines[1:]
        await settle(pilot, app)
        assert pane(app)[-3:] == [
            " ui> rig.busk:1  sel 1",
            " ui> rig.busk:2  sel 2",
            " · imported rig.busk: 2 lines (Ctrl+Z undoes it)",
        ]

    drive(app, body)


def test_a_refused_line_stops_the_import_and_says_where(tmp_path: Path) -> None:
    path = script(tmp_path, "sel 1\nbad line\nsel 3\n")
    bridge = FakeBridge(replies={"bad line": Reply(False, "error: no such thing\nat 'line'")})
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        app.start_import(path)
        await settle(pilot, app)
        assert entries(app)[-5:] == [
            ("ui", "rig.busk:1  sel 1"),  # its reply is empty: not shown
            ("ui", "rig.busk:2  bad line"),
            ("error", "no such thing"),
            ("error", "at 'line'"),
            ("error", "stopped at line 2 of 3 (Ctrl+Z undoes the lines before it)"),
        ]
        assert app.importing is None

    drive(app, body)


def test_a_script_refused_at_its_first_line_or_changing_nothing_has_no_step(
    tmp_path: Path,
) -> None:
    refused = script(tmp_path, "bad line\nsel 2\n", "bad.busk")
    quiet = script(tmp_path, "# nothing\n", "quiet.busk")
    bridge = FakeBridge(replies={"bad line": Reply(False, "error: no")})
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        app.start_import(refused)
        await settle(pilot, app)
        assert entries(app)[-1] == ("error", "stopped at line 1 of 2")
        app.start_import(quiet)
        await settle(pilot, app)
        assert entries(app)[-1] == ("info", "imported quiet.busk: 1 line")

    drive(app, body)


def test_a_quit_line_ends_the_import_and_opens_the_quit_dialog(tmp_path: Path) -> None:
    path = script(tmp_path, "sel 1\nquit\nsel 3\n")
    app = make_app(FakeBridge(replies={"quit": Reply(quit=True)}))

    async def body(pilot: Pilot[int]) -> None:
        app.start_import(path)
        await settle(pilot, app)
        assert ("info", "imported rig.busk: 2 of 3 lines, to its quit (Ctrl+Z undoes it)") in (
            entries(app)
        )
        assert isinstance(app.screen, QuitDialog)

    drive(app, body)


def test_a_script_that_cannot_be_read_says_why(tmp_path: Path) -> None:
    path = tmp_path / "gone.busk"
    bridge = FakeBridge(auto_reply=False)
    app = make_app(bridge)
    problem = f"cannot read {str(path)!r}: No such file or directory"

    async def body(pilot: Pilot[int]) -> None:
        app.start_import(path)
        ((ticket, _),) = bridge.scripts
        bridge.events.append(ScriptDone(ticket, path, False, 0, 0, False, problem=problem))
        await settle(pilot, app)
        assert entries(app)[-1] == ("error", problem)
        assert not hint(app).startswith("IMPORT")

    drive(app, body)


def test_what_another_script_sends_does_not_end_the_bar(tmp_path: Path) -> None:
    path = script(tmp_path, "sel 1\n")
    bridge = FakeBridge(auto_reply=False)
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        app.start_import(path)
        ((ticket, _),) = bridge.scripts
        bridge.events += script_events(ticket + 1, path)
        await settle(pilot, app)
        assert app.importing is not None
        assert hint(app) == import_text("rig.busk", 0, 0, 150).plain
        assert ("ui", "rig.busk:1  sel 1") not in entries(app)

    drive(app, body)


# ------------------------------------------------------- waiting for it


def test_another_show_and_another_script_wait_for_the_import(tmp_path: Path) -> None:
    path = script(tmp_path, "sel 1\n")
    bridge = FakeBridge(auto_reply=False)
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(
            SessionChanged(SessionState(0, 0, dirty=False, path=tmp_path / "a.show"))
        )
        await settle(pilot, app)
        app.start_import(path)
        await pilot.press("ctrl+n", "ctrl+o")
        await choose(pilot, "open_recent")
        await choose(pilot, "import_script")
        await choose(pilot, "close")
        assert not isinstance(app.screen, FileDialog | FileMenu)
        assert entries(app)[-5:] == [
            ("warning", "rig.busk is importing: start a new show once it ends"),
            ("warning", "rig.busk is importing: open another show once it ends"),
            ("warning", "rig.busk is importing: open another show once it ends"),
            ("warning", "rig.busk is importing: import another script once it ends"),
            ("warning", "rig.busk is importing: close the show once it ends"),
        ]
        app._open(tmp_path / "b.show")  # a show read or made before the import started
        app._open(parent.CLOSE)  # a close confirmed, its save waited for, meanwhile
        await pilot.pause()
        assert app.is_running
        assert app.next_show is None
        assert entries(app)[-1] == ("warning", "rig.busk is importing: close the show once it ends")
        ((ticket, _),) = bridge.scripts
        bridge.events += script_events(ticket, path)
        await settle(pilot, app)
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert isinstance(app.screen, FileDialog)

    drive(app, body)


# ------------------------------------------------------- import profile


def test_import_profile_sends_profile_import_and_the_reply_goes_to_the_log(
    tmp_path: Path,
) -> None:
    (tmp_path / "club.show").write_text("{}")
    (tmp_path / "spot.json").write_text("{}")
    line = f"profile import {json.dumps(str(tmp_path / 'spot.json'))}"
    bridge = FakeBridge(replies={line: Reply(False, "error: cannot import: not a profile")})
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(SessionChanged(SessionState(0, 0, False, tmp_path / "club.show")))
        await settle(pilot, app)
        await choose(pilot, "import_profile")
        files = app.screen
        assert isinstance(files, FileDialog)
        assert (files.mode, files.folder) == ("profile", tmp_path)  # the show's folder
        await pilot.press(*"spot", "enter")
        await settle(pilot, app)
        assert bridge.lines() == [line]
        assert ProfileDialog.last == tmp_path / "spot.json"
        assert ("ui", line) in entries(app)
        assert entries(app)[-1] == ("error", "cannot import: not a profile")

    drive(app, body)


def test_import_profile_starts_on_the_profile_file_chosen_last(tmp_path: Path) -> None:
    (tmp_path / "fixtures").mkdir()
    last = tmp_path / "fixtures" / "wash.gdtf"
    last.write_text("")
    ProfileDialog.last = last
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        await choose(pilot, "import_profile")
        files = app.screen
        assert isinstance(files, FileDialog)
        assert files.folder == last.parent
        assert files.current() == Entry("wash.gdtf", folder=False)

    drive(app, body)


# ------------------------------------------------------ the real engine


async def until(pilot: Pilot[int], test: Callable[[], bool]) -> None:
    for _ in range(300):
        if test():
            return
        await pilot.pause(0.05)
    raise AssertionError("timed out")


def test_an_import_on_the_real_engine_is_one_undo_step_and_typed_lines_wait(
    club_path: Path, tmp_path: Path
) -> None:
    """Each line in the log as it ran; a line typed after the import runs
    after it; one Ctrl+Z takes the import back whole, the show and the
    programmer. A refused line stops the next import, and one Ctrl+Z takes
    back the lines before it."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    rig = script(tmp_path, '# a group\nsel fixture 101\n\nrecord group 90 "Imported"\n')
    half = "sel fixture 102\nrecord group 92\nset nonsense 5\nsel + fixture 103\n"
    script(tmp_path, half, "half.busk")
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(), standalone=True)

    def groups() -> set[int]:
        return set() if app.view.show is None else {g.number for g in app.view.show.groups}

    def selected() -> int:
        return -1 if app.programmer is None else len(app.programmer.selection)

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.session is not None and selected() == 0)
        app.start_import(rig)
        assert app.importing is not None
        app.run_line("record group 91", "typed")  # while it imports
        await until(pilot, lambda: {90, 91} <= groups())
        log = entries(app)
        typed = log.index(("typed", "record group 91"))
        done = log.index(("info", "imported rig.busk: 4 lines (Ctrl+Z undoes it)"))
        assert typed < log.index(("ui", "rig.busk:2  sel fixture 101")) < done
        assert log.index(("ui", 'rig.busk:4  record group 90 "Imported"')) < done
        assert not any(text.startswith(("rig.busk:1", "rig.busk:3")) for _, text in log)
        assert any(kind == "result" and "91" in text for kind, text in log[done:])  # ran after
        await pilot.press("ctrl+z")  # the typed line
        await until(pilot, lambda: 91 not in groups())
        assert 90 in groups()
        assert selected() == 1
        await pilot.press("ctrl+z")  # the import, whole
        await until(pilot, lambda: 90 not in groups())
        assert selected() == 0
        assert ("result", f"undid: source {rig}") in entries(app)

        await choose(pilot, "import_script")  # through the menu
        await pilot.press(*"half", "enter")
        stopped = ("error", "stopped at line 3 of 4 (Ctrl+Z undoes the lines before it)")
        await until(pilot, lambda: stopped in entries(app))
        assert 92 in groups()
        assert selected() == 1  # line 4 never ran
        await pilot.press("ctrl+z")
        await until(pilot, lambda: 92 not in groups())
        assert selected() == 0

    try:
        drive(app, body)
    finally:
        bridge.stop()
