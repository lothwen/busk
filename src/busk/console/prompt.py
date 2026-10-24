"""Tab completion and ``?`` at the console prompt (``busk run`` on a terminal).

Both come from the parser, through :meth:`Console.expected
<busk.console.console.Console.expected>` (the facades' ``expected``, GAP-20
of ``docs/dev/tui/engine-gaps.md``), so they follow the grammar and know
the show and the libraries, and a frontend completes what the prompt
completes. Tab completes the word being typed: a keyword, or a name in
quotes (a master, a surface, a profile, a template). Where there is nothing
to complete, it prints what may come next, as ``?`` does. ``?`` prints the
words and values that may come next, ``<Enter>`` when the line runs as it
is, or the mistake that stops it. Then it prints the forms of the command
from ``help``, and gives the line back as it was.

With GNU readline, ``?`` is a key: it never goes into the line (Ctrl+V ``?``
types one). libedit (the readline of macOS and of uv's Pythons) cannot bind
it, so there a line ending in ``?`` prints the help when entered.
"""

from __future__ import annotations

import contextlib
import ctypes
import re
import shutil
from collections.abc import Mapping, Sequence
from types import ModuleType, TracebackType
from typing import TYPE_CHECKING, Final

from busk.console.parser import HELP, ParseError, tokenize

if TYPE_CHECKING:
    from busk.console.console import Console

PROMPT: Final = "busk> "

_DELIMITERS: Final = " \t,"
_KEYWORD: Final = re.compile(r"[a-z][a-zA-Z]*(?:\|[a-z][a-zA-Z]*)*")  # `on|off`, not `N`
_PLACEHOLDER: Final = re.compile(r"<[^<>\s]+>")
_DEFINITION: Final = re.compile(r"(<[^<>\s]+>) =")


def split(before: str) -> tuple[str, str]:
    """``before``, the line up to the cursor, as the text before the word
    being typed and that word (from its opening quote, for a name)."""
    start, quoted, escaped = 0, False, False
    for k, char in enumerate(before):
        if escaped:
            escaped = False
        elif quoted:
            escaped = char == "\\"
            if char == '"':
                quoted, start = False, k + 1
        elif char == '"':
            quoted, start = True, k
        elif char in _DELIMITERS:
            start = k + 1
    return before[:start], before[start:]


def hints(console: Console, before: str, width: int | None = None) -> list[str]:
    """What ``?`` prints for ``before``, the line up to the cursor: what may
    come there (or the mistake that stops the line), then :func:`grammar`."""
    expected = console.expected(before)
    word = before[expected.start :]
    if expected.error is not None:
        lines = [f"error: {expected.error}"]
    else:
        items = sorted(expected.words, key=str.lower)
        items += [f"<{value}>" for value in expected.values]
        if expected.runnable and not word:
            items.append("<Enter>")
        width = width or shutil.get_terminal_size().columns
        lines = _flow("next: ", items, width) if items else []
        if not items and word:
            lines = [f"nothing here starts with {word!r}"]
    return lines + grammar(before)


def grammar(line: str) -> list[str]:
    """The lines of ``help`` about the command ``line`` is: the forms its
    words so far fit, each with the notes under it, then the definitions of
    the ``<placeholders>`` they use. Nothing until the command's first word
    is whole."""
    try:
        words = [token.lower for token in tokenize(line)[0]]
    except ParseError:
        return []
    if not words:
        return []
    partial = line[-1] not in _DELIMITERS  # the last word is still being typed
    entries: list[tuple[str, list[str]]] = []  # each form line, with the notes under it
    for text in HELP:
        if text.startswith(" " * 8):
            entries[-1][1].append(text)
        else:
            entries.append((text, []))
    definitions: dict[str, list[str]] = {}
    for _, notes in entries:
        name = None
        for note in notes:
            if note.strip().startswith("|") and name is not None:
                definitions[name].append(note)  # the definition goes on
            elif (match := _DEFINITION.match(note.strip())) is not None:
                name = match[1]
                definitions[name] = [note]
            else:
                name = None
    starts = {  # the words a placeholder's forms start with: <entity> is fixture N, group N…
        name: {form.split()[0] for form in _forms(" ".join(lines).partition(" = ")[2])}
        for name, lines in definitions.items()
    }
    fits = [[(form, _fit(form, words, starts, partial=partial)) for form in _forms(text)]
            for text, _ in entries]  # fmt: skip
    best = max((score for each in fits for _, score in each if score is not None), default=0)
    found: list[str] = []
    for (_, notes), scored in zip(entries, fits, strict=True):
        forms = [form for form, score in scored if score == best]  # the most specific forms
        if forms:
            found += ["    " + " | ".join(forms), *notes]
    for name in dict.fromkeys(_PLACEHOLDER.findall("\n".join(found))):
        lines = definitions.get(name, [])
        if lines and lines[0] not in found:
            found += lines
    return found


def _forms(text: str) -> list[str]:
    """The forms of a grammar line: its parts between `` | `` outside brackets."""
    text = text.strip()
    forms, depth, start = [], 0, 0
    for k, char in enumerate(text):
        depth += (char in "[(") - (char in "])")
        if depth == 0 and text.startswith(" | ", k):
            forms.append(text[start:k])
            start = k + 3
    forms.append(text[start:])
    return forms


def _fit(
    form: str, words: Sequence[str], starts: Mapping[str, set[str]], *, partial: bool
) -> int | None:
    """How a line's ``words`` fit ``form``: the number of its keywords they
    match after the first, or ``None`` if they do not fit. Each keyword of
    the form, up to its first optional part, must be the word typed there
    (placeholders take any, but one that starts the form only the words its
    forms start with, ``starts``). A ``partial`` last word, after the first,
    need only start it."""
    last = len(words) - 1 if partial and len(words) > 1 else -1
    score = 0
    for k, (want, typed) in enumerate(zip(form.split(), words, strict=False)):
        if want.startswith("["):
            break
        if k == 0 and want.startswith("<") and typed not in starts.get(want, ()):
            return None
        if _KEYWORD.fullmatch(want):
            options = want.lower().split("|")
            if not any(o == typed or (k == last and o.startswith(typed)) for o in options):
                return None
            score += k > 0
    return score


def _flow(label: str, items: Sequence[str], width: int) -> list[str]:
    """``items`` after ``label``, two spaces apart, in lines of at most ``width``."""
    lines: list[str] = []
    line = ""
    for item in items:
        if line and len(label) + len(line) + 2 + len(item) > width:
            lines.append(line)
            line = ""
        line = f"{line}  {item}" if line else item
    lines.append(line)
    return [(label if k == 0 else " " * len(label)) + text for k, text in enumerate(lines)]


class Editing:
    """Line editing at the prompt with :mod:`readline`, where it exists:
    history, and while a command line is read (``with editing:``) Tab
    completion and ``?``. The questions (``save …? [y/n]``) keep plain input."""

    def __init__(self, console: Console) -> None:
        self.console = console
        self._matches: list[str] = []
        self._help: list[str] = []
        self.readline: ModuleType | None = None
        self.libedit = False
        with contextlib.suppress(ImportError):
            import readline

            self.readline = readline
            self.libedit = "libedit" in (readline.__doc__ or "")
            readline.set_completer_delims(_DELIMITERS)
            if self.libedit:
                readline.parse_and_bind("bind ^I rl_complete")
            else:
                readline.parse_and_bind("tab: complete")
                readline.parse_and_bind("set show-all-if-ambiguous on")
                readline.set_completion_display_matches_hook(self._display)

    @property
    def question_key(self) -> bool:
        """Whether ``?`` is a key (GNU readline); elsewhere a line ending in
        ``?`` asks for help (:meth:`asks`)."""
        return self.readline is not None and not self.libedit

    def typed(self) -> str:
        """The text on the line when Ctrl+C came, where readline can tell.
        GNU readline can. libedit may still hold an earlier line, so the line
        counts as empty there, as it does without readline."""
        if self.readline is None or self.libedit:
            return ""
        return str(self.readline.get_line_buffer())

    def asks(self, line: str) -> bool:
        """Whether ``line`` asks for help by ending in ``?`` (outside quotes),
        where ``?`` is not a key."""
        line = line.rstrip()
        return not self.question_key and line.endswith("?") and not split(line)[1].startswith('"')

    def __enter__(self) -> None:
        if self.readline is not None:
            self.readline.set_completer(self._complete)
            if self.question_key:
                self.readline.parse_and_bind('"?": possible-completions')

    def __exit__(
        self, kind: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        if self.readline is not None:
            self.readline.set_completer(None)
            if self.question_key:
                self.readline.parse_and_bind('"?": self-insert')

    # ------------------------------------------------------------- readline

    def _complete(self, text: str, state: int) -> str | None:
        """The readline completer: the ``state``-th match for ``text``."""
        if state == 0:
            self._matches = self._find(text)
        return self._matches[state] if state < len(self._matches) else None

    def _find(self, text: str) -> list[str]:
        """The matches for ``text``, readline's word (it splits at spaces and
        commas, not at quotes): each completion of the word being typed
        followed by a space, written from where ``text`` starts. Where Tab
        cannot complete (and for ``?``), it shows the help instead."""
        readline = self.readline
        assert readline is not None
        before = readline.get_line_buffer()[: readline.get_endidx()]
        expected = self.console.expected(before)
        head, word = before[: expected.start], before[expected.start :]
        found = [w + " " for w in expected.words]
        if self.libedit or readline.get_completion_type() != ord("?"):  # Tab, not ?
            alone = not (expected.values or expected.runnable or expected.error)
            if len(found) == 1 and (word or alone):
                return [self._from(found[0], head, readline.get_begidx())]
            longer = len(_common(found)) > len(word)
            if len(found) > 1 and (longer or not self.libedit):  # readline lists them (the help)
                self._help = hints(self.console, before)
                return [self._from(match, head, readline.get_begidx()) for match in found]
        self._help = hints(self.console, before)
        if self.libedit:  # no display hook: print it here, then the line again
            print("\n" + "\n".join(self._help), flush=True)
            print(PROMPT + readline.get_line_buffer(), end="", flush=True)
            return []
        return [text + "1", text + "2"]  # two: readline calls _display, and keeps the line

    @staticmethod
    def _from(match: str, head: str, begin: int) -> str:
        """``match``, a completion of the word that starts after ``head``, as
        readline wants it: from ``begin``, where readline's own word starts."""
        start = len(head)
        return head[begin:] + match if begin < start else match[begin - start :]

    def _display(self, substitution: str, matches: Sequence[str], longest: int) -> None:
        """The display hook (GNU readline): print the help, then the line again."""
        print("\n" + "\n".join(self._help), flush=True)
        readline = self.readline
        assert readline is not None
        try:
            library = ctypes.CDLL(getattr(readline, "__file__", None))
            library.rl_forced_update_display()
            ctypes.c_int.in_dll(library, "rl_display_fixed").value = 1
        except (OSError, AttributeError, ValueError):
            print(PROMPT + readline.get_line_buffer(), end="", flush=True)


def _common(words: Sequence[str]) -> str:
    """The longest start all ``words`` share, as readline finds it (any case)."""
    if not words:
        return ""
    first, last = min(words), max(words)
    k = 0
    while k < min(len(first), len(last)) and first[k] == last[k]:
        k += 1
    return first[:k]
