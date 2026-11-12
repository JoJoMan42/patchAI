"""Fix: scan → pick a finding → fix it live (or replay a recorded fix) → approve or reject."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import ui
from patchai import review
from patchai.checks import security_test_files
from patchai.context import get_context
from patchai.models import Finding, FixResult, cwe_name
from patchai.pipeline import fix_finding, scan_project

settings = ui.settings()
st.header("Find and fix vulnerabilities")

findings: list[Finding] = st.session_state.get("findings", [])
strip = st.empty()
ui.pipeline_strip(1 if not findings else 2, placeholder=strip)

if st.button("🔍 Scan project", type="primary"):
    with st.spinner("Running Bandit and Semgrep..."):
        st.session_state.findings = scan_project(settings.project)
        st.session_state.results = {}
    st.rerun()

if not findings:
    ui.empty_state("No findings yet.", "Click **Scan project**. The demo shop has one bug of each of the seven types.")
    st.stop()

high = sum(f.severity == "high" for f in findings)
medium = sum(f.severity == "medium" for f in findings)
types = len({f.cwe for f in findings})
c1, c2, c3, c4 = st.columns(4)
c1.metric("Findings", len(findings))
c2.metric("High severity", high)
c3.metric("Medium", medium)
c4.metric("Of the 7 types", types)
if not ui.status()["semgrep"]:
    st.warning("Semgrep is not installed: path traversal and XSS cannot be detected.", icon="⚠️")

table = pd.DataFrame([{
    "Severity": f"{ui.SEVERITY_ICON[f.severity]} {f.severity}", "Type": f"{f.cwe} {cwe_name(f.cwe)}",
    "File": f"{f.file_path}:{f.start_line}", "Scanner": f"{f.scanner} {f.rule_id}", "Message": f.message,
} for f in findings])
event = st.dataframe(table, hide_index=True, width="stretch", key="findings_table",
                     on_select="rerun", selection_mode="single-row")
selected_rows = event.selection.rows if event and event.selection else []
finding = findings[selected_rows[0]] if selected_rows else findings[0]

left, right = st.columns(2)
context = None
with left:
    st.markdown("**The code the AI may rewrite**")
    try:
        context = get_context(settings.project, finding)
        st.caption(f"`{context.function_name or 'module-level statement'}` · lines "
                   f"{context.start_line}–{context.end_line} · flagged: "
                   f"`{(finding.code.splitlines()[0].strip() if finding.code else '')[:70]}`")
        st.code(context.source, language="python", line_numbers=True)
    except Exception as e:
        st.warning(f"Could not read the code: {e}")
with right:
    st.markdown("**What an attacker can do**")
    st.markdown(f"An attacker can **{ui.ATTACKER_CAN.get(finding.cwe or '', 'abuse this code')}**.")
    attack_files = security_test_files(settings.project, finding)
    if attack_files:
        with st.expander("The attack PatchAI will try"):
            for file in attack_files:
                st.caption(file.name)
                st.code(file.read_text(encoding="utf-8"), language="python")
    else:
        st.caption("This project has no attack test for this type, so that check will be skipped.")

results: dict[str, FixResult] = st.session_state.setdefault("results", {})
usable = settings.model is not None and ui.status()["ollama"]

if st.button("🛡️ Fix with AI", type="primary", disabled=not usable,
             help=None if usable else (ui.status()["problem"] or "No model is usable.")):
    with st.status(f"Fixing {cwe_name(finding.cwe)} with {settings.model}...", expanded=True) as box:
        def on_event(stage: str, message: str) -> None:
            step = ui.STAGE_STEP.get(stage, 4)
            ui.pipeline_strip(step if step else 4, failed=(stage == "error"), placeholder=strip)
            box.write(f"**{stage}** · {message}")

        result = fix_finding(settings.project, finding, model=settings.model, on_event=on_event)
        box.update(label=f"Done in {result.seconds:.0f}s: {result.verdict}",
                   state="complete" if result.verdict == "fixed" else "error", expanded=False)
    results[finding.id] = result
    st.session_state.pop(f"replay-{finding.id}", None)

replayed = False
if not usable:
    match = next((c for c in ui.load_cases().values()
                  if c["source"] == "handwritten" and c["cwe"] == finding.cwe and c["file"] == finding.file_path), None)
    rec = ui.recorded("v2", "patchai-3b", match["id"]) if match else None
    if rec is not None and context is not None and rec.context and rec.context.source == context.source:
        if st.button("▶️ Replay the recorded fix for this bug"):
            st.session_state[f"replay-{finding.id}"] = True
        if st.session_state.get(f"replay-{finding.id}"):
            st.info("Recorded on 2026-11-09 on the RTX 4060 laptop (run `v2`). **Not a live run.**",
                    icon=":material/history:")
            ui.show_result(rec)
            replayed = True
    elif rec is None:
        st.caption("No model is usable and no recorded fix is available for this finding "
                   "(the replay needs `eval/results/v2/full/`).")

result = results.get(finding.id)
if result is not None:
    if result.verdict == "fixed":
        ui.pipeline_strip(5, placeholder=strip)
    ui.show_result(result)
    st.subheader("Your decision")
    if result.verdict == "fixed":
        approve_col, reject_col = st.columns(2)
        if approve_col.button("✅ Approve and apply", type="primary", width="stretch"):
            try:
                target = review.approve(settings.project, result, settings.reviewer)
                st.toast(f"Applied to {target}. Rescanning...")
                st.session_state.findings = scan_project(settings.project)
                results.pop(finding.id, None)
                st.rerun()
            except review.ApprovalError as e:
                st.error(str(e))
        with reject_col:
            with st.form(f"reject-{finding.id}"):
                reason = st.selectbox("Reason", ["Wrong fix", "Breaks behaviour", "Too large a change",
                                                 "Not a real vulnerability", "Other"])
                note = st.text_input("Details (optional)")
                if st.form_submit_button("❌ Reject"):
                    review.reject(settings.project, result, f"{reason}: {note}" if note else reason,
                                  settings.reviewer)
                    results.pop(finding.id, None)
                    st.toast("Rejected and recorded.")
                    st.rerun()
    else:
        st.caption("This fix was not verified, so it cannot be applied. "
                   "You can reject it with a reason, or try another model.")
        with st.form(f"reject-{finding.id}"):
            reason = st.selectbox("Reason", ["Wrong fix", "Breaks behaviour", "Too large a change",
                                             "Not a real vulnerability", "Other"])
            note = st.text_input("Details (optional)")
            if st.form_submit_button("❌ Reject"):
                review.reject(settings.project, result, f"{reason}: {note}" if note else reason, settings.reviewer)
                results.pop(finding.id, None)
                st.toast("Rejected and recorded.")
                st.rerun()
elif not replayed and usable:
    st.caption("Click **Fix with AI** to run the pipeline on the selected finding.")
