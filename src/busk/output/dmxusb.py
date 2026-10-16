"""DMX-USB output: the Enttec DMX USB Pro protocol over a serial device
(spec §14.2, phase-6-plan §5.16).

**Interfaces.** ``enttecPro`` and ``dmxking`` routes are sent: DMXking
interfaces speak the Enttec Pro protocol. These widgets time the DMX signal
themselves; the host only hands them frames. ``enttecOpen`` (the Open DMX
USB, an FTDI chip without firmware) needs breaks timed by the host, so the
output scheduler reports those routes as ignored (:data:`UNSUPPORTED`).

**Messages.** Every message is ``0x7E, label, length (LSB, MSB), data,
0xE7`` (:func:`enttec_message`). Two labels are used:

* label 4, *Set Widget Parameters* (:func:`parameters_message`), once after
  every open: break 9 (× 10.67 µs = 96 µs), mark-after-break 1 (10.67 µs)
  and the widget's output rate, ``refreshHz`` rounded and kept within 1–40
  packets per second (:func:`output_rate`; the widget reads 0 as "as fast
  as it can");
* label 6, *Output Only Send DMX Packet*: start code 0 and all 512 slots,
  518 bytes in all. A route builds it once; a send writes only the slots.

**Transmission.** :class:`~busk.output.sacn.SendPolicy` with no repeats and
a :data:`KEEPALIVE_S` keep-alive: a changed universe is sent at once, an
unchanged one every second. The widget repeats its last frame on the cable
at its own rate, so the keep-alive only refreshes a widget that was reset.

**The device** is opened non-blocking and raw (:func:`configure`): no
echo and no output processing, so a slot of 0x0A reaches the widget as
0x0A. The line is set to 8N1 at 115200 baud, which USB widgets ignore;
other drivers set the same.

**Writes never block.** When the device takes only part of a message, the
rest is kept, and every later :meth:`EnttecSender.send` writes it first. A
frame that comes due while a remainder is still waiting is dropped and
counted in :attr:`~busk.output.driver.DriverStatus.dropped` (not an error).
The next cycle then sends the latest universe even if it did not change, so
a dropped change is late by a cycle, never lost.

**Unplug and replug** (§14.2 "reconnect automatically"). A write error
(Linux answers ``EIO``, ``ENXIO`` or ``ENODEV`` on unplug) closes the
device and marks the route failed. From then on a send tries to reopen the
port every :data:`REOPEN_S`. Once it opens, the route sends the parameters
and a full frame and reports ``ok`` again, and ``busk run`` prints "sending
again". The kernel may give a replugged interface another ``ttyUSBn``, so
a stable name such as ``/dev/serial/by-id/…`` is the port to give. A port
that is missing when the route opens is tried again by the output scheduler
(Phase 7), so a widget plugged in after ``busk run`` started is found.

**Close** sends nothing more: the widget keeps outputting its last frame,
and the DMX cable has no "stream end". A message cut short by a partial
write is finished if the device takes the rest at once, so whatever opens
the device next starts on a message boundary.
"""

from __future__ import annotations

import contextlib
import math
import os
import termios
import tty
from collections.abc import Mapping
from typing import Final, Literal

from busk.convert.dmx import UNIVERSE_SIZE
from busk.model.output import DmxUsbRoute
from busk.output.driver import DriverStatus
from busk.output.sacn import SendPolicy

START: Final = 0x7E
"""Start-of-message delimiter."""
END: Final = 0xE7
"""End-of-message delimiter."""
SET_PARAMETERS: Final = 4
"""Label 4, "Set Widget Parameters Request": break, mark-after-break, output rate."""
SEND_DMX: Final = 6
"""Label 6, "Output Only Send DMX Packet Request": a start code and the slots."""

BREAK_TIME: Final = 9
"""The DMX break, in units of 10.67 µs (96 µs)."""
MARK_AFTER_BREAK: Final = 1
"""The mark after break, in units of 10.67 µs."""
MAX_RATE: Final = 40
"""The highest output rate a widget takes, in packets per second."""

KEEPALIVE_S: Final = 1.0
"""An unchanged universe is sent again after this many seconds."""
REOPEN_S: Final = 1.0
"""After a write error, the port is reopened at most this often."""

DEVICES: Final[Mapping[str, str]] = {"enttecPro": "Enttec DMX USB Pro", "dmxking": "DMXking"}
"""The ``device.driver`` values sent with this protocol, and how messages name them."""
UNSUPPORTED: Final[Mapping[str, str]] = {
    "enttecOpen": "Open DMX USB needs host-timed breaks; use an Enttec Pro or DMXking interface",
}
"""Why a known ``device.driver`` is not sent."""

_HEADER: Final = 4  # start, label, length LSB, length MSB
_SLOTS: Final = _HEADER + 1  # the slots follow the start code
_OK: Final = (True, "")


def enttec_message(label: int, data: bytes) -> bytes:
    """Frame ``data`` as one widget message: ``0x7E, label, length (LSB,
    MSB), data, 0xE7``."""
    size = len(data)
    return bytes((START, label, size & 0xFF, size >> 8)) + data + bytes((END,))


def output_rate(refresh_hz: float) -> int:
    """The widget's output rate for a route's ``refreshHz``: rounded, at
    least 1 (0 would mean "as fast as possible") and at most :data:`MAX_RATE`."""
    return max(1, min(MAX_RATE, round(refresh_hz)))


def parameters_message(rate: int) -> bytes:
    """Label 4: no user configuration bytes, then break, mark-after-break
    and the output rate."""
    return enttec_message(SET_PARAMETERS, bytes((0, 0, BREAK_TIME, MARK_AFTER_BREAK, rate)))


def configure(fd: int) -> None:
    """Put the serial device ``fd`` in raw mode, 8N1 at 115200 baud, with no
    flow control and the modem lines ignored. Raises ``termios.error`` if
    ``fd`` is not a terminal device."""
    mode = termios.tcgetattr(fd)
    tty.cfmakeraw(mode)
    mode[tty.CFLAG] &= ~(termios.CSTOPB | termios.CRTSCTS)
    mode[tty.CFLAG] |= termios.CLOCAL | termios.CREAD
    mode[tty.ISPEED] = mode[tty.OSPEED] = termios.B115200
    termios.tcsetattr(fd, termios.TCSANOW, mode)


class EnttecSender:
    """Sends one show universe to one Enttec Pro-compatible widget; an
    :class:`~busk.output.driver.OutputDriver` (see the module docs).

    Threads: :meth:`open` runs on the main thread before the output thread
    starts (or on the output thread, for a route added by a live edit);
    :meth:`send` and :meth:`close` run on the output thread; :meth:`status`
    may be called from any thread. As in :class:`~busk.output.sacn.SacnSender`,
    the immutable ``(ok, detail)`` pair is replaced only when it changes and
    the counters are plain ints.
    """

    def __init__(self, route: DmxUsbRoute) -> None:
        """``route.device.driver`` must be one of :data:`DEVICES`."""
        self._port = route["device"]["port"]
        self._device = DEVICES[route["device"]["driver"]]
        self._rate = output_rate(route["refreshHz"])
        self._parameters = parameters_message(self._rate)
        self._frame = bytearray(enttec_message(SEND_DMX, bytes(1 + UNIVERSE_SIZE)))
        self._slots = memoryview(self._frame)[_SLOTS : _SLOTS + UNIVERSE_SIZE]
        self._policy = SendPolicy(repeats=0, keepalive=KEEPALIVE_S)
        self._fd: int | None = None  # None until opened, after a failure, and once closed
        self._pending = b""  # the unwritten end of the last message
        self._owed = False  # a frame was dropped: send the next one even if unchanged
        self._reopen_at = math.inf  # when send may reopen; inf until a write fails
        self._state: tuple[bool, str] = (False, "not open")
        self._packets = 0
        self._errors = 0
        self._dropped = 0

    @property
    def protocol(self) -> Literal["dmxUsb"]:
        return "dmxUsb"

    @property
    def description(self) -> str:
        """The widget, its port and its output rate, e.g. ``Enttec DMX USB Pro
        on /dev/ttyUSB0 at 40 Hz``."""
        return f"{self._device} on {self._port} at {self._rate} Hz"

    def open(self) -> None:
        """Open the port and write the parameters. Call once, before the first
        :meth:`send`.

        On failure (no such device, not a serial device, a write error) the
        route stays closed, with ``ok = False`` and the reason as detail.
        Only a route that failed while sending is reopened by :meth:`send`.
        """
        self._connect()

    def send(self, data: bytes, changed: bool, now: float) -> None:
        """Finish any partly written message, then write the frame ``data``
        (512 bytes) if the send policy says one is due.

        While the route is failed, try to reopen the port every
        :data:`REOPEN_S`; once it opens, a full frame follows the parameters.
        Does nothing on a route that never opened or was closed.
        """
        if self._fd is None:
            if now < self._reopen_at:
                return
            self._reopen_at = now + REOPEN_S
            if not self._connect():
                return
            changed = True
        if not self._flush():
            self._reopen_at = now + REOPEN_S
            return
        if not self._policy.due(changed or self._owed, now):
            return
        if self._pending:  # the device has not taken the previous message yet
            self._dropped += 1
            self._owed = True
            return
        self._owed = False
        self._slots[:] = data
        self._pending = bytes(self._frame)
        if self._flush():
            self._packets += 1
        else:
            self._reopen_at = now + REOPEN_S

    def close(self) -> None:
        """Close the port, after one try at finishing a partly written message
        (nothing new is sent). Idempotent; a closed route never sends or
        reopens again."""
        self._reopen_at = math.inf
        fd, self._fd = self._fd, None
        if fd is None:
            return
        with contextlib.suppress(OSError):
            if self._pending:
                os.write(fd, self._pending)
        self._pending = b""
        _close(fd)

    def status(self) -> DriverStatus:
        ok, detail = self._state
        return DriverStatus(
            ok=ok, detail=detail, packets=self._packets, errors=self._errors, dropped=self._dropped
        )

    def _connect(self) -> bool:
        """Open and configure the port and write the parameters. On success
        the route is ``ok``; on failure the reason is its detail."""
        try:
            fd = os.open(self._port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError as exc:
            self._failed(exc.strerror or str(exc))
            return False
        try:
            configure(fd)
        except (OSError, termios.error) as exc:
            _close(fd)
            self._failed(f"cannot configure the serial device: {exc.args[-1]}")
            return False
        self._fd = fd
        self._pending = self._parameters
        if not self._flush():
            return False
        self._state = _OK
        return True

    def _flush(self) -> bool:
        """Write as much of the pending message as the device takes now.

        Returns ``False`` if the write failed: the error is counted, the
        port closed and the route marked failed.
        """
        if not self._pending:
            return True
        assert self._fd is not None
        try:
            written = os.write(self._fd, self._pending)
        except BlockingIOError:  # the device's buffer is full: try again next cycle
            return True
        except OSError as exc:
            self._errors += 1
            fd, self._fd = self._fd, None
            self._pending = b""
            self._owed = False
            _close(fd)
            self._failed(exc.strerror or str(exc))
            return False
        self._pending = self._pending[written:]
        return True

    def _failed(self, reason: str) -> None:
        state = (False, f"{self._port}: {reason}")
        if state != self._state:
            self._state = state


def _close(fd: int) -> None:
    """Close a descriptor whose device may already be gone."""
    with contextlib.suppress(OSError):
        os.close(fd)
