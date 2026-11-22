"""``rig check`` and ``rig import``: a plot becomes the rig (MVR plan Phase 2,
step 5), and keeps it up to date (Phase 3, step 7).

``rig import "<path>"`` reads an MVR plot and adds, in one undo step, the
profiles of its GDTF files, the universes its addresses need, its fixtures
(number, name, patch, inverts, location and ``mvrUuid``), a group for each
hanging position, and the show's ``stage``: the plot's file, hash and frame.
``rig check`` says what it would do and changes nothing. The club plot below
hangs three spots on LX1 and two on LX2, drawn with the audience at −Y.

Imported again, the plot updates the fixtures it has (matched by
``mvrUuid``), adds its new ones and removes those it lost, ``cascade``
taking them from what uses them; it never touches a fixture added by hand,
nor numbers, groups or what else busk owns (MVR plan Q2, Q3).
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pytest

from builders import channel, mode, profile
from busk import CounterIds, ImportFailed, LiveShow, OfflineShow, RigCheck, load_show, new_show
from busk.console.parser import Context, ImportRig, ParseError, parse
from busk.importers.gdtf import import_gdtf
from busk.model.show import Show
from busk.session.ids import RandomIds
from busk.session.library import ProfileLibrary
from gdtf_builder import TYPE_ID, description
from gdtf_builder import channel as gdtf_channel
from gdtf_builder import function as gdtf_function
from gdtf_builder import mode as gdtf_mode
from mvr_builder import (
    SPOT,
    fixture,
    gdtf,
    layer,
    matrix,
    model,
    plot,
    position,
    scene,
    scenery,
    spot,
)

PROFILE_ID = f"gdtf-{TYPE_ID.lower()}"

LX1: dict[str, dict[str, Any]] = {  # on a truss at Y −2000, Z 6000
    "f101": {"name": "Spot 1", "numeric": 101, "addresses": [("0", "1.1")],
             "at": matrix(o=(2000, 0, 0)), "position": "P1"},
    "f102": {"name": "Spot 2", "numeric": 102, "addresses": [("0", "1.4")],
             "position": "P1", "invert_pan": "true"},
    "f103": {"name": "Spot 3", "numeric": 103, "addresses": [("0", "1.7")],
             "at": matrix(o=(-2000, 0, 0)), "position": "P1"},
}  # fmt: skip
LX2: dict[str, dict[str, Any]] = {  # on a truss at Z 7000
    "f201": {"name": "Wash 1", "fixture_id": "201", "numeric": 0, "gdtf_mode": "1ch",
             "addresses": [("0", "2.1")], "at": matrix(o=(-1000, 0, 0)), "position": "P2"},
    "f202": {"name": "", "fixture_id": "202", "gdtf_mode": "1ch", "addresses": [("0", "514")],
             "at": matrix(o=(1000, 0, 0)), "position": "P2"},
}  # fmt: skip

type Changes = dict[str, dict[str, Any] | None]
"""What a later plot changes in a club fixture, by uuid; ``None`` removes it."""


def club_scene(
    *extra: ET.Element, changes: Changes | None = None, aux: tuple[ET.Element, ...] = ()
) -> bytes:
    """The club plot, ``changes`` made, with ``extra`` objects in its layer
    and ``aux`` in its ``AUXData``."""

    def hung(fixtures: dict[str, dict[str, Any]]) -> list[ET.Element]:
        found = []
        for uuid, fields in fixtures.items():
            change = (changes or {}).get(uuid, {})
            if change is not None:
                found.append(fixture(uuid, **{**fields, **change}))
        return found

    lx1 = scenery("Truss", "t1", "LX1", at=matrix(o=(0, -2000, 6000)), children=hung(LX1))
    lx2 = scenery("Truss", "t2", "LX2", at=matrix(o=(0, 0, 7000)), children=hung(LX2))
    return scene(
        layer("L1", "Lights", lx1, lx2, *extra),
        aux=[position("P1", "LX1"), position("P2", "LX2"), position("P3", "Floor"), *aux],
    )


def club(
    tmp_path: Path,
    data: bytes | None = None,
    files: dict[str, bytes] | None = None,
    name: str = "club.mvr",
) -> Path:
    folder = tmp_path / "plots"
    folder.mkdir(exist_ok=True)
    return plot(folder / name, data if data is not None else club_scene(), files)


def offline(**kwargs: Any) -> OfflineShow:
    return OfflineShow(new_show("Club", ids=CounterIds()), ids=CounterIds(100), **kwargs)


def run(show: OfflineShow | LiveShow, line: str) -> str:
    reply = show.execute(line)
    assert reply.ok, reply.text
    return reply.text


def by_number(show: Show) -> dict[int, dict[str, Any]]:
    return {f["number"]: dict(f) for f in show["fixtures"]}


CHECK = """\
the plot has 5 fixtures, 1 profile and 2 universes
  add 5: 101–103, 201, 202
  profiles to add: "Acme Spot"
  universes to add: 1, 2
  groups to add: "LX1", "LX2"
fixtures span x -2.0…2.0, y 0.0…2.0, z 6.0…7.0 m"""

IMPORTED = """\
imported 5 fixtures, 1 profile, 2 universes and 2 groups from club.mvr
fixtures span x -2.0…2.0, y 0.0…2.0, z 6.0…7.0 m"""


# ------------------------------------------------------------------ the lines


def test_rig_check_says_what_the_import_would_do_and_changes_nothing(tmp_path: Path) -> None:
    path = club(tmp_path)
    show = offline()
    before = copy.deepcopy(show.show)
    assert run(show, f'rig check "{path}"') == CHECK
    assert show.show == before
    assert run(show, f'rig import "{path}"') == IMPORTED
    alone = offline()
    run(alone, f'rig import "{path}"')
    assert show.show["fixtures"] == alone.show["fixtures"]  # check took none of the ids


def test_rig_import_builds_the_rig_in_one_undo_step(tmp_path: Path) -> None:
    path = club(tmp_path)
    show = offline()
    before = copy.deepcopy(show.show)
    assert run(show, f'rig import "{path}"') == IMPORTED
    built = show.show
    (acme,) = built["profiles"]
    assert (acme["id"], acme["name"]) == (PROFILE_ID, "Acme Spot")
    modes = {m["name"]: m["id"] for m in acme["modes"]}
    universes = {u["number"]: u for u in built["universes"]}
    assert [(u["number"], u["name"]) for u in built["universes"]] == [
        (1, "Universe 1"), (2, "Universe 2"),
    ]  # fmt: skip
    fixtures = by_number(built)
    assert list(fixtures) == [101, 102, 103, 201, 202]
    spot_1 = fixtures[101]
    assert spot_1 == {
        "id": spot_1["id"],
        "name": "Spot 1",
        "number": 101,
        "profileId": PROFILE_ID,
        "profileRevision": acme["revision"],
        "modeId": modes["3ch"],
        "patch": {"universeId": universes[1]["id"], "address": 1},
        "orientation": {"invertPan": False, "invertTilt": False, "swapPanTilt": False,
                        "panOffset": 0.0, "tiltOffset": 0.0},
        "location": {"x": -2.0, "y": 2.0, "z": 6.0, "rx": 180.0, "ry": 0.0, "rz": 180.0},
        "mvrUuid": "F101",
    }  # fmt: skip
    assert fixtures[102]["orientation"]["invertPan"] is True
    assert fixtures[201]["modeId"] == modes["1ch"]
    assert fixtures[202]["name"] == "Spot 202"  # <model> <number>, as fixture add names one
    assert fixtures[202]["patch"] == {"universeId": universes[2]["id"], "address": 2}
    assert built["stage"]["frame"] == {"origin": (0.0, 0.0, 0.0), "audience": "-y"}
    assert run(show, "undo") == f"undid: {IMPORTED.splitlines()[0]}"
    assert show.show == before


def test_groups_are_the_hanging_positions_stage_right_first(tmp_path: Path) -> None:
    show = offline()
    run(show, 'fixture add 1 "RGB Par 3ch" mode 3ch')
    run(show, "sel fixture 1")
    run(show, 'record group 7 "Mine"')
    run(show, f'rig import "{club(tmp_path)}"')
    numbers = {f["id"]: f["number"] for f in show.show["fixtures"]}
    groups = [(g["number"], g["name"], [numbers[m["fixtureId"]] for m in g["members"]])
              for g in show.show["groups"]]  # fmt: skip
    # Floor holds nothing, so it makes no group; 103 hangs at x 2 (stage right)
    assert groups == [(7, "Mine", [1]), (8, "LX1", [103, 102, 101]), (9, "LX2", [201, 202])]


def test_a_group_holds_every_element_of_its_fixtures(tmp_path: Path) -> None:
    """With a profile of two cells the show holds by the GDTF's id."""
    cells = [channel(0, "intensity", element=0), channel(1, "intensity", element=1),
             channel(2, "pan"), channel(3, "tilt")]  # fmt: skip
    held = {**profile(PROFILE_ID, mode(cells, mode_id="mode-3ch", elements=2)),
            "name": "Acme Spot", "revision": "mine"}  # fmt: skip
    held["modes"][0]["name"] = "3ch"
    file = tmp_path / "held.json"
    file.write_text(json.dumps(held))
    show = offline()
    run(show, f'profile import "{file}"')
    data = scene(layer("L1", "L", fixture("f1", "A", numeric=1, position="P1"),
                       fixture("f2", "B", numeric=2, position="P1", at=matrix(o=(-1000, 0, 0)))),
                 aux=[position("P1", "Boom")])  # fmt: skip
    reply = run(show, f'rig import "{club(tmp_path, data)}"')
    plotted = import_gdtf(spot()).profile["revision"]
    assert reply.splitlines()[0] == (
        f"note: the show holds \"Acme Spot\" at revision 'mine'; "
        f"the plot's {plotted!r} is not taken"
    )
    ids = {f["number"]: f["id"] for f in show.show["fixtures"]}
    (boom,) = show.show["groups"]
    assert boom["members"] == [{"fixtureId": ids[2], "element": 0},
                               {"fixtureId": ids[2], "element": 1},
                               {"fixtureId": ids[1], "element": 0},
                               {"fixtureId": ids[1], "element": 1}]  # fmt: skip
    assert {f["profileRevision"] for f in show.show["fixtures"]} == {"mine"}


def test_on_a_live_show_the_engine_follows(tmp_path: Path) -> None:
    path = club(tmp_path)
    with LiveShow(new_show("Club"), output=False) as live:
        assert run(live, f'rig check "{path}"') == CHECK
        assert run(live, f'rig import "{path}"') == IMPORTED

        def seen() -> set[int]:
            output = live.output
            return set() if output is None else {f.number for f in output.fixtures}

        eventually(lambda: seen() == {101, 102, 103, 201, 202})
        assert run(live, "undo").startswith("undid: imported 5 fixtures")
        eventually(lambda: seen() == set())


def eventually(test: Callable[[], bool], within: float = 5.0) -> None:
    deadline = time.monotonic() + within
    while not test():
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_the_dmx_of_an_imported_fixture_is_that_of_one_added_by_hand(tmp_path: Path) -> None:
    data = scene(layer("L1", "L", fixture("f1", "Spot", numeric=102, addresses=[("0", "1.4")],
                                          invert_pan="true")))  # fmt: skip
    imported = offline()
    run(imported, f'rig import "{club(tmp_path, data)}"')
    file = tmp_path / "Acme@Spot.gdtf"
    file.write_bytes(gdtf())

    def by_hand(invert: bool) -> OfflineShow:
        show = offline()
        for line in (f'profile import "{file}"', 'universe add 1',
                     'fixture add 102 "Acme Spot" mode 3ch at 1.4',
                     f"fixture 102 orientation.invertPan {str(invert).lower()}"):  # fmt: skip
            run(show, line)
        return show

    frames = []
    for show in (imported, by_hand(True), by_hand(False)):
        for line in ("sel fixture 102", "set intensity 50%", "set pan 45", "set tilt -30"):
            run(show, line)
        frames.append(show.tick(1.0).universes[1][:6])
    assert frames[0] == frames[1]
    assert frames[0] != frames[2]  # the invert is in the output
    assert frames[0][3] == 128  # 1.4 is the dimmer, at 50%


# ------------------------------------------------------------------ numbers and names


def test_numbers_and_names(tmp_path: Path) -> None:
    show = offline()
    run(show, 'fixture add 500 "RGB Par 3ch" mode 3ch')
    data = scene(layer("L1", "L",
        fixture("a", "A", numeric=101, fixture_id="7"),  # FixtureIDNumeric wins
        fixture("b", "B", numeric=0, fixture_id="102"),  # else FixtureID, a whole number
        fixture("c", "", fixture_id="C-3"),  # else the next above the highest
        fixture("d", "D", numeric=500),  # taken by the show
        fixture("e", "E", numeric=101),  # taken by A
    ))  # fmt: skip
    reply = run(show, f'rig import "{club(tmp_path, data)}"')
    assert reply.splitlines()[:2] == [
        "note: 1 fixture has no fixture number: numbered 501",
        "note: 2 fixtures have numbers already taken (101, 500): numbered 502, 503",
    ]
    names = {f["number"]: f["name"] for f in show.show["fixtures"]}
    assert names == {500: "Par 500", 101: "A", 102: "B", 501: "Spot 501", 502: "D", 503: "E"}


# ------------------------------------------------------------------ profiles


def test_a_profile_the_show_holds_is_used_as_it_is(tmp_path: Path) -> None:
    file = tmp_path / "Acme@Spot.gdtf"
    file.write_bytes(gdtf())
    show = offline()
    run(show, f'profile import "{file}"')
    held = copy.deepcopy(show.show["profiles"])
    check = run(show, f'rig check "{club(tmp_path)}"')
    assert "profiles to add" not in check
    assert not any("note" in line for line in check.splitlines())
    assert run(show, f'rig import "{club(tmp_path)}"').startswith(
        "imported 5 fixtures, 2 universes and 2 groups from club.mvr"
    )
    assert show.show["profiles"] == held


def test_a_gdtf_named_like_another_of_the_show_s_profiles_is_not_added(tmp_path: Path) -> None:
    file = tmp_path / "other.json"
    file.write_text(json.dumps({**profile("prof-other", mode([channel(0, "intensity")])),
                                "name": "ACME SPOT"}))  # fmt: skip
    show = offline()
    run(show, f'profile import "{file}"')
    before = copy.deepcopy(show.show)
    reply = show.execute(f'rig import "{club(tmp_path)}"')
    assert (reply.ok, reply.text) == (False, (
        'note: "Acme@Spot.gdtf" imports as "Acme Spot", a name another profile has: '
        '"Spot 1", "Spot 2", "Spot 3" and 2 more not added\n'
        "error: club.mvr has no fixture busk can add"
    ))  # fmt: skip
    assert show.show == before


def test_two_files_of_one_fixture_type_add_one_profile(tmp_path: Path) -> None:
    """The second file's fixtures take the profile the first added, whatever
    the order their fixtures come in."""
    older = description(*_spot_modes("3ch"), name="Spot", manufacturer="Acme",
                        revisions=("2020-01-01T00:00:00",))  # fmt: skip
    files = {SPOT: gdtf(), "Old.gdtf": gdtf(older)}
    data = scene(layer("L1", "L",
        fixture("f1", "Bad", numeric=1, gdtf_mode="nope"),  # SPOT, not added
        fixture("f2", "Old", numeric=2, gdtf="Old.gdtf"),  # adds the older revision
        fixture("f3", "New", numeric=3),  # SPOT again: takes the older
    ))  # fmt: skip
    show = offline()
    run(show, f'rig import "{club(tmp_path, data, files)}"')
    (added,) = show.show["profiles"]
    assert {f["profileRevision"] for f in show.show["fixtures"]} == {added["revision"]}
    assert [f["number"] for f in show.show["fixtures"]] == [2, 3]


def test_a_gdtf_named_like_one_the_import_adds_is_not_added(tmp_path: Path) -> None:
    other = description(*_spot_modes("3ch"), name="Spot", manufacturer="Acme",
                        type_id="11111111-2222-3333-4444-555555555555")  # fmt: skip
    files = {SPOT: gdtf(), "Other.gdtf": gdtf(other)}
    data = scene(layer("L1", "L", fixture("f1", "A", numeric=1),
                       fixture("f2", "B", numeric=2, gdtf="Other.gdtf")))  # fmt: skip
    check = run(offline(), f'rig check "{club(tmp_path, data, files)}"')
    assert check.splitlines()[3] == (
        '  note: "Other.gdtf" imports as "Acme Spot", a name another profile has: "B" not added'
    )


def _spot_modes(name: str) -> tuple[Any, ...]:
    dimmer = gdtf_channel("1", gdtf_function("Dimmer"))
    return (gdtf_mode(name, dimmer),)


def test_the_gdtf_importer_s_notes_are_counted_by_check_and_said_by_import(
    tmp_path: Path,
) -> None:
    channels = (gdtf_channel("1", gdtf_function("Dimmer")),
                gdtf_channel("2", gdtf_function("Control1")))  # fmt: skip
    files = {SPOT: gdtf(description(gdtf_mode("3ch", *channels), name="Spot", manufacturer="Acme"))}
    data = scene(layer("L1", "L", fixture("f1", "A", numeric=1)))
    path = club(tmp_path, data, files)
    show = offline()
    check = run(show, f'rig check "{path}"').splitlines()
    assert check[3] == '  note: "Acme Spot": 1 note from its GDTF, listed by rig import'
    reply = run(show, f'rig import "{path}"')
    assert reply.splitlines()[0] == (
        'note: "Acme@Spot.gdtf": Beam_Control1: no busk attribute (Control1); held at DMX 0'
    )


def test_fixtures_left_out_are_noted_by_why(tmp_path: Path) -> None:
    data = scene(layer("L1", "L",
        fixture("f1", "Kept", numeric=1),
        fixture("f2", "Copy", numeric=2, multipatch="f1"),
        fixture("f3", "Hazer", gdtf=None),
        fixture("f4", "Fan", gdtf=None),
        fixture("f5", "Lost", gdtf="Gone@Thing.gdtf"),
        fixture("f6", "Odd", gdtf_mode="16ch"),
        fixture("f7", "Bare", gdtf_mode=None),
    ))  # fmt: skip
    check = run(offline(), f'rig check "{club(tmp_path, data)}"')
    assert check.splitlines()[1:-1] == [
        "  add 1: 1",
        '  profiles to add: "Acme Spot"',
        '  note: multipatch copies of other fixtures: "Copy" not added',
        '  note: no GDTF in the plot: "Hazer", "Fan" not added',
        '  note: "Gone@Thing.gdtf" is not in the plot: "Lost" not added',
        '  note: "Acme Spot" has no mode "16ch": "Odd" not added',
        '  note: no GDTF mode: "Bare" not added',
    ]


# ------------------------------------------------------------------ patch


def test_the_patch(tmp_path: Path) -> None:
    show = offline()
    run(show, 'universe add 1 "Stage"')
    data = scene(layer("L1", "L",
        fixture("f1", "Split", numeric=1, addresses=[("0", "1.1"), ("1", "3.1")]),
        fixture("f2", "Late", numeric=2, addresses=[("0", "1.511")]),
        fixture("f3", "Loose", numeric=3),
        fixture("f4", "Second", numeric=4, addresses=[("1", "1.20")]),
        fixture("f5", "Off", numeric=5, addresses=[("0", "4.512")]),
    ))  # fmt: skip
    check = run(show, f'rig check "{club(tmp_path, data)}"')
    # 1 is the show's; nothing is patched in 3 (a second break) or 4 (past 512)
    assert "universes to add" not in check
    assert check.splitlines()[-3:-1] == [
        "  note: 1, 4 have a second DMX break, not patched",
        "  note: 2, 5 would end past channel 512, not patched",
    ]
    run(show, f'rig import "{club(tmp_path, data)}"')
    stage = show.show["universes"][0]["id"]
    patches = {f["number"]: f["patch"] for f in show.show["fixtures"]}
    assert patches == {1: {"universeId": stage, "address": 1}, 2: None, 3: None, 4: None, 5: None}
    assert len(show.show["universes"]) == 1


# ------------------------------------------------------------------ the frame and the plot


def test_the_frame_on_the_line_is_kept_and_used_again(tmp_path: Path) -> None:
    show = offline()
    reply = run(show, f'rig import "{club(tmp_path)}" origin 1000 -2000 6000 audience +x')
    # busk x, y are the plot's −Y, X, from the origin: LX1 is on x 0, LX2 on −2
    assert reply.splitlines()[-1] == "fixtures span x -2.0…0.0, y -3.0…1.0, z 0.0…1.0 m"
    frame = show.show["stage"]["frame"]
    assert frame == {"origin": (1000.0, -2000.0, 6000.0), "audience": "+x"}
    spot_1 = by_number(show.show)[101]["location"]
    assert spot_1 == {"x": 0.0, "y": 1.0, "z": 0.0, "rx": 180.0, "ry": 0.0, "rz": 90.0}
    run(show, "delete fixture 101 thru 202 cascade")
    again = run(show, f'rig check "{club(tmp_path)}" audience +x')  # origin as kept
    assert again.splitlines()[-1] == reply.splitlines()[-1]
    assert run(show, f'rig check "{club(tmp_path)}"').splitlines()[-1] == again.splitlines()[-1]


def test_the_show_keeps_the_plot_relative_to_its_file(tmp_path: Path) -> None:
    path = club(tmp_path)
    (tmp_path / "shows").mkdir()
    saved = offline(path=tmp_path / "shows" / "club.show")
    run(saved, f'rig import "{path}"')
    assert saved.show["stage"]["plot"] == os.path.join("..", "plots", "club.mvr")
    unsaved = offline()
    run(unsaved, f'rig import "{path}"')
    assert unsaved.show["stage"]["plot"] == str(path.absolute())
    assert unsaved.show["stage"]["plotHash"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_an_imported_rig_is_saved_and_loaded(tmp_path: Path) -> None:
    show = offline()
    run(show, f'rig import "{club(tmp_path)}"')
    run(show, f'save "{tmp_path / "club.show"}"')
    loaded, issues = load_show(tmp_path / "club.show")
    assert issues == []
    assert loaded["stage"] == show.show["stage"]
    assert [f.get("mvrUuid") for f in loaded["fixtures"]] == ["F101", "F102", "F103", "F201",
                                                             "F202"]  # fmt: skip


# ------------------------------------------------------------------ importing again


def imported(tmp_path: Path, *lines: str) -> OfflineShow:
    """A show with the club plot imported, then ``lines`` run."""
    show = offline()
    run(show, f'rig import "{club(tmp_path)}"')
    for line in lines:
        run(show, line)
    return show


def again(
    tmp_path: Path,
    *extra: ET.Element,
    changes: Changes | None = None,
    aux: tuple[ET.Element, ...] = (),
    files: dict[str, bytes] | None = None,
) -> Path:
    """The club plot as the designer sends it again, ``club-v2.mvr``."""
    data = club_scene(*extra, changes=changes, aux=aux)
    return club(tmp_path, data, files, name="club-v2.mvr")  # fmt: skip


def lines_of(show: OfflineShow, line: str) -> list[str]:
    return run(show, line).splitlines()


AGAIN_CHECK = """\
the plot has 6 fixtures, 1 profile and 3 universes; the show has 4 of them
  add 2: 104, 301
  move 1: 101
  repatch 2: 102, 201
  change 1: 202 mode 1ch → 3ch
  rename 1: 102
  invert 1: 201
  remove 1: 103: used by 1 group, add cascade
  universes to add: 3
  note: 201 has another number in the plot (211): number kept
  note: 104 is new on "LX1": no group changed
  note: 301 hangs on "LX3", a new position: no group made
fixtures span x -2.5…1.0, y -3.0…2.0, z 6.0…8.0 m"""

AGAIN_IMPORTED = """\
note: 201 has another number in the plot (211): number kept
note: 104 is new on "LX1": no group changed
note: 301 hangs on "LX3", a new position: no group made
updated the rig from club-v2.mvr: added 2 fixtures and 1 universe; moved 1, repatched 2, \
changed 1, renamed 1, inverted 1, removed 1 (left 1 group)
fixtures span x -2.5…1.0, y -3.0…2.0, z 6.0…8.0 m"""


def test_a_plot_imported_again_brings_its_fixtures_to_it(tmp_path: Path) -> None:
    show = imported(tmp_path,
        'fixture add 1 "RGB Par 3ch" mode 3ch at 1.30',  # by hand: never touched
        "fixture 101 orientation.swapPanTilt true", "fixture 101 limits tilt -90 10",
        "fixture 101 orientation.invertTilt true",  # the plot never says: kept
        'rename fixture 202 "Mine"',  # the plot names it not: kept
        "fixture 201 patch 2.40",  # the plot owns the patch: back to 2.1
    )  # fmt: skip
    before = copy.deepcopy(show.show)
    path = again(
        tmp_path,
        fixture("f104", "Spot 4", numeric=104, addresses=[("0", "1.20")], position="P1",
                at=matrix(o=(0, -2000, 6000))),
        fixture("f301", "Spot 5", numeric=301, addresses=[("0", "3.1")], position="P4",
                at=matrix(o=(0, 3000, 8000))),
        changes={
            "f101": {"at": matrix(o=(2500, 0, 0))},
            "f102": {"name": "Spot L", "addresses": [("0", "1.10")]},
            "f201": {"invert_tilt": "true", "fixture_id": "211"},
            "f202": {"gdtf_mode": "3ch"},
            "f103": None,
        },
        aux=(position("P4", "LX3"),),
    )  # fmt: skip
    assert run(show, f'rig check "{path}"') == AGAIN_CHECK
    assert show.show == before
    assert run(show, f'rig import "{path}" cascade') == AGAIN_IMPORTED
    was, now = by_number(before), by_number(show.show)
    assert list(now) == [101, 102, 201, 202, 1, 104, 301]
    assert now[1] == was[1]
    universes = {u["number"]: u["id"] for u in show.show["universes"]}
    assert now[101] == {**was[101], "location": {**was[101]["location"], "x": -2.5}}
    assert now[101]["orientation"]["swapPanTilt"] is True
    assert now[102] == {**was[102], "name": "Spot L",
                        "patch": {"universeId": universes[1], "address": 10}}  # fmt: skip
    assert now[201]["orientation"] == {**was[201]["orientation"], "invertTilt": True}
    assert now[201]["patch"] == {"universeId": universes[2], "address": 1}
    assert now[201]["number"] == 201
    modes = {m["name"]: m["id"] for m in show.show["profiles"][0]["modes"]}
    assert now[202] == {**was[202], "modeId": modes["3ch"]}
    assert now[202]["name"] == "Mine"
    assert (now[104]["mvrUuid"], now[301]["patch"]) == (
        "F104", {"universeId": universes[3], "address": 1},
    )  # fmt: skip
    groups = [(g["name"], [m["fixtureId"] for m in g["members"]]) for g in show.show["groups"]]
    # the removal took 103 from LX1; stage right first, as ever
    assert groups == [("LX1", [was[102]["id"], was[101]["id"]]),
                      ("LX2", [was[201]["id"], was[202]["id"]])]  # fmt: skip
    assert show.show["stage"]["plot"] == str(path.absolute())
    assert show.show["stage"]["plotHash"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert run(show, "undo").startswith("undid: updated the rig from club-v2.mvr: added 2")
    assert show.show == before


@pytest.mark.parametrize(
    ("changes", "line"),
    [
        ({"f101": {"at": matrix(o=(2500, 0, 0))}}, "  move 1: 101"),
        ({"f101": {"at": matrix(u=(0, 1, 0), v=(-1, 0, 0), o=(2000, 0, 0))}}, "  move 1: 101"),
        ({"f101": {"addresses": [("0", "1.20")]}}, "  repatch 1: 101"),
        ({"f101": {"addresses": []}}, "  repatch 1: 101"),  # the plot unpatches it
        ({"f201": {"gdtf_mode": "3ch"}}, "  change 1: 201 mode 1ch → 3ch"),
        ({"f101": {"name": "Front"}}, "  rename 1: 101"),
        ({"f101": {"invert_tilt": "true"}}, "  invert 1: 101"),
        ({"f102": {"invert_pan": "false"}}, "  invert 1: 102"),
        ({"f201": {"gdtf_mode": "3ch"}, "f202": {"gdtf_mode": "3CH"}},
         "  change 2: 201, 202 mode 1ch → 3ch"),
        ({"f103": None}, "  remove 1: 103: used by 1 group, add cascade"),
    ],
)  # fmt: skip
def test_each_change_alone(tmp_path: Path, changes: Changes, line: str) -> None:
    show = imported(tmp_path)
    before = copy.deepcopy(show.show)
    path = again(tmp_path, changes=changes)
    check = lines_of(show, f'rig check "{path}"')
    assert check[1:-1] == [line]
    reply = run(show, f'rig import "{path}" cascade').splitlines()
    assert reply[0].startswith("updated the rig from club-v2.mvr: ")
    assert run(show, "undo") == f"undid: {reply[0]}"
    assert show.show == before


def test_what_the_plot_does_not_say_is_not_changed(tmp_path: Path) -> None:
    """No name, no invert: the fixture keeps busk's."""
    show = imported(tmp_path, 'rename fixture 101 "Mine"', "fixture 101 orientation.invertPan true")
    unnamed = again(tmp_path, changes={"f101": {"name": ""}})
    assert lines_of(show, f'rig check "{unnamed}"')[1:-1] == ["  no fixture changes"]
    # the first plot names it "Spot 1", and says nothing of its inverts
    assert lines_of(show, f'rig check "{club(tmp_path)}"')[1:-1] == ["  rename 1: 101"]


def test_another_profile(tmp_path: Path) -> None:
    wash = gdtf(spot("Wash", "11111111-2222-3333-4444-555555555555"))
    files = {SPOT: gdtf(), "Acme@Wash.gdtf": wash}
    show = imported(tmp_path)
    path = again(tmp_path, changes={"f101": {"gdtf": "Acme@Wash.gdtf", "gdtf_mode": "1ch"}},
                 files=files)  # fmt: skip
    assert lines_of(show, f'rig check "{path}"')[1:-1] == [
        '  change 1: 101 "Acme Spot", 3ch → "Acme Wash", 1ch',
        '  profiles to add: "Acme Wash"',
    ]
    assert run(show, f'rig import "{path}"').splitlines()[0] == (
        "updated the rig from club-v2.mvr: added 1 profile; changed 1"
    )
    wash = show.show["profiles"][1]
    spot_1 = by_number(show.show)[101]
    assert (spot_1["profileId"], spot_1["profileRevision"], spot_1["modeId"]) == (
        wash["id"], wash["revision"], wash["modes"][1]["id"],
    )  # fmt: skip


def test_programming_on_a_moved_repatched_fixture_outputs_as_before(tmp_path: Path) -> None:
    show = imported(tmp_path,
        "sel fixture 101", "set pan 45", 'record preset position 1 "Side"', "clear",
        "sel fixture 101", "set intensity 50%", "set tilt -30", "record cue 1/1", "clear",
        "sel fixture 101", "set pan preset position 1", "record cue 1/1 merge", "clear",
        "playback add 1 cuelist 1", "go 1",
    )  # fmt: skip
    before = show.tick(1.0).universes[1]
    assert before[:3] != bytes(3)
    path = again(tmp_path, changes={"f101": {"at": matrix(o=(3000, 0, 0)),
                                             "addresses": [("0", "1.20")]}})  # fmt: skip
    assert lines_of(show, f'rig check "{path}"')[1:-1] == ["  move 1: 101", "  repatch 1: 101"]
    run(show, f'rig import "{path}"')
    after = show.tick(1.0).universes[1]
    assert after[19:22] == before[:3]
    assert after[:3] == bytes(3)
    assert after[3:9] == before[3:9]  # 102 and 103


def test_a_removal_is_refused_without_cascade_and_goes_as_delete_takes_it(tmp_path: Path) -> None:
    lines = ("sel fixture 103", "set intensity 50%", "record preset intensity 1 target",
             "record cue 1/1", "clear", "park fixture 103 intensity 0")  # fmt: skip
    show = imported(tmp_path, *lines)
    before = copy.deepcopy(show.show)
    path = again(tmp_path, changes={"f103": None})
    uses = "1 group, 1 preset, 1 cue and 1 parked value"
    assert lines_of(show, f'rig check "{path}"')[1:-1] == [
        f"  remove 1: 103: used by {uses}, add cascade"
    ]
    reply = show.execute(f'rig import "{path}"')
    assert (reply.ok, reply.text) == (
        False, f"error: fixture 103 is gone from the plot and used by {uses}: add cascade",
    )  # fmt: skip
    assert show.show == before
    assert run(show, f'rig import "{path}" cascade').splitlines()[0] == (
        f"updated the rig from club-v2.mvr: removed 1 (left {uses})"
    )
    by_hand = imported(tmp_path, *lines, "delete fixture 103 cascade")
    for key in ("fixtures", "groups", "presets", "cueLists", "park", "bindings"):
        assert show.show[key] == by_hand.show[key]


def test_a_show_whose_plot_fixtures_are_gone_starts_again(tmp_path: Path) -> None:
    """With no fixture from a plot left, the next import is a first one: it
    makes groups, though the show keeps its stage."""
    show = imported(tmp_path, "delete fixture 101 thru 202 cascade")
    assert "stage" in show.show
    check = lines_of(show, f'rig check "{club(tmp_path)}"')
    assert check[0] == "the plot has 5 fixtures, 1 profile and 2 universes"
    assert '  groups to add: "LX1", "LX2"' in check


def test_fixtures_nothing_uses_go_without_cascade(tmp_path: Path) -> None:
    show = imported(tmp_path, "delete group 1 cascade", "delete group 2 cascade")
    path = again(tmp_path, changes={"f103": None, "f202": None})
    assert lines_of(show, f'rig check "{path}"')[1:-1] == ["  remove 2: 103, 202"]
    assert run(show, f'rig import "{path}"').splitlines()[0] == (
        "updated the rig from club-v2.mvr: removed 2"
    )
    assert list(by_number(show.show)) == [101, 102, 201]


def two_cells(tmp_path: Path) -> OfflineShow:
    """The club plot imported over a profile the show holds by the GDTF's id,
    whose mode ``3ch`` has two cells and ``1ch`` one: group 1, LX1, holds both
    cells of 101 to 103."""
    cells = [channel(0, "intensity", element=0), channel(1, "intensity", element=1),
             channel(2, "pan"), channel(3, "tilt")]  # fmt: skip
    modes = (mode(cells, mode_id="3ch", elements=2), mode([channel(0, "intensity")], mode_id="1ch"))
    held = {**profile(PROFILE_ID, *modes), "name": "Acme Spot", "revision": "mine"}
    file = tmp_path / "held.json"
    file.write_text(json.dumps(held))
    show = offline()
    run(show, f'profile import "{file}"')
    run(show, f'rig import "{club(tmp_path)}"')
    return show


def test_a_mode_that_loses_elements_in_use_is_refused_even_with_cascade(tmp_path: Path) -> None:
    show = two_cells(tmp_path)
    run(show, "sel fixture 101.2")
    run(show, 'record group 7 "Second"')
    before = copy.deepcopy(show.show)
    path = again(tmp_path, changes={"f101": {"gdtf_mode": "1ch"}, "f102": {"gdtf_mode": "1ch"},
                                    "f103": None})  # fmt: skip
    blocked = "fixtures 101, 102 cannot run 1ch: groups 1, 7 use elements they would lose"
    check = lines_of(show, f'rig check "{path}"')
    assert check[1:5] == [
        f"  blocked: {blocked}",
        "  change 2: 101, 102 mode 3ch → 1ch",
        "  remove 1: 103: used by 1 group, add cascade",
        "  note: the show holds \"Acme Spot\" at revision 'mine'; "
        f"the plot's {import_gdtf(spot()).profile['revision']!r} is not taken",
    ]
    for cascade in ("", " cascade"):
        reply = show.execute(f'rig import "{path}"{cascade}')
        assert not reply.ok
        assert reply.text.splitlines()[0] == f"error: {blocked}"
    assert reply.text.splitlines()[1:] == []
    assert show.execute(f'rig import "{path}"').text.splitlines()[1] == (
        "error: fixture 103 is gone from the plot and used by 1 group: add cascade"
    )
    assert show.show == before
    one = again(tmp_path, changes={"f103": {"gdtf_mode": "1ch"}})  # 103 alone is in group 1 only
    assert lines_of(show, f'rig check "{one}"')[1] == (
        "  blocked: fixture 103 cannot run 1ch: group 1 uses elements it would lose"
    )
    run(show, "delete group 1 cascade")
    assert lines_of(show, f'rig check "{one}"')[1] == "  change 1: 103 mode 3ch → 1ch"


def test_numbers_stay_and_a_removed_fixture_s_number_is_free(tmp_path: Path) -> None:
    show = imported(tmp_path)
    ids = {f["number"]: f["id"] for f in show.show["fixtures"]}
    # the designer drew 103 again, with a new uuid, and renumbered 101
    path = again(tmp_path, fixture("g103", "Spot 3", numeric=103, addresses=[("0", "1.7")]),
                 changes={"f103": None, "f101": {"numeric": 105}})  # fmt: skip
    assert lines_of(show, f'rig check "{path}"')[1:-1] == [
        "  add 1: 103",
        "  remove 1: 103: used by 1 group, add cascade",
        "  note: 101 has another number in the plot (105): number kept",
    ]
    run(show, f'rig import "{path}" cascade')
    fixtures = by_number(show.show)
    assert fixtures[101]["id"] == ids[101]
    assert (fixtures[103]["mvrUuid"], fixtures[103]["id"] == ids[103]) == ("G103", False)


def test_a_frame_on_the_line_moves_every_fixture_from_the_plot(tmp_path: Path) -> None:
    show = imported(
        tmp_path,
        'fixture add 1 "RGB Par 3ch" mode 3ch',
        'fixture 1 location {"x": 1, "y": 0, "z": 0, "rx": 0, "ry": 0, "rz": 0}',
    )
    hand = by_number(show.show)[1]
    path = club(tmp_path)  # the same plot
    assert lines_of(show, f'rig check "{path}" audience +y')[1:] == [
        "  move 5: 101–103, 201, 202",
        "fixtures span x -2.0…2.0, y -2.0…0.0, z 6.0…7.0 m",
    ]
    run(show, f'rig import "{path}" audience +y')
    assert show.show["stage"]["frame"] == {"origin": (0.0, 0.0, 0.0), "audience": "+y"}
    assert by_number(show.show)[101]["location"] == {
        "x": 2.0, "y": -2.0, "z": 6.0, "rx": 180.0, "ry": 0.0, "rz": 0.0,
    }  # fmt: skip
    assert by_number(show.show)[1] == hand
    assert lines_of(show, f'rig check "{path}"')[1] == "  nothing to change"  # the frame kept


def test_a_fixture_of_the_show_the_plot_cannot_place_is_not_changed(tmp_path: Path) -> None:
    show = imported(tmp_path)
    before = copy.deepcopy(show.show)
    path = again(tmp_path, changes={
        "f101": {"gdtf_mode": "16ch", "at": matrix(o=(3000, 0, 0))},
        "f102": {"gdtf": None},
        "f201": {"multipatch": "F202"},
    })  # fmt: skip
    assert lines_of(show, f'rig check "{path}"')[1:-1] == [
        "  no fixture changes",
        '  note: "Acme Spot" has no mode "16ch": 101 not changed',
        "  note: no GDTF in the plot: 102 not changed",
        "  note: multipatch copies of other fixtures: 201 not changed",
    ]
    assert run(show, f'rig import "{path}"').splitlines()[-2:] == [
        "updated the rig from club-v2.mvr: no fixture changes",
        "fixtures span x -1.0…2.0, y 0.0…2.0, z 6.0…7.0 m",  # 103 and 202
    ]
    assert show.show["fixtures"] == before["fixtures"]
    assert show.show["stage"]["plot"].endswith("club-v2.mvr")


NOTHING = """\
the plot has 5 fixtures, 1 profile and 2 universes; the show has 5 of them
  nothing to change
fixtures span x -2.0…2.0, y 0.0…2.0, z 6.0…7.0 m"""


def test_a_plot_that_changes_nothing(tmp_path: Path) -> None:
    show = imported(tmp_path)
    path = club(tmp_path)
    assert run(show, f'rig check "{path}"') == NOTHING
    reply = show.execute(f'rig import "{path}"')
    assert (reply.ok, reply.text) == (False, "error: the rig is already as club.mvr has it")
    truss = scenery("Truss", "t9", "LX9", model("truss.glb"))
    changed = club(tmp_path, club_scene(truss), files={SPOT: gdtf(), "truss.glb": b"glTF"})
    assert lines_of(show, f'rig check "{changed}"')[1] == "  no fixture changes"
    assert run(show, f'rig import "{changed}"').splitlines()[0] == (
        "updated the rig from club.mvr: no fixture changes"
    )
    assert show.show["stage"]["plotHash"] == hashlib.sha256(changed.read_bytes()).hexdigest()


def test_on_a_live_show_an_import_again_reaches_the_engine(tmp_path: Path) -> None:
    path = club(tmp_path)
    v2 = again(tmp_path, fixture("f301", "New", numeric=301), changes={"f103": None})
    with LiveShow(new_show("Club"), output=False) as live:
        run(live, f'rig import "{path}"')

        def seen() -> set[int]:
            output = live.output
            return set() if output is None else {f.number for f in output.fixtures}

        eventually(lambda: seen() == {101, 102, 103, 201, 202})
        assert run(live, f'rig check "{v2}"').splitlines()[1:3] == [
            "  add 1: 301", "  remove 1: 103: used by 1 group, add cascade",
        ]  # fmt: skip
        reply = live.execute(f'rig import "{v2}"')
        assert (reply.ok, reply.text) == (
            False, "error: fixture 103 is gone from the plot and used by 1 group: add cascade",
        )  # fmt: skip
        run(live, f'rig import "{v2}" cascade')
        eventually(lambda: seen() == {101, 102, 201, 202, 301})
        assert run(live, "undo").startswith("undid: updated the rig from club-v2.mvr")
        eventually(lambda: seen() == {101, 102, 103, 201, 202})


# ------------------------------------------------------------------ refusals


@pytest.mark.parametrize(
    ("make", "says"),
    [
        (lambda p: None, "No such file or directory"),
        (lambda p: p.write_bytes(b"nope"), "not an MVR file: File is not a zip file"),
    ],
)
def test_a_file_that_fails_says_so_in_one_line(
    tmp_path: Path, make: Callable[[Path], object], says: str
) -> None:
    path = tmp_path / "club.mvr"
    make(path)
    show = offline()
    reply = show.execute(f'rig import "{path}"')
    assert not reply.ok
    assert reply.text.startswith(f"error: cannot import {str(path)!r}: ")
    assert says in reply.text
    assert "\n" not in reply.text


def test_a_plot_with_nothing_to_add(tmp_path: Path) -> None:
    path = club(tmp_path, scene(layer("L1", "L")))
    show = offline()
    assert run(show, f'rig check "{path}"') == (
        "the plot has 0 fixtures, 0 profiles and 0 universes\n  nothing to add"
    )
    reply = show.execute(f'rig import "{path}"')
    assert (reply.ok, reply.text) == (False, "error: club.mvr has no fixture busk can add")


# ------------------------------------------------------------------ the line


def context() -> Context:
    return Context(new_show("Club"), ProfileLibrary(), RandomIds())


@pytest.mark.parametrize(
    ("line", "action"),
    [
        ('rig check "plots/club.mvr"', ImportRig(Path("plots/club.mvr"), True)),
        ('RIG IMPORT "a b.mvr" AUDIENCE +X', ImportRig(Path("a b.mvr"), False, "+x")),
        ('rig import x.mvr origin -1.5 +2 .5 audience -x',
         ImportRig(Path("x.mvr"), False, "-x", (-1.5, 2.0, 0.5))),
        ('rig import x.mvr CASCADE audience +y', ImportRig(Path("x.mvr"), False, "+y", None, True)),
    ],
)  # fmt: skip
def test_the_parser_names_the_file_and_the_frame(line: str, action: ImportRig) -> None:
    assert parse(line, context()) == action


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ('rig check "a.mvr" audience down', "expected -y or +y or -x or +x, got 'down'"),
        ('rig check "a.mvr" origin 1 2', "expected a distance in mm"),
        ('rig check "a.mvr" origin 1 2 3%', "expected a distance in mm, got '3%'"),
        ('rig check "a.mvr" origin 1 "2" 3', "expected a distance in mm, got '2'"),
        ('rig check "a.mvr" audience -y audience +y', "expected origin, got 'audience'"),
        ('rig check "a.mvr" audience -y origin 0 0 0 cascade', "unexpected 'cascade'"),
        ('rig check "a.mvr" cascade', "expected audience or origin, got 'cascade'"),
        ('rig import "a.mvr" cascade cascade', "expected audience or origin, got 'cascade'"),
        ('rig check "a.mvr" frame', "expected audience or origin, got 'frame'"),
        ("rig load", "expected check or import, got 'load'"),
    ],
)
def test_the_parser_refuses_what_is_not_a_rig_line(line: str, error: str) -> None:
    with pytest.raises(ParseError) as caught:
        parse(line, context())
    assert caught.value.message == error


@pytest.mark.parametrize(
    ("line", "words", "values", "runnable"),
    [
        ("rig ", ("check", "import"), (), False),
        ("rig import ", (), ('a path in quotes, e.g. "plots/club.mvr"',), False),
        ('rig check "a.mvr" ', ("audience", "origin"), (), True),
        ('rig import "a.mvr" ', ("audience", "origin", "cascade"), (), True),
        ('rig import "a.mvr" audience ', ("-y", "+y", "-x", "+x"), (), False),
        ('rig import "a.mvr" audience +y ', ("origin", "cascade"), (), True),
        ('rig import "a.mvr" origin ', (), ("a distance in mm",), False),
        ('rig import "a.mvr" origin 0 0 0 audience +y ', ("cascade",), (), True),
        ('rig import "a.mvr" cascade origin 0 0 0 audience +y ', (), (), True),
    ],
)
def test_completion(
    line: str, words: tuple[str, ...], values: tuple[str, ...], runnable: bool
) -> None:
    found = offline().expected(line)
    assert (found.words, found.values, found.runnable, found.error) == (
        words, values, runnable, None,
    )  # fmt: skip


def test_rig_asks_nothing_and_has_help(tmp_path: Path) -> None:
    show = offline()
    assert show.confirmation(f'rig import "{club(tmp_path)}"') is None
    assert "rig" in show.expected("").words
    assert any(line.lstrip().startswith("rig import") for line in run(show, "help").splitlines())


# ------------------------------------------------------------------ a frontend's preview


def test_rig_check_as_a_value_is_the_line_s_answer_and_changes_nothing(tmp_path: Path) -> None:
    """GAP-59: ``rig_check`` says what ``rig check`` says, with what a
    frontend needs to offer the import, and uses none of the session's ids."""
    path = club(tmp_path)
    show = offline()
    before = copy.deepcopy(show.show)
    check = show.rig_check(path)
    assert check.text == CHECK == run(show, f'rig check "{path}"')
    assert (check.first, check.audience, check.origin) == (True, "-y", (0.0, 0.0, 0.0))
    assert (check.changes, check.cascade, check.blocked) == (True, False, ())
    assert show.show == before
    run(show, f'rig import "{path}"')
    alone = offline()
    run(alone, f'rig import "{path}"')
    assert show.show["fixtures"] == alone.show["fixtures"]  # the check took none of the ids


def test_rig_check_takes_the_frame_s_words_else_the_show_s(tmp_path: Path) -> None:
    path = club(tmp_path)
    show = offline()
    check = show.rig_check(path, audience="+x", origin=(1000, -2000, 6000))
    line = run(show, f'rig check "{path}" audience +x origin 1000 -2000 6000')
    assert check.text == line
    assert (check.audience, check.origin) == ("+x", (1000.0, -2000.0, 6000.0))
    assert all(isinstance(axis, float) for axis in check.origin)
    run(show, f'rig import "{path}" audience +x origin 1000 -2000 6000')
    kept = show.rig_check(path)
    assert (kept.first, kept.audience, kept.origin) == (False, "+x", (1000.0, -2000.0, 6000.0))
    assert (kept.text, kept.changes) == (run(show, f'rig check "{path}"'), False)
    turned = show.rig_check(path, audience="-y")
    assert (turned.audience, turned.origin) == ("-y", (1000.0, -2000.0, 6000.0))
    assert turned.changes
    assert turned.text.splitlines()[1] == "  move 5: 101–103, 201, 202"


def test_rig_check_says_when_the_import_needs_cascade_or_cannot_run(tmp_path: Path) -> None:
    show = two_cells(tmp_path)
    gone = again(tmp_path, changes={"f103": None})
    check = show.rig_check(gone)
    assert (check.changes, check.cascade, check.blocked) == (True, True, ())
    assert check.text == run(show, f'rig check "{gone}"')
    run(show, "sel fixture 101.2")
    run(show, 'record group 7 "Second"')
    lose = again(tmp_path, changes={"f101": {"gdtf_mode": "1ch"}, "f103": None})
    check = show.rig_check(lose)
    assert (check.changes, check.cascade) == (True, True)
    assert check.blocked == ("fixture 101 cannot run 1ch: groups 1, 7 use elements it would lose",)
    assert f"  blocked: {check.blocked[0]}" in check.text.splitlines()


def test_rig_check_says_when_there_is_nothing_to_do(tmp_path: Path) -> None:
    empty = club(tmp_path, scene(layer("L1", "L")), name="empty.mvr")
    check = offline().rig_check(empty)
    assert (check.first, check.changes) == (True, False)
    assert check.text.splitlines()[-1] == "  nothing to add"
    show = imported(tmp_path)
    check = show.rig_check(club(tmp_path))
    assert (check.first, check.changes, check.cascade, check.text) == (False, False, False, NOTHING)


@pytest.mark.parametrize(
    ("make", "says"),
    [
        (lambda p: None, "No such file or directory"),
        (lambda p: p.write_bytes(b"nope"), "not an MVR file: File is not a zip file"),
    ],
)
def test_rig_check_raises_import_failed_with_the_line_s_reason(
    tmp_path: Path, make: Callable[[Path], object], says: str
) -> None:
    path = tmp_path / "club.mvr"
    make(path)
    show = offline()
    with pytest.raises(ImportFailed) as raised:
        show.rig_check(path)
    assert says in str(raised.value)
    assert show.execute(f'rig check "{path}"').text == (
        f"error: cannot import {str(path)!r}: {raised.value}"
    )


def test_rig_check_reads_a_relative_path_as_the_line_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    club(tmp_path)
    monkeypatch.chdir(tmp_path)
    show = offline()
    assert show.rig_check("plots/club.mvr").text == run(show, 'rig check "plots/club.mvr"')


def test_rig_check_on_a_live_show_from_another_thread(tmp_path: Path) -> None:
    path = club(tmp_path)
    with LiveShow(new_show("Club"), output=False) as live:
        found: list[RigCheck] = []
        reader = threading.Thread(target=lambda: found.append(live.rig_check(path)))
        reader.start()
        reader.join(5)
        assert [check.text for check in found] == [CHECK]
        assert live.show["fixtures"] == []
