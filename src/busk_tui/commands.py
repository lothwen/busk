"""Every console line the UI sends, built in one place.

Each builder returns a :class:`Line`: its text, in busk's syntax, and whether
it is a *performance* line, one the engine carries out and that never waits
for another thread's line (``go``, ``fader``, ``gm`` …, see busk's
``LiveShow.execute``). The bridge sends performance lines on its controls
worker, the others on its ordered worker.

``tests/tui/test_tui_commands.py`` runs every builder's line on the
club-night show (the contract test), so a line busk would refuse fails
there, not on stage. Each phase adds its builders here and to that test.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Line:
    text: str
    performance: bool = False


def percent(level: float) -> str:
    """A level 0..1 as busk reads a percentage, in whole percent: ``72%``."""
    return f"{round(max(0.0, min(1.0, level)) * 100)}%"


def quoted(name: str) -> str:
    """A name as busk reads it, in double quotes. busk has no escape for a
    quote inside a name, so such a name is refused (:class:`ValueError`)."""
    if '"' in name:
        raise ValueError(f"a name with a double quote cannot be typed: {name!r}")
    return f'"{name}"'


def help_() -> Line:
    return Line("help")


def undo() -> Line:
    return Line("undo")


def redo() -> Line:
    return Line("redo")


def save() -> Line:
    return Line("save")
