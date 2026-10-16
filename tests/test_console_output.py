"""Console output (the ``--console`` sink): print-on-change and the golden line format."""

from __future__ import annotations

import io

from busk.compiler.compile import CompiledUniverse
from busk.engine.loop import Frame
from busk.model.common import UniverseId
from busk.output.console import ConsoleOutput

STAGE = CompiledUniverse(id=UniverseId("u1"), number=1, name="Stage")
SIDE = CompiledUniverse(id=UniverseId("u2"), number=2, name="Side")


def image(**channels: int) -> bytes:
    """A 512-byte universe; ``image(ch101=255)`` sets channel 101 (1-based)."""
    data = bytearray(512)
    for name, value in channels.items():
        data[int(name.removeprefix("ch")) - 1] = value
    return bytes(data)


class Source:
    """Stands in for the engine: whatever frame the test puts in ``latest``."""

    def __init__(self) -> None:
        self.latest: Frame | None = None


def console(*universes: CompiledUniverse) -> tuple[Source, ConsoleOutput, io.StringIO]:
    source, stream = Source(), io.StringIO()
    return source, ConsoleOutput(source, universes, stream), stream


def test_golden_line_format() -> None:
    source, output, stream = console(STAGE)
    source.latest = Frame(seq=1, time=0.0, universes=(image(ch101=255, ch102=255),))
    output.service(0.0)
    assert stream.getvalue() == "[frame 1] U1 Stage: 101=255 102=255\n"


def test_all_zero_universe_prints_all_0() -> None:
    source, output, stream = console(SIDE)
    source.latest = Frame(seq=3, time=0.02, universes=(image(),))
    output.service(0.02)
    assert stream.getvalue() == "[frame 3] U2 Side: all 0\n"


def test_channel_512_and_channel_1() -> None:
    source, output, stream = console(STAGE)
    source.latest = Frame(seq=1, time=0.0, universes=(image(ch1=1, ch512=7),))
    output.service(0.0)
    assert stream.getvalue() == "[frame 1] U1 Stage: 1=1 512=7\n"


def test_nothing_printed_before_the_first_frame() -> None:
    _, output, stream = console(STAGE)
    output.service(0.0)
    assert stream.getvalue() == ""


def test_a_static_show_prints_exactly_once() -> None:
    source, output, stream = console(STAGE)
    for seq in range(1, 50):  # a new frame object each tick, same bytes
        source.latest = Frame(seq=seq, time=seq / 100, universes=(image(ch1=128),))
        output.service(seq / 100)
        output.service(seq / 100)  # polling again without a new frame
    assert stream.getvalue() == "[frame 1] U1 Stage: 1=128\n"


def test_only_changed_universes_print_again() -> None:
    source, output, stream = console(STAGE, SIDE)
    source.latest = Frame(seq=1, time=0.0, universes=(image(ch1=10), image()))
    output.service(0.0)
    source.latest = Frame(seq=2, time=0.01, universes=(image(ch1=10), image(ch5=5)))
    output.service(0.01)
    source.latest = Frame(seq=3, time=0.02, universes=(image(ch1=20), image(ch5=5)))
    output.service(0.02)
    assert stream.getvalue().splitlines() == [
        "[frame 1] U1 Stage: 1=10",
        "[frame 1] U2 Side: all 0",
        "[frame 2] U2 Side: 5=5",
        "[frame 3] U1 Stage: 1=20",
    ]
