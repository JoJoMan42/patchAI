#!/usr/bin/env bash
# PatchAI v2: everything the GPU laptop has to do, in one command.
#
#   cd ~/patchAI && git pull     # always first
#   bash run_4060.sh             # about 4-5 hours, leave it running
#   bash run_4060.sh --dpo       # the same, plus the DPO bonus (about 3-4 hours more)
#
# Safe to stop and re-run: finished steps are skipped and the evaluation resumes.
# Everything is logged to logs/. If it stops with an error, send that log file to the team.

set -euo pipefail
cd "$(dirname "$0")"

DPO=0
SKIP_TESTS=0
for arg in "$@"; do
  case "$arg" in
    --dpo) DPO=1 ;;
    --skip-tests) SKIP_TESTS=1 ;;
    *) echo "Unknown option: $arg (use --dpo or --skip-tests)"; exit 2 ;;
  esac
done

mkdir -p logs
LOG="logs/run_$(date +%Y%m%d_%H%M).log"
exec > >(tee -a "$LOG") 2>&1

step() { echo; echo "==================== $* ===================="; date; }
die() { echo; echo "STOPPED: $*"; echo "Send this log file to the team: $LOG"; exit 1; }
free_gpu() {  # Ollama keeps models in GPU memory for a while; training needs all of it
  for m in $(ollama ps 2>/dev/null | awk 'NR > 1 {print $1}'); do ollama stop "$m" >/dev/null 2>&1 || true; done
}
has_model() {  # read the whole list first: `grep -q` in a pipe + pipefail can wrongly report "missing"
  local names
  names=$(ollama list 2>/dev/null | awk 'NR > 1 {print $1}' | sed 's/:latest$//') || true
  grep -qxF -- "$1" <<< "$names"
}
export_model() {  # export_model <run folder> <ollama name>
  if [ -f "$1/.exported" ] && has_model "$2"; then echo "Already exported: $2"; return; fi
  free_gpu
  python training/export.py --run "$1" --name "$2" \
    || { echo "GGUF export failed, trying the merged-model import instead"; python training/export.py --run "$1" --name "$2" --merged; } \
    || die "Could not load $2 into Ollama"
  touch "$1/.exported"
}

# ---------------------------------------------------------------------------------------------
step "1/8  Checking the setup"
[ -f .venv/bin/activate ] || die "No .venv folder. Create it first (see training/README.md, step 1)."
# shellcheck disable=SC1091
source .venv/bin/activate
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || die "nvidia-smi failed: WSL cannot see the GPU"
python -c "import torch, sys; ok = torch.cuda.is_available(); print('PyTorch sees the GPU:', ok); sys.exit(0 if ok else 1)" \
  || die "PyTorch cannot use the GPU. Run: pip install torch --index-url https://download.pytorch.org/whl/cu124"
python -c "import unsloth, trl, peft" >/dev/null 2>&1 || die "Training tools missing. Run: pip install -r requirements-train.txt"
curl -sf http://localhost:11434/api/tags >/dev/null || die "Ollama is not running. Open another terminal and run: ollama serve"
for m in qwen2.5-coder:3b qwen2.5-coder:7b; do has_model "$m" || ollama pull "$m"; done
pip install -q -e . >/dev/null

# ---------------------------------------------------------------------------------------------
step "2/8  Running PatchAI's own tests (about 3 minutes)"
if [ "$SKIP_TESTS" = 1 ]; then echo "Skipped (--skip-tests)"; else python -m pytest -q || die "PatchAI's tests failed"; fi

# ---------------------------------------------------------------------------------------------
step "3/8  Keeping the first model as patchai-3b-v1 (for the v1 vs v2 comparison)"
if has_model patchai-3b-v1; then
  echo "Already kept."
elif [ -f training/runs/v2/.exported ]; then
  echo "patchai-3b is already the v2 model, so v1 can't be kept any more. The comparison will not include v1."
elif has_model patchai-3b; then
  ollama cp patchai-3b patchai-3b-v1 && echo "Copied patchai-3b -> patchai-3b-v1"
else
  echo "No v1 model in Ollama. Fine: the comparison will just not include v1."
fi

# ---------------------------------------------------------------------------------------------
step "4/8  Building the v2 training data (20-40 minutes)"
if python -c "
import json, sys
from pathlib import Path
info, train = Path('data/training/dataset_info.json'), Path('data/training/train.jsonl')
ok = info.exists() and train.exists() and json.loads(info.read_text()).get('prompt_version') == 'v2'
sys.exit(0 if ok else 1)"; then
  echo "Already built."
else
  python training/make_dataset.py --n 2500 || die "Building the dataset failed"
fi

# ---------------------------------------------------------------------------------------------
step "5/8  Training patchai-3b v2 (about 2 hours, don't close this window)"
if [ -f training/runs/v2/manifest.json ] && [ -d training/runs/v2/lora ]; then
  echo "Already trained."
else
  free_gpu
  python training/train.py --run-name v2 \
    || { echo "Training failed (probably out of GPU memory). Trying again with a smaller batch..."; \
         python training/train.py --run-name v2 --batch-size 1 --grad-accum 16; } \
    || die "Training failed"
fi

# ---------------------------------------------------------------------------------------------
step "6/8  Loading the v2 model into Ollama as patchai-3b (10-20 minutes)"
export_model training/runs/v2 patchai-3b
python eval/run_eval.py --split dev --limit 2 --run-name smoke_v2 --models patchai-3b || die "The new model doesn't work in the pipeline"

# ---------------------------------------------------------------------------------------------
step "7/8  The experiment: every model on the 53 test cases (1-2 hours)"
MODELS="qwen2.5-coder:3b"
has_model patchai-3b-v1 && MODELS="$MODELS patchai-3b-v1"
MODELS="$MODELS patchai-3b qwen2.5-coder:7b"
# shellcheck disable=SC2086
python eval/run_eval.py --run-name v2 --models $MODELS || die "The evaluation failed (re-run this script to resume)"
python eval/report.py --run v2

# ---------------------------------------------------------------------------------------------
if [ "$DPO" = 1 ]; then
  step "Bonus: DPO, the model learns from its own mistakes (3-4 hours)"
  [ -f data/training/dpo.jsonl ] || python training/dpo.py collect --n 400 || die "DPO collect failed"
  free_gpu
  [ -f training/runs/dpo/manifest.json ] || python training/dpo.py train --sft-run training/runs/v2 || die "DPO training failed"
  export_model training/runs/dpo patchai-3b-dpo
  python eval/run_eval.py --run-name v2 --models patchai-3b-dpo || die "The DPO evaluation failed"
  python eval/report.py --run v2
fi

# ---------------------------------------------------------------------------------------------
step "8/8  Packing up the results"
python -c "import shutil; shutil.make_archive('logs/v2_full_eval_logs', 'zip', 'eval/results/v2', 'full')"
GGUF=$(find training/runs/v2 -name '*.gguf' 2>/dev/null | head -n 1 || true)
cat <<EOF

DONE. Results: eval/results/v2/results.md

Now send the results to the team:
  git add eval/results/v2 training/runs/v2/loss.png training/runs/v2/manifest.json data/training/dataset_info.json
  git commit -m "v2 training and evaluation results"
  git push

And upload these two files to Google Drive (too big for GitHub):
  logs/v2_full_eval_logs.zip      every attempt of every case (for the error analysis)
  ${GGUF:-training/runs/v2/... .gguf}      the trained v2 model, for the demo laptop
EOF
