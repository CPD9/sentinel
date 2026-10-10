#!/usr/bin/env bash
# Pod-side: Apertus v1.5 vLLM stack into /workspace/venvs/vllm, WITHOUT Docker, without compiling.
# Mirrors swiss-ai/model-launch images/vllm_apertus_1.5_release/Dockerfile: torch 2.11.0 (cu130), the swiss-ai
# transformers fork (--no-deps), the swiss-ai vLLM fork on top of an upstream precompiled wheel.
# The Pod driver (580.x) supports CUDA 13.0. Run on the Pod: bash scripts/pod_setup_vllm.sh > /workspace/logs/vllm_install.log 2>&1
set -euxo pipefail
export UV_CACHE_DIR=/workspace/cache/uv UV_HTTP_TIMEOUT=500 UV_INDEX_STRATEGY=unsafe-best-match UV_LINK_MODE=copy
export HF_HOME=/workspace/hf
V=/workspace/venvs/vllm
SWISS_AI_VLLM_COMMIT=a601a9d998ddeb488f0c17e8512874b116aa7658
TRANSFORMERS_COMMIT=3797303dda74844e3d1f8977ff5518bb91f818b4
VLLM_REPO_COMMIT=ae6170f874a7c66512bd24aa714b3a02f8a61838     # upstream commit the precompiled wheel was built from
mkdir -p /workspace/src /workspace/logs

[ -x "$V/bin/python" ] || uv venv "$V" --python 3.12
uv pip install --python "$V/bin/python" --extra-index-url https://download.pytorch.org/whl/cu130 \
  torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 "packaging>=24.2" ninja "cmake>=3.26.1" \
  "setuptools>=77.0.3,<81.0.0" "setuptools-scm>=8" "jinja2>=3.1.6" setuptools_rust regex build wheel "protobuf>=6.33.6"

[ -d /workspace/src/transformers ] || git clone --branch feature/apertus_1p5_pipeline https://github.com/swiss-ai/transformers.git /workspace/src/transformers
git -C /workspace/src/transformers checkout "$TRANSFORMERS_COMMIT"
uv pip install --python "$V/bin/python" --no-deps /workspace/src/transformers

[ -d /workspace/src/vllm ] || git clone --branch apertus-1-5 https://github.com/swiss-ai/vllm.git /workspace/src/vllm
git -C /workspace/src/vllm checkout "$SWISS_AI_VLLM_COMMIT"
cd /workspace/src/vllm
export VLLM_PRECOMPILED_WHEEL_VARIANT=cu130 VLLM_MAIN_CUDA_VERSION=13.0
export VLLM_PRECOMPILED_WHEEL_LOCATION="https://wheels.vllm.ai/${VLLM_REPO_COMMIT}/vllm-0.23.1rc1.dev977%2Bgae6170f87-cp38-abi3-manylinux_2_28_x86_64.whl"
export VLLM_PRECOMPILED_WHEEL_COMMIT="$VLLM_REPO_COMMIT"
VLLM_USE_PRECOMPILED=1 uv pip install --python "$V/bin/python" --reinstall-package vllm --no-build-isolation ".[audio]" --torch-backend=auto

"$V/bin/python" -c 'import torch, transformers, vllm; print("torch", torch.__version__, "cuda", torch.version.cuda, "transformers", transformers.__version__, "vllm", vllm.__version__); print(torch.ones(1, device="cuda"))'
"$V/bin/uv" --version >/dev/null 2>&1 || true
uv pip freeze --python "$V/bin/python" > /workspace/logs/vllm-requirements.txt
echo SETUP_DONE
