"""Loaded at start-up by every Python process the process tests start
(:mod:`process_harness` puts this directory first on ``PYTHONPATH``).

It does for a process tree what the in-process fixtures do with
``monkeypatch``: ``BUSK_TEST_SACN_PORT`` points every sACN route at the
test's receiver, and ``BUSK_TEST_MIDI_PORTS`` (a JSON list) is the MIDI
input port list every process sees, as test_cli's ``no_midi_devices``
arranges. Without the variables it does nothing.
"""

from __future__ import annotations

import json
import os

if port := os.environ.get("BUSK_TEST_SACN_PORT"):
    from busk.output import sacn

    sacn.SACN_PORT = int(port)  # type: ignore[misc]  # a test's receiver, as the fixture does

if (ports := os.environ.get("BUSK_TEST_MIDI_PORTS")) is not None:
    from busk.io import midi

    names: list[str] = json.loads(ports)
    midi.input_names = lambda: list(names)
