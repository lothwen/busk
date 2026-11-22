"""Synthetic MVR plots for the plot tests (MVR plan Phase 2, step 3).

As :mod:`gdtf_builder` writes GDTF files, this writes MVR files from DIN SPEC
15801 (MVR 1.6): small builders return :class:`xml.etree.ElementTree.Element`
nodes, :func:`scene` assembles a ``GeneralSceneDescription.xml`` and
:func:`plot` zips it with the files it names. :func:`spot` is a GDTF fixture
type of a dimmer, pan and tilt, ``Acme@Spot.gdtf`` by default.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from xml.etree import ElementTree as ET

from gdtf_builder import channel, description, function, mode

SPOT = "Acme@Spot.gdtf"
"""The GDTF file :func:`fixture` names unless told otherwise."""

type Vector = tuple[float, float, float]


def matrix(
    u: Vector = (1, 0, 0), v: Vector = (0, 1, 0), w: Vector = (0, 0, 1), o: Vector = (0, 0, 0)
) -> str:
    """A matrix as MVR writes it: ``{u}{v}{w}{o}``."""
    return "".join("{" + ",".join(f"{x:g}" for x in axis) + "}" for axis in (u, v, w, o))


def _node(tag: str, children: Sequence[ET.Element] = (), **attributes: object) -> ET.Element:
    node = ET.Element(tag, {k: str(v) for k, v in attributes.items() if v is not None})
    node.extend(children)
    return node


def _text(tag: str, text: object) -> ET.Element:
    node = ET.Element(tag)
    node.text = str(text)
    return node


def _object(
    tag: str,
    uuid: str,
    name: str | None,
    fields: Sequence[ET.Element],
    at: str | None,
    children: Sequence[ET.Element],
    **attributes: object,
) -> ET.Element:
    nodes = [_text("Matrix", at)] if at is not None else []
    nodes += fields
    if children:
        nodes.append(_node("ChildList", children))
    return _node(tag, nodes, uuid=uuid, name=name, **attributes)


def fixture(
    uuid: str,
    name: str | None = "",
    *,
    gdtf: str | None = SPOT,
    gdtf_mode: str | None = "3ch",
    fixture_id: str | None = None,
    numeric: object = None,
    addresses: Sequence[tuple[str | None, str]] = (),
    at: str | None = None,
    position: str | None = None,
    invert_pan: str | None = None,
    invert_tilt: str | None = None,
    multipatch: str | None = None,
    children: Sequence[ET.Element] = (),
) -> ET.Element:
    """A ``Fixture``; ``addresses`` are ``(break, value)``, a break of
    ``None`` leaving the attribute out."""
    fields = []
    for tag, value in (("GDTFSpec", gdtf), ("GDTFMode", gdtf_mode), ("Position", position)):
        if value is not None:
            fields.append(_text(tag, value))
    if addresses:
        nodes = []
        for dmx_break, value in addresses:
            node = _text("Address", value)
            if dmx_break is not None:
                node.set("break", dmx_break)
            nodes.append(node)
        fields.append(_node("Addresses", nodes))
    for tag, value in (
        ("FixtureID", fixture_id),
        ("FixtureIDNumeric", numeric),
        ("DMXInvertPan", invert_pan),
        ("DMXInvertTilt", invert_tilt),
    ):
        if value is not None:
            fields.append(_text(tag, value))
    return _object("Fixture", uuid, name, fields, at, children, multipatch=multipatch)


def scenery(
    tag: str,
    uuid: str,
    name: str | None,
    *geometries: ET.Element,
    at: str | None = None,
    children: Sequence[ET.Element] = (),
) -> ET.Element:
    """A ``Truss``, ``Support``, ``SceneObject``, ``VideoScreen`` or ``Projector``."""
    return _object(tag, uuid, name, [_node("Geometries", geometries)], at, children)


def group(uuid: str, name: str, *children: ET.Element, at: str | None = None) -> ET.Element:
    """A ``GroupObject``."""
    return _object("GroupObject", uuid, name, [], at, children)


def model(file: str, at: str | None = None) -> ET.Element:
    """A ``Geometry3D``."""
    return _node("Geometry3D", [_text("Matrix", at)] if at else [], fileName=file)


def symbol(uuid: str, symdef: str, at: str | None = None) -> ET.Element:
    """A ``Symbol`` placing a ``Symdef``."""
    return _node("Symbol", [_text("Matrix", at)] if at else [], uuid=uuid, symdef=symdef)


def symdef(uuid: str, name: str, *geometries: ET.Element) -> ET.Element:
    return _node("Symdef", [_node("ChildList", geometries)], uuid=uuid, name=name)


def position(uuid: str, name: str) -> ET.Element:
    """A hanging ``Position`` of ``AUXData``."""
    return _node("Position", uuid=uuid, name=name)


def layer(uuid: str, name: str, *children: ET.Element, at: str | None = None) -> ET.Element:
    return _object("Layer", uuid, name, [], at, children)


def scene(*layers: ET.Element, aux: Sequence[ET.Element] = ()) -> bytes:
    """A ``GeneralSceneDescription.xml`` of ``layers``, with ``aux`` (positions
    and symdefs) in its ``AUXData``."""
    body = _node("Scene", [_node("AUXData", aux), _node("Layers", layers)])
    root = _node("GeneralSceneDescription", [body], verMajor=1, verMinor=6, provider="tests")
    return b'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n' + ET.tostring(root)


def spot(name: str = "Spot", type_id: str | None = None) -> bytes:
    """A GDTF fixture type, ``Acme <name>``: mode ``3ch`` of a dimmer, pan
    and tilt (±270°, ±135°), mode ``1ch`` of the dimmer alone."""
    dimmer = channel("1", function("Dimmer"))
    pan = channel("2", function("Pan", physical=(-270, 270)))
    tilt = channel("3", function("Tilt", physical=(-135, 135)))
    modes = (mode("3ch", dimmer, pan, tilt), mode("1ch", channel("1", function("Dimmer"))))
    kwargs = {"type_id": type_id} if type_id is not None else {}
    return description(*modes, name=name, manufacturer="Acme", **kwargs)


def gdtf(data: bytes | None = None) -> bytes:
    """``data`` (a description, :func:`spot` by default) zipped as a GDTF file."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr("description.xml", data if data is not None else spot())
    return buffer.getvalue()


def plot(path: Path, data: bytes, files: Mapping[str, bytes] | None = None) -> Path:
    """Write the scene ``data`` and ``files`` (by name; :data:`SPOT` by
    default) as an MVR file at ``path``."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr("GeneralSceneDescription.xml", data)
        for name, content in (files if files is not None else {SPOT: gdtf()}).items():
            zipped.writestr(name, content)
    return path
