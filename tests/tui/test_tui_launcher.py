"""The launcher (file-menu plan call 15): ``busk-tui`` with no show lists the
shows it ran last, with a preview, and offers a new show and a show from a
file; the app ends with the show chosen, read first, or with nothing. A show
can be forgotten (call 23), and the ones busk would recover are marked
(call 24). They are in a box about half the screen's size, under busk's
banner where it fits."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from rich.text import Text
from textual.pilot import Pilot
from textual.widgets import Static

import busk
from busk_tui import colors, config
from busk_tui.bridge import banner, show_read
from busk_tui.launcher import BANNER_RATE, Launcher, LauncherScreen, frame_text
from busk_tui.model import Recovery
from busk_tui.widgets.file_picker import FileDialog
from busk_tui.widgets.show_dialogs import NO_RECENT, NewShowDialog, OpenDialog

NOTE = "↑ ↓: move · Enter: open · Delete: forget"
WRITTEN = datetime(2026, 11, 20, 21, 14, tzinfo=UTC)


def show_at(path: Path, title: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    busk.save_show(busk.new_show(title), path, backups=False)
    return path


def remember(*shows: tuple[Path, str]) -> None:
    """The recent shows, newest first."""
    for path, title in reversed(shows):
        config.remember_show(config.state_path(), path, title)


def drive(
    app: Launcher,
    body: Callable[[Pilot[Path]], Awaitable[None]],
    size: tuple[int, int] = (120, 30),
) -> None:
    async def main() -> None:
        async with app.run_test(size=size) as pilot:
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


def rows(app: Launcher) -> list[str]:
    shown = home(app).recent.list
    return [str(shown.get_option_at_index(i).prompt) for i in range(shown.option_count)]


def style_of(text: Text, word: str) -> str:
    """The style of ``word`` in ``text``."""
    start = text.plain.index(word)
    return next(str(span.style) for span in text.spans if span.start <= start < span.end)


def recovering(marks: dict[Path, Recovery], asked: list[Path]) -> Callable[[Path], Recovery | None]:
    """A recovery reading: what ``marks`` say, each file asked noted."""

    def read(path: Path) -> Recovery | None:
        asked.append(path)
        return marks.get(path)

    return read


def test_without_recent_shows_it_says_so_and_offers_a_new_show_and_a_file() -> None:
    app = Launcher(show_read)

    async def body(pilot: Pilot[Path]) -> None:
        screen = home(app)
        assert NO_RECENT in texts(app)
        assert "[n New show…]" in texts(app)
        assert "[o Open…]" in texts(app)
        assert "[q Quit]" in texts(app)
        assert NOTE not in texts(app)
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
        assert NOTE in texts(app)
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


def test_opening_a_recent_show_leaves_the_state_file_as_it_was(tmp_path: Path) -> None:
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


# ------------------------------------------------------------------ forget


@pytest.mark.parametrize("key", ["delete", "d"])
def test_delete_and_d_forget_the_show_the_cursor_is_on_and_leave_its_file(
    tmp_path: Path, key: str
) -> None:
    club = show_at(tmp_path / "club.show", "Club Night")
    fest = show_at(tmp_path / "fest.show", "Festival")
    late = show_at(tmp_path / "late.show", "Late Night")
    remember((club, "Club Night"), (fest, "Festival"), (late, "Late Night"))
    config.write_state(config.state_path(), page=4, layout="C")
    app = Launcher(show_read)

    async def body(pilot: Pilot[Path]) -> None:
        recent = home(app).recent
        await pilot.press("down", key)
        await pilot.pause()
        assert [show.title for show in recent.list.shows] == ["Club Night", "Late Night"]
        assert [row.split()[:2] for row in rows(app)] == [["Club", "Night"], ["Late", "Night"]]
        assert recent.list.highlighted == 1  # the cursor stays: on the next one
        await until(pilot, lambda: "Late Night" in str(recent.preview.content))
        assert config.recent_shows(config.state_path()) == (
            config.RecentShow(club, "Club Night"),
            config.RecentShow(late, "Late Night"),
        )
        await pilot.press(key)  # the last row: the cursor goes up
        await until(pilot, lambda: "Club Night" in str(recent.preview.content))
        assert [show.title for show in recent.list.shows] == ["Club Night"]
        assert recent.list.highlighted == 0
        await pilot.press("enter")
        await until(pilot, lambda: not app.is_running)

    drive(app, body)
    assert app.return_value == club
    assert fest.is_file()  # not touched
    assert late.is_file()
    remembered = config.read_state(config.state_path())
    assert (remembered["page"], remembered["layout"]) == (4, "C")
    assert [entry["path"] for entry in remembered["recent"]] == [str(club)]


def test_a_missing_show_is_forgotten_too(tmp_path: Path) -> None:
    gone = tmp_path / "gone.show"
    club = show_at(tmp_path / "club.show", "Club Night")
    remember((gone, "Gone"), (club, "Club Night"))
    app = Launcher(show_read)

    async def body(pilot: Pilot[Path]) -> None:
        recent = home(app).recent
        await pilot.press("d")
        await until(pilot, lambda: "Club Night" in str(recent.preview.content))
        assert recent.list.missing == (False,)

    drive(app, body)
    assert config.recent_shows(config.state_path()) == (config.RecentShow(club, "Club Night"),)


def test_forgetting_the_last_recent_show_says_there_is_none(tmp_path: Path) -> None:
    club = show_at(tmp_path / "club.show", "Club Night")
    remember((club, "Club Night"))
    app = Launcher(show_read)

    async def body(pilot: Pilot[Path]) -> None:
        recent = home(app).recent
        recent.action_forget()
        recent.action_forget()  # a second d before the launcher has taken the list away
        await pilot.pause()
        assert NO_RECENT in texts(app)
        assert NOTE not in texts(app)
        assert not home(app).recent.is_attached
        await pilot.press("d", "enter")  # nothing to forget or open
        await pilot.pause()
        assert app.is_running
        await pilot.press("q")
        await until(pilot, lambda: not app.is_running)

    drive(app, body)
    assert app.return_value is None
    assert config.recent_shows(config.state_path()) == ()


# ------------------------------------------------------------------ recovery


def test_the_shows_busk_would_recover_are_marked_and_say_what_comes_back(
    tmp_path: Path,
) -> None:
    club = show_at(tmp_path / "club.show", "Club Night")
    fest = show_at(tmp_path / "fest.show", "Festival")
    late = show_at(tmp_path / "late.show", "Late Night")
    gone = tmp_path / "gone.show"
    remember((club, "Club Night"), (gone, "Gone"), (fest, "Festival"), (late, "Late Night"))
    asked: list[Path] = []
    marks = {club: Recovery(WRITTEN, edits=True), fest: Recovery(WRITTEN, edits=False)}
    app = Launcher(show_read, recovery=recovering(marks, asked))
    when = f"{WRITTEN.astimezone():%Y-%m-%d %H:%M}"

    async def body(pilot: Pilot[Path]) -> None:
        recent = home(app).recent
        await until(pilot, lambda: "recovers" in rows(app)[2])
        assert asked == [club, fest, late]  # once each, not the missing one
        shown = rows(app)
        assert shown[0].split() == ["Club", "Night", "recovers", str(club)]
        assert shown[1].split() == ["Gone", "missing", str(gone)]
        assert shown[3].split() == ["Late", "Night", str(late)]
        prompt = recent.list.get_option_at_index(0).prompt
        assert isinstance(prompt, Text)
        assert style_of(prompt, "recovers") == colors.AMBER
        await until(pilot, lambda: "did not end cleanly" in str(recent.preview.content))
        preview = str(recent.preview.content)
        assert preview.startswith("Club Night\n")  # after what busk reads in the file
        assert preview.endswith(
            f"\n\nIts last run did not end cleanly ({when}): "
            "busk recovers the programmer and its unsaved edits."
        )
        await pilot.press("down", "down")
        await until(pilot, lambda: "Festival" in str(recent.preview.content))
        assert str(recent.preview.content).endswith("busk recovers the programmer.")
        await pilot.press("down")
        await until(pilot, lambda: "Late Night" in str(recent.preview.content))
        assert "did not end cleanly" not in str(recent.preview.content)
        await pilot.press("up", "d")  # forgetting keeps the other marks
        await pilot.pause()
        assert rows(app)[0].split() == ["Club", "Night", "recovers", str(club)]
        assert rows(app)[1].split() == ["Gone", "missing", str(gone)]
        assert rows(app)[2].split() == ["Late", "Night", str(late)]
        await pilot.press("up", "up", "d")
        await pilot.pause()
        assert rows(app)[0].split() == ["Gone", "missing", str(gone)]

    drive(app, body)
    assert asked == [club, fest, late]


def test_a_mark_that_comes_after_the_preview_is_added_to_it(tmp_path: Path) -> None:
    club = show_at(tmp_path / "club.show", "Club Night")
    fest = show_at(tmp_path / "fest.show", "Festival")
    remember((club, "Club Night"), (fest, "Festival"))
    asked, answer = threading.Event(), threading.Event()

    def slow(path: Path) -> Recovery | None:
        asked.set()
        answer.wait(5)
        return Recovery(WRITTEN, edits=False)

    app = Launcher(show_read, recovery=slow)

    async def body(pilot: Pilot[Path]) -> None:
        recent = home(app).recent
        await until(pilot, lambda: "Club Night" in str(recent.preview.content))
        assert asked.is_set()
        await pilot.press("down")
        await until(pilot, lambda: "Festival" in str(recent.preview.content))
        assert "did not end cleanly" not in str(recent.preview.content)
        await pilot.press("up", "d")  # Club Night, forgotten before its mark comes
        await until(pilot, lambda: "Festival" in str(recent.preview.content))
        answer.set()
        await until(pilot, lambda: "did not end cleanly" in str(recent.preview.content))
        assert rows(app)[0].split() == ["Festival", "recovers", str(fest)]
        assert app.is_running

    drive(app, body)


# ------------------------------------------------------------------ the banner


def test_the_banner_plays_over_the_middle_of_a_box_half_the_screen(tmp_path: Path) -> None:
    club = show_at(tmp_path / "club.show", "Club Night")
    remember((club, "Club Night"))
    rates: list[float] = []

    def quick(rate: float) -> tuple[str, ...]:
        """busk's banner, every 20th frame: the first, the last and two between."""
        rates.append(rate)
        return banner(rate)[::20]

    app = Launcher(show_read, banner=quick)

    async def body(pilot: Pilot[Path]) -> None:
        screen = home(app)
        shown = screen.banner
        assert shown is not None
        assert rates == [BANNER_RATE]
        assert shown.display
        assert not screen.badge.display
        assert (shown.rows, shown.columns) == (12, 38)
        box = screen.query_one("#box").region
        assert (box.width, box.height) == (100, 25)  # half of 200 × 50
        assert shown.region.bottom + 1 == box.y  # a row between them
        assert abs(shown.region.center[0] - box.center[0]) <= 0.5
        assert "lighting console engine" not in frame_text(shown.frames[0]).plain
        await until(pilot, lambda: shown.shown == len(shown.frames) - 1)
        assert "lighting console engine" in str(shown.content)
        assert shown.timer is not None
        await pilot.pause(0.2)
        assert shown.shown == len(shown.frames) - 1  # the last stays
        assert screen.recent.list.has_focus

    drive(app, body, size=(200, 50))


def test_where_the_banner_does_not_fit_the_badge_stands_there() -> None:
    app = Launcher(show_read, banner=banner)

    async def body(pilot: Pilot[Path]) -> None:
        screen = home(app)
        assert screen.banner is not None
        assert not screen.banner.display
        assert screen.badge.display
        box = screen.query_one("#box").region
        assert (box.width, box.height) == (80, 12)  # the fewest columns and rows
        await pilot.resize_terminal(120, 30)
        await pilot.pause()
        assert screen.banner.display
        assert not screen.badge.display
        assert screen.query_one("#box").region.size == (80, 15)

    drive(app, body, size=(80, 24))


def test_without_a_banner_the_badge_stands_over_the_box() -> None:
    app = Launcher(show_read)

    async def body(pilot: Pilot[Path]) -> None:
        screen = home(app)
        assert screen.banner is None
        assert screen.badge.display
        assert str(screen.badge.content) == " busk "

    drive(app, body)


def test_a_frame_leaves_out_the_background_its_escapes_reset_to() -> None:
    text = frame_text("\x1b[38;2;1;2;3m\x1b[48;2;4;5;6mA\x1b[49mB\x1b[0m")
    assert text.plain == "AB"

    def styles_at(offset: int) -> list[str]:
        return [str(span.style) for span in text.spans if span.start <= offset < span.end]

    assert any("on #040506" in style for style in styles_at(0))
    assert not any(" on " in style for style in styles_at(1))
    assert any("#010203" in style for style in styles_at(1))
