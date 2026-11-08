# PatchAI v2: steps on the RTX 4060 laptop

Everything runs in the **WSL Ubuntu terminal**. Keep the laptop **plugged in** and set Windows sleep to **Never**: it takes about 4-5 hours.

## 1. Start Ollama (leave this terminal open)

```bash
ollama serve
```

If it says the address is already in use, Ollama is already running. That's fine.

## 2. In a second terminal: update and run

```bash
cd ~/patchAI
git pull
source .venv/bin/activate
bash run_4060.sh
```

That's it. The script does everything in order and prints what it's doing:

| Step | What | Time |
| --- | --- | --- |
| 1 | Checks the GPU, PyTorch, Ollama, models | 1 min |
| 2 | Runs PatchAI's tests | 3 min |
| 3 | Keeps the old model as `patchai-3b-v1` | seconds |
| 4 | Builds the v2 training data (synthetic + real CVE fixes) | 20-40 min |
| 5 | Trains the v2 model | ~2 h |
| 6 | Loads it into Ollama as `patchai-3b` and tries it once | 15 min |
| 7 | The experiment: 4 models × 53 test cases | 1-2 h |
| 8 | Packs up the results | 1 min |

**If it stops** (error, laptop restarted, closed the window): run `bash run_4060.sh` again. Finished steps are skipped and the evaluation continues where it stopped.

**If it says STOPPED:** don't try to fix it. Send the log file it names (in `logs/`) to the team.

**Optional bonus** (another 3-4 hours, e.g. overnight): `bash run_4060.sh --dpo`

## 3. When it says DONE

Run the three `git` commands it prints (add, commit, push), and upload the two files it lists to Google Drive:
- `logs/v2_full_eval_logs.zip`: every attempt of every test case
- the `.gguf` file: the trained v2 model, for the demo laptop
