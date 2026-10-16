"""The public exception hierarchy (phase-8-plan §5.8, step 2).

Every error the public API raises on purpose is a :class:`BuskError`. The
existing classes keep their names, modules and attributes; only their base
changes, and :class:`ImportFailed` stays a :class:`ValueError`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from busk.compiler.compile import UnsupportedFeature
from busk.errors import BuskError, ScriptError
from busk.importers import ImportFailed
from busk.model.validate import Issue
from busk.persistence.show_file import ShowLoadError


@pytest.mark.parametrize("error", [ShowLoadError, UnsupportedFeature, ImportFailed, ScriptError])
def test_every_public_error_is_a_busk_error(error: type[Exception]) -> None:
    assert issubclass(error, BuskError)
    assert issubclass(BuskError, Exception)


def test_import_failed_is_still_a_value_error() -> None:
    assert issubclass(ImportFailed, ValueError)
    with pytest.raises(ValueError, match="no mode"):
        raise ImportFailed("no mode busk can use")


def test_the_existing_classes_keep_their_modules_and_attributes() -> None:
    assert ShowLoadError.__module__ == "busk.persistence.show_file"
    assert UnsupportedFeature.__module__ == "busk.compiler.compile"
    assert ImportFailed.__module__ == "busk.importers"
    issue = Issue("error", "fixtures[0]", "bad")
    error = ShowLoadError([issue])
    assert error.issues == [issue]
    assert str(error) == "show failed validation with 1 issue(s)"
    assert str(UnsupportedFeature("elementPatch")) == "elementPatch"


def test_a_script_error_names_its_line() -> None:
    error = ScriptError(Path("build.busk"), 2, "sel group 7", ["2 targets selected", "error: x"])
    assert (error.path, error.line, error.text) == (Path("build.busk"), 2, "sel group 7")
    assert error.output == ["2 targets selected", "error: x"]
    assert str(error) == "build.busk:2: sel group 7"
    assert ScriptError.__module__ == "busk.errors"
