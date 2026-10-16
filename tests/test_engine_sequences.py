"""Sequences through the engine: GO, BACK, GOTO and auto-GOs (phase-4-plan
§5.5–§5.6, decisions 4–6 and 9; step 9).

The rig is three Appendix A spots, ``fx-mh1…3``, with one tracking song
``cl-song`` on playback ``pb``. Its fader is ``none``, so the cue's
intensities reach the frame unscaled.
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from builders import (
    Doc,
    busk_rig,
    compile_doc,
    cue,
    cue_list,
    entry,
    lanes_of,
    literal,
    playback,
    rgb,
    speed_master,
    targets,
)
from busk.compiler.compile import CompiledShow
from busk.engine.playback_runtime import PlaybackRuntime
from harness import (
    Harness,
    Observation,
    Script,
    back,
    fader,
    flash,
    go,
    goto,
    release,
    toggle,
    trigger,
)

# ----------------------------------------------------------------- helpers


def step(number: int, *entries: Doc, trigger: Doc | None = None, **fields: Any) -> Doc:
    """Cue ``c<number>`` numbered ``number``. ``fields`` are cue timing
    fields (``fadeIn``, ``curve``…), or ``block`` and ``releases``."""
    made = cue(f"c{number}", *entries, number=str(number))
    for name in ("block", "releases"):
        if name in fields:
            made[name] = fields.pop(name)
    made["timing"].update(fields)
    if trigger is not None:
        made["trigger"] = trigger
    return made


def song(
    *cues: Doc,
    wrap: bool = False,
    release_at_end: bool = False,
    tracking: bool = True,
    extra: tuple[Doc, ...] = (),
    templates: tuple[Doc, ...] = (),
    **options: Any,
) -> CompiledShow:
    """The rig with the song ``cues`` on ``pb`` and ``extra`` playbacks, each a
    ``(cue list, playback)`` pair of docs flattened into the tuple. With
    effect ``templates``, the show also has a 120 BPM speed master."""
    doc = busk_rig(spots=3)
    if templates:
        doc["effects"] = list(templates)
        doc["masters"] = [speed_master()]
    songs = cue_list("cl-song", 1, *cues, release_at_end=release_at_end)
    songs.update(tracking=tracking, wrap=wrap)
    doc["cueLists"].append(songs)
    doc["playbacks"].append(playback("pb", 1, "cl-song", **{"fader": "none", **options}))
    for k in range(0, len(extra), 2):
        doc["cueLists"].append(extra[k])
        doc["playbacks"].append(extra[k + 1])
    return compile_doc(doc)


def level(compiled: CompiledShow, seen: Observation, fixture: str = "fx-mh1") -> float:
    return lanes_of(compiled, seen.logical, fixture, "intensity")[0]


def pan(compiled: CompiledShow, seen: Observation, fixture: str = "fx-mh1") -> float:
    return lanes_of(compiled, seen.logical, fixture, "pan")[0]


def runtime(harness: Harness, ident: str = "pb") -> PlaybackRuntime:
    return harness.engine.runtime.playbacks.runtimes[ident]


def at(fixture: str, attribute: str, value: Any) -> Doc:
    return entry(targets(fixture), attribute, literal(value))


def follow(delay: float) -> Doc:
    return {"kind": "follow", "delay": delay}


def wait(delay: float) -> Doc:
    return {"kind": "wait", "delay": delay}


# ------------------------------------------------------------ GO with timing


def test_go_steps_through_a_tracking_list_with_each_cues_timing() -> None:
    compiled = song(
        step(1, at("fx-mh1", "intensity", 1.0)),
        step(2, at("fx-mh2", "intensity", 1.0), fadeIn=2.0),
        step(3, at("fx-mh1", "intensity", 0.0), fadeIn=1.0, fadeOut=4.0),
    )
    h = Harness(compiled)
    seen = h.run(
        [(0.0, go("pb")), (1.0, go("pb")), (4.0, go("pb")), (10.0, go("pb"))],
        ticks=[2.0, 5.0, 9.0, 11.0],
    )
    assert level(compiled, seen[0.0]) == 1.0  # cue 1 cuts in
    assert (level(compiled, seen[2.0], "fx-mh2"), level(compiled, seen[2.0])) == (0.5, 1.0)
    assert level(compiled, seen[5.0]) == pytest.approx(0.75)  # cue 3 falls with fadeOut 4
    assert level(compiled, seen[5.0], "fx-mh2") == 1.0  # tracked, untouched
    assert (level(compiled, seen[9.0]), level(compiled, seen[9.0], "fx-mh2")) == (0.0, 1.0)
    # GO at the last cue, without wrap or releaseAtEnd, re-asserts it.
    assert (runtime(h).cue, runtime(h).state) == (2, "active")
    assert level(compiled, seen[11.0], "fx-mh2") == 1.0


def test_per_slot_timing_and_curves_through_the_engine() -> None:
    timed = at("fx-mh1", "pan", 90.0)
    timed["timing"] = {"fade": 1.0, "delay": 1.0, "curve": "linear"}
    compiled = song(
        step(
            1,
            at("fx-mh1", "intensity", 1.0),
            timed,
            at("fx-mh2", "pan", 90.0),
            fadeIn=2.0,
            curve="easeIn",
            perFamily={"position": {"fade": 4.0, "delay": 0.0}},
        )
    )
    seen = Harness(compiled).run([(0.0, go("pb"))], ticks=[1.0, 1.5, 2.0])
    assert level(compiled, seen[1.0]) == pytest.approx(0.25)  # easeIn: (1/2)²
    assert pan(compiled, seen[1.0]) == pytest.approx(0.0)  # the entry's 1 s delay
    assert pan(compiled, seen[1.5]) == pytest.approx(45.0)  # then linear over 1 s
    assert pan(compiled, seen[2.0], "fx-mh2") == pytest.approx(90.0 * 0.5**2)  # family, easeIn


def test_a_go_mid_fade_leaves_unchanged_slots_fading() -> None:
    """Decision 5: a 0-s GO halfway through a 10-s pan fade does not make the
    pan jump to its target."""
    compiled = song(
        step(1, at("fx-mh1", "pan", 90.0), fadeIn=10.0),
        step(2, at("fx-mh2", "intensity", 1.0)),
    )
    seen = Harness(compiled).run([(0.0, go("pb")), (5.0, go("pb"))], ticks=[7.5, 10.0])
    assert pan(compiled, seen[5.0]) == pytest.approx(45.0)
    assert level(compiled, seen[5.0], "fx-mh2") == 1.0
    assert pan(compiled, seen[7.5]) == pytest.approx(67.5)
    assert pan(compiled, seen[10.0]) == pytest.approx(90.0)


def test_tracked_slots_do_not_steal_from_a_newer_bump_but_changed_ones_do() -> None:
    """Decision 4: a GO numbers only the slots it changes."""
    red = (
        cue_list("cl-red", 2, cue("c-red", at("fx-mh1", "color", rgb(1, 0, 0)))),
        playback("pb-red", 2, "cl-red", fader="none"),
    )
    compiled = song(
        step(1, at("fx-mh1", "color", rgb(0, 0, 1)), at("fx-mh1", "intensity", 1.0)),
        step(2, at("fx-mh1", "intensity", 0.5)),  # colour tracks
        step(3, at("fx-mh1", "color", rgb(0, 1, 0))),  # colour changes
        extra=red,
    )
    seen = Harness(compiled).run(
        [(0.0, go("pb")), (1.0, trigger("pb-red")), (2.0, go("pb")), (3.0, go("pb"))]
    )

    def color(time: float) -> list[float]:
        return lanes_of(compiled, seen[time].logical, "fx-mh1", "color")[:3]

    assert color(0.0) == [0.0, 0.0, 1.0]
    assert color(1.0) == [1.0, 0.0, 0.0]  # the bump is newer
    assert (color(2.0), level(compiled, seen[2.0])) == ([1.0, 0.0, 0.0], 0.5)
    assert color(3.0) == [0.0, 1.0, 0.0]  # a changed slot takes a fresh number


# ------------------------------------------------------- the state machine


THREE = (
    step(1, at("fx-mh1", "intensity", 1.0)),
    step(2, at("fx-mh2", "intensity", 1.0)),
    step(3, at("fx-mh3", "intensity", 1.0)),
)


def cues_after(script: Script, **options: Any) -> list[tuple[str, int]]:
    """``(state, cue index)`` of ``pb`` after each command of ``script``."""
    h = Harness(song(*THREE, **options))
    states = []
    for time, command in script:
        h.run([(time, command)])
        states.append((runtime(h).state, runtime(h).cue))
    return states


def test_back_and_goto_on_an_idle_playback() -> None:
    assert cues_after([(0.0, back("pb")), (1.0, goto("pb", "2"))]) == [
        ("idle", -1),
        ("active", 1),
    ]


def test_go_and_back_at_the_ends() -> None:
    script = [(0.0, go("pb")), (1.0, back("pb")), (2.0, goto("pb", "3")), (3.0, go("pb"))]
    assert cues_after(script) == [("active", 0), ("active", 0), ("active", 2), ("active", 2)]
    assert cues_after(script, wrap=True) == [
        ("active", 0),
        ("active", 2),  # BACK wraps to the last cue
        ("active", 2),  # GOTO the current cue re-asserts
        ("active", 0),  # GO wraps to the first
    ]
    assert cues_after(script, release_at_end=True)[-1] == ("releasing", 2)


def test_go_on_a_releasing_playback_starts_again_at_the_first_cue() -> None:
    script = [(0.0, goto("pb", "2")), (1.0, toggle("pb")), (1.5, go("pb")), (2.0, back("pb"))]
    assert cues_after(script) == [
        ("active", 1),
        ("releasing", 1),
        ("active", 0),
        ("active", 0),  # BACK at the first cue: nothing
    ]


def test_trigger_reasserts_the_current_cue_and_toggle_starts_at_the_first() -> None:
    script = [(0.0, goto("pb", "3")), (1.0, trigger("pb")), (2.0, toggle("pb"))]
    assert cues_after(script)[1] == ("active", 2)
    restarted = cues_after([*script, (2.5, toggle("pb"))])
    assert restarted[2:] == [("releasing", 2), ("active", 0)]


def test_goto_the_current_cue_reasserts() -> None:
    h = Harness(song(*THREE))
    h.run([(0.0, goto("pb", "2"))])
    before = runtime(h).activationSeq
    h.run([(1.0, goto("pb", "2"))])
    assert (runtime(h).cue, runtime(h).activationSeq > before) == (1, True)


def test_back_fades_with_the_destinations_timing_and_schedules_nothing() -> None:
    compiled = song(
        step(1, at("fx-mh1", "intensity", 1.0), fadeIn=2.0, fadeOut=4.0),
        step(2, at("fx-mh1", "intensity", 0.0), trigger=follow(0.5)),
    )
    h = Harness(compiled)
    seen = h.run([(0.0, go("pb")), (3.0, back("pb"))], ticks=[2.5, 4.0, 10.0])
    assert level(compiled, seen[2.5]) == 0.0  # cue 2 followed at 2 + 0.5
    assert level(compiled, seen[4.0]) == pytest.approx(0.5)  # cue 1's fadeIn: 2 s
    assert (level(compiled, seen[10.0]), runtime(h).cue, runtime(h).auto) == (1.0, 0, None)


def test_flash_plays_the_cue_main_is_at() -> None:
    compiled = song(
        step(1, at("fx-mh1", "intensity", 0.5)),
        step(2, at("fx-mh2", "intensity", 1.0)),
        fader="master",  # at 0: main contributes no intensity
    )
    seen = Harness(compiled).run(
        [
            (0.0, flash("pb", True)),
            (0.5, flash("pb", False)),
            (1.0, go("pb")),
            (2.0, go("pb")),
            (3.0, flash("pb", True)),
        ]
    )
    assert (level(compiled, seen[0.0]), level(compiled, seen[0.0], "fx-mh2")) == (0.5, 0.0)
    assert (level(compiled, seen[2.0]), level(compiled, seen[2.0], "fx-mh2")) == (0.0, 0.0)
    assert (level(compiled, seen[3.0]), level(compiled, seen[3.0], "fx-mh2")) == (0.5, 1.0)


# ----------------------------------------------------------------- auto-GO

CHAIN = (
    step(1, at("fx-mh1", "intensity", 1.0), fadeIn=1.0),
    step(2, at("fx-mh2", "intensity", 1.0), fadeIn=1.0, trigger=follow(0.5)),
    step(3, at("fx-mh3", "intensity", 1.0), fadeIn=1.0, trigger=wait(0.25)),
)


def test_auto_gos_fire_at_their_exact_times_and_chain() -> None:
    """Cue 2 follows cue 1's completion (1 s) by 0.5 s; cue 3 waits 0.25 s
    after cue 2 starts. The fades start then, whatever the ticks."""
    compiled = song(*CHAIN)
    seen = Harness(compiled).run([(0.0, go("pb"))], ticks=[1.6, 2.0])
    assert level(compiled, seen[1.6], "fx-mh2") == pytest.approx(0.1)
    assert level(compiled, seen[2.0], "fx-mh2") == pytest.approx(0.5)
    assert level(compiled, seen[2.0], "fx-mh3") == pytest.approx(0.25)
    # One late tick fires the whole chain.
    late = Harness(compiled).run([(0.0, go("pb"))], ticks=[2.0])
    np.testing.assert_array_equal(late[2.0].logical, seen[2.0].logical)


@pytest.mark.parametrize(
    ("command", "state", "cue"),
    [
        (go("pb"), "active", 1),  # the manual GO moves on; cue 3 waits for GO
        (release("pb", 0.5), "idle", -1),
    ],
)
def test_a_pending_auto_go_is_cancelled(command: Any, state: str, cue: int) -> None:
    compiled = song(
        step(1, at("fx-mh1", "intensity", 1.0), fadeIn=1.0),
        step(2, at("fx-mh2", "intensity", 1.0), trigger=follow(0.5)),
        step(3, at("fx-mh3", "intensity", 1.0)),
    )
    h = Harness(compiled)
    h.run([(0.0, go("pb"))])
    assert runtime(h).auto == 1.5
    h.run([(1.0, command)], ticks=[5.0])
    assert (runtime(h).state, runtime(h).cue, runtime(h).auto) == (state, cue, None)


def test_back_cancels_a_pending_auto_go() -> None:
    compiled = song(
        step(1, at("fx-mh1", "intensity", 1.0)),
        step(2, at("fx-mh2", "intensity", 1.0), fadeIn=1.0),
        step(3, at("fx-mh3", "intensity", 1.0), trigger=follow(0.5)),
    )
    h = Harness(compiled)
    h.run([(0.0, goto("pb", "2"))])
    assert runtime(h).auto == 1.5
    h.run([(1.0, back("pb"))], ticks=[5.0])
    assert (runtime(h).cue, runtime(h).auto) == (0, None)


def test_auto_gos_fire_at_most_one_lap_per_tick() -> None:
    """A wrapped list of instant ``follow 0`` cues would loop forever: each
    tick fires one lap (one auto-GO per cue) and leaves the next one due."""
    compiled = song(
        step(1, at("fx-mh1", "intensity", 1.0), trigger=follow(0.0)),
        step(2, at("fx-mh2", "intensity", 1.0), trigger=follow(0.0)),
        step(3, at("fx-mh3", "intensity", 1.0), trigger=follow(0.0)),
        wrap=True,
        tracking=False,
    )
    h = Harness(compiled)
    moves: list[int] = []
    pb = runtime(h)
    original = pb.move
    pb.move = lambda now, cue, seqs: (moves.append(cue), original(now, cue, seqs))[-1]  # type: ignore[method-assign]
    h.run([(0.0, go("pb"))])
    assert moves == [1, 2, 0]
    h.run([], ticks=[0.01])
    assert moves == [1, 2, 0, 1, 2, 0]
    assert runtime(h).auto == 0.0  # still due


# ------------------------------------------------------ GOTO equals stepping

SLOTS = [(f, a) for f in ("fx-mh1", "fx-mh2", "fx-mh3") for a in ("intensity", "pan", "color")]
VALUES = {"intensity": [0.0, 0.5, 1.0], "pan": [-45.0, 0.0, 90.0], "color": [rgb(1, 0, 0)]}


@st.composite
def stacks(draw: st.DrawFn) -> list[Doc]:
    """A random tracking stack: cues set and release random slots, some block."""
    made = []
    for n in range(1, draw(st.integers(1, 5)) + 1):
        chosen = draw(st.lists(st.sampled_from(SLOTS), max_size=4, unique=True))
        entries = [at(f, a, draw(st.sampled_from(VALUES[a]))) for f, a in chosen]
        freed = draw(st.lists(st.sampled_from(SLOTS), max_size=2, unique=True))
        releases = [{"targets": targets(f), "attributes": [a]} for f, a in freed]
        made.append(step(n, *entries, block=draw(st.booleans()), releases=releases))
    return made


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(cues=stacks(), data=st.data())
def test_goto_equals_stepping(cues: list[Doc], data: st.DataObject) -> None:
    compiled = song(*cues)
    k = data.draw(st.integers(0, len(cues) - 1))
    stepped = Harness(compiled).run([(0.1 * n, go("pb")) for n in range(k + 1)], ticks=[1.0])
    jumped = Harness(compiled).run([(0.0, goto("pb", str(k + 1)))], ticks=[1.0])
    np.testing.assert_array_equal(stepped[1.0].logical, jumped[1.0].logical)


# --------------------------------------------------- schedule independence

BUSY: Script = [
    (0.0, go("pb")),
    (0.7, fader("pb", 0.4)),
    (3.3, go("pb")),  # mid-fade, cancels the follow
    (4.1, back("pb")),
    (5.0, goto("pb", "3")),  # the wait chain runs from here
    (9.2, release("pb", 1.5)),
    (11.0, go("pb")),
]
SHARED = [0.35, 1.2, 2.6, 3.5, 4.4, 5.3, 6.8, 8.0, 9.9, 11.5, 12.0]


def busy_song() -> CompiledShow:
    return song(
        step(1, at("fx-mh1", "intensity", 1.0), at("fx-mh1", "pan", 90.0), fadeIn=2.0),
        step(
            2,
            at("fx-mh2", "intensity", 0.8),
            at("fx-mh1", "pan", -45.0),
            fadeIn=1.5,
            fadeOut=3.0,
            curve="easeInOut",
            trigger=follow(1.0),
        ),
        step(3, at("fx-mh1", "intensity", 0.2), fadeOut=2.0, curve="easeOut"),
        step(4, at("fx-mh3", "color", rgb(0, 1, 0)), fadeIn=1.0, trigger=wait(0.75)),
        step(5, at("fx-mh3", "intensity", 1.0), fadeIn=0.5, trigger=follow(0.25)),
        wrap=True,
        fader="master",
    )


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_frames_do_not_depend_on_the_tick_schedule(seed: int) -> None:
    compiled = busy_song()
    steady = Harness(compiled).run(BUSY, ticks=[k / 100 for k in range(1201)] + SHARED)
    rng = random.Random(seed)
    irregular = Harness(compiled).run(BUSY, ticks=[rng.uniform(0, 12) for _ in range(40)] + SHARED)
    for time in SHARED:
        np.testing.assert_allclose(
            irregular[time].logical, steady[time].logical, rtol=0, atol=1e-9, err_msg=f"t={time}"
        )
        assert irregular[time].universe == steady[time].universe, f"t={time}"


# ---------------------------------------------------------------- effects
# phase-5-plan decisions 8–10 and §5.7: every move retargets the main bank.

SAW = {
    "id": "t-saw",
    "name": "Saw",
    "layers": [
        {
            "attribute": "intensity",
            "waveform": {"kind": "sawUp"},
            "phaseOffset": 0,
            "mode": "absolute",
        },
    ],
}
CYCLE = {
    "id": "t-cycle",
    "name": "Cycle",
    "layers": [
        {"attribute": "color", "palette": [rgb(1, 0, 0), rgb(0, 1, 0), rgb(0, 0, 1)],
         "blend": "snap", "mode": "absolute"},
    ],
}  # fmt: skip
TEMPLATES = (SAW, CYCLE)


def fx(instance_id: str, template_id: str, fixture: str, **fields: Any) -> Doc:
    """An instance at 1 Hz on element 0 of ``fixture``; ``sawUp`` gives ``P``'s
    fraction, so the intensity is the position within the cycle."""
    made: Doc = {
        "id": instance_id,
        "templateId": template_id,
        "targets": targets(fixture),
        "rate": {"kind": "hz", "value": 1.0},
        "direction": "forward",
        "size": 1.0,
        "phase": {"start": 0, "end": 0},
        "groups": 1,
        "blocks": 1,
        "wings": 1,
    }
    made.update(fields)
    return made


def with_fx(made: Doc, *instances: Doc) -> Doc:
    made["effects"] = list(instances)
    return made


def colour(compiled: CompiledShow, seen: Observation) -> list[float]:
    return lanes_of(compiled, seen.logical, "fx-mh1", "color")[:3]


def test_a_go_enters_changes_and_leaves_effects() -> None:
    """Decision 9. At the GO to cue 2 (fade in 1 s, out 2 s): ``x`` leaves
    over 2 s, still moving; ``y`` changes its ``high`` from 1 to ½, a
    cross-fade over 1 s on the same clock; ``z`` enters over 1 s on a new
    clock. The transition completes when the last of them has."""
    compiled = song(
        with_fx(step(1), fx("x", "t-saw", "fx-mh1"), fx("y", "t-saw", "fx-mh2", high=1.0)),
        with_fx(
            step(2, fadeIn=1.0, fadeOut=2.0),
            fx("y", "t-saw", "fx-mh2", high=0.5),
            fx("z", "t-saw", "fx-mh3"),
        ),
        tracking=False,
        templates=TEMPLATES,
    )
    h = Harness(compiled)
    seen = h.run([(0.0, go("pb")), (1.0, go("pb"))], [1.25, 1.5, 2.25, 3.0])
    got = {
        t: [level(compiled, obs, name) for name in ("fx-mh1", "fx-mh2", "fx-mh3")]
        for t, obs in seen.items()
    }
    assert got[1.25] == pytest.approx([0.875 * 0.25, 0.875 * 0.25, 0.25 * 0.25])
    assert got[1.5] == pytest.approx([0.75 * 0.5, 0.75 * 0.5, 0.5 * 0.5])
    assert got[2.25] == pytest.approx([0.375 * 0.25, 0.5 * 0.25, 0.25])
    assert got[3.0] == pytest.approx([0.0, 0.0, 0.0])
    assert runtime(h).completes == 3.0


def test_a_later_go_tops_a_tracked_effect_and_an_auto_go_goes_under_it() -> None:
    """Decisions 7 and 10 in a tracking list. Cue 2's colour cycle enters at
    a GO with a fresh number, over cue 1's amber. Cue 3 follows at once and
    changes the colour, keeping the slot's older number: under the cycle.
    Cue 4's GO changes it again with a fresh number: on top."""
    compiled = song(
        step(1, at("fx-mh1", "color", rgb(1, 0.5, 0))),
        with_fx(step(2), fx("e", "t-cycle", "fx-mh1")),
        step(3, at("fx-mh1", "color", rgb(1, 1, 1)), trigger=follow(0.0)),
        step(4, at("fx-mh1", "color", rgb(0.5, 0.5, 0.5))),
        templates=TEMPLATES,
    )
    seen = Harness(compiled).run([(t, go("pb")) for t in (0.0, 1.0, 2.0)], [0.5, 1.4, 2.4])
    assert colour(compiled, seen[0.5]) == [1.0, 0.5, 0.0]
    snapshot = seen[1.4].snapshot
    assert snapshot is not None
    assert snapshot.playbacks[0].cue == "3"
    assert colour(compiled, seen[1.4]) == [0.0, 1.0, 0.0]  # the cycle, at x = 1.2
    assert colour(compiled, seen[2.4]) == [0.5, 0.5, 0.5]


def test_follow_waits_for_the_effects_fades() -> None:
    """The completion time includes the effects: cue 2 follows cue 1's 2 s
    ``sizeFadeIn``, and cue 3 follows the effect's 1.5 s fade out of cue 2."""
    compiled = song(
        with_fx(step(1), fx("e", "t-saw", "fx-mh1", sizeFadeIn=2.0)),
        step(2, trigger=follow(0.0), fadeOut=1.5),
        step(3, trigger=follow(0.0)),
        tracking=False,
        templates=TEMPLATES,
    )
    seen = Harness(compiled).run([(0.0, go("pb"))], [1.9, 2.0, 3.4, 3.5])
    cues = {t: obs.snapshot.playbacks[0].cue for t, obs in seen.items() if obs.snapshot}
    assert [cues[t] for t in (1.9, 2.0, 3.4, 3.5)] == ["1", "2", "2", "3"]


def test_goto_lands_on_the_same_instances_as_stepping() -> None:
    """Decision 8: GOTO 3 gives cue 3's tracked state, cue 1's BPM effect
    included. At ×1 its cycles fall on beats either way, so it runs at the
    same phase as when stepping, though it started later."""
    compiled = song(
        with_fx(step(1), fx("e", "t-saw", "fx-mh1", rate={"kind": "bpm", "masterId": "m-speed",
                                                           "multiplier": 1.0})),
        step(2, at("fx-mh2", "intensity", 1.0)),
        step(3, at("fx-mh3", "intensity", 1.0)),
        templates=TEMPLATES,
    )  # fmt: skip
    stepped = Harness(compiled)
    by_go = stepped.run([(t, go("pb")) for t in (0.0, 1.0, 2.0)], [3.25])
    jumped = Harness(compiled)
    by_goto = jumped.run([(2.3, goto("pb", "3"))], [0.0, 3.25])  # beats count from 0
    assert list(runtime(stepped).bank.runtimes) == list(runtime(jumped).bank.runtimes) == ["e"]
    assert level(compiled, by_go[3.25]) == level(compiled, by_goto[3.25]) == pytest.approx(0.5)
