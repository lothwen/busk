"""Packaging (phase-8-plan §5.9, step 11).

* ``busk.__version__`` is the version in ``pyproject.toml``. The version is
  written in those two places, and only this test keeps them together.
* The built wheel's ``METADATA`` says ``License-Expression: MIT`` and names
  the ``LICENSE`` file, which the wheel carries (PEP 639). Its version, its
  ``midi`` extra (decision 5: MIDI only through the extra), its ``busk``
  command and its ``py.typed`` marker are the ones the guide documents.

The wheel is built with ``uv build`` into a temporary directory. uv builds a
``uv_build`` project itself, so that takes well under a second and fetches
nothing. Without ``uv`` on the ``PATH`` the wheel tests are skipped.
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
import zipfile
from collections.abc import Iterator
from email.message import Message
from email.parser import HeaderParser
from pathlib import Path

import pytest

import busk

ROOT = Path(__file__).parent.parent
"""The project directory: ``pyproject.toml`` and ``LICENSE``."""

DIST_INFO = f"busk-{busk.__version__}.dist-info"
"""The wheel's metadata directory."""


def test_the_version_is_the_one_in_pyproject() -> None:
    with (ROOT / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)["project"]
    assert project["version"] == busk.__version__


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Iterator[zipfile.ZipFile]:
    """The wheel ``uv build`` makes from this tree, opened."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not on the PATH")
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(out), str(ROOT)],
        capture_output=True,
        check=True,
        timeout=120,
    )
    (path,) = out.glob("busk-*.whl")
    with zipfile.ZipFile(path) as opened:
        yield opened


def metadata(wheel: zipfile.ZipFile) -> Message:
    """The wheel's ``METADATA`` headers."""
    return HeaderParser().parsestr(wheel.read(f"{DIST_INFO}/METADATA").decode())


def test_the_wheel_metadata_says_mit(wheel: zipfile.ZipFile) -> None:
    fields = metadata(wheel)
    assert fields["Name"] == "busk"
    assert fields["Version"] == busk.__version__
    assert fields["License-Expression"] == "MIT"
    assert fields.get_all("License-File") == ["LICENSE"]


def test_the_wheel_carries_the_license(wheel: zipfile.ZipFile) -> None:
    assert wheel.read(f"{DIST_INFO}/licenses/LICENSE") == (ROOT / "LICENSE").read_bytes()


def test_midi_is_only_an_extra(wheel: zipfile.ZipFile) -> None:
    fields = metadata(wheel)
    assert fields.get_all("Provides-Extra") == ["midi"]
    requires = fields.get_all("Requires-Dist") or []
    midi = [line for line in requires if line.startswith(("mido", "python-rtmidi"))]
    assert len(midi) == 2
    assert all(line.endswith("extra == 'midi'") for line in midi)


def test_the_wheel_has_the_command_and_the_type_marker(wheel: zipfile.ZipFile) -> None:
    entry_points = wheel.read(f"{DIST_INFO}/entry_points.txt").decode()
    assert "busk = busk.cli:main" in entry_points.splitlines()
    assert "busk/py.typed" in wheel.namelist()
