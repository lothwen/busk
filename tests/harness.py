"""The deterministic engine harness (§20): a fake clock and a scripted command list.

A script is a list of ``(time, command)`` pairs. :meth:`Harness.run` ticks the
engine at every requested time *and* every script time, in order; before the
tick at time ``t`` it submits the script's commands due at ``t`` (or
earlier), so each command is applied at exactly its scripted time, whatever
the tick schedule. After each tick it records an :class:`Observation`.

The command helpers (:func:`fader`, :func:`toggle`, …) build the command
dicts the bus accepts.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from busk.commands.types import Command
from busk.compiler.compile import CompiledShow
from busk.engine.clock import FakeClock
from busk.engine.loop import Engine, Frame
from busk.engine.snapshot import EngineSnapshot

type Script = Sequence[tuple[float, Command]]


@dataclass(frozen=True, kw_only=True)
class Observation:
    """What the engine published at one tick."""

    time: float
    logical: NDArray[np.float64]  # a copy of the logical frame, after masters
    frame: Frame
    snapshot: EngineSnapshot | None

    @property
    def universe(self) -> bytes:
        """The first universe's 512 bytes."""
        return self.frame.universes[0]

    def channels(self, *numbers: int) -> tuple[int, ...]:
        """The values of 1-based channels of the first universe."""
        return tuple(self.universe[number - 1] for number in numbers)


class Harness:
    """An engine on a fake clock, driven by scripted commands."""

    def __init__(self, compiled: CompiledShow, base: NDArray[np.float64] | None = None) -> None:
        self.compiled = compiled
        self.clock = FakeClock()
        self.engine = Engine(compiled, self.clock, base)

    def submit(self, *commands: Command) -> None:
        for command in commands:
            self.engine.bus.submit(command)

    def tick(self, now: float) -> Observation:
        """Move the clock to ``now`` (never backwards), tick and observe."""
        self.clock.sleep_until(now)
        self.engine.tick(now)
        assert self.engine.latest is not None
        return Observation(
            time=now,
            logical=self.engine.logical.copy(),
            frame=self.engine.latest,
            snapshot=self.engine.snapshot,
        )

    def run(self, script: Script, ticks: Iterable[float] = ()) -> dict[float, Observation]:
        """Tick at ``ticks`` and at the script's times, applying each command at its
        time; return the observation of every tick, by time."""
        pending = sorted(script, key=lambda item: item[0])  # stable: same-time order kept
        observations: dict[float, Observation] = {}
        k = 0
        for now in sorted({*ticks, *(t for t, _ in pending)}):
            while k < len(pending) and pending[k][0] <= now:
                self.submit(pending[k][1])
                k += 1
            observations[now] = self.tick(now)
        return observations


# ---------------------------------------------------------------- commands


def _command(**fields: Any) -> Command:
    return cast(Command, fields)


def trigger(playback: str) -> Command:
    return _command(type="TRIGGER_PLAYBACK", playbackId=playback)


def release(playback: str, time: float | None = None) -> Command:
    if time is None:
        return _command(type="RELEASE_PLAYBACK", playbackId=playback)
    return _command(type="RELEASE_PLAYBACK", playbackId=playback, time=time)


def toggle(playback: str) -> Command:
    return _command(type="TOGGLE_PLAYBACK", playbackId=playback)


def go(playback: str) -> Command:
    return _command(type="GO", playbackId=playback)


def flash(playback: str, down: bool) -> Command:
    return _command(type="FLASH", playbackId=playback, down=down)


def fader(playback: str, level: float) -> Command:
    return _command(type="SET_FADER", playbackId=playback, level=level)


def master(master_id: str, level: float) -> Command:
    return _command(type="SET_MASTER", masterId=master_id, level=level)


def blackout(on: bool) -> Command:
    return _command(type="BLACKOUT", on=on)


def back(playback: str) -> Command:
    return _command(type="BACK", playbackId=playback)


def goto(playback: str, number: str) -> Command:
    return _command(type="GOTO", playbackId=playback, cueNumber=number)


def tap(master_id: str) -> Command:
    return _command(type="TAP", masterId=master_id)


def set_bpm(master_id: str, bpm: float) -> Command:
    return _command(type="SET_BPM", masterId=master_id, bpm=bpm)
