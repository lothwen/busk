"""A stalled engine (phase-7-plan decision 14, §5.13, step 5).

When no new frame arrives for ``STALL_S``, the output keeps sending the
last frame as keep-alives: as it is (``holdLastFrameOnEngineStall: true``)
or with every intensity byte at its value for intensity 0 (``false``), so
the stage goes dark without heads swinging home. The dark bytes come from
the compiled show (:class:`~busk.compiler.compile.OutputLayout`).

The rig: a 16-bit dimmer with a focus channel at address 1, an inverted
8-bit dimmer at 10 and Appendix A's virtual-intensity RGB par at 20.
"""

from __future__ import annotations

from builders import APPENDIX_A, Doc, channel, compile_doc, fixture, load_doc, mode, profile, show
from busk.compiler.compile import CompiledShow, OutputLayout
from busk.engine.clock import FakeClock
from busk.engine.loop import Frame
from busk.output.scheduler import OUTPUT_HZ, STALL_S, OutputScheduler, ScheduledRoute
from test_output_scheduler import Recorder, Source

CYCLE = 1 / OUTPUT_HZ
DIMMER, FOCUS, INVERTED, PAR = 0, 2, 9, 19  # 0-based byte positions


def rig(hold: bool) -> CompiledShow:
    par = load_doc(APPENDIX_A)["profiles"][1]
    doc: Doc = show(
        [
            profile("p-dim16", mode([channel(0, "intensity", nbytes=2), channel(2, "focus")])),
            profile("p-inv", mode([channel(0, "intensity", invert=True)])),
            par,
        ],
        [
            fixture("fx-d16", 1, "p-dim16", 1),
            fixture("fx-inv", 2, "p-inv", 10),
            fixture("fx-par", 3, "prof-par", 20, mode_id="mode-3"),
        ],
    )
    doc["output"]["holdLastFrameOnEngineStall"] = hold
    return compile_doc(doc)


def lit_universe() -> bytes:
    data = bytearray(512)
    data[DIMMER : DIMMER + 3] = bytes([255, 255, 77])  # full, focus 77
    data[INVERTED] = 0  # inverted: full
    data[PAR : PAR + 3] = bytes([200, 100, 50])
    data[300] = 9  # a byte no fixture owns
    return bytes(data)


def dark_universe() -> bytes:
    data = bytearray(lit_universe())
    data[DIMMER : DIMMER + 2] = bytes([0, 0])
    data[INVERTED] = 255
    data[PAR : PAR + 3] = bytes([0, 0, 0])
    return bytes(data)


def frame(seq: int, layout: OutputLayout, data: bytes | None = None) -> Frame:
    return Frame(seq=seq, time=seq / 100, universes=(data or lit_universe(),), layout=layout)


def scheduler(layout: OutputLayout) -> tuple[OutputScheduler, Source, Recorder]:
    source = Source(frame(1, layout))
    recorder = Recorder()
    route = ScheduledRoute(id="r1", row=0, driver=recorder, description="test")
    return OutputScheduler(source, [route], FakeClock(), layout=layout), source, recorder


def notices(scheduler: OutputScheduler) -> list[str]:
    texts = []
    while not scheduler.notices.empty():
        texts.append(scheduler.notices.get().text)
    return texts


def cycles(scheduler: OutputScheduler, start: float, end: float) -> float:
    """Run cycles from ``start`` while before ``end``; return the next cycle's time."""
    now = start
    while now < end:
        scheduler.service(now)
        now += CYCLE
    return now


# ------------------------------------------------------------- dark bytes


def test_the_layout_holds_every_intensity_byte_at_intensity_zero() -> None:
    layout = rig(hold=False).layout
    dark = dict(zip(layout.darkPositions.tolist(), layout.darkValues.tolist(), strict=True))
    assert dark == {0: 0, 1: 0, 9: 255, 19: 0, 20: 0, 21: 0}


def test_layouts_are_equal_by_value() -> None:
    assert rig(hold=False).layout == rig(hold=False).layout
    assert rig(hold=False).layout != rig(hold=True).layout


# -------------------------------------------------------------- stalls


def test_hold_keeps_sending_the_last_frame() -> None:
    output, _, recorder = scheduler(rig(hold=True).layout)
    now = cycles(output, 0.0, STALL_S)
    assert notices(output) == []
    cycles(output, now, now + 2.0)
    assert notices(output) == ["engine: no new frame for 1.0 s; holding the last frame"]
    assert {data for data, _, _ in recorder.sent} == {lit_universe()}
    assert [changed for _, changed, _ in recorder.sent].count(True) == 1  # keep-alives after
    assert output.stats.framesHeld > 0
    assert output.stats.framesDarkened == 0


def test_hold_false_darkens_intensity_and_holds_the_rest() -> None:
    output, _, recorder = scheduler(rig(hold=False).layout)
    now = cycles(output, 0.0, STALL_S)
    before = len(recorder.sent)
    cycles(output, now, now + 2.0)
    assert notices(output) == ["engine: no new frame for 1.0 s; intensity off"]
    stalled = recorder.sent[before:]
    assert {data for data, _, _ in stalled} == {dark_universe()}
    assert stalled[0][1] is True  # the dark frame is a change …
    assert not any(changed for _, changed, _ in stalled[1:])  # … then keep-alives
    assert output.stats.framesDarkened == len(stalled)


def test_frames_again_after_a_stall() -> None:
    layout = rig(hold=False).layout
    output, source, recorder = scheduler(layout)
    now = cycles(output, 0.0, 1.5)
    notices(output)
    fresh = bytearray(lit_universe())
    fresh[FOCUS] = 78
    source.latest = frame(2, layout, bytes(fresh))
    output.service(now)
    assert notices(output) == ["engine: frames again"]
    assert recorder.sent[-1] == (bytes(fresh), True, now)
    cycles(output, now + CYCLE, now + 0.9)  # a fresh stall clock: no notice yet
    assert notices(output) == []


def test_a_frame_without_a_layout_is_held() -> None:
    output, source, recorder = scheduler(rig(hold=False).layout)
    source.latest = Frame(seq=1, time=0.0, universes=(lit_universe(),))
    cycles(output, 0.0, 2.0)
    assert notices(output) == ["engine: no new frame for 1.0 s; holding the last frame"]
    assert {data for data, _, _ in recorder.sent} == {lit_universe()}
