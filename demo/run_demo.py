"""
demo/run_demo.py

Live demonstration of the Inspectra QA agent on one requirement.

    python demo/run_demo.py                          # REQ-2.1, correct SUT, live model
    python demo/run_demo.py --planted-bug            # same, with a planted boundary defect
    python demo/run_demo.py --planted-bug --offline  # no network: scripted model + fixture tests

--planted-bug  copies sut/ to a temp folder and changes
               "if balance < self.UPGRADE_COST:" to "if balance <= self.UPGRADE_COST:"
               in the copy only. The real sut/ is never modified.
--offline      replaces the live model with a scripted model and demo/fixtures/req_2_1_tests.py.
               Every output line is labelled [SCRIPTED LLM]. Use it if the model quota or
               network fails during the presentation.

High-impact steps (file_issue) pause for approval: type y or n at the prompt. (In LangGraph
Studio the same pause is an approve/reject card; run the `inspectra_offline` graph there.)
"""

import argparse
import contextlib
import os
import sys

SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
sys.path.insert(0, os.path.abspath(SRC_DIR))

import agent
import demo_support
import guard_middleware
import models
import offline
import qa_tools


class _LabelledStdout:
    """Prefix every output line, so offline output cannot be mistaken for live model behaviour."""

    def __init__(self, stream, label):
        self._stream = stream
        self._label = label
        self._at_line_start = True

    def write(self, text):
        for piece in text.splitlines(keepends=True):
            if self._at_line_start and piece.strip():
                self._stream.write(f"{self._label} ")
            self._stream.write(piece)
            self._at_line_start = piece.endswith("\n")
        return len(text)

    def flush(self):
        self._stream.flush()


def build_prompt(requirement_id: str) -> str:
    req = qa_tools.load_requirement(requirement_id)
    title = f" ({req['title']})" if req["status"] == "success" else ""
    return f"Check {requirement_id}{title} against the code."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--requirement", default="REQ-2.1")
    parser.add_argument("--planted-bug", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()

    from langgraph.checkpoint.memory import InMemorySaver

    with contextlib.ExitStack() as stack:
        if args.offline:
            sys.stdout = _LabelledStdout(sys.__stdout__, demo_support.SCRIPTED_LABEL)
            stack.callback(setattr, sys, "stdout", sys.__stdout__)
            graph = offline.build_offline_agent(planted_bug=args.planted_bug, checkpointer=InMemorySaver())
            print("OFFLINE MODE: no live model is called; a scripted model and fixture tests are used.")
        else:
            graph = agent.build_agent(checkpointer=InMemorySaver())
            print(f"LIVE MODE: model {models.model_label()}, prompt {agent.PROMPT_VERSION}")

        if args.planted_bug:
            if not args.offline:
                copy = stack.enter_context(demo_support.planted_bug_sut())
            print("!" * 70)
            print("PLANTED DEFECT ACTIVE (temporary copy only, real sut/ untouched):")
            print(f"  {demo_support.PLANTED_BUG_FROM}  ->  {demo_support.PLANTED_BUG_TO}")
            if not args.offline:
                print(f"  copy: {copy}")
            print("!" * 70)

        prompt = build_prompt(args.requirement)
        print(f"
Request: {prompt}")
        print(f"Limits: MAX_HOPS={guard_middleware.MAX_HOPS}, "
              f"MAX_CALLS_PER_STEP={guard_middleware.MAX_CALLS_PER_STEP}
")

        final_state, _ = demo_support.trace_run(graph, prompt, decide=agent.terminal_decision)

        print("
Final answer:")
        # The line label already marks offline output; don't print it twice.
        print(agent.final_text(final_state).strip().removeprefix(demo_support.SCRIPTED_LABEL).strip())
        print(f"
Stop reason: {demo_support.stop_reason(final_state)} (final phase {final_state.get('phase')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
