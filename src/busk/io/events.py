"""Input events: the boundary between input backends and bindings (spec §5.15).

A backend (MIDI now; OSC, HID and web in Phase 6) turns whatever its device
sends into input events (:class:`InputEvent`): *which control* (an
:data:`~busk.model.surface.InputAddress`, exactly as bindings write it) moved
to *which value* (``0..1``). Bindings never see backend messages, so a
backend can be swapped without touching them. An event also keeps the
number the device sent (``raw``), for the input monitor (GAP-13 of
``docs/dev/tui/engine-gaps.md``): bindings never read it.
"""

from __future__ import annotations

from dataclasses import dataclass

from busk.model.common import SurfaceId
from busk.model.surface import InputAddress

type AddressKey = tuple[str, int | str, int] | tuple[str, int | str] | tuple[str]
"""A hashable form of an input address, for indexing bindings."""


@dataclass(frozen=True, slots=True)
class InputEvent:
    """A control on a surface moved to ``value`` (``0..1``). ``raw`` is the
    number the device sent, where it sent one: a CC's value and a note's
    velocity (0–127), a pitch bend's pitch (−8192–8191); ``None`` for OSC
    and the MIDI clock."""

    surfaceId: SurfaceId
    address: InputAddress
    value: float
    raw: int | None = None


def address_key(address: InputAddress) -> AddressKey:
    """The hashable key of an input address: ``("midiCC", channel, cc)`` etc."""
    if address["kind"] == "midiCC":
        return ("midiCC", address["channel"], address["cc"])
    if address["kind"] == "midiNote":
        return ("midiNote", address["channel"], address["note"])
    if address["kind"] == "midiPitchBend":
        return ("midiPitchBend", address["channel"])
    if address["kind"] == "midiClock":
        return ("midiClock",)
    if address["kind"] == "osc":
        return ("osc", address["path"])
    return ("hw", address["controlId"])
