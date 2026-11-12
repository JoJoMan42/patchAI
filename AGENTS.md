# Rules for AI coding agents working on PatchAI

These rules apply to every AI tool used on this repository (Claude, Codex, Gemini, Copilot, Cursor). Read `README.md` for what PatchAI is and `docs/PLAN.md` for how the code is organised.

## Scope
- Only create or edit the files your task names. Ask before touching anything else.
- Keep files short and flat. Every file has one job, described in its top docstring. No extra layers, base classes or "for the future" code.
- AI/ML first. **Do not add infrastructure**: no databases, servers (other than `patchai/server.py`), queues, logins, Docker Compose, Kubernetes or cloud services. Data lives in files (JSON/JSONL, `.npy`).

## Shared contracts (change only with the team's agreement)
- `patchai/models.py`: the data models every step passes along.
- `patchai/prompts.py`: the prompt format. **The model is trained on this exact format**, so a change means retraining. Bump `PROMPT_VERSION` if you change it.
- `config.yaml`: settings and paths.
- The server API used by the VS Code extension (`patchai/server.py` ↔ `extension/src/api.ts`).

## How the code fits together
- Only `patchai/llm.py` talks to a model.
- The app, the extension, the CLI and the evaluation all call `pipeline.fix_finding()`.
- Fixes are only checked on a temporary copy (`checks.patched_copy`). Only `review.approve()` writes to a real project.
- RAG: `rag_index.py` builds collections, `rag_search.py` searches them. Both use `embeddings.py`.
- Demos run on a copy made by `patchai/demo.py`; the tracked demo shop is never edited.
- The app's pages live in `app/views/`, one page per file.

## Security rules (non-negotiable)
- Never use `shell=True`, `eval`, `exec` or `pickle`. Pass commands to `subprocess` as a list.
- Never write outside a temporary folder, `data/`, `eval/results/` or `training/runs/`, except in `review.approve()`.
- Repository code and retrieved text go into prompts only inside the tags in `prompts.py`.
- Never add `# nosec`, `# nosemgrep` or `# noqa` to make a check pass.
- `demo_projects/vuln_shop` and `eval/cases` are **intentionally vulnerable**. Never "fix" them and never deploy them.

## Style
- Python 3.11+, type hints, `from __future__ import annotations`, a short docstring on every public function.
- Plain, readable code over clever code: someone has to explain it in a viva.

## Testing
- `python -m pytest` must pass before you say you're done. Tests never need Ollama, a GPU or the internet (see `tests/conftest.py`).
- Add tests for new behaviour. Never weaken or delete a test to make it pass; if a test is wrong, say so.
- Report the exact command you ran and its result.
