#!/usr/bin/env bash
# Laptop: decode a folder of WAVs on the GPU Pod and drop the decodes into <artifacts_dir>/cache/asr, so that
#   ./run.sh <wav_folder> --artifacts <artifacts_dir> --workers N
# reuses them instead of decoding on the laptop CPU (docs/PERFORMANCE.md has the measured times).
# Needs the `sentinel-pod` ssh entry (docs/RUN_HIDDEN_SET.md). The audio goes to the Pod (fictional case data only)
# under /workspace/runs/<name>/ and is removed again afterwards. No secrets here.
#
#   scripts/pod_asr_folder.sh <wav_folder> <artifacts_dir> [--flac]
#
# --flac converts to lossless FLAC first (same samples, smaller upload); the cache keys stay those of the WAVs.
# The pipeline code is shipped with the audio into the run dir, so the Pod decodes with exactly this checkout's
# pipeline/asr.py (same cache key and decode settings) and nothing shared on the Pod is overwritten.
set -euo pipefail
WAVS=${1:?usage: scripts/pod_asr_folder.sh <wav_folder> <artifacts_dir> [--flac]}
ART=${2:?usage: scripts/pod_asr_folder.sh <wav_folder> <artifacts_dir> [--flac]}
FMT=wav; [[ "${3:-}" == "--flac" ]] && FMT=flac
NAME="run_$(date +%Y%m%d_%H%M%S)"
REMOTE=/workspace/runs/$NAME
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WAVS="$(cd "$WAVS" && pwd)"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
now() { python3 -c 'import time; print(time.time())'; }
since() { python3 -c "import sys; print(f'{float(sys.argv[2]) - float(sys.argv[1]):.1f}')" "$1" "$(now)"; }

N=$(ls "$WAVS"/*.wav 2>/dev/null | wc -l | tr -d ' ')
[[ "$N" -gt 0 ]] || { echo "no .wav files in $WAVS" >&2; exit 1; }
T0=$(now)
mkdir -p "$STAGE/audio" "$STAGE/code/scripts"
if [[ $FMT == flac ]]; then
  # stem -> sha256 of the WAV, so the Pod writes the WAV's cache key
  "$ROOT/.venv/bin/python" - "$WAVS" "$STAGE/shas.json" <<'PY'
import hashlib, json, sys
from pathlib import Path
out = {}
for w in sorted(Path(sys.argv[1]).glob("*.wav")):
    h = hashlib.sha256()
    with w.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    out[w.stem] = h.hexdigest()
Path(sys.argv[2]).write_text(json.dumps(out))
PY
  ls "$WAVS"/*.wav | xargs -P 8 -I{} sh -c 'ffmpeg -nostdin -loglevel error -y -i "$1" -c:a flac -compression_level 5 "$2/$(basename "${1%.wav}").flac"' _ {} "$STAGE/audio"
else
  for w in "$WAVS"/*.wav; do ln -s "$w" "$STAGE/audio/"; done
fi
T_PREP=$(since "$T0")
cp -R "$ROOT/pipeline" "$STAGE/code/"
cp "$ROOT/scripts/pod_asr_folder.py" "$STAGE/code/scripts/"
BYTES=$(du -shL "$STAGE/audio" | cut -f1)

T1=$(now)
ssh sentinel-pod "mkdir -p $REMOTE/cache"
COPYFILE_DISABLE=1 tar --no-xattrs -chf - -C "$STAGE" . | ssh sentinel-pod "tar xf - --no-same-owner -C $REMOTE"
T_UP=$(since "$T1")

T2=$(now)
SHAS=""; [[ $FMT == flac ]] && SHAS="--shas $REMOTE/shas.json"
ssh sentinel-pod "source /workspace/sentinel/pod_env.sh >/dev/null && cd $REMOTE/code && python scripts/pod_asr_folder.py $REMOTE/audio $REMOTE/cache $SHAS 2>&1 | grep -v -i warning"
T_DEC=$(since "$T2")

T3=$(now)
mkdir -p "$ART/cache/asr"
ssh sentinel-pod "tar cf - -C $REMOTE/cache ." | tar xf - -C "$ART/cache/asr"
ssh sentinel-pod "rm -rf $REMOTE"
T_DOWN=$(since "$T3")
echo "GPU decodes in $ART/cache/asr: $(ls "$ART/cache/asr" | wc -l | tr -d ' ') files"
echo "pod_asr_timing format=$FMT files=$N size=$BYTES prep_s=$T_PREP upload_s=$T_UP decode_s=$T_DEC download_s=$T_DOWN total_s=$(since "$T0")"
