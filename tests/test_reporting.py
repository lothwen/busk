"""Core modules report through callbacks that default to logging
(phase-8-plan §5.6, step 3).

Built with their defaults, the session, the surfaces, the feedback worker
and the event log print nothing: each message goes, as the same text, to a
``busk.*`` logger (warnings at WARNING, start-up lines at INFO). The ``busk``
logger has a :class:`logging.NullHandler`, so a program that configures no
logging sees nothing. The CLI passes printers instead, so its output is
unchanged (test_cli, test_hotplug and the transcripts check that).
"""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import cast

import pytest

from builders import APPENDIX_A, load_doc
from busk.commands.types import Command
from busk.io import midi
from busk.io.bindings import BindingResolver
from busk.io.events import InputEvent
from busk.io.feedback import FeedbackWorker
from busk.io.osc import OscSurface, encode
from busk.io.surfaces import SurfaceManager
from busk.persistence.eventlog import START_PREFIX, EventLog
from session_harness import Live, put
from test_hotplug import THROUGH, midi_surface, show
from test_rate_limits import Clock, osc_surface


def records(caplog: pytest.LogCaptureFixture, logger: str) -> list[tuple[int, str]]:
    """The (level, message) of each record ``logger`` got."""
    return [(r.levelno, r.getMessage()) for r in caplog.records if r.name == logger]


def test_the_busk_logger_has_a_null_handler() -> None:
    import busk

    handlers = logging.getLogger(busk.__name__).handlers
    assert any(isinstance(h, logging.NullHandler) for h in handlers)


def test_a_posted_command_that_fails_is_logged(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    live = Live(load_doc(APPENDIX_A))
    live.session.post(cast(Command, put("pan", 1)))  # nothing is selected
    live.session.stop()
    assert records(caplog, "busk.session") == [(logging.WARNING, "SET_ATTRIBUTE: nothing selected")]
    assert capsys.readouterr() == ("", "")


def test_a_missing_midi_device_is_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(midi, "input_names", lambda: [THROUGH])
    events: list[InputEvent] = []
    manager = SurfaceManager(events.append)
    manager.reconcile(show(midi_surface("s-nano", "nanoKONTROL2")))
    manager.close()
    assert records(caplog, "busk.surfaces") == [
        (logging.WARNING, f"MIDI s-nano: 'nanoKONTROL2' not found; available: {THROUGH}")
    ]
    assert capsys.readouterr() == ("", "")


def test_an_open_osc_surface_is_logged_at_info(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.INFO, logger="busk")
    manager = SurfaceManager(lambda event: None)
    manager.reconcile(show(osc_surface()))
    manager.close()
    [(level, message)] = records(caplog, "busk.surfaces")
    assert level == logging.INFO
    assert message.startswith("OSC s-touch: ")
    assert capsys.readouterr() == ("", "")


def test_an_osc_flood_is_logged(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = Clock()
    surface = OscSurface(osc_surface(), lambda event: None, clock=clock)
    for k in range(1000):  # 1 s at 1000 messages a second
        clock.now = k / 1000
        surface.datagram(encode("/fader", 0.5), ("10.0.0.7", 9000))
    assert records(caplog, "busk.surfaces")[0] == (
        logging.WARNING,
        "OSC s-touch: rate limit: 1 message dropped",
    )
    assert capsys.readouterr() == ("", "")


def test_an_unwritable_event_log_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("")  # a file where the log directory should be
    log = EventLog(blocker / "logs")
    log.add(0.0, START_PREFIX + b'"show-1"}')
    log.add(0.1, START_PREFIX + b'"show-1"}')
    [(level, message)] = records(caplog, "busk.eventlog")
    assert level == logging.WARNING
    assert message.startswith("event log: cannot write: ")
    assert log.lost == 2
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    ("owner", "parameter", "logger", "level"),
    [
        (BindingResolver, "report", "busk.surfaces", "warning"),
        (FeedbackWorker, "report", "busk.surfaces", "warning"),
        (FeedbackWorker, "say", "busk.surfaces", "info"),
        (FeedbackWorker, "warn", "busk.surfaces", "warning"),
        (SurfaceManager, "say", "busk.surfaces", "info"),
        (SurfaceManager, "warn", "busk.surfaces", "warning"),
        (OscSurface, "report", "busk.surfaces", "warning"),
        (EventLog, "report", "busk.eventlog", "warning"),
    ],
)
def test_every_reporter_defaults_to_its_logger(
    owner: type, parameter: str, logger: str, level: str
) -> None:
    default = inspect.signature(owner).parameters[parameter].default
    assert default == getattr(logging.getLogger(logger), level)
