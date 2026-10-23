"""Console line → action (phase-3-plan §5.10). A pure function of the line and
the current show: nothing here changes state.

Grammar (``N`` is a user-facing number, ``U.A`` universe.address, ``<merge>``
one of ``merge``, ``replace``, ``remove``; quoted strings are names)::

    sel <targets> | sel + <targets> | sel - <targets> | sel none | sel playback N
        <targets> = <t>[, <t>…];  <t> = fixture N[.E] [thru M[.F]] | group N
        (fixture N is every element of N; .E picks element E, counted from 1)
    set <attribute> <value> | set <attribute> by <change>
    set color.r|g|b|w|a|uv <value> | set color.r|g|b|w|a|uv by <change>
        <change> = 5% | -5% | 15 | -15   (added to what the programmer holds)
    set <attribute> spread <from> [to] <to> [center|edges]
    set <attribute> preset <pool> N
    preset <pool> N
        <value> = 0.5 | 50% | -45 | r g b [w x] [a x] [uv x] | breakup
    clear | blind on|off | highlight on|off | fade <seconds> | programmer
    record group N [<merge>] ["name"]
    record preset <pool> N [global|profile|target] [<merge>] ["name"]
    record cue L[/C] [only <family>…] [<merge>] [freeze] ["name"]
    record slot [P.]S [only <family>…] [<merge>] ["name"]
    universe add N ["name"]
    fixture add N [thru M] "<profile>" mode <mode> [at U.A]
    fixture N patch U.A | fixture N patch none
    route add U sacn <universe> [unicast <host> | multicast <iface>]
    route add U artnet <net>.<sub>.<uni> [unicast <host>]
    route add U dmxusb enttecPro|dmxking <port> [hz N]
        (hz: the widget's output rate, 40 by default)
    surface add midi "<device>"
    surface add osc "<name>" [port N] [feedback <host>[:<port>]]
    surface add web "<name>" [port N] [on <host>]
    surface "<name>" pickup soft|jump
    bind "<surface>" <input> <what> [led|motor|display [<input>]]
    bind "<surface>" clock tap ["<master>"] [led|motor|display <input>]
        <input> = cc|note <channel> <number> | osc "/path"
        <what> = fader <slot> | fader playback N | button <slot> <b> | master gm
               | master "<name>" | tap ["<master>"] | blackout [momentary]
               | page +N | page -N | page N | release all [<seconds>] | output on|off
    feedback "<surface>" <input> [thru <number>] led|motor|display|none
    unbind "<surface>" <input> [thru <number>]
    page N | page next | page prev | page add N ["name"]
    page P slot S playback N | page P slot S clear
    playback N goto <cue>
    <entity> <prop[.sub…]> <value>     (value as JSON, else a bare string)
    rename <entity> "name" | delete <entity>
        <entity> = fixture N | group N | preset <pool> N | cuelist N | cue L/C
                 | playback N | page N | universe N | show
    cue L/C time <in>[/<out>] [delay <in>[/<out>]] [<curve>]
    cue L/C time <family> <fade> [delay <d>] [<curve>]
        <curve> = linear | easeIn | easeOut | easeInOut | snapStart | snapEnd
                | bezier x1 y1 x2 y2
    cue L/C go | cue L/C follow <d> | cue L/C wait <d>
    cue L/C release <targets> [only <attribute>…]
    cuelist N chase hz <rate> [<direction>] [crossfade <f>]
    cuelist N chase bpm ["<master>"] [x <multiplier>] [<direction>] [crossfade <f>]
        <direction> = forward | reverse | bounce | random
    cuelist N sequence
    go N | back N | goto N <cue> | release N [<seconds>] | fader N <level>
    flash N on|off | toggle N | button N <b> on|off
    gm <level> | master "<name>" <level> | blackout on|off
    release all [<seconds>] | output on|off
    park <targets> <attribute> <value> | unpark <targets> [<attribute>] | unpark all
    fixture N [thru M] limits pan|tilt <min> <max>
    fixture N [thru M] limits intensity <max> | fixture N [thru M] limits none
    safety strobe <hz> | safety strobe off
    profile update "<name>"
    tap ["<master>"] | bpm ["<master>"] <bpm>
        (without a name: the show's only speed master)
    master add speed "<name>" [bpm <x>] [steps <a>, <b>…]
    master add size "<name>" | master add group "<name>" group N
    master add fadetime "<name>"
    effect add "<template>" [id <id>] [hz <rate> | bpm ["<master>"] [x <m>]]
        [size <s>] [low <v> high <v>] [phase <start> <end>] [groups N] [blocks N]
        [wings N] [forward|reverse|bounce] [fadein <s>] [sizemaster "<name>"]
        [speedmaster "<name>"]
    effect remove <id> | effect clear
    effect template add "<name>" <JSON layers>
    cue L/C effect <id> <prop[.sub…]> <value>
    undo | redo | save [PATH] | list <kind> | list cues L | library | info
    status | help | source FILE | quit

Slots and buttons are counted from 1, like the physical controls. Defaults
the console fills in: a playback made by ``record slot`` copies Appendix A's
Blue playback without its exclusivity; a new cue list is a ``sequence``
without tracking, wrap or release at the end; a new fixture has a neutral
orientation and is named after its profile's model and its number.

Phase 4 sugar (phase-4-plan §5.13). Masters have no numbers, so they are
named in quotes (any case). ``cue L/C time`` sets the given timing fields in
one batch, ``<out>`` defaulting to ``<in>``; with a family it sets that
family's timing (delay 0 unless given), keeping the other families.
``release`` appends to the cue's releases (every attribute unless ``only``).
``chase hz|bpm`` sets the list's chase settings (defaults: ×1, ``forward``,
crossfade 0) and chase mode in one batch; ``cuelist N chase {json}`` is the
generic edit. ``master add speed`` defaults to 120 BPM, tap on and steps
0.25, 0.5, 1, 2, 4.

Phase 5 sugar (phase-5-plan §5.12). ``effect add`` adds an effect instance
on the selection, in order, to the programmer. The template is the show's
if it has one by that name (any case), else the built-in library's, which
is then embedded into the show first: the line runs two commands, in order,
stopping at the first failure (two undo steps). Options come in any order;
defaults: the library's ``size``, ``low``/``high`` and ``phase`` for the
template (else size 1, phase 0 0), a BPM rate ×1 on the show's only speed
master (else 1 Hz), 1 group, 1 block, 1 wing, ``forward``, and the id
``fx<n>`` with the lowest ``n`` that neither the programmer nor any cue
uses. ``effect template add`` adds a template made of JSON layers.
``cue L/C effect <id> …`` sets a property of one of a cue's effect
instances. ``record slot`` gives a new playback a ``size`` fader when its
cue will hold only effects. ``list effects`` lists the show's templates.

Phase 6 sugar (phase-6-plan §5.17). ``page N``, ``next`` and ``prev`` change
the engine's page, shared by every surface; it reaches the engine a tick
later, so a script records with ``record slot P.S`` rather than after a
``page`` line. ``record slot S`` records on the engine's current page (the
first page without an engine). ``page add`` makes a page with no slots;
assigning a slot extends them. OSC surfaces listen on port 8000 and web
surfaces on 8080 unless told otherwise; ``feedback <host>[:<port>]`` sends
OSC feedback there instead of to the sender (either part may be left out).
Surfaces are named in quotes (any case); a new surface needs a new name,
and a port free among the surfaces of its kind. A binding's feedback goes
to its own input unless another is given; ``motor`` drives a motor fader.
``feedback`` sets (or with ``none`` removes) the feedback of every binding
of the inputs it names, ``thru`` counting either way; ``unbind`` removes
every binding of the inputs it names, to bind them anew. ``playback N goto``
names the cue its ``goto`` buttons go to. A ``fadetime`` master starts at
0, the programmed times.

Phase 7 sugar (phase-7-plan §5.20, §5.22). ``park`` forces a value on
every target it names (a group's members, every element of a fixture),
replacing what was parked on those slots; ``unpark`` removes what is parked
on the targets (only the attribute, when given), ``unpark all`` everything.
Park entries have no ids, so both build the new park list and set it whole,
in one undo step. ``limits`` sets a key of each fixture's ``limits`` (pan
and tilt in degrees, as programmed; intensity at most a level) and keeps
the others; ``limits none`` removes them. ``safety strobe`` sets the show's
strobe-rate cap. ``release all`` releases every playback (each with its
release time unless one is given) and ``output off`` stops all DMX output:
at an interactive prompt it asks first, in scripts and bindings it does
not. ``profile update`` replaces the show's copy of a profile with the
library's other revision and moves its fixtures to it, refused when a
fixture's mode is missing from that revision. ``list park`` lists what is
parked; ``list profiles`` says which embedded profiles the library has in
another revision.

Playback buttons (GAP-04 of ``docs/dev/tui/engine-gaps.md``), for a
frontend that holds a button while it is down. ``flash N on`` holds
playback N's flash until ``flash N off`` (or ``release all``), whatever
buttons the playback has. ``button N <b> on|off`` presses and releases the
playback's button ``b`` as a bound control does: the function in its
``buttons`` acts, and a ``select`` button's press selects, as ``sel
playback N``. ``toggle N`` releases an active playback and activates any
other.

Relative and per-component values (GAP-05 of
``docs/dev/tui/engine-gaps.md``), for a frontend's encoders. ``set
<attribute> by <change>`` adds the change to the value the programmer holds
for each selected target (a preset reference counts with the preset's
value), within the attribute's range when it has one; ``set color.<c>``
sets one component of the colour, ``r``, ``g``, ``b``, ``w``, ``a`` or
``uv``, keeping the others, and ``by`` changes it within ``0..1`` (from 0
when the colour has none). Targets without a value in the programmer are
skipped. A colour changes only by component and a discrete attribute not at
all. Where ``by`` may come, a value with a plus sign is refused: ``set
intensity +5%`` would set 5%.

Completion (Tab and ``?`` at the prompt, :mod:`busk.console.prompt`).
:func:`expected` parses a line up to the word being typed. Where the line
runs out, the parser notes what it was looking for: keywords, names in
quotes from the show and the libraries, and descriptions of the values. It
also reports whether the line runs as it is, or the mistake that stops it.
"""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, cast

from busk.commands.patch import deep_copy
from busk.commands.types import Command, EditPath
from busk.model.attributes import ATTRIBUTES, AttributeDefinition
from busk.model.common import TargetRef
from busk.model.cue import CUE_NUMBER
from busk.model.profile import option_capabilities
from busk.model.show import Show
from busk.model.validate import COLOR_COMPONENTS
from busk.session.ids import IdFactory, RandomIds
from busk.session.library import EffectDefaults, EffectLibrary, ProfileLibrary, builtin_effects
from busk.session.programmer import EMPTY, Programmer, split_slot_key

# ------------------------------------------------------------------ actions


@dataclass(frozen=True)
class Submit:
    """Submit ``command`` to the session; print ``notes`` first. An
    interactive prompt asks ``confirm`` (a yes/no question) before it
    submits, when it is set (``output off``)."""

    command: Command
    notes: tuple[str, ...] = ()
    confirm: str | None = None


@dataclass(frozen=True)
class SubmitAll:
    """Submit ``commands`` to the session in order, stopping at the first
    that fails; print ``notes`` first. Each is its own undo step."""

    commands: tuple[Command, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Query:
    """Print something: ``programmer``, ``list <kind>`` (``list cues L``:
    ``number`` is ``L``), ``library``, ``info``, ``status`` or ``help``."""

    kind: str
    arg: str = ""
    number: int | None = None


@dataclass(frozen=True)
class Save:
    path: Path | None


@dataclass(frozen=True)
class Source:
    path: Path


@dataclass(frozen=True)
class Quit:
    pass


@dataclass(frozen=True)
class Nothing:
    """A blank line or a comment."""


type Action = Submit | SubmitAll | Query | Save | Source | Quit | Nothing


class ParseError(Exception):
    """The line is not a console command; the message says what is wrong."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class _Unfinished(ParseError):
    """The line ends where the command needs more (:func:`expected` tells it
    from a mistake before the end)."""


@dataclass(frozen=True)
class Context:
    """What parsing reads: the current show, the profile library, the id
    factory, the network interface for multicast and broadcast routes, the
    effect library, the programmer (``effect add`` targets its selection),
    and the id of the engine's current page (``record slot S`` records on
    it; ``None`` without an engine, which starts on the first page)."""

    show: Show
    library: ProfileLibrary
    ids: IdFactory
    iface: str = "eth0"
    effects: EffectLibrary = field(default_factory=builtin_effects)
    programmer: Programmer = EMPTY
    page: str | None = None


def parse(line: str, context: Context) -> Action:
    """Parse one console line. Raises :class:`ParseError`."""
    tokens, comment = tokenize(line)
    if not tokens:
        return Nothing()
    return _Parser(line, tokens, comment, context).command()


@dataclass(frozen=True)
class Expected:
    """What may follow a line (:func:`expected`)."""

    words: tuple[str, ...] = ()
    """Keywords and names that may come next, as typed (names in quotes)."""
    values: tuple[str, ...] = ()
    """Anything else that may come next, described: ``a fixture number``."""
    runnable: bool = False
    """The line is a whole command as it is."""
    error: str | None = None
    """The mistake that stops the line. ``words`` may still be set, when the
    mistake shows only at the end (``record slot 1`` on a slot in use)."""


def expected(line: str, context: Context) -> Expected:
    """What may follow ``line``, a line cut where its next word starts (Tab
    completion and ``?``). Like :func:`parse`, it changes nothing: ids come
    from a factory of its own."""
    try:
        tokens, end = tokenize(line)
    except ParseError as exc:
        return Expected(error=exc.message)
    if end < len(line):  # in a comment
        return Expected()
    if not tokens:
        return Expected(COMMANDS)
    parser = _Parser(line, tokens, end, replace(context, ids=RandomIds()))
    runnable, error = False, None
    try:
        parser.command()
        runnable = True
    except _Unfinished:
        pass
    except ParseError as exc:
        error = exc.message
    return Expected(
        tuple(dict.fromkeys(parser.offers)), tuple(dict.fromkeys(parser.needs)), runnable, error
    )


# ---------------------------------------------------------------- tokenizer

_TOKEN: Final = re.compile(r'\s*(?:(?P<quoted>"(?:[^"\\]|\\.)*")|(?P<comma>,)|(?P<word>[^\s",]+))')


@dataclass(frozen=True)
class Token:
    """One token, with where it starts in the line (for raw JSON values)."""

    text: str
    start: int
    quoted: bool = False

    @property
    def lower(self) -> str:
        return "" if self.quoted else self.text.lower()


def tokenize(line: str) -> tuple[list[Token], int]:
    """Words, commas and double-quoted strings (JSON escapes), up to a ``#``
    comment. Returns the tokens and where the comment starts (or the line's
    length)."""
    tokens: list[Token] = []
    position = 0
    while position < len(line):
        if not line[position:].strip():
            break
        match = _TOKEN.match(line, position)
        if match is None:
            column = line.index('"', position) + 1
            raise ParseError(f"unterminated quote at column {column}")
        start = match.start(match.lastgroup or "word")
        if match["quoted"] is not None:
            tokens.append(Token(json.loads(match["quoted"]), start, quoted=True))
        elif match["comma"] is not None:
            tokens.append(Token(",", start))
        else:
            if match["word"].startswith("#"):
                return tokens, start
            tokens.append(Token(match["word"], start))
        position = match.end()
    return tokens, len(line)


# ------------------------------------------------------------------- parser

_FAMILIES: Final = ("intensity", "position", "color", "beam", "focus", "shutter")
_MERGES: Final = ("merge", "replace", "remove")
_POOLS: Final = ("intensity", "position", "color", "beam", "focus", "all")
_SCOPES: Final = ("global", "profile", "target")
_DEFAULT_SCOPE: Final = {
    "color": "global",
    "intensity": "global",
    "beam": "profile",
    "focus": "profile",
    "position": "target",
    "all": "target",
}
_ATTRIBUTE_NAMES: Final = {attribute.lower(): attribute for attribute in ATTRIBUTES}
_COMPONENT_WORDS: Final = tuple(f"color.{component}" for component in COLOR_COMPONENTS)
_NUMBER: Final = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)%?")
_CUE: Final = re.compile(r"(\d+)(?:/(\d+(?:\.\d+)?))?")
_SLOT: Final = re.compile(r"(?:(\d+)\.)?(\d+)")
_QUERIES: Final = ("programmer", "library", "info", "status", "help")
_SECONDS: Final = re.compile(r"\d+(?:\.\d*)?|\.\d+")
_CURVES: Final = {
    name.lower(): name
    for name in ("linear", "easeIn", "easeOut", "easeInOut", "snapStart", "snapEnd")
}
_DIRECTIONS: Final = ("forward", "reverse", "bounce", "random")
_CUE_VERBS: Final = ("time", "go", "follow", "wait", "release")
_EFFECT_DIRECTIONS: Final = ("forward", "reverse", "bounce")
_EFFECT_OPTIONS: Final = (
    "id", "hz", "bpm", "size", "low", "phase", "groups", "blocks", "wings",
    *_EFFECT_DIRECTIONS, "fadein", "sizemaster", "speedmaster",
)  # fmt: skip
_DEFAULT_BPM: Final = 120
_DEFAULT_PORTS: Final = {"osc": 8000, "web": 8080}
_FEEDBACK: Final = {"led": "led", "motor": "motorFader", "display": "display"}
_DEFAULT_STEPS: Final = (0.25, 0.5, 1, 2, 4)


@dataclass
class _Options:
    """Trailing options of the record commands."""

    merge: str | None = None
    name: str | None = None
    scope: str | None = None
    freeze: bool = False
    families: list[str] = field(default_factory=list)


class _Parser:
    def __init__(self, line: str, tokens: list[Token], end: int, context: Context) -> None:
        self.line = line
        self.tokens = tokens
        self.end = end  # where the comment (if any) starts
        self.k = 0
        self.ctx = context
        self.show = context.show
        self.offers: list[str] = []  # what may come where the line ends: words…
        self.needs: list[str] = []  # …and anything else, described (see `expected`)

    # ------------------------------------------------------------ cursor

    def peek(self, offset: int = 0) -> Token | None:
        index = self.k + offset
        return self.tokens[index] if index < len(self.tokens) else None

    def ending(self, *offers: str, need: str = "") -> bool:
        """Whether the line ends here. If it does, note what may come next
        for :func:`expected`: ``offers``, words as typed, and ``need``, a
        description of anything else."""
        if self.peek() is not None:
            return False
        self.offers += offers
        if need:
            self.needs.append(need)
        return True

    def fail(self, message: str) -> ParseError:
        """The error for ``message``: :class:`_Unfinished` where the line ends."""
        return _Unfinished(message) if self.peek() is None else ParseError(message)

    def take(self, what: str, *names: str) -> Token:
        """The next token, ``what``. Where the line ends, :func:`expected`
        offers ``names`` for it, else describes it as ``what``."""
        if self.ending(*names, need="" if names else what):
            raise _Unfinished(f"expected {what}")
        self.k += 1
        return self.tokens[self.k - 1]

    def word(self, what: str, *names: str) -> str:
        return self.take(what, *names).lower

    def keyword(self, *options: str) -> str | None:
        token = self.peek()
        if token is None:
            self.offers += options
        elif token.lower in options:
            self.k += 1
            return token.lower
        return None

    def expect(self, *options: str) -> str:
        found = self.keyword(*options)
        if found is None:
            token = self.peek()
            got = f", got {token.text!r}" if token else ""
            raise self.fail(f"expected {' or '.join(options)}{got}")
        return found

    def integer(self, what: str) -> int:
        token = self.take(what)
        try:
            return int(token.text)
        except ValueError:
            raise ParseError(f"expected {what}, got {token.text!r}") from None

    def number(self, what: str = "a number") -> float:
        token = self.take(what)
        if token.quoted or _NUMBER.fullmatch(token.text) is None:
            raise ParseError(f"expected {what}, got {token.text!r}")
        if token.text.endswith("%"):
            return float(token.text[:-1]) / 100
        return _numeric(token.text)

    def numbers(self, what: str) -> list[float]:
        """``<x>[, <y>…]``: one number or more, comma-separated."""
        values = [self.number(what)]
        while self.keyword(","):
            values.append(self.number(what))
        return values

    def pair(self, what: str) -> tuple[float, float]:
        """``<a>[/<b>]`` in seconds; ``b`` defaults to ``a``."""
        token = self.take(what)
        parts = token.text.split("/")
        if token.quoted or len(parts) > 2 or not all(_SECONDS.fullmatch(p) for p in parts):
            raise ParseError(f"expected {what}, got {token.text!r}")
        return _numeric(parts[0]), _numeric(parts[-1])

    def curve(self) -> str | dict[str, Any] | None:
        """An optional fade curve: a name, or ``bezier x1 y1 x2 y2``."""
        token = self.peek()
        if token is None:
            self.offers += (*_CURVES.values(), "bezier")
            return None
        if token.lower == "bezier":
            self.k += 1
            return {"bezier": [self.number("a Bézier control value") for _ in range(4)]}
        name = _CURVES.get(token.lower)
        if name is None or token.quoted:
            names = ", ".join(_CURVES.values())
            raise ParseError(
                f"expected a curve ({names} or bezier x1 y1 x2 y2), got {token.text!r}"
            )
        self.k += 1
        return name

    def done(self) -> None:
        token = self.peek()
        if token is not None:
            raise ParseError(f"unexpected {token.text!r}")

    def rest(self) -> str:
        """The raw text from the next token to the comment (for JSON values)."""
        token = self.peek()
        if token is None:
            self.needs.append("a value")
            raise _Unfinished("expected a value")
        self.k = len(self.tokens)
        return self.line[token.start : self.end].strip()

    # -------------------------------------------------------------- lookups

    def by_number(self, collection: str, number: int, what: str) -> dict[str, Any]:
        for item in self.show[collection]:  # type: ignore[literal-required]
            if item["number"] == number:
                return cast(dict[str, Any], item)
        raise ParseError(f"no {what} {number}")

    def preset(self) -> dict[str, Any]:
        pool = self.expect(*_POOLS)
        number = self.integer("a preset number")
        for item in self.show["presets"]:
            if item["pool"] == pool and item["number"] == number:
                return cast(dict[str, Any], item)
        raise ParseError(f"no preset {pool} {number}")

    def playback_id(self) -> str:
        return cast(
            str, self.by_number("playbacks", self.integer("a playback number"), "playback")["id"]
        )

    def cue_ref(self) -> tuple[int, str | None]:
        token = self.take("a cue list number, as L or L/C")
        match = _CUE.fullmatch(token.text)
        if match is None:
            raise ParseError(f"expected a cue as L/C (e.g. 10/1), got {token.text!r}")
        return int(match[1]), match[2]

    def cue(self) -> tuple[EditPath, dict[str, Any]]:
        """``L/C``: the cue's edit path, and the cue."""
        list_number, cue_number = self.cue_ref()
        if cue_number is None:
            raise ParseError("expected a cue as L/C, e.g. 10/1")
        cue_list = self.by_number("cueLists", list_number, "cue list")
        cue = next((c for c in cue_list["cues"] if _same_cue(c["number"], cue_number)), None)
        if cue is None:
            raise ParseError(f"no cue {list_number}/{cue_number}")
        return ["cueLists", {"id": cue_list["id"]}, "cues", {"id": cue["id"]}], cast(
            dict[str, Any], cue
        )

    def master(self, what: str = 'a master name in quotes, e.g. "Speed 1"') -> str:
        """A master of any kind, named in quotes (any case)."""
        token = self.take(what, *_quoted(m["name"] for m in self.show["masters"]))
        if not token.quoted:
            raise ParseError(f"expected {what}")
        folded = token.text.casefold()
        found = next((m for m in self.show["masters"] if m["name"].casefold() == folded), None)
        if found is None:
            raise ParseError(f"no master {token.text!r}")
        return found["id"]

    def taken(self, collection: str) -> set[str]:
        return {item["id"] for item in self.show[collection]}  # type: ignore[literal-required]

    def new_id(self, prefix: str, collection: str) -> str:
        return self.ctx.ids.new(prefix, self.taken(collection))

    def free_number(self, collection: str, wanted: int) -> int:
        used = {item["number"] for item in self.show[collection]}  # type: ignore[literal-required]
        return wanted if wanted not in used else max(used) + 1

    # ------------------------------------------------------------- commands

    def command(self) -> Action:
        head = self.word("a command")
        handler = getattr(self, f"_cmd_{head}", None)
        if head in (
            "fixture",
            "group",
            "preset",
            "cuelist",
            "cue",
            "playback",
            "page",
            "universe",
            "show",
        ):
            return self._entity(head)
        if handler is None:
            raise ParseError(f"unknown command {self.tokens[0].text!r} (try 'help')")
        action: Action = handler()
        return action

    def submit(self, command: Mapping[str, Any], *notes: str) -> Submit:
        self.done()
        return Submit(cast(Command, dict(command)), tuple(notes))

    # selection

    def _cmd_sel(self) -> Action:
        if self.keyword("none"):
            return self.submit(
                {"type": "SELECT", "targets": {"kind": "targets", "refs": []}, "mode": "replace"}
            )
        mode = {"+": "add", "-": "remove"}.get(self.keyword("+", "-") or "", "replace")
        if self.keyword("playback"):
            return self.submit(
                {"type": "SELECT_PLAYBACK", "playbackId": self.playback_id(), "mode": mode}
            )
        return self.submit({"type": "SELECT", "targets": self.targets(), "mode": mode})

    def targets(self) -> dict[str, Any]:
        """``<t>[, <t>…]`` as a target spec: a group spec for one group, else a
        list of targets (groups expanded, duplicates dropped)."""
        items: list[dict[str, Any]] = []
        refs: list[dict[str, Any]] = []
        while True:
            kind = self.keyword("fixture", "group") or "fixture"
            if kind == "group":
                group = self.by_number("groups", self.integer("a group number"), "group")
                items.append({"kind": "group", "groupId": group["id"]})
                refs += group["members"]
            else:
                found = self.fixture_targets()
                items.append({"kind": "targets", "refs": found})
                refs += found
            if not self.keyword(","):
                break
        if len(items) == 1 and items[0]["kind"] == "group":
            return items[0]
        unique: dict[tuple[str, int], dict[str, Any]] = {}
        for ref in refs:
            unique.setdefault((ref["fixtureId"], ref["element"]), dict(ref))
        return {"kind": "targets", "refs": list(unique.values())}

    def target_refs(self) -> list[dict[str, Any]]:
        """``<t>[, <t>…]`` as a list of targets: a group's members, in order."""
        spec = self.targets()
        if spec["kind"] == "group":
            group = next(g for g in self.show["groups"] if g["id"] == spec["groupId"])
            return [dict(member) for member in group["members"]]
        return cast(list[dict[str, Any]], spec["refs"])

    def typed(self, start: int) -> str:
        """The tokens from ``start`` to the cursor, as typed (for messages)."""
        return " ".join(
            json.dumps(t.text) if t.quoted else t.text for t in self.tokens[start : self.k]
        )

    def fixture_range(self) -> list[dict[str, Any]]:
        """``N [thru M]``: whole fixtures, in number order."""
        first = self.integer("a fixture number")
        if not self.keyword("thru"):
            return [self.by_number("fixtures", first, "fixture")]
        last = self.integer("a fixture number after thru")
        low, high = sorted((first, last))
        found = sorted(
            (f for f in self.show["fixtures"] if low <= f["number"] <= high),
            key=lambda f: f["number"],
        )
        if not found:
            raise ParseError(f"no fixture from {first} to {last}")
        return cast(list[dict[str, Any]], found)

    def fixture_targets(self) -> list[dict[str, Any]]:
        first = self.take("a fixture number")
        number, element = self._fixture_number(first)
        if not self.keyword("thru"):
            fixture = self.by_number("fixtures", number, "fixture")
            return self._elements(fixture, element)
        number2, element2 = self._fixture_number(self.take("a fixture number after thru"))
        if element is not None or element2 is not None:
            if number != number2 or element is None or element2 is None:
                raise ParseError(
                    "thru between elements needs both on the same fixture, e.g. 301.1 thru 301.6"
                )
            fixture = self.by_number("fixtures", number, "fixture")
            step = 1 if element2 >= element else -1
            refs: list[dict[str, Any]] = []
            for e in range(element, element2 + step, step):
                refs += self._elements(fixture, e)
            return refs
        low, high = sorted((number, number2))
        fixtures = sorted(
            (f for f in self.show["fixtures"] if low <= f["number"] <= high),
            key=lambda f: f["number"],
            reverse=number2 < number,
        )
        if not fixtures:
            raise ParseError(f"no fixture from {number} to {number2}")
        return [
            ref
            for fixture in fixtures
            for ref in self._elements(cast(dict[str, Any], fixture), None)
        ]

    def _fixture_number(self, token: Token) -> tuple[int, int | None]:
        number, dot, element = token.text.partition(".")
        try:
            return int(number), (int(element) if dot else None)
        except ValueError:
            raise ParseError(
                f"expected a fixture number such as 101 or 301.2, got {token.text!r}"
            ) from None

    def _elements(self, fixture: Mapping[str, Any], element: int | None) -> list[dict[str, Any]]:
        count = self._element_count(fixture)
        if element is None:
            return [{"fixtureId": fixture["id"], "element": e} for e in range(count)]
        if not 1 <= element <= count:
            raise ParseError(
                f"fixture {fixture['number']} has {count} element(s); no element {element}"
            )
        return [{"fixtureId": fixture["id"], "element": element - 1}]

    def _element_count(self, fixture: Mapping[str, Any]) -> int:
        for profile in self.show["profiles"]:
            if profile["id"] == fixture["profileId"]:
                for mode in profile["modes"]:
                    if mode["id"] == fixture["modeId"]:
                        return len(mode["elements"])
        return 1

    # values

    def _cmd_set(self) -> Action:
        token = self.peek()
        if token is not None and token.lower.startswith("color."):
            self.k += 1
            return self._set_component(token.lower.removeprefix("color."))
        definition = self.attribute(*_COMPONENT_WORDS)
        if definition.kind == "scalar":
            if self.keyword("by"):
                return self._adjust(definition.id, delta=self.change())
            self.unsigned(definition.id)
        elif (token := self.peek()) is not None and token.lower == "by":
            if definition.kind == "color":
                raise ParseError(
                    "a colour changes by component: set color.r by 5% (r, g, b, w, a or uv)"
                )
            raise ParseError(f"{definition.id} is discrete: it has no relative values")
        if self.keyword("spread"):
            start = self.value(definition)
            self.keyword("to")
            end = self.value(definition)
            source: dict[str, Any] = {"kind": "spread", "from": start, "to": end}
            curve = self.keyword("center", "edges", "linear")
            if curve is not None and curve != "linear":
                source["curve"] = curve
        elif self.keyword("preset"):
            source = {"kind": "preset", "presetId": self.preset()["id"]}
        else:
            source = {"kind": "literal", "value": self.value(definition)}
        return self.submit({"type": "SET_ATTRIBUTE", "attribute": definition.id, "value": source})

    def _set_component(self, component: str) -> Action:
        """``set color.<c> [by] <value>``: one component of the colour."""
        if component not in COLOR_COMPONENTS:
            names = ", ".join(COLOR_COMPONENTS)
            raise ParseError(f"a colour has no component {component!r} ({names})")
        if self.keyword("by"):
            return self._adjust("color", component=component, delta=self.change())
        self.unsigned(f"color.{component}")
        value = self.number(f"the colour's {component}")
        return self._adjust("color", component=component, value=value)

    def _adjust(self, attribute: str, **fields: object) -> Action:
        return self.submit({"type": "ADJUST_ATTRIBUTE", "attribute": attribute, **fields})

    def change(self) -> float:
        return self.number("a change, e.g. 5% or -15")

    def unsigned(self, name: str) -> None:
        """Refuse a value with a plus sign where ``by`` may come instead:
        ``set intensity +5%`` would set 5%, not add it."""
        token = self.peek()
        if token is None or token.quoted or not token.text.startswith("+"):
            return
        if _NUMBER.fullmatch(token.text):
            bare = token.text[1:]
            raise ParseError(
                f"{token.text!r} has a plus sign: 'set {name} by {token.text}' changes "
                f"{name} by {bare}, 'set {name} {bare}' sets it"
            )

    def attribute(self, *also: str) -> AttributeDefinition:
        """An attribute's name; where the line ends, :func:`expected` offers
        the attributes, then ``also``."""
        token = self.take("an attribute", *ATTRIBUTES, *also)
        name = _ATTRIBUTE_NAMES.get(token.lower)
        if name is None:
            raise ParseError(f"unknown attribute {token.text!r}")
        return ATTRIBUTES[name]

    def value(
        self, definition: AttributeDefinition, targets: Sequence[TargetRef] | None = None
    ) -> Any:
        """An attribute's value. Where the line ends, a discrete attribute
        offers the options of ``targets`` (default: the selection)."""
        if definition.kind == "scalar":
            return self.number()
        if definition.kind == "discrete":
            names: list[str] = []
            if self.peek() is None:
                chosen = self.ctx.programmer.selection if targets is None else targets
                names = self._options(definition.id, chosen)
            token = self.take(f"a {definition.id} option", *names)
            return {"slot": token.text}
        color: dict[str, float] = {}
        for component in ("r", "g", "b"):
            color[component] = self.number(f"the colour's {component}")
        while (extra := self.keyword("w", "a", "uv")) is not None:
            color[extra] = self.number(f"the colour's {extra}")
        return color

    def _options(self, attribute: str, targets: Iterable[TargetRef]) -> list[str]:
        """The options the channels of ``attribute`` on ``targets`` offer."""
        fixtures = {fixture["id"]: fixture for fixture in self.show["fixtures"]}
        modes = {(p["id"], m["id"]): m for p in self.show["profiles"] for m in p["modes"]}
        names: dict[str, None] = {}
        for target in targets:
            fixture = fixtures.get(target["fixtureId"])
            mode = None if fixture is None else modes.get((fixture["profileId"], fixture["modeId"]))
            for channel in [] if mode is None else mode["channels"]:
                if channel["element"] == target["element"] and channel["attribute"] == attribute:
                    names.update((option, None) for option, _ in option_capabilities(channel))
        return list(names)

    def _cmd_preset(self) -> Action:
        return self.submit({"type": "APPLY_PRESET", "presetId": self.preset()["id"]})

    def _cmd_clear(self) -> Action:
        return self.submit({"type": "CLEAR_PROGRAMMER"})

    def _cmd_blind(self) -> Action:
        return self.submit({"type": "BLIND", "on": self.expect("on", "off") == "on"})

    def _cmd_highlight(self) -> Action:
        return self.submit({"type": "HIGHLIGHT", "on": self.expect("on", "off") == "on"})

    def _cmd_fade(self) -> Action:
        return self.submit({"type": "PROGRAMMER_FADE", "time": self.number("a time in seconds")})

    def _cmd_programmer(self) -> Action:
        self.done()
        return Query("programmer")

    # effects

    def _cmd_effect(self) -> Action:
        verb = self.expect("add", "remove", "clear", "template")
        if verb == "add":
            return self._effect_add()
        if verb == "template":
            self.expect("add")
            return self._template_add()
        if verb == "clear":
            return self.submit({"type": "REMOVE_EFFECT"})
        ids = (effect["id"] for effect in self.ctx.programmer.effects)
        return self.submit({"type": "REMOVE_EFFECT", "id": self.take("an effect id", *ids).text})

    def _effect_add(self) -> Action:
        """``effect add "<template>" [options]``: an instance of the template
        on the selection, after embedding a library template (module docs)."""
        names = [t["name"] for t in self.show["effects"]]
        names += [effect.template["name"] for effect in self.ctx.effects]
        token = self.take('a template name in quotes, e.g. "Circle"', *_quoted(names))
        template, defaults, embed = self._template(token.text)
        options: dict[str, Any] = {}
        while (option := self.keyword(*_EFFECT_OPTIONS)) is not None:
            if option in ("hz", "bpm"):
                key = "rate"
            elif option in _EFFECT_DIRECTIONS:
                key = "direction"
            else:
                key = option
            if key in options:  # given twice
                raise ParseError(f"unexpected {option!r}")
            options[key] = self._effect_option(option)
        self.done()
        selection = self.ctx.programmer.selection
        if not selection:
            raise ParseError("nothing selected")
        instance: dict[str, Any] = {
            "id": options.get("id") or self._effect_id(),
            "templateId": template["id"],
            "targets": {"kind": "targets", "refs": [dict(target) for target in selection]},
            "rate": options.get("rate") or self._default_rate(),
            "direction": options.get("direction", "forward"),
            "size": options.get("size", defaults.get("size", 1)),
        }
        low, high = options.get("low", (defaults.get("low"), defaults.get("high")))
        if low is not None:
            instance["low"] = low
        if high is not None:
            instance["high"] = high
        instance["phase"] = options.get("phase") or dict(
            defaults.get("phase", {"start": 0, "end": 0})
        )
        for key in ("groups", "blocks", "wings"):
            instance[key] = options.get(key, 1)
        for key, field_name in (
            ("fadein", "sizeFadeIn"),
            ("sizemaster", "sizeMasterId"),
            ("speedmaster", "speedMasterId"),
        ):
            if key in options:
                instance[field_name] = options[key]
        add = cast(Command, {"type": "ADD_EFFECT", "effect": instance})
        if not embed:
            return Submit(add)
        embedding = {"type": "ADD", "path": ["effects"], "value": deep_copy(template)}
        return SubmitAll((cast(Command, embedding), add))

    def _effect_option(self, option: str) -> Any:
        """The value of one ``effect add`` option (its keyword already taken)."""
        if option == "id":
            return self.take("an effect id").text
        if option == "hz":
            return {"kind": "hz", "value": self.number("a rate in Hz")}
        if option == "bpm":
            master = self.speed_master()
            multiplier = self.number("a multiplier") if self.keyword("x") else 1
            return {"kind": "bpm", "masterId": master, "multiplier": multiplier}
        if option == "size":
            return self.number("a size")
        if option == "low":
            low = self.number("a low value")
            self.expect("high")
            return low, self.number("a high value")
        if option == "phase":
            start = self.number("a start phase in degrees")
            return {"start": start, "end": self.number("an end phase in degrees")}
        if option in ("groups", "blocks", "wings"):
            return self.integer(f"a number of {option}")
        if option == "fadein":
            return self.number("a fade-in time in seconds")
        if option in ("sizemaster", "speedmaster"):
            return self.named_master(option.removesuffix("master"))
        return option  # a direction

    def _template(self, name: str) -> tuple[Mapping[str, Any], EffectDefaults, bool]:
        """The template to use, its console defaults and whether it must be
        embedded: the show's copy if it has one (the library's template id,
        or ``name`` as an id or a name, any case), else the library's. The
        defaults are the library's for that template id, if any."""
        library = self.ctx.effects.find(name)
        folded = name.casefold()
        embedded = next(
            (t for t in self.show["effects"]
             if (library is not None and t["id"] == library.template["id"])
             or t["id"] == name or t["name"].casefold() == folded),
            None,
        )  # fmt: skip
        if embedded is not None:
            known = self.ctx.effects.get(embedded["id"])
            return embedded, (known.defaults if known is not None else {}), False
        if library is None:
            raise ParseError(f"no template {name!r} in the library (see 'library')")
        return library.template, library.defaults, True

    def _default_rate(self) -> dict[str, Any]:
        """BPM ×1 on the show's only speed master, else 1 Hz."""
        speeds = [m for m in self.show["masters"] if m["kind"] == "speed"]
        if len(speeds) == 1:
            return {"kind": "bpm", "masterId": speeds[0]["id"], "multiplier": 1}
        return {"kind": "hz", "value": 1}

    def _effect_id(self) -> str:
        """``fx<n>`` with the lowest ``n`` that neither the programmer nor any
        cue uses, so recording with ``merge`` appends instead of replacing."""
        used = {effect["id"] for effect in self.ctx.programmer.effects}
        used |= {
            effect["id"]
            for cue_list in self.show["cueLists"]
            for cue in cue_list["cues"]
            for effect in cue["effects"]
        }
        n = 1
        while f"fx{n}" in used:
            n += 1
        return f"fx{n}"

    def _template_add(self) -> Action:
        """``effect template add "<name>" <JSON layers>``."""
        name = self._name()
        if name is None:
            raise self.fail("expected a template name in quotes")
        if any(t["name"].casefold() == name.casefold() for t in self.show["effects"]):
            raise ParseError(f"a template named {name!r} exists")
        example = 'expected the layers as a JSON list, e.g. [{"attribute": "pan", …}]'
        if self.ending(need="the layers as a JSON list"):
            raise _Unfinished(example)
        try:
            layers = json.loads(self.rest())
        except ValueError as exc:
            raise ParseError(f"{example}: {exc}") from None
        if not isinstance(layers, list):
            raise ParseError(example)
        value = {"id": self.new_id("ef", "effects"), "name": name, "layers": layers}
        return self.submit({"type": "ADD", "path": ["effects"], "value": value})

    # recording

    def options(self, *allowed: str) -> _Options:
        found = _Options()
        while (token := self.peek()) is not None:
            if token.quoted and "name" in allowed and found.name is None:
                self.k += 1
                found.name = token.text
            elif token.lower in _MERGES and "merge" in allowed and found.merge is None:
                self.k += 1
                found.merge = token.lower
            elif token.lower in _SCOPES and "scope" in allowed and found.scope is None:
                self.k += 1
                found.scope = token.lower
            elif token.lower == "freeze" and "freeze" in allowed:
                self.k += 1
                found.freeze = True
            elif token.lower == "only" and "only" in allowed:
                self.k += 1
                while (family := self.keyword(*_FAMILIES)) is not None:
                    found.families.append(family)
                if not found.families:
                    raise self.fail(
                        f"expected attribute families after only ({', '.join(_FAMILIES)})"
                    )
            else:
                raise ParseError(f"unexpected {token.text!r}")
        self.ending(  # the options still free
            *(_MERGES if "merge" in allowed and found.merge is None else ()),
            *(_SCOPES if "scope" in allowed and found.scope is None else ()),
            *(("only",) if "only" in allowed and not found.families else ()),
            *(("freeze",) if "freeze" in allowed and not found.freeze else ()),
            need="a name in quotes" if "name" in allowed and found.name is None else "",
        )
        return found

    def _cmd_record(self) -> Action:
        kind = self.expect("group", "preset", "cue", "slot")
        if kind == "group":
            number = self.integer("a group number")
            options = self.options("merge", "name")
            return self.submit(
                _record("RECORD_GROUP", number=number, merge=options.merge, name=options.name)
            )
        if kind == "preset":
            pool = self.expect(*_POOLS)
            number = self.integer("a preset number")
            options = self.options("merge", "name", "scope")
            scope = options.scope or _DEFAULT_SCOPE[pool]
            return self.submit(
                _record(
                    "RECORD_PRESET",
                    pool=pool,
                    number=number,
                    scope=scope,
                    merge=options.merge,
                    name=options.name,
                )
            )
        if kind == "cue":
            return self._record_cue()
        return self._record_slot()

    def _record_cue(self) -> Action:
        list_number, cue_number = self.cue_ref()
        options = self.options("merge", "name", "only", "freeze")
        existing = next((cl for cl in self.show["cueLists"] if cl["number"] == list_number), None)
        list_id = existing["id"] if existing is not None else self.new_id("cl", "cueLists")
        record = _record(
            "RECORD_CUE",
            cueListId=list_id,
            cueNumber=cue_number,
            filter=options.families or None,
            merge=options.merge,
            name=options.name,
            freeze=options.freeze or None,
        )
        if existing is not None:
            return self.submit(record)
        cue_list = _cue_list(list_id, list_number, f"Cue list {list_number}")
        return self.submit(
            {
                "type": "BATCH",
                "label": "",
                "commands": [{"type": "ADD", "path": ["cueLists"], "value": cue_list}, record],
            }
        )

    def _record_slot(self) -> Action:
        token = self.take("a slot number, as S or P.S")
        match = _SLOT.fullmatch(token.text)
        if token.quoted or match is None:
            raise ParseError(f"expected a slot number, as S or P.S, got {token.text!r}")
        slot = int(match[2])
        if slot < 1:
            raise ParseError("slots are counted from 1")
        page = (
            self.current_page()
            if match[1] is None
            else self.by_number("pages", int(match[1]), "page")
        )
        options = self.options("merge", "name", "only")
        on = f"on page {page['number']}"
        occupant = page["slots"][slot - 1] if slot <= len(page["slots"]) else None
        families = options.families or None
        if occupant is not None:
            if options.merge is None:
                raise ParseError(f"slot {slot} is in use {on}: add merge, replace or remove")
            playback = next(p for p in self.show["playbacks"] if p["id"] == occupant)
            runs = next(cl for cl in self.show["cueLists"] if cl["id"] == playback["cueListId"])
            first = runs["cues"][0]["number"] if runs["cues"] else "1"
            return self.submit(
                _record(
                    "RECORD_CUE",
                    cueListId=runs["id"],
                    cueNumber=first,
                    filter=families,
                    merge=options.merge,
                    name=options.name,
                )
            )
        if options.merge is not None:
            raise ParseError(f"slot {slot} is empty {on}: record it without {options.merge}")
        number = self.free_number("playbacks", slot)
        name = options.name or f"Playback {number}"
        fader = "size" if self._effects_only(families) else "master"
        list_id = self.new_id("cl", "cueLists")
        playback_id = self.new_id("pb", "playbacks")
        cue_list = _cue_list(list_id, self.free_number("cueLists", slot), name)
        commands = [
            {"type": "ADD", "path": ["cueLists"], "value": cue_list},
            _record("RECORD_CUE", cueListId=list_id, cueNumber="1", filter=families, name=name),
            {
                "type": "ADD",
                "path": ["playbacks"],
                "value": _playback(playback_id, number, name, list_id, fader),
            },
            {
                "type": "ASSIGN_PLAYBACK",
                "pageId": page["id"],
                "slot": slot - 1,
                "playbackId": playback_id,
            },
        ]
        on_first = page is min(self.show["pages"], key=lambda p: p["number"])
        where = str(slot) if on_first else f"{page['number']}.{slot}"
        label = f"recorded slot {where}: playback {number} {name!r}"
        return self.submit({"type": "BATCH", "label": label, "commands": commands})

    def current_page(self) -> dict[str, Any]:
        """The engine's current page, else (no engine, or a page the show no
        longer has) the first page, where the engine starts."""
        pages = self.show["pages"]
        if not pages:
            raise ParseError("the show has no page: add one first")
        current = next((p for p in pages if p["id"] == self.ctx.page), None)
        return cast(dict[str, Any], current or min(pages, key=lambda p: p["number"]))

    def _effects_only(self, families: Sequence[str] | None) -> bool:
        """Whether the cue ``record slot`` records will hold only effects: the
        programmer has no value in ``families`` (default: every family
        recorded) and an effect with a template layer in them."""
        wanted = set(families or _FAMILIES)
        programmer = self.ctx.programmer
        for key in programmer.values:
            split = split_slot_key(key)
            if split is not None and ATTRIBUTES[split[1]].family in wanted:
                return False
        templates = {template["id"]: template for template in self.show["effects"]}
        return any(
            ATTRIBUTES[layer["attribute"]].family in wanted
            for effect in programmer.effects
            if effect["templateId"] in templates
            for layer in templates[effect["templateId"]]["layers"]
        )

    # patch

    def _universe_add(self) -> Action:
        number = self.integer("a universe number")
        name = self._name() or f"Universe {number}"
        if any(u["number"] == number for u in self.show["universes"]):
            raise ParseError(f"universe {number} exists")
        value = {"id": self.new_id("u", "universes"), "name": name, "number": number}
        return self.submit({"type": "ADD", "path": ["universes"], "value": value})

    def _fixture_add(self) -> Action:
        first = self.integer("a fixture number")
        last = self.integer("a fixture number after thru") if self.keyword("thru") else first
        if last < first:
            raise ParseError("fixture add needs ascending numbers: N thru M with M ≥ N")
        names = [p["name"] for p in self.show["profiles"]] + [p["name"] for p in self.ctx.library]
        token = self.take('a profile name in quotes, e.g. "Generic Spot 16ch"', *_quoted(names))
        self.expect("mode")
        offered: list[str] = []
        if self.peek() is None:  # Tab offers the profile's modes
            with contextlib.suppress(ParseError):
                offered = [_word(m["name"]) for m in self._profile(token.text)[0]["modes"]]
        mode_name = self.take("a mode name", *offered).text
        patch: tuple[str, int] | None = None
        if self.keyword("at"):
            patch = self._address()
        self.done()
        profile, notes, embed = self._profile(token.text)
        mode = next(
            (
                m
                for m in profile["modes"]
                if mode_name.lower() in (m["name"].lower(), m["id"].lower())
            ),
            None,
        )
        if mode is None:
            modes = ", ".join(m["name"] for m in profile["modes"])
            raise ParseError(
                f"profile {profile['name']!r} has no mode {mode_name!r} (modes: {modes})"
            )
        used = {f["number"] for f in self.show["fixtures"]}
        taken = self.taken("fixtures")
        commands: list[dict[str, Any]] = []
        if embed:
            commands.append({"type": "ADD", "path": ["profiles"], "value": profile})
        for k, number in enumerate(range(first, last + 1)):
            if number in used:
                raise ParseError(f"fixture {number} exists")
            ident = self.ctx.ids.new("fx", taken)
            taken.add(ident)
            address = None
            if patch is not None:
                address = {"universeId": patch[0], "address": patch[1] + k * mode["footprint"]}
            commands.append({"type": "ADD", "path": ["fixtures"], "value": {
                "id": ident, "name": f"{profile['model']} {number}", "number": number,
                "profileId": profile["id"], "profileRevision": profile["revision"],
                "modeId": mode["id"], "patch": address,
                "orientation": {"invertPan": False, "invertTilt": False, "swapPanTilt": False,
                                "panOffset": 0, "tiltOffset": 0}}})  # fmt: skip
        span = f"{first}" if first == last else f"{first}–{last}"
        label = f"added fixture {span}: {profile['name']}, {mode['name']}"
        return Submit(cast(Command, {"type": "BATCH", "label": label, "commands": commands}), notes)

    def _profile(self, name: str) -> tuple[dict[str, Any], tuple[str, ...], bool]:
        """The profile to use: the show's embedded copy if it has one (with a
        note when the library's revision differs), else the library's, which
        must then be embedded."""
        library = self.ctx.library.find(name)
        folded = name.casefold()
        embedded = next(
            (p for p in self.show["profiles"]
             if (library is not None and p["id"] == library["id"])
             or p["id"] == name or p["name"].casefold() == folded),
            None,
        )  # fmt: skip
        if embedded is not None:
            notes: tuple[str, ...] = ()
            if library is not None and library["revision"] != embedded["revision"]:
                notes = (
                    f"warning: the show embeds {embedded['name']!r} revision "
                    f"{embedded['revision']!r}, the library has {library['revision']!r}: "
                    "using the show's copy",
                )
            return cast(dict[str, Any], embedded), notes, False
        if library is None:
            raise ParseError(f"no profile {name!r} in the library (see 'library')")
        return cast(dict[str, Any], library), (), True

    def _address(self) -> tuple[str, int]:
        token = self.take("an address as U.A, e.g. 1.101")
        universe, dot, address = token.text.partition(".")
        try:
            number, start = int(universe), int(address)
        except ValueError:
            raise ParseError(
                f"expected an address as U.A, e.g. 1.101, got {token.text!r}"
            ) from None
        if not dot:
            raise ParseError(f"expected an address as U.A, e.g. 1.101, got {token.text!r}")
        found = self.by_number("universes", number, "universe")
        return cast(str, found["id"]), start

    # output and surfaces

    def _cmd_route(self) -> Action:
        self.expect("add")
        universe = self.by_number("universes", self.integer("a universe number"), "universe")
        protocol = self.expect("sacn", "artnet", "dmxusb")
        route: dict[str, Any] = {
            "id": self._route_id(),
            "universeId": universe["id"],
            "enabled": True,
            "protocol": "dmxUsb" if protocol == "dmxusb" else protocol,
        }
        if protocol == "dmxusb":
            driver = self.expect("enttecpro", "dmxking")
            route["device"] = {
                "driver": "enttecPro" if driver == "enttecpro" else driver,
                "port": self.take("a serial port such as /dev/ttyUSB0").text,
            }
            route["refreshHz"] = self.number("a refresh rate in Hz") if self.keyword("hz") else 40
            return self.submit({"type": "ADD", "path": ["output", "routes"], "value": route})
        if protocol == "sacn":
            route["universe"] = self.integer("an sACN universe")
            route["priority"] = 100
            fallback = {"kind": "multicast", "iface": self.ctx.iface}
        else:
            token = self.take("an Art-Net port address as net.sub.universe")
            parts = token.text.split(".")
            if len(parts) != 3 or not all(part.isdigit() for part in parts):
                raise ParseError(
                    f"expected an Art-Net port address as net.sub.universe, got {token.text!r}"
                )
            net, sub, uni = (int(part) for part in parts)
            route["portAddress"] = {"net": net, "subNet": sub, "universe": uni}
            fallback = {"kind": "broadcast", "iface": self.ctx.iface}
        where = self.keyword("unicast", "multicast", "broadcast")
        if where == "unicast":
            route["destination"] = {"kind": "unicast", "host": self.take("a host").text}
        elif where is not None:
            route["destination"] = {"kind": where, "iface": self.take("an interface").text}
        else:
            route["destination"] = fallback
        return self.submit({"type": "ADD", "path": ["output", "routes"], "value": route})

    def _route_id(self) -> str:
        return self.ctx.ids.new("r", {r["id"] for r in self.show["output"]["routes"]})

    def _cmd_surface(self) -> Action:
        """``surface add midi|osc|web …`` or ``surface "<name>" pickup soft|jump``."""
        if not self.keyword("add"):
            surface = self.surface()
            self.expect("pickup")
            pickup = self.expect("soft", "jump")
            path = ["surfaces", {"id": surface["id"]}, "faderPickup"]
            return self.submit({"type": "SET", "path": path, "value": pickup})
        kind = self.expect("midi", "osc", "web")
        if kind == "midi":
            name = self.take('a device name in quotes, e.g. "nanoKONTROL2"').text
            match: dict[str, Any] = {"deviceName": name}
        else:
            name = self._name() or ""
            if not name:
                raise self.fail("expected a name in quotes")
            match = self._listening(kind)
        if any(s["name"].casefold() == name.casefold() for s in self.show["surfaces"]):
            raise ParseError(f"a surface named {name!r} exists")
        value = {"id": self.new_id("s", "surfaces"), "name": name, "kind": kind,
                 "match": match, "faderPickup": "jump"}  # fmt: skip
        return self.submit({"type": "ADD", "path": ["surfaces"], "value": value})

    def _listening(self, kind: str) -> dict[str, Any]:
        """The ``match`` of an OSC (``[port N] [feedback <host>[:<port>]]``)
        or web (``[port N] [on <host>]``) surface, options in any order. The
        port defaults to :data:`_DEFAULT_PORTS` and must be free among the
        surfaces of that kind."""
        options: dict[str, Any] = {}
        other = "feedback" if kind == "osc" else "on"
        while (option := self.keyword("port", other)) is not None and option not in options:
            if option == "port":
                token = self.take("a port")
                options[option] = _port(token.text)
                if options[option] is None:
                    raise ParseError(f"expected a port (1–65535), got {token.text!r}")
            elif option == "on":
                options[option] = self.take("a host").text
            else:
                options[option] = self._feedback_target()
        if option is not None:  # given twice
            raise ParseError(f"unexpected {option!r}")
        port = options.get("port", _DEFAULT_PORTS[kind])
        user = next(
            (s for s in self.show["surfaces"]
             if s["kind"] == kind and s["match"].get("port") == port),
            None,
        )  # fmt: skip
        if user is not None:
            raise ParseError(f"port {port} is in use by surface {user['name']!r}")
        match: dict[str, Any] = {"port": port}
        if "on" in options:
            match["host"] = options["on"]
        match.update(options.get("feedback", {}))
        return match

    def _feedback_target(self) -> dict[str, Any]:
        """``<host>[:<port>]``, either part left out but not both, as
        ``match.host`` and ``match.feedbackPort``."""
        token = self.take("<host>[:<port>]")
        host, colon, port = token.text.rpartition(":")
        if not colon:
            host, port = token.text, ""
        if not (host or port) or (port and _port(port) is None):
            raise ParseError(f"expected <host>[:<port>], got {token.text!r}")
        target: dict[str, Any] = {"host": host} if host else {}
        if port:
            target["feedbackPort"] = int(port)
        return target

    def surface(self) -> dict[str, Any]:
        """A surface named in quotes (any case; a MIDI surface also by its device)."""
        names = _quoted(s["name"] for s in self.show["surfaces"])
        name = self.take("a surface name in quotes", *names).text
        folded = name.casefold()
        surface = next(
            (s for s in self.show["surfaces"]
             if folded in (s["name"].casefold(), s["match"].get("deviceName", "").casefold())),
            None,
        )  # fmt: skip
        if surface is None:
            raise ParseError(f"no surface {name!r}")
        return cast(dict[str, Any], surface)

    def _cmd_bind(self) -> Action:
        surface = self.surface()
        address = self.address(clock=True)
        action: dict[str, Any]
        if address["kind"] == "midiClock":  # an external clock only taps
            self.expect("tap")
            action = {"kind": "tap", "masterId": self.speed_master()}
        else:
            action = self._what()
        value = {
            "id": self.new_id("b", "bindings"),
            "surfaceId": surface["id"],
            "input": address,
            "action": action,
        }
        if (token := self.peek()) is not None:
            kind = self.keyword(*_FEEDBACK)
            if kind is None:
                raise ParseError(f"expected led, motor or display, got {token.text!r}")
            target = address if self.ending("cc", "note", "osc") else self.address()
            if target["kind"] == "midiClock":
                raise ParseError("a clock input has no feedback address: give one")
            value["feedback"] = {"kind": _FEEDBACK[kind], "address": target}
        else:
            self.offers += _FEEDBACK  # a feedback may follow
        return self.submit({"type": "ADD", "path": ["bindings"], "value": value})

    def address(self, *, clock: bool = False) -> dict[str, Any]:
        """``cc|note <channel> <number>``, ``osc "/path"`` or (``clock``) ``clock``."""
        kinds = ("cc", "note", "osc", "clock") if clock else ("cc", "note", "osc")
        kind = self.expect(*kinds)
        if kind == "clock":
            return {"kind": "midiClock"}
        if kind == "osc":
            what = 'an OSC path in quotes, e.g. "/1/fader1"'
            token = self.take(what)
            if not token.quoted or not token.text.startswith("/"):
                raise ParseError(f"expected {what}")
            return {"kind": "osc", "path": token.text}
        channel = self.integer("a MIDI channel (1–16)")
        control = self.integer("a CC or note number")
        if kind == "cc":
            return {"kind": "midiCC", "channel": channel, "cc": control}
        return {"kind": "midiNote", "channel": channel, "note": control}

    def _what(self) -> dict[str, Any]:
        """A binding's ``<what>``: the action."""
        what = self.expect(
            "fader", "button", "master", "tap", "blackout", "page", "release", "output"
        )
        if what == "release":
            self.expect("all")
            return {"kind": "command", "command": self._release_all()}
        if what == "output":
            on = self.expect("on", "off") == "on"
            return {"kind": "command", "command": {"type": "OUTPUT", "on": on}}
        if what == "fader":
            if self.keyword("playback"):
                return {"kind": "playbackFaderAbs", "playbackId": self.playback_id()}
            return {"kind": "playbackFader", "slot": self._slot()}
        if what == "button":
            slot = self._slot()
            button = self.integer("a button number (from 1)")
            if button < 1:
                raise ParseError("buttons are counted from 1")
            return {"kind": "playbackButton", "slot": slot, "button": button - 1}
        if what == "master":
            master: str
            if self.keyword("gm"):
                grand = next((m for m in self.show["masters"] if m["kind"] == "grand"), None)
                if grand is None:
                    raise ParseError("the show has no grand master")
                master = grand["id"]
            else:
                master = self.master('gm or a master name in quotes, e.g. "Speed 1"')
            return {"kind": "master", "masterId": master}
        if what == "tap":
            return {"kind": "tap", "masterId": self.speed_master()}
        if what == "blackout":
            action: dict[str, Any] = {"kind": "blackout"}
            if self.keyword("momentary"):
                action["momentary"] = True
            return action
        token = self.take("+N, -N or a page number")
        if re.fullmatch(r"[+-]\d+", token.text) and not token.quoted:
            return {"kind": "page", "delta": int(token.text)}
        if not token.text.isdigit() or token.quoted:
            raise ParseError(f"expected +N, -N or a page number, got {token.text!r}")
        page = self.by_number("pages", int(token.text), "page")
        return {"kind": "pageAbs", "number": page["number"]}

    def _cmd_feedback(self) -> Action:
        """``feedback "<s>" <inputs> led|motor|display|none``: set or remove
        the feedback of every binding of those inputs, on their own address."""
        surface = self.surface()
        addresses = self.inputs()
        kind = self.keyword(*_FEEDBACK, "none")
        if kind is None:
            token = self.peek()
            got = f", got {token.text!r}" if token else ""
            raise self.fail(f"expected led, motor, display or none{got}")
        commands = []
        for address in addresses:
            for binding in self.bound(surface, address):
                path = ["bindings", {"id": binding["id"]}, "feedback"]
                if kind != "none":
                    value = {"kind": _FEEDBACK[kind], "address": address}
                    commands.append({"type": "SET", "path": path, "value": value})
                elif "feedback" in binding:
                    commands.append({"type": "DELETE", "path": path})
        if not commands:
            raise ParseError("no feedback to remove")
        count = len(commands)
        label = (
            f"feedback removed from {count} binding{'s' * (count != 1)}"
            if kind == "none"
            else f"feedback on {count} binding{'s' * (count != 1)}"
        )
        return self.submit({"type": "BATCH", "label": label, "commands": commands})

    def _cmd_unbind(self) -> Action:
        """``unbind "<s>" <inputs>``: remove every binding of those inputs
        (Phase 7: the §5.24 script moves marker SET to ``release all``)."""
        surface = self.surface()
        addresses = self.inputs()
        commands = [
            {"type": "DELETE", "path": ["bindings", {"id": binding["id"]}]}
            for address in addresses
            for binding in self.bound(surface, address)
        ]
        count = len(commands)
        label = f"unbound {count} binding{'s' * (count != 1)}"
        return self.submit({"type": "BATCH", "label": label, "commands": commands})

    def inputs(self) -> list[dict[str, Any]]:
        """``<input> [thru <number>]``: one input, or a run of CCs or notes
        on one channel, ``thru`` counting either way."""
        first = self.address()
        if first["kind"] == "osc" or not self.keyword("thru"):
            return [first]
        field = "cc" if first["kind"] == "midiCC" else "note"
        last = self.integer("a CC or note number after thru")
        step = 1 if last >= first[field] else -1
        return [{**first, field: n} for n in range(first[field], last + step, step)]

    def bound(self, surface: Mapping[str, Any], address: Mapping[str, Any]) -> list[Any]:
        """The surface's bindings on ``address``; at least one, or an error."""
        bound = [
            b for b in self.show["bindings"]
            if b["surfaceId"] == surface["id"] and b["input"] == address
        ]  # fmt: skip
        if not bound:
            raise ParseError(f"{surface['name']!r} has no binding on {_address_text(address)}")
        return bound

    def _slot(self) -> int:
        slot = self.integer("a slot number (from 1)")
        if slot < 1:
            raise ParseError("slots are counted from 1")
        return slot - 1

    # generic edits

    def _entity(self, head: str) -> Action:
        """``fixture …`` / ``universe …`` sub-commands, then ``<entity> <prop> <value>``."""
        if head == "fixture":
            if self.keyword("add"):
                return self._fixture_add()
            following = self.peek(1)
            if following is not None and following.lower == "patch":
                return self._patch()
            thru = following is not None and following.lower == "thru"
            after = self.peek(3) if thru else following
            if (after is not None and after.lower == "limits") or (thru and after is None):
                return self._limits()  # N thru M comes only before limits
            if following is None and self.peek() is not None:  # fixture N: Tab offers these
                self.offers += ("patch", "thru", "limits")
        if head == "universe" and self.keyword("add"):
            return self._universe_add()
        if head == "page":
            if self.keyword("add"):
                return self._page_add()
            if (step := self.keyword("next", "prev")) is not None:
                return self.submit({"type": "PAGE", "delta": 1 if step == "next" else -1})
        if head == "preset" and len(self.tokens) - self.k == 2:  # preset <pool> N: apply it
            return self._cmd_preset()
        if head == "cue":
            ref = self.peek()
            path, cue = self.cue()
            if self.keyword("effect"):
                return self._cue_effect(path, cue, ref.text if ref is not None else "")
            verb = self.keyword(*_CUE_VERBS)
            if verb is not None:
                return self._cue_verb(path, cue, verb)
        else:
            path = self.entity_path(head)
        if head == "page":
            page = _element(self.show["pages"], path)
            if self.ending("slot"):  # page N: go to it
                return self.submit({"type": "PAGE", "number": page["number"]})
            if self.keyword("slot"):
                return self._assign(page["id"])
        if head == "playback" and self.keyword("goto"):
            return self._goto_cue(path)
        if head == "cuelist":
            if self.keyword("sequence"):
                return self.submit({"type": "SET", "path": [*path, "mode"], "value": "sequence"})
            words = [token.lower for token in self.tokens[self.k : self.k + 2]]
            if words in (["chase", "hz"], ["chase", "bpm"]):  # else chase {json}: a plain SET
                self.k += 1
                return self._chase(path)
            if not words:
                self.offers.append("chase")
            elif words == ["chase"]:
                self.offers += ("hz", "bpm")
        return self._set(path, "name or timing.fadeIn")

    def _page_add(self) -> Action:
        """``page add N ["name"]``: a page with no slots (``ASSIGN_PLAYBACK``
        extends them)."""
        number = self.integer("a page number")
        if any(page["number"] == number for page in self.show["pages"]):
            raise ParseError(f"page {number} exists")
        name = self._name() or f"Page {number}"
        value = {"id": self.new_id("page", "pages"), "name": name, "number": number, "slots": []}
        return self.submit({"type": "ADD", "path": ["pages"], "value": value})

    def _assign(self, page: str) -> Action:
        """``page P slot S playback N`` or ``page P slot S clear``."""
        slot = self._slot()
        playback = None if self.expect("playback", "clear") == "clear" else self.playback_id()
        return self.submit(
            {"type": "ASSIGN_PLAYBACK", "pageId": page, "slot": slot, "playbackId": playback}
        )

    def _goto_cue(self, path: EditPath) -> Action:
        """``playback N goto <cue>``: the cue its ``goto`` buttons go to."""
        playback = _element(self.show["playbacks"], path)
        token = self.take("a cue number")
        if token.quoted or CUE_NUMBER.fullmatch(token.text) is None:
            raise ParseError(f"expected a cue number, got {token.text!r}")
        runs = next(cl for cl in self.show["cueLists"] if cl["id"] == playback["cueListId"])
        cue = next((c for c in runs["cues"] if _same_cue(c["number"], token.text)), None)
        if cue is None:
            raise ParseError(f"no cue {runs['number']}/{token.text}")
        return self.submit({"type": "SET", "path": [*path, "gotoCue"], "value": cue["number"]})

    def _set(self, path: EditPath, example: str) -> Action:
        """``<prop[.sub…]> <value>`` under ``path``: the value as JSON, else
        the raw text as a string."""
        prop = self.take(f"a property, e.g. {example}")
        keys = prop.text.split(".")
        if not all(keys):
            raise ParseError(f"expected a property, got {prop.text!r}")
        raw = self.rest()
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw
        return Submit(cast(Command, {"type": "SET", "path": [*path, *keys], "value": value}))

    def _cue_effect(self, path: EditPath, cue: Mapping[str, Any], ref: str) -> Action:
        """``cue L/C effect <id> <prop[.sub…]> <value>``: a property of one
        of the cue's effect instances."""
        ident = self.take("an effect id", *(effect["id"] for effect in cue["effects"])).text
        if not any(effect["id"] == ident for effect in cue["effects"]):
            raise ParseError(f"cue {ref} has no effect {ident!r}")
        return self._set([*path, "effects", {"id": ident}], "size or rate.multiplier")

    def _cue_verb(self, path: EditPath, cue: Mapping[str, Any], verb: str) -> Action:
        """``cue L/C time|go|follow|wait|release …``: edits of the cue's timing,
        trigger or releases."""
        if verb == "time":
            family = self.keyword(*_FAMILIES)
            if family is not None:
                timing: dict[str, Any] = {"fade": self.number("a fade time")}
                timing["delay"] = self.number("a delay") if self.keyword("delay") else 0
                if (curve := self.curve()) is not None:
                    timing["curve"] = curve
                families = {**cue["timing"].get("perFamily", {}), family: timing}
                return self.submit(
                    {"type": "SET", "path": [*path, "timing", "perFamily"], "value": families}
                )
            fade_in, fade_out = self.pair("a fade time")
            fields: dict[str, Any] = {"fadeIn": fade_in, "fadeOut": fade_out}
            if self.keyword("delay"):
                fields["delayIn"], fields["delayOut"] = self.pair("a delay")
            if (curve := self.curve()) is not None:
                fields["curve"] = curve
            sets = [
                {"type": "SET", "path": [*path, "timing", key], "value": value}
                for key, value in fields.items()
            ]
            return self.submit(_batch(*sets))
        if verb == "release":
            release = {"targets": self.targets(), "attributes": self._attributes()}
            releases = [*cue.get("releases", []), release]
            return self.submit({"type": "SET", "path": [*path, "releases"], "value": releases})
        trigger: dict[str, Any] = {"kind": verb}
        if verb != "go":
            trigger["delay"] = self.number("a delay")
        return self.submit({"type": "SET", "path": [*path, "trigger"], "value": trigger})

    def _attributes(self) -> list[str] | str:
        """``[only <attribute>…]``: the attributes a release names, else ``"all"``."""
        if not self.keyword("only"):
            return "all"
        names = []
        while (token := self.peek()) is not None and token.lower in _ATTRIBUTE_NAMES:
            self.k += 1
            names.append(_ATTRIBUTE_NAMES[token.lower])
        self.ending(*ATTRIBUTES)
        if not names:
            got = "" if token is None else f", got {token.text!r}"
            raise self.fail(f"expected attribute names after only{got}")
        return names

    def _chase(self, path: EditPath) -> Action:
        """``cuelist N chase hz|bpm …``: the chase settings, then chase mode."""
        rate: dict[str, Any]
        if self.expect("hz", "bpm") == "hz":
            rate = {"kind": "hz", "value": self.number("a rate in Hz")}
        else:
            master = self.speed_master()
            multiplier = self.number("a multiplier") if self.keyword("x") else 1
            rate = {"kind": "bpm", "masterId": master, "multiplier": multiplier}
        direction = self.keyword(*_DIRECTIONS) or "forward"
        crossfade = self.number("a crossfade fraction") if self.keyword("crossfade") else 0
        chase = {"rate": rate, "direction": direction, "crossfade": crossfade}
        return self.submit(
            _batch(
                {"type": "SET", "path": [*path, "chase"], "value": chase},
                {"type": "SET", "path": [*path, "mode"], "value": "chase"},
            )
        )

    def _patch(self) -> Action:
        fixture = self.by_number("fixtures", self.integer("a fixture number"), "fixture")
        self.expect("patch")
        if self.keyword("none"):
            patch = None
        else:
            universe, address = self._address()
            patch = {"universeId": universe, "address": address}
        return self.submit({"type": "PATCH_FIXTURE", "fixtureId": fixture["id"], "patch": patch})

    def entity_path(self, head: str) -> EditPath:
        if head == "show":
            return []
        if head == "preset":
            return ["presets", {"id": self.preset()["id"]}]
        if head == "cue":
            return self.cue()[0]
        collection, what = _COLLECTIONS[head]
        item = self.by_number(collection, self.integer(f"a {what} number"), what)
        return [collection, {"id": item["id"]}]

    def _cmd_rename(self) -> Action:
        head = self.word("an entity", *sorted(_ENTITIES))
        if head not in _ENTITIES:
            raise ParseError(f"cannot rename {head!r}")
        path = self.entity_path(head)
        name = self._name()
        if name is None:
            raise self.fail("expected a name in quotes")
        keys: EditPath = ["meta", "title"] if head == "show" else [*path, "name"]
        return self.submit({"type": "SET", "path": keys, "value": name})

    def _cmd_delete(self) -> Action:
        head = self.word("an entity", *sorted(_ENTITIES - {"show"}))
        if head not in _ENTITIES or head == "show":
            raise ParseError(f"cannot delete {head!r}")
        return self.submit({"type": "DELETE", "path": self.entity_path(head)})

    def _name(self) -> str | None:
        token = self.peek()
        if token is not None and token.quoted:
            self.k += 1
            return token.text
        self.ending(need="a name in quotes")
        return None

    # performance

    def _cmd_go(self) -> Action:
        return self.submit({"type": "GO", "playbackId": self.playback_id()})

    def _cmd_back(self) -> Action:
        return self.submit({"type": "BACK", "playbackId": self.playback_id()})

    def _cmd_flash(self) -> Action:
        playback = self.playback_id()
        down = self.expect("on", "off") == "on"
        return self.submit({"type": "FLASH", "playbackId": playback, "down": down})

    def _cmd_toggle(self) -> Action:
        return self.submit({"type": "TOGGLE_PLAYBACK", "playbackId": self.playback_id()})

    def _cmd_button(self) -> Action:
        """``button N <b> on|off``: a ``select`` button's press is the
        programmer's ``SELECT_PLAYBACK``, as the binding resolver sends it;
        every other press and release is ``PLAYBACK_BUTTON``."""
        playback = self.by_number("playbacks", self.integer("a playback number"), "playback")
        buttons = playback["buttons"]
        button = self.integer("a button number (from 1)")
        if button < 1:
            raise ParseError("buttons are counted from 1")
        if button > len(buttons):
            raise ParseError(
                f"playback {playback['number']} has {len(buttons)} button(s); no button {button}"
            )
        down = self.expect("on", "off") == "on"
        if down and buttons[button - 1] == "select":
            return self.submit(
                {"type": "SELECT_PLAYBACK", "playbackId": playback["id"], "mode": "replace"}
            )
        return self.submit(
            {
                "type": "PLAYBACK_BUTTON",
                "playbackId": playback["id"],
                "button": button - 1,
                "down": down,
            }
        )

    def _cmd_goto(self) -> Action:
        playback = self.playback_id()
        token = self.take("a cue number")
        if token.quoted or CUE_NUMBER.fullmatch(token.text) is None:
            raise ParseError(f"expected a cue number, got {token.text!r}")
        return self.submit({"type": "GOTO", "playbackId": playback, "cueNumber": token.text})

    def _cmd_release(self) -> Action:
        if self.keyword("all"):  # every playback: the panic release (decision 15)
            return self.submit(self._release_all())
        command: dict[str, Any] = {"type": "RELEASE_PLAYBACK", "playbackId": self.playback_id()}
        if not self.ending(need="a time in seconds"):  # the playback's releaseTime otherwise
            command["time"] = self.number("a time in seconds")
        return self.submit(command)

    def _cmd_fader(self) -> Action:
        playback = self.playback_id()
        return self.submit(
            {"type": "SET_FADER", "playbackId": playback, "level": self.number("a level")}
        )

    def _cmd_gm(self) -> Action:
        grand = next((m for m in self.show["masters"] if m["kind"] == "grand"), None)
        if grand is None:
            raise ParseError("the show has no grand master")
        return self.submit(
            {"type": "SET_MASTER", "masterId": grand["id"], "level": self.number("a level")}
        )

    def _cmd_master(self) -> Action:
        if self.keyword("add"):
            return self._master_add()
        master = self.master('a master name in quotes, e.g. "Speed 1", or add')
        return self.submit(
            {"type": "SET_MASTER", "masterId": master, "level": self.number("a level")}
        )

    def _master_add(self) -> Action:
        """``master add speed "<name>" [bpm <x>] [steps <a>, <b>…]``,
        ``master add size "<name>"``, ``master add group "<name>" group N`` or
        ``master add fadetime "<name>"`` (no ``initialLevel``: it starts at
        0, the programmed times)."""
        word = self.expect("speed", "size", "group", "fadetime")
        kind = "fadeTime" if word == "fadetime" else word
        name = self._name()
        if name is None:
            raise self.fail("expected a name in quotes")
        if any(m["name"].casefold() == name.casefold() for m in self.show["masters"]):
            raise ParseError(f"a master named {name!r} exists")
        value: dict[str, Any] = {"id": self.new_id("m", "masters"), "kind": kind, "name": name}
        if kind == "group":
            if not self.keyword("group"):
                raise self.fail("expected group N: the group the master scales")
            value["groupId"] = self.by_number("groups", self.integer("a group number"), "group")[
                "id"
            ]
        elif kind == "speed":
            options: dict[str, Any] = {}
            while (option := self.keyword("bpm", "steps")) is not None and option not in options:
                options[option] = (
                    self.number("a tempo") if option == "bpm" else self.numbers("a multiplier step")
                )
            if option is not None:  # given twice
                raise ParseError(f"unexpected {option!r}")
            value["defaultBpm"] = options.get("bpm", _DEFAULT_BPM)
            value["tap"] = True
            value["multiplierSteps"] = options.get("steps", list(_DEFAULT_STEPS))
        return self.submit({"type": "ADD", "path": ["masters"], "value": value})

    def _cmd_blackout(self) -> Action:
        return self.submit({"type": "BLACKOUT", "on": self.expect("on", "off") == "on"})

    def _cmd_tap(self) -> Action:
        return self.submit({"type": "TAP", "masterId": self.speed_master()})

    def _cmd_bpm(self) -> Action:
        master = self.speed_master()
        return self.submit({"type": "SET_BPM", "masterId": master, "bpm": self.number("a tempo")})

    def speed_master(self) -> str:
        """A quoted speed master name, or else the show's only speed master
        (masters have no numbers, phase-4-plan §5.13)."""
        token = self.peek()
        if token is not None and token.quoted:
            return self.named_master("speed")
        speeds = [m for m in self.show["masters"] if m["kind"] == "speed"]
        self.ending(*_quoted(m["name"] for m in speeds))
        if not speeds:
            raise ParseError("no speed master")
        if len(speeds) > 1:
            raise self.fail("several speed masters: name one")
        return speeds[0]["id"]

    def named_master(self, kind: str) -> str:
        """A master of ``kind``, named in quotes (any case)."""
        what = f"a {kind} master name in quotes"
        names = _quoted(m["name"] for m in self.show["masters"] if m["kind"] == kind)
        token = self.take(what, *names)
        if not token.quoted:
            raise ParseError(f"expected {what}")
        folded = token.text.casefold()
        named = next(
            (
                m
                for m in self.show["masters"]
                if m["kind"] == kind and m["name"].casefold() == folded
            ),
            None,
        )
        if named is None:
            raise ParseError(f"no {kind} master {token.text!r}")
        return named["id"]

    # panic and safety (Phase 7)

    def _release_all(self) -> dict[str, Any]:
        """``RELEASE_ALL``, with the time after ``all`` when there is one (a
        number: a binding's feedback may follow)."""
        command: dict[str, Any] = {"type": "RELEASE_ALL"}
        token = self.peek()
        if token is None:
            self.needs.append("a time in seconds")
        elif not token.quoted and _NUMBER.fullmatch(token.text):
            command["time"] = self.number("a time in seconds")
        return command

    def _cmd_output(self) -> Action:
        """``output on|off``; turning it off asks first at a prompt."""
        on = self.expect("on", "off") == "on"
        self.done()
        question = None if on else "Turn all DMX output off?"
        return Submit(cast(Command, {"type": "OUTPUT", "on": on}), confirm=question)

    def _cmd_park(self) -> Action:
        """``park <targets> <attribute> <value>``: one entry per target, in
        place of the one parked on that slot (new ones go at the end)."""
        start = self.k
        refs = self.target_refs()
        where = self.typed(start)
        definition = self.attribute()
        start = self.k
        value = self.value(definition, cast(list[TargetRef], refs))
        shown = self.typed(start)
        self.done()
        park = [cast(dict[str, Any], deep_copy(entry)) for entry in self.show["park"]]
        index = {_park_key(entry): k for k, entry in enumerate(park)}
        for ref in refs:
            entry = {"slot": {"target": ref, "attribute": definition.id}, "value": value}
            k = index.setdefault(_park_key(entry), len(park))
            if k == len(park):
                park.append(entry)
            else:
                park[k] = entry
        return Submit(_set_park(park, f"parked {where} {definition.id} at {shown}"))

    def _cmd_unpark(self) -> Action:
        """``unpark <targets> [<attribute>]`` or ``unpark all``."""
        park = self.show["park"]
        if self.keyword("all"):
            self.done()
            if not park:
                raise ParseError("nothing is parked")
            return Submit(_set_park([], f"unparked everything ({len(park)} parked)"))
        start = self.k
        refs = self.target_refs()
        attribute = None if self.ending(*ATTRIBUTES) else self.attribute().id
        where = self.typed(start)
        self.done()
        targets = {(ref["fixtureId"], ref["element"]) for ref in refs}
        kept = [
            cast(dict[str, Any], deep_copy(entry))
            for entry in park
            if (entry["slot"]["target"]["fixtureId"], entry["slot"]["target"]["element"])
            not in targets
            or attribute not in (None, entry["slot"]["attribute"])
        ]
        if len(kept) == len(park):
            raise ParseError(f"nothing parked on {where}")
        return Submit(_set_park(kept, f"unparked {where}"))

    def _limits(self) -> Action:
        """``fixture N [thru M] limits pan|tilt <min> <max>``, ``… limits
        intensity <max>`` or ``… limits none``, as one undo step: each
        fixture's ``limits`` set whole (``SET`` creates only the last key of
        a path), keeping the keys not named."""
        start = self.k
        fixtures = self.fixture_range()
        span = f"fixture {self.typed(start)}"
        self.expect("limits")
        what = self.expect("pan", "tilt", "intensity", "none")
        if what == "none":
            self.done()
            limited = [f for f in fixtures if "limits" in f]
            if not limited:
                raise ParseError(f"{span} has no limits")
            deletes = [{"type": "DELETE", "path": ["fixtures", {"id": f["id"]}, "limits"]}
                       for f in limited]  # fmt: skip
            return Submit(_labelled(f"removed the limits of {span}", *deletes))
        if what == "intensity":
            high = self.number("a maximum intensity, e.g. 0.5 or 50%")
            key, value, text = "intensityMax", cast(Any, high), f"intensity at most {high:g}"
        else:
            low = self.number(f"the lowest {what} in degrees")
            high = self.number(f"the highest {what} in degrees")
            if low > high:
                raise ParseError(f"min {low:g} above max {high:g}")
            key, value, text = what, [low, high], f"{what} {low:g}° to {high:g}°"
        self.done()
        sets = [
            {"type": "SET", "path": ["fixtures", {"id": f["id"]}, "limits"],
             "value": {**deep_copy(f.get("limits", {})), key: value}}
            for f in fixtures
        ]  # fmt: skip
        return Submit(_labelled(f"limited {span}: {text}", *sets))

    def _cmd_safety(self) -> Action:
        """``safety strobe <hz>`` sets the show's strobe-rate cap (decision 13);
        ``safety strobe off`` removes it."""
        self.expect("strobe")
        safety = dict(self.show.get("safety", {}))
        if self.keyword("off"):
            self.done()
            if "strobeMaxHz" not in safety:
                raise ParseError("no strobe cap is set")
            delete = {"type": "DELETE", "path": ["safety", "strobeMaxHz"]}
            return Submit(_labelled("removed the strobe cap", delete))
        hz = self.number("a rate in Hz, or off")
        self.done()
        command = {"type": "SET", "path": ["safety"], "value": {**safety, "strobeMaxHz": hz}}
        return Submit(_labelled(f"strobe cap {hz:g} Hz", command))

    def _cmd_profile(self) -> Action:
        """``profile update "<name>"`` (§5.20): the library's revision of a
        profile the show embeds, as one undo step. Each top-level key that
        differs is set (or deleted), so the profile keeps its place in the
        show, and each of its fixtures records the new revision."""
        self.expect("update")
        what = 'a profile name in quotes, e.g. "Generic Spot 16ch"'
        token = self.take(what, *_quoted(p["name"] for p in self.show["profiles"]))
        if not token.quoted:
            raise ParseError(f"expected {what}")
        self.done()
        name = token.text
        library = self.ctx.library.find(name)
        folded = name.casefold()
        embedded = next(
            (p for p in self.show["profiles"]
             if (library is not None and p["id"] == library["id"])
             or p["id"] == name or p["name"].casefold() == folded),
            None,
        )  # fmt: skip
        if embedded is None:
            raise ParseError(f"the show has no profile {name!r} (see 'list profiles')")
        if library is None or library["id"] != embedded["id"]:
            library = self.ctx.library.get(embedded["id"])
        if library is None:
            raise ParseError(f"no library profile named {name!r} (see 'library')")
        new, old = cast(dict[str, Any], library), cast(dict[str, Any], embedded)
        if new["revision"] == old["revision"]:
            raise ParseError(f"{old['name']!r} is already at the library's revision "
                             f"{new['revision']!r}")  # fmt: skip
        modes = {mode["id"] for mode in new["modes"]}
        users = [f for f in self.show["fixtures"] if f["profileId"] == old["id"]]
        for fixture in users:
            if fixture["modeId"] not in modes:
                mode = next((m["name"] for m in old["modes"] if m["id"] == fixture["modeId"]),
                            fixture["modeId"])  # fmt: skip
                raise ParseError(
                    f"fixture {fixture['number']} {fixture['name']!r} runs mode {mode!r}, "
                    f"which revision {new['revision']!r} of {old['name']!r} lacks"
                )
        path: EditPath = ["profiles", {"id": old["id"]}]
        commands: list[dict[str, Any]] = [
            {"type": "SET", "path": [*path, key], "value": deep_copy(value)}
            for key, value in new.items()
            if key != "id" and old.get(key) != value
        ]
        commands += [{"type": "DELETE", "path": [*path, key]} for key in old if key not in new]
        commands += [
            {"type": "SET", "path": ["fixtures", {"id": f["id"]}, "profileRevision"],
             "value": new["revision"]}
            for f in users
        ]  # fmt: skip
        label = (f"updated profile {old['name']!r} to revision {new['revision']!r} "
                 f"({len(users)} fixture{'' if len(users) == 1 else 's'})")  # fmt: skip
        return Submit(_labelled(label, *commands))

    # session

    def _cmd_undo(self) -> Action:
        return self.submit({"type": "UNDO"})

    def _cmd_redo(self) -> Action:
        return self.submit({"type": "REDO"})

    def _cmd_save(self) -> Action:
        token = self.peek()
        self.ending(need="a path")
        self.k = len(self.tokens)
        return Save(
            None if token is None else Path(self.line[token.start : self.end].strip().strip('"'))
        )

    def _cmd_source(self) -> Action:
        token = self.take("a file")
        self.done()
        return Source(Path(token.text))

    def _cmd_list(self) -> Action:
        kind = self.word(f"what to list ({', '.join(LIST_KINDS)})", *LIST_KINDS)
        if kind not in LIST_KINDS:
            raise ParseError(f"cannot list {kind!r}; try one of {', '.join(LIST_KINDS)}")
        if kind == "cues":
            number = self.integer("a cue list number")
            self.by_number("cueLists", number, "cue list")
            self.done()
            return Query("list", kind, number)
        self.done()
        return Query("list", kind)

    def _cmd_library(self) -> Action:
        self.done()
        return Query("library")

    def _cmd_info(self) -> Action:
        self.done()
        return Query("info")

    def _cmd_status(self) -> Action:
        self.done()
        return Query("status")

    def _cmd_help(self) -> Action:
        return Query("help")

    def _cmd_quit(self) -> Action:
        self.done()
        return Quit()

    _cmd_exit = _cmd_quit


# ------------------------------------------------------------------ defaults

LIST_KINDS: Final = (
    "fixtures", "groups", "presets", "cuelists", "cues", "playbacks", "pages",
    "masters", "universes", "routes", "surfaces", "bindings", "profiles", "effects", "park",
)  # fmt: skip

_COLLECTIONS: Final = {
    "fixture": ("fixtures", "fixture"),
    "group": ("groups", "group"),
    "cuelist": ("cueLists", "cue list"),
    "playback": ("playbacks", "playback"),
    "page": ("pages", "page"),
    "universe": ("universes", "universe"),
}
_ENTITIES: Final = frozenset({*_COLLECTIONS, "preset", "cue", "show"})

COMMANDS: Final = tuple(
    sorted({name.removeprefix("_cmd_") for name in vars(_Parser) if name.startswith("_cmd_")}
           | _ENTITIES)
)  # fmt: skip
"""The words a line can start with."""

_BARE: Final = re.compile(r'[^\s",#][^\s",]*')


def _numeric(text: str) -> float:
    """A number as typed: an ``int`` when written without a decimal point."""
    value = float(text)
    return int(value) if value.is_integer() and "." not in text else value


def _quoted(names: Iterable[str]) -> tuple[str, ...]:
    """Names as typed: in quotes, escaped as :func:`tokenize` reads them."""
    return tuple(json.dumps(name, ensure_ascii=False) for name in names)


def _word(name: str) -> str:
    """A name as typed: bare when it is one word, else in quotes."""
    return name if _BARE.fullmatch(name) else _quoted([name])[0]


def _element(items: Sequence[Any], path: EditPath) -> Mapping[str, Any]:
    """The element of ``items`` that an ``[collection, {"id": …}]`` path
    names (the parser built the path, so it exists)."""
    selector = cast(Mapping[str, Any], path[-1])
    return cast(Mapping[str, Any], next(item for item in items if item["id"] == selector["id"]))


def _port(text: str) -> int | None:
    """A UDP or TCP port, 1–65535, else ``None``."""
    return int(text) if text.isdigit() and 1 <= int(text) <= 65535 else None


def _address_text(address: Mapping[str, Any]) -> str:
    """An input address as the console writes it: ``cc 1 32``, ``osc "/x"``."""
    if address["kind"] == "midiCC":
        return f"cc {address['channel']} {address['cc']}"
    if address["kind"] == "midiNote":
        return f"note {address['channel']} {address['note']}"
    return f"osc {json.dumps(address['path'])}"


def _batch(*commands: Mapping[str, Any]) -> dict[str, Any]:
    """One undo step for several edits."""
    return {"type": "BATCH", "label": "", "commands": list(commands)}


def _labelled(label: str, *commands: Mapping[str, Any]) -> Command:
    """One undo step for ``commands``, reported as ``label``."""
    return cast(Command, {"type": "BATCH", "label": label, "commands": list(commands)})


def _set_park(park: list[dict[str, Any]], label: str) -> Command:
    """The whole park list, set in one labelled step (its entries have no ids)."""
    return _labelled(label, {"type": "SET", "path": ["park"], "value": park})


def _park_key(entry: Mapping[str, Any]) -> tuple[str, int, str]:
    """The slot a park entry parks: fixture, element, attribute."""
    slot = entry["slot"]
    return slot["target"]["fixtureId"], slot["target"]["element"], slot["attribute"]


def _same_cue(a: str, b: str) -> bool:
    return tuple(int(x) for x in a.split(".")) == tuple(int(x) for x in b.split("."))


def _record(kind: str, **fields: Any) -> dict[str, Any]:
    """A record command without its absent optional fields."""
    return {"type": kind, **{key: value for key, value in fields.items() if value is not None}}


def _cue_list(ident: str, number: int, name: str) -> dict[str, Any]:
    """A new cue list: ``sequence`` mode, no tracking, no wrap, no release at the end."""
    return {"id": ident, "name": name, "number": number, "mode": "sequence", "tracking": False,
            "wrap": False, "releaseAtEnd": False, "cues": []}  # fmt: skip


def _playback(
    ident: str, number: int, name: str, cue_list: str, fader: str = "master"
) -> dict[str, Any]:
    """A new playback: Appendix A's Blue playback without its exclusivity,
    with a ``fader`` of that kind."""
    return {
        "id": ident, "name": name, "number": number, "cueListId": cue_list, "priority": 50,
        "fader": fader, "buttons": ["toggle", "flash"], "ltpFaderMode": "threshold",
        "ltpThreshold": 0.02, "autoStart": True, "autoRelease": True,
        "flash": {"level": 1, "includeLtp": True}, "protectFromSwop": False, "releaseTime": 1,
    }  # fmt: skip


HELP: Final[Sequence[str]] = (
    (__doc__ or "").split("::", 1)[1].lstrip("\n").split("\n\n")[0].splitlines()
)
"""The grammar summary of the module docs, for the ``help`` command."""
