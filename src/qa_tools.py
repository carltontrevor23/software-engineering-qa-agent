"""
src/qa_tools.py

QA tool implementations for the Inspectra agent (Week 4, realigned).

Workflow: find a requirement -> propose tests -> run them in the sandbox ->
draft an issue for failures -> file the issue (human approval required).
Every function returns a structured {"status": ...} dict and never raises for
expected failures. src/agent_tools.py wraps these as LangChain tools.
"""

from __future__ import annotations

import ast
import os
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

import guardrails
import project_config
import sandbox
from approval import verify_and_consume_token
from model_client import ModelCallError, build_test_proposal_prompt, get_model_response
from rag import build_rag_pipeline

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# The requirements to check: INSPECTRA_REQUIREMENTS_DIR in .env, default docs/requirements.
REQUIREMENTS_DIR = project_config.requirements_dir()
ISSUES_DIR = PROJECT_ROOT / "evidence" / "issues"
PROMPT_TEMPLATE = PROJECT_ROOT / "prompts" / "v1.1_test_proposal.txt"
PROMPT_ADDENDUM = PROJECT_ROOT / "prompts" / "v1.1_pytest_output_addendum.txt"
PROMPT_VERSION = "v1.1+pytest-addendum-v1"
REFINE_TEMPLATE = PROJECT_ROOT / "prompts" / "v1.2_refine_tests.txt"
REFINE_PROMPT_VERSION = "v1.2-refine+pytest-addendum-v1"
MAX_READ_CHARS = 20_000
MAX_REFINE_INPUT_CHARS = 20_000
# GitHub Issues integration for file_issue; used only when GITHUB_TOKEN and GITHUB_REPO are set.
GITHUB_API = "https://api.github.com/repos/{repo}/issues"
GITHUB_LABELS = ["inspectra-qa"]
GITHUB_TIMEOUT_SECONDS = 15

_SECTION_RE = re.compile(r"^##\s+Section\s+(\d+(?:\.\d+)*)\s*:\s*(.+?)\s*$")
_CODE_BLOCK_RE = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)


# ---------------------------------------------------------------------
# Requirement IDs (deterministic, no LLM)
# ---------------------------------------------------------------------

def _source_label(path: Path) -> str:
    """Repo-relative path for files inside this repository, else 'folder/file' (no absolute paths)."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return f"{path.parent.name}/{path.name}"


def list_requirements() -> List[Dict[str, Any]]:
    """Parse '## Section X.Y: Title' headings in the requirements folder into REQ-X.Y records."""
    requirements = []
    for path in sorted(REQUIREMENTS_DIR.glob("*.md")):
        current = None
        body: List[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            match = _SECTION_RE.match(line.strip())
            if match:
                if current:
                    current["text"] = "\n".join(body).strip()
                    requirements.append(current)
                current = {
                    "requirement_id": f"REQ-{match.group(1)}",
                    "title": match.group(2),
                    "source_file": _source_label(path),
                }
                body = [line.strip()]
            elif current is not None:
                if line.strip().startswith("## "):
                    current["text"] = "\n".join(body).strip()
                    requirements.append(current)
                    current = None
                else:
                    body.append(line)
        if current:
            current["text"] = "\n".join(body).strip()
            requirements.append(current)
    return requirements


def load_requirement(requirement_id: str) -> Dict[str, Any]:
    for req in list_requirements():
        if req["requirement_id"] == requirement_id:
            return {"status": "success", **req}
    if not any(REQUIREMENTS_DIR.glob("*.md")):
        return {"status": "error", "error": f"No requirement files (*.md) in '{REQUIREMENTS_DIR.name}'."}
    return {"status": "error", "error": f"Unknown requirement '{requirement_id}'."}


def _requirement_id_from_section(section: str) -> Optional[str]:
    match = re.match(r"Section\s+(\d+(?:\.\d+)*)", section or "")
    return f"REQ-{match.group(1)}" if match else None


def _invalid_requirement_id(tool_name: str, requirement_id: Any) -> Optional[Dict[str, Any]]:
    """Error result for a malformed requirement id (input validation), else None."""
    reason = guardrails.check_requirement_id(requirement_id)
    if reason is None:
        return None
    guardrails.record("input_rejected", tool=tool_name, reason=reason)
    return {"status": "error", "error": reason}


def _file_slug(requirement_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", requirement_id.lower()).strip("_")


def requirement_id_from_args(args: Dict[str, Any]) -> str:
    """Case-history key for a tool call: the explicit requirement_id, else the id
    embedded in a draft name (ISSUE-REQ-2.1-...) or generated test name (test_req_2_1_...)."""
    if args.get("requirement_id"):
        return str(args["requirement_id"])
    name = Path(str(args.get("draft_path") or args.get("test_file") or "")).name
    match = re.match(r"ISSUE-(REQ-\d+(?:\.\d+)*)-", name)
    if match:
        return match.group(1)
    match = re.match(r"test_req_(\d+(?:_\d+)*)_[0-9a-f]{8}\.py$", name)
    if match:
        return "REQ-" + match.group(1).replace("_", ".")
    return "unknown"


# ---------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------

def search_requirements(query: str, top_k: int = 3) -> Dict[str, Any]:
    """BM25 search over docs/requirements (Week 3 RAG)."""
    invalid = guardrails.check_query(query, top_k)
    if invalid:
        guardrails.record("input_rejected", tool="search_requirements", reason=invalid)
        return {"status": "error", "error": invalid}
    try:
        retriever = build_rag_pipeline(str(REQUIREMENTS_DIR))
    except FileNotFoundError:
        return {"status": "error", "error": "Requirements corpus not found."}
    hits = retriever.retrieve(query, top_k=top_k)
    results = [
        {
            "requirement_id": _requirement_id_from_section(hit["chunk"].section),
            "source_file": hit["chunk"].source_file,
            "score": hit["score"],
            "text": hit["chunk"].text,
        }
        for hit in hits
    ]
    if not results:
        return {"status": "success", "results": [], "note": "NO_RELEVANT_REQUIREMENTS_FOUND"}
    return {"status": "success", "results": results}


def _sut_module_description() -> tuple:
    """(module text for the prompt, dotted name of the first module) for the configured code."""
    return project_config.module_description(Path(sandbox.SUT_DIR))


def _prompt_context(req: Dict[str, Any]) -> tuple:
    """((module text, addendum rules), None) for the configured project, or (None, error dict)."""
    try:
        module_text, first_module = _sut_module_description()
    except (project_config.ProjectConfigError, OSError) as e:
        return None, {"status": "error", "error": f"The code under test cannot be read: {e}"}
    addendum = PROMPT_ADDENDUM.read_text(encoding="utf-8")
    addendum = addendum.replace("{{first_module}}", first_module).replace(
        "{{packages}}", ", ".join(sorted(project_config.top_level_packages(Path(sandbox.SUT_DIR))))
    )
    return (module_text, addendum), None


def _save_generated_tests(requirement_id: str, reply: str) -> Dict[str, Any]:
    """Validate a model reply that should hold one python block and save it as a new test file."""
    if reply.strip().startswith("NO_GROUNDED_TESTS_FOUND"):
        return {"status": "error", "error": reply.strip()[:500]}
    match = _CODE_BLOCK_RE.search(reply)
    if not match:
        return {"status": "error", "error": "Model reply contained no python code block."}
    code = match.group(1)

    ok, reason = sandbox.validate_generated_code(code)
    if not ok:
        return {"status": "error", "error": f"Generated tests rejected by sandbox policy: {reason}"}

    test_count = sum(
        1 for node in ast.walk(ast.parse(code))
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    )
    test_path = sandbox.GENERATED_DIR / f"test_{_file_slug(requirement_id)}_{secrets.token_hex(4)}.py"
    try:
        sandbox.GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        test_path.write_text(code, encoding="utf-8")
    except OSError:
        return {"status": "error", "error": "Could not save the proposed tests, action not completed."}
    return {
        "status": "success",
        "requirement_id": requirement_id,
        "test_file": str(test_path),
        "test_count": test_count,
    }


def propose_tests(requirement_id: str) -> Dict[str, Any]:
    """Ask the model for pytest tests for one requirement and save them to the sandbox."""
    invalid = _invalid_requirement_id("propose_tests", requirement_id)
    if invalid:
        return invalid
    req = load_requirement(requirement_id)
    if req["status"] != "success":
        return req
    context, error = _prompt_context(req)
    if error:
        return error
    module_text, addendum = context

    prompt = build_test_proposal_prompt(
        template_path=str(PROMPT_TEMPLATE),
        module_description=module_text,
        requirements_excerpt=f"Source: {req['source_file']}\n{req['text']}",
    )
    prompt += "\n\n" + addendum
    try:
        reply = get_model_response(prompt, prompt_version=PROMPT_VERSION)
    except ModelCallError as e:
        return {"status": "error", "error": f"Model unavailable, no tests proposed: {e}"}
    return _save_generated_tests(requirement_id, reply)


def refine_tests(requirement_id: str, test_file: str, instruction: str) -> Dict[str, Any]:
    """Write a NEW test file: the given generated tests changed as the developer asks."""
    invalid = _invalid_requirement_id("refine_tests", requirement_id)
    if invalid:
        return invalid
    bad = guardrails.check_instruction(instruction)
    if bad:
        guardrails.record("input_rejected", tool="refine_tests", reason=bad)
        return {"status": "error", "error": bad}
    ok, resolved = sandbox.resolve_test_path(test_file)
    if not ok:
        return {"status": "error", "error": resolved}
    if not resolved.is_relative_to(Path(sandbox.GENERATED_DIR).resolve()):
        return {"status": "error", "error": "Only generated tests can be refined."}
    existing = resolved.read_text(encoding="utf-8")
    if len(existing) > MAX_REFINE_INPUT_CHARS:
        return {"status": "error", "error": "The existing tests are too long to refine."}
    req = load_requirement(requirement_id)
    if req["status"] != "success":
        return req
    context, error = _prompt_context(req)
    if error:
        return error
    module_text, addendum = context

    prompt = REFINE_TEMPLATE.read_text(encoding="utf-8")
    for key, value in (
        ("{{module_description}}", module_text),
        ("{{requirements_excerpt}}", f"Source: {req['source_file']}\n{req['text']}"),
        ("{{existing_tests}}", existing),
        ("{{instruction}}", guardrails.clean_text(instruction).strip()),
    ):
        prompt = prompt.replace(key, value)
    prompt += "\n\n" + addendum
    try:
        reply = get_model_response(prompt, prompt_version=REFINE_PROMPT_VERSION)
    except ModelCallError as e:
        return {"status": "error", "error": f"Model unavailable, no tests written: {e}"}
    result = _save_generated_tests(requirement_id, reply)
    if result["status"] == "success":
        result["refined_from"] = resolved.name
    return result


_HIDDEN_PARTS = {".git", "venv", ".venv", "site-packages", "__pycache__", "node_modules"}


def read_code(file: str = "") -> Dict[str, Any]:
    """Read-only: list the code under test, or return one source file from it."""
    directory = Path(sandbox.SUT_DIR).resolve()
    if not file:
        try:
            modules = project_config.code_modules(directory)
        except project_config.ProjectConfigError as e:
            return {"status": "error", "error": str(e)}
        return {"status": "success", "files": [m.as_posix() for m in modules]}
    if not isinstance(file, str) or len(file) > 200:
        return {"status": "error", "error": "file must be a short relative path such as pkg/module.py."}
    target = (directory / file).resolve()
    inside = target.is_relative_to(directory)
    relative_parts = target.relative_to(directory).parts if inside else ()
    if (not inside or target.suffix != ".py" or not target.is_file()
            or any(part in _HIDDEN_PARTS or part.startswith(".") for part in relative_parts)):
        guardrails.record("input_rejected", tool="read_code", reason="path outside the readable code")
        return {"status": "error", "error": "Only .py files inside the code under test can be read."}
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {"status": "error", "error": "That file could not be read."}
    return {
        "status": "success",
        "file": target.relative_to(directory).as_posix(),
        "content": text[:MAX_READ_CHARS],
        "truncated": len(text) > MAX_READ_CHARS,
    }


def run_tests(requirement_id: str, test_file: str) -> Dict[str, Any]:
    """Run one allowed test file in the sandbox and report the outcome."""
    invalid = _invalid_requirement_id("run_tests", requirement_id)
    if invalid:
        return invalid
    ok, resolved = sandbox.resolve_test_path(test_file)
    if not ok:
        return {"status": "error", "error": resolved}
    # Defence in depth: re-check generated files in case they changed after writing.
    if resolved.is_relative_to(Path(sandbox.GENERATED_DIR).resolve()):
        valid, reason = sandbox.validate_generated_code(resolved.read_text(encoding="utf-8"))
        if not valid:
            return {"status": "error", "error": f"Test file rejected by sandbox policy: {reason}"}
    result = sandbox.run_pytest(str(resolved))
    if result["status"] == "success":
        result["requirement_id"] = requirement_id
    return result


def draft_issue(
    requirement_id: str, title: str, summary: str, failing_tests: List[str]
) -> Dict[str, Any]:
    """Write a Markdown issue draft. Low impact: nothing leaves the repo."""
    invalid = _invalid_requirement_id("draft_issue", requirement_id)
    if invalid:
        return invalid
    bad_fields = guardrails.check_draft_fields(title, summary, failing_tests)
    if bad_fields:
        guardrails.record("input_rejected", tool="draft_issue", reason=bad_fields)
        return {"status": "error", "error": bad_fields}
    req = load_requirement(requirement_id)
    if req["status"] != "success":
        return req

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    drafts_dir = ISSUES_DIR / "drafts"
    draft_path = drafts_dir / f"ISSUE-{requirement_id}-{stamp}.md"

    quoted = "\n".join(f"> {line}" if line else ">" for line in req["text"].splitlines())
    tests = "\n".join(f"- `{guardrails.single_line(str(name))}`" for name in failing_tests) or "- (none listed)"
    try:
        drafts_dir.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(
            f"# {guardrails.single_line(title)}\n\n"
            f"**Requirement:** {requirement_id} ({req['source_file']})\n\n"
            f"{quoted}\n\n"
            f"## Failing tests\n\n{tests}\n\n"
            f"## Summary\n\n{guardrails.clean_text(summary)}\n\n"
            f"---\n_Drafted by Inspectra QA agent - not filed._\n",
            encoding="utf-8",
        )
    except OSError:
        return {"status": "error", "error": "Could not write the issue draft, action not completed."}
    return {"status": "success", "draft_path": str(draft_path)}


def _inside(path: Path, folder: Path) -> bool:
    return path.resolve().is_relative_to(folder.resolve())


def file_issue(draft_path: str, approval_token: Optional[str] = None) -> Dict[str, Any]:
    """HIGH IMPACT: file an approved draft. Needs a human-approved signed token."""
    is_valid, reason = verify_and_consume_token(
        approval_token, "file_issue", {"draft_path": draft_path}
    )
    if not is_valid:
        return {"status": "approval_required", "error": reason}

    source = Path(draft_path)
    if not _inside(source, ISSUES_DIR / "drafts") or not source.is_file():
        return {"status": "error", "error": "draft_path must be an existing draft in evidence/issues/drafts."}

    token, repo = os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPO")
    if token and repo:
        return _file_on_github(source, token, repo)
    try:
        filed_dir = ISSUES_DIR / "filed"
        filed_dir.mkdir(parents=True, exist_ok=True)
        filed_path = filed_dir / source.name
        shutil.copyfile(source, filed_path)
    except OSError:
        return {"status": "error", "error": "Could not file the issue, action not completed."}
    return {"status": "success", "filed_path": str(filed_path), "channel": "local"}


def _file_on_github(source: Path, token: str, repo: str) -> Dict[str, Any]:
    """POST the draft to GitHub Issues. The token is only ever sent in the header;
    it is never logged or returned. On failure the draft is kept and nothing is filed locally."""
    body = source.read_text(encoding="utf-8")
    first_line = body.splitlines()[0] if body else ""
    title = first_line.lstrip("#").strip() or source.stem
    try:
        response = requests.post(
            GITHUB_API.format(repo=repo),
            json={"title": title, "body": body, "labels": GITHUB_LABELS},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=GITHUB_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as e:
        return {"status": "error", "error": f"GitHub unreachable ({type(e).__name__}); draft kept at {source.name}."}
    if response.status_code != 201:
        return {"status": "error", "error": f"GitHub returned HTTP {response.status_code}; draft kept at {source.name}."}
    return {"status": "success", "channel": "github", "issue_url": response.json().get("html_url")}


def save_test_to_suite(test_file: str, approval_token: Optional[str] = None) -> Dict[str, Any]:
    """HIGH IMPACT: copy a generated test into the code folder's tests/ (a repo change)."""
    is_valid, reason = verify_and_consume_token(
        approval_token, "save_test_to_suite", {"test_file": test_file}
    )
    if not is_valid:
        return {"status": "approval_required", "error": reason}

    source = Path(test_file)
    if not _inside(source, sandbox.GENERATED_DIR) or not source.is_file():
        return {"status": "error", "error": "test_file must be an existing generated test in sandbox/generated."}
    try:
        suite_dir = sandbox.SUT_DIR / "tests"
        suite_dir.mkdir(parents=True, exist_ok=True)
        saved_path = suite_dir / source.name
        shutil.copyfile(source, saved_path)
    except OSError:
        return {"status": "error", "error": "Could not save the test, action not completed."}
    return {"status": "success", "saved_path": str(saved_path)}
