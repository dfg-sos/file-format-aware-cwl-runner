"""The core does not import extensions, and extensions do not import each other."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "sos_cwl"
EXTENSIONS = sorted(p.name for p in (SRC / "extensions").iterdir() if (p / "__init__.py").exists())


def imported_modules(package: Path) -> set[str]:
    found = set()
    for path in package.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module)
            elif isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
    return found


def test_core_does_not_import_extensions():
    assert not {m for m in imported_modules(SRC / "core") if m.startswith("sos_cwl.extensions")}


@pytest.mark.parametrize("name", EXTENSIONS)
def test_extension_imports_only_core(name):
    imports = {m for m in imported_modules(SRC / "extensions" / name) if m.startswith("sos_cwl")}
    assert all(m.startswith("sos_cwl.core") for m in imports), imports
