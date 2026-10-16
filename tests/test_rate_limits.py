"""Rate limits and the bounded drain (phase-7-plan decision 19, §5.17, step 12).

A token bucket per web client (120 commands a second, bursts of 240) and per
OSC surface (200 messages a second, bursts of 400); the excess is dropped,
counted and reported at most once a second. Button releases always pass.
Whatever gets through is applied at most 512 queued items per engine tick.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any, cast

import pytest

from builders import APPENDIX_A, compile_doc, load_doc
from busk.commands.bus import MAX_DRAIN
from busk.engine.clock import FakeClock
from busk.engine.loop import Engine
from busk.io.events import InputEvent
from busk.io.osc import OscSurface, encode
from busk.io.ratelimit import (
    OSC_BURST,
    OSC_RATE,
    REPORT_S,
    WEB_BURST,
    WEB_RATE,
    TokenBucket,
)
from busk.model.common import SurfaceId
from busk.model.surface import ControlSurface
from busk.web.api import WebApi
from test_web_api import FakeClient, Link


def test_the_limits_are_the_plans() -> None:
    assert (WEB_RATE, WEB_BURST, OSC_RATE, OSC_BURST, REPORT_S) == (120, 240, 200, 400, 1.0)


class Clock:
    """A clock the test sets."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# ------------------------------------------------------------------ the bucket


def test_a_bucket_starts_full_and_drops_once_empty() -> None:
    clock = Clock()
    bucket = TokenBucket(10.0, 3.0, clock)
    assert [bucket.take() for _ in range(5)] == [True, True, True, False, False]
    assert bucket.dropped == 2


def test_a_bucket_refills_at_its_rate_and_never_beyond_its_burst() -> None:
    clock = Clock()
    bucket = TokenBucket(10.0, 3.0, clock)
    for _ in range(3):
        bucket.take()
    clock.now = 0.25  # 2.5 tokens
    assert [bucket.take() for _ in range(3)] == [True, True, False]
    clock.now = 0.35  # 0.5 left + 1 = 1.5
    assert [bucket.take() for _ in range(2)] == [True, False]
    clock.now = 100.0  # a long quiet spell fills it to the burst only
    assert [bucket.take() for _ in range(4)] == [True, True, True, False]


def test_drops_are_reported_at_once_then_at_most_every_report_s() -> None:
    clock = Clock()
    bucket = TokenBucket(1.0, 1.0, clock)
    assert bucket.report() == 0  # nothing dropped
    assert [bucket.take(), bucket.take()] == [True, False]
    assert bucket.report() == 1  # the first drop is reported at once
    for _ in range(4):
        bucket.take()
    clock.now = 0.5
    assert bucket.report() == 0  # too soon: the drops wait
    assert bucket.dropped == 4
    clock.now = REPORT_S
    assert bucket.report() == 4
    assert (bucket.report(), bucket.dropped) == (0, 0)


# ------------------------------------------------------------------- web


def release(k: int) -> dict[str, Any]:
    return {"id": k, "command": {"type": "FLASH", "playbackId": "pb-blue", "down": False}}


def fader(k: int) -> dict[str, Any]:
    return {"id": k, "command": {"type": "SET_MASTER", "masterId": "m-gm", "level": 0.5}}


def errors(client: FakeClient) -> list[dict[str, Any]]:
    found = [m for m in client.sent if m["type"] == "error"]
    client.sent.clear()
    return found


def test_a_web_client_at_1000_commands_a_second_gets_120_a_second_through() -> None:
    link = Link()
    clock = Clock()
    api = WebApi(SurfaceId("s-web"), dataclasses.replace(link.link(), clock=clock))
    client = FakeClient()
    api.connected(cast(Any, client))
    client.sent.clear()
    through: list[int] = []  # per second: the faders that got through
    reported: list[list[dict[str, Any]]] = []
    released = 0
    for second in range(3):
        for k in range(1000 * second, 1000 * (second + 1)):
            clock.now = k / 1000
            message = release(k) if k % 10 == 9 else fader(k)
            api.received(cast(Any, client), json.dumps(message))
        submitted = [command for command, _ in link.drain()]
        released += sum(command["type"] == "FLASH" for command in submitted)
        through.append(sum(command["type"] == "SET_MASTER" for command in submitted))
        reported.append(errors(client))
    assert released == 300  # every release, whatever the limit
    assert abs(through[0] - (WEB_BURST + WEB_RATE)) <= 1
    assert [abs(n - WEB_RATE) <= 1 for n in through[1:]] == [True, True]
    assert [len(each) for each in reported] == [1, 1, 1]  # one error a second
    messages = [each[0] for each in reported]
    assert messages[0] == {"type": "error", "id": None, "message": "rate limit: 1 command dropped"}
    for message in messages[1:]:
        assert message["id"] is None
        dropped = int(message["message"].split()[2])
        assert message["message"] == f"rate limit: {dropped} commands dropped"
        assert 750 <= dropped <= 800  # a second of drops: 900 faders − 120 through


def test_each_web_client_has_its_own_bucket() -> None:
    link = Link()
    clock = Clock()
    api = WebApi(SurfaceId("s-web"), dataclasses.replace(link.link(), clock=clock))
    greedy, polite = FakeClient(), FakeClient()
    api.connected(cast(Any, greedy))
    api.connected(cast(Any, polite))
    for k in range(int(WEB_BURST) + 50):
        api.received(cast(Any, greedy), json.dumps(fader(k)))
    api.received(cast(Any, polite), json.dumps(fader(0)))
    assert len(link.drain()) == WEB_BURST + 1
    assert errors(polite) == []
    api.disconnected(cast(Any, greedy))  # its bucket goes with it


def test_garbage_counts_against_the_limit_and_its_errors_stop() -> None:
    link = Link()
    clock = Clock()
    api = WebApi(SurfaceId("s-web"), dataclasses.replace(link.link(), clock=clock))
    client = FakeClient()
    api.connected(cast(Any, client))
    client.sent.clear()
    for _ in range(int(WEB_BURST) + 100):
        api.received(cast(Any, client), "{not json")
    sent = errors(client)
    assert len(sent) == WEB_BURST + 1  # one "not JSON" each, then one rate-limit report
    assert sent[-1]["message"] == "rate limit: 1 command dropped"


# ------------------------------------------------------------------- OSC


def osc_surface() -> ControlSurface:
    return cast(
        ControlSurface,
        {
            "id": "s-touch",
            "name": "TouchOSC",
            "kind": "osc",
            "match": {"port": 0},
            "faderPickup": "jump",
        },
    )


def test_osc_drops_are_counted_and_reported_once_a_second(
    capsys: pytest.CaptureFixture[str],
) -> None:
    clock = Clock()
    events: list[InputEvent] = []
    surface = OscSurface(osc_surface(), events.append, clock=clock)
    source = ("10.0.0.7", 9000)
    for k in range(2000):  # 2 s at 1000 messages a second
        clock.now = k / 1000
        surface.datagram(encode("/fader", 0.5), source)
    assert abs(len(events) - (OSC_BURST + 2 * OSC_RATE)) <= 1
    assert surface.dropped == 2000 - len(events)
    lines = capsys.readouterr().err.splitlines()
    assert lines[0] == "OSC s-touch: rate limit: 1 message dropped"  # the first drop, at 0.5 s
    assert len(lines) == 2  # and one more a second later
    dropped = int(lines[1].split()[4])
    assert lines[1] == f"OSC s-touch: rate limit: {dropped} messages dropped"
    assert dropped == surface.dropped - 1 - surface._bucket.dropped  # the rest wait


def test_an_osc_message_of_zeros_is_never_dropped(capsys: pytest.CaptureFixture[str]) -> None:
    clock = Clock()
    events: list[InputEvent] = []
    surface = OscSurface(osc_surface(), events.append, clock=clock)
    source = ("10.0.0.7", 9000)
    for _ in range(int(OSC_BURST) + 10):
        surface.datagram(encode("/fader", 0.5), source)
    events.clear()
    surface.datagram(encode("/button", 0.0), source)  # a release
    surface.datagram(encode("/go", 1.0), source)  # a press: dropped
    surface.datagram(b"/go\0,\0\0\0", source)  # a bare message is a press too: dropped
    assert [(e.address, e.value) for e in events] == [({"kind": "osc", "path": "/button"}, 0.0)]
    assert surface.dropped == 12


# ------------------------------------------------------------ bounded drain


def test_a_flood_of_5000_commands_queued_in_one_tick_is_applied_over_10_ticks_in_order() -> None:
    engine = Engine(compile_doc(load_doc(APPENDIX_A)), FakeClock())
    for k in range(1, 5001):
        engine.bus.submit({"type": "SET_MASTER", "masterId": "m-gm", "level": k / 5000})
    seen = []
    for tick in range(11):
        engine.tick(tick / 100)
        seen.append((engine.stats.commandsApplied, engine.runtime.masterLevels["m-gm"]))
    expected = [min(MAX_DRAIN * (t + 1), 5000) for t in range(11)]
    assert seen == [(n, n / 5000) for n in expected]  # the newest applied is the n-th sent
    assert expected.index(5000) == 9  # the tenth tick applies the last
