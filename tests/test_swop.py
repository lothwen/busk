"""Swop buttons (phase-6-plan §5.3, decision 9).

A swop button is a flash that also removes the intensity presence of every
other playback that is not ``protectFromSwop``, while any swop is held.
Nothing fades: releasing the last swop gives back the exact frame.

The rig: three spots. pb-a (MH 1 at 0.8) is the playback that swops; pb-b
(MH 2 at 0.6, red) is unprotected and pb-c (MH 3 at 0.5) protected. pb-over
holds MH 1 at 0.2 from band 100, and pb-fx runs intensity effects.
"""

from __future__ import annotations

from typing import Any, cast

import numpy as np
import pytest

from builders import (
    busk_rig,
    compile_doc,
    entry,
    lanes_of,
    literal,
    look,
    page,
    rgb,
    targets,
)
from busk.cli import status_line
from busk.commands.types import Command, CommandOrigin
from busk.compiler.compile import CompiledShow
from busk.engine.install import EMPTY_FRAME, Install
from busk.engine.snapshot import PlaybackStatus
from harness import Harness, Observation, fader, flash

SWOP, FLASH = 0, 1


def _command(**fields: Any) -> Command:
    return cast(Command, fields)


def swop(playback: str, down: bool, **origin: Any) -> tuple[Command, CommandOrigin]:
    command = _command(type="PLAYBACK_BUTTON", playbackId=playback, button=SWOP, down=down)
    return command, cast(CommandOrigin, origin)


@pytest.fixture
def doc() -> dict[str, Any]:
    doc = busk_rig(spots=3)
    doc["effects"] = [
        {"id": "t-abs", "name": "abs", "layers": [_layer("absolute")]},
        {"id": "t-add", "name": "add", "layers": [_layer("add")]},
    ]
    buttons = ("swop", "flash", "toggle")
    look(doc, "pb-a", 1, entry(targets("fx-mh1"), "intensity", literal(0.8)), buttons=buttons)
    look(
        doc,
        "pb-b",
        2,
        entry(targets("fx-mh2"), "intensity", literal(0.6)),
        entry(targets("fx-mh2"), "color", literal(rgb(1, 0, 0))),
        buttons=buttons,
    )
    look(doc, "pb-c", 3, entry(targets("fx-mh3"), "intensity", literal(0.5)), buttons=buttons)
    doc["playbacks"][-1]["protectFromSwop"] = True
    look(
        doc,
        "pb-over",
        4,
        entry(targets("fx-mh1"), "intensity", literal(0.2)),
        priority=100,
        buttons=buttons,
    )
    look(doc, "pb-fx", 5, buttons=buttons)
    doc["cueLists"][-1]["cues"][0]["effects"] = [
        _instance("e-abs", "t-abs", "fx-mh2"),
        _instance("e-add", "t-add", "fx-mh1"),
    ]
    doc["pages"].append(page("page-1", 1, "pb-a", "pb-b"))
    doc["pages"].append(page("page-2", 2, "pb-b", "pb-a"))
    return doc


def _layer(mode: str) -> dict[str, Any]:
    return {"attribute": "intensity", "waveform": {"kind": "sine"}, "phaseOffset": 0, "mode": mode}


def _instance(ident: str, template: str, fixture: str) -> dict[str, Any]:
    return {
        "id": ident,
        "templateId": template,
        "targets": targets(fixture),
        "rate": {"kind": "hz", "value": 1.0},
        "direction": "forward",
        "size": 0.3,
        "phase": {"start": 0, "end": 0},
        "groups": 1,
        "blocks": 1,
        "wings": 1,
    }


@pytest.fixture
def show(doc: dict[str, Any]) -> CompiledShow:
    return compile_doc(doc)


def started(show: CompiledShow, *playbacks: str) -> Harness:
    """An engine with ``playbacks`` up on their faders, settled at t = 1."""
    harness = Harness(show)
    harness.submit(*(fader(ident, 1.0) for ident in playbacks))
    harness.tick(0.0)
    harness.tick(1.0)
    return harness


def submit(harness: Harness, *pressed: tuple[Command, CommandOrigin]) -> None:
    for command, origin in pressed:
        harness.engine.bus.submit(command, origin)


def intensity(harness: Harness, observed: Observation, fixture: str) -> float:
    return lanes_of(harness.compiled, observed.logical, fixture, "intensity")[0]


def levels(harness: Harness, observed: Observation) -> tuple[float, float, float]:
    mh1, mh2, mh3 = (intensity(harness, observed, f"fx-mh{k}") for k in (1, 2, 3))
    return mh1, mh2, mh3


def status(observed: Observation, ident: str) -> PlaybackStatus:
    assert observed.snapshot is not None
    return next(p for p in observed.snapshot.playbacks if p.id == ident)


def test_only_the_swopped_and_protected_playbacks_keep_their_intensity(
    show: CompiledShow,
) -> None:
    harness = started(show, "pb-b", "pb-c")
    before = harness.tick(1.1)
    assert levels(harness, before) == pytest.approx((0.0, 0.6, 0.5))
    submit(harness, swop("pb-a", True))
    held = harness.tick(1.2)
    assert levels(harness, held) == pytest.approx((0.8, 0.0, 0.5))  # pb-a's flash; pb-c kept
    assert (status(held, "pb-a").swop, status(held, "pb-a").flash) == (True, True)
    assert not status(held, "pb-b").swop
    assert status(held, "pb-b").state == "active"  # suppressed, not released
    submit(harness, swop("pb-a", False))
    after = harness.tick(1.3)
    np.testing.assert_array_equal(after.logical, before.logical)  # the exact frame back
    assert after.universe == before.universe
    assert (status(after, "pb-a").swop, status(after, "pb-a").flash) == (False, False)
    assert harness.engine.stats.commandErrors == 0


def test_an_override_band_does_not_hold_the_swopped_playback(show: CompiledShow) -> None:
    """With ``intensityScale = 0`` (§7.6) pb-over would still be present at
    band 100 and hold MH 1 at 0; without presence it cannot."""
    harness = started(show, "pb-a", "pb-over")
    assert levels(harness, harness.tick(1.1))[0] == pytest.approx(0.2)
    submit(harness, swop("pb-a", True))
    assert levels(harness, harness.tick(1.2))[0] == pytest.approx(0.8)
    submit(harness, swop("pb-a", False))
    assert levels(harness, harness.tick(1.3))[0] == pytest.approx(0.2)


def test_ltp_values_are_untouched(show: CompiledShow) -> None:
    harness = started(show, "pb-b")
    before = harness.tick(1.1)
    submit(harness, swop("pb-a", True))
    held = harness.tick(1.2)
    color = lanes_of(show, held.logical, "fx-mh2", "color")
    np.testing.assert_array_equal(color, lanes_of(show, before.logical, "fx-mh2", "color"))
    assert color[:3] == [1.0, 0.0, 0.0]
    assert levels(harness, held)[1] == 0.0


def test_effects_intensity_is_suppressed(show: CompiledShow) -> None:
    """pb-fx's absolute wave on MH 2 has no presence, and its relative wave
    on MH 1 no weight, so MH 1 is exactly pb-a's flash."""
    harness = started(show, "pb-fx")
    waving = [levels(harness, harness.tick(t)) for t in (1.3, 1.4)]
    assert all(mh1 > 0.0 and mh2 > 0.0 for mh1, mh2, _ in waving)
    submit(harness, swop("pb-a", True))
    for t in (1.4, 1.55, 1.8):
        mh1, mh2, _ = levels(harness, harness.tick(t))
        assert (mh1, mh2) == (pytest.approx(0.8), 0.0)


def test_another_playbacks_flash_is_suppressed_with_its_effects(show: CompiledShow) -> None:
    """pb-b's held flash, and pb-fx's flash with its flash bank's waves, have
    no intensity while pb-a swops."""
    harness = Harness(show)
    harness.submit(flash("pb-b", True), flash("pb-fx", True))
    harness.tick(0.0)  # the flash bank's waves start here
    flashing = levels(harness, harness.tick(1.3))
    assert flashing[0] > 0.0  # pb-fx's relative wave on MH 1
    assert flashing[1] >= 0.6
    submit(harness, swop("pb-a", True))
    for t in (1.4, 1.55):
        assert levels(harness, harness.tick(t)) == pytest.approx((0.8, 0.0, 0.0))


def test_two_swops_held(show: CompiledShow) -> None:
    harness = started(show, "pb-a", "pb-b", "pb-c")
    before = harness.tick(1.1)
    submit(harness, swop("pb-a", True), swop("pb-b", True))
    assert levels(harness, harness.tick(1.2)) == pytest.approx((0.8, 0.6, 0.5))
    submit(harness, swop("pb-b", False))  # pb-a still swops: pb-b is suppressed again
    assert levels(harness, harness.tick(1.3)) == pytest.approx((0.8, 0.0, 0.5))
    submit(harness, swop("pb-a", False))
    after = harness.tick(1.4)
    np.testing.assert_array_equal(after.logical, before.logical)


def test_the_same_playback_swopped_from_two_controls(show: CompiledShow) -> None:
    """Each press is counted: the swop holds until the last release."""
    harness = started(show, "pb-b")
    submit(harness, swop("pb-a", True), swop("pb-a", True, remote="phone"))
    harness.tick(1.1)
    submit(harness, swop("pb-a", False))
    held = harness.tick(1.2)
    assert status(held, "pb-a").swop
    assert levels(harness, held)[1] == 0.0
    submit(harness, swop("pb-a", False, remote="phone"))
    released = harness.tick(1.3)
    assert not status(released, "pb-a").swop
    assert levels(harness, released)[1] == pytest.approx(0.6)


def test_a_swop_and_a_flash_on_one_playback(show: CompiledShow) -> None:
    """The flash stays up while either button holds it."""
    harness = started(show, "pb-b")
    submit(harness, swop("pb-a", True))
    harness.submit(flash("pb-a", True))
    harness.tick(1.1)
    submit(harness, swop("pb-a", False))
    observed = harness.tick(1.2)
    assert levels(harness, observed)[:2] == pytest.approx((0.8, 0.6))  # a flash, no swop
    assert (status(observed, "pb-a").flash, status(observed, "pb-a").swop) == (True, False)


def test_a_release_without_a_press_does_nothing(show: CompiledShow) -> None:
    harness = started(show, "pb-b")
    before = harness.tick(1.1)
    submit(harness, swop("pb-a", False))
    after = harness.tick(1.2)
    np.testing.assert_array_equal(after.logical, before.logical)
    submit(harness, swop("pb-a", True))  # the stray release left no debt
    assert levels(harness, harness.tick(1.3))[1] == 0.0


def test_a_swop_held_through_a_slot_is_released_after_a_page_change(show: CompiledShow) -> None:
    harness = started(show, "pb-b")
    pressed = _command(type="PLAYBACK_BUTTON", slot=0, button=SWOP, down=True)
    harness.engine.bus.submit(pressed, CommandOrigin(control="b-swop"))  # pb-a on page 1
    harness.submit(_command(type="PAGE", number=2))
    held = harness.tick(1.1)
    assert status(held, "pb-a").swop
    released = _command(type="PLAYBACK_BUTTON", slot=0, button=SWOP, down=False)
    harness.engine.bus.submit(released, CommandOrigin(control="b-swop"))  # slot 0: pb-b now
    after = harness.tick(1.2)
    assert not status(after, "pb-a").swop
    assert levels(harness, after)[1] == pytest.approx(0.6)


def test_swop_applies_no_exclusivity(doc: dict[str, Any]) -> None:
    for playback in doc["playbacks"][:2]:
        playback["exclusivity"] = "looks"
    harness = started(compile_doc(doc), "pb-b")
    submit(harness, swop("pb-a", True))
    harness.tick(1.1)
    submit(harness, swop("pb-a", False))
    observed = harness.tick(1.2)
    assert status(observed, "pb-b").state == "active"


def install(harness: Harness, doc: dict[str, Any]) -> None:
    harness.engine.bus.install(
        Install(compiled=compile_doc(doc), remap=None, programmer=EMPTY_FRAME)
    )


def test_a_live_edit_protecting_a_playback_shows_it_at_once(
    doc: dict[str, Any], show: CompiledShow
) -> None:
    harness = started(show, "pb-b")
    submit(harness, swop("pb-a", True))
    assert levels(harness, harness.tick(1.1))[1] == 0.0
    doc["playbacks"][1]["protectFromSwop"] = True
    install(harness, doc)
    assert levels(harness, harness.tick(1.2))[1] == pytest.approx(0.6)


def test_deleting_the_swopped_playback_ends_the_swop(
    doc: dict[str, Any], show: CompiledShow
) -> None:
    harness = started(show, "pb-b")
    submit(harness, swop("pb-a", True))
    assert levels(harness, harness.tick(1.1))[1] == 0.0
    del doc["playbacks"][0]
    doc["pages"] = [page("page-1", 1, None, "pb-b")]
    install(harness, doc)
    assert levels(harness, harness.tick(1.2))[1] == pytest.approx(0.6)
    assert harness.engine.runtime.playbacks.swopping == {}


def test_the_status_line_shows_a_held_swop(show: CompiledShow) -> None:
    harness = started(show, "pb-b")
    submit(harness, swop("pb-a", True))
    observed = harness.tick(1.1)
    assert observed.snapshot is not None
    assert status_line(observed.snapshot).endswith("| 1 pb-a swop · 2 pb-b on 1.00")
