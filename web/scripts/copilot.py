"""Copilot for the web app (web/app/copilot-api): grounded questions about one call or the whole run, and
deterministic entity/phrase patterns across calls.

Spawned once per request by the Next route handler, which allows one LLM request at a time.
Protocol: one JSON request on stdin, NDJSON events on stdout.
  {"op": "ask", "scope": "call", "call_id": "call_017", "question": "...", "history": [{q, a}]}
  {"op": "ask", "scope": "all", "question": "...", "history": [...]}
      -> {"type": "start", provider, model, self_hosted}
         {"type": "claim", text, citations: [{call_id, segment_id, speaker, start_s, end_s, text}]}   (validated)
         {"type": "dropped", reason}                                                       (uncited / invalid)
         {"type": "retry"}                                     (every claim failed: asked once more, sequentially)
         {"type": "not_in_call"}                                                           (nothing survived)
         {"type": "done", kept, dropped, wall_ms}  |  {"type": "error", detail}
  {"op": "patterns"} -> {"type": "patterns", ...}  (no LLM)

Grounding: the model answers in schema-constrained JSON, one claim per segment id plus words copied from it; each claim is
checked with pipeline/validate.py (the same evidence checker the extraction uses) as soon as it is streamed, and
only claims that pass reach the officer. Uncited or unverifiable claims are dropped and only counted, never shown.
Label isolation: reads results/, transcripts[_reference]/, traces[_reference]/ and judge/ of the run (falling back
to the artifacts folder). Never evaluation.json, never original file names. Writes nothing; nothing is cached.
Usage: python web/scripts/copilot.py <artifacts_dir> <run_dir>
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline.llm import LLMError, check_permitted, get_client  # noqa: E402
from pipeline.schemas import Fact, Transcript, TranscriptSegment  # noqa: E402
from pipeline.validate import norm, reason_key, validate_facts  # noqa: E402

PROMPT_BUDGET = 15000          # characters of context; Apertus 8B on builder_pod serves 8192 tokens
MAX_TOKENS = 700


# --------------------------------------------------------------------------- data

class Store:
    def __init__(self, art: Path, run: Path):
        self.art, self.run = art, run
        res = _read(run / "results.json") or {}
        self.suffix = "_reference" if res.get("mode") == "reference" else ""
        self.provider_of_run = res.get("provider")

    def _find(self, kind: str, call_id: str) -> dict | None:
        for root in (self.run, self.art):
            for k in (f"{kind}{self.suffix}", kind) if kind == "judge" else (f"{kind}{self.suffix}",):
                d = _read(root / k / f"{call_id}.json")
                if d is not None:
                    return d
        return None

    def ids(self) -> list[str]:
        folder = self.run / "results"
        return sorted(p.stem for p in folder.glob("call_*.json")) if folder.exists() else []

    def result(self, call_id: str) -> dict | None:
        return _read(self.run / "results" / f"{call_id}.json")

    def transcript(self, call_id: str) -> Transcript | None:
        d = self._find("transcripts", call_id)
        if d is None:
            return None
        segs = [TranscriptSegment(id=s["id"], speaker=s.get("speaker", "unknown"), text=s.get("text", ""),
                                  start_s=s.get("start_s"), end_s=s.get("end_s")) for s in d.get("segments", [])]
        return Transcript(call_id=call_id, mode=d.get("mode", "asr"), segments=segs, duration_s=d.get("duration_s"))

    def trace(self, call_id: str) -> dict | None:
        return self._find("traces", call_id)

    def judge(self, call_id: str) -> dict | None:
        return self._find("judge", call_id)


def _read(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def emit(ev: dict) -> None:
    print(json.dumps(ev, ensure_ascii=False), flush=True)


# --------------------------------------------------------------------------- answer lines

def claim_schema(cross_call: bool) -> dict:
    item = {"claim": {"type": "string"}, "segment_id": {"type": "string", "pattern": "^S[0-9]{4}$"},
            "quote": {"type": "string"}}
    if cross_call:
        item = {"call_id": {"type": "string", "pattern": "^call_[0-9]{3}$"}, **item}
    return {"type": "object", "required": ["in_call", "claims"], "properties": {
        "in_call": {"type": "boolean"},
        "claims": {"type": "array", "maxItems": 6, "items": {"type": "object", "properties": item, "required": list(item)}}}}


def to_parsed(obj: dict) -> dict:
    """One claim object from the model -> {text, cites: [{refs: [(call_id|None, seg_id)], quote}]}."""
    if not isinstance(obj, dict):
        return {"text": "", "cites": []}
    seg = str(obj.get("segment_id") or "").strip()
    call = str(obj.get("call_id") or "").strip().lower() or None
    refs = [(call, seg.upper())] if seg else []
    return {"text": str(obj.get("claim") or "").strip(), "cites": [{"refs": refs, "quote": str(obj.get("quote") or "").strip()}] if refs else []}


class ClaimScanner:
    """Pulls complete claim objects out of a JSON reply while it is still streaming."""
    def __init__(self):
        self.buf, self.pos = "", None
        self.dec = json.JSONDecoder()

    def feed(self, piece: str) -> list[dict]:
        self.buf += piece
        if self.pos is None:
            k = self.buf.find('"claims"')
            j = self.buf.find("[", k) if k >= 0 else -1
            if j < 0:
                return []
            self.pos = j + 1
        out = []
        while True:
            while self.pos < len(self.buf) and self.buf[self.pos] in " \t\r\n,":
                self.pos += 1
            if self.pos >= len(self.buf) or self.buf[self.pos] != "{":
                return out
            try:
                obj, end = self.dec.raw_decode(self.buf, self.pos)
            except ValueError:
                return out                  # object not complete yet
            out.append(obj)
            self.pos = end


def check_line(parsed: dict, transcripts: dict[str, Transcript], default_call: str | None, n: int) -> dict:
    """Validate every citation of one parsed claim with pipeline.validate. -> {"ok": claim event} | {"drop": reason}.
    A claim survives when at least one citation passes; failing citations are removed from it."""
    if not parsed["cites"] or not parsed["text"] or not parsed["cites"][0]["quote"]:
        return {"drop": "uncited"}
    citations, reasons, seen = [], [], set()
    for cite in parsed["cites"]:
        by_call: dict[str, list[str]] = defaultdict(list)
        for call, seg in cite["refs"]:
            by_call[call or default_call or ""].append(seg)
        for call, segs in by_call.items():
            tr = transcripts.get(call)
            if tr is None:
                reasons.append("unknown call")
                continue
            fact = Fact(fact_id=f"q{n:03d}", speaker="unknown", act="other", info_type="other",
                        segment_ids=segs, quote=cite["quote"])
            checked = validate_facts([fact], tr)[0]
            if not checked.valid:
                reasons.append(reason_key(checked.drop_reason) or "invalid")
                continue
            by_id = {s.id: s for s in tr.segments}
            for sid in checked.segment_ids:
                if (call, sid) in seen:
                    continue
                seen.add((call, sid))
                seg = by_id[sid]
                citations.append({"call_id": call, "segment_id": sid, "speaker": seg.speaker, "start_s": seg.start_s,
                                  "end_s": seg.end_s, "text": seg.text, "quote": cite["quote"]})
    if not citations:
        return {"drop": reasons[0] if reasons else "invalid"}
    return {"ok": {"type": "claim", "text": parsed["text"], "citations": citations,
                   "dropped_citations": len(reasons)}}


# --------------------------------------------------------------------------- prompts

SYSTEM_CALL = """You help a bank compliance officer understand ONE recorded phone call (Swiss German, transcribed by ASR).
Use ONLY the material in the user message. Reply with JSON:
{"in_call": true, "claims": [{"claim": "...", "segment_id": "S0012", "quote": "..."}]}
- 1 to 5 claims. "claim": one short plain-English sentence for a non-technical reader; no fact ids or rule names.
- "segment_id": the ONE transcript segment that supports the claim. Each piece of evidence is its own claim.
- "quote": 3 to 15 words copied exactly from that segment, in the original language. Never translate.
- Speaker labels may be "unknown": for "who" questions describe the role (bank advisor or customer) only when the
  words make it clear; otherwise say "an unlabelled speaker".
- For "what would make this harmless / change the decision": cite the passages that drive the risk and say what
  would have to be different about them.
- If the call does not contain the answer, reply {"in_call": false, "claims": []}.
"""

SYSTEM_ALL = """You help a bank compliance officer find patterns across many recorded phone calls (Swiss German, ASR).
Use ONLY the material in the user message. Reply with JSON:
{"in_call": true, "claims": [{"claim": "...", "call_id": "call_017", "segment_id": "S0012", "quote": "..."}]}
- 1 to 6 claims. "claim": one short plain-English sentence for a non-technical reader.
- "call_id" + "segment_id": the ONE evidence line that supports the claim. Use only ids present in the EVIDENCE.
- "quote": 3 to 15 words copied exactly from that evidence line, in the original language. Never translate.
- If the material does not contain the answer, reply {"in_call": false, "claims": []}.
"""


def _fmt_t(t) -> str:
    return "" if t is None else f"[{t:.1f}s] "


def call_context(store: Store, call_id: str, tr: Transcript) -> str:
    trace = store.trace(call_id) or {}
    judge = store.judge(call_id) or {}
    res = store.result(call_id) or {}
    lines = [f"CALL {call_id}",
             f"Decision: {res.get('decision', trace.get('decision'))} (path {trace.get('decision_path')}), "
             f"risk {res.get('risk_score', trace.get('risk_score'))}, confidence {res.get('confidence', trace.get('confidence'))}"]
    if judge:
        cites = ", ".join(s for c in judge.get("citations", []) if c.get("valid", True) for s in c.get("segment_ids", []))
        lines.append(f"AI judge: {judge.get('decision')} / criterion {judge.get('criterion')} / risk {judge.get('risk')}"
                     f" / cited {cites or 'nothing'}. Reason: {judge.get('reason')}")
    fired = [r for r in trace.get("rules", []) if r.get("fired") or (r.get("risk") or 0) > 0]
    if fired:
        lines.append("Rules: " + "; ".join(f"{r['criterion']} risk {r['risk']}: {r.get('reason') or ''}"[:220] for r in fired))
    for k in ("why_not_flagged", "what_would_change"):
        v = trace.get(k)
        if v:
            lines.append(f"{k.replace('_', ' ').capitalize()}: {v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}"[:600])
    facts = [f for f in trace.get("facts", []) if f.get("valid")]
    if facts:
        lines.append("Extracted facts (validated):")
        for f in facts[:20]:
            lines.append(f"  {f['fact_id']} {f['speaker']} {f['act']} {f['info_type']}"
                         f"{' third-party' if f.get('recipient_third_party') else ''} {','.join(f['segment_ids'])}: \"{f['quote']}\"")
    head = "\n".join(lines)
    seg_lines = [f"{s.id} {_fmt_t(s.start_s)}{s.speaker}: {s.text}" for s in tr.segments]
    room = PROMPT_BUDGET - len(head)
    body = "\n".join(seg_lines)
    if len(body) > room:                   # keep the start; the 8B context is the hard limit
        body = body[:room].rsplit("\n", 1)[0] + "\n[... transcript truncated]"
    return f"{head}\n\nTRANSCRIPT\n{body}"


def _tokens(text: str) -> set[str]:
    return {w for w in norm(text).split() if len(w) > 3}


def all_context(store: Store, transcripts: dict[str, Transcript], question: str) -> str:
    q = _tokens(question)
    rows: list[tuple[float, str]] = []
    summary = []
    for cid, tr in transcripts.items():
        res = store.result(cid) or {}
        judge = store.judge(cid) or {}
        trace = store.trace(cid) or {}
        flagged = res.get("decision") in ("alarm", "review")
        if flagged:
            summary.append(f"{cid}: {res.get('decision')} risk {res.get('risk_score')} criterion {judge.get('criterion')}")
        by_id = {s.id: s for s in tr.segments}
        cited = {s for c in judge.get("citations", []) if c.get("valid", True) for s in c.get("segment_ids", [])}
        cited |= {s for f in trace.get("facts", []) if f.get("valid") and f.get("info_type") != "other" for s in f["segment_ids"]}
        for s in tr.segments:
            score = len(q & _tokens(s.text)) + (2.0 if s.id in cited else 0) + (1.0 if flagged and s.id in cited else 0)
            if score > 0:
                rows.append((score, f"{cid} {s.id} {_fmt_t(s.start_s)}{s.speaker}: {s.text}"))
    rows.sort(key=lambda r: -r[0])
    head = "FLAGGED CALLS\n" + ("\n".join(summary) or "none") + f"\n({len(transcripts)} calls in total)\n\nEVIDENCE\n"
    out, used = [], len(head)
    for _, line in rows:
        if used + len(line) + 1 > PROMPT_BUDGET:
            break
        out.append(line)
        used += len(line) + 1
    return head + "\n".join(out)


def messages_for(system: str, context: str, question: str, history: list[dict]) -> list[dict]:
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": context}]
    msgs.append({"role": "assistant", "content": "Understood. I will answer only from this material, with citations."})
    for h in history[-2:]:                 # earlier turns: only claims that passed validation, from browser memory
        q = str(h.get("q", ""))[:500] if isinstance(h, dict) else ""
        claims = [{k: str(c.get(k, ""))[:400] for k in ("claim", "call_id", "segment_id", "quote") if c.get(k)}
                  for c in (h.get("claims") or [])[:6] if isinstance(c, dict)] if q else []
        if q:
            msgs += [{"role": "user", "content": q},
                     {"role": "assistant", "content": json.dumps({"in_call": bool(claims), "claims": claims}, ensure_ascii=False)}]
    msgs.append({"role": "user", "content": question})
    return msgs


# --------------------------------------------------------------------------- LLM streaming

def stream_reply(client, messages: list[dict], schema: dict):
    """Yields text pieces. Streams through the client's guarded transport (gate, no redirects, origin pinned);
    falls back to one plain request if streaming fails before anything arrived."""
    check_permitted(client.spec, client.model)
    payload = {"model": client.model, "messages": messages, "temperature": 0.0, "max_tokens": MAX_TOKENS,
               **client.effective_extra_body(), "stream": True,
               "response_format": {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema}}}
    got = False
    try:
        with client._open(f"{client.base_url}/chat/completions", payload, client.timeout) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                chunk = json.loads(data)
                choices = chunk.get("choices") or []
                piece = ((choices[0].get("delta") or {}).get("content")) if choices else None
                if piece:
                    got = True
                    yield piece
        return
    except (LLMError, OSError, ValueError):
        if got:
            raise
    yield client.chat(messages, temperature=0.0, max_tokens=MAX_TOKENS, json_schema=schema, stream=False)


def answer(client, messages: list[dict], transcripts: dict[str, Transcript], default_call: str | None,
           schema: dict) -> dict:
    """Streams one reply and emits each claim as soon as it is complete and validated. When every claim fails the
    evidence check, asks once more with the reasons (same lock, sequential) before saying "not in this call"."""
    kept = dropped = retried = 0
    for attempt in range(2):
        scan, raw, reasons = ClaimScanner(), [], []
        for piece in stream_reply(client, messages, schema):
            raw.append(piece)
            for obj in scan.feed(piece):
                res = check_line(to_parsed(obj), transcripts, default_call, kept + dropped + 1)
                if "ok" in res:
                    kept += 1
                    emit(res["ok"])
                else:
                    dropped += 1
                    reasons.append(res["drop"])
                    emit({"type": "dropped", "reason": res["drop"]})
        if kept or not reasons or attempt:
            break
        retried = 1
        emit({"type": "retry"})
        messages = messages + [{"role": "assistant", "content": "".join(raw)}, {"role": "user", "content": (
            f"None of those claims passed the evidence check ({', '.join(sorted(set(reasons)))}). Answer again: copy the "
            "quote character for character from the cited segment, and cite the segment that really contains it.")}]
    if kept == 0:
        emit({"type": "not_in_call"})
    return {"kept": kept, "dropped": dropped, "retried": retried}


def ask(store: Store, req: dict, client=None) -> None:
    t0 = time.perf_counter()
    question = str(req.get("question", "")).strip()[:1000]
    if not question:
        emit({"type": "error", "detail": "empty question"})
        return
    history = req.get("history") or []
    if req.get("scope") == "all":
        transcripts = {cid: tr for cid in store.ids() if (tr := store.transcript(cid)) is not None}
        if not transcripts:
            emit({"type": "error", "detail": "no transcripts in this run"})
            return
        msgs = messages_for(SYSTEM_ALL, all_context(store, transcripts, question), question, history)
        default_call = None
    else:
        cid = str(req.get("call_id", ""))
        tr = store.transcript(cid) if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", cid) else None
        if tr is None:
            emit({"type": "error", "detail": f"no transcript for {cid}"})
            return
        transcripts = {cid: tr}
        msgs = messages_for(SYSTEM_CALL, call_context(store, cid, tr), question, history)
        default_call = cid
    try:
        client = client or get_client()
        emit({"type": "start", "provider": client.spec.name, "model": client.model, "self_hosted": client.spec.self_hosted})
        stats = answer(client, msgs, transcripts, default_call, claim_schema(req.get("scope") == "all"))
    except LLMError as e:
        emit({"type": "error", "detail": str(e)[:300]})
        return
    emit({"type": "done", **stats, "wall_ms": round((time.perf_counter() - t0) * 1000)})


# --------------------------------------------------------------------------- patterns (deterministic, no LLM)

SECURITIES = [("Shares (Aktien)", r"aktie\w*|\w+aktie\w*"), ("Bonds (Obligationen)", r"obligation\w*|anleihe\w*"),
              ("Funds / ETF", r"fonds|\w+fonds|etf\w*"), ("Options / derivatives", r"option(en)?|derivat\w*|zertifikat\w*"),
              ("Crypto", r"bitcoin\w*|krypto\w*|crypto\w*"), ("Takeover / merger", r"übernahm\w*|fusion\w*|merger")]
ACCOUNTS = [("Account (Konto)", r"\w*konto|\w*kontos|chonto|\w*konten"), ("Custody (Depot)", r"\w*depot\w*"),
            ("Pillar 3a / pension", r"3a|säule|vorsorge\w*|pensionskasse\w*"), ("Mortgage (Hypothek)", r"hypothek\w*"),
            ("Card", r"\w*karte\w*|kreditchart\w*|\w*charte"), ("IBAN", r"iban"), ("E-banking", r"e ?banking|ebanking|twint"),
            ("PIN / password", r"pin|passwort\w*|kennwort\w*|code")]
RECIPIENTS = [("Family member", r"mutter|muetter|vater|vatter|bruder|brüeder|schwester|schwöschter|sohn|tochter|tochter|"
                                 r"frau|mann|ehemann|ehefrau|partner\w*|onkel|tante|grossmuetter|grossmutter|schwager|cousin\w*"),
              ("Colleague / boss", r"kolleg\w*|chef\w*|mitarbeiter\w*|arbeitgeber\w*"),
              ("Friend / neighbour", r"freund\w*|kumpel|nachbar\w*|kolleg"),
              ("Lawyer / trustee", r"anwalt\w*|anwält\w*|treuhänd\w*|notar\w*|berater\w*"),
              ("Press / outsider", r"journalist\w*|zeitung|presse|reporter\w*")]
NGRAM = 4


def _evidence(store: Store, cid: str, tr: Transcript) -> list[dict]:
    """Validated facts + judge citations of one call: {segment_id, quote, third_party, criterion}."""
    trace = store.trace(cid) or {}
    judge = store.judge(cid) or {}
    out = []
    for f in trace.get("facts", []):
        if f.get("valid") and f.get("segment_ids"):
            out.append({"segment_id": f["segment_ids"][0], "quote": f["quote"], "third_party": bool(f.get("recipient_third_party")),
                        "source": "fact"})
    for c in judge.get("citations", []):
        if c.get("valid", True) and c.get("segment_ids"):
            out.append({"segment_id": c["segment_ids"][0], "quote": c.get("quote", ""),
                        "third_party": judge.get("criterion") == "third_party_disclosure" or bool(c.get("recipient_third_party")),
                        "source": "judge"})
    starts = {s.id: s.start_s for s in tr.segments}
    for e in out:
        e["start_s"] = starts.get(e["segment_id"])
    return out


def _match(lexicon, text: str) -> list[str]:
    words = norm(text).split()
    return [label for label, rx in lexicon if any(re.fullmatch(rx, w) for w in words)]


def patterns(store: Store) -> dict:
    calls, entities = {}, defaultdict(lambda: defaultdict(list))
    grams: dict[str, dict[str, dict]] = defaultdict(dict)
    for cid in store.ids():
        tr = store.transcript(cid)
        res = store.result(cid) or {}
        judge = store.judge(cid) or {}
        trace = store.trace(cid) or {}
        calls[cid] = {"decision": res.get("decision"), "risk_score": res.get("risk_score")}
        if tr is None:
            continue
        crit = {judge.get("criterion")} if judge.get("criterion") not in (None, "other") and judge.get("decision") != "no_alert" else set()
        crit |= {r["criterion"] for r in trace.get("rules", []) if r.get("fired")}
        for c in crit:
            entities["criteria"][c].append({"call_id": cid, "segment_id": None, "start_s": None, "quote": judge.get("reason", "")[:160] if c == judge.get("criterion") else ""})
        for e in _evidence(store, cid, tr):
            hit = {"call_id": cid, "segment_id": e["segment_id"], "start_s": e["start_s"], "quote": e["quote"]}
            for kind, lex in (("securities", SECURITIES), ("account_types", ACCOUNTS)):
                for label in _match(lex, e["quote"]):
                    entities[kind][label].append(hit)
            if e["third_party"]:
                for label in _match(RECIPIENTS, e["quote"]) or ["Unnamed third party"]:
                    entities["recipients"][label].append(hit)
            words = norm(e["quote"]).split()
            for i in range(len(words) - NGRAM + 1):
                g = " ".join(words[i:i + NGRAM])
                grams[g].setdefault(cid, hit)
    n_calls = max(1, len(calls))
    phrases = []
    for g, by_call in grams.items():
        if 2 <= len(by_call) <= max(2, int(0.25 * n_calls)):
            phrases.append({"phrase": g, "calls": list(by_call.values())})
    phrases.sort(key=lambda p: (-len(p["calls"]), p["phrase"]))
    seen_sets, uniq = [], []
    for p in phrases:                       # one phrase per identical set of calls (overlapping 4-grams)
        key = frozenset(h["call_id"] for h in p["calls"])
        if key in seen_sets:
            continue
        seen_sets.append(key)
        uniq.append(p)
    def pack(kind):
        rows = []
        for label, hits in entities[kind].items():
            dedup = {}
            for h in hits:
                dedup.setdefault((h["call_id"], h["segment_id"]), h)
            rows.append({"entity": label, "n_calls": len({h["call_id"] for h in hits}), "hits": list(dedup.values())})
        return sorted(rows, key=lambda r: (-r["n_calls"], r["entity"]))
    return {"type": "patterns", "calls": calls, "criteria": pack("criteria"), "securities": pack("securities"),
            "account_types": pack("account_types"), "recipients": pack("recipients"), "phrases": uniq[:30],
            "method": "heuristic: lexicon + 4-gram matching over validated facts and judge citations (no LLM)"}


def main() -> None:
    store = Store(Path(sys.argv[1]), Path(sys.argv[2]))
    try:
        req = json.loads(sys.stdin.readline() or "{}")
    except ValueError:
        emit({"type": "error", "detail": "bad request"})
        return
    if req.get("op") == "patterns":
        emit(patterns(store))
    else:
        ask(store, req)


if __name__ == "__main__":
    main()
