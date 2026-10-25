"""Text for the pages, made from view models: no busk, no Textual.

The selection is written as the operator types it (``sel fixture 101 thru
104, fixture 301.2``), without the words: ``101 thru 104, 301.2``. Times,
phases and stored values are written as busk's lines take them.
"""

from __future__ import annotations

from collections.abc import Sequence

from busk_tui import attributes
from busk_tui.model import CueInfo, FixtureInfo, StoredValue, Targets


def selection_text(selection: Sequence[tuple[int, int]], fixtures: Sequence[FixtureInfo]) -> str:
    """``selection`` (``(number, element)`` pairs, in order), compressed: a
    fixture whose elements are all selected, in order, is its number; runs
    of numbers, and of one fixture's elements, are ``thru``. Empty for an
    empty selection."""
    elements = {fixture.number: fixture.elements for fixture in fixtures}
    tokens: list[tuple[int, int | None]] = []  # (number, element), element None: the fixture
    index = 0
    while index < len(selection):
        number, _ = selection[index]
        count = elements.get(number, 1)
        whole = [(number, element) for element in range(1, count + 1)]
        if list(selection[index : index + count]) == whole:
            tokens.append((number, None))
            index += count
        else:
            tokens.append(selection[index])
            index += 1
    parts: list[str] = []
    start = 0
    while start < len(tokens):
        end = start
        while end + 1 < len(tokens) and _follows(tokens[end], tokens[end + 1]):
            end += 1
        first, last = _token(tokens[start]), _token(tokens[end])
        parts.append(first if end == start else f"{first} thru {last}")
        start = end + 1
    return ", ".join(parts)


def _follows(before: tuple[int, int | None], after: tuple[int, int | None]) -> bool:
    if before[1] is None and after[1] is None:
        return after[0] == before[0] + 1
    if before[1] is not None and after[1] is not None:
        return after[0] == before[0] and after[1] == before[1] + 1
    return False


def _token(token: tuple[int, int | None]) -> str:
    number, element = token
    return str(number) if element is None else f"{number}.{element}"


def seconds(value: float) -> str:
    """A time as busk takes it: ``3``, ``0.5``."""
    return f"{round(value, 2):g}"


def pair_text(first: float, second: float) -> str:
    """An in and an out time as ``cue L/C time`` takes them: ``3`` when they
    are the same, else ``1/3``."""
    if first == second:
        return seconds(first)
    return f"{seconds(first)}/{seconds(second)}"


def time_text(cue: CueInfo) -> str:
    """A cue's fade times, and its families' own: ``2, position 4``."""
    parts = [pair_text(cue.fadeIn, cue.fadeOut)]
    parts += [
        f"{family} {seconds(fade)}" + (f" delay {seconds(delay)}" if delay else "")
        for family, fade, delay in cue.families
    ]
    return ", ".join(parts)


def delay_text(cue: CueInfo) -> str:
    """A cue's delays; empty without one."""
    if not cue.delayIn and not cue.delayOut:
        return ""
    return pair_text(cue.delayIn, cue.delayOut)


def targets_text(targets: Targets, fixtures: Sequence[FixtureInfo]) -> str:
    """A group by its name, fixed elements compressed (``101 thru 104``)."""
    if targets.group is not None:
        return targets.group.name
    return selection_text(targets.elements, fixtures)


def phase_text(phase: tuple[float, float]) -> str:
    """An effect's phase spread: ``0→360``."""
    return f"{phase[0]:g}→{phase[1]:g}"


def stored_text(value: StoredValue) -> str:
    """A stored value as the show holds it: ``60%``, the preset's name,
    ``spread 0%→100%``, ``per target``; a colour by its components."""
    if value.kind == "preset":
        return value.preset or "preset"
    if value.kind == "perTarget":
        return "per target"
    if value.kind == "spread":
        if value.value is None or value.to is None or isinstance(value.value, tuple):
            return "spread"
        first = _value_text(value.attribute, value.value)
        return f"spread {first}→{_value_text(value.attribute, value.to)}"
    if value.value is None:
        return value.kind
    return _value_text(value.attribute, value.value)


def _value_text(attribute: str, value: float | str | tuple[tuple[str, float], ...]) -> str:
    if isinstance(value, tuple):
        return attributes.rgb_text(value)
    return attributes.summary_text(attribute, value)
