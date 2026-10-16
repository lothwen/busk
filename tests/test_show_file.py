"""Show files: .show / .json I/O, atomic writes, backups, the template (phase-3-plan §5.8)."""

from __future__ import annotations

import json
import os
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from builders import APPENDIX_A, load_doc, show_of
from busk.model.validate import validate_show
from busk.persistence import show_file
from busk.persistence.paths import autosave_directory, installation_cid, state_directory
from busk.persistence.show_file import (
    BACKUPS_KEPT,
    ShowLoadError,
    atomic_write,
    backup_directory,
    load_show,
    new_show,
    newest_backup,
    save_show,
)
from busk.session.ids import CounterIds

NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize("suffix", [".show", ".json"])
def test_round_trip(tmp_path: Path, suffix: str) -> None:
    show = show_of(load_doc(APPENDIX_A))
    path = tmp_path / f"club{suffix}"
    assert save_show(show, path, now=NOW) is None  # nothing to back up yet
    loaded, warnings = load_show(path)
    assert loaded == show
    assert warnings == []


def test_a_show_file_is_a_zip_of_readable_json(tmp_path: Path) -> None:
    show = show_of(load_doc(APPENDIX_A))
    path = tmp_path / "club.show"
    save_show(show, path, now=NOW)
    with zipfile.ZipFile(path) as archive:
        assert archive.namelist() == ["show.json"]
        info = archive.getinfo("show.json")
        assert (info.compress_type, info.date_time) == (zipfile.ZIP_DEFLATED, (1980, 1, 1, 0, 0, 0))
        text = archive.read("show.json").decode("utf-8")
    assert text.startswith('{\n  "schemaVersion": 1,\n  "meta": {\n    "id": "show-01",')
    assert list(json.loads(text)) == list(show)  # keys in schema order


def test_equal_shows_save_byte_identical(tmp_path: Path) -> None:
    show = show_of(load_doc(APPENDIX_A))
    first, second = tmp_path / "a.show", tmp_path / "b.show"
    save_show(show, first, now=NOW)
    save_show(show_of(load_doc(APPENDIX_A)), second, now=NOW + timedelta(hours=1))
    assert first.read_bytes() == second.read_bytes()


def test_a_failing_replace_leaves_the_original_and_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "club.json"
    path.write_bytes(b"original")

    def broken(source: object, target: object) -> None:
        raise OSError("disk on fire")

    monkeypatch.setattr(show_file.os, "replace", broken)
    with pytest.raises(OSError, match="disk on fire"):
        atomic_write(path, b"new")
    assert path.read_bytes() == b"original"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["club.json"]


def test_atomic_write_replaces(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    atomic_write(path, b"one")
    atomic_write(path, b"two")
    assert path.read_bytes() == b"two"
    assert os.listdir(tmp_path) == ["x.json"]


def test_backups_rotate_and_keep_the_newest(tmp_path: Path) -> None:
    show = show_of(load_doc(APPENDIX_A))
    path = tmp_path / "club.show"
    save_show(show, path, now=NOW)
    for k in range(BACKUPS_KEPT + 3):
        kept = save_show(show, path, now=NOW + timedelta(seconds=k))
        assert kept is not None
    backups = sorted(backup_directory(path).iterdir())
    assert len(backups) == BACKUPS_KEPT
    assert backups[0].name == "club-20261011T120003000000Z.show"
    assert newest_backup(path) == backups[-1] == kept


def test_backups_with_the_same_timestamp_do_not_overwrite(tmp_path: Path) -> None:
    show = show_of(load_doc(APPENDIX_A))
    path = tmp_path / "club.json"
    for _ in range(3):
        save_show(show, path, now=NOW)
    names = sorted(p.name for p in backup_directory(path).iterdir())
    assert names == ["club-20261011T120000000000Z-1.json", "club-20261011T120000000000Z.json"]


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("club.txt", b"{}", "Unknown show file extension '.txt': use .show or .json"),
        ("club.show", b"not a zip", "Not a valid .show file: File is not a zip file"),
    ],
)
def test_bad_files_are_refused(tmp_path: Path, name: str, content: bytes, message: str) -> None:
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(ShowLoadError) as raised:
        load_show(path)
    assert [issue.message for issue in raised.value.issues] == [message]


def test_save_refuses_an_unknown_extension(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"use \.show or \.json"):
        save_show(show_of(load_doc(APPENDIX_A)), tmp_path / "club.xml", now=NOW)


def test_the_template_is_a_valid_empty_show() -> None:
    show = new_show(
        "Club Night", ids=CounterIds(), now=NOW, cid="0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f"
    )
    assert validate_show(json.dumps(show)) == (show, [])
    assert show["meta"] == {
        "id": "show-000000000001",
        "title": "Club Night",
        "created": "2026-10-11T12:00:00Z",
        "modified": "2026-10-11T12:00:00Z",
        "app": "busk 0.1.0",
    }
    assert show["pages"] == [{"id": "page-000000000002", "name": "Main", "number": 1, "slots": []}]
    assert show["masters"] == [{"id": "m-000000000003", "name": "Grand Master", "kind": "grand"}]
    assert show["output"] == {
        "engineHz": 100.0,
        "sacnSourceName": "Busk Console",
        "sacnCid": "0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f",
        "holdLastFrameOnEngineStall": True,
        "routes": [],
    }
    for key in (
        "profiles",
        "fixtures",
        "groups",
        "presets",
        "cueLists",
        "playbacks",
        "bindings",
        "park",
    ):
        assert show[key] == []  # type: ignore[literal-required]


def test_state_directory_and_installation_cid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    assert state_directory() == tmp_path / "xdg" / "busk"
    assert state_directory(tmp_path / "mine") == tmp_path / "mine"
    monkeypatch.delenv("XDG_STATE_HOME")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert state_directory() == tmp_path / "home" / ".local" / "state" / "busk"
    cid = installation_cid(tmp_path / "state")
    assert installation_cid(tmp_path / "state") == cid  # created once
    assert (tmp_path / "state" / "cid").read_text() == cid + "\n"
    assert autosave_directory(tmp_path, "show/../x") == tmp_path / "autosave" / "show_.._x"
