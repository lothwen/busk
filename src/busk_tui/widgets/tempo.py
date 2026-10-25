"""A speed master's tempo (spec §8.1 TEMPO, §8.7 SPEED).

Its BPM in big digits, the beat dots, ``[TAP]`` (``tap "<name>"``) and
``[−] [+]`` (``bpm "<name>" <bpm ∓ 1>``). With ``full`` (F7): a large TAP,
``[−1] [+1]``, the master's level bar, which picks its multiplier, and the
multiplier steps with the current one lit. Tap tempo is busk's: the TUI
only sends the taps.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.model import MasterView, SpeedView
from busk_tui.nav import Item, Stop
from busk_tui.widgets.controls import CommandButton
from busk_tui.widgets.digits import BeatDots, BigDigits
from busk_tui.widgets.masters import MasterBar, master_item


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
