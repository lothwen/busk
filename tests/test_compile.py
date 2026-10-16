"""Compiler: universe table, base images (§13.5) and the §13.1 byte split."""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from builders import APPENDIX_A, compile_doc, load_doc
from busk.compiler.compile import CompiledShow, UnsupportedFeature, compile_show
from busk.convert.dmx import split_raw
from busk.model.validate import has_errors, validate_show

type Doc = dict[str, Any]


def compiled(doc: Doc) -> CompiledShow:
    """Validate ``doc`` (it must be error-free) and compile it."""
    show, issues = validate_show(json.dumps(doc))
    assert show is not None
    assert not has_errors(issues), issues
    return compile_show(show)


def nonzero(image: np.ndarray[Any, Any]) -> dict[int, int]:
    """Non-zero channels of a universe image, 1-based."""
    return {int(index) + 1: int(image[index]) for index in np.flatnonzero(image)}


def test_appendix_a_base_image(appendix_a: Doc) -> None:
    # Pan/tilt default 32768 → coarse 128 / fine 0, zoom 128, everything else 0.
    # MH 1 at address 1, MH 2 at 17; the par (at 101) is all zeros.
    result = compiled(appendix_a)
    assert [u.id for u in result.universes] == ["u1"]
    assert result.baseImages.shape == (1, 512)
    assert result.baseImages.dtype == np.uint8
    assert nonzero(result.baseImages[0]) == {1: 128, 3: 128, 11: 128, 17: 128, 19: 128, 27: 128}
    assert result.engineHz == 100


def test_demo_base_image(demo_path: Path) -> None:
    # Only the MH-X25s' pan/tilt have non-zero defaultDmx (32768 → coarse 128). Their
    # shutters' defaultDmx is 0, "blackout": conversion overwrites it with "open".
    show, _ = validate_show(demo_path.read_bytes())
    assert show is not None
    assert nonzero(compile_show(show).baseImages[0]) == {1: 128, 2: 128, 13: 128, 14: 128}


# ------------------------------------------------------------- byte split


@pytest.mark.parametrize(
    ("raw", "nbytes", "expected"),
    [
        (0, 1, (0,)),
        (255, 1, (255,)),
        (32768, 2, (128, 0)),
        (65535, 2, (255, 255)),
        (0x1234, 2, (0x12, 0x34)),
        (0x123456, 3, (0x12, 0x34, 0x56)),
        (16777215, 3, (255, 255, 255)),
    ],
)
def test_split_raw(raw: int, nbytes: int, expected: tuple[int, ...]) -> None:
    assert split_raw(raw, nbytes) == expected


@pytest.mark.parametrize(("raw", "nbytes"), [(256, 1), (65536, 2), (-1, 1), (1 << 24, 3)])
def test_split_raw_rejects_values_that_do_not_fit(raw: int, nbytes: int) -> None:
    with pytest.raises(ValueError, match="does not fit"):
        split_raw(raw, nbytes)


def test_split_raw_recombines() -> None:
    for raw in range(0, 65536, 257):
        coarse, fine = split_raw(raw, 2)
        assert coarse << 8 | fine == raw


# ------------------------------------------------------ hand-built shows


def channel(offset: int, attribute: str, default: int, nbytes: int = 1, **extra: Any) -> Doc:
    top = 256**nbytes - 1
    return {
        "offset": offset,
        "element": 0,
        "attribute": attribute,
        "bytes": nbytes,
        "defaultDmx": default,
        "capabilities": [{"kind": "range", "dmx": [0, top], "value": [0, 1]}],
        **extra,
    }


def fixture(fid: str, number: int, patch: Doc | None, mode: str = "m") -> Doc:
    return {
        "id": fid,
        "number": number,
        "name": fid,
        "profileId": "p",
        "profileRevision": "1",
        "modeId": mode,
        "patch": patch,
        "orientation": {
            "invertPan": False,
            "invertTilt": False,
            "swapPanTilt": False,
            "panOffset": 0,
            "tiltOffset": 0,
        },
    }


def show_with(
    channels: list[Doc],
    fixtures: list[Doc],
    universes: list[Doc] | None = None,
    footprint: int = 8,
) -> Doc:
    """A minimal valid show with one profile ``p`` / mode ``m``."""
    return {
        "schemaVersion": 1,
        "meta": {"id": "t", "title": "t", "created": "", "modified": "", "app": "test"},
        "profiles": [
            {
                "id": "p",
                "name": "Test",
                "manufacturer": "Test",
                "model": "Test",
                "revision": "1",
                "source": "user",
                "physical": {},
                "wheels": [],
                "modes": [
                    {
                        "id": "m",
                        "name": "m",
                        "footprint": footprint,
                        "intensityStrategy": "dimmerChannel",
                        "elements": [{"index": 0, "name": "Main"}],
                        "channels": channels,
                    }
                ],
            }
        ],
        "universes": universes or [{"id": "u1", "name": "One", "number": 1}],
        "fixtures": fixtures,
        "groups": [],
        "presets": [],
        "effects": [],
        "cueLists": [],
        "playbacks": [],
        "pages": [],
        "masters": [],
        "surfaces": [],
        "bindings": [],
        "output": {
            "engineHz": 50,
            "sacnSourceName": "t",
            "sacnCid": "00000000-0000-0000-0000-000000000000",
            "holdLastFrameOnEngineStall": True,
            "routes": [],
        },
        "park": [],
    }


def at(universe: str, address: int) -> Doc:
    return {"universeId": universe, "address": address}


def test_non_adjacent_fine_offsets() -> None:
    # Coarse pan/tilt at offsets 0–1, fine bytes in a separate block at 2–3.
    doc = show_with(
        [
            channel(0, "pan", 0x1234, 2, fineOffsets=[2]),
            channel(1, "tilt", 0xABCD, 2, fineOffsets=[3]),
            channel(4, "intensity", 0),
        ],
        [fixture("f", 1, at("u1", 10))],
    )
    assert nonzero(compiled(doc).baseImages[0]) == {10: 0x12, 11: 0xAB, 12: 0x34, 13: 0xCD}


def test_three_byte_channel_with_implied_fine_offsets() -> None:
    doc = show_with(
        [channel(0, "pan", 0x123456, 3), channel(3, "intensity", 0)],
        [fixture("f", 1, at("u1", 1))],
    )
    assert nonzero(compiled(doc).baseImages[0]) == {1: 0x12, 2: 0x34, 3: 0x56}


def test_three_byte_channel_with_explicit_fine_offsets() -> None:
    doc = show_with(
        [channel(0, "pan", 0x123456, 3, fineOffsets=[5, 3]), channel(1, "intensity", 0)],
        [fixture("f", 1, at("u1", 1))],
    )
    assert nonzero(compiled(doc).baseImages[0]) == {1: 0x12, 6: 0x34, 4: 0x56}


def test_universes_are_ordered_by_number() -> None:
    doc = show_with(
        [channel(0, "intensity", 7)],
        [fixture("a", 1, at("u-ten", 1)), fixture("b", 2, at("u-two", 2))],
        universes=[
            {"id": "u-ten", "name": "Ten", "number": 10},
            {"id": "u-empty", "name": "Empty", "number": 5},
            {"id": "u-two", "name": "Two", "number": 2},
        ],
    )
    result = compiled(doc)
    assert [(u.id, u.number, u.name) for u in result.universes] == [
        ("u-two", 2, "Two"),
        ("u-empty", 5, "Empty"),
        ("u-ten", 10, "Ten"),
    ]
    assert [nonzero(row) for row in result.baseImages] == [{2: 7}, {}, {1: 7}]


def test_unpatched_fixtures_are_skipped() -> None:
    doc = show_with([channel(0, "intensity", 255)], [fixture("f", 1, None)])
    assert nonzero(compiled(doc).baseImages[0]) == {}


def test_on_overlap_the_later_fixture_wins() -> None:
    doc = show_with(
        [channel(0, "intensity", 11), channel(1, "pan", 22)],
        [fixture("first", 1, at("u1", 1))],
        footprint=2,
    )
    # A second mode with different defaults, patched one channel later.
    doc["profiles"][0]["modes"].append(
        {
            **doc["profiles"][0]["modes"][0],
            "id": "m2",
            "channels": [channel(0, "intensity", 33), channel(1, "pan", 44)],
        }
    )
    doc["fixtures"].append(fixture("second", 2, at("u1", 2), mode="m2"))
    _, issues = validate_show(json.dumps(doc))
    assert [issue.severity for issue in issues] == ["warning"]  # the overlap
    assert nonzero(compiled(doc).baseImages[0]) == {1: 11, 2: 33, 3: 44}


def test_element_patch_is_unsupported() -> None:
    doc = show_with([channel(0, "intensity", 1)], [fixture("f", 1, at("u1", 1))])
    doc["fixtures"][0]["elementPatch"] = {"0": at("u1", 100)}
    show, issues = validate_show(json.dumps(doc))
    assert show is not None
    assert issues == []
    with pytest.raises(UnsupportedFeature, match=r"fixtures\[0\]\.elementPatch"):
        compile_show(show)


def test_base_images_are_read_only(appendix_a: Doc) -> None:
    images = compiled(appendix_a).baseImages
    with pytest.raises(ValueError, match="read-only"):
        images[0, 0] = 1


def test_compiling_does_not_mutate_the_show(appendix_a: Doc) -> None:
    show, _ = validate_show(json.dumps(appendix_a))
    assert show is not None
    before = json.dumps(show, sort_keys=True)
    compile_show(show)
    assert json.dumps(show, sort_keys=True) == before


def test_every_compiled_array_is_read_only(appendix_a: Doc) -> None:
    # The compiled show is shared between threads (plan decision 15).
    def arrays(node: object) -> list[np.ndarray[Any, Any]]:
        if isinstance(node, np.ndarray):
            return [node]
        if dataclasses.is_dataclass(node) and not isinstance(node, type):
            return [a for f in dataclasses.fields(node) for a in arrays(getattr(node, f.name))]
        if isinstance(node, tuple):
            return [a for item in node if item is not None for a in arrays(item)]
        return []

    found = arrays(compiled(appendix_a))
    assert len(found) > 30
    assert not [a for a in found if a.flags.writeable]


# --------------------------------------------- Phase 7: unpatched fixtures, park


def _par2(doc: Doc, **changes: Any) -> Doc:
    """An unpatched copy of Par 1, appended as fixtures[3] ('Par 2')."""
    par = {**copy.deepcopy(doc["fixtures"][2]), "id": "fx-par2", "number": 202, "name": "Par 2"}
    doc["fixtures"].append({**par, "patch": None, **changes})
    return doc


def test_unpatched_fixtures_that_a_playback_drives_are_warned_about() -> None:
    doc = load_doc(APPENDIX_A)
    doc["fixtures"][1]["patch"] = None
    doc["fixtures"][2]["patch"] = None
    assert [str(w) for w in compile_doc(doc).warnings] == [
        "fixtures[1]: 'MH 2' is not patched; playback 1 'Song' drives it",
        "fixtures[2]: 'Par 1' is not patched; playback 3 'Blue' drives it",
    ]


def test_an_unpatched_fixture_only_a_park_entry_drives_is_warned_about() -> None:
    doc = _par2(load_doc(APPENDIX_A))
    assert compile_doc(doc).warnings == ()  # nothing drives it
    doc["park"] = [
        {"slot": {"target": {"fixtureId": "fx-par2", "element": 0}, "attribute": "intensity"},
         "value": 1}
    ]  # fmt: skip
    assert [str(w) for w in compile_doc(doc).warnings] == [
        "fixtures[3]: 'Par 2' is not patched; park[0] drives it"
    ]


def test_park_entries_that_cannot_act_are_warned_about_and_skipped() -> None:
    doc = load_doc(APPENDIX_A)
    doc["park"] = [
        {"slot": {"target": {"fixtureId": "fx-par1", "element": 0}, "attribute": "gobo1"},
         "value": {"slot": "open"}},
        {"slot": {"target": {"fixtureId": "fx-mh1", "element": 0}, "attribute": "gobo1"},
         "value": {"slot": "nope"}},
        {"slot": {"target": {"fixtureId": "fx-mh1", "element": 0}, "attribute": "pan"},
         "value": 5},
    ]  # fmt: skip
    compiled = compile_doc(doc)
    assert [str(w) for w in compiled.warnings] == [
        "park[0].slot.attribute: 'Par 1' element 0 has no 'gobo1'; this entry does nothing",
        "park[1].value.slot: fx-mh1:0 has no 'gobo1' option 'nope'; it offers 'open', "
        "'breakup'; this entry does nothing",
    ]
    pan = compiled.slots.slots[compiled.slots.byKey[("fx-mh1:0", "pan")]]
    assert compiled.safety.parkLanes.tolist() == [pan.laneOffset]
    assert compiled.safety.parkValues.tolist() == [5.0]
