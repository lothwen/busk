"""Text for the pages, made from view models: no busk, no Textual.

The selection is written as the operator types it (``sel fixture 101 thru
104, fixture 301.2``), without the words: ``101 thru 104, 301.2``.
"""

from __future__ import annotations

from collections.abc import Sequence

from busk_tui.model import FixtureInfo


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
