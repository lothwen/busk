"""The launcher (file-menu plan call 15): ``busk-tui`` with no show lists the
shows it ran last, with a preview, and offers a new show and a show from a
file; the app ends with the show chosen, read first, or with nothing."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from textual.pilot import Pilot
from textual.widgets import Static

import busk
from busk_tui import config
from busk_tui.bridge import show_read
from busk_tui.launcher import Launcher, LauncherScreen
from busk_tui.widgets.file_picker import FileDialog
from busk_tui.widgets.show_dialogs import NO_RECENT, NewShowDialog, OpenDialog


def show_at(path: Path, title: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    busk.save_show(busk.new_show(title), path, backups=False)
    return path


def remember(*shows: tuple[Path, str]) -> None:
    """The recent shows, newest first."""
    for path, title in reversed(shows):
        config.remember_show(config.state_path(), path, title)


def drive(app: Launcher, body: Callable[[Pilot[Path]], Awaitable[None]]) -> None:
    async def main() -> None:
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await body(pilot)

    asyncio.run(main())


async def until(pilot: Pilot[Path], test: Callable[[], object]) -> None:
    for _ in range(200):
        if test():
            return
        await pilot.pause(0.05)
    raise AssertionError("timed out")


def home(app: Launcher) -> LauncherScreen:
    screen = app.screen
    assert isinstance(screen, LauncherScreen), screen
    return screen


def texts(app: Launcher) -> list[str]:
    return [str(widget.content) for widget in app.screen.query(Static)]


def test_without_recent_shows_it_says_so_and_offers_a_new_show_and_a_file() -> None:
    app = Launcher(show_read)

    async def body(pilot: Pilot[Path]) -> None:
        screen = home(app)
        assert NO_RECENT in texts(app)
        assert "[n New show…]" in texts(app)
        assert "[o Open…]" in texts(app)
        assert "[q Quit]" in texts(app)
        assert "↑ ↓: move · Enter: open" not in texts(app)
        assert not screen.recent.is_attached
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_running
        await pilot.press("q")
        await until(pilot, lambda: not app.is_running)

    drive(app, body)
    assert app.return_value is None


def test_it_lists_the_recent_shows_with_a_preview_and_opens_the_one_chosen(
    tmp_path: Path,
) -> None:
    club = show_at(tmp_path / "club.show", "Club Night")
    fest = show_at(tmp_path / "fest.show", "Festival")
    gone = tmp_path / "gone.show"
    remember((club, "Club Night"), (gone, "Gone"), (fest, "Festival"))
    app = Launcher(show_read)

    async def body(pilot: Pilot[Path]) -> None:
        recent = home(app).recent
        assert [show.title for show in recent.list.shows] == ["Club Night", "Gone", "Festival"]
        assert recent.list.missing == (False, True, False)
        row = str(recent.list.get_option_at_index(1).prompt)
        assert row.split() == ["Gone", "missing", str(gone)]
        assert recent.list.has_focus
        assert "↑ ↓: move · Enter: open" in texts(app)
        await until(pilot, lambda: "Club Night" in str(recent.preview.content))
        assert "0 fixtures · 0 cue lists · 0 playbacks" in str(recent.preview.content)
        await pilot.press("down")
        assert str(recent.preview.content) == f"{gone} is gone"
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert app.is_running  # a missing one cannot be opened
        await pilot.press("down")
        await until(pilot, lambda: "Festival" in str(recent.preview.content))
        await pilot.press("enter")
        await until(pilot, lambda: not app.is_running)

    drive(app, body)
    assert app.return_value == fest


def test_a_show_busk_cannot_open_is_refused_and_the_launcher_stays(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{}")
    remember((broken, "Broken"))
    app = Launcher(show_read)

    async def body(pilot: Pilot[Path]) -> None:
        await until(pilot, lambda: "busk cannot open it" in str(home(app).recent.preview.content))
        await pilot.press("enter")
        await until(pilot, lambda: isinstance(app.screen, OpenDialog))
        shown = texts(app)
        assert shown[0] == f"{broken} cannot be opened:"
        assert "schemaVersion" in shown[1]
        assert "The show that runs now goes on." not in shown  # none runs
        assert "[c Close]" in shown
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, LauncherScreen)
        await pilot.press("escape")
        await until(pilot, lambda: not app.is_running)

    drive(app, body)
    assert app.return_value is None


def test_n_makes_a_new_show_in_the_working_folder_and_chooses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    state = tmp_path / "state"
    app = Launcher(show_read, state_dir=state)

    async def body(pilot: Pilot[Path]) -> None:
        await pilot.press("n")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, NewShowDialog)
        assert form.folder == tmp_path
        await pilot.press(*"Late Night", "enter")
        await until(pilot, lambda: not app.is_running)

    drive(app, body)
    made = tmp_path / "late-night.show"
    assert app.return_value == made
    show, _ = busk.load_show(made)
    assert show["meta"]["title"] == "Late Night"
    assert (state / "cid").is_file()  # busk new's sACN CID, from the state directory given


def test_a_new_show_busk_new_refuses_is_said_and_the_launcher_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    refused = [sys.executable, "-c", "import sys; sys.exit('busk: the disk is full')"]
    monkeypatch.setattr(config, "busk_new_command", lambda path, title, state: refused)
    app = Launcher(show_read)

    async def body(pilot: Pilot[Path]) -> None:
        await pilot.press("n")
        await pilot.pause()
        await pilot.press(*"Late Night", "enter")
        message = home(app).message
        await until(pilot, lambda: str(message.content) == "the disk is full")
        assert app.is_running

    drive(app, body)


def test_o_opens_the_file_picker_in_the_working_folder_and_opens_the_show_chosen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    show_at(tmp_path / "club.show", "Club Night")
    fest = show_at(tmp_path / "fest.show", "Festival")
    monkeypatch.chdir(tmp_path)
    app = Launcher(show_read)

    async def body(pilot: Pilot[Path]) -> None:
        await pilot.press("o")
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, FileDialog)
        assert (picker.mode, picker.folder) == ("open", tmp_path)
        await pilot.press(*"fest", "enter")
        await until(pilot, lambda: not app.is_running)

    drive(app, body)
    assert app.return_value == fest


@pytest.mark.parametrize("key", ["q", "escape", "ctrl+c"])
def test_q_esc_and_ctrl_c_quit(key: str) -> None:
    app = Launcher(show_read)

    async def body(pilot: Pilot[Path]) -> None:
        await pilot.press(key)
        await until(pilot, lambda: not app.is_running)

    drive(app, body)
    assert app.return_value is None


def test_the_choices_are_clicks_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = Launcher(show_read)

    async def body(pilot: Pilot[Path]) -> None:
        await pilot.click("#choice-new_show")
        await pilot.pause()
        assert isinstance(app.screen, NewShowDialog)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.click("#choice-open_show")
        await pilot.pause()
        assert isinstance(app.screen, FileDialog)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, LauncherScreen)
        await pilot.click("#choice-quit")
        await until(pilot, lambda: not app.is_running)

    drive(app, body)
    assert app.return_value is None


def test_it_only_reads_the_recent_shows(tmp_path: Path) -> None:
    club = show_at(tmp_path / "club.show", "Club Night")
    remember((club, "Club Night"))
    before = config.state_path().read_text()
    app = Launcher(show_read)

    async def body(pilot: Pilot[Path]) -> None:
        await pilot.press("enter")
        await until(pilot, lambda: not app.is_running)

    drive(app, body)
    assert app.return_value == club
    assert config.state_path().read_text() == before
    assert json.loads(before)["recent"][0]["path"] == str(club)
