# Evaluation

**Question:** does our fine-tuned model fix more vulnerabilities than the normal model?

Every model runs through the **same full pipeline** (RAG, up to 3 attempts, all checks) on the **same test cases**. A case only counts as fixed if the project's tests still pass, the attack in the security test no longer works, and the scanner no longer flags it.

## The benchmark (`eval/cases/`)

```bash
python eval/make_cases.py     # about 15 minutes; rebuilds eval/cases/
```

- **56 generated cases:** 14 code patterns (2 per vulnerability type) × 4 random variants. These patterns are deliberately **different from the training patterns** (class methods, date ranges, `%`-formatting, `make_response`, class attributes, request signatures, ...).
- **7 hand-written cases:** the demo shop's vulnerabilities.
- **Dev set:** 10 cases (variant 0 of 10 patterns) for trying out prompts. Report results on the **test** set only.

Every generated case is **validated** before it is kept: the scanner detects it, its normal tests pass, its security test fails on the vulnerable code, and a known-correct fix passes every check of the real pipeline. So every case is real and solvable.

Each case folder has `case.json` (type, file, split, the reference fix) and `project/` (the code, `tests/`, `security_tests/`).

## Running it

On the GPU laptop, `bash run_4060.sh` runs the whole v2 experiment. By hand:

```bash
# a quick check first
python eval/run_eval.py --split dev --limit 3 --run-name smoke

# the experiment: normal 3B, our v1 and v2 models, normal 7B, on the test split
python eval/run_eval.py --run-name v2 --models qwen2.5-coder:3b patchai-3b-v1 patchai-3b qwen2.5-coder:7b

# tables and charts
python eval/report.py --run v2
```

The run can be stopped and restarted at any time: finished cases are skipped. Expect roughly 10–30 seconds per case per model on the 4060.

## The runs in this repo

| Run | What it is |
| --- | --- |
| `v1` | The first experiment (2026-11-08): normal 3B, patchai-3b v1, normal 7B. **Scored with the old parser**, which counted fixes wrapped in `<vulnerable_code>` tags as syntax errors; that hurt the normal models (the 7B lost 11 cases this way). Kept as the record of what happened. |
| `v1_rescored` | The same recorded answers, re-checked with the fixed parser and checks (`python eval/rescore.py --run v1`, no model needed). **The fair v1 numbers.** |
| `v2` | After the v1 error analysis: improved training data (+ real CVE fixes), retry prompts that show the previous fix and the real error. Made by `run_4060.sh`. |

`eval/rescore.py` replays a run's recorded model answers through today's pipeline. When the first answer passes, the result is exact; when it still fails, the model's next recorded answer (written after the old retry prompt) is replayed as it was.

## Outputs (`eval/results/<run-name>/`)

| File | Contents |
| --- | --- |
| `results.jsonl` | One line per model × case |
| `full/<model>/<case>.json` | Everything: prompt context, every attempt, diffs, check details |
| `summary.csv`, `by_cwe.csv`, `results.md` | Tables for the report |
| `fix_rate.png` | **Headline chart:** fix rate per model with 95% intervals |
| `by_cwe.png` | Fix rate per vulnerability type |
| `quality.png` | Unreadable answers, guard blocks, fake fixes |
| `failures.png` | Why unfixed cases failed |

The Results tab of the review app shows the same numbers.

## What each measure means

| Measure | Meaning |
| --- | --- |
| Fix rate | Share of cases truly fixed (main result), with a 95% Wilson confidence interval |
| First-try fix rate | Fixed on the first attempt, without needing the retry loop |
| Fake fixes | An attempt fooled the scanner, but the attack still worked (caught by the security test) |
| Unreadable answers | Attempts whose output wasn't valid JSON |
| Guard blocks | Attempts blocked by the safety guard (hallucinated imports, dangerous calls, ...) |
| Avg attempts, avg time | Cost per case |

## Honest-reporting checklist

- Report the test split only; say how many cases and how many runs.
- Show the confidence intervals: with about 50 cases, a difference of a few percent is not meaningful.
- Say that generated cases come from templates (a limitation), and show the hand-written shop cases separately if they differ.
- Read about 20 failures in `full/` and describe the common causes.
