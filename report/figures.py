"""Figures for the PatchAI project report (run with the project's .venv python)."""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).parent / "fig"
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "training"))
from patchai import metrics  # noqa: E402

# Same validated categorical palette as eval/report.py; colour follows the model in every figure.
BLUE, ORANGE, GREEN, AMBER, PINK, DKGREEN = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#c9418f", "#008300"
INK, INK2, GRID, SURF = "#1a1a1a", "#52514e", "#e3e2de", "#ffffff"
ARROW = "\u2192"
DOT = "\u00b7"
TIMES = "\u00d7"
# Model names, colours and order come from patchai/metrics.py, so every figure matches the app.
label, color = metrics.model_label, metrics.model_color
CWES = ["CWE-89", "CWE-78", "CWE-22", "CWE-79", "CWE-798", "CWE-327", "CWE-502"]
CWE_SHORT = {"CWE-89": "SQL\ninjection", "CWE-78": "Command\ninjection", "CWE-22": "Path\ntraversal",
             "CWE-79": "XSS", "CWE-798": "Hard-coded\nsecret", "CWE-327": "Weak\ncrypto",
             "CWE-502": "Unsafe\ndeserial."}

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
                     "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.dpi": 220})


def grid_y(ax, pct=True):
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    if pct:
        ax.set_ylim(0, 1.1)
        ax.set_yticks([0, .25, .5, .75, 1])
        ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])


def load(run):
    """A run's records, with every model name turned into its canonical id (v1 runs: patchai-3b = v1)."""
    rows = [json.loads(line) for line in open(ROOT / "eval" / "results" / run / "results.jsonl", encoding="utf-8")]
    for r in rows:
        r["model"] = metrics.canonical_model(r["model"], run)
    return rows


fair, original, v2 = load("v1_rescored"), load("v1"), load("v2")
S, S0, S2 = metrics.summarize(fair), metrics.summarize(original), metrics.summarize(v2)
ORDER = metrics.model_order(list(S))      # the three models of the v1 runs
ORDER2 = metrics.model_order(list(S2))    # the four models of run v2


# ------------------------------------------------------------------ diagrams
def box(ax, x, y, w, h, lines, fc="#eef4fb", ec=BLUE, fs=9):
    """A rounded box: first line bold, the rest smaller. Spacing is in points, so it works at any size."""
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.006,rounding_size=0.015", fc=fc, ec=ec, lw=1.3))
    cx, cy = x + w / 2, y + h / 2
    step = fs * 1.45
    top = (len(lines) - 1) * step / 2
    ax.annotate(lines[0], (cx, cy), xytext=(0, top), textcoords="offset points", ha="center", va="center",
                fontsize=fs + 0.5, weight="bold", color=INK)
    for i, line in enumerate(lines[1:], start=1):
        ax.annotate(line, (cx, cy), xytext=(0, top - i * step), textcoords="offset points", ha="center",
                    va="center", fontsize=fs - 0.5, color=INK2)


def arrow(ax, a, b, color=INK2, ls="-", rad=0.0, lw=1.3):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=12, color=color, lw=lw, linestyle=ls,
                                 connectionstyle=f"arc3,rad={rad}"))


def canvas(w, h):
    fig = plt.figure(figsize=(w, h))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def fig_architecture():
    fig, ax = canvas(7.8, 8.4)
    x, w, h = 0.255, 0.41, 0.092
    stages = [
        (0.875, ["Input: Python project", "source files, unit tests, security (attack) tests"], "#f4f4f2", INK2),
        (0.745, ["1  Detection", "Bandit rules + custom Semgrep taint rules", f"{ARROW} Finding (CWE, file, line, rule)"], "#eef4fb", BLUE),
        (0.615, ["Context extraction", "AST: enclosing function, imports,", "called functions"], "#eef4fb", BLUE),
        (0.485, ["2  Retrieval (hybrid RAG)", f"dense + BM25 {ARROW} RRF {ARROW} cross-encoder", "6 chunks: guides, project code, past fixes"], "#eef4fb", BLUE),
        (0.355, ["3  Generation", "PatchAI-3B (QLoRA fine-tuned) via Ollama", "JSON: status, fixed_code, explanation"], "#e9f7f1", GREEN),
        (0.205, ["4  Verification (on a temporary copy)", f"safety guard {ARROW} project tests {ARROW}", f"attack test {ARROW} re-scan"], "#fff6e5", AMBER),
        (0.035, ["5  Human review", f"Streamlit app {DOT} VS Code extension", f"approve / reject {ARROW} decision log"], "#f4f4f2", INK2),
    ]
    for y, lines, fc, ec in stages:
        box(ax, x, y, w, h, lines, fc=fc, ec=ec)
    for (y1, *_), (y2, *_) in zip(stages, stages[1:]):
        arrow(ax, (x + w / 2, y1), (x + w / 2, y2 + h))
    ax.text(x + w / 2 + 0.012, 0.165, "all checks passed", fontsize=8, color=INK2, va="center")
    lx = x + w + 0.035
    ax.plot([x + w, lx, lx], [0.205 + h / 2, 0.205 + h / 2, 0.38], color=ORANGE, lw=1.3, ls="--")
    arrow(ax, (lx, 0.38), (x + w, 0.38), color=ORANGE)
    ax.text(lx + 0.012, 0.29, "check failed:\nprevious fix +\nexact error\n(max 3 attempts)", fontsize=7.5,
            color=ORANGE, va="center")
    kx, kw, kh = 0.01, 0.2, 0.072
    ax.text(kx + kw / 2, 0.64, "Knowledge base\n(NumPy vectors + BM25)", ha="center", fontsize=8, color=INK2, weight="bold")
    for y, t, sub in [(0.545, "Security guides", "7, one per CWE"), (0.46, "Past fixes", "35 before/after pairs"),
                      (0.375, "Project code index", "functions + call graph")]:
        box(ax, kx, y, kw, kh, [t, sub], fc="#ffffff", ec=INK2, fs=8)
        arrow(ax, (kx + kw, y + kh / 2), (x, 0.485 + h / 2 + (y - 0.46) * 0.35), lw=0.9)
    tx, tw, th = 0.785, 0.205, 0.072
    ax.text(tx + tw / 2, 0.79, "Offline training\n(RTX 4060 laptop, 8 GB)", ha="center", fontsize=8, color=GREEN, weight="bold")
    items = [(0.69, "Synthetic pairs", "25 code families"), (0.60, "Real CVE fixes", "CVEfixes, 21 kept"),
             (0.51, "QLoRA SFT (+ DPO)", f"Unsloth {DOT} TRL {DOT} PEFT"), (0.42, "GGUF export", "4-bit, served by Ollama")]
    for y, t, sub in items:
        box(ax, tx, y, tw, th, [t, sub], fc="#ffffff", ec=GREEN, fs=8)
    for (y1, *_), (y2, *_) in zip(items, items[1:]):
        arrow(ax, (tx + tw / 2, y1), (tx + tw / 2, y2 + th), color=GREEN, lw=1)
    arrow(ax, (tx, 0.42 + th / 2), (x + w, 0.355 + h - 0.02), color=GREEN, lw=1.2)
    fig.savefig(OUT / "architecture.png", bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def fig_rag():
    fig, ax = canvas(7.6, 3.2)
    box(ax, 0.01, 0.36, 0.15, 0.3, ["Query", "finding message", "+ vulnerable", "function"], fc="#f4f4f2", ec=INK2, fs=8)
    box(ax, 0.22, 0.64, 0.17, 0.25, ["Dense search", "BGE-small-en-v1.5", "(384-d, cosine)"], fs=8)
    box(ax, 0.22, 0.13, 0.17, 0.25, ["Sparse search", "BM25 (Okapi)", "exact identifiers"], fs=8)
    box(ax, 0.45, 0.36, 0.15, 0.3, ["Fusion", "Reciprocal Rank", "Fusion (k = 60)", "20 candidates"], fs=8)
    box(ax, 0.655, 0.36, 0.15, 0.3, ["Re-ranking", "cross-encoder", "MiniLM-L-6", "(MS MARCO)"], fs=8)
    for y, t, sub in [(0.66, "Guides", "top 2, same CWE"), (0.4, "Project code", "top 2, callees first"),
                      (0.14, "Past fixes", "top 2, same CWE")]:
        box(ax, 0.855, y, 0.14, 0.2, [t, sub], fc="#ffffff", ec=INK2, fs=8)
        arrow(ax, (0.805, 0.51), (0.855, y + 0.1), lw=1)
    arrow(ax, (0.16, 0.56), (0.22, 0.74))
    arrow(ax, (0.16, 0.46), (0.22, 0.27))
    arrow(ax, (0.39, 0.76), (0.45, 0.58))
    arrow(ax, (0.39, 0.25), (0.45, 0.44))
    arrow(ax, (0.60, 0.51), (0.655, 0.51))
    ax.text(0.5, 0.02, "Each of the three collections is searched separately; the six chunks are wrapped in <reference> tags in the prompt.",
            ha="center", fontsize=7.5, color=INK2)
    fig.savefig(OUT / "rag.png", bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def fig_method():
    fig, ax = canvas(7.6, 2.3)
    steps = [(["Build", "pipeline, data,", "benchmark"], "#f4f4f2", INK2),
             (["Train v1", "QLoRA SFT", "2,500 examples"], "#e9f7f1", GREEN),
             (["Evaluate", f"3 models {TIMES} 53", "validated cases"], "#eef4fb", BLUE),
             (["Analyse", "read every attempt", "in the logs"], "#fff6e5", AMBER),
             (["Improve", "data, prompt,", "scoring, real data"], "#fdeef4", PINK),
             (["Train v2", "re-evaluate", "4 models"], "#e9f7f1", GREEN)]
    w, gap = 0.14, 0.024
    for i, (lines, fc, ec) in enumerate(steps):
        x = 0.01 + i * (w + gap)
        box(ax, x, 0.36, w, 0.5, lines, fc=fc, ec=ec, fs=8)
        if i:
            arrow(ax, (x - gap, 0.61), (x, 0.61))
    a = 0.01 + 4 * (w + gap) + w / 2
    b = 0.01 + 2 * (w + gap) + w / 2
    arrow(ax, (a, 0.36), (b, 0.36), color=INK2, ls="--", rad=-0.35, lw=1)
    ax.text((a + b) / 2, 0.02, "iterate: the error analysis drives the next version", ha="center", fontsize=8, color=INK2)
    fig.savefig(OUT / "method.png", bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


# ------------------------------------------------------------------ data charts
def fig_data_composition():
    """Training examples per type, v1 against v2, read from the two training manifests."""
    fp_type = {"fp_allowlisted_table": "CWE-89", "fp_constant_command": "CWE-78", "fp_not_a_secret": "CWE-798"}

    def vulnerable(run):
        info = json.load(open(ROOT / "training" / "runs" / run / "manifest.json"))["dataset_info"]
        counts = dict(info["by_cwe"])
        for family, n in info["by_family"].items():
            if family in fp_type:
                counts[fp_type[family]] -= n
        false_alarms = sum(n for family, n in info["by_family"].items() if family.startswith("fp_"))
        return counts, false_alarms, sum(info["by_cwe"].values())

    v1, fp1, n1 = vulnerable("v1")
    v2_all, fp2, n2 = vulnerable("v2")
    real = json.load(open(ROOT / "data" / "real_fixes" / "cvefixes_info.json"))["by_cwe"]
    v2_syn = {c: v2_all.get(c, 0) - real.get(c, 0) for c in CWES}
    fig, ax = plt.subplots(figsize=(7.6, 3.4))
    xs = list(range(len(CWES)))
    w = 0.36
    ax.bar([x - w / 2 for x in xs], [v1.get(c, 0) for c in CWES], w, color="#e3a6c8", edgecolor=SURF, lw=1.5,
           label="v1 vulnerable examples")
    ax.bar([x + w / 2 for x in xs], [v2_syn[c] for c in CWES], w, color=BLUE, edgecolor=SURF, lw=1.5,
           label="v2 synthetic examples")
    ax.bar([x + w / 2 for x in xs], [real.get(c, 0) * 2 for c in CWES], w, bottom=[v2_syn[c] for c in CWES],
           color=DKGREEN, edgecolor=SURF, lw=1.5, label=f"v2 real CVE fixes ({TIMES}2)")
    for x, c in zip(xs, CWES):
        ax.text(x - w / 2, v1.get(c, 0) + 8, str(v1.get(c, 0)), ha="center", fontsize=7.5, color=INK2)
        ax.text(x + w / 2, v2_syn[c] + real.get(c, 0) * 2 + 8, str(v2_all.get(c, 0)), ha="center", fontsize=7.5,
                color=INK)
    ax.set_xticks(xs)
    ax.set_xticklabels([CWE_SHORT[c] for c in CWES], fontsize=8.5)
    ax.set_ylabel("training examples")
    grid_y(ax, pct=False)
    ax.set_ylim(0, 420)
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper left", bbox_to_anchor=(0, 1.16))
    ax.text(1.0, 1.0, f"false alarms: v1 {fp1} ({fp1 / n1:.1%}) {ARROW} v2 {fp2} ({fp2 / n2:.1%})",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=8, color=INK2)
    fig.tight_layout()
    fig.savefig(OUT / "data_composition.png", bbox_inches="tight")
    plt.close(fig)


def fig_cvefixes():
    info = json.load(open(ROOT / "data" / "real_fixes" / "cvefixes_info.json"))
    labels = {"function_not_changed_by_fix": "finding outside the changed function",
              "fixed_version_still_flagged": "fixed version still flagged",
              "not_python3": "not parseable as Python 3",
              "not_in_a_function": "finding at module level",
              "cve_limit": "more than 3 examples from one CVE",
              "change_too_large": "change > 30 lines or function > 80 lines",
              "signature_changed": "function signature changed",
              "function_renamed_or_removed": "function renamed or removed",
              "still_uses_a_shell": "fix still uses shell=True",
              "loader_not_fully_safe": "fix uses yaml.full_load",
              "parameters_not_a_tuple": "SQL parameters not a tuple",
              "kept": "kept for training"}
    items = sorted(((labels[k], v) for k, v in info["filtered"].items()), key=lambda kv: (kv[0] != "kept for training", kv[1]))
    names, vals = zip(*items)
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    ax.barh(names, vals, color=[DKGREEN if n == "kept for training" else "#b7b5ae" for n in names], edgecolor=SURF, height=0.7)
    for i, v in enumerate(vals):
        ax.text(v + 1, i, str(v), va="center", fontsize=8, color=INK)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0, labelsize=8)
    ax.set_xlabel("scanner findings in the 334 rebuilt files (162 CVE fixes)")
    fig.tight_layout()
    fig.savefig(OUT / "cvefixes_filter.png", bbox_inches="tight")
    plt.close(fig)


def fig_fix_rate(summary=None, order=None, name="fix_rate.png"):
    summary, order = summary or S, order or ORDER
    fig, ax = plt.subplots(figsize=(1.7 * len(order) + 1.3, 3.4))
    for i, m in enumerate(order):
        s = summary[m]
        ax.bar(i, s["fix_rate"], 0.55, color=color(m), edgecolor=SURF)
        ax.errorbar(i, s["fix_rate"], yerr=[[s["fix_rate"] - s["fix_rate_low"]], [s["fix_rate_high"] - s["fix_rate"]]],
                    color=INK2, capsize=5, lw=1.2)
        ax.text(i, s["fix_rate_high"] + 0.03, f"{s['fix_rate']:.0%}  ({s['fixed']}/{s['cases']})", ha="center",
                fontsize=9.5, weight="bold", color=INK)
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([label(m).replace(" (", "\n(") for m in order], fontsize=9)
    ax.set_ylabel("verified fix rate")
    grid_y(ax)
    fig.tight_layout()
    fig.savefig(OUT / name, bbox_inches="tight")
    plt.close(fig)


def fig_by_cwe(records=None, order=None, name="by_cwe.png"):
    records, order = records or fair, order or ORDER
    by = metrics.fix_rate_by_cwe(records)
    fig, ax = plt.subplots(figsize=(7.6, 3.5))
    w = 0.8 / len(order)
    for j, m in enumerate(order):
        xs = [i + (j - (len(order) - 1) / 2) * w for i in range(len(CWES))]
        ys = [by[m].get(c, 0) for c in CWES]
        ax.bar(xs, ys, w, color=color(m), edgecolor=SURF, lw=1.2, label=label(m))
        for x, y in zip(xs, ys):
            ax.text(x, y + 0.02, f"{y:.0%}", ha="center", fontsize=5.6 if len(order) > 3 else 6.3, color=INK2)
    ax.set_xticks(range(len(CWES)))
    ax.set_xticklabels([CWE_SHORT[c] for c in CWES], fontsize=8.5)
    grid_y(ax)
    ax.legend(frameon=False, fontsize=8, ncol=min(4, len(order)), loc="upper left", bbox_to_anchor=(0, 1.14))
    fig.tight_layout()
    fig.savefig(OUT / name, bbox_inches="tight")
    plt.close(fig)


def fig_rescoring():
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    for i, m in enumerate(ORDER):
        a, b = S0[m]["fix_rate"], S[m]["fix_rate"]
        col = color(m)
        ax.plot([a, b], [i, i], color=GRID, lw=6, solid_capstyle="round", zorder=1)
        ax.scatter([a], [i], s=70, facecolor=SURF, edgecolor=col, lw=2, zorder=2)
        ax.scatter([b], [i], s=70, color=col, zorder=3)
        ax.text(min(a, b) - 0.025, i, f"{a:.0%}", ha="right", va="center", fontsize=8.5, color=INK2)
        ax.text(max(a, b) + 0.025, i, f"{b:.0%}" if b != a else "unchanged", ha="left", va="center", fontsize=8.5,
                weight="bold" if b != a else "normal", color=INK if b != a else INK2)
    ax.set_yticks(range(len(ORDER)))
    ax.set_yticklabels([label(m) for m in ORDER], fontsize=9)
    ax.set_xlim(0.25, 1.08)
    ax.set_xticks([.25, .5, .75, 1])
    ax.set_xticklabels(["25%", "50%", "75%", "100%"])
    ax.xaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.set_ylim(-0.6, len(ORDER) - 0.4)
    ax.scatter([], [], s=50, facecolor=SURF, edgecolor=INK2, label="original scoring")
    ax.scatter([], [], s=50, color=INK2, label="corrected parser (re-scored)")
    ax.legend(frameon=False, fontsize=8, ncol=2, loc="upper left", bbox_to_anchor=(0, 1.22))
    fig.tight_layout()
    fig.savefig(OUT / "rescoring.png", bbox_inches="tight")
    plt.close(fig)


def fig_attempts(summary=None, order=None, name="attempts.png"):
    summary, order = summary or S, order or ORDER
    fig, ax = plt.subplots(figsize=(6.4, 0.75 * len(order) + 0.6))
    for i, m in enumerate(order):
        s = summary[m]
        first, later = s["first_try_fix_rate"], s["fix_rate"] - s["first_try_fix_rate"]
        col = color(m)
        ax.barh(i, first, 0.55, color=col, edgecolor=SURF)
        ax.barh(i, later, 0.55, left=first, color=col, alpha=0.35, edgecolor=SURF, hatch="///")
        ax.text(first / 2, i, f"{first:.0%}", ha="center", va="center", fontsize=8.5, color="white", weight="bold")
        ax.text(first + later + 0.015, i, f"+{later:.0%} after retry" if later > 0.005 else "no gain from retries",
                va="center", fontsize=8.5, color=INK)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([label(m) for m in order], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.2)
    ax.set_xticks([0, .25, .5, .75, 1])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.xaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.set_xlabel("test cases fixed: solid = first attempt, hatched = attempt 2 or 3")
    fig.tight_layout()
    fig.savefig(OUT / name, bbox_inches="tight")
    plt.close(fig)


def fig_failures(records=None, order=None, name="failures.png"):
    records, order = records or fair, order or ORDER
    reasons = metrics.failure_reasons(records)
    kinds = [("tests", "broke project tests"), ("guard", "blocked by safety guard"),
             ("security_test", "attack still works"), ("rescan", "scanner still flags it")]
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    h = 0.8 / len(order)
    for j, m in enumerate(order):
        ys = [i + (j - (len(order) - 1) / 2) * h for i in range(len(kinds))]
        vals = [reasons.get(m, {}).get(k, 0) for k, _ in kinds]
        ax.barh(ys, vals, h, color=color(m), edgecolor=SURF, label=label(m))
        for y, v in zip(ys, vals):
            ax.text(v + 0.3, y, str(v), va="center", fontsize=7.5, color=INK2)
    ax.set_yticks(range(len(kinds)))
    ax.set_yticklabels([lbl for _, lbl in kinds], fontsize=9)
    ax.invert_yaxis()
    ax.xaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.set_xlabel("unfixed test cases, by the check that failed on the last attempt")
    ax.legend(frameon=False, fontsize=8, ncol=2 if len(order) > 3 else 3, loc="lower left",
              bbox_to_anchor=(-0.35, 1.0))
    fig.tight_layout()
    fig.savefig(OUT / name, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------ v2 figures (run v2, four models)
def fig_speed_accuracy_v2():
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    for m in ORDER2:
        s = S2[m]
        ax.scatter(s["avg_seconds"], s["fix_rate"], s=140, color=color(m), edgecolor=SURF, lw=2, zorder=3)
        ax.annotate(f"{label(m)}\n{s['fix_rate']:.0%} {DOT} {s['avg_seconds']:.1f} s per fix",
                    (s["avg_seconds"], s["fix_rate"]), xytext=(9, -3), textcoords="offset points",
                    fontsize=8, color=INK, va="top")
    ax.set_xlim(0, max(S2[m]["avg_seconds"] for m in ORDER2) * 1.6)
    ax.set_xlabel("average seconds per fix (left is faster)")
    ax.set_ylabel("verified fix rate")
    grid_y(ax)
    ax.xaxis.grid(True, color=GRID, lw=0.8)
    fig.tight_layout()
    fig.savefig(OUT / "speed_accuracy_v2.png", bbox_inches="tight")
    plt.close(fig)


def fig_v1_to_v2():
    by = metrics.fix_rate_by_cwe(v2)
    a_model, b_model = "patchai-3b-v1", "patchai-3b"
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    for i, c in enumerate(CWES):
        a, b = by[a_model].get(c, 0), by[b_model].get(c, 0)
        ax.plot([a, b], [i, i], color=GRID, lw=6, solid_capstyle="round", zorder=1)
        ax.scatter([a], [i], s=70, color=color(a_model), zorder=2)
        ax.scatter([b], [i], s=70, color=color(b_model), zorder=3)
        change = b - a
        ax.text(1.07, i, f"{change * 100:+.0f} pts" if abs(change) > 0.005 else "same", va="center", fontsize=8.5,
                weight="bold" if change > 0.005 else "normal", color=INK if change > 0.005 else INK2)
    ax.set_yticks(range(len(CWES)))
    ax.set_yticklabels([CWE_SHORT[c].replace("\n", " ") for c in CWES], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(-0.05, 1.17)
    ax.set_xticks([0, .25, .5, .75, 1])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.xaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.scatter([], [], s=50, color=color(a_model), label=label(a_model))
    ax.scatter([], [], s=50, color=color(b_model), label=label(b_model))
    ax.legend(frameon=False, fontsize=8, ncol=2, loc="upper left", bbox_to_anchor=(0, 1.13))
    ax.set_xlabel("fix rate per type in run v2 (same cases, same day)")
    fig.tight_layout()
    fig.savefig(OUT / "v1_to_v2.png", bbox_inches="tight")
    plt.close(fig)


def fig_loss_v1_v2():
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    for run, model in (("v1", "patchai-3b-v1"), ("v2", "patchai-3b")):
        loss = json.load(open(ROOT / "training" / "runs" / run / "loss.json"))
        for kind, style in (("train", "-"), ("validation", "--")):
            steps, values = zip(*loss[kind])
            ax.plot(steps, values, style, color=color(model), lw=1.8,
                    marker="o" if kind == "validation" else None, ms=3.5,
                    label=f"{run} {'training' if kind == 'train' else 'validation'}")
    ax.set_yscale("log")
    ax.set_xlabel("training step")
    ax.set_ylabel("loss (log scale)")
    ax.yaxis.grid(True, color=GRID, lw=0.8, which="both")
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.legend(frameon=False, fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(OUT / "loss_v1_v2.png", bbox_inches="tight")
    plt.close(fig)


def figs_v2():
    fig_fix_rate(S2, ORDER2, "fix_rate_v2.png")
    fig_by_cwe(v2, ORDER2, "by_cwe_v2.png")
    fig_attempts(S2, ORDER2, "attempts_v2.png")
    fig_failures(v2, ORDER2, "failures_v2.png")
    fig_speed_accuracy_v2()
    fig_v1_to_v2()
    fig_loss_v1_v2()


for f in (fig_architecture, fig_rag, fig_method, fig_data_composition, fig_cvefixes, fig_fix_rate, fig_by_cwe,
          fig_rescoring, fig_attempts, fig_failures, figs_v2):
    f()
print("written:", sorted(p.name for p in OUT.glob("*.png")))
