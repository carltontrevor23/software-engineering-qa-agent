"""
demo/run_demo.py

Live demonstration of the Inspectra QA agent on one requirement.

    python demo/run_demo.py                          # REQ-2.1, correct SUT, live Gemini
    python demo/run_demo.py --planted-bug            # same, with a planted boundary defect
    python demo/run_demo.py --planted-bug --offline  # no Gemini: scripted LLM + fixture tests

--planted-bug  copies sut/ to a temp folder and changes
               "if balance < self.UPGRADE_COST:" to "if balance <= self.UPGRADE_COST:"
               in the copy only. The real sut/ is never modified.
--offline      replaces Gemini with a scripted LLM and demo/fixtures/req_2_1_tests.py.
               Every output line is labelled [SCRIPTED LLM]. Use it if the model quota or
               network fails during the presentation.

High-impact steps (file_issue) stop at the interactive approval prompt: type y or n.
"""

import argparse
import contextlib
import os
import sys

SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
sys.path.insert(0, os.path.abspath(SRC_DIR))

import demo_support
import qa_tools
import tool_calling


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

    with contextlib.ExitStack() as stack:
        if args.offline:
            sys.stdout = _LabelledStdout(sys.__stdout__, demo_support.SCRIPTED_LABEL)
            stack.callback(setattr, sys, "stdout", sys.__stdout__)
            stack.enter_context(_swap(tool_calling, "llm_with_tools", demo_support.ScriptedLLM()))
            stack.enter_context(_swap(qa_tools, "get_model_response", demo_support.fixture_model_reply))
            print("OFFLINE MODE: Gemini is NOT being called; a scripted LLM and fixture tests are used.")
        else:
            print(f"LIVE MODE: model {tool_calling.MODEL_NAME}, prompt {tool_calling.PROMPT_VERSION}")

        if args.planted_bug:
            copy = stack.enter_context(demo_support.planted_bug_sut())
            print("!" * 70)
            print("PLANTED DEFECT ACTIVE (temporary copy only, real sut/ untouched):")
            print(f"  {demo_support.PLANTED_BUG_FROM}  ->  {demo_support.PLANTED_BUG_TO}")
            print(f"  copy: {copy}")
            print("!" * 70)

        prompt = build_prompt(args.requirement)
        print(f"\nRequest: {prompt}")
        print(f"Limits: MAX_HOPS={tool_calling.MAX_HOPS}, MAX_CALLS_PER_STEP={tool_calling.MAX_CALLS_PER_STEP}\n")

        final_state, _ = demo_support.trace_run(
            tool_calling.graph, prompt, initial_state=tool_calling.initial_state(prompt)
        )

        replies = [m for m in final_state["messages"]
                   if type(m).__name__ == "AIMessage" and m.content and not m.tool_calls]
        answer = demo_support._text(replies[-1].content) if replies else tool_calling.STOPPED_MESSAGE
        print("\nFinal answer:")
        # The line label already marks offline output; don't print it twice.
        print(answer.strip().removeprefix(demo_support.SCRIPTED_LABEL).strip())
        print(f"\nStop reason: {demo_support.stop_reason(final_state)} (final phase {final_state.get('phase')})")
    return 0


@contextlib.contextmanager
def _swap(module, name, value):
    saved = getattr(module, name)
    setattr(module, name, value)
    try:
        yield value
    finally:
        setattr(module, name, saved)


if __name__ == "__main__":
    sys.exit(main())
