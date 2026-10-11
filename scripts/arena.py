"""Model arena: the S4 direct-judge prompt on the ASR transcripts of the 62 case calls, one lane per model.

    SENTINEL_ALLOW_REMOTE_LLM=fictional_data_only python scripts/arena.py [--models ID ...] [--calls ID ...] [--workers 4]

Lanes:
- remote: every model on the OpenRouter open-weight allowlist (config/providers.yaml). The policy gate in
  pipeline/llm.py decides; a refusal stops the whole run (no fallback, no skip). The case calls are fictional, which
  is the only reason this lane exists. Production stays self-hosted.
- apertus-8b (self-hosted): the cached S4 results (artifacts/judge, artifacts/cache/judge); no network call.

Only call ids from artifacts/manifests/inference.json are accepted (exit 2 otherwise); transcripts come only from
artifacts/transcripts/<id>.json. There is no upload or file input.
Same prompt, schema and citation validator as production (pipeline.judge.judge_call). Cached in artifacts/arena/cache.
Labels are read only through pipeline.evaluate, after every prediction exists. Nothing is tuned (no thresholds),
so the holdout split is never tuned on.

Outputs (artifacts/arena/): runs/<slug>.json, leaderboard.json, duel_pool.json (no labels).
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import evaluate, judge, llm  # noqa: E402
from pipeline.io import write_json_atomic  # noqa: E402
from pipeline.llm import DiskCache, LLMError, ProviderNotPermitted, extraction_cache_key  # noqa: E402
from pipeline.schemas import Transcript  # noqa: E402

MANIFEST = REPO_ROOT / "artifacts" / "manifests" / "inference.json"
TRANSCRIPTS = REPO_ROOT / "artifacts" / "transcripts"
APERTUS_JUDGE_DIR = REPO_ROOT / "artifacts" / "judge"
APERTUS_CACHE = REPO_ROOT / "artifacts" / "cache" / "judge"
ARENA_DIR = REPO_ROOT / "artifacts" / "arena"
REMOTE_PROVIDER = "openrouter"
APERTUS = {"slug": "apertus-8b", "model": "swiss-ai/Apertus-v1.5-8B", "provider": "builder_pod", "self_hosted": True}


class CallRefused(ValueError):
    pass


def manifest_ids(path: Path = MANIFEST) -> list[str]:
    return [c["call_id"] for c in json.loads(path.read_text(encoding="utf-8"))["calls"]]


def check_calls(requested: list[str] | None, allowed: list[str]) -> list[str]:
    """Case-manifest calls only. Anything else (an upload, a typo, a path) is refused, never looked up."""
    if not requested:
        return list(allowed)
    bad = [c for c in requested if c not in set(allowed)]
    if bad:
        raise CallRefused(f"refused: not a case-manifest call: {bad}")
    return list(requested)


def transcript(cid: str) -> Transcript:
    return Transcript.from_dict(json.loads((TRANSCRIPTS / f"{cid}.json").read_text(encoding="utf-8")))


def slug(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", model.split("/")[-1].lower()).strip("-")


def remote_models() -> list[str]:
    _, specs = llm.load_providers()
    return list(specs[REMOTE_PROVIDER].allowed_models)


# --------------------------------------------------------------------------- lanes

def run_remote(model: str, ids: list[str], workers: int) -> dict:
    client = llm.get_client(REMOTE_PROVIDER, model)       # the gate; ProviderNotPermitted propagates and stops the run
    client.probe()
    cache = DiskCache(ARENA_DIR / "cache")

    def one(cid):
        try:
            r = judge.judge_call(transcript(cid), client=client, cache=cache)
        except ProviderNotPermitted:
            raise
        except (judge.JudgeError, LLMError) as e:
            print(f"  {model} {cid}: ERROR {str(e)[:120]}", flush=True)
            return cid, {"error": str(e)[:300]}
        return cid, {**r.to_dict(), "metrics": r.metrics, "cached": r.cached, "error": None}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        calls = dict(pool.map(one, ids))
    return {"slug": slug(model), "model": model, "provider": REMOTE_PROVIDER, "self_hosted": False,
            "revision": client.model_revision, "prompt_version": judge.PROMPT_VERSION_FULL, "calls": calls}


def run_apertus(ids: list[str]) -> dict:
    """Cached self-hosted S4 results; latency/tokens from the judge cache entry of the same transcript and prompt."""
    revision = None
    for p in APERTUS_CACHE.glob("*/*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("provider") == APERTUS["provider"] and d.get("prompt_version") == judge.PROMPT_VERSION_FULL:
            revision, model_id = d["revision"], d["model"]
            break
    cache = DiskCache(APERTUS_CACHE)
    calls = {}
    for cid in ids:
        p = APERTUS_JUDGE_DIR / f"{cid}.json"
        if not p.is_file():
            calls[cid] = {"error": "no cached self-hosted S4 result"}
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        metrics = []
        if revision and r.get("version") == judge.PROMPT_VERSION_FULL:
            segs = [{"id": s.id, "speaker": s.speaker, "text": s.text} for s in transcript(cid).segments]
            hit = cache.get(extraction_cache_key(segs, model_id, revision, judge.PROMPT_VERSION_FULL,
                                                 provider=APERTUS["provider"]))
            metrics = hit["metrics"] if hit else []
        calls[cid] = {**r, "metrics": metrics, "cached": True, "error": None}
    return {**APERTUS, "revision": revision, "prompt_version": judge.PROMPT_VERSION_FULL, "calls": calls}


# --------------------------------------------------------------------------- scoring

def _q(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 1)


def score_run(run: dict, ids: list[str]) -> dict:
    """Leaderboard row. Errors count as failures: risk 0 / no_alert for ranking, and they are reported."""
    calls = run["calls"]
    ok = {c: calls[c] for c in ids if c in calls and not calls[c].get("error")}
    errors = [c for c in ids if c not in ok]
    risk = {c: (ok[c]["risk"] if c in ok else 0.0) for c in ids}
    decisions = {c: (ok[c]["decision"] if c in ok else "no_alert") for c in ids}
    auc = evaluate.escalation_auc(risk)
    esc = evaluate.score_decisions(decisions)["all"]["escalation"]
    tpr = esc["tp"] / max(1, esc["tp"] + esc["fn"])
    tnr = esc["tn"] / max(1, esc["tn"] + esc["fp"])
    cites = [x for c in ok.values() for x in c.get("citations", [])]
    flagged = [c for c, d in ok.items() if d["decision"] != "no_alert"]
    no_valid = [c for c in flagged if not any(x.get("valid") for x in ok[c].get("citations", []))]
    walls = [m["wall_ms"] for c in ok.values() for m in c.get("metrics", [])[:1] if m.get("wall_ms") is not None]
    costs = [m["cost_usd"] for c in ok.values() for m in c.get("metrics", []) if m.get("cost_usd") is not None]
    return {
        "slug": run["slug"], "model": run["model"], "provider": run["provider"], "self_hosted": run["self_hosted"],
        "n": len(ids), "n_positive": auc["n_positive"], "errors": len(errors), "error_calls": errors,
        "auc": auc["auc"], "auc_ci95": auc["ci95"], "auc_by_split": auc["by_split"],
        "false_alarms": esc["fp"], "missed": esc["fn"], "tp": esc["tp"], "tn": esc["tn"],
        "balanced_accuracy": round((tpr + tnr) / 2, 4), "esc_precision": esc["precision"], "esc_recall": esc["recall"],
        "flagged": len(flagged),
        "citations_valid": sum(1 for x in cites if x.get("valid")), "citations_total": len(cites),
        "citation_validity": round(sum(1 for x in cites if x.get("valid")) / len(cites), 4) if cites else None,
        "flagged_without_valid_citation": len(no_valid),
        "latency_ms_median": round(statistics.median(walls), 1) if walls else None,
        "latency_ms_p90": _q(walls, 0.9), "latency_n": len(walls),
        "cost_usd": round(sum(costs), 4) if costs else None, "cost_calls": len(costs),
        "cost_note": "self-hosted: GPU time, no per-token cost" if run["self_hosted"] else "OpenRouter usage.cost",
    }


def duel_pool(runs: list[dict], ids: list[str]) -> dict:
    """Per call, each model's verdict and citations with the cited lines' text and time. No labels."""
    out = {}
    for cid in ids:
        segs = {s.id: s for s in transcript(cid).segments}
        verdicts = {}
        for run in runs:
            v = run["calls"].get(cid)
            if not v or v.get("error"):
                continue
            cites = []
            for x in v.get("citations", []):
                sid = (x.get("segment_ids") or [None])[0]
                s = segs.get(sid)
                cites.append({"segment_id": sid, "speaker": x.get("speaker"), "quote": x.get("quote"),
                              "valid": bool(x.get("valid")), "drop_reason": x.get("drop_reason"),
                              "text": s.text if s else None, "start_s": s.start_s if s else None,
                              "end_s": s.end_s if s else None})
            verdicts[run["slug"]] = {"decision": v["decision"], "risk": v["risk"], "criterion": v.get("criterion"),
                                     "reason": v.get("reason"), "citations": cites}
        out[cid] = verdicts
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="*", help="remote model ids (default: the whole OpenRouter allowlist)")
    ap.add_argument("--calls", nargs="*", help="case-manifest call ids (default: all)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-remote", action="store_true", help="score cached runs only, no network")
    a = ap.parse_args(argv)
    allowed = manifest_ids()
    try:
        ids = check_calls(a.calls, allowed)
    except CallRefused as e:
        print(e, file=sys.stderr)
        return 2
    models = a.models or remote_models()
    runs_dir = ARENA_DIR / "runs"
    runs = [run_apertus(ids)]
    for m in models:
        p = runs_dir / f"{slug(m)}.json"
        if a.no_remote:
            if p.is_file():
                runs.append(json.loads(p.read_text(encoding="utf-8")))
            continue
        t0 = time.time()
        print(f"{m}: judging {len(ids)} calls", flush=True)
        try:
            run = run_remote(m, ids, a.workers)
        except ProviderNotPermitted as e:
            print(f"REFUSED by policy gate, stopping (no workaround): {e}", file=sys.stderr)
            return 2
        write_json_atomic(p, run)
        print(f"{m}: done in {time.time() - t0:.0f}s, errors {sum(1 for v in run['calls'].values() if v.get('error'))}",
              flush=True)
        runs.append(run)
    write_json_atomic(runs_dir / "apertus-8b.json", runs[0])
    rows = sorted((score_run(r, ids) for r in runs), key=lambda r: -(r["auc"] or 0))
    write_json_atomic(ARENA_DIR / "leaderboard.json", {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "prompt_version": judge.PROMPT_VERSION_FULL,
        "n_calls": len(ids), "mode": "ASR transcripts, case calls (fictional)",
        "note": ("AUC vs gold escalation (alarm+review vs no_alert), dialogue-group bootstrap 95% CI; false alarms / "
                 "missed / balanced accuracy from each model's own decision (no threshold tuning); n is small"),
        "rows": rows})
    write_json_atomic(ARENA_DIR / "duel_pool.json", {"prompt_version": judge.PROMPT_VERSION_FULL,
                                                      "models": [r["slug"] for r in runs], "calls": duel_pool(runs, ids)})
    f = lambda x, d=2: "n/a" if x is None else f"{x:.{d}f}"
    print(f"\n{'model':38s} {'AUC [95% CI]':22s} {'FA':>3s} {'miss':>4s} {'bacc':>5s} {'cites ok':>9s} "
          f"{'p50 ms':>7s} {'cost $':>7s} err")
    for r in rows:
        print(f"{r['model'][:38]:38s} {f(r['auc'])} [{f(r['auc_ci95'][0])}, {f(r['auc_ci95'][1])}]{'':6s} "
              f"{r['false_alarms']:3d} {r['missed']:4d} {f(r['balanced_accuracy']):>5s} "
              f"{r['citations_valid']:3d}/{r['citations_total']:<4d} {f(r['latency_ms_median'], 0):>7s} "
              f"{f(r['cost_usd'], 3) if r['cost_usd'] is not None else 'self':>7s} {r['errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
