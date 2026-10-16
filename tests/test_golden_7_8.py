"""The §7.8 worked example as a golden test (the Phase 2 done criterion).

Four moving heads with the Appendix A spot profile (pan 540°, tilt 270°,
RGBW, 16-bit dimmer) at 1 / 17 / 33 / 49 (``fixtures/golden_7_8.json``).
Grand master at 80 %.

=========  ====  ===================================  ================================
Playback   Seq   Content                              State at 10.5 s
=========  ====  ===================================  ================================
P1 Verse   10    int 0.40, warm {1, .8, .6}, pan 0°   active, fader 1.0
P2 Chorus  11    int 1.00, white {1, 1, 1}            active, fader 0.6
P3 Blue    12    preset Blue {0, 0, 1}, 2 s fade      0.5 s into its fade → weight 0.25
P5 Aud.    13    MH1 pan 45°                          ``followFader``, fader 0.5
=========  ====  ===================================  ================================

It is reproduced at two levels: the resolver fed the table's contributions
directly, and the engine driven by commands on a fake clock. Both check the
logical values and the DMX bytes of the §7.8 conversion table (written here
by hand from the spec, never produced by running the code), then the two
follow-ups described under the table: the release continuation and the
exclusivity variant.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray

from builders import ROOT, compile_doc, lanes_of, load_doc
from busk.compiler.compile import CompiledShow
from busk.engine.contributions import SORT_KEY, Source
from busk.engine.masters import apply_masters
from busk.engine.resolver import Resolver
from conftest import fast_convert
from harness import Harness, fader, master, release, toggle
from reference_resolver import reference_resolve

GOLDEN = ROOT / "tests" / "fixtures" / "golden_7_8.json"
NAN = math.nan
HEADS = ("fx-mh1", "fx-mh2", "fx-mh3", "fx-mh4")


@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    return load_doc(GOLDEN)


@pytest.fixture(scope="module")
def compiled(doc: dict[str, Any]) -> CompiledShow:
    return compile_doc(doc)


def expected_universe(compiled: CompiledShow, mh1_pan: tuple[int, int] = (138, 170)) -> bytes:
    """The §7.8 DMX table over the no-playback frame: per head dimmer 122/225
    and RGBW 0/0/64/191; MH 1's pan 138/170, the others' pan 0° → 128/0."""
    universe = bytearray(fast_convert(compiled, compiled.slots.defaultFrame)[0].tobytes())
    for k, start in enumerate((1, 17, 33, 49)):
        values = {
            start + 0: mh1_pan[0] if k == 0 else 128,  # pan coarse
            start + 1: mh1_pan[1] if k == 0 else 0,  # pan fine
            start + 4: 0,  # R
            start + 5: 0,  # G
            start + 6: 64,  # B
            start + 7: 191,  # W
            start + 8: 122,  # dimmer coarse
            start + 9: 225,  # dimmer fine
        }
        for channel, value in values.items():
            universe[channel - 1] = value
    return bytes(universe)


def check_logical(compiled: CompiledShow, logical: NDArray[np.float64], intensity: float) -> None:
    for head in HEADS:
        assert lanes_of(compiled, logical, head, "intensity") == pytest.approx([intensity])
        assert lanes_of(compiled, logical, head, "color") == pytest.approx(
            [0.75, 0.75, 1.0, NAN], nan_ok=True
        )
        assert lanes_of(compiled, logical, head, "pan") == pytest.approx(
            [22.5 if head == "fx-mh1" else 0.0]
        )


# ------------------------------------------------------- resolver level


def test_resolver_fed_the_table(compiled: CompiledShow) -> None:
    def source(playback: str, seq: int, htp: float, scale: float, ltp: float) -> Source:
        made = Source.of_cue(playback, 50, compiled.playbacks[playback].cueList.first)
        made.seq, made.htpWeight, made.intensityScale, made.ltpWeight = seq, htp, scale, ltp
        return made

    sources = sorted(
        [
            source("pb-verse", 10, htp=1.0, scale=1.0, ltp=1.0),
            source(
                "pb-chorus", 11, htp=1.0, scale=0.6, ltp=1.0
            ),  # threshold: LTP ignores the fader
            source("pb-blue", 12, htp=0.25, scale=0.0, ltp=0.25),  # 0.5 s into a 2 s linear fade
            source("pb-aud", 13, htp=1.0, scale=0.5, ltp=0.5),  # followFader at 0.5
        ],
        key=SORT_KEY,
    )
    frame = np.empty(compiled.slots.laneCount)
    Resolver(compiled.slots).resolve(sources, compiled.slots.defaultFrame, frame)
    np.testing.assert_allclose(
        frame,
        reference_resolve(compiled.slots, sources, compiled.slots.defaultFrame),
        rtol=0,
        atol=1e-12,
        equal_nan=True,
    )
    # MH1 intensity: P = 1, bandValue = max(0.40 · 1.0, 1.00 · 0.6) = 0.60.
    check_logical(compiled, frame, intensity=0.60)

    # Masters: intensity 0.60 × GM 0.80 = 0.48.
    apply_masters(frame, compiled.slots.intensityLanes, 0.8, blackout=False)
    check_logical(compiled, frame, intensity=0.48)
    assert fast_convert(compiled, frame)[0].tobytes() == expected_universe(compiled)


# --------------------------------------------------------- engine level

SCRIPT = [
    (0.0, master("m-gm", 0.8)),
    (0.0, fader("pb-verse", 1.0)),  # autoStart, above the threshold: LTP latches
    (0.0, fader("pb-chorus", 0.6)),
    (10.0, toggle("pb-blue")),  # 2 s linear fade from here
    (10.1, fader("pb-aud", 0.5)),  # followFader: LTP weight = fader level
]


def test_engine_driven_by_commands(compiled: CompiledShow) -> None:
    at = Harness(compiled).run(SCRIPT, ticks=[2.5, 10.5])[10.5]
    check_logical(compiled, at.logical, intensity=0.48)
    assert at.universe == expected_universe(compiled)
    # MH1: dimmer 122/225, pan 138/170, R G B W 0/0/64/191 (§7.8 conversion table).
    assert at.channels(9, 10, 1, 2, 5, 6, 7, 8) == (122, 225, 138, 170, 0, 0, 64, 191)
    assert at.snapshot is not None
    states = {status.id: (status.state, status.faderLevel) for status in at.snapshot.playbacks}
    assert states == {
        "pb-verse": ("active", 1.0),
        "pb-chorus": ("active", 0.6),
        "pb-blue": ("active", 0.0),
        "pb-red": ("idle", 0.0),
        "pb-aud": ("active", 0.5),
    }
    assert at.snapshot.grandMaster == 0.8


def test_release_continuation(compiled: CompiledShow) -> None:
    """Release P3 at 10.5 with its 1 s release time: weight 0.25 → 0, and the
    colour glides back to white (P2)."""
    run = Harness(compiled).run([*SCRIPT, (10.5, release("pb-blue"))], ticks=[11.0, 11.5])
    half = run[11.0]  # weight 0.125: colour {.875, .875, 1}
    assert lanes_of(compiled, half.logical, "fx-mh1", "color") == pytest.approx(
        [0.875, 0.875, 1.0, NAN], nan_ok=True
    )
    # W = min = 0.875 → 223; B = 1 − 0.875 = 0.125 → 32; R = G = 0.
    assert half.channels(5, 6, 7, 8) == (0, 0, 32, 223)
    done = run[11.5]
    assert lanes_of(compiled, done.logical, "fx-mh1", "color") == pytest.approx(
        [1.0, 1.0, 1.0, NAN], nan_ok=True
    )
    assert done.channels(5, 6, 7, 8) == (0, 0, 0, 255)  # white from the white emitter
    assert done.snapshot is not None
    assert {s.id: s.state for s in done.snapshot.playbacks}["pb-blue"] == "idle"


def test_exclusivity_variant(compiled: CompiledShow) -> None:
    """Red is up, Blue is triggered (releasing Red), Blue is released: the look
    falls back to white, not to the stale Red."""
    script = [
        *SCRIPT[:3],
        (1.0, toggle("pb-red")),
        (5.0, toggle("pb-blue")),
        (8.0, release("pb-blue")),
    ]
    run = Harness(compiled).run(script, ticks=[4.0, 5.5, 7.5, 9.5])
    assert lanes_of(compiled, run[4.0].logical, "fx-mh1", "color")[:3] == [1.0, 0.0, 0.0]
    assert run[5.5].snapshot is not None
    states = {s.id: s.state for s in run[5.5].snapshot.playbacks}
    assert (states["pb-red"], states["pb-blue"]) == ("releasing", "active")
    assert lanes_of(compiled, run[7.5].logical, "fx-mh1", "color")[:3] == [0.0, 0.0, 1.0]
    assert lanes_of(compiled, run[9.5].logical, "fx-mh1", "color")[:3] == [1.0, 1.0, 1.0]


def test_without_exclusivity_the_stale_red_reappears(doc: dict[str, Any]) -> None:
    """The problem §5.12 describes, for contrast: plain LTP brings Red back."""
    plain = {**doc, "playbacks": [{**pb} for pb in doc["playbacks"]]}
    for playback in plain["playbacks"]:
        playback.pop("exclusivity", None)
    compiled = compile_doc(plain)
    script = [
        *SCRIPT[:3],
        (1.0, toggle("pb-red")),
        (5.0, toggle("pb-blue")),
        (8.0, release("pb-blue")),
    ]
    run = Harness(compiled).run(script, ticks=[9.5])
    assert lanes_of(compiled, run[9.5].logical, "fx-mh1", "color")[:3] == [1.0, 0.0, 0.0]
