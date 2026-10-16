"""Synthetic GDTF files for the import tests (phase-7-plan §5.19, step 15).

No real GDTF file exists on this machine (the GDTF Share needs an account),
so the tests write their own from DIN SPEC 15800: small builders return
:class:`xml.etree.ElementTree.Element` nodes, :func:`description` assembles a
``description.xml`` and :func:`archive` zips it as a ``.gdtf`` file.

Attributes are spelled as in GDTF 1.1: a function's ``Default``, a
channel's ``Highlight`` and ``InitialFunction``, DMX values as
``value/bytes``.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

TYPE_ID = "6E3A1F52-0D4B-4C3B-9F51-1A2B3C4D5E6F"
D65 = "0.312700,0.329000,100.000000"
SRGB_RED = "0.640000,0.330000,21.260000"
SRGB_GREEN = "0.300000,0.600000,71.520000"
SRGB_BLUE = "0.150000,0.060000,7.220000"


def _node(tag: str, children: tuple[ET.Element, ...] = (), **attributes: object) -> ET.Element:
    node = ET.Element(tag, {k: str(v) for k, v in attributes.items() if v is not None})
    node.extend(children)
    return node


def channel_set(name: str, dmx_from: str, slot: int | None = None) -> ET.Element:
    """A ``ChannelSet`` (``slot``: its ``WheelSlotIndex``, 1-based)."""
    return _node("ChannelSet", Name=name, DMXFrom=dmx_from, WheelSlotIndex=slot)


def function(
    attribute: str,
    dmx_from: str = "0/1",
    physical: tuple[float, float] = (0, 1),
    *sets: ET.Element,
    name: str | None = None,
    wheel: str | None = None,
    emitter: str | None = None,
    default: str = "0/1",
    mode_master: str | None = None,
    dmx_profile: str | None = None,
) -> ET.Element:
    """A ``ChannelFunction``."""
    return _node(
        "ChannelFunction",
        sets,
        Name=name or attribute,
        Attribute=attribute,
        DMXFrom=dmx_from,
        Default=default,
        PhysicalFrom=physical[0],
        PhysicalTo=physical[1],
        Wheel=wheel,
        Emitter=emitter,
        ModeMaster=mode_master,
        ModeFrom="0/1" if mode_master else None,
        ModeTo="127/1" if mode_master else None,
        DMXProfile=dmx_profile,
    )


def channel(
    offset: str | None,
    *functions: ET.Element,
    geometry: str = "Beam",
    attribute: str | None = None,
    dmx_break: str = "1",
    highlight: str = "None",
    initial: str | None = None,
) -> ET.Element:
    """A ``DMXChannel`` with one ``LogicalChannel`` (``offset`` ``None``: a
    virtual channel). The logical channel's attribute defaults to the first
    function's."""
    logical = _node(
        "LogicalChannel", functions, Attribute=attribute or functions[0].get("Attribute")
    )
    return _node(
        "DMXChannel",
        (logical,),
        DMXBreak=dmx_break,
        Offset=offset if offset is not None else "",
        Highlight=highlight,
        Geometry=geometry,
        InitialFunction=initial,
    )


def mode(
    name: str,
    *channels: ET.Element,
    geometry: str = "Base",
    relations: bool = False,
    macros: bool = False,
) -> ET.Element:
    """A ``DMXMode`` (``relations``/``macros``: one of each, to be reported)."""
    extra: list[ET.Element] = [_node("DMXChannels", channels)]
    relation = _node("Relation", Name="R", Master="a", Follower="b", Type="Multiply")
    extra.append(_node("Relations", (relation,) if relations else ()))
    extra.append(_node("FTMacros", (_node("FTMacro", Name="Reset"),) if macros else ()))
    return _node("DMXMode", tuple(extra), Name=name, Geometry=geometry)


def slot(name: str, color: str | None = None, facets: int = 0) -> ET.Element:
    """A wheel ``Slot`` (``facets``: prism facets)."""
    return _node("Slot", tuple(_node("Facet", Color=D65) for _ in range(facets)),
                 Name=name, Color=color)  # fmt: skip


def wheel(name: str, *slots: ET.Element) -> ET.Element:
    return _node("Wheel", slots, Name=name)


def emitter(name: str, color: str) -> ET.Element:
    return _node("Emitter", Name=name, Color=color)


def geometry(tag: str, name: str, *children: ET.Element) -> ET.Element:
    """A geometry node (``Geometry``, ``Axis``, ``Beam`` …)."""
    return _node(tag, children, Name=name, Model=name)


def reference(name: str, referenced: str, *breaks: tuple[str, int]) -> ET.Element:
    """A ``GeometryReference`` with its ``Break``\\ s ``(DMXBreak, DMXOffset)``."""
    nodes = tuple(_node("Break", DMXBreak=b, DMXOffset=o) for b, o in breaks)
    return _node("GeometryReference", nodes, Name=name, Geometry=referenced, Model=referenced)


BASE = geometry("Geometry", "Base", geometry("Beam", "Beam"))
"""The default geometry: one beam."""


def description(
    *modes: ET.Element,
    name: str = "Thing",
    manufacturer: str = "Acme",
    type_id: str = TYPE_ID,
    wheels: tuple[ET.Element, ...] = (),
    emitters: tuple[ET.Element, ...] = (),
    geometries: tuple[ET.Element, ...] = (BASE,),
    revisions: tuple[str, ...] = ("2024-03-01T10:00:00",),
) -> bytes:
    """A ``description.xml`` with the given modes."""
    fixture = _node(
        "FixtureType",
        (
            _node("AttributeDefinitions"),
            _node("Wheels", wheels),
            _node("PhysicalDescriptions", (_node("Emitters", emitters),)),
            _node("Geometries", geometries),
            _node("DMXModes", modes),
            _node("Revisions", tuple(_node("Revision", Date=d, Text="") for d in revisions)),
        ),
        Name=name,
        ShortName=name,
        LongName=name,
        Manufacturer=manufacturer,
        Description="",
        FixtureTypeID=type_id,
    )
    root = _node("GDTF", (fixture,), DataVersion="1.1")
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root)


def archive(path: Path, data: bytes, member: str = "description.xml") -> Path:
    """Write ``data`` as ``member`` of a GDTF (ZIP) archive at ``path``."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(member, data)
    return path
