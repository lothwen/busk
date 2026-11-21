"""The two hosts (plan step 0.1, §4.6): the ``busk run`` command line and
environment ``busk-tui`` starts, ``--standalone``'s load errors and its loop
over the shows the TUI opens, the wheel, the bridge on a real ``busk run
--frontend``, with processes and with ``--threads``, and the parent starting
the show a real run hands over (file-menu plan Phase 3)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import busk
from busk_tui import app, config, parent
from busk_tui.bridge import Bridge
from process_harness import BuskRun

HERE = Path(__file__).parent
ROOT = HERE.parents[1]


def test_busk_tui_runs_busk_run_with_its_frontend() -> None:
    options = config.parse_arguments(["club.show", "--threads", "--layout", "A", "--faders", "8"])
    command, environment = app.run_command(options)
    assert command == [
        sys.executable, "-m", "busk", "run", "club.show", "--frontend", "busk_tui.app:frontend",
        "--threads",
    ]  # fmt: skip
    given = json.loads(environment[config.ENVIRONMENT])
    assert (given["layout"], given["faders"], given["colors"]) == ("A", 8, None)
    assert environment["PATH"] == os.environ["PATH"]  # the rest of the environment


def test_colors_set_textuals_colour_system_for_busk_run_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEXTUAL_COLOR_SYSTEM", raising=False)
    ran: list[tuple[list[str], Any, dict[str, str]]] = []

    def run(first: list[str], then: Any, environment: dict[str, str]) -> int:
        ran.append((first, then, environment))
        return 5

    monkeypatch.setattr(parent, "run", run)
    assert app.main(["club.show", "--colors", "16", "--script", "x.busk"]) == 5  # the run's code
    ((first, then, environment),) = ran
    assert first[0] == sys.executable
    assert first[3:5] == ["run", "club.show"]
    assert "--script" in first
    following = then(Path("/s/b.show"))
    assert following[3:5] == ["run", "/s/b.show"]
    assert "--script" not in following  # the show given's only
    assert environment["TEXTUAL_COLOR_SYSTEM"] == "standard"


def test_without_a_show_busk_run_runs_the_one_the_launcher_chose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The launcher's choice is the show given, with the options given
    (``--script`` too); quitting it runs nothing, and a launcher that
    crashed ends ``busk-tui`` with its code."""
    from busk_tui.launcher import Launcher

    chosen: list[Path | None] = [Path("/s/club.show")]
    ran: list[list[str]] = []

    def launch(self: Launcher) -> Path | None:
        return chosen[0]

    def run(first: list[str], then: Any, environment: dict[str, str]) -> int:
        ran.append(first)
        return 0

    monkeypatch.setattr(Launcher, "run", launch)
    monkeypatch.setattr(parent, "run", run)
    assert app.main(["--script", "x.busk", "--threads"]) == 0
    (first,) = ran
    assert first[3:5] == ["run", "/s/club.show"]
    assert first[-3:] == ["--threads", "--script", "x.busk"]
    ran.clear()
    chosen[0] = None
    assert app.main([]) == 0
    assert ran == []

    def crash(self: Launcher) -> None:
        self._return_code = 1  # as Textual leaves it after an exception

    monkeypatch.setattr(Launcher, "run", crash)
    assert app.main([]) == 1
    assert ran == []


def test_the_debug_log_is_set_up_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The launcher sets it up, then ``--standalone``: one handler, not two."""
    logger = logging.getLogger("busk_tui")
    for name in ("handlers", "level", "propagate"):
        monkeypatch.setattr(logger, name, getattr(logger, name))
    logger.handlers = []
    app._debug_log()
    app._debug_log()
    assert len(logger.handlers) == 1


def test_standalone_says_why_a_show_does_not_load_and_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{}")
    assert app.main([str(broken), "--standalone"]) == 2
    err = capsys.readouterr().err
    assert err.startswith(f"busk-tui: {broken}: error ")
    assert app.main([str(tmp_path / "missing.show"), "--standalone"]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_standalone_runs_the_next_show_the_tui_opens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A new bridge and a new app on each show the app ends with, the
    first the launcher's when no show is given; a next show that does not
    load ends it with 2, as the first would."""
    shows = {name: tmp_path / f"{name}.show" for name in ("a", "b")}
    for name, path in shows.items():
        busk.save_show(busk.new_show(name.upper()), path, backups=False)
    broken = tmp_path / "broken.json"
    broken.write_text("{}")
    from busk_tui.shell import BuskApp

    opened: list[Path] = []
    nexts = [shows["b"], None]
    standalone = Bridge.standalone

    def bridge(path: Path, **given: Any) -> Bridge:
        opened.append(path)
        return standalone(path, **given)

    def run(self: BuskApp) -> int:
        self.next_show = nexts.pop(0)
        return 0

    monkeypatch.setattr(Bridge, "standalone", bridge)
    monkeypatch.setattr(BuskApp, "run", run)
    options = ["--standalone", "--no-output", "--no-surfaces"]
    assert app.main([str(shows["a"]), *options]) == 0
    assert opened == [shows["a"], shows["b"]]
    from busk_tui.launcher import Launcher

    monkeypatch.setattr(Launcher, "run", lambda self: shows["b"])
    opened.clear()
    nexts = [None]
    assert app.main(options) == 0  # no show: the launcher's
    assert opened == [shows["b"]]
    nexts = [broken]
    assert app.main([str(shows["a"]), *options]) == 2
    assert "busk-tui: " in capsys.readouterr().err


@pytest.mark.parametrize("handing", [True, False], ids=["parent", "no parent"])
def test_the_frontend_hands_the_show_the_tui_opened_to_its_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, handing: bool
) -> None:
    """Under busk-tui's parent (``$BUSK_TUI_NEXT``), the TUI can open
    another show, and the frontend hands it over once the app ends; without
    one, the TUI is told it cannot."""
    from tui_fakes import FakeBridge

    from busk_tui.shell import BuskApp

    next_file = tmp_path / "next.json"
    if handing:
        monkeypatch.setenv(parent.NEXT, str(next_file))
    else:
        monkeypatch.delenv(parent.NEXT, raising=False)
    monkeypatch.setenv(config.ENVIRONMENT, json.dumps({"state_dir": str(tmp_path / "st")}))
    seen: list[tuple[bool, Path | None]] = []

    def run(self: BuskApp) -> int:
        seen.append((self.opens, self.state_dir))
        self.next_show = tmp_path / "b.show"
        return 0

    monkeypatch.setattr(Bridge, "attached", lambda show: FakeBridge())
    monkeypatch.setattr(BuskApp, "run", run)
    app.frontend(object())
    assert seen == [(handing, tmp_path / "st")]
    if handing:
        assert parent.read_next(next_file) == tmp_path / "b.show"
    else:
        assert not next_file.exists()


def test_python_m_busk_tui_is_busk_tui() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "busk_tui", "--version"], capture_output=True, text=True, timeout=30
    )
    assert done.returncode == 0
    assert done.stdout.strip() == f"busk-tui {busk.__version__}"


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Iterator[zipfile.ZipFile]:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not on the PATH")
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(out), str(ROOT)],
        capture_output=True,
        check=True,
        timeout=120,
    )
    (path,) = out.glob("busk-*.whl")
    with zipfile.ZipFile(path) as opened:
        yield opened


def test_the_wheel_carries_the_tui_and_its_command(wheel: zipfile.ZipFile) -> None:
    names = wheel.namelist()
    for module in ("__init__", "__main__", "app", "bridge", "shell", "model"):
        assert f"busk_tui/{module}.py" in names
    assert "busk_tui/busk.tcss" in names
    assert "busk_tui/widgets/prompt.py" in names
    dist_info = f"busk-{busk.__version__}.dist-info"
    entry_points = wheel.read(f"{dist_info}/entry_points.txt").decode()
    assert "busk-tui = busk_tui.app:main" in entry_points
    metadata = wheel.read(f"{dist_info}/METADATA").decode()
    assert "Provides-Extra: tui" in metadata
    assert "Requires-Dist: textual>=8.2 ; extra == 'tui'" in metadata


# ----------------------------------------------------------- under busk run


@pytest.fixture
def small_show(tmp_path: Path) -> Path:
    """A show with a grand master, no route and no surface."""
    path = tmp_path / "small.show"
    busk.save_show(busk.new_show("Small"), path, backups=False)
    return path


def test_a_patch_and_a_route_from_f3_and_f8_reach_the_engine_under_busk_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "rig.show"
    show = busk.OfflineShow(busk.new_show("Rig"), path=path)
    for line in ('universe add 1 "Stage"', 'fixture add 1 "RGB Par 3ch" mode "3ch" at 1.1', "save"):
        assert show.execute(line).ok, line
    report = tmp_path / "report.json"
    monkeypatch.setenv("BUSK_TUI_TEST_REPORT", str(report))
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(HERE), os.environ.get("PYTHONPATH", "")]))
    options = ["--frontend", "tui_rig_frontend:main", "--state-dir", str(tmp_path / "state")]
    with BuskRun(path, *options, "--no-log") as run:
        assert run.wait() == 0, run.err
    seen = json.loads(report.read_text())
    assert seen["timeout"] is None, seen
    assert seen["frames"] == [[1, 2, 3], [101, 102, 103], [201, 202, 203]]
    assert seen["routes"] == ["ok", "disabled", "ok", "ok", None]
    assert seen["changed"] == ["7", "unicast 127.0.0.1", True]


@pytest.mark.parametrize("threads", [False, True], ids=["processes", "threads"])
def test_the_bridge_on_busk_runs_show(
    small_show: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, threads: bool
) -> None:
    report = tmp_path / "report.json"
    monkeypatch.setenv("BUSK_TUI_TEST_REPORT", str(report))
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(HERE), os.environ.get("PYTHONPATH", "")]))
    options = ["--frontend", "tui_probe:main", "--state-dir", str(tmp_path / "state"), "--no-log"]
    with BuskRun(small_show, *options, *(["--threads"] if threads else [])) as run:
        assert run.wait() == 0, run.err
    seen = json.loads(report.read_text())
    assert seen["timeout"] is None, seen
    assert seen["seconds"] < 1.0
    assert seen["help"] > 50
    assert seen["health"] == "running"  # the bridge never stopped the show


def test_the_parent_starts_the_show_a_real_run_hands_over(tmp_path: Path) -> None:
    """Two real ``busk run``s, one after the other: the first one's frontend
    hands ``b.show`` over through ``$BUSK_TUI_NEXT``, which reaches the
    console process; the parent starts it, and ends with its code."""
    shows = {name: tmp_path / f"{name.lower()}.show" for name in ("A", "B")}
    for title, path in shows.items():
        busk.save_show(busk.new_show(title), path, backups=False)
    report = tmp_path / "report.jsonl"
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(HERE), os.environ.get("PYTHONPATH", "")]),
        "BUSK_TUI_TEST_REPORT": str(report),
        "BUSK_TUI_TEST_NEXT": str(shows["B"]),
    }

    def command(show: Path) -> list[str]:
        return [sys.executable, "-m", "busk", "run", str(show), "--frontend",
                "tui_handoff_frontend:main", "--state-dir", str(tmp_path / "state"),
                "--no-log"]  # fmt: skip

    with (tmp_path / "out.txt").open("w") as out:

        def start(line: list[str], given: dict[str, str]) -> parent.Run:
            return subprocess.Popen(line, env=given, stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=subprocess.STDOUT)  # fmt: skip

        code = parent.run(command(shows["A"]), command, environment, start)
    assert code == 0, (tmp_path / "out.txt").read_text()
    seen = [json.loads(line) for line in report.read_text().splitlines()]
    assert [entry["title"] for entry in seen] == ["A", "B"]
    assert seen[0]["next"] == seen[1]["next"] is not None
    assert not Path(seen[0]["next"]).parent.exists()
