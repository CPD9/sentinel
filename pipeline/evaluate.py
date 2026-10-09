"""Score a predictions file against the labels. The ONLY pipeline module that reads evaluation.json.

    python -m pipeline.evaluate --pred artifacts/predictions/<run>.json [--split dev]

Reports, always all three until the organizers confirm their convention:
  strict_alarm  precision/recall/F1 of `alarm` vs everything else
  escalation    precision/recall/F1 of `alarm`+`review` vs `no_alert`
  three_class   confusion matrix, per-class P/R/F1, macro F1, accuracy
each overall and broken down per Stufe, per variant (clean / noisy / unspecified) and per test target,
plus the evidence validity rate of flagged calls (alarm + review).

`reference_transcript(call_id)` also lives here: it looks a call's organizer script up through the
evaluation manifest and returns only the dialogue turns (segment_id, speaker, text) - never the label,
file name, Stufe or assessment. It is what "reference transcript mode" feeds to a system under test.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
import wave
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from pipeline.schemas import DECISIONS, RunResult

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_MANIFEST = REPO_ROOT / "artifacts" / "manifests" / "evaluation.json"
INFERENCE_MANIFEST = REPO_ROOT / "artifacts" / "manifests" / "inference.json"
SPLITS_FILE = REPO_ROOT / "artifacts" / "splits" / "dialogue_splits.json"
TRANSCRIPTS_DIR = REPO_ROOT / "artifacts" / "transcripts"
METRICS_DIR = REPO_ROOT / "artifacts" / "metrics"

QUOTE_MATCH_THRESHOLD = 0.85
FLAGGED = ("alarm", "review")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- reference transcripts

# Same two script formats as scripts/prepare_data.parse_turns (a test keeps them in sync).
_TURN_DOT_RE = re.compile(r"^(T\d{3}) · (\S+)$")          # "T001 · Beratung" + text lines
_TURN_INLINE_RE = re.compile(r"^(T\d{3}) ([A-Z]): (.*)$")  # "T001 B: text"
_ROLE = {"Beratung": "advisor", "B": "advisor", "Kundin": "customer", "Kunde": "customer", "K": "customer"}


def _parse_turns(text: str) -> list[dict]:
    turns: list[dict] = []
    for line in text.splitlines():
        line = line.rstrip()
        if m := _TURN_INLINE_RE.match(line):
            turns.append({"segment_id": m[1], "speaker": _ROLE.get(m[2], "unknown"), "text": m[3].strip()})
        elif m := _TURN_DOT_RE.match(line):
            turns.append({"segment_id": m[1], "speaker": _ROLE.get(m[2], "unknown"), "text": ""})
        elif line.strip() and turns:
            turns[-1]["text"] = (turns[-1]["text"] + " " + line.strip()).strip()
    return turns


def reference_transcript(call_id: str, eval_manifest: Path = EVAL_MANIFEST) -> list[dict]:
    """Label-free organizer script of one call: [{segment_id, speaker, text}]."""
    ev = _load(eval_manifest)
    dlg = ev["dialogues"][ev["calls"][call_id]["dialogue_id"]]
    turns = _parse_turns((REPO_ROOT / dlg["transcript_path"]).read_text(encoding="utf-8"))
    if not turns:
        raise ValueError(f"{call_id}: reference transcript has no turns")
    return [{"segment_id": t["segment_id"], "speaker": t["speaker"], "text": t["text"]} for t in turns]


# --------------------------------------------------------------------------- metrics

def _prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None   # None = undefined (no predicted positives)
    r = tp / (tp + fn) if tp + fn else None   # None = undefined (no gold positives)
    if tp:
        f1 = 2 * p * r / (p + r)
    else:
        f1 = 0.0 if fp + fn else None         # None = no positives anywhere
    return {"precision": p, "recall": r, "f1": f1}


def binary(gold: list[str], pred: list[str], positive: tuple[str, ...]) -> dict:
    g = [x in positive for x in gold]
    p = [x in positive for x in pred]
    tp = sum(a and b for a, b in zip(g, p))
    fp = sum(b and not a for a, b in zip(g, p))
    fn = sum(a and not b for a, b in zip(g, p))
    tn = len(g) - tp - fp - fn
    return {"positive": list(positive), "tp": tp, "fp": fp, "fn": fn, "tn": tn, **_prf(tp, fp, fn)}


def three_class(gold: list[str], pred: list[str]) -> dict:
    cm = {g: {p: 0 for p in DECISIONS} for g in DECISIONS}
    for g, p in zip(gold, pred):
        cm[g][p] += 1
    per_class, f1s = {}, []
    for c in DECISIONS:
        tp = cm[c][c]
        fp = sum(cm[g][c] for g in DECISIONS if g != c)
        fn = sum(cm[c][p] for p in DECISIONS if p != c)
        m = {**_prf(tp, fp, fn), "support": tp + fn}
        if tp + fp + fn == 0:   # class absent from gold and pred: excluded from macro F1
            m["f1"] = None
        per_class[c] = m
        if m["f1"] is not None:
            f1s.append(m["f1"])
    return {
        "labels": list(DECISIONS),
        "confusion": cm,               # rows = gold, columns = predicted
        "per_class": per_class,
        "macro_f1": sum(f1s) / len(f1s) if f1s else None,
        "macro_f1_classes": [c for c in DECISIONS if per_class[c]["f1"] is not None],
        "accuracy": sum(g == p for g, p in zip(gold, pred)) / len(gold) if gold else None,
    }


def metric_block(gold: list[str], pred: list[str]) -> dict:
    return {
        "n": len(gold),
        "gold_counts": dict(Counter(gold)),
        "pred_counts": dict(Counter(pred)),
        "strict_alarm": binary(gold, pred, ("alarm",)),
        "escalation": binary(gold, pred, FLAGGED),
        "three_class": three_class(gold, pred),
    }


# --------------------------------------------------------------------------- evidence validity

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def quote_score(quote: str, source: str) -> float:
    """1.0 if the normalized quote is a substring, else the best fuzzy ratio over same-length windows."""
    q, s = _norm(quote), _norm(source)
    if not q:
        return 0.0
    if q in s:
        return 1.0
    qw, sw = q.split(), s.split()
    n = len(qw)
    if n > len(sw):
        return SequenceMatcher(None, q, s).ratio()
    return max(SequenceMatcher(None, q, " ".join(sw[i:i + n])).ratio() for i in range(len(sw) - n + 1))


def _snippet_playable(path: Path) -> bool | None:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as w:
                return w.getnframes() > 0
        except (wave.Error, EOFError):
            return False
    if shutil.which("ffprobe"):
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                            str(path)], capture_output=True, text=True)
        try:
            return r.returncode == 0 and float(r.stdout.strip()) > 0
        except ValueError:
            return False
    return None   # cannot check without ffprobe


def _segments_for(call_id: str, mode: str) -> dict[str, dict] | None:
    if mode == "reference":
        return {t["segment_id"]: t for t in reference_transcript(call_id)}
    p = TRANSCRIPTS_DIR / f"{call_id}.json"
    if not p.is_file():
        return None
    segs = _load(p).get("segments", [])
    return {str(s.get("id", s.get("segment_id"))): s for s in segs}


def check_evidence(ev: dict, segments: dict | None, mode: str, duration_s: float | None) -> dict:
    """Per-item checks. True/False = checked, None = not applicable or not checkable (see `skipped`)."""
    checks: dict[str, bool | None] = {}
    skipped: dict[str, str] = {}
    ids = ev["segment_ids"]
    if segments is None:
        for k in ("segment_refs", "quote_match", "speaker_match"):
            checks[k] = None
            skipped[k] = "no transcript available for this call"
    else:
        cited = [segments[i] for i in ids if i in segments]
        checks["segment_refs"] = bool(ids) and len(cited) == len(ids)
        src = " ".join(c.get("text", "") for c in cited)
        checks["quote_match"] = bool(cited) and quote_score(ev["text"], src) >= QUOTE_MATCH_THRESHOLD
        spk = {c.get("speaker", "unknown") for c in cited} - {"unknown"}
        checks["speaker_match"] = bool(cited) and (not spk or spk == {ev["speaker"]})
    if mode == "reference":
        for k in ("timestamps", "snippet_playable", "snippet_contains_speech"):
            checks[k] = None
            skipped[k] = "reference mode: scripts have no timestamps or audio snippets"
    else:
        s, e = ev.get("start_s"), ev.get("end_s")
        checks["timestamps"] = (s is not None and e is not None and 0 <= s < e
                                and (duration_s is None or e <= duration_s + 0.05))
        sp = ev.get("snippet_path")
        if not sp:
            checks["snippet_playable"] = False
        else:
            path = Path(sp) if Path(sp).is_absolute() else REPO_ROOT / sp
            checks["snippet_playable"] = _snippet_playable(path)
            if checks["snippet_playable"] is None:
                skipped["snippet_playable"] = "ffprobe not installed"
        checks["snippet_contains_speech"] = None
        skipped["snippet_contains_speech"] = "not implemented: needs ASR re-check of the cut snippet"
    applied = [k for k, v in checks.items() if v is not None]
    return {"checks": checks, "skipped": skipped, "valid": bool(applied) and all(checks[k] for k in applied)}


def evidence_validity(run: RunResult, labels: dict[str, dict], durations: dict[str, float]) -> dict:
    items, per_call = [], {}
    gold_overlap = []
    for c in run.calls:
        if c.decision not in FLAGGED:
            continue
        evs = [e.__dict__ for f in c.findings for e in f.evidence]
        segments = _segments_for(c.call_id, run.mode)
        results = [check_evidence(e, segments, run.mode, durations.get(c.call_id)) for e in evs]
        items += results
        per_call[c.call_id] = {"n_evidence": len(evs), "n_valid": sum(r["valid"] for r in results),
                               "failed_checks": sorted({k for r in results for k, v in r["checks"].items()
                                                        if v is False})}
        gold_ids = set(labels[c.call_id].get("evidence_turn_ids") or [])
        if run.mode == "reference" and labels[c.call_id]["label"] in FLAGGED and gold_ids:
            cited = {i for e in evs for i in e["segment_ids"]}
            gold_overlap.append(bool(cited & gold_ids))
    applied = sorted({k for r in items for k, v in r["checks"].items() if v is not None})
    skipped = sorted({f"{k}: {why}" for r in items for k, why in r["skipped"].items()})
    n_flagged = len(per_call)
    return {
        "definition": "evidence items of flagged calls (alarm+review) passing every applicable check",
        "checks_applied": applied,
        "checks_skipped": skipped,
        "n_items": len(items),
        "n_valid_items": sum(r["valid"] for r in items),
        "item_validity_rate": sum(r["valid"] for r in items) / len(items) if items else None,
        "per_check_pass_rate": {k: sum(1 for r in items if r["checks"].get(k)) /
                                sum(1 for r in items if r["checks"].get(k) is not None) for k in applied},
        "n_flagged_calls": n_flagged,
        "flagged_calls_without_evidence": sorted(k for k, v in per_call.items() if v["n_evidence"] == 0),
        "flagged_calls_with_valid_evidence_rate":
            sum(1 for v in per_call.values() if v["n_valid"] > 0) / n_flagged if n_flagged else None,
        "gold_passage_hit_rate": (sum(gold_overlap) / len(gold_overlap)) if gold_overlap else None,
        "gold_passage_hit_definition": ("reference mode, correctly-escalated calls: share where a cited "
                                        "segment is one of the organizers' supporting passages"),
        "per_call": per_call,
    }


# --------------------------------------------------------------------------- main

def _call_labels(ev: dict) -> dict[str, dict]:
    out = {}
    for cid, c in ev["calls"].items():
        d = ev["dialogues"][c["dialogue_id"]]
        out[cid] = {"label": c["label"], "stufe": c["stufe"], "variant": c["variant"], "split": c["split"],
                    "test_target": d.get("test_target") or "unspecified",
                    "evidence_turn_ids": d.get("evidence_turn_ids", [])}
    return out


def evaluate(pred_path: Path, split: str | None = None, eval_manifest: Path = EVAL_MANIFEST) -> dict:
    if not pred_path.is_file():
        raise SystemExit(f"no predictions at {pred_path}")
    run = RunResult.from_dict(_load(pred_path))      # predictions first, then labels
    labels = _call_labels(_load(eval_manifest))
    durations = {c["call_id"]: c["duration_s"] for c in _load(INFERENCE_MANIFEST)["calls"]}
    warnings = []

    unknown = [c.call_id for c in run.calls if c.call_id not in labels]
    if unknown:
        raise SystemExit(f"predictions for unknown call ids: {unknown}")
    calls = [c for c in run.calls if split is None or labels[c.call_id]["split"] == split]
    if split is not None:
        expected = set(_load(SPLITS_FILE)["splits"][split]["call_ids"])
        missing = sorted(expected - {c.call_id for c in calls})
        if missing:
            warnings.append(f"{len(missing)} {split} calls have no prediction and are NOT scored: {missing}")
    if not calls:
        raise SystemExit("no predictions to score")
    splits_present = dict(Counter(labels[c.call_id]["split"] for c in calls))
    if "test" in splits_present:
        warnings.append("predictions include the locked test split")
    errored = [c.call_id for c in calls if c.stage_errors]
    if errored:
        warnings.append(f"{len(errored)} calls have stage errors (scored as predicted): {errored}")
    if run.mode == "reference":
        warnings.append("reference mode: clean and noisy recordings of a dialogue get the same script, "
                        "so the clean/noisy breakdown says nothing about audio robustness")

    gold = [labels[c.call_id]["label"] for c in calls]
    pred = [c.decision for c in calls]
    breakdowns = {}
    for key in ("stufe", "variant", "test_target"):
        groups = defaultdict(list)
        for i, c in enumerate(calls):
            groups[str(labels[c.call_id][key])].append(i)
        breakdowns[key] = {g: metric_block([gold[i] for i in idx], [pred[i] for i in idx])
                           for g, idx in sorted(groups.items())}
    mode_run = RunResult(**{**run.__dict__, "calls": calls})
    return {
        "pred_file": str(pred_path),
        "run_id": run.run_id, "system": run.system, "provider": run.provider, "mode": run.mode,
        "split_filter": split, "splits_present": splits_present,
        "run_notes": run.notes, "warnings": warnings,
        "overall": metric_block(gold, pred),
        "breakdown": breakdowns,
        "evidence_validity": evidence_validity(mode_run, labels, durations),
        "per_call": [{"call_id": c.call_id, "gold": labels[c.call_id]["label"], "pred": c.decision,
                      "stufe": labels[c.call_id]["stufe"], "variant": labels[c.call_id]["variant"],
                      "test_target": labels[c.call_id]["test_target"],
                      "criteria": [f.criterion for f in c.findings],
                      "stage_errors": [e.stage for e in c.stage_errors]} for c in calls],
    }


def _f(x) -> str:
    return "  n/a" if x is None else f"{x:5.2f}"


def format_report(m: dict) -> str:
    o = m["overall"]
    lines = [f"run {m['run_id']}  system={m['system']}  provider={m['provider']}  mode={m['mode']}",
             f"split filter: {m['split_filter']}  splits present: {m['splits_present']}  n={o['n']}"]
    lines += [f"WARNING: {w}" for w in m["warnings"]]
    lines.append("")
    lines.append(f"{'group':24s} {'n':>3s} | {'alarm P':>7s} {'R':>5s} {'F1':>5s} | "
                 f"{'esc P':>5s} {'R':>5s} {'F1':>5s} | {'macroF1':>7s} {'acc':>5s}")

    def row(name, b):
        s, e, t = b["strict_alarm"], b["escalation"], b["three_class"]
        return (f"{name:24s} {b['n']:3d} | {_f(s['precision']):>7s} {_f(s['recall'])} {_f(s['f1'])} | "
                f"{_f(e['precision'])} {_f(e['recall'])} {_f(e['f1'])} | {_f(t['macro_f1']):>7s} "
                f"{_f(t['accuracy'])}")
    lines.append(row("overall", o))
    for key, groups in m["breakdown"].items():
        for g, b in groups.items():
            lines.append(row(f"{key}={g}", b))
    cm = o["three_class"]["confusion"]
    lines += ["", "confusion (rows gold, cols pred): " + "  ".join(f"{p:>8s}" for p in DECISIONS)]
    lines += [f"{g:>33s}: " + "  ".join(f"{cm[g][p]:8d}" for p in DECISIONS) for g in DECISIONS]
    ev = m["evidence_validity"]
    lines += ["", f"evidence validity: {ev['n_valid_items']}/{ev['n_items']} items "
                  f"({_f(ev['item_validity_rate']).strip()}), checks applied {ev['checks_applied']}",
              f"  per check: { {k: round(v, 3) for k, v in ev['per_check_pass_rate'].items()} }",
              f"  flagged calls with >=1 valid evidence: {_f(ev['flagged_calls_with_valid_evidence_rate']).strip()}"
              f" of {ev['n_flagged_calls']}; without evidence: {ev['flagged_calls_without_evidence']}",
              f"  gold passage hit rate: {_f(ev['gold_passage_hit_rate']).strip()}"]
    lines += [f"  skipped: {s}" for s in ev["checks_skipped"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pred", type=Path, required=True)
    ap.add_argument("--split", choices=("dev", "holdout", "test"), default=None)
    ap.add_argument("--out", type=Path, default=None, help="metrics JSON (default artifacts/metrics/<run>.json)")
    args = ap.parse_args(argv)
    m = evaluate(args.pred, args.split)
    suffix = f"_{args.split}" if args.split and not m["run_id"].endswith(f"_{args.split}") else ""
    out = args.out or METRICS_DIR / f"{m['run_id']}{suffix}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(format_report(m))
    print(f"\nmetrics written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
