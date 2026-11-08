"""Turns a trained model into an Ollama model, so the pipeline can use it by name.

Three ways, depending on what you have:

  1. On the GPU machine (Linux, WSL or Colab), straight from a training run:
       python training/export.py --run training/runs/v2 --name patchai-3b
     Unsloth converts the model to GGUF (4-bit, q4_k_m) and registers it with Ollama.

  2. If GGUF conversion fails (it compiles llama.cpp, which can be painful on Windows):
       python training/export.py --run training/runs/v2 --name patchai-3b --merged
     Ollama imports the merged 16-bit model itself and quantizes it to q4_K_M.

  3. On the demo laptop, with a .gguf file copied from the GPU machine:
       python training/export.py --gguf path/to/model.gguf --name patchai-3b
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Qwen's chat format (ChatML). Used only if `ollama show <base>` is not available.
CHATML_TEMPLATE = '''TEMPLATE """{{- if .System }}<|im_start|>system
{{ .System }}<|im_end|>
{{ end }}
{{- range .Messages }}{{- if or (ne .Role "system") (not $.System) }}<|im_start|>{{ .Role }}
{{ .Content }}<|im_end|>
{{ end }}{{- end }}<|im_start|>assistant
"""
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|endoftext|>"'''


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", type=Path, help="a training run folder (has lora/ and merged/)")
    p.add_argument("--gguf", type=Path, help="an existing .gguf file")
    p.add_argument("--name", default="patchai-3b", help="name of the model in Ollama")
    p.add_argument("--merged", action="store_true", help="let Ollama import the merged model instead of GGUF")
    p.add_argument("--base", default="qwen2.5-coder:3b", help="Ollama model to copy the chat template from")
    args = p.parse_args()

    if args.gguf:
        source = args.gguf.resolve()
        quantize = None
    elif args.run and args.merged:
        source, quantize = (args.run / "merged").resolve(), "q4_K_M"
    elif args.run:
        source, quantize = to_gguf(args.run.resolve()), None
    else:
        p.error("give --run or --gguf")

    modelfile = (args.run or args.gguf.parent).resolve() / "Modelfile"
    modelfile.write_text(f"FROM {source.as_posix()}\n{chat_template(args.base)}\n"
                         "PARAMETER temperature 0.1\nPARAMETER num_ctx 8192\n", encoding="utf-8")
    command = ["ollama", "create", args.name, "-f", str(modelfile)]
    if quantize:
        command += ["--quantize", quantize]
    print("Running:", " ".join(command))
    subprocess.run(command, check=True)
    print(f"Done. `ollama run {args.name}` works now, and PatchAI uses it as the default model.")


def to_gguf(run: Path) -> Path:
    """Convert the LoRA run to a 4-bit GGUF file with Unsloth (needs the GPU machine)."""
    from unsloth import FastLanguageModel

    model, tokenizer = FastLanguageModel.from_pretrained(str(run / "lora"), max_seq_length=4096, load_in_4bit=True)
    out = run / "gguf"
    model.save_pretrained_gguf(str(out), tokenizer, quantization_method="q4_k_m")
    # Depending on the Unsloth version the file lands in gguf/ or gguf_gguf/ (or next to them).
    files = sorted(run.rglob("*.gguf"), key=lambda f: ("q4_k_m" not in f.name.lower(), -f.stat().st_mtime))
    if not files:
        sys.exit(f"No .gguf file was written under {run}. Try --merged instead.")
    return files[0].resolve()


def chat_template(base: str) -> str:
    """Copy the TEMPLATE and stop words from the base model, so prompts are formatted identically."""
    try:
        text = subprocess.run(["ollama", "show", base, "--modelfile"], capture_output=True, text=True,
                              check=True, encoding="utf-8").stdout
    except (OSError, subprocess.CalledProcessError):
        return CHATML_TEMPLATE
    keep, inside = [], False
    for line in text.splitlines():
        if line.startswith("TEMPLATE"):
            inside = line.count('"""') == 1
            keep.append(line)
        elif inside:
            keep.append(line)
            inside = '"""' not in line
        elif line.startswith("PARAMETER stop"):
            keep.append(line)
    return "\n".join(keep) if keep else CHATML_TEMPLATE


if __name__ == "__main__":
    main()
