"""Feedback (phase-6-plan §5.10): what each binding shows, and the worker.

:func:`feedback_values` is tested against hand-built snapshots, row by row
of the §5.10 table, and against a running engine for page changes and the
tap LED. :class:`FeedbackWorker` is tested with fake senders (diffs, a full
send on reopen, the echo hold, errors) and with faked MIDI output ports.
"""

from __future__ import annotations

import threading
from typing import Any, cast

import mido
import pytest

from builders import APPENDIX_A, Doc, compile_doc, load_doc
from busk.commands.types import Command
from busk.compiler.compile import CompiledShow
from busk.engine.snapshot import EngineSnapshot, PageStatus, PlaybackStatus, SpeedStatus
from busk.io import midi
from busk.io.feedback import ECHO_HOLD, FeedbackValue, FeedbackWorker, feedback_values
from busk.model.common import MasterId, PlaybackId, SurfaceId
from busk.model.surface import InputAddress
from busk.process.report import say, warn
from harness import Harness, tap

type Spec = tuple[str, Doc, str] | tuple[str, Doc, str, str]
"""A binding: id, action, feedback kind and optionally its surface."""


def build(*specs: Spec, edit: Doc | None = None, goto_cue: bool = True) -> CompiledShow:
    """Appendix A with pages 2 "Washes" (pb-blue, pb-song) and 4 "Four"
    (empty), wider buttons, a second MIDI surface ``s-two``, and one binding
    per spec: binding *i* listens to CC *i* and sends feedback there.
    ``edit`` replaces the first binding's feedback."""
    doc = load_doc(APPENDIX_A)  # page 1 "Main": pb-song, -, pb-blue, -, -, pb-pulse, -, -
    doc["pages"] += [
        {"id": "page-2", "number": 2, "name": "Washes", "slots": ["pb-blue", "pb-song"]},
        {"id": "page-4", "number": 4, "name": "Four", "slots": []},
    ]
    doc["playbacks"][0]["buttons"] = ["go", "back", "goto", "release", "select", "none"]
    if goto_cue:
        doc["playbacks"][0]["gotoCue"] = "2"
    doc["playbacks"][1]["buttons"] = ["toggle", "flash", "swop"]
    doc["surfaces"].append(
        {"id": "s-two", "name": "Two", "kind": "midi", "match": {"deviceName": "Two"},
         "faderPickup": "jump"}
    )  # fmt: skip
    doc["bindings"] = [
        {"id": spec[0], "surfaceId": spec[3] if len(spec) == 4 else "s-midi",
         "input": cc(i), "action": spec[1], "feedback": {"kind": spec[2], "address": cc(i)}}
        for i, spec in enumerate(specs)
    ]  # fmt: skip
    if edit is not None:
        doc["bindings"][0]["feedback"] = edit
    return compile_doc(doc)


def cc(number: int) -> Doc:
    return {"kind": "midiCC", "channel": 1, "cc": number}


def fader(slot: int) -> Doc:
    return {"kind": "playbackFader", "slot": slot}


def button(slot: int, index: int) -> Doc:
    return {"kind": "playbackButton", "slot": slot, "button": index}


def status(ident: str, name: str, **fields: Any) -> PlaybackStatus:
    defaults: dict[str, Any] = {"number": 1, "state": "idle", "faderLevel": 0.0, "flash": False}
    return PlaybackStatus(id=PlaybackId(ident), name=name, **(defaults | fields))


IDLE = (status("pb-song", "Song"), status("pb-blue", "Blue"), status("pb-pulse", "Slow Pulse"))
PAGES = {1: ("page-1", "Main"), 2: ("page-2", "Washes"), 4: ("page-4", "Four")}


def snapshot(
    *changed: PlaybackStatus,
    page: int = 1,
    blackout: bool = False,
    gm: float = 1.0,
    bpm: float = 120.0,
    anchor: tuple[float, float] = (0.0, 0.0),
) -> EngineSnapshot:
    """A snapshot of the :func:`build` show: the playbacks idle at 0 unless
    ``changed``."""
    playbacks = {s.id: s for s in IDLE} | {s.id: s for s in changed}
    ident, name = PAGES[page]
    speed = SpeedStatus(
        id=MasterId("m-speed"), name="Speed 1", bpm=bpm, multiplier=1.0, level=0.5,
        beatTime=anchor[0], beat=anchor[1],
    )  # fmt: skip
    return EngineSnapshot(
        seq=1,
        time=0.0,
        grandMaster=gm,
        blackout=blackout,
        playbacks=tuple(playbacks.values()),
        masterLevels=((MasterId("m-gm"), gm), (MasterId("m-speed"), 0.5)),
        speed=(speed,),
        page=PageStatus(id=ident, number=page, name=name),
    )


# ------------------------------------------------------------ the §5.10 table

TABLE: tuple[Spec, ...] = (
    ("fader-led", fader(0), "led"),
    ("fader-motor", fader(0), "motorFader"),
    ("fader-name", fader(0), "display"),
    ("empty-led", fader(1), "led"),
    ("empty-motor", fader(1), "motorFader"),
    ("empty-name", fader(1), "display"),
    ("off-motor", fader(9), "motorFader"),  # beyond the page
    ("abs-led", {"kind": "playbackFaderAbs", "playbackId": "pb-blue"}, "led"),
    ("abs-motor", {"kind": "playbackFaderAbs", "playbackId": "pb-blue"}, "motorFader"),
    ("abs-name", {"kind": "playbackFaderAbs", "playbackId": "pb-blue"}, "display"),
    ("go", button(0, 0), "led"),
    ("back", button(0, 1), "led"),
    ("goto", button(0, 2), "led"),
    ("release", button(0, 3), "led"),
    ("select", button(0, 4), "led"),
    ("none", button(0, 5), "led"),
    ("beyond", button(0, 6), "led"),  # pb-song has six buttons
    ("button-name", button(0, 0), "display"),
    ("button-motor", button(0, 0), "motorFader"),  # nothing to show
    ("toggle", button(2, 0), "led"),
    ("flash", button(2, 1), "led"),
    ("swop", button(2, 2), "led"),
    ("empty-button", button(1, 0), "led"),
    ("empty-button-name", button(1, 0), "display"),
    ("gm-led", {"kind": "master", "masterId": "m-gm"}, "led"),
    ("gm-motor", {"kind": "master", "masterId": "m-gm"}, "motorFader"),
    ("gm-name", {"kind": "master", "masterId": "m-gm"}, "display"),
    ("speed-motor", {"kind": "master", "masterId": "m-speed"}, "motorFader"),
    ("tap-led", {"kind": "tap", "masterId": "m-speed"}, "led"),
    ("tap-name", {"kind": "tap", "masterId": "m-speed"}, "display"),
    ("tap-motor", {"kind": "tap", "masterId": "m-speed"}, "motorFader"),  # nothing
    ("bo-led", {"kind": "blackout"}, "led"),
    ("bo-name", {"kind": "blackout"}, "display"),  # nothing
    ("next-led", {"kind": "page", "delta": 1}, "led"),
    ("prev-led", {"kind": "page", "delta": -1}, "led"),
    ("zero-led", {"kind": "page", "delta": 0}, "led"),
    ("page-name", {"kind": "page", "delta": 1}, "display"),
    ("page-motor", {"kind": "page", "delta": 1}, "motorFader"),  # nothing
    ("p2-led", {"kind": "pageAbs", "number": 2}, "led"),
    ("p2-name", {"kind": "pageAbs", "number": 2}, "display"),
    ("p3-name", {"kind": "pageAbs", "number": 3}, "display"),  # no page 3
    ("cmd-led", {"kind": "command", "command": {"type": "BLACKOUT"}}, "led"),  # nothing
)


@pytest.fixture(scope="module")
def table() -> CompiledShow:
    return build(*TABLE)


def test_every_row_of_the_table(table: CompiledShow) -> None:
    """Page 1: pb-song active at cue 2 with its fader at 0.6; pb-blue idle
    with its flash present; GM 0.8 and blackout on; on the beat."""
    song = status("pb-song", "Song", state="active", faderLevel=0.6, cue="2")
    blue = status("pb-blue", "Blue", flash=True)
    values = feedback_values(table, snapshot(song, blue, gm=0.8, blackout=True, bpm=127.5), 0.0)
    assert values == {
        "fader-led": 1.0, "fader-motor": 0.6, "fader-name": "Song",
        "empty-led": 0.0, "empty-motor": 0.0, "empty-name": "",
        "off-motor": 0.0,
        "abs-led": 0.0, "abs-motor": 0.0, "abs-name": "Blue",
        "go": 1.0, "back": 1.0, "goto": 1.0, "release": 1.0, "select": 1.0,
        "none": 0.0, "beyond": 0.0, "button-name": "Song",
        "toggle": 0.0, "flash": 1.0, "swop": 0.0,
        "empty-button": 0.0, "empty-button-name": "",
        "gm-led": 1.0, "gm-motor": 0.8, "gm-name": "Grand Master", "speed-motor": 0.5,
        "tap-led": 1.0, "tap-name": "127.5 BPM",
        "bo-led": 1.0,
        "next-led": 1.0, "prev-led": 0.0, "zero-led": 0.0, "page-name": "Main",
        "p2-led": 0.0, "p2-name": "Washes", "p3-name": "",
    }  # fmt: skip


def pick(values: dict[str, FeedbackValue], *idents: str) -> tuple[FeedbackValue | None, ...]:
    return tuple(values.get(ident) for ident in idents)


BUTTONS = ("go", "back", "goto", "release", "select", "none")


def test_button_leds_follow_the_playback_state(table: CompiledShow) -> None:
    def leds(*changed: PlaybackStatus) -> tuple[FeedbackValue | None, ...]:
        return pick(feedback_values(table, snapshot(*changed), 0.0), *BUTTONS)

    assert leds() == (0.0,) * 6  # idle
    song = status("pb-song", "Song", state="active", cue="1")
    assert leds(song) == (1.0, 1.0, 0.0, 1.0, 1.0, 0.0)  # goto: lit only at its cue
    releasing = status("pb-song", "Song", state="releasing", cue="2")
    assert leds(releasing) == (0.0,) * 6
    flashing = status("pb-song", "Song", flash=True)  # a flash alone lights no go
    assert leds(flashing) == (0.0,) * 6


def test_flash_swop_and_toggle_leds(table: CompiledShow) -> None:
    def leds(blue: PlaybackStatus) -> tuple[FeedbackValue | None, ...]:
        return pick(feedback_values(table, snapshot(blue), 0.0), "toggle", "flash", "swop")

    assert leds(status("pb-blue", "Blue", state="active")) == (1.0, 0.0, 0.0)
    assert leds(status("pb-blue", "Blue", flash=True, swop=True)) == (0.0, 1.0, 1.0)


def test_a_goto_button_without_a_goto_cue_stays_dark() -> None:
    compiled = build(("goto", button(0, 2), "led"), goto_cue=False)
    song = status("pb-song", "Song", state="active", cue="2")
    assert feedback_values(compiled, snapshot(song), 0.0) == {"goto": 0.0}


def test_levels_at_zero_are_dark(table: CompiledShow) -> None:
    values = feedback_values(table, snapshot(gm=0.0), 0.0)
    assert pick(values, "fader-led", "fader-motor", "gm-led", "gm-motor", "bo-led") == (
        0.0, 0.0, 0.0, 0.0, 0.0,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("page", "expected"),
    [
        (1, (1.0, 0.0, "Main", 0.0)),
        (2, (1.0, 1.0, "Washes", 1.0)),
        (4, (0.0, 1.0, "Four", 0.0)),
    ],
)
def test_page_leds_and_names(
    table: CompiledShow, page: int, expected: tuple[FeedbackValue, ...]
) -> None:
    values = feedback_values(table, snapshot(page=page), 0.0)
    assert pick(values, "next-led", "prev-led", "page-name", "p2-led") == expected
    assert pick(values, "zero-led", "p2-name") == (0.0, "Washes")


def test_a_snapshot_page_gone_after_an_edit_reads_as_the_first_page(table: CompiledShow) -> None:
    gone = snapshot(status("pb-song", "Song", faderLevel=0.5))
    gone = EngineSnapshot(**{**_fields(gone), "page": PageStatus(id="page-9", number=9, name="")})
    assert pick(feedback_values(table, gone, 0.0), "fader-motor", "page-name") == (0.5, "Main")


def _fields(snap: EngineSnapshot) -> dict[str, Any]:
    return {f: getattr(snap, f) for f in snap.__dataclass_fields__}


@pytest.mark.parametrize(
    ("now", "lit"),
    [(0.0, 1.0), (0.1, 1.0), (0.125, 0.0), (0.3, 0.0), (0.5, 1.0), (0.62, 1.0), (0.63, 0.0)],
)
def test_the_tap_led_lights_the_first_quarter_of_each_beat(
    table: CompiledShow, now: float, lit: float
) -> None:
    """At 120 BPM a beat is 0.5 s: lit from each beat for 0.125 s."""
    assert feedback_values(table, snapshot(), now)["tap-led"] == lit


# ---------------------------------------------------- against the engine


def page_cmd(number: int) -> Command:
    return cast(Command, {"type": "PAGE", "number": number})


def test_a_page_change_moves_every_page_relative_value(table: CompiledShow) -> None:
    harness = Harness(table)
    harness.submit(cast(Command, {"type": "SET_FADER", "playbackId": "pb-song", "level": 0.7}))
    first = harness.tick(0.0).snapshot  # raising its master fader started pb-song
    assert first is not None
    relative = ("fader-motor", "fader-name", "toggle", "go", "page-name", "prev-led", "p2-led")
    assert pick(feedback_values(table, first, 0.0), *relative) == (
        0.7, "Song", 0.0, 1.0, "Main", 0.0, 0.0,
    )  # fmt: skip
    harness.submit(page_cmd(2))  # slot 0: pb-blue (idle); slot 2: nothing
    second = harness.tick(0.02).snapshot
    assert second is not None
    values = feedback_values(table, second, 0.02)
    assert pick(values, *relative) == (0.0, "Blue", 0.0, 0.0, "Washes", 1.0, 1.0)
    assert pick(values, "abs-name", "gm-motor", "fader-led") == ("Blue", 1.0, 0.0)
    harness.submit(page_cmd(4))  # an empty page
    third = harness.tick(0.04).snapshot
    assert third is not None
    values = feedback_values(table, third, 0.04)
    assert pick(values, "fader-name", "button-name", "next-led", "page-name") == (
        "", "", 0.0, "Four",
    )  # fmt: skip


def test_the_tap_led_follows_the_anchor_across_a_tap(table: CompiledShow) -> None:
    harness = Harness(table)  # m-speed at 120 BPM from 0 s
    before = harness.tick(0.0).snapshot
    assert before is not None
    assert feedback_values(table, before, 1.4)["tap-led"] == 0.0  # 2.8 beats
    harness.submit(tap("m-speed"))  # at 1.3 s = 2.6 beats: the tap lands on beat 3
    after = harness.tick(1.3).snapshot
    assert after is not None
    assert [feedback_values(table, after, t)["tap-led"] for t in (1.3, 1.4, 1.45, 1.8)] == [
        1.0, 1.0, 0.0, 1.0,
    ]  # fmt: skip


# ------------------------------------------------------------- the worker


class FakeSender:
    """Records what it sends, as (cc, kind, value); can fail."""

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[int, str, FeedbackValue]] = []
        self.fail = fail

    def send(self, address: InputAddress, kind: str, value: FeedbackValue) -> None:
        self.sent.append((cast(Doc, address)["cc"], kind, value))
        if self.fail:
            raise OSError("unplugged")


@pytest.fixture(autouse=True)
def no_midi_ports(monkeypatch: pytest.MonkeyPatch) -> None:
    """No real MIDI output port is ever opened here."""
    monkeypatch.setattr(midi, "output_names", list)


SMALL: tuple[Spec, ...] = (
    ("led", button(0, 0), "led"),  # cc 0
    ("motor", fader(0), "motorFader"),  # cc 1
    ("name", fader(0), "display"),  # cc 2
    ("gm", {"kind": "master", "masterId": "m-gm"}, "motorFader", "s-two"),  # cc 3
)


class Rig:
    """A worker over :data:`SMALL`, with a settable snapshot and senders."""

    def __init__(self, *, compiled: CompiledShow | None = None) -> None:
        self.compiled = compiled or build(*SMALL)
        self.snapshot: EngineSnapshot | None = snapshot()
        self.lastInput: dict[str, float] = {}
        self.senders: dict[SurfaceId, Any] = {
            SurfaceId("s-midi"): FakeSender(),
            SurfaceId("s-two"): FakeSender(),
        }
        self.reports: list[str] = []
        self.worker = FeedbackWorker(
            lambda: self.compiled,
            lambda: self.snapshot,
            self.lastInput,
            senders=lambda: self.senders,
            report=self.reports.append,
            say=say,
            warn=warn,
        )

    def sent(self, surface: str = "s-midi") -> list[tuple[int, str, FeedbackValue]]:
        """What ``surface``'s sender got since the last call."""
        sender = self.senders[SurfaceId(surface)]
        sent, sender.sent = sender.sent, []
        return cast(list[tuple[int, str, FeedbackValue]], sent)


ACTIVE = status("pb-song", "Song", state="active", faderLevel=0.5, cue="1")


def test_nothing_is_sent_before_the_first_snapshot() -> None:
    rig = Rig()
    rig.snapshot = None
    rig.worker.service(0.0)
    assert rig.sent() == rig.sent("s-two") == []


def test_only_changed_values_are_sent_and_everything_on_reopen() -> None:
    rig = Rig()
    rig.worker.service(0.0)
    assert rig.sent() == [(0, "led", 0.0), (1, "motorFader", 0.0), (2, "display", "Song")]
    assert rig.sent("s-two") == [(3, "motorFader", 1.0)]
    rig.worker.service(0.1)
    assert rig.sent() == rig.sent("s-two") == []
    rig.snapshot = snapshot(ACTIVE)
    rig.worker.service(0.2)
    assert rig.sent() == [(0, "led", 1.0), (1, "motorFader", 0.5)]
    assert rig.sent("s-two") == []
    rig.senders[SurfaceId("s-midi")] = FakeSender()  # the surface reopened
    rig.worker.service(0.3)
    assert rig.sent() == [(0, "led", 1.0), (1, "motorFader", 0.5), (2, "display", "Song")]
    assert rig.sent("s-two") == []
    del rig.senders[SurfaceId("s-two")]  # closed, then back: everything again
    rig.worker.service(0.4)
    rig.senders[SurfaceId("s-two")] = FakeSender()
    rig.worker.service(0.5)
    assert rig.sent("s-two") == [(3, "motorFader", 1.0)]


def test_an_edited_feedback_address_gets_the_value() -> None:
    rig = Rig()
    rig.worker.service(0.0)
    rig.sent()
    rig.compiled = build(*SMALL, edit={"kind": "led", "address": cc(100)})
    rig.worker.service(0.1)
    assert rig.sent() == [(100, "led", 0.0)]  # the same value, on its new address


def test_the_echo_hold_holds_motor_faders_only() -> None:
    rig = Rig()
    rig.worker.service(0.0)
    rig.sent()
    rig.snapshot = snapshot(ACTIVE)
    rig.lastInput.update(motor=1.0, led=1.0)  # both controls moved at 1 s
    rig.worker.service(1.2)
    assert rig.sent() == [(0, "led", 1.0)]
    rig.worker.service(1.0 + ECHO_HOLD - 0.01)
    assert rig.sent() == []
    rig.worker.service(1.0 + ECHO_HOLD)  # the hold is over: the fader goes where the show is
    assert rig.sent() == [(1, "motorFader", 0.5)]


def test_a_failing_sender_is_counted_and_reported_once() -> None:
    rig = Rig()
    rig.senders[SurfaceId("s-midi")] = FakeSender(fail=True)
    rig.worker.service(0.0)
    assert rig.reports == ["feedback to s-midi: OSError: unplugged"]
    assert rig.sent("s-two") == [(3, "motorFader", 1.0)]  # the other surface is served
    rig.snapshot = snapshot(ACTIVE)
    rig.worker.service(0.1)
    assert len(rig.sent()) == 5  # each value tried once, not again every cycle
    assert rig.worker.errors == {"s-midi": 5}
    assert len(rig.reports) == 1


# ------------------------------------------------------------ MIDI ports


class FakeOutput:
    def __init__(self, name: str) -> None:
        self.name, self.sent, self.closed = name, list[Any](), 0

    def send(self, message: Any) -> None:
        self.sent.append(message)

    def close(self) -> None:
        self.closed += 1


@pytest.fixture
def outputs(monkeypatch: pytest.MonkeyPatch) -> list[FakeOutput]:
    opened: list[FakeOutput] = []

    def open_output(name: str) -> FakeOutput:
        opened.append(FakeOutput(name))
        return opened[-1]

    monkeypatch.setattr(midi, "output_names", lambda: ["nanoKONTROL2 CTRL", "Other"])
    monkeypatch.setattr(midi.mido, "open_output", open_output)
    return opened


def test_the_worker_opens_midi_outputs_for_surfaces_with_feedback(
    outputs: list[FakeOutput], capsys: pytest.CaptureFixture[str]
) -> None:
    rig = Rig()
    rig.senders = {}
    rig.snapshot = snapshot(ACTIVE)
    rig.worker.service(0.0)
    out, err = capsys.readouterr()
    assert out == "MIDI s-midi feedback: nanoKONTROL2 CTRL\n"
    assert err == "MIDI s-two feedback: 'Two' not found; available: nanoKONTROL2 CTRL, Other\n"
    (port,) = outputs
    assert port.sent == [  # the display has no MIDI message
        mido.Message("control_change", channel=0, control=0, value=127),
        mido.Message("control_change", channel=0, control=1, value=64),
    ]
    rig.compiled = build(*SMALL[3:])  # s-midi has no feedback left: its port closes
    rig.worker.service(0.1)
    assert port.closed == 1
    assert capsys.readouterr() == ("", "")  # s-two unchanged: not tried again
    rig.worker.close()
    assert port.closed == 1


def test_run_services_until_stopped_then_closes_the_ports(outputs: list[FakeOutput]) -> None:
    rig = Rig()
    rig.senders = {}
    stop = threading.Event()
    thread = threading.Thread(target=rig.worker.run, args=(stop,))
    thread.start()
    try:
        for _ in range(200):
            if outputs and outputs[0].sent:
                break
            stop.wait(0.01)
    finally:
        stop.set()
        thread.join(timeout=2.0)
    assert not thread.is_alive()
    (port,) = outputs
    assert len(port.sent) == 2  # led and motor, once: nothing changed afterwards
    assert port.closed == 1


def test_run_reports_an_unexpected_error_once_and_goes_on() -> None:
    rig = Rig()
    calls = 0
    stop = threading.Event()

    def broken() -> EngineSnapshot:
        nonlocal calls
        calls += 1
        if calls >= 3:
            stop.set()
        raise RuntimeError("bug")

    rig.worker = FeedbackWorker(
        lambda: rig.compiled, broken, {}, clock=lambda: 0.0, report=rig.reports.append
    )
    rig.worker.run(stop)
    assert calls == 3
    assert rig.reports == ["feedback: RuntimeError: bug"]
