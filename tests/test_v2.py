"""Tests for the v2 changes: fair parsing, clearer errors, retry prompts, balanced training data,
and the real-world (CVEfixes) data builder. No model, GPU or network needed."""

import ast
import random
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "training"))

from make_dataset import retry_for  # noqa: E402
from real_data import split_diff, undo_diff  # noqa: E402
from synth import generate  # noqa: E402

from patchai.checks import error_lines  # noqa: E402
from patchai.models import CodeContext, Finding  # noqa: E402
from patchai.patching import clean_model_code  # noqa: E402
from patchai.prompts import build_prompt  # noqa: E402


@pytest.mark.parametrize("wrapped", [
    "<vulnerable_code>def f():\n    return 1</vulnerable_code>",
    "<vulnerable_code>\ndef f():\n    return 1\n</vulnerable_code>",
    "```python\ndef f():\n    return 1\n```",
    "```python\n<vulnerable_code>\ndef f():\n    return 1\n</vulnerable_code>\n```",
    "    def f():\n        return 1",
])
def test_model_wrapping_is_removed(wrapped):
    assert clean_model_code(wrapped) == "def f():\n    return 1"


def test_code_that_mentions_tags_is_untouched():
    assert clean_model_code('html = "<code>x</code>"') == 'html = "<code>x</code>"'


def test_error_lines_come_from_pytest_output():
    out = "ERROR collecting tests/test_a.py\nE   KeyError: 'API_TOKEN'\nE   KeyError: 'API_TOKEN'\n=== 1 error ==="
    assert error_lines(out) == "KeyError: 'API_TOKEN'"
    assert error_lines("all good") == ""


def test_retry_prompt_shows_the_previous_fix():
    finding = Finding(id="x", scanner="bandit", rule_id="B105", cwe="CWE-798", severity="low", message="m",
                      file_path="m.py", start_line=1, end_line=1, code='KEY = "abc"')
    context = CodeContext(file_path="m.py", function_name=None, start_line=1, end_line=1, source='KEY = "abc"\n',
                          indent="")
    user = build_prompt(finding, context, [], error="KeyError: 'KEY'", previous_fix='KEY = os.environ["KEY"]')[1]["content"]
    assert '<previous_fix>\nKEY = os.environ["KEY"]\n</previous_fix>' in user
    assert "<error>\nKeyError: 'KEY'\n</error>" in user and "Do not repeat" in user
    assert "previous_fix" not in build_prompt(finding, context, [])[1]["content"]


def test_training_data_is_balanced():
    pairs = generate(1400, seed=7)
    assert len(pairs) == 1400 and len({p.id for p in pairs}) == 1400
    fixed = Counter(p.cwe for p in pairs if p.status == "fixed")
    assert len(fixed) == 7 and max(fixed.values()) - min(fixed.values()) <= 2  # v1 bug: CWE-78 got 88 of 2500
    false_alarms = [p for p in pairs if p.status == "false_positive"]
    assert len(false_alarms) == round(1400 * 0.08)  # v1 bug: 25% false alarms
    assert max(Counter(p.family for p in false_alarms).values()) < len(false_alarms) * 0.7


def test_training_pairs_are_valid_python_and_secrets_never_crash():
    for pair in generate(600, seed=3):
        ast.parse(pair.module())
        ast.parse(pair.fixed)
        if pair.cwe == "CWE-798" and pair.status == "fixed":
            assert 'os.environ["' not in pair.fixed  # v1 habit that crashed on import


def test_retry_examples_use_the_typical_mistake():
    pair = next(p for p in generate(300, seed=1) if p.family == "secret_constant")
    finding = Finding(id="x", scanner="bandit", rule_id="B105", cwe="CWE-798", severity="low",
                      message="Possible hardcoded password", file_path="module.py", start_line=4, end_line=4,
                      code=pair.vulnerable)
    kinds = Counter(retry_for(pair, finding, random.Random(i))[0] for i in range(200))
    assert kinds["typical_mistake"] > 80
    kind, error, previous = next(retry_for(pair, finding, random.Random(i)) for i in range(200)
                                 if retry_for(pair, finding, random.Random(i))[0] == "typical_mistake")
    assert "KeyError" in error and 'os.environ["' in previous


DIFF = """diff --git a/app/db.py b/app/db.py
index 1..2 100644
--- a/app/db.py
+++ b/app/db.py
@@ -1,4 +1,4 @@
 def find(cur, name):
-    cur.execute("SELECT * FROM t WHERE n = '%s'" % name)
+    cur.execute("SELECT * FROM t WHERE n = ?", (name,))
     return cur.fetchall()
 
"""


def test_undo_diff_rebuilds_the_vulnerable_file():
    after = 'def find(cur, name):\n    cur.execute("SELECT * FROM t WHERE n = ?", (name,))\n    return cur.fetchall()\n\nX = 1\n'
    files = split_diff(DIFF)
    assert list(files) == ["app/db.py"]
    before = undo_diff(after, files["app/db.py"])
    assert before == after.replace('"SELECT * FROM t WHERE n = ?", (name,)', '"SELECT * FROM t WHERE n = \'%s\'" % name')
    assert undo_diff("something else entirely\n", files["app/db.py"]) is None
