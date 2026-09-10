# software-engineering-qa-agent

An AI-native Software-Engineering QA Agent for the BSE4104 capstone project.
It reads a team's own requirements/repository documentation, proposes unit
and integration tests, and (in later weeks) will execute approved tests in
a sandbox and draft issue/PR notes for human review.

This is a Week 2 baseline: foundation model integration + prompt
specification + evaluation. No RAG, tools, or agent loop yet.

## Setup

1. **Clone the repo and enter it**
   ```
   cd software-engineering-qa-agent
   ```

2. **Create and activate a virtual environment**
   ```
   python -m venv venv
   venv\Scripts\activate        # Windows
   source venv/bin/activate     # macOS / Linux
   ```

3. **Install dependencies**
   ```
   pip install -r requirements.txt
   ```

4. **Add your Gemini API key**

   Copy `.env.example` to `.env` and fill in your own key:
   ```
   cp .env.example .env
   ```
   Then edit `.env`:
   ```
   GEMINI_API_KEY=your_key_here
   ```
   Get a free key at https://aistudio.google.com (click the key icon in
   the sidebar → Create API key). **Never commit `.env`** — it's already
   in `.gitignore`.

## Running it

### Quick connection + baseline test

Runs a simple "say hello" check, then one real test-proposal prompt using
`prompts/v1.0_test_proposal.txt`:

```
python src/model_client.py
```

### Run the full 10-case evaluation

Runs every case in `docs/evaluation/evaluation_cases.json` through the
model using the v1.0 prompt, and saves expected vs. actual results:

```
python src/model_client.py --run-evaluation
```

Results are written to `evidence/traces/evaluation_results.json`. Every
individual API call (success or failure) is also logged to
`evidence/traces/trace_<date>.jsonl` for traceability.

### Running against a different prompt version

Once a new prompt spec (e.g. `v1.1_test_proposal.txt`) exists in `prompts/`:

```
python src/model_client.py --run-evaluation --template prompts/v1.1_test_proposal.txt --prompt-version v1.1 --output evidence/traces/evaluation_results_v1.1.json
```

## Project structure

```
docs/
  architecture/       # architecture diagrams
  evaluation/          # evaluation_cases.json + evaluation write-ups
  requirements/        # requirements/documentation the agent reads
  weekly-reports/       # weekly progress reports
evidence/
  demo/                # demo recordings/screens
  screenshots/
  traces/               # logged model calls + evaluation results
knowledge/              # corpus metadata/provenance (no restricted data)
prompts/                 # versioned Prompt Specification files
src/
  model_client.py        # model integration: connects to Gemini, runs prompts, logs calls
tests/
```

## Model

Gemini 3.6 Flash, via Google's Interactions API (`client.interactions.create`).
See `docs/` for the full Model Selection Note.

## Notes for the team

- `src/model_client.py` is the shared integration layer — import
  `get_model_response()` and `build_test_proposal_prompt()` rather than
  duplicating API calls elsewhere.
- Prompt specs live in `prompts/`, one file per version (`v1.0_*.txt`,
  `v1.1_*.txt`, ...). Never edit an old version in place — version history
  needs to show what changed and why.
- Evaluation cases live in `docs/evaluation/evaluation_cases.json`.
