"""
tests/test_project_config.py

The requirements folder and the code folder are settings, not fixed paths: a second, unrelated
project works end to end (requirements parsed, code shown to the test writer, generated tests
validated and run against it), and bad settings fail with a clear message.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import project_config
import qa_tools
import sandbox

REQUIREMENTS = """# Library

## Section 1.1: Late Fees
Acceptance Criteria:
1. A book returned after the due day costs 2 per late day.
"""

CODE = '''
class LateFeeError(Exception):
    pass


def late_fee(days_late):
    if days_late < 0:
        raise LateFeeError("negative")
    return days_late * 2


def _private():
    return 1
'''

GENERATED = '''
import pytest
from library.fees import late_fee, LateFeeError


def test_fee_is_two_per_day():
    assert late_fee(3) == 6


def test_negative_days_raise():
    with pytest.raises(LateFeeError):
        late_fee(-1)
'''


@pytest.fixture
def other_project(tmp_path, monkeypatch):
    """A project that is not the bundled subscription sample, selected through the settings."""
    reqs = tmp_path / "reqs"
    reqs.mkdir()
    (reqs / "library.md").write_text(REQUIREMENTS, encoding="utf-8")
    code = tmp_path / "code"
    (code / "library").mkdir(parents=True)
    (code / "library" / "__init__.py").write_text("", encoding="utf-8")
    (code / "library" / "fees.py").write_text(CODE, encoding="utf-8")
    (code / "tests").mkdir()
    (code / "tests" / "test_old.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    generated = tmp_path / "generated"
    generated.mkdir()

    monkeypatch.setenv("INSPECTRA_REQUIREMENTS_DIR", str(reqs))
    monkeypatch.setenv("INSPECTRA_CODE_DIR", str(code))
    monkeypatch.setattr(qa_tools, "REQUIREMENTS_DIR", project_config.requirements_dir())
    monkeypatch.setattr(sandbox, "SUT_DIR", project_config.code_dir())
    monkeypatch.setattr(sandbox, "GENERATED_DIR", generated)
    monkeypatch.setattr(sandbox, "ALLOWED_TEST_DIRS", [generated, code / "tests"])
    return tmp_path


def test_defaults_are_the_bundled_sample(monkeypatch):
    monkeypatch.delenv("INSPECTRA_REQUIREMENTS_DIR", raising=False)
    monkeypatch.delenv("INSPECTRA_CODE_DIR", raising=False)
    monkeypatch.delenv("INSPECTRA_CODE_MODULES", raising=False)
    assert project_config.requirements_dir() == PROJECT_ROOT / "docs" / "requirements"
    assert project_config.code_dir() == PROJECT_ROOT / "sut"
    modules = project_config.code_modules(project_config.code_dir())
    assert [m.as_posix() for m in modules] == ["subscription_service/subscription_manager.py"]


def test_relative_paths_resolve_against_the_repository(monkeypatch):
    monkeypatch.setenv("INSPECTRA_CODE_DIR", "sut")
    assert project_config.code_dir() == PROJECT_ROOT / "sut"


def test_missing_folders_give_a_clear_message(monkeypatch, tmp_path):
    monkeypatch.setenv("INSPECTRA_REQUIREMENTS_DIR", str(tmp_path / "nope"))
    with pytest.raises(project_config.ProjectConfigError, match="INSPECTRA_REQUIREMENTS_DIR"):
        project_config.requirements_dir()
    monkeypatch.setenv("INSPECTRA_CODE_DIR", str(tmp_path / "nope"))
    with pytest.raises(project_config.ProjectConfigError, match="INSPECTRA_CODE_DIR"):
        project_config.code_dir()


def test_code_dir_cannot_be_the_repository_or_its_parent(monkeypatch):
    for path in (PROJECT_ROOT, PROJECT_ROOT.parent):
        monkeypatch.setenv("INSPECTRA_CODE_DIR", str(path))
        with pytest.raises(project_config.ProjectConfigError, match="not this repository"):
            project_config.code_dir()


def test_listed_modules_must_be_python_files_inside_the_code_folder(monkeypatch, other_project):
    monkeypatch.setenv("INSPECTRA_CODE_MODULES", "../reqs/library.md")
    with pytest.raises(project_config.ProjectConfigError, match="INSPECTRA_CODE_MODULES"):
        project_config.code_modules(project_config.code_dir())
    monkeypatch.setenv("INSPECTRA_CODE_MODULES", "library/fees.py")
    assert [m.as_posix() for m in project_config.code_modules(project_config.code_dir())] == ["library/fees.py"]


def test_requirements_come_from_the_configured_folder(other_project):
    reqs = qa_tools.list_requirements()
    assert [r["requirement_id"] for r in reqs] == ["REQ-1.1"]
    assert reqs[0]["source_file"] == "reqs/library.md"
    assert qa_tools.load_requirement("REQ-1.1")["status"] == "success"
    assert qa_tools.load_requirement("REQ-2.1")["status"] == "error"  # the sample's id is gone
    found = qa_tools.search_requirements("late fee per day")
    assert found["results"][0]["requirement_id"] == "REQ-1.1"


def test_module_description_shows_source_and_the_exact_import_line(other_project):
    text, first = project_config.module_description(sandbox.SUT_DIR)
    assert first == "library.fees"
    assert "from library.fees import (LateFeeError, late_fee)" in text  # public names only
    assert "_private" in text  # the source itself is shown, only the import line hides it
    assert "test_old" not in text  # existing tests are not part of the code under test


def test_validator_allows_the_configured_project_and_nothing_else(other_project):
    assert sandbox.validate_generated_code(GENERATED) == (True, "ok")
    ok, reason = sandbox.validate_generated_code("import subscription_service\n")
    assert not ok and "allow-list" in reason
    ok, _ = sandbox.validate_generated_code("import subprocess\n")
    assert not ok


def test_generated_tests_run_against_the_configured_code(other_project):
    path = sandbox.GENERATED_DIR / "test_req_1_1_aaaaaaaa.py"
    path.write_text(GENERATED, encoding="utf-8")
    result = sandbox.run_pytest(str(path))
    assert (result["status"], result["test_outcome"], result["passed"]) == ("success", "passed", 2)


def test_propose_tests_prompt_names_the_configured_project(other_project, monkeypatch):
    seen = {}

    def fake_model(prompt, prompt_version=""):
        seen["prompt"] = prompt
        return "```python\n" + GENERATED + "```"

    monkeypatch.setattr(qa_tools, "get_model_response", fake_model)
    result = qa_tools.propose_tests("REQ-1.1")
    assert result["status"] == "success" and result["test_count"] == 2
    prompt = seen["prompt"]
    assert "library.fees" in prompt and "A book returned after the due day" in prompt
    assert "subscription" not in prompt.lower()  # nothing from the bundled sample leaks in
    assert "{{" not in prompt.split("EXECUTABLE OUTPUT ADDENDUM")[1]  # every placeholder filled


def test_unreadable_code_folder_is_reported_not_crashed(other_project, monkeypatch, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(sandbox, "SUT_DIR", empty)
    result = qa_tools.propose_tests("REQ-1.1")
    assert result["status"] == "error" and "code under test" in result["error"]


def test_the_model_has_no_way_to_set_the_paths():
    import agent_tools

    for tool in agent_tools.TOOLS:
        assert not {"path", "directory", "requirements_dir", "code_dir"} & set(tool.args)
