"""The two hosts (plan step 0.1, §4.6): the ``busk run`` command line and
environment ``busk-tui`` replaces itself with, ``--standalone``'s load
errors, the wheel, and the bridge on a real ``busk run --frontend``, with
processes and with ``--threads``."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

import busk
from busk_tui import app, config
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
    ran: list[tuple[str, list[str], dict[str, str]]] = []
    monkeypatch.setattr(os, "execve", lambda path, argv, env: ran.append((path, argv, env)))
    assert app.main(["club.show", "--colors", "16"]) == 0
    ((path, argv, environment),) = ran
    assert path == sys.executable
    assert argv[3:5] == ["run", "club.show"]
    assert environment["TEXTUAL_COLOR_SYSTEM"] == "standard"


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
