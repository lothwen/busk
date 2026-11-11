"""A fixture's mode and profile (GAP-26 of ``docs/dev/tui/engine-gaps.md``).

``fixture N mode <mode>`` takes another mode of the fixture's profile, and
``fixture N profile "<profile>" mode <mode>`` another profile, found as
``fixture add`` finds it, in one undo step with the embedding of a library
profile. Both leave the rest to the validator. No shipped profile has two
modes, so the rig below has its own, with three: the name of one needs quotes.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from builders import APPENDIX_A, ROOT, channel, fixture, load_doc, mode, profile, show, show_of
from busk import LiveShow, OfflineShow, ProfileLibrary, new_show
from busk.model.show import Show

CLUB_NIGHT = ROOT / "examples" / "club-night.busk"


def two_modes(revision: str = "1") -> dict[str, Any]:
    """A par of three modes: one channel, 20 channels, and four cells."""
    small = {**mode([channel(0, "intensity")], mode_id="mode-1"), "name": "One Channel"}
    wide = {**mode([channel(0, "intensity")], mode_id="mode-20", footprint=20), "name": "20ch"}
    cells = [channel(k, "intensity", element=k) for k in range(4)]
    bar = {**mode(cells, mode_id="mode-cells", elements=4), "name": "Cells"}
    return {**profile("prof-two", small, wide, bar), "name": "Two Mode Par", "revision": revision}


def rig() -> Show:
    """Fixtures 1 and 2 at 1.1 and 1.5, and 3 near the end of the universe."""
    return show_of(
        show(
            [two_modes()],
            [
                fixture("fx-1", 1, "prof-two", 1, mode_id="mode-1"),
                fixture("fx-2", 2, "prof-two", 5, mode_id="mode-1"),
                fixture("fx-3", 3, "prof-two", 505, mode_id="mode-1"),
            ],
        )
    )


def run(offline: OfflineShow, *lines: str) -> list[str]:
    texts = []
    for line in lines:
        reply = offline.execute(line)
        assert reply.ok, (line, reply.text)
        texts.append(reply.text)
    return texts


def refused(offline: OfflineShow, line: str, text: str) -> None:
    """``line`` fails, says ``text``, and leaves the show as it was."""
    before = offline.show
    reply = offline.execute(line)
    assert not reply.ok, reply.text
    assert text in reply.text
    assert offline.show == before


def elements(offline: OfflineShow) -> list[tuple[int, int]]:
    offline.tick(offline.time)
    output = offline.output
    assert output is not None
    return [(f.number, f.element) for f in output.fixtures]


# --------------------------------------------------------------------- mode


@pytest.mark.parametrize(
    ("word", "ident"),
    [
        ("20ch", "mode-20"),
        ("20CH", "mode-20"),
        ('"20ch"', "mode-20"),
        ("mode-20", "mode-20"),
        ("MODE-20", "mode-20"),
        ('"One Channel"', "mode-1"),
        ('"one channel"', "mode-1"),
        ("cells", "mode-cells"),
    ],
)
def test_a_mode_is_taken_by_name_or_id_in_any_case(word: str, ident: str) -> None:
    offline = OfflineShow(rig())
    run(offline, "fixture 3 patch 1.100")
    if ident == "mode-1":  # the mode it runs is refused
        run(offline, "fixture 1 mode Cells")
    run(offline, f"fixture 1 mode {word}")
    assert offline.show["fixtures"][0]["modeId"] == ident


def test_tab_offers_the_modes_of_the_fixtures_own_profile() -> None:
    assert OfflineShow(rig()).expected("fixture 1 mode ").words == (
        '"One Channel"',
        "20ch",
        "Cells",
    )


def test_a_mode_is_one_undo_step_and_the_output_follows() -> None:
    offline = OfflineShow(rig())
    assert elements(offline) == [(1, 1), (2, 1), (3, 1)]
    assert run(offline, "fixture 3 mode Cells") == ["fixture 3 runs Cells"]
    assert elements(offline) == [(1, 1), (2, 1), (3, 1), (3, 2), (3, 3), (3, 4)]
    assert run(offline, "undo") == ["undid: fixture 3 runs Cells"]
    assert offline.show == rig()
    assert elements(offline) == [(1, 1), (2, 1), (3, 1)]


@pytest.mark.parametrize("word", ['"One Channel"', '"one channel"', "MODE-1"])
def test_the_mode_a_fixture_runs_is_refused_and_spends_no_undo_step(word: str) -> None:
    offline = OfflineShow(rig())
    refused(offline, f"fixture 1 mode {word}", "error: fixture 1 already runs One Channel")
    assert offline.execute("undo").text == "error: nothing to undo"


def test_the_new_modes_channels_reach_the_frame() -> None:
    offline = OfflineShow(rig())
    run(offline, "fixture 3 mode Cells", "sel fixture 3.4", "set intensity 1")
    assert offline.tick(offline.time).universes[1][507] == 255  # 1.508, the fourth cell


def test_a_mode_past_channel_512_is_refused() -> None:
    offline = OfflineShow(rig())
    refused(offline, "fixture 3 mode 20ch", "past channel 512")
    reply = offline.execute("fixture 3 mode 20ch")
    assert reply.text == "error: fixture 3 would end at channel 524, past channel 512"


def test_a_mode_that_overlaps_warns_and_is_taken() -> None:
    offline = OfflineShow(rig())
    reply = offline.execute("fixture 1 mode 20ch")
    assert reply.ok, reply.text
    assert "fixture 1 runs 20ch" in reply.text
    assert "overlap" in reply.text


def test_a_mode_is_not_asked_about() -> None:
    assert OfflineShow(rig()).confirmation("fixture 1 mode Cells") is None
    assert OfflineShow(rig()).confirmation('fixture 1 profile "Two Mode Par" mode Cells') is None


@pytest.mark.parametrize(
    "line",
    ['record group 7 "Cell 4"', "record cue 1/1", "park fixture 3.4 intensity 0"],
)
def test_a_mode_is_refused_while_anything_names_an_element_it_lacks(line: str) -> None:
    offline = OfflineShow(rig())
    run(offline, "fixture 3 mode Cells", "sel fixture 3.4", "set intensity 0.5", line, "clear")
    refused(offline, 'fixture 3 mode "One Channel"', "does not exist")


def test_what_the_programmer_holds_on_a_lost_element_goes_dormant() -> None:
    offline = OfflineShow(rig())
    run(offline, "fixture 3 mode Cells", "sel fixture 3", "set intensity 1")
    assert len(offline.programmer.selection) == 4
    run(offline, 'fixture 3 mode "One Channel"')
    assert offline.programmer.selection == ((3, 1),)
    assert [value.element for value in offline.programmer.values] == [1]
    assert run(offline, "programmer") == [
        "selection: 3\nblind: off\nhighlight: off\nfade: 0 s\n  3 intensity = 1"
    ]
    assert elements(offline) == [(1, 1), (2, 1), (3, 1)]
    assert offline.tick(offline.time).universes[1][504] == 255
    run(offline, "undo")
    assert len(offline.programmer.selection) == 4
    assert run(offline, "programmer")[0].startswith("selection: 3.1, 3.2, 3.3, 3.4\n")


# ------------------------------------------------------------------ profile


def test_a_profile_the_show_holds_is_taken_in_one_undo_step() -> None:
    doc = load_doc(APPENDIX_A)
    offline = OfflineShow(show_of(doc))
    before = offline.show
    assert run(offline, 'fixture 201 profile "Generic Spot 16ch" mode 16ch') == [
        "fixture 201 runs Generic Spot 16ch, 16ch"
    ]
    par = next(f for f in offline.show["fixtures"] if f["number"] == 201)
    assert (par["profileId"], par["modeId"]) == ("prof-mh", "mode-16")
    assert [p["id"] for p in offline.show["profiles"]] == ["prof-mh", "prof-par"]
    assert run(offline, "undo") == ["undid: fixture 201 runs Generic Spot 16ch, 16ch"]
    assert offline.show == before


def test_a_library_profile_is_embedded_and_undo_takes_it_back() -> None:
    offline = OfflineShow(show_of(load_doc(APPENDIX_A)))
    before = offline.show
    line = 'fixture 201 profile "Stairville MH-X25 LED Spot" mode 12-channel'
    assert run(offline, line) == ["fixture 201 runs Stairville MH-X25 LED Spot, 12-channel"]
    assert [p["id"] for p in offline.show["profiles"]] == ["prof-mh", "prof-par", "prof-mhx25"]
    par = next(f for f in offline.show["fixtures"] if f["number"] == 201)
    assert (par["profileId"], par["profileRevision"], par["modeId"]) == (
        "prof-mhx25",
        offline.show["profiles"][2]["revision"],
        "mode-12ch",
    )
    run(offline, "undo")
    assert offline.show == before


def test_tab_offers_the_profiles_then_that_profiles_modes() -> None:
    offline = OfflineShow(rig())
    assert (
        offline.expected("fixture 1 profile ").words
        == (
            offline.expected("fixture add 900 ").words[1:]  # after `thru`
        )
    )
    assert offline.expected('fixture 1 profile "Two Mode Par" mode ').words == (
        '"One Channel"',
        "20ch",
        "Cells",
    )
    assert offline.expected('fixture 1 profile "RGB Par 3ch" mode ').words == ("3ch",)


def test_the_shows_copy_is_used_when_the_librarys_revision_differs(tmp_path: Path) -> None:
    (tmp_path / "two.json").write_text(json.dumps(two_modes(revision="2")))
    doc = load_doc(APPENDIX_A)
    doc["profiles"].append(two_modes())
    offline = OfflineShow(show_of(doc), library=ProfileLibrary([tmp_path]))
    reply = offline.execute('fixture 201 profile "Two Mode Par" mode 20ch')
    assert reply.ok, reply.text
    assert reply.text.splitlines() == [
        "warning: the show embeds 'Two Mode Par' revision '1', the library has '2': "
        "using the show's copy",
        "fixture 201 runs Two Mode Par, 20ch",
    ]
    par = next(f for f in offline.show["fixtures"] if f["number"] == 201)
    assert par["profileRevision"] == "1"
    assert len(offline.show["profiles"]) == 3


def test_a_fixture_records_the_revision_of_the_profile_it_takes(tmp_path: Path) -> None:
    (tmp_path / "two.json").write_text(json.dumps(two_modes(revision="7")))
    offline = OfflineShow(show_of(load_doc(APPENDIX_A)), library=ProfileLibrary([tmp_path]))
    reply = offline.execute('fixture 201 profile "Two Mode Par" mode 20ch')
    assert reply.text == "fixture 201 runs Two Mode Par, 20ch"  # no word of a drift
    par = next(f for f in offline.show["fixtures"] if f["number"] == 201)
    assert par["profileRevision"] == "7"


def test_the_profile_and_mode_a_fixture_runs_are_refused() -> None:
    offline = OfflineShow(rig())
    line = 'fixture 1 profile "Two Mode Par" mode "One Channel"'
    refused(offline, line, "error: fixture 1 already runs Two Mode Par, One Channel")
    assert offline.execute("undo").text == "error: nothing to undo"
    assert run(offline, 'fixture 1 profile "Two Mode Par" mode Cells') == [
        "fixture 1 runs Two Mode Par, Cells"
    ]


def test_the_same_profile_is_taken_when_the_fixture_is_behind_its_revision() -> None:
    """A fixture patched with an older revision than the show embeds (a show
    file can hold one, with a warning): the line brings it to the show's."""
    doc = show(
        [two_modes(revision="2")],
        [fixture("fx-1", 1, "prof-two", 1, mode_id="mode-1")],  # revision "1"
    )
    offline = OfflineShow(show_of(doc))
    line = 'fixture 1 profile "Two Mode Par" mode "One Channel"'
    assert run(offline, line) == ["fixture 1 runs Two Mode Par, One Channel"]
    assert offline.show["fixtures"][0]["profileRevision"] == "2"
    refused(offline, line, "already runs")


def test_the_same_profile_is_refused_when_only_the_library_is_newer(tmp_path: Path) -> None:
    """The line takes the show's copy (``profile update`` brings the
    library's), so it would change nothing."""
    (tmp_path / "two.json").write_text(json.dumps(two_modes(revision="2")))
    offline = OfflineShow(rig(), library=ProfileLibrary([tmp_path]))
    line = 'fixture 1 profile "Two Mode Par" mode "One Channel"'
    refused(offline, line, "error: fixture 1 already runs Two Mode Par, One Channel")


def test_a_profile_past_channel_512_is_refused_and_embeds_nothing() -> None:
    offline = OfflineShow(rig())
    refused(
        offline,
        'fixture 3 profile "Generic Spot 16ch" mode 16ch',
        "past channel 512",
    )
    reply = offline.execute('fixture 3 profile "Generic Spot 16ch" mode 16ch')
    assert reply.text == "error: fixture 3 would end at channel 520, past channel 512"


def test_a_bar_is_refused_while_groups_name_its_elements(tmp_path: Path) -> None:
    path = tmp_path / "club.show"
    offline = OfflineShow(new_show("Club Night"), path=path)
    offline.run_script(CLUB_NIGHT)
    refused(offline, 'fixture 301 profile "RGB Par 3ch" mode 3ch', "does not exist")


def test_what_a_new_profile_cannot_do_is_kept_and_does_nothing() -> None:
    """A spot goes to a par: its tilt limit warns and its presets stay."""
    offline = OfflineShow(show_of(load_doc(APPENDIX_A)))
    presets = offline.show["presets"]
    reply = offline.execute('fixture 101 profile "RGB Par 3ch" mode 3ch')
    assert reply.ok, reply.text
    assert "tilt" in reply.text
    assert offline.show["presets"] == presets
    assert offline.show["fixtures"][0]["limits"] == {"tilt": (-120, 120)}


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("fixture 1 mode", "expected a mode name"),
        ("fixture 1 mode nope", "profile 'Two Mode Par' has no mode 'nope'"),
        ("fixture 1 mode 20ch now", "unexpected 'now'"),
        ("fixture 9 mode 20ch", "no fixture 9"),
        ("fixture 1.1 mode 20ch", "expected a fixture number, got '1.1'"),
        ("fixture 1 profile", "expected a profile name in quotes"),
        ('fixture 1 profile "Nope" mode 20ch', "no profile 'Nope' in the library"),
        ('fixture 1 profile "RGB Par 3ch"', "expected mode"),
        ('fixture 1 profile "RGB Par 3ch" 3ch', "expected mode, got '3ch'"),
        ('fixture 1 profile "RGB Par 3ch" mode', "expected a mode name"),
        ('fixture 1 profile "RGB Par 3ch" mode 9ch', "profile 'RGB Par 3ch' has no mode '9ch'"),
        ('fixture 1 profile "RGB Par 3ch" mode 3ch now', "unexpected 'now'"),
        ('fixture 9 profile "RGB Par 3ch" mode 3ch', "no fixture 9"),
    ],
)
def test_the_lines_say_what_is_wrong(line: str, error: str) -> None:
    refused(OfflineShow(rig()), line, error)


def test_the_generic_edit_of_the_mode_id_still_works() -> None:
    offline = OfflineShow(rig())
    run(offline, 'fixture 1 modeId "mode-cells"')
    assert offline.show["fixtures"][0]["modeId"] == "mode-cells"


# ------------------------------------------------------- a running show


def eventually(test: Callable[[], bool], within: float = 5.0) -> None:
    deadline = time.monotonic() + within
    while not test():
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_a_running_show_follows_a_profile_and_undo() -> None:
    running = show_of(load_doc(APPENDIX_A))
    with LiveShow(running, output=False) as live:

        def seen() -> dict[int, int]:
            output = live.output
            return {} if output is None else {f.number: f.element for f in output.fixtures}

        eventually(lambda: seen() == {101: 1, 102: 1, 201: 1})
        line = 'fixture 201 profile "Chauvet DJ COLORband PiX" mode 36-CH'
        assert live.execute(line).ok
        eventually(lambda: seen() == {101: 1, 102: 1, 201: 12})
        assert live.execute("undo").ok
        eventually(lambda: seen() == {101: 1, 102: 1, 201: 1})
        assert live.show == running
