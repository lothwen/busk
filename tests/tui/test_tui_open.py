"""Opening another show (file-menu plan Phase 3): New…, Open… and Open
recent… in the File menu, Ctrl+N and Ctrl+O, the show read before it is
opened, the confirmation before the show changes (D2, call 12), and the app
ending with the show to start next (``BuskApp.next_show``)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from textual.pilot import Pilot
from textual.widgets import Input, Static
from tui_fakes import FakeBridge, Reply, drive, settle

import busk
from busk_tui import config
from busk_tui.model import CommandDone, RoutesChanged, RouteView, SessionChanged, SessionState
from busk_tui.shell import BuskApp
from busk_tui.widgets.file_menu import ITEMS
from busk_tui.widgets.file_picker import FileDialog
from busk_tui.widgets.log import LogView
from busk_tui.widgets.show_dialogs import (
    ROWS,
    NewShowDialog,
    OpenDialog,
    RecentDialog,
    file_name,
    new_path,
)


def show_at(path: Path, title: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    busk.save_show(busk.new_show(title), path, backups=False)
    return path


def folder_of_shows(root: Path) -> Path:
    """``root/shows``: ``club.show`` (Club Night) and ``fest.show`` (Festival)."""
    folder = root / "shows"
    show_at(folder / "club.show", "Club Night")
    show_at(folder / "fest.show", "Festival")
    return folder


def make(bridge: FakeBridge, **given: object) -> BuskApp:
    return BuskApp(bridge, config.Settings(), **given)  # type: ignore[arg-type]


def at(path: Path | None, dirty: bool = False) -> SessionChanged:
    return SessionChanged(SessionState(0, 0, dirty=dirty, path=path))


def route(protocol: str, universe: int, state: str | None) -> RouteView:
    return RouteView(protocol, universe, True, state, "", 0)  # type: ignore[arg-type]


async def choose(pilot: Pilot[int], item: str) -> None:
    """Open the File menu with Alt+F and choose ``item``."""
    await pilot.press("alt+f")
    await pilot.pause()
    index = [choice for choice, _, _ in ITEMS].index(item)  # type: ignore[comparison-overlap]
    await pilot.press(*["down"] * index, "enter")
    await pilot.pause()


async def until(pilot: Pilot[int], test: Callable[[], object]) -> None:
    for _ in range(200):
        if test():
            return
        await pilot.pause(0.05)
    raise AssertionError("timed out")


async def pick(pilot: Pilot[int], app: BuskApp, name: str) -> None:
    """In the file picker, open the file ``name``."""
    picker = app.screen
    assert isinstance(picker, FileDialog), picker
    assert picker.mode == "open"
    await pilot.press(*name, "enter")


def texts(app: BuskApp) -> list[str]:
    return [str(widget.content) for widget in app.screen.query(Static)]


def dialog_of(app: BuskApp) -> OpenDialog:
    screen = app.screen
    assert isinstance(screen, OpenDialog), screen
    return screen


# ------------------------------------------------------------------ open


def test_with_nothing_unsaved_and_no_output_ctrl_o_opens_the_show_at_once(
    tmp_path: Path,
) -> None:
    folder = folder_of_shows(tmp_path)
    bridge = FakeBridge()
    app = make(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(at(folder / "club.show"))
        await settle(pilot, app)
        await pilot.press("ctrl+o")
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, FileDialog)
        assert (picker.folder, picker.current()) == (folder, picker.shown[0])  # on club.show
        await pick(pilot, app, "fest")
        await until(pilot, lambda: not app.is_running)

    drive(app, body)
    assert app.next_show == folder / "fest.show"
    assert app.return_value == 0
    assert bridge.lines() == []


@pytest.mark.parametrize("answer", ["c", "o", "s"])
def test_with_unsaved_edits_it_asks_to_save_and_open_open_without_saving_or_cancel(
    tmp_path: Path, answer: str
) -> None:
    folder = folder_of_shows(tmp_path)
    bridge = FakeBridge()
    app = make(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(at(folder / "club.show", dirty=True))
        await settle(pilot, app)
        await choose(pilot, "open")
        await pick(pilot, app, "fest")
        await until(pilot, lambda: isinstance(app.screen, OpenDialog))
        dialog = dialog_of(app)
        assert dialog.border_title is None
        shown = texts(app)
        assert shown[0] == f'Open "Festival" ({folder / "fest.show"})?'
        assert "There are unsaved edits." in shown
        assert "[s Save and open]" in shown
        assert "[o Open without saving]" in shown
        assert "[c Cancel]" in shown
        assert not any("output stops" in text for text in shown)
        await pilot.press(answer)
        await settle(pilot, app)
        if answer != "c":
            await until(pilot, lambda: not app.is_running)

    drive(app, body)
    assert bridge.lines() == (["save"] if answer == "s" else [])
    assert app.next_show == (None if answer == "c" else tmp_path / "shows" / "fest.show")


def test_save_and_open_waits_for_the_save_and_a_failed_save_keeps_the_show(
    tmp_path: Path,
) -> None:
    folder = folder_of_shows(tmp_path)
    bridge = FakeBridge(auto_reply=False)
    app = make(bridge)

    def done(ok: bool) -> CommandDone:
        text = () if ok else ("error: cannot write club.show",)
        return CommandDone(bridge.sent[-1].ticket, "save", "ui", ok, text, 0.0, False)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(at(folder / "club.show", dirty=True))
        await settle(pilot, app)
        for ok in (False, True):
            await pilot.press("ctrl+o")
            await pilot.pause()
            await pick(pilot, app, "fest")
            await until(pilot, lambda: isinstance(app.screen, OpenDialog))
            await pilot.press("s")
            await settle(pilot, app)
            assert bridge.lines()[-1] == "save"
            assert app.is_running  # until the save's reply
            bridge.events.append(done(ok))
            await settle(pilot, app)
            if not ok:
                assert app.is_running
                assert app.next_show is None
                assert ("error", "cannot write club.show") in app.query_one(LogView).entries
        await until(pilot, lambda: not app.is_running)

    drive(app, body)
    assert app.next_show == folder / "fest.show"


def test_live_output_warns_naming_only_the_routes_that_send(tmp_path: Path) -> None:
    folder = folder_of_shows(tmp_path)
    bridge = FakeBridge()
    app = make(bridge)
    sending = (route("sACN", 1, "ok"), route("ArtNet", 2, "disabled"), route("sACN", 3, None),
               route("DMX-USB", 4, "ok"))  # fmt: skip

    async def body(pilot: Pilot[int]) -> None:
        bridge.events += [at(folder / "club.show"), RoutesChanged(sending)]
        await settle(pilot, app)
        await pilot.press("ctrl+o")
        await pilot.pause()
        await pick(pilot, app, "fest")
        await until(pilot, lambda: isinstance(app.screen, OpenDialog))
        shown = texts(app)
        assert (
            "The output stops while the next show starts:\n"
            "2 routes are sending (sACN·U1, DMX-USB·U4)."
        ) in shown
        assert "There are unsaved edits." not in shown
        assert [text for text in shown if text.startswith("[")] == ["[o Open]", "[c Cancel]"]
        await pilot.press("s")  # not offered
        await pilot.pause()
        assert isinstance(app.screen, OpenDialog)
        await pilot.press("o")
        await until(pilot, lambda: not app.is_running)

    drive(app, body)
    assert app.next_show == folder / "fest.show"
    assert bridge.lines() == []


def test_without_a_route_that_sends_there_is_no_warning(tmp_path: Path) -> None:
    folder = folder_of_shows(tmp_path)
    bridge = FakeBridge()
    app = make(bridge)
    quiet = (route("sACN", 1, "failed"), route("sACN", 2, None))

    async def body(pilot: Pilot[int]) -> None:
        bridge.events += [at(folder / "club.show"), RoutesChanged(quiet)]
        await settle(pilot, app)
        await pilot.press("ctrl+o")
        await pilot.pause()
        await pick(pilot, app, "fest")
        await until(pilot, lambda: not app.is_running)

    drive(app, body)
    assert app.next_show == folder / "fest.show"


def test_before_the_session_is_known_it_cannot_tell_and_offers_to_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = folder_of_shows(tmp_path)
    monkeypatch.chdir(folder)
    app = make(FakeBridge())

    async def body(pilot: Pilot[int]) -> None:
        await pilot.press("ctrl+o")
        await pilot.pause()
        await pick(pilot, app, "fest")
        await until(pilot, lambda: isinstance(app.screen, OpenDialog))
        shown = texts(app)
        assert "The TUI cannot tell whether there are unsaved edits." in shown
        assert "[s Save and open]" in shown
        await pilot.press("escape")
        await pilot.pause()
        assert app.is_running

    drive(app, body)
    assert app.next_show is None


def test_a_show_that_does_not_load_is_refused_and_the_show_runs_on(tmp_path: Path) -> None:
    folder = folder_of_shows(tmp_path)
    (folder / "broken.json").write_text("{}")
    bridge = FakeBridge()
    app = make(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(at(folder / "club.show", dirty=True))
        await settle(pilot, app)
        await pilot.press("ctrl+o")
        await pilot.pause()
        await pick(pilot, app, "broken")
        await until(pilot, lambda: isinstance(app.screen, OpenDialog))
        shown = texts(app)
        assert shown[0] == f"{folder / 'broken.json'} cannot be opened:"
        assert "schemaVersion: Field required" in shown[1].splitlines()
        assert shown[2:] == ["The show that runs now goes on.", "[c Close]"]
        await pilot.press("s", "o")  # neither is offered
        await pilot.pause()
        assert isinstance(app.screen, OpenDialog)
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, OpenDialog)
        assert app.is_running

    drive(app, body)
    assert app.next_show is None
    assert bridge.lines() == []


def test_a_tui_whose_host_cannot_start_another_show_says_so(tmp_path: Path) -> None:
    app = make(FakeBridge(), opens=False)

    async def body(pilot: Pilot[int]) -> None:
        for key in ("ctrl+o", "ctrl+n"):
            await pilot.press(key)
            await pilot.pause()
            assert app.screen is app.screen_stack[0]
        await choose(pilot, "open_recent")
        assert app.screen is app.screen_stack[0]
        warnings = [text for kind, text in app.query_one(LogView).entries if kind == "warning"]
        assert len(warnings) == 3
        assert warnings[0].startswith("this TUI cannot open another show: busk-tui SHOW can")

    drive(app, body)


# ------------------------------------------------------------------ new


def test_a_new_shows_file_is_its_title_as_a_file_name_in_a_folder() -> None:
    assert file_name("Late Night") == "late-night.show"
    assert file_name("  Club / Night 2.0 ") == "club-night-2-0.show"
    assert file_name("Fête") == "fête.show"
    assert file_name(" ?! ") == ""
    folder = Path("/s")
    assert new_path(folder, "late.show") == Path("/s/late.show")
    assert new_path(folder, "late") == Path("/s/late.show")
    assert new_path(folder, "late.JSON") == Path("/s/late.JSON")
    assert new_path(folder, "/t/x") == Path("/t/x.show")
    assert new_path(folder, "~/x.show") == Path.home() / "x.show"
    assert new_path(folder, " ") is None
    assert new_path(folder, "/t/") is None


def test_new_writes_the_show_with_busk_new_and_opens_it(tmp_path: Path) -> None:
    folder = folder_of_shows(tmp_path)
    state = tmp_path / "state"
    bridge = FakeBridge()
    app = make(bridge, state_dir=state)
    path = folder / "late-night.show"

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(at(folder / "club.show"))
        await settle(pilot, app)
        await choose(pilot, "new")
        form = app.screen
        assert isinstance(form, NewShowDialog)
        _, file = form.query(Input)
        assert file.value == f"{folder}/"
        await pilot.press(*"Late", "space", *"Night")
        assert file.value == str(path)  # the title as a file name, as it is typed
        await pilot.press("enter")
        await until(pilot, lambda: not app.is_running)
        assert ("info", f"created {path}") in app.query_one(LogView).entries

    drive(app, body)
    assert app.next_show == path
    show, _ = busk.load_show(path)
    assert show["meta"]["title"] == "Late Night"
    cid = (state / "cid").read_text().strip()  # the installation's, in the state given
    assert show["output"]["sacnCid"] == cid
    assert bridge.lines() == []


def test_new_refuses_no_title_and_a_file_that_exists_and_a_typed_file_stays(
    tmp_path: Path,
) -> None:
    folder = folder_of_shows(tmp_path)
    bridge = FakeBridge()
    app = make(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(at(folder / "club.show"))
        await settle(pilot, app)
        await pilot.press("ctrl+n")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, NewShowDialog)
        await pilot.press("enter")
        assert str(form.error.content) == "a title cannot be empty"
        await pilot.press(*"Club", "enter")
        assert str(form.error.content) == (
            f"{folder / 'club.show'} exists: a new show needs a file of its own"
        )
        await pilot.press("tab", "ctrl+u", *"other", "shift+tab", "backspace")
        _, file = form.query(Input)
        assert file.value == "other"  # typed in: it no longer follows the title
        await pilot.press("escape")
        await pilot.pause()
        assert app.is_running
        assert not (folder / "other.show").exists()

    drive(app, body)
    assert app.next_show is None


def test_new_with_unsaved_edits_asks_first_and_writes_nothing_on_cancel(tmp_path: Path) -> None:
    folder = folder_of_shows(tmp_path)
    bridge = FakeBridge()
    app = make(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(at(folder / "club.show", dirty=True))
        await settle(pilot, app)
        await pilot.press("ctrl+n")
        await pilot.pause()
        await pilot.press(*"Late", "enter")
        await pilot.pause()
        dialog = dialog_of(app)
        assert texts(app)[0] == f'Open a new show "Late" ({folder / "late.show"})?'
        assert dialog.dirty
        await pilot.press("c")
        await pilot.pause()
        assert app.is_running

    drive(app, body)
    assert not (folder / "late.show").exists()
    assert app.next_show is None


def test_new_says_why_busk_new_failed_and_the_show_runs_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = folder_of_shows(tmp_path)
    bridge = FakeBridge(replies={"save": Reply(text="saved")})
    app = make(bridge)
    late = folder / "late.show"

    def command(show: Path, title: str, state: Path | None) -> list[str]:
        late.write_text("{}")  # made meanwhile: busk new refuses it
        return real(show, title, state)

    real = config.busk_new_command
    monkeypatch.setattr(config, "busk_new_command", command)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(at(folder / "club.show", dirty=True))
        await settle(pilot, app)
        await pilot.press("ctrl+n")
        await pilot.pause()
        await pilot.press(*"Late", "enter")
        await pilot.pause()
        await pilot.press("s")  # save first
        await until(
            pilot, lambda: any(kind == "error" for kind, _ in app.query_one(LogView).entries)
        )
        errors = [text for kind, text in app.query_one(LogView).entries if kind == "error"]
        assert errors == [f"{str(late)!r} exists; not overwriting it"]
        assert app.is_running

    drive(app, body)
    assert bridge.lines() == ["save"]
    assert app.next_show is None


# ------------------------------------------------------------------ recent


def test_open_recent_lists_the_recent_shows_but_the_one_that_runs(tmp_path: Path) -> None:
    folder = folder_of_shows(tmp_path)
    state = config.state_path()
    config.remember_show(state, folder / "gone.show", "Gone")
    config.remember_show(state, folder / "fest.show", "Festival")
    config.remember_show(state, folder / "club.show", "Club Night")
    bridge = FakeBridge()
    app = make(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(at(folder / "club.show"))
        await settle(pilot, app)
        await choose(pilot, "open_recent")
        dialog = app.screen
        assert isinstance(dialog, RecentDialog)
        assert dialog.recent.size.height == ROWS
        assert [show.title for show in dialog.recent.list.shows] == ["Festival", "Gone"]
        assert dialog.recent.list.missing == (False, True)
        rows = [str(dialog.recent.list.get_option_at_index(i).prompt) for i in range(2)]
        assert rows[1].split() == ["Gone", "missing", str(folder / "gone.show")]
        await until(pilot, lambda: "Festival" in str(dialog.recent.preview.content))
        assert "0 fixtures · 0 cue lists · 0 playbacks" in str(dialog.recent.preview.content)
        await pilot.press("down")
        assert str(dialog.recent.preview.content) == f"{folder / 'gone.show'} is gone"
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is dialog  # a missing one cannot be opened
        await pilot.press("up", "enter")
        await until(pilot, lambda: not app.is_running)

    drive(app, body)
    assert app.next_show == folder / "fest.show"


def test_open_recent_without_recent_shows_says_so(tmp_path: Path) -> None:
    app = make(FakeBridge())

    async def body(pilot: Pilot[int]) -> None:
        await choose(pilot, "open_recent")
        assert isinstance(app.screen, RecentDialog)
        assert texts(app)[0] == "No recent shows: busk-tui lists the shows it opens."
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, RecentDialog)

    drive(app, body)
