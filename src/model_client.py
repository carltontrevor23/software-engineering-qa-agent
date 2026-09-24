"""
model_client.py — Sends a prompt to Gemini via LangChain, with
retry/error handling and batch evaluation. Usage: python src/model_client.py [--run-evaluation]
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency in some envs
    def load_dotenv(*args, **kwargs):
        return False

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from rag import build_rag_pipeline


# Setup


load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.6-flash"

if not API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY not found. Create a .env file in the project "
        "root with a line like: GEMINI_API_KEY=your_key_here"
    )

# Shared LangChain chat model for plain (non-tool-calling) prompts.
# agent.py binds its own tools instance rather than reusing this one.
llm = ChatGoogleGenerativeAI(model=MODEL_NAME, google_api_key=API_KEY)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRACES_DIR = PROJECT_ROOT / "evidence" / "traces"
TRACES_DIR.mkdir(parents=True, exist_ok=True)


# Custom exception
class ModelCallError(Exception):
    """Raised when a call to the model fails after retries (rate limit,
    auth failure, network issue, etc.)."""
    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


# Core function (now with error handling + light retry)

def get_model_response(
    prompt: str,
    prompt_version: str = "unversioned",
    max_retries: int = 3,
) -> str:
    """Sends a prompt to Gemini and returns the text response. Logs
    every call, retries rate limits, and raises ModelCallError on failure."""
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 2):  # e.g. max_retries=3 -> 4 attempts
        try:
            ai_message = llm.invoke([HumanMessage(content=prompt)])
            reply_text = ai_message.content

            _log_call(
                prompt=prompt,
                prompt_version=prompt_version,
                response=reply_text,
                status="success",
            )
            return reply_text

        except Exception as e:
            err_msg = str(e).lower()
            is_rate_limited = (
                "429" in err_msg
                or "too_many_requests" in err_msg
                or "quota exceeded" in err_msg
                or "resource_exhausted" in err_msg
                or "rate limit" in err_msg
            )

            if is_rate_limited and attempt <= max_retries:
                wait_seconds = 65  # safely past the 60s sliding RPM window
                print(
                    f"[model_client] Rate limited (429), pausing for {wait_seconds}s "
                    f"before retry {attempt}/{max_retries}...",
                    file=sys.stderr,
                )
                time.sleep(wait_seconds)
                last_error = e
                continue

            # Non-429 errors (or 429 with no retries left) are unrecoverable.
            last_error = e
            _log_call(
                prompt=prompt,
                prompt_version=prompt_version,
                response=None,
                status="failed",
                error=str(e),
            )
            raise ModelCallError(
                f"Model call failed: {e}", cause=e
            ) from e

    # Should not normally reach here, but just in case:
    raise ModelCallError(f"Model call failed: {last_error}", cause=last_error)



# Logging helper


def _log_call(
    prompt: str,
    prompt_version: str,
    response: str | None,
    status: str = "success",
    error: str | None = None,
) -> None:
    """Append a record of this call (success or failure) to a dated trace file."""
    timestamp = datetime.now(timezone.utc).isoformat()

    record = {
        "timestamp_utc": timestamp,
        "model": MODEL_NAME,
        "prompt_version": prompt_version,
        "status": status,          # "success" or "failed"
        "prompt": prompt,
        "response": response,      # None if the call failed
        "error": error,            # None if the call succeeded
    }

    trace_file = TRACES_DIR / f"trace_{datetime.now(timezone.utc).date()}.jsonl"
    with open(trace_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")



# Prompt template loader (for use with prompts/v1.0_test_proposal.txt)


def load_prompt_template(template_path: str) -> str:
    """Read a prompt specification file from disk as a plain string."""
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()


def build_test_proposal_prompt(
    template_path: str,
    module_description: str,
    requirements_excerpt: str,
) -> str:
    """
    Fill in the {{module_description}} and {{requirements_excerpt}}
    placeholders in a prompt specification template.
    """
    template = load_prompt_template(template_path)
    prompt = template.replace("{{module_description}}", module_description)
    prompt = prompt.replace("{{requirements_excerpt}}", requirements_excerpt)
    return prompt

def build_grounded_prompt(
    module_description: str,
    query: str,
    template_path: str,
    corpus_dir: str = str(PROJECT_ROOT / "docs" / "requirements"),
    top_k: int = 3,
    min_score: float = 1.0,
) -> str:
    """Retrieves top-k requirement chunks for `query`, formats them into
    a cited context block, and inserts it into the test-proposal prompt."""
    retriever = build_rag_pipeline(corpus_dir)
    results = retriever.retrieve(query, top_k=top_k, min_score=min_score)
    requirements_excerpt = retriever.format_context_for_prompt(results)


    return build_test_proposal_prompt(
        template_path=template_path,
        module_description=module_description,
        requirements_excerpt=requirements_excerpt,
    )


# Batch evaluation runner (runs all 10 cases in one go)


def run_evaluation(
    cases_path: str,
    template_path: str,
    prompt_version: str,
    output_path: str,
    delay_between_calls: float = 65.0,
) -> list[dict]:
    """Runs each evaluation case through the model and saves results to
    output_path as JSON, paced by delay_between_calls."""
    with open(cases_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    results = []

    for index, case in enumerate(cases):
        case_id = case.get("id")
        print(f"[model_client] Running case {case_id}...")

        prompt = build_test_proposal_prompt(
            template_path=template_path,
            module_description=case.get("module_description", ""),
            requirements_excerpt=case.get("requirements_excerpt", ""),
        )

        result = {
            "id": case_id,
            "case_type": case.get("case_type"),
            "module_description": case.get("module_description"),
            "requirements_excerpt": case.get("requirements_excerpt"),
            "expected_behaviour": case.get("expected_behaviour"),
            "actual_behaviour": None,
            "status": None,
        }

        try:
            actual = get_model_response(prompt, prompt_version=prompt_version)
            result["actual_behaviour"] = actual
            result["status"] = "completed"
        except ModelCallError as e:
            result["actual_behaviour"] = f"[CALL FAILED] {e}"
            result["status"] = "error"
            print(f"[model_client] Case {case_id} failed: {e}", file=sys.stderr)

        results.append(result)
        # Pace requests to respect free-tier RPM ceilings (skip delay after the last case)
        if index < len(cases) - 1:
            time.sleep(delay_between_calls)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n[model_client] Done. {len(results)} cases run.")
    print(f"[model_client] Results saved to: {output_path}")

    return results



# Command-line entry point


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="QA Agent model client")
    parser.add_argument(
        "--run-evaluation",
        action="store_true",
        help="Run all cases from evaluation_cases.json instead of the connection test.",
    )
    parser.add_argument(
        "--cases",
        default=str(PROJECT_ROOT / "docs" / "evaluation" / "evaluation_cases.json"),
        help="Path to the JSON file of evaluation cases.",
    )
    parser.add_argument(
        "--template",
        default=str(PROJECT_ROOT / "prompts" / "v1.0_test_proposal.txt"),
        help="Path to the prompt specification template to test.",
    )
    parser.add_argument(
        "--prompt-version",
        default="v1.0",
        help="Label recorded in logs/results for this run (e.g. v1.0, v1.1).",
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "evidence" / "traces" / "evaluation_results.json"),
        help="Where to save the evaluation results JSON.",
    )
    args = parser.parse_args()

    if args.run_evaluation:
        run_evaluation(
            cases_path=args.cases,
            template_path=args.template,
            prompt_version=args.prompt_version,
            output_path=args.output,
        )
    else:
        # Step 1: sanity-check the connection with a throwaway prompt.
        print("=== Step 1: connection test ===")
        try:
            test_reply = get_model_response(
                "Say hello in one sentence.",
                prompt_version="connection_test",
            )
            print(test_reply)
        except ModelCallError as e:
            print(f"Connection test FAILED: {e}")
            sys.exit(1)
        print()

        # Step 2: run a real QA-agent prompt using the v1.0 template.
        print("=== Step 2: real test-proposal prompt ===")
        template_path = str(PROJECT_ROOT / "prompts" / "v1.0_test_proposal.txt")

        # 1. Load your Python file directly from disk into module_description
        source_code_path = PROJECT_ROOT / "src" / "subscription_manager.py"
        with open(source_code_path, "r", encoding="utf-8") as f:
            module_code = f.read()
            example_module = f"Module: src/subscription_manager.py\n\n{module_code}"

        # 2. Retrieve + format context, then build the prompt (Week 3 RAG)
        full_prompt = build_grounded_prompt(
            module_description=example_module,
            query="tier upgrade balance threshold active status",
            template_path=template_path,
        )

        try:
            real_reply = get_model_response(full_prompt, prompt_version="v1.0")
            print(real_reply)
        except ModelCallError as e:
            print(f"Test-proposal call FAILED: {e}")
            sys.exit(1)

        print()
        print(f"Logged to: {TRACES_DIR}")
        print(
            "\nTip: run 'python src/model_client.py --run-evaluation' once "
            "docs/evaluation/evaluation_cases.json exists, to run all 10 cases at once."
        )
