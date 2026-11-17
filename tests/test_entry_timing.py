"""Timing per target, with a fan (GAP-48 of ``docs/dev/tui/engine-gaps.md``).

``cue L/C time <targets> <family> <fade> [to <fade>] [delay <d> [to <d>]]
[center|edges] [<curve>]`` sets the own timing of the cue's entries of that
family on exactly those targets, and ``… none`` removes it. A ``to`` makes a
fan: the entry's targets, in their order, take the times from the first to
the second, as a spread takes values (Q11 (a) of the pending plan).

The rig: five Appendix A heads, 101 to 105. Group 1 is all five, group 2
101 and 102. Cue 1/1 sets the five heads' intensity, pan and tilt on group 1,
then tilt again on 104 and 105 as a list, with a 2 s fade.
"""

from __future__ import annotations

import copy
from typing import Any, cast

import pytest

from builders import (
    APPENDIX_A,
    ROOT,
    Doc,
    busk_rig,
    compile_doc,
    cue,
    cue_list,
    entry,
    group,
    in_group,
    issues_of,
    literal,
    load_doc,
    playback,
    show_of,
    targets,
)
from busk import LiveShow, OfflineShow, load_show, new_show
from busk.compiler.compile import compile_show
from busk.compiler.cues import SlotTiming
from busk.console.parser import Context, Submit, parse
from busk.model.show import Show
from busk.model.validate import has_errors
from busk.session.ids import CounterIds
from test_console import eventually, status_of
from test_console_parser import LIBRARY, labelled
from test_tracking import held

HEADS = [f"fx-mh{k}" for k in range(1, 6)]
CLUB_NIGHT = ROOT / "examples" / "club-night.busk"
TUPPER_DEMO = ROOT / "examples" / "tupperdmx" / "tupper-demo.show"


def rig(pars: int = 0) -> Doc:
    doc = busk_rig(spots=5, pars=pars)
    doc["groups"] = [group("g-heads", 1, *HEADS), group("g-two", 2, "fx-mh1", "fx-mh2")]
    doc["cueLists"].append(
        cue_list(
            "cl",
            1,
            cue(
                "c1",
                entry(in_group("g-heads"), "intensity", literal(1.0)),
                entry(in_group("g-heads"), "pan", literal(10.0)),
                entry(in_group("g-heads"), "tilt", literal(20.0)),
                entry(targets("fx-mh4", "fx-mh5"), "tilt", literal(30.0)),
                fade_in=2,
                fade_out=2,
            ),
        )
    )
    doc["playbacks"].append(playback("pb", 1, "cl"))
    return doc


@pytest.fixture
def offline() -> OfflineShow:
    return OfflineShow(show_of(rig()))


def run(show: OfflineShow | LiveShow, *lines: str) -> list[str]:
    texts = []
    for line in lines:
        reply = show.execute(line)
        assert reply.ok, f"{line}: {reply.text}"
        texts.append(reply.text)
    return texts


def entries(show: OfflineShow | LiveShow) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], show.show["cueLists"][0]["cues"][0]["entries"])


def timings(show: Show, attribute: str) -> list[SlotTiming]:
    """How each head that cue 1/1 gives ``attribute`` fades it in, as compiled."""
    compiled = compile_show(show)
    slots = held(compiled, compiled.cueLists["cl"].cues[0])
    return [slots[head, attribute].rising for head in HEADS if (head, attribute) in slots]


def spans(show: Show, attribute: str = "intensity") -> list[tuple[float, float]]:
    """Each head's fade of ``attribute``: where it starts and ends, in seconds after GO."""
    return [(round(t.delay, 6), round(t.delay + t.fade, 6)) for t in timings(show, attribute)]


# --------------------------------------------------------------------- fans


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("1 to 5", [(0, 1), (0, 2), (0, 3), (0, 4), (0, 5)]),  # up
        ("5 to 1", [(0, 5), (0, 4), (0, 3), (0, 2), (0, 1)]),  # down
        ("1 to 5 center", [(0, 1), (0, 3), (0, 5), (0, 3), (0, 1)]),
        ("1 to 5 edges", [(0, 5), (0, 3), (0, 1), (0, 3), (0, 5)]),
        ("2 delay 0 to 2", [(0, 2), (0.5, 2.5), (1, 3), (1.5, 3.5), (2, 4)]),
        ("2 delay 2 to 0", [(2, 4), (1.5, 3.5), (1, 3), (0.5, 2.5), (0, 2)]),
        ("1 to 3 delay 0 to 2 edges", [(2, 5), (1, 3), (0, 1), (1, 3), (2, 5)]),
        ("4", [(0, 4)] * 5),  # no fan: one timing for every head
        ("4 delay 1", [(1, 5)] * 5),
    ],
)
def test_a_fan_spreads_the_times_over_the_targets_in_order(
    offline: OfflineShow, line: str, expected: list[tuple[float, float]]
) -> None:
    run(offline, f"cue 1/1 time group 1 intensity {line}")
    assert spans(offline.show) == expected


def test_an_intensity_falls_with_its_entrys_timing_too(offline: OfflineShow) -> None:
    run(offline, "cue 1/1 time group 1 intensity 1 to 5 delay 1 easeIn")
    compiled = compile_show(offline.show)
    slots = held(compiled, compiled.cueLists["cl"].cues[0])
    assert [slots[head, "intensity"].falling for head in HEADS] == [
        SlotTiming(fade=fade, delay=1, curve="easeIn") for fade in (1, 2, 3, 4, 5)
    ]


def test_the_stage_staggers_the_heads(offline: OfflineShow) -> None:
    """``delay 0 to 2`` with no fade: one more head comes on every half second."""
    run(offline, "cue 1/1 time group 1 intensity 0 delay 0 to 2", "fader 1 1", "go 1")
    start = offline.time
    lit = []
    for after in (0.25, 0.75, 1.25, 1.75, 2.25):
        offline.tick(start + after)
        lit.append([f.intensity for f in offline.output.fixtures])
    assert lit == [[1.0] * k + [0.0] * (5 - k) for k in range(1, 6)]


def test_a_fan_follows_its_group_as_it_grows(offline: OfflineShow) -> None:
    run(offline, "sel fixture 105", "record group 1 remove")
    run(offline, "cue 1/1 time group 1 intensity 1 to 4")
    assert [t.fade for t in timings(offline.show, "intensity")] == [1, 2, 3, 4]
    run(offline, "sel fixture 105", "record group 1 merge")
    assert [t.fade for t in timings(offline.show, "intensity")] == [1, 1.75, 2.5, 3.25, 4]


def test_a_fan_counts_the_targets_without_the_attribute_as_a_spread_does() -> None:
    """A par in the group has no pan: it keeps its place in the fan."""
    doc = rig(pars=1)
    doc["groups"][0]["members"].insert(1, {"fixtureId": "fx-par1", "element": 0})
    offline = OfflineShow(show_of(doc))
    run(offline, "cue 1/1 time group 1 position 0 to 5")
    assert [t.fade for t in timings(offline.show, "pan")] == [0, 2, 3, 4, 5]


# ------------------------------------------------------- which entries it sets


def test_the_line_is_one_labelled_set_of_the_cues_entries() -> None:
    """Entries have no ids, so the line sets the whole list, in one step."""
    doc = rig()
    action = parse(
        "cue 1/1 time group 1 position 2 delay 0 to 1 edges",
        Context(show_of(doc), LIBRARY, CounterIds()),
    )
    assert isinstance(action, Submit)
    made = doc["cueLists"][0]["cues"][0]["entries"]
    for timed in made[1:3]:
        timed["timing"] = {"fade": 2, "delay": 0, "delayTo": 1, "fan": "edges"}
    assert action.command == labelled(
        "cue 1/1 fades position on group 1 over 2 s, delay 0 s to 1 s, edges",
        {"type": "SET", "path": ["cueLists", {"id": "cl"}, "cues", {"id": "c1"}, "entries"],
         "value": made},
    )  # fmt: skip


def test_the_line_sets_the_entries_of_the_family_on_exactly_those_targets(
    offline: OfflineShow,
) -> None:
    """Group 1's pan and tilt take the fan; the tilt on 104 and 105, a later
    entry, keeps the family's timing and wins for those two."""
    assert run(offline, "cue 1/1 time position 4", "cue 1/1 time group 1 position 1 to 3") == [
        "cue 1/1 fades position over 4 s",
        "cue 1/1 fades position on group 1 over 1 s to 3 s",
    ]
    fan = {"fade": 1, "fadeTo": 3, "delay": 0}
    assert [e.get("timing") for e in entries(offline)] == [None, fan, fan, None]
    assert [t.fade for t in timings(offline.show, "pan")] == [1, 1.5, 2, 2.5, 3]
    assert [t.fade for t in timings(offline.show, "tilt")] == [1, 1.5, 2, 4, 4]


def test_a_list_of_fixtures_is_named_in_any_order(offline: OfflineShow) -> None:
    assert run(offline, "cue 1/1 time fixture 105, 104 position 3 delay 1") == [
        "cue 1/1 fades position on fixture 105, 104 over 3 s, delay 1 s"
    ]
    assert [e.get("timing") for e in entries(offline)] == [
        None, None, None, {"fade": 3, "delay": 1}
    ]  # fmt: skip
    run(offline, "cue 1/1 time fixture 104 thru 105 position 2")
    assert entries(offline)[3]["timing"] == {"fade": 2, "delay": 0}


def test_the_line_replaces_the_timing_whole(offline: OfflineShow) -> None:
    run(offline, "cue 1/1 time group 1 intensity 1 to 2 delay 0 to 1 center bezier 0.4 0 0.2 1")
    assert entries(offline)[0]["timing"] == {
        "fade": 1, "fadeTo": 2, "delay": 0, "delayTo": 1, "fan": "center",
        "curve": {"bezier": (0.4, 0, 0.2, 1)},  # the show holds a tuple
    }  # fmt: skip
    run(offline, "cue 1/1 time group 1 intensity 3")
    assert entries(offline)[0]["timing"] == {"fade": 3, "delay": 0}


def test_none_takes_it_away_and_undo_gives_it_back(offline: OfflineShow) -> None:
    before = offline.show
    family = SlotTiming(fade=4, delay=0, curve="linear")
    run(offline, "cue 1/1 time position 4")
    with_family = offline.show
    run(offline, "cue 1/1 time group 1 position 1 to 3 easeOut")
    assert run(offline, "cue 1/1 time group 1 position none") == [
        "cue 1/1 fades position on group 1 with the cue again"
    ]
    assert offline.show == with_family
    assert timings(offline.show, "pan") == [family] * 5
    assert run(offline, "undo", "undo", "undo") == [
        "undid: cue 1/1 fades position on group 1 with the cue again",
        "undid: cue 1/1 fades position on group 1 over 1 s to 3 s, easeOut",
        "undid: cue 1/1 fades position over 4 s",
    ]
    assert offline.show == before
    run(offline, "redo", "redo")
    assert timings(offline.show, "pan")[-1] == SlotTiming(fade=3, delay=0, curve="easeOut")


# ---------------------------------------------------------------- list cues


def test_list_cues_shows_each_entrys_timing_as_the_line_takes_it(offline: OfflineShow) -> None:
    """After the cue's and its families' timing, in the cue's entry order:
    pan and tilt on group 1, set by one line, come once."""
    run(offline, "cue 1/1 time position 4", "cue 1/1 time group 1 position 1 to 3 center easeOut")
    run(offline, "cue 1/1 time fixture 105, 104 position 2 delay 0 to 1")
    run(offline, "cue 1/1 time group 1 intensity 2 delay 1")
    assert offline.execute("list cues 1").text == (  # in the cue's entry order
        "    1  c1                   time 2, position 4, group 1 intensity 2 delay 1, group 1"
        " position 1 to 3 center easeOut, fixture 104, 105 position 2 delay 0 to 1  go"
    )


def test_each_item_typed_back_gives_the_same_entries(offline: OfflineShow) -> None:
    lines = [
        "group 1 position 1 to 3 delay 0 to 2 edges bezier 0.4 0 0.2 1",
        "fixture 104, 105 position 0.5",
    ]
    for line in lines:
        run(offline, f"cue 1/1 time {line}")
    before = entries(offline)
    assert offline.execute("list cues 1").text == (
        f"    1  c1                   time 2, {', '.join(lines)}  go"
    )
    run(
        offline, "cue 1/1 time group 1 position none", "cue 1/1 time fixture 104, 105 position none"
    )
    assert offline.execute("list cues 1").text == "    1  c1                   time 2  go"
    for line in lines:
        run(offline, f"cue 1/1 time {line}")
    assert entries(offline) == before


def test_list_cues_words_a_timing_only_the_generic_edit_makes() -> None:
    """A delay alone, a fade with a curve, and pan and tilt timed apart."""
    doc = rig()
    made = doc["cueLists"][0]["cues"][0]["entries"]
    made[0]["timing"] = {"delay": 1}
    made[1]["timing"] = {"fade": 3, "curve": "easeIn"}
    made[2]["timing"] = {"fade": 5}
    offline = OfflineShow(show_of(doc))
    assert offline.execute("list cues 1").text == (
        "    1  c1                   time 2, group 1 intensity delay 1, group 1 position 3 easeIn,"
        " group 1 position 5  go"
    )


# ---------------------------------------------------------------- refusals


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("cue 1/1 time group 2 position 4",
         "cue 1/1 sets position on group 1 and fixture 104, 105: name one of them"),
        ("cue 1/1 time fixture 101 thru 105 intensity 4",
         "cue 1/1 sets intensity on group 1: name it"),
        ("cue 1/1 time fixture 104 position 4",
         "cue 1/1 sets position on group 1 and fixture 104, 105: name one of them"),
        ("cue 1/1 time group 1 color 4", "cue 1/1 sets no color"),
        ("cue 1/1 time group 1 intensity none",
         "cue 1/1 has no intensity timing of its own on group 1"),
        ("cue 1/1 time group 1 intensity 4 center",
         "center shapes a fan: give the fade or the delay a 'to'"),
        ("cue 1/1 time group 1 intensity 4 delay 1 edges",
         "edges shapes a fan: give the fade or the delay a 'to'"),
        ("cue 1/1 time group 1 intensity none 4", "unexpected '4'"),
        ("cue 1/1 time group 1 intensity 4 to 6 to 2", "expected a curve (linear, easeIn, "
         "easeOut, easeInOut, snapStart, snapEnd or bezier x1 y1 x2 y2), got 'to'"),
        ("cue 1/1 time group 1 intensity 4 to", "expected a fade time"),
        ("cue 1/1 time group 1 intensity -4", "expected a fade time, got '-4'"),
        ("cue 1/1 time group 1 intensity 4 to 50%", "expected a fade time, got '50%'"),
        ("cue 1/1 time group 1 intensity 4 delay 0 to x", "expected a delay, got 'x'"),
        ("cue 1/1 time group 1 4", "expected intensity or position or color or beam or focus or "
         "shutter, got '4'"),
        ("cue 1/1 time group 9 intensity 4", "no group 9"),
        ("cue 1/1 time fixture 199 intensity 4", "no fixture 199"),
    ],
)  # fmt: skip
def test_a_line_that_names_no_entry_is_refused_in_one_line(
    offline: OfflineShow, line: str, error: str
) -> None:
    before = offline.show
    reply = offline.execute(line)
    assert (reply.ok, reply.text) == (False, f"error: {error}")
    assert offline.show == before
    assert offline.execute("undo").text == "error: nothing to undo"


def test_the_refusal_names_a_run_of_fixtures_as_the_line_takes_it() -> None:
    doc = rig()
    cue_entries = doc["cueLists"][0]["cues"][0]["entries"]
    cue_entries[3]["targets"] = targets("fx-mh1", "fx-mh2", "fx-mh3", "fx-mh5")
    offline = OfflineShow(show_of(doc))
    reply = offline.execute("cue 1/1 time group 2 position 4")
    assert reply.text == (
        "error: cue 1/1 sets position on group 1 and fixture 101 thru 103, 105: name one of them"
    )
    run(offline, "cue 1/1 time fixture 101 thru 103, 105 position 4")
    assert entries(offline)[3]["timing"] == {"fade": 4, "delay": 0}


def test_elements_are_named_one_by_one_unless_the_fixture_is_whole(club_show: Show) -> None:
    """The club's bar, 301, has 12 elements."""
    show = OfflineShow(copy.deepcopy(club_show))
    bar = next(f["id"] for f in show.show["fixtures"] if f["number"] == 301)
    washes = [f["id"] for f in show.show["fixtures"] if 201 <= f["number"] <= 203]
    song = next(cl for cl in show.show["cueLists"] if cl["number"] == 9)
    outro = song["cues"][-1]
    assert outro["number"] == "5"
    path = ["cueLists", {"id": song["id"]}, "cues", {"id": outro["id"]}]
    cells = [{"fixtureId": bar, "element": k} for k in range(12)]
    made = [
        entry({"kind": "targets", "refs": cells[:3]}, "intensity", literal(1.0)),
        entry({"kind": "targets", "refs": cells}, "intensity", literal(1.0)),
        entry(targets(*washes), "intensity", literal(1.0)),
    ]
    assert show.submit(cast(Any, {"type": "SET", "path": [*path, "entries"], "value": made})).ok
    assert show.execute("cue 9/5 time group 1 intensity 2").text == (
        "error: cue 9/5 sets intensity on fixture 301.1, 301.2, 301.3; fixture 301 and "
        "fixture 201 thru 203: name one of them"
    )
    run(show, "cue 9/5 time fixture 301.1 thru 301.3 intensity 2", "cue 9/5 time fixture 301 "
        "intensity 3", "cue 9/5 time fixture 203, 201, 202 intensity 4")  # fmt: skip
    song = next(cl for cl in show.show["cueLists"] if cl["number"] == 9)
    assert [e["timing"]["fade"] for e in song["cues"][-1]["entries"]] == [
        2, 3, 4
    ]  # fmt: skip


# --------------------------------------------------------- recording again


def test_load_then_replace_keeps_the_timing() -> None:
    """Without the tilt on 104 and 105, the cue comes back as it was."""
    doc = rig()
    del doc["cueLists"][0]["cues"][0]["entries"][3]
    offline = OfflineShow(show_of(doc))
    run(offline, "cue 1/1 time group 1 intensity 1 to 5")
    run(offline, "cue 1/1 time group 1 position 3 delay 0 to 1 edges easeOut")
    before = offline.show
    assert run(offline, "load cue 1/1")[0].endswith(
        "; 3 entries' own timing is not loaded, and replace keeps it on the same targets"
    )
    run(offline, "record cue 1/1 replace")
    assert offline.show == before


def test_a_target_list_that_recording_finds_a_group_for_loses_it(offline: OfflineShow) -> None:
    """The tilt on 104 and 105 comes back inside group 1's tilt, per target."""
    run(offline, "cue 1/1 time fixture 104, 105 position 3")
    assert run(offline, "load cue 1/1")[0].endswith(
        "; 1 entry's own timing is not loaded, and replace keeps it on the same targets"
    )
    run(offline, "record cue 1/1 replace")
    assert [(e["attribute"], e["targets"], e.get("timing")) for e in entries(offline)] == [
        ("intensity", in_group("g-heads"), None),
        ("pan", in_group("g-heads"), None),
        ("tilt", in_group("g-heads"), None),
    ]


def test_merge_keeps_it_on_an_entry_recorded_again(offline: OfflineShow) -> None:
    run(offline, "cue 1/1 time group 1 intensity 1 to 5")
    run(offline, "sel group 1", "set intensity 50%", "record cue 1/1 merge")
    assert [(e["attribute"], e.get("timing")) for e in entries(offline)] == [
        ("pan", None),
        ("tilt", None),
        ("tilt", None),
        ("intensity", {"fade": 1, "fadeTo": 5, "delay": 0}),
    ]
    assert [t.fade for t in timings(offline.show, "intensity")] == [1, 2, 3, 4, 5]


def test_other_targets_take_none_and_a_restricted_entry_keeps_its_fan(
    offline: OfflineShow,
) -> None:
    """The heads but one recorded again: a targets entry, with no timing.
    Merging one head leaves the group's entry on the other four, its fan
    spread over them."""
    run(offline, "cue 1/1 time group 1 intensity 1 to 5")
    run(offline, "sel fixture 101", "set intensity 50%", "record cue 1/1 merge")
    assert [(e["attribute"], e["targets"], e.get("timing")) for e in entries(offline)][::4] == [
        ("intensity", targets(*HEADS[1:]), {"fade": 1, "fadeTo": 5, "delay": 0}),
        ("intensity", targets("fx-mh1"), None),
    ]
    fades = [t.fade for t in timings(offline.show, "intensity")]
    assert fades == pytest.approx([2, 1, 7 / 3, 11 / 3, 5])
    run(offline, "clear", "sel fixture 101 thru 104", "set intensity 50%")
    run(offline, "record cue 1/1 replace")
    assert [(e["targets"], e.get("timing")) for e in entries(offline)] == [
        (in_group("g-two"), None),
        (targets("fx-mh3", "fx-mh4"), None),
    ]


# ------------------------------------------------------------- show files


@pytest.fixture(scope="module")
def club_show(tmp_path_factory: pytest.TempPathFactory) -> Show:
    path = tmp_path_factory.mktemp("club") / "club.show"
    OfflineShow(new_show("Club Night"), path=path).run_script(CLUB_NIGHT)
    return load_show(path)[0]


def test_the_shows_of_today_load_and_play_the_same(club_show: Show) -> None:
    """The shipped shows load, and an entry's timing of today (fade, delay,
    curve, no fan) compiles as it did."""
    for show in (club_show, load_show(TUPPER_DEMO)[0], show_of(load_doc(APPENDIX_A))):
        assert not has_errors(issues_of(cast(Doc, show)))
    doc = rig()
    doc["cueLists"][0]["cues"][0]["entries"][0]["timing"] = {"fade": 3, "curve": "easeIn"}
    timed = compile_doc(doc)
    slots = held(timed, timed.cueLists["cl"].cues[0])
    assert {slots[head, "intensity"].rising for head in HEADS} == {
        SlotTiming(fade=3, delay=0, curve="easeIn")
    }


def test_the_club_show_takes_a_fan_and_saves_it(club_show: Show, tmp_path: Any) -> None:
    show = OfflineShow(copy.deepcopy(club_show), path=tmp_path / "club.show")
    assert run(show, "cue 9/1 time group 2 intensity 1 to 4 delay 0 to 1.5 edges")[0] == (
        "cue 9/1 fades intensity on group 2 over 1 s to 4 s, delay 0 s to 1.5 s, edges"
    )
    run(show, "save")
    loaded = load_show(tmp_path / "club.show")[0]
    assert loaded["cueLists"] == show.show["cueLists"]
    assert show.execute("cue 9/3 time group 1 intensity 1").text == (
        "error: cue 9/3 sets intensity on group 3 and group 2: name one of them"
    )


@pytest.mark.parametrize(
    ("timing", "issue"),
    [
        ({"fadeTo": 3}, ("error", "timing.fadeTo", "fadeTo needs a fade to fan from")),
        ({"fade": 1, "delayTo": 3},
         ("error", "timing.delayTo", "delayTo needs a delay to fan from")),
        ({"fade": 1, "fan": "center"},
         ("warning", "timing.fan", "fan has no effect without fadeTo or delayTo")),
    ],
)  # fmt: skip
def test_the_validator_checks_a_fans_ends(timing: Doc, issue: tuple[str, str, str]) -> None:
    doc = rig()
    doc["cueLists"][0]["cues"][0]["entries"][0]["timing"] = timing
    found = [
        (i.severity, i.path.removeprefix("cueLists[0].cues[0].entries[0]."), i.message)
        for i in issues_of(doc)
    ]
    assert found == [issue]


def test_the_generic_edit_refuses_a_fan_without_its_start(offline: OfflineShow) -> None:
    reply = offline.execute('cue 1/1 entries [{"targets": {"kind": "group", "groupId": "g-heads"},'
                            ' "attribute": "intensity", "value": {"kind": "literal", "value": 1},'
                            ' "timing": {"fadeTo": 2}}]')  # fmt: skip
    assert not reply.ok
    assert "fadeTo needs a fade to fan from" in reply.text


# ------------------------------------------------------------ a running show


def test_a_fan_goes_on_a_running_show() -> None:
    running = show_of(rig())
    with LiveShow(running, output=False) as live:
        eventually(lambda: status_of(live, 1) is not None)
        assert live.execute("go 1").ok
        eventually(lambda: status_of(live, 1).state == "active")
        reply = live.execute("cue 1/1 time group 1 intensity 1 to 5 center")
        assert (reply.ok, reply.text) == (
            True,
            "cue 1/1 fades intensity on group 1 over 1 s to 5 s, center",
        )
        assert [t.fade for t in timings(live.show, "intensity")] == [1, 3, 5, 3, 1]
        assert live.execute("cue 1/1 time group 1 intensity none").ok
        assert live.show == running
        assert live.execute("undo").ok
        assert entries(live)[0]["timing"] == {"fade": 1, "fadeTo": 5, "delay": 0, "fan": "center"}
        assert status_of(live, 1).state == "active"
