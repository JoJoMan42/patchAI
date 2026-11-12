# PatchAI v2: running training on the RTX 4060 laptop

v2 was trained with this procedure on 2026-11-09. Keep it for re-runs.

Everything runs in **WSL Ubuntu** on the 4060 laptop. Keep the laptop **plugged in** and set Windows sleep to **Never**: it takes about 4-5 hours. You can use the laptop for light things meanwhile, but nothing that needs the GPU (no games).

## The easy way: one double-click

1. **Put `run_4060.bat` on the Windows Desktop** (it is in the repo root; copy it from `\\wsl$\Ubuntu\home\<your-user>\patchAI\run_4060.bat`).
2. **Double-click it.** It pulls the latest code, starts Ollama if needed, and runs `run_4060.sh` inside WSL. Don't close the black window.
3. Wait for **DONE**, then do "When it's done" below.

**Optional bonus** (about 3-4 hours more, e.g. overnight): open a Command Prompt where the file is and run `run_4060.bat --dpo`.

## The manual way (the same thing, by hand)

Terminal 1 (leave it open):

```bash
ollama serve
```

If it says the address is already in use, Ollama is already running. That's fine.

Terminal 2:

```bash
cd ~/patchAI
git pull
source .venv/bin/activate
bash run_4060.sh
```

## What the script does

| Step | What | Time |
| --- | --- | --- |
| 1 | Checks the GPU, PyTorch, Ollama, models | 1 min |
| 2 | Runs PatchAI's tests | 3 min |
| 3 | Keeps the old model as `patchai-3b-v1` (`ollama cp`) | seconds |
| 4 | Builds the v2 training data (synthetic + real CVE fixes) | 20-40 min |
| 5 | Trains the v2 model (QLoRA) | ~2 h |
| 6 | Loads it into Ollama as `patchai-3b` and tries it once | 15 min |
| 7 | The experiment: 4 models × 53 test cases | 1-2 h |
| 8 | Packs up the results (`logs/v2_full_eval_logs.zip`) | 1 min |

**If it stops** (error, laptop restarted, closed the window): run it again. Finished steps are skipped and the evaluation continues where it stopped. Every run is logged to `~/patchAI/logs/run_<date>.log`.

**If it says STOPPED:** don't try to fix the project's code. Send the log file it names (in `~/patchAI/logs/`) to the team, or use the troubleshooting prompt below.

## When it's done

In the WSL Ubuntu terminal:

```bash
cd ~/patchAI
git add eval/results/v2 training/runs/v2/loss.png training/runs/v2/manifest.json data/training/dataset_info.json
git commit -m "v2 training and evaluation results"
git push
```

Then open a pull request on GitHub from your fork to `JoJoMan42/patchAI`.

Upload these to Google Drive and share them with the team:
- `~/patchAI/logs/v2_full_eval_logs.zip`: every attempt of every test case
- the `.gguf` file the window printed at the end (inside `~/patchAI/training/runs/v2/`, about 1.9 GB): the trained model, for the demo laptop

---

## If anything goes wrong: paste this into an AI chat

Copy everything in the box, then paste your error underneath it.

```text
I'm running a university project called PatchAI on my Windows laptop (RTX 4060, 8 GB VRAM) using WSL2 Ubuntu.
The project is in ~/patchAI inside WSL, with a Python virtual environment in ~/patchAI/.venv.
It fine-tunes Qwen2.5-Coder-3B with QLoRA (Unsloth, TRL, PEFT, PyTorch CUDA), exports it to GGUF,
loads it into Ollama (running inside WSL on localhost:11434), and then runs an evaluation.

I start everything by double-clicking run_4060.bat on Windows. It runs, inside WSL:
  cd ~/patchAI
  git pull --no-edit https://github.com/JoJoMan42/patchAI.git main
  (starts `ollama serve` if it isn't running)
  source .venv/bin/activate
  bash run_4060.sh

run_4060.sh does these steps in order and skips steps that are already done:
  1/8 checks: nvidia-smi, torch.cuda.is_available(), imports unsloth/trl/peft, Ollama is running,
      pulls qwen2.5-coder:3b and qwen2.5-coder:7b if missing, pip install -e .
  2/8 python -m pytest -q   (PatchAI's own tests)
  3/8 ollama cp patchai-3b patchai-3b-v1   (keeps the old model)
  4/8 python training/make_dataset.py --n 2500
  5/8 python training/train.py --run-name v2   (retries with --batch-size 1 --grad-accum 16 if it fails)
  6/8 python training/export.py --run training/runs/v2 --name patchai-3b   (falls back to --merged)
      then a quick test: python eval/run_eval.py --split dev --limit 2 --run-name smoke_v2 --models patchai-3b
  7/8 python eval/run_eval.py --run-name v2 --models <the models>, then python eval/report.py --run v2
  8/8 zips the logs
The script is safe to re-run: finished steps are skipped and the evaluation resumes.
Every run is logged to ~/patchAI/logs/run_<date>.log.

Rules for helping me:
- Do NOT tell me to change the project's Python code. If a code change seems needed, tell me to send the log to my team instead.
- Prefer fixes to my environment (installing a package, starting Ollama, freeing GPU memory, git problems).
- Give me exact commands to paste into the WSL Ubuntu terminal, one step at a time, and tell me what output to expect.
- After the fix, the way to continue is to double-click run_4060.bat again (or run: cd ~/patchAI && source .venv/bin/activate && bash run_4060.sh).
- If git pull fails because of local changes, help me keep my changes safe (git stash) rather than deleting anything.

Here is the error (the last lines of the window or the log file):
```

### Common problems (quick answers)

| Message | What to do |
| --- | --- |
| `~/patchAI not found in WSL` | The project is in a different folder. Tell the team where it is. |
| `git pull` says *local changes would be overwritten* | In WSL: `cd ~/patchAI && git stash`, then double-click the .bat again |
| `Ollama is not running` | In WSL: `ollama serve` in a separate terminal, leave it open, run the .bat again |
| `PyTorch cannot use the GPU` | In WSL: `cd ~/patchAI && source .venv/bin/activate && pip install torch --index-url https://download.pytorch.org/whl/cu124` |
| `CUDA out of memory` twice | Close everything else that uses the GPU, restart the laptop, run the .bat again |
| The laptop went to sleep / restarted | Just double-click the .bat again; it continues |
