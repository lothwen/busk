"""Shared fixtures: Appendix A, the Phase 1 demo show, both converters, and
an sACN and an Art-Net receiver."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray

from artnet_node import ArtNetReceiver
from builders import APPENDIX_A, DEMO, DEMO_VALUES
from busk.compiler.compile import CompiledShow
from busk.convert.converter import Converter
from busk.output import artnet, sacn
from reference_convert import reference_convert
from sacn_receiver import Receiver

type Convert = Callable[[CompiledShow, NDArray[np.float64]], NDArray[np.uint8]]
"""Convert a logical frame into new universe buffers."""


@pytest.fixture(autouse=True)
def state_directory(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Every test gets its own busk state directory (installation CID,
    autosaves), never the user's ``~/.local/state/busk``."""
    root = tmp_path_factory.mktemp("xdg-state")
    monkeypatch.setenv("XDG_STATE_HOME", str(root))
    return root / "busk"


@pytest.fixture
def appendix_a_path() -> Path:
    """Path to a verbatim copy of the spec's Appendix A example show."""
    return APPENDIX_A


@pytest.fixture
def appendix_a_text(appendix_a_path: Path) -> str:
    return appendix_a_path.read_text(encoding="utf-8")


@pytest.fixture
def appendix_a(appendix_a_text: str) -> dict[str, Any]:
    """A fresh, mutable parse of Appendix A for each test."""
    data: dict[str, Any] = json.loads(appendix_a_text)
    return data


@pytest.fixture
def demo_path() -> Path:
    """The Phase 1 demo: three real fixtures (MH-X25, ML-56 RGBW, COLORband PiX)."""
    return DEMO


@pytest.fixture
def values_path() -> Path:
    """The demo's static values file."""
    return DEMO_VALUES


def fast_convert(compiled: CompiledShow, frame: NDArray[np.float64]) -> NDArray[np.uint8]:
    """The production converter, over a copy of the base images (as the engine does)."""
    out = np.array(compiled.baseImages)
    Converter(compiled.plan).convert(frame, out)
    return out


@pytest.fixture(params=["reference", "fast"])
def convert(request: pytest.FixtureRequest) -> Convert:
    """Each golden test runs against both converters."""
    return reference_convert if request.param == "reference" else fast_convert


@pytest.fixture
def receiver(monkeypatch: pytest.MonkeyPatch) -> Iterator[Receiver]:
    """An E1.31 receiver on localhost. ``SACN_PORT`` is patched to its port, so
    every sACN route opened during the test that sends unicast to 127.0.0.1
    lands here."""
    with Receiver.localhost() as receiver:
        monkeypatch.setattr(sacn, "SACN_PORT", receiver.port)
        yield receiver


@pytest.fixture
def artnet_receiver(monkeypatch: pytest.MonkeyPatch) -> Iterator[ArtNetReceiver]:
    """An Art-Net receiver on localhost. ``ARTNET_PORT`` is patched to its
    port, so every Art-Net route opened during the test that sends to
    127.0.0.1 lands here."""
    with ArtNetReceiver.localhost() as receiver:
        monkeypatch.setattr(artnet, "ARTNET_PORT", receiver.port)
        yield receiver
