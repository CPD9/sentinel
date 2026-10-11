# Running SENTINEL on a new set of calls (e.g. the jury's hidden set)

Tested on 11 Oct 2026 with 18 WAVs under neutral names (re-encoded copies of dev calls, so no cache could help):
**10.8 min end to end** on a MacBook Air (8 cores) with the builder Pod: 3.2 min Pod ASR (upload 150 MB,
GPU decode 102 s, download), 7.6 min pipeline on the laptop (LLM extraction + direct judge through the tunnel,
4 calls in parallel, plus CPU audio analysis). Without the Pod step the laptop decodes on its CPU at ~5 min per
call with 4 in parallel (~25 min for 18 calls): it still works, it is just slow.

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
scripts/pod_asr_folder.sh /path/to/wavs runs/hidden/artifacts \
  && ./run.sh /path/to/wavs --out runs/hidden/out --artifacts runs/hidden/artifacts --workers 4
```

The first part decodes all WAVs on the Pod's GPU and drops the decodes into the run's own artifacts dir; the second
runs the whole pipeline. Skip the first part if the Pod's SSH is unavailable (CPU ASR, slower). `--artifacts` keeps
transcripts, traces, audio analysis and the ASR / LLM caches of this set in its own folder: nothing shared is read or
written. `--workers 4` is the tested setting (more only competes for the laptop CPU and the shared Apertus).

## Output (`runs/hidden/out/`)

| file | what it is |
|---|---|
| `results.json` | all calls in one `RunResult`: `decision` (alarm / review / no_alert), `risk_score`, `confidence`, `findings` (criterion, reason, evidence with segment ids, times, text, `snippet_path`), `narrative`, `stage_errors`, `versions` |
| `results/<call_id>.json` | the same per call |
| `id_map.json` | original file name → neutral call id (`call_x001` …); file names never reach the pipeline |
| `snippets/<call_id>/*.wav` | the evidence passage ±10 s for every alarm and review, ffprobe-checked |
| `judge/<call_id>.json` | the direct judge's verdict, risk, reason and citations (each marked valid or not) |
| `triggers/` | alarm payloads for the Outcept trigger API (dry run unless `TRIGGER_URL` is set) |
| `../artifacts/traces/<call_id>.json` | the full decision trace: facts with quotes and German gloss, rule results, keyword hits, confidence breakdown, why not flagged / what would change |

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
