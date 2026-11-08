"""Turns an evaluation run into tables and charts for the report.

  python eval/report.py --run <run-name>       # default: the newest run

Writes into eval/results/<run-name>/:
  summary.csv      every measure per model (fix rate with 95% interval, fake fixes, ...)
  by_cwe.csv       fix rate per model and vulnerability type
  results.md       the same tables in Markdown, ready to paste into the report
  fix_rate.png     the headline chart: fix rate per model with 95% intervals
  by_cwe.png       fix rate per vulnerability type
  quality.png      format errors, guard rejections and fake fixes per model
  failures.png     why the unfixed cases failed
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from patchai import metrics  # noqa: E402
from patchai.models import CWE_NAMES  # noqa: E402

# Validated categorical palette (fixed order) and recessive ink, on a light surface.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"
FAILURE_ORDER = ["format", "guard", "tests", "security_test", "rescan", "cannot_fix"]
FAILURE_LABELS = {"format": "Unreadable answer", "guard": "Blocked by guard", "tests": "Broke tests",
                  "security_test": "Attack still works", "rescan": "Scanner still flags it",
                  "cannot_fix": "Model gave up"}


def model_colors(models: list[str]) -> dict[str, str]:
    """Colour follows the model, never its rank: the same model gets the same colour in every chart."""
    order = sorted(models, key=lambda m: (not m.startswith("patchai"), m))
    return {m: SERIES[i % len(SERIES)] for i, m in enumerate(order)}


def style(ax, title: str, ylabel: str = "") -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=INK, fontsize=12, fontweight="bold", pad=12)
    ax.set_ylabel(ylabel, color=INK_2)
    ax.tick_params(colors=INK_2, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def percent_axis(ax) -> None:
    ax.set_ylim(0, 1.08)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])


def chart_fix_rate(summary: dict, colors: dict, out: Path) -> None:
    models = list(colors)
    fig, ax = plt.subplots(figsize=(max(7, 1.9 * len(models)), 4.2), facecolor=SURFACE)
    rates = [summary[m]["fix_rate"] for m in models]
    low = [summary[m]["fix_rate"] - summary[m]["fix_rate_low"] for m in models]
    high = [summary[m]["fix_rate_high"] - summary[m]["fix_rate"] for m in models]
    ax.bar(models, rates, width=0.5, color=[colors[m] for m in models], edgecolor=SURFACE, linewidth=2)
    ax.errorbar(models, rates, yerr=[low, high], fmt="none", ecolor=INK_2, elinewidth=1.2, capsize=5)
    for i, m in enumerate(models):
        ax.text(i, summary[m]["fix_rate_high"] + 0.03, f"{rates[i]:.0%}", ha="center", color=INK, fontsize=11, fontweight="bold")
    style(ax, "Vulnerabilities truly fixed", "fix rate")
    percent_axis(ax)
    n = summary[models[0]]["cases"]
    ax.text(0, -0.17, f"Fixed = tests, attack test and re-scan all pass · n = {n} test cases per model · "
                      "error bars: 95% Wilson interval",
            transform=ax.transAxes, color=INK_2, fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "fix_rate.png", dpi=160)
    plt.close(fig)


def chart_by_cwe(by_cwe: dict, colors: dict, out: Path) -> None:
    models = list(colors)
    cwes = sorted({c for m in models for c in by_cwe.get(m, {})}, key=lambda c: int(c.split("-")[1]))
    width = 0.8 / len(models)
    fig, ax = plt.subplots(figsize=(10, 4.5), facecolor=SURFACE)
    for i, m in enumerate(models):
        xs = [x + (i - (len(models) - 1) / 2) * width for x in range(len(cwes))]
        ys = [by_cwe.get(m, {}).get(c, 0) for c in cwes]
        ax.bar(xs, ys, width=width, color=colors[m], edgecolor=SURFACE, linewidth=2, label=m)
        for x, y in zip(xs, ys):
            ax.text(x, y + 0.02, f"{y:.0%}", ha="center", fontsize=7, color=INK_2)
    ax.set_xticks(range(len(cwes)))
    ax.set_xticklabels([textwrap.fill(CWE_NAMES.get(c, c), 14, break_long_words=False) + f"\n{c}" for c in cwes],
                       fontsize=8)
    style(ax, "Fix rate per vulnerability type", "fix rate")
    percent_axis(ax)
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(0, -0.27), ncol=len(models), labelcolor=INK_2)
    fig.tight_layout()
    fig.savefig(out / "by_cwe.png", dpi=160)
    plt.close(fig)


def chart_quality(summary: dict, colors: dict, out: Path) -> None:
    measures = [("format_error_rate", "Unreadable answers\n(per attempt)"),
                ("guard_rejection_rate", "Blocked by safety guard\n(per attempt)"),
                ("fake_fix_rate", "Fake fixes: scanner fooled,\nattack still works (per case)")]
    models = list(colors)
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.8), facecolor=SURFACE, sharey=True)
    for ax, (key, title) in zip(axes, measures):
        values = [summary[m][key] for m in models]
        ax.bar(range(len(models)), values, width=0.6, color=[colors[m] for m in models], edgecolor=SURFACE, linewidth=2)
        for i, v in enumerate(values):
            ax.text(i, v + 0.02, f"{v:.0%}", ha="center", fontsize=9, color=INK)
        ax.set_xticks(range(len(models)))
        ax.set_xticklabels(models, rotation=20, ha="right", fontsize=8)
        style(ax, title)
        ax.title.set_fontsize(10)
        percent_axis(ax)
    fig.suptitle("Mistakes the pipeline caught (lower is better)", x=0.01, ha="left", color=INK, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out / "quality.png", dpi=160)
    plt.close(fig)


def chart_failures(reasons: dict, colors: dict, out: Path) -> None:
    models = [m for m in colors if m in reasons]
    if not models:
        return
    fig, ax = plt.subplots(figsize=(9, 0.8 + 0.7 * len(models)), facecolor=SURFACE)
    left = [0] * len(models)
    for k, reason in enumerate(FAILURE_ORDER):
        counts = [reasons[m].get(reason, 0) + (reasons[m].get("false_positive", 0) if reason == "cannot_fix" else 0)
                  for m in models]
        if not any(counts):
            continue
        ax.barh(models, counts, left=left, color=SERIES[k], edgecolor=SURFACE, linewidth=2, label=FAILURE_LABELS[reason])
        for i, c in enumerate(counts):
            if c:
                ax.text(left[i] + c / 2, i, str(c), ha="center", va="center", fontsize=8, color=INK)
        left = [a + b for a, b in zip(left, counts)]
    style(ax, "Why the unfixed cases failed (last attempt)")
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.yaxis.grid(False)
    ax.set_xlabel("cases", color=INK_2)
    ax.invert_yaxis()
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(0, -0.25), ncol=3, fontsize=8, labelcolor=INK_2)
    fig.tight_layout()
    fig.savefig(out / "failures.png", dpi=160)
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", default=None, help="run name under eval/results (default: newest)")
    args = p.parse_args()
    runs = sorted((ROOT / "eval" / "results").glob("*/results.jsonl"), key=lambda f: f.stat().st_mtime)
    if not runs:
        sys.exit("No results yet. Run: python eval/run_eval.py")
    results = (ROOT / "eval" / "results" / args.run / "results.jsonl") if args.run else runs[-1]
    out = results.parent
    records = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines() if line.strip()]

    summary = metrics.summarize(records)
    by_cwe = metrics.fix_rate_by_cwe(records)
    reasons = metrics.failure_reasons(records)
    colors = model_colors(list(summary))

    table = pd.DataFrame(summary).T.loc[list(colors)]
    table.to_csv(out / "summary.csv")
    cwe_table = pd.DataFrame(by_cwe).loc[:, list(colors)]
    cwe_table.to_csv(out / "by_cwe.csv")

    chart_fix_rate(summary, colors, out)
    chart_by_cwe(by_cwe, colors, out)
    chart_quality(summary, colors, out)
    chart_failures(reasons, colors, out)

    def shop(model: str) -> str:  # the hand-written demo-shop cases, reported separately
        rows = [r for r in records if r["model"] == model and r.get("source") != "generated"]
        return f"{sum(r['verdict'] == 'fixed' for r in rows)}/{len(rows)}" if rows else "-"

    lines = ["# Evaluation results", "", f"Run `{out.name}`, {len(records)} runs.", "",
             "| Model | Fix rate | 95% interval | Demo shop | First try | Fake fixes | Unreadable | Guard blocked | Avg attempts | Avg time |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for m, s in table.iterrows():
        lines.append(f"| {m} | **{s.fix_rate:.0%}** ({int(s.fixed)}/{int(s.cases)}) | {s.fix_rate_low:.0%}–{s.fix_rate_high:.0%} | "
                     f"{shop(m)} | {s.first_try_fix_rate:.0%} | {s.fake_fix_rate:.0%} | {s.format_error_rate:.0%} | "
                     f"{s.guard_rejection_rate:.0%} | {s.avg_attempts:.1f} | {s.avg_seconds:.0f}s |")
    lines += ["", "## Fix rate per vulnerability type", "", "| Type | " + " | ".join(colors) + " |",
              "| --- | " + " | ".join("---" for _ in colors) + " |"]
    for cwe, row in cwe_table.iterrows():
        lines.append(f"| {cwe} {CWE_NAMES.get(cwe, '')} | " + " | ".join(f"{v:.0%}" for v in row) + " |")
    lines += ["", "![Fix rate](fix_rate.png)", "", "![By type](by_cwe.png)", "", "![Quality](quality.png)", "",
              "![Failures](failures.png)", ""]
    (out / "results.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:6 + len(table)]))
    print(f"\nCharts and tables written to {out}")


if __name__ == "__main__":
    main()
