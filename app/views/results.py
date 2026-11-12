"""Results: the evaluation dashboard, built from the recorded runs."""

from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

import charts
import ui
from patchai import metrics
from patchai.config import ROOT

st.header("Evaluation results")

all_runs = ui.runs()
if not all_runs:
    ui.empty_state("No evaluation results yet.", "Run `python eval/run_eval.py` (see eval/README.md).")
    st.stop()

run = st.selectbox("Evaluation run", all_runs, index=0)
manifest = ui.run_manifest(run)
records = ui.load_records(run)
st.caption(f"Run `{run}` · started {manifest.get('started', '?')[:10]} · {manifest.get('cases', '?')} cases "
           f"· prompt {manifest.get('prompt_version', '?')} · commit `{manifest.get('git_commit', '?')[:7]}`")

summary = metrics.summarize(records)
models = metrics.model_order(list(summary))

columns = st.columns(len(models))
for column, m in zip(columns, models):
    s = summary[m]
    column.metric(metrics.model_label(m), f"{s['fix_rate']:.0%}",
                  help=f"{s['fixed']}/{s['cases']} · 95% interval {s['fix_rate_low']:.0%}–{s['fix_rate_high']:.0%}")

left, right = st.columns(2)
with left:
    st.altair_chart(charts.fix_rate(summary), width="stretch",
                    alt="Fix rate per model with 95% intervals; our v2 is close behind the 7B")
    st.caption("Fixed = project tests, the attack test and the re-scan all pass. Error bars: 95% Wilson interval.")
with right:
    st.altair_chart(charts.speed_accuracy(summary), width="stretch",
                    alt="Fix rate against seconds per fix; our v2 is nearly as accurate as the 7B at a third of the time")
    st.caption("The headline: our 3B is almost as accurate as the 7B at about a third of the time per fix.")

counts = Counter(r["cwe"] for r in records if r["model"] == models[0])
st.altair_chart(charts.cwe_heatmap(metrics.fix_rate_by_cwe(records), dict(counts)), width="stretch",
                alt="Heat map of fix rate per vulnerability type and model")
st.caption(f"Each cell is the share of that type's cases the model truly fixed "
           f"({min(counts.values())}–{max(counts.values())} cases per type).")

left, right = st.columns(2)
with left:
    st.altair_chart(charts.first_try(summary), width="stretch",
                    alt="Share fixed on the first try against after a retry, per model")
    st.caption("The solid part passed on attempt 1; the lighter part needed the error fed back.")
with right:
    st.altair_chart(charts.failures(metrics.failure_reasons(records)), width="stretch",
                    alt="Why unfixed cases failed, per model")
    st.caption("The first failing check of the last attempt, for every case that was not fixed.")

st.altair_chart(charts.quality(summary), width="stretch",
                alt="Fake fixes, guard blocks and unreadable answers per model")
st.caption("A *fake fix* fooled the scanner while the attack still worked — the attack test caught it.")

st.subheader("Every case")
st.altair_chart(charts.case_grid(records), width="stretch",
                alt="Grid of every benchmark case against every model, coloured by outcome")
case_ids = sorted({r["case_id"] for r in records})
chosen_case = st.selectbox("Open one case in the explorer", case_ids)
if st.button("Open in the case explorer"):
    st.session_state.selected_case = (run, models[-1], chosen_case)
    st.switch_page("views/cases.py")

st.subheader("Hand-written demo-shop cases")
shop_records = [r for r in records if r.get("source") != "generated"]
if shop_records:
    table = pd.DataFrame([{
        "Model": metrics.model_label(m),
        "Fixed": f"{sum(r['verdict'] == 'fixed' for r in shop_records if r['model'] == m)}"
                 f"/{sum(1 for r in shop_records if r['model'] == m)}",
    } for m in models])
    st.dataframe(table, hide_index=True)
    st.caption("The 7 hand-written cases from the demo shop, reported separately from the generated ones.")

if "patchai-3b-v1" in summary and "patchai-3b" in summary:
    st.subheader("From v1 to v2")
    left, right = st.columns(2)
    with left:
        st.altair_chart(charts.v1_to_v2(metrics.fix_rate_by_cwe(records), dict(counts)), width="stretch",
                        alt="Per-type fix rate slopes from our v1 model to our v2 model")
    with right:
        st.markdown("""**What we changed after v1's error analysis** (training/README.md):

| v1 problem | v2 change |
| --- | --- |
| 0% on hard-coded secrets | fixes use `os.environ.get("X", "")`, which never crashes |
| 0/4 on key derivation | new PBKDF2 key-stretching pattern in the training data |
| Retries repeated the same wrong fix | the retry prompt now shows the previous fix and the real error |
| 25% of data was one false-alarm pattern | fixed quotas per type, exactly 8% false alarms |
| Synthetic data only | 21 real CVE fixes from the CVEfixes dataset |
""")

st.subheader("Read this honestly")
st.markdown("""
- With 53 cases, the 95% intervals of **our v2 (75–93%) and the base 7B (80–96%) overlap** — we cannot claim to beat it.
- Run-to-run noise is about **±7 points** (the same v1 model scored 79% in one run and 72% in another), so only compare models **inside one run**.
- Generated cases come from **templates we wrote**; the 7 hand-written shop cases are reported separately.
- The attack test proves that **the attacks we wrote** fail — not that every possible attack fails.
""")

with st.expander("Download the data and the report charts"):
    for name in ("summary.csv", "by_cwe.csv"):
        file = ROOT / "eval" / "results" / run / name
        if file.exists():
            st.download_button(f"Download {name}", file.read_bytes(), file_name=f"{run}_{name}", key=f"dl-{name}")
    for png in sorted((ROOT / "eval" / "results" / run).glob("*.png")):
        st.image(str(png), caption=png.stem)
