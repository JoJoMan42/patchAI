"""Turns evaluation records into the numbers and tables we report.

One record = one model on one test case (written by eval/run_eval.py). Fields used here:
  model, case_id, cwe, verdict, attempts, seconds, changed_lines,
  first_attempt_fixed, format_failures, guard_failures, fake_fix, final_failure
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict

from patchai.models import FixResult
from patchai.patching import changed_line_count


def to_record(result: FixResult, case_id: str) -> dict:
    """Summarise one FixResult as one evaluation record."""
    attempts = result.attempts
    final = result.final

    def check(attempt, name):
        return next((c for c in attempt.checks if c.name == name), None)

    fake_fix = any(
        (rs := check(a, "rescan")) is not None and rs.passed
        and (st := check(a, "security_test")) is not None and not st.passed and not st.skipped
        for a in attempts
    )
    final_failure = None
    if final is not None:
        final_failure = next((c.name for c in final.checks if not c.passed), None)
    return {
        "case_id": case_id,
        "cwe": result.finding.cwe,
        "model": result.model,
        "verdict": result.verdict,
        "attempts": len(attempts),
        "seconds": result.seconds,
        "tokens_in": sum(a.tokens_in for a in attempts),
        "tokens_out": sum(a.tokens_out for a in attempts),
        "changed_lines": changed_line_count(result.diff) if result.verdict == "fixed" else 0,
        "first_attempt_fixed": bool(attempts) and attempts[0].passed,
        "format_failures": sum(1 for a in attempts if (c := check(a, "format")) and not c.passed),
        "guard_failures": sum(1 for a in attempts if (c := check(a, "guard")) and not c.passed),
        "fake_fix": fake_fix,
        "final_failure": final_failure,
        "error": result.error,
    }


MODEL_INFO: dict[str, tuple[str, str]] = {  # canonical id -> (label, colour), in display order
    "qwen2.5-coder:3b": ("Qwen2.5-Coder 3B (base)", "#eb6834"),
    "patchai-3b-v1": ("PatchAI-3B v1 (ours)", "#c9418f"),
    "patchai-3b": ("PatchAI-3B v2 (ours)", "#2a78d6"),
    "patchai-3b-dpo": ("PatchAI-3B v2 + DPO (ours)", "#eda100"),
    "qwen2.5-coder:7b": ("Qwen2.5-Coder 7B (base)", "#1baf7a"),
}

_UNKNOWN_COLOR = "#8a8984"
_NO_RAG = " [no RAG]"


def _split_suffix(model: str) -> tuple[str, str]:
    """Split off the ' [no RAG]' suffix that eval/run_eval.py --no-rag appends."""
    if model.endswith(_NO_RAG):
        return model[: -len(_NO_RAG)], _NO_RAG
    return model, ""


def canonical_model(model: str, run: str = "") -> str:
    """The one id a model is known by everywhere.

    The raw name `patchai-3b` means v1 in runs whose name starts with `v1`
    (v2 did not exist yet) and v2 everywhere else.
    """
    base, suffix = _split_suffix(model)
    if base == "patchai-3b" and run.startswith("v1"):
        base = "patchai-3b-v1"
    return base + suffix


def model_label(model: str, run: str = "") -> str:
    """The label charts and tables show. Unknown models keep their own name."""
    base, suffix = _split_suffix(canonical_model(model, run))
    label = MODEL_INFO.get(base, (base,))[0]
    return label + suffix


def model_color(model: str, run: str = "") -> str:
    """The one colour a model has in every chart. Unknown models are grey."""
    base, _ = _split_suffix(canonical_model(model, run))
    return MODEL_INFO.get(base, ("", _UNKNOWN_COLOR))[1]


def model_order(models: list[str], run: str = "") -> list[str]:
    """The given names sorted into display order (MODEL_INFO order, unknown ones last by name)."""
    known = list(MODEL_INFO)

    def key(model: str) -> tuple[int, str]:
        base, _ = _split_suffix(canonical_model(model, run))
        return (known.index(base), "") if base in known else (len(known), base)

    return sorted(models, key=key)


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval for a proportion. Better than ±1.96·SE for small samples."""
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - margin), min(1.0, centre + margin)


def summarize(records: list[dict]) -> dict[str, dict]:
    """Headline numbers for each model."""
    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_model[r["model"]].append(r)
    summary = {}
    for model, rows in by_model.items():
        n = len(rows)
        fixed = sum(r["verdict"] == "fixed" for r in rows)
        low, high = wilson_interval(fixed, n)
        fixed_rows = [r for r in rows if r["verdict"] == "fixed"]
        summary[model] = {
            "cases": n,
            "fixed": fixed,
            "fix_rate": fixed / n,
            "fix_rate_low": low,
            "fix_rate_high": high,
            "first_try_fix_rate": sum(bool(r["first_attempt_fixed"]) for r in rows) / n,
            "fake_fix_rate": sum(bool(r["fake_fix"]) for r in rows) / n,
            "format_error_rate": sum(r["format_failures"] for r in rows) / max(1, sum(r["attempts"] for r in rows)),
            "guard_rejection_rate": sum(r["guard_failures"] for r in rows) / max(1, sum(r["attempts"] for r in rows)),
            "cannot_fix_rate": sum(r["verdict"] in ("cannot_fix", "false_positive") for r in rows) / n,
            "avg_attempts": sum(r["attempts"] for r in rows) / n,
            "avg_seconds": sum(r["seconds"] for r in rows) / n,
            "avg_changed_lines": (sum(r["changed_lines"] for r in fixed_rows) / len(fixed_rows)) if fixed_rows else 0.0,
        }
    return summary


def fix_rate_by_cwe(records: list[dict]) -> dict[str, dict[str, float]]:
    """{model: {cwe: fix rate}}"""
    counts: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in records:
        cell = counts[r["model"]][r["cwe"]]
        cell[0] += r["verdict"] == "fixed"
        cell[1] += 1
    return {m: {c: fixed / n for c, (fixed, n) in sorted(cwes.items())} for m, cwes in counts.items()}


def failure_reasons(records: list[dict]) -> dict[str, Counter]:
    """{model: Counter of why unfixed cases failed (the first failing check of the last attempt)}"""
    reasons: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        if r["verdict"] == "fixed":
            continue
        reasons[r["model"]][r["final_failure"] or r["verdict"]] += 1
    return dict(reasons)
