"""The file picker (``busk_tui.widgets.file_picker``): three columns, the
profile picker's keys, and a preview of the file, in each of its modes: the
profile picker's ``[import…]`` (what busk reads in a profile file), the File
menu's Import script… (a script's first lines) and its Save as… (a name)."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from textual.containers import Vertical
from textual.pilot import Pilot
from tui_fakes import FakeBridge, drive, make_app

from busk_tui import colors
from busk_tui.model import ModeInfo, ProfileRead
from busk_tui.shell import BuskApp
from busk_tui.widgets.file_picker import (
    KINDS,
    ROWS,
    Entry,
    FileDialog,
    Mode,
    entry_text,
    filtered,
    home_text,
    listing,
    read_text,
    save_name,
    script_text,
)

DIMMER = {
    "name": "Test",
    "meta": {"lastModifyDate": "2026-01-02"},
    "availableChannels": {"Dimmer": {"capability": {"type": "Intensity"}}},
    "modes": [{"name": "All", "channels": ["Dimmer"]}],
}
"""An Open Fixture Library fixture: busk names it after its folder, ``acme Test``."""


def rig(root: Path) -> Path:
    """``root/rig``: ``acme/`` (an OFL fixture, a broken one, a readme), ``beta/``,
    a hidden ``.git/`` and a ``notes.txt``."""
    folder = root / "rig"
    (folder / "acme").mkdir(parents=True)
    (folder / "beta").mkdir()
    (folder / ".git").mkdir()
    (folder / "notes.txt").write_text("x")
    (folder / "acme" / "dim.json").write_text(json.dumps(DIMMER))
    (folder / "acme" / "broken.json").write_text("{")
    (folder / "acme" / "README.md").write_text("x")
    return folder


@dataclass
class CountingBridge(FakeBridge):
    """A fake that keeps the files it was asked to read, each read slow, and
    the most it read at once."""

    asked: list[Path] = field(default_factory=list)
    reading: int = 0
    most: int = 0

    def read_profile(self, path: Path) -> ProfileRead:
        self.asked.append(path)
        self.reading += 1
        self.most = max(self.most, self.reading)
        time.sleep(0.03)
        self.reading -= 1
        return super().read_profile(path)


class Opened:
    """A file picker opened on an app, and what it closed with."""

    def __init__(self, app: BuskApp, dialog: FileDialog) -> None:
        self.app = app
        self.dialog = dialog
        self.closed: list[Path | None] = []

    def names(self) -> list[str]:
        return [entry.name for entry in self.dialog.shown]

    def on(self) -> str | None:
        entry = self.dialog.current()
        return None if entry is None else entry.name

    def preview(self) -> str:
        return str(self.dialog.preview.content)


def with_picker(
    folder: Path,
    body: Callable[[Pilot[int], Opened], object],
    chosen: str | None = None,
    bridge: FakeBridge | None = None,
    size: tuple[int, int] = (150, 48),
    mode: Mode = "profile",
    own: Path | None = None,
) -> None:
    """Run the app with a file picker on ``folder`` (on ``chosen``)."""
    app = make_app(bridge or FakeBridge())

    async def main(pilot: Pilot[int]) -> None:
        dialog = FileDialog(folder, chosen, mode, own)
        opened = Opened(app, dialog)
        app.push_screen(dialog, opened.closed.append)
        await pilot.pause()
        await body(pilot, opened)  # type: ignore[misc]

    drive(app, main, size=size)


async def until(pilot: Pilot[int], test: Callable[[], bool]) -> None:
    for _ in range(100):
        if test():
            return
        await pilot.pause(0.02)
    raise AssertionError("timed out")


# ------------------------------------------------------------------ the parts


def test_a_listing_has_its_folders_first_each_in_name_order_in_any_case(tmp_path: Path) -> None:
    for name in ("b.json", "A.gdtf", "c.txt"):
        (tmp_path / name).write_text("")
    for name in ("d", "C"):
        (tmp_path / name).mkdir()
    (tmp_path / "to-d").symlink_to(tmp_path / "d")
    (tmp_path / "gone.json").symlink_to(tmp_path / "nowhere")
    assert listing(tmp_path) == (
        Entry("C", True),
        Entry("d", True),
        Entry("to-d", True),  # a link is what it leads to
        Entry("A.gdtf", False),
        Entry("b.json", False),
        Entry("c.txt", False),
        Entry("gone.json", False),
    )
    with pytest.raises(FileNotFoundError):
        listing(tmp_path / "nowhere")


def test_busk_imports_a_json_or_a_gdtf_file_and_the_rest_is_dimmed() -> None:
    assert Entry("spot.gdtf", False).fits(KINDS["profile"])
    assert Entry("dim.json", False).fits(KINDS["profile"])
    assert not Entry("dim.json", True).fits(KINDS["profile"])  # a folder
    assert not Entry("spot.GDTF", False).fits(KINDS["profile"])  # busk reads it as JSON
    assert not Entry("notes.txt", False).fits(KINDS["profile"])
    assert entry_text(Entry("acme", True)).plain == "acme/"
    assert entry_text(Entry("notes.txt", False)).style != entry_text(Entry("a.json", False)).style


def test_the_filter_takes_every_word_in_any_case_and_a_dot_shows_the_hidden() -> None:
    entries = (Entry(".git", True), Entry("Acme", True), Entry("acme-spot.json", False))
    assert filtered(entries, "") == entries[1:]
    assert filtered(entries, "ACME spot") == entries[2:]
    assert filtered(entries, ".") == entries[:1] + entries[2:]  # holding a dot
    assert filtered(entries, " .g") == entries[:1]


def test_a_path_starts_at_home_when_it_is_in_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert home_text(tmp_path) == "~"
    assert home_text(tmp_path / "rig" / "acme") == "~/rig/acme"
    assert home_text(Path("/srv")) == "/srv"


def test_the_preview_of_a_profile_says_its_maker_name_and_modes() -> None:
    found = ProfileRead("Acme", "Bar", (ModeInfo("3ch", 3, 1), ModeInfo("Pixels", 24, 8)))
    assert read_text(found).plain == (
        "Acme\nBar\n\n2 modes\n3ch · 3 channels\nPixels · 24 channels · 8 elements"
    )
    assert read_text(ProfileRead(problem="no mode busk can use")).plain == (
        "busk cannot import it:\nno mode busk can use"
    )


# ---------------------------------------------------------------- the dialog


def test_it_starts_in_the_folder_on_the_name_given_else_on_the_first(tmp_path: Path) -> None:
    folder = rig(tmp_path)

    async def body(pilot: Pilot[int], opened: Opened) -> None:
        assert opened.names() == ["acme", "beta", "notes.txt"]  # no .git
        assert opened.on() == "beta"
        assert opened.dialog.path.text == str(folder)
        parent = opened.dialog.parent_list
        names = [entry.name for entry in opened.dialog.parent_entries]
        assert parent.highlighted is not None
        assert names[parent.highlighted] == "rig"

    with_picker(folder, body, chosen="beta")

    async def first(pilot: Pilot[int], opened: Opened) -> None:
        assert opened.dialog.folder == folder / "acme"  # the nearest that exists
        assert opened.on() == "broken.json"

    with_picker(folder / "acme" / "gone" / "deeper", first, chosen="deeper")


def test_arrows_go_into_a_folder_and_up_onto_the_folder_left(tmp_path: Path) -> None:
    folder = rig(tmp_path)

    async def body(pilot: Pilot[int], opened: Opened) -> None:
        dialog = opened.dialog
        await pilot.press("right")
        assert dialog.folder == folder / "acme"
        assert opened.names() == ["broken.json", "dim.json", "README.md"]
        await pilot.press("down", "right")  # a file: nothing
        assert (dialog.folder, opened.on()) == (folder / "acme", "dim.json")
        await pilot.press("left")
        assert (dialog.folder, opened.on()) == (folder, "acme")
        await pilot.press("pagedown")
        assert opened.on() == "notes.txt"  # the list stops at its end
        await pilot.press("up")
        assert opened.on() == "beta"
        dialog.go(Path("/"))
        await pilot.press("left")
        assert dialog.folder == Path("/")
        assert dialog.parent_list.option_count == 0
        assert opened.closed == []

    with_picker(folder, body)


def test_typing_filters_and_backspace_takes_a_letter_back_then_goes_up(tmp_path: Path) -> None:
    folder = rig(tmp_path)

    async def body(pilot: Pilot[int], opened: Opened) -> None:
        dialog = opened.dialog
        await pilot.press("right", *"dim")
        assert opened.names() == ["dim.json"]
        await pilot.press(*"x")
        assert opened.names() == []
        assert str(dialog.none.content) == "nothing has 'dimx'"
        assert dialog.none.display
        assert not dialog.list.display
        await pilot.press("backspace")
        assert (dialog.field.value, opened.names()) == ("dim", ["dim.json"])
        await pilot.press("backspace", "backspace", "backspace")
        assert opened.names() == ["broken.json", "dim.json", "README.md"]
        assert opened.on() == "dim.json"  # the row it was on stays
        await pilot.press("backspace")  # an empty filter: up
        assert (dialog.folder, opened.on()) == (folder, "acme")
        await pilot.press(*"be", "right")
        assert dialog.folder == folder / "beta"
        assert dialog.field.value == ""  # each folder starts unfiltered
        assert str(dialog.none.content) == "empty"
        await pilot.press("left", ".")
        assert opened.names() == [".git", "notes.txt"]

    with_picker(folder, body)


def test_enter_goes_into_a_folder_and_chooses_a_profile_file_but_no_other(
    tmp_path: Path,
) -> None:
    folder = rig(tmp_path)

    async def body(pilot: Pilot[int], opened: Opened) -> None:
        await pilot.press(*"notes", "enter")
        assert opened.closed == []  # dimmed: nothing
        await pilot.press("backspace", "backspace", "backspace", "backspace", "backspace")
        assert opened.on() == "notes.txt"
        await pilot.press("up", "up", "enter")
        assert opened.dialog.folder == folder / "acme"
        await pilot.press(*"broken", "enter")  # busk will say why
        await pilot.pause()
        assert opened.closed == [folder / "acme" / "broken.json"]

    with_picker(folder, body)


def test_esc_closes_it_with_nothing(tmp_path: Path) -> None:
    async def body(pilot: Pilot[int], opened: Opened) -> None:
        await pilot.press("escape")
        await pilot.pause()
        assert opened.closed == [None]

    with_picker(rig(tmp_path), body)


def test_the_preview_shows_a_folder_and_what_busk_reads_in_a_file(tmp_path: Path) -> None:
    folder = rig(tmp_path)

    async def body(pilot: Pilot[int], opened: Opened) -> None:
        assert opened.preview() == "broken.json\ndim.json\nREADME.md"  # acme/
        await pilot.press("down")
        assert opened.preview() == "empty"  # beta/
        await pilot.press("down")
        assert opened.preview() == "not a profile file"
        await pilot.press("up", "up", "right")
        await until(pilot, lambda: opened.preview().startswith("busk cannot import it:\n"))
        assert opened.preview() == (
            "busk cannot import it:\n"
            "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"
        )
        await pilot.press("down")
        await until(pilot, lambda: opened.preview() != "reading…")
        assert opened.preview() == "acme\nacme Test\n\n1 mode\nAll · 1 channel"

    with_picker(folder, body)


def test_busk_reads_one_file_at_a_time_and_each_once(tmp_path: Path) -> None:
    folder = rig(tmp_path) / "acme"
    for n in range(4):
        (folder / f"more{n}.json").write_text(json.dumps(DIMMER))
    bridge = CountingBridge()

    async def body(pilot: Pilot[int], opened: Opened) -> None:
        dialog = opened.dialog

        def shown() -> bool:
            return dialog.reading is None and dialog.folder / str(opened.on()) in dialog.read

        await pilot.press("down", "down", "down", "down")
        await until(pilot, shown)
        assert opened.preview() == "acme\nacme Test\n\n1 mode\nAll · 1 channel"  # more2
        await pilot.press("up", "up", "up", "up")
        await until(pilot, shown)
        assert opened.preview().startswith("busk cannot import it:")  # broken
        assert bridge.most == 1
        assert len(bridge.asked) == len(set(bridge.asked))
        assert bridge.asked[0] == folder / "broken.json"
        assert folder / "more2.json" in bridge.asked
        assert folder / "more3.json" not in bridge.asked

    with_picker(folder, body, bridge=bridge)


def test_a_read_that_comes_after_the_picker_closed_does_no_harm(tmp_path: Path) -> None:
    """What it asks then never reaches the app: the picker is closed."""

    async def body(pilot: Pilot[int], opened: Opened) -> None:
        dialog = opened.dialog
        dialog.reading = dialog.folder / "dim.json"
        await pilot.press("escape")
        await pilot.pause()
        dialog._read(ProfileRead(problem="late"))
        await pilot.pause()
        assert opened.closed == [None]

    with_picker(rig(tmp_path) / "acme", body)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads every folder")
def test_a_folder_that_cannot_be_read_says_why(tmp_path: Path) -> None:
    folder = rig(tmp_path)
    (folder / "beta").chmod(0)

    async def body(pilot: Pilot[int], opened: Opened) -> None:
        dialog = opened.dialog
        await pilot.press("down")
        assert opened.preview() == "cannot read it: Permission denied"
        await pilot.press("right")
        assert dialog.folder == folder / "beta"
        assert str(dialog.none.content) == "cannot read it: Permission denied"
        await pilot.press("left")
        assert (dialog.folder, opened.on()) == (folder, "beta")

    try:
        with_picker(folder, body)
    finally:
        (folder / "beta").chmod(0o755)


def test_a_click_in_the_middle_is_enter_and_on_the_left_goes_up_onto_that_row(
    tmp_path: Path,
) -> None:
    folder = rig(tmp_path)

    async def body(pilot: Pilot[int], opened: Opened) -> None:
        dialog = opened.dialog
        await pilot.click(dialog.list, offset=(2, 1))  # beta/
        await pilot.pause()
        assert dialog.folder == folder / "beta"
        names = [entry.name for entry in dialog.parent_entries]
        await pilot.click(dialog.parent_list, offset=(2, names.index("acme")))
        await pilot.pause()
        assert (dialog.folder, opened.on()) == (folder, "acme")
        await pilot.click(dialog.list, offset=(2, 0))
        await pilot.click(dialog.list, offset=(2, 1))  # dim.json
        await pilot.pause()
        assert opened.closed == [folder / "acme" / "dim.json"]

    with_picker(folder, body)


def test_it_fits_a_terminal_of_100_by_30_and_cuts_a_long_path_at_its_start(
    tmp_path: Path,
) -> None:
    folder = rig(tmp_path / ("long" * 30))

    async def body(pilot: Pilot[int], opened: Opened) -> None:
        dialog = opened.dialog
        box = dialog.query_one(Vertical).region
        assert box.right <= 100
        assert box.bottom <= 30
        assert dialog.list.size.height == ROWS
        assert dialog.preview.region.right < box.right
        shown = dialog.path.render().plain
        assert shown.startswith("…")
        assert shown.endswith("/rig")
        assert len(shown) == dialog.path.size.width

    with_picker(folder, body, size=(100, 30))


# ------------------------------------------------------------ the modes


@pytest.mark.parametrize(
    ("mode", "title", "note"),
    [
        ("profile", "IMPORT PROFILE", "busk imports an OFL .json, a .gdtf"),
        ("script", "IMPORT SCRIPT", "busk runs a .busk script"),
        ("save", "SAVE AS", "busk saves a .show or a .json file"),
    ],
)
def test_each_mode_has_its_title_and_says_what_it_takes(
    tmp_path: Path, mode: Mode, title: str, note: str
) -> None:
    async def body(pilot: Pilot[int], opened: Opened) -> None:
        assert opened.dialog.query_one(Vertical).border_title == title
        notes = [str(note.content) for note in opened.dialog.query(".note")]
        assert notes[0].startswith(note)

    with_picker(tmp_path, body, mode=mode)


def scripts(root: Path) -> Path:
    """``root/scripts``: ``sub/``, ``build.busk`` (a comment, then lines), ``notes.txt``."""
    folder = root / "scripts"
    (folder / "sub").mkdir(parents=True)
    (folder / "build.busk").write_text("# Build the rig\n#  two lines\n\nsel group 1\n")
    (folder / "notes.txt").write_text("x")
    return folder


def test_a_script_picker_takes_a_busk_file_and_shows_its_first_lines(tmp_path: Path) -> None:
    folder = scripts(tmp_path)

    async def body(pilot: Pilot[int], opened: Opened) -> None:
        dialog = opened.dialog
        assert opened.names() == ["sub", "build.busk", "notes.txt"]
        assert entry_text(Entry("notes.txt", False), dialog.kinds).style == colors.DIM
        await pilot.press("down")
        assert opened.preview() == "# Build the rig\n#  two lines\n\nsel group 1"
        text = script_text(folder / "build.busk")
        styles = {text.plain[span.start : span.end]: span.style for span in text.spans}
        assert (styles["# Build the rig"], styles["sel group 1"]) == (colors.DIM, colors.FG)
        await pilot.press("down")
        assert opened.preview() == "not a script"
        await pilot.press("enter")
        assert opened.closed == []  # dimmed: nothing
        await pilot.press(*"bui", "enter")  # typing filters, as for a profile
        await pilot.pause()
        assert opened.closed == [folder / "build.busk"]

    with_picker(folder, body, mode="script")


def test_a_scripts_preview_is_its_first_rows_and_an_empty_one_says_so(tmp_path: Path) -> None:
    folder = tmp_path / "scripts"
    folder.mkdir()
    (folder / "a.busk").write_text("".join(f"go {n}\n" for n in range(1, 40)))
    (folder / "b.busk").write_text("")

    async def body(pilot: Pilot[int], opened: Opened) -> None:
        assert opened.preview().splitlines() == [f"go {n}" for n in range(1, ROWS + 1)]
        await pilot.press("down")
        assert opened.preview() == "empty"

    with_picker(folder, body, mode="script")


def shows(root: Path) -> Path:
    """``root/shows``: ``old/`` (``rig.show``), ``club.show``, ``fest.json``, ``notes.txt``."""
    folder = root / "shows"
    (folder / "old").mkdir(parents=True)
    (folder / "old" / "rig.show").write_text("{}")
    (folder / "club.show").write_text("{}")
    (folder / "fest.json").write_text("{}")
    (folder / "notes.txt").write_text("x")
    return folder


def test_a_name_saves_as_a_show_file() -> None:
    assert save_name("copy") == "copy.show"
    assert save_name(" late night ") == "late night.show"
    assert save_name("copy.json") == "copy.json"
    assert save_name("COPY.SHOW") == "COPY.SHOW"  # busk reads the suffix in any case
    assert save_name("club.v2") == "club.v2.show"


def test_saving_starts_on_the_shows_name_on_no_row_and_enter_saves_it(tmp_path: Path) -> None:
    folder = shows(tmp_path)
    own = folder / "club.show"

    async def body(pilot: Pilot[int], opened: Opened) -> None:
        dialog = opened.dialog
        assert (dialog.folder, dialog.field.value, opened.on()) == (folder, "club.show", None)
        assert opened.names() == ["old", "club.show", "fest.json", "notes.txt"]
        assert opened.preview() == "Enter saves the show to its own file"
        await pilot.press("enter")
        await pilot.pause()
        assert opened.closed == [own]

    with_picker(folder, body, "club.show", mode="save", own=own)


def test_a_name_typed_saves_a_copy_with_show_added(tmp_path: Path) -> None:
    folder = shows(tmp_path)

    async def body(pilot: Pilot[int], opened: Opened) -> None:
        await pilot.press("ctrl+u")
        assert opened.preview() == "type a name"
        await pilot.press("enter")
        assert opened.closed == []  # no name: nothing
        await pilot.press(*"copy")
        assert opened.preview() == (
            "Enter saves a copy of the show as copy.show\n\n"
            "a show of its own: club.show stays as it was saved"
        )
        await pilot.press("enter")
        await pilot.pause()
        assert opened.closed == [folder / "copy.show"]

    with_picker(folder, body, "club.show", mode="save", own=folder / "club.show")


def test_the_cursor_on_a_show_file_takes_its_name_and_enter_goes_into_a_folder(
    tmp_path: Path,
) -> None:
    folder = shows(tmp_path)

    async def body(pilot: Pilot[int], opened: Opened) -> None:
        dialog = opened.dialog
        await pilot.press("down")  # old/: the name stays
        assert (opened.on(), dialog.field.value, opened.preview()) == (
            "old",
            "club.show",
            "rig.show",
        )
        await pilot.press("down", "down")
        assert (opened.on(), dialog.field.value) == ("fest.json", "fest.json")
        assert opened.preview() == (
            "fest.json exists: Enter asks before it replaces it, and busk keeps a backup of it"
        )
        await pilot.press("down")  # not a show file: the name stays, and Enter does nothing
        assert (opened.on(), dialog.field.value, opened.preview()) == (
            "notes.txt",
            "fest.json",
            "not a show file",
        )
        await pilot.press("enter")
        assert opened.closed == []
        await pilot.press("up", "up", "up")  # over club.show, which takes its name, onto old/
        assert (opened.on(), dialog.field.value) == ("old", "club.show")
        await pilot.press("enter")  # into old/, the name kept, on no row
        assert (dialog.folder, dialog.field.value, opened.on()) == (
            folder / "old",
            "club.show",
            None,
        )
        await pilot.press("left")  # up, on no row
        assert (dialog.folder, opened.on()) == (folder, None)
        await pilot.press("right")  # on no row: nothing
        assert dialog.folder == folder
        await pilot.press("up")  # from the name onto the last row
        assert opened.on() == "notes.txt"
        await pilot.press(*"late")  # typing leaves the rows
        assert opened.on() is None
        await pilot.press("enter")
        await pilot.pause()
        assert opened.closed[0] is not None
        assert opened.closed[0].parent == folder
        assert opened.closed[0].name.endswith("late.show")

    with_picker(folder, body, "club.show", mode="save")


def test_saving_backspace_takes_a_letter_then_goes_up(tmp_path: Path) -> None:
    folder = shows(tmp_path) / "old"

    async def body(pilot: Pilot[int], opened: Opened) -> None:
        dialog = opened.dialog
        await pilot.press("end", "backspace")
        assert dialog.field.value == "a"
        await pilot.press("backspace", "backspace")
        assert (dialog.folder, opened.on()) == (folder.parent, None)

    with_picker(folder, body, "ab", mode="save")


def test_a_name_that_is_a_folder_is_not_saved(tmp_path: Path) -> None:
    folder = shows(tmp_path)
    (folder / "odd.show").mkdir()

    async def body(pilot: Pilot[int], opened: Opened) -> None:
        assert opened.preview() == "odd.show is a folder"
        await pilot.press("enter")
        assert opened.closed == []

    with_picker(folder, body, "odd.show", mode="save")
