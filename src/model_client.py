"""
model_client.py

Baseline model integration for the Software-Engineering QA Agent.

This module's core job is still simple: send a prompt to Gemini and
return the text response. No RAG, no tools, no agent loop yet — those
come in later weeks. On top of that it now also handles:

  - API failures gracefully (rate limits, bad key, network issues)
    instead of crashing with a raw traceback.
  - Running a whole batch of evaluation cases in one go, instead of
    calling get_model_response() by hand for each of the 10 cases.

Usage (quick manual connection test):
    python src/model_client.py

Usage (run all 10 evaluation cases and save results):
    python src/model_client.py --run-evaluation

Usage (import into other code, e.g. a future tools/agent layer):
    from model_client import get_model_response
    reply = get_model_response("Say hello in one sentence.")
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors


# Setup


load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.6-flash"

if not API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY not found. Create a .env file in the project "
        "root with a line like: GEMINI_API_KEY=your_key_here"
    )

client = genai.Client(api_key=API_KEY)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRACES_DIR = PROJECT_ROOT / "evidence" / "traces"
TRACES_DIR.mkdir(parents=True, exist_ok=True)


# Custom exception
class ModelCallError(Exception):
    """
    Raised when a call to the model fails after retries, for a reason
    the caller should know about (rate limit, auth failure, network
    issue, etc.) rather than an unhandled crash.
    """
    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


# Core function (now with error handling + light retry)

def get_model_response(
    prompt: str,
    prompt_version: str = "unversioned",
    max_retries: int = 2,
) -> str:
    """
    Send a prompt to Gemini and return the text response.

    Every call — successful or failed — is logged to evidence/traces/
    with a timestamp, the prompt version label, the full prompt sent,
    and either the response or the error. This is the evidence trail
    required by the project brief (US-10: every agent action must be
    logged and traceable, including refusals/failures).

    On failure (rate limit, bad key, network issue, etc.), this
    retries a small number of times with a short pause, then raises
    ModelCallError with a clear message instead of letting the raw
    SDK traceback crash the whole script. Callers (e.g. the batch
    evaluation runner) can catch ModelCallError per-case so one
    failed case doesn't kill the other nine.

    Args:
        prompt: The full, already-assembled prompt text to send.
        prompt_version: A label like "v1.0" or "v1.1", used only for
            logging so you can trace which prompt spec produced which
            output. Does not affect the API call itself.
        max_retries: How many extra attempts to make after the first
            failed call, before giving up. Default 2 (3 attempts total).

    Returns:
        The model's text response as a string.

    Raises:
        ModelCallError: if the call fails on every attempt.
    """
    import time

    last_error: Exception | None = None

    for attempt in range(1, max_retries + 2):  # e.g. max_retries=2 -> 3 attempts
        try:
            interaction = client.interactions.create(
                model=MODEL_NAME,
                input=prompt,
            )
            reply_text = interaction.output_text

            _log_call(
                prompt=prompt,
                prompt_version=prompt_version,
                response=reply_text,
                status="success",
            )
            return reply_text

        except genai_errors.ClientError as e:
            # 4xx errors (bad key, model not found, permission denied,
            # bad request) generally won't fix themselves by retrying.
            last_error = e
            _log_call(
                prompt=prompt,
                prompt_version=prompt_version,
                response=None,
                status="failed",
                error=str(e),
            )
            raise ModelCallError(
                f"Model call failed (client error, not retried): {e}", cause=e
            ) from e

        except genai_errors.ServerError as e:
            # 5xx errors / rate limiting are often transient — worth a retry.
            last_error = e
            if attempt <= max_retries:
                wait_seconds = 2 ** attempt  # simple backoff: 2s, 4s, ...
                print(
                    f"[model_client] Call failed (attempt {attempt}), "
                    f"retrying in {wait_seconds}s... ({e})",
                    file=sys.stderr,
                )
                time.sleep(wait_seconds)
                continue
            _log_call(
                prompt=prompt,
                prompt_version=prompt_version,
                response=None,
                status="failed",
                error=str(e),
            )
            raise ModelCallError(
                f"Model call failed after {attempt} attempts: {e}", cause=e
            ) from e

        except Exception as e:
            # Anything unexpected (network issue, etc.) — log and stop.
            last_error = e
            _log_call(
                prompt=prompt,
                prompt_version=prompt_version,
                response=None,
                status="failed",
                error=str(e),
            )
            raise ModelCallError(
                f"Model call failed with an unexpected error: {e}", cause=e
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



# Batch evaluation runner (runs all 10 cases in one go)


def run_evaluation(
    cases_path: str,
    template_path: str,
    prompt_version: str,
    output_path: str,
) -> list[dict]:
    """
    Load a JSON file of evaluation cases, run each one through the
    model using the given prompt template, and save the results
    (including the model's actual output) to output_path as JSON.

    This is what turns the 10-case evaluation table from a manual,
    one-call-at-a-time chore into a single command. If one case fails
    (e.g. a transient API error), the run continues with the rest —
    the failure is recorded for that case instead of stopping the
    whole batch.

    Expected format of the cases JSON file: a list of objects like:
        {
          "id": 1,
          "case_type": "Normal / grounded",
          "module_description": "...",
          "requirements_excerpt": "...",
          "expected_behaviour": "..."
        }

    Returns:
        The list of result records (also written to output_path).
    """
    with open(cases_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    results = []

    for case in cases:
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

        example_module = "payment_service.calculate_total()"
        example_requirements = (
            "Source: docs/requirements/payment.md, section 3.2\n"
            "'calculate_total() must apply a 10% discount when the cart "
            "total exceeds 100,000 UGX, and must reject negative quantities "
            "with a ValueError.'"
        )

        full_prompt = build_test_proposal_prompt(
            template_path=template_path,
            module_description=example_module,
            requirements_excerpt=example_requirements,
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