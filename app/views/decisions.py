"""Decisions: the log of every approve and reject, with the evidence for each."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import ui
from patchai import review
from patchai.config import path

st.header("Decisions log")

decisions = review.load_decisions()
if not decisions:
    ui.empty_state("No decisions yet.", "Approve or reject a fix on the **Fix** page and it lands here.")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Approved", sum(d["decision"] == "approved" for d in decisions))
c2.metric("Rejected", sum(d["decision"] == "rejected" for d in decisions))
c3.metric("Reviewers", len({d.get("reviewer") for d in decisions}))

columns = ["time", "reviewer", "decision", "reason", "cwe", "file", "model", "attempts"]
table = pd.DataFrame(decisions)
table = table[[c for c in columns if c in table.columns]].iloc[::-1].reset_index(drop=True)
event = st.dataframe(table, hide_index=True, width="stretch", key="decisions_table",
                     on_select="rerun", selection_mode="single-row")
rows = event.selection.rows if event and event.selection else []
if rows:
    chosen = decisions[::-1][rows[0]]
    st.markdown(f"**{chosen['decision'].title()}** by `{chosen.get('reviewer', '?')}` at {chosen.get('time', '?')}"
                + (f" — {chosen['reason']}" if chosen.get("reason") else ""))
    if chosen.get("diff"):
        st.code(chosen["diff"], language="diff")

log = path("decisions")
if log.exists():
    st.download_button("Download the log (JSONL)", log.read_bytes(), file_name="decisions.jsonl")
