"""Incremental recompile: reuse by identity equals a full compile (§6.4, phase-3-plan §5.11)."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from builders import APPENDIX_A, ROOT, load_doc
from busk.compiler.compile import CompiledShow, compile_show
from busk.compiler.cues import CompiledCue
from busk.compiler.playbacks import CompiledCueList
from busk.console.console import Console
from busk.engine.clock import FakeClock
from busk.engine.loop import Engine
from busk.persistence.show_file import new_show
from busk.session.ids import CounterIds
from busk.session.library import ProfileLibrary
from busk.session.session import Session
from session_harness import Live

NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)


def same_cue(a: CompiledCue, b: CompiledCue) -> None:
    assert (a.id, a.number, a.name, a.inTiming, a.outTiming, a.timings, a.targets) == (
        b.id,
        b.number,
        b.name,
        b.inTiming,
        b.outTiming,
        b.timings,
        b.targets,
    )
    assert len(a.effects) == len(b.effects)
    assert all(x.same(y) for x, y in zip(a.effects, b.effects, strict=True))
    assert (a.trigger, a.triggerDelay) == (b.trigger, b.triggerDelay)
    for name in (
        "htpIn",
        "htpOut",
        "ltpTiming",
        "snapTiming",
        "leave",
        "htpPos",
        "htpValues",
        "ltpLanes",
        "ltpValues",
        "snapLanes",
        "snapValues",
        "snapThresholds",
    ):
        np.testing.assert_array_equal(getattr(a, name), getattr(b, name))


def same_list(a: CompiledCueList, b: CompiledCueList) -> None:
    assert (a.id, a.mode, a.tracking, a.wrap, a.releaseAtEnd, dict(a.byId)) == (
        b.id,
        b.mode,
        b.tracking,
        b.wrap,
        b.releaseAtEnd,
        dict(b.byId),
    )
    assert len(a.cues) == len(b.cues)
    for x, y in zip(a.cues, b.cues, strict=True):
        same_cue(x, y)


def assert_same(incremental: CompiledShow, full: CompiledShow) -> None:
    """Everything the engine, output and input read is equal."""
    assert incremental.universes == full.universes
    assert list(incremental.slots.byKey) == list(full.slots.byKey)
    np.testing.assert_array_equal(incremental.slots.defaultFrame, full.slots.defaultFrame)
    np.testing.assert_array_equal(incremental.baseImages, full.baseImages)
    assert incremental.channels == full.channels
    assert list(incremental.cueLists) == list(full.cueLists)
    for ident, cue_list in full.cueLists.items():
        same_list(incremental.cueLists[ident], cue_list)
    assert list(incremental.playbacks) == list(full.playbacks)
    for ident, playback in full.playbacks.items():
        mine = incremental.playbacks[ident]
        same_list(mine.cueList, playback.cueList)
        assert {**vars(mine), "cueList": None} == {**vars(playback), "cueList": None}
    assert incremental.pages == full.pages
    assert incremental.masters == full.masters
    assert incremental.warnings == full.warnings
    assert incremental.engineHz == full.engineHz


def test_every_step_of_the_build_compiles_like_a_full_compile() -> None:
    ids = CounterIds()
    show = new_show("Club Night", ids=ids, now=NOW, cid="0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f")
    compiled = compile_show(show)
    session = Session(show, Engine(compiled, FakeClock()).bus, compiled=compiled, ids=ids)
    console = Console(session, ProfileLibrary())
    lines = (ROOT / "tests" / "fixtures" / "phase3-build.busk").read_text().splitlines()
    for line in [*lines, "undo", "undo", "undo", "redo"]:
        if line.strip() == "save":
            continue
        reply = console.execute(line)
        assert reply.ok, (line, reply.text)
        assert_same(session.compiled, compile_show(session.show))


def test_what_did_not_change_is_reused() -> None:
    live = Live(load_doc(APPENDIX_A))
    first = live.session.compiled
    live.do({"type": "SET", "path": ["playbacks", {"id": "pb-blue"}, "name"], "value": "Navy"})
    second = live.session.compiled
    assert second.slots is first.slots
    assert second.plan is first.plan
    assert second.cueLists["cl-song"] is first.cueLists["cl-song"]  # so are untouched lists
    # Re-recording Blue recompiles exactly the lists that read it.
    live.do(
        {"type": "SELECT", "targets": {"kind": "group", "groupId": "g-mh"}, "mode": "replace"},
        {
            "type": "SET_ATTRIBUTE",
            "attribute": "color",
            "value": {"kind": "literal", "value": {"r": 0, "g": 0, "b": 0.5}},
        },
        {
            "type": "RECORD_PRESET",
            "pool": "color",
            "number": 1,
            "scope": "global",
            "merge": "merge",
        },
    )
    third = live.session.compiled
    assert third.cueLists["cl-song"] is second.cueLists["cl-song"]
    assert third.cueLists["cl-blue"] is not second.cueLists["cl-blue"]
    # A patch change rebuilds the rig.
    live.do({"type": "PATCH_FIXTURE", "fixtureId": "fx-par1", "patch": None})
    assert live.session.compiled.slots is not third.slots
    assert_same(live.session.compiled, compile_show(live.session.show))


def test_moving_a_cue_list_recompiles_it_for_its_new_warning_paths() -> None:
    doc = load_doc(APPENDIX_A)
    doc["cueLists"][1]["cues"][0]["entries"].append(
        {
            "targets": {"kind": "group", "groupId": "g-mh"},
            "attribute": "gobo1",
            "value": {"kind": "literal", "value": {"slot": "dots"}},
        }
    )
    live = Live(doc)
    paths = [warning.path for warning in live.session.compiled.warnings]
    assert paths == ["cueLists[1].cues[0].entries[2].value"] * 2  # one per head
    # Deleting the first cue list moves Blue to index 0, unchanged.
    live.do(
        {
            "type": "BATCH",
            "label": "drop the song",
            "commands": [
                {"type": "ASSIGN_PLAYBACK", "pageId": "page-1", "slot": 0, "playbackId": None},
                {"type": "DELETE", "path": ["playbacks", {"id": "pb-song"}]},
                {"type": "DELETE", "path": ["cueLists", {"id": "cl-song"}]},
            ],
        }
    )
    paths = [warning.path for warning in live.session.compiled.warnings]
    assert paths == ["cueLists[0].cues[0].entries[2].value"] * 2
    assert_same(live.session.compiled, compile_show(live.session.show))


def test_a_tracking_list_recompiles_when_a_group_its_releases_read_changes() -> None:
    """Releases read groups too: editing a group only a release names must
    recompile the tracking list that uses it."""
    doc = load_doc(APPENDIX_A)
    doc["groups"].append(
        {
            "id": "g-one",
            "number": 9,
            "name": "One",
            "members": [{"fixtureId": "fx-mh1", "element": 0}],
        }
    )
    doc["cueLists"][0]["cues"][1]["releases"] = [
        {"targets": {"kind": "group", "groupId": "g-one"}, "attributes": ["pan"]}
    ]
    live = Live(doc)
    before = live.session.compiled
    live.do(
        {
            "type": "SET",
            "path": ["groups", {"id": "g-one"}, "members"],
            "value": [{"fixtureId": "fx-mh2", "element": 0}],
        }
    )
    after = live.session.compiled
    assert after.cueLists["cl-song"] is not before.cueLists["cl-song"]
    assert after.cueLists["cl-blue"] is before.cueLists["cl-blue"]
    assert_same(after, compile_show(live.session.show))


def test_an_edited_template_or_palette_preset_recompiles_exactly_the_lists_that_read_it() -> None:
    """Effects read templates, groups and palette presets: editing one of
    them recompiles the lists whose effects read it, and only those."""
    doc = load_doc(APPENDIX_A)
    doc["presets"].append(
        {
            "id": "pr-green",
            "number": 9,
            "name": "Green",
            "pool": "color",
            "values": [
                {
                    "scope": {"kind": "global"},
                    "attribute": "color",
                    "value": {"r": 0, "g": 1, "b": 0},
                }
            ],
        }
    )
    doc["effects"].append(
        {
            "id": "ef-cycle",
            "name": "Cycle",
            "layers": [
                {
                    "attribute": "color",
                    "palette": [{"presetId": "pr-green"}, {"r": 0, "g": 0, "b": 1}],
                    "blend": "fade",
                    "mode": "absolute",
                }
            ],
        }
    )
    pulse = doc["cueLists"][2]["cues"][0]["effects"][0]
    doc["cueLists"][0]["cues"][1]["effects"].append(
        {
            **pulse,
            "id": "ei-cycle",
            "templateId": "ef-cycle",
            "targets": {"kind": "group", "groupId": "g-par"},
        }
    )
    live = Live(doc)
    before = live.session.compiled
    assert [len(c.effects) for c in before.cueLists["cl-song"].cues] == [0, 1]
    # A template edit: only the Slow Pulse list reads ef-pulse.
    live.do(
        {
            "type": "SET",
            "path": ["effects", {"id": "ef-pulse"}, "layers"],
            "value": [
                {
                    "attribute": "intensity",
                    "waveform": {"kind": "triangle"},
                    "phaseOffset": 0,
                    "mode": "multiply",
                }
            ],
        }
    )
    edited = live.session.compiled
    assert edited.cueLists["cl-pulse"] is not before.cueLists["cl-pulse"]
    assert edited.cueLists["cl-song"] is before.cueLists["cl-song"]
    assert edited.cueLists["cl-blue"] is before.cueLists["cl-blue"]
    (layer,) = edited.cueLists["cl-pulse"].cues[0].effects[0].layers
    assert layer.wave is not None
    assert layer.wave.kind == "triangle"
    assert_same(edited, compile_show(live.session.show))
    # A palette preset edit: only the Song's Chorus cycle reads pr-green.
    live.do(
        {
            "type": "SET",
            "path": ["presets", {"id": "pr-green"}, "values"],
            "value": [
                {
                    "scope": {"kind": "global"},
                    "attribute": "color",
                    "value": {"r": 0, "g": 0.5, "b": 0},
                }
            ],
        }
    )
    recoloured = live.session.compiled
    assert recoloured.cueLists["cl-song"] is not edited.cueLists["cl-song"]
    assert recoloured.cueLists["cl-pulse"] is edited.cueLists["cl-pulse"]
    assert recoloured.cueLists["cl-blue"] is edited.cueLists["cl-blue"]
    (cycle,) = recoloured.cueLists["cl-song"].cues[1].effects
    assert cycle.layers[0].palette is not None
    assert cycle.layers[0].palette[0].tolist() == [[0.0, 0.5, 0.0], [0.0, 0.0, 1.0]]
    assert_same(recoloured, compile_show(live.session.show))
