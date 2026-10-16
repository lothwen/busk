"""Commands: the only way surfaces and UIs change state (spec §15).

``busk.commands.types``
    The command types (§15.2) and envelopes (§15.1). Bindings embed commands
    in the show file, so these types are part of the show schema.
``busk.commands.classes``
    Every command type's class: performance, programmer, show edit, session.
``busk.commands.bus``
    The engine's queue: performance commands (validated at submit time) and
    the session's live-edit installs, drained every tick.
``busk.commands.patch``
    Copy-on-write JSON patches with inverses: the undo mechanism (§15.4).
``busk.commands.edits``
    Generic edits (``ADD``/``SET``/``DELETE``), patching, page assignment.
``busk.commands.record``
    Recording groups, presets and cues from the programmer (§15.3).
``busk.commands.errors``
    :class:`~busk.commands.errors.CommandError`, raised by every handler.

The session (:mod:`busk.session`) routes commands by class. The event log
(§15.5, Phase 7) records what the engine applied, and why
(:mod:`busk.persistence.eventlog`).
"""
