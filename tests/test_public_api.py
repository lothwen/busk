"""The public namespace and its boundary (phase-8-plan §5.3, step 8).

* ``busk.__all__`` is the 28 names of §5.1, the two of GAP-01
  (``OutputSnapshot``, ``FixtureOutput``), the two of GAP-02
  (``ProgrammerStatus``, ``ProgrammerValue``), the one of GAP-07
  (``RouteStatus``), the one of GAP-08 (``SurfaceStatus``) and the two of
  GAP-09 (``EffectSnapshot``, ``EffectStatus``; ``docs/dev/tui/engine-gaps.md``).
  Each resolves lazily from the module of the §5.1 table, and the type
  checkers' re-exports in ``busk/__init__.py`` are the same table.
* Nothing else is an attribute of ``busk``.
* ``tests/golden/public_api.json`` pins the API: the signature of every
  public function and method, the fields of every public dataclass, the keys
  of the two public ``TypedDict``\\ s, the members of ``Command`` and the
  bases of the errors. Any change to it is a reviewed diff: regenerate it
  with ``BUSK_REGOLDEN=1`` only after a deliberate change (§5.11).
* The boundary: what the public names, ``import busk`` and the engine
  process each load, checked in fresh interpreters.

``tests/api_consumer.py`` checks the other side, the types a consumer sees,
under ``uv run mypy --strict tests/api_consumer.py``.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import os
import subprocess
import sys
import textwrap
import typing
from pathlib import Path
from typing import Any

import pytest

import busk

GOLDEN = Path(__file__).parent / "golden" / "public_api.json"
REGOLDEN = os.environ.get("BUSK_REGOLDEN") == "1"

PUBLIC = [
    # Show documents
    "load_show",
    "save_show",
    "new_show",
    "validate_show",
    # Fixture profiles
    "read_ofl",
    "read_gdtf",
    "ProfileLibrary",
    # Running a show
    "OfflineShow",
    "LiveShow",
    # Data types
    "Show",
    "FixtureProfile",
    "Command",
    "Issue",
    "CommandResult",
    "Reply",
    "ImportReport",
    "EngineSnapshot",
    "PlaybackStatus",
    "SpeedStatus",
    "PageStatus",
    "DmxFrame",
    "OutputSnapshot",
    "FixtureOutput",
    "ProgrammerStatus",
    "ProgrammerValue",
    "RouteStatus",
    "SurfaceStatus",
    "EffectSnapshot",
    "EffectStatus",
    "IdFactory",
    "CounterIds",
    # Errors
    "BuskError",
    "ShowLoadError",
    "UnsupportedFeature",
    "ImportFailed",
    "ScriptError",
]
"""The §5.1 list, in its order, with GAP-01's two after ``DmxFrame``,
GAP-02's two after them, GAP-07's one after those, GAP-08's one
after it and GAP-09's two after that."""

DUNDERS = {"__init__", "__enter__", "__exit__", "__iter__", "__len__", "__str__"}
"""The special methods a public class documents; the rest come from Python."""


def run(script: str) -> str:
    """Run ``script`` (dedented) in a fresh interpreter and return its stdout;
    fail with its stderr if it fails."""
    done = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


# ----------------------------------------------------------------- the names


def test_all_is_the_planned_list_sorted() -> None:
    assert len(PUBLIC) == 36
    assert busk.__all__ == sorted(PUBLIC)


def test_every_public_name_comes_from_the_module_of_the_table() -> None:
    assert busk._EXPORTS.keys() == set(PUBLIC)
    for name, module in busk._EXPORTS.items():
        value = getattr(busk, name)
        assert value is getattr(sys.modules[module], name)
        assert value.__module__ == module, name


def test_the_type_checkers_see_the_same_table() -> None:
    """The ``if TYPE_CHECKING:`` block re-exports exactly ``_EXPORTS``, each
    as ``from module import name as name`` (an explicit re-export)."""
    source = Path(busk.__file__).read_text(encoding="utf-8")
    seen: dict[str, str] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.If) and ast.unparse(node.test) == "TYPE_CHECKING":
            for statement in node.body:
                assert isinstance(statement, ast.ImportFrom)
                for alias in statement.names:
                    assert alias.asname == alias.name
                    assert statement.module is not None
                    seen[alias.name] = statement.module
    assert seen == busk._EXPORTS


def test_star_import_gives_the_public_names() -> None:
    namespace: dict[str, Any] = {}
    exec("from busk import *", namespace)
    namespace.pop("__builtins__")
    assert sorted(namespace) == busk.__all__


def test_dir_lists_every_public_name_imported_or_not() -> None:
    names = dir(busk)
    assert names == sorted(names)
    assert {*busk.__all__, "__version__"} <= set(names)


@pytest.mark.parametrize("name", ["Session", "Console", "compile_show", "RunOptions", "midi"])
def test_any_other_name_is_an_attribute_error(name: str) -> None:
    with pytest.raises(AttributeError, match=f"module 'busk' has no attribute '{name}'"):
        getattr(busk, name)
    assert not hasattr(busk, name)


def test_from_import_of_an_internal_name_fails() -> None:
    with pytest.raises(ImportError):
        exec("from busk import Session", {})


def test_a_name_is_imported_on_first_use_and_kept() -> None:
    out = run(
        """
        import sys
        import busk
        print("load_show" in vars(busk), "busk.persistence.show_file" in sys.modules)
        load = busk.load_show
        print(vars(busk)["load_show"] is load, "busk.persistence.show_file" in sys.modules)
        print("busk.runner" in sys.modules)
        """
    )
    assert out == "False False\nTrue True\nFalse\n"


# ------------------------------------------------------------- the boundary


def test_the_public_names_load_no_cli() -> None:
    out = run(
        """
        import sys
        import busk
        for name in busk.__all__:
            getattr(busk, name)
        print(sorted(
            module for module in sys.modules
            if module == "argparse" or module.startswith(("busk.cli", "busk.process"))
        ))
        """
    )
    assert out == "[]\n"


def test_the_engine_process_loads_no_session_console_web_or_midi() -> None:
    out = run(
        """
        import sys
        import busk.process.engine_host
        print(sorted(
            module for module in sys.modules
            if module.split(".")[:2] in (["busk", "console"], ["busk", "session"], ["busk", "web"])
            or module.split(".")[0] in ("mido", "rtmidi")
        ))
        """
    )
    assert out == "[]\n"


def test_import_busk_loads_nothing_but_logging() -> None:
    out = run(
        """
        import logging
        import sys
        before = set(sys.modules)
        import busk
        print(sorted(set(sys.modules) - before))
        """
    )
    assert out == "['busk']\n"


# ----------------------------------------------------------- the API golden


class _Text:
    """An annotation as written, which :mod:`inspect` prints unquoted."""

    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:
        return self.text


def _annotation(value: object) -> str:
    if isinstance(value, typing.ForwardRef):  # a TypedDict's keys before Python 3.14
        return value.__forward_arg__
    return value if isinstance(value, str) else inspect.formatannotation(value)


def _signature(function: Any) -> str:
    """``inspect.signature`` of ``function``, with its annotations as written
    in the source (they are strings: every module has postponed
    annotations)."""
    signature = inspect.signature(function)
    empty = inspect.Parameter.empty
    parameters = [
        p.replace(annotation=_Text(_annotation(p.annotation))) if p.annotation is not empty else p
        for p in signature.parameters.values()
    ]
    returns = signature.return_annotation
    return str(
        signature.replace(
            parameters=parameters,
            return_annotation=returns if returns is empty else _Text(_annotation(returns)),
        )
    )


def _members(cls: type) -> dict[str, str]:
    """The public methods, properties and annotated attributes of ``cls`` and
    of its busk bases (so a private base's methods count as the class's)."""
    members: dict[str, str] = {}
    fields = {f.name for f in dataclasses.fields(cls)} if dataclasses.is_dataclass(cls) else set()
    for klass in reversed(cls.__mro__):
        if not klass.__module__.startswith("busk"):
            continue
        for name, annotation in inspect.get_annotations(klass).items():
            if not name.startswith("_") and name not in fields:
                members[name] = f"attribute: {_annotation(annotation)}"
        for name, value in vars(klass).items():
            if name.startswith("_") and name not in DUNDERS:
                continue
            if isinstance(value, property):
                returns = inspect.signature(value.fget).return_annotation
                members[name] = f"property: {_annotation(returns)}"
            elif isinstance(value, staticmethod | classmethod):
                members[name] = f"{type(value).__name__}{_signature(value.__func__)}"
            elif inspect.isfunction(value) and value.__module__.startswith("busk"):
                # (not the placeholder ``__init__`` that ``typing.Protocol`` adds)
                members[name] = _signature(value)
    return members


def _describe(name: str, value: Any) -> dict[str, Any]:
    """What the golden pins of one public name."""
    entry: dict[str, Any] = {"module": value.__module__}
    if isinstance(value, typing.TypeAliasType):
        union = value.__value__
        if typing.get_origin(union) is typing.Annotated:  # Command: a discriminated union
            union = typing.get_args(union)[0]
        members = typing.get_args(union)
        entry["kind"] = "type alias"
        entry["members"] = sorted(member.__name__ for member in members)
    elif inspect.isfunction(value):
        entry["kind"] = "function"
        entry["signature"] = _signature(value)
    elif typing.is_typeddict(value):
        entry["kind"] = "TypedDict"
        keys = inspect.get_annotations(value)
        entry["keys"] = {key: _annotation(annotation) for key, annotation in keys.items()}
    elif dataclasses.is_dataclass(value):
        frozen = value.__dataclass_params__.frozen
        entry["kind"] = "frozen dataclass" if frozen else "dataclass"
        entry["fields"] = [f"{f.name}: {_annotation(f.type)}" for f in dataclasses.fields(value)]
        entry["members"] = _members(value)
    elif issubclass(value, BaseException):
        entry["kind"] = "exception"
        entry["bases"] = [base.__name__ for base in value.__bases__]
        entry["members"] = _members(value)
    else:
        entry["kind"] = "protocol" if getattr(value, "_is_protocol", False) else "class"
        entry["members"] = _members(value)
    return entry


def api() -> dict[str, Any]:
    """The whole public API, as the golden stores it."""
    return {name: _describe(name, getattr(busk, name)) for name in busk.__all__}


def test_the_public_api_matches_its_golden() -> None:
    text = json.dumps(api(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if REGOLDEN:
        GOLDEN.write_text(text, encoding="utf-8")
    assert text == GOLDEN.read_text(encoding="utf-8")
