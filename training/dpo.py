"""Bonus stage: the model learns from its own mistakes (DPO, Direct Preference Optimization).

Step 1, collect (needs Ollama running our SFT model, `patchai-3b`):
    python training/dpo.py collect --n 400
  For new training cases (never test cases), the SFT model writes 4 fixes each at a higher
  temperature. Our pipeline checks every fix (format, safety guard, re-scan). Each fix that
  FAILS becomes a "rejected" answer, paired with the correct fix as the "chosen" answer.
  Result: data/training/dpo.jsonl

Step 2, train (needs the GPU):
    python training/dpo.py train
  Starts from the merged SFT model and trains it to prefer the chosen answers over its own
  rejected ones. Then export it:
    python training/export.py --run training/runs/dpo --name patchai-3b-dpo
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "training"))

from make_dataset import Prepared, prepare, write_cases  # noqa: E402
from patchai import checks, llm  # noqa: E402
from patchai.fixer import parse_proposal  # noqa: E402
from patchai.guard import check_fix  # noqa: E402
from patchai.patching import apply_fix, read_text  # noqa: E402
from patchai.prompts import answer_json  # noqa: E402
from patchai.scan import scan  # noqa: E402
from synth import generate  # noqa: E402

DATA = ROOT / "data" / "training"


def why_it_fails(case: Prepared, text: str) -> str | None:
    """Run our checks on one model answer. Returns the failure reason, or None if it passes."""
    try:
        proposal = parse_proposal(text)
    except ValueError:
        return "format"
    if proposal.status != "fixed":
        return "gave_up"  # the case is a real vulnerability with a known fix
    original = read_text(case.folder / "module.py")
    patched = apply_fix(original, case.context, proposal)
    if not check_fix(original, patched, proposal, case.context, case.folder).passed:
        return "guard"
    before = scan(case.folder, only_file="module.py", scanners=checks.rescan_scanners(case.finding))
    with checks.patched_copy(case.folder, "module.py", patched.text) as copy:
        if not checks.rescan(copy, case.finding, patched, before).passed:
            return "rescan"
    return None


def collect(n: int, samples: int, model: str, seed: int) -> None:
    pairs = [p for p in generate(n, seed=seed) if p.status == "fixed"]  # a different seed from the SFT data
    rows, stats = [], Counter()
    with tempfile.TemporaryDirectory() as tmp:
        write_cases(pairs, Path(tmp))
        prepared, _ = prepare(pairs, Path(tmp), seed, retry_share=0.0)
        started = time.time()
        for i, case in enumerate(prepared):
            chosen = answer_json(case.answer)
            for _ in range(samples):
                reply = llm.chat(case.messages, model, temperature=0.8)
                reason = why_it_fails(case, reply.text)
                stats[reason or "passed"] += 1
                if reason is not None:
                    rows.append({"id": case.pair.id, "cwe": case.pair.cwe, "reason": reason,
                                 "prompt": case.messages, "chosen": chosen, "rejected": reply.text})
            if (i + 1) % 10 == 0:
                rate = (time.time() - started) / (i + 1)
                print(f"  {i + 1}/{len(prepared)} cases, {len(rows)} pairs, ~{rate * (len(prepared) - i - 1) / 60:.0f} min left")

    random.Random(seed).shuffle(rows)
    DATA.mkdir(parents=True, exist_ok=True)
    with open(DATA / "dpo.jsonl", "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    info = {"cases": len(prepared), "samples_per_case": samples, "model": model, "pairs": len(rows), "outcomes": dict(stats)}
    (DATA / "dpo_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(json.dumps(info, indent=2))


def train(sft_run: Path, run_name: str, beta: float, lr: float, epochs: float, seed: int) -> None:
    from unsloth import FastLanguageModel, PatchDPOTrainer, is_bfloat16_supported

    PatchDPOTrainer()
    from datasets import load_dataset
    from trl import DPOConfig, DPOTrainer

    from train import make_config, make_trainer, save_loss

    out = ROOT / "training" / "runs" / run_name
    # Start from the merged SFT model and add a fresh LoRA. With the LoRA switched off, the
    # model IS the SFT model, which DPO uses as its reference.
    model, tokenizer = FastLanguageModel.from_pretrained(str(sft_run / "merged"), max_seq_length=4096, load_in_4bit=True)
    model = FastLanguageModel.get_peft_model(
        model, r=16, lora_alpha=32, lora_dropout=0, bias="none", use_gradient_checkpointing="unsloth",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"], random_state=seed,
    )
    data = load_dataset("json", data_files=str(DATA / "dpo.jsonl"))["train"]
    data = data.map(lambda row: {
        "prompt": tokenizer.apply_chat_template(row["prompt"], tokenize=False, add_generation_prompt=True),
        "chosen": row["chosen"] + "<|im_end|>",
        "rejected": row["rejected"] + "<|im_end|>",
    }, remove_columns=data.column_names)
    split = data.train_test_split(test_size=0.05, seed=seed)

    config = make_config(DPOConfig, dict(
        output_dir=str(out / "checkpoints"), beta=beta, learning_rate=lr, num_train_epochs=epochs,
        per_device_train_batch_size=1, per_device_eval_batch_size=1, gradient_accumulation_steps=8,
        max_length=4096, max_prompt_length=3584, warmup_ratio=0.1, lr_scheduler_type="cosine",
        optim="adamw_8bit", logging_steps=5, eval_strategy="steps", eval_steps=25, save_strategy="no",
        bf16=is_bfloat16_supported(), fp16=not is_bfloat16_supported(), seed=seed, report_to="none",
    ))
    trainer = make_trainer(DPOTrainer, model, tokenizer, split["train"], split["test"], config, ref_model=None)
    trainer.train()
    model.save_pretrained(str(out / "lora"))
    tokenizer.save_pretrained(str(out / "lora"))
    model.save_pretrained_merged(str(out / "merged"), tokenizer, save_method="merged_16bit")
    save_loss(trainer.state.log_history, out)
    (out / "manifest.json").write_text(json.dumps({
        "kind": "dpo", "started_from": str(sft_run), "beta": beta, "lr": lr, "epochs": epochs,
        "pairs": len(data), "dpo_info": json.loads((DATA / "dpo_info.json").read_text()),
    }, indent=2), encoding="utf-8")
    print(f"Done. Next: python training/export.py --run {out.relative_to(ROOT)} --name patchai-3b-dpo")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="step", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--n", type=int, default=400, help="how many new training cases")
    c.add_argument("--samples", type=int, default=4, help="fixes the model writes per case")
    c.add_argument("--model", default="patchai-3b")
    c.add_argument("--seed", type=int, default=1234)
    t = sub.add_parser("train")
    t.add_argument("--sft-run", type=Path, default=ROOT / "training" / "runs" / "v2")
    t.add_argument("--run-name", default="dpo")
    t.add_argument("--beta", type=float, default=0.1)
    t.add_argument("--lr", type=float, default=5e-6)
    t.add_argument("--epochs", type=float, default=1)
    t.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    if args.step == "collect":
        collect(args.n, args.samples, args.model, args.seed)
    else:
        train(args.sft_run, args.run_name, args.beta, args.lr, args.epochs, args.seed)
