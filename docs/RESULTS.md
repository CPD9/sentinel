# SENTINEL results (DRAFT)

Draft while tuning is in progress. Every number here was computed on the date shown, from the runs named.
**Nothing on this page is from the holdout split**: holdout (14 calls) is run exactly once, at the end (final evaluation).

## Model and prompt choice (T2/T3, 11 Oct 2026)

Setup: reference transcripts (not ASR), full pipeline from fact extraction to decision with the **untuned placeholder**
rules and thresholds in `config/`, so absolute numbers are a lower bound for every row; the ranking compares like with like.
Tuning set = dev (28 calls) + Testset_30 (20 calls, cleared by Outcept for tuning) = 48 calls. Both models are
self-hosted on the builder Pod (A40) through `config/providers.yaml`; temperature 0, cached by content hash.
Gold distribution: 21 alarm, 7 review, 20 no_alert.

| model | prompt | esc F1 dev | esc F1 test30 | esc F1 mean | esc F1 all [95% CI] | alarm P | alarm R | macro F1 | false alarms on gold no_alert | failed calls | tokens in/out per call | s per call |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Apertus v1.5 8B** | **v2** | 0.59 | 0.67 | **0.63** | 0.63 [0.47, 0.75] | 0.45 | 0.43 | 0.29 | 10 (+6 review) | 0 | 3490 / 2054 | 106 |
| Apertus v1.5 8B | v1 | 0.42 | 0.75 | 0.59 | 0.58 [0.43, 0.71] | 0.26 | 0.24 | 0.21 | 12 (+6 review) | 0 | 1935 / 492 | 37 |
| Qwen2.5-32B-Instruct-AWQ | v1 | 0.43 | 0.40 | 0.41 | 0.42 [0.24, 0.58] | 0.33 | 0.05 | 0.12 | 2 (+12 review) | 0 | 2003 / 457 | 44 |
| Qwen2.5-32B-Instruct-AWQ | v2 | 0.17 | 0.43 | 0.30 | 0.30 [0.13, 0.45] | 0.00 | 0.00 | 0.11 | 6 (+6 review) | 0 | 3504 / 559 | 54 |

Reference point (not comparable run, dev only): Llama-3.3-70B with prompt v1 through OpenRouter (fictional data only)
reached escalation F1 0.76 on dev.

**Choice: Apertus v1.5 8B (`builder_pod`) with prompt v2.** It was already the default provider and prompt, so no config change.
- Ranking rule: equal-weight mean of dev and Testset_30 escalation F1 (v2 was iterated on dev, so Testset_30 counts at least
  as much as dev), ties → strict-alarm precision, then self-hosted Swiss Apertus. Apertus v2 leads on the mean (0.63) and on
  strict-alarm P/R. Apertus v1 is better on Testset_30 alone (0.75 vs 0.67), so the v1/v2 gap is not clearly significant
  (the CIs overlap heavily).
- Qwen-32B is more conservative under these rules: it labels many acts `hypothetical`/`warn` where Apertus says
  `request`/`disclose`, so few rules fire (strict-alarm recall 0.05 / 0.00). Its facts are valid (2–5 % dropped by the
  evidence validator). With rules tuned for it, it might do better; this grid does not show that.
- Apertus v2 per Stufe (escalation F1, 48 calls): Stufe 1 0.69, Stufe 2 0.57, Stufe 3 0.60.
- Known weakness: 10 false alarms on gold no_alert, 8 of them `credential_sharing` (harmless calls that mention passwords
  or codes, often in a warning). Next lever: counter-evidence handling in `config/rules.yaml` (warn/refuse acts lowering
  risk), calibrated in the final evaluation.

Infrastructure: zero failed calls in all four runs. Two Apertus v2 windows first hit the 3000-token answer limit (the model
lists one fact per utterance, up to 22 per window). `pipeline/extract.py` now splits such a window in half and retries;
windows that fit are unchanged, so cached runs stay valid.

Caveats: n = 48 with clean and noisy recordings of the same dialogue counted separately (they share a script in reference
mode), so the bootstrap CIs (2000 call resamples) are optimistic. Latency is per call with 2–4 calls in parallel and both
models sharing one A40, so it is an upper bound for a single stream.

Reproduce:
```bash
python scripts/run_extract.py --split tune --allow-test --provider builder_pod --prompt v2 --workers 4
python scripts/model_grid.py artifacts/predictions/extract_builder_pod_*_reference_tune*.json
```

## Detection strategies (T4, 11 Oct 2026)

Same tuning set (48 calls, reference transcripts, untuned rules), all LLM work by Apertus v1.5 8B on the builder Pod.
S2 and S3 re-decide the cached prompt-v2 facts; S4 is one prompt per call (`scripts/baseline_direct.py`).
Run `strategy_lab_t4` (`artifacts/bench/strategy_lab_t4/summary.json`), 2000 paired call resamples.

| id | strategy | esc F1 dev | esc F1 test30 | esc F1 all [95% CI] | alarm P | alarm R | macro F1 | false alarms on gold no_alert |
|---|---|---|---|---|---|---|---|---|
| S3 | hybrid: LLM facts + keyword hits through the rules (shipped) | 0.59 | 0.67 | **0.63** [0.47, 0.75] | 0.45 | 0.43 | 0.29 | 10 |
| S2 | context only: LLM facts, no keyword hits | 0.59 | 0.57 | 0.58 [0.42, 0.72] | 0.40 | 0.29 | 0.24 | 8 |
| S8 | ensemble: majority of S1, S3, S4; disagreement → review | 0.53 | 0.55 | 0.54 [0.36, 0.69] | 0.40 | 0.10 | 0.25 | 2 |
| S1 | keywords only (placeholder: alarm at hits in 3 segments of one family) | 0.43 | 0.55 | 0.48 [0.30, 0.64] | 0.44 | 0.19 | 0.23 | 4 |
| S4 | direct judge: one LLM prompt per call | 0.55 | 0.29 | 0.44 [0.23, 0.64] | n/a (no alarm) | 0.00 | 0.31 | 0 |

- **Default stays S3 (hybrid)**, written to `config/strategy_defaults.json` with S2 and S8 as the next two.
- Separable at P ≥ 0.95 (paired bootstrap on escalation F1): only **S3 > S1** (0.958). S3 vs S2, S8 and S4 are not
  separable at n = 48; the order among them is a tendency, not a result.
- Agreement (Cohen's κ): S2 and S3 agree on 90 % of calls (κ 0.84), so keyword hits change few decisions; LLM-fact
  strategies barely agree with S1 and S4 (κ ≤ 0.04). The ensemble follows S1 closely (κ 0.79) and trades recall for
  precision: only 2 false alarms on gold no_alert, but strict-alarm recall drops to 0.10.
- S4 never says `alarm` with this model: Apertus 8B as a one-prompt judge escalates only to review.
- Per Stufe (escalation F1): S3 0.69 / 0.57 / 0.60 for Stufe 1 / 2 / 3; S1 and S4 score 0.00 on Stufe 2.

```bash
python scripts/baseline_direct.py --split dev && python scripts/baseline_direct.py --split test --allow-test
python scripts/strategy_lab.py --facts artifacts/traces_extract/extract_builder_pod_apertus-8b_reference_tune_v2 \
    --direct artifacts/predictions/baseline_direct_builder-pod-apertus-8b_{dev,test}.json --run-id strategy_lab_t4
```
