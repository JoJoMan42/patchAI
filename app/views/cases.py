"""Case explorer: replay any recorded benchmark case, attempt by attempt."""

from __future__ import annotations

import json

import streamlit as st

import ui
from patchai import metrics
from patchai.config import ROOT
from patchai.models import CWE_NAMES

st.header("Case explorer")

all_runs = ui.runs()
if not all_runs:
    ui.empty_state("No evaluation runs found.", "Pull the repo or run `python eval/run_eval.py`.")
    st.stop()

preset = st.session_state.pop("selected_case", None)  # (run, model, case_id) set by the Results page
preset_run, preset_model, preset_case = preset if preset else (None, None, None)

run = st.selectbox("Run", all_runs, index=all_runs.index(preset_run) if preset_run in all_runs else 0)
records = ui.load_records(run)
if not ui.has_full_logs(run):
    ui.empty_state(
        f"Run `{run}` has no per-case logs on this machine (`eval/results/{run}/full/`).",
        "Download `v2_full_eval_logs.zip` from the team's Google Drive and extract it there (plan WP0, step 5).")
    st.stop()

models = metrics.model_order(sorted({r["model"] for r in records}))
cwes = sorted({r["cwe"] for r in records})
c1, c2, c3 = st.columns(3)
model = c1.selectbox("Model", models, format_func=metrics.model_label,
                     index=models.index(preset_model) if preset_model in models else 0)
cwe = c2.selectbox("Type", ["(all)"] + cwes, format_func=lambda c: CWE_NAMES.get(c, c))
outcome = c3.selectbox("Outcome", ["(all)", "fixed", "not fixed"])

rows = [r for r in records if r["model"] == model
        and (cwe == "(all)" or r["cwe"] == cwe)
        and (outcome == "(all)" or (r["verdict"] == "fixed") == (outcome == "fixed"))]
ids = sorted(r["case_id"] for r in rows)
if not ids:
    st.info("No case matches these filters.")
    st.stop()
case_id = st.selectbox("Case", ids, index=ids.index(preset_case) if preset_case in ids else 0)

case = ui.load_cases().get(case_id, {})
record = next((r for r in rows if r["case_id"] == case_id), {})
c1, c2, c3, c4 = st.columns(4)
c1.metric("Type", CWE_NAMES.get(case.get("cwe", ""), case.get("cwe", "?")))
c2.metric("Pattern family", case.get("family", "?"))
c3.metric("Origin", "hand-written" if case.get("source") == "handwritten" else "generated")
c4.metric("Verdict here", record.get("verdict", "?"))

project = ROOT / case.get("project", "")
vulnerable = project / case.get("file", "")
if vulnerable.is_file():
    with st.expander("The vulnerable file", expanded=False):
        st.code(vulnerable.read_text(encoding="utf-8"), language="python", line_numbers=True)
tests = sorted((project / "security_tests").glob("test_*.py")) if (project / "security_tests").is_dir() else []
if tests:
    with st.expander("The attack test"):
        for t in tests:
            st.caption(t.name)
            st.code(t.read_text(encoding="utf-8"), language="python")

result = ui.recorded(run, model, case_id)
if result is None:
    st.warning(f"The log file for `{case_id}` with this model is missing under `eval/results/{run}/full/`.")
else:
    st.subheader("The recorded run")
    ui.show_result(result)

reference = case.get("reference_fix")
if reference:
    with st.expander("The reference fix (what a correct answer looks like)"):
        st.code(reference.get("fixed_code", ""), language="python")
        if reference.get("imports_to_add"):
            st.caption("Adds imports: " + ", ".join(reference["imports_to_add"]))
