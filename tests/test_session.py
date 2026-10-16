"""The session: store invariant, one undo timeline, unblocked performance (phase-3-plan §5.6)."""

from __future__ import annotations

import copy
import json
import threading
from typing import Any, cast

import pytest

from builders import (
    APPENDIX_A,
    busk_rig,
    cue,
    cue_list,
    effect_instance,
    entry,
    literal,
    load_doc,
    playback,
    targets,
)
from busk.commands.types import Command
from busk.engine.install import Install, ProgrammerFrame
from busk.session import session as session_module
from busk.session.programmer import EMPTY, from_json, to_json
from session_harness import CLEAR, REDO, UNDO, Live, blind, put, sel


@pytest.fixture
def live() -> Live:
    return Live(load_doc(APPENDIX_A))


def queued(live: Live) -> list[Any]:
    """Drain the engine queue (installs and envelopes)."""
    return list(live.engine.bus.drain())


def submit(live: Live, command: dict[str, Any]) -> Any:
    return live.session.submit(cast(Command, command))


RENAME = {"type": "SET", "path": ["fixtures", {"id": "fx-mh1"}, "name"], "value": "Left"}


def test_a_rejected_edit_changes_nothing(live: Live) -> None:
    session = live.session
    live.do(sel("fx-mh1"), put("pan", 10))
    queued(live)
    show, compiled, programmer = session.show, session.compiled, session.programmer
    snapshot, steps = copy.deepcopy(show), session.timeline.undo_count
    result = submit(live, {"type": "DELETE", "path": ["fixtures", {"id": "fx-mh1"}]})
    assert not result.ok
    assert result.message == "deleted fixtures[0]: rejected, the show would not be valid"
    assert ("groups[0].members[0].fixtureId", "Unknown fixture 'fx-mh1'") in [
        (issue.path, issue.message) for issue in result.issues
    ]
    assert session.show is show
    assert show == snapshot
    assert session.compiled is compiled
    assert session.programmer is programmer
    assert session.timeline.undo_count == steps
    assert queued(live) == []
    assert not session.dirty


def test_a_batch_whose_last_command_fails_changes_nothing(live: Live) -> None:
    show = live.session.show
    result = submit(
        live,
        {
            "type": "BATCH",
            "label": "two",
            "commands": [RENAME, {"type": "DELETE", "path": ["groups", {"id": "g-nope"}]}],
        },
    )
    assert (result.ok, result.message) == (False, "groups has no element with id 'g-nope'")
    assert live.session.show is show
    assert queued(live) == []


def test_a_batch_is_one_undo_step(live: Live) -> None:
    before = live.session.show
    result = live.do(
        {
            "type": "BATCH",
            "label": "rename both",
            "commands": [
                RENAME,
                {"type": "SET", "path": ["fixtures", {"id": "fx-mh2"}, "name"], "value": "Right"},
            ],
        }
    )
    assert result.message == "rename both"
    assert [f["name"] for f in live.session.show["fixtures"][:2]] == ["Left", "Right"]
    assert live.do(UNDO).message == "undid: rename both"
    assert live.session.show == before


def test_undo_and_redo_across_programmer_and_show_steps(live: Live) -> None:
    session = live.session
    initial = session.show
    live.do(sel("fx-mh1"))  # 1 programmer
    live.do(put("pan", 10))  # 2 programmer
    live.do(RENAME)  # 3 show
    live.do(put("pan", 20))  # 4 programmer
    renamed = session.show
    assert live.do(UNDO).message == "undid: pan: 1 target"
    assert dict(session.programmer.values) == {"fx-mh1:0/pan": {"kind": "literal", "value": 10}}
    live.do(UNDO)
    assert session.show == initial
    assert session.show["fixtures"][0]["name"] == "MH 1"
    live.do(UNDO)
    assert dict(session.programmer.values) == {}
    assert session.programmer.selection == ({"fixtureId": "fx-mh1", "element": 0},)
    live.do(UNDO)
    assert session.programmer == EMPTY
    assert not submit(live, UNDO).ok
    for _ in range(4):
        live.do(REDO)
    assert session.show == renamed
    assert dict(session.programmer.values) == {"fx-mh1:0/pan": {"kind": "literal", "value": 20}}
    assert submit(live, REDO).message == "nothing to redo"


def test_a_new_step_clears_redo(live: Live) -> None:
    live.do(RENAME, UNDO)
    assert live.session.timeline.redo_count == 1
    live.do(sel("fx-mh2"))
    assert live.session.timeline.redo_count == 0
    assert not submit(live, REDO).ok


def test_blind_is_never_undone(live: Live) -> None:
    live.do(sel("fx-mh1"), blind(True), put("pan", 5))
    live.do(UNDO)  # undoes the value, not blind
    assert live.session.programmer.blind
    live.do(UNDO)  # the selection
    assert live.session.programmer.blind
    live.do(blind(False))
    assert live.session.timeline.redo_count == 2  # blind pushed no step


def fade(time: float) -> dict[str, Any]:
    return {"type": "PROGRAMMER_FADE", "time": time}


def test_the_programmer_fade_is_a_mode_never_undone(live: Live) -> None:
    session = live.session
    live.do(sel("fx-mh1"))
    queued(live)
    live.do(fade(2.0))
    assert session.programmer.fadeTime == 2.0
    assert session.timeline.undo_count == 1  # no step for the fade time
    assert queued(live) == []  # and no install: the next frame carries it
    live.do(put("pan", 5))
    (install,) = queued(live)
    assert install.programmer.fadeTime == 2.0
    live.do(UNDO)  # undoes the value, not the fade time
    assert session.programmer.fadeTime == 2.0
    assert queued(live)[-1].programmer.fadeTime == 2.0  # the undo fades too
    live.do(fade(0.5), REDO)
    assert session.programmer.fadeTime == 0.5
    assert session.programmer.values == {"fx-mh1:0/pan": {"kind": "literal", "value": 5}}


def test_the_programmer_fade_survives_restore_programmer(live: Live) -> None:
    live.do(sel("fx-mh1"), put("pan", 5), fade(1.5))
    recovered, dropped = from_json(json.loads(json.dumps(to_json(live.session.programmer))))
    assert dropped == []
    fresh = Live(load_doc(APPENDIX_A))
    fresh.session.restore_programmer(recovered)
    assert fresh.session.programmer.fadeTime == 1.5
    assert queued(fresh)[-1].programmer.fadeTime == 1.5


def test_a_no_op_programmer_step_is_not_pushed(live: Live) -> None:
    live.do(sel("fx-mh1"))
    live.do(sel("fx-mh1"))
    live.do(CLEAR, CLEAR)
    assert live.session.timeline.undo_count == 2


def test_undoing_everything_returns_the_initial_show(live: Live) -> None:
    initial = copy.deepcopy(live.session.show)
    live.do(
        sel("fx-mh1", "fx-mh2"),
        put("color", {"r": 1, "g": 0, "b": 0}),
        {"type": "RECORD_PRESET", "pool": "color", "number": 7, "scope": "global"},
        {"type": "RECORD_GROUP", "number": 9, "name": "Heads again"},
        {"type": "PATCH_FIXTURE", "fixtureId": "fx-par1", "patch": None},
        {"type": "ASSIGN_PLAYBACK", "pageId": "page-1", "slot": 11, "playbackId": "pb-blue"},
        {"type": "RECORD_CUE", "cueListId": "cl-blue", "cueNumber": "1", "merge": "merge"},
    )
    final = copy.deepcopy(live.session.show)
    while live.session.timeline.undo_count:
        live.do(UNDO)
    assert live.session.show == initial
    assert live.session.programmer == EMPTY
    while live.session.timeline.redo_count:
        live.do(REDO)
    assert live.session.show == final


def test_dormant_values_come_back_with_an_undone_delete(live: Live) -> None:
    doc = load_doc(APPENDIX_A)
    doc["fixtures"].append(
        {
            **doc["fixtures"][2],
            "id": "fx-spare",
            "number": 299,
            "name": "Spare",
            "patch": {"universeId": "u1", "address": 200},
        }
    )
    live = Live(doc)
    live.do(sel("fx-spare"), put("color", {"r": 0, "g": 1, "b": 0}), put("intensity", 1))
    live.tick()
    assert live.lanes("fx-spare", "intensity") == [1.0]
    live.do({"type": "DELETE", "path": ["fixtures", {"id": "fx-spare"}]})
    live.tick()
    assert "fx-spare:0/intensity" in live.session.programmer.values  # kept, dormant
    assert live.universe()[199:202] == b"\x00\x00\x00"
    live.do(UNDO)
    live.tick()
    assert live.lanes("fx-spare", "color") == [0.0, 1.0, 0.0]
    assert live.universe()[199:202] == b"\x00\xff\x00"
    assert live.engine.stats.installErrors == 0


def test_new_warnings_are_reported_with_the_edit(live: Live) -> None:
    result = live.do(
        {
            "type": "PATCH_FIXTURE",
            "fixtureId": "fx-par1",
            "patch": {"universeId": "u1", "address": 2},
        }
    )
    assert [(w.severity, w.path) for w in result.issues] == [
        ("warning", "fixtures[2].patch.address")
    ]
    # The overlap is known now: the next edit does not repeat it.
    title = {"type": "SET", "path": ["meta", "title"], "value": "Renamed"}
    assert live.do(title).issues == ()


def test_installs_reach_the_engine_in_commit_order(live: Live) -> None:
    live.do(sel("fx-mh1"), put("pan", 1), RENAME, put("pan", 2))
    items = queued(live)
    assert [type(item) for item in items] == [Install, Install, Install]
    assert [item.compiled is None for item in items] == [True, False, True]
    assert items[1].compiled is live.session.compiled
    assert live.engine.bus.compiled is live.session.compiled


def test_a_performance_command_is_queued_while_an_edit_holds_the_lock(
    live: Live, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = threading.Event(), threading.Event()
    real = session_module.compile_show

    def slow(show: Any, **options: Any) -> Any:
        entered.set()
        assert release.wait(5)
        return real(show, **options)

    monkeypatch.setattr(session_module, "compile_show", slow)
    results: list[Any] = []
    editor = threading.Thread(target=lambda: results.append(submit(live, RENAME)))
    editor.start()
    assert entered.wait(5)  # the edit holds the session lock, compiling
    result = submit(live, {"type": "TRIGGER_PLAYBACK", "playbackId": "pb-blue"})
    assert result.ok
    first = queued(live)
    assert [item["command"]["type"] for item in first] == ["TRIGGER_PLAYBACK"]
    release.set()
    editor.join(5)
    assert results[0].ok
    assert [type(item) for item in queued(live)] == [Install]


def test_post_keeps_arrival_order_and_reports_failures(live: Live) -> None:
    reports: list[str] = []
    live.session._report = reports.append
    live.session.post(cast(Command, sel("fx-mh1")))
    live.session.post(cast(Command, put("pan", 1)))
    live.session.post(cast(Command, put("pan", 2)))
    live.session.post(cast(Command, put("intensity", 7)))  # invalid
    live.session.post(
        cast(Command, {"type": "GO", "playbackId": "pb-song"})
    )  # straight to the queue
    live.session.stop()
    assert dict(live.session.programmer.values) == {"fx-mh1:0/pan": {"kind": "literal", "value": 2}}
    assert reports == ["SET_ATTRIBUTE: intensity must be within 0..1, got 7"]
    assert live.session.timeline.undo_count == 3


def test_unknown_and_malformed_commands_are_results_not_exceptions(live: Live) -> None:
    assert submit(live, {"type": "NOPE"}).message == "unknown command type 'NOPE'"
    result = submit(live, {"type": "SET", "path": []})  # no value: a malformed command
    assert not result.ok
    assert result.message.startswith("SET needs")
    batch = submit(live, {"type": "BATCH", "label": "", "commands": [{"type": "UNDO"}]})
    assert batch.message == "a BATCH can only hold show edits, not UNDO"


# ------------------------------------------------------- SELECT_PLAYBACK


def stack() -> Live:
    """pb-song plays the tracking list cl-song: cue k puts MH k at full (k = 1–3)."""
    doc = busk_rig(spots=3)
    cues = [
        cue(f"c{k}", entry(targets(f"fx-mh{k}"), "intensity", literal(1.0)), number=str(k))
        for k in (1, 2, 3)
    ]
    songs = cue_list("cl-song", 1, *cues)
    songs["tracking"] = True
    doc["cueLists"].append(songs)
    doc["playbacks"].append(playback("pb-song", 1, "cl-song", fader="none"))
    return Live(doc)


def selected(live: Live) -> list[str]:
    return [target["fixtureId"] for target in live.session.programmer.selection]


SELECT_SONG = {"type": "SELECT_PLAYBACK", "playbackId": "pb-song", "mode": "replace"}


def test_select_playback_selects_the_current_cue_of_a_running_stack() -> None:
    live = stack()
    for _ in range(3):  # activate at cue 1, then GO to cues 2 and 3
        live.do({"type": "GO", "playbackId": "pb-song"})
        live.tick()
    live.do(SELECT_SONG)
    # cue 3's tracked state: its own MH 3, then MH 2 and MH 1 tracked in
    assert selected(live) == ["fx-mh3", "fx-mh2", "fx-mh1"]


def test_select_playback_on_an_idle_playback_selects_the_first_cue() -> None:
    live = stack()
    live.tick()
    live.do(SELECT_SONG)
    assert selected(live) == ["fx-mh1"]


def test_select_playback_after_a_release_selects_the_first_cue_again() -> None:
    live = stack()
    for _ in range(2):
        live.do({"type": "GO", "playbackId": "pb-song"})
        live.tick()
    live.do({"type": "RELEASE_PLAYBACK", "playbackId": "pb-song", "time": 0.0})
    live.tick()
    live.do(SELECT_SONG)
    assert selected(live) == ["fx-mh1"]


def test_select_playback_without_an_engine_snapshot_selects_the_first_cue() -> None:
    live = stack()
    live.do({"type": "GO", "playbackId": "pb-song"}, {"type": "GO", "playbackId": "pb-song"})
    live.do(SELECT_SONG)  # no tick yet: the engine has published nothing
    assert live.engine.snapshot is None
    assert selected(live) == ["fx-mh1"]


def test_select_playback_with_a_snapshot_older_than_an_edit_selects_the_first_cue() -> None:
    live = stack()
    for _ in range(3):
        live.do({"type": "GO", "playbackId": "pb-song"})
        live.tick()
    # cue 3 is deleted; the engine has not ticked since, so its snapshot still shows cue 3
    live.do({"type": "DELETE", "path": ["cueLists", {"id": "cl-song"}, "cues", {"id": "c3"}]})
    live.do(SELECT_SONG)
    assert selected(live) == ["fx-mh1"]
    live.tick()  # the engine re-points to cue 2 and publishes it
    live.do(SELECT_SONG)
    assert selected(live) == ["fx-mh2", "fx-mh1"]


# ------------------------------------------------------------ effects (Phase 5)

PULSE = effect_instance("fx1", "ef-pulse", {"kind": "group", "groupId": "g-mh"}, size=0.5)


def add_effect(**fields: Any) -> dict[str, Any]:
    """``ADD_EFFECT`` of Appendix A's pulse on the heads, with ``fields`` changed."""
    return {"type": "ADD_EFFECT", "effect": {**PULSE, **fields}}


def effect_sizes(live: Live) -> list[tuple[str, float]]:
    return [(effect["id"], effect["size"]) for effect in live.session.programmer.effects]


def frames(live: Live) -> list[ProgrammerFrame]:
    """The programmer frames queued since the last call."""
    return [item.programmer for item in queued(live) if isinstance(item, Install)]


def test_effect_commands_are_undone_and_redone(live: Live) -> None:
    live.do(add_effect())
    live.do(add_effect(size=0.8))  # replaces fx1 in place
    live.do(add_effect(id="fx2"))
    live.do({"type": "REMOVE_EFFECT", "id": "fx1"})
    assert effect_sizes(live) == [("fx2", 0.5)]
    assert live.do(UNDO).message == "undid: removed effect 'fx1'"
    assert effect_sizes(live) == [("fx1", 0.8), ("fx2", 0.5)]
    live.do(UNDO, UNDO)
    assert effect_sizes(live) == [("fx1", 0.5)]
    live.do(UNDO)
    assert live.session.programmer == EMPTY
    live.do(REDO, REDO, REDO, REDO)
    assert effect_sizes(live) == [("fx2", 0.5)]
    live.do(CLEAR)
    assert effect_sizes(live) == []
    live.do(UNDO)
    assert effect_sizes(live) == [("fx2", 0.5)]


def test_touched_effects_are_the_ones_a_command_added_or_changed(live: Live) -> None:
    queued(live)
    live.do(add_effect(), add_effect(id="fx2"))
    first, second = frames(live)
    assert (first.touchedEffects, second.touchedEffects) == ({"fx1"}, {"fx2"})
    assert [effect.key for effect in second.effects] == ["fx1", "fx2"]
    live.do(add_effect(id="fx2"))  # the same instance again is still the latest action
    live.do(sel("fx-mh1"), put("pan", 10))
    again, value = frames(live)
    assert (again.touchedEffects, value.touchedEffects) == ({"fx2"}, frozenset())
    live.do(RENAME)  # a show edit touches nothing
    (edit,) = frames(live)
    assert (edit.touchedEffects, [effect.key for effect in edit.effects]) == (
        frozenset(),
        ["fx1", "fx2"],
    )
    live.do({"type": "REMOVE_EFFECT", "id": "fx1"}, UNDO)
    removed, undone = frames(live)
    assert (removed.touchedEffects, [effect.key for effect in removed.effects]) == (
        frozenset(),
        ["fx2"],
    )
    assert undone.touchedEffects == {"fx1"}  # it came back


def test_blind_holds_effects_and_leaving_it_touches_every_one(live: Live) -> None:
    live.do(blind(True), add_effect(), add_effect(id="fx2"))
    queued(live)
    live.do(blind(False))
    (frame,) = frames(live)
    assert (frame.blind, frame.touchedEffects) == (False, {"fx1", "fx2"})
    live.do(blind(True))
    (frame,) = frames(live)
    assert frame.blind
    assert effect_sizes(live) == [("fx1", 0.5), ("fx2", 0.5)]  # still held
