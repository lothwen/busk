"""Importing a plot from the TUI (MVR plan Phase 4): the file picker's plot
mode and its preview, IMPORT PLOT (``busk_tui.widgets.plot_dialog``), the File
menu's Import plot… and F3's ``[import plot…]``. busk's own check runs on an
:class:`~busk.OfflineShow` behind the fake bridge, on real plot files; the
real engine is in ``test_tui_e2e.py``."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.pilot import Pilot
from textual.widget import Widget
from tui_fakes import FakeBridge, drive, make_app, settle, show_model

from busk_tui import commands
from busk_tui.model import PlotRead, ScriptDone, SessionChanged, SessionState, ShowChanged
from busk_tui.pages.fixtures import FixturesPage
from busk_tui.shell import BuskApp, Importing
from busk_tui.widgets.dialogs import FormDialog
from busk_tui.widgets.file_menu import ITEMS
from busk_tui.widgets.file_picker import Entry, FileDialog, plot_text
from busk_tui.widgets.log import LogView
from busk_tui.widgets.plot_dialog import CHECK_ROWS, PlotDialog, frame_text
from test_rig import CHECK, club, offline, run, two_cells
from test_rig import again as club_v2


def plain(widget: Widget) -> str:
    content = widget.content  # type: ignore[attr-defined]
    return content.plain if isinstance(content, Text) else str(content)


async def until(pilot: Pilot[int], test: Callable[[], bool]) -> None:
    for _ in range(200):
        if test():
            return
        await pilot.pause(0.02)
    raise AssertionError("timed out")


async def choose(pilot: Pilot[int], item: str) -> None:
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


def dialog_of(app: BuskApp) -> PlotDialog:
    screen = app.screen
    assert isinstance(screen, PlotDialog), screen
    return screen


async def open_dialog(pilot: Pilot[int], app: BuskApp, path: Path) -> PlotDialog:
    """Import plot… from the menu, the plot at ``path`` chosen, and busk's check shown."""
    await choose(pilot, "import_plot")
    files = picker_of(app)
    files.go(path.parent, path.name)
    await until(pilot, lambda: not plain(files.preview).endswith("…"))
    await pilot.press("enter")
    await until(pilot, lambda: isinstance(app.screen, PlotDialog))
    dialog = dialog_of(app)
    await until(pilot, lambda: dialog.found is not None and not dialog.checking)
    return dialog


def at(folder: Path) -> SessionChanged:
    return SessionChanged(SessionState(0, 0, False, folder / "club.show"))


def line_of(dialog: PlotDialog) -> str:
    return plain(dialog.line_text).removeprefix("busk> ")


# ------------------------------------------------------------------ the words


def test_rig_import_writes_the_frame_and_cascade_only_where_given() -> None:
    assert commands.rig_import("/p/club.mvr").text == 'rig import "/p/club.mvr"'
    line = commands.rig_import('/p/a "b".mvr', "+y", (0.0, -1500.5, -0.0), cascade=True)
    assert line.text == 'rig import "/p/a \\"b\\".mvr" audience +y origin 0 -1500.5 0 cascade'
    assert commands.rig_import("c.mvr", origin=(0.000001, 1e20, 3)).text == (
        'rig import "c.mvr" origin 0.000001 100000000000000000000 3'
    )
    assert frame_text("-x", (1000.0, 0.0, -0.0)) == "audience -x · origin 1000 0 0 mm"


# ------------------------------------------------------------------ the picker


def test_the_picker_takes_plots_and_previews_what_rig_import_would_do(tmp_path: Path) -> None:
    path = club(tmp_path)
    (path.parent / "notes.txt").write_text("")
    (path.parent / "broken.mvr").write_bytes(b"nope")
    bridge = FakeBridge(show=offline())
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        app.push_screen(FileDialog(path.parent, "club.mvr", "plot"))
        await pilot.pause()
        files = picker_of(app)
        assert files.query_one(".note", Widget) is not None
        assert files.shown == (
            Entry("broken.mvr", False),
            Entry("club.mvr", False),
            Entry("notes.txt", False),
        )
        assert [entry.fits(files.kinds) for entry in files.shown] == [True, True, False]
        await until(pilot, lambda: plain(files.preview) == CHECK)
        await pilot.press("up")
        await until(pilot, lambda: plain(files.preview).startswith("busk cannot import it:"))
        assert "not an MVR file" in plain(files.preview)
        await pilot.press("down", "down")
        assert plain(files.preview) == "not a plot"
        await pilot.press("enter")  # dimmed: nothing
        assert app.screen is files

    drive(app, body)


def test_a_plot_s_preview_is_busk_s_check_or_why_it_cannot_read_it(tmp_path: Path) -> None:
    show = offline()
    found = FakeBridge(show=show).read_plot(club(tmp_path))
    assert plot_text(found).plain == CHECK
    missing = FakeBridge(show=show).read_plot(tmp_path / "gone.mvr")
    assert plot_text(missing).plain.startswith("busk cannot import it:\n[Errno 2]")
    assert FakeBridge().read_plot(tmp_path / "x.mvr").problem == "the show has not started yet"


def test_import_plot_opens_the_picker_in_the_shows_folder(tmp_path: Path) -> None:
    app = make_app(FakeBridge(show=offline()))

    async def body(pilot: Pilot[int]) -> None:
        app.bridge.events.append(at(tmp_path))  # type: ignore[attr-defined]
        await settle(pilot, app)
        await choose(pilot, "import_plot")
        files = picker_of(app)
        assert (files.mode, files.folder) == ("plot", tmp_path)
        await pilot.press("escape")
        await pilot.pause()
        assert app.bridge.lines() == []  # type: ignore[attr-defined]

    drive(app, body)


def test_the_picker_starts_on_the_plot_the_rig_came_from(tmp_path: Path) -> None:
    club(tmp_path)
    app = make_app(FakeBridge(show=offline()))

    async def body(pilot: Pilot[int]) -> None:
        bridge = app.bridge
        bridge.events += [at(tmp_path), ShowChanged(show_model(plot="plots/club.mvr"))]  # type: ignore[attr-defined]
        await settle(pilot, app)
        await choose(pilot, "import_plot")
        files = picker_of(app)
        assert (files.folder, files.current()) == (tmp_path / "plots", Entry("club.mvr", False))
        await pilot.press("escape")
        bridge.events.append(ShowChanged(show_model(plot=str(tmp_path / "plots" / "gone.mvr"))))  # type: ignore[attr-defined]
        await settle(pilot, app)
        await choose(pilot, "import_plot")  # absolute, and gone: its folder
        files = picker_of(app)
        assert (files.folder, files.current()) == (tmp_path / "plots", Entry("club.mvr", False))

    drive(app, body)


# ------------------------------------------------------------------ IMPORT PLOT


def test_the_dialog_starts_from_the_previews_check(tmp_path: Path) -> None:
    path = club(tmp_path)
    asked: list[tuple[Path, str | None]] = []

    class Counting(FakeBridge):
        def read_plot(self, path: Path, audience: str | None = None, *rest: Any) -> PlotRead:
            asked.append((path, audience))
            return super().read_plot(path, audience, *rest)

    app = make_app(Counting(show=offline()))

    async def body(pilot: Pilot[int]) -> None:
        dialog = await open_dialog(pilot, app, path)
        assert asked == [(path, None)]  # the preview's, through the show's frame
        assert plain(dialog.check) == CHECK
        await pilot.press("right")
        await until(pilot, lambda: not dialog.checking)
        assert asked == [(path, None), (path, "+y")]

    drive(app, body)


def test_a_first_import_asks_for_the_frame_and_sends_rig_import(tmp_path: Path) -> None:
    path = club(tmp_path)
    bridge = FakeBridge(show=offline())
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        bridge.events.append(at(tmp_path))
        await settle(pilot, app)
        dialog = await open_dialog(pilot, app, path)
        assert (dialog.first, dialog.audience, dialog.origin) == (True, "-y", (0.0, 0.0, 0.0))
        assert plain(dialog.check) == CHECK
        assert dialog.audience_row.display
        assert dialog.origin_row.display
        assert plain(dialog.origin_text) == "0 0 0 mm"
        assert [b.label.plain for b in dialog.audiences.buttons] == [
            "[-y below]", "[+y above]", "[-x left]", "[+x right]",
        ]  # fmt: skip
        assert app.focused is dialog.audiences
        assert line_of(dialog) == f'rig import "{path}"'
        assert not dialog.send.inert
        assert not dialog.cascade_row.display
        assert not dialog.why.display
        assert plain(dialog.keys) == "← →: audience · o: origin · Enter: import · Esc: cancel"

        await pilot.press("right")  # +y: the plot turned, so the fixtures' span
        await until(pilot, lambda: not dialog.checking)
        assert dialog.audience == "+y"
        assert plain(dialog.check) == run(bridge.show, f'rig check "{path}" audience +y')
        assert plain(dialog.check) != CHECK
        assert line_of(dialog) == f'rig import "{path}" audience +y'

        await pilot.press("o")
        form = app.screen
        assert isinstance(form, FormDialog)
        assert [field.value for field in form.inputs] == ["0", "0", "0"]
        await pilot.press("tab", "ctrl+u", *"-1500", "enter")
        await until(pilot, lambda: app.screen is dialog and not dialog.checking)
        assert dialog.origin == (0.0, -1500.0, 0.0)
        assert plain(dialog.origin_text) == "0 -1500 0 mm"
        words = "audience +y origin 0 -1500 0"
        assert plain(dialog.check) == run(bridge.show, f'rig check "{path}" {words}')
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.lines() == [f'rig import "{path}" {words}']
        assert ("ui", bridge.lines()[0]) in app.query_one(LogView).entries

    drive(app, body)


def test_a_frame_back_where_it_started_has_no_words(tmp_path: Path) -> None:
    path = club(tmp_path)
    app = make_app(FakeBridge(show=offline()))

    async def body(pilot: Pilot[int]) -> None:
        dialog = await open_dialog(pilot, app, path)
        await pilot.click(dialog.audiences, offset=(30, 0))  # -x left
        await until(pilot, lambda: dialog.audience == "-x" and not dialog.checking)
        await pilot.press("left")
        await until(pilot, lambda: dialog.audience == "+y" and not dialog.checking)
        await pilot.press("left")
        await until(pilot, lambda: dialog.audience == "-y" and not dialog.checking)
        assert plain(dialog.check) == CHECK
        assert line_of(dialog) == f'rig import "{path}"'

    drive(app, body)


def test_a_frame_changed_while_busk_checks_is_checked_once_it_is_back(tmp_path: Path) -> None:
    path = club(tmp_path)
    bridge = FakeBridge(show=offline())
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        dialog = await open_dialog(pilot, app, path)
        dialog.pick("+x")
        assert dialog.checking
        assert plain(dialog.why) == "busk is checking the frame shown…"
        assert dialog.send.inert
        dialog.pick("-x")
        assert dialog.stale
        await until(pilot, lambda: not dialog.checking)
        assert (dialog.found and dialog.found.audience, dialog.stale) == ("-x", False)
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.lines()[0].endswith(" audience -x")

    drive(app, body)


def test_a_later_import_shows_the_frame_the_show_keeps(tmp_path: Path) -> None:
    path = club(tmp_path)
    show = offline()
    run(show, f'rig import "{path}" audience +x')
    bridge = FakeBridge(show=show)
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        moved = club_v2(tmp_path, changes={"f101": {"numeric": 101, "at": None}})
        dialog = await open_dialog(pilot, app, moved)
        assert not dialog.first
        assert not dialog.audience_row.display
        assert not dialog.origin_row.display
        assert plain(dialog.frame) == "frame: audience +x · origin 0 0 0 mm, as the show keeps it"
        assert plain(dialog.check) == run(show, f'rig check "{moved}"')
        assert plain(dialog.keys) == "Enter: import · Esc: cancel"
        await pilot.press("right", "o")  # no frame to change
        assert app.screen is dialog
        assert dialog.audience == "+x"
        await pilot.press("enter")
        await settle(pilot, app)
        assert bridge.lines() == [f'rig import "{moved}"']

    drive(app, body)


def test_cascade_is_ticked_when_the_import_needs_it(tmp_path: Path) -> None:
    show = offline()
    run(show, f'rig import "{club(tmp_path)}"')
    gone = club_v2(tmp_path, changes={"f103": None})  # 103 is in group 1
    bridge = FakeBridge(show=show)
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        dialog = await open_dialog(pilot, app, gone)
        assert "  remove 1: 103: used by 1 group, add cascade" in plain(dialog.check)
        assert dialog.cascade_row.display
        assert dialog.tick.reverse  # ticked
        assert line_of(dialog) == f'rig import "{gone}" cascade'
        assert not dialog.send.inert
        assert plain(dialog.keys) == "x: cascade · Enter: import · Esc: cancel"
        await pilot.press("x")
        assert not dialog.tick.reverse
        assert line_of(dialog) == f'rig import "{gone}"'
        assert dialog.send.inert
        assert plain(dialog.why) == "it removes fixtures that something uses: tick cascade"
        assert plain(dialog.cascade_note) == "without cascade busk refuses the import"
        await pilot.press("enter")
        assert app.screen is dialog
        await pilot.click(dialog.tick)
        assert dialog.tick.reverse
        await pilot.click(dialog.send)
        await settle(pilot, app)
        assert bridge.lines() == [f'rig import "{gone}" cascade']

    drive(app, body)


def test_a_blocked_import_cannot_run_and_says_why(tmp_path: Path) -> None:
    show = two_cells(tmp_path)
    run(show, "sel fixture 101.2")
    run(show, 'record group 7 "Second"')
    lose = club_v2(tmp_path, changes={"f101": {"gdtf_mode": "1ch"}})
    app = make_app(FakeBridge(show=show))

    async def body(pilot: Pilot[int]) -> None:
        dialog = await open_dialog(pilot, app, lose)
        blocked = "fixture 101 cannot run 1ch: groups 1, 7 use elements it would lose"
        assert f"  blocked: {blocked}" in plain(dialog.check)
        assert plain(dialog.why) == f"busk refuses this import, even with cascade:\n{blocked}"
        assert dialog.send.inert
        await pilot.press("enter")
        assert app.screen is dialog
        await pilot.press("escape")
        await pilot.pause()
        assert app.bridge.lines() == []  # type: ignore[attr-defined]

    drive(app, body)


def test_a_plot_with_nothing_to_import_cannot_run(tmp_path: Path) -> None:
    path = club(tmp_path)
    show = offline()
    run(show, f'rig import "{path}"')
    app = make_app(FakeBridge(show=show))

    async def body(pilot: Pilot[int]) -> None:
        dialog = await open_dialog(pilot, app, path)
        assert plain(dialog.check).splitlines()[1] == "  nothing to change"
        assert plain(dialog.why) == "nothing to import: the rig is already as the plot has it"
        assert dialog.send.inert
        await pilot.press("enter")
        assert app.screen is dialog

    drive(app, body)


def test_a_plot_busk_cannot_read_says_why_and_cannot_run(tmp_path: Path) -> None:
    broken = tmp_path / "broken.mvr"
    broken.write_bytes(b"nope")
    app = make_app(FakeBridge(show=offline()))

    async def body(pilot: Pilot[int]) -> None:
        dialog = await open_dialog(pilot, app, broken)
        assert not dialog.scroll.display
        assert not dialog.audience_row.display
        assert plain(dialog.why).startswith("busk cannot import it:\nnot an MVR file")
        assert dialog.send.inert

    drive(app, body)


def test_a_long_check_scrolls_in_its_rows(tmp_path: Path) -> None:
    app = make_app(FakeBridge(show=offline()))
    long = "\n".join(f"  note: {n}" for n in range(40))

    async def body(pilot: Pilot[int]) -> None:
        dialog = PlotDialog(tmp_path / "club.mvr", FakeBridge().read_plot(tmp_path / "x"))
        app.push_screen(dialog)
        await pilot.pause()
        dialog.checked(type(dialog.found)(tmp_path / "x", long, changes=True))  # type: ignore[misc]
        await pilot.pause()
        assert dialog.scroll.region.height == CHECK_ROWS
        assert dialog.scroll.max_scroll_y > 0

    drive(app, body)


def test_on_a_small_screen_the_check_gives_up_rows_so_the_buttons_show(tmp_path: Path) -> None:
    app = make_app(FakeBridge(show=offline()))
    long = "\n".join(f"  note: {n}" for n in range(40))

    async def body(pilot: Pilot[int]) -> None:
        dialog = PlotDialog(
            tmp_path / "club.mvr", PlotRead(tmp_path / "club.mvr", long, changes=True)
        )
        app.push_screen(dialog)
        await until(pilot, lambda: dialog.scroll.region.height < CHECK_ROWS)
        await pilot.pause()
        screen = app.screen.region
        assert dialog.scroll.region.height >= 3
        assert screen.contains_region(dialog.send.region)
        assert screen.contains_region(dialog.keys.region)

    drive(app, body, size=(80, 24))


def test_a_check_that_comes_back_after_the_dialog_closed_is_dropped(tmp_path: Path) -> None:
    path = club(tmp_path)
    released = threading.Event()

    class Slow(FakeBridge):
        def read_plot(self, *args: Any) -> PlotRead:
            released.wait(5)
            return super().read_plot(*args)

    bridge = Slow(show=offline())
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        dialog = PlotDialog(path)
        app.push_screen(dialog, lambda line: bridge.sent.append(line))  # type: ignore[arg-type]
        await pilot.pause()
        assert dialog.checking
        await pilot.press("escape")
        await pilot.pause()
        released.set()
        await pilot.pause(0.3)
        assert app.screen is not dialog
        assert bridge.sent == [None]  # type: ignore[comparison-overlap]

    drive(app, body)


# ------------------------------------------------------------------ F3 and the menu


def test_f3s_import_plot_opens_the_picker_and_is_the_first_stop(tmp_path: Path) -> None:
    app = make_app(FakeBridge(show=offline()), page=3)

    async def body(pilot: Pilot[int]) -> None:
        page = app.query_one(FixturesPage)
        assert page.plot_button.label == "import plot…"
        assert [stop.item.label for stop in page.stops()][:3] == ["import plot…", "+ add", "edit"]
        await pilot.click(page.plot_button)
        await pilot.pause()
        assert picker_of(app).mode == "plot"
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("tab", "enter")  # the pane cursor's first stop
        await pilot.pause()
        assert picker_of(app).mode == "plot"

    drive(app, body)


def test_import_plot_waits_for_a_script_that_imports(tmp_path: Path) -> None:
    app = make_app(FakeBridge(show=offline()))

    async def body(pilot: Pilot[int]) -> None:
        app.importing = Importing(9, tmp_path / "rig.busk")
        await choose(pilot, "import_plot")
        assert not isinstance(app.screen, FileDialog)
        assert app.query_one(LogView).entries[-1] == (
            "warning", "rig.busk is importing: import a plot once it ends",
        )  # fmt: skip
        app.take(ScriptDone(9, tmp_path / "rig.busk", True, 1, 1, False, False))
        await choose(pilot, "import_plot")
        assert isinstance(app.screen, FileDialog)

    drive(app, body)


def test_the_line_sent_is_the_one_busk_runs(tmp_path: Path) -> None:
    """The dialog's line, run on the show it checked, imports what it said."""
    path = club(tmp_path)
    show = offline()
    bridge = FakeBridge(show=show)
    app = make_app(bridge)

    async def body(pilot: Pilot[int]) -> None:
        dialog = await open_dialog(pilot, app, path)
        await pilot.press("right")
        await until(pilot, lambda: not dialog.checking)
        span = plain(dialog.check).splitlines()[-1]
        await pilot.press("enter")
        await settle(pilot, app)
        (line,) = bridge.lines()
        assert run(show, line).splitlines()[-1] == span
        assert show.show["stage"]["frame"]["audience"] == "+y"
        assert json.loads(line.split(" ", 2)[2].rsplit(" audience", 1)[0]) == str(path)

    drive(app, body)
