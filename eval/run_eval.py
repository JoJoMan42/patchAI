"""Runs every test case through the full PatchAI pipeline with each model, and saves the results.

  python eval/run_eval.py                                     # models from config.yaml (models.compare)
  python eval/run_eval.py --models qwen2.5-coder:3b patchai-3b --run-name v2
  python eval/run_eval.py --split dev --limit 3               # quick check on the dev set
  python eval/run_eval.py --no-rag --run-name no_rag          # optional: the same run without RAG

Results go to eval/results/<run-name>/:
  results.jsonl      one line per (model, case): verdict, attempts, time, fake fix, ...
  full/<model>/      the complete FixResult of every case (diffs, checks, retrieved context)
  manifest.json      models, settings, date and commit, so the run can be reproduced
Interrupted? Run the same command again: finished (model, case) pairs are skipped.
Then make the charts:  python eval/report.py --run <run-name>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from patchai import llm, metrics  # noqa: E402
from patchai.config import get_config  # noqa: E402
from patchai.pipeline import fix_finding  # noqa: E402
from patchai.prompts import PROMPT_VERSION  # noqa: E402
from patchai.scan import scan  # noqa: E402

CASES = ROOT / "eval" / "cases" / "manifest.json"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", nargs="+", default=None, help="Ollama model names (default: models.compare in config.yaml)")
    p.add_argument("--split", choices=["test", "dev", "all"], default="test")
    p.add_argument("--run-name", default=datetime.now().strftime("%Y%m%d_%H%M"))
    p.add_argument("--limit", type=int, default=0, help="only the first N cases (for a quick try)")
    p.add_argument("--attempts", type=int, default=get_config()["repair"]["max_attempts"])
    p.add_argument("--no-rag", action="store_true", help="give the model no retrieved context")
    args = p.parse_args()

    if not CASES.exists():
        sys.exit("No benchmark yet. Run: python eval/make_cases.py")
    cases = [c for c in json.loads(CASES.read_text(encoding="utf-8")) if args.split == "all" or c["split"] == args.split]
    if args.limit:
        cases = cases[: args.limit]
    models = args.models or get_config()["models"]["compare"]
    installed = llm.list_models()
    missing = [m for m in models if m not in installed]
    if missing:
        sys.exit(f"Not installed in Ollama: {missing}. Installed: {installed}")

    out = ROOT / "eval" / "results" / args.run_name
    out.mkdir(parents=True, exist_ok=True)
    results_file = out / "results.jsonl"
    done = set()
    if results_file.exists():
        for line in results_file.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            done.add((row["model"], row["case_id"]))
    write_manifest(out, args, models, cases)

    label = (lambda m: f"{m} [no RAG]") if args.no_rag else (lambda m: m)
    total, finished, started = len(cases) * len(models), len(done), time.time()
    print(f"{len(cases)} cases × {len(models)} models = {total} runs ({finished} already done)")

    for case in cases:  # cases outside, models inside: a partial run stays balanced across models
        if all((label(m), case["id"]) in done for m in models):
            continue
        project = ROOT / case["project"]
        targets = [f for f in scan(project) if f.file_path == case["file"] and f.cwe == case["cwe"]]
        if not targets:
            print(f"  ! {case['id']}: the scanner no longer finds the vulnerability, skipped")
            continue
        for model in models:
            if (label(model), case["id"]) in done:
                continue
            result = fix_finding(project, targets[0], model=model, max_attempts=args.attempts, use_rag=not args.no_rag)
            result.model = label(model)
            record = metrics.to_record(result, case["id"])
            record.update(split=case["split"], family=case["family"], source=case["source"])
            with open(results_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            full = out / "full" / safe_name(label(model))
            full.mkdir(parents=True, exist_ok=True)
            (full / f"{case['id']}.json").write_text(result.model_dump_json(indent=1), encoding="utf-8")

            finished += 1
            per_run = (time.time() - started) / max(1, finished - len(done))
            print(f"  [{finished}/{total}] {label(model):28} {case['id']:38} {result.verdict:14} "
                  f"{result.seconds:5.0f}s  (~{per_run * (total - finished) / 60:.0f} min left)")

    print(f"Done. Next: python eval/report.py --run {args.run_name}")


def write_manifest(out: Path, args, models: list[str], cases: list[dict]) -> None:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except OSError:
        commit = ""
    previous = out / "manifest.json"
    if previous.exists():  # models added to the run later (e.g. the DPO model) keep the earlier ones listed
        earlier = json.loads(previous.read_text(encoding="utf-8")).get("models", [])
        models = earlier + [m for m in models if m not in earlier]
    manifest = {
        "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "models": models, "split": args.split, "cases": len(cases), "max_attempts": args.attempts,
        "rag": not args.no_rag, "prompt_version": PROMPT_VERSION, "git_commit": commit or None,
        "config": get_config(),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def safe_name(model: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in model)


if __name__ == "__main__":
    main()
