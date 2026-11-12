# PatchAI: final polish, implementation plan

Written 2026-11-10 against commit `778597f` on `main` (v2 training and evaluation are merged).

This plan takes PatchAI from "every part works on its own" to "one finished system that demos well". It is written so that an AI coding agent (or a teammate) with no earlier context can pick up one work package and finish it.

---

## 0. How to use this plan

1. Read `AGENTS.md` and `README.md` first, then sections 1 to 4 of this file.
2. Do **one work package (WP) per session**, in the order given in section 5. Each WP lists the files it may create or edit. That list is the permission `AGENTS.md` asks for. If you need to touch any other file, stop and ask.
3. After every WP run `python -m pytest` (about 3 minutes) and report the exact command and its result. For WP4 also run `npm test` in `extension/`.
4. Do not start a WP whose "Needs" line is not satisfied.
5. When a step says **verify**, check it against the installed version instead of trusting this plan. Library APIs move.

### Frozen: never change these

| Thing | Why |
| --- | --- |
| `patchai/prompts.py` | The v2 model is trained on this exact format. Any change means retraining. |
| `patchai/models.py` | Every recorded result (`eval/results/*/full/*.json`) is parsed with these models. |
| `eval/cases/`, `demo_projects/vuln_shop/` | Intentionally vulnerable. Never "fix" them. |
| `eval/results/*/results.jsonl` | Recorded measurements. Charts and tables are regenerated from them, never edited by hand. |
| The Python core (`scan`, `context`, `fixer`, `guard`, `checks`, `patching`, `review`) | It is tidy and tested. Do not refactor it. Only the small changes named in WP2 are allowed. |

### Contract changes this plan approves

`AGENTS.md` says shared contracts change only with the team's agreement. The repo owner asked for this polish pass, so these additions are approved. All of them are **additive**: nothing existing is renamed or removed.

- `patchai/server.py` ↔ `extension/src/api.ts`: new endpoints `POST /fix/start`, `GET /fix/status/{job_id}`, `POST /demo`; new keys in `GET /health` (Appendix C).
- `config.yaml`: new keys `generation.keep_alive` and `paths.demo_workspace`.
- `patchai/metrics.py`: new helpers for model labels, order and colours (WP1).

### Security rules that matter most here

- Python: commands go to `subprocess` as a list. Never `shell=True`.
- TypeScript: start processes with `child_process.spawn(command, argsArray)`. Never `exec`, never `shell: true`.
- Everything from the server or from source code is HTML-escaped before it goes into the webview (`esc()` in the panel code).
- Never add `# nosec`, `# nosemgrep` or `# noqa`. (Some existing files have `# noqa: E402` next to `sys.path` imports. Leave those lines alone, and write new files so they do not need one.)

---

## 1. Where the project stands (verified on 2026-11-10)

| Fact | Evidence |
| --- | --- |
| `python -m pytest` passes: **69 passed** in 184 s | Windows 11, Python 3.11.9, `.venv` |
| The Streamlit app loads with no exception, even without Ollama | headless run with `streamlit.testing.v1.AppTest`; Streamlit 1.67.0 |
| The extension compiles (`npm run compile`, exit 0) | Node 24, TypeScript 5.9 |
| **The extension has never been run end to end** | `PROJECT_STORY.md` section 12, item 4 |
| **Ollama is not installed on the development laptop** | `ollama` is not on PATH |
| The v1 model file is on this laptop | `PatchAI_Final_Delivery-20261108T100730Z-1-001/PatchAI_Final_Delivery/Qwen2.5-Coder-3B-Instruct.Q4_K_M.gguf` (1.9 GB, git-ignored) |
| The v2 model file and `v2_full_eval_logs.zip` are **not** on this laptop | They are on the 4060 owner's machine or Google Drive |
| `eval/results/v1/full/` exists locally (git-ignored); `eval/results/v2/full/` does not | directory listing |
| `report/` (the Word report builder) is untracked local work | `git status` |

### The numbers (single source of truth)

Run `v2`, 2026-11-09, 53 test cases, every model through the same pipeline. Source: `eval/results/v2/results.jsonl`.

| Ollama name | Label to show | Fixed | Fix rate | 95% interval | First try | Fake fixes | Guard blocks | Avg attempts | Avg time | Demo shop |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `qwen2.5-coder:3b` | Qwen2.5-Coder 3B (base) | 26/53 | 49% | 36–62% | 38% | 23% | 15% | 2.2 | 9.1 s | 4/7 |
| `patchai-3b-v1` | PatchAI-3B v1 (ours) | 38/53 | 72% | 58–82% | 72% | 13% | 4% | 1.6 | 6.5 s | 6/7 |
| `patchai-3b` | PatchAI-3B v2 (ours) | 46/53 | **87%** | 75–93% | 87% | 6% | 0% | 1.3 | 6.2 s | 6/7 |
| `qwen2.5-coder:7b` | Qwen2.5-Coder 7B (base) | 48/53 | 91% | 80–96% | 91% | 4% | 14% | 1.2 | 20.1 s | 5/7 |

Fix rate per type in run `v2`:

| Type | Base 3B | Ours v1 | Ours v2 | Base 7B |
| --- | --- | --- | --- | --- |
| CWE-22 Path traversal | 29% | 71% | 57% | 100% |
| CWE-327 Weak cryptography | 44% | 56% | 100% | 100% |
| CWE-502 Unsafe deserialization | 100% | 100% | 100% | 100% |
| CWE-78 Command injection | 29% | 71% | 100% | 100% |
| CWE-79 XSS | 14% | 100% | 86% | 71% |
| CWE-798 Hard-coded secret | 57% | 0% | 57% | 71% |
| CWE-89 SQL injection | 57% | 100% | 100% | 86% |

The 7 cases v2 did not fix:

| Case | Check that failed on the last attempt | Note |
| --- | --- | --- |
| `cwe22_path_fstring_1`, `_2`, `_3` | `rescan` | Tests and the attack test **passed**. Only the scanner still flags the code. See WP5. |
| `cwe798_secret_compare_1`, `_2`, `_3` | `tests` | Marked as fake fix: an attempt fooled the scanner while the attack still worked. |
| `shop_cwe79` | `tests` | Hand-written demo-shop XSS. |

Other facts to keep straight:

- Training v2: 2,289 train / 252 validation examples (2,500 synthetic + 21 real CVE fixes from 14 CVEs), QLoRA rank 16, 2 epochs, 117.4 minutes on the RTX 4060, final validation loss 0.0303 (v1: 0.0342).
- Retries rescued **zero** cases for v1, v2 and the 7B in run `v2` (first-try rate equals fix rate). Only the base 3B gained from retries (6 cases).
- Run-to-run noise is about ±7 points: the same v1 model scored 79% in run `v1_rescored` and 72% in run `v2`. Always compare models **inside one run**.
- **Naming trap:** the Ollama name `patchai-3b` means **v1** in runs `v1` and `v1_rescored`, and **v2** in run `v2`. In run `v2`, v1 is called `patchai-3b-v1`.

---

## 2. Problems found

Each problem has an id that the work packages refer to.

### A. Things that can break the demo

| Id | Problem | Evidence |
| --- | --- | --- |
| A1 | Approving a fix in the app or the extension **edits the tracked demo shop**. After one demo the repo is dirty, later demos show fewer bugs, and tests that copy the shop start failing. `AGENTS.md` also forbids fixing it. | `app/review_app.py:54` (default project), `extension/.vscode/launch.json` (opens `demo_projects/vuln_shop`), `tests/conftest.py:25` |
| A2 | **Semgrep silently skips files that git ignores.** A copy of the demo shop inside a git-ignored folder of the repo shows only 5 of 7 vulnerability types (path traversal and XSS are missing). Verified on 2026-11-10: the same copy in a temp folder shows all 7. Any user project with ignored source files is affected. | `patchai/scan.py:112` (no `--no-git-ignore`) |
| A3 | An extension installed from a `.vsix` cannot start the server: it assumes the repo is the parent of the extension folder. | `extension/src/extension.ts:420` |
| A4 | A fix that takes longer than 5 minutes fails in the extension, because Node's `fetch` gives up waiting for headers after 300 s. Three attempts on a CPU-only laptop can take that long. | `extension/src/api.ts:161-165`, `:192` |
| A5 | If Ollama or the model is not available during the viva, the app can show nothing live: the Fix button is just disabled. | `app/review_app.py:165` |
| A6 | When `patchai-3b` is not installed, the pipeline silently uses the base model. The extension's status bar says only "default model". | `patchai/llm.py:55-57`, `extension/src/extension.ts:498` |
| A7 | The first fix is slow (the model loads) and Ollama unloads the model after 5 idle minutes. There is no warm-up and no keep-alive. | `patchai/llm.py:66-75` |

### B. Bugs and inconsistencies

| Id | Problem | Evidence |
| --- | --- | --- |
| B1 | Extension **Accept** replaces the whole file with text generated from an older version. It only checks for unsaved edits; edits saved after the fix was generated are lost. | `extension/src/extension.ts:312-325` (compare `patchai/review.py:29`) |
| B2 | Accept edits the file first and logs the decision second. If the server restarted, logging fails with 404 after the file was already changed. | `extension/src/extension.ts:333`, `patchai/server.py:72-74` |
| B3 | A skipped check is drawn as passed (✔) in the extension, because the TypeScript type has no `skipped` field. | `extension/src/api.ts:45-49`, `extension/src/panel.ts:191-193` |
| B4 | `report/figures.py` reads `data/training/dataset_info.json` as the **v1** dataset. After the v2 pull that file describes **v2**, so regenerating the figure draws wrong v1 bars. | `report/figures.py:174`; the v1 numbers live in `training/runs/v1/manifest.json` |
| B5 | The same model has different colours in different charts, and `patchai-3b` is shown without a version. | `eval/report.py:44-47`, `report/figures.py:26-29`, `app/review_app.py:236` |
| B6 | Scan-on-save shows an error popup on every save while the server is down. | `extension/src/extension.ts:98-100` |
| B7 | `training/runs/sft/loss.json` is v1's loss history in the wrong folder (its last value 0.03416 equals v1's manifest). | `training/runs/v1/manifest.json` |
| B8 | `training/runs/v2/Modelfile` is committed with a teammate's absolute path (`/home/adrish/...`). | file content |
| B9 | The extension README says `patchai.pythonPath` defaults to `python`; `package.json` says `""` (auto-detect `.venv`). | `extension/README.md`, `extension/package.json` |
| B10 | Quick fixes find their finding through a `Map` keyed by the Diagnostic **object**. That only works if VS Code hands back the same objects. | `extension/src/extension.ts:23`, `:192` |
| B11 | Names differ between the two interfaces: "Cross-site scripting" vs "Cross-site scripting (XSS)"; "Format / Tests" vs "Valid answer / Project tests". | `extension/src/api.ts:84`, `extension/src/panel.ts:57-63`, `app/review_app.py:32-38` |
| B12 | `requirements.txt` allows Streamlit 1.35, but the app uses `width="stretch"`, which older versions do not have. | `requirements.txt`, `app/review_app.py:139` |
| B13 | The extension activates only after a Python file is opened, so the status bar is missing in a freshly opened folder. | `extension/package.json:15-17` |
| B14 | Nothing stops two fixes from running at once in the extension. | `extension/src/extension.ts:208` |

### C. Stale documents

| Id | Where | What is stale |
| --- | --- | --- |
| C1 | `README.md:85`, `:120-134`, `:99`, `:184` | "until it's trained"; results show v1 only; test count |
| C2 | `PLAN.md:23-24`, `:26-32` | v2 and report still "To do" |
| C3 | `PROJECT_STORY.md:250`, `:296-301` | "results go to..."; "What's left" |
| C4 | `report/build_report.js:13`, `:325`, `:577-580` | v1 loss only; "v2 run pending"; `[[ ]]` placeholders |
| C5 | `RUN_ON_4060.md` and `INSTRUCTIONS_4060.md` | Two documents for the same job |

### D. Clutter

| Id | What |
| --- | --- |
| D1 | Uncommitted local edits to `.gitignore` and `.gitattributes`; untracked `run_4060.bat`, `INSTRUCTIONS_4060.md`, `PROJECT_STORY.md`. |
| D2 | Root folder holds `Markdown Live Preview.pdf` and `Project_Report-format.docx` (untracked, the owner's files). |
| D3 | 47 stale per-project indexes in `data/index/projects/` (git-ignored, safe to delete). |

---

## 3. What "done" looks like

**Review app.** `patchai app` opens a multi-page Streamlit app. A teacher sees, without any terminal work:

- an overview page with the pipeline diagram, the headline numbers and a system status check
- a live fix with a five-step progress strip, the attack that will be tried, before/after code, every check, every attempt, what RAG retrieved, and the exact prompt
- a model comparison (base 3B vs our v1 vs our v2 vs base 7B) on the same bug
- an evaluation dashboard built from the recorded data: fix rates with intervals, accuracy against speed, a per-type heat map, a case-by-case grid, failure reasons, and the v1 → v2 story
- a case explorer that replays any recorded benchmark run, attempt by attempt
- a training page: loss curves, data composition, the CVEfixes filter funnel, real CVE examples, settings
- a RAG page: search the knowledge base and see each ranking stage
- the decisions log

Every page still renders when Ollama is not running, and recorded runs can be replayed as a fallback.

**VS Code extension.** `code --install-extension patchai.vsix`, open any Python folder, and:

- the server starts by itself and the workspace is scanned
- findings appear as underlines, in the Problems panel, and in a PatchAI side bar
- one click fixes a finding, with live progress and a review panel
- Accept is safe (stale-file check, one-step undo), Reject is logged
- a walkthrough, a setup check and an "Open Demo Project" command make the first five minutes obvious

**Consistency.** One set of names, colours and numbers everywhere: app, extension, charts, README, report.

---

## 4. Decisions already made

Do not reopen these. They exist so that separate sessions produce parts that fit together.

### 4.1 Model names, order and colours

One place defines them: `patchai/metrics.py` (WP1). Everything else imports from there. The extension cannot import Python, so it copies the labels.

| Canonical id | Label | Colour |
| --- | --- | --- |
| `qwen2.5-coder:3b` | Qwen2.5-Coder 3B (base) | `#eb6834` |
| `patchai-3b-v1` | PatchAI-3B v1 (ours) | `#c9418f` (the palette's pink `#e87ba4` failed a colour-vision check against the base-3B orange, so it was darkened) |
| `patchai-3b` | PatchAI-3B v2 (ours) | `#2a78d6` |
| `patchai-3b-dpo` | PatchAI-3B v2 + DPO (ours) | `#eda100` |
| `qwen2.5-coder:7b` | Qwen2.5-Coder 7B (base) | `#1baf7a` |
| anything else | the Ollama name itself | next unused colour of `SERIES` in `eval/report.py` |

- The table order is the display order in every chart and table (it tells the story: base → v1 → v2 → bigger model).
- **Canonical id rule:** in a run whose name starts with `v1`, the raw name `patchai-3b` is canonical id `patchai-3b-v1`. In every other run the raw name is the canonical id.
- All colours come from the palette already used in `eval/report.py`. Colour follows the model, never its rank.

### 4.2 Wording

| Thing | Text to show |
| --- | --- |
| verdict `fixed` | Fixed and verified |
| verdict `failed` | Not fixed |
| verdict `cannot_fix` | The model could not fix this safely |
| verdict `false_positive` | The model says this is a false alarm |
| check `format` | Readable answer |
| check `guard` | Safety guard |
| check `tests` | Project tests |
| check `security_test` | Attack test |
| check `rescan` | Re-scan |
| a skipped check | "skipped" with a neutral icon, never ✔ |
| vulnerability names | exactly `CWE_NAMES` in `patchai/models.py` (so "Cross-site scripting (XSS)") |

### 4.3 Other decisions

- **Charts:** Altair inside the app (it ships with Streamlit, no new dependency). Matplotlib stays for the PNG files of `eval/report.py` and `report/figures.py`.
- **Demo workspace:** demos run on a copy of the demo shop at `data/demo_workspace/vuln_shop`, created and reset by `patchai/demo.py`. The tracked shop is never edited.
- **Live progress in VS Code:** the server runs a fix as a job in a background thread, and the extension asks for its status every half second. No streaming, no queue.
- **Server for the extension:** the extension starts the server as a child process (not in a terminal), shows its output in an Output channel, and waits until `/health` answers.
- **No new infrastructure and no new Python dependencies.** One new dev dependency in the extension: `@vscode/vsce` for packaging.

---

## 5. Work packages

```
WP0  human prerequisites  ─┐
WP1  housekeeping         ─┼─► WP2 core ─┬─► WP3 app        ─┐
                           │             ├─► WP4 extension  ─┼─► WP6 docs ─► WP7 release
                           └─────────────┴─► WP5 evaluation ─┘
```

WP3, WP4 and WP5 do not depend on each other and can run in parallel once WP2 is merged.

| WP | Size | Needs |
| --- | --- | --- |
| WP0 | 1 hour of human time, mostly downloads | nothing |
| WP1 | small | nothing |
| WP2 | medium | WP1 |
| WP3 | large | WP2; WP0 for the live checks |
| WP4 | large | WP2; WP0 for the live checks |
| WP5 | medium | WP1; the v2 full logs from WP0 |
| WP6 | small | WP3, WP4, WP5 |
| WP7 | small | everything |

---

### WP0. Human prerequisites (a person must do these)

A model cannot do these. Until they are done, live fixes cannot be tested on this laptop; everything else can.

1. **Install Ollama** from https://ollama.com and make sure `ollama` works in a terminal.
2. **Base models:** `ollama pull qwen2.5-coder:3b` and `ollama pull qwen2.5-coder:7b` (the 7B is 4.7 GB; skip it if the demo laptop is short on memory).
3. **The v2 model:** download the v2 `.gguf` from the team's Google Drive, then
   ```powershell
   python training/export.py --gguf <path-to-v2>.gguf --name patchai-3b
   ```
4. **The v1 model** (already on this laptop), for the v1 vs v2 comparison:
   ```powershell
   python training/export.py --gguf "PatchAI_Final_Delivery-20261108T100730Z-1-001\PatchAI_Final_Delivery\Qwen2.5-Coder-3B-Instruct.Q4_K_M.gguf" --name patchai-3b-v1
   ```
   Do step 2 first: `export.py` copies the chat template from `qwen2.5-coder:3b`.
5. **The v2 full logs:** download `v2_full_eval_logs.zip` and extract it so that `eval/results/v2/full/patchai-3b/shop_cwe89.json` exists. There should be four model folders with 53 files each.
6. Run `patchai doctor`. Every line should be green.
7. **Decisions for the owner** (defaults in brackets):
   - Commit `eval/results/v2/full/` to git, about 2.5 MB of JSON? [yes: the case explorer and the replay fallback then work after a plain `git pull`]
   - A licence for the repo and the extension? [none: do not invent one]
   - May the Semgrep path-traversal rule be changed and v2 re-scored if WP5 shows it rejects correct fixes? [no: analyse and report only]
   - Commit `report/` (without `node_modules`)? [yes]
   - What to do with `Markdown Live Preview.pdf` and `Project_Report-format.docx`? [leave them; add both to `.gitignore`]

---

### WP1. Housekeeping and one source of truth

**Goal:** names, colours, files and folders are consistent before anything is built on them. No behaviour changes.

**Files:** `patchai/metrics.py`, `eval/report.py`, `tests/test_units.py`, `.gitignore`, `.gitattributes`, `pyproject.toml`, `requirements.txt`, `training/runs/sft/loss.json` (move), `training/runs/v2/Modelfile` (delete), `RUN_ON_4060.md`, `INSTRUCTIONS_4060.md`, `run_4060.bat`, `PLAN.md` (one link), and the regenerated files under `eval/results/{v1,v1_rescored,v2}/`.

**Steps**

1. **Model labels in `patchai/metrics.py`** (fixes B5). Add, with docstrings:
   ```python
   MODEL_INFO: dict[str, tuple[str, str]] = {   # canonical id -> (label, colour), in display order
       "qwen2.5-coder:3b": ("Qwen2.5-Coder 3B (base)", "#eb6834"),
       "patchai-3b-v1": ("PatchAI-3B v1 (ours)", "#e87ba4"),
       "patchai-3b": ("PatchAI-3B v2 (ours)", "#2a78d6"),
       "patchai-3b-dpo": ("PatchAI-3B v2 + DPO (ours)", "#eda100"),
       "qwen2.5-coder:7b": ("Qwen2.5-Coder 7B (base)", "#1baf7a"),
   }

   def canonical_model(model: str, run: str = "") -> str: ...   # the rule in section 4.1
   def model_label(model: str, run: str = "") -> str: ...       # unknown models: the name itself
   def model_color(model: str, run: str = "") -> str: ...       # unknown models: a fixed grey "#8a8984"
   def model_order(models: list[str], run: str = "") -> list[str]: ...  # MODEL_INFO order, unknown ones last by name
   ```
   A model name with a ` [no RAG]` suffix (written by `eval/run_eval.py --no-rag`) keeps the suffix in its label.
   Add tests to `tests/test_units.py`: the canonical rule for runs `v1`, `v1_rescored`, `v2`; label, colour and order for known and unknown names.

2. **`eval/report.py` uses them.** Give `model_colors` the run name and build it from `model_order` and `model_color`. Chart axes, legends and the tables in `results.md` show `model_label(...)`. `summary.csv` and `by_cwe.csv` keep the raw Ollama names (they are data files). Then regenerate, with no model needed:
   ```powershell
   python eval/report.py --run v1
   python eval/report.py --run v1_rescored
   python eval/report.py --run v2
   ```
   Check: the fix rates in each `results.md` are unchanged (v2: 49 / 72 / 87 / 91), and v2's PatchAI bars are blue in all four PNGs.

3. **Loss file (B7):** `git mv training/runs/sft/loss.json training/runs/v1/loss.json`. The `sft` folder disappears.

4. **Modelfile (B8):** `git rm training/runs/v2/Modelfile` and add `training/runs/*/Modelfile` to `.gitignore`. `export.py` writes it again whenever a model is registered.

5. **`.gitignore`:** keep the two local additions (`training/runs/*/.cache/`, `report/node_modules/`) and add:
   ```
   data/demo_workspace/
   training/runs/*/Modelfile
   Markdown Live Preview.pdf
   Project_Report-format.docx
   ```
   If the owner said yes in WP0.7, add `!eval/results/v2/full/` on the line after `eval/results/*/full/`, and check with `git status` that the 212 JSON files show up.

6. **4060 documents (C5):** merge `INSTRUCTIONS_4060.md` (the newer one, it covers `run_4060.bat` and the troubleshooting prompt) into `RUN_ON_4060.md`, then delete `INSTRUCTIONS_4060.md`. Keep the file name `RUN_ON_4060.md` because `PLAN.md` and `training/README.md` link to it. Add a first line: "v2 was trained with this procedure on 2026-11-09. Keep it for re-runs."

7. **`pyproject.toml`:** version `1.0.0`. Make `pip install -e .` install the dependencies too:
   ```toml
   [project]
   dynamic = ["dependencies"]

   [tool.setuptools.dynamic]
   dependencies = {file = ["requirements.txt"]}
   ```
   **Verify** in a throwaway venv that `pip install -e .` still works with the comment lines in `requirements.txt`. If it does not, drop this step and say so.

8. **`requirements.txt` (B12):** raise the Streamlit floor to the lowest version that has every API the app uses. If you cannot establish that, use the tested version: `streamlit>=1.67`.

9. **Commit the loose files (D1):** `.gitattributes`, `.gitignore`, `run_4060.bat`, `PROJECT_STORY.md`. Commit `report/` if the owner agreed. Only commit when the owner asks for a commit.

**Done when:** tests pass; the three `results.md` files show labels; `git status` shows no stray files in the root except the two ignored owner files.

---

### WP2. Core: model serving, demo workspace, server API

**Goal:** the shared Python layer that both interfaces need. Small, tested additions.

**Files:** `patchai/scan.py` (one flag), `patchai/llm.py`, `patchai/demo.py` (new), `patchai/rag_search.py`, `patchai/server.py`, `patchai/cli.py`, `config.yaml`, `tests/conftest.py`, `tests/test_server.py`, `tests/test_units.py`, `tests/test_rag_and_review.py`, `tests/test_demo.py` (new).

**Steps**

1. **Semgrep must not depend on git (A2).** In `run_semgrep` add `"--no-git-ignore"` to the command list. `SKIP_DIRS` already keeps virtual environments and `node_modules` out.
   Test (`tests/test_demo.py` or `tests/test_units.py`): create a git repo in `tmp_path` (`git init`, a `.gitignore` containing `shop_copy/`), copy the demo shop into `shop_copy/`, scan it, and assert all 7 CWE ids are found. Skip the test when `shutil.which("git")` or `semgrep_available()` is false.
   This changes no recorded result: benchmark cases are tracked files and training data is scanned in temp folders.

2. **`config.yaml`:** add
   ```yaml
   generation:
     keep_alive: 30m   # how long Ollama keeps the model in memory after a call
   paths:
     demo_workspace: data/demo_workspace
   ```
   In `tests/conftest.py` add `os.environ["PATCHAI_DEMO_WORKSPACE"] = str(_TMP / "demo_workspace")` next to the other overrides (`patchai.config.path` already supports this).

3. **`patchai/llm.py` (A6, A7).** It stays the only file that talks to a model.
   - `chat()`: pass `keep_alive=gen.get("keep_alive")` to `_client().chat(...)`.
   - New `warm_up(model: str) -> float`: loads the model with an empty `generate` call and the same `keep_alive`, returns the seconds it took, raises `LLMError` on failure. **Verify** the call against the installed `ollama` package.
   - New `model_status() -> dict` for the interfaces. It never raises:
     ```python
     {"ollama": bool,            # the server answers
      "installed": list[str],
      "default": str | None,     # what resolve_model(None) would use, None if nothing is usable
      "fine_tuned": bool,        # default starts with "patchai"
      "problem": str | None}     # one sentence for the user, None when everything is fine
     ```
     `problem` examples: "Ollama is not running. Start it with `ollama serve`." and "The fine-tuned model `patchai-3b` is not installed, so the base model `qwen2.5-coder:3b` is used. See training/README.md."
   - Tests: monkeypatch `llm.list_models` to return `[]`, `["qwen2.5-coder:3b"]` and `["patchai-3b", "qwen2.5-coder:3b"]`, and check the three statuses.

4. **`patchai/demo.py` (new, A1).** Top docstring: "A scratch copy of the demo shop, so demos never change the tracked vulnerable project."
   ```python
   SOURCE = ROOT / "demo_projects" / "vuln_shop"

   def demo_project(reset: bool = False) -> Path:
       """The demo copy (created on first use). `reset=True` throws away every applied fix."""
   ```
   The target is `path("demo_workspace") / "vuln_shop"`. Copy with `shutil.copytree(..., ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))`. On reset use `shutil.rmtree` first.
   Tests (`tests/test_demo.py`): the copy has `shop/db.py`; changing a file and calling `demo_project()` keeps the change; `demo_project(reset=True)` restores it; the tracked shop's bytes never change.

5. **`patchai/rag_search.py`: expose the ranking stages** (for the RAG page in WP3). Split `search()` without changing its results:
   ```python
   def rank(collection, query, where=None, rerank=True) -> list[dict]:
       """Every candidate with its place in each stage, best first:
       {"index", "meaning_rank", "keyword_rank", "fused", "score"}  (a rank is None when that search did not return it)"""

   def search(collection, source, query, k, where=None, rerank=True) -> list[RetrievedChunk]:
       # unchanged signature; now: rank(...)[:k] turned into RetrievedChunk
   ```
   Test: for a fixed query with the hash embedder, `search()` returns the same titles and scores before and after the change (compute "before" by running the old code once and pasting the expected titles into the test), and `rank()` returns non-decreasing `score` order with at least one row that has both ranks.

6. **`patchai/server.py`** (Appendix C has the exact shapes).
   - `/health`: add `version`, `root`, `ollama`, `fine_tuned`, `semgrep`, `problem`. Keep `ok`, `models`, `default_model` exactly as they are.
   - `POST /fix/start` and `GET /fix/status/{job_id}` (A4): a job runs `fix_finding` in a `threading.Thread(daemon=True)` and collects `on_event` calls in a list. Keep the jobs in a module-level dict and drop the oldest when there are more than 20. When a job finishes, store its result in `_recent_fixes` exactly like `/fix` does.
   - `POST /demo`: returns the demo workspace path, optionally reset.
   - `POST /fix` and `POST /decision` stay unchanged.
   - Tests in `tests/test_server.py`, following the existing `monkeypatch.setattr(server, "fix_finding", fake_fix)` pattern: start a job, poll until `done`, check the events and the result; unknown job id gives 404; `/demo` returns an existing folder that is not the tracked shop; `/health` still works without Ollama and has the new keys. The fake must accept `on_event` and call it at least once.

7. **`patchai/cli.py`.**
   - `patchai doctor`: use `llm.model_status()`; print which model fixes will use, and a yellow warning line when it is not the fine-tuned one. Add `--warm` to load the model and print the seconds.
   - `patchai demo [--reset]`: print the demo workspace path.
   - `patchai app`: run `[sys.executable, "-m", "streamlit", "run", str(ROOT / "app" / "review_app.py")]`.
   - `patchai serve [--port 8765]`: run the server with `uvicorn.run("patchai.server:app", host="127.0.0.1", port=port)`.

**Done when:** tests pass (expect about 80); `patchai doctor`, `patchai demo --reset` and `patchai serve` work by hand; `curl http://127.0.0.1:8765/health` shows the new keys.

---

### WP3. The review app

**Goal:** the app a teacher sees. It has to look finished, explain the system, show all the data, and never dead-end.

**Before writing code:** if your tool has a Streamlit skill (`developing-with-streamlit`), load it. Otherwise read the documentation of the **installed** Streamlit version. Do not write Streamlit code from memory.

**Files:** `app/review_app.py` (rewritten as the entry point), `app/ui.py` (new), `app/charts.py` (new), `app/views/*.py` (new, eight files), `.streamlit/config.toml` (new), `tests/test_app.py` (new), `requirements.txt` (only the Streamlit floor).

#### 3.1 Structure

```
app/
  review_app.py      entry point: page config, sidebar, navigation        (keep this name: README and PLAN use it)
  ui.py              shared widgets and cached data loaders
  charts.py          Altair chart builders (one function per chart)
  views/
    overview.py      what PatchAI is, headline numbers, system status
    fix.py           scan → fix → evidence → approve or reject           (the live demo)
    compare.py       one vulnerability through several models
    results.py       the evaluation dashboard
    cases.py         replay any recorded benchmark case
    training.py      how the model was trained
    rag.py           what the knowledge base contains and how search ranks it
    decisions.py     the decisions log
.streamlit/config.toml
```

Rules for these files:

- The folder is called `views`, not `pages`: Streamlit treats a `pages` folder specially.
- Each view is one file with one job and stays under about 150 lines. Shared code goes to `ui.py` or `charts.py`, not into a view.
- No `sys.path` tricks and no `# noqa`: `pip install -e .` makes `patchai` importable, and Streamlit puts `app/` on the path, so views write `import ui` and `import charts`. For the one import from `training/` (section 3.8), add the path inside the function that needs it.
- A view must work when run alone (the tests do that). So views read their settings through `ui.settings()`, which falls back to defaults when the sidebar has not run.
- Navigation: `st.navigation` with `st.Page` objects, grouped as **Demo** (Overview, Fix, Compare), **Evidence** (Results, Case explorer, Training, RAG) and **Log** (Decisions). **Verify** the API in the installed version.
- `.streamlit/config.toml`: a light theme with `primaryColor = "#2a78d6"`, and `[browser] gatherUsageStats = false` (the project claims to run offline).

#### 3.2 `app/ui.py`

Constants: the wording from section 4.2, severity icons, RAG source labels.

Cached loaders (use `st.cache_data`; pass the file's modification time as an argument so the cache refreshes when a file changes):

| Function | Returns | Reads |
| --- | --- | --- |
| `runs()` | run names, newest first by the manifest's `started` | `eval/results/*/manifest.json` |
| `records(run)` | list of dicts, with `model` replaced by its canonical id | `eval/results/<run>/results.jsonl` |
| `cases()` | case id → case dict | `eval/cases/manifest.json` |
| `recorded(run, model, case_id)` | `FixResult` or `None` | `eval/results/<run>/full/<folder>/<case>.json`; the folder name is the raw model name with every character that is not a letter, digit, `-`, `_` or `.` replaced by `_` (same as `safe_name` in `eval/run_eval.py`) |
| `training_run(name)` | manifest dict and loss dict | `training/runs/<name>/manifest.json`, `loss.json` |
| `status()` | `llm.model_status()` plus `semgrep_available()` | cached for 10 seconds |

Widgets:

| Function | Shows |
| --- | --- |
| `settings()` | a small dataclass: project folder, model, reviewer. Read from `st.session_state` with defaults (demo workspace, the status default model, the OS user name). |
| `sidebar()` | described in 3.3 |
| `pipeline_strip(active, failed=False)` | five boxes in a row: Scanner · RAG · Our model · Checks · Human, with done / active / waiting states |
| `show_result(result, compact=False, key="")` | everything about one `FixResult`, described in 3.5. Used by Fix, Compare and Case explorer. |
| `empty_state(text, hint)` | a consistent "nothing here yet" box with the command or click that fixes it |

#### 3.3 Sidebar (in the entry point, shown on every page)

- Title and one line: "AI security fixes with a fine-tuned model and RAG. Nothing changes without your approval."
- **System status**, four lines with a green or red dot: Ollama · model (label, and "fine-tuned" or "base model, fallback") · Semgrep · embeddings. Under it the `problem` sentence from `model_status()` when there is one.
- **Project:** a choice between "Demo shop (safe copy)" and "Another folder". The first uses `demo.demo_project()`. The second shows a text input, and an error if the folder does not exist.
- A **Reset demo shop** button (only for the demo choice): calls `demo.demo_project(reset=True)`, clears the findings and results in the session, and reruns.
- **Model:** a select box of installed models in `metrics.model_order`, shown with `model_label`. Disabled, with a note, when Ollama is not running.
- A **Warm up model** button: `llm.warm_up(model)` in a spinner, then "Loaded in N s".
- **Reviewer name.**

Session-state keys, so views agree: `project`, `model`, `reviewer`, `findings` (list of `Finding`), `results` (finding id → `FixResult`), `comparison` (list of `FixResult`), `selected_case` (run, model, case id).

#### 3.4 Overview (`views/overview.py`)

1. Title, one sentence, and three badges: "runs offline", "fine-tuned 3B model", "every fix is proven".
2. The pipeline as a diagram: `st.graphviz_chart` with a DOT string (five boxes left to right, plus the dashed "failed: previous fix + exact error, max 3" arrow from Checks back to Our model). **Verify** it renders without the `graphviz` Python package.
3. **Headline numbers**, computed from the newest run that contains `patchai-3b` (never typed in by hand): four `st.metric` cards in story order. Each shows the fix rate; the two PatchAI cards also show the change against the base 3B in percentage points. Under them one sentence built from the data, in this form: "Fine-tuning took the 3B model from 49% to 87% on our 53-case benchmark, close to the 7B model's 91%, at a third of the time per fix (6 s vs 20 s)."
4. **What each page shows:** a short list with page links.
5. **Before a demo:** a checklist driven by `ui.status()`: Ollama running, fine-tuned model installed, Semgrep installed, embeddings loaded (not the hash fallback), recorded runs present, demo shop in its original state.

#### 3.5 Fix (`views/fix.py`): the live demo

Layout, top to bottom:

1. `pipeline_strip`: step 1 is active before a scan, step 5 after a verified fix.
2. **Scan** button. After the scan:
   - a row of counts: total, high, medium, and how many of the 7 types were found
   - a warning when Semgrep is missing: "Path traversal and XSS cannot be detected without Semgrep."
   - the findings table (severity, type, file:line, scanner rule, message) as a selectable table: one row selected at a time, first row by default. **Verify** the row-selection API of `st.dataframe` in the installed version; fall back to the current select box.
3. **The selected finding**, in two columns:
   - left: "The code the AI may rewrite", with line numbers starting at the function's first line, and a caption naming the flagged line
   - right: "What an attacker can do" (one sentence per type, taken from the README table), and an expander "The attack PatchAI will try" that shows the source of `checks.security_test_files(project, finding)`. When there is none: "This project has no attack test for this type, so that check will be skipped."
4. **Fix with AI** button (disabled with the reason when no model is usable). While it runs:
   - `pipeline_strip` is redrawn from the progress events through an `st.empty()` placeholder. Mapping: `context`, `retrieve` → RAG; `generate` → Our model; `guard`, `tests`, `security_test`, `rescan` → Checks; `retry` → back to Our model; `done` → Human; `error` → the active step turns red.
   - an `st.status` box lists each event as it arrives.
5. **When Ollama is not usable:** in place of the button's result, offer **Replay a recorded fix**. It is only available for demo-shop findings: find the case in `ui.cases()` with `source == "handwritten"` and the same `cwe` and `file`, load `ui.recorded("v2", "patchai-3b", case_id)`, and show it only when the recorded `context.source` equals the current code. Label it clearly: "Recorded on 2026-11-09 on the RTX 4060 laptop. Not a live run." A replayed result is view-only: no Approve button.
6. **The result**, drawn by `ui.show_result`:
   - a verdict banner (wording from 4.2) with model label, attempts, seconds and total tokens
   - the explanation and the model's confidence
   - tabs **Before / after** (two code columns: `context.source` and the final `fixed_code`) and **Diff** (the unified diff)
   - **Checks:** five small cards in pipeline order with pass / fail / skipped and the details text
   - **Attempts:** one expander per attempt (the final one open). Each shows its checks, its diff, and for a failed attempt a quoted block "What the model was told next" containing the failed checks' details. When the answer could not be parsed, show the raw output.
   - **What the AI read (RAG):** grouped by source, each chunk with its relevance as a progress bar and its text in an expander
   - an expander **The exact prompt (attempt 1)**: the two messages from `prompts.build_prompt(result.finding, result.context, result.retrieved)`
   - with `compact=True` (used by Compare) only the banner, the explanation, the diff and the checks are shown
7. **Your decision** (live results only):
   - verdict `fixed`: **Approve and apply** calls `review.approve`, rescans, and reruns; next to it the reject form
   - otherwise: a caption that unverified fixes cannot be applied, plus the reject form
   - the reject form keeps the current reasons and the optional note

Do not change `review.py` or `pipeline.py` for this page.

#### 3.6 Compare (`views/compare.py`)

- Needs findings from the Fix page; otherwise an `empty_state` with a link.
- Pick a finding and the models. Default: every installed model among the four of section 4.1.
- **Run comparison** runs them one after another, each with its own status box.
- Result: a summary table first (model label, verdict, attempts, seconds, tokens, changed lines), then one column per model with `show_result(compact=True)`.
- When Ollama is not usable and the finding is a demo-shop case: **Load the recorded comparison** from `eval/results/v2/full/` for all four models, labelled as recorded.
- A caption suggests the best demo: "Try the hard-coded secret: v1 fails it, v2 fixes it."

#### 3.7 Results (`views/results.py`): the evaluation dashboard

All charts come from `app/charts.py`, built from `metrics.summarize`, `metrics.fix_rate_by_cwe`, `metrics.failure_reasons` and the raw records. Each chart function takes plain data and returns an Altair chart with the colours and order of section 4.1, a tooltip on every mark, and a one-sentence caption that says what to look at.

Before drawing charts, read the dataviz guidance your tool has, if any. Minimum rules: label values directly on bars, start bar axes at zero, show percentages as percentages, keep the model order fixed, and never use colour alone to carry meaning (add the label).

1. Run selector (default: the newest run), with the run's date, number of cases, prompt version and commit from its manifest.
2. **Headline cards:** one per model, as on the Overview, with the interval and `n` in the help text.
3. **Fix rate with 95% intervals:** horizontal bars with error bars (Wilson interval), value labels like "87% (46/53)".
4. **Accuracy against speed:** a scatter plot, x = average seconds per fix, y = fix rate, one labelled point per model. This is the chart for "almost as good as the 7B at a third of the time".
5. **Fix rate per vulnerability type:** a heat map (rows = types with their names, columns = models, the percentage written in every cell). A caption gives the number of cases per type.
6. **First try or after a retry:** stacked horizontal bars, first-try share solid and retry share lighter.
7. **Mistakes the pipeline caught:** grouped bars for fake fixes, guard blocks and unreadable answers.
8. **Why unfixed cases failed:** stacked horizontal bars, with the labels of `FAILURE_LABELS` in `eval/report.py`.
9. **Every case:** a grid with one row per case and one column per model; each cell is coloured "fixed on first try", "fixed after a retry" or "not fixed" and its tooltip names the failed check. Under it, a select box of cases and a button **Open in the case explorer** (sets `selected_case` and switches page).
10. **Hand-written demo-shop cases:** a small table, per model, of the 7 shop cases.
11. **From v1 to v2** (only when the run contains both `patchai-3b-v1` and `patchai-3b`): a per-type chart with one line per type from the v1 value to the v2 value, and next to it the table of changes from `training/README.md` ("v1 → v2: what we changed").
12. **Read this honestly** (always visible, not hidden in an expander): four bullets. With 53 cases the intervals of v2 and the 7B overlap. Run-to-run noise is about ±7 points, so compare inside one run. Generated cases come from templates; the hand-written shop cases are shown separately. An attack test proves that the attacks we wrote fail, not every possible attack.
13. Download buttons for `summary.csv` and `by_cwe.csv`, and an expander with the PNG charts that go into the report.

#### 3.8 Case explorer, Training, RAG, Decisions

**Case explorer (`views/cases.py`)**
- Filters: run, model, vulnerability type, outcome. Then a case select box. Starts from `selected_case` when it is set.
- Shows the case facts (id, type, pattern family, hand-written or generated), the vulnerable file, the attack test source, the recorded `FixResult` through `ui.show_result`, and the reference fix from `eval/cases/<id>/case.json` in an expander.
- When the run has no `full/` folder: an `empty_state` that says where the full logs come from (WP0, step 5).

**Training (`views/training.py`)**
- Header cards from `training/runs/v2/manifest.json`: base model, method (QLoRA, rank and alpha), epochs, learning rate, training minutes, train and validation examples, final validation loss.
- **Loss curves:** v1 and v2, training and validation, from the two `loss.json` files. Use a log y-axis or a zoom toggle; the first step is about 1.09 and the rest is below 0.1.
- **Training data, v1 against v2:** grouped bars of examples per type from each manifest's `dataset_info.by_cwe`, and three numbers under it: false alarms (643 → 200), retry examples, real-world examples (0 → 21).
- **Real CVE fixes:** a horizontal bar chart of `data/real_fixes/cvefixes_info.json` → `filtered` (the kept bar in a different colour), then a table of the 21 kept examples from `data/real_fixes/cvefixes.jsonl` (CVE id linked to `https://nvd.nist.gov/vuln/detail/<id>`, repository, type, function). Selecting one shows its vulnerable and fixed code side by side.
- **A synthetic training example:** a button that draws one pair from `training/synth.py` (`generate(...)`) and shows vulnerable and fixed code with its explanation.
- **Settings and why:** the table from `training/README.md`.
- **How the model is served:** GGUF, 4-bit (Q4_K_M), about 1.9 GB, through Ollama, temperature 0.1, context 8,192 tokens, JSON shape enforced.

**RAG (`views/rag.py`)**
- Three count cards: guide sections, past fixes, functions in the current project.
- **Try a search:** choose a collection, optionally a vulnerability type, type a query (pre-filled with a real one, for example "parameterized query placeholder sqlite3"). Show a table from `rag_search.rank`: title, place in the meaning search, place in the keyword search, fused score, reranker score. Then the top results' text in expanders.
- A sentence explaining the stages: two searches, rank fusion, reranker.
- **Read a guide:** pick a type and render its file from `data/knowledge/`.
- Say which embedder is active. When it is the hash fallback, show a warning that results are weaker.

**Decisions (`views/decisions.py`)**
- Three counts (approved, rejected, reviewers), the table newest first, and for the selected row its diff and reason. A download button for the log.

#### 3.9 Tests (`tests/test_app.py`)

With `streamlit.testing.v1.AppTest`, and no Ollama (the tests already run that way):

- the entry point and each of the eight views run with **no exception**
- the Results view shows the same fix rates as `metrics.summarize` for run `v2`
- the Fix view with Ollama unavailable shows the replay option or the "not running" message, never a crash
- the Case explorer shows its `empty_state` when a run has no `full/` folder
- no view writes into `demo_projects/` (compare a hash of the folder before and after)

`AppTest.from_file` resolves relative paths against the test file, so pass absolute paths.

#### 3.10 Manual check (needs WP0)

Run `patchai app` and walk through the demo script in Appendix E. Then stop Ollama and walk through it again using the replay fallback.

**Done when:** tests pass; both walk-throughs work; a second person can run the demo from Appendix E without help.

---

### WP4. The VS Code extension

**Goal:** install the `.vsix`, open a Python folder, and it is useful within a minute.

**Files:** `extension/src/extension.ts`, `api.ts`, `panel.ts` (edited); `extension/src/server.ts`, `findings.ts`, `fix.ts`, `render.ts` (new); `extension/package.json`, `package-lock.json`, `README.md`, `.vscodeignore`, `.vscode/launch.json`; `extension/CHANGELOG.md`, `extension/media/icon.png`, `extension/media/shield.svg`, `extension/media/walkthrough/*.md`, `extension/test/render.test.js` (new).

#### 4.1 File layout (one job per file)

| File | Job |
| --- | --- |
| `extension.ts` | `activate`: create the pieces, register commands, wire events. Nothing else. |
| `api.ts` | types and one function per server endpoint |
| `server.ts` | find the PatchAI folder and Python, start and stop the server, wait until it is healthy |
| `findings.ts` | the findings store, diagnostics, quick fixes, hovers, CodeLens, the side-bar tree, the status bar |
| `fix.ts` | the fix flow: start the job, show progress, accept, reject, diff |
| `panel.ts` | the webview panel: create it, pass messages |
| `render.ts` | pure functions that build the panel's HTML (no `vscode` import, so they can be tested with Node) |

#### 4.2 `api.ts`

- Add the missing fields so the types match `patchai/models.py`: `Finding.code`; `CheckResult.skipped`; `Attempt.raw_output`, `tokens_in`, `tokens_out`; `FixResult.error`.
- `CWE_NAMES`: copy `patchai/models.py` exactly (B11).
- `Health`: the new keys of Appendix C.
- New: `startFix(projectDir, finding, model)`, `fixStatus(jobId)`, `demoProject(reset)`. Keep `fix()` for compatibility but stop using it.
- Every request is now short, so one 30-second timeout is enough for all endpoints except `/scan` (3 minutes).

#### 4.3 `server.ts`: the server takes care of itself (A3)

- **`findPatchaiFolder()`**, first match wins. A folder counts when it contains both `patchai/server.py` and `config.yaml`.
  1. the setting `patchai.serverDir`
  2. each workspace folder, then its parents up to four levels
  3. the parent of the extension folder (development mode)
  4. the folder remembered in `globalState`
  5. only when the user started an action (never on start-up): a folder picker, "Select your PatchAI folder". Remember a valid choice in `globalState`.
- **`findPython(folder)`:** the setting `patchai.pythonPath` (a relative path is resolved against the folder); else `<folder>/.venv/Scripts/python.exe` on Windows or `<folder>/.venv/bin/python` elsewhere; else `python` (Windows) or `python3`.
- **`ensureServer(interactive)`:** if `/health` answers, done. Otherwise start
  `spawn(python, ["-m", "uvicorn", "patchai.server:app", "--host", "127.0.0.1", "--port", port], { cwd: folder })`,
  pipe stdout and stderr into an Output channel named "PatchAI Server", and poll `/health` every 500 ms for up to 60 s under a progress notification "Starting PatchAI…".
- If the process exits early, show an error with the last output lines and a specific hint. For "No module named": "Run `pip install -r requirements.txt` in <folder>, or set `patchai.pythonPath`." Offer a "Show log" button.
- Stop only a server this window started, on deactivation and through `PatchAI: Stop Server`.
- Commands: `patchai.startServer`, `patchai.stopServer`, `patchai.showServerLog`, `patchai.setFolder`.

#### 4.4 `findings.ts`: findings are visible everywhere

- **Store:** `Map<string, Finding>` keyed by `file_path|start_line|cwe`. The server already removes duplicates with exactly this key. Diagnostics, quick fixes, hovers and the tree all look findings up through it (fixes B10).
- **Diagnostics:** as today. A quick fix finds its finding by the diagnostic's source (`PatchAI`), start line and code value.
- **Side bar:** an activity-bar container "PatchAI" (icon `media/shield.svg`) with one tree view. Findings are grouped by file; each item shows the type name, the line and a severity icon; clicking opens the file at the line; an inline button runs the fix. The view title has Scan, Select Model and Check Setup buttons. When there are no findings, welcome content explains PatchAI in two lines and offers **Scan Workspace**, **Open Demo Project** and **Check Setup**.
- **Hover:** on a flagged line, a markdown hover with the type name, severity, one sentence on what an attacker can do, and a command link "Fix with PatchAI". Only `patchai.fix` may be enabled as a trusted command.
- **CodeLens:** above the flagged line, "🛡️ Fix <type name> with PatchAI".
- **Status bar:** one item with clear states: "PatchAI: starting…", "PatchAI: server offline" (click starts it), "PatchAI: scanning…", "PatchAI: 5 issues", "PatchAI: no issues", "PatchAI: fixing…". A second item shows the model that will be used, with its label, and a warning icon when it is not the fine-tuned model (A6).
- **When scans happen:** on start-up when the folder has Python files, the PatchAI folder is found without asking, and `patchai.scanOnOpen` is on; after a Python file is saved when `patchai.scanOnSave` is on (default now **true**); after a fix is accepted. Quiet scans never show popups (B6); they only update the status bar.
- Activation: add `workspaceContains:**/*.py` to `activationEvents` (B13).

#### 4.5 `fix.ts`: the fix flow

1. If a fix is already running, say so and return (B14).
2. `await ensureServer(true)`.
3. Read the file from disk and remember its text as `original`.
4. Open the panel at once in its "working" state: the finding's header, the five-step strip, and a live log.
5. `startFix`, then call `fixStatus` every 500 ms. Send new events to the panel (same event-to-step mapping as in WP3, section 3.5). The notification's Cancel button stops the polling and closes the panel; say that the server finishes the job anyway.
6. When the job is done, show the result page in the same panel, or the error.
7. **Accept** (B1, B2):
   - Compare the document's current text with `original`, ignoring line-ending differences. If they differ: "This file changed after the fix was made." with buttons **Fix again** and **Cancel**. Never overwrite.
   - Apply one `WorkspaceEdit`, save, then send the decision inside its own `try`. If logging fails, warn "The fix was applied, but the decision could not be logged." and continue.
   - Show "Fix applied to <file>." with an **Undo** button that reverts the edit and saves.
   - Rescan quietly.
8. **Reject:** as today (a reason is required).
9. New panel buttons: **Fix again** (same model) and **Try another model** (opens the model picker, then runs again).

#### 4.6 `render.ts` and `panel.ts`: the review panel

Move the HTML building from `panel.ts` into pure functions in `render.ts`: `renderWorking(finding, modelLabel, nonce)` and `renderResult(result, nonce)`. Keep the strict Content-Security-Policy with a nonce and the `esc()` function. `panel.ts` keeps the panel lifecycle and the message passing.

The result page, top to bottom:

1. Header: type name, verdict badge (wording from 4.2), file:line, rule, severity, model label, seconds.
2. The five-step strip with the final state of each step.
3. Buttons: Accept, Reject, Open in diff editor, Fix again, Try another model. Under them the note explaining why Accept is disabled, when it is.
4. `result.error`, when there is one.
5. Explanation and confidence.
6. Changes (the coloured diff).
7. Checks of the final attempt: ✔ passed, ✘ failed, – skipped (B3), with details.
8. Earlier attempts, collapsed. Each shows its checks, its diff and "What the model was told next".
9. What the AI read (grouped, with scores).
10. A small footer: attempts, tokens in and out.

#### 4.7 First five minutes

- **`PatchAI: Check Setup`:** calls `ensureServer`, then shows a checklist from `/health`: server, Ollama, fine-tuned model, Semgrep, each with a tick or a one-line fix.
- **`PatchAI: Open Demo Project`:** `ensureServer`, `POST /demo` with `reset: true`, remember the PatchAI folder in `globalState`, then open the returned folder with the `vscode.openFolder` command. The new window scans on start-up.
- **Walkthrough** (`contributes.walkthroughs`, shown on the Welcome page), four steps with short markdown files in `media/walkthrough/`: 1. Check the setup. 2. Open the demo project. 3. Scan and read a finding. 4. Fix it and review the evidence. Each step has a button that runs the matching command.
- **`.vscode/launch.json`:** the "on vuln_shop (demo)" configuration must no longer open the tracked shop (A1). Open no folder there and use Open Demo Project.

#### 4.8 `package.json` and packaging

- Version `1.0.0`. Add `"repository": {"type": "git", "url": "https://github.com/JoJoMan42/patchAI"}`, `"icon": "media/icon.png"`, keywords, and the new commands, views, walkthrough and settings.
- Settings: keep `serverUrl`, `model`, `pythonPath`, `serverDir` (describe it as "the PatchAI folder"); change `scanOnSave` to default `true`; add `scanOnOpen` (default `true`) and `autoStartServer` (default `true`).
- `media/icon.png`: 256×256, a simple shield on the primary blue. Generate it once with a short matplotlib script from your scratch folder and commit only the PNG. `media/shield.svg`: 24×24, one colour, `fill="currentColor"`.
- Scripts:
  ```json
  "compile": "tsc -p ./",
  "test": "npm run compile && node --test test/",
  "vscode:prepublish": "npm run compile",
  "package": "vsce package --no-dependencies --out patchai.vsix"
  ```
  Dev dependency: `@vscode/vsce`. Add `test/**` to `.vscodeignore`; keep `media/**` in the package.
- If `vsce` asks about a missing LICENSE, either add the licence the owner chose in WP0.7 or pass the flag that skips the question. Do not invent a licence. **Verify** the flag name with `npx vsce package --help`.
- Install and try: `npm run package`, then `code --install-extension extension/patchai.vsix --force`.

#### 4.9 Tests

`extension/test/render.test.js`, run with Node's built-in test runner against `out/render.js`:

- text from the model is escaped (`<script>` in an explanation appears as `&lt;script&gt;`)
- a skipped check is rendered as skipped, not as passed
- Accept is disabled for verdicts `failed`, `cannot_fix`, `false_positive`, and when `patched_file_text` is null
- diff lines get the right class (file header, hunk, added, removed, context)
- the working page contains the five step names

#### 4.10 Manual test matrix (needs WP0)

Run each line in a real VS Code window with the installed `.vsix`, and write the result into the session report.

| # | Do | Expect |
| --- | --- | --- |
| 1 | Install the `.vsix` in a clean window, open the walkthrough | four steps, every button works |
| 2 | Check Setup with the server stopped | the server starts; four ticks |
| 3 | Open Demo Project | new window, 7 findings within about 15 s, no popups |
| 4 | Look at `shop/db.py` | underline, hover with explanation, CodeLens, entry in the side bar and Problems |
| 5 | Fix the SQL injection | the panel shows the steps live, then "Fixed and verified" |
| 6 | Open in diff editor | current file left, proposed file right |
| 7 | Accept | file changes, underline disappears, side bar shows 6, decision is in `data/decisions.jsonl` |
| 8 | Undo from the notification | file is back, 7 findings after the rescan |
| 9 | Start a fix, edit and save the file, then Accept | "This file changed" message; nothing is overwritten |
| 10 | Fix the hard-coded secret with `patchai-3b-v1` | "Not fixed"; Accept disabled; Reject asks for a reason |
| 11 | Try another model → `patchai-3b` | "Fixed and verified" |
| 12 | Stop Ollama, fix something | a clear error that names Ollama; no hang |
| 13 | Kill the server process, save a Python file | status bar says offline; no popup |
| 14 | Open a folder without Python files | no scan, no server start, no errors |
| 15 | Check that `git status` in the repo shows no change under `demo_projects/` | clean |

**Done when:** `npm test` passes, `python -m pytest` passes, the matrix is filled in, and `extension/patchai.vsix` installs.

---

### WP5. Evaluation follow-up and report material

**Goal:** the v2 results are explained, and the report's figures and tables match them.

**Files:** `training/README.md`, `eval/README.md`, `report/figures.py`, `report/build_report.js`, `report/fig/*`, `report/PatchAI_Project_Report.docx`. Only with the owner's yes from WP0.7: `data/semgrep_rules.yaml`, `eval/results/v2_rescored/`.

**Steps**

1. **Read v2's seven failures** in `eval/results/v2/full/patchai-3b/` (ids in section 1). For each, note what the model wrote in every attempt and what each failed check said. Write one or two factual sentences per group into a new section "v2 results and what still fails" in `training/README.md`, next to the v2 numbers. Three questions to answer:
   - **Path traversal, `path_fstring`:** tests and the attack test pass, only the re-scan fails. Hypothesis to check, not to assume: the fix cleans the argument before it is put into the f-string (for example by re-assigning it from `os.path.basename`), and the Semgrep rule in `data/semgrep_rules.yaml` only recognises a sanitizer applied **after** the join, so it still reports the line. If that is what the logs show, these are correct fixes rejected by our own rule.
   - **Secrets, `secret_compare`:** which attempt fooled the scanner, and why do the tests fail?
   - **Retries:** v2 never recovered on attempts 2 or 3. Did it repeat itself, or change the fix in a way that did not help?
2. **Only with the owner's yes:** if the path-traversal hypothesis holds, extend the rule so that an argument sanitized before the join is not a source. Prove with a test that the rule still flags the unfixed benchmark files and the demo shop. Then re-score every model with `python eval/rescore.py --run v2` and `python eval/report.py --run v2_rescored`. Report **both** runs, say that the scoring rule changed after the results were seen and that it was applied to all four models, exactly as was done for v1. Without the yes: describe the finding as a limitation and change nothing.
3. **`report/figures.py`:**
   - B4: read the v1 dataset numbers from `training/runs/v1/manifest.json` → `dataset_info`, and the v2 numbers from `training/runs/v2/manifest.json`. Do not call the generator for counts that the manifest already has.
   - Use `metrics.model_label`, `model_color`, `model_order` in place of the local `MODEL` and `ORDER`.
   - Keep the v1 figures (they tell the first half of the story) and add v2 figures from run `v2`: `fix_rate_v2.png` (four models with intervals), `by_cwe_v2.png`, `speed_accuracy_v2.png`, `v1_to_v2.png` (per-type change), and `loss_v1_v2.png` from the two `loss.json` files.
   - Run it and look at every PNG.
4. **`report/build_report.js`:** fill the v2 table from `eval/results/v2/summary.csv` and `by_cwe.csv` (replace every `[[  ]]`), change "done (v2 run pending)" to done, add the v2 loss curve and the new figures with captions, and add the honest notes from section 1 (overlapping intervals, ±7 points between runs, retries did not help v2, path traversal and secrets remain weak). Rebuild with `npm run build` in `report/` and open the `.docx` to check the tables.
5. **`eval/README.md`:** add the v2 result table under "The runs in this repo" and one line on the naming trap.

**Done when:** no `[[` placeholder is left in `build_report.js`; every number in the report tables can be traced to a file under `eval/results/` or `training/runs/`.

---

### WP6. Documents say the same thing

**Files:** `README.md`, `PLAN.md`, `PROJECT_STORY.md`, `AGENTS.md` (two lines), `extension/README.md`, `docs/DEMO.md` (new).

1. **`README.md` (C1):**
   - Results: replace "Results so far" with the v2 table from section 1, the v1 table as history, and the four honest notes.
   - Quick start: `pip install -e .` (now installs dependencies), `pip install semgrep`, the WP0 model steps, `patchai doctor`, `patchai app`. Remove "until it's trained".
   - Demo: three lines and a link to `docs/DEMO.md`.
   - VS Code: `code --install-extension extension/patchai.vsix`, then **PatchAI: Open Demo Project**.
   - Project map: add `patchai/demo.py`, the `app/` layout, `docs/`.
   - Test count: write the real number from the last `python -m pytest` run, in both places.
2. **`PLAN.md` (C2):** mark v2, the app, the extension and the report as done with their dates; replace "What is left" with what is truly left (rehearsal, backup video, slides); add `demo.py` to the status table.
3. **`PROJECT_STORY.md` (C3):** add a section "Results: v2" after section 8 with the table, the per-type changes and the WP5 findings; rewrite section 12; update the test count.
4. **`AGENTS.md`:** under "How the code fits together" add: "Demos run on a copy made by `patchai/demo.py`; the tracked demo shop is never edited." and "The app's pages live in `app/views/`, one page per file."
5. **`extension/README.md`:** rewrite around installation from the `.vsix`, the first five minutes, the commands and settings tables (fix B9), and troubleshooting.
6. **`docs/DEMO.md` (new):** the pre-demo checklist, the ten-minute script (Appendix E), the fallback plan, and a table of likely viva questions with the file that answers each.
7. **Consistency check.** Search the repo and fix or justify every hit:
   ```
   "79%"  "42%"  "92%"        only where the text clearly says run v1_rescored
   "69 "                      the old test count
   "until it's trained"  "To do"  "pending"  "[["
   "RUN_ON_4060"  "INSTRUCTIONS_4060"
   "Cross-site scripting"     must be followed by "(XSS)" wherever it is a type name
   ```

**Done when:** a reader who opens only the README can install, run the demo and find the v2 numbers, and no document contradicts another.

---

### WP7. Final verification

1. `python -m pytest`; `npm test` in `extension/`.
2. Fresh-clone test: clone the repo into a temp folder, make a venv, `pip install -e .`, `pip install semgrep`, `patchai doctor`, `patchai app`. Everything that does not need a model must work.
3. The app walk-through (Appendix E) with Ollama, then without it.
4. The extension matrix (WP4, section 4.10).
5. `git status` is clean; `demo_projects/` is unchanged; no file over 5 MB is staged.
6. Record the backup demo video.
7. When the owner asks: commit, and tag `v1.0`.

---

## 6. Risks and fallbacks

| Risk | What to do |
| --- | --- |
| The demo laptop has no GPU and a fix takes a minute or more | Warm up the model before the demo; keep-alive is 30 minutes; in the app demo use one attempt-heavy case at most; the replay fallback shows the recorded run in seconds |
| Ollama or the model fails during the viva | App: Replay a recorded fix and Load the recorded comparison. Plus the backup video. |
| The embedding models were never downloaded on the demo laptop (first use needs the internet) | `patchai doctor` once while online; the Overview checklist shows "hash fallback" in red |
| The v2 full logs never arrive | Results, Training and RAG pages still work; Case explorer and replay show their empty state; only run `v1` can be replayed locally |
| A Streamlit or VS Code API named in this plan differs in the installed version | Follow the installed version. The plan fixes behaviour, not API names. |
| WP3 and WP4 are done by different sessions and drift apart | Sections 4.1 and 4.2 and Appendix C are the contract. Do not change them in one place only. |
| Someone "improves" the prompt | Do not. See "Frozen". |

---

## Appendix A. Files this plan creates, moves or deletes

| Action | Path | WP |
| --- | --- | --- |
| create | `patchai/demo.py`, `tests/test_demo.py` | 2 |
| create | `app/ui.py`, `app/charts.py`, `app/views/{overview,fix,compare,results,cases,training,rag,decisions}.py`, `.streamlit/config.toml`, `tests/test_app.py` | 3 |
| create | `extension/src/{server,findings,fix,render}.ts`, `extension/test/render.test.js`, `extension/media/icon.png`, `extension/media/shield.svg`, `extension/media/walkthrough/*.md`, `extension/CHANGELOG.md` | 4 |
| create | `report/fig/*_v2.png`, `docs/DEMO.md` | 5, 6 |
| move | `training/runs/sft/loss.json` → `training/runs/v1/loss.json` | 1 |
| delete | `training/runs/v2/Modelfile`, `INSTRUCTIONS_4060.md` (after merging) | 1 |
| rewrite | `app/review_app.py`, `extension/README.md` | 3, 4 |
| never touch | everything in the "Frozen" table of section 0 | |

## Appendix B. Progress events

`fix_finding(..., on_event=fn)` calls `fn(stage, message)`. These are all the stages (from `patchai/pipeline.py` and `patchai/fixer.py`):

| Stage | When | Step in the five-step strip |
| --- | --- | --- |
| `context` | reading the code around the finding | 2 RAG |
| `retrieve` | searching guides, code and past fixes | 2 RAG |
| `generate` | "Attempt N: asking <model> for a fix" | 3 Our model |
| `guard` | safety guard | 4 Checks |
| `tests` | baseline run and each attempt's test run | 4 Checks |
| `security_test` | the attack test | 4 Checks |
| `rescan` | the re-scan | 4 Checks |
| `retry` | an attempt failed or repeated an earlier one | back to 3 |
| `done` | an attempt passed, or the model answered cannot_fix / false_positive | 5 Human |
| `error` | the pipeline itself failed | the active step turns red |

## Appendix C. Server API after WP2

All endpoints listen on `127.0.0.1` only. Errors are `{"detail": "message"}`.

**`GET /health`**
```json
{"ok": true,
 "models": ["patchai-3b", "qwen2.5-coder:3b"],
 "default_model": "patchai-3b",
 "version": "1.0.0",
 "root": "C:/Users/.../patchAI",
 "ollama": true,
 "fine_tuned": true,
 "semgrep": true,
 "problem": null}
```
`ok`, `models` and `default_model` are unchanged. The endpoint must keep working when Ollama is down (`ollama: false`, `problem` set).

**`POST /scan`** unchanged. Body `{"project_dir": "..."}` → `{"findings": [Finding, ...]}`.

**`POST /fix`** unchanged (blocking; kept for compatibility).

**`POST /fix/start`**. Body: the same as `/fix` (`project_dir`, `finding`, `model`). → `{"job_id": "<32 hex characters>"}`. 400 when `project_dir` is not a folder.

**`GET /fix/status/{job_id}`**
```json
{"done": false,
 "events": [{"stage": "retrieve", "message": "Searching security guides, project code and past fixes"}],
 "result": null,
 "error": null}
```
- `events` always holds every event so far; the client remembers how many it has shown.
- When `done` is true, exactly one of `result` (a full `FixResult`, the same JSON as `/fix`) and `error` (a string) is set. `error` is set in the case where `/fix` would answer 503: the pipeline failed before any attempt.
- 404 for an unknown job id.

**`POST /demo`**. Body `{"reset": false}` → `{"project_dir": "<absolute path of the demo copy>"}`.

**`POST /decision`** unchanged.

## Appendix D. Sketch of the job endpoints

A sketch to keep the two sides compatible. Adapt names to the file's style.

```python
_jobs: dict[str, dict] = {}   # job id -> {"done", "events", "result", "error"}

@app.post("/fix/start")
def fix_start(request: FixRequest) -> dict:
    project = _project(request.project_dir)
    job_id = uuid.uuid4().hex
    job = _jobs[job_id] = {"done": False, "events": [], "result": None, "error": None}
    while len(_jobs) > 20:
        _jobs.pop(next(iter(_jobs)))

    def run() -> None:
        result = fix_finding(project, request.finding, model=request.model or None,
                             on_event=lambda stage, message: job["events"].append({"stage": stage, "message": message}))
        if result.error and not result.attempts:
            job["error"] = result.error
        else:
            _recent_fixes[request.finding.id] = result
            job["result"] = result.model_dump()
        job["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}
```

`fix_finding` never raises, so `run` needs no `try`. Appending to a list and setting dict keys are safe to read from the polling request.

## Appendix E. The ten-minute demo (also the manual test of WP3)

Before: `patchai doctor --warm`, `patchai app`, sidebar shows four green dots, click **Reset demo shop**.

1. **Overview.** The pipeline diagram and the four headline numbers. "A 3B model we trained ourselves reaches 87%, next to 91% for a model twice its size, at a third of the time."
2. **Fix → Scan.** Seven findings, one per type. Select the SQL injection. Show the code, and open "The attack PatchAI will try".
3. **Fix with AI.** Watch the five steps. Then: the before/after code, the five checks, "What the AI read", and the exact prompt.
4. **Approve.** The finding disappears from the next scan. Show the entry on the Decisions page.
5. **Compare.** The hard-coded secret through v1 and v2: v1 fails, v2 fixes it. Open v1's attempts to show the error that was fed back.
6. **Results.** Fix rates with intervals, accuracy against speed, the heat map, then the "Read this honestly" box. Click one failed case and open it in the Case explorer.
7. **Training.** Loss curves, the data before and after, one real CVE fix.
8. **RAG.** Type a query and show the three ranking stages.
9. **VS Code.** Open Demo Project, the underlines, Fix with PatchAI, Accept, Undo.
10. **One limitation**, said out loud: path traversal and secrets are still the weak types, and the benchmark is our own.

Fallback when the model is not available: steps 2 to 5 with **Replay a recorded fix** and **Load the recorded comparison**; steps 6 to 8 need no model at all.
