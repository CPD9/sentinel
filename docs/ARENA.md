# Model arena

*Run on 11 Oct 2026 (remote lane 06:20, leaderboard regenerated from cache 06:36). Code: [`scripts/arena.py`](../scripts/arena.py).
Page: `/arena`. Outputs: `artifacts/arena/` (gitignored).*

## Question
Does any open-weight model judge the case calls clearly better than our self-hosted production model, Apertus v1.5 8B?

## Method
- **Same judge as production.** Every model got the S4 direct-judge prompt `judge-asr-v1+cea5e163`, with the same
  strict JSON schema and the same citation validator. Concretely:
  - `pipeline/judge.py:judge_call` with temperature 0 and at most 700 output tokens;
  - `pipeline/validate.py` checks every citation: the segment id must exist, and the quote must be found in the
    cited line.
- **Same data.** The ASR transcripts of all 62 case calls in `artifacts/manifests/inference.json`. 34 calls should be
  escalated (gold alarm or review) and 28 should not.
  - The case calls are fictional. That is the only reason a remote lane exists here.
  - `arena.py` refuses any call id that is not in the case manifest (exit 2). It has no file or upload input.
- **Remote lane.** All 6 models on the OpenRouter open-weight allowlist in `config/providers.yaml`, through the policy
  gate in `pipeline/llm.py`:
  - the gate needs an explicit `SENTINEL_ALLOW_REMOTE_LLM=fictional_data_only` and an allowlisted model;
  - a refusal stops the run, with no fallback;
  - OpenRouter requests are sent with `data_collection: deny`.
- **Self-hosted lane.** Apertus 8B results come from the cached production S4 run. No new calls were made.
- **Metrics.** Labels are read only through `pipeline.evaluate`, after all predictions exist. Nothing is tuned, so the
  holdout split is never tuned on.
  - **AUC:** how well each model's risk score ranks calls against the gold escalation. The 95% CI comes from
    resampling whole dialogues (2000 resamples).
  - **False alarms, missed, balanced accuracy:** from each model's own decision (alarm or review counts as
    escalate).
  - **Citation validity:** valid citations divided by all citations.
  - **Latency:** wall-clock time per call.
  - **Cost:** OpenRouter's reported `usage.cost`.
  - **Failed calls:** a call with no usable answer counts as `no_alert` with risk 0, so a failure costs the model a
    miss and is never hidden.

## Leaderboard
| # | Model | Lane | AUC [95% CI] | False alarms | Missed | Bal. acc. | Citations valid | Latency p50 / p90 | Cost (62 calls) | Failed calls |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | qwen/qwen3-32b | OpenRouter | 0.72 [0.58, 0.85] | 5 / 28 | 11 / 34 | 0.75 | 81 / 88 (92%) | 19.6 s / 25.2 s | $0.017 | 12 |
| 2 | mistralai/mistral-small-3.2-24b-instruct | OpenRouter | 0.69 [0.53, 0.84] | 8 / 28 | 11 / 34 | 0.70 | 75 / 78 (96%) | 2.9 s / 5.6 s | $0.011 | 1 |
| 3 | meta-llama/llama-3.1-8b-instruct | OpenRouter | 0.66 [0.52, 0.79] | 10 / 28 | 13 / 34 | 0.63 | 75 / 86 (87%) | 0.9 s / 2.0 s | $0.028 | 1 |
| 4 | **swiss-ai/Apertus-v1.5-8B** | **self-hosted (production)** | 0.63 [0.53, 0.74] | 0 / 28 | 25 / 34 | 0.63 | 27 / 29 (93%) | 7.6 s / 11.9 s | GPU time | 0 |
| 5 | qwen/qwen-2.5-72b-instruct | OpenRouter | 0.63 [0.48, 0.77] | 21 / 28 | 1 / 34 | 0.61 | 93 / 100 (93%) | 4.1 s / 83.3 s | $0.049 | 1 |
| 6 | meta-llama/llama-3.3-70b-instruct | OpenRouter | 0.63 [0.46, 0.80] | 15 / 28 | 10 / 34 | 0.59 | 61 / 61 (100%) | 3.9 s / 9.2 s | $0.024 | 1 |
| 7 | mistralai/mistral-nemo | OpenRouter | 0.55 [0.44, 0.66] | 27 / 28 | 0 / 34 | 0.52 | 105 / 122 (86%) | 3.3 s / 6.3 s | $0.004 | 1 |

**Total remote cost: $0.13** (0.1331 USD, as reported by OpenRouter).

## Failure notes
- **call_030 fails on every remote model.** Its ASR transcript has one line with a long repeated card number
  ("4242…").
  - The models copy that number into their quote until they hit the 700-token limit, so the JSON never closes and the
    answer is unusable.
  - Apertus answered this call.
  - This is a real weakness of these models with this prompt, not a network error.
- **Qwen3-32B fails 12 calls on the first pass.** Its thinking step appears to use up the same 700-token budget
  intermittently: the failing answers contain no JSON object, or JSON that is cut off.
  - A single retry of call_003 succeeded: 539 output tokens, 13.8 s to the first token.
  - We kept the first-pass numbers and did not retry until success, because that would flatter the model.
  - Its AUC could move either way once the budget issue is fixed, for example with thinking off or a larger
    `max_tokens`.
- **The remote numbers measure OpenRouter-hosted weights.** We don't know how those hosts quantize them.

## Conclusion
**No measured win over self-hosted Apertus 8B.**
- Every challenger's AUC CI overlaps Apertus's (0.53–0.74), so the point estimates alone don't justify a swap.
- Apertus is the most conservative model: 0 false alarms, but 25 of 34 escalation cases missed.

**Next: serve Mistral Small 3.2 24B ourselves and re-measure.** It is the cleanest challenger: 1 failed call, 96% valid
citations, 2.9 s per call. Serve it on our own GPU with the same prompt and cache, then run the arena again. It
replaces production only after a measured win (CI clear of Apertus) and an officer's approval.

## Reproduce
```
SENTINEL_ALLOW_REMOTE_LLM=fictional_data_only python scripts/arena.py --workers 8   # remote lane (cached afterwards)
python scripts/arena.py --no-remote                                                 # re-score from cache, no network
pytest tests/test_arena.py
```
