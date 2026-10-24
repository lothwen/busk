"""Completion and hints (GAP-20 of ``docs/dev/tui/engine-gaps.md``).

``OfflineShow.expected(line)`` and ``LiveShow.expected(line)`` say what may
come at the end of ``line``, the line up to the cursor, as ``busk run``'s
prompt completes it on Tab and shows it on ``?``: the word being typed
starts at ``start``, ``words`` are the keywords and names that may come
there and that it starts (in any case), ``values`` describe the rest, and
``runnable`` and ``error`` are about the line before it. So a frontend
completes every word without a tokenizer of its own. Asking changes nothing.
Appendix A's show, with its masters "Grand Master" and "Speed 1" and its
surface "MIDI Controller".
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from builders import APPENDIX_A, ROOT, load_doc, show_of
from busk import CounterIds, Expected, LiveShow, OfflineShow, Reply, new_show
from busk.compiler.compile import compile_show
from busk.console.parser import COMMANDS, tokenize
from busk.console.prompt import hints
from busk.engine.clock import FakeClock
from busk.engine.link import LocalEngine
from busk.engine.loop import Engine
from busk.persistence.show_file import show_json
from busk.session.library import ProfileLibrary
from test_console_prompt import complete

CLUB_NIGHT = ROOT / "examples" / "club-night.busk"
CID = "0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f"


@pytest.fixture
def offline() -> OfflineShow:
    return OfflineShow(show_of(load_doc(APPENDIX_A)))


def test_an_empty_line_may_start_with_any_command(offline: OfflineShow) -> None:
    assert offline.expected("") == Expected(COMMANDS)
    assert offline.expected("   ") == Expected(COMMANDS, start=3)
    assert {"sel", "go", "fader", "record", "quit", "help"} <= set(COMMANDS)


# (line, words, values, runnable, start): the line is typed up to the cursor
CASES: list[tuple[str, tuple[str, ...], tuple[str, ...], bool, int]] = [
    ("rou", ("route",), (), False, 0),
    ("ROU", ("route",), (), False, 0),  # any case; the word as it is written
    ("route add 1 ", ("sacn", "artnet", "dmxusb"), (), False, 12),
    ("route add 1 sa", ("sacn",), (), False, 12),
    ("route add 1 DMX", ("dmxusb",), (), False, 12),
    ("output o", ("on", "off"), (), False, 7),
    ("output of", ("off",), (), False, 7),
    ('master "', ('"Grand Master"', '"Speed 1"'), (), False, 7),
    ('master "gr', ('"Grand Master"',), (), False, 7),
    ('master "Grand M', ('"Grand Master"',), (), False, 7),  # the space is in the name
    ("master gr", (), (), False, 7),  # a name starts with its quote
    ('tap "Speed 1"', (), (), True, 13),  # whole once its quote closes
    ("sel fixture 101,", ("fixture", "group"), ("a fixture number",), False, 16),
    ("sel fixture 101,gr", ("group",), ("a fixture number",), False, 16),
    ("go 1", (), ("a playback number",), False, 3),  # being typed: runnable once it is whole
    ("go 1 ", (), (), True, 5),
    ("release 1 2", (), ("a time in seconds",), True, 10),  # release 1 runs as it is
    ("cue 10/1 time 3 ease", ("easeIn", "easeOut", "easeInOut"), (), True, 16),
    ("lip", (), (), False, 0),  # nothing starts with it
    ("sel # the he", (), (), False, 10),  # nothing may come in a comment
    ('rename show "a \\" b', (), ("a name in quotes",), False, 12),  # the escaped quote
]  # fmt: skip


@pytest.mark.parametrize(
    ("line", "words", "values", "runnable", "start"), CASES, ids=[case[0] for case in CASES]
)
def test_what_may_come_where_the_word_being_typed_starts(
    offline: OfflineShow,
    line: str,
    words: tuple[str, ...],
    values: tuple[str, ...],
    runnable: bool,
    start: int,
) -> None:
    assert offline.expected(line) == Expected(words, values, runnable, None, start)


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("sel fixture 99 ", "no fixture 99"),
        ("sel fixture 99", None),  # a word being typed is no mistake yet
        ("xyz ", "unknown command 'xyz' (try 'help')"),
        ("xyz", None),
        ('master "Sp', None),  # a name being typed: its quote is still open
        (
            "set intensity +5% ",
            "'+5%' has a plus sign: 'set intensity by +5%' changes intensity by 5%, "
            "'set intensity 5%' sets it",
        ),
    ],
)
def test_the_mistake_that_stops_the_line_before_the_word(
    offline: OfflineShow, line: str, error: str | None
) -> None:
    assert offline.expected(line).error == error


def test_a_mistake_that_shows_at_the_end_keeps_what_may_come(offline: OfflineShow) -> None:
    """``record slot 1`` on a slot in use needs merge, replace or remove next."""
    found = offline.expected("record slot 1 m")
    assert found.error == "slot 1 is in use on page 1: add merge, replace or remove"
    assert (found.words, found.start) == (("merge",), 14)


def test_what_may_come_follows_the_show_and_the_programmer(offline: OfflineShow) -> None:
    assert offline.expected('bind "').words == ('"MIDI Controller"',)
    assert offline.execute('surface add osc "Pad"').ok
    assert offline.expected('bind "').words == ('"MIDI Controller"', '"Pad"')
    assert offline.expected("set gobo1 o").words == ()  # nothing selected: a value
    assert offline.execute("sel fixture 101").ok
    assert offline.expected("set gobo1 o") == Expected(("open",), start=10)


# ------------------------------------------------------- Tab, as a frontend does it


def test_tab_completes_every_word_of_the_example_show_as_it_is_typed() -> None:
    """Through ``examples/club-night.busk``, line by line: each keyword and
    name that may come where it stands is offered for every start of it
    typed, at that word's start, so replacing ``line[start:]`` with the word
    offered types it (in its own case). Asking at every key builds the same
    show, byte for byte, as not asking: no id is used up."""

    def build(ask: bool) -> tuple[OfflineShow, int]:
        ids = CounterIds()
        now = datetime(2026, 10, 24, tzinfo=UTC)
        offline = OfflineShow(new_show("Club Night", cid=CID, now=now, ids=ids), ids=ids)
        completed = 0
        for line in CLUB_NIGHT.read_text(encoding="utf-8").splitlines():
            if line == "save":
                continue
            for token in tokenize(line)[0] if ask else ():
                if token.text == "," and not token.quoted:
                    continue  # a comma ends a word: it is never being typed
                typed = json.dumps(token.text, ensure_ascii=False) if token.quoted else token.text
                if typed.lower() not in map(str.lower, offline.expected(line[: token.start]).words):
                    continue  # a value (a number, raw JSON)
                for k in range(1, len(typed) + (not token.quoted)):  # a closing quote ends it
                    found = offline.expected(line[: token.start] + typed[:k])
                    assert found.start == token.start, (line, typed[:k])
                    words = [w for w in found.words if w.lower() == typed.lower()]
                    assert words, (line, typed[:k], found)
                completed += 1
            assert offline.execute(line).ok, line
        return offline, completed

    (asked, completed), (built, _) = build(ask=True), build(ask=False)
    assert completed > 650
    assert show_json(asked.show) == show_json(built.show)
    assert asked.programmer == built.programmer


def test_asking_commits_nothing(offline: OfflineShow) -> None:
    assert offline.execute("sel fixture 101").ok
    show, programmer = offline.show, offline.programmer
    for line in ('universe add 2 "Spare"', "record cue 99/1 ", "set intensity 5", "output off"):
        offline.expected(line)
    assert offline.show is show
    assert offline.programmer is programmer
    assert offline.snapshot.outputEnabled
    assert offline.execute("undo") == Reply("undid: 1 target selected")


# ------------------------------------------------------------------- hosts


def test_a_live_show_answers_before_it_starts_from_another_thread_and_after_it_stops() -> None:
    live = LiveShow(show_of(load_doc(APPENDIX_A)), output=False)
    tapped = Expected(('"Speed 1"',), (), True, None, 4)
    assert live.expected("tap ") == tapped
    with live:
        answers: list[Expected] = []
        reader = threading.Thread(
            target=lambda: answers.extend(live.expected(line) for line in ("tap ", "output o"))
        )
        reader.start()
        reader.join()
        assert answers == [tapped, Expected(("on", "off"), start=7)]
    assert live.expected("tap ") == tapped


def test_busk_runs_show_answers_what_its_prompt_completes() -> None:
    """The console process's show answers what its prompt's Tab completes and
    its ``?`` shows: the same answer, from the same console."""
    shown = show_of(load_doc(APPENDIX_A))
    compiled = compile_show(shown)
    clock = FakeClock()
    live = LiveShow._attached(
        shown,
        compiled,
        LocalEngine(Engine(compiled, clock)),
        clock,
        path=Path("unused.show"),
        library=ProfileLibrary(),
        state_dir=Path("unused"),
        dirty=False,
        stamp=("s", 0),
        causes=False,
        iface="lo",
        status=lambda: "",
        about=lambda: (),
        poll=lambda: None,
        routes=lambda: None,
        say=lambda text: None,
        warn=lambda text: None,
    )
    for line in ("rou", "route add 1 s", 'master "Sp', "output of", 'bind "mi'):
        found = live.expected(line)
        assert len(found.words) == 1, line
        assert complete(live._console, line) == [found.words[0] + " "]
    found = live.expected("output o")
    assert found.words == ("on", "off")
    assert hints(live._console, "output o", 80)[0] == "next: " + "  ".join(sorted(found.words))
    assert hints(live._console, "sel fixture 99 ", 80)[0] == "error: no fixture 99"
    assert live.expected("sel fixture 99 ").error == "no fixture 99"
