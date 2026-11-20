"""The file picker of the profile picker's ``[import…]`` (``busk_tui.widgets.file_picker``):
three columns, the profile picker's keys, and a preview of what busk reads in a file."""

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

from busk_tui.model import ModeInfo, ProfileRead
from busk_tui.shell import BuskApp
from busk_tui.widgets.file_picker import (
    ROWS,
    Entry,
    FileDialog,
    entry_text,
    filtered,
    home_text,
    listing,
    read_text,
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
) -> None:
    """Run the app with a file picker on ``folder`` (on ``chosen``)."""
    app = make_app(bridge or FakeBridge())

    async def main(pilot: Pilot[int]) -> None:
        dialog = FileDialog(folder, chosen)
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
    assert Entry("spot.gdtf", False).importable()
    assert Entry("dim.json", False).importable()
    assert not Entry("dim.json", True).importable()  # a folder
    assert not Entry("spot.GDTF", False).importable()  # busk reads it as JSON
    assert not Entry("notes.txt", False).importable()
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
