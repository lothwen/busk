"""The CLI's transcripts: stdout, stderr and exit codes, byte for byte
(phase-8-plan §6 step 1).

Phase 8 rebuilds the CLI on the public API, and the CLI's output is its
interface for the user, so every step must leave it unchanged. Each case
runs one command and compares its masked transcript with
``tests/golden/cli/<case>.txt``, recorded from the CLI as it was before
Phase 8 and reviewed by hand. Regenerate them with ``BUSK_REGOLDEN=1``
only after a deliberate change, then review the diff.

A transcript names the command, its exit code, then stdout and stderr,
each line indented by two spaces (``\\ no newline at end`` marks output
that does not end with one). What varies from run to run is masked:

* ids (``<prefix>-<12 hex>``), as ``<prefix>-<id>``;
* the repository and temporary paths, as ``<repo>`` and ``<tmp>``;
* pids, as ``pid <n>``;
* the counters and times of the ``engine:`` and route statistics lines.

In process mode the root's and the console's lines interleave in any
order, so that case compares the sorted lines of each stream. It also
leaves out the root's ``no output: no route is open`` warning: the root
prints it only when the engine's first layout comes before the script has
added the route, which is a race.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
from collections.abc import Callable
from pathlib import Path

import pytest

from builders import ROOT
from busk.cli import main
from busk.io import midi
from gdtf_builder import archive
from process_harness import BuskRun
from test_gdtf import spot

GOLDEN = Path(__file__).parent / "golden" / "cli"
REGOLDEN = os.environ.get("BUSK_REGOLDEN") == "1"
APPENDIX_A = ROOT / "tests" / "fixtures" / "appendix_a.json"
OFL = ROOT / "tests" / "fixtures" / "ofl" / "tupperdmx"
SCRIPT = ROOT / "tests" / "fixtures" / "phase3-build.busk"
MIDI_PORTS = ["Midi Through:Midi Through Port-0 14:0"]
"""The one MIDI port every run sees, as in test_cli."""

ID = re.compile(r"\b([a-z]+)-[0-9a-f]{12}\b")
PID = re.compile(r"\bpid \d+")
ENGINE_STATS = re.compile(
    r"^engine: \d+ ticks @ (\d+) Hz, \d+ overruns, max tick [\d.]+ ms, \d+ commands, "
    r"\d+ command errors$",
    re.MULTILINE,
)
NO_ROUTE = "no output: no route is open (add --console to print frames)"
ROUTE_STATS = re.compile(r"^(\S+ \S+): \d+ packets, \d+ errors$", re.MULTILINE)


@pytest.fixture(autouse=True)
def one_midi_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """The in-process runs see :data:`MIDI_PORTS`, whatever is plugged in."""
    monkeypatch.setattr(midi, "input_names", lambda: list(MIDI_PORTS))


def mask(text: str, tmp: Path) -> str:
    """``text`` with what varies between runs replaced (see the module docs)."""
    text = text.replace(str(tmp), "<tmp>").replace(str(ROOT), "<repo>")
    text = ID.sub(r"\1-<id>", text)
    text = PID.sub("pid <n>", text)
    text = ENGINE_STATS.sub(
        r"engine: <n> ticks @ \1 Hz, <n> overruns, max tick <t> ms, <n> commands, "
        r"<n> command errors",
        text,
    )
    return ROUTE_STATS.sub(r"\1: <n> packets, <n> errors", text)


def stream(name: str, text: str) -> list[str]:
    """One stream of a transcript: its name, then its lines, indented."""
    lines = [f"{name}:"]
    for line in text.splitlines(keepends=True):
        lines.append("  " + line.removesuffix("\n"))
        if not line.endswith("\n"):
            lines.append("\\ no newline at end")
    return lines


def transcript(argv: list[str], code: int, out: str, err: str, tmp: Path) -> str:
    """The masked transcript of one command."""
    command = mask("$ " + shlex.join(["busk", *argv]), tmp)
    out, err = mask(out, tmp), mask(err, tmp)
    lines = [command, f"exit {code}", *stream("stdout", out), *stream("stderr", err)]
    return "\n".join(lines) + "\n"


def check(case: str, text: str) -> None:
    """Compare ``text`` with the golden of ``case`` (or write it, with ``BUSK_REGOLDEN=1``)."""
    path = GOLDEN / f"{case}.txt"
    if REGOLDEN:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert text == path.read_text(encoding="utf-8")


def run(
    argv: list[str], tmp: Path, capsys: pytest.CaptureFixture[str], extra: Callable[[], str] = str
) -> str:
    """Run ``busk argv`` in this process; its transcript, followed by ``extra()``."""
    capsys.readouterr()
    code = main(argv)
    captured = capsys.readouterr()
    return transcript(argv, code, captured.out, captured.err, tmp) + mask(extra(), tmp)


def hashes(directory: Path) -> str:
    """One ``sha256`` line per file in ``directory``, by name."""
    return "".join(
        f"sha256 {path.name} {hashlib.sha256(path.read_bytes()).hexdigest()}\n"
        for path in sorted(directory.iterdir())
    )


def new_show(tmp: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    """A ``busk new`` show in ``tmp`` (not part of any transcript)."""
    path = tmp / "club.show"
    assert main(["new", str(path), "--state-dir", str(tmp / "state")]) == 0
    capsys.readouterr()
    return path


# ------------------------------------------------------------------ the cases


def test_validate_appendix_a(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    check("validate-appendix-a", run(["validate", str(APPENDIX_A)], tmp_path, capsys))


def test_validate_a_broken_show(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = json.loads(APPENDIX_A.read_text(encoding="utf-8"))
    doc["fixtures"][2]["patch"]["address"] = 511  # past the universe's end
    doc["playbacks"][0]["cueListId"] = "nope"
    doc["fixtures"][0]["profileRevision"] = "0"  # a warning
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(doc), encoding="utf-8")
    check("validate-broken", run(["validate", str(broken)], tmp_path, capsys))


def test_validate_a_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    check("validate-missing", run(["validate", str(tmp_path / "nope.json")], tmp_path, capsys))


def test_new(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["new", str(tmp_path / "club.show"), "--title", "Club Night"]
    argv += ["--state-dir", str(tmp_path / "state")]
    check("new", run(argv, tmp_path, capsys) + run(argv, tmp_path, capsys))


def test_import_ofl(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "profiles"
    argv = ["import", "ofl", *(str(p) for p in sorted(OFL.glob("*.json")))]
    argv += ["--out", str(out), "--report"]
    check("import-ofl", run(argv, tmp_path, capsys, lambda: hashes(out)))


def test_import_gdtf(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "profiles"
    spot_file = archive(tmp_path / "spot.gdtf", spot())
    broken = archive(tmp_path / "broken.gdtf", b"<GDTF/>")
    argv = ["import", "gdtf", str(spot_file), str(broken), "--out", str(out), "--report"]
    check("import-gdtf", run(argv, tmp_path, capsys, lambda: hashes(out)))


RUN = ["--no-console", "--duration", "1", "--iface", "lo", "--script", str(SCRIPT)]
"""The ``run`` options of both modes: the Phase 3 build on a new show, then 1 s."""


def test_run_with_threads(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    show = new_show(tmp_path, capsys)
    argv = ["run", "--threads", str(show), *RUN, "--state-dir", str(tmp_path / "state")]
    check("run-threads", run(argv, tmp_path, capsys))


def test_run_with_processes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    show = new_show(tmp_path, capsys)
    args = [*RUN, "--state-dir", str(tmp_path / "state")]
    with BuskRun(show, *args, midi_ports=MIDI_PORTS) as process:
        code = process.wait(timeout=60)
        out = sorted(process.out)
        err = sorted(line for line in process.err if line != NO_ROUTE)
    joined = ("".join(f"{line}\n" for line in lines) for lines in (out, err))
    check("run-processes", transcript(["run", str(show), *args], code, *joined, tmp_path))
