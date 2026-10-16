"""The web remote's HTTP and WebSocket server (phase-6-plan §5.12, decision 15).

Routes
------
* ``GET /`` and ``GET /index.html`` serve the phone page;
* ``GET /ws`` upgrades to a WebSocket (:mod:`busk.web.websocket`);
* anything else is 404, and a method other than ``GET`` is 501.

No path ever reaches the file system: the page is one file read from the
package with :mod:`importlib.resources` (:func:`index_page`).

Access
------
Every route needs the installation's key in the query string, ``?k=<key>``
(:func:`busk.persistence.paths.web_key`). A missing or wrong key gets 403
with a hint; keys are compared in constant time. The WebSocket upgrade also
checks the browser's ``Origin`` against the ``Host`` it asked for
(:func:`~busk.web.websocket.check_origin`), so another site's page open on
the phone cannot drive the show.

Clients
-------
Each WebSocket is served on its own handler thread, which hands its
messages to the :class:`WebApp`; the app sends with
:meth:`~busk.web.websocket.WebSocket.send` and
:meth:`~busk.web.websocket.WebSocket.publish`. :meth:`WebServer.clients`
lists the connected clients, for broadcasts. An exception raised by the app
is counted in :attr:`WebServer.errors` and the connection goes on.

The server binds ``host`` (``""``: every interface) at ``port``. Nothing is
logged: the console shares the terminal.
"""

from __future__ import annotations

import hmac
import importlib.resources
import socketserver
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from typing import Final, Protocol
from urllib.parse import parse_qs, urlsplit

from busk.web.websocket import (
    LINGER,
    STALL_TIMEOUT,
    VERSION,
    CloseCode,
    HandshakeError,
    WebSocket,
    accept_key,
    check_origin,
    check_upgrade,
)

PAGE_PATHS: Final = ("/", "/index.html")
SOCKET_PATH: Final = "/ws"

HTTP_TIMEOUT: Final = 10.0
"""Seconds an HTTP connection may sit idle before it is dropped (not WebSockets)."""

POLL_INTERVAL: Final = 0.05
"""Seconds between the accept loop's checks for :meth:`WebServer.close`."""

KEY_HINT: Final = b"Open the address printed by busk run: it ends with ?k=<key>.\n"


def index_page() -> bytes:
    """The phone page, from the package."""
    return importlib.resources.files("busk.web").joinpath("static/index.html").read_bytes()


class WebApp(Protocol):
    """What the server calls for each WebSocket client, on its handler thread."""

    def connected(self, client: WebSocket) -> None: ...

    def received(self, client: WebSocket, text: str) -> None: ...

    def disconnected(self, client: WebSocket) -> None: ...


class WebServer:
    """One ``web`` surface's server: see the module docs.

    ``stall`` and ``linger`` are passed to each
    :class:`~busk.web.websocket.WebSocket` (tests shorten them).
    """

    def __init__(
        self,
        app: WebApp,
        key: str,
        *,
        host: str = "",
        port: int = 0,
        page: bytes | None = None,
        stall: float = STALL_TIMEOUT,
        linger: float = LINGER,
    ) -> None:
        self.app = app
        self.host = host
        self._key = key.encode("utf-8")
        self._port = port
        self.page = index_page() if page is None else page
        self.stall = stall
        self.linger = linger
        self.port: int | None = None
        """The port it listens on, once open."""
        self.errors = 0
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._clients: dict[WebSocket, threading.Thread] = {}
        self._closed = False

    def open(self) -> str | None:
        """Listen and start the accept loop. Returns ``None``, or why it
        cannot listen."""
        try:
            server = _Server((self.host, self._port), _Handler)
        except OSError as exc:
            where = f"{self.host}:{self._port}" if self.host else f"tcp {self._port}"
            return f"cannot listen on {where}: {exc.strerror or exc}"
        server.web = self
        self._server = server
        self.port = server.server_address[1]
        self._thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": POLL_INTERVAL},
            name=f"web {self.port}",
            daemon=True,
        )
        self._thread.start()
        return None

    def allows(self, key: str) -> bool:
        """Whether ``key`` is the access key (constant time)."""
        return hmac.compare_digest(key.encode("utf-8"), self._key)

    def clients(self) -> tuple[WebSocket, ...]:
        """The connected WebSocket clients."""
        with self._lock:
            return tuple(self._clients)

    def serve(self, client: WebSocket) -> None:
        """Run one upgraded connection to its end, on its handler thread."""
        with self._lock:
            self._clients[client] = threading.current_thread()
            closed = self._closed
        client.start()
        if closed:
            client.close(CloseCode.GOING_AWAY)
        try:
            self._call(self.app.connected, client)
            while (text := client.receive()) is not None:
                self._call(self.app.received, client, text)
        finally:
            client.finish()
            self._call(self.app.disconnected, client)
            with self._lock:
                del self._clients[client]

    def _call(self, method: Callable[..., None], *args: object) -> None:
        try:
            method(*args)
        except Exception:  # an app bug must not take the connection down
            self.errors += 1

    def close(self) -> None:
        """Stop listening, send every client a close frame (1001, going
        away) and wait for their connections to end. Idempotent."""
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join()
        with self._lock:
            self._closed = True
            clients = dict(self._clients)
        for client in clients:
            client.close(CloseCode.GOING_AWAY)
        for handler in clients.values():
            handler.join(self.stall + self.linger + 1.0)


class _Server(socketserver.ThreadingTCPServer):
    """The accept loop. Unlike ``HTTPServer`` it never looks up its own
    host name, which can take seconds without DNS in a venue."""

    allow_reuse_address = True
    daemon_threads = True
    web: WebServer

    def handle_error(self, request: object, client_address: object) -> None:
        self.web.errors += 1


class _Handler(BaseHTTPRequestHandler):
    """One HTTP connection: the routes of the module docs."""

    protocol_version = "HTTP/1.1"
    server_version = "busk"
    timeout = HTTP_TIMEOUT
    disable_nagle_algorithm = True  # a state frame goes out at once, not after the last one's ACK
    server: _Server

    def log_message(self, format: str, *args: object) -> None:
        """Silent: the console shares the terminal."""

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        web = self.server.web
        if url.path not in (*PAGE_PATHS, SOCKET_PATH):
            self._respond(404, b"Not found.\n")
            return
        if not web.allows(parse_qs(url.query).get("k", [""])[0]):
            self._respond(403, KEY_HINT)
            return
        if url.path != SOCKET_PATH:
            self._respond(200, web.page, "text/html; charset=utf-8")
            return
        try:
            key = check_upgrade(self.headers)
            check_origin(self.headers.get("Origin"), self.headers.get("Host"))
        except HandshakeError as error:
            extra = (("Sec-WebSocket-Version", VERSION),) if error.status == 426 else ()
            self._respond(error.status, f"{error.message}.\n".encode(), headers=extra)
            return
        self._upgrade(key)

    def _respond(
        self,
        status: int,
        body: bytes,
        content_type: str = "text/plain; charset=utf-8",
        headers: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _upgrade(self, key: str) -> None:
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept_key(key))
        self.end_headers()
        self.close_connection = True
        self.connection.settimeout(None)  # a WebSocket may be quiet for as long as it likes
        host, port = self.client_address[:2]
        web = self.server.web
        client = WebSocket(
            self.rfile,
            self.connection,
            remote=f"{host}:{port}",
            stall=web.stall,
            linger=web.linger,
        )
        web.serve(client)
