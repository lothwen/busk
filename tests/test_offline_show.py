"""``OfflineShow``: a session over an engine on a clock the caller drives
(phase-8-plan §5.4, step 6).

The Phase 3 build runs through the facade and gives the same show and the
same frame as ``test_build_from_scratch``, which wires the parts by hand. The
Phase 4–7 scripts follow it. Commands happen at the current engine time
(decision 20): a tick at the same time is a no-op for fades and chases.
"""

from __future__ import annotations

import copy
import json
import shutil
import signal
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from builders import APPENDIX_A, ROOT, load_doc, show_of
from busk.commands.types import Command
from busk.compiler.compile import UnsupportedFeature
from busk.console.console import Console, Reply
from busk.errors import ScriptError
from busk.model.show import Show
from busk.persistence.show_file import (
    ShowLoadError,
    load_show,
    new_show,
    read_show_bytes,
    show_json,
)
from busk.runner import DmxFrame, OfflineShow
from busk.session.ids import CounterIds

EXAMPLES = ROOT / "examples"
GOLDEN = Path(__file__).parent / "golden"
NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)  # test_build_from_scratch's
CID = "0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f"
LATER = ["phase4-song.busk", "phase5-effects.busk", "phase6-surfaces.busk", "phase7-safety.busk"]


def golden(name: str) -> Any:
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))


def channels(universe: bytes) -> dict[str, int]:
    """Non-zero channels, 1-based, as the Phase 3 frame golden keeps them."""
    return {str(k + 1): value for k, value in enumerate(universe) if value}


def without_modified(show: Any) -> Any:
    show = copy.deepcopy(show)
    del show["meta"]["modified"]
    return show


class Built:
    """``busk new`` and ``phase3-build.busk`` through the facade."""

    def __init__(self, directory: Path) -> None:
        ids = CounterIds()
        self.template = new_show("Club Night", cid=CID, now=NOW, ids=ids)
        self.path = directory / "club.show"
        self.offline = OfflineShow(self.template, path=str(self.path), ids=ids)
        self.output = self.offline.run_script(EXAMPLES / "phase3-build.busk")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Built:
    return Built(tmp_path_factory.mktemp("built"))


@pytest.fixture
def phase3(built: Built, tmp_path: Path) -> Path:
    """A copy of the built Phase 3 show."""
    return Path(shutil.copy(built.path, tmp_path / "club.show"))


@pytest.fixture(scope="module")
def phase4(built: Built, tmp_path_factory: pytest.TempPathFactory) -> Show:
    """The Phase 3 show with ``phase4-song.busk`` run on it (song 9, chase 10)."""
    path = Path(shutil.copy(built.path, tmp_path_factory.mktemp("phase4") / "club.show"))
    offline = OfflineShow(load_show(path)[0], path=path)
    offline.run_script(EXAMPLES / "phase4-song.busk")
    return offline.show


# ------------------------------------------------------------- the build


def test_the_phase3_build_gives_the_golden_show(built: Built) -> None:
    assert built.output[-1] == f"saved {built.path}"
    saved = json.loads(read_show_bytes(built.path))
    assert without_modified(saved) == without_modified(golden("phase3_built_show.json"))
    assert saved == json.loads(show_json(built.offline.show))  # the session keeps tuples
    assert built.offline.warnings == ()


def test_busking_the_built_show_gives_the_golden_frame(phase3: Path) -> None:
    offline = OfflineShow(load_show(phase3)[0])
    offline.execute("fader 1 1")
    offline.execute("fader 3 1")
    offline.tick(1.0)
    frame = offline.tick(2.5)
    assert list(frame.universes) == [1]
    assert channels(frame.universes[1]) == golden("phase3_frames.json")["warm_and_blue"]


def test_the_phase4_to_7_scripts_follow(phase3: Path) -> None:
    offline = OfflineShow(load_show(phase3)[0], path=phase3)
    for name in LATER:
        output = offline.run_script(str(EXAMPLES / name))  # a ScriptError fails the test
        assert output[-1] == f"saved {phase3}", name
    assert load_show(phase3)[0] == offline.show


# ------------------------------------------------- commands happen now


def test_a_command_happens_at_once(phase3: Path) -> None:
    offline = OfflineShow(load_show(phase3)[0])
    assert offline.time == 0.0
    before = offline.snapshot
    assert offline.execute("fader 1 1").ok
    after = offline.snapshot
    assert after.seq > before.seq
    assert next(p for p in after.playbacks if p.number == 1).faderLevel == 1.0
    assert offline.time == 0.0


def test_submit_takes_command_dicts(phase3: Path) -> None:
    offline = OfflineShow(load_show(phase3)[0])
    grand = next(m["id"] for m in offline.show["masters"] if m["kind"] == "grand")
    result = offline.submit(cast(Command, {"type": "SET_MASTER", "masterId": grand, "level": 0.5}))
    assert result.ok, result
    assert offline.snapshot.grandMaster == 0.5
    refused = offline.submit(cast(Command, {"type": "NO_SUCH_THING"}))
    assert not refused.ok


def test_a_tick_at_the_same_time_leaves_fades_and_chases_alone(phase4: Show) -> None:
    def play(times: list[float]) -> tuple[DmxFrame, Any]:
        offline = OfflineShow(phase4)
        for line in ("fader 9 1", "go 9", "fader 10 1"):
            assert offline.execute(line).ok, line
        frame = offline.tick(times[0])
        for t in times[1:]:
            frame = offline.tick(t)
        return frame, offline.snapshot

    once, snapshot_once = play([0.3, 1.7])
    twice, snapshot_twice = play([0.3, 0.3, 0.3, 1.7])
    assert once.universes == twice.universes
    assert snapshot_once.playbacks == snapshot_twice.playbacks
    assert twice.seq == once.seq + 2


def test_two_ticks_at_one_time_give_the_same_frame(phase4: Show) -> None:
    offline = OfflineShow(phase4)
    for line in ("fader 9 1", "go 9", "fader 10 1"):
        assert offline.execute(line).ok, line
    first = offline.tick(0.5)
    second = offline.tick(0.5)
    assert (first.time, second.time) == (0.5, 0.5)
    assert second.seq == first.seq + 1
    assert first.universes == second.universes


def test_time_cannot_go_back(phase3: Path) -> None:
    offline = OfflineShow(load_show(phase3)[0])
    offline.tick(2.0)
    with pytest.raises(ValueError, match="back"):
        offline.tick(1.0)
    assert offline.time == 2.0


# ------------------------------------------------------- scripts, saving


def test_a_failing_line_raises_a_script_error(tmp_path: Path) -> None:
    offline = OfflineShow(new_show("x"))
    script = tmp_path / "bad.busk"
    script.write_text("gm 0.5\nlist pages\nfrobnicate the rig\ngm 1\n")
    with pytest.raises(ScriptError) as caught:
        offline.run_script(script)
    error = caught.value
    assert (error.path, error.line, error.text) == (script, 3, "frobnicate the rig")
    assert str(error) == f"{script}:3: frobnicate the rig"
    assert any("Main" in line for line in error.output)  # `list pages` ran
    assert f"{script}:3: frobnicate the rig" in error.output
    assert error.output[-1].startswith("error:")
    assert offline.snapshot.grandMaster == 0.5  # line 4 did not run


def test_an_unreadable_script_raises_os_error(tmp_path: Path) -> None:
    offline = OfflineShow(new_show("x"))
    with pytest.raises(FileNotFoundError):
        offline.run_script(tmp_path / "missing.busk")


def test_save_sets_modified_and_writes_the_path(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    offline = OfflineShow(new_show("x", now=NOW), path=path)
    result = offline.save()
    assert result.ok, result
    assert load_show(path)[0] == offline.show
    assert offline.show["meta"]["modified"] != "2026-10-11T12:00:00Z"
    other = tmp_path / "y.show"
    assert offline.save(str(other)).ok
    assert other.exists()
    assert not OfflineShow(new_show("x")).save().ok  # no path: a refusal, not a raise


# --------------------------------------------------------- construction


def test_an_invalid_show_raises_show_load_error() -> None:
    show = new_show("x")
    broken = cast(Show, {**show, "pages": [*show["pages"], dict(show["pages"][0])]})
    with pytest.raises(ShowLoadError) as caught:
        OfflineShow(broken)
    assert any(issue.severity == "error" for issue in caught.value.issues)


def test_a_split_patch_raises_unsupported_feature() -> None:
    doc = load_doc(APPENDIX_A)
    doc["fixtures"][2]["elementPatch"] = {"0": {"universeId": "u1", "address": 200}}
    with pytest.raises(UnsupportedFeature, match="elementPatch"):
        OfflineShow(show_of(doc))


def test_no_threads_no_prints_no_home(
    phase3: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / "state"))
    threads = threading.active_count()
    offline = OfflineShow(load_show(phase3)[0], path=phase3)
    offline.execute("fader 1 1")
    offline.execute("record cue 1/9")  # fails or succeeds, quietly either way
    offline.run_script(EXAMPLES / "phase4-song.busk")
    offline.tick(1.0)
    assert threading.active_count() == threads
    assert capsys.readouterr() == ("", "")
    assert list(home.iterdir()) == []


def test_ctrl_c_during_a_line_is_raised_once_the_line_is_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    offline = OfflineShow(new_show("x"))
    original = Console._execute

    def interrupted(console: Console, line: str) -> Reply:
        reply = original(console, line)
        if line.startswith("gm"):
            signal.raise_signal(signal.SIGINT)  # held back: the line still completes
        return reply

    monkeypatch.setattr(Console, "_execute", interrupted)
    with pytest.raises(KeyboardInterrupt):
        offline.execute("gm 0.5")
    assert offline.snapshot.grandMaster == 0.5
    script = tmp_path / "long.busk"
    script.write_text("list pages\ngm 0.25\ngm 1\n")
    with pytest.raises(KeyboardInterrupt):
        offline.run_script(script)
    assert offline.snapshot.grandMaster == 0.25  # the line after it did not run
    assert offline.execute("list pages").ok  # and the facade goes on
