"""A project that depends on busk, as strict mypy sees it (phase-8-plan §5.10).

This file is type-checked, not run::

    uv run mypy --strict tests/api_consumer.py

It uses public names only, all through ``import busk``: the three examples
of the library guide, typed, and every public name at least once. So it
proves that the lazy re-exports of ``busk/__init__.py`` type-check for a
consumer, with the types each call really returns. The last function proves
the other half: a name that is not public is an error, not ``Any``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

import busk


def tooling(show_path: str, ofl_path: Path) -> list[str]:
    """Example 1: validate a show, import a profile."""
    try:
        show, warnings = busk.load_show(show_path)
    except busk.ShowLoadError as exc:
        return [str(issue) for issue in exc.issues]
    lines: list[str] = [f"{issue.severity} {issue.path}: {issue.message}" for issue in warnings]
    lines.append(show["meta"]["title"])

    report: busk.ImportReport = busk.read_ofl(ofl_path, manufacturer="TupperDMX")
    profile: busk.FixtureProfile = report.profile
    lines.append(profile["name"])
    lines.extend(mode["name"] for mode in profile["modes"])
    lines.extend(report.notes)
    try:
        busk.read_gdtf("spot.gdtf")
    except busk.ImportFailed as exc:
        lines.append(str(exc))

    checked, issues = busk.validate_show(b"{}")
    if checked is None:
        lines.extend(str(issue) for issue in issues)
    return lines


def offline(directory: Path) -> bytes:
    """Example 2: build a show from a script, render it on a clock you drive."""
    path = directory / "club.show"
    template: busk.Show = busk.new_show("Club Night", ids=busk.CounterIds())
    backup: Path | None = busk.save_show(template, path, now=datetime.now(UTC))
    assert backup is None
    show, _ = busk.load_show(path)

    library = busk.ProfileLibrary([directory / "profiles"])
    problems: list[str] = library.problems
    assert not problems
    assert len(library) > 0
    found: busk.FixtureProfile | None = library.find("dimmer")
    assert found is None or found is library.get(found["id"])

    ids: busk.IdFactory = busk.CounterIds(start=1)
    show_ = busk.OfflineShow(show, path=path, library=library, ids=ids)
    try:
        written: list[str] = show_.run_script("examples/club-night.busk")
    except busk.ScriptError as exc:
        written = [f"{exc.path}:{exc.line}: {exc.text}", *exc.output]
    assert written

    reply: busk.Reply = show_.execute("fader 1 1")
    assert reply.ok, reply.text
    command: busk.Command = {"type": "BLACKOUT", "on": False}
    nudge: busk.Command = {"type": "ADJUST_ATTRIBUTE", "attribute": "color", "component": "r",
                           "delta": -0.1}  # fmt: skip
    assert show_.submit(nudge).message
    result: busk.CommandResult = show_.submit(command)
    if not result.ok:
        raise SystemExit(result.message + "".join(str(issue) for issue in result.issues))

    frame: busk.DmxFrame = show_.tick(3.0)
    universes: Mapping[int, bytes] = frame.universes
    assert frame.time == show_.time == 3.0
    assert frame.seq >= 0
    assert show_.save().ok
    assert not show_.warnings
    snapshot: busk.EngineSnapshot = show_.snapshot
    playing: list[busk.PlaybackStatus] = [p for p in snapshot.playbacks if p.state != "idle"]
    speeds: tuple[busk.SpeedStatus, ...] = snapshot.speed
    page: busk.PageStatus | None = snapshot.page
    assert playing or speeds or page
    output: busk.OutputSnapshot = show_.output
    assert output.seq == frame.seq
    for element in output.fixtures:
        fixture: busk.FixtureOutput = element
        color: tuple[float, float, float] | None = fixture.color
        level: float = fixture.intensity if color is None else fixture.intensity * max(color)
        pan: float | None = fixture.pan
        driver: str | None = fixture.source.get("intensity")
        number: int | None = fixture.playback
        assert 0.0 <= level <= 1.0
        assert (pan, driver, number) is not None
    programmer: busk.ProgrammerStatus = show_.programmer
    selected: tuple[tuple[int, int], ...] = programmer.selection
    for entry in programmer.values:
        value: busk.ProgrammerValue = entry
        preset: tuple[str, int, str] | None = value.preset
        assert (value.number, value.element, value.attribute, preset) is not None
    effects: list[str] = [effect["id"] for effect in programmer.effects]
    assert programmer.version >= 1
    assert (selected, effects, programmer.blind, programmer.fadeTime) is not None
    return universes[1][:16]


def live(path: str, host: Callable[[busk.LiveShow], None]) -> busk.Show:
    """Example 3: live, inside the host application."""
    show, _ = busk.load_show(path)
    with busk.LiveShow(show, path=path, surfaces=True) as live:
        live.execute("gm 0.8")
        live.execute("go 9")
        if live.snapshot is not None:
            states: list[tuple[int, str, str | None]] = [
                (p.number, p.state, p.cue) for p in live.snapshot.playbacks
            ]
            assert states
        frame: busk.DmxFrame | None = live.frame
        assert frame is None or 1 in frame.universes
        output: busk.OutputSnapshot | None = live.output
        assert output is None or output.fixtures
        programmer: busk.ProgrammerStatus = live.programmer
        assert programmer.version >= 1
        host(live)
    live.stop()  # idempotent
    return live.show


def errors(error: busk.BuskError) -> str:
    """Every public error is a :class:`busk.BuskError`."""
    if isinstance(error, busk.UnsupportedFeature | busk.ShowLoadError | busk.ScriptError):
        return type(error).__name__
    if isinstance(error, busk.ImportFailed):
        value_error: ValueError = error
        return str(value_error)
    return busk.__version__


def internal_names_are_errors() -> None:
    """``busk`` exports nothing else. Should a type checker ever see an
    attribute here, each ignore below becomes unused, and ``--strict``
    (``warn_unused_ignores``) fails on it."""
    busk.Session  # type: ignore[attr-defined]  # noqa: B018
    busk.compile_show  # type: ignore[attr-defined]  # noqa: B018
