"""The hint row under the prompt, and Tab completion (spec §7.2, plan §2.1).

The hint row has two parts:

* what may come at the cursor, from the engine's ``expected(line)``: ``next:
  …`` with the words, the ``<values>`` and ``<Enter>``, or the ``error: …``
  that stops the line, as ``busk run``'s ``?`` shows them;
* the syntax: the top-level lines of ``help`` (4-space indent) whose
  alternatives (split on `` | ``) start with the first word typed, up to two,
  those naming more of the words typed first. While the first word is typed
  and has no such line, the commands it starts (the engine's), or ``unknown
  command``.

The help text is the engine's, shown as it is; only its layout (the indent
and the `` | ``) is read. If its format changes, the syntax part shows less,
never something wrong, and completion is the engine's either way.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from busk_tui.model import Completion

EMPTY_HINT = "type a command · help for syntax · clicks in the UI echo the command they run"


class HelpIndex:
    """The top-level lines of ``help``, by the first word of each alternative."""

    def __init__(self, help_lines: Sequence[str]) -> None:
        self._lines: dict[str, list[str]] = {}
        for text in help_lines:
            if not text.startswith("    ") or text.startswith("     "):
                continue  # only the 4-space forms, not the notes under them
            form = text.strip()
            for alternative in form.split(" | "):
                word = alternative.split(maxsplit=1)[0] if alternative.strip() else ""
                if word.isalpha() and form not in self._lines.setdefault(word, []):
                    self._lines[word].append(form)

    def syntax(self, line: str, limit: int = 2) -> list[str]:
        """Up to ``limit`` forms for the command of ``line``: those that name
        most of its words first, in help order among equals."""
        words = line.split()
        if not words:
            return []
        forms = self._lines.get(words[0].lower(), [])
        typed = {word.lower() for word in words[1:]}

        def named(form: str) -> int:
            return -len(typed & {word.lower() for word in form.split()})

        return sorted(forms, key=named)[:limit]


@dataclass(frozen=True, slots=True)
class Hint:
    """The hint row: ``expected`` (what may come at the cursor; an error
    when ``error``), then ``syntax``."""

    expected: str = ""
    error: bool = False
    syntax: str = ""


def hint(index: HelpIndex | None, line: str, completion: Completion | None) -> Hint:
    """The hint row for ``line`` (the line up to the cursor), with the
    engine's ``completion`` for it (``None`` before the engine answers)."""
    if not line.strip():
        return Hint(syntax=EMPTY_HINT)
    syntax = "    ".join(index.syntax(line)) if index is not None else ""
    if " " not in line.lstrip():  # the first word: its syntax, else the commands it starts
        if syntax or completion is None:
            return Hint(syntax=syntax)
        words = completion.words
        return Hint(syntax=" · ".join(words) if words else "unknown command")
    if completion is None:
        return Hint(syntax=syntax)
    if completion.error is not None:
        return Hint(expected=f"error: {completion.error}", error=True, syntax=syntax)
    return Hint(expected=next_words(line, completion), syntax=syntax)


def next_words(line: str, completion: Completion) -> str:
    """``next: …``: the words, ``<values>`` and ``<Enter>`` that may come."""
    word = line[completion.start :]
    items = sorted(completion.words, key=str.lower)
    items += [f"<{value}>" for value in completion.values]
    if completion.runnable and not word:
        items.append("<Enter>")
    if not items:
        return f"nothing here starts with {word!r}" if word else ""
    return "next: " + " ".join(items)


@dataclass(frozen=True, slots=True)
class Completed:
    """What Tab does: the new line and cursor, or the candidates to list."""

    line: str
    cursor: int
    candidates: tuple[str, ...] = ()


def complete(line: str, cursor: int, completion: Completion) -> Completed:
    """Tab at ``cursor`` in ``line``, with the engine's ``completion`` for
    ``line[:cursor]``: one word replaces the word being typed, followed by a
    space; several extend it by what they share, and are the candidates."""
    words = completion.words
    start = completion.start
    head, tail = line[:start], line[cursor:]
    if len(words) == 1:
        word = words[0] + ("" if tail.startswith(" ") else " ")
        return Completed(head + word + tail, len(head) + len(word))
    if not words:
        return Completed(line, cursor)
    shared = _shared_prefix(words)
    typed = line[start:cursor]
    if len(shared) > len(typed):
        return Completed(head + shared + tail, len(head) + len(shared), tuple(words))
    return Completed(line, cursor, tuple(words))


def _shared_prefix(words: Sequence[str]) -> str:
    """What the words start with, compared without case, as the first has it."""
    first = words[0]
    length = len(first)
    for word in words[1:]:
        length = min(length, len(word))
        for index in range(length):
            if word[index].lower() != first[index].lower():
                length = index
                break
    return first[:length]
