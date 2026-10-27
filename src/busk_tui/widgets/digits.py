"""Big digits and beat dots (spec §4.3).

Big digits are a 3-row block font of ``█`` and ``▀``: each glyph is a 3 × 5
dot pattern, two dot rows per text row (``▀`` the upper one), 3 cells wide
(``.`` 1), with a 1-cell gap. Used for BPM and GM.
"""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from busk_tui import colors

GLYPHS: dict[str, tuple[str, str, str]] = {
    "0": ("█▀█", "█ █", "▀▀▀"),
    "1": ("▀█ ", " █ ", "▀▀▀"),
    "2": ("▀▀█", "█▀▀", "▀▀▀"),
    "3": ("▀▀█", "▀▀█", "▀▀▀"),
    "4": ("█ █", "▀▀█", "  ▀"),
    "5": ("█▀▀", "▀▀█", "▀▀▀"),
    "6": ("█▀▀", "█▀█", "▀▀▀"),
    "7": ("▀▀█", "  █", "  ▀"),
    "8": ("█▀█", "█▀█", "▀▀▀"),
    "9": ("█▀█", "▀▀█", "▀▀▀"),
    ".": (" ", " ", "▀"),
    "-": ("   ", "▀▀▀", "   "),
    " ": ("   ", "   ", "   "),
}


def big(text: str) -> tuple[str, str, str]:
    """``text`` in the big font, as its three rows (unknown characters are
    left out)."""
    glyphs = [GLYPHS[character] for character in text if character in GLYPHS]
    rows = tuple(" ".join(glyph[row] for glyph in glyphs) for row in range(3))
    return rows[0], rows[1], rows[2]


class BigDigits(Static):
    """``text`` in big digits, in ``color``."""

    DEFAULT_CSS = "BigDigits { width: auto; height: 3; }"

    def __init__(
        self,
        text: str = "",
        color: str = colors.FG,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self.text = text
        self.color = color
        super().__init__(self._drawn(), id=id, classes=classes)

    def show(self, text: str, color: str | None = None) -> None:
        if color is not None:
            self.color = color
        self.text = text
        self.update(self._drawn())

    def _drawn(self) -> Text:
        return Text("\n".join(big(self.text)), style=self.color)


def beat_dots(beats: float | None) -> Text:
    """Four ``●``: the current beat of the bar amber (the first magenta), the
    others in the track colour; all dim without a beat count."""
    text = Text()
    current = None if beats is None else int(beats // 1) % 4
    for index in range(4):
        if index:
            text.append(" ")
        if index == current:
            text.append("●", style=colors.MAGENTA if index == 0 else colors.AMBER)
        else:
            text.append("●", style=colors.TRACK)
    return text


class BeatDots(Static):
    """Beat dots that follow a speed master's beat count (drawn again
    without a layout pass: they are always the same size)."""

    DEFAULT_CSS = "BeatDots { width: auto; height: 1; }"

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(beat_dots(None), id=id)
        self.beats: float | None = None

    def show(self, beats: float | None) -> None:
        old = None if self.beats is None else int(self.beats // 1)
        new = None if beats is None else int(beats // 1)
        self.beats = beats
        if old != new:
            self.update(beat_dots(beats), layout=False)
