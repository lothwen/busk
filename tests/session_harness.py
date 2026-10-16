"""A session wired to a real engine on a fake clock (Phase 3 tests).

Commands go through :meth:`Session.submit`; the engine applies installs and
performance commands at its next :meth:`tick`. Everything is single-threaded
and deterministic: counter ids and a fixed wall clock.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from builders import Doc, show_of
from busk.commands.types import Command
from busk.compiler.compile import compile_show
from busk.engine.clock import FakeClock
from busk.engine.loop import Engine
from busk.model.common import FixtureId, TargetRef
from busk.session.ids import CounterIds
from busk.session.session import CommandResult, Session

WALL = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)


class Live:
    """A session and its engine."""

    def __init__(self, doc: Doc) -> None:
        show = show_of(doc)
        compiled = compile_show(show)  # of the session's own show, as `busk run` does
        self.clock = FakeClock()
        self.engine = Engine(compiled, self.clock)
        self.session = Session(
            show,
            self.engine.bus,
            compiled=compiled,
            ids=CounterIds(),
            wall_clock=lambda: WALL,
            engine_state=lambda: self.engine.snapshot,
        )
        self.now = 0.0

    def do(self, *commands: dict[str, Any]) -> CommandResult:
        """Submit commands in order; every one must succeed. Returns the last result."""
        result = CommandResult(ok=True, message="")
        for command in commands:
            result = self.session.submit(cast(Command, command))
            assert result.ok, (command, result)
        return result

    def tick(self, dt: float = 0.01) -> NDArray[np.float64]:
        """Advance the clock by ``dt``, tick, and return the logical frame (a copy)."""
        self.now += dt
        self.clock.sleep_until(self.now)
        self.engine.tick(self.now)
        return self.engine.logical.copy()

    def lanes(self, fixture: str, attribute: str, element: int = 0) -> list[float]:
        """The current lanes of a slot after the last tick."""
        slot = self.engine.compiled.slots.find(
            TargetRef(fixtureId=FixtureId(fixture), element=element), attribute
        )
        assert slot is not None, (fixture, attribute)
        return [float(v) for v in self.engine.logical[slot.lanes]]

    def universe(self) -> bytes:
        latest = self.engine.latest
        assert latest is not None
        return latest.universes[0]


# ------------------------------------------------------------------ commands


def sel(*fixture_ids: str, mode: str = "replace") -> dict[str, Any]:
    refs = [{"fixtureId": f, "element": 0} for f in fixture_ids]
    return {"type": "SELECT", "targets": {"kind": "targets", "refs": refs}, "mode": mode}


def put(attribute: str, value: Any) -> dict[str, Any]:
    return {
        "type": "SET_ATTRIBUTE",
        "attribute": attribute,
        "value": {"kind": "literal", "value": value},
    }


def blind(on: bool) -> dict[str, Any]:
    return {"type": "BLIND", "on": on}


def fader(playback: str, level: float) -> dict[str, Any]:
    return {"type": "SET_FADER", "playbackId": playback, "level": level}


def trigger(playback: str) -> dict[str, Any]:
    return {"type": "TRIGGER_PLAYBACK", "playbackId": playback}


UNDO: dict[str, Any] = {"type": "UNDO"}
REDO: dict[str, Any] = {"type": "REDO"}
CLEAR: dict[str, Any] = {"type": "CLEAR_PROGRAMMER"}
