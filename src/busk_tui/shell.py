"""The Textual app: the frame, the pages, the keys, and the drain loop.

It talks to the engine only through a :class:`~busk_tui.model.BridgeLike`:
lines go out with ``send`` (after the engine's question, if it has one),
and every 25 ms ``drain`` brings in what changed. Nothing here waits for the
engine (plan §4.1).

Keys (plan §4.4). The prompt always has the keyboard. F1–F9 and Alt+1–9
switch pages, F10 and Alt+0 toggle help, Esc closes help, leaves the pane
cursor or clears the prompt. On an empty prompt only: ``?`` toggles help,
Tab moves the pane cursor into the page, Space runs GO on the selected
playback, ← → select another, ``[ ]`` move its fader 5 %, and PgUp PgDn
change the playback page. Everything else types.

What the bridge sends goes into one :class:`~busk_tui.pages.base.View`;
after each drain the visible page redraws the parts that changed.

Imported only once ``TEXTUAL_COLOR_SYSTEM`` is set (:mod:`busk_tui.app`),
since Textual reads it when it is imported.
"""

from __future__ import annotations

import asyncio
import signal
import time
from collections.abc import Callable, Sequence
from typing import ClassVar, Final

from rich.text import Text
from textual import events
from textual.actions import SkipAction
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import ContentSwitcher, Input, Static

from busk_tui import colors, commands, config
from busk_tui.hints import HelpIndex, complete, hint
from busk_tui.model import (
    Beat,
    BridgeEvent,
    BridgeLike,
    CommandDone,
    EffectsChanged,
    EngineFailed,
    EngineNews,
    EngineRunning,
    EngineStarting,
    EngineStopped,
    HealthChanged,
    LiveChanged,
    LiveState,
    Origin,
    OutputChanged,
    ProgrammerChanged,
    ProgrammerModel,
    RoutesChanged,
    SessionChanged,
    SessionState,
    ShowChanged,
)
from busk_tui.nav import PaneCursor
from busk_tui.pages.base import ALL_PARTS, Page, Part, View
from busk_tui.pages.busk import BuskPage, Slots, follow, step, visible_slots
from busk_tui.pages.masters import MastersPage
from busk_tui.pages.placeholder import Placeholder
from busk_tui.pages.presets import PresetsPage
from busk_tui.pages.program import ProgramPage
from busk_tui.widgets.controls import FillPrompt, RunLine
from busk_tui.widgets.dialogs import ConfirmDialog, QuitChoice, QuitDialog
from busk_tui.widgets.frame import PAGES, KeyLegend, StatusBar, TabBar
from busk_tui.widgets.help import HelpOverlay
from busk_tui.widgets.log import LogView
from busk_tui.widgets.playbacks import PlaybackRow
from busk_tui.widgets.prompt import HintRow, Prompt, PromptRow

DRAIN_S: Final = 0.025
BUSY_AFTER_S: Final = 0.3
NARROW: Final = 100
"""Below this many columns, side-by-side panels stack (the ``narrow`` class)."""

NUDGE_S: Final = 0.5
"""``[ ]`` step from the level they last sent for this long; after it, from
the level the engine shows."""

BUILT: Final[dict[int, type[Page]]] = {
    1: BuskPage,
    2: ProgramPage,
    6: PresetsPage,
    7: MastersPage,
}
"""The pages built so far; the others are placeholders."""

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


class BuskApp(App[int]):
    """The TUI on one show (see the module docs)."""

    CSS_PATH = "busk.tcss"
    TITLE = "busk"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS: ClassVar[list[BindingType]] = [
        *(Binding(f"f{n},alt+{n}", f"page({n})", show=False, priority=True) for n in range(1, 10)),
        Binding("f10,alt+0", "toggle_help", show=False, priority=True),
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
    ) -> None:
        super().__init__()
        self.bridge = bridge
        self.settings = settings
        self.standalone = standalone
        self.page = settings.page
        self.view = View(faders=settings.faders, quick=settings.quick)
        self.cursor = PaneCursor()
        self.session: SessionState | None = None
        self._changed: set[Part] = set()  # the parts of the view since the page last drew
        self._slots: Slots = ()  # F1's slots, which the selected playback follows
        self._nudged: tuple[int, float, float] | None = None  # [ ]: playback, level, when
        self._help_index: HelpIndex | None = None
        self._interrupted = False  # a Ctrl+C on an empty prompt: the next one quits
        self._quitting: int | None = None  # the ticket of "save and quit"'s save
        self._context_text = ""
        self._waiting: dict[int, Callable[[bool], None]] = {}  # ticket → what to call when done
        self._keyed: dict[str, int] = {}  # key → the newest ticket with such a callback

    # ------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        with Vertical(id="upper"):
            yield StatusBar(id="status")
            yield TabBar(id="tabs")
            with ContentSwitcher(id="main", initial=f"page-{self.page}"):
                for number, title in PAGES:
                    yield BUILT.get(number, Placeholder)(number, title)
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
        self.set_interval(1.0, self.status.refresh)  # the clock
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
        self._redraw()

    def _redraw(self) -> None:
        changed = self._changed
        if not changed:
            return
        self._changed = set()
        if changed & {"show", "live"}:
            slots = visible_slots(self.view.show, self.view.live, self.view.faders)
            if slots != self._slots:
                chosen = follow(self.view.playback, self._slots, slots)
                self._slots = slots
                if chosen != self.view.playback:
                    self.view.playback = chosen
                    changed.add("playback")
        self.current_page.update_view(self.view, frozenset(changed))

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
            case RoutesChanged(routes=routes):
                self.status.set_routes(routes)
            case HealthChanged(state=state, late=late):
                self.status.engine, self.status.late = state, late
                self.status.refresh()
            case SessionChanged(session=session):
                self.session = self.status.session = session
                self.status.refresh()
            case EngineNews(level=level, text=text):
                self.log_view.add(level, text)

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
        elif done.ok:
            if done.lines:
                self.log_view.add("result", "\n".join(done.lines))
        else:
            lines = list(done.lines) or ["failed"]
            lines[0] = lines[0].removeprefix("error: ")  # busk's mark of a refused line
            self.log_view.add("error", "\n".join(lines))
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
    ) -> None:
        """Send ``line``: after the engine's question, if it asks one (not
        for a control's keyed moves), echoed unless ``internal``. ``done``
        is called with the line's success once it has run."""
        question = None if key is not None else self.bridge.confirmation(line)
        if question is None:
            self._send(line, origin, key, performance, done)
            return

        def answered(yes: bool | None) -> None:
            if yes:
                self._send(line, origin, key, performance, done)
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
    ) -> int:
        if origin != "internal":
            self.log_view.add("typed" if origin == "typed" else "ui", line)
        ticket = self.bridge.send(line, origin, key=key, performance=performance)
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
        self.run_line(line.text, message.origin, message.key, line.performance, message.done)

    def on_fill_prompt(self, message: FillPrompt) -> None:
        """A pre-fill from a page: the text goes in the prompt, to finish."""
        message.stop()
        self._disarm()
        self._leave_cursor()
        self.prompt.value = message.text
        self.prompt.cursor_position = len(message.text)
        self.prompt.focus()

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
        prompt = self.prompt
        before = prompt.value[: prompt.cursor_position]
        if self._help_index is None and self.bridge.help_lines:
            self._help_index = HelpIndex(self.bridge.help_lines)
        completion = self.bridge.expected(before) if before.strip() else None
        self.query_one(HintRow).show(hint(self._help_index, before, completion))

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

    def _show_page(self) -> None:
        """The page just shown: what the bridge reads for it, and all of it drawn."""
        page = self.current_page
        self.bridge.watch(output=page.WATCH_OUTPUT, effects=page.WATCH_EFFECTS)
        self._changed |= ALL_PARTS
        self._redraw()

    def action_layout(self, layout: str) -> None:
        """A click on F1's layout switch."""
        if layout != "B":
            name = {"A": "console", "C": "stage"}.get(layout, layout)
            self.log_view.add("info", f"layout {layout} ({name}) comes in Phase 5; F1 shows B")

    def action_toggle_help(self) -> None:
        if self._modal():
            raise SkipAction
        self._disarm()
        if self.help_overlay.is_open:
            self.close_help()
        else:
            self.open_help(self.bridge.help_lines)

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
        """Close help, else leave the pane cursor, else clear the prompt."""
        if self.help_overlay.is_open:
            self.close_help()
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
        """Enter on the pane cursor: run its item's line, and stay (TAP, GO
        again), or put its line in the prompt to finish."""
        index = self.cursor.index
        item = None if index is None else self.current_page.current_item(index)
        if item is None or item.line is None:
            self._leave_cursor()
        if item is None:
            return
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
        self.cursor.move(step)
        self.current_page.show_cursor(self.cursor.index)

    def _leave_cursor(self) -> None:
        if self.cursor.active:
            self.cursor.leave()
            self.current_page.show_cursor(None)
