"""Base logical frames from a values file (``busk run --values``).

A values file sets what slots output when no playback controls them: the
resolver starts each tick from this frame instead of the slot defaults, and
playbacks layer on top of it. (In Phase 1, before the resolver, it was the
engine's whole static output.) :func:`compile_values` is the last of the
values file's three checks (the first two are
:func:`busk.model.validate.validate_values`): it checks each entry against
the compiled show and writes it into the frame.

Values-file entries are stricter than cue entries. An attribute the target
does not have, or a discrete ``slot`` that is not one of the channel's
options, is an **error** here, while a cue entry in that situation is
silently dropped (§6.3).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import numpy as np
from numpy.typing import NDArray

from busk.compiler.compile import CompiledShow
from busk.compiler.lanes import EncodeError, encode_value
from busk.model.attributes import DiscreteValue
from busk.model.show import ParkEntry
from busk.model.validate import Issue, has_errors


def compile_values(
    compiled: CompiledShow, entries: Sequence[ParkEntry]
) -> tuple[NDArray[np.float64] | None, list[Issue]]:
    """Build the logical frame for ``entries`` (which passed
    :func:`~busk.model.validate.validate_values`).

    The frame starts as a copy of the default frame; each entry then
    overwrites its slot's lanes, so a later entry for the same slot wins.
    Returns the read-only frame and no issues, or ``None`` and every issue
    found, with paths like ``values[3].slot.attribute``.
    """
    frame = compiled.slots.defaultFrame.copy()
    issues: list[Issue] = []
    for index, entry in enumerate(entries):
        path = f"values[{index}]"
        target, attribute = entry["slot"]["target"], entry["slot"]["attribute"]
        slot = compiled.slots.find(target, attribute)
        if slot is None:
            issues.append(
                Issue(
                    "error",
                    f"{path}.slot.attribute",
                    f"Fixture {target['fixtureId']!r} element {target['element']} has no "
                    f"{attribute!r}",
                )
            )
            continue
        value = entry["value"]
        if slot.attribute.kind == "discrete":
            wheel = cast(DiscreteValue, value).get("wheel")
            if wheel is not None and wheel not in slot.wheels:
                offered = ", ".join(repr(w) for w in slot.wheels) or "none"
                issues.append(
                    Issue(
                        "error",
                        f"{path}.value.wheel",
                        f"The {attribute!r} channel is not on wheel {wheel!r} "
                        f"(its wheels: {offered})",
                    )
                )
                continue
        try:
            lanes = encode_value(slot, value)
        except EncodeError as exc:
            issues.append(Issue("error", f"{path}.value.slot", str(exc)))
            continue
        frame[slot.lanes] = lanes
    if has_errors(issues):
        return None, issues
    frame.flags.writeable = False
    return frame, issues
