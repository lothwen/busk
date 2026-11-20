"""The session status (GAP-03 of ``docs/dev/tui/engine-gaps.md``).

``OfflineShow.session`` and ``LiveShow.session`` say whether the show has
unsaved edits, the file ``save`` writes, what ``undo`` and ``redo`` would take
back, and the counters that grow with each change to the show and to the
programmer, all of one moment. The show: the template with a universe and an
RGB par 101.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from busk.persistence.show_file import load_show, new_show
from busk.runner import LiveShow, OfflineShow
from busk.session.ids import CounterIds
from busk.session.session import SessionSnapshot, SessionStatus

PAR = 'fixture add 101 "RGB Par 3ch" mode "3ch" at 1.1'


@pytest.fixture
def club(tmp_path: Path) -> Path:
    """``club.show``: the template with universe 1 and par 101, saved."""
    path = tmp_path / "club.show"
    builder = OfflineShow(new_show("Club"), path=path, ids=CounterIds())
    for line in ("universe add 1", PAR):
        assert builder.execute(line).ok
    assert builder.save().ok
    return path


def offline(path: Path) -> OfflineShow:
    return OfflineShow(load_show(path)[0], path=path, ids=CounterIds(100))


def test_a_loaded_show_has_nothing_to_undo_and_names_its_file(club: Path) -> None:
    status = offline(club).session
    assert status == SessionStatus(
        showVersion=0,
        programmerVersion=0,
        dirty=False,
        path=str(club),
        undoSteps=0,
        redoSteps=0,
        nextUndo=None,
        nextRedo=None,
    )


def test_an_edit_undo_and_redo(club: Path) -> None:
    show = offline(club)
    said = show.execute('rename show "Night"').text
    edited = show.session
    assert edited.dirty
    assert edited.showVersion == 1
    assert (edited.undoSteps, edited.redoSteps) == (1, 0)
    assert (edited.nextUndo, edited.nextRedo) == (said, None)
    assert show.execute("undo").text == f"undid: {edited.nextUndo}"
    undone = show.session
    assert undone.dirty  # an undo is an edit too
    assert undone.showVersion == 2
    assert (undone.undoSteps, undone.redoSteps) == (0, 1)
    assert (undone.nextUndo, undone.nextRedo) == (None, said)
    assert show.execute("redo").text == f"redid: {said}"
    redone = show.session
    assert redone.showVersion == 3
    assert (redone.undoSteps, redone.redoSteps, redone.nextUndo) == (1, 0, said)


def test_programmer_changes_count_apart_from_the_show(club: Path) -> None:
    show = offline(club)
    selected = show.execute("sel fixture 101").text
    show.execute("blind on")  # a mode: no undo step
    status = show.session
    assert (status.showVersion, status.programmerVersion) == (0, 2)
    assert not status.dirty
    assert (status.undoSteps, status.nextUndo) == (1, selected)
    show.execute("undo")
    assert show.session.programmerVersion == 3
    assert (show.session.redoSteps, show.session.nextRedo) == (1, selected)


def test_an_undo_group_is_one_step_with_its_label(club: Path) -> None:
    show = offline(club)
    show.execute("sel fixture 101")
    assert show.execute('undo group "fade up"').ok
    assert show.session.undoSteps == 1  # an open group is not a step yet
    show.execute("set intensity 0.5")
    show.execute("set intensity 1")
    status = show.session
    assert (status.undoSteps, status.nextUndo) == (2, "fade up")


def test_a_save_clears_dirty_and_gives_the_path(
    club: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    show = OfflineShow(load_show(club)[0])
    assert show.session.path is None
    show.execute('rename show "Night"')
    assert show.execute("save club.show").ok  # a relative path: the status is absolute
    status = show.session
    assert not status.dirty
    assert status.path == str(tmp_path / "club.show")
    assert status.showVersion == 2  # a save counts as a change to the show
    assert status.undoSteps == 1  # and is no undo step


def test_the_same_object_until_something_changes(club: Path) -> None:
    show = offline(club)
    first = show.session
    assert show.session is first
    show.execute("go 1")  # no playback: refused, nothing changes
    show.execute("gm 50%")  # a performance line: the session does not change
    assert show.session is first
    show.execute("sel fixture 101")
    assert show.session is not first


@pytest.mark.parametrize("line", ['rename show "Night"', "sel fixture 101", "undo", "redo", "save"])
def test_each_change_publishes_one_snapshot_that_holds_its_step(club: Path, line: str) -> None:
    """A reader never sees a change without its undo step: the timeline moves
    before the snapshot is published, in the same one."""
    show = offline(club)
    if line in ("undo", "redo"):
        show.execute('rename show "Night"')
    if line == "redo":
        show.execute("undo")
    session = show._session
    published: list[SessionSnapshot] = []
    publish = session._publish

    def spy() -> None:
        publish()
        published.append(session.snapshot)

    session._publish = spy  # type: ignore[method-assign]
    assert show.execute(line).ok
    assert len(published) == 1
    timeline = session.timeline
    assert (published[0].undoSteps, published[0].redoSteps) == (
        timeline.undo_count,
        timeline.redo_count,
    )


def test_a_live_show_has_it_too(club: Path) -> None:
    with LiveShow(load_show(club)[0], path=club, output=False) as live:
        assert live.session.path == str(club)
        said = live.execute('rename show "Live"').text
        status = live.session
        assert status.dirty
        assert (status.showVersion, status.undoSteps, status.nextUndo) == (1, 1, said)
        assert live.execute("save").ok
        assert not live.session.dirty
