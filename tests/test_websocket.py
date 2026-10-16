"""The web remote's WebSocket server (phase-6-plan step 12).

The client side is :mod:`ws_client`, written independently from the RFC.
Servers listen on 127.0.0.1 at ephemeral ports, with short stall and linger
times so the closing paths stay fast.
"""

from __future__ import annotations

import io
import queue
import socket
import stat
import threading
import time
from email.message import Message
from pathlib import Path

import pytest

from busk.persistence.paths import web_key
from busk.web.server import WebServer, _Handler, index_page
from busk.web.websocket import (
    MAX_MESSAGE,
    MAX_REPLIES,
    CloseCode,
    FrameReader,
    HandshakeError,
    Opcode,
    ProtocolError,
    WebSocket,
    accept_key,
    check_origin,
    check_upgrade,
)
from ws_client import (
    BINARY,
    CLOSE,
    CONTINUATION,
    PING,
    PONG,
    TEXT,
    Connection,
    WsClient,
    frame,
    request,
    upgrade_headers,
)

KEY = "Qx7f2LmA"
PAGE = b"<!doctype html><title>remote</title>"
WAIT = 5.0


class Echo:
    """A WebApp that echoes text and records connections. ``raise`` makes
    :meth:`received` fail once."""

    def __init__(self) -> None:
        self.events: queue.Queue[tuple[str, WebSocket]] = queue.Queue()

    def connected(self, client: WebSocket) -> None:
        self.events.put(("connected", client))

    def received(self, client: WebSocket, text: str) -> None:
        if text == "raise":
            raise RuntimeError("app bug")
        client.send(text)

    def disconnected(self, client: WebSocket) -> None:
        self.events.put(("disconnected", client))

    def next(self, kind: str) -> WebSocket:
        event, client = self.events.get(timeout=WAIT)
        assert event == kind
        return client


@pytest.fixture
def app() -> Echo:
    return Echo()


@pytest.fixture
def web(app: Echo) -> WebServer:
    server = WebServer(app, KEY, host="127.0.0.1", page=PAGE, stall=0.3, linger=0.3)
    assert server.open() is None
    yield server
    server.close()


def connect(web: WebServer, **options: object) -> WsClient:
    assert web.port is not None
    return WsClient(web.port, KEY, **options)  # type: ignore[arg-type]


# --------------------------------------------------------------------- handshake


def test_accept_key_matches_the_rfc_example() -> None:
    # RFC 6455 §1.3.
    assert accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def headers(**fields: str) -> Message:
    message = Message()
    for name, value in (upgrade_headers("dGhlIHNhbXBsZSBub25jZQ==") | fields).items():
        if value:
            message[name.replace("_", "-")] = value
    return message


def test_a_valid_upgrade_returns_the_key() -> None:
    assert check_upgrade(headers()) == "dGhlIHNhbXBsZSBub25jZQ=="
    # Firefox sends "keep-alive, Upgrade"; tokens are case-insensitive.
    assert check_upgrade(headers(Connection="keep-alive, upgrade", Upgrade="WebSocket"))


@pytest.mark.parametrize(
    ("fields", "status"),
    [
        ({"Upgrade": ""}, 400),
        ({"Upgrade": "h2c"}, 400),
        ({"Connection": ""}, 400),
        ({"Connection": "keep-alive"}, 400),
        ({"Sec-WebSocket-Version": ""}, 426),
        ({"Sec-WebSocket-Version": "8"}, 426),
        ({"Sec-WebSocket-Key": ""}, 400),
        ({"Sec-WebSocket-Key": "not base64!"}, 400),
        ({"Sec-WebSocket-Key": "c2hvcnQ="}, 400),  # 5 bytes
    ],
)
def test_upgrade_errors(fields: dict[str, str], status: int) -> None:
    with pytest.raises(HandshakeError) as caught:
        check_upgrade(headers(**fields))
    assert caught.value.status == status


def test_origin_must_be_absent_or_the_page_itself() -> None:
    check_origin(None, "10.0.0.5:8080")
    check_origin("http://10.0.0.5:8080", "10.0.0.5:8080")
    check_origin("HTTP://Phone.local:8080", "phone.local:8080")
    for origin, host in [
        ("http://evil.example", "10.0.0.5:8080"),
        ("http://10.0.0.5:8081", "10.0.0.5:8080"),
        ("https://10.0.0.5:8080", "10.0.0.5:8080"),
        ("http://10.0.0.5:8080", None),
        ("null", "10.0.0.5:8080"),
    ]:
        with pytest.raises(HandshakeError) as caught:
            check_origin(origin, host)
        assert caught.value.status == 403


# --------------------------------------------------------------------- HTTP


def get(web: WebServer, path: str, fields: dict[str, str] | None = None) -> tuple[int, bytes]:
    assert web.port is not None
    connection, response = request(web.port, path, fields)
    connection.close()
    return response.status, response.body


def test_the_page_needs_the_key(web: WebServer) -> None:
    assert get(web, f"/?k={KEY}") == (200, PAGE)
    assert get(web, f"/index.html?k={KEY}") == (200, PAGE)
    status, body = get(web, "/")
    assert status == 403
    assert b"?k=" in body
    assert get(web, "/?k=Qx7f2LmB")[0] == 403
    assert get(web, f"/?k={KEY}x")[0] == 403


def test_no_other_path_is_served(web: WebServer) -> None:
    for path in ["/favicon.ico", "/static/index.html", "/../pyproject.toml", "/ws/"]:
        assert get(web, f"{path}?k={KEY}")[0] == 404


def test_only_get_is_implemented(web: WebServer) -> None:
    assert web.port is not None
    connection = Connection(web.port)
    connection.sock.sendall(b"POST /?k=" + KEY.encode() + b" HTTP/1.1\r\nHost: x\r\n\r\n")
    assert connection.response().status == 501
    connection.close()


def test_connections_send_without_nagle_delay() -> None:
    # With Nagle's algorithm a state frame waits for the ACK of the one before,
    # which a phone may delay by 40 ms or more (phase-6-plan step 19).
    assert _Handler.disable_nagle_algorithm is True


def test_upgrade_errors_over_http(web: WebServer) -> None:
    upgrade = upgrade_headers()
    assert get(web, f"/ws?k={KEY}", {"Host": "x"})[0] == 400
    assert get(web, f"/ws?k={KEY}", upgrade | {"Connection": "close"})[0] == 400
    assert web.port is not None
    connection, response = request(
        web.port, f"/ws?k={KEY}", upgrade | {"Sec-WebSocket-Version": "12"}
    )
    connection.close()
    assert response.status == 426
    assert response.headers["sec-websocket-version"] == "13"


def test_a_wrong_key_or_a_foreign_origin_is_refused(web: WebServer) -> None:
    assert get(web, "/ws?k=wrong", upgrade_headers())[0] == 403
    assert get(web, "/ws", upgrade_headers())[0] == 403
    foreign = upgrade_headers() | {"Origin": "http://evil.example"}
    assert get(web, f"/ws?k={KEY}", foreign)[0] == 403


def test_the_page_own_origin_is_accepted(web: WebServer) -> None:
    origin = {"Origin": f"http://127.0.0.1:{web.port}"}
    with connect(web, headers=origin) as client:
        client.send_text("hi")
        assert client.recv_text() == "hi"


# --------------------------------------------------------------------- frames


@pytest.mark.parametrize("size", [0, 125, 126, 65535, MAX_MESSAGE])
def test_masked_frames_of_every_length_encoding(web: WebServer, size: int) -> None:
    text = "x" * size
    with connect(web) as client:
        client.send_text(text)
        assert client.recv_text() == text


def test_fragmented_message_with_a_ping_between(web: WebServer) -> None:
    with connect(web) as client:
        client.send(TEXT, b"Hel", fin=False)
        client.send(PING, b"p")
        client.send(CONTINUATION, b"lo ", fin=False)
        client.send(CONTINUATION, b"world")
        assert client.recv() == (PONG, b"p")
        assert client.recv_text() == "Hello world"
        client.send_text("next")  # the fragment state was reset
        assert client.recv_text() == "next"


def test_a_character_split_between_fragments(web: WebServer) -> None:
    data = "café".encode()
    with connect(web) as client:
        client.send(TEXT, data[:-1], fin=False)
        client.send(CONTINUATION, data[-1:])
        assert client.recv_text() == "café"


def test_ping_is_answered_and_pong_ignored(web: WebServer) -> None:
    with connect(web) as client:
        client.send(PONG, b"unsolicited")
        client.send(PING, b"abc")
        assert client.recv() == (PONG, b"abc")
        client.send(PING)
        assert client.recv() == (PONG, b"")


def test_the_first_frame_in_the_headers_packet(web: WebServer) -> None:
    with connect(web, after=frame(TEXT, b"early") + frame(TEXT, b"second")) as client:
        assert client.recv_text() == "early"
        assert client.recv_text() == "second"


def test_a_client_close_is_answered(web: WebServer, app: Echo) -> None:
    with connect(web) as client:
        server_side = app.next("connected")
        client.send(CLOSE, (1000).to_bytes(2, "big") + b"bye")
        assert client.recv_close() == 1000
    assert app.next("disconnected") is server_side


def test_a_close_without_a_code_is_answered_without_one(web: WebServer) -> None:
    with connect(web) as client:
        client.send(CLOSE)
        assert client.recv_close() is None


TOO_BIG = b"x" * (MAX_MESSAGE + 1)


@pytest.mark.parametrize(
    ("frames", "code"),
    [
        pytest.param([frame(TEXT, b"hi", masked=False)], 1002, id="unmasked"),
        pytest.param([frame(TEXT, b"hi", rsv=4)], 1002, id="reserved-bit"),
        pytest.param([frame(0x3, b"hi")], 1002, id="unknown-data-opcode"),
        pytest.param([frame(0xB)], 1002, id="unknown-control-opcode"),
        pytest.param([frame(CONTINUATION, b"hi")], 1002, id="continuation-first"),
        pytest.param(
            [frame(TEXT, b"a", fin=False), frame(TEXT, b"b")], 1002, id="text-inside-fragments"
        ),
        pytest.param([frame(PING, b"p", fin=False)], 1002, id="fragmented-ping"),
        pytest.param([frame(PING, b"p" * 126)], 1002, id="long-ping"),
        pytest.param([frame(CLOSE, b"\x03")], 1002, id="one-byte-close"),
        pytest.param([frame(BINARY, b"\x00\x01")], 1003, id="binary"),
        pytest.param([frame(TEXT, b"\xff\xfe")], 1007, id="invalid-utf8"),
        pytest.param([frame(TEXT, "é".encode()[:1])], 1007, id="truncated-character"),
        pytest.param([frame(CLOSE, b"\x03\xe8\xff")], 1007, id="invalid-close-reason"),
        pytest.param([frame(TEXT, TOO_BIG)], 1009, id="one-frame-too-big"),
        pytest.param(
            [frame(TEXT, TOO_BIG[:40000], fin=False), frame(CONTINUATION, TOO_BIG[40000:])],
            1009,
            id="fragments-too-big",
        ),
    ],
)
def test_protocol_violations_close_with_their_code(
    web: WebServer, app: Echo, frames: list[bytes], code: int
) -> None:
    with connect(web) as client:
        client.connection.sock.sendall(b"".join(frames))
        assert client.recv_close() == code
    app.next("connected")
    app.next("disconnected")


def test_a_bad_frame_after_good_ones(web: WebServer) -> None:
    with connect(web) as client:
        client.send_text("ok")
        assert client.recv_text() == "ok"
        client.send(BINARY, b"\x00")
        assert client.recv_close() == CloseCode.UNSUPPORTED_DATA


def test_the_frame_reader_on_a_stream() -> None:
    def read(data: bytes) -> list[object]:
        reader, out = FrameReader(io.BufferedReader(io.BytesIO(data))), []
        while (message := reader.read()) is not None:
            out.append(message)
        return out

    assert read(frame(TEXT, b"a", fin=False) + frame(PONG, b"x") + frame(CONTINUATION, b"b")) == [
        (Opcode.PONG, b"x"),
        "ab",
    ]
    assert read(frame(TEXT, b"hello")[:-2]) == []  # the stream ends inside a frame
    huge = bytes((0x81, 0xFF)) + (1 << 63).to_bytes(8, "big")
    with pytest.raises(ProtocolError) as caught:
        read(huge)
    assert caught.value.code == CloseCode.PROTOCOL_ERROR


# --------------------------------------------------------------------- writing


def pair(**options: float) -> tuple[WebSocket, Connection]:
    """A WebSocket on one end of a socket pair, and a client reading the other."""
    ours, theirs = socket.socketpair()
    theirs.settimeout(WAIT)
    client = Connection.__new__(Connection)
    client.sock, client.buffer = theirs, bytearray()
    return WebSocket(ours.makefile("rb"), ours, **options), client


def frames(connection: Connection, count: int) -> list[tuple[int, bytes]]:
    out = []
    for _ in range(count):
        first, size = connection.read(2)
        out.append((first & 0x0F, connection.read(size & 0x7F)))
    return out


def test_replies_go_first_then_the_latest_of_each_slot() -> None:
    ws, client = pair()
    ws.publish("state", "s1")
    ws.publish("show", "show1")
    ws.send("reply1")
    ws.publish("state", "s2")
    ws.send("reply2")
    ws.start()
    assert frames(client, 4) == [
        (TEXT, b"reply1"),
        (TEXT, b"reply2"),
        (TEXT, b"s2"),  # slots in the order first published
        (TEXT, b"show1"),
    ]
    ws.close()
    assert frames(client, 1) == [(CLOSE, (1000).to_bytes(2, "big"))]
    client.close()
    ws.finish()


def test_nothing_is_sent_after_the_close_frame() -> None:
    ws, client = pair()
    ws.send("queued before")
    ws.close(CloseCode.GOING_AWAY)
    ws.send("after")
    ws.publish("state", "after")
    ws.start()
    assert frames(client, 1) == [(CLOSE, (1001).to_bytes(2, "big"))]
    assert client.sock.recv(1) == b""
    client.close()
    ws.finish()


def test_old_replies_are_dropped_past_the_limit() -> None:
    ws, client = pair()
    for number in range(MAX_REPLIES + 3):
        ws.send(str(number))
    ws.start()
    received = frames(client, MAX_REPLIES)
    assert received[0] == (TEXT, b"3")
    assert received[-1] == (TEXT, str(MAX_REPLIES + 2).encode())
    client.close()
    ws.abort()
    ws.finish()


def test_a_client_that_does_not_answer_the_close_is_dropped_after_the_linger() -> None:
    ws, client = pair(linger=0.2)
    ws.start()
    ws.close()
    started = time.monotonic()
    ws.finish()  # the client never closes its end
    assert 0.15 < time.monotonic() - started < 2.0
    client.close()


# --------------------------------------------------------------------- the server


def test_a_stalled_client_is_closed_without_blocking_another(web: WebServer, app: Echo) -> None:
    stalled = connect(web)
    stalled_side = app.next("connected")
    reader = connect(web)
    reader_side = app.next("connected")
    received: queue.Queue[str] = queue.Queue()

    def read() -> None:
        try:
            while True:
                received.put(reader.recv_text())
        except (EOFError, OSError):
            pass

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    big = "y" * (1 << 20)
    deadline = time.monotonic() + WAIT
    disconnected = None
    while disconnected is None and time.monotonic() < deadline:
        for client in web.clients():
            client.publish("state", big)
        try:
            event, disconnected = app.events.get(timeout=0.02)
            assert event == "disconnected"
        except queue.Empty:
            pass
    assert disconnected is stalled_side
    reader_side.publish("state", "after")
    while (text := received.get(timeout=WAIT)) != "after":
        assert text == big
    assert reader_side in web.clients()
    stalled.close()
    reader.close()
    thread.join(WAIT)


def test_close_sends_going_away_and_waits(web: WebServer, app: Echo) -> None:
    client = connect(web)
    server_side = app.next("connected")
    web.close()
    assert client.recv_close() == CloseCode.GOING_AWAY
    assert app.next("disconnected") is server_side
    assert web.clients() == ()
    web.close()  # idempotent
    client.close()


def test_an_app_error_is_counted_and_the_connection_goes_on(web: WebServer) -> None:
    with connect(web) as client:
        client.send_text("raise")
        client.send_text("still here")
        assert client.recv_text() == "still here"
    assert web.errors == 1


def test_the_remote_address_is_known(web: WebServer, app: Echo) -> None:
    with connect(web) as client:
        local = client.connection.sock.getsockname()
        assert app.next("connected").remote == f"{local[0]}:{local[1]}"


def test_a_taken_port_is_reported(app: Echo) -> None:
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        server = WebServer(app, KEY, host="127.0.0.1", port=port, page=PAGE)
        reason = server.open()
    assert reason is not None
    assert reason.startswith(f"cannot listen on 127.0.0.1:{port}")
    server.close()


def test_the_page_comes_from_the_package() -> None:
    page = index_page()
    assert page.lower().startswith(b"<!doctype html>")
    assert b"http://" not in page
    assert b"https://" not in page


# --------------------------------------------------------------------- the key


def test_the_web_key_is_made_once(tmp_path: Path) -> None:
    key = web_key(tmp_path)
    assert len(key) == 8
    assert key.replace("-", "").replace("_", "").isalnum()
    path = tmp_path / "web-key"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert web_key(tmp_path) == key
    path.unlink()
    assert web_key(tmp_path) != key


def test_a_damaged_key_file_is_replaced(tmp_path: Path) -> None:
    (tmp_path / "web-key").write_text("Qx7f2LmA has spaces\n")
    key = web_key(tmp_path)
    assert len(key) == 8
    assert (tmp_path / "web-key").read_text() == key + "\n"
    (tmp_path / "web-key").write_text("MyOwnLongerKey_123\n")
    assert web_key(tmp_path) == "MyOwnLongerKey_123"
