"""Step 2b: find the information the model needs to fix a finding (the "R" in RAG).

For each finding we search three collections:
  guide     how to fix this vulnerability type          (searched with a "how to fix" question)
  past_fix  similar bugs that were fixed before         (searched with the vulnerable code)
  code      helper functions in the same project        (functions the code calls come first)

Each search is hybrid: meaning-based (embeddings) and keyword-based (BM25) results are
merged with reciprocal rank fusion, then a cross-encoder reranker picks the best ones.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np

from patchai.config import get_config
from patchai.embeddings import get_embedder, get_reranker, tokenize
from patchai.models import CodeContext, Finding, RetrievedChunk, cwe_name
from patchai.rag_index import Collection, code_collection, knowledge_collections

RRF_K = 60  # standard constant for reciprocal rank fusion


def retrieve(project_dir: str | Path, finding: Finding, context: CodeContext) -> list[RetrievedChunk]:
    """Everything RAG gives the model for one finding."""
    top_k = get_config()["rag"]["top_k"]
    knowledge = knowledge_collections()
    same_type = (lambda c: c.get("cwe") == finding.cwe) if finding.cwe else None

    guides = search(
        knowledge["guide"], "guide",
        f"How to fix {cwe_name(finding.cwe)} ({finding.cwe}) in Python safely. {finding.message}",
        top_k["guide"], where=same_type,
    )
    past_fixes = search(knowledge["past_fix"], "past_fix", context.source, top_k["past_fix"], where=same_type)
    helpers = related_code(code_collection(project_dir), context, top_k["code"])
    return guides + helpers + past_fixes


def related_code(collection: Collection, context: CodeContext, k: int) -> list[RetrievedChunk]:
    """Project functions that help the model fix the code in the project's own style."""

    def is_other_code(chunk: dict) -> bool:
        same_place = (
            chunk["file_path"] == context.file_path
            and chunk["start_line"] <= context.end_line
            and chunk["end_line"] >= context.start_line
        )
        return not same_place

    # Functions the vulnerable code calls directly are the most useful (e.g. a db helper).
    called = [
        _to_result(c, "code", 1.0)
        for c in collection.chunks
        if is_other_code(c) and c.get("symbol") in context.calls
    ][:k]
    if len(called) >= k:
        return called
    query = " ".join(context.calls) + "\n" + context.source
    taken = {r.title for r in called}
    others = [r for r in search(collection, "code", query, k + len(called), where=is_other_code) if r.title not in taken]
    return called + others[: k - len(called)]


def rank(collection: Collection, query: str,
         where: Callable[[dict], bool] | None = None, rerank: bool = True) -> list[dict]:
    """Every candidate with its place in each ranking stage, best first.

    Each row: {"index": chunk index, "meaning_rank": 1-based place in the embedding
    search or None, "keyword_rank": same for BM25, "fused": the fusion score,
    "score": the final (reranker) score}.
    """
    allowed = [i for i, c in enumerate(collection.chunks) if where is None or where(c)]
    if not allowed:
        return []
    n = get_config()["rag"]["candidates"]

    # 1. Meaning-based ranking (cosine similarity of embeddings).
    query_vec = get_embedder(collection.embedder).embed([query])[0]
    sims = collection.vectors[allowed] @ query_vec
    by_meaning = [allowed[i] for i in np.argsort(-sims)[:n]]

    # 2. Keyword ranking (BM25).
    keyword_scores = collection.bm25.get_scores(tokenize(query))
    by_keyword = sorted((i for i in allowed if keyword_scores[i] > 0), key=lambda i: -keyword_scores[i])[:n]

    # 3. Reciprocal rank fusion: documents ranked high by either method rise to the top.
    fused: dict[int, float] = {}
    for ranking in (by_meaning, by_keyword):
        for place, i in enumerate(ranking):
            fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + place + 1)
    candidates = sorted(fused, key=lambda i: -fused[i])[:n]

    # 4. Rerank the candidates with a cross-encoder, which reads query and chunk together.
    reranker = get_reranker() if rerank else None
    max_chars = get_config()["rag"]["max_chunk_chars"]
    if reranker is not None:
        texts = [collection.chunks[i]["title"] + "\n" + collection.chunks[i]["text"][:max_chars] for i in candidates]
        scores = dict(zip(candidates, reranker.score(query[:2000], texts)))
    else:
        best = max(fused.values())
        scores = {i: fused[i] / best for i in candidates}

    meaning_place = {i: p + 1 for p, i in enumerate(by_meaning)}
    keyword_place = {i: p + 1 for p, i in enumerate(by_keyword)}
    return [{"index": i, "meaning_rank": meaning_place.get(i), "keyword_rank": keyword_place.get(i),
             "fused": fused[i], "score": scores[i]}
            for i in sorted(candidates, key=lambda i: -scores[i])]


def search(collection: Collection, source: str, query: str, k: int,
           where: Callable[[dict], bool] | None = None, rerank: bool = True) -> list[RetrievedChunk]:
    """Hybrid search: embeddings + BM25, merged with reciprocal rank fusion, then reranked."""
    if k <= 0:
        return []
    rows = rank(collection, query, where=where, rerank=rerank)
    return [_to_result(collection.chunks[r["index"]], source, r["score"]) for r in rows[:k]]


def _to_result(chunk: dict, source: str, score: float) -> RetrievedChunk:
    max_chars = get_config()["rag"]["max_chunk_chars"]
    return RetrievedChunk(
        source=source, title=chunk["title"], text=chunk["text"][:max_chars],
        file_path=chunk.get("file_path"), score=round(float(score), 3),
    )
