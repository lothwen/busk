"""A minimal WebSocket client for the tests: the client side of RFC 6455.

It imports nothing from :mod:`busk.web`. The accept key and the frame layout
are written here from the RFC, so a mistake in the server fails the tests
instead of round-tripping through shared code. Every socket has a timeout,
so a test never hangs on a server that stopped answering.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import os
import socket
from dataclasses import dataclass
from types import TracebackType
from typing import Self

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
CONTINUATION, TEXT, BINARY, CLOSE, PING, PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
TIMEOUT = 5.0


def frame(
    opcode: int,
    payload: bytes = b"",
    *,
    fin: bool = True,
    masked: bool = True,
    rsv: int = 0,
    mask: bytes | None = None,
) -> bytes:
    """One client frame (RFC 6455 §5.2): masked unless told otherwise."""
    first = (0x80 if fin else 0) | (rsv << 4) | opcode
    size = len(payload)
    flag = 0x80 if masked else 0
    if size < 126:
        header = bytes((first, flag | size))
    elif size < 65536:
        header = bytes((first, flag | 126)) + size.to_bytes(2, "big")
    else:
        header = bytes((first, flag | 127)) + size.to_bytes(8, "big")
    if not masked:
        return header + payload
    key = os.urandom(4) if mask is None else mask
    return header + key + bytes(b ^ key[i % 4] for i, b in enumerate(payload))


def accept_for(key: str) -> str:
    """The ``Sec-WebSocket-Accept`` a server must answer to ``key``."""
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


@dataclass
class Response:
    status: int
    headers: dict[str, str]  # names lower-cased
    body: bytes


class Connection:
    """A TCP connection with a read buffer."""

    def __init__(self, port: int, host: str = "127.0.0.1", timeout: float = TIMEOUT) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.buffer = bytearray()

    def read(self, size: int) -> bytes:
        """Exactly ``size`` bytes; :class:`EOFError` if the server closes first."""
        while len(self.buffer) < size:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError(f"connection closed with {len(self.buffer)} of {size} bytes")
            self.buffer += chunk
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data

    def read_until(self, marker: bytes) -> bytes:
        while (end := self.buffer.find(marker)) < 0:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError("connection closed before the end of the headers")
            self.buffer += chunk
        return self.read(end + len(marker))

    def response(self) -> Response:
        """Read an HTTP response; the body by its Content-Length."""
        head = self.read_until(b"\r\n\r\n").decode("latin-1")
        status_line, *lines = head.split("\r\n")[:-2]
        headers = {}
        for line in lines:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        status = int(status_line.split()[1])
        body = self.read(int(headers.get("content-length", "0"))) if status != 101 else b""
        return Response(status, headers, body)

    def close(self) -> None:
        """Close; shutting down first wakes a thread blocked reading it."""
        with contextlib.suppress(OSError):
            self.sock.shutdown(socket.SHUT_RDWR)
        self.sock.close()


def request(
    port: int,
    path: str,
    headers: dict[str, str] | None = None,
    *,
    after: bytes = b"",
) -> tuple[Connection, Response]:
    """Send ``GET path`` with ``headers`` (plus ``after`` in the same write)
    and read the response."""
    connection = Connection(port)
    lines = [f"GET {path} HTTP/1.1", f"Host: 127.0.0.1:{port}"]
    lines += [f"{name}: {value}" for name, value in (headers or {}).items()]
    connection.sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode() + after)
    return connection, connection.response()


def upgrade_headers(key: str | None = None) -> dict[str, str]:
    """The headers of a valid upgrade request."""
    return {
        "Upgrade": "websocket",
        "Connection": "Upgrade",
        "Sec-WebSocket-Key": key or base64.b64encode(os.urandom(16)).decode(),
        "Sec-WebSocket-Version": "13",
    }


class WsClient:
    """A connected WebSocket client. ``after`` is sent in the same write as
    the handshake (the first frame in the headers' packet)."""

    def __init__(
        self,
        port: int,
        key: str,
        *,
        headers: dict[str, str] | None = None,
        after: bytes = b"",
    ) -> None:
        request_headers = upgrade_headers() | (headers or {})
        self.connection, response = request(port, f"/ws?k={key}", request_headers, after=after)
        assert response.status == 101, response
        assert response.headers["upgrade"].lower() == "websocket"
        assert response.headers["connection"].lower() == "upgrade"
        expected = accept_for(request_headers["Sec-WebSocket-Key"])
        assert response.headers["sec-websocket-accept"] == expected

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.connection.close()

    def send(self, opcode: int, payload: bytes = b"", **options: object) -> None:
        self.connection.sock.sendall(frame(opcode, payload, **options))  # type: ignore[arg-type]

    def send_text(self, text: str) -> None:
        self.send(TEXT, text.encode())

    def recv(self) -> tuple[int, bytes]:
        """One server frame: its opcode and payload. Server frames must be
        final and unmasked."""
        first, second = self.connection.read(2)
        assert first & 0x80, "server frames are never fragmented"
        assert not first & 0x70, "no extensions"
        assert not second & 0x80, "server frames are never masked"
        size = second & 0x7F
        if size == 126:
            size = int.from_bytes(self.connection.read(2), "big")
            assert size >= 126, "the shortest length encoding"
        elif size == 127:
            size = int.from_bytes(self.connection.read(8), "big")
            assert size >= 65536, "the shortest length encoding"
        return first & 0x0F, self.connection.read(size)

    def recv_text(self) -> str:
        opcode, payload = self.recv()
        assert opcode == TEXT, (opcode, payload)
        return payload.decode()

    def recv_close(self) -> int | None:
        """Read up to the server's close frame and return its code, then
        check that the server closes the connection."""
        while True:
            opcode, payload = self.recv()
            if opcode == CLOSE:
                break
        with contextlib.suppress(ConnectionResetError):
            assert self.connection.sock.recv(1) == b"", "nothing after a close frame"
        return int.from_bytes(payload[:2], "big") if payload else None

    def close(self) -> None:
        self.connection.close()
