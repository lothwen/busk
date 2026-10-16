"""The library guide, ``docs/library.md`` (phase-8-plan §5.10, step 12).

* Its ``>>>`` examples run, with :func:`doctest.testfile`, on that file
  alone: ``docs/`` also holds the spec and the phase plans, and a
  ``--doctest-glob`` over the folder would turn any ``>>>`` line in a plan
  into a test. They run in a temporary directory that looks like a checkout
  (``examples/`` and ``tests/fixtures/`` link to the real ones), so the
  ``club.show`` they write stays out of the project.
* Its reference table has one row for each name of ``busk.__all__``.
"""

from __future__ import annotations

import doctest
import re
from pathlib import Path

import pytest

import busk

ROOT = Path(__file__).parent.parent
GUIDE = ROOT / "docs" / "library.md"


def test_the_guide_examples_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "examples").symlink_to(ROOT / "examples")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "fixtures").symlink_to(ROOT / "tests" / "fixtures")
    monkeypatch.chdir(tmp_path)
    results = doctest.testfile(
        str(GUIDE),
        module_relative=False,
        optionflags=doctest.ELLIPSIS,
        encoding="utf-8",
    )
    assert results.attempted > 0
    assert results.failed == 0, "a guide example failed: see the captured stdout"


def reference_names() -> list[str]:
    """The first column of the guide's reference table."""
    section = GUIDE.read_text(encoding="utf-8").split("\n## Reference\n", 1)[1]
    section = section.split("\n## ", 1)[0]
    return re.findall(r"^\| `(\w+)` \|", section, flags=re.MULTILINE)


def test_the_reference_has_every_public_name_once() -> None:
    names = reference_names()
    assert sorted(names) == sorted(busk.__all__)
