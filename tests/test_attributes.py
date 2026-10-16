"""The attribute registry matches the spec's §5.3 table."""

from __future__ import annotations

import pytest

from busk.model.attributes import ATTRIBUTES, ScalarRange, value_kind

# The §5.3 table, row by row: id, family, kind, unit, merge, fade, default.
# Colour's tabled unit "linear RGB" is stored as "normalized" (components 0..1).
SPEC_TABLE = [
    ("intensity", "intensity", "scalar", "normalized", "HTP", "fade", 0.0),
    ("pan", "position", "scalar", "degrees", "LTP", "fade", 0.0),
    ("tilt", "position", "scalar", "degrees", "LTP", "fade", 0.0),
    ("positionSpeed", "position", "scalar", "normalized", "LTP", "snap", 0.0),
    ("color", "color", "color", "normalized", "LTP", "fade", {"r": 1.0, "g": 1.0, "b": 1.0}),
    ("colorWheel", "color", "discrete", "none", "LTP", "snap", {"slot": "open"}),
    ("cto", "color", "scalar", "normalized", "LTP", "fade", 0.0),
    ("gobo1", "beam", "discrete", "none", "LTP", "snap", {"slot": "open"}),
    ("gobo2", "beam", "discrete", "none", "LTP", "snap", {"slot": "open"}),
    ("gobo1Rotation", "beam", "scalar", "degPerSec", "LTP", "fade", 0.0),
    ("gobo2Rotation", "beam", "scalar", "degPerSec", "LTP", "fade", 0.0),
    ("prism", "beam", "discrete", "none", "LTP", "snap", {"slot": "off"}),
    ("prismRotation", "beam", "scalar", "degPerSec", "LTP", "fade", 0.0),
    ("zoom", "beam", "scalar", "degrees", "LTP", "fade", "profileMidpoint"),
    ("iris", "beam", "scalar", "normalized", "LTP", "fade", 1.0),
    ("frost", "beam", "scalar", "normalized", "LTP", "fade", 0.0),
    ("focus", "focus", "scalar", "normalized", "LTP", "fade", 0.5),
    ("shutter", "shutter", "discrete", "none", "LTP", "snap", {"slot": "open"}),
    ("strobeRate", "shutter", "scalar", "hz", "LTP", "fade", 0.0),
    ("control", "control", "discrete", "none", "LTP", "snap", {"slot": "none"}),
]


def test_registry_holds_exactly_the_spec_attributes_in_table_order() -> None:
    assert list(ATTRIBUTES) == [row[0] for row in SPEC_TABLE]
    assert len(ATTRIBUTES) == 20


@pytest.mark.parametrize(
    ("attribute", "family", "kind", "unit", "merge", "fade", "default"), SPEC_TABLE
)
def test_definition_matches_spec_row(
    attribute: str, family: str, kind: str, unit: str, merge: str, fade: str, default: object
) -> None:
    definition = ATTRIBUTES[attribute]
    assert definition.id == attribute
    assert (definition.family, definition.kind, definition.unit) == (family, kind, unit)
    assert (definition.merge, definition.fade) == (merge, fade)
    assert definition.default == default


def test_only_intensity_is_htp() -> None:
    assert [a.id for a in ATTRIBUTES.values() if a.merge == "HTP"] == ["intensity"]


def test_every_discrete_attribute_snaps_at_start() -> None:
    discrete = [a for a in ATTRIBUTES.values() if a.kind == "discrete"]
    assert discrete
    for definition in discrete:
        assert (definition.fade, definition.snapAt) == ("snap", "start"), definition.id


def test_each_default_shape_matches_its_kind() -> None:
    for definition in ATTRIBUTES.values():
        if definition.id == "zoom":
            # The profile midpoint is resolved per fixture by the slot compiler.
            assert definition.default == "profileMidpoint"
        else:
            assert value_kind(definition.default) == definition.kind, definition.id


def test_normalised_scalars_have_unit_range_and_others_none() -> None:
    for definition in ATTRIBUTES.values():
        if definition.kind == "scalar" and definition.unit == "normalized":
            assert definition.range == ScalarRange(min=0.0, max=1.0), definition.id
        else:
            assert definition.range is None, definition.id


def test_registry_is_read_only() -> None:
    with pytest.raises(TypeError):
        ATTRIBUTES["sparkle"] = ATTRIBUTES["intensity"]  # type: ignore[index]


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        (0, "scalar"),
        (-12.5, "scalar"),
        ({"r": 1, "g": 0, "b": 0}, "color"),
        ({"r": 1}, "color"),  # malformed colours are still "colour-shaped"
        ({"slot": "open"}, "discrete"),
        ({"wheel": "gobo1", "slot": "open"}, "discrete"),
        (True, None),  # bool is an int in Python, but not a number in a show
        ("open", None),
        ([1, 2], None),
        (None, None),
    ],
)
def test_value_kind(value: object, kind: str | None) -> None:
    assert value_kind(value) == kind
