"""The review app renders without Ollama: every page loads, data matches metrics, nothing
touches the tracked demo shop. Uses Streamlit's headless AppTest (no browser, no server)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from patchai import demo, metrics

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
ENTRY = APP / "review_app.py"
VIEWS = ["overview", "fix", "compare", "results", "cases", "training", "rag", "decisions"]


def shop_fingerprint() -> str:
    digest = hashlib.sha256()
    for file in sorted(demo.SOURCE.rglob("*")):
        if file.is_file() and "__pycache__" not in file.parts:
            digest.update(file.read_bytes())
    return digest.hexdigest()


@pytest.fixture(autouse=True)
def app_on_path(monkeypatch):
    """Views import `ui` and `charts`; Streamlit puts app/ on the path, the tests must too."""
    monkeypatch.syspath_prepend(str(APP))


def run_view(name: str) -> AppTest:
    return AppTest.from_file(str(APP / "views" / f"{name}.py"), default_timeout=30).run()


def test_entry_point_runs():
    at = AppTest.from_file(str(ENTRY), default_timeout=30).run()
    assert not at.exception


@pytest.mark.parametrize("view", VIEWS)
def test_each_view_runs_alone(view):
    before = shop_fingerprint()
    at = run_view(view)
    assert not at.exception, f"{view}: {at.exception[0].value if at.exception else ''}"
    assert shop_fingerprint() == before, f"{view} modified the tracked demo shop"


def test_results_view_matches_metrics():
    records = [__import__("json").loads(line) for line in
               (ROOT / "eval" / "results" / "v2" / "results.jsonl").read_text(encoding="utf-8").splitlines()
               if line.strip()]
    for r in records:
        r["model"] = metrics.canonical_model(r["model"], "v2")
    summary = metrics.summarize(records)

    at = run_view("results")
    assert not at.exception
    at.selectbox[0].select("v2").run()
    assert not at.exception
    shown = {m.label: m.value for m in at.metric}
    for model, s in summary.items():
        label = metrics.model_label(model)
        assert shown.get(label) == f"{s['fix_rate']:.0%}", f"{label}: {shown.get(label)} != {s['fix_rate']:.0%}"


def test_fix_view_without_ollama_never_crashes():
    at = run_view("fix")
    assert not at.exception
    # No Ollama in tests: the page shows its empty state (no scan yet) and no crash.
    assert at.info or at.warning or at.error


def test_case_explorer_empty_state_when_full_logs_missing(tmp_path, monkeypatch):
    # Point the app at a run without a full/ folder by checking a run name that has none locally.
    at = run_view("cases")
    assert not at.exception
    runs_without_full = [r.parent.name for r in (ROOT / "eval" / "results").glob("*/results.jsonl")
                         if not (r.parent / "full").is_dir()]
    if runs_without_full:
        at.selectbox[0].select(runs_without_full[0]).run()
        assert not at.exception
        assert at.info  # the empty_state box
