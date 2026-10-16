"""Static values files (``busk run --values``): the three checks and the frame.

1. structural, as ``list[ParkEntry]``;
2. semantic, with the park checks (target, registry attribute, not control, shape);
3. against the compiled show (the target has the attribute, the option exists,
   the wheel matches) — :func:`busk.compiler.values.compile_values`.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from builders import DEMO, compile_doc, load_doc
from busk.compiler.compile import CompiledShow
from busk.compiler.values import compile_values
from busk.model.common import FixtureId, TargetRef
from busk.model.show import Show
from busk.model.validate import has_errors, validate_show, validate_values
from busk.persistence.values_file import load_values


@pytest.fixture(scope="module")
def show() -> Show:
    validated, _ = validate_show(DEMO.read_bytes())
    assert validated is not None
    return validated


@pytest.fixture(scope="module")
def compiled() -> CompiledShow:
    return compile_doc(load_doc(DEMO))


def entry(fixture_id: str, attribute: str, value: Any, element: int = 0) -> dict[str, Any]:
    target = {"fixtureId": fixture_id, "element": element}
    return {"slot": {"target": target, "attribute": attribute}, "value": value}


def check(
    show: Show, compiled: CompiledShow, entries: list[Any]
) -> tuple[Any, set[tuple[str, str]]]:
    """Run all three checks; return the frame (or None) and ``(severity, path)``s."""
    parsed, issues = validate_values(json.dumps(entries), show)
    if parsed is None or has_errors(issues):
        return None, {(i.severity, i.path) for i in issues}
    frame, issues = compile_values(compiled, parsed)
    return frame, {(i.severity, i.path) for i in issues}


def lanes(compiled: CompiledShow, frame: Any, fixture_id: str, attribute: str) -> list[float]:
    found = compiled.slots.find(TargetRef(fixtureId=FixtureId(fixture_id), element=0), attribute)
    assert found is not None
    return list(frame[found.lanes])


def test_a_valid_file_compiles(show: Show, compiled: CompiledShow) -> None:
    frame, issues = check(
        show,
        compiled,
        [
            entry("fx-mh1", "pan", 90),
            entry("fx-mh1", "colorWheel", {"wheel": "color1", "slot": "red"}),
            entry("fx-wash1", "color", {"r": 1, "g": 0.5, "b": 0}),
        ],
    )
    assert issues == set()
    assert lanes(compiled, frame, "fx-mh1", "pan") == [90.0]
    assert lanes(compiled, frame, "fx-mh1", "colorWheel") == [7.0]  # red is option 7
    r, g, b, w = lanes(compiled, frame, "fx-wash1", "color")
    assert (r, g, b) == (1.0, 0.5, 0.0)
    assert math.isnan(w)  # not given: derived
    assert lanes(compiled, frame, "fx-mh1", "tilt") == [0.0]  # untouched slots keep defaults
    assert not frame.flags.writeable


def test_later_entries_override_earlier_ones(show: Show, compiled: CompiledShow) -> None:
    frame, issues = check(show, compiled, [entry("fx-mh1", "pan", 90), entry("fx-mh1", "pan", -30)])
    assert issues == set()
    assert lanes(compiled, frame, "fx-mh1", "pan") == [-30.0]


@pytest.mark.parametrize(
    ("bad", "path"),
    [
        (entry("fx-wash1", "zoom", 20), "values[1].slot.attribute"),  # no zoom on an ML-56
        (entry("fx-mh1", "gobo1", {"slot": "gobo9"}), "values[1].value.slot"),
        (entry("fx-mh1", "gobo1", {"wheel": "color1", "slot": "open"}), "values[1].value.wheel"),
        (entry("fx-nope", "pan", 0), "values[1].slot.target.fixtureId"),
        (
            entry("fx-bar1", "color", {"r": 1, "g": 0, "b": 0}, element=12),
            "values[1].slot.target.element",
        ),
        (entry("fx-mh1", "pan", {"slot": "open"}), "values[1].value"),  # wrong shape
        (entry("fx-mh1", "control", {"slot": "reset"}), "values[1].slot.attribute"),
        (entry("fx-mh1", "sparkle", 1), "values[1].slot.attribute"),  # not in the registry
        (entry("fx-mh1", "shutter", {"slot": "goboYoyo"}), "values[1].value.slot"),
    ],
)
def test_errors_carry_their_path(
    show: Show, compiled: CompiledShow, bad: dict[str, Any], path: str
) -> None:
    frame, issues = check(show, compiled, [entry("fx-mh1", "pan", 0), bad])
    assert frame is None
    assert issues == {("error", path)}


def test_every_error_is_collected(show: Show, compiled: CompiledShow) -> None:
    frame, issues = check(
        show,
        compiled,
        [
            entry("fx-wash1", "zoom", 20),
            entry("fx-mh1", "pan", 1),
            entry("fx-mh1", "gobo1", {"slot": "x"}),
        ],
    )
    assert frame is None
    assert issues == {("error", "values[0].slot.attribute"), ("error", "values[2].value.slot")}


@pytest.mark.parametrize(
    ("text", "path"),
    [
        ('{"not": "a list"}', "values"),
        (json.dumps([{"slot": entry("fx-mh1", "pan", 0)["slot"]}]), "values[0].value"),  # missing
        (json.dumps([{**entry("fx-mh1", "pan", 0), "x": 0}]), "values[0].x"),  # unknown key
        ("[1,", ""),  # invalid JSON
    ],
)
def test_structural_errors(show: Show, text: str, path: str) -> None:
    entries, issues = validate_values(text, show)
    assert entries is None
    assert [(i.severity, i.path) for i in issues] == [("error", path)]


def test_load_values_reads_the_file(tmp_path: Path, show: Show) -> None:
    path = tmp_path / "values.json"
    path.write_text(json.dumps([entry("fx-mh1", "intensity", 1)]), encoding="utf-8")
    entries, issues = load_values(path, show)
    assert issues == []
    assert entries == [entry("fx-mh1", "intensity", 1)]
    with pytest.raises(FileNotFoundError):
        load_values(tmp_path / "missing.json", show)
