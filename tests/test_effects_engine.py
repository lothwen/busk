"""Effects through the engine (phase-5-plan §5.7–5.9; step 7).

Each test runs a show on the deterministic :class:`~harness.Harness` and
reads the logical frame. Expected values are worked out by hand from the
formulas of decisions 3, 6 and 12:

* ``sine``: ``w = ½ − ½·cos 2πp``, so ``w`` is 0, ½, 1, ½ at ``p`` = 0, ¼, ½, ¾;
  ``sawUp``: ``w = p``;
* ``multiply``: ``amount = 1 − size·d·(1 − w)``, applied as
  ``v·(1 + (amount − 1)·W)``; ``add``: ``amount = size·d·(2w − 1)``;
* absolute layers: the value ``lerp(low, high, w)`` at presence × ``d``.

The rig is two Appendix A spots unless a test says otherwise. Hz effects
run at 1 Hz, so their position ``P`` is the time since they entered.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from builders import (
    busk_rig,
    compile_doc,
    entry,
    lanes_of,
    literal,
    look,
    rgb,
    speed_master,
    targets,
)
from busk.compiler.compile import CompiledShow
from harness import (
    Harness,
    Observation,
    Script,
    fader,
    flash,
    master,
    release,
    tap,
    toggle,
    trigger,
)

type Doc = dict[str, Any]

SPOTS = targets("fx-mh1", "fx-mh2")
ABS = pytest.approx


def layer(attribute: str, kind: str, mode: str = "absolute") -> Doc:
    return {"attribute": attribute, "waveform": {"kind": kind}, "phaseOffset": 0, "mode": mode}


def template(template_id: str, *layers: Doc) -> Doc:
    return {"id": template_id, "name": template_id, "layers": list(layers)}


TEMPLATES = [
    template("t-sine", layer("intensity", "sine")),
    template("t-saw", layer("intensity", "sawUp")),
    template("t-pan", layer("pan", "sine", "add")),
    template(
        "t-cycle",
        {
            "attribute": "color",
            "palette": [rgb(1, 0, 0), rgb(0, 1, 0), rgb(0, 0, 1)],
            "blend": "snap",
            "mode": "absolute",
        },
    ),
]


def instance(instance_id: str, template_id: str, spec: Doc = SPOTS, **fields: Any) -> Doc:
    """An instance at 1 Hz, forward, full size, every member in phase."""
    doc: Doc = {
        "id": instance_id,
        "templateId": template_id,
        "targets": spec,
        "rate": {"kind": "hz", "value": 1.0},
        "direction": "forward",
        "size": 1.0,
        "phase": {"start": 0, "end": 0},
        "groups": 1,
        "blocks": 1,
        "wings": 1,
    }
    doc.update(fields)
    return doc


def bpm(multiplier: float = 1.0) -> Doc:
    return {"kind": "bpm", "masterId": "m-speed", "multiplier": multiplier}


def rig() -> Doc:
    """Two spots, the templates, a 120 BPM speed master and a size master."""
    doc = busk_rig(2)
    doc["effects"] = TEMPLATES
    doc["masters"] = [speed_master(), {"id": "m-size", "kind": "size", "name": "FX"}]
    return doc


def effect_look(
    doc: Doc, playback_id: str, number: int, *entries: Doc, effects: list[Doc], **options: Any
) -> Doc:
    """A single-cue playback (:func:`look`) whose cue also holds ``effects``."""
    look(doc, playback_id, number, *entries, **options)
    doc["cueLists"][-1]["cues"][0]["effects"] = effects
    return doc


def run(
    doc_or_compiled: Doc | CompiledShow, script: Script, ticks: list[float]
) -> tuple[CompiledShow, dict[float, Observation]]:
    """Run ``script`` from a first tick at 0 (when the speed master starts
    counting), ticking at ``ticks`` too."""
    compiled = (
        doc_or_compiled
        if isinstance(doc_or_compiled, CompiledShow)
        else compile_doc(doc_or_compiled)
    )
    return compiled, Harness(compiled).run(script, [0.0, *ticks])


def values(
    compiled: CompiledShow, seen: dict[float, Observation], attribute: str, *fixtures: str
) -> dict[float, list[float]]:
    """``attribute``'s first lane on each of ``fixtures`` (default: both
    spots), at every observed time."""
    names = fixtures or ("fx-mh1", "fx-mh2")
    return {
        t: [lanes_of(compiled, obs.logical, name, attribute)[0] for name in names]
        for t, obs in seen.items()
    }


# ------------------------------------------------------------- Appendix A


def test_appendix_a_pulse_multiplies_the_heads(appendix_a: Doc) -> None:
    """Appendix A's pulse: ``multiply`` sine, size 0.7, ×½ on 120 BPM (one
    cycle a second), MH 2 half a cycle behind MH 1, entering over its
    1 s ``sizeFadeIn``, under the Verse's 0.4 on the heads. It starts at
    beat 5 (t = 2.5), on the grid, so ``P = t − 2.5``; the ``size`` fader is
    its dynamics ``d``."""
    script = [
        (0.0, fader("pb-song", 1.0)),  # autoStart: the Verse, 0.4, in by t = 2
        (2.5, toggle("pb-pulse")),
        (2.5, fader("pb-pulse", 1.0)),
        (4.0, fader("pb-pulse", 0.5)),
    ]
    compiled, seen = run(appendix_a, script, [3.0, 3.5, 3.75, 4.25])
    got = values(compiled, seen, "intensity")
    assert got[2.5] == ABS([0.4, 0.4])  # presence 0: nothing yet
    # Half present: MH 1 at p = ½ (w = 1, amount 1); MH 2 at p = 0 (amount
    # 0.3), half applied: 0.4·(1 − 0.7·½) = 0.26.
    assert got[3.0] == ABS([0.4, 0.26])
    assert got[3.5] == ABS([0.4 * 0.3, 0.4])  # fully present: MH 1 at its trough
    assert got[3.75] == ABS([0.26, 0.26])  # w = ½ on both: amount 0.65
    # d = ½: amount 1 − 0.35·(1 − w).
    assert got[4.0] == ABS([0.4, 0.4 * 0.65])
    assert got[4.25] == ABS([0.4 * 0.825, 0.4 * 0.825])


# ------------------------------------------------------- absolute layers


def test_an_absolute_wave_merges_htp_over_a_static_look() -> None:
    """Decision 7: an absolute intensity wave over a static 0.8 shows only
    above 0.8; a ``master`` fader scales both (decision 12)."""
    doc = effect_look(
        rig(),
        "pb",
        1,
        entry(SPOTS, "intensity", literal(0.8)),
        effects=[instance("e", "t-sine")],
    )
    script = [(0.0, fader("pb", 1.0)), (2.0, fader("pb", 0.5))]
    compiled, seen = run(doc, script, [0.25, 1 / 3, 5 / 12, 0.5, 0.75, 2.25, 2.5])
    got = values(compiled, seen, "intensity", "fx-mh1")
    assert got[0.0] == ABS([0.8])  # w = 0
    assert got[0.25] == ABS([0.8])  # w = ½
    assert got[1 / 3] == ABS([0.8])  # w = ¾
    assert got[5 / 12] == ABS([0.5 + 0.25 * math.sqrt(3)])  # w ≈ 0.933
    assert got[0.5] == ABS([1.0])
    assert got[0.75] == ABS([0.8])
    assert got[2.25] == ABS([0.4])  # at half: the look 0.4, the wave ½·½
    assert got[2.5] == ABS([0.5])  # the wave's crest ½ beats the look


def test_a_colour_cycle_wins_the_tie_with_its_cues_colour() -> None:
    """Decision 7: the effect and the amber share the playback's band and
    number, and the effect comes after the values: it shows, snapping
    through red, green and blue (``x = 3p``)."""
    doc = effect_look(
        rig(),
        "pb",
        1,
        entry(SPOTS, "color", literal(rgb(1, 0.5, 0))),
        effects=[instance("e", "t-cycle")],
    )
    compiled, seen = run(doc, [(0.0, fader("pb", 1.0))], [0.4, 0.7, 1.2])
    rgb_of = {t: lanes_of(compiled, obs.logical, "fx-mh1", "color")[:3] for t, obs in seen.items()}
    assert rgb_of[0.0] == [1.0, 0.0, 0.0]
    assert rgb_of[0.4] == [0.0, 1.0, 0.0]
    assert rgb_of[0.7] == [0.0, 0.0, 1.0]
    assert rgb_of[1.2] == [1.0, 0.0, 0.0]


# ---------------------------------------------------- release, re-activate


def test_a_release_fades_a_moving_effect_and_reactivation_folds_it_in() -> None:
    """Decision 11: the effect keeps moving while the release fades the
    playback's envelope; going idle stops it. Re-activating a releasing
    playback folds the release level into the presence, which fades back
    with the cue's in timing (1 s, as the effect entered), so nothing
    jumps."""
    doc = effect_look(rig(), "pb", 1, effects=[instance("e", "t-saw")], fade_in=1.0)
    script: Script = [(0.0, fader("pb", 1.0)), (2.0, release("pb", 1.0))]
    later = [(4.25, trigger("pb"))]
    compiled, seen = run(doc, [*script, *later], [2.25, 2.5, 2.75, 3.0, 3.25, 4.75])
    got = values(compiled, seen, "intensity", "fx-mh1")
    assert got[2.0] == ABS([0.0])  # w = 0 at the release
    assert got[2.25] == ABS([0.25 * 0.75])  # still moving, at env ¾
    assert got[2.5] == ABS([0.5 * 0.5])
    assert got[2.75] == ABS([0.75 * 0.25])
    assert got[3.0] == got[3.25] == ABS([0.0])  # idle: the bank is cleared
    assert got[4.25] == ABS([0.0])  # a fresh start: a new clock, entering again
    assert got[4.75] == ABS([0.5 * 0.5])  # P = ½ at presence ½

    script = [*script, (2.5, trigger("pb"))]
    compiled, seen = run(doc, script, [2.25, 3.0, 3.25, 3.5])
    got = values(compiled, seen, "intensity", "fx-mh1")
    assert got[2.5] == ABS([0.25])  # env ½ × presence 1 → env 1 × presence ½
    assert got[3.0] == ABS([0.0])  # w = 0 (P = 3)
    assert got[3.25] == ABS([0.25 * 0.875])  # presence ½ → 1 over 1 s
    assert got[3.5] == ABS([0.5])  # back to full


# ---------------------------------------------------------------- faders


def test_a_size_fader_starts_releases_and_scales_the_dynamics() -> None:
    """Decision 14: the ``size`` fader starts the playback at 0 → x and
    releases it at x → 0, and sets ``d`` for an ``add`` pan wave of ±20°;
    the cue's own intensity stays at full."""
    doc = effect_look(
        rig(),
        "pb",
        1,
        entry(SPOTS, "intensity", literal(0.6)),
        entry(SPOTS, "pan", literal(0.0)),
        effects=[instance("e", "t-pan", size=20.0)],
        fader="size",
        release_time=0.5,
    )
    script = [(0.0, fader("pb", 0.5)), (1.0, fader("pb", 1.0)), (2.0, fader("pb", 0.0))]
    compiled, seen = run(doc, script, [0.25, 0.5, 1.5, 2.25, 2.5])
    pan = values(compiled, seen, "pan", "fx-mh1")
    intensity = values(compiled, seen, "intensity", "fx-mh1")
    assert seen[0.0].snapshot is not None
    assert seen[0.0].snapshot.playbacks[0].state == "active"
    assert (pan[0.0], pan[0.25], pan[0.5]) == (ABS([-10.0]), ABS([0.0]), ABS([10.0]))
    assert intensity[0.5] == ABS([0.6])  # not scaled by the size fader
    assert (pan[1.0], pan[1.5]) == (ABS([-20.0]), ABS([20.0]))
    assert pan[2.25] == ABS([0.0])  # d = 0
    snapshot = seen[2.0].snapshot
    assert snapshot is not None
    assert snapshot.playbacks[0].state == "releasing"
    assert intensity[2.25] == ABS([0.3])
    assert intensity[2.5] == ABS([0.0])


def test_a_rate_fader_rerates_hz_and_bpm_effects() -> None:
    """Decision 14: a ``rate`` fader at 0.75 runs an Hz effect at
    4^0.5 = ×2, and a BPM one at ×2 (rounded to a power of two). The
    positions are continuous: the Hz clock rebases, the BPM clock aligns
    on the grid (here without a nudge: P = 1 at beat 1)."""
    doc = effect_look(
        rig(),
        "pb",
        1,
        effects=[
            instance("hz", "t-saw", targets("fx-mh1")),
            instance("beat", "t-saw", targets("fx-mh2"), rate=bpm()),
        ],
        fader="rate",
        buttons=["toggle"],
    )
    script = [(0.0, toggle("pb")), (0.5, fader("pb", 0.75))]
    compiled, seen = run(doc, script, [0.25, 0.625, 0.75])
    got = values(compiled, seen, "intensity")
    assert got[0.25] == ABS([0.25, 0.5])  # ×1: 1 Hz, and 1 cycle a beat at 2 beats/s
    assert got[0.625] == ABS([0.75, 0.5])  # P = 0.5 + 2·0.125; P = 1 + 2·0.25
    assert got[0.75] == ABS([0.0, 0.0])  # P = 1.0 and 2.0


# --------------------------------------------------------------- masters


def test_a_size_master_scales_the_presence_of_an_absolute_layer() -> None:
    """Decision 15: ``SET_MASTER`` on a size master sets ``d`` for the
    effects that name it; for an absolute layer ``d`` scales its presence."""
    doc = effect_look(
        rig(),
        "pb",
        1,
        effects=[
            instance("e", "t-sine", targets("fx-mh1"), sizeMasterId="m-size"),
            instance("f", "t-sine", targets("fx-mh2")),
        ],
    )
    script = [(0.0, fader("pb", 1.0)), (1.0, master("m-size", 0.5))]
    compiled, seen = run(doc, script, [0.5, 1.5])
    got = values(compiled, seen, "intensity")
    assert got[0.5] == ABS([1.0, 1.0])
    assert got[1.5] == ABS([0.5, 1.0])  # only the instance that names it


def test_a_speed_master_step_rerates_bpm_and_hz_effects() -> None:
    """Decision 15 and §5.4: the master's ×2 step moves a BPM effect to
    2 cycles a beat, aligned on the grid nearest where it is and nudged
    there over a beat, and an Hz effect naming it in ``speedMasterId`` to
    2 Hz, rebased."""
    doc = effect_look(
        rig(),
        "pb",
        1,
        effects=[
            instance("beat", "t-saw", targets("fx-mh1"), rate=bpm()),
            instance("hz", "t-saw", targets("fx-mh2"), speedMasterId="m-speed"),
        ],
    )
    script = [(0.0, fader("pb", 1.0)), (1.1, master("m-speed", 0.75))]
    compiled, seen = run(doc, script, [1.2, 1.6])
    got = values(compiled, seen, "intensity")
    # Beats 2.2 at the step: P = 2.2 → the grid's 2.4, error −0.2 closing by
    # beat 3.2. At beat 2.4: 2.4 + 2·0.2 − 0.2·0.8 = 2.64.
    assert got[1.1] == ABS([0.2, 0.1])  # continuous
    assert got[1.2] == ABS([0.64, 0.3])
    assert got[1.6] == ABS([0.4, 0.1])  # on the grid (P = 2·beats − 2); Hz: 1.1 + 2·0.5


# ------------------------------------------------------------------ taps


TAPS = [10.0, 10.46875, 10.9375, 11.40625]
"""§5.4's worked example: taps in time at 128 BPM."""


def test_taps_lock_a_bpm_effect_without_a_jump() -> None:
    """§5.4: a ``sawUp`` at ×1 started at t = 3 (beat 6) on 120 BPM runs at
    ``P = beats − 6``. Tap 2 moves the master to 128 BPM and beat 21;
    ``P`` stays continuous (14.9375) and closes the −0.0625 gap by beat 22,
    where it is on the new grid."""
    doc = effect_look(rig(), "pb", 1, effects=[instance("e", "t-saw", rate=bpm())])
    script: Script = [(3.0, fader("pb", 1.0)), *((t, tap("m-speed")) for t in TAPS)]
    checks = [10.703125, 11.171875, 11.5]
    compiled = compile_doc(doc)
    _, seen = run(compiled, script, checks)
    _, plain = run(compiled, script[:1], [*TAPS, *checks])
    got = values(compiled, seen, "intensity", "fx-mh1")
    untapped = values(compiled, plain, "intensity", "fx-mh1")
    assert got[10.46875] == untapped[10.46875] == ABS([0.9375])  # nothing moves at a tap
    assert got[10.703125] == ABS([0.46875])  # mid-nudge: 15 + ½ − 0.0625·½
    assert got[11.171875] == ABS([0.5])  # on the grid: beat 22.5, P = 16.5
    assert got[11.5] == ABS([0.2])  # beat 23.2 after tap 4
    assert untapped[11.5] == ABS([0.0])  # 120 BPM: beat 23, P = 17


# ---------------------------------------------------- flash and temp (step 10)


def test_a_held_flash_runs_an_idle_playbacks_effects_in_its_band() -> None:
    """Decision 16: the flash bank plays the idle playback's effects in the
    flash band (50 + 30): its ``add`` pan wave is not suspended by ``low``'s
    static pan at band 60, as it would be in pb's own band. Releasing the
    flash stops them at once."""
    doc = effect_look(rig(), "low", 1, entry(SPOTS, "pan", literal(10.0)), effects=[], priority=60)
    effects = [
        instance("e", "t-pan", targets("fx-mh1"), size=20.0),
        instance("s", "t-saw", targets("fx-mh2")),
    ]
    effect_look(doc, "pb", 2, effects=effects, boost=30, include_ltp=True)
    compiled = compile_doc(doc)
    harness = Harness(compiled)
    harness.submit(fader("low", 1.0), flash("pb", True))
    seen = {0.0: harness.tick(0.0), 0.25: harness.tick(0.25), 0.5: harness.tick(0.5)}
    pb = harness.engine.runtime.playbacks.runtimes["pb"]
    assert pb.state == "idle"
    assert not pb.bank.active
    assert [(rt.source.priority, rt.seq) for rt in pb.flashBank.runtimes.values()] == [
        (80, pb.flashSeq),
        (80, pb.flashSeq),
    ]
    harness.submit(flash("pb", False))
    seen[0.75] = harness.tick(0.75)
    pan = values(compiled, seen, "pan", "fx-mh1")
    assert (pan[0.0], pan[0.25], pan[0.5], pan[0.75]) == (
        ABS([-10.0]),
        ABS([10.0]),
        ABS([30.0]),
        ABS([10.0]),
    )
    saw = values(compiled, seen, "intensity", "fx-mh2")
    assert (saw[0.25], saw[0.5], saw[0.75]) == (ABS([0.25]), ABS([0.5]), ABS([0.0]))
    assert not pb.flashBank.active


@pytest.mark.parametrize("include_ltp", [False, True])
def test_a_flash_brings_ltp_layers_only_with_include_ltp(include_ltp: bool) -> None:
    """Decision 16: without ``includeLtp`` the flash bank's absolute colour
    cycle and relative pan wave have no weight; its intensity wave plays."""
    effects = [
        instance("e", "t-pan", targets("fx-mh1"), size=20.0),
        instance("c", "t-cycle", targets("fx-mh2")),
        instance("s", "t-saw", targets("fx-mh2")),
    ]
    doc = effect_look(rig(), "pb", 1, effects=effects, include_ltp=include_ltp)
    compiled, seen = run(doc, [(0.0, flash("pb", True))], [0.4, 0.5])
    default = compiled.slots.defaultFrame
    rest_pan = lanes_of(compiled, default, "fx-mh1", "pan")[0]
    rest_rgb = lanes_of(compiled, default, "fx-mh2", "color")[:3]
    assert values(compiled, seen, "intensity", "fx-mh2")[0.5] == ABS([0.5])
    pan = values(compiled, seen, "pan", "fx-mh1")[0.5]
    rgb_of = lanes_of(compiled, seen[0.4].logical, "fx-mh2", "color")[:3]
    if include_ltp:
        assert (pan, rgb_of) == (ABS([rest_pan + 20.0]), [0.0, 1.0, 0.0])
    else:
        assert (pan, rgb_of) == (ABS([rest_pan]), ABS(rest_rgb))


def test_nothing_doubles_while_main_is_active() -> None:
    """Decision 16: a flash on an active playback adds its static values
    only; main's bank alone moves the pan (+20° at P = ½, not +40°)."""
    doc = effect_look(
        rig(),
        "pb",
        1,
        entry(SPOTS, "pan", literal(0.0)),
        effects=[instance("e", "t-pan", targets("fx-mh1"), size=20.0)],
        include_ltp=True,
    )
    compiled = compile_doc(doc)
    script: Script = [(0.0, fader("pb", 1.0))]
    _, flashed = run(compiled, [*script, (0.1, flash("pb", True))], [0.5])
    _, plain = run(compiled, script, [0.5])
    assert values(compiled, flashed, "pan", "fx-mh1")[0.5] == ABS([20.0])
    np.testing.assert_array_equal(flashed[0.5].logical, plain[0.5].logical)


def test_activating_main_during_a_held_flash_hands_over_on_the_beat_grid() -> None:
    """Decision 16: when main activates, the flash bank stops and main's
    bank starts a new clock on the speed master's grid, so a BPM ×1
    ``sawUp`` carries on at the same phase, ``frac(beats)``: the frames
    are those of the flash alone."""
    doc = effect_look(
        rig(), "pb", 1, effects=[instance("e", "t-saw", targets("fx-mh1"), rate=bpm())]
    )
    compiled = compile_doc(doc)
    checks = [0.3, 0.35, 0.6, 0.85]
    harness = Harness(compiled)
    script: Script = [(0.1, flash("pb", True))]
    handed = harness.run([*script, (0.3, fader("pb", 1.0))], [0.0, *checks])
    _, flashed = run(compiled, script, checks)
    pb = harness.engine.runtime.playbacks.runtimes["pb"]
    assert (pb.state, pb.bank.active, pb.flashBank.active) == ("active", True, False)
    got = values(compiled, handed, "intensity", "fx-mh1")
    for t in checks:  # 120 BPM: beats = 2t
        assert got[t] == ABS([2 * t % 1.0]), t
        assert got[t] == ABS(values(compiled, flashed, "intensity", "fx-mh1")[t]), t


def test_a_temp_fader_scales_the_flashed_effects() -> None:
    """Decision 16: a ``temp`` fader is a flash at the fader's level. Its
    effects take the flash's intensity scale and full dynamics: only a
    size master reduces them (here to ½ on fx-mh2)."""
    effects = [
        instance("e", "t-saw", targets("fx-mh1")),
        instance("m", "t-saw", targets("fx-mh2"), sizeMasterId="m-size"),
    ]
    doc = effect_look(rig(), "pb", 1, effects=effects, fader="temp")
    script: Script = [
        (0.0, fader("pb", 0.5)),
        (0.0, master("m-size", 0.5)),
        (1.0, fader("pb", 1.0)),
        (2.0, fader("pb", 0.0)),
    ]
    compiled, seen = run(doc, script, [0.5, 1.5, 2.5])
    got = values(compiled, seen, "intensity")
    assert got[0.5] == ABS([0.5 * 0.5, 0.5 * 0.5 * 0.5])
    assert got[1.5] == ABS([0.5, 0.5 * 0.5])
    assert got[2.5] == ABS([0.0, 0.0])


def test_the_flash_bank_follows_taps_and_speed_steps_like_main() -> None:
    """§5.7: taps and the speed master's step re-time the flash bank's
    clocks as they do main's, so a held flash and an active main started
    at the same time show the same BPM wave throughout."""
    doc = effect_look(
        rig(), "pb", 1, effects=[instance("e", "t-saw", targets("fx-mh1"), rate=bpm())]
    )
    compiled = compile_doc(doc)
    events: Script = [
        (1.0, master("m-speed", 0.75)),  # the ×2 step
        *((t, tap("m-speed")) for t in (2.0, 2.45, 2.9)),
    ]
    checks = [1.2, 1.7, 2.2, 2.6, 3.1, 3.4, 3.8]
    _, flashed = run(compiled, [(0.1, flash("pb", True)), *events], checks)
    _, active = run(compiled, [(0.1, fader("pb", 1.0)), *events], checks)
    by_flash = values(compiled, flashed, "intensity", "fx-mh1")
    by_main = values(compiled, active, "intensity", "fx-mh1")
    for t in checks:
        assert by_flash[t] == ABS(by_main[t]), t
    assert len({round(by_flash[t][0], 6) for t in checks}) > 1  # it moves


def test_a_flash_held_through_the_end_of_a_release_takes_over_the_effects() -> None:
    """Beyond the plan: the flash bank runs whenever the flash is present
    and main is idle, so a flash held while a release ends takes over the
    effects from the release's end (1.5 s), on any tick schedule. While main
    is releasing its bank alone plays them (no doubling)."""
    doc = effect_look(
        rig(), "pb", 1, effects=[instance("e", "t-saw", targets("fx-mh1"))], release_time=0.5
    )
    compiled = compile_doc(doc)
    script: Script = [(0.0, fader("pb", 1.0)), (0.1, flash("pb", True)), (1.0, release("pb"))]
    _, sparse = run(compiled, script, [1.25, 1.75])
    _, dense = run(compiled, script, [1.25, 1.6, 1.75])
    got = values(compiled, sparse, "intensity", "fx-mh1")
    assert got[1.25] == ABS([0.25 * 0.5])  # main's bank at env ½
    assert got[1.75] == ABS([0.25])  # the flash bank's clock started at 1.5
    np.testing.assert_array_equal(sparse[1.75].logical, dense[1.75].logical)


# --------------------------------------------------- schedule independence


def test_frames_do_not_depend_on_the_tick_schedule(appendix_a: Doc) -> None:
    """Decision 1: effects are pure functions of time between events, so
    100 Hz ticks and an irregular schedule give byte-identical frames at
    the times both tick."""
    appendix_a["effects"] += TEMPLATES
    effect = instance("e", "t-pan", size=15.0, rate=bpm(2.0), phase={"start": 0, "end": 180})
    appendix_a["cueLists"][2]["cues"][0]["effects"].append(effect)
    script: Script = [
        (0.0, fader("pb-song", 1.0)),
        (0.3, toggle("pb-pulse")),
        (0.31, fader("pb-pulse", 0.8)),
        (1.05, master("m-speed", 0.75)),
        *((t, tap("m-speed")) for t in (1.5, 1.97, 2.43)),
        (2.6, fader("pb-pulse", 0.3)),
        (3.1, toggle("pb-pulse")),
    ]
    checks = [0.5, 1.0, 1.25, 1.75, 2.0, 2.5, 2.75, 3.3, 3.9, 4.5]
    compiled = compile_doc(appendix_a)
    _, steady = run(compiled, script, [k / 100 for k in range(1, 451)])
    irregular = sorted(np.random.default_rng(7).uniform(0.0, 4.5, 40).tolist())
    _, uneven = run(compiled, script, [*irregular, *checks])
    for t in checks:
        assert np.array_equal(steady[t].logical, uneven[t].logical, equal_nan=True), t
        assert steady[t].frame.universes == uneven[t].frame.universes, t
