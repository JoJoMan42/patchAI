# Training our model (patchai-3b)

We fine-tune **Qwen2.5-Coder-3B-Instruct** to do one job well: rewrite a vulnerable function into a small, correct, secure fix, in our exact JSON format.

```
real_data.py (CVEfixes) ─┐
synth.py ────────────────┴─▶ make_dataset.py ─▶ train.py (SFT) ─▶ export.py ─▶ Ollama: patchai-3b
                                                     │
                                                     └─▶ dpo.py collect ─▶ dpo.py train ─▶ export.py ─▶ patchai-3b-dpo   (bonus)
```

| File | What it does | Where it runs |
| --- | --- | --- |
| `synth.py` | Generates pairs of vulnerable code and its correct fix (25 code patterns × random names and styles, plus false alarms), balanced over the 7 types | any laptop |
| `real_data.py` | Turns **real CVE fixes** from the CVEfixes dataset into examples: rebuilds the vulnerable file, keeps only fixes our scanners confirm | any laptop (already done: `data/real_fixes/`) |
| `make_dataset.py` | Scans every example with the real scanners, builds the real prompt (with RAG), adds realistic retry examples, writes `data/training/train.jsonl` + `val.jsonl` | any laptop |
| `train.py` | QLoRA supervised fine-tuning | GPU laptop |
| `export.py` | Converts the trained model and registers it in Ollama | GPU laptop (or demo laptop with a .gguf) |
| `dpo.py` | Bonus: the model writes fixes, our checks mark the bad ones, the model learns to avoid them | GPU laptop |

## On the RTX 4060 laptop: one command

```bash
cd ~/patchAI && git pull
source .venv/bin/activate
bash run_4060.sh            # everything: checks, dataset, training, export, evaluation, report (~4-5 h)
bash run_4060.sh --dpo      # the same plus the DPO bonus (~3-4 h more)
```

The script skips finished steps, so it can be stopped and re-run. It keeps the first model as `patchai-3b-v1` so the evaluation can compare v1 and v2. See [RUN_ON_4060.md](../RUN_ON_4060.md).

First-time setup of the laptop (only once): WSL2 + Ubuntu, then

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt -r requirements-train.txt
pip install -e .
```

The individual steps, if you want to run them by hand:

```bash
python training/make_dataset.py --n 2500                        # 20-40 min
python training/train.py --run-name v2                          # ~2 h  (out of memory? add --batch-size 1 --grad-accum 16)
python training/export.py --run training/runs/v2 --name patchai-3b   # (fails? add --merged)
```

### Moving the model to the demo laptop

Copy the `.gguf` file from `training/runs/v2/` (it may be in a `gguf/` or `gguf_gguf/` subfolder) to the demo laptop, then:

```bash
python training/export.py --gguf path/to/model.Q4_K_M.gguf --name patchai-3b
```

## v1 → v2: what we changed after the first model's error analysis

v1 (trained 2026-11-08) reached 79% on the benchmark, but reading its failures showed four fixable problems:

| Problem seen in v1 | Cause | v2 change |
| --- | --- | --- |
| 0% on hard-coded secrets | 2/3 of training fixes used `os.environ["X"]`, which crashes on import when the variable isn't set | Secrets always use `os.environ.get("X", "")`; new credential-check pattern |
| 0/4 on key derivation | Training only had password hashing (random salt, hex string); the model copied that into key derivation | New key-stretching pattern: PBKDF2, deterministic, still returns bytes; checksums keep their return type |
| Retries repeated the same wrong fix | The retry prompt had a vague error (`<test run error>`) and didn't show the previous fix | Retry prompt shows the previous fix + the real error (`KeyError: 'X'`); training has realistic retry examples |
| 25% of the data was one false-alarm pattern, only 88 command-injection examples | Generator bug: an exhausted type let false alarms fill the gap | Fixed quotas per type, exactly 8% false alarms, more command/deserialization variety |
| Synthetic data only | | Real CVE fixes from CVEfixes added |

The prompt changed (retries), so `PROMPT_VERSION` is now `v2`. First attempts are unchanged, so the v1 model still works with it.

## Real-world data (CVEfixes)

`real_data.py` reads the [CVEfixes](https://github.com/secureIT-project/CVEfixes) dataset (Bhandari et al., PROMISE 2021; Hugging Face copy `hitoshura25/cvefixes`, Apache-2.0): real CVEs linked to the commits that fixed them. For every Python fix of our 7 types it:

1. downloads the fixed file from GitHub at the fixing commit and **undoes the diff** to get the vulnerable file
2. runs **our scanners**; keeps a finding only if it is inside a function the commit changed **and** the fixed version is no longer flagged
3. keeps only fixes our pipeline could accept (same signature, ≤ 30 changed lines, no new third-party imports, no new helpers)

Real fixes are messy, so most are filtered out (the counts are in `data/real_fixes/cvefixes_info.json`). Each kept example appears twice in training. The output is committed, so the GPU laptop doesn't need to download anything.

## Bonus: DPO (learning from its own mistakes)

```bash
python training/dpo.py collect --n 400     # 2–3 hours: 4 fixes per case, each one checked
python training/dpo.py train               # about 1 hour (starts from training/runs/v2)
python training/export.py --run training/runs/dpo --name patchai-3b-dpo
```

`collect` uses **new** training cases (a different random seed, never test cases). Every fix the model gets wrong (broken JSON, blocked by the safety guard, or still flagged by the scanner) becomes a "rejected" answer, paired with the correct fix as "chosen". DPO then teaches the model to prefer the chosen answers over its own typical mistakes.

## What to put in the report

- `data/training/dataset_info.json`: dataset size, synthetic vs real-world, examples per type and pattern, retry kinds, false alarms
- `data/real_fixes/cvefixes_info.json`: how many real fixes were kept and why the others were filtered out
- `training/runs/v1/` and `training/runs/v2/`: loss curves (`loss.png`) and every setting + dataset hashes (`manifest.json`)
- `data/training/dpo_info.json`: how often the model's own fixes passed or failed each check

## Keeping the evaluation fair

- The training code patterns (`synth.py`) and the evaluation code patterns (`eval/make_cases.py`) are **different code shapes**. v2 added two patterns after looking at v1's failures (credential checks, key stretching); they teach the same *concepts* as two benchmark patterns but are written differently. Say this in the report.
- The demo shop is never used for training. CVEfixes code comes from real open-source projects, not from the benchmark.
- DPO never sees test cases.
- The past fixes in `data/fix_examples/` are only used by RAG, never as training answers.

## Settings and why

| Setting | Value | Why |
| --- | --- | --- |
| Method | QLoRA (4-bit base + LoRA rank 16) | Fits a 3B model in 8 GB of VRAM |
| Max length | 4096 tokens | Our prompts are about 2,000 tokens including RAG context |
| Epochs | 2 | Enough for format and patterns; more risks memorising templates |
| Learning rate | 2e-4 (SFT), 5e-6 (DPO) | Standard values for LoRA fine-tuning and DPO |
| Loss | Answer tokens only | The model learns to write fixes, not to repeat prompts |
| Retry examples | 20% | Teaches the model to use the error and its previous fix |
