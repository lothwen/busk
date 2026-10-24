"""The console: run lines and scripts against a session (phase-3-plan §5.10).

:meth:`Console.execute` runs one line and returns the text to print as a
:class:`Reply`; :meth:`Console.run_script` runs a file and stops at the first
error. Command results print their one-line message, then any warnings with
their paths; errors print as ``error: …`` followed by the validator's issues,
each with its path, so deleting a fixture that is still in use lists every
place that uses it.

A ``quit`` line stops a script there, and its reply says so (``Reply.quit``,
GAP-18 of ``docs/dev/tui/engine-gaps.md``), as does that of a ``source``
that stops at one, for a frontend to end on. It also sets
:attr:`Console.quit_requested`, which ends ``busk run``'s loops.

:func:`interact` is the interactive loop of ``busk run`` on a terminal, with
``readline`` history, Tab completion and ``?`` (:mod:`busk.console.prompt`).
Ctrl+C clears a typed line. On an empty line it says how to quit, and a
second Ctrl+C in a row quits, so one stray press never stops the output.
``quit``, Ctrl+D or that second Ctrl+C asks whether to save unsaved edits,
and a line that needs confirmation (``output off``) asks first. Scripts and
piped input never ask.

**Ctrl+C never splits a command.** Python raises ``KeyboardInterrupt`` in the
main thread wherever it happens to be; inside an edit, between queueing the
engine's install and committing the session, it would leave the engine and
the session with different shows. So while a command runs, SIGINT is held
back: :attr:`Console.interrupted` records it, and the caller acts on it once
the command is done (the prompt drops it, a script stops, piped input ends
the run).

**Lines from several threads** (GAP-12 of ``docs/dev/tui/engine-gaps.md``).
A line other than a performance line runs whole under the console's line
lock, from its parse to its reply, so lines from different threads run as if
one after the other; a ``source`` script, and :meth:`Console.run_lines`, run
whole too. A performance line (a command of the performance class: ``go``,
``fader``, ``gm`` …) takes no lock: it is parsed against the session's
published state and goes straight to the engine's queue
(:mod:`busk.session.session`), so it never waits for another thread's edit,
save or script. To tell them apart, every line is parsed first with an id
factory of its own, as :meth:`Console.confirmation` parses; any other line is
parsed again under the lock, with the session's, so it uses up the ids a
single thread would. SIGINT can only be held back on the main thread, so
only the main thread's line or script acts on :attr:`Console.interrupted`.
"""

from __future__ import annotations

import contextlib
import json
import signal
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import FrameType
from typing import Any, Final, Literal, cast

from busk.commands.classes import command_class
from busk.console.parser import (
    HELP,
    Action,
    Context,
    Expected,
    Nothing,
    ParseError,
    Query,
    Quit,
    Save,
    Source,
    Submit,
    SubmitAll,
    expected,
    find_template,
    parse,
)
from busk.console.prompt import PROMPT, Editing, hints
from busk.engine.snapshot import EngineSnapshot
from busk.io.osc import feedback_target
from busk.model.common import TargetRef
from busk.model.effect import ColorLayer, EffectInstance, EffectLayer
from busk.model.entry import TargetSpec
from busk.model.show import Show
from busk.session.ids import RandomIds
from busk.session.library import EffectDefaults, EffectLibrary, ProfileLibrary, builtin_effects
from busk.session.programmer import split_slot_key
from busk.session.session import CommandResult, Session

MAX_DEPTH: Final = 8
"""How deeply ``source`` may nest (a script sourcing itself stops here)."""


@dataclass(frozen=True)
class Reply:
    """What a line printed, whether it succeeded, and whether it asked to
    quit (GAP-18 of ``docs/dev/tui/engine-gaps.md``).

    ``quit`` is true for a ``quit`` or ``exit`` line, and for a ``source``
    line whose script stopped at one (in a script it sources, too): the
    lines after which ``busk run``'s prompt ends the run. Only the line says
    so: the next line's reply is false again, so a frontend that asks before
    quitting, and is told no, carries on as before.
    """

    text: str
    ok: bool = True
    quit: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class EffectTemplateInfo:
    """One effect template that ``effect add`` takes, as a display lists it
    (GAP-15 of ``docs/dev/tui/engine-gaps.md``).

    ``name`` is the name ``effect add "<name>"`` takes for it. ``source`` is
    ``"show"`` for a template the show holds (in ``show["effects"]``, with
    ``id``), and ``"library"`` for one of the effect library's that the show
    has no copy of: ``effect add`` embeds it into the show first, and from
    then on it is the show's, with the same id. ``summary`` is its layers in
    one line, as ``list effects`` and ``library`` print them, text to show as
    it is.

    ``size``, ``low``, ``high`` and ``phase`` (start and end, in degrees)
    are the library's defaults for an instance, as ``library`` prints them,
    also once the show holds the template. ``None`` where the library has
    none, as for a template the show made itself (``effect template add``):
    then ``effect add`` gives size 1, no low or high, and phase 0 0. An
    option on the line overrides each.
    """

    name: str
    id: str
    source: Literal["show", "library"]
    summary: str  # "pan add sine, tilt add sine +90°"
    size: float | None
    low: float | None
    high: float | None
    phase: tuple[float, float] | None


class Console:
    """Runs console lines against one session."""

    def __init__(
        self,
        session: Session,
        library: ProfileLibrary,
        *,
        iface: str = "eth0",
        status: Callable[[], str] | None = None,
        effects: EffectLibrary | None = None,
        about: Callable[[], Sequence[str]] | None = None,
        settle: Callable[[], None] | None = None,
    ) -> None:
        """``iface`` is used by multicast and broadcast routes; ``status``
        returns the engine's status line for the ``status`` command;
        ``effects`` is the effect library (the built-in one by default);
        ``about`` returns the lines ``info`` adds about the run (its
        processes and restarts). ``settle`` is called after every line,
        in scripts and sourced files too, while SIGINT is still held back:
        :class:`~busk.runner.OfflineShow` ticks its engine there, so each
        line takes effect before the next one runs."""
        self.session = session
        self.library = library
        self.effects = effects if effects is not None else builtin_effects()
        self.iface = iface
        self._status = status
        self._about = about
        self._settle = settle
        self.quit_requested = False
        self.interrupted = False
        """Ctrl+C arrived while a command ran on the main thread (it was held
        back until it finished)."""
        self._depth = 0
        self._lock = threading.RLock()  # every line but a performance line (see the module docs)

    # ---------------------------------------------------------- running

    def execute(self, line: str) -> Reply:
        """Run one line; never raises, not even for Ctrl+C (see the module
        docs). Safe from any thread: a performance line never waits for
        another thread's line, and any other line waits for one that runs."""
        with self._interrupts_held():
            reply = self._execute(line)
            if self._settle is not None:
                self._settle()
            return reply

    @contextlib.contextmanager
    def _interrupts_held(self) -> Iterator[None]:
        """Record SIGINT in :attr:`interrupted` instead of raising, while the
        block runs. Only the main thread can set signal handlers; elsewhere
        nothing changes (and no SIGINT arrives there anyway)."""
        if threading.current_thread() is not threading.main_thread():
            yield
            return

        def held(signum: int, frame: FrameType | None) -> None:
            self.interrupted = True

        previous = signal.signal(signal.SIGINT, held)
        try:
            yield
        finally:
            signal.signal(signal.SIGINT, previous)

    def confirmation(self, line: str) -> str | None:
        """The yes/no question to ask before running ``line`` at a prompt
        (``Turn all DMX output off?``), or ``None``: also for a line that
        does not parse, whose error :meth:`execute` reports. Like
        :meth:`expected`, it changes nothing: ids come from a factory of its
        own, so asking first leaves the ids the line then gets as they were."""
        try:
            action = parse(line, replace(self._context(), ids=RandomIds()))
        except ParseError:
            return None
        return action.confirm if isinstance(action, Submit) else None

    def expected(self, line: str) -> Expected:
        """What may follow ``line`` at the prompt (Tab completion and ``?``)."""
        return expected(line, self._context())

    def effect_templates(self, show: Show) -> tuple[EffectTemplateInfo, ...]:
        """Every template ``effect add`` takes in ``show``, once, as it finds
        them by name (:func:`~busk.console.parser.find_template`): the show's
        in show order, then the effect library's that the show has no copy
        of. Each is listed under the first name that finds it; one that no
        name finds is left out (a show template named like an earlier one,
        a library template whose name a show template has)."""
        names = [t["name"] for t in show["effects"]] + [e.template["name"] for e in self.effects]
        found: dict[str, EffectTemplateInfo] = {}
        for name in names:
            resolved = find_template(show, self.effects, name)
            assert resolved is not None  # each name finds at least its own template
            template, defaults, embed = resolved
            if template["id"] in found:
                continue
            phase = defaults.get("phase")
            found[template["id"]] = EffectTemplateInfo(
                name=name,
                id=template["id"],
                source="library" if embed else "show",
                summary=_layers(template["layers"]),
                size=defaults.get("size"),
                low=defaults.get("low"),
                high=defaults.get("high"),
                phase=None if phase is None else (phase["start"], phase["end"]),
            )
        return tuple(found.values())

    def _context(self) -> Context:
        session = self.session
        snapshot = session.snapshot  # one read: the show and the programmer of one moment
        return Context(
            snapshot.show,
            self.library,
            session.ids,
            self.iface,
            effects=self.effects,
            programmer=snapshot.programmer,
            page=self._page(),
        )

    def _execute(self, line: str) -> Reply:
        try:
            action = parse(line, replace(self._context(), ids=RandomIds()))
        except ParseError as exc:
            return Reply(f"error: {exc.message}", ok=False)
        if isinstance(action, Nothing) or (
            isinstance(action, Submit)
            and command_class(cast(Mapping[str, object], action.command)) == "performance"
        ):
            return self._run(action)  # no lock: see the module docs
        with self._lock:
            try:  # again, now that no other line runs, and with the session's ids
                action = parse(line, self._context())
            except ParseError as exc:
                return Reply(f"error: {exc.message}", ok=False)
            return self._run(action)

    def _run(self, action: Action) -> Reply:
        session = self.session
        if isinstance(action, Nothing):
            return Reply("")
        if isinstance(action, Submit):
            result = session.submit(action.command)
            return _join(*action.notes, render_result(result), ok=result.ok)
        if isinstance(action, SubmitAll):
            texts = list(action.notes)
            for command in action.commands:
                result = session.submit(command)
                texts.append(render_result(result))
                if not result.ok:
                    return _join(*texts, ok=False)
            return _join(*texts, ok=True)
        if isinstance(action, Save):
            result = session.save(action.path)
            return Reply(render_result(result), ok=result.ok)
        if isinstance(action, Source):
            return self._source(action.path)
        if isinstance(action, Quit):
            self.quit_requested = True
            return Reply("", quit=True)
        return Reply(self._query(action))

    def run_script(self, path: Path, write: Callable[[str], None]) -> bool:
        """Run every line of ``path``, writing each non-empty reply; stop at the
        first error (after writing where it happened), or after a ``quit``
        line. Returns success."""
        return self._script(path, write)[0]

    def _script(self, path: Path, write: Callable[[str], None]) -> tuple[bool, bool]:
        """:meth:`run_script`'s success, and whether a ``quit`` line ended it."""
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            write(f"error: cannot read {str(path)!r}: {exc.strerror or exc}")
            return False, False
        return self._lines(path, lines, write, None)

    def run_lines(
        self,
        path: Path,
        lines: Sequence[str],
        write: Callable[[str], None],
        *,
        failed: Callable[[int, str], None] | None = None,
    ) -> bool:
        """Run ``lines``, read from ``path``, as :meth:`run_script` does.

        ``failed(number, line)`` is told which line failed (1-based, its
        text stripped) before the location line is written. Returns success.
        They run whole, as one line does: a line of another thread waits
        until they are done, unless it is a performance line. A line whose
        reply asks to quit ends them (a ``quit`` of an earlier line does not).
        """
        return self._lines(path, lines, write, failed)[0]

    def _lines(
        self,
        path: Path,
        lines: Sequence[str],
        write: Callable[[str], None],
        failed: Callable[[int, str], None] | None,
    ) -> tuple[bool, bool]:
        """:meth:`run_lines`'s success, and whether a ``quit`` line ended them."""
        main = threading.current_thread() is threading.main_thread()
        with self._lock:
            for number, line in enumerate(lines, start=1):
                reply = self.execute(line)
                if not reply.ok:
                    if failed is not None:
                        failed(number, line.strip())
                    write(f"{path}:{number}: {line.strip()}")
                if reply.text:
                    write(reply.text)
                if not reply.ok:
                    return False, False
                if main and self.interrupted:
                    write(f"{path}:{number}: interrupted")
                    return False, False
                if reply.quit:
                    return True, True
        return True, False

    def _source(self, path: Path) -> Reply:
        if self._depth >= MAX_DEPTH:
            return Reply(f"error: source nests more than {MAX_DEPTH} deep", ok=False)
        written: list[str] = []
        self._depth += 1
        try:
            ok, quit = self._script(path, written.append)
        finally:
            self._depth -= 1
        return Reply("\n".join(written), ok=ok, quit=quit)

    # ------------------------------------------------------------ queries

    def _query(self, query: Query) -> str:
        if query.kind == "programmer":
            return self._programmer()
        if query.kind == "list" and query.arg == "cues" and query.number is not None:
            return self._list_cues(query.number)
        if query.kind == "list":
            return self._list(query.arg)
        if query.kind == "library":
            return self._library()
        if query.kind == "info":
            return self._info()
        if query.kind == "status":
            return self._status() if self._status is not None else "no engine is running"
        return "\n".join(HELP)

    def target(self, target: TargetRef) -> str:
        """A target as the operator types it: ``101``, or ``301.3`` for an element."""
        fixture = next(
            (f for f in self.session.show["fixtures"] if f["id"] == target["fixtureId"]), None
        )
        if fixture is None:
            return f"{target['fixtureId']} (gone)"
        if self.session.state.elements.get(fixture["id"], 1) > 1:
            return f"{fixture['number']}.{target['element'] + 1}"
        return str(fixture["number"])

    def _programmer(self) -> str:
        programmer = self.session.programmer
        selection = ", ".join(self.target(t) for t in programmer.selection) or "nothing"
        lines = [
            f"selection: {selection}",
            f"blind: {'on' if programmer.blind else 'off'}",
            f"highlight: {'on' if programmer.highlight else 'off'}",
            f"fade: {programmer.fadeTime:g} s",
        ]
        for key, source in programmer.values.items():
            split = split_slot_key(key)
            if split is None:
                continue
            target, attribute = split
            if source["kind"] == "preset":
                shown = self._preset_name(source["presetId"])
            else:
                shown = format_value(source["value"])
            lines.append(f"  {self.target(target)} {attribute} = {shown}")
        for effect in programmer.effects:
            stopped = " (stopped)" if effect["id"] in programmer.stopped else ""
            lines.append(f"  effect {self._effect(effect)}{stopped}")
        return "\n".join(lines)

    def _effect(self, effect: EffectInstance) -> str:
        """An effect instance in one line: ``fx1 'Circle' on group 1, bpm
        'Speed 1' ×0.5, size 15``."""
        show = self.session.show
        template = next((t for t in show["effects"] if t["id"] == effect["templateId"]), None)
        name = repr(template["name"]) if template is not None else f"{effect['templateId']} (gone)"
        rate = effect["rate"]
        if rate["kind"] == "hz":
            speed = f"{rate['value']:g} Hz"
        else:
            master = next((m for m in show["masters"] if m["id"] == rate["masterId"]), None)
            label = repr(master["name"]) if master is not None else f"{rate['masterId']} (gone)"
            speed = f"bpm {label} ×{rate['multiplier']:g}"
        targets = self._targets(effect["targets"])
        return f"{effect['id']} {name} on {targets}, {speed}, size {effect['size']:g}"

    def _targets(self, spec: TargetSpec) -> str:
        """A target spec as the operator types it: ``group 1`` or ``101, 102``."""
        if spec["kind"] == "group":
            group = next(
                (g for g in self.session.show["groups"] if g["id"] == spec["groupId"]), None
            )
            return f"group {group['number']}" if group is not None else f"{spec['groupId']} (gone)"
        return ", ".join(self.target(target) for target in spec["refs"]) or "nothing"

    def _preset_name(self, ident: str) -> str:
        preset = next((p for p in self.session.show["presets"] if p["id"] == ident), None)
        if preset is None:
            return f"preset {ident} (gone)"
        return f"preset {preset['pool']} {preset['number']} {preset['name']!r}"

    def _list(self, kind: str) -> str:
        lines = getattr(self, f"_list_{kind}")(self.session.show)
        return "\n".join(lines) or ("nothing is parked" if kind == "park" else f"no {kind}")

    def _list_park(self, show: Show) -> list[str]:
        """Each parked slot as ``park`` takes it: ``204 intensity 0``."""
        return [
            f"{self.target(entry['slot']['target'])} {entry['slot']['attribute']} "
            f"{format_value(entry['value'])}"
            for entry in show["park"]
        ]

    def _list_fixtures(self, show: Show) -> list[str]:
        universes = {u["id"]: u["number"] for u in show["universes"]}
        profiles = {p["id"]: p for p in show["profiles"]}
        lines = []
        for fixture in sorted(show["fixtures"], key=lambda f: f["number"]):
            profile = profiles[fixture["profileId"]]
            mode = next(m["name"] for m in profile["modes"] if m["id"] == fixture["modeId"])
            patch = fixture["patch"]
            where = "unpatched"
            if patch is not None:
                where = f"{universes[patch['universeId']]}.{patch['address']}"
            name = fixture["name"]
            lines.append(f"{fixture['number']:>5}  {name:<20} {profile['name']} / {mode}  {where}")
        return lines

    def _list_groups(self, show: Show) -> list[str]:
        return [
            f"{group['number']:>5}  {group['name']:<20} "
            + ", ".join(self.target(member) for member in group["members"])
            for group in sorted(show["groups"], key=lambda g: g["number"])
        ]

    def _list_presets(self, show: Show) -> list[str]:
        return [
            f"{preset['pool']:>9} {preset['number']:<4} {preset['name']:<20} "
            f"{_count(len(preset['values']), 'value')}"
            for preset in sorted(show["presets"], key=lambda p: (p["pool"], p["number"]))
        ]

    def _list_cuelists(self, show: Show) -> list[str]:
        lines = []
        for cue_list in sorted(show["cueLists"], key=lambda cl: cl["number"]):
            cues = ", ".join(f"{c['number']} {c['name']!r}" for c in cue_list["cues"])
            lines.append(f"{cue_list['number']:>5}  {cue_list['name']:<20} {cues or 'no cues'}")
        return lines

    def _list_cues(self, number: int) -> str:
        """``list cues L``: each cue's number, name, timing and trigger, in the
        console's own syntax (``time 3/1 delay 0/2 easeIn, color 3  follow 0``)."""
        lists = self.session.show["cueLists"]
        cue_list = next((cl for cl in lists if cl["number"] == number), None)
        if cue_list is None:  # deleted since the line was parsed, by a command of another thread
            return f"no cue list {number}"
        lines = [
            f"{cue['number']:>5}  {cue['name']:<20} {_timing(cue['timing'])}  "
            f"{_trigger(cue['trigger'])}"
            + (f"  {_count(len(cue['effects']), 'effect')}" if cue["effects"] else "")
            for cue in cue_list["cues"]
        ]
        return "\n".join(lines) or "no cues"

    def _list_masters(self, show: Show) -> list[str]:
        """Each master's kind and level, and a speed master's tempo: the
        engine's when it runs, else the show's initial values."""
        compiled = self.session.state.compiled
        snapshot = self.session.engine_snapshot()
        levels = dict(snapshot.masterLevels) if snapshot is not None else {}
        tempos = {s.id: s for s in snapshot.speed} if snapshot is not None else {}
        lines = []
        for master in show["masters"]:
            ident = master["id"]
            known = compiled.masters.get(ident)
            if known is None:  # deleted since `show` was read, by a command of another thread
                continue
            level = levels.get(ident, known.initialLevel)
            line = f"{master['name']:<20} {master['kind']:<6} {level:>5.0%}"
            if master["kind"] == "speed":
                bpm = tempos[ident].bpm if ident in tempos else known.defaultBpm
                multiplier = known.multiplier(level)
                line += f"  {round(bpm, 1):g} BPM ×{multiplier:g}"
            lines.append(line)
        return lines

    def _list_playbacks(self, show: Show) -> list[str]:
        lists = {cue_list["id"]: cue_list["number"] for cue_list in show["cueLists"]}
        lines = []
        for playback in sorted(show["playbacks"], key=lambda p: p["number"]):
            extra = f", exclusivity {playback['exclusivity']}" if "exclusivity" in playback else ""
            lines.append(
                f"{playback['number']:>5}  {playback['name']:<20} "
                f"cue list {lists.get(playback['cueListId'], '?')}, band {playback['priority']}, "
                f"{playback['fader']} fader{extra}"
            )
        return lines

    def _page(self) -> str | None:
        """The id of the engine's current page (``None`` without an engine)."""
        snapshot = self.session.engine_snapshot()
        return None if snapshot is None or snapshot.page is None else snapshot.page.id

    def _list_pages(self, show: Show) -> list[str]:
        """Each page's slots, ``*`` marking the current page: the engine's,
        else the first, where the engine starts."""
        numbers = {playback["id"]: playback["number"] for playback in show["playbacks"]}
        pages = sorted(show["pages"], key=lambda p: p["number"])
        current = self._page()
        if all(page["id"] != current for page in pages):
            current = pages[0]["id"] if pages else None
        lines = []
        for page in pages:
            slots = " ".join(
                f"{k + 1}:{'-' if slot is None else numbers.get(slot, '?')}"
                for k, slot in enumerate(page["slots"])
            )
            mark = "*" if page["id"] == current else " "
            lines.append(f"{mark}{page['number']:>4}  {page['name']:<20} {slots or 'empty'}")
        return lines

    def _list_universes(self, show: Show) -> list[str]:
        return [
            f"{u['number']:>5}  {u['name']}"
            for u in sorted(show["universes"], key=lambda u: u["number"])
        ]

    def _list_routes(self, show: Show) -> list[str]:
        universes = {u["id"]: u["number"] for u in show["universes"]}
        return [
            f"{route['id']}  U{universes[route['universeId']]} → {_route(route)}"
            for route in show["output"]["routes"]
        ]

    def _list_surfaces(self, show: Show) -> list[str]:
        """Each surface's kind, its device or port, and its fader pickup."""
        return [f"{s['id']}  {s['kind']} {s['name']!r}{_surface(s)}" for s in show["surfaces"]]

    def _list_bindings(self, show: Show) -> list[str]:
        """Each binding's input and action, masters, pages and playbacks by
        name, and its feedback in brackets (its address only when it is not
        the input's)."""
        surfaces = {surface["id"]: surface["name"] for surface in show["surfaces"]}
        names: dict[str, Mapping[Any, Any]] = {
            "masterId": {master["id"]: master["name"] for master in show["masters"]},
            "number": {page["number"]: page["name"] for page in show["pages"]},
            "playbackId": {p["id"]: (p["number"], p["name"]) for p in show["playbacks"]},
        }
        lines = []
        for binding in show["bindings"]:
            line = (
                f"{binding['id']}  {surfaces.get(binding['surfaceId'], '?')} "
                f"{_input(binding['input'])} → {_action(binding['action'], names)}"
            )
            feedback = binding.get("feedback")
            if feedback is not None:
                kind = "motor" if feedback["kind"] == "motorFader" else feedback["kind"]
                own = feedback["address"] == binding["input"]
                line += f" [{kind}]" if own else f" [{kind} {_input(feedback['address'])}]"
            lines.append(line)
        return lines

    def _list_effects(self, show: Show) -> list[str]:
        """The show's effect templates and their layers."""
        return [f"{t['name']:<20} {_layers(t['layers'])}" for t in show["effects"]]

    def _list_profiles(self, show: Show) -> list[str]:
        """Each embedded profile, its category, its revision (``→ <revision>
        in the library`` when the library has another one: ``profile
        update`` takes it) and its modes."""
        lines = []
        for profile in show["profiles"]:
            revision = profile["revision"]
            library = self.library.get(profile["id"])
            if library is not None and library["revision"] != revision:
                revision += f" → {library['revision']} in the library"
            category = f"{profile['category']}, " if "category" in profile else ""
            modes = ", ".join(mode["name"] for mode in profile["modes"])
            lines.append(f"{profile['name']} ({category}revision {revision}): {modes}")
        return lines

    def _library(self) -> str:
        lines = [
            f"{p['name']} ({p['manufacturer']}, revision {p['revision']}): "
            + ", ".join(m["name"] for m in p["modes"])
            for p in self.library
        ]
        lines += [f"skipped {problem}" for problem in self.library.problems]
        lines += [
            f"effect {e.template['name']}: {_layers(e.template['layers'])}{_defaults(e.defaults)}"
            for e in self.effects
        ]
        lines += [f"skipped {problem}" for problem in self.effects.problems]
        return "\n".join(lines) or "the library is empty"

    def _info(self) -> str:
        snapshot = self.session.snapshot
        show = snapshot.show
        counts = ", ".join(
            _count(len(show[key]), word)  # type: ignore[literal-required]
            for key, word in (
                ("universes", "universe"), ("fixtures", "fixture"), ("groups", "group"),
                ("presets", "preset"), ("cueLists", "cue list"), ("playbacks", "playback"),
                ("bindings", "binding"),
            )
        )  # fmt: skip
        timeline = self.session.timeline
        programmer = snapshot.programmer
        where = str(snapshot.path) if snapshot.path is not None else "no file"
        return "\n".join(
            [
                f"show: {show['meta']['title']} ({show['meta']['id']})",
                f"file: {where}, {'unsaved edits' if snapshot.dirty else 'saved'}",
                counts,
                f"undo: {_count(timeline.undo_count, 'step')}, "
                f"redo: {_count(timeline.redo_count, 'step')}",
                f"programmer: {len(programmer.selection)} selected, "
                f"{_count(len(programmer.values), 'value')}, "
                f"blind {'on' if programmer.blind else 'off'}",
                *(self._about() if self._about is not None else ()),
            ]
        )


# ------------------------------------------------------------------ formatting


def render_result(result: CommandResult) -> str:
    """A command result as console text."""
    if result.ok:
        lines = [result.message] if result.message else []
        lines += [f"{issue.severity} {issue}" for issue in result.issues]
        return "\n".join(lines)
    return "\n".join([f"error: {result.message}", *(f"  {issue}" for issue in result.issues)])


def format_value(value: Any) -> str:
    """An attribute value as the console writes it."""
    if isinstance(value, dict):
        if "slot" in value:
            return str(value["slot"])
        parts = [f"{value[c]:g}" for c in ("r", "g", "b")]
        parts += [f"{c} {value[c]:g}" for c in ("w", "a", "uv") if c in value]
        return " ".join(parts)
    return f"{value:g}" if isinstance(value, int | float) else json.dumps(value)


def _layers(layers: Iterable[EffectLayer]) -> str:
    """Effect layers in one line: ``pan add sine, tilt add sine +90°``."""
    parts = []
    for layer in layers:
        if "palette" in layer:
            colour = cast(ColorLayer, layer)
            parts.append(f"color {colour['blend']} {_count(len(colour['palette']), 'colour')}")
            continue
        offset = layer["phaseOffset"]
        shift = f" {offset:+g}°" if offset else ""
        parts.append(f"{layer['attribute']} {layer['mode']} {layer['waveform']['kind']}{shift}")
    return ", ".join(parts)


def _defaults(defaults: EffectDefaults) -> str:
    """A library template's console defaults: `` (size 20)``, or nothing."""
    parts = []
    if "size" in defaults:
        parts.append(f"size {defaults['size']:g}")
    bounds = [(k, v) for k, v in (("low", defaults.get("low")), ("high", defaults.get("high")))]
    if any(v is not None for _, v in bounds):
        parts.append(" ".join(f"{k} {v:g}" for k, v in bounds if v is not None))
    if "phase" in defaults:
        parts.append(f"phase {defaults['phase']['start']:g} {defaults['phase']['end']:g}")
    return f" ({', '.join(parts)})" if parts else ""


def _join(*parts: str, ok: bool) -> Reply:
    return Reply("\n".join(part for part in parts if part), ok=ok)


def _count(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _route(route: Mapping[str, Any]) -> str:
    state = "" if route["enabled"] else " (disabled)"
    if route["protocol"] == "dmxUsb":
        device = route["device"]
        return f"DMX-USB {device['driver']} {device['port']} {route['refreshHz']:g} Hz{state}"
    destination = route["destination"]
    where = destination.get("host") or destination.get("iface")
    if route["protocol"] == "sacn":
        what = f"sACN {route['universe']}"
    elif route["protocol"] == "artnet":
        address = route["portAddress"]
        what = f"Art-Net {address['net']}.{address['subNet']}.{address['universe']}"
    else:
        what = route["protocol"]
    return f"{what} {destination['kind']} {where}{state}"


def _surface(surface: Mapping[str, Any]) -> str:
    """`` device '…'`` or `` port N``, then the pickup (not for a web
    remote, whose faders move relative to the level)."""
    match = surface["match"]
    kind = surface["kind"]
    text = ""
    if "deviceName" in match:
        text = f" device {match['deviceName']!r}"
    elif "port" in match:
        text = f" port {match['port']}"
    if kind == "osc":
        text += f", feedback to {feedback_target(match)}"
    if kind == "web":
        return text + (f" on {match['host']}" if "host" in match else "")
    return f"{text}, {surface['faderPickup']} pickup"


def _input(address: Mapping[str, Any]) -> str:
    kind = address["kind"]
    if kind == "midiCC":
        return f"cc {address['channel']} {address['cc']}"
    if kind == "midiNote":
        return f"note {address['channel']} {address['note']}"
    if kind == "osc":
        return f"osc {json.dumps(address['path'])}"
    if kind == "midiClock":
        return "clock"
    return " ".join(str(v) for v in address.values())


def _timing(timing: Mapping[str, Any]) -> str:
    """A cue's timing as ``cue L/C time`` takes it, per-family timing after commas."""
    words = [f"time {_pair(timing['fadeIn'], timing['fadeOut'])}"]
    if timing["delayIn"] or timing["delayOut"]:
        words.append(f"delay {_pair(timing['delayIn'], timing['delayOut'])}")
    if timing["curve"] != "linear":
        words.append(_curve(timing["curve"]))
    text = " ".join(words)
    for family, own in timing.get("perFamily", {}).items():
        text += f", {family} {own['fade']:g}"
        if own["delay"]:
            text += f" delay {own['delay']:g}"
        if "curve" in own:
            text += f" {_curve(own['curve'])}"
    return text


def _pair(first: float, second: float) -> str:
    """``3`` for equal values, else ``3/1``."""
    return f"{first:g}" if first == second else f"{first:g}/{second:g}"


def _curve(curve: str | Mapping[str, Any]) -> str:
    if isinstance(curve, str):
        return curve
    return "bezier " + " ".join(f"{value:g}" for value in curve["bezier"])


def _trigger(trigger: Mapping[str, Any]) -> str:
    """``go``, ``wait 8`` or ``follow 0``."""
    return trigger["kind"] if trigger["kind"] == "go" else f"{trigger['kind']} {trigger['delay']:g}"


def _action(action: Mapping[str, Any], names: Mapping[str, Mapping[Any, Any]]) -> str:
    """An action as ``bind`` takes it, with the names of the master, page or
    playback it drives (``names``: id or page number → name, by field)."""
    kind = action["kind"]
    if kind == "playbackFader":
        return f"fader {action['slot'] + 1}"
    if kind == "playbackButton":
        return f"button {action['slot'] + 1} {action['button'] + 1}"
    if kind == "command":
        return f"command {action['command']['type']}"
    if kind in ("master", "tap"):
        return f"{kind} {names['masterId'].get(action['masterId'], action['masterId'])!r}"
    if kind == "page":
        return f"page {action['delta']:+d}"
    if kind == "pageAbs":
        name = names["number"].get(action["number"])
        return f"page {action['number']}" + ("" if name is None else f" {name!r}")
    if kind == "playbackFaderAbs":
        number, name = names["playbackId"].get(action["playbackId"], ("?", "?"))
        return f"fader playback {number} {name!r}"
    if kind == "blackout":
        return "blackout momentary" if action.get("momentary") else "blackout"
    return " ".join(str(v) for v in action.values())


_LEVEL_SHOWN: Final = frozenset({"master", "size", "temp"})
"""The fader functions whose level the status line shows."""


def status_line(snapshot: EngineSnapshot) -> str:
    """One line for the engine's state, e.g.
    ``GM 80% | BO off | P1 Main | Speed 1 128 BPM ×2 | Fade 2.5 s | 9 Song on 3 Pre 1.00``.

    ``OUT off`` follows while ``OUTPUT`` has turned DMX output off (Phase
    7). The current page shows its number and name (Phase 6). Each speed master
    shows its tempo and multiplier, and the fade-time override its time
    while a fade-time master is up (Phase 6). Every playback that is
    not idle, is flashing or has a ``master``, ``size`` or ``temp`` fader up
    is listed: its number and name, ``on`` (active) or ``rel`` (releasing),
    the current cue (number and name) of a sequence of several cues, while
    a ``crossfade`` fader drives a transition ``→`` before that cue and the
    progress after it (``18 Manual on → 2 Verse 50%``; Phase 6),
    ``swop`` while a swop button is held (Phase 6), else ``flash``, and
    that fader's level when above 0. A chase shows no step, a
    ``rate`` fader no level (0.5 is its resting state) and an effect no phase,
    so a running chase or effect does not print a line per step or tick
    (phase-4-plan §5.11, phase-5-plan §5.13).
    """
    parts = [f"GM {snapshot.grandMaster:.0%}", f"BO {'on' if snapshot.blackout else 'off'}"]
    if not snapshot.outputEnabled:
        parts.append("OUT off")
    if snapshot.page is not None:
        parts.append(f"P{snapshot.page.number} {snapshot.page.name}")
    if snapshot.speed:
        parts.append(
            " · ".join(
                f"{speed.name} {round(speed.bpm, 1):g} BPM ×{speed.multiplier:g}"
                for speed in snapshot.speed
            )
        )
    if snapshot.fadeTime is not None:
        parts.append(f"Fade {round(snapshot.fadeTime, 1):g} s")
    shown = []
    for playback in snapshot.playbacks:
        level = playback.faderLevel if playback.fader in _LEVEL_SHOWN else 0.0
        if playback.state == "idle" and not playback.flash and level == 0.0:
            continue
        words = [str(playback.number), playback.name]
        if playback.state != "idle":
            words.append("on" if playback.state == "active" else "rel")
            if not playback.chase and playback.cueCount > 1 and playback.cue is not None:
                if playback.progress is not None:
                    words.append("→")
                words.append(playback.cue)
                if playback.cueName:
                    words.append(playback.cueName)
            if playback.progress is not None:
                words.append(f"{playback.progress:.0%}")
        if playback.swop:  # a swop holds the flash up
            words.append("swop")
        elif playback.flash:
            words.append("flash")
        if level > 0.0:
            words.append(f"{level:.2f}")
        shown.append(" ".join(words))
    if shown:
        parts.append(" · ".join(shown))
    return " | ".join(parts)


# --------------------------------------------------------------- interactive


def interact(
    console: Console, ask: Callable[[str], str] = input, write: Callable[[str], None] = print
) -> None:
    """The interactive loop on a terminal, until ``quit``, Ctrl+D or Ctrl+C twice.

    Ctrl+C clears a typed line. On an empty line it says how to quit, and a
    second Ctrl+C in a row quits: one stray press never stops the show. At
    the end, with unsaved edits, it asks whether to save first.
    """
    editing = Editing(console)
    armed = False  # Ctrl+C came on an empty line: the next one quits
    while not console.quit_requested:
        try:
            with editing:
                line = ask(PROMPT)
        except KeyboardInterrupt:
            write("")  # a new, empty prompt: the output keeps running
            if editing.typed().strip():  # it cleared the line
                armed = False
            elif not armed:
                write("press Ctrl+C again to quit")
                armed = True
            else:
                console.quit_requested = True
                break
            continue
        except EOFError:
            write("")
            console.quit_requested = True
            break
        armed = False
        if editing.asks(line):  # where ? is not a key
            if lines := hints(console, line.rstrip()[:-1]):
                write("\n".join(lines))
            continue
        question = console.confirmation(line)
        if question is not None and not _confirmed(question, ask, write):
            continue
        reply = console.execute(line)
        if reply.text:
            write(reply.text)
        console.interrupted = False  # a Ctrl+C while the line ran: dropped, it has run
    if console.session.dirty:
        _offer_save(console, ask, write)


def _confirmed(question: str, ask: Callable[[str], str], write: Callable[[str], None]) -> bool:
    """Ask ``question`` with ``[y/N]``: only ``y`` or ``yes`` confirms;
    anything else (Ctrl+C and Ctrl+D too) cancels the line."""
    try:
        answer = ask(f"{question} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        write("")
        answer = ""
    if answer in ("y", "yes"):
        return True
    write("cancelled")
    return False


def _offer_save(console: Console, ask: Callable[[str], str], write: Callable[[str], None]) -> None:
    where = console.session.path
    question = (
        f"save unsaved edits to {where}? [y/n] "
        if where
        else "unsaved edits: save to (path, or empty to skip)? "
    )
    while True:
        try:
            answer = ask(question).strip()
        except (EOFError, KeyboardInterrupt):
            write("")
            return
        if where is None:
            if answer:
                write(render_result(console.session.save(Path(answer))))
            return
        if answer.lower() in ("y", "yes"):
            write(render_result(console.session.save()))
            return
        if answer.lower() in ("n", "no"):
            return


def lines_of(texts: Iterable[str]) -> list[str]:
    """Split replies into lines (for tests and transcripts)."""
    return [line for text in texts for line in text.splitlines()]
