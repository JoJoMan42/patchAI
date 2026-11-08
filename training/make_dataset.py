"""Builds the fine-tuning dataset (data/training/train.jsonl and val.jsonl).

Two sources:
  - synthetic pairs from training/synth.py (about 2,500, balanced over the 7 vulnerability types)
  - real-world fixes from CVEfixes (data/real_fixes/cvefixes.jsonl, made by training/real_data.py)

For every pair:
  1. write the vulnerable file and run the real scanners on it   -> a real Finding
  2. extract the code region with patchai.context                 -> the same CodeContext as in real use
  3. retrieve guides and past fixes with patchai.rag_search       -> the same RAG context as in real use
  4. build the prompt with patchai.prompts.build_prompt           -> exactly the prompt the model will see
  5. the answer is the correct fix as FixProposal JSON
Examples the scanners don't detect are dropped, so every example matches a real finding.

About 20% of examples are "retries": the prompt shows a wrong previous fix and the exact error
our checks report for it (e.g. "KeyError: 'API_TOKEN'"), and the answer is the correct fix.
This teaches the model to actually use the feedback instead of repeating itself.

Run:  python training/make_dataset.py --n 2500
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import textwrap
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "training"))

from patchai.config import get_config  # noqa: E402
from patchai.context import get_context  # noqa: E402
from patchai.models import CodeContext, Finding, FixProposal, RetrievedChunk, cwe_name  # noqa: E402
from patchai.prompts import PROMPT_VERSION, answer_json, build_prompt  # noqa: E402
from patchai.rag_index import knowledge_collections  # noqa: E402
from patchai.rag_search import search  # noqa: E402
from patchai.scan import scan  # noqa: E402
from synth import Pair, generate  # noqa: E402

OUT_DIR = ROOT / "data" / "training"
REAL_FIXES = ROOT / "data" / "real_fixes" / "cvefixes.jsonl"

NOSEC_ERROR = ("The safety guard rejected the fix: The fix adds a comment that silences the scanner "
               "(e.g. `# nosec`). Fix the code instead.")
FORMAT_ERROR = ("Your answer could not be read. The answer is not valid FixProposal JSON: 1 validation error "
                "for FixProposal. Answer with JSON only.")
UNCHANGED_ERROR = ("[security_test] The vulnerability can still be exploited (test_attack_is_blocked). "
                   "1 failed, 1 passed in 0.06s. Error: AssertionError: the attack still works "
                   "[rescan] The scanner still reports {cwe} here: {message}")
UNCHANGED_ERROR_NO_TESTS = "[rescan] The scanner still reports {cwe} here: {message}"


@dataclass
class Prepared:
    """A pair turned into a real finding, its context, the prompt and the correct answer."""

    pair: Pair
    folder: Path  # the folder holding this example's file
    finding: Finding
    context: CodeContext
    messages: list[dict]  # system + user prompt
    answer: FixProposal
    retry: str = ""  # which kind of wrong previous fix the prompt shows ("" = first attempt)


def load_real_pairs(path: Path = REAL_FIXES) -> list[Pair]:
    """Real-world vulnerability fixes prepared by training/real_data.py."""
    if not path.exists():
        return []
    pairs = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        row = json.loads(line)
        pairs.append(Pair(
            id=f"cvefixes-{i:04d}", cwe=row["cwe"], family="cvefixes", header="",
            vulnerable=row["vulnerable"], fixed=row["fixed"], fix_imports=row.get("imports_to_add", []),
            explanation=row["explanation"], source_text=row["file_text"], source=f"cvefixes:{row['cve_id']}",
            lines=(row["start_line"], row["end_line"]),
        ))
    return pairs


def write_cases(pairs: list[Pair], root: Path) -> None:
    """Each pair becomes its own tiny project: root/<id>/module.py"""
    for pair in pairs:
        folder = root / pair.id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "module.py").write_bytes(pair.module().replace("\r\n", "\n").encode("utf-8"))


def retry_for(pair: Pair, finding: Finding, r: random.Random) -> tuple[str, str, str]:
    """A realistic failed previous attempt for this pair: (kind, error message, previous fix)."""
    fill = lambda text: text.replace("{cwe}", finding.cwe).replace("{message}", finding.message)  # noqa: E731
    roll = r.random()
    if pair.mistakes and roll < 0.6:  # the typical mistake for this pattern, e.g. os.environ["X"]
        code, error = r.choice(pair.mistakes)
        return "typical_mistake", fill(error), code
    if roll < 0.75:
        flagged = (finding.code or "").splitlines()[0].strip() if finding.code else ""
        lines = pair.vulnerable.splitlines()
        for i, line in enumerate(lines):
            if flagged and line.strip() == flagged:
                lines[i] = line + "  # nosec"
                return "nosec", NOSEC_ERROR, "\n".join(lines)
    if roll < 0.9:
        error = UNCHANGED_ERROR if pair.source == "synthetic" else UNCHANGED_ERROR_NO_TESTS
        return "unchanged", fill(error), pair.vulnerable
    return "format", FORMAT_ERROR, ""


def prepare(pairs: list[Pair], root: Path, seed: int, rerank: bool = True,
            retry_share: float = 0.2) -> tuple[list[Prepared], Counter]:
    """Scan every case once, then build each example's prompt exactly like the real pipeline."""
    r = random.Random(seed)
    knowledge = knowledge_collections()
    top_k = get_config()["rag"]["top_k"]
    stats: Counter = Counter()
    print(f"Scanning {len(pairs)} files (this takes a few minutes)...")
    by_case: dict[str, list[Finding]] = {}
    for f in scan(root):
        by_case.setdefault(f.file_path.split("/")[0], []).append(f)

    prepared = []
    for i, pair in enumerate(pairs):
        found = by_case.get(pair.id, [])
        matching = [f for f in found if f.cwe == pair.cwe] or (found if pair.status != "fixed" else [])
        if pair.lines:  # real files can have several findings: take the one inside the fixed function
            matching = [f for f in matching if pair.lines[0] <= f.start_line <= pair.lines[1]]
        if not matching:
            stats[f"dropped_not_detected:{pair.family}"] += 1
            continue
        folder = root / pair.id
        finding = matching[0].model_copy(update={"file_path": "module.py"})
        context = get_context(folder, finding)
        if textwrap.dedent(context.source.replace("\r\n", "\n")).strip() != pair.vulnerable.strip():
            stats[f"dropped_region_mismatch:{pair.family}"] += 1
            continue

        retrieved = retrieve_knowledge(knowledge, finding, context, top_k, rerank)
        if pair.helper and r.random() < 0.8:
            retrieved.insert(top_k["guide"], RetrievedChunk(source="code", title="module.py::helper",
                                                            text=pair.helper, file_path="module.py", score=1.0))
        kind, error, previous = "", None, None
        if pair.status == "fixed" and r.random() < retry_share:
            kind, error, previous = retry_for(pair, finding, r)
        answer = FixProposal(
            status=pair.status,
            fixed_code=pair.fixed if pair.status == "fixed" else "",
            imports_to_add=pair.fix_imports,
            explanation=pair.explanation,
            confidence=round(r.uniform(0.8, 0.95) if pair.status == "fixed" else r.uniform(0.6, 0.85), 2),
        )
        messages = build_prompt(finding, context, retrieved, error, previous or None)
        prepared.append(Prepared(pair, folder, finding, context, messages, answer, kind))
        stats[f"kept:{pair.cwe}"] += 1
        if (i + 1) % 250 == 0:
            print(f"  {i + 1}/{len(pairs)} prepared")
    return prepared, stats


def build(n: int, seed: int, val_share: float = 0.1, rerank: bool = True, real: bool = True,
          real_repeat: int = 2) -> dict:
    """Generate, prepare and save the SFT dataset."""
    synthetic = generate(n, seed=seed)
    real_pairs = load_real_pairs() if real else []
    pairs = synthetic + real_pairs
    with tempfile.TemporaryDirectory() as tmp:
        write_cases(pairs, Path(tmp))
        prepared, stats = prepare(pairs, Path(tmp), seed, rerank)

    examples = [{
        "id": p.pair.id, "cwe": p.pair.cwe, "family": p.pair.family, "status": p.pair.status,
        "source": p.pair.source.split(":")[0], "retry": p.retry,
        "messages": p.messages + [{"role": "assistant", "content": answer_json(p.answer)}],
    } for p in prepared]
    random.Random(seed).shuffle(examples)
    n_val = max(1, int(len(examples) * val_share))
    val, train = examples[:n_val], examples[n_val:]
    # Real-world examples are few, so each one appears `real_repeat` times in training (never in val twice).
    train += [e for e in train if e["source"] == "cvefixes" for _ in range(real_repeat - 1)]
    random.Random(seed + 1).shuffle(train)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(OUT_DIR / "val.jsonl", val)
    write_jsonl(OUT_DIR / "train.jsonl", train)
    chars = sorted(sum(len(m["content"]) for m in ex["messages"]) for ex in examples)
    info = {
        "generated": len(pairs), "kept": len(examples), "train": len(train), "val": len(val),
        "seed": seed, "prompt_version": PROMPT_VERSION, "approx_tokens_median": chars[len(chars) // 2] // 3 if chars else 0,
        "approx_tokens_max": chars[-1] // 3 if chars else 0,
        "by_source": dict(Counter(e["source"] for e in examples)),
        "real_world_cves": sorted({p.pair.source.split(":", 1)[1] for p in prepared if p.pair.source != "synthetic"}),
        "real_repeat_in_train": real_repeat,
        "by_cwe": dict(sorted(Counter(e["cwe"] for e in examples).items())),
        "by_family": dict(sorted(Counter(e["family"] for e in examples).items())),
        "retries": dict(Counter(e["retry"] for e in examples if e["retry"])),
        "false_positives": sum(e["status"] == "false_positive" for e in examples),
        "dropped": {k: v for k, v in sorted(stats.items()) if k.startswith("dropped")},
    }
    (OUT_DIR / "dataset_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def retrieve_knowledge(knowledge, finding, context, top_k, rerank: bool) -> list[RetrievedChunk]:
    """The same guide and past-fix retrieval as patchai.rag_search.retrieve (no project code)."""
    same_type = lambda c: c.get("cwe") == finding.cwe  # noqa: E731
    guides = search(knowledge["guide"], "guide",
                    f"How to fix {cwe_name(finding.cwe)} ({finding.cwe}) in Python safely. {finding.message}",
                    top_k["guide"], where=same_type, rerank=rerank)
    past = search(knowledge["past_fix"], "past_fix", context.source, top_k["past_fix"], where=same_type, rerank=rerank)
    return guides + past


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=2500, help="how many synthetic pairs to generate")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-rerank", action="store_true", help="skip the reranker (faster)")
    parser.add_argument("--no-real", action="store_true", help="leave out the real-world CVEfixes examples")
    parser.add_argument("--real-repeat", type=int, default=2, help="how often each real example appears in training")
    args = parser.parse_args()
    print(json.dumps(build(args.n, args.seed, rerank=not args.no_rerank, real=not args.no_real,
                           real_repeat=args.real_repeat), indent=2))
