"""End-to-end tests: the whole pipeline on the demo shop, with a scripted stand-in for the model."""

import pytest
from reference_fixes import FAKE_TOKEN_FIX, GOOD_FIXES, HALLUCINATED_FIX, HAND_ESCAPED_FIX

from patchai.llm import LLMReply
from patchai.models import FixProposal
from patchai.pipeline import fix_finding


def scripted_model(*answers: FixProposal | str):
    """A fake model that gives the listed answers in order, and records the prompts it saw."""
    replies = [a if isinstance(a, str) else a.model_dump_json() for a in answers]
    prompts = []

    def chat(messages, model):
        prompts.append(messages[-1]["content"])
        return LLMReply(text=replies[min(len(prompts) - 1, len(replies) - 1)], model=model,
                        tokens_in=100, tokens_out=50, seconds=0.0)

    chat.prompts = prompts
    return chat


def finding_for(findings, cwe):
    return next(f for f in findings if f.cwe == cwe)


@pytest.mark.parametrize("cwe", sorted(GOOD_FIXES))
def test_good_fix_passes_every_check(shop, shop_findings, cwe):
    result = fix_finding(shop, finding_for(shop_findings, cwe), model="fake",
                         chat_fn=scripted_model(GOOD_FIXES[cwe]))
    assert result.error is None
    checks = {c.name: c for c in result.final.checks}
    assert result.verdict == "fixed", {n: c.details for n, c in checks.items()}
    assert set(checks) == {"format", "guard", "tests", "security_test", "rescan"}
    assert not checks["security_test"].skipped
    assert result.patched_file_text and result.diff.startswith("--- a/")


def test_fake_fix_is_caught_by_the_security_test(shop, shop_findings):
    result = fix_finding(shop, finding_for(shop_findings, "CWE-327"), model="fake",
                         max_attempts=1, chat_fn=scripted_model(FAKE_TOKEN_FIX))
    checks = {c.name: c for c in result.final.checks}
    assert result.verdict == "failed"
    assert checks["rescan"].passed  # the scanner is fooled...
    assert not checks["security_test"].passed  # ...but the attack still works


def test_hallucinated_import_is_blocked_by_the_guard(shop, shop_findings):
    result = fix_finding(shop, finding_for(shop_findings, "CWE-89"), model="fake",
                         max_attempts=1, chat_fn=scripted_model(HALLUCINATED_FIX))
    guard = next(c for c in result.final.checks if c.name == "guard")
    assert not guard.passed and "sqlsafe" in guard.details
    assert result.verdict == "failed"


def test_hand_escaping_is_rejected_by_the_rescan(shop, shop_findings):
    result = fix_finding(shop, finding_for(shop_findings, "CWE-89"), model="fake",
                         max_attempts=1, chat_fn=scripted_model(HAND_ESCAPED_FIX))
    rescan = next(c for c in result.final.checks if c.name == "rescan")
    assert not rescan.passed


def test_retry_uses_the_error_and_succeeds(shop, shop_findings):
    model = scripted_model(HALLUCINATED_FIX, GOOD_FIXES["CWE-89"])
    result = fix_finding(shop, finding_for(shop_findings, "CWE-89"), model="fake", chat_fn=model)
    assert result.verdict == "fixed"
    assert len(result.attempts) == 2
    assert "sqlsafe" in model.prompts[1]  # the second prompt contains the guard's error


def test_broken_json_counts_as_a_format_failure(shop, shop_findings):
    model = scripted_model("Sure! Here is the fix: def search_products(...)", GOOD_FIXES["CWE-89"])
    result = fix_finding(shop, finding_for(shop_findings, "CWE-89"), model="fake", chat_fn=model)
    assert result.attempts[0].checks[0].name == "format" and not result.attempts[0].checks[0].passed
    assert result.verdict == "fixed"


def test_model_can_report_a_false_positive(shop, shop_findings):
    answer = FixProposal(status="false_positive", explanation="Only constant values reach the query.")
    result = fix_finding(shop, finding_for(shop_findings, "CWE-89"), model="fake", chat_fn=scripted_model(answer))
    assert result.verdict == "false_positive"
    assert len(result.attempts) == 1


def test_prompt_contains_the_retrieved_context(shop, shop_findings):
    model = scripted_model(GOOD_FIXES["CWE-89"])
    result = fix_finding(shop, finding_for(shop_findings, "CWE-89"), model="fake", chat_fn=model)
    sources = {chunk.source for chunk in result.retrieved}
    assert "code" in sources
    assert "rows_to_dicts" in model.prompts[0]  # the helper the vulnerable function calls
    assert "<vulnerable_code>" in model.prompts[0]


def test_the_original_project_is_never_modified(shop, shop_findings):
    before = (shop / "shop" / "db.py").read_bytes()
    fix_finding(shop, finding_for(shop_findings, "CWE-89"), model="fake",
                chat_fn=scripted_model(GOOD_FIXES["CWE-89"]))
    assert (shop / "shop" / "db.py").read_bytes() == before


# ---- v2: retries see the previous fix and the real error; repeated answers aren't re-checked ----

CRASHING_SECRET_FIX = FixProposal(status="fixed", fixed_code='ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]',
                                  explanation="Read it from the environment.", confidence=0.9)


def test_the_real_error_reaches_the_model(shop, shop_findings, monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    model = scripted_model(CRASHING_SECRET_FIX, GOOD_FIXES["CWE-798"])
    result = fix_finding(shop, finding_for(shop_findings, "CWE-798"), model="fake", chat_fn=model)
    tests = next(c for c in result.attempts[0].checks if c.name == "tests")
    assert not tests.passed and "KeyError: 'ADMIN_PASSWORD'" in tests.details  # not just "<test run error>"
    assert "KeyError: 'ADMIN_PASSWORD'" in model.prompts[1]
    assert '<previous_fix>\nADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]\n</previous_fix>' in model.prompts[1]
    assert result.verdict == "fixed"


def test_a_repeated_answer_is_not_checked_again(shop, shop_findings):
    model = scripted_model(HAND_ESCAPED_FIX)  # the same wrong answer every time
    result = fix_finding(shop, finding_for(shop_findings, "CWE-89"), model="fake", max_attempts=3, chat_fn=model)
    assert result.verdict == "failed" and len(result.attempts) == 3
    assert all("same code as attempt 1" in c.details for c in result.attempts[2].checks if c.name != "format")
    assert "exactly the same code" in model.prompts[2]


def test_code_wrapped_in_prompt_tags_still_counts(shop, shop_findings):
    good = GOOD_FIXES["CWE-89"]
    wrapped = good.model_copy(update={"fixed_code": f"<vulnerable_code>{good.fixed_code}</vulnerable_code>"})
    result = fix_finding(shop, finding_for(shop_findings, "CWE-89"), model="fake", chat_fn=scripted_model(wrapped))
    assert result.verdict == "fixed"
