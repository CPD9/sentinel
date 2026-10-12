# Operating concept

How SENTINEL would run in production at a bank, in a secured environment. Short by design: each section says what is
already in the prototype and what a production rollout adds. (Stretch goal "operating concept" of the case brief.)

## 1. Where it runs: on-prem GPU, no egress

| | Prototype (hackathon) | Production |
|---|---|---|
| GPU | one rented NVIDIA A40 (Runpod), fictional data only | on-premise GPU server or a Swiss-region dedicated GPU, inside the bank's network zone for recordings |
| Models | faster-whisper large-v3-turbo (ASR), Apertus v1.5 8B via vLLM (checks): open weights, self-hosted | the same, pinned by revision (`name@revision` is recorded in every result) |
| Network | services bind to `127.0.0.1`, reached only through an SSH tunnel | no inbound port from outside the zone; **no egress**: no cloud AI API, no telemetry, model weights mirrored internally |
| Input | WAV folder, upload in the web app | the call-recording system drops each finished call into the queue; no manual upload |

The pipeline already refuses remote language models for anything but fictional data (`pipeline/llm.py` gate,
`config/providers.yaml`), and every result records `versions.provider` and `versions.self_hosted`.

## 2. Roles

| Role | Can | Cannot |
|---|---|---|
| Compliance officer | see alerts and reviews, play the evidence, mark verdicts (correct, false alarm, missed, escalate), propose threshold or keyword changes | change the shipped configuration alone, delete results |
| Second officer (4-eyes) | confirm or reject an alarm before it is reported; approve configuration changes | approve their own proposal |
| Compliance lead | approve model updates (section 6), set retention | read calls outside their mandate |
| Operator (IT) | run, monitor and update the service; see health and timings | see call content (transcripts, audio, evidence) |

## 3. Four eyes on alarms

An `alarm` is a proposal until a second officer confirms it. Only a confirmed alarm notifies the responsible person
and goes to the Outcept trigger API (`pipeline/trigger.py`, dry-run unless `TRIGGER_URL` is set; the trigger links
straight to the passage, `…/calls/<id>?t=<seconds>`). `review` always goes to a person; a failed stage is recorded as
an error and ends as `review`, never as "all clear".

## 4. Retention

- Audio and transcripts: as long as the bank's call-recording retention requires, not longer; SENTINEL keeps no copy
  beyond the run folder of the period being checked.
- Evidence snippets (±10 s) and the audit record of an alarm: with the compliance case file.
- `no_alert` results: decision, versions and timings only, after the retention period of the recording.
- Display-only analyses (speaker roles, language routing) are personal data under the nDSG and stay in the run
  folder; they never feed a decision ([DIALECT.md](DIALECT.md)).

## 5. Audit log

Every call already produces a complete, reproducible record: the decision, the decision path, the AI judge's checks
with their citations and whether each citation was found word for word, the thresholds, and the exact versions of
ASR model, language model, prompt and rules (`results/`, `traces/`, `judge/` of a run; the printable audit record on
the call page). Production adds an append-only log of who saw, confirmed, rejected or changed what, and when.

## 6. Model and configuration updates: the arena gate plus officer approval

No model, prompt or threshold reaches production because it looks better on one example:

1. **Arena gate**: a challenger model or prompt runs on the same fixed case set as the production one
   ([`docs/ARENA.md`](ARENA.md), `/arena`); it is promoted only if its measured quality is not worse on the agreed
   metrics (no extra false alarms, recall and AUC with confidence intervals), on self-hosted open weights.
2. **Officer approval**: the compliance lead and a second officer approve the change with the arena report in hand;
   the approval is logged with the new version ids.
3. **Threshold and keyword changes** go the same way: the Settings page previews the effect on every cached call
   (missed cases, false alarms, review load) before anything is saved; saving needs the second officer.

## 7. Running it

- Batch: `scripts/run_test_set.sh <folder>` (checks, GPU ASR, pipeline, timing, export), see
  [RUN_HIDDEN_SET.md](RUN_HIDDEN_SET.md). Measured: 20 calls end to end in 10.1 min on one A40 + one laptop
  ([PERFORMANCE.md](PERFORMANCE.md)). Estimate, scaled linearly from that rate and not run: about 8.5 h for 1,000
  calls of the case length on that setup, so a bank-scale volume needs the language model on a larger GPU or several.
- Monitoring: stage errors per call (never silent), timings per stage (`run.py --timings`), review load.
- Failure modes: language model unreachable → every call ends as `review` with a stage error and is re-run from cache
  once it is back; ASR fails for a file → that call ends as `review`, the others are unaffected.
