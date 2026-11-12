# Changelog

## 1.0.0 — 2026-11-10

First complete release, built around the v2 fine-tuned model.

- The extension starts the PatchAI server itself (child process + output channel) and finds the PatchAI folder from the workspace, its parents, or a remembered choice — a `.vsix` install works outside the repository.
- New PatchAI side bar with the findings grouped by file, hovers, and a CodeLens above every finding.
- Fixes run as server jobs with live five-step progress; fixes longer than five minutes no longer time out.
- Accept is safe: the decision is logged, files changed after the fix was generated are never overwritten, and there is a one-click Undo.
- Skipped checks are shown as skipped, not as passed.
- New commands: Check Setup, Open Demo Project, Stop Server, Show Server Log, Set PatchAI Folder.
- A four-step walkthrough on the Welcome page.
- Scan on save is quiet (status bar only) and on by default; scans also run when a Python folder opens.

## 0.1.0 — 2026-11-05

First version: scan, blocking fix, review panel, accept/reject.
