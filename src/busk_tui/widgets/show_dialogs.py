"""The dialogs of opening another show (file-menu plan Phase 3): the
confirmation before the show changes (:class:`OpenDialog`), the new show's
form (:class:`NewShowDialog`), and the recent shows (:class:`RecentDialog`,
on a :class:`RecentList`).

None of them sends anything: each closes with what was chosen, and the app
opens the show.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Final, Literal, cast

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from busk_tui import colors
from busk_tui.config import RecentShow
from busk_tui.model import ShowRead
from busk_tui.widgets.controls import ReadShow
from busk_tui.widgets.dialogs import Choice, FormDialog, dialog_css
from busk_tui.widgets.file_picker import home_text, save_name, show_text
from busk_tui.widgets.group_panel import plural

type OpenChoice = Literal["save", "open", "cancel"]

PROBLEMS: Final = 8
"""The most of a show's errors :class:`OpenDialog` lists."""

TITLE: Final = 20
"""The width of a recent show's title in its row."""

ROWS: Final = 12


class OpenDialog(ModalScreen[OpenChoice]):
    """Before the show changes, for New, Open and Open recent (file-menu plan
    D2, call 12): ``question``, then what applies. Unsaved edits (``dirty``;
    ``None``: the TUI cannot tell) offer Save and open, and Open without
    saving; without them, Open. The names of the routes that send
    (``sending``) say that the output stops while the next show starts.

    With ``problems``, the show cannot be opened: it says why, and closes."""

    DEFAULT_CSS = dialog_css("OpenDialog")
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("s", "choose('save')", "Save and open", show=False),
        Binding("o", "choose('open')", "Open", show=False),
        Binding("c,escape,enter", "choose('cancel')", "Cancel", show=False),
    ]

    def __init__(
        self,
        title: str,
        question: str,
        dirty: bool | None = False,
        sending: Sequence[str] = (),
        problems: Sequence[str] = (),
    ) -> None:
        super().__init__()
        self.title_text = title
        self.question = question
        self.dirty = dirty
        self.sending = tuple(sending)
        self.problems = tuple(problems)

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = self.title_text
            yield Static(Text(self.question), classes="question")  # names in it are not markup
            if self.problems:
                yield from self._refused()
                return
            if self.dirty:
                yield Static("There are unsaved edits.", classes="question")
            elif self.dirty is None:
                yield Static("The TUI cannot tell whether there are unsaved edits.", classes="note")
            if self.sending:
                count = len(self.sending)
                sending = f"{plural(count, 'route')} {'is' if count == 1 else 'are'} sending"
                text = f"The output stops while the next show starts:\n{sending} "
                yield Static(Text(f"{text}({', '.join(self.sending)}).", colors.AMBER))
            with Horizontal():
                if self.dirty is not False:
                    yield Choice("s", "Save and open", "save", colors.GREEN)
                    yield Choice("o", "Open without saving", "open", colors.RED)
                else:
                    yield Choice("o", "Open", "open", colors.AMBER)
                yield Choice("c", "Cancel", "cancel", colors.MID)

    def _refused(self) -> ComposeResult:
        shown = list(self.problems[:PROBLEMS])
        if len(self.problems) > PROBLEMS:
            shown.append(f"… and {len(self.problems) - PROBLEMS} more")
        yield Static(Text("\n".join(shown), colors.RED), classes="question")
        yield Static("The show that runs now goes on.", classes="note")
        with Horizontal():
            yield Choice("c", "Close", "cancel", colors.MID)

    def action_choose(self, value: str) -> None:
        if self.problems and value != "cancel":
            return
        if value == "save" and self.dirty is False:
            return
        self.dismiss(cast(OpenChoice, value))

    def on_choice_chosen(self, message: Choice.Chosen) -> None:
        self.action_choose(message.value)


def file_name(title: str) -> str:
    """The title as a file name: its words in lower case, joined by ``-``,
    with ``.show`` (``Late Night`` is ``late-night.show``); empty without
    a word."""
    words = re.findall(r"\w+", title.casefold())
    return "-".join(words) + ".show" if words else ""


def new_path(folder: Path, text: str) -> Path | None:
    """The file a typed path names: ``~`` is the home folder, a relative
    path is in ``folder``, and a name that does not end in ``.show`` or
    ``.json`` gets ``.show``; ``None`` for no file (nothing, or a folder)."""
    text = text.strip()
    if not text or text.endswith(os.sep):
        return None
    path = folder / Path(text).expanduser()
    if path.is_dir():
        return None
    return path.with_name(save_name(path.name))


class NewShowDialog(FormDialog):
    """New…: the new show's title, and its file, which is the title as a
    file name (:func:`file_name`) in ``folder`` until it is typed in. It
    refuses an empty title, and a file that exists, as ``busk new`` does;
    the app reads the file with :func:`new_path`."""

    DEFAULT_CSS = "NewShowDialog > Vertical { width: 80; max-width: 100%; }"

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.made = self._file("")  # the file as the title made it last
        super().__init__(
            "NEW SHOW",
            (("title", ""), ("file", self.made)),
            self._check,
            note="busk writes a new, empty show to the file and opens it",
        )

    def _file(self, title: str) -> str:
        name = file_name(title)
        return home_text(self.folder / name) if name else home_text(self.folder) + os.sep

    def _check(self, values: tuple[str, ...]) -> str | None:
        title, file = values
        if not title.strip():
            return "a title cannot be empty"
        path = new_path(self.folder, file)
        if path is None:
            return "the file to write the show to"
        if path.exists():
            return f"{home_text(path)} exists: a new show needs a file of its own"
        return None

    def on_input_changed(self, event: Input.Changed) -> None:
        """The title typed: the file follows it, unless it was typed in."""
        event.stop()
        title, file = self.inputs
        if event.input is title and file.value == self.made:
            self.made = self._file(title.value)
            file.value = self.made


def recent_text(show: RecentShow, missing: bool) -> Text:
    """A recent show's row: its title, ``missing`` if its file is gone (the
    row dimmed), and its file."""
    title = show.title if len(show.title) <= TITLE else show.title[: TITLE - 1] + "…"
    text = Text(f"{title:<{TITLE}}  ", style=colors.DIM if missing else colors.FG)
    if missing:
        text.append("missing  ", style=colors.DIM)
    text.append(home_text(show.path), style=colors.DIM if missing else colors.MID)
    return text


class RecentList(OptionList):
    """The recent shows, newest first; one whose file is gone is dimmed, as
    ``missing``."""

    def __init__(self, shows: Sequence[RecentShow]) -> None:
        self.shows = tuple(shows)
        self.missing = tuple(not show.path.is_file() for show in self.shows)
        super().__init__(
            *(Option(recent_text(s, m)) for s, m in zip(self.shows, self.missing, strict=True))
        )

    def current(self) -> int | None:
        """The row the cursor is on."""
        return self.highlighted if self.shows else None


class RecentDialog(ModalScreen[Path | None]):
    """Open recent…: the recent shows (but the one that runs), and a preview
    of the one the cursor is on, from busk's reading of it
    (:class:`~busk_tui.widgets.controls.ReadShow`, one at a time, each once).
    ↑ ↓ move, Enter opens it (not a missing one), Esc cancels. Closes with
    its file, or ``None``."""

    DEFAULT_CSS = (
        dialog_css("RecentDialog")
        + f"""
    RecentDialog > Vertical {{ width: 110; max-width: 100%; }}
    RecentDialog Horizontal.columns {{ width: 100%; height: {ROWS}; margin-top: 0; }}
    RecentDialog RecentList, RecentDialog RecentList:focus {{
        width: 3fr; height: {ROWS}; margin-right: 1; padding: 0; border: none;
        background: {colors.BG}; scrollbar-size-vertical: 1;
        text-wrap: nowrap; text-overflow: ellipsis;
    }}
    RecentDialog RecentList > .option-list--option-highlighted {{
        background: {colors.SEL}; text-style: none;
    }}
    RecentDialog .preview {{ width: 2fr; height: {ROWS}; }}
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, shows: Sequence[RecentShow]) -> None:
        super().__init__()
        self.list = RecentList(shows)
        self.preview = Static("", classes="preview")
        self.read: dict[Path, ShowRead] = {}  # what busk found in each file read
        self.reading: Path | None = None  # the file busk is reading now

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = "OPEN RECENT"
            if not self.list.shows:
                none = "No recent shows: busk-tui lists the shows it opens."
                yield Static(none, classes="question")
                yield Static("Esc: close", classes="note")
                return
            with Horizontal(classes="columns"):
                yield self.list
                yield self.preview
            yield Static("↑ ↓: move · Enter: open · Esc: cancel", classes="note")

    def on_mount(self) -> None:
        if self.list.shows:
            self.list.highlighted = 0
            self.list.focus()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        event.stop()
        self._preview()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if not self.list.missing[event.option_index]:
            self.dismiss(self.list.shows[event.option_index].path)

    def _preview(self) -> None:
        index = self.list.current()
        if index is None:
            self.preview.update("")
            return
        path = self.list.shows[index].path
        if self.list.missing[index]:
            self.preview.update(Text(f"{home_text(path)} is gone", style=colors.DIM))
        elif (found := self.read.get(path)) is not None:
            self.preview.update(show_text(found))
        else:
            self.preview.update(Text("reading…", style=colors.DIM))
            if self.reading is None:
                self.reading = path
                self.post_message(ReadShow(path, self._read))

    def _read(self, found: ShowRead) -> None:
        """What busk found in the file it read: shown if the cursor is on it,
        and the file the cursor is on now read next."""
        path, self.reading = self.reading, None
        if path is not None:
            self.read[path] = found
        self._preview()

    def action_cancel(self) -> None:
        self.dismiss(None)
