"""``rig check`` and ``rig import``: a plot becomes the rig (MVR plan Phase 2, step 5).

``rig import "<path>"`` reads an MVR plot and adds, in one undo step, the
profiles of its GDTF files, the universes its addresses need, its fixtures
(number, name, patch, inverts, location and ``mvrUuid``), a group for each
hanging position, and the show's ``stage``: the plot's file, hash and frame.
``rig check`` says what it would do and changes nothing. The club plot below
hangs three spots on LX1 and two on LX2, drawn with the audience at −Y.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from builders import channel, mode, profile
from busk import CounterIds, LiveShow, OfflineShow, load_show, new_show
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
    plot,
    position,
    scene,
    scenery,
    spot,
)

PROFILE_ID = f"gdtf-{TYPE_ID.lower()}"


def club_scene(*extra: Any) -> bytes:
    lx1 = scenery("Truss", "t1", "LX1", at=matrix(o=(0, -2000, 6000)), children=[
        fixture("f101", "Spot 1", numeric=101, addresses=[("0", "1.1")],
                at=matrix(o=(2000, 0, 0)), position="P1"),
        fixture("f102", "Spot 2", numeric=102, addresses=[("0", "1.4")],
                position="P1", invert_pan="true"),
        fixture("f103", "Spot 3", numeric=103, addresses=[("0", "1.7")],
                at=matrix(o=(-2000, 0, 0)), position="P1"),
    ])  # fmt: skip
    lx2 = scenery("Truss", "t2", "LX2", at=matrix(o=(0, 0, 7000)), children=[
        fixture("f201", "Wash 1", fixture_id="201", numeric=0, gdtf_mode="1ch",
                addresses=[("0", "2.1")], at=matrix(o=(-1000, 0, 0)), position="P2"),
        fixture("f202", "", fixture_id="202", gdtf_mode="1ch", addresses=[("0", "514")],
                at=matrix(o=(1000, 0, 0)), position="P2"),
    ])  # fmt: skip
    return scene(
        layer("L1", "Lights", lx1, lx2, *extra),
        aux=[position("P1", "LX1"), position("P2", "LX2"), position("P3", "Floor")],
    )


def club(tmp_path: Path, data: bytes | None = None, files: dict[str, bytes] | None = None) -> Path:
    folder = tmp_path / "plots"
    folder.mkdir(exist_ok=True)
    return plot(folder / "club.mvr", data if data is not None else club_scene(), files)


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


# ------------------------------------------------------------------ refusals


def test_a_show_with_fixtures_from_a_plot_is_refused(tmp_path: Path) -> None:
    show = offline()
    run(show, f'rig import "{club(tmp_path)}"')
    before = copy.deepcopy(show.show)
    for verb in ("check", "import"):
        reply = show.execute(f'rig {verb} "{club(tmp_path)}"')
        assert (reply.ok, reply.text) == (False, "error: the show has fixtures from a plot "
                                                 "already: importing a plot again is not "
                                                 "supported yet")  # fmt: skip
    assert show.show == before


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
        ('rig import "a.mvr" ', ("audience", "origin"), (), True),
        ('rig import "a.mvr" audience ', ("-y", "+y", "-x", "+x"), (), False),
        ('rig import "a.mvr" audience +y ', ("origin",), (), True),
        ('rig import "a.mvr" origin ', (), ("a distance in mm",), False),
        ('rig import "a.mvr" origin 0 0 0 audience +y ', (), (), True),
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
