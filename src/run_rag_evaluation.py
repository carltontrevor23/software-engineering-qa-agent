"""
src/run_rag_evaluation.py

Batch runner for the Week 3 RAG evaluation set.

For each of the 15 questions in docs/evaluation/rag_evaluation_questions.json,
this script:
  1. Retrieves the top matching chunks from the requirements corpus
     using the BM25 pipeline in src/rag.py.
  2. Builds a grounded answer prompt from prompts/rag_answer_prompt_v1.0.txt,
     filling in the question and the retrieved context.
  3. Sends that prompt to the model via get_model_response() in
     src/model_client.py.
  4. Records expected vs actual behaviour, plus retrieval details
     (which chunks were retrieved and their BM25 scores), so retrieval
     failures can be told apart from generation failures.

Usage:
    python src/run_rag_evaluation.py
    python src/run_rag_evaluation.py --top-k 3 --min-score 1.0
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag import build_rag_pipeline
from src.model_client import get_model_response, ModelCallError


def load_questions(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_prompt_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_answer_prompt(template: str, question: str, context: str) -> str:
    prompt = template.replace("{{question}}", question)
    prompt = prompt.replace("{{context}}", context)
    return prompt


def run_rag_evaluation(
    questions_path: str,
    corpus_dir: str,
    template_path: str,
    output_path: str,
    top_k: int = 3,
    min_score: float = 1.0,
    prompt_version: str = "rag_v1.0",
) -> list[dict]:
    questions = load_questions(questions_path)
    template = load_prompt_template(template_path)

    print(f"[rag_eval] Building RAG pipeline from: {corpus_dir}")
    retriever = build_rag_pipeline(corpus_dir)
    print(f"[rag_eval] Indexed {len(retriever.index.chunks)} chunks.")

    results = []

    for q in questions:
        q_id = q.get("id")
        question_text = q.get("question", "")
        print(f"[rag_eval] Running question {q_id}: {question_text[:60]}...")

        # --- Retrieval ---
        retrieved = retriever.retrieve(question_text, top_k=top_k, min_score=min_score)
        context = retriever.format_context_for_prompt(retrieved)

        retrieved_summary = [
            {
                "chunk_id": item["chunk"].chunk_id,
                "source_file": item["chunk"].source_file,
                "section": item["chunk"].section,
                "score": item["score"],
            }
            for item in retrieved
        ]

        # --- Generation ---
        prompt = build_answer_prompt(template, question_text, context)

        result = {
            "id": q_id,
            "category": q.get("category"),
            "question": question_text,
            "expected_answer_summary": q.get("expected_answer_summary"),
            "retrieved_chunks": retrieved_summary,
            "retrieval_hit": len(retrieved) > 0,
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
            print(f"[rag_eval] Question {q_id} failed: {e}", file=sys.stderr)

        results.append(result)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n[rag_eval] Done. {len(results)} questions run.")
    print(f"[rag_eval] Results saved to: {output_path}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG evaluation batch runner")
    parser.add_argument(
        "--questions",
        default=str(PROJECT_ROOT / "docs" / "evaluation" / "rag_evaluation_questions.json"),
        help="Path to the RAG evaluation questions JSON file.",
    )
    parser.add_argument(
        "--corpus",
        default=str(PROJECT_ROOT / "docs" / "requirements"),
        help="Path to the requirements corpus directory.",
    )
    parser.add_argument(
        "--template",
        default=str(PROJECT_ROOT / "prompts" / "rag_answer_prompt_v1.0.txt"),
        help="Path to the RAG answer prompt template.",
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "evidence" / "traces" / "rag_evaluation_results.json"),
        help="Where to save the RAG evaluation results JSON.",
    )
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--min-score", type=float, default=1.0)
    args = parser.parse_args()

    run_rag_evaluation(
        questions_path=args.questions,
        corpus_dir=args.corpus,
        template_path=args.template,
        output_path=args.output,
        top_k=args.top_k,
        min_score=args.min_score,
    )