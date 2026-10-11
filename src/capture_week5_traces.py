"""
src/capture_week5_traces.py

Week 5 (realigned): capture three execution traces of the bounded QA agent.

  T1  REQ-2.1 on the correct SUT. Whatever really happens is recorded: a pass, or a
      "test defect" if a generated test is wrong.
  T2  REQ-2.1 with the planted boundary defect: failure -> draft -> approval -> filed.
  T3  Failure/recovery: same as T2, but the human REJECTS file_issue. The agent stops
      with human_rejection and nothing new appears in evidence/issues/filed/.

Each scenario runs against the live Gemini model. Only if a live run fails (quota,
network, key) is it re-run with the scripted LLM; the mode used is recorded per trace.
Approvals use approval.set_approval_hook, and every decision is logged.

Outputs:
  - evidence/traces/week5_live_traces.jsonl
  - evidence/week5_live_execution_traces.md

Run:  python src/capture_week5_traces.py
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(__file__))

import approval
import demo_support
import qa_tools
import tool_calling

ROOT_DIR = Path(__file__).resolve().parent.parent
TRACES_JSONL_PATH = ROOT_DIR / "evidence" / "traces" / "week5_live_traces.jsonl"
TRACES_MD_PATH = ROOT_DIR / "evidence" / "week5_live_execution_traces.md"
PROMPT = "Check REQ-2.1 (Tier Upgrades) against the code."

SCENARIOS = [
    {"id": "T1", "title": "Correct SUT", "planted_bug": False, "approve": True,
     "description": "REQ-2.1 against the unmodified SUT. Expected: tests pass and the agent stops "
                    "without drafting an issue (or reports a test defect if a generated test is wrong)."},
    {"id": "T2", "title": "Planted defect, human approves", "planted_bug": True, "approve": True,
     "description": "REQ-2.1 with 'balance <' changed to 'balance <=' in a temporary SUT copy. Expected: "
                    "boundary test fails -> draft_issue -> human approves -> file_issue succeeds."},
    {"id": "T3", "title": "Planted defect, human rejects (failure/recovery)", "planted_bug": True, "approve": False,
     "description": "Same as T2, but the human rejects file_issue. Expected: the agent stops with "
                    "human_rejection and nothing is filed."},
]


@contextlib.contextmanager
def _swap(module: Any, name: str, value: Any):
    saved = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, saved)


def _filed() -> set:
    folder = qa_tools.ISSUES_DIR / "filed"
    return {p.name for p in folder.glob("*.md")} if folder.exists() else set()


def run_scenario(scenario: Dict[str, Any], offline: bool) -> Dict[str, Any]:
    approvals: List[Dict[str, Any]] = []

    def hook(tool_name: str, arguments: Dict[str, Any]) -> bool:
        decision = scenario["approve"]
        approvals.append({
            "tool_name": tool_name,
            "arguments": arguments,
            "decision": "APPROVED" if decision else "REJECTED",
            "time_utc": datetime.now(timezone.utc).isoformat(),
        })
        print(f"  --> HUMAN GATE: {tool_name} -> {'APPROVED' if decision else 'REJECTED'}")
        return decision

    filed_before = _filed()
    started = datetime.now(timezone.utc).isoformat()
    with contextlib.ExitStack() as stack:
        approval.set_approval_hook(hook)
        stack.callback(approval.set_approval_hook, None)
        if offline:
            stack.enter_context(_swap(tool_calling, "llm_with_tools", demo_support.ScriptedLLM()))
            stack.enter_context(_swap(qa_tools, "get_model_response", demo_support.fixture_model_reply))
        if scenario["planted_bug"]:
            stack.enter_context(demo_support.planted_bug_sut())
        final_state, steps = demo_support.trace_run(
            tool_calling.graph, PROMPT, printer=lambda s: print("  " + s),
            initial_state=tool_calling.initial_state(PROMPT),
        )

    replies = [m for m in final_state["messages"]
               if type(m).__name__ == "AIMessage" and m.content and not m.tool_calls]
    answer = demo_support._text(replies[-1].content).strip() if replies else tool_calling.STOPPED_MESSAGE
    newly_filed = sorted(_filed() - filed_before)
    return {
        "scenario_id": scenario["id"],
        "title": scenario["title"],
        "description": scenario["description"],
        "mode": "offline_scripted_llm" if offline else "live_gemini",
        "model": "ScriptedLLM + demo/fixtures/req_2_1_tests.py" if offline else tool_calling.MODEL_NAME,
        "prompt_version": tool_calling.PROMPT_VERSION,
        "prompt": PROMPT,
        "planted_bug": scenario["planted_bug"],
        "max_hops": tool_calling.MAX_HOPS,
        "total_hops": final_state.get("hops", 0),
        "start_time_utc": started,
        "end_time_utc": datetime.now(timezone.utc).isoformat(),
        "tool_sequence": [s["tool"] for s in steps if s["action"] == "call_tool"],
        "human_approval_events": approvals,
        "issues_filed_during_run": newly_filed,
        "stop_reason": demo_support.stop_reason(final_state),
        "final_answer": answer,
        "steps": steps,
    }


def capture(scenario: Dict[str, Any]) -> Dict[str, Any]:
    print("\n" + "=" * 76)
    print(f"[{scenario['id']}] {scenario['title']}")
    print("=" * 76)
    try:
        return run_scenario(scenario, offline=False)
    except Exception as e:  # live model failed: record why, then fall back
        print(f"  Live run failed ({type(e).__name__}: {e}). Re-running with the scripted LLM.")
        record = run_scenario(scenario, offline=True)
        record["live_failure"] = f"{type(e).__name__}: {e}"
        record["live_failure_traceback"] = traceback.format_exc(limit=3)
        return record


def _cell(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")
    text = text.replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= 160 else text[:160] + "..."


def write_markdown(records: List[Dict[str, Any]]) -> None:
    lines = [
        "# Week 5 (realigned): Bounded QA Agent Execution Traces",
        "",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}  ",
        f"**Agent prompt:** `prompts/agent_system_prompt_{tool_calling.PROMPT_VERSION}.txt`  ",
        f"**Limits:** `MAX_HOPS = {tool_calling.MAX_HOPS}`, `MAX_CALLS_PER_STEP = {tool_calling.MAX_CALLS_PER_STEP}`  ",
        "**Script:** `src/capture_week5_traces.py` (structured records in `evidence/traces/week5_live_traces.jsonl`)",
        "",
        "Each trace shows, per hop, the graph node, the tool and its arguments, the tool's `status` / "
        "`test_outcome`, and the latency since the previous step. `mode` says whether the live Gemini "
        "model or the offline scripted LLM produced the decisions.",
        "",
        "| Trace | Mode | Tool sequence | Approval | Filed | Stop reason |",
        "|---|---|---|---|---|---|",
    ]
    for r in records:
        decisions = ", ".join(a["decision"] for a in r["human_approval_events"]) or "none"
        lines.append(
            f"| {r['scenario_id']} | `{r['mode']}` | {' -> '.join(r['tool_sequence'])} | {decisions} | "
            f"{len(r['issues_filed_during_run'])} | `{r['stop_reason']}` |"
        )
    lines += ["", "---"]

    for r in records:
        lines += [
            "",
            f"## {r['scenario_id']}: {r['title']}",
            "",
            f"**Scenario:** {r['description']}  ",
            f"**Mode:** `{r['mode']}` | **Model:** `{r['model']}` | **Planted bug:** `{r['planted_bug']}`  ",
            f"**Prompt:** \"{r['prompt']}\"  ",
            f"**Hops used:** {r['total_hops']}/{r['max_hops']} | **Stop reason:** `{r['stop_reason']}`  ",
        ]
        if r.get("live_failure"):
            lines.append(f"**Live run failed, fell back to offline:** `{_cell(r['live_failure'])}`  ")
        lines += [
            "",
            "| Hop | Node | Step | Tool | Args / result | Status | Test outcome | Latency (s) |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for s in r["steps"]:
            detail = s.get("args") if s["action"] == "call_tool" else s.get("text") if s["action"] == "final_answer" else s.get("result")
            if s["action"] == "tool_result" and isinstance(detail, dict):
                detail = {k: v for k, v in detail.items() if k not in ("status", "test_outcome")}
            lines.append(
                f"| {s['hop']} | `{s['node']}` | {s['action']} | {s.get('tool', '')} | {_cell(detail)} | "
                f"{s.get('status') or ''} | {s.get('test_outcome') or ''} | {s['latency_s']} |"
            )
        lines += ["", "**Human approval events:**", ""]
        if r["human_approval_events"]:
            for a in r["human_approval_events"]:
                lines.append(f"- `{a['tool_name']}` on `{Path(str(a['arguments'].get('draft_path', ''))).name}` -> **{a['decision']}**")
        else:
            lines.append("- none (no high-impact tool was requested)")
        lines += [
            "",
            f"**Issues filed during this run:** {', '.join(r['issues_filed_during_run']) or 'none'}",
            "",
            "**Final answer:**",
            "",
            "> " + r["final_answer"].replace("\n", "\n> "),
            "",
            "---",
        ]
    TRACES_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    print(f"Model: {tool_calling.MODEL_NAME} | prompt {tool_calling.PROMPT_VERSION} | MAX_HOPS {tool_calling.MAX_HOPS}")
    records = [capture(s) for s in SCENARIOS]
    TRACES_JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TRACES_JSONL_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    write_markdown(records)
    print(f"\n[OK] {len(records)} traces -> {TRACES_JSONL_PATH} and {TRACES_MD_PATH}")
    for r in records:
        print(f"  {r['scenario_id']}: mode={r['mode']} stop={r['stop_reason']} "
              f"tools={' -> '.join(r['tool_sequence'])} filed={len(r['issues_filed_during_run'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
