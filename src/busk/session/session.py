"""The session: the command bus of spec §15 and the single writer of editing state
(phase-3-plan §3 decisions 2–4, §5.6).

Every command enters through :meth:`Session.submit` (synchronous, returns a
:class:`CommandResult`) or :meth:`Session.post` (fire and forget, for input
threads). The session routes it by class
(:mod:`busk.commands.classes`):

* **performance** commands go straight onto the engine's queue
  (:meth:`CommandBus.submit <busk.commands.bus.CommandBus.submit>`). No lock
  is taken, so performance never waits for an edit;
* **programmer** commands, under the session lock: the handler returns a new
  :class:`~busk.session.programmer.Programmer`, a programmer frame is built
  and installed in the engine, and a step goes on the undo timeline (not
  for ``BLIND``, ``PROGRAMMER_FADE`` and ``HIGHLIGHT``: modes are never
  undone). A fade time installs nothing: the next frame carries it. While
  highlight is on, a selection change installs a frame too, since the
  highlight follows the selection;
* **show edits**, under the session lock: the handler's patch ops are
  applied copy-on-write to a candidate show, which is validated
  (:func:`~busk.model.validate.validate_edit`) and compiled; only then is it
  committed and installed in the engine, with a slot remap when the slot
  keys changed. Any error rejects the whole edit and nothing changes
  anywhere: **the session only ever holds a show that validates and
  compiles** (decision 4);
* ``UNDO`` / ``REDO`` walk the one timeline; a show step goes through the
  same validate → compile → install path.

**Ordering.** Installs and performance commands share the engine's FIFO
queue, and installs are queued while the lock is held, so the engine sees
edits in commit order and a programmer frame always arrives after the
compiled show it was built against. Right after queueing a compiled show the
session points the bus at it, so a command naming a new playback is
validated against the show that has it and queued behind the install.

**The event log** (Phase 7, phase-7-plan §5.21). With ``causes`` on, each
install carries its cause for the engine to record
(:mod:`busk.persistence.eventlog`): a show edit, undo or redo its forward
patch ops, a programmer command the command (``SELECT_PLAYBACK`` as the
``SELECT`` it resolved to), and a programmer undo, redo or recovery the
programmer it set. A programmer change that installs nothing (a selection,
a fade time) still matters to the commands after it: its cause waits for
the next install and goes before that install's own. Every install also
carries ``(show, programmer)`` as its ``source``, which a console's bus
keeps for the record of a reconnect.
``busk replay`` applies the ops with :meth:`Session.apply_ops`.

**Readers.** Other threads (the autosave worker, the console) read
:attr:`Session.snapshot`, an immutable :class:`SessionSnapshot` published by
one reference assignment after every change: they never take the lock.
"""

from __future__ import annotations

import logging
import queue
import secrets
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, cast

from busk.commands import edits, record
from busk.commands.bus import CommandBus, CommandRejected
from busk.commands.classes import command_class
from busk.commands.errors import CommandError
from busk.commands.patch import Op, apply
from busk.commands.types import Command, CommandOrigin
from busk.compiler.compile import CompiledShow, UnsupportedFeature, compile_show
from busk.engine.install import Install, Stamp
from busk.engine.snapshot import EngineSnapshot
from busk.model.show import Show
from busk.model.validate import Issue, validate_edit
from busk.persistence import eventlog
from busk.persistence.show_file import WallClock, iso_time, save_show, utc_now
from busk.session.frame import build_frame, slot_remap
from busk.session.ids import IdFactory, RandomIds
from busk.session.programmer import (
    EMPTY,
    Programmer,
    drop_invalid_effects,
    drop_missing,
    handle,
    playback_targets,
    to_json,
)
from busk.session.state import ShowState
from busk.session.timeline import ProgrammerStep, ShowStep, Timeline


@dataclass(frozen=True, kw_only=True)
class CommandResult:
    """The outcome of one command.

    ``message`` is one line for the operator (``recorded cue 10/1: 2
    entries``); ``issues`` are the errors when not ``ok`` and new warnings
    when ``ok``, with their paths.
    """

    ok: bool
    message: str
    issues: tuple[Issue, ...] = ()


@dataclass(frozen=True, kw_only=True)
class SessionSnapshot:
    """What lock-free readers see of the session; replaced, never mutated."""

    show: Show
    compiled: CompiledShow
    programmer: Programmer
    dirty: bool  # the show has edits that are not saved
    showVersion: int  # +1 per committed show change (edit, undo, redo, save)
    programmerVersion: int  # +1 per programmer change (blind included)
    saves: int  # +1 per successful save
    path: Path | None  # where `save` writes by default
    stamp: Stamp  # the stamp of `compiled`, the show the engine was last given (Phase 7)


type Report = Callable[[str], None]


_MODES: Final = frozenset({"BLIND", "PROGRAMMER_FADE", "HIGHLIGHT"})
"""Programmer commands that switch a mode: no undo step."""


_log = logging.getLogger("busk.session")


class Session:
    """The single writer of the show, the programmer and the undo timeline."""

    def __init__(
        self,
        show: Show,
        bus: CommandBus,
        *,
        compiled: CompiledShow | None = None,
        path: Path | None = None,
        ids: IdFactory | None = None,
        wall_clock: WallClock = utc_now,
        dirty: bool = False,
        report: Report = _log.warning,
        engine_state: Callable[[], EngineSnapshot | None] | None = None,
        stamp: Stamp | None = None,
        programmer: Programmer = EMPTY,
        causes: bool = False,
    ) -> None:
        """``show`` must be valid; ``compiled`` is its compiled form if the
        caller has it already. The bus's compiled show is replaced by this
        session's from now on.

        ``stamp`` is the stamp of ``show`` (phase-7-plan decision 8): a
        restarted console passes the one its recovered show had, so it can
        tell whether the engine still runs that show. By default it is
        ``(sessionId, 0)``. Each show the session installs is stamped
        ``(sessionId, n)``, with a session id of its own.

        ``engine_state`` reads the engine's latest snapshot (``busk run``
        passes ``lambda: engine.snapshot``): ``SELECT_PLAYBACK`` selects the
        targets of the playback's current cue from it. Without it, the first
        cue's targets are selected.

        ``programmer`` is the programmer the session starts with, installed
        nowhere (``busk replay``: the engine has its frame already).
        ``causes`` puts the event-log cause on every install (see the
        module docs).
        """
        self._lock = threading.Lock()
        self._bus = bus
        self._ids: IdFactory = RandomIds() if ids is None else ids
        self._wall_clock = wall_clock
        self._report = report
        self._engine_state = engine_state
        compiled = compile_show(show) if compiled is None else compiled
        self._state = ShowState(show=show, compiled=compiled)
        self._known = _warning_keys(self._state, validate_edit(show, show)[1])
        self._programmer = programmer
        self._causes = causes
        self._pending: list[bytes] = []  # causes of changes that installed nothing yet
        self._dirty = dirty
        self._path = path
        self._versions = [0, 0, 0]  # show, programmer, saves
        self._sessionId = secrets.token_hex(8)
        self._installs = 0  # shows installed: the n of the next stamp is one more
        self._stamp: Stamp = (self._sessionId, 0) if stamp is None else stamp
        self.timeline = Timeline()
        bus.compiled = compiled
        self._worker: threading.Thread | None = None
        self._posted: queue.SimpleQueue[tuple[Command, CommandOrigin] | None] = queue.SimpleQueue()
        self.snapshot: SessionSnapshot
        self._publish()

    # ----------------------------------------------------------- reading

    @property
    def show(self) -> Show:
        return self._state.show

    @property
    def compiled(self) -> CompiledShow:
        return self._state.compiled

    @property
    def state(self) -> ShowState:
        return self._state

    @property
    def programmer(self) -> Programmer:
        return self._programmer

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def ids(self) -> IdFactory:
        return self._ids

    # --------------------------------------------------------- commands

    def submit(self, command: Command, origin: CommandOrigin | None = None) -> CommandResult:
        """Carry out ``command`` and say how it went. Never raises."""
        kind = command_class(cast(Mapping[str, object], command))
        if kind == "performance":
            try:
                self._bus.submit(command, origin)
            except CommandRejected as exc:
                return CommandResult(ok=False, message=exc.reason)
            return CommandResult(ok=True, message="")
        if kind is None:
            return CommandResult(ok=False, message=f"unknown command type {command.get('type')!r}")
        with self._lock:
            try:
                if kind == "programmer":
                    return self._programmer_command(command)
                if kind == "show":
                    return self._show_command(command)
                return self._undo() if command["type"] == "UNDO" else self._redo()
            except CommandError as exc:
                return CommandResult(ok=False, message=exc.message, issues=exc.issues)
            except Exception as exc:  # a bug must not take the console down
                return CommandResult(
                    ok=False, message=f"internal error: {type(exc).__name__}: {exc}"
                )

    def post(self, command: Command, origin: CommandOrigin | None = None) -> None:
        """Submit from an input thread without waiting.

        Performance commands go straight to the engine queue (a rejection
        raises :class:`~busk.commands.bus.CommandRejected`, as the bus does).
        Every other command is handed to one worker thread that submits them
        in arrival order, so an input thread never blocks behind a long edit;
        failures are reported through ``report`` (by default a ``busk.session``
        warning; the CLI prints them on stderr).
        """
        if command_class(cast(Mapping[str, object], command)) == "performance":
            self._bus.submit(command, origin)
            return
        self.start()
        self._posted.put((command, CommandOrigin() if origin is None else origin))

    def start(self) -> None:
        """Start the worker thread of :meth:`post` (idempotent)."""
        with self._lock:
            if self._worker is None:
                self._worker = threading.Thread(target=self._work, name="busk-session", daemon=True)
                self._worker.start()

    def stop(self) -> None:
        """Finish the posted commands, then stop the worker."""
        worker = self._worker
        if worker is not None:
            self._posted.put(None)
            worker.join()
            self._worker = None

    def _work(self) -> None:
        while (item := self._posted.get()) is not None:
            command, origin = item
            result = self.submit(command, origin)
            if not result.ok:
                self._report(f"{command['type']}: {result.message}")

    # -------------------------------------------------------- programmer

    def engine_snapshot(self) -> EngineSnapshot | None:
        """The engine's latest snapshot, or ``None`` without an engine (or
        before its first tick)."""
        return None if self._engine_state is None else self._engine_state()

    def _programmer_command(self, command: Command) -> CommandResult:
        engine = self.engine_snapshot()
        change = handle(self._state, self._programmer, command, engine)
        cause = None
        if self._causes:
            logged: Mapping[str, object] = command
            if command["type"] == "SELECT_PLAYBACK":  # what it selected, not what it read
                targets = playback_targets(self._state, command["playbackId"], engine)
                logged = {
                    "type": "SELECT",
                    "targets": {"kind": "targets", "refs": [dict(t) for t in targets]},
                    "mode": command["mode"],
                }
            cause = eventlog.programmer_cause(logged)
        self._set_programmer(
            change.programmer,
            label=change.message,
            step=command["type"] not in _MODES,
            written=change.written,
            written_effects=change.writtenEffects,
            cause=cause,
        )
        return CommandResult(ok=True, message=change.message)

    def _set_programmer(
        self,
        new: Programmer,
        *,
        label: str,
        step: bool,
        written: frozenset[str] = frozenset(),
        written_effects: frozenset[str] = frozenset(),
        cause: bytes | None = None,
    ) -> None:
        """Install ``new`` in the engine and, for content changes, record a step.

        ``written`` slots and ``written_effects`` effect ids count as touched
        even if their value or instance did not change. ``cause`` is the
        install's event-log cause; ``None`` with causes on means the whole
        programmer is logged (an undo, redo or recovery).
        """
        old = self._programmer
        installs = bool(
            written
            or written_effects
            or dict(old.values) != dict(new.values)
            or old.effects != new.effects
            or old.blind != new.blind
            or old.highlight != new.highlight
            or (new.highlight and old.selection != new.selection)  # highlight follows it
        )
        if self._causes and (installs or old != new):
            if cause is None:  # an undo, redo or recovery: the whole programmer
                cause = eventlog.state_cause(label, to_json(new))
            self._pending.append(cause)
        if installs:
            frame = build_frame(
                self._state,
                new,
                old.values,
                previous_effects=old.effects,
                written=written,
                written_effects=written_effects,
                touch_all=old.blind and not new.blind,
            )
            self._bus.install(
                Install(
                    compiled=None,
                    remap=None,
                    programmer=frame,
                    causes=self._take_causes(),
                    source=(self._state.show, new),
                )
            )
        if step and not old.same_content(new):
            self.timeline.push(ProgrammerStep(before=old, after=new, label=label))
        self._programmer = new
        self._versions[1] += 1
        self._publish()

    def _take_causes(self) -> tuple[bytes, ...]:
        """The causes waiting for an install, now on one (the lock is held)."""
        causes, self._pending = tuple(self._pending), []
        return causes

    def restore_programmer(self, programmer: Programmer) -> list[str]:
        """Replace the programmer without an undo step (crash recovery).

        Selected targets that no longer exist are dropped, and so are effects
        that no longer validate against the show; returns one message per
        effect dropped.
        """
        with self._lock:
            restored, dropped = drop_invalid_effects(self._state, programmer)
            restored = replace(restored, selection=drop_missing(self._state, restored.selection))
            self._set_programmer(restored, label="recovered programmer", step=False)
            return dropped

    # ------------------------------------------------------------- show

    def _show_command(self, command: Command) -> CommandResult:
        if command["type"] == "BATCH":
            commands: Sequence[Command] = command["commands"]
            if not commands:
                raise CommandError("BATCH holds no commands")
        else:
            commands = [command]
        working = self._state.show
        forward: list[Op] = []
        inverse: list[Op] = []
        messages: list[str] = []
        warnings: list[Issue] = []
        for inner in commands:
            if (
                inner["type"] == "BATCH"
                or command_class(cast(Mapping[str, object], inner)) != "show"
            ):
                raise CommandError(f"a BATCH can only hold show edits, not {inner['type']}")
            edit = self._edit(working, inner)
            working, undo = apply(working, edit.ops)
            forward += edit.ops
            inverse[:0] = undo
            messages.append(edit.message)
            warnings += edit.warnings
        label = (
            command["label"]
            if command["type"] == "BATCH" and command["label"]
            else "; ".join(messages)
        )
        new_warnings = self._commit(working, label, forward)
        self.timeline.push(ShowStep(forward=tuple(forward), inverse=tuple(inverse), label=label))
        return CommandResult(ok=True, message=label, issues=(*warnings, *new_warnings))

    def _edit(self, show: Show, command: Command) -> edits.Edit:
        """One show-edit handler, against ``show`` (ahead of the committed one in a batch)."""
        state, programmer, ids = self._state, self._programmer, self._ids
        if command["type"] == "RECORD_CUE":
            return record.record_cue(state, show, programmer, command, ids)
        if command["type"] == "RECORD_PRESET":
            return record.record_preset(state, show, programmer, command, ids)
        if command["type"] == "RECORD_GROUP":
            return record.record_group(show, programmer, command, ids)
        if command["type"] == "PATCH_FIXTURE":
            return edits.patch_fixture(show, command)
        if command["type"] == "ASSIGN_PLAYBACK":
            return edits.assign_playback(show, command)
        if command["type"] == "ADD":
            return edits.add(show, command)
        if command["type"] == "SET":
            return edits.set_(show, command)
        if command["type"] == "DELETE":
            return edits.delete(show, command)
        raise CommandError(f"{command['type']} is not a show edit")

    def _commit(self, candidate: Show, label: str, ops: Sequence[Op]) -> list[Issue]:
        """Validate, compile, install and commit ``candidate``; return the
        warnings it introduced. Raises :class:`CommandError` (nothing changes)
        if it does not validate or compile. ``ops`` made it from the
        committed show: the install's event-log cause."""
        before = self._state
        show, issues = validate_edit(before.show, candidate)
        errors = [issue for issue in issues if issue.severity == "error"]
        if show is None or errors:
            raise CommandError(f"{label}: rejected, the show would not be valid", errors or issues)
        try:
            compiled = compile_show(show, previous=before.compiled)
        except UnsupportedFeature as exc:
            raise CommandError(f"{label}: rejected, {exc}") from None
        state = ShowState(show=show, compiled=compiled)
        remap = slot_remap(before.compiled.slots, compiled.slots)
        programmer = self._programmer
        frame = build_frame(  # unchanged sources: no touch
            state, programmer, programmer.values, previous_effects=programmer.effects
        )
        known = _warning_keys(state, issues)
        fresh = [w for w in (*issues, *compiled.warnings) if (w.path, w.message) not in self._known]
        self._installs += 1
        stamp = (self._sessionId, self._installs)
        # Nothing below can fail: once the engine has the install, the session commits.
        if self._causes:
            self._pending.append(eventlog.edit_cause(label, ops))
        self._bus.install(
            Install(
                compiled=compiled,
                remap=remap,
                programmer=frame,
                stamp=stamp,
                causes=self._take_causes(),
                source=(show, programmer),
            )
        )
        self._bus.compiled = compiled
        self._state, self._known, self._stamp = state, known, stamp
        self._dirty = True
        self._versions[0] += 1
        self._publish()
        return fresh

    def apply_ops(self, ops: Sequence[Op], label: str) -> CommandResult:
        """Apply patch ops to the show through the validate → compile →
        install path of an undo (``busk replay``: a logged edit). No undo
        step is recorded. Never raises."""
        with self._lock:
            try:
                candidate, _ = apply(self._state.show, ops)
                issues = self._commit(candidate, label, ops)
            except CommandError as exc:
                return CommandResult(ok=False, message=exc.message, issues=exc.issues)
            except Exception as exc:  # a bug must not take the caller down
                return CommandResult(
                    ok=False, message=f"internal error: {type(exc).__name__}: {exc}"
                )
            return CommandResult(ok=True, message=label, issues=tuple(issues))

    # -------------------------------------------------------- undo, redo

    def _undo(self) -> CommandResult:
        step = self.timeline.next_undo()
        if step is None:
            raise CommandError("nothing to undo")
        if isinstance(step, ShowStep):
            self._commit(
                apply(self._state.show, step.inverse)[0], f"undo {step.label}", step.inverse
            )
        else:
            self._restore(step.before, f"undo {step.label}")
        self.timeline.undone()
        return CommandResult(ok=True, message=f"undid: {step.label}")

    def _redo(self) -> CommandResult:
        step = self.timeline.next_redo()
        if step is None:
            raise CommandError("nothing to redo")
        if isinstance(step, ShowStep):
            self._commit(
                apply(self._state.show, step.forward)[0], f"redo {step.label}", step.forward
            )
        else:
            self._restore(step.after, f"redo {step.label}")
        self.timeline.redone()
        return CommandResult(ok=True, message=f"redid: {step.label}")

    def _restore(self, target: Programmer, label: str) -> None:
        """Restore a programmer step's selection and values; the modes (blind,
        the fade time, highlight) keep their state. Selected targets that no longer exist
        are dropped."""
        selection = drop_missing(self._state, target.selection)
        current = self._programmer
        restored = replace(
            target,
            selection=selection,
            blind=current.blind,
            fadeTime=current.fadeTime,
            highlight=current.highlight,
        )
        self._set_programmer(restored, label=label, step=False)

    # -------------------------------------------------------------- save

    def save(self, path: Path | None = None) -> CommandResult:
        """Write the show (default: where it was loaded from), backing up the
        file it replaces. Sets ``meta.modified``; not an undo step."""
        with self._lock:
            target = path if path is not None else self._path
            if target is None:
                return CommandResult(ok=False, message="no file to save to: give a path")
            now = self._wall_clock()
            show, _ = apply(self._state.show, [Op("replace", ("meta", "modified"), iso_time(now))])
            try:
                save_show(show, target, now=now)
            except (OSError, ValueError) as exc:
                return CommandResult(ok=False, message=f"cannot save {str(target)!r}: {exc}")
            self._state = ShowState(show=show, compiled=self._state.compiled)
            self._path = target
            self._dirty = False
            self._versions[0] += 1
            self._versions[2] += 1
            self._publish()
            return CommandResult(ok=True, message=f"saved {target}")

    # ----------------------------------------------------------- helpers

    def _publish(self) -> None:
        state = self._state
        self.snapshot = SessionSnapshot(
            show=state.show,
            compiled=state.compiled,
            programmer=self._programmer,
            dirty=self._dirty,
            showVersion=self._versions[0],
            programmerVersion=self._versions[1],
            saves=self._versions[2],
            path=self._path,
            stamp=self._stamp,
        )


def _warning_keys(state: ShowState, issues: Sequence[Issue]) -> set[tuple[str, str]]:
    """The warnings a committed show has, validation's and the compiler's."""
    return {
        (issue.path, issue.message)
        for issue in (*issues, *state.compiled.warnings)
        if issue.severity == "warning"
    }


class InputSink:
    """What input bindings submit to: :meth:`Session.post` behind the bus's
    ``submit(command, origin)`` signature, so a binding works the same with a
    bare bus (Phase 2) or a session (programmer and show-edit commands too)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def submit(self, command: Command, origin: CommandOrigin | None = None) -> None:
        self._session.post(command, origin)
