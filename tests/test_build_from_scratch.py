"""The Phase 3 done criterion: build a complete busking show from `busk new`
with console commands only (phase-3-plan, "Done when").

The build runs ``tests/fixtures/phase3-build.busk`` against a session and a real
engine on a fake clock, with counter ids, a fixed wall clock and a fixed
installation CID, so it is deterministic. Goldens live in ``tests/golden/``;
regenerate them with ``BUSK_REGOLDEN=1`` after a deliberate change, then
review the diff.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from builders import ROOT
from busk.commands.types import Command
from busk.compiler.compile import compile_show
from busk.console.console import Console
from busk.engine.clock import FakeClock
from busk.engine.loop import Engine
from busk.model.show import Show
from busk.model.validate import validate_show
from busk.persistence.paths import installation_cid
from busk.persistence.show_file import load_show, new_show, read_show_bytes
from busk.session.ids import CounterIds
from busk.session.library import ProfileLibrary
from busk.session.session import Session

SCRIPT = ROOT / "tests" / "fixtures" / "phase3-build.busk"
GOLDEN = Path(__file__).parent / "golden"
NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)
CID = "0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f"
REGOLDEN = os.environ.get("BUSK_REGOLDEN") == "1"


class Build:
    """``busk new`` + the build script, on a session with an engine."""

    def __init__(self, tmp_path: Path) -> None:
        state = tmp_path / "state"
        state.mkdir()
        (state / "cid").write_text(CID + "\n")  # an installation with a known CID
        ids = CounterIds()
        self.template = new_show("Club Night", ids=ids, now=NOW, cid=installation_cid(state))
        self.path = tmp_path / "club.show"
        compiled = compile_show(self.template)
        self.clock = FakeClock()
        self.engine = Engine(compiled, self.clock)
        self.session = Session(
            self.template,
            self.engine.bus,
            compiled=compiled,
            path=self.path,
            ids=ids,
            wall_clock=lambda: NOW,
        )
        self.console = Console(self.session, ProfileLibrary())
        self.output: list[str] = []
        self.ok = self.console.run_script(SCRIPT, self.output.append)

    def do(self, *lines: str) -> None:
        for line in lines:
            reply = self.console.execute(line)
            assert reply.ok, (line, reply.text)

    def tick(self, at: float) -> bytes:
        self.clock.sleep_until(at)
        self.engine.tick(at)
        assert self.engine.latest is not None
        return self.engine.latest.universes[0]


@pytest.fixture(scope="module")
def build(tmp_path_factory: pytest.TempPathFactory) -> Build:
    return Build(tmp_path_factory.mktemp("build"))


def channels(universe: bytes) -> dict[str, int]:
    """Non-zero channels, 1-based (JSON keys are strings)."""
    return {str(k + 1): value for k, value in enumerate(universe) if value}


def golden(name: str, actual: Any) -> Any:
    path = GOLDEN / name
    if REGOLDEN:
        path.write_text(json.dumps(actual, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_line_of_the_script_succeeds(build: Build) -> None:
    assert build.ok, build.output
    assert build.output[-1] == f"saved {build.path}"


def test_the_saved_show_matches_the_golden_and_validates(build: Build) -> None:
    saved = json.loads(read_show_bytes(build.path))
    assert saved == golden("phase3_built_show.json", saved)
    show, issues = validate_show(read_show_bytes(build.path))
    assert show is not None
    assert issues == []
    # Intent survived recording: looks reference groups and presets.
    blue = next(cl for cl in saved["cueLists"] if cl["name"] == "Blue")["cues"][0]
    assert [entry["targets"]["kind"] for entry in blue["entries"]] == ["group"]
    assert blue["entries"][0]["value"]["kind"] == "preset"


def busk(build: Build) -> tuple[bytes, bytes]:
    """Warm and Blue up: the frame after one tick, and once Blue's 1 s fade is done."""
    build.do("fader 1 1", "fader 3 1")
    start = build.tick(1.0)
    return start, build.tick(2.5)


def test_busking_the_built_show_gives_the_golden_frame(tmp_path: Path) -> None:
    build = Build(tmp_path)
    _, settled = busk(build)
    frame = golden("phase3_frames.json", {"warm_and_blue": channels(settled)})
    assert channels(settled) == frame["warm_and_blue"]
    # Worked out by hand: spot 1 at 1 (pan/tilt centred, RGBW blue, 16-bit dimmer
    # 0.8 = 204/204, zoom midpoint 128, gobo open 4, shutter open 11); ML-56 at 33
    # (virtual dimmer: blue × 0.8 = 204); the PiX's 12 cells from 49 (0 0 204 each).
    assert settled[0:13] == bytes([128, 0, 128, 0, 0, 0, 255, 0, 204, 204, 128, 4, 11])
    assert settled[32:36] == bytes([0, 0, 204, 0])
    assert settled[48:84] == bytes([0, 0, 204] * 12)


def test_a_live_preset_edit_reaches_output_through_references(tmp_path: Path) -> None:
    build = Build(tmp_path)
    _, before = busk(build)
    build.do("sel group 1", "set color 0 0.3 1", "record preset color 1 merge", "clear")
    # The edit fades with the cue's timing (phase-4-plan decision 14): Blue's 1 s fade in.
    assert build.tick(3.0)[4:8] == before[4:8]
    assert 0 < build.tick(3.5)[5] < 76
    after = build.tick(4.5)
    assert after[4:8] == bytes([0, 76, 255, 0]) != before[4:8]  # the heads' new blue
    assert after[32:36] == bytes([0, 61, 204, 0])  # global: the washes follow too
    preset = next(p for p in build.session.show["presets"] if p["name"] == "Blue")
    blue = next(cl for cl in build.session.show["cueLists"] if cl["name"] == "Blue")["cues"][0]
    assert blue["entries"][0]["value"] == {"kind": "preset", "presetId": preset["id"]}


def test_undo_everything_gives_the_template_and_redo_the_final_show(build: Build) -> None:
    session = build.session
    final = copy.deepcopy(session.show)
    steps = session.timeline.undo_count
    assert steps > 100
    for _ in range(steps):
        assert session.submit(cast(Command, {"type": "UNDO"})).ok
    assert session.show == build.template
    assert session.programmer.selection == ()
    assert dict(session.programmer.values) == {}
    for _ in range(steps):
        assert session.submit(cast(Command, {"type": "REDO"})).ok
    assert session.show == final
    assert build.engine.stats.installErrors == 0


def test_save_and_load_round_trip_and_play_the_same(tmp_path: Path) -> None:
    build = Build(tmp_path)
    loaded, warnings = load_show(build.path)
    assert loaded == build.session.show
    assert warnings == []
    _, settled = busk(build)
    fresh = Engine(compile_show(cast(Show, loaded)), FakeClock())
    for playback in ("1", "3"):
        number = int(playback)
        ident = next(p["id"] for p in loaded["playbacks"] if p["number"] == number)
        fresh.bus.submit(cast(Command, {"type": "SET_FADER", "playbackId": ident, "level": 1.0}))
    fresh.tick(1.0)
    fresh.tick(2.5)
    assert fresh.latest is not None
    assert fresh.latest.universes[0] == settled
