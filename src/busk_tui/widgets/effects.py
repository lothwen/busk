"""Effect rows (spec §8.1 layout B EFFECTS, plan §2.2; F5 reuses them).

A row is one effect: who runs it (``P11``, the playback whose cue holds it,
or ``prog``, the programmer), its id and template, a sparkline of its next
cycle, and its state, ``[RUN]`` (dimmed while it fades in or out) or
``[off]``. The state runs, for a cue effect, ``release N`` on its playback:
the effect leaves the list, and GO on the playback brings it back. For a
programmer effect it runs ``effect stop <id>`` or ``effect run <id>``.

The rows are the cue effects that run (busk's ``LiveShow.effects``), then
every programmer effect, stopped ones included.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.colors import ColorMode
from busk_tui.commands import Line
from busk_tui.model import EffectsModel, ProgrammerModel, Rgb, ShowModel
from busk_tui.nav import Item, Stop
from busk_tui.widgets.controls import CommandButton

BLOCKS: Final = "▁▂▃▄▅▆▇█"
WAVE_CELLS: Final = 20


def sparkline(
    wave: Sequence[float],
    hues: Sequence[Rgb],
    running: bool,
    mode: ColorMode,
    width: int = WAVE_CELLS,
) -> Text:
    """One cycle in ``width`` cells: heights from ``wave`` (full without
    one), each cell in its hue from ``hues`` (a colour cycle) or green; flat
    and grey with neither, or when not ``running``."""
    samples = len(wave) or len(hues)
    if not samples or not running:
        return Text(BLOCKS[0] * width, style=colors.BORDER)
    text = Text()
    for cell in range(width):
        sample = cell * samples // width
        height = wave[sample] if wave else 1.0
        glyph = BLOCKS[round(max(0.0, min(1.0, height)) * (len(BLOCKS) - 1))]
        text.append(glyph, style=colors.swatch(hues[sample], 1.0, mode) if hues else colors.GREEN)
    return text


@dataclass(frozen=True, slots=True)
class EffectLine:
    """One row's content (see :func:`effect_lines`)."""

    key: tuple[
        int | None, str | None, str
    ]  # (playback, cue, id); the programmer's: (None, None, id)
    owner: str  # P11, prog
    id: str
    template: str
    running: bool
    presence: float
    wave: tuple[float, ...]
    hues: tuple[Rgb, ...]
    toggle: Line


def effect_lines(
    show: ShowModel | None, programmer: ProgrammerModel | None, effects: EffectsModel | None
) -> list[EffectLine]:
    """The rows: the cue effects that run, then the programmer's effects."""
    running = () if effects is None else effects.effects
    stopped = frozenset[str]() if programmer is None else programmer.stopped
    lines: list[EffectLine] = []
    for effect in running:
        if effect.playback is None:
            continue
        lines.append(
            EffectLine(
                key=(effect.playback, effect.cue, effect.id),
                owner=f"P{effect.playback}",
                id=effect.id,
                template=_cue_template(show, effect.playback, effect.cue, effect.id),
                running=True,
                presence=effect.presence,
                wave=effect.wave,
                hues=effect.colors,
                toggle=commands.release(effect.playback),
            )
        )
    for info in () if programmer is None else programmer.effects:
        live = next((e for e in running if e.playback is None and e.id == info.id), None)
        lines.append(
            EffectLine(
                key=(None, None, info.id),
                owner="prog",
                id=info.id,
                template=info.template,
                running=info.id not in stopped,
                presence=0.0 if live is None else live.presence,
                wave=() if live is None else live.wave,
                hues=() if live is None else live.colors,
                toggle=(
                    commands.effect_run(info.id)
                    if info.id in stopped
                    else commands.effect_stop(info.id)
                ),
            )
        )
    return lines


def _cue_template(show: ShowModel | None, playback: int, cue: str | None, effect: str) -> str:
    info = None if show is None else show.playback(playback)
    cue_list = None if show is None or info is None else show.cue_list(info.cueList)
    for found in () if cue_list is None else cue_list.cues:
        if found.number == cue:
            for instance in found.effects:
                if instance.id == effect:
                    return instance.template
    return ""


class Sparkline(Widget):
    """A :func:`sparkline` as wide as the widget, up to :data:`WAVE_CELLS`."""

    DEFAULT_CSS = "Sparkline { height: 1; }"

    def __init__(self, *, classes: str | None = None) -> None:
        super().__init__(classes=classes)
        self.shown: tuple[tuple[float, ...], tuple[Rgb, ...], bool, ColorMode] = (
            (),
            (),
            False,
            "256",
        )

    def show(
        self, wave: tuple[float, ...], hues: tuple[Rgb, ...], running: bool, mode: ColorMode
    ) -> None:
        if (wave, hues, running, mode) != self.shown:
            self.shown = (wave, hues, running, mode)
            self.refresh()

    def render(self) -> Text:
        wave, hues, running, mode = self.shown
        return sparkline(wave, hues, running, mode, min(WAVE_CELLS, self.size.width))


class EffectRow(Horizontal):
    """One :class:`EffectLine`."""

    DEFAULT_CSS = """
    EffectRow { height: 1; }
    EffectRow > .fx-who { width: 10; text-wrap: nowrap; text-overflow: ellipsis; }
    EffectRow > .fx-template {
        width: 1fr; min-width: 6; text-wrap: nowrap; text-overflow: ellipsis;
    }
    EffectRow > Sparkline { width: 2fr; max-width: 20; margin: 0 1; }
    EffectRow > CommandButton { width: 5; }
    """

    def __init__(self, line: EffectLine, mode: ColorMode) -> None:
        super().__init__()
        self.line = line
        self.who = Static(classes="fx-who")
        self.template = Static(classes="fx-template")
        self.wave = Sparkline()
        self.state = CommandButton("RUN", line.toggle, "go")
        self.show(line, mode)

    def compose(self) -> ComposeResult:
        yield self.who
        yield self.template
        yield self.wave
        yield self.state

    def show(self, line: EffectLine, mode: ColorMode) -> None:
        self.line = line
        who = Text(line.owner, style=colors.DIM)
        who.append(f" {line.id}", style=colors.MID)
        self.who.update(who)
        self.template.update(Text(line.template, style=colors.FG))
        self.wave.show(line.wave, line.hues, line.running, mode)
        if line.running:
            self.state.change("RUN", line.toggle, "go", dim=line.presence < 1.0)
        else:
            self.state.change("off", line.toggle, "off", dim=False)


class EffectList(Vertical):
    """The rows of :func:`effect_lines`; rebuilt when the effects listed
    change, redrawn otherwise."""

    DEFAULT_CSS = "EffectList { height: auto; }"

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.keys: tuple[tuple[int | None, str | None, str], ...] | None = None
        self.rows: list[EffectRow] = []

    def show(self, lines: Sequence[EffectLine], mode: ColorMode) -> None:
        keys = tuple(line.key for line in lines)
        if keys == self.keys:
            for row, line in zip(self.rows, lines, strict=True):
                row.show(line, mode)
            return
        self.keys = keys
        self.rows = [EffectRow(line, mode) for line in lines]
        self.remove_children()
        if self.rows:
            self.mount_all(self.rows)
        else:
            self.mount(Static(Text("no effects run", style=colors.DIM)))

    def stops(self) -> list[Stop]:
        return [
            Stop(Item(f"{row.line.owner} {row.line.id}", line=row.line.toggle.text), row.state)
            for row in self.rows
        ]
