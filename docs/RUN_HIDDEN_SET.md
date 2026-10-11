# Running SENTINEL on a new set of calls (e.g. the jury's hidden set)

**One command** (measured 11 Oct 2026, [PERFORMANCE.md](PERFORMANCE.md)):

```bash
scripts/run_test_set.sh /path/to/audio_or_the_organisers_packet
```

Rehearsal with 20 new calls under neutral names (101 min of audio, re-encoded copies so no cache could help):
**10.1 min end to end** with 8 workers and zero stage errors: 2.7 min Pod ASR (FLAC upload 80 MB in 31 s, GPU decode
128 s, download 4 s) + 7.4 min pipeline on the laptop (LLM extraction + multi-check judge through the tunnel, plus CPU
audio analysis). Transcription alone is 5.5 s per call on the A40 (RTF 0.020). Without the Pod the laptop decodes on
its CPU at about 62 s per call (RTF 0.22): it still works, it is just slower.

## Prerequisites

1. Repository checkout with the venv: `python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
   -r requirements-asr.txt -r requirements-analysis.txt` (ffmpeg on the PATH for snippets).
2. The `sentinel-pod` entry in `~/.ssh/config` (HostName / Port / User / IdentityFile / known_hosts of the builder
   Pod; the key never goes into the repository).
3. The SSH tunnel to the Pod, left running in its own terminal: `scripts/pod_tunnel.sh` (Pod 127.0.0.1:8000 →
   laptop 127.0.0.1:8000).
4. Apertus up on the Pod: `curl -s http://127.0.0.1:8000/v1/models` lists `apertus-8b`. If not, on the Pod:
   `tmux new-session -d -s vllm 'GPU_UTIL=0.85 bash /workspace/sentinel/scripts/pod_serve_vllm.sh'` (about 2 min).
5. Environment: nothing is required. `ASR_MODEL_PATH` defaults to `mobiuslabsgmbh/faster-whisper-large-v3-turbo`;
   the LLM provider defaults to `builder_pod` (`config/providers.yaml`). Leave `TRIGGER_URL` unset unless alarms
   should really be posted to the Outcept trigger API (otherwise the payloads are written as a dry run).

## The command

```bash
scripts/run_test_set.sh <folder> [--workers 8] [--labels labels.json] [--run-dir DIR] [--wav] [--cpu]
```

It runs, and prints the time of, each step:

1. **checks**: venv, ffmpeg, Apertus reachable through the tunnel, ssh to the Pod, disk space;
2. **audio**: every wav / mp3 / m4a / flac / ogg in the folder; anything that is not 16 kHz mono PCM WAV is converted;
   given the organisers' packet folder, it takes `01_Audio/`;
3. **GPU ASR on the Pod** (`scripts/pod_asr_folder.sh --flac`): lossless FLAC upload in one stream, one model load,
   the decodes land in the run's own `artifacts/cache/asr`; if the Pod is unreachable the run decodes on the CPU;
4. **the pipeline**: `./run.sh <wavs> --out <run>/out --artifacts <run>/artifacts --workers 8 --timings ...`;
   `--artifacts` keeps transcripts, traces, audio analysis and the ASR / LLM caches of this set in its own folder,
   nothing shared is read or written;
5. **summary**: decisions, stage errors, Pod ASR / pipeline / total time (`out/timing_summary.json`), and precision /
   recall in all three conventions if `--labels` (file name → alarm / review / no_alert) is given;
6. **the organisers' result files** in `<run>/export/` ([`scripts/export_organiser.py`](../scripts/export_organiser.py)):
   `Ergebnisse.csv`, `Ergebnisse.jsonl` (one row per `clip_id` = file stem: `alert` = alarm, `manual_review` = review,
   `keyword_ids` K01–K11 found verbatim, `alert_audio_seconds` = start of the alarm's first evidence passage,
   `entity_types` not reported) and `Laufprotokoll.json` (run id, version, settings, audio SHA-256, checked against
   the packet's `Auswahl.json`).

`--workers 8` was the fastest of 4 / 6 / 8 with zero stage errors (PERFORMANCE.md). The two manual steps it wraps
still work on their own:

```bash
scripts/pod_asr_folder.sh /path/to/wavs runs/hidden/artifacts --flac \
  && ./run.sh /path/to/wavs --out runs/hidden/out --artifacts runs/hidden/artifacts --workers 8
```

## Output (`runs/hidden/out/`)

| file | what it is |
|---|---|
| `results.json` | all calls in one `RunResult`: `decision` (alarm / review / no_alert), `risk_score`, `confidence`, `findings` (criterion, reason, evidence with segment ids, times, text, `snippet_path`), `narrative`, `stage_errors`, `versions` |
| `results/<call_id>.json` | the same per call |
| `id_map.json` | original file name → neutral call id (`call_x001` …); file names never reach the pipeline |
| `snippets/<call_id>/*.wav` | the evidence passage ±10 s for every alarm and review, ffprobe-checked |
| `judge/<call_id>.json` | the multi-check judge's verdict: call risk (max over the checks), reason, citations (each marked valid or not) and the per-criterion `checks` |
| `timings.json`, `timing_summary.json` | per-call, per-stage processing times; Pod ASR, pipeline and total time |
| `../export/` | the organisers' result files (Ergebnisse.csv / .jsonl, Laufprotokoll.json) |
| `triggers/` | alarm payloads for the Outcept trigger API (dry run unless `TRIGGER_URL` is set) |
| `../artifacts/traces/<call_id>.json` | the full decision trace: facts with quotes and German gloss, keyword hits, rule results (context, not the decision source), confidence breakdown, why not flagged / what would change |

Read a call: `decision` first; for alarm and review, `findings[0].evidence` gives the passage and the snippet to play;
for no_alert, the trace's `why_not_flagged` and `what_would_change` say why. Thresholds and the keyword switch are in
`config/thresholds.json`; `python -m pipeline.simulate` (or the web Threshold page) re-decides from cache in
milliseconds.

## If the LLM is unreachable

Every call still finishes. Extraction and the judge each record a stage error (`stage_errors: [{"stage":
"extract" | "judge", "message": "…cannot reach http://127.0.0.1:8000…"}]`) and the call becomes **review, never
no_alert and never dropped**; the narrative says a stage failed. Fix the tunnel or restart Apertus, then run the same
command again: decoded audio and finished LLM answers are cached in the run's artifacts dir, so only the missing
work is redone.

## If ASR fails for a file

That call becomes review with a stage error `asr` (unreadable or empty audio); the other calls are unaffected.
