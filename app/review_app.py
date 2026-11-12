"""PatchAI review app (step 5: the human decision).

Run:  patchai app     (or: streamlit run app/review_app.py)

Pages (in app/views/, one file each):
  Demo      Overview · Fix · Compare
  Evidence  Results · Case explorer · Training · RAG
  Log       Decisions
"""

from __future__ import annotations

import streamlit as st

import ui  # app/ is on the path when Streamlit runs this file

st.set_page_config(page_title="PatchAI", page_icon="🛡️", layout="wide")

pages = {
    "Demo": [
        st.Page("views/overview.py", title="Overview", icon=":material/shield:", default=True,
                help="What PatchAI is, the headline numbers, and a pre-demo checklist."),
        st.Page("views/fix.py", title="Fix", icon=":material/build:",
                help="Scan a project, fix a vulnerability live, review the evidence, approve or reject."),
        st.Page("views/compare.py", title="Compare", icon=":material/balance:",
                help="Run one vulnerability through several models side by side."),
    ],
    "Evidence": [
        st.Page("views/results.py", title="Results", icon=":material/bar_chart:",
                help="The evaluation dashboard: fix rates with intervals, per-type heat map, failures."),
        st.Page("views/cases.py", title="Case explorer", icon=":material/search:",
                help="Replay any recorded benchmark case, attempt by attempt."),
        st.Page("views/training.py", title="Training", icon=":material/model_training:",
                help="How the model was trained: loss curves, data composition, real CVE fixes."),
        st.Page("views/rag.py", title="RAG", icon=":material/menu_book:",
                help="What the knowledge base contains and how the hybrid search ranks it."),
    ],
    "Log": [
        st.Page("views/decisions.py", title="Decisions", icon=":material/history:",
                help="Every approve and reject recorded so far."),
    ],
}

st.sidebar.title("🛡️ PatchAI")
ui.sidebar()
st.navigation(pages).run()
