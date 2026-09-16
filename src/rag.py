"""
Simple Context Engineering & RAG Pipeline for the Software-Engineering QA Agent.
  1. Ingestion: Reads markdown requirements from docs/requirements/
  2. Chunking: Splits requirements into section- and criterion-level chunks
  3. Indexing: Pure Python BM25 indexer (no external vector DB or heavy libraries needed)
  4. Retrieval: Scores and returns top-k relevant chunks with source citations

"""

import os
import re
import math
from dataclasses import dataclass
from collections import Counter
from pathlib import Path
from typing import List, Dict, Optional


# =====================================================================
# 1. Data Models
# =====================================================================

@dataclass
class Document:
    """Represents a raw document file read from disk."""
    file_path: str
    filename: str
    content: str


@dataclass
class Chunk:
    """Represents an atomic, traceable segment of a requirement document."""
    chunk_id: str
    source_file: str
    section: str
    text: str

    def to_citation(self) -> str:
        """Format the chunk with explicit provenance for prompt grounding."""
        return f"Source: {self.source_file}, {self.section}\n{self.text}"


# =====================================================================
# 2. Ingestion
# =====================================================================

def ingest_directory(directory_path: str) -> List[Document]:
    """
    Step 1: INGESTION
    Scans a directory for .md and .txt requirement files and loads their text.

    Args:
        directory_path: Path to the folder containing requirement documents.

    Returns:
        A list of Document objects.
    """
    dir_path = Path(directory_path).resolve()
    if not dir_path.exists() or not dir_path.is_dir():
        raise FileNotFoundError(f"Corpus directory not found: {directory_path}")

    # Use relative path for cleaner citation displays if inside current working directory
    cwd = Path.cwd().resolve()

    documents = []
    # Search for markdown and text requirement files
    for file_path in sorted(dir_path.iterdir()):
        if file_path.is_file() and file_path.suffix in [".md", ".txt"]:
            # Skip hidden files or gitkeep
            if file_path.name.startswith("."):
                continue
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                try:
                    rel_path = file_path.relative_to(cwd)
                    display_path = str(rel_path).replace("\\", "/")
                except ValueError:
                    display_path = str(file_path).replace("\\", "/")

                documents.append(
                    Document(
                        file_path=display_path,
                        filename=file_path.name,
                        content=content,
                    )
                )
    return documents


# =====================================================================
# 3. Chunking / Segmentation
# =====================================================================

def chunk_document(doc: Document) -> List[Chunk]:
    """
    Step 2: CHUNKING / SEGMENTATION
    Splits a requirement document into logical, traceable chunks.

    Extracts:
      - Document Title (from # Header)
      - Section Headers (from ## Header)
      - Feature Name (from Feature: ...)
      - Individual Acceptance Criteria (e.g., "1. The system must...")
      - Explanatory Notes (e.g., "Note: ...")

    Each criterion chunk preserves its parent Section and Feature name
    so every retrieved excerpt carries unambiguous context and provenance.
    """
    chunks: List[Chunk] = []
    lines = doc.content.splitlines()

    current_section = doc.filename
    current_feature = ""
    chunk_index = 1

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Document title (# ...)
        if stripped.startswith("# ") and not stripped.startswith("## "):
            # Track as default section if none set
            current_section = stripped.lstrip("#").strip()
            i += 1
            continue

        # Section header (## ...)
        if stripped.startswith("## "):
            current_section = stripped.lstrip("#").strip()
            current_feature = ""
            i += 1
            continue

        # Feature label (Feature: ...)
        if stripped.startswith("Feature:"):
            current_feature = stripped
            i += 1
            continue

        # Skip bare label lines like "Acceptance Criteria:"
        if stripped.lower() in ["acceptance criteria:", "acceptance criteria"]:
            i += 1
            continue

        # Acceptance Criterion (e.g. "1. The system must...")
        match = re.match(r"^(\d+)\.\s+(.*)", stripped)
        if match:
            crit_num = match.group(1)
            criterion_lines = [stripped]
            # Capture any indented or continuation lines belonging to this criterion
            j = i + 1
            while j < len(lines):
                next_stripped = lines[j].strip()
                if (
                    not next_stripped
                    or next_stripped.startswith("#")
                    or next_stripped.startswith("Feature:")
                    or next_stripped.lower().startswith("acceptance criteria")
                    or next_stripped.startswith("Note:")
                    or re.match(r"^\d+\.\s+", next_stripped)
                ):
                    break
                criterion_lines.append(next_stripped)
                j += 1
            i = j

            criterion_text = " ".join(criterion_lines)
            full_text = (
                f"[{current_feature}] {criterion_text}"
                if current_feature
                else criterion_text
            )
            chunks.append(
                Chunk(
                    chunk_id=f"{doc.filename}#sec{current_section[:10]}#ac-{crit_num}",
                    source_file=doc.file_path,
                    section=current_section,
                    text=full_text,
                )
            )
            chunk_index += 1
            continue

        # Notes or boundary warnings (e.g. "Note: This document does not specify...")
        if stripped.startswith("Note:"):
            note_lines = [stripped]
            j = i + 1
            while j < len(lines):
                next_stripped = lines[j].strip()
                if next_stripped.startswith("#") or re.match(r"^\d+\.\s+", next_stripped):
                    break
                if next_stripped:
                    note_lines.append(next_stripped)
                j += 1
            i = j
            note_text = " ".join(note_lines)
            chunks.append(
                Chunk(
                    chunk_id=f"{doc.filename}#sec{current_section[:10]}#note",
                    source_file=doc.file_path,
                    section=current_section,
                    text=note_text,
                )
            )
            chunk_index += 1
            continue

        # Any other substantive standalone paragraph
        if len(stripped) > 20:
            chunks.append(
                Chunk(
                    chunk_id=f"{doc.filename}#chunk-{chunk_index}",
                    source_file=doc.file_path,
                    section=current_section,
                    text=stripped,
                )
            )
            chunk_index += 1
        i += 1

    return chunks


def chunk_corpus(documents: List[Document]) -> List[Chunk]:
    """Applies chunking to a list of ingested documents."""
    all_chunks: List[Chunk] = []
    for doc in documents:
        all_chunks.extend(chunk_document(doc))
    return all_chunks


# =====================================================================
# 4. Tokenization & BM25 Indexing
# =====================================================================

def tokenize(text: str) -> List[str]:
    """
    Tokenizes text into lowercase words/code identifiers.
    Also splits camelCase and snake_case so technical terms like
    'InactiveUserError' can match 'inactive', 'user', and 'error'.
    """
    # Insert spaces before capital letters in CamelCase words (e.g., InactiveUser -> Inactive User)
    spaced_camel = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    # Replace underscores with spaces
    spaced_snake = spaced_camel.replace("_", " ")
    # Extract lowercase alphanumeric words
    tokens = re.findall(r"\b[a-zA-Z0-9]+\b", spaced_snake.lower())
    return tokens


class BM25Index:
    """
    Step 3: INDEXING
    Pure-Python Okapi BM25 Index.
    
    Why BM25 for software engineering QA?
    - Deterministic, fast, and requires zero external C-libraries or API calls.
    - Accurately matches technical terms, error classes, status codes, and paths.
    - Transparent scoring formula that is easy to explain and inspect.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.chunks: List[Chunk] = []
        self.doc_lengths: List[int] = []
        self.avg_doc_length: float = 0.0
        self.doc_term_freqs: List[Counter] = []
        self.doc_freqs: Dict[str, int] = Counter()
        self.idf: Dict[str, float] = {}
        self.total_docs: int = 0

    def build(self, chunks: List[Chunk]) -> None:
        """Builds the BM25 index from a list of chunks."""
        self.chunks = chunks
        self.total_docs = len(chunks)
        self.doc_lengths = []
        self.doc_term_freqs = []
        self.doc_freqs = Counter()

        if self.total_docs == 0:
            self.avg_doc_length = 0.0
            return

        for chunk in chunks:
            # Combine section name and text for indexing so section keywords match
            full_text = f"{chunk.section} {chunk.text}"
            tokens = tokenize(full_text)
            self.doc_lengths.append(len(tokens))

            term_counts = Counter(tokens)
            self.doc_term_freqs.append(term_counts)

            # Record document frequency for each unique term
            for term in term_counts.keys():
                self.doc_freqs[term] += 1

        self.avg_doc_length = sum(self.doc_lengths) / self.total_docs

        # Calculate Inverse Document Frequency (IDF) for all terms
        self.idf = {}
        for term, df in self.doc_freqs.items():
            # Standard Okapi BM25 IDF with smoothing (+1 to ensure non-negative values)
            self.idf[term] = math.log((self.total_docs - df + 0.5) / (df + 0.5) + 1.0)


# =====================================================================
# 5. Retrieval & Context Assembly
# =====================================================================

class SimpleRetriever:
    """
    Step 4: RETRIEVAL
    Queries the BM25 index to find the most relevant chunks, with
    minimum score thresholding to reject unanswerable queries.
    """

    def __init__(self, index: BM25Index):
        self.index = index

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 1.0,
    ) -> List[Dict]:
        """
        Retrieves top-k relevant chunks for a given query string.

        Args:
            query: The search query or test module description.
            top_k: Maximum number of chunks to return.
            min_score: Minimum BM25 score required for a chunk to be returned.
                       Scores below this indicate weak or unrelated matches.

        Returns:
            A list of dicts with:
                - chunk: the Chunk object
                - score: the BM25 relevance score
        """
        query_tokens = tokenize(query)
        if not query_tokens or self.index.total_docs == 0:
            return []

        scores = []
        for i, chunk in enumerate(self.index.chunks):
            doc_len = self.index.doc_lengths[i]
            tf_map = self.index.doc_term_freqs[i]
            score = 0.0

            for term in query_tokens:
                if term not in tf_map:
                    continue
                tf = tf_map[term]
                idf = self.index.idf.get(term, 0.0)

                # Okapi BM25 scoring formula
                numerator = tf * (self.index.k1 + 1)
                denominator = tf + self.index.k1 * (
                    1 - self.index.b + self.index.b * (doc_len / self.index.avg_doc_length)
                )
                score += idf * (numerator / denominator)

            if score >= min_score:
                scores.append({"chunk": chunk, "score": round(score, 3)})

        # Sort descending by score
        scores.sort(key=lambda x: x["score"], reverse=True)
        return scores[:top_k]

    def format_context_for_prompt(self, results: List[Dict]) -> str:
        """
        Formats retrieved chunks into a clean, cited string suitable for
        the {{requirements_excerpt}} slot in our prompt templates.
        """
        if not results:
            return "NO_RELEVANT_REQUIREMENTS_FOUND"

        excerpts = []
        for item in results:
            chunk: Chunk = item["chunk"]
            excerpts.append(chunk.to_citation())

        return "\n\n---\n\n".join(excerpts)


# =====================================================================
# 6. High-Level Helper & CLI
# =====================================================================

def build_rag_pipeline(corpus_dir: str = "docs/requirements") -> SimpleRetriever:
    """Convenience factory: Ingests, chunks, indexes, and returns a retriever."""
    docs = ingest_directory(corpus_dir)
    chunks = chunk_corpus(docs)
    index = BM25Index()
    index.build(chunks)
    return SimpleRetriever(index)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Software-Engineering QA Agent RAG Pipeline")
    parser.add_argument(
        "--corpus",
        default="docs/requirements",
        help="Path to the directory containing requirements files.",
    )
    parser.add_argument(
        "--query",
        type=str,
        default="refund eligibility window and balance revert",
        help="Test query to search across the requirements corpus.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="Number of top chunks to retrieve.",
    )
    args = parser.parse_args()

    print(f"[RAG] Ingesting corpus from: {args.corpus}")
    retriever = build_rag_pipeline(args.corpus)
    total_chunks = len(retriever.index.chunks)
    print(f"[RAG] Ingested and indexed {total_chunks} chunks.")
    print(f"[RAG] Query: \"{args.query}\"")
    print("=" * 60)

    results = retriever.retrieve(args.query, top_k=args.top_k)
    if not results:
        print("No matching requirements found (score below threshold).")
    else:
        for idx, res in enumerate(results, 1):
            chunk = res["chunk"]
            score = res["score"]
            print(f"Result {idx} (BM25 Score: {score}):")
            print(f"  ID:      {chunk.chunk_id}")
            print(f"  Source:  {chunk.source_file}")
            print(f"  Section: {chunk.section}")
            print(f"  Text:    {chunk.text}")
            print("-" * 60)

    print("\n[RAG] Formatted Prompt Context Output:")
    print("=" * 60)
    print(retriever.format_context_for_prompt(results))
