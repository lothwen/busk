"""Rate limits for remote inputs (phase-7-plan decision 19, §5.17).

A phone or an OSC app on the network can send far more than a performer
does: a script in a loop, a fader dragged by a buggy client. Each web client
and each OSC surface gets a :class:`TokenBucket`:

==============  ===================  =============================================
Input           Rate, burst          What is dropped
==============  ===================  =============================================
web client      :data:`WEB_RATE`,    any message but a button release
                :data:`WEB_BURST`    (``PLAYBACK_BUTTON`` or ``FLASH`` with
                                     ``down: false``), so a held flash cannot stick
OSC surface     :data:`OSC_RATE`,    any message with a value other than 0 (a
                :data:`OSC_BURST`    message of zeros may be a button's release)
==============  ===================  =============================================

The bursts are twice what the phone page sends at most, so a person using
it never meets the limit. MIDI is not limited: it is local hardware.

The excess is dropped and counted, and reported at most once every
:data:`REPORT_S` (:meth:`TokenBucket.report`): the web client gets an
``error`` (``rate limit: 37 commands dropped``), OSC drops are printed on
stderr. Commands that get through can still come in a flood (many clients);
the engine applies at most :data:`~busk.commands.bus.MAX_DRAIN` queued items
per tick, so even then one tick cannot grow arbitrarily long.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Final

WEB_RATE: Final = 120.0
"""Commands per second a web client may send."""

WEB_BURST: Final = 240.0
"""How many commands a web client may send at once, after a quiet spell."""

OSC_RATE: Final = 200.0
"""Messages per second an OSC surface takes."""

OSC_BURST: Final = 400.0
"""How many messages an OSC surface takes at once, after a quiet spell."""

REPORT_S: Final = 1.0
"""Seconds between two reports of dropped commands, at the most."""


class TokenBucket:
    """A token bucket: :attr:`rate` tokens a second, at most :attr:`burst`
    in the bucket, which starts full. Each command takes one; a command that
    finds the bucket empty is dropped and counted in :attr:`dropped`.

    Not thread-safe: each bucket belongs to one receiving thread.
    """

    def __init__(self, rate: float, burst: float, clock: Callable[[], float]) -> None:
        """``clock`` is any monotonic time in seconds."""
        self.rate = rate
        self.burst = burst
        self._clock = clock
        self._tokens = burst
        self._at = clock()  # when _tokens was last brought up to date
        self._reported = -math.inf  # when report last returned drops
        self.dropped = 0
        """Commands dropped since the last report."""

    def take(self) -> bool:
        """Take a token for one command: ``True`` if it may go through,
        ``False`` (and counted) if it is dropped."""
        now = self._clock()
        self._tokens = min(self.burst, self._tokens + (now - self._at) * self.rate)
        self._at = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        self.dropped += 1
        return False

    def report(self) -> int:
        """The number of drops to report now: :attr:`dropped`, reset to 0, if
        there are any and :data:`REPORT_S` has passed since the last report;
        otherwise 0, and the drops wait for a later report."""
        now = self._clock()
        if not self.dropped or now - self._reported < REPORT_S:
            return 0
        dropped, self.dropped, self._reported = self.dropped, 0, now
        return dropped
