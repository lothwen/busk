"""The lines the UI builds (``busk_tui.commands``): their format, their
performance marks, and the contract test: busk accepts every one of them on
the club-night show (plan §4.6)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

import busk
from busk_tui import commands
from busk_tui.commands import Line
from busk_tui.pages.placeholder import PLANNED

BUILDERS: dict[str, tuple[Callable[[], Line], bool]] = {
    # name: (builder, whether busk runs its line as a performance line, GAP-12)
    "help": (commands.help_, False),
    "undo": (commands.undo, False),
    "redo": (commands.redo, False),
    "save": (commands.save, False),
}

PERFORMANCE_WORDS = {
    "go", "back", "goto", "release", "fader", "flash", "toggle", "button", "gm", "master",
    "blackout", "tap", "bpm", "page", "output",
}  # fmt: skip
"""The first words of busk's performance lines (``LiveShow.execute``);
``master add`` and ``page add`` are edits."""


@pytest.fixture
def show(club_path: Path, tmp_path: Path) -> busk.OfflineShow:
    """A club-night show of the test's own, saved to a file of its own."""
    document, _ = busk.load_show(club_path)
    return busk.OfflineShow(document, path=tmp_path / "club.show")


def test_levels_are_whole_percent() -> None:
    assert commands.percent(0.72) == "72%"
    assert commands.percent(0.004) == "0%"
    assert commands.percent(0.996) == "100%"
    assert commands.percent(1.5) == "100%"
    assert commands.percent(-0.2) == "0%"


def test_names_are_quoted_and_a_quote_in_one_is_refused() -> None:
    assert commands.quoted("Grand Master") == '"Grand Master"'
    with pytest.raises(ValueError, match="double quote"):
        commands.quoted('Say "hi"')


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_each_builder_is_marked_as_busk_runs_it(name: str) -> None:
    builder, performance = BUILDERS[name]
    line = builder()
    assert line.performance is performance
    first = line.text.split()[0]
    assert (first in PERFORMANCE_WORDS) is performance


def test_busk_accepts_every_builders_line(show: busk.OfflineShow) -> None:
    assert show.execute("sel group 1").ok  # something to undo and redo
    for name in ("help", "undo", "redo", "save"):
        builder, _ = BUILDERS[name]
        reply = show.execute(builder().text)
        assert reply.ok, (name, reply.text)


def test_the_placeholder_lines_are_busks(show: busk.OfflineShow) -> None:
    """A whole line runs; a line to finish (ending in a space) is one busk
    takes so far."""
    for _, lines in PLANNED.values():
        for line in lines:
            if line.endswith(" "):
                answer = show.expected(line)
                assert answer.error is None, (line, answer.error)
                assert answer.words or answer.values, line
            elif line != "output off":  # asked first; runs too, but darkens the show
                reply = show.execute(line)
                assert reply.ok, (line, reply.text)
    assert show.confirmation("output off") is not None
