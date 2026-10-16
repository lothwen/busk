"""The command bus: validation, envelopes and the engine's queue (spec §15, §16).

Surfaces, the CLI and UIs never touch engine state. Performance commands go
to :meth:`CommandBus.submit` on the caller's thread; the engine thread drains
the queue at stage 1 of every tick (§4.2) and applies the commands in
arrival order, at the tick's time. Since Phase 3 the queue also carries the
session's :class:`~busk.engine.install.Install` items (live edits), in the same
FIFO order, so the engine sees edits and commands in the order they were
made.

Only the performance class reaches this queue. Programmer, show-edit and
session commands go to the session (:mod:`busk.session.session`), which
owns editing state; the bus rejects them.

**Validation happens at submit time**, on the caller's thread
(phase-2-plan decision 12), so the caller learns at once that a command is
wrong:

* the command type must be one the engine applies (:data:`ENGINE_COMMANDS`);
* the playback or master it names must exist in :attr:`CommandBus.compiled`.
  ``SET_FADER`` and ``PLAYBACK_BUTTON`` name exactly one of a
  ``playbackId`` and a ``slot`` (an integer ≥ 0) of the engine's current
  page, which the engine resolves; an empty slot is not an error, and
  neither is a ``button`` (an integer ≥ 0) beyond the playback's buttons.
  ``PAGE`` gives exactly one of a ``number``, which must name a page, and
  an integer ``delta`` (Phase 6);
  ``SET_MASTER`` must name a grand, group, size or speed master (fade-time
  masters are rejected as unassigned in the roadmap); ``TAP`` a speed master that
  takes taps, and ``SET_BPM`` a speed master; ``GOTO`` must name a cue of the
  playback's list;
* levels must be numbers and are clamped to ``0..1``; a release ``time``
  must be finite and ``≥ 0``; a tempo must be a number in
  ``0 < bpm ≤`` :data:`~busk.model.master.MAX_BPM`; ``FLASH`` and
  ``PLAYBACK_BUTTON`` need a boolean ``down``, and ``BLACKOUT`` a boolean
  ``on`` if it gives one (without it, a toggle);
* ``RELEASE_ALL`` takes an optional release ``time`` like
  ``RELEASE_PLAYBACK``'s, and ``OUTPUT`` needs a boolean ``on`` (Phase 7).

**Ids can change** since Phase 3. The session points :attr:`CommandBus.compiled`
at each newly committed show right after queueing its install, so a command
submitted after an edit is validated against the edited show and is queued
behind the install that brings it. A command validated just before an edit
may still name a playback the edit deleted; the engine guards every command,
counts that one as a command error and keeps ticking.

The queue is a :class:`queue.SimpleQueue`: unbounded, lock-free for the
engine to drain, and safe to submit to from any number of threads.
"""

from __future__ import annotations

import math
import queue
import threading
from collections.abc import Iterator, Mapping
from typing import Final, cast

from busk.commands.classes import command_class
from busk.commands.types import Command, CommandEnvelope, CommandOrigin
from busk.compiler.compile import CompiledShow
from busk.compiler.playbacks import CompiledMaster
from busk.engine.clock import Clock
from busk.engine.install import Install
from busk.engine.snapshot import Restore, Sync
from busk.model.common import MasterId, PlaybackId
from busk.model.master import MAX_BPM

type QueueItem = CommandEnvelope | Install | Restore | Sync
"""What the engine drains: commands, live edits, restores and sync markers."""

MAX_DRAIN: Final = 512
"""Queued items the engine applies per tick at most (phase-7-plan decision
19): a flood of commands is spread over ticks, in order, so no tick grows
without bound."""

ENGINE_COMMANDS: Final = frozenset(
    {
        "TRIGGER_PLAYBACK",
        "RELEASE_PLAYBACK",
        "TOGGLE_PLAYBACK",
        "FLASH",
        "GO",
        "BACK",
        "GOTO",
        "SET_FADER",
        "SET_MASTER",
        "TAP",
        "SET_BPM",
        "BLACKOUT",
        "PAGE",  # Phase 6
        "PLAYBACK_BUTTON",  # Phase 6
        "RELEASE_ALL",  # Phase 7
        "OUTPUT",  # Phase 7
    }
)
"""The command types the engine applies: the whole performance class."""

_PLAYBACK_COMMANDS: Final = frozenset(
    ENGINE_COMMANDS
    - {"SET_MASTER", "TAP", "SET_BPM", "BLACKOUT", "PAGE", "SET_FADER", "PLAYBACK_BUTTON"}
    - {"RELEASE_ALL", "OUTPUT"}
)
"""Command types that name a playback by ``playbackId`` only."""


class CommandRejected(Exception):
    """A command failed validation; ``reason`` says why, readable as is."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def unsupported_reason(command: Mapping[str, object], compiled: CompiledShow) -> str | None:
    """Why this build cannot carry out a command of this type, or ``None`` if it can.

    Programmer, show-edit and session commands are supported (by the
    session). Only the *type* is checked here, not the ids; the limitation
    report uses it for commands embedded in bindings. Every master kind
    works since Phase 6 (fade-time masters).
    """
    kind = command.get("type")
    if kind not in ENGINE_COMMANDS:
        if command_class(command) in ("programmer", "show", "session"):
            return None
        return f"unknown command type {kind!r}"
    return None


class CommandBus:
    """Validates commands, wraps them in envelopes and queues them for the engine."""

    def __init__(self, compiled: CompiledShow, clock: Clock) -> None:
        self.compiled = compiled
        """The compiled show commands are validated against: the last one the
        session committed (a plain reference, replaced atomically)."""
        self._clock = clock
        self._queue: queue.SimpleQueue[QueueItem] = queue.SimpleQueue()
        self._lock = threading.Lock()  # guards the id counter across submitting threads
        self._next_id = 1

    def submit(self, command: Command, origin: CommandOrigin | None = None) -> CommandEnvelope:
        """Validate ``command`` and queue it for the next engine tick.

        Returns the queued envelope; its command is a normalised copy (levels
        clamped), never the caller's dict. Raises :class:`CommandRejected`
        with a readable reason if the command fails validation.
        """
        checked = self.check(command)
        with self._lock:
            ident = str(self._next_id)
            self._next_id += 1
        envelope = CommandEnvelope(
            id=ident,
            issuedAt=self._clock.now(),
            origin=CommandOrigin() if origin is None else origin,
            command=checked,
        )
        self.enqueue(envelope)
        return envelope

    def enqueue(self, envelope: CommandEnvelope) -> None:
        """Deliver a validated, numbered envelope: :meth:`submit` ends here.
        The engine host also queues envelopes another process's bus made
        with it (phase-7-plan §5.2: the engine side never re-validates; it
        may still be one install behind the console). A console's
        :class:`~busk.process.links.RemoteBus` sends them over its link."""
        self._queue.put(envelope)

    def install(self, item: Install) -> None:
        """Queue a live edit for the engine, behind every command queued before it.

        Only the session installs, while it holds its lock, so installs are
        queued in commit order.
        """
        self._queue.put(item)

    def restore(self, item: Restore) -> None:
        """Queue a restore after an engine restart, behind everything queued
        before it: the console sends it after the first install (§5.7)."""
        self._queue.put(item)

    def mark(self, item: Sync) -> None:
        """Queue a sync marker behind everything queued before it (Phase 7)."""
        self._queue.put(item)

    def drain(self) -> Iterator[QueueItem]:
        """Yield queued envelopes, installs, restores and sync markers in arrival
        order until the queue is empty, or :data:`MAX_DRAIN` items have been yielded: the rest stay
        queued, in order, for the next tick.

        Only the engine thread drains.
        """
        for _ in range(MAX_DRAIN):
            try:
                yield self._queue.get_nowait()
            except queue.Empty:
                return

    def check(self, command: Command) -> Command:
        """The validation of :meth:`submit` (decision 12): return the normalised
        command or raise :class:`CommandRejected`."""
        if not isinstance(command, Mapping):
            raise CommandRejected(f"not a command: {command!r}")
        data = cast(Mapping[str, object], command)
        compiled = self.compiled  # one read: the session may replace it meanwhile
        reason = unsupported_reason(data, compiled)
        if reason is not None:
            raise CommandRejected(reason)
        kind = data["type"]
        if kind not in ENGINE_COMMANDS:
            raise CommandRejected(f"{kind} is not a performance command; submit it to the session")
        if kind in _PLAYBACK_COMMANDS:
            playback = data.get("playbackId")
            if playback not in compiled.playbacks:
                raise CommandRejected(f"unknown playback {playback!r}")
        if kind == "GOTO":
            cue_list = compiled.playbacks[cast(PlaybackId, data["playbackId"])].cueList
            number = data.get("cueNumber")
            if not isinstance(number, str) or cue_list.find(number) is None:
                raise CommandRejected(f"no cue {number} in cue list {cue_list.number}")
        if kind in ("SET_FADER", "PLAYBACK_BUTTON"):
            if _one_of(data, "playbackId", "slot") == "slot":
                _index(data, "slot")
            elif data["playbackId"] not in compiled.playbacks:
                raise CommandRejected(f"unknown playback {data['playbackId']!r}")
        if kind == "SET_FADER":
            return cast(Command, {**data, "level": _level(data)})
        if kind == "PLAYBACK_BUTTON":
            _index(data, "button")
        if kind == "PAGE":
            if _one_of(data, "number", "delta") == "delta":
                if not _is_int(data["delta"]):
                    raise CommandRejected(f"delta must be an integer, got {data['delta']!r}")
            elif all(page.number != data["number"] for page in compiled.pages):
                raise CommandRejected(f"no page {data['number']!r}")
        if kind == "SET_MASTER":
            _master(data, compiled)
            return cast(Command, {**data, "level": _level(data)})
        if kind == "TAP":
            master = _master(data, compiled, "speed")
            if not master.tap:
                raise CommandRejected(f"speed master {master.name!r} does not take taps")
        if kind == "SET_BPM":
            _master(data, compiled, "speed")
            bpm = data.get("bpm")
            if not _is_number(bpm) or not 0 < cast(float, bpm) <= MAX_BPM:
                raise CommandRejected(
                    f"bpm must be a number greater than 0 and at most {MAX_BPM:g}, got {bpm!r}"
                )
            return cast(Command, {**data, "bpm": float(cast(float, bpm))})
        if kind in ("RELEASE_PLAYBACK", "RELEASE_ALL") and "time" in data:
            time = data["time"]
            if not _is_number(time) or not 0 <= cast(float, time) < math.inf:
                raise CommandRejected(f"release time must be a finite number ≥ 0, got {time!r}")
        if kind in ("FLASH", "PLAYBACK_BUTTON", "OUTPUT") or (kind == "BLACKOUT" and "on" in data):
            flag = "on" if kind in ("BLACKOUT", "OUTPUT") else "down"
            if not isinstance(data.get(flag), bool):
                raise CommandRejected(f"{kind} needs a boolean {flag!r}, got {data.get(flag)!r}")
        return cast(Command, dict(data))  # a copy: the caller may reuse its dict


def _master(
    command: Mapping[str, object], compiled: CompiledShow, kind: str | None = None
) -> CompiledMaster:
    """The master ``command`` names, which must exist and be of ``kind`` if given."""
    ident = command.get("masterId")
    master = compiled.masters.get(cast(MasterId, ident))
    if master is None:
        raise CommandRejected(f"unknown master {ident!r}")
    if kind is not None and master.kind != kind:
        raise CommandRejected(
            f"{command['type']} needs a {kind} master; {ident!r} is {master.kind}"
        )
    return master


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _one_of(command: Mapping[str, object], first: str, second: str) -> str:
    """Which of ``first`` and ``second`` the command gives; exactly one must be given."""
    if (first in command) == (second in command):
        raise CommandRejected(f"{command['type']} needs exactly one of {first!r} and {second!r}")
    return first if first in command else second


def _index(command: Mapping[str, object], key: str) -> None:
    """``command[key]`` must be an integer ≥ 0 (a slot or a button)."""
    value = command.get(key)
    if not _is_int(value) or cast(int, value) < 0:
        raise CommandRejected(f"{key} must be an integer ≥ 0, got {value!r}")


def _level(command: Mapping[str, object]) -> float:
    """The command's ``level``, clamped to ``0..1``; ``NaN`` and non-numbers are rejected."""
    level = command.get("level")
    if not _is_number(level) or math.isnan(cast(float, level)):
        raise CommandRejected(f"level must be a number, got {level!r}")
    return min(max(float(cast(float, level)), 0.0), 1.0)
