"""DMX-USB output (phase-6-plan §5.16): the Enttec Pro protocol on a
pseudo-terminal.

A :class:`~dmx_widget.Widget` (``tests/dmx_widget.py``) is the master side
of a pseudo-terminal: it reads what an Enttec widget would receive. The
route's port is a symlink to the slave side, so re-pointing the link at a
new pseudo-terminal is a replug, and closing the master is an unplug.
"""

from __future__ import annotations

import termios
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

from busk.compiler.compile import CompiledUniverse
from busk.engine.loop import Frame
from busk.model.common import UniverseId
from busk.model.output import DmxUsbRoute, OutputSettings
from busk.output import dmxusb
from busk.output.dmxusb import (
    REOPEN_S,
    EnttecSender,
    enttec_message,
    output_rate,
    parameters_message,
)
from busk.output.driver import RouteNotice
from busk.output.scheduler import OutputScheduler, build_routes
from dmx_widget import PARAMETERS_40, Widget, dmx_message, image, messages

STAGE = CompiledUniverse(id=UniverseId("u1"), number=1, name="Stage")
CYCLE = 1 / 44


# Bytes a cooked terminal would change: LF (→ CR LF), CR, ^C, XON, XOFF, DEL.
TRICKY = image(0x0A, 0x0D, 0x03, 0x11, 0x13, 0x7F, 0xFF)


@pytest.fixture
def port(tmp_path: Path) -> Path:
    return tmp_path / "ttyBUSK"


@pytest.fixture
def widgets(port: Path) -> Iterator[list[Widget]]:
    """Plug widgets in at ``port`` (``widgets[-1]`` is the current one)."""
    plugged = [Widget(port)]
    yield plugged
    for widget in plugged:
        widget.unplug()


def dmx_usb_route(
    port: Path | str, *, driver: str = "enttecPro", hz: float = 40, route_id: str = "r1"
) -> DmxUsbRoute:
    return cast(
        DmxUsbRoute,
        {
            "id": route_id,
            "universeId": "u1",
            "enabled": True,
            "protocol": "dmxUsb",
            "device": {"driver": driver, "port": str(port)},
            "refreshHz": hz,
        },
    )


@pytest.fixture
def sender(port: Path, widgets: list[Widget]) -> Iterator[EnttecSender]:
    opened = EnttecSender(dmx_usb_route(port))
    opened.open()
    yield opened
    opened.close()


# ------------------------------------------------------------- the messages


def test_a_message_is_start_label_length_data_end() -> None:
    assert enttec_message(4, bytes((0, 0, 9, 1, 40))) == PARAMETERS_40
    assert parameters_message(40) == PARAMETERS_40
    assert enttec_message(6, b"\x00" + TRICKY) == dmx_message(TRICKY)
    assert enttec_message(9, b"") == bytes.fromhex("7e 09 00 00 e7")


@pytest.mark.parametrize(
    ("hz", "rate"), [(40, 40), (44, 40), (25.4, 25), (25.6, 26), (1, 1), (0.2, 1), (0, 1)]
)
def test_the_output_rate_is_refresh_hz_rounded_within_1_to_40(hz: float, rate: int) -> None:
    assert output_rate(hz) == rate


# ------------------------------------------------------------- sending


def test_open_writes_the_parameters_and_the_first_send_a_frame_byte_for_byte(
    port: Path, widgets: list[Widget], sender: EnttecSender
) -> None:
    assert widgets[0].read() == PARAMETERS_40
    sender.send(TRICKY, True, 0.0)
    assert widgets[0].read() == dmx_message(TRICKY)  # raw: no CR added, nothing swallowed
    status = sender.status()
    assert (status.ok, status.detail, status.packets, status.errors) == (True, "", 1, 0)
    assert sender.protocol == "dmxUsb"
    assert sender.description == f"Enttec DMX USB Pro on {port} at 40 Hz"


def test_the_device_is_raw_8n1_at_115200_baud_without_flow_control(
    port: Path, widgets: list[Widget]
) -> None:
    # Left by another program (the pty driver itself keeps parity off).
    widgets[0].configure(termios.CSTOPB | termios.CRTSCTS)
    sender = EnttecSender(dmx_usb_route(port))
    sender.open()
    sender.close()
    iflag, oflag, cflag, lflag, ispeed, ospeed, _ = widgets[0].mode()
    assert iflag & (termios.ICRNL | termios.IXON | termios.ISTRIP) == 0
    assert oflag & termios.OPOST == 0
    assert lflag & (termios.ECHO | termios.ICANON | termios.ISIG) == 0
    assert cflag & termios.CSIZE == termios.CS8
    assert cflag & (termios.PARENB | termios.CSTOPB | termios.CRTSCTS) == 0
    assert cflag & (termios.CLOCAL | termios.CREAD) == termios.CLOCAL | termios.CREAD
    assert (ispeed, ospeed) == (termios.B115200, termios.B115200)


def test_the_route_rate_goes_into_the_parameters(port: Path, widgets: list[Widget]) -> None:
    sender = EnttecSender(dmx_usb_route(port, driver="dmxking", hz=25))
    sender.open()
    try:
        assert widgets[0].read() == parameters_message(25)
        assert sender.description == f"DMXking on {port} at 25 Hz"
    finally:
        sender.close()


def test_frames_go_out_on_change_and_every_second(
    widgets: list[Widget], sender: EnttecSender
) -> None:
    widget = widgets[0]
    widget.read()
    sent = []
    for now, data, changed in [
        (0.0, image(1), True),
        (CYCLE, image(1), False),
        (0.5, image(2), True),
        (1.0, image(2), False),  # 0.5 s after the last frame
        (1.5, image(2), False),  # the keep-alive
        (1.5 + CYCLE, image(2), False),
        (2.5, image(2), False),
    ]:
        sender.send(data, changed, now)
        sent.append([data[0] for _, data in messages(widget.read())])
    # The data starts with the start code 0, then the first slot.
    assert sent == [[0], [], [0], [], [0], [], [0]]
    assert sender.status().packets == 4


def test_a_partial_write_is_finished_first_and_a_frame_due_meanwhile_is_dropped(
    widgets: list[Widget], sender: EnttecSender
) -> None:
    widget = widgets[0]
    offered: list[bytes] = []
    now = 0.0
    while sender.status().dropped == 0:  # the widget reads nothing, so its buffer fills
        assert len(offered) < 1000, "the pseudo-terminal never filled"
        offered.append(image(len(offered) % 256, 0x0A))
        sender.send(offered[-1], True, now)
        now += CYCLE
    first = widget.read()
    assert (len(first) - len(PARAMETERS_40)) % len(dmx_message(TRICKY)) != 0  # cut mid-message
    sender.send(offered[-1], False, now)  # unchanged, but the dropped frame is owed
    stream = first + widget.read()
    received = messages(stream)
    assert received[0] == (4, PARAMETERS_40[4:-1])
    # Every frame arrives whole and in order; the dropped one arrives a cycle late.
    assert [data for _, data in received[1:]] == [b"\x00" + data for data in offered]
    status = sender.status()
    assert (status.ok, status.packets, status.errors, status.dropped) == (
        True,
        len(offered),
        0,
        1,
    )
    sender.send(offered[-1], False, now + CYCLE)
    assert widget.read() == b""  # nothing owed any more


# ------------------------------------------------------------- unplug and replug


def test_an_unplug_marks_the_route_failed(
    port: Path, widgets: list[Widget], sender: EnttecSender
) -> None:
    sender.send(image(1), True, 0.0)
    widgets[0].unplug()
    sender.send(image(2), True, 0.5)
    status = sender.status()
    assert (status.ok, status.detail, status.packets, status.errors) == (
        False,
        f"{port}: Input/output error",
        1,
        1,
    )
    sender.send(image(3), True, 0.6)
    assert sender.status().errors == 1  # closed: nothing is written until it reopens


def test_a_replug_sends_the_parameters_and_a_full_frame_again(
    port: Path, widgets: list[Widget], sender: EnttecSender
) -> None:
    sender.send(image(1), True, 0.0)
    widgets[0].unplug()
    sender.send(image(2), True, 0.5)  # fails: reopen at 1.5 at the earliest
    sender.send(image(2), False, 1.5)  # the port is gone: reopen at 2.5
    assert sender.status().detail == f"{port}: No such file or directory"
    widgets.append(Widget(port))
    sender.send(image(2), False, 2.0)
    assert widgets[1].read() == b""  # not yet: at most one try per second
    sender.send(image(2), False, 2.5)
    assert widgets[1].read() == PARAMETERS_40 + dmx_message(image(2))
    status = sender.status()
    assert (status.ok, status.detail, status.packets, status.errors) == (True, "", 2, 1)
    sender.send(image(2), False, 2.5 + CYCLE)
    assert widgets[1].read() == b""  # back to the send policy


def test_a_reopened_device_gets_a_frame_at_once_whatever_the_keep_alive(
    port: Path, widgets: list[Widget], sender: EnttecSender, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dmxusb, "REOPEN_S", 0.25)  # sooner than the 1 s keep-alive
    widgets[0].unplug()
    sender.send(image(1), True, 0.5)
    widgets.append(Widget(port))
    sender.send(image(1), False, 0.75)
    assert widgets[1].read() == PARAMETERS_40 + dmx_message(image(1))


def test_a_device_that_fails_on_reopen_waits_another_second(
    port: Path, widgets: list[Widget], sender: EnttecSender
) -> None:
    widgets[0].unplug()
    sender.send(image(1), True, 0.0)
    assert REOPEN_S == 1.0
    # Each time the port turns into something else, so every try leaves its own detail.
    not_serial = f"{port}: cannot configure the serial device: Inappropriate ioctl for device"
    tries = []
    for now, kind in [(0.5, "file"), (1.0, "dir"), (1.5, "file"), (2.0, "file"), (2.5, "dir")]:
        port.unlink()
        if kind == "dir":
            port.mkdir()
        else:
            port.write_bytes(b"")
        sender.send(image(1), False, now)
        tries.append(sender.status().detail)
        if kind == "dir":
            port.rmdir()
        else:
            port.unlink()
        port.symlink_to("/nonexistent")
    assert tries == [
        f"{port}: Input/output error",  # no try yet
        f"{port}: Is a directory",  # tried at 1.0
        f"{port}: Is a directory",  # no try before 2.0
        not_serial,  # tried at 2.0
        not_serial,  # no try before 3.0
    ]


def test_close_sends_nothing_and_a_closed_route_never_reopens(
    port: Path, widgets: list[Widget], sender: EnttecSender
) -> None:
    sender.send(image(1), True, 0.0)
    widgets[0].read()
    sender.close()
    sender.close()  # idempotent
    assert widgets[0].read() == b""
    sender.send(image(2), True, 5.0)
    assert widgets[0].read() == b""
    assert sender.status().packets == 1


def test_close_finishes_a_message_cut_short_if_the_device_takes_it(
    widgets: list[Widget], sender: EnttecSender
) -> None:
    widget = widgets[0]
    now = 0.0
    while sender.status().dropped == 0:
        sender.send(image(int(now * 44) % 256), True, now)
        now += CYCLE
    stream = widget.read()  # makes room for the rest
    sender.close()
    stream += widget.read()
    assert len(messages(stream)) == 1 + sender.status().packets  # ends on a message boundary


def test_a_route_failed_while_sending_stops_reopening_once_closed(
    port: Path, widgets: list[Widget], sender: EnttecSender
) -> None:
    widgets[0].unplug()
    sender.send(image(1), True, 0.0)
    sender.close()
    widgets.append(Widget(port))
    sender.send(image(1), True, 5.0)
    assert widgets[1].read() == b""


# ------------------------------------------------------------- open failures


def test_a_missing_port_fails_to_open_and_is_not_retried(tmp_path: Path) -> None:
    port = tmp_path / "ttyUSB9"
    sender = EnttecSender(dmx_usb_route(port))
    sender.open()
    assert sender.status().ok is False
    assert sender.status().detail == f"{port}: No such file or directory"
    widget = Widget(port)
    try:
        sender.send(image(1), True, 10.0)
        assert widget.read() == b""  # only a route that failed while sending reopens
    finally:
        widget.unplug()
        sender.close()


def test_a_file_that_is_not_a_serial_device_fails_to_open(tmp_path: Path) -> None:
    port = tmp_path / "plain"
    port.write_bytes(b"")
    sender = EnttecSender(dmx_usb_route(port))
    sender.open()
    assert sender.status().detail == (
        f"{port}: cannot configure the serial device: Inappropriate ioctl for device"
    )
    assert port.read_bytes() == b""


# ------------------------------------------------------------- the scheduler


def settings(*routes: DmxUsbRoute) -> OutputSettings:
    return cast(
        OutputSettings,
        {
            "engineHz": 100,
            "sacnSourceName": "Busk Console",
            "sacnCid": "6f2b0c1e-4c1a-4d5e-9f00-000000000001",
            "holdLastFrameOnEngineStall": True,
            "routes": list(routes),
        },
    )


class Source:
    def __init__(self, latest: Frame) -> None:
        self.latest = latest


def test_build_routes_opens_pro_and_dmxking_routes_and_ignores_the_others(
    port: Path, widgets: list[Widget]
) -> None:
    missing = port.with_name("ttyGONE")
    routes, notices = build_routes(
        settings(
            dmx_usb_route(port, route_id="r1"),
            dmx_usb_route(port, driver="enttecOpen", route_id="r2"),
            dmx_usb_route(port, driver="ftdiRaw", route_id="r3"),
            dmx_usb_route(missing, driver="dmxking", route_id="r4"),
            {**dmx_usb_route(port, route_id="r5"), "enabled": False},
        ),
        (STAGE,),
    )
    try:
        assert [(r.label, r.description) for r in routes] == [
            ("DMX-USB r1", f"U1 Stage → Enttec DMX USB Pro on {port} at 40 Hz"),
        ]
        open_dmx = "Open DMX USB needs host-timed breaks; use an Enttec Pro or DMXking interface"
        unknown = "unknown interface driver 'ftdiRaw'; use enttecPro or dmxking"
        gone = f"{missing}: No such file or directory"
        assert notices == [
            RouteNotice(
                text=f"DMX-USB r2: ignored ({open_dmx})", failed=False, route="r2", detail=open_dmx
            ),
            RouteNotice(
                text=f"DMX-USB r3: ignored ({unknown})", failed=False, route="r3", detail=unknown
            ),
            RouteNotice(
                text=f"DMX-USB r4: cannot open: {gone}", failed=True, route="r4", detail=gone
            ),
            RouteNotice(text="DMX-USB r5: disabled", failed=False, route="r5"),
        ]
    finally:
        for route in routes:
            route.driver.close()


def test_the_scheduler_sends_frames_and_reopens_a_replugged_widget(
    port: Path, widgets: list[Widget]
) -> None:
    routes, _ = build_routes(settings(dmx_usb_route(port)), (STAGE,))
    source = Source(Frame(seq=1, time=0.0, universes=(TRICKY,)))
    scheduler = OutputScheduler(source, routes, clock=cast(Any, None))
    scheduler.service(0.0)
    assert widgets[0].read() == PARAMETERS_40 + dmx_message(TRICKY)
    widgets[0].unplug()
    source.latest = Frame(seq=2, time=0.1, universes=(image(9),))
    scheduler.service(0.1)
    assert routes[0].driver.status().ok is False
    widgets.append(Widget(port))
    scheduler.service(0.1 + REOPEN_S)
    assert widgets[1].read() == PARAMETERS_40 + dmx_message(image(9))
    assert routes[0].driver.status().ok is True
    scheduler.close()
    assert routes[0].faults == 0
