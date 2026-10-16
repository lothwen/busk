"""Install sizes and load times on the console → engine link (phase-7-plan §5.3, step 6).

A compiled show reaches the engine process as its engine view, in chunks,
with structural sharing (:mod:`busk.process.wire`). This benchmark reports,
per rig:

* the pickled size of the full compiled show (without its compile memo,
  which never travels) and of its engine view;
* the first install's chunk count, total size, and the slowest chunk's load
  time (best of 3; the target is 5 ms, so the engine's link thread never
  holds the GIL for long);
* for each edit kind of ``bench/edit_latency.py``, the bytes sent per edit
  (every install the edit's commands cause: programmer frames and shows),
  median and max over 20 edits, and the most chunks one edit sent.

Rigs: **demo** (the Phase 3 build), **reference** (``edit_latency.py``'s
§19 rig: 400 fixtures, 64 universes, 100 cue lists) and **busking**
(``tests/builders.busking_benchmark_rig``: the perf tests' 64-universe rig
with 60 playbacks). Edits run on the first two.

Run it with ``uv run python bench/transport.py``.
"""

from __future__ import annotations

import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from builders import busking_benchmark_rig, compile_doc  # noqa: E402
from busk.commands.bus import CommandBus  # noqa: E402
from busk.commands.types import Command  # noqa: E402
from busk.compiler.compile import CompiledShow, compile_show  # noqa: E402
from busk.engine.clock import MonotonicClock  # noqa: E402
from busk.engine.install import EMPTY_FRAME, Install  # noqa: E402
from busk.model.show import Show  # noqa: E402
from busk.process.wire import ShowDecoder, ShowEncoder, dumps, engine_view  # noqa: E402
from busk.session.ids import CounterIds  # noqa: E402
from busk.session.session import Session  # noqa: E402
from edit_latency import demo_show, edits, reference_show  # noqa: E402

EDITS = 20


def first_install(compiled: CompiledShow) -> dict[str, Any]:
    """The first install's chunks and the slowest one's load time (best of 3)."""
    chunks = ShowEncoder().encode(Install(compiled=compiled, remap=None, programmer=EMPTY_FRAME))
    best = [float("inf")] * len(chunks)
    for _ in range(3):
        decoder = ShowDecoder()
        for k, chunk in enumerate(chunks):
            started = time.perf_counter()
            decoder.feed(chunk)
            best[k] = min(best[k], time.perf_counter() - started)
    slowest = max(range(len(chunks)), key=best.__getitem__)
    return {
        "chunks": len(chunks),
        "bytes": sum(len(chunk) for chunk in chunks),
        "slowest": best[slowest],
        "slowestBytes": len(chunks[slowest]),
    }


class RecordingBus(CommandBus):
    """A bus that encodes every install as a link would and counts its bytes."""

    def __init__(self, compiled: CompiledShow) -> None:
        super().__init__(compiled, MonotonicClock())
        self.encoder = ShowEncoder()
        self.encoder.encode(Install(compiled=compiled, remap=None, programmer=EMPTY_FRAME))
        self.bytes = 0
        self.chunks = 0

    def install(self, item: Install) -> None:
        chunks = self.encoder.encode(item)
        self.bytes += sum(len(chunk) for chunk in chunks)
        self.chunks += len(chunks)


def edit_bytes(show: Show) -> dict[str, tuple[float, int, int]]:
    """Per edit kind: median and max bytes per edit, most chunks per edit."""
    compiled = compile_show(show)
    bus = RecordingBus(compiled)
    session = Session(show, bus, compiled=compiled, ids=CounterIds(10_000))
    result: dict[str, tuple[float, int, int]] = {}
    for kind, make in edits(session.show).items():
        sizes: list[int] = []
        chunks = 0
        for k in range(EDITS):
            before, before_chunks = bus.bytes, bus.chunks
            for command in make(k):
                outcome = session.submit(cast(Command, command))
                assert outcome.ok, (kind, command, outcome)
            sizes.append(bus.bytes - before)
            chunks = max(chunks, bus.chunks - before_chunks)
        result[kind] = (statistics.median(sizes), max(sizes), chunks)
    return result


def main() -> None:
    rigs: list[tuple[str, Show | None, CompiledShow]] = []
    for name, make in (("demo", demo_show), ("reference", reference_show)):
        show = make()
        rigs.append((name, show, compile_show(show)))
    rigs.append(("busking", None, compile_doc(busking_benchmark_rig())))
    for name, show, compiled in rigs:
        full = len(dumps(replace(compiled, memo=None)))
        view = len(dumps(engine_view(compiled)))
        first = first_install(compiled)
        print(
            f"{name}: {len(compiled.slots.slots)} slots, {len(compiled.cueLists)} cue lists; "
            f"full {full / 1e6:.2f} MB, engine view {view / 1e6:.2f} MB; first install "
            f"{first['chunks']} chunks, {first['bytes'] / 1e6:.2f} MB, slowest chunk "
            f"{first['slowest'] * 1000:.2f} ms ({first['slowestBytes'] / 1e6:.2f} MB)"
        )
        if show is None:
            continue
        for kind, (median, most, chunks) in edit_bytes(show).items():
            print(
                f"  {kind:<14} median {median / 1e3:8.1f} kB   max {most / 1e3:8.1f} kB   "
                f"≤ {chunks} chunks per edit"
            )


if __name__ == "__main__":
    main()
