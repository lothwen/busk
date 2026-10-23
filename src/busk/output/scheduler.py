"""The output scheduler: the output thread of spec §14 and §16.

One thread runs at :data:`OUTPUT_HZ`, the DMX512 refresh ceiling, with the
same drop-don't-spiral timing as the engine loop. Each cycle:

1. reads ``engine.latest`` once. Before the first frame there is nothing to
   do;
2. marks each universe as *changed* if its bytes differ from the previous
   cycle's frame. Everything is changed on the first frame, and nothing is
   when the frame is the same object;
3. services Art-Net discovery (:meth:`~busk.output.artnet.ArtNetNetwork.service`:
   ArtPolls, replies, the node table), so broadcast routes send to the nodes
   known this cycle; what it reports goes to :attr:`OutputScheduler.notices`.
   sACN universe discovery (:class:`~busk.output.sacn.UniverseDiscovery`)
   follows the sends;
4. offers every route its universe's row with that flag. The driver decides
   whether a packet is due (send-on-change and keep-alive: see
   :class:`~busk.output.sacn.SendPolicy`). A failed DMX-USB route reopens
   its device here (:class:`~busk.output.dmxusb.EnttecSender`);
5. reconnects routes (below);
6. services the console sink (``busk run --console``), if there is one.

**Reconnects** (phase-7-plan decision 17, §5.15). Every route reconnects,
whatever made it fail:

* a route that failed to *open* (an interface not up yet, a serial device
  not plugged in; not one that is disabled or ignored) is tried again every
  :data:`REOPEN_S`. Its notice was printed once, at the first failure; when
  it opens, its route line is printed again, ending in ``(sending)``;
* a route whose status has been failing for :data:`FAIL_S` is closed and
  reopened, then again every :data:`REOPEN_S` while it keeps failing. Each
  driver's ``open`` resolves its interface index, host and broadcast
  address again, so a USB network adapter plugged back in with another
  index is found. Every universe is offered as changed after a reopen, so
  the reopened route sends at once. DMX-USB routes are left alone: their
  driver reopens its device itself.

Sequence numbers continue across reopens (and engine restarts): they live in
the shared :class:`~busk.output.sacn.Sequences` and
:class:`~busk.output.artnet.ArtNetNetwork`. Nothing is reopened while output
is off. Health is read every :data:`HEALTH_S`, not every cycle: a status is
a small object built on each call.

**Isolation** (spec §18). Each driver call is wrapped in its own
``try/except``. A driver bug is counted as a fault on its route, and the
other routes and the console keep running. Network errors never reach this
far: drivers record them in their status.

**Stalls** (phase-7-plan decision 14). The scheduler notes when each new
frame arrives. After :data:`STALL_S` without one, it keeps offering the last
frame, either as it is (``holdLastFrameOnEngineStall: true``, the default:
the look holds on stage) or with every intensity byte at its value for
intensity 0 (the frame's :class:`~busk.compiler.compile.OutputLayout` dark
bytes), so the stage goes dark while heads stay where they are. Either way
it is offered as unchanged after the first stalled cycle, so the routes send
keep-alives. Both the stall and the next new frame are reported on
:attr:`OutputScheduler.notices`.

**Output off** (decision 15). While a frame says ``outputEnabled: false``
(the engine's ``OUTPUT`` state), no route sends. sACN routes are closed when
it goes off, so receivers see Stream_Terminated and let go at once, and are
opened again when it comes back, with continuing sequence numbers; Art-Net
nodes and DMX-USB widgets hold their last frame by themselves. Turning
output on sends every universe at once.

**Shutdown.** The CLI (or the root, Phase 7) stops the engine first, then stops this
thread. :meth:`OutputScheduler.run` makes one last pass, so the final frame
goes out, and then closes every driver: sACN routes send Stream_Terminated.

**Live edits** (Phase 3). Each :class:`~busk.engine.loop.Frame` carries the
:class:`~busk.compiler.compile.OutputLayout` of the compiled show it was made
with (Phase 7: a frame from the engine process has no compiled show). When
that changes, the scheduler reconciles its routes before sending: routes
are compared by id and value (and by the show's sACN CID and source name);
a removed or changed route is closed, so an sACN route sends
Stream_Terminated, and a new or changed one is opened.
Art-Net routes share one :class:`~busk.output.artnet.ArtNetNetwork` (one
socket and the sequence numbers) for the whole run, as sACN routes share one
:class:`~busk.output.sacn.Sequences`.
Universe rows are matched by universe id, never by position: adding universe
1 after universe 2 reorders the rows. What changed is reported on
:attr:`OutputScheduler.notices` for the CLI to print.

**Route status** (GAP-07 of ``docs/dev/tui/engine-gaps.md``). Whenever the
routes change (opened, closed, reconciled, or a route that is not open
fails again with another error), the output thread publishes them by
reference assignment: the layout it follows, the open routes, and why each
other route is not sent (:func:`open_route`'s notice says it). Any thread
then reads :meth:`OutputScheduler.route_status`, which adds each open
driver's status (``status`` is safe on any thread).
"""

from __future__ import annotations

import dataclasses
import math
import queue
import threading
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import numpy as np

from busk.compiler.compile import CompiledUniverse, OutputLayout
from busk.engine.clock import Clock, FixedRateSchedule
from busk.engine.loop import Frame
from busk.model.output import OutputRoute, OutputSettings
from busk.output.artnet import ArtNetNetwork, ArtNetSender
from busk.output.console import ConsoleOutput, FrameSource
from busk.output.dmxusb import DEVICES, UNSUPPORTED, EnttecSender
from busk.output.driver import (
    PROTOCOL_LABELS,
    OutputDriver,
    RouteNotice,
    RouteState,
    RouteStatus,
)
from busk.output.sacn import SacnSender, Sequences, UniverseDiscovery

OUTPUT_HZ: Final = 44.0
"""Output cycles per second: at most one packet per route per cycle."""

STALL_S: Final = 1.0
"""Seconds without a new frame after which the engine counts as stalled."""

REOPEN_S: Final = 2.0
"""Seconds between two attempts to open a route that is not open, or to
reopen one that keeps failing (decision 17)."""

FAIL_S: Final = 1.0
"""Seconds a route's status must have been failing before it is reopened."""

HEALTH_S: Final = 0.1
"""Seconds between two reads of the routes' status, for :data:`FAIL_S`."""


@dataclass(kw_only=True)
class OutputStats:
    """Counters kept by the output thread (phase-7-plan §5.13). Read them
    once :meth:`OutputScheduler.run` has returned."""

    cycles: int = 0
    lateCycles: int = 0  # cycles that started more than one period after their deadline
    longestGap: float = 0.0  # the longest time between the starts of two cycles, seconds
    framesHeld: int = 0  # stalled cycles that offered the last frame as it is
    framesDarkened: int = 0  # stalled cycles that offered it with intensity off


@dataclass(kw_only=True)
class ScheduledRoute:
    """An open route, as the output scheduler services it."""

    id: str
    row: int  # universe row in Frame.universes and CompiledShow.universes
    driver: OutputDriver
    description: str  # e.g. "U1 Stage → universe 1, multicast 239.255.0.1 via eth0, …"
    faults: int = 0  # exceptions raised by the driver; counted on the output thread
    key: Any = None  # what the route was opened from (route, CID, source name); None in tests
    reopenAt: float | None = None  # while its status fails: when the scheduler reopens it

    @property
    def label(self) -> str:
        """How messages name the route, e.g. ``sACN r1``."""
        return f"{PROTOCOL_LABELS[self.driver.protocol]} {self.id}"


def build_routes(
    settings: OutputSettings,
    universes: Sequence[CompiledUniverse],
    sequences: Sequences | None = None,
    *,
    artnet: ArtNetNetwork | None = None,
) -> tuple[list[ScheduledRoute], list[RouteNotice]]:
    """Create and open a driver for every enabled route of a validated show.

    ``universes`` is ``CompiledShow.universes``: a route's row is its show
    universe's index there. Every sACN route shares one
    :class:`~busk.output.sacn.Sequences`, so routes that send the same sACN
    universe share its sequence numbers; every Art-Net route shares one
    :class:`~busk.output.artnet.ArtNetNetwork`. Pass the same two objects
    to the :class:`OutputScheduler`.

    Returns the routes that opened, in show order, and a notice for every
    other route: disabled, ignored (a DMX-USB interface this protocol does
    not drive) or failed to open, followed by the Art-Net network's notices.
    A route that failed to open is tried again by the :class:`OutputScheduler`
    given the show's layout (Phase 7).
    """
    if sequences is None:
        sequences = Sequences()
    if artnet is None:
        artnet = ArtNetNetwork()
    artnet.name = settings["sacnSourceName"]  # what its ArtPollReplies say
    routes: list[ScheduledRoute] = []
    notices: list[RouteNotice] = []
    for route in settings["routes"]:
        opened = open_route(route, settings, universes, sequences, artnet)
        if isinstance(opened, RouteNotice):
            notices.append(opened)
        else:
            routes.append(opened)
    notices += _network_notices(artnet)
    return routes, notices


def open_route(
    route: OutputRoute,
    settings: OutputSettings,
    universes: Sequence[CompiledUniverse],
    sequences: Sequences,
    artnet: ArtNetNetwork,
) -> ScheduledRoute | RouteNotice:
    """Open one route of :func:`build_routes`, or say why it is not sent
    (the notice's ``route`` and ``detail`` say it too)."""
    name = PROTOCOL_LABELS[route["protocol"]]
    ident = route["id"]
    label = f"{name} {ident}"
    if not route["enabled"]:
        return RouteNotice(text=f"{label}: disabled", failed=False, route=ident)
    sender: SacnSender | ArtNetSender | EnttecSender
    if route["protocol"] == "sacn":
        cid = uuid.UUID(settings["sacnCid"]).bytes
        sender = SacnSender(
            route, cid=cid, sourceName=settings["sacnSourceName"], sequences=sequences
        )
    elif route["protocol"] == "artnet":
        sender = ArtNetSender(route, network=artnet)
    else:
        driver = route["device"]["driver"]
        if driver not in DEVICES:
            reason = UNSUPPORTED.get(
                driver, f"unknown interface driver {driver!r}; use enttecPro or dmxking"
            )
            text = f"{label}: ignored ({reason})"
            return RouteNotice(text=text, failed=False, route=ident, detail=reason)
        sender = EnttecSender(route)
    sender.open()
    status = sender.status()
    if not status.ok:
        text = f"{label}: cannot open: {status.detail}"
        return RouteNotice(text=text, failed=True, route=ident, detail=status.detail)
    row = _rows(universes)[route["universeId"]]
    universe = universes[row]
    return ScheduledRoute(
        id=route["id"],
        row=row,
        driver=sender,
        description=f"U{universe.number} {universe.name} → {sender.description}",
        key=_route_key(route, settings),
    )


def _retried(route: OutputRoute) -> bool:
    """Whether a route that is not open is tried again: one that failed to
    open, rather than one that is disabled or ignored (see :func:`open_route`)."""
    if not route["enabled"]:
        return False
    return route["protocol"] != "dmxUsb" or route["device"]["driver"] in DEVICES


type _Unsent = tuple[RouteState, str]
"""Why a route of the show is not sent: its state and detail in :class:`RouteStatus`."""

type _Table = tuple[OutputLayout, tuple[ScheduledRoute, ...], Mapping[str, _Unsent]]
"""What :meth:`OutputScheduler.route_status` reads, published whole: the
layout the routes follow, the open routes, and why each other route is not sent."""


def _unsent(route: OutputRoute, notice: RouteNotice | None) -> _Unsent:
    """Why ``route``, which is not open, is not sent. ``notice`` is what
    :func:`open_route` said about it (``None``: the scheduler was not told,
    so the detail is empty)."""
    if not route["enabled"]:
        return ("disabled", "")
    detail = "" if notice is None else notice.detail
    return ("failed" if _retried(route) else "ignored", detail)


def _network_notices(artnet: ArtNetNetwork) -> list[RouteNotice]:
    """Take the Art-Net network's notices (a taken port, nodes)."""
    notices, artnet.notices = artnet.notices, []
    return notices


def _route_key(route: OutputRoute, settings: OutputSettings) -> Any:
    """What a route is opened from: it is reopened when any of it changes."""
    return (route, settings["sacnCid"], settings["sacnSourceName"])


def _rows(universes: Sequence[CompiledUniverse]) -> dict[str, int]:
    return {universe.id: row for row, universe in enumerate(universes)}


def _darkened(frame: Frame, layout: OutputLayout) -> Frame:
    """``frame`` with its layout's dark bytes set: intensity off, everything
    else held (decision 14)."""
    images = np.frombuffer(b"".join(frame.universes), dtype=np.uint8).copy()
    images[layout.darkPositions] = layout.darkValues
    size = len(frame.universes[0]) if frame.universes else 0
    rows = tuple(images[k * size : (k + 1) * size].tobytes() for k in range(len(frame.universes)))
    return dataclasses.replace(frame, universes=rows)


class OutputScheduler:
    """Offers the engine's latest frame to every route at :data:`OUTPUT_HZ`.

    Everything here runs on the output thread except construction and
    :meth:`route_status`, which any thread may call.
    """

    def __init__(
        self,
        engine: FrameSource,
        routes: Sequence[ScheduledRoute],
        clock: Clock,
        console: ConsoleOutput | None = None,
        *,
        layout: OutputLayout | None = None,
        sequences: Sequences | None = None,
        artnet: ArtNetNetwork | None = None,
        notices: Sequence[RouteNotice] = (),
    ) -> None:
        """``layout`` is the output layout of the compiled show ``routes``
        were built from (``None``: the routes open with the first frame);
        ``sequences`` and ``artnet`` are their sACN sequence counters and
        Art-Net network, and ``notices`` the notices (as passed to and
        returned by :func:`build_routes`: they say why the other routes are
        not sent). A frame with another layout object triggers a reconcile,
        which changes nothing when the layouts are equal (an engine restart)."""
        self._engine = engine
        self._routes = tuple(routes)
        self._clock = clock
        self._console = console
        self._previous: Frame | None = None  # the frame of the previous cycle
        self._layout = layout
        self._sequences = Sequences() if sequences is None else sequences
        self._artnet = ArtNetNetwork() if artnet is None else artnet
        self._discovery = UniverseDiscovery()
        self._discovery.update(self._sacn_senders())
        self._skipped: dict[str, Any] = {}  # route id → key of a route reported as not sent
        self._retry: dict[str, float | None] = {}  # failed to open → next try (None: unset)
        self._unsent: dict[str, _Unsent] = {}  # route id → why a route of the show is not sent
        self._published: _Table | None = None  # for route_status, once a layout is known
        if layout is not None:
            reported = {notice.route: notice for notice in notices if notice.route is not None}
            for route in layout.output["routes"]:
                if route["id"] not in {r.id for r in routes}:
                    self._skipped[route["id"]] = _route_key(route, layout.output)
                    self._unsent[route["id"]] = _unsent(route, reported.get(route["id"]))
                    if _retried(route):
                        self._retry[route["id"]] = None
            self._publish()
        self._health_at = -math.inf  # when the routes' status is read next
        self.opened: list[ScheduledRoute] = list(routes)
        """Every route opened during the run, closed ones included (for the final counts)."""
        self.notices: queue.SimpleQueue[RouteNotice] = queue.SimpleQueue()
        """Route changes made by reconciling, and engine stalls, for the CLI to print."""
        self.stats = OutputStats()
        self._fresh: Frame | None = None  # the newest frame the engine published …
        self._freshAt = 0.0  # … and the output time it was first seen
        self._stall: Frame | None = None  # while stalled: what is offered instead
        self._enabled = True  # the last frame's outputEnabled
        self._silenced: list[ScheduledRoute] = []  # sACN routes closed by OUTPUT off

    @property
    def routes(self) -> tuple[ScheduledRoute, ...]:
        """The routes being sent now (replaced, never mutated, by the output thread)."""
        return self._routes

    @property
    def layout(self) -> OutputLayout | None:
        """The layout the routes follow: ``None`` until a frame brought one."""
        return self._layout

    def route_status(self) -> tuple[RouteStatus, ...] | None:
        """Every route of the show, in show order, with what it does (see
        :class:`~busk.output.driver.RouteStatus`); ``None`` until a layout
        named the routes. Safe on any thread: it reads what the output thread
        published last, and the open drivers' status."""
        published = self._published  # one read: published by reference assignment
        if published is None:
            return None
        layout, routes, unsent = published
        numbers = {universe.id: universe.number for universe in layout.universes}
        open_routes = {route.id: route for route in routes}
        statuses = []
        for definition in layout.output["routes"]:
            ident = definition["id"]
            label = f"{PROTOCOL_LABELS[definition['protocol']]} {ident}"
            universe = numbers[definition["universeId"]]
            route = open_routes.get(ident)
            if route is None:
                state, detail = unsent[ident]
                packets = errors = 0
            else:
                status = route.driver.status()
                state, detail = ("ok" if status.ok else "failed"), status.detail
                packets, errors = status.packets, status.errors
            statuses.append(
                RouteStatus(
                    id=ident,
                    label=label,
                    universe=universe,
                    state=state,
                    detail=detail,
                    packets=packets,
                    errors=errors,
                )
            )
        return tuple(statuses)

    def service(self, now: float) -> None:
        """Run one output cycle for output time ``now``."""
        frame = self._engine.latest
        if frame is None:
            return
        if frame.layout is not None and frame.layout is not self._layout:
            self._reconcile(frame.layout)
        self._artnet.service(now)
        for notice in _network_notices(self._artnet):
            self.notices.put(notice)
        frame = self._follow(frame, now)
        if self._output(frame):
            changed = self._changes(frame)
            for route in self._routes:
                try:
                    route.driver.send(frame.universes[route.row], changed[route.row], now)
                except Exception:
                    route.faults += 1
            if self._retry:
                self._open_again(now)
            if now >= self._health_at:
                self._health_at = now + HEALTH_S
                self._check_health(now)
        self._discovery.service(now)
        if self._console is not None:
            self._console.service(now)

    def run(self, stop: threading.Event) -> None:
        """Run cycles at :data:`OUTPUT_HZ` until ``stop`` is set, then one final
        cycle, then :meth:`close` every driver (also if a cycle raises)."""
        clock = self._clock
        schedule = FixedRateSchedule(clock, OUTPUT_HZ)
        stats = self.stats
        late = 2.0 / OUTPUT_HZ  # a gap of more than two periods: a late cycle
        last: float | None = None
        try:
            while not stop.is_set():
                now = clock.now()
                if last is not None:
                    gap = now - last
                    stats.longestGap = max(stats.longestGap, gap)
                    stats.lateCycles += gap > late
                last = now
                stats.cycles += 1
                self.service(now)
                schedule.wait_next()
            self.service(clock.now())  # the frame the engine published last
        finally:
            self.close()

    def close(self) -> None:
        """Close every driver once, each guarded like :meth:`service`'s sends,
        and stop sACN universe discovery."""
        for route in self._routes:
            try:
                route.driver.close()
            except Exception:
                route.faults += 1
        self._discovery.close()

    def _follow(self, frame: Frame, now: float) -> Frame:
        """Note new frames and stalls (see the module docs); return the frame
        to offer: ``frame`` itself, or while stalled the held or darkened
        frame (one object for the whole stall, so it reads as unchanged)."""
        if frame is not self._fresh:
            if self._stall is not None:
                self._stall = None
                self.notices.put(RouteNotice(text="engine: frames again", failed=False))
            self._fresh, self._freshAt = frame, now
            return frame
        if self._stall is None:
            if now - self._freshAt < STALL_S:
                return frame
            layout = frame.layout
            if layout is None or layout.output["holdLastFrameOnEngineStall"]:
                self._stall, what = frame, "holding the last frame"
            else:
                self._stall, what = _darkened(frame, layout), "intensity off"
            text = f"engine: no new frame for {STALL_S:.1f} s; {what}"
            self.notices.put(RouteNotice(text=text, failed=True))
        if self._stall is frame:
            self.stats.framesHeld += 1
        else:
            self.stats.framesDarkened += 1
        return self._stall

    def _output(self, frame: Frame) -> bool:
        """Follow the frame's ``outputEnabled`` (see the module docs); return
        whether the routes send this cycle."""
        enabled = frame.outputEnabled
        if enabled == self._enabled:
            return enabled
        self._enabled = enabled
        if not enabled:
            self._silenced = [r for r in self._routes if isinstance(r.driver, SacnSender)]
            for route in self._silenced:
                try:
                    route.driver.close()  # Stream_Terminated
                except Exception:
                    route.faults += 1
            return False
        current = {id(route) for route in self._routes}
        for route in self._silenced:
            if id(route) in current:  # a live edit may have replaced it meanwhile
                try:
                    route.driver.open()
                except Exception:
                    route.faults += 1
        self._silenced = []
        self._previous = None  # every universe counts as changed: send at once
        return True

    def _sacn_senders(self) -> list[SacnSender]:
        return [route.driver for route in self._routes if isinstance(route.driver, SacnSender)]

    def _publish(self) -> None:
        """Publish the routes for :meth:`route_status` (one assignment: other
        threads see the table whole). Call after every change to them."""
        assert self._layout is not None
        self._published = (self._layout, self._routes, dict(self._unsent))

    def _changes(self, frame: Frame) -> list[bool]:
        """Per universe: do ``frame``'s bytes differ from the previous cycle's?

        Universes are matched by id when both frames carry a layout, so a
        reordered or new universe is compared with itself.
        """
        previous, self._previous = self._previous, frame
        if previous is None:
            return [True] * len(frame.universes)
        if frame is previous:
            return [False] * len(frame.universes)
        if frame.layout is None or previous.layout is None:
            return [
                new != old for new, old in zip(frame.universes, previous.universes, strict=True)
            ]
        before: Mapping[str, bytes] = {
            universe.id: data
            for universe, data in zip(previous.layout.universes, previous.universes, strict=True)
        }
        return [
            data != before.get(universe.id)
            for universe, data in zip(frame.layout.universes, frame.universes, strict=True)
        ]

    def _reconcile(self, layout: OutputLayout) -> None:
        """Follow a live edit: close removed or changed routes, open new or
        changed ones, re-point rows by universe id (see the module docs)."""
        settings = layout.output
        self._artnet.name = settings["sacnSourceName"]
        wanted = {route["id"]: route for route in settings["routes"]}
        rows = _rows(layout.universes)
        kept: dict[str, ScheduledRoute] = {}
        for route in self._routes:
            definition = wanted.get(route.id)
            if definition is not None and route.key == _route_key(definition, settings):
                route.row = rows[definition["universeId"]]
                kept[route.id] = route
                continue
            try:
                route.driver.close()
            except Exception:
                route.faults += 1
            self.notices.put(RouteNotice(text=f"{route.label}: closed", failed=False))
        routes: list[ScheduledRoute] = []
        skipped: dict[str, Any] = {}
        retry: dict[str, float | None] = {}
        unsent: dict[str, _Unsent] = {}
        for definition in settings["routes"]:
            ident = definition["id"]
            if ident in kept:
                routes.append(kept[ident])
                continue
            key = _route_key(definition, settings)
            if self._skipped.get(ident) == key:  # still not sent, already reported
                skipped[ident] = key
                unsent[ident] = self._unsent[ident]
                if ident in self._retry:
                    retry[ident] = self._retry[ident]
                continue
            opened = open_route(
                definition, settings, layout.universes, self._sequences, self._artnet
            )
            if isinstance(opened, RouteNotice):
                skipped[ident] = key
                unsent[ident] = _unsent(definition, opened)
                if _retried(definition):
                    retry[ident] = None
                self.notices.put(opened)
            else:
                routes.append(opened)
                self.opened.append(opened)
                self.notices.put(
                    RouteNotice(text=f"{opened.label}: {opened.description}", failed=False)
                )
        self._skipped = skipped
        self._retry = retry
        self._unsent = unsent
        self._routes = tuple(routes)
        self._layout = layout  # last: other threads see the routes once they see the layout
        self._publish()
        self._discovery.update(self._sacn_senders())

    def _open_again(self, now: float) -> None:
        """Try again to open the routes that failed to open, each every
        :data:`REOPEN_S` (see the module docs). A failure is not reported
        again (its new error only shows in :meth:`route_status`); a route
        that opens joins the others in show order."""
        layout = self._layout
        assert layout is not None  # routes are only retried once a layout named them
        settings = layout.output
        opened: list[ScheduledRoute] = []
        changed = False  # a failure's detail changed
        for ident, due in list(self._retry.items()):
            if due is None:  # first seen: the failed open was just now
                self._retry[ident] = now + REOPEN_S
                continue
            if now < due:
                continue
            definition = next(r for r in settings["routes"] if r["id"] == ident)
            route = open_route(
                definition, settings, layout.universes, self._sequences, self._artnet
            )
            if isinstance(route, RouteNotice):
                self._retry[ident] = now + REOPEN_S
                unsent = _unsent(definition, route)
                if unsent != self._unsent[ident]:
                    self._unsent[ident] = unsent
                    changed = True
                continue
            del self._retry[ident], self._skipped[ident], self._unsent[ident]
            opened.append(route)
            self.opened.append(route)
            text = f"{route.label}: {route.description} (sending)"
            self.notices.put(RouteNotice(text=text, failed=False))
        if opened:
            order = {route["id"]: k for k, route in enumerate(settings["routes"])}
            self._routes = tuple(sorted((*self._routes, *opened), key=lambda r: order[r.id]))
            self._discovery.update(self._sacn_senders())
            self._previous = None  # the new routes send at once
        if opened or changed:
            self._publish()

    def _check_health(self, now: float) -> None:
        """Close and reopen each route whose status has been failing for
        :data:`FAIL_S`, then every :data:`REOPEN_S` while it fails (see the
        module docs). DMX-USB routes reopen themselves."""
        reopened = False
        for route in self._routes:
            driver = route.driver
            if isinstance(driver, EnttecSender):
                continue
            try:
                ok = driver.status().ok
            except Exception:
                route.faults += 1
                continue
            if ok:
                route.reopenAt = None
            elif route.reopenAt is None:
                route.reopenAt = now + FAIL_S
            elif now >= route.reopenAt:
                route.reopenAt = now + REOPEN_S
                reopened = True
                try:
                    driver.close()
                    driver.open()
                except Exception:
                    route.faults += 1
        if reopened:
            self._previous = None  # every universe counts as changed: send at once
            self._discovery.close()  # its sockets may hold a stale interface index too
            self._discovery.update(self._sacn_senders())
