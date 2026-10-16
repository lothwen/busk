"""Loaded at start-up by every Python process the process tests start
(:mod:`process_harness` puts this directory first on ``PYTHONPATH``).

It does for a process tree what the in-process ``receiver`` fixture does
with ``monkeypatch``: ``BUSK_TEST_SACN_PORT`` points every sACN route at
the test's receiver. Without the variable it does nothing.
"""

from __future__ import annotations

import os

if port := os.environ.get("BUSK_TEST_SACN_PORT"):
    from busk.output import sacn

    sacn.SACN_PORT = int(port)  # type: ignore[misc]  # a test's receiver, as the fixture does
