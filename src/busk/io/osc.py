"""OSC 1.0 over UDP: the codec and one OSC control surface (phase-6-plan §5.11).

Codec
-----
:func:`decode` and :func:`encode` implement OSC 1.0 with the standard
library only. Strings are null-terminated and padded to 4 bytes; the type
tags read are ``i`` (int32), ``f`` (float32), ``d`` (float64), ``h``
(int64), ``s`` (string), ``b`` (blob), ``T`` and ``F`` (true and false), and
``N`` and ``I`` (nil and impulse, both read as ``None``). A message with any
other type tag is dropped. Bundles (``#bundle``, a time tag, elements with
their sizes) are unpacked recursively, and their time tags ignored: input
acts on arrival. A message without a type tag string (old OSC) has no
arguments. A malformed packet raises :class:`OscError`; the surface counts
and drops it.

Input (decision 14)
-------------------
An ``osc`` surface listens on ``match.port``, on every interface. A message
becomes an :class:`~busk.io.events.InputEvent` on the input address
``{kind: "osc", path}``, matched literally (no OSC patterns):

* its first argument is the value: ints and floats clamped to 0..1, ``T``
  and ``F`` as 1 and 0;
* a message without arguments (or with ``N`` or ``I`` first) is a press
  followed by a release, so a bare ``/go`` works as a button;
* a message whose first argument is a string or a blob is ignored.

**Rate limit** (Phase 7, decision 19). Each surface has a
:class:`~busk.io.ratelimit.TokenBucket` of :data:`~busk.io.ratelimit.OSC_RATE`
messages a second, bursts of :data:`~busk.io.ratelimit.OSC_BURST`. Beyond it
a message is dropped and counted in :attr:`OscSurface.dropped`, unless all
its values are 0: it may release a button, which must never stick. Drops are
printed on stderr at most once a second (``OSC s-touch: rate limit: 37
messages dropped``).

Feedback
--------
Feedback goes out of the listening socket, so its source port is the port
the client sends to; some clients answer only to that. It goes to
``match.host`` (else the address of the last message received) at
``match.feedbackPort`` (else that message's source port). Until both are
known there is nowhere to send, and :attr:`OscSurface.feedback` is
``None``. Each destination gets its own :class:`OscFeedback`, so the
feedback worker sends every value again when the destination changes.
"""

from __future__ import annotations

import math
import socket
import struct
import sys
import threading
import time
from collections.abc import Callable
from typing import Final

from busk.io.events import InputEvent
from busk.io.midi import FeedbackKind
from busk.io.ratelimit import OSC_BURST, OSC_RATE, TokenBucket
from busk.model.common import SurfaceId
from busk.model.surface import ControlSurface, InputAddress, OscInput, SurfaceMatch

type OscArg = int | float | str | bytes | bool | None
"""A decoded argument (``N`` and ``I`` are ``None``)."""

type OscMessage = tuple[str, tuple[OscArg, ...]]
"""An address and its arguments."""

RECEIVE_TIMEOUT: Final = 0.2
"""Seconds the receive thread blocks before it checks for :meth:`OscSurface.close`."""

MAX_DATAGRAM: Final = 65536
"""Bytes read per datagram: more than any UDP payload."""

MAX_DEPTH: Final = 16
"""Bundles nested deeper than this are malformed."""

BUNDLE: Final = b"#bundle\0"


class OscError(ValueError):
    """A malformed OSC packet."""


# -- codec ---------------------------------------------------------------------


def decode(packet: bytes) -> list[OscMessage]:
    """The messages of ``packet``, bundles flattened in order.

    Raises :class:`OscError` when the packet is malformed or truncated. A
    message with an unknown type tag is left out.
    """
    messages: list[OscMessage] = []
    _packet(packet, messages, 0)
    return messages


def _packet(data: bytes, messages: list[OscMessage], depth: int) -> None:
    if data.startswith(b"#bundle"):
        if depth >= MAX_DEPTH:
            raise OscError("bundles nested too deep")
        if not data.startswith(BUNDLE) or len(data) < 16:
            raise OscError("truncated bundle header")
        at = 16  # "#bundle\0" and the 8-byte time tag
        while at < len(data):
            size = _size(data, at)
            at += 4
            if size < 0 or at + size > len(data):
                raise OscError("a bundle element runs past the packet")
            _packet(data[at : at + size], messages, depth + 1)
            at += size
        return
    message = _message(data)
    if message is not None:
        messages.append(message)


def _message(data: bytes) -> OscMessage | None:
    if not data.startswith(b"/"):
        raise OscError("neither a message nor a bundle")
    address, at = _string(data, 0)
    if at == len(data):
        return address, ()  # no type tag string: no arguments
    tags, at = _string(data, at)
    if not tags.startswith(","):
        raise OscError("no type tag string")
    args: list[OscArg] = []
    for tag in tags[1:]:
        if tag == "i":
            args.append(_unpack(">i", data, at)[0])
            at += 4
        elif tag == "f":
            args.append(_unpack(">f", data, at)[0])
            at += 4
        elif tag == "d":
            args.append(_unpack(">d", data, at)[0])
            at += 8
        elif tag == "h":
            args.append(_unpack(">q", data, at)[0])
            at += 8
        elif tag == "s":
            text, at = _string(data, at)
            args.append(text)
        elif tag == "b":
            size = _size(data, at)
            end = at + 4 + size
            if size < 0 or end > len(data):
                raise OscError("a blob runs past the packet")
            args.append(data[at + 4 : end])
            at += 4 + _padded(size)
        elif tag in "TF":
            args.append(tag == "T")
        elif tag in "NI":
            args.append(None)
        else:
            return None  # unknown type: its size is unknown too
    return address, tuple(args)


def _unpack(fmt: str, data: bytes, at: int) -> tuple[int | float, ...]:
    if at + struct.calcsize(fmt) > len(data):
        raise OscError("truncated argument")
    return struct.unpack_from(fmt, data, at)


def _size(data: bytes, at: int) -> int:
    """The int32 size at ``at`` (of a bundle element or a blob)."""
    if at + 4 > len(data):
        raise OscError("truncated size")
    size: int = struct.unpack_from(">i", data, at)[0]
    return size


def _string(data: bytes, at: int) -> tuple[str, int]:
    """The OSC-string at ``at``, and where the next field starts."""
    end = data.find(b"\0", at)
    if end < 0:
        raise OscError("unterminated string")
    try:
        text = data[at:end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OscError("a string is not UTF-8") from exc
    return text, min(at + _padded(end - at + 1), len(data))


def _padded(size: int) -> int:
    """``size`` rounded up to a multiple of 4."""
    return (size + 3) & ~3


def _pad(data: bytes) -> bytes:
    return data + b"\0" * (_padded(len(data)) - len(data))


def encode(address: str, *args: OscArg) -> bytes:
    """An OSC message: bools as ``T``/``F``, ints as ``i``, floats as
    ``f``, strings as ``s``, bytes as ``b`` and ``None`` as ``N``."""
    tags = [","]
    payload: list[bytes] = []
    for arg in args:
        if isinstance(arg, bool):
            tags.append("T" if arg else "F")
        elif isinstance(arg, int):
            tags.append("i")
            payload.append(struct.pack(">i", arg))
        elif isinstance(arg, float):
            tags.append("f")
            payload.append(struct.pack(">f", arg))
        elif isinstance(arg, str):
            tags.append("s")
            payload.append(_pad(arg.encode("utf-8") + b"\0"))
        elif isinstance(arg, bytes):
            tags.append("b")
            payload.append(struct.pack(">i", len(arg)) + _pad(arg))
        else:
            tags.append("N")
    head = _pad(address.encode("utf-8") + b"\0") + _pad("".join(tags).encode("ascii") + b"\0")
    return head + b"".join(payload)


# -- input ---------------------------------------------------------------------


def values(args: tuple[OscArg, ...]) -> tuple[float, ...]:
    """The input values a message with ``args`` gives (decision 14): one,
    a press and a release, or none."""
    if not args or args[0] is None:
        return (1.0, 0.0)
    first = args[0]
    if isinstance(first, bool):
        return (1.0 if first else 0.0,)
    if isinstance(first, int | float) and not math.isnan(first):
        return (min(max(float(first), 0.0), 1.0),)
    return ()


class OscFeedback:
    """Feedback from an OSC surface's socket to one destination."""

    def __init__(self, sock: socket.socket, destination: tuple[str, int]) -> None:
        self._socket = sock
        self.destination = destination

    def send(self, address: InputAddress, kind: FeedbackKind, value: float | str) -> None:
        """Send ``value`` as the one argument of a message to the address's
        path; only ``osc`` addresses can be sent. Raises the socket's
        error, except once the surface closed."""
        if address["kind"] == "osc" and self._socket.fileno() >= 0:
            self._socket.sendto(encode(address["path"], value), self.destination)


def feedback_target(match: SurfaceMatch) -> str:
    """Where an OSC surface's feedback goes, in words: ``host:port``, or
    the sender's address or port for the part ``match`` leaves out."""
    host, port = match.get("host"), match.get("feedbackPort")
    if host is not None and port is not None:
        return f"{host}:{port}"
    if port is not None:
        return f"the sender at port {port}"
    if host is not None:
        return f"{host} at the sender's port"
    return "the sender"


class OscSurface:
    """One ``osc`` control surface: a UDP socket and its receive thread.

    ``on_event`` runs on the receive thread; an exception it raises is
    counted in :attr:`errors`. Malformed packets are counted in
    :attr:`malformed`, messages beyond the rate limit in :attr:`dropped`.
    """

    def __init__(
        self,
        surface: ControlSurface,
        on_event: Callable[[InputEvent], None],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """``clock`` times the rate limit (tests pass a fake one)."""
        self.surface = surface
        self._on_event = on_event
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._host: str | None = None  # match.host, resolved
        self.port: int | None = None
        """The port it listens on, once open."""
        self.feedback: OscFeedback | None = None
        """Where feedback goes now; ``None`` while that is not known."""
        self.malformed = 0
        self.errors = 0
        self.dropped = 0
        """Messages dropped by the rate limit."""
        self._bucket = TokenBucket(OSC_RATE, OSC_BURST, clock)

    @property
    def id(self) -> SurfaceId:
        return self.surface["id"]

    def open(self) -> str | None:
        """Listen on ``match.port`` and start the receive thread. Returns
        ``None``, or why it cannot listen."""
        match = self.surface["match"]
        port = match.get("port", 0)
        host = match.get("host")
        try:
            self._host = None if host is None else socket.gethostbyname(host)
        except OSError as exc:
            return f"cannot resolve feedback host {host!r}: {exc}"
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(("", port))
        except OSError as exc:
            sock.close()
            return f"cannot listen on udp {port}: {exc.strerror or exc}"
        sock.settimeout(RECEIVE_TIMEOUT)
        self._socket = sock
        self.port = sock.getsockname()[1]
        feedback_port = match.get("feedbackPort")
        if self._host is not None and feedback_port is not None:
            self.feedback = OscFeedback(sock, (self._host, feedback_port))
        self._thread = threading.Thread(target=self._receive, name=f"osc {self.id}", daemon=True)
        self._thread.start()
        return None

    def describe(self) -> str:
        """Where it listens and where feedback goes, for the start-up line."""
        return f"listening on udp {self.port}, feedback to {feedback_target(self.surface['match'])}"

    def _receive(self) -> None:
        sock = self._socket
        assert sock is not None
        while not self._stop.is_set():
            try:
                data, source = sock.recvfrom(MAX_DATAGRAM)
            except TimeoutError:
                continue
            except OSError:
                if self._stop.is_set():
                    break
                self.errors += 1
                self._stop.wait(RECEIVE_TIMEOUT)  # never spin on a failing socket
                continue
            self.datagram(data, source)

    def datagram(self, data: bytes, source: tuple[str, int]) -> None:
        """Handle one datagram from ``source``: follow the sender for
        feedback, then deliver its messages' events, within the rate limit
        (see the module docs)."""
        try:
            messages = decode(data)
        except OscError:
            self.malformed += 1
            return
        self._follow(source)
        for path, args in messages:
            address = OscInput(kind="osc", path=path)
            given = values(args)
            if any(given) and not self._bucket.take():
                self.dropped += 1
                if dropped := self._bucket.report():
                    noun = "message" if dropped == 1 else "messages"
                    print(
                        f"OSC {self.id}: rate limit: {dropped} {noun} dropped",
                        file=sys.stderr,
                        flush=True,
                    )
                continue
            for value in given:
                try:
                    self._on_event(InputEvent(self.id, address, value))
                except Exception:  # never out of the receive thread
                    self.errors += 1

    def _follow(self, source: tuple[str, int]) -> None:
        """Point feedback at the sender where the show leaves it open."""
        sock = self._socket
        if sock is None:
            return
        port = self.surface["match"].get("feedbackPort", source[1])
        destination = (self._host or source[0], port)
        current = self.feedback
        if current is None or current.destination != destination:
            self.feedback = OscFeedback(sock, destination)

    def close(self) -> None:
        """Stop the receive thread and close the socket. Idempotent."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join()
        sock, self._socket = self._socket, None
        if sock is not None:
            sock.close()
        self.feedback = None
