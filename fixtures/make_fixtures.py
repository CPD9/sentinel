"""Generate the MOCK fixtures in fixtures/ (deterministic, stdlib only).

    .venv/bin/python fixtures/make_fixtures.py [--out fixtures]

Everything here is INVENTED for frontend/API development: no model ran, no case data was read.
Dialogues are made up; quality numbers come from a made-up per-call table run through
pipeline.evaluate's own metric functions, so they are internally consistent but mean nothing.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline.evaluate import binary, three_class  # noqa: E402
from pipeline.schemas import (  # noqa: E402
    DECISIONS, AnalysisArtifact, CallListItem, CallResult, DecisionTrace, ProcessingEvent, QualityReport,
    Transcript,
)

MOCK = "MOCK - invented data for frontend/API development, not model output"
VERSIONS = {"asr": "MOCK", "llm": "MOCK", "prompt": "MOCK", "rules": "MOCK"}
THRESHOLDS = {"alarm": 0.7, "review": 0.4, "confidence_gate": 0.5}
SAMPLE_RATE = 16000


def r3(x: float) -> float:
    return round(x, 3)


def axis(label: str, unit: str) -> dict:
    return {"label": label, "unit": unit}


TIME = axis("time", "s")

# --------------------------------------------------------------------------- dialogues (invented)
# (id, speaker, start_s, end_s, text, avg_logprob, no_speech_prob)

CALL_1 = ("call_MOCK_001", 138.6, [
    ("s001", "advisor", 0.8, 6.2, "Grüezi, Bank Lindenhof, Sie spräched mit de Frau Keller. Wie chan ich Ihne hälfe?", -0.21, 0.02),
    ("s002", "customer", 6.9, 14.5, "Grüezi. Ich chume nöd i mis E-Banking ine, es seit immer, d Aamäldig seig gsperrt.", -0.34, 0.03),
    ("s003", "advisor", 15.2, 24.0, "Das tuet mer leid. Mir fröged normalerwiis nie nach Passwörter, aber ich lueg emal, was ich mache cha.", -0.27, 0.02),
    ("s004", "customer", 24.8, 31.3, "Danke. Ich mues hüt no e Rechnig zahle, das isch dringend.", -0.30, 0.04),
    ("s005", "advisor", 32.0, 41.6, "Verstande. Chönd Sie mir zerscht Ihres Geburtsdatum und d Vertragsnummer säge?", -0.25, 0.02),
    ("s006", "customer", 42.3, 51.9, "Ja, de vierzähti März, und d Vertragsnummer isch drü sibe vier nüün.", -0.41, 0.05),
    ("s007", "advisor", 52.5, 60.2, "Merci, das stimmt. Ich gseh, dass d Aamäldig nach drü Fählversüech gsperrt worde isch.", -0.22, 0.02),
    ("s008", "customer", 61.0, 67.4, "Genau, ich ha mi glaub vertippt.", -0.36, 0.06),
    ("s009", "advisor", 68.1, 79.5, "Ich chan das entsperre. Dänn mues ich aber teste, öb s Passwort funktioniert.", -0.24, 0.02),
    ("s010", "customer", 80.2, 86.0, "Okay, was bruuched Sie vo mir?", -0.29, 0.03),
    ("s011", "advisor", 92.3, 97.8, "Säged Sie mir eifach Ihres aktuelle Passwort, dänn probier ich s grad sälber us.", -0.31, 0.03),
    ("s012", "customer", 98.6, 104.1, "Also, es isch Sunneblueme, grossgschribe, und dänn zwei drü.", -0.48, 0.07),
    ("s013", "advisor", 104.8, 112.0, "Perfekt, ich ha s notiert. Das bliibt under üs.", -0.26, 0.03),
    ("s014", "customer", 112.9, 118.5, "Guet, merci vilmal.", -0.33, 0.05),
    ("s015", "advisor", 119.2, 131.0, "Gärn gscheh. Ich mälde mich, sobald s wieder gaht. En schöne Tag no.", -0.23, 0.02),
    ("s016", "customer", 131.6, 134.2, "Ihne au, adieu.", -0.40, 0.08),
])

CALL_2 = ("call_MOCK_002", 96.4, [
    ("s001", "advisor", 0.6, 5.9, "Grüezi, Bank Lindenhof, Brunner am Apparat.", -0.19, 0.02),
    ("s002", "customer", 6.5, 15.8, "Grüezi. Ich ha mis Passwort fürs E-Banking vergässe. Chönd Sie mir hälfe?", -0.28, 0.03),
    ("s003", "advisor", 16.4, 27.9, "Sicher. Bitte säged Sie mir Ihres Passwort uf kei Fall, au nöd s alte. Ich schicke Ihne en Link zum Zruggsetze.", -0.24, 0.02),
    ("s004", "customer", 28.6, 33.0, "Ah guet, das isch eifacher.", -0.35, 0.05),
    ("s005", "advisor", 33.7, 45.2, "De Link chunnt per SMS uf Ihri hinterlegti Nummer. Dänn wähled Sie es neus Passwort.", -0.22, 0.02),
    ("s006", "customer", 46.0, 52.4, "Isch scho do. Merci.", -0.31, 0.04),
    ("s007", "advisor", 53.1, 66.8, "Wänn Sie wänd, chan ich Ihne no zeige, wie Sie d Zwei-Faktor-Bestätigung iirichted.", -0.26, 0.03),
    ("s008", "customer", 67.5, 79.0, "Nei danke, das han ich scho. Das isch alles gsi.", -0.33, 0.05),
    ("s009", "advisor", 79.8, 88.6, "Super. Dänn wünsch ich Ihne en schöne Tag. Adieu.", -0.21, 0.02),
])


def transcript(call: tuple) -> dict:
    call_id, duration, segs = call
    return Transcript.from_dict({
        "call_id": call_id, "mode": "asr", "asr_model": "MOCK", "duration_s": duration, "is_mock": True,
        "notes": [MOCK],
        "segments": [{"id": i, "speaker": sp, "start_s": s, "end_s": e, "text": t, "avg_logprob": lp,
                      "no_speech_prob": ns} for i, sp, s, e, t, lp, ns in segs],
    }).to_dict()


def ev(call: tuple, seg_id: str, text: str | None = None, snippet: str | None = None) -> dict:
    _, _, segs = call
    _, sp, s, e, t, _, _ = next(x for x in segs if x[0] == seg_id)
    return {"segment_ids": [seg_id], "speaker": sp, "text": text or t, "start_s": s, "end_s": e,
            "snippet_path": snippet}


# --------------------------------------------------------------------------- results + traces

def call_1() -> tuple[dict, dict]:
    snip = "out/snippets/call_MOCK_001/f0_e{}.wav"
    result = CallResult.from_dict({
        "call_id": "call_MOCK_001", "decision": "alarm", "risk_score": 0.91, "confidence": 0.78,
        "findings": [
            {"criterion": "credential_sharing", "risk": 0.91,
             "reason": "[MOCK] The advisor asks for the customer's current e-banking password and the "
                       "customer reads it out; the advisor then says it stays between them.",
             "evidence": [
                 ev(CALL_1, "s011", "Säged Sie mir eifach Ihres aktuelle Passwort", snip.format(0)),
                 ev(CALL_1, "s012", "es isch Sunneblueme, grossgschribe, und dänn zwei drü", snip.format(1)),
                 ev(CALL_1, "s013", "Das bliibt under üs.", snip.format(2)),
             ],
             "counter_evidence": [ev(CALL_1, "s003", "Mir fröged normalerwiis nie nach Passwörter")]},
            {"criterion": "payment_card_data", "risk": 0.08,
             "reason": "[MOCK] A contract number is read out for identification; it is not card data.",
             "evidence": [ev(CALL_1, "s006", "d Vertragsnummer isch drü sibe vier nüün")],
             "counter_evidence": []},
        ],
        "narrative": "[MOCK] Alarm: credential sharing. At 01:32 the advisor asks for the current password "
                     "(\"Säged Sie mir eifach Ihres aktuelle Passwort\"), at 01:38 the customer discloses it, "
                     "and at 01:44 the advisor adds \"Das bliibt under üs\". The advisor's earlier remark "
                     "that the bank never asks for passwords (00:15) was considered as counter-evidence; it "
                     "makes the request more, not less, irregular.",
        "stage_errors": [], "versions": VERSIONS,
    }).to_dict()
    trace = DecisionTrace.from_dict({
        "call_id": "call_MOCK_001", "decision": "alarm", "decision_path": "alarm",
        "risk_score": 0.91, "confidence": 0.78, "thresholds": THRESHOLDS,
        "facts": [
            {"fact_id": "F1", "speaker": "advisor", "act": "request", "info_type": "credentials",
             "segment_ids": ["s011"], "quote": "Säged Sie mir eifach Ihres aktuelle Passwort",
             "recipient_third_party": False, "secrecy_cue": False},
            {"fact_id": "F2", "speaker": "customer", "act": "disclose", "info_type": "credentials",
             "segment_ids": ["s012"], "quote": "es isch Sunneblueme, grossgschribe, und dänn zwei drü",
             "recipient_third_party": False, "secrecy_cue": False},
            {"fact_id": "F3", "speaker": "advisor", "act": "other", "info_type": "credentials",
             "segment_ids": ["s013"], "quote": "Das bliibt under üs.", "secrecy_cue": True},
            {"fact_id": "F4", "speaker": "advisor", "act": "warn", "info_type": "credentials",
             "segment_ids": ["s003"], "quote": "Mir fröged normalerwiis nie nach Passwörter",
             "counter_evidence": "Advisor states the bank never asks for passwords."},
            {"fact_id": "F5", "speaker": "customer", "act": "disclose", "info_type": "client_data",
             "segment_ids": ["s007"], "quote": "d Vertragsnummer isch drü sibe vier nüün", "valid": False,
             "drop_reason": "quote does not match cited segment s007 (best match s006); speaker mismatch"},
        ],
        "keyword_hits": [
            {"hit_id": "H1", "family": "access", "term": "Passwort", "matched_text": "Passwörter",
             "segment_id": "s003", "score": 0.93},
            {"hit_id": "H2", "family": "access", "term": "Passwort", "matched_text": "Passwort",
             "segment_id": "s009", "score": 1.0},
            {"hit_id": "H3", "family": "access", "term": "Passwort", "matched_text": "Passwort",
             "segment_id": "s011", "score": 1.0},
            {"hit_id": "H4", "family": "numbers", "term": "Nummer", "matched_text": "Vertragsnummer",
             "segment_id": "s006", "score": 0.82},
        ],
        "rules": [
            {"criterion": "credential_sharing", "risk": 0.91, "fired": True,
             "reason": "[MOCK] request (F1) + disclosure (F2) of an active credential, secrecy cue (F3)",
             "fact_ids": ["F1", "F2", "F3", "F4"], "keyword_hit_ids": ["H1", "H2", "H3"]},
            {"criterion": "payment_card_data", "risk": 0.08, "fired": False,
             "reason": "[MOCK] number read out is a contract number used for identification",
             "fact_ids": [], "keyword_hit_ids": ["H4"]},
            {"criterion": "insider_trading", "risk": 0.0, "fired": False, "reason": "[MOCK] no trade facts"},
            {"criterion": "third_party_disclosure", "risk": 0.0, "fired": False, "reason": "[MOCK] no third party"},
            {"criterion": "documentation_concealment", "risk": 0.05, "fired": False,
             "reason": "[MOCK] secrecy cue (F3) concerns the password, not a documented fact", "fact_ids": ["F3"]},
            {"criterion": "control_evasion", "risk": 0.0, "fired": False, "reason": "[MOCK] no movements"},
        ],
        "confidence_breakdown": {"value": 0.78, "gate": 0.5, "components": {
            "asr": 0.81, "threshold_proximity": 0.93, "conflicts": 0.7, "missing_evidence": 0.9,
            "audio_quality": 0.86}},
        "why_not_flagged": None,
        "what_would_change": "[MOCK] Without the customer's disclosure (F2) the risk would drop to ~0.55 "
                             "(review band): a request alone is reviewed, not alarmed.",
        "timings_s": {"asr": 34.8, "diarize": 6.1, "keywords": 0.02, "extract": 11.4, "validate": 0.03,
                      "rules": 0.01, "confidence": 0.01, "decide": 0.0, "narrate": 3.9, "snippets": 0.6},
        "versions": VERSIONS, "is_mock": True,
    }).to_dict()
    return result, trace


def call_2() -> tuple[dict, dict]:
    result = CallResult.from_dict({
        "call_id": "call_MOCK_002", "decision": "no_alert", "risk_score": 0.12, "confidence": 0.84,
        "findings": [
            {"criterion": "credential_sharing", "risk": 0.12,
             "reason": "[MOCK] 'Passwort' is mentioned, but no secret is disclosed and the advisor "
                       "explicitly refuses to hear it; a reset link is sent instead.",
             "evidence": [ev(CALL_2, "s002", "Ich ha mis Passwort fürs E-Banking vergässe")],
             "counter_evidence": [ev(CALL_2, "s003", "Bitte säged Sie mir Ihres Passwort uf kei Fall")]},
        ],
        "narrative": "[MOCK] No alert. The keyword 'Passwort' occurs three times, but only in a password "
                     "reset: the customer never reveals a secret and the advisor warns against doing so "
                     "(00:16).",
        "stage_errors": [], "versions": VERSIONS,
    }).to_dict()
    trace = DecisionTrace.from_dict({
        "call_id": "call_MOCK_002", "decision": "no_alert", "decision_path": "no_alert",
        "risk_score": 0.12, "confidence": 0.84, "thresholds": THRESHOLDS,
        "facts": [
            {"fact_id": "F1", "speaker": "customer", "act": "request", "info_type": "credentials",
             "segment_ids": ["s002"], "quote": "Ich ha mis Passwort fürs E-Banking vergässe"},
            {"fact_id": "F2", "speaker": "advisor", "act": "refuse", "info_type": "credentials",
             "segment_ids": ["s003"], "quote": "Bitte säged Sie mir Ihres Passwort uf kei Fall",
             "counter_evidence": "Advisor refuses to receive the password."},
        ],
        "keyword_hits": [
            {"hit_id": "H1", "family": "access", "term": "Passwort", "matched_text": "Passwort",
             "segment_id": "s002", "score": 1.0},
            {"hit_id": "H2", "family": "access", "term": "Passwort", "matched_text": "Passwort",
             "segment_id": "s003", "score": 1.0},
            {"hit_id": "H3", "family": "access", "term": "Passwort", "matched_text": "Passwort",
             "segment_id": "s005", "score": 1.0},
        ],
        "rules": [
            {"criterion": "credential_sharing", "risk": 0.12, "fired": False,
             "reason": "[MOCK] keyword hits but no disclose/request-to-disclose fact; refusal F2",
             "fact_ids": ["F1", "F2"], "keyword_hit_ids": ["H1", "H2", "H3"]},
        ],
        "confidence_breakdown": {"value": 0.84, "gate": 0.5, "components": {
            "asr": 0.86, "threshold_proximity": 0.9, "conflicts": 1.0, "missing_evidence": 1.0,
            "audio_quality": 0.71}},
        "why_not_flagged": "[MOCK] 'Passwort' appears 3x (keyword family access), but the extracted facts "
                           "are a reset request (F1) and an explicit refusal by the advisor (F2). "
                           "credential_sharing needs a disclosed or requested active secret.",
        "what_would_change": "[MOCK] If the customer had read out the old password, or the advisor had "
                             "asked for it, credential_sharing would exceed the alarm threshold (0.7).",
        "timings_s": {"asr": 22.1, "diarize": 4.0, "keywords": 0.01, "extract": 7.2, "validate": 0.02,
                      "rules": 0.01, "confidence": 0.01, "decide": 0.0, "narrate": 2.8, "snippets": 0.3},
        "versions": VERSIONS, "is_mock": True,
    }).to_dict()
    return result, trace


def call_4() -> dict:
    return CallResult.from_dict({
        "call_id": "call_MOCK_004", "decision": "review", "risk_score": 0.0, "confidence": None,
        "findings": [],
        "narrative": "[MOCK] ASR failed, so the call could not be assessed and was routed to review.",
        "stage_errors": [{"stage": "asr", "message": "[MOCK] CUDA out of memory while loading the ASR model"}],
        "versions": {**VERSIONS, "llm": None, "prompt": None},
    }).to_dict()


# --------------------------------------------------------------------------- analysis artifact

def analysis(call: tuple, result: dict, seed: int, failed: tuple[str, ...] = ()) -> dict:
    call_id, dur, segs = call
    rng = random.Random(seed)
    speaking = [(s, e, sp) for _, sp, s, e, *_ in segs]

    def speaker_at(t: float) -> str | None:
        return next((sp for s, e, sp in speaking if s <= t < e), None)

    bucket = 0.25
    n_buckets = math.ceil(dur / bucket)
    mins, maxs = [], []
    for i in range(n_buckets):
        sp = speaker_at((i + 0.5) * bucket)
        amp = (0.35 + 0.3 * abs(math.sin(i * 0.7))) * (0.6 + 0.4 * rng.random()) if sp else 0.02 + 0.02 * rng.random()
        mins.append(r3(-amp * (0.8 + 0.2 * rng.random())))
        maxs.append(r3(amp))

    times = [r3(0.25 + 0.5 * i) for i in range(int((dur - 0.25) / 0.5) + 1)]
    mel = lambda m: 700 * (10 ** (m / 2595) - 1)  # noqa: E731
    top = 2595 * math.log10(1 + 8000 / 700)
    freqs = [round(mel(top * (k + 0.5) / 40), 1) for k in range(40)]
    db = []
    for k, f in enumerate(freqs):
        row = []
        for t in times:
            sp = speaker_at(t)
            f0 = 210 if sp == "advisor" else 120
            if sp:
                level = -25 - 18 * (k / 40) + 8 * math.exp(-((f % (f0 * 3)) / (f0 * 1.5)) ** 2) + 4 * rng.random()
            else:
                level = -72 + 6 * rng.random()
            row.append(round(max(-80.0, min(0.0, level)), 1))
        db.append(row)

    hop = 0.2
    ctimes = [r3(hop * i) for i in range(int(dur / hop))]
    pitch = []
    for t in ctimes:
        sp = speaker_at(t)
        voiced = sp is not None and rng.random() > 0.25
        base = 205 if sp == "advisor" else 118
        pitch.append(round(base + 25 * math.sin(t * 1.3) + 8 * rng.random(), 1) if voiced else None)
    energy = [round(-28 + 6 * math.sin(t * 2.1) + 3 * rng.random(), 1) if speaker_at(t) else
              round(-62 + 4 * rng.random(), 1) for t in ctimes]

    turns = []
    for sid, sp, s, e, *_ in segs:
        if turns and turns[-1]["speaker"] == sp:
            turns[-1].update(end_s=e, segment_ids=turns[-1]["segment_ids"] + [sid])
        else:
            turns.append({"start_s": s, "end_s": e, "speaker": sp, "segment_ids": [sid]})

    quality = []
    for sid, _, s, e, *_ in segs:
        snr = round(14 + 14 * rng.random() - (6 if seed % 2 == 0 else 0), 1)
        quality.append({"segment_id": sid, "start_s": s, "end_s": e, "snr_db": snr,
                        "score": r3(max(0.0, min(1.0, (snr - 5) / 25)))})
    call_snr = round(sum(q["snr_db"] for q in quality) / len(quality), 1)

    windows = [{"start_s": e["start_s"], "end_s": e["end_s"], "criterion": f["criterion"],
                "finding_index": fi, "evidence_index": ei}
               for fi, f in enumerate(result["findings"]) for ei, e in enumerate(f["evidence"])]

    d = {
        "call_id": call_id, "duration_s": dur, "sample_rate": SAMPLE_RATE, "evidence_windows": windows,
        "waveform_peaks": {"bucket_s": bucket, "min": mins, "max": maxs,
                           "axes": {"x": TIME, "y": axis("amplitude", "normalised (-1..1)")}},
        "mel_spectrogram": {"times_s": times, "freqs_hz": freqs, "db": db, "db_min": -80.0, "db_max": 0.0,
                            "png_path": None,
                            "axes": {"x": TIME, "y": axis("frequency", "Hz (mel scale)"),
                                     "value": axis("level", "dB")}},
        "speech_activity": {"intervals": [{"start_s": max(0.0, r3(s - 0.1)), "end_s": min(dur, r3(e + 0.1))}
                                          for _, _, s, e, *_ in segs], "axes": {"x": TIME}},
        "turns": {"items": turns, "axes": {"x": TIME}},
        "speech_rate": {"points": [{"start_s": s, "end_s": e, "speaker": sp,
                                    "value": round(len(t.split()) / (e - s) * 60, 1)}
                                   for _, sp, s, e, t, *_ in segs],
                        "axes": {"x": TIME, "value": axis("speech rate", "words/min")}},
        "pitch": {"times_s": ctimes, "values": pitch, "axes": {"x": TIME, "value": axis("pitch (F0)", "Hz")}},
        "energy": {"times_s": ctimes, "values": energy, "axes": {"x": TIME, "value": axis("energy", "dB")}},
        "audio_quality": {"call_snr_db": call_snr, "call_score": r3(max(0.0, min(1.0, (call_snr - 5) / 25))),
                          "segments": quality,
                          "axes": {"x": TIME, "value": axis("audio quality", "score 0-1")}},
        "asr_confidence": {"segments": [{"segment_id": sid, "start_s": s, "end_s": e, "avg_logprob": lp,
                                         "no_speech_prob": ns} for sid, _, s, e, _, lp, ns in segs],
                           "axes": {"x": TIME, "value": axis("ASR avg log-prob", "nats/token")}},
        "feature_maps": None, "feature_maps_status": "not_computed", "audio_quality_cnn": None,
        "stage_errors": [], "versions": {"analysis": "MOCK", "asr": "MOCK"}, "is_mock": True,
    }
    for block in failed:
        d[block] = None
        d["stage_errors"].append({"stage": f"analysis.{block}", "message": f"[MOCK] {block} extraction failed"})
    return AnalysisArtifact.from_dict(d).to_dict()


# --------------------------------------------------------------------------- inbox + SSE

def calls_list(r1: dict, r2: dict, r4: dict) -> list[dict]:
    def row(r: dict, status: str, dur: float, variant: str, ts: str) -> dict:
        crit = [f["criterion"] for f in sorted(r["findings"], key=lambda f: -f["risk"])]
        return {"call_id": r["call_id"], "status": status, "duration_s": dur, "variant": variant,
                "decision": r["decision"], "risk_score": r["risk_score"], "confidence": r["confidence"],
                "criteria": crit, "n_stage_errors": len(r["stage_errors"]), "updated_at": ts, "is_mock": True}
    rows = [
        row(r1, "done", CALL_1[1], "clean", "2026-10-10T14:02:11Z"),
        row(r2, "done", CALL_2[1], "noisy", "2026-10-10T14:03:40Z"),
        {"call_id": "call_MOCK_003", "status": "processing", "duration_s": 212.0, "variant": "unspecified",
         "updated_at": "2026-10-10T14:05:02Z", "is_mock": True},
        row(r4, "error", 175.3, "noisy", "2026-10-10T14:04:19Z"),
    ]
    return [CallListItem.from_dict(r).to_dict() for r in rows]


def events_call_1(trace: dict) -> list[dict]:
    t0 = 14 * 3600 + 1 * 60 + 5   # 14:01:05Z
    out, seq, t = [], 1, float(t0)

    def ts(x: float) -> str:
        x = int(x)
        return f"2026-10-10T{x // 3600:02d}:{x // 60 % 60:02d}:{x % 60:02d}Z"

    def add(**kw):
        nonlocal seq
        out.append({"seq": seq, "call_id": "call_MOCK_001", "ts": ts(t), **kw})
        seq += 1
    add(event="job_queued", message="[MOCK] call_MOCK_001.wav uploaded")
    for stage in ("asr", "diarize", "keywords", "extract", "validate", "rules", "confidence", "decide",
                  "narrate", "snippets"):
        add(event="stage_started", stage=stage)
        dt = trace["timings_s"][stage]
        t += dt
        add(event="stage_finished", stage=stage, elapsed_s=dt, cached=False)
    add(event="job_finished", decision=trace["decision"])
    return [ProcessingEvent.from_dict(e).to_dict() for e in out]


# --------------------------------------------------------------------------- quality report

N_BOOT, CI_LEVEL, BOOT_SEED = 1000, 0.95, 20261010


def decide(risk: float, conf: float, t: dict) -> str:
    if conf < t["confidence_gate"]:
        return "review"
    return "alarm" if risk >= t["alarm"] else "review" if risk >= t["review"] else "no_alert"


def eval_table() -> list[dict]:
    """Invented per-call table: 20 calls in 9 dialogue groups, clean + noisy versions together."""
    rng = random.Random(7)
    groups = [("alarm", 3), ("alarm", 3), ("alarm", 2), ("review", 2), ("review", 2),
              ("no_alert", 2), ("no_alert", 2), ("no_alert", 2), ("alarm", 2)]
    base = {"alarm": 0.8, "review": 0.55, "no_alert": 0.2}
    stufe = {"alarm": "3", "review": "2", "no_alert": "1"}   # MOCK mapping, not the case's definition
    rows = []
    for g, (gold, size) in enumerate(groups):
        for k in range(size):
            variant = "clean" if k % 2 == 0 else "noisy"
            noise = 0.12 if variant == "clean" else 0.2
            clip = lambda x: min(1.0, max(0.0, x))  # noqa: E731
            risk = {("combined", "asr"): clip(base[gold] + rng.gauss(0, noise)),
                    ("combined", "reference"): clip(base[gold] + rng.gauss(0, 0.08)),
                    ("keyword_only", "asr"): clip(base[gold] + 0.25 * (gold == "no_alert") + rng.gauss(0, noise)),
                    ("keyword_only", "reference"): clip(base[gold] + 0.25 * (gold == "no_alert") + rng.gauss(0, 0.08)),
                    ("llm_only", "asr"): clip(base[gold] + rng.gauss(0, noise + 0.05)),
                    ("llm_only", "reference"): clip(base[gold] + rng.gauss(0, 0.1))}
            conf = clip(0.82 - (0.2 if variant == "noisy" else 0) + rng.gauss(0, 0.08))
            rows.append({"group": g, "gold": gold, "variant": variant, "stufe": stufe[gold], "risk": risk,
                         "conf": conf, "wer": clip((0.22 if variant == "clean" else 0.42) + rng.gauss(0, 0.07))})
    return rows


def resamples(rows: list[dict], name: str) -> list[list[int]]:
    """Bootstrap by dialogue group: draw groups with replacement, keep all their calls."""
    rng = random.Random(f"{BOOT_SEED}:{name}")
    by_group: dict[int, list[int]] = {}
    for i, r in enumerate(rows):
        by_group.setdefault(r["group"], []).append(i)
    keys = sorted(by_group)
    return [[i for _ in keys for i in by_group[rng.choice(keys)]] for _ in range(N_BOOT)]


def ci(values: list[float | None]) -> tuple[float | None, float | None]:
    vals = sorted(v for v in values if v is not None)
    if len(vals) < N_BOOT / 2:
        return None, None
    a = (1 - CI_LEVEL) / 2
    return r3(vals[int(a * (len(vals) - 1))]), r3(vals[int((1 - a) * (len(vals) - 1))])


def metric(point: float | None, boots: list[float | None]) -> dict:
    lo, hi = ci(boots)
    return {"value": None if point is None else r3(point), "ci_low": lo, "ci_high": hi}


def conventions(gold: list[str], pred: list[str], boot: list[list[int]]) -> dict:
    def blocks(idx):
        g, p = [gold[i] for i in idx], [pred[i] for i in idx]
        return binary(g, p, ("alarm",)), binary(g, p, ("alarm", "review")), three_class(g, p)
    point = blocks(range(len(gold)))
    bs = [blocks(idx) for idx in boot]
    out = {"n": len(gold)}
    for j, conv in enumerate(("strict_alarm", "escalation")):
        b = point[j]
        out[conv] = {**{k: b[k] for k in ("tp", "fp", "fn", "tn")},
                     **{k: metric(b[k], [x[j][k] for x in bs]) for k in ("precision", "recall", "f1")}}
    tc = point[2]
    out["three_class"] = {"labels": list(DECISIONS), "confusion": tc["confusion"],
                          "macro_f1": metric(tc["macro_f1"], [x[2]["macro_f1"] for x in bs]),
                          "accuracy": metric(tc["accuracy"], [x[2]["accuracy"] for x in bs])}
    return out


def ece(rows: list[dict], preds: list[str], idx, edges: list[float]) -> tuple[float | None, list[dict]]:
    bins = []
    for lo, hi in zip(edges, edges[1:]):
        members = [i for i in idx if lo <= rows[i]["conf"] < hi or (hi == 1.0 and rows[i]["conf"] == 1.0)]
        conf = sum(rows[i]["conf"] for i in members) / len(members) if members else None
        acc = sum(rows[i]["gold"] == preds[i] for i in members) / len(members) if members else None
        bins.append({"lo": lo, "hi": hi, "n": len(members), "mean_confidence": conf, "accuracy": acc})
    n = sum(b["n"] for b in bins)
    e = sum(b["n"] / n * abs(b["accuracy"] - b["mean_confidence"]) for b in bins if b["n"]) if n else None
    return e, bins


def quality_report() -> dict:
    rows = eval_table()
    gold = [r["gold"] for r in rows]
    preds = {k: [decide(r["risk"][k], r["conf"], THRESHOLDS) for r in rows] for k in rows[0]["risk"]}
    pred = preds[("combined", "asr")]
    boot = resamples(rows, "overall")

    breakdowns = {}
    for key in ("stufe", "variant"):
        breakdowns[key] = {}
        for g in sorted({r[key] for r in rows}):
            sub = [i for i, r in enumerate(rows) if r[key] == g]
            sb = resamples([rows[i] for i in sub], f"{key}={g}")
            breakdowns[key][g] = conventions([gold[i] for i in sub], [pred[i] for i in sub], sb)

    def curve(param: str, convention: str) -> dict:
        positive = ("alarm",) if convention == "strict_alarm" else ("alarm", "review")
        points = []
        for k in range(21):
            t = {**THRESHOLDS, param.replace("_threshold", ""): k / 20}
            if t["review"] >= t["alarm"] and param != "confidence_gate":
                t = {**t, "review" if param == "alarm_threshold" else "alarm": k / 20}
            p = [decide(r["risk"][("combined", "asr")], r["conf"], t) for r in rows]
            b = binary(gold, p, positive)
            points.append({"threshold": r3(k / 20), **{m: None if b[m] is None else r3(b[m])
                                                        for m in ("precision", "recall", "f1")}})
        current = THRESHOLDS[param.replace("_threshold", "")]
        return {"param": param, "convention": convention, "current": current, "points": points}

    edges = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    e_point, bins = ece(rows, pred, range(len(rows)), edges)
    e_boot = [ece(rows, pred, idx, edges)[0] for idx in boot]
    bins = [{**b, "mean_confidence": None if b["mean_confidence"] is None else r3(b["mean_confidence"]),
             "accuracy": None if b["accuracy"] is None else r3(b["accuracy"])} for b in bins]

    wer_bins = []
    escalate = [i for i, g in enumerate(gold) if g != "no_alert"]
    for lo, hi in ((0.0, 0.2), (0.2, 0.35), (0.35, 0.5), (0.5, 1.0)):
        members = [i for i in escalate if lo <= rows[i]["wer"] < hi]
        rec = lambda idx: (sum(pred[i] != "no_alert" for i in idx) / len(idx)) if idx else None  # noqa: E731
        mb = resamples([rows[i] for i in members], f"wer={lo}") if members else []
        wer_bins.append({"wer_lo": lo, "wer_hi": hi, "n": len(members),
                         "escalation_recall": metric(rec(members), [rec([members[j] for j in idx]) for idx in mb])})

    latency = [
        {"stage": s, "n": 20, "mean_s": m, "p50_s": p50, "p95_s": p95} for s, m, p50, p95 in (
            ("asr", 38.2, 35.0, 61.4), ("diarize", 6.3, 5.9, 9.8), ("keywords", 0.02, 0.02, 0.04),
            ("extract", 12.7, 11.9, 19.5), ("validate", 0.03, 0.03, 0.05), ("rules", 0.01, 0.01, 0.02),
            ("confidence", 0.01, 0.01, 0.02), ("decide", 0.0, 0.0, 0.0), ("narrate", 3.6, 3.4, 5.9),
            ("snippets", 0.5, 0.4, 1.1))]

    return QualityReport.from_dict({
        "report_id": "quality_MOCK_test", "created_at": "2026-10-10T14:10:00Z", "run_id": "pipeline_MOCK_test",
        "system": "pipeline", "provider": "MOCK", "mode": "asr", "split": "test",
        "bootstrap": {"n_resamples": N_BOOT, "ci_level": CI_LEVEL, "unit": "dialogue group", "seed": BOOT_SEED},
        "overall": conventions(gold, pred, boot),
        "breakdowns": breakdowns,
        "threshold_curves": [curve("alarm_threshold", "strict_alarm"), curve("review_threshold", "escalation"),
                             curve("confidence_gate", "escalation")],
        "reliability": {"correctness": "3-class decision == gold label", "bins": bins,
                        "ece": metric(e_point, e_boot)},
        "ablations": [{"name": n, "transcript": t,
                       "conventions": conventions(gold, preds[(n, t)], boot)}
                      for n in ("keyword_only", "llm_only", "combined") for t in ("reference", "asr")],
        "wer_vs_recall": wer_bins,
        "latency": latency,
        "evidence_validity": {"n_items": 41, "n_valid_items": 37, "item_validity_rate": r3(37 / 41),
                              "per_check_pass_rate": {"segment_refs": 1.0, "quote_match": 0.927,
                                                      "speaker_match": 0.951, "timestamps": 1.0,
                                                      "snippet_playable": 0.976},
                              "checks_skipped": ["snippet_contains_speech: not implemented: needs ASR "
                                                 "re-check of the cut snippet"]},
        "warnings": [MOCK, "MOCK stufe mapping (alarm=3, review=2, no_alert=1) is invented"],
        "notes": ["Numbers come from an invented per-call table scored with pipeline.evaluate.binary/three_class; "
                  "CIs are a percentile bootstrap over dialogue groups."],
        "is_mock": True,
    }).to_dict()


# --------------------------------------------------------------------------- output

def dumps(o, ind: int = 0) -> str:
    """JSON with scalar lists on one line (keeps arrays readable and diffs small)."""
    pad = "  " * ind
    if isinstance(o, dict) and o:
        items = [f"{pad}  {json.dumps(k, ensure_ascii=False)}: {dumps(v, ind + 1)}" for k, v in o.items()]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(o, list) and any(isinstance(x, (dict, list)) for x in o):
        return "[\n" + ",\n".join(f"{pad}  {dumps(x, ind + 1)}" for x in o) + f"\n{pad}]"
    return json.dumps(o, ensure_ascii=False)


def with_audio_quality(trace: dict, an: dict) -> dict:
    """audio_quality is the one analysis block that feeds the confidence gate: keep them in sync."""
    trace["confidence_breakdown"]["components"]["audio_quality"] = an["audio_quality"]["call_score"]
    return DecisionTrace.from_dict(trace).to_dict()


def whatif() -> dict[str, object]:
    """feedback.json, simulation.json, suggestions.json, whatif_calls.json: the REAL simulate/suggest code run over a small
    invented corpus (call_MOCK_101..112, config frozen in fixtures/config_snapshot/ so tuning config/ never drifts these)."""
    from dataclasses import replace
    import yaml
    sys.path.insert(0, str(REPO_ROOT / "fixtures"))
    from whatif_corpus import make_corpus
    from pipeline.feedback import make_entry
    from pipeline.schemas import FeedbackEntry, SimulationResult, SuggestionsResponse
    from pipeline.simulate import RawConfig, Simulator, split_patch, patch_components
    from pipeline.suggest import suggestions_response

    snap = Path(__file__).resolve().parent / "config_snapshot"
    raw = RawConfig(json.loads((snap / "keywords.json").read_text(encoding="utf-8")),
                    yaml.safe_load((snap / "rules.yaml").read_text(encoding="utf-8")),
                    json.loads((snap / "thresholds.json").read_text(encoding="utf-8")))
    calls = make_corpus(12, seed=1, mock=True, first_id=101)
    base = Simulator(calls, raw).baseline
    # Officer verdicts (invented): the two password jokes are false alarms, one split-payment alarm is a false alarm,
    # the insider alarms and the quiet calls are right.
    verdicts = {"call_MOCK_104": ("false_alarm", "Kunde hat Spass gemacht, kein echtes Passwort."),
                "call_MOCK_106": ("false_alarm", "Ironisch gemeint."),
                "call_MOCK_107": ("false_alarm", "Ratenzahlung mit Segen der Kreditabteilung."),
                "call_MOCK_103": ("correct", None), "call_MOCK_105": ("correct", None), "call_MOCK_101": ("correct", None),
                "call_MOCK_102": ("correct", None), "call_MOCK_108": ("correct", None), "call_MOCK_110": ("correct", None)}
    fb = {}
    for i, (cid, (verdict, note)) in enumerate(sorted(verdicts.items())):
        fb[cid] = make_entry(cid, verdict, base[cid].decision, note, base[cid].versions.rules, f"2026-10-10T13:{i:02d}:00Z", True)
    resp = replace(suggestions_response(calls, fb, raw), generated_at="2026-10-10T14:10:00Z")
    sim = Simulator(calls, raw, fb)
    sample = sim.run({"thresholds": {"alarm": 0.87}})
    toggles = (split_patch({"keywords": {"disable_families": sorted(raw.keywords["families"])}})
               + split_patch({"rules": {"disable": [r["criterion"] for r in raw.rules["rules"] if r.get("enabled", True)]}}))
    components = [patch_components(p)[0] for p in toggles]
    solo = {c.call_id: {} for c in calls}
    for comp, p in zip(components, toggles):
        for cid, d in sim.decisions(p).items():
            solo[cid][comp] = d
    rows = [{"call_id": c.call_id, "decision": base[c.call_id].decision, "decision_path": base[c.call_id].decision_path,
             "risk_score": base[c.call_id].risk_score, "confidence": base[c.call_id].confidence, "locked": c.locked,
             "if_disabled": solo[c.call_id]} for c in calls]
    for d in (resp, sample):
        assert d.is_mock
    assert SuggestionsResponse.validate(resp.to_dict()) == [] and SimulationResult.validate(sample.to_dict()) == []
    return {
        "feedback.json": [FeedbackEntry.from_dict(e.to_dict()).to_dict() for e in fb.values()],
        "simulation.json": sample.to_dict(),
        "suggestions.json": resp.to_dict(),
        "whatif_calls.json": {"is_mock": True, "config_version": sim.base_config.rules_version, "thresholds":
                              {k: raw.thresholds[k] for k in ("alarm", "review", "confidence_gate")}, "components": components, "calls": rows},
    }


def build() -> dict[str, object]:
    r1, t1 = call_1()
    r2, t2 = call_2()
    r4 = call_4()
    a1 = analysis(CALL_1, r1, seed=1)
    a2 = analysis(CALL_2, r2, seed=2, failed=("pitch",))
    t1, t2 = with_audio_quality(t1, a1), with_audio_quality(t2, a2)
    return {
        "calls.json": calls_list(r1, r2, r4),
        "call_MOCK_001.result.json": r1,
        "call_MOCK_001.transcript.json": transcript(CALL_1),
        "call_MOCK_001.trace.json": t1,
        "call_MOCK_001.analysis.json": a1,
        "call_MOCK_001.events.json": events_call_1(t1),
        "call_MOCK_002.result.json": r2,
        "call_MOCK_002.transcript.json": transcript(CALL_2),
        "call_MOCK_002.trace.json": t2,
        "call_MOCK_002.analysis.json": a2,
        "call_MOCK_004.result.json": r4,
        "quality_report.json": quality_report(),
        **whatif(),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, obj in build().items():
        (args.out / name).write_text(dumps(obj) + "\n", encoding="utf-8")
        print(f"wrote {args.out / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
