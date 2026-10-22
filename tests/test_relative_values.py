"""Relative and per-component values (GAP-05 of ``docs/dev/tui/engine-gaps.md``).

``ADJUST_ATTRIBUTE`` changes what the programmer holds on each selected
target that holds something: a scalar by a delta, or one colour component
by a delta or to a value. The console says ``set <attribute> by <change>``
and ``set color.<c> [by] <value>`` (the parser's cases are in
``test_console_parser.py``). Appendix A: two heads (MH 1 and 2, fixtures 101
and 102, with a white emitter) and a par (201, red, green and blue, no pan);
preset position 1 "Audience" gives each head its own pan, preset color 1 is
blue.
"""

from __future__ import annotations

import json
import math
import socket
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from builders import APPENDIX_A, load_doc, localhost_route, show_of, state_of
from busk import LiveShow, OfflineShow, Reply
from busk.commands.errors import CommandError
from busk.commands.types import Command
from busk.model.validate import validate_show
from busk.session.programmer import EMPTY, Programmer, handle
from busk.session.state import ShowState
from process_harness import BuskRun
from sacn_receiver import Receiver

MH1, MH2, PAR = (
    {"fixtureId": "fx-mh1", "element": 0},
    {"fixtureId": "fx-mh2", "element": 0},
    {"fixtureId": "fx-par1", "element": 0},
)


@pytest.fixture(scope="module")
def state() -> ShowState:
    return state_of(load_doc(APPENDIX_A))


def run(state: ShowState, programmer: Programmer, *commands: dict[str, Any]) -> Programmer:
    for command in commands:
        programmer = handle(state, programmer, cast(Command, command)).programmer
    return programmer


def message(state: ShowState, programmer: Programmer, command: dict[str, Any]) -> str:
    return handle(state, programmer, cast(Command, command)).message


def select(*refs: dict[str, Any]) -> dict[str, Any]:
    return {"type": "SELECT", "targets": {"kind": "targets", "refs": list(refs)}, "mode": "replace"}


def set_attr(attribute: str, value: Any) -> dict[str, Any]:
    return {"type": "SET_ATTRIBUTE", "attribute": attribute,
            "value": {"kind": "literal", "value": value}}  # fmt: skip


def preset(ident: str) -> dict[str, Any]:
    return {"type": "APPLY_PRESET", "presetId": ident}


def by(attribute: str, delta: float, component: str | None = None) -> dict[str, Any]:
    command = {"type": "ADJUST_ATTRIBUTE", "attribute": attribute, "delta": delta}
    return command if component is None else {**command, "component": component}


def to(component: str, value: float) -> dict[str, Any]:
    return {"type": "ADJUST_ATTRIBUTE", "attribute": "color", "component": component,
            "value": value}  # fmt: skip


def values(programmer: Programmer) -> dict[str, Any]:
    return {key: dict(source) for key, source in programmer.values.items()}


# ----------------------------------------------------------------- relative


def test_a_delta_is_added_to_each_targets_own_value(state: ShowState) -> None:
    p = run(state, EMPTY, select(MH1), set_attr("intensity", 0.2),
            select(MH2), set_attr("intensity", 0.5), select(MH1, MH2))  # fmt: skip
    assert message(state, p, by("intensity", 0.05)) == "intensity: 2 targets"
    p = run(state, p, by("intensity", 0.05))
    assert values(p) == {
        "fx-mh1:0/intensity": {"kind": "literal", "value": 0.25},
        "fx-mh2:0/intensity": {"kind": "literal", "value": 0.55},
    }


def test_a_change_stays_within_the_attributes_range(state: ShowState) -> None:
    """Intensity is 0..1; pan has no range of its own, so it goes as far as
    ``set pan`` does."""
    p = run(state, EMPTY, select(MH1), set_attr("intensity", 0.98), set_attr("pan", 300))
    p = run(state, p, by("intensity", 0.05), by("pan", 100))
    assert values(p)["fx-mh1:0/intensity"]["value"] == 1.0
    assert values(p)["fx-mh1:0/pan"]["value"] == 400
    p = run(state, p, by("intensity", -2), by("pan", -1000))
    assert values(p)["fx-mh1:0/intensity"]["value"] == 0.0
    assert values(p)["fx-mh1:0/pan"]["value"] == -600


def test_steps_add_up_without_float_noise(state: ShowState) -> None:
    p = run(state, EMPTY, select(MH1), set_attr("intensity", 0.35), by("intensity", 0.05))
    assert values(p)["fx-mh1:0/intensity"]["value"] == 0.4  # not 0.39999999999999997
    p = run(state, p, *[by("intensity", -0.1)] * 3)
    assert values(p)["fx-mh1:0/intensity"]["value"] == 0.1


def test_a_preset_reference_becomes_the_presets_value_changed(state: ShowState) -> None:
    """Each head's pan in Audience is its own (45 and -45); the reference
    gives way to the literal, as editing a preset value does on a console."""
    p = run(state, EMPTY, select(MH1, MH2), preset("pr-aud"), by("pan", 15))
    assert values(p)["fx-mh1:0/pan"] == {"kind": "literal", "value": 60}
    assert values(p)["fx-mh2:0/pan"] == {"kind": "literal", "value": -30}
    assert values(p)["fx-mh1:0/tilt"] == {"kind": "preset", "presetId": "pr-aud"}  # untouched


def test_targets_without_a_value_are_skipped_and_said(state: ShowState) -> None:
    """The programmer does not know what the stage shows where it holds
    nothing, so it changes nothing there."""
    p = run(state, EMPTY, select(MH1), set_attr("pan", 10), select(MH1, MH2, PAR))
    assert message(state, p, by("pan", 5)) == (
        "pan: 1 target; skipped 1 no pan, 1 not in the programmer"
    )
    assert list(values(run(state, p, by("pan", 5)))) == ["fx-mh1:0/pan"]
    refused = r"^no selected target has intensity to change \(3 not in the programmer\)$"
    with pytest.raises(CommandError, match=refused):
        handle(state, p, cast(Command, by("intensity", 0.05)))


def test_a_preset_that_no_longer_gives_a_value_is_skipped(state: ShowState) -> None:
    """A dormant reference (the preset lost the value) is not changed."""
    p = Programmer(
        selection=(MH1, MH2),
        values={
            "fx-mh1:0/color": {"kind": "preset", "presetId": "pr-aud"},  # Audience has no colour
            "fx-mh2:0/color": {"kind": "literal", "value": {"r": 1, "g": 0, "b": 0}},
        },
    )
    assert message(state, p, by("color", 0.5, "g")) == "color.g: 1 target; skipped 1 no value"


def test_the_changed_slots_count_as_touched(state: ShowState) -> None:
    """Like a ``set``, a change is the operator's latest action on its slots."""
    p = run(state, EMPTY, select(MH1, MH2), set_attr("pan", 0), select(MH1, PAR))
    assert handle(state, p, cast(Command, by("pan", 0))).written == {"fx-mh1:0/pan"}


# ---------------------------------------------------------------- components


def test_a_component_is_set_and_the_others_kept(state: ShowState) -> None:
    p = run(state, EMPTY, select(MH1, PAR), preset("pr-blue"))
    assert message(state, p, to("r", 0.5)) == "color.r: 2 targets"
    p = run(state, p, to("r", 0.5))
    assert values(p)["fx-mh1:0/color"] == {"kind": "literal", "value": {"r": 0.5, "g": 0, "b": 1}}
    assert values(p)["fx-par1:0/color"] == values(p)["fx-mh1:0/color"]


def test_a_component_changes_within_0_to_1_and_from_0_when_missing(state: ShowState) -> None:
    """A colour without ``w`` lets the fixture derive its white; a change of
    ``w`` starts from 0 and makes it explicit."""
    p = run(state, EMPTY, select(MH1), set_attr("color", {"r": 0.9, "g": 0.5, "b": 0}))
    p = run(state, p, by("color", 0.2, "r"), by("color", -0.6, "g"), by("color", 0.3, "w"))
    assert values(p)["fx-mh1:0/color"]["value"] == {"r": 1.0, "g": 0.0, "b": 0, "w": 0.3}


@pytest.mark.parametrize(
    ("command", "error"),
    [
        ({"type": "ADJUST_ATTRIBUTE", "attribute": "pan"},
         "ADJUST_ATTRIBUTE needs exactly one of 'delta' and 'value'"),
        ({**to("r", 0.5), "delta": 0.1},
         "ADJUST_ATTRIBUTE needs exactly one of 'delta' and 'value'"),
        (by("pan", math.nan), "delta must be a finite number"),
        (by("pan", cast(float, True)), "delta must be a finite number"),
        (by("pan", cast(float, "5")), "delta must be a finite number"),
        (by("gobo1", 1), "gobo1 is discrete and cannot be adjusted"),
        (by("pan", 1, "r"), "pan has no components"),
        ({"type": "ADJUST_ATTRIBUTE", "attribute": "pan", "value": 10},
         "pan takes a delta here: SET_ATTRIBUTE sets its value"),
        (by("color", 0.1), "color is adjusted one component at a time: r, g, b, w, a, uv"),
        (by("color", 0.1, "x"), r"a colour has no component 'x' \(r, g, b, w, a, uv\)"),
        (to("r", 1.5), r"color.r must be within 0..1, got 1.5"),
        (by("control", 1), r"control attributes cannot be programmed \(§5.5\)"),
        (by("sparkle", 1), "unknown attribute 'sparkle'"),
    ],
)  # fmt: skip
def test_invalid_adjustments_are_errors(
    state: ShowState, command: dict[str, Any], error: str
) -> None:
    p = run(state, EMPTY, select(MH1), set_attr("pan", 0))
    with pytest.raises(CommandError, match=f"^{error}$"):
        handle(state, p, cast(Command, command))


def test_nothing_selected_is_an_error(state: ShowState) -> None:
    with pytest.raises(CommandError, match=r"^nothing selected$"):
        handle(state, EMPTY, cast(Command, by("pan", 1)))


# --------------------------------------------------------------------- hosts


@pytest.fixture
def offline() -> OfflineShow:
    return OfflineShow(show_of(load_doc(APPENDIX_A)))


def lines(show: OfflineShow | LiveShow, *typed: str) -> list[Reply]:
    return [show.execute(line) for line in typed]


def test_the_console_lines_reach_the_programmer_and_the_stage(offline: OfflineShow) -> None:
    assert lines(offline, "sel group 1", "set intensity 50%", "set intensity by 10%",
                 "preset color 1", "set color.r by 50%", "set color.w 20%") == [
        Reply("2 targets selected"), Reply("intensity: 2 targets"), Reply("intensity: 2 targets"),
        Reply("Blue: 2 values on 2 targets"), Reply("color.r: 2 targets"),
        Reply("color.w: 2 targets"),
    ]  # fmt: skip
    status = offline.programmer
    assert [(v.number, v.attribute, v.value, v.preset) for v in status.values] == [
        (101, "intensity", 0.6, None),
        (102, "intensity", 0.6, None),
        (101, "color", {"r": 0.5, "g": 0, "b": 1, "w": 0.2}, None),
        (102, "color", {"r": 0.5, "g": 0, "b": 1, "w": 0.2}, None),
    ]
    head = offline.output.fixtures[0]
    assert (head.number, head.intensity, head.source["intensity"]) == (101, 0.6, "programmer")


def test_each_change_is_one_undo_step(offline: OfflineShow) -> None:
    lines(offline, "sel fixture 101", "set intensity 50%", "set intensity by 10%",
          "set intensity by 10%")  # fmt: skip
    assert offline.execute("undo") == Reply("undid: intensity: 1 target")
    assert offline.programmer.values[0].value == 0.6
    assert offline.execute("undo").ok
    assert offline.programmer.values[0].value == 0.5


def test_a_refused_change_says_why_and_changes_nothing(offline: OfflineShow) -> None:
    lines(offline, "sel fixture 101")
    version = offline.programmer.version
    assert offline.execute("set intensity by 5%") == Reply(
        "error: no selected target has intensity to change (1 not in the programmer)", ok=False
    )
    assert offline.execute("set intensity +5%") == Reply(
        "error: '+5%' has a plus sign: 'set intensity by +5%' changes intensity by 5%, "
        "'set intensity 5%' sets it",
        ok=False,
    )
    assert offline.programmer.version == version
    assert offline.programmer.values == ()


def test_submit_takes_the_typed_command(offline: OfflineShow) -> None:
    lines(offline, "sel fixture 201", "set color 1 0 0")
    result = offline.submit(cast(Command, to("b", 1)))
    assert (result.ok, result.message) == (True, "color.b: 1 target")
    assert offline.programmer.values[0].value == {"r": 1, "g": 0, "b": 1}


def eventually(condition: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_a_live_show_takes_the_lines() -> None:
    live = LiveShow(show_of(load_doc(APPENDIX_A)), output=False)
    with live:
        assert lines(live, "sel fixture 101", "set pan 10", "set pan by -25") == [
            Reply("1 target selected"), Reply("pan: 1 target"), Reply("pan: 1 target")
        ]  # fmt: skip
        eventually(lambda: [v.value for v in live.programmer.values] == [-15])


@pytest.mark.skipif(
    not hasattr(socket, "send_fds") or not Path("/proc").is_dir(),
    reason="the process tree needs descriptor passing, the harness /proc",
)
def test_busk_run_takes_them_at_its_prompt(tmp_path: Path, receiver: Receiver) -> None:
    """The session runs in the console process, so its prompt changes the
    programmer as a ``LiveShow`` does."""
    show = tmp_path / "show.json"
    show.write_text(json.dumps(localhost_route(load_doc(APPENDIX_A))))
    with BuskRun(show, sacn_port=receiver.port) as busk:
        busk.send("sel fixture 101\nset intensity 50%\nset intensity by 10%\nprogrammer\n")
        busk.wait_for("intensity: 1 target")
        busk.wait_for("  101 intensity = 0.6")
        busk.send("quit\n")
        assert busk.wait() == 0, busk.err


# ------------------------------------------------------------------ bindings


def binding_issues(command: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Validate Appendix A with ``command`` in a new binding."""
    doc = load_doc(APPENDIX_A)
    doc["bindings"].append(
        {"id": "b9", "surfaceId": "s-midi", "input": {"kind": "midiNote", "channel": 1, "note": 9},
         "action": {"kind": "command", "command": command}}
    )  # fmt: skip
    _, issues = validate_show(json.dumps(doc))
    return [(issue.severity, issue.path, issue.message) for issue in issues]


@pytest.mark.parametrize("command", [by("intensity", 0.1), by("color", -0.1, "uv"), to("w", 1)])
def test_a_binding_can_adjust(command: dict[str, Any]) -> None:
    assert binding_issues(command) == []


@pytest.mark.parametrize(
    ("command", "path", "error"),
    [
        (by("sparkle", 1), ".attribute", "Unknown attribute 'sparkle'"),
        (by("control", 1), ".attribute",
         "Control attributes cannot be used in programmer values"),
        ({**by("pan", 1), "value": 2}, "",
         "ADJUST_ATTRIBUTE needs exactly one of 'delta' and 'value'"),
        (by("color", 1), "", "color is adjusted one component at a time: r, g, b, w, a, uv"),
        (to("r", 2), "", "color.r must be within 0..1, got 2"),
    ],
)  # fmt: skip
def test_a_bindings_adjustment_is_checked(command: dict[str, Any], path: str, error: str) -> None:
    assert binding_issues(command) == [("error", f"bindings[3].action.command{path}", error)]


def test_a_bindings_adjustment_is_strict() -> None:
    issues = binding_issues({**by("color", 1, "x")})
    assert [(severity, path) for severity, path, _ in issues] == [
        ("error", "bindings[3].action.command.component")
    ]
