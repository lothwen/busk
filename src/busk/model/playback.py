"""Playbacks and playback pages (spec §5.12).

A playback is a *performance handle* around a cue list: how it reacts to its
fader and buttons and how it competes with other sources (priority band,
exclusivity, release time).
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from pydantic import with_config

from busk.model.common import STRICT, CueListId, EntityBase, PlaybackId, Seconds, Unit

type FaderFunction = Literal[
    "master",  # scales intensity; LTP per `ltpFaderMode`
    "crossfade",  # fader position = progress of the next cue transition
    "rate",  # chase / effect speed
    "size",  # effect size
    "temp",  # fader acts as a variable-level flash
    "none",
]

type ButtonFunction = Literal[
    "go",
    "back",
    "goto",
    "flash",  # on while held, released on button-up
    "swop",  # flash + suppress all other intensity
    "toggle",  # on/off
    "release",
    "select",  # select this playback's targets in the programmer
    "none",
]


@with_config(STRICT)
class PlaybackFlash(TypedDict):
    """Behaviour of the playback's flash button."""

    level: Unit  # usually 1.0
    includeLtp: bool  # does a flash also bring LTP values?
    priorityBoost: NotRequired[int]  # optional: flash contributes at a higher band


@with_config(STRICT)
class Playback(EntityBase[PlaybackId]):
    """A fader + buttons running one cue list at a priority band."""

    number: int
    cueListId: CueListId
    priority: int  # band; see §7.2 for recommended values
    fader: FaderFunction
    buttons: list[ButtonFunction]  # physical buttons 1..n under the fader
    ltpFaderMode: Literal[
        "followFader",  # LTP weight = fader level
        "threshold",  # LTP snaps in (with cue timing) when the fader passes `ltpThreshold`
        "ignoreFader",  # LTP fully present while active; fader only scales intensity
    ]
    ltpThreshold: Unit  # default 0.02
    autoStart: bool  # fader leaving 0 triggers the playback
    autoRelease: bool  # fader reaching 0 releases it
    flash: PlaybackFlash
    exclusivity: NotRequired[str]  # playbacks sharing a key release each other
    gotoCue: NotRequired[str]  # Phase 6: the cue number every `goto` button jumps to
    protectFromSwop: bool
    releaseTime: Seconds  # LTP fades back to what's underneath
    uiColor: NotRequired[str]


@with_config(STRICT)
class PlaybackPage(EntityBase[str]):
    """A page of playbacks placed on the physical slots of a surface."""

    number: int
    slots: list[PlaybackId | None]  # index = physical slot on the surface
