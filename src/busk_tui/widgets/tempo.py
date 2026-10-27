"""A speed master's tempo (spec §8.1 TEMPO, §8.7 SPEED).

Its BPM in big digits, the beat dots, ``[TAP]`` (``tap "<name>"``) and
``[−] [+]`` (``bpm "<name>" <bpm ∓ 1>``). With ``full`` (F7): a large TAP,
``[−1] [+1]``, the master's level bar, which picks its multiplier, and the
multiplier steps with the current one lit. Tap tempo is busk's: the TUI
only sends the taps.

:class:`TempoRow` is the one-line tempo of layouts A and C: the master's
name, its BPM, the beat dots, ``[TAP]`` and ``[B.O.]``.
"""

from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.model import LiveState, MasterView, ShowModel, SpeedView
from busk_tui.nav import Item, Stop
from busk_tui.widgets.controls import CommandButton
from busk_tui.widgets.digits import BeatDots, BigDigits
from busk_tui.widgets.masters import BlackoutButton, MasterBar, master_item


def first_speed(show: ShowModel | None) -> MasterView | None:
    """The show's first speed master, which F1's tempo follows."""
    return None if show is None else next((m for m in show.masters if m.kind == "speed"), None)


def speed_of(live: LiveState | None, name: str) -> SpeedView | None:
    """Speed master ``name`` as the engine has it now."""
    return None if live is None else next((s for s in live.speed if s.name == name), None)


def beats_of(live: LiveState | None, beats: Sequence[float], name: str) -> float | None:
    """Speed master ``name``'s beat count, from each master's (``beats``, in
    the order of ``live.speed``)."""
    if live is None:
        return None
    index = next((i for i, speed in enumerate(live.speed) if speed.name == name), None)
    return None if index is None or index >= len(beats) else beats[index]


class Tempo(Vertical):
    """One speed master, ``master`` (see the module docs)."""

    DEFAULT_CSS = """
    Tempo { height: auto; }
    Tempo > .tempo-top { height: 3; }
    Tempo .tempo-side { width: auto; height: 3; padding-left: 2; }
    Tempo .tempo-buttons { height: 1; width: auto; margin-top: 1; }
    Tempo .tempo-buttons > CommandButton { margin-right: 1; }
    Tempo > MasterBar { margin-top: 1; }
    Tempo > .tempo-steps { height: 1; }
    """

    def __init__(self, master: MasterView, *, full: bool = False) -> None:
        super().__init__()
        self.master = master
        self.full = full
        self.speed: SpeedView | None = None
        name = master.name
        self.digits = BigDigits("---", colors.AMBER)
        self.dots = BeatDots()
        self.tap = CommandButton(
            " TAP " if full else "TAP", commands.tap(name), "tempo", reverse=full
        )
        self.slower = CommandButton("−1" if full else "−", commands.bpm(name, 119))
        self.faster = CommandButton("+1" if full else "+", commands.bpm(name, 121))
        self.level = MasterBar(master, 0.0, label="level")
        self.steps = Static("", classes="tempo-steps")

    def compose(self) -> ComposeResult:
        with Horizontal(classes="tempo-top"):
            yield self.digits
            with Vertical(classes="tempo-side"):
                yield self.dots
                with Horizontal(classes="tempo-buttons"):
                    yield self.tap
                    yield self.slower
                    yield self.faster
        if self.full:
            yield self.level
            yield self.steps

    def show(self, speed: SpeedView | None) -> None:
        if speed == self.speed:
            return
        self.speed = speed
        if speed is None:
            self.digits.show("---")
            return
        self.digits.show(f"{speed.bpm:.1f}")
        self.slower.change(line=commands.bpm(self.master.name, speed.bpm - 1))
        self.faster.change(line=commands.bpm(self.master.name, speed.bpm + 1))
        self.level.show(speed.level)
        self.steps.update(self._steps(speed.multiplier))

    def show_beats(self, beats: float | None) -> None:
        self.dots.show(beats)

    def stops(self) -> list[Stop]:
        name = self.master.name
        stops = [
            Stop(Item(f"tap {name}", line=self.tap.line.text), self.tap),
            Stop(Item(f"{name} slower", line=self.slower.line.text), self.slower),
            Stop(Item(f"{name} faster", line=self.faster.line.text), self.faster),
        ]
        if self.full:
            stops.append(Stop(master_item(self.master), self.level))
        return stops

    def _steps(self, multiplier: float) -> Text:
        text = Text("steps", style=colors.DIM)
        for step in self.master.steps:
            lit = step == multiplier
            text.append(
                f" x {step:g} ", style=f"bold {colors.BG} on {colors.AMBER}" if lit else colors.MID
            )
        return text


class TempoRow(Horizontal):
    """``Main 128.0 ● ● ● ●  [TAP] [B.O.]`` for the speed ``master`` (``None``:
    the show has none, and the row has only ``[B.O.]``)."""

    DEFAULT_CSS = """
    TempoRow { height: 1; }
    TempoRow > .tempo-name { width: auto; max-width: 12; padding-right: 1; text-wrap: nowrap;
                             text-overflow: ellipsis; }
    TempoRow > .tempo-none { width: auto; }
    TempoRow > .tempo-bpm { width: auto; padding-right: 1; }
    TempoRow > .tempo-gap { width: 1fr; }
    TempoRow > CommandButton { margin-left: 1; }
    """

    def __init__(self, master: MasterView | None) -> None:
        super().__init__()
        self.master = master
        self.speed: SpeedView | None = None
        name = (
            Text("no speed master", style=colors.DIM)
            if master is None
            else Text(master.name, style=colors.DIM)
        )
        self.name_text = Static(name, classes="tempo-none" if master is None else "tempo-name")
        self.bpm = Static(Text("---", style=colors.AMBER), classes="tempo-bpm")
        self.dots = BeatDots()
        self.tap = (
            None if master is None else CommandButton("TAP", commands.tap(master.name), "tempo")
        )
        self.blackout = BlackoutButton(short=True)

    def compose(self) -> ComposeResult:
        yield self.name_text
        if self.master is not None:
            yield self.bpm
            yield self.dots
        yield Static("", classes="tempo-gap")
        if self.tap is not None:
            yield self.tap
        yield self.blackout

    def show(self, speed: SpeedView | None, blackout: bool) -> None:
        if speed != self.speed:
            self.speed = speed
            self.bpm.update(
                Text("---" if speed is None else f"{speed.bpm:.1f}", style=colors.AMBER)
            )
        self.blackout.show(blackout)

    def show_beats(self, beats: float | None) -> None:
        self.dots.show(beats)

    def stops(self) -> list[Stop]:
        stops = []
        if self.tap is not None and self.master is not None:
            stops.append(Stop(Item(f"tap {self.master.name}", line=self.tap.line.text), self.tap))
        stops.append(Stop(Item("blackout", line=self.blackout.line.text), self.blackout))
        return stops
