"""
src/sandbox.py

Sandboxed test runner for the QA agent (Week 4, realigned).

The agent may only run pytest on files inside ALLOWED_TEST_DIRS. Tests run in a
separate process with no shell, a timeout, and a minimal environment that carries
no secrets. Generated test code is checked against an import allow-list before it
is written or run.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUT_DIR = PROJECT_ROOT / "sut"
GENERATED_DIR = PROJECT_ROOT / "sandbox" / "generated"
ALLOWED_TEST_DIRS = [GENERATED_DIR, SUT_DIR / "tests"]
TEST_TIMEOUT_SECONDS = 60
MAX_OUTPUT_CHARS = 4000

ALLOWED_IMPORTS = {
    "pytest", "unittest", "json", "os", "tempfile", "pathlib", "requests",
    "subscription_service",
}
BANNED_IMPORTS = {"subprocess", "socket", "shutil", "ctypes", "urllib", "http"}
BANNED_BUILTINS = {"eval", "exec", "compile", "__import__"}
BANNED_OS_CALLS = {"system", "popen", "remove", "unlink", "rmdir"}
BANNED_MUTATING_CALLS = {
    "write_text", "write_bytes", "unlink", "rmdir", "rename", "replace", "mkdir", "chmod",
}
BANNED_REQUESTS_CALLS = {"post", "put", "delete", "patch"}
# Only these variables are copied into the test process; everything else (API keys,
# tokens) is left behind.
ENV_ALLOW_LIST = ("PATH", "SYSTEMROOT", "TEMP", "TMP")


def _root_module(name: str) -> str:
    return name.split(".")[0]


def validate_generated_code(code: str) -> Tuple[bool, str]:
    """Static check of generated test code. Returns (ok, reason)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Generated code does not parse: {e.msg} (line {e.lineno})."

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    return False, "Relative imports are not allowed."
                names = [node.module or ""]
            else:
                names = [alias.name for alias in node.names]
            for name in names:
                root = _root_module(name)
                if root in BANNED_IMPORTS:
                    return False, f"Import of '{name}' is not allowed."
                if root not in ALLOWED_IMPORTS:
                    return False, f"Import of '{name}' is not on the allow-list."
        elif isinstance(node, ast.Name) and node.id in BANNED_BUILTINS:
            return False, f"Use of '{node.id}' is not allowed."
        elif isinstance(node, ast.Attribute):
            if (
                isinstance(node.value, ast.Name)
                and node.value.id == "os"
            ):
                attr = node.attr
                if attr in BANNED_OS_CALLS or attr.startswith(("exec", "spawn")):
                    return False, f"Use of 'os.{attr}' is not allowed."
            elif (
                isinstance(node.value, ast.Name)
                and node.value.id == "requests"
            ):
                if node.attr in BANNED_REQUESTS_CALLS:
                    return False, f"Use of 'requests.{node.attr}' is not allowed in generated tests."
            if node.attr in BANNED_MUTATING_CALLS:
                return False, f"Mutating call '{node.attr}' is not allowed in generated tests."
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "open"
        ):
            for arg in node.args[1:]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if any(m in arg.value for m in ("w", "a", "x", "+")):
                        return False, "Opening files in write or append mode is not allowed in generated tests."
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    if any(m in kw.value.value for m in ("w", "a", "x", "+")):
                        return False, "Opening files in write or append mode is not allowed in generated tests."
    return True, "ok"


def resolve_test_path(test_file: str) -> Tuple[bool, Any]:
    """Resolve test_file and refuse anything outside ALLOWED_TEST_DIRS.

    Returns (True, Path) or (False, reason).
    """
    if not test_file:
        return False, "test_file is required."
    candidate = Path(test_file)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve()
    for allowed in ALLOWED_TEST_DIRS:
        if resolved.is_relative_to(Path(allowed).resolve()):
            if resolved.suffix != ".py" or not resolved.is_file():
                return False, f"Test file '{test_file}' does not exist."
            return True, resolved
    return False, f"Test file '{test_file}' is outside the sandbox's allowed test folders."


def _minimal_env() -> Dict[str, str]:
    env = {k: os.environ[k] for k in ENV_ALLOW_LIST if k in os.environ}
    env["PYTHONPATH"] = str(SUT_DIR)
    return env


def _truncate(text: str) -> str:
    text = text or ""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + "... [truncated]"


def _parse_junit(xml_path: Path) -> Dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = failed = errors = skipped = 0
    failures = []
    for suite in suites:
        total += int(suite.get("tests", 0))
        failed += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
        for case in suite.iter("testcase"):
            for problem in list(case.findall("failure")) + list(case.findall("error")):
                name = "::".join(p for p in (case.get("classname"), case.get("name")) if p)
                message = problem.get("message") or (problem.text or "")
                failures.append({"test_name": name, "message": _truncate(message)})
    return {
        "passed": total - failed - errors - skipped,
        "failed": failed,
        "errors": errors,
        "failures": failures,
    }


def run_pytest(test_file: str) -> Dict[str, Any]:
    """Run pytest on one allowed test file in a separate, secret-free process."""
    ok, resolved = resolve_test_path(test_file)
    if not ok:
        return {"status": "error", "error": resolved}

    workdir = Path(tempfile.mkdtemp(prefix="inspectra_run_"))
    xml_path = workdir / "report.xml"
    cmd = [
        sys.executable, "-m", "pytest", str(resolved), "-q",
        "-p", "no:cacheprovider", "--junitxml", str(xml_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            shell=False,
            cwd=str(PROJECT_ROOT),
            env=_minimal_env(),
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(workdir, ignore_errors=True)
        return {
            "status": "error",
            "error": f"Test run exceeded the {TEST_TIMEOUT_SECONDS}s sandbox timeout and was stopped.",
        }

    try:
        if not xml_path.exists():
            return {
                "status": "error",
                "error": "pytest did not produce a report.",
                "output": _truncate(proc.stdout + proc.stderr),
            }
        counts = _parse_junit(xml_path)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    # Exit code 5 means pytest collected no tests.
    if proc.returncode == 5 or (counts["passed"] + counts["failed"] + counts["errors"]) == 0:
        outcome = "no_tests"
    elif counts["failed"] or counts["errors"]:
        outcome = "failed"
    else:
        outcome = "passed"
    return {"status": "success", "test_outcome": outcome, **counts}
