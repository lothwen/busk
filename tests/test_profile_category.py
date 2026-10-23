"""Fixture categories (GAP-16 of ``docs/dev/tui/engine-gaps.md``).

A profile may have a ``category`` (:data:`~busk.model.profile.ProfileCategory`),
for a display to group and draw fixtures by kind. Checked here:

* the vocabulary, and that the show file and the library refuse anything else;
* the built-in profiles' categories, embedded by ``fixture add``;
* the OFL import: every OFL category, the first one busk knows wins, a moving
  head or scanner is a ``spot`` with a gobo wheel and a ``wash`` without, the
  user's TupperDMX files; the GDTF import, whose format has none;
* ``profile "<name>" category <category>|none``: what it submits, its errors,
  one undo step, no new revision and the same DMX, ``list profiles``;
* ``profile update`` keeps the show's category, or takes the library's when
  the show's copy has none;
* a ``LiveShow`` and a saved show. ``busk run --frontend`` reads it in
  ``tests/test_frontend.py``; completion is in ``tests/test_console_prompt.py``.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from builders import APPENDIX_A, ROOT, load_doc, show_of
from busk import LiveShow, OfflineShow, ProfileLibrary, load_show, new_show, validate_show
from busk.console.parser import HELP, ParseError, Submit, parse
from busk.importers.gdtf import import_gdtf
from busk.importers.ofl import CATEGORIES, import_ofl, read_ofl
from busk.model.profile import PROFILE_CATEGORIES
from busk.persistence.show_file import save_show
from busk.session.library import builtin_directory
from test_console_parser import p7_context
from test_gdtf import bar, spot
from test_ofl import OFL, ofl, one

SPOT = ["profiles", {"id": "prof-mh"}, "category"]
PAR = ["profiles", {"id": "prof-par"}, "category"]


def appendix() -> OfflineShow:
    """Appendix A's show: a Generic Spot 16ch and an RGB Par 3ch, neither
    with a category (it predates them)."""
    return OfflineShow(show_of(load_doc(APPENDIX_A)))


def categories(show: OfflineShow | LiveShow) -> dict[str, str | None]:
    return {p["name"]: p.get("category") for p in show.show["profiles"]}


# ------------------------------------------------------------------ the vocabulary


def test_the_categories() -> None:
    assert PROFILE_CATEGORIES == (
        "par", "spot", "wash", "beam", "pixel", "strobe", "blinder", "dimmer", "effect", "fog",
        "other",
    )  # fmt: skip
    start = next(k for k, line in enumerate(HELP) if line.strip().startswith("<category> ="))
    words = " ".join(HELP[start : start + 2]).split("=", 1)[1].replace("|", " ").split()
    assert tuple(words) == PROFILE_CATEGORIES  # help lists every one, in order


def test_a_show_file_takes_a_category_and_refuses_an_unknown_one() -> None:
    doc = load_doc(APPENDIX_A)
    doc["profiles"][0]["category"] = "spot"
    show, issues = validate_show(json.dumps(doc).encode())
    assert show is not None, issues
    assert show["profiles"][0]["category"] == "spot"
    doc["profiles"][0]["category"] = "spotlight"
    show, issues = validate_show(json.dumps(doc).encode())
    assert show is None
    assert [issue.path for issue in issues] == ["profiles[0].category"]


def test_a_library_profile_with_an_unknown_category_is_skipped(tmp_path: Path) -> None:
    profile = json.loads((builtin_directory() / "generic-spot-16ch.json").read_text("utf-8"))
    (tmp_path / "good.json").write_text(json.dumps({**profile, "category": "beam"}))
    (tmp_path / "bad.json").write_text(json.dumps({**profile, "id": "x", "category": "mover"}))
    library = ProfileLibrary([tmp_path], builtin=False)
    assert [p["category"] for p in library] == ["beam"]
    assert len(library.problems) == 1
    assert "bad.json" in library.problems[0]
    assert "category" in library.problems[0]


# ------------------------------------------------------------------ the built-in library


def test_the_built_in_profiles_have_categories() -> None:
    assert {p["name"]: p.get("category") for p in ProfileLibrary()} == {
        "Chauvet DJ COLORband PiX": "pixel",
        "Eurolite LED ML-56 RGBW": "par",
        "RGB Par 3ch": "par",
        "Generic Spot 16ch": "spot",
        "Stairville MH-X25 LED Spot": "spot",
    }
    assert {p["revision"] for p in ProfileLibrary()} == {"1"}  # a label is no new revision


def test_fixture_add_embeds_the_category(tmp_path: Path) -> None:
    show = OfflineShow(new_show("Club Night"), path=tmp_path / "club.show")
    show.run_script(ROOT / "examples" / "club-night.busk")
    assert categories(show) == {
        "Generic Spot 16ch": "spot",
        "Eurolite LED ML-56 RGBW": "par",
        "Chauvet DJ COLORband PiX": "pixel",
    }


# ------------------------------------------------------------------ the importers


def ofl_category(*names: object, gobo: bool = False) -> str | None:
    """The category of an OFL dimmer whose ``categories`` are ``names``, with
    a gobo wheel when ``gobo``."""
    extra: dict[str, Any] = {"categories": list(names)}
    if gobo:
        slots = [{"type": "Open"}, {"type": "Gobo", "name": "Dots"}]
        extra["wheels"] = {"Gobo Wheel": {"slots": slots}}
    data = ofl({"Dimmer": one({"type": "Intensity"})}, **extra)
    return import_ofl(data, manufacturer="Test", key="test").profile.get("category")


@pytest.mark.parametrize(
    ("ofl_name", "category"),
    [
        ("Barrel Scanner", "effect"),
        ("Blinder", "blinder"),
        ("Color Changer", "par"),
        ("Dimmer", "dimmer"),
        ("Effect", "effect"),
        ("Fan", "other"),
        ("Flower", "effect"),
        ("Hazer", "fog"),
        ("Laser", "effect"),
        ("Matrix", "pixel"),
        ("Other", "other"),
        ("Pixel Bar", "pixel"),
        ("Smoke", "fog"),
        ("Stand", "other"),
        ("Strobe", "strobe"),
    ],
)
def test_each_ofl_category(ofl_name: str, category: str) -> None:
    assert ofl_category(ofl_name) == category
    assert ofl_category(ofl_name, gobo=True) == category  # the gobo rule is for movers only


@pytest.mark.parametrize("ofl_name", ["Moving Head", "Scanner"])
def test_a_mover_is_a_spot_with_a_gobo_wheel_and_a_wash_without(ofl_name: str) -> None:
    assert ofl_category(ofl_name, gobo=True) == "spot"
    assert ofl_category(ofl_name) == "wash"


def test_the_table_covers_every_ofl_category() -> None:
    assert len(CATEGORIES) == 17  # OFL's schema: 17 categories
    assert set(CATEGORIES.values()) <= set(PROFILE_CATEGORIES) - {"wash", "beam"}


def test_the_first_category_busk_knows_wins() -> None:
    assert ofl_category("Pixel Bar", "Color Changer", "Strobe") == "pixel"
    assert ofl_category("Color Changer", "Strobe") == "par"
    assert ofl_category("Spaceship", "Strobe") == "strobe"  # unknown: the next one
    assert ofl_category(3, None, "Smoke") == "fog"


def test_no_category_busk_knows_gives_none() -> None:
    data = ofl({"Dimmer": one({"type": "Intensity"})})
    assert "category" not in import_ofl(data, manufacturer="T", key="t").profile
    assert ofl_category() is None
    assert ofl_category("Spaceship") is None
    malformed = ofl({"Dimmer": one({"type": "Intensity"})}, categories="Strobe")
    assert "category" not in import_ofl(malformed, manufacturer="T", key="t").profile


def test_the_tupperdmx_files() -> None:
    found = {
        path.stem: read_ofl(path, manufacturer="TupperDMX").profile.get("category")
        for path in sorted(OFL.glob("*.json"))
    }
    assert found == {
        "blinder": "blinder",
        "ledbar": "pixel",
        "moving-head": "spot",
        "par-rgbw": "par",
        "smoke-machine": "fog",
    }


def test_the_category_goes_after_the_source_in_an_imported_file() -> None:
    profile = read_ofl(OFL / "par-rgbw.json", manufacturer="TupperDMX").profile
    keys = list(profile)
    assert keys[keys.index("source") + 1] == "category"


def test_a_library_directory_imports_ofl_files_with_their_category(tmp_path: Path) -> None:
    (tmp_path / "tupperdmx").mkdir()
    (tmp_path / "tupperdmx" / "par.json").write_text((OFL / "par-rgbw.json").read_text("utf-8"))
    library = ProfileLibrary([tmp_path / "tupperdmx"], builtin=False)
    assert [p.get("category") for p in library] == ["par"]


def test_a_gdtf_import_has_no_category() -> None:
    """DIN SPEC 15800 gives a fixture type no category, and busk guesses none:
    not for a moving spot, not for a bar of cells."""
    for data in (spot(), bar()):
        assert "category" not in import_gdtf(data).profile


# ------------------------------------------------------------------ the console line


def submitted(line: str, doc: dict[str, Any] | None = None) -> dict[str, Any]:
    action = parse(line, p7_context(doc))
    assert isinstance(action, Submit)
    return dict(action.command)


def labelled(label: str, command: dict[str, Any]) -> dict[str, Any]:
    return {"type": "BATCH", "label": label, "commands": [command]}


def test_profile_category_sets_it() -> None:
    assert submitted('profile "RGB Par 3ch" category wash') == labelled(
        "set the category of profile 'RGB Par 3ch' to wash",
        {"type": "SET", "path": PAR, "value": "wash"},
    )
    # the name in any case, or the id; the category in any case
    assert submitted('PROFILE "generic SPOT 16ch" CATEGORY Beam')["commands"] == [
        {"type": "SET", "path": SPOT, "value": "beam"}
    ]
    assert submitted('profile "prof-mh" category spot')["commands"] == [
        {"type": "SET", "path": SPOT, "value": "spot"}
    ]


def test_profile_category_none_removes_it() -> None:
    doc = load_doc(APPENDIX_A)
    doc["profiles"][1]["category"] = "par"
    assert submitted('profile "RGB Par 3ch" category none', doc) == labelled(
        "removed the category of profile 'RGB Par 3ch'", {"type": "DELETE", "path": PAR}
    )


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ('profile "RGB Par 3ch" category none', "profile 'RGB Par 3ch' has no category"),
        ('profile "RGB Par 3ch" category mover',
         "expected a category (par, spot, wash, beam, pixel, strobe, blinder, dimmer, effect, "
         "fog, other) or none, got 'mover'"),
        ('profile "RGB Par 3ch" category par now', "unexpected 'now'"),
        ('profile "RGB Par 3ch" category', "expected a category, or none"),
        ('profile "RGB Par 3ch" kind par', "expected category, got 'kind'"),
        ('profile "RGB Par 3ch"', "expected category"),
        ('profile "Nope" category par', "the show has no profile 'Nope' (see 'list profiles')"),
        # in the library, not in the show: the category belongs to the show's copy
        ('profile "Stairville MH-X25 LED Spot" category spot',
         "the show has no profile 'Stairville MH-X25 LED Spot' (see 'list profiles')"),
        ("profile par category spot",
         'expected update or a profile name in quotes, e.g. "Generic Spot 16ch", got \'par\''),
        ("profile", 'expected update or a profile name in quotes, e.g. "Generic Spot 16ch"'),
    ],
)  # fmt: skip
def test_profile_category_errors(line: str, error: str) -> None:
    with pytest.raises(ParseError) as raised:
        parse(line, p7_context())
    assert raised.value.message == error


def test_one_undo_step_no_new_revision_and_the_same_dmx() -> None:
    show = appendix()
    assert show.execute("blackout off").ok
    for line in ("sel fixture 101 thru 102, fixture 201", "set intensity 80%", "set pan 30"):
        assert show.execute(line).ok
    before = show.tick(0.1).universes
    reply = show.execute('profile "Generic Spot 16ch" category wash')
    assert reply.ok
    assert reply.text == "set the category of profile 'Generic Spot 16ch' to wash"
    assert categories(show) == {"Generic Spot 16ch": "wash", "RGB Par 3ch": None}
    assert [p["revision"] for p in show.show["profiles"]] == ["1", "1"]
    assert {f["profileRevision"] for f in show.show["fixtures"]} == {"1"}
    assert not show.warnings
    after = show.tick(0.2).universes
    assert {n: bytes(u) for n, u in after.items()} == {n: bytes(u) for n, u in before.items()}
    assert show.execute("undo").text == (
        "undid: set the category of profile 'Generic Spot 16ch' to wash"
    )
    assert categories(show)["Generic Spot 16ch"] is None
    assert show.execute("redo").ok
    assert categories(show)["Generic Spot 16ch"] == "wash"
    assert show.execute('profile "Generic Spot 16ch" category none').ok
    assert categories(show)["Generic Spot 16ch"] is None


def test_a_command_with_an_unknown_category_is_refused() -> None:
    show = appendix()
    result = show.submit({"type": "SET", "path": SPOT, "value": "mover"})
    assert not result.ok
    assert categories(show)["Generic Spot 16ch"] is None


def test_list_profiles_prints_the_category() -> None:
    show = appendix()
    assert show.execute('profile "RGB Par 3ch" category par').ok
    assert show.execute("list profiles").text.splitlines() == [
        "Generic Spot 16ch (revision 1): 16ch",
        "RGB Par 3ch (par, revision 1): 3ch",
    ]


# ------------------------------------------------------------------ profile update


def library_spot(tmp_path: Path, **changes: Any) -> ProfileLibrary:
    """A library holding revision 2 of the built-in spot, with ``changes``."""
    profile = json.loads((builtin_directory() / "generic-spot-16ch.json").read_text("utf-8"))
    profile.update(revision="2", **changes)
    profile = {key: value for key, value in profile.items() if value is not None}
    (tmp_path / "spot.json").write_text(json.dumps(profile), encoding="utf-8")
    return ProfileLibrary([tmp_path], builtin=False)


@pytest.mark.parametrize(
    ("ours", "library", "kept"),
    [
        ("wash", "spot", "wash"),  # the show's wins over the library's
        ("wash", None, "wash"),  # and is not deleted when the library has none
        (None, "spot", "spot"),  # a copy with none takes the library's
        (None, None, None),
    ],
)
def test_profile_update_keeps_the_shows_category(
    tmp_path: Path, ours: str | None, library: str | None, kept: str | None
) -> None:
    doc = load_doc(APPENDIX_A)
    if ours is not None:
        doc["profiles"][0]["category"] = ours
    show = OfflineShow(show_of(doc), library=library_spot(tmp_path, category=library))
    reply = show.execute('profile update "Generic Spot 16ch"')
    assert reply.text == "updated profile 'Generic Spot 16ch' to revision '2' (2 fixtures)"
    assert categories(show)["Generic Spot 16ch"] == kept
    assert show.show["profiles"][0]["revision"] == "2"


# ------------------------------------------------------------------ live and saved


def test_a_live_show_sets_it_and_another_thread_reads_it() -> None:
    live = LiveShow(show_of(load_doc(APPENDIX_A)), output=False)
    with live:
        assert live.execute('profile "RGB Par 3ch" category par').ok
        read: list[dict[str, str | None]] = []
        reader = threading.Thread(target=lambda: read.append(categories(live)))
        reader.start()
        reader.join()
    assert read == [{"Generic Spot 16ch": None, "RGB Par 3ch": "par"}]


def test_a_saved_show_keeps_it(tmp_path: Path) -> None:
    show = appendix()
    assert show.execute('profile "Generic Spot 16ch" category beam').ok
    path = tmp_path / "saved.show"
    save_show(show.show, path)
    loaded, warnings = load_show(path)
    assert not warnings
    assert loaded["profiles"][0]["category"] == "beam"
