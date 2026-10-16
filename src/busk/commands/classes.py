"""Command classes: who handles each command type (spec §15.2, phase-3-plan §5.1).

Every member of the :data:`~busk.commands.types.Command` union belongs to
exactly one class, and the session (:mod:`busk.session.session`) routes a
command by its class:

==============  ===============================================  ==================
Class           Handled by                                       Undo
==============  ===============================================  ==================
performance     the engine, through its command queue; never     no
                waits for the session lock
programmer      the session: a new programmer, then a            yes (one timeline)
                programmer frame installed in the engine
show            the session: copy-on-write patches, validated    yes (one timeline)
                and compiled, then installed in the engine
session         the session: the undo timeline itself            —
==============  ===============================================  ==================
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Literal

type CommandClass = Literal["performance", "programmer", "show", "session"]

COMMAND_CLASSES: Final[Mapping[str, CommandClass]] = MappingProxyType(
    {
        # performance (§15.2, plus Phase 2's TOGGLE_PLAYBACK)
        "TRIGGER_PLAYBACK": "performance",
        "RELEASE_PLAYBACK": "performance",
        "TOGGLE_PLAYBACK": "performance",
        "FLASH": "performance",
        "GO": "performance",
        "BACK": "performance",
        "GOTO": "performance",
        "SET_FADER": "performance",
        "SET_MASTER": "performance",
        "TAP": "performance",
        "SET_BPM": "performance",  # Phase 4
        "BLACKOUT": "performance",
        "PAGE": "performance",  # Phase 6
        "PLAYBACK_BUTTON": "performance",  # Phase 6
        "RELEASE_ALL": "performance",  # Phase 7
        "OUTPUT": "performance",  # Phase 7
        # programmer
        "SELECT": "programmer",
        "SELECT_PLAYBACK": "programmer",
        "SET_ATTRIBUTE": "programmer",
        "APPLY_PRESET": "programmer",
        "CLEAR_PROGRAMMER": "programmer",
        "BLIND": "programmer",
        "PROGRAMMER_FADE": "programmer",  # Phase 4
        "ADD_EFFECT": "programmer",  # Phase 5
        "REMOVE_EFFECT": "programmer",  # Phase 5
        "HIGHLIGHT": "programmer",  # Phase 7
        # show edit
        "RECORD_CUE": "show",
        "RECORD_PRESET": "show",
        "RECORD_GROUP": "show",
        "PATCH_FIXTURE": "show",
        "ASSIGN_PLAYBACK": "show",
        "ADD": "show",
        "SET": "show",
        "DELETE": "show",
        "BATCH": "show",
        # session
        "UNDO": "session",
        "REDO": "session",
    }
)
"""The class of every command type."""


def command_class(command: Mapping[str, object]) -> CommandClass | None:
    """The class of ``command``, or ``None`` if its ``type`` is unknown."""
    kind = command.get("type")
    return COMMAND_CLASSES.get(kind) if isinstance(kind, str) else None
