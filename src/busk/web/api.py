"""The web remote's JSON protocol, its broadcaster and the web surface (phase-6-plan §5.12).

Messages
--------
Every message is one JSON object in a text frame.

==========  =================================================================
Server →    When
==========  =================================================================
``hello``   on connect: ``version`` (:data:`PROTOCOL_VERSION`), ``surface``
            (its id) and ``time``, the engine time, so the page can place
            the beat anchors on its own clock
``show``    on connect, and when the compiled show changes (by identity):
            ``pages``, ``playbacks`` and ``masters`` (:func:`show_message`;
            a master's ``tap`` says whether TAP drives it)
``state``   on connect, and when the engine publishes a new snapshot, at
            most :data:`STATE_HZ` times a second: the
            :class:`~busk.engine.snapshot.EngineSnapshot` as JSON
``error``   a command refused: ``id`` (the client's) and ``message``
==========  =================================================================

A client sends ``{"id": <its id>, "command": {…}}``. Only *performance*
commands are accepted (decision 15: single writer; programmer and show edits
stay on the console), so the session lock is never taken. They go through
``submit`` with the origin ``{surfaceId, remote: "ip:port"}``; a command the
bus rejects is answered with an ``error``, an accepted one with nothing (the
next ``state`` shows it).

Rate limit
----------
Each client has a :class:`~busk.io.ratelimit.TokenBucket` (phase-7-plan
decision 19): :data:`~busk.io.ratelimit.WEB_RATE` messages a second, bursts
of :data:`~busk.io.ratelimit.WEB_BURST`. Beyond it a message is dropped,
unless it releases a button (``PLAYBACK_BUTTON`` or ``FLASH`` with ``down:
false``), so a held flash cannot stick. The client hears about drops at most
once a second: an ``error`` with ``id`` null and ``rate limit: N commands
dropped``.

Held buttons
------------
The API remembers each ``PLAYBACK_BUTTON`` a client pressed and did not
release. When the client disconnects (a phone locks its screen, Wi-Fi
drops), each is released, so a flash or a swop is never left on.

Broadcast
---------
:meth:`WebApi.broadcast` checks the compiled show and the engine snapshot,
serialises each new one once, and hands the text to every client's slot
(``show``, ``state``): a client that reads slowly skips states instead of
queueing them. :meth:`WebApi.run` calls it :data:`STATE_HZ` times a second,
so a burst of fader moves costs at most that many messages per client.

The surface
-----------
:class:`WebSurface` is one ``web`` surface in ``busk run``: its
:class:`~busk.web.server.WebServer` on ``match.host`` (default: every
interface) and ``match.port``, its API and the broadcaster thread.
"""

from __future__ import annotations

import dataclasses
import json
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

from busk.commands.classes import command_class
from busk.commands.types import Command, CommandOrigin
from busk.compiler.compile import CompiledShow
from busk.engine.snapshot import EngineSnapshot
from busk.io.ratelimit import WEB_BURST, WEB_RATE, TokenBucket
from busk.model.common import PlaybackId, SurfaceId
from busk.model.surface import ControlSurface
from busk.output.netif import ipv4_addresses
from busk.web.server import WebServer
from busk.web.websocket import LINGER, STALL_TIMEOUT, WebSocket

if TYPE_CHECKING:
    from busk.session.session import CommandResult

PROTOCOL_VERSION: Final = 1
STATE_HZ: Final = 30.0
"""Broadcasts per second: the most ``state`` messages a client gets."""

type Message = dict[str, object]
type Press = tuple[PlaybackId | None, int | None, int]
"""A held ``PLAYBACK_BUTTON``: its ``playbackId`` or ``slot``, and ``button``."""


@dataclass(frozen=True, slots=True)
class WebLink:
    """What a web surface reads and submits to in ``busk run``."""

    snapshot: Callable[[], EngineSnapshot | None]  # the engine's latest snapshot
    compiled: Callable[[], CompiledShow]  # the show the engine runs
    submit: Callable[[Command, CommandOrigin], CommandResult]  # Session.submit
    clock: Callable[[], float]  # engine time
    key: str  # the access key (busk.persistence.paths.web_key)


def show_message(compiled: CompiledShow) -> Message:
    """What the page needs to know of the show: pages, playbacks, masters."""
    playbacks = []
    for playback in compiled.playbacks.values():
        cues = playback.cueList.cues
        goto = None if playback.gotoCue is None else cues[playback.gotoCue]
        playbacks.append(
            {
                "id": playback.id,
                "number": playback.number,
                "name": playback.name,
                "fader": playback.fader,
                "buttons": list(playback.buttons),
                "gotoCue": None if goto is None else {"number": goto.number, "name": goto.name},
                "cueCount": len(cues),
            }
        )
    return {
        "type": "show",
        "pages": [
            {"id": page.id, "number": page.number, "name": page.name, "slots": list(page.slots)}
            for page in compiled.pages
        ],
        "playbacks": playbacks,
        "masters": [
            {
                "id": master.id,
                "name": master.name,
                "kind": master.kind,
                "steps": list(master.multiplierSteps),
                "tap": master.tap,
            }
            for master in compiled.masters.values()
        ],
    }


def state_message(snapshot: EngineSnapshot) -> Message:
    """The engine snapshot as JSON: tuples become lists, ``masterLevels``
    a list of ``[id, level]`` pairs."""
    return {"type": "state", **dataclasses.asdict(snapshot)}


def _release(message: object) -> bool:
    """Whether ``message`` releases a button: never dropped by the rate limit."""
    if not isinstance(message, dict):
        return False
    command = message.get("command")
    return (
        isinstance(command, dict)
        and command.get("type") in ("PLAYBACK_BUTTON", "FLASH")
        and command.get("down") is False
    )


def dumps(message: Message) -> str:
    return json.dumps(message, separators=(",", ":"))


class WebApi:
    """The protocol of one web surface: a :class:`~busk.web.server.WebApp`
    for its server, and the broadcaster (see the module docs).

    The handler threads call :meth:`connected`, :meth:`received` and
    :meth:`disconnected`; the broadcaster thread calls :meth:`broadcast`.
    Exceptions raised by :meth:`broadcast` in :meth:`run` are counted in
    :attr:`errors`.
    """

    def __init__(self, surface_id: SurfaceId, link: WebLink) -> None:
        self.surface_id = surface_id
        self._link = link
        self._lock = threading.Lock()
        self._clients: dict[WebSocket, set[Press]] = {}
        self._buckets: dict[WebSocket, TokenBucket] = {}  # each client's rate limit
        self._compiled: CompiledShow | None = None
        self._snapshot: EngineSnapshot | None = None
        self._show: str | None = None
        self._state: str | None = None
        self.errors = 0

    # ------------------------------------------------------------ clients

    def connected(self, client: WebSocket) -> None:
        """Greet a new client: hello, then the current show and state."""
        hello = {
            "type": "hello",
            "version": PROTOCOL_VERSION,
            "surface": self.surface_id,
            "time": self._link.clock(),
        }
        client.send(dumps(hello))
        with self._lock:
            self._update()
            self._clients[client] = set()
            self._buckets[client] = TokenBucket(WEB_RATE, WEB_BURST, self._link.clock)
            if self._show is not None:
                client.publish("show", self._show)
            if self._state is not None:
                client.publish("state", self._state)

    def received(self, client: WebSocket, text: str) -> None:
        """Submit a client's command, or answer why not; drop it beyond the
        client's rate limit (see the module docs)."""
        try:
            message = json.loads(text)
        except ValueError as exc:
            if self._admitted(client, None):
                self._error(client, None, f"not JSON: {exc}")
            return
        if not self._admitted(client, message):
            return
        if not isinstance(message, dict):
            self._error(client, None, 'expected an object {"id": …, "command": {…}}')
            return
        ident = message.get("id")
        if not isinstance(ident, str | int) or isinstance(ident, bool):
            ident = None
        command = message.get("command")
        if not isinstance(command, dict):
            self._error(client, ident, "expected a command object")
            return
        kind = command_class(command)
        if kind != "performance":
            what = command.get("type")
            reason = (
                f"unknown command type {what!r}"
                if kind is None
                else f"{what} is a {kind} command; the web remote sends performance commands only"
            )
            self._error(client, ident, reason)
            return
        result = self._link.submit(cast(Command, command), self._origin(client))
        if not result.ok:
            self._error(client, ident, result.message)
        elif command["type"] == "PLAYBACK_BUTTON":
            press = (command.get("playbackId"), command.get("slot"), command["button"])
            with self._lock:
                held = self._clients.get(client)
                if held is not None:
                    (held.add if command["down"] else held.discard)(press)

    def disconnected(self, client: WebSocket) -> None:
        """Release every button the client still held."""
        with self._lock:
            held = self._clients.pop(client, set())
            self._buckets.pop(client, None)
        for playback, slot, button in sorted(held, key=repr):
            command: Message = {"type": "PLAYBACK_BUTTON", "button": button, "down": False}
            if playback is not None:
                command["playbackId"] = playback
            if slot is not None:
                command["slot"] = slot
            self._link.submit(cast(Command, command), self._origin(client))

    def _admitted(self, client: WebSocket, message: object) -> bool:
        """Whether the client's rate limit lets ``message`` through: a button
        release always passes. A dropped message may get the client the
        error that reports the drops."""
        with self._lock:
            bucket = self._buckets.get(client)
        if bucket is None or _release(message) or bucket.take():
            return True
        dropped = bucket.report()
        if dropped:
            noun = "command" if dropped == 1 else "commands"
            self._error(client, None, f"rate limit: {dropped} {noun} dropped")
        return False

    def _origin(self, client: WebSocket) -> CommandOrigin:
        return {"surfaceId": self.surface_id, "remote": client.remote}

    def _error(self, client: WebSocket, ident: str | int | None, message: str) -> None:
        client.send(dumps({"type": "error", "id": ident, "message": message}))

    # ------------------------------------------------------------ broadcast

    def broadcast(self) -> None:
        """Hand a new show or state to every client."""
        with self._lock:
            show, state = self._update()
            for client in self._clients:
                if show is not None:
                    client.publish("show", show)
                if state is not None:
                    client.publish("state", state)

    def _update(self) -> tuple[str | None, str | None]:
        """Serialise the show and the snapshot if they changed (under the
        lock); returns the new texts, ``None`` for an unchanged one."""
        show = state = None
        compiled = self._link.compiled()
        if compiled is not self._compiled:
            self._compiled = compiled
            self._show = show = dumps(show_message(compiled))
        snapshot = self._link.snapshot()
        if snapshot is not None and snapshot is not self._snapshot:
            self._snapshot = snapshot
            self._state = state = dumps(state_message(snapshot))
        return show, state

    def run(self, stop: threading.Event) -> None:
        """Broadcast :data:`STATE_HZ` times a second until ``stop`` is set."""
        while not stop.wait(1.0 / STATE_HZ):
            try:
                self.broadcast()
            except Exception:  # never out of the broadcaster
                self.errors += 1


class WebSurface:
    """One ``web`` surface: its server, its API and the broadcaster thread.

    ``stall`` and ``linger`` are passed to the server (tests shorten them).
    """

    def __init__(
        self,
        surface: ControlSurface,
        link: WebLink,
        *,
        stall: float = STALL_TIMEOUT,
        linger: float = LINGER,
    ) -> None:
        self.surface = surface
        self.key = link.key
        self.api = WebApi(surface["id"], link)
        match = surface["match"]
        self.server = WebServer(
            self.api,
            link.key,
            host=match.get("host", ""),
            port=match.get("port", 0),
            stall=stall,
            linger=linger,
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def id(self) -> SurfaceId:
        return self.surface["id"]

    def open(self) -> str | None:
        """Listen and start broadcasting. Returns ``None``, or why it cannot
        listen."""
        reason = self.server.open()
        if reason is not None:
            return reason
        self._thread = threading.Thread(
            target=self.api.run, args=(self._stop,), name=f"web {self.id}", daemon=True
        )
        self._thread.start()
        return None

    def urls(self) -> list[str]:
        """The addresses to open on a phone: ``match.host`` if the show binds
        one, else one per IPv4 interface (loopback only when it is all
        there is)."""
        host = self.surface["match"].get("host")
        if host:
            hosts = [host]
        else:
            try:
                addresses = [address for _, address in ipv4_addresses()]
            except OSError:
                addresses = [socket.gethostname()]
            hosts = [a for a in addresses if not a.startswith("127.")] or addresses
        return [f"http://{host}:{self.server.port}/?k={self.key}" for host in hosts]

    def close(self) -> None:
        """Stop broadcasting, then close the server (its clients' held
        buttons are released). Idempotent."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join()
        self.server.close()
