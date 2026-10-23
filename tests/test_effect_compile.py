"""Compiled effects: instances into lanes, phases, waves and palettes (phase-5-plan §5.2)."""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pytest

from builders import (
    APPENDIX_A,
    busk_rig,
    compile_doc,
    cue,
    cue_list,
    group,
    in_group,
    load_doc,
    preset,
    preset_value,
    rgb,
    slot_of,
    speed_master,
    targets,
)
from busk.compiler.compile import CompiledShow
from busk.compiler.effects import CompiledEffect
from busk.engine.install import lane_maps

type Doc = dict[str, Any]

SINE: Doc = {"kind": "sine"}
CELL = "cueLists[0].cues[0]"


def scalar(attribute: str, mode: str = "absolute", offset: float = 0.0) -> Doc:
    return {"attribute": attribute, "waveform": SINE, "phaseOffset": offset, "mode": mode}


def palette(*colours: Doc, blend: str = "fade") -> Doc:
    return {"attribute": "color", "palette": list(colours), "blend": blend, "mode": "absolute"}


def template(template_id: str, *layers: Doc) -> Doc:
    return {"id": template_id, "name": template_id, "layers": list(layers)}


CIRCLE = template("t-circle", scalar("pan", "add"), scalar("tilt", "add", offset=90.0))
DIM = template("t-dim", scalar("intensity"))


def instance(instance_id: str, template_id: str, spec: Doc, **fields: Any) -> Doc:
    doc: Doc = {
        "id": instance_id,
        "templateId": template_id,
        "targets": spec,
        "rate": {"kind": "hz", "value": 1.0},
        "direction": "forward",
        "size": 1.0,
        "phase": {"start": 0, "end": 360},
        "groups": 1,
        "blocks": 1,
        "wings": 1,
    }
    doc.update(fields)
    return doc


def rig() -> Doc:
    """Two spots (RGBW colour) and two RGB pars, interleaved in group g-all."""
    doc = busk_rig(2, 2)
    doc["groups"] = [group("g-all", 1, "fx-mh1", "fx-par1", "fx-mh2", "fx-par2")]
    doc["masters"] = [
        speed_master(),
        speed_master("m-other"),
        {"id": "m-size", "kind": "size", "name": "FX"},
    ]
    return doc


def with_effects(
    *instances: Doc, templates: tuple[Doc, ...] = (CIRCLE, DIM), presets: tuple[Doc, ...] = ()
) -> Doc:
    doc = rig()
    doc["effects"] = list(templates)
    doc["presets"] = list(presets)
    only = cue("c1")
    only["effects"] = list(instances)
    doc["cueLists"] = [cue_list("cl", 1, only)]
    return doc


def effects_of(compiled: CompiledShow) -> tuple[CompiledEffect, ...]:
    return compiled.cueLists["cl"].cues[0].effects


def compile_effects(*instances: Doc, **options: Any) -> tuple[CompiledEffect, ...]:
    return effects_of(compile_doc(with_effects(*instances, **options)))


def lane(compiled: CompiledShow, fixture_id: str, attribute: str) -> int:
    return int(slot_of(compiled, fixture_id, attribute).laneOffset)


def frozen(array: np.ndarray) -> bool:
    return not array.flags.writeable


# --------------------------------------------------------------- Appendix A


def test_appendix_a_pulse_compiles_to_golden_arrays() -> None:
    compiled = compile_doc(load_doc(APPENDIX_A))
    found = [e for cl in compiled.cueLists.values() for c in cl.cues for e in c.effects]
    assert len(found) == 1
    (pulse,) = found
    assert (pulse.key, pulse.rate, pulse.hz, pulse.masterId, pulse.multiplier) == (
        "ei-1",
        "bpm",
        0.0,
        "m-speed",
        0.5,
    )
    assert (pulse.speedMasterId, pulse.sizeMasterId) == (None, None)
    assert (pulse.direction, pulse.size, pulse.sizeFadeIn) == ("forward", 0.7, 1.0)
    assert pulse.targets == (
        {"fixtureId": "fx-mh1", "element": 0},
        {"fixtureId": "fx-mh2", "element": 0},
    )
    (layer,) = pulse.layers
    assert (layer.attribute, layer.mode, layer.htp, layer.clamp) == (
        "intensity",
        "multiply",
        False,
        None,
    )
    assert layer.wave is not None
    assert layer.wave.kind == "sine"
    assert layer.palette is None
    assert layer.extras.size == 0
    # A multiply layer works on the frame: the heads' intensity lanes.
    assert layer.lanes.tolist() == [
        lane(compiled, "fx-mh1", "intensity"),
        lane(compiled, "fx-mh2", "intensity"),
    ]
    assert layer.lanes.dtype == np.intp
    assert layer.member.tolist() == [0, 1]
    np.testing.assert_array_equal(layer.phase, [0.0, 0.5])  # 0→360° over two heads
    assert frozen(layer.lanes)
    assert frozen(layer.member)
    assert frozen(layer.phase)


def test_appendix_a_cues_carry_their_out_timing() -> None:
    compiled = compile_doc(load_doc(APPENDIX_A))
    for cue_list_doc in load_doc(APPENDIX_A)["cueLists"]:
        for cue_doc, mine in zip(
            cue_list_doc["cues"], compiled.cueLists[cue_list_doc["id"]].cues, strict=True
        ):
            timing = cue_doc["timing"]
            assert (mine.outTiming.fade, mine.outTiming.delay, mine.outTiming.curve) == (
                timing["fadeOut"],
                timing["delayOut"],
                timing["curve"],
            )


# ------------------------------------------------------------------ members


def test_members_without_the_attribute_keep_their_position() -> None:
    """The circle over g-all (head, par, head, par): the pars have no pan or
    tilt, so the layers hold the heads only, at the heads' positions in the
    spread (0° and 180°), the tilt a quarter turn ahead."""
    doc = with_effects(instance("e", "t-circle", in_group("g-all"), size=15.0))
    compiled = compile_doc(doc)
    (circle,) = effects_of(compiled)
    pan, tilt = circle.layers
    assert pan.lanes.tolist() == [lane(compiled, "fx-mh1", "pan"), lane(compiled, "fx-mh2", "pan")]
    assert tilt.lanes.tolist() == [
        lane(compiled, "fx-mh1", "tilt"),
        lane(compiled, "fx-mh2", "tilt"),
    ]
    assert pan.member.tolist() == tilt.member.tolist() == [0, 2]
    np.testing.assert_allclose(pan.phase, [0.0, 0.5])
    np.testing.assert_allclose(tilt.phase, [0.25, 0.75])
    assert (pan.mode, pan.htp, pan.clamp) == ("add", False, None)  # pan has no range
    assert len(circle.targets) == 4  # the targets stay whole


def test_absolute_intensity_goes_to_htp_positions_with_the_full_range() -> None:
    compiled = compile_doc(with_effects(instance("e", "t-dim", in_group("g-all"))))
    (dim,) = effects_of(compiled)
    (layer,) = dim.layers
    assert layer.htp
    # Positions in intensityLanes [mh1, mh2, par1, par2], in g-all's order.
    assert compiled.slots.intensityLanes[layer.lanes].tolist() == [
        lane(compiled, f, "intensity") for f in ("fx-mh1", "fx-par1", "fx-mh2", "fx-par2")
    ]
    assert layer.lanes.tolist() == [0, 2, 1, 3]
    assert (layer.low, layer.high, layer.clamp) == (0.0, 1.0, None)


@pytest.mark.parametrize(
    ("bounds", "expected"),
    [
        ({"low": 0.2, "high": 0.8}, (0.2, 0.8)),
        ({"low": -0.5, "high": 2.0}, (0.0, 1.0)),  # clamped to the registry range
        ({"low": 0.8, "high": 0.2}, (0.8, 0.2)),  # an inverted sweep is kept
        ({"high": 0.5}, (0.0, 0.5)),
    ],
)
def test_low_and_high_default_to_the_range_and_are_clamped_to_it(
    bounds: Doc, expected: tuple[float, float]
) -> None:
    (dim,) = compile_effects(instance("e", "t-dim", targets("fx-mh1"), **bounds))
    assert (dim.layers[0].low, dim.layers[0].high) == expected


def test_an_unranged_attribute_sweeps_its_own_bounds() -> None:
    sweep = template("t-sweep", scalar("pan"))
    (effect,) = compile_effects(
        instance("e", "t-sweep", targets("fx-mh1"), low=-30.0, high=270.0), templates=(sweep,)
    )
    (layer,) = effect.layers
    assert (layer.htp, layer.low, layer.high) == (False, -30.0, 270.0)


def test_add_layers_on_ranged_attributes_are_clamped() -> None:
    layers = template(
        "t-mix", scalar("intensity", "add"), scalar("zoom", "add"), scalar("cto", "multiply")
    )
    compiled = compile_doc(
        with_effects(instance("e", "t-mix", targets("fx-mh1"), size=0.5), templates=(layers,))
    )
    intensity, zoom = effects_of(compiled)[0].layers  # the heads have no cto
    assert (intensity.htp, intensity.clamp) == (False, (0.0, 1.0))
    assert intensity.lanes.tolist() == [lane(compiled, "fx-mh1", "intensity")]
    assert zoom.clamp is None


# ----------------------------------------------------------------- palettes


def test_palettes_resolve_per_member_through_preset_scopes() -> None:
    """A preset's colour comes from the target scope, then the profile, then
    the global value (§5.8); literal colours are as written, without extras."""
    blue = preset(
        "p-blue",
        1,
        "color",
        preset_value("color", rgb(0, 0, 1)),
        preset_value("color", rgb(0, 1, 0), "fx-mh2:0"),
        preset_value("color", rgb(1, 1, 0), "profile:prof-par"),
    )
    cycle = template("t-cycle", palette(rgb(1, 0, 0, w=1), {"presetId": "p-blue"}, blend="snap"))
    compiled = compile_doc(
        with_effects(
            instance("e", "t-cycle", in_group("g-all")), templates=(cycle,), presets=(blue,)
        )
    )
    (effect,) = effects_of(compiled)
    (layer,) = effect.layers
    assert (layer.attribute, layer.mode, layer.htp, layer.blend) == (
        "color",
        "absolute",
        False,
        "snap",
    )
    assert layer.wave is None
    assert layer.palette is not None
    red = [1.0, 0.0, 0.0]
    assert layer.palette.tolist() == [
        [red, [0.0, 0.0, 1.0]],  # MH 1: global
        [red, [1.0, 1.0, 0.0]],  # Par 1: profile
        [red, [0.0, 1.0, 0.0]],  # MH 2: target
        [red, [1.0, 1.0, 0.0]],  # Par 2: profile
    ]
    first = [lane(compiled, f, "color") for f in ("fx-mh1", "fx-par1", "fx-mh2", "fx-par2")]
    assert layer.lanes.tolist() == [[f, f + 1, f + 2] for f in first]
    # The heads' white lanes, held at NaN (derive) while the cycle runs.
    assert layer.extras.tolist() == [first[0] + 3, first[2] + 3]
    np.testing.assert_allclose(layer.phase, [0.0, 0.25, 0.5, 0.75])
    assert frozen(layer.palette)
    assert frozen(layer.extras)
    memo = compiled.memo
    assert memo is not None
    read = memo.cueLists["cl"]
    assert (read.groups, read.presets, read.templates) == (
        frozenset({"g-all"}),
        frozenset({"p-blue"}),
        frozenset({"t-cycle"}),
    )


def test_a_member_without_a_palette_colour_is_left_out_with_a_warning() -> None:
    mine = preset("p-mine", 1, "color", preset_value("color", rgb(0, 0, 1), "fx-mh1:0"))
    cycle = template("t-cycle", palette(rgb(1, 0, 0), {"presetId": "p-mine"}))
    compiled = compile_doc(
        with_effects(
            instance("e", "t-cycle", targets("fx-mh1", "fx-mh2")),
            templates=(cycle,),
            presets=(mine,),
        )
    )
    (layer,) = effects_of(compiled)[0].layers
    assert layer.member.tolist() == [0]
    np.testing.assert_allclose(layer.phase, [0.0])  # MH 2 kept its place in the spread
    assert [(w.severity, w.path, w.message) for w in compiled.warnings] == [
        (
            "warning",
            f"{CELL}.effects[0]",
            "palette preset 'p-mine' has no colour for fx-mh2:0; it is left out of the effect",
        )
    ]


def test_an_effect_that_drives_nothing_compiles_to_none_with_a_warning() -> None:
    compiled = compile_doc(
        with_effects(
            instance("circle", "t-circle", targets("fx-par1", "fx-par2")),
            instance("dim", "t-dim", targets("fx-par1")),
        )
    )
    assert [effect.key for effect in effects_of(compiled)] == ["dim"]
    assert [(w.path, w.message) for w in compiled.warnings] == [
        (f"{CELL}.effects[0]", "no target has pan or tilt: the effect does nothing")
    ]


# -------------------------------------------------------------------- rates


def test_rates_and_masters() -> None:
    hz, bpm, plain = compile_effects(
        instance(
            "hz",
            "t-dim",
            targets("fx-mh1"),
            rate={"kind": "hz", "value": 2.5},
            speedMasterId="m-speed",
            sizeMasterId="m-size",
        ),
        instance(
            "bpm",
            "t-dim",
            targets("fx-mh1"),
            rate={"kind": "bpm", "masterId": "m-speed", "multiplier": 2},
            speedMasterId="m-other",  # ignored, with a validation warning
            direction="bounce",
        ),
        instance("plain", "t-dim", targets("fx-mh1")),
    )
    assert (hz.rate, hz.hz, hz.masterId, hz.multiplier, hz.speedMasterId) == (
        "hz",
        2.5,
        None,
        1.0,
        "m-speed",
    )
    assert hz.sizeMasterId == "m-size"
    assert (bpm.rate, bpm.hz, bpm.masterId, bpm.multiplier, bpm.speedMasterId) == (
        "bpm",
        0.0,
        "m-speed",
        2.0,
        None,
    )
    assert bpm.direction == "bounce"
    assert (plain.sizeFadeIn, plain.sizeMasterId, plain.speedMasterId) == (None, None, None)


# --------------------------------------------------- same, without, remapped


def test_same_compares_structure_and_identity_is_not_needed() -> None:
    doc = with_effects(instance("e", "t-circle", in_group("g-all"), size=15.0))
    (first,) = effects_of(compile_doc(doc))
    (again,) = effects_of(compile_doc(copy.deepcopy(doc)))
    assert again is not first
    assert first.same(again)
    assert again.same(first)
    assert first != again  # `==` is identity: use same()
    bigger = copy.deepcopy(doc)
    bigger["cueLists"][0]["cues"][0]["effects"][0]["size"] = 20.0
    assert not first.same(effects_of(compile_doc(bigger))[0])
    turned = copy.deepcopy(doc)
    turned["effects"][0]["layers"][1]["phaseOffset"] = -90.0
    assert not first.same(effects_of(compile_doc(turned))[0])
    squared = copy.deepcopy(doc)
    squared["effects"][0]["layers"][0]["waveform"] = {"kind": "square", "duty": 0.5}
    assert not first.same(effects_of(compile_doc(squared))[0])


def test_an_instance_knows_the_cue_that_defines_it_and_same_leaves_it_out() -> None:
    circle = instance("e", "t-circle", in_group("g-all"))
    doc = with_effects(circle)
    cues = doc["cueLists"][0]["cues"]
    cues.extend([cue("c2", number="2"), cue("c3", number="2.5")])
    cues[2]["effects"] = [{**circle, "size": 3.0}]
    doc["cueLists"][0]["tracking"] = True
    compiled = compile_doc(doc)
    first, tracked, redefined = (c.effects[0] for c in compiled.cueLists["cl"].cues)
    assert (first.cue, tracked.cue, redefined.cue) == ("1", "1", "2.5")
    assert tracked is first  # a tracked instance is the same object
    renumbered = copy.deepcopy(doc)
    renumbered["cueLists"][0]["cues"][0]["number"] = "0.5"
    (moved,) = effects_of(compile_doc(renumbered))
    assert moved.cue == "0.5"
    assert moved.same(first)  # the cue is not structure: nothing changes on stage


def test_palettes_are_compared_by_value() -> None:
    cycle = template("t-cycle", palette(rgb(1, 0, 0), rgb(0, 0, 1)))
    doc = with_effects(instance("e", "t-cycle", targets("fx-mh1")), templates=(cycle,))
    (first,) = effects_of(compile_doc(doc))
    assert first.same(effects_of(compile_doc(copy.deepcopy(doc)))[0])
    doc["effects"][0]["layers"][0]["palette"][1] = rgb(0, 1, 0)
    assert not first.same(effects_of(compile_doc(doc))[0])


def test_without_trims_released_slots() -> None:
    compiled = compile_doc(with_effects(instance("e", "t-circle", in_group("g-all"), size=15.0)))
    (circle,) = effects_of(compiled)
    table = compiled.slots
    pan1 = slot_of(compiled, "fx-mh1", "pan").index
    assert circle.without(frozenset(), table) is circle
    assert circle.without({slot_of(compiled, "fx-par1", "intensity").index}, table) is circle
    trimmed = circle.without({pan1}, table)
    assert trimmed is not None
    assert trimmed is not circle
    pan, tilt = trimmed.layers
    assert pan.member.tolist() == [2]
    assert pan.lanes.tolist() == [lane(compiled, "fx-mh2", "pan")]
    np.testing.assert_allclose(pan.phase, [0.5])  # MH 2 keeps its phase
    assert tilt is circle.layers[1]  # untouched layers are kept as they are
    assert trimmed.targets == circle.targets
    tilts = {slot_of(compiled, f, "tilt").index for f in ("fx-mh1", "fx-mh2")}
    only_pan = circle.without(tilts, table)
    assert only_pan is not None
    assert [layer.attribute for layer in only_pan.layers] == ["pan"]
    pans = {slot_of(compiled, f, "pan").index for f in ("fx-mh1", "fx-mh2")}
    assert circle.without(pans | tilts, table) is None


def test_without_trims_htp_positions_and_colour_extras() -> None:
    cycle = template("t-cycle", palette(rgb(1, 0, 0), rgb(0, 0, 1)))
    compiled = compile_doc(
        with_effects(
            instance("dim", "t-dim", in_group("g-all")),
            instance("cycle", "t-cycle", in_group("g-all")),
            templates=(DIM, cycle),
        )
    )
    dim, colours = effects_of(compiled)
    table = compiled.slots
    released = {slot_of(compiled, "fx-mh1", a).index for a in ("intensity", "color")}
    trimmed_dim = dim.without(released, table)
    assert trimmed_dim is not None
    assert trimmed_dim.layers[0].lanes.tolist() == [2, 1, 3]
    assert trimmed_dim.layers[0].member.tolist() == [1, 2, 3]
    trimmed = colours.without(released, table)
    assert trimmed is not None
    (layer,) = trimmed.layers
    assert layer.member.tolist() == [1, 2, 3]
    assert layer.extras.tolist() == [lane(compiled, "fx-mh2", "color") + 3]
    assert layer.palette is not None
    assert layer.palette.shape == (3, 2, 3)


def test_remapped_follows_a_patch_change() -> None:
    """Deleting MH 1 moves every other lane down: a running effect follows
    the slots that are left, and drops MH 1's rows."""
    cycle = template("t-cycle", palette(rgb(1, 0, 0), rgb(0, 0, 1)))
    old = compile_doc(
        with_effects(
            instance("circle", "t-circle", in_group("g-all"), size=15.0),
            instance("dim", "t-dim", in_group("g-all")),
            instance("cycle", "t-cycle", in_group("g-all")),
            templates=(CIRCLE, DIM, cycle),
        )
    )
    smaller = busk_rig(2, 2)
    smaller["fixtures"] = smaller["fixtures"][1:]
    new = compile_doc(smaller)
    by_key = np.array([new.slots.byKey.get(key, -1) for key in old.slots.byKey], dtype=np.int32)
    lane_map, pos_map = lane_maps(old.slots, new.slots, by_key)
    circle, dim, colours = effects_of(old)
    assert circle.remapped(np.arange(old.slots.laneCount), np.arange(4)) is circle
    moved = circle.remapped(lane_map, pos_map)
    assert moved is not None
    assert [layer.lanes.tolist() for layer in moved.layers] == [
        [lane(new, "fx-mh2", "pan")],
        [lane(new, "fx-mh2", "tilt")],
    ]
    assert moved.layers[0].member.tolist() == [2]
    moved_dim = dim.remapped(lane_map, pos_map)
    assert moved_dim is not None
    assert new.slots.intensityLanes[moved_dim.layers[0].lanes].tolist() == [
        lane(new, f, "intensity") for f in ("fx-par1", "fx-mh2", "fx-par2")
    ]
    moved_colours = colours.remapped(lane_map, pos_map)
    assert moved_colours is not None
    (layer,) = moved_colours.layers
    first = [lane(new, f, "color") for f in ("fx-par1", "fx-mh2", "fx-par2")]
    assert layer.lanes.tolist() == [[f, f + 1, f + 2] for f in first]
    assert layer.extras.tolist() == [lane(new, "fx-mh2", "color") + 3]
    gone = np.full(old.slots.laneCount, -1)
    assert circle.remapped(gone, np.full(4, -1)) is None
