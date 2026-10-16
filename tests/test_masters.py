"""Grand and group masters and blackout: correct, and non-destructive (§12, §20)."""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
import pytest

from builders import (
    busk_rig,
    compile_doc,
    entry,
    grand_master,
    group,
    in_group,
    lanes_of,
    literal,
    look,
    rgb,
    slot_of,
    targets,
)
from busk.compiler.compile import CompiledShow
from busk.engine.loop import Engine
from busk.engine.masters import apply_masters, grand_master_level, group_factor
from harness import Harness, blackout, fader, flash, master
from session_harness import Live

ALL = ("fx-mh1", "fx-mh2", "fx-par1", "fx-par2")


@pytest.fixture(scope="module")
def compiled() -> CompiledShow:
    """Two spots and two pars; a base look at 0.8 (band 50) and a panic flash
    (band 200, white at full)."""
    doc = busk_rig(spots=2, pars=2)
    doc["groups"].append(group("g-all", 1, *ALL))
    doc["masters"].append(grand_master())
    look(
        doc,
        "base",
        1,
        entry(in_group("g-all"), "intensity", literal(0.8)),
        entry(in_group("g-all"), "color", literal(rgb(1, 0.5, 0))),
        entry(in_group("g-all"), "pan", literal(30)),
    )
    look(
        doc,
        "panic",
        2,
        entry(in_group("g-all"), "intensity", literal(1.0)),
        entry(in_group("g-all"), "color", literal(rgb(1, 1, 1))),
        priority=200,
        fader="none",
        include_ltp=True,
    )
    return compile_doc(doc)


def test_grand_master_level_is_the_product() -> None:
    assert grand_master_level([]) == 1.0
    assert grand_master_level([0.5, 0.8]) == pytest.approx(0.4)


def test_apply_masters_touches_only_intensity_lanes(compiled: CompiledShow) -> None:
    generator = np.random.default_rng(7)
    frame = generator.uniform(0, 1, compiled.slots.laneCount)
    before = frame.copy()
    lanes = compiled.slots.intensityLanes
    apply_masters(frame, lanes, 0.25, blackout=False)
    others = np.setdiff1d(np.arange(frame.size), lanes)
    np.testing.assert_array_equal(frame[others], before[others])
    np.testing.assert_allclose(frame[lanes], before[lanes] * 0.25)
    apply_masters(frame, lanes, 1.0, blackout=True)
    assert not frame[lanes].any()
    np.testing.assert_array_equal(frame[others], before[others])


def test_the_grand_master_scales_intensity_only(compiled: CompiledShow) -> None:
    harness = Harness(compiled)
    harness.submit(fader("base", 1.0))
    full = harness.tick(0.0)
    harness.submit(master("m-gm", 0.5))
    half = harness.tick(0.01)
    for fixture in ALL:
        assert lanes_of(compiled, half.logical, fixture, "intensity") == [0.4]
        assert lanes_of(compiled, half.logical, fixture, "color") == pytest.approx(
            lanes_of(compiled, full.logical, fixture, "color"), nan_ok=True
        )
    lanes = compiled.slots.intensityLanes
    others = np.setdiff1d(np.arange(compiled.slots.laneCount), lanes)
    np.testing.assert_array_equal(half.logical[others], full.logical[others])


def test_blackout_zeroes_flashes_and_override_bands(compiled: CompiledShow) -> None:
    harness = Harness(compiled)
    harness.submit(fader("base", 1.0), flash("panic", True))
    lit = harness.tick(0.0)
    assert lanes_of(compiled, lit.logical, "fx-par1", "intensity") == [1.0]  # the panic band
    harness.submit(blackout(True))
    dark = harness.tick(0.01)
    for fixture in ALL:
        assert lanes_of(compiled, dark.logical, fixture, "intensity") == [0.0]
    # DMX: the spots' 16-bit dimmers at 0, every par emitter at 0 (virtual intensity).
    assert dark.channels(9, 10, 25, 26) == (0, 0, 0, 0)
    assert dark.channels(*range(33, 39)) == (0,) * 6
    # Non-intensity attributes keep the look: the panic white, MH 1 at pan 30°.
    assert lanes_of(compiled, dark.logical, "fx-mh1", "pan") == [30.0]


def fingerprint(engine: Engine) -> Any:
    """Every piece of playback runtime state, comparable with ``==``."""
    playbacks = engine.runtime.playbacks
    return (
        playbacks.seqCounter,
        tuple(playbacks.live),
        tuple(
            (
                ident,
                rt.state,
                rt.faderLevel,
                rt.activationSeq,
                dataclasses.astuple(rt.env),
                dataclasses.astuple(rt.ltpEnv),
                rt.ltpLatched,
                rt.flashButton,
                rt.flashSeq,
            )
            for ident, rt in playbacks.runtimes.items()
        ),
    )


def test_masters_and_blackout_never_change_runtime_state(compiled: CompiledShow) -> None:
    """§20: toggling the GM and blackout away and back gives an identical frame,
    and leaves the runtime state exactly as it was."""
    harness = Harness(compiled)
    harness.submit(fader("base", 0.7), flash("panic", True), master("m-gm", 0.9))
    live = harness.tick(1.0)
    state = fingerprint(harness.engine)
    for step, commands in enumerate(
        [
            [master("m-gm", 0.0)],
            [blackout(True)],
            [master("m-gm", 0.3)],
            [blackout(False), master("m-gm", 0.9)],
        ],
        start=1,
    ):
        harness.submit(*commands)
        observed = harness.tick(1.0 + step / 100)
        assert fingerprint(harness.engine) == state
    assert observed.universe == live.universe
    np.testing.assert_array_equal(observed.logical, live.logical)
    assert observed.snapshot is not None
    assert (observed.snapshot.grandMaster, observed.snapshot.blackout) == (0.9, False)


def test_grand_masters_start_at_their_initial_level_and_multiply() -> None:
    doc = busk_rig(spots=1)
    doc["masters"] += [grand_master("m-a", initial=0.5), grand_master("m-b", initial=0.5)]
    look(doc, "pb", 1, entry(targets("fx-mh1"), "intensity", literal(1.0)))
    harness = Harness(compile_doc(doc))
    harness.submit(fader("pb", 1.0))
    assert lanes_of(harness.compiled, harness.tick(0.0).logical, "fx-mh1", "intensity") == [0.25]


# ------------------------------------------------------------ group masters (Phase 5)


def group_master(master_id: str, group_id: str) -> dict[str, Any]:
    return {"id": master_id, "kind": "group", "name": master_id, "groupId": group_id}


def group_rig() -> dict[str, Any]:
    """The module's rig and looks, plus two overlapping groups with a group
    master each: m-heads (fx-mh2, fx-mh1: out of patch order) and m-left
    (fx-mh1, fx-par1)."""
    doc = busk_rig(spots=2, pars=2)
    doc["groups"] += [
        group("g-all", 1, *ALL),
        group("g-heads", 2, "fx-mh2", "fx-mh1"),
        group("g-left", 3, "fx-mh1", "fx-par1"),
    ]
    doc["masters"] += [
        grand_master(),
        group_master("m-heads", "g-heads"),
        group_master("m-left", "g-left"),
    ]
    look(
        doc,
        "base",
        1,
        entry(in_group("g-all"), "intensity", literal(0.8)),
        entry(in_group("g-all"), "color", literal(rgb(1, 0.5, 0))),
        entry(in_group("g-all"), "pan", literal(30)),
    )
    look(
        doc,
        "panic",
        2,
        entry(in_group("g-all"), "intensity", literal(1.0)),
        priority=200,
        fader="none",
    )
    return doc


@pytest.fixture(scope="module")
def grouped() -> CompiledShow:
    return compile_doc(group_rig())


def intensities(compiled: CompiledShow, logical: Any) -> list[float]:
    """Every fixture's intensity in :data:`ALL` order."""
    return [lanes_of(compiled, logical, fixture, "intensity")[0] for fixture in ALL]


def test_group_masters_compile_to_their_members_intensity_positions(
    grouped: CompiledShow,
) -> None:
    """``positions`` index ``intensityLanes``: ascending, whatever the
    members' order. Other kinds of master have none."""

    def lanes(*fixtures: str) -> list[int]:
        return sorted(slot_of(grouped, fixture, "intensity").laneOffset for fixture in fixtures)

    heads, left = grouped.masters["m-heads"], grouped.masters["m-left"]
    assert list(grouped.slots.intensityLanes[list(heads.positions)]) == lanes("fx-mh1", "fx-mh2")
    assert list(grouped.slots.intensityLanes[list(left.positions)]) == lanes("fx-mh1", "fx-par1")
    assert list(heads.positions) == sorted(heads.positions)
    assert grouped.masters["m-gm"].positions == ()


def test_the_group_factor_is_the_product_of_the_group_masters_containing_each_target(
    grouped: CompiledShow,
) -> None:
    masters = grouped.masters
    count = grouped.slots.intensityLanes.size
    assert group_factor(masters, {"m-heads": 1.0, "m-left": 1.0}, count) is None
    assert group_factor(masters, {}, count) is None
    factor = group_factor(masters, {"m-heads": 0.5, "m-left": 0.4}, count)
    assert factor is not None
    by_fixture = dict(zip(ALL, intensities(grouped, _spread(grouped, factor)), strict=True))
    assert by_fixture == {"fx-mh1": 0.2, "fx-mh2": 0.5, "fx-par1": 0.4, "fx-par2": 1.0}
    one = group_factor(masters, {"m-heads": 1.0, "m-left": 0.4}, count)
    assert one is not None
    assert intensities(grouped, _spread(grouped, one)) == [0.4, 1.0, 0.4, 1.0]


def _spread(compiled: CompiledShow, factor: Any) -> Any:
    """A logical frame holding ``factor`` on the intensity lanes, for reading by fixture."""
    frame = np.zeros(compiled.slots.laneCount)
    frame[compiled.slots.intensityLanes] = factor
    return frame


def test_group_masters_scale_their_members_intensity_only(grouped: CompiledShow) -> None:
    harness = Harness(grouped)
    harness.submit(fader("base", 1.0))
    full = harness.tick(0.0)
    assert intensities(grouped, full.logical) == [0.8] * 4
    harness.submit(master("m-heads", 0.5), master("m-left", 0.5))
    scaled = harness.tick(0.01)
    # fx-mh1 is in both groups: their levels multiply.
    assert intensities(grouped, scaled.logical) == [0.2, 0.4, 0.4, 0.8]
    lanes = grouped.slots.intensityLanes
    others = np.setdiff1d(np.arange(grouped.slots.laneCount), lanes)
    np.testing.assert_array_equal(scaled.logical[others], full.logical[others])
    # DMX: fx-par2's emitters are untouched; fx-par1's red is at 0.4 of full.
    assert scaled.channels(36, 37, 38) == full.channels(36, 37, 38)
    assert scaled.channels(33) == (round(0.4 * 255),)


def test_group_masters_come_before_the_grand_master_and_blackout(grouped: CompiledShow) -> None:
    """Spec §12: group masters, then the grand master, then blackout. The
    float product is order-sensitive, so the exact value shows the order."""
    harness = Harness(grouped)
    harness.submit(fader("base", 1.0), master("m-heads", 0.1), master("m-gm", 0.7))
    observed = harness.tick(0.0)
    assert lanes_of(grouped, observed.logical, "fx-mh2", "intensity") == [(0.8 * 0.1) * 0.7]
    assert (0.8 * 0.1) * 0.7 != 0.8 * (0.1 * 0.7)
    assert lanes_of(grouped, observed.logical, "fx-par2", "intensity") == [0.8 * 0.7]
    harness.submit(blackout(True))
    assert intensities(grouped, harness.tick(0.01).logical) == [0.0] * 4


def test_group_masters_scale_flashes_and_override_bands(grouped: CompiledShow) -> None:
    harness = Harness(grouped)
    harness.submit(flash("panic", True), master("m-left", 0.25))
    assert intensities(grouped, harness.tick(0.0).logical) == [0.25, 1.0, 0.25, 1.0]


def test_group_masters_are_non_destructive(grouped: CompiledShow) -> None:
    """Moving group masters away and back gives an identical frame and runtime
    state (§12: they act on the output frame only)."""
    harness = Harness(grouped)
    harness.submit(fader("base", 0.7), flash("panic", True), master("m-heads", 0.9))
    live = harness.tick(1.0)
    state = fingerprint(harness.engine)
    for step, commands in enumerate(
        [
            [master("m-heads", 0.0)],
            [master("m-left", 0.3), master("m-gm", 0.5)],
            [master("m-heads", 1.0)],
            [master("m-left", 1.0), master("m-gm", 1.0), master("m-heads", 0.9)],
        ],
        start=1,
    ):
        harness.submit(*commands)
        observed = harness.tick(1.0 + step / 100)
        assert fingerprint(harness.engine) == state
    assert observed.universe == live.universe
    np.testing.assert_array_equal(observed.logical, live.logical)


def test_group_masters_start_at_their_initial_level() -> None:
    doc = group_rig()
    next(m for m in doc["masters"] if m["id"] == "m-heads")["initialLevel"] = 0.5
    compiled = compile_doc(doc)
    harness = Harness(compiled)
    harness.submit(fader("base", 1.0))
    assert intensities(compiled, harness.tick(0.0).logical) == [0.4, 0.4, 0.8, 0.8]
    assert harness.engine.runtime.groupLevels == {"m-heads": 0.5, "m-left": 1.0}


def test_a_group_edit_takes_effect_at_once_and_levels_survive_live_edits() -> None:
    live = Live(group_rig())
    live.do(
        {"type": "SET_FADER", "playbackId": "base", "level": 1.0},
        {"type": "SET_MASTER", "masterId": "m-heads", "level": 0.5},
    )
    live.tick()
    assert [live.lanes(f, "intensity")[0] for f in ALL] == [0.4, 0.4, 0.8, 0.8]
    members = [{"fixtureId": f, "element": 0} for f in ("fx-mh1", "fx-par2")]
    live.do({"type": "SET", "path": ["groups", {"id": "g-heads"}, "members"], "value": members})
    live.tick()
    assert live.engine.runtime.groupLevels["m-heads"] == 0.5
    assert [live.lanes(f, "intensity")[0] for f in ALL] == [0.4, 0.8, 0.8, 0.4]
    live.do({"type": "DELETE", "path": ["masters", {"id": "m-heads"}]})
    live.tick()
    assert live.engine.runtime.groupLevels == {"m-left": 1.0}
    assert [live.lanes(f, "intensity")[0] for f in ALL] == [0.8] * 4
