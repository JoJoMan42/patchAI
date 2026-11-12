# 🛡️ PatchAI

**An AI that fixes security vulnerabilities in Python code, using a model we fine-tuned ourselves.**

PatchAI finds security holes in a project, gathers the right information with RAG, writes a fix with our own trained model, **proves** the fix works by running tests and the actual attack, and lets a human approve it. Everything runs on a laptop, so your code never leaves your machine.

> Final-year project. The new version of PatchPilot: same topic, now focused on AI/ML instead of infrastructure.

---

## How it works

```
1. SCANNER       FINDS the vulnerability          Bandit + our own Semgrep taint rules
      │                                            "SQL injection in shop/db.py line 54"
      ▼
2. RAG           GATHERS information              hybrid search (embeddings + BM25) + reranker over
      │                                            security guides, the project's code, past fixes
      ▼
3. OUR MODEL     WRITES the fix                   fine-tuned Qwen2.5-Coder 3B returns the fixed function
      │                                            as JSON (or says "cannot fix" / "false alarm")
      ▼
4. CHECKS        PROVE it works                   safety guard → project tests → attack test → re-scan
      │          (failed? the model gets the       all on a temporary copy, never the real project
      │           error and tries again, max 3)
      ▼
5. HUMAN         APPROVES or rejects              review app or VS Code; every decision is logged
```

Each part has one job: the **scanner** is the alarm, **RAG** is the research assistant, **our model** is the specialist, the **checks** are the inspector, and the **human** is the boss.

### What is a vulnerability?

A security hole: the code works for normal users, but an attacker can abuse it.

```python
# Vulnerable: an attacker types  ' OR '1'='1  and gets every product
sql = f"SELECT * FROM products WHERE name LIKE '%{term}%'"

# Fixed by PatchAI: the input is a parameter, never part of the SQL
sql = "SELECT * FROM products WHERE name LIKE ?"
return run_query(conn, sql, (f"%{term}%",))
```

| Type | What an attacker can do |
| --- | --- |
| SQL injection (CWE-89) | Read or change the database |
| Command injection (CWE-78) | Run commands on the server |
| Path traversal (CWE-22) | Read files they shouldn't (`../../secrets`) |
| Cross-site scripting (XSS) (CWE-79) | Run scripts in other users' browsers |
| Hard-coded secrets (CWE-798) | Steal passwords written in the code |
| Weak cryptography (CWE-327) | Break or predict hashes and tokens |
| Unsafe deserialization (CWE-502) | Run code by uploading crafted data |

---

## What makes it impressive

- **We train our own model.** QLoRA fine-tuning of Qwen2.5-Coder 3B on about 2,500 examples, including **real CVE fixes from open-source projects** (CVEfixes), on an RTX 4060 laptop. Bonus: **DPO** trains it to avoid its own typical mistakes.
- **Real RAG.** Three knowledge sources, hybrid search with reciprocal rank fusion, a cross-encoder reranker, and call-graph-aware code retrieval (functions the vulnerable code calls come first).
- **Proof, not promises.** Every fix must pass the project's tests, a **security test that performs the real attack**, and a re-scan. That catches **fake fixes** that fool the scanner but stay exploitable.
- **It doesn't trust the AI.** A safety guard blocks hallucinated imports, `eval`/`shell=True`, `# nosec` tricks, signature changes and oversized edits.
- **Self-correcting.** A failed attempt's fix and its exact error (e.g. `KeyError: 'API_TOKEN'`) go back to the model, which tries again. The model is trained on such retries.
- **Honest AI.** The model can say "cannot fix" or "this is a false alarm" instead of guessing.
- **Explainable.** The review screen shows the diff, the explanation, every attempt, and exactly what RAG retrieved.
- **Human in control.** Nothing touches the real project until a person clicks Approve, and every decision is logged.
- **Private.** Runs fully offline: local models through Ollama, local embeddings, no cloud.
- **Measured, and improved from the measurements.** A validated benchmark of 63 cases compares our model against the normal 3B and the bigger 7B, with confidence intervals. Reading v1's failures led to v2 (see Results).

---

## Quick start

```powershell
# 1. Python environment (Windows; on Linux/macOS use: source .venv/bin/activate)
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .               # PatchAI and all its dependencies
pip install semgrep            # path traversal + XSS rules

# 2. Models (install Ollama from https://ollama.com first)
ollama pull qwen2.5-coder:3b
ollama pull qwen2.5-coder:7b   # optional, for the comparison
python training/export.py --gguf <path-to-v2>.gguf --name patchai-3b      # our model (from the team's Drive)

# 3. Check everything (and load the model into memory)
patchai doctor --warm

# 4. Open the review app
patchai app
```

Other ways in:

```powershell
patchai demo                                   # path of the safe demo copy (patchai demo --reset restores it)
patchai scan (patchai demo)                    # list vulnerabilities
patchai fix  (patchai demo)                    # fix one in the terminal, then approve/reject
patchai serve                                  # the local server for the VS Code extension
python -m pytest                               # 93 tests, no model or GPU needed
```

**VS Code extension:** `code --install-extension extension/patchai.vsix`, then run **PatchAI: Open Demo Project**. The extension starts the server by itself. See [extension/README.md](extension/README.md).

Demos always run on a **copy** of the vulnerable shop (`data/demo_workspace/`), so approving a fix never changes the tracked `demo_projects/vuln_shop`.

---

## Demo (about 10 minutes)

`patchai doctor --warm`, `patchai app`, click **Reset demo shop**, then: Overview → Fix (scan, fix SQL injection live, approve) → Compare (the hard-coded secret: v1 fails, v2 fixes it) → Results → Training → RAG → VS Code. The full script, a pre-demo checklist, the fallback when the model is not available, and likely viva questions are in [docs/DEMO.md](docs/DEMO.md).

---

## Results

**Run `v2`** (2026-11-09): four models, the same 53 test cases, every model through the same full pipeline (see [eval/README.md](eval/README.md)):

| Model | Fix rate | 95% interval | Demo shop (hand-written) | Time per fix |
| --- | --- | --- | --- | --- |
| Qwen2.5-Coder 3B (base) | 49% | 36–62% | 4/7 | 9 s |
| PatchAI-3B v1 (ours) | 72% | 58–82% | 6/7 | 6.5 s |
| **PatchAI-3B v2 (ours)** | **87%** | 75–93% | 6/7 | **6.2 s** |
| Qwen2.5-Coder 7B (base) | 91% | 80–96% | 5/7 | 20 s |

- **Our 3B model is almost as accurate as a model more than twice its size, at about a third of the time per fix.** Fine-tuning took the 3B model from 49% to 87%.
- v1 → v2 fixed exactly what the v1 error analysis found: hard-coded secrets **0% → 57%**, weak cryptography **56% → 100%**, command injection 71% → 100%, and no v2 attempt was blocked by the safety guard. Details: [training/README.md](training/README.md#v2-results-and-what-still-fails).

**Read this honestly:**
- The 95% intervals of v2 and the 7B overlap, so we do not claim to beat it.
- The same v1 model scored 79% in an earlier run and 72% here: run-to-run noise is about ±7 points, so we only compare models **inside one run**.
- Generated cases come from templates; the 7 hand-written shop cases are reported separately.
- Path traversal and secrets are still v2's weak types. Three of its path-traversal "failures" passed the tests and the attack and were rejected only by our own Semgrep rule, which we showed does not accept a sanitiser applied before the path is built.

**History, run `v1_rescored`** (2026-11-08, three models): base 3B 42%, PatchAI-3B v1 79%, base 7B 92%. Reading every v1 failure led to v2.

---

## Project map

```
patchai/                 the pipeline (one file per step)
  scan.py                1. Bandit + Semgrep → Findings (only our 7 types)
  context.py                the function the model may rewrite (Python ast)
  rag_index.py           2. builds the guide / past_fix / code collections (NumPy vectors + BM25)
  rag_search.py             hybrid search, rank fusion, reranker, call-graph-aware code retrieval
  embeddings.py             embedding model + reranker (fastembed/ONNX, offline fallback)
  prompts.py             3. the prompt (shared with training, so they always match)
  llm.py                    Ollama client (the only file that calls a model)
  fixer.py                  ask → check → retry loop
  patching.py               puts the fixed function back into the file, makes the diff
  guard.py               4. fast safety rules
  checks.py                 tests, attack test and re-scan on a temporary copy
  pipeline.py               fix_finding(): steps 2–4 for one finding
  review.py              5. approve / reject + decisions log
  metrics.py                fix rate, confidence intervals, fake fixes, model names and colours
  demo.py                   the safe, resettable copy of the demo shop
  server.py, cli.py         local API for VS Code, command line
app/                     Streamlit review app: review_app.py (entry), ui.py, charts.py,
  views/                 one page per file: overview, fix, compare, results, cases, training, rag, decisions
extension/               VS Code extension (TypeScript; patchai.vsix is the installable package)
docs/                    every guide, in one place:
  PATCHAI_EXPLAINED.md     the whole project explained for anyone (start here)
  DEMO.md                  the demo script, checklist, fallback plan and viva questions
  PLAN.md                  status, what is left, who owns what
  PROJECT_STORY.md         the story: problem, design, results, lessons
  RUN_ON_4060.md           how the GPU training run is done
  IMPLEMENTATION_PLAN.md   the polish plan (history: all work packages are done)
  reference/               the owner's report template and reference PDF
report/                  builds the project report (figures.py → fig/, build_report.js → .docx)
training/                synth.py + real_data.py → make_dataset.py → train.py → export.py (+ dpo.py)
eval/                    make_cases.py → run_eval.py → report.py (+ rescore.py)
run_4060.sh              the whole GPU part in one command (see docs/RUN_ON_4060.md)
data/knowledge/          7 security guides (one per type)
data/fix_examples/       35 past fixes
data/semgrep_rules.yaml  our taint-tracking rules for path traversal and XSS
data/real_fixes/         real CVE fixes from CVEfixes, filtered by our scanners
demo_projects/vuln_shop/ the intentionally vulnerable demo app (+ tests + attack tests)
tests/                   PatchAI's own tests
```

See [docs/PLAN.md](docs/PLAN.md) for the status, what is left, and who does what.

---

## Why this is better than the old version

| | Old version (PatchPilot) | New version (PatchAI) |
| --- | --- | --- |
| Focus | Running it as a cloud service | Making the AI fix bugs well, and proving it |
| Built with | Postgres, Redis, Celery, separate services, auth, WebSockets, Kubernetes | Python, a fine-tuned model, RAG, Streamlit, VS Code |
| AI part | Called an existing model | We train our own model (SFT + DPO) and build RAG around it |
| Proof a fix works | Planned | Tests + real attack test + re-scan on every fix |
| Results | Nothing to measure | Validated benchmark, fix rates with confidence intervals |
| Demo | API documentation | Eight-page review app + installable VS Code extension |
| Status | Skeleton that didn't run end to end | Runs end to end, 93 passing tests, two trained models evaluated |

The old design was built like a hosted product. PatchAI is a local research prototype, so servers and deployment tools added work without adding anything to demonstrate or measure. **Kept:** the scanners, the safety guard, testing fixes on a copy of the code, and human approval.

## Limitations (say these in the viva)

- Python only, seven vulnerability types.
- Fixes are limited to one function (or statement) per finding.
- Tests run on a temporary copy, not inside a container. The project's own tests are trusted code. Run untrusted projects in a VM.
- Generated benchmark cases come from templates, so the 7 hand-written shop cases are reported separately as a check.
- Security tests prove the attacks we wrote fail, not that every possible attack fails.
- The benchmark is our own (53 test cases), and results move by about ±7 points between runs.
- Retries rarely rescue a case for the stronger models: when a fine-tuned model fails once, it tends to fail again.

## Tech stack

Python 3.11 · Bandit · Semgrep · Python `ast` · Ollama · Qwen2.5-Coder (3B fine-tuned, 3B and 7B base) · Unsloth, TRL, PEFT (QLoRA, DPO) · fastembed (BAAI/bge-small-en-v1.5, ms-marco-MiniLM cross-encoder) · rank-bm25 · NumPy · Streamlit · FastAPI · TypeScript (VS Code API) · pandas, matplotlib · pytest
