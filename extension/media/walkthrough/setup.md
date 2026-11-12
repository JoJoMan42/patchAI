# Check the setup

**PatchAI: Check Setup** starts the local PatchAI server if it is not running, then checks everything a fix needs:

- **The server** — found and started automatically; its output is in the "PatchAI Server" output channel.
- **Ollama** — runs the model locally. Install it from [ollama.com](https://ollama.com) and keep `ollama serve` running.
- **The fine-tuned model** (`patchai-3b`) — our own model. Without it, PatchAI falls back to the base model and says so in the status bar.
- **Semgrep** — the second scanner. Without it, path traversal and XSS are not detected.

Everything runs on your machine. No code leaves it.
