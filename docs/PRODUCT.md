# SENTINEL — product spec (web surfaces → JSON fields)

What each screen shows, which JSON field feeds each element, and what it shows when the data is
empty, loading or broken. The contracts are in `pipeline/schemas.py`. The endpoints are in [API.md](API.md).
MOCK data for every contract is in `fixtures/` (see `fixtures/README.md`).

## Conventions

**Field paths.** A path starts with the document it comes from. `[]` means "each item of the list".

| Prefix | Document | Schema | Endpoint | Fixture |
|---|---|---|---|---|
| `calls[].` | inbox row | `CallListItem` | `GET /api/calls` | `calls.json` |
| `event.` | SSE payload | `ProcessingEvent` | `GET /api/calls/{id}/events` | `call_MOCK_001.events.json` |
| `result.` | call result | `CallResult` | `GET /api/calls/{id}` | `call_MOCK_00x.result.json` |
| `transcript.` | transcript | `Transcript` | `GET /api/calls/{id}/transcript` | `call_MOCK_00x.transcript.json` |
| `trace.` | decision trace | `DecisionTrace` | `GET /api/calls/{id}/trace` | `call_MOCK_00x.trace.json` |
| `analysis.` | audio analysis | `AnalysisArtifact` | `GET /api/calls/{id}/analysis` | `call_MOCK_00x.analysis.json` |
| `quality.` | quality report | `QualityReport` | `GET /api/quality/{report_id}` | `quality_report.json` |
| `simulation.` | what-if result | `SimulationResult` | `POST /api/simulate` | `simulation.json` |
| `suggestions.` | ranked suggestions | `SuggestionsResponse` | `GET /api/suggestions` | `suggestions.json` |
| `feedback[].` | officer verdicts | `FeedbackEntry` | `GET /api/feedback` | `feedback.json` |

`tests/test_fixtures.py` checks that every path quoted in this file (outside the STRETCH section)
exists in the fixtures. If you rename a field, the test fails until this doc is updated too.

**Global UI rules**
- Decision badge colours: `alarm` red, `review` amber, `no_alert` grey. A `review` is never styled as a
  confident alarm. A call with stage errors shows a red "stage error" chip next to its badge, and its
  decision is never `no_alert` (the schema enforces this).
- **MOCK banner.** Show a persistent "MOCK DATA" banner when any loaded document has `is_mock: true`,
  or when every value in `result.versions` is `"MOCK"`.
- Times are shown as `mm:ss` (one decimal for windows shorter than 10 s). Scores 0–1 are shown as
  0–100 %. Risk and confidence are always shown together.
- **Axis labels and units are never hardcoded.** Every chart reads them from the `axes` object of its
  data block (`{label, unit}` for `x`, `y`, `value`).
- Every surface has three states. **Loading**: a skeleton in the final layout, with no spinner-only
  pages. **Empty**: one sentence saying why, plus the next action. **Error**: what failed, with the
  `{error, detail}` text from the API and a retry button. A missing optional block (analysis, trace) is
  an *empty* state, not an error.

---

## 1. Overview (two panels)

The default page (`/`). Left: every call, grouped by what the officer has to do. Right: the selected call
(`/?call=<id>`, default the first alarm), enough to judge it without leaving the page. On narrow screens the two
panels stack. Components: `web/components/inbox/` (`call-list.tsx`, `call-panel.tsx`, `excerpt-player.tsx`).

**Left panel: call list**

| Element | Fed by |
|---|---|
| Groups Alarms / To review / No alert / Processing, each with its count (No alert folded by default; Processing only while something runs) | `calls[].decision`, `calls[].status` |
| Row: call ID, kind of fraud, risk %, time | `calls[].call_id`, `calls[].criteria`, `calls[].risk_score`, `calls[].updated_at` |
| Stage error chip (risk hidden when a failed call was never checked) | `calls[].n_stage_errors` |
| Processing rows show the current stage | `GET /api/events` (global SSE), latest `event.stage` |

Within a group: risk descending (Processing: newest first).

**Right panel: selected call**

| Element | Fed by |
|---|---|
| Header: decision │ call ID · time · duration, link "Open full call" | `calls[].decision`, `calls[].duration_s` |
| What was said: cited lines bold (click = play that passage), one line before and after in grey, keywords underlined | `result.findings[].evidence[].segment_ids`, `transcript.segments[].text`, `trace.keyword_hits[].segment_id`, `trace.keyword_hits[].matched_text` |
| One player: the passage ±10 s over the call's waveform, cited words highlighted | `result.findings[].evidence[].snippet_path`, `analysis.waveform_peaks.max` |
| Risk and threshold: big %, one bar with the alarm threshold; confidence as one line (above / below the gate) | `result.risk_score`, `result.confidence`, `GET /api/settings/thresholds` |
| Why this was flagged / why a person must look / why it was not flagged | `result.findings[].reason`, `trace.decision_path`, `trace.what_would_change`, `trace.why_not_flagged`, `result.stage_errors` |
| Evidence: kind of fraud, keywords found ×n | `result.findings[].criterion`, `trace.keyword_hits[].term` |
| Reliability: call quality, transcript certainty (words + %; the 70 % / 40 % cut-offs are a display choice) | `analysis.audio_quality.call_score`, `trace.confidence_breakdown.components.asr` |

A cleared call shows its top finding's passages as "below the review threshold" (demo moment 3).

**Below the panels:** "All calls" table, folded: filters by decision, status, criterion, variant, "has stage errors"; sort by
risk / confidence / updated (`calls[].confidence`, `calls[].variant`). **Header:** upload button and drop anywhere on the page (`POST /api/calls`).

- **Loading:** skeleton rows on the left, skeleton blocks in the panel. **Empty:** "No calls yet. Drop .wav files on this page or run `./run.sh <folder>`."
- **Error:** the list request failed → banner with retry, last good data kept and marked stale. A missing transcript, trace or
  analysis (404) makes only its part say "not available"; a call whose ASR failed shows its stage error instead.

## 2. Processing view

Opened from a processing row, or automatically after an upload. It shows a live stage timeline for one call.

| Element | Fed by |
|---|---|
| Stage list, in pipeline order (asr → diarize → keywords → extract → validate → rules → confidence → decide → narrate → snippets → analysis → trigger) | `schemas.STAGES`; stages that are not run stay grey |
| State per stage: waiting / running (live elapsed timer) / done / failed | `event.event` (`stage_started`, `stage_finished`, `stage_failed`) for `event.stage` |
| Stage duration | `event.elapsed_s` |
| "from cache" tag (shows that re-runs are instant) | `event.cached` |
| Failure message (red, under the stage) | `event.message` on `stage_failed` |
| Final decision; button "Open call" | `event.decision` on `job_finished` |
| Event log (collapsible, raw) | `event.seq`, `event.ts`, `event.message` |

- **Loading:** stage list with every stage waiting. Shown while the SSE connection opens.
- **Empty:** the call finished before the view opened. The API replays past events, so the timeline
  fills in at once. With no events at all: "No processing history for this call."
- **Error:** the SSE connection dropped → "Reconnecting…". The browser resumes with `Last-Event-ID`.
  After 3 failures: a banner and a manual refresh button. A failed stage is not a page error: the
  timeline continues and the call ends as `review`.

## 3. Call dashboard

The header is shared by all tabs. It shows the call ID, the decision badge (`result.decision`), the risk (`result.risk_score`),
the confidence (`result.confidence`, "n/a" when null) and a stage error banner listing
`result.stage_errors[].stage` and `result.stage_errors[].message`.
The tab is chosen by URL (`/calls/{id}?tab=evidence`).

- **Loading:** a header skeleton plus a skeleton for the active tab.
- **Error:** 404 → "Unknown call". Any other failure → error card with retry.
- **Still processing:** the API answers 202 → the dashboard shows the processing timeline inline (as
  in section 2).

### 3.1 Summary

| Element | Fed by |
|---|---|
| One-paragraph narrative | `result.narrative` |
| Findings list, sorted by risk, each with criterion, risk bar and reason | `result.findings[].criterion`, `result.findings[].risk`, `result.findings[].reason` |
| Findings below the review threshold, under a "considered, not flagged" divider | the same fields, `risk` < `trace.thresholds.review` |
| Number of evidence passages per finding; click opens Evidence | `result.findings[].evidence` |
| "Why not flagged" box (no_alert and review calls) | `trace.why_not_flagged` |
| "What would change this" box | `trace.what_would_change` |

- **Empty:** no findings → "No compliance-relevant passages found." The "why not flagged" box is still shown when it exists.
- **Error:** the trace fails to load → the summary shows without the two boxes, plus a small note.

### 3.2 Evidence

One card per evidence passage, grouped by finding.

| Element | Fed by |
|---|---|
| Criterion header | `result.findings[].criterion` |
| Quote in Swiss German, speaker chip (advisor / customer / unknown) | `result.findings[].evidence[].text`, `result.findings[].evidence[].speaker` |
| Time range, mm:ss | `result.findings[].evidence[].start_s`, `result.findings[].evidence[].end_s` |
| Snippet player (cut passage ±10 s; the passage itself highlighted on the mini waveform) | `result.findings[].evidence[].snippet_path` → `GET /api/calls/{id}/snippets/{basename}` |
| "Jump to transcript" (scrolls to and highlights the cited segments) | `result.findings[].evidence[].segment_ids` |
| "Show in audio analysis" (opens that tab with the window selected) | the matching `analysis.evidence_windows[].finding_index` and `analysis.evidence_windows[].evidence_index` |
| Counter-evidence cards, grey with a "counter" label | `result.findings[].counter_evidence[].text`, `result.findings[].counter_evidence[].start_s` |

- **Empty:** "This call has no evidence passages." (normal for no_alert.)
- **Snippet error:** the snippet returns 404 or does not play → the card shows "snippet unavailable"
  and keeps the quote and time. The card never disappears. In fixture mode, all snippets are 404.
- **Reference-mode results** (`start_s` null) show "no timestamp (reference transcript)" and no player.

### 3.3 Transcript

| Element | Fed by |
|---|---|
| Segment rows: time, speaker lane colour, text | `transcript.segments[].start_s`, `transcript.segments[].speaker`, `transcript.segments[].text` |
| Evidence highlight (colour per criterion) | segment ids from `result.findings[].evidence[].segment_ids` |
| Counter-evidence highlight (grey underline) | `result.findings[].counter_evidence[].segment_ids` |
| Keyword hits underlined, tooltip with family, term and score | `trace.keyword_hits[].segment_id`, `trace.keyword_hits[].matched_text`, `trace.keyword_hits[].family`, `trace.keyword_hits[].score` |
| Low ASR confidence: text dimmed, with a dotted underline | `transcript.segments[].avg_logprob`, `transcript.segments[].no_speech_prob` |
| Click a row to play from there (full call audio) | `GET /api/calls/{id}/audio`, seek to `start_s` |
| Search box, filter by speaker | client-side |

- **Empty:** the transcript has 0 segments → "No speech recognised." (This should be rare: such a call ends as review because of missing evidence.)
- **Not available (404):** "Transcript not available (ASR failed or not run)." Shown together with the
  stage error banner.

### 3.4 Audio analysis — visual standard

**Stacked lanes on one shared time axis.** All lanes have the same x-scale, from 0 to
`analysis.duration_s`, in seconds (`axes.x.unit` = `s` is enforced by the schema). Zoom and pan act on
all lanes together. Top to bottom:

| Lane | Fed by | Axis labels / units from |
|---|---|---|
| Waveform (min/max envelope per bucket) | `analysis.waveform_peaks.min`, `analysis.waveform_peaks.max`, `analysis.waveform_peaks.bucket_s` | `analysis.waveform_peaks.axes` |
| Mel spectrogram (heatmap, rows = mel bands) **with a dB colour bar** from `db_min` to `db_max` | `analysis.mel_spectrogram.db`, `analysis.mel_spectrogram.times_s`, `analysis.mel_spectrogram.freqs_hz`, `analysis.mel_spectrogram.db_min`, `analysis.mel_spectrogram.db_max` | `analysis.mel_spectrogram.axes.y.unit` (Hz, mel scale), `analysis.mel_spectrogram.axes.value.unit` (dB) |
| Speakers (one row per role, turn bars) | `analysis.turns.items[].start_s`, `analysis.turns.items[].end_s`, `analysis.turns.items[].speaker` | `analysis.turns.axes` |
| Speech activity (VAD bars) | `analysis.speech_activity.intervals[].start_s`, `analysis.speech_activity.intervals[].end_s` | `analysis.speech_activity.axes` |
| ASR confidence (per-segment step line of avg log-prob; no-speech probability as hatched overlay) | `analysis.asr_confidence.segments[].avg_logprob`, `analysis.asr_confidence.segments[].no_speech_prob` | `analysis.asr_confidence.axes.value.unit` |
| Audio quality (per-segment score 0–1, SNR in tooltip; call score as a badge on the lane title) | `analysis.audio_quality.segments[].score`, `analysis.audio_quality.segments[].snr_db`, `analysis.audio_quality.call_score` | `analysis.audio_quality.axes` |
| Optional lanes, collapsed by default: pitch (F0) and energy contours, speech rate | `analysis.pitch.values`, `analysis.energy.values`, `analysis.speech_rate.points[].value` | `analysis.pitch.axes.value.unit`, `analysis.energy.axes.value.unit`, `analysis.speech_rate.axes.value.unit` |

- **Shaded evidence windows.** Every lane shades the same windows, in the criterion's colour, from
  `analysis.evidence_windows[].start_s` to `analysis.evidence_windows[].end_s`, labelled with
  `analysis.evidence_windows[].criterion`. Clicking a window selects it in every lane and links back to
  the Evidence card.
- **Synchronised playhead.** One audio element (`GET /api/calls/{id}/audio`) drives a vertical line
  across all lanes. Clicking any lane seeks. Playback follows the playhead, and pressing play inside a selected window loops it.
- **Audio quality feeds the decision.** This lane is labelled "feeds confidence gate". No other lane
  influences the decision, and the UI says so in the tab subtitle.
- Pitch values that are `null` are gaps (unvoiced), not zero.

- **Loading:** lane skeletons in their final heights. The analysis JSON is about 100 KB per call, so it loads in one request.
- **Empty / not available (404):** "Audio analysis not computed for this call." The other tabs are unaffected.
- **Partial:** a null block hides its lane and shows a one-line placeholder. If
  `analysis.stage_errors[].stage` names it, the placeholder shows `analysis.stage_errors[].message` (see
  `call_MOCK_002.analysis.json`, where pitch failed).
- **Error:** the JSON fails to load or validate → error card. The audio player still works.

### 3.5 Reasoning

Read top to bottom: facts → rules → confidence → decision.

| Element | Fed by |
|---|---|
| Facts table: speaker, act, info type, quote, cited segments, flags (third party, secrecy cue) | `trace.facts[].speaker`, `trace.facts[].act`, `trace.facts[].info_type`, `trace.facts[].quote`, `trace.facts[].segment_ids`, `trace.facts[].recipient_third_party`, `trace.facts[].secrecy_cue` |
| Dropped facts (struck through, with reason) → these raise "missing evidence" | `trace.facts[].valid`, `trace.facts[].drop_reason` |
| Counter-evidence notes | `trace.facts[].counter_evidence` |
| Keyword hits table (family, term → matched text, segment, score) | `trace.keyword_hits[].family`, `trace.keyword_hits[].term`, `trace.keyword_hits[].matched_text` |
| Rules: one row per criterion, with a fired/not-fired chip, risk bar and threshold markers | `trace.rules[].criterion`, `trace.rules[].fired`, `trace.rules[].risk`, `trace.rules[].reason`, `trace.thresholds.alarm`, `trace.thresholds.review` |
| Rule inputs (links to facts and hits) | `trace.rules[].fact_ids`, `trace.rules[].keyword_hit_ids` |
| Confidence breakdown: component bars plus total against the gate line | `trace.confidence_breakdown.components`, `trace.confidence_breakdown.value`, `trace.confidence_breakdown.gate` |
| Decision path: the 4 priority steps of decide.py, with the step that fired highlighted | `trace.decision_path` (stage_error / missing_evidence / contradictory_evidence / low_confidence → review; alarm; review_band; no_alert) |
| "Why not flagged" / "what would change this" | `trace.why_not_flagged`, `trace.what_would_change` |

- **Empty / not available (404):** "No decision trace for this call (e.g. a baseline run)." Summary and
  Evidence still work from `result`.
- **Error:** error card with retry.

### 3.6 Audit

| Element | Fed by |
|---|---|
| Versions: ASR model, LLM, prompt, rules | `result.versions.asr`, `result.versions.llm`, `result.versions.prompt`, `result.versions.rules` |
| Analysis version | `analysis.versions.analysis` |
| Thresholds used for this decision | `trace.thresholds` |
| Per-stage timings (horizontal bars) | `trace.timings_s` |
| Stage errors (full text) | `result.stage_errors` |
| Raw JSON viewer for each document, plus a download button | the documents themselves |

- **Empty:** a version that is null is shown as "not run".
- **Error:** per document. One failed document never blanks the others.

### 3.7 Feedback: false alarm / missed / correct

A small bar in the call header, under the decision badge. The officer's verdicts feed the suggestions in Settings (§4.3). They
never change a decision by themselves.

| Element | Fed by |
|---|---|
| Buttons "False alarm", "Missed", "Correct". Only the sensible ones are enabled: a `no_alert` call offers Missed and Correct, an `alarm` offers False alarm and Correct, a `review` offers all three | `result.decision` |
| The current verdict, highlighted, with its note and time ("marked false alarm, 14:02") | `feedback[].verdict`, `feedback[].note`, `feedback[].ts` for this call |
| Optional one-line note (kept with the verdict) | `POST /api/feedback` body `note` |

- Clicking again with another verdict replaces it (the log is append-only; the latest verdict per call wins).
- **Loading:** the buttons render at once, disabled for the first moment. **Error:** the verdict is rolled back and the reason shown
  under the bar. **Empty:** no verdict yet, all valid buttons neutral.
- In fixtures mode verdicts are kept in the browser only (MOCK banner shown).

## 4. Settings

The config files are edited without code (CLAUDE.md). Shapes are in API.md. The files themselves arrive in a
later milestone, so no settings fixture exists yet.

### 4.1 Tuning (thresholds)
- Sliders for `alarm`, `review` and `confidence_gate`, with the constraint review < alarm (`GET/PUT /api/settings/thresholds`).
- **Live impact while dragging** (debounced `POST /api/settings/preview`, nothing is saved): counts of
  calls per decision before → after, and a list of calls whose decision would change.
- Each slider shows the matching precision/recall curve from `quality.threshold_curves[].points`, with the
  current value (`quality.threshold_curves[].current`) and the dragged value as markers.
- Save → PUT → server re-runs steps 6–8 from cache → SSE `job_finished` per changed call → Inbox
  badges update.

### 4.2 Configuration (keywords, rules)
- Keyword families: terms and Swiss German variants per family, add/remove, with a **live hit count**
  per term across all processed calls (from the preview response).
- Rules: one card per criterion (enabled, weights/conditions as defined in rules.yaml), each with a
  live count of calls where it would fire.
- Save keywords → re-run step 3, then 6–8. Save rules → re-run 6–8. The LLM is never re-run (extraction
  does not see keyword hits).

- **Loading:** form skeleton.
- **Empty:** a config file is missing → "Using built-in defaults", with read-only values.
- **Error:** PUT returns 422 → field-level messages from `detail`, and nothing is saved. A preview failure → impact panel shows "preview unavailable" and the form still works.

### 4.3 What-if impact and suggested changes

Shown beside both Tuning and Configuration. Whatever the officer drafts (thresholds, a keyword family or a rule switched off) is
simulated live with `POST /api/simulate`. Nothing is saved until "Save"/"Apply" is confirmed.

| Element | Fed by |
|---|---|
| Decision counts before → after | `simulation.counts.before`, `simulation.counts.after` |
| **Workload meter**: alarms + reviews per 100 calls, before → after, and the change | `simulation.workload.before.alarms_per_100`, `simulation.workload.before.reviews_per_100`, `simulation.workload.after.flagged_per_100`, `simulation.workload.delta_flagged_per_100` |
| **Flipped calls**: id (link to the call), before → after badges, up/down arrow, the reasons, which part of the draft caused it | `simulation.flipped[].call_id`, `simulation.flipped[].before`, `simulation.flipped[].after`, `simulation.flipped[].direction`, `simulation.flipped[].reasons`, `simulation.flipped[].attributed_to` |
| A flipped call that the officer labelled gets a chip with the verdict | `simulation.flipped[].feedback_verdict` |
| Warning row when the draft changes a call marked "correct" or moves a labelled call the wrong way | `simulation.feedback_check.violations` |
| "Fixes n of your flagged verdicts" | `simulation.feedback_check.fixed`, `simulation.feedback_check.fix_credit` |

**Suggested changes** (a card list; never applied on its own):

| Element | Fed by |
|---|---|
| Title ("Raise review threshold 0.40 → 0.55") and the plain-language rationale | `suggestions.suggestions[].title`, `suggestions.suggestions[].rationale` |
| Calls fixed / still flagged wrongly / other calls that would change | `suggestions.suggestions[].fixed`, `suggestions.suggestions[].not_fixed`, `suggestions.suggestions[].collateral_flips` |
| Simulated effect: decision counts and workload change | `suggestions.suggestions[].effect.counts`, `suggestions.suggestions[].effect.workload.delta_flagged_per_100` |
| Honesty line: how many verdicts it is fitted to, and that it is not validated on unseen calls | `suggestions.n_feedback`, `suggestions.counts_by_verdict`, `suggestions.caveat` |
| What to do next when the list is empty | `suggestions.reason` |
| Button **Preview** loads the patch into the draft above, so the impact panel shows it; button **Apply…** opens a confirm dialog that lists the exact change and the calls that would flip | `suggestions.suggestions[].patch` |

- Applying writes the config, re-runs steps 6-8 from cache and adds a line to the audit log (who/when, what changed, from which
  suggestion). A small audit list under the suggestions shows the last entries (`GET /api/audit`).
- A suggestion built for an older config version is refused with 409; the UI reloads the list.
- **Loading:** skeleton cards. **Empty:** the `reason` text plus "Mark calls as false alarm, missed or correct on their call page".
  **Error:** card with retry; the sliders keep working. Fixtures mode: the list is MOCK sample data and says it is not recomputed
  from the officer's clicks; the impact numbers for a hand-made draft are a client-side approximation, labelled as such.

## 5. Quality lab

Picks a report (`GET /api/quality`) and shows one `QualityReport`. The header shows run, system,
mode, split, n and the bootstrap settings (`quality.run_id`, `quality.split`, `quality.mode`,
`quality.overall.n`, `quality.bootstrap.n_resamples`, `quality.bootstrap.ci_level`,
`quality.bootstrap.unit`). Warnings are shown verbatim (`quality.warnings`).

| Element | Fed by |
|---|---|
| **Three convention cards side by side** (never one without the others): strict alarm P/R/F1, escalation P/R/F1, 3-class macro F1 and accuracy, each with its CI as an error bar | `quality.overall.strict_alarm.precision.value`, `quality.overall.strict_alarm.precision.ci_low`, `quality.overall.strict_alarm.precision.ci_high`, `quality.overall.escalation.recall.value`, `quality.overall.three_class.macro_f1.value` |
| Confusion matrix 3×3 (rows = gold, columns = predicted) | `quality.overall.three_class.confusion` |
| Threshold curves: P and R against the threshold, with the current value marked | `quality.threshold_curves[].param`, `quality.threshold_curves[].convention`, `quality.threshold_curves[].points[].threshold`, `quality.threshold_curves[].points[].precision`, `quality.threshold_curves[].points[].recall` |
| Per-Stufe bars and clean vs noisy bars (with CIs) | `quality.breakdowns.stufe`, `quality.breakdowns.variant` |
| Reliability diagram (confidence against accuracy per bin, bar width = n) plus ECE with its CI | `quality.reliability.bins[].mean_confidence`, `quality.reliability.bins[].accuracy`, `quality.reliability.bins[].n`, `quality.reliability.ece.value` |
| Ablations: grouped bars for keyword-only / LLM-only / combined × reference / ASR transcript | `quality.ablations[].name`, `quality.ablations[].transcript`, `quality.ablations[].conventions.escalation.recall.value` |
| WER against downstream escalation recall (one point per WER bin, n as label) | `quality.wer_vs_recall[].wer_lo`, `quality.wer_vs_recall[].wer_hi`, `quality.wer_vs_recall[].escalation_recall.value`, `quality.wer_vs_recall[].n` |
| Per-stage latency (p50 bar, p95 whisker) | `quality.latency[].stage`, `quality.latency[].p50_s`, `quality.latency[].p95_s` |
| Evidence validity rate, with pass rate per check and the skipped checks listed | `quality.evidence_validity.item_validity_rate`, `quality.evidence_validity.per_check_pass_rate`, `quality.evidence_validity.checks_skipped` |

Rules: a null `value` is shown as "n/a (undefined)", never as 0. Every metric shows its CI. The text says "n is small"
when `quality.overall.n` < 30. Test-split reports carry a "locked test set — final report only" tag.

- **Loading:** card skeletons.
- **Empty:** no reports → "No evaluation run yet. Run `python -m pipeline.evaluate --pred …`."
  An empty list (`quality.ablations`, `quality.wer_vs_recall`, `quality.latency`) hides that panel with the note "not computed for
  this run".
- **Error:** the report fails to load → error card. One broken panel never blanks the page.

---

## 6. Demo path: the 4 jury moments

All four run on the laptop UI against the real API (SSH tunnel to the GPU VM). Before the demo, each
step is rehearsed on fixtures. Times below are targets.

1. **Audio → alert with snippet (≈90 s).** Overview → drag a held-out alarm .wav onto the page → the
   Processing view opens and stages tick through live (`event.stage`, `event.elapsed_s`) →
   `job_finished` with `event.decision` = alarm → "Open call" → Summary narrative
   (`result.narrative`) → Evidence tab → press play on the snippet
   (`result.findings[].evidence[].snippet_path`). The quote and the timestamp are visible, and the audio
   says the quoted words. Optional: Audio analysis tab, where the shaded window lines up with the
   spectrogram while the playhead runs.
2. **Threshold / keyword change (≈60 s).** Settings → Tuning → drag `alarm` from 0.70 to 0.85 → the
   impact panel shows which calls would move from alarm to review → Save → back to the Overview, where
   the badges change within seconds. Nothing is re-transcribed: the Processing view shows "from cache"
   (`event.cached`). Then Configuration → add a Swiss German variant to a keyword family → the hit
   count rises live. Restore the original values afterwards.
3. **Harmless call with a keyword (≈45 s).** Open a no_alert call whose transcript contains a flagged
   term (fixture: `call_MOCK_002`, "Passwort" in a password reset) → Transcript tab shows the keyword
   underlined (`trace.keyword_hits[].matched_text`) → Summary shows "why not flagged"
   (`trace.why_not_flagged`) → Reasoning shows the rule not fired (`trace.rules[].fired`) because the
   facts are a request plus a refusal, not a disclosure.
4. **Test-set metrics (≈60 s).** Quality lab → select the test-split report → the three convention
   cards with CIs → confusion matrix → clean vs noisy bars → ablation (keyword-only vs combined shows
   why the LLM step is worth it) → evidence validity rate. Say out loud: n is small, so look at the
   CIs. The test split was never tuned on.

Fallback if the GPU is down: start the API in fixture mode. The UI shows the MOCK banner, and we say so.

<!-- stretch:start -->
## 7. STRETCH: feature maps (nothing depends on this)

`analysis.feature_maps` is null unless `--feature-maps` was run, and `analysis.feature_maps_status`
is then `not_computed`. **No UI element may depend on it**: no layout, no tab and no demo step. If
present (`feature_maps_status` = ok), the Audio analysis tab may show an extra collapsed section,
"Model internals". It gives one small heatmap per layer (`analysis.feature_maps[].layers[].values`,
in [-1, 1], with a diverging colour map centred on 0), aligned to its evidence window
(`analysis.feature_maps[].start_s` and `analysis.feature_maps[].end_s`), with labels from
`analysis.feature_maps[].layers[].axes`. The same applies to `analysis.audio_quality_cnn`.
<!-- stretch:end -->

## 8. Open points

- The organizers' metric convention is unconfirmed, so all three conventions are always shown.
- The Stufe → expected decision mapping in the MOCK quality report is invented.
- The settings file shapes (keywords.json, rules.yaml) are proposals until the config milestone. There is no fixture for them.
- No audio in fixtures (`*.wav` is gitignored). Snippet and audio endpoints return 404 in fixture mode.
