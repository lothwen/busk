"""Every console line the UI sends, built in one place.

Each builder returns a :class:`Line`: its text, in busk's syntax, and whether
it is a *performance* line, one the engine carries out and that never waits
for another thread's line (``go``, ``fader``, ``gm`` …, see busk's
``LiveShow.execute``). The bridge sends performance lines on its controls
worker, the others on its ordered worker.

``tests/tui/test_tui_commands.py`` runs every builder's line on the
club-night show (the contract test), so a line busk would refuse fails
there, not on stage. Each phase adds its builders here and to that test.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Line:
    text: str
    performance: bool = False


def percent(level: float) -> str:
    """A level 0..1 as busk reads a percentage, in whole percent: ``72%``."""
    return f"{round(max(0.0, min(1.0, level)) * 100)}%"


def quoted(name: str) -> str:
    """A name as busk reads it, in double quotes. busk has no escape for a
    quote inside a name, so such a name is refused (:class:`ValueError`)."""
    if '"' in name:
        raise ValueError(f"a name with a double quote cannot be typed: {name!r}")
    return f'"{name}"'


def help_() -> Line:
    return Line("help")


def undo() -> Line:
    return Line("undo")


def redo() -> Line:
    return Line("redo")


def save() -> Line:
    return Line("save")


def number(value: float) -> str:
    """A number as busk reads it, to two decimals at most: ``120``, ``120.5``."""
    return f"{round(value, 2):g}"


# ------------------------------------------------------------- performance


def go(playback: int) -> Line:
    return Line(f"go {playback}", performance=True)


def back(playback: int) -> Line:
    return Line(f"back {playback}", performance=True)


def release(playback: int) -> Line:
    return Line(f"release {playback}", performance=True)


def release_all() -> Line:
    return Line("release all", performance=True)


def fader(playback: int, level: float) -> Line:
    return Line(f"fader {playback} {percent(level)}", performance=True)


def flash(playback: int, on: bool) -> Line:
    return Line(f"flash {playback} {'on' if on else 'off'}", performance=True)


def gm(level: float) -> Line:
    return Line(f"gm {percent(level)}", performance=True)


def master(name: str, level: float) -> Line:
    return Line(f"master {quoted(name)} {percent(level)}", performance=True)


def blackout(on: bool) -> Line:
    return Line(f"blackout {'on' if on else 'off'}", performance=True)


def output(on: bool) -> Line:
    return Line(f"output {'on' if on else 'off'}", performance=True)


def tap(name: str) -> Line:
    return Line(f"tap {quoted(name)}", performance=True)


def bpm(name: str, value: float) -> Line:
    return Line(f"bpm {quoted(name)} {number(value)}", performance=True)


def page(step: int) -> Line:
    """``page next`` (1) or ``page prev`` (-1)."""
    return Line("page next" if step > 0 else "page prev", performance=True)


def goto(playback: int, cue: str) -> Line:
    """Go to one cue of the list the playback runs: ``goto 9 3``."""
    return Line(f"goto {playback} {cue}", performance=True)


# -------------------------------------------------------------- programmer


def sel_group(group: int, *, add: bool = False) -> Line:
    return Line(f"sel + group {group}" if add else f"sel group {group}")


def sel_none() -> Line:
    return Line("sel none")


def preset(pool: str, preset_number: int) -> Line:
    return Line(f"preset {pool} {preset_number}")


def set_level(attribute: str, level: float) -> Line:
    """A level attribute (0..1) or a colour component: ``set intensity 72%``."""
    return Line(f"set {attribute} {percent(level)}")


def set_number(attribute: str, value: float) -> Line:
    """An attribute in its own unit (degrees, Hz): ``set pan -45``."""
    return Line(f"set {attribute} {number(value)}")


def step_level(attribute: str, change: float) -> Line:
    """A level changed by ``change`` (0..1) where the programmer holds it:
    ``set intensity by -5%``."""
    return Line(f"set {attribute} by {round(change * 100)}%")


def step_number(attribute: str, change: float) -> Line:
    """An attribute in its own unit changed by ``change``: ``set pan by 15``."""
    return Line(f"set {attribute} by {number(change)}")


def blind(on: bool) -> Line:
    return Line(f"blind {'on' if on else 'off'}")


def highlight(on: bool) -> Line:
    return Line(f"highlight {'on' if on else 'off'}")


def effect_stop(effect: str) -> Line:
    return Line(f"effect stop {effect}")


def effect_run(effect: str) -> Line:
    return Line(f"effect run {effect}")


def effect_remove(effect: str) -> Line:
    return Line(f"effect remove {effect}")


def effect_add(template: str) -> Line:
    """A programmer effect on the selection, with the template's defaults:
    ``effect add "Circle"``."""
    return Line(f"effect add {quoted(template)}")


# ------------------------------------------------------------------- cues


def record_cue(cue_list: int) -> Line:
    """The programmer as a new cue at the end of the list: ``record cue 9``."""
    return Line(f"record cue {cue_list}")


def cuelist_sequence(cue_list: int) -> Line:
    return Line(f"cuelist {cue_list} sequence")


def cuelist_chase(cue_list: int, settings: str | None = None, crossfade: float = 0.0) -> Line:
    """``cuelist 9 chase`` with ``settings`` (a rate and direction, ``bpm x 1
    bounce``) and a crossfade, as the list had them, else ``bpm x 1``."""
    if settings is None:
        return Line(f"cuelist {cue_list} chase bpm x 1")
    fade = f" crossfade {number(crossfade)}" if crossfade else ""
    return Line(f"cuelist {cue_list} chase {settings}{fade}")


# ---------------------------------------------------------------- pre-fills
# Lines put in the prompt for the operator to finish.


def set_prefill(attribute: str) -> str:
    return f"set {attribute} "


FADE_PREFILL = "fade "


def record_preset_prefill(pool: str, preset_number: int) -> str:
    """``record preset color 5 "``: the name comes next."""
    return f'record preset {pool} {preset_number} "'


def cue_prefill(cue_list: int, cue: str, verb: str) -> str:
    """``cue 9/3 time ``, ``cue 9/3 follow ``, ``cue 9/3 wait ``, and ``cue 9/3
    go`` (whole: Enter runs it)."""
    return f"cue {cue_list}/{cue} go" if verb == "go" else f"cue {cue_list}/{cue} {verb} "


def cue_time_prefill(cue_list: int, cue: str, times: str, then: str = "") -> str:
    """The cue's fade times kept, for what comes after them: ``cue 9/3 time
    1/3 delay `` (``then`` ``delay``), or ``cue 9/3 time 1/3 `` (a curve)."""
    return f"cue {cue_list}/{cue} time {times} " + (f"{then} " if then else "")


def rename_cue_prefill(cue_list: int, cue: str) -> str:
    """``rename cue 9/3 "``: the name comes next."""
    return f'rename cue {cue_list}/{cue} "'
