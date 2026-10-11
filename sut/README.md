# System Under Test (SUT)

System under test. The QA agent tests this code; it never operates it.

- `subscription_service/subscription_manager.py`: the subscription tier service
  specified in `docs/requirements/*.md` (Sections 2.1 to 2.6).
- `tests/`: the human-written baseline suite, plus any agent-generated test that a
  human approved through `save_test_to_suite`.

The agent only reads this folder and runs its tests in the sandbox
(`src/sandbox.py`). It never edits `subscription_service/`, and it never calls the
service to change a real account.

Run the baseline suite:

```
venv\Scripts\python -m pytest sut/tests/ -v
```
