"""The editing session: the command bus of spec §15 and the single writer of
editing state (phase-3-plan §3 decision 2, §5.4–§5.7).

Editing state is the show store, the programmer and the undo timeline. The
engine never imports this package: the session hands it immutable
:class:`~busk.engine.install.Install` items (a compiled show, a programmer
frame, or both) through the engine's own command queue.

``session``     :class:`~busk.session.session.Session`: routes every command
                by class, applies edits, keeps the store invariant
``timeline``    the one undo/redo timeline for show edits and programmer changes
``state``       :class:`~busk.session.state.ShowState`: a committed show with its
                compiled form and the lookups handlers share
``programmer``  the programmer value object and its command handlers
``status``      the programmer as a display reads it (public: ``ProgrammerStatus``)
``frame``       programmer frames and slot remaps for the engine
``library``     the fixture profile library
``ids``         entity id factories
"""
