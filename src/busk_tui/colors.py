"""The TUI's colours (spec §4.1, §4.2).

The chrome uses fixed xterm-256 colours, never the terminal's theme colours
0–15, which vary per user. They are written as the hex values of those
xterm indices, so a 256-colour terminal shows them exactly, and Rich maps
them to the nearest of 16 on a 16-colour one. ``busk.tcss`` uses the same
values.

Live output colours (fixture swatches) are quantised by :func:`swatch`.
Fixture types (profile categories) and what drives a value have colours of
their own (:func:`profile_colors`, :data:`SOURCE_COLORS`).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

type ColorMode = Literal["256", "16", "truecolor"]
type RGB = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class Token:
    xterm: int
    hex: str


PALETTE: Final = {
    "bg": Token(234, "#1c1c1c"),
    "bar": Token(235, "#262626"),
    "sel": Token(236, "#303030"),
    "track": Token(237, "#3a3a3a"),
    "border": Token(239, "#4e4e4e"),
    "dim": Token(243, "#767676"),
    "mid": Token(248, "#a8a8a8"),
    "fg": Token(253, "#dadada"),
    "cyan": Token(81, "#5fd7ff"),
    "magenta": Token(206, "#ff5fd7"),
    "green": Token(113, "#87d75f"),
    "amber": Token(221, "#ffd75f"),
    "red": Token(203, "#ff5f5f"),
}
"""The spec's tokens (§4.1): name → xterm index and hex."""

BG: Final = PALETTE["bg"].hex
BAR: Final = PALETTE["bar"].hex
SEL: Final = PALETTE["sel"].hex
TRACK: Final = PALETTE["track"].hex
BORDER: Final = PALETTE["border"].hex
DIM: Final = PALETTE["dim"].hex
MID: Final = PALETTE["mid"].hex
FG: Final = PALETTE["fg"].hex
CYAN: Final = PALETTE["cyan"].hex
MAGENTA: Final = PALETTE["magenta"].hex
GREEN: Final = PALETTE["green"].hex
AMBER: Final = PALETTE["amber"].hex
RED: Final = PALETTE["red"].hex

UNLIT: Final = 236
"""The xterm colour of an unlit swatch."""

_CUBE: Final = (0, 95, 135, 175, 215, 255)

ANSI16: Final[tuple[RGB, ...]] = (
    (0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0),
    (0, 0, 238), (205, 0, 205), (0, 205, 205), (229, 229, 229),
    (127, 127, 127), (255, 0, 0), (0, 255, 0), (255, 255, 0),
    (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
)  # fmt: skip
"""xterm's 16 ANSI colours, by index."""


def xterm_rgb(index: int) -> RGB:
    """The colour of an xterm-256 index (16–255: the cube and the grey ramp)."""
    if index < 16:
        return ANSI16[index]
    if index >= 232:
        grey = 8 + 10 * (index - 232)
        return (grey, grey, grey)
    index -= 16
    return (_CUBE[index // 36], _CUBE[index // 6 % 6], _CUBE[index % 6])


def nearest_256(rgb: RGB) -> int:
    """The nearest xterm colour of the 6×6×6 cube or the 24-step grey ramp,
    whichever is closer."""
    red, green, blue = (_nearest_level(channel) for channel in rgb)
    cube = 16 + 36 * red + 6 * green + blue
    grey = 232 + min(23, max(0, round((sum(rgb) / 3 - 8) / 10)))
    return min((cube, grey), key=lambda index: _distance(xterm_rgb(index), rgb))


def nearest_16(rgb: RGB) -> int:
    """The nearest of the 16 ANSI colours, by Euclidean RGB distance."""
    return min(range(16), key=lambda index: _distance(ANSI16[index], rgb))


def displayed(color: tuple[float, float, float], intensity: float) -> RGB | None:
    """A fixture's output as a swatch shows it: its colour (0..1) at the
    displayed brightness ``0.18 + 0.82 × intensity``, so low levels stay
    visible; ``None`` (unlit) below 1.5 %."""
    if intensity < 0.015:
        return None
    level = 0.18 + 0.82 * min(1.0, intensity)
    red, green, blue = (round(max(0.0, min(1.0, c)) * level * 255) for c in color)
    return (red, green, blue)


def swatch(color: tuple[float, float, float], intensity: float, mode: ColorMode) -> str:
    """The colour of a fixture's swatch for a terminal in ``mode``, as Rich
    colour text: ``color(N)`` (256 and 16 colours) or ``#rrggbb``."""
    rgb = displayed(color, intensity)
    if rgb is None:
        return f"color({UNLIT})"
    if mode == "truecolor":
        return "#{:02x}{:02x}{:02x}".format(*rgb)
    if mode == "16":
        return f"color({nearest_16(rgb)})"
    return f"color({nearest_256(rgb)})"


def _nearest_level(channel: int) -> int:
    return min(range(6), key=lambda level: abs(_CUBE[level] - channel))


def _distance(a: RGB, b: RGB) -> float:
    return math.dist(a, b)


CATEGORY_COLORS: Final[dict[str, str]] = {
    "par": AMBER,
    "spot": CYAN,
    "wash": MAGENTA,
    "pixel": GREEN,
    "strobe": FG,
    "beam": CYAN,
    "blinder": FG,
    "dimmer": AMBER,
    "effect": MID,
    "fog": MID,
    "other": MID,
}
"""A fixture type's colour (plan §3, 8): busk's profile categories, the
spec's five (par amber, spot cyan, wash magenta, pixel green, strobe the
foreground) and the rest beside the one they look like."""

UNSET_COLORS: Final = (AMBER, CYAN, MAGENTA, GREEN, FG, MID)
"""The colours of profiles with no category, by profile in show order."""


def profile_colors(profiles: Sequence[tuple[str, str | None]]) -> dict[str, str]:
    """Each profile's colour by name, from ``(name, category)`` pairs in
    show order: its category's, else the next of :data:`UNSET_COLORS`."""
    found: dict[str, str] = {}
    unset = 0
    for name, category in profiles:
        if category in CATEGORY_COLORS:
            found[name] = CATEGORY_COLORS[category]
        else:
            found[name] = UNSET_COLORS[unset % len(UNSET_COLORS)]
            unset += 1
    return found


SOURCE_COLORS: Final[dict[str, str]] = {
    "programmer": MAGENTA,
    "playback": FG,
    "effect": GREEN,
    "none": DIM,
}
"""What drives a value (spec §8.3's source colouring)."""
