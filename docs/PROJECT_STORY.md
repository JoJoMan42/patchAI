# PatchAI: the whole story

This document tells the project from start to finish: why it exists, how every part works and what it contributes, what we measured, what we learned, and what we improved. For quick setup see [README.md](../README.md); for status and who owns what see [PLAN.md](PLAN.md).

---

## 1. Where we started

The project topic was submitted as **AI-assisted secure code repair**: find security vulnerabilities in code and fix them automatically with AI.

The first design, **PatchPilot** (`autopatch/`), was built like a hosted cloud product: Postgres, Redis, Celery workers, separate services, authentication, WebSockets and Kubernetes. Most of the work went into infrastructure, the AI part was "call an existing model", there was nothing to measure, and it didn't run end to end.

We kept the topic and rebuilt it as **PatchAI**, with a different focus:

| | PatchPilot (old) | PatchAI (new) |
| --- | --- | --- |
| Focus | Running it as a cloud service | Making the AI fix bugs well, and proving it |
| AI part | Called an existing model | **Our own fine-tuned model** + RAG built around it |
| Proof a fix works | Planned | Tests + a real attack test + re-scan on every fix |
| Results | Nothing to measure | A validated benchmark with confidence intervals |
| Runs | Skeleton | End to end, on a laptop, fully offline |

What we kept from the old design: the scanners, the safety guard, testing fixes on a copy of the code, and human approval.

---

## 2. What PatchAI does

A **vulnerability** is a security hole: the code works for normal users, but an attacker can abuse it. Example:

```python
# Vulnerable: an attacker types  ' OR '1'='1  and gets every product
sql = f"SELECT * FROM products WHERE name LIKE '%{term}%'"

# Fixed: the input is a parameter, never part of the SQL
sql = "SELECT * FROM products WHERE name LIKE ?"
return run_query(conn, sql, (f"%{term}%",))
```

PatchAI covers 7 of the most common types in Python:

| Type | What an attacker can do |
| --- | --- |
| SQL injection (CWE-89) | Read or change the database |
| Command injection (CWE-78) | Run commands on the server |
| Path traversal (CWE-22) | Read files they shouldn't (`../../secrets`) |
| Cross-site scripting (CWE-79) | Run scripts in other users' browsers |
| Hard-coded secrets (CWE-798) | Steal passwords written in the code |
| Weak cryptography (CWE-327) | Break or predict hashes and keys |
| Unsafe deserialization (CWE-502) | Run code by uploading crafted data |

---

## 3. The pipeline: five steps

```
1. SCANNER     finds the vulnerability        Bandit + our own Semgrep rules
      ▼
2. RAG         gathers information             security guides, the project's code, past fixes
      ▼
3. OUR MODEL   writes the fix                  fine-tuned Qwen2.5-Coder 3B, answers in JSON
      ▼
4. CHECKS      prove it works                  guard → tests → attack test → re-scan
      │        (failed? the model sees its fix and the error, and tries again, max 3)
      ▼
5. HUMAN       approves or rejects             review app or VS Code; every decision is logged
```

The scanner is the alarm, RAG is the research assistant, the model is the specialist, the checks are the inspector, and the human is the boss.

### Step 1: Scanner (`patchai/scan.py`)
- Runs **Bandit**, a standard Python security scanner, and maps its rules to our 7 types (e.g. B608 → SQL injection).
- Bandit can't see path traversal or reflected XSS, so we wrote our own **Semgrep taint rules** (`data/semgrep_rules.yaml`). They follow user input from where it enters (a function argument, a request parameter) to where it's dangerous (`open()`, an HTML response).
- Everything that isn't one of our 7 types is dropped.
- **Contributes:** a precise, real finding (file, line, rule, message) that starts everything else.

### Code context (`patchai/context.py`)
- Uses Python's `ast` module to cut out **the function that contains the bug**. That function is the only code the model is allowed to rewrite.
- Also collects the file's imports and the functions this code calls.
- **Contributes:** keeps the model's job small and focused, and keeps the rest of the file safe.

### Step 2: RAG (`patchai/rag_index.py`, `rag_search.py`, `embeddings.py`)
Before the model writes anything, RAG looks up **6 useful pieces of text** from three sources:

| Source | What's in it | Why it helps |
| --- | --- | --- |
| Security guides | 7 guides we wrote, one per type (`data/knowledge/`) | The right way to fix this kind of bug |
| Past fixes | 35 before → after examples (`data/fix_examples/`) | A similar fix to copy the style from |
| Project code | Every function in the project being fixed | The project's own helpers, so the model doesn't invent functions |

How it searches:
1. **Two searches at once:** meaning search (BGE-small embeddings: finds text that *means* the same) and keyword search (BM25: finds exact names like `run_query`).
2. **Rank fusion** (reciprocal rank fusion) merges them: things ranked high in both go to the top.
3. **A reranker** (a small cross-encoder model) re-reads each candidate next to the bug and re-scores it.
4. **Call-graph boost:** functions the vulnerable code actually calls come first.

Vectors are stored as NumPy files, with no vector database, and everything runs offline.

- **Contributes:** information. The model gets the right technique, a known-good example and the real helpers, which means fewer made-up functions and better fixes. The app shows "What the AI read", so every fix is explainable.

### Step 3: Our model (`patchai/prompts.py`, `llm.py`, `fixer.py`)
- The prompt contains the finding, the function, the imports and the RAG material. Untrusted text is wrapped in tags (`<vulnerable_code>`, `<reference>`, `<error>`) and the model is told it is data, not instructions.
- The model answers in a fixed **JSON** shape: `status`, `fixed_code` (the whole fixed function), `imports_to_add`, `explanation`, `confidence`. Ollama enforces the shape.
- It can also answer **"cannot fix"** or **"false alarm"** instead of guessing.
- The model returns the whole function, not a diff (small models write broken diffs). `patching.py` splices it back in and computes the diff itself.
- **Contributes:** the skill. Section 4 explains how we trained it.

### Step 4: Checks (`patchai/guard.py`, `checks.py`)
Every fix must pass all of these, on a **temporary copy** of the project (the real project is never touched):

1. **Safety guard:** fast rules that don't trust the AI.
   - The code must parse.
   - The function's signature must stay the same.
   - The fix must be at most 30 changed lines.
   - No new `eval`/`exec`/`shell=True`.
   - No `# nosec` tricks that silence the scanner.
   - No **hallucinated imports** (packages that don't exist).
2. **Project tests:** the project's own tests must still pass, so the fix doesn't break normal behaviour.
3. **Security test (the attack):** a test that actually **performs the attack**, e.g. sends `../config.py` and checks it can't be read. It fails while the bug exists and passes once it's really fixed.
4. **Re-scan:** the scanner must no longer report the bug, and nothing new.

A **fake fix** fools the scanner but the attack still works. Only the attack test catches it, which is why it exists.

If an attempt fails, the model gets **its previous fix and the exact error** (e.g. `KeyError: 'API_TOKEN'`) and tries again, up to 3 times.

- **Contributes:** proof, not promises. A fix is only called "fixed" when it's proven.

### Step 5: Human review (`patchai/review.py`, `app/`, `extension/`)
- Nothing changes in the real project until a person clicks **Approve**. Every approve or reject is logged with who, when, which model and why (`data/decisions.jsonl`).
- **Review app** (Streamlit, `patchai app`), eight pages in `app/views/`:
  - **Overview:** the pipeline diagram, the headline numbers (computed from the newest run), a pre-demo checklist.
  - **Fix:** scan, pick a finding, see the attack that will be tried, fix it live with a five-step progress strip, then the before/after code, every check and attempt, what RAG read and the exact prompt; approve or reject. Without Ollama it can replay the recorded v2 fix.
  - **Compare:** the same bug through several models, side by side (or the recorded four-model comparison).
  - **Results:** the evaluation dashboard: fix rates with intervals, accuracy against speed, a per-type heat map, every case, failure reasons, v1 → v2, and an honest-reading box.
  - **Case explorer:** replay any recorded benchmark case, attempt by attempt.
  - **Training:** loss curves, the data before and after, the CVEfixes filter, real CVE fixes, a random synthetic example.
  - **RAG:** search the knowledge base and see each ranking stage.
  - **Decisions:** the log.
- Demos run on a **copy** of the demo shop (`patchai/demo.py`), so approving a fix never changes the tracked project.
- **VS Code extension** (`extension/`, TypeScript, installable `patchai.vsix`): it starts the local server itself, scans when a Python folder opens, and shows findings as underlines, in a PatchAI side bar, in hovers and as CodeLens. A fix runs as a server job with live progress; Accept refuses to overwrite a file you changed and offers Undo. **Open Demo Project** and a walkthrough make the first five minutes obvious.
- **CLI** (`patchai doctor`, `scan`, `fix`, `demo`, `app`, `serve`).
- **Contributes:** human control, and the demo.

---

## 4. Training our own model

We fine-tune **Qwen2.5-Coder-3B-Instruct** to do one job well: turn a vulnerable function into a small, correct, secure fix, in our exact JSON format.

### The data
Each training example is a **question and its correct answer**:
- **Question:** exactly the prompt PatchAI builds in real use (real scanner finding, real context, real RAG). In 20% of examples it also contains a wrong previous fix and its error.
- **Answer:** the correct fix as JSON.

Two sources:
- **Synthetic** (`training/synth.py`): 25 code patterns written twice (safe and vulnerable), with random names, styles and docstrings, so about 2,500 examples are all different. Some are **false alarms** (safe code a scanner flags anyway), so the model learns to say so. The safe version is the answer by construction, so there are no wrong labels.
- **Real-world** (`training/real_data.py`): **21 real CVE fixes from 14 open-source projects**, taken from the CVEfixes dataset. The dataset only stores changed lines, so the script:
  1. downloads each fixed file from GitHub at the fixing commit and undoes the diff to rebuild the vulnerable file
  2. runs **our** scanners on it
  3. keeps a fix only if the flagged function was changed by the commit and the fixed version is no longer flagged

  Bad lessons are filtered out (e.g. a "fix" that still used `shell=True`).

`training/make_dataset.py` runs every example through the real scanner, context and RAG code, so training prompts are identical to real prompts.

### The training
- **QLoRA:** the 3B model is loaded in 4-bit and frozen, and small LoRA layers (rank 16) are trained on top. That fits in the RTX 4060's 8 GB.
- Built with **Unsloth, TRL and PEFT**. 2 epochs, learning rate 2e-4, loss on the answer only.
- Exported to **GGUF** (4-bit) and loaded into **Ollama** as `patchai-3b`.
- **Bonus, DPO** (`training/dpo.py`): the model writes several fixes per new case, our checks mark the bad ones, and DPO trains it to prefer the correct fix over its own typical mistakes.

### Keeping it fair
- The training patterns and the benchmark patterns are **different code shapes**, so a good score means the model learned the skill, not our templates.
- The demo shop is never used for training. DPO never sees test cases.

---

## 5. Measuring it

### The benchmark (`eval/make_cases.py`)
- **56 generated cases** (14 patterns × 4 variants) + **7 hand-written cases** (the demo shop). 53 test cases, 10 dev cases.
- Every case is **validated** before use:
  - the scanner detects it
  - its normal tests pass
  - its attack works on the vulnerable code
  - a known-correct fix passes every check

  So every case is real and solvable.

### The experiment (`eval/run_eval.py`, `report.py`)
Every model goes through the **same full pipeline** (RAG, up to 3 attempts, all checks) on the **same cases**. A case only counts as fixed if the tests pass, the attack fails and the scanner is quiet. We report:
- fix rate with a 95% Wilson confidence interval
- first-try rate
- fake fixes
- unreadable answers
- guard blocks
- time

### The demo project (`demo_projects/vuln_shop/`)
A small Flask shop with **one vulnerability of each type, on purpose**. It has normal tests and one attack test per vulnerability. It's the patient in every demo.

---

## 6. Results: v1

The first model was trained on the 4060 (116 minutes, validation loss 0.034) and evaluated on 2026-11-08.

| Model | Fix rate | 95% interval | Demo shop | Time per fix |
| --- | --- | --- | --- | --- |
| Normal Qwen 3B | 42% | 29–55% | 1/7 | 10s |
| **patchai-3b v1 (ours)** | **79%** | 67–88% | **6/7** | **7s** |
| Normal Qwen 7B | 92% | 82–97% | 5/7 | 15s |

- Fine-tuning **nearly doubled** the 3B's fix rate, and the intervals don't overlap, so this is a real effect.
- Our answers were 100% readable in our format.
- Ours is about **twice as fast** as the 7B and **best on the hand-written demo shop**.
- The 7B, a model twice the size, is still better overall.

---

## 7. What we learned from v1 (error analysis)

We read the full logs of every attempt. Findings:

| # | What we saw | Cause |
| --- | --- | --- |
| 1 | The 7B first scored only 74%, with 0% on XSS | **Our bug:** it wrapped correct fixes in the `<vulnerable_code>` tags copied from our prompt, and our parser counted that as a syntax error. Fixing the parser and re-checking the recorded answers (`eval/rescore.py`) gave the fair 92%. |
| 2 | Ours: 0% on hard-coded secrets | Training taught `os.environ["X"]`, which **crashes** when the variable isn't set, so every test failed |
| 3 | Ours: 0/4 on key derivation | Training only had password hashing (random salt, hex string); the model copied that habit where keys must stay the same and be bytes |
| 4 | Retries barely helped: often the same wrong fix 3 times | The retry prompt showed a vague error (`<test run error>`) and **not** the previous fix |
| 5 | 25% of training data was one false-alarm pattern, and only 88 command-injection examples | A bug in the data generator |
| 6 | 15% fake fixes for ours vs 4% for the 7B | The attack tests caught them, which is exactly their job |

This is the most important lesson of the project: **fine-tuning gives a small model strong habits; where those habits don't fit, it fails, and the logs show exactly why.**

---

## 8. What we improved: v2

| Problem | v2 change |
| --- | --- |
| Unfair parsing | The parser strips echoed prompt tags and markdown fences. Recorded v1 answers re-scored (`eval/results/v1_rescored/`) |
| Vague errors | Test failures now report the real error line, e.g. `KeyError: 'API_TOKEN'` |
| Retries repeating themselves | The retry prompt shows **the previous fix + the real error**. An identical repeat isn't re-tested, and the model is told it repeated itself. Retries use a slightly higher temperature |
| Secrets crashing | Training always uses `os.environ.get("X", "")`. New credential-check pattern |
| Key derivation | New key-stretching pattern: PBKDF2, deterministic, still bytes. Checksums keep their return type |
| Generator bug | Fixed quotas: ~330 examples per type, exactly 8% false alarms |
| Learning from feedback | 20% retry examples with realistic mistakes and their real error messages |
| Synthetic-only data | **21 real CVE fixes** added (each used twice in training) |
| Export problems | The export finds the model file wherever Unsloth puts it |
| Hard to run on the GPU laptop | **`run_4060.sh`**: checks → tests → keep v1 → data → train → export → full comparison → pack results, in one command, safe to re-run |

The prompt changed for retries, so it's now version `v2`. Tests went from 54 to 69 (and to 93 with the final polish).

## 8b. Results: v2

The v2 experiment (run `v2`, 2026-11-09) compared **base 3B vs our v1 vs our v2 vs base 7B** on the same 53 test cases, on the same day:

| Model | Fix rate | 95% interval | Hard-coded secret | Weak crypto | Demo shop | Time per fix |
| --- | --- | --- | --- | --- | --- | --- |
| Qwen2.5-Coder 3B (base) | 49% | 36–62% | 57% | 44% | 4/7 | 9.1 s |
| PatchAI-3B v1 | 72% | 58–82% | 0% | 56% | 6/7 | 6.5 s |
| **PatchAI-3B v2** | **87%** | 75–93% | **57%** | **100%** | 6/7 | 6.2 s |
| Qwen2.5-Coder 7B (base) | 91% | 80–96% | 71% | 100% | 5/7 | 20.1 s |

- **Every fix from the error analysis worked:** secrets 0% → 57%, crypto 56% → 100%, command injection 71% → 100%, and the guard never had to block a v2 attempt.
- **Our 3B is now statistically level with the 7B** (the intervals overlap) at a third of the time per fix.
- **Honest notes:** the same v1 model scored 79% in the earlier run and 72% here, so runs vary by about ±7 points and we compare only inside one run. Retries rescued no case for v1, v2 or the 7B. v2's remaining failures are three path-traversal cases that passed the tests and the attack but were flagged by our own Semgrep rule (we showed the rule does not accept a sanitiser applied before the path is built), three credential-check secret cases, and the demo shop's XSS case. We did not change the scoring after seeing this.

---

## 9. Design decisions (and why)

| Decision | Why |
| --- | --- |
| A small local model, not GPT-4 | Code never leaves the machine, no cost, and it shows a trained small model can compete |
| Fine-tuning **and** RAG | RAG gives the model information (guides, helpers); fine-tuning gives it the skill (format, fix patterns) |
| The whole function, not a diff | Small models write broken diffs; we splice and diff ourselves |
| Structured JSON output | The pipeline can always read the answer |
| Attack tests + re-scan | A scanner can be fooled; a working attack can't |
| Checks on a temporary copy | The real project changes only after approval |
| NumPy vectors, no database | A few thousand chunks need no server; fully offline |
| Our own Semgrep taint rules | Bandit can't see path traversal or reflected XSS |
| Real CVE fixes filtered by our own scanners | CVEfixes is noisy; keeping only fixes our scanners confirm keeps the data consistent with how fixes are judged |
| No servers, queues or cloud | It's a research prototype; infrastructure adds work but nothing to measure |

---

## 10. Limitations (say these in the viva)

- Python only, 7 vulnerability types.
- One function (or statement) per fix.
- Tests run on a temporary copy, not in a container; run untrusted projects in a VM.
- Most training data and generated benchmark cases come from templates. The 7 hand-written shop cases are reported separately, and only 21 real-world examples survived filtering.
- Attack tests prove the attacks we wrote fail, not that every possible attack fails.
- In v2, two training patterns were added after looking at v1's test failures. They teach the same concepts as two benchmark patterns but in different code; we say this openly.

---

## 11. Where things are

```
patchai/            the pipeline, one file per step (+ demo.py: the safe demo copy)
app/                Streamlit review app: review_app.py, ui.py, charts.py, views/ (one page per file)
extension/          VS Code extension (patchai.vsix to install)
docs/DEMO.md        demo script, checklist, fallback plan, viva questions
report/             the project report builder (figures + .docx)
training/           synth.py, real_data.py → make_dataset.py → train.py → export.py (+ dpo.py)
eval/               make_cases.py → run_eval.py → report.py (+ rescore.py); results/v1, v1_rescored, v2
data/               guides, past fixes, Semgrep rules, real CVE fixes
demo_projects/      the vulnerable demo shop
tests/              93 tests, no model or GPU needed
run_4060.sh         the whole GPU part in one command
```

## 12. What's left

1. **Demo laptop:** install Ollama, register the v2 and v1 `.gguf` files (`training/export.py`), and `patchai doctor --warm`.
2. **Full logs:** extract `v2_full_eval_logs.zip` into `eval/results/v2/full/` for the case explorer and the replay fallback.
3. **Report:** fill in the team names, personal sections and two screenshots (yellow in the .docx), then rebuild.
4. **Slides, rehearsal and a backup video**, following [DEMO.md](DEMO.md).
