"""The operator console: line commands inside ``busk run`` and script files
(phase-3-plan §3 decision 1, §5.10).

``parser``   :func:`~busk.console.parser.parse`: one line → an action (pure)
``console``  :class:`~busk.console.console.Console`: runs lines and scripts
             against a session, and the interactive loop

The console is a thin client: every change goes through
:meth:`Session.submit <busk.session.session.Session.submit>`, the API the
Phase 6 WebSocket server will expose. It only turns user-facing numbers
("fixture 101", "preset color 2", "cue 10/1") into ids, picks free numbers,
fills in entity defaults and wraps multi-entity operations in a ``BATCH``.
"""
