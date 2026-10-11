#!/usr/bin/env bash
# Pod-side: serve Qwen2.5-32B-Instruct-AWQ on 127.0.0.1:8010 (never 0.0.0.0; 8001 is taken by the Runpod image nginx, which proxies it to :8000) next to Apertus on :8000, same vLLM venv.
# Weights live on the CONTAINER disk (/root/hf): /workspace has too little free space. A Pod restart wipes them;
# re-download (~19 GB, not gated, under a minute on the Pod):
#   HF_HOME=/root/hf /workspace/venvs/vllm/bin/hf download Qwen/Qwen2.5-32B-Instruct-AWQ
# Start detached AFTER Apertus is up (vLLM checks free memory at startup):
#   tmux new-session -d -s qwen 'bash /workspace/sentinel/scripts/pod_serve_qwen.sh'
# VRAM: 0.50 of the 46 GB A40 (~23 GB: ~18.5 GB AWQ weights + KV for 8k context); override with GPU_UTIL.
set -euo pipefail
export HF_HOME=/root/hf HF_HUB_OFFLINE=1
export PATH=/workspace/venvs/vllm/bin:$PATH
export VLLM_USE_FLASHINFER_SAMPLER=0          # see pod_serve_vllm.sh
SNAP=$(ls -d /root/hf/hub/models--Qwen--Qwen2.5-32B-Instruct-AWQ/snapshots/* | head -1)   # path carries the commit hash
mkdir -p /workspace/logs
exec /workspace/venvs/vllm/bin/vllm serve "$SNAP" --served-model-name qwen-32b \
  --host 127.0.0.1 --port 8010 --max-model-len 8192 --gpu-memory-utilization "${GPU_UTIL:-0.50}" --max-num-seqs 8 \
  --chat-template-content-format string \
  2>&1 | tee -a /workspace/logs/vllm_qwen.log
