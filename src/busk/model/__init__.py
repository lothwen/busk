"""Persistent show data model (spec §5.1–§5.17) and its validation.

Every persistent structure is a ``TypedDict``: a show is plain JSON-shaped
data (dicts, lists, tuples, numbers, strings), never a tree of objects. The
module layout follows the spec's sections:

========================  ====================================================
``common``                identifiers, ``EntityBase``, targets, strictness
                          config and constrained number aliases (§5.1, §5.6)
``attributes``            attribute registry and values (§5.3–§5.4)
``profile``               fixture profiles (§5.5)
``fixture``               universes and patched fixtures (§5.6)
``group``                 groups (§5.7)
``preset``                presets / palettes (§5.8)
``entry``                 value entries: targets, value sources, timing (§5.9)
``effect``                effect templates and instances (§5.10)
``cue``                   cue lists and cues (§5.11)
``playback``              playbacks and pages (§5.12)
``master``                masters (§5.13)
``surface``               control surfaces and bindings (§5.15)
``output``                output routes and settings (§5.16)
``show``                  the show root (§5.17)
``validate``              structural + semantic validation
========================  ====================================================

This ``__init__`` deliberately re-exports nothing: ``busk.commands.types``
imports from the model and ``model.surface`` imports the command types, so
eagerly importing every submodule here would create an import cycle.
"""
