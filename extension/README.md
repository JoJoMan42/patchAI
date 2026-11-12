# PatchAI – AI Security Fixes (VS Code extension)

PatchAI finds security vulnerabilities in Python code and fixes them with a **fine-tuned model that runs on your own machine**. Every fix is proven before you see it — by your project's tests, by a real attack against the code, and by a re-scan — and nothing changes until you click **Accept**.

The extension does no AI work itself. Scanning, RAG, the model and the checks run in the local PatchAI server (`patchai/server.py`), which the extension starts for you and talks to over `127.0.0.1`.

## Install

You need the PatchAI repository with its Python environment (`pip install -e .` in the repo root), and [Ollama](https://ollama.com) with the models (see the main README).

```
code --install-extension extension/patchai.vsix
```

To rebuild the `.vsix` yourself: `cd extension`, `npm install`, `npm run package`.

## The first five minutes

1. **Open the walkthrough:** *Help → Welcome → Get started with PatchAI*. Every step has a button.
2. **PatchAI: Check Setup** — starts the server if needed, then ticks off the server, Ollama, the fine-tuned model and Semgrep, with a one-line fix for anything missing.
3. **PatchAI: Open Demo Project** — opens a safe copy of a small online shop with seven deliberate vulnerabilities, one of each type. Running it again resets the copy. The tracked demo project is never edited.
4. The new window **scans on its own**. Findings appear as underlines, in the Problems panel, in the **PatchAI side bar** (shield icon), and in the status bar ("PatchAI: 7 issues").
5. **Hover** an underlined line to see what an attacker could do, then click **Fix with PatchAI** (or the CodeLens above the line, or the side bar).
6. The review panel shows the five steps live — **Scanner → RAG → Our model → Checks → Human** — then the result: the verdict, the model's explanation, the diff, every check, every attempt (with what the model was told after a failure), and everything the model read.
7. **Accept** applies the fix and offers **Undo**. **Reject** asks for a reason. **Try another model** runs the same bug through, say, the base model, for comparison.

## Safe by design

- **Proven fixes only:** Accept is enabled only when the final attempt passed every check. A check that could not run is shown as *skipped*, never as passed.
- **Your edits win:** if the file changed after the fix was generated, PatchAI refuses to overwrite it and offers to fix it again.
- **Logged first:** an accepted or rejected fix is recorded in `data/decisions.jsonl` with its reason.
- **Local only:** the server listens on `127.0.0.1`, the model runs in Ollama on your machine, and the panel escapes all model output behind a strict Content-Security-Policy.

## Commands

| Command | What it does |
| --- | --- |
| PatchAI: Scan Workspace for Vulnerabilities | Scan the first workspace folder |
| PatchAI: Fix with AI | Fix the finding at the cursor (also in the right-click menu) |
| PatchAI: Select Model | Choose the model that writes fixes |
| PatchAI: Check Setup | Start the server if needed and check everything a fix needs |
| PatchAI: Open Demo Project | Reset and open the safe copy of the demo shop |
| PatchAI: Start Server / Stop Server | Start the server, or stop the one this window started |
| PatchAI: Show Server Log | The server's output |
| PatchAI: Set PatchAI Folder | Point the extension at the PatchAI repository |

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `patchai.serverUrl` | `http://127.0.0.1:8765` | Where the PatchAI server listens. |
| `patchai.model` | `""` | Model used for fixes. Empty means the server's default (the fine-tuned `patchai-3b` when installed). |
| `patchai.pythonPath` | `""` | Python that runs the server. Empty means the PatchAI folder's `.venv`, else `python`. A relative path is resolved against the PatchAI folder. |
| `patchai.serverDir` | `""` | The PatchAI folder (with `config.yaml`). Empty means: find it from the workspace, its parent folders, or the last folder you chose. |
| `patchai.scanOnSave` | `true` | Scan again after a Python file is saved (quietly: status bar only). |
| `patchai.scanOnOpen` | `true` | Scan when a folder with Python files opens. |
| `patchai.autoStartServer` | `true` | Start the server automatically when it is not running. |

## Troubleshooting

| You see | Do this |
| --- | --- |
| "Could not find the PatchAI folder" | Run **PatchAI: Set PatchAI Folder** and pick the repository root. |
| "The PatchAI server stopped right away … No module named …" | Run `pip install -e .` in the PatchAI folder, or set `patchai.pythonPath` to the right Python. **Show log** has the details. |
| A ⚠ next to the model in the status bar | The fine-tuned model is not installed, so the base model is used. See `training/README.md`. |
| "Ollama is not running" in a fix | Start Ollama (`ollama serve`) and fix again. |
| Path traversal or XSS never found | Install Semgrep: `pip install semgrep`. |
| Accept is greyed out | The fix did not pass every check; the panel says which. Reject it with a reason, or try another model. |

## For developers

| File | Job |
| --- | --- |
| `src/extension.ts` | Activation: create the pieces, register commands |
| `src/api.ts` | Types for the server's JSON and one function per endpoint |
| `src/labels.ts` | Vulnerability and model names (pure, shared) |
| `src/server.ts` | Find the PatchAI folder and Python, start/stop the server, wait for `/health` |
| `src/findings.ts` | Findings store, diagnostics, quick fixes, hovers, CodeLens, side bar, status bar |
| `src/fix.ts` | The fix flow: job + polling, Accept (stale check, Undo), Reject, diff |
| `src/panel.ts` | The webview panel's lifecycle |
| `src/render.ts` | Pure functions that build the panel's HTML (tested in `test/render.test.js`) |

`npm test` compiles and runs the render tests. Press **F5** in the `extension` folder to open a development window.
