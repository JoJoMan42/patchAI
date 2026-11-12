"""Compare: one vulnerability through several models, side by side."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import ui
from patchai import metrics
from patchai.models import Finding, FixResult, cwe_name
from patchai.patching import changed_line_count
from patchai.pipeline import fix_finding

settings = ui.settings()
st.header("Compare models on the same vulnerability")
st.caption("Best demo: try the **hard-coded secret** — our v1 fails it, our v2 fixes it.")

findings: list[Finding] = st.session_state.get("findings", [])
if not findings:
    ui.empty_state("No findings yet.", "Scan a project on the **Fix** page first.")
    st.stop()

finding = st.selectbox("Vulnerability", findings, format_func=ui.finding_label, key="compare_finding")
status = ui.status()
story = ["qwen2.5-coder:3b", "patchai-3b-v1", "patchai-3b", "qwen2.5-coder:7b"]

if status["ollama"]:
    wanted = [m for m in story if m in status["installed"]] or status["installed"][:2]
    chosen = st.multiselect("Models", metrics.model_order(status["installed"]),
                            default=wanted, format_func=metrics.model_label)
    if st.button("⚖️ Run comparison", type="primary", disabled=not chosen):
        comparison = []
        for model in chosen:
            with st.status(f"{metrics.model_label(model)}...", expanded=False) as box:
                result = fix_finding(settings.project, finding, model=model,
                                     on_event=lambda stage, msg: box.write(f"**{stage}** · {msg}"))
                box.update(label=f"{metrics.model_label(model)}: {result.verdict} ({result.seconds:.0f}s)",
                           state="complete" if result.verdict == "fixed" else "error")
            comparison.append(result)
        st.session_state.comparison = comparison
else:
    st.caption("Ollama is not running, so a live comparison is not possible.")
    match = next((c for c in ui.load_cases().values()
                  if c["source"] == "handwritten" and c["cwe"] == finding.cwe
                  and c["file"] == finding.file_path), None)
    if match and st.button("▶️ Load the recorded comparison (run v2)"):
        loaded = [r for m in story if (r := ui.recorded("v2", m, match["id"])) is not None]
        if loaded:
            st.session_state.comparison = loaded
            st.session_state.comparison_recorded = True
        else:
            st.error("The recorded logs are missing (`eval/results/v2/full/`). See the plan's WP0, step 5.")

comparison: list[FixResult] = st.session_state.get("comparison", [])
if not comparison:
    st.stop()
if st.session_state.get("comparison_recorded"):
    st.info("Recorded on 2026-11-09 on the RTX 4060 laptop (run `v2`). **Not a live run.**",
            icon=":material/history:")

st.dataframe(pd.DataFrame([{
    "Model": metrics.model_label(r.model),
    "Verdict": ui.VERDICT_STYLE[r.verdict][1],
    "Attempts": len(r.attempts),
    "Seconds": round(r.seconds, 1),
    "Tokens": sum(a.tokens_in + a.tokens_out for a in r.attempts),
    "Changed lines": changed_line_count(r.diff) if r.verdict == "fixed" else 0,
} for r in comparison]), hide_index=True, width="stretch")

for column, result in zip(st.columns(len(comparison)), comparison):
    with column:
        st.markdown(f"### {metrics.model_label(result.model)}")
        ui.show_result(result, compact=True)
        with st.expander("All attempts"):
            for attempt in result.attempts:
                st.markdown(f"**Attempt {attempt.number}** — {'passed' if attempt.passed else 'failed'}")
                for c in attempt.checks:
                    icon = "➖" if c.skipped else ("✅" if c.passed else "❌")
                    st.caption(f"{icon} {ui.CHECK_LABELS[c.name]}: {c.details[:120]}")
