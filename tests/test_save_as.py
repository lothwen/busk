"""Saving to another file makes a new show (GAP-55 of ``docs/dev/tui/engine-gaps.md``).

``save PATH`` to another file than the show's own gives the copy a new
``meta.id``, and ``created`` and ``modified`` of now, so its autosaves and
crash recovery are its own; the file it was saved from stays as it was saved.
``save`` and a save to the show's own file keep the id, and so does the first
save of a show without a file. The show: the template, titled "Club", saved
as ``club.show``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from busk.persistence.show_file import load_show, new_show, save_show
from busk.runner import OfflineShow
from busk.session.ids import CounterIds

THEN = datetime(2026, 11, 1, 20, 0, 0, tzinfo=UTC)
"""When ``club.show`` was made."""


@pytest.fixture
def club(tmp_path: Path) -> Path:
    path = tmp_path / "club.show"
    save_show(new_show("Club", now=THEN, ids=CounterIds()), path, backups=False)
    return path


def opened(path: Path) -> OfflineShow:
    return OfflineShow(load_show(path)[0], path=path, ids=CounterIds(100))


def test_saving_to_its_own_file_keeps_the_id(club: Path) -> None:
    show = opened(club)
    ident = show.show["meta"]["id"]
    show.execute('rename show "Night"')
    assert show.execute("save").text == f"saved {club}"
    spelled = club.parent / "sub" / ".." / club.name  # the same file, compared resolved
    (club.parent / "sub").mkdir()
    assert show.execute(f"save {spelled}").text == f"saved {spelled}"
    meta = load_show(club)[0]["meta"]
    assert meta["id"] == ident
    assert meta["created"] == "2026-11-01T20:00:00Z"
    assert meta["title"] == "Night"


def test_saving_to_another_file_makes_a_new_show(club: Path, tmp_path: Path) -> None:
    before = club.read_bytes()
    show = opened(club)
    ident = show.show["meta"]["id"]
    show.execute('rename show "Night"')
    copy = tmp_path / "copy.show"
    reply = show.execute(f"save {copy}")
    assert reply.ok
    assert reply.text == f"saved {copy} as a new show; {club} stays as it was saved"
    meta = load_show(copy)[0]["meta"]
    assert meta["id"] not in (ident, None)
    assert meta["id"].startswith("show-")
    assert meta["created"] == meta["modified"] != "2026-11-01T20:00:00Z"
    assert meta["title"] == "Night"  # the title is kept
    assert show.show["meta"] == meta  # the session holds the copy
    assert club.read_bytes() == before  # the original is as it was saved
    assert show.session.path == str(copy)
    show.execute('rename show "Later"')
    assert show.execute("save").text == f"saved {copy}"  # a later save writes the copy
    assert load_show(copy)[0]["meta"]["id"] == meta["id"]
    assert load_show(club)[0]["meta"]["title"] == "Club"


def test_undo_after_it_keeps_the_new_id(club: Path, tmp_path: Path) -> None:
    show = opened(club)
    show.execute('rename show "Night"')
    assert show.execute(f"save {tmp_path / 'copy.show'}").ok
    ident = show.show["meta"]["id"]
    assert show.execute("undo").text == 'undid: renamed the show "Club" to "Night"'
    assert show.show["meta"]["title"] == "Club"
    assert show.show["meta"]["id"] == ident  # no step's inverse holds the whole meta
    assert show.execute("redo").ok
    assert show.show["meta"]["id"] == ident
    assert show.session.dirty


def test_a_show_without_a_file_keeps_its_id_on_its_first_save(tmp_path: Path) -> None:
    show = OfflineShow(new_show("Club", now=THEN, ids=CounterIds()), ids=CounterIds(100))
    ident = show.show["meta"]["id"]
    first = tmp_path / "first.show"
    assert show.execute(f"save {first}").text == f"saved {first}"
    assert load_show(first)[0]["meta"]["id"] == ident
    assert show.save(tmp_path / "second.show").ok  # it has a file now: a new show
    assert show.show["meta"]["id"] != ident


def test_a_failed_save_as_changes_nothing(club: Path, tmp_path: Path) -> None:
    show = opened(club)
    meta = dict(show.show["meta"])
    reply = show.execute(f"save {tmp_path / 'copy.txt'}")
    assert not reply.ok
    assert show.show["meta"] == meta
    assert show.session.path == str(club)
    assert not (tmp_path / "copy.txt").exists()
