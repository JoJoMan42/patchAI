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
| Cross-site scripting (CWE-79) | Run scripts in other users' browsers |
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
pip install -r requirements.txt
pip install semgrep            # path traversal + XSS rules
pip install -e .

# 2. Models (install Ollama from https://ollama.com first)
ollama pull qwen2.5-coder:3b
ollama pull qwen2.5-coder:7b   # optional, for the comparison
#    our model: see training/README.md (until it's trained, PatchAI uses qwen2.5-coder:3b)

# 3. Check everything
patchai doctor

# 4. Run the review app
streamlit run app/review_app.py
```

Other ways in:

```powershell
patchai scan demo_projects/vuln_shop          # list vulnerabilities
patchai fix  demo_projects/vuln_shop          # fix one in the terminal, then approve/reject
python -m pytest                               # 69 tests, no model or GPU needed
```

**VS Code extension:** open the `extension/` folder in VS Code, press **F5**, run **PatchAI: Start PatchAI Server**, then **PatchAI: Scan Workspace**. See `extension/README.md`.

---

## Demo (about 10 minutes)

1. `streamlit run app/review_app.py`. Click **Scan project**: the demo shop shows seven vulnerabilities, one of each type.
2. Pick **SQL injection** and look at the vulnerable code.
3. Click **Fix with AI** and watch the live steps. Open **What the AI read**: the SQL-injection guide, the shop's own database helper, and a similar past fix.
4. Show the **diff**, the explanation, and the checks: guard ✅, tests ✅, security test (the attack) ✅, re-scan ✅.
5. **Compare models** tab: the same bug with the normal model vs ours.
6. Show a caught mistake from an attempt list: a hallucinated import blocked by the guard, or a fake fix caught by the attack test, followed by the retry that fixed it.
7. Click **Approve**: the fix is applied and the bug disappears from the next scan. Show the **Decisions** log.
8. Repeat in **VS Code**: red underline → 🛡️ Fix with PatchAI → Accept.
9. **Results** tab: the fix-rate chart (normal 3B vs ours vs 7B) and one honest limitation.

---

## Results so far

**v1** (first trained model, 2026-11-08), 53 test cases, every model through the same full pipeline. Scored fairly with `eval/rescore.py` (see [eval/README.md](eval/README.md)):

| Model | Fix rate | 95% interval | Demo shop (hand-written) | Time per fix |
| --- | --- | --- | --- | --- |
| Normal Qwen2.5-Coder 3B | 42% | 29–55% | 1/7 | 10s |
| **patchai-3b v1 (ours)** | **79%** | 67–88% | 6/7 | **7s** |
| Normal Qwen2.5-Coder 7B | 92% | 82–97% | 5/7 | 15s |

- Fine-tuning **nearly doubled** the 3B model's fix rate (42% → 79%; the intervals don't overlap), and made its answers 100% readable in our format.
- The 7B, a model twice the size, is still better overall. Ours is about twice as fast and wins on the hand-written demo shop.
- Ours scored **0% on hard-coded secrets** and **0/4 on key derivation**. Reading the logs showed why: habits from the training data (`os.environ["X"]` crashes when the variable isn't set; a random salt makes keys change every time). Retries rarely helped, because the retry prompt showed only a vague error.

**v2** fixes exactly those problems (balanced data, the missing patterns, real CVE fixes, retries that show the previous fix and the real error). It's trained and evaluated by `run_4060.sh`, and its results go to `eval/results/v2/`. Details: [training/README.md](training/README.md#v1--v2-what-we-changed-after-the-first-models-error-analysis).

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
  metrics.py                fix rate, confidence intervals, fake fixes, ...
  server.py, cli.py         local API for VS Code, command line
app/review_app.py        Streamlit review app (Fix · Compare models · Results · Decisions)
extension/               VS Code extension (TypeScript)
training/                synth.py + real_data.py → make_dataset.py → train.py → export.py (+ dpo.py)
eval/                    make_cases.py → run_eval.py → report.py (+ rescore.py)
run_4060.sh              the whole GPU part in one command (see RUN_ON_4060.md)
data/knowledge/          7 security guides (one per type)
data/fix_examples/       35 past fixes
data/semgrep_rules.yaml  our taint-tracking rules for path traversal and XSS
data/real_fixes/         real CVE fixes from CVEfixes, filtered by our scanners
demo_projects/vuln_shop/ the intentionally vulnerable demo app (+ tests + attack tests)
tests/                   PatchAI's own tests
```

See [PLAN.md](PLAN.md) for the status, what is left, and who does what.

---

## Why this is better than the old version

| | Old version (PatchPilot) | New version (PatchAI) |
| --- | --- | --- |
| Focus | Running it as a cloud service | Making the AI fix bugs well, and proving it |
| Built with | Postgres, Redis, Celery, separate services, auth, WebSockets, Kubernetes | Python, a fine-tuned model, RAG, Streamlit, VS Code |
| AI part | Called an existing model | We train our own model (SFT + DPO) and build RAG around it |
| Proof a fix works | Planned | Tests + real attack test + re-scan on every fix |
| Results | Nothing to measure | Validated benchmark, fix rates with confidence intervals |
| Demo | API documentation | Review app + VS Code extension |
| Status | Skeleton that didn't run end to end | Runs end to end, 69 passing tests, trained and evaluated |

The old design was built like a hosted product. PatchAI is a local research prototype, so servers and deployment tools added work without adding anything to demonstrate or measure. **Kept:** the scanners, the safety guard, testing fixes on a copy of the code, and human approval.

## Limitations (say these in the viva)

- Python only, seven vulnerability types.
- Fixes are limited to one function (or statement) per finding.
- Tests run on a temporary copy, not inside a container. The project's own tests are trusted code. Run untrusted projects in a VM.
- Generated benchmark cases come from templates, so the 7 hand-written shop cases are reported separately as a check.
- Security tests prove the attacks we wrote fail, not that every possible attack fails.

## Tech stack

Python 3.11 · Bandit · Semgrep · Python `ast` · Ollama · Qwen2.5-Coder (3B fine-tuned, 3B and 7B base) · Unsloth, TRL, PEFT (QLoRA, DPO) · fastembed (BAAI/bge-small-en-v1.5, ms-marco-MiniLM cross-encoder) · rank-bm25 · NumPy · Streamlit · FastAPI · TypeScript (VS Code API) · pandas, matplotlib · pytest
