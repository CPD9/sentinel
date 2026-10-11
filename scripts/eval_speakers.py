"""% of words with the right speaker role, against the reference transcripts' turn speakers.

The reference turns have speakers but no timestamps, and the ASR text is closer to Standard German than the Swiss
German scripts, so each call's ASR word sequence is aligned to its reference word sequence (difflib, normalised
tokens). A matched ASR word is scored against the speaker of the reference word it matched.

  matched_acc  % correct over directly matched words (headline)
  filled_acc   % correct over all ASR words; unmatched words take the reference speaker of the nearest matched word
               in the same segment (else the nearest overall)
  coverage     matched words / ASR words
  oracle_acc   acoustic calls only: best possible cluster->role mapping (cluster purity), separates
               diarization errors from mapping errors
Evaluation code: the only place that reads evaluation.json (split, variant), after predictions exist.

    .venv/bin/python scripts/eval_speakers.py --pred ~/Developer/sentinel-runs/speakers
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.io import write_json_atomic  # noqa: E402

RUNS = Path.home() / "Developer/sentinel-runs"
FOLD = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss", "é": "e", "è": "e", "à": "a"})


def tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^\w]+", text.lower().translate(FOLD)) if t]


def score_call(asr_segments: list[dict], pred: dict, ref_turns: list[dict]) -> dict:
    roles = {s["id"]: s for s in pred["segments"]}
    a_tok, a_role, a_seg, a_cl = [], [], [], []
    for i, s in enumerate(asr_segments):
        p = roles.get(s["id"], {})
        for t in tokens(s["text"]):
            a_tok.append(t); a_role.append(p.get("role", "unknown")); a_seg.append(i); a_cl.append(p.get("cluster"))
    r_tok, r_spk = [], []
    for t in ref_turns:
        for w in tokens(t["text"]):
            r_tok.append(w); r_spk.append(t["speaker"])
    truth: list[str | None] = [None] * len(a_tok)
    for b in difflib.SequenceMatcher(None, a_tok, r_tok, autojunk=False).get_matching_blocks():
        for k in range(b.size):
            truth[b.a + k] = r_spk[b.b + k]
    matched = [i for i, x in enumerate(truth) if x is not None]
    filled = list(truth)
    for i, x in enumerate(truth):
        if x is None and matched:
            same = [j for j in matched if a_seg[j] == a_seg[i]] or matched
            filled[i] = truth[min(same, key=lambda j: abs(j - i))]
    ok = sum(a_role[i] == truth[i] for i in matched)
    ok_f = sum(a_role[i] == filled[i] for i in range(len(a_tok)) if filled[i])
    out = {"words": len(a_tok), "matched": len(matched), "correct": ok, "filled_correct": ok_f,
           "filled_n": sum(1 for f in filled if f),
           "all_advisor": sum(truth[i] == "advisor" for i in matched),
           "label_source": pred["label_source"]}
    if pred["label_source"] == "acoustic + content":
        per = defaultdict(Counter)
        for i in matched:
            per[a_cl[i]][truth[i]] += 1
        out["oracle_correct"] = sum(max(c.values()) for c in per.values())
    return out


def pct(a: int, b: int) -> float | None:
    return round(100 * a / b, 1) if b else None


def summarise(rows: list[dict]) -> dict:
    m = sum(r["matched"] for r in rows)
    s = {"calls": len(rows), "words": sum(r["words"] for r in rows), "matched_words": m,
         "matched_acc": pct(sum(r["correct"] for r in rows), m),
         "filled_acc": pct(sum(r["filled_correct"] for r in rows), sum(r["filled_n"] for r in rows)),
         "coverage": pct(m, sum(r["words"] for r in rows)),
         "baseline_all_advisor": pct(sum(r["all_advisor"] for r in rows), m),
         "calls_below_50pct": sum(1 for r in rows if r["matched"] and r["correct"] / r["matched"] < 0.5)}
    ac = [r for r in rows if "oracle_correct" in r]
    if ac:
        s["oracle_acc_acoustic"] = pct(sum(r["oracle_correct"] for r in ac), sum(r["matched"] for r in ac))
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", type=Path, default=RUNS / "speakers")
    ap.add_argument("--transcripts", type=Path, default=RUNS / "s4t_0551_final/transcripts")
    ap.add_argument("--reference", type=Path, default=Path("artifacts/manifests/reference_transcripts.json"))
    ap.add_argument("--evaluation", type=Path, default=Path("artifacts/manifests/evaluation.json"))
    args = ap.parse_args()

    ref = json.loads(args.reference.read_text())["calls"]
    meta = json.loads(args.evaluation.read_text())["calls"]
    meta = meta if isinstance(meta, dict) else {c["call_id"]: c for c in meta}
    per_call = {}
    for p in sorted(args.pred.glob("call_*.json")):
        cid = p.stem
        if cid not in ref:
            continue
        asr = json.loads((args.transcripts / p.name).read_text())["segments"]
        per_call[cid] = score_call(asr, json.loads(p.read_text()), ref[cid])
        per_call[cid] |= {"split": meta.get(cid, {}).get("split"), "variant": meta.get(cid, {}).get("variant")}
    rows = list(per_call.values())
    groups = {"all": rows}
    for key in ("label_source", "split", "variant"):
        for v in sorted({str(r[key]) for r in rows}):
            groups[f"{key}={v}"] = [r for r in rows if str(r[key]) == v]
    summary = {g: summarise(rs) for g, rs in groups.items()}
    write_json_atomic(args.pred / "_eval.json", {"summary": summary, "per_call": per_call})
    cols = ("calls", "matched_acc", "filled_acc", "coverage", "baseline_all_advisor", "oracle_acc_acoustic",
            "calls_below_50pct")
    print(f"{'group':<28}" + "".join(f"{c:>22}" for c in cols))
    for g, s in summary.items():
        print(f"{g:<28}" + "".join(f"{str(s.get(c, '-')):>22}" for c in cols))


if __name__ == "__main__":
    main()
