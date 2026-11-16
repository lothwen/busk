"""A cue list's tracked states (GAP-46) and block cues (GAP-47) of
``docs/dev/tui/engine-gaps.md``.

``OfflineShow.tracking(L)`` and ``LiveShow.tracking(L)`` give each cue of
list ``L`` with what it puts on stage when the list is played by GO from its
first cue, read from the compiled show: each value with the cue that stores
it, what the cue releases, and its effects. ``list cue L/C`` prints it.
``cue L/C block on|off`` makes a cue a whole state, or makes it track again.

The club show's Song (list 9, tracking): Intro sets the washes' intensity
and preset Blue; Verse the heads (intensity, colour, preset Audience); Pre
the bar (intensity, preset Amber) and the washes' intensity; Chorus every
fixture at full white, with the ``rainbow`` effect on the bar; Outro the
heads' intensity, and releases their pan and tilt.

Appendix A: two heads (101, 102: group 1) and a par (201). Song (list 1,
tracking): Verse sets the heads' intensity, colour and a pan spread; Chorus
their intensity and colour. Slow Pulse (20/1): one effect on group 1.
"""

from __future__ import annotations

import copy
import math
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from builders import APPENDIX_A, ROOT, load_doc, show_of
from busk import LiveShow, OfflineShow, TrackedCue, load_show, new_show
from busk.compiler.cues import CompiledCue, clamp_lanes
from busk.compiler.lanes import encode_value
from busk.compiler.slots import SlotTable
from busk.model.show import Show

CLUB_NIGHT = ROOT / "examples" / "club-night.busk"
TUPPER_DEMO = ROOT / "examples" / "tupperdmx" / "tupper-demo.show"


@pytest.fixture(scope="module")
def club_show(tmp_path_factory: pytest.TempPathFactory) -> Show:
    path = tmp_path_factory.mktemp("club") / "club.show"
    OfflineShow(new_show("Club Night"), path=path).run_script(CLUB_NIGHT)
    return load_show(path)[0]


@pytest.fixture
def club(club_show: Show) -> OfflineShow:
    return OfflineShow(copy.deepcopy(club_show))


@pytest.fixture
def offline() -> OfflineShow:
    return OfflineShow(show_of(load_doc(APPENDIX_A)))


def run(show: OfflineShow | LiveShow, *lines: str) -> list[str]:
    texts = []
    for line in lines:
        reply = show.execute(line)
        assert reply.ok, f"{line}: {reply.text}"
        texts.append(reply.text)
    return texts


def tracked(show: OfflineShow | LiveShow, cue_list: int) -> tuple[TrackedCue, ...]:
    cues = show.tracking(cue_list)
    assert cues is not None
    return cues


def sources(cue: TrackedCue, number: int) -> dict[str, tuple[Any, str | None]]:
    """Fixture ``number``'s first element: attribute → (the preset's name or
    the value, the cue it tracks from)."""
    return {
        v.attribute: (v.value if v.preset is None else v.preset[2], v.trackedFrom)
        for v in cue.values
        if (v.number, v.element) == (number, 1)
    }


# ------------------------------------------------------------ the read (GAP-46)


def test_song_tracks_each_value_from_the_cue_that_stores_it(club: OfflineShow) -> None:
    intro, verse, pre, chorus, outro = tracked(club, 9)
    assert [(c.number, c.name, c.block) for c in (intro, verse, pre, chorus, outro)] == [
        ("1", "Intro", False), ("2", "Verse", False), ("3", "Pre", False),
        ("4", "Chorus", False), ("5", "Outro", False),
    ]  # fmt: skip
    assert sources(intro, 201) == {"intensity": (0.6, None), "color": ("Blue", None)}
    assert sources(verse, 201) == {"intensity": (0.6, "1"), "color": ("Blue", "1")}
    assert sources(verse, 101) == {
        "intensity": (0.7, None),
        "pan": ("Audience", None),
        "tilt": ("Audience", None),
        "color": ({"r": 1.0, "g": 0.75, "b": 0.45}, None),
    }
    assert sources(pre, 201) == {"intensity": (0.3, None), "color": ("Blue", "1")}
    assert sources(pre, 101)["pan"] == ("Audience", "2")
    assert sources(chorus, 301) == {
        "intensity": (1.0, "3"),
        "color": ({"r": 1, "g": 1, "b": 1}, None),
    }
    assert sources(outro, 101) == {
        "intensity": (0.2, None),
        "color": ({"r": 1, "g": 1, "b": 1}, "4"),
    }
    assert [(v.number, v.element) for v in intro.values] == [
        (n, 1) for n in (201, 201, 202, 202, 203, 203, 204, 204)
    ]


def test_a_preset_value_is_the_one_it_gives_that_element(club: OfflineShow) -> None:
    verse = tracked(club, 9)[1]
    pans = [(v.number, v.value, v.preset) for v in verse.values if v.attribute == "pan"]
    assert pans == [
        (101, -30.0, ("position", 1, "Audience")),
        (102, 30.0, ("position", 1, "Audience")),
    ]


def test_a_release_takes_values_away(club: OfflineShow) -> None:
    *_, chorus, outro = tracked(club, 9)
    assert chorus.released == ()
    assert outro.released == ((101, 1, "pan"), (101, 1, "tilt"), (102, 1, "pan"), (102, 1, "tilt"))
    assert "pan" not in sources(outro, 101)


def test_an_effect_tracks_on_from_the_cue_that_holds_it(club: OfflineShow) -> None:
    *_, pre, chorus, outro = tracked(club, 9)
    assert pre.effects == ()
    assert [(e.id, e.trackedFrom) for e in chorus.effects] == [("rainbow", None)]
    assert [(e.id, e.trackedFrom) for e in outro.effects] == [("rainbow", "4")]


def test_a_block_cue_tracks_nothing_and_the_cues_after_it_track_from_it(
    club: OfflineShow,
) -> None:
    run(club, "cue 9/3 block on")
    _, _, pre, chorus, outro = tracked(club, 9)
    assert pre.block
    assert sources(pre, 201) == {"intensity": (0.3, None)}  # Intro's Blue does not track in
    assert sources(pre, 101) == {}
    assert "pan" not in sources(chorus, 101)  # Verse's position stops at the block
    assert sources(chorus, 301)["intensity"] == (1.0, "3")
    assert outro.released == ()  # nothing held the heads' pan and tilt
    run(club, "undo")
    assert sources(tracked(club, 9)[2], 101)["pan"] == ("Audience", "2")


def test_a_list_without_tracking_has_only_its_own(club: OfflineShow) -> None:
    run(club, "cuelist 9 tracking false")
    cues = tracked(club, 9)
    assert all(v.trackedFrom is None for cue in cues for v in cue.values)
    assert all(cue.released == () for cue in cues)
    assert sources(cues[1], 201) == {}
    assert [(e.id, e.trackedFrom) for e in cues[4].effects] == []
    assert [(e.id, e.trackedFrom) for e in cues[3].effects] == [("rainbow", None)]


def test_a_list_with_no_cues_and_one_that_is_not_there(club: OfflineShow) -> None:
    run(club, "cuelist add 30")
    assert club.tracking(30) == ()
    assert club.tracking(99) is None


def test_a_chase_tracks_in_list_order_whatever_its_direction(club: OfflineShow) -> None:
    """The compiler works out a chase's states once, in list order, as a
    sequence's, and the engine plays them in the chase's order."""
    run(club, "cuelist 10 tracking true")
    steps = tracked(club, 10)
    run(club, "cuelist 10 chase.direction reverse")
    assert tracked(club, 10) == steps
    first, second = steps[0], steps[1]
    own = {(v.number, v.element, v.attribute) for v in first.values}
    assert own
    assert all(v.trackedFrom is None for v in first.values)
    carried = {(v.number, v.element, v.attribute) for v in second.values if v.trackedFrom == "1"}
    assert carried == own - {
        (v.number, v.element, v.attribute) for v in second.values if not v.trackedFrom
    }


def test_an_own_value_and_an_own_effect_win_over_the_cues_releases(offline: OfflineShow) -> None:
    run(
        offline,
        "cue 1/2 release group 1",  # every attribute of the heads
    )
    chorus = tracked(offline, 1)[1]
    assert sources(chorus, 101) == {
        "intensity": (1.0, None),
        "color": ({"r": 1.0, "g": 1.0, "b": 1.0}, None),
    }
    assert chorus.released == ((101, 1, "pan"), (102, 1, "pan"))


def test_a_release_trims_a_tracked_effect_and_one_left_with_nothing_goes(
    offline: OfflineShow,
) -> None:
    run(
        offline,
        "sel group 1",
        'effect add "Circle" id spin',  # pan and tilt
        "record cue 1/1 merge",
        "clear",
        "cue 1/2 release group 1 only tilt",
    )
    chorus = tracked(offline, 1)[1]
    assert [(e.id, e.trackedFrom) for e in chorus.effects] == [("spin", "1")]
    assert chorus.released == ((101, 1, "tilt"), (102, 1, "tilt"))  # held by the effect only
    run(offline, "cue 1/2 release group 1 only pan")
    chorus = tracked(offline, 1)[1]
    assert chorus.effects == ()
    assert chorus.released == ((101, 1, "pan"), (101, 1, "tilt"), (102, 1, "pan"), (102, 1, "tilt"))


def test_an_instance_of_the_cues_own_takes_a_tracked_ones_place_untrimmed(
    offline: OfflineShow,
) -> None:
    """The compiler trims a tracked instance by the cue's releases, unless the
    cue holds one with its id; the tracked values go all the same."""
    run(
        offline,
        "sel group 1",
        'effect add "Circle" id spin',
        "record cue 1/1 merge",
        'effect add "Circle" id spin size 5',
        "record cue 1/2 merge",
        "clear",
        "cue 1/2 release group 1 only pan tilt",
    )
    chorus = tracked(offline, 1)[1]
    assert [(e.id, e.trackedFrom) for e in chorus.effects] == [("spin", None)]
    assert chorus.released == ((101, 1, "pan"), (102, 1, "pan"))  # Verse's pan spread


def test_the_read_follows_edits_and_undo(offline: OfflineShow) -> None:
    before = tracked(offline, 1)
    run(offline, "sel group 1", "set color preset color 2", "record cue 1/1 merge")
    verse, chorus = tracked(offline, 1)
    assert sources(verse, 101)["color"] == ("Red", None)
    assert sources(chorus, 101)["color"] == ({"r": 1.0, "g": 1.0, "b": 1.0}, None)
    run(offline, "undo")
    assert tracked(offline, 1) == before


# --------------------------------------------- the read against the compiled show


def compiled_values(cue: CompiledCue, table: SlotTable) -> dict[int, list[float]]:
    """The compiled state's lanes, by slot."""
    lanes: dict[int, float] = {}
    for position, value in zip(cue.htpPos.tolist(), cue.htpValues.tolist(), strict=True):
        lanes[int(table.intensityLanes[position])] = value
    for each, values in ((cue.ltpLanes, cue.ltpValues), (cue.snapLanes, cue.snapValues)):
        lanes.update(zip(each.tolist(), values.tolist(), strict=True))
    slots: dict[int, list[float]] = {}
    for lane, value in sorted(lanes.items()):
        slots.setdefault(int(table.laneSlot[lane]), []).append(value)
    return slots


def same(a: list[float], b: tuple[float, ...]) -> bool:
    return len(a) == len(b) and all(
        x == y or (math.isnan(x) and math.isnan(y)) for x, y in zip(a, b, strict=True)
    )


@pytest.mark.parametrize("name", ["club", "tupper"])
@pytest.mark.parametrize("tracking", [False, True])
def test_every_cue_reads_what_the_compiler_made(club_show: Show, name: str, tracking: bool) -> None:
    """Every cue of both shipped shows, as they are and with every list
    tracking: the read's slots and values are the compiled state's, its
    effects the compiled cue's, and in a tracking list each released value
    is one the cue before it held and this one does not."""
    doc = copy.deepcopy(club_show if name == "club" else load_show(TUPPER_DEMO)[0])
    if tracking:
        for cue_list in doc["cueLists"]:
            cue_list["tracking"] = True
    show = OfflineShow(doc)
    state = show._session.state
    table = state.compiled.slots
    ids = {fixture["number"]: fixture["id"] for fixture in state.show["fixtures"]}
    checked = 0
    for cue_list in state.show["cueLists"]:
        compiled = state.compiled.cueLists[cue_list["id"]].cues
        previous: set[int] = set()
        for cue, made in zip(tracked(show, cue_list["number"]), compiled, strict=True):
            lanes = compiled_values(made, table)
            read: dict[int, tuple[float, ...]] = {}
            for value in cue.values:
                target = {"fixtureId": ids[value.number], "element": value.element - 1}
                slot = table.find(cast(Any, target), value.attribute)
                assert slot is not None
                read[slot.index] = clamp_lanes(slot, encode_value(slot, value.value))
            assert read.keys() == lanes.keys(), (cue_list["number"], cue.number)
            assert all(same(lanes[index], read[index]) for index in read)
            assert [(e.id, e.trackedFrom or cue.number) for e in cue.effects] == [
                (e.key, e.cue) for e in made.effects
            ]
            gone = {
                cast(Any, table.find(cast(Any, {"fixtureId": ids[n], "element": e - 1}), a)).index
                for n, e, a in cue.released
            }
            if cue_list["tracking"] and not cue.block and not made.effects:
                assert gone == previous - lanes.keys()
            previous = set(lanes)
            checked += 1
    assert checked == (29 if name == "club" else 8)


# ------------------------------------------------------------- list cue L/C


def test_list_cue_prints_a_line_per_fixture_with_where_each_value_comes_from(
    club: OfflineShow,
) -> None:
    assert run(club, "list cue 9/2")[0].splitlines() == [
        "cue 9/2 'Verse'",
        "  101  intensity 70%  pan 'Audience'  tilt 'Audience'  color 1 0.75 0.45",
        "  102  intensity 70%  pan 'Audience'  tilt 'Audience'  color 1 0.75 0.45",
        "  201  intensity 60% ← 9/1  color 'Blue' ← 9/1",
        "  202  intensity 60% ← 9/1  color 'Blue' ← 9/1",
        "  203  intensity 60% ← 9/1  color 'Blue' ← 9/1",
        "  204  intensity 60% ← 9/1  color 'Blue' ← 9/1",
    ]
    assert run(club, "list cue 9/5")[0].splitlines()[-3:] == [
        "  301  intensity 100% ← 9/3  color 1 1 1 ← 9/4",
        "  releases 101 pan tilt, 102 pan tilt",
        "  effect rainbow 'Rainbow' on group 3, 0.25 Hz, size 1 ← 9/4",
    ]


def test_list_cue_prints_each_element_where_a_fixtures_elements_differ(
    club: OfflineShow,
) -> None:
    run(club, "sel fixture 301", "set intensity spread 0 100%", "record cue 9/6", "clear")
    lines = run(club, "list cue 9/6")[0].splitlines()
    assert lines[7:9] == [
        "   301.1  intensity 0%  color 1 1 1 ← 9/4",
        "   301.2  intensity 9.09091%  color 1 1 1 ← 9/4",
    ]
    assert lines[-2:] == [
        "  301.12  intensity 100% ← 9/3  color 1 1 1 ← 9/4",
        "  effect rainbow 'Rainbow' on group 3, 0.25 Hz, size 1 ← 9/4",
    ]
    assert lines[1] == "     101  intensity 20% ← 9/5  color 1 1 1 ← 9/4"
    run(
        club, "cuelist add 30", "sel fixture 301.1 thru 301.2", "set color 1 0 0", "record cue 30/1"
    )
    assert run(club, "list cue 30/1")[0].splitlines()[1:] == [  # two cells of twelve
        "  301.1  color 1 0 0",
        "  301.2  color 1 0 0",
    ]


def test_list_cue_says_a_block_cue_a_list_without_tracking_and_an_empty_cue(
    club: OfflineShow, offline: OfflineShow
) -> None:
    run(club, "cue 9/3 block on")
    assert run(club, "list cue 9/3")[0].splitlines()[0] == "cue 9/3 'Pre', a block cue"
    assert run(club, "list cue 12/1")[0].splitlines() == [
        "cue 12/1 'Pulse' (cue list 12 does not track)",
        "  effect fx2 'Pulse' on group 2, bpm 'Speed 1' ×1, size 0.8",
    ]
    run(offline, "cue 20/1 effect ei-1 remove")
    assert run(offline, "list cue 20/1")[0].splitlines() == [
        "cue 20/1 'Pulse' (cue list 20 does not track)",
        "  nothing",
    ]


def test_list_cue_refusals(club: OfflineShow) -> None:
    for line, error in [
        ("list cue 9", "error: expected a cue as L/C, e.g. 10/1"),
        ("list cue 9/9", "error: no cue 9/9"),
        ("list cue 99/1", "error: no cue list 99"),
        ("list cue 9/1 now", "error: unexpected 'now'"),
    ]:
        reply = club.execute(line)
        assert (reply.ok, reply.text) == (False, error)


def test_list_cues_marks_a_block_cue(club: OfflineShow) -> None:
    run(club, "cue 9/3 block on")
    assert run(club, "list cues 9")[0].splitlines()[2] == (
        "    3  Pre                  time 1/3  wait 8  block"
    )


# --------------------------------------------------------- block cues (GAP-47)


def test_block_on_and_off_are_one_undo_step_each(club: OfflineShow) -> None:
    def block() -> object:
        song = next(cl for cl in club.show["cueLists"] if cl["number"] == 9)
        return song["cues"][2].get("block")

    assert run(club, "cue 9/3 block on") == ["cue 9/3 tracks nothing from the cues before it"]
    assert block() is True
    assert run(club, "cue 9/3 block off") == ["cue 9/3 tracks again"]
    assert block() is None  # off takes it out, as a cue recorded without one
    assert run(club, "undo") == ["undid: cue 9/3 tracks again"]
    assert block() is True
    assert run(club, "undo") == ["undid: cue 9/3 tracks nothing from the cues before it"]
    assert block() is None


def test_a_block_line_that_changes_nothing_is_refused(club: OfflineShow) -> None:
    reply = club.execute("cue 9/3 block off")
    assert (reply.ok, reply.text) == (False, "error: cue 9/3 is not a block cue")
    run(club, "cue 9/3 block on")
    reply = club.execute("cue 9/3 block on")
    assert (reply.ok, reply.text) == (False, "error: cue 9/3 is a block cue already")
    run(club, "undo")
    assert club.execute("undo").text == "error: nothing to undo"  # the refusals spent no step


def test_block_in_a_list_without_tracking_says_it_changes_nothing(club: OfflineShow) -> None:
    on = run(club, "cue 18/2 block on")[0].splitlines()
    assert on[0] == (
        "cue 18/2 is a block cue; cue list 18 does not track, so that changes nothing until "
        "tracking is on"
    )
    assert on[1:] == ["warning cueLists[17].cues[1].block: block has no effect without tracking"]
    assert run(club, "cue 18/2 block off") == [
        "cue 18/2 is not a block cue; cue list 18 does not track, so that changes nothing until "
        "tracking is on"
    ]


def test_the_generic_edit_still_sets_block(club: OfflineShow) -> None:
    assert run(club, "cue 9/3 block true") == ["set cueLists[8].cues[2].block to true"]
    assert tracked(club, 9)[2].block
    assert run(club, "cue 9/3 block off") == ["cue 9/3 tracks again"]


def test_block_on_changes_the_compiled_states(club: OfflineShow) -> None:
    song = next(cl for cl in club.show["cueLists"] if cl["number"] == 9)
    compiled = club._session.state.compiled.cueLists[song["id"]]
    before = len(compiled.cues[3].targets)
    run(club, "cue 9/3 block on")
    compiled = club._session.state.compiled.cueLists[song["id"]]
    assert len(compiled.cues[2].targets) < before  # Pre lost the heads it tracked


# ------------------------------------------------------------ a running show


def eventually(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_a_running_show_reads_its_lists_and_takes_block() -> None:
    expected = OfflineShow(show_of(load_doc(APPENDIX_A))).tracking(1)
    with LiveShow(show_of(load_doc(APPENDIX_A)), output=False) as live:
        eventually(lambda: live.output is not None)
        run(live, "go 1")
        assert live.tracking(1) == expected
        assert live.tracking(7) is None
        assert run(live, "cue 1/2 block on") == ["cue 1/2 tracks nothing from the cues before it"]
        chorus = tracked(live, 1)[1]
        assert chorus.block
        assert all(v.trackedFrom is None for v in chorus.values)
        assert run(live, "list cue 1/2")[0].splitlines()[:2] == [
            "cue 1/2 'Chorus', a block cue",
            "  101  intensity 100%  color 1 1 1",
        ]


@pytest.mark.parametrize("backend", ["processes", "threads"])
def test_busk_run_prints_it(club_show: Show, tmp_path: Path, backend: str) -> None:
    """Under ``busk run`` the console process compiles every edit, so it has
    the compiled show to read, with its engine in another process too."""
    path = tmp_path / "club.show"
    doc = copy.deepcopy(club_show)
    for route in doc["output"]["routes"]:
        route["enabled"] = False  # sends nothing
    assert OfflineShow(doc, path=path).save().ok
    lines = ["list cue 9/2", "cue 9/2 block on", "list cue 9/2", "list cues 9", "quit"]
    result = subprocess.run(
        [
            sys.executable, "-m", "busk", "run", str(path),
            *(["--threads"] if backend == "threads" else []),
            "--state-dir", str(tmp_path / "state"),
        ],
        input="".join(f"{line}\n" for line in lines),
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "XDG_STATE_HOME": str(tmp_path / "xdg")},
        check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    out = result.stdout.splitlines()
    assert "  201  intensity 60% ← 9/1  color 'Blue' ← 9/1" in out
    assert "cue 9/2 tracks nothing from the cues before it" in out
    assert "cue 9/2 'Verse', a block cue" in out
    assert "    2  Verse                time 2, position 4  go  block" in out
