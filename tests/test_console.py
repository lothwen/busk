"""The console: execute, scripts, source, rendering, defaults, the prompt (phase-3-plan §5.10)."""

from __future__ import annotations

import json
import signal
from pathlib import Path
from typing import Any

import pytest

from builders import APPENDIX_A, load_doc
from busk.console.console import Console, interact
from busk.console.parser import SubmitAll
from busk.console.prompt import Editing
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


def test_commands_print_their_result(console: Console) -> None:
    assert run(console, "sel group 1", "set pan 10", "clear") == [
        "2 targets selected",
        "pan: 2 targets",
        "programmer cleared",
    ]
    assert run(console, "fader 3 1") == [""]  # performance commands print nothing


def test_errors_print_with_every_issue_path(console: Console) -> None:
    reply = console.execute("delete group 2")
    assert not reply.ok
    assert reply.text.splitlines() == [
        "error: deleted groups[1]: rejected, the show would not be valid",
        "  cueLists[1].cues[0].entries[1].targets.groupId: Unknown group 'g-par'",
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
    assert (
        run(console, "list profiles")[0].splitlines()[0] == "Generic Spot 16ch (revision 2): 16ch"
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
    assert console.confirmation("output off") == "Turn all DMX output off? [y/N] "
    assert console.confirmation("output of") is None  # its error is execute's to report


def test_info_ends_with_the_runs_processes(live: Live) -> None:
    about = ["processes: root 1, engine 2, console 3", "restarts: engine 0, console 0"]
    console = Console(live.session, LIBRARY, about=lambda: about)
    assert run(console, "info")[0].splitlines()[-2:] == about
