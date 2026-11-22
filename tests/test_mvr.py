"""Reading MVR plots, and the stage frame (MVR plan Phase 2, steps 3 and 4).

:func:`~busk.importers.mvr.read_plot` reads a plot into a plain description,
without a show: fixtures with their composed matrices, positions, GDTF types,
scenery and notes. :func:`~busk.importers.mvr.plot_location` places a plot
fixture in busk's frame and :func:`~busk.importers.mvr.location_matrix` turns
it back. Rotations are compared as matrices, never as rx/ry/rz triples, since
two triples can name one turn.
"""

from __future__ import annotations

import hashlib
import math
import zipfile
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

import busk.importers.mvr as mvr
from busk.importers import ImportFailed
from busk.importers.mvr import (
    IDENTITY,
    Matrix,
    PlotAddress,
    location_matrix,
    parse_matrix,
    plot_location,
    read_plot,
)
from busk.model.fixture import Location
from busk.model.show import Audience, StageFrame
from mvr_builder import (
    SPOT,
    fixture,
    gdtf,
    group,
    layer,
    matrix,
    model,
    plot,
    position,
    scene,
    scenery,
    spot,
    symbol,
    symdef,
)

AUDIENCES: tuple[Audience, ...] = ("-y", "+y", "-x", "+x")


def one_layer(*children: object, aux: tuple[object, ...] = ()) -> bytes:
    return scene(layer("L1", "Lights", *children), aux=aux)  # type: ignore[arg-type]


def read(tmp_path: Path, data: bytes, files: dict[str, bytes] | None = None) -> mvr.Plot:
    return read_plot(plot(tmp_path / "club.mvr", data, files))


def close(a: tuple[float, ...], b: tuple[float, ...], tolerance: float = 1e-9) -> bool:
    return all(abs(x - y) <= tolerance for x, y in zip(a, b, strict=True))


def same(a: Matrix, b: Matrix, turn: float = 1e-9, offset: float = 1e-6) -> bool:
    return (
        close(a.u, b.u, turn)
        and close(a.v, b.v, turn)
        and close(a.w, b.w, turn)
        and close(a.o, b.o, offset)
    )


# ------------------------------------------------------------------ fixtures


def test_a_fixture_is_read_with_what_busk_takes_from_it(tmp_path: Path) -> None:
    data = one_layer(
        fixture(
            "a1b2-c3", " Spot 1 ", fixture_id="101", numeric=101, gdtf_mode="1ch",
            addresses=[("0", "1.1")], at=matrix(o=(1000, -2000, 6000)), position="pos-1",
            invert_pan="true", invert_tilt="false",
        ),
        aux=(position("POS-1", "LX1"),),
    )  # fmt: skip
    found = read(tmp_path, data)
    assert found.positions == {"POS-1": "LX1"}
    (spot_1,) = found.fixtures
    assert spot_1 == mvr.PlotFixture(
        uuid="A1B2-C3",
        name="Spot 1",
        fixture_id="101",
        fixture_id_numeric=101,
        gdtf=SPOT,
        mode="1ch",
        addresses=(PlotAddress(dmx_break=0, universe=1, address=1),),
        matrix=Matrix(o=(1000, -2000, 6000)),
        position="POS-1",
        invert_pan=True,
        invert_tilt=False,
        multipatch=None,
    )
    assert spot_1.label == '"Spot 1"'
    assert found.notes == ()


def test_what_a_fixture_leaves_out_is_none(tmp_path: Path) -> None:
    data = one_layer(fixture("f1", None, gdtf=None, gdtf_mode=None, position="nowhere"))
    (found,) = read(tmp_path, data).fixtures
    assert (found.name, found.fixture_id, found.fixture_id_numeric) == ("", "", 0)
    assert (found.gdtf, found.mode, found.position, found.addresses) == (None, None, None, ())
    assert (found.invert_pan, found.invert_tilt, found.multipatch) == (None, None, None)
    assert found.matrix == IDENTITY
    assert found.label == 'uuid "F1"'


@pytest.mark.parametrize("numeric", ["0", "-3", "x", "1234567890", "1.5"])
def test_a_numeric_id_that_is_no_positive_number_is_0(tmp_path: Path, numeric: str) -> None:
    (found,) = read(tmp_path, one_layer(fixture("f1", "A", numeric=numeric))).fixtures
    assert found.fixture_id_numeric == 0


@pytest.mark.parametrize(
    ("text", "value"), [("true", True), ("TRUE", True), ("1", True), ("false", False),
                        ("0", False), ("maybe", None)],
)  # fmt: skip
def test_inverts_are_read_as_booleans(tmp_path: Path, text: str, value: bool | None) -> None:
    (found,) = read(tmp_path, one_layer(fixture("f1", invert_tilt=text))).fixtures
    assert found.invert_tilt is value


def test_a_multipatch_copy_names_the_fixture_it_copies(tmp_path: Path) -> None:
    data = one_layer(fixture("f1", "A"), fixture("f2", "A copy", multipatch="f1"))
    assert [f.multipatch for f in read(tmp_path, data).fixtures] == [None, "F1"]


def test_a_fixture_without_a_uuid_or_with_another_s_is_left_out(tmp_path: Path) -> None:
    data = one_layer(fixture("", "Lost"), fixture("f1", "First"), fixture("F1", "Twin"))
    found = read(tmp_path, data)
    assert [f.name for f in found.fixtures] == ["First"]
    assert found.notes == ('"Lost" has no uuid, left out',
                           '"Twin" has the uuid of "First", left out')  # fmt: skip


# ------------------------------------------------------------------ addresses


@pytest.mark.parametrize(
    ("dmx_break", "text", "address"),
    [
        (None, "45", (0, 1, 45)),
        ("0", "1", (0, 1, 1)),
        ("0", "512", (0, 1, 512)),
        ("0", "513", (0, 2, 1)),
        ("0", "1025", (0, 3, 1)),
        ("1", "2.17", (1, 2, 17)),
        ("0", "1.512", (0, 1, 512)),
        ("2", " 3.1 ", (2, 3, 1)),
    ],
)
def test_both_address_forms_and_breaks(
    tmp_path: Path, dmx_break: str | None, text: str, address: tuple[int, int, int]
) -> None:
    (found,) = read(tmp_path, one_layer(fixture("f1", "A", addresses=[(dmx_break, text)]))).fixtures
    wanted = PlotAddress(dmx_break=address[0], universe=address[1], address=address[2])
    assert found.addresses == (wanted,)


@pytest.mark.parametrize(
    ("dmx_break", "text"),
    [("0", "0"), ("0", "1.0"), ("0", "1.513"), ("0", "0.1"), ("0", "x"), ("0", ""),
     ("0", "-1"), ("x", "1"), ("-1", "1"), ("0", "1.1.1")],
)  # fmt: skip
def test_an_address_that_is_none_is_noted_and_left_out(
    tmp_path: Path, dmx_break: str, text: str
) -> None:
    found = read(tmp_path, one_layer(fixture("f1", "A", addresses=[(dmx_break, text)])))
    assert found.fixtures[0].addresses == ()
    assert found.notes == (f'"A": address "{text}" not read',)


# ------------------------------------------------------------------ matrices


def test_the_spec_s_example_matrix_is_read_as_its_axes() -> None:
    """MVR 1.6, "Node Definition: Matrix": u, v and w are the object's x, y
    and z axes (the columns of the turn), o its offset in mm."""
    text = (
        "{0.158127,-0.987419,0.000000}{0.987419,0.158127,0.000000}"
        "{0.000000,0.000000,1.000000}{6020.939200,2838.588955,4978.134651}"
    )
    found = parse_matrix(text)
    assert found == Matrix(
        u=(0.158127, -0.987419, 0.0),
        v=(0.987419, 0.158127, 0.0),
        w=(0.0, 0.0, 1.0),
        o=(6020.9392, 2838.588955, 4978.134651),
    )
    assert found.turn((1, 0, 0)) == found.u  # its own x axis, in its parent's frame
    assert close(found.turn((0, 1, 0)), found.v)


@pytest.mark.parametrize(
    "text",
    ["", "{1,0,0}{0,1,0}{0,0,1}", "{1,0,0}{0,1,0}{0,0,1}{0,0,0}{0,0,0}",
     "{1,0}{0,1,0}{0,0,1}{0,0,0}", "{1,0,0}{0,1,0}{0,0,1}{0,0,nan}",
     "{1,0,0}{0,1,0}{0,0,1}{0,0,inf}", "{a,0,0}{0,1,0}{0,0,1}{0,0,0}",
     "{1,0,0}x{0,1,0}{0,0,1}{0,0,0}"],
)  # fmt: skip
def test_a_matrix_that_is_none_is_noted_and_taken_as_none(tmp_path: Path, text: str) -> None:
    assert parse_matrix(text) is None
    found = read(tmp_path, one_layer(fixture("f1", "A", at=text)))
    assert found.fixtures[0].matrix == IDENTITY
    assert found.notes == (f'Fixture "A": matrix "{text}" not read, taken as none',)


def test_matrices_compose_from_the_layer_down_through_groups_and_trusses(tmp_path: Path) -> None:
    """A layer lifted 500 mm, a group turned 90° about z and moved, a truss in
    it moved along the group's x, and a fixture on the truss moved along the
    truss's x: each matrix is relative to its parent."""
    quarter = matrix(u=(0, 1, 0), v=(-1, 0, 0), o=(1000, 0, 0))
    hung = fixture("f1", "Spot", at=matrix(o=(100, 0, 0)))
    truss = scenery("Truss", "t1", "LX1", at=matrix(o=(2000, 0, 6000)), children=[hung])
    data = scene(layer("L1", "Rig", group("g1", "Upstage", truss, at=quarter),
                       at=matrix(o=(0, 0, 500))))  # fmt: skip
    (found,) = read(tmp_path, data).fixtures
    # the group's x is the plot's y: 1000 + (0, 2000 + 100), z 500 + 6000
    assert same(found.matrix, Matrix(u=(0, 1, 0), v=(-1, 0, 0), o=(1000, 2100, 6500)))


def test_a_child_s_turn_composes_with_its_parent_s() -> None:
    parent = Matrix(u=(0, 1, 0), v=(-1, 0, 0), o=(5, 0, 0))  # 90° about z
    child = Matrix(u=(1, 0, 0), v=(0, 0, 1), w=(0, -1, 0), o=(1, 2, 3))  # 90° about x
    composed = parent @ child
    for p in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
        assert close(composed.turn(p), parent.turn(child.turn(p)))
    assert close(composed.o, (5 - 2, 1, 3))


def test_a_fixture_with_no_turn_is_noted(tmp_path: Path) -> None:
    flat = matrix(u=(1, 0, 0), v=(2, 0, 0), w=(0, 0, 1), o=(0, 0, 3000))
    found = read(tmp_path, one_layer(fixture("f1", "Flat", at=flat)))
    assert found.notes == ('"Flat": its matrix has no turn, taken as none',)
    assert plot_location(found.fixtures[0].matrix, frame()) == location(z=3, rx=180, rz=180)


def test_a_scaled_fixture_keeps_its_turn() -> None:
    scaled = Matrix(u=(0, 2, 0), v=(-3, 0, 0), w=(0, 0, 0.5), o=(0, 0, 0))
    assert plot_location(scaled, frame("+y")) == plot_location(
        Matrix(u=(0, 1, 0), v=(-1, 0, 0)), frame("+y")
    )


# ------------------------------------------------------------------ fixture types


def test_each_gdtf_is_imported_once(tmp_path: Path) -> None:
    data = one_layer(fixture("f1", "A"), fixture("f2", "B"), fixture("f3", "C", gdtf=None))
    found = read(tmp_path, data)
    assert list(found.types) == [SPOT]
    spot_type = found.types[SPOT]
    assert spot_type.problem is None
    assert spot_type.report is not None
    assert spot_type.report.profile["name"] == "Acme Spot"
    assert [m["name"] for m in spot_type.report.profile["modes"]] == ["3ch", "1ch"]


def test_a_gdtf_named_without_its_extension_is_found(tmp_path: Path) -> None:
    found = read(tmp_path, one_layer(fixture("f1", "A", gdtf="Acme@Spot")))
    assert found.types["Acme@Spot"].report is not None


@pytest.mark.parametrize(
    ("files", "problem"),
    [
        ({}, "is not in the plot"),
        ({SPOT: b"not a zip"}, "cannot be imported: not a GDTF file: File is not a zip file"),
        ({SPOT: gdtf(b"<GDTF/>")},
         "cannot be imported: not a GDTF description: it has no GDTF/FixtureType"),
    ],
)  # fmt: skip
def test_a_gdtf_that_cannot_be_imported_says_why(
    tmp_path: Path, files: dict[str, bytes], problem: str
) -> None:
    found = read(tmp_path, one_layer(fixture("f1", "A")), files)
    assert found.types[SPOT] == mvr.PlotType(file=SPOT, report=None, problem=problem)
    assert [f.name for f in found.fixtures] == ["A"]


def test_a_gdtf_past_its_cap_is_not_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mvr, "GDTF_CAP", 100)
    found = read(tmp_path, one_layer(fixture("f1", "A")), {SPOT: gdtf(spot() + b" " * 200)})
    assert found.types[SPOT].problem == "is larger than 0 MB, not read"


# ------------------------------------------------------------------ scenery


def test_scenery_is_each_model_with_its_composed_matrix(tmp_path: Path) -> None:
    pipe = symdef("sd-1", "Pipe", model("pipe.glb", at=matrix(o=(0, 0, 10))))
    truss = scenery(
        "Truss", "t1", "LX1", model("truss.3ds"), symbol("s1", "SD-1", at=matrix(o=(500, 0, 0))),
        at=matrix(o=(0, -1000, 6000)),
    )  # fmt: skip
    screen = scenery("VideoScreen", "v1", "Screen", model("screen.glb"), at=matrix(o=(0, 4000, 0)))
    data = one_layer(truss, screen, fixture("f1", "A"), aux=(pipe,))
    files = {SPOT: gdtf(), "truss.3ds": b"3ds", "pipe.glb": b"glb", "screen.glb": b"glb"}
    found = read(tmp_path, data, files)
    assert [(s.kind, s.name, s.model, s.matrix.o) for s in found.scenery] == [
        ("Truss", "LX1", "truss.3ds", (0, -1000, 6000)),
        ("Truss", "LX1", "pipe.glb", (500, -1000, 6010)),
        ("VideoScreen", "Screen", "screen.glb", (0, 4000, 0)),
    ]
    assert found.notes == ()


@pytest.mark.parametrize("kind", ["Support", "SceneObject", "Projector"])
def test_every_kind_of_scenery_is_read(tmp_path: Path, kind: str) -> None:
    found = read(tmp_path, one_layer(scenery(kind, "o1", "Thing", model("a.glb"))), {"a.glb": b""})
    assert [s.kind for s in found.scenery] == [kind]


def test_a_missing_model_or_symdef_is_noted(tmp_path: Path) -> None:
    truss = scenery("Truss", "t1", "LX1", model("gone.3ds"), symbol("s1", "nowhere"))
    found = read(tmp_path, one_layer(truss), {})
    assert found.scenery == ()
    assert found.notes == ('model "gone.3ds" is not in the plot',
                           'Truss "LX1": a symbol names no Symdef')  # fmt: skip


def test_a_symbol_in_itself_stops(tmp_path: Path) -> None:
    loop = symdef("sd-1", "Loop", model("a.glb"), symbol("s1", "sd-1"))
    found = read(tmp_path, one_layer(scenery("Truss", "t1", "T", symbol("s0", "sd-1")),
                                     aux=(loop,)), {"a.glb": b""})  # fmt: skip
    assert len(found.scenery) == mvr.SYMBOL_DEPTH
    assert found.notes == (f"symbols nest more than {mvr.SYMBOL_DEPTH} deep; the rest left out",)


def test_symbols_that_fan_out_stop_at_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ten symbols of ten symbols of … would place 10^16 models."""
    monkeypatch.setattr(mvr, "GEOMETRY_CAP", 500)
    defs = [symdef(f"sd-{k}", f"D{k}", *(symbol(f"s{k}-{n}", f"sd-{k + 1}") for n in range(10)))
            for k in range(15)]  # fmt: skip
    defs.append(symdef("sd-15", "Leaf", model("a.glb")))
    found = read(tmp_path, one_layer(scenery("Truss", "t1", "T", symbol("s", "sd-0")),
                                     aux=tuple(defs)), {"a.glb": b""})  # fmt: skip
    assert found.notes[-1].startswith("the scenery expands to more than 500 models and symbols")


# ------------------------------------------------------------------ the file


def test_the_hash_is_the_file_s(tmp_path: Path) -> None:
    path = plot(tmp_path / "club.mvr", one_layer(fixture("f1", "A")))
    assert read_plot(path).sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_nul_bytes_ending_the_scene_and_a_gdtf_are_dropped(tmp_path: Path) -> None:
    """One exporter ends every XML file of its plots with the C string's
    terminator, the scene and each GDTF's ``description.xml``."""
    data = one_layer(fixture("f1", "A")) + b"\n\x00"
    found = read(tmp_path, data, {SPOT: gdtf(spot() + b"\n\x00")})
    assert [f.name for f in found.fixtures] == ["A"]
    assert found.types[SPOT].report is not None
    assert found.notes == ()


def test_a_doctype_is_refused(tmp_path: Path) -> None:
    data = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><GeneralSceneDescription/>'
    with pytest.raises(ImportFailed, match=r"^GeneralSceneDescription.xml declares a DOCTYPE"):
        read(tmp_path, data)


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda p: p.write_bytes(b"nope"), "not an MVR file: File is not a zip file"),
        (lambda p: zipfile.ZipFile(p, "w").close(),
         "not an MVR file: it has no GeneralSceneDescription.xml"),
        (lambda p: plot(p, b"<Other/>", {}),
         "not an MVR file: GeneralSceneDescription.xml has no GeneralSceneDescription/Scene"),
        (lambda p: plot(p, b"<GeneralSceneDescription", {}),
         "GeneralSceneDescription.xml is not well-formed XML: "),
    ],
)  # fmt: skip
def test_a_file_that_is_no_plot_is_refused(tmp_path: Path, make: object, message: str) -> None:
    path = tmp_path / "club.mvr"
    make(path)  # type: ignore[operator]
    with pytest.raises(ImportFailed) as caught:
        read_plot(path)
    assert str(caught.value).startswith(message)


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ImportFailed, match="No such file or directory"):
        read_plot(tmp_path / "gone.mvr")


def test_the_caps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = plot(tmp_path / "club.mvr", one_layer(fixture("f1", "A")))
    monkeypatch.setattr(mvr, "MEMBER_CAP", 1)
    with pytest.raises(ImportFailed, match=r"^the plot holds more than 1 files; not read$"):
        read_plot(path)
    monkeypatch.setattr(mvr, "MEMBER_CAP", 2)
    monkeypatch.setattr(mvr, "UNPACKED_CAP", 100)
    with pytest.raises(ImportFailed, match=r"^the plot unpacks to more than 0 MB; not read$"):
        read_plot(path)
    monkeypatch.setattr(mvr, "UNPACKED_CAP", 10**9)
    monkeypatch.setattr(mvr, "SCENE_CAP", 100)
    with pytest.raises(ImportFailed, match=r"larger than 0 MB; not read$"):
        read_plot(path)


def test_names_in_the_scene_are_only_looked_up_in_the_archive(tmp_path: Path) -> None:
    (tmp_path / "outside.gdtf").write_bytes(gdtf())
    found = read(tmp_path, one_layer(fixture("f1", "A", gdtf="../outside.gdtf")), {})
    assert found.types["../outside.gdtf"].problem == "is not in the plot"


# ------------------------------------------------------------------ the frame


def frame(audience: Audience = "-y", origin: tuple[float, float, float] = (0, 0, 0)) -> StageFrame:
    return StageFrame(origin=origin, audience=audience)


def location(**values: float) -> Location:
    return Location(**{"x": 0.0, "y": 0.0, "z": 0.0, "rx": 0.0, "ry": 0.0, "rz": 0.0, **values})


def busk_turn(at: Location) -> Matrix:
    """busk's turn of a location, ``R_z · R_y · R_x``, as the web view applies it."""
    rx, ry, rz = (math.radians(at[k]) for k in ("rx", "ry", "rz"))  # type: ignore[literal-required]
    z = Matrix((math.cos(rz), math.sin(rz), 0), (-math.sin(rz), math.cos(rz), 0))
    y = Matrix((math.cos(ry), 0, -math.sin(ry)), (0, 1, 0), (math.sin(ry), 0, math.cos(ry)))
    x = Matrix((1, 0, 0), (0, math.cos(rx), math.sin(rx)), (0, -math.sin(rx), math.cos(rx)))
    return z @ y @ x


THETA = {"-y": 180.0, "+y": 0.0, "-x": -90.0, "+x": 90.0}


@pytest.mark.parametrize("audience", AUDIENCES)
def test_identity_hangs_at_rx_180_and_rz_theta(audience: Audience) -> None:
    at = plot_location(IDENTITY, frame(audience))
    assert at == location(rx=180, rz=THETA[audience])


def test_with_the_audience_at_minus_y_identity_hangs_front_to_the_audience() -> None:
    turn = busk_turn(plot_location(IDENTITY, frame("-y")))
    assert close(turn.turn((0, 0, 1)), (0, 0, -1))  # the beam down
    assert close(turn.turn((0, 1, 0)), (0, 1, 0))  # the front (busk's +y) downstage


@pytest.mark.parametrize("audience", AUDIENCES)
def test_a_floor_fixture_stands_beam_up(audience: Audience) -> None:
    standing = Matrix(u=(1, 0, 0), v=(0, -1, 0), w=(0, 0, -1))  # GDTF's hung fixture turned over
    at = plot_location(standing, frame(audience))
    assert (at["rx"], at["ry"], at["rz"]) == (0, 0, THETA[audience])
    assert close(busk_turn(at).turn((0, 0, 1)), (0, 0, 1))


def test_a_fixture_aimed_at_the_audience_aims_downstage() -> None:
    """GDTF's beam is local −Z; turned to the plot's −Y, where the audience is."""
    aimed = Matrix(u=(1, 0, 0), v=(0, 0, -1), w=(0, 1, 0))  # R_x(−90°): −Z → −Y
    assert close(aimed.turn((0, 0, -1)), (0, -1, 0))
    at = plot_location(aimed, frame("-y"))
    assert close(busk_turn(at).turn((0, 0, 1)), (0, 1, 0))


@pytest.mark.parametrize(
    ("audience", "where"),
    [("-y", (-1, -2, 3)), ("+y", (1, 2, 3)), ("-x", (2, -1, 3)), ("+x", (-2, 1, 3))],
)
def test_each_audience_turns_the_plot(audience: Audience, where: tuple[float, ...]) -> None:
    at = plot_location(Matrix(o=(1000, 2000, 3000)), frame(audience))
    assert (at["x"], at["y"], at["z"]) == where


def test_an_origin_moves_the_plot_first(tmp_path: Path) -> None:
    at = plot_location(Matrix(o=(21000, 13500, 7000)), frame("-y", (20000, 15000, 1000)))
    assert (at["x"], at["y"], at["z"]) == (-1.0, 1.5, 6.0)


def test_locations_are_rounded() -> None:
    at = plot_location(Matrix(o=(1234.56789, 0, 0)), frame("+y"))
    assert at["x"] == 1.2346


def test_angles_are_above_minus_180_up_to_180() -> None:
    """A turn of −180° about z, as a CAD computes it, is 180°: one turn, one triple."""
    cos, sin = math.cos(-math.pi), math.sin(-math.pi)  # sin is −1.2e-16
    at = plot_location(Matrix(u=(cos, sin, 0), v=(-sin, cos, 0)), frame("+y"))
    assert at == location(rx=180, rz=180)


@pytest.mark.parametrize("ry", [90.0, -90.0])
@pytest.mark.parametrize("audience", AUDIENCES)
def test_the_gimbal_case_takes_rx_0(ry: float, audience: Audience) -> None:
    turn = busk_turn(location(rx=30, ry=ry, rz=40))
    there = location_matrix(location(rx=30, ry=ry, rz=40), frame(audience))
    at = plot_location(there, frame(audience))
    assert (at["rx"], at["ry"]) == (0, ry)
    assert same(busk_turn(at), turn, turn=1e-6)


_angles = st.floats(min_value=-180, max_value=180, allow_nan=False)
_metres = st.floats(min_value=-50, max_value=50, allow_nan=False)


@given(
    st.sampled_from(AUDIENCES), _metres, _metres, _metres, _angles, _angles, _angles,
    st.tuples(_metres, _metres, _metres),
)  # fmt: skip
def test_plot_to_busk_to_plot_comes_back(
    audience: Audience,
    x: float, y: float, z: float, rx: float, ry: float, rz: float,
    origin: tuple[float, float, float],
) -> None:  # fmt: skip
    here = frame(audience, (origin[0] * 1000, origin[1] * 1000, origin[2] * 1000))
    there = location_matrix(location(x=x, y=y, z=z, rx=rx, ry=ry, rz=rz), here)
    back = location_matrix(plot_location(there, here), here)
    assert same(back, there, turn=1e-4, offset=0.1)  # degrees to 3 places, metres to 4


def test_a_location_turned_back_is_the_plot_s_matrix() -> None:
    """busk → plot → busk, at a fixture the frame places by hand."""
    hung = location(x=-1, y=2, z=6.5, rx=180, rz=180)
    assert same(location_matrix(hung, frame("-y")), Matrix(o=(1000, -2000, 6500)))
