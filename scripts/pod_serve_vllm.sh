#!/usr/bin/env bash
# Pod-side: serve Apertus v1.5 8B on 127.0.0.1:8000 (never 0.0.0.0) from the local HF cache, offline (no token needed).
# Start detached:  tmux new-session -d -s vllm 'bash /workspace/sentinel/scripts/pod_serve_vllm.sh'
# Shared A40 (46 GB): Apertus 0.45 (~20.7 GB; ~18.1 GB is weights + overhead, 0.40 left only 0.31 GiB KV and failed at 8k),
# Qwen-32B-AWQ 0.50 on :8010 (scripts/pod_serve_qwen.sh). That leaves ~2 GB: stop Qwen (tmux kill-session -t qwen) before
# Whisper ASR (~2.6 GB peak). Apertus alone: GPU_UTIL=0.60. Start Apertus first: vLLM checks free memory at startup.
set -euo pipefail
export HF_HOME=/workspace/hf HF_HUB_OFFLINE=1
export PATH=/workspace/venvs/vllm/bin:$PATH
# FlashInfer's sampler JIT-compiles kernels at warmup (needs ninja + a matching nvcc; the Pod has CUDA 12.8 headers but torch is
# cu130), which crashed the first start. The PyTorch sampler is plenty for 8k-context extraction.
export VLLM_USE_FLASHINFER_SAMPLER=0
SNAP=$(ls -d /workspace/hf/hub/models--swiss-ai--Apertus-v1.5-8B/snapshots/* | head -1)   # path carries the commit hash
mkdir -p /workspace/logs
exec /workspace/venvs/vllm/bin/vllm serve "$SNAP" --served-model-name apertus-8b \
  --host 127.0.0.1 --port 8000 --max-model-len 8192 --gpu-memory-utilization "${GPU_UTIL:-0.45}" --max-num-seqs 8 \
  --chat-template-content-format string --default-chat-template-kwargs.enable_thinking false \
  2>&1 | tee -a /workspace/logs/vllm_serve.log
