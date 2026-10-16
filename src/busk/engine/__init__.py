"""The real-time engine: the fixed-rate tick and the busking pipeline (spec §4.2, §7, §11).

``clock``             clocks and fixed-rate scheduling
``curves``            fade curves (§5.9) and fade fractions
``fades``             presence envelopes
``playback_runtime``  playback state machines and their sources
``contributions``     sources (contributions batched per source) and gathering
``resolver``          the HTP/LTP resolver
``masters``           grand master and blackout
``waveforms``         effect waveforms (§10.3)
``effects``           effect clocks, runtimes and banks (§10)
``snapshot``          the UI snapshot
``install``           live edits: installs, programmer frames, the programmer source
``loop``              the tick, stages 1–13

The engine thread is the single owner of runtime state (§16). Other threads
submit commands through its bus and only read the immutable frames and
snapshots it publishes. Live edits arrive the same way: the session queues
immutable :class:`~busk.engine.install.Install` items that the engine applies
at a tick boundary.
"""
