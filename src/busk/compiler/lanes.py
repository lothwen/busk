"""Encoding attribute values into lanes (spec §6.2).

:func:`encode_value` turns a show value (a number, a colour or a discrete
value) into the float lanes of a given slot. The cue compiler
(:mod:`busk.compiler.cues`) and the values file both use it.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, cast

from busk.model.attributes import AttributeValue, ColorValue, DiscreteValue
from busk.model.common import target_key

if TYPE_CHECKING:
    from busk.compiler.slots import Slot


class EncodeError(ValueError):
    """A value cannot be encoded for a slot (e.g. an option it does not offer).

    The caller decides what that means: the values file reports an error;
    the cue compiler drops the value for that target with a warning, as §6.3
    drops entries whose attribute does not exist on a target.
    """


def encode_value(slot: Slot, value: AttributeValue) -> tuple[float, ...]:
    """Encode ``value`` as the lanes of ``slot``.

    * scalar → ``(v,)``;
    * colour → ``(r, g, b, *extras)``. An extra the value leaves out is
      ``NaN`` ("derive it"); an extra the element does not have is dropped,
      so a colour preset with ``uv`` still works on a fixture without UV;
    * discrete → ``(index of the option,)``. Raises :class:`EncodeError` if
      the slot does not offer the option.

    ``value`` must already have the attribute's shape (validation checks it).
    The optional ``wheel`` of a discrete value is not checked here; see
    :attr:`Slot.wheels <busk.compiler.slots.Slot.wheels>`.
    """
    kind = slot.attribute.kind
    if kind == "scalar":
        return (float(cast(float, value)),)
    if kind == "color":
        color = cast(ColorValue, value)
        rgb = (float(color["r"]), float(color["g"]), float(color["b"]))
        return rgb + tuple(float(color.get(extra, math.nan)) for extra in slot.extras)
    option = cast(DiscreteValue, value)["slot"]
    try:
        return (float(slot.options.index(option)),)
    except ValueError:
        raise EncodeError(
            f"{target_key(slot.target)} has no {slot.attribute.id!r} option {option!r}; "
            f"it offers {', '.join(repr(o) for o in slot.options)}"
        ) from None
