"""MVR plots (DIN SPEC 15801; MVR plan §2, §5 and Phase 2).

A **plot** is an MVR file: the rig as a lighting designer draws it in CAD.
:func:`read_plot` reads one into a :class:`Plot`, a plain description that
knows nothing of a show: its fixtures, the hanging positions they hang on,
the GDTF fixture types they name, its scenery, and notes on what it could not
read. ``rig check`` and ``rig import`` (:mod:`busk.console.rig`) turn it into
a rig.

**The archive.** An MVR file is a ZIP archive holding
``GeneralSceneDescription.xml`` and, side by side, the files it names. A plot
is untrusted:

* an archive of more than :data:`MEMBER_CAP` files, or whose files unpack to
  more than :data:`UNPACKED_CAP` bytes (by their declared sizes, which reading
  holds them to), is refused;
* the scene is read up to :data:`SCENE_CAP` bytes, parsed as GDTF's
  ``description.xml`` is (:func:`~busk.importers.gdtf.parse_description`: a
  ``DOCTYPE`` is refused, NUL bytes after the last element are dropped), and
  each GDTF up to :data:`GDTF_CAP`;
* names in the scene are only looked up in the archive, never used as paths;
* symbols expand at most :data:`SYMBOL_DEPTH` deep, and the scenery into at
  most :data:`GEOMETRY_CAP` models and symbols.

**The scene.** ``Scene/AUXData`` holds the hanging positions (``Position``)
and the shared geometry (``Symdef``). ``Scene/Layers/Layer`` holds the
objects (``Fixture``, ``Truss``, ``Support``, ``SceneObject``,
``VideoScreen``, ``Projector``, ``GroupObject``, ``FocusPoint``), and each
object may hold a ``ChildList`` of its own. A child's ``Matrix`` is relative
to its parent, so an object's matrix is composed from its layer down.

**Fixtures** keep what busk takes from them (:class:`PlotFixture`). Uuids are
read in upper case; a fixture without one, or with an earlier fixture's, is
left out. A GDTF named without its ``.gdtf`` is found with it. Each GDTF the
fixtures name is imported once (:class:`PlotType`), through
:func:`~busk.importers.gdtf.import_gdtf`.

**Scenery** is the geometry of trusses, supports, scene objects, video
screens and projectors: each ``Geometry3D`` model file, ``Symbol``\\ s
expanded from their ``Symdef``, with its composed matrix (:class:`Scenery`).

**The frame** (MVR plan §5). A plot is right-handed, Z up, in millimetres,
with its origin and its audience side its own; a GDTF fixture at the identity
hangs with its beam down (−Z) and its front to −Y. busk's frame is metres
from the middle of the downstage edge, x to stage right, y downstage, z up,
and a fixture at zero stands with its beam up. A show's
:class:`~busk.model.show.StageFrame` names where busk's origin is in the plot
and which side the audience is on, which turns the plot by θ about z:

=============  ======  =================================
``audience``   θ       busk x, y from the plot's X, Y
=============  ======  =================================
``-y``         180°    −X, −Y
``+y``         0°      X, Y
``-x``         −90°    Y, −X
``+x``         90°     −Y, X
=============  ======  =================================

:func:`plot_location` gives a fixture's busk location: ``R_z(θ) · (o −
origin) / 1000``, turned ``R_z(θ) · R · R_x(180°)`` and read as busk's ``rx``,
``ry``, ``rz`` (``R_z · R_y · R_x``; ``rx`` 0 where ``ry`` is ±90°).
:func:`location_matrix` turns a location back into the plot.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import zipfile
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from xml.etree import ElementTree as ET

from busk.importers import ImportFailed, ImportReport
from busk.importers.gdtf import _description, import_gdtf, parse_description
from busk.model.fixture import Location
from busk.model.show import Audience, StageFrame

_MB: Final = 1024 * 1024

SCENE: Final = "GeneralSceneDescription.xml"
"""The scene's file in the archive."""
SCENE_CAP: Final = 64 * _MB
"""The largest scene read, uncompressed, in bytes."""
GDTF_CAP: Final = 256 * _MB
"""The largest GDTF file read, uncompressed, in bytes."""
MEMBER_CAP: Final = 50_000
"""The most files a plot's archive may hold."""
UNPACKED_CAP: Final = 4096 * _MB
"""The most bytes a plot's files may unpack to, together."""
SYMBOL_DEPTH: Final = 16
"""How deeply symbols may nest in symbols."""
GEOMETRY_CAP: Final = 100_000
"""The most models and symbols a plot's scenery may expand to."""

SCENERY: Final = frozenset({"Truss", "Support", "SceneObject", "VideoScreen", "Projector"})
"""The objects whose geometry is scenery."""
OBJECTS: Final = frozenset({"Fixture", "GroupObject", "FocusPoint", *SCENERY})
"""The objects a ``ChildList`` holds that are read (their matrices compose)."""

TURNS: Final[Mapping[Audience, tuple[int, int]]] = {
    "-y": (-1, 0),
    "+y": (1, 0),
    "-x": (0, -1),
    "+x": (0, 1),
}
"""cos θ and sin θ of the turn about z from a plot's axes to busk's, by the
plot's audience side."""

type Vector = tuple[float, float, float]

_NUMBER: Final = re.compile(r"[0-9]{1,9}")
_UNIVERSE_ADDRESS: Final = re.compile(r"([0-9]{1,9})\.([0-9]{1,3})")
_MATRIX: Final = re.compile(r"\s*(?:\{[^{}]*\}\s*){4}")
_ROW: Final = re.compile(r"\{([^{}]*)\}")


# ------------------------------------------------------------------ matrices


@dataclass(frozen=True, slots=True)
class Matrix:
    """An MVR matrix, written ``{u}{v}{w}{o}``: the object's own x, y and z
    axes in its parent's frame (a turn, and a scale where they are not of
    length 1), and its offset there, in millimetres."""

    u: Vector = (1.0, 0.0, 0.0)
    v: Vector = (0.0, 1.0, 0.0)
    w: Vector = (0.0, 0.0, 1.0)
    o: Vector = (0.0, 0.0, 0.0)

    def turn(self, p: Vector) -> Vector:
        """``p`` turned (and scaled) by this matrix, not moved."""
        return _add(_add(_times(self.u, p[0]), _times(self.v, p[1])), _times(self.w, p[2]))

    def __matmul__(self, child: Matrix) -> Matrix:
        """``child``, a matrix in this one's frame, in this one's parent's."""
        u, v, w = self.turn(child.u), self.turn(child.v), self.turn(child.w)
        return Matrix(u, v, w, _add(self.turn(child.o), self.o))

    def rotation(self) -> Matrix | None:
        """The turn alone, its scale taken out (its axes made of length 1 and
        square, x first, then y, z from them), with no offset; ``None`` when the
        axes do not span a turn (one of length 0, or x and y in a line)."""
        u = _unit(self.u)
        if u is None:
            return None
        v = _unit(_add(self.v, _times(u, -_dot(self.v, u))))
        if v is None:
            return None
        return Matrix(u, v, _cross(u, v))

    def finite(self) -> bool:
        return all(math.isfinite(x) for axis in (self.u, self.v, self.w, self.o) for x in axis)


IDENTITY: Final = Matrix()


def parse_matrix(text: str) -> Matrix | None:
    """An MVR matrix as written (``{1,0,0}{0,1,0}{0,0,1}{0,0,0}``); ``None``
    when it is not four groups of three finite numbers."""
    if _MATRIX.fullmatch(text) is None:
        return None
    rows: list[Vector] = []
    for row in _ROW.findall(text):
        parts = row.split(",")
        if len(parts) != 3:
            return None
        try:
            x, y, z = (float(part) for part in parts)
        except ValueError:
            return None
        rows.append((x, y, z))
    matrix = Matrix(*rows)
    return matrix if matrix.finite() else None


def _add(a: Vector, b: Vector) -> Vector:
    return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def _times(a: Vector, k: float) -> Vector:
    return a[0] * k, a[1] * k, a[2] * k


def _dot(a: Vector, b: Vector) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vector, b: Vector) -> Vector:
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def _unit(a: Vector) -> Vector | None:
    length = math.hypot(*a)
    return None if not 1e-9 < length < math.inf else _times(a, 1 / length)


# ------------------------------------------------------------------ the frame

_HUNG: Final = Matrix((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0))
"""R_x(180°): busk's zero (standing, beam up) to GDTF's (hanging, beam down)."""


def _about_z(cos: float, sin: float) -> Matrix:
    return Matrix((cos, sin, 0.0), (-sin, cos, 0.0))


def plot_location(matrix: Matrix, frame: StageFrame) -> Location:
    """Where a plot fixture at ``matrix`` (composed, in the plot) is in busk
    (MVR plan §5): metres to 4 decimals, degrees to 3, angles in (−180°, 180°].
    A matrix without a turn (:meth:`Matrix.rotation`) is read as none."""
    cos, sin = TURNS[frame["audience"]]
    turn = _about_z(cos, sin)
    x, y, z = turn.turn(_times(_add(matrix.o, _times(frame["origin"], -1)), 1 / 1000))
    r = turn @ (matrix.rotation() or IDENTITY) @ _HUNG
    ry = math.degrees(math.asin(max(-1.0, min(1.0, -r.u[2]))))
    if abs(r.u[2]) < 1 - 1e-12:
        rx = math.degrees(math.atan2(r.v[2], r.w[2]))
        rz = math.degrees(math.atan2(r.u[1], r.u[0]))
    else:  # ry ±90°: only rz − rx (or rz + rx) shows, so rx is 0
        rx, rz = 0.0, math.degrees(math.atan2(-r.v[0], r.v[1]))
    return Location(
        x=_round(x, 4), y=_round(y, 4), z=_round(z, 4),
        rx=_angle(rx), ry=_angle(ry), rz=_angle(rz),
    )  # fmt: skip


def location_matrix(location: Location, frame: StageFrame) -> Matrix:
    """The plot matrix of a fixture at ``location``: :func:`plot_location`
    turned back."""
    cos, sin = TURNS[frame["audience"]]
    rx, ry, rz = (
        math.radians(location["rx"]),
        math.radians(location["ry"]),
        math.radians(location["rz"]),
    )
    turn = (
        _about_z(math.cos(rz), math.sin(rz))
        @ Matrix(
            (math.cos(ry), 0.0, -math.sin(ry)), (0.0, 1.0, 0.0), (math.sin(ry), 0.0, math.cos(ry))
        )
        @ Matrix(
            (1.0, 0.0, 0.0), (0.0, math.cos(rx), math.sin(rx)), (0.0, -math.sin(rx), math.cos(rx))
        )
    )
    back = _about_z(cos, -sin)
    r = back @ turn @ _HUNG
    offset = back.turn((location["x"] * 1000, location["y"] * 1000, location["z"] * 1000))
    return Matrix(r.u, r.v, r.w, _add(offset, frame["origin"]))


def _round(value: float, digits: int) -> float:
    return round(value, digits) + 0.0  # never -0.0


def _angle(degrees: float) -> float:
    value = _round(degrees, 3)
    return 180.0 if value == -180 else value


# ------------------------------------------------------------------ the plot


@dataclass(frozen=True, slots=True, kw_only=True)
class PlotAddress:
    """A fixture's DMX address on one of its breaks (``dmx_break`` 0 is the
    first): ``universe`` from 1, ``address`` 1 to 512."""

    dmx_break: int
    universe: int
    address: int


@dataclass(frozen=True, slots=True, kw_only=True)
class PlotFixture:
    """A fixture of a plot, as it is drawn.

    ``fixture_id`` is ``FixtureID`` as written and ``fixture_id_numeric``
    ``FixtureIDNumeric`` (0 when it has none). ``gdtf`` is the GDTF file it
    names, a key of :attr:`Plot.types`, and ``mode`` its ``GDTFMode``. The
    ``matrix`` is composed: its layer and every parent applied. ``position``
    is the uuid of its hanging position, a key of :attr:`Plot.positions`.
    The inverts are ``None`` where the file does not say, and
    ``multipatch`` the uuid of the fixture it copies."""

    uuid: str
    name: str
    fixture_id: str
    fixture_id_numeric: int
    gdtf: str | None
    mode: str | None
    addresses: tuple[PlotAddress, ...]
    matrix: Matrix
    position: str | None
    invert_pan: bool | None
    invert_tilt: bool | None
    multipatch: str | None

    @property
    def label(self) -> str:
        """How a note names it: its name in quotes, else its FixtureID, else its uuid."""
        return _who(self.name, self.fixture_id, self.uuid)


@dataclass(frozen=True, slots=True, kw_only=True)
class PlotType:
    """A GDTF file the plot's fixtures name: its profile and the import's
    notes, or why it could not be imported (``problem``)."""

    file: str
    report: ImportReport | None
    problem: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Scenery:
    """A model of the plot's scenery: the object it belongs to (its ``kind``,
    such as ``Truss``, and ``name``), its file in the archive (no extension
    means 3DS) and its composed matrix."""

    kind: str
    name: str
    model: str
    matrix: Matrix


@dataclass(frozen=True, slots=True, kw_only=True)
class Plot:
    """What a plot holds that busk reads, in the order it holds it.
    ``positions`` are the hanging positions' names, by uuid; ``sha256`` is
    that of the file's bytes, in hex."""

    fixtures: tuple[PlotFixture, ...]
    types: Mapping[str, PlotType]
    positions: Mapping[str, str]
    scenery: tuple[Scenery, ...]
    notes: tuple[str, ...]
    sha256: str


def read_plot(path: str | os.PathLike[str]) -> Plot:
    """Read the MVR file at ``path``. Raises :class:`ImportFailed`, saying
    why, for a file that cannot be read, is not an MVR file or is past the
    caps."""
    try:
        with open(path, "rb") as file:
            sha256 = hashlib.file_digest(file, "sha256").hexdigest()
            file.seek(0)
            with zipfile.ZipFile(file) as archive:
                return _Reader(archive).plot(sha256)
    except ImportFailed:
        raise
    except (zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, NotImplementedError) as exc:
        raise ImportFailed(f"not an MVR file: {exc}") from exc
    except OSError as exc:
        raise ImportFailed(str(exc)) from exc


class _TooBig(Exception):
    pass


class _Reader:
    def __init__(self, archive: zipfile.ZipFile) -> None:
        infos = archive.infolist()
        if len(infos) > MEMBER_CAP:
            raise ImportFailed(f"the plot holds more than {MEMBER_CAP:,} files; not read")
        if sum(info.file_size for info in infos) > UNPACKED_CAP:
            raise ImportFailed(
                f"the plot unpacks to more than {UNPACKED_CAP // _MB:,} MB; not read"
            )
        self.archive = archive
        self.names = {info.filename for info in infos}
        self.notes: dict[str, None] = {}  # in order, each once
        self.fixtures: dict[str, PlotFixture] = {}
        self.positions: dict[str, str] = {}
        self.symdefs: dict[str, ET.Element] = {}
        self.scenery: list[Scenery] = []
        self.expanded = 0  # geometry nodes read, against GEOMETRY_CAP

    def note(self, text: str) -> None:
        self.notes[text] = None

    def plot(self, sha256: str) -> Plot:
        if SCENE not in self.names:
            raise ImportFailed(f"not an MVR file: it has no {SCENE}")
        try:
            data = _member(self.archive, SCENE, SCENE_CAP)
        except _TooBig:
            raise ImportFailed(f"{SCENE} is larger than {SCENE_CAP // _MB} MB; not read") from None
        root = parse_description(data, SCENE)
        scene = root.find("Scene")
        if root.tag != "GeneralSceneDescription" or scene is None:
            raise ImportFailed(f"not an MVR file: {SCENE} has no GeneralSceneDescription/Scene")
        for node in scene.iterfind("AUXData/Position"):
            uuid, name = _uuid(node.get("uuid")), (node.get("name") or "").strip()
            if uuid and name:
                self.positions.setdefault(uuid, name)
        for node in scene.iterfind("AUXData/Symdef"):
            self.symdefs.setdefault(_uuid(node.get("uuid")), node)
        for layer in scene.iterfind("Layers/Layer"):
            matrix = self.matrix(layer, f"layer {_who(layer.get('name'), '', layer.get('uuid'))}")
            stack = [(child, matrix) for child in reversed(_children(layer))]
            while stack:
                node, parent = stack.pop()
                here = parent @ self.matrix(node, _object(node))
                if node.tag == "Fixture":
                    self.fixture(node, here)
                elif node.tag in SCENERY:
                    for geometry in node.iterfind("Geometries/*"):
                        self.geometry(node, geometry, here, 0)
                stack += [(child, here) for child in reversed(_children(node))]
        types: dict[str, PlotType] = {}
        for fixture in self.fixtures.values():
            if fixture.gdtf is not None and fixture.gdtf not in types:
                types[fixture.gdtf] = self.fixture_type(fixture.gdtf)
        return Plot(
            fixtures=tuple(self.fixtures.values()),
            types=types,
            positions=self.positions,
            scenery=tuple(self.scenery),
            notes=tuple(self.notes),
            sha256=sha256,
        )

    def matrix(self, node: ET.Element, who: str) -> Matrix:
        text = node.findtext("Matrix")
        if text is None:
            return IDENTITY
        matrix = parse_matrix(text)
        if matrix is None:
            self.note(f"{who}: matrix {_quoted(text)} not read, taken as none")
            return IDENTITY
        return matrix

    def fixture(self, node: ET.Element, matrix: Matrix) -> None:
        uuid, name = _uuid(node.get("uuid")), (node.get("name") or "").strip()
        fixture_id = _text(node, "FixtureID") or ""
        who = _who(name, fixture_id, uuid)
        if not uuid:
            self.note(f"{who} has no uuid, left out")
            return
        if uuid in self.fixtures:
            self.note(f"{who} has the uuid of {self.fixtures[uuid].label}, left out")
            return
        if not matrix.finite():
            self.note(f"{who}: its matrices compose past any number, taken as none")
            matrix = IDENTITY
        elif matrix.rotation() is None:
            self.note(f"{who}: its matrix has no turn, taken as none")
        addresses: list[PlotAddress] = []
        for address in node.iterfind("Addresses/Address"):
            read = _address(address.get("break", "0"), (address.text or "").strip())
            if read is None:
                self.note(f"{who}: address {_quoted(address.text or '')} not read")
            else:
                addresses.append(read)
        numeric = _text(node, "FixtureIDNumeric") or ""
        position = _uuid(_text(node, "Position"))
        self.fixtures[uuid] = PlotFixture(
            uuid=uuid,
            name=name,
            fixture_id=fixture_id,
            fixture_id_numeric=int(numeric) if _NUMBER.fullmatch(numeric) else 0,
            gdtf=_text(node, "GDTFSpec"),
            mode=_text(node, "GDTFMode"),
            addresses=tuple(addresses),
            matrix=matrix,
            position=position if position in self.positions else None,
            invert_pan=_boolean(_text(node, "DMXInvertPan")),
            invert_tilt=_boolean(_text(node, "DMXInvertTilt")),
            multipatch=_uuid(node.get("multipatch")) or None,
        )

    def geometry(self, owner: ET.Element, node: ET.Element, parent: Matrix, depth: int) -> None:
        """A ``Geometry3D`` or ``Symbol`` of ``owner``'s, placed in ``parent``."""
        if self.expanded >= GEOMETRY_CAP:
            self.note(f"the scenery expands to more than {GEOMETRY_CAP:,} models and symbols; "
                      "the rest left out")  # fmt: skip
            return
        self.expanded += 1
        here = parent @ self.matrix(node, _object(owner))
        if node.tag == "Geometry3D":
            model = (node.get("fileName") or "").strip()
            if model not in self.names:
                self.note(f"model {_quoted(model)} is not in the plot")
            elif here.finite():
                kind, name = owner.tag, (owner.get("name") or "").strip()
                self.scenery.append(Scenery(kind=kind, name=name, model=model, matrix=here))
        elif node.tag == "Symbol":
            symdef = self.symdefs.get(_uuid(node.get("symdef")))
            if symdef is None:
                self.note(f"{_object(owner)}: a symbol names no Symdef")
            elif depth >= SYMBOL_DEPTH:
                self.note(f"symbols nest more than {SYMBOL_DEPTH} deep; the rest left out")
            else:
                for child in symdef.iterfind("ChildList/*"):
                    self.geometry(owner, child, here, depth + 1)

    def fixture_type(self, file: str) -> PlotType:
        name = file
        if name not in self.names and not name.lower().endswith(".gdtf"):
            name += ".gdtf"
        if name not in self.names:
            return PlotType(file=file, report=None, problem="is not in the plot")
        try:
            data = _member(self.archive, name, GDTF_CAP)
            with zipfile.ZipFile(io.BytesIO(data)) as gdtf:
                description = _description(gdtf)
            return PlotType(file=file, report=import_gdtf(description), problem=None)
        except _TooBig:
            problem = f"is larger than {GDTF_CAP // _MB} MB, not read"
        except ImportFailed as exc:
            problem = f"cannot be imported: {exc}"
        except (OSError, zipfile.BadZipFile, zlib.error, EOFError, RuntimeError,
                NotImplementedError) as exc:  # fmt: skip
            problem = f"cannot be imported: not a GDTF file: {exc}"
        return PlotType(file=file, report=None, problem=problem)


def _member(archive: zipfile.ZipFile, name: str, cap: int) -> bytes:
    """The file ``name`` of ``archive``; :class:`_TooBig` above ``cap`` bytes
    (by its declared size, and by what it really inflates to)."""
    info = archive.getinfo(name)
    if info.file_size > cap:
        raise _TooBig
    with archive.open(info) as member:
        data = member.read(cap + 1)
    if len(data) > cap:
        raise _TooBig
    return data


def _children(node: ET.Element) -> list[ET.Element]:
    return [child for child in node.iterfind("ChildList/*") if child.tag in OBJECTS]


def _text(node: ET.Element, tag: str) -> str | None:
    """The text of ``node``'s child ``tag``, stripped; ``None`` when empty."""
    return (node.findtext(tag) or "").strip() or None


def _uuid(text: str | None) -> str:
    return (text or "").strip().upper()


def _boolean(text: str | None) -> bool | None:
    return {"true": True, "1": True, "false": False, "0": False}.get((text or "").lower())


def _address(dmx_break: str, text: str) -> PlotAddress | None:
    """``Address`` as written: absolute (1 is universe 1, address 1; 513 is
    universe 2, address 1) or ``Universe.Address``."""
    if _NUMBER.fullmatch(dmx_break.strip()) is None:
        return None
    if _NUMBER.fullmatch(text) is not None and int(text) >= 1:
        absolute = int(text) - 1
        universe, address = absolute // 512 + 1, absolute % 512 + 1
    elif (match := _UNIVERSE_ADDRESS.fullmatch(text)) is not None:
        universe, address = int(match[1]), int(match[2])
    else:
        return None
    if universe < 1 or not 1 <= address <= 512:
        return None
    return PlotAddress(dmx_break=int(dmx_break), universe=universe, address=address)


def _quoted(text: str, limit: int = 60) -> str:
    """Text from the plot for a note: in quotes, escaped, cut to ``limit``."""
    quoted = json.dumps(text, ensure_ascii=False)
    return quoted if len(quoted) <= limit else quoted[: limit - 1] + "…"


def _who(name: str | None, fixture_id: str, uuid: str | None) -> str:
    """A fixture (or layer) for a note: its name, else its FixtureID, else its uuid."""
    if name:
        return _quoted(name.strip())
    if fixture_id:
        return f"FixtureID {_quoted(fixture_id)}"
    return f"uuid {_quoted(_uuid(uuid))}" if uuid else "a fixture with no name"


def _object(node: ET.Element) -> str:
    """An object for a note: ``Truss "LX1"``."""
    name = (node.get("name") or "").strip()
    return f"{node.tag} {_quoted(name)}" if name else node.tag
