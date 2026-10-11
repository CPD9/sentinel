# Language routing map (experimental, display only)

**What it is for:** sending a call to the right language model and the right reviewer. A Swiss bank gets calls in
German (Swiss German), French and Italian; SENTINEL's ASR and judge are tuned on Swiss German, so a French or Italian
call should be routed to a model and a compliance officer who handle that language. The map in the call page's
**Audio analysis** tab shows, per speaker (advisor / customer), how likely each Swiss language region is.

**What it is not:** a statement about where a person lives or comes from. The map shades regions by probability,
never shows a pin, an address or a municipality, and **never feeds the decision** (`pipeline/` does not import it;
`tests/test_dialect.py` checks that, and that the decision files are byte-identical after a run).

Label in the UI: *Experimental · probability, not identity · not used in the decision*.

## Privacy (nDSG)

Inferring someone's language or dialect from their voice is processing of **personal data** under the Swiss Federal
Act on Data Protection (nDSG / revDSG, in force since 1 Sept 2023), and a dialect can hint at origin. So:

- purpose limitation: routing only (model choice, reviewer choice); no profiling, no storage in a customer record;
- data minimisation: region-level probabilities only (3 language regions on the map), no finer location;
- storage limitation: the files live in the run folder (`sentinel-runs/dialect/<call_id>.json`) next to the run's
  other outputs and go with it; nothing is sent anywhere (self-hosted Whisper on our own GPU);
- transparency: the method, the measured accuracy and the limits below are shown next to the map.

A bank deploying this would document it in its processing register and its data protection impact assessment.

## Method

1. **Speaker turns** come from the display-only speaker roles (`sentinel-runs/speakers/<call_id>.json`,
   pyannote 3.1 + Apertus, 87.3 % of words with the right role; see [RESULTS.md](RESULTS.md)).
2. **Language ID** ([`scripts/pod_langid.py`](../scripts/pod_langid.py), on the GPU Pod): each speaker's turns of
   at least 1 s are concatenated and cut into windows of at most 30 s; faster-whisper large-v3-turbo's
   `detect_language` gives a distribution over Whisper's ~100 languages per window; windows are averaged weighted by
   their speech seconds and collapsed to de / fr / it / en / other.
   **Whisper has no Romansh**, so Romansh speech can never be recognised as such (the UI says "not supported").
3. **Regions** ([`scripts/dialect_map.py`](../scripts/dialect_map.py), [`config/dialect_regions.json`](../config/dialect_regions.json)):
   de → German-speaking, fr → French-speaking, it → Italian-speaking Switzerland, at canton level by majority
   language (BFS). BE, FR, VS and GR are bilingual / trilingual and drawn hatched: their language border runs inside
   the canton. Confidence: *high* with ≥ 60 s of speech and a top language ≥ 0.9, *medium* with ≥ 15 s and ≥ 0.6,
   else *low*.
4. **Map** ([`web/components/audio/swiss-map.tsx`](../web/components/audio/swiss-map.tsx)): static, pre-projected
   canton paths generated once by [`scripts/build_swiss_map.py`](../scripts/build_swiss_map.py) from swiss-maps
   4.7.0 (`2026/ch-combined.json`, code BSD-3-Clause). Geodata: **Bundesamt für Statistik (BFS), GEOSTAT**,
   generalised administrative boundaries, based on swisstopo. No new npm package.

## Validation (measured)

*Filled in from `artifacts/metrics/langid_validation.json` after the Pod run.*

## Dialect (research only)

*Filled in from `artifacts/metrics/dialect_swissdial.json` after the Pod run.*

**Data:** SwissDial 1.1 as used in the ASR bake-off: 8 dialects (AG, BE, BS, GR, LU, SG, VS, ZH) × 20 parallel
sentences, **one speaker per dialect**. The case calls carry no canton or dialect tag, and **the case voices are
synthetic (TTS)**: they are not real Swiss German speakers, so any dialect estimate on them is not meaningful.

**The confound:** with one speaker per dialect, "dialect" and "voice" are the same label. Holding out sentences
(the same sentence is never in training and test) removes the content shortcut, but not the speaker shortcut: the
classifier can be right by recognising the voice. It **cannot be validated speaker-independently** with this data.

**Decision (Peter, 11 Oct 2026):** the map shows language ID only, with "dialect: not determined". The classifier's
top 3 appears only in a collapsed *Research: dialect estimate* panel, only if its cross-validated accuracy is above
chance (CI lower bound > 1/8), with the warning above.

## Limitations

- Language ID tells the language, not the region: a French speaker in Zurich lands in "French-speaking".
- Short turns are dropped (< 1 s); a speaker with little speech gets *low* confidence or no estimate.
- Speaker roles are imperfect (87.3 % of words right); a mis-assigned turn mixes the two speakers' estimates.
- Canton-level language regions are an approximation; bilingual cantons are hatched rather than split.
- Romansh is not detectable with Whisper.
