"""Builders for synthetic shows: profiles, the feature-matrix show, the benchmark
rig, and copies of shows with their output routes made safe for tests.

Everything here returns plain JSON-shaped dicts (``Doc``), the same shape as a
show file, so tests can mutate them before validating and compiling with
:func:`compile_doc`.

The **feature-matrix show** has one fixture per conversion edge case. Its
patch is listed in :data:`MATRIX_PATCH` so tests can name the DMX channels
they expect by hand.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from busk.compiler.compile import CompiledShow, compile_show
from busk.compiler.lanes import encode_value
from busk.model.common import FixtureId, TargetRef
from busk.model.show import Show
from busk.model.validate import Issue, has_errors, validate_show
from busk.session.library import builtin_effects
from busk.session.state import ShowState

type Doc = dict[str, Any]

ROOT = Path(__file__).parent.parent
APPENDIX_A = Path(__file__).parent / "fixtures" / "appendix_a.json"
DEMO = ROOT / "examples" / "real-fixtures.json"
DEMO_VALUES = Path(__file__).parent / "fixtures" / "phase1-values.json"

# ----------------------------------------------------------- capabilities


def rng(lo: int, hi: int, v0: float, v1: float) -> Doc:
    """A range capability: DMX ``lo..hi`` ↔ logical ``v0..v1``."""
    return {"kind": "range", "dmx": [lo, hi], "value": [v0, v1]}


def slot(lo: int, hi: int, slot_id: str, wheel: str | None = None) -> Doc:
    capability: Doc = {"kind": "slot", "dmx": [lo, hi], "slot": slot_id}
    if wheel is not None:
        capability["wheel"] = wheel
    return capability


def fn(lo: int, hi: int, name: str, param: tuple[str, float, float] | None = None) -> Doc:
    """A function capability, optionally with a ``(attribute, v0, v1)`` parameter."""
    capability: Doc = {"kind": "function", "dmx": [lo, hi], "fn": name}
    if param is not None:
        capability["param"] = {"attribute": param[0], "value": [param[1], param[2]]}
    return capability


def channel(
    offset: int,
    attribute: str,
    *capabilities: Doc,
    element: int = 0,
    nbytes: int = 1,
    default: int = 0,
    component: str | None = None,
    fine: list[int] | None = None,
    invert: bool | None = None,
) -> Doc:
    """A channel; without capabilities it gets one full-range ``0..1`` map."""
    doc: Doc = {"offset": offset, "element": element, "attribute": attribute, "bytes": nbytes}
    if component is not None:
        doc["component"] = component
    if fine is not None:
        doc["fineOffsets"] = fine
    if invert is not None:
        doc["invert"] = invert
    doc["defaultDmx"] = default
    doc["capabilities"] = list(capabilities) or [rng(0, 256**nbytes - 1, 0, 1)]
    return doc


def color(offset: int, component: str, element: int = 0) -> Doc:
    return channel(offset, "color", component=component, element=element)


def mode(
    channels: list[Doc],
    *,
    mode_id: str = "m",
    elements: int = 1,
    strategy: str = "dimmerChannel",
    curve: str | list[float] | None = None,
    footprint: int | None = None,
) -> Doc:
    """A mode; the footprint defaults to the highest byte offset used + 1."""
    used = [
        offset
        for c in channels
        for offset in [
            c["offset"],
            *c.get("fineOffsets", range(c["offset"] + 1, c["offset"] + c["bytes"])),
        ]
    ]
    doc: Doc = {
        "id": mode_id,
        "name": mode_id,
        "footprint": footprint or max(used) + 1,
        "elements": [{"index": i, "name": f"E{i}"} for i in range(elements)],
        "intensityStrategy": strategy,
        "channels": channels,
    }
    if curve is not None:
        doc["dimmerCurve"] = curve
    return doc


def profile(
    profile_id: str,
    *modes: Doc,
    wheels: list[Doc] | None = None,
    emitters: list[Doc] | None = None,
    physical: Doc | None = None,
) -> Doc:
    doc: Doc = {
        "id": profile_id,
        "name": profile_id,
        "manufacturer": "Test",
        "model": profile_id,
        "revision": "1",
        "source": "user",
        "physical": physical or {},
        "wheels": wheels or [],
        "modes": list(modes),
    }
    if emitters is not None:
        doc["emitters"] = emitters
    return doc


def fixture(
    fixture_id: str,
    number: int,
    profile_id: str,
    address: int | None,
    *,
    mode_id: str = "m",
    universe: str = "u1",
    **orientation: Any,
) -> Doc:
    """A fixture patched at ``universe``/``address`` (``None`` = unpatched)."""
    return {
        "id": fixture_id,
        "number": number,
        "name": fixture_id,
        "profileId": profile_id,
        "profileRevision": "1",
        "modeId": mode_id,
        "patch": None if address is None else {"universeId": universe, "address": address},
        "orientation": {
            "invertPan": False,
            "invertTilt": False,
            "swapPanTilt": False,
            "panOffset": 0,
            "tiltOffset": 0,
            **orientation,
        },
    }


def show(profiles: list[Doc], fixtures: list[Doc], universes: int = 1) -> Doc:
    """A minimal valid show; universes ``u1``, ``u2``… are numbered 1, 2…"""
    return {
        "schemaVersion": 1,
        "meta": {"id": "t", "title": "t", "created": "", "modified": "", "app": "test"},
        "profiles": profiles,
        "universes": [
            {"id": f"u{n}", "name": f"U{n}", "number": n} for n in range(1, universes + 1)
        ],
        "fixtures": fixtures,
        "groups": [],
        "presets": [],
        "effects": [],
        "cueLists": [],
        "playbacks": [],
        "pages": [],
        "masters": [],
        "surfaces": [],
        "bindings": [],
        "output": {
            "engineHz": 100,
            "sacnSourceName": "t",
            "sacnCid": "00000000-0000-0000-0000-000000000000",
            "holdLastFrameOnEngineStall": True,
            "routes": [],
        },
        "park": [],
    }


# ----------------------------------------------------------- output routes


def offline(doc: Doc) -> Doc:
    """A copy of ``doc`` with every output route disabled, so ``busk run``
    sends nothing (add ``--console`` to see the frames)."""
    copied = copy.deepcopy(doc)
    for route in copied["output"]["routes"]:
        route["enabled"] = False
    return copied


def localhost_route(doc: Doc) -> Doc:
    """A copy of ``doc`` whose sACN routes send unicast to 127.0.0.1.

    The schema has no port field: the ``receiver`` fixture patches
    ``SACN_PORT``, so the packets reach it.
    """
    copied = copy.deepcopy(doc)
    for route in copied["output"]["routes"]:
        if route["protocol"] == "sacn":
            route["destination"] = {"kind": "unicast", "host": "127.0.0.1"}
    return copied


# --------------------------------------------------------------- compiling


def load_doc(path: Path) -> Doc:
    doc: Doc = json.loads(path.read_text(encoding="utf-8"))
    return doc


def issues_of(doc: Doc) -> list[Issue]:
    _, issues = validate_show(json.dumps(doc))
    return issues


def compile_doc(doc: Doc) -> CompiledShow:
    """Validate ``doc`` (warnings allowed, errors not) and compile it."""
    shown, issues = validate_show(json.dumps(doc))
    assert shown is not None, issues
    assert not has_errors(issues), issues
    return compile_show(shown)


def show_of(doc: Doc) -> Show:
    """Validate ``doc`` (warnings allowed, errors not) and return the validated show."""
    shown, issues = validate_show(json.dumps(doc))
    assert shown is not None, issues
    assert not has_errors(issues), issues
    return shown


def state_of(doc: Doc) -> ShowState:
    """A committed show state (Phase 3): ``doc`` validated and compiled."""
    shown = show_of(doc)
    return ShowState(show=shown, compiled=compile_show(shown))


type ValueKey = tuple[str, int, str] | tuple[str, str]
"""``(fixtureId, element, attribute)``, or ``(fixtureId, attribute)`` for element 0."""


def frame(
    compiled: CompiledShow, values: Mapping[ValueKey, Any] | None = None
) -> NDArray[np.float64]:
    """The default frame with ``values`` encoded over it (a writable copy)."""
    result = compiled.slots.defaultFrame.copy()
    for key, value in (values or {}).items():
        fixture_id, element, attribute = key if len(key) == 3 else (key[0], 0, key[1])
        target = TargetRef(fixtureId=FixtureId(fixture_id), element=element)
        found = compiled.slots.find(target, attribute)
        assert found is not None, f"no slot {key}"
        result[found.lanes] = encode_value(found, value)
    return result


def random_frame(compiled: CompiledShow, generator: np.random.Generator) -> NDArray[np.float64]:
    """A random frame for a rig too big for hypothesis: same kinds of values,
    drawn with numpy."""
    logical = np.empty(compiled.slots.laneCount)
    for slot in compiled.slots.slots:
        lanes = logical[slot.lanes]
        if slot.attribute.kind == "scalar":
            lanes[:] = generator.choice(
                [generator.uniform(-0.25, 1.25), generator.uniform(-600, 600)]
            )
        elif slot.attribute.kind == "discrete":
            lanes[:] = generator.uniform(-2, len(slot.options) + 1)
        else:
            lanes[:] = generator.uniform(-0.25, 1.25, slot.laneCount)
            lanes[3:][generator.random(slot.laneCount - 3) < 0.5] = math.nan
    return logical


def nonzero(universe: NDArray[np.uint8]) -> dict[int, int]:
    """Non-zero channels of a universe image, 1-based."""
    return {int(index) + 1: int(universe[index]) for index in np.flatnonzero(universe)}


def channels_at(universe: NDArray[np.uint8], numbers: Iterable[int]) -> dict[int, int]:
    """The values of the given 1-based channels."""
    return {number: int(universe[number - 1]) for number in numbers}


# ------------------------------------------------------ feature-matrix show

MULTI_SEGMENTS = [rng(0, 9, 0, 0), rng(10, 100, 10, 100), rng(101, 200, -10, -100)]
"""``gobo1Rotation``: a zero-span stop (centre 4), a CW and a CCW range, with
gaps on either side of the stop."""

SHUTTER = [
    fn(0, 7, "closed"),
    fn(8, 15, "open"),
    fn(16, 131, "strobe", ("strobeRate", 1, 20)),
    fn(140, 149, "pulse", ("strobeRate", 5, 5)),  # zero-span parameter
    fn(150, 159, "random"),
    fn(160, 255, "macro"),  # never output
]

TABLE_CURVE = [0.0, 0.2, 0.6, 1.0]

MATRIX_PATCH: Mapping[str, tuple[str, int]] = {
    # fixture id: (universe, first channel)
    "fx-dim16": ("u1", 1),  # 16-bit dimmer: 1 coarse, 2 fine
    "fx-diminv": ("u1", 3),  # inverted 8-bit dimmer
    "fx-square": ("u1", 4),  # dimmer curves, one fixture each
    "fx-invsquare": ("u1", 5),
    "fx-scurve": ("u1", 6),
    "fx-table": ("u1", 7),
    "fx-ultra": ("u1", 8),  # 24-bit pan: 8 coarse, 12 fine, 10 ultra; dimmer 9
    "fx-half": ("u1", 13),  # dimmer 13; focus on dmx [0, 253] at 14
    "fx-multi": ("u1", 15),  # dimmer 15; multi-segment gobo rotation 16
    "fx-rgbw": ("u1", 17),  # dimmer 17; R G B W 18–21
    "fx-rgbawuv": ("u1", 22),  # virtual, square curve: R G B W A UV lime 22–28
    "fx-shutter": ("u1", 29),  # dimmer 29; shutter 30
    "fx-swap": ("u1", 31),  # dimmer 31; pan 32/33; tilt 34/35; swapped, offsets, invertTilt
    "fx-offset": ("u1", 36),  # same mover: panOffset 45, invertPan
    "fx-early": ("u1", 41),  # dimmer 41, focus 42, iris 43 (lost to fx-late)
    "fx-late": ("u1", 43),  # dimmer 43, focus 44, iris 45
    "fx-control": ("u1", 46),  # dimmer 46; control channel at 47 (defaultDmx 77)
    "fx-par": ("u1", 48),  # Appendix-A-style virtual RGB par, linear: 48–50
    "fx-cmy": ("u2", 1),  # second universe: dimmer 1; C M Y 2–4
}


def feature_matrix() -> Doc:
    """One fixture per conversion edge case (see :data:`MATRIX_PATCH`).

    ``fx-early`` and ``fx-late`` overlap on purpose (a validation warning);
    ``fx-unpatched`` has slots but no channels.
    """
    dimmer = channel(0, "intensity")
    mover = [
        dimmer,
        channel(1, "pan", rng(0, 65535, -270, 270), nbytes=2),
        channel(3, "tilt", rng(0, 65535, -135, 135), nbytes=2),
    ]
    profiles = [
        profile("p-dim16", mode([channel(0, "intensity", nbytes=2)])),
        profile("p-diminv", mode([channel(0, "intensity", invert=True)])),
        profile(
            "p-curves",
            mode([dimmer], mode_id="square", curve="square"),
            mode([dimmer], mode_id="invSquare", curve="invSquare"),
            mode([dimmer], mode_id="sCurve", curve="sCurve"),
            mode([dimmer], mode_id="table", curve=TABLE_CURVE),
        ),
        profile(
            "p-ultra",
            mode(
                [
                    channel(0, "pan", rng(0, 16777215, -270, 270), nbytes=3, fine=[4, 2]),
                    channel(1, "intensity"),
                ]
            ),
        ),
        profile("p-half", mode([dimmer, channel(1, "focus", rng(0, 253, 0, 1))])),
        profile("p-multi", mode([dimmer, channel(1, "gobo1Rotation", *MULTI_SEGMENTS)])),
        profile(
            "p-rgbw",
            mode(
                [
                    dimmer,
                    *(color(k + 1, c) for k, c in enumerate(["red", "green", "blue", "white"])),
                ]
            ),
        ),
        profile(
            "p-rgbawuv",
            mode(
                [
                    color(k, c)
                    for k, c in enumerate(["red", "green", "blue", "white", "amber", "uv", "lime"])
                ],
                strategy="virtual",
                curve="square",
            ),
        ),
        profile("p-shutter", mode([dimmer, channel(1, "shutter", *SHUTTER)])),
        profile("p-mover", mode(mover)),
        profile("p-pair", mode([dimmer, channel(1, "focus"), channel(2, "iris")])),
        profile(
            "p-control",
            mode([dimmer, channel(1, "control", fn(0, 255, "none"), default=77)]),
        ),
        profile(
            "p-par",
            mode([color(k, c) for k, c in enumerate(["red", "green", "blue"])], strategy="virtual"),
        ),
        profile(
            "p-cmy",
            mode(
                [
                    dimmer,
                    *(
                        color(k + 1, c)
                        for k, c in enumerate(["cyanFlag", "magentaFlag", "yellowFlag"])
                    ),
                ]
            ),
        ),
    ]
    profile_of = {
        "fx-dim16": "p-dim16",
        "fx-diminv": "p-diminv",
        "fx-square": "p-curves",
        "fx-invsquare": "p-curves",
        "fx-scurve": "p-curves",
        "fx-table": "p-curves",
        "fx-ultra": "p-ultra",
        "fx-half": "p-half",
        "fx-multi": "p-multi",
        "fx-rgbw": "p-rgbw",
        "fx-rgbawuv": "p-rgbawuv",
        "fx-shutter": "p-shutter",
        "fx-swap": "p-mover",
        "fx-offset": "p-mover",
        "fx-early": "p-pair",
        "fx-late": "p-pair",
        "fx-control": "p-control",
        "fx-par": "p-par",
        "fx-cmy": "p-cmy",
    }
    modes_of = {
        "fx-square": "square",
        "fx-invsquare": "invSquare",
        "fx-scurve": "sCurve",
        "fx-table": "table",
    }
    orientations: dict[str, Doc] = {
        "fx-swap": {"swapPanTilt": True, "panOffset": 10, "tiltOffset": -5, "invertTilt": True},
        "fx-offset": {"panOffset": 45, "invertPan": True},
    }
    fixtures = [
        fixture(
            fixture_id,
            number,
            profile_of[fixture_id],
            address,
            universe=universe,
            mode_id=modes_of.get(fixture_id, "m"),
            **orientations.get(fixture_id, {}),
        )
        for number, (fixture_id, (universe, address)) in enumerate(MATRIX_PATCH.items(), start=1)
    ]
    fixtures.append(fixture("fx-unpatched", 99, "p-dim16", None))
    # Channel dicts are shared between modes above; copy so tests can mutate freely.
    return copy.deepcopy(show(profiles, fixtures, universes=2))


# ------------------------------------------------------------ benchmark rig


def macro_rig() -> Doc:
    """Colour macros (color-macros-plan step 2): two RGB pars with a macro, a
    rate and a colour effect channel (fixtures 1 and 2, at 1 and 11), and a
    macro-only fixture whose default selects a black preset (fixture 3, at 21)."""

    def wheel(*names: str) -> Doc:
        colours = {"black": (0, 0, 0), "red": (1, 0, 0), "green": (0, 1, 0), "white": (1, 1, 1)}
        slots = [
            {"id": n, "name": n.title(), "color": dict(zip("rgb", colours[n], strict=True))}
            for n in names
        ]
        return {"id": "macro1", "kind": "color", "slots": slots}

    speed = ("colorMacroRate", 0.0, 1.0)
    macro = channel(
        4,
        "colorMacro",
        fn(0, 9, "off"),
        slot(10, 19, "red", "macro1"),
        slot(20, 29, "green", "macro1"),
        slot(30, 39, "white", "macro1"),
        fn(40, 199, "colourChange", speed),
        fn(200, 255, "soundActive"),
    )
    macro["highlightDmx"] = 35
    effect = channel(
        6, "colorEffect", fn(0, 9, "off"), fn(10, 127, "colorJump", speed),
        fn(128, 255, "colorFade", speed),
    )  # fmt: skip
    par = mode([
        channel(0, "intensity"), color(1, "red"), color(2, "green"), color(3, "blue"),
        macro, channel(5, "colorMacroRate"), effect,
    ])  # fmt: skip
    only = mode([
        channel(0, "intensity"),
        channel(1, "colorMacro", slot(0, 5, "black", "macro1"), slot(6, 13, "red", "macro1"),
                slot(14, 21, "white", "macro1"), fn(22, 255, "colourChange", speed)),
    ])  # fmt: skip
    return show(
        [
            profile("macro-par", par, wheels=[wheel("red", "green", "white")]),
            profile("macro-only", only, wheels=[wheel("black", "red", "white")]),
        ],
        [
            fixture("a", 1, "macro-par", 1),
            fixture("b", 2, "macro-par", 11),
            fixture("c", 3, "macro-only", 21),
        ],
    )


def benchmark_rig(universes: int = 64) -> Doc:
    """The §19 reference rig: per universe, 4 Appendix A spots, 6 MH-X25,
    10 ML-56 and 9 COLORband PiX (500 channels). Across 64 universes that is
    about 20 600 slots and 29 000 slot-driven channels."""
    appendix = load_doc(APPENDIX_A)
    demo = load_doc(DEMO)
    spot = appendix["profiles"][0]
    mhx25, ml56, pix = demo["profiles"]
    rig = show([spot, mhx25, ml56, pix], [], universes=universes)
    number = 0
    for u in range(1, universes + 1):
        address = 1
        for profile_doc, count in ((spot, 4), (mhx25, 6), (ml56, 10), (pix, 9)):
            mode_doc = profile_doc["modes"][0]
            for _ in range(count):
                number += 1
                rig["fixtures"].append(
                    fixture(
                        f"fx-{number}",
                        number,
                        profile_doc["id"],
                        address,
                        mode_id=mode_doc["id"],
                        universe=f"u{u}",
                    )
                )
                address += mode_doc["footprint"]
    return copy.deepcopy(rig)


# --------------------------------------------------------- busking content
# Groups, presets, cues, cue lists and playbacks (Phase 2), as JSON-shaped dicts.


def target_ref(fixture_id: str, element: int = 0) -> Doc:
    return {"fixtureId": fixture_id, "element": element}


def group(group_id: str, number: int, *fixture_ids: str) -> Doc:
    """A group of element 0 of each fixture, in the given order."""
    return {
        "id": group_id,
        "number": number,
        "name": group_id,
        "members": [target_ref(fixture_id) for fixture_id in fixture_ids],
    }


def in_group(group_id: str) -> Doc:
    """A ``TargetSpec`` that follows a group."""
    return {"kind": "group", "groupId": group_id}


def targets(*fixture_ids: str) -> Doc:
    """A fixed ``TargetSpec`` of element 0 of each fixture."""
    return {"kind": "targets", "refs": [target_ref(fixture_id) for fixture_id in fixture_ids]}


def literal(value: Any) -> Doc:
    return {"kind": "literal", "value": value}


def preset_source(preset_id: str) -> Doc:
    return {"kind": "preset", "presetId": preset_id}


def spread(start: Any, end: Any, curve: str | None = None) -> Doc:
    source: Doc = {"kind": "spread", "from": start, "to": end}
    if curve is not None:
        source["curve"] = curve
    return source


def per_target(values: Mapping[str, Any]) -> Doc:
    """A ``perTarget`` source keyed by ``"fixtureId:element"``."""
    return {"kind": "perTarget", "values": dict(values)}


def entry(spec: Doc, attribute: str, source: Doc) -> Doc:
    return {"targets": spec, "attribute": attribute, "value": source}


def rgb(r: float, g: float, b: float, **extras: float) -> Doc:
    return {"r": r, "g": g, "b": b, **extras}


def cue(
    cue_id: str,
    *entries: Doc,
    number: str = "1",
    fade_in: float = 0.0,
    delay_in: float = 0.0,
    fade_out: float = 0.0,
    delay_out: float = 0.0,
    curve: str = "linear",
) -> Doc:
    return {
        "id": cue_id,
        "number": number,
        "name": cue_id,
        "entries": list(entries),
        "effects": [],
        "timing": {
            "fadeIn": fade_in,
            "fadeOut": fade_out,
            "delayIn": delay_in,
            "delayOut": delay_out,
            "curve": curve,
        },
        "trigger": {"kind": "go"},
    }


def cue_list(list_id: str, number: int, *cues: Doc, release_at_end: bool = False) -> Doc:
    return {
        "id": list_id,
        "number": number,
        "name": list_id,
        "mode": "sequence",
        "tracking": False,
        "wrap": False,
        "releaseAtEnd": release_at_end,
        "cues": list(cues),
    }


def playback(
    playback_id: str,
    number: int,
    list_id: str,
    *,
    priority: int = 50,
    fader: str = "master",
    buttons: Iterable[str] = ("toggle", "flash", "release"),
    mode: str = "threshold",
    threshold: float = 0.02,
    auto_start: bool = True,
    auto_release: bool = True,
    flash_level: float = 1.0,
    include_ltp: bool = False,
    boost: int | None = None,
    exclusivity: str | None = None,
    release_time: float = 1.0,
) -> Doc:
    flash: Doc = {"level": flash_level, "includeLtp": include_ltp}
    if boost is not None:
        flash["priorityBoost"] = boost
    doc: Doc = {
        "id": playback_id,
        "number": number,
        "name": playback_id,
        "cueListId": list_id,
        "priority": priority,
        "fader": fader,
        "buttons": list(buttons),
        "ltpFaderMode": mode,
        "ltpThreshold": threshold,
        "autoStart": auto_start,
        "autoRelease": auto_release,
        "flash": flash,
        "protectFromSwop": False,
        "releaseTime": release_time,
    }
    if exclusivity is not None:
        doc["exclusivity"] = exclusivity
    return doc


def look(
    doc: Doc,
    playback_id: str,
    number: int,
    *entries: Doc,
    fade_in: float = 0.0,
    delay_in: float = 0.0,
    **options: Any,
) -> Doc:
    """Add a single-cue cue list ``cl-<playback_id>`` and a playback running it
    to ``doc``; ``options`` go to :func:`playback`. Returns ``doc``."""
    list_id = f"cl-{playback_id}"
    doc["cueLists"].append(
        cue_list(
            list_id,
            number,
            cue(f"c-{playback_id}", *entries, fade_in=fade_in, delay_in=delay_in),
            release_at_end=options.pop("release_at_end", False),
        )
    )
    doc["playbacks"].append(playback(playback_id, number, list_id, **options))
    return doc


def preset_value(attribute: str, value: Any, scope: str | None = None) -> Doc:
    """A preset value; ``scope`` is ``None`` (global), ``"profile:<id>"`` or a
    target key such as ``"fx-mh1:0"``."""
    if scope is None:
        scope_doc: Doc = {"kind": "global"}
    elif scope.startswith("profile:"):
        scope_doc = {"kind": "profile", "profileId": scope.removeprefix("profile:")}
    else:
        fixture_id, _, element = scope.rpartition(":")
        scope_doc = {"kind": "target", "target": target_ref(fixture_id, int(element))}
    return {"scope": scope_doc, "attribute": attribute, "value": value}


def preset(preset_id: str, number: int, pool: str, *values: Doc) -> Doc:
    return {
        "id": preset_id,
        "number": number,
        "name": preset_id,
        "pool": pool,
        "values": list(values),
    }


def grand_master(master_id: str = "m-gm", initial: float | None = None) -> Doc:
    master: Doc = {"id": master_id, "kind": "grand", "name": master_id}
    if initial is not None:
        master["initialLevel"] = initial
    return master


def speed_master(
    master_id: str = "m-speed",
    bpm: float = 120.0,
    steps: Sequence[float] = (0.25, 0.5, 1.0, 2.0, 4.0),
    *,
    tap: bool = True,
    initial: float | None = None,
) -> Doc:
    master: Doc = {
        "id": master_id,
        "kind": "speed",
        "name": master_id,
        "defaultBpm": bpm,
        "tap": tap,
        "multiplierSteps": list(steps),
    }
    if initial is not None:
        master["initialLevel"] = initial
    return master


def size_master(master_id: str = "m-size", initial: float | None = None) -> Doc:
    master: Doc = {"id": master_id, "kind": "size", "name": master_id}
    if initial is not None:
        master["initialLevel"] = initial
    return master


def effect_layer(attribute: str, kind: str, mode: str = "absolute", **fields: Any) -> Doc:
    """A scalar effect layer: ``kind`` is the waveform; ``fields`` go on the layer."""
    return {
        "attribute": attribute,
        "waveform": {"kind": kind},
        "phaseOffset": 0,
        "mode": mode,
        **fields,
    }


def effect_template(template_id: str, *layers: Doc) -> Doc:
    return {"id": template_id, "name": template_id, "layers": list(layers)}


def effect_instance(instance_id: str, template_id: str, spec: Doc, **fields: Any) -> Doc:
    """An effect instance on ``spec`` at 1 Hz, forward, full size, every
    member in phase; ``fields`` override or add fields."""
    doc: Doc = {
        "id": instance_id,
        "templateId": template_id,
        "targets": spec,
        "rate": {"kind": "hz", "value": 1.0},
        "direction": "forward",
        "size": 1.0,
        "phase": {"start": 0, "end": 0},
        "groups": 1,
        "blocks": 1,
        "wings": 1,
    }
    doc.update(fields)
    return doc


def page(page_id: str, number: int, *slots: str | None) -> Doc:
    return {"id": page_id, "number": number, "name": page_id, "slots": list(slots)}


def appendix_profiles() -> tuple[Doc, Doc]:
    """Appendix A's profiles: the generic 16-channel spot and the virtual RGB par."""
    spot, par = load_doc(APPENDIX_A)["profiles"]
    return spot, par


def busk_rig(spots: int = 4, pars: int = 0) -> Doc:
    """A show of Appendix A spots ``fx-mh1…`` (16 channels apart from 1) and
    RGB pars ``fx-par1…`` (after the spots), with no busking content yet."""
    spot, par = appendix_profiles()
    fixtures = [
        fixture(f"fx-mh{k}", 100 + k, "prof-mh", 1 + 16 * (k - 1), mode_id="mode-16")
        for k in range(1, spots + 1)
    ]
    fixtures += [
        fixture(f"fx-par{k}", 200 + k, "prof-par", 1 + 16 * spots + 3 * (k - 1), mode_id="mode-3")
        for k in range(1, pars + 1)
    ]
    return copy.deepcopy(show([spot, par], fixtures))


def slot_of(compiled: CompiledShow, fixture_id: str, attribute: str, element: int = 0) -> Any:
    """The compiled slot of ``attribute`` on a fixture (it must exist)."""
    found = compiled.slots.find(
        TargetRef(fixtureId=FixtureId(fixture_id), element=element), attribute
    )
    assert found is not None, f"no slot {fixture_id}:{element}/{attribute}"
    return found


def lanes_of(
    compiled: CompiledShow, logical: NDArray[np.float64], fixture_id: str, attribute: str
) -> list[float]:
    """The lanes of a fixture's attribute in a logical frame, as a list."""
    return [float(v) for v in logical[slot_of(compiled, fixture_id, attribute).lanes]]


def lane_kinds_rig(fixtures: int = 1, pars: int = 0) -> Doc:
    """Fixtures ``fx1…`` with every kind of lane the resolver merges differently:
    HTP (intensity), continuous LTP (pan, colour r/g/b, strobeRate), snap at
    start (positionSpeed, gobo1, shutter) and colour extras (w, a: snap at
    middle); plus Appendix A RGB pars ``fx-par1…`` (virtual intensity)."""
    wheels = [
        {
            "id": "w1",
            "kind": "gobo",
            "slots": [{"id": s, "name": s} for s in ("open", "dots", "lines")],
        }
    ]
    channels = [
        channel(0, "intensity"),
        channel(1, "pan", rng(0, 255, -90, 90)),
        channel(2, "positionSpeed"),
        *(color(3 + k, c) for k, c in enumerate(["red", "green", "blue", "white", "amber"])),
        channel(
            8,
            "gobo1",
            slot(0, 9, "open", "w1"),
            slot(10, 19, "dots", "w1"),
            slot(20, 29, "lines", "w1"),
        ),
        channel(
            9,
            "shutter",
            fn(0, 7, "closed"),
            fn(8, 15, "open"),
            fn(16, 255, "strobe", ("strobeRate", 1, 20)),
        ),
    ]
    _, par = appendix_profiles()
    rig = show(
        [profile("p", mode(channels), wheels=wheels), par],
        [fixture(f"fx{k}", k, "p", 1 + 10 * (k - 1)) for k in range(1, fixtures + 1)]
        + [
            fixture(f"fx-par{k}", 100 + k, "prof-par", 201 + 3 * (k - 1), mode_id="mode-3")
            for k in range(1, pars + 1)
        ],
    )
    return copy.deepcopy(rig)


BENCHMARK_TIMING: Final[Doc] = {
    "position": {"fade": 40.0, "delay": 1.0, "curve": "easeOut"},
    "color": {"fade": 25.0, "delay": 0.5, "curve": {"bezier": [0.25, 0.1, 0.25, 1.0]}},
}
"""Per-family timing of the benchmark rig's cues after the first: positions
and colours fade on their own times, delays and curves (the Bézier is the
dearest curve to evaluate)."""


def busking_benchmark_rig(
    universes: int = 64,
    playbacks: int = 60,
    seed: int = 19,
    *,
    cues: int = 1,
    tracking: bool = False,
    chases: int = 0,
    effects: int = 0,
) -> Doc:
    """The §19 reference rig (:func:`benchmark_rig`) with busking content:
    ``playbacks`` playbacks across 3 bands (2/3 at 50, 1/4 at 150, the rest
    at 200), each covering 3 random groups with intensity, colour, pan/tilt
    and gobo values.

    With ``cues=1`` (the Phase 3 benchmark) each playback runs that one cue,
    fading in over 1000 s. With more, the list (``tracking`` as given, wrap
    on) continues with cues that each change the 3 groups' intensities, one
    group's colour and, for heads, its tilt, fading 20 s in / 30 s out eased
    with :data:`BENCHMARK_TIMING`; the first cue fades in over 3 s.

    ``chases`` adds that many 4-step chases (playbacks ``ch-<k>``, band 100,
    crossfade 0.5) locked to the speed master ``m-speed`` (120 BPM) at ×8:
    16 steps per second. Each step lights one universe group.

    ``effects`` adds that many effect playbacks (``fx-<k>``, band 100, under
    the 1/3 of the looks in bands 150 and 200), each running one instance of
    a built-in library template with its console defaults, BPM-locked to
    ``m-speed`` at ×0.25 … ×2 (phase-5-plan §5.15). In turn: a circle (a
    relative ``add`` on pan and tilt) on ``g-heads``, then on the heads of
    one universe; a pulse (a relative ``multiply`` on intensity) on
    ``g-washes``; a wave (absolute intensity) on the cells of one universe;
    a colour cycle (absolute colour) on ``g-cells``. Circles, waves and
    colour cycles spread their phase over 360°.

    Groups: one per universe (every element of every fixture in it), and
    ``g-heads`` (all spots and MH-X25), ``g-washes`` (ML-56) and ``g-cells``
    (every PiX cell); with ``effects``, also ``g-heads-<u>`` and
    ``g-cells-<u>`` per universe, after the others.
    """
    generator = np.random.default_rng(seed)
    doc = benchmark_rig(universes)
    profiles = {p["id"]: p for p in doc["profiles"]}
    by_universe: dict[str, list[Doc]] = {}
    heads, washes, cells = [], [], []
    heads_in: dict[str, list[Doc]] = {}
    cells_in: dict[str, list[Doc]] = {}
    for fx in doc["fixtures"]:
        elements = len(profiles[fx["profileId"]]["modes"][0]["elements"])
        refs = [target_ref(fx["id"], e) for e in range(elements)]
        universe = fx["patch"]["universeId"]
        by_universe.setdefault(universe, []).extend(refs)
        attributes = {c["attribute"] for c in profiles[fx["profileId"]]["modes"][0]["channels"]}
        if "pan" in attributes:
            heads.append(refs[0])
            heads_in.setdefault(universe, []).append(refs[0])
        elif elements > 1:
            cells.extend(refs)
            cells_in.setdefault(universe, []).extend(refs)
        else:
            washes.append(refs[0])
    groups = {f"g-{u}": refs for u, refs in by_universe.items()}
    groups |= {"g-heads": heads, "g-washes": washes, "g-cells": cells}
    for number, (group_id, members) in enumerate(groups.items(), start=1):
        doc["groups"].append(
            {"id": group_id, "number": number, "name": group_id, "members": members}
        )
    names = list(groups)
    for k in range(playbacks):
        band = 50 if k < playbacks * 2 // 3 else 150 if k < playbacks * 11 // 12 else 200
        entries = []
        chosen = [str(group_id) for group_id in generator.choice(names, size=3, replace=False)]
        for group_id in chosen:
            spec = in_group(group_id)
            entries.append(entry(spec, "intensity", literal(float(generator.uniform(0.2, 1)))))
            entries.append(entry(spec, "color", literal(rgb(*generator.uniform(0, 1, 3).tolist()))))
            if group_id == "g-heads" or k % 4 == 0:
                entries.append(entry(spec, "pan", spread(-90, 90)))
                entries.append(entry(spec, "tilt", literal(float(generator.uniform(-45, 45)))))
                entries.append(entry(spec, "gobo1", literal({"slot": "open"})))
        if cues == 1:
            look(doc, f"pb-{k}", k + 1, *entries, fade_in=1000.0, priority=band, mode="ignoreFader")
            continue
        steps = [cue(f"c-pb-{k}-1", *entries, fade_in=3.0, curve="easeIn")]
        for c in range(2, cues + 1):
            changed = [
                entry(in_group(group_id), "intensity", literal(float(generator.uniform(0.2, 1))))
                for group_id in chosen
            ]
            recoloured = chosen[(c - 2) % 3]
            changed.append(
                entry(
                    in_group(recoloured),
                    "color",
                    literal(rgb(*generator.uniform(0, 1, 3).tolist())),
                )
            )
            if recoloured == "g-heads":
                tilt = float(generator.uniform(-45, 45))
                changed.append(entry(in_group(recoloured), "tilt", literal(tilt)))
            step = cue(
                f"c-pb-{k}-{c}",
                *changed,
                number=str(c),
                fade_in=20.0,
                fade_out=30.0,
                curve="easeInOut",
            )
            step["timing"]["perFamily"] = copy.deepcopy(BENCHMARK_TIMING)
            steps.append(step)
        sequence = cue_list(f"cl-pb-{k}", k + 1, *steps)
        sequence.update(tracking=tracking, wrap=True)
        doc["cueLists"].append(sequence)
        doc["playbacks"].append(
            playback(f"pb-{k}", k + 1, f"cl-pb-{k}", priority=band, mode="ignoreFader")
        )
    if chases or effects:
        doc["masters"].append(speed_master(bpm=120.0))
    universe_groups = [name for name in names if name.startswith("g-u")]
    for k in range(chases):
        number = playbacks + k + 1
        steps = [
            cue(
                f"c-ch-{k}-{s}",
                entry(in_group(universe_groups[(4 * k + s) % len(universe_groups)]), "intensity",
                      literal(1.0)),
                entry(in_group(universe_groups[(4 * k + s) % len(universe_groups)]), "color",
                      literal(rgb(*generator.uniform(0, 1, 3).tolist()))),
                number=str(s + 1),
            )
            for s in range(4)
        ]  # fmt: skip
        chase = cue_list(f"cl-ch-{k}", number, *steps)
        chase.update(
            mode="chase",
            chase={
                "rate": {"kind": "bpm", "masterId": "m-speed", "multiplier": 8.0},
                "direction": "forward",
                "crossfade": 0.5,
            },
        )
        doc["cueLists"].append(chase)
        doc["playbacks"].append(playback(f"ch-{k}", number, f"cl-ch-{k}", priority=100))
    if effects:
        _benchmark_effects(doc, effects, playbacks + chases, heads_in, cells_in)
    return copy.deepcopy(doc)


def _benchmark_effects(
    doc: Doc,
    count: int,
    numbered: int,
    heads_in: Mapping[str, list[Doc]],
    cells_in: Mapping[str, list[Doc]],
) -> None:
    """Add :func:`busking_benchmark_rig`'s ``count`` effect playbacks to
    ``doc``, numbered after its ``numbered`` playbacks."""
    extra = {f"g-heads-{u}": refs for u, refs in heads_in.items()}
    extra |= {f"g-cells-{u}": refs for u, refs in cells_in.items()}
    for group_id, members in extra.items():
        number = len(doc["groups"]) + 1
        doc["groups"].append(
            {"id": group_id, "number": number, "name": group_id, "members": members}
        )
    library = builtin_effects()
    universes = list(heads_in)
    used: set[str] = set()
    full_circle = {"phase": {"start": 0, "end": 360}}
    for k in range(count):
        kind, round_ = k % 4, k // 4
        universe = universes[round_ % len(universes)]
        template_id, group_id, spread_ = [
            ("ef-circle", "g-heads" if round_ == 0 else f"g-heads-{universe}", full_circle),
            ("ef-pulse", "g-washes", {}),
            ("ef-wave", f"g-cells-{universe}", full_circle),
            ("ef-rainbow", "g-cells", full_circle),
        ][kind]
        effect = library.get(template_id)
        assert effect is not None
        if template_id not in used:
            used.add(template_id)
            doc["effects"].append(copy.deepcopy(effect.template))
        multiplier = (0.25, 0.5, 1.0, 2.0)[round_ % 4]
        instance = effect_instance(
            f"ei-fx-{k}",
            template_id,
            in_group(group_id),
            rate={"kind": "bpm", "masterId": "m-speed", "multiplier": multiplier},
            **{**effect.defaults, **spread_},
        )
        step = cue(f"c-fx-{k}")
        step["effects"] = [instance]
        number = numbered + k + 1
        doc["cueLists"].append(cue_list(f"cl-fx-{k}", number, step))
        doc["playbacks"].append(playback(f"fx-{k}", number, f"cl-fx-{k}", priority=100))


def surface_benchmark_rig(bindings: int = 200) -> Doc:
    """The §19 reference rig (:func:`busking_benchmark_rig`) with one chase
    (61 playbacks and the speed master ``m-speed``), 3 pages of 20 slots and
    one MIDI controller ``s-midi`` with ``bindings`` bindings (at most 253),
    each with feedback on its own CC (128 per channel, from channel 1).

    In order: per slot of a page, its fader (motor and LED) and buttons (3
    LEDs, a scribble strip); an LED per playback; tap, blackout and page
    LEDs and displays; then motor faders for the playbacks by id.
    (phase-6-plan §5.20: the ``feedback_values`` gate and
    ``bench/surface_load.py``.)"""
    doc = busking_benchmark_rig(chases=1)
    ids = [playback["id"] for playback in doc["playbacks"]]
    doc["pages"] = [
        {"id": f"page-{n}", "number": n, "name": f"Page {n}", "slots": ids[(n - 1) * 20 : n * 20]}
        for n in (1, 2, 3)
    ]
    doc["surfaces"] = [
        {"id": "s-midi", "name": "Controller", "kind": "midi",
         "match": {"deviceName": "Controller"}, "faderPickup": "jump"}
    ]  # fmt: skip
    shown: list[tuple[dict[str, Any], str]] = []
    for slot in range(20):
        fader = {"kind": "playbackFader", "slot": slot}
        shown += [(fader, "motorFader"), (fader, "led")]
        shown += [({"kind": "playbackButton", "slot": slot, "button": b}, "led") for b in range(3)]
        shown.append(({"kind": "playbackButton", "slot": slot, "button": 0}, "display"))
    shown += [({"kind": "playbackFaderAbs", "playbackId": ident}, "led") for ident in ids]
    tap = {"kind": "tap", "masterId": "m-speed"}
    shown += [(tap, "led"), (tap, "display"), ({"kind": "blackout"}, "led")]
    shown += [({"kind": "page", "delta": delta}, "led") for delta in (1, -1)]
    shown += [
        ({"kind": "pageAbs", "number": n}, kind) for n in (1, 2, 3) for kind in ("led", "display")
    ]
    shown += [({"kind": "playbackFaderAbs", "playbackId": ident}, "motorFader") for ident in ids]
    doc["bindings"] = []
    for k, (action, kind) in enumerate(shown[:bindings]):
        address = {"kind": "midiCC", "channel": 1 + k // 128, "cc": k % 128}
        doc["bindings"].append(
            {"id": f"b-{k}", "surfaceId": "s-midi", "input": address, "action": action,
             "feedback": {"kind": kind, "address": address}}
        )  # fmt: skip
    assert len(doc["bindings"]) == bindings
    return doc
