"""The limitation report: show features this build accepts but ignores (phase-2-plan §5.3).

A show is valid against the whole schema, but this build implements only the
busking core (Phase 2), the programmer and recording (Phase 3), time:
sequences, fades, chases and speed masters (Phase 4), and effects with
their ``size`` faders and size masters, and group masters (Phase 5), and
pages, playback buttons, swop, soft takeover, fade-time masters and
``crossfade`` faders, OSC and web surfaces and feedback (Phase 6), and park,
fixture limits, the strobe-rate cap, highlight, the panic commands and a
stall that darkens the stage (Phase 7). ``busk run`` prints every feature
the show uses that does nothing yet, under ``Ignored in Phase 7:``, one line
each with its path, so an operator never has to wonder why a fader or button
does nothing (phase-6-plan §5.18, phase-7-plan §5.22):
``hid`` and ``internal`` surfaces, and ``hw`` inputs (no phase of the
roadmap has them yet); feedback a binding cannot show (``display`` on a
MIDI surface, any feedback on a ``command`` action).

Art-Net and DMX-USB routes are not listed here: the output scheduler already
reports them as ignored, next to the routes it opens.
"""

from __future__ import annotations

from dataclasses import dataclass

from busk.commands.bus import unsupported_reason
from busk.compiler.compile import CompiledShow
from busk.model.show import Show


@dataclass(frozen=True, slots=True)
class Limitation:
    """One ignored feature, at a path into the show document."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def collect_limitations(show: Show, compiled: CompiledShow) -> list[Limitation]:
    """Every feature ``show`` uses that this build ignores, in document order."""
    found: list[Limitation] = []

    def ignored(path: str, message: str) -> None:
        found.append(Limitation(path, message))

    served = {}  # the surfaces this build opens: id → kind
    for s, surface in enumerate(show["surfaces"]):
        if surface["kind"] == "web":
            continue  # served; validation warns about bindings on it
        if surface["kind"] not in ("midi", "osc"):
            ignored(f"surfaces[{s}].kind", f"{surface['kind']} surfaces are not implemented")
            continue
        served[surface["id"]] = surface["kind"]

    for b, binding in enumerate(show["bindings"]):
        path = f"bindings[{b}]"
        kind = served.get(binding["surfaceId"])
        if kind is None:
            continue  # its surface is reported, is a web remote, or does not exist
        if binding["input"]["kind"] == "hw":
            ignored(f"{path}.input", "hw inputs are not implemented")
            continue
        action = binding["action"]
        if action["kind"] == "command":
            reason = unsupported_reason(action["command"], compiled)
            if reason is not None:
                ignored(f"{path}.action.command", reason)
        feedback = binding.get("feedback")
        if feedback is None:
            continue
        if action["kind"] == "command":
            ignored(f"{path}.feedback", "a command action has no state to show")
        elif feedback["kind"] == "display" and kind == "midi":
            ignored(f"{path}.feedback", "MIDI surfaces cannot show display feedback")
    return found
