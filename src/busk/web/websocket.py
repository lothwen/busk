"""The server side of RFC 6455, as much as the web remote needs (phase-6-plan §5.12, decision 15).

Handshake
---------
:func:`check_upgrade` validates an upgrade request's headers (RFC 6455
§4.2.1): ``Upgrade: websocket``, ``Connection: Upgrade``, version 13 and a
16-byte ``Sec-WebSocket-Key``. :func:`check_origin` refuses a browser
connecting from another site's page (cross-site WebSocket hijacking): the
``Origin`` header must be absent, as from non-browser clients, or equal
``http://<Host>``. Both raise :class:`HandshakeError` with the HTTP status to
answer. :func:`accept_key` computes ``Sec-WebSocket-Accept``.

Frames
------
No extensions and no subprotocols. :class:`FrameReader` reads client frames:

* every client frame must be masked, and its reserved bits clear;
* text messages may be fragmented, with control frames between the
  fragments; they must be valid UTF-8 once complete;
* ping, pong and close frames are returned to the caller;
* violations raise :class:`ProtocolError` with the close code to send:
  1002 for a protocol error, 1003 for a binary message, 1007 for invalid
  UTF-8, 1009 for a message over :data:`MAX_MESSAGE` bytes. The size is
  checked from the frame header, so an oversized payload is never read
  into memory.

Server frames (:func:`encode_frame`) are unmasked and never fragmented.

Connections
-----------
A :class:`WebSocket` is one accepted connection. Frames are read on the
thread that calls :meth:`~WebSocket.receive`; every write happens on the
connection's own writer thread, so frames never interleave. The writer sends,
in this order of priority: pongs, the close frame, replies queued with
:meth:`~WebSocket.send`, then the latest text of each *slot* given to
:meth:`~WebSocket.publish`. A slot keeps only its latest text, so a client
that reads slowly gets fewer messages instead of a growing queue; slots are
sent in the order they were first published.

A write that makes no progress for ``stall`` seconds (default
:data:`STALL_TIMEOUT`) aborts the connection: a phone that stopped reading
is dropped without slowing anything else.

Closing follows RFC 6455 §7: the side that starts it sends a close frame,
the other answers with one. After its close frame the server stops writing
and reads until the client closes, for at most ``linger`` seconds (default
:data:`LINGER`), then aborts. Reading out what the client still sends keeps
the kernel from answering with a reset, which could destroy the close frame
before the client reads it.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import select
import socket
import threading
import time
from collections import deque
from email.message import Message
from enum import IntEnum
from typing import Final, Protocol

GUID: Final = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
"""The fixed string of RFC 6455 §1.3 that the accept key hashes with the client's key."""

VERSION: Final = "13"
"""The only ``Sec-WebSocket-Version`` accepted (RFC 6455 §4.1)."""

MAX_MESSAGE: Final = 64 * 1024
"""The largest client message accepted, in bytes; a larger one closes with 1009."""

STALL_TIMEOUT: Final = 2.0
"""Seconds a write may make no progress before the connection is aborted."""

LINGER: Final = 1.0
"""Seconds to wait for the client to close after the server's close frame."""

MAX_REPLIES: Final = 64
"""Replies queued for one client; past this the oldest are dropped."""


class Opcode(IntEnum):
    """Frame opcodes (RFC 6455 §5.2)."""

    CONTINUATION = 0x0
    TEXT = 0x1
    BINARY = 0x2
    CLOSE = 0x8
    PING = 0x9
    PONG = 0xA


class CloseCode(IntEnum):
    """The close codes this server sends (RFC 6455 §7.4.1)."""

    NORMAL = 1000
    GOING_AWAY = 1001
    PROTOCOL_ERROR = 1002
    UNSUPPORTED_DATA = 1003
    INVALID_DATA = 1007
    TOO_BIG = 1009


# --------------------------------------------------------------------- handshake


class HandshakeError(Exception):
    """An upgrade request to refuse, with the HTTP status to answer."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def accept_key(key: str) -> str:
    """``Sec-WebSocket-Accept`` for a client's ``Sec-WebSocket-Key``."""
    digest = hashlib.sha1((key + GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def _tokens(value: str | None) -> set[str]:
    """The comma-separated tokens of a header, lower-cased."""
    return {token.strip().lower() for token in (value or "").split(",")}


def check_upgrade(headers: Message) -> str:
    """Validate the WebSocket headers of an upgrade request and return its
    ``Sec-WebSocket-Key``. Raises :class:`HandshakeError` (400, or 426 for
    another version)."""
    if "websocket" not in _tokens(headers.get("Upgrade")):
        raise HandshakeError(400, "expected the header Upgrade: websocket")
    if "upgrade" not in _tokens(headers.get("Connection")):
        raise HandshakeError(400, "expected the header Connection: Upgrade")
    if headers.get("Sec-WebSocket-Version", "").strip() != VERSION:
        raise HandshakeError(426, f"only WebSocket version {VERSION} is supported")
    key = headers.get("Sec-WebSocket-Key", "").strip()
    try:
        valid = len(base64.b64decode(key, validate=True)) == 16
    except binascii.Error:
        valid = False
    if not valid:
        raise HandshakeError(400, "Sec-WebSocket-Key must be 16 bytes in base64")
    return key


def check_origin(origin: str | None, host: str | None) -> None:
    """Refuse a browser page from another origin (403). No ``Origin`` is
    accepted: only browsers send one, and they cannot leave it out."""
    if origin is None:
        return
    if host is None or origin.strip().lower() != f"http://{host.strip()}".lower():
        raise HandshakeError(403, "WebSocket connections from another site's page are refused")


# --------------------------------------------------------------------- frames


class ProtocolError(Exception):
    """A client frame that breaks the protocol, with the close code to send."""

    def __init__(self, code: CloseCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def encode_frame(opcode: Opcode, payload: bytes = b"") -> bytes:
    """One unfragmented, unmasked server frame."""
    size = len(payload)
    if size < 126:
        header = bytes((0x80 | opcode, size))
    elif size < 1 << 16:
        header = bytes((0x80 | opcode, 126)) + size.to_bytes(2, "big")
    else:
        header = bytes((0x80 | opcode, 127)) + size.to_bytes(8, "big")
    return header + payload


def unmask(payload: bytes, mask: bytes) -> bytes:
    """XOR ``payload`` with the 4-byte ``mask`` repeated (RFC 6455 §5.3)."""
    size = len(payload)
    if not size:
        return b""
    key = (mask * (size // 4 + 1))[:size]
    return (int.from_bytes(payload, "big") ^ int.from_bytes(key, "big")).to_bytes(size, "big")


class Stream(Protocol):
    """What the reader needs of a connection's buffered input."""

    def read(self, size: int = ..., /) -> bytes: ...

    def read1(self, size: int = ..., /) -> bytes: ...


type Control = tuple[Opcode, bytes]
"""A ping, pong or close frame and its payload."""


class FrameReader:
    """Client frames from a stream: complete text messages and control frames.

    The state of a fragmented message survives the control frames read
    between its fragments.
    """

    def __init__(self, stream: Stream, limit: int = MAX_MESSAGE) -> None:
        self._stream = stream
        self._limit = limit
        self._parts: list[bytes] = []
        self._size = 0
        self._started = False  # a fragmented text message is in progress

    def read(self) -> str | Control | None:
        """The next complete text message, or the next control frame;
        ``None`` at the end of the stream. Raises :class:`ProtocolError`."""
        while True:
            header = self._exact(2)
            if header is None:
                return None
            fin, opcode, length = header[0] & 0x80, header[0] & 0x0F, header[1] & 0x7F
            if header[0] & 0x70:
                raise ProtocolError(CloseCode.PROTOCOL_ERROR, "reserved bits are set")
            if not header[1] & 0x80:
                raise ProtocolError(CloseCode.PROTOCOL_ERROR, "client frames must be masked")
            if length >= 126:
                extended = self._exact(2 if length == 126 else 8)
                if extended is None:
                    return None
                length = int.from_bytes(extended, "big")
                if length >> 63:
                    raise ProtocolError(CloseCode.PROTOCOL_ERROR, "frame length out of range")
            self._check(opcode, fin, length)
            mask = self._exact(4)
            payload = None if mask is None else self._exact(length)
            if mask is None or payload is None:
                return None
            payload = unmask(payload, mask)
            if opcode >= Opcode.CLOSE:
                return self._control(Opcode(opcode), payload)
            self._parts.append(payload)
            self._size += length
            self._started = True
            if fin:
                return self._text()

    def _check(self, opcode: int, fin: int, length: int) -> None:
        """Reject a frame from its header, before its payload is read."""
        if opcode in (Opcode.CLOSE, Opcode.PING, Opcode.PONG):
            if not fin or length > 125:
                raise ProtocolError(
                    CloseCode.PROTOCOL_ERROR, "control frames must be single and short"
                )
            return
        if opcode == Opcode.CONTINUATION:
            if not self._started:
                raise ProtocolError(CloseCode.PROTOCOL_ERROR, "continuation without a message")
        elif opcode in (Opcode.TEXT, Opcode.BINARY):
            if self._started:
                raise ProtocolError(
                    CloseCode.PROTOCOL_ERROR, "a new message inside a fragmented one"
                )
            if opcode == Opcode.BINARY:
                raise ProtocolError(CloseCode.UNSUPPORTED_DATA, "binary messages are not accepted")
        else:
            raise ProtocolError(CloseCode.PROTOCOL_ERROR, f"unknown opcode {opcode:#x}")
        if self._size + length > self._limit:
            raise ProtocolError(CloseCode.TOO_BIG, f"messages are limited to {self._limit} bytes")

    def _control(self, opcode: Opcode, payload: bytes) -> Control:
        if opcode == Opcode.CLOSE:
            if len(payload) == 1:
                raise ProtocolError(CloseCode.PROTOCOL_ERROR, "a close code needs 2 bytes")
            try:
                payload[2:].decode("utf-8")
            except UnicodeDecodeError:
                raise ProtocolError(
                    CloseCode.INVALID_DATA, "the close reason is not UTF-8"
                ) from None
        return opcode, payload

    def _text(self) -> str:
        data = b"".join(self._parts)
        self._parts, self._size, self._started = [], 0, False
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            raise ProtocolError(CloseCode.INVALID_DATA, "text messages must be UTF-8") from None

    def _exact(self, size: int) -> bytes | None:
        """Exactly ``size`` bytes, or ``None`` if the stream ends first."""
        data = self._stream.read(size) if size else b""
        return data if len(data) == size else None


# --------------------------------------------------------------------- connections


class _Stalled(Exception):
    """A write made no progress for the stall timeout."""


class WebSocket:
    """One accepted connection: see the module docs.

    ``stream`` is the connection's buffered input, positioned after the
    handshake (it may already hold bytes of the first frame); ``sock`` is
    the connection's socket, in blocking mode. Call :meth:`start` once, then
    :meth:`receive` until it returns ``None``, then :meth:`finish`, all on
    the same thread. :meth:`send`, :meth:`publish`, :meth:`close` and
    :meth:`abort` may be called from any thread.
    """

    def __init__(
        self,
        stream: Stream,
        sock: socket.socket,
        *,
        remote: str = "",
        stall: float = STALL_TIMEOUT,
        linger: float = LINGER,
    ) -> None:
        self.remote = remote
        """The client's ``ip:port``."""
        self._stream = stream
        self._sock = sock
        self._reader = FrameReader(stream)
        self._stall = stall
        self._linger = linger
        self._ready = threading.Condition()
        self._controls: deque[Control] = deque()
        self._replies: deque[str] = deque(maxlen=MAX_REPLIES)
        self._slots: dict[str, str | None] = {}
        self._close_frame: bytes | None = None
        self._aborted = False
        self._finished = threading.Event()
        self._writer = threading.Thread(target=self._write_loop, name=f"ws {remote}", daemon=True)

    @property
    def closing(self) -> bool:
        """True once a close frame was queued or the connection aborted."""
        return self._close_frame is not None or self._aborted

    def start(self) -> None:
        """Start the writer thread."""
        self._writer.start()

    # ------------------------------------------------------------ input

    def receive(self) -> str | None:
        """The next text message; ``None`` once the connection is closing.
        Answers pings, ignores pongs, and answers a close frame or a
        protocol error with a close frame."""
        while not self.closing:
            try:
                message = self._reader.read()
            except ProtocolError as error:
                self.close(error.code)
                return None
            except OSError:
                message = None
            if message is None:  # the client went away without a close frame
                self.abort()
                return None
            if self.closing:
                return None
            if isinstance(message, str):
                return message
            opcode, payload = message
            if opcode == Opcode.PING:
                with self._ready:
                    self._controls.append((Opcode.PONG, payload))
                    self._ready.notify()
            elif opcode == Opcode.CLOSE:
                self._close(payload[:2])  # echo the client's code
                return None
        return None

    def finish(self) -> None:
        """After :meth:`receive` returned ``None``: read out what the client
        still sends until it closes (bounded by the writer's linger), then
        wait for the writer thread to end."""
        while True:
            try:
                if not self._stream.read1(65536):
                    break
            except (OSError, ValueError):
                break
        self._finished.set()
        self.abort()
        if self._writer.ident is not None:
            self._writer.join()

    # ------------------------------------------------------------ output

    def send(self, text: str) -> None:
        """Queue a text message (past :data:`MAX_REPLIES` the oldest go)."""
        with self._ready:
            if not self.closing:
                self._replies.append(text)
                self._ready.notify()

    def publish(self, slot: str, text: str) -> None:
        """Make ``text`` the slot's message, replacing one not yet sent."""
        with self._ready:
            if not self.closing:
                self._slots[slot] = text
                self._ready.notify()

    def close(self, code: int = CloseCode.NORMAL) -> None:
        """Start the closing handshake: the close frame goes next, and
        nothing queued after it. Idempotent."""
        self._close(code.to_bytes(2, "big"))

    def _close(self, payload: bytes) -> None:
        with self._ready:
            if not self.closing:
                self._close_frame = encode_frame(Opcode.CLOSE, payload)
                self._ready.notify()

    def abort(self) -> None:
        """Stop at once: no more frames, and both directions of the socket
        shut, which wakes a blocked read or write. Idempotent."""
        with self._ready:
            self._aborted = True
            self._ready.notify()
        with contextlib.suppress(OSError):  # already shut, or never connected
            self._sock.shutdown(socket.SHUT_RDWR)

    def _next(self) -> tuple[bytes, bool] | None:
        """The next frame to write, and whether it is the close frame;
        ``None`` once aborted. Blocks until there is one."""
        with self._ready:
            while not self._aborted:
                if self._controls:
                    opcode, payload = self._controls.popleft()
                    return encode_frame(opcode, payload), False
                if self._close_frame is not None:
                    return self._close_frame, True
                if self._replies:
                    return encode_frame(Opcode.TEXT, self._replies.popleft().encode()), False
                for slot, text in self._slots.items():
                    if text is not None:
                        self._slots[slot] = None
                        return encode_frame(Opcode.TEXT, text.encode()), False
                self._ready.wait()
            return None

    def _write_loop(self) -> None:
        try:
            while (frame := self._next()) is not None:
                data, last = frame
                self._write(data)
                if last:
                    self._sock.shutdown(socket.SHUT_WR)
                    self._finished.wait(self._linger)
                    break
        except (OSError, _Stalled):
            pass
        self.abort()

    def _write(self, data: bytes) -> None:
        """Write all of ``data``; raises :class:`_Stalled` after ``stall``
        seconds without progress. The socket stays in blocking mode for the
        reader: each send is non-blocking by its flag."""
        view = memoryview(data)
        deadline = time.monotonic() + self._stall
        while view:
            try:
                sent = self._sock.send(view, socket.MSG_DONTWAIT)
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._aborted:
                    raise _Stalled from None
                select.select([], [self._sock], [], remaining)
                continue
            view = view[sent:]
            deadline = time.monotonic() + self._stall
