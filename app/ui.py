"""Shared widgets, wording and cached data loaders for the review app's pages."""

from __future__ import annotations

import getpass
import json
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from patchai import demo, llm, metrics
from patchai.config import ROOT, get_config
from patchai.models import Finding, FixResult, cwe_name
from patchai.scan import semgrep_available

RESULTS = ROOT / "eval" / "results"

# ---- wording (section 4.2 of docs/IMPLEMENTATION_PLAN.md; the extension copies it) ----

VERDICT_STYLE = {
    "fixed": ("success", "✅ Fixed and verified"),
    "failed": ("error", "❌ Not fixed"),
    "cannot_fix": ("warning", "🤷 The model could not fix this safely"),
    "false_positive": ("info", "🔎 The model says this is a false alarm"),
}
CHECK_LABELS = {
    "format": "Readable answer",
    "guard": "Safety guard",
    "tests": "Project tests",
    "security_test": "Attack test",
    "rescan": "Re-scan",
}
CHECK_ORDER = ["format", "guard", "tests", "security_test", "rescan"]
SOURCE_LABELS = {"guide": "📘 Security guide", "code": "🧩 Project code", "past_fix": "🩹 Similar past fix"}
SEVERITY_ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}
ATTACKER_CAN = {  # from the README's vulnerability table
    "CWE-89": "read or change the database",
    "CWE-78": "run commands on the server",
    "CWE-22": "read files they shouldn't (`../../secrets`)",
    "CWE-79": "run scripts in other users' browsers",
    "CWE-798": "steal passwords written in the code",
    "CWE-327": "break or predict hashes and tokens",
    "CWE-502": "run code by uploading crafted data",
}
STEPS = ["Scanner", "RAG", "Our model", "Checks", "Human"]
STAGE_STEP = {"context": 2, "retrieve": 2, "generate": 3, "guard": 4, "tests": 4,
              "security_test": 4, "rescan": 4, "retry": 3, "done": 5, "error": 0}


# ---- cached data loaders ----

def _mtime(file: Path) -> float:
    return file.stat().st_mtime if file.exists() else 0.0


@st.cache_data(show_spinner=False)
def _runs(stamp: tuple) -> list[str]:
    found = []
    for manifest in RESULTS.glob("*/manifest.json"):
        try:
            found.append((json.loads(manifest.read_text(encoding="utf-8")).get("started", ""), manifest.parent.name))
        except Exception:
            continue
    return [name for _, name in sorted(found, reverse=True)]


def runs() -> list[str]:
    """Evaluation run names, newest first."""
    return _runs(tuple(sorted(f.name for f in RESULTS.glob("*/manifest.json"))))


def run_manifest(run: str) -> dict:
    """The manifest of one evaluation run ({} when missing)."""
    manifest = RESULTS / run / "manifest.json"
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return {}


@st.cache_data(show_spinner=False)
def records(run: str, stamp: float = 0.0) -> list[dict]:
    """The run's records, with `model` replaced by its canonical id (`raw_model` keeps the original)."""
    file = RESULTS / run / "results.jsonl"
    if not file.exists():
        return []
    rows = []
    for line in file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        r["raw_model"] = r["model"]
        r["model"] = metrics.canonical_model(r["model"], run)
        rows.append(r)
    return rows


def load_records(run: str) -> list[dict]:
    return records(run, _mtime(RESULTS / run / "results.jsonl"))


@st.cache_data(show_spinner=False)
def cases(stamp: float = 0.0) -> dict[str, dict]:
    """Benchmark case id -> its manifest entry."""
    manifest = ROOT / "eval" / "cases" / "manifest.json"
    if not manifest.exists():
        return {}
    return {c["id"]: c for c in json.loads(manifest.read_text(encoding="utf-8"))}


def load_cases() -> dict[str, dict]:
    return cases(_mtime(ROOT / "eval" / "cases" / "manifest.json"))


def safe_name(model: str) -> str:
    """Folder name for a model in eval/results/<run>/full/ (same as eval/run_eval.py)."""
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in model)


def recorded(run: str, model: str, case_id: str) -> FixResult | None:
    """A recorded FixResult from a run's full logs (None when the file is missing)."""
    candidates = [model]
    if run.startswith("v1") and model == "patchai-3b-v1":
        candidates.append("patchai-3b")  # the raw name in v1 runs
    for name in candidates:
        file = RESULTS / run / "full" / safe_name(name) / f"{case_id}.json"
        if file.exists():
            try:
                return FixResult.model_validate_json(file.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None


def has_full_logs(run: str) -> bool:
    """True when the run's per-case logs are on this machine."""
    return (RESULTS / run / "full").is_dir()


@st.cache_data(show_spinner=False)
def training_run(name: str, stamp: float = 0.0) -> tuple[dict, dict]:
    """(manifest, loss) for one training run; empty dicts when missing."""
    folder = ROOT / "training" / "runs" / name
    manifest, loss = {}, {}
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    try:
        loss = json.loads((folder / "loss.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    return manifest, loss


def load_training_run(name: str) -> tuple[dict, dict]:
    return training_run(name, _mtime(ROOT / "training" / "runs" / name / "manifest.json"))


@st.cache_data(ttl=10, show_spinner=False)
def status() -> dict:
    """llm.model_status() plus the scanner, cached for 10 seconds."""
    return {**llm.model_status(), "semgrep": semgrep_available()}


# ---- settings ----

@dataclass
class Settings:
    project: Path
    model: str | None
    reviewer: str


def settings() -> Settings:
    """What the sidebar chose, with safe defaults when a view runs alone."""
    project = st.session_state.get("project")
    if project is None:
        project = demo.demo_project()
    model = st.session_state.get("model") or status()["default"]
    reviewer = st.session_state.get("reviewer") or getpass.getuser()
    return Settings(project=Path(project), model=model, reviewer=reviewer)


# ---- widgets ----

def finding_label(f: Finding) -> str:
    return f"{SEVERITY_ICON[f.severity]} {f.cwe} {cwe_name(f.cwe)}  ·  {f.file_path}:{f.start_line}"


def sidebar() -> None:
    """Status, project, model and reviewer. Writes to st.session_state."""
    with st.sidebar:
        st.caption("AI security fixes with a fine-tuned model and RAG. "
                   "Nothing changes without your approval.")
        s = status()

        def dot(ok: bool, text: str) -> None:
            st.markdown(f"{'🟢' if ok else '🔴'} {text}")

        dot(s["ollama"], "Ollama" if s["ollama"] else "Ollama (not running)")
        if s["default"]:
            label = metrics.model_label(s["default"])
            dot(s["fine_tuned"], f"{label}" + ("" if s["fine_tuned"] else " — base model, fallback"))
        else:
            dot(False, "No model")
        dot(s["semgrep"], "Semgrep" if s["semgrep"] else "Semgrep (missing)")
        dot(get_config()["rag"]["embedder"] != "hash", f"Embeddings ({get_config()['rag']['embedder']})")
        if s["problem"]:
            st.caption(f"⚠️ {s['problem']}")
        st.divider()

        choice = st.radio("Project", ["Demo shop (safe copy)", "Another folder"],
                          key="project_choice", label_visibility="collapsed")
        if choice == "Demo shop (safe copy)":
            st.session_state.project = str(demo.demo_project())
            if st.button("Reset demo shop", width="stretch"):
                demo.demo_project(reset=True)
                for key in ("findings", "results", "comparison"):
                    st.session_state.pop(key, None)
                st.toast("Demo shop restored to its original, vulnerable state.")
                st.rerun()
        else:
            typed = st.text_input("Folder", str(st.session_state.get("project", "")))
            if typed and not Path(typed).is_dir():
                st.error("That folder does not exist.")
            elif typed:
                st.session_state.project = typed

        installed = metrics.model_order(s["installed"])
        if installed:
            default = s["default"]
            index = installed.index(default) if default in installed else 0
            st.session_state.model = st.selectbox(
                "Model", installed, index=index, format_func=metrics.model_label)
            if st.button("Warm up model", width="stretch",
                         help="Load the model into memory now, so the first fix is fast."):
                with st.spinner("Loading the model..."):
                    try:
                        seconds = llm.warm_up(st.session_state.model)
                        st.toast(f"Loaded in {seconds:.0f}s. It stays in memory for 30 minutes.")
                    except llm.LLMError as e:
                        st.error(str(e))
        else:
            st.selectbox("Model", ["(Ollama is not running)"], disabled=True)
            st.session_state.model = None
        st.session_state.reviewer = st.text_input("Reviewer name", st.session_state.get("reviewer", getpass.getuser()))


def pipeline_strip(active: int, failed: bool = False, placeholder=None) -> None:
    """Five boxes: Scanner · RAG · Our model · Checks · Human. `active` is 1-based; 0 = nothing yet."""
    marks = []
    for i, name in enumerate(STEPS, start=1):
        if i < active:
            marks.append(f"✅ {name}")
        elif i == active:
            marks.append(f"{'🟥' if failed else '🔵'} **{name}**")
        else:
            marks.append(f"⬜ {name}")
    target = placeholder if placeholder is not None else st
    target.markdown("&nbsp;&nbsp;→&nbsp;&nbsp;".join(marks))


def empty_state(text: str, hint: str) -> None:
    """A consistent 'nothing here yet' box with the action that fixes it."""
    st.info(f"{text}\n\n**{hint}**", icon=":material/lightbulb:")


def event_log(box, events: list[tuple[str, str]]) -> None:
    for stage, message in events:
        box.write(f"**{stage}** · {message}")


# ---- showing one FixResult ----

def show_result(result: FixResult, compact: bool = False, key: str = "") -> None:
    """Everything about one fix: verdict, code, checks, attempts, RAG, prompt."""
    if result.error:
        st.error(result.error)
    kind, text = VERDICT_STYLE[result.verdict]
    tokens = sum(a.tokens_in + a.tokens_out for a in result.attempts)
    getattr(st, kind)(f"{text}  ·  {metrics.model_label(result.model)}  ·  "
                      f"{len(result.attempts)} attempt(s)  ·  {result.seconds:.0f}s  ·  {tokens:,} tokens")

    final = result.final
    if final and final.proposal:
        st.markdown(f"**The model's explanation:** {final.proposal.explanation or '—'}")
        st.progress(final.proposal.confidence, text=f"Model confidence: {final.proposal.confidence:.0%}")

    if compact:
        if result.diff:
            st.code(result.diff, language="diff")
        if final:
            _checks_row(final)
        return

    if result.context and final and final.proposal and final.proposal.status == "fixed":
        before, after = st.tabs(["Before / after", "Diff"])
        with before:
            left, right = st.columns(2)
            left.caption("Vulnerable code")
            left.code(result.context.source, language="python", line_numbers=True)
            right.caption("The proposed fix")
            right.code(final.proposal.fixed_code, language="python", line_numbers=True)
        with after:
            st.code(result.diff or "(no diff)", language="diff")
    elif result.diff:
        st.code(result.diff, language="diff")

    if final:
        st.markdown("**The checks** (every one must pass before a fix can be applied):")
        _checks_row(final)

    for attempt in result.attempts:
        title = f"Attempt {attempt.number}: {'passed' if attempt.passed else 'failed'} ({attempt.seconds:.0f}s)"
        with st.expander(title, expanded=(attempt is final and len(result.attempts) > 1)):
            _checks_row(attempt)
            if attempt.diff and attempt is not final:
                st.code(attempt.diff, language="diff")
            failed_checks = [c for c in attempt.checks if not c.passed and not c.skipped]
            if failed_checks and attempt is not final:
                st.markdown("**What the model was told next:**")
                st.code("\n".join(f"{CHECK_LABELS[c.name]}: {c.details}" for c in failed_checks)[:1500])
            if attempt.proposal is None and attempt.raw_output:
                st.caption("The answer could not be parsed. Raw model output:")
                st.code(attempt.raw_output[:2000])

    if result.retrieved:
        st.markdown("**What the AI read (RAG):**")
        for source, label in SOURCE_LABELS.items():
            chunks = [c for c in result.retrieved if c.source == source]
            if not chunks:
                continue
            st.markdown(f"{label}")
            for i, c in enumerate(chunks):
                st.progress(min(1.0, max(0.0, c.score)), text=f"{c.title} · relevance {c.score:.2f}")
                with st.expander(c.title, expanded=False):
                    st.code(c.text, language="markdown" if source == "guide" else "python")

    if result.context is not None:
        with st.expander("The exact prompt (attempt 1)"):
            from patchai.prompts import build_prompt

            for message in build_prompt(result.finding, result.context, result.retrieved):
                st.caption(message["role"])
                st.code(message["content"], language="text")


def _checks_row(attempt) -> None:
    by_name = {c.name: c for c in attempt.checks}
    columns = st.columns(len(CHECK_ORDER))
    for column, name in zip(columns, CHECK_ORDER):
        c = by_name.get(name)
        with column:
            if c is None:
                st.markdown(f"◻️ {CHECK_LABELS[name]}")
                st.caption("not reached")
            elif c.skipped:
                st.markdown(f"➖ {CHECK_LABELS[name]}")
                st.caption("skipped")
            elif c.passed:
                st.markdown(f"✅ {CHECK_LABELS[name]}")
                st.caption(c.details[:80] or "passed")
            else:
                st.markdown(f"❌ **{CHECK_LABELS[name]}**")
                st.caption(c.details[:120] or "failed")
