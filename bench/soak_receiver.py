"""The soak's receiver process (phase-7-plan §5.25, decision 23).

It stands at the far end of the soak show's three routes and writes what it
sees as JSON lines to ``--out``:

* **sACN**: a UDP socket on ``127.0.0.1:5568`` (the route sends unicast
  there);
* **Art-Net**: a UDP socket on ``127.0.0.2:6454`` with ``SO_REUSEADDR``, as
  ``tests/test_artnet_discovery.py`` binds it;
* **DMX-USB**: the master side of a pseudo-terminal behind the route's port
  symlink (:class:`dmx_widget.Widget`). The harness unplugs and replugs it
  by writing ``unplug`` and ``replug`` lines on this process's stdin.

UDP packets carry the kernel's receive time (``SO_TIMESTAMPNS``), so a busy
receiver never makes a gap look longer than it was. The pseudo-terminal has
no such timestamps; its messages are timed when they are read. Every time is
wall-clock seconds (``time.time()``, the clock ``SO_TIMESTAMPNS`` uses), so
the harness can line them up with the root's ``--stats`` lines.

The packets are parsed by the tests' independent parsers
(:mod:`sacn_receiver`, :mod:`artnet_node`, :mod:`dmx_widget`), so a layout
mistake in the sender fails here. Each route is a :class:`Track`, which
writes an event for

* a gap longer than :data:`GAP_S` (two output cycles) between packets:
  ``{"event": "gap", "route", "t0", "t1", "changed"}``, where ``changed``
  says whether the packet after the gap carried new data (a keep-alive
  repeats the old data). The harness decides which gaps are drops: outside
  engine stalls every one is; during a stall only those longer than the
  protocol's keep-alive interval plus 250 ms;
* a missing sequence number (sACN, Art-Net): ``{"event": "sequence",
  "route", "t", "expected", "got"}``;
* a packet that does not parse: ``{"event": "bad", "route", "t", "error"}``;

and every :data:`COUNT_S` a ``count`` line with each route's packets,
changes and last packet time. ``unplug`` and ``replug`` lines record when
the harness asked for them, and ``first`` the first DMX-USB message after a
replug. It ends on ``quit`` or the end of its stdin.

Run by ``bench/soak.py``: ``python bench/soak_receiver.py --out FILE
--pty LINK``.
"""

from __future__ import annotations

import argparse
import json
import os
import selectors
import socket
import struct
import sys
import time
from pathlib import Path
from typing import Any, TextIO

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from artnet_node import parse_dmx  # noqa: E402
from dmx_widget import Widget  # noqa: E402
from sacn_receiver import parse  # noqa: E402

OUTPUT_HZ = 44.0
"""The output scheduler's cycle rate (``busk.output.scheduler.OUTPUT_HZ``)."""

GAP_S = 2 / OUTPUT_HZ
"""A gap longer than two output cycles (45.5 ms) is written down (decision 23)."""

COUNT_S = 10.0
"""How often a ``count`` line is written."""

SACN_ADDRESS = ("127.0.0.1", 5568)
ARTNET_ADDRESS = ("127.0.0.2", 6454)

SO_TIMESTAMPNS = 35
"""Linux's ``SO_TIMESTAMPNS`` (``SO_TIMESTAMPNS_OLD``; also the control
message type). Python's :mod:`socket` does not export it."""

TIMESPEC = struct.Struct("qq")
"""A 64-bit ``struct timespec``: seconds and nanoseconds."""

ENTTEC_START, ENTTEC_END, SEND_DMX = 0x7E, 0xE7, 6


class Events:
    """The ``--out`` file: one JSON object per line, flushed at once."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def write(self, event: str, **fields: Any) -> None:
        self._stream.write(json.dumps({"event": event, **fields}) + "\n")
        self._stream.flush()


class Track:
    """What one route has delivered: packet and change counts, the last
    packet's time, sequence number and data, and the events of gaps and
    missing sequence numbers. ``sequence`` is the rule for the next number
    (``None``: the protocol has none)."""

    def __init__(self, name: str, events: Events, sequence: str | None) -> None:
        self.name = name
        self._events = events
        self._sequence = sequence
        self.packets = 0
        self.changes = 0
        self.lastTime: float | None = None
        self._lastSequence: int | None = None
        self._lastData: bytes | None = None

    def packet(self, at: float, data: bytes, sequence: int | None = None) -> None:
        """Count a packet received at ``at`` and write its events."""
        changed = data != self._lastData
        if self.lastTime is not None and at - self.lastTime > GAP_S:
            self._events.write("gap", route=self.name, t0=self.lastTime, t1=at, changed=changed)
        if sequence is not None and self._lastSequence is not None:
            expected = self._next(self._lastSequence)
            if sequence != expected:
                self._events.write(
                    "sequence", route=self.name, t=at, expected=expected, got=sequence
                )
        self.packets += 1
        self.changes += changed
        self.lastTime = at
        self._lastData = data
        if sequence is not None:
            self._lastSequence = sequence

    def restart(self) -> None:
        """Forget the last packet (an unplugged DMX-USB widget): the next
        message starts a new stream with no gap before it."""
        self.lastTime = None
        self._lastData = None

    def count(self) -> dict[str, Any]:
        return {"packets": self.packets, "changes": self.changes, "last": self.lastTime}

    def _next(self, previous: int) -> int:
        if self._sequence == "sacn":
            return (previous + 1) % 256  # 0, 1, …, 255, 0
        return previous % 255 + 1  # Art-Net: 1, 2, …, 255, 1 (0 would mean "no sequence")


def udp_socket(address: tuple[str, int]) -> socket.socket:
    """A non-blocking UDP socket bound to ``address`` with kernel receive
    timestamps and a large receive buffer."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
    sock.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMPNS, 1)
    sock.bind(address)
    sock.setblocking(False)
    return sock


def receive(sock: socket.socket) -> list[tuple[float, bytes]]:
    """Every waiting datagram with its kernel receive time."""
    found: list[tuple[float, bytes]] = []
    while True:
        try:
            data, ancillary, _flags, _address = sock.recvmsg(2048, socket.CMSG_SPACE(TIMESPEC.size))
        except BlockingIOError:
            return found
        at = time.time()  # only if the kernel gave no timestamp
        for level, kind, payload in ancillary:
            if level == socket.SOL_SOCKET and kind == SO_TIMESTAMPNS:
                seconds, nanoseconds = TIMESPEC.unpack_from(payload)
                at = seconds + nanoseconds / 1e9
        found.append((at, data))


class EnttecStream:
    """Splits what a widget reads into Enttec messages, across reads."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> tuple[list[tuple[int, bytes]], int]:
        """The whole messages ``(label, data)`` now in the buffer, and how
        many bytes were skipped to find a message start."""
        self._buffer += chunk
        found: list[tuple[int, bytes]] = []
        skipped = 0
        while self._buffer:
            if self._buffer[0] != ENTTEC_START:
                start = self._buffer.find(ENTTEC_START)
                cut = len(self._buffer) if start < 0 else start
                del self._buffer[:cut]
                skipped += cut
                continue
            if len(self._buffer) < 4:
                break
            size = self._buffer[2] | self._buffer[3] << 8
            end = 4 + size
            if len(self._buffer) <= end:
                break
            if self._buffer[end] != ENTTEC_END:  # not a message: look for the next start
                del self._buffer[:1]
                skipped += 1
                continue
            found.append((self._buffer[1], bytes(self._buffer[4:end])))
            del self._buffer[: end + 1]
        return found, skipped

    def clear(self) -> None:
        self._buffer.clear()


class Receiver:
    """The selector loop over the two sockets, the widget and stdin."""

    def __init__(self, events: Events, link: Path) -> None:
        self._events = events
        self._link = link
        self._selector = selectors.DefaultSelector()
        self.tracks = {
            "sacn": Track("sacn", events, "sacn"),
            "artnet": Track("artnet", events, "artnet"),
            "dmxusb": Track("dmxusb", events, None),
        }
        self._sacn = udp_socket(SACN_ADDRESS)
        self._artnet = udp_socket(ARTNET_ADDRESS)
        self._selector.register(self._sacn, selectors.EVENT_READ, self._on_sacn)
        self._selector.register(self._artnet, selectors.EVENT_READ, self._on_artnet)
        os.set_blocking(sys.stdin.fileno(), False)
        self._selector.register(sys.stdin.fileno(), selectors.EVENT_READ, self._on_stdin)
        self._stdin = b""
        self._enttec = EnttecStream()
        self._widget: Widget | None = None
        self._awaitFirst = False  # a replugged widget has not had a message yet
        self._plug()
        self._running = True

    def run(self) -> None:
        """Receive until ``quit`` or the end of stdin, with ``count`` lines."""
        self._events.write("ready", t=time.time(), pty=str(self._link))
        count_due = time.monotonic() + COUNT_S
        while self._running:
            for key, _mask in self._selector.select(timeout=0.5):
                key.data()
            if time.monotonic() >= count_due:
                self._count()
                count_due += COUNT_S
        self._count()

    def _count(self) -> None:
        tracks = {name: track.count() for name, track in self.tracks.items()}
        self._events.write("count", t=time.time(), routes=tracks)

    def _on_sacn(self) -> None:
        for at, data in receive(self._sacn):
            try:
                packet = parse(data)
            except ValueError as error:
                self._events.write("bad", route="sacn", t=at, error=str(error))
                continue
            if packet.terminated:
                self._events.write("terminated", route="sacn", t=at)
                continue
            self.tracks["sacn"].packet(at, packet.data, packet.sequence)

    def _on_artnet(self) -> None:
        for at, data in receive(self._artnet):
            if data[8:10] != b"\x00\x50":  # not ArtDmx (an ArtPoll, say): not a frame
                continue
            try:
                packet = parse_dmx(data)
            except ValueError as error:
                self._events.write("bad", route="artnet", t=at, error=str(error))
                continue
            self.tracks["artnet"].packet(at, packet.data, packet.sequence)

    def _on_widget(self) -> None:
        assert self._widget is not None
        chunk = self._widget.read()
        at = time.time()
        messages, skipped = self._enttec.feed(chunk)
        if skipped:
            self._events.write("bad", route="dmxusb", t=at, error=f"{skipped} stray bytes")
        for label, data in messages:
            if label != SEND_DMX:
                continue  # the parameters after an open
            if self._awaitFirst:
                self._awaitFirst = False
                self._events.write("first", route="dmxusb", t=at)
            self.tracks["dmxusb"].packet(at, data[1:])  # after the start code

    def _on_stdin(self) -> None:
        try:
            chunk = os.read(sys.stdin.fileno(), 4096)
        except BlockingIOError:
            return
        if not chunk:
            self._running = False
            return
        self._stdin += chunk
        while b"\n" in self._stdin:
            line, self._stdin = self._stdin.split(b"\n", 1)
            command = line.decode().strip()
            if command == "unplug":
                self._unplug()
            elif command == "replug":
                self._plug()
                self._awaitFirst = True
                self._events.write("replug", t=time.time())
            elif command == "quit":
                self._running = False

    def _plug(self) -> None:
        if self._widget is not None:
            return
        self._widget = Widget(self._link)
        self._enttec.clear()
        self.tracks["dmxusb"].restart()
        self._selector.register(self._widget.master, selectors.EVENT_READ, self._on_widget)

    def _unplug(self) -> None:
        if self._widget is None:
            return
        self._events.write("unplug", t=time.time())
        self._selector.unregister(self._widget.master)
        self._widget.unplug()
        self._widget = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="the events file (JSON lines)")
    parser.add_argument("--pty", type=Path, required=True, help="the DMX-USB route's port link")
    args = parser.parse_args(argv)
    with args.out.open("a", encoding="utf-8") as stream:
        Receiver(Events(stream), args.pty).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
