"""The soak harness (phase-7-plan §5.25, step 19).

The unit tests check the harness's own rules on made-up readings: which gaps
are drops (decision 23), when a chaos action counts as recovered, the
overrun and memory sums, the receiver's sequence rules and Enttec framing,
and that the load leaves the Circle alone (universe 1 must change every
cycle). They run by default.

``test_a_one_minute_fast_soak_passes`` (marker ``soak``, excluded by default
like ``perf``) is the real thing: ``bench/soak.py`` for 60 s in ``fast``
chaos, with one engine kill, one DMX-USB unplug and one console kill. It
must pass. Run it with ``uv run pytest -m soak -s``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from builders import ROOT

sys.path.insert(0, str(ROOT / "bench"))

import soak
import soak_load
import soak_receiver

T = 1_000_000.0
"""The readings' start (wall-clock seconds)."""


def sample(t: float, pid: int = 10, ticks: int = 100, **fields: Any) -> soak.Sample:
    """A ``--stats`` sample ``t`` seconds into the run."""
    values: dict[str, Any] = {
        "t": T + t,
        "enginePid": pid,
        "state": "running",
        "ticks": ticks,
        "overruns": 0,
        "maxTickMs": 1.0,
        "tickErrors": 0,
        "installErrors": 0,
        "commandErrors": 0,
        "gcPauseMs": 0.1,
        "engineRss": 50 << 20,
        "engineRestarts": 0,
        "consolePid": 20,
        "consoleRestarts": 0,
        "consoleRss": 60 << 20,
        "rootRss": 70 << 20,
        "lateCycles": 0,
        "longestGapMs": 23.0,
    }
    return soak.Sample(**(values | fields))


def gap(route: str, t0: float, t1: float, changed: bool = True) -> dict[str, Any]:
    return {"event": "gap", "route": route, "t0": T + t0, "t1": T + t1, "changed": changed}


def counted(at: float, last: float | None = None) -> dict[str, Any]:
    """A receiver count line at ``at``: every route's last packet at ``last``."""
    stamp = T + (at if last is None else last)
    routes = {r: {"packets": 100, "changes": 100, "last": stamp} for r in soak.ROUTES}
    return {"event": "count", "t": T + at, "routes": routes}


def killed(at: float, pid: int = 10) -> dict[str, Any]:
    return {"t": T + at, "action": "engineKill", "pid": pid}


def drops_of(readings: soak.Readings, end: float = 100.0) -> list[dict[str, Any]]:
    windows = [outage.window() for outage in soak.outages(readings)]
    return soak.drops(readings, (T + 3.0, T + end), windows)


# ------------------------------------------------------------------- drops


def test_a_gap_outside_outages_is_a_drop() -> None:
    readings = soak.Readings(receiver=[gap("artnet", 10.0, 10.05)], counts=counted(100.0))
    assert [(d["kind"], d["route"]) for d in drops_of(readings)] == [("gap", "artnet")]
    assert drops_of(soak.Readings(counts=counted(100.0))) == []


def test_during_an_outage_only_gaps_beyond_the_keepalive_and_250_ms_are_drops() -> None:
    samples = [sample(9.0), sample(10.0), sample(11.0, pid=11), sample(12.0, pid=11)]
    readings = soak.Readings(
        samples=samples,
        chaos=[killed(10.2)],
        receiver=[
            gap("sacn", 10.1, 10.1 + 0.9 + 0.2),  # within the sACN keep-alive and 250 ms
            gap("artnet", 10.1, 10.1 + 1.0 + 0.3),  # the Art-Net keep-alive and 300 ms: too long
            gap("dmxusb", 30.0, 30.2),  # long after the outage
        ],
        counts=counted(100.0),
    )
    found = drops_of(readings)
    assert [(d["kind"], d["route"]) for d in found] == [("outageGap", "artnet"), ("gap", "dmxusb")]
    (outage,) = soak.outages(readings)
    assert outage.recovered == T + 11.0
    assert outage.window() == (T + 10.2, T + 11.0 + soak.WINDOW_SLACK_S)


def test_an_unplugged_dmx_usb_route_is_not_measured_but_the_others_are() -> None:
    readings = soak.Readings(
        chaos=[{"t": T + 20.0, "action": "unplug", "pid": None}],
        receiver=[
            {"event": "unplug", "t": T + 20.0},
            {"event": "replug", "t": T + 23.0},
            {"event": "first", "route": "dmxusb", "t": T + 23.05},
            gap("dmxusb", 19.99, 20.5),
            gap("sacn", 21.0, 21.1),
        ],
        counts=counted(100.0),
    )
    assert [d["route"] for d in drops_of(readings)] == ["sacn"]
    (unplug,) = soak.recoveries(readings, [])
    assert unplug["recovered"] is True
    assert unplug["seconds"] == pytest.approx(3.05)


def test_sequence_and_parse_errors_are_drops_inside_the_measured_time_only() -> None:
    readings = soak.Readings(
        receiver=[
            {"event": "sequence", "route": "sacn", "t": T + 1.0, "expected": 5, "got": 0},
            {"event": "sequence", "route": "sacn", "t": T + 50.0, "expected": 5, "got": 7},
            {"event": "bad", "route": "artnet", "t": T + 60.0, "error": "OpCode"},
        ],
        counts=counted(100.0),
    )
    found = drops_of(readings)
    assert [(d["kind"], d.get("got")) for d in found] == [("sequence", 7), ("bad", None)]


def test_a_route_that_falls_silent_is_a_drop() -> None:
    readings = soak.Readings(counts=counted(60.0, last=40.0))
    assert {(d["kind"], d["route"], d["t"]) for d in drops_of(readings)} == {
        ("silent", route, T + 40.0) for route in soak.ROUTES
    }
    assert drops_of(soak.Readings(counts=counted(60.0, last=59.5))) == []


# -------------------------------------------------------------- recoveries


def test_a_stopped_engine_recovers_when_a_new_one_runs_or_it_ticks_again() -> None:
    stopped = {"t": T + 10.0, "action": "engineStop", "pid": 10}
    restarted = soak.Readings(
        samples=[sample(9.5), sample(11.0), sample(13.4, pid=11, ticks=5)], chaos=[stopped]
    )
    assert [o.recovered for o in soak.outages(restarted)] == [T + 13.4]
    resumed = soak.Readings(
        samples=[sample(9.5), sample(12.0), sample(14.5, ticks=150)], chaos=[stopped]
    )
    assert [o.recovered for o in soak.outages(resumed)] == [T + 14.5]
    never = soak.Readings(samples=[sample(9.5), sample(30.0)], chaos=[stopped])
    (outage,) = soak.outages(never)
    assert outage.recovered is None
    assert soak.recoveries(never, [outage])[0]["recovered"] is False


def test_a_killed_console_recovers_when_another_console_runs() -> None:
    action = {"t": T + 5.0, "action": "consoleKill", "pid": 20}
    readings = soak.Readings(
        samples=[sample(5.5), sample(6.5, consolePid=None), sample(7.5, consolePid=21)],
        chaos=[action],
    )
    (result,) = soak.recoveries(readings, [])
    assert result["recovered"] is True
    assert result["seconds"] == pytest.approx(2.5)


# ------------------------------------------------- overruns, errors, memory


def test_overruns_count_outside_outages_and_errors_sum_over_engines() -> None:
    restarted = {"pid": 11, "tickErrors": 1}  # the counters are the new engine's, cumulative
    samples = [
        sample(20.0, ticks=1000, overruns=0),
        sample(21.0, ticks=1100, overruns=1),  # a quiet second: counted
        sample(22.0, ticks=1200, overruns=1),
        sample(23.5, ticks=50, overruns=3, **restarted),  # the new engine's first line
        sample(24.5, ticks=150, overruns=4, installErrors=2, **restarted),  # settling
        sample(34.0, ticks=1100, overruns=4, installErrors=2, **restarted),  # settling until 33.5
        sample(40.0, ticks=1700, overruns=5, installErrors=2, **restarted),  # quiet again
    ]
    readings = soak.Readings(samples=samples, chaos=[killed(22.5)])
    windows = [outage.window() for outage in soak.outages(readings)]
    counts = soak.engine_counts(samples, windows, T)
    assert counts["ticks"] == 200 + 100 + 950 + 600
    assert counts["overruns"] == 1 + 1 + 1
    assert counts["ticksOutsideOutages"] == 200 + 600
    assert counts["overrunsOutsideOutages"] == 1 + 1
    assert (counts["tickErrors"], counts["installErrors"]) == (1, 2)
    assert counts["processes"] == 2


def test_memory_is_compared_with_the_value_after_half_a_short_run() -> None:
    samples = [sample(float(t), engineRss=(50 + t) << 20) for t in range(0, 101, 10)]
    rss = soak.memory(samples, T, T + 100.0)
    assert rss["engine"]["baselineMB"] == 100  # at 50 s
    assert rss["engine"]["endMB"] == 150
    assert rss["engine"]["limitMB"] == pytest.approx(130)
    assert rss["engine"]["ok"] is False
    assert rss["engine"]["slopeMBPerHour"] == pytest.approx(3600)
    assert rss["root"]["ok"] is True


# ---------------------------------------------------------------- receiver


def test_the_receiver_follows_each_protocols_sequence_wrap() -> None:
    written: list[dict[str, Any]] = []

    class Events:
        def write(self, event: str, **fields: Any) -> None:
            written.append({"event": event, **fields})

    sacn = soak_receiver.Track("sacn", Events(), "sacn")  # type: ignore[arg-type]
    artnet = soak_receiver.Track("artnet", Events(), "artnet")  # type: ignore[arg-type]
    for at, number in enumerate([254, 255, 0, 1]):
        sacn.packet(at * 0.02, bytes([number]), number)
    for at, number in enumerate([254, 255, 1, 3]):
        artnet.packet(at * 0.02, b"\x00", number)
    sacn.packet(1.0, bytes([1]), 2)  # 0.94 s after the last: a gap, with unchanged data
    assert written == [
        {"event": "sequence", "route": "artnet", "t": 3 * 0.02, "expected": 2, "got": 3},
        {"event": "gap", "route": "sacn", "t0": 3 * 0.02, "t1": 1.0, "changed": False},
    ]
    assert (sacn.packets, sacn.changes, artnet.changes) == (5, 4, 1)


def test_the_enttec_stream_splits_messages_across_reads_and_skips_stray_bytes() -> None:
    message = bytes([0x7E, 6, 3, 0, 0, 1, 2, 0xE7])
    stream = soak_receiver.EnttecStream()
    assert stream.feed(b"\x01\x02" + message[:5]) == ([], 2)
    assert stream.feed(message[5:] + message) == ([(6, b"\x00\x01\x02"), (6, b"\x00\x01\x02")], 0)


# -------------------------------------------------------------------- load


def test_the_load_leaves_the_circle_running() -> None:
    circle = {19, 22, 58, 60}  # knob 4, the FX master, track ◀ (on/off), marker SET (release all)
    touched = {*soak_load.FADER_CCS, *soak_load.BUTTON_CCS, *soak_load.PAGE_CCS}
    assert not circle & (touched | {soak_load.SPEED_CC, soak_load.BLACKOUT_CC})
    assert soak_load.SPEED_LOWEST >= 32  # "Speed 1" never stops the effects
    lines = [
        *soak_load.PROGRAMMER,
        *(line for edit in soak_load.EDITS for line in edit),
        *soak_load.MASTERS,
    ]
    assert not [line for line in lines if "release" in line or "11" in line or "FX" in line]
    rng = soak_load.random.Random(1)
    assert {soak_load.fader_command(rng)["slot"] for _ in range(500)} == set(range(8))


def test_every_chaos_mode_starts_inside_its_period() -> None:
    for actions in soak.CHAOS.values():
        assert all(0 < first < period for first, period in actions.values())
    fast = soak.CHAOS["fast"]
    assert fast["engineKill"][0] < fast["consoleKill"][0] < 60 < fast["engineStop"][0]


# -------------------------------------------------------------------- soak


@pytest.mark.soak
def test_a_one_minute_fast_soak_passes(tmp_path: Path) -> None:
    report_path = tmp_path / "soak.json"
    command = [sys.executable, str(ROOT / "bench" / "soak.py"), "--hours", str(1 / 60)]
    command += ["--chaos", "fast", "--seed", "7", "--report", str(report_path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    report = json.loads(report_path.read_text())
    failed = [c for c in report["criteria"] if not c["ok"]]
    assert result.returncode == 0, (failed, result.stdout, result.stderr)
    assert report["result"] == "pass"
    actions = [(a["action"], a["recovered"]) for a in report["actions"]]
    assert actions == [("engineKill", True), ("unplug", True), ("consoleKill", True)]
    assert report["restarts"] == {
        "engine": {"chaos": 1, "restarts": 1},
        "console": {"chaos": 1, "restarts": 1},
    }
    assert all(report["routes"][route]["packets"] > 2000 for route in soak.ROUTES)
