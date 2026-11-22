"""The Textual app: the frame, the pages, the keys, and the drain loop.

It talks to the engine only through a :class:`~busk_tui.model.BridgeLike`:
lines go out with ``send`` (after the engine's question, if it has one),
and every 25 ms ``drain`` brings in what changed. Nothing here waits for the
engine (plan §4.1).

Keys (plan §4.4). The prompt always has the keyboard. F1–F9 and Alt+1–9
switch pages, F10 and Alt+0 toggle help, Alt+F opens the File menu, Ctrl+S
saves, Ctrl+N and Ctrl+O start a new show and open one, Esc closes help,
leaves the pane cursor or clears the prompt. On an
empty prompt only: ``?`` toggles help, Tab moves the pane cursor into the
page, Space runs GO on the selected playback, ← → select another, ``[ ]``
move its fader 5 %, and PgUp PgDn change the playback page. Everything else
types.

What the bridge sends goes into one :class:`~busk_tui.pages.base.View`;
after each drain the visible page redraws the parts that changed.

**Another show** (file-menu plan Phase 3): New…, Open… and Open recent… end
the app with :attr:`BuskApp.next_show` set, and the one that started it
starts that show next: ``busk-tui``'s parent process (:mod:`busk_tui.parent`),
or ``--standalone``'s loop. Close (Phase 9) ends it with the launcher next.

**Import plot…** and F3's ``[import plot…]`` (MVR plan Phase 4) choose a
plot in the file picker and show what busk would do with it, in IMPORT
PLOT, before its ``rig import`` line runs.

**Import script…** (file-menu plan Phase 7) runs a script through the bridge:
each line goes to the log as it runs, with its reply, and the hint row is a
bar until it ends. Meanwhile the lines sent wait for it, and another show
cannot open, nor the show close.

Imported only once ``TEXTUAL_COLOR_SYSTEM`` is set (:mod:`busk_tui.app`),
since Textual reads it when it is imported.
"""

from __future__ import annotations

import asyncio
import signal
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final, cast

from rich.text import Text
from textual import events
from textual.actions import SkipAction
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import ContentSwitcher, Input, Static
from textual.worker import get_current_worker

from busk_tui import colors, commands, config, parent
from busk_tui.hints import HelpIndex, complete, hint
from busk_tui.model import (
    Beat,
    BridgeEvent,
    BridgeLike,
    CommandDone,
    DmxChanged,
    EffectsChanged,
    EngineFailed,
    EngineNews,
    EngineRunning,
    EngineStarting,
    EngineStopped,
    HealthChanged,
    InputsChanged,
    LiveChanged,
    LiveState,
    Origin,
    OutputChanged,
    PlotRead,
    ProgrammerChanged,
    ProgrammerModel,
    Recovery,
    RoutesChanged,
    ScriptDone,
    ScriptLine,
    SessionChanged,
    SessionState,
    ShowChanged,
    ShowRead,
    SurfacesChanged,
    TrackingChanged,
)
from busk_tui.nav import PaneCursor
from busk_tui.pages.base import ALL_PARTS, Page, Part, View
from busk_tui.pages.busk import BuskPage, Slots, follow, step, visible_slots
from busk_tui.pages.cues import CuesPage
from busk_tui.pages.effects import EffectsPage
from busk_tui.pages.fixtures import FixturesPage
from busk_tui.pages.masters import MastersPage
from busk_tui.pages.patch import PatchPage
from busk_tui.pages.presets import PresetsPage
from busk_tui.pages.program import ProgramPage
from busk_tui.pages.surfaces import SurfacesPage
from busk_tui.widgets.controls import (
    FillPrompt,
    ReadPlot,
    ReadProfile,
    ReadRecovery,
    ReadShow,
    RunLine,
    ShowHint,
)
from busk_tui.widgets.dialogs import (
    ConfirmDialog,
    QuitChoice,
    QuitDialog,
    TextDialog,
    check_name,
)
from busk_tui.widgets.file_menu import FileChoice, FileMenu
from busk_tui.widgets.file_picker import FileDialog, home_text
from busk_tui.widgets.frame import PAGES, KeyLegend, StatusBar, TabBar
from busk_tui.widgets.help import HelpOverlay
from busk_tui.widgets.log import LogView
from busk_tui.widgets.playbacks import PlaybackRow
from busk_tui.widgets.plot_dialog import PlotDialog
from busk_tui.widgets.profile_picker import ProfileDialog
from busk_tui.widgets.prompt import HintRow, Prompt, PromptRow
from busk_tui.widgets.show_dialogs import (
    NewShowDialog,
    OpenChoice,
    OpenDialog,
    RecentDialog,
    new_path,
)

DRAIN_S: Final = 0.025
BUSY_AFTER_S: Final = 0.3
NARROW: Final = 100
"""Below this many columns, side-by-side panels stack (the ``narrow`` class)."""

LOG_S: Final = 0.2
"""While a script imports, the log's pane is written this often (5 Hz): each
write lays the screen out again, which at every drain made the import take
twice as long (file-menu plan Phase 7)."""

NUDGE_S: Final = 0.5
"""``[ ]`` step from the level they last sent for this long; after it, from
the level the engine shows."""

PAGE_TYPES: Final[dict[int, type[Page]]] = {
    1: BuskPage,
    2: ProgramPage,
    3: FixturesPage,
    4: CuesPage,
    5: EffectsPage,
    6: PresetsPage,
    7: MastersPage,
    8: PatchPage,
    9: SurfacesPage,
}
"""The pages by F-key."""

COLOR_MODES: Final[dict[str | None, colors.ColorMode]] = {"truecolor": "truecolor", "256": "256"}
"""Rich's colour system → how swatches are quantised (else: 16 colours)."""


class FailedScreen(Screen[None]):
    """The show could not start (``--standalone``): why, and ``q`` to quit."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q,escape,ctrl+c", "app.exit(1)", "Quit", priority=True)
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        text = Text("The show did not start\n\n", style=f"bold {colors.RED}")
        text.append(self.message, style=colors.FG)
        text.append("\n\nq to quit", style=colors.DIM)
        yield Static(text, id="failed")


def lines_text(count: int) -> str:
    """``2,189 lines``, ``1 line``."""
    return f"{count:,} line" + ("" if count == 1 else "s")


@dataclass(slots=True)
class Importing:
    """The script Import script… runs: its ticket, its file, and the line of
    the file that ran last, of how many (0 of 0 until the first has run)."""

    ticket: int
    path: Path
    number: int = 0
    total: int = 0


class BuskApp(App[int]):
    """The TUI on one show (see the module docs). ``opens``: whoever runs it
    starts :attr:`next_show` once it ends, so New…, Open… and Close can work.
    ``state_dir``: busk's state directory, for ``busk new``'s sACN CID.
    ``recovery``: what busk would recover of a show file, for Open recent…'s
    marks, called on a worker thread (``None``: the shows opened recover
    nothing, so none is marked)."""

    CSS_PATH = "busk.tcss"
    TITLE = "busk"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS: ClassVar[list[BindingType]] = [
        *(Binding(f"f{n},alt+{n}", f"page({n})", show=False, priority=True) for n in range(1, 10)),
        Binding("f10,alt+0", "toggle_help", show=False, priority=True),
        Binding("alt+f", "file_menu", show=False, priority=True),
        Binding("ctrl+q", "quit_dialog", show=False, priority=True),
    ]
    """The keys that act whatever the prompt holds. The others go to the
    prompt first, which offers them to :meth:`prompt_key` in typing order."""

    def __init__(
        self,
        bridge: BridgeLike,
        settings: config.Settings,
        *,
        standalone: bool = False,
        opens: bool = True,
        state_dir: Path | None = None,
        recovery: Callable[[Path], Recovery | None] | None = None,
    ) -> None:
        super().__init__()
        self.bridge = bridge
        self.settings = settings
        self.standalone = standalone
        self.opens = opens
        self.state_dir = state_dir
        self.recovery = recovery
        self.next_show: Path | parent.Close | None = None  # what starts once the app ends
        self.page = settings.page
        self.view = View(faders=settings.faders, quick=settings.quick, layout=settings.layout)
        self.cursor = PaneCursor()
        self.session: SessionState | None = None
        self._changed: set[Part] = set()  # the parts of the view since the page last drew
        self._slots: Slots = ()  # F1's slots, which the selected playback follows
        self._f1_editing = False  # F1's edit mode: its slots are all the page's
        self._nudged: tuple[int, float, float] | None = None  # [ ]: playback, level, when
        self._help_index: HelpIndex | None = None
        self._interrupted = False  # a Ctrl+C on an empty prompt: the next one quits
        self._quitting: int | None = None  # the ticket of "save and quit"'s save
        self._context_text = ""
        self._fill_note: tuple[str, str] | None = None  # a pre-fill and the hint row's note on it
        self._waiting: dict[int, Callable[[bool], None]] = {}  # ticket → what to call when done
        self._refusals: dict[int, Callable[[str], None]] = {}  # ticket → who says why it failed
        self._keyed: dict[str, int] = {}  # key → the newest ticket with such a callback
        self.importing: Importing | None = None  # the script Import script… runs
        self._bar_moved = False  # a line of it has run since the bar was drawn
        self._log_written = 0.0  # when the held log was last written (monotonic)

    # ------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        with Vertical(id="upper"):
            yield StatusBar(id="status")
            yield TabBar(id="tabs")
            with ContentSwitcher(id="main", initial=f"page-{self.page}"):
                for number, title in PAGES:
                    yield PAGE_TYPES[number](number, title)
            yield LogView(id="log")
            yield HelpOverlay()
        yield PromptRow(id="prompt-row")
        yield HintRow(id="hint")
        yield KeyLegend(id="legend")

    def on_mount(self) -> None:
        self.view.mode = COLOR_MODES.get(self.console.color_system, "16")
        self._show_page()
        self.tabs.show(self.page, False)
        self.prompt.offer = self.prompt_key
        self.prompt.focus()
        self._show_hint()
        self.watch(self.prompt, "selection", self._cursor_moved, init=False)
        for problem in self.settings.problems:
            self.log_view.add("info", problem)
        self.set_interval(DRAIN_S, self.drain)
        self.set_interval(1.0, self.status.tick)  # the clock, and the route lights
        self.set_interval(0.1, self._show_context)
        if self.standalone:
            loop = asyncio.get_running_loop()
            for number in (signal.SIGTERM, signal.SIGHUP):
                loop.add_signal_handler(number, self.exit)
        self.bridge.start()

    def on_resize(self, event: events.Resize) -> None:
        self.screen.set_class(event.size.width < NARROW, "narrow")

    @property
    def status(self) -> StatusBar:
        return self.query_one(StatusBar)

    @property
    def tabs(self) -> TabBar:
        return self.query_one(TabBar)

    @property
    def log_view(self) -> LogView:
        return self.query_one(LogView)

    @property
    def prompt(self) -> Prompt:
        return self.query_one(Prompt)

    @property
    def help_overlay(self) -> HelpOverlay:
        return self.query_one(HelpOverlay)

    @property
    def current_page(self) -> Page:
        return self.query_one(f"#page-{self.page}", Page)

    @property
    def live(self) -> LiveState | None:
        return self.view.live

    @property
    def programmer(self) -> ProgrammerModel | None:
        return self.view.programmer

    @property
    def playback(self) -> int:
        """The selected playback (Space, ``[ ]``)."""
        return self.view.playback

    # ------------------------------------------------------------ events

    def drain(self) -> None:
        """Take in what the bridge has sent since the last drain, and redraw
        what changed on the page. Not once the app is closing (its timers
        still run while its screens are taken down)."""
        if not self.is_running:
            return
        for event in self.bridge.drain():
            self.take(event)
        if self._bar_moved:
            self._bar_moved = False
            self._show_bar()
        if self.importing is not None and time.monotonic() - self._log_written >= LOG_S:
            self.log_view.flush(hold=True)
            self._log_written = time.monotonic()
        self._redraw()

    def _redraw(self) -> None:
        changed = self._changed
        if not changed:
            return
        self._changed = set()
        if changed & {"show", "live"} and self._follow_slots():
            changed.add("playback")
        self.current_page.update_view(self.view, frozenset(changed))

    def _follow_slots(self) -> bool:
        """F1's slots as they are now, which ← → step along: every slot of
        the page while F1 edits, as its grid shows them, else the first
        ``faders``. Whether the selection moved, as :func:`follow` moves it."""
        cap = None if self._f1_editing else self.view.faders
        slots = visible_slots(self.view.show, self.view.live, cap)
        if slots == self._slots:
            return False
        chosen = follow(self.view.playback, self._slots, slots)
        self._slots = slots
        if chosen == self.view.playback:
            return False
        self.view.playback = chosen
        return True

    def take(self, event: BridgeEvent) -> None:
        match event:
            case EngineStarting():
                self.status.engine = "starting"
                self.status.refresh()
            case EngineRunning(title=title, warnings=warnings):
                self.status.title = title
                self.status.refresh()
                self._banner(title)
                for warning in warnings:
                    self.log_view.add("warning", warning)
            case EngineFailed(message=message):
                self.push_screen(FailedScreen(message))
            case EngineStopped():
                pass
            case CommandDone():
                self._done(event)
            case LiveChanged(state=state):
                self.view.live = self.status.live = state
                self.status.refresh()
                self._changed.add("live")
            case Beat(beats=beats):
                self.status.set_beats(beats[0] if beats else None)
                self.view.beats = beats
                self._changed.add("beats")
            case ShowChanged(show=show):
                self.status.title = show.title
                self.status.refresh()
                self.view.show = show
                self._changed.add("show")
                for screen in self.screen_stack:  # a profile imported there shows at once
                    if isinstance(screen, ProfileDialog):
                        screen.offer(show.choices)
            case ProgrammerChanged(programmer=programmer):
                self.view.programmer = self.status.programmer = programmer
                self.status.refresh()
                self._changed.add("programmer")
            case EffectsChanged(effects=effects):
                self.view.effects = effects
                self._changed.add("effects")
            case OutputChanged(output=output):
                self.view.output = output
                self._changed.add("output")
            case DmxChanged(dmx=dmx):
                self.view.dmx = dmx
                self._changed.add("dmx")
            case TrackingChanged(sheet=sheet):
                self.view.tracking = sheet
                self._changed.add("tracking")
            case RoutesChanged(routes=routes):
                self.status.set_routes(routes)
                self.view.routes = routes
                self._changed.add("routes")
            case SurfacesChanged(surfaces=surfaces):
                self.view.surfaces = surfaces
                self._changed.add("surfaces")
            case InputsChanged(inputs=inputs):
                self.view.inputs = inputs
                self._changed.add("inputs")
            case HealthChanged(state=state, late=late):
                self.status.engine, self.status.late = state, late
                self.status.refresh()
            case SessionChanged(session=session):
                before = None if self.session is None else self.session.path
                self.session = self.status.session = session
                self.status.refresh()
                if session.path is not None and session.path != before:
                    # the show it runs, or the copy a save as made: a recent show
                    config.remember_show(config.state_path(), session.path, self.status.title)
            case EngineNews(level=level, text=text):
                self.log_view.add(level, text)
            case ScriptLine():
                self._script_line(event)
            case ScriptDone():
                self._script_done(event)

    def _banner(self, title: str) -> None:
        how = "standalone" if self.standalone else "under busk run"
        self.log_view.add(
            "info",
            f"busk-tui on {title!r} ({how}): F1–F9 pages · F10 or ? help · Tab completes · "
            "Ctrl+C twice quits",
        )
        if self.standalone:
            self.log_view.add(
                "info",
                "standalone has no watchdog, autosave or crash recovery: "
                "for a show, start busk-tui without --standalone",
            )

    def _done(self, done: CommandDone) -> None:
        callback = self._waiting.pop(done.ticket, None)
        refused = self._refusals.pop(done.ticket, None)
        if callback is not None:
            for key, ticket in list(self._keyed.items()):
                if ticket == done.ticket:
                    del self._keyed[key]
            callback(done.ok)
        if done.origin == "internal":
            return
        if done.ticket == self._quitting:
            self._quitting = None
            if done.ok:
                self.exit(0)
                return
        if done.ok and done.line.split()[:1] == ["help"]:
            self.open_help(done.lines)
        else:
            said = self._log_reply(done.ok, done.lines)
            if not done.ok and refused is not None:
                refused(said)
        if done.quit:
            self.action_quit_dialog()

    def _log_reply(self, ok: bool, lines: Sequence[str]) -> str:
        """A line's reply in the log, a result, or an error without busk's
        mark of a refused line; the text shown."""
        if ok:
            if lines:
                self.log_view.add("result", "\n".join(lines))
            return "\n".join(lines)
        shown = list(lines) or ["failed"]
        shown[0] = shown[0].removeprefix("error: ")
        self.log_view.add("error", "\n".join(shown))
        return "\n".join(shown)

    def _script_line(self, line: ScriptLine) -> None:
        """A line of the script Import script… runs: in the log with its
        place (``festival.busk:812``) and its reply, as a typed line is,
        unless it is blank or a comment; and the bar moves on."""
        importing = self.importing
        if importing is None or line.ticket != importing.ticket:
            return
        importing.number, importing.total = line.number, line.total
        self._bar_moved = True
        if line.line and not line.line.startswith("#"):
            self.log_view.add("ui", f"{importing.path.name}:{line.number}  {line.line}")
            self._log_reply(line.ok, line.lines)

    def _script_done(self, done: ScriptDone) -> None:
        """The script has ended: what happened, in the log; the hint row is
        the hint again. A ``quit`` line in it opens the quit dialog, as from
        a script ``source`` runs."""
        importing = self.importing
        if importing is None or done.ticket != importing.ticket:
            return
        self.importing = None
        self.log_view.flush()
        if done.problem is not None:
            self.log_view.add("error", done.problem)
        elif done.ok:
            ran = lines_text(done.total)
            if done.quit:
                ran = f"{done.number:,} of {ran}, to its quit"
            undo = " (Ctrl+Z undoes it)" if done.stepped else ""
            self.log_view.add("info", f"imported {done.path.name}: {ran}{undo}")
        else:
            undo = " (Ctrl+Z undoes the lines before it)" if done.stepped else ""
            self.log_view.add("error", f"stopped at line {done.number:,} of {done.total:,}{undo}")
        self._show_hint()
        if done.quit:
            self.action_quit_dialog()

    # ---------------------------------------------------------- the lines

    def run_line(
        self,
        line: str,
        origin: Origin,
        key: str | None = None,
        performance: bool = False,
        done: Callable[[bool], None] | None = None,
        ask: str | None = None,
        refused: Callable[[str], None] | None = None,
    ) -> None:
        """Send ``line``: after the engine's question, if it asks one (not
        for a control's keyed moves), else after ``ask``, the TUI's own;
        echoed unless ``internal``. ``done`` is called with the line's
        success once it has run, and ``refused`` with busk's reply if it was
        refused."""
        question = None if key is not None else self.bridge.confirmation(line)
        if question is None:
            question = ask
        if question is None:
            self._send(line, origin, key, performance, done, refused)
            return

        def answered(yes: bool | None) -> None:
            if yes:
                self._send(line, origin, key, performance, done, refused)
            else:
                self.log_view.add("info", f"cancelled: {line}")

        self.push_screen(ConfirmDialog(question, line), answered)

    def _send(
        self,
        line: str,
        origin: Origin,
        key: str | None,
        performance: bool,
        done: Callable[[bool], None] | None = None,
        refused: Callable[[str], None] | None = None,
    ) -> int:
        if origin != "internal":
            self.log_view.add("typed" if origin == "typed" else "ui", line)
        ticket = self.bridge.send(line, origin, key=key, performance=performance)
        if refused is not None:
            self._refusals[ticket] = refused
        if done is not None:
            if key is not None:  # a newer keyed line replaces the older if unsent: forget it
                older = self._keyed.pop(key, None)
                if older is not None:
                    self._waiting.pop(older, None)
                self._keyed[key] = ticket
            self._waiting[ticket] = done
        return ticket

    def on_playback_row_chosen(self, message: PlaybackRow.Chosen) -> None:
        message.stop()
        self._select_playback(message.number)

    def on_run_line(self, message: RunLine) -> None:
        message.stop()
        self._disarm()
        line = message.line
        self.run_line(
            line.text,
            message.origin,
            message.key,
            line.performance,
            message.done,
            message.ask,
            message.refused,
        )

    def on_read_profile(self, message: ReadProfile) -> None:
        """A profile file to show before it is imported (the file picker):
        busk reads it on a worker thread, and ``then`` gets what it found."""
        message.stop()
        bridge, path, then = self.bridge, message.path, message.then

        def read() -> None:
            found = bridge.read_profile(path)
            if not get_current_worker().is_cancelled:
                self.call_from_thread(then, found)

        self.run_worker(read, thread=True, group="read-profile")

    def on_read_plot(self, message: ReadPlot) -> None:
        """A plot to check before it is imported (the file picker, IMPORT
        PLOT): busk reads it on a worker thread, and ``then`` gets what
        ``rig import`` would do."""
        message.stop()
        bridge, then = self.bridge, message.then
        path, audience, origin = message.path, message.audience, message.origin

        def read() -> None:
            found = bridge.read_plot(path, audience, origin)
            if not get_current_worker().is_cancelled:
                self.call_from_thread(then, found)

        self.run_worker(read, thread=True, group="read-plot")

    def on_read_show(self, message: ReadShow) -> None:
        """A show file to show before it is opened (the file picker, Open
        recent…): busk reads it on a worker thread, and ``then`` gets what it
        found."""
        message.stop()
        self._read_show(message.path, message.then)

    def _read_show(self, path: Path, then: Callable[[ShowRead], None]) -> None:
        bridge = self.bridge

        def read() -> None:
            found = bridge.read_show(path)
            if not get_current_worker().is_cancelled:
                self.call_from_thread(then, found)

        self.run_worker(read, thread=True, group="read-show")

    def on_read_recovery(self, message: ReadRecovery) -> None:
        """Recent shows to mark (Open recent…): busk tells, on a worker
        thread, which it would recover, and ``then`` gets each."""
        message.stop()
        recovery, paths, then = self.recovery, message.paths, message.then
        if recovery is None:
            return

        def read() -> None:
            for path in paths:
                found = recovery(path)
                if get_current_worker().is_cancelled:
                    return
                if found is not None:
                    self.call_from_thread(then, path, found)

        self.run_worker(read, thread=True, group="read-recovery")

    def on_fill_prompt(self, message: FillPrompt) -> None:
        """A pre-fill from a page: the text goes in the prompt, to finish."""
        message.stop()
        self._disarm()
        self._leave_cursor()
        self._fill_note = None if message.note is None else (message.text, message.note)
        self.prompt.value = message.text
        self.prompt.cursor_position = len(message.text)
        self.prompt.focus()

    def on_show_hint(self, message: ShowHint) -> None:
        """What is under the mouse, in the hint row (F8's DMX cells, F6's
        panel buttons)."""
        message.stop()
        if message.text is None:
            self._show_hint()
        elif self.importing is None:  # else the bar keeps the row
            self.query_one(HintRow).show_text(message.text, colors.MID)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        line = event.value.strip()
        self.prompt.remember(line)
        self.prompt.clear_line()
        if line:
            self.run_line(line, "typed")

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self._disarm()
        if event.value and self.cursor.active:
            self._leave_cursor()
        self._show_hint()

    def _cursor_moved(self, _selection: object) -> None:
        self._show_hint()

    def _show_hint(self) -> None:
        if self.importing is not None:  # the bar takes the hint row's place
            self._show_bar()
            return
        prompt = self.prompt
        if self._fill_note is not None:  # a pre-fill's note, until the line changes
            if prompt.value == self._fill_note[0]:
                self.query_one(HintRow).show_text(self._fill_note[1])
                return
            self._fill_note = None
        before = prompt.value[: prompt.cursor_position]
        if self._help_index is None and self.bridge.help_lines:
            self._help_index = HelpIndex(self.bridge.help_lines)
        completion = self.bridge.expected(before) if before.strip() else None
        self.query_one(HintRow).show(hint(self._help_index, before, completion))

    def _show_bar(self) -> None:
        """The import bar in the hint row, while a script imports; not over
        Ctrl+C's word on quitting, which stays until it is disarmed."""
        importing = self.importing
        if importing is not None and not self._interrupted:
            hint_row = self.query_one(HintRow)
            hint_row.show_import(importing.path.name, importing.number, importing.total)

    def _show_context(self) -> None:
        """The prompt's right side: busy line, selection, page, playback, undo."""
        if not self.is_running:
            return
        parts: list[str] = []
        busy = self.bridge.busy
        if busy is not None:
            seconds = time.monotonic() - busy.since
            if seconds >= BUSY_AFTER_S:
                shown = busy.line if len(busy.line) <= 24 else busy.line[:23] + "…"
                parts.append(f"⧗ {shown} {seconds:.1f}s")
        if self.programmer is not None:
            parts.append(f"sel {len(self.programmer.selection)}")
        if self.live is not None and self.live.page is not None:
            parts.append(f"page {self.live.page.number}")
        parts.append(f"P{self.view.playback}")
        if self.session is not None:
            parts.append(f"undo {self.session.undo}")
        text = " · ".join(parts)
        if text != self._context_text:
            self._context_text = text
            self.query_one("#context", Static).update(text)

    # ------------------------------------------------------------ actions

    def _modal(self) -> bool:
        return isinstance(self.screen, ModalScreen | FailedScreen)

    def _disarm(self) -> None:
        if self._interrupted:
            self._interrupted = False
            self._show_hint()

    def action_page(self, number: int) -> None:
        if self._modal():
            raise SkipAction
        self._disarm()
        self._leave_cursor()
        if self.help_overlay.is_open:
            self.close_help()
        self.page = number
        self.query_one(ContentSwitcher).current = f"page-{number}"
        self.tabs.show(number, False)
        self._show_page()
        self._show_hint()  # not what was under the mouse on the page before

    def _show_page(self) -> None:
        """The page just shown: what the bridge reads for it, and all of it drawn."""
        page = self.current_page
        output, effects = page.watches(self.view)
        self.bridge.watch(
            output=output, effects=effects, dmx=page.WATCH_DMX, inputs=page.WATCH_INPUTS
        )
        self.bridge.track(page.tracks())
        self._changed |= ALL_PARTS
        self._redraw()

    def action_layout(self, layout: str) -> None:
        """F1's layout switch (a click, or the pane cursor): A the console,
        B the stack, C the stage. The pane cursor stays where it was."""
        if layout not in config.LAYOUTS or layout == self.view.layout:
            return
        self.view.layout = cast(config.Layout, layout)
        label = None if self.cursor.current is None else self.cursor.current.label
        if self.page == 1:
            self._show_page()
        if label is not None:
            self.cursor.follow(self.current_page.items(), label)
            self.current_page.show_cursor(self.cursor.index)

    def on_busk_page_layout_chosen(self, message: BuskPage.LayoutChosen) -> None:
        message.stop()
        self.action_layout(message.layout)

    def on_busk_page_editing_changed(self, message: BuskPage.EditingChanged) -> None:
        message.stop()
        self._f1_editing = message.editing
        if self._follow_slots():
            self._changed.add("playback")
            self._redraw()
            self._show_context()

    def on_patch_page_add_here(self, message: PatchPage.AddHere) -> None:
        """F8's ``[add fixture here…]``: F3, with the new fixture form at that place."""
        message.stop()
        page = self.query_one(FixturesPage)
        self.action_page(page.number)
        page.add_fixture((message.universe, message.address))

    def on_page_watches_changed(self, message: Page.WatchesChanged) -> None:
        """A page now watches other parts (F6's edit mode, F4's list):
        the bridge reads them if it is the page shown."""
        message.stop()
        if message.page is self.current_page:
            output, effects = message.page.watches(self.view)
            page = message.page
            self.bridge.watch(
                output=output, effects=effects, dmx=page.WATCH_DMX, inputs=page.WATCH_INPUTS
            )
            self.bridge.track(message.page.tracks())

    def action_toggle_help(self) -> None:
        if self._modal():
            raise SkipAction
        self._disarm()
        if self.help_overlay.is_open:
            self.close_help()
        else:
            self.open_help(self.bridge.help_lines)

    def action_rename_show(self) -> None:
        """A click on the status bar's title: a name dialog, then ``rename
        show "…"``; nothing for the title it has, or before a show is there."""
        if self._modal():
            raise SkipAction
        self._disarm()
        if self.view.show is None:
            return
        title = self.view.show.title

        def given(text: str | None) -> None:
            if text is not None and text.strip() != title:
                self._run(commands.rename_show(text.strip()))

        self.push_screen(TextDialog("RENAME SHOW", title, check_name(True)), given)

    def action_file_menu(self) -> None:
        """A click on the badge, or Alt+F: the File menu; Alt+F again closes it."""
        if isinstance(self.screen, FileMenu):
            self.screen.dismiss(None)
            return
        if self._modal():
            raise SkipAction
        self._disarm()
        self.push_screen(FileMenu(), self._file_chosen)

    def _file_chosen(self, choice: FileChoice | None) -> None:
        match choice:
            case "new":
                self.new_show()
            case "open":
                self.open_show()
            case "open_recent":
                self.open_recent()
            case "save":  # even with nothing unsaved: harmless
                self._run(commands.save())
            case "save_as":
                self.save_as()
            case "import_script":
                self.import_script()
            case "import_profile":
                self.import_profile()
            case "import_plot":
                self.import_plot()
            case "close":
                self.close_show()
            case "quit":
                self.action_quit_dialog()

    def save_as(self) -> None:
        """Save as…: the file picker, saving, in the show's folder on its
        file's name; then ``save "<path>"``, after a question if it replaces a
        file, or ``save`` for the show's own file."""
        own = None if self.session is None else self.session.path
        folder, name = (Path.cwd(), "") if own is None else (own.parent, own.name)

        def chosen(path: Path | None) -> None:
            if path is None:
                return
            if own is not None and path.resolve() == own.resolve():
                self._run(commands.save())
                return
            line = commands.save_as(str(path))
            ask = f"Replace {path.name}? busk keeps a backup of it." if path.exists() else None
            self.run_line(line.text, "ui", ask=ask)

        self.push_screen(FileDialog(folder, name, "save", own), chosen)

    def import_script(self) -> None:
        """Import script…: a ``.busk`` file from the file picker, in the
        show's folder; then the bridge runs it (:meth:`start_import`). Not
        while another imports."""
        if self._held("import another script"):
            return
        own = None if self.session is None else self.session.path
        folder = Path.cwd() if own is None else own.parent

        def chosen(path: Path | None) -> None:
            if path is not None:
                self.start_import(path)

        self.push_screen(FileDialog(folder, mode="script"), chosen)

    def start_import(self, path: Path) -> None:
        """Run the script at ``path`` through the bridge, after the lines
        sent before it, as one undo step: its lines go to the log as they
        run, and the hint row is its bar until it ends (file-menu plan
        calls 20 and 21)."""
        self.importing = Importing(self.bridge.run_script(path), path)
        self.log_view.add("info", f"importing {home_text(path)}")
        self.log_view.hold()  # its lines reach the pane 5 times a second
        self._log_written = time.monotonic()
        self._show_hint()

    def import_profile(self) -> None:
        """Import profile…: the profile picker's file picker, on the profile
        file chosen last in this run, else in the show's folder; then
        ``profile import "<path>"``, whose reply goes to the log."""
        last = ProfileDialog.last
        if last is not None:
            files = FileDialog(last.parent, last.name)
        else:
            own = self._own_file()
            files = FileDialog(Path.cwd() if own is None else own.parent)

        def chosen(path: Path | None) -> None:
            if path is not None:
                ProfileDialog.last = path
                self._run(commands.profile_import(str(path)))

        self.push_screen(files, chosen)

    def import_plot(self) -> None:
        """Import plot… and F3's ``[import plot…]`` (MVR plan Phase 4): the
        file picker on plots, on the plot the rig came from if the show has
        one, else in the show's folder; then IMPORT PLOT, which has busk
        check it, and the ``rig import`` line it closes with. Not while a
        script imports: its check would be of a show still changing."""
        if self._held("import a plot"):
            return
        own = self._own_file()
        home = Path.cwd() if own is None else own.parent
        stored = None if self.view.show is None else self.view.show.plot
        if stored is not None:
            plot = home / stored  # relative to the show's folder, or absolute
            files = FileDialog(plot.parent, plot.name, "plot")
        else:
            files = FileDialog(home, mode="plot")

        def chosen(path: Path | None) -> None:
            if path is None:
                return
            found = files.read.get(path)  # the preview's check, through the show's frame
            self.push_screen(
                PlotDialog(path, found if isinstance(found, PlotRead) else None), self._run_plot
            )

        self.push_screen(files, chosen)

    def _run_plot(self, line: commands.Line | None) -> None:
        if line is not None:
            self.run_line(line.text, "ui")

    def on_fixtures_page_import_plot(self, message: FixturesPage.ImportPlot) -> None:
        message.stop()
        self.import_plot()

    def _held(self, what: str) -> bool:
        """Whether a script imports, which ``what`` waits for: the log says
        so, and nothing is done (file-menu plan call 21)."""
        if self.importing is None:
            return False
        name = self.importing.path.name
        self.log_view.add("warning", f"{name} is importing: {what} once it ends")
        return True

    # ------------------------------------------------------ another show

    def new_show(self) -> None:
        """New…: a form for the title and the file, in the show's folder;
        then the confirmation, ``busk new`` (:meth:`_make_show`), and the new
        show opened."""
        if not self._can_open("start a new show"):
            return
        own = self._own_file()
        folder = Path.cwd() if own is None else own.parent

        def given(values: tuple[str, ...] | None) -> None:
            if values is None:
                return
            title, path = values[0].strip(), new_path(folder, values[1])
            assert path is not None  # the form's check
            question = f'Open a new show "{title}" ({home_text(path)})?'
            self._confirm_open("NEW SHOW", question, lambda: self._make_show(path, title))

        self.push_screen(NewShowDialog(folder), given)

    def open_show(self) -> None:
        """Open…: the file picker on show files, in the show's folder, on its
        file; then the show chosen is checked (:meth:`_check_open`)."""
        if not self._can_open("open another show"):
            return
        own = self._own_file()
        folder, name = (Path.cwd(), None) if own is None else (own.parent, own.name)
        self.push_screen(FileDialog(folder, name, "open"), self._check_open)

    def open_recent(self) -> None:
        """Open recent…: the recent shows but the one that runs; then the
        show chosen is checked (:meth:`_check_open`)."""
        if not self._can_open("open another show"):
            return
        own = self._own_file()
        shows = [show for show in config.recent_shows(config.state_path()) if show.path != own]
        self.push_screen(RecentDialog(shows), self._check_open)

    def close_show(self) -> None:
        """Close: back to the launcher (file-menu plan call 25), after the
        confirmation, worded for closing."""
        if not self._can_open("close the show"):
            return
        named = "the show" if self.view.show is None else f'"{self.view.show.title}"'
        own = self._own_file()
        if own is not None:
            named += f" ({home_text(own)})"
        question = f"Close {named} and go back to the launcher?"
        self._confirm_open("CLOSE", question, lambda: self._open(parent.CLOSE), closing=True)

    def _own_file(self) -> Path | None:
        return None if self.session is None else self.session.path

    def _can_open(self, what: str) -> bool:
        if not self.opens:
            self.log_view.add(
                "warning",
                f"this TUI cannot {what}: busk-tui SHOW can, "
                "not busk run --frontend busk_tui.app:frontend",
            )
        return self.opens and not self._held(what)

    def _check_open(self, path: Path | None) -> None:
        """A show chosen to open: busk reads it as ``busk run`` would load
        it, on a worker; one that does not load is refused, with why, and the
        show that runs goes on. Else the confirmation, and the show opened."""
        if path is None:
            return

        def found(read: ShowRead) -> None:
            title = f'"{read.title}" ({home_text(path)})' if read.title else home_text(path)
            if read.errors:
                question = f"{title} cannot be opened:"
                self.push_screen(OpenDialog("OPEN", question, problems=read.errors))
            else:
                self._confirm_open("OPEN", f"Open {title}?", lambda: self._open(path))

        self._read_show(path, found)

    def _confirm_open(
        self, title: str, question: str, then: Callable[[], None], closing: bool = False
    ) -> None:
        """Before the show changes (D2), or ``closing`` it: ``then`` at once,
        unless there are unsaved edits (or the TUI cannot tell) or a route
        sends; then the confirmation first, which may save and wait for the
        save, as Save and quit does. A failed save keeps the show that runs."""
        dirty = None if self.session is None else self.session.dirty
        sending = [f"{r.protocol}·U{r.universe}" for r in self.view.routes if r.state == "ok"]
        if dirty is False and not sending:
            then()
            return

        def saved(ok: bool) -> None:
            if ok:
                then()

        def chosen(choice: OpenChoice | None) -> None:
            if choice == "save":
                line = commands.save()
                self._send(line.text, "ui", None, line.performance, saved)
            elif choice == "open":
                then()

        self.push_screen(OpenDialog(title, question, dirty, sending, closing=closing), chosen)

    def _make_show(self, path: Path, title: str) -> None:
        """``busk new`` on a worker: the template show, with the
        installation's sACN CID; then it is opened, or the log says why not
        and the show that runs goes on."""
        command = config.busk_new_command(path, title, self.state_dir)

        def make() -> None:
            done = subprocess.run(command, capture_output=True, text=True, check=False)
            said = (done.stdout if done.returncode == 0 else done.stderr).strip()
            self.call_from_thread(made, done.returncode == 0, said)

        def made(ok: bool, said: str) -> None:
            if ok:
                self.log_view.add("info", said)
                self._open(path)
            else:
                self.log_view.add("error", said.removeprefix("busk: ") or "busk new failed")

        self.run_worker(make, thread=True, group="new-show")

    def _open(self, show: Path | parent.Close) -> None:
        """End the app, for ``show`` to start next, or the launcher
        (:data:`~busk_tui.parent.CLOSE`); not while a script imports (one
        started while the show was read, made or saved)."""
        if self._held("close the show" if show is parent.CLOSE else "open another show"):
            return
        self.next_show = show
        self.exit(0)

    def open_help(self, lines: Sequence[str]) -> None:
        self.help_overlay.open(lines)
        self.query_one("#upper").add_class("help-open")
        self.tabs.show(self.page, True)

    def close_help(self) -> None:
        self.help_overlay.close()
        self.query_one("#upper").remove_class("help-open")
        self.tabs.show(self.page, False)

    def on_click(self, event: events.Click) -> None:
        """A click outside the help panel closes it."""
        overlay = self.help_overlay
        widget = event.widget
        if overlay.is_open and (widget is None or overlay not in widget.ancestors_with_self):
            self.close_help()

    def prompt_key(self, key: str) -> bool:
        """A key the prompt offers before it handles it itself, in the order
        it was typed (an app binding would see it before the keys typed just
        before it): ``True`` if it was used here."""
        if key != "ctrl+c":
            self._disarm()
        prompt = self.prompt
        match key:
            case "tab":
                self._tab()
            case "escape":
                self._escape()
            case "ctrl+c":
                self._interrupt()
            case "ctrl+s":
                self._run(commands.save())
            case "ctrl+n":
                self.new_show()
            case "ctrl+o":
                self.open_show()
            case "ctrl+z":
                self._run(commands.undo())
            case "ctrl+y":
                self._run(commands.redo())
            case "question_mark" if not prompt.value:
                self.action_toggle_help()
            case "enter" if self.cursor.active:
                self._take()
            case "up" | "left" if self.cursor.active:
                self._move_cursor(-1)
            case "down" | "right" if self.cursor.active:
                self._move_cursor(1)
            case "pageup" | "pagedown" if self.help_overlay.is_open:
                self.help_overlay.scroll_page(1 if key == "pagedown" else -1)
            case _ if prompt.value:
                return False
            case "space":
                self._run(commands.go(self.view.playback))
            case "left" | "right":
                by = 1 if key == "right" else -1
                self._select_playback(step(self.view.playback, self._slots, by))
            case "left_square_bracket" | "right_square_bracket":
                self._nudge(0.05 if key == "right_square_bracket" else -0.05)
            case "pageup" | "pagedown":
                self._run(commands.page(1 if key == "pagedown" else -1))
            case _:
                return False
        return True

    def _run(self, line: commands.Line) -> None:
        self.run_line(line.text, "ui", performance=line.performance)

    def _select_playback(self, number: int) -> None:
        if number != self.view.playback:
            self.view.playback = number
            self._changed.add("playback")
            self._redraw()
            self._show_context()

    def _nudge(self, by: float) -> None:
        """``[ ]``: the selected playback's fader 5 % down or up, from the
        level last sent if that was just now (the engine has not shown it
        yet), else from the engine's."""
        number = self.view.playback
        shown = None if self.view.live is None else self.view.live.playback(number)
        level = 0.0 if shown is None else shown.level
        now = time.monotonic()
        nudged = self._nudged
        if nudged is not None and nudged[0] == number and now - nudged[2] < NUDGE_S:
            level = nudged[1]
        level = round(max(0.0, min(1.0, level + by)), 4)
        self._nudged = (number, level, now)
        line = commands.fader(number, level)
        self.run_line(line.text, "ui", key=f"fader:{number}", performance=line.performance)

    def _escape(self) -> None:
        """Close help, else the page's own (F9's learn mode), else leave the
        pane cursor, else clear the prompt."""
        if self.help_overlay.is_open:
            self.close_help()
        elif self.current_page.escape():
            pass
        elif self.cursor.active:
            self._leave_cursor()
        else:
            self.prompt.clear_line()

    def _tab(self) -> None:
        """Complete the word at the cursor; on an empty prompt, move into the
        page (and through it, once there)."""
        prompt = self.prompt
        if self.cursor.active:
            self._move_cursor(1)
            return
        if not prompt.value:
            if self.cursor.enter(self.current_page.items()):
                self.current_page.show_cursor(self.cursor.index)
            return
        cursor = prompt.cursor_position
        done = complete(prompt.value, cursor, self.bridge.expected(prompt.value[:cursor]))
        if done.line != prompt.value:
            prompt.value = done.line
        prompt.cursor_position = done.cursor
        if done.candidates:
            self.log_view.add("info", "  ".join(done.candidates))

    def _take(self) -> None:
        """Enter on the pane cursor: do its item's action, run its line, and
        stay (TAP, GO again), or put its line in the prompt to finish."""
        index = self.cursor.index
        item = None if index is None else self.current_page.current_item(index)
        if item is None or (item.line is None and item.action is None):
            self._leave_cursor()
        if item is None:
            return
        if item.action is not None:
            item.action()
            self._redraw()
            self.cursor.follow(self.current_page.items(), item.label)  # they may have changed
            self.current_page.show_cursor(self.cursor.index)
        if item.line is not None:
            self.run_line(item.line, "ui")
        elif item.prefill is not None:
            self.prompt.value = item.prefill
            self.prompt.cursor_position = len(item.prefill)

    def _interrupt(self) -> None:
        """Ctrl+C: clear a typed line; on an empty prompt say how to quit,
        and a second one in a row opens the quit dialog (as ``busk run``)."""
        if self.prompt.value:
            self.prompt.clear_line()
            return
        if self._interrupted:
            self._interrupted = False
            self._show_hint()
            self.action_quit_dialog()
            return
        self._interrupted = True
        self.query_one(HintRow).show_text("press Ctrl+C again to quit")

    def action_quit_dialog(self) -> None:
        if self._modal():
            return

        def chosen(choice: QuitChoice | None) -> None:
            if choice == "save":
                line = commands.save()
                self._quitting = self._send(line.text, "ui", None, line.performance)
            elif choice == "quit":
                self.exit(0)

        self.push_screen(QuitDialog(None if self.session is None else self.session.dirty), chosen)

    def _move_cursor(self, step: int) -> None:
        self.cursor.move(step, self.current_page.items())  # they may have changed (F4's cues)
        self.current_page.show_cursor(self.cursor.index)

    def _leave_cursor(self) -> None:
        if self.cursor.active:
            self.cursor.leave()
            self.current_page.show_cursor(None)
