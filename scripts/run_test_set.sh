#!/usr/bin/env bash
# One command for a new set of calls (the organisers' test set): checks, GPU ASR on the Pod, the full pipeline,
# a quality summary if labels are given, a timing summary, and the total time. docs/RUN_HIDDEN_SET.md explains it.
#
#   scripts/run_test_set.sh <audio_folder | organisers' packet> [--workers N] [--labels F] [--run-dir D] [--wav] [--cpu]
#   scripts/run_test_set.sh --export-only <run_dir> [--package <packet>]     # re-export a finished run
#
# Given the organisers' packet folder (with 01_Audio/ and Auswahl.json), it takes the audio from 01_Audio and writes
# their result files (export/Ergebnisse.csv, Ergebnisse.jsonl, Laufprotokoll.json; scripts/export_organiser.py).
#
#   --workers N   calls in parallel on the laptop (default 8, the fastest of 4 / 6 / 8 with 0 stage errors, docs/PERFORMANCE.md)
#   --labels F    {"<file name>": "alarm|review|no_alert"} or CSV file,label; read only after predictions exist
#   --run-dir D   where everything goes (default ~/Developer/sentinel-runs/testset_<timestamp>)
#   --wav         upload WAV instead of lossless FLAC     --cpu   skip the Pod, decode on the laptop CPU (~1 min per call)
# The Pod and the pipeline use the same ASR model (pipeline.asr.DEFAULT_ASR_MODEL, name AND revision): if the Pod is
# unreachable or its decodes do not match the pipeline's cache keys, the run stops instead of silently re-decoding on
# the CPU (rerun with --cpu to accept that on purpose).
# Any audio ffmpeg reads (wav, mp3, m4a, flac, ogg) is accepted; files that are not 16 kHz mono WAV are converted.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Export in the organisers' format; exit 4 from the exporter = integrity check failed: outputs are kept, the banner is
# repeated at the very end instead of the success line, and this script exits 4 too.
export_results() {   # <run_dir> <package or ""> <started_utc>
  local py="$ROOT/.venv/bin/python"; [[ -x "$py" ]] || py=python3
  echo "== export (organisers' format)"
  local rc=0
  "$py" "$ROOT/scripts/export_organiser.py" "$1" --started-utc "$3" ${2:+--package "$2"} 2> "$1/export_stderr.txt" || rc=$?
  cat "$1/export_stderr.txt" >&2
  if [[ $rc -eq 4 ]]; then INTEGRITY_FAILED=1; elif [[ $rc -ne 0 ]]; then echo "export failed (exit $rc)" >&2; exit "$rc"; fi
}
finish() {   # <run_dir> <success line>
  if [[ ${INTEGRITY_FAILED:-0} == 1 ]]; then
    echo; cat "$1/export_stderr.txt" >&2
    echo "outputs kept in $1 (results, timing, export) for inspection" >&2
    exit 4
  fi
  echo "$2"
}
if [[ "${1:-}" == "--export-only" ]]; then
  RUN_ONLY=$(cd "${2:?usage: run_test_set.sh --export-only <run_dir> [--package <packet>]}" && pwd)
  PKG=""; [[ "${3:-}" == "--package" ]] && PKG=$(cd "${4:?--package needs a folder}" && pwd)
  export_results "$RUN_ONLY" "$PKG" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  finish "$RUN_ONLY" "export: $RUN_ONLY/export/"
  exit 0
fi

SRC=${1:?usage: scripts/run_test_set.sh <audio_folder> [--workers N] [--labels F] [--run-dir D] [--wav] [--cpu]}
shift
WORKERS=8; LABELS=""; RUN=""; FMT=flac; CPU=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --workers) WORKERS=$2; shift 2 ;;
    --labels) LABELS=$(cd "$(dirname "$2")" && pwd)/$(basename "$2"); shift 2 ;;
    --run-dir) RUN=$2; shift 2 ;;
    --wav) FMT=wav; shift ;;
    --cpu) CPU=1; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
SRC="$(cd "$SRC" && pwd)"
PACKAGE=""
if [[ -d "$SRC/01_Audio" ]]; then PACKAGE="$SRC"; SRC="$SRC/01_Audio"; fi
RUN=${RUN:-$HOME/Developer/sentinel-runs/testset_$(date +%Y%m%d_%H%M%S)}
mkdir -p "$RUN"; RUN="$(cd "$RUN" && pwd)"
PY="$ROOT/.venv/bin/python"
# one model spec for the Pod and for run.py (overrides .env, which run.py would read otherwise)
export ASR_MODEL_PATH="$("$PY" -c 'import sys; sys.path.insert(0, sys.argv[1]); from pipeline.asr import DEFAULT_ASR_MODEL; print(DEFAULT_ASR_MODEL)' "$ROOT")"
now() { python3 -c 'import time; print(time.time())'; }
T0=$(now)
STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
ok() { printf '  \033[32mok\033[0m  %s\n' "$1"; }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; }

echo "== checks"
[[ -x "$PY" ]] && ok "venv" || { bad "no .venv (see docs/RUN_HIDDEN_SET.md)"; exit 1; }
command -v ffmpeg >/dev/null && ok "ffmpeg" || { bad "ffmpeg not on PATH"; exit 1; }
if curl -sf -m 5 http://127.0.0.1:8000/v1/models | grep -q apertus; then ok "Apertus reachable on 127.0.0.1:8000"
else bad "Apertus not reachable: start scripts/pod_tunnel.sh (calls would end as review with a stage error)"; exit 1; fi
IDLINE=$("$PY" "$ROOT/scripts/asr_cache_check.py" id) || { bad "ASR model cannot be reproduced on the Pod"; exit 1; }
ok "ASR model $(printf '%s' "$IDLINE" | cut -f2)"
if [[ $CPU == 0 ]]; then
  if ssh -o ConnectTimeout=8 -o BatchMode=yes sentinel-pod true 2>/dev/null; then ok "ssh sentinel-pod"
  else bad "ssh sentinel-pod failed: start the Pod / fix ~/.ssh/config, or rerun with --cpu (laptop ASR, ~1 min per call)"; exit 1; fi
fi
# portable (macOS + Linux): POSIX df in 1 KiB blocks, column 4 = available
FREE_KB=$(df -Pk "$RUN" | awk 'NR==2 {print $4}')
if [[ ${FREE_KB:-0} -ge $((2 * 1024 * 1024)) ]]; then ok "disk $((FREE_KB / 1024 / 1024)) GB free"; else bad "less than 2 GB free"; exit 1; fi

echo "== audio"
WAVS="$RUN/wavs"; mkdir -p "$WAVS"
n=0; conv=0
shopt -s nullglob nocaseglob
for f in "$SRC"/*.{wav,mp3,m4a,flac,ogg,aac}; do
  n=$((n+1)); stem=$(basename "${f%.*}")
  info=$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,sample_rate,channels -of csv=p=0 "$f" || true)
  if [[ "$info" == "pcm_s16le,16000,1" && "${f##*.}" =~ ^[wW][aA][vV]$ ]]; then cp -c "$f" "$WAVS/$stem.wav" 2>/dev/null || cp "$f" "$WAVS/$stem.wav"
  else ffmpeg -nostdin -loglevel error -y -i "$f" -ar 16000 -ac 1 -c:a pcm_s16le "$WAVS/$stem.wav"; conv=$((conv+1)); fi
done
shopt -u nullglob nocaseglob
[[ $n -gt 0 ]] || { bad "no audio files in $SRC"; exit 1; }
mkdir -p "$RUN/out"
# SHA-256 of the ORIGINAL files, before any conversion (Laufprotokoll.json, check against Auswahl.json)
"$PY" - "$SRC" "$RUN/out/source_files.json" <<'PYEOF'
import hashlib, json, sys
from pathlib import Path
out = {}
for f in sorted(Path(sys.argv[1]).iterdir()):
    if f.suffix.lower() in {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"} and f.is_file():
        h = hashlib.sha256()
        with f.open("rb") as fh:
            for c in iter(lambda: fh.read(1 << 20), b""):
                h.update(c)
        out[f.stem] = {"file": f.name, "sha256": h.hexdigest()}
Path(sys.argv[2]).write_text(json.dumps(out, indent=1))
PYEOF
ok "$n files ($conv converted to 16 kHz mono WAV) in $WAVS"

POD_LINE=""
if [[ $CPU == 0 ]]; then
  echo "== GPU ASR on the Pod ($FMT upload)"
  FLAG=""; [[ $FMT == flac ]] && FLAG="--flac"
  # incremental on a retry (same --run-dir): recordings already decoded are not uploaded again
  if OUT=$("$ROOT/scripts/pod_asr_folder.sh" "$WAVS" "$RUN/artifacts" $FLAG --model-id "$(printf '%s' "$IDLINE" | cut -f2)" 2>&1); then
    echo "$OUT" | tail -2; POD_LINE=$(echo "$OUT" | grep '^pod_asr_timing' || true)
  else
    echo "$OUT" | tail -5; bad "Pod ASR failed or its decodes do not match the pipeline's model: stopping (rerun with --cpu to decode on the laptop on purpose)"; exit 3
  fi
fi

echo "== pipeline ($WORKERS workers)"
echo "$WAVS" > "$RUN/out/source_folder.txt"
"$ROOT/run.sh" "$WAVS" --out "$RUN/out" --artifacts "$RUN/artifacts" --workers "$WORKERS" \
  --timings "$RUN/out/timings.json" --run-id "testset_$(basename "$RUN")"

TOTAL=$(python3 -c "import time; print(round(time.time() - $T0, 1))")
echo "== summary"
"$PY" "$ROOT/scripts/test_set_summary.py" "$RUN/out" --total-s "$TOTAL" --format "$FMT" --label "$(basename "$RUN")" \
  ${POD_LINE:+--pod-asr "$POD_LINE"} ${LABELS:+--labels "$LABELS"}
export_results "$RUN" "$PACKAGE" "$STARTED"
finish "$RUN" "results: $RUN/out/results.json · timing: $RUN/out/timing_summary.json · export: $RUN/export/"
