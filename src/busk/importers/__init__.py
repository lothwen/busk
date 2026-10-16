"""Fixture profile importers (phase-7-plan §5.18–§5.19, decisions 20–21).

Each importer turns a fixture description from another format into a busk
:class:`~busk.model.profile.FixtureProfile` and says, in plain lines, what it
could not carry over or had to guess:

* :mod:`busk.importers.ofl`: the Open Fixture Library's JSON format;
* :mod:`busk.importers.gdtf`: GDTF (DIN SPEC 15800) ``.gdtf`` archives, a
  subset (it shares the OFL import's modelling rules where both apply).

``busk import ofl|gdtf`` writes the profiles as files; a ``--library``
directory imports them on the fly
(:class:`~busk.session.library.ProfileLibrary`).
"""

from __future__ import annotations

from dataclasses import dataclass

from busk.model.profile import FixtureProfile


@dataclass(frozen=True, kw_only=True)
class ImportReport:
    """An imported profile and the import's notes: unmapped channels held at
    a default, estimated values, skipped modes, each naming its channel or
    mode."""

    profile: FixtureProfile
    notes: tuple[str, ...]


class ImportFailed(ValueError):
    """A file that is not a fixture of the format, or that has no mode busk
    can use. The message says why."""
