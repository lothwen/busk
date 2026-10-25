"""Effect rows: F1's EFFECTS (spec §8.1 layout B, plan §2.2) and F5's
table (spec §8.5, plan Phase 3), with one sparkline.

On F1 a row is one effect that runs: who runs it (``P11``, the playback
whose cue holds it, or ``prog``, the programmer), its id and template, a
sparkline of its next cycle, and its state, ``[RUN]`` (dimmed while it
fades in or out) or ``[off]``. The state runs, for a cue effect, ``release
N`` on its playback: the effect leaves the list, and GO on the playback
brings it back. For a programmer effect it runs ``effect stop <id>`` or
``effect run <id>``. The rows are the cue effects that run (busk's
``LiveShow.effects``), then every programmer effect, stopped ones included.

F5's table (:class:`EffectTable`, :func:`effect_rows`) lists every effect
the show's cues hold, running or not, then the programmer's, each with the
settings ``effect add`` takes, formatted alike. A cue effect's state goes
to its cue (``goto N C``) while it does not run, and releases its playback
while it does.
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
from busk_tui.formats import phase_text, targets_text
from busk_tui.model import (
    EffectInfo,
    EffectsModel,
    EffectView,
    ProgrammerModel,
    Rgb,
    ShowModel,
    TemplateInfo,
)
from busk_tui.nav import Item, Stop
from busk_tui.widgets.controls import CommandButton
from busk_tui.widgets.rows import Cells, Column, RowTable, cell

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
    for index in range(width):
        sample = index * samples // width
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


# ------------------------------------------------------------------- F5


@dataclass(frozen=True, slots=True)
class FxRow:
    """One row of F5's table: a cue's effect (``owner`` ``9/4``) or the
    programmer's (``prog``); ``live``, its status while it runs; ``toggle``,
    the line its state runs (``None``: no playback runs its list);
    ``remove``, a programmer effect's ``effect remove``."""

    owner: str
    info: EffectInfo
    running: bool  # it runs, or (the programmer's) is not stopped
    live: EffectView | None
    toggle: Line | None
    remove: Line | None


def effect_rows(
    show: ShowModel | None, programmer: ProgrammerModel | None, effects: EffectsModel | None
) -> list[FxRow]:
    """Every cue effect of the show, by list, cue and order, then the
    programmer's in the order they were added."""
    running = () if effects is None else effects.effects
    rows: list[FxRow] = []
    for cue_list in () if show is None else show.cueLists:
        runs = show.runs(cue_list.number) if show is not None else ()
        for cue in cue_list.cues:
            for info in cue.effects:
                live = next(
                    (
                        e
                        for e in running
                        if e.playback in runs and e.cue == cue.number and e.id == info.id
                    ),
                    None,
                )
                toggle = None
                if live is not None and live.playback is not None:
                    toggle = commands.release(live.playback)
                elif runs:
                    toggle = commands.goto(runs[0], cue.number)
                owner = f"{cue_list.number}/{cue.number}"
                rows.append(FxRow(owner, info, live is not None, live, toggle, None))
    stopped = frozenset[str]() if programmer is None else programmer.stopped
    for info in () if programmer is None else programmer.effects:
        live = next((e for e in running if e.playback is None and e.id == info.id), None)
        toggle = (
            commands.effect_run(info.id) if info.id in stopped else commands.effect_stop(info.id)
        )
        rows.append(
            FxRow(
                "prog",
                info,
                info.id not in stopped,
                live,
                toggle,
                commands.effect_remove(info.id),
            )
        )
    return rows


class EffectTable(RowTable):
    COLUMNS = (
        Column("owner", "cue", 5),
        Column("id", "id", 7),
        Column("template", "template", 8),
        Column("targets", "fixtures", 8, flex=True),
        Column("rate", "rate", 10),
        Column("hz", "now", 6, drop=4, right=True),
        Column("size", "size", 6, drop=3, right=True),
        Column("phase", "phase", 7, drop=5),
        Column("wings", "wings", 5, drop=6, right=True),
        Column("wave", "wave", WAVE_CELLS, drop=2),
        Column("state", "state", 5),
        Column("remove", "", 1),
    )


def fx_cells(row: FxRow, show: ShowModel | None, mode: ColorMode) -> Cells:
    info, live = row.info, row.live
    fixtures = () if show is None else show.fixtures
    if info.low is not None and info.high is not None:
        size = f"{_level(info.low)}–{_level(info.high)}"
    else:
        size = f"{info.size:g}"
    wings = str(info.wings)
    if info.groups != 1 or info.blocks != 1:
        wings = f"{wings} g{info.groups} b{info.blocks}"
    if row.toggle is None:
        state = cell("—", colors.BORDER)
    elif row.running:
        dim = live is None or live.presence < 1.0
        state = cell("[RUN]", f"{colors.GREEN} dim" if dim else colors.GREEN)
    else:
        state = cell("[off]", colors.DIM)
    wave = () if live is None else live.wave
    hues = () if live is None else live.colors
    return {
        "owner": cell(row.owner, colors.DIM if row.owner == "prog" else colors.MID),
        "id": cell(info.id, colors.MID),
        "template": cell(info.template, colors.FG),
        "targets": cell(targets_text(info.targets, fixtures), colors.CYAN),
        "rate": cell(rate_text(info), colors.FG),
        "hz": cell(f"{live.hz:.2f}" if live is not None else "·", colors.DIM),
        "size": cell(size, colors.FG),
        "phase": cell(phase_text(info.phase), colors.FG),
        "wings": cell(wings, colors.FG),
        "wave": sparkline(wave, hues, live is not None and row.running, mode),
        "state": state,
        "remove": cell("✕" if row.remove is not None else "", colors.RED),
    }


def rate_text(info: EffectInfo) -> str:
    """The rate, and the direction unless forward, as ``effect add`` takes
    them: ``bpm x 0.5``, ``hz 2 bounce``."""
    return info.rate if info.direction == "forward" else f"{info.rate} {info.direction}"


def _level(value: object) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


class TemplateTable(RowTable):
    COLUMNS = (
        Column("name", "name", 9),
        Column("summary", "layers", 10, flex=True),
        Column("defaults", "defaults", 12, drop=2),
        Column("source", "from", 7, drop=1),
    )


def template_cells(template: TemplateInfo) -> Cells:
    """A template: its name, its layers, the defaults the library gives an
    instance (``size 20``, ``low 0 high 1``, ``phase 0 360``), and where it
    is from (``show``, or ``library``: the show has no copy of it yet)."""
    defaults = []
    if template.size is not None:
        defaults.append(f"size {template.size:g}")
    if template.low is not None and template.high is not None:
        defaults.append(f"low {template.low:g} high {template.high:g}")
    if template.phase is not None:
        defaults.append(f"phase {template.phase[0]:g} {template.phase[1]:g}")
    return {
        "name": cell(template.name, colors.GREEN),
        "summary": cell(template.summary, colors.MID),
        "defaults": cell(" ".join(defaults), colors.DIM),
        "source": cell(template.source, colors.MID if template.source == "show" else colors.DIM),
    }
