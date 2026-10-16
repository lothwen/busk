"""Load a values file (``busk run --values``).

A values file is a JSON list of :class:`~busk.model.show.ParkEntry`-shaped
entries: logical values for slots that no playback controls (the resolver's
starting frame, instead of the registry defaults)::

    [ { "slot": { "target": { "fixtureId": "fx-mh1", "element": 0 },
                  "attribute": "pan" },
        "value": 90 },
      { "slot": { "target": { "fixtureId": "fx-mh1", "element": 0 },
                  "attribute": "colorWheel" },
        "value": { "slot": "red" } } ]

It reuses the show schema and the park checks; see
:func:`busk.model.validate.validate_values` and
:func:`busk.compiler.values.compile_values`.
"""

from __future__ import annotations

from pathlib import Path

from busk.model.show import ParkEntry, Show
from busk.model.validate import Issue, validate_values


def load_values(path: str | Path, show: Show) -> tuple[list[ParkEntry] | None, list[Issue]]:
    """Read the values file at ``path`` and check it against ``show``.

    Returns the entries and every issue found. The entries are ``None`` when
    the file is not structurally valid; callers must also refuse entries
    that come with errors (see :func:`~busk.model.validate.has_errors`).
    Raises :class:`OSError` (for example :class:`FileNotFoundError`) if the
    file cannot be read.
    """
    return validate_values(Path(path).read_bytes(), show)
