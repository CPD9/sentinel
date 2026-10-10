"""Milestone 4 driver: extract -> validate -> decide_call -> predictions -> pipeline.evaluate, on the DEV split only.

    # self-hosted (default provider apertus_aws, SSH tunnel on 127.0.0.1:8000)
    python scripts/run_extract.py --split dev --source reference
    # remote open-weight model, fictional data only (the gate refuses without the env var, set per shell)
    SENTINEL_ALLOW_REMOTE_LLM=fictional_data_only python scripts/run_extract.py --split dev --source reference \\
        --provider openrouter --model meta-llama/llama-3.3-70b-instruct

Holdout and test are refused. Rules and thresholds come from config/ untouched (untuned placeholders).
An extraction failure is recorded as StageError("extract") and the call becomes review, never no_alert.
Writes artifacts/predictions/<run_id>.json, artifacts/metrics/extract_<run_id>.json (extraction stats),
artifacts/traces_extract/<run_id>/<call_id>.json, then runs pipeline.evaluate on the predictions.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import decide as dec  # noqa: E402
from pipeline import evaluate  # noqa: E402
from pipeline import extract as ex  # noqa: E402
from pipeline import llm, stages  # noqa: E402
from pipeline.io import write_json_atomic  # noqa: E402
from pipeline.schemas import CallResult, RunResult, StageError, Transcript, Versions  # noqa: E402
from pipeline.validate import reason_key  # noqa: E402

SPLITS_FILE = REPO_ROOT / "artifacts" / "splits" / "dialogue_splits.json"
PRED_DIR = REPO_ROOT / "artifacts" / "predictions"
METRICS_DIR = REPO_ROOT / "artifacts" / "metrics"
TRACE_DIR = REPO_ROOT / "artifacts" / "traces_extract"
ASR_DIR = REPO_ROOT / "artifacts" / "transcripts"


def load_transcript(call_id: str, source: str) -> Transcript | None:
    if source == "reference":
        t, errs = stages.run_reference(call_id)
        if t is None:
            raise RuntimeError(errs[0].message)
        return t
    p = ASR_DIR / f"{call_id}.json"
    if not p.is_file():
        return None
    t = Transcript.from_dict(json.loads(p.read_text(encoding="utf-8")))
    return t if t.mode == "asr" else None


def mean(xs):
    return round(statistics.fmean(xs), 1) if xs else None


def summarise(per_call: list[dict]) -> dict:
    ok = [c for c in per_call if not c["failed"]]
    windows = [w for c in per_call for w in c["windows"]]
    live = [w for w in windows if not w["cached"]]
    drops = Counter(r for c in ok for r, n in c["drops"].items() for _ in range(n))
    n_facts = sum(c["n_facts"] for c in ok)
    ms = lambda ws: [m["wall_ms"] for w in ws for m in w["metrics"]]
    return {
        "calls": len(per_call), "calls_failed": len(per_call) - len(ok),
        "facts_total": n_facts, "facts_valid": sum(c["n_valid"] for c in ok),
        "facts_per_call_mean": round(n_facts / len(ok), 2) if ok else None,
        "drop_rate": round(sum(drops.values()) / n_facts, 3) if n_facts else None,
        "drops_by_reason": dict(drops),
        "windows": len(windows), "windows_cached": len(windows) - len(live),
        "windows_repaired": sum(w["repaired"] for w in windows),
        "json_repair_rate": round(sum(w["repaired"] for w in windows) / len(windows), 3) if windows else None,
        "json_failure_rate": round((len(per_call) - len(ok)) / len(per_call), 3) if per_call else None,
        "latency_ms_per_window_mean": mean([sum(m["wall_ms"] for m in w["metrics"]) for w in windows]),
        "latency_ms_per_call_mean": mean([c["wall_ms"] for c in ok]),
        "input_tokens_per_call_mean": mean([c["input_tokens"] for c in ok if c["input_tokens"] is not None]),
        "output_tokens_per_call_mean": mean([c["output_tokens"] for c in ok if c["output_tokens"] is not None]),
        "input_tokens_per_window_max": max((m["input_tokens"] for w in windows for m in w["metrics"]
                                            if m["input_tokens"] is not None), default=None),
        "cost_usd_total": round(sum(m["cost_usd"] for w in windows for m in w["metrics"] if m["cost_usd"] is not None), 5)
        if any(m["cost_usd"] is not None for w in windows for m in w["metrics"]) else None,
        "note": "latency/tokens of cached windows are the stored numbers of the original live request",
    }


def run(split: str, source: str, provider: str | None, model: str | None, limit: int | None) -> tuple[Path, dict]:
    call_ids = json.loads(SPLITS_FILE.read_text(encoding="utf-8"))["splits"][split]["call_ids"]
    client = llm.get_client(provider, model)
    client.probe()                           # fails loudly on a dead tunnel; resolves model id + revision
    info = client.version_info()
    config = dec.load_config()
    results, per_call = [], []
    selected = 0
    for cid in call_ids:
        if limit and selected >= limit:
            break
        t = load_transcript(cid, source)
        if t is None:
            print(f"{cid}: no stored {source} transcript, skipped")
            continue
        selected += 1
        report: list[dict] = []
        errors: list[StageError] = []
        try:
            facts = ex.extract_facts(t, client=client, report=report)
        except Exception as exc:
            facts, errors = None, [StageError("extract", f"{type(exc).__name__}: {exc}"[:500])]
        versions = Versions(asr=t.asr_model or "reference-transcript", llm=info["llm"], prompt=ex.PROMPT_VERSION_FULL,
                            provider=info["provider"], self_hosted=info["self_hosted"])
        trace, derrs = stages.run_decision(t, facts, None, config, errors, versions)
        errors += derrs
        if trace is None:
            res = CallResult(cid, "review", 0.0, None, narrative="decision failed; human review", stage_errors=errors,
                             versions=versions)
        else:
            write_json_atomic(TRACE_DIR / run_id(provider, client, source, split) / f"{cid}.json", trace.to_dict())
            res = CallResult(cid, trace.decision, trace.risk_score, trace.confidence,
                             findings=stages.build_findings(trace, t),
                             narrative="(M4 run: no narrative stage)", stage_errors=errors, versions=trace.versions)
        results.append(res)
        ms = [m for w in report for m in w["metrics"]]
        tok = lambda k: sum(m[k] or 0 for m in ms) if ms and all(m[k] is not None for m in ms) else None
        per_call.append({
            "call_id": cid, "failed": facts is None, "error": errors[0].message if errors else None,
            "n_facts": len(facts or []), "n_valid": sum(f.valid for f in facts or []),
            "drops": dict(Counter(reason_key(f.drop_reason) for f in facts or [] if not f.valid)),
            "windows": report, "wall_ms": sum(m["wall_ms"] for m in ms),
            "input_tokens": tok("input_tokens"), "output_tokens": tok("output_tokens"),
            "decision": res.decision, "decision_path": trace.decision_path if trace else None})
        print(f"{cid}: {res.decision:8s} facts={len(facts or [])} valid={per_call[-1]['n_valid']} "
              f"windows={len(report)}{' ERROR ' + errors[0].message[:100] if errors else ''}")

    rid = run_id(provider, client, source, split)
    label = f"{info['provider']} / {client.model} / self_hosted={info['self_hosted']}"
    rr = RunResult(
        run_id=rid, mode=source, system="pipeline_extract", provider=f"llm:{client.model}",
        created_at=datetime.now(timezone.utc).isoformat(), calls=results,
        notes=[f"M4 fact extraction: {label}", f"input: {source} transcripts, split={split}, n={len(results)}",
               "rules/thresholds untuned placeholders; no narrative, snippets or audio analysis in this run"])
    pred = PRED_DIR / f"{rid}.json"
    write_json_atomic(pred, rr.to_dict())
    stats = {"run_id": rid, "provider": info["provider"], "model": client.model, "revision": client.model_revision,
             "self_hosted": info["self_hosted"], "source": source, "split": split,
             "prompt_version": ex.PROMPT_VERSION_FULL, "summary": summarise(per_call), "per_call": per_call}
    write_json_atomic(METRICS_DIR / f"extract_{rid}.json", stats)
    return pred, stats


def run_id(provider, client, source, split) -> str:
    slug = re.sub(r"[^A-Za-z0-9.-]+", "-", client.model or "model")
    tag = "" if ex.PROMPT_VERSION == "extract-v1" else "_" + ex.PROMPT_VERSION.removeprefix("extract-")   # v1 ids stay as before
    return f"extract_{client.spec.name}_{slug}_{source}_{split}{tag}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=("dev",), default="dev", help="dev only; holdout and test are refused")
    ap.add_argument("--source", choices=("reference", "asr"), default="reference")
    ap.add_argument("--provider", help="name from config/providers.yaml (default: registry default)")
    ap.add_argument("--model", help="model id; remote providers need an allowlisted one")
    ap.add_argument("--prompt", choices=sorted(ex.PROMPTS), default="v2", help="prompt generation (default v2)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    try:
        ex.set_prompt(args.prompt)
        pred, stats = run(args.split, args.source, args.provider, args.model, args.limit)
    except llm.LLMError as e:
        print(f"LLM unavailable or refused: {e}", file=sys.stderr)
        return 2
    print("\n" + json.dumps(stats["summary"], indent=2))
    print(f"\nLabel: {stats['provider']} / {stats['model']} / self_hosted={stats['self_hosted']}, {args.source} "
          f"transcripts, dev n={stats['summary']['calls']}, untuned placeholders\n")
    return evaluate.main(["--pred", str(pred), "--split", args.split])


if __name__ == "__main__":
    sys.exit(main())
