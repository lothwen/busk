"""busk without ``mido``: MIDI is the optional extra ``busk[midi]``
(phase-8-plan §5.7, step 4).

Each check runs in a fresh interpreter. :data:`BLOCK` makes ``import mido``
fail there, as on an install without the extra. The console, OSC, the
feedback worker and the surface manager still import and work. A MIDI
surface says once that it needs the extra, and stays closed; its status
says why.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

BLOCK = 'import sys\nsys.modules["mido"] = None  # `import mido` raises ImportError\n'
"""The first lines of every script: no ``mido``."""

SURFACES = """
from types import SimpleNamespace
from busk.io.surfaces import SurfaceManager
from busk.io.feedback import FeedbackWorker
from busk.process.report import say, warn

def show(*surfaces):
    return SimpleNamespace(surfaces=tuple(surfaces), bindings=())

def surface(ident, kind, match):
    return {"id": ident, "name": ident, "kind": kind, "match": match, "faderPickup": "jump"}
"""


def run(*parts: str) -> subprocess.CompletedProcess[str]:
    """Run the script made of ``parts`` (each dedented) in a fresh
    interpreter; fail with its stderr if it fails."""
    script = "".join(textwrap.dedent(part) for part in parts)
    done = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done


def test_the_console_and_the_surfaces_import_without_mido() -> None:
    done = run(
        BLOCK,
        """
        import busk.console.console, busk.io.surfaces, busk.io.feedback, busk.io.osc
        import busk.process.console_host
        print("busk.io.midi" in sys.modules)
        """,
    )
    assert done.stdout == "False\n"


def test_importing_the_console_loads_no_mido() -> None:
    """With ``mido`` installed, it is loaded only when a MIDI port opens."""
    done = run(
        """
        import sys
        import busk.console.console, busk.io.surfaces, busk.io.feedback
        print(sorted(m for m in ("mido", "rtmidi", "busk.io.midi") if m in sys.modules))
        """
    )
    assert done.stdout == "[]\n"


def test_an_osc_surface_opens_without_mido() -> None:
    done = run(
        BLOCK,
        SURFACES,
        """
        manager = SurfaceManager(lambda event: None, say=say, warn=warn)
        manager.reconcile(show(surface("s-touch", "osc", {"port": 0})))
        manager.close()
        """,
    )
    assert done.stdout.startswith("OSC s-touch: listening on udp ")
    assert done.stderr == ""


def test_a_midi_surface_says_once_that_it_needs_the_extra() -> None:
    done = run(
        BLOCK,
        SURFACES,
        """
        manager = SurfaceManager(lambda event: None, say=say, warn=warn)
        nano = surface("s-nano", "midi", {"deviceName": "nanoKONTROL2"})
        manager.reconcile(show(nano))
        for now in (0.0, 5.0, 10.0):  # hot-plug reads: silent
            manager.poll(now)
        manager.close()
        """,
    )
    assert done.stdout == ""
    assert done.stderr == "MIDI s-nano: unavailable: install busk[midi]\n"


def test_a_midi_surface_without_the_extra_has_failed_and_says_why() -> None:
    """Its status (GAP-08) has the reason its line gave."""
    done = run(
        BLOCK,
        SURFACES,
        """
        manager = SurfaceManager(lambda event: None, say=say, warn=lambda text: None)
        manager.reconcile(show(surface("s-nano", "midi", {"deviceName": "nanoKONTROL2"})))
        manager.poll(5.0)
        [status] = manager.status()
        print(status.state, status.detail)
        manager.close()
        """,
    )
    assert done.stdout == "failed unavailable: install busk[midi]\n"


def test_midi_feedback_says_once_that_it_needs_the_extra() -> None:
    done = run(
        BLOCK,
        SURFACES,
        """
        nano = surface("s-nano", "midi", {"deviceName": "nanoKONTROL2"})
        led = {"kind": "midiNote", "channel": 1, "note": 41}
        binding = {"id": "b1", "surfaceId": "s-nano", "input": led,
                   "action": {"type": "blackout"}, "feedback": {"kind": "led", "address": led}}
        compiled = SimpleNamespace(surfaces=(nano,), bindings=(binding,))
        worker = FeedbackWorker(lambda: compiled, lambda: None, {}, say=say, warn=warn)
        worker.open()
        for now in (0.0, 5.0, 10.0):
            worker.service(now)
        worker.close()
        """,
    )
    assert done.stdout == ""
    assert done.stderr == "MIDI s-nano feedback: unavailable: install busk[midi]\n"
