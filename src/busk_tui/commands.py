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

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class Line:
    text: str
    performance: bool = False


def percent(level: float) -> str:
    """A level 0..1 as busk reads a percentage, in whole percent: ``72%``."""
    return f"{round(max(0.0, min(1.0, level)) * 100)}%"


def quoted(name: str) -> str:
    """A name as busk reads it: in double quotes, with JSON's escapes."""
    return json.dumps(name, ensure_ascii=False)


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


def sel_fixture(fixture: int, *, add: bool = False, remove: bool = False) -> Line:
    """``sel fixture 101``; ``add``: ``sel + fixture 101``; ``remove``: ``sel -
    fixture 101``."""
    change = "+ " if add else "- " if remove else ""
    return Line(f"sel {change}fixture {fixture}")


def sel_fixtures(fixtures: Sequence[int], *, add: bool = False) -> Line:
    """Several fixtures at once: ``sel fixture 501, fixture 502`` (``add``:
    ``sel + …``)."""
    targets = ", ".join(f"fixture {fixture}" for fixture in fixtures)
    return Line(f"sel {'+ ' if add else ''}{targets}")


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


def set_color(red: float, green: float, blue: float) -> Line:
    """A whole colour, 0..1 each, to two decimals: ``set color 1 0.25 0``
    (busk derives the white, amber and UV emitters)."""
    return Line(f"set color {number(red)} {number(green)} {number(blue)}")


def set_option(attribute: str, option: str) -> Line:
    """A discrete attribute's option: ``set gobo1 star``."""
    return Line(f"set {attribute} {option}")


def set_spread(
    attribute: str,
    low: float,
    high: float,
    how: Literal["center", "edges"] | None = None,
    *,
    level: bool = False,
) -> Line:
    """A fan over the selection, from ``low`` to ``high``: ``set pan spread
    -30 30``, ``set intensity spread 0% 100% edges`` (``level``: 0..1, sent
    as percentages); ``how`` ``center`` or ``edges`` mirrors it."""
    ends = (percent(low), percent(high)) if level else (number(low), number(high))
    return Line(" ".join(["set", attribute, "spread", *ends, *([how] if how else [])]))


def clear() -> Line:
    return Line("clear")


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


# ---------------------------------------------------------------- presets


def record_preset(
    pool: str,
    preset_number: int,
    scope: str | None,
    merge: Literal["merge", "replace", "remove"] | None = None,
    name: str | None = None,
) -> Line:
    """The programmer's values in the pool's families as a preset, at
    ``scope``: ``record preset color 5 global "Crimson"``; ``merge`` (or
    ``replace``, ``remove``) for one that exists: ``record preset color 5
    global merge``. Without a name, busk names a new one (``Color 5``).
    ``remove`` takes every scope (busk ignores one), so it is sent without:
    ``record preset color 5 remove``."""
    words = ["record", "preset", pool, str(preset_number), *([scope] if scope else [])]
    if merge is not None:
        words.append(merge)
    if name is not None:
        words.append(quoted(name))
    return Line(" ".join(words))


def delete_preset(pool: str, preset_number: int) -> Line:
    return Line(f"delete preset {pool} {preset_number}")


def rename_preset(pool: str, preset_number: int, name: str) -> Line:
    return Line(f"rename preset {pool} {preset_number} {quoted(name)}")


def renumber_preset(pool: str, preset_number: int, new_number: int) -> Line:
    """``preset color 7 number 9``."""
    return Line(f"preset {pool} {preset_number} number {new_number}")


# -------------------------------------------------------------------- rig


def _span(first: int, last: int) -> str:
    """``101``, or ``101 thru 104``."""
    return str(first) if first == last else f"{first} thru {last}"


def _address(at: tuple[int, int]) -> str:
    """A universe and an address as busk reads them: ``1.85``."""
    return f"{at[0]}.{at[1]}"


def fixture_add(
    first: int, last: int, profile: str, mode: str, at: tuple[int, int] | None = None
) -> Line:
    """``fixture add 302 thru 305 "Generic Spot 16ch" mode "16ch" at 1.85``;
    busk patches each fixture after the one before it."""
    where = "" if at is None else f" at {_address(at)}"
    return Line(f"fixture add {_span(first, last)} {quoted(profile)} mode {quoted(mode)}{where}")


def delete_fixture(fixture: int) -> Line:
    """``delete fixture 101 cascade``: busk asks, naming what it leaves."""
    return Line(f"delete fixture {fixture} cascade")


def rename_fixture(fixture: int, name: str) -> Line:
    return Line(f"rename fixture {fixture} {quoted(name)}")


def renumber_fixture(fixture: int, new_number: int) -> Line:
    """``fixture 101 number 150``."""
    return Line(f"fixture {fixture} number {new_number}")


def patch_fixture(fixture: int, at: tuple[int, int] | None) -> Line:
    """``fixture 101 patch 1.85``; ``at`` ``None``: ``fixture 101 patch none``."""
    return Line(f"fixture {fixture} patch {'none' if at is None else _address(at)}")


def limit_range(first: int, last: int, attribute: str, low: float, high: float) -> Line:
    """``fixture 101 thru 102 limits tilt -90 10`` (``thru`` covers every
    fixture between its ends)."""
    return Line(f"fixture {_span(first, last)} limits {attribute} {number(low)} {number(high)}")


def limit_intensity(first: int, last: int, level: float) -> Line:
    """``fixture 301 limits intensity 50%``."""
    return Line(f"fixture {_span(first, last)} limits intensity {percent(level)}")


def no_limit(first: int, last: int, attribute: str) -> Line:
    """``fixture 101 limits tilt none``: that limit goes, the others stay."""
    return Line(f"fixture {_span(first, last)} limits {attribute} none")


def no_limits(first: int, last: int) -> Line:
    """``fixture 101 limits none``: all of them go."""
    return Line(f"fixture {_span(first, last)} limits none")


def orientation(fixture: int, key: str, value: bool | float) -> Line:
    """``fixture 101 orientation.invertPan true``, ``fixture 101
    orientation.panOffset 30``."""
    text = str(value).lower() if isinstance(value, bool) else number(value)
    return Line(f"fixture {fixture} orientation.{key} {text}")


def location(fixture: int, values: Sequence[float]) -> Line:
    """``fixture 101 location {"x": 0, "y": 0, "z": 0, "rx": 0, "ry": 0, "rz": 0}``."""
    pairs = ", ".join(
        f'"{key}": {number(value)}'
        for key, value in zip(("x", "y", "z", "rx", "ry", "rz"), values, strict=True)
    )
    return Line(f"fixture {fixture} location {{{pairs}}}")


def no_location(fixture: int) -> Line:
    return Line(f"fixture {fixture} location none")


def fixture_mode(fixture: int, mode: str) -> Line:
    """``fixture 101 mode "16ch"``."""
    return Line(f"fixture {fixture} mode {quoted(mode)}")


def fixture_profile(fixture: int, profile: str, mode: str) -> Line:
    """``fixture 101 profile "RGB Par 3ch" mode "3ch"``."""
    return Line(f"fixture {fixture} profile {quoted(profile)} mode {quoted(mode)}")


def category(profile: str, word: str) -> Line:
    """``profile "Generic Spot 16ch" category spot``, or ``… category none``."""
    return Line(f"profile {quoted(profile)} category {word}")


def universe_add(universe: int, name: str | None = None) -> Line:
    """``universe add 2 "Balcony"``; without a name, busk names it (``Universe 2``)."""
    return Line(f"universe add {universe}" + ("" if name is None else f" {quoted(name)}"))


def delete_universe(universe: int) -> Line:
    """``delete universe 2 cascade``: busk asks, naming what goes."""
    return Line(f"delete universe {universe} cascade")


def rename_universe(universe: int, name: str) -> Line:
    return Line(f"rename universe {universe} {quoted(name)}")


def renumber_universe(universe: int, new_number: int) -> Line:
    """``universe 2 number 7``."""
    return Line(f"universe {universe} number {new_number}")


def route_add(
    universe: int,
    protocol: Literal["sacn", "artnet", "dmxusb"],
    address: str,
    destination: str | None = None,
    hz: float | None = None,
) -> Line:
    """``route add 2 sacn 2``, with the address and destination as
    :class:`~busk_tui.model.RouteView` has them: ``route add 2 artnet 0.0.1
    unicast 10.0.0.50``, ``route add 2 dmxusb enttecPro /dev/ttyUSB0 hz 30``."""
    words = ["route", "add", str(universe), protocol, address]
    if destination is not None:
        words.append(destination)
    if hz is not None:
        words += ["hz", number(hz)]
    return Line(" ".join(words))


def delete_route(route: str) -> Line:
    """``delete route r-1``: busk asks."""
    return Line(f"delete route {route}")


def route_on(route: str, on: bool) -> Line:
    """``route r-1 on``; busk asks before ``off``."""
    return Line(f"route {route} {'on' if on else 'off'}")


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


def patch_prefill(fixture: int) -> str:
    """``fixture 101 patch ``: an address (``1.101``) or ``none`` next."""
    return f"fixture {fixture} patch "


def location_prefill(fixture: int, place: Sequence[float] | None) -> str:
    """:func:`location`, whole, at the fixture's own place when it has one,
    to change."""
    return location(fixture, (0.0,) * 6 if place is None else place).text


def rename_fixture_prefill(fixture: int) -> str:
    """``rename fixture 101 "``: the name comes next."""
    return f'rename fixture {fixture} "'


def category_prefill(profile: str) -> str:
    """``profile "Generic Spot" category ``: a category or ``none`` next."""
    return f"profile {quoted(profile)} category "


def bind_prefill(surface: str) -> str:
    """``bind "nanoKONTROL2" ``: an input and what it drives next."""
    return f"bind {quoted(surface)} "


def unbind_prefill(surface: str, given: str) -> str:
    """``unbind "nanoKONTROL2" cc 1 0``, whole: Enter runs it."""
    return f"unbind {quoted(surface)} {given}"


def feedback_prefill(surface: str, given: str) -> str:
    """``feedback "nanoKONTROL2" cc 1 0 ``: ``led``, ``motor``, ``display``
    or ``none`` next."""
    return f"feedback {quoted(surface)} {given} "


def pickup_prefill(surface: str) -> str:
    """``surface "nanoKONTROL2" pickup ``: ``soft`` or ``jump`` next."""
    return f"surface {quoted(surface)} pickup "
