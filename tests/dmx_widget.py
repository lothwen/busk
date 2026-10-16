"""A pseudo-terminal that stands in for an Enttec DMX USB Pro widget
(phase-6-plan §5.16; shared by test_dmxusb.py and test_reconnect.py).

A :class:`Widget` is the master side of a pseudo-terminal: it reads what
an Enttec widget would receive. The route's port is a symlink to the slave
side, so re-pointing the link at a new pseudo-terminal is a replug, and
closing the master is an unplug. The message parser here is written from
the Enttec API document, independently of :mod:`busk.output.dmxusb`.
"""

from __future__ import annotations

import os
import termios
from pathlib import Path
from typing import Any

# Label 4 at 40 packets per second: no user bytes, break 9, mark-after-break 1, rate 40.
PARAMETERS_40 = bytes.fromhex("7e 04 05 00  00 00 09 01 28  e7")


def image(*values: int) -> bytes:
    """A 512-byte universe whose first channels hold ``values``."""
    return bytes(values) + bytes(512 - len(values))


def dmx_message(universe: bytes) -> bytes:
    """Label 6 with start code 0: length 513 is 0x0201, low byte first."""
    return bytes.fromhex("7e 06 01 02") + b"\x00" + universe + b"\xe7"


def messages(stream: bytes) -> list[tuple[int, bytes]]:
    """Split a widget's input into ``(label, data)`` messages; every byte
    must belong to a whole message."""
    found = []
    i = 0
    while i < len(stream):
        assert stream[i] == 0x7E, f"no start of message at byte {i}"
        size = stream[i + 2] | stream[i + 3] << 8
        end = i + 4 + size
        assert stream[end] == 0xE7, f"no end of message at byte {end}"
        found.append((stream[i + 1], stream[i + 4 : end]))
        i = end + 1
    return found


class Widget:
    """The far end of a pseudo-terminal, reached through ``link``."""

    def __init__(self, link: Path) -> None:
        self.master, self._slave = os.openpty()
        os.set_blocking(self.master, False)
        temporary = link.with_name(link.name + ".new")
        temporary.symlink_to(os.ttyname(self._slave))
        temporary.replace(link)  # re-points the route's port atomically
        self.plugged = True

    def read(self) -> bytes:
        """Everything written since the last read."""
        chunks = []
        while True:
            try:
                chunk = os.read(self.master, 65536)
            except BlockingIOError:
                return b"".join(chunks)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)

    def mode(self) -> list[Any]:
        """The terminal settings the sender left on the device."""
        return termios.tcgetattr(self._slave)

    def configure(self, cflags: int) -> None:
        """Set control flags on the device, as a previous program might have."""
        mode = termios.tcgetattr(self._slave)
        mode[2] |= cflags
        termios.tcsetattr(self._slave, termios.TCSANOW, mode)
        assert termios.tcgetattr(self._slave)[2] & cflags == cflags

    def unplug(self) -> None:
        """Close both sides: the device node disappears and writes fail with EIO."""
        if self.plugged:
            self.plugged = False
            os.close(self._slave)
            os.close(self.master)
