"""Altair chart builders for the review app. One function per chart.

Every function takes plain data plus the model order/labels/colours from
patchai.metrics, and returns a chart with a tooltip on every mark.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

from patchai import metrics
from patchai.models import CWE_NAMES

INK, INK_2 = "#0b0b0b", "#52514e"
FAILURE_LABELS = {"format": "Unreadable answer", "guard": "Blocked by guard", "tests": "Broke tests",
                  "security_test": "Attack still works", "rescan": "Scanner still flags it",
                  "cannot_fix": "Model gave up", "false_positive": "Model gave up"}
FAILURE_COLORS = {"Unreadable answer": "#8a8984", "Blocked by guard": "#eda100", "Broke tests": "#eb6834",
                  "Attack still works": "#c0392b", "Scanner still flags it": "#2a78d6", "Model gave up": "#1baf7a"}
OUTCOME_COLORS = {"Fixed on first try": "#1a7f4e", "Fixed after a retry": "#7cc7a0", "Not fixed": "#e3e2de"}


def _scale(models: list[str]) -> alt.Scale:
    return alt.Scale(domain=[metrics.model_label(m) for m in models],
                     range=[metrics.model_color(m) for m in models])


def _order(models: list[str]) -> list[str]:
    return [metrics.model_label(m) for m in metrics.model_order(models)]


def fix_rate(summary: dict[str, dict]) -> alt.Chart:
    """Horizontal bars with 95% Wilson intervals and a value label per bar."""
    models = metrics.model_order(list(summary))
    df = pd.DataFrame([{
        "model": metrics.model_label(m), "rate": s["fix_rate"], "low": s["fix_rate_low"],
        "high": s["fix_rate_high"],
        "label": f"{s['fix_rate']:.0%} ({s['fixed']}/{s['cases']})",
    } for m, s in ((m, summary[m]) for m in models)])
    base = alt.Chart(df).encode(
        y=alt.Y("model:N", sort=_order(models), title=None),
        tooltip=[alt.Tooltip("model:N", title="Model"),
                 alt.Tooltip("rate:Q", format=".0%", title="Fix rate"),
                 alt.Tooltip("low:Q", format=".0%", title="95% low"),
                 alt.Tooltip("high:Q", format=".0%", title="95% high")],
    )
    bars = base.mark_bar(height=22, cornerRadiusEnd=4).encode(
        x=alt.X("rate:Q", axis=alt.Axis(format=".0%", title="fix rate"), scale=alt.Scale(domain=[0, 1])),
        color=alt.Color("model:N", scale=_scale(models), legend=None),
    )
    error = base.mark_rule(color=INK_2, strokeWidth=1.6).encode(x="low:Q", x2="high:Q")
    text = base.mark_text(align="left", dx=4, color=INK, fontWeight="bold").encode(
        x="high:Q", text="label:N")
    return (bars + error + text).properties(height=44 * len(df), title="Vulnerabilities truly fixed")


def speed_accuracy(summary: dict[str, dict]) -> alt.Chart:
    """Scatter: average seconds per fix against fix rate, one labelled point per model."""
    models = metrics.model_order(list(summary))
    df = pd.DataFrame([{
        "model": metrics.model_label(m), "seconds": summary[m]["avg_seconds"],
        "rate": summary[m]["fix_rate"],
    } for m in models])
    base = alt.Chart(df).encode(
        x=alt.X("seconds:Q", title="average seconds per fix", scale=alt.Scale(zero=True)),
        y=alt.Y("rate:Q", axis=alt.Axis(format=".0%", title="fix rate"), scale=alt.Scale(domain=[0, 1])),
        tooltip=[alt.Tooltip("model:N", title="Model"), alt.Tooltip("seconds:Q", format=".1f", title="s / fix"),
                 alt.Tooltip("rate:Q", format=".0%", title="Fix rate")],
    )
    points = base.mark_circle(size=220, opacity=1).encode(
        color=alt.Color("model:N", scale=_scale(models), legend=None))
    labels = base.mark_text(dy=-16, color=INK, fontWeight="bold").encode(text="model:N")
    return (points + labels).properties(height=320, title="Accuracy against speed (up and left is better)")


def cwe_heatmap(by_cwe: dict[str, dict[str, float]], counts: dict[str, int]) -> alt.Chart:
    """Fix rate per vulnerability type: rows = types, columns = models, the value in every cell."""
    models = metrics.model_order(list(by_cwe))
    rows = []
    for m in models:
        for cwe, rate in by_cwe[m].items():
            rows.append({"model": metrics.model_label(m),
                         "type": f"{CWE_NAMES.get(cwe, cwe)} ({cwe}, n={counts.get(cwe, '?')})",
                         "rate": rate, "label": f"{rate:.0%}"})
    df = pd.DataFrame(rows)
    types = sorted(df["type"].unique())
    base = alt.Chart(df).encode(
        x=alt.X("model:N", sort=_order(models), title=None, axis=alt.Axis(labelAngle=-20)),
        y=alt.Y("type:N", sort=types, title=None),
        tooltip=[alt.Tooltip("model:N", title="Model"), alt.Tooltip("type:N", title="Type"),
                 alt.Tooltip("rate:Q", format=".0%", title="Fix rate")],
    )
    cells = base.mark_rect(stroke="#ffffff", strokeWidth=2).encode(
        color=alt.Color("rate:Q", scale=alt.Scale(scheme="blues", domain=[0, 1]),
                        legend=alt.Legend(format=".0%", title="fix rate")))
    text = base.mark_text(fontWeight="bold").encode(
        text="label:N",
        color=alt.condition(alt.datum.rate > 0.65, alt.value("#ffffff"), alt.value(INK)))
    return (cells + text).properties(height=32 * len(types) + 20, title="Fix rate per vulnerability type")


def first_try(summary: dict[str, dict]) -> alt.Chart:
    """Stacked horizontal bars: fixed on the first try (solid) and after a retry (lighter)."""
    models = metrics.model_order(list(summary))
    rows = []
    for m in models:
        s = summary[m]
        first = s["first_try_fix_rate"]
        retry = max(0.0, s["fix_rate"] - first)
        rows.append({"model": metrics.model_label(m), "part": "First try", "rate": first, "opacity": 1.0})
        rows.append({"model": metrics.model_label(m), "part": "After a retry", "rate": retry, "opacity": 0.45})
    df = pd.DataFrame(rows)
    return alt.Chart(df).mark_bar(height=22).encode(
        y=alt.Y("model:N", sort=_order(models), title=None),
        x=alt.X("rate:Q", axis=alt.Axis(format=".0%", title="share of all cases"), scale=alt.Scale(domain=[0, 1])),
        color=alt.Color("model:N", scale=_scale(models), legend=None),
        opacity=alt.Opacity("part:N", scale=alt.Scale(domain=["First try", "After a retry"], range=[1.0, 0.45]),
                            legend=alt.Legend(title=None, orient="bottom")),
        order=alt.Order("opacity:Q", sort="descending"),
        tooltip=[alt.Tooltip("model:N", title="Model"), alt.Tooltip("part:N", title="Fixed"),
                 alt.Tooltip("rate:Q", format=".0%", title="Share")],
    ).properties(height=44 * len(models), title="Fixed on the first try, or only after a retry")


def quality(summary: dict[str, dict]) -> alt.Chart:
    """Grouped bars: the mistakes the pipeline caught (lower is better)."""
    measures = [("fake_fix_rate", "Fake fixes (per case)"),
                ("guard_rejection_rate", "Blocked by guard (per attempt)"),
                ("format_error_rate", "Unreadable answers (per attempt)")]
    models = metrics.model_order(list(summary))
    rows = [{"model": metrics.model_label(m), "measure": label, "rate": summary[m][key],
             "label": f"{summary[m][key]:.0%}"}
            for m in models for key, label in measures]
    df = pd.DataFrame(rows)
    bars = alt.Chart(df).mark_bar(width=26, cornerRadiusEnd=3).encode(
        x=alt.X("model:N", sort=_order(models), title=None, axis=alt.Axis(labelAngle=-20)),
        y=alt.Y("rate:Q", axis=alt.Axis(format=".0%", title=None), scale=alt.Scale(domain=[0, 0.5])),
        color=alt.Color("model:N", scale=_scale(models), legend=None),
        tooltip=[alt.Tooltip("model:N", title="Model"), alt.Tooltip("measure:N", title="Measure"),
                 alt.Tooltip("rate:Q", format=".0%", title="Rate")],
    )
    text = bars.mark_text(dy=-8, color=INK).encode(text="label:N")
    return (bars + text).facet(column=alt.Column("measure:N", title=None)).properties(
        title="Mistakes the pipeline caught (lower is better)")


def failures(reasons: dict[str, dict[str, int]]) -> alt.Chart:
    """Stacked horizontal bars: why the unfixed cases failed on their last attempt."""
    models = metrics.model_order(list(reasons))
    rows = []
    for m in models:
        for reason, count in reasons[m].items():
            label = FAILURE_LABELS.get(reason, reason)
            rows.append({"model": metrics.model_label(m), "reason": label, "count": count})
    df = pd.DataFrame(rows).groupby(["model", "reason"], as_index=False).sum()
    reason_order = [r for r in dict.fromkeys(FAILURE_LABELS.values()) if r in set(df["reason"])]
    return alt.Chart(df).mark_bar(height=22).encode(
        y=alt.Y("model:N", sort=_order(models), title=None),
        x=alt.X("count:Q", title="cases"),
        color=alt.Color("reason:N", scale=alt.Scale(domain=reason_order,
                                                    range=[FAILURE_COLORS[r] for r in reason_order]),
                        legend=alt.Legend(title=None, orient="bottom", columns=3)),
        order=alt.Order("reason:N"),
        tooltip=[alt.Tooltip("model:N", title="Model"), alt.Tooltip("reason:N", title="Why it failed"),
                 alt.Tooltip("count:Q", title="Cases")],
    ).properties(height=44 * len(models), title="Why the unfixed cases failed (last attempt)")


def case_grid(records: list[dict]) -> alt.Chart:
    """One row per case, one column per model, coloured by outcome."""
    models = metrics.model_order(sorted({r["model"] for r in records}))
    rows = []
    for r in records:
        if r["verdict"] == "fixed":
            outcome = "Fixed on first try" if r.get("first_attempt_fixed") else "Fixed after a retry"
        else:
            outcome = "Not fixed"
        failed = r.get("final_failure")
        rows.append({"case": r["case_id"], "model": metrics.model_label(r["model"]), "outcome": outcome,
                     "type": CWE_NAMES.get(r["cwe"], r["cwe"]),
                     "failed_check": FAILURE_LABELS.get(failed, failed) if failed else "—"})
    df = pd.DataFrame(rows)
    case_order = sorted(df["case"].unique())
    return alt.Chart(df).mark_rect(stroke="#ffffff", strokeWidth=1.5).encode(
        x=alt.X("model:N", sort=_order(models), title=None, axis=alt.Axis(labelAngle=-20, orient="top")),
        y=alt.Y("case:N", sort=case_order, title=None, axis=alt.Axis(labelFontSize=9)),
        color=alt.Color("outcome:N",
                        scale=alt.Scale(domain=list(OUTCOME_COLORS), range=list(OUTCOME_COLORS.values())),
                        legend=alt.Legend(title=None, orient="bottom")),
        tooltip=[alt.Tooltip("case:N", title="Case"), alt.Tooltip("type:N", title="Type"),
                 alt.Tooltip("model:N", title="Model"), alt.Tooltip("outcome:N", title="Outcome"),
                 alt.Tooltip("failed_check:N", title="Failed check")],
    ).properties(height=13 * len(case_order), title="Every case, every model")


def v1_to_v2(by_cwe: dict[str, dict[str, float]], counts: dict[str, int]) -> alt.Chart:
    """A slope per vulnerability type from the v1 value to the v2 value (same run)."""
    rows = []
    for version, model in (("v1", "patchai-3b-v1"), ("v2", "patchai-3b")):
        for cwe, rate in by_cwe.get(model, {}).items():
            rows.append({"version": version, "type": f"{CWE_NAMES.get(cwe, cwe)}", "rate": rate,
                         "label": f"{rate:.0%}"})
    df = pd.DataFrame(rows)
    base = alt.Chart(df).encode(
        x=alt.X("version:N", sort=["v1", "v2"], title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("rate:Q", axis=alt.Axis(format=".0%", title="fix rate"), scale=alt.Scale(domain=[0, 1])),
        detail="type:N",
        tooltip=[alt.Tooltip("type:N", title="Type"), alt.Tooltip("version:N", title="Model"),
                 alt.Tooltip("rate:Q", format=".0%", title="Fix rate")],
    )
    lines = base.mark_line(color=INK_2, strokeWidth=1.6, point=True)
    labels = alt.Chart(df[df["version"] == "v2"]).mark_text(align="left", dx=8, fontSize=10).encode(
        x=alt.X("version:N", sort=["v1", "v2"]), y="rate:Q", text="type:N", detail="type:N")
    return (lines + labels).properties(height=320, width=260, title="Per type: our v1 → our v2 (run v2)")


def loss_curves(losses: dict[str, dict]) -> alt.Chart:
    """Training and validation loss for the given runs ({run: loss.json dict})."""
    rows = []
    for run, loss in losses.items():
        for kind in ("train", "validation"):
            for step, value in loss.get(kind, []):
                rows.append({"run": run, "kind": kind, "step": step, "loss": value})
    df = pd.DataFrame(rows)
    return alt.Chart(df).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("step:Q", title="training step"),
        y=alt.Y("loss:Q", scale=alt.Scale(type="log"), title="loss (log scale)"),
        color=alt.Color("run:N", scale=alt.Scale(domain=["v1", "v2"], range=["#c9418f", "#2a78d6"]),
                        legend=alt.Legend(title=None, orient="bottom")),
        strokeDash=alt.StrokeDash("kind:N", legend=alt.Legend(title=None, orient="bottom")),
        tooltip=[alt.Tooltip("run:N"), alt.Tooltip("kind:N"), alt.Tooltip("step:Q"),
                 alt.Tooltip("loss:Q", format=".4f")],
    ).properties(height=300, title="Training loss, v1 and v2")


def data_composition(v1_by_cwe: dict[str, int], v2_by_cwe: dict[str, int]) -> alt.Chart:
    """Training examples per vulnerability type, v1 against v2."""
    rows = [{"dataset": name, "type": CWE_NAMES.get(cwe, cwe), "examples": n}
            for name, data in (("v1", v1_by_cwe), ("v2", v2_by_cwe)) for cwe, n in data.items()]
    df = pd.DataFrame(rows)
    return alt.Chart(df).mark_bar(cornerRadiusEnd=3).encode(
        y=alt.Y("type:N", title=None),
        x=alt.X("examples:Q", title="training examples"),
        yOffset="dataset:N",
        color=alt.Color("dataset:N", scale=alt.Scale(domain=["v1", "v2"], range=["#c9418f", "#2a78d6"]),
                        legend=alt.Legend(title=None, orient="bottom")),
        tooltip=["dataset:N", "type:N", "examples:Q"],
    ).properties(height=260, title="Training data per type: v1 was skewed, v2 has fixed quotas")


def cve_funnel(filtered: dict[str, int]) -> alt.Chart:
    """Why CVEfixes candidates were dropped; the kept bar stands out."""
    rows = [{"reason": ("Kept" if k == "kept" else k.replace("_", " ")), "count": v,
             "kept": k == "kept"} for k, v in sorted(filtered.items(), key=lambda kv: -kv[1])]
    df = pd.DataFrame(rows)
    bars = alt.Chart(df).mark_bar(height=16, cornerRadiusEnd=3).encode(
        y=alt.Y("reason:N", sort="-x", title=None),
        x=alt.X("count:Q", title="candidate functions"),
        color=alt.condition(alt.datum.kept, alt.value("#1a7f4e"), alt.value("#b9b8b4")),
        tooltip=["reason:N", "count:Q"],
    )
    text = bars.mark_text(align="left", dx=4, color=INK_2).encode(text="count:Q")
    return (bars + text).properties(height=24 * len(df), title=f"Real CVE fixes: strict filters keep {filtered.get('kept', 0)} of {sum(filtered.values())}")
