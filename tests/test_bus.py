"""Command bus: validation at submit time, normalisation, envelopes, FIFO order."""

from __future__ import annotations

import math
import typing
from typing import Any, cast

import pytest

from builders import compile_doc, issues_of
from busk.commands.bus import ENGINE_COMMANDS, CommandBus, CommandRejected
from busk.commands.classes import COMMAND_CLASSES
from busk.commands.types import Command
from busk.compiler.compile import CompiledShow
from busk.engine.clock import FakeClock
from busk.model.validate import Issue


@pytest.fixture
def compiled(appendix_a: dict[str, Any]) -> CompiledShow:
    return compile_doc(appendix_a)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(start=5.0)


@pytest.fixture
def bus(compiled: CompiledShow, clock: FakeClock) -> CommandBus:
    return CommandBus(compiled, clock)


def submit(bus: CommandBus, command: dict[str, Any]) -> Command:
    return bus.submit(cast(Command, command))["command"]


def test_every_command_type_is_applied_or_sent_to_the_session() -> None:
    union = typing.get_args(Command.__value__)[0]
    types = {
        typing.get_args(typing.get_type_hints(member)["type"])[0]
        for member in typing.get_args(union)
    }
    performance = {t for t, kind in COMMAND_CLASSES.items() if kind == "performance"}
    assert performance == ENGINE_COMMANDS
    assert performance | {t for t in types if COMMAND_CLASSES[t] != "performance"} == types


@pytest.mark.parametrize(
    "command",
    [
        {"type": "TRIGGER_PLAYBACK", "playbackId": "pb-blue"},
        {"type": "RELEASE_PLAYBACK", "playbackId": "pb-blue"},
        {"type": "RELEASE_PLAYBACK", "playbackId": "pb-blue", "time": 0},
        {"type": "TOGGLE_PLAYBACK", "playbackId": "pb-blue"},
        {"type": "FLASH", "playbackId": "pb-blue", "down": True},
        {"type": "GO", "playbackId": "pb-song"},
        {"type": "SET_FADER", "playbackId": "pb-song", "level": 0.5},
        {"type": "SET_MASTER", "masterId": "m-gm", "level": 0.8},
        {"type": "BLACKOUT", "on": False},
        {"type": "BACK", "playbackId": "pb-song"},
        {"type": "GOTO", "playbackId": "pb-song", "cueNumber": "2"},
        {"type": "TAP", "masterId": "m-speed"},
        {"type": "SET_BPM", "masterId": "m-speed", "bpm": 128.5},
        {"type": "SET_BPM", "masterId": "m-speed", "bpm": 999.0},
        {"type": "SET_MASTER", "masterId": "m-speed", "level": 0.25},
        {"type": "SET_FADER", "slot": 0, "level": 0.5},  # Phase 6
        {"type": "SET_FADER", "slot": 99, "level": 0.5},  # beyond the page: the engine ignores it
        {"type": "PAGE", "number": 1},
        {"type": "PAGE", "delta": -3},
        {"type": "PAGE", "delta": 0},
        {"type": "BLACKOUT"},  # a toggle
        {"type": "PLAYBACK_BUTTON", "playbackId": "pb-song", "button": 0, "down": True},
        {"type": "PLAYBACK_BUTTON", "playbackId": "pb-song", "button": 9, "down": True},
        {"type": "PLAYBACK_BUTTON", "slot": 0, "button": 1, "down": False},
        {"type": "PLAYBACK_BUTTON", "slot": 99, "button": 0, "down": True},  # beyond the page
        {"type": "RELEASE_ALL"},  # Phase 7
        {"type": "RELEASE_ALL", "time": 0},
        {"type": "RELEASE_ALL", "time": 2.5},
        {"type": "OUTPUT", "on": False},
        {"type": "OUTPUT", "on": True},
    ],
)
def test_performance_commands_are_accepted_unchanged(
    bus: CommandBus, command: dict[str, Any]
) -> None:
    queued = submit(bus, command)
    assert queued == command
    assert queued is not command  # the engine never shares a dict with the caller


def test_toggle_playback_validates_inside_a_binding(appendix_a: dict[str, Any]) -> None:
    action = {"kind": "command", "command": {"type": "TOGGLE_PLAYBACK", "playbackId": "pb-blue"}}
    appendix_a["bindings"][0]["action"] = action
    assert issues_of(appendix_a) == []
    action["command"]["playbackId"] = "nope"
    assert issues_of(appendix_a) == [
        Issue("error", "bindings[0].action.command.playbackId", "Unknown playback 'nope'")
    ]


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        (
            {"type": "GOTO", "playbackId": "pb-song", "cueNumber": "7"},
            "no cue 7 in cue list 1",
        ),
        (
            {"type": "GOTO", "playbackId": "pb-song", "cueNumber": "two"},
            "no cue two in cue list 1",
        ),
        ({"type": "GOTO", "playbackId": "pb-song"}, "no cue None in cue list 1"),
        ({"type": "BACK", "playbackId": "pb-nope"}, "unknown playback 'pb-nope'"),
        ({"type": "TAP", "masterId": "m-gm"}, "TAP needs a speed master; 'm-gm' is grand"),
        ({"type": "TAP", "masterId": "m-nope"}, "unknown master 'm-nope'"),
        ({"type": "TAP"}, "unknown master None"),
        (
            {"type": "SET_BPM", "masterId": "m-gm", "bpm": 120},
            "SET_BPM needs a speed master; 'm-gm' is grand",
        ),
        (
            {"type": "SET_BPM", "masterId": "m-speed", "bpm": 0},
            "bpm must be a number greater than 0 and at most 999, got 0",
        ),
        (
            {"type": "SET_BPM", "masterId": "m-speed", "bpm": 999.5},
            "bpm must be a number greater than 0 and at most 999, got 999.5",
        ),
        (
            {"type": "SET_BPM", "masterId": "m-speed", "bpm": math.nan},
            "bpm must be a number greater than 0 and at most 999, got nan",
        ),
        (
            {"type": "SET_BPM", "masterId": "m-speed", "bpm": "120"},
            "bpm must be a number greater than 0 and at most 999, got '120'",
        ),
        (
            {"type": "SET_BPM", "masterId": "m-speed", "bpm": True},
            "bpm must be a number greater than 0 and at most 999, got True",
        ),
        (
            {"type": "SET_BPM", "masterId": "m-speed"},
            "bpm must be a number greater than 0 and at most 999, got None",
        ),
        (
            {"type": "CLEAR_PROGRAMMER"},
            "CLEAR_PROGRAMMER is not a performance command; submit it to the session",
        ),
        ({"type": "UNDO"}, "UNDO is not a performance command; submit it to the session"),
        ({"type": "NOPE"}, "unknown command type 'NOPE'"),
        ({}, "unknown command type None"),
        ({"type": "GO", "playbackId": "pb-nope"}, "unknown playback 'pb-nope'"),
        (
            {"type": "SET_FADER", "level": 1},
            "SET_FADER needs exactly one of 'playbackId' and 'slot'",
        ),
        ({"type": "SET_MASTER", "masterId": "m-nope", "level": 1}, "unknown master 'm-nope'"),
        (
            {"type": "SET_FADER", "playbackId": "pb-song", "level": math.nan},
            "level must be a number, got nan",
        ),
        (
            {"type": "SET_FADER", "playbackId": "pb-song", "level": True},
            "level must be a number, got True",
        ),
        (
            {"type": "SET_MASTER", "masterId": "m-gm", "level": "1"},
            "level must be a number, got '1'",
        ),
        (
            {"type": "RELEASE_PLAYBACK", "playbackId": "pb-blue", "time": -1},
            "release time must be a finite number ≥ 0, got -1",
        ),
        (
            {"type": "RELEASE_PLAYBACK", "playbackId": "pb-blue", "time": math.inf},
            "release time must be a finite number ≥ 0, got inf",
        ),
        (
            {"type": "FLASH", "playbackId": "pb-blue", "down": 1},
            "FLASH needs a boolean 'down', got 1",
        ),
        ({"type": "BLACKOUT", "on": 1}, "BLACKOUT needs a boolean 'on', got 1"),
        # Phase 6: page-relative faders and pages
        ({"type": "SET_FADER", "playbackId": "pb-song", "slot": 0, "level": 1},
         "SET_FADER needs exactly one of 'playbackId' and 'slot'"),
        ({"type": "SET_FADER", "slot": -1, "level": 1}, "slot must be an integer ≥ 0, got -1"),
        ({"type": "SET_FADER", "slot": True, "level": 1}, "slot must be an integer ≥ 0, got True"),
        ({"type": "SET_FADER", "slot": 0, "level": "x"}, "level must be a number, got 'x'"),
        ({"type": "PAGE"}, "PAGE needs exactly one of 'number' and 'delta'"),
        ({"type": "PAGE", "number": 1, "delta": 1},
         "PAGE needs exactly one of 'number' and 'delta'"),
        ({"type": "PAGE", "number": 2}, "no page 2"),
        ({"type": "PAGE", "delta": 0.5}, "delta must be an integer, got 0.5"),
        ({"type": "PAGE", "delta": True}, "delta must be an integer, got True"),
        # Phase 6: playback buttons
        ({"type": "PLAYBACK_BUTTON", "button": 0, "down": True},
         "PLAYBACK_BUTTON needs exactly one of 'playbackId' and 'slot'"),
        ({"type": "PLAYBACK_BUTTON", "playbackId": "pb-song", "slot": 0, "button": 0,
          "down": True}, "PLAYBACK_BUTTON needs exactly one of 'playbackId' and 'slot'"),
        ({"type": "PLAYBACK_BUTTON", "playbackId": "pb-nope", "button": 0, "down": True},
         "unknown playback 'pb-nope'"),
        ({"type": "PLAYBACK_BUTTON", "slot": -1, "button": 0, "down": True},
         "slot must be an integer ≥ 0, got -1"),
        ({"type": "PLAYBACK_BUTTON", "slot": 0, "down": True},
         "button must be an integer ≥ 0, got None"),
        ({"type": "PLAYBACK_BUTTON", "slot": 0, "button": -1, "down": True},
         "button must be an integer ≥ 0, got -1"),
        ({"type": "PLAYBACK_BUTTON", "slot": 0, "button": 1.0, "down": True},
         "button must be an integer ≥ 0, got 1.0"),
        ({"type": "PLAYBACK_BUTTON", "slot": 0, "button": 0},
         "PLAYBACK_BUTTON needs a boolean 'down', got None"),
        ({"type": "PLAYBACK_BUTTON", "slot": 0, "button": 0, "down": 0},
         "PLAYBACK_BUTTON needs a boolean 'down', got 0"),
        # Phase 7: panic commands; highlight belongs to the session
        ({"type": "RELEASE_ALL", "time": -0.5},
         "release time must be a finite number ≥ 0, got -0.5"),
        ({"type": "RELEASE_ALL", "time": math.nan},
         "release time must be a finite number ≥ 0, got nan"),
        ({"type": "RELEASE_ALL", "time": "1"}, "release time must be a finite number ≥ 0, got '1'"),
        ({"type": "OUTPUT"}, "OUTPUT needs a boolean 'on', got None"),
        ({"type": "OUTPUT", "on": 0}, "OUTPUT needs a boolean 'on', got 0"),
        ({"type": "HIGHLIGHT", "on": True},
         "HIGHLIGHT is not a performance command; submit it to the session"),
    ],
)  # fmt: skip
def test_invalid_commands_are_rejected_with_a_reason(
    bus: CommandBus, command: dict[str, Any], reason: str
) -> None:
    with pytest.raises(CommandRejected) as rejected:
        submit(bus, command)
    assert rejected.value.reason == reason
    assert list(bus.drain()) == []  # nothing was queued


def test_not_a_mapping_is_rejected(bus: CommandBus) -> None:
    with pytest.raises(CommandRejected, match="not a command"):
        bus.submit(cast(Command, "GO"))


@pytest.mark.parametrize(
    ("level", "clamped"), [(1.5, 1.0), (-0.25, 0.0), (math.inf, 1.0), (1, 1.0)]
)
def test_levels_are_clamped(bus: CommandBus, level: float, clamped: float) -> None:
    fader = {"type": "SET_FADER", "playbackId": "pb-song", "level": level}
    master = {"type": "SET_MASTER", "masterId": "m-gm", "level": level}
    assert submit(bus, fader) == {**fader, "level": clamped}
    assert submit(bus, master) == {**master, "level": clamped}
    assert fader["level"] == level  # the caller's dict is never modified


def test_a_tempo_is_normalised_to_a_float(bus: CommandBus) -> None:
    queued = submit(bus, {"type": "SET_BPM", "masterId": "m-speed", "bpm": 120})
    assert type(queued["bpm"]) is float  # type: ignore[typeddict-item]


def test_tap_needs_a_master_that_takes_taps(appendix_a: dict[str, Any], clock: FakeClock) -> None:
    appendix_a["masters"][1]["tap"] = False
    bus = CommandBus(compile_doc(appendix_a), clock)
    with pytest.raises(CommandRejected, match="speed master 'Speed 1' does not take taps"):
        bus.submit(cast(Command, {"type": "TAP", "masterId": "m-speed"}))
    queued = submit(bus, {"type": "SET_BPM", "masterId": "m-speed", "bpm": 90})
    assert queued["bpm"] == 90  # type: ignore[typeddict-item]


def test_set_master_takes_every_master_kind(appendix_a: dict[str, Any], clock: FakeClock) -> None:
    """Size and group masters work since Phase 5 (steps 7 and 9), fade-time
    masters since Phase 6 (step 7)."""
    appendix_a["masters"] += [
        {"id": "m-size", "kind": "size", "name": "FX"},
        {"id": "m-group", "kind": "group", "name": "Heads", "groupId": "g-mh"},
        {"id": "m-fade", "kind": "fadeTime", "name": "Fade"},
    ]
    bus = CommandBus(compile_doc(appendix_a), clock)
    queued = submit(bus, {"type": "SET_MASTER", "masterId": "m-size", "level": 1.5})
    assert queued == {"type": "SET_MASTER", "masterId": "m-size", "level": 1.0}
    queued = submit(bus, {"type": "SET_MASTER", "masterId": "m-group", "level": -0.5})
    assert queued == {"type": "SET_MASTER", "masterId": "m-group", "level": 0.0}
    queued = submit(bus, {"type": "SET_MASTER", "masterId": "m-fade", "level": 2})
    assert queued == {"type": "SET_MASTER", "masterId": "m-fade", "level": 1.0}


def test_envelopes_are_numbered_timed_and_drained_in_order(
    bus: CommandBus, clock: FakeClock
) -> None:
    first = bus.submit({"type": "TRIGGER_PLAYBACK", "playbackId": "pb-blue"})
    clock.advance(0.5)
    second = bus.submit(
        {"type": "BLACKOUT", "on": True},
        origin={"surfaceId": "s-midi"},  # type: ignore[typeddict-item]
    )
    assert (first["id"], first["issuedAt"], first["origin"]) == ("1", 5.0, {})
    assert (second["id"], second["issuedAt"], second["origin"]) == (
        "2",
        5.5,
        {"surfaceId": "s-midi"},
    )
    assert list(bus.drain()) == [first, second]
    assert list(bus.drain()) == []  # drained means empty
    third = bus.submit({"type": "GO", "playbackId": "pb-song"})
    assert third["id"] == "3"
    assert list(bus.drain()) == [third]
