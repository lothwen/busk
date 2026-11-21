"""The launcher (file-menu plan call 15): what ``busk-tui`` shows when it is
given no show. A Textual app of its own, with no show running behind it.

It lists the shows busk-tui ran last (``recent`` in ``state.json``), with a
preview of the one the cursor is on (:class:`RecentShows`), the ones busk
would recover marked (file-menu plan call 24), and offers a new show and a
show from a file. ↑ ↓ move, Enter opens a recent show (not a missing one),
Delete or ``d`` forgets one (call 23), ``n`` makes a new show, ``o`` opens
the file picker, ``q`` or Esc quits. A show chosen is read first, as the TUI's
Open… reads it (file-menu plan call 13): one that busk cannot open is
refused, with why. A new show is written by ``busk new`` in the folder
busk-tui runs in.

The app ends with the show chosen (``None``: quit), and ``busk-tui`` runs it
as the show given (:mod:`busk_tui.app`). It runs again when the TUI closes
its show (file-menu plan call 25), and the show chosen then is opened, as
the TUI opens one.

Imported only once ``TEXTUAL_COLOR_SYSTEM`` is set, as :mod:`busk_tui.shell`.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import ClassVar, cast

from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import OptionList, Static
from textual.worker import get_current_worker

from busk_tui import colors, config
from busk_tui.config import RecentShow
from busk_tui.model import Recovery, ShowRead
from busk_tui.widgets.controls import ReadRecovery, ReadShow
from busk_tui.widgets.dialogs import Choice
from busk_tui.widgets.file_picker import FileDialog, home_text
from busk_tui.widgets.panel import Panel
from busk_tui.widgets.show_dialogs import (
    NO_RECENT,
    NewShowDialog,
    OpenDialog,
    RecentShows,
    new_path,
)


class LauncherScreen(Screen[None]):
    """The launcher's one screen: the recent shows and the choices."""

    DEFAULT_CSS = f"""
    LauncherScreen #bar {{ height: 1; background: {colors.BAR}; }}
    LauncherScreen Panel {{ height: 1fr; }}
    LauncherScreen RecentShows {{ height: 1fr; }}
    LauncherScreen RecentShows .preview {{
        border-left: solid {colors.BORDER}; padding-left: 1;
    }}
    LauncherScreen .none {{ color: {colors.FG}; }}
    LauncherScreen #choices {{ height: 1; margin: 1 1 0 1; }}
    LauncherScreen .choice {{ width: auto; margin-right: 2; }}
    LauncherScreen .choice:hover {{ background: {colors.SEL}; }}
    LauncherScreen #message {{ height: auto; margin: 0 1; color: {colors.RED}; }}
    LauncherScreen .note {{ height: 1; margin: 0 1; color: {colors.DIM}; }}
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("n", "app.new_show", "New show", show=False),
        Binding("o", "app.open_show", "Open", show=False),
        Binding("q,escape,ctrl+c", "app.quit", "Quit", show=False),
    ]

    def __init__(self, shows: Sequence[RecentShow]) -> None:
        super().__init__()
        self.recent = RecentShows(shows)
        self.message = Static("", id="message")  # why a new show was not made

    def compose(self) -> ComposeResult:
        badge = Style(bold=True, color=colors.BG, bgcolor=colors.CYAN)
        yield Static(Text(" busk ", style=badge), id="bar")
        with Panel("Recent shows"):
            if self.recent.list.shows:
                yield self.recent
            else:
                yield Static(NO_RECENT, classes="none")
        with Horizontal(id="choices"):
            yield Choice("n", "New show…", "new_show", colors.GREEN)
            yield Choice("o", "Open…", "open_show", colors.CYAN)
            yield Choice("q", "Quit", "quit", colors.MID)
        yield self.message
        if self.recent.list.shows:
            yield Static("↑ ↓: move · Enter: open · Delete: forget", classes="note")

    def on_recent_shows_emptied(self, event: RecentShows.Emptied) -> None:
        """The last one forgotten: the launcher says there is none."""
        event.stop()
        self.query_one(Panel).mount(Static(NO_RECENT, classes="none"))
        self.query_one(".note").remove()
        self.recent.remove()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        path = self.recent.chosen(event.option_index)
        if path is not None:
            cast(Launcher, self.app).check(path)

    async def on_choice_chosen(self, message: Choice.Chosen) -> None:
        await self.run_action(f"app.{message.value}")


class Launcher(App[Path]):
    """The launcher (see the module docs). ``read``: busk's reading of a
    show file (:func:`busk_tui.bridge.show_read`), called on a worker
    thread; ``recovery``: what busk would recover of one, the same way
    (``None``: the shows it opens recover nothing, so none is marked).
    ``state_dir``: busk's state directory, for ``busk new``'s sACN CID."""

    CSS_PATH = "busk.tcss"
    TITLE = "busk"
    ENABLE_COMMAND_PALETTE = False
    home: LauncherScreen

    def __init__(
        self,
        read: Callable[[Path], ShowRead],
        *,
        recovery: Callable[[Path], Recovery | None] | None = None,
        state_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.read = read
        self.recovery = recovery
        self.state_dir = state_dir

    def get_default_screen(self) -> LauncherScreen:
        self.home = LauncherScreen(config.recent_shows(config.state_path()))
        return self.home

    def on_read_show(self, message: ReadShow) -> None:
        """A show file to preview: busk reads it on a worker thread, and
        ``then`` gets what it found."""
        message.stop()
        self._read_show(message.path, message.then)

    def _read_show(self, path: Path, then: Callable[[ShowRead], None]) -> None:
        read = self.read

        def work() -> None:
            found = read(path)
            if not get_current_worker().is_cancelled:
                self.call_from_thread(then, found)

        self.run_worker(work, thread=True, group="read-show")

    def on_read_recovery(self, message: ReadRecovery) -> None:
        """Recent shows to mark: busk tells, on a worker thread, which it
        would recover, and ``then`` gets each."""
        message.stop()
        recovery, paths, then = self.recovery, message.paths, message.then
        if recovery is None:
            return

        def work() -> None:
            for path in paths:
                found = recovery(path)
                if get_current_worker().is_cancelled:
                    return
                if found is not None:
                    self.call_from_thread(then, path, found)

        self.run_worker(work, thread=True, group="read-recovery")

    def action_new_show(self) -> None:
        """``n``: a form for the title and the file, in the folder busk-tui
        runs in; then ``busk new``, and the new show chosen."""
        folder = Path.cwd()

        def given(values: tuple[str, ...] | None) -> None:
            if values is None:
                return
            path = new_path(folder, values[1])
            assert path is not None  # the form's check
            self._make_show(path, values[0].strip())

        self.push_screen(NewShowDialog(folder), given)

    def action_open_show(self) -> None:
        """``o``: the file picker on show files, in the folder busk-tui runs
        in; then the show chosen is checked (:meth:`check`)."""
        self.push_screen(FileDialog(Path.cwd(), mode="open"), self.check)

    def check(self, path: Path | None) -> None:
        """A show chosen: busk reads it as ``busk run`` would load it, on a
        worker; one that does not load is refused, with why. Else the app
        ends with it."""
        if path is None:
            return

        def found(read: ShowRead) -> None:
            if not read.errors:
                self.exit(path)
                return
            title = f'"{read.title}" ({home_text(path)})' if read.title else home_text(path)
            question = f"{title} cannot be opened:"
            self.push_screen(OpenDialog("OPEN", question, problems=read.errors, running=False))

        self._read_show(path, found)

    def _make_show(self, path: Path, title: str) -> None:
        """``busk new`` on a worker: the template show, with the
        installation's sACN CID; then the app ends with it, or says why
        not."""
        command = config.busk_new_command(path, title, self.state_dir)
        self.home.message.update("")

        def make() -> None:
            done = subprocess.run(command, capture_output=True, text=True, check=False)
            said = done.stderr.strip().removeprefix("busk: ") or "busk new failed"
            self.call_from_thread(made, done.returncode == 0, said)

        def made(ok: bool, said: str) -> None:
            if ok:
                self.exit(path)
            else:
                self.home.message.update(Text(said))

        self.run_worker(make, thread=True, group="new-show")
