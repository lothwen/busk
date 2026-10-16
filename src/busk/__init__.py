"""busk — a real-time busking lighting console.

busk drives DMX fixtures over sACN, Art-Net and USB widgets from a show file:
fixtures, groups, presets, cues, effects, playbacks on pages, masters and
control surfaces. It runs as the ``busk`` command line, and as this library.

The public API
==============

Every public name is importable from ``busk`` itself; ``__all__`` lists the
28 of them. The library guide, ``docs/library.md``, has the examples and the
reference.

Show documents
    :func:`load_show`, :func:`save_show`, :func:`new_show` and
    :func:`validate_show`: what ``busk validate`` and ``busk new`` do.
Fixture profiles
    :func:`read_ofl` and :func:`read_gdtf` (what ``busk import`` does), and
    :class:`ProfileLibrary` for ``fixture add`` with your own profiles.
Running a show
    :class:`OfflineShow` renders frames on a clock the caller drives: no
    threads, no sockets. :class:`LiveShow` runs the engine and the DMX output
    as threads in the caller's process, optionally with the show's surfaces.
    Both take commands (:meth:`~OfflineShow.submit`), console lines
    (:meth:`~OfflineShow.execute`) and scripts.
Data types
    :class:`Show`, :class:`FixtureProfile` and :data:`Command`, the
    ``TypedDict``\\ s of the file and command formats; :class:`Issue`,
    :class:`CommandResult`, :class:`Reply`, :class:`ImportReport`;
    :class:`EngineSnapshot` with :class:`PlaybackStatus`,
    :class:`SpeedStatus` and :class:`PageStatus`; :class:`DmxFrame`;
    :class:`IdFactory` and :class:`CounterIds`.
Errors
    :class:`BuskError` is the base of every error the API raises on purpose:
    :class:`ShowLoadError`, :class:`UnsupportedFeature`, :class:`ImportFailed`
    and :class:`ScriptError`. A refused command is not an error but a value
    (``CommandResult.ok``, ``Reply.ok``).

What is public
==============

Public means the names in ``__all__``, with their documented attributes and
methods, and the ``TypedDict``\\ s and type aliases of ``busk.model.*`` and
``busk.commands.types``, which describe the show file and the commands.
Everything else is internal, whether or not its name starts with an
underscore: the modules stay where they are, and the ``busk`` command line
uses them, but they may change in any release.

Stability
=========

busk follows 0.x semver: a patch release (0.1.1) only fixes; a minor release
(0.2.0) may break the public API, after a deprecation wherever possible. No
message text is part of the API: CLI output, :attr:`Issue.message`,
:attr:`Reply.text` and log records may change in any release.

Logging
=======

The library prints nothing. It reports through the loggers under ``busk``
(``busk.session``, ``busk.surfaces``, ``busk.output``, ``busk.eventlog``), and
``busk`` has a :class:`logging.NullHandler`, so a program that configures no
logging sees none of it.

Laziness
========

``import busk`` loads no busk module: each public name is imported from its
module the first time it is used (PEP 562). So the command line and the
engine process load only what they run, and the model ↔ commands import
cycle (see :mod:`busk.model`) is never touched.
"""

import logging

TYPE_CHECKING = False  # as ``typing.TYPE_CHECKING``, without importing typing

__version__ = "0.1.0"

__all__ = [
    "BuskError",
    "Command",
    "CommandResult",
    "CounterIds",
    "DmxFrame",
    "EngineSnapshot",
    "FixtureProfile",
    "IdFactory",
    "ImportFailed",
    "ImportReport",
    "Issue",
    "LiveShow",
    "OfflineShow",
    "PageStatus",
    "PlaybackStatus",
    "ProfileLibrary",
    "Reply",
    "ScriptError",
    "Show",
    "ShowLoadError",
    "SpeedStatus",
    "UnsupportedFeature",
    "load_show",
    "new_show",
    "read_gdtf",
    "read_ofl",
    "save_show",
    "validate_show",
]

_EXPORTS: dict[str, str] = {
    "load_show": "busk.persistence.show_file",
    "save_show": "busk.persistence.show_file",
    "new_show": "busk.persistence.show_file",
    "ShowLoadError": "busk.persistence.show_file",
    "validate_show": "busk.model.validate",
    "Issue": "busk.model.validate",
    "Show": "busk.model.show",
    "FixtureProfile": "busk.model.profile",
    "Command": "busk.commands.types",
    "read_ofl": "busk.importers.ofl",
    "read_gdtf": "busk.importers.gdtf",
    "ImportReport": "busk.importers",
    "ImportFailed": "busk.importers",
    "ProfileLibrary": "busk.session.library",
    "IdFactory": "busk.session.ids",
    "CounterIds": "busk.session.ids",
    "CommandResult": "busk.session.session",
    "Reply": "busk.console.console",
    "EngineSnapshot": "busk.engine.snapshot",
    "PlaybackStatus": "busk.engine.snapshot",
    "SpeedStatus": "busk.engine.snapshot",
    "PageStatus": "busk.engine.snapshot",
    "UnsupportedFeature": "busk.compiler.compile",
    "OfflineShow": "busk.runner",
    "LiveShow": "busk.runner",
    "DmxFrame": "busk.runner",
    "BuskError": "busk.errors",
    "ScriptError": "busk.errors",
}
"""Each public name → the module that defines it (phase-8-plan §5.1)."""

if TYPE_CHECKING:  # what type checkers see: the same table, as explicit re-exports
    from busk.commands.types import Command as Command
    from busk.compiler.compile import UnsupportedFeature as UnsupportedFeature
    from busk.console.console import Reply as Reply
    from busk.engine.snapshot import EngineSnapshot as EngineSnapshot
    from busk.engine.snapshot import PageStatus as PageStatus
    from busk.engine.snapshot import PlaybackStatus as PlaybackStatus
    from busk.engine.snapshot import SpeedStatus as SpeedStatus
    from busk.errors import BuskError as BuskError
    from busk.errors import ScriptError as ScriptError
    from busk.importers import ImportFailed as ImportFailed
    from busk.importers import ImportReport as ImportReport
    from busk.importers.gdtf import read_gdtf as read_gdtf
    from busk.importers.ofl import read_ofl as read_ofl
    from busk.model.profile import FixtureProfile as FixtureProfile
    from busk.model.show import Show as Show
    from busk.model.validate import Issue as Issue
    from busk.model.validate import validate_show as validate_show
    from busk.persistence.show_file import ShowLoadError as ShowLoadError
    from busk.persistence.show_file import load_show as load_show
    from busk.persistence.show_file import new_show as new_show
    from busk.persistence.show_file import save_show as save_show
    from busk.runner import DmxFrame as DmxFrame
    from busk.runner import LiveShow as LiveShow
    from busk.runner import OfflineShow as OfflineShow
    from busk.session.ids import CounterIds as CounterIds
    from busk.session.ids import IdFactory as IdFactory
    from busk.session.library import ProfileLibrary as ProfileLibrary
    from busk.session.session import CommandResult as CommandResult


def _lazy(name: str) -> object:
    """Import the public ``name`` from its module, and keep it here, so the
    next lookup is a plain attribute. Raises :class:`AttributeError` for any
    name that is not public."""
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'busk' has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value


if not TYPE_CHECKING:
    # Hidden from type checkers: for them, a module ``__getattr__`` would make
    # every unknown ``busk.name`` valid, typed by its return type.
    __getattr__ = _lazy


def __dir__() -> list[str]:
    """The module's globals and every public name, imported or not."""
    return sorted({*globals(), *__all__})


# Core modules report through ``busk.*`` loggers (phase-8-plan §5.6); a
# program that configures no logging sees nothing of them.
logging.getLogger(__name__).addHandler(logging.NullHandler())
