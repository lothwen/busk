"""The programmer status (GAP-02 of ``docs/dev/tui/engine-gaps.md``).

``OfflineShow.programmer`` and ``LiveShow.programmer`` give the programmer
with fixtures by number: the selection as ``(number, element)`` pairs, the
values in the show's units with each preset reference resolved for its
element, the effect instances as the show file holds them, blind, highlight
and the fade time. What is dormant is left out, and ``version`` changes with
the content only. The rig: a spot with a colour wheel (101), two RGBW pars
(201, 202), a bar of four RGB cells (301), and a speed master.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from builders import (
    Doc,
    channel,
    color,
    effect_layer,
    effect_template,
    fixture,
    mode,
    preset,
    preset_value,
    profile,
    rgb,
    rng,
    show,
    show_of,
    slot,
    speed_master,
)
from busk.compiler.compile import compile_show
from busk.engine.clock import FakeClock
from busk.engine.link import LocalEngine
from busk.engine.loop import Engine
from busk.runner import LiveShow, OfflineShow
from busk.session.library import ProfileLibrary
from busk.session.status import ProgrammerStatus, ProgrammerValue


def status_rig() -> Doc:
    """Fixtures 101 (spot: intensity, pan, colour wheel), 201 and 202 (RGBW
    pars) and 301 (four RGB cells, its dimmer on the first); colour preset 1
    "Red" (global) and 2 "Mixed" (a global value, and cell 301.4's own); an
    intensity template "Wave"; a speed master "Speed"."""
    wheel = {
        "id": "color1",
        "kind": "color",
        "slots": [
            {"id": "open", "name": "Open"},
            {"id": "red", "name": "Red", "color": {"r": 1, "g": 0, "b": 0}},
        ],
    }
    spot = profile(
        "p-spot",
        mode(
            [
                channel(0, "intensity"),
                channel(1, "pan", rng(0, 255, -270, 270)),
                channel(2, "colorWheel", slot(0, 127, "open"), slot(128, 255, "red")),
            ]
        ),
        wheels=[wheel],
    )
    components = ("red", "green", "blue", "white")
    par = profile(
        "p-par",
        mode([channel(0, "intensity"), *(color(1 + k, c) for k, c in enumerate(components))]),
    )
    cells = [
        color(1 + 3 * cell + k, component, element=cell)
        for cell in range(4)
        for k, component in enumerate(("red", "green", "blue"))
    ]
    bar = profile("p-bar", mode([channel(0, "intensity"), *cells], elements=4))
    doc = show(
        [spot, par, bar],
        [
            fixture("f-spot", 101, "p-spot", 1),
            fixture("f-par1", 201, "p-par", 10),
            fixture("f-par2", 202, "p-par", 20),
            fixture("f-bar", 301, "p-bar", 30),
        ],
    )
    red = preset("pr-red", 1, "color", preset_value("color", rgb(1, 0, 0)))
    mixed = preset(
        "pr-mixed",
        2,
        "color",
        preset_value("color", rgb(0, 0, 1)),
        preset_value("color", rgb(0, 1, 0), "f-bar:3"),
    )
    red["name"], mixed["name"] = "Red", "Mixed"
    doc["presets"] = [red, mixed]
    wave = effect_template("ef-wave", effect_layer("intensity", "sine"))
    wave["name"] = "Wave"
    doc["effects"] = [wave]
    doc["masters"] = [speed_master("m-speed")]
    doc["masters"][0]["name"] = "Speed"
    return doc


@pytest.fixture
def offline() -> OfflineShow:
    return OfflineShow(show_of(status_rig()))


def run(show_: OfflineShow | LiveShow, *lines: str) -> None:
    for line in lines:
        reply = show_.execute(line)
        assert reply.ok, f"{line}: {reply.text}"


def value(
    number: int, attribute: str, shown: Any, preset_: tuple[str, int, str] | None = None
) -> ProgrammerValue:
    """A value of element 1 of fixture ``number``."""
    return ProgrammerValue(
        number=number, element=1, attribute=attribute, value=shown, preset=preset_
    )


# ------------------------------------------------------------- the content


def test_a_new_show_has_an_empty_programmer(offline: OfflineShow) -> None:
    status = offline.programmer
    assert status == ProgrammerStatus(
        version=1,
        selection=(),
        blind=False,
        highlight=False,
        fadeTime=0.0,
        values=(),
        effects=(),
    )
    assert offline.programmer is status  # nothing changed: the same object


def test_the_selection_is_number_and_element_in_selection_order(offline: OfflineShow) -> None:
    run(offline, "sel fixture 301")
    assert offline.programmer.selection == ((301, 1), (301, 2), (301, 3), (301, 4))
    run(offline, "sel fixture 202, fixture 101, fixture 301.3")
    assert offline.programmer.selection == ((202, 1), (101, 1), (301, 3))
    run(offline, "sel + fixture 201", "sel - fixture 101")
    assert offline.programmer.selection == ((202, 1), (301, 3), (201, 1))
    run(offline, "sel none")
    assert offline.programmer.selection == ()


def test_values_are_in_the_shows_units_in_the_programmers_order(offline: OfflineShow) -> None:
    run(offline, "sel fixture 101", "set intensity 50%", "set pan -45", "set colorWheel red")
    run(offline, "sel fixture 201", "set color 1 0.5 0 w 0.25", "sel fixture 301.2")
    run(offline, "set color 0 0 1", "sel fixture 101", "set intensity 75%")  # keeps its place
    assert offline.programmer.values == (
        value(101, "intensity", 0.75),
        value(101, "pan", -45.0),
        value(101, "colorWheel", {"slot": "red"}),
        value(201, "color", {"r": 1.0, "g": 0.5, "b": 0.0, "w": 0.25}),
        ProgrammerValue(number=301, element=2, attribute="color", value=rgb(0, 0, 1), preset=None),
    )
    assert offline.programmer.selection == ((101, 1),)  # values outlive the selection


def test_a_preset_reference_has_the_value_it_gives_each_element(offline: OfflineShow) -> None:
    run(offline, "sel fixture 201, fixture 301.4", "preset color 2")
    mixed = ("color", 2, "Mixed")
    assert offline.programmer.values == (
        value(201, "color", rgb(0, 0, 1), mixed),  # the global value
        ProgrammerValue(  # the cell's own
            number=301, element=4, attribute="color", value=rgb(0, 1, 0), preset=mixed
        ),
    )


def test_the_modes_are_listed(offline: OfflineShow) -> None:
    run(offline, "blind on", "highlight on", "fade 2.5")
    status = offline.programmer
    assert (status.blind, status.highlight, status.fadeTime) == (True, True, 2.5)
    run(offline, "blind off")
    assert offline.programmer.blind is False


def test_effects_are_the_instances_as_the_show_file_holds_them(offline: OfflineShow) -> None:
    run(offline, "sel fixture 201 thru 202", 'effect add "Wave" hz 2')
    run(offline, 'effect add "Wave" id slow bpm "Speed" x 0.5 wings 2')
    first, second = offline.programmer.effects
    refs = [{"fixtureId": "f-par1", "element": 0}, {"fixtureId": "f-par2", "element": 0}]
    assert (first["templateId"], first["targets"], first["rate"]) == (
        "ef-wave",
        {"kind": "targets", "refs": refs},
        {"kind": "hz", "value": 2},
    )
    assert (second["id"], second["rate"], second["wings"]) == (
        "slow",
        {"kind": "bpm", "masterId": "m-speed", "multiplier": 0.5},
        2,
    )
    run(offline, f"effect remove {first['id']}")
    assert [effect["id"] for effect in offline.programmer.effects] == ["slow"]
    run(offline, "clear")
    assert (offline.programmer.values, offline.programmer.effects) == ((), ())


def test_the_status_is_a_copy(offline: OfflineShow) -> None:
    run(offline, "sel fixture 201", "set color 1 0 0", 'effect add "Wave" hz 2')
    status = offline.programmer
    shown = status.values[0].value
    assert isinstance(shown, dict)
    shown["r"] = 0.0
    status.effects[0]["size"] = 0.0
    run(offline, "blind on")  # a new status, from the session's own programmer
    assert offline.programmer.values[0].value == rgb(1, 0, 0)
    assert offline.programmer.effects[0]["size"] == 1


# ---------------------------------------------------------------- dormant


def test_what_is_dormant_is_left_out_until_an_undo_brings_it_back(
    offline: OfflineShow,
) -> None:
    run(offline, "sel fixture 202, fixture 201", "set intensity 40%", 'effect add "Wave" hz 2')
    run(offline, "delete fixture 202")
    status = offline.programmer
    assert status.selection == ((201, 1),)
    assert status.values == (value(201, "intensity", 0.4),)
    assert status.effects == ()  # it targets 202: it no longer validates
    run(offline, "undo")
    restored = offline.programmer
    assert restored.selection == ((202, 1), (201, 1))
    assert [v.number for v in restored.values] == [202, 201]
    assert len(restored.effects) == 1


def test_a_reference_to_a_deleted_preset_is_left_out(offline: OfflineShow) -> None:
    run(offline, "sel fixture 201", "preset color 1", "set intensity 50%")
    run(offline, "delete preset color 1")
    assert offline.programmer.values == (value(201, "intensity", 0.5),)
    run(offline, "undo")
    assert offline.programmer.values[0] == value(201, "color", rgb(1, 0, 0), ("color", 1, "Red"))


# ----------------------------------------------------------------- version


def test_the_version_grows_with_every_change_of_the_content(offline: OfflineShow) -> None:
    versions = [offline.programmer.version]
    for line in ("sel fixture 201", "set intensity 50%", "blind on", "fade 1", "undo"):
        run(offline, line)
        versions.append(offline.programmer.version)
    assert versions == [1, 2, 3, 4, 5, 6]


def test_a_show_change_alone_changes_what_it_shows(offline: OfflineShow) -> None:
    run(offline, "sel fixture 202", "preset color 2")
    before = offline.programmer
    run(offline, 'rename preset color 2 "Deep"')
    renamed = offline.programmer
    assert renamed.values[0].preset == ("color", 2, "Deep")
    assert renamed.version == before.version + 1
    run(offline, "fixture 202 number 205")
    renumbered = offline.programmer
    assert (renumbered.selection, renumbered.values[0].number) == (((205, 1),), 205)
    assert renumbered.version == renamed.version + 1


def test_a_change_that_shows_nothing_new_keeps_the_status(
    offline: OfflineShow, tmp_path: Path
) -> None:
    run(offline, "sel fixture 201", "set intensity 50%")
    status = offline.programmer
    run(offline, 'universe add 2 "Spare"', f"save {tmp_path / 'saved.show'}")
    run(offline, "sel fixture 201")  # the same selection again
    assert offline.programmer is status


# ------------------------------------------------------------------- hosts


def test_a_live_show_has_it_before_and_while_it_runs() -> None:
    live = LiveShow(show_of(status_rig()), output=False)
    run(live, "sel fixture 101")  # programmer commands apply in the session at once
    assert live.programmer.selection == ((101, 1),)
    with live:
        run(live, "set intensity 30%")
        read: list[ProgrammerStatus] = []
        reader = threading.Thread(target=lambda: read.append(live.programmer))
        reader.start()
        reader.join()
        assert read[0].values == (value(101, "intensity", 0.3),)


def test_busk_runs_console_process_has_it_too() -> None:
    shown = show_of(status_rig())
    compiled = compile_show(shown)
    clock = FakeClock()
    live = LiveShow._attached(
        shown,
        compiled,
        LocalEngine(Engine(compiled, clock)),
        clock,
        path=Path("unused.show"),
        library=ProfileLibrary(),
        state_dir=Path("unused"),
        dirty=False,
        stamp=("s", 0),
        causes=False,
        iface="lo",
        status=lambda: "",
        about=lambda: (),
        poll=lambda: None,
        routes=lambda: None,
        say=lambda text: None,
        warn=lambda text: None,
    )
    run(live, "sel fixture 301.4", "set color 0 1 0")
    status = live.programmer
    assert status.selection == ((301, 4),)
    assert status.values == (
        ProgrammerValue(number=301, element=4, attribute="color", value=rgb(0, 1, 0), preset=None),
    )
    assert (live.frame, live.output) == (None, None)  # those stay in the engine process
