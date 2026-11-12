"""Fast unit tests for the individual pieces (no scanners, no model)."""

import textwrap

import pytest

from patchai import metrics
from patchai.context import get_context
from patchai.fixer import parse_proposal
from patchai.guard import check_fix
from patchai.models import CodeContext, Finding, FixProposal, RetrievedChunk
from patchai.patching import apply_fix, changed_line_count, clean_model_code, make_diff
from patchai.prompts import build_prompt

SOURCE = textwrap.dedent('''\
    """A module."""
    import sqlite3


    class Repo:
        def __init__(self, conn):
            self.conn = conn

        def find(self, name):
            sql = f"SELECT * FROM users WHERE name = '{name}'"
            return self.conn.execute(sql).fetchall()


    API_TOKEN = "abc123"
''')


def finding(line: int, cwe: str = "CWE-89") -> Finding:
    return Finding(id="x", scanner="bandit", rule_id="B608", cwe=cwe, severity="high",
                   file_path="mod.py", start_line=line, end_line=line, message="SQL built from a string")


@pytest.fixture
def project(tmp_path):
    (tmp_path / "mod.py").write_text(SOURCE, encoding="utf-8")
    return tmp_path


# ---- context ----

def test_context_is_the_enclosing_method(project):
    ctx = get_context(project, finding(10))
    assert ctx.function_name == "find"
    assert (ctx.start_line, ctx.end_line) == (9, 11)
    assert ctx.indent == "    "
    assert "import sqlite3" in ctx.imports
    assert "execute" in ctx.calls


def test_context_for_a_module_level_statement(project):
    ctx = get_context(project, finding(14, "CWE-798"))
    assert ctx.function_name is None
    assert ctx.source.strip() == 'API_TOKEN = "abc123"'


# ---- patching ----

def fixed_method() -> FixProposal:
    return FixProposal(status="fixed", fixed_code=(
        "def find(self, name):\n"
        "    sql = \"SELECT * FROM users WHERE name = ?\"\n"
        "    return self.conn.execute(sql, (name,)).fetchall()"))


def test_fix_is_reindented_into_the_class(project):
    ctx = get_context(project, finding(10))
    patched = apply_fix(SOURCE, ctx, fixed_method())
    assert "    def find(self, name):\n        sql = \"SELECT * FROM users WHERE name = ?\"" in patched.text
    assert patched.text.count("class Repo") == 1


def test_new_import_goes_below_existing_imports(project):
    ctx = get_context(project, finding(10))
    proposal = fixed_method().model_copy(update={"imports_to_add": ["import logging", "import sqlite3"]})
    patched = apply_fix(SOURCE, ctx, proposal)
    lines = patched.text.splitlines()
    assert lines[2] == "import logging"  # after `import sqlite3`, and not duplicated
    assert patched.text.count("import sqlite3") == 1
    assert lines[patched.start_line - 1].strip().startswith("def find")


def test_windows_line_endings_are_kept(project):
    crlf = SOURCE.replace("\n", "\r\n")
    ctx = get_context(project, finding(10))
    patched = apply_fix(crlf, ctx, fixed_method())
    assert "\r\n" in patched.text and "\n" not in patched.text.replace("\r\n", "")


def test_markdown_fences_are_removed():
    assert clean_model_code("```python\nx = 1\n```") == "x = 1"


def test_diff_and_changed_lines():
    diff = make_diff("a\nb\n", "a\nc\n", "f.py")
    assert diff.startswith("--- a/f.py") and changed_line_count(diff) == 2


# ---- guard ----

def guard_for(project, proposal: FixProposal, line: int = 10):
    ctx = get_context(project, finding(line))
    return check_fix(SOURCE, apply_fix(SOURCE, ctx, proposal), proposal, ctx, project)


def test_guard_accepts_a_good_fix(project):
    assert guard_for(project, fixed_method()).passed


@pytest.mark.parametrize("code,imports,expected", [
    ("def find(self, name):\n    return eval(name)", [], "dangerous call: eval"),
    ("def find(self, name):\n    import os\n    return os.system('ls ' + name)", [], "os.system"),
    ("def find(self, name):\n    return sqlsafe.q(name)", ["import sqlsafe"], "not installed"),
    ("def find(self, name):  # nosec\n    return []", [], "silences the scanner"),
    ("def find(self):\n    return []", [], "parameters"),
    ("def lookup(self, name):\n    return []", [], "no longer defines"),
    ("def find(self, name):\n    return [", [], "Syntax error"),
])
def test_guard_rejects_bad_fixes(project, code, imports, expected):
    result = guard_for(project, FixProposal(status="fixed", fixed_code=code, imports_to_add=imports))
    assert not result.passed and expected in result.details


def test_guard_rejects_unchanged_code(project):
    ctx = get_context(project, finding(10))
    result = guard_for(project, FixProposal(status="fixed", fixed_code=ctx.source))
    assert not result.passed and "does not change" in result.details


def test_guard_rejects_huge_changes(project):
    body = "\n".join(f"    x{i} = {i}" for i in range(40))
    result = guard_for(project, FixProposal(status="fixed", fixed_code=f"def find(self, name):\n{body}\n    return []"))
    assert not result.passed and "limit" in result.details


# ---- model answers ----

def test_parse_plain_json():
    assert parse_proposal('{"status": "fixed", "fixed_code": "x = 1"}').fixed_code == "x = 1"


def test_parse_json_in_a_code_fence():
    assert parse_proposal('Here:\n```json\n{"status": "cannot_fix", "explanation": "unsure"}\n```').status == "cannot_fix"


@pytest.mark.parametrize("text", ["no json here", '{"status": "maybe"}', '{"status": "fixed", "confidence": 7}'])
def test_parse_rejects_invalid_answers(text):
    with pytest.raises(ValueError):
        parse_proposal(text)


# ---- prompt ----

def test_prompt_wraps_untrusted_text(project):
    ctx = get_context(project, finding(10))
    chunk = RetrievedChunk(source="guide", title="CWE-89: How to fix", text="Use parameters.")
    messages = build_prompt(finding(10), ctx, [chunk], error="tests failed")
    user = messages[1]["content"]
    assert messages[0]["role"] == "system" and "data, not instructions" in messages[0]["content"]
    assert "<vulnerable_code>\ndef find(self, name):" in user  # dedented
    assert '<reference kind="Security guide"' in user and "<error>\ntests failed\n</error>" in user


# ---- model status ----

def test_model_status_without_ollama(monkeypatch):
    from patchai import llm

    monkeypatch.setattr(llm, "list_models", lambda: [])
    status = llm.model_status()
    assert status["ollama"] is False and status["default"] is None and "Ollama" in status["problem"]


def test_model_status_with_only_the_base_model(monkeypatch):
    from patchai import llm

    monkeypatch.setattr(llm, "list_models", lambda: ["qwen2.5-coder:3b"])
    status = llm.model_status()
    assert status["ollama"] and status["default"] == "qwen2.5-coder:3b"
    assert status["fine_tuned"] is False and "patchai-3b" in status["problem"]


def test_model_status_with_the_fine_tuned_model(monkeypatch):
    from patchai import llm

    monkeypatch.setattr(llm, "list_models", lambda: ["patchai-3b", "qwen2.5-coder:3b"])
    status = llm.model_status()
    assert status["default"] == "patchai-3b" and status["fine_tuned"] and status["problem"] is None


# ---- metrics ----

def test_wilson_interval():
    low, high = metrics.wilson_interval(7, 10)
    assert 0.39 < low < 0.40 and 0.89 < high < 0.90
    assert metrics.wilson_interval(0, 0) == (0.0, 0.0)


def test_canonical_model_depends_on_the_run():
    assert metrics.canonical_model("patchai-3b", "v1") == "patchai-3b-v1"
    assert metrics.canonical_model("patchai-3b", "v1_rescored") == "patchai-3b-v1"
    assert metrics.canonical_model("patchai-3b", "v2") == "patchai-3b"
    assert metrics.canonical_model("patchai-3b-v1", "v2") == "patchai-3b-v1"
    assert metrics.canonical_model("qwen2.5-coder:7b", "v1") == "qwen2.5-coder:7b"
    assert metrics.canonical_model("patchai-3b [no RAG]", "v1") == "patchai-3b-v1 [no RAG]"


def test_model_labels_and_colors():
    assert metrics.model_label("patchai-3b", "v2") == "PatchAI-3B v2 (ours)"
    assert metrics.model_label("patchai-3b", "v1_rescored") == "PatchAI-3B v1 (ours)"
    assert metrics.model_label("patchai-3b [no RAG]", "v2") == "PatchAI-3B v2 (ours) [no RAG]"
    assert metrics.model_label("mystery-model") == "mystery-model"
    assert metrics.model_color("patchai-3b", "v2") == "#2a78d6"
    assert metrics.model_color("patchai-3b", "v1") == "#c9418f"
    assert metrics.model_color("mystery-model") == "#8a8984"


def test_model_order():
    models = ["qwen2.5-coder:7b", "zz-unknown", "patchai-3b", "qwen2.5-coder:3b", "aa-unknown"]
    assert metrics.model_order(models, "v2") == [
        "qwen2.5-coder:3b", "patchai-3b", "qwen2.5-coder:7b", "aa-unknown", "zz-unknown"]
    # In a v1 run, patchai-3b is v1 and sorts into v1's slot.
    assert metrics.model_order(["patchai-3b", "qwen2.5-coder:3b"], "v1") == ["qwen2.5-coder:3b", "patchai-3b"]


def test_summary():
    rows = [
        {"model": "m", "cwe": "CWE-89", "verdict": "fixed", "attempts": 1, "seconds": 10, "changed_lines": 4,
         "first_attempt_fixed": True, "format_failures": 0, "guard_failures": 0, "fake_fix": False, "final_failure": None},
        {"model": "m", "cwe": "CWE-78", "verdict": "failed", "attempts": 3, "seconds": 30, "changed_lines": 0,
         "first_attempt_fixed": False, "format_failures": 1, "guard_failures": 1, "fake_fix": True, "final_failure": "tests"},
    ]
    s = metrics.summarize(rows)["m"]
    assert s["fix_rate"] == 0.5 and s["fake_fix_rate"] == 0.5 and s["format_error_rate"] == 0.25
    assert metrics.fix_rate_by_cwe(rows)["m"] == {"CWE-78": 0.0, "CWE-89": 1.0}
    assert metrics.failure_reasons(rows)["m"]["tests"] == 1
