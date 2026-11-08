"""The console: execute, scripts, source, rendering, defaults, the prompt (phase-3-plan §5.10)."""

from __future__ import annotations

import copy
import json
import signal
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from builders import APPENDIX_A, load_doc, show_of
from busk import LiveShow, OfflineShow, ScriptError, load_show
from busk.console.console import Console, interact
from busk.console.parser import SubmitAll
from busk.console.prompt import Editing
from busk.model.show import Show
from busk.session.library import ProfileLibrary, builtin_directory
from session_harness import Live

LIBRARY = ProfileLibrary()


@pytest.fixture
def live() -> Live:
    return Live(load_doc(APPENDIX_A))


@pytest.fixture
def console(live: Live) -> Console:
    return Console(live.session, LIBRARY, status=lambda: "GM 100% | BO off")


def run(console: Console, *lines: str) -> list[str]:
    """Execute lines; every one must succeed. Returns their printed text."""
    texts = []
    for line in lines:
        reply = console.execute(line)
        assert reply.ok, (line, reply.text)
        texts.append(reply.text)
    return texts


def test_a_route_can_be_switched_off_on_and_deleted_each_in_one_undo_step(
    console: Console,
) -> None:
    listed = "r1  U1 → sACN 1 multicast eth0"
    assert run(console, "route r1 off", "list routes") == [
        "switched route r1 off",
        f"{listed} (disabled)",
    ]
    assert run(console, "undo", "list routes") == ["undid: switched route r1 off", listed]
    assert run(console, "route r1 off", "route r1 on", "list routes") == [
        "switched route r1 off",
        "switched route r1 on",
        listed,
    ]
    assert run(console, "delete route r1", "list routes") == ["deleted route r1", "no routes"]
    assert run(console, "undo", "list routes") == ["undid: deleted route r1", listed]


def test_list_routes_marks_every_kind_of_disabled_route(console: Console) -> None:
    run(
        console,
        "route add 1 artnet 0.0.1",
        "route add 1 dmxusb enttecPro /dev/ttyUSB0",
    )
    for route in console.session.show["output"]["routes"]:
        run(console, f"route {route['id']} off")
    lines = run(console, "list routes")[0].splitlines()
    assert len(lines) == 3
    assert all(line.endswith(" (disabled)") for line in lines)


def test_a_route_cannot_come_on_where_it_would_clash(console: Console) -> None:
    """A disabled route is not checked, so the universe it sent may be taken
    meanwhile. busk refuses the line that would send it twice."""
    run(console, 'universe add 2 "Side"', "route r1 off", "route add 2 sacn 1")
    reply = console.execute("route r1 on")
    assert not reply.ok
    assert "already sent by route" in reply.text
    assert run(console, "list routes")[0].startswith("r1  U1 → sACN 1 multicast eth0 (disabled)")


def test_a_universe_takes_the_same_route_once(console: Console) -> None:
    """On or off, a second copy would send the same: busk names the first."""
    run(console, "route add 1 artnet 0.0.1", "route add 1 dmxusb enttecPro /dev/ttyUSB0")
    routes = console.session.show["output"]["routes"]
    artnet, dmx = routes[1]["id"], routes[2]["id"]
    run(console, f"route {artnet} off")
    for line, first in (
        ("route add 1 sacn 1 multicast eth0", "r1"),
        ("route add 1 artnet 0.0.1", artnet),
        ("route add 1 artnet 0.0.1 broadcast eth0", artnet),
        ("route add 1 dmxusb enttecPro /dev/ttyUSB0 hz 40", dmx),
    ):
        reply = console.execute(line)
        assert reply.text == f"error: the same as route {first} of universe 1"
        assert len(console.session.show["output"]["routes"]) == 3
    run(
        console,
        "route add 1 sacn 1 unicast 10.0.0.50",
        "route add 1 artnet 0.0.2",
        "route add 1 dmxusb dmxking /dev/ttyUSB1",
    )


def test_a_universe_freed_of_its_routes_and_fixtures_is_deleted_plainly(console: Console) -> None:
    run(console, 'universe add 2 "Side"', "route add 2 sacn 2", "fixture 201 patch 2.1")
    route = console.session.show["output"]["routes"][-1]["id"]
    assert not console.execute("delete universe 2").ok
    run(console, "fixture 201 patch none")
    assert not console.execute("delete universe 2").ok  # the route still sends it
    run(console, f"delete route {route}", "delete universe 2")
    assert [u["number"] for u in console.session.show["universes"]] == [1]


def test_commands_print_their_result(console: Console) -> None:
    assert run(console, "sel group 1", "set pan 10", "clear") == [
        "2 targets selected",
        "pan: 2 targets",
        "programmer cleared",
    ]
    assert run(console, "fader 3 1") == [""]  # performance commands print nothing


def test_errors_print_with_every_issue_path(console: Console) -> None:
    reply = console.execute('group 2 members [{"fixtureId": "nope", "element": 0}]')
    assert not reply.ok
    assert reply.text.splitlines() == [
        'error: set groups[1].members to [{"fixtureId": "nope", "element": 0}]: '
        "rejected, the show would not be valid",
        "  groups[1].members[0].fixtureId: Unknown fixture 'nope'",
    ]
    reply = console.execute("sel group 9")
    assert (reply.ok, reply.text) == (False, "error: no group 9")


def test_new_warnings_print_after_the_result(console: Console) -> None:
    reply = console.execute("fixture 201 patch 1.2")
    assert reply.ok
    assert reply.text.splitlines() == [
        "patched fixture 201 at 1.2",
        "warning fixtures[2].patch.address: Channels 2–4 overlap fixture 'MH 1' (fixtures[0])",
    ]


def test_record_slot_defaults_and_list_rendering(console: Console, live: Live) -> None:
    run(console, "sel group 2", "set intensity 1", 'record slot 2 "Wash"')
    playback = next(p for p in live.session.show["playbacks"] if p["number"] == 2)
    assert "exclusivity" not in playback
    assert (playback["buttons"], playback["flash"], playback["releaseTime"]) == (
        ["toggle", "flash"],
        {"level": 1.0, "includeLtp": True},
        1.0,
    )
    cue_list = next(cl for cl in live.session.show["cueLists"] if cl["id"] == playback["cueListId"])
    assert (cue_list["mode"], cue_list["tracking"], cue_list["wrap"], cue_list["releaseAtEnd"]) == (
        "sequence",
        False,
        False,
        False,
    )
    assert run(console, "list pages") == [
        "*   1  Main                 1:1 2:2 3:3 4:- 5:- 6:6 7:- 8:-"
    ]
    assert run(console, "list playbacks")[0].splitlines()[1] == (
        "    2  Wash                 cue list 2, band 50, master fader"
    )
    assert (
        run(console, "list cuelists")[0].splitlines()[1] == "    2  Wash                 1 'Wash'"
    )


def test_queries(console: Console, live: Live) -> None:
    run(console, "sel fixture 101", "set color preset color 1", "set pan 12.5")
    assert run(console, "programmer") == [
        "selection: 101\nblind: off\nhighlight: off\nfade: 0 s\n"
        "  101 color = preset color 1 'Blue'\n  101 pan = 12.5"
    ]
    assert run(console, "list fixtures")[0].splitlines() == [
        "  101  MH 1                 Generic Spot 16ch / 16ch  1.1",
        "  102  MH 2                 Generic Spot 16ch / 16ch  1.17",
        "  201  Par 1                RGB Par 3ch / 3ch  1.101",
    ]
    assert run(console, "list groups")[0].splitlines()[0] == "    1  Moving Heads         101, 102"
    assert run(console, "list routes") == ["r1  U1 → sACN 1 multicast eth0"]
    run(console, "route add 1 dmxusb enttecPro /dev/ttyUSB0 hz 30")
    assert run(console, "list routes")[0].splitlines()[1:] == [
        "r-000000000001  U1 → DMX-USB enttecPro /dev/ttyUSB0 30 Hz"
    ]
    assert (
        run(console, "list bindings")[0].splitlines()[0] == "b1  MIDI Controller cc 1 0 → fader 1"
    )
    assert run(console, "list surfaces") == [
        "s-midi  midi 'MIDI Controller' device 'nanoKONTROL2', soft pickup"
    ]
    assert run(console, "status") == ["GM 100% | BO off"]
    info = run(console, "info")[0].splitlines()
    assert info[0] == "show: Club Night (show-01)"
    assert (
        info[2]
        == "1 universe, 3 fixtures, 2 groups, 3 presets, 3 cue lists, 3 playbacks, 3 bindings"
    )
    assert info[4] == "programmer: 1 selected, 2 values, blind off"
    assert (
        "Generic Spot 16ch (Generic, revision 1): 16ch" in run(console, "library")[0].splitlines()
    )
    assert run(console, "help")[0].splitlines()[0].strip().startswith("sel <targets>")


def test_programmer_prints_its_fade_time(console: Console) -> None:
    run(console, "fade 2.5")
    assert run(console, "programmer") == [
        "selection: nothing\nblind: off\nhighlight: off\nfade: 2.5 s"
    ]


def test_list_cues_shows_timing_and_triggers(console: Console) -> None:
    assert run(console, "list cues 1")[0].splitlines() == [
        "    1  Verse                time 2 easeInOut  go",
        "    2  Chorus               time 0.5/1  go",
    ]
    run(
        console,
        "cue 1/2 time 3/1 delay 0/2 bezier 0.25 0.1 0.25 1",
        "cue 1/2 time color 3 delay 1 easeIn",
        "cue 1/2 time position 4",
        "cue 1/2 follow 0.5",
        "cue 1/1 wait 8",
        'cue 1/1 name ""',
    )
    assert run(console, "list cues 1")[0].splitlines() == [
        "    1                       time 2 easeInOut  wait 8",
        "    2  Chorus               time 3/1 delay 0/2 bezier 0.25 0.1 0.25 1,"
        " color 3 delay 1 easeIn, position 4  follow 0.5",
    ]
    reply = console.execute("list cues 7")
    assert (reply.ok, reply.text) == (False, "error: no cue list 7")


def test_list_masters_shows_kind_level_and_tempo(console: Console, live: Live) -> None:
    before = ["Grand Master         grand   100%", "Speed 1              speed    50%  120 BPM ×1"]
    assert run(console, "list masters")[0].splitlines() == before  # the show's: no engine yet
    run(console, "bpm 128", 'master "Speed 1" 1', "gm 80%")
    live.tick()
    assert run(console, "list masters")[0].splitlines() == [
        "Grand Master         grand    80%",
        "Speed 1              speed   100%  128 BPM ×4",
    ]


def test_a_script_stops_at_its_first_error(console: Console, live: Live, tmp_path: Path) -> None:
    script = tmp_path / "build.busk"
    script.write_text("sel group 1\nset pan 5\nsel group 9\nset pan 6\n")
    written: list[str] = []
    assert not console.run_script(script, written.append)
    assert written == [
        "2 targets selected",
        "pan: 2 targets",
        f"{script}:3: sel group 9",
        "error: no group 9",
    ]
    assert dict(live.session.programmer.values)["fx-mh1:0/pan"] == {"kind": "literal", "value": 5}


def test_source_runs_a_file_and_nesting_is_bounded(console: Console, tmp_path: Path) -> None:
    inner = tmp_path / "inner.busk"
    inner.write_text("sel group 2\n")
    outer = tmp_path / "outer.busk"
    outer.write_text(f"source {inner}\nset intensity 1\n")
    assert run(console, f"source {outer}") == ["1 target selected\nintensity: 1 target"]
    loop = tmp_path / "loop.busk"
    loop.write_text(f"source {loop}\n")
    reply = console.execute(f"source {loop}")
    assert not reply.ok
    assert reply.text.endswith("error: source nests more than 8 deep")
    missing = console.execute(f"source {tmp_path / 'nope.busk'}")
    assert not missing.ok
    assert "cannot read" in missing.text


def test_save_and_quit(console: Console, live: Live, tmp_path: Path) -> None:
    assert console.execute("save").text == "error: no file to save to: give a path"
    target = tmp_path / "out.show"
    assert run(console, f"save {target}") == [f"saved {target}"]
    assert target.exists()
    assert not live.session.dirty
    run(console, "quit")
    assert console.quit_requested


# ------------------------------------------------------------------- prompt


class answers:
    """Scripted prompt answers; an exception class is raised at its turn."""

    def __init__(self, *items: str | type[BaseException]) -> None:
        self._items = list(items)

    def __next__(self) -> str:
        item = self._items.pop(0)
        if isinstance(item, type):
            raise item()
        return item


def typing(monkeypatch: pytest.MonkeyPatch, *lines: str) -> None:
    """What is on the prompt's line at each Ctrl+C, in turn."""
    on_line = iter(lines)
    monkeypatch.setattr(Editing, "typed", lambda self: next(on_line))


def test_ctrl_c_on_a_typed_line_clears_it_and_keeps_running(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    typing(monkeypatch, "set pa")
    feed = answers("sel group 1", KeyboardInterrupt, "set pan 1", "quit")
    written: list[str] = []
    interact(console, ask=lambda prompt: next(feed), write=written.append)
    assert written == ["2 targets selected", "", "pan: 2 targets"]
    assert console.quit_requested


def test_ctrl_c_twice_on_an_empty_line_quits(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    typing(monkeypatch, "", "")
    feed = answers("sel group 1", KeyboardInterrupt, KeyboardInterrupt)
    written: list[str] = []
    interact(console, ask=lambda prompt: next(feed), write=written.append)
    assert written == ["2 targets selected", "", "press Ctrl+C again to quit", ""]
    assert console.quit_requested


def test_only_two_ctrl_c_in_a_row_quit(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    """A line, or a Ctrl+C that clears one, in between: the next Ctrl+C warns again."""
    typing(monkeypatch, "", "", "sel gr", "", "")
    feed = answers(
        KeyboardInterrupt, "sel group 1", KeyboardInterrupt, KeyboardInterrupt, KeyboardInterrupt,
        KeyboardInterrupt,
    )  # fmt: skip
    written: list[str] = []
    interact(console, ask=lambda prompt: next(feed), write=written.append)
    warning = ["", "press Ctrl+C again to quit"]
    assert written == [*warning, "2 targets selected", *warning, "", *warning, ""]
    assert console.quit_requested


def test_ctrl_c_twice_with_unsaved_edits_offers_to_save(
    console: Console, live: Live, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    typing(monkeypatch, "", "")
    live.session._path = tmp_path / "show.json"
    feed = answers('rename show "Edited"', KeyboardInterrupt, KeyboardInterrupt, "y")
    written: list[str] = []
    interact(console, ask=lambda prompt: next(feed), write=written.append)
    assert written[-1] == f"saved {tmp_path / 'show.json'}"
    assert not live.session.dirty


def test_quit_with_unsaved_edits_offers_to_save(
    console: Console, live: Live, tmp_path: Path
) -> None:
    live.session._path = tmp_path / "show.json"
    feed = answers('rename show "Edited"', "quit", "maybe", "y")
    prompts: list[str] = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return next(feed)

    written: list[str] = []
    interact(console, ask=ask, write=written.append)
    assert prompts[-2:] == [f"save unsaved edits to {tmp_path / 'show.json'}? [y/n] "] * 2
    assert written[-1] == f"saved {tmp_path / 'show.json'}"
    assert not live.session.dirty


def test_ctrl_d_quits_and_declining_keeps_the_edits_unsaved(
    console: Console, live: Live, tmp_path: Path
) -> None:
    live.session._path = tmp_path / "show.json"
    feed = answers('rename show "Edited"', EOFError, "n")
    interact(console, ask=lambda prompt: next(feed), write=lambda text: None)
    assert live.session.dirty
    assert not (tmp_path / "show.json").exists()


def test_ctrl_c_during_a_command_is_held_until_it_finishes(
    console: Console, live: Live, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interrupt inside an edit must not split it (engine and session apart)."""
    submit = live.session.submit

    def interrupted_submit(command: Any, origin: Any = None) -> Any:
        signal.raise_signal(signal.SIGINT)  # Ctrl+C in the middle of the command
        return submit(command, origin)

    monkeypatch.setattr(live.session, "submit", interrupted_submit)
    reply = console.execute('rename show "Edited"')
    assert reply.ok
    assert live.session.show["meta"]["title"] == "Edited"
    assert console.interrupted
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


def test_a_script_stops_when_interrupted(
    console: Console, live: Live, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "long.busk"
    script.write_text("sel group 1\nset pan 1\n")
    submit = live.session.submit

    def interrupted_submit(command: Any, origin: Any = None) -> Any:
        signal.raise_signal(signal.SIGINT)
        return submit(command, origin)

    monkeypatch.setattr(live.session, "submit", interrupted_submit)
    written: list[str] = []
    assert not console.run_script(script, written.append)
    assert written == ["2 targets selected", f"{script}:1: interrupted"]


# ------------------------------------------------------------ Phase 5 effects


def test_a_library_template_is_embedded_once(console: Console, live: Live) -> None:
    assert run(console, "sel group 1", 'effect add "Circle"', 'effect add "circle" hz 2') == [
        "2 targets selected",
        "added effect template 'Circle'\nadded effect 'fx1' on 2 targets",
        "added effect 'fx2' on 2 targets",
    ]
    assert [t["name"] for t in live.session.show["effects"]] == ["Pulse", "Circle"]
    # Two undo steps for the first line: the effect, then the template.
    run(console, "undo", "undo")
    assert [e["id"] for e in live.session.programmer.effects] == []
    assert [t["name"] for t in live.session.show["effects"]] == ["Pulse", "Circle"]
    run(console, "undo")
    assert [t["name"] for t in live.session.show["effects"]] == ["Pulse"]


def test_a_two_command_line_reports_the_failing_command(console: Console, live: Live) -> None:
    run(console, "sel group 1")
    reply = console.execute('effect add "Flicker" size 2')  # a multiply layer needs size ≤ 1
    assert not reply.ok
    assert reply.text.splitlines()[:2] == [
        "added effect template 'Flicker'",
        "error: effect 'fx1': An effect with a multiply layer needs a size within 0..1, got 2",
    ]
    assert live.session.programmer.effects == ()


def test_effects_are_listed(console: Console, live: Live) -> None:
    run(
        console,
        "sel group 1",
        'effect add "Circle" bpm x 0.5 size 15',
        "sel 201",
        'effect add "Rainbow" id rb hz 0.25',
    )
    pulse = {
        "id": "ei-9",
        "templateId": "ef-pulse",
        "targets": {"kind": "group", "groupId": "g-par"},
        "rate": {"kind": "hz", "value": 1},
        "direction": "forward",
        "size": 0.5,
        "phase": {"start": 0, "end": 0},
        "groups": 1,
        "blocks": 1,
        "wings": 1,
    }
    assert live.session.submit({"type": "ADD_EFFECT", "effect": pulse}).ok  # type: ignore[typeddict-item]
    assert run(console, "list effects")[0].splitlines() == [
        "Pulse                intensity multiply sine",
        "Circle               pan add sine, tilt add sine +90°",
        "Rainbow              color fade 3 colours",
    ]
    assert run(console, "programmer")[0].splitlines()[4:] == [
        "  effect fx1 'Circle' on 101, 102, bpm 'Speed 1' ×0.5, size 15",
        "  effect rb 'Rainbow' on 201, 0.25 Hz, size 1",
        "  effect ei-9 'Pulse' on group 2, 1 Hz, size 0.5",
    ]
    library = run(console, "library")[0].splitlines()
    assert "effect Circle: pan add sine, tilt add sine +90° (size 20)" in library
    assert "effect Wave: intensity absolute sine (low 0 high 1)" in library
    assert "effect Rainbow: color fade 3 colours (phase 0 360)" in library


def test_list_cues_counts_effects(console: Console) -> None:
    assert run(console, "list cues 20") == ["    1  Pulse                time 0  go  1 effect"]
    assert not any(line.endswith("effect") for line in run(console, "list cues 1")[0].splitlines())


def test_record_slot_of_an_effect_gives_a_size_fader(console: Console, live: Live) -> None:
    run(console, "sel group 1", 'effect add "Circle"', 'record slot 2 "Circle"')
    show = live.session.show
    playback = next(p for p in show["playbacks"] if p["name"] == "Circle")
    cues = next(cl for cl in show["cueLists"] if cl["id"] == playback["cueListId"])["cues"]
    assert playback["fader"] == "size"
    assert [(cue["entries"], cue["effects"][0]["targets"]) for cue in cues] == [
        ([], {"kind": "group", "groupId": "g-mh"})
    ]


def test_a_line_of_commands_stops_at_the_first_failure(
    console: Console, live: Live, monkeypatch: pytest.MonkeyPatch
) -> None:
    failing = {"type": "SET", "path": ["groups", {"id": "g-nope"}, "name"], "value": "X"}
    select = {"type": "SELECT", "targets": {"kind": "group", "groupId": "g-mh"}, "mode": "replace"}
    action = SubmitAll((failing, select), notes=("a note",))  # type: ignore[arg-type]
    monkeypatch.setattr("busk.console.console.parse", lambda line, context: action)
    reply = console.execute("anything")
    assert not reply.ok
    assert reply.text.splitlines()[0] == "a note"
    assert reply.text.splitlines()[1].startswith("error: ")
    assert live.session.programmer.selection == ()  # the second command never ran


# ------------------------------------------------------------------ Phase 6


def test_list_pages_marks_the_engines_page_and_record_slot_records_on_it(
    console: Console, live: Live
) -> None:
    run(console, 'page add 2 "Washes"', "page 2 slot 2 playback 3")
    assert run(console, "list pages")[0].splitlines() == [
        "*   1  Main                 1:1 2:- 3:3 4:- 5:- 6:6 7:- 8:-",
        "    2  Washes               1:- 2:3",
    ]
    run(console, "page 2")
    live.tick()
    assert run(console, "list pages")[0].splitlines() == [
        "    1  Main                 1:1 2:- 3:3 4:- 5:- 6:6 7:- 8:-",
        "*   2  Washes               1:- 2:3",
    ]
    run(console, "sel group 2", "set intensity 1")
    assert run(console, 'record slot 1 "Wash"') == ["recorded slot 2.1: playback 7 'Wash'"]
    page = next(p for p in live.session.show["pages"] if p["number"] == 2)
    assert page["slots"][0] is not None


def test_list_surfaces_shows_kind_port_or_device_and_pickup(console: Console) -> None:
    run(
        console,
        'surface add osc "TouchOSC"',
        'surface add osc "Lemur" port 9000 feedback 10.0.0.9:9001',
        'surface add osc "Mixer" port 9100 feedback mixer.local',
        'surface add osc "Pad" port 9200 feedback :9201',
        'surface add web "Phone" port 8081 on 127.0.0.1',
        'surface "TouchOSC" pickup soft',
    )
    assert run(console, "list surfaces")[0].splitlines() == [
        "s-midi  midi 'MIDI Controller' device 'nanoKONTROL2', soft pickup",
        "s-000000000001  osc 'TouchOSC' port 8000, feedback to the sender, soft pickup",
        "s-000000000002  osc 'Lemur' port 9000, feedback to 10.0.0.9:9001, jump pickup",
        "s-000000000003  osc 'Mixer' port 9100, feedback to mixer.local at the sender's port, "
        "jump pickup",
        "s-000000000004  osc 'Pad' port 9200, feedback to the sender at port 9201, jump pickup",
        "s-000000000005  web 'Phone' port 8081 on 127.0.0.1",
    ]


def test_list_bindings_names_masters_and_pages_and_shows_feedback(console: Console) -> None:
    run(
        console,
        'page add 2 "Washes"',
        'surface add osc "TouchOSC"',
        'feedback "MIDI Controller" cc 1 0 motor',
        'bind "MIDI Controller" note 1 40 page 2 led cc 1 64',
        'bind "MIDI Controller" cc 1 61 page -1',
        'bind "MIDI Controller" cc 1 62 page +1 led',
        'bind "MIDI Controller" clock tap',
        'bind "MIDI Controller" cc 1 16 fader playback 3',
        'bind "MIDI Controller" cc 1 42 blackout momentary',
        'bind "TouchOSC" osc "/1/fader1" fader 1 display osc "/1/label1"',
    )
    assert run(console, "list bindings")[0].splitlines() == [
        "b1  MIDI Controller cc 1 0 → fader 1 [motor]",
        "b2  MIDI Controller note 1 32 → button 1 1",
        "b3  MIDI Controller cc 1 7 → master 'Grand Master'",
        "b-000000000003  MIDI Controller note 1 40 → page 2 'Washes' [led cc 1 64]",
        "b-000000000004  MIDI Controller cc 1 61 → page -1",
        "b-000000000005  MIDI Controller cc 1 62 → page +1 [led]",
        "b-000000000006  MIDI Controller clock → tap 'Speed 1'",
        "b-000000000007  MIDI Controller cc 1 16 → fader playback 3 'Blue'",
        "b-000000000008  MIDI Controller cc 1 42 → blackout momentary",
        'b-000000000009  TouchOSC osc "/1/fader1" → fader 1 [display osc "/1/label1"]',
    ]


# ------------------------------------------------------------------ Phase 7 (phase-7-plan §5.22)


def test_park_unpark_and_list_park(console: Console, live: Live) -> None:
    assert run(console, "list park") == ["nothing is parked"]
    assert run(console, "park fixture 201 intensity 0", "park 102 color 1 0 0") == [
        "parked fixture 201 intensity at 0",
        "parked 102 color at 1 0 0",
    ]
    assert run(console, "list park")[0].splitlines() == ["201 intensity 0", "102 color 1 0 0"]
    run(console, "fader 3 1")  # Blue on the heads and the par
    live.tick()
    assert live.lanes("fx-mh2", "color") == [
        1.0,
        0.0,
        0.0,
        pytest.approx(float("nan"), nan_ok=True),
    ]
    assert run(console, "unpark all", "list park") == [
        "unparked everything (2 parked)",
        "nothing is parked",
    ]
    live.tick()  # MH 2 is back under Blue, mid-fade as MH 1 is
    assert live.lanes("fx-mh2", "color")[:3] == live.lanes("fx-mh1", "color")[:3]
    assert live.lanes("fx-mh1", "color")[:3] != [1.0, 0.0, 0.0]
    assert run(console, "undo") == ["undid: unparked everything (2 parked)"]


def test_limits_and_the_strobe_cap_reach_the_engine(console: Console, live: Live) -> None:
    assert run(console, "fixture 101 thru 102 limits tilt -90 10", "safety strobe 3") == [
        "limited fixture 101 thru 102: tilt -90° to 10°",
        "strobe cap 3 Hz",
    ]
    run(console, "sel group 1", "set tilt 45", "set strobeRate 10")
    live.tick()
    assert live.lanes("fx-mh1", "tilt") == [10.0]
    assert live.lanes("fx-mh2", "strobeRate") == [3.0]
    assert live.session.show["fixtures"][0]["limits"] == {"tilt": (-90.0, 10.0)}
    assert run(console, "fixture 101 limits none", "safety strobe off") == [
        "removed the limits of fixture 101",
        "removed the strobe cap",
    ]
    live.tick()
    assert live.lanes("fx-mh1", "tilt") == [45.0]
    assert live.lanes("fx-mh2", "tilt") == [10.0]
    assert live.lanes("fx-mh2", "strobeRate") == [10.0]


def test_one_limit_goes_the_others_stay_and_undo_brings_it_back(
    console: Console, live: Live
) -> None:
    def limits() -> Any:
        return live.session.show["fixtures"][0].get("limits")

    run(console, "fixture 101 limits pan -90 90", "fixture 101 limits intensity 50%")
    whole = limits()
    assert set(whole) == {"tilt", "pan", "intensityMax"}
    assert run(console, "fixture 101 limits pan none") == ["removed the pan limit of fixture 101"]
    assert set(limits()) == {"tilt", "intensityMax"}
    assert run(console, "undo") == ["undid: removed the pan limit of fixture 101"]
    assert limits() == whole
    run(console, "fixture 101 limits pan none", "fixture 101 limits intensity none")
    assert set(limits()) == {"tilt"}
    run(console, "fixture 101 limits tilt none")
    assert limits() is None  # the last one takes `limits` with it: no empty one stays
    run(console, "undo")
    assert set(limits()) == {"tilt"}


def test_thru_takes_a_limit_from_those_that_have_it_in_one_undo_step(console: Console) -> None:
    def limits() -> list[Any]:
        return [f.get("limits") for f in console.session.show["fixtures"]]

    run(console, "fixture 102 limits tilt -90 10", "fixture 102 limits pan -90 90")
    before = limits()
    assert run(console, "fixture 101 thru 201 limits tilt none") == [
        "removed the tilt limit of fixture 101 thru 201"
    ]
    assert limits() == [None, {"pan": (-90.0, 90.0)}, None]
    assert run(console, "undo") == ["undid: removed the tilt limit of fixture 101 thru 201"]
    assert limits() == before


def test_orientation_over_a_span_is_one_undo_step(console: Console) -> None:
    def orientations() -> list[dict[str, Any]]:
        return [dict(f["orientation"]) for f in console.session.show["fixtures"]]

    before = orientations()
    assert run(console, "fixture 101 thru 201 orientation.panOffset 30") == [
        "oriented fixture 101 thru 201: panOffset 30°"
    ]
    assert orientations() == [{**o, "panOffset": 30} for o in before]  # the other keys stay
    assert run(console, "undo") == ["undid: oriented fixture 101 thru 201: panOffset 30°"]
    assert orientations() == before
    assert not console.execute("undo").ok


def test_thru_covers_what_is_between_its_ends_and_no_more(console: Console) -> None:
    run(console, "fixture 102 thru 101 orientation.tiltOffset 5")
    fixtures = console.session.show["fixtures"]
    assert [f["orientation"]["tiltOffset"] for f in fixtures] == [5, 5, 0]


def test_orientation_over_a_span_reaches_the_output(console: Console, live: Live) -> None:
    """MH 2 hangs inverted, so with the same pan its channel differs from MH 1's."""
    run(console, "sel group 1", "set pan 22.5")
    live.tick()
    assert live.universe()[0] != live.universe()[16]
    run(console, "fixture 101 thru 102 orientation.invertPan true")
    live.tick()
    assert live.universe()[0] == live.universe()[16]


def test_a_fixture_that_cannot_take_it_refuses_the_whole_line() -> None:
    """A swap needs pan and tilt, so a scanner with pan alone stops the span."""
    doc = load_doc(APPENDIX_A)
    scanner = json.loads(json.dumps(doc["profiles"][0]))
    scanner["id"], scanner["name"] = "p-scanner", "Scanner"
    tilt = next(c for c in scanner["modes"][0]["channels"] if c["attribute"] == "tilt")
    tilt["attribute"] = "frost"
    doc["profiles"].append(scanner)
    doc["fixtures"][1]["profileId"] = "p-scanner"
    del doc["fixtures"][0]["limits"]
    console = Console(Live(doc).session, LIBRARY, status=lambda: "")

    reply = console.execute("fixture 101 thru 102 orientation.swapPanTilt true")

    assert not reply.ok
    assert "Swapping pan and tilt needs both" in reply.text
    assert not any(f["orientation"]["swapPanTilt"] for f in console.session.show["fixtures"])
    assert not console.execute("undo").ok


def test_a_limit_removed_leaves_the_engine_too(console: Console, live: Live) -> None:
    run(console, "fixture 101 limits tilt -90 10", "sel fixture 101", "set tilt 45")
    live.tick()
    assert live.lanes("fx-mh1", "tilt") == [10.0]
    run(console, "fixture 101 limits tilt none")
    live.tick()
    assert live.lanes("fx-mh1", "tilt") == [45.0]


def test_a_location_goes_and_undo_brings_it_back(console: Console, live: Live) -> None:
    def location() -> Any:
        return live.session.show["fixtures"][0].get("location")

    place = {"x": 1, "y": 2, "z": 3, "rx": 0, "ry": 0, "rz": 0}
    assert not console.execute("fixture 101 location none").ok
    run(console, f"fixture 101 location {json.dumps(place)}")
    assert location() == place
    assert run(console, "fixture 101 location none") == ["removed the location of fixture 101"]
    assert location() is None
    assert run(console, "undo") == ["undid: removed the location of fixture 101"]
    assert location() == place
    reply = console.execute("fixture 102 location none")
    assert (reply.ok, reply.text) == (False, "error: fixture 102 has no location")


LONG = "7" * 5000  # past what int reads
TOO_LONG = (
    "route add 1 artnet 0.0.{n}",
    "route add 1 sacn {n}",
    'surface add osc "Lemur" port {n}',
    'surface add osc "Lemur" feedback pad:{n}',
    'bind "nanoKONTROL2" cc 1 1 page {n}',
    'bind "nanoKONTROL2" cc 1 1 page +{n}',
    'bind "nanoKONTROL2" cc 1 1 page -{n}',
    "cue {n}",
    "cue 10/{n}",
    "delete cue 10/{n}",
    "playback 1 goto {n}",
    "goto 1 {n}",
    'goto 1 "{n}"',
    "record slot {n}",
    "record slot {n}.1",
    "record slot 2.{n}",
    "fade {n}",
    "fixture 101 orientation.panOffset {n}",
)


def too_long(template: str) -> Any:
    """A row of the test below: the error names the column of the word."""
    column = template.rindex(" ", 0, template.index("{n}")) + 2
    error = f"number too long at column {column}: at most 300 digits"
    return pytest.param(template.format(n=LONG), error, id=template)


@pytest.mark.parametrize(
    ("line", "error"),
    [
        *(too_long(template) for template in TOO_LONG),
        ('rename fixture 101 "back\\slash"', "bad escape in a quote at column 25"),
        ('set "\\q"', "bad escape in a quote at column 6"),
        ('rename fixture 101 "tab\there"', "control character in a quote at column 24"),
        (
            "route add 1 artnet 0.0.²",
            "expected an Art-Net port address as net.sub.universe, got '0.0.²'",
        ),
        ('bind "nanoKONTROL2" cc 1 1 page ²', "expected +N, -N or a page number, got '²'"),
        ('surface add osc "Lemur" port ²', "expected a port (1–65535), got '²'"),
        ("fixture 101 thru 102 patch 1.200", "expected limits or orientation.<key>, got 'patch'"),
        ('fixture 101 thru 102 name "x"', "expected limits or orientation.<key>, got 'name'"),
        (
            'fixture add 300 "RGB Par 3ch" mode 3ch at 1.511',
            "fixture 300 would end at channel 513, past channel 512",
        ),
        (
            'fixture add 300 thru 303 "RGB Par 3ch" mode 3ch at 1.503',
            "fixture 300–303 would end at channel 514, past channel 512",
        ),
        (
            'fixture add 300 thru 303 "RGB Par 3ch" mode 3ch at 1.513',
            "expected a channel from 1 to 512, got 513",
        ),
        (
            'fixture add 300 "RGB Par 3ch" mode 3ch at 1.0',
            "expected a channel from 1 to 512, got 0",
        ),
        ("fixture 201 patch 1.511", "fixture 201 would end at channel 513, past channel 512"),
        ("fixture 201 patch 1.512", "fixture 201 would end at channel 514, past channel 512"),
        ("fixture 201 patch 1.513", "expected a channel from 1 to 512, got 513"),
        ("fixture 201 number 101", "fixture 101 exists"),
        ("fixture 201 number 0", "fixtures are numbered from 1"),
        ("fixture 201 number -5", "fixtures are numbered from 1"),
        ("fixture 201 number x", "expected a fixture number, got 'x'"),
        ("fixture 201 number 300 now", "unexpected 'now'"),
        ("universe 1 number 0", "universes are numbered from 1"),
        ("universe 1 number x", "expected a universe number, got 'x'"),
        ('fixture add 0 "RGB Par 3ch" mode 3ch', "fixtures are numbered from 1"),
        ('fixture add -5 "RGB Par 3ch" mode 3ch', "fixtures are numbered from 1"),
        ('fixture add -5 thru 5 "RGB Par 3ch" mode 3ch', "fixtures are numbered from 1"),
        ("universe add 0", "universes are numbered from 1"),
        ("universe add -1", "universes are numbered from 1"),
        (
            "route add 1 dmxusb enttecPro /dev/ttyUSB0 hz 0",
            "expected a refresh rate from 1 to 40 Hz, got 0",
        ),
        (
            "route add 1 dmxusb enttecPro /dev/ttyUSB0 hz -1",
            "expected a refresh rate from 1 to 40 Hz, got -1",
        ),
        (
            "route add 1 dmxusb enttecPro /dev/ttyUSB0 hz 40.5",
            "expected a refresh rate from 1 to 40 Hz, got 40.5",
        ),
        (
            "route add 1 dmxusb enttecPro /dev/ttyUSB0 hz 1000",
            "expected a refresh rate from 1 to 40 Hz, got 1000",
        ),
        ("route add 1 sacn 0", "expected an sACN universe from 1 to 63999, got 0"),
        ("route add 1 sacn -1", "expected an sACN universe from 1 to 63999, got -1"),
        ("route add 1 sacn 64000", "expected an sACN universe from 1 to 63999, got 64000"),
        ("group 1 number 2", "group 2 exists"),
        ("cuelist 1 number 10", "cue list 10 exists"),
        ("playback 1 number 3", "playback 3 exists"),
        ("preset color 1 number 2", "preset color 2 exists"),
        ("group 1 number x", "expected a group number, got 'x'"),
        ("group 1 number 1.5", "expected a group number, got '1.5'"),
        ("cuelist 1 number x", "expected a cue list number, got 'x'"),
        ("playback 1 number x", "expected a playback number, got 'x'"),
        ("page 1 number x", "expected a page number, got 'x'"),
        ("preset color 1 number x", "expected a preset number, got 'x'"),
        ("cue 1/1 number 2", "cue 1/2 exists"),
        ("cue 1/1 number 2.0", "cue 1/1 cannot pass cue 1/2"),
        ("cue 1/1 number 7", "cue 1/1 cannot pass cue 1/2"),
        ("cue 1/2 number 0.5", "cue 1/2 cannot pass cue 1/1"),
        ("cue 1/1 number x", "expected a cue number, got 'x'"),
    ],
)
def test_a_line_busk_cannot_read_is_refused_wherever_it_goes(
    line: str, error: str, tmp_path: Path
) -> None:
    offline = OfflineShow(show_of(load_doc(APPENDIX_A)))
    before = offline.show
    reply = offline.execute(line)
    assert (reply.ok, reply.text) == (False, f"error: {error}")
    assert offline.expected(f"{line} ").error == error
    assert offline.confirmation(line) is None
    script = tmp_path / "script.busk"
    script.write_text(f"sel fixture 101\n{line}\nclear\n", encoding="utf-8")
    with pytest.raises(ScriptError) as raised:
        offline.run_script(script)
    assert (raised.value.line, raised.value.text) == (2, line)
    assert raised.value.output[-1] == f"error: {error}"
    assert offline.show == before


def test_a_number_a_preset_of_another_pool_has_is_free() -> None:
    offline = OfflineShow(show_of(load_doc(APPENDIX_A)))
    assert offline.execute("preset color 2 number 3").ok
    assert offline.execute("preset position 1 number 3").ok


def test_a_cue_takes_its_number_as_typed_or_in_quotes() -> None:
    offline = OfflineShow(show_of(load_doc(APPENDIX_A)))
    assert offline.execute("cue 1/1 number 1.5").ok
    assert offline.show["cueLists"][0]["cues"][0]["number"] == "1.5"
    assert offline.execute('cue 1/1.5 number "1.25"').ok
    assert offline.show["cueLists"][0]["cues"][0]["number"] == "1.25"


@pytest.mark.parametrize(
    "line",
    [
        "fixture 201 number 201",  # its own number: nothing to refuse
        "fixture 201 number 1",
        "universe 1 number 1",
        "universe 1 number 7",
        'fixture add 1 "RGB Par 3ch" mode 3ch',
        'fixture add 300 "RGB Par 3ch" mode 3ch at 1.510',  # ends on channel 512
        'fixture add 300 thru 301 "RGB Par 3ch" mode 3ch at 1.507',
        "fixture 201 patch 1.510",
        "fixture 201 patch 1.1",
        "route add 1 dmxusb enttecPro /dev/ttyUSB0 hz 1",
        "route add 1 dmxusb enttecPro /dev/ttyUSB0 hz 40",
        "route add 1 sacn 2",
        "route add 1 sacn 63999",
        "group 1 number 1",  # its own number: nothing to refuse
        "group 1 number 7",
        "group 1 number 0",  # only fixtures and universes start at 1
        "cuelist 1 number 7",
        "playback 1 number 7",
        "page 1 number 7",
        "preset color 1 number 1",
        "preset color 1 number 7",
        "cue 1/1 number 1",
        "cue 1/1 number 1.5",  # between its neighbours
        "cue 1/2 number 7",  # the last: nothing to pass
        "cue 1/1 number 0.5",
    ],
)
def test_the_edge_of_each_refusal_still_runs(line: str) -> None:
    offline = OfflineShow(show_of(load_doc(APPENDIX_A)))
    assert offline.execute(line).ok


def test_a_universe_number_in_use_is_named() -> None:
    offline = OfflineShow(show_of(load_doc(APPENDIX_A)))
    assert offline.execute("universe add 2").ok
    reply = offline.execute("universe 1 number 2")
    assert (reply.ok, reply.text) == (False, "error: universe 2 exists")


def test_programmer_leaves_out_a_deleted_fixture_and_undo_brings_it_back() -> None:
    offline = OfflineShow(show_of(load_doc(APPENDIX_A)))
    for line in ("sel fixture 101, 102", "set pan 12.5", 'effect add "Pulse" id fx1'):
        assert offline.execute(line).ok, line
    before = offline.execute("programmer").text
    assert before.startswith("selection: 101, 102\n")
    assert "101 pan = 12.5" in before
    assert "effect fx1 'Pulse' on 101, 102" in before

    assert offline.execute("delete fixture 101 cascade").ok

    assert offline.programmer.selection == ((102, 1),)
    assert offline.programmer.effects == ()
    assert offline.execute("programmer").text == (
        "selection: 102\nblind: off\nhighlight: off\nfade: 0 s\n  102 pan = 12.5"
    )
    assert offline.execute("undo").ok
    assert offline.execute("programmer").text == before


def test_programmer_leaves_out_a_deleted_preset_and_undo_brings_it_back() -> None:
    offline = OfflineShow(show_of(load_doc(APPENDIX_A)))
    for line in ("sel fixture 101", "set color preset color 2", "delete preset color 2"):
        assert offline.execute(line).ok, line

    assert offline.programmer.values == ()
    assert offline.execute("programmer").text == (
        "selection: 101\nblind: off\nhighlight: off\nfade: 0 s"
    )
    assert offline.execute("undo").ok
    assert "101 color = preset color 2" in offline.execute("programmer").text


def test_a_cue_number_too_long_is_refused_through_submit() -> None:
    doc = load_doc(APPENDIX_A)
    offline = OfflineShow(show_of(doc))
    before = offline.show
    cue = {**doc["cueLists"][0]["cues"][-1], "id": "cue-long", "number": LONG}

    goto = offline.submit({"type": "GOTO", "playbackId": "pb-song", "cueNumber": LONG})
    added = offline.submit({"type": "ADD", "path": ["cueLists", {"id": "cl-song"}, "cues"],
                            "value": cue})  # fmt: skip

    assert not goto.ok
    assert goto.message.startswith("no cue 777")
    assert not added.ok
    assert [issue.path for issue in added.issues] == ["cueLists[0].cues[2].number"]
    assert offline.show == before


def test_a_quote_read_as_json_still_reads_as_it_did() -> None:
    offline = OfflineShow(show_of(load_doc(APPENDIX_A)))
    assert offline.execute('rename fixture 101 "C:\\new"').ok
    assert offline.show["fixtures"][0]["name"] == "C:\new"  # \n is a newline, as before
    assert offline.execute('rename fixture 101 "say \\"hi\\""').ok
    assert offline.show["fixtures"][0]["name"] == 'say "hi"'


def test_release_all_releases_every_playback(console: Console, live: Live) -> None:
    run(console, "fader 1 1", "fader 3 1")
    live.tick()
    assert run(console, "release all 0") == [""]
    live.tick()
    snapshot = live.engine.snapshot
    assert snapshot is not None
    assert {p.state for p in snapshot.playbacks} == {"idle"}


def test_list_profiles_and_profile_update(live: Live, tmp_path: Path) -> None:
    profile = json.loads((builtin_directory() / "generic-spot-16ch.json").read_text("utf-8"))
    profile["revision"] = "2"
    profile["physical"]["maxStrobeHz"] = 25
    (tmp_path / "spot.json").write_text(json.dumps(profile), encoding="utf-8")
    console = Console(live.session, ProfileLibrary([tmp_path], builtin=False))
    assert run(console, "list profiles")[0].splitlines() == [
        "Generic Spot 16ch (revision 1 → 2 in the library): 16ch",
        "RGB Par 3ch (revision 1): 3ch",
    ]
    live.tick()
    before = live.universe()
    assert run(console, 'profile update "Generic Spot 16ch"') == [
        "updated profile 'Generic Spot 16ch' to revision '2' (2 fixtures)"
    ]
    assert (  # the show's copy had no category: it takes the library's
        run(console, "list profiles")[0].splitlines()[0]
        == "Generic Spot 16ch (spot, revision 2): 16ch"
    )
    show = live.session.show
    assert show["profiles"][0]["physical"]["maxStrobeHz"] == 25
    assert [f["profileRevision"] for f in show["fixtures"]] == ["2", "2", "1"]
    live.tick()
    assert live.universe() == before  # the same channels: the same bytes
    assert run(console, "undo") == [
        "undid: updated profile 'Generic Spot 16ch' to revision '2' (2 fixtures)"
    ]
    assert [f["profileRevision"] for f in live.session.show["fixtures"]] == ["1", "1", "1"]


def test_output_off_asks_at_the_prompt(console: Console, live: Live) -> None:
    feed = answers("output off", "n", "output off", KeyboardInterrupt, "output off", "y", "quit")
    prompts: list[str] = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return next(feed)

    written: list[str] = []
    interact(console, ask=ask, write=written.append)
    assert prompts == ["busk> ", "Turn all DMX output off? [y/N] "] * 3 + ["busk> "]
    assert written == ["cancelled", "", "cancelled"]
    live.tick()
    snapshot = live.engine.snapshot
    assert snapshot is not None
    assert not snapshot.outputEnabled


def test_output_off_does_not_ask_in_a_script_or_piped(
    console: Console, live: Live, tmp_path: Path
) -> None:
    script = tmp_path / "panic.busk"
    script.write_text("output off\n", encoding="utf-8")
    assert console.run_script(script, lambda text: None)
    live.tick()
    assert live.engine.snapshot is not None
    assert not live.engine.snapshot.outputEnabled
    assert run(console, "output on") == [""]  # piped input runs lines through execute
    live.tick()
    assert live.engine.snapshot is not None
    assert live.engine.snapshot.outputEnabled
    assert console.confirmation("output off") == "Turn all DMX output off?"
    assert console.confirmation("output of") is None  # its error is execute's to report


def test_info_ends_with_the_runs_processes(live: Live) -> None:
    about = ["processes: root 1, engine 2, console 3", "restarts: engine 0, console 0"]
    console = Console(live.session, LIBRARY, about=lambda: about)
    assert run(console, "info")[0].splitlines()[-2:] == about


# ------------------------------------------------- GAP-31, GAP-32, GAP-33

SINE_TILT = [{"attribute": "tilt", "waveform": {"kind": "sine"}, "phaseOffset": 0, "mode": "add"}]
TILT_JSON = json.dumps(SINE_TILT)
PULSE_CUE = "cue 20/1"


def template(show: Any, ident: str = "ef-pulse") -> dict[str, Any]:
    return next(t for t in show["effects"] if t["id"] == ident)


def test_a_template_is_renamed_updated_and_deleted_each_in_one_undo_step(
    console: Console, live: Live
) -> None:
    before = copy.deepcopy(live.session.show)
    assert run(console, 'effect template rename "Pulse" "Beat"', "undo") == [
        "renamed effect template 'Pulse' to 'Beat'",
        "undid: renamed effect template 'Pulse' to 'Beat'",
    ]
    assert live.session.show == before
    assert run(console, f'effect template update "Pulse" {TILT_JSON}') == [
        "updated effect template 'Pulse': 1 layer"
    ]
    assert template(live.session.show)["layers"] == SINE_TILT
    assert run(console, "undo") == ["undid: updated effect template 'Pulse': 1 layer"]
    assert live.session.show == before
    run(console, f'effect template add "Spare" {TILT_JSON}')
    with_spare = copy.deepcopy(live.session.show)
    assert run(console, 'effect template delete "Spare"') == ["deleted effect template 'Spare'"]
    assert live.session.show == before
    assert run(console, "undo") == ["undid: deleted effect template 'Spare'"]
    assert live.session.show == with_spare


def test_a_used_template_stays_and_the_reply_says_why(console: Console) -> None:
    reply = console.execute('effect template delete "Pulse"')
    assert not reply.ok
    assert reply.text == "error: template 'Pulse' is used by cue 20/1"
    assert "\n" not in reply.text


def test_an_update_the_show_cannot_take_is_refused_whole(console: Console, live: Live) -> None:
    before = copy.deepcopy(live.session.show)
    reply = console.execute('effect template update "Pulse" []')
    assert not reply.ok
    assert "An effect template needs at least one layer" in reply.text
    assert live.session.show == before


def test_an_update_a_cues_effect_cannot_take_is_refused(console: Console, live: Live) -> None:
    add = [{**SINE_TILT[0], "attribute": "intensity"}]
    run(console, f'effect template update "Pulse" {json.dumps(add)}', "cue 20/1 effect ei-1 size 2")
    before = copy.deepcopy(live.session.show)
    multiply = [{**add[0], "mode": "multiply"}]
    reply = console.execute(f'effect template update "Pulse" {json.dumps(multiply)}')
    assert not reply.ok
    assert "An effect with a multiply layer needs a size within 0..1" in reply.text
    assert live.session.show == before


def test_a_cue_list_may_be_numbered_below_one_as_a_page_may(console: Console) -> None:
    assert run(console, "cuelist add 0") == ["added cue list 'Cue list 0'"]


def test_a_template_edit_survives_a_save_and_a_load(tmp_path: Path) -> None:
    path = tmp_path / "show.json"
    offline = OfflineShow(show_of(load_doc(APPENDIX_A)), path=path)
    run_lines = [
        f'effect template add "Spare" {TILT_JSON}',
        f'effect template update "Pulse" {TILT_JSON}',
        'effect template rename "Pulse" "Beat"',
        "cue 20/1 effect ei-1 remove",
        'effect template delete "Beat"',
        'cuelist add 5 "Blue Wash"',
    ]
    for line in run_lines:
        reply = offline.execute(line)
        assert reply.ok, (line, reply.text)
    offline.save()
    loaded = load_show(path)[0]
    assert [t["name"] for t in loaded["effects"]] == ["Spare"]
    assert next(cl for cl in loaded["cueLists"] if cl["number"] == 5)["name"] == "Blue Wash"
    assert next(cl for cl in loaded["cueLists"] if cl["number"] == 20)["cues"][0]["effects"] == []


def test_removing_a_cues_only_effect_leaves_the_cue(console: Console, live: Live) -> None:
    before = copy.deepcopy(live.session.show)
    assert run(console, f"{PULSE_CUE} effect ei-1 remove") == ["removed effect ei-1 from cue 20/1"]
    cues = next(cl for cl in live.session.show["cueLists"] if cl["number"] == 20)["cues"]
    assert [cue["effects"] for cue in cues] == [[]]
    assert run(console, "undo") == ["undid: removed effect ei-1 from cue 20/1"]
    assert live.session.show == before


def test_an_empty_cue_list_is_listed_and_recorded_into(console: Console, live: Live) -> None:
    before = copy.deepcopy(live.session.show)
    assert run(console, "cuelist add 5") == ["added cue list 'Cue list 5'"]
    assert any(
        line.split() == ["5", "Cue", "list", "5", "no", "cues"]
        for line in run(console, "list cuelists")[0].splitlines()
    )
    assert run(console, "sel fixture 101", "set intensity 1", "record cue 5")[2] == (
        "recorded cue 5/1: 1 entry"
    )
    cues = next(cl for cl in live.session.show["cueLists"] if cl["number"] == 5)["cues"]
    assert [cue["number"] for cue in cues] == ["1"]
    run(console, "undo", "undo", "undo", "undo")
    assert live.session.show == before


def empty_list_show() -> Show:
    """Appendix A with playback 3's list emptied."""
    doc = load_doc(APPENDIX_A)
    doc["cueLists"][1]["cues"] = []
    return show_of(doc)


def eventually(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_go_and_goto_say_so_on_an_empty_list_offline() -> None:
    offline = OfflineShow(empty_list_show())
    assert offline.execute("go 3").text == "error: cue list 10 has no cues"
    assert offline.execute("goto 3 1").text == "error: no cue 1 in cue list 10"


def test_go_and_goto_on_an_empty_list_leave_a_running_engine_alone() -> None:
    with LiveShow(empty_list_show(), output=False) as live:

        def state() -> str | None:
            snapshot = live.snapshot
            if snapshot is None:
                return None
            return next(p.state for p in snapshot.playbacks if p.number == 3)

        eventually(lambda: state() == "idle")
        assert live.execute("go 3").text == "error: cue list 10 has no cues"
        assert live.execute("goto 3 1").text == "error: no cue 1 in cue list 10"
        health = live.health
        assert health is not None
        ticks = health.ticks
        eventually(lambda: live.health is not None and live.health.ticks > ticks)
        assert live.health is not None
        assert live.health.state == "running"
        assert state() == "idle"


def source_of(live: LiveShow, family: str) -> str | None:
    """What drives ``family`` on moving head 101 (``None`` before the first readout)."""
    output = live.output
    if output is None:
        return None
    return next(f for f in output.fixtures if f.number == 101).source[family]


def test_a_template_update_reaches_the_cue_that_runs_it() -> None:
    running = show_of(load_doc(APPENDIX_A))
    with LiveShow(running, output=False) as live:
        assert live.execute("toggle 6").ok
        eventually(lambda: source_of(live, "intensity") == "effect")
        assert source_of(live, "position") != "effect"
        reply = live.execute(f'effect template update "Pulse" {TILT_JSON}')
        assert reply.ok, reply.text
        eventually(lambda: source_of(live, "position") == "effect")
        assert source_of(live, "intensity") != "effect"
        assert live.execute("undo").ok
        eventually(lambda: source_of(live, "intensity") == "effect")
        assert live.show == running


def test_a_cues_effect_leaves_a_running_cue_and_comes_back() -> None:
    running = show_of(load_doc(APPENDIX_A))
    with LiveShow(running, output=False) as live:

        def effects() -> list[str]:
            status = live.effects
            return [] if status is None else [effect.id for effect in status.effects]

        def state() -> str | None:
            snapshot = live.snapshot
            if snapshot is None:
                return None
            return next(p.state for p in snapshot.playbacks if p.number == 6)

        assert live.execute("toggle 6").ok
        eventually(lambda: effects() == ["ei-1"])
        assert live.execute("cue 20/1 effect ei-1 remove").ok
        eventually(lambda: effects() == [])
        assert state() == "active"
        assert live.execute("undo").ok
        eventually(lambda: effects() == ["ei-1"])
        assert live.show == running


def status_of(live: LiveShow, number: int) -> Any:
    """Playback ``number`` as the engine reports it (``None`` before a snapshot)."""
    snapshot = live.snapshot
    if snapshot is None:
        return None
    return next(p for p in snapshot.playbacks if p.number == number)


def test_a_playback_added_and_placed_is_one_undo_step(console: Console, live: Live) -> None:
    before = copy.deepcopy(live.session.show)
    assert run(console, 'playback add 7 cuelist 10 at 2 "Blue 2"') == [
        "added playback 7 'Blue 2' on cue list 10 at 1.2"
    ]
    assert "cue list 10, band 50, master fader" in run(console, "list playbacks")[0].splitlines()[3]
    assert run(console, "list pages") == [
        "*   1  Main                 1:1 2:7 3:3 4:- 5:- 6:6 7:- 8:-"
    ]
    assert run(console, "undo") == ["undid: added playback 7 'Blue 2' on cue list 10 at 1.2"]
    assert live.session.show == before


def test_a_playback_added_is_saved_and_reloaded(console: Console, tmp_path: Path) -> None:
    run(console, 'playback add 7 cuelist 10 at 2 "Blue 2"', "playback 7 exclusivity color")
    saved = tmp_path / "saved.json"
    run(console, f'save "{saved}"')
    show = load_show(saved)[0]
    playback = next(p for p in show["playbacks"] if p["number"] == 7)
    assert (playback["name"], playback["cueListId"], playback["exclusivity"]) == (
        "Blue 2",
        "cl-blue",
        "color",
    )
    assert show["pages"][0]["slots"][1] == playback["id"]


def test_a_playback_is_pointed_at_another_list_and_undo_brings_it_back(
    console: Console, live: Live
) -> None:
    before = copy.deepcopy(live.session.show)
    assert run(console, "playback 3 cuelist 1") == ["playback 3 runs cue list 1"]
    assert "cue list 1," in run(console, "list playbacks")[0].splitlines()[1]
    assert run(console, "undo") == ["undid: playback 3 runs cue list 1"]
    assert live.session.show == before


def test_a_goto_cue_the_new_list_lacks_is_a_warning(console: Console) -> None:
    run(console, "playback 1 gotoCue 2")
    reply = console.execute("playback 1 cuelist 10")
    assert reply.ok
    assert reply.text == (
        "playback 1 runs cue list 10\nwarning playbacks[0].gotoCue: Cue list 'Blue' has no cue '2'"
    )


def test_the_properties_are_removed_and_undo_brings_them_back(console: Console, live: Live) -> None:
    before = copy.deepcopy(live.session.show)
    assert run(console, "playback 3 exclusivity none") == ["removed the exclusivity of playback 3"]
    assert "exclusivity" not in next(p for p in live.session.show["playbacks"] if p["number"] == 3)
    assert run(console, "undo") == ["undid: removed the exclusivity of playback 3"]
    assert live.session.show == before
    assert console.execute("playback 1 bogus 3").text == (
        "error: playback 1 has no property 'bogus'"
    )
    assert run(console, "playback 1 flash.priorityBoost 5", "playback 1 flash.priorityBoost none")
    assert live.session.show == before


def test_a_running_playback_refuses_another_list_until_it_is_released() -> None:
    running = show_of(load_doc(APPENDIX_A))
    with LiveShow(running, output=False) as live:

        def idle() -> bool:
            status = status_of(live, 1)
            return status is not None and status.state == "idle"

        eventually(idle)
        assert live.execute("go 1").ok
        eventually(lambda: status_of(live, 1).state == "active")
        assert live.execute("playback 1 cuelist 10").text == (
            "error: playback 1 is running: release it first"
        )
        assert live.expected("playback 1 cuelist 10 ").error == (
            "playback 1 is running: release it first"
        )
        assert live.show == running  # nothing changed, and it plays on
        assert status_of(live, 1).cue == "1"
        assert live.execute("release 1 0").ok
        eventually(idle)
        assert live.execute("playback 1 cuelist 10").text == "playback 1 runs cue list 10"
        eventually(lambda: status_of(live, 1).cueCount == 1)
        assert live.execute("go 1").ok
        eventually(lambda: status_of(live, 1).cueName == "Blue")
        assert live.execute("release 1 0").ok
        eventually(idle)
        assert live.execute("undo").ok
        eventually(lambda: status_of(live, 1).cueCount == 2)
        assert live.show == running


def test_a_playback_added_on_a_running_show_is_there_at_once() -> None:
    running = show_of(load_doc(APPENDIX_A))
    with LiveShow(running, output=False) as live:
        eventually(lambda: status_of(live, 1) is not None)
        assert live.execute("go 3").ok
        eventually(lambda: status_of(live, 3).state == "active")
        assert live.execute("playback add 7 cuelist 10 at 2").ok
        eventually(lambda: any(p.number == 7 for p in live.snapshot.playbacks))  # type: ignore[union-attr]
        assert status_of(live, 7).state == "idle"
        assert status_of(live, 3).state == "active"
        assert live.execute("go 7").ok
        eventually(lambda: status_of(live, 7).state == "active")
        assert live.execute("release 7 0").ok
        eventually(lambda: status_of(live, 7).state == "idle")
        assert live.execute("undo").ok
        eventually(lambda: all(p.number != 7 for p in live.snapshot.playbacks))  # type: ignore[union-attr]
        assert status_of(live, 3).state == "active"


def test_removing_a_property_reaches_a_running_show() -> None:
    running = show_of(load_doc(APPENDIX_A))
    with LiveShow(running, output=False) as live:
        eventually(lambda: status_of(live, 1) is not None)
        assert live.execute("go 3").ok
        eventually(lambda: status_of(live, 3).state == "active")
        assert live.execute("playback 3 exclusivity none").ok
        assert live.execute("undo").ok
        assert live.show == running
        assert status_of(live, 3).state == "active"
