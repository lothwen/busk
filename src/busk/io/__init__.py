"""Control surfaces: input → commands, and feedback back out (spec §4.1
"bindings → Commands", §5.15).

``busk.io.events``
    :class:`~busk.io.events.InputEvent`: one control moved, as a value in
    ``0..1``. The boundary between input backends and bindings.
``busk.io.bindings``
    :class:`~busk.io.bindings.BindingResolver`: the show's bindings turn
    events into commands on the bus.
``busk.io.midi``
    :class:`~busk.io.midi.MidiInput`: MIDI ports (``mido`` + ``python-rtmidi``)
    → input events, MIDI clock as beats; :class:`~busk.io.midi.MidiOutput`:
    feedback to a device. The only module that imports ``mido``.
``busk.io.feedback``
    :class:`~busk.io.feedback.FeedbackWorker`: LEDs, motor faders and labels
    from engine snapshots, at 30 Hz.
``busk.io.osc``
    OSC 1.0 over UDP: the codec and :class:`~busk.io.osc.OscSurface`.
``busk.io.surfaces``
    :class:`~busk.io.surfaces.SurfaceManager`: opens and closes the show's
    MIDI, OSC and web surfaces as live edits change them.

Pages, soft takeover and held buttons are the engine's (Phase 6). The web
remote is :mod:`busk.web`.
"""
