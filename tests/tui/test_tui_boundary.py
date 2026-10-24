"""The TUI's boundary (plan §1.2, §4.6): only ``bridge.py`` imports busk, and
only names of ``busk.__all__``; the plain modules import no Textual; and
``app.py`` imports Textual only inside functions, after ``--colors`` has set
``TEXTUAL_COLOR_SYSTEM``."""

from __future__ import annotations

import ast
from pathlib import Path

import busk

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "busk_tui"

PLAIN = ("model", "commands", "hints", "colors", "config", "nav")
"""Modules with neither busk nor Textual."""


def imports(path: Path, *, top_only: bool = False) -> list[tuple[str, tuple[str, ...]]]:
    """``(module, names)`` of every import in ``path`` (``names`` empty for a
    plain ``import``); with ``top_only``, only the module's own statements."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = tree.body if top_only else list(ast.walk(tree))
    found: list[tuple[str, tuple[str, ...]]] = []
    for node in nodes:
        if isinstance(node, ast.Import):
            found += [(alias.name, ()) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.append((node.module, tuple(alias.name for alias in node.names)))
    return found


def root(module: str) -> str:
    return module.split(".")[0]


def modules() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def test_the_package_is_where_the_test_looks() -> None:
    names = {path.stem for path in modules()}
    assert {"bridge", "app", "shell", *PLAIN} <= names


def test_only_the_bridge_imports_busk() -> None:
    importers = sorted(
        str(path.relative_to(PACKAGE))
        for path in modules()
        if any(root(module) == "busk" for module, _ in imports(path))
    )
    assert importers == ["bridge.py"]


def test_the_bridge_imports_only_public_names() -> None:
    for module, names in imports(PACKAGE / "bridge.py"):
        if root(module) != "busk":
            continue
        assert module == "busk", f"bridge.py imports {module}: only busk itself is public"
        assert names, "import busk names, not the module"
        assert set(names) <= set(busk.__all__), set(names) - set(busk.__all__)


def test_the_plain_modules_import_no_textual_nor_rich() -> None:
    for name in (*PLAIN, "bridge", "app"):
        roots = {root(module) for module, _ in imports(PACKAGE / f"{name}.py")}
        if name == "app":
            roots = {root(module) for module, _ in imports(PACKAGE / "app.py", top_only=True)}
        assert not roots & {"textual", "rich"}, name


def test_app_imports_the_textual_side_only_inside_functions() -> None:
    top = {module for module, _ in imports(PACKAGE / "app.py", top_only=True)}
    assert "busk_tui.shell" not in top
    assert "busk_tui.bridge" not in top
