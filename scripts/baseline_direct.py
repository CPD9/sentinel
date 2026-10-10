"""Milestone 2 baseline: one LLM prompt per call over the reference transcript -> decision + evidence.

For every call in a split, the organizer script is read through pipeline.reference.reference_transcript
(artifacts/manifests/reference_transcripts.json; label-free: segment_id, speaker, text only) and sent with ONE prompt to the self-hosted LLM at
LLM_BASE_URL, which answers with decision + criterion + evidence quotes as JSON. No rules, no keywords,
no confidence gate: this is the number the real pipeline has to beat.

Responses are cached under artifacts/cache/baseline_direct/ by sha256 of (provider, model, revision,
prompt version, messages, runtime). Clean and noisy recordings share a script, so they share a cache entry.

    python scripts/baseline_direct.py --split dev                    # real LLM, fails if unreachable
    python scripts/baseline_direct.py --split dev --provider mock    # MOCK: keyword cues, not a model
    python -m pipeline.evaluate --pred artifacts/predictions/<run_id>.json --split dev
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline.llm import RUNTIME_VERSION, DiskCache, LLMError, ProviderNotPermitted, get_client  # noqa: E402
from pipeline.reference import reference_transcript  # noqa: E402
from pipeline.schemas import (CRITERIA, DECISIONS, SPEAKERS, CallResult, Evidence, Finding,  # noqa: E402
                              RunResult, StageError, Versions)

PROMPT_VERSION = "baseline-direct-v1"
SPLITS_FILE = REPO_ROOT / "artifacts" / "splits" / "dialogue_splits.json"
CACHE_DIR = REPO_ROOT / "artifacts" / "cache" / "baseline_direct"
PRED_DIR = REPO_ROOT / "artifacts" / "predictions"
MOCK_ID = "MOCK:keyword-cues-v1"

SYSTEM_PROMPT = """You are a compliance reviewer for a Swiss bank. You read the transcript of one phone call \
between a bank advisor and a customer, in Swiss German, and decide whether compliance must be alerted.

Criteria (the only reasons for an alarm):
- insider_trading: the customer requests a trade of their own BECAUSE of nonpublic, price-relevant \
information they hold (e.g. an unannounced takeover from an insider). Execution is not required.
- credential_sharing: someone actually discloses a currently active access secret (password, PIN, \
one-time code). Mentioning, refusing, or reading an expired value is not disclosure of an active secret.
- third_party_disclosure: the advisor actually reveals protected details about another person after it \
was clear the caller is not authorised. Merely asking, or refusing, is not disclosure.
- documentation_concealment: an intentional request to hide a relevant fact from the internal party who \
must receive it. Correcting a mistake is fine.
- control_evasion: a request to split a payment or transaction into connected parts expressly to avoid a \
stated internal check or approval process.
- payment_card_data: a full number is read out; classify what it is. Digits alone never justify an alarm.

Decisions:
- "alarm": the call clearly meets one criterion.
- "review": a criterion might be met, but a decisive fact is missing or ambiguous, so a human must decide.
- "no_alert": no criterion is met (including calls where a risky topic is raised and correctly refused).

Answer with ONE JSON object and nothing else:
{"decision": "alarm" | "review" | "no_alert",
 "criterion": one of the criterion names above, or "none",
 "risk": number between 0 and 1,
 "reason": one or two sentences,
 "evidence": [{"segment_id": "T012", "speaker": "advisor" | "customer", "quote": "exact words copied from that segment"}]}
Cite the segments that justify the decision (empty list for no_alert). Quotes must be copied verbatim."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": list(DECISIONS)},
        "criterion": {"type": "string", "enum": [c for c in CRITERIA if c != "other"] + ["none"]},
        "risk": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
        "evidence": {"type": "array", "items": {
            "type": "object",
            "properties": {"segment_id": {"type": "string"},
                           "speaker": {"type": "string", "enum": ["advisor", "customer"]},
                           "quote": {"type": "string"}},
            "required": ["segment_id", "speaker", "quote"]}},
    },
    "required": ["decision", "criterion", "risk", "reason", "evidence"],
}


def build_messages(turns: list[dict]) -> list[dict]:
    body = "\n".join(f"[{t['segment_id']}] {t['speaker']}: {t['text']}" for t in turns)
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Transcript:\n{body}"}]


# --------------------------------------------------------------------------- providers

class MockProvider:
    """MOCK, NOT A MODEL. Flags the first turn containing a hard-coded cue so the plumbing can be
    exercised while the GPU endpoint is down. Its metrics mean nothing about LLM quality."""
    model, model_revision = MOCK_ID, "mock"
    CUES = [
        ("insider_trading", ("nöd öffentlich", "vor der bekanntgabe", "übernahme")),
        ("credential_sharing", ("passwort", "pin", "code")),
        ("third_party_disclosure", ("kontostand vo", "ihrer mueter", "ihrem ma")),
        ("documentation_concealment", ("wegloh", "nöd ufschriibe", "weglaa")),
        ("control_evasion", ("ufteile", "zwei zahlige", "under de grenze")),
    ]

    def chat(self, messages, **_kw) -> str:
        transcript = messages[-1]["content"]
        for line in transcript.splitlines():
            m = re.match(r"^\[(\S+)\] (\w+): (.*)$", line)
            if not m:
                continue
            low = m[3].lower()
            for criterion, cues in self.CUES:
                if any(re.search(rf"\b{re.escape(c)}\b", low) for c in cues):
                    return json.dumps({"decision": "alarm", "criterion": criterion, "risk": 0.8,
                                       "reason": f"MOCK cue match for {criterion}",
                                       "evidence": [{"segment_id": m[1], "speaker": m[2],
                                                     "quote": " ".join(m[3].split()[:12])}]})
        return json.dumps({"decision": "no_alert", "criterion": "none", "risk": 0.1,
                           "reason": "MOCK: no cue matched", "evidence": []})


# --------------------------------------------------------------------------- response -> CallResult

def parse_json_object(text: str) -> dict:
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no JSON object in response")
        obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("response JSON is not an object")
    return obj


DEFAULT_RISK = {"alarm": 0.9, "review": 0.5, "no_alert": 0.1}


def to_call_result(call_id: str, raw: str, versions: Versions) -> CallResult:
    try:
        obj = parse_json_object(raw)
        decision = obj.get("decision")
        if decision not in DECISIONS:
            raise ValueError(f"invalid decision {decision!r}")
    except (ValueError, json.JSONDecodeError) as e:
        # never silently no_alert: an unusable answer goes to a human
        return CallResult(call_id=call_id, decision="review", risk_score=0.0, confidence=None,
                          narrative="LLM answer unusable; sent to human review.",
                          stage_errors=[StageError("baseline_llm", f"{e}; raw={raw[:300]!r}")],
                          versions=versions)
    risk = obj.get("risk")
    risk = min(max(float(risk), 0.0), 1.0) if isinstance(risk, (int, float)) and not isinstance(risk, bool) \
        else DEFAULT_RISK[decision]
    evidence = []
    for e in obj.get("evidence") or []:
        if not isinstance(e, dict):
            continue
        sid = e.get("segment_id")
        ids = [str(s) for s in sid] if isinstance(sid, list) else ([str(sid)] if sid else [])
        if not ids:
            continue
        speaker = e.get("speaker") if e.get("speaker") in SPEAKERS else "unknown"
        evidence.append(Evidence(segment_ids=ids, speaker=speaker, text=str(e.get("quote") or "")))
    reason = str(obj.get("reason") or "")
    findings = []
    if decision != "no_alert":
        criterion = obj.get("criterion") if obj.get("criterion") in CRITERIA else "other"
        findings.append(Finding(criterion=criterion, risk=risk, reason=reason, evidence=evidence))
    return CallResult(call_id=call_id, decision=decision, risk_score=risk, confidence=None,
                      findings=findings, narrative=reason, versions=versions)


# --------------------------------------------------------------------------- main

def run(split: str, provider_name: str, out_dir: Path = PRED_DIR, cache_dir: Path = CACHE_DIR,
        limit: int | None = None, model: str | None = None) -> tuple[Path, dict]:
    call_ids = json.loads(SPLITS_FILE.read_text(encoding="utf-8"))["splits"][split]["call_ids"]
    if limit:
        call_ids = call_ids[:limit]
    opts_tag = ""
    if provider_name == "mock":
        provider = MockProvider()
        provider_id = MOCK_ID
    else:
        provider = get_client(model=model)     # provider: $SENTINEL_LLM_PROVIDER, else the registry default
        provider.probe()           # fails loudly if the tunnel / vLLM is down
        opts = provider.effective_extra_body()
        # request options change the answers, so they are part of the run identity (same provider + model + options
        # = same run; different options must not overwrite each other)
        opts_tag = hashlib.sha256(json.dumps(opts, sort_keys=True).encode()).hexdigest()[:8] if opts else ""
        provider_id = f"llm:{provider.spec.name}:{provider.model}" + (f"+opts-{opts_tag}" if opts_tag else "")
    if provider_name == "mock":
        versions = Versions(llm=f"{provider.model}@{provider.model_revision}", prompt=PROMPT_VERSION)
    else:
        versions = Versions(**provider.version_info(), prompt=PROMPT_VERSION)
    provider_key = "mock" if provider_name == "mock" else provider.spec.name
    cache = DiskCache(cache_dir)
    stats = {"calls": 0, "cache_hits": 0, "llm_requests": 0, "stage_errors": 0}
    results = []
    for cid in call_ids:
        messages = build_messages(reference_transcript(cid))
        key = cache.key({"provider": provider_id, "provider_name": provider_key,
                         "extra_body": {} if provider_name == "mock" else provider.effective_extra_body(), "model": provider.model, "revision": provider.model_revision,
                         "prompt_version": PROMPT_VERSION, "runtime": RUNTIME_VERSION, "messages": messages,
                         "temperature": 0.0, "schema": RESPONSE_SCHEMA})
        hit = cache.get(key)
        if hit is not None:
            raw = hit["response"]
            stats["cache_hits"] += 1
        else:
            try:
                raw = provider.chat(messages, temperature=0.0, max_tokens=1024, json_schema=RESPONSE_SCHEMA)
                cache.put(key, {"response": raw, "provider": provider_id, "model": provider.model,
                                "revision": provider.model_revision, "prompt_version": PROMPT_VERSION,
                                "created_at": datetime.now(timezone.utc).isoformat()})
            except LLMError as e:
                raw = ""
                print(f"{cid}: LLM error: {e}", file=sys.stderr)
            stats["llm_requests"] += 1
        res = to_call_result(cid, raw, versions)
        stats["stage_errors"] += bool(res.stage_errors)
        stats["calls"] += 1
        results.append(res)
        print(f"{cid}: {res.decision:8s} {[f.criterion for f in res.findings]}"
              f"{'  (cached)' if hit is not None else ''}{'  STAGE ERROR' if res.stage_errors else ''}")

    tag = "MOCK" if provider_name == "mock" else re.sub(r"[^A-Za-z0-9.-]+", "-", f"{provider.spec.name}-{provider.model}"
                                            + (f"-opts-{opts_tag}" if opts_tag else ""))
    run_id = f"baseline_direct_{tag}_{split}"
    notes = [f"input: reference transcripts (organizer scripts), split={split}",
             "confidence is not computed by this baseline (null)",
             "risk_score is the model's self-reported risk; falls back to a per-decision default if missing"]
    if provider_name == "mock":
        notes.insert(0, "MOCK PROVIDER: hard-coded keyword cues, not an LLM. Metrics are plumbing checks only.")
    rr = RunResult(run_id=run_id, mode="reference", system="baseline_direct", provider=provider_id,
                   created_at=datetime.now(timezone.utc).isoformat(), calls=results, notes=notes)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{run_id}.json"
    out.write_text(json.dumps(rr.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=("dev", "holdout", "test"), default="dev")
    ap.add_argument("--provider", choices=("llm", "mock"), default="llm")
    ap.add_argument("--model", help="model id (needed for remote providers; set the provider with SENTINEL_LLM_PROVIDER)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N calls (smoke test)")
    ap.add_argument("--allow-test", action="store_true", help="required to run on the locked test split")
    args = ap.parse_args(argv)
    if args.split == "test" and not args.allow_test:
        ap.error("the test split is locked; pass --allow-test for the final report only")
    try:
        out, stats = run(args.split, args.provider, limit=args.limit, model=args.model)
    except ProviderNotPermitted as e:
        print(f"REFUSED by the provider policy gate: {e}", file=sys.stderr)
        return 2
    except LLMError as e:
        print(f"LLM endpoint unavailable: {e}\nStart the SSH tunnel, or run with --provider mock "
              f"(clearly labelled, not an LLM).", file=sys.stderr)
        return 2
    print(f"\n{stats}\npredictions written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
