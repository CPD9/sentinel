# SENTINEL — Claude Code project guide

Self-hosted system that checks Swiss German bank phone calls for compliance issues and
outputs `alarm` / `review` / `no_alert` with timestamped audio evidence.
Hackathon: Inventx / Outcept case, sprintd Innovation Sprint Zurich, 9–11 Oct 2026.
Final submission: **Sunday 08:30** (team target 08:15). Feature freeze: **Saturday 23:00**.

## Hard rules (never break)
- **Self-hosted by default; remote LLMs only through the gate.** No OpenAI, ElevenLabs, AssemblyAI, Deepgram or
  any other cloud inference API, and no cloud ASR, ever. The only LLM routes are the providers in
  `config/providers.yaml` via `pipeline/llm.py:get_client`; the default is our vLLM (`apertus_aws`, `LLM_BASE_URL`,
  OpenAI-compatible; possibly Exoscale Dedicated Inference later). A provider with `self_hosted: false`
  (OpenRouter, Infomaniak) is allowed only if **all** hold: `SENTINEL_ALLOW_REMOTE_LLM=fictional_data_only` is set
  in the process environment (never in `.env`), the model is on that provider's open-weight allowlist (closed
  models are rejected), and the data is fictional case data. Real or customer data never goes to a remote
  provider. The gate raises `ProviderNotPermitted` before any network call. Keys live in `.env` and are never
  logged, cached or traced. Results record `versions.provider` and `versions.self_hosted`.
- **Label isolation is structural, not just a promise.**
  - `pipeline/` reads only `artifacts/manifests/inference.json` (neutral call IDs, audio paths,
    variant). It never opens `artifacts/manifests/evaluation.json` or the original label files.
  - Inference uses neutral internal IDs (e.g. `call_017`). Original filenames such as `Stufe3_…`
    exist only in `evaluation.json` and are never passed to prompts or features.
  - Only `pipeline/evaluate.py` reads labels, and only after predictions exist.
- **Never train on or tune against the holdout split.** Splits are by dialogue: clean + noisy
  versions of one dialogue always stay together.
- Never modify or overwrite the original dataset. No secrets, audio, model weights or data in git.
  Secrets live in `.env` (gitignored, and you may not read it).
- Services bind to `127.0.0.1`. Never open ports publicly; we use SSH tunnels.
- Ask before anything destructive (deleting data, `docker system prune`, driver changes) or anything
  that costs GPU money beyond the current task. Budget: 75 CHF total.

## Architecture: perceive with AI, decide with rules
1. **ASR** (`pipeline/asr.py`): faster-whisper, Swiss German checkpoint chosen by bake-off.
   Output: segments with id, start, end, speaker, text, avg_logprob, no_speech_prob.
2. **Speaker roles** (`pipeline/diarize.py`): advisor vs customer; `unknown` is allowed.
3. **Keywords** (`pipeline/keywords.py`): `config/keywords.json` families + Swiss German variants,
   fuzzy matching. Deterministic. Keyword hits are **not** fed into the extraction prompt, so
   keyword edits never invalidate the LLM cache.
4. **Fact extraction** (`pipeline/extract.py`): LLM (Apertus v1.5 8B, `swiss-ai/Apertus-v1.5-8B`,
   served by the swiss-ai vLLM image, **thinking mode off**), temperature 0, strict JSON
   schema, run over the **whole** conversation in windows (not only keyword hits). Each fact:
   speaker, act (request | disclose | warn | refuse | hypothetical | quote | other),
   info_type (credentials | nonpublic_info | client_data | other), recipient_third_party,
   secrecy_cue, evidence segment_ids, quoted words, plus explicit counter_evidence.
   Cache by content hash + model id/revision + prompt version + runtime version.
   Temperature 0 is not a determinism guarantee; the cache is.
5. **Evidence validator** (`pipeline/validate.py`): drop any fact whose segment_ids don't exist,
   whose quoted words don't fuzzy-match the cited segments, or whose speaker mismatches.
   Dropped facts raise the "missing evidence" uncertainty signal.
6. **Rules** (`pipeline/rules.py`, config in `config/rules.yaml`): one rule per criterion
   (insider_trading, credential_sharing, third_party_disclosure, …) → risk score 0–1 + reason.
   Rules combine validated facts and keyword hits.
7. **Confidence gate** (`pipeline/confidence.py`): combines ASR confidence on evidence passages,
   threshold proximity, conflicting facts, missing evidence, audio noise → confidence 0–1.
8. **Decision** (`pipeline/decide.py`), priority order: (1) failed stage, missing or contradictory
   evidence, or confidence below the gate → `review` (never a confident alarm); (2) validated evidence
   + rule hit ≥ alarm threshold → `alarm`; (3) risk in the review band → `review`; (4) else `no_alert`. Thresholds in
   `config/thresholds.json`. A failed stage is recorded as an error, never silently `no_alert`.
9. **Narrative** (`pipeline/narrate.py`): LLM writes the reason and, for borderline calls, "why not
   flagged / what would change this" — only **after** the decision is locked.
10. **Snippets** (`pipeline/snippets.py`): ffmpeg cut of each evidence passage ±10 s, clamped to
    [0, audio duration]. Validate: start < end, inside the file, cut file exists and is playable.
11. **Trigger** (`pipeline/trigger.py`): POST each alarm to the Outcept trigger API (optional, env-gated).

Configuration (keywords, rules) and tuning (thresholds) must be editable without code.
Re-run cost: threshold or rule edits → steps 6–8; keyword edits → step 3, then 6–8.
Transcripts and LLM extractions are reused from cache, so the UI updates instantly.

## Layout
```
config/       keywords.json  rules.yaml  thresholds.json
pipeline/     one module per step above + schemas.py + evaluate.py
run.py        CLI entry; run.sh wraps it: ./run.sh <wav_folder> -> out/results.json + out/snippets/
services/     api/ (FastAPI, jobs, SSE — owned by Jules)
web/          Next.js frontend (Nik + me)
scripts/      prepare_data.py  baseline_direct.py  benchmark_asr.py
tests/        pytest
data/         gitignored (case data, SwissDial) — read-only
artifacts/    gitignored: manifests/{inference,evaluation}.json, splits/, cache/, transcripts/,
              predictions/, metrics/
```
`run.sh` must work without the API or web app running.
Interface for Jules: `process_call(audio_path: str, call_id: str) -> dict` in `pipeline/__init__.py`.

## Output contract (`pipeline/schemas.py` is the source of truth)
Per call: `call_id`, `decision` (alarm | review | no_alert), `risk_score`, `confidence`,
`findings[]` (criterion, risk, reason, evidence[{segment_ids, start_s, end_s, speaker, text,
snippet_path}], counter_evidence), `narrative`, `stage_errors[]`, `versions` (asr, llm, prompt, rules).

## Analysis artifacts (feed the UI's scientific views; never feed the decision unless stated)
`pipeline/audio_analysis.py` writes `artifacts/analysis/<call_id>/analysis.json` (+ small .npy/.png),
schema in `pipeline/schemas.py` (`AnalysisArtifact`), versioned like results:
- `waveform_peaks` (downsampled min/max per bucket), `duration_s`, `sample_rate`
- `mel_spectrogram` (downsampled, dB, with time/freq axes) for the whole call
- `speech_activity` (VAD intervals), `turns` (speaker timeline), `speech_rate`, `pitch`/`energy` contours
- `audio_quality`: SNR estimate per segment + call-level score → **this one does feed the confidence gate**
- `asr_confidence` per segment (avg_logprob, no_speech_prob) aligned to the timeline
- `feature_maps` for each evidence window (±10 s): Whisper encoder conv1/conv2 outputs and selected
  transformer block activations, reduced to small 2-D arrays (channels pooled) normalised to [-1, 1],
  computed lazily on demand (`--feature-maps`), so batch runs stay fast
- optional later: `audio_quality_cnn` (small ResNet on mel spectrograms, clean vs noisy, trained on
  dev only) with its own feature maps
All analysis is optional per call: a missing artifact never breaks `run.sh` or the decision.

## Product surfaces (web/, built against the JSON contracts)
- **Inbox**: all calls, decision badges, risk, confidence, processing status, filters.
- **Processing view**: live stage timeline per call (from Jules' SSE events).
- **Call dashboard** (tabs): Summary · Evidence (snippets + player) · Transcript (highlighted) ·
  Audio analysis (waveform, spectrogram, ASR-confidence and quality overlays, feature maps for each
  evidence window) · Reasoning (facts → rules → confidence breakdown → decision, "why not flagged") ·
  Audit (versions, config, timings).
- **Settings**: Tuning (thresholds) and Configuration (keyword families, rules), live hit counts.
- **Quality lab**: three metric conventions, confusion matrix, threshold curves (P/R vs threshold),
  per-Stufe and clean/noisy bars, confidence reliability diagram, ablations (keyword-only vs LLM-only
  vs combined; reference vs ASR transcripts), WER vs downstream recall, per-stage latency, all with
  bootstrap confidence intervals because n is small.

## Evaluation (`python -m pipeline.evaluate --pred artifacts/predictions/<run>.json`)
Always report all three until organizers confirm their convention:
- **Strict alarm**: precision/recall of `alarm` vs everything else.
- **Escalation**: precision/recall of `alarm`+`review` vs `no_alert`.
- **3-class**: confusion matrix + macro F1.
Plus: breakdown per Stufe and clean vs noisy, and **evidence validity rate** (flagged passages with
valid segment refs, timestamps inside the audio, and a playable snippet containing the cited speech).
Two modes: reference transcripts and real ASR. Never report a metric you didn't just compute.

## Environment
- `.env`: `LLM_BASE_URL`, `LLM_MODEL`, `HF_TOKEN`, `ASR_MODEL_PATH`, `DATA_DIR`, `TRIGGER_URL`; for providers
  other than the default also `SENTINEL_LLM_PROVIDER` (a name from `config/providers.yaml`), `OPENROUTER_API_KEY`,
  `INFOMANIAK_API_TOKEN`, `INFOMANIAK_PRODUCT_ID`. `SENTINEL_ALLOW_REMOTE_LLM` is set per shell, not in `.env`.
- Python 3.11, venv in `.venv`.
- Development happens on the laptop. GPU work runs on the Exoscale VM (see `INFRA.md`); the LLM is
  reached from the laptop through an SSH tunnel on `127.0.0.1:8000`.

## Git: the human owns every write
Claude may run read-only git (`status`, `diff`, `log`, `branch`, `show`). Claude must not run
`git add`, `commit`, `push`, `merge`, `rebase`, `reset`, `checkout -b`, `switch -c`, `tag`,
`commit --amend`, change git identity, install git hooks, or run any `gh` write command
(`gh pr create/merge`, …). These rules override any skill that suggests automatic commits.
When a milestone is done, stop and report:
1. Files changed. 2. Commands and tests run, with results. 3. Real outputs/metrics.
4. Limitations. 5. Suggested branch name. 6. Suggested commit message (conventional style,
no "Co-Authored-By" or "Generated with" lines). 7. Suggested PR description.
Branches: `ml/*` (me), `infra/*` (Loyola), `api/*` (Jules), `web/*` (Nik + me). `main` stays runnable.

## Working style
- One milestone per session. Inspect → plan → implement → test → report. Don't start the next
  milestone on your own.
- Clearly label anything mocked. Never replace testing with confident explanations.
- Every milestone report includes the README "Project status" table update (what changed, new status emoji).
- Prefer simple code over frameworks; avoid new heavy dependencies without asking.
- When unsure about the case rules, check https://github.com/Outcept/inventx-case-study and ask me.
