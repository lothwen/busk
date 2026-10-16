"""Shared building blocks of the show schema (spec §5.1, §5.6).

Conventions used by every model module
--------------------------------------
* **Plain data.** Persistent structures are ``TypedDict``s, so a validated show
  is ordinary JSON-shaped data. Field names keep the spec's camelCase because
  they *are* the JSON keys; that keeps code and spec greppable.
* **Strict by default.** Every ``TypedDict`` is decorated with
  ``@with_config(STRICT)``. Unknown keys are errors (a typo in a hand-written
  show must not be silently ignored) and ``NaN``/``Infinity`` are rejected.
  The config is *not* inherited by ``TypedDict`` subclasses, so each class
  carries its own decorator; ``tests/test_schema.py`` checks that none is
  missing.
* **Tagged unions.** Unions with a ``kind`` / ``type`` / ``protocol`` tag are
  wrapped in ``Annotated[..., Field(discriminator=...)]`` so validation errors
  name the one member that applies instead of listing every alternative.
* **Simple ranges** are declared structurally with the ``Annotated`` aliases
  below. Rules spanning several fields or entities live in the semantic pass
  of ``busk.model.validate``.
* ``from __future__ import annotations`` keeps forward references working on
  Python 3.12. Referenced names must be imported at module level (not under
  ``TYPE_CHECKING``) so pydantic can resolve the string annotations.
"""

from __future__ import annotations

import re
from typing import Annotated, Final, Generic, NewType, NotRequired, TypedDict, TypeVar

from pydantic import ConfigDict, Field, with_config

# --------------------------------------------------------------------------- ids
# Every entity has an immutable opaque `id` used for all references (§5.1).

FixtureId = NewType("FixtureId", str)
ProfileId = NewType("ProfileId", str)
ModeId = NewType("ModeId", str)
GroupId = NewType("GroupId", str)
PresetId = NewType("PresetId", str)
CueListId = NewType("CueListId", str)
CueId = NewType("CueId", str)
PlaybackId = NewType("PlaybackId", str)
EffectId = NewType("EffectId", str)
MasterId = NewType("MasterId", str)
UniverseId = NewType("UniverseId", str)
SurfaceId = NewType("SurfaceId", str)

type AttributeId = str
"""An attribute name from the registry (§5.3), e.g. ``"pan"``."""

# ---------------------------------------------------------------- strictness

STRICT: Final = ConfigDict(extra="forbid", allow_inf_nan=False)
"""Pydantic config applied to every show ``TypedDict`` (see module docs)."""

# ------------------------------------------------------- constrained numbers

Unit = Annotated[float, Field(ge=0, le=1)]
"""A normalised quantity in ``0.0 – 1.0`` (intensity, colour components, levels)."""

Seconds = Annotated[float, Field(ge=0)]
"""A non-negative duration in seconds (fades, delays, release times)."""

DmxAddress = Annotated[int, Field(ge=1, le=512)]
"""A 1-based DMX start channel within a universe."""

NonNegativeInt = Annotated[int, Field(ge=0)]
"""Zero or a positive integer (0-based offsets and indices)."""

PositiveInt = Annotated[int, Field(ge=1)]
"""An integer ≥ 1 (1-based numbers, counts)."""

# -------------------------------------------------------------------- entity


TId = TypeVar("TId", bound=str)


@with_config(STRICT)
class EntityBase(TypedDict, Generic[TId]):  # noqa: UP046 — see below
    """Fields shared by every top-level entity (§5.1).

    ``TId`` is bound to ``str`` on purpose. Pydantic does not substitute the
    type parameter of a generic ``TypedDict`` base, so it validates ``id``
    against the bound; with an unbounded parameter any JSON value would be
    accepted as an id. Every id type is a ``NewType`` of ``str``, so the bound
    is exactly the runtime truth, while type checkers still see the precise id
    type (``ProfileId``, ``FixtureId`` …).

    ``TId`` is a module-level ``TypeVar`` rather than a PEP 695 class
    parameter (``class EntityBase[TId: str]``): with postponed annotations,
    pydantic resolves the string ``"TId"`` in this module's globals, and on
    Python 3.12–3.13 a PEP 695 parameter is not there.
    """

    id: TId
    name: str
    notes: NotRequired[str]
    tags: NotRequired[list[str]]


# ------------------------------------------------------------------- targets


@with_config(STRICT)
class TargetRef(TypedDict):
    """A ``(fixture, element)`` pair: the smallest thing an attribute belongs to (§5.6)."""

    fixtureId: FixtureId
    element: NonNegativeInt  # 0 for single-element fixtures


type TargetKey = str
"""Canonical string form of a :class:`TargetRef`: ``f"{fixtureId}:{element}"``."""

_TARGET_KEY = re.compile(r"(?P<fixture>.+):(?P<element>0|[1-9][0-9]*)")


def target_key(ref: TargetRef) -> TargetKey:
    """Format ``ref`` as its canonical :data:`TargetKey`, e.g. ``"fx-mh1:0"``."""
    return f"{ref['fixtureId']}:{ref['element']}"


def parse_target_key(key: str) -> TargetRef | None:
    """Parse a canonical :data:`TargetKey`; return ``None`` if it is malformed.

    The element must be written canonically (no sign, no leading zeros) so
    that two different keys can never name the same target. The fixture id is
    everything before the *last* colon, so ids may themselves contain colons.
    """
    match = _TARGET_KEY.fullmatch(key)
    if match is None:
        return None
    return TargetRef(fixtureId=FixtureId(match["fixture"]), element=int(match["element"]))
