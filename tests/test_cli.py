"""Command line: ``validate`` exit codes and ``run`` end to end (real threads, real clock).

``run`` tests use copies of the shows whose routes are disabled (``offline``)
or send unicast to a localhost receiver (``localhost_route``), so no packet
leaves the machine.
"""

from __future__ import annotations

import errno
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

import mido
import pytest

from builders import DEMO, ROOT, compile_doc, load_doc, localhost_route, offline
from busk.cli import main, status_line
from busk.engine.snapshot import EngineSnapshot, PageStatus, PlaybackStatus, SpeedStatus
from busk.io import midi
from busk.model.common import MasterId, PlaybackId
from harness import Harness, go
from sacn_receiver import Receiver

MIDI_PORTS = ["Midi Through:Midi Through Port-0 14:0"]


@pytest.fixture(autouse=True)
def no_midi_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    """``run`` sees one MIDI port that matches no surface, whatever is plugged
    in; tests that need a device patch ``input_names`` again."""
    monkeypatch.setattr(midi, "input_names", lambda: list(MIDI_PORTS))


def write_show(directory: Path, doc: dict[str, Any]) -> Path:
    path = directory / "show.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# ------------------------------------------------------------------ validate


def test_validate_appendix_a(appendix_a_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(appendix_a_path)]) == 0
    assert capsys.readouterr().out == "0 errors, 0 warnings\n"


def test_validate_broken_show(
    tmp_path: Path, appendix_a: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    appendix_a["fixtures"][2]["patch"]["address"] = 511
    appendix_a["playbacks"][0]["cueListId"] = "nope"
    assert main(["validate", str(write_show(tmp_path, appendix_a))]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "error   fixtures[2].patch.address: Footprint of 3 channel(s) starting at 511 ends at "
        "513, past channel 512",
        "error   playbacks[0].cueListId: Unknown cue list 'nope'",
        "2 errors, 0 warnings",
    ]


def test_validate_with_only_warnings_succeeds(
    tmp_path: Path, appendix_a: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    appendix_a["fixtures"][0]["profileRevision"] = "0"
    assert main(["validate", str(write_show(tmp_path, appendix_a))]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("warning fixtures[0].profileRevision: ")
    assert out[-1] == "0 errors, 1 warning"


def test_validate_invalid_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{"schemaVersion": 1,', encoding="utf-8")
    assert main(["validate", str(path)]) == 1
    assert capsys.readouterr().out.startswith("error   Invalid JSON at line 1")


def test_validate_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(tmp_path / "missing.json")]) == 1
    assert "cannot read" in capsys.readouterr().err


# ----------------------------------------------------------------------- run

STATS = re.compile(
    r"^engine: (?P<ticks>\d+) ticks @ 100 Hz, (?P<overruns>\d+) overruns, max tick [\d.]+ ms, "
    r"(?P<commands>\d+) commands?, (?P<errors>\d+) command errors?$",
    re.MULTILINE,
)


DEMO_LINE = (
    "U1 Stage: 1=170 2=85 3=170 4=85 6=37 7=5 8=255 9=19 "
    "13=85 14=128 15=85 18=2 19=88 20=255 21=3 25=204 26=102 "
    "29=255 34=255 35=255 40=255 41=255 46=255 47=255 52=255 53=255 58=255 59=255 64=255"
)  # chart-derived, see test_real_fixtures.DEMO_GOLDEN

APPENDIX_A_LINE = (
    "U1 Stage: 1=128 3=128 8=255 11=128 12=4 13=11 17=128 19=128 24=255 27=128 28=4 29=11"
)


def universe(line: str) -> bytes:
    """The 512 bytes a frame line such as ``U1 Stage: 1=170 2=85`` describes."""
    data = bytearray(512)
    for channel in line.partition(": ")[2].split():
        number, value = channel.split("=")
        data[int(number) - 1] = int(value)
    return bytes(data)


@pytest.fixture
def offline_demo(tmp_path: Path) -> Path:
    """The demo with its route disabled: ``run`` sends nothing."""
    return write_show(tmp_path, offline(load_doc(DEMO)))


def test_run_demo_with_values(
    offline_demo: Path, values_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = [
        "run",
        "--threads",
        str(offline_demo),
        "--values",
        str(values_path),
        "--duration",
        "0.3",
    ]
    assert main([*args, "--console"]) == 0
    captured = capsys.readouterr()
    assert captured.out.count(DEMO_LINE + "\n") == 1
    assert captured.out.startswith("sACN r1: disabled\n")
    assert "no output" not in captured.err  # --console is output
    stats = STATS.search(captured.out)
    assert stats is not None, captured.out
    assert int(stats["ticks"]) > 0


def test_run_demo_without_values_outputs_the_defaults(
    offline_demo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["run", "--threads", str(offline_demo), "--duration", "0.2", "--console"]) == 0
    # Pan/tilt centred, colour wheel, shutter (open, not blackout) and gobo at their defaults.
    assert (
        capsys.readouterr().out.count(
            "U1 Stage: 1=128 2=128 6=2 7=5 9=3 13=128 14=128 18=2 19=5 21=3\n"
        )
        == 1
    )


def test_run_appendix_a_opens_the_shutters(
    tmp_path: Path, appendix_a: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_show(tmp_path, offline(appendix_a))
    assert main(["run", "--threads", str(path), "--duration", "0.2", "--console"]) == 0
    assert capsys.readouterr().out.count(APPENDIX_A_LINE + "\n") == 1


def test_run_without_console_prints_no_frames(
    offline_demo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["run", "--threads", str(offline_demo), "--duration", "0.1"]) == 0
    captured = capsys.readouterr()
    assert "[frame" not in captured.out
    assert captured.err == "no output: no route is open (add --console to print frames)\n"
    assert STATS.search(captured.out)


def test_run_makes_the_web_key(offline_demo: Path, state_directory: Path) -> None:
    assert main(["run", "--threads", str(offline_demo), "--duration", "0.1"]) == 0
    assert len((state_directory / "web-key").read_text().strip()) == 8


def test_run_goes_on_when_the_web_key_cannot_be_saved(
    offline_demo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("")
    args = [
        "run",
        "--threads",
        str(offline_demo),
        "--duration",
        "0.1",
        "--state-dir",
        str(not_a_directory),
    ]
    assert main(args) == 0
    assert "web key not saved: " in capsys.readouterr().err


# -------------------------------------------------------------- run over sACN


def test_run_sends_the_demo_over_sacn(
    tmp_path: Path, values_path: Path, receiver: Receiver, capsys: pytest.CaptureFixture[str]
) -> None:
    """The done criterion: the golden bytes go out, then the stream is terminated."""
    doc = localhost_route(load_doc(DEMO))
    path = write_show(tmp_path, doc)
    assert (
        main(["run", "--threads", str(path), "--values", str(values_path), "--duration", "0.3"])
        == 0
    )

    packets = receiver.drain()
    # 0.3 s ends long before the first keep-alive (~0.98 s), so the count is exact:
    # the first frame, three repeats, then three Stream_Terminated packets.
    assert [(p.sequence, p.terminated) for p in packets] == [
        (0, False),
        (1, False),
        (2, False),
        (3, False),
        (4, True),
        (5, True),
        (6, True),
    ]
    assert {p.data for p in packets} == {universe(DEMO_LINE)}
    output = doc["output"]
    assert {(p.cid, p.sourceName, p.priority, p.universe, p.startCode) for p in packets} == {
        (uuid.UUID(output["sacnCid"]), output["sacnSourceName"], 100, 1, 0)
    }

    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert lines[0] == "sACN r1: U1 Stage → universe 1, unicast 127.0.0.1, priority 100"
    assert STATS.match(lines[-2]), lines
    assert lines[-1] == "sACN r1: 7 packets, 0 errors"
    assert "[frame" not in captured.out
    assert captured.err == ""


def test_two_runs_send_identical_packets(
    tmp_path: Path, values_path: Path, receiver: Receiver
) -> None:
    path = write_show(tmp_path, localhost_route(load_doc(DEMO)))
    runs = []
    for _ in range(2):
        assert (
            main(["run", "--threads", str(path), "--values", str(values_path), "--duration", "0.2"])
            == 0
        )
        runs.append(receiver.drain())
    assert len(runs[0]) == 7
    assert runs[0] == runs[1]


def test_run_reports_routes_it_does_not_send(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = load_doc(DEMO)
    routes = doc["output"]["routes"]
    routes[0]["destination"]["iface"] = "no-such-if0"
    routes.append(
        {
            "id": "r2",
            "universeId": "u1",
            "enabled": True,
            "protocol": "artnet",
            "portAddress": {"net": 0, "subNet": 0, "universe": 0},
            "destination": {"kind": "broadcast", "iface": "no-such-if0"},
        }
    )
    routes.append({**routes[0], "id": "r3", "enabled": False})
    routes.append(
        {
            "id": "r4",
            "universeId": "u1",
            "enabled": True,
            "protocol": "dmxUsb",
            "device": {"driver": "enttecOpen", "port": "/dev/ttyUSB0"},
            "refreshHz": 40,
        }
    )
    assert main(["run", "--threads", str(write_show(tmp_path, doc)), "--duration", "0.1"]) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines()[:2] == [
        "sACN r3: disabled",
        "DMX-USB r4: ignored (Open DMX USB needs host-timed breaks; "
        "use an Enttec Pro or DMXking interface)",
    ]
    available = ", ".join(name for _, name in socket.if_nameindex())
    assert captured.err.splitlines() == [
        f"sACN r1: cannot open: no network interface 'no-such-if0' (available: {available})",
        f"Art-Net r2: cannot open: no network interface 'no-such-if0' (available: {available})",
        "no output: no route is open (add --console to print frames)",
    ]
    assert STATS.search(captured.out)


def test_run_sends_dmx_usb_frames_to_a_serial_device(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    master, slave = os.openpty()  # the slave side stands in for /dev/ttyUSB0
    port = os.ttyname(slave)
    try:
        doc = load_doc(DEMO)
        doc["output"]["routes"] = [
            {
                "id": "r1",
                "universeId": doc["universes"][0]["id"],
                "enabled": True,
                "protocol": "dmxUsb",
                "device": {"driver": "enttecPro", "port": port},
                "refreshHz": 30,
            }
        ]
        assert main(["run", "--threads", str(write_show(tmp_path, doc)), "--duration", "0.2"]) == 0
        os.set_blocking(master, False)
        received = os.read(master, 65536)
    finally:
        os.close(slave)
        os.close(master)
    out = capsys.readouterr().out
    assert re.search(rf"^DMX-USB r1: U1 .* → Enttec DMX USB Pro on {port} at 30 Hz$", out, re.M)
    assert re.search(r"^DMX-USB r1: \d+ packets?, 0 errors$", out, re.M)
    # The parameters (rate 30 = 0x1e), then the first frame: label 6, 513 bytes.
    assert received.startswith(bytes.fromhex("7e 04 05 00 00 00 09 01 1e e7 7e 06 01 02 00"))


def test_run_reports_send_failures(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Without SO_BROADCAST the kernel refuses a broadcast before anything goes out.
    doc = load_doc(DEMO)
    doc["output"]["routes"][0]["destination"] = {"kind": "unicast", "host": "255.255.255.255"}
    assert main(["run", "--threads", str(write_show(tmp_path, doc)), "--duration", "0.3"]) == 0
    captured = capsys.readouterr()
    error = f"[Errno {errno.EACCES}] {os.strerror(errno.EACCES)}"
    assert captured.err == f"sACN r1: send failed: {error}\n"
    assert re.search(r"^sACN r1: 0 packets, [1-9]\d* errors?$", captured.out, re.MULTILINE)


def test_run_refuses_a_bad_values_file(
    tmp_path: Path, demo_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    values = tmp_path / "values.json"
    entry = {"slot": {"target": {"fixtureId": "fx-wash1", "element": 0}, "attribute": "zoom"}}
    values.write_text(json.dumps([{**entry, "value": 20}]), encoding="utf-8")
    assert (
        main(["run", "--threads", str(demo_path), "--values", str(values), "--duration", "0.1"])
        == 1
    )
    captured = capsys.readouterr()
    assert "error   values[0].slot.attribute: Fixture 'fx-wash1' element 0 has no 'zoom'" in (
        captured.err
    )
    assert "engine:" not in captured.out


def test_run_refuses_a_structurally_invalid_values_file(
    tmp_path: Path, demo_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    values = tmp_path / "values.json"
    values.write_text('{"not": "a list"}', encoding="utf-8")
    assert (
        main(["run", "--threads", str(demo_path), "--values", str(values), "--duration", "0.1"])
        == 1
    )
    assert "error   values: Input should be a valid array" in capsys.readouterr().err


def test_run_refuses_a_missing_values_file(
    tmp_path: Path, demo_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.json"
    assert (
        main(["run", "--threads", str(demo_path), "--values", str(missing), "--duration", "0.1"])
        == 1
    )
    assert "cannot read" in capsys.readouterr().err


def test_run_refuses_an_invalid_show(
    tmp_path: Path, appendix_a: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    appendix_a["playbacks"][0]["cueListId"] = "nope"
    assert (
        main(["run", "--threads", str(write_show(tmp_path, appendix_a)), "--duration", "0.1"]) == 1
    )
    captured = capsys.readouterr()
    assert "playbacks[0].cueListId: Unknown cue list 'nope'" in captured.err
    assert "engine:" not in captured.out


def test_run_prints_warnings_and_still_runs(
    tmp_path: Path, appendix_a: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    appendix_a["fixtures"][0]["profileRevision"] = "0"
    assert (
        main(
            [
                "run",
                "--threads",
                str(write_show(tmp_path, offline(appendix_a))),
                "--duration",
                "0.1",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert "warning fixtures[0].profileRevision" in captured.err
    assert STATS.search(captured.out)


def test_run_refuses_an_unsupported_element_patch(
    tmp_path: Path, appendix_a: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    appendix_a["fixtures"][2]["elementPatch"] = {"0": {"universeId": "u1", "address": 200}}
    assert (
        main(["run", "--threads", str(write_show(tmp_path, appendix_a)), "--duration", "0.1"]) == 1
    )
    assert "elementPatch: split patches are not supported yet" in capsys.readouterr().err


@pytest.mark.parametrize("duration", ["0", "-1", "soon", "nan"])
def test_run_rejects_bad_durations(demo_path: Path, duration: str) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["run", "--threads", str(demo_path), "--duration", duration])
    assert exit_info.value.code == 2


def test_python_dash_m_entry_point(appendix_a_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "busk", "validate", str(appendix_a_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode, result.stdout) == (0, "0 errors, 0 warnings\n")


# ------------------------------------------------------------ Phase 2: busking

PHASE2 = ROOT / "examples" / "phase2-busk.json"


def test_validate_the_phase_2_demo(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(PHASE2)]) == 0
    assert capsys.readouterr().out == "0 errors, 0 warnings\n"


def test_run_appendix_a_ignores_nothing(
    tmp_path: Path, appendix_a: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_show(tmp_path, offline(appendix_a))
    assert main(["run", "--threads", str(path), "--duration", "0.3"]) == 0
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    # effects, `size` faders (Phase 5), soft pickup (Phase 6) and limits (Phase 7) work
    assert "Ignored" not in captured.out
    assert lines[0] == "sACN r1: disabled"
    assert "GM 100% | BO off | P1 Main | Speed 1 120 BPM ×1" in lines
    stats = STATS.search(captured.out)
    assert stats is not None
    assert (stats["commands"], stats["errors"]) == ("0", "0")
    # The missing controller is reported with the ports that exist, and the run goes on.
    assert (
        "MIDI s-midi: 'nanoKONTROL2' not found; available: Midi Through:Midi Through Port-0 14:0"
        in captured.err.splitlines()
    )


def test_run_prints_what_phase_7_ignores(
    tmp_path: Path, appendix_a: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """The limitation block, under its Phase 7 header, with its paths."""
    appendix_a["surfaces"].append(
        {"id": "s-int", "name": "Panel", "kind": "internal", "match": {}, "faderPickup": "jump"}
    )
    path = write_show(tmp_path, offline(appendix_a))
    assert main(["run", "--threads", str(path), "--duration", "0.2"]) == 0
    lines = capsys.readouterr().out.splitlines()
    start = lines.index("Ignored in Phase 7:")
    assert lines[start + 1] == "  surfaces[1].kind: internal surfaces are not implemented"


def test_info_with_threads_names_one_process(
    tmp_path: Path, appendix_a: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_show(tmp_path, offline(appendix_a))
    script = tmp_path / "info.busk"
    script.write_text("info\n", encoding="utf-8")
    args = ["run", "--threads", str(path), "--script", str(script), "--duration", "0.2"]
    assert main(args) == 0
    assert f"processes: one (--threads), pid {os.getpid()}" in capsys.readouterr().out.splitlines()


def test_run_the_phase_2_demo_has_no_limitations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_show(tmp_path, offline(load_doc(PHASE2)))
    assert main(["run", "--threads", str(path), "--duration", "0.2"]) == 0
    captured = capsys.readouterr()
    assert "Ignored" not in captured.out
    assert captured.out.startswith("sACN r1: disabled\n")
    assert "MIDI s-nano: 'nanoKONTROL2' not found" in captured.err


def test_run_when_the_midi_backend_cannot_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def broken() -> list[str]:
        raise OSError("ALSA lib seq_hw.c: cannot open /dev/snd/seq")

    monkeypatch.setattr(midi, "input_names", broken)
    path = write_show(tmp_path, offline(load_doc(PHASE2)))
    assert main(["run", "--threads", str(path), "--duration", "0.1"]) == 0
    captured = capsys.readouterr()
    assert "MIDI s-nano: unavailable: ALSA lib seq_hw.c: cannot open /dev/snd/seq" in captured.err
    assert STATS.search(captured.out)


def test_run_prints_compile_warnings(
    tmp_path: Path, appendix_a: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    entries = appendix_a["cueLists"][1]["cues"][0]["entries"]
    entries.append(
        {"targets": {"kind": "group", "groupId": "g-mh"}, "attribute": "gobo1",
         "value": {"kind": "literal", "value": {"slot": "dots"}}}
    )  # fmt: skip
    assert (
        main(
            [
                "run",
                "--threads",
                str(write_show(tmp_path, offline(appendix_a))),
                "--duration",
                "0.1",
            ]
        )
        == 0
    )
    assert (
        "warning cueLists[1].cues[0].entries[2].value: fx-mh1:0 has no 'gobo1' option 'dots'; "
        "it offers 'open', 'breakup'; dropped for that target"
    ) in capsys.readouterr().err.splitlines()


class FakePort:
    """Stands in for a mido input port: the test drives its callback."""

    def __init__(self, name: str, callback: Any) -> None:
        self.name, self.callback = name, callback
        self.closed = threading.Event()

    def close(self) -> None:
        self.closed.set()


NANO = "nanoKONTROL2:nanoKONTROL2 _ CTRL 20:0"


def test_busk_with_midi_faders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``run`` on the demo with a (fake) nanoKONTROL2: CC messages on its
    callback thread become commands, and the status line follows them."""
    ports: list[FakePort] = []
    opened = threading.Event()

    def open_input(name: str, callback: Any) -> FakePort:
        ports.append(FakePort(name, callback))
        opened.set()
        return ports[-1]

    monkeypatch.setattr(midi, "input_names", lambda: [*MIDI_PORTS, NANO])
    monkeypatch.setattr(midi.mido, "open_input", open_input)
    path = write_show(tmp_path, offline(load_doc(PHASE2)))
    result: list[int] = []
    run = threading.Thread(
        target=lambda: result.append(main(["run", "--threads", str(path), "--duration", "1.5"]))
    )
    run.start()
    assert opened.wait(5)
    send = ports[0].callback
    gap = 0.25  # > the CLI's 0.1 s status poll, so every step gets its own line

    def cc(control: int, value: int) -> None:
        send(mido.Message("control_change", channel=0, control=control, value=value))

    time.sleep(gap)
    cc(0, 127)  # fader 1: Warm up (autoStart)
    time.sleep(gap)
    cc(34, 127)  # S3: toggle Blue
    cc(34, 0)
    time.sleep(gap)
    cc(42, 127)  # ■: blackout latches on (Phase 6)
    cc(42, 0)
    time.sleep(gap)
    cc(42, 127)  # ■ again: off
    cc(42, 0)
    cc(23, 0)  # knob 8: grand master to 0
    run.join(10)
    assert result == [0]
    assert ports[0].closed.is_set()
    lines = capsys.readouterr().out.splitlines()
    assert f"MIDI s-nano: {NANO}" in lines
    status = [line for line in lines if line.startswith("GM ")]
    assert status[0] == "GM 100% | BO off | P1 Main"
    assert "GM 100% | BO off | P1 Main | 1 Warm on 1.00" in status
    assert "GM 100% | BO off | P1 Main | 1 Warm on 1.00 · 3 Blue on" in status
    assert "GM 100% | BO on | P1 Main | 1 Warm on 1.00 · 3 Blue on" in status
    assert status[-1] == "GM 0% | BO off | P1 Main | 1 Warm on 1.00 · 3 Blue on"
    stats = STATS.search("\n".join(lines))
    assert stats is not None
    # Fader, S3 press and release (Phase 6: the engine gets both edges),
    # two blackout toggles, GM.
    assert (stats["commands"], stats["errors"]) == ("6", "0")


def test_status_line() -> None:
    def status(
        number: int,
        name: str,
        state: str,
        fader: float = 0.0,
        flash: bool = False,
        **more: Any,
    ) -> PlaybackStatus:
        return PlaybackStatus(
            id=PlaybackId(name), number=number, name=name, state=state,  # type: ignore[arg-type]
            faderLevel=fader, flash=flash, **more,
        )  # fmt: skip

    snapshot = EngineSnapshot(
        seq=1,
        time=0.0,
        grandMaster=0.8,
        blackout=False,
        playbacks=(
            status(1, "Warm", "active", 0.75),
            status(2, "Cool", "idle"),
            status(3, "Blue", "releasing"),
            status(5, "Green", "idle", 0.25),
            status(8, "Panic", "idle", flash=True),
        ),
    )
    assert status_line(snapshot) == (
        "GM 80% | BO off | 1 Warm on 0.75 · 3 Blue rel · 5 Green 0.25 · 8 Panic flash"
    )
    assert status_line(
        EngineSnapshot(seq=2, time=0.0, grandMaster=1.0, blackout=True, playbacks=())
    ) == ("GM 100% | BO on")
    page = PageStatus(id="page-2", number=2, name="Washes")  # shown after blackout (Phase 6)
    assert status_line(replace(snapshot, page=page)) == (
        "GM 80% | BO off | P2 Washes | 1 Warm on 0.75 · 3 Blue rel · 5 Green 0.25 · 8 Panic flash"
    )


def test_the_status_line_shows_tempo_cues_and_master_size_and_temp_faders() -> None:
    def status(number: int, name: str, state: str, level: float, **more: Any) -> PlaybackStatus:
        return PlaybackStatus(
            id=PlaybackId(name), number=number, name=name, state=state,  # type: ignore[arg-type]
            faderLevel=level, flash=False, cueCount=4, **more,
        )  # fmt: skip

    def speed(name: str, bpm: float, multiplier: float) -> SpeedStatus:
        return SpeedStatus(
            id=MasterId(name), name=name, bpm=bpm, multiplier=multiplier, level=0.5,
            beatTime=0.0, beat=0.0,
        )  # fmt: skip

    snapshot = EngineSnapshot(
        seq=1,
        time=0.0,
        grandMaster=1.0,
        blackout=False,
        playbacks=(
            status(9, "Song", "active", 1.0, cue="3", cueName="Pre", next="4"),
            status(10, "Washes", "active", 0.5, fader="rate", cue="2", chase=True),
            status(11, "Idle chase", "idle", 0.5, fader="rate", chase=True),  # resting: not listed
            status(12, "Pulse", "idle", 0.4, fader="size"),  # listed since Phase 5
            status(13, "Hit", "idle", 0.3, fader="temp"),
            status(14, "Stack", "releasing", 0.0, cue="2.5"),  # an unnamed cue
            replace(status(15, "Look", "active", 0.0, cue="1", cueName="Look"), cueCount=1),
            status(16, "Circle", "active", 0.0, fader="size"),  # fader down: no level
        ),
        speed=(speed("Speed 1", 128.0, 2.0), speed("Speed 2", 127.53, 0.25)),
    )
    assert status_line(snapshot) == (
        "GM 100% | BO off | Speed 1 128 BPM ×2 · Speed 2 127.5 BPM ×0.25"
        " | 9 Song on 3 Pre 1.00 · 10 Washes on · 12 Pulse 0.40 · 13 Hit 0.30"
        " · 14 Stack rel 2.5 · 15 Look on · 16 Circle on"
    )


def test_a_running_chase_does_not_change_the_status_line(appendix_a: dict[str, Any]) -> None:
    appendix_a["cueLists"][0].update(
        mode="chase",
        chase={"rate": {"kind": "hz", "value": 4.0}, "direction": "forward", "crossfade": 0},
    )
    harness = Harness(compile_doc(appendix_a))
    harness.run([(0.0, go("pb-song"))], [0.0])
    snapshots = [harness.tick((k + 0.5) / 4).snapshot for k in range(1, 9)]  # one per step
    assert len({snapshot.seq for snapshot in snapshots if snapshot is not None}) == 8
    lines = {status_line(snapshot) for snapshot in snapshots if snapshot is not None}
    assert lines == {"GM 100% | BO off | P1 Main | Speed 1 120 BPM ×1 | 1 Song on"}


# ------------------------------------------------------------ Phase 3: console

PHASE3_SCRIPT = ROOT / "examples" / "phase3-build.busk"


def test_new_writes_a_valid_template_and_never_overwrites(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "shows" / "club.show"
    assert (
        main(["new", str(path), "--title", "Club Night", "--state-dir", str(tmp_path / "s")]) == 0
    )
    assert capsys.readouterr().out == f"created {path}\n"
    assert main(["validate", str(path)]) == 0
    assert capsys.readouterr().out == "0 errors, 0 warnings\n"
    show = json.loads(zipfile.ZipFile(path).read("show.json"))
    assert show["meta"]["title"] == "Club Night"
    assert show["output"]["sacnCid"] == (tmp_path / "s" / "cid").read_text().strip()
    assert main(["new", str(path)]) == 1
    assert "exists; not overwriting it" in capsys.readouterr().err


def test_run_a_script_then_busk(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The done criterion through the CLI: the script builds and saves the show."""
    path = tmp_path / "club.show"
    assert main(["new", str(path)]) == 0
    script = tmp_path / "build.busk"
    # The example script, minus its multicast route (tests never send to a network).
    script.write_text(PHASE3_SCRIPT.read_text().replace("route add 1 sacn 1\n", ""))
    capsys.readouterr()
    assert main(["run", "--threads", str(path), "--script", str(script), "--duration", "0.3"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "added universe 'Stage'"
    assert f"saved {path}" in out
    assert STATS.search("\n".join(out))
    assert main(["validate", str(path)]) == 0


def test_a_failing_script_stops_at_its_first_error(
    tmp_path: Path, appendix_a: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    script = tmp_path / "bad.busk"
    script.write_text("sel group 1\nsel group 7\nset pan 1\n")
    path = write_show(tmp_path, offline(appendix_a))
    assert main(["run", "--threads", str(path), "--script", str(script), "--duration", "5"]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out[out.index("2 targets selected") + 1 :][:2] == [
        f"{script}:2: sel group 7",
        "error: no group 7",
    ]
    assert STATS.search("\n".join(out))


def test_run_reads_commands_from_stdin(tmp_path: Path, appendix_a: dict[str, Any]) -> None:
    path = write_show(tmp_path, offline(appendix_a))
    env = {**os.environ, "XDG_STATE_HOME": str(tmp_path / "state")}
    result = subprocess.run(
        [sys.executable, "-m", "busk", "run", str(path)],
        input="sel group 1\nset pan 30\nprogrammer\nfader 3 1\nrecord preset position 9\n",
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout.splitlines()
    assert "selection: 101, 102" in out
    assert "  101 pan = 30" in out
    assert "recorded preset position 9 'Position 9': 2 values" in out
    assert "unsaved edits kept in" in result.stdout  # stdin's end quits; edits stay in an autosave


def test_no_console_reads_nothing(tmp_path: Path, appendix_a: dict[str, Any]) -> None:
    path = write_show(tmp_path, offline(appendix_a))
    env = {**os.environ, "XDG_STATE_HOME": str(tmp_path / "state")}
    result = subprocess.run(
        [sys.executable, "-m", "busk", "run", str(path), "--no-console", "--duration", "0.3"],
        input="quit\n",
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    assert STATS.search(result.stdout)
    assert "selected" not in result.stdout


def test_a_corrupt_show_names_its_newest_backup(
    tmp_path: Path, appendix_a: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "club.show"
    assert main(["new", str(path)]) == 0
    backups = tmp_path / "club.backups"
    backups.mkdir()
    (backups / "club-20261011T120000000000Z.show").write_bytes(path.read_bytes())
    path.write_bytes(b"garbage")
    assert main(["run", "--threads", str(path), "--duration", "0.1"]) == 1
    err = capsys.readouterr().err
    assert "Not a valid .show file" in err
    assert f"the newest backup is {backups / 'club-20261011T120000000000Z.show'}" in err


class FakeOutput:
    """Stands in for a mido output port: records what the feedback thread sends."""

    def __init__(self, name: str) -> None:
        self.name, self.sent = name, list[mido.Message]()
        self.closed = threading.Event()

    def send(self, message: mido.Message) -> None:
        self.sent.append(message)

    def close(self) -> None:
        self.closed.set()


def free_port(kind: socket.SocketKind) -> int:
    """A localhost port of ``kind`` that nothing listens on now."""
    with socket.socket(socket.AF_INET, kind) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_run_opens_every_surface_and_sends_feedback(
    tmp_path: Path,
    state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``run`` with a (fake) nanoKONTROL2, an OSC app and a phone: one
    start-up line per surface and feedback port before the run starts, the
    feedback thread lighting the stop LED while blackout is on, and the
    feedback port closed at the end (phase-6-plan §5.13)."""
    doc = offline(load_doc(PHASE2))
    stop = next(b for b in doc["bindings"] if b["action"]["kind"] == "blackout")
    stop["feedback"] = {"kind": "led", "address": stop["input"]}
    osc_port, web_port = free_port(socket.SOCK_DGRAM), free_port(socket.SOCK_STREAM)
    doc["surfaces"] += [
        {"id": "s-osc", "name": "TouchOSC", "kind": "osc", "match": {"port": osc_port},
         "faderPickup": "jump"},
        {"id": "s-phone", "name": "Phone", "kind": "web",
         "match": {"port": web_port, "host": "127.0.0.1"}, "faderPickup": "jump"},
    ]  # fmt: skip
    inputs: list[FakePort] = []
    outputs: list[FakeOutput] = []

    def open_input(name: str, callback: Any) -> FakePort:
        inputs.append(FakePort(name, callback))
        return inputs[-1]

    def open_output(name: str) -> FakeOutput:
        outputs.append(FakeOutput(name))
        return outputs[-1]

    monkeypatch.setattr(midi, "input_names", lambda: [NANO])
    monkeypatch.setattr(midi, "output_names", lambda: [NANO])
    monkeypatch.setattr(midi.mido, "open_input", open_input)
    monkeypatch.setattr(midi.mido, "open_output", open_output)
    path = write_show(tmp_path, doc)
    result: list[int] = []
    run = threading.Thread(
        target=lambda: result.append(main(["run", "--threads", str(path), "--duration", "1.5"]))
    )
    run.start()

    def led(value: int) -> bool:
        return any(
            m.type == "control_change" and m.control == stop["input"]["cc"] and m.value == value
            for m in (outputs[0].sent if outputs else [])
        )

    deadline = time.monotonic() + 5
    while not led(0) and time.monotonic() < deadline:  # every value on open
        time.sleep(0.01)
    assert led(0)
    assert not led(127)
    press = mido.Message("control_change", channel=0, control=stop["input"]["cc"], value=127)
    inputs[0].callback(press)
    inputs[0].callback(press.copy(value=0))
    run.join(10)
    assert result == [0]
    assert led(127)
    assert outputs[0].closed.is_set()
    assert inputs[0].closed.is_set()
    lines = capsys.readouterr().out.splitlines()
    startup = lines[: next(k for k, line in enumerate(lines) if line.startswith("GM "))]
    key = (state_directory / "web-key").read_text().strip()
    assert f"MIDI s-nano: {NANO}" in startup
    assert f"MIDI s-nano feedback: {NANO}" in startup
    assert f"OSC s-osc: listening on udp {osc_port}, feedback to the sender" in startup
    assert f"Web s-phone: http://127.0.0.1:{web_port}/?k={key}" in startup
