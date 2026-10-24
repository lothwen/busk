"""The Textual app: the frame, the pages, the keys, and the drain loop.

It talks to the engine only through a :class:`~busk_tui.model.BridgeLike`:
lines go out with ``send`` (after the engine's question, if it has one),
and every 25 ms ``drain`` brings in what changed. Nothing here waits for the
engine (plan §4.1).

Keys (plan §4.4). The prompt always has the keyboard. F1–F9 and Alt+1–9
switch pages, F10 and Alt+0 toggle help, Esc closes help, leaves the pane
cursor or clears the prompt. On an empty prompt only: ``?`` toggles help and
Tab moves the pane cursor into the page. Everything else types.

Imported only once ``TEXTUAL_COLOR_SYSTEM`` is set (:mod:`busk_tui.app`),
since Textual reads it when it is imported.
"""

from __future__ import annotations

import asyncio
import signal
import time
from collections.abc import Sequence
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
    EngineFailed,
    EngineNews,
    EngineRunning,
    EngineStarting,
    EngineStopped,
    HealthChanged,
    LiveChanged,
    LiveState,
    Origin,
    ProgrammerChanged,
    ProgrammerModel,
    RoutesChanged,
    SessionChanged,
    SessionState,
    ShowChanged,
)
from busk_tui.nav import PaneCursor
from busk_tui.pages.base import Page
from busk_tui.pages.placeholder import Placeholder
from busk_tui.widgets.controls import RunLine
from busk_tui.widgets.dialogs import ConfirmDialog, QuitChoice, QuitDialog
from busk_tui.widgets.frame import PAGES, KeyLegend, StatusBar, TabBar
from busk_tui.widgets.help import HelpOverlay
from busk_tui.widgets.log import LogView
from busk_tui.widgets.prompt import HintRow, Prompt, PromptRow

DRAIN_S: Final = 0.025
BUSY_AFTER_S: Final = 0.3
NARROW: Final = 100
"""Below this many columns, side-by-side panels stack (the ``narrow`` class)."""


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
        self.playback = 1  # the selected playback (F1's, Phase 1)
        self.cursor = PaneCursor()
        self.live: LiveState | None = None
        self.programmer: ProgrammerModel | None = None
        self.session: SessionState | None = None
        self._help_index: HelpIndex | None = None
        self._interrupted = False  # a Ctrl+C on an empty prompt: the next one quits
        self._quitting: int | None = None  # the ticket of "save and quit"'s save
        self._context_text = ""

    # ------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        with Vertical(id="upper"):
            yield StatusBar(id="status")
            yield TabBar(id="tabs")
            with ContentSwitcher(id="main", initial=f"page-{self.page}"):
                for number, title in PAGES:
                    yield Placeholder(number, title)
            yield LogView(id="log")
            yield HelpOverlay()
        yield PromptRow(id="prompt-row")
        yield HintRow(id="hint")
        yield KeyLegend(id="legend")

    def on_mount(self) -> None:
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

    # ------------------------------------------------------------ events

    def drain(self) -> None:
        """Take in what the bridge has sent since the last drain."""
        for event in self.bridge.drain():
            self.take(event)

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
                self.live = self.status.live = state
                self.status.refresh()
            case Beat(beats=beats):
                self.status.set_beats(beats[0] if beats else None)
            case ShowChanged(show=show):
                self.status.title = show.title
                self.status.refresh()
            case ProgrammerChanged(programmer=programmer):
                self.programmer = self.status.programmer = programmer
                self.status.refresh()
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
        self, line: str, origin: Origin, key: str | None = None, performance: bool = False
    ) -> None:
        """Send ``line``: after the engine's question, if it asks one (not
        for a control's keyed moves), echoed unless ``internal``."""
        question = None if key is not None else self.bridge.confirmation(line)
        if question is None:
            self._send(line, origin, key, performance)
            return

        def answered(yes: bool | None) -> None:
            if yes:
                self._send(line, origin, key, performance)
            else:
                self.log_view.add("info", f"cancelled: {line}")

        self.push_screen(ConfirmDialog(question, line), answered)

    def _send(self, line: str, origin: Origin, key: str | None, performance: bool) -> int:
        if origin != "internal":
            self.log_view.add("typed" if origin == "typed" else "ui", line)
        return self.bridge.send(line, origin, key=key, performance=performance)

    def on_run_line(self, message: RunLine) -> None:
        message.stop()
        self._disarm()
        self.run_line(message.line.text, message.origin, message.key, message.line.performance)

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
        parts.append(f"P{self.playback}")
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
        self.bridge.watch(output=False, effects=False)  # no Phase 0 page shows them

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
            case _:
                return False
        return True

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
        """Enter on the pane cursor: run its item's line, or put it in the prompt."""
        item = self.cursor.current
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
