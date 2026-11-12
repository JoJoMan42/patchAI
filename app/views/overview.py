"""Overview: what PatchAI is, the headline numbers, and the pre-demo checklist."""

from __future__ import annotations

import streamlit as st

import ui
from patchai import demo, metrics
from patchai.config import get_config

st.title("🛡️ PatchAI")
st.markdown("**An AI that fixes security vulnerabilities in Python code — and proves every fix.**")
c1, c2, c3 = st.columns(3)
c1.markdown(":material/wifi_off: **Runs offline** — local models, local data")
c2.markdown(":material/model_training: **Fine-tuned 3B model** — trained by us, on our own data")
c3.markdown(":material/verified: **Every fix is proven** — tests, a real attack, and a re-scan")

st.graphviz_chart("""
digraph {
  rankdir=LR; bgcolor=transparent;
  node [shape=box, style="rounded,filled", fillcolor="#eef4fb", color="#2a78d6",
        fontname="sans-serif", fontsize=11, margin="0.18,0.12"];
  Scanner [label="1 · Scanner\\nBandit + Semgrep"];
  RAG [label="2 · RAG\\nguides · code · past fixes"];
  Model [label="3 · Our model\\nfine-tuned Qwen 3B"];
  Checks [label="4 · Checks\\nguard · tests · attack · re-scan"];
  Human [label="5 · Human\\napprove or reject"];
  Scanner -> RAG -> Model -> Checks -> Human;
  Checks -> Model [style=dashed, color="#eb6834", fontcolor="#eb6834",
                   label="failed: previous fix + exact error, max 3"];
}
""")

# Headline numbers from the newest run that contains our v2 model — never typed in by hand.
run = next((r for r in ui.runs() if any(rec["model"] == "patchai-3b" for rec in ui.load_records(r))), None)
if run:
    records = ui.load_records(run)
    summary = metrics.summarize(records)
    story = [m for m in ("qwen2.5-coder:3b", "patchai-3b-v1", "patchai-3b", "qwen2.5-coder:7b") if m in summary]
    base = summary.get("qwen2.5-coder:3b")
    columns = st.columns(len(story))
    for column, m in zip(columns, story):
        s = summary[m]
        delta = None
        if m.startswith("patchai") and base:
            delta = f"{(s['fix_rate'] - base['fix_rate']) * 100:+.0f} pts vs base 3B"
        column.metric(metrics.model_label(m), f"{s['fix_rate']:.0%}", delta=delta,
                      help=f"{s['fixed']}/{s['cases']} fixed · 95% interval "
                           f"{s['fix_rate_low']:.0%}–{s['fix_rate_high']:.0%} · run `{run}`")
    ours, big = summary.get("patchai-3b"), summary.get("qwen2.5-coder:7b")
    if ours and base and big:
        st.markdown(
            f"Fine-tuning took the 3B model from **{base['fix_rate']:.0%}** to **{ours['fix_rate']:.0%}** on our "
            f"{ours['cases']}-case benchmark, close to the 7B model's {big['fix_rate']:.0%}, at about a third of "
            f"the time per fix ({ours['avg_seconds']:.0f} s vs {big['avg_seconds']:.0f} s).")
else:
    ui.empty_state("No evaluation results found.", "Run `python eval/run_eval.py` or pull the repo's results.")

st.subheader("What each page shows")
st.markdown("""
- **Fix** — scan the demo shop, watch the model fix a bug live, and approve or reject it
- **Compare** — the same bug through the base model, our v1, our v2 and the 7B
- **Results** — the full evaluation: fix rates with intervals, per-type heat map, failures
- **Case explorer** — replay any recorded benchmark case, attempt by attempt
- **Training** — loss curves, what changed from v1 to v2, real CVE fixes
- **RAG** — search the knowledge base and see every ranking stage
- **Decisions** — the log of every approve and reject
""")

st.subheader("Before a demo")
s = ui.status()
shop_clean = True
try:
    copy = demo.demo_project()
    import filecmp
    comparison = filecmp.dircmp(demo.SOURCE, copy, ignore=["__pycache__", ".pytest_cache"])
    shop_clean = not comparison.diff_files
except Exception:
    shop_clean = False
embedder = get_config()["rag"]["embedder"]
checks = [
    (s["ollama"], "Ollama is running", "Start it with `ollama serve`."),
    (s["fine_tuned"], "The fine-tuned model is installed",
     s["problem"] or "Register it with `python training/export.py`."),
    (s["semgrep"], "Semgrep is installed", "Run `pip install semgrep` (path traversal and XSS need it)."),
    (embedder != "hash", "Real embeddings are configured", "The hash fallback gives weaker search results."),
    (bool(ui.runs()), "Recorded evaluation runs are present", "Pull the repo or run the evaluation."),
    (shop_clean, "The demo shop copy is in its original state", "Click **Reset demo shop** in the sidebar."),
]
for ok, text, hint in checks:
    st.markdown(f"{'✅' if ok else '❌'} {text}" + ("" if ok else f" — {hint}"))
