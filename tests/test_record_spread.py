"""A recorded spread follows its group (GAP-49 of ``docs/dev/tui/engine-gaps.md``).

The programmer holds a spread as each target's value. When recording covers
a group's members with literals that differ, it checks whether they are a
spread over the members, in their order: linear, center or edges, from the
values themselves. If one gives every value exactly, the cue stores that
spread, so a fixture that joins the group later takes its place in the fan
(Q12 (a) of the pending plan). Otherwise the values stay per target.

The rig: five Appendix A heads, 101 to 105, and two RGB pars, 201 and 202.
Group 1 is the heads 101 to 104, group 2 the pars, group 3 101 and 102.
"""

from __future__ import annotations

import math
from typing import Any, cast

import pytest

from builders import Doc, busk_rig, group, rgb, show_of
from busk import OfflineShow
from busk.compiler.compile import compile_show
from test_tracking import held

HEADS = [f"fx-mh{k}" for k in range(1, 6)]


def rig() -> Doc:
    doc = busk_rig(spots=5, pars=2)
    doc["groups"] = [
        group("g-heads", 1, *HEADS[:4]),
        group("g-pars", 2, "fx-par1", "fx-par2"),
        group("g-two", 3, "fx-mh1", "fx-mh2"),
    ]
    return doc


@pytest.fixture
def offline() -> OfflineShow:
    return OfflineShow(show_of(rig()))


def run(show: OfflineShow, *lines: str) -> list[str]:
    texts = []
    for line in lines:
        reply = show.execute(line)
        assert reply.ok, f"{line}: {reply.text}"
        texts.append(reply.text)
    return texts


def entries(show: OfflineShow, cue: int = 0) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], show.show["cueLists"][0]["cues"][cue]["entries"])


def sources(show: OfflineShow, cue: int = 0) -> list[tuple[str, str, dict[str, Any]]]:
    """Each entry of the cue: its targets' kind, its attribute and its value."""
    return [(e["targets"]["kind"], e["attribute"], e["value"]) for e in entries(show, cue)]


def on_stage(show: OfflineShow, attribute: str, cue: int = 0) -> dict[str, list[float]]:
    """Each fixture's lanes of ``attribute`` in cue 1/``cue + 1``, as compiled."""
    compiled = compile_show(show.show)
    slots = held(compiled, compiled.cueLists[show.show["cueLists"][0]["id"]].cues[cue])
    return {f: found.lanes for (f, a), found in slots.items() if a == attribute}


def spread(start: Any, end: Any, curve: str | None = None) -> dict[str, Any]:
    source = {"kind": "spread", "from": start, "to": end}
    return source if curve is None else {**source, "curve": curve}


# ------------------------------------------------------------ what is found


@pytest.mark.parametrize(
    ("heads", "line", "expected"),
    [
        (4, "-30 30", spread(-30, 30)),
        (4, "30 to -30", spread(30, -30)),
        (4, "-30 30 center", spread(-30, 30, "center")),  # no head at `to`: found by rounding
        (4, "-30 30 edges", spread(-30, 30, "edges")),
        (5, "-30 30", spread(-30, 30)),
        (5, "-30 30 center", spread(-30, 30, "center")),
        (5, "-30 30 edges", spread(30, -30, "center")),  # the same fan, center tried first
        (4, "0.1 to 0.7 center", spread(0.1, 0.7, "center")),
        (4, "0 to 12.3456789012345", spread(0, 12.3456789012345)),  # past 9 decimals: as it is
    ],
)
def test_a_spread_on_a_group_is_recorded_as_the_spread(
    offline: OfflineShow, heads: int, line: str, expected: dict[str, Any]
) -> None:
    if heads == 5:
        run(offline, "sel group 1, fixture 105", "record group 1 merge")
    run(offline, "sel group 1", f"set pan spread {line}", "record cue 1")
    assert sources(offline) == [("group", "pan", expected)]


@pytest.mark.parametrize("line", ["0 -30 edges", "30 0 center"])
def test_an_end_at_zero_is_not_negative_zero(offline: OfflineShow, line: str) -> None:
    """The line reaches the end at 0 at -1.8e-15 here: rounded, it is 0, not -0."""
    run(offline, "sel group 1", f"set pan spread {line}", "record cue 1")
    ends = sources(offline)[0][2]
    assert [math.copysign(1, ends[end]) for end in ("from", "to") if ends[end] == 0] == [1.0]


@pytest.mark.parametrize("shape", ["", "center", "edges"])
def test_the_spread_plays_as_the_values_recorded_per_target(
    offline: OfflineShow, shape: str
) -> None:
    """Exactly: each head's compiled pan is the float the programmer held."""
    run(offline, "sel group 1", f"set pan spread -45.3 to 30.7 {shape}", "set tilt spread 3.1 7.3")
    run(offline, "record cue 1/1", "record cue 1/2 freeze")
    assert [s[2]["kind"] for s in sources(offline)] == ["spread", "spread"]
    assert [s[2]["kind"] for s in sources(offline, 1)] == ["perTarget", "perTarget"]
    for attribute in ("pan", "tilt"):
        assert on_stage(offline, attribute) == on_stage(offline, attribute, 1)


def test_a_head_that_joins_the_group_takes_its_place_in_the_fan(offline: OfflineShow) -> None:
    run(offline, "sel group 1", "set pan spread -30 30", "record cue 1")
    assert on_stage(offline, "pan") == {
        "fx-mh1": [-30.0], "fx-mh2": [-10.0], "fx-mh3": [10.0], "fx-mh4": [30.0]
    }  # fmt: skip
    run(offline, "sel fixture 105", "record group 1 merge")
    assert on_stage(offline, "pan") == {
        "fx-mh1": [-30.0], "fx-mh2": [-15.0], "fx-mh3": [0.0], "fx-mh4": [15.0], "fx-mh5": [30.0]
    }  # fmt: skip


def test_a_member_without_the_attribute_keeps_its_place(offline: OfflineShow) -> None:
    """A par between the heads has no pan: the spread counts it, as `set` does."""
    run(offline, "sel fixture 101, 201, 102, 103", "record group 4", "set pan spread -30 30")
    run(offline, "record cue 1")
    assert sources(offline) == [("group", "pan", spread(-30, 30))]
    assert on_stage(offline, "pan") == {"fx-mh1": [-30.0], "fx-mh2": [10.0], "fx-mh3": [30.0]}


def test_a_member_listed_twice_takes_its_last_place() -> None:
    """Only the generic edit lists a member twice. The cue compiles a later
    place over an earlier one, so 101, at places 0 and 2 of 4, plays the
    value of place 2."""
    doc = rig()
    doc["groups"].append(group("g-twice", 4, "fx-mh1", "fx-mh2", "fx-mh1", "fx-mh3"))
    offline = OfflineShow(show_of(doc))
    for number, pan in ((101, 10), (102, -10), (103, 30)):
        run(offline, f"sel fixture {number}", f"set pan {pan}")
    run(offline, "sel group 4", "record cue 1")
    assert sources(offline) == [("group", "pan", spread(-30, 30))]
    assert on_stage(offline, "pan") == {"fx-mh1": [10.0], "fx-mh2": [-10.0], "fx-mh3": [30.0]}


@pytest.mark.parametrize(
    ("chosen", "line", "fan"),
    [
        ("group 2", "1 0 0 to 0 0.5 1", spread(rgb(1, 0, 0), rgb(0, 0.5, 1))),  # the pars
        # The heads, with no head at `to`: as computed, its red is 0.2000000000000001.
        ("group 1", "0.9 0.1 0.3 to 0.2 0.7 0.6 center",
         spread(rgb(0.9, 0.1, 0.3), rgb(0.2, 0.7, 0.6), "center")),
    ],
)  # fmt: skip
def test_a_colour_spread(offline: OfflineShow, chosen: str, line: str, fan: Doc) -> None:
    run(offline, f"sel {chosen}", f"set color spread {line}", "record cue 1/1")
    run(offline, "record cue 1/2 freeze")
    assert sources(offline) == [("group", "color", fan)]
    assert repr(on_stage(offline, "color")) == repr(on_stage(offline, "color", 1))  # NaN: derive w


def test_two_members_always_fit_a_spread(offline: OfflineShow) -> None:
    run(offline, "sel fixture 101", "set intensity 70%", "sel fixture 102", "set intensity 20%")
    run(offline, "record cue 1")
    assert sources(offline) == [("group", "intensity", spread(0.7, 0.2))]


def test_values_over_the_group_and_another_head_fan_over_the_group(offline: OfflineShow) -> None:
    """Spread over five heads, the four of group 1 still lie on a fan: it is
    recorded, from the first to its fourth value, and 105 keeps its own."""
    run(offline, "sel group 1, fixture 105", "set pan spread -30 30", "record cue 1")
    assert sources(offline) == [
        ("group", "pan", spread(-30, 15)),
        ("targets", "pan", {"kind": "literal", "value": 30.0}),
    ]


# ---------------------------------------------------------- what stays per target


def per_target(show: OfflineShow) -> list[tuple[str, str, str]]:
    return [(kind, attribute, value["kind"]) for kind, attribute, value in sources(show)]


def test_values_that_are_not_a_fan_stay_per_target(offline: OfflineShow) -> None:
    for number, level in zip((101, 102, 103, 104), (10, 50, 20, 90), strict=True):
        run(offline, f"sel fixture {number}", f"set intensity {level}%")
    run(offline, "record cue 1")
    assert per_target(offline) == [("group", "intensity", "perTarget")]


def test_a_value_off_the_fan_by_a_rounding_error_stays_per_target(offline: OfflineShow) -> None:
    """The values must be exactly the spread's: 1/3 is 0.333…33, not …334."""
    run(offline, "sel group 1", "set intensity spread 0 to 1", "sel fixture 102")
    run(offline, "set intensity 33.33333333334%", "record cue 1")
    assert per_target(offline) == [("group", "intensity", "perTarget")]


def test_ends_set_would_refuse_leave_it_per_target(offline: OfflineShow) -> None:
    """50, 100, 100, 50 is a centre fan to 125 % over four heads, or edges from it."""
    run(offline, "sel group 1", "set intensity 100%", "sel fixture 101, 104", "set intensity 50%")
    run(offline, "record cue 1")
    assert per_target(offline) == [("group", "intensity", "perTarget")]


def test_colours_with_other_components_stay_per_target(offline: OfflineShow) -> None:
    run(offline, "sel group 1", "set color spread 1 0 0 to 0 0 1", "sel fixture 104")
    run(offline, "set color.w 50%", "record cue 1")
    assert per_target(offline) == [("group", "color", "perTarget")]


def test_a_spread_over_targets_that_are_no_group_stays_per_target(offline: OfflineShow) -> None:
    run(offline, "sel fixture 102 thru 104", "set pan spread -30 30", "record cue 1")
    assert per_target(offline) == [("targets", "pan", "perTarget")]


def test_freeze_records_per_target(offline: OfflineShow) -> None:
    run(offline, "sel group 1", "set pan spread -30 30", "record cue 1 freeze")
    assert per_target(offline) == [("targets", "pan", "perTarget")]


# ------------------------------------------------------------------- tracking


def test_a_spread_equal_to_what_the_list_tracks_is_not_stored(offline: OfflineShow) -> None:
    run(offline, "cuelist add 1", "cuelist 1 tracking true")
    run(offline, "sel group 1", "set pan spread -30 30", "record cue 1")
    assert run(offline, "record cue 1/2") == [
        "recorded cue 1/2: 0 entries; 4 values tracked from cue 1/1"
    ]
    run(offline, "set pan spread -60 60 center")
    assert run(offline, "record cue 1/3") == ["recorded cue 1/3: 1 entry"]
    assert sources(offline, 2) == [("group", "pan", spread(-60, 60, "center"))]
