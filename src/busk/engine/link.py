"""How the console side reads and writes the engine (phase-7-plan §5.5).

Everything that talks to the engine from outside its thread (the session,
the feedback worker, the web link, the binding resolver, autosave, the
status line) goes through an :class:`EngineLink`: the bus's compiled show,
the published snapshot and statistics, ``submit`` and ``install``.

* :class:`LocalEngine`: an :class:`~busk.engine.loop.Engine` in this
  process and its bus (:class:`~busk.runner.LiveShow`, ``busk run
  --threads``).
* :class:`~busk.process.links.RemoteBus`: the console process's bus,
  writing to the engine process over a socket (``busk run``).

Both live here, below :mod:`busk.runner` and :mod:`busk.process`, so the
runner and the CLI share one :class:`LocalEngine` (phase-8-plan step 10).
"""

from __future__ import annotations

import time
from typing import Final, Protocol

from busk.commands.bus import CommandBus
from busk.commands.types import Command, CommandEnvelope, CommandOrigin
from busk.compiler.compile import CompiledShow
from busk.engine.install import Install
from busk.engine.loop import Engine, EngineStats
from busk.engine.snapshot import EngineSnapshot, Sync

_SYNC_POLL_S: Final = 0.002
"""How often :meth:`LocalEngine.sync` looks at the engine."""


class EngineLink(Protocol):
    """What the console side reads of the engine and writes to it."""

    compiled: CompiledShow
    """The bus's show: the session points it at each new one."""

    @property
    def bus(self) -> CommandBus:
        """The bus the session submits to and installs through."""
        ...

    @property
    def snapshot(self) -> EngineSnapshot | None:
        """The engine's latest published snapshot."""
        ...

    @property
    def stats(self) -> EngineStats:
        """The engine's latest statistics."""
        ...

    def submit(self, command: Command, origin: CommandOrigin | None = None) -> CommandEnvelope:
        """Validate ``command`` and send it to the engine."""
        ...

    def install(self, item: Install) -> None:
        """Send a live edit to the engine."""
        ...

    def sync(self, timeout: float) -> bool:
        """Wait until the engine has applied everything sent so far and
        :attr:`snapshot` shows it; ``False`` if that took longer than
        ``timeout`` seconds (or no engine is attached in time)."""
        ...


class LocalEngine:
    """An :class:`EngineLink` to an engine in this process (``LiveShow``,
    ``busk run --threads``)."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._token = 0

    @property
    def bus(self) -> CommandBus:
        return self.engine.bus

    @property
    def compiled(self) -> CompiledShow:
        return self.engine.bus.compiled

    @compiled.setter
    def compiled(self, compiled: CompiledShow) -> None:
        self.engine.bus.compiled = compiled

    @property
    def snapshot(self) -> EngineSnapshot | None:
        return self.engine.snapshot

    @property
    def stats(self) -> EngineStats:
        return self.engine.stats

    def submit(self, command: Command, origin: CommandOrigin | None = None) -> CommandEnvelope:
        return self.engine.bus.submit(command, origin)

    def install(self, item: Install) -> None:
        self.engine.bus.install(item)

    def sync(self, timeout: float) -> bool:
        self._token += 1
        token = self._token
        self.engine.bus.mark(Sync(token=token))
        deadline = time.monotonic() + timeout
        while self.engine.synced < token:  # set by the engine thread, after the snapshot
            if time.monotonic() >= deadline:
                return False
            time.sleep(_SYNC_POLL_S)
        return True
