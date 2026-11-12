# Demo guide

Everything needed to show PatchAI in a viva: what to check beforehand, a ten-minute script, what to do when something fails, and where the answers to likely questions are.

## Before the demo (the day before, and again 15 minutes before)

| Check | How | Expected |
| --- | --- | --- |
| Ollama is running | `ollama list` | `patchai-3b`, `qwen2.5-coder:3b` (and `patchai-3b-v1`, `qwen2.5-coder:7b` for the comparison) |
| Everything is installed | `patchai doctor --warm` | every line green; "Model loaded in N s" |
| Embeddings are downloaded | `patchai doctor` once **while online** | "Embeddings: BAAI/bge-small-en-v1.5", not "hash" |
| The app opens | `patchai app` | the sidebar shows four green dots |
| The demo shop is fresh | sidebar → **Reset demo shop** | the Overview checklist is all ✅ |
| The extension is installed | `code --list-extensions \| findstr patchai` | `patchai-team.patchai` |
| Recorded runs are present | Results page | run `v2` with four models |
| Full logs (for replay) | `eval/results/v2/full/patchai-3b/` exists | 53 files |
| Backup video | on the laptop **and** on a USB stick | plays offline |

Close other heavy programs. Plug the laptop in. `keep_alive` keeps the model in memory for 30 minutes after each fix; run **Warm up model** again if the demo starts later than that.

## The ten-minute script

| # | Page | Do | Say |
| --- | --- | --- | --- |
| 1 | Overview | Point at the pipeline diagram and the four numbers | "A 3B model we trained ourselves reaches 87%, next to 91% for a model more than twice its size, at a third of the time." |
| 2 | Fix | **Scan project** → seven findings, one per type. Select the SQL injection. Open **The attack PatchAI will try** | "This is the real attack. A fix only counts if this attack fails afterwards." |
| 3 | Fix | **Fix with AI**. Watch the five steps. Then: before/after, the five checks, **What the AI read**, **The exact prompt** | "The model saw a security guide, the shop's own database helper, and a similar past fix." |
| 4 | Fix → Decisions | **Approve and apply**. The finding is gone from the rescan. Show the entry on **Decisions** | "Nothing changes until a human approves, and every decision is logged." |
| 5 | Compare | Select the **hard-coded secret**, models v1 and v2, **Run comparison**. Open v1's attempts | "v1 crashed on import because it learned `os.environ['X']`. We found that in the logs and fixed the training data." |
| 6 | Results | Fix rate with intervals → accuracy against speed → heat map → **Read this honestly**. Click a failed case → **Open in the case explorer** | "The intervals of v2 and the 7B overlap, so we don't claim to beat it." |
| 7 | Training | Loss curves, data v1 against v2, one real CVE fix | "21 real CVE fixes from open-source projects, filtered by our own scanners." |
| 8 | RAG | Type a query; show the meaning rank, keyword rank and final score | "Two searches, merged by rank fusion, then a reranker reads query and text together." |
| 9 | VS Code | **PatchAI: Open Demo Project** → underlines and side bar → CodeLens **Fix** → live panel → **Accept** → **Undo** | "The same pipeline, where developers already work." |
| 10 | — | One limitation, out loud | "Path traversal and secrets are still the weak types, and the benchmark is our own." |

Best live bugs: **SQL injection** (fast, clean, clear attack) and **command injection**. Avoid **XSS** live: v2 failed the demo-shop XSS case in the recorded run.

## When something fails

| Problem | What to do |
| --- | --- |
| Ollama or the model is not available | Fix page: **Replay the recorded fix for this bug**. Compare page: **Load the recorded comparison (run v2)**. Both are clearly labelled as recorded. Results, Case explorer, Training and RAG need no model at all. |
| A live fix is slow (no GPU) | Keep talking through the RAG and prompt sections while it runs; use the replay for the next one. |
| A live fix fails | Good material: open the attempts and show what the model was told next. That is the retry loop working. |
| The app shows an error | Refresh the browser tab. If it persists, restart with `patchai app`. |
| VS Code: "server offline" | Click the status bar item, or run **PatchAI: Check Setup** (it starts the server). **PatchAI: Show Server Log** shows why it stopped. |
| Nothing works | Play the backup video. |

## Likely viva questions

| Question | Short answer | Where it is shown |
| --- | --- | --- |
| Why fine-tune instead of prompting a bigger model? | A 3B model runs on a laptop and is 3× faster; fine-tuning took it from 49% to 87%, near the 7B. | Results page; `eval/results/v2/results.md` |
| How do you know a fix really works? | Project tests, a real attack test and a re-scan, all on a temporary copy. | Fix page → checks; `patchai/checks.py` |
| What is a fake fix? | A change that stops the scanner from flagging the code while the attack still works. The attack test catches it. | Results → mistakes chart; `patchai/metrics.py` (`fake_fix`) |
| What stops the model from doing something dangerous? | The safety guard: no `eval`/`shell=True`, no new third-party imports, no `# nosec`, same signature, at most 30 changed lines. | `patchai/guard.py` |
| Can untrusted code or text trick the model? | Code and retrieved text go into the prompt only inside tags, and the system prompt says they are data, not instructions. | Fix page → **The exact prompt**; `patchai/prompts.py` |
| How does RAG work here? | Embeddings and BM25 searches, merged with reciprocal rank fusion, then a cross-encoder reranker; functions the code calls come first. | RAG page; `patchai/rag_search.py` |
| Where does the training data come from? | 2,500 synthetic pairs from our generator plus 21 real CVE fixes (CVEfixes), every one checked by our own scanners. | Training page; `training/synth.py`, `training/real_data.py` |
| How did you get from v1 to v2? | We read every v1 failure, found two habits learned from the data and a vague retry prompt, and fixed exactly those. | Training page; `training/README.md` |
| Is the benchmark fair? | Every case is validated (detectable, exploitable, solvable); all models run through the same pipeline; we report intervals and the hand-written cases separately. | `eval/README.md` |
| Why not 100%? | The remaining failures are path traversal (where our own scanner rule rejects a sanitiser applied before the path is built) and credential checks. | `training/README.md` → "v2 results and what still fails" |
| Does any code leave the machine? | No: local models through Ollama, local embeddings, the server listens on 127.0.0.1. | `patchai/llm.py`, `patchai/server.py` |
| What would you do next? | Fix the path-traversal rule and re-score, more real-world data, DPO on the model's own mistakes, more languages. | `training/README.md`, report chapter 6 |
