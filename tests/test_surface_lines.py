"""Surfaces renamed, deleted and changed, and the MIDI devices plugged in
(GAP-60, GAP-61 and GAP-62 of ``docs/dev/tui/engine-gaps.md``).

``rename surface "<name>" "<new name>"`` and ``delete surface "<name>"
[cascade]``: a rename refuses a name another surface has, in any case; a
surface with bindings goes only with ``cascade``, which takes them and asks
first at a prompt. ``surface "<name>" change …`` takes what ``surface add``
takes after the kind and the name, whole, and keeps the surface's kind, id,
name, pickup and bindings. Each is one undo step, with a reply in words. A
running show closes what goes or changes and opens the new definition.

``busk.midi_devices()`` gives the MIDI input devices plugged in, as ``surface
add midi`` takes them.

The rig below has one surface of each kind busk opens, and a ``hid`` one,
which it does not.
"""

from __future__ import annotations

import copy
import json
import logging
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import mido
import pytest

import busk
from builders import ROOT, localhost_route
from busk import LiveShow, OfflineShow, load_show, new_show
from busk.commands.types import Command
from busk.io import midi
from busk.io.osc import encode
from busk.io.surfaces import device_names
from busk.persistence.show_file import save_show
from process_harness import BuskRun
from sacn_receiver import Receiver
from test_hotplug import NANO, THROUGH, Ports, sequencer_available

CLUB_NIGHT = ROOT / "examples" / "club-night.busk"


def run(show: OfflineShow | LiveShow, *lines: str) -> None:
    for line in lines:
        reply = show.execute(line)
        assert reply.ok, (line, reply.text)


def said(show: OfflineShow | LiveShow, line: str) -> str:
    """The reply to ``line``, which must go through."""
    reply = show.execute(line)
    assert reply.ok, (line, reply.text)
    return reply.text


def refused(show: OfflineShow, line: str) -> str:
    """The reply to ``line``, which must be refused."""
    reply = show.execute(line)
    assert not reply.ok, (line, reply.text)
    return reply.text


def one_step(show: OfflineShow, line: str) -> Any:
    """Run ``line``; check that one ``undo`` gives the document back and that
    ``redo`` does it again. The document after it."""
    before = copy.deepcopy(show.show)
    run(show, line)
    after = copy.deepcopy(show.show)
    run(show, "undo")
    assert show.show == before
    run(show, "redo")
    assert show.show == after
    return show.show


def surface(show: OfflineShow | LiveShow, name: str) -> dict[str, Any]:
    return cast(dict[str, Any], next(s for s in show.show["surfaces"] if s["name"] == name))


def names(show: OfflineShow) -> list[str]:
    return [s["name"] for s in show.show["surfaces"]]


def bound(show: OfflineShow, name: str) -> list[str]:
    """The ids of the bindings of surface ``name``."""
    ident = surface(show, name)["id"]
    return [b["id"] for b in show.show["bindings"] if b["surfaceId"] == ident]


def add_hid(show: OfflineShow) -> None:
    """A ``hid`` surface, which no line makes and busk shows as ignored."""
    value = {"id": "s-keys", "name": "Keys", "kind": "hid", "match": {}, "faderPickup": "jump"}
    result = show.submit(cast(Command, {"type": "ADD", "path": ["surfaces"], "value": value}))
    assert result.ok, result.message


@pytest.fixture
def rig() -> OfflineShow:
    show = OfflineShow(new_show("Rig"))
    run(
        show,
        'universe add 1 "Stage"',
        'fixture add 1 thru 2 "RGB Par 3ch" mode 3ch at 1.1',
        "sel fixture 1 thru 2",
        "set intensity 100%",
        "record slot 1",
        "clear",
        'surface add midi "Pad"',
        'surface add osc "Touch" port 9000 feedback 10.0.0.2:9001',
        'surface add web "Phone" port 8080',
        'surface "Pad" pickup soft',
        'bind "Pad" cc 1 0 fader 1',
        'bind "Pad" cc 1 32 button 1 1 led',
        'bind "Touch" osc "/fader/1" fader 1',
    )
    add_hid(show)
    return show


# ----------------------------------------------------------------- rename


@pytest.mark.parametrize("name", ["Pad", "Touch", "Phone", "Keys"])
def test_each_kind_is_renamed_in_one_step(rig: OfflineShow, name: str) -> None:
    ident = surface(rig, name)["id"]
    assert rig.confirmation(f'rename surface "{name}" "Desk"') is None
    reply = said(rig, f'rename surface "{name}" "Desk"')
    assert reply == f'renamed surface "{name}" to "Desk"'
    run(rig, "undo")
    doc = one_step(rig, f'rename surface "{name}" "Desk"')
    assert next(s for s in doc["surfaces"] if s["id"] == ident)["name"] == "Desk"


def test_a_surface_is_named_in_any_case_and_may_change_its_own_case(rig: OfflineShow) -> None:
    assert said(rig, 'rename surface "touch" "TOUCH"') == 'renamed surface "Touch" to "TOUCH"'
    assert names(rig) == ["Pad", "TOUCH", "Phone", "Keys"]


def test_a_name_another_surface_has_is_refused_in_any_case(rig: OfflineShow) -> None:
    assert refused(rig, 'rename surface "Touch" "phone"') == "error: a surface named 'phone' exists"
    assert names(rig) == ["Pad", "Touch", "Phone", "Keys"]


def test_its_bindings_follow_its_new_name(rig: OfflineShow) -> None:
    run(rig, 'rename surface "Touch" "Desk"')
    assert said(rig, "list bindings").splitlines()[-1].endswith('Desk osc "/fader/1" → fader 1')
    run(rig, 'bind "Desk" osc "/fader/2" fader 2', 'unbind "Desk" osc "/fader/1"')
    assert len(bound(rig, "Desk")) == 1


def test_a_midi_surface_renamed_is_found_by_its_device_until_a_surface_takes_the_name(
    rig: OfflineShow,
) -> None:
    run(rig, 'rename surface "Pad" "Left"', 'bind "Pad" cc 1 1 fader 2')  # by its device
    assert len(bound(rig, "Left")) == 3
    run(rig, 'surface add midi "Pad"', 'bind "Pad" cc 1 1 fader 2')  # by its name, first
    assert (len(bound(rig, "Left")), len(bound(rig, "Pad"))) == (3, 1)
    assert said(rig, 'rename surface "Left" "pad left"') == 'renamed surface "Left" to "pad left"'


# ----------------------------------------------------------------- delete


@pytest.mark.parametrize("name", ["Phone", "Keys"])
def test_a_surface_with_no_bindings_goes_plainly_in_one_step(rig: OfflineShow, name: str) -> None:
    assert rig.confirmation(f'delete surface "{name}"') is None
    assert said(rig, f'delete surface "{name}"') == f'deleted surface "{name}"'
    run(rig, "undo")
    doc = one_step(rig, f'delete surface "{name}"')
    assert name not in [s["name"] for s in doc["surfaces"]]


def test_with_nothing_to_cascade_it_still_asks(rig: OfflineShow) -> None:
    assert rig.confirmation('delete surface "Phone" cascade') == 'Delete surface "Phone"?'
    assert said(rig, 'delete surface "Phone" cascade') == 'deleted surface "Phone"'


def test_a_surface_with_bindings_needs_the_cascade(rig: OfflineShow) -> None:
    error = 'error: surface "Pad" has 2 bindings: add cascade'
    assert refused(rig, 'delete surface "Pad"') == error
    found = rig.expected('delete surface "Pad" ')
    assert (found.words, found.runnable) == (("cascade",), False)
    assert names(rig) == ["Pad", "Touch", "Phone", "Keys"]


def test_the_cascade_takes_its_bindings_and_leaves_the_others(rig: OfflineShow) -> None:
    others = bound(rig, "Touch")
    assert rig.confirmation('delete surface "Pad" cascade') == (
        'Delete surface "Pad"? It leaves 2 bindings.'
    )
    assert said(rig, 'delete surface "Pad" cascade') == 'deleted surface "Pad": left 2 bindings'
    assert [b["id"] for b in rig.show["bindings"]] == others
    run(rig, "undo")
    doc = one_step(rig, 'delete surface "Pad" cascade')
    assert [s["name"] for s in doc["surfaces"]] == ["Touch", "Phone", "Keys"]


def test_the_question_says_one_binding_in_the_singular(rig: OfflineShow) -> None:
    assert rig.confirmation('delete surface "Touch" cascade') == (
        'Delete surface "Touch"? It leaves 1 binding.'
    )
    assert refused(rig, 'delete surface "Touch"') == (
        'error: surface "Touch" has 1 binding: add cascade'
    )


def test_a_name_with_a_quote_is_written_as_it_is_typed(rig: OfflineShow) -> None:
    run(rig, 'rename surface "Touch" "the \\"desk\\""')
    assert rig.confirmation('delete surface "the \\"desk\\"" cascade') == (
        'Delete surface "the \\"desk\\""? It leaves 1 binding.'
    )


def test_a_script_does_not_ask(rig: OfflineShow, tmp_path: Path) -> None:
    script = tmp_path / "go.busk"
    script.write_text('delete surface "Pad" cascade\n')
    rig.run_script(script)
    assert names(rig) == ["Touch", "Phone", "Keys"]


def test_the_club_shows_controller_goes_with_its_bindings_and_the_show_reloads(
    tmp_path: Path,
) -> None:
    path = tmp_path / "club.show"
    club = OfflineShow(new_show("Club Night"), path=path)
    club.run_script(CLUB_NIGHT)
    count = len(club.show["bindings"])
    assert said(club, 'delete surface "nanoKONTROL2" cascade') == (
        f'deleted surface "nanoKONTROL2": left {count} bindings'
    )
    assert club.show["bindings"] == []
    run(club, 'delete surface "Phone"')
    save_show(club.show, path)
    show, issues = load_show(path)
    assert (show["surfaces"], show["bindings"], issues) == ([], [], [])


# ----------------------------------------------------------------- change


def test_a_midi_surface_changes_its_device_and_keeps_the_rest(rig: OfflineShow) -> None:
    before = surface(rig, "Pad")
    bindings = bound(rig, "Pad")
    reply = said(rig, 'surface "Pad" change "Pad MIDI 2"')
    assert reply == 'changed surface "Pad": device "Pad MIDI 2"'
    run(rig, "undo")
    one_step(rig, 'surface "Pad" change "Pad MIDI 2"')
    assert surface(rig, "Pad") == {**before, "match": {"deviceName": "Pad MIDI 2"}}
    assert bound(rig, "Pad") == bindings  # the pickup stays soft, and the bindings stay


@pytest.mark.parametrize(
    ("options", "match", "words"),
    [
        ("port 9001 feedback 10.0.0.2:9001", {"port": 9001, "host": "10.0.0.2",
         "feedbackPort": 9001}, "port 9001, feedback to 10.0.0.2:9001"),
        ("feedback 10.0.0.3", {"port": 8000, "host": "10.0.0.3"},
         "port 8000, feedback to 10.0.0.3 at the sender's port"),
        ("feedback :9002 port 9003", {"port": 9003, "feedbackPort": 9002},
         "port 9003, feedback to the sender at port 9002"),
        ("", {"port": 8000}, "port 8000, feedback to the sender"),
    ],
)  # fmt: skip
def test_an_osc_surface_changes_whole_what_it_listens_on_and_where_feedback_goes(
    rig: OfflineShow, options: str, match: dict[str, Any], words: str
) -> None:
    before = surface(rig, "Touch")
    line = f'surface "Touch" change {options}'.rstrip()
    assert rig.confirmation(line) is None
    assert said(rig, line) == f'changed surface "Touch": {words}'
    assert surface(rig, "Touch") == {**before, "match": match}  # what is left out goes back
    run(rig, "undo")
    one_step(rig, line)


@pytest.mark.parametrize(
    ("options", "match", "words"),
    [
        ("port 8081 on 10.0.0.5", {"port": 8081, "host": "10.0.0.5"}, "port 8081 on 10.0.0.5"),
        ("on 127.0.0.1", {"port": 8080, "host": "127.0.0.1"}, "port 8080 on 127.0.0.1"),
    ],
)
def test_a_web_remote_changes_its_port_and_host(
    rig: OfflineShow, options: str, match: dict[str, Any], words: str
) -> None:
    before = surface(rig, "Phone")
    assert said(rig, f'surface "Phone" change {options}') == f'changed surface "Phone": {words}'
    assert surface(rig, "Phone") == {**before, "match": match}
    assert said(rig, 'surface "Phone" change') == 'changed surface "Phone": port 8080'
    assert surface(rig, "Phone") == before


def test_a_port_another_surface_of_its_kind_listens_on_is_refused(rig: OfflineShow) -> None:
    run(rig, 'surface add osc "Other" port 9100')
    assert refused(rig, 'surface "Touch" change port 9100') == (
        "error: port 9100 is in use by surface 'Other'"
    )
    run(rig, 'surface "Touch" change port 9000')  # its own port; feedback to the sender now
    run(rig, 'surface "Touch" change port 8080')  # the web remote's, but another kind


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ('surface "Touch" change port 9000 feedback 10.0.0.2:9001',
         'surface "Touch" is set up that way already'),
        ('surface "Pad" change "Pad"', 'surface "Pad" is set up that way already'),
        ('surface "Phone" change port 8080', 'surface "Phone" is set up that way already'),
        ('surface "Keys" change', 'surface "Keys" is a hid surface, which busk does not open'),
        ('surface "Touch" change port 0', "expected a port (1–65535), got '0'"),
        ('surface "Touch" change port 9001 port 9002', "unexpected 'port'"),
        ('surface "Touch" change on 10.0.0.2', "unexpected 'on'"),
        ('surface "Phone" change feedback 10.0.0.2', "unexpected 'feedback'"),
        ('surface "Pad" change', 'expected a device name in quotes, e.g. "nanoKONTROL2"'),
        ('surface "Pad" change "X" now', "unexpected 'now'"),
        ('surface "Touch" port 9001', "expected pickup or change, got 'port'"),
    ],
)  # fmt: skip
def test_what_change_refuses(rig: OfflineShow, line: str, error: str) -> None:
    before = copy.deepcopy(rig.show)
    assert refused(rig, line) == f"error: {error}"
    assert rig.show == before


# -------------------------------------------------------- refusals, Tab


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ('rename surface "Nope" "X"', "no surface 'Nope'"),
        ('delete surface "Nope"', "no surface 'Nope'"),
        ('rename surface "Touch"', "expected a name in quotes"),
        ('rename surface "Touch" Desk', "expected a name in quotes"),
        ('rename surface "Touch" "Desk" now', "unexpected 'now'"),
        ('delete surface "Phone" now', "unexpected 'now'"),
        ('delete surface "Pad" cascade now', "unexpected 'now'"),
    ],
)
def test_what_rename_and_delete_refuse(rig: OfflineShow, line: str, error: str) -> None:
    assert refused(rig, line) == f"error: {error}"


def test_tab_offers_the_lines_and_the_surfaces(rig: OfflineShow) -> None:
    surfaces = ('"Pad"', '"Touch"', '"Phone"', '"Keys"')
    assert "surface" in rig.expected("rename ").words
    assert "surface" in rig.expected("delete ").words
    assert rig.expected("rename surface ").words == surfaces
    assert rig.expected("delete surface ").words == surfaces
    assert rig.expected('delete surface "P').words == ('"Pad"', '"Phone"')
    assert rig.expected('surface "Touch" ').words == ("pickup", "change")
    found = rig.expected('surface "Touch" change ')
    assert (found.words, found.runnable) == (("port", "feedback"), True)
    found = rig.expected('surface "Phone" change ')  # it listens on 8080 with no host already
    assert (found.words, found.runnable) == (("port", "on"), False)
    assert found.error == 'surface "Phone" is set up that way already'
    found = rig.expected('surface "Pad" change ')
    assert (found.words, found.runnable) == ((), False)
    assert found.values == ('a device name in quotes, e.g. "nanoKONTROL2"',)


# ------------------------------------------------------- the MIDI devices


@pytest.mark.parametrize(
    ("ports", "devices"),
    [
        ([], ()),
        ([THROUGH], ()),  # ALSA's own loopback
        ([THROUGH, NANO], ("nanoKONTROL2",)),
        ([NANO, "nanoKONTROL2:nanoKONTROL2 _ CTRL 28:0"], ("nanoKONTROL2",)),  # two alike
        (["X-Touch:X-Touch MIDI 1 24:0", "X-Touch:X-Touch MIDI 2 24:1"],
         ("X-Touch:X-Touch MIDI 1", "X-Touch:X-Touch MIDI 2")),  # one each
        (["RtMidiOut Client:Pad 128:0"], ("RtMidiOut Client:Pad",)),  # a program's port
        (["IAC Driver Bus 1", "nanoKONTROL2 SLIDER/KNOB"],
         ("IAC Driver Bus 1", "nanoKONTROL2 SLIDER/KNOB")),  # no client: whole
    ],
)  # fmt: skip
def test_device_names_are_what_surface_add_midi_takes(
    ports: list[str], devices: tuple[str, ...]
) -> None:
    assert device_names(ports) == devices
    for device in devices:  # each opens a port of its own, as a surface matches it
        assert sum(device.casefold() in port.casefold() for port in ports) >= 1


def test_midi_devices_reads_the_system_each_time(monkeypatch: pytest.MonkeyPatch) -> None:
    system = Ports()
    monkeypatch.setattr(midi, "input_names", system.list)
    assert busk.midi_devices() == ()
    system.names.append(NANO)  # plugged in
    assert busk.midi_devices() == ("nanoKONTROL2",)
    system.broken = True  # no ALSA sequencer
    assert busk.midi_devices() == ()


def test_midi_devices_without_mido_is_empty() -> None:
    script = (
        'import sys\nsys.modules["mido"] = None\n'
        "import busk\nprint(busk.midi_devices(), 'busk.io.midi' in sys.modules)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60, check=False
    )
    assert (done.returncode, done.stdout) == (0, "() False\n"), done.stderr


@pytest.mark.midi
@pytest.mark.skipif(not sequencer_available(), reason="needs an ALSA sequencer (/dev/snd/seq)")
def test_midi_devices_lists_a_virtual_alsa_port_while_it_is_there() -> None:
    name = f"busk-devices-{uuid.uuid4().hex[:8]}"
    with mido.open_output(name, virtual=True):
        devices = busk.midi_devices()
    assert f"RtMidiOut Client:{name}" in devices
    assert not any("Midi Through" in device for device in devices)
    assert f"RtMidiOut Client:{name}" not in busk.midi_devices()


# ------------------------------------------------------------- LiveShow


def eventually(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def free_port(kind: socket.SocketKind) -> int:
    with socket.socket(socket.AF_INET, kind) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def state(live: LiveShow, name: str) -> tuple[str, str] | None:
    """Surface ``name``'s state and detail, ``None`` while it has no status."""
    ident = surface(live, name)["id"] if any(
        s["name"] == name for s in live.show["surfaces"]
    ) else None  # fmt: skip
    found = next((s for s in live.surfaces or () if s.id == ident), None)
    return None if found is None else (found.state, found.detail)


@pytest.fixture
def no_midi(monkeypatch: pytest.MonkeyPatch) -> Ports:
    """The fake MIDI system, with nothing but Midi Through plugged in."""
    system = Ports()
    monkeypatch.setattr(midi, "input_names", system.list)
    monkeypatch.setattr(midi, "output_names", system.list)
    monkeypatch.setattr(midi.mido, "open_input", system.open_input)
    monkeypatch.setattr(midi.mido, "open_output", system.open_output)
    return system


def live_rig(rig: OfflineShow, osc: int, web: int) -> LiveShow:
    """The rig, its OSC surface on ``osc`` and its web remote on ``web``, on
    localhost, with its surfaces open."""
    run(rig, f'surface "Touch" change port {osc}')
    run(rig, f'surface "Phone" change port {web} on 127.0.0.1')
    return LiveShow(copy.deepcopy(rig.show), output=False, surfaces=True)


def heard(live: LiveShow, path: str) -> int:
    return sum(i.input == f'osc "{path}"' for i in live.inputs)


def fader(snapshot: Any) -> float:
    return float(snapshot.playbacks[0].faderLevel)


def reach(live: LiveShow, client: socket.socket, port: int, path: str, value: float) -> None:
    """Send ``path`` to ``port`` until the show hears it once more: a surface
    opens a moment after the line that changes it."""
    count = heard(live, path)
    deadline = time.monotonic() + 5.0
    while heard(live, path) == count:
        assert time.monotonic() < deadline, f"nothing heard on port {port}"
        client.sendto(encode(path, value), ("127.0.0.1", port))
        time.sleep(0.05)


@pytest.mark.usefixtures("no_midi")
def test_an_osc_surface_moved_on_a_running_show_listens_on_its_new_port(rig: OfflineShow) -> None:
    old, new = free_port(socket.SOCK_DGRAM), free_port(socket.SOCK_DGRAM)
    with (
        live_rig(rig, old, free_port(socket.SOCK_STREAM)) as live,
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client,
    ):
        eventually(lambda: state(live, "Touch") == ("ok", ""))
        reach(live, client, old, "/fader/1", 0.25)
        reply = said(live, f'surface "Touch" change port {new}')
        assert reply == f'changed surface "Touch": port {new}, feedback to the sender'
        reach(live, client, new, "/fader/1", 0.5)
        assert live.inputs[-1].drives == ("fader 1",)
        eventually(lambda: live.snapshot is not None and fader(live.snapshot) == 0.5)
        client.sendto(encode("/old", 1.0), ("127.0.0.1", old))  # nobody listens there now
        reach(live, client, new, "/marker", 1.0)
        assert heard(live, "/old") == 0
        assert state(live, "Touch") == ("ok", "")

        run(live, "undo")  # back to the old port
        reach(live, client, old, "/fader/1", 0.25)
        client.sendto(encode("/new", 1.0), ("127.0.0.1", new))
        reach(live, client, old, "/marker", 1.0)
        assert heard(live, "/new") == 0


@pytest.mark.usefixtures("no_midi")
def test_a_surface_deleted_on_a_running_show_closes_and_undo_opens_it(rig: OfflineShow) -> None:
    osc = free_port(socket.SOCK_DGRAM)
    with (
        live_rig(rig, osc, free_port(socket.SOCK_STREAM)) as live,
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client,
    ):
        eventually(lambda: state(live, "Touch") == ("ok", ""))
        run(live, 'delete surface "Touch" cascade')
        eventually(lambda: [s.name for s in live.surfaces or ()] == ["Pad", "Phone", "Keys"])
        run(live, "undo")
        eventually(lambda: state(live, "Touch") == ("ok", ""))
        reach(live, client, osc, "/fader/1", 0.5)
        assert live.inputs[-1].drives == ("fader 1",)  # its binding came back with it


def page(url: str) -> int:
    with urllib.request.urlopen(url, timeout=5) as response:
        return int(response.status)


@pytest.mark.usefixtures("no_midi")
def test_a_web_remote_renamed_keeps_its_server_and_moved_restarts(rig: OfflineShow) -> None:
    web, new = free_port(socket.SOCK_STREAM), free_port(socket.SOCK_STREAM)
    with live_rig(rig, free_port(socket.SOCK_DGRAM), web) as live:
        eventually(lambda: state(live, "Phone") == ("ok", ""))
        [phone] = [s for s in live.surfaces or () if s.name == "Phone"]
        [url] = phone.urls
        assert page(url) == 200
        run(live, 'rename surface "Phone" "Stage phone"')
        eventually(lambda: any(s.name == "Stage phone" for s in live.surfaces or ()))
        [renamed] = [s for s in live.surfaces or () if s.name == "Stage phone"]
        assert renamed.urls == (url,)  # the same server, its key unchanged
        run(live, f'surface "Stage phone" change port {new} on 127.0.0.1')
        eventually(lambda: any(f":{new}/" in u for s in live.surfaces or () for u in s.urls))
        [moved] = [s.urls[0] for s in live.surfaces or () if s.name == "Stage phone"]
        assert page(moved) == 200
        with pytest.raises(urllib.error.URLError, match="refused"):  # nothing serves it now
            page(url)


def test_a_midi_surface_moved_to_a_device_not_plugged_in_fails_until_it_comes(
    rig: OfflineShow, no_midi: Ports
) -> None:
    no_midi.names.append("Pad A:Pad A 20:0")
    run(rig, 'surface "Pad" change "Pad A"')
    with LiveShow(copy.deepcopy(rig.show), output=False, surfaces=True) as live:
        eventually(lambda: state(live, "Pad") == ("ok", ""))
        run(live, 'surface "Pad" change "Pad B"')
        missing = f"'Pad B' not found; available: {THROUGH}, Pad A:Pad A 20:0"
        eventually(lambda: state(live, "Pad") == ("failed", missing))
        no_midi.names.append("Pad B:Pad B 24:0")  # plugged in: the next hot-plug read opens it
        eventually(lambda: state(live, "Pad") == ("ok", ""), timeout=6.0)
        assert [port.name for port in no_midi.opened if port.callback] == [
            "Pad A:Pad A 20:0",
            "Pad B:Pad B 24:0",
        ]


def test_a_rename_or_a_pickup_reopens_no_surface_on_a_running_show(
    rig: OfflineShow, no_midi: Ports, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="busk.surfaces")
    no_midi.names.append("Pad A:Pad A 20:0")
    run(rig, 'surface "Pad" change "Pad A"')
    osc = free_port(socket.SOCK_DGRAM)
    with (
        live_rig(rig, osc, free_port(socket.SOCK_STREAM)) as live,
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client,
    ):
        eventually(lambda: [s.state for s in live.surfaces or ()] == ["ok", "ok", "ok", "ignored"])
        eventually(lambda: len(no_midi.opened) == 2)  # the input, and the feedback's output
        for line in ('rename surface "Pad" "Left"', 'surface "Left" pickup jump',
                     'rename surface "Touch" "Desk"', 'surface "Desk" pickup soft'):  # fmt: skip
            run(live, line)
        eventually(
            lambda: [s.name for s in live.surfaces or ()] == ["Left", "Desk", "Phone", "Keys"]
        )
        reach(live, client, osc, "/fader/1", 0.5)  # the edits have reached the surfaces
        assert live.inputs[-1].surface == "Desk"
        assert [port.name for port in no_midi.opened] == ["Pad A:Pad A 20:0"] * 2
        listening = [r for r in caplog.records if "listening on udp" in r.getMessage()]
        assert len(listening) == 1


# ----------------------------------------------------------------- busk run


@pytest.mark.parametrize("threads", [False, True], ids=["processes", "threads"])
def test_busk_run_changes_a_surface_and_reads_the_midi_devices_in_its_console_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receiver: Receiver,
    rig: OfflineShow,
    threads: bool,
) -> None:
    old, new = free_port(socket.SOCK_DGRAM), free_port(socket.SOCK_DGRAM)
    run(rig, f'surface "Touch" change port {old}', 'delete surface "Pad" cascade')
    run(rig, 'delete surface "Phone"', 'delete surface "Keys"')
    show = tmp_path / "show.json"
    show.write_text(json.dumps(localhost_route(cast(Any, rig.show))))
    report = tmp_path / "report.json"
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "lines": [f'surface "Touch" change port {new}', 'rename surface "Touch" "Desk"'],
                "osc": {"port": new, "messages": [["/fader/1", 0.75]], "repeat": True},
                "midiDevices": True,
                "report": str(report),
            }
        )
    )
    monkeypatch.setenv("BUSK_TEST_FRONTEND", str(plan))
    options = ["--frontend", "frontend_probe:main", "--state-dir", str(tmp_path / "state")]
    if threads:
        options.append("--threads")
    with BuskRun(show, *options, "--no-log", sacn_port=receiver.port) as busk_run:
        assert busk_run.wait() == 0, busk_run.err
    seen = json.loads(report.read_text())
    assert seen["timeout"] is None, seen
    assert [reply[:3] for reply in seen["replies"]] == [
        [f'surface "Touch" change port {new}',
         f'changed surface "Touch": port {new}, feedback to the sender', True],
        ['rename surface "Touch" "Desk"', 'renamed surface "Touch" to "Desk"', True],
    ]  # fmt: skip
    assert seen["inputs"][0][2:] == ["Desk", 'osc "/fader/1"', None, 0.75, ["fader 1"]]
    assert seen["midiDevices"] == list(busk.midi_devices())  # the same host
