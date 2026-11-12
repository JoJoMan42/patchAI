"""RAG: what the knowledge base contains and how the hybrid search ranks it."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import ui
from patchai.config import get_config, path
from patchai.embeddings import get_embedder
from patchai.models import CWE_NAMES
from patchai.rag_index import code_collection, knowledge_collections
from patchai.rag_search import rank

settings = ui.settings()
st.header("The knowledge base")
st.caption("Before the model writes a fix, PatchAI retrieves a security guide for the bug's type, "
           "similar past fixes, and helper functions from the project itself.")


@st.cache_resource(show_spinner="Loading the search index...")
def collections(project: str):
    knowledge = knowledge_collections()
    return {"guide": knowledge["guide"], "past_fix": knowledge["past_fix"],
            "code": code_collection(project)}


cols = collections(str(settings.project))
c1, c2, c3 = st.columns(3)
c1.metric("Guide sections", len(cols["guide"].chunks), help="7 hand-written guides, 7 sections each")
c2.metric("Past fixes", len(cols["past_fix"].chunks))
c3.metric("Functions in this project", len(cols["code"].chunks))

embedder = get_embedder()
if embedder.name == "hash":
    st.warning("The offline **hash** embedder is active, so meaning-based search is weak. "
               "Set `rag.embedder: fastembed` in config.yaml and run `patchai doctor` once while online.",
               icon="⚠️")
else:
    st.caption(f"Embeddings: `{embedder.name}` · reranker: `{get_config()['rag']['reranker'] or 'off'}` "
               "· all local, nothing leaves this machine.")

st.subheader("Try a search")
st.markdown("Two searches run at once — one by **meaning** (embeddings), one by **keywords** (BM25). "
            "Their ranks are merged (reciprocal rank fusion), then a **reranker** reads the query and each "
            "candidate together and picks the best.")
c1, c2 = st.columns(2)
source = c1.selectbox("Collection", ["guide", "past_fix", "code"],
                      format_func=lambda s: ui.SOURCE_LABELS.get(s, s))
cwe = c2.selectbox("Vulnerability type (guides and past fixes only)",
                   ["(any)"] + list(CWE_NAMES), format_func=lambda c: CWE_NAMES.get(c, c))
query = st.text_input("Query", "parameterized query placeholder sqlite3")

if query.strip():
    where = None
    if cwe != "(any)" and source != "code":
        def where(chunk: dict) -> bool:
            return chunk.get("cwe") == cwe
    collection = cols[source]
    rows = rank(collection, query, where=where)
    if not rows:
        st.info("Nothing matched. Try other words, or drop the type filter.")
    else:
        st.dataframe(pd.DataFrame([{
            "Title": collection.chunks[r["index"]]["title"],
            "Meaning rank": str(r["meaning_rank"]) if r["meaning_rank"] is not None else "—",
            "Keyword rank": str(r["keyword_rank"]) if r["keyword_rank"] is not None else "—",
            "Fused": round(r["fused"], 4),
            "Final score": round(r["score"], 3),
        } for r in rows[:10]]), hide_index=True, width="stretch")
        st.caption("A result that only one search found still wins when the reranker likes it.")
        for r in rows[:3]:
            chunk = collection.chunks[r["index"]]
            with st.expander(f"{chunk['title']} · final score {r['score']:.2f}"):
                st.code(chunk["text"][:2000], language="markdown" if source == "guide" else "python")

st.subheader("Read a guide")
guide_cwe = st.selectbox("Type", list(CWE_NAMES), format_func=lambda c: f"{CWE_NAMES[c]} ({c})")
guide_file = path("knowledge") / f"{guide_cwe.lower()}.md"
if guide_file.exists():
    with st.container(border=True):
        st.markdown(guide_file.read_text(encoding="utf-8"))
else:
    st.warning(f"Guide file not found: {guide_file.name}")
