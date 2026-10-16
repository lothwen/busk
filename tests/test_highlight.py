"""Highlight (phase-7-plan decision 12, §5.12, step 4).

``HIGHLIGHT {on}`` is a programmer mode: every selected target gets
intensity 1 (after the masters), shutter ``open`` and colour white, and its
other channels their profile's ``highlightDmx``, except pan, tilt and
parked slots. Blackout, park and limits win over it; blind does not hide
it; a selection change moves it; it is never undone.

Appendix A's moving-head profile gets ``highlightDmx`` on pan, tilt and
intensity (never written: pan and tilt are excluded, intensity is set
logically), zoom and gobo, and a new 16-bit focus channel. MH 1 is
patched at address 1, MH 2 at 17.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from builders import APPENDIX_A, Doc, channel, load_doc
from session_harness import Live, blind, put, sel

PAN, DIMMER, ZOOM, GOBO, FOCUS = 0, 8, 10, 11, 13  # 0-based offsets in the footprint
MH2 = 16  # MH 2's first byte


def appendix(park: list[Doc] | None = None) -> Doc:
    """Appendix A with highlight values on the moving heads, and ``park``."""
    doc = load_doc(APPENDIX_A)
    channels = doc["profiles"][0]["modes"][0]["channels"]  # prof-mh mode-16
    by_attribute = {c["attribute"]: c for c in channels if c["attribute"] != "color"}
    for attribute, value in [("pan", 0), ("tilt", 0), ("intensity", 0), ("zoom", 200),
                             ("gobo1", 9)]:  # fmt: skip
        by_attribute[attribute]["highlightDmx"] = value
    focus = channel(FOCUS, "focus", nbytes=2, default=0)
    focus["highlightDmx"] = 0x1234
    channels.append(focus)
    doc["park"] = copy.deepcopy(park or [])
    return doc


def highlight(on: bool) -> dict[str, Any]:
    return {"type": "HIGHLIGHT", "on": on}


def parked(attribute: str, value: Any) -> Doc:
    return {"slot": {"target": {"fixtureId": "fx-mh1", "element": 0}, "attribute": attribute},
            "value": value}  # fmt: skip


def shutter_open(live: Live) -> float:
    """The lane value of MH 1's ``open`` shutter option."""
    slots = live.engine.compiled.slots
    slot = next(s for s in slots.slots if s.attribute.id == "shutter")
    return float(slot.options.index("open"))


def lit(live: Live) -> Live:
    live.do(sel("fx-mh1"), highlight(True))
    live.tick()
    return live


# ------------------------------------------------------------- the look


def test_highlight_is_full_white_and_open_under_a_grand_master_at_half() -> None:
    live = Live(appendix())
    live.do({"type": "SET_MASTER", "masterId": "m-gm", "level": 0.5})
    lit(live)
    assert live.lanes("fx-mh1", "intensity") == [1.0]
    assert live.lanes("fx-mh1", "color")[:3] == [1.0, 1.0, 1.0]
    assert live.lanes("fx-mh1", "shutter") == [shutter_open(live)]
    assert live.lanes("fx-mh2", "intensity") == [0.0]  # not selected
    dmx = live.universe()
    assert dmx[DIMMER : DIMMER + 2] == bytes([255, 255])  # not highlightDmx 0
    assert dmx[MH2 + DIMMER : MH2 + DIMMER + 2] == bytes([0, 0])


def test_highlight_dmx_goes_to_other_channels_but_never_pan_or_tilt() -> None:
    live = lit(Live(appendix()))
    dmx = live.universe()
    assert dmx[ZOOM] == 200
    assert dmx[GOBO] == 9
    assert dmx[FOCUS : FOCUS + 2] == bytes([0x12, 0x34])  # coarse, fine
    assert dmx[PAN : PAN + 4] == bytes([128, 0, 128, 0])  # pan and tilt at their defaults
    assert dmx[MH2 + ZOOM] == 128  # MH 2 keeps its default zoom


def test_highlight_off_returns_to_the_live_look() -> None:
    live = Live(appendix())
    plain = live.tick()
    before = live.universe()
    lit(live)
    live.do(highlight(False))
    after = live.tick()
    assert live.universe() == before
    assert after.tolist() == pytest.approx(plain.tolist(), nan_ok=True)


# ------------------------------------------------------------- what wins


def test_blackout_wins_over_highlight_and_its_bytes() -> None:
    dark = Live(appendix())
    dark.do({"type": "BLACKOUT", "on": True})
    dark.tick()
    live = lit(Live(appendix()))
    live.do({"type": "BLACKOUT", "on": True})
    live.tick()
    assert live.lanes("fx-mh1", "intensity") == [0.0]
    dmx, plain = live.universe(), dark.universe()
    assert dmx[DIMMER : DIMMER + 2] == bytes([0, 0])
    for offset in (ZOOM, GOBO, FOCUS, FOCUS + 1):  # no highlightDmx in blackout
        assert dmx[offset] == plain[offset]


def test_park_wins_over_highlight_lanes_and_bytes() -> None:
    green = {"r": 0, "g": 1, "b": 0}
    park = [parked("intensity", 0.3), parked("gobo1", {"slot": "breakup"}),
            parked("color", green)]  # fmt: skip
    unlit = Live(appendix(park))
    unlit.tick()
    live = lit(Live(appendix(park)))
    assert live.lanes("fx-mh1", "intensity") == [0.3]
    assert live.lanes("fx-mh1", "color")[:3] == [0.0, 1.0, 0.0]
    assert live.universe()[GOBO] == unlit.universe()[GOBO] != 9  # the parked gobo
    assert live.universe()[ZOOM] == 200  # zoom is not parked


def test_a_park_edit_while_highlighted_takes_the_slot_out() -> None:
    live = lit(Live(appendix()))
    live.do({"type": "SET", "path": ["park"], "value": [parked("zoom", 30)]})
    live.tick()
    assert live.lanes("fx-mh1", "intensity") == [1.0]  # still highlighted
    assert live.universe()[ZOOM] != 200
    assert live.lanes("fx-mh1", "zoom") == [30.0]


def test_limits_win_over_highlight() -> None:
    doc = appendix()
    doc["fixtures"][0]["limits"] = {"intensityMax": 0.6}
    live = lit(Live(doc))
    assert live.lanes("fx-mh1", "intensity") == [0.6]


# ------------------------------------------------------------ programmer mode


def test_blind_does_not_hide_highlight() -> None:
    live = Live(appendix())
    live.do(blind(True), sel("fx-mh1"), put("intensity", 0.2), highlight(True))
    live.tick()
    assert live.lanes("fx-mh1", "intensity") == [1.0]
    live.do(highlight(False))
    live.tick()
    assert live.lanes("fx-mh1", "intensity") == [0.0]  # blind: the 0.2 is not live


def test_a_selection_change_moves_highlight() -> None:
    live = lit(Live(appendix()))
    live.do(sel("fx-mh2"))
    live.tick()
    assert live.lanes("fx-mh1", "intensity") == [0.0]
    assert live.lanes("fx-mh2", "intensity") == [1.0]
    assert live.universe()[MH2 + ZOOM] == 200
    live.do({"type": "CLEAR_PROGRAMMER"})
    live.tick()
    assert live.lanes("fx-mh2", "intensity") == [0.0]
    assert live.session.programmer.highlight  # the mode stays on


def test_highlight_survives_a_show_edit() -> None:
    live = lit(Live(appendix()))
    live.do({"type": "SET", "path": ["meta", "title"], "value": "Renamed"})
    live.tick()
    assert live.lanes("fx-mh1", "intensity") == [1.0]


def test_highlight_is_a_mode_without_an_undo_step() -> None:
    live = Live(appendix())
    live.do(sel("fx-mh1"))
    steps = live.session.timeline.undo_count
    live.do(highlight(True), highlight(False), highlight(True))
    assert live.session.timeline.undo_count == steps
    live.do({"type": "UNDO"})  # undoes the selection; highlight stays on
    live.tick()
    assert live.session.programmer.highlight
    assert live.lanes("fx-mh1", "intensity") == [0.0]


def test_highlight_is_saved_with_the_programmer() -> None:
    from busk.session.programmer import from_json, to_json

    live = lit(Live(appendix()))
    data = to_json(live.session.programmer)
    assert data["highlight"] is True
    restored, dropped = from_json(data)
    assert restored.highlight
    assert not dropped
    assert not from_json({**data, "highlight": None})[0].highlight
    del data["highlight"]  # files from before Phase 7
    old, dropped = from_json(data)
    assert not old.highlight
    assert not dropped
