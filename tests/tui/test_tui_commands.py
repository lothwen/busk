"""The lines the UI builds (``busk_tui.commands``): their format, their
performance marks, and the contract test: busk accepts every one of them on
the club-night show (plan §4.6)."""

from __future__ import annotations

from pathlib import Path

import pytest

import busk
from busk_tui import commands
from busk_tui.commands import Line
from busk_tui.pages.placeholder import PLANNED

BUILDERS: dict[str, tuple[Line, str, bool]] = {
    # name: (a line it builds, that line's text, whether busk runs it as a performance line)
    "help": (commands.help_(), "help", False),
    "undo": (commands.undo(), "undo", False),
    "redo": (commands.redo(), "redo", False),
    "save": (commands.save(), "save", False),
    "go": (commands.go(3), "go 3", True),
    "back": (commands.back(3), "back 3", True),
    "release": (commands.release(9), "release 9", True),
    "release_all": (commands.release_all(), "release all", True),
    "fader": (commands.fader(3, 0.72), "fader 3 72%", True),
    "flash on": (commands.flash(3, True), "flash 3 on", True),
    "flash off": (commands.flash(3, False), "flash 3 off", True),
    "gm": (commands.gm(0.8), "gm 80%", True),
    "master": (commands.master("Wash level", 0.4), 'master "Wash level" 40%', True),
    "blackout on": (commands.blackout(True), "blackout on", True),
    "blackout off": (commands.blackout(False), "blackout off", True),
    "output on": (commands.output(True), "output on", True),
    "output off": (commands.output(False), "output off", True),
    "tap": (commands.tap("Speed 1"), 'tap "Speed 1"', True),
    "bpm": (commands.bpm("Speed 1", 120.5), 'bpm "Speed 1" 120.5', True),
    "page next": (commands.page(1), "page next", True),
    "page prev": (commands.page(-1), "page prev", True),
    "sel group": (commands.sel_group(2), "sel group 2", False),
    "sel + group": (commands.sel_group(1, add=True), "sel + group 1", False),
    "preset": (commands.preset("color", 1), "preset color 1", False),
    "effect stop": (commands.effect_stop("fx5"), "effect stop fx5", False),
    "effect run": (commands.effect_run("fx5"), "effect run fx5", False),
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


def test_numbers_have_two_decimals_at_most() -> None:
    assert commands.number(120.0) == "120"
    assert commands.number(120.456) == "120.46"
    assert commands.number(99.5) == "99.5"


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_each_builder_is_marked_as_busk_runs_it(name: str) -> None:
    line, text, performance = BUILDERS[name]
    assert line.text == text
    assert line.performance is performance
    first = line.text.split()[0]
    assert (first in PERFORMANCE_WORDS) is performance


def test_busk_accepts_every_builders_line(show: busk.OfflineShow) -> None:
    assert show.execute("sel group 1").ok  # something to undo and redo, an effect to stop
    assert show.execute('effect add "Circle" id fx5').ok
    for name, (line, _, _) in BUILDERS.items():
        reply = show.execute(line.text)
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
