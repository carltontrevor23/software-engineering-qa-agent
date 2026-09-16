"""
tests/test_rag.py

Unit tests for the Week 3 RAG Pipeline (Ingestion, Chunking, Indexing, Retrieval).
Uses Python's built-in unittest framework (no external dependencies needed).

Run using:
    python tests/test_rag.py
    or
    python -m unittest tests/test_rag.py
"""

import unittest
import os
from pathlib import Path

# Add project root to sys.path
import sys
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag import (
    Document,
    Chunk,
    ingest_directory,
    chunk_document,
    chunk_corpus,
    tokenize,
    BM25Index,
    SimpleRetriever,
    build_rag_pipeline,
)


class TestRAGPipeline(unittest.TestCase):

    def setUp(self):
        self.requirements_dir = str(PROJECT_ROOT / "docs" / "requirements")

    def test_01_ingestion(self):
        """Test Step 1: Ingestion reads documents from the requirements directory."""
        docs = ingest_directory(self.requirements_dir)
        self.assertGreater(len(docs), 0, "Ingestion should load at least one document.")
        
        filenames = [d.filename for d in docs]
        self.assertIn("subscription.md", filenames)
        self.assertIn("refund.md", filenames)
        self.assertIn("downgrade.md", filenames)
        
        # Verify non-empty content
        for doc in docs:
            self.assertTrue(len(doc.content) > 0, f"Document {doc.filename} is empty.")

    def test_02_ingestion_invalid_path(self):
        """Test that ingestion raises FileNotFoundError for non-existent directories."""
        with self.assertRaises(FileNotFoundError):
            ingest_directory("non_existent_directory_xyz")

    def test_03_chunking(self):
        """Test Step 2: Chunking creates discrete, traceable chunks with section context."""
        sample_doc = Document(
            file_path="docs/requirements/test_spec.md",
            filename="test_spec.md",
            content=(
                "# Sample Requirements\n\n"
                "## Section 1: Authentication\n"
                "Feature: User Login\n\n"
                "Acceptance Criteria:\n"
                "1. User enters valid username and password.\n"
                "2. System locks account after 5 failed attempts.\n\n"
                "Note: MFA is not yet supported.\n"
            ),
        )
        chunks = chunk_document(sample_doc)
        
        # We expect 2 criteria chunks + 1 note chunk = 3 chunks
        self.assertEqual(len(chunks), 3)
        self.assertIn("ac-1", chunks[0].chunk_id)
        self.assertIn("valid username and password", chunks[0].text)
        self.assertEqual(chunks[0].section, "Section 1: Authentication")
        
        self.assertIn("ac-2", chunks[1].chunk_id)
        self.assertIn("locks account after 5 failed attempts", chunks[1].text)
        
        self.assertIn("note", chunks[2].chunk_id)
        self.assertIn("MFA is not yet supported", chunks[2].text)

    def test_04_tokenization(self):
        """Test tokenizer splits words, code symbols, and handles CamelCase."""
        text = "InactiveUserError at /users/{user_id} with 50.00 balance"
        tokens = tokenize(text)
        
        # CamelCase InactiveUserError should split into inactive, user, error
        self.assertIn("inactive", tokens)
        self.assertIn("user", tokens)
        self.assertIn("error", tokens)
        self.assertIn("users", tokens)
        self.assertIn("50", tokens)

    def test_05_bm25_indexing(self):
        """Test Step 3: Indexing builds term frequencies, document lengths, and IDFs."""
        chunks = [
            Chunk(chunk_id="c1", source_file="doc1.md", section="Sec 1", text="Process upgrade tier to PREMIUM"),
            Chunk(chunk_id="c2", source_file="doc2.md", section="Sec 2", text="Downgrade from PREMIUM to STANDARD"),
            Chunk(chunk_id="c3", source_file="doc3.md", section="Sec 3", text="Refund upgrade within 7 days"),
        ]
        index = BM25Index()
        index.build(chunks)
        
        self.assertEqual(index.total_docs, 3)
        self.assertGreater(index.avg_doc_length, 0)
        # Term appearing in fewer docs should have higher IDF
        self.assertGreater(index.idf.get("refund", 0), index.idf.get("premium", 0))

    def test_06_retrieval_answerable(self):
        """Test Step 4: Retrieval returns the correct chunk for an answerable query."""
        retriever = build_rag_pipeline(self.requirements_dir)
        results = retriever.retrieve("refund within 7 days", top_k=3, min_score=1.0)
        
        self.assertGreater(len(results), 0, "Should retrieve at least one chunk for refund query.")
        top_chunk = results[0]["chunk"]
        self.assertIn("refund", top_chunk.source_file.lower())
        self.assertIn("7 days", top_chunk.text)

    def test_07_retrieval_unanswerable(self):
        """Test Step 4: Retrieval returns empty for completely ungrounded/unanswerable query."""
        retriever = build_rag_pipeline(self.requirements_dir)
        results = retriever.retrieve("quantum blockchain cryptocurrency mining", min_score=1.0)
        
        self.assertEqual(len(results), 0, "Unanswerable query should return 0 chunks above threshold.")

    def test_08_prompt_context_formatting(self):
        """Test that context formatting outputs clean provenance citations for the prompt."""
        retriever = build_rag_pipeline(self.requirements_dir)
        results = retriever.retrieve("downgrade premium to standard", top_k=2)
        
        formatted = retriever.format_context_for_prompt(results)
        self.assertIn("Source: docs/requirements/downgrade.md", formatted)
        self.assertIn("Section 2.3: Subscription Tier Downgrade", formatted)


if __name__ == "__main__":
    unittest.main(verbosity=2)
