#!/usr/bin/env bash
# Pod-side: serve Apertus v1.5 8B on 127.0.0.1:8000 (never 0.0.0.0) from the local HF cache, offline (no token needed).
# Start detached:  tmux new-session -d -s vllm 'bash /workspace/sentinel/scripts/pod_serve_vllm.sh'
# Whisper (~2.6 GB peak) shares the GPU: vLLM gets 0.60 of the 46 GB A40 (override with GPU_UTIL=0.65).
set -euo pipefail
export HF_HOME=/workspace/hf HF_HUB_OFFLINE=1
export PATH=/workspace/venvs/vllm/bin:$PATH
# FlashInfer's sampler JIT-compiles kernels at warmup (needs ninja + a matching nvcc; the Pod has CUDA 12.8 headers but torch is
# cu130), which crashed the first start. The PyTorch sampler is plenty for 8k-context extraction.
export VLLM_USE_FLASHINFER_SAMPLER=0
SNAP=$(ls -d /workspace/hf/hub/models--swiss-ai--Apertus-v1.5-8B/snapshots/* | head -1)   # path carries the commit hash
mkdir -p /workspace/logs
exec /workspace/venvs/vllm/bin/vllm serve "$SNAP" --served-model-name apertus-8b \
  --host 127.0.0.1 --port 8000 --max-model-len 8192 --gpu-memory-utilization "${GPU_UTIL:-0.60}" \
  --chat-template-content-format string --default-chat-template-kwargs.enable_thinking false \
  2>&1 | tee -a /workspace/logs/vllm_serve.log
