"""Re-checks a finished evaluation run with the CURRENT checks, using the answers the models
already gave (saved in eval/results/<run>/full/). No model or GPU needed.

Why: v1 was scored with a parser that didn't strip the <vulnerable_code> tags some models
copy from the prompt, so correct fixes were counted as syntax errors. Re-scoring replays each
model's recorded answers through today's pipeline (parser, guard, tests, attack test, re-scan).

  python eval/rescore.py --run v1        # writes eval/results/v1_rescored/

Honest caveat: a recorded retry answer was written after the OLD retry prompt. When the first
answer now passes, nothing else is used, so the result is exact; when it still fails, the
model's next recorded answer is replayed as it was.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from patchai import llm, metrics  # noqa: E402
from patchai.models import FixResult  # noqa: E402
from patchai.pipeline import fix_finding  # noqa: E402
from patchai.scan import scan  # noqa: E402

RESULTS = ROOT / "eval" / "results"
CASES = ROOT / "eval" / "cases" / "manifest.json"


def replay(answers: list[str]):
    """A stand-in model that gives the recorded answers in order (repeating the last one)."""
    calls = []

    def chat(messages, model):
        calls.append(1)
        text = answers[min(len(calls), len(answers)) - 1] if answers else ""
        return llm.LLMReply(text=text, model=model, tokens_in=0, tokens_out=0, seconds=0.0)

    return chat


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", required=True, help="the run to re-score, e.g. v1")
    args = p.parse_args()

    source = RESULTS / args.run
    out = RESULTS / f"{args.run}_rescored"
    out.mkdir(parents=True, exist_ok=True)
    cases = {c["id"]: c for c in json.loads(CASES.read_text(encoding="utf-8"))}
    old = [json.loads(line) for line in (source / "results.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    targets_cache: dict[str, object] = {}
    rows, changed = [], 0

    for i, record in enumerate(old):
        folder = record["model"].replace(":", "_")
        full = source / "full" / folder / f"{record['case_id']}.json"
        if not full.exists():
            sys.exit(f"Missing {full}. Copy the run's full/ folder (from the GPU laptop) into {source}.")
        saved = FixResult.model_validate_json(full.read_text(encoding="utf-8"))
        case = cases[record["case_id"]]
        project = ROOT / case["project"]
        if case["id"] not in targets_cache:
            targets_cache[case["id"]] = [f for f in scan(project) if f.file_path == case["file"] and f.cwe == case["cwe"]][0]
        answers = [a.raw_output for a in saved.attempts]
        result = fix_finding(project, targets_cache[case["id"]], model=record["model"],
                             max_attempts=len(answers) or 1, chat_fn=replay(answers))
        result.seconds = saved.seconds  # keep the real timing from the original run
        new = metrics.to_record(result, case["id"])
        new.update(split=record["split"], family=record["family"], source=record["source"],
                   tokens_in=record["tokens_in"], tokens_out=record["tokens_out"])
        rows.append(new)
        if new["verdict"] != record["verdict"]:
            changed += 1
            print(f"  {record['model']:20} {case['id']:38} {record['verdict']} -> {new['verdict']}")
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(old)} re-scored")

    with open(out / "results.jsonl", "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    manifest["rescored_from"] = args.run
    manifest["note"] = "Recorded model answers re-checked with the current parser and checks (eval/rescore.py)."
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"{changed} of {len(rows)} verdicts changed. Next: python eval/report.py --run {out.name}")


if __name__ == "__main__":
    main()
