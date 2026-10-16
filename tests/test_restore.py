"""Engine restore after a restart (phase-7-plan decision 5, §5.7, step 7).

A restarted engine gets its look back from the last snapshot the console
received: masters (speed masters with tempo and beat anchor), blackout,
output enabled, the page, and every active playback at its cue and fader
level, snapped, in activation order. All in one process on a fake clock:
engine A plays into a state, engine B is a fresh engine on the same show
that gets A's snapshot as a :class:`Restore`.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from builders import (
    Doc,
    busk_rig,
    compile_doc,
    cue,
    cue_list,
    entry,
    grand_master,
    literal,
    look,
    page,
    playback,
    rgb,
    speed_master,
    targets,
)
from busk.compiler.compile import CompiledShow
from busk.engine.snapshot import EngineSnapshot, PlaybackStatus, Restore
from harness import Harness, Observation, _command, fader, go, master, release, set_bpm, trigger

PARS = ("fx-par1", "fx-par2")
SPOTS = ("fx-mh1", "fx-mh2", "fx-mh3", "fx-mh4")


def looks_show() -> CompiledShow:
    """Static looks: warm and blue pars (same priority: the later one's
    colour wins), a two-cue spot stack, two pages; everything fades in."""
    doc = busk_rig(spots=4, pars=2)
    doc["masters"].append(grand_master())
    look(doc, "pb-warm", 1, entry(targets(*PARS), "intensity", literal(1.0)),
         entry(targets(*PARS), "color", literal(rgb(1.0, 0.5, 0.0))), fade_in=2.0)  # fmt: skip
    look(doc, "pb-blue", 2, entry(targets(*PARS), "color", literal(rgb(0.0, 0.0, 1.0))),
         fade_in=2.0, release_time=5.0)  # fmt: skip
    stack = cue_list(
        "cl-spots", 3,
        cue("c-1", entry(targets(*SPOTS), "intensity", literal(0.5)), number="1", fade_in=2.0),
        cue("c-2", entry(targets(*SPOTS), "pan", literal(30.0)), number="2", fade_in=2.0),
    )  # fmt: skip
    doc["cueLists"].append(stack)
    doc["playbacks"].append(playback("pb-spots", 3, "cl-spots"))
    doc["pages"] = [page("pg-1", 1, "pb-warm", "pb-blue"), page("pg-2", 2, "pb-spots")]
    return compile_doc(doc)


def chase_show() -> CompiledShow:
    """A BPM chase (one beat per step) over four spots, on ``m-speed``."""
    doc = busk_rig(spots=4)
    doc["masters"].append(speed_master())
    steps = [
        cue(f"c{k}", entry(targets(SPOTS[k - 1]), "intensity", literal(1.0)), number=str(k))
        for k in range(1, 5)
    ]
    chase = cue_list("cl-chase", 1, *steps)
    rate = {"kind": "bpm", "masterId": "m-speed", "multiplier": 1.0}
    chase.update(mode="chase", chase={"rate": rate, "direction": "forward", "crossfade": 0.0})
    doc["cueLists"].append(chase)
    doc["playbacks"].append(playback("pb", 1, "cl-chase", fader="none"))
    return compile_doc(doc)


def snapshot_of(seen: Observation) -> EngineSnapshot:
    assert seen.snapshot is not None
    return seen.snapshot


def status(seen: Observation, ident: str) -> PlaybackStatus:
    return next(s for s in snapshot_of(seen).playbacks if s.id == ident)


def restored(compiled: CompiledShow, snapshot: EngineSnapshot, at: float) -> Harness:
    """A fresh engine on ``compiled`` that restores ``snapshot`` at its first tick."""
    harness = Harness(compiled)
    harness.engine.bus.restore(Restore(snapshot=snapshot))
    harness.tick(at)
    return harness


def play(compiled: CompiledShow, script: list[tuple[float, Any]], until: float) -> Harness:
    harness = Harness(compiled)
    harness.run(script, ticks=np.arange(0.0, until + 1e-9, 0.1).round(6).tolist())
    return harness


# ------------------------------------------------------------- static looks


def test_a_restored_engine_makes_the_same_frame() -> None:
    compiled = looks_show()
    a = play(compiled, [
        (0.0, fader("pb-warm", 0.8)),
        (0.0, fader("pb-spots", 1.0)),
        (0.5, trigger("pb-blue")),
        (1.0, go("pb-spots")),
        (1.0, master("m-gm", 0.7)),
    ], until=10.0)  # fmt: skip
    before = a.tick(10.0)
    assert status(before, "pb-spots").cue == "2"
    b = restored(compiled, snapshot_of(before), at=20.0)
    after = b.tick(20.0)
    assert after.frame.universes == before.frame.universes
    np.testing.assert_array_equal(after.logical, before.logical)
    assert snapshot_of(after).grandMaster == pytest.approx(0.7)
    assert {s.id: (s.state, s.cue, s.faderLevel) for s in snapshot_of(after).playbacks} == {
        s.id: (s.state, s.cue, s.faderLevel) for s in snapshot_of(before).playbacks
    }
    assert b.engine.stats.installErrors == 0


@pytest.mark.parametrize("first", ["pb-warm", "pb-blue"])
def test_the_ltp_stack_comes_back_in_activation_order(first: str) -> None:
    compiled = looks_show()
    second = "pb-blue" if first == "pb-warm" else "pb-warm"
    up = {"pb-warm": fader("pb-warm", 1.0), "pb-blue": trigger("pb-blue")}  # warm lights the pars
    a = play(compiled, [(0.0, up[first]), (0.5, up[second])], until=5.0)
    before = a.tick(5.0)
    assert status(before, second).seq > status(before, first).seq
    blue = before.frame.universes[0][64:67] == bytes([0, 0, 255])
    assert blue == (second == "pb-blue")  # the second one's colour is on top
    after = restored(compiled, snapshot_of(before), at=9.0).tick(9.0)
    assert after.frame.universes == before.frame.universes
    np.testing.assert_array_equal(after.logical, before.logical)


def test_releasing_playbacks_are_not_restored() -> None:
    compiled = looks_show()
    a = play(compiled, [(0.0, trigger("pb-warm")), (0.0, trigger("pb-blue")),
                        (3.0, release("pb-blue"))], until=4.0)  # fmt: skip
    before = a.tick(4.0)
    assert status(before, "pb-blue").state == "releasing"
    after = restored(compiled, snapshot_of(before), at=9.0).tick(9.0)
    assert status(after, "pb-blue").state == "idle"
    assert status(after, "pb-warm").state == "active"


def test_page_blackout_and_output_come_back() -> None:
    compiled = looks_show()
    a = play(compiled, [
        (0.0, trigger("pb-warm")),
        (0.5, _command(type="PAGE", number=2)),
        (0.5, _command(type="BLACKOUT", on=True)),
        (0.5, _command(type="OUTPUT", on=False)),
    ], until=3.0)  # fmt: skip
    before = a.tick(3.0)
    after = restored(compiled, snapshot_of(before), at=9.0).tick(9.0)
    snapshot = snapshot_of(after)
    assert snapshot.page is not None
    assert snapshot.page.id == "pg-2"
    assert snapshot.blackout is True
    assert snapshot.outputEnabled is False
    assert after.frame.outputEnabled is False
    assert after.frame.universes == before.frame.universes


def test_masters_and_playbacks_the_show_lacks_are_skipped() -> None:
    compiled = looks_show()
    before = play(compiled, [(0.0, trigger("pb-warm"))], until=3.0).tick(3.0)
    snapshot = snapshot_of(before)
    ghost = PlaybackStatus(id="pb-gone", number=99, name="gone", state="active",
                           faderLevel=1.0, flash=False, cue="1", seq=99)  # fmt: skip
    odd = EngineSnapshot(
        seq=snapshot.seq, time=snapshot.time, grandMaster=1.0, blackout=False,
        playbacks=(*snapshot.playbacks, ghost),
        masterLevels=(*snapshot.masterLevels, ("m-gone", 0.5)),
    )  # fmt: skip
    b = restored(compiled, odd, at=9.0)
    assert b.engine.stats.installErrors == 0
    assert status(b.tick(9.0), "pb-warm").state == "active"


# ------------------------------------------------------------- tempo and chases


def chase_cues(harness: Harness, times: list[float]) -> dict[float, str | None]:
    return {t: status(harness.tick(t), "pb").cue for t in times}


def test_the_tempo_beat_anchor_and_chase_step_come_back() -> None:
    compiled = chase_show()
    script = [(0.3, set_bpm("m-speed", 100.0)), (0.4, master("m-speed", 0.75)),
              (0.5, trigger("pb"))]  # fmt: skip
    a = play(compiled, script, until=7.3)
    before = a.tick(7.37)
    b = restored(compiled, snapshot_of(before), at=7.37)
    after = b.tick(7.37)
    assert snapshot_of(after).speed == snapshot_of(before).speed  # bpm, level, anchor
    assert status(after, "pb").cue == status(before, "pb").cue
    later = [round(7.4 + 0.05 * k, 6) for k in range(100)]
    assert chase_cues(b, later) == chase_cues(a, later)  # the same step on the same beats


def test_a_later_restore_steps_on_the_same_beat_grid() -> None:
    compiled = chase_show()
    a = play(compiled, [(0.3, set_bpm("m-speed", 100.0)), (0.5, trigger("pb"))], until=7.3)
    before = a.tick(7.37)
    b = restored(compiled, snapshot_of(before), at=9.0)
    assert status(b.tick(9.0), "pb").cue == status(before, "pb").cue  # starts at the step

    def changes(harness: Harness) -> set[float]:
        times = [round(9.05 + 0.05 * k, 6) for k in range(120)]
        cues = chase_cues(harness, times)
        return {t for t, previous in zip(times[1:], times, strict=False)
                if cues[t] != cues[previous]}  # fmt: skip

    assert changes(b) == changes(a)  # the steps fall on the same beats


# ------------------------------------------------------------- crossfade faders


def crossfade_show() -> CompiledShow:
    doc: Doc = busk_rig(spots=2)
    stack = cue_list(
        "cl-x", 1,
        cue("c-1", entry(targets("fx-mh1"), "intensity", literal(1.0)), number="1", fade_in=2.0),
        cue("c-2", entry(targets("fx-mh2"), "intensity", literal(1.0)), number="2", fade_in=2.0),
    )  # fmt: skip
    doc["cueLists"].append(stack)
    doc["playbacks"].append(playback("pb-x", 1, "cl-x", fader="crossfade"))
    return compile_doc(doc)


def test_a_crossfade_fader_between_its_ends_comes_back_detached() -> None:
    compiled = crossfade_show()
    a = play(compiled, [(0.0, trigger("pb-x")), (3.0, fader("pb-x", 0.4))], until=4.0)
    before = a.tick(4.0)
    assert status(before, "pb-x").progress == pytest.approx(0.4)
    b = restored(compiled, snapshot_of(before), at=9.0)
    runtime = b.engine.runtime.playbacks.runtimes["pb-x"]
    assert runtime.crossRest is None
    assert runtime.faderLevel == pytest.approx(0.4)
    b.submit(fader("pb-x", 0.6))  # detached: drives nothing until it reaches an end
    seen = status(b.tick(9.5), "pb-x")
    assert (seen.cue, seen.progress) == ("2", None)


def test_a_crossfade_fader_at_an_end_rests_there() -> None:
    compiled = crossfade_show()
    before = play(compiled, [(0.0, trigger("pb-x"))], until=3.0).tick(3.0)
    b = restored(compiled, snapshot_of(before), at=9.0)
    assert b.engine.runtime.playbacks.runtimes["pb-x"].crossRest == 0.0
