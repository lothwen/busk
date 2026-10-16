"""Entity ids for things the console creates (spec §5.1, phase-3-plan decision 12).

Every new entity gets an immutable opaque id of the form
``<prefix>-<12 hex chars>``, e.g. ``fx-3f9a0c71b2de``. The prefix says what
it is (``fx`` fixture, ``g`` group, ``pr`` preset, ``cl`` cue list, ``c``
cue, ``pb`` playback, ``u`` universe, ``r`` route, ``s`` surface, ``b``
binding, ``show`` show).

Ids come from an injectable factory: :class:`RandomIds` in production,
:class:`CounterIds` in tests, so a scripted build produces the same show
byte for byte. Both skip ids that are already taken.
"""

from __future__ import annotations

import secrets
from collections.abc import Container
from typing import Protocol


class IdFactory(Protocol):
    """Makes fresh entity ids."""

    def new(self, prefix: str, taken: Container[str] = ()) -> str:
        """A new id ``<prefix>-<12 hex chars>`` that is not in ``taken``."""
        ...


class RandomIds:
    """Random ids: 48 bits from :mod:`secrets` (collisions are retried)."""

    def new(self, prefix: str, taken: Container[str] = ()) -> str:
        while True:
            ident = f"{prefix}-{secrets.token_hex(6)}"
            if ident not in taken:
                return ident


class CounterIds:
    """Deterministic ids from one counter: ``fx-000000000001``, ``g-000000000002`` …"""

    def __init__(self, start: int = 1) -> None:
        self._next = start

    def new(self, prefix: str, taken: Container[str] = ()) -> str:
        while True:
            ident = f"{prefix}-{self._next:012x}"
            self._next += 1
            if ident not in taken:
                return ident
