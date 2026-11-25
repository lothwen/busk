"""busk's banner: a small lighting rig that fires its cues over the busk
wordmark.

:func:`play_banner` shows it while a program starts, as ``busk`` does
before ``busk run``'s interactive prompt (:mod:`busk.launch`):

* It animates (about 2 s) only on a colour terminal, and not under CI or with
  ``BUSK_NO_ANIM=1``: elsewhere it prints the last frame straight away.
* It animates on a thread of its own, and nothing waits for it: the first
  write to the program's stdout or stderr, or to those of a child process
  that holds them (:func:`hold_output`), brings it to rest at once, its last
  frame drawn wherever the animation is, and goes on.
* Colour: 24-bit when ``COLORTERM`` says ``truecolor`` or ``24bit``, else
  xterm-256. ``NO_COLOR``, ``TERM=dumb`` or a stream that is not a terminal
  give plain characters.
* A terminal narrower than the banner gets one line instead, and an encoding
  that cannot show block characters a plain one.

:func:`banner_frames` (public) gives the animation's frames, for a frontend
to play (busk-tui's launcher), and :func:`letter_colors` the escapes that
colour each letter of ``busk`` in its gel, as the console prompt does.
Standard library only.
"""

from __future__ import annotations

import contextlib
import functools
import math
import os
import select
import shutil
import sys
import threading
import time
from collections.abc import Callable
from typing import Any, Final, Literal, NamedTuple, TextIO, cast

__all__ = [
    "DURATION",
    "HEIGHT",
    "WIDTH",
    "banner_frames",
    "child_hold",
    "color_mode",
    "hold_output",
    "letter_colors",
    "play_banner",
    "render_frame",
]

type RGB = tuple[float, float, float]
type ColorMode = Literal["truecolor", "256"]

# ---------------------------------------------------------------- palette
BG: RGB = (14, 14, 18)  # assumed dark terminal background
WHITE: RGB = (244, 241, 234)
GELS: tuple[RGB, ...] = (  # one gel per fixture / letter
    (255, 61, 139),  # magenta
    (255, 178, 30),  # amber
    (47, 224, 208),  # cyan
    (111, 134, 255),  # blue
)
RIG: RGB = (108, 108, 122)
FLOOR: RGB = (58, 58, 70)
TEXT: RGB = (154, 154, 168)
UNLIT: RGB = (34, 34, 42)  # letters before their fixture fires
LENS_OFF: RGB = (52, 46, 44)
TALLY: RGB = (255, 77, 94)
TALLY_OFF: RGB = (52, 30, 34)

# ---------------------------------------------------------------- lettering
# Bold lowercase bitmap, 7 px wide, 9 px tall (+1 px pad). Drawn with
# half-blocks so one character cell holds two vertical pixels.
_FONT = {
    "b": ["XX.....", "XX.....", "XX.....", "XXXXXX.", "XX...XX",
          "XX...XX", "XX...XX", "XX...XX", "XXXXXX."],
    "u": [".......", ".......", ".......", "XX...XX", "XX...XX",
          "XX...XX", "XX...XX", "XX...XX", ".XXXXXX"],
    "s": [".......", ".......", ".......", ".XXXXXX", "XX.....",
          ".XXXXX.", ".....XX", ".....XX", "XXXXXX."],
    "k": ["XX.....", "XX.....", "XX.....", "XX...XX", "XX..XX.",
          "XXXXX..", "XX..XX.", "XX...XX", "XX...XX"],
}  # fmt: skip
_WORD = "busk"
_LW, _GAP, _MARGIN = 7, 2, 2
WIDTH = _MARGIN * 2 + len(_WORD) * _LW + (len(_WORD) - 1) * _GAP  # 38
HEIGHT = 12
TAGLINE = "lighting console engine"

# ---------------------------------------------------------------- timeline
_FIRE_AT = [0.25 + i * 0.2 for i in range(4)]  # each fixture strikes
_LIVE_AT = 1.45
_TYPE_AT = 1.45
_TYPE_RATE = 55.0  # tagline characters per second
DURATION = _TYPE_AT + 27 / _TYPE_RATE + 0.05  # about 2 s: the tagline typed, and a beat


def _strike(s: float) -> float:
    """Lamp strike: a flash, a dip, then an eased fade to full."""
    if s < 0:
        return 0.0
    if s < 0.05:
        return 0.85
    if s < 0.11:
        return 0.2
    u = min(1.0, (s - 0.11) / 0.5)
    return 0.2 + 0.8 * (1 - (1 - u) ** 3)


def _levels(t: float) -> dict[str, float]:
    levels = {
        "static": 1.0,
        "live": 1.0 if t >= _LIVE_AT else 0.0,
        "type": (t - _TYPE_AT) * _TYPE_RATE,
    }
    for i, at in enumerate(_FIRE_AT):
        levels[f"fx{i}"] = _strike(t - at)
    return levels


# ---------------------------------------------------------------- scene
def _mix(a: RGB, b: RGB, t: float) -> RGB:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


class _Cell(NamedTuple):
    char: str
    channel: str | None  # what lights it (None: nothing)
    off: RGB  # its colour at level 0
    on: RGB  # and at level 1
    bg: RGB | None
    hide: bool  # blank while its channel is dark


_EMPTY = _Cell(" ", None, BG, BG, None, False)


@functools.cache
def _scene() -> tuple[tuple[_Cell, ...], ...]:
    """The banner's cells, each with what lights it."""
    g = [[_EMPTY] * WIDTH for _ in range(HEIGHT)]

    def put(
        x: int,
        y: int,
        char: str,
        channel: str = "static",
        off: RGB | None = None,
        *,
        on: RGB,
        bg: RGB | None = None,
        hide: bool = False,
    ) -> None:
        g[y][x] = _Cell(char, channel, on if off is None else off, on, bg, hide)

    centers = [_MARGIN + i * (_LW + _GAP) + _LW // 2 for i in range(4)]

    # truss and fixtures (always visible: the stage is dark, the rig is not)
    for x in range(WIDTH):
        put(x, 0, "━", on=RIG)
    put(0, 0, "╺", on=RIG)
    put(WIDTH - 1, 0, "╸", on=RIG)
    for i, c in enumerate(centers):
        put(c, 0, "┳", on=RIG)
        put(c - 1, 1, "▐", on=RIG)
        put(c + 1, 1, "▌", on=RIG)
        put(c, 1, "▄", f"fx{i}", LENS_OFF, on=_mix(GELS[i], WHITE, 0.55), bg=RIG)

    # wordmark, rows 5..9 (lit from above: pale top, saturated bottom)
    bitmap = [("." * _GAP).join(_FONT[ch][r] for ch in _WORD) for r in range(9)]
    bitmap.append("." * len(bitmap[0]))
    for r in range(5):
        top, bottom = bitmap[2 * r], bitmap[2 * r + 1]
        for px in range(len(top)):
            a, b = top[px] == "X", bottom[px] == "X"
            if not (a or b):
                continue
            letter = px // (_LW + _GAP)
            char = "█" if a and b else ("▀" if a else "▄")
            gel = GELS[letter]
            on = _mix(_mix(gel, WHITE, 0.6), gel, min(1.0, r / 4 * 1.1))
            put(_MARGIN + px, 5 + r, char, f"fx{letter}", UNLIT, on=on)

    # beams: rows 2..5, widening, never over a letter
    for i, c in enumerate(centers):
        cx = c + 0.5
        for y in range(2, 6):
            half = 1.5 + min(y - 2, 2)
            for x in range(int(cx - half), int(cx + half) + 1):
                dist = abs(x + 0.5 - cx) / half
                if dist > 1 or g[y][x].char != " ":
                    continue
                fade = 0.8 - 0.08 * (y - 2)
                on = _mix(BG, _mix(GELS[i], WHITE, 0.25), fade * (1 - 0.55 * dist))
                put(x, y, "▒" if dist < 0.3 else "░", f"fx{i}", BG, on=on, hide=True)

    # stage floor with a pool of light under each letter
    for x in range(WIDTH):
        put(x, 10, "▀", on=FLOOR)
    for i, c in enumerate(centers):
        cx = c + 0.5
        for x in range(c - 4, c + 5):
            d = abs(x + 0.5 - cx) / 4.5
            put(x, 10, "▀", f"fx{i}", FLOOR, on=_mix(FLOOR, GELS[i], 0.75 * (1 - d) ** 1.3))

    # tally light and tagline
    put(_MARGIN, 11, "▮", "live", TALLY_OFF, on=TALLY)
    for k, char in enumerate(" live"):
        put(_MARGIN + 1 + k, 11, char, "live", BG, on=TEXT, hide=True)
    x0 = WIDTH - _MARGIN - len(TAGLINE)
    for k, char in enumerate(TAGLINE):
        put(x0 + k, 11, char, f"type{k}", BG, on=TEXT, hide=True)
    return tuple(tuple(row) for row in g)


# ---------------------------------------------------------------- colour output
_STEPS = (0, 95, 135, 175, 215, 255)


def _byte(v: float) -> int:
    return max(0, min(255, round(v)))


def _to256(c: RGB) -> int:
    """The nearest xterm-256 colour: of the 6×6×6 cube or the grey ramp."""
    rgb = [_byte(v) for v in c]
    q = [0 if v < 48 else 1 if v < 115 else (v - 35) // 40 for v in rgb]
    cube = [_STEPS[i] for i in q]
    avg = sum(rgb) // 3
    gi = 0 if avg < 8 else 23 if avg > 238 else (avg - 8) // 10
    gray = [8 + 10 * gi] * 3

    def dist(p: list[int]) -> int:
        return sum((p[i] - rgb[i]) ** 2 for i in range(3))

    return 232 + gi if dist(gray) < dist(cube) else 16 + 36 * q[0] + 6 * q[1] + q[2]


def _sgr(c: RGB, mode: ColorMode, layer: int) -> str:
    """layer 38 = foreground, 48 = background."""
    if mode == "truecolor":
        r, g, b = (_byte(v) for v in c)
        return f"\x1b[{layer};2;{r};{g};{b}m"
    return f"\x1b[{layer};5;{_to256(c)}m"


def render_frame(t: float = DURATION, color: ColorMode | None = "truecolor") -> str:
    """The banner ``t`` seconds into its animation, as :data:`HEIGHT` lines
    (no trailing newline); ``color`` ``None`` gives plain characters."""
    levels = _levels(t)
    lines = []
    for row in _scene():
        out: list[str] = []
        cur_fg: str | None = None
        cur_bg: str | None = None
        for char, channel, off, on, bg, hide in row:
            if channel is None:
                level = 0.0
            elif channel.startswith("type"):
                level = 1.0 if levels["type"] >= int(channel[4:]) else 0.0
            else:
                level = levels[channel]
            if char == " " or (hide and level < 0.06):
                if color and cur_bg is not None:
                    out.append("\x1b[49m")
                    cur_bg = None
                out.append(" ")
                continue
            if color:
                fg = _sgr(_mix(off, on, level), color, 38)
                if fg != cur_fg:
                    out.append(fg)
                    cur_fg = fg
                bgc = _sgr(bg, color, 48) if bg else None
                if bgc != cur_bg:
                    out.append(bgc or "\x1b[49m")
                    cur_bg = bgc
            out.append(char)
        line = "".join(out)
        lines.append(line + "\x1b[0m" if color else line.rstrip())
    return "\n".join(lines)


def banner_frames(rate: float = 30.0) -> tuple[str, ...]:
    """busk's banner as the frames of its animation, ``rate`` a second, for a
    frontend to play. Each is 12 lines of 38 columns (no trailing newline),
    coloured with 24-bit ANSI escapes; the last is the banner at rest."""
    if rate <= 0:
        raise ValueError(f"rate must be positive, not {rate}")
    count = math.ceil(DURATION * rate)
    return (*(render_frame(n / rate) for n in range(count)), render_frame())


# ---------------------------------------------------------------- terminal
def color_mode(stream: TextIO) -> ColorMode | None:
    """The colours ``stream`` shows: none (``None``) where it is not a
    terminal or ``NO_COLOR`` or ``TERM=dumb`` says so; 24-bit where
    ``COLORTERM`` says ``truecolor`` or ``24bit``; else xterm-256."""
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return None
    if not stream.isatty():
        return None
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return "truecolor"
    return "256"


def _can_encode(stream: TextIO) -> bool:
    try:
        "█▀▄░▒━┳▐▌▮".encode(stream.encoding or "utf-8")
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def letter_colors(color: ColorMode) -> tuple[str, ...]:
    """The escape that colours each letter of ``busk`` in its gel, as the
    banner lights it, in ``color``."""
    return tuple(_sgr(gel, color, 38) for gel in GELS)


def _one_line(color: ColorMode | None) -> str:
    if not color:
        return f"busk - {TAGLINE}"
    word = "".join(
        f"{sgr}\x1b[1m{ch}\x1b[22m" for sgr, ch in zip(letter_colors(color), _WORD, strict=True)
    )
    return f"{word}{_sgr(TEXT, color, 38)} · {TAGLINE}\x1b[0m"


HOLD_S: Final = 1.0
"""The longest a write waits for the banner to come to rest (it takes a
frame, unless the program that plays it is gone)."""

_ENVIRONMENT: Final = "BUSK_BANNER"
"""A child process's banner pipes: ``ASK,REST``, the descriptors it writes
to, to ask the banner to come to rest, and reads, to see that it has."""

_playing: _Player | None = None


def play_banner(stream: TextIO | None = None) -> Callable[[], None]:
    """Show the banner on ``stream`` (default: stdout) while the program
    starts; return what brings it to rest.

    On a colour terminal it animates on a thread of its own, and this
    process's stdout and stderr hold their first write until it is at rest
    (see the module docs); so do child processes started with
    :func:`child_hold`. The function returned brings it to rest too, and
    waits for its thread: call it before the program ends. Elsewhere the
    banner is printed at rest, or as one line, at once, and the function
    returned does nothing."""
    global _playing
    stream = stream or sys.stdout
    color = color_mode(stream)
    if not _can_encode(stream):
        stream.write(f"busk - {TAGLINE}\n")
    elif shutil.get_terminal_size((80, 24)).columns < WIDTH:
        stream.write(_one_line(color) + "\n")
    elif color is None or os.environ.get("BUSK_NO_ANIM") or os.environ.get("CI"):
        stream.write(render_frame(DURATION, color) + "\n")
    else:
        _playing = _Player(stream, color)
        return _playing.finish
    stream.flush()
    return lambda: None


def child_hold() -> tuple[tuple[int, ...], dict[str, str] | None]:
    """For a child process that holds its output until the banner is at rest
    (it calls :func:`hold_output`): the descriptors to pass it and its
    environment; ``((), None)`` (the environment inherited) where no banner
    played."""
    if _playing is None:
        return (), None
    return (_playing.ask, _playing.rest), {
        **os.environ,
        _ENVIRONMENT: f"{_playing.ask},{_playing.rest}",
    }


def hold_output() -> None:
    """In a child process started with :func:`child_hold`: hold the first
    write to stdout or stderr until the banner is at rest, as the process
    that plays it holds its own. Elsewhere, nothing."""
    found = os.environ.pop(_ENVIRONMENT, None)
    if found is not None:
        ask, rest = (int(fd) for fd in found.split(","))
        _hold(ask, rest)


class _Player:
    """The banner animated on a thread, until it ends or until a byte comes
    on its ``ask`` pipe; then its last frame, and its ``rest`` pipe closes.
    The writing ends stay open while the process runs, so a child started
    after the banner rested finds it so at once."""

    def __init__(self, stream: TextIO, color: ColorMode) -> None:
        self.stream = stream
        self.color = color
        self.asked, self.ask = os.pipe()  # the thread reads; whoever needs the terminal writes
        self.rest, self.rested = os.pipe()  # writers wait to read its end; the thread closes it
        self.thread = threading.Thread(target=self._run, name="busk-banner", daemon=True)
        self.thread.start()
        self.release = _hold(self.ask, self.rest)

    def _run(self) -> None:
        stream = self.stream
        stream.write("\x1b[?25l")  # hide the cursor
        start = time.monotonic()
        drawn = asked = False
        try:
            while True:
                t = DURATION if asked else min(time.monotonic() - start, DURATION)
                if drawn:
                    stream.write(f"\x1b[{HEIGHT}F")  # back to the banner's top line
                stream.write(render_frame(t, self.color) + "\n")
                stream.flush()
                drawn = True
                if t >= DURATION:
                    break
                asked = bool(select.select([self.asked], [], [], 1 / 30)[0])
        finally:
            stream.write("\x1b[?25h")  # show the cursor
            stream.flush()
            os.close(self.asked)
            os.close(self.rested)  # at rest: the writes held go on

    def finish(self) -> None:
        """Bring the banner to rest, the streams as they were, and wait for
        its thread."""
        self.release()
        self.thread.join()


class _Held:
    """A stream whose first write waits for the banner to be at rest."""

    def __init__(self, stream: TextIO, wait: Callable[[], None]) -> None:
        self._stream = stream
        self._wait = wait

    def write(self, text: str) -> int:
        self._wait()
        return self._stream.write(text)

    def writelines(self, lines: list[str]) -> None:
        self._wait()
        self._stream.writelines(lines)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


def _hold(ask: int, rest: int) -> Callable[[], None]:
    """Hold this process's first write to stdout or stderr: ask the banner
    to come to rest (``ask``; it rested already if the pipe is closed) and
    wait until it has (``rest`` closes), at most :data:`HOLD_S`; then the
    streams are as they were. Returns that wait, for the first write not to
    wait for."""
    lock = threading.Lock()
    waited = False
    out, err = sys.stdout, sys.stderr

    def wait() -> None:
        nonlocal waited
        with lock:
            if waited:
                return
            with contextlib.suppress(OSError):
                os.write(ask, b"!")
            with contextlib.suppress(OSError, ValueError):
                select.select([rest], [], [], HOLD_S)
            waited = True
            if sys.stdout is held_out:
                sys.stdout = out
            if sys.stderr is held_err:
                sys.stderr = err

    held_out, held_err = cast(TextIO, _Held(out, wait)), cast(TextIO, _Held(err, wait))
    sys.stdout, sys.stderr = held_out, held_err
    return wait
