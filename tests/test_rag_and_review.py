"""RAG indexing/search and the human approval step."""

import json

import pytest
from reference_fixes import GOOD_FIXES

from patchai import review
from patchai.config import path
from patchai.context import get_context
from patchai.llm import LLMReply
from patchai.models import Finding, FixResult
from patchai.pipeline import fix_finding
from patchai.rag_index import build_index, chunk_code, chunk_guides, chunk_past_fixes, code_collection
from patchai.rag_search import rank, retrieve, search


def test_knowledge_files_are_chunked():
    guides = chunk_guides(path("knowledge"))
    assert {c["cwe"] for c in guides} == {"CWE-89", "CWE-78", "CWE-22", "CWE-79", "CWE-798", "CWE-327", "CWE-502"}
    assert len(guides) == 7 * 7  # seven sections per guide
    assert len(chunk_past_fixes(path("fix_examples"))) == 35


def test_code_is_chunked_by_function(shop):
    titles = {c["title"] for c in chunk_code(shop)}
    assert "shop/db.py::search_products" in titles
    assert not any("tests/" in t for t in titles)


def test_build_index_counts(shop):
    counts = build_index(shop)
    assert counts["guide"] == 49 and counts["past_fix"] == 35 and counts["code"] > 10


def test_hybrid_search_finds_the_right_guide(shop):
    from patchai.rag_index import knowledge_collections

    results = search(knowledge_collections()["guide"], "guide", "parameterized query placeholder sqlite3 execute", 3)
    assert results and results[0].title.startswith("CWE-89")


def test_rank_exposes_every_stage_and_search_uses_it(shop):
    """search() is rank()[:k]; a row shows its place in each ranking stage."""
    from patchai.rag_index import knowledge_collections

    guide = knowledge_collections()["guide"]
    query = "parameterized query placeholder sqlite3 execute"
    rows = rank(guide, query)
    assert rows and all(rows[i]["score"] >= rows[i + 1]["score"] for i in range(len(rows) - 1))
    assert any(r["meaning_rank"] is not None and r["keyword_rank"] is not None for r in rows)
    results = search(guide, "guide", query, 3)
    # Pasted from the code before the rank/search split (hash embedder, no reranker):
    assert results[0].title == "CWE-89: SQL Injection: How to fix it in Python"
    assert [r.title for r in results] == [guide.chunks[row["index"]]["title"] for row in rows[:3]]
    assert [r.score for r in results] == [round(float(row["score"]), 3) for row in rows[:3]]


def test_retrieve_returns_guides_code_and_past_fixes_of_the_same_type(shop, shop_findings):
    finding = next(f for f in shop_findings if f.cwe == "CWE-89")
    chunks = retrieve(shop, finding, get_context(shop, finding))
    assert {c.source for c in chunks} == {"guide", "code", "past_fix"}
    assert all(c.title.startswith("CWE-89") for c in chunks if c.source == "guide")
    code = [c for c in chunks if c.source == "code"]
    assert code[0].title == "shop/db.py::rows_to_dicts"  # the helper the vulnerable function calls
    assert all("search_products" not in c.title for c in code)  # never the vulnerable function itself


def test_code_index_updates_when_a_file_changes(shop):
    first = code_collection(shop)
    (shop / "shop" / "extra.py").write_text("def brand_new_helper():\n    return 42\n", encoding="utf-8")
    second = code_collection(shop)
    assert len(second.chunks) == len(first.chunks) + 1


# ---- review ----

def fixed_result(shop, shop_findings) -> FixResult:
    finding = next(f for f in shop_findings if f.cwe == "CWE-798")
    answer = GOOD_FIXES["CWE-798"].model_dump_json()
    return fix_finding(shop, finding, model="fake", use_rag=False,
                       chat_fn=lambda m, model: LLMReply(answer, model, 0, 0, 0.0))


def test_approve_writes_the_fix_and_logs_it(shop, shop_findings):
    result = fixed_result(shop, shop_findings)
    assert result.verdict == "fixed"
    review.approve(shop, result, reviewer="tester")
    assert "os.environ" in (shop / "shop" / "config.py").read_text(encoding="utf-8")
    last = review.load_decisions()[-1]
    assert last["decision"] == "approved" and last["reviewer"] == "tester" and last["cwe"] == "CWE-798"


def test_unverified_fix_cannot_be_approved(shop):
    finding = Finding(id="x", scanner="bandit", rule_id="B608", cwe="CWE-89", severity="high",
                      file_path="shop/db.py", start_line=1, end_line=1, message="")
    with pytest.raises(review.ApprovalError):
        review.approve(shop, FixResult(finding=finding, model="m", verdict="failed"))


def test_approval_refuses_if_the_file_changed(shop, shop_findings):
    result = fixed_result(shop, shop_findings)
    (shop / "shop" / "config.py").write_text("# edited by someone else\n", encoding="utf-8")
    with pytest.raises(review.ApprovalError):
        review.approve(shop, result)


def test_reject_needs_a_reason(shop, shop_findings):
    result = fixed_result(shop, shop_findings)
    with pytest.raises(review.ApprovalError):
        review.reject(shop, result, "  ")
    review.reject(shop, result, "Wrong fix", reviewer="tester")
    assert review.load_decisions()[-1]["reason"] == "Wrong fix"
    assert json.loads(path("decisions").read_text().splitlines()[-1])["decision"] == "rejected"
