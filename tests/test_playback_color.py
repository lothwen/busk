"""The playback colour (GAP-17 of ``docs/dev/tui/engine-gaps.md``).

``PlaybackStatus.color`` is the colour of the cue a playback is at, for a
display to draw the playback in. The compiler reads it once per cue, from the
cue's tracked state (:func:`~busk.compiler.readout.cue_color`, kept as
``CompiledCue.color``), and the snapshot names the current cue's. Checked
here, on the output readout's rig (a spot with a colour wheel, an RGBW par, a
bar of four cells on one master dimmer):

* whose colour: the brightest element whose colour the cue holds, the first
  in the cue's order among equals and when none is lit; cells lit by their
  master; tracked colours; no colour; effects do not count;
* mixed as the output readout mixes it: the wheel's filter, an explicit
  white;
* the snapshot: idle, active, a GOTO, every step of a chase, a release; an
  edit that recolours a running cue republishes it;
* the event log's JSON keeps it, and a ``LiveShow`` has it. ``busk run
  --frontend`` reads it from the engine process in ``tests/test_frontend.py``.
"""

from __future__ import annotations

import json
import time

import pytest

from builders import (
    Doc,
    cue,
    cue_list,
    entry,
    literal,
    look,
    playback,
    rgb,
    show_of,
    target_ref,
    targets,
)
from busk.persistence.eventlog import snapshot_from_json, snapshot_json
from busk.runner import LiveShow, OfflineShow
from test_output_readout import of, readout_rig, rounded, run

type Color = tuple[float, float, float] | None

RED, GREEN, BLUE = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)


@pytest.fixture
def offline() -> OfflineShow:
    return OfflineShow(show_of(readout_rig()))


def colors(show_: OfflineShow | LiveShow) -> dict[int, Color]:
    """Each playback's colour in ``show_``'s snapshot, by number."""
    snapshot = show_.snapshot
    assert snapshot is not None
    return {status.number: status.color for status in snapshot.playbacks}


def look_show(*entries: Doc) -> OfflineShow:
    """The readout rig with playback 1 on one cue of ``entries``, in their order."""
    doc = readout_rig()
    look(doc, "pb-1", 1, *entries)
    return OfflineShow(show_of(doc))


def lit(level: float, *fixture_ids: str) -> Doc:
    return entry(targets(*fixture_ids), "intensity", literal(level))


def colored(fixture_id: str, r: float, g: float, b: float, element: int = 0) -> Doc:
    spec = {"kind": "targets", "refs": [target_ref(fixture_id, element)]}
    return entry(spec, "color", literal(rgb(r, g, b)))


def wheel(fixture_id: str, slot_id: str) -> Doc:
    return entry(targets(fixture_id), "colorWheel", literal({"slot": slot_id}))


# ------------------------------------------------------------- the snapshot


def test_a_playback_has_its_cues_colour_while_it_is_at_the_cue(offline: OfflineShow) -> None:
    run(offline, "sel fixture 201", "set intensity 80%", "set color 1 0 0")
    run(offline, 'record slot 1 "Red"', "clear")
    assert colors(offline) == {1: None}  # idle: at no cue
    run(offline, "go 1")
    assert colors(offline) == {1: RED}
    run(offline, "fader 1 30%", "gm 50%")  # levels change the output, not the cue's colour
    assert colors(offline) == {1: RED}
    run(offline, "release 1")
    offline.tick(offline.time + 2.0)  # past its release time
    assert offline.snapshot.playbacks[0].state == "idle"
    assert colors(offline) == {1: None}


def test_a_cue_without_a_colour_has_none(offline: OfflineShow) -> None:
    run(offline, "sel fixture 201", "set intensity 80%", 'record slot 1 "Dim"', "clear", "go 1")
    assert colors(offline) == {1: None}


def test_a_programmer_on_top_does_not_change_it(offline: OfflineShow) -> None:
    run(offline, "sel fixture 201", "set intensity 80%", "set color 1 0 0")
    run(offline, "record slot 1", "clear", "go 1", "sel fixture 201", "set color 0 0 1")
    assert of(offline.output, 201).color == BLUE
    assert colors(offline) == {1: RED}


# ------------------------------------------------------------- whose colour


def test_the_brightest_element_whose_colour_the_cue_holds_gives_it(
    offline: OfflineShow,
) -> None:
    run(offline, "sel fixture 101", "set intensity 20%", "set colorWheel red")
    run(offline, "sel fixture 201", "set intensity 80%", "set color 0 0 1")
    run(offline, "sel fixture 301", "set intensity 100%")  # the brightest holds no colour
    run(offline, "record slot 1", "clear", "go 1")
    assert colors(offline) == {1: BLUE}


def test_an_element_the_cue_leaves_dark_counts_only_when_none_is_lit() -> None:
    dark_first = look_show(lit(0.0, "f-spot"), wheel("f-spot", "red"), colored("f-par", 0, 0, 1))
    dark_first.execute("go 1")
    assert colors(dark_first) == {1: RED}  # nothing lit: the first
    moved_in_black = look_show(
        lit(0.0, "f-spot"), wheel("f-spot", "red"), lit(0.5, "f-par"), colored("f-par", 0, 0, 1)
    )
    moved_in_black.execute("go 1")
    assert colors(moved_in_black) == {1: BLUE}


@pytest.mark.parametrize(
    ("order", "expected"), [(("f-par", "f-spot"), BLUE), (("f-spot", "f-par"), RED)]
)
def test_among_equals_the_cues_order_decides(order: tuple[str, str], expected: Color) -> None:
    # The colour entries come in the same order; the cue's targets follow its first entry.
    show_ = look_show(lit(1.0, *order), wheel("f-spot", "red"), colored("f-par", 0, 0, 1))
    show_.execute("go 1")
    assert colors(show_) == {1: expected}


@pytest.mark.parametrize(("master", "expected"), [(1.0, GREEN), (0.0, RED)])
def test_a_cell_is_lit_by_its_master_dimmer(master: float, expected: Color) -> None:
    show_ = look_show(
        lit(0.5, "f-par"),
        colored("f-par", 1, 0, 0),
        lit(master, "f-bar"),  # element 0: the bar's dimmer, and its first cell
        colored("f-bar", 0, 1, 0, element=2),
    )
    show_.execute("go 1")
    assert colors(show_) == {1: expected}


def test_a_tracking_cue_counts_what_it_tracks_and_its_own_targets_first() -> None:
    doc = readout_rig()
    song = cue_list(
        "cl-song",
        1,
        cue("c-1", lit(0.5, "f-par"), colored("f-par", 1, 0, 0), number="1"),
        cue("c-2", lit(0.5, "f-spot"), wheel("f-spot", "cyan"), number="2"),
        cue("c-3", lit(1.0, "f-par"), number="3"),
    )
    song["tracking"] = True
    doc["cueLists"].append(song)
    doc["playbacks"].append(playback("pb-1", 1, "cl-song"))
    show_ = OfflineShow(show_of(doc))
    seen = []
    for _ in range(3):
        show_.execute("go 1")
        seen.append(colors(show_)[1])
    # Cue 2 ties the tracked par at 50 %: its own spot first. Cue 3 lights the
    # tracked red brightest.
    assert seen == [RED, (0.0, 1.0, 1.0), RED]
    show_.execute("goto 1 2")
    assert colors(show_) == {1: (0.0, 1.0, 1.0)}
    song["tracking"] = False
    plain = OfflineShow(show_of(doc))
    plain.execute("goto 1 3")
    assert colors(plain) == {1: None}  # its own values only: no colour


def test_effects_do_not_count(offline: OfflineShow) -> None:
    run(offline, "sel fixture 201", "set intensity 100%", 'effect add "Rainbow"')
    run(offline, "record slot 1", "clear", "go 1")
    offline.tick(0.5)
    assert colors(offline) == {1: None}
    run(offline, "sel fixture 101", "set intensity 100%", "set colorWheel cyan")
    run(offline, 'effect add "Rainbow"', "record slot 2", "clear", "go 2")
    assert colors(offline)[2] == (0.0, 1.0, 1.0)


# --------------------------------------------------------------- the mixing


@pytest.mark.parametrize(
    ("number", "line", "expected"),
    [
        (101, "set colorWheel red", RED),
        (101, "set colorWheel cyan", (0.0, 1.0, 1.0)),
        (101, "set colorWheel uv", (1.0, 1.0, 1.0)),  # no colour in the profile: no filter
        (201, "set color 0.2 0.4 0.6", (0.2, 0.4, 0.6)),  # white derived: the same light
        (201, "set color 1 0 0 w 0.5", (1.0, 0.5, 0.5)),
    ],
)
def test_the_colour_is_mixed_as_the_output_readout_mixes_it(
    offline: OfflineShow, number: int, line: str, expected: Color
) -> None:
    run(offline, f"sel fixture {number}", "set intensity 100%", line, "record slot 1", "clear")
    run(offline, "go 1")
    color = colors(offline)[1]
    assert rounded(color) == expected
    assert rounded(color) == rounded(of(offline.output, number).color)  # it alone drives it


# ------------------------------------------------------------- what follows


def test_a_chase_has_the_colour_of_each_step() -> None:
    doc = readout_rig()
    steps = [
        cue(f"c-{k}", lit(1.0, "f-par"), colored("f-par", *color), number=str(k))
        for k, color in enumerate((RED, GREEN, BLUE), start=1)
    ]
    chase = cue_list("cl-chase", 1, *steps)
    chase.update(
        mode="chase",
        chase={"rate": {"kind": "hz", "value": 1.0}, "direction": "forward", "crossfade": 0.0},
    )
    doc["cueLists"].append(chase)
    doc["playbacks"].append(playback("pb-1", 1, "cl-chase"))
    show_ = OfflineShow(show_of(doc))
    show_.execute("go 1")
    seen = {}
    for _ in range(7):
        show_.tick(show_.time + 0.5)
        status = show_.snapshot.playbacks[0]
        seen[status.cue] = status.color
    assert seen == {"1": RED, "2": GREEN, "3": BLUE}


def test_an_edit_recolours_a_running_cue(offline: OfflineShow) -> None:
    run(offline, "sel fixture 201", "set intensity 100%", "set color 0 0 1")
    run(offline, 'record preset color 1 "Wash"', "clear")
    run(offline, "sel fixture 201", "set intensity 100%", "preset color 1")
    run(offline, "record slot 1", "clear", "go 1")
    before = offline.snapshot
    assert colors(offline) == {1: BLUE}
    run(offline, "sel fixture 201", "set color 1 0 0", "record preset color 1 replace", "clear")
    assert offline.snapshot.seq > before.seq  # republished with no playback command
    assert colors(offline) == {1: RED}


def test_the_event_logs_json_keeps_it(offline: OfflineShow) -> None:
    run(offline, "sel fixture 201", "set intensity 80%", "set color 1 0 0")
    run(offline, "record slot 1", "clear", "go 1")
    snapshot = offline.snapshot
    data = json.loads(json.dumps(snapshot_json(snapshot)))
    assert data["playbacks"][0]["color"] == [1.0, 0.0, 0.0]
    assert snapshot_from_json(data) == snapshot
    del data["playbacks"][0]["color"]  # a record from before GAP-17
    assert snapshot_from_json(data).playbacks[0].color is None


def test_a_live_show_has_it() -> None:
    doc = readout_rig()
    look(doc, "pb-1", 1, lit(1.0, "f-par"), colored("f-par", 0, 0, 1))
    with LiveShow(show_of(doc), output=False) as live:
        assert live.execute("go 1").ok
        deadline = time.monotonic() + 2.0
        while colors(live)[1] is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert colors(live) == {1: BLUE}
