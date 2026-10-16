"""The web remote's API, its phone page and the web surface (phase-6-plan step 13).

Most tests drive :class:`~busk.web.api.WebApi` with a fake client: the API
only sends, publishes and reads the client's address. The engine is a
:class:`~harness.Harness` on Appendix A with a second page, wider buttons and
a web surface. The end-to-end tests listen on 127.0.0.1 and use
:mod:`ws_client`.
"""

from __future__ import annotations

import dataclasses
import importlib.resources
import itertools
import json
import queue
import re
import threading
import time
from typing import Any, cast

import pytest

from builders import APPENDIX_A, Doc, compile_doc, load_doc
from busk.commands.bus import CommandRejected
from busk.commands.types import Command, CommandOrigin
from busk.compiler.compile import CompiledShow
from busk.io.ratelimit import WEB_BURST
from busk.io.surfaces import SurfaceManager
from busk.model.surface import ControlSurface
from busk.process import report
from busk.session.session import CommandResult
from busk.web import api as web_api
from busk.web.api import PROTOCOL_VERSION, STATE_HZ, WebApi, WebLink, WebSurface
from busk.web.server import index_page
from busk.web.websocket import WebSocket
from harness import Harness
from ws_client import WsClient, request

KEY = "Qx7f2LmA"
REMOTE = "10.0.0.7:51234"
WAIT = 5.0


def doc() -> Doc:
    """Appendix A with page 2 "Washes", a goto button on pb-song (to cue 2
    "Chorus"), flash and swop on pb-blue, and a web surface."""
    show = load_doc(APPENDIX_A)
    show["pages"].append(
        {"id": "page-2", "number": 2, "name": "Washes", "slots": ["pb-blue", "pb-song"]}
    )
    show["playbacks"][0]["buttons"] = ["go", "back", "goto", "select"]
    show["playbacks"][0]["gotoCue"] = "2"
    show["playbacks"][1]["buttons"] = ["toggle", "flash", "swop"]
    show["surfaces"].append(
        {"id": "s-web", "name": "Phone", "kind": "web", "match": {"port": 8080},
         "faderPickup": "jump"}
    )  # fmt: skip
    return show


class Link:
    """A :class:`WebLink` on a harness. ``submit`` goes to the engine's bus,
    as :meth:`Session.submit`'s performance branch does, and is recorded."""

    def __init__(self, compiled: CompiledShow | None = None) -> None:
        self.compiled = compiled or compile_doc(doc())
        self.harness = Harness(self.compiled)
        self.harness.tick(0.0)
        self.submitted: queue.Queue[tuple[Command, CommandOrigin]] = queue.Queue()

    def link(self) -> WebLink:
        return WebLink(
            snapshot=lambda: self.harness.engine.snapshot,
            compiled=lambda: self.compiled,
            submit=self.submit,
            clock=lambda: 12.5,
            key=KEY,
        )

    def submit(self, command: Command, origin: CommandOrigin) -> CommandResult:
        self.submitted.put((command, origin))
        try:
            self.harness.engine.bus.submit(command, origin)
        except CommandRejected as exc:
            return CommandResult(ok=False, message=exc.reason)
        return CommandResult(ok=True, message="")

    def drain(self) -> list[tuple[Command, CommandOrigin]]:
        out = []
        while not self.submitted.empty():
            out.append(self.submitted.get())
        return out


class FakeClient:
    """What the API uses of a :class:`WebSocket`."""

    remote = REMOTE

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.slots: dict[str, dict[str, Any]] = {}
        self.published = 0

    def send(self, text: str) -> None:
        self.sent.append(json.loads(text))

    def publish(self, slot: str, text: str) -> None:
        self.slots[slot] = json.loads(text)
        self.published += 1


@pytest.fixture
def link() -> Link:
    return Link()


def connect(api: WebApi) -> FakeClient:
    client = FakeClient()
    api.connected(cast(WebSocket, client))
    return client


def say(api: WebApi, client: FakeClient, message: object) -> list[dict[str, Any]]:
    """Send ``message`` (JSON unless already a string); return the replies."""
    client.sent.clear()
    text = message if isinstance(message, str) else json.dumps(message)
    api.received(cast(WebSocket, client), text)
    return client.sent


ORIGIN = {"surfaceId": "s-web", "remote": REMOTE}


# --------------------------------------------------------------------- messages


def test_hello_show_and_state_on_connect(link: Link) -> None:
    client = connect(WebApi("s-web", link.link()))
    assert client.sent == [
        {"type": "hello", "version": PROTOCOL_VERSION, "surface": "s-web", "time": 12.5}
    ]
    show = client.slots["show"]
    assert show["type"] == "show"
    assert show["pages"] == [
        {"id": "page-1", "number": 1, "name": "Main",
         "slots": ["pb-song", None, "pb-blue", None, None, "pb-pulse", None, None]},
        {"id": "page-2", "number": 2, "name": "Washes", "slots": ["pb-blue", "pb-song"]},
    ]  # fmt: skip
    source = doc()["playbacks"]
    assert show["playbacks"] == [
        {"id": "pb-song", "number": source[0]["number"], "name": source[0]["name"],
         "fader": "master", "buttons": ["go", "back", "goto", "select"],
         "gotoCue": {"number": "2", "name": "Chorus"}, "cueCount": 2},
        {"id": "pb-blue", "number": source[1]["number"], "name": source[1]["name"],
         "fader": "master", "buttons": ["toggle", "flash", "swop"], "gotoCue": None,
         "cueCount": 1},
        {"id": "pb-pulse", "number": source[2]["number"], "name": source[2]["name"],
         "fader": "size", "buttons": ["toggle"], "gotoCue": None, "cueCount": 1},
    ]  # fmt: skip
    masters = {m["id"]: m for m in show["masters"]}
    assert list(masters) == ["m-gm", "m-speed"]
    assert masters["m-gm"] | {"name": None} == {
        "id": "m-gm", "name": None, "kind": "grand", "steps": [], "tap": False
    }  # fmt: skip
    assert masters["m-speed"]["kind"] == "speed"
    assert masters["m-speed"]["tap"] is True
    assert masters["m-speed"]["steps"] == list(link.compiled.masters["m-speed"].multiplierSteps)

    state = client.slots["state"]
    snapshot = link.harness.engine.snapshot
    assert snapshot is not None
    assert state["type"] == "state"
    assert state["seq"] == snapshot.seq
    assert state["time"] == 0.0
    assert state["blackout"] is False
    assert state["grandMaster"] == 1.0
    assert state["page"] == {"id": "page-1", "number": 1, "name": "Main"}
    assert [p["id"] for p in state["playbacks"]] == ["pb-song", "pb-blue", "pb-pulse"]
    assert state["playbacks"][0]["state"] == "idle"
    assert state["masterLevels"][0] == ["m-gm", 1.0]
    (speed,) = state["speed"]
    assert speed["id"] == "m-speed"
    assert {"bpm", "multiplier", "level", "beatTime", "beat"} <= speed.keys()
    assert state["fadeTime"] is None


def test_no_state_before_the_engine_published_one(link: Link) -> None:
    api = WebApi("s-web", dataclasses.replace(link.link(), snapshot=lambda: None))
    client = connect(api)
    assert set(client.slots) == {"show"}


def test_states_follow_snapshots_and_shows_follow_live_edits(link: Link) -> None:
    api = WebApi("s-web", link.link())
    client = connect(api)
    client.slots.clear()
    api.broadcast()
    assert client.slots == {}  # nothing changed

    link.harness.submit(cast(Command, {"type": "BLACKOUT"}))
    link.harness.tick(0.02)
    api.broadcast()
    assert set(client.slots) == {"state"}
    assert client.slots["state"]["blackout"] is True

    edited = doc()
    edited["pages"][1]["name"] = "Wash looks"
    link.compiled = compile_doc(edited)
    client.slots.clear()
    api.broadcast()
    assert set(client.slots) == {"show"}
    assert client.slots["show"]["pages"][1]["name"] == "Wash looks"


def test_every_client_gets_each_change(link: Link) -> None:
    api = WebApi("s-web", link.link())
    first, second = connect(api), connect(api)
    link.harness.submit(cast(Command, {"type": "PAGE", "number": 2}))
    link.harness.tick(0.02)
    api.broadcast()
    for client in (first, second):
        assert client.slots["state"]["page"]["name"] == "Washes"
    api.disconnected(cast(WebSocket, first))
    link.harness.submit(cast(Command, {"type": "PAGE", "number": 1}))
    link.harness.tick(0.04)
    api.broadcast()
    assert first.slots["state"]["page"]["name"] == "Washes"
    assert second.slots["state"]["page"]["name"] == "Main"


def test_states_are_capped_under_a_burst_of_changes(link: Link) -> None:
    base = link.harness.engine.snapshot
    assert base is not None
    counter = itertools.count(1)
    burst = dataclasses.replace(
        link.link(), snapshot=lambda: dataclasses.replace(base, seq=next(counter))
    )
    api = WebApi("s-web", burst)
    client = connect(api)
    client.published = 0
    stop = threading.Event()
    thread = threading.Thread(target=api.run, args=(stop,))
    started = time.monotonic()
    thread.start()
    time.sleep(0.5)
    stop.set()
    thread.join()
    elapsed = time.monotonic() - started
    assert 5 <= client.published <= elapsed * STATE_HZ + 1
    assert api.errors == 0


# --------------------------------------------------------------------- commands


def test_performance_commands_are_submitted_with_the_origin(link: Link) -> None:
    api = WebApi("s-web", link.link())
    client = connect(api)
    go = {"type": "GO", "playbackId": "pb-song"}
    assert say(api, client, {"id": "7", "command": go}) == []
    assert link.drain() == [(go, ORIGIN)]
    link.harness.tick(0.02)
    snapshot = link.harness.engine.snapshot
    assert snapshot is not None
    assert snapshot.playbacks[0].state == "active"


@pytest.mark.parametrize(
    ("command", "message"),
    [
        ({"type": "SELECT", "groupId": "g-1"},
         "SELECT is a programmer command; the web remote sends performance commands only"),
        ({"type": "RECORD_CUE", "cueListId": "cl-song"},
         "RECORD_CUE is a show command; the web remote sends performance commands only"),
        ({"type": "SELF_DESTRUCT"}, "unknown command type 'SELF_DESTRUCT'"),
        ({"playbackId": "pb-song"}, "unknown command type None"),
    ],
)  # fmt: skip
def test_programmer_and_show_commands_are_refused(
    link: Link, command: dict[str, object], message: str
) -> None:
    api = WebApi("s-web", link.link())
    client = connect(api)
    assert say(api, client, {"id": 8, "command": command}) == [
        {"type": "error", "id": 8, "message": message}
    ]
    assert link.drain() == []


def test_a_command_the_bus_rejects_is_answered(link: Link) -> None:
    api = WebApi("s-web", link.link())
    client = connect(api)
    (reply,) = say(api, client, {"id": "9", "command": {"type": "GO", "playbackId": "pb-nope"}})
    assert reply["type"] == "error"
    assert reply["id"] == "9"
    assert "pb-nope" in reply["message"]


@pytest.mark.parametrize(
    ("text", "ident", "start"),
    [
        ("not json{", None, "not JSON: "),
        ("[1, 2]", None, 'expected an object {"id": …, "command": {…}}'),
        ('{"id": 3}', 3, "expected a command object"),
        ('{"id": "4", "command": [1]}', "4", "expected a command object"),
        ('{"id": {"x": 1}, "command": 5}', None, "expected a command object"),
        ('{"id": true, "command": 5}', None, "expected a command object"),
    ],
)
def test_bad_messages_are_answered(link: Link, text: str, ident: object, start: str) -> None:
    api = WebApi("s-web", link.link())
    client = connect(api)
    (reply,) = say(api, client, text)
    assert reply["type"] == "error"
    assert reply["id"] == ident
    assert reply["message"].startswith(start)
    assert link.drain() == []


def button(down: bool, index: int, **target: object) -> dict[str, object]:
    return {"type": "PLAYBACK_BUTTON", "button": index, "down": down, **target}


def test_held_buttons_are_released_on_disconnect(link: Link) -> None:
    api = WebApi("s-web", link.link())
    client = connect(api)
    for command in [
        button(True, 1, playbackId="pb-blue"),  # flash, held
        button(True, 2, playbackId="pb-blue"),  # swop, pressed …
        button(False, 2, playbackId="pb-blue"),  # … and released
        button(True, 0, slot=0),  # go on page 1's first slot, held
        button(True, 7, playbackId="pb-blue"),  # no such button: accepted, does nothing
    ]:
        assert say(api, client, {"id": "x", "command": command}) == []
    link.harness.tick(0.02)
    snapshot = link.harness.engine.snapshot
    assert snapshot is not None
    assert snapshot.playbacks[1].flash
    link.drain()

    api.disconnected(cast(WebSocket, client))
    released = link.drain()
    assert sorted(released, key=repr) == sorted(
        [
            (button(False, 1, playbackId="pb-blue"), ORIGIN),
            (button(False, 0, slot=0), ORIGIN),
            (button(False, 7, playbackId="pb-blue"), ORIGIN),
        ],
        key=repr,
    )
    link.harness.tick(0.04)
    snapshot = link.harness.engine.snapshot
    assert snapshot is not None
    assert not snapshot.playbacks[1].flash
    api.disconnected(cast(WebSocket, client))  # a second time: nothing more
    assert link.drain() == []


def test_a_rejected_press_is_not_held(link: Link) -> None:
    api = WebApi("s-web", link.link())
    client = connect(api)
    (reply,) = say(api, client, {"command": button(True, 0, playbackId="pb-nope")})
    assert reply["type"] == "error"
    link.drain()
    api.disconnected(cast(WebSocket, client))
    assert link.drain() == []


# --------------------------------------------------------------------- the page


def page_text() -> str:
    return index_page().decode("utf-8")


def listed_commands() -> list[str]:
    path = importlib.resources.files("busk.web").joinpath("static/commands.json")
    return cast(list[str], json.loads(path.read_text(encoding="utf-8")))


def test_the_page_sends_exactly_the_listed_command_types() -> None:
    sent = set(re.findall(r'type:\s*"([A-Z_]+)"', page_text()))
    assert sent == set(listed_commands())


EXAMPLES: dict[str, dict[str, object]] = {
    "PAGE": {"type": "PAGE", "delta": 1},
    "BLACKOUT": {"type": "BLACKOUT"},
    "SET_MASTER": {"type": "SET_MASTER", "masterId": "m-gm", "level": 0.5},
    "TAP": {"type": "TAP", "masterId": "m-speed"},
    "SET_FADER": {"type": "SET_FADER", "playbackId": "pb-blue", "level": 0.25},
    "PLAYBACK_BUTTON": button(True, 1, playbackId="pb-blue"),
}


def test_every_listed_command_is_accepted_by_the_bus(link: Link) -> None:
    assert set(EXAMPLES) == set(listed_commands())
    api = WebApi("s-web", link.link())
    client = connect(api)
    for command in EXAMPLES.values():
        assert say(api, client, {"id": "1", "command": command}) == [], command


def test_the_page_needs_nothing_from_outside() -> None:
    text = page_text()
    assert "http://" not in text
    assert "https://" not in text
    assert not re.search(r"<(script|link|img|iframe)[^>]*(src|href)=", text)
    assert "@import" not in text
    assert 'new WebSocket("ws://" + location.host + "/ws" + location.search)' in text


# --------------------------------------------------------------------- the surface


def web_surface(host: str = "127.0.0.1", name: str = "Phone") -> ControlSurface:
    return cast(
        ControlSurface,
        {"id": "s-web", "name": name, "kind": "web", "match": {"port": 0, "host": host},
         "faderPickup": "jump"},
    )  # fmt: skip


@pytest.fixture
def surface(link: Link) -> WebSurface:
    web = WebSurface(web_surface(), link.link(), stall=0.3, linger=0.3)
    assert web.open() is None
    yield web
    web.close()


def test_the_page_is_served_with_the_key_only(surface: WebSurface) -> None:
    assert surface.server.port is not None
    connection, response = request(surface.server.port, f"/?k={KEY}")
    connection.close()
    assert response.status == 200
    assert response.body == index_page()
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    connection, response = request(surface.server.port, "/")
    connection.close()
    assert response.status == 403


def test_a_phone_round_trip(surface: WebSurface, link: Link) -> None:
    assert surface.server.port is not None
    client = WsClient(surface.server.port, KEY)
    messages = [json.loads(client.recv_text()) for _ in range(3)]
    assert [m["type"] for m in messages] == ["hello", "show", "state"]
    press = button(True, 1, playbackId="pb-blue")
    client.send_text(json.dumps({"id": "1", "command": press}))
    command, origin = link.submitted.get(timeout=WAIT)
    assert command == press
    assert origin["surfaceId"] == "s-web"
    assert origin["remote"].startswith("127.0.0.1:")
    link.harness.tick(0.02)
    state = json.loads(client.recv_text())  # the broadcaster's next state
    assert state["playbacks"][1]["flash"] is True
    client.close()  # the phone vanishes without a close frame
    command, _ = link.submitted.get(timeout=WAIT)
    assert command == button(False, 1, playbackId="pb-blue")


def test_a_flooding_phone_hears_about_the_rate_limit(surface: WebSurface, link: Link) -> None:
    """Phase 7 (decision 19). The link's clock stands still, so the client's
    bucket never refills: the burst gets through, the next command is dropped
    and reported with ``id`` null."""
    assert surface.server.port is not None
    client = WsClient(surface.server.port, KEY)
    fader = {"type": "SET_MASTER", "masterId": "m-gm", "level": 0.5}
    for k in range(int(WEB_BURST) + 1):
        client.send_text(json.dumps({"id": k, "command": fader}))
    while (reply := json.loads(client.recv_text()))["type"] != "error":
        pass  # hello, show and states
    assert reply == {"type": "error", "id": None, "message": "rate limit: 1 command dropped"}
    assert link.submitted.qsize() == WEB_BURST
    client.close()


def test_closing_the_surface_closes_its_clients(link: Link) -> None:
    web = WebSurface(web_surface(), link.link(), stall=0.3, linger=0.3)
    assert web.open() is None
    assert web.server.port is not None
    client = WsClient(web.server.port, KEY)
    web.close()
    assert client.recv_close() == 1001
    web.close()  # idempotent
    client.close()


def test_urls(link: Link, monkeypatch: pytest.MonkeyPatch) -> None:
    web = WebSurface(web_surface(host="127.0.0.1"), link.link())
    web.server.port = 8080
    assert web.urls() == [f"http://127.0.0.1:8080/?k={KEY}"]

    web = WebSurface(web_surface(host=""), link.link())
    web.server.port = 8080
    interfaces = [("lo", "127.0.0.1"), ("eth0", "10.0.0.5"), ("wlan0", "192.168.1.20")]
    monkeypatch.setattr(web_api, "ipv4_addresses", lambda: interfaces)
    assert web.urls() == [f"http://10.0.0.5:8080/?k={KEY}", f"http://192.168.1.20:8080/?k={KEY}"]
    monkeypatch.setattr(web_api, "ipv4_addresses", lambda: [("lo", "127.0.0.1")])
    assert web.urls() == [f"http://127.0.0.1:8080/?k={KEY}"]

    def unavailable() -> list[tuple[str, str]]:
        raise OSError("not Linux")

    monkeypatch.setattr(web_api, "ipv4_addresses", unavailable)
    monkeypatch.setattr(web_api.socket, "gethostname", lambda: "console")
    assert web.urls() == [f"http://console:8080/?k={KEY}"]


# --------------------------------------------------------------------- the manager


def shown(*surfaces: ControlSurface) -> CompiledShow:
    return cast(CompiledShow, dataclasses.replace(compile_doc(doc()), surfaces=surfaces))


def test_the_manager_opens_web_surfaces(link: Link, capsys: pytest.CaptureFixture[str]) -> None:
    manager = SurfaceManager(lambda event: None, link.link(), say=report.say, warn=report.warn)
    manager.reconcile(shown(web_surface()))
    out = capsys.readouterr().out
    match = re.fullmatch(rf"Web s-web: http://127\.0\.0\.1:(\d+)/\?k={KEY}\n", out)
    assert match is not None
    client = WsClient(int(match.group(1)), KEY)
    assert json.loads(client.recv_text())["type"] == "hello"

    manager.reconcile(shown(web_surface(name="Renamed phone")))
    assert capsys.readouterr().out == ""  # still the same server
    client.send_text(json.dumps({"command": {"type": "SELF_DESTRUCT"}}))
    while json.loads(client.recv_text())["type"] != "error":
        pass

    manager.reconcile(shown(web_surface(host="127.0.0.2")))  # a new address: restarted
    assert client.recv_close() == 1001
    assert re.fullmatch(r"Web s-web: http://127\.0\.0\.2:\d+/\?k=\w+\n", capsys.readouterr().out)
    client.close()
    manager.close()


def test_a_taken_port_is_reported(link: Link, capsys: pytest.CaptureFixture[str]) -> None:
    first = WebSurface(web_surface(), link.link())
    assert first.open() is None
    taken = web_surface()
    taken["match"]["port"] = first.server.port  # type: ignore[typeddict-item]
    manager = SurfaceManager(lambda event: None, link.link(), say=report.say, warn=report.warn)
    manager.reconcile(shown(taken))
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(f"Web s-web: cannot listen on 127.0.0.1:{first.server.port}")
    manager.close()
    first.close()
