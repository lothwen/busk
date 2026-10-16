"""The soak's load process (phase-7-plan §5.25): a seeded busker on every
surface at once, at ``nice 10``.

=================  ==========================================================
Source             What
=================  ==========================================================
MIDI               :data:`MIDI_RATE` events/s on a virtual ALSA port named
                   "nanoKONTROL2": faders and knobs, button presses and
                   releases; the page buttons every :data:`PAGE_S`; blackout
                   on and, :data:`BLACKOUT_HOLD_S` later, off every
                   :data:`BLACKOUT_S`. A virtual input of the same name takes
                   the LED feedback, which is counted.
OSC                :data:`OSC_RATE` messages/s to the soak's OSC surface
                   (faders 1–8 and the "Wash level" master).
Phone              :data:`PHONE_RATE` ``SET_FADER``/s and a button press
                   every :data:`PHONE_BUTTON_S` over the web surface's
                   WebSocket; a :data:`FLOOD_S` flood of :data:`FLOOD_RATE`/s
                   every :data:`FLOOD_EVERY_S` (the rate limit's test, the
                   first :data:`FLOOD_FIRST_S` in); a reconnect every
                   :data:`RECONNECT_S`. A console restart takes the web
                   server down for a moment: the phone reconnects.
Console stdin      a programmer command every :data:`PROGRAMMER_S`, a show
                   edit every :data:`EDIT_S` (``record cue … merge``,
                   ``record preset … merge``, ``cue … time``, ``undo``,
                   ``redo``, a fixture repatched and back), a master or
                   ``tap`` every :data:`MASTER_S` and an invalid command
                   every :data:`INVALID_S`, counted.
=================  ==========================================================

The load never stops the Circle (playback 11): decision 23 needs universe 1
to change every output cycle, so knob 4 (its fader), the FX size master,
track ◀ (its on/off button) and marker SET (``release all``) are left alone,
and "Speed 1" stays above a quarter.

Each source runs on its own thread with its own :class:`random.Random`
seeded from ``--seed``, so a run's load is reproducible. The counts go to
``--out`` (JSON, replaced every :data:`COUNTS_S` and at the end). The process
ends on ``SIGTERM``.

Run by ``bench/soak.py``: ``python bench/soak_load.py --out FILE --seed S
--stdin-fd N --osc-port P --web-port P --web-key K [--no-midi]``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import random
import signal
import socket
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from busk.io.osc import encode  # noqa: E402
from ws_client import WsClient  # noqa: E402

MIDI_RATE = 100.0
OSC_RATE = 60.0
PHONE_RATE = 60.0
PHONE_BUTTON_S = 2.0
FLOOD_RATE = 1000.0
FLOOD_S = 5.0
FLOOD_FIRST_S = 300.0
FLOOD_EVERY_S = 3600.0
RECONNECT_S = 300.0
PAGE_S = 20.0
BLACKOUT_S = 600.0
BLACKOUT_FIRST_S = 120.0
BLACKOUT_HOLD_S = 5.0
PROGRAMMER_S = 1.0
EDIT_S = 10.0
MASTER_S = 5.0
INVALID_S = 60.0
COUNTS_S = 10.0

DEVICE = "nanoKONTROL2"
"""The virtual ALSA port's name: the show's MIDI surface matches it."""

FADER_CCS = [0, 1, 2, 3, 4, 5, 6, 7, 16, 17, 20, 21, 23]
"""Faders 1–8, knobs 1, 2, 5 and 6, and knob 8 (the grand master)."""

SPEED_CC = 18
"""Knob 3, "Speed 1": kept at :data:`SPEED_LOWEST` or more."""

SPEED_LOWEST = 32

BUTTON_CCS = [*range(32, 40), *range(48, 56), *range(64, 72), 41, 43, 44, 45, 46, 59]
"""S, M and R of slots 1–8, the transport buttons (the Song and the Chase),
cycle (tap) and track ▶ (the Pulse)."""

PAGE_CCS = (62, 61)
"""Marker ▶ and ◀: the next page, then back."""

BLACKOUT_CC = 42

OSC_PATHS = [*(f"/soak/fader/{n}" for n in range(1, 9)), "/soak/master"]
"""The OSC surface's bindings (``bench/soak.py`` writes them)."""

PROGRAMMER = [
    "sel group 2",
    "set intensity {percent}%",
    "preset color {preset}",
    "sel fixture 301",
    "set color {r} {g} {b}",
    "fade {fade}",
    "clear",
]
"""The programmer commands, one a second, in this order."""

EDITS = [
    ["sel group 2", "set intensity {percent}%", "record cue 1/1 merge"],
    ["sel group 2", "set color {r} {g} {b}", "record preset color 4 merge"],
    ["cue 1/1 time {fade}"],
    ["undo", "redo"],
    ["fixture 201 patch 1.100", "fixture 201 patch 1.33"],
]
"""The show edits, one every :data:`EDIT_S`, in this order. They leave a
selection for the programmer commands, and ``redo`` follows ``undo`` at once:
any programmer change in between would clear the redo history."""

MASTERS = ['master "Wash level" {level}', "gm {gm}", "tap"]
"""The master commands, one every :data:`MASTER_S`, in this order."""

INVALID = ["frobnicate", "fixture 999 patch 1.1"]
"""Commands that fail, one every :data:`INVALID_S`: each prints one ``error:`` line."""


class Load:
    """The threads and their counters (see the module docs)."""

    def __init__(self, args: argparse.Namespace) -> None:
        self._args = args
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.counts: Counter[str] = Counter()
        self.notes: list[str] = []
        self._start = time.monotonic()

    def count(self, name: str, n: int = 1) -> None:
        with self._lock:
            self.counts[name] += n

    def note(self, text: str) -> None:
        with self._lock:
            self.notes.append(text)

    def run(self) -> None:
        sources: list[Callable[[random.Random], None]] = [self._osc, self._phone, self._console]
        if self._args.midi:
            sources.append(self._midi)
        else:
            self.note("midi: off (--no-midi)")
        threads = [
            threading.Thread(target=self._guard, args=(source, offset), daemon=True)
            for offset, source in enumerate(sources)
        ]
        for thread in threads:
            thread.start()
        while not self._stop.wait(COUNTS_S):
            self._write()
        for thread in threads:
            thread.join(5.0)
        self._write()

    def stop(self) -> None:
        self._stop.set()

    def _guard(self, source: Callable[[random.Random], None], offset: int) -> None:
        """Run ``source`` with its own seeded generator; note an exception."""
        try:
            source(random.Random(self._args.seed * 100 + offset))
        except Exception as error:  # a source that dies is a finding, not a crash
            self.note(f"{source.__name__}: {type(error).__name__}: {error}")
            self.count(f"{source.__name__.lstrip('_')}Died")

    def _write(self) -> None:
        with self._lock:
            data = {
                "seconds": time.monotonic() - self._start,
                "counts": dict(self.counts),
                "notes": list(self.notes),
            }
        temporary = self._args.out.with_name(self._args.out.name + ".new")
        temporary.write_text(json.dumps(data, indent=1))
        temporary.replace(self._args.out)

    def _elapsed(self) -> float:
        return time.monotonic() - self._start

    def _paced(self, rate: float) -> Callable[[], bool]:
        """A pacer for ``rate`` events a second: each call sleeps until the
        next event is due; ``False`` once the load stops."""
        period = 1.0 / rate
        due = time.monotonic()

        def wait() -> bool:
            nonlocal due
            due += period
            delay = due - time.monotonic()
            if delay < -1.0:  # far behind (a stopped machine): do not catch up in a burst
                due = time.monotonic()
            return not self._stop.wait(max(0.0, delay))

        return wait

    # ------------------------------------------------------------------ MIDI

    def _midi(self, rng: random.Random) -> None:
        import mido

        feedback = mido.open_input(
            DEVICE, virtual=True, callback=lambda _m: self.count("midiFeedback")
        )
        device = mido.open_output(DEVICE, virtual=True)
        levels = {cc: rng.randrange(128) for cc in [*FADER_CCS, SPEED_CC]}
        held: list[int] = []  # buttons pressed and not yet released
        page_due, page_turn = PAGE_S, 0
        blackout_due, blackout_on = BLACKOUT_FIRST_S, False

        def send(control: int, value: int) -> None:
            device.send(mido.Message("control_change", channel=0, control=control, value=value))
            self.count("midiEvents")

        wait = self._paced(MIDI_RATE)
        try:
            while wait():
                now = self._elapsed()
                if now >= page_due:  # a press and a release of marker ▶ or ◀
                    page_due += PAGE_S
                    control = PAGE_CCS[page_turn % 2]
                    page_turn += 1
                    send(control, 127)
                    send(control, 0)
                    self.count("midiPages")
                    continue
                if now >= blackout_due:  # ■ toggles the blackout
                    blackout_on = not blackout_on
                    blackout_due += BLACKOUT_HOLD_S if blackout_on else BLACKOUT_S - BLACKOUT_HOLD_S
                    send(BLACKOUT_CC, 127)
                    send(BLACKOUT_CC, 0)
                    self.count("midiBlackouts")
                    continue
                if held and (len(held) > 3 or rng.random() < 0.15):
                    send(held.pop(rng.randrange(len(held))), 0)
                elif rng.random() < 0.1:
                    button = rng.choice(BUTTON_CCS)
                    if button not in held:
                        held.append(button)
                        send(button, 127)
                else:
                    control = rng.choice([*FADER_CCS, SPEED_CC])
                    lowest = SPEED_LOWEST if control == SPEED_CC else 0
                    level = levels[control] + rng.randint(-12, 12)
                    levels[control] = min(127, max(lowest, level))
                    send(control, levels[control])
            for button in held:
                send(button, 0)
        finally:
            device.close()
            feedback.close()

    # ------------------------------------------------------------------- OSC

    def _osc(self, rng: random.Random) -> None:
        address = ("127.0.0.1", self._args.osc_port)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            wait = self._paced(OSC_RATE)
            while wait():
                sock.sendto(encode(rng.choice(OSC_PATHS), rng.random()), address)
                self.count("oscMessages")

    # ----------------------------------------------------------------- phone

    def _phone(self, rng: random.Random) -> None:
        ident = 0
        flood_due = FLOOD_FIRST_S
        while not self._stop.is_set():
            client = self._connect()
            if client is None:
                return
            reader = threading.Thread(target=self._read_phone, args=(client,), daemon=True)
            reader.start()
            connected = self._elapsed()
            button_due = connected + PHONE_BUTTON_S
            wait = self._paced(PHONE_RATE)
            try:
                while wait() and self._elapsed() - connected < RECONNECT_S:
                    now = self._elapsed()
                    if now >= flood_due:
                        flood_due += FLOOD_EVERY_S
                        ident = self._flood(client, rng, ident)
                        continue
                    ident += 1
                    if now >= button_due:
                        button_due += PHONE_BUTTON_S
                        slot = rng.randrange(8)
                        for down in (True, False):
                            command = {"type": "PLAYBACK_BUTTON", "slot": slot, "button": 0}
                            send_command(client, ident, {**command, "down": down})
                        self.count("phoneButtons")
                        continue
                    send_command(client, ident, fader_command(rng))
                    self.count("phoneFaders")
            except OSError:
                self.count("phoneDisconnects")  # the console restarted: connect again
            with contextlib.suppress(OSError):
                client.close()
            reader.join(2.0)
            self.count("phoneReconnects")

    def _connect(self) -> WsClient | None:
        """A phone connected to the web surface (retried every 0.5 s while
        the console restarts); ``None`` once the load stops."""
        while not self._stop.is_set():
            try:
                return WsClient(self._args.web_port, self._args.web_key)
            except (OSError, AssertionError):
                self.count("phoneConnectFailures")
                self._stop.wait(0.5)
        return None

    def _read_phone(self, client: WsClient) -> None:
        """Read and count what the server sends until the connection ends."""
        while True:
            try:
                text = client.recv_text()
            except TimeoutError:
                continue  # a quiet server (no new state): keep reading
            except (OSError, EOFError, AssertionError, ValueError):
                return
            message = json.loads(text)
            if message.get("type") == "error":
                self.count("phoneRateLimited" if message.get("id") is None else "phoneErrors")
            else:
                self.count("phoneStates")

    def _flood(self, client: WsClient, rng: random.Random, ident: int) -> int:
        """:data:`FLOOD_S` of :data:`FLOOD_RATE` fader moves a second."""
        end = self._elapsed() + FLOOD_S
        wait = self._paced(FLOOD_RATE)
        while wait() and self._elapsed() < end:
            ident += 1
            send_command(client, ident, fader_command(rng))
            self.count("phoneFlood")
        self.count("phoneFloods")
        return ident

    # --------------------------------------------------------------- console

    def _console(self, rng: random.Random) -> None:
        fd = self._args.stdin_fd

        def write(line: str) -> None:
            os.write(fd, (line + "\n").encode())  # one write per line: atomic below PIPE_BUF
            self.count("consoleLines")

        turn = Counter[str]()
        due = {"programmer": PROGRAMMER_S, "edit": EDIT_S, "master": MASTER_S, "invalid": INVALID_S}
        period = {
            "programmer": PROGRAMMER_S,
            "edit": EDIT_S,
            "master": MASTER_S,
            "invalid": INVALID_S,
        }
        try:
            while not self._stop.wait(0.05):
                now = self._elapsed()
                for kind in due:
                    if now < due[kind]:
                        continue
                    due[kind] += period[kind]
                    number = turn[kind]
                    turn[kind] += 1
                    if kind == "programmer":
                        write(fill(PROGRAMMER[number % len(PROGRAMMER)], rng))
                    elif kind == "edit":
                        for line in EDITS[number % len(EDITS)]:
                            write(fill(line, rng))
                        self.count("consoleEdits")
                    elif kind == "master":
                        write(fill(MASTERS[number % len(MASTERS)], rng))
                    else:
                        write(INVALID[number % len(INVALID)])
                        self.count("consoleInvalid")
        except BrokenPipeError:
            self.note("console: stdin closed")
        finally:
            os.close(fd)


def fill(line: str, rng: random.Random) -> str:
    """``line`` with its placeholders filled from ``rng``."""
    return line.format(
        percent=rng.randrange(20, 101),
        preset=rng.randrange(1, 5),
        r=round(rng.random(), 2),
        g=round(rng.random(), 2),
        b=round(rng.random(), 2),
        fade=round(rng.uniform(0.0, 2.0), 1),
        level=round(rng.uniform(0.3, 1.0), 2),
        gm=round(rng.uniform(0.5, 1.0), 2),
    )


def fader_command(rng: random.Random) -> dict[str, Any]:
    """A phone's ``SET_FADER`` on slots 1–8 (0-based 0–7: never the Circle's 11)."""
    return {"type": "SET_FADER", "slot": rng.randrange(8), "level": round(rng.random(), 3)}


def send_command(client: WsClient, ident: int, command: dict[str, Any]) -> None:
    client.send_text(json.dumps({"id": ident, "command": command}))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="the counts file (JSON)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--stdin-fd", type=int, required=True, help="the console's stdin pipe")
    parser.add_argument("--osc-port", type=int, required=True)
    parser.add_argument("--web-port", type=int, required=True)
    parser.add_argument("--web-key", required=True)
    parser.add_argument("--no-midi", dest="midi", action="store_false")
    args = parser.parse_args(argv)
    os.nice(10)
    load = Load(args)
    signal.signal(signal.SIGTERM, lambda *_: load.stop())
    load.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
