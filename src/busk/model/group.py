"""Groups: ordered references to targets (spec §5.7).

Groups *reference* targets and never copy fixture data. Member order matters:
it drives fans and effect phase ("left to right" vs "outside in").
"""

from __future__ import annotations

from typing import NotRequired, TypedDict

from pydantic import with_config

from busk.model.common import STRICT, EntityBase, GroupId, NonNegativeInt, PositiveInt, TargetRef


@with_config(STRICT)
class GroupLayout(TypedDict):
    """Optional 2D layout for matrix effects.

    ``cells`` is row-major with ``width × height`` entries; each entry is an
    index into the group's ``members`` or ``None`` for an empty cell.
    """

    width: PositiveInt
    height: PositiveInt
    cells: list[NonNegativeInt | None]


@with_config(STRICT)
class Group(EntityBase[GroupId]):
    """A named, ordered set of targets."""

    number: int
    members: list[TargetRef]  # ORDERED — order drives fans and effect phase
    layout: NotRequired[GroupLayout]
    uiColor: NotRequired[str]
