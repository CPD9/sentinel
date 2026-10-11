#!/usr/bin/env bash
# Laptop: decode a folder of WAVs on the GPU Pod and drop the decodes into <artifacts_dir>/cache/asr, so that
#   ./run.sh <wav_folder> --artifacts <artifacts_dir> --workers 4
# reuses them instead of decoding on the laptop CPU (~5 min per call there, ~5 s per call on the Pod's A40).
# Needs the `sentinel-pod` ssh entry (docs/RUN_HIDDEN_SET.md). The audio goes to the Pod (fictional case data only)
# under /workspace/runs/<name>/ and is removed again afterwards. No secrets here.
set -euo pipefail
WAVS=${1:?usage: scripts/pod_asr_folder.sh <wav_folder> <artifacts_dir>}
ART=${2:?usage: scripts/pod_asr_folder.sh <wav_folder> <artifacts_dir>}
NAME="run_$(date +%Y%m%d_%H%M%S)"
REMOTE=/workspace/runs/$NAME
cd "$(dirname "$0")/.."
ssh sentinel-pod "mkdir -p $REMOTE/wav $REMOTE/cache"
scp -q "$WAVS"/*.wav "sentinel-pod:$REMOTE/wav/"
scp -q scripts/pod_asr_folder.py "sentinel-pod:/workspace/sentinel/scripts/pod_asr_folder.py"
ssh sentinel-pod "cd /workspace/sentinel && source pod_env.sh >/dev/null && python scripts/pod_asr_folder.py $REMOTE/wav $REMOTE/cache"
mkdir -p "$ART/cache/asr"
scp -q "sentinel-pod:$REMOTE/cache/*.json" "$ART/cache/asr/"
ssh sentinel-pod "rm -rf $REMOTE"
echo "GPU decodes in $ART/cache/asr: $(ls "$ART/cache/asr" | wc -l | tr -d ' ') files"
