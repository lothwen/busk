"""The stage view's rig and feed (:mod:`busk.web.stage`).

The rig is Appendix A's: two moving heads (16 channels: pan and tilt 16-bit,
RGBW, a 16-bit dimmer, zoom, a gobo wheel, a shutter) at 1 and 17, and an RGB
par with no dimmer at 101, on universe 1. Frames are built by hand, with the
compiled show's layout, so each byte is known.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess

import pytest

from builders import APPENDIX_A, load_doc, show_of
from busk.compiler.compile import compile_show
from busk.engine.loop import Frame
from busk.model.show import Show
from busk.web.server import stage_page
from busk.web.stage import StageFeed, build_rig

PAN, TILT, ZOOM, SHUTTER, HZ = range(3, 8)  # a one-cell look's fields after r, g, b


def appendix_a() -> Show:
    return show_of(load_doc(APPENDIX_A))


def frame(show: Show, writes: dict[int, bytes], seq: int = 1) -> Frame:
    """A frame of ``show``'s universe 1 with ``writes`` ({1-based address: bytes})."""
    universe = bytearray(512)
    for address, data in writes.items():
        universe[address - 1 : address - 1 + len(data)] = data
    layout = compile_show(show).layout
    return Frame(seq=seq, time=0.0, universes=(bytes(universe),), layout=layout)


def test_fixtures_the_show_has_not_placed_stand_in_a_row_per_kind() -> None:
    rig = {f.number: f for f in build_rig(appendix_a())}
    assert {n: f.kind for n, f in rig.items()} == {101: "head", 102: "head", 201: "par"}
    heads = [rig[101].location, rig[102].location]
    assert heads == [
        {"x": -0.5, "y": -3.0, "z": 6.0, "rx": 180.0, "ry": 0.0, "rz": 0.0},
        {"x": 0.5, "y": -3.0, "z": 6.0, "rx": 180.0, "ry": 0.0, "rz": 0.0},
    ]
    assert rig[201].location == {"x": 0.0, "y": -1.0, "z": 5.5, "rx": 180.0, "ry": 0.0, "rz": 0.0}
    assert rig[101].beam == 21.0  # the middle of the zoom range
    assert rig[201].beam == 25.0  # a par's, with no zoom range


def test_a_location_places_a_fixture_and_a_category_names_its_kind() -> None:
    doc = load_doc(APPENDIX_A)
    place = {"x": 2.0, "y": -4.0, "z": 0.0, "rx": -90.0, "ry": 0.0, "rz": 15.0}
    doc["fixtures"][2]["location"] = place
    doc["profiles"][1]["category"] = "fog"
    (*_, par) = build_rig(show_of(doc))
    assert (par.kind, par.location) == ("fog", place)


def test_a_look_is_read_through_the_profile_mode() -> None:
    show = appendix_a()
    writes = {
        1: bytes([0xFF, 0xFF, 0, 0, 255, 0, 0, 0, 0x80, 0, 255, 0, 12]),  # MH 1: open
        101: bytes([255, 51, 0]),  # the par
    }
    feed = StageFeed()
    feed.update(show, frame(show, writes))
    assert feed.look is not None
    head, second, par = json.loads(feed.look)["looks"]
    # Red at half intensity, pan and tilt at their ends, zoom wide, the shutter open.
    assert head == [0.5, 0.0, 0.0, 270.0, -135.0, 30.0, 0, 0.0]
    # All zeros: dark, pan and tilt at the other ends, zoom narrow, the shutter closed.
    assert second == [0.0, 0.0, 0.0, -270.0, -135.0, 12.0, 1, 0.0]
    # No dimmer: the colour as it is.
    assert par == [1.0, 0.2, 0.0, 0.0, 0.0, 25.0, 0, 0.0]


def test_a_strobing_shutter_and_the_resting_look() -> None:
    show = appendix_a()
    feed = StageFeed()
    _, look = feed.update(show, None)
    assert look is not None
    head = json.loads(look)["looks"][0]
    assert head[SHUTTER] == 1  # the defaults: closed, pan and tilt in the middle
    assert (head[PAN], head[TILT], head[ZOOM]) == (0.0, 0.0, 21.04)
    feed.update(show, frame(show, {13: bytes([100])}))
    assert feed.look is not None
    assert json.loads(feed.look)["looks"][0][SHUTTER] == 2


def test_the_feed_says_only_what_changed() -> None:
    show = appendix_a()
    feed = StageFeed()
    rig, look = feed.update(show, None)
    assert rig is not None
    assert look is not None
    assert json.loads(rig)["title"] == "Club Night"
    assert feed.update(show, None) == (None, None)
    lit = frame(show, {101: bytes([255, 0, 0])})
    _, look = feed.update(show, lit)
    assert look is not None
    assert feed.update(show, lit) == (None, None)
    # The next tick's frame, the same bytes.
    assert feed.update(show, frame(show, {101: bytes([255, 0, 0])}, seq=2)) == (None, None)
    # An edit that changes nothing the page draws, with the same frame: no flash of dark.
    edited = copy.deepcopy(show)
    edited["meta"]["modified"] = "2026-11-15T12:00:00Z"
    assert feed.update(edited, lit) == (None, None)
    # A fixture moved: a new rig.
    moved = copy.deepcopy(edited)
    moved["fixtures"][0]["location"] = {"x": 1.0, "y": -2.0, "z": 7, "rx": 0, "ry": 0, "rz": 0}
    rig, look = feed.update(moved, lit)
    assert rig is not None
    assert look is None
    assert json.loads(rig)["fixtures"][0]["loc"]["z"] == 7


def test_the_deck_is_sized_to_the_rig() -> None:
    doc = load_doc(APPENDIX_A)
    doc["fixtures"][0]["location"] = {"x": 9.0, "y": -8.0, "z": 6, "rx": 180, "ry": 0, "rz": 0}
    show = show_of(doc)
    stage = json.loads(StageFeed().update(show, None)[0] or "")["stage"]
    assert stage == {"width": 20.0, "depth": 9.5, "height": 1.2}


CAMERA = """
class Vector3 {
  constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
  copy(v) { this.x = v.x; this.y = v.y; this.z = v.z; return this; }
}
const THREE = { Vector3, Group: class { constructor() { this.rotation = {}; } } };
const scene = { add() {} };
const camera = { position: new Vector3() };
const controls = { target: new Vector3(), update() {} };
const D = 8;
%s
// The stage group's turn about x, which places the fixtures, is world()'s.
const a = stage.rotation.x, p = world(1, 2, 3);
const same = [p.x - 1, p.y - (2 * Math.cos(a) - 3 * Math.sin(a)),
              p.z - (2 * Math.sin(a) + 3 * Math.cos(a))].every((d) => Math.abs(d) < 1e-9);
// three.js's lookAt, y up, puts the screen's right along (target - camera) × up.
const eye = camera.position, at = controls.target;
const right = [-(at.z - eye.z), 0, at.x - eye.x];
const across = (x) => {  // how far right of the screen's middle a fixture at x is
  const q = world(x, -2, 6);
  return (q.x - eye.x) * right[0] + (q.z - eye.z) * right[2];
};
console.log(JSON.stringify({ same, stageRight: across(3), stageLeft: across(-3) }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run the page's script")
def test_stage_right_is_on_the_left_from_the_front_of_house() -> None:
    """The page's own ``world()``, stage group and front-of-house camera, run
    in node: a fixture at x 3 (stage right) is on the screen's left, as F1
    C's stage draws it (``test_stage_right_comes_first_in_a_row``)."""
    page = stage_page().decode()
    block = re.search(
        r"^const stage = new THREE\.Group\(\);$.*?^frontOfHouse\(\);$", page, re.M | re.S
    )
    assert block is not None
    script = CAMERA % block.group(0)
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    seen = json.loads(done.stdout)
    assert seen["same"]
    assert seen["stageRight"] < 0 < seen["stageLeft"]  # x 3 on the screen's left, x -3 right
