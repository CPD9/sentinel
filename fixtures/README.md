# fixtures/ — MOCK data

**Everything in this folder is invented.** No model ran, and no case data was read. These files let the web app
and the API be built before ASR and the LLM run. Each document is marked: side artifacts have
`"is_mock": true`, call results have `versions` = `"MOCK"` and a narrative starting with `[MOCK]`.

Regenerate (deterministic, stdlib only; `tests/test_fixtures.py` fails if the files drift):

```bash
.venv/bin/python fixtures/make_fixtures.py
```

| File | Schema (`pipeline/schemas.py`) | Shows |
|---|---|---|
| `calls.json` | `list[CallListItem]` | Inbox: done alarm, done no_alert, processing, error |
| `call_MOCK_001.*` | result / transcript / trace / analysis / events | **alarm**, credential sharing: advisor asks for the password, customer reads it out. Has counter-evidence, a dropped fact and a full SSE event log |
| `call_MOCK_002.*` | result / transcript / trace / analysis | **no_alert** although "Passwort" occurs 3× (jury moment 3). Its analysis is partial: `pitch` failed, which shows the partial-artifact state |
| `call_MOCK_003` | list row only | still processing (detail endpoints → 202) |
| `call_MOCK_004.result.json` | CallResult | ASR stage error → `review`, never no_alert |
| `quality_report.json` | QualityReport | test split, n=20, all three conventions with bootstrap CIs, curves, reliability, ablations, WER bins, latency. The numbers come from an invented per-call table scored with `pipeline.evaluate`'s own metric functions |
| `whatif_calls.json` | plain JSON | 12 invented sample calls `call_MOCK_101..112` (no detail documents): decision, path, risk, confidence and the decision each would get if one keyword family or rule were switched off. Feeds the fixtures-mode what-if approximation |
| `feedback.json` | `list[FeedbackEntry]` | invented officer verdicts on those calls (3 false alarms, 6 correct) |
| `simulation.json` | `SimulationResult` | the real `simulate()` result for "alarm threshold 0.87" over the sample calls |
| `suggestions.json` | `SuggestionsResponse` | the real `suggest()` output for that feedback: ranked patches with their simulated effect |

The last four are produced by running the **real** `pipeline.simulate` / `pipeline.suggest` over the sample calls
(`fixtures/whatif_corpus.py`), with the config frozen in `fixtures/config_snapshot/` so tuning `config/` never makes them drift.

There is no audio here (`*.wav` is gitignored), so `snippet_path` points to files that do not exist.
The UI must show its "snippet unavailable" state. `feature_maps` is null everywhere (STRETCH).
