"""The output driver protocol (spec §14.5).

A driver sends one show universe to one destination using one protocol
(sACN, Art-Net or DMX-USB). The output scheduler
(:mod:`busk.output.scheduler`) owns the drivers and calls them on its own
thread; the engine knows nothing about protocols.

Two deviations from §14.5 (phase-1.5-plan decision 6):

* the protocol is **synchronous**. Drivers run on the output thread, so
  ``open`` and ``close`` are plain methods, not coroutines. ``send`` must
  never block, and an ``OSError`` while sending is recorded in the status,
  never raised;
* ``send`` takes the universe as ``bytes``, which is what
  :class:`~busk.engine.loop.Frame` carries, and :class:`DriverStatus` holds
  packet and error counters instead of ``packetsPerSec``, which needs a
  time window and arrives with the UI (Phase 6).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal, Protocol

type ProtocolName = Literal["dmxUsb", "artnet", "sacn"]
"""The ``protocol`` tag of an output route (§5.16)."""

PROTOCOL_LABELS: Final[Mapping[ProtocolName, str]] = {
    "dmxUsb": "DMX-USB",
    "artnet": "Art-Net",
    "sacn": "sACN",
}
"""How messages name each protocol, as in ``sACN r1: …``."""


@dataclass(frozen=True, kw_only=True)
class DriverStatus:
    """A snapshot of a driver's health, safe to build on any thread."""

    ok: bool
    detail: str  # "" when ok; otherwise the last error
    packets: int  # packets sent successfully
    errors: int  # sends that failed
    dropped: int = 0  # frames skipped while the transport was still busy (DMX-USB)


@dataclass(frozen=True, kw_only=True)
class RouteNotice:
    """Something about the output that the CLI prints: a route of the show
    that is not sent and why, or an event of a protocol's network (such as
    Art-Net's taken port)."""

    text: str  # e.g. "sACN r2: disabled"
    failed: bool  # an error (printed to stderr), rather than a route disabled or ignored


class OutputDriver(Protocol):
    """Sends one universe over one transport."""

    @property
    def protocol(self) -> ProtocolName: ...

    def open(self) -> None:
        """Acquire the transport. A failure is recorded in :meth:`status`
        (``ok = False``), never raised."""
        ...

    def send(self, data: bytes, changed: bool, now: float) -> None:
        """Offer the universe's 512 bytes for output time ``now``.

        ``changed`` says whether they differ from the previous call's. The
        driver decides whether a packet is due (send-on-change, keep-alive).
        It never blocks and never raises ``OSError``: a failed send is
        counted in :meth:`status`.
        """
        ...

    def close(self) -> None:
        """Send the protocol's termination, if it has one, and release the
        transport. Idempotent; nothing is sent afterwards."""
        ...

    def status(self) -> DriverStatus: ...
