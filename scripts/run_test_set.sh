#!/usr/bin/env bash
# One command for a new set of calls (the organisers' test set): checks, GPU ASR on the Pod, the full pipeline,
# a quality summary if labels are given, a timing summary, and the total time. docs/RUN_HIDDEN_SET.md explains it.
#
#   scripts/run_test_set.sh <audio_folder | organisers' packet> [--workers N] [--labels F] [--run-dir D] [--wav] [--cpu]
#
# Given the organisers' packet folder (with 01_Audio/ and Auswahl.json), it takes the audio from 01_Audio and writes
# their result files (export/Ergebnisse.csv, Ergebnisse.jsonl, Laufprotokoll.json; scripts/export_organiser.py).
#
#   --workers N   calls in parallel on the laptop (default 8, the fastest of 4 / 6 / 8 with 0 stage errors, docs/PERFORMANCE.md)
#   --labels F    {"<file name>": "alarm|review|no_alert"} or CSV file,label; read only after predictions exist
#   --run-dir D   where everything goes (default ~/Developer/sentinel-runs/testset_<timestamp>)
#   --wav         upload WAV instead of lossless FLAC     --cpu   skip the Pod, decode on the laptop CPU (slow)
# Any audio ffmpeg reads (wav, mp3, m4a, flac, ogg) is accepted; files that are not 16 kHz mono WAV are converted.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
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
if [[ $CPU == 0 ]]; then
  if ssh -o ConnectTimeout=8 -o BatchMode=yes sentinel-pod true 2>/dev/null; then ok "ssh sentinel-pod"
  else bad "ssh sentinel-pod failed: falling back to CPU ASR (slow)"; CPU=1; fi
fi
FREE_GB=$(df -g "$RUN" | awk 'NR==2 {print $4}')
[[ ${FREE_GB:-0} -ge 2 ]] && ok "disk ${FREE_GB} GB free" || { bad "less than 2 GB free"; exit 1; }

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
ok "$n files ($conv converted to 16 kHz mono WAV) in $WAVS"

POD_LINE=""
if [[ $CPU == 0 ]]; then
  echo "== GPU ASR on the Pod ($FMT upload)"
  FLAG=""; [[ $FMT == flac ]] && FLAG="--flac"
  if OUT=$("$ROOT/scripts/pod_asr_folder.sh" "$WAVS" "$RUN/artifacts" $FLAG 2>&1); then
    echo "$OUT" | tail -2; POD_LINE=$(echo "$OUT" | grep '^pod_asr_timing' || true)
  else
    echo "$OUT" | tail -5; bad "Pod ASR failed: the run decodes the missing files on the laptop CPU"
  fi
fi

echo "== pipeline ($WORKERS workers)"
mkdir -p "$RUN/out"; echo "$WAVS" > "$RUN/out/source_folder.txt"
"$ROOT/run.sh" "$WAVS" --out "$RUN/out" --artifacts "$RUN/artifacts" --workers "$WORKERS" \
  --timings "$RUN/out/timings.json" --run-id "testset_$(basename "$RUN")"

TOTAL=$(python3 -c "import time; print(round(time.time() - $T0, 1))")
echo "== summary"
"$PY" "$ROOT/scripts/test_set_summary.py" "$RUN/out" --total-s "$TOTAL" --format "$FMT" --label "$(basename "$RUN")" \
  ${POD_LINE:+--pod-asr "$POD_LINE"} ${LABELS:+--labels "$LABELS"}
echo "== export (organisers' format)"
"$PY" "$ROOT/scripts/export_organiser.py" "$RUN" --started-utc "$STARTED" ${PACKAGE:+--package "$PACKAGE"}
echo "results: $RUN/out/results.json · timing: $RUN/out/timing_summary.json · export: $RUN/export/"
