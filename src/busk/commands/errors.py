"""The error every programmer and show-edit handler raises (phase-3-plan §5.6).

A handler that cannot do what a command asks raises :class:`CommandError`
with a message written for the operator (``no group 7``, ``preset color 1
exists: add merge or replace``) and, when validation found them, the issues
with their paths. The session turns it into a failed
:class:`~busk.session.session.CommandResult`; nothing changes anywhere.
"""

from __future__ import annotations

from collections.abc import Sequence

from busk.model.validate import Issue


class CommandError(Exception):
    """A command was refused; :attr:`message` says why, :attr:`issues` where."""

    def __init__(self, message: str, issues: Sequence[Issue] = ()) -> None:
        super().__init__(message)
        self.message = message
        self.issues = tuple(issues)
