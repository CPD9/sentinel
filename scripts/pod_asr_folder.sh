#!/usr/bin/env bash
# Laptop: decode a folder of WAVs on the GPU Pod and drop the decodes into <artifacts_dir>/cache/asr, so that
#   ./run.sh <wav_folder> --artifacts <artifacts_dir> --workers N
# reuses them instead of decoding on the laptop CPU (docs/PERFORMANCE.md has the measured times).
# Needs the `sentinel-pod` ssh entry (docs/RUN_HIDDEN_SET.md). The audio goes to the Pod (fictional case data only)
# under /workspace/runs/<name>/ and is removed again afterwards. No secrets here.
#
#   scripts/pod_asr_folder.sh <wav_folder> <artifacts_dir> [--flac] [--dry-run] [--model-id NAME@REV]
#
# Retries are incremental: recordings that already have a valid GPU decode in <artifacts_dir>/cache/asr under the
# pipeline's key are neither uploaded nor decoded again (--dry-run only prints what would be decoded).
# --flac converts to lossless FLAC first (same samples, smaller upload); the cache keys stay those of the WAVs.
# The pipeline code is shipped with the audio into the run dir, so the Pod decodes with exactly this checkout's
# pipeline/asr.py (same cache key and decode settings) and nothing shared on the Pod is overwritten. The model is the
# one the pipeline resolves (scripts/asr_cache_check.py id: same name AND revision; the Pod refuses another one), and
# after the download every WAV's GPU decode is checked under the pipeline's own cache key: exit 3 on any mismatch,
# because ./run.sh would otherwise silently re-decode those files on the laptop CPU.
set -euo pipefail
USAGE="usage: scripts/pod_asr_folder.sh <wav_folder> <artifacts_dir> [--flac] [--dry-run] [--model-id NAME@REV]"
WAVS=${1:?$USAGE}
ART=${2:?$USAGE}
shift 2
FMT=wav; DRY=0; MODEL_ID=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --flac) FMT=flac; shift ;;
    --dry-run) DRY=1; shift ;;
    --model-id) MODEL_ID=$2; shift 2 ;;
    *) echo "$USAGE" >&2; exit 2 ;;
  esac
done
NAME="run_$(date +%Y%m%d_%H%M%S)"
REMOTE=/workspace/runs/$NAME
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"; [[ -x "$PY" ]] || PY=python3
WAVS="$(cd "$WAVS" && pwd)"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
now() { python3 -c 'import time; print(time.time())'; }
since() { python3 -c "import sys; print(f'{float(sys.argv[2]) - float(sys.argv[1]):.1f}')" "$1" "$(now)"; }

if [[ -z "$MODEL_ID" ]]; then
  IDLINE=$("$PY" "$ROOT/scripts/asr_cache_check.py" id) || exit 2
  MODEL_ID=$(printf '%s' "$IDLINE" | cut -f2)
fi
SPEC=${MODEL_ID%@*}
echo "ASR model: $MODEL_ID"
TOTAL=$(ls "$WAVS"/*.wav 2>/dev/null | wc -l | tr -d ' ')
[[ "$TOTAL" -gt 0 ]] || { echo "no .wav files in $WAVS" >&2; exit 1; }
# incremental: only recordings without a valid GPU decode under the pipeline's key (a retry skips the rest)
mkdir -p "$ART/cache/asr"
TODO=()
while IFS= read -r name; do [[ -n "$name" ]] && TODO+=("$name"); done \
  < <("$PY" "$ROOT/scripts/asr_cache_check.py" missing "$WAVS" "$ART/cache/asr" "$MODEL_ID")
N=${#TODO[@]}
echo "to decode: $N of $TOTAL ($((TOTAL - N)) already in $ART/cache/asr)"
if [[ $DRY == 1 ]]; then printf '  %s\n' "${TODO[@]+"${TODO[@]}"}"; exit 0; fi
if [[ $N == 0 ]]; then
  "$PY" "$ROOT/scripts/asr_cache_check.py" check "$WAVS" "$ART/cache/asr" "$MODEL_ID" || exit 3
  echo "pod_asr_timing format=$FMT files=0 size=0 prep_s=0.0 upload_s=0.0 decode_s=0.0 download_s=0.0 total_s=0.0"
  exit 0
fi
T0=$(now)
mkdir -p "$STAGE/audio" "$STAGE/code/scripts"
if [[ $FMT == flac ]]; then
  # stem -> sha256 of the WAV, so the Pod writes the WAV's cache key
  "$PY" - "$WAVS" "$STAGE/shas.json" "${TODO[@]}" <<'PY'
import hashlib, json, sys
from pathlib import Path
out = {}
for w in [Path(sys.argv[1]) / n for n in sys.argv[3:]]:
    h = hashlib.sha256()
    with w.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    out[w.stem] = h.hexdigest()
Path(sys.argv[2]).write_text(json.dumps(out))
PY
  printf "$WAVS/%s\n" "${TODO[@]}" | xargs -P 8 -I{} sh -c 'ffmpeg -nostdin -loglevel error -y -i "$1" -c:a flac -compression_level 5 "$2/$(basename "${1%.wav}").flac"' _ {} "$STAGE/audio"
else
  for n in "${TODO[@]}"; do ln -s "$WAVS/$n" "$STAGE/audio/"; done
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
ssh sentinel-pod "source /workspace/sentinel/pod_env.sh >/dev/null && cd $REMOTE/code && python scripts/pod_asr_folder.py $REMOTE/audio $REMOTE/cache $SHAS --model $SPEC --expect-model-id $MODEL_ID 2>&1 | grep -v -i warning; exit \${PIPESTATUS[0]}" || { echo "Pod ASR failed (see above)" >&2; ssh sentinel-pod "rm -rf $REMOTE"; exit 3; }
T_DEC=$(since "$T2")

T3=$(now)
mkdir -p "$ART/cache/asr"
ssh sentinel-pod "tar cf - -C $REMOTE/cache ." | tar xf - -C "$ART/cache/asr"
ssh sentinel-pod "rm -rf $REMOTE"
T_DOWN=$(since "$T3")
echo "GPU decodes in $ART/cache/asr: $(ls "$ART/cache/asr" | wc -l | tr -d ' ') files"
"$PY" "$ROOT/scripts/asr_cache_check.py" check "$WAVS" "$ART/cache/asr" "$MODEL_ID" || exit 3
echo "pod_asr_timing format=$FMT files=$N size=$BYTES prep_s=$T_PREP upload_s=$T_UP decode_s=$T_DEC download_s=$T_DOWN total_s=$(since "$T0")"
