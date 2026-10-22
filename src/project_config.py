"""
src/project_config.py

Which project Inspectra checks. The operator chooses it in .env (or the environment);
the model never sees or sets these paths, so a prompt cannot point the agent elsewhere.

  INSPECTRA_REQUIREMENTS_DIR  folder of requirement .md files with '## Section X.Y: Title'
                              headings (default: docs/requirements)
  INSPECTRA_CODE_DIR          the folder to put on PYTHONPATH: it holds the importable
                              package(s) under test, and its tests/ folder receives approved
                              tests (default: sut)
  INSPECTRA_CODE_MODULES      optional, comma-separated .py files (relative to the code dir)
                              whose source is shown to the test writer; default: every
                              non-test .py file under the code dir

Relative paths are resolved against the repository root. Run `python src/project_config.py`
to check a configuration before starting the agent.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import List, Tuple

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional; plain environment variables still work
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REQUIREMENTS_DIR = PROJECT_ROOT / "docs" / "requirements"
DEFAULT_CODE_DIR = PROJECT_ROOT / "sut"

MAX_SOURCE_CHARS = 30_000
_SKIP_DIRS = {"tests", "test", "__pycache__", "venv", ".venv", "node_modules", ".git", "site-packages"}


class ProjectConfigError(ValueError):
    """The configured project cannot be used. The message says how to fix it."""


def _resolve(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    path = Path(raw).expanduser()
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()


def requirements_dir() -> Path:
    path = _resolve("INSPECTRA_REQUIREMENTS_DIR", DEFAULT_REQUIREMENTS_DIR)
    if not path.is_dir():
        raise ProjectConfigError(f"INSPECTRA_REQUIREMENTS_DIR '{path.name}' is not a folder.")
    return path


def code_dir() -> Path:
    path = _resolve("INSPECTRA_CODE_DIR", DEFAULT_CODE_DIR)
    if not path.is_dir():
        raise ProjectConfigError(f"INSPECTRA_CODE_DIR '{path.name}' is not a folder.")
    # The test process must not be able to see this repository (.env, source, evidence).
    if path == PROJECT_ROOT or path in PROJECT_ROOT.parents:
        raise ProjectConfigError(
            "INSPECTRA_CODE_DIR must be the folder that holds the code under test, "
            "not this repository's root or a parent of it."
        )
    return path


def _is_test_file(path: Path) -> bool:
    return path.name.startswith("test_") or path.name.endswith("_test.py") or path.name == "conftest.py"


def code_modules(directory: Path) -> List[Path]:
    """Source files shown to the test writer, as paths relative to `directory`."""
    listed = os.environ.get("INSPECTRA_CODE_MODULES", "").strip()
    if listed:
        modules = []
        for name in (n.strip() for n in listed.split(",") if n.strip()):
            full = (directory / name).resolve()
            if not full.is_file() or not full.is_relative_to(directory.resolve()) or full.suffix != ".py":
                raise ProjectConfigError(f"INSPECTRA_CODE_MODULES entry '{name}' is not a .py file in the code folder.")
            modules.append(full.relative_to(directory.resolve()))
        return modules
    found = []
    for path in sorted(directory.rglob("*.py")):
        relative = path.relative_to(directory)
        if any(part in _SKIP_DIRS or part.startswith(".") for part in relative.parts[:-1]):
            continue
        if path.name == "__init__.py" or _is_test_file(path):
            continue
        found.append(relative)
    return found


def top_level_packages(directory: Path) -> set:
    """Names a test may import from the code folder: its packages and top-level modules."""
    names = set()
    for child in directory.iterdir():
        if child.name in _SKIP_DIRS or child.name.startswith((".", "_")):
            continue
        if child.is_dir() and any(child.rglob("*.py")):
            names.add(child.name)
        elif child.suffix == ".py" and not _is_test_file(child):
            names.add(child.stem)
    return names


def dotted(relative: Path) -> str:
    return ".".join(relative.with_suffix("").parts)


def public_names(source: str) -> List[str]:
    """Top-level classes and functions a test would import."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return [
        node.name for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
    ]


def module_description(directory: Path) -> Tuple[str, str]:
    """(text for the test-writer prompt, dotted name of the first module). The text holds each
    module's source and the exact import line to use."""
    modules = code_modules(directory)
    if not modules:
        raise ProjectConfigError("No source files found in the code folder (INSPECTRA_CODE_DIR).")
    parts, used = [], 0
    for relative in modules:
        source = (directory / relative).read_text(encoding="utf-8")
        used += len(source)
        if used > MAX_SOURCE_CHARS and parts:
            parts.append(f"(further modules omitted: size limit of {MAX_SOURCE_CHARS} characters)")
            break
        names = public_names(source)
        import_line = f"from {dotted(relative)} import ({', '.join(names)})" if names else f"import {dotted(relative)}"
        parts.append(
            f"Module: {relative.as_posix()}\nImport it in tests with: {import_line}\n\n{source}"
        )
    return "\n\n".join(parts), dotted(modules[0])


def describe() -> str:
    req, code = requirements_dir(), code_dir()
    return (
        f"requirements: {req}\ncode: {code}\n"
        f"modules: {', '.join(m.as_posix() for m in code_modules(code)) or '(none)'}\n"
        f"importable: {', '.join(sorted(top_level_packages(code))) or '(none)'}"
    )


if __name__ == "__main__":
    try:
        print(describe())
    except ProjectConfigError as exc:
        print(f"Configuration problem: {exc}")
        raise SystemExit(1)
