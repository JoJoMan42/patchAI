# PatchAI: status and plan

Read [README.md](../README.md) first. This file says what is built, what is left, and who does what.

## Status

| Part | Status | Where |
| --- | --- | --- |
| Scanning (Bandit + our Semgrep taint rules) | ✅ Done, tested | `patchai/scan.py`, `data/semgrep_rules.yaml` |
| Code context (ast) | ✅ Done, tested | `patchai/context.py` |
| RAG: 7 guides, 35 past fixes, code index, hybrid search, reranker | ✅ Done, tested | `patchai/rag_*.py`, `patchai/embeddings.py`, `data/` |
| Prompt, model client, fix-and-retry loop | ✅ Done, tested with a scripted model | `patchai/prompts.py`, `llm.py`, `fixer.py` |
| Safety guard, tests, attack test, re-scan | ✅ Done, tested | `patchai/guard.py`, `checks.py` |
| Human review + decisions log | ✅ Done, tested | `patchai/review.py` |
| Review app (Streamlit): eight pages, replay fallback without Ollama | ✅ Done (2026-11-11), tested headless | `app/review_app.py`, `app/views/` |
| VS Code extension + local server: self-starting server, side bar, live progress, safe Accept with Undo | ✅ Done (2026-11-11), `.vsix` builds and installs | `extension/`, `patchai/server.py` |
| Demo shop (7 vulnerabilities, tests, attack tests) | ✅ Done | `demo_projects/vuln_shop/` |
| Safe demo copy (demos never edit the tracked shop) | ✅ Done (2026-11-10) | `patchai/demo.py` |
| Training data generator + dataset builder | ✅ v2: balanced, realistic retry examples, + 21 real CVE fixes | `training/synth.py`, `make_dataset.py`, `real_data.py` |
| SFT training, export, DPO scripts | ✅ Run on the 4060 (v1); one-command runner for v2 | `training/`, `run_4060.sh` |
| Benchmark (validated cases) | ✅ Generated | `eval/cases/` |
| Evaluation runner + charts + re-scoring | ✅ Done | `eval/run_eval.py`, `report.py`, `rescore.py` |
| **Model v1** trained and evaluated | ✅ Done (2026-11-08) | `training/runs/v1/`, `eval/results/v1*/` |
| **Model v2** (after v1 error analysis) | ✅ Done (2026-11-09): 87% vs v1 72% in the same run | `training/runs/v2/`, `eval/results/v2/`, [RUN_ON_4060.md](RUN_ON_4060.md) |
| **Report** (figures and v2 results) | ✅ Built (2026-11-11); team names, personal sections and two screenshots still to fill in | `report/` |
| **Slides, demo rehearsal** | ⬜ To do | [DEMO.md](DEMO.md) |

## What is left, in order

1. **Demo laptop:** install Ollama, pull the base models, register the v2 `.gguf` from the Drive as `patchai-3b` and the v1 `.gguf` as `patchai-3b-v1` (`python training/export.py --gguf <file> --name <name>`), then `patchai doctor --warm`.
2. **Full logs:** extract `v2_full_eval_logs.zip` into `eval/results/v2/full/` (the case explorer and the replay fallback use it), and commit it.
3. **Report:** fill in the yellow placeholders (team names, personal contributions, two screenshots), then `npm run build` in `report/`.
4. **Slides:** results from `eval/results/v2/results.md`, figures from `report/fig/`.
5. **Rehearse the demo 2–3 times** with [DEMO.md](DEMO.md) and record a backup video.

## Team split

| Person | Owns | Explains in the viva |
| --- | --- | --- |
| **A: Training** (the 4060 owner) | `training/*`: dataset, SFT, export, DPO | How the model was trained, the data, the loss curves |
| **B: RAG** | `rag_index.py`, `rag_search.py`, `embeddings.py`, `data/knowledge/`, `data/fix_examples/` | Chunking, hybrid search, rank fusion, reranking |
| **C: Model and fixing** | `prompts.py`, `llm.py`, `fixer.py`, `patching.py`, `pipeline.py` | Prompt design, structured output, the retry loop |
| **D: Detection and checks** | `scan.py`, `context.py`, `guard.py`, `checks.py`, `data/semgrep_rules.yaml`, `demo_projects/` | Scanners, taint rules, the guard, attack tests, fake fixes |
| **E: Interface and evaluation** | `app/`, `extension/`, `server.py`, `review.py`, `eval/`, `metrics.py` | The review flow, the benchmark, the results |

**A and C must agree before the final training run:** the model learns the exact prompt in `prompts.py`.

## Design decisions (and why)

| Decision | Why |
| --- | --- |
| The model returns the whole fixed function, not a diff | Small models often write broken diffs. We splice the function back in and compute the diff ourselves |
| Structured JSON output (enforced by Ollama) | The pipeline can always read the answer. "Unreadable answer" is still measured, because the prompt also asks for it |
| Checks run on a temporary copy | The real project is only changed by `review.approve()` |
| An attack test per vulnerability, plus the re-scan | A scanner can be fooled ("fake fix"); a working attack can't |
| Vectors stored as NumPy files, not a vector database | A few thousand chunks need no server; it's simpler and fully offline |
| fastembed (ONNX) for embeddings and reranking | Real models without PyTorch on every laptop; falls back to an offline embedder |
| Our own Semgrep taint rules for CWE-22 and CWE-79 | Bandit can't see path traversal or reflected XSS; the rules are short and explainable |
| Training templates ≠ evaluation templates | The test measures learning the vulnerability type, not memorising templates |
| DPO pairs = the correct fix vs the model's own failed fix | The "rejected" side is exactly the mistakes the model really makes |
| Retries show the previous fix and the real error | v1 showed only a vague error, and the model repeated the same wrong fix in half its retries |
| The parser strips prompt tags the model echoes | Otherwise a correct fix wrapped in `<vulnerable_code>` counts as a syntax error, which made the v1 comparison unfair to the normal models |
| Real CVE fixes are filtered by our own scanners | CVEfixes is noisy; keeping only fixes our scanners confirm makes every real example consistent with how the pipeline judges fixes |
| No servers, databases, queues or cloud | It's a local research prototype; infrastructure adds work but nothing to measure |

## Rules

See [AGENTS.md](../AGENTS.md) (for people and AI coding tools alike).
