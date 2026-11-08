"""Fine-tunes Qwen2.5-Coder-3B-Instruct into our model with QLoRA (supervised fine-tuning, SFT).

Needs an NVIDIA GPU (an RTX 4060 laptop with 8 GB is enough). Run on the GPU machine:
    pip install -r requirements-train.txt
    python training/make_dataset.py          # if data/training/train.jsonl doesn't exist yet
    python training/train.py
Then turn it into an Ollama model:
    python training/export.py --run training/runs/v2 --name patchai-3b

Outputs go to training/runs/<name>/:
    lora/          the trained LoRA adapter (small, about 100 MB)
    merged/        base model + adapter merged (needed by dpo.py and export.py --merged)
    loss.json      training and validation loss for every logged step
    loss.png       the loss curves (put this in the report)
    manifest.json  every setting, dataset size and file hash, so the run can be reproduced
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import inspect
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "training"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="QLoRA fine-tuning for PatchAI")
    p.add_argument("--base-model", default="unsloth/Qwen2.5-Coder-3B-Instruct")
    p.add_argument("--run-name", default="v2", help="folder under training/runs/ (v1 was the first model)")
    p.add_argument("--max-seq-length", type=int, default=4096)
    p.add_argument("--epochs", type=float, default=2)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--batch-size", type=int, default=2, help="use 1 (and --grad-accum 16) if you run out of memory")
    p.add_argument("--grad-accum", type=int, default=8)
    p.add_argument("--lora-r", type=int, default=16)
    p.add_argument("--lora-alpha", type=int, default=32)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--no-merged", action="store_true", help="don't save the merged 16-bit model (saves ~6 GB disk)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out = ROOT / "training" / "runs" / args.run_name
    out.mkdir(parents=True, exist_ok=True)

    # Unsloth must be imported before transformers/trl: it patches them to use less memory.
    from unsloth import FastLanguageModel, is_bfloat16_supported
    from unsloth.chat_templates import train_on_responses_only
    from datasets import load_dataset
    from trl import SFTConfig, SFTTrainer

    # 1. Load the base model in 4-bit and add small trainable LoRA layers (QLoRA).
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base_model, max_seq_length=args.max_seq_length, load_in_4bit=True, dtype=None,
    )
    model = FastLanguageModel.get_peft_model(
        model, r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=0, bias="none",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth", random_state=args.seed,
    )

    # 2. Turn each example's chat messages into the model's chat format, drop ones that are too long.
    data = load_dataset("json", data_files={"train": str(DATA / "train.jsonl"), "validation": str(DATA / "val.jsonl")})
    data = data.map(lambda batch: {"text": [tokenizer.apply_chat_template(m, tokenize=False) for m in batch["messages"]]},
                    batched=True, remove_columns=data["train"].column_names)
    before = {split: len(data[split]) for split in data}
    data = data.filter(lambda ex: len(tokenizer(ex["text"]).input_ids) <= args.max_seq_length)
    print({split: f"{len(data[split])}/{before[split]} examples fit in {args.max_seq_length} tokens" for split in data})

    # 3. Train. Only the assistant's answer counts towards the loss, not the prompt.
    config = make_config(SFTConfig, dict(
        output_dir=str(out / "checkpoints"), dataset_text_field="text", max_seq_length=args.max_seq_length,
        per_device_train_batch_size=args.batch_size, per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum, num_train_epochs=args.epochs, learning_rate=args.lr,
        warmup_ratio=0.03, lr_scheduler_type="cosine", weight_decay=0.01, optim="adamw_8bit",
        logging_steps=10, eval_strategy="steps", eval_steps=50, save_strategy="steps", save_steps=200,
        save_total_limit=2, bf16=is_bfloat16_supported(), fp16=not is_bfloat16_supported(),
        seed=args.seed, report_to="none",
    ))
    trainer = make_trainer(SFTTrainer, model, tokenizer, data["train"], data["validation"], config)
    trainer = train_on_responses_only(trainer, instruction_part="<|im_start|>user\n",
                                      response_part="<|im_start|>assistant\n")
    started = time.time()
    trainer.train()
    minutes = (time.time() - started) / 60

    # 4. Save the adapter, the merged model, the loss curves and a manifest.
    model.save_pretrained(str(out / "lora"))
    tokenizer.save_pretrained(str(out / "lora"))
    if not args.no_merged:
        model.save_pretrained_merged(str(out / "merged"), tokenizer, save_method="merged_16bit")
    save_loss(trainer.state.log_history, out)
    manifest = {
        "kind": "sft", "base_model": args.base_model, "settings": vars(args), "minutes": round(minutes, 1),
        "train_examples": len(data["train"]), "val_examples": len(data["validation"]),
        "dataset_sha256": {f: sha256(DATA / f) for f in ("train.jsonl", "val.jsonl")},
        "dataset_info": json.loads((DATA / "dataset_info.json").read_text()) if (DATA / "dataset_info.json").exists() else None,
        "final_eval_loss": next((h["eval_loss"] for h in reversed(trainer.state.log_history) if "eval_loss" in h), None),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Done in {minutes:.0f} minutes. Next: python training/export.py --run {out.relative_to(ROOT)} --name patchai-3b")


def make_config(config_cls, values: dict):
    """Build a TRL config, coping with argument names that changed between TRL versions."""
    fields = {f.name for f in dataclasses.fields(config_cls)}
    renames = {"max_seq_length": "max_length", "eval_strategy": "evaluation_strategy"}
    clean = {}
    for key, value in values.items():
        if key in fields:
            clean[key] = value
        elif renames.get(key) in fields:
            clean[renames[key]] = value
    return config_cls(**clean)


def make_trainer(trainer_cls, model, tokenizer, train, val, config, **extra):
    """Create a TRL trainer; newer versions call the tokenizer `processing_class`."""
    params = inspect.signature(trainer_cls.__init__).parameters
    key = "processing_class" if "processing_class" in params else "tokenizer"
    return trainer_cls(model=model, args=config, train_dataset=train, eval_dataset=val, **{key: tokenizer}, **extra)


def save_loss(history: list[dict], out: Path) -> None:
    """Write loss.json and plot loss.png."""
    train = [(h["step"], h["loss"]) for h in history if "loss" in h]
    val = [(h["step"], h["eval_loss"]) for h in history if "eval_loss" in h]
    (out / "loss.json").write_text(json.dumps({"train": train, "validation": val}, indent=1), encoding="utf-8")
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7, 4))
        if train:
            ax.plot(*zip(*train), label="training loss")
        if val:
            ax.plot(*zip(*val), marker="o", label="validation loss")
        ax.set_xlabel("step")
        ax.set_ylabel("loss")
        ax.set_title(f"PatchAI fine-tuning ({out.name})")
        ax.legend()
        fig.tight_layout()
        fig.savefig(out / "loss.png", dpi=150)
    except ImportError:
        pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    main()
