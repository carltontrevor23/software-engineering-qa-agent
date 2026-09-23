Project: Software-Engineering QA Agent (RAG Pipeline)
Evaluation Target: 15-Case RAG Suite (docs/evaluation/rag_evaluation_questions.json)

Retriever Architecture: BM25 lexical search over segmented Markdown chunks (src/rag.py)

Failure 1: Cross-Document Term Imbalance
Related Test Case: Case 10 & Case 11 (Partially Answerable)Question: "If a user downgrades from PREMIUM to STANDARD, are they notified, and does the downgrade affect the refund eligibility window on their original upgrade?"
Observed Behaviour:Retrieval Phase: BM25 surfaced chunks exclusively from notifications.md  because keywords like "downgrade", "STANDARD", and "notification" dominated term frequencies. Zero chunks from refund.md were returned because top_k=3 was exhausted by the notification chunks, and refund.md did not contain the word "downgrade".
Generation Phase: The model correctly stated that notifications are sent, but had no retrieved context to address the second half of the query (refund interaction).
Root Cause:Term frequency skew in lexical retrieval. BM25 scores single queries holistically against isolated chunks. For compound/multi-hop questions touching two distinct domains (Notifications vs. Refunds), chunks containing words for only one topic outscore chunks containing words for the other topic, causing total retrieval starvation for the second domain.

Failure 2: Vocabulary Mismatch / Synonym Dropout
Related Test Case: Case 1 (Answerable Variant / Semantic Edge Test)
Question: "What happens to the account ledger when a subscriber chooses to terminate agreement?"
Target Grounding: docs/requirements/cancellation.md, Section 2.2
Observed Behaviour: Retrieval Phase: The retriever returned NO_RELEVANT_REQUIREMENTS_FOUND because the BM25 score dropped below min_score=1.0.
Generation Phase: Following prompt constraint 5, the model safely emitted: NO_GROUNDED_ANSWER_FOUND: no relevant requirements were retrieved for this question.

Root Cause: Lexical vs. semantic divergence. The corpus consistently uses the domain tokens "cancel", "cancellation", and "FREE". The user query used legal synonyms ("terminate agreement", "subscriber"). Because BM25 relies on exact character token matching, zero term overlap occurred despite high semantic equivalence.

Failure 3: Semantic Granularity & Scope Drift on Undefined Behavior
Related Test Case: Case 7 & Case 8 (Partially Answerable / Explicit Note Chunks)
Question: "What happens automatically when a user's 14-day trial period ends?"

Observed Behaviour:
Retrieval Phase: Successfully retrieved docs/requirements/trial_period.md, Section 2.5, Note chunk (which states that auto-downgrade vs. auto-billing is undefined and out of scope).

Generation Phase: In early baseline prompts without strict negative constraints, the LLM attempted to infer common SaaS industry behavior ("the user is typically downgraded to the Free tier"), introducing unverified assumptions. Under hardened prompt v1.0, it correctly output that the behavior is unrecorded.

Root Cause: Parametric prior bias over partial chunks. When a document chunk discusses a topic but explicitly defines it as unimplemented or open, pre-trained LLMs experience high attention bias toward completing the business logic rather than respecting the negative constraint.