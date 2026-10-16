"""Crash recovery end to end: `kill -9` a running console, start it again (phase-3-plan §5.9;
phase-4-plan step 15: the tempo and the programmer fade time come back too; phase-5-plan
step 12: so do group and size levels and the programmer's effects; phase-6-plan: the page
and fade-time levels).

This runs ``busk run`` as a real process. The show autosave is written 5 s
after the last edit, so the test takes a few seconds.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from builders import effect_instance, offline

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="needs SIGKILL")


def wait_for(predicate: Any, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("timed out")


def test_a_killed_session_comes_back(tmp_path: Path, appendix_a: dict[str, Any]) -> None:
    appendix_a["masters"] += [
        {"id": "m-heads", "kind": "group", "name": "Heads", "groupId": "g-mh"},
        {"id": "m-fx", "kind": "size", "name": "FX"},
        {"id": "m-fade", "kind": "fadeTime", "name": "Fade"},
    ]
    appendix_a["pages"].append({"id": "page-2", "number": 2, "name": "Two", "slots": []})
    show = tmp_path / "club.json"
    show.write_text(json.dumps(offline(appendix_a)))
    os.utime(show, (1, 1))  # older than any autosave
    env = {**os.environ, "XDG_STATE_HOME": str(tmp_path / "state")}
    command = [sys.executable, "-m", "busk", "run", str(show)]
    first = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert first.stdin is not None
    first.stdin.write(
        'sel group 1\nset pan 33\nblind on\nhighlight on\nrename show "Crashed"\ngm 50%\n'
        "fade 2\nbpm 128\n"
        'master "Heads" 40%\nmaster "FX" 30%\nmaster "Fade" 50%\npage 2\n'
    )
    first.stdin.flush()  # stdin stays open: the console keeps running
    session_json = tmp_path / "state" / "busk" / "autosave" / "show-01" / "session.json"

    def saved() -> bool:
        try:
            data = json.loads(session_json.read_text())
        except (OSError, ValueError):
            return False
        return (
            bool(data["showAutosave"])
            and data["masterLevels"]
            == {"m-gm": 0.5, "m-speed": 0.5, "m-heads": 0.4, "m-fx": 0.3, "m-fade": 0.5}
            and data["speedBpm"] == {"m-speed": 128.0}
            and data["programmer"]["fadeTime"] == 2
            and data["programmer"]["highlight"] is True
            and bool(data["programmer"]["values"])
            and data["page"] == "page-2"
        )

    wait_for(saved)
    first.send_signal(signal.SIGKILL)
    first.wait(10)
    crashed = json.loads(session_json.read_text())
    assert crashed["cleanExit"] is False

    second = subprocess.run(
        command,
        input="programmer\ninfo\nstatus\nlist masters\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert second.returncode == 0, second.stderr
    out = second.stdout.splitlines()
    recovered = next(line for line in out if line.startswith("recovered "))
    assert recovered.startswith(
        "recovered programmer with 2 values (blind, highlight, fade 2 s), 5 master levels, "
        "1 tempo, "
        "page 2, unsaved edits from "
    )
    assert "blind: on" in out
    assert "highlight: on" in out
    assert "  101 pan = 33" in out
    assert "  102 pan = 33" in out
    assert "show: Crashed (show-01)" in out  # the unsaved edit
    assert any(line.startswith("file: ") and line.endswith("unsaved edits") for line in out)
    # The recovered tempo, page and fade time.
    assert "GM 50% | BO off | P2 Two | Speed 1 128 BPM ×1 | Fade 2.5 s" in out
    assert f"{'Heads':<20} {'group':<6} {0.4:>5.0%}" in out
    assert f"{'FX':<20} {'size':<6} {0.3:>5.0%}" in out
    # This run quit cleanly, with the tempo and the fade time it recovered;
    # the next start is a normal one.
    clean = json.loads(session_json.read_text())
    assert clean["cleanExit"] is True
    assert clean["speedBpm"] == {"m-speed": 128.0}
    assert clean["programmer"]["fadeTime"] == 2
    third = subprocess.run(
        [*command, "--duration", "0.3"],
        input="",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert "recovered" not in third.stdout


def test_no_recover_starts_normally(tmp_path: Path, appendix_a: dict[str, Any]) -> None:
    show = tmp_path / "club.json"
    show.write_text(json.dumps(offline(appendix_a)))
    folder = tmp_path / "state" / "busk" / "autosave" / "show-01"
    folder.mkdir(parents=True)
    (folder / "session.json").write_text(
        json.dumps(
            {
                "programmer": {
                    "selection": [],
                    "values": {"fx-mh1:0/pan": {"kind": "literal", "value": 1}},
                    "blind": False,
                },
                "masterLevels": {},
                "showPath": str(show),
                "showAutosave": None,
                "cleanExit": False,
            }
        )
    )
    env = {**os.environ, "XDG_STATE_HOME": str(tmp_path / "state")}
    base = [sys.executable, "-m", "busk", "run", str(show), "--duration", "0.3"]
    plain = subprocess.run(
        [*base, "--no-recover"], input="", capture_output=True, text=True, env=env, check=False
    )
    assert "recovered" not in plain.stdout
    (folder / "session.json").write_text(
        json.dumps(
            {
                "programmer": {
                    "selection": [],
                    "values": {"fx-mh1:0/pan": {"kind": "literal", "value": 1}},
                    "blind": False,
                },
                "masterLevels": {},
                "showPath": str(show),
                "showAutosave": None,
                "cleanExit": False,
            }
        )
    )
    recovering = subprocess.run(
        base, input="", capture_output=True, text=True, env=env, check=False
    )
    assert "recovered programmer with 1 value, 0 master levels" in recovering.stdout


def test_saved_programmer_effects_come_back_and_invalid_ones_are_dropped(
    tmp_path: Path, appendix_a: dict[str, Any]
) -> None:
    show = tmp_path / "club.json"
    show.write_text(json.dumps(offline(appendix_a)))
    folder = tmp_path / "state" / "busk" / "autosave" / "show-01"
    folder.mkdir(parents=True)
    pulse = effect_instance("fx1", "ef-pulse", {"kind": "group", "groupId": "g-mh"}, size=0.5)
    gone = {**pulse, "id": "fx2", "templateId": "ef-gone"}
    session = {
        "programmer": {"selection": [], "values": {}, "effects": [pulse, gone], "blind": False},
        "masterLevels": {},
        "showPath": str(show),
        "showAutosave": None,
        "cleanExit": False,
    }
    (folder / "session.json").write_text(json.dumps(session))
    env = {**os.environ, "XDG_STATE_HOME": str(tmp_path / "state")}
    command = [sys.executable, "-m", "busk", "run", str(show), "--duration", "0.3"]
    run = subprocess.run(command, input="", capture_output=True, text=True, env=env, check=False)
    assert run.returncode == 0, run.stderr
    assert "recovered programmer with 0 values, 1 effect, 0 master levels" in run.stdout
    assert (
        "recovery: dropped programmer effect 'fx2': Unknown effect template 'ef-gone'" in run.stderr
    )
    clean = json.loads((folder / "session.json").read_text())
    assert [effect["id"] for effect in clean["programmer"]["effects"]] == ["fx1"]
