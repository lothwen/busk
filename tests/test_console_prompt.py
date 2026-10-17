"""Tab completion and ``?`` at the console prompt: what the parser expects where
a line ends (``parser.expected``), the help ``?`` prints, the readline
completer, and a real prompt on a pseudo-terminal."""

from __future__ import annotations

import json
import os
import select
import sys
import time
from pathlib import Path

import pytest

from builders import APPENDIX_A, ROOT, load_doc, show_of
from busk import new_show
from busk.console.console import Console
from busk.console.parser import (
    COMMANDS,
    LIST_KINDS,
    Context,
    Expected,
    ParseError,
    expected,
    parse,
    tokenize,
)
from busk.console.prompt import Editing, grammar, hints, split
from busk.model.attributes import ATTRIBUTES
from busk.runner import OfflineShow
from busk.session.ids import CounterIds
from busk.session.library import ProfileLibrary, builtin_effects
from session_harness import Live

LIBRARY = ProfileLibrary()
CLUB_NIGHT = ROOT / "examples" / "club-night.busk"


def context() -> Context:
    return Context(show_of(load_doc(APPENDIX_A)), LIBRARY, CounterIds())


def after(line: str) -> Expected:
    return expected(line, context())


@pytest.fixture
def console() -> Console:
    return Console(Live(load_doc(APPENDIX_A)).session, LIBRARY)


# ------------------------------------------------------------- expected


def test_an_empty_line_may_start_with_any_command() -> None:
    assert after("") == Expected(COMMANDS)
    assert {"sel", "route", "fixture", "cue", "record", "quit", "help"} <= set(COMMANDS)


SHOW = show_of(load_doc(APPENDIX_A))  # the show's names first, then the libraries'
PROFILES = tuple(dict.fromkeys(json.dumps(p["name"]) for p in [*SHOW["profiles"], *LIBRARY]))
TEMPLATES = tuple(
    dict.fromkeys(
        json.dumps(t["name"]) for t in [*SHOW["effects"], *(e.template for e in builtin_effects())]
    )
)
CURVES = ("linear", "easeIn", "easeOut", "easeInOut", "snapStart", "snapEnd", "bezier")

# (line, words, values, runnable): the line ends where the next word starts
EXPECTED: list[tuple[str, tuple[str, ...], tuple[str, ...], bool]] = [
    ("route ", ("add",), (), False),
    ("route add ", (), ("a universe number",), False),
    ("route add 1 ", ("sacn", "artnet", "dmxusb"), (), False),
    ("route add 1 sacn 1 ", ("unicast", "multicast", "broadcast"), (), True),
    ("sel fixture ", (), ("a fixture number",), False),
    ("sel fixture 101 ", ("thru", ","), (), True),
    ("fixture ", ("add",), ("a fixture number",), False),
    ("fixture 101 ", ("patch", "thru", "limits"), ("a property, e.g. name or timing.fadeIn",),
     False),
    ("fixture 101 thru ", (), ("a fixture number after thru",), False),
    ("fixture 101 thru 102 ", ("limits",), (), False),
    ("fixture add 5 ", ("thru", *PROFILES), (), False),
    ('fixture add 5 "Generic Spot 16ch" mode ', ("16ch",), (), False),
    ("set ", tuple(ATTRIBUTES), (), False),
    ("set pan ", ("spread", "preset"), ("a number",), False),
    ("record ", ("group", "preset", "cue", "slot"), (), False),
    ("record cue 1/1 ", ("merge", "replace", "remove", "only", "freeze"),
     ("a name in quotes",), True),
    ("record cue 1/1 only ", ("intensity", "position", "color", "beam", "focus", "shutter"), (),
     False),
    ("cue 10/1 ", ("effect", "time", "go", "follow", "wait", "release"),
     ("a property, e.g. name or timing.fadeIn",), False),
    ("cue 10/1 time 3 ", ("delay", *CURVES), (), True),
    ("cuelist 10 ", ("sequence", "chase"), ("a property, e.g. name or timing.fadeIn",), False),
    ("cuelist 10 chase ", ("hz", "bpm"), ("a value",), False),
    ("list ", LIST_KINDS, (), False),
    ("rename ", ("cue", "cuelist", "fixture", "group", "page", "playback", "preset", "show",
                 "universe"), (), False),
    ("delete ", ("cue", "cuelist", "fixture", "group", "page", "playback", "preset",
                 "universe"), (), False),
    ("master ", ("add", '"Grand Master"', '"Speed 1"'), (), False),
    ("tap ", ('"Speed 1"',), (), True),
    ("release ", ("all",), ("a playback number",), False),
    ("release 1 ", (), ("a time in seconds",), True),
    ("page 1 ", ("slot",), (), True),
    ("bind ", ('"MIDI Controller"',), (), False),
    ('bind "MIDI Controller" cc 1 2 fader 1 ', ("led", "motor", "display"), (), True),
    ('bind "MIDI Controller" cc 1 2 fader 1 led ', ("cc", "note", "osc"), (), True),
    ("effect add ", TEMPLATES, (), False),
    ("universe add 2 ", (), ("a name in quotes",), True),
    ("save ", (), ("a path",), True),
    ("quit ", (), (), True),
]  # fmt: skip


@pytest.mark.parametrize(
    ("line", "words", "values", "runnable"), EXPECTED, ids=[case[0] for case in EXPECTED]
)
def test_what_may_follow_a_line(
    line: str, words: tuple[str, ...], values: tuple[str, ...], runnable: bool
) -> None:
    assert after(line) == Expected(words, values, runnable)


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("sel fixture 99 ", "no fixture 99"),
        ("xyz ", "unknown command 'xyz' (try 'help')"),
        ('master "Sp', "unterminated quote at column 8"),
    ],
)
def test_a_mistake_before_the_end_stops_the_line(line: str, error: str) -> None:
    assert after(line).error == error


def test_a_mistake_that_shows_at_the_end_keeps_what_may_come() -> None:
    """``record slot 1`` on a slot in use needs merge, replace or remove next."""
    found = after("record slot 1 ")
    assert found.error == "slot 1 is in use on page 1: add merge, replace or remove"
    assert found.words[:3] == ("merge", "replace", "remove")


def test_nothing_follows_a_comment() -> None:
    assert after("sel # the heads ") == Expected()


def test_expected_changes_nothing() -> None:
    """A line that would make a cue list takes no id from the console's factory."""
    ctx = context()
    before = json.dumps(ctx.show, sort_keys=True)
    assert expected("record cue 99/1 ", ctx).runnable
    assert ctx.ids.new("x") == CounterIds().new("x")
    assert json.dumps(ctx.show, sort_keys=True) == before


def test_only_limits_follows_a_fixture_range() -> None:
    with pytest.raises(ParseError, match=r"^expected limits$"):
        parse("fixture 101 thru 102", context())


def test_tab_offers_every_word_of_the_example_show_where_it_stands(tmp_path: Path) -> None:
    """Completion follows the parser: through ``examples/club-night.busk``, line
    by line, every keyword and name is offered where it stands (or a value is
    described there, or the line could already run: a raw JSON value), and no
    line is a mistake before its end."""
    ids = CounterIds()
    offline = OfflineShow(new_show("Club Night", ids=ids), path=tmp_path / "club.show", ids=ids)
    offered = 0
    for line in CLUB_NIGHT.read_text(encoding="utf-8").splitlines():
        tokens, _ = tokenize(line)
        for token in tokens:
            found = offline._console.expected(line[: token.start])
            assert found.error is None, (line, token.text)
            typed = json.dumps(token.text, ensure_ascii=False) if token.quoted else token.text
            known = typed.lower() in (word.lower() for word in found.words)
            assert known or found.values or found.runnable, (line, token.text, found)
            offered += known
        if tokens:
            assert offline.execute(line).ok, line
    assert offered > 600


# ------------------------------------------------------------------- help


@pytest.mark.parametrize(
    ("before", "split_at"),
    [
        ("", ("", "")),
        ("rou", ("", "rou")),
        ("route add ", ("route add ", "")),
        ("sel fixture 1,fix", ("sel fixture 1,", "fix")),
        ('master "Spe', ("master ", '"Spe')),
        ('master "Grand Ma', ("master ", '"Grand Ma')),
        ('rename show "a \\" b', ("rename show ", '"a \\" b')),
        ('bind "Pad" cc', ('bind "Pad" ', "cc")),
    ],
)
def test_split_finds_the_word_being_typed(before: str, split_at: tuple[str, str]) -> None:
    assert split(before) == split_at


def test_question_mark_shows_what_may_come_and_the_command(console: Console) -> None:
    assert hints(console, "route add 1 ", 80) == [
        "next: artnet  dmxusb  sacn",
        "    route add U sacn <universe> [unicast <host> | multicast <iface>]",
        "    route add U artnet <net>.<sub>.<uni> [unicast <host>]",
        "    route add U dmxusb enttecPro|dmxking <port> [hz N]",
        "        (hz: the widget's output rate, 40 by default)",
    ]


def test_question_mark_after_a_partial_word(console: Console) -> None:
    assert hints(console, "route add 1 sa", 80) == [
        "next: sacn",
        "    route add U sacn <universe> [unicast <host> | multicast <iface>]",
    ]
    assert hints(console, "rou", 80) == ["next: route"]
    assert hints(console, "lip", 80) == ["nothing here starts with 'lip'"]


def test_question_mark_says_enter_runs_the_line_and_wraps(console: Console) -> None:
    lines = hints(console, "cue 10/1 time 3 ", 40)
    assert lines[:4] == [
        "next: bezier  delay  easeIn  easeInOut",
        "      easeOut  linear  snapEnd",
        "      snapStart  <Enter>",
        "    cue L/C time <in>[/<out>] [delay <in>[/<out>]] [<curve>]",
    ]


def test_question_mark_shows_the_mistake(console: Console) -> None:
    assert hints(console, "sel fixture 99 ", 80)[0] == "error: no fixture 99"


def test_grammar_keeps_the_forms_that_fit_with_the_definitions_they_use() -> None:
    assert grammar("park ") == [
        "    park <targets> <attribute> <value>",
        "        <targets> = <t>[, <t>…];  <t> = fixture N[.E] [thru M[.F]] | group N",
        "        <value> = 0.5 | 50% | -45 | r g b [w x] [a x] [uv x] | breakup",
    ]
    assert grammar("record cue ") == [
        '    record cue L[/C] [only <family>…] [<merge>] [freeze] ["name"]'
    ]
    assert grammar("release ") == ["    release N [<seconds>]", "    release all [<seconds>]"]


def test_grammar_shows_an_entitys_generic_edit_until_a_sub_command_fits() -> None:
    generic = "    <entity> <prop[.sub…]> <value>     (value as JSON, else a bare string)"
    assert generic in grammar("fixture 101 ")
    assert generic in grammar("group 1 ")
    assert generic not in grammar("route ")
    assert grammar("cue 10/1 time ") == [
        "    cue L/C time <in>[/<out>] [delay <in>[/<out>]] [<curve>]",
        "    cue L/C time <family> <fade> [delay <d>] [<curve>]",
        "        <curve> = linear | easeIn | easeOut | easeInOut | snapStart | snapEnd",
        "                | bezier x1 y1 x2 y2",
    ]


def test_no_grammar_before_the_first_word_is_whole() -> None:
    assert grammar("") == []
    assert grammar("rou") == []
    assert grammar("route")[0].startswith("    route add U sacn")


# --------------------------------------------------------------- completer


class FakeReadline:
    """What :class:`Editing` asks readline, for a line typed up to its end."""

    def __init__(self, line: str, kind: str = "\t") -> None:
        self.line = line
        self.kind = kind

    def get_line_buffer(self) -> str:
        return self.line

    def get_endidx(self) -> int:
        return len(self.line)

    def get_begidx(self) -> int:  # readline's word: after the last space or comma
        return max(self.line.rfind(" "), self.line.rfind(","), self.line.rfind("\t")) + 1

    def get_completion_type(self) -> int:
        return ord(self.kind)


def complete(console: Console, line: str, *, kind: str = "\t", libedit: bool = False) -> list[str]:
    """Every match the completer gives for ``line``."""
    editing = Editing(console)
    fake = FakeReadline(line, kind)
    editing.readline, editing.libedit = fake, libedit  # type: ignore[assignment]
    text = line[fake.get_begidx() :]
    found = []
    while (match := editing._complete(text, len(found))) is not None:
        found.append(match)
    return found


def test_tab_completes_a_keyword_with_a_space(console: Console) -> None:
    assert complete(console, "rou") == ["route "]
    assert complete(console, "Rou") == ["route "]
    assert complete(console, "route ") == ["add "]  # the only word that may come
    assert complete(console, "route add 1 s") == ["sacn "]


def test_tab_completes_a_name_in_quotes(console: Console) -> None:
    assert complete(console, 'master "Sp') == ['"Speed 1" ']
    assert complete(console, 'master "grand m') == ['Master" ']  # from readline's word, "m"
    assert complete(console, 'fixture add 5 "Generic S') == ['Spot 16ch" ']


def test_tab_lists_several_words(console: Console) -> None:
    assert complete(console, "route add 1 ") == ["sacn ", "artnet ", "dmxusb "]


def test_tab_shows_the_help_where_a_value_may_come(console: Console) -> None:
    """``fixture `` takes ``add`` or a number: Tab must not type ``add``. Two
    stand-in matches make readline list (through the hook) and keep the line."""
    assert complete(console, "fixture ") == ["1", "2"]
    assert complete(console, "sel fixture 1") == ["11", "12"]


def test_question_mark_never_completes(console: Console) -> None:
    assert complete(console, "rou", kind="?") == ["rou1", "rou2"]


def test_libedit_prints_the_help_itself(
    console: Console, capsys: pytest.CaptureFixture[str]
) -> None:
    assert complete(console, "route ", libedit=True) == ["add "]
    assert complete(console, "route add 1 ", libedit=True) == []
    out = capsys.readouterr().out
    assert "\nnext: artnet  dmxusb  sacn\n" in out
    assert out.endswith("busk> route add 1 ")


def test_libedit_extends_to_the_common_start(console: Console) -> None:
    assert complete(console, "fa", libedit=True) == ["fade ", "fader "]


def test_a_line_ending_in_a_question_mark_asks_where_it_is_no_key(console: Console) -> None:
    editing = Editing(console)
    editing.readline, editing.libedit = FakeReadline(""), True  # type: ignore[assignment]
    assert editing.asks("route add ?")
    assert editing.asks("route?  ")
    assert not editing.asks('rename show "Why?')
    assert not editing.asks('rename show "Why?"')
    editing.libedit = False
    assert not editing.asks("route add ?")  # GNU readline: ? is a key


# ------------------------------------------------------------ a real prompt

PROMPT_SCRIPT = f"""
import sys
sys.path[:0] = [{str(ROOT / "src")!r}, {str(ROOT / "tests")!r}]
from builders import APPENDIX_A, load_doc
from session_harness import Live
from busk.console.console import Console, interact
from busk.session.library import ProfileLibrary
interact(Console(Live(load_doc(APPENDIX_A)).session, ProfileLibrary()))
print("[EXIT]", flush=True)
"""


def test_tab_question_mark_and_ctrl_c_on_a_terminal() -> None:
    """The readline glue on a pseudo-terminal, with this interpreter's readline."""
    pty = pytest.importorskip("pty")
    readline = pytest.importorskip("readline")
    libedit = "libedit" in (readline.__doc__ or "")
    pid, fd = pty.fork()
    if pid == 0:  # the child: a prompt on the terminal
        try:
            env = {**os.environ, "TERM": "xterm", "INPUTRC": os.devnull}
            os.execve(sys.executable, [sys.executable, "-c", PROMPT_SCRIPT], env)
        finally:
            os._exit(127)
    out = b""

    def expect(text: str) -> str:
        """Read until ``text``; return what came before it."""
        nonlocal out
        deadline = time.monotonic() + 10
        while text.encode() not in out:
            assert time.monotonic() < deadline, (text, out.decode(errors="replace"))
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    out += os.read(fd, 4096)
                except OSError:  # the child is gone
                    break
        before, _, out = out.partition(text.encode())
        return before.decode(errors="replace")

    try:
        expect("busk> ")
        os.write(fd, b"sel fix\t101\r")  # Tab completes "fixture "
        expect("1 target selected")
        os.write(fd, b"route add 1 ?" + (b"\r" if libedit else b""))
        expect("next: artnet  dmxusb  sacn")
        expect("busk> ")  # the line again (libedit: a new, empty one)
        time.sleep(0.2)  # a Ctrl+C while the help is still printing would be lost
        if not libedit:  # GNU readline kept the line: Ctrl+C clears it, and that is all
            os.write(fd, b"\x03")
            assert "press Ctrl+C" not in expect("busk> ")
        os.write(fd, b"\x03")
        expect("press Ctrl+C again to quit")
        expect("busk> ")
        os.write(fd, b"\x03")
        expect("[EXIT]")
    finally:
        os.close(fd)
        os.waitpid(pid, 0)
