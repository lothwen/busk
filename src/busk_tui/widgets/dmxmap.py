"""F8's DMX map (spec §8.8, plan Phase 4): one universe's 512 channels, 64
to a row (32 when the map is narrower than that), the first address of each
row on the left.

A free channel is ``·`` (track); a fixture's start address ``█`` and the
rest of its footprint ``▓``, in its type's colour (the profile's category,
else a colour by profile); a red cross (:data:`OVERLAP`) where two fixtures
overlap. The
footprints are the show's patch: a fixture's address and its mode's
footprint, nothing decoded from DMX.

Under the mouse, a fixture's channels light up and the hint row says what
the channel is (``1.94 · fixture 501 · ch 3/12``); a click posts
:class:`DmxMap.Clicked` with the fixtures on the channel. The pane cursor
marks one footprint (:meth:`DmxMap.mark`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from rich.text import Text
from textual import events
from textual.geometry import Size
from textual.message import Message
from textual.widget import Widget

from busk_tui import colors
from busk_tui.model import FixtureInfo
from busk_tui.widgets.controls import MARKED, ShowHint

CHANNELS: Final = 512
LABEL: Final = 5  # the address column, a space included
WIDE: Final = 64
NARROW: Final = 32
OVERLAP: Final = "\u2573"  # a box-drawing cross: two fixtures on one channel


@dataclass(frozen=True, slots=True)
class Footprint:
    """The channels one fixture takes in a universe."""

    fixture: int
    start: int  # its first address, 1..512
    size: int
    color: str

    @property
    def end(self) -> int:
        """Its last address (cut at 512)."""
        return min(CHANNELS, self.start + self.size - 1)


def footprints(
    fixtures: Sequence[FixtureInfo], universe: int, profile_colors: dict[str, str]
) -> tuple[Footprint, ...]:
    """The fixtures patched in ``universe``, by address (then number)."""
    found = [
        Footprint(
            fixture.number,
            fixture.patch[1],
            fixture.footprint,
            profile_colors.get(fixture.profile, colors.MID),
        )
        for fixture in fixtures
        if fixture.patch is not None and fixture.patch[0] == universe
    ]
    return tuple(sorted(found, key=lambda print_: (print_.start, print_.fixture)))


def owners(prints: Sequence[Footprint]) -> list[tuple[Footprint, ...]]:
    """Each channel's footprints, channel 1 at index 0."""
    found: list[list[Footprint]] = [[] for _ in range(CHANNELS)]
    for print_ in prints:
        for channel in range(print_.start, print_.end + 1):
            found[channel - 1].append(print_)
    return [tuple(channel) for channel in found]


def used(prints: Sequence[Footprint]) -> int:
    """How many channels some fixture takes."""
    return sum(1 for channel in owners(prints) if channel)


def overlaps(prints: Sequence[Footprint]) -> int:
    """How many pairs of fixtures share channels."""
    return sum(
        1
        for index, first in enumerate(prints)
        for second in prints[index + 1 :]
        if first.start <= second.end and second.start <= first.end
    )


def channel_text(universe: int, channel: int, found: Sequence[Footprint]) -> str:
    """What the hint row says of a channel: ``1.94 · fixture 501 · ch 3/12``,
    each fixture of an overlap, or ``free``."""
    parts = [f"{universe}.{channel}"]
    if not found:
        parts.append("free")
    for print_ in found:
        parts.append(f"fixture {print_.fixture} · ch {channel - print_.start + 1}/{print_.size}")
    if len(found) > 1:
        parts.insert(1, "overlap")
    return " · ".join(parts)


class DmxMap(Widget):
    """One universe's channels (see the module docs)."""

    DEFAULT_CSS = "DmxMap { height: auto; }"

    class Clicked(Message):
        """A click on a channel that ``fixtures`` take."""

        def __init__(self, dmx_map: DmxMap, fixtures: tuple[int, ...], shift: bool) -> None:
            super().__init__()
            self.dmx_map = dmx_map
            self.fixtures = fixtures
            self.shift = shift

    def __init__(self, universe: int, *, classes: str | None = None) -> None:
        super().__init__(classes=classes)
        self.universe = universe
        self.prints: tuple[Footprint, ...] = ()
        self._owners: list[tuple[Footprint, ...]] = owners(())
        self._hover: tuple[Footprint, ...] = ()  # the footprints under the mouse
        self._hint: str | None = None
        self._marked: Footprint | None = None

    def show(self, prints: tuple[Footprint, ...]) -> None:
        if prints != self.prints:
            self.prints = prints
            self._owners = owners(prints)
            self._hover, self._marked = (), None
            self.refresh()

    def mark(self, index: int | None) -> None:
        """The pane cursor on footprint ``index`` (``None``: nowhere)."""
        self._marked = None if index is None or index >= len(self.prints) else self.prints[index]
        self.refresh()

    @staticmethod
    def per_row(width: int) -> int:
        return WIDE if width >= LABEL + WIDE else NARROW

    def lines(self, width: int) -> list[Text]:
        row_size = self.per_row(width)
        lines: list[Text] = []
        for first in range(1, CHANNELS + 1, row_size):
            line = Text(f"{first:>{LABEL - 1}} ", style=colors.DIM)
            for channel in range(first, first + row_size):
                line.append(*self._glyph(channel))
            lines.append(line)
        return lines

    def _glyph(self, channel: int) -> tuple[str, str]:
        found = self._owners[channel - 1]
        if not found:
            return "·", colors.TRACK
        if self._marked in found:
            return ("█" if found[0].start == channel else "▓"), MARKED
        lit = f" on {colors.SEL}" if any(print_ in self._hover for print_ in found) else ""
        if len(found) > 1:
            return OVERLAP, colors.RED + lit
        return ("█" if found[0].start == channel else "▓"), found[0].color + lit

    def render(self) -> Text:
        text = Text("\n").join(self.lines(self.size.width))
        text.no_wrap = True
        return text

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return CHANNELS // self.per_row(width)

    def _channel(self, event: events.MouseEvent) -> int | None:
        """The channel under the mouse."""
        offset = event.get_content_offset(self)
        if offset is None:
            return None
        row_size = self.per_row(self.size.width)
        column = offset.x - LABEL
        if not 0 <= column < row_size or not 0 <= offset.y < CHANNELS // row_size:
            return None
        return offset.y * row_size + column + 1

    def on_mouse_move(self, event: events.MouseMove) -> None:
        channel = self._channel(event)
        found = () if channel is None else self._owners[channel - 1]
        if found != self._hover:
            self._hover = found
            self.refresh()
        hint = None if channel is None else channel_text(self.universe, channel, found)
        if hint != self._hint:
            self._hint = hint
            self.post_message(ShowHint(hint))

    def on_leave(self, event: events.Leave) -> None:
        if self._hover:
            self._hover = ()
            self.refresh()
        if self._hint is not None:
            self._hint = None
            self.post_message(ShowHint(None))

    def on_click(self, event: events.Click) -> None:
        channel = self._channel(event)
        found = () if channel is None else self._owners[channel - 1]
        if found:
            event.stop()
            fixtures = tuple(print_.fixture for print_ in found)
            self.post_message(self.Clicked(self, fixtures, event.shift))
