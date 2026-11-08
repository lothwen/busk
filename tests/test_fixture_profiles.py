"""The fixture profiles ``fixture add`` takes (GAP-27 of ``docs/dev/tui/engine-gaps.md``).

``OfflineShow.fixture_profiles`` and ``LiveShow.fixture_profiles`` list every
profile ``fixture add N "<name>"`` takes, as
:class:`~busk.console.console.FixtureProfileInfo`: the show's in show order,
then the profile library's that the show has no copy of, each once, with its
modes. So a frontend can place a fixture before ``fixture add`` embeds its
profile, which ``expected()`` cannot help with: it gives names, not
footprints. The contract: ``fixture add`` with a listed name and mode uses that
profile, embeds it exactly when it is the library's, and takes the footprint
listed. Appendix A's show holds two of the library's profiles; the variants
below rename one, shadow a library profile, and repeat a name.
"""

from __future__ import annotations

import copy
import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from builders import APPENDIX_A, ROOT, channel, load_doc, mode, profile, show_of
from busk import (
    FixtureModeInfo,
    FixtureProfileInfo,
    LiveShow,
    OfflineShow,
    ProfileLibrary,
    load_show,
    new_show,
)
from busk.console.parser import Context, ImportProfile, parse
from busk.model.show import Show
from busk.persistence.show_file import save_show
from busk.session.ids import CounterIds
from gdtf_builder import archive, description, function
from gdtf_builder import channel as gdtf_channel
from gdtf_builder import mode as gdtf_mode

CLUB_NIGHT = ROOT / "examples" / "club-night.busk"
TUPPER_DEMO = ROOT / "examples" / "tupperdmx" / "tupper-demo.show"

PIX = FixtureProfileInfo(
    name="Chauvet DJ COLORband PiX",
    id="prof-pix",
    source="library",
    manufacturer="Chauvet DJ",
    revision="1",
    library_revision="1",
    modes=(FixtureModeInfo(name="36-CH", footprint=36, elements=12),),
)
ML56 = FixtureProfileInfo(
    name="Eurolite LED ML-56 RGBW",
    id="prof-ml56",
    source="library",
    manufacturer="Eurolite",
    revision="1",
    library_revision="1",
    modes=(FixtureModeInfo(name="4-channel", footprint=4, elements=1),),
)
PAR = FixtureProfileInfo(
    name="RGB Par 3ch",
    id="prof-par",
    source="library",
    manufacturer="Generic",
    revision="1",
    library_revision="1",
    modes=(FixtureModeInfo(name="3ch", footprint=3, elements=1),),
)
SPOT = FixtureProfileInfo(
    name="Generic Spot 16ch",
    id="prof-mh",
    source="library",
    manufacturer="Generic",
    revision="1",
    library_revision="1",
    modes=(FixtureModeInfo(name="16ch", footprint=16, elements=1),),
)
MHX25 = FixtureProfileInfo(
    name="Stairville MH-X25 LED Spot",
    id="prof-mhx25",
    source="library",
    manufacturer="Stairville",
    revision="1",
    library_revision="1",
    modes=(FixtureModeInfo(name="12-channel", footprint=12, elements=1),),
)
LIBRARY = (PIX, ML56, PAR, SPOT, MHX25)
"""A new show's: the built-in library, in its order."""


def held(info: FixtureProfileInfo) -> FixtureProfileInfo:
    """``info`` as the show lists it once it holds a copy."""
    return FixtureProfileInfo(
        name=info.name,
        id=info.id,
        source="show",
        manufacturer=info.manufacturer,
        revision=info.revision,
        library_revision=info.library_revision,
        modes=info.modes,
    )


LISTED = (held(SPOT), held(PAR), PIX, ML56, MHX25)
"""Appendix A's: its two, then the rest of the library, in its order."""


def appendix(*profiles: dict[str, Any], rename: str | None = None, first: bool = False) -> Show:
    """Appendix A's show, with its spot renamed and ``profiles`` added after
    its own (or before them, ``first``)."""
    doc = load_doc(APPENDIX_A)
    if rename is not None:
        doc["profiles"][0]["name"] = rename
    added = list(profiles)
    doc["profiles"] = added + doc["profiles"] if first else doc["profiles"] + added
    return show_of(doc)


def own(ident: str, name: str) -> dict[str, Any]:
    """A profile of the show's own, of one 2-channel mode ``2ch``."""
    two = {**mode([channel(0, "intensity"), channel(1, "pan")], mode_id="mode-2"), "name": "2ch"}
    return {**profile(ident, two), "name": name}


def names(profiles: tuple[FixtureProfileInfo, ...]) -> list[tuple[str, str]]:
    return [(p.name, p.source) for p in profiles]


def offered(show: OfflineShow) -> list[str]:
    """The names ``expected`` offers after ``fixture add 900``, without its ``thru``."""
    words = show.expected("fixture add 900 ").words
    assert words[0] == "thru"
    return [json.loads(word) for word in words[1:]]


# ----------------------------------------------------------------- the list


def test_a_new_show_lists_the_library_in_its_order() -> None:
    assert OfflineShow(new_show("Empty")).fixture_profiles == LIBRARY


def test_the_shows_profiles_come_first_then_the_librarys_it_has_no_copy_of() -> None:
    assert OfflineShow(show_of(load_doc(APPENDIX_A))).fixture_profiles == LISTED


def test_a_mode_says_what_it_takes() -> None:
    (bar,) = [p for p in OfflineShow(new_show("Empty")).fixture_profiles if p.id == "prof-pix"]
    assert bar.modes == (FixtureModeInfo(name="36-CH", footprint=36, elements=12),)


def test_every_mode_of_a_profile_is_listed_in_its_order() -> None:
    wide = {**mode([channel(0, "intensity")], mode_id="mode-20", footprint=20), "name": "20 ch"}
    cells = [channel(k, "intensity", element=k) for k in range(4)]
    bar = {**mode(cells, mode_id="mode-cells", elements=4), "name": "Cells"}
    doc = {**profile("prof-two", wide, bar), "name": "Two", "manufacturer": "Test"}
    listed = OfflineShow(appendix(doc)).fixture_profiles[2]
    assert listed == FixtureProfileInfo(
        name="Two",
        id="prof-two",
        source="show",
        manufacturer="Test",
        revision="1",
        library_revision=None,
        modes=(
            FixtureModeInfo(name="20 ch", footprint=20, elements=1),
            FixtureModeInfo(name="Cells", footprint=4, elements=4),
        ),
    )


def test_a_library_directory_is_listed_after_the_built_in_ones(tmp_path: Path) -> None:
    (tmp_path / "extra.json").write_text(json.dumps(own("prof-extra", "Extra")))
    show = OfflineShow(new_show("Empty"), library=ProfileLibrary([tmp_path]))
    assert names(show.fixture_profiles)[:5] == names(LIBRARY)
    assert names(show.fixture_profiles)[5:] == [("Extra", "library")]
    assert offered(show) == [p.name for p in show.fixture_profiles]


@pytest.fixture(scope="module")
def club_show(tmp_path_factory: pytest.TempPathFactory) -> Show:
    path = tmp_path_factory.mktemp("club") / "club.show"
    OfflineShow(new_show("Club Night"), path=path).run_script(CLUB_NIGHT)
    return load_show(path)[0]


@pytest.mark.parametrize("extra", [False, True], ids=["built-in", "with a library directory"])
@pytest.mark.parametrize("which", ["club", "tupper"])
def test_the_names_are_those_tab_offers_on_both_shows(
    which: str, extra: bool, club_show: Show, tmp_path: Path
) -> None:
    (tmp_path / "extra.json").write_text(json.dumps(own("prof-extra", "Extra")))
    library = ProfileLibrary([tmp_path] if extra else [])
    doc = copy.deepcopy(club_show) if which == "club" else load_show(TUPPER_DEMO)[0]
    show = OfflineShow(doc, library=library)
    assert [p.name for p in show.fixture_profiles] == offered(show)
    assert ("Extra" in offered(show)) is extra
    shows = [p["name"] for p in show.show["profiles"]]
    listed = show.fixture_profiles
    assert [p.name for p in listed if p.source == "show"] == shows
    assert [p.source for p in listed] == ["show"] * len(shows) + ["library"] * (
        len(listed) - len(shows)
    )


def test_a_renamed_copy_of_a_library_profile_is_listed_once_by_its_new_name() -> None:
    show = OfflineShow(appendix(rename="Our Spot"))
    assert names(show.fixture_profiles)[:2] == [("Our Spot", "show"), ("RGB Par 3ch", "show")]
    assert "Generic Spot 16ch" not in [p.name for p in show.fixture_profiles]
    assert len(show.fixture_profiles) == len(LISTED)


def test_a_show_profile_named_like_a_library_one_takes_its_place() -> None:
    listed = OfflineShow(appendix(own("prof-mine", "stairville mh-x25 led spot"))).fixture_profiles
    assert ("stairville mh-x25 led spot", "show") in names(listed)
    assert "prof-mhx25" not in [p.id for p in listed]
    assert len(listed) == len(LISTED)


def test_a_name_an_earlier_profile_answers_to_is_not_listed_again() -> None:
    listed = OfflineShow(appendix(own("prof-a", "Twin"), own("prof-b", "twin"))).fixture_profiles
    assert [p.id for p in listed if p.name.casefold() == "twin"] == ["prof-a"]


def test_a_profile_is_listed_under_the_first_name_that_finds_it() -> None:
    """``fixture add N "Twin"`` takes the first Twin, ``fixture add N "Generic
    Spot 16ch"`` the show's copy of it, renamed Twin."""
    listed = OfflineShow(appendix(own("prof-mine", "Twin"), rename="Twin", first=True))
    assert [(p.name, p.id) for p in listed.fixture_profiles if p.source == "show"] == [
        ("Twin", "prof-mine"),
        ("RGB Par 3ch", "prof-par"),
        ("Generic Spot 16ch", "prof-mh"),
    ]


def test_a_profile_no_name_finds_is_left_out() -> None:
    """Its name is an earlier profile's id, so ``fixture add`` takes that one."""
    listed = OfflineShow(appendix(own("prof-b", "Second"), own("prof-a", "prof-b")))
    ids = [p.id for p in listed.fixture_profiles]
    assert "prof-b" in ids
    assert "prof-a" not in ids


def test_an_own_profile_named_like_the_library_one_a_renamed_copy_holds() -> None:
    """The copy has the library's id, so the library's name finds the copy
    when it comes first, and the show's own profile of that name no name finds."""
    listed = OfflineShow(
        appendix(own("prof-mine", "Generic Spot 16ch"), rename="Our Spot")
    ).fixture_profiles
    assert [p.id for p in listed if p.source == "show"] == ["prof-mh", "prof-par"]
    first = OfflineShow(
        appendix(own("prof-mine", "Generic Spot 16ch"), rename="Our Spot", first=True)
    ).fixture_profiles
    assert [(p.name, p.id) for p in first[:2]] == [
        ("Generic Spot 16ch", "prof-mine"),
        ("Our Spot", "prof-mh"),
    ]


# ----------------------------------------------------------------- the contract

SHOWS: dict[str, Callable[[], Show]] = {
    "new": lambda: new_show("Empty"),
    "appendix": appendix,
    "renamed": lambda: appendix(rename="Our Spot"),
    "shadowed": lambda: appendix(own("prof-mine", "stairville mh-x25 led spot")),
    "repeated": lambda: appendix(own("prof-a", "Twin"), own("prof-b", "twin")),
    "taken name": lambda: appendix(own("prof-mine", "Twin"), rename="Twin", first=True),
    "own first": lambda: appendix(own("prof-mine", "Generic Spot 16ch"), rename="S", first=True),
    "own after": lambda: appendix(own("prof-mine", "Generic Spot 16ch"), rename="S"),
}


@pytest.mark.parametrize("variant", SHOWS)
def test_fixture_add_takes_each_listed_name_and_mode_as_listed(variant: str) -> None:
    for listed in OfflineShow(SHOWS[variant]()).fixture_profiles:
        for each in listed.modes:
            show = OfflineShow(SHOWS[variant]())
            before = [p["id"] for p in show.show["profiles"]]
            reply = show.execute(f'fixture add 900 "{listed.name}" mode "{each.name}"')
            assert reply.ok, (listed, reply.text)
            added = show.show["fixtures"][-1]
            assert added["profileId"] == listed.id
            embedded = [] if listed.source == "show" else [listed.id]
            assert [p["id"] for p in show.show["profiles"]] == before + embedded
            profile_ = next(p for p in show.show["profiles"] if p["id"] == listed.id)
            used = next(m for m in profile_["modes"] if m["id"] == added["modeId"])
            assert used["name"] == each.name
            assert used["footprint"] == each.footprint
            assert len(used["elements"]) == each.elements
            assert profile_["manufacturer"] == listed.manufacturer


def test_adding_a_library_profile_moves_it_to_the_shows() -> None:
    show = OfflineShow(show_of(load_doc(APPENDIX_A)))
    assert show.execute('fixture add 900 "Eurolite LED ML-56 RGBW" mode 4-channel').ok
    assert show.fixture_profiles == (held(SPOT), held(PAR), held(ML56), PIX, MHX25)
    show.execute("undo")
    assert show.fixture_profiles == LISTED


def test_a_fixture_moved_to_a_library_profile_makes_it_the_shows() -> None:
    show = OfflineShow(show_of(load_doc(APPENDIX_A)))
    assert show.execute('fixture 201 profile "Stairville MH-X25 LED Spot" mode 12-channel').ok
    assert show.fixture_profiles == (held(SPOT), held(PAR), held(MHX25), PIX, ML56)


# -------------------------------------------------------------- the reads


def test_the_same_tuple_until_a_profile_changes() -> None:
    show = OfflineShow(show_of(load_doc(APPENDIX_A)))
    first = show.fixture_profiles
    assert show.fixture_profiles is first
    show.execute("fader 1 1")  # no edit
    assert show.fixture_profiles is first
    shown = show.show
    show.execute("sel fixture 101")
    show.execute('record group 7 "Seven"')  # an edit that leaves the profiles as they were
    assert show.show is not shown
    assert show.fixture_profiles is first
    show.execute('fixture add 900 "Eurolite LED ML-56 RGBW" mode 4-channel')
    assert show.fixture_profiles is not first
    assert show.fixture_profiles != first


def test_a_live_show_lists_them_before_it_starts_and_from_another_thread() -> None:
    live = LiveShow(show_of(load_doc(APPENDIX_A)), output=False)
    assert live.fixture_profiles == LISTED
    with live:
        assert live.execute('fixture add 900 "RGB Par 3ch" mode 3ch').ok  # the show's already
        assert live.execute('fixture add 901 "Chauvet DJ COLORband PiX" mode 36-CH').ok
        read: list[tuple[FixtureProfileInfo, ...]] = []
        reader = threading.Thread(target=lambda: read.append(live.fixture_profiles))
        reader.start()
        reader.join()
    assert names(read[0])[:3] == [
        ("Generic Spot 16ch", "show"),
        ("RGB Par 3ch", "show"),
        ("Chauvet DJ COLORband PiX", "show"),
    ]
    assert read[0] is live.fixture_profiles


def test_a_saved_show_lists_the_same_after_loading(tmp_path: Path) -> None:
    show = OfflineShow(show_of(load_doc(APPENDIX_A)))
    show.execute('fixture add 900 "Stairville MH-X25 LED Spot" mode 12-channel')
    path = tmp_path / "saved.show"
    save_show(show.show, path)
    loaded, _ = load_show(path)
    assert OfflineShow(loaded).fixture_profiles == show.fixture_profiles


# ------------------------------------------------- the revisions (GAP-39)


def listed(show: OfflineShow, name: str) -> FixtureProfileInfo:
    return next(p for p in show.fixture_profiles if p.name == name)


def with_revision(ident: str, revision: str) -> Show:
    """Appendix A's show, its copy of profile ``ident`` at ``revision``."""
    doc = load_doc(APPENDIX_A)
    next(p for p in doc["profiles"] if p["id"] == ident)["revision"] = revision
    return show_of(doc)


def test_a_library_profile_lists_the_librarys_revision_twice() -> None:
    info = listed(OfflineShow(new_show("Rig")), "RGB Par 3ch")
    assert (info.source, info.revision, info.library_revision) == ("library", "1", "1")


def test_a_profile_at_the_librarys_revision_has_nothing_to_update() -> None:
    show = OfflineShow(appendix())
    info = listed(show, "RGB Par 3ch")
    assert (info.source, info.revision, info.library_revision) == ("show", "1", "1")
    assert "already at the library" in show.execute('profile update "RGB Par 3ch"').text


def test_a_revision_that_differs_says_profile_update_has_work() -> None:
    show = OfflineShow(with_revision("prof-par", "7"))
    info = listed(show, "RGB Par 3ch")
    assert (info.source, info.revision, info.library_revision) == ("show", "7", "1")
    assert show.execute('profile update "RGB Par 3ch"').ok
    updated = listed(show, "RGB Par 3ch")
    assert updated.revision == updated.library_revision == "1"


def test_a_profile_only_the_show_holds_has_no_library_revision() -> None:
    show = OfflineShow(appendix(own("prof-own", "Own")))
    assert listed(show, "Own").library_revision is None
    assert "no library profile" in show.execute('profile update "Own"').text


# ---------------------------------------------- importing a profile (GAP-39)


def gdtf_spot() -> bytes:
    """A GDTF fixture of a dimmer and a control channel busk has no attribute for."""
    channels = (gdtf_channel("1", function("Dimmer")), gdtf_channel("2", function("Control1")))
    return description(gdtf_mode("2ch", *channels), name="Spot", manufacturer="Generic")


def gdtf_file(tmp_path: Path) -> tuple[Path, str]:
    return archive(tmp_path / "spot.gdtf", gdtf_spot()), "Generic Spot"


def ofl_file(tmp_path: Path) -> tuple[Path, str]:
    folder = tmp_path / "acme"
    folder.mkdir()
    file = folder / "dim.json"
    channels = {"Dimmer": {"capability": {"type": "Intensity"}}}
    fixture = {
        "name": "Test",
        "meta": {"lastModifyDate": "2026-01-02"},
        "availableChannels": channels,
        "modes": [{"name": "All", "channels": list(channels)}],
    }
    file.write_text(json.dumps(fixture))
    return file, "acme Test"


def busk_file(tmp_path: Path) -> tuple[Path, str]:
    file = tmp_path / "own.json"
    file.write_text(json.dumps(own("prof-own", "Own")))
    return file, "Own"


FORMATS = [gdtf_file, ofl_file, busk_file]
FORMAT_IDS = ["gdtf", "ofl", "busk"]


@pytest.mark.parametrize("make", FORMATS, ids=FORMAT_IDS)
def test_a_file_of_each_format_is_embedded_in_one_undo_step(
    make: Callable[[Path], tuple[Path, str]], tmp_path: Path
) -> None:
    file, name = make(tmp_path)
    show = OfflineShow(appendix())
    before = copy.deepcopy(show.show["profiles"])
    reply = show.execute(f'profile import "{file}"')
    assert reply.ok, reply.text
    assert reply.text.splitlines()[-1] == f"imported profile {name!r}"
    assert [p["name"] for p in show.show["profiles"]][-1] == name
    info = listed(show, name)
    assert (info.source, info.library_revision) == ("show", None)
    assert show.execute("undo").text == f"undid: imported profile {name!r}"
    assert show.show["profiles"] == before
    assert all(p.name != name for p in show.fixture_profiles)


def test_the_importers_notes_are_said(tmp_path: Path) -> None:
    file, _ = gdtf_file(tmp_path)
    reply = OfflineShow(appendix()).execute(f'profile import "{file}"')
    assert reply.ok
    assert (
        reply.text.splitlines()[0]
        == "note: Beam_Control1: no busk attribute (Control1); held at DMX 0"
    )


def test_fixture_add_takes_the_imported_profile_by_name(tmp_path: Path) -> None:
    file, name = busk_file(tmp_path)
    show = OfflineShow(appendix())
    assert show.execute(f'profile import "{file}"').ok
    assert json.dumps(name) in show.expected("fixture add 900 ").words
    assert show.execute(f'fixture add 900 "{name}" mode 2ch at 1.300').ok
    assert show.show["fixtures"][-1]["profileId"] == "prof-own"


def test_an_imported_profile_is_saved_and_reloaded(tmp_path: Path) -> None:
    file, name = busk_file(tmp_path)
    show = OfflineShow(appendix())
    path = tmp_path / "saved.show"
    assert show.execute(f'profile import "{file}"').ok
    assert show.execute(f'save "{path}"').ok
    assert listed(OfflineShow(load_show(path)[0]), name).source == "show"


def bad_files(tmp_path: Path) -> dict[str, Path]:
    missing = tmp_path / "missing"
    bad = {
        "bad.json": tmp_path / "bad.json",
        "not-a-profile.json": tmp_path / "not-a-profile.json",
        "bad.gdtf": tmp_path / "bad.gdtf",
    }
    bad["bad.json"].write_text("{")
    bad["not-a-profile.json"].write_text(json.dumps({"id": "x"}))
    bad["bad.gdtf"].write_bytes(b"not a zip")
    return {**bad, "missing.json": missing / "m.json", "missing.gdtf": missing / "m.gdtf",
            "a folder": tmp_path}  # fmt: skip


@pytest.mark.parametrize(
    "which",
    ["bad.json", "not-a-profile.json", "bad.gdtf", "missing.json", "missing.gdtf", "a folder"],
)
def test_a_file_that_fails_says_so_in_one_line_and_changes_nothing(
    which: str, tmp_path: Path
) -> None:
    file = bad_files(tmp_path)[which]
    show = OfflineShow(appendix())
    before = copy.deepcopy(show.show)
    reply = show.execute(f'profile import "{file}"')
    assert not reply.ok
    assert reply.text.startswith(f"error: cannot import {str(file)!r}: ")
    assert "\n" not in reply.text
    assert show.show == before


def test_an_id_the_show_holds_is_refused(tmp_path: Path) -> None:
    file = tmp_path / "again.json"
    file.write_text(json.dumps(own("prof-own", "Another name")))
    show = OfflineShow(appendix(own("prof-own", "Own")))
    before = copy.deepcopy(show.show)
    reply = show.execute(f'profile import "{file}"')
    assert (reply.ok, reply.text) == (False, "error: the show holds this profile as 'Own'")
    assert show.show == before


@pytest.mark.parametrize("name", ["Own", "OWN"])
def test_a_name_the_show_holds_is_refused_in_any_case(name: str, tmp_path: Path) -> None:
    """``fixture add`` would never find it by that name."""
    file = tmp_path / "twin.json"
    file.write_text(json.dumps(own("prof-twin", name)))
    show = OfflineShow(appendix(own("prof-own", "Own")))
    reply = show.execute(f'profile import "{file}"')
    assert (reply.ok, reply.text) == (False, "error: the show has a profile named 'Own'")


def test_a_name_only_the_library_holds_takes_its_place(tmp_path: Path) -> None:
    file = tmp_path / "shadow.json"
    file.write_text(json.dumps(own("prof-shadow", "Stairville MH-X25 LED Spot")))
    show = OfflineShow(appendix())
    assert show.execute(f'profile import "{file}"').ok
    info = listed(show, "Stairville MH-X25 LED Spot")
    assert (info.id, info.source) == ("prof-shadow", "show")


def test_an_import_asks_nothing(tmp_path: Path) -> None:
    file, _ = busk_file(tmp_path)
    assert OfflineShow(appendix()).confirmation(f'profile import "{file}"') is None


@pytest.mark.parametrize("path", ["nope.gdtf", "with space/nope.json"])
def test_the_parser_names_the_file_and_reads_nothing(path: str) -> None:
    context = Context(appendix(), ProfileLibrary(), CounterIds())
    assert parse(f'profile import "{path}"', context) == ImportProfile(Path(path))


def test_a_library_directory_still_reports_what_a_file_says(tmp_path: Path) -> None:
    """``ProfileLibrary`` reads through the same function as the line."""
    (tmp_path / "bad.json").write_text("{")
    archive(tmp_path / "spot.gdtf", gdtf_spot())
    library = ProfileLibrary([tmp_path], builtin=False)
    assert [p["name"] for p in library] == ["Generic Spot"]
    assert any(line.startswith(f"{tmp_path / 'bad.json'}: ") for line in library.problems)
    assert any("Beam_Control1" in line for line in library.problems)
