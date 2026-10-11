"""
src/qa_tools.py

QA tool implementations for the Inspectra agent (Week 4, realigned).

Workflow: find a requirement -> propose tests -> run them in the sandbox ->
draft an issue for failures -> file the issue (human approval required).
Every function returns a structured {"status": ...} dict and never raises for
expected failures. src/tool_calling.py wraps these as LangChain tools.
"""

from __future__ import annotations

import ast
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import sandbox
from approval import verify_and_consume_token
from model_client import ModelCallError, build_test_proposal_prompt, get_model_response
from rag import build_rag_pipeline

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_DIR = PROJECT_ROOT / "docs" / "requirements"
ISSUES_DIR = PROJECT_ROOT / "evidence" / "issues"
PROMPT_TEMPLATE = PROJECT_ROOT / "prompts" / "v1.1_test_proposal.txt"
PROMPT_ADDENDUM = PROJECT_ROOT / "prompts" / "v1.1_pytest_output_addendum.txt"
PROMPT_VERSION = "v1.1+pytest-addendum-v1"
SUT_MODULE = Path("subscription_service") / "subscription_manager.py"
SUT_IMPORT_LINE = (
    "from subscription_service.subscription_manager import (SubscriptionManager, "
    "InsufficientFundsError, InactiveUserError, AlreadyPremiumError, UserNotFoundError)"
)

_SECTION_RE = re.compile(r"^##\s+Section\s+(\d+(?:\.\d+)*)\s*:\s*(.+?)\s*$")
_CODE_BLOCK_RE = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)


# ---------------------------------------------------------------------
# Requirement IDs (deterministic, no LLM)
# ---------------------------------------------------------------------

def list_requirements() -> List[Dict[str, Any]]:
    """Parse '## Section X.Y: Title' headings in docs/requirements into REQ-X.Y records."""
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
                    "source_file": f"docs/requirements/{path.name}",
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
    return {"status": "error", "error": f"Unknown requirement '{requirement_id}'."}


def _requirement_id_from_section(section: str) -> Optional[str]:
    match = re.match(r"Section\s+(\d+(?:\.\d+)*)", section or "")
    return f"REQ-{match.group(1)}" if match else None


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


def _sut_module_description() -> str:
    source = (sandbox.SUT_DIR / SUT_MODULE).read_text(encoding="utf-8")
    return (
        f"Module: sut/{SUT_MODULE.as_posix()}\n"
        f"Import it in tests with: {SUT_IMPORT_LINE}\n\n{source}"
    )


def propose_tests(requirement_id: str) -> Dict[str, Any]:
    """Ask the model for pytest tests for one requirement and save them to the sandbox."""
    req = load_requirement(requirement_id)
    if req["status"] != "success":
        return req

    prompt = build_test_proposal_prompt(
        template_path=str(PROMPT_TEMPLATE),
        module_description=_sut_module_description(),
        requirements_excerpt=f"Source: {req['source_file']}\n{req['text']}",
    )
    prompt += "\n\n" + PROMPT_ADDENDUM.read_text(encoding="utf-8")

    try:
        reply = get_model_response(prompt, prompt_version=PROMPT_VERSION)
    except ModelCallError as e:
        return {"status": "error", "error": f"Model unavailable, no tests proposed: {e}"}

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
    sandbox.GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    test_path = sandbox.GENERATED_DIR / f"test_{_file_slug(requirement_id)}_{secrets.token_hex(4)}.py"
    test_path.write_text(code, encoding="utf-8")
    return {
        "status": "success",
        "requirement_id": requirement_id,
        "test_file": str(test_path),
        "test_count": test_count,
    }


def run_tests(requirement_id: str, test_file: str) -> Dict[str, Any]:
    """Run one allowed test file in the sandbox and report the outcome."""
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
    req = load_requirement(requirement_id)
    if req["status"] != "success":
        return req

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    drafts_dir = ISSUES_DIR / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    draft_path = drafts_dir / f"ISSUE-{requirement_id}-{stamp}.md"

    quoted = "\n".join(f"> {line}" if line else ">" for line in req["text"].splitlines())
    tests = "\n".join(f"- `{name}`" for name in failing_tests) or "- (none listed)"
    draft_path.write_text(
        f"# {title}\n\n"
        f"**Requirement:** {requirement_id} ({req['source_file']})\n\n"
        f"{quoted}\n\n"
        f"## Failing tests\n\n{tests}\n\n"
        f"## Summary\n\n{summary}\n\n"
        f"---\n_Drafted by Inspectra QA agent - not filed._\n",
        encoding="utf-8",
    )
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
    try:
        filed_dir = ISSUES_DIR / "filed"
        filed_dir.mkdir(parents=True, exist_ok=True)
        filed_path = filed_dir / source.name
        shutil.copyfile(source, filed_path)
    except OSError:
        return {"status": "error", "error": "Could not file the issue, action not completed."}
    return {"status": "success", "filed_path": str(filed_path), "channel": "local"}


def save_test_to_suite(test_file: str, approval_token: Optional[str] = None) -> Dict[str, Any]:
    """HIGH IMPACT: copy a generated test into sut/tests (a repo change)."""
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
