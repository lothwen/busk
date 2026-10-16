"""busk — a real-time busking lighting console engine.

The architecture is specified in ``docs/busking-console-architecture-python.md``
(referred to throughout the code as "the spec", with section numbers such as
§5.3). This package currently implements **Phase 3** (programmer and
recording) on top of Phase 2 (the busking core), Phase 1.5 (sACN output),
Phase 1 (fixtures) and the Phase 0 walking skeleton:

    console / MIDI → session (programmer, edits, undo) ─┐   performance commands
                         validate → compile → install ───┴→ engine thread (fixed tick)
              → frame handoff → output thread → sACN (E1.31)

The operator builds and changes the show from the console while output keeps
running: every edit is validated and compiled off the engine thread and
swapped in at a tick boundary.

Each tick drains the command queue, advances the playbacks, resolves their
contributions into a logical frame (one float lane per slot of the rig) with
HTP/LTP merging by priority band, applies the grand master and blackout, and
converts the frame into DMX through the fixture profiles. The output thread
sends each universe as sACN, on change and as keep-alive.

Package map (a subset of spec §21):

``busk.model``
    Persistent show schema (§5.1–§5.17) as ``TypedDict``s, the attribute
    registry (§5.3) and validation.
``busk.commands``
    Command types (§15.2), the engine's queue, copy-on-write patches, show
    edits and recording.
``busk.session``
    The session: the single writer of the show, the programmer and the undo
    timeline (§15); the profile library.
``busk.console``
    The operator console: line commands and scripts.
``busk.persistence``
    ``.show`` files, backups, autosave and crash recovery.
``busk.compiler``
    Turns validated show data into flat engine structures: universes, base
    images, the slot table, compiled channels, compiled cues and playbacks
    (§6), and the report of features this build ignores.
``busk.convert``
    Logical → DMX conversion: the conversion plan and the vectorised
    converter (§13).
``busk.engine``
    The fixed-rate engine loop (§11): playback runtimes, presence fades, the
    resolver (§7), masters and blackout (§12), UI snapshots.
``busk.io``
    Input: MIDI ports → input events → bindings → commands (§5.15).
``busk.output``
    The output thread (§14): the sACN driver, and a console debug sink.
``busk.library``
    The built-in fixture profiles.
``busk.cli``
    The ``busk`` command line (``validate``, ``new``, ``run``).
"""

import logging

__version__ = "0.1.0"

# Core modules report through ``busk.*`` loggers (phase-8-plan §5.6); a
# program that configures no logging sees nothing of them.
logging.getLogger(__name__).addHandler(logging.NullHandler())
