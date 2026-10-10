# SENTINEL

**Every bank call checked, not just samples.**

<p align="center">
  <img src="docs/assets/pipeline.svg" alt="SENTINEL pipeline: call audio, speech detection, Swiss German transcription, fact extraction and keyword matching, evidence validation, rules, confidence gate, decision, narrative and audio snippets, dashboard and trigger API. Evaluation labels reach only evaluate.py." width="100%">
</p>

**Figure 1. From a phone call to a decision with evidence.** AI reads the call, fixed rules decide, and every alert carries the exact audio that caused it.

Built for the Inventx / Outcept case at the sprintd Innovation Sprint Zurich (9–11 October 2026).

---

# Part 1 · For everyone

## The problem

Banks record client phone calls, but people can only listen to a small sample of them. Calls that break the rules, for example an advisor asking for a customer's password or acting on inside information, can slip through unnoticed. Checking every call by hand is impossible, and tools that send recordings to a cloud service are not acceptable for client conversations.

## What SENTINEL does

<p align="center">
  <img src="docs/assets/call-walkthrough.svg" alt="Animated example of one invented call going through five steps: listen, transcribe, understand, decide, show the evidence." width="100%">
</p>

**Figure 2. One call, five steps.** The example is invented; it shows what the compliance officer ends up seeing.

1. **Listen.** SENTINEL takes in the recording of a call, however noisy the line.
2. **Transcribe.** It turns the Swiss German speech into text, with a time stamp for every sentence.
3. **Understand.** It works out who asked for what and who revealed what, instead of just searching for suspicious words. A harmless call that merely contains the word "password" is not flagged.
4. **Decide.** Fixed, readable rules turn what was understood into one of three outcomes: **alarm**, **review** (a person should take a look) or **no alert**.
5. **Show the evidence.** Every alert comes with the exact quote, the time in the call and a short audio clip to play, so a compliance officer can check it in seconds.

## Why it can be trusted

- **Evidence for every alert.** The design discards any alert whose quote cannot be found in the call at the cited time, before anyone sees it.
- **It says when it is unsure.** If the audio is poor, the transcript is doubtful or the evidence conflicts, the call goes to **review**. The design never turns doubt into a confident alarm, and a technical failure is recorded as an error, not as "all clear".
- **Self-hosted by design.** The plan is to run all models on our own server in Switzerland, with no audio or transcript sent to any cloud AI service.
- **People stay in charge.** The AI reads and writes text. The decision comes from rules and thresholds that a compliance officer can read and change without programming.
- **Measured carefully.** Quality is to be reported on held-out calls, with its uncertainty, because the sample is small. No such results exist yet.

## Project status

*As of 10 October 2026.* ✅ done and tested · 🟡 works, but only with mock or invented data · 📐 specified, not yet built · ⬜ not started

| Milestone | What it delivers | Status |
|---|---|---|
| Data and splits | Neutral call IDs, labels kept apart from inference, dev / holdout / test split by dialogue | ✅ |
| Output contract and evaluation | Result schema, three metric conventions with confidence intervals, evidence validity check | ✅ |
| Baseline | One-prompt LLM judge over the reference transcript, the number the real pipeline must beat | 🟡 runs with the `mock` provider (keyword cues, not a model); no real LLM run recorded yet |
| Product and API specification | Every screen mapped to JSON fields, every endpoint and error state ([PRODUCT.md](docs/PRODUCT.md), [API.md](docs/API.md)) | ✅ |
| Mock data for the web app | Example calls, transcripts, traces, events and a quality report in [`fixtures/`](fixtures/README.md) | 🟡 all invented |
| Infrastructure | GPU server in Switzerland, vLLM, SSH tunnel | ⬜ not in the repo yet |
| Transcription | Swiss German speech-to-text, model chosen by bake-off | ⬜ |
| Speaker roles, keywords, fact extraction | Who said what, keyword families, LLM facts | ⬜ |
| Evidence check, rules, confidence, decision | The deterministic core | ⬜ |
| Narrative, audio snippets, trigger | Explanations, playable clips, call to the Outcept API | ⬜ |
| `run.sh` command line | `./run.sh <folder>` produces `out/results.json` and snippets | ⬜ |
| Audio analysis | Waveform, spectrogram, quality score for the UI | 🟡 |
| API service | FastAPI, job queue, live events | 📐 |
| Web app | Inbox, call dashboard, settings, quality lab ([`web/`](web/README.md)) | 🟡 all screens built and shown with MOCK fixtures; not yet run against the real API |

## Team

| Who | Role |
|---|---|
| Peter | AI / ML and full stack |
| Loyola | Infrastructure and integration |
| Jules | Infrastructure and integration |
| Nik | UX and presentation |

---

# Part 2 · For developers

## Quickstart

Requires Python 3.11 and [uv](https://docs.astral.sh/uv/). The pipeline code so far uses only the standard library; `pytest` is the one dev dependency.

```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements-dev.txt
```

Put the case data under `data/case/` and the organisers' 30 % package under `data/test30/` (read-only, never committed), then build the manifests and splits:

```bash
python scripts/prepare_data.py
```

Run the tests:

```bash
pytest
```

Run the baseline without a model (`--provider mock` uses keyword cues, **not** an LLM) and score it:

```bash
python scripts/baseline_direct.py --split dev --provider mock
python -m pipeline.evaluate --pred artifacts/predictions/baseline_direct_MOCK_dev.json --split dev
```

A real baseline run needs `LLM_BASE_URL` (and optionally `LLM_MODEL`) in `.env`, pointing at the vLLM server through the SSH tunnel on `127.0.0.1:8000`.

## Architecture

<p align="center">
  <img src="docs/assets/architecture.svg" alt="Deployment: the compliance officer's laptop reaches FastAPI on an Exoscale GPU VM through an SSH tunnel. The VM runs the pipeline, vLLM with Apertus, faster-whisper and the artifact store, all inside a secured environment. No cloud AI APIs." width="100%">
</p>

**Figure 3. Target deployment: everything that touches a call stays inside the secured environment.** The laptop reaches it only through an SSH tunnel, and no cloud AI API is called, not even for a quick test.

<p align="center">
  <img src="docs/assets/decision.svg" alt="Confidence gate with five components feeding a four-step decision ladder: failed stage, missing evidence or low confidence gives review; validated evidence with risk at or above the alarm threshold gives alarm; risk in the review band gives review; otherwise no alert." width="100%">
</p>

**Figure 4. Doubt is checked first, so an unsure call is meant to end as `review`, not as an alarm.** Thresholds come from `config/thresholds.json`, and the "why not flagged" text is written only after the decision is locked.

The full step-by-step design, output contract and evaluation rules are in [CLAUDE.md](CLAUDE.md).

## Repository layout

```
CLAUDE.md          project guide, hard rules, output contract
docs/              PRODUCT.md (screens → JSON fields), API.md (endpoints), assets/ (figures)
fixtures/          MOCK data for every contract (invented)
pipeline/          schemas.py, evaluate.py, llm.py, reference.py      (stage modules: planned)
scripts/           prepare_data.py, baseline_direct.py
tests/             pytest suite
data/              case data, read-only, gitignored
artifacts/         manifests, splits, cache, predictions, metrics, gitignored
web/               Next.js app (fixtures mode and api mode)
config/ services/ run.sh      planned, not created yet
```

## Documentation

- [CLAUDE.md](CLAUDE.md): rules, pipeline design, output contract, evaluation
- [docs/PRODUCT.md](docs/PRODUCT.md): what each screen shows and which JSON field feeds it
- [docs/API.md](docs/API.md): endpoints, events, settings, error shapes
- [fixtures/README.md](fixtures/README.md): the MOCK data and how to regenerate it
- [web/README.md](web/README.md): running the web app
- [docs/REFERENCE_NOTES.md](docs/REFERENCE_NOTES.md): which reference code the web app adapts, and what it drops

## Data policy

No audio, case data, model weights, `.env` files or secrets go into git (see `.gitignore`). The original dataset under `data/` is read-only. The pipeline reads only neutral call IDs from `artifacts/manifests/inference.json`; labels and original file names live in `evaluation.json` and are read only by `pipeline/evaluate.py`, after predictions exist. The test split is never used for tuning.

## Branching strategy

Work is split by area, with one long-lived branch (`main`) and short-lived topic branches. Each branch prefix has an owning area, changes reach `main` only through a reviewed pull request, and `main` should stay runnable.

```mermaid
gitGraph
    commit id: "main"
    branch ml/asr
    branch infra/gpu-vm
    branch api/jobs
    branch web/inbox
    checkout ml/asr
    commit id: "feature"
    commit id: "tests"
    checkout infra/gpu-vm
    commit id: "setup"
    checkout main
    merge ml/asr id: "PR review"
    checkout api/jobs
    commit id: "endpoints"
    checkout main
    merge infra/gpu-vm id: "PR review "
    checkout web/inbox
    commit id: "screens"
    checkout main
    merge api/jobs id: "PR review  "
    merge web/inbox id: "PR review   "
```

| Prefix | Area |
|---|---|
| `ml/*` | Pipeline, models, evaluation |
| `infra/*` | Servers and deployment |
| `api/*` | Backend service |
| `web/*` | Frontend |
| `docs/*` | Documentation |
