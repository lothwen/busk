"""Autosave triggers, retention, session.json and the recovery decision (phase-3-plan §5.9;
phase-4-plan §5.12: the programmer fade time and the speed masters' tempos; phase-5-plan
§5.10: the programmer's effects; phase-7-plan §5.8: the show stamp and forced recovery)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from builders import APPENDIX_A, effect_instance, load_doc
from busk.engine.clock import FakeClock
from busk.persistence.autosave import (
    SHOWS_KEPT,
    AutosaveWorker,
    read_recovery,
)
from busk.persistence.show_file import load_show, save_show
from session_harness import Live, put, sel


class Wall:
    """A wall clock the test moves along with the fake monotonic clock."""

    def __init__(self) -> None:
        self.now = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Live, AutosaveWorker, Wall, Path]:
    live = Live(load_doc(APPENDIX_A))
    path = tmp_path / "club.show"
    save_show(live.session.show, path, now=Wall().now)
    live.session._path = path  # as if loaded from there
    live.session._publish()
    wall = Wall()
    levels = {"m-gm": 1.0, "m-speed": 0.5}
    tempos = {"m-speed": 128.0}
    worker = AutosaveWorker(
        live.session,
        tmp_path / "state",
        clock=FakeClock(),
        wall_clock=wall,
        masters=lambda: levels,
        tempos=lambda: tempos,
        page=lambda: "page-1",
    )
    return live, worker, wall, path


def rename(live: Live, name: str) -> None:
    live.do({"type": "SET", "path": ["meta", "title"], "value": name})


def shows(worker: AutosaveWorker) -> list[str]:
    return sorted(p.name for p in worker.folder.glob("show-*.show"))


def session_json(worker: AutosaveWorker) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((worker.folder / "session.json").read_text())
    return data


def test_a_burst_is_saved_five_seconds_after_its_last_edit(setup: Any) -> None:
    live, worker, wall, _ = setup
    worker.service(0.0)
    for t in (1.0, 2.0, 3.0):
        rename(live, f"t{t}")
        worker.service(t)
    worker.service(7.5)
    assert shows(worker) == []  # 4.5 s after the last edit
    wall.now += timedelta(seconds=8)
    worker.service(8.0)
    assert shows(worker) == ["show-20261011T120008000000Z.show"]
    assert load_show(worker.folder / shows(worker)[0])[0]["meta"]["title"] == "t3.0"
    worker.service(20.0)
    assert len(shows(worker)) == 1  # nothing new to save


def test_a_long_burst_is_saved_every_180_seconds(setup: Any) -> None:
    live, worker, wall, _ = setup
    written = []
    for k in range(200):  # an edit every 2 s for 400 s
        t = 2.0 * k
        wall.now = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC) + timedelta(seconds=t)
        rename(live, f"t{k}")
        before = len(shows(worker))
        worker.service(t)
        if len(shows(worker)) > before:
            written.append(t)
    assert written == [180.0, 360.0]


def test_unchanged_or_saved_shows_are_not_autosaved(setup: Any) -> None:
    live, worker, _, _path = setup
    live.do(sel("fx-mh1"), put("pan", 3))  # programmer only
    worker.service(0.0)
    worker.service(10.0)
    assert shows(worker) == []
    rename(live, "x")
    worker.service(11.0)
    assert live.session.save().ok
    worker.service(20.0)
    assert shows(worker) == []  # saved before the burst ended
    assert session_json(worker)["showAutosave"] is None


def test_retention_keeps_the_newest(setup: Any) -> None:
    live, worker, wall, _ = setup
    for k in range(SHOWS_KEPT + 4):
        rename(live, f"v{k}")
        wall.now += timedelta(seconds=10)
        worker.service(10.0 * k)
        worker.service(10.0 * k + 6)
    assert len(shows(worker)) == SHOWS_KEPT
    newest = load_show(worker.folder / shows(worker)[-1])[0]
    assert newest["meta"]["title"] == f"v{SHOWS_KEPT + 3}"


def test_session_json_holds_what_a_restart_needs(setup: Any) -> None:
    live, worker, _wall, path = setup
    worker.service(0.0)
    data = session_json(worker)
    assert data == {
        "programmer": {
            "selection": [],
            "values": {},
            "effects": [],
            "blind": False,
            "fadeTime": 0.0,
            "highlight": False,
        },
        "masterLevels": {"m-gm": 1.0, "m-speed": 0.5},
        "speedBpm": {"m-speed": 128.0},
        "page": "page-1",
        "showPath": str(path),
        "showAutosave": None,
        "showStamp": list(live.session.snapshot.stamp),
        "cleanExit": False,
    }
    live.do(sel("fx-mh1"), put("pan", 3), {"type": "BLIND", "on": True})
    live.do({"type": "PROGRAMMER_FADE", "time": 1.5})
    worker.service(0.5)  # at most once per second
    assert session_json(worker)["programmer"]["values"] == {}
    worker.service(1.0)
    assert session_json(worker)["programmer"] == {
        "selection": [{"fixtureId": "fx-mh1", "element": 0}],
        "values": {"fx-mh1:0/pan": {"kind": "literal", "value": 3}},
        "effects": [],
        "blind": True,
        "fadeTime": 1.5,
        "highlight": False,
    }
    rename(live, "edited")
    worker.service(1.5)  # the worker notices the edit when it polls
    worker.service(7.0)
    assert session_json(worker)["showAutosave"] == str(worker.folder / shows(worker)[0])
    assert worker.finish(8.0) == worker.folder / shows(worker)[0]  # unsaved edits: named
    assert session_json(worker)["cleanExit"] is True


def test_finish_autosaves_pending_edits(setup: Any) -> None:
    live, worker, _, _ = setup
    worker.service(0.0)
    rename(live, "late")
    worker.service(1.0)
    kept = worker.finish(1.5)
    assert kept is not None
    assert load_show(kept)[0]["meta"]["title"] == "late"
    clean = AutosaveWorker(
        live.session, worker.folder.parent.parent, clock=FakeClock(), wall_clock=Wall()
    )
    live.session.save()
    assert clean.finish(0.0) is None


# ------------------------------------------------------------------ recovery


def crash(setup: Any) -> tuple[Live, AutosaveWorker, Path]:
    """Edit, program, autosave, and stop without finish(): a crash."""
    live, worker, wall, path = setup
    worker.service(0.0)
    live.do(sel("fx-mh2"), put("tilt", -20), {"type": "BLIND", "on": True})
    rename(live, "unsaved")
    worker.service(1.0)
    wall.now += timedelta(seconds=10)
    os.utime(path, (1, 1))  # the show file is older than any autosave
    worker.service(10.0)
    return live, worker, path


def test_a_crash_is_recovered(setup: Any, tmp_path: Path) -> None:
    live, worker, path = crash(setup)
    recovery = read_recovery(tmp_path / "state", live.session.show["meta"]["id"], path)
    assert recovery is not None
    assert recovery.programmer == live.session.programmer
    assert recovery.programmer.blind
    assert recovery.masterLevels == {"m-gm": 1.0, "m-speed": 0.5}
    assert recovery.speedBpm == {"m-speed": 128.0}
    assert recovery.page == "page-1"
    assert recovery.showAutosave == worker.folder / shows(worker)[0]
    assert load_show(recovery.showAutosave)[0]["meta"]["title"] == "unsaved"


def test_an_autosave_older_than_the_show_file_is_not_used(setup: Any, tmp_path: Path) -> None:
    live, _, path = crash(setup)
    os.utime(path, None)  # saved again since, outside this session
    recovery = read_recovery(tmp_path / "state", live.session.show["meta"]["id"], path)
    assert recovery is not None
    assert recovery.showAutosave is None
    assert recovery.showStamp is None  # it described the autosave, which is not loaded


@pytest.mark.parametrize("case", ["missing", "clean", "garbage"])
def test_a_normal_start(setup: Any, tmp_path: Path, case: str) -> None:
    live, worker, _, path = setup
    worker.service(0.0)
    session = worker.folder / "session.json"
    if case == "missing":
        session.unlink()
    elif case == "clean":
        worker.finish(1.0)
    else:
        session.write_text("{not json")
    assert read_recovery(tmp_path / "state", live.session.show["meta"]["id"], path) is None


def test_malformed_entries_are_dropped_not_fatal(setup: Any, tmp_path: Path) -> None:
    live, worker, _, path = setup
    worker.service(0.0)
    data = session_json(worker)
    data["programmer"]["values"] = {
        "fx-mh1:0/pan": {"kind": "spread"},
        "fx-mh1:0/tilt": {"kind": "literal", "value": 2},
    }
    data["masterLevels"] = {"m-gm": 0.5, "m-bad": 7}
    data["speedBpm"] = {
        "m-speed": 96,
        "m-0": 0,
        "m-max": 999,
        "m-fast": 1000,
        "m-x": "x",
        "m-t": True,
    }
    (worker.folder / "session.json").write_text(json.dumps(data))
    recovery = read_recovery(tmp_path / "state", live.session.show["meta"]["id"], path)
    assert recovery is not None
    assert dict(recovery.programmer.values) == {"fx-mh1:0/tilt": {"kind": "literal", "value": 2}}
    assert recovery.dropped == ("programmer.values['fx-mh1:0/pan']",)
    assert recovery.masterLevels == {"m-gm": 0.5}
    assert recovery.speedBpm == {"m-speed": 96.0, "m-max": 999.0}


def test_a_session_json_from_before_phase_4_still_loads(setup: Any, tmp_path: Path) -> None:
    live, worker, _, path = setup
    worker.service(0.0)
    data = session_json(worker)
    del data["speedBpm"], data["programmer"]["fadeTime"]
    (worker.folder / "session.json").write_text(json.dumps(data))
    recovery = read_recovery(tmp_path / "state", live.session.show["meta"]["id"], path)
    assert recovery is not None
    assert recovery.speedBpm == {}
    assert recovery.programmer.fadeTime == 0.0
    assert recovery.masterLevels == {"m-gm": 1.0, "m-speed": 0.5}


@pytest.mark.parametrize("stamp", ["missing", None, ["a", "1"], ["a", True], ["a"], "a"])
def test_a_session_json_without_a_valid_show_stamp_recovers_none(
    setup: Any, tmp_path: Path, stamp: object
) -> None:
    """Files from before Phase 7 have no stamp; a malformed one is ignored."""
    live, worker, _, path = setup
    worker.service(0.0)
    data = session_json(worker)
    if stamp == "missing":
        del data["showStamp"]
    else:
        data["showStamp"] = stamp
    (worker.folder / "session.json").write_text(json.dumps(data))
    recovery = read_recovery(tmp_path / "state", live.session.show["meta"]["id"], path)
    assert recovery is not None
    assert recovery.showStamp is None


# ------------------------------------------------------------------ the show stamp (Phase 7)


def test_the_show_stamp_is_the_stamp_of_the_show_on_disk(setup: Any) -> None:
    live, worker, _, _ = setup
    loaded = live.session.snapshot.stamp
    assert loaded[1] == 0  # the show the session started with
    worker.service(0.0)
    rename(live, "edited")
    edited = live.session.snapshot.stamp
    assert edited == (loaded[0], 1)  # each show install counts
    worker.service(1.0)
    assert session_json(worker)["showStamp"] == list(loaded)  # not autosaved yet
    worker.service(7.0)
    assert session_json(worker)["showAutosave"] is not None
    assert session_json(worker)["showStamp"] == list(edited)
    assert live.session.save().ok
    assert live.session.snapshot.stamp == edited  # a save installs nothing: same stamp
    worker.service(9.0)
    assert session_json(worker)["showAutosave"] is None
    assert session_json(worker)["showStamp"] == list(edited)  # the saved file's


def test_a_crash_recovers_the_stamp_of_the_autosaved_show(setup: Any, tmp_path: Path) -> None:
    live, _, path = crash(setup)
    recovery = read_recovery(tmp_path / "state", live.session.show["meta"]["id"], path)
    assert recovery is not None
    assert recovery.showStamp == live.session.snapshot.stamp


def test_force_recovers_after_a_clean_exit(setup: Any, tmp_path: Path) -> None:
    """A console that exits 70 writes a clean exit on its way out; the
    console that replaces it recovers anyway."""
    live, worker, _, path = setup
    worker.service(0.0)
    live.do(sel("fx-mh1"), put("pan", 3))
    rename(live, "late")
    kept = worker.finish(1.0)
    show_id = live.session.show["meta"]["id"]
    assert read_recovery(tmp_path / "state", show_id, path) is None
    os.utime(path, (1, 1))  # the show file is older than the autosave
    recovery = read_recovery(tmp_path / "state", show_id, path, force=True)
    assert recovery is not None
    assert recovery.programmer == live.session.programmer
    assert recovery.showAutosave == kept
    assert recovery.showStamp == live.session.snapshot.stamp


@pytest.mark.parametrize("page", ["missing", None, 3])
def test_a_session_json_without_a_page_recovers_none(
    setup: Any, tmp_path: Path, page: object
) -> None:
    """Files from before Phase 6 have no page; a malformed one is ignored."""
    live, worker, _, path = setup
    worker.service(0.0)
    data = session_json(worker)
    if page == "missing":
        del data["page"]
    else:
        data["page"] = page
    (worker.folder / "session.json").write_text(json.dumps(data))
    recovery = read_recovery(tmp_path / "state", live.session.show["meta"]["id"], path)
    assert recovery is not None
    assert recovery.page is None


def test_a_restored_programmer_goes_live(setup: Any, tmp_path: Path) -> None:
    live, _, path = crash(setup)
    recovery = read_recovery(tmp_path / "state", live.session.show["meta"]["id"], path)
    assert recovery is not None
    fresh = Live(load_doc(APPENDIX_A))
    fresh.session.restore_programmer(recovery.programmer)
    fresh.do({"type": "BLIND", "on": False})
    fresh.tick()
    assert fresh.lanes("fx-mh2", "tilt") == [-20.0]
    assert fresh.session.timeline.undo_count == 0


PULSE = effect_instance("fx1", "ef-pulse", {"kind": "group", "groupId": "g-mh"}, size=0.5)


def test_programmer_effects_are_saved_and_recovered(setup: Any, tmp_path: Path) -> None:
    live, worker, _, path = setup
    worker.service(0.0)
    live.do({"type": "ADD_EFFECT", "effect": PULSE})
    worker.service(1.0)
    data = session_json(worker)
    assert data["programmer"]["effects"] == [PULSE]
    show_id = live.session.show["meta"]["id"]
    recovery = read_recovery(tmp_path / "state", show_id, path)
    assert recovery is not None
    assert recovery.programmer.effects == live.session.programmer.effects
    data["programmer"]["effects"].append({**PULSE, "id": "fx2", "templateId": "ef-gone"})
    (worker.folder / "session.json").write_text(json.dumps(data))
    recovery = read_recovery(tmp_path / "state", show_id, path)
    assert recovery is not None
    assert recovery.dropped == ()  # well formed: whether it fits the show is checked on restore
    fresh = Live(load_doc(APPENDIX_A))
    dropped = fresh.session.restore_programmer(recovery.programmer)
    assert dropped == ["programmer effect 'fx2': Unknown effect template 'ef-gone'"]
    assert [effect["id"] for effect in fresh.session.programmer.effects] == ["fx1"]
    fresh.tick()
    assert list(fresh.engine._programmer.bank.runtimes) == ["fx1"]  # it runs again
