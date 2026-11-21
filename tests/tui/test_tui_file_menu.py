"""The File menu (``busk_tui.widgets.file_menu``) on the status bar's badge,
what its items do (Save, Save as…, Import script…, Quit), Ctrl+S, and the
recent shows the app keeps in ``state.json`` (file-menu plan Phase 2). How an
import runs, and Import profile…, are in ``test_tui_import.py``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from textual.pilot import Pilot
from textual.widgets import OptionList
from tui_fakes import FakeBridge, Reply, drive, make_app, settle

import busk
from busk_tui import config
from busk_tui.bridge import Bridge
from busk_tui.model import EngineRunning, SessionChanged, SessionState
from busk_tui.shell import BuskApp
from busk_tui.widgets.dialogs import ConfirmDialog, QuitDialog
from busk_tui.widgets.file_menu import ITEMS, FileMenu
from busk_tui.widgets.file_picker import FileDialog
from busk_tui.widgets.frame import StatusBar
from busk_tui.widgets.log import LogView
from busk_tui.widgets.prompt import Prompt


def menu_of(app: BuskApp) -> FileMenu:
    screen = app.screen
    assert isinstance(screen, FileMenu), screen
    return screen


async def choose(pilot: Pilot[int], app: BuskApp, item: str) -> None:
    """Open the menu with Alt+F and choose ``item``."""
    await pilot.press("alt+f")
    await pilot.pause()
    index = [choice for choice, _, _ in ITEMS].index(item)  # type: ignore[comparison-overlap]
    await pilot.press(*["down"] * index, "enter")
    await pilot.pause()


def picker_of(app: BuskApp) -> FileDialog:
    screen = app.screen
    assert isinstance(screen, FileDialog), screen
    return screen


def at(path: Path, dirty: bool = False) -> SessionChanged:
    return SessionChanged(SessionState(0, 0, dirty=dirty, path=path))


# ------------------------------------------------------------------ the menu


def test_a_click_on_the_badge_opens_the_menu_under_it_and_esc_closes_it() -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        await pilot.click(StatusBar, offset=(2, 0))
        await pilot.pause()
        menu = menu_of(app)
        options = menu.query_one(OptionList)
        assert (options.region.x, options.region.y) == (0, 1)
        assert options.border_title == "FILE"
        rows = [str(options.get_option_at_index(i).prompt) for i in range(options.option_count)]
        assert [" ".join(row.split()) for row in rows] == [
            "New… Ctrl+N",
            "Open… Ctrl+O",
            "Open recent…",
            "Save Ctrl+S",
            "Save as…",
            "Import script…",
            "Import profile…",
            "Quit Ctrl+Q",
        ]
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, FileMenu)
        assert app.focused is app.query_one(Prompt)

    drive(app, body)


def test_alt_f_opens_and_closes_it_and_a_click_outside_closes_it() -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        await pilot.press("alt+f")
        await pilot.pause()
        menu_of(app)
        await pilot.press("alt+f")
        await pilot.pause()
        assert not isinstance(app.screen, FileMenu)
        await pilot.press("alt+f")
        await pilot.pause()
        await pilot.click(offset=(80, 20))
        await pilot.pause()
        assert not isinstance(app.screen, FileMenu)
        assert app.bridge.lines() == []  # type: ignore[attr-defined]

    drive(app, body)


def test_the_menu_keeps_the_page_keys_while_it_is_open() -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        await pilot.press("alt+f")
        await pilot.pause()
        await pilot.press("f3")
        await pilot.pause()
        assert app.page == 1
        menu_of(app)

    drive(app, body)


def test_save_in_the_menu_and_ctrl_s_send_save_with_or_without_edits() -> None:
    bridge = FakeBridge(replies={"save": Reply(text="saved /s/club.show")})
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        await choose(pilot, app, "save")
        await settle(pilot, app)
        assert bridge.lines() == ["save"]
        assert ("result", "saved /s/club.show") in app.query_one(LogView).entries
        await pilot.press(*"sel", "space", "1", "ctrl+s")  # whatever the prompt holds
        await settle(pilot, app)
        assert bridge.lines() == ["save", "save"]
        assert app.query_one(Prompt).value == "sel 1"

    drive(app, body)


def test_quit_in_the_menu_opens_the_quit_dialog() -> None:
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        await choose(pilot, app, "quit")
        assert isinstance(app.screen, QuitDialog)

    drive(app, body)


# ------------------------------------------------------------------ save as


def show_folder(root: Path) -> Path:
    folder = root / "shows"
    folder.mkdir()
    (folder / "club.show").write_text("{}")
    (folder / "fest.show").write_text("{}")
    return folder


def test_save_as_starts_on_the_shows_file_and_sends_the_path_typed(tmp_path: Path) -> None:
    folder = show_folder(tmp_path)
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(at(folder / "club.show", dirty=True))
        await settle(pilot, app)
        await choose(pilot, app, "save_as")
        picker = picker_of(app)
        assert (picker.mode, picker.folder, picker.field.value) == ("save", folder, "club.show")
        await pilot.press("ctrl+u", *"late", "space", *"night", "enter")
        await settle(pilot, app)
        line = f"save {json.dumps(str(folder / 'late night.show'))}"
        assert bridge.lines() == [line]
        assert ("ui", line) in app.query_one(LogView).entries

    drive(app, body)


def test_save_as_over_another_file_asks_first(tmp_path: Path) -> None:
    folder = show_folder(tmp_path)
    bridge = FakeBridge()
    app = make_app(bridge)
    line = f"save {json.dumps(str(folder / 'fest.show'))}"

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(at(folder / "club.show"))
        await settle(pilot, app)
        for answer in ("n", "y"):
            await choose(pilot, app, "save_as")
            await pilot.press("ctrl+u", *"fest", "enter")
            await pilot.pause()
            dialog = app.screen
            assert isinstance(dialog, ConfirmDialog)
            assert dialog.question == "Replace fest.show? busk keeps a backup of it."
            assert dialog.line == line
            await pilot.press(answer)
            await settle(pilot, app)
            assert bridge.lines() == ([] if answer == "n" else [line])

    drive(app, body)


def test_save_as_to_the_shows_own_file_is_a_plain_save(tmp_path: Path) -> None:
    folder = show_folder(tmp_path)
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(at(folder / "club.show"))
        await settle(pilot, app)
        await choose(pilot, app, "save_as")
        await pilot.press("enter")
        await settle(pilot, app)
        assert not isinstance(app.screen, ConfirmDialog)
        assert bridge.lines() == ["save"]

    drive(app, body)


def test_save_as_before_the_show_has_a_file_starts_where_busk_tui_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = make_app()

    async def body(pilot: Pilot[int]) -> None:
        await choose(pilot, app, "save_as")
        picker = picker_of(app)
        assert (picker.folder, picker.field.value) == (tmp_path, "")

    drive(app, body)


# ------------------------------------------------------------ import script


def test_import_script_starts_in_the_shows_folder_and_runs_the_script(tmp_path: Path) -> None:
    folder = show_folder(tmp_path)
    script = folder / "rig.busk"
    script.write_text("sel group 1\n")
    bridge = FakeBridge(replies={"sel group 1": Reply(text="2 targets selected")})
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(at(folder / "club.show"))
        await settle(pilot, app)
        await choose(pilot, app, "import_script")
        picker = picker_of(app)
        assert (picker.mode, picker.folder) == ("script", folder)
        await pilot.press(*"rig", "enter")
        await settle(pilot, app)
        assert [path for _, path in bridge.scripts] == [script]
        assert bridge.lines() == []  # not as a line
        entries = app.query_one(LogView).entries
        assert ("ui", "rig.busk:1  sel group 1") in entries
        assert ("result", "2 targets selected") in entries

    drive(app, body)


# ------------------------------------------------------------ recent shows


def test_the_show_running_and_a_copy_saved_are_recent_shows(tmp_path: Path) -> None:
    bridge = FakeBridge()
    app = make_app(bridge)
    state = config.state_path()

    def recent() -> list[tuple[str, str]]:
        return [(e["path"], e["title"]) for e in config.read_state(state).get("recent", [])]

    async def body(pilot: Pilot[int]) -> None:
        bridge.events += [EngineRunning("Club Night", ()), at(tmp_path / "club.show")]
        await settle(pilot, app)
        assert recent() == [(str(tmp_path / "club.show"), "Club Night")]
        state.unlink()
        bridge.events.append(at(tmp_path / "club.show", dirty=True))  # the same file
        await settle(pilot, app)
        assert not state.exists()
        bridge.events.append(at(tmp_path / "copy.show"))  # a save as
        await settle(pilot, app)
        assert recent() == [(str(tmp_path / "copy.show"), "Club Night")]

    drive(app, body)


def test_a_session_without_a_file_is_no_recent_show() -> None:
    bridge = FakeBridge()
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(SessionChanged(SessionState(0, 0, dirty=True)))
        await settle(pilot, app)
        assert "recent" not in config.read_state(config.state_path())

    drive(app, body)


# ------------------------------------------------------------ the real engine


def test_save_as_and_import_script_on_the_real_engine(club_path: Path, tmp_path: Path) -> None:
    """Save as writes a copy with an id of its own and leaves the file it
    came from as it was; the copy is the show from then on, and the newest
    recent show. Import script runs the script's lines."""
    path = tmp_path / "club.show"
    path.write_bytes(club_path.read_bytes())
    (tmp_path / "groups.busk").write_text('# a group\nsel fixture 101\nrecord group 90 "Script"\n')
    bridge = Bridge.standalone(path, output=False, surfaces=False)
    app = BuskApp(bridge, config.Settings(), standalone=True)

    async def until(pilot: Pilot[int], test: object) -> None:
        for _ in range(300):
            if test():  # type: ignore[operator]
                return
            await pilot.pause(0.05)
        raise AssertionError("timed out")

    async def body(pilot: Pilot[int]) -> None:
        await until(pilot, lambda: app.session is not None and app.session.path == path)
        await pilot.press(*"sel", "space", *"fixture", "space", *"101", "enter")
        await pilot.press(*"record", "space", *"group", "space", *"91", "enter")
        await until(pilot, lambda: app.session.dirty)  # type: ignore[union-attr]
        await choose(pilot, app, "save_as")
        await pilot.press("ctrl+u", *"copy", "enter")
        await until(pilot, lambda: app.session.path == tmp_path / "copy.show")  # type: ignore[union-attr]
        assert not app.session.dirty  # type: ignore[union-attr]
        recent = config.read_state(config.state_path())["recent"]
        assert [e["path"] for e in recent] == [str(tmp_path / "copy.show"), str(path)]
        await choose(pilot, app, "import_script")
        await pilot.press(*"groups", "enter")
        shown = app.view
        await until(
            pilot,
            lambda: shown.show is not None and any(g.name == "Script" for g in shown.show.groups),
        )
        await choose(pilot, app, "save")
        await until(pilot, lambda: not app.session.dirty)  # type: ignore[union-attr]

    try:
        drive(app, body)
    finally:
        bridge.stop()
    original, _ = busk.load_show(path)
    copy, _ = busk.load_show(tmp_path / "copy.show")
    assert path.read_bytes() == club_path.read_bytes()
    assert copy["meta"]["id"] != original["meta"]["id"]
    assert any(group["name"] == "Script" for group in copy["groups"])
