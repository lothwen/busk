"""Stopping and running a programmer effect again (GAP-14 of
``docs/dev/tui/engine-gaps.md``).

``effect stop <id>`` stops one of the programmer's effects and keeps it,
with its settings, until ``effect run <id>``: ``RUN_EFFECT`` with ``on``.
The stage sees it leave and come back exactly as if it were removed and
added again; recording leaves it out; stopping is content, undone and
autosaved. Appendix A: two heads (MH 1 and 2, fixtures 101 and 102, group 1)
and a par (201); the effects come from the built-in library.
"""

from __future__ import annotations

import json
import socket
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from builders import APPENDIX_A, load_doc, localhost_route, show_of, state_of
from busk import LiveShow, OfflineShow, Reply
from busk.commands.types import Command
from busk.console.parser import Context, ParseError, expected, parse
from busk.model.effect import EffectInstance
from busk.model.validate import validate_show
from busk.session.ids import CounterIds
from busk.session.library import ProfileLibrary
from busk.session.programmer import Programmer, drop_invalid_effects, from_json, to_json
from process_harness import BuskRun, Collector
from sacn_receiver import Receiver

PULSE = 'effect add "Pulse" id pulse hz 2'
"""A sine on the heads' intensity, multiplied: the level moves all the time."""


@pytest.fixture
def offline() -> OfflineShow:
    return OfflineShow(show_of(load_doc(APPENDIX_A)))


def run(show: OfflineShow | LiveShow, *lines: str) -> None:
    for line in lines:
        reply = show.execute(line)
        assert reply.ok, f"{line}: {reply.text}"


def running(offline: OfflineShow) -> list[str]:
    """The ids of the effects the engine runs, after a tick."""
    offline.tick(offline.time + 0.05)
    return [effect.id for effect in offline.effects.effects]


def head(offline: OfflineShow) -> float:
    """Fixture 101's intensity now."""
    fixture = offline.output.fixtures[0]
    assert fixture.number == 101
    return fixture.intensity


def cue_effects(offline: OfflineShow, cue_list: int, cue: str) -> list[dict[str, Any]]:
    listed = next(cl for cl in offline.show["cueLists"] if cl["number"] == cue_list)
    return [dict(e) for e in next(c for c in listed["cues"] if c["number"] == cue)["effects"]]


# ------------------------------------------------------------------- the stage


def test_a_stopped_effect_stays_in_the_programmer_and_leaves_the_stage(
    offline: OfflineShow,
) -> None:
    run(offline, "sel group 1", "set intensity 50%", PULSE)
    assert running(offline) == ["pulse"]
    added = offline.programmer.effects
    assert offline.execute("effect stop pulse") == Reply("stopped effect 'pulse'")
    status = offline.programmer
    assert (status.effects, status.stopped) == (added, frozenset({"pulse"}))
    assert running(offline) == []
    assert head(offline) == 0.5  # the programmer's own level, without the pulse
    assert offline.execute("effect run pulse") == Reply("started effect 'pulse'")
    assert offline.programmer.stopped == frozenset()
    assert running(offline) == ["pulse"]
    assert head(offline) < 0.5


def same_stage(events: dict[float, tuple[tuple[str, ...], tuple[str, ...]]]) -> set[float]:
    """Run two shows for 6 s, in 50 ms ticks, with each event's first lines
    in one and its second lines in the other; check that their frames and
    effect statuses are the same at every tick. Returns the levels fixture
    101 had."""
    shows = [OfflineShow(show_of(load_doc(APPENDIX_A))) for _ in range(2)]
    levels = set()
    for step in range(121):
        t = round(step * 0.05, 2)
        for show, lines in zip(shows, events.get(t, ((), ())), strict=True):
            run(show, *lines)
        frames = [show.tick(t).universes for show in shows]
        assert frames[0] == frames[1], t
        statuses = [
            [(e.id, e.presence, e.phase, e.size, e.hz) for e in show.effects.effects]
            for show in shows
        ]
        assert statuses[0] == statuses[1], t
        levels.add(head(shows[0]))
    return levels


def test_it_leaves_and_comes_back_as_if_removed_and_added_again() -> None:
    """Byte for byte, over a programmer fade of 1 s: a stop, a run while it
    fades out (it fades back in on its clock), a stop, and a run once it
    has gone (a new clock, as a new effect gets)."""
    levels = same_stage(
        {
            0.0: (("sel group 1", "set intensity 50%", "fade 1", PULSE),) * 2,
            1.5: (("effect stop pulse",), ("effect remove pulse",)),
            2.0: (("effect run pulse",), (PULSE,)),
            3.0: (("effect stop pulse",), ("effect remove pulse",)),
            5.0: (("effect run pulse",), (PULSE,)),
        }
    )
    assert len(levels) > 20  # the effect did move the heads


def test_a_started_effect_goes_on_top_as_an_added_one_does() -> None:
    """An absolute pan effect and the programmer's own pan: the newest
    action wins the heads' pan. Started while it still fades out, the
    effect goes back on top of the pan set after it stopped."""
    swing = 'effect add "Swing" id swing hz 1 low -45 high 45'
    template = (
        'effect template add "Swing" [{"attribute": "pan", "waveform": {"kind": "sine"}, '
        '"phaseOffset": 0, "mode": "absolute"}]'
    )
    same_stage(
        {
            0.0: ((template, "sel group 1", "set pan 10", swing, "fade 1"),) * 2,
            1.0: (("effect stop swing",), ("effect remove swing",)),
            1.2: (("set pan 20",),) * 2,
            1.4: (("effect run swing",), (swing,)),
        }
    )


def test_blind_and_stopping_are_separate(offline: OfflineShow) -> None:
    run(offline, "sel group 1", PULSE, "blind on", "effect stop pulse", "blind off")
    assert running(offline) == []  # still stopped
    run(offline, "blind on", "effect run pulse")
    assert running(offline) == []  # still blind
    run(offline, "blind off")
    assert running(offline) == ["pulse"]


# ------------------------------------------------------------- the commands


def test_stopping_or_running_twice_changes_nothing(offline: OfflineShow) -> None:
    run(offline, "sel group 1", PULSE)
    assert offline.execute("effect run pulse") == Reply("effect 'pulse' is already running")
    run(offline, "effect stop pulse")
    version = offline.programmer.version
    assert offline.execute("effect stop pulse") == Reply("effect 'pulse' is already stopped")
    assert offline.programmer.version == version
    assert offline.execute("undo") == Reply("undid: stopped effect 'pulse'")  # one step


def test_an_effect_the_programmer_lacks_is_refused(offline: OfflineShow) -> None:
    run(offline, "sel group 1", PULSE)
    version = offline.programmer.version
    assert offline.execute("effect stop fx9") == Reply(
        "error: the programmer has no effect 'fx9'", ok=False
    )
    assert offline.execute("effect run") == Reply("error: expected an effect id", ok=False)
    assert offline.execute("effect stop pulse now") == Reply("error: unexpected 'now'", ok=False)
    assert offline.programmer.version == version


def test_each_is_an_undo_step(offline: OfflineShow) -> None:
    run(offline, "sel group 1", PULSE, "effect stop pulse")
    assert offline.execute("undo") == Reply("undid: stopped effect 'pulse'")
    assert (offline.programmer.stopped, running(offline)) == (frozenset(), ["pulse"])
    assert offline.execute("redo") == Reply("redid: stopped effect 'pulse'")
    assert (offline.programmer.stopped, running(offline)) == ({"pulse"}, [])
    run(offline, "effect run pulse", "undo")
    assert offline.programmer.stopped == {"pulse"}


def test_undoing_a_removal_brings_it_back_stopped(offline: OfflineShow) -> None:
    run(offline, "sel group 1", PULSE, "effect stop pulse", "effect remove pulse", "undo")
    assert [e["id"] for e in offline.programmer.effects] == ["pulse"]
    assert (offline.programmer.stopped, running(offline)) == ({"pulse"}, [])


def test_replacing_a_stopped_effect_keeps_it_stopped(offline: OfflineShow) -> None:
    run(offline, "sel group 1", PULSE, "effect stop pulse")
    assert offline.execute('effect add "Pulse" id pulse hz 4') == Reply(
        "replaced effect 'pulse' on 2 targets (stopped)"
    )
    (effect,) = offline.programmer.effects
    assert effect["rate"] == {"kind": "hz", "value": 4}
    assert (offline.programmer.stopped, running(offline)) == ({"pulse"}, [])


@pytest.mark.parametrize("line", ["effect remove pulse", "effect clear", "clear"])
def test_an_effect_removed_and_added_again_runs(offline: OfflineShow, line: str) -> None:
    run(offline, "sel group 1", PULSE, "effect stop pulse", line, "sel group 1")
    assert offline.programmer.stopped == frozenset()
    assert offline.execute(PULSE) == Reply("added effect 'pulse' on 2 targets")
    assert running(offline) == ["pulse"]


def test_submit_takes_the_typed_command(offline: OfflineShow) -> None:
    run(offline, "sel group 1", PULSE)
    command = {"type": "RUN_EFFECT", "id": "pulse", "on": False}
    result = offline.submit(cast(Command, command))
    assert (result.ok, result.message) == (True, "stopped effect 'pulse'")
    assert offline.programmer.stopped == {"pulse"}


def test_the_programmer_says_which_are_stopped(offline: OfflineShow) -> None:
    run(offline, "sel group 1", PULSE, 'effect add "Wave" id wave hz 1', "effect stop pulse")
    lines = offline.execute("programmer").text.splitlines()
    assert lines[-2:] == [
        "  effect pulse 'Pulse' on 101, 102, 2 Hz, size 0.7 (stopped)",
        "  effect wave 'Wave' on 101, 102, 1 Hz, size 1",
    ]


def test_completion_offers_the_effects_each_verb_acts_on() -> None:
    effects = cast(tuple[EffectInstance, ...], ({"id": "a"}, {"id": "b"}, {"id": "c"}))
    programmer = Programmer(effects=effects, stopped=frozenset({"b"}))
    context = Context(
        show_of(load_doc(APPENDIX_A)), ProfileLibrary(), CounterIds(), programmer=programmer
    )
    assert expected("effect stop ", context).words == ("a", "c")
    assert expected("effect run ", context).words == ("b",)
    assert expected("effect remove ", context).words == ("a", "b", "c")
    with pytest.raises(ParseError, match="expected an effect id"):
        parse("effect stop", context)


# --------------------------------------------------------------- recording


def test_a_stopped_effect_is_not_recorded(offline: OfflineShow) -> None:
    run(offline, "sel group 1", "set intensity 50%", PULSE, 'effect add "Wave" id wave hz 1')
    run(offline, "effect stop wave")
    assert offline.execute("record cue 50/1") == Reply(
        "added cue list 'Cue list 50'; recorded cue 50/1: 1 entry, 1 effect; "
        "1 stopped effect not recorded"
    )
    assert [effect["id"] for effect in cue_effects(offline, 50, "1")] == ["pulse"]


def test_merging_and_removing_leave_the_cues_instance_alone(offline: OfflineShow) -> None:
    run(offline, "sel group 1", "set intensity 50%", PULSE, "record cue 50/1")
    run(offline, 'effect add "Pulse" id pulse hz 4', "effect stop pulse", "set intensity 80%")
    for line in ("record cue 50/1 merge", "record cue 50/1 remove"):
        run(offline, line)
        (effect,) = cue_effects(offline, 50, "1")
        assert effect["rate"] == {"kind": "hz", "value": 2}, line


def test_stopped_effects_alone_are_nothing_to_record(offline: OfflineShow) -> None:
    run(offline, "sel group 1", PULSE, "effect stop pulse")
    assert offline.execute("record cue 50/1") == Reply(
        "error: the programmer has no values or effects to record "
        "(stopped effects are not recorded)",
        ok=False,
    )


# --------------------------------------------------------------- the status


def test_the_status_lists_the_stopped_effects(offline: OfflineShow) -> None:
    run(offline, "sel group 1", PULSE, 'effect add "Wave" id wave hz 1')
    versions = [offline.programmer.version]
    for line in ("effect stop wave", "effect stop pulse", "effect run wave"):
        run(offline, line)
        versions.append(offline.programmer.version)
    assert offline.programmer.stopped == {"pulse"}
    assert versions == list(range(versions[0], versions[0] + 4))


def test_a_dormant_effect_is_not_listed_as_stopped(offline: OfflineShow) -> None:
    run(offline, 'fixture add 401 "Generic Spot 16ch" mode 16ch', "sel fixture 401", PULSE)
    run(offline, "effect stop pulse", "delete fixture 401")  # the effect no longer validates
    assert (offline.programmer.effects, offline.programmer.stopped) == ((), frozenset())
    run(offline, "undo")
    assert offline.programmer.stopped == {"pulse"}


# ------------------------------------------------------------------ autosave


def pulse_instance() -> EffectInstance:
    show = OfflineShow(show_of(load_doc(APPENDIX_A)))
    run(show, "sel group 1", PULSE)
    return show.programmer.effects[0]


def test_the_autosave_keeps_it_stopped() -> None:
    held = Programmer(effects=(pulse_instance(),), stopped=frozenset({"pulse"}))
    data = to_json(held)
    assert data["stopped"] == ["pulse"]
    assert from_json(json.loads(json.dumps(data))) == (held, [])


@pytest.mark.parametrize(
    ("stopped", "kept", "dropped"),
    [
        (None, frozenset(), []),  # a file from before GAP-14
        (["pulse", "gone"], frozenset({"pulse"}), []),  # an effect dropped or never there
        ("pulse", frozenset(), ["programmer.stopped"]),
        ([1], frozenset(), ["programmer.stopped"]),
    ],
)
def test_a_recovered_file_keeps_what_fits(
    stopped: object, kept: frozenset[str], dropped: list[str]
) -> None:
    data = to_json(Programmer(effects=(pulse_instance(),)))
    if stopped is None:
        del data["stopped"]
    else:
        data["stopped"] = stopped
    programmer, problems = from_json(data)
    assert (programmer.stopped, problems) == (kept, dropped)


def test_an_effect_dropped_on_recovery_is_no_longer_stopped() -> None:
    gone = {"kind": "targets", "refs": [{"fixtureId": "fx-gone", "element": 0}]}
    effect = cast(EffectInstance, {**pulse_instance(), "targets": gone})
    held = Programmer(effects=(effect,), stopped=frozenset({"pulse"}))
    programmer, dropped = drop_invalid_effects(state_of(load_doc(APPENDIX_A)), held)
    assert (programmer.effects, programmer.stopped, len(dropped)) == ((), frozenset(), 1)


# --------------------------------------------------------------------- hosts


def eventually(condition: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_a_live_show_stops_and_runs_it() -> None:
    live = LiveShow(show_of(load_doc(APPENDIX_A)), output=False)
    with live:
        run(live, "sel group 1", PULSE)
        assert live.effects is None  # the first read turns the capture on

        def ids() -> list[str] | None:
            effects = live.effects
            return None if effects is None else [effect.id for effect in effects.effects]

        eventually(lambda: ids() == ["pulse"])
        assert live.execute("effect stop pulse") == Reply("stopped effect 'pulse'")
        assert live.programmer.stopped == {"pulse"}
        eventually(lambda: ids() == [])
        run(live, "effect run pulse")
        eventually(lambda: ids() == ["pulse"])


@pytest.mark.skipif(
    not hasattr(socket, "send_fds") or not Path("/proc").is_dir(),
    reason="the process tree needs descriptor passing, the harness /proc",
)
def test_busk_run_stops_it_on_stage(tmp_path: Path, receiver: Receiver) -> None:
    """The session runs in the console process and the engine in its own:
    the stopped effect leaves the sACN output, and comes back."""
    show = tmp_path / "show.json"
    show.write_text(json.dumps(localhost_route(load_doc(APPENDIX_A))))
    collector = Collector(receiver)
    try:
        with BuskRun(show, sacn_port=receiver.port) as busk:
            busk.send("sel group 1\nset intensity 50%\n")
            busk.wait_for("intensity: 2 targets")
            eventually(lambda: bool(collector.packets), timeout=10.0)
            still = collector.settle()
            busk.send(f"{PULSE}\neffect stop pulse\n")
            busk.wait_for("stopped effect 'pulse'")
            assert collector.settle() == still
            busk.send("effect run pulse\nprogrammer\n")
            busk.wait_for("started effect 'pulse'")
            busk.wait_for("  effect pulse 'Pulse' on 101, 102, 2 Hz, size 0.7")
            eventually(lambda: collector.latest() != still, timeout=5.0)
            busk.send("quit\n")
            assert busk.wait() == 0, busk.err
    finally:
        collector.stop()


# ------------------------------------------------------------------ bindings


def binding_issues(command: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Validate Appendix A with ``command`` in a new binding."""
    doc = load_doc(APPENDIX_A)
    doc["bindings"].append(
        {"id": "b9", "surfaceId": "s-midi", "input": {"kind": "midiNote", "channel": 1, "note": 9},
         "action": {"kind": "command", "command": command}}
    )  # fmt: skip
    _, issues = validate_show(json.dumps(doc))
    return [(issue.severity, issue.path, issue.message) for issue in issues]


def test_a_binding_can_stop_and_run_an_effect() -> None:
    assert binding_issues({"type": "RUN_EFFECT", "id": "fx1", "on": False}) == []
    missing = binding_issues({"type": "RUN_EFFECT", "id": "fx1"})
    assert [(severity, path) for severity, path, _ in missing] == [
        ("error", "bindings[3].action.command.on")
    ]
