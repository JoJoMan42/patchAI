"""Training: how the model was trained, what the data looks like, and what changed from v1 to v2."""

from __future__ import annotations

import json
import sys

import pandas as pd
import streamlit as st

import charts
import ui
from patchai.config import ROOT

st.header("How the model was trained")

v2_manifest, v2_loss = ui.load_training_run("v2")
v1_manifest, v1_loss = ui.load_training_run("v1")
if not v2_manifest:
    ui.empty_state("No training manifest found.", "Pull the repo: `training/runs/v2/manifest.json` is tracked.")
    st.stop()

s = v2_manifest.get("settings", {})
info = v2_manifest.get("dataset_info", {})
c1, c2, c3, c4 = st.columns(4)
c1.metric("Base model", "Qwen2.5-Coder 3B", help=v2_manifest.get("base_model", ""))
c2.metric("Method", f"QLoRA r={s.get('lora_r')}", help=f"alpha {s.get('lora_alpha')}, 4-bit base")
c3.metric("Epochs · LR", f"{s.get('epochs')} · {s.get('lr')}")
c4.metric("Training time", f"{v2_manifest.get('minutes', 0):.0f} min", help="On one RTX 4060 laptop GPU (8 GB)")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Training examples", f"{v2_manifest.get('train_examples', 0):,}")
c2.metric("Validation examples", f"{v2_manifest.get('val_examples', 0):,}")
val = v2_loss.get("validation", [])
c3.metric("Final validation loss", f"{val[-1][1]:.4f}" if val else "?",
          help="v1 finished at 0.0342; lower is better")
c4.metric("Real CVE fixes", info.get("by_source", {}).get("cvefixes", 0),
          help=f"from {len(info.get('real_world_cves', []))} CVEs (CVEfixes dataset)")

if v1_loss or v2_loss:
    losses = {name: loss for name, loss in (("v1", v1_loss), ("v2", v2_loss)) if loss}
    st.altair_chart(charts.loss_curves(losses), width="stretch",
                    alt="Training and validation loss curves for v1 and v2 on a log scale")
    st.caption("Log scale: the first step is about 1.09 and everything after is below 0.1. "
               "Dashed = validation. v2 ends slightly lower than v1.")

st.subheader("The training data, v1 against v2")
v1_cwe = v1_manifest.get("dataset_info", {}).get("by_cwe", {})
v2_cwe = info.get("by_cwe", {})
if v1_cwe and v2_cwe:
    st.altair_chart(charts.data_composition(v1_cwe, v2_cwe), width="stretch",
                    alt="Training examples per vulnerability type: v1 was dominated by SQL injection, v2 is balanced")
c1, c2, c3 = st.columns(3)
c1.metric("False-alarm examples", "643 → 200", help="v1's generator bug let one false-alarm pattern fill 25% of the data; v2 caps it at 8%")
c2.metric("Command-injection examples", f"{v1_cwe.get('CWE-78', 0)} → {v2_cwe.get('CWE-78', 0)}")
c3.metric("Real-world examples", f"0 → {info.get('by_source', {}).get('cvefixes', 0)}")

st.subheader("Real CVE fixes (CVEfixes)")
info_file = ROOT / "data" / "real_fixes" / "cvefixes_info.json"
jsonl = ROOT / "data" / "real_fixes" / "cvefixes.jsonl"
if info_file.exists():
    cve_info = json.loads(info_file.read_text(encoding="utf-8"))
    st.altair_chart(charts.cve_funnel(cve_info.get("filtered", {})), width="stretch",
                    alt="Filter funnel: most CVEfixes candidates are dropped, 21 strict examples are kept")
    st.caption("A candidate is kept only when our scanners flag the vulnerable version, stop flagging the "
               "fixed version, and the fix is one our pipeline could accept.")
if jsonl.exists():
    examples = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    table = pd.DataFrame([{
        "CVE": e["cve_id"], "Repository": e["repo"], "Type": e.get("cwe_label", e.get("cwe", "")),
        "Function": e.get("function", ""),
    } for e in examples])
    st.dataframe(table, hide_index=True, width="stretch",
                 column_config={"CVE": st.column_config.TextColumn(help="Look any id up at nvd.nist.gov")})
    chosen = st.selectbox("See one real fix", [e["cve_id"] + " · " + e.get("function", "") for e in examples])
    example = examples[[e["cve_id"] + " · " + e.get("function", "") for e in examples].index(chosen)]
    st.markdown(f"[{example['cve_id']} on nvd.nist.gov](https://nvd.nist.gov/vuln/detail/{example['cve_id']})")
    left, right = st.columns(2)
    left.caption("Vulnerable (reconstructed from the fixing commit)")
    left.code(example.get("vulnerable", ""), language="python")
    right.caption("Fixed (the project's own fix)")
    right.code(example.get("fixed", ""), language="python")

st.subheader("A synthetic training example")
if st.button("Draw one at random"):
    sys.path.insert(0, str(ROOT / "training"))
    import random

    import synth

    pair = random.choice(synth.generate(40, seed=random.randint(0, 10_000)))
    st.caption(f"{pair.cwe} · pattern family `{pair.family}` · status `{pair.status}`")
    left, right = st.columns(2)
    left.caption("Vulnerable")
    left.code(pair.vulnerable, language="python")
    right.caption("The fix the model learns")
    right.code(pair.fixed, language="python")
    st.markdown(f"**Explanation it learns to give:** {pair.explanation}")

st.subheader("Settings and why")
st.markdown("""
| Setting | Value | Why |
| --- | --- | --- |
| Method | QLoRA (4-bit base, LoRA rank 16, alpha 32) | fits an 8 GB laptop GPU |
| Epochs · learning rate | 2 · 2e-4 | more epochs overfit the templates |
| Max sequence length | 4,096 tokens | covers the 95th-percentile prompt |
| Seed | 42 | the whole dataset build and split is reproducible |
""")

st.subheader("How the model is served")
st.markdown("GGUF export, 4-bit (Q4_K_M), about **1.9 GB**, served by **Ollama** · temperature 0.1 · "
            "context 8,192 tokens · the answer is **forced into the `FixProposal` JSON shape**, "
            "so it always parses.")
