"""The file picker of the profile picker's ``[import…]``: three columns, as
in yazi (the folder above, the folder, and a preview of what the cursor is
on), to find a profile file instead of typing its path.

It starts in a folder, on a name in it (the profile picker's: where
busk-tui runs, or on the file chosen last). Every entry is listed, folders
first; a file busk does not import (not a ``.json`` or a ``.gdtf``) is
dimmed, and a hidden one (``.name``) shows only while the filter starts with
a dot. The keys are the profile picker's: typing filters the folder, ↑ ↓
PgUp PgDn move, → goes into a folder, ← (or Backspace on an empty filter)
goes up, onto the folder it leaves, Enter goes into a folder or chooses a
profile file, and Esc cancels. A click in the middle column is Enter on that
row; a click in the left one goes up, onto that row. A folder that cannot
be read says why.

The preview of a folder is what it holds; of a profile file, what busk reads
in it: its maker, name and modes, or why busk cannot import it. The app
reads it on a worker thread (:class:`~busk_tui.widgets.controls.ReadProfile`),
one file at a time, each once.

It sends nothing: it closes with the file's path, or ``None``.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from busk_tui import colors
from busk_tui.model import ProfileRead
from busk_tui.widgets.controls import ReadProfile
from busk_tui.widgets.dialogs import dialog_css
from busk_tui.widgets.group_panel import plural

KINDS: Final = (".json", ".gdtf")
"""The files busk imports, as ``profile import`` tells them apart."""
FILES: Final = "an OFL .json, a .gdtf or a busk profile .json"
ROWS: Final = 16
PAGE: Final = ROWS - 1


@dataclass(frozen=True, slots=True)
class Entry:
    """A folder or a file in a folder, by its name."""

    name: str
    folder: bool

    def importable(self) -> bool:
        """Whether busk imports it: a ``.json`` or a ``.gdtf`` file."""
        return not self.folder and Path(self.name).suffix in KINDS


def listing(folder: Path) -> tuple[Entry, ...]:
    """What ``folder`` holds, folders first, each in name order, in any case.
    A link is what it leads to. Raises :class:`OSError`."""
    with os.scandir(folder) as found:
        entries = [Entry(item.name, item.is_dir()) for item in found]
    return tuple(sorted(entries, key=lambda e: (not e.folder, e.name.casefold(), e.name)))


def filtered(entries: Sequence[Entry], text: str) -> tuple[Entry, ...]:
    """The entries whose names hold every word of ``text``, in any case; a
    hidden one only when ``text`` starts with a dot."""
    words = text.casefold().split()
    hidden = text.lstrip().startswith(".")
    return tuple(
        entry
        for entry in entries
        if (hidden or not entry.name.startswith("."))
        and all(word in entry.name.casefold() for word in words)
    )


def entry_text(entry: Entry) -> Text:
    """A row: a folder in cyan, with a ``/``; a file busk does not import, dimmed."""
    if entry.folder:
        return Text(f"{entry.name}/", style=colors.CYAN, no_wrap=True, overflow="ellipsis")
    style = colors.FG if entry.importable() else colors.DIM
    return Text(entry.name, style=style, no_wrap=True, overflow="ellipsis")


def folder_text(folder: Path) -> Text:
    """The preview of a folder: what it holds, without its hidden entries."""
    try:
        entries = filtered(listing(folder), "")
    except OSError as exc:
        return Text(f"cannot read it: {exc.strerror or exc}", style=colors.RED)
    if not entries:
        return Text("empty", style=colors.DIM)
    return Text("\n").join(entry_text(entry) for entry in entries[:ROWS])


def read_text(found: ProfileRead) -> Text:
    """The preview of a profile file: what busk reads in it, or why it cannot."""
    if found.problem is not None:
        text = Text("busk cannot import it:\n", style=colors.RED)
        text.append(found.problem, style=colors.FG)
        return text
    text = Text(f"{found.manufacturer}\n", style=colors.DIM)
    text.append(f"{found.name}\n\n", style=f"bold {colors.FG}")
    text.append(f"{plural(len(found.modes), 'mode')}\n", style=colors.MID)
    for mode in found.modes:
        text.append(f"{mode.name}", style=colors.FG)
        text.append(f" · {plural(mode.footprint, 'channel')}", style=colors.MID)
        if mode.elements > 1:
            text.append(f" · {plural(mode.elements, 'element')}", style=colors.MID)
        text.append("\n")
    text.rstrip()
    return text


def home_text(folder: Path) -> str:
    """``folder`` as a path, with ``~`` for the home folder."""
    home = Path.home()
    if folder == home:
        return "~"
    return f"~/{folder.relative_to(home)}" if folder.is_relative_to(home) else str(folder)


class PathLine(Widget):
    """The folder's path, its start cut when it is too long: the end names it."""

    def __init__(self) -> None:
        super().__init__()
        self.text = ""

    def show(self, text: str) -> None:
        self.text = text
        self.refresh()

    def render(self) -> Text:
        width, text = self.size.width, self.text
        if len(text) > width > 1:
            text = "…" + text[len(text) - width + 1 :]
        return Text(text, style=colors.FG, no_wrap=True)


class FileDialog(ModalScreen[Path | None]):
    """Closes with a profile file's path, or ``None`` (see the module docs).
    It starts in ``folder`` (the nearest folder that exists), on ``chosen``
    if it is there, else on the first row."""

    DEFAULT_CSS = (
        dialog_css("FileDialog")
        + f"""
    FileDialog > Vertical {{ width: 110; max-width: 100%; }}
    FileDialog PathLine {{ width: 100%; height: 1; }}
    FileDialog Input {{ width: 100%; margin-bottom: 1; }}
    FileDialog Horizontal.columns {{ width: 100%; height: {ROWS}; margin-top: 0; }}
    FileDialog .parent {{ width: 2fr; margin-right: 1; }}
    FileDialog .middle {{ width: 4fr; margin-right: 1; }}
    FileDialog .preview {{ width: 4fr; height: {ROWS}; }}
    FileDialog OptionList {{
        height: {ROWS}; padding: 0; border: none; background: {colors.BG};
        scrollbar-size-vertical: 1; text-wrap: nowrap; text-overflow: ellipsis;
    }}
    FileDialog OptionList > .option-list--option-highlighted {{
        background: {colors.SEL}; text-style: none;
    }}
    FileDialog .none {{ height: {ROWS}; }}
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("up", "move(-1)", "Up", show=False),
        Binding("down", "move(1)", "Down", show=False),
        Binding("pageup", f"move(-{PAGE})", "Page up", show=False),
        Binding("pagedown", f"move({PAGE})", "Page down", show=False),
        # before the filter's own: it is typed at its end, and these move
        Binding("left", "out", "Up a folder", show=False, priority=True),
        Binding("right", "into", "Into a folder", show=False, priority=True),
        Binding("backspace", "back", "Back", show=False, priority=True),
    ]

    def __init__(self, folder: Path, chosen: str | None = None) -> None:
        super().__init__()
        folder = folder.absolute()
        while not folder.is_dir() and folder != folder.parent:
            folder = folder.parent
        self.folder = folder
        self.chosen = chosen
        self.entries: tuple[Entry, ...] = ()  # the folder's
        self.shown: tuple[Entry, ...] = ()  # those the filter finds
        self.problem: str | None = None  # why the folder cannot be read
        self.read: dict[Path, ProfileRead] = {}  # what busk found in each file read
        self.reading: Path | None = None  # the file busk is reading now
        self.path = PathLine()
        self.field = Input(placeholder="type to filter", compact=True)
        self.parent_entries: tuple[Entry, ...] = ()  # the left column's
        self.parent_list = OptionList(classes="parent")
        self.parent_list.can_focus = False
        self.list = OptionList(classes="middle")
        self.list.can_focus = False  # the filter keeps the keyboard
        self.none = Static("", classes="middle none")
        self.preview = Static("", classes="preview")

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = "IMPORT PROFILE"
            yield self.path
            yield self.field
            with Horizontal(classes="columns"):
                yield self.parent_list
                yield self.list
                yield self.none
                yield self.preview
            yield Static(f"busk imports {FILES}; other files are dimmed", classes="note")
            yield Static(
                "type: filter (from . for hidden) · ↑ ↓: move · →: into · ←: up · "
                "Enter: choose · Esc: cancel",
                classes="note",
            )

    def on_mount(self) -> None:
        self.go(self.folder, self.chosen)
        self.field.focus()

    # ------------------------------------------------------------ the folder

    def go(self, folder: Path, keep: str | None = None) -> None:
        """Show ``folder``, the filter cleared, on ``keep`` if it is there."""
        self.folder = folder
        self.path.show(home_text(folder))
        try:
            self.entries, self.problem = listing(folder), None
        except OSError as exc:
            self.entries, self.problem = (), f"cannot read it: {exc.strerror or exc}"
        self._fill_parent()
        with self.prevent(Input.Changed):
            self.field.value = ""
        self._fill(keep)

    def _fill_parent(self) -> None:
        """The left column: the folder above, without its hidden entries but
        this folder, on this one; empty at the root."""
        self.parent_list.clear_options()
        self.parent_entries = ()
        above, name = self.folder.parent, self.folder.name
        if above == self.folder:
            return
        try:
            found = listing(above)
        except OSError:
            return
        self.parent_entries = tuple(
            entry for entry in found if not entry.name.startswith(".") or entry.name == name
        )
        names = [entry.name for entry in self.parent_entries]
        self.parent_list.add_options([Option(entry_text(entry)) for entry in self.parent_entries])
        self.parent_list.highlighted = names.index(name) if name in names else None

    def _fill(self, keep: str | None) -> None:
        """The middle column: what the filter finds, on ``keep`` if it is
        there, else the first row; then the preview."""
        text = self.field.value
        self.shown = filtered(self.entries, text)
        names = [entry.name for entry in self.shown]
        self.list.clear_options()
        self.list.add_options([Option(entry_text(entry)) for entry in self.shown])
        self.list.highlighted = (names.index(keep) if keep in names else 0) if names else None
        self.list.display = bool(names)
        self.none.display = not names
        if self.problem is not None:
            self.none.update(Text(self.problem, style=colors.RED))
        elif text.strip():
            self.none.update(Text(f"nothing has {text.strip()!r}", style=colors.DIM))
        else:
            self.none.update(Text("empty", style=colors.DIM))
        self._preview()

    def current(self) -> Entry | None:
        """The row the cursor is on."""
        index = self.list.highlighted
        return None if index is None or not self.shown else self.shown[index]

    # ------------------------------------------------------------ the preview

    def _preview(self) -> None:
        entry = self.current()
        if entry is None:
            self.preview.update("")
            return
        path = self.folder / entry.name
        if entry.folder:
            self.preview.update(folder_text(path))
        elif not entry.importable():
            self.preview.update(Text("not a profile file", style=colors.DIM))
        elif (found := self.read.get(path)) is not None:
            self.preview.update(read_text(found))
        else:
            self.preview.update(Text("reading…", style=colors.DIM))
            if self.reading is None:
                self.reading = path
                self.post_message(ReadProfile(path, self._read))

    def _read(self, found: ProfileRead) -> None:
        """What busk found in the file it read: shown if the cursor is on it,
        and the file the cursor is on now read next."""
        path, self.reading = self.reading, None
        if path is not None:
            self.read[path] = found
        self._preview()

    # ------------------------------------------------------------ the keys

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        entry = self.current()
        self._fill(None if entry is None else entry.name)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._enter()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        event.stop()
        if event.option_list is self.list:
            self._preview()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_list is self.list:
            self._enter()
        elif event.option_list is self.parent_list:
            self.go(self.folder.parent, self.parent_entries[event.option_index].name)

    def _enter(self) -> None:
        """Enter: into a folder, or a profile file chosen."""
        entry = self.current()
        if entry is None:
            return
        if entry.folder:
            self.go(self.folder / entry.name)
        elif entry.importable():
            self.dismiss(self.folder / entry.name)

    def action_move(self, by: int) -> None:
        index = self.list.highlighted
        if index is not None:
            self.list.highlighted = index + by  # the list stops it at its ends

    def action_out(self) -> None:
        """←: up, onto the folder it leaves; not at the root."""
        if self.folder.parent != self.folder:
            self.go(self.folder.parent, self.folder.name)

    def action_into(self) -> None:
        """→: into the folder the cursor is on."""
        entry = self.current()
        if entry is not None and entry.folder:
            self.go(self.folder / entry.name)

    def action_back(self) -> None:
        """Backspace: the filter's last character, else up."""
        if self.field.value:
            self.field.action_delete_left()
        else:
            self.action_out()

    def action_cancel(self) -> None:
        self.dismiss(None)
