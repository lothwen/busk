"""The stage view's rig and feed (:mod:`busk.web.stage`).

The rig is Appendix A's: two moving heads (16 channels: pan and tilt 16-bit,
RGBW, a 16-bit dimmer, zoom, a gobo wheel, a shutter) at 1 and 17, and an RGB
par with no dimmer at 101, on universe 1. Frames are built by hand, with the
compiled show's layout, so each byte is known.

The scenery's tests (MVR plan Phase 5) import a plot of one spot hung on a
truss, whose model is ``truss.glb``, into a show saved in ``shows/``, beside
the plot's folder ``plots/``. The feed never reads a model, so a model's bytes
are any.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pytest

import busk.web.stage as web_stage
from builders import APPENDIX_A, load_doc, show_of
from busk import CounterIds, OfflineShow, new_show
from busk.compiler.compile import compile_show
from busk.engine.loop import Frame
from busk.importers.mvr import read_plot
from busk.model.show import Show
from busk.web.server import stage_page
from busk.web.stage import StageFeed, build_rig, scenery_file
from mvr_builder import SPOT, fixture, gdtf, layer, matrix, model, plot, position, scene, scenery

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


STAGE = """
const box = (x0, y0, z0, x1, y1, z1) => ({ min: { x: x0, y: y0, z: z0 },
                                           max: { x: x1, y: y1, z: z1 } });
%s
// Demostage's scenery, its origin in the middle of its deck, on the floor.
const plot = [
  box(-6, -4, 1.0, 6, 4, 1.1),            // the deck's top
  box(-6, 3.9, 0, 6, 4, 1.0),             // its skirt, at the front
  box(-6.15, -4.17, 0, 6.15, -0.12, 8),   // the LED wall's box, upstage
  box(4.5, -0.17, 0, 9, -0.07, 8),        // a wing
  box(-9, -0.17, 0, -4.5, -0.07, 8),      // the other
  box(-9, 6.36, 9, 9, 6.64, 9.29),        // the front of house truss, flown
  box(7.21, 3.56, 6.6, 7.79, 4.16, 8.5),  // a PA hang, flown
  box(-3, 20, 0, 3, 24, 0.4),             // the mix riser, out in the audience
  box(-50, -50, -0.05, 50, 50, 0),        // the venue's floor
];
const trusses = [box(-9, -4.14, 7.5, 9, -3.86, 7.79), box(-9, 3.86, 8.5, 9, 4.14, 8.79)];
console.log(JSON.stringify({ plot: stageOf(plot, 0), trusses: stageOf(trusses, 0) }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run the page's script")
def test_the_stage_of_a_plot_is_what_stands_on_the_floor() -> None:
    """The page's own ``stageOf``, run in node: the stage is the block of
    scenery standing on the floor that covers the most of it. What is flown,
    a riser apart from the stage and the floor itself are not the stage; a
    plot with nothing on the floor has none."""
    page = stage_page().decode()
    block = re.search(r"^const REACH = .*?^}$", page, re.M | re.S)
    assert block is not None
    done = subprocess.run(
        ["node", "-e", STAGE % block.group(0)], capture_output=True, text=True, timeout=30
    )
    assert done.returncode == 0, done.stderr
    seen = json.loads(done.stdout)
    stage = seen["plot"]
    assert (stage["min"], stage["max"]) == ({"x": -9, "y": -4.17}, {"x": 9, "y": 4})
    assert seen["trusses"] is None


# --------------------------------------------------------------------- the plot's scenery

TRUSS = b"glTF: the truss"
PLOT = os.path.join("..", "plots", "club.mvr")  # as the show keeps it
WITHOUT = "the stage is drawn without its scenery"


def club_plot(tmp_path: Path, *objects: ET.Element, files: dict[str, bytes] | None = None) -> Path:
    """The plot: spot 101 hung on truss LX1 (``truss.glb``, at Y −2 m, Z 6 m),
    and ``objects``."""
    spot = fixture("F101", "Spot 1", numeric=101, addresses=[("0", "1.1")], position="P1")
    truss = scenery("Truss", "T1", "LX1", model("truss.glb"), at=matrix(o=(0, -2000, 6000)),
                    children=[spot])  # fmt: skip
    data = scene(layer("L1", "Lights", truss, *objects), aux=[position("P1", "LX1")])
    (tmp_path / "plots").mkdir(exist_ok=True)
    files = {SPOT: gdtf(), "truss.glb": TRUSS, **(files or {})}
    return plot(tmp_path / "plots" / "club.mvr", data, files)


def imported(tmp_path: Path) -> OfflineShow:
    """A show in ``shows/club.show`` with the club plot imported."""
    (tmp_path / "shows").mkdir()
    show = OfflineShow(
        new_show("Club", ids=CounterIds()),
        path=tmp_path / "shows" / "club.show",
        ids=CounterIds(100),
    )
    assert show.execute(f'rig import "{club_plot(tmp_path)}"').ok
    assert show.show["stage"]["plot"] == PLOT
    return show


def rig_of(show: OfflineShow, feed: StageFeed | None = None) -> dict[str, Any]:
    """The rig a page that opens gets."""
    feed = feed or StageFeed()
    feed.update(show.show, None, Path(show.session.path or ""), opened=True)
    return dict(json.loads(feed.rig or ""))


def test_a_rig_from_a_plot_brings_its_scenery(tmp_path: Path) -> None:
    show = imported(tmp_path)
    feed = StageFeed()
    rig = rig_of(show, feed)
    # Through the frame (audience -y): the truss at busk (0, 2, 6), turned 180° about z.
    at = [-1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 2.0, 6.0]
    assert rig["scenery"] == [{"file": "truss.glb", "format": "gltf", "at": [at]}]
    assert rig["notes"] == []
    assert rig["fixtures"][0]["loc"]["y"] == 2.0  # the spot hangs on it
    assert feed.plot is not None
    assert feed.plot.resolve() == (tmp_path / "plots" / "club.mvr").resolve()


def test_a_show_without_a_plot_has_no_scenery() -> None:
    feed = StageFeed()
    rig = json.loads(feed.update(appendix_a(), None)[0] or "")
    assert (rig["scenery"], rig["notes"], feed.plot) == ([], [], None)


def test_a_plot_with_no_show_file_is_read_where_it_is(tmp_path: Path) -> None:
    show = OfflineShow(new_show("Club", ids=CounterIds()), ids=CounterIds(100))
    assert show.execute(f'rig import "{club_plot(tmp_path)}"').ok
    assert os.path.isabs(show.show["stage"]["plot"])
    rig = json.loads(StageFeed().update(show.show, None, None)[0] or "")
    assert [model["file"] for model in rig["scenery"]] == ["truss.glb"]


def test_each_model_file_comes_once_with_every_place_it_stands(tmp_path: Path) -> None:
    show = imported(tmp_path)
    second = scenery("Truss", "T2", "LX2", model("truss.glb"), at=matrix(o=(1000, 0, 7000)))
    riser = scenery("SceneObject", "S1", "Riser", model("riser"))  # no extension: 3DS
    club_plot(tmp_path, second, riser, files={"riser": b"3DS"})
    models = rig_of(show)["scenery"]
    assert [(m["file"], m["format"], len(m["at"])) for m in models] == [
        ("truss.glb", "gltf", 2),
        ("riser", "3ds", 1),
    ]
    assert models[0]["at"][1][9:] == [-1.0, 0.0, 7.0]


def test_a_missing_plot_draws_the_deck_and_says_so(tmp_path: Path) -> None:
    show = imported(tmp_path)
    feed = StageFeed()
    rig_of(show, feed)
    assert feed.plot is not None
    (tmp_path / "plots" / "club.mvr").unlink()
    rig = rig_of(show, feed)
    assert rig["scenery"] == []
    assert rig["notes"] == [f"the plot {PLOT} is not there: {WITHOUT}"]
    assert feed.plot is None  # nothing of it is served


def test_a_plot_undone_is_served_no_more(tmp_path: Path) -> None:
    show = imported(tmp_path)
    feed = StageFeed()
    rig_of(show, feed)
    assert show.execute("undo").ok  # the import
    assert rig_of(show, feed)["scenery"] == []
    assert feed.plot is None


def test_a_plot_busk_cannot_read_draws_the_deck_and_says_why(tmp_path: Path) -> None:
    show = imported(tmp_path)
    (tmp_path / "plots" / "club.mvr").write_text("not a zip")
    rig = rig_of(show)
    assert rig["scenery"] == []
    [note] = rig["notes"]
    assert note.startswith(f"the plot {PLOT} cannot be read (not an MVR file: ")
    assert note.endswith(f"): {WITHOUT}")


def test_a_changed_plot_is_drawn_as_it_is_now_and_says_so(tmp_path: Path) -> None:
    show = imported(tmp_path)
    moved = scenery("Truss", "T1", "LX1", model("truss.glb"), at=matrix(o=(0, -3000, 6000)))
    plot(tmp_path / "plots" / "club.mvr", scene(layer("L1", "L", moved)), {"truss.glb": TRUSS})
    rig = rig_of(show)
    assert rig["scenery"][0]["at"][0][9:] == [0.0, 3.0, 6.0]
    assert rig["notes"] == [f"the plot {PLOT} has changed since the rig was imported"]


def test_models_in_a_format_busk_does_not_draw_are_counted(tmp_path: Path) -> None:
    show = imported(tmp_path)
    sets = [scenery("SceneObject", f"S{n}", "Set", model(f"set{n}.obj")) for n in (1, 2)]
    club_plot(tmp_path, *sets, files={"set1.obj": b"obj", "set2.obj": b"obj"})
    rig = rig_of(show)
    assert [m["file"] for m in rig["scenery"]] == ["truss.glb"]
    assert rig["notes"][1:] == ["2 models of the plot in a format busk does not draw"]


def test_the_plot_is_read_again_only_when_its_file_has_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    show = imported(tmp_path)
    reads: list[Path] = []

    def counted(path: Path, *, types: bool = True) -> Any:
        reads.append(path)
        return read_plot(path, types=types)

    monkeypatch.setattr(web_stage, "read_plot", counted)
    feed, path = StageFeed(), Path(show.session.path or "")
    assert feed.update(show.show, None, path)[0] is not None
    assert show.execute('rename show "Night"').ok  # a new show, the same plot
    assert feed.update(show.show, None, path)[0] is not None  # the title changed
    assert feed.update(show.show, None, path, opened=True) == (None, None)  # a page opens
    assert len(reads) == 1
    riser = scenery("SceneObject", "S1", "Riser", model("truss.glb"))
    club_plot(tmp_path, riser)  # the designer's new plot, saved over it
    rig, _ = feed.update(show.show, None, path, opened=True)
    assert rig is not None  # the pages open reload with it
    assert len(json.loads(rig)["scenery"][0]["at"]) == 2
    assert len(reads) == 2


def test_scenery_files_are_the_models_and_what_they_name_only(tmp_path: Path) -> None:
    files = {"tex.PNG": b"png", "riser": b"3DS", "page.html": b"<script>", "logo.svg": b"<svg/>"}
    path = club_plot(tmp_path, files=files)
    assert scenery_file(path, "truss.glb") == (TRUSS, "model/gltf-binary")
    assert scenery_file(path, "tex.PNG") == (b"png", "image/png")
    assert scenery_file(path, "riser") == (b"3DS", "application/octet-stream")
    for name in ("GeneralSceneDescription.xml", SPOT, "page.html", "logo.svg", "gone.glb"):
        assert scenery_file(path, name) is None, name
