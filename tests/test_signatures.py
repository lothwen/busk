"""Library-friendly signatures (phase-8-plan §5.1, step 5).

The show-file and import functions keep their existing keywords and gain
defaults, so a library user can call them without the CLI's plumbing:

* ``save_show(show, path)`` takes the wall clock itself;
* ``new_show(title)`` makes a fresh sACN CID, ids and timestamps, and never
  touches the state directory (``busk new`` still passes the installation's
  CID);
* the path parameters of ``read_ofl``, ``read_gdtf``, ``ProfileLibrary`` and
  the show-file functions accept ``str`` as well as :class:`~pathlib.Path`.
"""

from __future__ import annotations

import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from busk.importers.gdtf import read_gdtf
from busk.importers.ofl import read_ofl
from busk.model.validate import validate_show
from busk.persistence.show_file import load_show, new_show, save_show, show_json
from busk.session.ids import CounterIds
from busk.session.library import ProfileLibrary
from gdtf_builder import archive
from test_gdtf import spot

OFL = Path(__file__).parent / "fixtures" / "ofl" / "tupperdmx"


@pytest.fixture
def empty_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """``HOME`` and ``XDG_STATE_HOME`` pointed at one empty directory."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / "state"))
    return home


# ------------------------------------------------------------------ new_show


def test_new_show_with_defaults_touches_no_state_directory(empty_home: Path) -> None:
    show = new_show("x")
    assert list(empty_home.iterdir()) == []
    checked, issues = validate_show(show_json(show))
    assert checked is not None
    assert issues == []
    assert show["meta"]["title"] == "x"


def test_new_show_makes_a_fresh_cid_and_ids_each_time(empty_home: Path) -> None:
    first, second = new_show("x"), new_show("x")
    cid = first["output"]["sacnCid"]
    assert str(uuid.UUID(cid)) == cid
    assert cid != second["output"]["sacnCid"]
    assert first["meta"]["id"] != second["meta"]["id"]


def test_new_show_stamps_the_current_time(empty_home: Path) -> None:
    before = datetime.now(UTC).replace(microsecond=0)
    show = new_show("x")
    after = datetime.now(UTC)
    created = datetime.strptime(show["meta"]["created"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert before <= created <= after
    assert show["meta"]["modified"] == show["meta"]["created"]


def test_new_show_keeps_the_explicit_keywords() -> None:
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    cid = "6f1d3c1e-8b8a-4c55-9a7e-1d2c3b4a5f60"
    show = new_show("x", ids=CounterIds(), now=now, cid=cid)
    assert show == new_show("x", cid=cid, now=now, ids=CounterIds())
    assert show["output"]["sacnCid"] == cid
    assert show["meta"]["created"] == "2026-01-02T03:04:05Z"
    assert show["meta"]["id"] == "show-000000000001"


# ----------------------------------------------------------------- save_show


def test_save_show_without_now_uses_the_wall_clock(tmp_path: Path) -> None:
    path = tmp_path / "club.show"
    show = new_show("Club")
    assert save_show(show, str(path)) is None
    before = datetime.now(UTC)
    backup = save_show(show, str(path))
    after = datetime.now(UTC)
    assert backup is not None
    assert backup.parent == tmp_path / "club.backups"
    stamp = datetime.strptime(backup.stem.removeprefix("club-"), "%Y%m%dT%H%M%S%fZ")
    assert before <= stamp.replace(tzinfo=UTC) <= after
    assert load_show(str(path))[0] == show


# ------------------------------------------------------------------ str paths


def test_read_ofl_accepts_a_str_path() -> None:
    report = read_ofl(str(OFL / "par-rgbw.json"))
    assert report == read_ofl(OFL / "par-rgbw.json")
    assert report.profile["manufacturer"] == "tupperdmx"


def test_read_gdtf_accepts_a_str_path(tmp_path: Path) -> None:
    path = archive(tmp_path / "spot.gdtf", spot())
    assert read_gdtf(str(path)) == read_gdtf(path)


def test_profile_library_accepts_str_directories(tmp_path: Path) -> None:
    shutil.copy(OFL / "blinder.json", tmp_path)
    library = ProfileLibrary([str(tmp_path)], builtin=False)
    assert len(library) == 1
    assert not any("not a directory" in line for line in library.problems)
    missing = ProfileLibrary([str(tmp_path / "nowhere")], builtin=False)
    assert missing.problems == [f"{tmp_path / 'nowhere'}: not a directory"]
